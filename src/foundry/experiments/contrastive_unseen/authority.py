"""Mechanical human-authority protocol for root supersessions (spec §8; T2 brief).

Law: this module may only relay an *already-pending, model-originated* ``SUPERSEDE``
proposal verbatim to a human AGREE, or refuse to. It never authors, edits, retargets,
selects, or repairs a proposal; it never decides whether the superseded interpretation
was semantically correct to retire (that is architect adjudication, per spec §8); and
it never constructs or calls a ``SemanticReasoner`` -- every write here goes through
``SemanticGovernor.submit`` under the frozen human fingerprint, never through
``propose``/``propose_and_submit``.

Only F and A ever reach this module, at their two authority checkpoints: T2's
designated ``A`` root and T4's designated ``B`` root. ``N`` is a stable control and is
never a checkpoint.

Two structural guards surround an AGREE:

* **pre-check** -- before ``submit`` is called, a live, project-wide
  (``scope == ()``) ``AuthorityRecord`` authorized by the frozen human fingerprint
  must already exist in replayed state (written once, before T1, by
  ``record_architect_authority``), otherwise the AGREE is refused and the ledger is
  untouched;
* **post-check** -- after the judgment is submitted, its admission must have routed
  ``APPLY`` with reason ``HUMAN_AUTHORITY``; anything else is an operational failure
  (a break in the governor's own trust boundary), never a semantic one, and is
  raised rather than silently accepted.

Controller Ruling 3 (binding): ``AuthorizationBudget`` is a ``typing.Protocol`` naming
one mutable attribute, ``human_authorizations``. It is the runner's non-durable tally,
never durable state; ``authorize_root_supersessions`` enforces the ``MAX_HUMAN_
AUTHORIZATIONS`` ceiling against it BEFORE constructing or submitting the human
judgment, and increments it only after a successful AGREED write.
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
from foundry.domain.state import IntentState
from foundry.experiments.contrastive_unseen.designation import RootDesignation
from foundry.experiments.contrastive_unseen.timeline import MAX_HUMAN_AUTHORIZATIONS

__all__ = [
    "ARCHITECT_ACTOR",
    "HUMAN_FINGERPRINT",
    "AuthorizationBudget",
    "AuthorizationCeilingExceeded",
    "AuthorizationOutcome",
    "AuthorizationRecord",
    "authorize_root_supersessions",
    "record_architect_authority",
]

ARCHITECT_ACTOR: Final = "architect"
"""The experiment artifact's logical display actor. Never passed as ``human_actor_id``."""

HUMAN_FINGERPRINT: Final = ReasonerFingerprint(
    provider="human",
    model="human://architect",
    policy_version="intent-v2-9p2-unseen-v1",
)
"""The frozen human identity. ``SemanticGovernor.submit`` authenticates
``human_actor_id`` against ``.model``, so the authenticated actor is always
``"human://architect"`` -- never ``ARCHITECT_ACTOR`` alone."""

_HUMAN_AUTHORITY_REASON: Final = "HUMAN_AUTHORITY"
_AUTHORITY_SUBJECT: Final = "material-semantic-change"


class AuthorizationOutcome(StrEnum):
    AGREED = "AGREED"
    NO_PROPOSAL = "NO_PROPOSAL"
    AMBIGUOUS_PROPOSALS = "AMBIGUOUS_PROPOSALS"
    NON_ROOT_NOT_AUTHORIZED = "NON_ROOT_NOT_AUTHORIZED"


class AuthorizationRecord(FrozenModel):
    """Log line for one root creating-judgment id, or one withheld non-root id."""

    arm: Literal["F", "A"]
    t: Literal[2, 4]
    root_key: Literal["A", "B"]
    target_judgment_id: str
    outcome: AuthorizationOutcome
    pending_judgment_ids: tuple[str, ...]
    submitted_judgment_id: str | None
    proposal_signature: tuple[str, ...] | None
    actor_id: Literal["architect"] = "architect"


class AuthorizationCeilingExceeded(RuntimeError):
    """Raised before any durable write once the human-authorization ceiling is reached."""


class AuthorizationBudget(Protocol):
    """Controller Ruling 3: a mutable, runner-held tally. Never durable/ledger state."""

    human_authorizations: int


