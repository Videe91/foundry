"""Timepoint-exact adjudication packets and the single standing (design §7.2, §8).

Every sealed question names its ledger and one of six timepoints: ``T1`` and ``T2`` (every
ledger); ``AGREED`` and ``DECLINED`` (the dense ledger right after the scripted human's
decisions, per branch); ``T3-AGREE`` and ``T3-DECLINE`` (after the T3 delta in each branch).
Its packet is built from exactly that frozen state: the addresses active then, their claims
(live or not), the judgments admitted by then with their routes, the correction sets and
their status, the scripted human's decisions, and the documents the ledger had received by
then. Nothing later appears in an earlier packet, and a branch's packet never shows the other
branch. The adjudicator receives one packet per question and nothing of the builder's
reasoning. ``standing`` turns the structural verdicts and the answers into one result.
"""

from __future__ import annotations

import json
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
from foundry.domain.state import IntentState
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v6.corpus import (
    DOCUMENTS,
    REVISION,
    SEED_DOCUMENTS,
    T3_DOCUMENTS,
)
from foundry.experiments.locus_validation_v6.evaluation import CaseResult
from foundry.experiments.locus_validation_v6.expectations import (
    CASES,
    CRITICAL_CASES,
    SEMANTIC_QUESTIONS,
    Timepoint,
)
from foundry.experiments.locus_validation_v6.protocol import SCOPES
from foundry.experiments.locus_validation_v6.runner import BranchRun, DeltaRun, LedgerRun, RunRecord

