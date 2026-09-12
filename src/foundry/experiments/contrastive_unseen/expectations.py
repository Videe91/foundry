"""Sealed scientific decision contract for the 9P2 unseen-lifecycle experiment.

Spec §6 (sealed semantic answer key), §10 (material-continuity error rubric),
§11 (mandatory Arm F integrity expectations), §13 (scientific decision rule),
and §14.5 (sealed leakage needles). This module is grading/preflight data
only: it names loci and expectations in prose, carries no runtime id (no
address/claim/judgment id) and no Kestrel evidence text, and is never sent to
a model. ``timeline.py`` must not import this module — see the ``ast``-based
import check in ``tests/unit/test_contrastive_unseen_timeline.py``.

``decision_rule`` computes the exact PASS/INCONCLUSIVE/FAIL logic from
already-adjudicated inputs (material error counts, token counts, integrity
flags); it invents no semantic verdict of its own (Global Constraint 11, C5).
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel

__all__ = [
    "ANSWER_KEY_LOCUS_A",
    "ANSWER_KEY_LOCUS_B",
    "ANSWER_KEY_LOCUS_N",
    "ANSWER_KEY_SENTENCES",
    "DECISION_RULE_TEXT",
    "FA_RUBRIC",
    "GRADING_LABELS",
    "INCONCLUSIVE_NOTE",
    "INTEGRITY_EXPECTATIONS",
    "NORMALIZED_CONCLUSIONS",
    "R_GRADING_RUBRIC",
    "DecisionInputs",
    "DecisionOutcome",
    "ExpectationsDocument",
    "FACheckpointRubric",
    "IntegrityExpectation",
    "IntegrityInputs",
    "RGradingRubric",
    "decision_rule",
    "expectations_document",
]

# --- §6 sealed semantic answer key (grading truth; never sent to a model) ---------

ANSWER_KEY_LOCUS_A: Final[tuple[str, ...]] = (
    "T1: maximum **three total attempts**, initial attempt included.",
    "T2: one initial attempt plus up to three retries, therefore up to "
    "**four total attempts**. The old three-total interpretation is no longer current.",
    "T3: materially the same as T2. It is a **restatement**, not another correction.",
)

ANSWER_KEY_LOCUS_B: Final[tuple[str, ...]] = (
    "T1: fixed five-second wait before every retry.",
    "T4: fixed five seconds is replaced by exponential delay starting at two seconds, "
    "doubling before later retries, capped at thirty seconds.",
)

ANSWER_KEY_LOCUS_N: Final[tuple[str, ...]] = (
    "final unsuccessful job remains failed;",
    "operator review is required;",
    "the job is not automatically discarded.",
)

ANSWER_KEY_SENTENCES: Final[tuple[str, ...]] = (
    *ANSWER_KEY_LOCUS_A,
    *ANSWER_KEY_LOCUS_B,
    *ANSWER_KEY_LOCUS_N,
)
"""Every full hidden answer-key sentence from spec §6, byte-exact. A leakage
needle source (spec §14.5 item 2); T4's leakage gate imports this tuple."""

# --- §14.5 sealed normalized conclusions (leakage needles) -------------------------

NORMALIZED_CONCLUSIONS: Final[tuple[str, ...]] = (
    "maximum four total attempts",
    "T3 is a restatement, not another correction",
    "fixed five-second wait is replaced",
    "exponential retry delay begins at two seconds and caps at thirty seconds",
)
"""Spec §14.5 item 3, byte-exact. T4's leakage gate imports this tuple."""

# --- grading-only expectation/decision labels (spec §13) ---------------------------

