"""Hidden 9P3 scientific contract: checkpoints, answer key, thresholds, selection (T1).

Locks the fifteen checkpoints C02..C16 with their transition classes, targets and
controls, the per-version current-meaning answer key, the exact-rational F/A token
difference, the spec §16.2 architecture-selection precedence (binding §16.4
examples, exhaustive predicate classification, ``errors_R`` irrelevance, rule 0
first) and the canonical expectations document. Nothing here is ever sent to a
model; no live call exists.
"""

from __future__ import annotations

import itertools
import json
import socket
from fractions import Fraction
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.experiments.long_horizon_bounded.expectations import (
    BASELINE_MEANINGS,
    CHECKPOINTS,
    CURRENT_MEANING_BY_T,
    DECISION_NAMES,
    SelectionInputs,
    expectations_document,
    select_architecture,
    token_diff_fa,
)
from foundry.experiments.long_horizon_bounded.timeline import EXPERIMENT_VERSION, LOCI


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def test_checkpoints_c02_to_c16_with_classes_and_targets() -> None:
    assert [c.id for c in CHECKPOINTS] == [f"C{t:02d}" for t in range(2, 17)]
    classes = {c.t: (c.transition_class, c.target_locus) for c in CHECKPOINTS}
    assert classes[2] == ("RESTATEMENT", "C")
    assert classes[3] == ("CORRECTION", "A")
    assert classes[4] == ("SEMANTIC_NO_OP", None)
    assert classes[8] == ("REVERT", "B")
    assert classes[9] == ("COMPATIBLE_EXTENSION", "H")
    assert classes[13] == ("RESTATEMENT", "K")
    assert {t for t, (k, _) in classes.items() if k == "CORRECTION"} == {3, 5, 7, 10, 12, 14, 16}
    for c in CHECKPOINTS:
        assert c.controls == tuple(locus for locus in LOCI if locus != c.target_locus)


def test_current_meaning_by_t_tracks_the_answer_key() -> None:
    # spec §4.13 verbatim ("3 total", not "three"): the spec outranks the plan's paraphrase
    assert BASELINE_MEANINGS["A"] == (
        "maximum 3 total execution attempts, initial attempt included"
    )
    assert "3 total" in BASELINE_MEANINGS["A"]
    assert CURRENT_MEANING_BY_T[1] == BASELINE_MEANINGS
    assert "4 total" in CURRENT_MEANING_BY_T[3]["A"]
    assert CURRENT_MEANING_BY_T[6]["A"] == CURRENT_MEANING_BY_T[3]["A"]
    assert "exponential" in CURRENT_MEANING_BY_T[5]["B"].lower()
    assert "fixed 5" in CURRENT_MEANING_BY_T[8]["B"]
    assert CURRENT_MEANING_BY_T[16]["I"] != CURRENT_MEANING_BY_T[15]["I"]


def test_token_diff_fa_is_symmetric_with_cheaper_denominator() -> None:
    assert token_diff_fa(100, 88) == Fraction(12, 88) == token_diff_fa(88, 100)
    assert token_diff_fa(100, 100) == 0


def _inputs(**kw: Any) -> SelectionInputs:
    # completed valid run with all-zero errors, bounded, economical by default
    base: dict[str, Any] = dict(
        completed=True,
        scientifically_valid=True,
        errors_F=0,
        errors_A=0,
        errors_R=0,
        integrity_F=True,
        integrity_A=True,
        f_total=100,
        a_total=100,
        r_total=200,
        f_early_mean="10/1",
        f_late_mean="11/1",
        a_early_mean="10/1",
        a_late_mean="11/1",
        r_early_mean="10/1",
        r_late_mean="16/1",
    )
    base.update(kw)
    return SelectionInputs(**base)


def test_binding_examples_from_spec_16_4() -> None:
    # ex 1
    assert select_architecture(_inputs(errors_F=1, a_total=103)).decision == "SELECT_A"
    assert (
        select_architecture(_inputs(errors_F=1, a_total=103, a_late_mean="20/1")).decision
        == "REDESIGN_PERSISTENT_CONTEXT"
    )
    # ex 2 (12 % cheaper)
    assert select_architecture(_inputs(a_total=88)).decision == "SELECT_A"
    # ex 3 (2 % cheaper)
    assert select_architecture(_inputs(f_total=98)).decision == "INCONCLUSIVE_TIE"
    # ex 4
    assert select_architecture(_inputs(errors_A=1, a_total=60, f_total=100)).decision == "SELECT_F"
    # ex 5
    assert (
        select_architecture(_inputs(f_total=190, a_total=190, r_late_mean="12/1")).decision
        == "SCALE_NOT_YET_PROVEN"
    )


