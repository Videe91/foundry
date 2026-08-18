"""Packet: T-008 / R-028 — the ping gate tells outage from misconfiguration.

One job: test that the ping gate blocks on a CONFIG failure and warns-then-
proceeds on a provider capacity outage, naming each affected role and whether it
has a usable fallback.

The Opus-5 outage of 2026-08-18 blocked a nine-model sweep with the advice "fix
registry.toml" when there was nothing to fix. Split from test_smoke.py and
test_smoke_wiring.py under R-017 when both reached the ceiling; per R-026 the
split inherits their map entries.

Version: 0.10.2
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeCompletion
from test_smoke import SHARED, SMOKE_REGISTRY, SONNET
from test_smoke_wiring import SmokeFake

import smoke
from smoke import ping_model, print_ping_table, report_unavailable
from switchboard.registry import ModelRegistry, RoleRoute, load_registry


# --- T-008: a capacity outage is not a configuration error ------------------


class Down:
    """A provider that is up but cannot serve this model right now."""

    def __init__(self, message: str) -> None:
        self.message = message

    def __call__(self, **_kwargs: object) -> object:
        raise RuntimeError(self.message)


OVERLOADED = (
    'litellm.InternalServerError: AnthropicError - {"type":"error","error":'
    '{"type":"overloaded_error","message":"Overloaded"}}'
)

# Every one of these is a real defect this project actually hit. None may be
# excused as a transient outage — that is what makes the split meaningful.
CONFIG_FAILURES = [
    "litellm.BadRequestError: XaiException - Model not found: grok-4.1-fast",
    "Invalid file data: unsupported MIME type 'text/plain'",
    "Image has 256 total pixels (16x16), which is below the minimum of 512",
]


def test_a_capacity_outage_is_flagged_unavailable_not_failed() -> None:
    result = ping_model(SHARED, Down(OVERLOADED))
    assert result.ok is False
    assert result.unavailable is True


@pytest.mark.parametrize("message", CONFIG_FAILURES)
def test_the_discriminating_trio_stays_a_plain_failure(message: str) -> None:
    """T-004, T-006 and the bad model ID each needed a registry or code fix.
    If any of them read as UNAVAILABLE the gate would wave real defects through.
    """
    result = ping_model(SHARED, Down(message))
    assert result.ok is False
    assert result.unavailable is False


def test_a_healthy_ping_is_never_marked_unavailable() -> None:
    assert ping_model(SHARED, FakeCompletion()).unavailable is False


def test_the_table_labels_an_outage_as_capacity_not_config(
    capsys: pytest.CaptureFixture,
) -> None:
    print_ping_table([ping_model(SHARED, Down(OVERLOADED))])
    out = capsys.readouterr().out
    assert "UNAVAIL" in out
    assert "provider capacity, not config" in out
    assert "FAIL" not in out


def test_the_warning_names_the_affected_role_and_its_fallback(
    capsys: pytest.CaptureFixture,
) -> None:
    """Ruled under T-008: proceeding quietly is not acceptable — a role answered
    by its fallback is a different receipt from the one the registry describes.
    """
    registry = ModelRegistry(
        roles={"architect": RoleRoute(model=SONNET, fallbacks=[SHARED],
                                      max_tokens=64000)}
    )
    report_unavailable(registry, [
        ping_model(SONNET, Down(OVERLOADED)),
        ping_model(SHARED, FakeCompletion()),
    ])
    out = capsys.readouterr().out
    assert "1 model(s) unavailable" in out
    assert SONNET in out and "architect" in out
    assert f"will run on {SHARED}" in out


def test_the_warning_says_so_when_no_fallback_can_cover(
    capsys: pytest.CaptureFixture,
) -> None:
    registry = ModelRegistry(
        roles={"architect": RoleRoute(model=SONNET, fallbacks=[], max_tokens=64000)}
    )
    report_unavailable(registry, [ping_model(SONNET, Down(OVERLOADED))])
    out = capsys.readouterr().out
    assert "NO reachable fallback" in out


def test_nothing_is_printed_when_every_model_answers(
    capsys: pytest.CaptureFixture,
) -> None:
    """Discriminating: a warning on every run would be noise, not signal."""
    report_unavailable(SMOKE_REGISTRY, [ping_model(SHARED, FakeCompletion())])
    assert capsys.readouterr().out == ""


# --- T-008: the gate blocks on config, proceeds through an outage -----------

OVERLOADED = 'InternalServerError - {"type":"overloaded_error"}'


class GateFake(SmokeFake):
    """Fails one named model with a given error; serves everything else."""

    def __init__(self, model: str, message: str) -> None:
        super().__init__()
        self.down = model
        self.message = message

    def __call__(self, **kwargs: Any) -> Any:
        if kwargs["model"] == self.down:
            raise RuntimeError(self.message)
        return super().__call__(**kwargs)


def _gate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    module = types.ModuleType("litellm")
    module.completion = fake
    module.completion_cost = lambda *_a, **_k: 0.0001
    module.token_counter = lambda **_k: 4142
    monkeypatch.setitem(sys.modules, "litellm", module)
    monkeypatch.setattr(smoke, "load_env", lambda: None)
    monkeypatch.setattr(smoke, "METER_PATH", tmp_path / "meter.jsonl")
    monkeypatch.setattr(smoke, "MATRIX_PATH", tmp_path / "matrix-runs.md")


def test_a_config_failure_still_blocks_the_whole_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A model ID that does not exist is exactly what the gate is for."""
    registry = load_registry(smoke.REGISTRY_PATH)
    victim = next(iter(registry.roles.values())).model
    _gate_env(tmp_path, monkeypatch, GateFake(victim, "Model not found: nonesuch"))
    assert smoke.main([]) == 1
    out = capsys.readouterr().out
    assert "PING FAILURES — fix registry.toml" in out
    assert "PROVE 1" not in out


def test_an_outage_warns_and_the_run_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """T-008: eight healthy models should not wait on one overloaded provider."""
    registry = load_registry(smoke.REGISTRY_PATH)
    victim = next(iter(registry.roles.values())).model
    _gate_env(tmp_path, monkeypatch, GateFake(victim, OVERLOADED))
    assert smoke.main([]) == 0
    out = capsys.readouterr().out
    assert "UNAVAIL" in out
    assert "model(s) unavailable" in out
    assert "PING FAILURES" not in out
    for phase in ("PROVE 1", "PROVE 2", "PROVE 3", "PROVE 4"):
        assert phase in out, f"{phase} never ran"
