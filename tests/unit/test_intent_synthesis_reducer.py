"""T4 — reducer: durable decision projection and atomic application.

Three transitions, and only the middle one has an effect:

* ``DECIDED``      → the durable decision record is projected. No object, no edge, no
                     retirement, no marker.
* ``SYNTHESIZED``  → object + derivation edges + optional retirement + applied marker,
                     all in ONE reducer application.
* ``INVALIDATED``  → the invalidated marker, and nothing else.

The reducer validates STRUCTURE and replays deterministically. It never derives a
semantic view, never re-runs routing, and never re-decides authority.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from foundry.application.reducer import reduce_event
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    SourceKind,
)
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    IntentObjectPayload,
    IntentSynthesisDecidedPayload,
    IntentSynthesisInvalidatedPayload,
    StoredEvent,
)
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisDecision,
    IntentSynthesisRoute,
    InvalidationReason,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
)
from foundry.domain.intent_synthesis_state import incomplete_proposal_ids
from foundry.domain.semantic import Requirement
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticAddress,
    SemanticClaim,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.semantic_state import SemanticState
from foundry.domain.state import IntentState

PROJECT = "PROJ-A"
DECIDED_AT = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
AUTHOR = ReasonerFingerprint(provider="human", model="human://alice", policy_version="v1")
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref="human://alice")


def _identity(tag: str = "p1") -> SynthesisIdentity:
    return SynthesisIdentity(project_id=PROJECT, synthesis_run_id="RUN-1", model_proposal_id=tag)


def _address(address_id: str, scope: tuple[str, ...] = ("keyring",)) -> SemanticAddress:
    return SemanticAddress(
        address_id=address_id,
        project_id=PROJECT,
        subject="Client credential",
        facet="What are the rules of revocation?",
        scope=scope,
        created_by_judgment_id=f"JDG-addr-{address_id}",
    )


def _claim(claim_id: str, address_id: str) -> SemanticClaim:
    return SemanticClaim(
        claim_id=claim_id,
        project_id=PROJECT,
        address_id=address_id,
        predicate="when revocation takes effect",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="immediately"),
        evidence_ids=("EV-1",),
        authority=Authority.CANONICAL,
        provenance=PROVENANCE,
        created_by_judgment_id=f"JDG-claim-{claim_id}",
    )


def _semantic(
    claims: dict[str, str] | None = None, scopes: dict[str, tuple[str, ...]] | None = None
) -> SemanticState:
    """Claims mapped to their address ids; addresses carry the given scopes."""
    claims = claims or {"CLAIM-1": "ADDR-1"}
    scopes = scopes or {}
    addresses = {aid: _address(aid, scopes.get(aid, ("keyring",))) for aid in set(claims.values())}
    return SemanticState(
        addresses=addresses,
        claims={cid: _claim(cid, aid) for cid, aid in claims.items()},
    )


def _state(
    *,
    semantic: SemanticState | None = None,
    objects: dict[str, Requirement] | None = None,
    sequence: int = 0,
) -> IntentState:
    return IntentState(
        project_id=PROJECT,
        last_sequence=sequence,
        objects=objects or {},
        semantic=semantic or _semantic(),
    )


def _proposal(
    tag: str = "p1",
    *,
    disposition: IntentDisposition = IntentDisposition.NEW,
    statement: str = "Revocation is immediate.",
    basis_claim_ids: tuple[str, ...] = ("CLAIM-1",),
    relates_to_object_id: str | None = None,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=tag,
        disposition=disposition,
        statement=statement,
        rationale="Stated by the owner.",
        basis_claim_ids=basis_claim_ids,
        relates_to_object_id=relates_to_object_id,
    )


def _decided(
    *,
    identity: SynthesisIdentity | None = None,
    proposal: RequirementSynthesisProposal | None = None,
    route: IntentSynthesisRoute = IntentSynthesisRoute.APPLY,
    assigned_authority: Authority | None = Authority.CANONICAL,
    origin: SynthesisOrigin = SynthesisOrigin.HUMAN_STATED,
) -> EventEnvelope:
    ident = identity or _identity()
    return EventEnvelope(
        event_id=ident.event_id("DECIDED"),
        project_id=PROJECT,
        event_type=EventType.INTENT_SYNTHESIS_DECIDED,
        occurred_at=DECIDED_AT,
        payload=IntentSynthesisDecidedPayload(
            proposal=proposal or _proposal(ident.model_proposal_id),
            author=AUTHOR,
            identity=ident,
            origin=origin,
            assigned_authority=assigned_authority,
            decision=IntentSynthesisDecision(
                proposal_instance_id=ident.proposal_instance_id, route=route, reasons=("R",)
            ),
        ),
    )


def _requirement(
    identity: SynthesisIdentity,
    *,
    object_id: str | None = None,
    statement: str = "Revocation is immediate.",
    authority: Authority = Authority.CANONICAL,
    created_at: datetime = DECIDED_AT,
    scope: tuple[str, ...] = ("keyring",),
    basis_claim_ids: tuple[str, ...] = ("CLAIM-1",),
    relations: tuple[Relation, ...] | None = None,
    source_event_ids: tuple[str, ...] | None = None,
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
    revision: int = 1,
) -> Requirement:
    return Requirement(
        id=object_id or identity.object_id("REQ"),
        project_id=PROJECT,
        authority=authority,
        confidence=1.0,
        provenance=Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref="human://alice",
            source_event_ids=source_event_ids
            if source_event_ids is not None
            else (identity.event_id("DECIDED"),),
        ),
        created_at=created_at,
        scope=scope,
        relations=relations
        if relations is not None
        else tuple(
            Relation(relation_type=RelationType.DERIVED_FROM, target_id=cid)
            for cid in basis_claim_ids
        ),
        lifecycle=lifecycle,
        revision=revision,
        statement=statement,
        materiality=Materiality.LOW,
        requires_metric=False,
        requires_verification=False,
    )


def _synthesized(
    identity: SynthesisIdentity,
    *,
    obj: Requirement | None = None,
    basis_claim_ids: tuple[str, ...] = ("CLAIM-1",),
    replaces_object_id: str | None = None,
    event_id: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id or identity.event_id("SYNTHESIZED"),
        project_id=PROJECT,
        event_type=EventType.INTENT_OBJECT_SYNTHESIZED,
        occurred_at=DECIDED_AT,
        payload=IntentObjectPayload(
            object=obj or _requirement(identity, basis_claim_ids=basis_claim_ids),
            basis_claim_ids=basis_claim_ids,
            replaces_object_id=replaces_object_id,
            proposal_instance_id=identity.proposal_instance_id,
        ),
    )


def _invalidated(
    identity: SynthesisIdentity,
    *,
    reason: InvalidationReason = InvalidationReason.BASIS_CHANGED,
    event_id: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id or identity.event_id("INVALIDATED"),
        project_id=PROJECT,
        event_type=EventType.INTENT_SYNTHESIS_INVALIDATED,
        occurred_at=DECIDED_AT,
        payload=IntentSynthesisInvalidatedPayload(
            proposal_instance_id=identity.proposal_instance_id, reason=reason
        ),
    )


def _reduce(state: IntentState, *events: EventEnvelope) -> IntentState:
    for event in events:
        state = reduce_event(state, StoredEvent(sequence=state.last_sequence + 1, event=event))
    return state


# --- IntentState gains one additive plane ---------------------------------------------


def test_a_fresh_intent_state_has_an_empty_synthesis_plane() -> None:
    state = _state()
    assert state.intent_synthesis.decisions == {}
    assert state.intent_synthesis.applied_proposal_ids == ()
    assert state.intent_synthesis.invalidated_proposal_ids == ()
    assert state.intent_synthesis.retirements == ()


def test_intent_state_still_round_trips() -> None:
    state = _state()
    assert IntentState.model_validate(state.model_dump(mode="json")) == state


def test_a_non_synthesis_event_leaves_the_synthesis_plane_empty() -> None:
    """Historical streams replay unchanged because the field defaults empty."""
    state = _reduce(
        _state(),
        EventEnvelope(
            event_id="EVT-closure",
            project_id=PROJECT,
            event_type=EventType.INTENT_REOPENED,
            occurred_at=DECIDED_AT,
            payload=__import__("foundry.domain.events", fromlist=["ReopenPayload"]).ReopenPayload(
                scope="keyring", reason="r"
            ),
        ),
    )
    assert state.intent_synthesis.decisions == {}


# --- DECIDED: projection only ----------------------------------------------------------


def test_decided_projects_the_durable_decision_record() -> None:
    ident = _identity()
    state = _reduce(_state(), _decided(identity=ident))
    record = state.intent_synthesis.decisions[ident.proposal_instance_id]
    assert record.identity == ident
    assert record.proposal.statement == "Revocation is immediate."
    assert record.author == AUTHOR
    assert record.origin is SynthesisOrigin.HUMAN_STATED
    assert record.assigned_authority is Authority.CANONICAL
    assert record.decision_event_id == ident.event_id("DECIDED")
    assert record.decided_at == DECIDED_AT


def test_decided_creates_no_effect_whatsoever() -> None:
    ident = _identity()
    state = _reduce(_state(), _decided(identity=ident))
    assert state.objects == {}
    assert state.semantic.derivations == ()
    assert state.intent_synthesis.retirements == ()
    assert state.intent_synthesis.applied_proposal_ids == ()
    assert state.intent_synthesis.invalidated_proposal_ids == ()
    assert incomplete_proposal_ids(state.intent_synthesis) == (ident.proposal_instance_id,)


def test_decided_requires_the_deterministic_event_id() -> None:
    ident = _identity()
    event = _decided(identity=ident).model_copy(update={"event_id": "EVT-arbitrary"})
    with pytest.raises(ValueError, match="event id"):
        _reduce(_state(), event)


def test_a_proposal_cannot_be_decided_twice() -> None:
    ident = _identity()
    state = _reduce(_state(), _decided(identity=ident))
    with pytest.raises(ValueError, match="already"):
        _reduce(state, _decided(identity=ident))


def test_an_apply_decision_must_carry_an_assigned_authority() -> None:
    """An applied object necessarily carries an authority."""
    with pytest.raises(ValueError, match="authority"):
        _reduce(_state(), _decided(assigned_authority=None))


def test_existing_unchanged_can_never_be_an_apply_lifecycle() -> None:
    """A durable APPLY would contradict the proposal's declared lifecycle meaning."""
    ident = _identity()
    proposal = _proposal(
        ident.model_proposal_id,
        disposition=IntentDisposition.EXISTING_UNCHANGED,
        relates_to_object_id="REQ-existing",
    )
    with pytest.raises(ValueError, match="EXISTING_UNCHANGED"):
        _reduce(_state(), _decided(identity=ident, proposal=proposal))