def test_exhaustive_predicate_classification_and_errors_r_is_irrelevant() -> None:
    for acc_f, acc_a, b_f, b_a, e_f, e_a, rg in itertools.product([False, True], repeat=7):
        for f_total, a_total in ((100, 100), (100, 103), (103, 100), (100, 120), (120, 100)):
            inputs = _inputs(
                errors_F=0 if acc_f else 1,
                errors_A=0 if acc_a else 1,
                f_late_mean="11/1" if b_f else "20/1",
                a_late_mean="11/1" if b_a else "20/1",
                f_total=f_total if e_f else 200,
                a_total=a_total if e_a else 200,
                r_total=200,
                r_late_mean="16/1" if rg else "12/1",
            )
            out = select_architecture(inputs)
            assert out.decision in DECISION_NAMES and out.matched_rule != "residual"
            assert not (out.decision == "SELECT_F" and not acc_f)
            assert not (out.decision == "SELECT_A" and not acc_a)
            for r_err in (0, 3):
                updated = inputs.model_copy(update={"errors_R": r_err})
                assert select_architecture(updated).decision == out.decision


def test_invalid_or_incomplete_run_is_experiment_inconclusive_first() -> None:
    assert select_architecture(_inputs(completed=False)).decision == "EXPERIMENT_INCONCLUSIVE"
    outcome = select_architecture(_inputs(scientifically_valid=False, errors_F=1, errors_A=1))
    assert outcome.matched_rule == "0"


@pytest.mark.parametrize("bad", ["abc", "", "nan", "inf", "1/0", "-1/2", "0x10"])
def test_window_means_are_validated_at_construction_so_rule_0_never_raises(bad: str) -> None:
    # a malformed or negative window mean is refused by typed construction, so rule 0
    # (operational invalidity) can never be pre-empted by a ValueError/ZeroDivisionError
    with pytest.raises(ValidationError):
        _inputs(completed=False, f_early_mean=bad)
    # and a canonical non-negative rational on an INVALID run still resolves to rule 0 first
    assert select_architecture(_inputs(completed=False, f_early_mean="7/2")).matched_rule == "0"


def test_rule_3b_selects_the_bounded_arm_even_when_the_unbounded_arm_is_cheaper() -> None:
    out = select_architecture(_inputs(a_late_mean="20/1", a_total=50))
    assert (out.decision, out.matched_rule) == ("SELECT_F", "3B")
    out = select_architecture(_inputs(f_late_mean="20/1", f_total=50))
    assert (out.decision, out.matched_rule) == ("SELECT_A", "3B")
    out = select_architecture(_inputs(a_late_mean="20/1", f_total=200, r_late_mean="12/1"))
    assert (out.decision, out.matched_rule) == ("SCALE_NOT_YET_PROVEN", "3B")
    out = select_architecture(_inputs(a_late_mean="20/1", f_total=200))
    assert (out.decision, out.matched_rule) == ("EXPERIMENT_INCONCLUSIVE", "3B")


