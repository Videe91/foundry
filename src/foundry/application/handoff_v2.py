"""Intent → Decision handoff v2: the delivery gate and traceability envelope (T10).

The **contract** delivered downstream is unchanged and remains ``CanonicalIntentPackage``.
V2 adds only two things around it: a reconciliation-aware answer to *may this be
delivered at all?*, and an id-only bridge from each intent object to the semantic claims
it rests on, so Architecture can trace a commitment back to its evidence without any
content being copied out of the ledger.

Why the DTO lives here and not in ``domain/`` (C25)
--------------------------------------------------
It embeds ``CanonicalIntentPackage``, which lives in ``application.package``. Putting the
model in ``domain/`` — as the original spec sketch did — would force a domain module to
import an application one purely to satisfy a file path. The reconciliation and readiness
primitives stay pure in ``domain/handoff_v2.py``; only the DTO and its builder live here,
where application → application is the natural direction. The package is neither
relocated nor duplicated.

V1 is untouched and undeprecated. Both versions are built from the same state, no
consumer is migrated, and ``domain/handoff.py`` / ``application/handoff.py`` remain
byte-identical (I11).
"""

from __future__ import annotations

from typing import Final, Literal

from foundry.application.handoff import build_intent_decision_handoff
from foundry.application.package import CanonicalIntentPackage, build_intent_package
from foundry.domain.basis import BASIS_BLOCKER_CODES
from foundry.domain.common import Authority, FrozenModel, LifecycleStatus, RelationType
from foundry.domain.handoff import locus_in_scope
from foundry.domain.handoff_v2 import (
    IntentBasisRef,
    IntentDeliveryReadiness,
    build_intent_delivery_readiness,
)
from foundry.domain.intent_synthesis import INTENT_BEARING_SEMANTIC_KINDS
from foundry.domain.relevance import RELEVANCE_BLOCKER_CODES
from foundry.domain.scope import scope_applies
from foundry.domain.semantic import SemanticBase
from foundry.domain.semantic_view import CurrentSemanticView, SemanticLocus, derive_view
from foundry.domain.state import IntentState

__all__ = [
    "HANDOFF_V2_VERSION",
    "IntentDecisionHandoffV2",
    "IntentDeliveryNotReadyError",
    "build_intent_decision_handoff_v2",
]

type HandoffV2Version = Literal["intent-decision-handoff-v2"]
HANDOFF_V2_VERSION: Final[HandoffV2Version] = "intent-decision-handoff-v2"

_BLOCKER_CODE_ORDER: Final[tuple[str, ...]] = (
    "CLOSURE_NOT_MET",
    "DISPUTED_LOCUS",
    "PENDING_MATERIAL_JUDGMENT",
    "UNRECONCILED_STALE_OBJECT",
    "MULTIPLE_CANONICAL_ROOTS",
    "ORPHANED_CANONICAL_OBJECT",
    "RELEVANCE_CYCLE",
    "UNGROUNDED_CANONICAL_OBJECT",
    "DEAD_BASIS",
    "UNLAWFUL_BASIS_AUTHORITY",
    "ASSUMPTION_IN_BASIS",
    "BASIS_CYCLE",
    "INCOMPLETE_SYNTHESIS",
)


class IntentDeliveryNotReadyError(RuntimeError):
    """Delivery was refused. Names every applicable category, not merely the first.

    Stopping at the first blocker would make resolution an iterative guessing game;
    the caller should be able to see the whole set of reasons at once. Exact ids live in
    the readiness object — this exception names categories only.
    """

    def __init__(self, blocker_codes: tuple[str, ...]) -> None:
        self.blocker_codes = blocker_codes
        super().__init__(f"Intent is not deliverable: {', '.join(blocker_codes)}")


