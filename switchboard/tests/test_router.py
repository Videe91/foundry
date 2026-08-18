"""Packet: P-005 — Anthropic Polish: Cache Fix + Streaming.

One job: test route_call — the tag gate, role resolution, family adapter
selection, the fallback chain, usage extraction, cost, and metering.
Shared fakes live in conftest.py (R-009). Fully offline.

Version: 0.5.0
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from datetime import timezone
from types import SimpleNamespace
from pathlib import Path

import pytest
from conftest import (
    ANTHROPIC_MODEL,
    ANTHROPIC_REGISTRY,
    FALLBACK,
    FREE,
    LAST_RESORT,
    PRIMARY,
    REGISTRY,
    FakeCompletion,
    fixed_cost,
    make_request,
    raising_cost,
)
from pydantic import ValidationError

from switchboard.meter import MeterLedger, MeterRecord
from switchboard.request import Attachment, Message, SwitchboardRequest
from switchboard.router import ProviderCallError, route_call
from switchboard.tags import CallTags, MissingTagsError

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_valid_call_returns_ok_with_model_and_content() -> None:
    fake = FakeCompletion(answer="pong")
    response = route_call(make_request(packet_id="P-004"), REGISTRY, fake, FREE)
    assert response.status == "ok"
    assert response.model_used == PRIMARY
    assert response.content == "pong"
    assert response.tags.project_id == "foundry"
    assert response.tags.packet_id == "P-004"


def test_response_carries_utc_timestamp() -> None:
    response = route_call(make_request(), REGISTRY, FakeCompletion(), FREE)
    assert response.received_at.tzinfo is not None
    assert response.received_at.utcoffset() == timezone.utc.utcoffset(None)


def test_primary_failure_falls_back_to_next_model() -> None:
    fake = FakeCompletion(answer="from the backup", failing=(PRIMARY,))
    response = route_call(make_request(), REGISTRY, fake, FREE)
    assert response.model_used == FALLBACK
    assert [call["model"] for call in fake.calls] == [PRIMARY, FALLBACK]


def test_all_models_failing_raises_provider_call_error_naming_each() -> None:
    fake = FakeCompletion(failing=(PRIMARY, FALLBACK, LAST_RESORT))
    with pytest.raises(ProviderCallError) as excinfo:
        route_call(make_request(), REGISTRY, fake, FREE)
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
        route_call(make_request(**override), REGISTRY, fake, FREE)
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
    route_call(request, REGISTRY, fake, FREE)
    call = fake.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "ping"},
    ]
    assert call["max_tokens"] == 4096


def test_unknown_role_routes_through_the_default_entry() -> None:
    fake = FakeCompletion()
    response = route_call(make_request(role="archivist"), REGISTRY, fake, FREE)
    assert response.model_used == "default/model-d"
    assert fake.calls[0]["max_tokens"] == 1024


def test_usage_and_cost_are_carried_on_the_response() -> None:
    fake = FakeCompletion(usage=(100, 50, 150))
    response = route_call(make_request(), REGISTRY, fake, fixed_cost(0.0042))
    assert response.usage.prompt_tokens == 100
    assert response.usage.completion_tokens == 50
    assert response.usage.total_tokens == 150
    assert response.usage.cost_usd == 0.0042


def test_response_without_usage_attribute_records_zeros() -> None:
    fake = FakeCompletion(usage=None)
    response = route_call(make_request(), REGISTRY, fake, lambda _c: None)
    assert response.status == "ok"
    assert response.usage.total_tokens == 0
    assert response.usage.cost_usd is None


def test_cost_fn_raising_leaves_cost_none_and_call_succeeds() -> None:
    fake = FakeCompletion(usage=(7, 3, 10))
    response = route_call(make_request(), REGISTRY, fake, raising_cost)
    assert response.status == "ok"
    assert response.usage.total_tokens == 10
    assert response.usage.cost_usd is None


def _litellm_shaped(prompt: int, cached: int, creation: int) -> object:
    """Usage shape LiteLLM builds for Anthropic (T-002): BOTH a nested
    prompt_tokens_details AND top-level cache_* fields. cached from the
    wrapper, creation from the top level."""
    usage = SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=20, total_tokens=prompt + 20,
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=cached, cache_creation_tokens=creation
        ),
        cache_creation_input_tokens=creation, cache_read_input_tokens=cached,
    )
    choice = SimpleNamespace(message=SimpleNamespace(content="ok"))
    return SimpleNamespace(choices=[choice], usage=usage)


def test_cache_write_is_read_from_the_real_litellm_shape() -> None:
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _litellm_shaped(3721, 0, 3721), FREE
    )
    assert response.usage.cache_creation_tokens == 3721
    assert response.usage.cached_tokens == 0


def test_cache_read_is_read_from_the_real_litellm_shape() -> None:
    response = route_call(
        make_request(), REGISTRY, lambda **_kw: _litellm_shaped(3721, 3721, 0), FREE
    )
    assert response.usage.cached_tokens == 3721
    assert response.usage.cache_creation_tokens == 0


def test_cache_token_fields_default_to_zero_when_absent() -> None:
    response = route_call(make_request(), REGISTRY, FakeCompletion(), FREE)
    assert response.usage.cached_tokens == 0
    assert response.usage.cache_creation_tokens == 0


def test_anthropic_request_reaches_the_provider_adapter_shaped(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pixel.png"
    path.write_bytes(PNG_BYTES)
    fake = FakeCompletion()
    request = make_request(
        system="stable instructions",
        attachments=[Attachment(kind="image", path=str(path))],
    )
    route_call(request, ANTHROPIC_REGISTRY, fake, FREE)
    messages = fake.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    parts = messages[-1]["content"]
    assert any(part["type"] == "image_url" for part in parts)


def test_non_adapter_family_refuses_attachments(tmp_path: Path) -> None:
    path = tmp_path / "pixel.png"
    path.write_bytes(PNG_BYTES)
    fake = FakeCompletion()
    request = make_request(attachments=[Attachment(kind="image", path=str(path))])
    with pytest.raises(ProviderCallError) as excinfo:
        route_call(request, REGISTRY, fake, FREE)
    assert "attachments" in str(excinfo.value)
    assert len(fake.calls) == 0


def test_non_adapter_family_prepends_system_as_a_plain_message() -> None:
    fake = FakeCompletion()
    route_call(make_request(system="be brief"), REGISTRY, fake, FREE)
    messages = fake.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "be brief"}
    assert messages[1]["content"] == "ping"


def test_meter_writes_one_record_matching_the_call(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    fake = FakeCompletion(usage=(100, 50, 150))
    route_call(
        make_request(packet_id="P-004"),
        REGISTRY,
        fake,
        fixed_cost(0.0042),
        ledger,
    )
    lines = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["model_used"] == PRIMARY
    assert entry["tags"]["packet_id"] == "P-004"
    assert entry["usage"]["total_tokens"] == 150


def test_no_meter_means_no_file_is_written(tmp_path: Path) -> None:
    response = route_call(make_request(), REGISTRY, FakeCompletion(), FREE, None)
    assert response.status == "ok"
    assert list(tmp_path.iterdir()) == []


def test_the_fallback_winner_is_the_metered_model(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    fake = FakeCompletion(failing=(PRIMARY,))
    route_call(make_request(), REGISTRY, fake, FREE, ledger)
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
        response = route_call(make_request(), REGISTRY, fake, FREE, ExplodingMeter())
    assert response.status == "ok"
    assert response.content == "still fine"


def test_failed_calls_are_not_metered(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    fake = FakeCompletion(failing=(PRIMARY, FALLBACK, LAST_RESORT))
    with pytest.raises(ProviderCallError):
        route_call(make_request(), REGISTRY, fake, FREE, ledger)
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
