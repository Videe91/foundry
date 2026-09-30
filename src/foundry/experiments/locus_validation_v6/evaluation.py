"""Deterministic structural evaluation of a v6 run (design §7). No wording is read.

Every check is computed from the frozen run (governed states at every timepoint, admissions,
correction sets, the scripted human's decisions, call records) and the sealed expectations.
Findings are tagged; a case passes only with no finding. Wording belongs to the independent
semantic adjudication, never to this module.

Formation is checked per sealed concern (a concern may span several documents): one
CREATE_ADDRESS citing exactly its documents, none citing two concerns' documents
(``OVER_SPLIT`` / ``UNDER_SPLIT``). Corrections are checked as atomic correction sets:
one PENDING set per sealed correction, its targets among the claims of the sealed documents
(``WRONG_SUPERSEDE_TARGET`` / ``MISSING_TARGET``), nothing of it live while PENDING (``LEAK``,
``EARLY_RETIREMENT``); after AGREE every member applied and every target retired
(``PARTIAL_APPLY``, ``TARGET_NOT_RETIRED``); after DECLINE nothing applied and nothing still
held (``DECLINE_APPLIED``, ``STILL_BLOCKING``); a repeat of a DECLINED correction on the same
basis never becomes work again (``REOPENED``). Authority routing is checked at every
timepoint (``ROUTING``): the production invariant, no per-edge work for a correction, every
decision by the architect on a listed set, stable work ids.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Final

from foundry.application.replay import replay
from foundry.domain.authority_work import authority_routing_findings, authority_work
from foundry.domain.common import FrozenModel
from foundry.domain.correction_set import CORRECTION_DECLINED
from foundry.domain.events import CorrectionSetDecidedPayload, EventType
from foundry.domain.proposition_accounting import (
    AccountedProposition,
    CorrectionEdge,
    NonOperativeSentence,
    PropositionDisposition,
    accounting_findings,
    correction_edge_findings,
)
from foundry.domain.semantic_identity import canonical_facet
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    JudgmentKind,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.state import IntentState
from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS
from foundry.experiments.locus_validation_v6.expectations import (
    BANNED_FACETS,
    CASES,
    CONCERNS,
    CORRECTIONS,
    EXPECTED_ADDRESS_COUNTS,
    EXPECTED_CONFLICTS,
    EXPECTED_PENDING_SETS,
    EXPECTED_SEPARATE,
    ITEMS,
    LIVE_CLAIMS,
    STRUCTURAL_CHECKS,
    CorrectionExpectation,
    ItemExpectation,
    Timepoint,
    concern_of_document,
    source_coverage_findings,
    timepoints_of,
)
from foundry.experiments.locus_validation_v6.protocol import (
    ARCHITECT,
    AUTHORITY_PROTOCOL,
    BRANCHED,
    BRANCHES,
    CALLS_PER_DELTA,
    CORRECTION_LAW_FROZEN,
    LEDGERS,
    MAX_FRONTIER_CALLS,
    MODEL_SEEDED,
    SCOPES,
    Branch,
    LedgerId,
)
from foundry.experiments.locus_validation_v6.recording import CallRecord
from foundry.experiments.locus_validation_v6.runner import BranchRun, LedgerRun, RunRecord

__all__ = ["CaseResult", "evaluate", "recompute_accounting", "split_tally"]

_V5_ITEM_CASE: Final[dict[str, str]] = {
    **{f"{k}-T1": "C0-CORE-SEED" for k in ("PICKUP", "LABEL", "WEIGHT", "ATTEMPTS")},
    "LATE-T1": "C6-LATE-DELIVERY",
    "DAMAGE-T1": "U2-LATE-VS-DAMAGE",
    "SETTLEMENT-T1": "U3-COMPENSATION-VS-SETTLEMENT",
    "H-T1": "C7-C09-REGRESSION",
    "CANCEL-T1": "U1-CANCEL-VS-AUDIT",
    "AUDIT-T1": "U1-CANCEL-VS-AUDIT",
    "CUSTOMER-REFUND-T1": "U4-CUSTOMER-VS-SUPPLIER-REFUND",
    "SUPPLIER-OVERPAYMENT-T1": "U4-CUSTOMER-VS-SUPPLIER-REFUND",
    "PICKUP-T2": "C1-RESTATEMENT",
    "LABEL-T2": "C2-EXTENSION",
    "ATTEMPTS-T2": "C3-NEW-CONCERN",
    "WEIGHT-T2": "C4-CORRECTION",
    "LATE-NOTE-T2": "C6-LATE-DELIVERY",
    "H-T9": "C7-C09-REGRESSION",
    "CANCEL-NOTE-T2": "U1-CANCEL-VS-AUDIT",
    "HANDBOOK-T2": "C5-EXISTING-CONFLICT",
    "FAQ-T2": "C5-EXISTING-CONFLICT",
    "RETURNS-NOTE-T2": "C8-LARGE-WORLD",
}
_DENSE_ITEM_CASE: Final[dict[str, str]] = {
    "K-CLEANING-T2": "X1-ONE-TO-ONE",
    "K-LATE-T2": "X2-MANY-TO-ONE",
    "K-CREDIT-T2": "X3-ONE-TO-MANY",
    "K-UNLOCK-WAIT-T2": "X4-MANY-TO-MANY",
    "K-TRIP-T2": "Z6-AUTHORITY-ROUTING",
    "K-UNLOCK-WAIT-T3": "Z4-REPEAT-SUPPRESSED",
    "K-CLEANING-T3": "Z5-CHANGED-BASIS-REOPENS",
}
_DENSE_FORMATION_CASE: Final[dict[str, str]] = {
    "RESERVATION": "D1-RESERVATION-ONE-CONCERN",
    "UNLOCK": "D2-UNLOCK-ATTEMPTS-ONE-CONCERN",
    "LATE-FEE": "D3-LATE-FEE-ONE-CONCERN",
    "SERVICE-CREDIT": "D4-SERVICE-CREDIT-ONE-CONCERN",
}
_PENDING_CASE: Final[dict[Timepoint, str]] = {
    "T2": "Z1-PENDING-ATOMIC",
    "AGREED": "Z2-AGREE",
    "DECLINED": "Z3-DECLINE",
    "T3-AGREE": "Z5-CHANGED-BASIS-REOPENS",
    "T3-DECLINE": "Z4-REPEAT-SUPPRESSED",
}
_LEGACY_ALLOWED: Final = frozenset({JudgmentKind.CONFLICTS_WITH.value})
"""Per-signature authority work that may exist: a pending CONFLICTS_WITH (a relation, never a
correction). A SUPERSEDE or an ASSERT_CLAIM is only ever decided inside a correction set."""


class CaseResult(FrozenModel):
    case_id: str
    passed: bool
    findings: tuple[str, ...]


class _Draft(FrozenModel):
    at: Timepoint
    call: int
    judgment: SemanticJudgment
    route: str
    reasons: tuple[str, ...]


def _cited(j: SemanticJudgment) -> tuple[str, ...]:
    p = j.proposal
    if isinstance(p, CreateAddressProposal | BindToAddressProposal):
        return p.candidate.evidence_ids
    if isinstance(p, AssertClaimProposal | SupportsClaimProposal):
        return p.evidence_ids
    return j.visible_evidence_ids


class _Findings:
    def __init__(self) -> None:
        self.by_case: dict[str, list[str]] = defaultdict(list)

    def add(self, case: str, tag: str, detail: str) -> None:
        self.by_case[case].append(f"{tag}: {detail}")


# ------------------------------------------------------------------ the ledger's surfaces


class _Ledger:
    """One completed ledger: its state and drafts at every timepoint, its concern addresses."""

    def __init__(self, run: LedgerRun) -> None:
        self.run = run
        self.ledger: LedgerId = run.ledger
        self.states: dict[Timepoint, IntentState] = {
            "T1": run.deltas[0].state_after,
            "T2": run.deltas[1].state_after,
        }
        self.branches: dict[Branch, BranchRun] = {b.branch: b for b in run.branches}
        for b in run.branches:
            self.states["AGREED" if b.branch == "AGREE" else "DECLINED"] = b.state_after_decisions
            if b.t3 is not None:
                self.states[f"T3-{b.branch}"] = b.t3.state_after  # type: ignore[index]
        drafts: list[_Draft] = []
        deltas: list[tuple[Timepoint, object]] = [("T1", run.deltas[0]), ("T2", run.deltas[1])]
        deltas += [(f"T3-{b.branch}", b.t3) for b in run.branches if b.t3 is not None]  # type: ignore[misc]
        for at, delta in deltas:
            final = self.states[at].semantic
            for call, batch in ((1, delta.call_1), (2, delta.call_2)):  # type: ignore[attr-defined]
                for d in batch:
                    drafts.append(
                        _Draft(
                            at=at,
                            call=call,
                            judgment=final.judgments[d.judgment_id],
                            route=d.route,
                            reasons=d.reasons,
                        )
                    )
        self.drafts = tuple(drafts)
        self.addresses: dict[str, str | None] = {}
        for concern in CONCERNS:
            if concern.ledger != self.ledger:
                continue
            if concern.origin == "AUTHOR_SEED":
                self.addresses[concern.key] = run.seed_address_ids.get(concern.key)
            else:
                formed_at: Timepoint = "T1" if concern.origin == "MODEL_T1" else "T2"
                self.addresses[concern.key] = self._formed(concern.documents, formed_at)

    def semantic(self, at: Timepoint) -> SemanticState:
        return self.states[at].semantic

    def timepoints(self) -> tuple[Timepoint, ...]:
        return tuple(t for t in timepoints_of(self.ledger) if t in self.states)

    def _formed(self, documents: tuple[str, ...], at: Timepoint) -> str | None:
        evidence = {DOCUMENTS[d].evidence_id for d in documents}
        creates = [
            d
            for d in self.select(at=at, call=1, kind=JudgmentKind.CREATE_ADDRESS)
            if set(_cited(d.judgment)) & evidence
        ]
        if len(creates) != 1 or set(_cited(creates[0].judgment)) != evidence:
            return None
        return self.address_created_by(creates[0].judgment.judgment_id)

    def address_created_by(self, jid: str) -> str | None:
        for address_id, address in self.semantic("T2").addresses.items():
            if address.created_by_judgment_id == jid:
                return address_id
        return None

    def select(
        self,
        *,
        at: Timepoint | None = None,
        call: int | None = None,
        kind: JudgmentKind | None = None,
        citing: str | None = None,
    ) -> tuple[_Draft, ...]:
        return tuple(
            d
            for d in self.drafts
            if (at is None or d.at == at)
            and (call is None or d.call == call)
            and (kind is None or d.judgment.proposal.kind is kind)
            and (citing is None or citing in _cited(d.judgment))
        )

    def live_claims(self, address_id: str | None, at: Timepoint) -> tuple[str, ...]:
        if address_id is None:
            return ()
        state = self.semantic(at)
        active = active_judgment_ids(state)
        return tuple(
            sorted(
                cid
                for cid, c in state.claims.items()
                if c.address_id == address_id and c.created_by_judgment_id in active
            )
        )

    def active_addresses(self, at: Timepoint) -> int:
        state = self.semantic(at)
        active = active_judgment_ids(state)
        scope = SCOPES[self.ledger]
        return sum(
            1
            for a in state.addresses.values()
            if a.created_by_judgment_id in active and scope in a.scope
        )

    def key_of(self, address_id: str | None) -> str | None:
        for key, value in self.addresses.items():
            if value is not None and value == address_id:
                return key
        return None

    def pending_sets(self, at: Timepoint) -> dict[str, list[str]]:
        """Address id -> ids of its PENDING correction sets at ``at``."""
        out: dict[str, list[str]] = defaultdict(list)
        for record in self.semantic(at).correction_sets.values():
            if record.status == "PENDING":
                out[record.address_id].append(record.correction_set_id)
        return out


def _previous(at: Timepoint) -> Timepoint | None:
    return {
        "T1": None,
        "T2": "T1",
        "AGREED": "T2",
        "DECLINED": "T2",
        "T3-AGREE": "AGREED",
        "T3-DECLINE": "DECLINED",
    }[at]


# ------------------------------------------------------------------ formation (per concern)


def _formation_case(ledger: LedgerId, concern: str, documents: tuple[str, ...]) -> str:
    if ledger == "dense":
        return _DENSE_FORMATION_CASE.get(concern, "D5-SINGLE-SECTION-CONCERNS")
    return _V5_ITEM_CASE.get(documents[0], "C8-LARGE-WORLD") if documents else "C8-LARGE-WORLD"


def _check_formation(lg: _Ledger, out: _Findings) -> None:
    """One CREATE per concern citing exactly its documents; none spanning two concerns."""
    for concern in CONCERNS:
        if concern.ledger != lg.ledger or concern.origin == "AUTHOR_SEED":
            continue
        at: Timepoint = "T1" if concern.origin == "MODEL_T1" else "T2"
        cases = {_formation_case(lg.ledger, concern.key, concern.documents)}
        if lg.ledger == "dense":
            cases.add("D0-DENSE-FORMATION")
        evidence = {DOCUMENTS[d].evidence_id for d in concern.documents}
        creates = [
            d
            for d in lg.select(at=at, call=1, kind=JudgmentKind.CREATE_ADDRESS)
            if set(_cited(d.judgment)) & evidence
        ]
        for case in sorted(cases):
            if len(creates) > 1:
                out.add(case, "OVER_SPLIT", f"{len(creates)} CREATE_ADDRESS form {concern.key}")
            elif not creates:
                out.add(case, "UNDER_SPLIT", f"no CREATE_ADDRESS forms {concern.key}")
            for d in creates:
                cited = set(_cited(d.judgment))
                spans = {
                    concern_of_document(doc)
                    for doc in (_doc_key(e) for e in cited)
                    if doc is not None and DOCUMENTS[doc].t == 1
                }
                others = sorted(c for c in spans if c is not None and c != concern.key)
                if others:
                    out.add(case, "UNDER_SPLIT", f"{concern.key} formed together with {others}")
                elif len(creates) == 1 and cited != evidence and at == "T1":
                    out.add(case, "OVER_SPLIT", f"{concern.key} formed from part of its sections")


def _doc_key(evidence_id: str) -> str | None:
    for key, doc in DOCUMENTS.items():
        if doc.evidence_id == evidence_id:
            return key
    return None


# ------------------------------------------------------------------ revised items


def _item_case(item: ItemExpectation) -> str:
    return _V5_ITEM_CASE.get(item.document) or _DENSE_ITEM_CASE[item.document]


def _targets_of(lg: _Ledger, at: Timepoint, document: str) -> set[str]:
    """Claim ids targeted by the SUPERSEDEs of ``document``'s delta at ``at``."""
    state = lg.semantic(at)
    by_judgment = {c.created_by_judgment_id: cid for cid, c in state.claims.items()}
    ev = DOCUMENTS[document].evidence_id
    targets: set[str] = set()
    for d in lg.select(at=at, call=2, kind=JudgmentKind.SUPERSEDE, citing=ev):
        proposal = d.judgment.proposal
        assert isinstance(proposal, SupersedeProposal)
        claim = by_judgment.get(proposal.target_judgment_id)
        if claim is not None:
            targets.add(claim)
    return targets


