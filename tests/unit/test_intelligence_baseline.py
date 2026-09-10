from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.domain.gaps import GapKind
from foundry.intelligence.baseline import (
    BaselineGap,
    BaselineIntelligence,
    BaselinePayload,
    BaselineResult,
)
from foundry.intelligence.baseline_validation import (
    BaselineValidationError,
    validate_baseline_result,
)
from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.proposals import IntelligenceUsage


def _request(*event_ids: str) -> IntelligenceInput:
    return IntelligenceInput(
        fixture_id="t",
        project_id="PROJ-1",
        source_event_ids=event_ids,
        inputs=(),
    )


def _gap(
    gap_id: str = "B-1",
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    subject_key: str = "response-time",
    description: str = "A potential gap.",
    source_event_ids: tuple[str, ...] = (),
    confidence: float = 0.9,
) -> BaselineGap:
    return BaselineGap(
        gap_id=gap_id,
        kind=kind,
        subject_key=subject_key,
        description=description,
        source_event_ids=source_event_ids,
        confidence=confidence,
    )


def _result(gaps: tuple[BaselineGap, ...] = ()) -> BaselineResult:
    return BaselineResult(payload=BaselinePayload(gaps=gaps), usage=IntelligenceUsage())


def test_baseline_gap_constructs() -> None:
    gap = _gap()
    assert gap.gap_id == "B-1"
    assert gap.kind is GapKind.AMBIGUITY
    assert gap.subject_key == "response-time"
    assert gap.description == "A potential gap."
    assert gap.source_event_ids == ()
    assert gap.confidence == 0.9


def test_baseline_models_are_immutable() -> None:
    gap = _gap()
    payload = BaselinePayload(gaps=(gap,))
    result = _result((gap,))
    with pytest.raises(ValidationError):
        gap.confidence = 0.1
    with pytest.raises(ValidationError):
        payload.gaps = ()
    with pytest.raises(ValidationError):
        result.usage = IntelligenceUsage(input_tokens=1)


def test_baseline_extras_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        BaselineGap.model_validate(
            {
                "gap_id": "B-1",
                "kind": "AMBIGUITY",
                "subject_key": "response-time",
                "description": "A potential gap.",
                "confidence": 0.9,
                "authority": "CANONICAL",
            }
        )
    with pytest.raises(ValidationError):
        BaselineGap.model_validate(
            {
                "gap_id": "B-1",
                "kind": "AMBIGUITY",
                "subject_key": "response-time",
                "description": "A potential gap.",
                "confidence": 0.9,
                "project_id": "PROJ-1",
            }
        )
    with pytest.raises(ValidationError):
        BaselineGap.model_validate(
            {
                "gap_id": "B-1",
                "kind": "AMBIGUITY",
                "subject_key": "response-time",
                "description": "A potential gap.",
                "confidence": 0.9,
                "fingerprint": "AMBIGUITY:response-time",
            }
        )


def test_baseline_confidence_bounds_are_enforced() -> None:
    _gap(confidence=0.0)
    _gap(confidence=1.0)
    with pytest.raises(ValidationError):
        _gap(confidence=-0.1)
    with pytest.raises(ValidationError):
        _gap(confidence=1.1)


def test_baseline_payload_contains_gaps_only() -> None:
    assert set(BaselinePayload.model_fields) == {"gaps"}
    with pytest.raises(ValidationError):
        BaselinePayload.model_validate({"gaps": [], "usage": {}})
    with pytest.raises(ValidationError):
        BaselinePayload.model_validate({"gaps": [], "semantic_proposals": []})


def test_baseline_result_separates_payload_from_usage() -> None:
    usage = IntelligenceUsage(input_tokens=11, output_tokens=7, cost_usd=0.01)
    result = BaselineResult(payload=BaselinePayload(), usage=usage)
    assert result.payload.gaps == ()
    assert result.usage is usage
    assert "usage" not in BaselinePayload.model_fields
    assert set(BaselineResult.model_fields) == {"payload", "usage"}


def test_baseline_intelligence_is_structural() -> None:
    class Fake:
        def analyze(self, request: IntelligenceInput) -> BaselineResult:
            return BaselineResult(payload=BaselinePayload(), usage=IntelligenceUsage())

    worker: BaselineIntelligence = Fake()
    result = worker.analyze(_request("EVT-1"))
    assert result.payload.gaps == ()


def test_baseline_has_no_semantic_proposal_or_fingerprint_fields() -> None:
    fields = set(BaselineGap.model_fields)
    for forbidden in (
        "fingerprint",
        "blocking",
        "affected_proposal_ids",
        "authority",
        "lifecycle",
        "project_id",
        "revision",
        "provenance",
        "usage",
        "cost",
        "tokens",
        "semantic_proposals",
        "proposal_id",
    ):
        assert forbidden not in fields


def test_duplicate_gap_id_is_rejected() -> None:
    result = _result((_gap("B-1", subject_key="latency"), _gap("B-1", subject_key="scope")))
    with pytest.raises(BaselineValidationError, match="duplicate baseline gap_id: B-1"):
        validate_baseline_result(_request(), result)


