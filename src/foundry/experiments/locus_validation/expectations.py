"""Hidden scientific contract of the locus-validation experiment.

Spec §2 (hypotheses), §4 (case slots and semantic classes), §6 (expected lifecycle
state), §7.1 (deterministic assertion rows and failure tags), §7.2 (architect
semantic questions) and §14 (scoring and outcome vocabulary). This module is the
answer key: grading, preflight and leakage data only. It carries no runtime id (no
address/claim/judgment id) and no evidence text, and it is never sent to a model.
No request-path module (``corpus`` and every later runner-side module) may import
it; ``corpus.py`` is checked by ``ast`` in its unit tests.

``experiment_outcome`` computes the spec §14 rule literally from already-adjudicated
inputs (rule 0 and twelve per-case booleans); it invents no semantic verdict of its
own and is called only by the adjudication writer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen.artifacts import canonical_bytes
from foundry.experiments.locus_validation.corpus import DOCUMENTS, LEDGERS, Ledger

__all__ = [
    "ASSERTION_TEXT",
    "CASES",
    "CASE_IDS",
    "CASE_OUTCOME_RULES",
    "EXPECTED_STATE",
    "FAILURE_TAGS",
    "HYPOTHESES",
    "OUTCOMES",
    "SCORING_RULE",
    "SEMANTIC_ASSERTION_IDS",
    "SEMANTIC_CLASSES",
    "SEMANTIC_QUESTIONS",
    "Case",
    "CaseOutcomeRule",
    "ExpectationsDocument",
    "SemanticClass",
    "expectations_document",
    "experiment_outcome",
]

CASE_IDS: Final[tuple[str, ...]] = ("S01", "V01", "V02", "V03", "V04", "V05")

SemanticClass = Literal[
    "SEED", "COMPATIBLE_EXTENSION", "DISTINCT_LOCUS", "RESTATEMENT", "CORRECTION"
]
SEMANTIC_CLASSES: Final[tuple[SemanticClass, ...]] = (
    "SEED",
    "COMPATIBLE_EXTENSION",
    "DISTINCT_LOCUS",
    "RESTATEMENT",
    "CORRECTION",
)


class Case(FrozenModel):
    """One case slot of spec §4 for one ledger: id, class and the document carrying it."""

    id: str = Field(min_length=1)
    semantic_class: SemanticClass
    document: str = Field(min_length=1)


# (case id, class, index of the carrying document in the ledger's document order);
# the seed covers all four documents and records the first (spec §4, §6).
_CASE_SLOTS: Final[tuple[tuple[str, SemanticClass, int], ...]] = (
    ("S01", "SEED", 0),
    ("V01", "COMPATIBLE_EXTENSION", 0),
    ("V02", "COMPATIBLE_EXTENSION", 1),
    ("V03", "DISTINCT_LOCUS", 1),
    ("V04", "RESTATEMENT", 2),
    ("V05", "CORRECTION", 3),
)

CASES: Final[dict[Ledger, tuple[Case, ...]]] = {
    ledger: tuple(
        Case(id=case_id, semantic_class=semantic_class, document=DOCUMENTS[ledger][slot])
        for case_id, semantic_class, slot in _CASE_SLOTS
    )
    for ledger in LEDGERS
}

FAILURE_TAGS: Final[tuple[str, ...]] = (
    "OVER_SPLIT",
    "UNDER_SPLIT",
    "MISSING_EXTENSION",
    "DUPLICATE_ASSERTION",
    "MISSING_SUPERSEDE",
    "WRONG_SUPERSEDE_TARGET",
    "CONFLICT_INSTEAD_OF_CORRECTION",
    "UNGOVERNED_SUPERSEDE",
    "WRONG_BIND",
    "EXTRA_DRAFT",
)

OUTCOMES: Final[tuple[str, ...]] = (
    "LOCUS_POLICY_VALIDATED",
    "LOCUS_POLICY_NOT_VALIDATED",
    "EXPERIMENT_INCONCLUSIVE",
)

# --- spec §2 hypothesis cells, verbatim ---------------------------------------------

HYPOTHESES: Final[dict[str, str]] = {
    "H0": (
        "**Creation granularity.** A seed delta of four documents, each about one locus, "
        "yields exactly four addresses, one live claim each, with locus-level facets."
    ),
    "H1": (
        "**No over-splitting.** A genuinely new proposition compatible with a known locus's "
        "current claim is asserted as an additional claim at that same address; the existing "
        "claim stays current; no address is created; nothing is superseded."
    ),
    "H2": (
        "**No under-splitting.** A proposition answering a different question is created as a "
        "new address even though it shares the subject and the document of a known locus."
    ),
    "H3": (
        "**Restatement is not re-asserted.** A rewording of a current claim yields "
        "`SUPPORTS_CLAIM` of that claim and no new claim, no new address."
    ),
    "H4": (
        "**Correction stays governed.** An incompatible value yields exactly one new claim at "
        "the same address plus one `SUPERSEDE` of the old claim's `created_by_judgment_id`, "
        "which remains pending (no human); no `CONFLICTS_WITH` in its place."
    ),
}

# --- spec §6 expected lifecycle state, bullets verbatim (joined with "\n") -------------

EXPECTED_STATE: Final[dict[str, str]] = {
    "T1": "\n".join(
        (
            "- exactly 4 active in-scope addresses `X1..X4`;",
            "- each `Xi` has exactly one live claim citing `Di-T1`;",
            "- Call 1 applied exactly 4 `CREATE_ADDRESS` (one per item) and 0 `BIND_TO_ADDRESS`; "
            "Call 2 applied exactly 4 `ASSERT_CLAIM`; 0 `SUPERSEDE`, 0 `CONFLICTS_WITH`, "
            "0 rejections.",
        )
    ),
    "T2": "\n".join(
        (
            "- exactly **5** active in-scope addresses: `X1..X4` and one new address `X5` (V03);",
            "- `X1` (V01): 2 live claims — the T1 claim (same id, still live) and exactly one new "
            "claim citing `D1'`; no supersede targets `X1`'s claims;",
            "- `X2` (V02): 2 live claims — the T1 claim and exactly one new claim citing `D2'`;",
            "- `X5` (V03): exactly 1 live claim citing `D2'`; created by a `CREATE_ADDRESS` "
            "citing `D2'`;",
            "- `X3` (V04): exactly 1 live claim (the T1 claim); at least one `SUPPORTS_CLAIM` of "
            "it citing `D3'`; **no** `ASSERT_CLAIM` cites `D3'`;",
            "- `X4` (V05): 2 live claims — the T1 claim (still live: no human authority exists) "
            "and exactly one new claim citing `D4'`; exactly one `SUPERSEDE` whose "
            "`target_judgment_id` equals the T1 claim's `created_by_judgment_id`, admitted "
            "`REQUIRE_SECOND_LENS` and never applied; 0 `CONFLICTS_WITH`;",
            "- Call-1 drafts of T2: exactly one `BIND_TO_ADDRESS` per revised document to its "
            "own T1 address (`D1'→X1`, `D2'→X2`, `D3'→X3`, `D4'→X4`) and exactly one "
            "`CREATE_ADDRESS`, citing `D2'`;",
            "- `human_authorizations == 0`; `pending_judgment_ids` == the single V05 supersede.",
        )
    ),
}

# --- spec §7.1 assertion rows, verbatim -----------------------------------------------

ASSERTION_TEXT: Final[dict[str, str]] = {
    "S01": (
        "`len(addresses) == 4`; one live claim per address; the 4 creates cite distinct items; "
        "0 binds; 0 supersede/conflict; 0 rejected admissions"
    ),
    "V01": (
        "exactly one Call-1 draft cites `D1'` and it is a `BIND` to `X1`; `X1` live claims == "
        "{T1 claim, one new claim citing `D1'`}; no `SUPERSEDE` targets `X1`'s claims; total "
        "address count unchanged by `D1'`"
    ),
    "V02": "same shape for `D2'` at `X2` (the bind and the new claim)",
    "V03": (
        "exactly one `CREATE_ADDRESS` in Call 1 of T2 and it cites `D2'`; total addresses == 5; "
        "the created address has exactly one live claim citing `D2'`; no claim citing `D2'` at "
        "any address other than `X2` and `X5`"
    ),
    "V04": (
        "exactly one Call-1 draft cites `D3'` and it is a `BIND` to `X3`; `X3` live claims == "
        "{T1 claim}; ≥ 1 `SUPPORTS_CLAIM` of that claim citing `D3'`; 0 `ASSERT_CLAIM` citing "
        "`D3'`; 0 structural duplicate rejections in the run"
    ),
    "V05": (
        "exactly one Call-1 draft cites `D4'` and it is a `BIND` to `X4`; `X4` live claims == "
        "{T1 claim, one new claim citing `D4'`}; exactly one `SUPERSEDE` in the run, target == "
        "T1 claim's `created_by_judgment_id`, route `REQUIRE_SECOND_LENS`, not applied; "
        "0 `CONFLICTS_WITH`; `human_authorizations == 0`"
    ),
}

# --- spec §7.2 architect semantic questions, verbatim ---------------------------------

SEMANTIC_ASSERTION_IDS: Final[tuple[str, ...]] = ("A-S01", "A-V01", "A-V02", "A-V03", "A-V05")

SEMANTIC_QUESTIONS: Final[dict[str, str]] = {
    "A-S01": (
        "Do the four seed facets name the locus-level question (e.g. what revocation does; "
        "how retries are timed; how long a lease lasts; how long an execution may run) rather "
        "than the first claim's specific value?"
    ),
    "A-V01": (
        "Does the new claim at `X1` state the V01 proposition (α: repeated revocation is "
        "idempotent and leaves the credential revoked; β: acknowledgement releases the reserved "
        "storage slot)?"
    ),
    "A-V02": (
        "Does the new claim at `X2` state the V02 proposition (α: jitter capped at 500 ms; "
        "β: ordering preserved across a redelivery)?"
    ),
    "A-V03": (
        "Do `X5`'s descriptors and claim denote the V03 locus (α: audit-record retention, "
        "30 days; β: delivery-receipt retention, 14 days) and nothing about `X2`'s question?"
    ),
    "A-V05": "Does the new claim at `X4` state the corrected value (α: 45 seconds; β: 48 hours)?",
}

# --- spec §14 scoring as data ---------------------------------------------------------

SCORING_RULE: Final[str] = (
    "PASS iff every deterministic assertion of its §7.1 row holds **and** its §7.2 semantic "
    'assertion (where one exists) is answered "yes". A structurally correct but semantically '
    "wrong result is a FAIL, never `INCONCLUSIVE`."
)


class CaseOutcomeRule(FrozenModel):
    """Spec §14 per case: structural holds and the semantic answer, where one exists, is yes."""

    case_id: str = Field(min_length=1)
    semantic_assertion_id: str | None

    def case_passes(self, *, structural: bool, semantic: bool | None) -> bool:
        """Apply the rule; an unanswered or spurious semantic answer is a protocol error."""
        if self.semantic_assertion_id is None:
            if semantic is not None:
                raise ValueError(f"case {self.case_id} has no semantic assertion")
            return structural
        if semantic is None:
            raise ValueError(
                f"case {self.case_id} requires an answer to {self.semantic_assertion_id}"
            )
        return structural and semantic


def _semantic_assertion_for(case_id: str) -> str | None:
    candidate = f"A-{case_id}"
    return candidate if candidate in SEMANTIC_ASSERTION_IDS else None


CASE_OUTCOME_RULES: Final[dict[str, CaseOutcomeRule]] = {
    case_id: CaseOutcomeRule(
        case_id=case_id, semantic_assertion_id=_semantic_assertion_for(case_id)
    )
    for case_id in CASE_IDS
}


def experiment_outcome(*, rule_zero: bool, case_passes: Mapping[tuple[Ledger, str], bool]) -> str:
    """Spec §14 experiment outcome from adjudicated inputs.

    Rule 0 (experiment invalidity) outranks every case; otherwise all twelve case
    instances must pass for validation. Exactly the twelve ``(ledger, case_id)``
    keys are required. Pure; called only by the adjudication writer.
    """
    expected = {(ledger, case_id) for ledger in LEDGERS for case_id in CASE_IDS}
    if set(case_passes) != expected:
        missing = sorted(expected - set(case_passes))
        extra = sorted(set(case_passes) - expected)
        raise ValueError(f"case_passes must carry exactly 12 keys; missing={missing} extra={extra}")
    if rule_zero:
        return "EXPERIMENT_INCONCLUSIVE"
    if all(case_passes[key] for key in expected):
        return "LOCUS_POLICY_VALIDATED"
    return "LOCUS_POLICY_NOT_VALIDATED"


class ExpectationsDocument(FrozenModel):
    case_ids: tuple[str, ...]
    semantic_classes: tuple[str, ...]
    cases: dict[str, tuple[Case, ...]]
    failure_tags: tuple[str, ...]
    outcomes: tuple[str, ...]
    hypotheses: dict[str, str]
    expected_state: dict[str, str]
    assertion_text: dict[str, str]
    semantic_assertion_ids: tuple[str, ...]
    semantic_questions: dict[str, str]
    scoring_rule: str
    case_outcome_rules: dict[str, CaseOutcomeRule]


def expectations_document() -> dict[str, Any]:
    """Canonical answer-key document: sorted keys, deterministic, no runtime id or evidence text."""
    document = ExpectationsDocument(
        case_ids=CASE_IDS,
        semantic_classes=SEMANTIC_CLASSES,
        cases={ledger: CASES[ledger] for ledger in LEDGERS},
        failure_tags=FAILURE_TAGS,
        outcomes=OUTCOMES,
        hypotheses=HYPOTHESES,
        expected_state=EXPECTED_STATE,
        assertion_text=ASSERTION_TEXT,
        semantic_assertion_ids=SEMANTIC_ASSERTION_IDS,
        semantic_questions=SEMANTIC_QUESTIONS,
        scoring_rule=SCORING_RULE,
        case_outcome_rules=CASE_OUTCOME_RULES,
    )
    loaded: dict[str, Any] = json.loads(canonical_bytes(document))
    return loaded