def _check_item(lg: _Ledger, item: ItemExpectation, out: _Findings) -> None:
    case = _item_case(item)
    at = item.at
    ev = DOCUMENTS[item.document].evidence_id
    state = lg.semantic(at)
    binds = lg.select(at=at, call=1, kind=JudgmentKind.BIND_TO_ADDRESS, citing=ev)
    bound: dict[str | None, int] = defaultdict(int)
    for d in binds:
        proposal = d.judgment.proposal
        assert isinstance(proposal, BindToAddressProposal)
        bound[proposal.address_id] += 1
    expected_ids = {lg.addresses.get(k) for k in item.binds}
    for key in item.binds:
        target = lg.addresses.get(key)
        if target is None or bound.get(target, 0) != 1:
            out.add(case, "MISSING_BIND", f"{item.document} bound {bound.get(target, 0)}x to {key}")
    for address_id, n in bound.items():
        if address_id not in expected_ids:
            out.add(case, "WRONG_BIND", f"{item.document} bound {n}x to {lg.key_of(address_id)}")
    creates = lg.select(at=at, call=1, kind=JudgmentKind.CREATE_ADDRESS, citing=ev)
    if len(creates) > item.creates:
        out.add(case, "OVER_SPLIT", f"{len(creates)} CREATE_ADDRESS cite {item.document}")
    elif len(creates) < item.creates:
        out.add(case, "UNDER_SPLIT", f"{len(creates)} CREATE_ADDRESS cite {item.document}")

    new_ids = {d.judgment.judgment_id for d in lg.select(at=at)}
    active = active_judgment_ids(state)
    new_at: dict[str, int] = defaultdict(int)
    for c in state.claims.values():
        if (
            c.created_by_judgment_id in new_ids
            and c.created_by_judgment_id in active
            and ev in c.evidence_ids
        ):
            new_at[c.address_id] += 1
    for key, (low, high) in item.new_live.items():
        got = new_at.get(lg.addresses.get(key) or "", 0)
        if not low <= got <= high:
            tag = "MISSING_EXTENSION" if got < low else "DUPLICATE_ASSERTION"
            out.add(case, tag, f"{got} new live claims citing {item.document} at {key}")
    expected_new = {lg.addresses.get(k) for k in item.new_live}
    for address_id, n in new_at.items():
        if address_id in expected_new:
            continue
        where = lg.key_of(address_id)
        tag = "LEAK" if lg.key_of(address_id) in item.held else "UNEXPECTED_CLAIM"
        out.add(case, tag, f"{n} new live claims citing {item.document} at {where}")

    held_at: dict[str | None, int] = defaultdict(int)
    for d in lg.select(at=at, call=2, kind=JudgmentKind.ASSERT_CLAIM, citing=ev):
        if d.route == AdmissionRoute.REQUIRE_HUMAN.value and _in_pending_set(state, d):
            proposal = d.judgment.proposal
            assert isinstance(proposal, AssertClaimProposal)
            held_at[proposal.address_id] += 1
    for key, (low, high) in item.held.items():
        got = held_at.get(lg.addresses.get(key), 0)
        if not low <= got <= high:
            out.add(case, "HELD_COUNT", f"{got} held assertions citing {item.document} at {key}")
    for address_id, n in held_at.items():
        if lg.key_of(address_id) not in item.held:
            out.add(case, "UNEXPECTED_HOLD", f"{n} held assertions at {lg.key_of(address_id)}")

    supported: set[str] = set()
    for d in lg.select(at=at, call=2, kind=JudgmentKind.SUPPORTS_CLAIM, citing=ev):
        proposal = d.judgment.proposal
        assert isinstance(proposal, SupportsClaimProposal)
        claim = state.claims.get(proposal.claim_id)
        where = None if claim is None else claim.address_id
        if where not in expected_ids:
            out.add(case, "WRONG_BIND", f"{item.document} supports a claim at {lg.key_of(where)}")
        if d.judgment.judgment_id in state.applied_judgment_ids:
            supported.add(proposal.claim_id)
    if item.support_documents:
        targets = _targets_of(lg, at, item.document)
        support_ev = {DOCUMENTS[s].evidence_id for s in item.support_documents}
        missing = [
            cid
            for key in item.binds
            for cid in lg.live_claims(lg.addresses.get(key), at)
            if cid not in targets
            and set(state.claims[cid].evidence_ids) & support_ev
            and state.claims[cid].created_by_judgment_id not in new_ids
            and cid not in supported
        ]
        if missing:
            out.add(case, "MISSING_SUPPORT", f"{item.document} does not support {missing}")