@pytest.mark.parametrize(
    ("overrides", "decision", "rule"),
    [
        (dict(errors_F=1, errors_A=1), "REDESIGN_PERSISTENT_CONTEXT", "1"),
        (dict(integrity_F=False, integrity_A=False), "REDESIGN_PERSISTENT_CONTEXT", "1"),
        (dict(errors_A=1, a_total=10), "SELECT_F", "2A"),  # A cheaper but out of contention
        (dict(errors_A=1, f_late_mean="20/1"), "REDESIGN_PERSISTENT_CONTEXT", "2B"),
        (dict(errors_A=1, f_total=200, r_late_mean="12/1"), "SCALE_NOT_YET_PROVEN", "2C"),
        (dict(errors_A=1, f_total=200), "EXPERIMENT_INCONCLUSIVE", "2C"),
        (dict(f_late_mean="20/1", a_late_mean="20/1"), "REDESIGN_PERSISTENT_CONTEXT", "3A"),
        (dict(a_late_mean="20/1", a_total=50), "SELECT_F", "3B"),  # bounded beats cheaper unbounded
        (dict(f_late_mean="20/1", f_total=50), "SELECT_A", "3B"),
        (dict(a_late_mean="20/1", f_total=200, r_late_mean="12/1"), "SCALE_NOT_YET_PROVEN", "3B"),
        (dict(a_late_mean="20/1", f_total=200), "EXPERIMENT_INCONCLUSIVE", "3B"),
        (dict(f_total=200, a_total=200, r_late_mean="12/1"), "SCALE_NOT_YET_PROVEN", "3C.a"),
        (dict(f_total=200, a_total=200), "EXPERIMENT_INCONCLUSIVE", "3C.a"),
        (dict(f_total=200, a_total=150), "SELECT_A", "3C.b"),
        (dict(f_total=150, a_total=200), "SELECT_F", "3C.b"),
        (dict(f_total=100, a_total=105), "SELECT_F", "3C.c"),  # exactly 5 % is meaningful
        (dict(f_total=105, a_total=100), "SELECT_A", "3C.c"),
        (dict(f_total=100, a_total=104), "INCONCLUSIVE_TIE", "3C.c"),
        (dict(f_total=100, a_total=100), "INCONCLUSIVE_TIE", "3C.c"),
        (
            dict(f_early_mean="100", f_late_mean="135", a_late_mean="20/1"),
            "SELECT_F",
            "3B",
        ),  # 1.35 inclusive
        (
            dict(f_early_mean="10000", f_late_mean="13501", a_late_mean="20/1"),
            "REDESIGN_PERSISTENT_CONTEXT",
            "3A",
        ),
        (dict(f_total=150, a_total=200, r_total=200), "SELECT_F", "3C.b"),  # 4F == 3R inclusive
        (dict(f_total=151, a_total=200, r_total=200), "EXPERIMENT_INCONCLUSIVE", "3C.a"),
        (
            dict(f_total=200, a_total=200, r_early_mean="10", r_late_mean="15"),
            "EXPERIMENT_INCONCLUSIVE",
            "3C.a",
        ),  # 1.5 inclusive
        (
            dict(f_total=200, a_total=200, r_early_mean="10", r_late_mean="149/10"),
            "SCALE_NOT_YET_PROVEN",
            "3C.a",
        ),
    ],
)
def test_every_16_2_rule_and_threshold_boundary_reports_its_matched_rule(
    overrides: dict[str, Any], decision: str, rule: str
) -> None:
    out = select_architecture(_inputs(**overrides))
    assert (out.decision, out.matched_rule) == (decision, rule)


def test_residual_records_the_unmatched_predicate_vector() -> None:
    out = select_architecture(_inputs(f_total=0, a_total=0, r_total=0))
    assert (out.decision, out.matched_rule) == ("EXPERIMENT_INCONCLUSIVE", "residual")
    assert tuple(out.predicates) == (
        "acceptable_F",
        "acceptable_A",
        "bounded_F",
        "bounded_A",
        "economy_F",
        "economy_A",
        "r_grows",
        "token_diff",
    )
    assert out.predicates["token_diff"] == "undefined"


def _mirror_key(key: str) -> str:
    if key.startswith("f_"):
        return "a_" + key[2:]
    if key.startswith("a_"):
        return "f_" + key[2:]
    if key.endswith("_F"):
        return key[:-2] + "_A"
    if key.endswith("_A"):
        return key[:-2] + "_F"
    return key


def test_selection_has_no_favoured_arm() -> None:
    swap = {"SELECT_F": "SELECT_A", "SELECT_A": "SELECT_F"}
    for acc_f, acc_a, b_f, b_a, e_f, e_a, rg in itertools.product([False, True], repeat=7):
        for ft, at in ((100, 100), (100, 103), (100, 105), (100, 120)):
            kw: dict[str, Any] = dict(
                errors_F=0 if acc_f else 1,
                errors_A=0 if acc_a else 1,
                f_late_mean="11/1" if b_f else "20/1",
                a_late_mean="11/1" if b_a else "20/1",
                f_total=ft if e_f else 200,
                a_total=at if e_a else 200,
                r_late_mean="16/1" if rg else "12/1",
            )
            mirrored = {_mirror_key(k): v for k, v in kw.items()}
            a, b = select_architecture(_inputs(**kw)), select_architecture(_inputs(**mirrored))
            assert (swap.get(a.decision, a.decision), a.matched_rule) == (
                b.decision,
                b.matched_rule,
            )


def test_expectations_document_is_canonical_and_free_of_runtime_ids() -> None:
    doc = expectations_document()
    assert doc["experiment_version"] == EXPERIMENT_VERSION
    assert doc["thresholds"]["bounded_factor"] == "27/20"
    assert "ADDR-" not in json.dumps(doc) and "CLAIM-" not in json.dumps(doc)
