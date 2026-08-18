"""Packet: P-003 — Switchboard Meter.

One job: test route_call — the tag gate, role resolution, the fallback chain,
usage extraction, cost, and metering. Fully offline via injected fakes.

Version: 0.3.0
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from switchboard.meter import MeterLedger, MeterRecord
from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.request import Message, SwitchboardRequest
from switchboard.router import ProviderCallError, route_call
from switchboard.tags import CallTags, MissingTagsError

PRIMARY = "primary/model-a"
FALLBACK = "backup/model-b"
LAST_RESORT = "backup/model-c"
SRC_DIR = Path(__file__).resolve().parents[1] / "src"

REGISTRY = ModelRegistry(
    roles={
        "builder": RoleRoute(
            model=PRIMARY, fallbacks=[FALLBACK, LAST_RESORT], max_tokens=4096
        ),
        "default": RoleRoute(model="default/model-d", fallbacks=[], max_tokens=1024),
    }
)


def _provider_response(
    content: str, usage: tuple[int, int, int] | None
) -> SimpleNamespace:
    """Mimic the LiteLLM response shape; omit `usage` entirely when None."""
    payload = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    if usage is not None:
        payload.usage = SimpleNamespace(
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            total_tokens=usage[2],
        )
    return payload


class FakeCompletion:
    """Record every call received, and fail for the named models."""
    def __init__(
        self,
        answer: str = "an answer",
        failing: tuple[str, ...] = (),
        usage: tuple[int, int, int] | None = (10, 5, 15),
    ) -> None:
        self.answer = answer
        self.failing = failing
        self.usage = usage
        self.calls: list[dict[str, object]] = []
    def __call__(
        self, model: str, messages: list[dict[str, str]], max_tokens: int
    ) -> SimpleNamespace:
        self.calls.append(
            {"model": model, "messages": messages, "max_tokens": max_tokens}
        )
        if model in self.failing:
            raise RuntimeError(f"provider {model} is unavailable")
        return _provider_response(self.answer, self.usage)


def fixed_cost(value: float) -> Callable[[object], float]:
    def _cost_fn(_completion: object) -> float:
        return value
    return _cost_fn


def raising_cost(_completion: object) -> float:
    raise RuntimeError("cost lookup exploded")


FREE = fixed_cost(0.0)


def _request(**tag_values: object) -> SwitchboardRequest:
    tag_values.setdefault("project_id", "foundry")
    tag_values.setdefault("department", "floor")
    tag_values.setdefault("role", "builder")
    return SwitchboardRequest(
        tags=CallTags(**tag_values),
        messages=[Message(role="user", content="ping")],
    )


def test_valid_call_returns_ok_with_model_and_content() -> None:
    fake = FakeCompletion(answer="pong")
    response = route_call(_request(packet_id="P-003"), REGISTRY, fake, cost_fn=FREE)
    assert response.status == "ok"
    assert response.model_used == PRIMARY
    assert response.content == "pong"
    assert response.tags.project_id == "foundry"
    assert response.tags.packet_id == "P-003"
    assert response.tags.ticket_id is None


def test_response_carries_utc_timestamp() -> None:
    response = route_call(_request(), REGISTRY, FakeCompletion(), cost_fn=FREE)
    assert response.received_at.tzinfo is not None
    assert response.received_at.utcoffset() == timezone.utc.utcoffset(None)


def test_primary_failure_falls_back_to_next_model() -> None:
    fake = FakeCompletion(answer="from the backup", failing=(PRIMARY,))
    response = route_call(_request(), REGISTRY, fake, cost_fn=FREE)
    assert response.model_used == FALLBACK
    assert response.content == "from the backup"
    assert [call["model"] for call in fake.calls] == [PRIMARY, FALLBACK]


def test_all_models_failing_raises_provider_call_error_naming_each() -> None:
    fake = FakeCompletion(failing=(PRIMARY, FALLBACK, LAST_RESORT))
    with pytest.raises(ProviderCallError) as excinfo:
        route_call(_request(), REGISTRY, fake, cost_fn=FREE)
    message = str(excinfo.value)
    assert PRIMARY in message and FALLBACK in message and LAST_RESORT in message
    assert len(fake.calls) == 3


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"project_id": ""}, "project_id"),
        ({"role": ""}, "role"),
        ({"department": "marketing"}, "marketing"),
    ],
)
def test_bad_tags_block_the_call_before_any_provider_call(
    override: dict[str, str], expected: str
) -> None:
    fake = FakeCompletion()
    with pytest.raises(MissingTagsError) as excinfo:
        route_call(_request(**override), REGISTRY, fake, cost_fn=FREE)
    assert expected in str(excinfo.value)
    assert len(fake.calls) == 0


def test_empty_messages_list_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SwitchboardRequest(
            tags=CallTags(project_id="foundry", department="floor", role="builder"),
            messages=[],
        )


def test_completion_receives_plain_dicts_and_the_roles_max_tokens() -> None:
    fake = FakeCompletion()
    request = SwitchboardRequest(
        tags=CallTags(project_id="foundry", department="floor", role="builder"),
        messages=[
            Message(role="system", content="be brief"),
            Message(role="user", content="ping"),
        ],
    )
    route_call(request, REGISTRY, fake, cost_fn=FREE)
    call = fake.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "ping"},
    ]
    assert all(isinstance(item, dict) for item in call["messages"])
    assert call["max_tokens"] == 4096


def test_unknown_role_routes_through_the_default_entry() -> None:
    fake = FakeCompletion()
    response = route_call(_request(role="archivist"), REGISTRY, fake, cost_fn=FREE)
    assert response.model_used == "default/model-d"
    assert fake.calls[0]["max_tokens"] == 1024


def test_usage_and_cost_are_carried_on_the_response() -> None:
    fake = FakeCompletion(usage=(100, 50, 150))
    response = route_call(_request(), REGISTRY, fake, cost_fn=fixed_cost(0.0042))
    assert response.usage.prompt_tokens == 100
    assert response.usage.completion_tokens == 50
    assert response.usage.total_tokens == 150
    assert response.usage.cost_usd == 0.0042


def test_response_without_usage_attribute_records_zeros() -> None:
    fake = FakeCompletion(usage=None)
    response = route_call(_request(), REGISTRY, fake, cost_fn=lambda _c: None)
    assert response.status == "ok"
    assert response.usage.prompt_tokens == 0
    assert response.usage.completion_tokens == 0
    assert response.usage.total_tokens == 0
    assert response.usage.cost_usd is None


def test_cost_fn_raising_leaves_cost_none_and_call_succeeds() -> None:
    fake = FakeCompletion(usage=(7, 3, 10))
    response = route_call(_request(), REGISTRY, fake, cost_fn=raising_cost)
    assert response.status == "ok"
    assert response.usage.total_tokens == 10
    assert response.usage.cost_usd is None


def test_meter_writes_one_record_matching_the_call(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    fake = FakeCompletion(usage=(100, 50, 150))
    route_call(
        _request(packet_id="P-003"),
        REGISTRY,
        fake,
        cost_fn=fixed_cost(0.0042),
        meter=ledger,
    )
    lines = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["model_used"] == PRIMARY
    assert entry["tags"]["project_id"] == "foundry"
    assert entry["tags"]["packet_id"] == "P-003"
    assert entry["usage"]["total_tokens"] == 150
    assert entry["usage"]["cost_usd"] == 0.0042


def test_no_meter_means_no_file_is_written(tmp_path: Path) -> None:
    response = route_call(
        _request(), REGISTRY, FakeCompletion(), cost_fn=FREE, meter=None
    )
    assert response.status == "ok"
    assert list(tmp_path.iterdir()) == []


def test_the_fallback_winner_is_the_metered_model(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    fake = FakeCompletion(failing=(PRIMARY,))
    route_call(_request(), REGISTRY, fake, cost_fn=FREE, meter=ledger)
    restored = MeterRecord.model_validate_json(
        ledger.path.read_text(encoding="utf-8").strip()
    )
    assert restored.model_used == FALLBACK


def test_meter_write_failure_warns_but_returns_the_response() -> None:
    class ExplodingMeter:
        def record(self, _record: MeterRecord) -> None:
            raise OSError("disk full")
    fake = FakeCompletion(answer="still fine")
    with pytest.warns(RuntimeWarning, match="meter write failed"):
        response = route_call(
            _request(), REGISTRY, fake, cost_fn=FREE, meter=ExplodingMeter()
        )
    assert response.status == "ok"
    assert response.content == "still fine"


def test_failed_calls_are_not_metered(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    fake = FakeCompletion(failing=(PRIMARY, FALLBACK, LAST_RESORT))
    with pytest.raises(ProviderCallError):
        route_call(_request(), REGISTRY, fake, cost_fn=FREE, meter=ledger)
    assert not ledger.path.exists()


def test_importing_the_router_does_not_import_litellm() -> None:
    probe = (
        "import sys\n"
        "import switchboard.router\n"
        "sys.exit(1 if 'litellm' in sys.modules else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"litellm was imported at module level.\n{result.stderr}"
    )
