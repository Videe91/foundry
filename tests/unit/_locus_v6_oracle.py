"""A scripted reasoner that plays ``intent-v2-locus-v6`` lawfully, or with one named fault.

Test-only. It answers from the sealed v6 answer key through the real two-call pipeline and
governors running ``AdmissionPolicy(canonical_facets=True, correction_sets=True)``, so the v6
structural evaluator, the scripted human authority and the adjudication packets are exercised
on genuine governed state. It is never a model and proves nothing about one.

Call 1 forms one address per sealed concern (a CREATE citing every document of the concern)
and binds every revised document to its concerns. Call 2 accounts for every sentence from the
sealed coverage map and disposes of every proposition by the claim laws: a correction is its
replacements' ASSERT_CLAIMs, the first carrying one SUPERSEDE per obsolete claim (TARGET_SET).
At T3 the branch is read from the request alone: agreed claims are known in the AGREE branch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import Final

from foundry.domain.common import Authority
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticCandidate,
    canonical_facet,
)
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
from foundry.domain.source_text import numbered_sentences
from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS, SEED_WORLDS
from foundry.experiments.locus_validation_v6.expectations import (
    CONCERNS,
    CORRECTIONS,
    PROPOSITIONS,
    SOURCE_COVERAGE,
    Proposition,
    concern_of_document,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

ORACLE: Final = ReasonerFingerprint(provider="oracle", model="concern-oracle", policy_version="o6")
AT: Final = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
_BY_EVIDENCE: Final = {d.evidence_id: d.key for d in DOCUMENTS.values()}
_SEED_TEXT: Final = {c.key: c.text for w in SEED_WORLDS.values() for a in w for c in a.claims}
_SUBJECT: Final = {a.key: a.subject for w in SEED_WORLDS.values() for a in w}

MERGES: Final[dict[str, tuple[str, str]]] = {
    # fault: (absorbed concern, absorbing concern): one CREATE cites both concerns' documents
    "late-clean-merge": ("CLEANING-FEE", "LATE-FEE"),
    "reservation-unlock-merge": ("UNLOCK", "RESERVATION"),
    "late-damage-merge": ("LATE", "DAMAGE"),
}
SPLITS: Final[dict[str, tuple[str, str]]] = {
    # fault: (concern, document given its own CREATE)
    "unlock-timeout-split": ("UNLOCK", "K-UNLOCK-TIMEOUT-T1"),
    "late-waiver-split": ("LATE-FEE", "K-LATE-WAIVER-T1"),
}
DROPPED: Final = "K-RES-6"
"""The proposition the ``drop-proposition`` fault never accounts for."""


def _home(document: str) -> str:
    """The T1 section a revised document descends from (the section-grain fault's address)."""
    doc = DOCUMENTS[document]
    while doc.supersedes is not None:
        doc = next(d for d in DOCUMENTS.values() if d.evidence_id == doc.supersedes)
    return doc.key


def subject_of(key: str) -> str:
    return _SUBJECT.get(key, f"subject {key}")


class _Payload:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return self._data


class Oracle:
    include_sentence_index = True
    accepts_reproposal = False

    def __init__(self, *faults: str) -> None:
        self.faults = frozenset(faults)
        self._ids = count(1)
        self.draft_payloads: list[_Payload] = []
        self.receipts: list[object] = []
        self._redirect = {a: b for f, (a, b) in MERGES.items() if f in self.faults}
        self._split = {doc: f"{c}-PART" for f, (c, doc) in SPLITS.items() if f in self.faults}

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return ORACLE

    # ---------------------------------------------------------------- helpers

    def _j(
        self, request: ReasoningRequest, proposal: JudgmentProposal, ev: str
    ) -> SemanticJudgment:
        n = next(self._ids)
        return SemanticJudgment(
            judgment_id=f"JDG-ORACLE-{n:05d}",
            project_id=request.project_id,
            proposal=proposal,
            visible_evidence_ids=(ev,),
            rationale="oracle",
            reasoner=ORACLE,
            invocation_id=f"INV-ORACLE-{n:05d}",
            proposed_at=AT,
        )

    def _concern_of(self, p: Proposition) -> str:
        key = self._redirect.get(p.concern, p.concern)
        if "section-grain" in self.faults and p.ledger == "dense":
            return _home(p.document)
        if p.document in self._split and p.relation == "SEED":
            return self._split[p.document]
        if "h-over-split" in self.faults and p.id == "H-4":
            return "H-REPEAT"
        if "late-deadline-split" in self.faults and p.id == "LATE-3":
            return "LATE-DEADLINE"
        return key

    def _address(self, request: ReasoningRequest, key: str) -> str:
        (hit,) = [a.address_id for a in request.known_addresses if a.subject == subject_of(key)]
        return hit

    def _claim(self, request: ReasoningRequest, pid: str) -> tuple[str, str] | None:
        text = _SEED_TEXT.get(pid)
        hits = [
            (c.claim_id, c.created_by_judgment_id)
            for c in request.known_claims
            if (c.value.text == text if text is not None else c.predicate == pid)
        ]
        return hits[0] if hits else None

    def _create(
        self, request: ReasoningRequest, key: str, evs: tuple[str, ...]
    ) -> SemanticJudgment:
        facet = canonical_facet(subject_of(key))
        if "non-canonical-candidate" in self.faults and key == "MEMBERSHIP":
            facet = "How it is governed"
        scope = next(tuple(e.scope) for e in request.evidence if e.evidence_id == evs[0])
        return self._j(
            request,
            CreateAddressProposal(
                candidate=SemanticCandidate(
                    candidate_id=f"CAND-{key}-{next(self._ids)}",
                    subject=subject_of(key),
                    facet=facet,
                    scope=scope,
                    evidence_ids=evs,
                )
            ),
            evs[0],
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
                    facet=canonical_facet(subject_of(key)),
                    scope=tuple(
                        next(a.scope for a in request.known_addresses if a.address_id == address)
                    ),
                    evidence_ids=(ev,),
                ),
            ),
            ev,
        )

    def _assert(self, request: ReasoningRequest, key: str, pid: str, ev: str) -> SemanticJudgment:
        return self._j(
            request,
            AssertClaimProposal(
                address_id=self._address(request, key),
                predicate=pid,
                value=ClaimValue(kind=ClaimValueKind.TEXT, text=f"statement of {pid}"),
                evidence_ids=(ev,),
                authority=Authority.INFERRED,
            ),
            ev,
        )

    @staticmethod
    def _branch(request: ReasoningRequest) -> str | None:
        documents = {_BY_EVIDENCE[e.evidence_id] for e in request.evidence}
        if not any(DOCUMENTS[d].t == 3 for d in documents):
            return None
        agreed = {"K-UNL-9", "K-CLEAN-1C"}
        return "AGREE" if any(c.predicate in agreed for c in request.known_claims) else "DECLINE"

    def _props(self, document: str, branch: str | None) -> list[Proposition]:
        return [p for p in PROPOSITIONS if p.document == document and p.branch == branch]

    # ---------------------------------------------------------------- protocol

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            self.draft_payloads.append(_Payload({"drafts": []}))
            return self._call_1(request)
        judgments, payload = self._call_2(request)
        self.draft_payloads.append(_Payload(payload))
        return judgments

    def _call_1(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        out: list[SemanticJudgment] = []
        by_concern: dict[str, list[str]] = {}
        branch = self._branch(request)
        for item in request.evidence:
            doc, ev = _BY_EVIDENCE[item.evidence_id], item.evidence_id
            forming = concern_of_document(doc)
            if forming is not None and DOCUMENTS[doc].t == 1:
                key = self._split.get(doc, self._redirect.get(forming, forming))
                if "section-grain" in self.faults and doc.startswith("K-"):
                    key = doc
                by_concern.setdefault(key, []).append(ev)
                continue
            props = self._props(doc, branch)
            for key in sorted({self._concern_of(p) for p in props if p.relation != "NEW_CONCERN"}):
                if key in ("H-REPEAT", "LATE-DEADLINE"):
                    out.append(self._create(request, key, (ev,)))
                    continue
                out.append(self._bind(request, key, ev))
            if any(p.relation == "NEW_CONCERN" for p in props):
                out.append(self._create(request, "POD", (ev,)))
        for key, evs in by_concern.items():
            out.append(self._create(request, key, tuple(evs)))
        return tuple(out)

    def _call_2(
        self, request: ReasoningRequest
    ) -> tuple[tuple[SemanticJudgment, ...], dict[str, object]]:
        branch = self._branch(request)
        content = {e.evidence_id: e.content for e in request.evidence}
        out: list[SemanticJudgment] = []
        propositions: list[dict[str, object]] = []
        silent: list[dict[str, object]] = []
        drafts: list[dict[str, object]] = []
        conflict_done = False
        for ev in request.accountable_evidence_ids:
            doc = _BY_EVIDENCE[ev]
            ids = {s: sid for sid, s in numbered_sentences(ev, content[ev])}
            mine = {p.id for p in self._props(doc, branch)}
            carried: dict[str, list[str]] = {}
            for account in SOURCE_COVERAGE[doc]:
                pids = [p for p in account.propositions if p in mine]
                if "drop-proposition" in self.faults:
                    pids = [p for p in pids if p != DROPPED]
                if pids:
                    for pid in pids:
                        carried.setdefault(pid, []).append(ids[account.sentence])
                elif not account.propositions:
                    silent.append({"sentence_id": ids[account.sentence], "reason": "example"})
            for pid, sentence_ids in carried.items():
                propositions.append(
                    {"proposition_id": pid, "sentence_ids": sentence_ids, "statement": pid}
                )
            for p in self._props(doc, branch):
                if p.id not in carried:
                    continue
                out.extend(self._dispose(request, p, ev, drafts))
            if doc in ("HANDBOOK-T2", "FAQ-T2") and not conflict_done:
                a, b = self._claim(request, "SESSION-15"), self._claim(request, "SESSION-30")
                assert a is not None and b is not None
                out.append(self._j(request, ConflictsWithProposal(claim_a=a[0], claim_b=b[0]), ev))
                conflict_done = True
        return tuple(out), {"propositions": propositions, "non_operative": silent, "drafts": drafts}

    def _dispose(
        self, request: ReasoningRequest, p: Proposition, ev: str, drafts: list[dict[str, object]]
    ) -> list[SemanticJudgment]:
        if p.relation in ("SEED", "EXTENDS", "NEW_CONCERN"):
            drafts.append({"kind": "ASSERT_CLAIM", "proposition_id": p.id, "evidence_ids": [ev]})
            return [self._assert(request, self._concern_of(p), p.id, ev)]
        if p.relation == "RESTATES":
            hit = self._claim(request, p.of[0])
            assert hit is not None, p.id
            drafts.append({"kind": "SUPPORTS_CLAIM", "proposition_id": p.id, "evidence_ids": [ev]})
            return [
                self._j(request, SupportsClaimProposal(claim_id=hit[0], evidence_ids=(ev,)), ev)
            ]
        out = [self._assert(request, self._concern_of(p), p.id, ev)]
        drafts.append({"kind": "ASSERT_CLAIM", "proposition_id": p.id, "evidence_ids": [ev]})
        group = next(g for g in CORRECTIONS if p.id in g.replacements)
        if p.id != group.replacements[0]:
            return out
        obsolete = group.obsolete
        if "one-target-only" in self.faults and group.cardinality == "N:M":
            obsolete = obsolete[:1]
        for old in obsolete:
            hit = self._claim(request, old)
            assert hit is not None, (p.id, old)
            out.append(
                self._j(request, SupersedeProposal(target_judgment_id=hit[1], reason="x"), ev)
            )
            drafts.append(
                {"kind": "SUPERSEDE", "proposition_id": p.id, "target_judgment_id": hit[1]}
            )
        return out


CONCERN_KEYS: Final = tuple(c.key for c in CONCERNS)
