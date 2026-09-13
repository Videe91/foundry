"""Tests for the 9P3 measurement contract (T3 brief; spec §13–§14).

``measure_step`` pairs request records with adapter receipts strictly by position and
copies structural/economic facts verbatim; ``summarize`` totals the scientific window
(T2..T16) with exact rational means. Every record here is a real ``RequestRecord``
(the frozen 9P2 model, reused by import); every receipt is a tiny local fake carrying
only the five attributes the contract reads. Wording is opaque (``REQUEST_BODY_ALPHA``,
``ADDR-ALPHA``); nothing here resembles evidence text or an answer key. No reasoner
is constructed or called anywhere. ZERO live calls; sockets are blocked.
"""

from __future__ import annotations

import ast
import inspect
import json
import socket
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest

from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.long_horizon_bounded import measurements as measurements_module
from foundry.experiments.long_horizon_bounded.measurements import (
    CallMeasurement,
    MeasurementMismatch,
    TokenSummary,
    measure_step,
    summarize,
    window_mean,
)
from foundry.experiments.long_horizon_bounded.protocol import (
    EARLY_WINDOW,
    LATE_WINDOW,
    MEASURED_WINDOW,
    Arm,
)
from foundry.experiments.long_horizon_bounded.timeline import raw_evidence_character_count

PACKAGE_DIR = Path(measurements_module.__file__).resolve().parent
SHA_ALPHA = "a" * 64
SHA_BETA = "b" * 64
SHA_GAMMA = "c" * 64
ARMS: tuple[Arm, ...] = ("F", "A", "R")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- fakes ------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeReceipt:
    """The five adapter-economics attributes the measurement contract reads."""

    input_tokens: int
    output_tokens: int
    cost_usd: float
    wall_clock_ms: int
    invocation_id: str


