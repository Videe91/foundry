"""REQUIREMENT versus CONSTRAINT: the ontology reaches the model, and exam v3 tests both sides.

The defect (found auditing Grok's exam-v2 case A, 2026-09-28): Foundry's ontology separates a
REQUIREMENT ("required obligation", IE2 §2) from a CONSTRAINT ("hard boundary on the solution
space"), and the two behave differently downstream (a PROPOSED Constraint blocks closure; a
PROPOSED Requirement does not, IE3 §15). The runtime-v2 prompt named both kinds but defined
neither, the facet meanings never reached the schema, and case A's claim carried only a bare
value. The exam scored the distinction anyway, and never once required a CONSTRAINT.

Runtime-v3 gives the model the ontology (never an expected answer). Exam v3 states every claim
as a proposition, and adds a paired case whose two claims share their modality ("must ...
within") yet differ in kind, so neither keyword matching nor "always REQUIREMENT" can pass it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import tests.certification._intent_graph_exam as exam
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION,
    IntentGraphDraftPayload,
)
from foundry.application.intent_graph_synthesis import (
    GRAPH_SYNTHESIS_POLICY_VERSION as FENCE,
)
from foundry.domain.semantic import SemanticKind
from tests.certification._exam_identity import canonical_digest
from tests.certification._intent_graph_exam import (
    EXPECTED_GRAPH_EXAM_SHA256,
    GRAPH_BUILDERS,
    GRAPH_CASES,
    GRAPH_EXAM_VERSION,
    SUPERSEDED_GRAPH_EXAMS,
    graph_certificate_standing,
    graph_exam_sha256,
)
from tests.certification.test_intent_graph_exam_harness import (
    CORRECT,
    _request,
    attempt,
    fails,
    passes,
)
from tests.unit._ie3_fixtures import b, e, edge, node

K = SemanticKind
S = exam.RelationType.SERVES
D = exam.RelationType.DERIVED_FROM
EVIDENCE = Path(__file__).parent / "evidence"
V2_MANIFEST = Path(__file__).parent / "exam_manifests" / "ie3-graph-exam-v2.json"


def _prompt() -> str:
    return " ".join(GRAPH_SYSTEM_INSTRUCTION.split())


# --------------------------------------------------------------------------- 1-3 the contract


def test_1_requirement_semantics_are_in_the_model_facing_contract() -> None:
    prompt = _prompt()
    assert "REQUIREMENT: a required obligation." in prompt
    assert (
        "It states a behaviour, capability, outcome, policy obligation or condition that the "
        "system or process being built must deliver or satisfy." in prompt
    )


def test_2_constraint_semantics_are_in_the_model_facing_contract() -> None:
    prompt = _prompt()
    assert "CONSTRAINT: a hard, non-tradeable boundary on the solution space." in prompt
    assert (
        "It does not state what is delivered; it restricts how any solution may be designed, "
        "built, hosted, sourced or operated." in prompt
    )
    for facet in ("EXTERNAL_MANDATE:", "PROJECT_BOUNDARY:", "EVIDENCE_BOUND:"):
        assert facet in prompt, "every facet's relaxation meaning is visible"


def test_3_the_distinction_is_semantic_not_modal_wording() -> None:
    prompt = _prompt()
    assert "Choose a kind by what the meaning does, never by its wording." in prompt
    assert (
        "Words such as must, may, only, within, at most or never appear in both kinds and "
        "never decide the kind." in prompt
    )
    assert "Ask what the meaning governs." in prompt


def test_every_legal_kind_is_defined() -> None:
    prompt = _prompt()
    for kind in (
        "INTENT",
        "GOAL",
        "OUTCOME",
        "REQUIREMENT",
        "CONSTRAINT",
        "NON_GOAL",
        "PREFERENCE",
        "DECISION",
        "ASSUMPTION",
    ):
        assert f"{kind}: " in prompt, kind


def test_the_contract_carries_ontology_not_exam_answers() -> None:
    prompt = _prompt().lower()
    for leaked in ("refund", "uk", "thirty", "approval", "case a", "case i", "scorer"):
        assert not re.search(rf"\b{leaked}\b", prompt), leaked


def test_the_contract_version_moved_with_the_text() -> None:
    assert GRAPH_SYNTHESIS_POLICY_VERSION == "intent-graph-synthesis-runtime-v3"
    assert FENCE == GRAPH_SYNTHESIS_POLICY_VERSION
    assert exam.EXPECTED_GRAPH_POLICY_VERSION == GRAPH_SYNTHESIS_POLICY_VERSION


# --------------------------------------------------------------------------- the paired case


def _claims(case_id: str) -> dict[str, dict[str, Any]]:
    """What the model is shown for each claim of a case, keyed by the exam's claim name."""
    substrate = GRAPH_BUILDERS[case_id]()
    request = _request(case_id)
    shown = {
        claim.claim_id: {
            "subject": locus.subject,
            "facet": locus.facet,
            "predicate": claim.predicate,
            "value": claim.value.text,
        }
        for locus in request.basis
        for claim in locus.live_claims
    }
    return {name: shown[cid] for name, cid in substrate.claim_ids.items() if cid in shown}


