from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.domain.gaps import GapKind
from foundry.domain.semantic import SemanticKind
from foundry.intelligence.errors import IntelligenceValidationError
from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.kinds import IntelligenceSemanticKind
from foundry.intelligence.proposals import (
    GapProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
    IntentProposal,
    RequirementProposal,
)
from foundry.intelligence.validation import validate_intelligence_result


def _request(*event_ids: str) -> IntelligenceInput:
    return IntelligenceInput(
        fixture_id="t",
        project_id="PROJ-1",
        source_event_ids=event_ids,
        inputs=(),
    )


def _intent(proposal_id: str = "P-1", *, source_event_ids: tuple[str, ...] = ()) -> IntentProposal:
    return IntentProposal(
        proposal_id=proposal_id,
        confidence=1.0,
        mission="Build payments.",
        source_event_ids=source_event_ids,
    )


def _gap(
    proposal_id: str = "G-1",
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    subject_key: str = "very-fast",
    source_event_ids: tuple[str, ...] = (),
    affected_proposal_ids: tuple[str, ...] = (),
    confidence: float = 0.9,
) -> GapProposal:
    return GapProposal(
        proposal_id=proposal_id,
        kind=kind,
        subject_key=subject_key,
        description="A potential gap.",
        source_event_ids=source_event_ids,
        affected_proposal_ids=affected_proposal_ids,
        blocking=True,
        confidence=confidence,
    )


def _result(
    semantics: tuple[object, ...] = (),
    gaps: tuple[object, ...] = (),
) -> IntentIntelligenceResult:
    return IntentIntelligenceResult(
        payload=IntentIntelligencePayload(
            semantic_proposals=semantics,  # type: ignore[arg-type]
            gap_proposals=gaps,  # type: ignore[arg-type]
        ),
        usage=IntelligenceUsage(),
    )


def test_valid_result_returns_the_same_object() -> None:
    request = _request("EVT-1")
    result = _result((_intent(source_event_ids=("EVT-1",)),), (_gap(source_event_ids=("EVT-1",)),))
    assert validate_intelligence_result(request, result) is result


def test_empty_payload_validates() -> None:
    result = _result()
    assert validate_intelligence_result(_request(), result) is result


def test_duplicate_semantic_proposal_id_is_rejected() -> None:
    result = _result(
        (
            _intent("P-1"),
            RequirementProposal(proposal_id="P-1", confidence=1.0, statement="Stay up."),
        )
    )
    with pytest.raises(IntelligenceValidationError, match="duplicate semantic proposal_id: P-1"):
        validate_intelligence_result(_request(), result)


def test_duplicate_gap_proposal_id_is_rejected() -> None:
    result = _result(
        gaps=(_gap("G-1", subject_key="latency"), _gap("G-1", subject_key="jurisdiction"))
    )
    with pytest.raises(IntelligenceValidationError, match="duplicate gap proposal_id: G-1"):
        validate_intelligence_result(_request(), result)


def test_duplicate_kind_subject_key_is_rejected() -> None:
    result = _result(gaps=(_gap("G-1"), _gap("G-2")))
    with pytest.raises(
        IntelligenceValidationError, match="duplicate gap identity: AMBIGUITY:very-fast"
    ):
        validate_intelligence_result(_request(), result)


def test_same_subject_key_with_different_kind_is_allowed() -> None:
    result = _result(
        gaps=(
            _gap("G-1", kind=GapKind.AMBIGUITY, subject_key="latency"),
            _gap("G-2", kind=GapKind.MISSING_SUCCESS_METRIC, subject_key="latency"),
        )
    )
    assert validate_intelligence_result(_request(), result) is result


@pytest.mark.parametrize(
    "subject_key",
    [
        "jurisdiction",
        "currency-scope",
        "latency",
        "money-conservation",
        "legacy-retry-count",
        "retry-count-3",
    ],
)
def test_valid_subject_keys_are_accepted(subject_key: str) -> None:
    result = _result(gaps=(_gap(subject_key=subject_key),))
    assert validate_intelligence_result(_request(), result) is result


@pytest.mark.parametrize(
    "subject_key",
    [
        "CurrencyScope",
        "currency_scope",
        "currency scope",
        "-currency",
        "currency-",
        "currency--scope",
        "CURRENCY",
    ],
)
def test_invalid_subject_keys_are_rejected(subject_key: str) -> None:
    result = _result(gaps=(_gap(subject_key=subject_key),))
    with pytest.raises(IntelligenceValidationError, match=f"invalid subject_key: {subject_key}"):
        validate_intelligence_result(_request(), result)


def test_unknown_semantic_source_event_is_rejected() -> None:
    result = _result((_intent(source_event_ids=("EVT-999",)),))
    with pytest.raises(
        IntelligenceValidationError,
        match="unknown source_event_id on semantic proposal P-1: EVT-999",
    ):
        validate_intelligence_result(_request("EVT-1", "EVT-2"), result)


def test_unknown_gap_source_event_is_rejected() -> None:
    result = _result(gaps=(_gap(source_event_ids=("EVT-999",)),))
    with pytest.raises(
        IntelligenceValidationError,
        match="unknown source_event_id on gap proposal G-1: EVT-999",
    ):
        validate_intelligence_result(_request("EVT-1"), result)


def test_known_source_event_is_accepted() -> None:
    result = _result(
        (_intent(source_event_ids=("EVT-2",)),),
        (_gap(source_event_ids=("EVT-1", "EVT-2")),),
    )
    assert validate_intelligence_result(_request("EVT-1", "EVT-2"), result) is result


