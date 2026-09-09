from __future__ import annotations

from foundry.domain.common import (
    Authority,
    FrozenModel,
    LifecycleStatus,
    Materiality,
    RelationType,
    RiskLevel,
)
from foundry.domain.gaps import Gap, GapStatus
from foundry.domain.semantic import Assumption, Conflict, Requirement, SemanticBase, Unknown
from foundry.domain.state import IntentState


class ClosureBlocker(FrozenModel):
    code: str
    object_ids: tuple[str, ...]
    message: str


class ClosureResult(FrozenModel):
    scope: str
    closed: bool
    blockers: tuple[ClosureBlocker, ...]


def _object_in_scope(obj: SemanticBase, scope: str) -> bool:
    return not obj.scope or scope in obj.scope


def _gap_in_scope(gap: Gap, state: IntentState, scope: str) -> bool:
    if not gap.affected_object_ids:
        return True
    for object_id in gap.affected_object_ids:
        obj = state.objects.get(object_id)
        if obj is None or _object_in_scope(obj, scope):
            return True
    return False


def _has_relation(requirement: Requirement, relation_type: RelationType) -> bool:
    return any(relation.relation_type is relation_type for relation in requirement.relations)


def _assumption_is_controlled(assumption: Assumption, state: IntentState, scope: str) -> bool:
    for gap in state.gaps.values():
        if assumption.id not in gap.affected_object_ids:
            continue
        if not _gap_in_scope(gap, state, scope):
            continue
        if gap.status in {GapStatus.RESOLVED, GapStatus.WAIVED}:
            return True
    return False


def evaluate_closure(state: IntentState, scope: str) -> ClosureResult:
    blockers: list[ClosureBlocker] = []

    for gap in state.gaps.values():
        if gap.status is GapStatus.OPEN and gap.blocking and _gap_in_scope(gap, state, scope):
            blockers.append(
                ClosureBlocker(
                    code="OPEN_BLOCKING_GAP",
                    object_ids=(gap.id, *gap.affected_object_ids),
                    message=f"Blocking gap {gap.id} is still open.",
                )
            )

    for obj in state.objects.values():
        if not _object_in_scope(obj, scope) or obj.lifecycle is not LifecycleStatus.ACTIVE:
            continue

        if isinstance(obj, Requirement):
            if obj.materiality is not Materiality.LOW and obj.authority is not Authority.CANONICAL:
                blockers.append(
                    ClosureBlocker(
                        code="NON_CANONICAL_REQUIREMENT",
                        object_ids=(obj.id,),
                        message=f"Material requirement {obj.id} is not canonical.",
                    )
                )
            if (
                obj.requires_metric
                and not obj.metric_exempt_reason
                and not _has_relation(obj, RelationType.MEASURED_BY)
            ):
                blockers.append(
                    ClosureBlocker(
                        code="MISSING_METRIC",
                        object_ids=(obj.id,),
                        message=f"Requirement {obj.id} requires a success metric.",
                    )
                )
            if (
                obj.requires_verification
                and not obj.verification_exempt_reason
                and not _has_relation(obj, RelationType.VERIFIED_BY)
            ):
                blockers.append(
                    ClosureBlocker(
                        code="MISSING_VERIFICATION_OBLIGATION",
                        object_ids=(obj.id,),
                        message=f"Requirement {obj.id} requires a verification obligation.",
                    )
                )

        elif isinstance(obj, Assumption):
            high_risk = obj.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            if high_risk and not _assumption_is_controlled(obj, state, scope):
                blockers.append(
                    ClosureBlocker(
                        code="UNCONTROLLED_HIGH_RISK_ASSUMPTION",
                        object_ids=(obj.id,),
                        message=f"High-risk assumption {obj.id} is not explicitly controlled.",
                    )
                )

        elif isinstance(obj, Conflict) and not obj.resolved:
            blockers.append(
                ClosureBlocker(
                    code="UNRESOLVED_CONFLICT",
                    object_ids=(obj.id, *obj.object_ids),
                    message=f"Conflict {obj.id} is unresolved.",
                )
            )

        elif isinstance(obj, Unknown) and obj.blocking:
            blockers.append(
                ClosureBlocker(
                    code="BLOCKING_UNKNOWN",
                    object_ids=(obj.id,),
                    message=f"Unknown {obj.id} blocks downstream work.",
                )
            )

    ordered = tuple(sorted(blockers, key=lambda blocker: (blocker.code, blocker.object_ids)))
    return ClosureResult(scope=scope, closed=not ordered, blockers=ordered)
