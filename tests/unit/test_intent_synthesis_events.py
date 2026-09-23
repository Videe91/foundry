"""T3 — the Intent Synthesis event vocabulary.

Three events and no more (C12, C7):

* ``INTENT_SYNTHESIS_DECIDED`` — proposal AND decision in one durable event. There is
  no separate ``PROPOSED`` or ``ADMITTED``; collapsing them is what removed the
  decided-with-no-decision recovery state.
* ``INTENT_OBJECT_SYNTHESIZED`` — the object and its effect inputs in one event. There
  is no ``INTENT_OBJECT_RETIRED``; retirement rides inside this event so a replacement
  can never be complete while its retirement is missing.
* ``INTENT_SYNTHESIS_INVALIDATED`` — the terminal non-effect of a durable
  ``DECIDED(APPLY)``.

T3 defines **vocabulary only**. Nothing here applies an object, retires anything,
routes, or touches projected state; those are T4+.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, FrozenModel, Materiality, Provenance, RiskLevel
from foundry.domain.events import (
    EVENT_PAYLOAD_TYPES,
    GENERIC_SEMANTIC_KINDS,
    SPECIALIZED_SEMANTIC_KIND_BY_EVENT,
    EventEnvelope,
    EventType,
    IntentObjectPayload,
    IntentSynthesisDecidedPayload,
    IntentSynthesisInvalidatedPayload,
    SemanticObjectPayload,
    parse_event,
)
from foundry.domain.intent_synthesis import (
    INTENT_BEARING_SEMANTIC_KINDS,
    IntentDisposition,
    IntentSynthesisDecision,
    IntentSynthesisRoute,
    InvalidationReason,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
)
from foundry.domain.semantic import (
    Actor,
    Assumption,
    Constraint,
    Contract,
    Decision,
    Goal,
    Intent,
    NonGoal,
    Outcome,
    Preference,
    Requirement,
    SemanticBase,
    SemanticKind,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint

PROJECT = "PROJ-A"
OCCURRED_AT = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
AUTHOR = ReasonerFingerprint(provider="human", model="human://alice", policy_version="v1")
PROVENANCE = Provenance(source_kind="HUMAN", source_ref="human://alice")

THE_TEN = {
    SemanticKind.INTENT,
    SemanticKind.GOAL,
    SemanticKind.OUTCOME,
    SemanticKind.REQUIREMENT,
    SemanticKind.CONSTRAINT,
    SemanticKind.NON_GOAL,
    SemanticKind.PREFERENCE,
    SemanticKind.DECISION,
    SemanticKind.ASSUMPTION,
    SemanticKind.CONTRACT,
}


def _identity(tag: str = "p1", project_id: str = PROJECT) -> SynthesisIdentity:
    return SynthesisIdentity(project_id=project_id, synthesis_run_id="RUN-1", model_proposal_id=tag)


def _proposal(tag: str = "p1") -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=tag,
        disposition=IntentDisposition.NEW,
        statement="Revocation is immediate.",
        rationale="Stated by the owner.",
        basis_claim_ids=("CLAIM-1",),
    )


def _decided_payload(
    *,
    identity: SynthesisIdentity | None = None,
    proposal: RequirementSynthesisProposal | None = None,
    decision: IntentSynthesisDecision | None = None,
    assigned_authority: Authority | None = Authority.CANONICAL,
    origin: SynthesisOrigin = SynthesisOrigin.HUMAN_STATED,
) -> IntentSynthesisDecidedPayload:
    ident = identity or _identity()
    return IntentSynthesisDecidedPayload(
        proposal=proposal or _proposal(ident.model_proposal_id),
        author=AUTHOR,
        identity=ident,
        origin=origin,
        assigned_authority=assigned_authority,
        decision=decision
        or IntentSynthesisDecision(
            proposal_instance_id=ident.proposal_instance_id,
            route=IntentSynthesisRoute.APPLY,
            reasons=("HUMAN_AUTHORITY",),
        ),
    )


def _base_fields(kind: SemanticKind, project_id: str = PROJECT) -> dict[str, object]:
    return {
        "id": f"OBJ-{kind.value}",
        "project_id": project_id,
        "authority": Authority.CANONICAL,
        "confidence": 1.0,
        "provenance": PROVENANCE,
        "created_at": OCCURRED_AT,
    }


def _object(kind: SemanticKind, project_id: str = PROJECT) -> SemanticBase:
    """A minimal valid object of any kind, for boundary testing."""
    base = _base_fields(kind, project_id)
    builders: dict[SemanticKind, SemanticBase] = {
        SemanticKind.INTENT: Intent(**base, mission="Ship safely."),  # type: ignore[arg-type]
        SemanticKind.GOAL: Goal(**base, statement="s"),  # type: ignore[arg-type]
        SemanticKind.OUTCOME: Outcome(**base, statement="s"),  # type: ignore[arg-type]
        SemanticKind.NON_GOAL: NonGoal(**base, statement="s"),  # type: ignore[arg-type]
        SemanticKind.PREFERENCE: Preference(**base, statement="s"),  # type: ignore[arg-type]
        SemanticKind.CONSTRAINT: Constraint(**base, statement="s"),  # type: ignore[arg-type]
        SemanticKind.REQUIREMENT: Requirement(  # type: ignore[arg-type]
            **base,
            statement="s",
            materiality=Materiality.LOW,
            requires_metric=False,
            requires_verification=False,
        ),
        SemanticKind.DECISION: Decision(**base, statement="s", rationale="r"),  # type: ignore[arg-type]
        SemanticKind.ASSUMPTION: Assumption(  # type: ignore[arg-type]
            **base, statement="s", risk_level=RiskLevel.LOW
        ),
        SemanticKind.CONTRACT: Contract(**base, statement="s", observable=True),  # type: ignore[arg-type]
        SemanticKind.ACTOR: Actor(**base, name="n", description="d"),  # type: ignore[arg-type]
    }
    return builders[kind]


def _envelope(
    event_type: EventType,
    payload: FrozenModel,
    *,
    project_id: str = PROJECT,
    event_id: str = "EVT-1",
    occurred_at: datetime = OCCURRED_AT,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        project_id=project_id,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,  # type: ignore[arg-type]
    )


def _object_payload(
    *,
    kind: SemanticKind = SemanticKind.REQUIREMENT,
    project_id: str = PROJECT,
    basis_claim_ids: tuple[str, ...] = ("CLAIM-1",),
    replaces_object_id: str | None = None,
    proposal_instance_id: str = "SYN-1",
) -> IntentObjectPayload:
    return IntentObjectPayload(
        object=_object(kind, project_id),  # type: ignore[arg-type]
        basis_claim_ids=basis_claim_ids,
        replaces_object_id=replaces_object_id,
        proposal_instance_id=proposal_instance_id,
    )


# --- event vocabulary -----------------------------------------------------------------


def test_exactly_three_synthesis_event_types_exist() -> None:
    synthesis = {
        m for m in EventType if "INTENT_SYNTHESIS" in m.value or "INTENT_OBJECT" in m.value
    }
    assert synthesis == {
        EventType.INTENT_SYNTHESIS_DECIDED,
        EventType.INTENT_OBJECT_SYNTHESIZED,
        EventType.INTENT_SYNTHESIS_INVALIDATED,
    }


@pytest.mark.parametrize(
    "absent", ["INTENT_SYNTHESIS_PROPOSED", "INTENT_SYNTHESIS_ADMITTED", "INTENT_OBJECT_RETIRED"]
)
def test_the_collapsed_events_do_not_exist(absent: str) -> None:
    """C12 collapsed proposal+admission; C7 folded retirement into SYNTHESIZED."""
    assert absent not in {m.value for m in EventType}


def test_all_three_are_mapped_to_their_payload_types() -> None:
    assert EVENT_PAYLOAD_TYPES[EventType.INTENT_SYNTHESIS_DECIDED] is IntentSynthesisDecidedPayload
    assert EVENT_PAYLOAD_TYPES[EventType.INTENT_OBJECT_SYNTHESIZED] is IntentObjectPayload
    assert (
        EVENT_PAYLOAD_TYPES[EventType.INTENT_SYNTHESIS_INVALIDATED]
        is IntentSynthesisInvalidatedPayload
    )


def test_existing_event_contracts_are_untouched() -> None:
    """Protected: the old kind sets keep their exact membership and meaning."""
    assert SPECIALIZED_SEMANTIC_KIND_BY_EVENT[EventType.REQUIREMENT_CANONICALIZED] is (
        SemanticKind.REQUIREMENT
    )
    assert SemanticKind.INTENT in GENERIC_SEMANTIC_KINDS
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in SPECIALIZED_SEMANTIC_KIND_BY_EVENT
    assert EVENT_PAYLOAD_TYPES[EventType.SEMANTIC_OBJECT_RECORDED] is SemanticObjectPayload


# --- DECIDED payload ------------------------------------------------------------------


def test_a_coherent_decided_envelope_is_accepted() -> None:
    envelope = _envelope(EventType.INTENT_SYNTHESIS_DECIDED, _decided_payload())
    assert envelope.event_type is EventType.INTENT_SYNTHESIS_DECIDED


def test_the_decided_payload_carries_exactly_six_fields() -> None:
    assert set(IntentSynthesisDecidedPayload.model_fields) == {
        "proposal",
        "author",
        "identity",
        "origin",
        "assigned_authority",
        "decision",
    }


@pytest.mark.parametrize("field", ["decision_event_id", "decided_at"])
def test_envelope_derived_fields_cannot_be_supplied_in_the_payload(field: str) -> None:
    """They come from the envelope's event_id / occurred_at, never from a synthesizer."""
    payload = _decided_payload()
    with pytest.raises(ValidationError):
        IntentSynthesisDecidedPayload.model_validate(
            {**payload.model_dump(mode="json"), field: "smuggled"}
        )


