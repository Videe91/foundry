from pathlib import Path

import pytest

from foundry.evaluation.loader import load_input
from foundry.intelligence.compiler import compile_intelligence_input
from foundry.intelligence.errors import IntelligenceValidationError
from foundry.intelligence.fake import FakeIntentIntelligence
from foundry.intelligence.port import IntentIntelligence
from foundry.intelligence.proposals import (
    ClaimProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentProposal,
)
from foundry.intelligence.validation import validate_intelligence_result

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures"


def test_fake_satisfies_intent_intelligence_port() -> None:
    payload = IntentIntelligencePayload()
    executor: IntentIntelligence = FakeIntentIntelligence(payload)
    result = executor.analyze(
        compile_intelligence_input(load_input(FIXTURES / "greenfield" / "payments_vague"))
    )
    assert result.payload is payload


def test_fake_returns_caller_supplied_payload_and_usage() -> None:
    payload = IntentIntelligencePayload(
        semantic_proposals=(
            IntentProposal(proposal_id="P-1", confidence=0.8, mission="Build a payment platform."),
        )
    )
    usage = IntelligenceUsage(deterministic_jobs=1, wall_clock_ms=4)
    fake = FakeIntentIntelligence(payload, usage)
    request = compile_intelligence_input(load_input(FIXTURES / "greenfield" / "payments_vague"))
    snapshot = request.model_dump()
    result = fake.analyze(request)
    assert result.payload is payload
    assert result.usage == usage
    assert payload.semantic_proposals[0].mission == "Build a payment platform."
    assert request.model_dump() == snapshot


def test_omitted_usage_is_zero_runtime_usage() -> None:
    payload = IntentIntelligencePayload()
    result = FakeIntentIntelligence(payload).analyze(
        compile_intelligence_input(load_input(FIXTURES / "greenfield" / "payments_vague"))
    )
    assert result.usage == IntelligenceUsage()
    assert "usage" not in IntentIntelligencePayload.model_fields


def test_greenfield_compile_fake_validate_does_not_load_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("load_judge must not be called")

    monkeypatch.setattr("foundry.evaluation.loader.load_judge", _fail_if_called)
    eval_input = load_input(FIXTURES / "greenfield" / "payments_vague")
    request = compile_intelligence_input(eval_input)
    payload = IntentIntelligencePayload(
        semantic_proposals=(
            IntentProposal(
                proposal_id="P-1",
                confidence=0.8,
                source_event_ids=("EVT-GF-1",),
                mission="Build a payment platform.",
            ),
        ),
        gap_proposals=(),
    )
    executor: IntentIntelligence = FakeIntentIntelligence(payload)
    result = executor.analyze(request)
    validated = validate_intelligence_result(request, result)
    assert validated is result
    assert result.payload is payload


def test_brownfield_compile_fake_validate_preserves_both_claims() -> None:
    request = compile_intelligence_input(load_input(FIXTURES / "brownfield" / "retry_conflict"))
    payload = IntentIntelligencePayload(
        semantic_proposals=(
            ClaimProposal(
                proposal_id="P-CLAIM-1",
                confidence=0.9,
                source_event_ids=("EVT-BF-1",),
                statement="Legacy retry count is 3.",
            ),
            ClaimProposal(
                proposal_id="P-CLAIM-2",
                confidence=0.9,
                source_event_ids=("EVT-BF-2",),
                statement="Legacy retry count is 5.",
            ),
        ),
        gap_proposals=(),
    )
    result = FakeIntentIntelligence(payload).analyze(request)
    validated = validate_intelligence_result(request, result)
    assert validated.payload.gap_proposals == ()
    statements = [proposal.statement for proposal in validated.payload.semantic_proposals]
    assert statements == ["Legacy retry count is 3.", "Legacy retry count is 5."]


def test_fake_does_not_validate_internally() -> None:
    request = compile_intelligence_input(load_input(FIXTURES / "greenfield" / "payments_vague"))
    payload = IntentIntelligencePayload(
        semantic_proposals=(
            IntentProposal(
                proposal_id="P-1",
                confidence=0.8,
                source_event_ids=("EVT-NOT-THERE",),
                mission="Build a payment platform.",
            ),
        )
    )
    result = FakeIntentIntelligence(payload).analyze(request)
    assert result.payload is payload
    with pytest.raises(IntelligenceValidationError, match="EVT-NOT-THERE"):
        validate_intelligence_result(request, result)


def test_fake_and_port_have_no_forbidden_imports() -> None:
    import foundry.intelligence.fake as fake
    import foundry.intelligence.port as port

    fake_source = Path(fake.__file__).read_text()
    port_source = Path(port.__file__).read_text()
    forbidden = (
        "openai",
        "anthropic",
        "grok",
        "gemini",
        "load_judge",
        "score_prediction",
        "PostgresEventStore",
        "validate_intelligence_result",
        "EvalPrediction",
        "EvalExpectation",
        "compile_intelligence_input",
        "load_input",
    )
    for token in forbidden:
        assert token not in fake_source
        assert token not in port_source
    for answer in (
        "AMBIGUITY:never-loses-money",
        "AMBIGUITY:very-fast",
        "MISSING_INFORMATION:jurisdiction",
        "MISSING_INFORMATION:currency-scope",
        "MISSING_SUCCESS_METRIC:latency",
        "MISSING_VERIFICATION_OBLIGATION:money-conservation",
        "CONTRADICTION:legacy-retry-count",
        "MISSING_AUTHORITY:legacy-retry-count",
        'subject_key="jurisdiction"',
        'subject_key="currency-scope"',
        "never loses money",
        "legacy-retry-count",
    ):
        assert answer not in fake_source
