"""Agree-or-decline authority protocol for supersession (plan Task 9; spec §17, §26, §28).

Human authorization is a **governance action, not a reasoning pass**. Before the run,
one project-wide ``AuthorityRecord`` for ``ARCHITECT_ACTOR`` is recorded at T0 as an
ordinary event (``record_architect_authority``). When a material ``SUPERSEDE`` proposal
is pending, the harness presents it verbatim and the architect may only:

* **AGREE** — a ``SemanticJudgment`` carrying the *identical* proposal object (same
  target, same reason, therefore the same ``proposal_signature``) under
  ``HUMAN_FINGERPRINT`` is submitted through ``SemanticGovernor.submit(...,
  human_actor_id=ARCHITECT_ACTOR)``. Admission routes it ``APPLY`` under the human
  authority rule; the view then derives the AI proposal ``SATISFIED_BY`` it.
* **DECLINE** — nothing is submitted. The old judgment stays active, both claims stay
  live, the proposal stays pending and the scope's readiness stays qualified. No
  ``CONFLICTS_WITH`` is inferred.

Two guards surround an AGREE. The **pre-check** is what prevents a durable write: before
``submit`` is called, a live, project-wide (``scope == ()``) ``AuthorityRecord`` with
``authorized_by == ARCHITECT_ACTOR`` must exist in replayed state, otherwise the AGREE
is refused and the ledger is untouched. Without it a human SUPERSEDE that agrees with
the AI's would still route ``APPLY`` — as *independent corroboration*, a second lens —
and be applied durably; the pre-check exists so that path is never reached. The
**post-check** (route is ``APPLY`` with reason ``HUMAN_AUTHORITY``) runs after the
judgment and its admission are already in the ledger; it is a second line that halts
the run on an unexpected route, not a guard that undoes anything.

The human never edits, retargets, creates, selects, repairs or authors: the only
input path is an ``Authorizer`` that receives the pending judgment and returns a
decision. No function in this module accepts a proposal, target, reason, claim or
address from the caller.

Budget (spec §17, §26: agree/decline, ≤1 per tracked correction, ≤3 per run).
``AuthorizationBudget`` is the immutable ceiling; ``AuthorizationCounter`` is the
runner-held, non-durable tally. A proposal that was *presented and answered* consumes
its track's slot and one of the total, whether the answer was AGREE or DECLINE
(ruling R9-b); a declined id is never re-presented. The counter is deliberately not
state: every AGREE is already an applied human judgment in the ledger, and a DECLINE
writes nothing by design, so the counter is the only place a decline is remembered
within a run. A proposal that is not offered is logged with the reason it was withheld
and is never shown to the human.

Failure mid-batch (ruling R9-c): ``resolve_pending_supersessions`` raises
``AuthorizationHalted`` carrying the records completed before the failure, so the log
of what was presented and answered survives the halt.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import Field, model_validator

from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import authority_record_is_live
from foundry.domain.common import Authority, FrozenModel, Provenance, SourceKind
from foundry.domain.events import StoredEvent
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    proposal_signature,
)
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState

ARCHITECT_ACTOR: Final[str] = "human://architect"
HUMAN_FINGERPRINT: Final = ReasonerFingerprint(
    provider="human", model=ARCHITECT_ACTOR, policy_version="9p-authority-v1"
)
_HUMAN_AUTHORITY_REASON: Final = "HUMAN_AUTHORITY"


class AuthorizationDecision(StrEnum):
    """The only two things the human may say about a verbatim proposal."""

    AGREE = "AGREE"
    DECLINE = "DECLINE"


class NotOfferedReason(StrEnum):
    """Why a pending id was withheld from the human. Never a human decision."""

    UNTRACKED = "UNTRACKED"
    TRACK_BUDGET_EXHAUSTED = "TRACK_BUDGET_EXHAUSTED"
    TOTAL_BUDGET_EXHAUSTED = "TOTAL_BUDGET_EXHAUSTED"
    ALREADY_DECLINED = "ALREADY_DECLINED"
    NOT_PENDING = "NOT_PENDING"
    NOT_SUPERSEDE = "NOT_SUPERSEDE"


class AuthorizationRecord(FrozenModel):
    """Log line for one pending id: what was presented and what was answered.

    Exactly one of ``decision`` (the human answered) and ``not_offered`` (the harness
    withheld it) is set; ``submitted_judgment_id`` is set iff the decision was AGREE.
    """

    track: str | None
    pending_judgment_id: str = Field(min_length=1)
    decision: AuthorizationDecision | None
    not_offered: NotOfferedReason | None = None
    submitted_judgment_id: str | None
    proposal_signature: tuple[str, ...]
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_outcome(self) -> AuthorizationRecord:
        if (self.decision is None) == (self.not_offered is None):
            raise ValueError("exactly one of decision and not_offered must be set")
        agreed = self.decision is AuthorizationDecision.AGREE
        if agreed != (self.submitted_judgment_id is not None):
            raise ValueError("submitted_judgment_id is set iff the decision is AGREE")
        return self


class AuthorizationHalted(RuntimeError):
    """A batch stopped at a failure; ``records`` are the outcomes completed before it.

    Raised for every mid-batch failure — an unknown id, a non-decision from the
    authorizer, a missing authority record, an unexpected route — chained ``from`` the
    originating ``ValueError``.
    """

    def __init__(self, message: str, *, records: tuple[AuthorizationRecord, ...]) -> None:
        super().__init__(message)
        self.records = records


Authorizer = Callable[[SemanticJudgment], AuthorizationDecision]


class AuthorizationBudget(FrozenModel):
    """Preregistered ceiling (spec §17): ≤1 per tracked correction, ≤3 per run."""

    per_track: int = Field(default=1, ge=0)
    total: int = Field(default=3, ge=0)


class AuthorizationCounter:
    """Runner-held, non-durable tally of answered proposals. Never written to the ledger."""

    __slots__ = ("_answered_by_track", "_declined_ids", "_total")

    def __init__(self) -> None:
        self._answered_by_track: dict[str, int] = {}
        self._declined_ids: set[str] = set()
        self._total = 0

    @property
    def total(self) -> int:
        return self._total

    def answered(self, track: str) -> int:
        return self._answered_by_track.get(track, 0)

    def withheld_reason(
        self, pending_id: str, track: str, budget: AuthorizationBudget
    ) -> NotOfferedReason | None:
        if pending_id in self._declined_ids:
            return NotOfferedReason.ALREADY_DECLINED
        if self._total >= budget.total:
            return NotOfferedReason.TOTAL_BUDGET_EXHAUSTED
        if self.answered(track) >= budget.per_track:
            return NotOfferedReason.TRACK_BUDGET_EXHAUSTED
        return None

    def consume(self, pending_id: str, track: str, decision: AuthorizationDecision) -> None:
        """An answered proposal consumes its slot whichever way it was answered (R9-b)."""
        self._answered_by_track[track] = self.answered(track) + 1
        self._total += 1
        if decision is AuthorizationDecision.DECLINE:
            self._declined_ids.add(pending_id)


def record_architect_authority(
    governor: SemanticGovernor,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> StoredEvent:
    """Record the project-wide ``AuthorityRecord`` for ``ARCHITECT_ACTOR`` (spec §17).

    Scope ``()`` covers every address, so a supersession — which has no single target
    scope — is covered. It is an ordinary ``SEMANTIC_OBJECT_RECORDED`` event.
    """
    record = AuthorityRecord(
        id=id_factory("authority"),
        project_id=governor.project_id,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=ARCHITECT_ACTOR),
        created_at=clock(),
        scope=(),
        subject_id="material-semantic-change",
        authorized_by=ARCHITECT_ACTOR,
        rationale="Architect authority for AGREE/DECLINE of material supersession proposals.",
    )
    return governor.record_authority(record)


def _architect_authority_recorded(state: IntentState) -> bool:
    """A live, project-wide AuthorityRecord for the architect exists in state."""
    return any(
        isinstance(obj, AuthorityRecord)
        and obj.authorized_by == ARCHITECT_ACTOR
        and obj.scope == ()
        and authority_record_is_live(obj)
        for obj in state.objects.values()
    )


def _agreeing_judgment(
    pending: SemanticJudgment,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> SemanticJudgment:
    """The human's AGREE: the pending proposal object itself, re-authored by nobody."""
    return SemanticJudgment(
        judgment_id=id_factory("judgment"),
        project_id=pending.project_id,
        proposal=pending.proposal,
        visible_evidence_ids=(),
        rationale=f"AGREE: {pending.judgment_id}",
        reasoner=HUMAN_FINGERPRINT,
        invocation_id=id_factory("authorization"),
        proposed_at=clock(),
    )


