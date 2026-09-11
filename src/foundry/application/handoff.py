"""Build the scoped Intent -> Decision handoff from replayed state (plan §8.2).

Orchestration only: derive the current view, select the in-scope loci, collect the
ids they point at, and evaluate readiness through the pure domain builder. Nothing
here copies rationale, evidence content or judgment bodies — the handoff is IDs plus
the representative locus view, and its consumer resolves ids against the ledger.
"""

from __future__ import annotations

from foundry.domain.admission import authority_record_is_live
from foundry.domain.handoff import (
    IntentDecisionHandoff,
    build_semantic_readiness,
    in_scope_address_ids,
    judgment_address_ids,
    locus_in_scope,
    scoped_stale_object_ids,
)
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState


def build_intent_decision_handoff(state: IntentState, scope: str) -> IntentDecisionHandoff:
    semantic = state.semantic
    view = derive_view(semantic)
    loci = tuple(locus for locus in view.loci if locus_in_scope(locus, scope))
    addresses = in_scope_address_ids(loci)

    claim_ids = tuple(sorted({claim_id for locus in loci for claim_id in locus.claim_ids}))
    evidence_ids = tuple(
        sorted(
            {
                evidence_id
                for claim_id in claim_ids
                for evidence_id in semantic.claims[claim_id].evidence_ids
            }
        )
    )
    authority_record_ids = tuple(
        sorted(
            object_id
            for object_id, obj in state.objects.items()
            if isinstance(obj, AuthorityRecord)
            and authority_record_is_live(obj)
            and (obj.scope == () or scope in obj.scope)
        )
    )
    superseded_judgment_ids = tuple(
        sorted(
            {
                record.target_judgment_id
                for record in semantic.supersessions
                if record.target_judgment_id in semantic.judgments
                and judgment_address_ids(semantic, semantic.judgments[record.target_judgment_id])
                & addresses
            }
        )
    )
    return IntentDecisionHandoff(
        project_id=state.project_id,
        scope=scope,
        semantic_state_revision=state.revision,
        loci=loci,
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        authority_record_ids=authority_record_ids,
        superseded_judgment_ids=superseded_judgment_ids,
        stale_object_ids=scoped_stale_object_ids(semantic, view, loci),
        readiness=build_semantic_readiness(state, view, scope, loci),
    )
