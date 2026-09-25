"""A real governed world for the IE2.2b basis tests.

Claims here arrive the only way a v2 ``SemanticClaim`` can: evidence is ingested, a human
creates an address, a human asserts the claim, and admission applies it. Nothing is placed
into ``state.semantic`` by hand, because the law under test reads the asserting judgment's
liveness and the claim's authority -- a hand-built claim would satisfy the check without
proving the governed path produces what the check expects.

Authority is recorded **before** any claim is asserted (R47): a ``CANONICAL`` claim needs
covering human authority at the moment it is asserted, not afterwards.
"""

from __future__ import annotations

from itertools import count

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import EventEnvelope, SemanticObjectPayload
from foundry.domain.events import EventType as _EventType
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic import SemanticObject
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    SemanticJudgment,
    SupersedeProposal,
)
from tests.unit._ie21_fixtures import ALICE, AT, HUMAN, PROJECT, SCOPE, authority_record

_IDS = count(1)

EVIDENCE_ID = "EV-policy"


def _judgment(judgment_id: str, proposal: JudgmentProposal) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(EVIDENCE_ID,),
        rationale="stated by the product owner",
        reasoner=HUMAN,
        invocation_id=f"INV-{judgment_id}-{next(_IDS)}",
        proposed_at=AT,
    )


class World:
    """One governed project: authority first, then evidence and an address."""

    def __init__(self) -> None:
        self.store = InMemoryEventStore()
        self.governor = SemanticGovernor(
            store=self.store,
            project_id=PROJECT,
            policy=AdmissionPolicy(),
            clock=lambda: AT,
            id_factory=lambda prefix: f"{prefix}-{next(_IDS):04d}",
        )
        # Project-wide: covers claim assertion, supersession and canonical admission alike.
        self.governor.record_authority(
            authority_record("AUTH-project", scope=(), subject_id="payments intent")
        )
        self.governor.ingest(
            evidence_item(
                evidence_id=EVIDENCE_ID,
                project_id=PROJECT,
                source_kind=SourceKind.HUMAN,
                source_ref=ALICE,
                content="Refunds must complete within thirty days.",
                observed_at=AT,
                scope=(SCOPE,),
            )
        )
        decision = self.governor.submit(
            _judgment(
                "J-address",
                CreateAddressProposal(
                    candidate=SemanticCandidate(
                        candidate_id="CAND-refund",
                        subject="Refund window",
                        facet="How long may a refund take?",
                        scope=(SCOPE,),
                        evidence_ids=(EVIDENCE_ID,),
                    )
                ),
            ),
            human_actor_id=ALICE,
        )
        assert decision.route is AdmissionRoute.APPLY, decision
        self.address_id = address_id_for(PROJECT, "J-address")

    def claim(self, judgment_id: str, *, authority: Authority, text: str = "thirty days") -> str:
        """A human asserts a claim with exactly the authority requested."""
        decision = self.governor.submit(
            _judgment(
                judgment_id,
                AssertClaimProposal(
                    address_id=self.address_id,
                    predicate="refund_window",
                    value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
                    evidence_ids=(EVIDENCE_ID,),
                    authority=authority,
                ),
            ),
            human_actor_id=ALICE,
        )
        assert decision.route is AdmissionRoute.APPLY, decision
        return claim_id_for(PROJECT, judgment_id)

    def supersede(self, judgment_id: str, target_judgment_id: str) -> None:
        """Retire a claim by superseding the judgment that asserted it."""
        decision = self.governor.submit(
            _judgment(
                judgment_id,
                SupersedeProposal(target_judgment_id=target_judgment_id, reason="corrected"),
            ),
            human_actor_id=ALICE,
        )
        assert decision.route is AdmissionRoute.APPLY, decision

    def legacy(self, *objects: SemanticObject) -> None:
        """Record objects the way history holds them: through no IE2 validation at all."""
        from foundry.domain.events import SPECIALIZED_SEMANTIC_KIND_BY_EVENT

        specialized = {kind: ev for ev, kind in SPECIALIZED_SEMANTIC_KIND_BY_EVENT.items()}
        for obj in objects:
            self.store.append(
                EventEnvelope(
                    event_id=f"EVT-legacy-{obj.id}-{next(_IDS)}",
                    project_id=PROJECT,
                    event_type=specialized.get(obj.kind, _EventType.SEMANTIC_OBJECT_RECORDED),
                    occurred_at=AT,
                    payload=SemanticObjectPayload(object=obj),
                ),
                expected_sequence=self.store.current_sequence(PROJECT),
            )

    def admit_canonical(self, obj: SemanticObject) -> None:
        """A human with covering authority canonicalizes through the IE2 seam."""
        self.governor.record_intent_object(obj, author=HUMAN, human_actor_id=ALICE)

    def event_count(self) -> int:
        return len(self.store.load(PROJECT))
