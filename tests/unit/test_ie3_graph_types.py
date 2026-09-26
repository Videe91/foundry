"""IE3 Slice 1 — typed graph proposals, reference namespaces and the Q1 widening.

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§5, §8, §9, §10,
§19, §23, §26; R99, R100; Q1, Q3, Q6).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.domain.common import Authority, Provenance, RelationType, RiskLevel, SourceKind
from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload, parse_event
from foundry.domain.gap_resolution import GapResolutionRoute
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    IE3_GRAPH_NODE_KINDS,
    IE3_MODEL_GAP_KINDS,
    IE3_PROPOSABLE_RELATIONS,
    MAX_GRAPH_GAPS,
    MAX_GRAPH_NODES,
    MAX_GRAPH_RELATIONS,
    AssumptionNodeProposal,
    BasisClaimRef,
    ConstraintNodeProposal,
    DecisionNodeProposal,
    ExistingObjectRef,
    GraphNodeDisposition,
    GraphRelationProposal,
    IntentGraphSynthesisResult,
    LocalNodeRef,
    MissingNeed,
)
from foundry.domain.intent_synthesis import INTENT_BEARING_SEMANTIC_KINDS
from foundry.domain.semantic import (
    Actor,
    Amendment,
    Assumption,
    AuthorityRecord,
    Claim,
    Conflict,
    Constraint,
    Contract,
    Evidence,
    Goal,
    Intent,
    Metric,
    NonGoal,
    Outcome,
    Preference,
    ProjectDecision,
    Question,
    Requirement,
    Risk,
    SemanticBase,
    SemanticKind,
    Unknown,
    VerificationObligation,
)
from tests.unit._ie3_fixtures import PROJECT, SCOPE, b, e, edge, gap, local, node, result

NINE = (
    SemanticKind.INTENT,
    SemanticKind.GOAL,
    SemanticKind.OUTCOME,
    SemanticKind.REQUIREMENT,
    SemanticKind.CONSTRAINT,
    SemanticKind.NON_GOAL,
    SemanticKind.PREFERENCE,
    SemanticKind.DECISION,
    SemanticKind.ASSUMPTION,
)

# --------------------------------------------------------------------------- Q1: confidence


_AT = "2026-09-26T12:00:00Z"
_PROV = Provenance(source_kind=SourceKind.HUMAN, source_ref="human://alice")


def _fields(cls: type[SemanticBase]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": f"{cls.__name__}-1",
        "project_id": PROJECT,
        "authority": Authority.PROPOSED,
        "provenance": _PROV,
        "created_at": _AT,
    }
    extra: dict[type[SemanticBase], dict[str, Any]] = {
        Intent: {"mission": "m"},
        Goal: {"statement": "s"},
        Outcome: {"statement": "s"},
        Constraint: {"statement": "s"},
        NonGoal: {"statement": "s"},
        ProjectDecision: {"statement": "s", "rationale": "r"},
        Preference: {"statement": "s"},
        Assumption: {"statement": "s", "risk_level": RiskLevel.LOW},
        Requirement: {
            "statement": "s",
            "materiality": "LOW",
            "requires_metric": False,
            "requires_verification": False,
        },
        Actor: {"name": "n", "description": "d"},
        Claim: {"statement": "s"},
        Evidence: {"statement": "s", "retrieved_at": _AT},
        Unknown: {"question": "q", "blocking": True},
        Question: {"prompt": "p", "target_object_ids": ()},
        Conflict: {"statement": "s", "object_ids": (), "resolved": False},
        Risk: {"statement": "s", "risk_level": RiskLevel.LOW},
        Metric: {"name": "n", "definition": "d", "target": "t"},
        Contract: {"statement": "s", "observable": True},
        VerificationObligation: {"statement": "s", "target_object_ids": (), "method_class": "m"},
        AuthorityRecord: {"subject_id": "x", "authorized_by": "human://alice", "rationale": "r"},
        Amendment: {"subject_id": "x", "change_statement": "c", "rationale": "r"},
    }
    fields.update(extra[cls])
    return fields


WIDENED = (Intent, Goal, Outcome, Constraint, NonGoal, ProjectDecision, Preference, Assumption)
NON_IE3 = (
    Actor,
    Claim,
    Evidence,
    Unknown,
    Question,
    Conflict,
    Risk,
    Metric,
    Contract,
    VerificationObligation,
    AuthorityRecord,
    Amendment,
)


@pytest.mark.parametrize("cls", WIDENED, ids=lambda c: c.__name__)
def test_q1_widened_ie3_kinds_accept_absent_confidence(cls: type[SemanticBase]) -> None:
    obj = cls(**_fields(cls))
    assert obj.confidence is None
    explicit_none = cls(**_fields(cls), confidence=None)
    assert explicit_none.confidence is None


@pytest.mark.parametrize("cls", WIDENED, ids=lambda c: c.__name__)
def test_q1_none_round_trips_and_stays_distinct_from_zero(cls: type[SemanticBase]) -> None:
    absent = cls(**_fields(cls), confidence=None)
    zero = cls(**_fields(cls), confidence=0.0)
    assert cls.model_validate_json(absent.model_dump_json()).confidence is None
    assert cls.model_validate_json(zero.model_dump_json()).confidence == 0.0
    assert absent != zero


@pytest.mark.parametrize("cls", WIDENED, ids=lambda c: c.__name__)
def test_q1_widened_kinds_still_bound_numeric_confidence(cls: type[SemanticBase]) -> None:
    with pytest.raises(ValidationError):
        cls(**_fields(cls), confidence=1.5)


def test_q1_requirement_keeps_its_d12_optional_confidence() -> None:
    assert Requirement(**_fields(Requirement)).confidence is None


def test_q1_semantic_base_confidence_stays_required() -> None:
    assert SemanticBase.model_fields["confidence"].is_required()


@pytest.mark.parametrize("cls", NON_IE3, ids=lambda c: c.__name__)
def test_q1_every_non_ie3_kind_still_requires_numeric_confidence(
    cls: type[SemanticBase],
) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        cls(**_fields(cls))
    with pytest.raises(ValidationError, match="confidence"):
        cls(**_fields(cls), confidence=None)


def test_q1_historical_numeric_confidence_replays_unchanged() -> None:
    goal = Goal(**_fields(Goal), confidence=0.9)
    envelope = EventEnvelope(
        event_id="EVT-hist-1",
        project_id=PROJECT,
        event_type=EventType.SEMANTIC_OBJECT_RECORDED,
        occurred_at=_AT,
        payload=SemanticObjectPayload(object=goal),
    )
    raw = envelope.model_dump(mode="json")
    assert parse_event(raw) == envelope
    store = InMemoryEventStore()
    store.append(envelope, expected_sequence=0)
    replayed = replay(PROJECT, store.load(PROJECT)).objects[goal.id]
    assert replayed == goal
    assert replayed.confidence == 0.9


# --------------------------------------------------------------------------- kind set (R99)


def test_ie3_kind_set_is_exactly_the_nine_and_not_the_frozen_synthesis_set() -> None:
    assert frozenset(NINE) == IE3_GRAPH_NODE_KINDS
    assert IE3_GRAPH_NODE_KINDS != INTENT_BEARING_SEMANTIC_KINDS
    assert SemanticKind.CONTRACT not in IE3_GRAPH_NODE_KINDS


@pytest.mark.parametrize("kind", NINE, ids=lambda k: k.value)
def test_every_ie3_kind_has_a_typed_variant(kind: SemanticKind) -> None:
    proposal = node(kind, "n1")
    assert proposal.kind is kind
    assert result(proposal).nodes[0] == proposal


@pytest.mark.parametrize(
    "kind",
    [
        SemanticKind.ACTOR,
        SemanticKind.CONTRACT,
        SemanticKind.CLAIM,
        SemanticKind.EVIDENCE,
        SemanticKind.UNKNOWN,
        SemanticKind.QUESTION,
        SemanticKind.CONFLICT,
        SemanticKind.RISK,
        SemanticKind.METRIC,
        SemanticKind.VERIFICATION_OBLIGATION,
        SemanticKind.AUTHORITY_RECORD,
        SemanticKind.AMENDMENT,
    ],
    ids=lambda k: k.value,
)
def test_unsupported_kind_is_refused_by_the_discriminated_union(kind: SemanticKind) -> None:
    raw = {
        "kind": kind.value,
        "local_id": {"namespace": "local", "local_id": "x"},
        "statement": "s",
        "proposal_rationale": "r",
    }
    with pytest.raises(ValidationError):
        IntentGraphSynthesisResult.model_validate({"nodes": [raw]})


def test_there_is_no_generic_node_with_a_free_field_dict() -> None:
    raw = {
        "kind": "GOAL",
        "local_id": {"namespace": "local", "local_id": "x"},
        "proposal_rationale": "r",
        "fields": {"statement": "s"},
    }
    with pytest.raises(ValidationError):
        IntentGraphSynthesisResult.model_validate({"nodes": [raw]})


# ------------------------------------------------------------------ kind-specific meaning


def test_constraint_requires_a_facet() -> None:
    with pytest.raises(ValidationError, match="facet"):
        ConstraintNodeProposal(local_id=local("c"), statement="s", proposal_rationale="r")


def test_decision_requires_a_decision_rationale() -> None:
    with pytest.raises(ValidationError, match="decision_rationale"):
        DecisionNodeProposal(local_id=local("d"), statement="s", proposal_rationale="r")


def test_assumption_risk_is_optional_input_only() -> None:
    bare = AssumptionNodeProposal(local_id=local("a"), statement="s", proposal_rationale="r")
    assert bare.proposed_risk_level is None
    stated = AssumptionNodeProposal(
        local_id=local("a"),
        statement="s",
        proposal_rationale="r",
        proposed_risk_level=RiskLevel.LOW,
    )
    assert stated.proposed_risk_level is RiskLevel.LOW


@pytest.mark.parametrize("kind", NINE, ids=lambda k: k.value)
def test_text_meaning_may_not_be_empty(kind: SemanticKind) -> None:
    text_field = "mission" if kind is SemanticKind.INTENT else "statement"
    with pytest.raises(ValidationError):
        node(kind, "n1", **{text_field: ""})


@pytest.mark.parametrize("kind", NINE, ids=lambda k: k.value)
def test_confidence_is_optional_and_bounded_on_every_variant(kind: SemanticKind) -> None:
    assert node(kind, "n1").confidence is None
    assert node(kind, "n1", confidence=0.0).confidence == 0.0
    with pytest.raises(ValidationError):
        node(kind, "n1", confidence=1.01)


FORBIDDEN_RUNTIME_FIELDS = {
    "id": "REQ-1",
    "object_id": "REQ-1",
    "project_id": PROJECT,
    "authority": "CANONICAL",
    "scope": [SCOPE],
    "provenance": {"source_kind": "HUMAN", "source_ref": "human://alice"},
    "created_at": _AT,
    "lifecycle": "ACTIVE",
    "revision": 1,
    "materiality": "LOW",
    "source_event_ids": ["EVT-1"],
    "relations": [{"relation_type": "SERVES", "target_id": "GOAL-1"}],
    "event_id": "EVT-1",
    "proposal_instance_id": "SYN-1",
    "risk_level": "LOW",
}


@pytest.mark.parametrize("kind", NINE, ids=lambda k: k.value)
@pytest.mark.parametrize("field", sorted(FORBIDDEN_RUNTIME_FIELDS))
def test_runtime_owned_fields_cannot_be_smuggled_into_any_variant(
    kind: SemanticKind, field: str
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        node(kind, "n1", **{field: FORBIDDEN_RUNTIME_FIELDS[field]})


# -------------------------------------------------------------------- references (R100)


@pytest.mark.parametrize(
    "bad", ["", "Goal", "1goal", "goal 1", "local://goal-1", "goal.1", "g" * 65, "-goal"]
)
def test_invalid_local_ids_are_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        LocalNodeRef(local_id=bad)


@pytest.mark.parametrize("good", ["g", "goal-1", "req_2", "a" * 64])
def test_valid_local_ids_are_accepted(good: str) -> None:
    assert LocalNodeRef(local_id=good).local_id == good


@pytest.mark.parametrize("uri", ["local://goal", "existing://GOAL-1", "basis://CLAIM-1", "goal"])
def test_uri_strings_are_never_accepted_in_place_of_typed_refs(uri: str) -> None:
    with pytest.raises(ValidationError):
        GraphRelationProposal.model_validate(
            {
                "source": uri,
                "relation_type": "SERVES",
                "target": {"namespace": "local", "local_id": "g"},
            }
        )
    with pytest.raises(ValidationError):
        GraphRelationProposal.model_validate(
            {
                "source": {"namespace": "local", "local_id": "r"},
                "relation_type": "SERVES",
                "target": uri,
            }
        )


def test_namespaces_stay_distinct_types() -> None:
    assert local("x") != e("x")
    assert e("x") != b("x")
    parsed = GraphRelationProposal.model_validate(
        {
            "source": {"namespace": "local", "local_id": "r"},
            "relation_type": "DERIVED_FROM",
            "target": {"namespace": "basis", "claim_id": "CLAIM-1"},
        }
    )
    assert isinstance(parsed.target, BasisClaimRef)
    existing = GraphRelationProposal.model_validate(
        {
            "source": {"namespace": "local", "local_id": "r"},
            "relation_type": "SERVES",
            "target": {"namespace": "existing", "object_id": "GOAL-1"},
        }
    )
    assert isinstance(existing.target, ExistingObjectRef)


def test_relation_source_must_be_a_local_node() -> None:
    with pytest.raises(ValidationError):
        GraphRelationProposal.model_validate(
            {
                "source": {"namespace": "existing", "object_id": "GOAL-1"},
                "relation_type": "SERVES",
                "target": {"namespace": "local", "local_id": "g"},
            }
        )


# ----------------------------------------------------------------- relation types (§10)


def test_proposable_relations_are_exactly_the_four_axes() -> None:
    assert (
        frozenset(
            {
                RelationType.DERIVED_FROM,
                RelationType.SERVES,
                RelationType.EXCLUDES,
                RelationType.AFFECTS,
            }
        )
        == IE3_PROPOSABLE_RELATIONS
    )


@pytest.mark.parametrize(
    "relation_type",
    sorted(
        set(RelationType)
        - {
            RelationType.DERIVED_FROM,
            RelationType.SERVES,
            RelationType.EXCLUDES,
            RelationType.AFFECTS,
        }
    ),
    ids=lambda r: r.value,
)
def test_every_other_relation_type_fails_closed(relation_type: RelationType) -> None:
    with pytest.raises(ValidationError, match="not proposable"):
        edge("r", relation_type, "g")


# ------------------------------------------------------------ disposition / replacement


def test_disposition_is_new_or_replaces_stale_only() -> None:
    assert set(GraphNodeDisposition) == {
        GraphNodeDisposition.NEW,
        GraphNodeDisposition.REPLACES_STALE,
    }
    # EXISTING_UNCHANGED is expressed as an ExistingObjectRef, never as a node (design §8).
    with pytest.raises(ValidationError):
        node(SemanticKind.GOAL, "g", disposition="EXISTING_UNCHANGED")


def test_new_node_may_not_name_a_replacement_target() -> None:
    with pytest.raises(ValidationError, match="NEW"):
        node(SemanticKind.REQUIREMENT, "r", replaces=e("REQ-old"))


def test_replaces_stale_requires_a_replacement_target() -> None:
    with pytest.raises(ValidationError, match="REPLACES_STALE"):
        node(SemanticKind.REQUIREMENT, "r", disposition=GraphNodeDisposition.REPLACES_STALE)


def test_replacement_target_must_be_an_existing_ref() -> None:
    with pytest.raises(ValidationError):
        node(
            SemanticKind.REQUIREMENT,
            "r",
            disposition=GraphNodeDisposition.REPLACES_STALE,
            replaces=local("other"),
        )


@pytest.mark.parametrize("kind", [SemanticKind.INTENT, SemanticKind.ASSUMPTION], ids=str)
def test_intent_and_assumption_can_never_be_replaced(kind: SemanticKind) -> None:
    with pytest.raises(ValidationError, match="cannot be replaced"):
        node(kind, "n", disposition=GraphNodeDisposition.REPLACES_STALE, replaces=e("OLD-1"))


@pytest.mark.parametrize(
    "kind",
    [k for k in NINE if k not in (SemanticKind.INTENT, SemanticKind.ASSUMPTION)],
    ids=lambda k: k.value,
)
def test_other_kinds_may_declare_a_stale_replacement(kind: SemanticKind) -> None:
    proposal = node(kind, "n", disposition=GraphNodeDisposition.REPLACES_STALE, replaces=e("OLD-1"))
    assert proposal.replaces == e("OLD-1")


# -------------------------------------------------------------------- result structure


def test_empty_result_is_refused() -> None:
    with pytest.raises(ValidationError, match="empty"):
        IntentGraphSynthesisResult()


def test_gap_only_result_is_legal() -> None:
    assert result(gaps=(gap(),)).nodes == ()


def test_duplicate_node_local_ids_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate node local_id"):
        result(node(SemanticKind.GOAL, "g"), node(SemanticKind.OUTCOME, "g"))


def test_duplicate_gap_ids_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate gap id"):
        result(gaps=(gap("g1"), gap("g1")))


def test_node_and_gap_ids_may_not_collide() -> None:
    with pytest.raises(ValidationError, match="collide"):
        result(node(SemanticKind.GOAL, "x"), gaps=(gap("x"),))


def test_graph_contract_version_is_pinned() -> None:
    graph = result(node(SemanticKind.GOAL, "g"))
    assert graph.graph_contract_version == "ie3.graph-v1"
    with pytest.raises(ValidationError):
        IntentGraphSynthesisResult.model_validate(
            {**graph.model_dump(mode="json"), "graph_contract_version": "ie3.graph-v2"}
        )


# -------------------------------------------------------------------------- caps (Q6)


def test_caps_are_pinned() -> None:
    assert (MAX_GRAPH_NODES, MAX_GRAPH_RELATIONS, MAX_GRAPH_GAPS) == (32, 128, 16)


def test_exactly_at_the_node_cap_is_accepted_and_one_over_is_refused() -> None:
    nodes = [node(SemanticKind.GOAL, f"g{i}") for i in range(MAX_GRAPH_NODES)]
    assert len(result(*nodes).nodes) == MAX_GRAPH_NODES
    with pytest.raises(ValidationError, match="MAX_GRAPH_NODES"):
        result(*nodes, node(SemanticKind.GOAL, "one-more"))


def test_exactly_at_the_relation_cap_is_accepted_and_one_over_is_refused() -> None:
    relations = tuple(
        edge(f"g{i}", RelationType.SERVES, f"t{i}") for i in range(MAX_GRAPH_RELATIONS)
    )
    graph = result(node(SemanticKind.GOAL, "g0"), relations=relations)
    assert len(graph.relations) == MAX_GRAPH_RELATIONS
    with pytest.raises(ValidationError, match="MAX_GRAPH_RELATIONS"):
        result(
            node(SemanticKind.GOAL, "g0"),
            relations=(*relations, edge("x", RelationType.SERVES, "y")),
        )


def test_exactly_at_the_gap_cap_is_accepted_and_one_over_is_refused() -> None:
    gaps = tuple(gap(f"g{i}") for i in range(MAX_GRAPH_GAPS))
    assert len(result(gaps=gaps).gaps) == MAX_GRAPH_GAPS
    with pytest.raises(ValidationError, match="MAX_GRAPH_GAPS"):
        result(gaps=(*gaps, gap("one-more")))


# ------------------------------------------------------------------- gaps (Q3, §19)


def test_model_gap_kinds_are_fenced() -> None:
    assert (
        frozenset(
            {
                GapKind.AMBIGUITY,
                GapKind.MISSING_INFORMATION,
                GapKind.CONTRADICTION,
                GapKind.UNSUPPORTED_ASSUMPTION,
                GapKind.UNDERSPECIFIED_SCOPE,
            }
        )
        == IE3_MODEL_GAP_KINDS
    )


@pytest.mark.parametrize(
    "kind",
    sorted(
        set(GapKind)
        - {
            GapKind.AMBIGUITY,
            GapKind.MISSING_INFORMATION,
            GapKind.CONTRADICTION,
            GapKind.UNSUPPORTED_ASSUMPTION,
            GapKind.UNDERSPECIFIED_SCOPE,
        }
    ),
    ids=lambda k: k.value,
)
def test_every_other_gap_kind_is_refused(kind: GapKind) -> None:
    with pytest.raises(ValidationError, match="IE3 model gap"):
        gap(kind=kind)


def test_model_gaps_must_be_blocking() -> None:
    with pytest.raises(ValidationError, match="blocking"):
        gap(blocking=False)


def test_missing_need_is_exactly_the_three_untrusted_values() -> None:
    assert {m.value for m in MissingNeed} == {"PROJECT_CHOICE", "EXTERNAL_FACT", "UNDETERMINED"}


def test_missing_need_is_not_a_route() -> None:
    assert not issubclass(MissingNeed, GapResolutionRoute)
    assert {m.value for m in MissingNeed}.isdisjoint({r.value for r in GapResolutionRoute})
    for need in MissingNeed:
        with pytest.raises(ValueError):
            GapResolutionRoute(need.value)


@pytest.mark.parametrize("bad", ["ASK_HUMAN", "RESEARCH", "EXISTING_CONTRADICTION"])
def test_missing_need_refuses_route_values_and_unknowns(bad: str) -> None:
    with pytest.raises(ValidationError):
        gap(missing_need=bad)


def test_gap_anchors_are_typed_refs() -> None:
    anchored = gap(anchors=(local("a"), e("GOAL-1"), b("CLAIM-1")))
    assert len(anchored.anchors) == 3
    with pytest.raises(ValidationError):
        gap(anchors=("GOAL-1",))


def test_gap_cannot_carry_model_owned_event_or_proposal_references() -> None:
    for field in ("source_event_ids", "affected_proposal_ids", "affected_object_ids", "id"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            gap(**{field: ("X",)})
