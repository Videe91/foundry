"""Reconciliation-aware delivery readiness (Slice-1 task T10, pure domain half).

Why v2 readiness exists at all
------------------------------
``SemanticReadiness.stale_object_ids`` is **topological**: once a basis claim is
superseded, every object derived from it is in the blast radius, and it stays there
permanently. That is correct for v1 — the blast radius is exactly what surfaces work
that needs doing — but it makes the raw set unusable as a *delivery* gate. After a stale
Requirement has been properly replaced and retired, the historical object is still a
descendant of a superseded judgment, so ``ready`` remains ``False`` forever and the
project can never deliver again once it has corrected itself.

V2 therefore partitions that same raw set rather than recomputing it: ids that are
**provably reconciled** stop blocking, everything else still does. The raw set is never
shortened and nothing is dropped; a reconciled id remains visible as history (I19/C6).

"Provably" is the load-bearing word. Reconciliation is accepted only on durable
``RetirementRecord`` evidence leading to a head that is current, in scope, itself fresh,
and — when the original was canonical — canonical too. A ``SUPERSEDED`` lifecycle proves
nothing on its own: anything could have set it.

C25 — dependency direction
--------------------------
This module holds the reconciliation and readiness primitives ONLY. The final v2 DTO
lives in ``application/handoff_v2.py``, because it must embed ``CanonicalIntentPackage``,
which lives in ``application.package``. The earlier design sketch put the whole v2 model
in ``domain/``, but a domain module importing an application module to satisfy a file
location would invert the dependency for no benefit. The split resolves it without
relocating the package or duplicating it.

Pure domain: no I/O, no clock, no randomness, no application import.
"""

from __future__ import annotations

from typing import Final

from foundry.domain.common import Authority, FrozenModel, LifecycleStatus
from foundry.domain.handoff import SemanticReadiness, scoped_stale_object_ids
from foundry.domain.intent_synthesis_state import incomplete_proposal_ids
from foundry.domain.semantic_view import CurrentSemanticView, SemanticLocus
from foundry.domain.state import IntentState

__all__ = [
    "IntentBasisRef",
    "IntentDeliveryReadiness",
    "build_intent_delivery_readiness",
    "partition_stale_object_ids",
    "scoped_incomplete_synthesis_proposal_ids",
    "v2_blocking_stale_object_ids",
    "validly_reconciled",
]

_DEAD_AUTHORITIES: Final[frozenset[Authority]] = frozenset(
    {Authority.REJECTED, Authority.SUPERSEDED}
)


class IntentBasisRef(FrozenModel):
    """The bridge from one intent object to the semantic claims it rests on. Ids only.

    Deliberately carries no statement, value, predicate, rationale or provenance body:
    the downstream consumer resolves ids against the ledger, and copying content here
    would create a second, drifting record of the same truth (I9).

    Empty tuples are legal. A legacy object created before v2 synthesis provenance
    existed simply has no claim basis, and inventing one for it would be a lie.
    """

    object_id: str
    basis_claim_ids: tuple[str, ...] = ()
    basis_locus_ids: tuple[str, ...] = ()


class IntentDeliveryReadiness(FrozenModel):
    """Whether this scope is safe to hand downstream, and precisely why not.

    ``semantic_readiness`` is the v1 object embedded **verbatim**, never reinterpreted:
    v2 adds a decision on top of it rather than replacing what it means.
    """

    semantic_readiness: SemanticReadiness
    blocking_stale_object_ids: tuple[str, ...] = ()
    reconciled_stale_object_ids: tuple[str, ...] = ()
    incomplete_synthesis_proposal_ids: tuple[str, ...] = ()
    deliverable: bool = False


def _object_applies(scope_descriptor: tuple[str, ...], scope: str) -> bool:
    return scope_descriptor == () or scope in scope_descriptor


def validly_reconciled(
    state: IntentState, view: CurrentSemanticView, scope: str, object_id: str
) -> bool:
    """Has ``object_id``'s staleness been genuinely resolved by a replacement chain?

    Every condition below is a way the answer could be "no" while still *looking* like a
    resolution, which is why each is checked rather than assumed:

    1. a durable ``RetirementRecord`` must exist — a ``SUPERSEDED`` lifecycle alone could
       have been set by any legacy path and proves nothing about a valid replacement;
    2. each retired object must actually be ``SUPERSEDED`` in the current projection — a
       record contradicting the projection is evidence of a defect, not of reconciliation,
       and is never silently trusted;
    3. the chain is followed to its head, so ``A → B → C`` resolves to ``C``; a visited
       set makes a malformed cycle terminate as unreconciled instead of hanging;
    4. the head must be current, live and in scope — a replacement that does not apply
       here cannot settle an obligation that does;
    5. the head must not itself be stale, or nothing is settled: the correction merely
       moved, and the original must keep blocking until the chain comes to rest;
    6. a canonical original needs a canonical head (C11), checked here independently of
       routing and the reducer so the guarantee does not rest on one layer alone.
    """
    retirement_by_retired = {
        record.retired_object_id: record.replaced_by_object_id
        for record in state.intent_synthesis.retirements
    }
    original = state.objects.get(object_id)
    if original is None or object_id not in retirement_by_retired:
        return False
    requires_canonical = original.authority is Authority.CANONICAL

    seen: set[str] = set()
    current_id = object_id
    while current_id in retirement_by_retired:
        if current_id in seen:
            return False
        seen.add(current_id)
        retired = state.objects.get(current_id)
        if retired is None or retired.lifecycle is not LifecycleStatus.SUPERSEDED:
            return False
        current_id = retirement_by_retired[current_id]

    head = state.objects.get(current_id)
    if head is None:
        return False
    if head.lifecycle is not LifecycleStatus.ACTIVE or head.authority in _DEAD_AUTHORITIES:
        return False
    if not _object_applies(tuple(head.scope), scope):
        return False
    if head.id in view.stale_ids:
        return False
    return not (requires_canonical and head.authority is not Authority.CANONICAL)