def _in_pending_set(state: SemanticState, d: _Draft) -> bool:
    jid = d.judgment.judgment_id
    return any(
        r.status == "PENDING" and jid in r.member_judgment_ids
        for r in state.correction_sets.values()
    )


# ------------------------------------------------------------------ corrections and decisions


def _correction_case(g: CorrectionExpectation) -> str:
    if g.id.startswith("Z5-"):
        return "Z5-CHANGED-BASIS-REOPENS"
    return "C4-CORRECTION" if g.id == "X0-WEIGHT" else g.id


def _new_sets(lg: _Ledger, at: Timepoint, address_id: str | None) -> list[str]:
    before = _previous(at)
    known = set(lg.semantic(before).correction_sets) if before is not None else set()
    return sorted(
        r.correction_set_id
        for r in lg.semantic(at).correction_sets.values()
        if r.correction_set_id not in known and r.address_id == address_id
    )


def _check_correction(lg: _Ledger, g: CorrectionExpectation, out: _Findings) -> None:
    case = _correction_case(g)
    if g.at not in lg.states:
        out.add(case, "ABORTED", f"no state at {g.at}")
        return
    address = lg.addresses.get(g.concern)
    state = lg.semantic(g.at)
    active = active_judgment_ids(state)
    new = _new_sets(lg, g.at, address)
    if g.outcome == "SUPPRESSED_AS_DECLINED":
        if new:
            out.add(case, "REOPENED", f"{len(new)} new correction set(s) at {g.concern}")
        declined = [
            r.correction_set_id
            for r in state.correction_sets.values()
            if r.status == "DECLINED" and r.address_id == address
        ]
        ev = DOCUMENTS[g.document].evidence_id
        for d in lg.select(at=g.at, call=2, citing=ev):
            if d.judgment.proposal.kind not in (JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPERSEDE):
                continue
            if d.reasons[:1] != (CORRECTION_DECLINED,) or d.reasons[1:2] != tuple(declined[:1]):
                out.add(case, "REOPENED", f"a repeated correction was routed {d.route}")
        return
    if len(new) != 1:
        out.add(case, "MISSING_SET" if not new else "DUPLICATE_SET", f"{len(new)} new sets")
        return
    record = state.correction_sets[new[0]]
    if record.status != "PENDING":
        out.add(case, "NOT_PENDING", f"{record.correction_set_id} is {record.status}")
    by_judgment = {c.created_by_judgment_id: cid for cid, c in state.claims.items()}
    targets = {by_judgment.get(t) for t in record.target_judgment_ids}
    target_ev = {DOCUMENTS[d].evidence_id for d in g.target_documents}
    allowed = {
        cid
        for cid in lg.live_claims(address, g.at)
        if set(state.claims[cid].evidence_ids) & target_ev
    }
    for t in sorted(str(t) for t in targets if t not in allowed or t is None):
        out.add(case, "WRONG_SUPERSEDE_TARGET", f"{record.correction_set_id} retires {t}")
    real = {t for t in targets if t in allowed}
    if not 1 <= len(real) <= len(g.obsolete) or (g.exact_targets and real != allowed):
        out.add(
            case,
            "MISSING_TARGET",
            f"{len(real)} of the sealed claims targeted ({len(allowed)} candidates)",
        )
    members = set(record.member_judgment_ids) & set(state.applied_judgment_ids)
    if members:
        out.add("Z1-PENDING-ATOMIC" if g.at == "T2" else case, "LEAK", f"{sorted(members)}")
    retired = [t for t in record.target_judgment_ids if t not in active]
    if retired:
        out.add("Z1-PENDING-ATOMIC" if g.at == "T2" else case, "EARLY_RETIREMENT", f"{retired}")
    if g.decided:
        _check_decided(lg, g, record.correction_set_id, out)


