from __future__ import annotations

from collections.abc import Iterable

from foundry.domain.closure import evaluate_closure
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

CURRENT_DECISION_CANDIDATE_AUTHORITIES = frozenset(
    {Authority.OBSERVED, Authority.INFERRED, Authority.PROPOSED, Authority.DISPUTED}
)
NON_CURRENT_AUTHORITIES = frozenset({Authority.REJECTED, Authority.SUPERSEDED})


class CanonicalIntentPackage(FrozenModel):
    project_id: str
    intent_version: int
    scope: str
    purpose_ids: tuple[str, ...]
    boundary_ids: tuple[str, ...]
    """DEPRECATED compatibility field: exactly ``sorted(exclusion_ids + preference_ids)``.

    Retained so no current consumer loses it, but it must not be used as the authoritative
    distinction: it conflates a hard exclusion with a tradeable preference, which is the
    defect ``exclusion_ids``/``preference_ids`` exist to fix. Downstream cannot tell what it
    may trade away from what it must never reintroduce by reading this field.
    """
    exclusion_ids: tuple[str, ...] = ()
    """``NonGoal`` — explicit exclusions. Never tradeable."""
    preference_ids: tuple[str, ...] = ()
    """``Preference`` — tradeable inclinations. Never obligations."""
    obligation_ids: tuple[str, ...]
    canonical_decision_ids: tuple[str, ...]
    proposed_decision_ids: tuple[str, ...]
    superseded_decision_ids: tuple[str, ...]
    epistemic_ids: tuple[str, ...]
    quality_ids: tuple[str, ...]
    governance_ids: tuple[str, ...]
    history_event_ids: tuple[str, ...]


class IntentNotClosedError(RuntimeError):
    def __init__(self, blocker_codes: tuple[str, ...]) -> None:
        self.blocker_codes = blocker_codes
        super().__init__(f"Intent is not closed: {', '.join(blocker_codes)}")


def build_intent_package(state: IntentState, scope: str) -> CanonicalIntentPackage:
    closure = evaluate_closure(state, scope)
    if not closure.closed:
        codes = tuple(sorted({blocker.code for blocker in closure.blockers}))
        raise IntentNotClosedError(codes)

    objects = list(state.objects.values())
    current = [obj for obj in objects if _is_current(obj) and _applies(obj, scope)]
    return CanonicalIntentPackage(
        project_id=state.project_id,
        intent_version=state.revision,
        scope=scope,
        purpose_ids=_sorted_ids(current, Intent, Goal, Actor, Outcome),
        boundary_ids=_sorted_ids(current, NonGoal, Preference),
        exclusion_ids=_sorted_ids(current, NonGoal),
        preference_ids=_sorted_ids(current, Preference),
        obligation_ids=_sorted_ids(
            [
                obj
                for obj in current
                if isinstance(obj, Requirement | Constraint | Contract)
                and obj.authority is Authority.CANONICAL
            ]
        ),
        canonical_decision_ids=_sorted_ids(
            [
                obj
                for obj in current
                if isinstance(obj, Decision) and obj.authority is Authority.CANONICAL
            ]
        ),
        proposed_decision_ids=_sorted_ids(
            [
                obj
                for obj in current
                if isinstance(obj, Decision)
                and obj.authority in CURRENT_DECISION_CANDIDATE_AUTHORITIES
            ]
        ),
        superseded_decision_ids=_sorted_ids(
            [
                obj
                for obj in objects
                if isinstance(obj, Decision)
                and (
                    obj.lifecycle is LifecycleStatus.SUPERSEDED
                    or obj.authority is Authority.SUPERSEDED
                )
                and _applies(obj, scope)
            ]
        ),
        epistemic_ids=_sorted_ids(
            current,
            Assumption,
            Claim,
            Evidence,
            Unknown,
            Question,
            Conflict,
        ),
        quality_ids=_sorted_ids(
            [
                obj
                for obj in current
                if (
                    isinstance(obj, Metric | VerificationObligation)
                    and obj.authority is Authority.CANONICAL
                )
            ]
        ),
        governance_ids=_sorted_ids(current, Risk, AuthorityRecord, Amendment),
        history_event_ids=state.source_events,
    )


def _is_current(obj: SemanticBase) -> bool:
    return obj.lifecycle is LifecycleStatus.ACTIVE and obj.authority not in NON_CURRENT_AUTHORITIES


def _applies(obj: SemanticBase, scope: str) -> bool:
    return obj.scope == () or scope in obj.scope


def _sorted_ids(objects: Iterable[SemanticBase], *types: type[SemanticBase]) -> tuple[str, ...]:
    selected = objects if not types else [obj for obj in objects if isinstance(obj, types)]
    return tuple(sorted(obj.id for obj in selected))
