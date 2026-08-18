"""Packet: R-028 — a fallback substitution must never be silent.

One job: test that the prove phases say out loud when a fallback answered
instead of the role's primary.

During the 2026-08-18 Opus-5 outage every `architect` call ran on Sonnet-5 —
correctly, and completely silently. Split from test_smoke_wiring.py under R-017
when it reached the ceiling; per R-026 the split inherits its parent's entries.

Version: 0.10.1
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FREE, FakeCompletion
from test_smoke_wiring import SHARED, SONNET, SmokeFake

from smoke import prove_roles
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute

# --- R-028: a fallback substitution must never be silent -------------------

FALLBACK_REGISTRY = ModelRegistry(roles={
    "architect": RoleRoute(model=SONNET, fallbacks=[SHARED], max_tokens=64000),
})


def test_a_fallback_substitution_is_announced_in_prove_1(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """During the Opus-5 outage every architect call ran on Sonnet-5 —
    correctly, and completely silently. The chain should absorb an outage; it
    should not hide which model did the work."""
    fake = FakeCompletion(failing=(SONNET,))
    prove_roles(FALLBACK_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), fake, FREE)
    out = capsys.readouterr().out
    assert "[fallback] architect" in out
    assert SONNET in out and SHARED in out


def test_no_note_is_printed_when_the_primary_answers(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Discriminating: a note on every call would be noise, not signal."""
    prove_roles(FALLBACK_REGISTRY, MeterLedger(tmp_path / "m.jsonl"), SmokeFake(), FREE)
    assert "[fallback]" not in capsys.readouterr().out