def test_unknown_affected_semantic_proposal_is_rejected() -> None:
    result = _result(gaps=(_gap(affected_proposal_ids=("P-MISSING",)),))
    with pytest.raises(
        IntelligenceValidationError,
        match="unknown affected_proposal_id on gap proposal G-1: P-MISSING",
    ):
        validate_intelligence_result(_request(), result)


def test_known_affected_semantic_proposal_is_accepted() -> None:
    result = _result((_intent("P-1"),), (_gap(affected_proposal_ids=("P-1",)),))
    assert validate_intelligence_result(_request(), result) is result


def test_gap_id_does_not_satisfy_affected_proposal_reference() -> None:
    result = _result(gaps=(_gap("G-1", affected_proposal_ids=("G-1",)),))
    with pytest.raises(
        IntelligenceValidationError,
        match="unknown affected_proposal_id on gap proposal G-1: G-1",
    ):
        validate_intelligence_result(_request(), result)


def test_semantic_confidence_below_zero_is_rejected() -> None:
    proposal = IntentProposal.model_construct(
        proposal_id="P-1",
        kind=IntelligenceSemanticKind.INTENT,
        confidence=-0.1,
        mission="Build payments.",
        source_event_ids=(),
    )
    result = IntentIntelligenceResult.model_construct(
        payload=IntentIntelligencePayload.model_construct(
            semantic_proposals=(proposal,),
            gap_proposals=(),
        ),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(
        IntelligenceValidationError,
        match="invalid confidence on semantic proposal P-1: -0.1",
    ):
        validate_intelligence_result(_request(), result)


def test_semantic_confidence_above_one_is_rejected() -> None:
    proposal = IntentProposal.model_construct(
        proposal_id="P-1",
        kind=IntelligenceSemanticKind.INTENT,
        confidence=1.1,
        mission="Build payments.",
        source_event_ids=(),
    )
    result = IntentIntelligenceResult.model_construct(
        payload=IntentIntelligencePayload.model_construct(
            semantic_proposals=(proposal,),
            gap_proposals=(),
        ),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(
        IntelligenceValidationError,
        match="invalid confidence on semantic proposal P-1: 1.1",
    ):
        validate_intelligence_result(_request(), result)


def test_gap_confidence_below_zero_is_rejected() -> None:
    gap = GapProposal.model_construct(
        proposal_id="G-1",
        kind=GapKind.AMBIGUITY,
        subject_key="very-fast",
        description="A potential gap.",
        affected_proposal_ids=(),
        source_event_ids=(),
        blocking=True,
        confidence=-0.1,
    )
    result = IntentIntelligenceResult.model_construct(
        payload=IntentIntelligencePayload.model_construct(
            semantic_proposals=(),
            gap_proposals=(gap,),
        ),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(
        IntelligenceValidationError,
        match="invalid confidence on gap proposal G-1: -0.1",
    ):
        validate_intelligence_result(_request(), result)


def test_gap_confidence_above_one_is_rejected() -> None:
    gap = GapProposal.model_construct(
        proposal_id="G-1",
        kind=GapKind.AMBIGUITY,
        subject_key="very-fast",
        description="A potential gap.",
        affected_proposal_ids=(),
        source_event_ids=(),
        blocking=True,
        confidence=1.1,
    )
    result = IntentIntelligenceResult.model_construct(
        payload=IntentIntelligencePayload.model_construct(
            semantic_proposals=(),
            gap_proposals=(gap,),
        ),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(
        IntelligenceValidationError,
        match="invalid confidence on gap proposal G-1: 1.1",
    ):
        validate_intelligence_result(_request(), result)


def test_disallowed_semantic_kind_is_rejected() -> None:
    proposal = IntentProposal.model_construct(
        proposal_id="P-1",
        kind=SemanticKind.DECISION,
        confidence=1.0,
        mission="Build payments.",
        source_event_ids=(),
    )
    result = IntentIntelligenceResult.model_construct(
        payload=IntentIntelligencePayload.model_construct(
            semantic_proposals=(proposal,),
            gap_proposals=(),
        ),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(IntelligenceValidationError):
        validate_intelligence_result(_request(), result)


def test_raw_gap_proposal_with_fingerprint_fails_pydantic() -> None:
    with pytest.raises(ValidationError):
        GapProposal.model_validate(
            {
                "proposal_id": "G-1",
                "kind": GapKind.AMBIGUITY,
                "subject_key": "very-fast",
                "description": "A potential gap.",
                "blocking": True,
                "confidence": 0.9,
                "fingerprint": "AMBIGUITY:very-fast",
            }
        )


def test_raw_payload_with_usage_fails_pydantic() -> None:
    with pytest.raises(ValidationError):
        IntentIntelligencePayload.model_validate(
            {"semantic_proposals": (), "gap_proposals": (), "usage": {"input_tokens": 3}}
        )


def test_validator_does_not_mutate_subject_key() -> None:
    gap = _gap(subject_key="very-fast")
    result = _result(gaps=(gap,))
    validate_intelligence_result(_request(), result)
    assert gap.subject_key == "very-fast"


def test_validator_does_not_create_fingerprints_or_import_judge() -> None:
    import foundry.intelligence.validation as validation

    source = Path(validation.__file__).read_text()
    assert "EvalPrediction" not in source
    assert "EvalExpectation" not in source
    assert "score_prediction" not in source
    assert "load_judge" not in source
    assert 'f"{gap.kind.value}:{gap.subject_key}"' not in source
    assert "f'{gap.kind.value}:{gap.subject_key}'" not in source
