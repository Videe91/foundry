"""Experiment-only frozen 9P ablation arm (Arm A; spec §4; T3 brief).

Arm A reproduces the historical, pre-9P2 model-visible treatment for one delta: each
call sees only the delta as evidence, is shown either every active in-scope address
(Call 1) or exactly the Call-1 decision neighbourhood (Call 2), and never sees a live
claim in Call 1, a comparison context in either call, or any address outside the
applied Call-1 CREATE/BIND neighbourhood. This module builds its own bounded
``ReasoningRequest`` objects; it never calls ``assemble_assimilation_request`` or
``assemble_claim_request`` (those attach the 9P2 comparison context) and it never
constructs a reasoner -- Arm A's live reasoner is later the historical
``XAISemanticReasoner``, supplied by the caller.

Law of this module: selection never decides meaning, and this ablation decides
nothing that 9P2 production does not already decide structurally. It reuses
``active_in_scope_addresses``, ``live_claims_at``, ``neighborhood_from_decisions``,
``CANDIDATE_ADDRESS_THRESHOLD`` and the two judgment-kind constants from
``foundry.application.assimilation_context`` verbatim, and it mirrors
``assimilate_delta``'s ingest-then-two-calls shape from
``foundry.application.incremental_assimilation`` exactly, with the ONLY difference
being what each call is allowed to see: ``known_claims=()`` and
``comparison_context=ComparisonContext()`` at Call 1, and no contrastive widening of
the Call-2 neighbourhood -- there is no comparison context here to widen from. No
retry, no reconciliation call, no third call, no whole-state call, and no meaning
comparison of any kind anywhere in this file.
"""

from __future__ import annotations

from typing import Final

from foundry.application.assimilation_context import (
    ASSIMILATION_JUDGMENT_KINDS,
    CANDIDATE_ADDRESS_THRESHOLD,
    CLAIM_ASSIMILATION_JUDGMENT_KINDS,
    ContextUnsupported,
    active_in_scope_addresses,
    live_claims_at,
    neighborhood_from_decisions,
)
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision
from foundry.domain.common import FrozenModel
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import ComparisonContext, ReasoningRequest, SemanticReasoner

__all__ = [
    "ABLATION_CALLS_PER_DELTA",
    "AblationOutcome",
    "assemble_ablation_call1",
    "assemble_ablation_call2",
    "assimilate_ablation_delta",
]

ABLATION_CALLS_PER_DELTA: Final[int] = 2
"""Exactly two frontier calls per delta -- the same shape as frozen production."""


class AblationOutcome(FrozenModel):
    """What one delta did under Arm A, as recorded admissions; never a claim of truth."""

    stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]
    """Call 1 decisions, then Call 2 decisions, each in submission order."""

    neighborhood: tuple[str, ...]
    """Addresses touched by Call 1's applied bindings and creations (sorted)."""

    pending_supersede_judgment_ids: tuple[str, ...]
    """``view.pending_judgment_ids`` restricted to ``SUPERSEDE`` -- surfaced, not resolved."""

    calls_made: int
    """Always ``ABLATION_CALLS_PER_DELTA`` on success."""


def _pending_supersede_judgment_ids(state: IntentState) -> tuple[str, ...]:
    semantic = state.semantic
    return tuple(
        judgment_id
        for judgment_id in derive_view(semantic).pending_judgment_ids
        if semantic.judgments[judgment_id].kind is JudgmentKind.SUPERSEDE
    )


def assemble_ablation_call1(
    *,
    project_id: str,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    scope: str,
) -> ReasoningRequest:
    """Call 1: the delta, every active in-scope address, zero claims, no context.

    Raises ``ContextUnsupported`` when more than ``CANDIDATE_ADDRESS_THRESHOLD``
    addresses are active in scope -- the same 200-address refusal rule as the frozen
    production path, checked before any request is built.
    """
    addresses = active_in_scope_addresses(state, scope)
    if len(addresses) > CANDIDATE_ADDRESS_THRESHOLD:
        raise ContextUnsupported(
            f"UNSUPPORTED_ABOVE_THRESHOLD: {len(addresses)} active addresses in scope "
            f"{scope!r} exceed the candidate threshold of {CANDIDATE_ADDRESS_THRESHOLD}; "
            "the above-threshold retrieval branch is deferred to the Context Compiler"
        )
    return ReasoningRequest(
        project_id=project_id,
        evidence=delta,
        known_addresses=addresses,
        known_claims=(),
        allowed_judgment_kinds=ASSIMILATION_JUDGMENT_KINDS,
        comparison_context=ComparisonContext(),
    )


def assemble_ablation_call2(
    *,
    project_id: str,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    neighborhood: tuple[str, ...],
) -> ReasoningRequest:
    """Call 2: the delta, exactly the Call-1 decision neighbourhood, its live claims.

    ``neighborhood`` is Call 1's applied CREATE/BIND neighbourhood exactly as
    ``neighborhood_from_decisions`` reports it -- never widened, because there is no
    comparison context here to widen from. Raises ``KeyError`` for a neighbourhood
    address unknown to ``state``.
    """
    semantic = state.semantic
    address_ids = tuple(sorted(frozenset(neighborhood)))
    addresses = tuple(semantic.addresses[address_id] for address_id in address_ids)
    return ReasoningRequest(
        project_id=project_id,
        evidence=delta,
        known_addresses=addresses,
        known_claims=live_claims_at(state, address_ids),
        allowed_judgment_kinds=CLAIM_ASSIMILATION_JUDGMENT_KINDS,
        comparison_context=ComparisonContext(),
    )


def assimilate_ablation_delta(
    *,
    governor: SemanticGovernor,
    reasoner: SemanticReasoner,
    delta: tuple[EvidenceItem, ...],
    scope: str,
) -> AblationOutcome:
    """Ingest ``delta``, run Arm A's Call 1 then Call 2, return the recorded outcome.

    Exceptions propagate unchanged: a refused ingest or a context refusal happens
    before the corresponding call; a failure in Call 2 leaves Call 1's state recorded.
    Nothing is retried and there is no third call.
    """
    for item in delta:
        governor.ingest(item)

    request_1 = assemble_ablation_call1(
        project_id=governor.project_id, delta=delta, state=governor.state(), scope=scope
    )
    decisions_1 = governor.propose_and_submit(reasoner, request_1)

    neighborhood = neighborhood_from_decisions(governor.state(), decisions_1)

    request_2 = assemble_ablation_call2(
        project_id=governor.project_id,
        delta=delta,
        state=governor.state(),
        neighborhood=neighborhood,
    )
    decisions_2 = governor.propose_and_submit(reasoner, request_2)

    return AblationOutcome(
        stage_decisions=(decisions_1, decisions_2),
        neighborhood=neighborhood,
        pending_supersede_judgment_ids=_pending_supersede_judgment_ids(governor.state()),
        calls_made=ABLATION_CALLS_PER_DELTA,
    )