def test_a_non_apply_decision_is_projected_without_authority() -> None:
    ident = _identity()
    state = _reduce(
        _state(),
        _decided(identity=ident, route=IntentSynthesisRoute.REQUIRE_HUMAN, assigned_authority=None),
    )
    record = state.intent_synthesis.decisions[ident.proposal_instance_id]
    assert record.assigned_authority is None
    assert incomplete_proposal_ids(state.intent_synthesis) == ()


# --- C20: the effect must belong to the durable decision -------------------------------


def _decided_state(
    ident: SynthesisIdentity,
    *,
    proposal: RequirementSynthesisProposal | None = None,
    assigned_authority: Authority = Authority.CANONICAL,
    semantic: SemanticState | None = None,
    objects: dict[str, Requirement] | None = None,
) -> IntentState:
    return _reduce(
        _state(semantic=semantic, objects=objects),
        _decided(identity=ident, proposal=proposal, assigned_authority=assigned_authority),
    )


def test_synthesized_requires_a_prior_durable_decision() -> None:
    ident = _identity()
    with pytest.raises(ValueError, match="no durable decision"):
        _reduce(_state(), _synthesized(ident))


def test_synthesized_requires_the_decision_route_to_be_apply() -> None:
    ident = _identity()
    state = _reduce(
        _state(),
        _decided(identity=ident, route=IntentSynthesisRoute.NO_CHANGE, assigned_authority=None),
    )
    with pytest.raises(ValueError, match="APPLY"):
        _reduce(state, _synthesized(ident))


