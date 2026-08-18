"""Packet: P-009.5 — The Model Matrix.

One job: the R-020 wiring guard — that each smoke phase actually passes system
blocks, attachments (all three kinds), effort, the meter, and stream options
through to route_call, and that main() runs end to end.

Split from test_smoke.py under R-018's standing pre-authorization when that
file reached the 300-line ceiling.

No network, no keys, no dotenv import. Shapes mirror the real API per R-019.

Version: 0.9.5
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
    prove_attachments,
    prove_cache,
    prove_families,
    prove_roles,
    prove_streaming,
)
from smoke_families import families_in, family_has_adapter
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


def test_prove_attachments_passes_all_three_files_through(tmp_path: Path) -> None:
    """P-006: the demo sends an image, a PDF, and a text document."""
    fake = SmokeFake()
    prove_attachments(SMOKE_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), "floor_agent", fake, FREE)
    parts = _messages(fake)[-1]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url", "file", "document"]
    pdf = next(part for part in parts if part["type"] == "file")
    assert pdf["file"]["file_data"].startswith("data:application/pdf;base64,")
    # T-003: the text kind rides a native document block, not a base64 URL.
    text_document = next(part for part in parts if part["type"] == "document")
    assert text_document["source"]["type"] == "text"
    assert text_document["source"]["media_type"] == "text/plain"


XAI_REGISTRY = ModelRegistry(roles={
    "floor_agent": RoleRoute(model="xai/grok-4.6", fallbacks=[], max_tokens=64000)
})


@pytest.mark.parametrize(
    ("registry", "sent"),
    [(SMOKE_REGISTRY, 3), (XAI_REGISTRY, 2)],
)
def test_prove_attachments_sends_only_the_kinds_the_family_accepts(
    tmp_path: Path, registry: ModelRegistry, sent: int
) -> None:
    """P-009 contract 4: a refused kind is announced, never crashed on."""
    fake = SmokeFake()
    prove_attachments(registry, MeterLedger(tmp_path / "m.jsonl"), "floor_agent", fake, FREE)
    parts = _messages(fake)[-1]["content"]
    assert parts[0]["text"].startswith(f"Name the {sent} file types")
    assert len(parts) == 1 + sent


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
    assert smoke.main([]) == 0
    out = capsys.readouterr().out
    for phase in ("=== PING ===", "PROVE 1", "PROVE 2", "PROVE 3", "PROVE 4"):
        assert phase in out, f"{phase} never ran"
    # Counts derive from the registry — including how many families it holds —
    # so a human editing registry.toml under R-012 cannot turn this red.
    registry = load_registry(smoke.REGISTRY_PATH)
    proven = [r for r in registry.roles if r not in EXCLUDED_FROM_PROVE]
    # Per family: two cache calls, one streaming call, plus an attachments
    # call when the family has an adapter. PROVE 4 is per-family since P-010
    # put every family on the streaming path.
    demos = sum(3 + int(family_has_adapter(registry, f)) for f in families_in(registry))
    records = (tmp_path / "meter.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(records) == len(proven) + demos


def _matrix_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SmokeFake:
    fake = SmokeFake()
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = fake
    fake_litellm.completion_cost = lambda *_a, **_k: 0.0001
    fake_litellm.token_counter = lambda **_k: 4142
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    monkeypatch.setattr(smoke, "load_env", lambda: None)
    monkeypatch.setattr(smoke, "METER_PATH", tmp_path / "meter.jsonl")
    monkeypatch.setattr(smoke, "MATRIX_PATH", tmp_path / "matrix-runs.md")
    return fake


def test_the_default_run_never_touches_the_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """P-009.5: --matrix is additive; the default run is unchanged."""
    _matrix_env(tmp_path, monkeypatch)
    assert smoke.main([]) == 0
    assert "=== MATRIX" not in capsys.readouterr().out
    assert not (tmp_path / "matrix-runs.md").exists()


def test_matrix_flag_sweeps_every_model_and_writes_the_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _matrix_env(tmp_path, monkeypatch)
    assert smoke.main(["--matrix"]) == 0
    out = capsys.readouterr().out
    assert "=== MATRIX" in out
    registry = load_registry(smoke.REGISTRY_PATH)
    for model in smoke.unique_models(registry):
        assert model in out, f"{model} missing from the grid"
    artifact = (tmp_path / "matrix-runs.md").read_text(encoding="utf-8")
    assert "# Matrix runs" in artifact
    # The PROVE phases belong to the default run and are skipped here.
    assert "PROVE 1" not in out


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
