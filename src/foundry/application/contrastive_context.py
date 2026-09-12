"""Structural comparison-context compiler (9P2 Task T3; spec §9, §10, §17, §18).

``compile_comparison_context`` turns the current delta plus durable state into the
request-only ``ComparisonContext`` of spec §8. It follows ONLY explicit structural
edges, in this locked order (plan §5):

1. a delta item without ``supersedes_evidence_id`` yields no transition;
2. otherwise the predecessor is fetched by exact id from ``state.semantic.evidence``
   (missing -> ``ValueError``; there is no search) and its ``artifact_ref`` must equal
   the current item's (mismatch -> ``ValueError``);
3. a claim is *touched* iff it is live, the predecessor id is in the current view's
   ``effective_evidence`` for it — immutable claim evidence ∪ ACTIVE ``SUPPORTS_CLAIM``
   evidence, exactly as ``derive_view`` computes it (spec §12) — AND its ``address_id``
   is in the caller-supplied ``profile_address_ids``. That set is the request's
   eligible semantic-address set (2026-09-12 pre-experiment amendment, Ruling A): a
   predecessor may structurally support live claims in several scopes, but a request
   assembled for one scope may only see, and later widen to, claims at addresses
   already eligible for it. Out-of-profile claim/address ids never appear in any
   transition field or edge, so ``contrastive_address_ids`` ⊆ ``profile_address_ids``;
4. touched claims are sorted by id, touched addresses are the unique sorted
   ``claim.address_id`` values, and the audit trail is one
   ``current --SUPERSEDES--> predecessor`` edge followed, per touched claim, by
   ``predecessor --EFFECTIVE_EVIDENCE_OF--> claim`` and
   ``claim --CLAIM_AT_ADDRESS--> address``;
5. the diff is ``render_unified_diff`` (T2); a transition exists even with zero
   touched claims — whether none is structurally reached or none is eligible —
   because the version lineage itself is explicit;
6. every live claim at a caller-supplied profile address contributes one
   ``address --ACTIVE_CLAIM_PROFILE--> claim`` edge, sorted by (address, claim);
7. the canonical JSON of the result may not exceed ``MAX_COMPARISON_CONTEXT_CHARS``;
   beyond that the compiler raises ``ContextUnsupported``
   (``UNSUPPORTED_COMPARISON_CONTEXT``) — never truncates, ranks, or falls back.

Law of this module: it decides what structurally connected history is *shown*, never
what it *means*. No claim or address wording (subject, facet, predicate, value,
content) is ever compared; only ids and the view's structural mappings are read.
Nothing here classifies a transition as support, correction, conflict, or new
meaning, and nothing here is persisted. Pure function of its inputs.
"""

from __future__ import annotations

import json
from typing import Final

from foundry.application.context_errors import ContextUnsupported
from foundry.application.contrastive_diff import render_unified_diff
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import (
    ComparisonContext,
    ContextInclusionEdge,
    ContextRelation,
    EvidenceTransitionContext,
)

MAX_COMPARISON_CONTEXT_CHARS: Final[int] = 131_072
"""Maximum canonical-JSON length of one ``ComparisonContext`` (spec §10, §18)."""


