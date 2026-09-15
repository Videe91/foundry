"""Deterministic case evaluation of spec §7.1 over a T3 ``LedgerRecord``.

Spec §6 (expected lifecycle state), §7.1 (the six assertion sets and the ten failure
tags) and §14 (a case's structural verdict is one input to its outcome; the semantic
questions of §7.2 are answered elsewhere, offline, never here).

Law of this module: it reads ids, kinds, routes, counts and structural values and
nothing else. It never reads a claim's predicate or value text, a candidate's
descriptors, a rationale or an evidence body; evidence-id and address-id equality is
the only comparison it makes, and the only admission reason it recognises is the
governor's structural duplicate refusal, by its fixed prefix and suffix. It selects no
outcome: it records, per case, whether the §7.1 assertion set holds and which tags name
the failure. It is a grading module -- it imports the hidden answer key for the case
table and the tag vocabulary -- and no request-path module may import it.

Inputs (T3 records only): ``deltas[i].stage_decisions`` attributes judgments to a
delta and a call; the judgment and admission events in ``ledger_events`` carry the
proposals (kinds, cited evidence ids, address ids, claim ids, target judgment ids) and
the latest route per judgment; the seed state is ``deltas[0].state_snapshot`` and the
revision state is ``final_state`` (or the revision snapshot when the final capture
failed). A failed delta records ``((), ())``: its judgments are then attributed from
the events -- a judgment recorded at or after the first ingest of a revised item
belongs to the revision delta, and its call is Call 1 for ``CREATE_ADDRESS`` /
``BIND_TO_ADDRESS`` and Call 2 otherwise.

Structural identities. ``Di-T1`` / ``Di'`` are ``corpus.evidence_id(document, 1 | 2)``.
``Xi`` is the address created by the single applied seed-delta ``CREATE_ADDRESS`` whose
candidate cites ``Di-T1`` (ambiguous or absent -> no ``Xi``). ``Ci`` (the seed claim)
is every claim at ``Xi`` created by a seed-delta judgment. ``X5`` is every active
in-scope address created by an applied revision ``CREATE_ADDRESS`` citing ``D2'``. A
"new claim citing ``Di'``" is a live claim at the address whose ``evidence_ids``
contains ``Di'`` and whose ``created_by_judgment_id`` is a revision-delta judgment.
"Cites" is membership of the proposal's own ``evidence_ids`` (candidate or claim);
``SUPERSEDE`` and ``CONFLICTS_WITH`` cite nothing and are attributed by target
address. In-scope addresses are those whose creating judgment is active and whose
scope names the ledger scope; live claims are those whose creating judgment is active.

A case whose delta did not run -- no delta record, or one in which no forwarded call
was answered (``requests == ()``) -- is ``structural_passed=None``, no tags, detail
``"delta not run"``; a ``NOT_RUN`` ledger yields six of them. A delta whose state
could not be captured is likewise ``None`` with detail ``"state not captured"``.
Otherwise ``structural_passed`` is ``False`` iff at least one tag applies, and
``detail`` lists every finding as ``<TAG>: <violated assertion>`` -- ids, kinds,
routes and counts only, never claim or evidence content -- joined with ``"; "`` in
tag order; a passing case's detail is ``"all assertions hold"``. A tag outside
``expectations.FAILURE_TAGS`` is a programming error and is refused, never dropped.

Tag rules (ids only; several may apply; tags are ordered as in
``expectations.FAILURE_TAGS``):

* ``OVER_SPLIT`` -- S01: more than 4 in-scope addresses after the seed, or a seed
  item cited by more than one applied ``CREATE_ADDRESS``. V01/V04/V05: any revision
  Call-1 ``CREATE_ADDRESS`` cites the case's revised item. V03: a revision
  ``CREATE_ADDRESS`` whose cited revised items are not exactly ``{D2'}``, more than
  one citing ``D2'``, or more than 5 in-scope addresses after the revision.
* ``UNDER_SPLIT`` -- S01: fewer than 4 in-scope addresses, or a seed item cited by no
  applied ``CREATE_ADDRESS``. V03: no ``X5``, fewer than 5 in-scope addresses, or an
  ``X5`` with no live claim citing ``D2'``.
* ``MISSING_EXTENSION`` -- the address's expected new ledger effect from the delta's
  item is absent: S01: an in-scope address with no live claim; V01/V02/V05: no new
  claim citing the revised item at ``Xi``; V04: no active ``SUPPORTS_CLAIM`` record
  of ``C3`` citing ``D3'``.
* ``DUPLICATE_ASSERTION`` -- V04: any revision ``ASSERT_CLAIM`` draft cites ``D3'``,
  or any admission in the run carries the governor's structural duplicate refusal.
  S01: a seed rejection carrying that refusal.
* ``MISSING_SUPERSEDE`` -- V05: no ``SUPERSEDE`` draft in the run; or the one
  targeting ``C4``'s judgment is not held ``REQUIRE_SECOND_LENS`` in
  ``pending_judgment_ids`` (and not applied).
* ``WRONG_SUPERSEDE_TARGET`` -- V01/V02/V04: any ``SUPERSEDE`` draft targets the
  creating judgment of a claim at ``Xi``. V05: any ``SUPERSEDE`` draft targets a
  judgment other than ``C4``'s. S01: any seed ``SUPERSEDE`` draft.
* ``CONFLICT_INSTEAD_OF_CORRECTION`` -- V05: any ``CONFLICTS_WITH`` draft in the run.
  S01: any seed ``CONFLICTS_WITH`` draft.
* ``UNGOVERNED_SUPERSEDE`` -- a non-human ``SUPERSEDE`` judgment present in
  ``applied_judgment_ids``: on the case of its target's address (S01 for a seed
  supersede; V05 when unattributable); also on a case whose seed claim is no longer
  live.
* ``WRONG_BIND`` -- V01/V02/V04/V05: no revision Call-1 ``BIND_TO_ADDRESS`` citing
  the revised item targets ``Xi``, or one targets another address. S01: any seed
  ``BIND_TO_ADDRESS`` draft.
* ``EXTRA_DRAFT`` -- V01/V02/V04/V05: more than one Call-1 ``BIND_TO_ADDRESS`` cites
  the revised item; more than one new claim citing it at ``Xi``; a live claim at
  ``Xi`` that is neither a seed claim nor such a new claim; a Call-2 draft citing it
  whose kind is outside the item's expected set (V01/V02: ``ASSERT_CLAIM``,
  ``SUPPORTS_CLAIM``; V04: ``SUPPORTS_CLAIM``, ``ASSERT_CLAIM`` -- the latter is
  ``DUPLICATE_ASSERTION``; V05: ``ASSERT_CLAIM``). V03: more than one live claim at
  an ``X5``, a live claim at an ``X5`` not citing ``D2'``, or a live claim citing
  ``D2'`` at an address other than ``X2`` and ``X5``. V05: more than one
  ``SUPERSEDE`` targeting ``C4``'s judgment, or any human-fingerprint judgment or
  authority record in the ledger (``human_authorizations != 0``). S01: an in-scope
  address with more than one live claim, or a seed rejection that is not a
  duplicate refusal.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from foundry.domain.common import FrozenModel
from foundry.domain.events import (
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    SemanticObjectPayload,
    StoredEvent,
)
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_identity import SemanticClaim
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import CurrentSemanticView, active_judgment_ids
from foundry.experiments.locus_validation.corpus import DOCUMENTS, Ledger, evidence_id
from foundry.experiments.locus_validation.expectations import CASE_IDS, CASES, FAILURE_TAGS
from foundry.experiments.locus_validation.runner import DeltaRecord, LedgerRecord, RunResult

__all__ = ["CaseResult", "evaluate_ledger", "evaluate_run"]

_OVER_SPLIT: Final = "OVER_SPLIT"
_UNDER_SPLIT: Final = "UNDER_SPLIT"
_MISSING_EXTENSION: Final = "MISSING_EXTENSION"
_DUPLICATE_ASSERTION: Final = "DUPLICATE_ASSERTION"
_MISSING_SUPERSEDE: Final = "MISSING_SUPERSEDE"
_WRONG_SUPERSEDE_TARGET: Final = "WRONG_SUPERSEDE_TARGET"
_CONFLICT_INSTEAD_OF_CORRECTION: Final = "CONFLICT_INSTEAD_OF_CORRECTION"
_UNGOVERNED_SUPERSEDE: Final = "UNGOVERNED_SUPERSEDE"
_WRONG_BIND: Final = "WRONG_BIND"
_EXTRA_DRAFT: Final = "EXTRA_DRAFT"

_SEED_T: Final = 1
_REVISION_T: Final = 2
_SEED_ADDRESS_COUNT: Final = 4
_REVISION_ADDRESS_COUNT: Final = 5
_CALL_ONE_KINDS: Final[frozenset[JudgmentKind]] = frozenset(
    {JudgmentKind.CREATE_ADDRESS, JudgmentKind.BIND_TO_ADDRESS}
)
_EXTENSION_CALL_TWO_KINDS: Final[frozenset[JudgmentKind]] = frozenset(
    {JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPPORTS_CLAIM}
)
_CORRECTION_CALL_TWO_KINDS: Final[frozenset[JudgmentKind]] = frozenset({JudgmentKind.ASSERT_CLAIM})
# The governor's structural duplicate refusal, recognised by its fixed frame only.
_DUPLICATE_PREFIX: Final = "STRUCTURAL: claim "
_DUPLICATE_SUFFIX: Final = "; support it instead"
_NOT_RUN_DETAIL: Final = "delta not run"
_NO_STATE_DETAIL: Final = "state not captured"
_HOLDS_DETAIL: Final = "all assertions hold"
_TAG_ORDER: Final[dict[str, int]] = {tag: index for index, tag in enumerate(FAILURE_TAGS)}


class CaseResult(FrozenModel):
    """One case of one ledger: the structural verdict, its tags and ids-only evidence."""

    ledger: Ledger
    case_id: str
    structural_passed: bool | None
    """``None`` when the ledger did not run the case's delta."""
    tags: tuple[str, ...]
    detail: str
    evidence: dict[str, Any]


