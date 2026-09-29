"""Deterministic structural evaluation of a v5 run (design §7). No wording is read.

Every check is computed from the frozen run (governed state, admissions, call records) and
the sealed expectations. Findings are tagged; a case passes only with no finding. Wording
questions belong to the independent semantic adjudication, never to this module.

Tags: ``OVER_SPLIT`` ``UNDER_SPLIT`` ``WRONG_BIND`` ``MISSING_BIND`` ``MISSING_EXTENSION``
``DUPLICATE_ASSERTION`` ``MISSING_SUPPORT`` ``CLAIM_COUNT`` ``ADDRESS_COUNT``
``MISSING_SUPERSEDE`` ``WRONG_SUPERSEDE_TARGET`` ``UNGOVERNED_SUPERSEDE``
``FABRICATED_SUPERSEDE`` ``UNEXPECTED_SUPERSEDE`` ``CONFLICT_INSTEAD_OF_CORRECTION``
``MISSING_CONFLICT`` ``UNEXPECTED_CONFLICT`` ``REJECTED_ADMISSION`` ``UNEXPECTED_CLAIM``
``ABORTED`` ``INTEGRITY``; and, run-wide, ``NON_CANONICAL_FACET`` ``BANNED_FACET``
``FACET_COLLISION`` ``MODEL_FACET`` (case ``CANONICAL-FACETS``) and the sealed source-coverage
findings (case ``SOURCE-COVERAGE``). Claim counts are the sealed ranges (design §6).
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Final

from foundry.domain.common import FrozenModel
from foundry.domain.proposition_accounting import (
    AccountedProposition,
    NonOperativeSentence,
    PropositionDisposition,
    accounting_findings,
)
from foundry.domain.semantic_identity import canonical_facet
from foundry.domain.semantic_judgment import (
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
from foundry.experiments.locus_validation_v5.corpus import DOCUMENTS
from foundry.experiments.locus_validation_v5.expectations import (
    ADDRESSES,
    BANNED_FACETS,
    CASES,
    EXPECTED_ADDRESS_COUNTS,
    EXPECTED_CONFLICTS,
    EXPECTED_SEPARATE,
    EXPECTED_SUPERSEDES,
    LARGE_KEYS,
    REVISED_ITEMS,
    SEED_ITEMS,
    STRUCTURAL_CHECKS,
    ItemExpectation,
    source_coverage_findings,
)
from foundry.experiments.locus_validation_v5.protocol import (
    CALLS_PER_DELTA,
    LEDGERS,
    MAX_FRONTIER_CALLS,
    MODEL_SEEDED,
    SCOPES,
    LedgerId,
)
from foundry.experiments.locus_validation_v5.recording import CallRecord
from foundry.experiments.locus_validation_v5.runner import LedgerRun, RunRecord

__all__ = ["CaseResult", "evaluate", "recompute_accounting", "split_tally"]

_ITEM_CASE: Final[dict[str, str]] = {
    **{f"{k}-T1": "C0-CORE-SEED" for k in ("PICKUP", "LABEL", "WEIGHT", "ATTEMPTS")},
    "LATE-T1": "C6-LATE-DELIVERY",
    "DAMAGE-T1": "U2-LATE-VS-DAMAGE",
    "SETTLEMENT-T1": "U3-COMPENSATION-VS-SETTLEMENT",
    "H-T1": "C7-C09-REGRESSION",
    "CANCEL-T1": "U1-CANCEL-VS-AUDIT",
    "AUDIT-T1": "U1-CANCEL-VS-AUDIT",
    **{f"{k}-T1": "C8-LARGE-WORLD" for k in LARGE_KEYS},
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
_ADDRESS_CASES: Final[dict[str, tuple[str | None, str]]] = {
    "PICKUP": ("C0-CORE-SEED", "C1-RESTATEMENT"),
    "LABEL": ("C0-CORE-SEED", "C2-EXTENSION"),
    "WEIGHT": ("C0-CORE-SEED", "C4-CORRECTION"),
    "ATTEMPTS": ("C0-CORE-SEED", "C3-NEW-CONCERN"),
    "LATE": ("C6-LATE-DELIVERY", "C6-LATE-DELIVERY"),
    "DAMAGE": ("U2-LATE-VS-DAMAGE", "U2-LATE-VS-DAMAGE"),
    "SETTLEMENT": ("U3-COMPENSATION-VS-SETTLEMENT", "U3-COMPENSATION-VS-SETTLEMENT"),
    "POD": (None, "C3-NEW-CONCERN"),
    "H": ("C7-C09-REGRESSION", "C7-C09-REGRESSION"),
    "CANCEL": ("U1-CANCEL-VS-AUDIT", "U1-CANCEL-VS-AUDIT"),
    "AUDIT": ("U1-CANCEL-VS-AUDIT", "U1-CANCEL-VS-AUDIT"),
    "SESSION": ("C5-EXISTING-CONFLICT", "C5-EXISTING-CONFLICT"),
    "CUSTOMER-REFUND": ("U4-CUSTOMER-VS-SUPPLIER-REFUND", "C8-LARGE-WORLD"),
    "SUPPLIER-OVERPAYMENT": ("U4-CUSTOMER-VS-SUPPLIER-REFUND", "C8-LARGE-WORLD"),
}
"""(case for the T1 count, case for the T2 count). Every other large-world address is C8."""
_GOVERNANCE_CASE: Final[dict[LedgerId, str]] = {
    "core": "C4-CORRECTION",
    "orion": "C7-C09-REGRESSION",
    "jobs": "U1-CANCEL-VS-AUDIT",
    "conflict": "C5-EXISTING-CONFLICT",
    "large": "C8-LARGE-WORLD",
}
_PENDING: Final = "REQUIRE_SECOND_LENS"


class CaseResult(FrozenModel):
    case_id: str
    passed: bool
    findings: tuple[str, ...]


class _Draft(FrozenModel):
    t: int
    call: int
    judgment: SemanticJudgment
    route: str
    applied: bool


def _cited(j: SemanticJudgment) -> tuple[str, ...]:
    p = j.proposal
    if isinstance(p, CreateAddressProposal | BindToAddressProposal):
        return p.candidate.evidence_ids
    if isinstance(p, AssertClaimProposal | SupportsClaimProposal):
        return p.evidence_ids
    return j.visible_evidence_ids


class _Ledger:
    """One completed ledger's structural surface."""

    def __init__(self, run: LedgerRun) -> None:
        self.run = run
        self.ledger: LedgerId = run.ledger
        self.t1: SemanticState = run.deltas[0].state_after.semantic
        self.t2: SemanticState = run.deltas[1].state_after.semantic
        drafts: list[_Draft] = []
        for delta in run.deltas:
            for call, batch in ((1, delta.call_1), (2, delta.call_2)):
                for d in batch:
                    drafts.append(
                        _Draft(
                            t=delta.t,
                            call=call,
                            judgment=self.t2.judgments[d.judgment_id],
                            route=d.route,
                            applied=d.judgment_id in self.t2.applied_judgment_ids,
                        )
                    )
        self.drafts = tuple(drafts)
        self.addresses: dict[str, str | None] = {}
        for expected in ADDRESSES:
            if expected.ledger != self.ledger:
                continue
            if expected.origin == "AUTHOR_SEED":
                self.addresses[expected.key] = run.seed_address_ids.get(expected.key)
            else:
                assert expected.created_from is not None
                t = 1 if expected.origin == "MODEL_T1" else 2
                self.addresses[expected.key] = self._created_by(expected.created_from, t)

    def _created_by(self, document: str, t: int) -> str | None:
        ev = DOCUMENTS[document].evidence_id
        created = [
            self._address_of_judgment(d.judgment.judgment_id)
            for d in self.select(t=t, kind=JudgmentKind.CREATE_ADDRESS, citing=ev)
            if d.applied
        ]
        return created[0] if len(created) == 1 else None

    def _address_of_judgment(self, jid: str) -> str | None:
        for address_id, address in self.t2.addresses.items():
            if address.created_by_judgment_id == jid:
                return address_id
        return None

    def select(
        self,
        *,
        t: int | None = None,
        call: int | None = None,
        kind: JudgmentKind | None = None,
        citing: str | None = None,
    ) -> tuple[_Draft, ...]:
        return tuple(
            d
            for d in self.drafts
            if (t is None or d.t == t)
            and (call is None or d.call == call)
            and (kind is None or d.judgment.proposal.kind is kind)
            and (citing is None or citing in _cited(d.judgment))
        )

    def state(self, t: int) -> SemanticState:
        return self.t1 if t == 1 else self.t2

    def live_claims(self, address_id: str | None, t: int) -> tuple[str, ...]:
        if address_id is None:
            return ()
        state = self.state(t)
        active = active_judgment_ids(state)
        return tuple(
            sorted(
                cid
                for cid, c in state.claims.items()
                if c.address_id == address_id and c.created_by_judgment_id in active
            )
        )

    def active_addresses(self, t: int) -> int:
        state = self.state(t)
        active = active_judgment_ids(state)
        scope = SCOPES[self.ledger]
        return sum(
            1
            for a in state.addresses.values()
            if a.created_by_judgment_id in active and scope in a.scope
        )

    def key_of(self, address_id: str | None) -> str | None:
        for key, value in self.addresses.items():
            if value == address_id and address_id is not None:
                return key
        return None

    def claim_address(self, claim_id: str) -> str | None:
        claim = self.t2.claims.get(claim_id)
        return None if claim is None else claim.address_id