def _check_decided(lg: _Ledger, g: CorrectionExpectation, set_id: str, out: _Findings) -> None:
    for branch in BRANCHES:
        at: Timepoint = "AGREED" if branch == "AGREE" else "DECLINED"
        case = "Z2-AGREE" if branch == "AGREE" else "Z3-DECLINE"
        if at not in lg.states:
            out.add(case, "ABORTED", f"no {at} state")
            continue
        state = lg.semantic(at)
        record = state.correction_sets.get(set_id)
        if record is None or record.status != g.decided[branch]:
            out.add(case, "UNDECIDED", f"{set_id} is {None if record is None else record.status}")
            continue
        applied = set(record.member_judgment_ids) & set(state.applied_judgment_ids)
        active = active_judgment_ids(state)
        live_targets = [t for t in record.target_judgment_ids if t in active]
        if branch == "AGREE":
            if applied != set(record.member_judgment_ids):
                out.add(case, "PARTIAL_APPLY", f"{g.id}: {len(applied)} of the members applied")
            if live_targets:
                out.add(case, "TARGET_NOT_RETIRED", f"{g.id}: {live_targets}")
        else:
            if applied:
                out.add(case, "DECLINE_APPLIED", f"{g.id}: {sorted(applied)}")
            if len(live_targets) != len(record.target_judgment_ids):
                out.add(case, "DECLINE_APPLIED", f"{g.id}: a target was retired")
            from foundry.domain.semantic_view import derive_view

            pending = set(derive_view(state).pending_judgment_ids)
            if pending & set(record.member_judgment_ids):
                out.add(case, "STILL_BLOCKING", f"{g.id}: members still pending")


