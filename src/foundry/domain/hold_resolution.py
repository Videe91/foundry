"""Cause-specific, deterministic closing of runtime holds (protocol ``ie2-runtime-holds-v1``).

Only ``SemanticHoldGap`` -- a gap Foundry created because it did not apply work -- is ever
closed here; no other gap is touched. Two laws, each over structure only:

* **Delivery** (every cause but ``CONFLICT``): the hold closes when a later response delivers
  its whole ``basis`` -- the same source sentences, at the same concerns -- through propositions
  verified COMPLETE whose work was admitted (none held, none refused). Unrelated sentences,
  another concern, or a changed sentence deliver nothing, so they never close it.
* **Change** (``CONFLICT``): the hold closes when a later lawful change applies a claim at one of
  its concerns and none of its conflicting current claims is current any more (it was retired
  by an authorized correction). Restating the current side changes nothing; which side was
  right stays a decision -- a human waiver remains the way to keep the current side.

Gaps recorded by the very response being processed are never closed by it.
"""

from __future__ import annotations

from collections.abc import Collection

from foundry.domain.gaps import GapStatus
from foundry.domain.semantic_holds import HoldBasis, PropositionConflict, SemanticHoldGap
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.state import IntentState

__all__ = ["closed_by_change", "closed_by_delivery", "conflict_findings", "open_holds"]


def open_holds(state: IntentState) -> tuple[SemanticHoldGap, ...]:
    return tuple(
        g
        for g in state.gaps.values()
        if isinstance(g, SemanticHoldGap) and g.status is GapStatus.OPEN
    )


def conflict_findings(
    state: IntentState, proposition_ids: Collection[str], conflicts: Collection[PropositionConflict]
) -> tuple[str, ...]:
    """A conflict must name a proposition of the response and a current claim or a sibling."""
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    current = {c.claim_id for c in semantic.claims.values() if c.created_by_judgment_id in active}
    findings: list[str] = []
    for c in conflicts:
        if c.proposition_id not in proposition_ids:
            findings.append(f"UNKNOWN_CONFLICT_PROPOSITION: {c.proposition_id}")
        if c.with_proposition_id is not None and c.with_proposition_id not in proposition_ids:
            findings.append(f"UNKNOWN_CONFLICT_PROPOSITION: {c.with_proposition_id}")
        if c.with_claim_id is not None and c.with_claim_id not in current:
            findings.append(f"CONFLICT_TARGET_NOT_CURRENT: {c.with_claim_id}")
    return tuple(findings)


def closed_by_delivery(
    state: IntentState, delivered: Collection[HoldBasis], exclude: Collection[str] = ()
) -> tuple[str, ...]:
    have = set(delivered)
    return tuple(
        g.id
        for g in open_holds(state)
        if g.cause != "CONFLICT" and g.id not in exclude and g.basis and set(g.basis) <= have
    )


def closed_by_change(
    state: IntentState, applied_addresses: Collection[str], exclude: Collection[str] = ()
) -> tuple[str, ...]:
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    current = {c.claim_id for c in semantic.claims.values() if c.created_by_judgment_id in active}
    return tuple(
        g.id
        for g in open_holds(state)
        if g.cause == "CONFLICT"
        and g.id not in exclude
        and set(g.address_ids) & set(applied_addresses)
        and not set(g.conflicting_claim_ids) & current
    )