class IntentDecisionHandoffV2(FrozenModel):
    """What Architecture/Planning receives for ONE scope, once delivery is permitted.

    Ids and traceability only. The embedded package is the contract; everything else is
    the envelope around it.
    """

    handoff_version: HandoffV2Version = HANDOFF_V2_VERSION
    project_id: str
    scope: str
    intent_version: int
    semantic_state_revision: int

    contract: CanonicalIntentPackage
    canonical_intent_object_ids: tuple[str, ...] = ()
    proposed_intent_object_ids: tuple[str, ...] = ()

    intent_basis: tuple[IntentBasisRef, ...] = ()

    loci: tuple[SemanticLocus, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    authority_record_ids: tuple[str, ...] = ()
    superseded_judgment_ids: tuple[str, ...] = ()

    blocking_stale_object_ids: tuple[str, ...] = ()
    reconciled_stale_object_ids: tuple[str, ...] = ()
    pending_material_judgment_ids: tuple[str, ...] = ()
    incomplete_synthesis_proposal_ids: tuple[str, ...] = ()

    readiness: IntentDeliveryReadiness


def _is_current(obj: SemanticBase) -> bool:
    return obj.lifecycle is LifecycleStatus.ACTIVE and obj.authority not in (
        Authority.REJECTED,
        Authority.SUPERSEDED,
    )


def _applies(obj: SemanticBase, scope: str) -> bool:
    return scope_applies(tuple(obj.scope), scope)


def _intent_objects(state: IntentState, scope: str, authority: Authority) -> tuple[str, ...]:
    """Current in-scope intent-bearing objects at one authority, by id.

    Reuses ``INTENT_BEARING_SEMANTIC_KINDS`` rather than restating the list: a second
    copy would drift, and the two would disagree about what counts as intent.
    """
    return tuple(
        sorted(
            object_id
            for object_id, obj in state.objects.items()
            if obj.kind in INTENT_BEARING_SEMANTIC_KINDS
            and _is_current(obj)
            and _applies(obj, scope)
            and obj.authority is authority
        )
    )


def _basis_ref(state: IntentState, view: CurrentSemanticView, object_id: str) -> IntentBasisRef:
    """One object's claim basis and the loci those exact claims sit at.

    Only ``DERIVED_FROM`` targets that are genuinely v2 claims count. A legacy object may
    carry the same relation name pointing at something else entirely, and treating that
    as a claim id would invent a basis that does not exist.

    There is deliberately no same-locus expansion: the loci reported are those of the
    claims this object actually cites, not every claim that happens to share an address.
    Widening it would attribute evidence the object was never derived from.
    """
    obj = state.objects[object_id]
    claim_ids = sorted(
        {
            relation.target_id
            for relation in obj.relations
            if relation.relation_type is RelationType.DERIVED_FROM
            and relation.target_id in state.semantic.claims
        }
    )
    locus_ids = sorted(
        {
            view.representatives.get(
                state.semantic.claims[claim_id].address_id,
                state.semantic.claims[claim_id].address_id,
            )
            for claim_id in claim_ids
        }
    )
    return IntentBasisRef(
        object_id=object_id,
        basis_claim_ids=tuple(claim_ids),
        basis_locus_ids=tuple(locus_ids),
    )


def _blocker_codes(readiness: IntentDeliveryReadiness) -> tuple[str, ...]:
    semantic = readiness.semantic_readiness
    applicable = {
        "CLOSURE_NOT_MET": not semantic.closure.closed,
        "DISPUTED_LOCUS": bool(semantic.disputed_locus_ids),
        "PENDING_MATERIAL_JUDGMENT": bool(semantic.pending_material_judgment_ids),
        "UNRECONCILED_STALE_OBJECT": bool(readiness.blocking_stale_object_ids),
        "INCOMPLETE_SYNTHESIS": bool(readiness.incomplete_synthesis_proposal_ids),
    }
    # Each basis and relevance category is exposed by name, never collapsed into one code.
    basis_codes = {blocker.code for blocker in readiness.basis_blockers}
    applicable.update({code: code in basis_codes for code in BASIS_BLOCKER_CODES})
    relevance_codes = {blocker.code for blocker in readiness.relevance_blockers}
    applicable.update({code: code in relevance_codes for code in RELEVANCE_BLOCKER_CODES})
    return tuple(code for code in _BLOCKER_CODE_ORDER if applicable[code])


def build_intent_decision_handoff_v2(state: IntentState, scope: str) -> IntentDecisionHandoffV2:
    """Gate first, then build. A refused delivery yields no partial handoff.

    The package is constructed only once delivery is permitted, so nothing downstream can
    receive a contract assembled from state that was not fit to deliver. V1 traceability
    is reused verbatim rather than recomputed, which is what keeps scope attribution,
    evidence selection, authority selection, pending governance and semantic readiness
    single-sourced instead of quietly forking into a second implementation.
    """
    v1 = build_intent_decision_handoff(state, scope)
    view = derive_view(state.semantic)
    in_scope_loci = tuple(locus for locus in view.loci if locus_in_scope(locus, scope))
    readiness = build_intent_delivery_readiness(state, view, scope, in_scope_loci, v1.readiness)
    if not readiness.deliverable:
        raise IntentDeliveryNotReadyError(_blocker_codes(readiness))

    canonical = _intent_objects(state, scope, Authority.CANONICAL)
    proposed = _intent_objects(state, scope, Authority.PROPOSED)
    return IntentDecisionHandoffV2(
        project_id=state.project_id,
        scope=scope,
        intent_version=state.revision,
        semantic_state_revision=state.revision,
        contract=build_intent_package(state, scope),
        canonical_intent_object_ids=canonical,
        proposed_intent_object_ids=proposed,
        intent_basis=tuple(
            _basis_ref(state, view, object_id) for object_id in sorted({*canonical, *proposed})
        ),
        loci=v1.loci,
        claim_ids=v1.claim_ids,
        evidence_ids=v1.evidence_ids,
        authority_record_ids=v1.authority_record_ids,
        superseded_judgment_ids=v1.superseded_judgment_ids,
        blocking_stale_object_ids=readiness.blocking_stale_object_ids,
        reconciled_stale_object_ids=readiness.reconciled_stale_object_ids,
        pending_material_judgment_ids=v1.pending_material_judgment_ids,
        incomplete_synthesis_proposal_ids=readiness.incomplete_synthesis_proposal_ids,
        readiness=readiness,
    )