# --------------------------------------------------------------------------- drafts


@dataclass(frozen=True, slots=True)
class _Draft:
    judgment: SemanticJudgment
    t: int
    call: int
    route: AdmissionRoute | None
    reasons: tuple[str, ...]

    @property
    def judgment_id(self) -> str:
        return self.judgment.judgment_id

    @property
    def kind(self) -> JudgmentKind:
        return self.judgment.kind

    @property
    def cited(self) -> frozenset[str]:
        proposal = self.judgment.proposal
        if isinstance(proposal, CreateAddressProposal | BindToAddressProposal):
            return frozenset(proposal.candidate.evidence_ids)
        if isinstance(proposal, AssertClaimProposal | SupportsClaimProposal):
            return frozenset(proposal.evidence_ids)
        return frozenset()

    @property
    def bound_address_id(self) -> str | None:
        proposal = self.judgment.proposal
        return proposal.address_id if isinstance(proposal, BindToAddressProposal) else None

    @property
    def supersede_target(self) -> str | None:
        proposal = self.judgment.proposal
        return proposal.target_judgment_id if isinstance(proposal, SupersedeProposal) else None

    @property
    def rejected(self) -> bool:
        return self.route is AdmissionRoute.REJECT

    @property
    def duplicate_refusal(self) -> bool:
        return any(_is_duplicate_reason(reason) for reason in self.reasons)