def test_the_paired_case_shares_modality_and_differs_only_in_what_is_governed() -> None:
    shown = _claims("I")
    obligation, boundary = shown["obligation"]["value"], shown["boundary"]["value"]
    for text in (obligation, boundary):
        assert re.search(r"\bmust\b", text) and re.search(r"\bwithin\b", text), text
    assert "refund" in obligation.lower() and "refund" in boundary.lower()
    assert shown["obligation"]["predicate"] != shown["boundary"]["predicate"]


@pytest.mark.parametrize(
    ("case_id", "name", "needles"),
    [
        ("A", "refund", ("refunds must complete", "thirty calendar days", "after approval")),
        ("I", "obligation", ("refund processing must complete", "thirty calendar days")),
        ("I", "boundary", ("refund-processing data must remain", "uk-hosted infrastructure")),
    ],
)
def test_8_the_request_shown_to_the_model_carries_the_whole_proposition(
    case_id: str, name: str, needles: tuple[str, ...]
) -> None:
    shown = _claims(case_id)[name]
    text = " ".join(str(v) for v in shown.values()).lower()
    for needle in needles:
        assert needle in text, (needle, shown)


def _answer(obligation_kind: SemanticKind, boundary_kind: SemanticKind) -> Any:
    def answer(s: Any) -> object:
        def made(local: str, kind: SemanticKind, statement: str, claim: str) -> Any:
            extra = {"facet": "PROJECT_BOUNDARY"} if kind is K.CONSTRAINT else {}
            return (
                node(kind, local, statement=statement, **extra),
                (edge(local, S, e("GOAL-refunds")), edge(local, D, b(s.claim_ids[claim]))),
            )

        first, first_rels = made(
            "completion",
            obligation_kind,
            "Refund processing must complete within thirty calendar days after approval.",
            "obligation",
        )
        second, second_rels = made(
            "hosting",
            boundary_kind,
            "Refund-processing data must remain within approved UK-hosted infrastructure.",
            "boundary",
        )
        return IntentGraphDraftPayload(nodes=(first, second), relations=(*first_rels, *second_rels))

    return answer


def test_6_7_the_correct_pair_passes() -> None:
    passes("I", _answer(K.REQUIREMENT, K.CONSTRAINT))
    passes("I", CORRECT["I"])


def test_4_the_obligation_as_constraint_fails() -> None:
    fails("I", _answer(K.CONSTRAINT, K.CONSTRAINT), "REQUIREMENT")


def test_5_the_boundary_as_requirement_fails() -> None:
    fails("I", _answer(K.REQUIREMENT, K.REQUIREMENT), "CONSTRAINT")


def test_11_swapping_the_two_kinds_fails() -> None:
    fails("I", _answer(K.CONSTRAINT, K.REQUIREMENT), "must be exactly one REQUIREMENT")


def test_case_a_scores_the_obligation_as_constraint_wrong() -> None:
    def as_constraint(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(
                node(
                    K.CONSTRAINT,
                    "req",
                    statement="Refunds must complete within thirty calendar days after approval.",
                    facet="PROJECT_BOUNDARY",
                ),
            ),
            relations=(edge("req", S, e("GOAL-refunds")), edge("req", D, b(s.claim_ids["refund"]))),
        )

    fails("A", as_constraint, "Requirement")


def test_the_pair_rejects_one_node_standing_for_both_claims() -> None:
    def merged(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(
                node(
                    K.REQUIREMENT,
                    "both",
                    statement="Refund processing must complete within thirty calendar days "
                    "and its data must remain within approved UK-hosted infrastructure.",
                ),
            ),
            relations=(
                edge("both", S, e("GOAL-refunds")),
                edge("both", D, b(s.claim_ids["obligation"])),
                edge("both", D, b(s.claim_ids["boundary"])),
            ),
        )

    fails("I", merged, "CONSTRAINT")


