from __future__ import annotations

from foundry.domain.closure import ClosureBlocker, evaluate_closure
from foundry.domain.common import Authority, FrozenModel, LifecycleStatus
from foundry.domain.semantic import (
    Actor,
    Amendment,
    Assumption,
    AuthorityRecord,
    Claim,
    Conflict,
    Constraint,
    Contract,
    Decision,
    Evidence,
    Goal,
    Intent,
    Metric,
    NonGoal,
    Outcome,
    Preference,
    Question,
    Requirement,
    Risk,
    SemanticBase,
    Unknown,
    VerificationObligation,
)
from foundry.domain.state import IntentState


class IntentNotClosedError(RuntimeError):
    def __init__(self, blockers: tuple[ClosureBlocker, ...]) -> None:
        self.blockers = blockers
        codes = ", ".join(blocker.code for blocker in blockers)
        super().__init__(f"intent is not closed: {codes}")


class CanonicalIntentPackage(FrozenModel):
    project_id: str
    intent_version: int
    scope: str
    purpose_ids: tuple[str, ...]
    boundary_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    canonical_decision_ids: tuple[str, ...]
    proposed_decision_ids: tuple[str, ...]
    superseded_decision_ids: tuple[str, ...]
    epistemic_ids: tuple[str, ...]
    quality_ids: tuple[str, ...]
    governance_ids: tuple[str, ...]
    history_event_ids: tuple[str, ...]


def _in_scope(obj: SemanticBase, scope: str) -> bool:
    return not obj.scope or scope in obj.scope


def _sorted_ids(objects: list[SemanticBase]) -> tuple[str, ...]:
    return tuple(sorted(obj.id for obj in objects))


def build_intent_package(state: IntentState, scope: str) -> CanonicalIntentPackage:
    closure = evaluate_closure(state, scope)
    if not closure.closed:
        raise IntentNotClosedError(closure.blockers)

    scoped = [obj for obj in state.objects.values() if _in_scope(obj, scope)]
    active = [obj for obj in scoped if obj.lifecycle is LifecycleStatus.ACTIVE]

    purpose = [
        obj
        for obj in active
        if isinstance(obj, (Intent, Goal, Actor, Outcome)) and obj.authority is Authority.CANONICAL
    ]
    boundaries = [
        obj
        for obj in active
        if isinstance(obj, NonGoal) and obj.authority is Authority.CANONICAL
    ]
    obligations = [
        obj
        for obj in active
        if isinstance(obj, (Requirement, Constraint, Contract))
        and obj.authority is Authority.CANONICAL
    ]
    canonical_decisions = [
        obj
        for obj in active
        if isinstance(obj, Decision) and obj.authority is Authority.CANONICAL
    ]
    proposed_decisions = [
        obj
        for obj in active
        if isinstance(obj, Decision) and obj.authority is Authority.PROPOSED
    ]
    superseded_decisions = [
        obj
        for obj in scoped
        if isinstance(obj, Decision)
        and (
            obj.lifecycle is LifecycleStatus.SUPERSEDED
            or obj.authority is Authority.SUPERSEDED
        )
    ]
    epistemics = [
        obj
        for obj in active
        if isinstance(obj, (Assumption, Claim, Evidence, Conflict, Unknown, Question, Preference))
    ]
    quality = [obj for obj in active if isinstance(obj, (Metric, VerificationObligation))]
    governance = [obj for obj in active if isinstance(obj, (Risk, AuthorityRecord, Amendment))]

    return CanonicalIntentPackage(
        project_id=state.project_id,
        intent_version=state.revision,
        scope=scope,
        purpose_ids=_sorted_ids(purpose),
        boundary_ids=_sorted_ids(boundaries),
        obligation_ids=_sorted_ids(obligations),
        canonical_decision_ids=_sorted_ids(canonical_decisions),
        proposed_decision_ids=_sorted_ids(proposed_decisions),
        superseded_decision_ids=_sorted_ids(superseded_decisions),
        epistemic_ids=_sorted_ids(epistemics),
        quality_ids=_sorted_ids(quality),
        governance_ids=_sorted_ids(governance),
        history_event_ids=state.source_events,
    )
