"""The structured exam's certification harness, offline: every attempt through the production
structured verifier, the Model Runtime and contract-bound routing, against scripted answers.

A perfect structured verifier is certified on all ``case_count * 3`` attempts. Always-COMPLETE,
right verdicts with wrong evidence, wrong kinds, wrong directions, fabricated quotes, wrong
claim references and a v1-format answer are not. The same answers with any explanation text
earn exactly the same result. No model adjudicates anything.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_V1_CONTRACT,
    COMPLETENESS_V2_CONTRACT,
    STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION,
)
from foundry.domain.semantic_completeness import (
    CompletenessRequest,
    SemanticFinding,
)
from foundry.model_runtime.domain import CertifiedContract, ModelIdentity, ModelTask
from foundry.model_runtime.errors import ModelUnavailableError
from tests.certification._certification_run import Contestant
from tests.certification._completeness_exam import (
    COMPLETENESS_TIMEOUT_SECONDS,
    attempt_evidence,
    normalise,
    render_request,
)
from tests.certification._structured_completeness_exam import (
    CALL_BUDGET,
    CASES,
    RUNS_PER_CASE,
    StructuredCase,
    case_by_id,
    perfect_findings,
    run_structured_attempt,
    score_structured_attempt,
    score_structured_report,
    scripted_report,
    structured_verdict,
)
from tests.certification._structured_diagnostic import TRANSLATIONS
from tests.certification.test_semantic_completeness_exam_v2_harness import (
    ScriptedVerifierProvider,
)

SCRIPTED = ModelIdentity(provider="scripted", model="verifier-model")
V2_SITTING = (
    CertifiedContract(
        task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION, contract=COMPLETENESS_V2_CONTRACT
    ),
)

Findings = Callable[[StructuredCase], dict[str, tuple[SemanticFinding, ...]]]


def _contestant(contracts: tuple[CertifiedContract, ...] = V2_SITTING) -> Contestant:
    return Contestant(
        identity=SCRIPTED,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        timeout_seconds=COMPLETENESS_TIMEOUT_SECONDS,
        task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
        evidence_namespace="unused",
        wire_schema=OpenAIModelProvider.wire_schema,
        wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
        contracts=contracts,
    )


def _case_of(request: CompletenessRequest) -> StructuredCase:
    (case,) = [c for c in CASES if c.request == request]
    return case


def answering(findings: Findings) -> Callable[[CompletenessRequest], Any]:
    def answer(request: CompletenessRequest) -> Any:
        case = _case_of(request)
        return scripted_report(case, findings(case)).model_dump(mode="json")

    return answer


def sit(
    answer: Callable[[CompletenessRequest], Any],
) -> tuple[list[dict[str, Any]], ScriptedVerifierProvider]:
    provider = ScriptedVerifierProvider(answer)
    contestant = _contestant()
    attempts: list[dict[str, Any]] = []
    for case in CASES:
        for attempt in range(1, RUNS_PER_CASE + 1):
            observation = run_structured_attempt(contestant, case, attempt, provider=provider)
            failures = score_structured_attempt(observation, case, candidate=SCRIPTED)
            attempts.append(
                attempt_evidence(
                    observation, verdict="FAIL" if failures else "PASS", failures=failures
                )
            )
    return attempts, provider


def _bad(findings: Findings) -> set[str]:
    attempts, _ = sit(answering(findings))
    assert structured_verdict(attempts) == "NOT CERTIFIED"
    return {a["case"] for a in attempts if a["verdict"] != "PASS"}


NON_COMPLETE = {
    c.case_id for c in CASES if any(e.verdict != "COMPLETE" for e in c.expected.values())
}


def _remap(
    case: StructuredCase, change: Callable[[SemanticFinding], SemanticFinding]
) -> dict[str, tuple[SemanticFinding, ...]]:
    return {pid: tuple(change(f) for f in fs) for pid, fs in perfect_findings(case).items()}


# --- budget and repetition ------------------------------------------------------------------------


def test_the_call_budget_is_case_count_times_three() -> None:
    assert RUNS_PER_CASE == 3 and len(CASES) == 28
    assert CALL_BUDGET == len(CASES) * RUNS_PER_CASE == 84


def test_a_perfect_structured_verifier_is_certified_in_exactly_the_budget() -> None:
    attempts, provider = sit(answering(perfect_findings))
    assert len(provider.requests) == CALL_BUDGET
    assert [a["failures"] for a in attempts if a["verdict"] != "PASS"] == []
    assert structured_verdict(attempts) == "PASS"


def test_fewer_attempts_or_one_failed_repetition_is_never_a_pass() -> None:
    attempts, _ = sit(answering(perfect_findings))
    assert structured_verdict([a for a in attempts if a["attempt"] == 1]) == "NOT CERTIFIED"
    assert structured_verdict(attempts[:-1]) == "NOT CERTIFIED"
    flipped = [dict(a) for a in attempts]
    flipped[40]["verdict"] = "FAIL"
    assert structured_verdict(flipped) == "NOT CERTIFIED"


# --- scripted bad verifiers ---------------------------------------------------------------------


def test_always_complete_is_not_certified() -> None:
    assert _bad(lambda c: {}) == NON_COMPLETE


def test_right_verdict_wrong_evidence_is_not_certified() -> None:
    """Each proposition quote is replaced by one real word of the statement that lies outside
    every sealed anchor: grounded, right kind, right direction, wrong region."""

    def elsewhere(case: StructuredCase) -> dict[str, tuple[SemanticFinding, ...]]:
        def shift(f: SemanticFinding) -> SemanticFinding:
            if f.proposition_evidence is None:
                return f
            for review in case.request.propositions:
                anchors = [
                    a for r in case.expected[review.proposition_id].regions for a in r.anchors
                ]
                if f.proposition_evidence not in anchors:
                    continue
                inside = {w for a in anchors for w in normalise(a).split()}
                word = next(w for w in normalise(review.statement).split() if w not in inside)
                return f.model_copy(update={"proposition_evidence": word})
            return f

        return _remap(case, shift)

    with_proposition_side = {
        c.case_id for c in CASES for e in c.expected.values() for r in e.regions if r.anchors
    }
    assert _bad(elsewhere) == with_proposition_side


def test_right_evidence_wrong_kind_is_not_certified() -> None:
    def wrong_kind(case: StructuredCase) -> dict[str, tuple[SemanticFinding, ...]]:
        return _remap(case, lambda f: f.model_copy(update={"kind": "REPETITION"}))

    assert _bad(wrong_kind) == NON_COMPLETE


def test_right_evidence_wrong_direction_is_not_certified() -> None:
    def flip(f: SemanticFinding) -> SemanticFinding:
        if f.direction == "MISSING":
            return SemanticFinding(
                kind=f.kind,
                direction="CONTRADICTORY",
                proposition_evidence=f.proposition_evidence,
                claim_ref="JDG-1",
                claim_evidence="x",
            )
        return f

    failed = _bad(lambda case: _remap(case, flip))
    incomplete = {
        c.case_id for c in CASES if any(e.verdict == "INCOMPLETE" for e in c.expected.values())
    }
    assert failed >= incomplete


def test_a_fabricated_quote_is_not_certified() -> None:
    def fabricate(f: SemanticFinding) -> SemanticFinding:
        if f.proposition_evidence is not None:
            return f.model_copy(
                update={"proposition_evidence": f"{f.proposition_evidence} on Sundays"}
            )
        return f.model_copy(update={"claim_evidence": f"{f.claim_evidence} on Sundays"})

    assert _bad(lambda case: _remap(case, fabricate)) == NON_COMPLETE


def test_a_wrong_claim_ref_is_not_certified() -> None:
    def other_ref(f: SemanticFinding) -> SemanticFinding:
        return f if f.claim_ref is None else f.model_copy(update={"claim_ref": "JDG-404"})

    with_claim = {
        c.case_id for c in CASES for e in c.expected.values() for r in e.regions if r.claim_ref
    }
    assert _bad(lambda case: _remap(case, other_ref)) == with_claim


def test_a_v1_format_answer_is_not_certified() -> None:
    def v1(request: CompletenessRequest) -> Any:
        verdicts = [
            {"proposition_id": p.proposition_id, "verdict": "COMPLETE",
             "claim_refs": [c.ref for c in p.claims]}
            for p in request.propositions
        ]  # fmt: skip
        return {"verdicts": verdicts}

    attempts, _ = sit(v1)
    assert structured_verdict(attempts) == "NOT CERTIFIED"
    assert all(a["verdict"] == "FAIL" and a["parsed_report"] is None for a in attempts)


# --- explanation independence ---------------------------------------------------------------------

EXPLANATIONS = (
    "",
    "The claims omit this assertion.",
    "The permission to renew a loan is granted to a member.",
    "A member is the actor permitted to renew the loan.",
    "The renewal permission applies to a member.",
    "Irrelevant prose about the weather and the price of tea.",
)


@pytest.mark.parametrize("explanation", EXPLANATIONS)
def test_the_certification_result_never_depends_on_the_explanation(explanation: str) -> None:
    attempts, _ = sit(
        answering(
            lambda case: _remap(case, lambda f: f.model_copy(update={"explanation": explanation}))
        )
    )
    assert structured_verdict(attempts) == "PASS"
    assert all(a["failures"] == [] for a in attempts)


# --- routing: a v2 sitting needs the v2 contract ------------------------------------------------


def test_a_contestant_sitting_only_the_v1_contract_cannot_even_be_asked() -> None:
    v1_only = _contestant(
        (
            CertifiedContract(
                task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION, contract=COMPLETENESS_V1_CONTRACT
            ),
        )
    )
    provider = ScriptedVerifierProvider(answering(perfect_findings))
    with pytest.raises(ModelUnavailableError):
        run_structured_attempt(v1_only, case_by_id("S01"), 1, provider=provider)
    assert provider.requests == []


# --- what the model saw ---------------------------------------------------------------------------

_HIDDEN = (
    "complete", "incomplete", "overreach", "contradictory", "missing", "unsupported", "sealed",
    "anchor", "expected", "regression", "k credit", "category", "exam", "kinds", "region",
)  # fmt: skip


def test_no_request_leaks_the_answer_key_or_the_case_labels() -> None:
    _, provider = sit(answering(perfect_findings))
    labels = {normalise(c.category) for c in CASES} | {c.case_id.lower() for c in CASES}
    for sent in provider.requests:
        system, user = sent.messages
        assert system.content == STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION
        assert sent.contract == COMPLETENESS_V2_CONTRACT
        text = f" {normalise(user.content)} "
        for word in (*_HIDDEN, *labels):
            assert f" {word} " not in text, (word, user.content[:100])


def test_every_attempt_sends_exactly_the_sealed_request() -> None:
    attempts, provider = sit(answering(perfect_findings))
    rendered = [render_request(c.request) for c in CASES for _ in range(RUNS_PER_CASE)]
    assert [r.messages[1].content for r in provider.requests] == rendered
    assert [a["request_json"] for a in attempts] == rendered
    ids = [r.trace.run_id for r in provider.requests]
    assert len(set(ids)) == len(ids)


def test_an_answer_from_another_model_fails_the_global_gates() -> None:
    case = case_by_id("S01")
    observation = run_structured_attempt(
        _contestant(), case, 1, provider=ScriptedVerifierProvider(answering(perfect_findings))
    )
    assert score_structured_attempt(observation, case, candidate=SCRIPTED) == ()
    other = ModelIdentity(provider="scripted", model="other")
    assert score_structured_attempt(observation, case, candidate=other) != ()


# --- the historical diagnostic, through the exam's own scorer ------------------------------------


@pytest.mark.parametrize(
    ("case_id", "translation_case"), [("S26", "C21"), ("S27", "C05"), ("S28", "C17")]
)
def test_the_hand_mapped_historical_answers_score_on_structure_alone(
    case_id: str, translation_case: str
) -> None:
    case = case_by_id(case_id)
    for t in (t for t in TRANSLATIONS if t.case == translation_case):
        assert score_structured_report(case, scripted_report(case, t.structured)) == (), (
            t.exam,
            t.attempt,
        )


def test_the_live_module_sits_only_the_structured_contract_through_the_certified_wire() -> None:
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider
    from foundry.domain.semantic_completeness import StructuredCompletenessReport
    from tests.certification import test_gpt_6_astra_structured_completeness_live as live
    from tests.certification._schema_identity import schema_sha256
    from tests.certification._structured_completeness_exam import STRUCTURED_EVIDENCE_NAMESPACE

    contestant = live.ASTRA_STRUCTURED
    assert contestant.identity == ModelIdentity(provider="openai", model="gpt-6-astra")
    assert contestant.evidence_namespace == STRUCTURED_EVIDENCE_NAMESPACE
    (certified,) = contestant.contracts
    assert certified.contract == COMPLETENESS_V2_CONTRACT
    assert certified.wire_schema_compiler == OpenAIModelProvider.WIRE_SCHEMA_COMPILER
    assert certified.wire_schema_sha256 == schema_sha256(
        OpenAIModelProvider.wire_schema(StructuredCompletenessReport)
    )


def test_a_request_bound_to_any_other_contract_fails_the_global_gates() -> None:
    case = case_by_id("S01")
    observation = run_structured_attempt(
        _contestant(), case, 1, provider=ScriptedVerifierProvider(answering(perfect_findings))
    )
    (sent,) = observation.sent
    v1_bound = type(observation)(
        case_id=observation.case_id,
        attempt=observation.attempt,
        sent=(sent.model_copy(update={"contract": COMPLETENESS_V1_CONTRACT}),),
        result=observation.result,
        report=observation.report,
        verifier=observation.verifier,
    )
    assert any(
        "contract" in f for f in score_structured_attempt(v1_bound, case, candidate=SCRIPTED)
    )