def _is_duplicate_reason(reason: str) -> bool:
    return reason.startswith(_DUPLICATE_PREFIX) and reason.endswith(_DUPLICATE_SUFFIX)


def _revision_boundary(events: Iterable[StoredEvent], revised_ids: frozenset[str]) -> int | None:
    """Sequence of the first ingest of a revised item; ``None`` when none was ingested."""
    for stored in events:
        payload = stored.event.payload
        if (
            stored.event.event_type is EventType.EVIDENCE_INGESTED
            and isinstance(payload, EvidencePayload)
            and payload.evidence.evidence_id in revised_ids
        ):
            return stored.sequence
    return None


def _drafts(record: LedgerRecord, revised_ids: frozenset[str]) -> tuple[_Draft, ...]:
    """Every recorded judgment with its latest route, attributed to a delta and a call:
    by ``stage_decisions`` where the delta recorded them, else by the ledger events."""
    attributed: dict[str, tuple[int, int]] = {}
    for delta in record.deltas:
        for call, decisions in enumerate(delta.stage_decisions, start=1):
            for decision in decisions:
                attributed[decision.judgment_id] = (delta.t, call)
    boundary = _revision_boundary(record.ledger_events, revised_ids)

    judgments: list[tuple[int, SemanticJudgment]] = []
    admissions: dict[str, SemanticAdmissionPayload] = {}
    for stored in record.ledger_events:
        payload = stored.event.payload
        if isinstance(payload, SemanticJudgmentPayload):
            judgments.append((stored.sequence, payload.judgment))
        elif isinstance(payload, SemanticAdmissionPayload):
            admissions[payload.judgment_id] = payload

    drafts: list[_Draft] = []
    for sequence, judgment in judgments:
        if judgment.judgment_id in attributed:
            t, call = attributed[judgment.judgment_id]
        else:
            t = _REVISION_T if boundary is not None and sequence >= boundary else _SEED_T
            call = 1 if judgment.kind in _CALL_ONE_KINDS else 2
        admission = admissions.get(judgment.judgment_id)
        drafts.append(
            _Draft(
                judgment=judgment,
                t=t,
                call=call,
                route=None if admission is None else admission.route,
                reasons=() if admission is None else admission.reasons,
            )
        )
    return tuple(drafts)


def _human_authorizations(events: Iterable[StoredEvent]) -> int:
    total = 0
    for stored in events:
        payload = stored.event.payload
        human_judgment = (
            isinstance(payload, SemanticJudgmentPayload) and payload.judgment.reasoner.is_human
        )
        authority_record = (
            isinstance(payload, SemanticObjectPayload)
            and payload.object.kind is SemanticKind.AUTHORITY_RECORD
        )
        if human_judgment or authority_record:
            total += 1
    return total


# --------------------------------------------------------------------------- context


class _Context:
    """The structural surface of one ledger at one delta's state: drafts, active ids,
    in-scope addresses, live claims and the seed identities ``Xi`` / ``Ci``."""

    def __init__(
        self,
        record: LedgerRecord,
        drafts: tuple[_Draft, ...],
        state: SemanticState,
        view: CurrentSemanticView,
    ) -> None:
        self.ledger = record.ledger
        self.scope = record.scope
        self.documents = DOCUMENTS[record.ledger]
        self.drafts = drafts
        self.state = state
        self.view = view
        self.active = active_judgment_ids(state)
        self.applied = frozenset(state.applied_judgment_ids)
        self.seed_ids = {doc: evidence_id(doc, 1) for doc in self.documents}
        self.revised_ids = {doc: evidence_id(doc, 2) for doc in self.documents}
        self.in_scope_addresses = tuple(
            sorted(
                address_id
                for address_id, address in state.addresses.items()
                if address.created_by_judgment_id in self.active and self.scope in address.scope
            )
        )
        self.address_by_judgment = {
            address.created_by_judgment_id: address_id
            for address_id, address in state.addresses.items()
        }
        self.human_authorizations = _human_authorizations(record.ledger_events)

    # --- selections ---------------------------------------------------------------

    def select(
        self,
        *,
        t: int | None = None,
        call: int | None = None,
        kind: JudgmentKind | None = None,
        citing: str | None = None,
    ) -> tuple[_Draft, ...]:
        return tuple(
            draft
            for draft in self.drafts
            if (t is None or draft.t == t)
            and (call is None or draft.call == call)
            and (kind is None or draft.kind is kind)
            and (citing is None or citing in draft.cited)
        )

    def is_applied(self, draft: _Draft) -> bool:
        return draft.judgment_id in self.applied

    def judgment_ids(self, t: int) -> frozenset[str]:
        return frozenset(draft.judgment_id for draft in self.drafts if draft.t == t)

    def claims_at(self, address_id: str | None) -> tuple[SemanticClaim, ...]:
        """Every claim ever applied at ``address_id`` (live or not), by claim id."""
        if address_id is None:
            return ()
        return tuple(
            claim
            for _, claim in sorted(self.state.claims.items())
            if claim.address_id == address_id
        )

    def live_claims_at(self, address_id: str | None) -> tuple[SemanticClaim, ...]:
        return tuple(
            claim
            for claim in self.claims_at(address_id)
            if claim.created_by_judgment_id in self.active
        )

    def seed_address(self, document: str) -> str | None:
        """``Xi``: the address of the single applied seed ``CREATE_ADDRESS`` citing ``Di-T1``."""
        created = [
            self.address_by_judgment[draft.judgment_id]
            for draft in self.select(
                t=_SEED_T, kind=JudgmentKind.CREATE_ADDRESS, citing=self.seed_ids[document]
            )
            if self.is_applied(draft) and draft.judgment_id in self.address_by_judgment
        ]
        return created[0] if len(created) == 1 else None

    def seed_claims(self, address_id: str | None) -> tuple[SemanticClaim, ...]:
        """``Ci``: every claim at ``Xi`` created by a seed-delta judgment."""
        seed_judgments = self.judgment_ids(_SEED_T)
        return tuple(
            claim
            for claim in self.claims_at(address_id)
            if claim.created_by_judgment_id in seed_judgments
        )

    def target_address(self, draft: _Draft) -> str | None:
        """The address of the claim whose creating judgment a ``SUPERSEDE`` targets."""
        target = draft.supersede_target
        if target is None:
            return None
        for claim in self.state.claims.values():
            if claim.created_by_judgment_id == target:
                return claim.address_id
        return None

    def ungoverned_supersedes(self, t: int | None = None) -> tuple[_Draft, ...]:
        """Non-human ``SUPERSEDE`` judgments present in ``applied_judgment_ids``."""
        return tuple(
            draft
            for draft in self.select(t=t, kind=JudgmentKind.SUPERSEDE)
            if self.is_applied(draft) and not draft.judgment.reasoner.is_human
        )


