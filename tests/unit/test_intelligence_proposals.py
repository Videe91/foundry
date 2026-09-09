import pytest
from pydantic import TypeAdapter, ValidationError

from foundry.domain.common import RiskLevel
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.semantic import SemanticBase, SemanticKind
from foundry.intelligence.kinds import IntelligenceSemanticKind
from foundry.intelligence.proposals import (
    AssumptionProposal,
    ClaimProposal,
    ConstraintProposal,
    GapProposal,
    GoalProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
    IntentProposal,
    NonGoalProposal,
    OutcomeProposal,
    PreferenceProposal,
    QuestionProposal,
    RequirementProposal,
    SemanticProposal,
    UnknownProposal,
)


def test_intelligence_semantic_kind_values_are_exactly_the_approved_set() -> None:
    assert {kind.value for kind in IntelligenceSemanticKind} == {
        "INTENT",
        "GOAL",
        "OUTCOME",
        "REQUIREMENT",
        "CONSTRAINT",
        "NON_GOAL",
        "PREFERENCE",
        "ASSUMPTION",
        "CLAIM",
        "UNKNOWN",
        "QUESTION",
    }


def test_approved_kinds_correspond_to_existing_semantic_kind() -> None:
    for kind in IntelligenceSemanticKind:
        assert kind.value in {member.value for member in SemanticKind}


def test_forbidden_semantic_kinds_are_absent() -> None:
    values = {kind.value for kind in IntelligenceSemanticKind}
    assert values.isdisjoint(
        {
            "ACTOR",
            "DECISION",
            "EVIDENCE",
            "CONFLICT",
            "RISK",
            "METRIC",
            "CONTRACT",
            "VERIFICATION_OBLIGATION",
            "AUTHORITY_RECORD",
            "AMENDMENT",
        }
    )


def test_every_allowed_semantic_proposal_kind_constructs() -> None:
    proposals = (
        IntentProposal(proposal_id="P-INTENT", confidence=1.0, mission="Build payments."),
        GoalProposal(proposal_id="P-GOAL", confidence=1.0, statement="Stay available."),
        OutcomeProposal(proposal_id="P-OUT", confidence=1.0, statement="Checkout survives."),
        RequirementProposal(proposal_id="P-REQ", confidence=1.0, statement="Do not lose money."),
        ConstraintProposal(proposal_id="P-CON", confidence=1.0, statement="No single region."),
        NonGoalProposal(proposal_id="P-NG", confidence=1.0, statement="No rewrite."),
        PreferenceProposal(proposal_id="P-PREF", confidence=1.0, statement="Prefer active-active."),
        AssumptionProposal(
            proposal_id="P-ASM",
            confidence=0.7,
            statement="Regions fail independently.",
            risk_level=RiskLevel.HIGH,
        ),
        ClaimProposal(proposal_id="P-CLAIM", confidence=0.9, statement="Retry count is 3."),
        UnknownProposal(
            proposal_id="P-UNK",
            confidence=0.8,
            question="What is the latency threshold?",
            blocking=True,
        ),
        QuestionProposal(proposal_id="P-Q", confidence=0.5, prompt="Which currency?"),
    )
    kinds = [proposal.kind for proposal in proposals]
    assert set(kinds) == set(IntelligenceSemanticKind)


def test_proposals_are_immutable() -> None:
    proposal = IntentProposal(proposal_id="P-1", confidence=1.0, mission="Build payments.")
    with pytest.raises(ValidationError):
        proposal.confidence = 0.1


def test_confidence_bounds() -> None:
    IntentProposal(proposal_id="P-0", confidence=0.0, mission="Build payments.")
    IntentProposal(proposal_id="P-1", confidence=1.0, mission="Build payments.")
    with pytest.raises(ValidationError):
        IntentProposal(proposal_id="P-LOW", confidence=-0.1, mission="Build payments.")
    with pytest.raises(ValidationError):
        IntentProposal(proposal_id="P-HIGH", confidence=1.01, mission="Build payments.")


def test_authority_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        IntentProposal.model_validate(
            {
                "proposal_id": "P-1",
                "confidence": 1.0,
                "mission": "Build payments.",
                "authority": "CANONICAL",
            }
        )


def test_project_id_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GoalProposal.model_validate(
            {
                "proposal_id": "P-1",
                "confidence": 1.0,
                "statement": "Stay available.",
                "project_id": "PROJ-1",
            }
        )


def test_gap_proposal_has_local_identity_and_subject_key() -> None:
    gap = GapProposal(
        proposal_id="G-1",
        kind=GapKind.AMBIGUITY,
        subject_key="very-fast",
        description="The term very fast has no threshold.",
        blocking=True,
        confidence=0.9,
    )
    assert gap.proposal_id == "G-1"
    assert gap.subject_key == "very-fast"
    assert "fingerprint" not in GapProposal.model_fields


def test_gap_proposal_rejects_fingerprint() -> None:
    with pytest.raises(ValidationError):
        GapProposal.model_validate(
            {
                "proposal_id": "G-1",
                "kind": GapKind.AMBIGUITY,
                "subject_key": "very-fast",
                "description": "The term very fast has no threshold.",
                "blocking": True,
                "confidence": 0.9,
                "fingerprint": "AMBIGUITY:very-fast",
            }
        )


def test_payload_holds_semantic_and_gap_tuples_without_usage() -> None:
    payload = IntentIntelligencePayload(
        semantic_proposals=(
            IntentProposal(proposal_id="P-1", confidence=1.0, mission="Build payments."),
        ),
        gap_proposals=(
            GapProposal(
                proposal_id="G-1",
                kind=GapKind.AMBIGUITY,
                subject_key="very-fast",
                description="No threshold.",
                blocking=True,
                confidence=0.8,
            ),
        ),
    )
    assert len(payload.semantic_proposals) == 1
    assert len(payload.gap_proposals) == 1
    assert "usage" not in IntentIntelligencePayload.model_fields


def test_payload_rejects_usage_field() -> None:
    with pytest.raises(ValidationError):
        IntentIntelligencePayload.model_validate(
            {
                "semantic_proposals": (),
                "gap_proposals": (),
                "usage": {"input_tokens": 12},
            }
        )


def test_usage_rejects_negative_counters_and_cost() -> None:
    with pytest.raises(ValidationError):
        IntelligenceUsage(input_tokens=-1)
    with pytest.raises(ValidationError):
        IntelligenceUsage(cost_usd=-0.01)


def test_result_wraps_payload_and_runtime_usage() -> None:
    payload = IntentIntelligencePayload()
    usage = IntelligenceUsage(deterministic_jobs=1, wall_clock_ms=3)
    result = IntentIntelligenceResult(payload=payload, usage=usage)
    assert result.payload == payload
    assert result.usage == usage


def test_discriminated_union_preserves_concrete_type() -> None:
    proposal = RequirementProposal(
        proposal_id="P-REQ",
        confidence=1.0,
        statement="Do not lose money.",
    )
    restored = TypeAdapter(SemanticProposal).validate_python(proposal.model_dump(mode="json"))
    assert isinstance(restored, RequirementProposal)
    assert restored == proposal


def test_proposal_classes_are_not_canonical_types() -> None:
    assert not issubclass(IntentProposal, SemanticBase)
    assert not issubclass(GapProposal, Gap)
    assert not issubclass(RequirementProposal, SemanticBase)
    assert not issubclass(ClaimProposal, SemanticBase)