def test_a_proposal_body_from_another_proposal_is_rejected_at_the_ledger_boundary() -> None:
    """T2.2 coherence, enforced before a malformed event can enter the ledger."""
    payload = _decided_payload(identity=_identity("p1"), proposal=_proposal("p2"))
    with pytest.raises(ValidationError):
        _envelope(EventType.INTENT_SYNTHESIS_DECIDED, payload)


def test_a_decision_naming_another_proposal_instance_is_rejected() -> None:
    other = _identity("other")
    payload = _decided_payload(
        decision=IntentSynthesisDecision(
            proposal_instance_id=other.proposal_instance_id,
            route=IntentSynthesisRoute.APPLY,
            reasons=("R",),
        )
    )
    with pytest.raises(ValidationError):
        _envelope(EventType.INTENT_SYNTHESIS_DECIDED, payload)


def test_an_envelope_project_that_differs_from_the_identity_project_is_rejected() -> None:
    payload = _decided_payload(identity=_identity(project_id="PROJ-OTHER"))
    with pytest.raises(ValidationError):
        _envelope(EventType.INTENT_SYNTHESIS_DECIDED, payload, project_id=PROJECT)


def test_assigned_authority_may_be_absent() -> None:
    payload = _decided_payload(
        assigned_authority=None,
        decision=IntentSynthesisDecision(
            proposal_instance_id=_identity().proposal_instance_id,
            route=IntentSynthesisRoute.REQUIRE_HUMAN,
            reasons=("AUTHORITY_UNRESOLVED",),
        ),
    )
    envelope = _envelope(EventType.INTENT_SYNTHESIS_DECIDED, payload)
    assert isinstance(envelope.payload, IntentSynthesisDecidedPayload)
    assert envelope.payload.assigned_authority is None


