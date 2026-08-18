"""Packet: P-009 — Family Four: xAI (Grok) Adapter.

One job: test the smoke script's ping and prove logic offline, with fakes.

The R-020 wiring guard lives in test_smoke_wiring.py — split out under R-018's
standing pre-authorization when this file reached the 300-line ceiling.

No network, no keys, no dotenv import.

Version: 0.9.2
"""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import pytest
from conftest import FREE, FakeCompletion

from smoke import (
    EXCLUDED_FROM_PROVE,
    SMOKE_DEPARTMENT,
    SMOKE_PROJECT,
    ping_model,
    ping_registry,
    print_ping_table,
    prove_roles,
    unique_models,
)
from smoke_fixtures import TINY_PNG_BASE64
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute

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


# --- P-007: family-aware smoke logic --------------------------------------





















def test_unpriced_model_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract 7: unpriced is a warning, not a gate."""
    fake = FakeCompletion()
    result = ping_model("vendor/not-a-real-model", fake)
    assert result.ok is True
    assert result.priced is False


def test_priced_model_is_recognised() -> None:
    assert ping_model("anthropic/claude-haiku-4-5-20251001", FakeCompletion()).priced


def test_ping_table_renders_the_pricing_warning(capsys: pytest.CaptureFixture) -> None:
    fake = FakeCompletion()
    print_ping_table(
        [ping_model("vendor/not-a-real-model", fake), ping_model(SHARED, fake)]
    )
    out = capsys.readouterr().out
    assert "UNPRICED — update litellm pin" in out
    assert "(priced)" in out






# --- T-006: the fixture image must clear the strictest family's minimum ----

# Each retired fixture fails a DIFFERENT clause of xAI's rule, which is what
# makes the guard below discriminating rather than decorative.
RETIRED_1X1_PNG = (  # fails the per-side minimum
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
RETIRED_16X16_PNG = (  # clears the sides, fails the 512-pixel total
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAAAAAA6mKC9AAAAGUlEQVR42mNgAIL/"
    "QIBMkypAqX4YGATuAADA/X+BdAueyAAAAABJRU5ErkJggg=="
)

# xAI's stated image minimums, both of them (T-006, R-027).
MIN_SIDE_PIXELS = 8
MIN_TOTAL_PIXELS = 512


def _png_dimensions(encoded: str) -> tuple[int, int]:
    """Width and height straight out of the PNG's IHDR chunk."""
    raw = base64.b64decode(encoded)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", raw[16:24])


def test_the_attachment_png_clears_every_stated_family_minimum() -> None:
    """xAI enforces two independent image minimums and reported them one at a
    time: each side >= 8 pixels, and >= 512 pixels in total.

    The first guard asserted only the per-side rule — the clause the first
    error message happened to name — so a 16x16 fixture passed the suite and
    was rejected live. Assert the whole rule, not the reported half.
    """
    width, height = _png_dimensions(TINY_PNG_BASE64)
    assert min(width, height) >= MIN_SIDE_PIXELS, f"{width}x{height}: side too small"
    assert width * height >= MIN_TOTAL_PIXELS, f"{width}x{height}: too few pixels"


def test_each_retired_fixture_fails_a_different_clause() -> None:
    """The guard cannot pass vacuously: both retired images are still checked,
    and each is rejected by the clause it actually violated in the live run."""
    w1, h1 = _png_dimensions(RETIRED_1X1_PNG)
    assert min(w1, h1) < MIN_SIDE_PIXELS

    w16, h16 = _png_dimensions(RETIRED_16X16_PNG)
    assert min(w16, h16) >= MIN_SIDE_PIXELS, "16x16 cleared the per-side rule"
    assert w16 * h16 < MIN_TOTAL_PIXELS, "and failed only on total pixels"
