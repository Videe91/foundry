from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    SemanticObjectPayload,
    SourceReferencePayload,
    UserStatedIntentPayload,
)
from foundry.domain.semantic import Claim
from foundry.evaluation.loader import load_input
from foundry.evaluation.models import EvalInput
from foundry.intelligence.compiler import compile_intelligence_input
from foundry.intelligence.input import IntelligenceInput, IntelligenceSource

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
OCCURRED_AT = datetime(2026, 9, 9, tzinfo=UTC)


def test_greenfield_fixture_compiles_stated_intent() -> None:
    eval_input = load_input(FIXTURES / "greenfield" / "payments_vague")
    compiled = compile_intelligence_input(eval_input)

    assert compiled.fixture_id == "greenfield-payments-vague-v1"
    assert compiled.project_id == "EVAL-GF-1"
    assert compiled.source_event_ids == ("EVT-GF-1",)
    assert len(compiled.inputs) == 1
    source = compiled.inputs[0]
    assert source.event_type is EventType.USER_STATED_INTENT
    assert source.content == ("Build a payment platform that never loses money and is very fast.")
    assert source.source_kind is SourceKind.HUMAN
    assert source.source_ref == "OWNER"


def test_brownfield_fixture_preserves_both_claims_without_choosing() -> None:
    eval_input = load_input(FIXTURES / "brownfield" / "retry_conflict")
    compiled = compile_intelligence_input(eval_input)

    assert compiled.fixture_id == "brownfield-retry-conflict-v1"
    assert compiled.project_id == "EVAL-BF-1"
    assert compiled.source_event_ids == ("EVT-BF-1", "EVT-BF-2")
    assert [source.content for source in compiled.inputs] == [
        "Legacy retry count is 3.",
        "Legacy retry count is 5.",
    ]
    assert [source.source_kind for source in compiled.inputs] == [
        SourceKind.CODE,
        SourceKind.CODE,
    ]
    assert [source.source_ref for source in compiled.inputs] == [
        "repo://legacy/client.py#L10-L12",
        "repo://legacy/worker.py#L20-L22",
    ]


def test_compiled_source_has_no_canonical_metadata_fields() -> None:
    forbidden = {
        "authority",
        "confidence",
        "lifecycle",
        "revision",
        "created_at",
        "project_id",
        "provenance",
        "semantic_object",
        "relations",
    }
    assert forbidden.isdisjoint(set(IntelligenceSource.model_fields))
    assert "judge" not in IntelligenceInput.model_fields
    assert "expectation" not in IntelligenceInput.model_fields
    assert "score" not in IntelligenceInput.model_fields


def test_brownfield_claim_authority_is_stripped() -> None:
    eval_input = load_input(FIXTURES / "brownfield" / "retry_conflict")
    original = eval_input.events[0].payload
    assert isinstance(original, SemanticObjectPayload)
    assert isinstance(original.object, Claim)
    assert original.object.authority is Authority.OBSERVED
    assert original.object.confidence == 0.9

    compiled = compile_intelligence_input(eval_input)
    source = compiled.inputs[0]
    dumped = source.model_dump()
    assert "authority" not in dumped
    assert "confidence" not in dumped
    assert source.content == original.object.statement
    assert source.source_kind is original.object.provenance.source_kind
    assert source.source_ref == original.object.provenance.source_ref


def test_unsupported_event_type_fails_visibly() -> None:
    eval_input = EvalInput(
        fixture_id="unsupported-v1",
        family="greenfield",
        project_id="PROJ-1",
        events=(
            EventEnvelope(
                event_id="EVT-DOC",
                project_id="PROJ-1",
                event_type=EventType.DOCUMENT_ADDED,
                occurred_at=OCCURRED_AT,
                payload=SourceReferencePayload(source_ref="doc://spec.md"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="Unsupported intelligence event type: DOCUMENT_ADDED"):
        compile_intelligence_input(eval_input)


def test_event_order_is_preserved() -> None:
    events = (
        EventEnvelope(
            event_id="EVT-Z",
            project_id="PROJ-1",
            event_type=EventType.USER_STATED_INTENT,
            occurred_at=OCCURRED_AT,
            payload=UserStatedIntentPayload(text="Second thought.", actor_id="OWNER"),
        ),
        EventEnvelope(
            event_id="EVT-A",
            project_id="PROJ-1",
            event_type=EventType.USER_STATED_INTENT,
            occurred_at=OCCURRED_AT,
            payload=UserStatedIntentPayload(text="First thought.", actor_id="OWNER"),
        ),
    )
    compiled = compile_intelligence_input(
        EvalInput(
            fixture_id="order-v1",
            family="greenfield",
            project_id="PROJ-1",
            events=events,
        )
    )
    assert compiled.source_event_ids == ("EVT-Z", "EVT-A")
    assert [source.content for source in compiled.inputs] == [
        "Second thought.",
        "First thought.",
    ]


def test_empty_events_compile_to_empty_tuples() -> None:
    compiled = compile_intelligence_input(
        EvalInput(
            fixture_id="empty-v1",
            family="greenfield",
            project_id="PROJ-1",
            events=(),
        )
    )
    assert compiled.source_event_ids == ()
    assert compiled.inputs == ()


def test_compiler_does_not_call_load_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("load_judge must not be called")

    monkeypatch.setattr("foundry.evaluation.loader.load_judge", _fail_if_called)
    eval_input = load_input(FIXTURES / "greenfield" / "payments_vague")
    compiled = compile_intelligence_input(eval_input)
    assert compiled.fixture_id == "greenfield-payments-vague-v1"


def test_compiler_module_does_not_import_judge_types() -> None:
    import foundry.intelligence.compiler as compiler

    assert "EvalExpectation" not in compiler.__dict__
    assert "load_judge" not in compiler.__dict__
    source = Path(compiler.__file__).read_text()
    assert "EvalExpectation" not in source
    assert "load_judge" not in source
    assert "judge.json" not in source


def test_compiled_objects_are_immutable() -> None:
    compiled = compile_intelligence_input(
        EvalInput(
            fixture_id="empty-v1",
            family="greenfield",
            project_id="PROJ-1",
            events=(),
        )
    )
    with pytest.raises(ValidationError):
        compiled.project_id = "OTHER"
    source = IntelligenceSource(
        event_id="EVT-1",
        event_type=EventType.USER_STATED_INTENT,
        content="Build payments.",
        source_kind=SourceKind.HUMAN,
        source_ref="OWNER",
    )
    with pytest.raises(ValidationError):
        source.content = "changed"