def test_author_origin_and_authority_survive_a_json_round_trip() -> None:
    envelope = _envelope(
        EventType.INTENT_SYNTHESIS_DECIDED,
        _decided_payload(origin=SynthesisOrigin.AI_INFERRED, assigned_authority=Authority.PROPOSED),
    )
    revived = parse_event(envelope.model_dump(mode="json"))
    assert revived == envelope
    payload = revived.payload
    assert isinstance(payload, IntentSynthesisDecidedPayload)
    assert payload.origin is SynthesisOrigin.AI_INFERRED
    assert payload.assigned_authority is Authority.PROPOSED
    assert payload.author == AUTHOR


def test_the_proposal_schema_is_not_widened_by_the_event_layer() -> None:
    """C17/C19: author, origin and authority live on the EVENT, never on the proposal."""
    forbidden = {"author", "origin", "assigned_authority", "authority"}
    assert not forbidden & set(RequirementSynthesisProposal.model_fields)


# --- SYNTHESIZED payload --------------------------------------------------------------


def test_the_object_payload_carries_exactly_four_fields() -> None:
    assert set(IntentObjectPayload.model_fields) == {
        "object",
        "basis_claim_ids",
        "replaces_object_id",
        "proposal_instance_id",
    }


def test_the_object_payload_carries_no_reducer_owned_consequences() -> None:
    """Derivation edges, retirement records and the applied marker are T4 outputs."""
    fields = set(IntentObjectPayload.model_fields)
    assert not fields & {
        "derivations",
        "derivation_edges",
        "parent_judgment_ids",
        "retirement",
        "retirements",
        "applied",
        "applied_proposal_ids",
        "route",
        "decision",
        "lifecycle",
    }