def _submit_agreement(
    governor: SemanticGovernor,
    pending: SemanticJudgment,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> str:
    """Pre-check authority on fresh state (no write yet), submit, post-check the route.

    The state is re-read here, after the authorizer callback has returned, so a
    callback that retired the record cannot slip an independent-corroboration apply
    through on a stale snapshot.
    """
    if not _architect_authority_recorded(governor.state()):
        raise ValueError(
            f"AGREE on {pending.judgment_id} refused: no live project-wide AuthorityRecord "
            f"for {ARCHITECT_ACTOR}; nothing was written"
        )
    judgment = _agreeing_judgment(pending, clock=clock, id_factory=id_factory)
    decision = governor.submit(judgment, human_actor_id=ARCHITECT_ACTOR)
    if (
        decision.route is not AdmissionRoute.APPLY
        or _HUMAN_AUTHORITY_REASON not in decision.reasons
    ):
        raise ValueError(
            f"AGREE on {pending.judgment_id} routed {decision.route.value} "
            f"{decision.reasons}; expected APPLY under {_HUMAN_AUTHORITY_REASON}"
        )
    return judgment.judgment_id


def _withheld(
    view: CurrentSemanticView,
    pending: SemanticJudgment,
    track: str,
    budget: AuthorizationBudget,
    counter: AuthorizationCounter,
) -> NotOfferedReason | None:
    """Why ``pending`` must not be shown to the human, or None if it may be."""
    if pending.judgment_id not in view.pending_judgment_ids:
        return NotOfferedReason.NOT_PENDING
    if not isinstance(pending.proposal, SupersedeProposal):
        return NotOfferedReason.NOT_SUPERSEDE
    return counter.withheld_reason(pending.judgment_id, track, budget)


def _not_offered(
    pending_id: str,
    track: str | None,
    reason: NotOfferedReason,
    signature: tuple[str, ...],
    recorded_at: datetime,
) -> AuthorizationRecord:
    return AuthorizationRecord(
        track=track,
        pending_judgment_id=pending_id,
        decision=None,
        not_offered=reason,
        submitted_judgment_id=None,
        proposal_signature=signature,
        recorded_at=recorded_at,
    )


def _resolve_one(
    pending_id: str,
    *,
    governor: SemanticGovernor,
    authorizer: Authorizer,
    track_of: Callable[[str], str | None],
    budget: AuthorizationBudget,
    counter: AuthorizationCounter,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> AuthorizationRecord:
    state = governor.state()
    pending = state.semantic.judgments.get(pending_id)
    if pending is None:
        raise ValueError(f"judgment {pending_id} is unknown to the ledger")
    track = track_of(pending_id)
    signature = proposal_signature(pending.proposal)
    if track is None:
        return _not_offered(pending_id, None, NotOfferedReason.UNTRACKED, signature, clock())
    withheld = _withheld(derive_view(state.semantic), pending, track, budget, counter)
    if withheld is not None:
        return _not_offered(pending_id, track, withheld, signature, clock())
    decision = authorizer(pending)
    submitted_id: str | None = None
    if decision is AuthorizationDecision.AGREE:
        submitted_id = _submit_agreement(governor, pending, clock=clock, id_factory=id_factory)
    elif decision is not AuthorizationDecision.DECLINE:
        raise ValueError(f"authorizer returned {decision!r}; only AGREE or DECLINE is allowed")
    counter.consume(pending_id, track, decision)
    return AuthorizationRecord(
        track=track,
        pending_judgment_id=pending_id,
        decision=decision,
        submitted_judgment_id=submitted_id,
        proposal_signature=signature,
        recorded_at=clock(),
    )


def resolve_pending_supersessions(
    *,
    governor: SemanticGovernor,
    pending_ids: tuple[str, ...],
    authorizer: Authorizer,
    track_of: Callable[[str], str | None],
    budget: AuthorizationBudget,
    counter: AuthorizationCounter,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> tuple[AuthorizationRecord, ...]:
    """Offer each pending ``SUPERSEDE`` to the human, in order; log every outcome.

    For each id: an id that is untracked (``track_of`` returns None), not currently
    pending, not a ``SUPERSEDE``, already declined in this run, or over budget is
    logged ``not_offered`` and never presented. Otherwise the pending judgment is
    handed verbatim to ``authorizer``: AGREE submits the identical proposal under
    ``HUMAN_FINGERPRINT``; DECLINE submits nothing; either answer consumes the track's
    slot and one of the total. Ledger state is re-read per id, so an earlier AGREE is
    visible to later checks.

    Raises ``AuthorizationHalted`` — carrying the records completed so far — when an
    id is unknown to the ledger, the authorizer returns anything but a decision, no
    live project-wide architect ``AuthorityRecord`` exists on the state re-read just
    before submission (refused before any write), a submitted AGREE routes anything
    but ``APPLY`` under ``HUMAN_AUTHORITY``, or the authorizer itself raises a
    ``ValueError`` (wrapped the same way).
    """
    records: list[AuthorizationRecord] = []
    for pending_id in pending_ids:
        try:
            record = _resolve_one(
                pending_id,
                governor=governor,
                authorizer=authorizer,
                track_of=track_of,
                budget=budget,
                counter=counter,
                clock=clock,
                id_factory=id_factory,
            )
        except ValueError as exc:
            raise AuthorizationHalted(str(exc), records=tuple(records)) from exc
        records.append(record)
    return tuple(records)
