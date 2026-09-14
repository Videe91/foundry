"""Hidden scientific contract for the 9P3 long-horizon bounded-memory experiment.

Spec §4.13 (baseline meanings), §5 ("Meaning"/"Expected" lines), §6 (transition
classes), §10 (checkpoints, controls, R grading), §12 (integrity gate titles),
§14 (economy and bounded-growth thresholds) and §16 (architecture-selection
precedence). This module is grading/preflight data only: it names loci and
expectations in prose, carries no runtime id (no address/claim/judgment id) and
no Orion evidence text, and is never sent to a model. No request-path module
(``timeline``, ``protocol``, and every later runner-side module) may import it;
``timeline.py`` and ``protocol.py`` are checked by ``ast`` in their unit tests.

``select_architecture`` computes the spec §16.2 precedence literally from
already-adjudicated inputs (error counts, integrity flags, exact token totals and
window means); it invents no semantic verdict of its own. Every threshold is an
exact rational locked in the approved spec.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Final, Literal

from pydantic import Field, field_validator

from foundry.domain.common import FrozenModel
from foundry.experiments.long_horizon_bounded.protocol import EARLY_WINDOW, LATE_WINDOW
from foundry.experiments.long_horizon_bounded.timeline import (
    EXPERIMENT_VERSION,
    LOCI,
    VERSION_COUNT,
    Locus,
)

__all__ = [
    "BASELINE_MEANINGS",
    "BOUNDED_FACTOR",
    "CHECKPOINTS",
    "CONTROL_ERROR_RULES",
    "CURRENT_MEANING_BY_T",
    "DECISION_NAMES",
    "ECONOMY_DEN",
    "ECONOMY_NUM",
    "GRADING_LABELS",
    "INTEGRITY_TITLES",
    "MEANINGFUL_DIFF",
    "PERSISTENT_RUBRIC",
    "R_GRADING_RULES",
    "R_GROWTH_FACTOR",
    "SELECTION_PRECEDENCE_TEXT",
    "Checkpoint",
    "ExpectationsDocument",
    "SelectionInputs",
    "SelectionOutcome",
    "Thresholds",
    "TransitionClass",
    "expectations_document",
    "select_architecture",
    "token_diff_fa",
]

TransitionClass = Literal[
    "RESTATEMENT",
    "CORRECTION",
    "REVERT",
    "COMPATIBLE_EXTENSION",
    "SEMANTIC_NO_OP",
]

# --- §4.13 baseline meanings (grading reference; not model-visible) -----------------

BASELINE_MEANINGS: Final[dict[Locus, str]] = {
    "A": "maximum 3 total execution attempts, initial attempt included",
    "B": "fixed 5-second wait before every retry",
    "C": "each execution attempt times out after 30 seconds",
    "D": "a duplicate delivery with the same job id is ignored while an existing job is active",
    "E": "idempotency keys retained for 24 hours",
    "F": "worker lease duration 60 seconds",
    "G": "worker may renew the lease every 30 seconds while work is progressing",
    "H": (
        "cancellation prevents future attempts but does not interrupt an attempt already executing"
    ),
    "I": (
        "after the final unsuccessful attempt the job is automatically moved to the dead-letter "
        "queue"
    ),
    "J": "operator escalation after 3 dead-letter events for the same tenant within 1 hour",
    "K": "FIFO ordering guaranteed only within one queue partition",
    "L": "audit events retained for 30 days",
}

# --- §5 "Meaning" / "Expected" lines, byte-exact -------------------------------------

_MEANING_T02_C: Final = "unchanged (30-second per-attempt timeout)."
_MEANING_T03_A: Final = (
    "one initial attempt plus up to three retries, i.e. **maximum 4 total attempts**; the 3-total "
    "meaning is no longer current."
)
_MEANING_T04: Final = (
    "unchanged at every locus: every section changes bytes and no normative meaning changes."
)
_MEANING_T05_B: Final = (
    "exponential retry delay starting at 2 seconds, doubling, capped at 30 seconds; the "
    "fixed-5-second meaning is no longer current."
)
_MEANING_T06_A: Final = "unchanged (one initial plus up to three retries; 4 total)."
_MEANING_T07_F: Final = (
    "worker lease duration 90 seconds; the 60-second meaning is no longer current."
)
_MEANING_T08_B: Final = (
    "fixed 5-second wait before every retry — the same meaning that was current at T1–T4 — and the "
    "exponential meaning current since T5 is no longer current. This is intentionally difficult: "
    "the new meaning matches an older historical meaning but supersedes the **current** meaning."
)
_MEANING_T09_H: Final = (
    "the existing cancellation rules (no future attempt after cancellation; a running attempt is "
    "not interrupted) remain current, and a genuinely new, compatible rule is added — repeated "
    "cancellation of an already-cancelled job is idempotent: the job remains cancelled and no "
    "other job state changes because of the repeated cancellation. The added rule is not implied "
    "by T1: T1 constrains what happens to execution attempts after a cancellation, and says "
    "nothing about what a second cancellation does to the job's state."
)
_MEANING_T10_D: Final = (
    "a duplicate is ignored only when both job id and idempotency key match; otherwise it is "
    'rejected as conflicting input. The unqualified "ignore by job id alone" rule is materially '
    "incomplete and must not remain current."
)
_MEANING_T11_L: Final = "unchanged (30-day audit retention)."
_MEANING_T12_G: Final = (
    "renew when 20 seconds of lease life remain, never more often than once every 15 seconds; the "
    "fixed every-30-seconds renewal meaning is no longer current."
)
_MEANING_T13_K: Final = "unchanged (FIFO only within one queue partition)."
_MEANING_T14_J: Final = (
    "escalation after 5 dead-letter events for the same tenant within a rolling 30-minute window; "
    "the 3-in-1-hour rule is no longer current."
)
_MEANING_T15_F: Final = "unchanged (90-second lease)."
_MEANING_T16_I: Final = (
    "the job is left failed and requires operator review; automatic dead-lettering is no longer "
    "current."
)

_EXPECTED_T02: Final = (
    "same C address; `SUPPORTS_CLAIM`; no duplicate current claim; no supersession."
)
_EXPECTED_T03: Final = (
    "same A address; assert the corrected 4-total meaning; the incompatible 3-total meaning is "
    "superseded through human authority."
)
_EXPECTED_T04: Final = (
    "no material semantic churn in any locus — every live claim is restated or left untouched; no "
    "supersession, no new address, no conflict, no duplicate current meaning. (Arm F receives "
    "twelve structural transitions with twelve real diffs at this version; that is the point.)"
)
_EXPECTED_T05: Final = (
    "same B address; new backoff meaning asserted; governed supersession of the fixed-5 meaning."
)
_EXPECTED_T06: Final = (
    "same A address; `SUPPORTS_CLAIM` on the current 4-total meaning; no supersession."
)
_EXPECTED_T07: Final = (
    "same F address; new 90-second claim; governed supersession of the 60-second claim."
)
_EXPECTED_T08: Final = (
    "same B address; assert a current fixed-5 claim; supersede the current exponential meaning; do "
    "not resurrect the old durable claim object as if history rewound (the T1 claim remains "
    "historical and superseded; a new claim carries the restored meaning); append-only lineage "
    "preserved."
)
_EXPECTED_T09: Final = (
    "same designated H address; the existing cancellation meaning remains current; the new "
    "idempotent-repeat-cancellation meaning becomes current (a new compatible `ASSERT_CLAIM` at H, "
    "or a support of an existing H claim plus a new compatible `ASSERT_CLAIM`, provided the "
    "material meanings are correct); no existing compatible H claim is superseded; no duplicate H "
    "address."
)
_EXPECTED_T10: Final = (
    "same D address; corrected current duplicate rule; governed supersession of the unqualified "
    "old rule."
)
_EXPECTED_T11: Final = "same L address; `SUPPORTS_CLAIM`; no duplicate."
_EXPECTED_T12: Final = (
    "same G address; corrected renewal meaning; governed supersession of the old fixed-interval "
    "meaning."
)
_EXPECTED_T13: Final = (
    "same K address; support of the existing meaning; no duplicate address caused by the "
    "relocation."
)
_EXPECTED_T14: Final = (
    "same J address; corrected threshold and window; governed supersession of the old rule."
)
_EXPECTED_T15: Final = "same F address; support of the 90-second claim; no supersession."
_EXPECTED_T16: Final = (
    "same I address; corrected current meaning; governed supersession of the automatic dead-letter "
    "behaviour."
)

# --- §10.2 checkpoint requirements by class ------------------------------------------

PERSISTENT_RUBRIC: Final[dict[TransitionClass, tuple[str, ...]]] = {
    "RESTATEMENT": (
        "the delta is bound to the designated address of the target locus (no `CREATE_ADDRESS` "
        "for that locus);",
        "the current meaning of the target locus is unchanged;",
        "a `SUPPORTS_CLAIM` (or no change) is the only semantic action on the current claim where "
        "support is appropriate;",
        "no duplicate current meaning is created at the locus;",
        "no pending or applied `SUPERSEDE` targets a live claim at the locus.",
    ),
    "CORRECTION": (
        "the delta is bound to the designated address (no duplicate same-locus address);",
        "the corrected meaning is asserted and current at that address;",
        "the incompatible old meaning remains historically readable;",
        "the incompatible old meaning does not leave the current view before authority;",
        "a model `SUPERSEDE` proposal targets the creating judgment of every materially "
        "incompatible claim that was live at the designated address immediately before T (an "
        "eligible pre-T target, §18.1) and is applied only through the mechanical authority "
        "protocol (§18);",
        "after authority, no incompatible old meaning is current at the locus;",
        "any still-compatible subclaim at the locus is not required to be superseded.",
    ),
    "REVERT": (
        "the delta is bound to the designated B address;",
        "the immediately preceding current meaning (exponential; the T5-created claim live at the "
        "designated B address immediately before T8, i.e. the eligible pre-T target of §18.1) is "
        "targeted for governed supersession and, after authority, is not current;",
        "the restored meaning (fixed 5 seconds) is current, carried by a claim asserted at T8 (a "
        "new claim object);",
        "the historical T1 claim object is not treated as re-activated or as a literal state "
        "rollback (it remains superseded);",
        "history is append-only and the lineage T1 → T5 → T8 is readable.",
    ),
    "COMPATIBLE_EXTENSION": (
        "the delta is bound to the designated H address (no duplicate H address);",
        "the existing compatible cancellation meaning (no future attempt after cancellation; a "
        "running attempt is not interrupted) remains current;",
        "the new compatible meaning — repeated cancellation of an already-cancelled job is "
        "idempotent — is added and current (a new compatible `ASSERT_CLAIM` at H, or a support of "
        "an existing H claim plus a new compatible `ASSERT_CLAIM`, provided the material meanings "
        "are correct);",
        "no `SUPERSEDE` (pending or applied) targets any existing compatible H claim.",
    ),
    "SEMANTIC_NO_OP": (
        "there is no material semantic churn in any locus: no new address for any locus, no "
        "pending or applied `SUPERSEDE`, no `CONFLICTS_WITH`, no duplicate current meaning, no "
        "change to any current meaning; supports and no-ops are the only permitted actions.",
    ),
}

# --- §10.3 stable controls -------------------------------------------------------------

CONTROL_ERROR_RULES: Final[tuple[str, ...]] = (
    "At every T2–T16, every locus other than the transition's target locus is a control. A "
    "**control error** is counted for that arm at that T for any unjustified:",
    "supersession (pending or applied) of a control claim;",
    "`CONFLICTS_WITH` involving a control claim;",
    "duplicate current address for a control locus;",
    "duplicate current meaning at a control locus;",
    "material mutation of a control's current meaning;",
    "semantic disappearance of a control's current meaning.",
    "At most one control error is counted per arm per T. Control errors count toward the arm's "
    "total semantic error count.",
)

# --- §10.4 R grading -------------------------------------------------------------------

R_GRADING_RULES: Final[tuple[str, ...]] = (
    "R has no persistent address identity and no authority. At each T, R is judged only on the "
    "fresh current reconstruction:",
    "the current reconstruction must cleanly represent the meaning that is current at that T for "
    "every locus (§4.13 and §5);",
    "obsolete historical interpretations must not remain concurrently current at the same locus "
    "— for example after T3 the 3-total and 4-total meanings cannot both be current; after T5 "
    "fixed-5 and exponential cannot both be current; after T8 exponential must not be current when "
    "fixed-5 has been restored; after T10 the unqualified duplicate rule must not be current; "
    "after T16 automatic dead-lettering must not be current;",
    "duplicate same-locus current addresses are errors.",
    "R's checkpoint C0k is PASS iff both the target locus and every control locus meet these "
    "conditions at T = k; one material error per failed checkpoint; control errors are counted for "
    "R under the same definitions as §10.3 restricted to what a fresh reconstruction can exhibit.",
)

# --- §5/§6/§10.2 checkpoints C02..C16 ----------------------------------------------------


class Checkpoint(FrozenModel):
    """One hidden binary checkpoint (spec §10.2).

    ``expected_current_meaning`` is the spec §5 "Meaning" sentence of the transition
    (for C04, the no-op statement). ``requirements`` is the spec §5 "Expected"
    sentence followed by the §10.2 rubric of the transition class. ``controls`` is
    every locus other than the target (spec §10.3); for C04 every locus is a control.
    """

    id: str = Field(pattern=r"^C(0[2-9]|1[0-6])$")
    t: int = Field(ge=2, le=VERSION_COUNT)
    transition_class: TransitionClass
    target_locus: Locus | None
    expected_current_meaning: str = Field(min_length=1)
    requirements: tuple[str, ...] = Field(min_length=1)
    controls: tuple[Locus, ...]


def _checkpoint(
    t: int,
    transition_class: TransitionClass,
    target_locus: Locus | None,
    meaning: str,
    expected: str,
) -> Checkpoint:
    return Checkpoint(
        id=f"C{t:02d}",
        t=t,
        transition_class=transition_class,
        target_locus=target_locus,
        expected_current_meaning=meaning,
        requirements=(expected, *PERSISTENT_RUBRIC[transition_class]),
        controls=tuple(locus for locus in LOCI if locus != target_locus),
    )


CHECKPOINTS: Final[tuple[Checkpoint, ...]] = (
    _checkpoint(2, "RESTATEMENT", "C", _MEANING_T02_C, _EXPECTED_T02),
    _checkpoint(3, "CORRECTION", "A", _MEANING_T03_A, _EXPECTED_T03),
    _checkpoint(4, "SEMANTIC_NO_OP", None, _MEANING_T04, _EXPECTED_T04),
    _checkpoint(5, "CORRECTION", "B", _MEANING_T05_B, _EXPECTED_T05),
    _checkpoint(6, "RESTATEMENT", "A", _MEANING_T06_A, _EXPECTED_T06),
    _checkpoint(7, "CORRECTION", "F", _MEANING_T07_F, _EXPECTED_T07),
    _checkpoint(8, "REVERT", "B", _MEANING_T08_B, _EXPECTED_T08),
    _checkpoint(9, "COMPATIBLE_EXTENSION", "H", _MEANING_T09_H, _EXPECTED_T09),
    _checkpoint(10, "CORRECTION", "D", _MEANING_T10_D, _EXPECTED_T10),
    _checkpoint(11, "RESTATEMENT", "L", _MEANING_T11_L, _EXPECTED_T11),
    _checkpoint(12, "CORRECTION", "G", _MEANING_T12_G, _EXPECTED_T12),
    _checkpoint(13, "RESTATEMENT", "K", _MEANING_T13_K, _EXPECTED_T13),
    _checkpoint(14, "CORRECTION", "J", _MEANING_T14_J, _EXPECTED_T14),
    _checkpoint(15, "RESTATEMENT", "F", _MEANING_T15_F, _EXPECTED_T15),
    _checkpoint(16, "CORRECTION", "I", _MEANING_T16_I, _EXPECTED_T16),
)

# --- current meaning per version per locus (§4.13 carried forward, replaced by §5) -----

_MEANING_CHANGES: Final[dict[int, tuple[Locus, str]]] = {
    3: ("A", _MEANING_T03_A),
    5: ("B", _MEANING_T05_B),
    7: ("F", _MEANING_T07_F),
    8: ("B", _MEANING_T08_B),
    9: ("H", _MEANING_T09_H),
    10: ("D", _MEANING_T10_D),
    12: ("G", _MEANING_T12_G),
    14: ("J", _MEANING_T14_J),
    16: ("I", _MEANING_T16_I),
}
"""Transitions whose current meaning changes (correction, revert, compatible
extension). Restatements (T2, T6, T11, T13, T15) and the no-op (T4) carry every
meaning forward unchanged."""


def _materialize_meanings() -> dict[int, dict[Locus, str]]:
    by_t: dict[int, dict[Locus, str]] = {}
    current = dict(BASELINE_MEANINGS)
    for t in range(1, VERSION_COUNT + 1):
        change = _MEANING_CHANGES.get(t)
        if change is not None:
            locus, meaning = change
            current[locus] = meaning
        by_t[t] = dict(current)
    return by_t


CURRENT_MEANING_BY_T: Final[dict[int, dict[Locus, str]]] = _materialize_meanings()

# --- §12 integrity gate titles -----------------------------------------------------------

INTEGRITY_TITLES: Final[tuple[str, ...]] = (
    "exactly twelve pairwise-distinct designated T1 root addresses",
    "exactly two model calls for every completed persistent T (call numbers 1, 2; no duplicate "
    "request identity)",
    "no semantic retry, fallback, judge or third phase anywhere in the run",
    "every evidence id cited by every model-originated proposal was present in that exact "
    "request's `ReasoningRequest.evidence`",
    "a predecessor shown only in comparison context is never cited",
    'scope closure: every known address is eligible for `("orion-jobs",)`; known claims and '
    "touched addresses stay within each request's known addresses",
    "no model-originated `SUPERSEDE` is itself the applied state-changing judgment",
    "every applied material supersession is a human AGREE (route `APPLY`, reason "
    "`HUMAN_AUTHORITY`) whose proposal signature equals an earlier pending model proposal",
    "replay of the final ledger reproduces the final state and derived view exactly",
    "request-only reference law (the frozen adapter law; known reference sets are built from the "
    "`ReasoningRequest` ONLY): for every model-originated draft/proposal, every cited evidence id "
    "existed in that exact `ReasoningRequest.evidence`; every referenced address id existed in "
    "that exact `ReasoningRequest.known_addresses`; every referenced claim id existed in that "
    "exact `ReasoningRequest.known_claims`; every `SUPERSEDE` `target_judgment_id` was the "
    "`created_by_judgment_id` of a claim present in that exact `ReasoningRequest.known_claims`; no "
    "id minted while wrapping another draft from the same provider response satisfies any "
    "reference (a claim asserted by one draft cannot be referenced by another draft of that "
    "response); any violation is a structural failure under the frozen adapter law — never "
    "repaired, guessed, substituted or silently dropped",
    "durable history is append-only and every superseded claim/judgment remains readable in the "
    "final ledger",
    "no hidden reconciliation operation exists: request records, receipts and ledger events "
    "reconcile one-to-one with the 96-call schedule",
    "offline compilation of every R Call-1 request and every persistent T1 request from the frozen "
    "corpus succeeds within the frozen bounds, and R's T16 canonical comparison context is ≤ "
    "100,000 characters (≈ 76 % of the 131,072 bound, leaving headroom for Call-2 profile edges)",
    "9P2's leakage gate (five-key skeletons, needle set of §15) passes over the 9P3 needle set",
    "mechanical authority chain (§18.3): every applied material supersession is a human AGREE "
    "whose target judgment id was in that transition's structurally snapshotted pre-T eligible set "
    "`ELIGIBLE_T` (§18.1), whose proposal signature equals an earlier pending model-originated "
    "proposal, routed `APPLY` with reason `HUMAN_AUTHORITY`; every AGREE was issued only at a "
    "correction/revert checkpoint; every pending proposal outside `ELIGIBLE_T` was recorded as not "
    "authorized and never applied; no authority record or AGREE carries any semantic assessment",
)
"""Spec §12 gate requirements, I1..I15 in order."""

# --- grading-only labels and decision names (§10, §12, §16) ------------------------------

DECISION_NAMES: Final[tuple[str, ...]] = (
    "SELECT_F",
    "SELECT_A",
    "REDESIGN_PERSISTENT_CONTEXT",
    "SCALE_NOT_YET_PROVEN",
    "INCONCLUSIVE_TIE",
    "EXPERIMENT_INCONCLUSIVE",
)

GRADING_LABELS: Final[tuple[str, ...]] = (
    *(f"C{t:02d}" for t in range(2, VERSION_COUNT + 1)),
    *(f"I{n}" for n in range(1, 16)),
    "errors_F",
    "errors_A",
    "errors_R",
    *DECISION_NAMES,
)

# --- §14 / §16.1 thresholds (exact rationals) ---------------------------------------------

ECONOMY_NUM: Final[int] = 4
ECONOMY_DEN: Final[int] = 3
BOUNDED_FACTOR: Final[Fraction] = Fraction(135, 100)
R_GROWTH_FACTOR: Final[Fraction] = Fraction(3, 2)
MEANINGFUL_DIFF: Final[Fraction] = Fraction(5, 100)

# --- §16.2 precedence text, verbatim ----------------------------------------------------------

SELECTION_PRECEDENCE_TEXT: Final[str] = (
    "Evaluated strictly top to bottom; the first matching rule is the decision. The decision "
    "artifact records every input, the truth value of every predicate, the matched rule, and — for "
    "the residual — the unmatched predicate vector.\n"
    "\n"
    "**0. Operational / scientific invalidity — above architecture judgment.** If the experiment "
    "cannot be scientifically adjudicated because of a provider/runtime abort, a violated "
    "preregistration, missing or corrupted artifacts, invalid call counts, answer-key leakage, or "
    "any other experiment-invalidating integrity failure (a failed gate of §12 that is not "
    "attributable to one arm's semantic behaviour), then:\n"
    "\n"
    "```text\n"
    "EXPERIMENT_INCONCLUSIVE\n"
    "```\n"
    "\n"
    "**1. Neither persistent arm is semantically acceptable.**\n"
    "\n"
    "```text\n"
    "NOT acceptable_F AND NOT acceptable_A  ->  REDESIGN_PERSISTENT_CONTEXT\n"
    "```\n"
    "\n"
    "**2. Exactly one persistent arm is semantically acceptable.** Let X be that arm (the other "
    "arm is out of contention regardless of its cost).\n"
    "\n"
    "```text\n"
    "2A. BOUNDED_X AND ECONOMY_X          ->  SELECT_X\n"
    "2B. NOT BOUNDED_X                    ->  REDESIGN_PERSISTENT_CONTEXT\n"
    "2C. BOUNDED_X AND NOT ECONOMY_X:\n"
    "        NOT R_GROWS                  ->  SCALE_NOT_YET_PROVEN\n"
    "        R_GROWS                      ->  EXPERIMENT_INCONCLUSIVE\n"
    "```\n"
    "\n"
    "Reason: a semantically wrong competitor never wins because it happens to use fewer tokens.\n"
    "\n"
    "**3. Both F and A are semantically acceptable.** Boundedness is evaluated first.\n"
    "\n"
    "```text\n"
    "3A. NOT BOUNDED_F AND NOT BOUNDED_A  ->  REDESIGN_PERSISTENT_CONTEXT\n"
    "\n"
    "3B. exactly one bounded; let X be the bounded arm:\n"
    "        ECONOMY_X                    ->  SELECT_X\n"
    "        NOT ECONOMY_X AND NOT R_GROWS ->  SCALE_NOT_YET_PROVEN\n"
    "        NOT ECONOMY_X AND R_GROWS    ->  EXPERIMENT_INCONCLUSIVE\n"
    "\n"
    "3C. both bounded; evaluate economy versus R:\n"
    "    a. NOT ECONOMY_F AND NOT ECONOMY_A:\n"
    "        NOT R_GROWS                  ->  SCALE_NOT_YET_PROVEN\n"
    "        R_GROWS                      ->  EXPERIMENT_INCONCLUSIVE\n"
    "    b. exactly one economical; let X be the economical arm:\n"
    "                                     ->  SELECT_X\n"
    "    c. ECONOMY_F AND ECONOMY_A:\n"
    "        TOKEN_DIFF_FA < 5/100        ->  INCONCLUSIVE_TIE\n"
    "        F_TOTAL < A_TOTAL            ->  SELECT_F\n"
    "        A_TOTAL < F_TOTAL            ->  SELECT_A\n"
    "```\n"
    "\n"
    "(In 3C.c, `F_TOTAL == A_TOTAL` gives `TOKEN_DIFF_FA == 0`, which is the tie.)\n"
    "\n"
    "**4. Residual.** Any state not matched above:\n"
    "\n"
    "```text\n"
    "EXPERIMENT_INCONCLUSIVE, recording the unmatched predicate vector\n"
    "(acceptable_F, acceptable_A, BOUNDED_F, BOUNDED_A, ECONOMY_F, ECONOMY_A, R_GROWS, "
    "TOKEN_DIFF_FA)\n"
    "```\n"
)

# --- §16 architecture selection ---------------------------------------------------------------


class SelectionInputs(FrozenModel):
    """Already-adjudicated inputs of spec §16.1.

    Window means are exact ``Fraction`` strings (``"p/q"``) so the document stays
    JSON-canonical; they are parsed with ``Fraction(value)`` and never rounded.
    """

    completed: bool
    scientifically_valid: bool
    errors_F: int = Field(ge=0)
    errors_A: int = Field(ge=0)
    errors_R: int = Field(ge=0)
    integrity_F: bool
    integrity_A: bool
    f_total: int = Field(ge=0)
    a_total: int = Field(ge=0)
    r_total: int = Field(ge=0)
    f_early_mean: str
    f_late_mean: str
    a_early_mean: str
    a_late_mean: str
    r_early_mean: str
    r_late_mean: str

    @field_validator(
        "f_early_mean",
        "f_late_mean",
        "a_early_mean",
        "a_late_mean",
        "r_early_mean",
        "r_late_mean",
    )
    @classmethod
    def _window_mean_is_a_non_negative_rational(cls, value: str) -> str:
        """Refuse a string ``Fraction`` cannot parse (or a zero denominator) and a
        negative mean at construction, so rule 0 is never pre-empted by an exception
        inside the predicate evaluation. Returns the original string unchanged."""
        try:
            parsed = Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"window mean {value!r} is not an exact rational") from exc
        if parsed < 0:
            raise ValueError(f"window mean {value!r} must be non-negative")
        return value


class SelectionOutcome(FrozenModel):
    decision: str
    matched_rule: str
    predicates: dict[str, bool | str]
    reason: str


def token_diff_fa(f_total: int, a_total: int) -> Fraction:
    """Spec §16.1: ``|F_TOTAL − A_TOTAL| / min(F_TOTAL, A_TOTAL)``, exact."""
    denominator = min(f_total, a_total)
    if denominator <= 0:
        raise ValueError("token totals must be strictly positive for a completed run")
    return Fraction(abs(f_total - a_total), denominator)


def _bounded(early: str, late: str) -> bool:
    return Fraction(late) <= BOUNDED_FACTOR * Fraction(early)


def _predicates(inputs: SelectionInputs) -> dict[str, bool | str]:
    return {
        "acceptable_F": inputs.errors_F == 0 and inputs.integrity_F,
        "acceptable_A": inputs.errors_A == 0 and inputs.integrity_A,
        "bounded_F": _bounded(inputs.f_early_mean, inputs.f_late_mean),
        "bounded_A": _bounded(inputs.a_early_mean, inputs.a_late_mean),
        "economy_F": ECONOMY_NUM * inputs.f_total <= ECONOMY_DEN * inputs.r_total,
        "economy_A": ECONOMY_NUM * inputs.a_total <= ECONOMY_DEN * inputs.r_total,
        "r_grows": Fraction(inputs.r_late_mean) >= R_GROWTH_FACTOR * Fraction(inputs.r_early_mean),
        "token_diff": str(token_diff_fa(inputs.f_total, inputs.a_total))
        if min(inputs.f_total, inputs.a_total) > 0
        else "undefined",
    }


def _scale_or_inconclusive(r_grows: bool) -> str:
    return "EXPERIMENT_INCONCLUSIVE" if r_grows else "SCALE_NOT_YET_PROVEN"


def select_architecture(inputs: SelectionInputs) -> SelectionOutcome:
    """Spec §16.2 precedence, evaluated strictly top to bottom; nothing is configurable."""
    p = _predicates(inputs)

    def out(decision: str, rule: str, reason: str = "") -> SelectionOutcome:
        return SelectionOutcome(decision=decision, matched_rule=rule, predicates=p, reason=reason)

    if not inputs.completed or not inputs.scientifically_valid:
        return out("EXPERIMENT_INCONCLUSIVE", "0", "operational or scientific invalidity")
    acc_f, acc_a = p["acceptable_F"], p["acceptable_A"]
    r_grows = bool(p["r_grows"])
    if not acc_f and not acc_a:
        return out("REDESIGN_PERSISTENT_CONTEXT", "1")
    if acc_f != acc_a:
        x = "F" if acc_f else "A"
        if p[f"bounded_{x}"] and p[f"economy_{x}"]:
            return out(f"SELECT_{x}", "2A")
        if not p[f"bounded_{x}"]:
            return out("REDESIGN_PERSISTENT_CONTEXT", "2B")
        return out(_scale_or_inconclusive(r_grows), "2C")
    if not p["bounded_F"] and not p["bounded_A"]:
        return out("REDESIGN_PERSISTENT_CONTEXT", "3A")
    if p["bounded_F"] != p["bounded_A"]:
        x = "F" if p["bounded_F"] else "A"
        if p[f"economy_{x}"]:
            return out(f"SELECT_{x}", "3B")
        return out(_scale_or_inconclusive(r_grows), "3B")
    if not p["economy_F"] and not p["economy_A"]:
        return out(_scale_or_inconclusive(r_grows), "3C.a")
    if p["economy_F"] != p["economy_A"]:
        return out("SELECT_F" if p["economy_F"] else "SELECT_A", "3C.b")
    if min(inputs.f_total, inputs.a_total) <= 0:
        return out("EXPERIMENT_INCONCLUSIVE", "residual", "undefined TOKEN_DIFF_FA")
    diff = token_diff_fa(inputs.f_total, inputs.a_total)
    if diff < MEANINGFUL_DIFF:
        return out("INCONCLUSIVE_TIE", "3C.c")
    return out("SELECT_F" if inputs.f_total < inputs.a_total else "SELECT_A", "3C.c")


# --- canonical grading/preflight document -----------------------------------------------------


class Thresholds(FrozenModel):
    economy: str
    bounded_factor: str
    r_growth_factor: str
    meaningful_diff: str
    early_window: tuple[int, ...]
    late_window: tuple[int, ...]


class ExpectationsDocument(FrozenModel):
    experiment_version: str
    checkpoints: tuple[Checkpoint, ...]
    baseline_meanings: dict[Locus, str]
    current_meaning_by_t: dict[int, dict[Locus, str]]
    control_error_rules: tuple[str, ...]
    r_grading_rules: tuple[str, ...]
    persistent_rubric: dict[TransitionClass, tuple[str, ...]]
    integrity_titles: tuple[str, ...]
    grading_labels: tuple[str, ...]
    thresholds: Thresholds
    selection_precedence: str
    decision_names: tuple[str, ...]


def expectations_document() -> dict[str, Any]:
    """Canonical grading/preflight document (spec §19 step 2).

    Answer key, checkpoints, rubric, R rules, gate titles, thresholds and the
    selection precedence. Contains no runtime id and no Orion evidence text; it is
    never sent to a model.
    """
    document = ExpectationsDocument(
        experiment_version=EXPERIMENT_VERSION,
        checkpoints=CHECKPOINTS,
        baseline_meanings=BASELINE_MEANINGS,
        current_meaning_by_t=CURRENT_MEANING_BY_T,
        control_error_rules=CONTROL_ERROR_RULES,
        r_grading_rules=R_GRADING_RULES,
        persistent_rubric=PERSISTENT_RUBRIC,
        integrity_titles=INTEGRITY_TITLES,
        grading_labels=GRADING_LABELS,
        thresholds=Thresholds(
            economy=f"{ECONOMY_NUM}/{ECONOMY_DEN}",
            bounded_factor=str(BOUNDED_FACTOR),
            r_growth_factor=str(R_GROWTH_FACTOR),
            meaningful_diff=str(MEANINGFUL_DIFF),
            early_window=EARLY_WINDOW,
            late_window=LATE_WINDOW,
        ),
        selection_precedence=SELECTION_PRECEDENCE_TEXT,
        decision_names=DECISION_NAMES,
    )
    return document.model_dump(mode="json")