def test_basis_claim_ids_requires_at_least_one_id() -> None:
    with pytest.raises(ValidationError):
        _object_payload(basis_claim_ids=())


def test_proposal_instance_id_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        _object_payload(proposal_instance_id="")


def test_replaces_object_id_is_optional_and_accepted_when_supplied() -> None:
    assert _object_payload().replaces_object_id is None
    assert _object_payload(replaces_object_id="REQ-old").replaces_object_id == "REQ-old"


def test_the_allowed_synthesis_kind_set_is_exactly_the_approved_ten() -> None:
    assert INTENT_BEARING_SEMANTIC_KINDS == THE_TEN
    assert len(INTENT_BEARING_SEMANTIC_KINDS) == 10


@pytest.mark.parametrize("kind", sorted(THE_TEN, key=lambda k: k.value))
def test_every_intent_bearing_kind_is_accepted(kind: SemanticKind) -> None:
    envelope = _envelope(EventType.INTENT_OBJECT_SYNTHESIZED, _object_payload(kind=kind))
    assert envelope.event_type is EventType.INTENT_OBJECT_SYNTHESIZED


def test_actor_is_specifically_excluded() -> None:
    """D1: Actor is canonical intent CONTEXT, never an intent-bearing commitment."""
    assert SemanticKind.ACTOR not in INTENT_BEARING_SEMANTIC_KINDS
    with pytest.raises(ValidationError):
        _envelope(EventType.INTENT_OBJECT_SYNTHESIZED, _object_payload(kind=SemanticKind.ACTOR))


def test_no_non_intent_bearing_kind_is_permitted() -> None:
    excluded = {
        SemanticKind.ACTOR,
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
    }
    assert not excluded & INTENT_BEARING_SEMANTIC_KINDS


def test_an_envelope_project_that_differs_from_the_object_project_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _envelope(
            EventType.INTENT_OBJECT_SYNTHESIZED,
            _object_payload(project_id="PROJ-OTHER"),
            project_id=PROJECT,
        )