# --------------------------------------------------------------------------- cases


def _ids(claims: Iterable[SemanticClaim]) -> list[str]:
    return [claim.claim_id for claim in claims]


def _judgment_ids(drafts: Iterable[_Draft]) -> list[str]:
    return [draft.judgment_id for draft in drafts]


def _listed(ids: Iterable[str]) -> str:
    """Ids joined for a detail; ``"none"`` when there are none."""
    joined = ", ".join(ids)
    return joined if joined else "none"


class _Findings:
    """The violated assertions of one case, each under its tag; tags are unique and
    ordered as in ``FAILURE_TAGS``, findings keep their insertion order within a tag."""

    def __init__(self) -> None:
        self._items: list[tuple[str, str]] = []

    def add(self, tag: str, assertion: str) -> None:
        if tag not in _TAG_ORDER:
            raise ValueError(f"unknown failure tag {tag!r}")
        self._items.append((tag, assertion))

    def __bool__(self) -> bool:
        return bool(self._items)

    @property
    def tags(self) -> tuple[str, ...]:
        present = {tag for tag, _ in self._items}
        return tuple(tag for tag in FAILURE_TAGS if tag in present)

    def detail(self) -> str:
        if not self._items:
            return _HOLDS_DETAIL
        ordered = sorted(enumerate(self._items), key=lambda item: (_TAG_ORDER[item[1][0]], item[0]))
        return "; ".join(f"{tag}: {assertion}" for _, (tag, assertion) in ordered)


def _seed_case(ctx: _Context) -> tuple[_Findings, dict[str, Any]]:
    """S01 (spec §7.1): 4 in-scope addresses, one live claim each, the 4 creates cite
    distinct items, 0 binds, 0 supersede/conflict, 0 rejected admissions."""
    found = _Findings()
    addresses = ctx.in_scope_addresses
    creates = ctx.select(t=_SEED_T, kind=JudgmentKind.CREATE_ADDRESS)
    applied_creates = tuple(draft for draft in creates if ctx.is_applied(draft))
    binds = ctx.select(t=_SEED_T, kind=JudgmentKind.BIND_TO_ADDRESS)
    supersedes = ctx.select(t=_SEED_T, kind=JudgmentKind.SUPERSEDE)
    conflicts = ctx.select(t=_SEED_T, kind=JudgmentKind.CONFLICTS_WITH)
    rejected = tuple(draft for draft in ctx.select(t=_SEED_T) if draft.rejected)
    ungoverned = ctx.ungoverned_supersedes(_SEED_T)

    count_text = (
        f"in-scope addresses after the seed = {len(addresses)} ({_listed(addresses)}), "
        f"expected {_SEED_ADDRESS_COUNT}"
    )
    if len(addresses) > _SEED_ADDRESS_COUNT:
        found.add(_OVER_SPLIT, count_text)
    if len(addresses) < _SEED_ADDRESS_COUNT:
        found.add(_UNDER_SPLIT, count_text)
    for document in ctx.documents:
        seed_id = ctx.seed_ids[document]
        citing = tuple(draft for draft in applied_creates if seed_id in draft.cited)
        text = (
            f"applied CREATE_ADDRESS drafts citing {seed_id} = {len(citing)} "
            f"({_listed(_judgment_ids(citing))}), expected 1"
        )
        if not citing:
            found.add(_UNDER_SPLIT, text)
        if len(citing) > 1:
            found.add(_OVER_SPLIT, text)
    for address_id in addresses:
        live = ctx.live_claims_at(address_id)
        if not live:
            found.add(_MISSING_EXTENSION, f"live claims at {address_id} = 0, expected 1")
        if len(live) > 1:
            found.add(
                _EXTRA_DRAFT,
                f"live claims at {address_id} = {len(live)} ({_listed(_ids(live))}), expected 1",
            )
    if binds:
        found.add(
            _WRONG_BIND,
            f"seed BIND_TO_ADDRESS drafts = {len(binds)} ({_listed(_judgment_ids(binds))}), "
            f"expected 0",
        )
    if supersedes:
        found.add(
            _WRONG_SUPERSEDE_TARGET,
            f"seed SUPERSEDE drafts = {len(supersedes)} ({_listed(_judgment_ids(supersedes))}), "
            f"expected 0",
        )
    for draft in ungoverned:
        found.add(_UNGOVERNED_SUPERSEDE, _applied_supersede_text(draft))
    if conflicts:
        found.add(
            _CONFLICT_INSTEAD_OF_CORRECTION,
            f"seed CONFLICTS_WITH drafts = {len(conflicts)} "
            f"({_listed(_judgment_ids(conflicts))}), expected 0",
        )
    for draft in rejected:
        if draft.duplicate_refusal:
            found.add(
                _DUPLICATE_ASSERTION,
                f"{draft.judgment_id} was rejected with the structural duplicate refusal",
            )
        else:
            found.add(_EXTRA_DRAFT, f"{draft.judgment_id} was rejected, expected 0 rejections")

    evidence: dict[str, Any] = {
        "address_count": len(addresses),
        "address_ids": list(addresses),
        "live_claim_ids": [
            claim_id
            for address_id in addresses
            for claim_id in _ids(ctx.live_claims_at(address_id))
        ],
        "create_count": len(creates),
        "applied_create_count": len(applied_creates),
        "bind_count": len(binds),
        "supersede_count": len(supersedes),
        "conflict_count": len(conflicts),
        "rejected_count": len(rejected),
        "ungoverned_supersede_judgment_ids": _judgment_ids(ungoverned),
    }
    return found, evidence


