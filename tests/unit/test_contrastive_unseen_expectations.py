"""9P2 T1: scientific decision contract (spec §6, §10, §11, §13, §14.5).

Locks ``decision_rule`` exactly and the grading-only expectations document
(answer key, C1/C2/C3 rubric, F1-F8 integrity expectations, decision rule
text, leakage needle source material). This module is grading/preflight data
only; it is never sent to a model and must never be imported by
``timeline.py`` (checked in the timeline test module).
"""

from __future__ import annotations

import socket

import pytest
from pydantic import ValidationError

from foundry.experiments.contrastive_unseen.expectations import (
    ANSWER_KEY_SENTENCES,
    GRADING_LABELS,
    NORMALIZED_CONCLUSIONS,
    DecisionInputs,
    DecisionOutcome,
    IntegrityInputs,
    decision_rule,
    expectations_document,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _integrity(*, all_pass: bool = True, **overrides: bool) -> IntegrityInputs:
    values = {f"f{i}": all_pass for i in range(1, 9)}
    values.update(overrides)
    return IntegrityInputs(**values)


def test_grading_labels_are_locked() -> None:
    assert GRADING_LABELS == (
        "C1",
        "C2",
        "C3",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
        "F7",
        "F8",
        "F_SEMANTIC",
        "CAUSAL",
        "ECONOMY",
        "NO_WORSE_R",
        "INTEGRITY",
    )


def test_decision_pass_case() -> None:
    inputs = DecisionInputs(
        f_material_errors=0,
        a_material_errors=1,
        r_material_errors=1,
        f_input_tokens_t2_t4=75,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(),
    )
    outcome = decision_rule(inputs)
    assert outcome == DecisionOutcome(result="PASS", failing=(), note="")


def test_decision_inconclusive_when_f_equals_a() -> None:
    inputs = DecisionInputs(
        f_material_errors=0,
        a_material_errors=0,
        r_material_errors=0,
        f_input_tokens_t2_t4=75,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(),
    )
    outcome = decision_rule(inputs)
    assert outcome.result == "INCONCLUSIVE"
    assert outcome.failing == ()
    assert outcome.note == "CAUSAL_NOT_ESTABLISHED: Arm A was also semantically correct."


def test_fail_when_f_semantic_false() -> None:
    inputs = DecisionInputs(
        f_material_errors=1,
        a_material_errors=2,
        r_material_errors=2,
        f_input_tokens_t2_t4=75,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(),
    )
    outcome = decision_rule(inputs)
    assert outcome.result == "FAIL"
    assert outcome.failing == ("F_SEMANTIC",)
    assert outcome.note == ""


def test_fail_when_causal_false_but_not_inconclusive_shape() -> None:
    # F_SEMANTIC true, CAUSAL false (F == A, but ECONOMY false too) -> FAIL naming both.
    inputs = DecisionInputs(
        f_material_errors=0,
        a_material_errors=0,
        r_material_errors=0,
        f_input_tokens_t2_t4=76,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(),
    )
    outcome = decision_rule(inputs)
    assert outcome.result == "FAIL"
    assert outcome.failing == ("CAUSAL", "ECONOMY")


def test_fail_when_no_worse_r_false() -> None:
    # F_material_errors > R_material_errors also makes F_SEMANTIC false (F must be > 0
    # for NO_WORSE_R to fail), so both are named — FAIL never isolates NO_WORSE_R alone.
    inputs = DecisionInputs(
        f_material_errors=1,
        a_material_errors=2,
        r_material_errors=0,
        f_input_tokens_t2_t4=75,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(),
    )
    outcome = decision_rule(inputs)
    assert outcome.result == "FAIL"
    assert outcome.failing == ("F_SEMANTIC", "NO_WORSE_R")


@pytest.mark.parametrize("flag", ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8"])
def test_fail_names_each_false_integrity_component(flag: str) -> None:
    inputs = DecisionInputs(
        f_material_errors=0,
        a_material_errors=1,
        r_material_errors=1,
        f_input_tokens_t2_t4=75,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(**{flag: False}),
    )
    outcome = decision_rule(inputs)
    assert outcome.result == "FAIL"
    assert outcome.failing == (flag.upper(),)


def test_fail_orders_failing_components_f_semantic_causal_economy_no_worse_r_then_integrity() -> (
    None
):
    inputs = DecisionInputs(
        f_material_errors=3,
        a_material_errors=2,
        r_material_errors=1,
        f_input_tokens_t2_t4=100,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(f3=False, f7=False),
    )
    outcome = decision_rule(inputs)
    assert outcome.result == "FAIL"
    assert outcome.failing == ("F_SEMANTIC", "CAUSAL", "ECONOMY", "NO_WORSE_R", "F3", "F7")


def test_economy_boundary_equality_passes_one_unit_beyond_fails() -> None:
    passing = DecisionInputs(
        f_material_errors=0,
        a_material_errors=1,
        r_material_errors=1,
        f_input_tokens_t2_t4=75,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(),
    )
    assert "ECONOMY" not in decision_rule(passing).failing
    assert 4 * 75 == 3 * 100

    failing = DecisionInputs(
        f_material_errors=0,
        a_material_errors=1,
        r_material_errors=1,
        f_input_tokens_t2_t4=76,
        r_input_tokens_t2_t4=100,
        integrity=_integrity(),
    )
    assert decision_rule(failing).failing == ("ECONOMY",)
    assert 4 * 76 > 3 * 100


@pytest.mark.parametrize("bad_value", [-1, 4])
def test_material_error_counts_reject_outside_0_to_3(bad_value: int) -> None:
    with pytest.raises(ValidationError):
        DecisionInputs(
            f_material_errors=bad_value,
            a_material_errors=0,
            r_material_errors=0,
            f_input_tokens_t2_t4=0,
            r_input_tokens_t2_t4=0,
            integrity=_integrity(),
        )
    with pytest.raises(ValidationError):
        DecisionInputs(
            f_material_errors=0,
            a_material_errors=bad_value,
            r_material_errors=0,
            f_input_tokens_t2_t4=0,
            r_input_tokens_t2_t4=0,
            integrity=_integrity(),
        )
    with pytest.raises(ValidationError):
        DecisionInputs(
            f_material_errors=0,
            a_material_errors=0,
            r_material_errors=bad_value,
            f_input_tokens_t2_t4=0,
            r_input_tokens_t2_t4=0,
            integrity=_integrity(),
        )


def test_answer_key_sentences_and_normalized_conclusions_are_locked() -> None:
    assert ANSWER_KEY_SENTENCES == (
        "T1: maximum **three total attempts**, initial attempt included.",
        "T2: one initial attempt plus up to three retries, therefore up to "
        "**four total attempts**. The old three-total interpretation is no longer current.",
        "T3: materially the same as T2. It is a **restatement**, not another correction.",
        "T1: fixed five-second wait before every retry.",
        "T4: fixed five seconds is replaced by exponential delay starting at two seconds, "
        "doubling before later retries, capped at thirty seconds.",
        "final unsuccessful job remains failed;",
        "operator review is required;",
        "the job is not automatically discarded.",
    )
    assert NORMALIZED_CONCLUSIONS == (
        "maximum four total attempts",
        "T3 is a restatement, not another correction",
        "fixed five-second wait is replaced",
        "exponential retry delay begins at two seconds and caps at thirty seconds",
    )


def test_expectations_document_contains_sealed_wording_but_no_runtime_ids() -> None:
    document = expectations_document()

    def _flatten_strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            out: list[str] = []
            for v in value.values():
                out.extend(_flatten_strings(v))
            return out
        if isinstance(value, (list, tuple)):
            out = []
            for v in value:
                out.extend(_flatten_strings(v))
            return out
        return []

    strings = _flatten_strings(document)
    haystack = "\n".join(strings)

    for sentence in ANSWER_KEY_SENTENCES:
        assert sentence in haystack
    for conclusion in NORMALIZED_CONCLUSIONS:
        assert conclusion in haystack
    for label in GRADING_LABELS:
        assert label in strings or any(label in s for s in strings)

    # No runtime ids: this is grading/preflight prose, not a ledger record.
    forbidden_markers = ("ADDR-", "CLAIM-", "judgment_id", "address_id", "claim_id")
    for marker in forbidden_markers:
        assert marker not in haystack

    # No Kestrel evidence text (that lives only in timeline.py).
    assert "# Delivery attempt allowance" not in haystack
    assert "# Retry wait" not in haystack
    assert "# Final failure handling" not in haystack