def test_a_proposal_cannot_be_applied_twice() -> None:
    ident = _identity()
    state = _reduce(_decided_state(ident), _synthesized(ident))
    with pytest.raises(ValueError, match="already applied"):
        _reduce(state, _synthesized(ident))


def test_an_invalidated_proposal_cannot_then_be_applied() -> None:
    ident = _identity()
    state = _reduce(_decided_state(ident), _invalidated(ident))
    with pytest.raises(ValueError, match="already invalidated"):
        _reduce(state, _synthesized(ident))


def test_synthesized_requires_the_deterministic_event_id() -> None:
    ident = _identity()
    with pytest.raises(ValueError, match="event id"):
        _reduce(_decided_state(ident), _synthesized(ident, event_id="EVT-arbitrary"))


def test_the_object_id_must_be_the_deterministic_one() -> None:
    ident = _identity()
    obj = _requirement(ident, object_id="REQ-hand-picked")
    with pytest.raises(ValueError, match="object id"):
        _reduce(_decided_state(ident), _synthesized(ident, obj=obj))


def test_the_object_id_must_not_already_exist() -> None:
    ident = _identity()
    existing = _requirement(ident)
    state = _decided_state(ident, objects={existing.id: existing})
    with pytest.raises(ValueError, match="already exists"):
        _reduce(state, _synthesized(ident))