def _applied_supersede_text(draft: _Draft) -> str:
    return f"SUPERSEDE {draft.judgment_id} is in applied_judgment_ids, expected never applied"


def _revised_item_shape(
    ctx: _Context,
    document: str,
    *,
    expected_new_claims: int,
    call_two_kinds: frozenset[JudgmentKind],
    creates_are_over_split: bool,
) -> tuple[_Findings, dict[str, Any], tuple[_Draft, ...]]:
    """The shape shared by V01, V02, V04 and V05 for one revised item ``Di'`` at its seed
    address ``Xi``: the Call-1 bind, the live claims at ``Xi``, and the Call-2 kinds
    citing the item. Also returns the ``SUPERSEDE`` drafts targeting ``Xi``'s claims,
    which the caller judges (a wrong target for V01/V02/V04; V05 judges its own)."""
    found = _Findings()
    revised = ctx.revised_ids[document]
    address_id = ctx.seed_address(document)
    call_one = ctx.select(t=_REVISION_T, call=1, citing=revised)
    binds = tuple(draft for draft in call_one if draft.kind is JudgmentKind.BIND_TO_ADDRESS)
    creates = tuple(draft for draft in call_one if draft.kind is JudgmentKind.CREATE_ADDRESS)
    bound = [draft.bound_address_id for draft in binds]
    if address_id is None:
        found.add(
            _WRONG_BIND,
            f"no single applied seed CREATE_ADDRESS cites {ctx.seed_ids[document]}: "
            f"{revised} has no T1 address to bind to",
        )
    else:
        for draft in binds:
            if draft.bound_address_id != address_id:
                found.add(
                    _WRONG_BIND,
                    f"{draft.judgment_id} binds {revised} to {draft.bound_address_id}, "
                    f"expected {address_id}",
                )
        if address_id not in bound:
            found.add(
                _WRONG_BIND, f"no call-1 BIND_TO_ADDRESS citing {revised} targets {address_id}"
            )
    if len(binds) > 1:
        found.add(
            _EXTRA_DRAFT,
            f"call-1 BIND_TO_ADDRESS drafts citing {revised} = {len(binds)} "
            f"({_listed(_judgment_ids(binds))}), expected 1",
        )
    if creates_are_over_split and creates:
        found.add(
            _OVER_SPLIT,
            f"call-1 CREATE_ADDRESS drafts citing {revised} = {len(creates)} "
            f"({_listed(_judgment_ids(creates))}), expected 0",
        )

    seed = ctx.seed_claims(address_id)
    live = ctx.live_claims_at(address_id)
    live_ids = frozenset(_ids(live))
    revision_judgments = ctx.judgment_ids(_REVISION_T)
    new = tuple(
        claim
        for claim in live
        if revised in claim.evidence_ids and claim.created_by_judgment_id in revision_judgments
    )
    seed_ids = frozenset(_ids(seed))
    new_ids = frozenset(_ids(new))
    for claim_id in sorted(seed_ids - live_ids):
        found.add(_UNGOVERNED_SUPERSEDE, f"seed claim {claim_id} at {address_id} is no longer live")
    new_text = (
        f"new live claims citing {revised} at {address_id} = {len(new)} "
        f"({_listed(sorted(new_ids))}), expected {expected_new_claims}"
    )
    if expected_new_claims == 0 and new:
        found.add(_DUPLICATE_ASSERTION, new_text)
    if expected_new_claims > 0 and not new:
        found.add(_MISSING_EXTENSION, f"no live claim at {address_id} cites {revised}")
    if len(new) > expected_new_claims:
        found.add(_EXTRA_DRAFT, new_text)
    others = sorted(live_ids - seed_ids - new_ids)
    if others:
        found.add(
            _EXTRA_DRAFT,
            f"live claims at {address_id} beyond the seed claim and the new claim citing "
            f"{revised}: {_listed(others)}",
        )

    claim_judgments = frozenset(claim.created_by_judgment_id for claim in ctx.claims_at(address_id))
    supersedes_here = tuple(
        draft
        for draft in ctx.select(kind=JudgmentKind.SUPERSEDE)
        if draft.supersede_target in claim_judgments
    )
    ungoverned = tuple(
        draft for draft in ctx.ungoverned_supersedes() if ctx.target_address(draft) == address_id
    )
    for draft in ungoverned:
        found.add(_UNGOVERNED_SUPERSEDE, _applied_supersede_text(draft))
    call_two = ctx.select(t=_REVISION_T, call=2, citing=revised)
    expected_kinds = _listed(sorted(kind.value for kind in call_two_kinds))
    for draft in call_two:
        if draft.kind not in call_two_kinds:
            found.add(
                _EXTRA_DRAFT,
                f"call-2 {draft.kind.value} draft {draft.judgment_id} cites {revised}, "
                f"expected kinds {expected_kinds}",
            )

    evidence: dict[str, Any] = {
        "address_id": address_id,
        "call_one_draft_count": len(call_one),
        "bound_address_ids": [b for b in bound if b is not None],
        "create_judgment_ids": _judgment_ids(creates),
        "seed_claim_ids": sorted(seed_ids),
        "live_claim_ids": sorted(live_ids),
        "new_claim_ids": sorted(new_ids),
        "supersede_judgment_ids_targeting_address": _judgment_ids(supersedes_here),
        "ungoverned_supersede_judgment_ids": _judgment_ids(ungoverned),
        "call_two_kinds": sorted(draft.kind.value for draft in call_two),
        "address_count": len(ctx.in_scope_addresses),
    }
    return found, evidence, supersedes_here