# --------------------------------------------------------------------------- always-one-kind


@pytest.mark.parametrize("kind", [K.REQUIREMENT, K.CONSTRAINT])
def test_a_contestant_that_always_chooses_one_kind_cannot_score_perfectly(
    kind: SemanticKind,
) -> None:
    observation, substrate = attempt("I", _answer(kind, kind))
    with pytest.raises(exam.ExamFailure):
        exam.score_graph_attempt(observation, substrate, candidate=exam_fake())


def exam_fake() -> Any:
    from tests.certification.test_intent_graph_exam_harness import FAKE

    return FAKE


def test_exam_v3_has_both_kinds_as_required_answers() -> None:
    assert GRAPH_CASES == ("A", "B", "C", "D", "E", "F", "G", "H", "I")
    assert GRAPH_EXAM_VERSION == "4"  # v3 introduced case I; v4 kept it
    for case_id in GRAPH_CASES:
        passes(case_id, CORRECT[case_id])


# --------------------------------------------------------------------------- 9 exam v2 frozen


def test_9_exam_v2_is_frozen_and_reproducible_from_its_manifest() -> None:
    manifest = json.loads(V2_MANIFEST.read_text())
    assert canonical_digest(manifest) == (
        "813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c"
    )
    assert manifest["exam_version"] == "2"
    assert sorted(manifest["cases"]) == ["A", "B", "C", "D", "E", "F", "G", "H"]


def test_exam_v3_is_frozen_and_distinct() -> None:
    assert graph_exam_sha256() == EXPECTED_GRAPH_EXAM_SHA256
    assert EXPECTED_GRAPH_EXAM_SHA256 != (
        "813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c"
    )


# --------------------------------------------------------------------------- 7 supersession


def test_exam_v2_is_recorded_as_superseded_with_its_defect() -> None:
    (v2,) = [s for s in SUPERSEDED_GRAPH_EXAMS if s.exam_version == "2"]
    assert v2.exam_sha256 == "813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c"
    assert v2.superseded_by == "3"
    assert "REQUIREMENT" in v2.defect and "CONSTRAINT" in v2.defect
    assert v2.not_a_precedent_for == "REQUIREMENT_VERSUS_CONSTRAINT"


def _record(relative: str) -> dict[str, Any]:
    return json.loads((EVIDENCE / relative).read_text())


def test_astra_exam_v2_certificate_is_historically_valid_but_superseded() -> None:
    record = _record("openai/gpt-6-astra/intent_graph_synthesis_exam_bound/certification.json")
    assert record["verdict"] == "PASS" and record["exam_version"] == "2"
    assert graph_certificate_standing(record) == "SUPERSEDED"


def test_the_grok_exam_v2_run_is_diagnostic_not_certified() -> None:
    record = _record("xai/grok-4.7/intent_graph_synthesis_exam_bound/certification.json")
    assert record["verdict"] == "NOT CERTIFIED" and record["exam_version"] == "2"
    assert graph_certificate_standing(record) == "NOT_CERTIFIED"
    kind_failures = [
        (a["case"], a["attempt"]) for a in record["attempts"] if a["verdict"] == "FAIL"
    ]
    assert kind_failures == [("A", 2), ("A", 3)], "the unencoded-dimension failures, unchanged"


@pytest.mark.parametrize(
    "relative",
    [
        "xai/grok-4.7/intent_graph_synthesis/certification.json",
        "xai/grok-4.7/intent_graph_synthesis_v2/certification.json",
        "openai/gpt-6-astra/intent_graph_synthesis_v2/certification.json",
        "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/certification.json",
    ],
)
def test_older_records_keep_their_historical_standing(relative: str) -> None:
    assert graph_certificate_standing(_record(relative)) in {"NOT_CERTIFIED", "HISTORICAL_FORMAT"}


def test_only_a_record_for_the_current_contract_and_exam_is_current() -> None:
    current = _record("openai/gpt-6-astra/intent_graph_synthesis_exam_bound/certification.json")
    current = {
        **current,
        "policy_version": GRAPH_SYNTHESIS_POLICY_VERSION,
        "prompt_sha256": exam.GRAPH_SYSTEM_INSTRUCTION_SHA256,
        "exam_version": GRAPH_EXAM_VERSION,
        "exam_sha256": EXPECTED_GRAPH_EXAM_SHA256,
    }
    assert graph_certificate_standing(current) == "CURRENT"
    assert graph_certificate_standing({**current, "exam_sha256": "0" * 64}) == "NOT_BINDING"