def _check_pending_sets(lg: _Ledger, out: _Findings) -> None:
    for at in lg.timepoints():
        expected = EXPECTED_PENDING_SETS[lg.ledger][at]
        pending = lg.pending_sets(at)
        case = (
            "C4-CORRECTION" if lg.ledger == "core" else _PENDING_CASE.get(at, f"LEDGER-{lg.ledger}")
        )
        if lg.ledger not in ("core", "dense"):
            case = f"LEDGER-{lg.ledger}"
        for key in expected:
            n = len(pending.get(lg.addresses.get(key) or "", []))
            if n != 1:
                out.add(case, "MISSING_SET" if n == 0 else "DUPLICATE_SET", f"{key} at {at}: {n}")
        wanted = {lg.addresses.get(k) for k in expected}
        for address_id in pending:
            if address_id not in wanted:
                out.add(case, "UNEXPECTED_SET", f"{lg.key_of(address_id)} at {at}")


# ------------------------------------------------------------------ authority routing


def _check_routing(lg: _Ledger, out: _Findings) -> None:
    case = "AUTHORITY-ROUTING"
    for at in lg.timepoints():
        state = lg.states[at]
        queue = authority_work(state)
        for finding in authority_routing_findings(state, queue):
            out.add(case, "ROUTING", f"{lg.ledger} {at}: {finding}")
        for item in queue.items:
            if item.kind not in _LEGACY_ALLOWED:
                out.add(case, "ROUTING", f"{lg.ledger} {at}: per-edge {item.kind} work")
    if lg.run.work_after_t2 is not None:
        replayed = authority_work(replay(lg.states["T2"].project_id, lg.run.events))
        if lg.run.branches:
            pass  # the branch clones extend the ledger; stability is checked on T2's events
        elif [s.work_id for s in replayed.correction_sets] != [
            s.work_id for s in lg.run.work_after_t2.correction_sets
        ]:
            out.add(case, "ROUTING", f"{lg.ledger}: work ids changed on replay")
    for b in lg.run.branches:
        listed = {s.work_id for s in b.work_before.correction_sets}
        decided = {d.work_id for d in b.decisions}
        if decided != listed:
            out.add(
                "Z6-AUTHORITY-ROUTING",
                "ROUTING",
                f"{b.branch}: decided {len(decided)} of {len(listed)} listed sets",
            )
        t2_ids = {
            s.work_id
            for s in (lg.run.work_after_t2.correction_sets if lg.run.work_after_t2 else ())
        }
        if listed != t2_ids:
            out.add("Z6-AUTHORITY-ROUTING", "ROUTING", f"{b.branch}: listing differs from T2's")
        payloads = [
            e.event.payload
            for e in b.events
            if e.event.event_type is EventType.CORRECTION_SET_DECIDED
        ]
        for p in payloads:
            if not (
                isinstance(p, CorrectionSetDecidedPayload)
                and p.decided_by == ARCHITECT
                and p.authority_protocol == AUTHORITY_PROTOCOL
            ):
                out.add("Z6-AUTHORITY-ROUTING", "SELF_APPROVAL", f"{b.branch}: {p}")
        if len(payloads) != len(listed):
            out.add("Z6-AUTHORITY-ROUTING", "ROUTING", f"{b.branch}: {len(payloads)} decisions")
    for d in lg.drafts:
        semantic = lg.semantic(d.at)
        if d.route == AdmissionRoute.APPLY.value and any(
            d.judgment.judgment_id in r.member_judgment_ids
            for r in semantic.correction_sets.values()
        ):
            out.add("Z6-AUTHORITY-ROUTING", "SELF_APPROVAL", f"{d.judgment.judgment_id} applied")