class _Findings:
    def __init__(self) -> None:
        self.by_case: dict[str, list[str]] = defaultdict(list)

    def add(self, case: str, tag: str, detail: str) -> None:
        self.by_case[case].append(f"{tag}: {detail}")


def _check_item(lg: _Ledger, item: ItemExpectation, out: _Findings) -> None:
    case = _ITEM_CASE[item.document]
    ev = DOCUMENTS[item.document].evidence_id
    t = item.t
    binds = lg.select(t=t, call=1, kind=JudgmentKind.BIND_TO_ADDRESS, citing=ev)
    bound: dict[str | None, int] = defaultdict(int)
    for d in binds:
        proposal = d.judgment.proposal
        assert isinstance(proposal, BindToAddressProposal)
        bound[proposal.address_id] += 1
    expected_bind_ids = {lg.addresses.get(k) for k in item.binds}
    for key in item.binds:
        target = lg.addresses.get(key)
        if target is None or bound.get(target, 0) != 1:
            out.add(case, "MISSING_BIND", f"{item.document} bound {bound.get(target, 0)}x to {key}")
    for address_id, n in bound.items():
        if address_id not in expected_bind_ids:
            out.add(
                case,
                "WRONG_BIND",
                f"{item.document} bound {n}x to {lg.key_of(address_id) or address_id}",
            )
    creates = lg.select(t=t, call=1, kind=JudgmentKind.CREATE_ADDRESS, citing=ev)
    if len(creates) > item.creates:
        out.add(case, "OVER_SPLIT", f"{len(creates)} CREATE_ADDRESS cite {item.document}")
    elif len(creates) < item.creates:
        out.add(case, "UNDER_SPLIT", f"{len(creates)} CREATE_ADDRESS cite {item.document}")
    for d in creates:
        proposal = d.judgment.proposal
        assert isinstance(proposal, CreateAddressProposal)
        others = set(proposal.candidate.evidence_ids) - {ev}
        if others:
            out.add(
                case,
                "UNDER_SPLIT",
                f"one CREATE_ADDRESS cites {item.document} and {sorted(others)}",
            )

    new_ids = {d.judgment.judgment_id for d in lg.select(t=t)}
    state = lg.state(t)
    active = active_judgment_ids(state)
    new_at: dict[str, int] = defaultdict(int)
    for c in state.claims.values():
        if (
            c.created_by_judgment_id in new_ids
            and c.created_by_judgment_id in active
            and ev in c.evidence_ids
        ):
            new_at[c.address_id] += 1
    for key, (low, high) in item.new_claims.items():
        got = new_at.get(lg.addresses.get(key) or "", 0)
        if not low <= got <= high:
            tag = (
                "CLAIM_COUNT"
                if t == 1
                else ("MISSING_EXTENSION" if got < low else "DUPLICATE_ASSERTION")
            )
            out.add(
                case,
                tag,
                f"{got} new claims citing {item.document} at {key}, expected {low}-{high}",
            )
    expected_new = {lg.addresses.get(k) for k in item.new_claims}
    for address_id, n in new_at.items():
        if address_id in expected_new:
            continue
        where = lg.key_of(address_id)
        if address_id in expected_bind_ids:
            out.add(
                case, "DUPLICATE_ASSERTION", f"{n} new claims citing {item.document} at {where}"
            )
        elif where is not None:
            out.add(case, "WRONG_BIND", f"{n} new claims citing {item.document} at {where}")
        else:
            out.add(
                case,
                "UNEXPECTED_CLAIM",
                f"{n} new claims citing {item.document} at an unexpected address",
            )

    supports = lg.select(t=t, call=2, kind=JudgmentKind.SUPPORTS_CLAIM, citing=ev)
    supported: set[str] = set()
    for d in supports:
        proposal = d.judgment.proposal
        assert isinstance(proposal, SupportsClaimProposal)
        where = lg.claim_address(proposal.claim_id)
        if where not in expected_bind_ids:
            out.add(
                case,
                "WRONG_BIND",
                f"{item.document} supports a claim at {lg.key_of(where) or where}",
            )
        if d.applied:
            supported.add(proposal.claim_id)
    if item.must_support:
        (key,) = item.binds
        existing = [
            cid
            for cid in lg.live_claims(lg.addresses.get(key), t)
            if state.claims[cid].created_by_judgment_id not in new_ids
        ]
        missing = [cid for cid in existing if cid not in supported]
        if missing:
            out.add(case, "MISSING_SUPPORT", f"{item.document} does not support {missing}")