def test_a_durable_decision_for_one_statement_cannot_establish_another() -> None:
    ident = _identity()
    obj = _requirement(ident, statement="A COMPLETELY DIFFERENT commitment.")
    with pytest.raises(ValueError, match="statement"):
        _reduce(_decided_state(ident), _synthesized(ident, obj=obj))


def test_a_proposed_decision_cannot_establish_a_canonical_object() -> None:
    ident = _identity()
    state = _decided_state(ident, assigned_authority=Authority.PROPOSED)
    obj = _requirement(ident, authority=Authority.CANONICAL)
    with pytest.raises(ValueError, match="authority"):
        _reduce(state, _synthesized(ident, obj=obj))


def test_the_object_creation_time_must_be_the_durable_decision_time() -> None:
    """C19 made decided_at durable so recovery cannot mint a different creation time."""
    ident = _identity()
    obj = _requirement(ident, created_at=datetime(2026, 12, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="created_at"):
        _reduce(_decided_state(ident), _synthesized(ident, obj=obj))


def test_the_basis_must_equal_the_decided_basis_exactly() -> None:
    ident = _identity()
    proposal = _proposal(ident.model_proposal_id, basis_claim_ids=("CLAIM-1",))
    state = _decided_state(
        ident, proposal=proposal, semantic=_semantic({"CLAIM-1": "ADDR-1", "CLAIM-2": "ADDR-1"})
    )
    with pytest.raises(ValueError, match="basis"):
        _reduce(state, _synthesized(ident, basis_claim_ids=("CLAIM-1", "CLAIM-2")))


def test_every_basis_claim_must_exist_in_semantic_state() -> None:
    ident = _identity()
    proposal = _proposal(ident.model_proposal_id, basis_claim_ids=("CLAIM-missing",))
    state = _decided_state(ident, proposal=proposal)
    with pytest.raises(ValueError, match="CLAIM-missing"):
        _reduce(state, _synthesized(ident, basis_claim_ids=("CLAIM-missing",)))


def test_a_newly_synthesized_object_must_arrive_active_at_revision_one() -> None:
    ident = _identity()
    obj = _requirement(ident, lifecycle=LifecycleStatus.SUPERSEDED, revision=3)
    with pytest.raises(ValueError, match="revision|lifecycle"):
        _reduce(_decided_state(ident), _synthesized(ident, obj=obj))


# --- runtime-owned scope ---------------------------------------------------------------


def test_the_object_scope_must_equal_the_union_of_its_basis_address_scopes() -> None:
    ident = _identity()
    proposal = _proposal(ident.model_proposal_id, basis_claim_ids=("CLAIM-1", "CLAIM-2"))
    semantic = _semantic(
        {"CLAIM-1": "ADDR-1", "CLAIM-2": "ADDR-2"},
        {"ADDR-1": ("keyring",), "ADDR-2": ("relay",)},
    )
    state = _decided_state(ident, proposal=proposal, semantic=semantic)
    good = _requirement(ident, scope=("keyring", "relay"), basis_claim_ids=("CLAIM-1", "CLAIM-2"))
    applied = _reduce(state, _synthesized(ident, obj=good, basis_claim_ids=("CLAIM-1", "CLAIM-2")))
    assert applied.objects[good.id].scope == ("keyring", "relay")

    bad = _requirement(ident, scope=("keyring",), basis_claim_ids=("CLAIM-1", "CLAIM-2"))
    with pytest.raises(ValueError, match="scope"):
        _reduce(state, _synthesized(ident, obj=bad, basis_claim_ids=("CLAIM-1", "CLAIM-2")))


def test_project_wide_addresses_yield_a_project_wide_object() -> None:
    ident = _identity()
    semantic = _semantic({"CLAIM-1": "ADDR-1"}, {"ADDR-1": ()})
    state = _decided_state(ident, semantic=semantic)
    obj = _requirement(ident, scope=())
    applied = _reduce(state, _synthesized(ident, obj=obj))
    assert applied.objects[obj.id].scope == ()


# --- I3: dual provenance ---------------------------------------------------------------


def test_relations_target_claim_ids_while_edges_target_asserting_judgments() -> None:
    """The asymmetry is load-bearing: an edge to a claim id would not propagate."""
    ident = _identity()
    proposal = _proposal(ident.model_proposal_id, basis_claim_ids=("CLAIM-1", "CLAIM-2"))
    semantic = _semantic({"CLAIM-1": "ADDR-1", "CLAIM-2": "ADDR-1"})
    state = _decided_state(ident, proposal=proposal, semantic=semantic)
    obj = _requirement(ident, basis_claim_ids=("CLAIM-1", "CLAIM-2"))
    applied = _reduce(state, _synthesized(ident, obj=obj, basis_claim_ids=("CLAIM-1", "CLAIM-2")))

    stored = applied.objects[obj.id]
    relation_targets = {
        r.target_id for r in stored.relations if r.relation_type is RelationType.DERIVED_FROM
    }
    assert relation_targets == {"CLAIM-1", "CLAIM-2"}

    edges = [e for e in applied.semantic.derivations if e.child_id == obj.id]
    assert {e.parent_id for e in edges} == {
        semantic.claims["CLAIM-1"].created_by_judgment_id,
        semantic.claims["CLAIM-2"].created_by_judgment_id,
    }
    for edge in edges:
        assert edge.parent_id not in relation_targets
        assert edge.recorded_by_event_id == ident.event_id("SYNTHESIZED")

    assert len(relation_targets) == len(proposal.basis_claim_ids) == len(edges)


def test_a_missing_basis_relation_is_refused() -> None:
    ident = _identity()
    proposal = _proposal(ident.model_proposal_id, basis_claim_ids=("CLAIM-1", "CLAIM-2"))
    semantic = _semantic({"CLAIM-1": "ADDR-1", "CLAIM-2": "ADDR-1"})
    state = _decided_state(ident, proposal=proposal, semantic=semantic)
    obj = _requirement(
        ident,
        basis_claim_ids=("CLAIM-1", "CLAIM-2"),
        relations=(Relation(relation_type=RelationType.DERIVED_FROM, target_id="CLAIM-1"),),
    )
    with pytest.raises(ValueError, match="relation"):
        _reduce(state, _synthesized(ident, obj=obj, basis_claim_ids=("CLAIM-1", "CLAIM-2")))


def test_an_unrelated_relation_cannot_be_smuggled_in() -> None:
    ident = _identity()
    obj = _requirement(
        ident,
        relations=(
            Relation(relation_type=RelationType.DERIVED_FROM, target_id="CLAIM-1"),
            Relation(relation_type=RelationType.MEASURED_BY, target_id="METRIC-1"),
        ),
    )
    with pytest.raises(ValueError, match="relation"):
        _reduce(_decided_state(ident), _synthesized(ident, obj=obj))


def test_the_object_provenance_points_back_at_the_durable_decision() -> None:
    ident = _identity()
    obj = _requirement(ident, source_event_ids=("EVT-somewhere-else",))
    with pytest.raises(ValueError, match="provenance|source_event_ids"):
        _reduce(_decided_state(ident), _synthesized(ident, obj=obj))


# --- disposition / replacement ---------------------------------------------------------


def _stale_target(
    *,
    object_id: str = "REQ-old",
    scope: tuple[str, ...] = ("keyring",),
    authority: Authority = Authority.CANONICAL,
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
) -> Requirement:
    return Requirement(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=DECIDED_AT,
        scope=scope,
        lifecycle=lifecycle,
        statement="The older commitment.",
        materiality=Materiality.LOW,
        requires_metric=False,
        requires_verification=False,
    )


def test_a_new_disposition_must_not_name_a_replacement() -> None:
    ident = _identity()
    with pytest.raises(ValueError, match="NEW"):
        _reduce(_decided_state(ident), _synthesized(ident, replaces_object_id="REQ-old"))


def test_a_replacement_must_name_the_decided_target() -> None:
    ident = _identity()
    target = _stale_target()
    proposal = _proposal(
        ident.model_proposal_id,
        disposition=IntentDisposition.REPLACES_STALE,
        relates_to_object_id=target.id,
    )
    state = _decided_state(ident, proposal=proposal, objects={target.id: target})
    with pytest.raises(ValueError, match="replaces_object_id"):
        _reduce(state, _synthesized(ident, replaces_object_id="REQ-somebody-else"))


def _replacement_state(
    ident: SynthesisIdentity,
    target: Requirement,
    *,
    assigned_authority: Authority = Authority.CANONICAL,
) -> IntentState:
    proposal = _proposal(
        ident.model_proposal_id,
        disposition=IntentDisposition.REPLACES_STALE,
        relates_to_object_id=target.id,
    )
    return _decided_state(
        ident, proposal=proposal, assigned_authority=assigned_authority, objects={target.id: target}
    )


def test_a_non_canonical_replacement_cannot_retire_a_canonical_target() -> None:
    """C11: canonical authority is preserved by a single equality safeguard."""
    ident = _identity()
    target = _stale_target(authority=Authority.CANONICAL)
    state = _replacement_state(ident, target, assigned_authority=Authority.PROPOSED)
    obj = _requirement(ident, authority=Authority.PROPOSED)
    with pytest.raises(ValueError, match="CANONICAL"):
        _reduce(state, _synthesized(ident, obj=obj, replaces_object_id=target.id))


def test_a_retired_target_cannot_be_retired_again() -> None:
    ident = _identity()
    target = _stale_target(lifecycle=LifecycleStatus.SUPERSEDED)
    state = _replacement_state(ident, target)
    with pytest.raises(ValueError, match="ACTIVE|lifecycle"):
        _reduce(state, _synthesized(ident, replaces_object_id=target.id))


def test_a_missing_replacement_target_is_refused() -> None:
    ident = _identity()
    target = _stale_target()
    proposal = _proposal(
        ident.model_proposal_id,
        disposition=IntentDisposition.REPLACES_STALE,
        relates_to_object_id=target.id,
    )
    state = _decided_state(ident, proposal=proposal)
    with pytest.raises(ValueError, match="REQ-old"):
        _reduce(state, _synthesized(ident, replaces_object_id=target.id))


# --- C21: a replacement may not narrow applicability ------------------------------------


def test_a_scoped_replacement_cannot_retire_a_project_wide_requirement() -> None:
    """The required C21 negative control: intent must not silently vanish elsewhere."""
    ident = _identity()
    target = _stale_target(scope=())
    state = _replacement_state(ident, target)
    obj = _requirement(ident, scope=("keyring",))
    with pytest.raises(ValueError, match="scope"):
        _reduce(state, _synthesized(ident, obj=obj, replaces_object_id=target.id))


def test_a_replacement_missing_one_of_the_targets_scopes_is_refused() -> None:
    ident = _identity()
    target = _stale_target(scope=("keyring", "relay"))
    state = _replacement_state(ident, target)
    obj = _requirement(ident, scope=("keyring",))
    with pytest.raises(ValueError, match="scope"):
        _reduce(state, _synthesized(ident, obj=obj, replaces_object_id=target.id))


def test_an_equal_scope_replacement_is_eligible() -> None:
    ident = _identity()
    target = _stale_target(scope=("keyring",))
    state = _replacement_state(ident, target)
    applied = _reduce(state, _synthesized(ident, replaces_object_id=target.id))
    assert applied.objects[target.id].lifecycle is LifecycleStatus.SUPERSEDED


def test_a_broader_replacement_is_eligible() -> None:
    ident = _identity()
    target = _stale_target(scope=("keyring",))
    semantic = _semantic({"CLAIM-1": "ADDR-1"}, {"ADDR-1": ("keyring", "relay")})
    proposal = _proposal(
        ident.model_proposal_id,
        disposition=IntentDisposition.REPLACES_STALE,
        relates_to_object_id=target.id,
    )
    state = _decided_state(ident, proposal=proposal, semantic=semantic, objects={target.id: target})
    obj = _requirement(ident, scope=("keyring", "relay"))
    applied = _reduce(state, _synthesized(ident, obj=obj, replaces_object_id=target.id))
    assert applied.objects[target.id].lifecycle is LifecycleStatus.SUPERSEDED


def test_a_project_wide_replacement_is_eligible() -> None:
    ident = _identity()
    target = _stale_target(scope=("keyring",))
    semantic = _semantic({"CLAIM-1": "ADDR-1"}, {"ADDR-1": ()})
    proposal = _proposal(
        ident.model_proposal_id,
        disposition=IntentDisposition.REPLACES_STALE,
        relates_to_object_id=target.id,
    )
    state = _decided_state(ident, proposal=proposal, semantic=semantic, objects={target.id: target})
    obj = _requirement(ident, scope=())
    applied = _reduce(state, _synthesized(ident, obj=obj, replaces_object_id=target.id))
    assert applied.objects[target.id].lifecycle is LifecycleStatus.SUPERSEDED


# --- atomicity --------------------------------------------------------------------------


def test_a_plain_new_application_establishes_object_edges_and_marker_together() -> None:
    ident = _identity()
    applied = _reduce(_decided_state(ident), _synthesized(ident))
    obj_id = ident.object_id("REQ")
    assert obj_id in applied.objects
    assert [e.child_id for e in applied.semantic.derivations] == [obj_id]
    assert applied.intent_synthesis.applied_proposal_ids == (ident.proposal_instance_id,)
    assert applied.intent_synthesis.retirements == ()


def test_a_replacement_establishes_retirement_in_the_same_transition() -> None:
    """There is no state where the replacement exists but its retirement is missing."""
    ident = _identity()
    target = _stale_target()
    state = _replacement_state(ident, target)
    applied = _reduce(state, _synthesized(ident, replaces_object_id=target.id))

    new_id = ident.object_id("REQ")
    assert applied.objects[new_id].lifecycle is LifecycleStatus.ACTIVE
    retired = applied.objects[target.id]
    assert retired.lifecycle is LifecycleStatus.SUPERSEDED
    assert retired.revision == target.revision + 1
    assert applied.intent_synthesis.applied_proposal_ids == (ident.proposal_instance_id,)
    record = applied.intent_synthesis.retirements[0]
    assert record.retired_object_id == target.id
    assert record.replaced_by_object_id == new_id
    assert record.proposal_instance_id == ident.proposal_instance_id
    assert record.recorded_by_event_id == ident.event_id("SYNTHESIZED")
    assert len(applied.intent_synthesis.retirements) == 1


# --- INVALIDATED ------------------------------------------------------------------------


def test_invalidated_records_only_the_marker() -> None:
    ident = _identity()
    state = _reduce(_decided_state(ident), _invalidated(ident))
    assert state.intent_synthesis.invalidated_proposal_ids == (ident.proposal_instance_id,)
    assert state.objects == {}
    assert state.semantic.derivations == ()
    assert state.intent_synthesis.retirements == ()
    assert state.intent_synthesis.applied_proposal_ids == ()


def test_invalidated_requires_a_prior_apply_decision() -> None:
    ident = _identity()
    with pytest.raises(ValueError, match="no durable decision"):
        _reduce(_state(), _invalidated(ident))


def test_an_applied_proposal_cannot_then_be_invalidated() -> None:
    ident = _identity()
    state = _reduce(_decided_state(ident), _synthesized(ident))
    with pytest.raises(ValueError, match="already applied"):
        _reduce(state, _invalidated(ident))


def test_invalidated_requires_the_deterministic_event_id() -> None:
    ident = _identity()
    with pytest.raises(ValueError, match="event id"):
        _reduce(_decided_state(ident), _invalidated(ident, event_id="EVT-arbitrary"))


@pytest.mark.parametrize("reason", list(InvalidationReason))
def test_every_bounded_reason_is_recorded(reason: InvalidationReason) -> None:
    ident = _identity()
    state = _reduce(_decided_state(ident), _invalidated(ident, reason=reason))
    assert state.intent_synthesis.invalidated_proposal_ids == (ident.proposal_instance_id,)


# --- I24 after every transition ----------------------------------------------------------


def test_the_partition_holds_after_each_transition() -> None:
    ident = _identity()
    decided = _decided_state(ident)
    pid = ident.proposal_instance_id
    assert incomplete_proposal_ids(decided.intent_synthesis) == (pid,)
    assert decided.intent_synthesis.applied_proposal_ids == ()
    assert decided.intent_synthesis.invalidated_proposal_ids == ()

    applied = _reduce(decided, _synthesized(ident))
    assert applied.intent_synthesis.applied_proposal_ids == (pid,)
    assert applied.intent_synthesis.invalidated_proposal_ids == ()
    assert incomplete_proposal_ids(applied.intent_synthesis) == ()

    invalidated = _reduce(decided, _invalidated(ident))
    assert invalidated.intent_synthesis.invalidated_proposal_ids == (pid,)
    assert invalidated.intent_synthesis.applied_proposal_ids == ()
    assert incomplete_proposal_ids(invalidated.intent_synthesis) == ()


# --- replay / C2 --------------------------------------------------------------------------


def test_replay_before_the_effect_reproduces_the_earlier_projection_exactly() -> None:
    """Immutability belongs to the log; the current projection is allowed to move."""
    ident = _identity()
    target = _stale_target()
    base = _state(objects={target.id: target})
    decided = _decided(
        identity=ident,
        proposal=_proposal(
            ident.model_proposal_id,
            disposition=IntentDisposition.REPLACES_STALE,
            relates_to_object_id=target.id,
        ),
    )
    synthesized = _synthesized(ident, replaces_object_id=target.id)

    at_n1 = _reduce(base, decided)
    assert at_n1.objects[target.id].lifecycle is LifecycleStatus.ACTIVE
    assert at_n1.objects[target.id].revision == target.revision
    assert ident.object_id("REQ") not in at_n1.objects
    assert incomplete_proposal_ids(at_n1.intent_synthesis) == (ident.proposal_instance_id,)

    at_n2 = _reduce(at_n1, synthesized)
    assert at_n2.objects[target.id].lifecycle is LifecycleStatus.SUPERSEDED
    assert at_n2.objects[target.id].revision == target.revision + 1
    assert at_n2.objects[ident.object_id("REQ")].id != target.id
    assert len(at_n2.intent_synthesis.retirements) == 1
    assert at_n2.intent_synthesis.applied_proposal_ids == (ident.proposal_instance_id,)
    assert len(at_n2.semantic.derivations) == 1

    replayed_to_n1 = _reduce(base, decided)
    assert replayed_to_n1.objects == at_n1.objects
    assert replayed_to_n1.intent_synthesis == at_n1.intent_synthesis
