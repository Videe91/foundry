"""Pre-T eligible-target authority protocol for the persistent arms (spec §18; T2 brief).

Law: this module may only (a) snapshot, structurally and from pre-T state, which
judgment ids created the claims live at a locus's designated address, and (b) relay
an *already-pending, model-originated* ``SUPERSEDE`` proposal that targets exactly
one of those ids verbatim to a human AGREE -- or refuse to. It never authors, edits,
retargets, selects among, or repairs a proposal; it never decides whether the retired
interpretation was semantically right to retire (that is architect adjudication after
the raw freeze, spec §10.6); and it never constructs or calls a ``SemanticReasoner``.
Every write goes through ``SemanticGovernor.submit`` under the frozen human
fingerprint, never through ``propose``/``propose_and_submit``.

The frozen pre-T eligibility rule (spec §18.1)::

    ELIGIBLE_T = { claim.created_by_judgment_id
                   for claim live in derive_view(state_before_T)
                   if claim.address_id == DESIGNATED_ADDRESS[target_locus(T)] }

``snapshot_eligible_targets`` is taken BEFORE the arm ingests T's evidence and is
never recomputed afterwards; ``authorize_eligible_supersessions`` runs after that
arm's Call 2 over that same snapshot. For each eligible id (sorted): exactly one
matching pending model ``SUPERSEDE`` -> one AGREE; zero -> ``NO_PROPOSAL``; more than
one -> ``AMBIGUOUS_PROPOSALS`` (fail closed). Every pending model ``SUPERSEDE`` whose
target is not eligible -- not live pre-T, live only since T, at another address, or
the locus undesignated -- is recorded ``NOT_ELIGIBLE_NOT_AUTHORIZED`` and stays
pending. This generalises 9P2's "T1 root creating judgments": at the T8 revert the
eligible target is the T5-created claim's judgment, not the T1 judgment.

Two structural guards surround an AGREE:

* **pre-check** -- a live, project-wide (``scope == ()``) ``AuthorityRecord``
  authorized by the frozen human identity must already exist in replayed state
  (written once, before T1, by ``record_architect_authority``), otherwise the AGREE
  is refused and the ledger is untouched;
* **post-check** -- the submitted judgment must have routed ``APPLY`` with reason
  ``HUMAN_AUTHORITY``; anything else is an operational failure (a break in the
  governor's own trust boundary), never a semantic one, and is raised.

``AuthorizationBudget`` is a ``typing.Protocol`` naming one mutable attribute,
``human_authorizations``: the runner's non-durable tally, never durable state. The
``MAX_HUMAN_AUTHORIZATIONS`` ceiling is enforced against it BEFORE the human
judgment is constructed or submitted, and it is incremented only after an AGREED
write. This module imports ``timeline``/``protocol`` only, never ``expectations``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Protocol

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
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.experiments.long_horizon_bounded.protocol import MAX_HUMAN_AUTHORIZATIONS
from foundry.experiments.long_horizon_bounded.timeline import Locus

__all__ = [
    "ARCHITECT_ACTOR",
    "HUMAN_FINGERPRINT",
    "AuthorizationBudget",
    "AuthorizationCeilingExceeded",
    "AuthorizationOutcome",
    "AuthorizationRecord",
    "EligibleTargets",
    "authorize_eligible_supersessions",
    "record_architect_authority",
    "snapshot_eligible_targets",
]

ARCHITECT_ACTOR: Final = "architect"
"""The experiment artifact's logical display actor. Never passed as ``human_actor_id``."""

HUMAN_FINGERPRINT: Final = ReasonerFingerprint(
    provider="human",
    model="human://architect",
    policy_version="intent-v2-9p3-long-horizon-v1",
)
"""The frozen human identity (spec §18.2). ``SemanticGovernor.submit`` authenticates
``human_actor_id`` against ``.model``, so the authenticated actor is always
``"human://architect"`` -- never ``ARCHITECT_ACTOR`` alone."""

_HUMAN_AUTHORITY_REASON: Final = "HUMAN_AUTHORITY"
_AUTHORITY_SUBJECT: Final = "material-semantic-change"

PersistentArm = Literal["F", "A"]


class AuthorizationOutcome(StrEnum):
    AGREED = "AGREED"
    NO_PROPOSAL = "NO_PROPOSAL"
    AMBIGUOUS_PROPOSALS = "AMBIGUOUS_PROPOSALS"
    NOT_ELIGIBLE_NOT_AUTHORIZED = "NOT_ELIGIBLE_NOT_AUTHORIZED"