# ------------------------------------------------------------------ counts, separation, facets


def _count_case(lg: _Ledger, key: str, at: Timepoint) -> str:
    if lg.ledger != "dense":
        concern = next(c for c in CONCERNS if c.ledger == lg.ledger and c.key == key)
        documents = concern.documents
        if at == "T1" or not documents:
            return (
                _formation_case(lg.ledger, key, documents) if documents else "C5-EXISTING-CONFLICT"
            )
        t2 = next(
            (i.document for i in ITEMS if i.ledger == lg.ledger and key in (*i.binds, *i.new_live)),
            None,
        )
        return _V5_ITEM_CASE.get(t2 or "", _formation_case(lg.ledger, key, documents))
    if at == "T1":
        return _DENSE_FORMATION_CASE.get(key, "D5-SINGLE-SECTION-CONCERNS")
    return {"AGREED": "Z2-AGREE", "DECLINED": "Z3-DECLINE"}.get(at, "D0-DENSE-FORMATION")


def _check_counts(lg: _Ledger, out: _Findings) -> None:
    for at in lg.timepoints():
        for key, address_id in lg.addresses.items():
            want = LIVE_CLAIMS.get(f"{lg.ledger}/{key}/{at}")
            if want is None:
                continue
            got = len(lg.live_claims(address_id, at))
            if address_id is None or not want[0] <= got <= want[1]:
                out.add(
                    _count_case(lg, key, at),
                    "CLAIM_COUNT",
                    f"{key} has {got} live claims at {at}, expected {want[0]}-{want[1]}",
                )
        want_n = EXPECTED_ADDRESS_COUNTS[lg.ledger][at]
        got_n = lg.active_addresses(at)
        if got_n != want_n:
            out.add(f"LEDGER-{lg.ledger}", "ADDRESS_COUNT", f"{got_n} active addresses at {at}")
    for pair in EXPECTED_SEPARATE:
        if pair.ledger != lg.ledger:
            continue
        a, b = lg.addresses.get(pair.a), lg.addresses.get(pair.b)
        if a is None or b is None or a == b:
            out.add(pair.case, "UNDER_SPLIT", f"{pair.a} and {pair.b} are not two addresses")
    for d in lg.drafts:
        if d.route != "REJECT":
            continue
        suppressed = d.at == "T3-DECLINE" and d.reasons[:1] == (CORRECTION_DECLINED,)
        if not suppressed:
            out.add(
                f"LEDGER-{lg.ledger}",
                "REJECTED_ADMISSION",
                f"{d.at} call {d.call} {d.judgment.proposal.kind.value}: {d.reasons[:1]}",
            )


def _check_governance(lg: _Ledger, out: _Findings) -> None:
    """No SUPERSEDE outside a sealed correction; the v5 conflict law."""
    sealed = {
        (g.at, DOCUMENTS[g.document].evidence_id) for g in CORRECTIONS if g.ledger == lg.ledger
    }
    for d in lg.select(kind=JudgmentKind.SUPERSEDE):
        if not any((d.at, e) in sealed for e in d.judgment.visible_evidence_ids):
            case = "C5-EXISTING-CONFLICT" if lg.ledger == "conflict" else f"LEDGER-{lg.ledger}"
            tag = "FABRICATED_SUPERSEDE" if lg.ledger == "conflict" else "UNEXPECTED_SUPERSEDE"
            if lg.ledger == "orion":
                case = "C7-C09-REGRESSION"
            out.add(case, tag, f"{d.at}: a SUPERSEDE outside every sealed correction")
    wanted = {
        frozenset(lg.run.seed_claim_ids.get(k) for k in pair)
        for pair in EXPECTED_CONFLICTS[lg.ledger]
    }
    named: set[frozenset[str | None]] = set()
    for d in lg.select(kind=JudgmentKind.CONFLICTS_WITH):
        proposal = d.judgment.proposal
        assert isinstance(proposal, ConflictsWithProposal)
        pair: frozenset[str | None] = frozenset({proposal.claim_a, proposal.claim_b})
        case = "C5-EXISTING-CONFLICT" if lg.ledger == "conflict" else f"LEDGER-{lg.ledger}"
        if pair not in wanted:
            out.add(case, "UNEXPECTED_CONFLICT", f"{d.at}: a CONFLICTS_WITH names other claims")
            continue
        if d.route != AdmissionRoute.REQUIRE_SECOND_LENS.value:
            out.add(case, "UNGOVERNED_CONFLICT", f"a CONFLICTS_WITH routed {d.route}")
        named.add(pair)
    if wanted - named:
        out.add("C5-EXISTING-CONFLICT", "MISSING_CONFLICT", "the seeded claims were not held")


