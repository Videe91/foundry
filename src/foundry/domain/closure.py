from __future__ import annotations

from foundry.domain.authority import object_is_current
from foundry.domain.common import (
    Authority,
    FrozenModel,
    LifecycleStatus,
    Materiality,
    RelationType,
    RiskLevel,
)
from foundry.domain.gaps import Gap, GapStatus
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import (
    Assumption,
    Conflict,
    Constraint,
    Contract,
    Intent,
    Metric,
    NonGoal,
    Requirement,
    SemanticBase,
    Unknown,
    VerificationObligation,
)
from foundry.domain.state import IntentState

MATERIAL_REQUIREMENT_LEVELS = frozenset(
    {Materiality.MEDIUM, Materiality.HIGH, Materiality.CRITICAL}
)
HIGH_RISK_LEVELS = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


class ClosureBlocker(FrozenModel):
    code: str
    object_ids: tuple[str, ...]
    message: str


class ClosureResult(FrozenModel):
    scope: str
    closed: bool
    blockers: tuple[ClosureBlocker, ...]


def evaluate_closure(state: IntentState, scope: str) -> ClosureResult:
    blockers: list[ClosureBlocker] = []
    current = [
        obj for obj in state.objects.values() if _is_current(obj) and _object_applies(obj, scope)
    ]

    if not any(isinstance(obj, Intent) and obj.authority is Authority.CANONICAL for obj in current):
        blockers.append(
            ClosureBlocker(
                code="MISSING_CANONICAL_INTENT",
                object_ids=(),
                message="Scope requires an active canonical Intent.",
            )
        )
    if not any(
        isinstance(obj, Requirement | Constraint | Contract)
        and obj.authority is Authority.CANONICAL
        for obj in current
    ):
        blockers.append(
            ClosureBlocker(
                code="MISSING_CANONICAL_OBLIGATION",
                object_ids=(),
                message="Scope requires an active canonical Requirement, Constraint, or Contract.",
            )
        )

    for gap in state.gaps.values():
        if (
            _gap_applies(gap, state, scope)
            and gap.status is GapStatus.OPEN
            and gap.blocking is True
        ):
            blockers.append(
                ClosureBlocker(
                    code="OPEN_BLOCKING_GAP",
                    object_ids=(gap.id,),
                    message=f"Open blocking gap {gap.id} prevents closure.",
                )
            )

    for obj in current:
        if isinstance(obj, Unknown) and obj.blocking is True:
            blockers.append(
                ClosureBlocker(
                    code="BLOCKING_UNKNOWN",
                    object_ids=(obj.id,),
                    message=f"Blocking unknown {obj.id} remains unresolved.",
                )
            )
        if isinstance(obj, NonGoal) and obj.authority is Authority.CANONICAL:
            # IE2.1 enforces EXPLICIT exclusion edges only. Nothing here infers that a
            # requirement's text collides with a non-goal's text; recognising that is a
            # synthesis-stage obligation. What is guaranteed is narrow and real: once an
            # exclusion is recorded, a canonical object on the other end cannot pass
            # silently, which is what made NonGoal decorative before.
            for relation in obj.relations:
                if relation.relation_type is not RelationType.EXCLUDES:
                    continue
                excluded = state.objects.get(relation.target_id)
                # `current` already means active, not-superseded, not-rejected AND in
                # scope, so membership is the whole liveness test; repeating the scope
                # check here would be a second definition of the same thing.
                if (
                    excluded is not None
                    and excluded in current
                    and excluded.authority is Authority.CANONICAL
                ):
                    blockers.append(
                        ClosureBlocker(
                            code="EXCLUDED_BY_NON_GOAL",
                            object_ids=(obj.id, excluded.id),
                            message=(
                                f"Canonical {excluded.id} is explicitly excluded by "
                                f"non-goal {obj.id}."
                            ),
                        )
                    )
        if isinstance(obj, Conflict) and obj.resolved is False:
            blockers.append(
                ClosureBlocker(
                    code="UNRESOLVED_CONFLICT",
                    object_ids=(obj.id,),
                    message=f"Unresolved conflict {obj.id} prevents closure.",
                )
            )
        if (
            isinstance(obj, Requirement)
            and obj.materiality in MATERIAL_REQUIREMENT_LEVELS
            and obj.authority is not Authority.CANONICAL
        ):
            blockers.append(
                ClosureBlocker(
                    code="NON_CANONICAL_REQUIREMENT",
                    object_ids=(obj.id,),
                    message=f"Material requirement {obj.id} is not canonical.",
                )
            )
        if isinstance(obj, Constraint | Contract) and obj.authority is not Authority.CANONICAL:
            blockers.append(
                ClosureBlocker(
                    code="NON_CANONICAL_OBLIGATION",
                    object_ids=(obj.id,),
                    message=f"Hard obligation {obj.id} is not canonical.",
                )
            )
        if (
            isinstance(obj, Assumption)
            and obj.risk_level in HIGH_RISK_LEVELS
            and not _assumption_is_controlled(obj, state)
        ):
            blockers.append(
                ClosureBlocker(
                    code="UNCONTROLLED_HIGH_RISK_ASSUMPTION",
                    object_ids=(obj.id,),
                    message=f"High-risk assumption {obj.id} is not controlled.",
                )
            )
        if isinstance(obj, Requirement) and obj.authority is Authority.CANONICAL:
            if obj.requires_metric and not _has_valid_metric(obj, state, scope):
                blockers.append(
                    ClosureBlocker(
                        code="MISSING_METRIC",
                        object_ids=(obj.id,),
                        message=f"Canonical requirement {obj.id} has no valid metric.",
                    )
                )
            if obj.requires_verification and not _has_valid_verifier(obj, state, scope):
                blockers.append(
                    ClosureBlocker(
                        code="MISSING_VERIFICATION_OBLIGATION",
                        object_ids=(obj.id,),
                        message=(
                            f"Canonical requirement {obj.id} has no valid verification obligation."
                        ),
                    )
                )

    ordered = tuple(sorted(blockers, key=lambda blocker: (blocker.code, blocker.object_ids)))
    return ClosureResult(scope=scope, closed=len(ordered) == 0, blockers=ordered)


