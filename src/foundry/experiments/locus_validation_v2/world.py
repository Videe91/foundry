"""Fresh ledgers and the deterministic seed worlds (design §4.3, §4.4).

Every ledger is a fresh project, event store and governor. The ``conflict`` and ``large``
worlds are written by a human seed author through the real governor, as the certification
exams write theirs: ``CREATE_ADDRESS`` and ``ASSERT_CLAIM`` judgments, admitted by the
unchanged admission policy (human, low-risk kinds: applied). Nothing is written to state
any other way, so replay covers the seed exactly as it covers the model's judgments.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from itertools import count
from typing import Final

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.experiments.locus_validation_v2.corpus import (
    AUTHOR,
    DOCUMENTS,
    SEED_WORLDS,
    evidence,
    seed_delta,
)
from foundry.experiments.locus_validation_v2.protocol import (
    OBSERVED_AT,
    PROJECT_IDS,
    SCOPES,
    LedgerId,
)

__all__ = ["SEED_AUTHOR", "SeededWorld", "fresh_governor", "seed_world"]

SEED_AUTHOR: Final = ReasonerFingerprint(
    provider="human", model=AUTHOR, policy_version="locus-validation-v2-seed-author"
)


class SeededWorld:
    """Which runtime ids the seed author's addresses and claims received."""

    def __init__(self) -> None:
        self.address_ids: dict[str, str] = {}
        self.claim_ids: dict[str, str] = {}


def fresh_governor(
    ledger: LedgerId,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> tuple[InMemoryEventStore, SemanticGovernor]:
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT_IDS[ledger],
        policy=AdmissionPolicy(),
        clock=clock,
        id_factory=id_factory,
    )
    return store, governor


def _judgment(ledger: LedgerId, jid: str, proposal: JudgmentProposal, ev: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=jid,
        project_id=PROJECT_IDS[ledger],
        proposal=proposal,
        visible_evidence_ids=(ev,),
        rationale="written by the validation seed author",
        reasoner=SEED_AUTHOR,
        invocation_id=f"INV-{jid}",
        proposed_at=OBSERVED_AT,
    )


def seed_world(ledger: LedgerId, governor: SemanticGovernor) -> SeededWorld:
    """Ingest the seed documents and write the ledger's seed addresses and claims."""
    world = SeededWorld()
    for item in seed_delta(ledger):
        governor.ingest(item)
    ids = count(1)
    for address in SEED_WORLDS[ledger]:
        claim_documents = {c.document for c in address.claims}
        first = DOCUMENTS[sorted(claim_documents)[0]]
        jid = f"JDG-SEED-{ledger.upper()}-{next(ids):03d}"
        decision = governor.submit(
            _judgment(
                ledger,
                jid,
                CreateAddressProposal(
                    candidate=SemanticCandidate(
                        candidate_id=f"CAND-{jid}",
                        subject=address.subject,
                        facet=address.facet,
                        scope=(SCOPES[ledger],),
                        evidence_ids=tuple(
                            sorted(DOCUMENTS[d].evidence_id for d in claim_documents)
                        ),
                    )
                ),
                first.evidence_id,
            ),
            human_actor_id=AUTHOR,
        )
        _require_applied(decision.route, jid)
        address_id = _address_created_by(governor, jid)
        world.address_ids[address.key] = address_id
        for claim in address.claims:
            cid = f"JDG-SEED-{ledger.upper()}-{next(ids):03d}"
            source = DOCUMENTS[claim.document]
            decision = governor.submit(
                _judgment(
                    ledger,
                    cid,
                    AssertClaimProposal(
                        address_id=address_id,
                        predicate=claim.predicate,
                        value=ClaimValue(kind=ClaimValueKind.TEXT, text=claim.text),
                        evidence_ids=(evidence(source).evidence_id,),
                        authority=Authority.INFERRED,
                    ),
                    source.evidence_id,
                ),
                human_actor_id=AUTHOR,
            )
            _require_applied(decision.route, cid)
            world.claim_ids[claim.key] = _claim_created_by(governor, cid)
    return world


def _require_applied(route: AdmissionRoute, jid: str) -> None:
    if route is not AdmissionRoute.APPLY:
        raise RuntimeError(f"SEED_NOT_APPLIED: seed judgment {jid} routed {route.value}")


def _address_created_by(governor: SemanticGovernor, jid: str) -> str:
    (address_id,) = [
        a
        for a, address in governor.state().semantic.addresses.items()
        if address.created_by_judgment_id == jid
    ]
    return address_id


def _claim_created_by(governor: SemanticGovernor, jid: str) -> str:
    (claim_id,) = [
        c
        for c, claim in governor.state().semantic.claims.items()
        if claim.created_by_judgment_id == jid
    ]
    return claim_id
