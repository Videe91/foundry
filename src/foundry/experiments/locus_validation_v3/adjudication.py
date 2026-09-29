"""Timepoint-exact adjudication packets and the single standing (design §7.2, §8).

v2's semantic questions asked about T1 but were answered against the final state. Here every
sealed question names its ledger and timepoint, and its packet is built from exactly that
ledger's frozen ``state_after`` of exactly that delta: the addresses active then, their
claims (live or not) then, the judgments admitted by then with their routes, and the
documents the ledger had received by then. Nothing later can appear in an earlier packet.

The adjudicator receives one packet per question and nothing of the builder's reasoning.
``standing`` turns the structural verdicts and the adjudicator's answers into the one
all-or-nothing result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_identity import ClaimValue
from foundry.domain.semantic_judgment import (
    ConflictsWithProposal,
    CreateAddressProposal,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_view import active_judgment_ids
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v3.corpus import DOCUMENTS, REVISION, SEED_DOCUMENTS
from foundry.experiments.locus_validation_v3.evaluation import CaseResult
from foundry.experiments.locus_validation_v3.expectations import (
    CASES,
    CRITICAL_CASE,
    SEMANTIC_QUESTIONS,
)
from foundry.experiments.locus_validation_v3.protocol import SCOPES, LedgerId
from foundry.experiments.locus_validation_v3.runner import LedgerRun, RunRecord

__all__ = [
    "VALIDATED",
    "NOT_VALIDATED",
    "Standing",
    "adjudication_bundle",
    "packet",
    "packet_id",
    "render_value",
    "standing",
]

VALIDATED: Final = "LOCUS_POLICY_VALIDATED"
NOT_VALIDATED: Final = "LOCUS_POLICY_NOT_VALIDATED"
_DOC_BY_EVIDENCE: Final = {d.evidence_id: d.key for d in DOCUMENTS.values()}


def packet_id(ledger: LedgerId, after: int) -> str:
    return f"{ledger}-after-T{after}"


def render_value(value: ClaimValue) -> str:
    if value.text is not None:
        return value.text
    if value.quantity is not None:
        return f"{value.quantity} {value.unit}" if value.unit else str(value.quantity)
    return value.kind.value


def _docs(evidence_ids: tuple[str, ...]) -> list[str]:
    return [_DOC_BY_EVIDENCE.get(e, e) for e in evidence_ids]


def packet(run: LedgerRun, after: int) -> dict[str, Any]:
    """The frozen state of one ledger after T``after`` (1 or 2), exactly as it stood then."""
    if after not in (1, 2) or len(run.deltas) < after:
        raise ValueError(f"no frozen state for {run.ledger} after T{after}")
    state = run.deltas[after - 1].state_after.semantic
    active = active_judgment_ids(state)
    routes = {
        d.judgment_id: d.route
        for delta in run.deltas[:after]
        for d in (*delta.call_1, *delta.call_2)
    }
    scope = SCOPES[run.ledger]
    addresses = []
    for address_id, address in sorted(state.addresses.items()):
        if address.created_by_judgment_id not in active or scope not in address.scope:
            continue
        creator = state.judgments.get(address.created_by_judgment_id)
        created_from = (
            _docs(creator.proposal.candidate.evidence_ids)
            if creator is not None and isinstance(creator.proposal, CreateAddressProposal)
            else []
        )
        claims = [
            {
                "claim_id": claim_id,
                "live": claim.created_by_judgment_id in active,
                "predicate": claim.predicate,
                "value": render_value(claim.value),
                "cites": _docs(claim.evidence_ids),
                "created_by_judgment_id": claim.created_by_judgment_id,
            }
            for claim_id, claim in sorted(state.claims.items())
            if claim.address_id == address_id
        ]
        addresses.append(
            {
                "address_id": address_id,
                "subject": address.subject,
                "facet": address.facet,
                "created_from_documents": created_from,
                "claims": claims,
            }
        )
    relations = []
    for jid, judgment in sorted(state.judgments.items()):
        p = judgment.proposal
        if not isinstance(p, SupersedeProposal | ConflictsWithProposal | SupportsClaimProposal):
            continue
        entry: dict[str, Any] = {
            "judgment_id": jid,
            "kind": p.kind.value,
            "route": routes.get(jid, "SEED"),
            "applied": jid in state.applied_judgment_ids,
            "cites": _docs(judgment.visible_evidence_ids),
        }
        if isinstance(p, SupersedeProposal):
            entry["target_claim_created_by_judgment_id"] = p.target_judgment_id
        elif isinstance(p, ConflictsWithProposal):
            entry["claims"] = sorted((p.claim_a, p.claim_b))
        else:
            entry["claim_id"] = p.claim_id
        relations.append(entry)
    received = [*SEED_DOCUMENTS[run.ledger], *(REVISION[run.ledger] if after == 2 else ())]
    return {
        "packet_id": packet_id(run.ledger, after),
        "ledger": run.ledger,
        "after": f"T{after}",
        "documents_received": [{"key": d.key, "text": d.text} for d in received],
        "addresses": addresses,
        "relations": relations,
    }


def adjudication_bundle(run: RunRecord) -> dict[str, Any]:
    """One entry per sealed question: the question and the packet of its own timepoint."""
    by_ledger = {lg.ledger: lg for lg in run.ledgers if lg.status == "COMPLETED"}
    items = []
    for q in SEMANTIC_QUESTIONS:
        lg = by_ledger.get(q.ledger)
        frozen = packet(lg, q.after) if lg is not None else None
        items.append(
            {
                "id": q.id,
                "case": q.case,
                "ledger": q.ledger,
                "after": f"T{q.after}",
                "question": q.question,
                "packet_id": packet_id(q.ledger, q.after),
                "packet_sha256": canonical_sha256(frozen) if frozen is not None else None,
                "packet": frozen,
            }
        )
    return {"items": items}


class Standing(FrozenModel):
    structural_all_passed: bool
    semantic_all_yes: bool
    semantic_missing: tuple[str, ...]
    semantic_no: tuple[str, ...]
    critical_case: str
    critical_passed: bool
    cases: dict[str, bool]
    standing: str


def standing(structural: Mapping[str, CaseResult], answers: Mapping[str, str]) -> Standing:
    """All-or-nothing. ``answers`` maps question id to the adjudicator's YES/NO."""
    missing = tuple(q.id for q in SEMANTIC_QUESTIONS if q.id not in answers)
    said_no = tuple(q.id for q in SEMANTIC_QUESTIONS if answers.get(q.id, "YES") != "YES")
    semantic_ok = not missing and not said_no
    structural_ok = bool(structural) and all(r.passed for r in structural.values())
    cases = {
        c.id: c.id in structural
        and structural[c.id].passed
        and all(answers.get(q) == "YES" for q in c.semantic)
        for c in CASES
    }
    critical = cases.get(CRITICAL_CASE, False)
    validated = structural_ok and semantic_ok and critical and all(cases.values())
    return Standing(
        structural_all_passed=structural_ok,
        semantic_all_yes=semantic_ok,
        semantic_missing=missing,
        semantic_no=said_no,
        critical_case=CRITICAL_CASE,
        critical_passed=critical,
        cases=cases,
        standing=VALIDATED if validated else NOT_VALIDATED,
    )
