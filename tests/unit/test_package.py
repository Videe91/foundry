from datetime import UTC, datetime

import pytest

from foundry.application.package import IntentNotClosedError, build_intent_package
from foundry.domain.common import (
    Authority,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    RiskLevel,
    SourceKind,
)
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.semantic import Goal, Intent, Metric, Requirement, VerificationObligation
from foundry.domain.state import IntentState

NOW = datetime(2026, 9, 9, tzinfo=UTC)
PROVENANCE = Provenance(
    source_kind=SourceKind.HUMAN,
    source_ref="human://owner",
    source_event_ids=("EVT-1",),
)


def _closed_state() -> IntentState:
    intent = Intent(
        id="INTENT-1",
        project_id="PROJ-1",
        mission="Keep the service available through regional loss.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    goal = Goal(
        id="GOAL-1",
        project_id="PROJ-1",
        statement="Survive loss of one region.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    metric = Metric(
        id="METRIC-1",
        project_id="PROJ-1",
        name="Regional loss interruption",
        definition="Maximum service interruption during a regional-loss exercise.",
        target="<= 5 seconds",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    verification = VerificationObligation(
        id="VERIFY-1",
        project_id="PROJ-1",
        statement="Simulate loss of one region and measure interruption.",
        target_object_ids=("REQ-1",),
        method_class="failure-simulation",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    requirement = Requirement(
        id="REQ-1",
        project_id="PROJ-1",
        statement="The service must survive loss of one region.",
        materiality=Materiality.CRITICAL,
        requires_metric=True,
        requires_verification=True,
        relations=(
            Relation(relation_type=RelationType.MEASURED_BY, target_id=metric.id),
            Relation(relation_type=RelationType.VERIFIED_BY, target_id=verification.id),
        ),
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    return IntentState(
        project_id="PROJ-1",
        revision=5,
        last_sequence=5,
        source_events=("EVT-1", "EVT-2", "EVT-3", "EVT-4", "EVT-5"),
        objects={
            intent.id: intent,
            goal.id: goal,
            requirement.id: requirement,
            metric.id: metric,
            verification.id: verification,
        },
    )


def test_package_is_deterministic_projection_of_closed_state() -> None:
    state = _closed_state()

    first = build_intent_package(state, "core")
    second = build_intent_package(state, "core")

    assert first == second
    assert first.project_id == "PROJ-1"
    assert first.intent_version == 5
    assert first.purpose_ids == ("GOAL-1", "INTENT-1")
    assert first.obligation_ids == ("REQ-1",)
    assert first.quality_ids == ("METRIC-1", "VERIFY-1")
    assert first.history_event_ids == state.source_events


def test_package_cannot_be_built_while_intent_is_open() -> None:
    state = _closed_state()
    gap = Gap(
        id="GAP-1",
        project_id="PROJ-1",
        kind=GapKind.AMBIGUITY,
        description="Failover threshold is ambiguous.",
        materiality=Materiality.CRITICAL,
        risk=RiskLevel.CRITICAL,
        affected_object_ids=("REQ-1",),
        blocking=True,
    )
    open_state = state.model_copy(update={"gaps": {gap.id: gap}})

    with pytest.raises(IntentNotClosedError, match="OPEN_BLOCKING_GAP"):
        build_intent_package(open_state, "core")