def test_duplicate_kind_subject_key_is_rejected() -> None:
    result = _result((_gap("B-1"), _gap("B-2")))
    with pytest.raises(
        BaselineValidationError,
        match="duplicate baseline gap identity: AMBIGUITY:response-time",
    ):
        validate_baseline_result(_request(), result)


def test_same_subject_key_with_different_kind_is_allowed() -> None:
    result = _result(
        (
            _gap("B-1", kind=GapKind.AMBIGUITY, subject_key="latency"),
            _gap("B-2", kind=GapKind.MISSING_SUCCESS_METRIC, subject_key="latency"),
        )
    )
    assert validate_baseline_result(_request(), result) is result


@pytest.mark.parametrize(
    "subject_key",
    ["latency", "deployment-region", "retry-count", "retry-count-3"],
)
def test_valid_subject_keys_are_accepted(subject_key: str) -> None:
    result = _result((_gap(subject_key=subject_key),))
    assert validate_baseline_result(_request(), result) is result


@pytest.mark.parametrize(
    "subject_key",
    [
        "Latency",
        "deployment_region",
        "deployment region",
        "-latency",
        "latency-",
        "latency--target",
    ],
)
def test_invalid_subject_keys_are_rejected(subject_key: str) -> None:
    result = _result((_gap(subject_key=subject_key),))
    with pytest.raises(BaselineValidationError, match="invalid subject_key: " + subject_key):
        validate_baseline_result(_request(), result)


def test_unknown_source_event_is_rejected() -> None:
    result = _result((_gap(source_event_ids=("EVT-999",)),))
    with pytest.raises(
        BaselineValidationError,
        match="unknown source_event_id on baseline gap B-1: EVT-999",
    ):
        validate_baseline_result(_request("EVT-1"), result)


def test_known_source_event_is_accepted() -> None:
    result = _result((_gap(source_event_ids=("EVT-1", "EVT-2")),))
    assert validate_baseline_result(_request("EVT-1", "EVT-2"), result) is result


def test_empty_source_event_ids_are_legal() -> None:
    result = _result((_gap(source_event_ids=()),))
    assert validate_baseline_result(_request("EVT-1"), result) is result


def test_confidence_bypass_below_zero_is_rejected() -> None:
    gap = BaselineGap.model_construct(
        gap_id="B-1",
        kind=GapKind.AMBIGUITY,
        subject_key="response-time",
        description="A potential gap.",
        source_event_ids=(),
        confidence=-0.1,
    )
    result = BaselineResult.model_construct(
        payload=BaselinePayload.model_construct(gaps=(gap,)),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(
        BaselineValidationError,
        match="invalid confidence on baseline gap B-1: -0.1",
    ):
        validate_baseline_result(_request(), result)


def test_confidence_bypass_above_one_is_rejected() -> None:
    gap = BaselineGap.model_construct(
        gap_id="B-1",
        kind=GapKind.AMBIGUITY,
        subject_key="response-time",
        description="A potential gap.",
        source_event_ids=(),
        confidence=1.1,
    )
    result = BaselineResult.model_construct(
        payload=BaselinePayload.model_construct(gaps=(gap,)),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(
        BaselineValidationError,
        match="invalid confidence on baseline gap B-1: 1.1",
    ):
        validate_baseline_result(_request(), result)


def test_disallowed_kind_bypass_is_rejected() -> None:
    gap = BaselineGap.model_construct(
        gap_id="B-1",
        kind="NOT_A_GAP_KIND",
        subject_key="response-time",
        description="A potential gap.",
        source_event_ids=(),
        confidence=0.9,
    )
    result = BaselineResult.model_construct(
        payload=BaselinePayload.model_construct(gaps=(gap,)),
        usage=IntelligenceUsage(),
    )
    with pytest.raises(
        BaselineValidationError,
        match="disallowed gap kind on baseline gap B-1: NOT_A_GAP_KIND",
    ):
        validate_baseline_result(_request(), result)


def test_valid_validation_returns_same_object() -> None:
    result = _result((_gap(source_event_ids=("EVT-1",)),))
    assert validate_baseline_result(_request("EVT-1"), result) is result


def test_validator_does_not_mutate_or_repair() -> None:
    gap = _gap(subject_key="Latency")
    result = _result((gap,))
    snapshot = result.model_dump()
    with pytest.raises(BaselineValidationError, match="invalid subject_key: Latency"):
        validate_baseline_result(_request(), result)
    assert result.model_dump() == snapshot
    assert gap.subject_key == "Latency"


def test_empty_payload_validates() -> None:
    result = _result()
    assert validate_baseline_result(_request(), result) is result


def test_baseline_modules_have_no_forbidden_imports() -> None:
    import foundry.intelligence.baseline as baseline
    import foundry.intelligence.baseline_validation as validation

    for module in (baseline, validation):
        source = Path(module.__file__).read_text()
        for token in (
            "xai_sdk",
            "XAIIntentIntelligence",
            "XAI_API_KEY",
            "grok-4.6",
            "load_judge",
            "score_prediction",
            "EvalExpectation",
            "PostgresEventStore",
            "EventEnvelope",
            "IntentState",
            "SemanticObject",
            "reducer",
            "build_intent_package",
            "evaluate_closure",
            "evals/holdout",
            "C-001",
            "C-002",
        ):
            assert token not in source
        assert "never-loses-money" not in source
        assert "legacy-retry-count" not in source