GRADING_LABELS: Final[tuple[str, ...]] = (
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

# --- §10 material-continuity error rubric ------------------------------------------


class FACheckpointRubric(FrozenModel):
    checkpoint: Literal["C1", "C2", "C3"]
    title: str = Field(min_length=1)
    conditions: tuple[str, ...]
    error_note: str = Field(min_length=1)


FA_RUBRIC: Final[tuple[FACheckpointRubric, ...]] = (
    FACheckpointRubric(
        checkpoint="C1",
        title="F/A C1 — T2 A correction",
        conditions=(
            "T2 remains at the designated A address rather than creating a duplicate "
            "same-locus address;",
            "current A meaning expresses one initial attempt plus up to three retries / "
            "up to four total attempts;",
            "pre-T2 A claims remain readable historical state;",
            "every pre-T2 A root claim whose material meaning is incompatible with T2 is "
            "targeted for governed supersession;",
            "no still-compatible A subclaim is required to be superseded merely because it "
            "shares the root evidence;",
            "incompatible old A meaning does not leave the current view before authority;",
            "after authority, no incompatible three-total-attempt interpretation remains current;",
            "no duplicate current A identity represents the corrected meaning.",
        ),
        error_note="Any failure contributes exactly 1 C1 error.",
    ),
    FACheckpointRubric(
        checkpoint="C2",
        title="F/A C2 — T3 A restatement",
        conditions=(
            "T3 remains at the designated A address;",
            "current A meaning still expresses the T2 one-plus-three-retries interpretation;",
            "T3 produces `SUPPORTS_CLAIM` for the current A meaning;",
            "the current corrected A claim is not superseded merely because of T3;",
            "no materially duplicate A claim/address is created for the restatement.",
        ),
        error_note="Any failure contributes exactly 1 C2 error.",
    ),
    FACheckpointRubric(
        checkpoint="C3",
        title="F/A C3 — T4 B correction",
        conditions=(
            "T4 remains at the designated B address rather than creating a duplicate "
            "same-locus address;",
            "current B meaning expresses exponential retry delay beginning at two seconds, "
            "doubling before later retries, capped at thirty seconds;",
            "pre-T4 B claims remain readable historical state;",
            "every pre-T4 B root claim whose material meaning is incompatible with T4 is "
            "targeted for governed supersession;",
            "no still-compatible B subclaim is required to be superseded merely because it "
            "shares the root evidence;",
            "incompatible fixed-five-second meaning does not leave the current view before "
            "authority;",
            "after authority, incompatible fixed-five-second meaning is no longer current;",
            "no duplicate current B identity represents the corrected meaning.",
        ),
        error_note="Any failure contributes exactly 1 C3 error.",
    ),
)


class RGradingRubric(FrozenModel):
    checkpoint: Literal["C1", "C2", "C3"]
    text: str = Field(min_length=1)


R_GRADING_RUBRIC: Final[tuple[RGradingRubric, ...]] = (
    RGradingRubric(
        checkpoint="C1",
        text=(
            "current reconstruction cleanly represents one initial plus up to three "
            "retries; obsolete three-total-attempt meaning may not remain concurrently "
            "current as a competing interpretation of the same locus."
        ),
    ),
    RGradingRubric(
        checkpoint="C2",
        text=(
            "current reconstruction cleanly represents the same one-plus-three-retries "
            "meaning; obsolete or incompatible duplicate meaning may not remain current."
        ),
    ),
    RGradingRubric(
        checkpoint="C3",
        text=(
            "current reconstruction cleanly represents exponential retry delay "
            "2 -> double -> cap 30; fixed-five-second meaning may not remain concurrently "
            "current as a competing interpretation of the same locus."
        ),
    ),
)

# --- §11 mandatory Arm F integrity expectations ------------------------------------


class IntegrityExpectation(FrozenModel):
    id: Literal["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)


INTEGRITY_EXPECTATIONS: Final[tuple[IntegrityExpectation, ...]] = (
    IntegrityExpectation(
        id="F1",
        title="unique T1 root addresses",
        text="A, B, and N each designate exactly one root address by §7.",
    ),
    IntegrityExpectation(
        id="F2",
        title="stable control",
        text=(
            "N remains materially unchanged through T4 and is not spuriously superseded, "
            "conflicted, or duplicated because of A/B changes."
        ),
    ),
    IntegrityExpectation(
        id="F3",
        title="allowed operation boundary",
        text=(
            "Every F request uses only the locked two-call judgment sets. No "
            "relationship-repair phase, `EQUIVALENT`/`DISTINCT` call, third reconciliation "
            "call, or hidden semantic repair is introduced."
        ),
    ),
    IntegrityExpectation(
        id="F4",
        title="non-citable historical context",
        text=(
            "For every F proposal, each cited evidence id must be present in that exact "
            "request's `ReasoningRequest.evidence`. A predecessor present only in "
            "`comparison_context` is non-citable."
        ),
    ),
    IntegrityExpectation(
        id="F5",
        title="scoped visibility",
        text=(
            'Every address/claim exposed in F is eligible for ("kestrel-delivery",) under '
            "the locked scope rule. Contrastive context may not widen across scope."
        ),
    ),
    IntegrityExpectation(
        id="F6",
        title="exactly two calls, no retry",
        text="Each completed F T makes exactly two calls, in order, with no retry/fallback/judge.",
    ),
    IntegrityExpectation(
        id="F7",
        title="exact replay",
        text=(
            "Replay of F's final append-only ledger reproduces final F state and derived "
            "view exactly."
        ),
    ),
    IntegrityExpectation(
        id="F8",
        title="governance boundary",
        text=(
            "No model directly applies material supersession. Incompatible old meaning "
            "leaves the current view only through existing admission plus the mechanical "
            "authority protocol."
        ),
    ),
)

# --- §13 scientific decision rule ---------------------------------------------------

DECISION_RULE_TEXT: Final[str] = (
    "F_SEMANTIC = (F_material_errors == 0)\n"
    "CAUSAL     = (F_material_errors < A_material_errors)\n"
    "ECONOMY    = (4 * F_input_tokens_T2_T4 <= 3 * R_input_tokens_T2_T4)\n"
    "NO_WORSE_R = (F_material_errors <= R_material_errors)\n"
    "INTEGRITY  = all F1..F8 pass\n"
    "\n"
    "PASS iff F_SEMANTIC AND CAUSAL AND ECONOMY AND NO_WORSE_R AND INTEGRITY\n"
    "INCONCLUSIVE iff F_SEMANTIC AND NOT CAUSAL AND ECONOMY AND NO_WORSE_R AND INTEGRITY\n"
    "FAIL otherwise"
)

INCONCLUSIVE_NOTE: Final = "CAUSAL_NOT_ESTABLISHED: Arm A was also semantically correct."

_INTEGRITY_FIELD_ORDER: Final[tuple[str, ...]] = (
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
)


class IntegrityInputs(FrozenModel):
    f1: bool
    f2: bool
    f3: bool
    f4: bool
    f5: bool
    f6: bool
    f7: bool
    f8: bool


class DecisionInputs(FrozenModel):
    f_material_errors: int = Field(ge=0, le=3)
    a_material_errors: int = Field(ge=0, le=3)
    r_material_errors: int = Field(ge=0, le=3)
    f_input_tokens_t2_t4: int = Field(ge=0)
    r_input_tokens_t2_t4: int = Field(ge=0)
    integrity: IntegrityInputs


class DecisionOutcome(FrozenModel):
    result: Literal["PASS", "INCONCLUSIVE", "FAIL"]
    failing: tuple[str, ...]
    note: str


def decision_rule(inputs: DecisionInputs) -> DecisionOutcome:
    """Spec §13 decision rule, preregistered. No threshold is configurable.

    For PASS and INCONCLUSIVE, ``failing == ()``. INCONCLUSIVE's note is exactly
    :data:`INCONCLUSIVE_NOTE`. For FAIL, ``failing`` lists each false component in
    order: ``F_SEMANTIC``, ``CAUSAL``, ``ECONOMY``, ``NO_WORSE_R``, then false
    ``F1``..``F8``.
    """
    f_semantic = inputs.f_material_errors == 0
    causal = inputs.f_material_errors < inputs.a_material_errors
    economy = 4 * inputs.f_input_tokens_t2_t4 <= 3 * inputs.r_input_tokens_t2_t4
    no_worse_r = inputs.f_material_errors <= inputs.r_material_errors
    integrity_flags = {name: getattr(inputs.integrity, name) for name in _INTEGRITY_FIELD_ORDER}
    integrity = all(integrity_flags.values())

    if f_semantic and causal and economy and no_worse_r and integrity:
        return DecisionOutcome(result="PASS", failing=(), note="")
    if f_semantic and not causal and economy and no_worse_r and integrity:
        return DecisionOutcome(result="INCONCLUSIVE", failing=(), note=INCONCLUSIVE_NOTE)

    failing: list[str] = []
    if not f_semantic:
        failing.append("F_SEMANTIC")
    if not causal:
        failing.append("CAUSAL")
    if not economy:
        failing.append("ECONOMY")
    if not no_worse_r:
        failing.append("NO_WORSE_R")
    for name in _INTEGRITY_FIELD_ORDER:
        if not integrity_flags[name]:
            failing.append(name.upper())
    return DecisionOutcome(result="FAIL", failing=tuple(failing), note="")


# --- canonical grading/preflight document -------------------------------------------


class ExpectationsDocument(FrozenModel):
    experiment_version: str
    grading_labels: tuple[str, ...]
    answer_key_locus_a: tuple[str, ...]
    answer_key_locus_b: tuple[str, ...]
    answer_key_locus_n: tuple[str, ...]
    fa_rubric: tuple[FACheckpointRubric, ...]
    r_grading_rubric: tuple[RGradingRubric, ...]
    integrity_expectations: tuple[IntegrityExpectation, ...]
    decision_rule_text: str
    inconclusive_note: str
    normalized_conclusions: tuple[str, ...]


def expectations_document() -> dict[str, object]:
    """Canonical grading/preflight document: answer key, rubric, F1-F8, decision
    rule, and leakage needle source material. Contains no runtime id and no
    Kestrel evidence text; it is never sent to a model.
    """
    document = ExpectationsDocument(
        experiment_version="intent-v2-contrastive-unseen-lifecycle-v1",
        grading_labels=GRADING_LABELS,
        answer_key_locus_a=ANSWER_KEY_LOCUS_A,
        answer_key_locus_b=ANSWER_KEY_LOCUS_B,
        answer_key_locus_n=ANSWER_KEY_LOCUS_N,
        fa_rubric=FA_RUBRIC,
        r_grading_rubric=R_GRADING_RUBRIC,
        integrity_expectations=INTEGRITY_EXPECTATIONS,
        decision_rule_text=DECISION_RULE_TEXT,
        inconclusive_note=INCONCLUSIVE_NOTE,
        normalized_conclusions=NORMALIZED_CONCLUSIONS,
    )
    return document.model_dump(mode="json")