def _payload_facets(value: object) -> int:
    if isinstance(value, dict):
        return sum(1 for k in value if k == "facet") + sum(
            _payload_facets(v) for v in value.values()
        )
    if isinstance(value, list):
        return sum(_payload_facets(v) for v in value)
    return 0


def _check_facets(lg: _Ledger, out: _Findings) -> None:
    case = "CANONICAL-FACETS"
    for at in lg.timepoints():
        state = lg.semantic(at)
        active = active_judgment_ids(state)
        seen: dict[str, str] = {}
        for address_id, a in sorted(state.addresses.items()):
            if a.facet != canonical_facet(a.subject):
                out.add(case, "NON_CANONICAL_FACET", f"{lg.ledger} {at} {address_id}: {a.facet!r}")
            if a.facet in BANNED_FACETS:
                out.add(case, "BANNED_FACET", f"{lg.ledger} {at} {address_id}: {a.facet!r}")
            if a.created_by_judgment_id not in active:
                continue
            if a.facet in seen:
                out.add(case, "FACET_COLLISION", f"{lg.ledger} {at} {seen[a.facet]}, {address_id}")
            seen[a.facet] = address_id
    for d in lg.drafts:
        p = d.judgment.proposal
        if isinstance(
            p, CreateAddressProposal | BindToAddressProposal
        ) and p.candidate.facet != canonical_facet(p.candidate.subject):
            out.add(case, "NON_CANONICAL_FACET", f"{lg.ledger} {d.at}: {p.candidate.facet!r}")
    for c in lg.run.calls:
        n = _payload_facets(c.model_payload)
        if n:
            out.add(case, "MODEL_FACET", f"{lg.ledger} T{c.t} call {c.call}: {n} facet field(s)")


# ------------------------------------------------------------------ integrity and accounting


def _expected_calls(ledger: LedgerId) -> dict[tuple[int, str | None], int]:
    calls: dict[tuple[int, str | None], int] = {(2, None): CALLS_PER_DELTA}
    if ledger in MODEL_SEEDED:
        calls[(1, None)] = CALLS_PER_DELTA
    if ledger == BRANCHED:
        for branch in BRANCHES:
            calls[(3, branch)] = CALLS_PER_DELTA
    return calls


def _check_integrity(run: RunRecord, out: _Findings) -> None:
    case = "RUN-INTEGRITY"
    if run.status != "COMPLETED":
        out.add(case, "ABORTED", f"run status {run.status}")
    present = {lg.ledger for lg in run.ledgers}
    for ledger in LEDGERS:
        if ledger not in present:
            out.add(case, "ABORTED", f"ledger {ledger} never ran")
    for lg in run.ledgers:
        if lg.status not in ("COMPLETED", "REFUSED"):
            out.add(case, "ABORTED", f"ledger {lg.ledger}: {lg.error}")
        if lg.replay_matches is not True:
            out.add(case, "INTEGRITY", f"ledger {lg.ledger} replay did not reproduce state")
        for b in lg.branches:
            if b.status not in ("COMPLETED", "REFUSED"):
                out.add(case, "ABORTED", f"branch {b.branch}: {b.error}")
            if b.replay_matches is not True:
                out.add(case, "INTEGRITY", f"branch {b.branch} replay did not reproduce state")
        if lg.ledger == BRANCHED and lg.status == "COMPLETED" and len(lg.branches) != 2:
            out.add(case, "ABORTED", f"{len(lg.branches)} dense branches")
        per: dict[tuple[int, str | None], int] = defaultdict(int)
        for c in lg.calls:
            per[(c.t, c.branch)] += 1
        refused = lg.status == "REFUSED" or any(b.status == "REFUSED" for b in lg.branches)
        if refused:
            if any(n > CALLS_PER_DELTA for n in per.values()):
                out.add(case, "INTEGRITY", f"ledger {lg.ledger} calls per delta {dict(per)}")
        elif dict(per) != _expected_calls(lg.ledger):
            out.add(case, "INTEGRITY", f"ledger {lg.ledger} calls per delta {dict(per)}")
        for c in lg.calls:
            state = _final_state(lg, c).semantic
            for jid in c.returned_judgment_ids:
                j = state.judgments.get(jid)
                if j is None:
                    continue
                problem = _reference_problem(j, c)
                if problem:
                    out.add(case, "INTEGRITY", f"{lg.ledger} T{c.t} call {c.call}: {problem}")
    any_refused = any(
        lg.status == "REFUSED" or any(b.status == "REFUSED" for b in lg.branches)
        for lg in run.ledgers
    )
    if run.frontier_calls != MAX_FRONTIER_CALLS and run.status == "COMPLETED" and not any_refused:
        out.add(case, "INTEGRITY", f"{run.frontier_calls} frontier calls")


def _final_state(lg: LedgerRun, c: CallRecord) -> IntentState:
    if c.branch is not None:
        for b in lg.branches:
            if b.branch == c.branch and b.t3 is not None:
                return b.t3.state_after
    return lg.deltas[-1].state_after