class EligibleTargets(FrozenModel):
    """The frozen pre-T snapshot for one (arm, T) authority checkpoint (spec §18.1).

    ``eligible_judgment_ids`` are the sorted, deduplicated ``created_by_judgment_id``s
    of the claims live at ``designated_address_id`` immediately before T's evidence
    was ingested; ``live_claim_ids`` are those claims' ids, sorted;
    ``snapshot_sequence`` is the ledger length at the moment of the snapshot. An
    undesignated locus (``designated_address_id is None``) snapshots empty.
    """

    arm: PersistentArm
    t: int
    target_locus: Locus
    designated_address_id: str | None
    eligible_judgment_ids: tuple[str, ...]
    live_claim_ids: tuple[str, ...]
    snapshot_sequence: int


class AuthorizationRecord(FrozenModel):
    """Log line for one eligible target id, or one withheld non-eligible proposal."""

    arm: PersistentArm
    t: int
    target_locus: Locus
    target_judgment_id: str
    outcome: AuthorizationOutcome
    pending_judgment_ids: tuple[str, ...]
    submitted_judgment_id: str | None
    proposal_signature: tuple[str, ...] | None
    actor_id: Literal["architect"] = "architect"


class AuthorizationCeilingExceeded(RuntimeError):
    """Raised before any durable write once the human-authorization ceiling is reached."""


class AuthorizationBudget(Protocol):
    """A mutable, runner-held tally. Never durable/ledger state."""

    human_authorizations: int


# --- authority record ---------------------------------------------------------------------


def record_architect_authority(
    governor: SemanticGovernor,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> StoredEvent:
    """Record the one project-wide active ``AuthorityRecord`` for a persistent arm, before T1.

    Scope ``()`` covers every address, so a supersession -- which has no single
    target scope -- is covered. This makes no model call; it is an ordinary
    ``SEMANTIC_OBJECT_RECORDED`` event.
    """
    record = AuthorityRecord(
        id=id_factory("authority"),
        project_id=governor.project_id,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=HUMAN_FINGERPRINT.model),
        created_at=clock(),
        scope=(),
        subject_id=_AUTHORITY_SUBJECT,
        authorized_by=HUMAN_FINGERPRINT.model,
        rationale=(
            "Architect authority for mechanical AGREE of eligible pre-T supersession "
            "proposals (9P3 long-horizon bounded-memory experiment)."
        ),
    )
    return governor.record_authority(record)


def _architect_authority_recorded(state: IntentState) -> bool:
    """A live, project-wide ``AuthorityRecord`` for the frozen human identity exists."""
    return any(
        isinstance(obj, AuthorityRecord)
        and obj.authorized_by == HUMAN_FINGERPRINT.model
        and obj.scope == ()
        and authority_record_is_live(obj)
        for obj in state.objects.values()
    )


# --- pre-T snapshot ------------------------------------------------------------------------


def snapshot_eligible_targets(
    state: IntentState,
    *,
    arm: PersistentArm,
    t: int,
    target_locus: Locus,
    designated_address_id: str | None,
    ledger_length: int,
) -> EligibleTargets:
    """Snapshot ``ELIGIBLE_T`` from ``state`` -- which the caller must pass BEFORE ingesting T.

    Reads ids, addresses and liveness only, never wording.
    """
    if designated_address_id is None:
        return EligibleTargets(
            arm=arm,
            t=t,
            target_locus=target_locus,
            designated_address_id=None,
            eligible_judgment_ids=(),
            live_claim_ids=(),
            snapshot_sequence=ledger_length,
        )
    view = derive_view(state.semantic)
    live = sorted(
        claim_id
        for claim_id in view.effective_evidence
        if state.semantic.claims[claim_id].address_id == designated_address_id
    )
    judgments = tuple(
        sorted({state.semantic.claims[claim_id].created_by_judgment_id for claim_id in live})
    )
    return EligibleTargets(
        arm=arm,
        t=t,
        target_locus=target_locus,
        designated_address_id=designated_address_id,
        eligible_judgment_ids=judgments,
        live_claim_ids=tuple(live),
        snapshot_sequence=ledger_length,
    )


# --- mechanical AGREE ----------------------------------------------------------------------