def partition_stale_object_ids(
    state: IntentState,
    view: CurrentSemanticView,
    scope: str,
    in_scope_loci: tuple[SemanticLocus, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split the v1 scoped stale set into ``(blocking, reconciled)``.

    The attribution law is NOT reimplemented: ``scoped_stale_object_ids`` stays the one
    definition of which stale ids belong to this scope, and v2 only decides which of
    them have been resolved. Every raw id lands in exactly one half.
    """
    raw = scoped_stale_object_ids(state.semantic, view, in_scope_loci)
    reconciled = tuple(
        sorted(object_id for object_id in raw if validly_reconciled(state, view, scope, object_id))
    )
    reconciled_set = frozenset(reconciled)
    blocking = tuple(sorted(object_id for object_id in raw if object_id not in reconciled_set))
    return blocking, reconciled


def v2_blocking_stale_object_ids(
    state: IntentState,
    view: CurrentSemanticView,
    scope: str,
    in_scope_loci: tuple[SemanticLocus, ...],
) -> tuple[str, ...]:
    """The stale ids that still block delivery for this scope."""
    blocking, _ = partition_stale_object_ids(state, view, scope, in_scope_loci)
    return blocking


def scoped_incomplete_synthesis_proposal_ids(state: IntentState, scope: str) -> tuple[str, ...]:
    """Incomplete synthesis proposals whose basis applies to ``scope``.

    ``incomplete_proposal_ids`` is project-wide, but handoff is per scope: without this
    filter one unrelated scope's interrupted synthesis would freeze delivery for the
    whole project.

    Applicability is rebuilt structurally — claim → address → address scope — the same
    rule synthesis used to derive the object's own scope. Never from statement text, and
    never from the synthesis request, which no longer exists by the time recovery or
    delivery runs. A proposal whose basis has vanished stays listed rather than being
    silently dropped: it is still unfinished work, and hiding it would be the one
    outcome that lets an incomplete proposal escape the gate.
    """
    scoped: list[str] = []
    for proposal_instance_id in incomplete_proposal_ids(state.intent_synthesis):
        record = state.intent_synthesis.decisions[proposal_instance_id]
        scopes: set[str] = set()
        resolved = True
        for claim_id in record.proposal.basis_claim_ids:
            claim = state.semantic.claims.get(claim_id)
            address = None if claim is None else state.semantic.addresses.get(claim.address_id)
            if address is None:
                resolved = False
                break
            scopes.update(address.scope)
        if not resolved or _object_applies(tuple(sorted(scopes)), scope):
            scoped.append(proposal_instance_id)
    return tuple(scoped)


def build_intent_delivery_readiness(
    state: IntentState,
    view: CurrentSemanticView,
    scope: str,
    in_scope_loci: tuple[SemanticLocus, ...],
    semantic_readiness: SemanticReadiness,
) -> IntentDeliveryReadiness:
    """Compose the v2 gate from the v1 readiness plus the two v2-specific conditions.

    The formula deliberately does **not** consult ``semantic_readiness.ready``: that
    value folds in the raw stale set, which is exactly the thing v2 exists to refine.
    ``open_locus_ids`` is likewise not a gate here — adding it would change existing
    readiness semantics under the guise of a new feature.
    """
    blocking, reconciled = partition_stale_object_ids(state, view, scope, in_scope_loci)
    incomplete = scoped_incomplete_synthesis_proposal_ids(state, scope)
    deliverable = (
        semantic_readiness.closure.closed
        and not semantic_readiness.disputed_locus_ids
        and not semantic_readiness.pending_material_judgment_ids
        and not blocking
        and not incomplete
    )
    return IntentDeliveryReadiness(
        semantic_readiness=semantic_readiness,
        blocking_stale_object_ids=blocking,
        reconciled_stale_object_ids=reconciled,
        incomplete_synthesis_proposal_ids=incomplete,
        deliverable=deliverable,
    )
