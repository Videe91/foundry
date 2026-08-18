"""Packet: P-009.5 + R-028 — The Model Matrix.

One job: test the matrix sweep offline — that it iterates every unique MODEL
rather than per-family roles, renders a refused kind as by-design, captures a
failure without aborting the sweep, and writes its artifact.

No network, no keys. Shapes mirror the real API per R-019.

Version: 0.10.1
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import FREE, fixed_cost

from smoke_matrix import (
    KINDS,
    OK,
    REFUSED,
    matrix_registry,
    render_matrix,
    run_matrix,
)
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute

SHARED = "anthropic/claude-haiku-4-5-20251001"
OPENAI = "openai/gpt-5.6-terra"
XAI = "xai/grok-4.6"
MISTRAL = "mistral/large"

# Two roles, five distinct models — SHARED appears twice, once as a primary and
# once as a fallback, so a matrix that iterated roles would over- or under-count.
SWEEP_REGISTRY = ModelRegistry(
    roles={
        "judge": RoleRoute(model=OPENAI, fallbacks=[SHARED], max_tokens=128000),
        "floor_agent": RoleRoute(model=SHARED, fallbacks=[XAI], max_tokens=64000),
        "scribe": RoleRoute(model=MISTRAL, fallbacks=[], max_tokens=8000),
    }
)
ALL_MODELS = [OPENAI, SHARED, XAI, MISTRAL]


class MatrixFake:
    """Records every call; fails only for the models it is told to fail."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.failing = failing
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if kwargs["model"] in self.failing:
            raise RuntimeError(f"provider {kwargs['model']} is unavailable")
        usage = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            prompt_tokens_details=SimpleNamespace(cached_tokens=64),
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=usage
        )
        if not kwargs.get("stream"):
            return response
        return self._stream(usage)

    def _stream(self, usage: Any) -> Any:
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))]
        )
        yield SimpleNamespace(choices=[], usage=usage)


def _sweep(tmp_path: Path, fake: MatrixFake, models: list[str] | None = None):
    return run_matrix(
        SWEEP_REGISTRY,
        models if models is not None else ALL_MODELS,
        MeterLedger(tmp_path / "m.jsonl"),
        tmp_path / "matrix-runs.md",
        fake,
        FREE,
    )


# --- it sweeps MODELS, not roles ------------------------------------------


def test_the_sweep_visits_every_unique_model_exactly_once(tmp_path: Path) -> None:
    rows = _sweep(tmp_path, MatrixFake())
    assert [row.model for row in rows] == ALL_MODELS


def test_every_call_is_pinned_to_the_row_model_with_no_fallbacks(
    tmp_path: Path,
) -> None:
    """A silent hand-off to another model would make the grid a liar."""
    fake = MatrixFake()
    _sweep(tmp_path, fake)
    assert {call["model"] for call in fake.calls} <= set(ALL_MODELS)
    for model in ALL_MODELS:
        assert matrix_registry(SWEEP_REGISTRY, model).resolve("matrix").fallbacks == []


def test_max_tokens_is_inherited_from_the_owning_role_not_invented() -> None:
    """A ceiling is a human decision under R-012 (the matrix picks none)."""
    assert matrix_registry(SWEEP_REGISTRY, OPENAI).resolve("matrix").max_tokens == 128000
    assert matrix_registry(SWEEP_REGISTRY, XAI).resolve("matrix").max_tokens == 64000
    assert matrix_registry(SWEEP_REGISTRY, MISTRAL).resolve("matrix").max_tokens == 8000


def test_no_effort_is_sent_so_a_family_ceiling_cannot_be_breached(
    tmp_path: Path,
) -> None:
    """R-025: a role's level inherited across families could exceed a ceiling
    and inject a failure that says nothing about attachments or caching."""
    fake = MatrixFake()
    _sweep(tmp_path, fake)
    assert all("reasoning_effort" not in call for call in fake.calls)


# --- refused by design is not a failure -----------------------------------


def test_xai_pdf_is_refused_by_design_and_costs_no_call(tmp_path: Path) -> None:
    fake = MatrixFake()
    rows = {row.model: row for row in _sweep(tmp_path, fake, [XAI])}
    cells = rows[XAI].cells
    assert cells["pdf"] == REFUSED
    assert (cells["image"], cells["text"]) == (OK, OK)
    # 2 attachment calls + 2 cache calls; the refused kind was never sent.
    assert len(fake.calls) == 4


def test_an_adapterless_family_refuses_every_kind_by_design(
    tmp_path: Path,
) -> None:
    fake = MatrixFake()
    rows = {row.model: row for row in _sweep(tmp_path, fake, [MISTRAL])}
    assert [rows[MISTRAL].cells[kind] for kind in KINDS] == [REFUSED] * 3
    assert len(fake.calls) == 2  # cache only