def record_architect_authority(
    governor: SemanticGovernor,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> StoredEvent:
    """Record the one project-wide active ``AuthorityRecord`` for F/A, before T1.

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
            "Architect authority for AGREE of material supersession proposals "
            "(9P2 unseen-lifecycle experiment)."
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


def _require_authority_checkpoint_key(key: Literal["A", "B", "N"]) -> Literal["A", "B"]:
    if key == "A" or key == "B":
        return key
    raise ValueError(f"root key {key!r} is never an authority checkpoint")


def _model_supersede_targets(
    state: IntentState, pending_judgment_ids: tuple[str, ...]
) -> dict[str, list[str]]:
    """Pending, model-originated SUPERSEDE judgment ids among ``pending_judgment_ids``,
    grouped by ``target_judgment_id``, each group's ids sorted."""
    by_target: dict[str, list[str]] = {}
    for judgment_id in pending_judgment_ids:
        judgment = state.semantic.judgments.get(judgment_id)
        if judgment is None:
            continue
        proposal = judgment.proposal
        if not isinstance(proposal, SupersedeProposal) or judgment.reasoner.is_human:
            continue
        by_target.setdefault(proposal.target_judgment_id, []).append(judgment_id)
    for judgment_ids in by_target.values():
        judgment_ids.sort()
    return by_target


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
            f"AGREE on {pending.judgment_id} routed {decision.route.value} "
            f"{decision.reasons}; expected APPLY under {_HUMAN_AUTHORITY_REASON}"
        )
    return judgment.judgment_id


def authorize_root_supersessions(
    *,
    governor: SemanticGovernor,
    arm: Literal["F", "A"],
    t: Literal[2, 4],
    root: RootDesignation,
    pending_judgment_ids: tuple[str, ...],
    budget: AuthorizationBudget,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> tuple[AuthorizationRecord, ...]:
    """Offer at most one AGREE per root creating-judgment id; log every outcome.

    For every ``root.creating_judgment_ids`` (sorted): zero pending model-originated
    SUPERSEDE proposals targeting it -> ``NO_PROPOSAL``; more than one -> ``AMBIGUOUS_
    PROPOSALS`` (none submitted); exactly one -> the ceiling is checked, the pre-check
    authority record is verified, the identical proposal is submitted as a human AGREE,
    the post-check route is verified, and the budget is incremented -> ``AGREED``.

    Every pending model-originated SUPERSEDE targeting a judgment that is not one of
    ``root.creating_judgment_ids`` (including all of them, when ``root`` is
    ``UNDESIGNATED`` and that tuple is empty) is recorded ``NON_ROOT_NOT_AUTHORIZED``,
    sorted by pending judgment id, after every root-target record. Those never consume
    the budget and are never submitted.
    """
    root_key = _require_authority_checkpoint_key(root.key)
    state = governor.state()
    by_target = _model_supersede_targets(state, pending_judgment_ids)
    root_target_ids = frozenset(root.creating_judgment_ids)

    records: list[AuthorizationRecord] = []
    for creating_judgment_id in sorted(root.creating_judgment_ids):
        matches = by_target.get(creating_judgment_id, [])
        if not matches:
            records.append(
                AuthorizationRecord(
                    arm=arm,
                    t=t,
                    root_key=root_key,
                    target_judgment_id=creating_judgment_id,
                    outcome=AuthorizationOutcome.NO_PROPOSAL,
                    pending_judgment_ids=(),
                    submitted_judgment_id=None,
                    proposal_signature=None,
                )
            )
        elif len(matches) > 1:
            records.append(
                AuthorizationRecord(
                    arm=arm,
                    t=t,
                    root_key=root_key,
                    target_judgment_id=creating_judgment_id,
                    outcome=AuthorizationOutcome.AMBIGUOUS_PROPOSALS,
                    pending_judgment_ids=tuple(matches),
                    submitted_judgment_id=None,
                    proposal_signature=None,
                )
            )
        else:
            pending_id = matches[0]
            if budget.human_authorizations >= MAX_HUMAN_AUTHORIZATIONS:
                raise AuthorizationCeilingExceeded(
                    f"human-authorization ceiling {MAX_HUMAN_AUTHORIZATIONS} reached; "
                    f"refusing to authorize {pending_id} before any write"
                )
            pending = state.semantic.judgments[pending_id]
            submitted_id = _submit_agreement(governor, pending, clock=clock, id_factory=id_factory)
            budget.human_authorizations += 1
            records.append(
                AuthorizationRecord(
                    arm=arm,
                    t=t,
                    root_key=root_key,
                    target_judgment_id=creating_judgment_id,
                    outcome=AuthorizationOutcome.AGREED,
                    pending_judgment_ids=(pending_id,),
                    submitted_judgment_id=submitted_id,
                    proposal_signature=proposal_signature(pending.proposal),
                )
            )

    non_root_ids = sorted(
        judgment_id
        for target, judgment_ids in by_target.items()
        if target not in root_target_ids
        for judgment_id in judgment_ids
    )
    for judgment_id in non_root_ids:
        judgment = state.semantic.judgments[judgment_id]
        proposal = judgment.proposal
        assert isinstance(proposal, SupersedeProposal)
        records.append(
            AuthorizationRecord(
                arm=arm,
                t=t,
                root_key=root_key,
                target_judgment_id=proposal.target_judgment_id,
                outcome=AuthorizationOutcome.NON_ROOT_NOT_AUTHORIZED,
                pending_judgment_ids=(judgment_id,),
                submitted_judgment_id=None,
                proposal_signature=proposal_signature(proposal),
            )
        )

    return tuple(records)
