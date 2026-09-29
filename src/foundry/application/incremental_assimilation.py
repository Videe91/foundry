"""Incremental assimilation orchestrator (9P Task 8 -> 9P2 Task T4; spec §6, §11, §12).

One evidence delta, exactly two frontier calls, nothing else:

1. **Ingest** every delta item through the governor. Evidence lineage
   (``artifact_ref`` / ``supersedes_evidence_id``) is validated by the reducer dry-run
   inside ``ingest``; it is deterministic data and carries no semantic authority.
2. **Call 1 — assimilation.** ``assemble_assimilation_request`` (delta + descriptors and
   live claim profiles of every active in-scope address + compiled comparison context;
   ``BIND_TO_ADDRESS | CREATE_ADDRESS`` only), submitted through ``propose_and_submit``
   and routed by deterministic admission.
3. **Neighbourhoods.** ``neighborhood_from_decisions`` — the addresses touched by the
   applied bindings and creations of Call 1 (``neighborhood``, unchanged 9P meaning).
   The *claim neighbourhood* is its union with the addresses Call 1's comparison context
   structurally touched (``contrastive_address_ids``), sorted. Both are selections over
   explicit durable edges and admissions, never a meaning decision; a deliberate Call-1
   ``CREATE_ADDRESS`` is not repaired into a bind, the old address is merely kept
   visible to Call 2.
4. **Call 2 — claim assimilation.** ``assemble_claim_request`` (the SAME delta as the
   ONLY evidence + claim-neighbourhood addresses + their live claims + call-specific
   comparison context; ``SUPPORTS_CLAIM | ASSERT_CLAIM | SUPERSEDE | CONFLICTS_WITH``
   only; ``accountable_evidence_ids`` = the delta items Call 1's applied CREATE/BIND
   judgments cite, design §7.1.3), submitted the same way. Current citable evidence
   remains delta-only; structurally selected predecessor material appears only in
   non-citable comparison context.
5. **Outcome.** Both decision batches, both neighbourhoods, and the ids of every
   ``SUPERSEDE`` judgment the view reports as pending. Pending governance is *surfaced*
   here so the caller (the arm runner) can take the authority step; it is never resolved
   here.

What this module deliberately does not do (spec §6, plan constraints 2, 4, 6, 7):

* no whole-state reconciliation call and no third call of any kind;
* no authority logic — there is no authenticated-actor path and ``submit`` is never
  called directly; the only judgment entry point used is ``propose_and_submit``, which
  itself refuses human fingerprints;
* no rollback, no re-attempt and no fallback — an exception anywhere (including a
  ``ContextUnsupported`` refusal raised while assembling either request, which happens
  before that request reaches the reasoner) propagates to the caller, and a failure in
  Call 2 leaves Call 1's admissions recorded in the ledger exactly as they were, because
  every transition is already an appended event.
"""

from __future__ import annotations

from typing import Final

from foundry.application.assimilation_context import (
    accountable_evidence_from_decisions,
    assemble_assimilation_request,
    assemble_claim_request,
    neighborhood_from_decisions,
)
from foundry.application.contrastive_context import contrastive_address_ids
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision
from foundry.domain.common import FrozenModel
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import SemanticReasoner

CALLS_PER_DELTA: Final[int] = 2
"""Bind-first, two frontier calls per delta (spec §6). Never more, never fewer."""


class DeltaOutcome(FrozenModel):
    """What one delta did to the ledger, as recorded admissions; never a claim of truth."""

    stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]
    """Call 1 decisions, then Call 2 decisions, each in submission order."""

    neighborhood: tuple[str, ...]
    """Addresses touched by Call 1's applied bindings and creations (sorted)."""

    claim_neighborhood: tuple[str, ...]
    """``neighborhood`` ∪ addresses structurally touched by Call 1's comparison context
    (sorted); the addresses Call 2 was shown."""

    pending_supersede_judgment_ids: tuple[str, ...]
    """``view.pending_judgment_ids`` restricted to ``SUPERSEDE`` — surfaced, not resolved."""

    calls_made: int
    """Always ``CALLS_PER_DELTA`` on success."""


def _pending_supersede_judgment_ids(state: IntentState) -> tuple[str, ...]:
    semantic = state.semantic
    return tuple(
        judgment_id
        for judgment_id in derive_view(semantic).pending_judgment_ids
        if semantic.judgments[judgment_id].kind is JudgmentKind.SUPERSEDE
    )


def assimilate_delta(
    *,
    governor: SemanticGovernor,
    reasoner: SemanticReasoner,
    delta: tuple[EvidenceItem, ...],
    scope: str,
) -> DeltaOutcome:
    """Ingest ``delta``, run Call 1 then Call 2, return the recorded outcome.

    Exceptions propagate unchanged: a refused ingest or a context refusal happens
    before the corresponding call; a failure in Call 2 leaves Call 1's state recorded.
    Nothing is retried.
    """
    for item in delta:
        governor.ingest(item)

    request_1 = assemble_assimilation_request(
        project_id=governor.project_id, delta=delta, state=governor.state(), scope=scope
    )
    decisions_1 = governor.propose_and_submit(reasoner, request_1)

    decision_neighborhood = neighborhood_from_decisions(governor.state(), decisions_1)
    contrastive = contrastive_address_ids(request_1.comparison_context)
    claim_neighborhood = tuple(sorted(set(decision_neighborhood) | set(contrastive)))

    request_2 = assemble_claim_request(
        project_id=governor.project_id,
        delta=delta,
        state=governor.state(),
        neighborhood=claim_neighborhood,
        accountable_evidence_ids=accountable_evidence_from_decisions(governor.state(), decisions_1),
    )
    decisions_2 = governor.propose_and_submit(reasoner, request_2)

    return DeltaOutcome(
        stage_decisions=(decisions_1, decisions_2),
        neighborhood=decision_neighborhood,
        claim_neighborhood=claim_neighborhood,
        pending_supersede_judgment_ids=_pending_supersede_judgment_ids(governor.state()),
        calls_made=CALLS_PER_DELTA,
    )