def _check_counts(lg: _Ledger, out: _Findings) -> None:
    for expected in ADDRESSES:
        if expected.ledger != lg.ledger:
            continue
        cases = _ADDRESS_CASES.get(expected.key, ("C8-LARGE-WORLD", "C8-LARGE-WORLD"))
        address_id = lg.addresses.get(expected.key)
        for t, want, case in (
            (1, expected.live_claims_after_t1, cases[0]),
            (2, expected.live_claims_after_t2, cases[1]),
        ):
            if want is None or case is None:
                continue
            got = len(lg.live_claims(address_id, t))
            if address_id is None or not want[0] <= got <= want[1]:
                out.add(
                    case,
                    "CLAIM_COUNT",
                    f"{expected.key} has {got} live claims after T{t}, "
                    f"expected {want[0]}-{want[1]}",
                )
    for pair in EXPECTED_SEPARATE:
        if pair.ledger != lg.ledger:
            continue
        a, b = lg.addresses.get(pair.a), lg.addresses.get(pair.b)
        if a is None or b is None or a == b:
            out.add(
                pair.case, "UNDER_SPLIT", f"{pair.a} and {pair.b} are not two distinct addresses"
            )
    ledger_case = f"LEDGER-{lg.ledger}"
    want_t1, want_t2 = EXPECTED_ADDRESS_COUNTS[lg.ledger]
    for t, count in ((1, want_t1), (2, want_t2)):
        got = lg.active_addresses(t)
        if got != count:
            out.add(
                ledger_case, "ADDRESS_COUNT", f"{got} active addresses after T{t}, expected {count}"
            )
    for d in lg.drafts:
        if d.route == "REJECT":
            out.add(
                ledger_case,
                "REJECTED_ADMISSION",
                f"T{d.t} call {d.call} {d.judgment.proposal.kind.value} rejected",
            )


