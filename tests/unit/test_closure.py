from datetime import UTC, datetime

from foundry.domain.closure import evaluate_closure
from foundry.domain.common import (
    Authority,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    RiskLevel,
    SourceKind,
)
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.semantic import Assumption, Conflict, Requirement, Unknown
from foundry.domain.state import IntentState

NOW = datetime(2026, 9, 9, tzinfo=UTC)
PROVENANCE = Provenance(
    source_kind=SourceKind.HUMAN,
    source_ref="human://owner",
    source_event_ids=("EVT-1",),
)


def _requirement(**changes: object) -> Requirement:
    values: dict[str, object] = {
        "id": "REQ-1",
        "project_id": "PROJ-1",
        "statement": "The service must remain available.",
        "materiality": Materiality.HIGH,
        "authority": Authority.CANONICAL,
        "confidence": 1.0,
        "provenance": PROVENANCE,
        "created_at": NOW,
    }
    values.update(changes)
    return Requirement.model_validate(values)


def test_open_blocking_gap_prevents_closure() -> None:
    gap = Gap(
        id="GAP-1",
        project_id="PROJ-1",
        kind=GapKind.AMBIGUITY,
        description="Availability threshold is unclear.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=("REQ-1",),
        blocking=True,
    )
    state = IntentState(project_id="PROJ-1", objects={"REQ-1": _requirement()}, gaps={"GAP-1": gap})

    result = evaluate_closure(state, "core")

    assert result.closed is False
    assert "OPEN_BLOCKING_GAP" in {blocker.code for blocker in result.blockers}


def test_non_blocking_unknown_does_not_prevent_closure() -> None:
    unknown = Unknown(
        id="UNK-1",
        project_id="PROJ-1",
        question="Which dashboard style should we use?",
        blocking=False,
        authority=Authority.PROPOSED,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    state = IntentState(project_id="PROJ-1", objects={"UNK-1": unknown})

    assert evaluate_closure(state, "core").closed is True


def test_material_noncanonical_requirement_prevents_closure() -> None:
    requirement = _requirement(authority=Authority.PROPOSED)
    state = IntentState(project_id="PROJ-1", objects={requirement.id: requirement})

    result = evaluate_closure(state, "core")

    assert "NON_CANONICAL_REQUIREMENT" in {blocker.code for blocker in result.blockers}


def test_required_metric_must_be_related_or_explicitly_exempted() -> None:
    requirement = _requirement(requires_metric=True)
    state = IntentState(project_id="PROJ-1", objects={requirement.id: requirement})

    assert "MISSING_METRIC" in {blocker.code for blocker in evaluate_closure(state, "core").blockers}

    exempt = _requirement(requires_metric=True, metric_exempt_reason="Qualitative legal constraint.")
    exempt_state = IntentState(project_id="PROJ-1", objects={exempt.id: exempt})
    assert "MISSING_METRIC" not in {
        blocker.code for blocker in evaluate_closure(exempt_state, "core").blockers
    }


def test_required_verification_must_be_related_or_explicitly_exempted() -> None:
    requirement = _requirement(requires_verification=True)
    state = IntentState(project_id="PROJ-1", objects={requirement.id: requirement})

    assert "MISSING_VERIFICATION_OBLIGATION" in {
        blocker.code for blocker in evaluate_closure(state, "core").blockers
    }

    exempt = _requirement(
        requires_verification=True,
        verification_exempt_reason="Human policy sign-off is the terminal evidence.",
    )
    exempt_state = IntentState(project_id="PROJ-1", objects={exempt.id: exempt})
    assert "MISSING_VERIFICATION_OBLIGATION" not in {
        blocker.code for blocker in evaluate_closure(exempt_state, "core").blockers
    }


def test_metric_and_verification_relations_satisfy_requirements() -> None:
    requirement = _requirement(
        requires_metric=True,
        requires_verification=True,
        relations=(
            Relation(relation_type=RelationType.MEASURED_BY, target_id="METRIC-1"),
            Relation(relation_type=RelationType.VERIFIED_BY, target_id="VERIFY-1"),
        ),
    )
    state = IntentState(project_id="PROJ-1", objects={requirement.id: requirement})

    codes = {blocker.code for blocker in evaluate_closure(state, "core").blockers}
    assert "MISSING_METRIC" not in codes
    assert "MISSING_VERIFICATION_OBLIGATION" not in codes


def test_high_risk_assumption_requires_explicit_control() -> None:
    assumption = Assumption(
        id="ASSUME-1",
        project_id="PROJ-1",
        statement="The upstream provider is always reachable.",
        risk_level=RiskLevel.HIGH,
        authority=Authority.PROPOSED,
        confidence=0.5,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    state = IntentState(project_id="PROJ-1", objects={assumption.id: assumption})
    assert "UNCONTROLLED_HIGH_RISK_ASSUMPTION" in {
        blocker.code for blocker in evaluate_closure(state, "core").blockers
    }

    control = Gap(
        id="GAP-A1",
        project_id="PROJ-1",
        kind=GapKind.UNSUPPORTED_ASSUMPTION,
        description="Assumption reviewed and explicitly accepted.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=(assumption.id,),
        blocking=True,
        status=GapStatus.WAIVED,
        resolution_event_id="EVT-WAIVE",
    )
    controlled = IntentState(
        project_id="PROJ-1",
        objects={assumption.id: assumption},
        gaps={control.id: control},
    )
    assert "UNCONTROLLED_HIGH_RISK_ASSUMPTION" not in {
        blocker.code for blocker in evaluate_closure(controlled, "core").blockers
    }


def test_unresolved_conflict_and_blocking_unknown_prevent_closure() -> None:
    conflict = Conflict(
        id="CONFLICT-1",
        project_id="PROJ-1",
        statement="Two retention periods disagree.",
        object_ids=("REQ-A", "REQ-B"),
        resolved=False,
        authority=Authority.DISPUTED,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    unknown = Unknown(
        id="UNK-1",
        project_id="PROJ-1",
        question="Which jurisdiction governs retention?",
        blocking=True,
        authority=Authority.PROPOSED,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=NOW,
    )
    state = IntentState(
        project_id="PROJ-1",
        objects={conflict.id: conflict, unknown.id: unknown},
    )

    codes = {blocker.code for blocker in evaluate_closure(state, "core").blockers}
    assert "UNRESOLVED_CONFLICT" in codes
    assert "BLOCKING_UNKNOWN" in codes