def _wrong_targets(
    found: _Findings, supersedes_here: Iterable[_Draft], address_id: str | None
) -> None:
    for draft in supersedes_here:
        found.add(
            _WRONG_SUPERSEDE_TARGET,
            f"SUPERSEDE {draft.judgment_id} targets {draft.supersede_target}, the "
            f"created_by_judgment_id of a claim at {address_id}",
        )


def _extension_case(
    ctx: _Context, document: str, *, creates_are_over_split: bool
) -> tuple[_Findings, dict[str, Any]]:
    """V01 / V02: the bind to ``Xi``, one new claim citing ``Di'``, no supersede of
    ``Xi``'s claims; for V01 also no creation from ``D1'`` (the ``D2'`` creation is
    V03's assertion, not V02's)."""
    found, evidence, supersedes_here = _revised_item_shape(
        ctx,
        document,
        expected_new_claims=1,
        call_two_kinds=_EXTENSION_CALL_TWO_KINDS,
        creates_are_over_split=creates_are_over_split,
    )
    _wrong_targets(found, supersedes_here, evidence["address_id"])
    return found, evidence


def _distinct_locus_case(ctx: _Context, document: str) -> tuple[_Findings, dict[str, Any]]:
    """V03: exactly one revision ``CREATE_ADDRESS`` and it cites ``D2'``; 5 addresses; the
    created address has exactly one live claim citing ``D2'``; no claim citing ``D2'``
    elsewhere than ``X2`` and ``X5``."""
    found = _Findings()
    revised = ctx.revised_ids[document]
    revised_all = frozenset(ctx.revised_ids.values())
    x2 = ctx.seed_address(document)
    creates = ctx.select(t=_REVISION_T, kind=JudgmentKind.CREATE_ADDRESS)
    citing = tuple(draft for draft in creates if revised in draft.cited)
    for draft in creates:
        cited_revised = sorted(draft.cited & revised_all)
        if cited_revised != [revised]:
            found.add(
                _OVER_SPLIT,
                f"call-1 CREATE_ADDRESS {draft.judgment_id} cites revised items "
                f"{_listed(cited_revised)}, expected only {revised}",
            )
    if len(citing) > 1:
        found.add(
            _OVER_SPLIT,
            f"call-1 CREATE_ADDRESS drafts citing {revised} = {len(citing)} "
            f"({_listed(_judgment_ids(citing))}), expected 1",
        )
    created = [
        ctx.address_by_judgment[draft.judgment_id]
        for draft in citing
        if ctx.is_applied(draft)
        and ctx.address_by_judgment.get(draft.judgment_id) in ctx.in_scope_addresses
    ]
    if not created:
        found.add(_UNDER_SPLIT, f"applied in-scope CREATE_ADDRESS citing {revised} = 0, expected 1")
    count_text = (
        f"in-scope addresses after the revision = {len(ctx.in_scope_addresses)} "
        f"({_listed(ctx.in_scope_addresses)}), expected {_REVISION_ADDRESS_COUNT}"
    )
    if len(ctx.in_scope_addresses) > _REVISION_ADDRESS_COUNT:
        found.add(_OVER_SPLIT, count_text)
    if len(ctx.in_scope_addresses) < _REVISION_ADDRESS_COUNT:
        found.add(_UNDER_SPLIT, count_text)
    created_claims: list[str] = []
    for x5 in created:
        live = ctx.live_claims_at(x5)
        cited = tuple(claim for claim in live if revised in claim.evidence_ids)
        created_claims += _ids(cited)
        if not cited:
            found.add(_UNDER_SPLIT, f"live claims at {x5} citing {revised} = 0, expected 1")
        if len(cited) > 1 or len(live) > len(cited):
            found.add(
                _EXTRA_DRAFT,
                f"live claims at {x5} = {len(live)} ({_listed(_ids(live))}), expected exactly "
                f"1 citing {revised}",
            )
    allowed = frozenset(created) | ({x2} if x2 is not None else frozenset())
    elsewhere = [
        claim.claim_id
        for address_id in ctx.in_scope_addresses
        if address_id not in allowed
        for claim in ctx.live_claims_at(address_id)
        if revised in claim.evidence_ids
    ]
    if elsewhere:
        found.add(
            _EXTRA_DRAFT,
            f"live claims citing {revised} at addresses other than {_listed(sorted(allowed))}: "
            f"{_listed(elsewhere)}",
        )
    evidence: dict[str, Any] = {
        "seed_address_id": x2,
        "create_count": len(creates),
        "create_judgment_ids": _judgment_ids(creates),
        "created_address_ids": created,
        "created_claim_ids": created_claims,
        "claim_ids_citing_item_elsewhere": elsewhere,
        "address_count": len(ctx.in_scope_addresses),
    }
    return found, evidence


