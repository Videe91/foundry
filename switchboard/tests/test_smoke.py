"""Packet: P-005 — Anthropic Polish (R-020 wiring guard).

One job: test the smoke script's ping and prove logic offline, with fakes,
including the R-020 wiring guard — that each phase actually passes system
blocks, attachments, effort, the meter, and stream options through to
route_call, and that main() runs end to end.

No network, no keys, no dotenv import. Chunk and usage shapes mirror the real
API per R-019: with stream_options the terminal chunk carries usage and EMPTY
choices.

Version: 0.5.0
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import FREE, FakeCompletion

import smoke
from smoke import (
    EXCLUDED_FROM_PROVE,
    SMOKE_DEPARTMENT,
    SMOKE_PROJECT,
    ping_model,
    ping_registry,
    prove_attachments,
    prove_cache,
    prove_roles,
    prove_streaming,
    unique_models,
)
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute, load_registry

SHARED = "anthropic/claude-haiku-4-5-20251001"
SONNET = "anthropic/claude-sonnet-5"

SMOKE_REGISTRY = ModelRegistry(
    roles={
        "architect": RoleRoute(
            model=SONNET, fallbacks=[SHARED], max_tokens=128000, effort="xhigh"
        ),
        "architect_max": RoleRoute(
            model="anthropic/claude-fable-5", fallbacks=[SONNET], max_tokens=128000
        ),
        "judge": RoleRoute(model=SONNET, fallbacks=[SHARED], max_tokens=128000),
        "floor_agent": RoleRoute(model=SHARED, fallbacks=[SONNET], max_tokens=64000),
        "default": RoleRoute(model=SHARED, fallbacks=[], max_tokens=64000),
    }
)


def test_ping_model_reports_ok() -> None:
    result = ping_model(SHARED, FakeCompletion())
    assert result.ok is True
    assert result.model == SHARED
    assert result.error is None


def test_ping_model_reports_failure_without_raising() -> None:
    result = ping_model(SHARED, FakeCompletion(failing=(SHARED,)))
    assert result.ok is False
    assert "unavailable" in result.error


def test_ping_uses_a_minimal_call() -> None:
    fake = FakeCompletion()
    ping_model(SHARED, fake)
    assert fake.calls[0]["max_tokens"] == 8


def test_unique_models_deduplicates_across_roles() -> None:
    models = unique_models(SMOKE_REGISTRY)
    assert sorted(models) == sorted({SHARED, SONNET, "anthropic/claude-fable-5"})


def test_ping_registry_pings_each_model_exactly_once() -> None:
    fake = FakeCompletion()
    results = ping_registry(SMOKE_REGISTRY, fake)
    assert len(fake.calls) == 3
    assert len(results) == 3
    assert all(result.ok for result in results)


def test_prove_roles_skips_default_and_the_escalation_tier(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    responses = prove_roles(SMOKE_REGISTRY, ledger, FakeCompletion(), FREE)
    proven = [response.tags.role for response in responses]
    assert proven == ["architect", "judge", "floor_agent"]
    assert all(role not in proven for role in EXCLUDED_FROM_PROVE)


def test_prove_roles_writes_one_meter_record_per_proven_role(
    tmp_path: Path,
) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    prove_roles(SMOKE_REGISTRY, ledger, FakeCompletion(), FREE)
    lines = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    records = [json.loads(line) for line in lines]
    assert [record["tags"]["role"] for record in records] == [
        "architect",
        "judge",
        "floor_agent",
    ]
    assert all(
        record["tags"]["project_id"] == SMOKE_PROJECT
        and record["tags"]["department"] == SMOKE_DEPARTMENT
        for record in records
    )


# --- R-020 wiring guard ---------------------------------------------------
#
# Unit tests of smoke's parts all passed while smoke.py would not start
# (the load_env defect). These assert the phases are actually wired.


def _usage(prompt: int = 40, completion: int = 6) -> SimpleNamespace:
    """Usage shape LiteLLM builds for Anthropic (R-019, T-002 diagnosis)."""
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0, cache_creation_tokens=0),
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


class SmokeFake:
    """Records every kwarg; streams when asked, per the real API shape."""

    def __init__(self, deltas: tuple[str, ...] = ("1\n", "2\n")) -> None:
        self.deltas = deltas
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if kwargs.get("stream"):
            return self._stream()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=_usage(),
        )

    def _stream(self) -> Any:
        for delta in self.deltas:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=delta))]
            )
        # R-019: with stream_options the terminal chunk has EMPTY choices.
        yield SimpleNamespace(choices=[], usage=_usage())


@pytest.fixture
def stub_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake litellm so no provider library is imported at all."""
    module = types.ModuleType("litellm")
    module.completion = lambda **_k: None
    module.completion_cost = lambda *_a, **_k: 0.0
    module.token_counter = lambda **_k: 4142
    monkeypatch.setitem(sys.modules, "litellm", module)


