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


def test_expectations_document_is_canonical_and_free_of_runtime_ids() -> None:
    doc = expectations_document()
    assert doc["experiment_version"] == EXPERIMENT_VERSION
    assert doc["thresholds"]["bounded_factor"] == "27/20"
    assert "ADDR-" not in json.dumps(doc) and "CLAIM-" not in json.dumps(doc)