def test_a_full_adapter_family_attempts_all_three_kinds(tmp_path: Path) -> None:
    fake = MatrixFake()
    rows = {row.model: row for row in _sweep(tmp_path, fake, [SHARED])}
    assert [rows[SHARED].cells[kind] for kind in KINDS] == [OK] * 3
    assert len(fake.calls) == 5


# --- a failure is a cell, never a stop ------------------------------------


def test_one_models_failure_never_aborts_the_sweep(tmp_path: Path) -> None:
    """The whole point of a grid: the other rows still get measured."""
    fake = MatrixFake(failing=(OPENAI,))
    rows = {row.model: row for row in _sweep(tmp_path, fake)}
    assert len(rows) == len(ALL_MODELS)
    for kind in KINDS:
        assert rows[OPENAI].cells[kind].startswith("FAIL(")
    assert rows[OPENAI].cells["cache c1"].startswith("FAIL(")
    # every other model was still measured
    assert [rows[SHARED].cells[kind] for kind in KINDS] == [OK] * 3
    assert rows[XAI].cells["image"] == OK


def test_a_failure_cell_is_truncated_and_never_blank(tmp_path: Path) -> None:
    class Verbose(MatrixFake):
        def __call__(self, **kwargs: Any) -> Any:
            raise RuntimeError("x" * 500)

    rows = _sweep(tmp_path, Verbose(), [SHARED])
    cell = rows[0].cells["image"]
    assert cell.startswith("FAIL(") and cell.endswith(")")
    assert 0 < len(cell) < 200


# --- observed, never asserted ---------------------------------------------


def test_cache_cells_report_observed_values_rather_than_a_verdict(
    tmp_path: Path,
) -> None:
    """R-014: the instrument extends the open Gemini and xAI observations."""
    rows = _sweep(tmp_path, MatrixFake(), [SHARED])
    assert rows[0].cells["cache c1"] == "64/0"
    assert rows[0].cells["cache c2"] == "64/0"


def test_cost_accumulates_across_every_call_in_the_row(tmp_path: Path) -> None:
    rows = run_matrix(
        SWEEP_REGISTRY,
        [SHARED],
        MeterLedger(tmp_path / "m.jsonl"),
        tmp_path / "matrix-runs.md",
        MatrixFake(),
        fixed_cost(0.001),
    )
    assert rows[0].cost_usd == pytest.approx(0.005)  # 3 kinds + 2 cache calls


# --- the artifact ----------------------------------------------------------


def test_the_grid_is_written_to_the_artifact_and_appends(tmp_path: Path) -> None:
    path = tmp_path / "matrix-runs.md"
    _sweep(tmp_path, MatrixFake())
    first = path.read_text(encoding="utf-8")
    assert "# Matrix runs" in first
    for model in ALL_MODELS:
        assert model in first

    _sweep(tmp_path, MatrixFake())
    second = path.read_text(encoding="utf-8")
    assert second.startswith("# Matrix runs")
    assert second.count("```") == 4  # two fenced grids, appended not replaced


def test_the_grid_names_every_column_and_row(tmp_path: Path) -> None:
    rows = _sweep(tmp_path, MatrixFake())
    grid = render_matrix(rows)
    for column in ("model", *KINDS, "cache c1", "cache c2", "cost"):
        assert column in grid
    for model in ALL_MODELS:
        assert model in grid
    assert f"{len(ALL_MODELS)} models swept" in grid


def test_a_failure_becomes_a_marker_in_the_grid_and_a_footnote_below(
    tmp_path: Path,
) -> None:
    """The grid stays a grid: an 80-character error in a cell would set the
    width of every column, so the cell carries a marker and the text lives
    underneath. Nothing is lost — the row's own cell keeps the full string."""
    rows = _sweep(tmp_path, MatrixFake(failing=(OPENAI,)))
    grid = render_matrix(rows)
    assert "FAIL[1]" in grid
    assert "failures (5):" in grid
    assert "[1] openai/gpt-5.6-terra image: FAIL(" in grid
    # The wrapper naming the role is stripped; the provider's words survive.
    assert "all models failed for role" not in grid
    assert "is unavailable" in grid
    # No column is widened by the error text.
    header = grid.splitlines()[0]
    assert len(header) < 130


def test_a_clean_sweep_prints_no_failures_section(tmp_path: Path) -> None:
    grid = render_matrix(_sweep(tmp_path, MatrixFake()))
    assert "failures" not in grid