__all__ = [
    "NOT_VALIDATED",
    "VALIDATED",
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


def packet_id(ledger: str, at: str) -> str:
    return f"{ledger}-at-{at}"


def render_value(value: ClaimValue) -> str:
    if value.text is not None:
        return value.text
    if value.quantity is not None:
        return f"{value.quantity} {value.unit}" if value.unit else str(value.quantity)
    return value.kind.value


def _docs(evidence_ids: tuple[str, ...]) -> list[str]:
    return [_DOC_BY_EVIDENCE.get(e, e) for e in evidence_ids]


def _branch(run: LedgerRun, at: Timepoint) -> BranchRun | None:
    wanted = {"AGREED": "AGREE", "T3-AGREE": "AGREE", "DECLINED": "DECLINE"}.get(at, "DECLINE")
    return next((b for b in run.branches if b.branch == wanted), None)


def _frozen(run: LedgerRun, at: Timepoint) -> tuple[IntentState, list[DeltaRun], BranchRun | None]:
    """The state at ``at``, the model deltas that produced it, and its branch."""
    if at == "T1" and run.deltas:
        return run.deltas[0].state_after, list(run.deltas[:1]), None
    if at == "T2" and len(run.deltas) >= 2:
        return run.deltas[1].state_after, list(run.deltas[:2]), None
    branch = _branch(run, at) if at not in ("T1", "T2") else None
    if branch is None:
        raise ValueError(f"no frozen state for {run.ledger} at {at}")
    if at in ("AGREED", "DECLINED"):
        return branch.state_after_decisions, list(run.deltas), branch
    if branch.t3 is None:
        raise ValueError(f"no frozen state for {run.ledger} at {at}")
    return branch.t3.state_after, [*run.deltas, branch.t3], branch


def _received(run: LedgerRun, at: Timepoint) -> list[Any]:
    received = list(SEED_DOCUMENTS[run.ledger])
    if at != "T1":
        received += list(REVISION[run.ledger])
    if at.startswith("T3-"):
        received += list(T3_DOCUMENTS)
    return received


def packet(run: LedgerRun, at: Timepoint) -> dict[str, Any]:
    """The frozen state of one ledger at ``at``, exactly as it stood then."""
    state, deltas, branch = _frozen(run, at)
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    routes = {d.judgment_id: d.route for delta in deltas for d in (*delta.call_1, *delta.call_2)}
    scope = SCOPES[run.ledger]
    addresses = []
    for address_id, address in sorted(semantic.addresses.items()):
        if address.created_by_judgment_id not in active or scope not in address.scope:
            continue
        creator = semantic.judgments.get(address.created_by_judgment_id)
        created_from = (
            _docs(creator.proposal.candidate.evidence_ids)
            if creator is not None and isinstance(creator.proposal, CreateAddressProposal)
            else []
        )
        addresses.append(
            {
                "address_id": address_id,
                "subject": address.subject,
                "facet": address.facet,
                "created_from_documents": created_from,
                "claims": [
                    {
                        "claim_id": claim_id,
                        "live": claim.created_by_judgment_id in active,
                        "predicate": claim.predicate,
                        "value": render_value(claim.value),
                        "cites": _docs(claim.evidence_ids),
                        "created_by_judgment_id": claim.created_by_judgment_id,
                    }
                    for claim_id, claim in sorted(semantic.claims.items())
                    if claim.address_id == address_id
                ],
            }
        )
    relations = []
    for jid, judgment in sorted(semantic.judgments.items()):
        p = judgment.proposal
        if not isinstance(p, SupersedeProposal | ConflictsWithProposal | SupportsClaimProposal):
            continue
        admission = semantic.admissions.get(jid)
        entry: dict[str, Any] = {
            "judgment_id": jid,
            "kind": p.kind.value,
            "route": routes.get(jid, admission.route.value if admission else "SEED"),
            "reasons": list(admission.reasons) if admission else [],
            "applied": jid in semantic.applied_judgment_ids,
            "cites": _docs(judgment.visible_evidence_ids),
        }
        if isinstance(p, SupersedeProposal):
            entry["target_claim_created_by_judgment_id"] = p.target_judgment_id
        elif isinstance(p, ConflictsWithProposal):
            entry["claims"] = sorted((p.claim_a, p.claim_b))
        else:
            entry["claim_id"] = p.claim_id
        relations.append(entry)
    correction_sets = []
    for set_id, record in sorted(semantic.correction_sets.items()):
        held = [
            {
                "judgment_id": j,
                "predicate": getattr(semantic.judgments[j].proposal, "predicate", None),
                "value": render_value(semantic.judgments[j].proposal.value)  # type: ignore[union-attr]
                if hasattr(semantic.judgments[j].proposal, "value")
                else None,
                "cites": _docs(getattr(semantic.judgments[j].proposal, "evidence_ids", ())),
            }
            for j in record.assertion_judgment_ids
        ]
        correction_sets.append(
            {
                "correction_set_id": set_id,
                "address_id": record.address_id,
                "status": record.status,
                "held_assertions": held,
                "supersede_judgment_ids": list(record.supersede_judgment_ids),
                "retires_claims_created_by": list(record.target_judgment_ids),
                "decided_by": record.decided_by,
            }
        )
    decisions = [d.model_dump(mode="json") for d in branch.decisions] if branch else []
    return {
        "model_accounting": _model_accounting(run, at),
        "packet_id": packet_id(run.ledger, at),
        "ledger": run.ledger,
        "after": at,
        "documents_received": [{"key": d.key, "text": d.text} for d in _received(run, at)],
        "addresses": addresses,
        "relations": relations,
        "correction_sets": correction_sets,
        "human_decisions": decisions,
    }


def _model_accounting(run: LedgerRun, at: Timepoint) -> dict[str, Any] | None:
    """The claim-writing call of the delta that produced ``at``; ``None`` for a decision
    timepoint (no model call) and for the seeded T1 of ``conflict``."""
    if at in ("AGREED", "DECLINED"):
        return None
    t = {"T1": 1, "T2": 2}.get(at, 3)
    branch = at.removeprefix("T3-") if t == 3 else None
    calls = [
        c
        for c in run.calls
        if c.t == t and c.branch == branch and "ASSERT_CLAIM" in c.allowed_kinds
    ]
    if not calls:
        return None
    (call,) = calls
    rendered = json.loads(call.rendered_request)
    text = {s["sentence_id"]: s["text"] for s in rendered.get("sentences_to_account", ())}
    payload = call.model_payload or {}
    return {
        "refused": list(call.refusal_findings),
        "sentences_to_account": [
            {"sentence_id": sid, "text": sentence} for sid, sentence in text.items()
        ],
        "propositions": [
            {**p, "sentences": [text.get(sid, "?") for sid in p["sentence_ids"]]}
            for p in payload.get("propositions", ())
        ],
        "non_operative": [
            {**n, "text": text.get(n["sentence_id"], "?")} for n in payload.get("non_operative", ())
        ],
        "dispositions": [
            {
                k: d[k]
                for k in (
                    "kind",
                    "proposition_id",
                    "claim_id",
                    "address_id",
                    "predicate",
                    "value",
                    "target_judgment_id",
                )
                if k in d
            }
            for d in payload.get("drafts", ())
        ],
    }


def adjudication_bundle(run: RunRecord) -> dict[str, Any]:
    """One entry per sealed question: the question and the packet of its own timepoint."""
    by_ledger = {lg.ledger: lg for lg in run.ledgers if lg.status in ("COMPLETED", "REFUSED")}
    items = []
    for q in SEMANTIC_QUESTIONS:
        lg = by_ledger.get(q.ledger)
        try:
            frozen = packet(lg, q.after) if lg is not None else None
        except ValueError:
            frozen = None
        items.append(
            {
                "id": q.id,
                "case": q.case,
                "ledger": q.ledger,
                "after": q.after,
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
    critical_cases: tuple[str, ...]
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
    critical = all(cases.get(c, False) for c in CRITICAL_CASES)
    validated = structural_ok and semantic_ok and critical and all(cases.values())
    return Standing(
        structural_all_passed=structural_ok,
        semantic_all_yes=semantic_ok,
        semantic_missing=missing,
        semantic_no=said_no,
        critical_cases=CRITICAL_CASES,
        critical_passed=critical,
        cases=cases,
        standing=VALIDATED if validated else NOT_VALIDATED,
    )
