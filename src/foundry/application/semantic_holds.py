"""Record runtime holds and close them when their cause is gone (``ie2-runtime-holds-v1``).

``hold_gap`` builds the one durable gap for one held unit of one Call-2 response, scoped to the
smallest safe area it can name: the concerns (addresses) its judgments touch, plus the current
claims a conflict names. Only when nothing can be localised is it project-wide (``()``).

``close_resolved_holds`` appends ``GAP_RESOLVED`` for every open hold the domain law
(``domain.hold_resolution``) says is closed by what was just delivered or changed. Replay reads
those events; it never recomputes a resolution.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.common import Materiality, RiskLevel
from foundry.domain.hold_resolution import closed_by_change, closed_by_delivery
from foundry.domain.semantic_completeness import CompletenessRequest
from foundry.domain.semantic_holds import (
    HOLD_PROTOCOL,
    HoldBasis,
    HoldCause,
    SemanticHoldGap,
    hold_kind,
    hold_resolution_key,
    sentence_sha256,
)
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.state import IntentState

__all__ = ["close_resolved_holds", "hold_basis", "hold_gap", "judgment_addresses"]


def judgment_addresses(state: IntentState, judgment: SemanticJudgment) -> tuple[str, ...]:
    """The concern (address) a claim judgment is about, read from its proposal or its target."""
    semantic = state.semantic
    p = judgment.proposal
    if isinstance(p, AssertClaimProposal):
        return (p.address_id,)
    if isinstance(p, SupportsClaimProposal) and p.claim_id in semantic.claims:
        return (semantic.claims[p.claim_id].address_id,)
    if isinstance(p, SupersedeProposal):
        return tuple(
            c.address_id
            for c in semantic.claims.values()
            if c.created_by_judgment_id == p.target_judgment_id
        )
    return ()


def hold_basis(
    state: IntentState,
    check: CompletenessRequest,
    judgments: Sequence[SemanticJudgment],
    disposed_by: Mapping[str, str],
    proposition_ids: Collection[str],
) -> tuple[HoldBasis, ...]:
    """Every (address, source-sentence sha256) pair the given propositions carry."""
    sentences = {p.proposition_id: p.source_sentences for p in check.propositions}
    pairs: set[tuple[str, str]] = set()
    for j in judgments:
        pid = disposed_by.get(j.judgment_id)
        if pid is None or pid not in proposition_ids:
            continue
        for address in judgment_addresses(state, j):
            pairs |= {(address, sentence_sha256(s)) for s in sentences.get(pid, ())}
    return tuple(HoldBasis(address_id=a, sentence_sha256=s) for a, s in sorted(pairs))


def hold_gap(
    *,
    project_id: str,
    gap_id: str,
    cause: HoldCause,
    invocation_id: str,
    basis: tuple[HoldBasis, ...],
    proposition_ids: tuple[str, ...],
    judgment_ids: tuple[str, ...],
    conflicting_claim_ids: tuple[str, ...] = (),
    detail: str = "",
) -> SemanticHoldGap:
    kind = hold_kind(cause)
    addresses = tuple(sorted({b.address_id for b in basis}))
    return SemanticHoldGap(
        id=gap_id,
        project_id=project_id,
        kind=kind,
        description=(
            f"Call-2 work held ({cause}) for invocation {invocation_id}{detail}: "
            f"proposition(s) {', '.join(proposition_ids) or '(none)'} not applied; judgment(s) "
            f"{', '.join(judgment_ids) or '(none)'} held."
        ),
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=(*addresses, *sorted(conflicting_claim_ids)),
        blocking=True,
        hold_protocol=HOLD_PROTOCOL,
        cause=cause,
        resolution_key=hold_resolution_key(project_id, kind, basis),
        subject_invocation_id=invocation_id,
        basis=basis,
        held_proposition_ids=proposition_ids,
        held_judgment_ids=judgment_ids,
        conflicting_claim_ids=tuple(sorted(conflicting_claim_ids)),
    )


def close_resolved_holds(
    governor: SemanticGovernor,
    *,
    delivered: Collection[HoldBasis] = (),
    applied_addresses: Collection[str] = (),
    exclude: Collection[str] = (),
) -> tuple[str, ...]:
    state = governor.state()
    closed = (
        *closed_by_delivery(state, delivered, exclude),
        *closed_by_change(state, applied_addresses, exclude),
    )
    for gap_id in closed:
        governor.resolve_hold_gap(gap_id)
    return closed
