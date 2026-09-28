"""Deterministic structural evaluation of a v2 run (design §7). No wording is read.

Every check is computed from the frozen run (governed state, admissions, call records) and
the sealed expectations. Findings are tagged; a case passes only with no finding. Wording
questions belong to the independent semantic adjudication, never to this module.

Tags: ``OVER_SPLIT`` ``UNDER_SPLIT`` ``WRONG_BIND`` ``MISSING_BIND`` ``MISSING_EXTENSION``
``DUPLICATE_ASSERTION`` ``MISSING_SUPPORT`` ``CLAIM_COUNT`` ``ADDRESS_COUNT``
``MISSING_SUPERSEDE`` ``WRONG_SUPERSEDE_TARGET`` ``UNGOVERNED_SUPERSEDE``
``FABRICATED_SUPERSEDE`` ``UNEXPECTED_SUPERSEDE`` ``CONFLICT_INSTEAD_OF_CORRECTION``
``MISSING_CONFLICT`` ``UNEXPECTED_CONFLICT`` ``REJECTED_ADMISSION`` ``UNEXPECTED_CLAIM``
``ABORTED`` ``INTEGRITY``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Final

from foundry.domain.common import FrozenModel
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
from foundry.experiments.locus_validation_v2.corpus import DOCUMENTS
from foundry.experiments.locus_validation_v2.expectations import (
    ADDRESSES,
    CASES,
    EXPECTED_ADDRESS_COUNTS,
    EXPECTED_CONFLICTS,
    EXPECTED_SUPERSEDES,
    REVISED_ITEMS,
    SEED_ITEMS,
    ItemExpectation,
)
from foundry.experiments.locus_validation_v2.protocol import (
    LEDGERS,
    MAX_FRONTIER_CALLS,
    MODEL_SEEDED,
    SCOPES,
    LedgerId,
)
from foundry.experiments.locus_validation_v2.runner import LedgerRun, RunRecord

__all__ = ["CaseResult", "evaluate"]

_ITEM_CASE: Final[dict[str, str]] = {
    **{i.document: "C0-CORE-SEED" for i in SEED_ITEMS if i.ledger == "core"},
    "H-T1": "C7-C09-REGRESSION",
    "PICKUP-T2": "C1-RESTATEMENT",
    "LABEL-T2": "C2-EXTENSION",
    "ATTEMPTS-T2": "C3-NEW-LOCUS",
    "WEIGHT-T2": "C4-CORRECTION",
    "LATE-NOTE-T2": "C6-NEARBY",
    "H-T9": "C7-C09-REGRESSION",
    "HANDBOOK-T2": "C5-EXISTING-CONFLICT",
    "FAQ-T2": "C5-EXISTING-CONFLICT",
    "REFUND-UPDATE-T2": "C8-LARGE-WORLD",
}
_ADDRESS_CASES: Final[dict[str, tuple[str | None, str]]] = {
    "PICKUP": ("C0-CORE-SEED", "C1-RESTATEMENT"),
    "LABEL": ("C0-CORE-SEED", "C2-EXTENSION"),
    "WEIGHT": ("C0-CORE-SEED", "C4-CORRECTION"),
    "ATTEMPTS": ("C0-CORE-SEED", "C3-NEW-LOCUS"),
    "INSURANCE": ("C0-CORE-SEED", "C6-NEARBY"),
    "LATE": ("C0-CORE-SEED", "C6-NEARBY"),
    "POD": (None, "C3-NEW-LOCUS"),
    "H": ("C7-C09-REGRESSION", "C7-C09-REGRESSION"),
    "SESSION": ("C5-EXISTING-CONFLICT", "C5-EXISTING-CONFLICT"),
}
"""(case for the T1 count, case for the T2 count). Every large-world address is C8."""
_GOVERNANCE_CASE: Final[dict[LedgerId, str]] = {
    "core": "C4-CORRECTION",
    "orion": "C7-C09-REGRESSION",
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
    for key, n in item.new_claims.items():
        got = new_at.get(lg.addresses.get(key) or "", 0)
        if got != n:
            tag = (
                "CLAIM_COUNT"
                if t == 1
                else ("MISSING_EXTENSION" if got < n else "DUPLICATE_ASSERTION")
            )
            out.add(case, tag, f"{got} new claims citing {item.document} at {key}, expected {n}")
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
            if address_id is None or got != want:
                out.add(
                    case,
                    "CLAIM_COUNT",
                    f"{expected.key} has {got} live claims after T{t}, expected {want}",
                )
    if lg.ledger == "core":
        insurance, late = lg.addresses.get("INSURANCE"), lg.addresses.get("LATE")
        if insurance is None or late is None or insurance == late:
            out.add("C6-NEARBY", "UNDER_SPLIT", "INSURANCE and LATE are not two distinct addresses")
    ledger_case = f"LEDGER-{lg.ledger}"
    want_t1, want_t2 = EXPECTED_ADDRESS_COUNTS[lg.ledger]
    for t, want in ((1, want_t1), (2, want_t2)):
        got = lg.active_addresses(t)
        if got != want:
            out.add(
                ledger_case, "ADDRESS_COUNT", f"{got} active addresses after T{t}, expected {want}"
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


def _check_integrity(run: RunRecord, out: _Findings) -> None:
    case = "RUN-INTEGRITY"
    if run.status != "COMPLETED":
        out.add(case, "ABORTED", f"run status {run.status}")
    present = {lg.ledger for lg in run.ledgers}
    for ledger in LEDGERS:
        if ledger not in present:
            out.add(case, "ABORTED", f"ledger {ledger} never ran")
    for lg in run.ledgers:
        if lg.status != "COMPLETED":
            out.add(case, "ABORTED", f"ledger {lg.ledger}: {lg.error}")
        if lg.replay_matches is not True:
            out.add(case, "INTEGRITY", f"ledger {lg.ledger} replay did not reproduce state")
        expected_calls = {1: 2, 2: 2} if lg.ledger in MODEL_SEEDED else {2: 2}
        per_t: dict[int, int] = defaultdict(int)
        for c in lg.calls:
            per_t[c.t] += 1
        if dict(per_t) != expected_calls:
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
    if run.frontier_calls != MAX_FRONTIER_CALLS and run.status == "COMPLETED":
        out.add(case, "INTEGRITY", f"{run.frontier_calls} frontier calls, expected 12")


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


def evaluate(run: RunRecord) -> dict[str, CaseResult]:
    out = _Findings()
    _check_integrity(run, out)
    completed = {lg.ledger: lg for lg in run.ledgers if lg.status == "COMPLETED"}
    for ledger in LEDGERS:
        if ledger not in completed:
            for c in CASES:
                if c.ledger == ledger or (ledger == "core" and c.id == "C0-CORE-SEED"):
                    out.add(c.id, "ABORTED", f"ledger {ledger} did not complete")
            out.add(f"LEDGER-{ledger}", "ABORTED", f"ledger {ledger} did not complete")
            continue
        lg = _Ledger(completed[ledger])
        for item in (*SEED_ITEMS, *REVISED_ITEMS):
            if item.ledger == ledger:
                _check_item(lg, item, out)
        _check_counts(lg, out)
        _check_governance(lg, out)
    names = (*(c.id for c in CASES), *(f"LEDGER-{ledger}" for ledger in LEDGERS), "RUN-INTEGRITY")
    return {
        name: CaseResult(
            case_id=name,
            passed=not out.by_case.get(name),
            findings=tuple(out.by_case.get(name, ())),
        )
        for name in names
    }