def _restatement_case(ctx: _Context, document: str) -> tuple[_Findings, dict[str, Any]]:
    """V04: the bind to ``X3``; ``X3`` live claims == the seed claim; ≥ 1 active
    ``SUPPORTS_CLAIM`` of it citing ``D3'``; 0 ``ASSERT_CLAIM`` citing ``D3'``; 0
    structural duplicate refusals in the run."""
    found, evidence, supersedes_here = _revised_item_shape(
        ctx,
        document,
        expected_new_claims=0,
        call_two_kinds=_EXTENSION_CALL_TWO_KINDS,
        creates_are_over_split=True,
    )
    _wrong_targets(found, supersedes_here, evidence["address_id"])
    revised = ctx.revised_ids[document]
    seed_claim_ids = frozenset(evidence["seed_claim_ids"])
    supports = tuple(
        support
        for support in ctx.state.claim_supports
        if support.claim_id in seed_claim_ids
        and support.judgment_id in ctx.active
        and revised in support.evidence_ids
    )
    if not supports:
        found.add(
            _MISSING_EXTENSION,
            f"active SUPPORTS_CLAIM records of {_listed(sorted(seed_claim_ids))} citing "
            f"{revised} = 0, expected at least 1",
        )
    asserts = ctx.select(t=_REVISION_T, kind=JudgmentKind.ASSERT_CLAIM, citing=revised)
    duplicates = tuple(draft for draft in ctx.drafts if draft.duplicate_refusal)
    if asserts:
        found.add(
            _DUPLICATE_ASSERTION,
            f"ASSERT_CLAIM drafts citing {revised} = {len(asserts)} "
            f"({_listed(_judgment_ids(asserts))}), expected 0",
        )
    if duplicates:
        found.add(
            _DUPLICATE_ASSERTION,
            f"admissions carrying the structural duplicate refusal = {len(duplicates)} "
            f"({_listed(_judgment_ids(duplicates))}), expected 0",
        )
    evidence |= {
        "support_judgment_ids": [support.judgment_id for support in supports],
        "assert_count": len(asserts),
        "assert_judgment_ids": _judgment_ids(asserts),
        "duplicate_rejection_count": len(duplicates),
        "duplicate_rejection_judgment_ids": _judgment_ids(duplicates),
    }
    return found, evidence


def _correction_case(ctx: _Context, document: str) -> tuple[_Findings, dict[str, Any]]:
    """V05: the bind to ``X4``; ``X4`` live claims == seed claim + one new claim citing
    ``D4'``; exactly one ``SUPERSEDE`` in the run targeting the seed claim's judgment,
    held ``REQUIRE_SECOND_LENS``, never applied; 0 ``CONFLICTS_WITH``; 0 human
    authorizations."""
    found, evidence, _supersedes_here = _revised_item_shape(
        ctx,
        document,
        expected_new_claims=1,
        call_two_kinds=_CORRECTION_CALL_TWO_KINDS,
        creates_are_over_split=True,
    )
    seed_judgments = frozenset(
        claim.created_by_judgment_id for claim in ctx.seed_claims(evidence["address_id"])
    )
    seed_text = _listed(sorted(seed_judgments))
    supersedes = ctx.select(kind=JudgmentKind.SUPERSEDE)
    targeting = tuple(draft for draft in supersedes if draft.supersede_target in seed_judgments)
    if not supersedes:
        found.add(_MISSING_SUPERSEDE, "SUPERSEDE drafts in the run = 0, expected 1")
    for draft in supersedes:
        if draft.supersede_target not in seed_judgments:
            found.add(
                _WRONG_SUPERSEDE_TARGET,
                f"SUPERSEDE {draft.judgment_id} targets {draft.supersede_target}, which is not "
                f"the T1 claim's created_by_judgment_id {seed_text}",
            )
    if len(targeting) > 1:
        found.add(
            _EXTRA_DRAFT,
            f"SUPERSEDE drafts targeting {seed_text} = {len(targeting)} "
            f"({_listed(_judgment_ids(targeting))}), expected 1",
        )
    pending = ctx.view.pending_judgment_ids
    for draft in targeting:
        held = draft.judgment_id in pending
        if ctx.is_applied(draft):
            found.add(_UNGOVERNED_SUPERSEDE, _applied_supersede_text(draft))
        elif draft.route is not AdmissionRoute.REQUIRE_SECOND_LENS or not held:
            route = "none" if draft.route is None else draft.route.value
            found.add(
                _MISSING_SUPERSEDE,
                f"SUPERSEDE {draft.judgment_id} route = {route}, pending = {held}, expected "
                f"{AdmissionRoute.REQUIRE_SECOND_LENS.value} and pending",
            )
    unattributed = tuple(
        draft for draft in ctx.ungoverned_supersedes() if ctx.target_address(draft) is None
    )
    for draft in unattributed:
        found.add(_UNGOVERNED_SUPERSEDE, _applied_supersede_text(draft))
    conflicts = ctx.select(kind=JudgmentKind.CONFLICTS_WITH)
    if conflicts:
        found.add(
            _CONFLICT_INSTEAD_OF_CORRECTION,
            f"CONFLICTS_WITH drafts in the run = {len(conflicts)} "
            f"({_listed(_judgment_ids(conflicts))}), expected 0",
        )
    if ctx.human_authorizations != 0:
        found.add(_EXTRA_DRAFT, f"human_authorizations = {ctx.human_authorizations}, expected 0")

    sole = supersedes[0] if len(supersedes) == 1 else None
    evidence |= {
        "seed_claim_judgment_ids": sorted(seed_judgments),
        "supersede_judgment_ids": _judgment_ids(supersedes),
        "supersede_target_judgment_id": None if sole is None else sole.supersede_target,
        "supersede_route": None if sole is None or sole.route is None else sole.route.value,
        "supersede_applied": any(ctx.is_applied(draft) for draft in supersedes),
        "ungoverned_supersede_judgment_ids": sorted(
            set(evidence["ungoverned_supersede_judgment_ids"]) | set(_judgment_ids(unattributed))
        ),
        "pending_judgment_ids": list(pending),
        "conflict_count": len(conflicts),
        "conflict_judgment_ids": _judgment_ids(conflicts),
        "human_authorizations": ctx.human_authorizations,
    }
    return found, evidence