def test_a_synthesized_object_event_round_trips_through_json() -> None:
    envelope = _envelope(
        EventType.INTENT_OBJECT_SYNTHESIZED,
        _object_payload(basis_claim_ids=("CLAIM-1", "CLAIM-2"), replaces_object_id="REQ-old"),
    )
    revived = parse_event(envelope.model_dump(mode="json"))
    assert revived == envelope
    payload = revived.payload
    assert isinstance(payload, IntentObjectPayload)
    assert payload.basis_claim_ids == ("CLAIM-1", "CLAIM-2")
    assert payload.replaces_object_id == "REQ-old"


# --- INVALIDATED payload --------------------------------------------------------------


def test_the_invalidated_payload_carries_exactly_two_fields() -> None:
    assert set(IntentSynthesisInvalidatedPayload.model_fields) == {
        "proposal_instance_id",
        "reason",
    }


@pytest.mark.parametrize("reason", list(InvalidationReason))
def test_each_bounded_reason_is_accepted(reason: InvalidationReason) -> None:
    envelope = _envelope(
        EventType.INTENT_SYNTHESIS_INVALIDATED,
        IntentSynthesisInvalidatedPayload(proposal_instance_id="SYN-1", reason=reason),
    )
    assert envelope.event_type is EventType.INTENT_SYNTHESIS_INVALIDATED


def test_a_free_text_reason_is_rejected() -> None:
    """The ledger stays analysable: the reason vocabulary is bounded, never prose."""
    with pytest.raises(ValidationError):
        IntentSynthesisInvalidatedPayload.model_validate(
            {"proposal_instance_id": "SYN-1", "reason": "the basis moved under us"}
        )


def test_an_empty_proposal_instance_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        IntentSynthesisInvalidatedPayload(
            proposal_instance_id="", reason=InvalidationReason.BASIS_CHANGED
        )


@pytest.mark.parametrize(
    "extra", ["detail", "message", "proposal", "object", "authority", "decision"]
)
def test_the_invalidated_payload_forbids_extra_content(extra: str) -> None:
    with pytest.raises(ValidationError):
        IntentSynthesisInvalidatedPayload.model_validate(
            {
                "proposal_instance_id": "SYN-1",
                "reason": InvalidationReason.BASIS_CHANGED.value,
                extra: "smuggled",
            }
        )


def test_an_invalidated_event_round_trips_through_json() -> None:
    envelope = _envelope(
        EventType.INTENT_SYNTHESIS_INVALIDATED,
        IntentSynthesisInvalidatedPayload(
            proposal_instance_id="SYN-1", reason=InvalidationReason.TARGET_CHANGED
        ),
    )
    revived = parse_event(envelope.model_dump(mode="json"))
    assert revived == envelope


# --- exact event/payload contract -----------------------------------------------------


@pytest.mark.parametrize(
    ("event_type", "wrong_payload"),
    [
        (EventType.INTENT_SYNTHESIS_DECIDED, "object"),
        (EventType.INTENT_SYNTHESIS_DECIDED, "invalidated"),
        (EventType.INTENT_OBJECT_SYNTHESIZED, "decided"),
        (EventType.INTENT_OBJECT_SYNTHESIZED, "invalidated"),
        (EventType.INTENT_SYNTHESIS_INVALIDATED, "decided"),
        (EventType.INTENT_SYNTHESIS_INVALIDATED, "object"),
    ],
)
def test_a_wrong_synthesis_payload_type_is_rejected(
    event_type: EventType, wrong_payload: str
) -> None:
    """No implicit coercion between synthesis payload types."""
    payloads: dict[str, FrozenModel] = {
        "decided": _decided_payload(),
        "object": _object_payload(),
        "invalidated": IntentSynthesisInvalidatedPayload(
            proposal_instance_id="SYN-1", reason=InvalidationReason.BASIS_CHANGED
        ),
    }
    with pytest.raises(ValidationError):
        _envelope(event_type, payloads[wrong_payload])


def test_an_existing_event_still_rejects_a_synthesis_payload() -> None:
    with pytest.raises(ValidationError):
        _envelope(EventType.SEMANTIC_OBJECT_RECORDED, _object_payload())
