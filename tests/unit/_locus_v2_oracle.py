"""A scripted reasoner that plays the locus policy perfectly, or with one injected fault.

Test-only. It answers from the sealed proposition inventory, through the real two-call
pipeline, so the structural evaluator is exercised on genuine governed state. Every fault
is a named deviation the evaluator must catch; ``()`` is the lawful answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import Final

from foundry.domain.common import Authority
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.experiments.locus_validation_v2.corpus import DOCUMENTS, SEED_WORLDS
from foundry.experiments.locus_validation_v2.expectations import PROPOSITIONS
from foundry.ports.semantic_reasoner import ReasoningRequest

ORACLE: Final = ReasonerFingerprint(provider="oracle", model="locus-oracle", policy_version="o1")
AT: Final = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
_BY_EVIDENCE: Final = {d.evidence_id: d.key for d in DOCUMENTS.values()}
_SEED_TEXT: Final = {
    c.key: c.text for world in SEED_WORLDS.values() for a in world for c in a.claims
}
_SUBJECT: Final = {a.key: a.subject for world in SEED_WORLDS.values() for a in world}


def subject_of(address_key: str) -> str:
    return _SUBJECT.get(address_key, f"subject {address_key}")


class Oracle:
    def __init__(self, *faults: str) -> None:
        self.faults = frozenset(faults)
        self._ids = count(1)

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return ORACLE

    # ---------------------------------------------------------------- helpers

    def _j(
        self, request: ReasoningRequest, proposal: JudgmentProposal, ev: str
    ) -> SemanticJudgment:
        n = next(self._ids)
        return SemanticJudgment(
            judgment_id=f"JDG-ORACLE-{n:04d}",
            project_id=request.project_id,
            proposal=proposal,
            visible_evidence_ids=(ev,),
            rationale="oracle",
            reasoner=ORACLE,
            invocation_id=f"INV-ORACLE-{n:04d}",
            proposed_at=AT,
        )

    def _address(self, request: ReasoningRequest, key: str) -> str:
        (hit,) = [a.address_id for a in request.known_addresses if a.subject == subject_of(key)]
        return hit

    def _claim_by_predicate(self, request: ReasoningRequest, predicate: str) -> tuple[str, str]:
        (hit,) = [
            (c.claim_id, c.created_by_judgment_id)
            for c in request.known_claims
            if c.predicate == predicate
        ]
        return hit

    def _claim_for(self, request: ReasoningRequest, proposition: str) -> tuple[str, str]:
        if proposition in _SEED_TEXT:
            (hit,) = [
                (c.claim_id, c.created_by_judgment_id)
                for c in request.known_claims
                if c.value.text == _SEED_TEXT[proposition]
            ]
            return hit
        return self._claim_by_predicate(request, proposition)

    def _create(
        self, request: ReasoningRequest, key: str, ev: str, *extra: str
    ) -> SemanticJudgment:
        return self._j(
            request,
            CreateAddressProposal(
                candidate=SemanticCandidate(
                    candidate_id=f"CAND-{key}-{next(self._ids)}",
                    subject=subject_of(key),
                    facet=f"the locus-level question of {key}",
                    scope=next(tuple(e.scope) for e in request.evidence if e.evidence_id == ev),
                    evidence_ids=(ev, *extra),
                )
            ),
            ev,
        )

    def _bind(self, request: ReasoningRequest, key: str, ev: str) -> SemanticJudgment:
        address = self._address(request, key)
        return self._j(
            request,
            BindToAddressProposal(
                address_id=address,
                candidate=SemanticCandidate(
                    candidate_id=f"CAND-BIND-{key}-{next(self._ids)}",
                    subject=subject_of(key),
                    facet=f"the locus-level question of {key}",
                    scope=tuple(
                        next(a.scope for a in request.known_addresses if a.address_id == address)
                    ),
                    evidence_ids=(ev,),
                ),
            ),
            ev,
        )

    def _assert(
        self, request: ReasoningRequest, key: str, predicate: str, ev: str
    ) -> SemanticJudgment:
        return self._j(
            request,
            AssertClaimProposal(
                address_id=self._address(request, key),
                predicate=predicate,
                value=ClaimValue(kind=ClaimValueKind.TEXT, text=f"statement of {predicate}"),
                evidence_ids=(ev,),
                authority=Authority.INFERRED,
            ),
            ev,
        )

    # ---------------------------------------------------------------- protocol

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            return self._call_1(request)
        return self._call_2(request)

    def _call_1(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        out: list[SemanticJudgment] = []
        docs = [(_BY_EVIDENCE[e.evidence_id], e.evidence_id) for e in request.evidence]
        for doc, ev in docs:
            if doc.endswith("-T1"):
                key = doc.removesuffix("-T1")
                if "under-split" in self.faults and key == "LATE":
                    continue
                if "under-split" in self.faults and key == "INSURANCE":
                    late = DOCUMENTS["LATE-T1"].evidence_id
                    out.append(self._create(request, key, ev, late))
                    continue
                out.append(self._create(request, key, ev))
                continue
            targets = {
                p.address for p in PROPOSITIONS if p.document == doc and p.relation != "NEW_LOCUS"
            }
            for key in sorted(targets):
                if "h-over-split" in self.faults and doc == "H-T9":
                    out.append(self._bind(request, "H", ev))
                    out.append(self._create(request, "H-REPEAT", ev))
                    break
                if "over-split" in self.faults and doc == "LABEL-T2":
                    out.append(self._create(request, "LABEL-BARCODE", ev))
                    break
                if self.faults & {"wrong-bind", "under-split"} and doc == "LATE-NOTE-T2":
                    key = "INSURANCE"
                if "large-wrong-bind" in self.faults and doc == "REFUND-UPDATE-T2":
                    key = "STORE-CREDIT"
                if "misbind-only" in self.faults and doc == "LABEL-T2":
                    key = "PICKUP"
                out.append(self._bind(request, key, ev))
            if any(p.document == doc and p.relation == "NEW_LOCUS" for p in PROPOSITIONS):
                out.append(self._create(request, "POD", ev))
        return tuple(out)

    def _call_2(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        out: list[SemanticJudgment] = []
        conflict_emitted = False
        for item in request.evidence:
            doc, ev = _BY_EVIDENCE[item.evidence_id], item.evidence_id
            for p in (p for p in PROPOSITIONS if p.document == doc):
                if p.relation in ("SEED", "EXTENDS", "NEW_LOCUS"):
                    key = p.address
                    if "h-over-split" in self.faults and p.id == "H-4":
                        key = "H-REPEAT"
                    if "over-split" in self.faults and p.id == "LABEL-3":
                        key = "LABEL-BARCODE"
                    if "under-split" in self.faults and p.address == "LATE" and doc == "LATE-T1":
                        key = "INSURANCE"
                    if self.faults & {"wrong-bind", "under-split"} and p.id == "LATE-3":
                        key = "INSURANCE"
                    if "large-wrong-bind" in self.faults and p.id == "PARTIAL-2":
                        key = "STORE-CREDIT"
                    if "missing-extension" in self.faults and p.id == "LABEL-3":
                        continue
                    if "h-missing-extension" in self.faults and p.id == "H-4":
                        continue
                    if "missing-claim" in self.faults and p.id == "PICKUP-2":
                        continue
                    out.append(self._assert(request, key, p.id, ev))
                    if "extra-claim" in self.faults and p.id == "PICKUP-2":
                        out.append(self._assert(request, key, "PICKUP-EXTRA", ev))
                elif p.relation == "RESTATES":
                    assert p.of is not None
                    if "missing-claim" in self.faults and p.of == "PICKUP-2":
                        continue
                    claim_id, _ = self._claim_for(request, p.of)
                    if "duplicate-assert" in self.faults and p.id == "PICKUP-1R":
                        out.append(self._assert(request, p.address, "PICKUP-1-AGAIN", ev))
                        continue
                    if "missing-support" in self.faults and p.id == "PICKUP-2R":
                        continue
                    if "misplaced-support" in self.faults and p.id == "PICKUP-1R":
                        stray, _ = self._claim_by_predicate(request, "LABEL-1")
                        out.append(
                            self._j(
                                request,
                                SupportsClaimProposal(claim_id=stray, evidence_ids=(ev,)),
                                ev,
                            )
                        )
                    out.append(
                        self._j(
                            request,
                            SupportsClaimProposal(claim_id=claim_id, evidence_ids=(ev,)),
                            ev,
                        )
                    )
                elif p.relation == "CORRECTS":
                    assert p.of is not None
                    claim_id, judgment_id = self._claim_for(request, p.of)
                    out.append(self._assert(request, p.address, p.id, ev))
                    if "missing-supersede" in self.faults:
                        continue
                    if "conflict-instead" in self.faults:
                        refusal, _ = self._claim_for(request, "WEIGHT-2")
                        out.append(
                            self._j(
                                request,
                                ConflictsWithProposal(claim_a=claim_id, claim_b=refusal),
                                ev,
                            )
                        )
                        continue
                    if "wrong-supersede-target" in self.faults:
                        _, judgment_id = self._claim_for(request, "PICKUP-1")
                    out.append(
                        self._j(
                            request,
                            SupersedeProposal(target_judgment_id=judgment_id, reason="corrected"),
                            ev,
                        )
                    )
            if doc in ("HANDBOOK-T2", "FAQ-T2") and not conflict_emitted:
                a, ja = self._claim_for(request, "SESSION-15")
                b, jb = self._claim_for(request, "SESSION-30")
                if "fabricated-supersede" in self.faults:
                    out.append(
                        self._j(request, SupersedeProposal(target_judgment_id=jb, reason="x"), ev)
                    )
                if "missing-conflict" not in self.faults:
                    out.append(self._j(request, ConflictsWithProposal(claim_a=a, claim_b=b), ev))
                conflict_emitted = True
        return tuple(out)