class PoisonReceipt:
    """A receipt whose every attribute read is an error: proves nothing is read
    before the positional length check has passed."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"receipt attribute {name!r} was read before the length check")


def _record(
    arm: Arm,
    t: int,
    call_number: Literal[1, 2],
    *,
    rendered: str = "REQUEST_BODY_ALPHA",
    request_sha256: str = SHA_ALPHA,
    address_ids: tuple[str, ...] = (),
    claim_ids: tuple[str, ...] = (),
    comparison_context_chars: int = 0,
) -> RequestRecord:
    return RequestRecord(
        arm=arm,
        t=t,
        call_number=call_number,
        policy_version="POLICY_ALPHA",
        system_prompt_sha256=SHA_GAMMA,
        rendered_user_request=rendered,
        request_sha256=request_sha256,
        citable_evidence_ids=("EV-ALPHA",),
        historical_comparison_evidence_ids=(),
        known_address_ids=address_ids,
        known_claim_ids=claim_ids,
        allowed_judgment_kinds=("KIND_ALPHA",),
        comparison_context_chars=comparison_context_chars,
    )


def _receipt(invocation_id: str = "INV-ALPHA", *, input_tokens: int = 100) -> FakeReceipt:
    return FakeReceipt(
        input_tokens=input_tokens,
        output_tokens=7,
        cost_usd=0.0123,
        wall_clock_ms=4321,
        invocation_id=invocation_id,
    )


def _pair(arm: Arm, t: int) -> tuple[tuple[RequestRecord, ...], tuple[FakeReceipt, ...]]:
    records = (_record(arm, t, 1), _record(arm, t, 2))
    receipts = (_receipt("INV-ONE"), _receipt("INV-TWO"))
    return records, receipts


def _measurement(
    arm: Arm, t: int, call_number: Literal[1, 2], *, input_tokens: int
) -> CallMeasurement:
    return CallMeasurement(
        arm=arm,
        t=t,
        call_number=call_number,
        input_tokens=input_tokens,
        output_tokens=3,
        provider_cost_usd="0.01",
        wall_clock_ms=10,
        rendered_request_chars=18,
        known_address_count=0,
        known_claim_count=0,
        comparison_context_chars=0,
        r_cumulative_raw_evidence_chars=raw_evidence_character_count(t) if arm == "R" else None,
        request_sha256=SHA_ALPHA,
        invocation_id=f"INV-{arm}-{t:02d}-{call_number}",
    )


def _tokens(arm: Arm, t: int, call_number: int) -> int:
    """Deterministic, arm- and T-distinct input tokens; both calls differ."""
    base = {"F": 1000, "A": 2000, "R": 3000}[arm]
    return base + 10 * t + call_number


def _full_measurements(
    *, versions: tuple[int, ...] = tuple(range(1, 17))
) -> tuple[CallMeasurement, ...]:
    return tuple(
        _measurement(arm, t, call_number, input_tokens=_tokens(arm, t, call_number))
        for t in versions
        for arm in ARMS
        for call_number in (1, 2)
    )


# --- (1)–(5) positional pairing and exact field copy ------------------------------


def test_measure_step_pairs_record_i_with_receipt_i() -> None:
    records = (
        _record("F", 4, 1, request_sha256=SHA_ALPHA),
        _record("F", 4, 2, request_sha256=SHA_BETA),
    )
    receipts = (_receipt("INV-FIRST", input_tokens=11), _receipt("INV-SECOND", input_tokens=22))

    rows = measure_step(arm="F", t=4, records=records, receipts=receipts)

    assert len(rows) == 2
    assert (
        rows[0].call_number,
        rows[0].request_sha256,
        rows[0].invocation_id,
        rows[0].input_tokens,
    ) == (1, SHA_ALPHA, "INV-FIRST", 11)
    assert (
        rows[1].call_number,
        rows[1].request_sha256,
        rows[1].invocation_id,
        rows[1].input_tokens,
    ) == (2, SHA_BETA, "INV-SECOND", 22)

    swapped = measure_step(arm="F", t=4, records=records, receipts=(receipts[1], receipts[0]))
    assert swapped[0].invocation_id == "INV-SECOND"
    assert swapped[0].request_sha256 == SHA_ALPHA
    assert swapped[1].invocation_id == "INV-FIRST"


def test_measure_step_copies_every_field_exactly() -> None:
    record = _record(
        "F",
        6,
        2,
        rendered="REQUEST_BODY_BETA",
        request_sha256=SHA_BETA,
        address_ids=("ADDR-ALPHA", "ADDR-BETA"),
        claim_ids=("CLM-ALPHA",),
        comparison_context_chars=57,
    )
    receipt = FakeReceipt(
        input_tokens=1234,
        output_tokens=56,
        cost_usd=0.0789,
        wall_clock_ms=9876,
        invocation_id="INV-BETA",
    )

    (row,) = measure_step(arm="F", t=6, records=(record,), receipts=(receipt,))

    assert isinstance(row, CallMeasurement)
    assert row.arm == "F"
    assert row.t == 6
    assert row.call_number == 2
    assert row.input_tokens == 1234
    assert row.output_tokens == 56
    assert row.provider_cost_usd == "0.0789"
    assert Decimal(row.provider_cost_usd) == Decimal(str(receipt.cost_usd))
    assert row.wall_clock_ms == 9876
    assert row.rendered_request_chars == len("REQUEST_BODY_BETA")
    assert row.known_address_count == 2
    assert row.known_claim_count == 1
    assert row.comparison_context_chars == 57
    assert row.r_cumulative_raw_evidence_chars is None
    assert row.request_sha256 == SHA_BETA
    assert row.invocation_id == "INV-BETA"


def test_rendered_request_chars_is_the_rendered_length() -> None:
    rendered = "REQUEST_BODY_GAMMA " * 7
    (row,) = measure_step(
        arm="R", t=2, records=(_record("R", 2, 1, rendered=rendered),), receipts=(_receipt(),)
    )
    assert row.rendered_request_chars == len(rendered)


def test_known_address_count_is_the_address_id_count() -> None:
    (row,) = measure_step(
        arm="F",
        t=2,
        records=(_record("F", 2, 1, address_ids=("ADDR-ALPHA", "ADDR-BETA", "ADDR-GAMMA")),),
        receipts=(_receipt(),),
    )
    assert row.known_address_count == 3


def test_known_claim_count_is_the_claim_id_count() -> None:
    (row,) = measure_step(
        arm="F",
        t=2,
        records=(
            _record("F", 2, 1, claim_ids=("CLM-ALPHA", "CLM-BETA", "CLM-GAMMA", "CLM-DELTA")),
        ),
        receipts=(_receipt(),),
    )
    assert row.known_claim_count == 4


# --- (6) count mismatch fails closed, before any row ---------------------------------


@pytest.mark.parametrize("receipt_count", [0, 1, 3])
def test_record_receipt_count_mismatch_raises_with_no_partial_result(receipt_count: int) -> None:
    records = (_record("F", 3, 1), _record("F", 3, 2))
    receipts = tuple(PoisonReceipt() for _ in range(receipt_count))

    with pytest.raises(MeasurementMismatch):
        measure_step(arm="F", t=3, records=records, receipts=receipts)


def test_record_arm_or_t_disagreeing_with_the_step_raises() -> None:
    records, receipts = _pair("F", 3)
    with pytest.raises(MeasurementMismatch):
        measure_step(arm="A", t=3, records=records, receipts=receipts)
    with pytest.raises(MeasurementMismatch):
        measure_step(arm="F", t=4, records=records, receipts=receipts)


# --- (7)(8) Arm A comparison-context guard -------------------------------------------


def test_arm_a_record_with_nonzero_comparison_context_raises() -> None:
    records = (_record("A", 5, 1), _record("A", 5, 2, comparison_context_chars=1))
    with pytest.raises(MeasurementMismatch):
        measure_step(arm="A", t=5, records=records, receipts=(_receipt(), _receipt()))


def test_arm_a_record_with_zero_comparison_context_measures() -> None:
    records, receipts = _pair("A", 5)
    rows = measure_step(arm="A", t=5, records=records, receipts=receipts)
    assert [row.comparison_context_chars for row in rows] == [0, 0]


# --- (9)(10)(11) the R-only cumulative raw-evidence column ---------------------------


@pytest.mark.parametrize("t", [1, 2, 9, 16])
def test_arm_r_rows_carry_the_cumulative_raw_evidence_count(t: int) -> None:
    records, receipts = _pair("R", t)
    rows = measure_step(arm="R", t=t, records=records, receipts=receipts)
    assert [row.r_cumulative_raw_evidence_chars for row in rows] == [
        raw_evidence_character_count(t),
        raw_evidence_character_count(t),
    ]
    assert rows[0].r_cumulative_raw_evidence_chars is not None
    assert rows[0].r_cumulative_raw_evidence_chars > 0


@pytest.mark.parametrize("arm", ["F", "A"])
def test_arm_f_and_a_rows_carry_none_not_zero(arm: Arm) -> None:
    records, receipts = _pair(arm, 9)
    rows = measure_step(arm=arm, t=9, records=records, receipts=receipts)
    for row in rows:
        assert row.r_cumulative_raw_evidence_chars is None


@pytest.mark.parametrize("arm", ["F", "A"])
def test_arm_f_and_a_json_dump_serializes_null(arm: Arm) -> None:
    records, receipts = _pair(arm, 9)
    (row, _) = measure_step(arm=arm, t=9, records=records, receipts=receipts)

    dumped = row.model_dump(mode="json")
    assert "r_cumulative_raw_evidence_chars" in dumped
    assert dumped["r_cumulative_raw_evidence_chars"] is None
    assert json.loads(json.dumps(dumped))["r_cumulative_raw_evidence_chars"] is None
    assert '"r_cumulative_raw_evidence_chars": null' in json.dumps(dumped)


# --- (12)(13) summarize totals over the scientific window only -----------------------


def test_summarize_excludes_t1_from_totals_and_per_t() -> None:
    summary = summarize(_full_measurements())

    assert isinstance(summary, TokenSummary)
    for arm, total in (("F", summary.f_total), ("A", summary.a_total), ("R", summary.r_total)):
        expected = sum(_tokens(arm, t, c) for t in MEASURED_WINDOW for c in (1, 2))
        assert total == expected
        assert 1 not in summary.per_arm_per_t[arm]
        assert set(summary.per_arm_per_t[arm]) == set(MEASURED_WINDOW)
    assert set(summary.per_arm_per_t) == {"F", "A", "R"}


def test_summarize_sums_both_calls_per_arm_per_t() -> None:
    summary = summarize(_full_measurements())
    for arm in ARMS:
        for t in MEASURED_WINDOW:
            assert summary.per_arm_per_t[arm][t] == _tokens(arm, t, 1) + _tokens(arm, t, 2)


# --- (14)(15) exact rational early/late means -----------------------------------------


def _expected_mean(arm: Arm, window: tuple[int, ...]) -> Fraction:
    values = [_tokens(arm, t, 1) + _tokens(arm, t, 2) for t in window]
    return Fraction(sum(values), len(values))


def test_summarize_early_and_late_means_are_exact_fractions() -> None:
    summary = summarize(_full_measurements())

    assert Fraction(summary.f_early_mean) == _expected_mean("F", EARLY_WINDOW)
    assert Fraction(summary.f_late_mean) == _expected_mean("F", LATE_WINDOW)
    assert Fraction(summary.a_early_mean) == _expected_mean("A", EARLY_WINDOW)
    assert Fraction(summary.a_late_mean) == _expected_mean("A", LATE_WINDOW)
    assert Fraction(summary.r_early_mean) == _expected_mean("R", EARLY_WINDOW)
    assert Fraction(summary.r_late_mean) == _expected_mean("R", LATE_WINDOW)
    # The fixture's per-T totals are 2*base + 20*t + 3; over T2..T5 that averages
    # to exactly 2*base + 73 -- check one by literal value.
    assert Fraction(summary.f_early_mean) == Fraction(2 * 1000 + 73)


def test_mean_strings_round_trip_through_fraction() -> None:
    def tokens(arm: Arm, t: int, call_number: int) -> int:
        # Per-T totals of 25 (T2, T13) and 12 elsewhere: window sums of 61 over
        # four versions give the non-integer mean "61/4" in both windows.
        if t in (2, 13):
            return 13 if call_number == 1 else 12
        return 11 if call_number == 1 else 1

    rows = tuple(
        _measurement(arm, t, call_number, input_tokens=tokens(arm, t, call_number))
        for t in range(1, 17)
        for arm in ARMS
        for call_number in (1, 2)
    )
    summary = summarize(rows)

    for value in (
        summary.f_early_mean,
        summary.a_early_mean,
        summary.r_early_mean,
        summary.f_late_mean,
        summary.a_late_mean,
        summary.r_late_mean,
    ):
        assert isinstance(value, str)
        assert Fraction(value) == Fraction(61, 4)
        assert value == "61/4"
        assert value == str(Fraction(value))
        assert "." not in value


def test_window_mean_is_exact() -> None:
    assert window_mean((11, 12)) == Fraction(23, 2)
    assert str(window_mean((11, 12))) == "23/2"
    assert window_mean((11, 11, 11)) == Fraction(11)
    assert str(window_mean((11, 11, 11))) == "11"
    assert isinstance(window_mean(iter((1, 2))), Fraction)


# --- (16)(17)(18) refusals -------------------------------------------------------------


@pytest.mark.parametrize(("arm", "t"), [("F", 2), ("A", 9), ("R", 16)])
def test_summarize_refuses_a_missing_arm_t_pair(arm: Arm, t: int) -> None:
    rows = tuple(m for m in _full_measurements() if not (m.arm == arm and m.t == t))
    with pytest.raises(MeasurementMismatch):
        summarize(rows)


def test_summarize_refuses_a_missing_t1_free_window_gap_even_when_t1_present() -> None:
    rows = tuple(m for m in _full_measurements() if m.t != 10)
    with pytest.raises(MeasurementMismatch):
        summarize(rows)


def test_summarize_refuses_a_duplicate_call() -> None:
    full = _full_measurements()
    duplicate = next(m for m in full if m.arm == "A" and m.t == 7 and m.call_number == 1)
    with pytest.raises(MeasurementMismatch):
        summarize((*full, duplicate))
    with pytest.raises(MeasurementMismatch):
        summarize((*full, duplicate.model_copy(update={"input_tokens": 1})))


def test_summarize_refuses_a_single_call_t() -> None:
    rows = tuple(
        m for m in _full_measurements() if not (m.arm == "R" and m.t == 12 and m.call_number == 2)
    )
    with pytest.raises(MeasurementMismatch):
        summarize(rows)


def test_summarize_refuses_three_calls_at_one_t() -> None:
    full = _full_measurements()
    extra = _measurement("F", 3, 2, input_tokens=5).model_copy(update={"invocation_id": "INV-X"})
    with pytest.raises(MeasurementMismatch):
        summarize((*full, extra))


def test_window_mean_of_nothing_raises() -> None:
    with pytest.raises(ValueError):
        window_mean(())
    with pytest.raises(ValueError):
        window_mean(iter(()))


# --- (19)(20) reuse boundary and import law -------------------------------------------


def _import_froms(tree: ast.AST) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            out.setdefault(node.module, set()).update(alias.name for alias in node.names)
    return out


def test_measurements_reuses_records_by_import() -> None:
    tree = ast.parse(inspect.getsource(measurements_module))
    imports = _import_froms(tree)
    names = imports.get("foundry.experiments.contrastive_unseen.records", set())
    assert {"RequestRecord", "RecordingReasoner"} <= names


def test_measurements_never_imports_expectations() -> None:
    tree = ast.parse(inspect.getsource(measurements_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.endswith("expectations")
            assert "expectations" not in {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            assert not any(alias.name.endswith("expectations") for alias in node.names)


def test_package_never_redefines_reused_components() -> None:
    assert not (PACKAGE_DIR / "records.py").exists()
    assert not (PACKAGE_DIR / "ablation.py").exists()
    sources = sorted(PACKAGE_DIR.glob("*.py"))
    assert (PACKAGE_DIR / "measurements.py") in sources
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name != "RecordingReasoner", path
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                assert node.name != "assimilate_ablation_delta", path