def _model_supersede_targets(
    state: IntentState, pending_judgment_ids: tuple[str, ...]
) -> dict[str, list[str]]:
    """``target_judgment_id -> sorted pending judgment ids``, for model-originated
    ``SUPERSEDE`` proposals only. An unknown pending id raises ``KeyError``: that is a
    caller-contract error, never repaired here."""
    targets: dict[str, list[str]] = {}
    for pending_id in sorted(pending_judgment_ids):
        judgment = state.semantic.judgments[pending_id]
        proposal = judgment.proposal
        if isinstance(proposal, SupersedeProposal) and not judgment.reasoner.is_human:
            targets.setdefault(proposal.target_judgment_id, []).append(pending_id)
    return targets


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
    """Pre-check authority on fresh state, submit, post-check the route."""
    if not _architect_authority_recorded(governor.state()):
        raise ValueError(
            f"AGREE on {pending.judgment_id} refused: no live project-wide AuthorityRecord "
            f"for {HUMAN_FINGERPRINT.model}; nothing was written"
        )
    judgment = _agreeing_judgment(pending, clock=clock, id_factory=id_factory)
    decision = governor.submit(judgment, human_actor_id=HUMAN_FINGERPRINT.model)
    if (
        decision.route is not AdmissionRoute.APPLY
        or _HUMAN_AUTHORITY_REASON not in decision.reasons
    ):
        raise RuntimeError(
            f"AGREE on {pending.judgment_id} routed {decision.route} "
            f"{decision.reasons}; expected APPLY under {_HUMAN_AUTHORITY_REASON}"
        )
    return judgment.judgment_id


def _record(
    eligible: EligibleTargets,
    *,
    target: str,
    outcome: AuthorizationOutcome,
    pending: tuple[str, ...] = (),
    submitted: str | None = None,
    signature: tuple[str, ...] | None = None,
) -> AuthorizationRecord:
    return AuthorizationRecord(
        arm=eligible.arm,
        t=eligible.t,
        target_locus=eligible.target_locus,
        target_judgment_id=target,
        outcome=outcome,
        pending_judgment_ids=pending,
        submitted_judgment_id=submitted,
        proposal_signature=signature,
    )


def authorize_eligible_supersessions(
    *,
    governor: SemanticGovernor,
    eligible: EligibleTargets,
    pending_judgment_ids: tuple[str, ...],
    budget: AuthorizationBudget,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> tuple[AuthorizationRecord, ...]:
    """Offer at most one AGREE per eligible target id; log every outcome (spec §18.1).

    For every ``eligible.eligible_judgment_ids`` (already sorted by the snapshot): zero
    pending model-originated ``SUPERSEDE`` proposals targeting it -> ``NO_PROPOSAL``;
    more than one -> ``AMBIGUOUS_PROPOSALS`` (none submitted); exactly one -> the
    ceiling is checked, the pre-check authority record is verified, the identical
    proposal is submitted as a human AGREE, the post-check route is verified, and the
    budget is incremented -> ``AGREED``.

    Every pending model-originated ``SUPERSEDE`` targeting a judgment that is not in
    the snapshot (including all of them, when the locus is undesignated and the
    snapshot is empty) is recorded ``NOT_ELIGIBLE_NOT_AUTHORIZED``, one record per
    pending id, sorted by target then pending id, after every eligible-target record.
    Those never consume the budget, are never submitted, and are never retargeted.
    """
    targets = _model_supersede_targets(governor.state(), pending_judgment_ids)
    records: list[AuthorizationRecord] = []
    for target in eligible.eligible_judgment_ids:
        pending = tuple(targets.get(target, []))
        if not pending:
            records.append(
                _record(eligible, target=target, outcome=AuthorizationOutcome.NO_PROPOSAL)
            )
            continue
        if len(pending) > 1:
            records.append(
                _record(
                    eligible,
                    target=target,
                    outcome=AuthorizationOutcome.AMBIGUOUS_PROPOSALS,
                    pending=pending,
                )
            )
            continue
        if budget.human_authorizations >= MAX_HUMAN_AUTHORIZATIONS:
            raise AuthorizationCeilingExceeded(
                f"human authorization ceiling {MAX_HUMAN_AUTHORIZATIONS} reached before "
                f"AGREE on {pending[0]}; nothing was written"
            )
        pending_judgment = governor.state().semantic.judgments[pending[0]]
        submitted = _submit_agreement(
            governor, pending_judgment, clock=clock, id_factory=id_factory
        )
        budget.human_authorizations += 1
        records.append(
            _record(
                eligible,
                target=target,
                outcome=AuthorizationOutcome.AGREED,
                pending=pending,
                submitted=submitted,
                signature=proposal_signature(pending_judgment.proposal),
            )
        )

    eligible_ids = frozenset(eligible.eligible_judgment_ids)
    for target, pending_ids in sorted(targets.items()):
        if target in eligible_ids:
            continue
        for pending_id in pending_ids:
            records.append(
                _record(
                    eligible,
                    target=target,
                    outcome=AuthorizationOutcome.NOT_ELIGIBLE_NOT_AUTHORIZED,
                    pending=(pending_id,),
                )
            )
    return tuple(records)