# --------------------------------------------------------------------------- driver


def _delta(record: LedgerRecord, t: int) -> DeltaRecord | None:
    for delta in record.deltas:
        if delta.t == t:
            return delta
    return None


def _ran(delta: DeltaRecord | None) -> bool:
    """A delta ran when at least one forwarded call was answered."""
    return delta is not None and len(delta.requests) > 0


def _state_for(record: LedgerRecord, t: int) -> tuple[SemanticState, CurrentSemanticView] | None:
    """The seed delta's own snapshot; the ledger's final state for the revision delta,
    falling back to the revision snapshot when the final capture failed."""
    delta = _delta(record, t)
    if delta is None:
        return None
    if t == _REVISION_T and record.final_state is not None and record.final_view is not None:
        return record.final_state.semantic, record.final_view
    if delta.state_snapshot is None or delta.view_snapshot is None:
        return None
    return delta.state_snapshot.semantic, delta.view_snapshot


def _result(
    ledger: Ledger,
    case_id: str,
    *,
    passed: bool | None,
    tags: Iterable[str] = (),
    detail: str,
    evidence: dict[str, Any] | None = None,
) -> CaseResult:
    chosen = tuple(tags)
    unknown = sorted(set(chosen) - set(FAILURE_TAGS))
    if unknown:
        raise ValueError(f"unknown failure tags {unknown} for {ledger} {case_id}")
    return CaseResult(
        ledger=ledger,
        case_id=case_id,
        structural_passed=passed,
        tags=tuple(tag for tag in FAILURE_TAGS if tag in chosen),
        detail=detail,
        evidence={} if evidence is None else evidence,
    )


def _evaluate_case(ctx: _Context, case_id: str, document: str) -> tuple[_Findings, dict[str, Any]]:
    match case_id:
        case "S01":
            return _seed_case(ctx)
        case "V01":
            return _extension_case(ctx, document, creates_are_over_split=True)
        case "V02":
            return _extension_case(ctx, document, creates_are_over_split=False)
        case "V03":
            return _distinct_locus_case(ctx, document)
        case "V04":
            return _restatement_case(ctx, document)
        case "V05":
            return _correction_case(ctx, document)
    raise ValueError(f"unknown case {case_id!r}")


def evaluate_ledger(record: LedgerRecord) -> tuple[CaseResult, ...]:
    """The six §7.1 cases of ``record`` in ``CASE_IDS`` order (S01, V01..V05)."""
    revised_ids = frozenset(evidence_id(doc, 2) for doc in DOCUMENTS[record.ledger])
    drafts = _drafts(record, revised_ids)
    contexts: dict[int, _Context | str] = {}
    for t in (_SEED_T, _REVISION_T):
        if record.status == "NOT_RUN" or not _ran(_delta(record, t)):
            contexts[t] = _NOT_RUN_DETAIL
            continue
        captured = _state_for(record, t)
        if captured is None:
            contexts[t] = _NO_STATE_DETAIL
            continue
        state, view = captured
        contexts[t] = _Context(record, drafts, state, view)

    results: list[CaseResult] = []
    for case in CASES[record.ledger]:
        t = _SEED_T if case.id == "S01" else _REVISION_T
        ctx = contexts[t]
        if isinstance(ctx, str):
            results.append(_result(record.ledger, case.id, passed=None, detail=ctx))
            continue
        found, evidence = _evaluate_case(ctx, case.id, case.document)
        results.append(
            _result(
                record.ledger,
                case.id,
                passed=not found,
                tags=found.tags,
                detail=found.detail(),
                evidence=evidence,
            )
        )
    if [result.case_id for result in results] != list(CASE_IDS):
        raise RuntimeError("case table does not match CASE_IDS")
    return tuple(results)


def evaluate_run(run: RunResult) -> tuple[CaseResult, ...]:
    """Twelve results: the alpha ledger's six cases, then the beta ledger's."""
    return tuple(result for record in run.ledgers for result in evaluate_ledger(record))
