"""9P2 T1: provider-neutral comparison-context contract on ``ReasoningRequest``.

Spec §8 / §16, plan §3. ``ComparisonContext`` is request-only structural history:
deterministic facts about *why* prior material is being shown. It is never evidence,
never a judgment, never persisted, and it carries no semantic classification. The
tests below lock the shape, the frozen/extra-forbid behavior, the blank-id refusals,
the deterministic provider-neutral serialization, and the absence of any field that
would let Foundry (rather than the model) decide meaning.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

import pytest
from pydantic import ValidationError

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.ports.semantic_reasoner import (
    ComparisonContext,
    ContextInclusionEdge,
    ContextRelation,
    EvidenceTransitionContext,
    ReasoningRequest,
    SemanticReasoner,
)

PROJECT = "proj-9p2"
T0 = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)

EV_T1 = evidence_item(
    evidence_id="EV-T1-02",
    project_id=PROJECT,
    source_kind=SourceKind.DOCUMENT,
    source_ref="repo://EV-T1-02",
    content="Audit records are retained for seven years.",
    observed_at=T0,
)
EV_T2 = evidence_item(
    evidence_id="EV-T2-01",
    project_id=PROJECT,
    source_kind=SourceKind.DOCUMENT,
    source_ref="repo://EV-T2-01",
    content="Audit records are retained for ten years.",
    observed_at=T0,
    artifact_ref="docs/retention.md",
    supersedes_evidence_id="EV-T1-02",
)

FORBIDDEN_FIELD_NAMES = frozenset(
    {"classification", "correction", "supports", "confidence", "authority", "verdict"}
)


def _edge(
    source_id: str = "EV-T2-01",
    relation: ContextRelation = ContextRelation.SUPERSEDES,
    target_id: str = "EV-T1-02",
) -> ContextInclusionEdge:
    return ContextInclusionEdge(source_id=source_id, relation=relation, target_id=target_id)


def _transition(**overrides: object) -> EvidenceTransitionContext:
    kwargs: dict[str, object] = {
        "current_evidence_id": "EV-T2-01",
        "predecessor_evidence_id": "EV-T1-02",
        "artifact_ref": "docs/retention.md",
        "historical_diff": "--- EV-T1-02\n+++ EV-T2-01\n@@ -1 +1 @@\n-seven\n+ten\n",
        "touched_claim_ids": ("CLAIM-03937dfe0815d553",),
        "touched_address_ids": ("ADDR-ea676cc2a41f99e1",),
        "inclusion_edges": (
            _edge(),
            _edge("EV-T1-02", ContextRelation.EFFECTIVE_EVIDENCE_OF, "CLAIM-03937dfe0815d553"),
            _edge(
                "CLAIM-03937dfe0815d553", ContextRelation.CLAIM_AT_ADDRESS, "ADDR-ea676cc2a41f99e1"
            ),
        ),
    }
    kwargs.update(overrides)
    return EvidenceTransitionContext(**kwargs)  # type: ignore[arg-type]


def _context() -> ComparisonContext:
    return ComparisonContext(
        transitions=(_transition(),),
        active_claim_profile_edges=(
            _edge(
                "ADDR-ea676cc2a41f99e1",
                ContextRelation.ACTIVE_CLAIM_PROFILE,
                "CLAIM-03937dfe0815d553",
            ),
        ),
    )


# --------------------------------------------------------------------------- relation enum


def test_context_relation_is_a_str_enum_with_exactly_the_four_structural_relations() -> None:
    assert issubclass(ContextRelation, StrEnum)
    assert {member.value for member in ContextRelation} == {
        "SUPERSEDES",
        "EFFECTIVE_EVIDENCE_OF",
        "CLAIM_AT_ADDRESS",
        "ACTIVE_CLAIM_PROFILE",
    }
    assert ContextRelation.SUPERSEDES == "SUPERSEDES"
    assert ContextRelation.EFFECTIVE_EVIDENCE_OF == "EFFECTIVE_EVIDENCE_OF"
    assert ContextRelation.CLAIM_AT_ADDRESS == "CLAIM_AT_ADDRESS"
    assert ContextRelation.ACTIVE_CLAIM_PROFILE == "ACTIVE_CLAIM_PROFILE"


# --------------------------------------------------------------------------- existing callers


def test_default_request_gets_an_empty_comparison_context_so_existing_callers_are_unchanged() -> (
    None
):
    request = ReasoningRequest(project_id=PROJECT, evidence=(EV_T1,))

    assert request.comparison_context == ComparisonContext()
    assert request.comparison_context.transitions == ()
    assert request.comparison_context.active_claim_profile_edges == ()
    # The rest of the request is untouched by the extension.
    assert request.allowed_judgment_kinds == frozenset(JudgmentKind)
    assert request.focus_object_ids == ()
    assert request.known_addresses == ()
    assert request.known_claims == ()


def test_each_default_request_gets_its_own_context_instance_via_default_factory() -> None:
    field = ReasoningRequest.model_fields["comparison_context"]
    assert field.default_factory is ComparisonContext
    first = ReasoningRequest(project_id=PROJECT, evidence=(EV_T1,))
    second = ReasoningRequest(project_id=PROJECT, evidence=(EV_T1,))
    assert first.comparison_context == second.comparison_context


def test_request_accepts_an_explicit_comparison_context() -> None:
    context = _context()
    request = ReasoningRequest(project_id=PROJECT, evidence=(EV_T2,), comparison_context=context)
    assert request.comparison_context is context
    assert request.comparison_context.transitions[0].predecessor_evidence_id == "EV-T1-02"


def test_semantic_reasoner_protocol_surface_is_unchanged() -> None:
    assert set(SemanticReasoner.__protocol_attrs__) == {"fingerprint", "propose"}  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- frozen + extra forbid


@pytest.mark.parametrize(
    "model",
    [ContextInclusionEdge, EvidenceTransitionContext, ComparisonContext],
)
def test_models_derive_from_frozen_model(model: type[FrozenModel]) -> None:
    assert issubclass(model, FrozenModel)
    assert model.model_config.get("frozen") is True
    assert model.model_config.get("extra") == "forbid"


def test_edge_is_frozen_and_rejects_extra_fields() -> None:
    edge = _edge()
    with pytest.raises(ValidationError):
        edge.source_id = "EV-OTHER"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ContextInclusionEdge(
            source_id="a",
            relation=ContextRelation.SUPERSEDES,
            target_id="b",
            weight=1.0,  # type: ignore[call-arg]
        )


def test_transition_is_frozen_and_rejects_extra_fields() -> None:
    transition = _transition()
    with pytest.raises(ValidationError):
        transition.historical_diff = "tampered"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _transition(is_correction=True)


def test_comparison_context_is_frozen_and_rejects_extra_fields() -> None:
    context = _context()
    with pytest.raises(ValidationError):
        context.transitions = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ComparisonContext(summary="history")  # type: ignore[call-arg]


# --------------------------------------------------------------------------- blank ids / refs


@pytest.mark.parametrize("field", ["source_id", "target_id"])
def test_edge_blank_ids_fail(field: str) -> None:
    kwargs = {"source_id": "a", "relation": ContextRelation.SUPERSEDES, "target_id": "b"}
    kwargs[field] = ""
    with pytest.raises(ValidationError):
        ContextInclusionEdge(**kwargs)  # type: ignore[arg-type]


def test_edge_relation_must_be_a_known_context_relation() -> None:
    with pytest.raises(ValidationError):
        ContextInclusionEdge(source_id="a", relation="CORRECTS", target_id="b")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field", ["current_evidence_id", "predecessor_evidence_id", "artifact_ref"]
)
def test_transition_blank_ids_and_blank_artifact_ref_fail(field: str) -> None:
    with pytest.raises(ValidationError):
        _transition(**{field: ""})


def test_transition_ids_are_required_not_optional() -> None:
    for field in ("current_evidence_id", "predecessor_evidence_id", "artifact_ref"):
        assert EvidenceTransitionContext.model_fields[field].is_required()
        with pytest.raises(ValidationError):
            _transition(**{field: None})


def test_empty_historical_diff_is_legal() -> None:
    transition = _transition(historical_diff="")
    assert transition.historical_diff == ""


def test_historical_diff_is_required_even_when_empty() -> None:
    assert EvidenceTransitionContext.model_fields["historical_diff"].is_required()


def test_transition_inclusion_edges_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        _transition(inclusion_edges=())


def test_transition_inclusion_edges_is_required() -> None:
    assert EvidenceTransitionContext.model_fields["inclusion_edges"].is_required()


def test_transition_touched_ids_default_to_empty_tuples() -> None:
    transition = _transition(touched_claim_ids=(), touched_address_ids=())
    assert transition.touched_claim_ids == ()
    assert transition.touched_address_ids == ()
    assert EvidenceTransitionContext.model_fields["touched_claim_ids"].default == ()
    assert EvidenceTransitionContext.model_fields["touched_address_ids"].default == ()


def test_comparison_context_defaults_to_empty_tuples() -> None:
    context = ComparisonContext()
    assert context.transitions == ()
    assert context.active_claim_profile_edges == ()


# --------------------------------------------------------------------------- serialization


def test_serialization_is_deterministic_and_round_trips_as_plain_data() -> None:
    context = _context()

    first = context.model_dump(mode="json")
    second = context.model_dump(mode="json")
    assert first == second

    restored = ComparisonContext.model_validate(first)
    assert restored == context
    assert restored.model_dump(mode="json") == first


def test_serialized_relation_is_a_plain_string() -> None:
    dumped = _edge().model_dump(mode="json")
    assert dumped == {
        "source_id": "EV-T2-01",
        "relation": "SUPERSEDES",
        "target_id": "EV-T1-02",
    }
    assert type(dumped["relation"]) is str


def test_serialized_transition_shape_is_provider_neutral() -> None:
    dumped = _transition().model_dump(mode="json")
    assert set(dumped) == {
        "current_evidence_id",
        "predecessor_evidence_id",
        "artifact_ref",
        "historical_diff",
        "touched_claim_ids",
        "touched_address_ids",
        "inclusion_edges",
    }
    assert dumped["touched_claim_ids"] == ["CLAIM-03937dfe0815d553"]
    assert dumped["touched_address_ids"] == ["ADDR-ea676cc2a41f99e1"]
    assert dumped["inclusion_edges"][0] == {
        "source_id": "EV-T2-01",
        "relation": "SUPERSEDES",
        "target_id": "EV-T1-02",
    }


def test_full_request_with_context_round_trips_through_json_mode() -> None:
    request = ReasoningRequest(
        project_id=PROJECT,
        evidence=(EV_T2,),
        comparison_context=_context(),
    )

    first = request.model_dump(mode="json")
    second = request.model_dump(mode="json")
    assert first == second
    assert set(first["comparison_context"]) == {"transitions", "active_claim_profile_edges"}

    restored = ReasoningRequest.model_validate(first)
    assert restored == request
    assert restored.comparison_context == request.comparison_context


# --------------------------------------------------------------------------- no semantic authority


@pytest.mark.parametrize(
    "model",
    [ContextInclusionEdge, EvidenceTransitionContext, ComparisonContext, ReasoningRequest],
)
def test_contract_carries_no_semantic_classification_fields(model: type[FrozenModel]) -> None:
    names = set(model.model_fields)
    leaked = {
        name
        for name in names
        if name in FORBIDDEN_FIELD_NAMES
        or any(forbidden in name for forbidden in FORBIDDEN_FIELD_NAMES)
    }
    assert leaked == set(), f"{model.__name__} exposes semantic-authority fields: {leaked}"


def test_request_field_set_is_exactly_the_locked_shape() -> None:
    assert set(ReasoningRequest.model_fields) == {
        "project_id",
        "evidence",
        "focus_object_ids",
        "known_addresses",
        "known_claims",
        "allowed_judgment_kinds",
        "comparison_context",
        "accountable_evidence_ids",  # IE2 §7.1.3: ids of evidence to account for, not state
        "reproposal",  # production re-proposal notice (findings only), not state
    }


def test_comparison_context_field_set_is_exactly_the_locked_shape() -> None:
    assert set(ComparisonContext.model_fields) == {"transitions", "active_claim_profile_edges"}
    assert set(ContextInclusionEdge.model_fields) == {"source_id", "relation", "target_id"}
