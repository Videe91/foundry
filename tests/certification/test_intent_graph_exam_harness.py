"""IE3 graph certification exam — offline proof that the exam is sound and can fail.

No provider is reached here: every attempt runs the real production path (real substrate, real
context compiler, real ``synthesize_intent_graph``, real Model Runtime, real graph adapter) with
a strict ``FakeModelProvider`` scripted per test. That proves three things before any live call:

* **integrity:** each case shows the model exactly what the case claims, including that the
  hidden object is genuinely absent (case E) and the stale object is genuinely flagged (F);
* **passability:** a correct answer passes every case end to end, so a live failure cannot be
  blamed on an impossible exam;
* **falsifiability:** wrong answers are rejected, case by case, by deterministic scoring. An
  exam that cannot fail certifies nothing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_ID,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
    IntentGraphDraftPayload,
    IntentGraphGapDraft,
)
from foundry.application.intent_graph_synthesis_context import compile_intent_graph_context
from foundry.domain.common import RelationType
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import MissingNeed
from foundry.domain.semantic import SemanticKind
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from tests.certification._certification_run import Contestant, ProtocolTaskFailure
from tests.certification._intent_graph_exam import (
    EXPECTED_GRAPH_POLICY_ID,
    EXPECTED_GRAPH_POLICY_VERSION,
    EXPECTED_GRAPH_PROMPT_SHA256,
    GRAPH_BUILDERS,
    GRAPH_CASES,
    GRAPH_EVIDENCE_NAMESPACE,
    GRAPH_RUNS_PER_CASE,
    GraphObservation,
    certificate_binds,
    run_graph_attempt,
    score_graph_attempt,
)
from tests.certification._intent_synthesis_exam import SCOPE, ExamFailure, Substrate, state_of
from tests.unit._ie3_fixtures import b, e, edge, node

K = SemanticKind
S = RelationType.SERVES
D = RelationType.DERIVED_FROM
FAKE = ModelIdentity(provider="fake-graph", model="graph-contestant")
CONTESTANT = Contestant(
    identity=FAKE,
    credential_env="UNUSED",
    provider_factory=lambda _: None,
    task=ModelTask.INTENT_GRAPH_SYNTHESIS,
    evidence_namespace=GRAPH_EVIDENCE_NAMESPACE,
)


def _gap(local_gap_id: str, kind: GapKind, *anchors: Any) -> IntentGraphGapDraft:
    return IntentGraphGapDraft(
        local_gap_id=local_gap_id,
        kind=kind,
        description="The supplied material does not settle this.",
        missing_need=MissingNeed.PROJECT_CHOICE,
        anchors=anchors,
    )


def attempt(
    case_id: str,
    answer: Callable[[Substrate], object],
    *,
    reported_model: str | None = None,
    scripts: int = 1,
) -> tuple[GraphObservation, Substrate]:
    substrate = GRAPH_BUILDERS[case_id]()
    output = answer(substrate)
    provider = FakeModelProvider(
        provider_id=FAKE.provider,
        responses=tuple(
            ScriptedResponse(output=output, model=reported_model or FAKE.model)
            for _ in range(scripts)
        ),
    )
    observation = run_graph_attempt(CONTESTANT, substrate, case_id, 1, provider=provider)
    return observation, substrate


def passes(case_id: str, answer: Callable[[Substrate], object]) -> None:
    observation, substrate = attempt(case_id, answer)
    score_graph_attempt(observation, substrate, candidate=FAKE)


def fails(case_id: str, answer: Callable[[Substrate], object], match: str) -> None:
    observation, substrate = attempt(case_id, answer)
    with pytest.raises(ExamFailure, match=match):
        score_graph_attempt(observation, substrate, candidate=FAKE)


# ---------------------------------------------------------------- the frozen contestant


def test_the_exam_is_frozen_to_the_current_graph_contract() -> None:
    import hashlib

    from foundry.adapters.intent_graph_synthesis.model_runtime import GRAPH_SYSTEM_INSTRUCTION

    assert EXPECTED_GRAPH_PROMPT_SHA256 == (
        "e8e1763db2c7f7df1496406082d0e0014b4de0f0ecea80f6e1e535951a97e605"
    )
    assert hashlib.sha256(GRAPH_SYSTEM_INSTRUCTION.encode()).hexdigest() == (
        EXPECTED_GRAPH_PROMPT_SHA256
    )
    assert GRAPH_SYSTEM_INSTRUCTION_SHA256 == EXPECTED_GRAPH_PROMPT_SHA256
    assert GRAPH_SYNTHESIS_POLICY_ID == EXPECTED_GRAPH_POLICY_ID
    assert GRAPH_SYNTHESIS_POLICY_VERSION == EXPECTED_GRAPH_POLICY_VERSION


def test_the_matrix_and_rule_reuse_the_existing_protocol() -> None:
    assert GRAPH_CASES == ("A", "B", "C", "D", "E", "F", "G", "H")
    assert GRAPH_RUNS_PER_CASE == 3
    assert set(GRAPH_BUILDERS) == set(GRAPH_CASES)


def test_graph_evidence_never_shares_a_path_with_slice_1_evidence() -> None:
    slice1 = Contestant(identity=FAKE, credential_env="UNUSED", provider_factory=lambda _: None)
    assert CONTESTANT.evidence_dir == slice1.evidence_dir / GRAPH_EVIDENCE_NAMESPACE
    assert CONTESTANT.measurements_path != slice1.measurements_path
    (descriptor,) = CONTESTANT.registry().descriptors
    assert descriptor.certified_tasks == frozenset({ModelTask.INTENT_GRAPH_SYNTHESIS})


def test_the_live_exam_is_double_opt_in() -> None:
    import tests.certification.test_grok_4_7_intent_graph_synthesis_live as live

    enabled = bool(
        os.environ.get("XAI_API_KEY") and os.environ.get("RUN_LIVE_MODEL_CERTIFICATION") == "1"
    )
    (mark,) = [m for m in live.pytestmark if m.name == "skipif"]  # type: ignore[attr-defined]
    assert mark.args[0] is (not enabled)
    assert "LIVE_MODEL_CERTIFICATION_NOT_ENABLED" in mark.kwargs["reason"]


# ------------------------------------------------------------------- exam integrity


def _request(case_id: str) -> Any:
    request = compile_intent_graph_context(
        state_of(GRAPH_BUILDERS[case_id]().store), scope=SCOPE
    ).request
    assert request is not None
    return request


def _shown(case_id: str) -> dict[str, Any]:
    return {o.object_id: o for o in _request(case_id).known_objects}


def _claims(case_id: str) -> set[str]:
    return {c.claim_id for locus in _request(case_id).basis for c in locus.live_claims}


def test_integrity_b_the_same_thing_is_shown_current_and_fresh() -> None:
    existing = _shown("B")["REQ-existing"]
    assert existing.is_stale is False
    assert existing.text == "Refund requests are accepted within 30 days of purchase."


def test_integrity_c_the_changed_object_is_shown_stale_with_the_corrected_claim() -> None:
    assert _shown("C")["REQ-old"].is_stale is True
    substrate = GRAPH_BUILDERS["C"]()
    assert substrate.claim_ids["corrected"] in _claims("C")
    assert substrate.claim_ids["old"] not in _claims("C")


def test_integrity_d_both_competing_claims_are_shown() -> None:
    substrate = GRAPH_BUILDERS["D"]()
    assert {substrate.claim_ids["seven"], substrate.claim_ids["thirty"]} <= _claims("D")


def test_integrity_e_the_hidden_object_exists_but_is_never_shown() -> None:
    substrate = GRAPH_BUILDERS["E"]()
    assert "REQ-hidden" in state_of(substrate.store).objects
    assert "REQ-hidden" not in _shown("E")
    assert "REQ-hidden" not in _request("E").model_dump_json()


def test_integrity_f_stale_is_flagged_and_dead_is_absent() -> None:
    shown = _shown("F")
    assert shown["REQ-stale"].is_stale is True
    assert "REQ-dead" not in shown
    assert "REQ-dead" not in _request("F").model_dump_json()


def test_integrity_g_the_conflicting_non_goal_is_shown() -> None:
    assert _shown("G")["NG-digital"].kind is K.NON_GOAL


def test_integrity_h_both_claims_and_the_represented_object_are_shown() -> None:
    substrate = GRAPH_BUILDERS["H"]()
    assert {substrate.claim_ids["window"], substrate.claim_ids["payment"]} <= _claims("H")
    assert _shown("H")["REQ-existing"].is_stale is False


# ------------------------------------------------------------ correct answers pass


def _req(local_id: str, statement: str, claim: str, *extra: Any) -> tuple[Any, tuple[Any, ...]]:
    return (
        node(K.REQUIREMENT, local_id, statement=statement),
        (edge(local_id, S, e("GOAL-refunds")), edge(local_id, D, b(claim)), *extra),
    )


def _new_answer(key: str, statement: str) -> Callable[[Substrate], object]:
    def answer(substrate: Substrate) -> object:
        req, rels = _req("req", statement, substrate.claim_ids[key])
        return IntentGraphDraftPayload(nodes=(req,), relations=rels)

    return answer


CORRECT: dict[str, Callable[[Substrate], object]] = {
    "A": _new_answer("refund", "Refunds must complete within thirty calendar days after approval."),
    "B": lambda s: IntentGraphDraftPayload(unchanged_object_refs=(e("REQ-existing"),)),
    "C": lambda s: IntentGraphDraftPayload(
        nodes=(
            node(
                K.REQUIREMENT,
                "req",
                statement="Refund requests are accepted within 14 days of purchase.",
                disposition="REPLACES_STALE",
                replaces=e("REQ-old"),
            ),
        ),
        relations=(edge("req", S, e("GOAL-refunds")), edge("req", D, b(s.claim_ids["corrected"]))),
    ),
    "D": lambda s: IntentGraphDraftPayload(
        gaps=(_gap("window", GapKind.AMBIGUITY, b(s.claim_ids["seven"]), b(s.claim_ids["thirty"])),)
    ),
    "E": _new_answer("refund", "Refund requests are accepted within 30 days of purchase."),
    "F": lambda s: IntentGraphDraftPayload(
        nodes=(
            node(
                K.REQUIREMENT,
                "req",
                statement="Refund requests are accepted within 30 days of purchase.",
                disposition="REPLACES_STALE",
                replaces=e("REQ-stale"),
            ),
        ),
        relations=(edge("req", S, e("GOAL-refunds")), edge("req", D, b(s.claim_ids["restated"]))),
    ),
    "G": lambda s: IntentGraphDraftPayload(
        gaps=(_gap("conflict", GapKind.CONTRADICTION, e("NG-digital"), b(s.claim_ids["digital"])),)
    ),
    "H": lambda s: IntentGraphDraftPayload(
        nodes=(
            node(
                K.REQUIREMENT, "pay", statement="Refunds are paid to the original payment method."
            ),
        ),
        relations=(edge("pay", S, e("GOAL-refunds")), edge("pay", D, b(s.claim_ids["payment"]))),
        unchanged_object_refs=(e("REQ-existing"),),
    ),
}


@pytest.mark.parametrize("case_id", ["A", "B", "C", "D", "E", "F", "G", "H"])
def test_a_correct_answer_passes_every_case_end_to_end(case_id: str) -> None:
    passes(case_id, CORRECT[case_id])


def test_f_also_accepts_an_honest_gap_instead_of_the_replacement() -> None:
    passes(
        "F",
        lambda s: IntentGraphDraftPayload(
            gaps=(_gap("stale", GapKind.MISSING_INFORMATION, e("REQ-stale")),)
        ),
    )


def test_a_passing_attempt_records_the_contestant_and_the_graph_task() -> None:
    observation, _ = attempt("B", CORRECT["B"])
    assert observation.evidence is not None
    assert observation.evidence.task == "INTENT_GRAPH_SYNTHESIS"
    assert observation.evidence.tier == "REASONER"
    assert observation.provider_calls == 1
    assert observation.raw_draft is not None
    assert observation.record is not None
    assert observation.record.author.policy_version == EXPECTED_GRAPH_POLICY_VERSION


# ------------------------------------------------------------------ wrong answers fail


def test_a_rejects_an_invented_existing_witness() -> None:
    def answer(s: Substrate) -> object:
        req, rels = _req("req", "Refunds must complete within thirty days.", s.claim_ids["refund"])
        return IntentGraphDraftPayload(
            nodes=(req,), relations=rels, unchanged_object_refs=(e("GOAL-refunds"),)
        )

    fails("A", answer, "witness")


def test_a_rejects_a_requirement_that_lost_the_thirty_day_window() -> None:
    fails("A", _new_answer("refund", "Refunds must be processed promptly."), "refund window")


def test_b_rejects_a_duplicate_new_requirement() -> None:
    fails(
        "B",
        _new_answer("refund", "Refunds may be requested up to thirty days after purchase."),
        "NO_CHANGE",
    )


def test_b_rejects_a_witness_on_the_wrong_object() -> None:
    fails(
        "B",
        lambda s: IntentGraphDraftPayload(unchanged_object_refs=(e("GOAL-refunds"),)),
        "REQ-existing",
    )


def test_c_rejects_no_change_on_a_real_change() -> None:
    fails("C", lambda s: IntentGraphDraftPayload(unchanged_object_refs=(e("REQ-old"),)), "refused")


def test_c_rejects_a_new_duplicate_instead_of_a_replacement() -> None:
    fails(
        "C",
        _new_answer("corrected", "Refund requests are accepted within 14 days of purchase."),
        "REPLACES_STALE",
    )


def test_d_rejects_an_invented_choice() -> None:
    fails(
        "D", _new_answer("thirty", "Refunds must complete within thirty calendar days."), "invented"
    )


def test_e_rejects_citing_the_hidden_object() -> None:
    fails(
        "E", lambda s: IntentGraphDraftPayload(unchanged_object_refs=(e("REQ-hidden"),)), "refused"
    )


def test_f_rejects_a_stale_witness() -> None:
    fails(
        "F", lambda s: IntentGraphDraftPayload(unchanged_object_refs=(e("REQ-stale"),)), "refused"
    )


def test_f_rejects_a_duplicate_that_leaves_staleness_unaddressed() -> None:
    fails(
        "F",
        _new_answer("restated", "Refund requests are accepted within 30 days of purchase."),
        "stale",
    )


def test_g_rejects_proposing_the_excluded_node() -> None:
    fails(
        "G",
        _new_answer("digital", "Digital download purchases may be refunded within thirty days."),
        "NonGoal",
    )


def test_g_rejects_a_gap_that_is_not_a_contradiction_on_the_non_goal() -> None:
    fails(
        "G",
        lambda s: IntentGraphDraftPayload(
            gaps=(_gap("q", GapKind.AMBIGUITY, b(s.claim_ids["digital"])),)
        ),
        "CONTRADICTION",
    )


def test_h_rejects_a_missing_witness() -> None:
    def answer(s: Substrate) -> object:
        req, rels = _req(
            "pay", "Refunds are paid to the original payment method.", s.claim_ids["payment"]
        )
        return IntentGraphDraftPayload(nodes=(req,), relations=rels)

    fails("H", answer, "REQ-existing")


def test_h_rejects_duplicating_the_represented_window() -> None:
    def answer(s: Substrate) -> object:
        pay, pay_rels = _req(
            "pay", "Refunds are paid to the original payment method.", s.claim_ids["payment"]
        )
        win, win_rels = _req(
            "win", "Refund requests are accepted within 30 days of purchase.", s.claim_ids["window"]
        )
        return IntentGraphDraftPayload(
            nodes=(pay, win),
            relations=(*pay_rels, *win_rels),
            unchanged_object_refs=(e("REQ-existing"),),
        )

    fails("H", answer, "duplicat")


def test_an_unlawful_graph_is_a_scored_refusal_not_a_pass() -> None:
    """The deterministic layers stay authoritative: an ungrounded model node is refused."""
    fails(
        "A",
        lambda s: IntentGraphDraftPayload(
            nodes=(node(K.REQUIREMENT, "req", statement="Refunds within thirty days."),),
            relations=(edge("req", S, e("GOAL-refunds")),),
        ),
        "refused",
    )


def test_a_model_substitution_is_a_protocol_failure_not_a_score() -> None:
    with pytest.raises(ProtocolTaskFailure):
        attempt("B", CORRECT["B"], reported_model="some-other-model")


def test_global_gates_reject_missing_evidence_and_foreign_identity() -> None:
    observation, substrate = attempt("B", CORRECT["B"])
    from dataclasses import replace

    with pytest.raises(ExamFailure, match="evidence"):
        score_graph_attempt(replace(observation, evidence=None), substrate, candidate=FAKE)
    with pytest.raises(ExamFailure, match="candidate"):
        score_graph_attempt(
            observation, substrate, candidate=ModelIdentity(provider="xai", model="grok-4.7")
        )
    with pytest.raises(ExamFailure, match="one provider call"):
        score_graph_attempt(replace(observation, provider_calls=2), substrate, candidate=FAKE)


# ---------------------------------------------------------------- certificate binding


RECORD = {
    "verdict": "PASS",
    "provider": "xai",
    "model": "grok-4.7",
    "task": "INTENT_GRAPH_SYNTHESIS",
    "policy_id": EXPECTED_GRAPH_POLICY_ID,
    "policy_version": EXPECTED_GRAPH_POLICY_VERSION,
    "prompt_sha256": EXPECTED_GRAPH_PROMPT_SHA256,
}
GROK = ModelIdentity(provider="xai", model="grok-4.7")


def _binds(record: dict[str, Any], **overrides: Any) -> bool:
    fields: dict[str, Any] = {
        "identity": GROK,
        "task": ModelTask.INTENT_GRAPH_SYNTHESIS,
        "policy_id": EXPECTED_GRAPH_POLICY_ID,
        "policy_version": EXPECTED_GRAPH_POLICY_VERSION,
        "prompt_sha256": EXPECTED_GRAPH_PROMPT_SHA256,
    }
    fields.update(overrides)
    return certificate_binds(record, **fields)


def test_a_passing_record_binds_exactly_its_contestant() -> None:
    assert _binds(RECORD)


@pytest.mark.parametrize(
    "override",
    [
        {"prompt_sha256": "0" * 64},
        {"identity": ModelIdentity(provider="xai", model="grok-4.8")},
        {"identity": ModelIdentity(provider="openai", model="grok-4.7")},
        {"policy_version": "intent-graph-synthesis-runtime-v3"},
        {"policy_id": "intent-synthesis.slice1"},
        {"task": ModelTask.INTENT_SYNTHESIS},
    ],
    ids=lambda o: next(iter(o)),
)
def test_a_changed_prompt_model_policy_or_task_is_not_certified_by_an_old_record(
    override: dict[str, Any],
) -> None:
    assert not _binds(RECORD, **override)


def test_a_failed_record_certifies_nothing() -> None:
    assert not _binds({**RECORD, "verdict": "NOT CERTIFIED"})


def test_an_incomplete_record_certifies_nothing() -> None:
    assert not _binds({k: v for k, v in RECORD.items() if k != "prompt_sha256"})
