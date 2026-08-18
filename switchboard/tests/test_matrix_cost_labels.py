"""Packet: P-010 — matrix cost labels: zero claims free, None means unknown.

One job: test that a cost cell the map cannot price renders "unpriced" rather
than 0.000000, and that a genuine zero still renders numerically.

Same class of defect as the Gemini cache note that printed "unknown" about a
family we understood precisely: a label that misstates what we know is worse
than a missing one. Here the misstatement runs the other way — 0.000000 asserts
a sweep was free when the truth is that nobody knows what it cost.

Split from test_smoke_matrix.py under R-017; per R-026 it inherits its parent's
map entries.

Version: 0.11.1
"""

from __future__ import annotations

from pathlib import Path

from smoke_matrix import UNPRICED_COST, render_matrix, run_matrix
from switchboard.meter import MeterLedger
from test_smoke_matrix import MISTRAL, SHARED, SWEEP_REGISTRY, XAI, MatrixFake, _sweep


# --- cost labels: zero claims free, None means unknown ---------------------


def _unpriced_sweep(tmp_path: Path, models: list[str]):
    """A cost function that cannot price the call — litellm's answer for the
    three openrouter models this project ships (the UNPRICED standing note)."""
    return run_matrix(
        SWEEP_REGISTRY,
        models,
        MeterLedger(tmp_path / "m.jsonl"),
        tmp_path / "matrix-runs.md",
        MatrixFake(),
        lambda _completion: None,
    )


def test_an_unpriced_model_renders_unpriced_not_zero(tmp_path: Path) -> None:
    """0.000000 asserts the sweep was free. It was not — we do not know."""
    row = _unpriced_sweep(tmp_path, [SHARED])[0]
    assert row.cells["cost"] == UNPRICED_COST
    assert "0.000000" not in row.cells["cost"]
    assert row.cost_known is False


def test_a_genuinely_zero_cost_still_renders_numerically(tmp_path: Path) -> None:
    """Discriminating: the fix must distinguish 0.0 from None, not blanket
    every cheap row as unpriced. A real 0.0 is knowledge, not absence."""
    rows = _sweep(tmp_path, MatrixFake(), [SHARED])  # conftest FREE = 0.0
    assert rows[0].cells["cost"] == "0.000000"
    assert rows[0].cost_known is True


def test_one_unknown_call_makes_the_whole_row_unknown(tmp_path: Path) -> None:
    """A total containing an unknown line item is not a total."""
    calls = {"n": 0}

    def sometimes(_completion: object) -> float | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else 0.5

    rows = run_matrix(
        SWEEP_REGISTRY, [SHARED], MeterLedger(tmp_path / "m.jsonl"),
        tmp_path / "matrix-runs.md", MatrixFake(), sometimes,
    )
    assert rows[0].cells["cost"] == UNPRICED_COST


def test_refused_and_failed_cells_still_cost_a_true_zero(tmp_path: Path) -> None:
    """No call was made, so nothing was spent — 0.000000 is TRUE here, and must
    not be swept into "unpriced" by an over-eager fix."""
    rows = _sweep(tmp_path, MatrixFake(), [MISTRAL])  # all kinds refused
    assert rows[0].cells["cost"] == "0.000000"
    assert rows[0].cost_known is True


def test_the_summary_line_admits_the_total_is_a_floor(tmp_path: Path) -> None:
    """A total that silently omits unpriced rows reads as the whole bill."""
    grid = render_matrix(_unpriced_sweep(tmp_path, [SHARED, XAI]))
    assert "unpriced" in grid
    assert "actual spend is higher" in grid


def test_a_fully_priced_sweep_says_nothing_extra(tmp_path: Path) -> None:
    """Discriminating: the caveat must not appear on every run."""
    grid = render_matrix(_sweep(tmp_path, MatrixFake()))
    assert "actual spend is higher" not in grid