def _check_governance(lg: _Ledger, out: _Findings) -> None:
    case = _GOVERNANCE_CASE[lg.ledger]
    expected_keys = EXPECTED_SUPERSEDES[lg.ledger]
    supersedes = lg.select(kind=JudgmentKind.SUPERSEDE)
    target_claims = {c.created_by_judgment_id: c.address_id for c in lg.t2.claims.values()}
    for d in supersedes:
        proposal = d.judgment.proposal
        assert isinstance(proposal, SupersedeProposal)
        where = target_claims.get(proposal.target_judgment_id)
        if not expected_keys:
            tag = "FABRICATED_SUPERSEDE" if lg.ledger == "conflict" else "UNEXPECTED_SUPERSEDE"
            out.add(case, tag, f"a SUPERSEDE targets a claim at {lg.key_of(where) or where}")
        elif where not in {lg.addresses.get(k) for k in expected_keys}:
            out.add(
                case,
                "WRONG_SUPERSEDE_TARGET",
                f"a SUPERSEDE targets a claim at {lg.key_of(where) or where}",
            )
        if d.applied or d.route != _PENDING:
            out.add(case, "UNGOVERNED_SUPERSEDE", f"a SUPERSEDE routed {d.route}")
    if expected_keys and len(supersedes) != len(expected_keys):
        tag = (
            "MISSING_SUPERSEDE" if len(supersedes) < len(expected_keys) else "UNEXPECTED_SUPERSEDE"
        )
        out.add(case, tag, f"{len(supersedes)} SUPERSEDE judgments, expected {len(expected_keys)}")

    wanted = {
        frozenset(lg.run.seed_claim_ids.get(k) for k in pair)
        for pair in EXPECTED_CONFLICTS[lg.ledger]
    }
    named: set[frozenset[str | None]] = set()
    for d in lg.select(kind=JudgmentKind.CONFLICTS_WITH):
        proposal = d.judgment.proposal
        assert isinstance(proposal, ConflictsWithProposal)
        named_pair: frozenset[str | None] = frozenset({proposal.claim_a, proposal.claim_b})
        if named_pair not in wanted:
            tag = "CONFLICT_INSTEAD_OF_CORRECTION" if expected_keys else "UNEXPECTED_CONFLICT"
            out.add(case, tag, "a CONFLICTS_WITH names claims the case does not hold in conflict")
            continue
        if d.applied or d.route != _PENDING:
            out.add(case, "UNGOVERNED_CONFLICT", f"a CONFLICTS_WITH routed {d.route}")
        named.add(named_pair)
    if wanted - named:
        out.add(
            case, "MISSING_CONFLICT", "the seeded incompatible claims were not held in conflict"
        )