def comparison_context_json(context: ComparisonContext) -> str:
    """The exact canonical rendering the support bound is measured on (plan §5)."""
    return json.dumps(
        context.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def comparison_context_character_count(context: ComparisonContext) -> int:
    return len(comparison_context_json(context))


def contrastive_address_ids(context: ComparisonContext) -> tuple[str, ...]:
    """Structurally touched addresses across all transitions, sorted and deduplicated."""
    return tuple(
        sorted({address_id for t in context.transitions for address_id in t.touched_address_ids})
    )


def historical_evidence_ids(context: ComparisonContext) -> tuple[str, ...]:
    """Predecessor evidence ids shown as history, sorted and deduplicated (non-citable)."""
    return tuple(sorted({t.predecessor_evidence_id for t in context.transitions}))


def _predecessor(state: IntentState, current: EvidenceItem, predecessor_id: str) -> EvidenceItem:
    predecessor = state.semantic.evidence.get(predecessor_id)
    if predecessor is None:
        raise ValueError(
            f"evidence {current.evidence_id} supersedes unknown evidence {predecessor_id}"
        )
    if predecessor.artifact_ref != current.artifact_ref:
        raise ValueError(
            f"evidence {current.evidence_id} (artifact_ref {current.artifact_ref!r}) cannot "
            f"supersede evidence {predecessor_id} (artifact_ref "
            f"{predecessor.artifact_ref!r}): artifact_ref differs"
        )
    return predecessor


def _transition(
    state: IntentState,
    current: EvidenceItem,
    predecessor: EvidenceItem,
    effective_evidence: dict[str, tuple[str, ...]],
    eligible_address_ids: frozenset[str],
) -> EvidenceTransitionContext:
    predecessor_id = predecessor.evidence_id
    claims = state.semantic.claims
    touched_claim_ids = tuple(
        sorted(
            claim_id
            for claim_id, evidence_ids in effective_evidence.items()
            if predecessor_id in evidence_ids
            and claims[claim_id].address_id in eligible_address_ids
        )
    )
    address_of = {claim_id: claims[claim_id].address_id for claim_id in touched_claim_ids}
    edges = [
        ContextInclusionEdge(
            source_id=current.evidence_id,
            relation=ContextRelation.SUPERSEDES,
            target_id=predecessor_id,
        )
    ]
    for claim_id in touched_claim_ids:
        edges.append(
            ContextInclusionEdge(
                source_id=predecessor_id,
                relation=ContextRelation.EFFECTIVE_EVIDENCE_OF,
                target_id=claim_id,
            )
        )
        edges.append(
            ContextInclusionEdge(
                source_id=claim_id,
                relation=ContextRelation.CLAIM_AT_ADDRESS,
                target_id=address_of[claim_id],
            )
        )
    # ``artifact_ref`` is a non-empty string here: the current item carries lineage, so
    # the domain validator already required it, and the predecessor's equals it.
    if current.artifact_ref is None:  # pragma: no cover - excluded by EvidenceItem's validator
        raise ValueError(f"evidence {current.evidence_id} supersedes without artifact_ref")
    return EvidenceTransitionContext(
        current_evidence_id=current.evidence_id,
        predecessor_evidence_id=predecessor_id,
        artifact_ref=current.artifact_ref,
        historical_diff=render_unified_diff(predecessor, current),
        touched_claim_ids=touched_claim_ids,
        touched_address_ids=tuple(sorted(set(address_of.values()))),
        inclusion_edges=tuple(edges),
    )


def compile_comparison_context(
    *,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    profile_address_ids: tuple[str, ...],
) -> ComparisonContext:
    """Compile request-only structural comparison context for ``delta`` (plan §5).

    ``profile_address_ids`` is this request's eligible semantic-address set: it bounds
    both the active claim profile edges and the transition-touched claims/addresses.

    Raises ``ValueError`` for a missing predecessor or an ``artifact_ref`` mismatch and
    ``ContextUnsupported`` (``UNSUPPORTED_COMPARISON_CONTEXT``) when the canonical JSON
    exceeds ``MAX_COMPARISON_CONTEXT_CHARS``. Never truncates or falls back.
    """
    view = derive_view(state.semantic)
    effective_evidence = dict(view.effective_evidence)  # keyed by LIVE claims only
    profile = frozenset(profile_address_ids)
    transitions: list[EvidenceTransitionContext] = []
    for current in delta:
        predecessor_id = current.supersedes_evidence_id
        if predecessor_id is None:
            continue
        predecessor = _predecessor(state, current, predecessor_id)
        transitions.append(_transition(state, current, predecessor, effective_evidence, profile))

    profile_pairs = sorted(
        (state.semantic.claims[claim_id].address_id, claim_id)
        for claim_id in effective_evidence
        if state.semantic.claims[claim_id].address_id in profile
    )
    profile_edges = tuple(
        ContextInclusionEdge(
            source_id=address_id,
            relation=ContextRelation.ACTIVE_CLAIM_PROFILE,
            target_id=claim_id,
        )
        for address_id, claim_id in profile_pairs
    )

    context = ComparisonContext(
        transitions=tuple(transitions), active_claim_profile_edges=profile_edges
    )
    size = comparison_context_character_count(context)
    if size > MAX_COMPARISON_CONTEXT_CHARS:
        raise ContextUnsupported(
            "UNSUPPORTED_COMPARISON_CONTEXT: canonical comparison context has "
            f"{size} characters; maximum is {MAX_COMPARISON_CONTEXT_CHARS}"
        )
    return context
