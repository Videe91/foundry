"""Scripted Call-1/Call-2 reasoner and scripted completeness verifier (test-only, no provider).

The reasoner answers from a script keyed by the delta's documents: Call 1 creates or binds one
address per concern; Call 2 lists propositions (with sentence ids from the real sentence index)
and one or more drafts per proposition. It exposes ``propose_accounted`` exactly as an
accounting adapter does. The verifier returns a scripted report and records what it was shown.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from typing import Any

from foundry.domain.common import Authority
from foundry.domain.proposition_accounting import AccountedProposition
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    CompletenessReport,
    CompletenessRequest,
    PropositionVerdict,
    VerifierIdentity,
)
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticCandidate,
    canonical_facet,
)
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.source_text import numbered_sentences
from foundry.ports.semantic_completeness import CompletenessVerification
from foundry.ports.semantic_reasoner import AccountedProposal, ReasoningRequest

AT = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
WRITER = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v6")
VERIFIER = VerifierIdentity(
    provider="openai", model="gpt-6-astra", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION
)

# One proposition: (id, [sentence numbers], statement, [drafts]); a draft is
# ("ASSERT", predicate, value) | ("SUPPORT", predicate-of-supported-claim)
# | ("SUPERSEDE", predicate-of-retired-claim).
Draft = tuple[str, ...]
Prop = tuple[str, tuple[int, ...], str, tuple[Draft, ...]]


class ScriptedAccountingReasoner:
    include_sentence_index = True
    accepts_reproposal = False

    def __init__(self, subject: str, call_2: list[tuple[Prop, ...]]) -> None:
        self.subject = subject
        self.call_2 = list(call_2)
        self._ids = count(1)
        self.calls = 0

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return WRITER

    def _j(
        self, request: ReasoningRequest, proposal: JudgmentProposal, ev: str
    ) -> SemanticJudgment:
        n = next(self._ids)
        return SemanticJudgment(
            judgment_id=f"JDG-S-{n:04d}",
            project_id=request.project_id,
            proposal=proposal,
            visible_evidence_ids=tuple(e.evidence_id for e in request.evidence),
            rationale="scripted",
            reasoner=WRITER,
            invocation_id=f"INV-S-{self.calls}",
            proposed_at=AT,
        )

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        return self.propose_accounted(request).judgments

    def propose_accounted(self, request: ReasoningRequest) -> AccountedProposal:
        self.calls += 1
        (item,) = request.evidence
        ev = item.evidence_id
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            known = [a for a in request.known_addresses if a.subject == self.subject]
            candidate = SemanticCandidate(
                candidate_id=f"CAND-{next(self._ids)}",
                subject=self.subject,
                facet=canonical_facet(self.subject),
                scope=tuple(item.scope),
                evidence_ids=(ev,),
            )
            proposal: JudgmentProposal = (
                BindToAddressProposal(candidate=candidate, address_id=known[0].address_id)
                if known
                else CreateAddressProposal(candidate=candidate)
            )
            return AccountedProposal(judgments=(self._j(request, proposal, ev),))
        (address,) = [a.address_id for a in request.known_addresses if a.subject == self.subject]
        sids = [sid for sid, _ in numbered_sentences(ev, item.content)]
        by_predicate = {c.predicate: c for c in request.known_claims}
        judgments: list[SemanticJudgment] = []
        disposed: dict[str, str] = {}
        props: list[AccountedProposition] = []
        for pid, numbers, statement, drafts in self.call_2.pop(0):
            props.append(
                AccountedProposition(
                    proposition_id=pid,
                    sentence_ids=tuple(sids[n - 1] for n in numbers),
                    statement=statement,
                )
            )
            for draft in drafts:
                if draft[0] == "ASSERT":
                    p: JudgmentProposal = AssertClaimProposal(
                        address_id=address,
                        predicate=draft[1],
                        value=ClaimValue(kind=ClaimValueKind.TEXT, text=draft[2]),
                        evidence_ids=(ev,),
                        authority=Authority.INFERRED,
                    )
                elif draft[0] == "SUPPORT":
                    p = SupportsClaimProposal(
                        claim_id=by_predicate[draft[1]].claim_id, evidence_ids=(ev,)
                    )
                else:
                    p = SupersedeProposal(
                        target_judgment_id=by_predicate[draft[1]].created_by_judgment_id,
                        reason="corrected",
                    )
                j = self._j(request, p, ev)
                judgments.append(j)
                disposed[j.judgment_id] = pid
        return AccountedProposal(
            judgments=tuple(judgments), propositions=tuple(props), disposed_by=disposed
        )


class ScriptedVerifier:
    """Answers each request with ``answer(request)``; records every request it was shown."""

    def __init__(
        self,
        answer: Callable[[CompletenessRequest], CompletenessReport | None],
        identity: VerifierIdentity = VERIFIER,
    ) -> None:
        self._answer = answer
        self.identity = identity
        self.requests: list[CompletenessRequest] = []

    def verify(self, request: CompletenessRequest) -> CompletenessVerification:
        self.requests.append(request)
        return CompletenessVerification(
            report=self._answer(request),
            verifier=self.identity,
            invocation_id=f"VINV-{len(self.requests)}",
            input_tokens=100,
            output_tokens=20,
            wall_clock_ms=5,
        )


def all_complete(request: CompletenessRequest) -> CompletenessReport:
    return CompletenessReport(
        verdicts=tuple(
            PropositionVerdict(
                proposition_id=p.proposition_id,
                verdict="COMPLETE",
                claim_refs=tuple(c.ref for c in p.claims),
            )
            for p in request.propositions
        )
    )


def missing_in(pid: str, region: str) -> Callable[[CompletenessRequest], CompletenessReport]:
    def answer(request: CompletenessRequest) -> CompletenessReport:
        return CompletenessReport(
            verdicts=tuple(
                PropositionVerdict(
                    proposition_id=p.proposition_id,
                    verdict="INCOMPLETE" if p.proposition_id == pid else "COMPLETE",
                    claim_refs=tuple(c.ref for c in p.claims),
                    missing=(region,) if p.proposition_id == pid else (),
                )
                for p in request.propositions
            )
        )

    return answer


def event_types(store: Any, project_id: str) -> list[str]:
    return [e.event.event_type.value for e in store.load(project_id)]