def _payload_facets(value: object) -> int:
    """How many ``facet`` keys a recorded model payload carries, at any depth."""
    if isinstance(value, dict):
        return sum(1 for k in value if k == "facet") + sum(
            _payload_facets(v) for v in value.values()
        )
    if isinstance(value, list):
        return sum(_payload_facets(v) for v in value)
    return 0


def _check_facets(lg: _Ledger, out: _Findings) -> None:
    """Every address and every CREATE/BIND candidate carries ``canonical_facet(subject)``;
    no banned facet; facets pairwise distinct among a ledger's active addresses; no model
    payload carries a facet (design §7.3)."""
    case = "CANONICAL-FACETS"
    for t in (1, 2):
        state = lg.state(t)
        active = active_judgment_ids(state)
        seen: dict[str, str] = {}
        for address_id, a in sorted(state.addresses.items()):
            if a.facet != canonical_facet(a.subject):
                out.add(case, "NON_CANONICAL_FACET", f"{lg.ledger} T{t} {address_id}: {a.facet!r}")
            if a.facet in BANNED_FACETS:
                out.add(case, "BANNED_FACET", f"{lg.ledger} T{t} {address_id}: {a.facet!r}")
            if a.created_by_judgment_id not in active:
                continue
            if a.facet in seen:
                out.add(
                    case,
                    "FACET_COLLISION",
                    f"{lg.ledger} T{t} {seen[a.facet]} and {address_id}: {a.facet!r}",
                )
            seen[a.facet] = address_id
    for d in lg.drafts:
        p = d.judgment.proposal
        if isinstance(
            p, CreateAddressProposal | BindToAddressProposal
        ) and p.candidate.facet != canonical_facet(p.candidate.subject):
            out.add(
                case,
                "NON_CANONICAL_FACET",
                f"{lg.ledger} T{d.t} candidate {p.candidate.candidate_id}: {p.candidate.facet!r}",
            )
    for c in lg.run.calls:
        n = _payload_facets(c.model_payload)
        if n:
            out.add(case, "MODEL_FACET", f"{lg.ledger} T{c.t} call {c.call}: {n} facet field(s)")


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
        expected_calls = {1: 2, 2: 2} if lg.ledger in MODEL_SEEDED else {2: 2}
        per_t: dict[int, int] = defaultdict(int)
        for c in lg.calls:
            per_t[c.t] += 1
        if lg.status == "REFUSED":
            # A single-attempt refusal ends the ledger early: never more calls than the budget.
            if any(n > CALLS_PER_DELTA for n in per_t.values()):
                out.add(case, "INTEGRITY", f"ledger {lg.ledger} calls per delta {dict(per_t)}")
        elif dict(per_t) != expected_calls:
            out.add(case, "INTEGRITY", f"ledger {lg.ledger} calls per delta {dict(per_t)}")
        if lg.status == "COMPLETED":
            state = lg.deltas[-1].state_after.semantic
            for c in lg.calls:
                for jid in c.returned_judgment_ids:
                    j = state.judgments.get(jid)
                    if j is None:
                        continue
                    problem = _reference_problem(
                        j,
                        c.citable_evidence_ids,
                        c.known_address_ids,
                        c.known_claim_ids,
                        c.known_claim_judgment_ids,
                    )
                    if problem:
                        out.add(case, "INTEGRITY", f"{lg.ledger} T{c.t} call {c.call}: {problem}")
    refused = any(lg.status == "REFUSED" for lg in run.ledgers)
    if run.frontier_calls != MAX_FRONTIER_CALLS and run.status == "COMPLETED" and not refused:
        out.add(
            case,
            "INTEGRITY",
            f"{run.frontier_calls} frontier calls, expected {MAX_FRONTIER_CALLS}",
        )