def _is_current(obj: SemanticBase) -> bool:
    return object_is_current(obj)


def _object_applies(obj: SemanticBase, scope: str) -> bool:
    return obj.scope == () or scope in obj.scope


def _gap_applies(gap: Gap | IntentSynthesisGap, state: IntentState, scope: str) -> bool:
    # A synthesis gap states its own scope, so it is authoritative and checked first.
    # Falling through to the affected-object logic would be wrong: an unknown id there
    # counts as applying, which would make a scope-local blocker block every scope.
    if isinstance(gap, IntentSynthesisGap) and gap.scope != () and scope not in gap.scope:
        return False
    if gap.affected_object_ids == ():
        return True
    for object_id in gap.affected_object_ids:
        obj = state.objects.get(object_id)
        if obj is None:
            return True
        if _object_applies(obj, scope):
            return True
    return False


def _assumption_is_controlled(assumption: Assumption, state: IntentState) -> bool:
    return any(
        assumption.id in gap.affected_object_ids
        and gap.status in {GapStatus.RESOLVED, GapStatus.WAIVED}
        for gap in state.gaps.values()
    )


def _has_nonempty_reason(reason: str | None) -> bool:
    return reason is not None and reason.strip() != ""


def _has_valid_metric(requirement: Requirement, state: IntentState, scope: str) -> bool:
    if _has_nonempty_reason(requirement.metric_exempt_reason):
        return True
    return any(
        relation.relation_type is RelationType.MEASURED_BY
        and _is_canonical_target(state, relation.target_id, Metric, scope)
        for relation in requirement.relations
    )


def _has_valid_verifier(requirement: Requirement, state: IntentState, scope: str) -> bool:
    if _has_nonempty_reason(requirement.verification_exempt_reason):
        return True
    return any(
        relation.relation_type is RelationType.VERIFIED_BY
        and _is_canonical_target(state, relation.target_id, VerificationObligation, scope)
        for relation in requirement.relations
    )


def _is_canonical_target(
    state: IntentState,
    target_id: str,
    expected_type: type[Metric] | type[VerificationObligation],
    scope: str,
) -> bool:
    target = state.objects.get(target_id)
    return (
        isinstance(target, expected_type)
        and target.lifecycle is LifecycleStatus.ACTIVE
        and target.authority is Authority.CANONICAL
        and _object_applies(target, scope)
    )