def _messages(fake: SmokeFake, index: int = 0) -> list[dict]:
    return fake.calls[index]["messages"]


def test_prove_roles_passes_the_system_block_through(tmp_path: Path) -> None:
    fake = SmokeFake()
    prove_roles(SMOKE_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), fake, FREE)
    system = _messages(fake)[0]
    assert system["role"] == "system"
    assert "FOUNDRY ONLINE" in system["content"][-1]["text"]


def test_prove_roles_passes_the_configured_effort_through(tmp_path: Path) -> None:
    fake = SmokeFake()
    prove_roles(SMOKE_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), fake, FREE)
    assert fake.calls[0]["reasoning_effort"] == "xhigh"


def test_prove_cache_passes_a_cache_marked_block_through(
    tmp_path: Path, stub_litellm: None
) -> None:
    fake = SmokeFake()
    prove_cache(SMOKE_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), "floor_agent", fake, FREE)
    system = _messages(fake)[0]
    assert system["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert len(fake.calls) == 2, "the cache demo must call twice"
    assert _messages(fake, 0) == _messages(fake, 1), "both calls must be identical"


def test_prove_attachments_passes_both_files_through(tmp_path: Path) -> None:
    fake = SmokeFake()
    prove_attachments(SMOKE_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), "floor_agent", fake, FREE)
    parts = _messages(fake)[-1]["content"]
    kinds = [part["type"] for part in parts]
    assert "image_url" in kinds and "file" in kinds


def test_prove_streaming_passes_stream_options_through(tmp_path: Path) -> None:
    fake = SmokeFake()
    prove_streaming(SMOKE_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), "judge", fake, FREE)
    call = fake.calls[0]
    assert call["stream"] is True
    assert call["stream_options"] == {"include_usage": True}


def test_every_prove_phase_writes_its_meter_records(
    tmp_path: Path, stub_litellm: None
) -> None:
    ledger = MeterLedger(tmp_path / "m.jsonl")
    prove_cache(SMOKE_REGISTRY, ledger, "floor_agent", SmokeFake(), FREE)
    prove_attachments(SMOKE_REGISTRY, ledger, "floor_agent", SmokeFake(), FREE)
    prove_streaming(SMOKE_REGISTRY, ledger, "judge", SmokeFake(), FREE)
    assert len(ledger.path.read_text(encoding="utf-8").strip().splitlines()) == 4


def test_smoke_exposes_every_symbol_main_uses() -> None:
    """The load_env defect: a deleted module-level name broke startup."""
    for name in (
        "load_env",
        "dump_usage",
        "ping_registry",
        "print_ping_table",
        "prove_roles",
        "prove_cache",
        "prove_attachments",
        "prove_streaming",
        "main",
    ):
        assert hasattr(smoke, name), f"smoke.{name} is missing"


def test_main_runs_every_phase_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The guard that would have caught the load_env defect.

    A fake litellm module is injected into sys.modules, so no provider library
    is imported and no call leaves the process.
    """
    fake = SmokeFake()
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = fake
    fake_litellm.completion_cost = lambda *_a, **_k: 0.0001
    fake_litellm.token_counter = lambda **_k: 4142
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    # setattr fails loudly if load_env has gone missing again — that is the point
    monkeypatch.setattr(smoke, "load_env", lambda: None)
    monkeypatch.setattr(smoke, "METER_PATH", tmp_path / "meter.jsonl")

    assert smoke.main() == 0

    out = capsys.readouterr().out
    for phase in ("=== PING ===", "PROVE 1", "PROVE 2", "PROVE 3", "PROVE 4"):
        assert phase in out, f"{phase} never ran"

    # Counts derive from the registry, never from hardcoded config values,
    # so a human editing registry.toml under R-012 cannot turn this red.
    registry = load_registry(smoke.REGISTRY_PATH)
    proven = [r for r in registry.roles if r not in EXCLUDED_FROM_PROVE]
    records = (tmp_path / "meter.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(records) == len(proven) + 4


def test_main_stops_at_a_ping_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A failed ping must return 1 and never reach the prove phases."""

    def refuse(**_kwargs: Any) -> Any:
        raise RuntimeError("model unavailable")

    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = refuse
    fake_litellm.completion_cost = lambda *_a, **_k: 0.0
    fake_litellm.token_counter = lambda **_k: 4142
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    monkeypatch.setattr(smoke, "load_env", lambda: None)
    monkeypatch.setattr(smoke, "METER_PATH", tmp_path / "meter.jsonl")

    assert smoke.main() == 1

    out = capsys.readouterr().out
    assert "PING FAILURES" in out
    assert "PROVE 1" not in out
    assert not (tmp_path / "meter.jsonl").exists()