def _reference_problem(j: SemanticJudgment, c: CallRecord) -> str | None:
    """The request-only reference law: every id a judgment names was in its request."""
    p = j.proposal
    cited = set(_cited(j))
    if not cited <= set(c.citable_evidence_ids):
        return f"cites evidence outside its request: {sorted(cited - set(c.citable_evidence_ids))}"
    if (
        isinstance(p, BindToAddressProposal | AssertClaimProposal)
        and p.address_id not in c.known_address_ids
    ):
        return f"names address {p.address_id} outside its request"
    if isinstance(p, SupportsClaimProposal) and p.claim_id not in c.known_claim_ids:
        return f"supports claim {p.claim_id} outside its request"
    if isinstance(p, ConflictsWithProposal) and not {p.claim_a, p.claim_b} <= set(
        c.known_claim_ids
    ):
        return "names a conflicting claim outside its request"
    if isinstance(p, SupersedeProposal) and p.target_judgment_id not in c.known_claim_judgment_ids:
        return f"supersedes {p.target_judgment_id} outside its request"
    return None


def _check_accounting(run: RunRecord, out: _Findings) -> None:
    case = "PROPOSITION-ACCOUNTING"
    for lg in run.ledgers:
        for c in lg.calls:
            where = f"{lg.ledger} T{c.t}{'' if c.branch is None else '-' + c.branch}"
            if c.refusal_findings:
                for finding in c.refusal_findings:
                    out.add(case, "STRUCTURAL_REFUSAL", f"{where} call {c.call}: {finding}")
                continue
            if "ASSERT_CLAIM" not in c.allowed_kinds:
                continue
            if c.model_payload is None:
                out.add(case, "UNRECORDED_PAYLOAD", f"{where} call {c.call}")
                continue
            for finding in recompute_accounting(c):
                out.add(case, "ACCOUNTING_RECOMPUTED", f"{where}: {finding}")


def recompute_accounting(call: CallRecord) -> tuple[str, ...]:
    """The production accounting law (TARGET_SET) over what one call was shown and returned."""
    rendered = json.loads(call.rendered_request)
    sentences = {
        s["sentence_id"]: s["evidence_id"] for s in rendered.get("sentences_to_account", ())
    }
    payload = call.model_payload or {}
    drafts = [d for d in payload.get("drafts", ()) if "proposition_id" in d]
    findings = accounting_findings(
        sentence_evidence=sentences,
        propositions=[
            AccountedProposition.model_validate(p) for p in payload.get("propositions", ())
        ],
        non_operative=[
            NonOperativeSentence.model_validate(n) for n in payload.get("non_operative", ())
        ],
        dispositions=[
            PropositionDisposition(
                proposition_id=d["proposition_id"],
                kind=JudgmentKind(d["kind"]),
                evidence_ids=tuple(d.get("evidence_ids", ())),
                target_judgment_id=d.get("target_judgment_id"),
            )
            for d in drafts
        ],
        correction_law=CORRECTION_LAW_FROZEN,
    )
    asserted: dict[str, set[str]] = defaultdict(set)
    for d in drafts:
        if d["kind"] == "ASSERT_CLAIM" and "address_id" in d:
            asserted[d["proposition_id"]].add(d["address_id"])
    shown = {c["created_by_judgment_id"]: c["address_id"] for c in rendered.get("known_claims", ())}
    edges = [
        CorrectionEdge(
            proposition_id=d["proposition_id"],
            target_judgment_id=d.get("target_judgment_id"),
            proposition_address_ids=tuple(sorted(asserted.get(d["proposition_id"], ()))),
            target_address_id=shown.get(d.get("target_judgment_id")),
        )
        for d in drafts
        if d["kind"] == "SUPERSEDE" and asserted.get(d["proposition_id"])
    ]
    return (*findings, *correction_edge_findings(edges))


# ------------------------------------------------------------------ entry point


def evaluate(run: RunRecord) -> dict[str, CaseResult]:
    out = _Findings()
    _check_integrity(run, out)
    _check_accounting(run, out)
    completed = {lg.ledger: lg for lg in run.ledgers if lg.status == "COMPLETED"}
    ran = {lg.ledger: lg for lg in run.ledgers}
    for ledger in LEDGERS:
        if ledger not in completed:
            detail = f"ledger {ledger} did not complete"
            if ledger in ran:
                refused = [f for c in ran[ledger].calls for f in c.refusal_findings]
                detail = " | ".join(refused) or detail
            for c in CASES:
                if c.ledger == ledger:
                    out.add(c.id, "ABORTED", detail)
            out.add(f"LEDGER-{ledger}", "ABORTED", detail)
            continue
        lg = _Ledger(completed[ledger])
        _check_formation(lg, out)
        for item in ITEMS:
            if item.ledger == ledger and item.at in lg.states:
                _check_item(lg, item, out)
        for g in CORRECTIONS:
            if g.ledger == ledger:
                _check_correction(lg, g, out)
        _check_pending_sets(lg, out)
        _check_routing(lg, out)
        _check_counts(lg, out)
        _check_governance(lg, out)
        _check_facets(lg, out)
    for finding in source_coverage_findings():
        out.add("SOURCE-COVERAGE", "SOURCE_COVERAGE", finding)
    names = (
        *(c.id for c in CASES),
        *(f"LEDGER-{ledger}" for ledger in LEDGERS),
        *STRUCTURAL_CHECKS,
        "RUN-INTEGRITY",
    )
    unknown = set(out.by_case) - set(names)
    for name in sorted(unknown):
        out.add("RUN-INTEGRITY", "UNROUTED_FINDING", f"{name}: {out.by_case[name]}")
    return {
        name: CaseResult(
            case_id=name,
            passed=not out.by_case.get(name),
            findings=tuple(out.by_case.get(name, ())),
        )
        for name in names
    }


def split_tally(results: dict[str, CaseResult]) -> dict[str, int]:
    tally = {"OVER_SPLIT": 0, "UNDER_SPLIT": 0}
    for result in results.values():
        for finding in result.findings:
            tag = finding.split(":", 1)[0]
            if tag in tally:
                tally[tag] += 1
    return tally
