"""Incremental assimilation orchestrator (9P Task 8; spec §6, §26).

One evidence delta, exactly two frontier calls, nothing else:

1. **Ingest** every delta item through the governor. Evidence lineage
   (``artifact_ref`` / ``supersedes_evidence_id``) is validated by the reducer dry-run
   inside ``ingest``; it is deterministic data and carries no semantic authority.
2. **Call 1 — assimilation.** ``assemble_assimilation_request`` (delta + descriptors of
   every active in-scope address; ``BIND_TO_ADDRESS | CREATE_ADDRESS`` only), submitted
   through ``propose_and_submit`` and routed by deterministic admission.
3. **Neighbourhood.** ``neighborhood_from_decisions`` — the addresses touched by the
   applied bindings and creations of Call 1. A selection, never a meaning decision.
4. **Call 2 — claim assimilation.** ``assemble_claim_request`` (delta + neighbourhood
   addresses + their live claims + cited evidence; ``SUPPORTS_CLAIM | ASSERT_CLAIM |
   SUPERSEDE | CONFLICTS_WITH`` only), submitted the same way.
5. **Outcome.** Both decision batches, the neighbourhood, and the ids of every
   ``SUPERSEDE`` judgment the view reports as pending. Pending governance is *surfaced*
   here so the caller (the arm runner) can take the authority step; it is never resolved
   here.

What this module deliberately does not do (spec §6, plan constraints 2, 4, 7):

* no whole-state reconciliation call and no third call of any kind;
* no authority logic — there is no authenticated-actor path and ``submit`` is never
  called directly; the only judgment entry point used is ``propose_and_submit``, which
  itself refuses human fingerprints;
* no rollback and no re-attempt — an exception anywhere propagates to the caller, and a
  failure in Call 2 leaves Call 1's admissions recorded in the ledger exactly as they
  were, because every transition is already an appended event.
"""

from __future__ import annotations

from typing import Final

from foundry.application.assimilation_context import (
    assemble_assimilation_request,
    assemble_claim_request,
    neighborhood_from_decisions,
)
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

    Exceptions propagate unchanged: a refused ingest happens before any call; a
    failure in Call 2 leaves Call 1's state recorded. Nothing is retried.
    """
    for item in delta:
        governor.ingest(item)

    request_1 = assemble_assimilation_request(
        project_id=governor.project_id, delta=delta, state=governor.state(), scope=scope
    )
    decisions_1 = governor.propose_and_submit(reasoner, request_1)

    neighborhood = neighborhood_from_decisions(governor.state(), decisions_1)

    request_2 = assemble_claim_request(
        project_id=governor.project_id,
        delta=delta,
        state=governor.state(),
        neighborhood=neighborhood,
    )
    decisions_2 = governor.propose_and_submit(reasoner, request_2)

    return DeltaOutcome(
        stage_decisions=(decisions_1, decisions_2),
        neighborhood=neighborhood,
        pending_supersede_judgment_ids=_pending_supersede_judgment_ids(governor.state()),
        calls_made=CALLS_PER_DELTA,
    )