def _reference_problem(
    j: SemanticJudgment,
    evidence: tuple[str, ...],
    addresses: tuple[str, ...],
    claims: tuple[str, ...],
    claim_judgments: tuple[str, ...],
) -> str | None:
    """The request-only reference law: every id a judgment names was in its request."""
    p = j.proposal
    cited = set(_cited(j))
    if not cited <= set(evidence):
        return f"cites evidence outside its request: {sorted(cited - set(evidence))}"
    if isinstance(p, BindToAddressProposal | AssertClaimProposal) and p.address_id not in addresses:
        return f"names address {p.address_id} outside its request"
    if isinstance(p, SupportsClaimProposal) and p.claim_id not in claims:
        return f"supports claim {p.claim_id} outside its request"
    if isinstance(p, ConflictsWithProposal) and not {p.claim_a, p.claim_b} <= set(claims):
        return "names a conflicting claim outside its request"
    if isinstance(p, SupersedeProposal) and p.target_judgment_id not in claim_judgments:
        return f"supersedes {p.target_judgment_id} outside its request"
    return None


def _refusals(lg: LedgerRun) -> list[str]:
    return [
        f"T{c.t} call {c.call}: {'; '.join(c.refusal_findings)}"
        for c in lg.calls
        if c.refusal_findings
    ]


def _check_accounting(run: RunRecord, out: _Findings) -> None:
    """Design §7.4: no call was refused, and every accepted claim-writing call's own payload
    accounts, by the production law recomputed from the recorded request and payload, for
    every sentence it was given and every proposition it listed."""
    case = "PROPOSITION-ACCOUNTING"
    for lg in run.ledgers:
        for c in lg.calls:
            if c.refusal_findings:
                for finding in c.refusal_findings:
                    out.add(
                        case,
                        "STRUCTURAL_REFUSAL",
                        f"{lg.ledger} T{c.t} call {c.call}: {finding}",
                    )
                continue
            if "ASSERT_CLAIM" not in c.allowed_kinds:
                continue
            if c.model_payload is None:
                out.add(case, "UNRECORDED_PAYLOAD", f"{lg.ledger} T{c.t} call {c.call}")
                continue
            for finding in recompute_accounting(c):
                out.add(case, "ACCOUNTING_RECOMPUTED", f"{lg.ledger} T{c.t}: {finding}")


def recompute_accounting(call: CallRecord) -> tuple[str, ...]:
    """The production accounting law over what one call was shown and returned."""
    rendered = json.loads(call.rendered_request)
    sentences = {
        s["sentence_id"]: s["evidence_id"] for s in rendered.get("sentences_to_account", ())
    }
    payload = call.model_payload or {}
    return accounting_findings(
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
            )
            for d in payload.get("drafts", ())
            if "proposition_id" in d
        ],
    )


def evaluate(run: RunRecord) -> dict[str, CaseResult]:
    out = _Findings()
    _check_integrity(run, out)
    _check_accounting(run, out)
    completed = {lg.ledger: lg for lg in run.ledgers if lg.status == "COMPLETED"}
    ran = {lg.ledger: lg for lg in run.ledgers}
    for ledger in LEDGERS:
        if ledger not in completed:
            refused = _refusals(ran[ledger]) if ledger in ran else []
            tag, detail = (
                ("STRUCTURAL_REFUSAL", " | ".join(refused))
                if refused
                else ("ABORTED", f"ledger {ledger} did not complete")
            )
            for c in CASES:
                if c.ledger == ledger:
                    out.add(c.id, tag, detail)
            out.add(f"LEDGER-{ledger}", tag, detail)
            continue
        lg = _Ledger(completed[ledger])
        for item in (*SEED_ITEMS, *REVISED_ITEMS):
            if item.ledger == ledger:
                _check_item(lg, item, out)
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
    return {
        name: CaseResult(
            case_id=name,
            passed=not out.by_case.get(name),
            findings=tuple(out.by_case.get(name, ())),
        )
        for name in names
    }


def split_tally(results: dict[str, CaseResult]) -> dict[str, int]:
    """How many OVER_SPLIT and UNDER_SPLIT findings the verdicts hold, across all cases."""
    tally = {"OVER_SPLIT": 0, "UNDER_SPLIT": 0}
    for result in results.values():
        for finding in result.findings:
            tag = finding.split(":", 1)[0]
            if tag in tally:
                tally[tag] += 1
    return tally
