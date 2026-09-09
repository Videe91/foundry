from datetime import UTC, datetime

from foundry.domain.closure import evaluate_closure
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    RiskLevel,
    SourceKind,
)
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.semantic import (
    Assumption,
    Conflict,
    Constraint,
    Contract,
    Intent,
    Metric,
    Requirement,
    Unknown,
    VerificationObligation,
)
from foundry.domain.state import IntentState

OCCURRED_AT = datetime(2026, 9, 9, tzinfo=UTC)
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref="human://owner")
SCOPE = "core"


def _base(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": "PROJ-1",
        "authority": Authority.CANONICAL,
        "confidence": 1.0,
        "provenance": PROVENANCE,
        "created_at": OCCURRED_AT,
    }
    payload.update(overrides)
    return payload


def _intent(**overrides: object) -> Intent:
    payload = _base(id="INTENT-1", mission="Keep payments available.")
    payload.update(overrides)
    return Intent(**payload)


def _constraint(**overrides: object) -> Constraint:
    payload = _base(id="CON-1", statement="No single-region dependency.")
    payload.update(overrides)
    return Constraint(**payload)


def _requirement(**overrides: object) -> Requirement:
    payload = _base(
        id="REQ-1",
        statement="Regional loss must not interrupt service.",
        materiality=Materiality.HIGH,
        requires_metric=False,
        requires_verification=False,
    )
    payload.update(overrides)
    return Requirement(**payload)


def _state(*objects: object, gaps: tuple[Gap, ...] = (), **overrides: object) -> IntentState:
    return IntentState(
        project_id="PROJ-1",
        objects={obj.id: obj for obj in objects},  # type: ignore[union-attr]
        gaps={gap.id: gap for gap in gaps},
        **overrides,
    )


def _closed_state(**overrides: object) -> IntentState:
    return _state(_intent(), _constraint(), **overrides)


def _gap(**overrides: object) -> Gap:
    payload: dict[str, object] = {
        "id": "GAP-1",
        "project_id": "PROJ-1",
        "kind": GapKind.AMBIGUITY,
        "description": "The term fast has no threshold.",
        "materiality": Materiality.HIGH,
        "risk": RiskLevel.HIGH,
        "affected_object_ids": (),
        "blocking": True,
        "status": GapStatus.OPEN,
    }
    payload.update(overrides)
    return Gap(**payload)


def test_empty_state_is_not_closed() -> None:
    result = evaluate_closure(IntentState(project_id="PROJ-1"), SCOPE)
    assert result.closed is False
    codes = [blocker.code for blocker in result.blockers]
    assert "MISSING_CANONICAL_INTENT" in codes
    assert "MISSING_CANONICAL_OBLIGATION" in codes


def test_missing_canonical_intent_blocks() -> None:
    result = evaluate_closure(_state(_constraint()), SCOPE)
    assert result.closed is False
    assert any(blocker.code == "MISSING_CANONICAL_INTENT" for blocker in result.blockers)


def test_missing_canonical_obligation_blocks() -> None:
    result = evaluate_closure(_state(_intent()), SCOPE)
    assert result.closed is False
    assert any(blocker.code == "MISSING_CANONICAL_OBLIGATION" for blocker in result.blockers)


def test_minimum_canonical_intent_and_obligation_can_close() -> None:
    result = evaluate_closure(_closed_state(), SCOPE)
    assert result.closed is True
    assert result.blockers == ()
    assert result.scope == SCOPE


def test_open_blocking_gap_blocks() -> None:
    result = evaluate_closure(_closed_state(gaps=(_gap(),)), SCOPE)
    assert result.closed is False
    assert any(
        blocker.code == "OPEN_BLOCKING_GAP" and blocker.object_ids == ("GAP-1",)
        for blocker in result.blockers
    )


def test_scope_specific_gap_does_not_block_unrelated_scope() -> None:
    requirement = _requirement(scope=("core",))
    gap = _gap(affected_object_ids=("REQ-1",))
    state = _state(_intent(), _constraint(), requirement, gaps=(gap,))
    result = evaluate_closure(state, "other")
    assert result.closed is True


def test_project_wide_gap_blocks_every_scope() -> None:
    result = evaluate_closure(_closed_state(gaps=(_gap(affected_object_ids=()),)), "other")
    assert result.closed is False
    assert any(blocker.code == "OPEN_BLOCKING_GAP" for blocker in result.blockers)


def test_gap_referencing_missing_object_is_conservatively_applicable() -> None:
    gap = _gap(affected_object_ids=("REQ-MISSING",))
    result = evaluate_closure(_closed_state(gaps=(gap,)), SCOPE)
    assert result.closed is False
    assert any(blocker.code == "OPEN_BLOCKING_GAP" for blocker in result.blockers)


def test_blocking_unknown_blocks_and_non_blocking_unknown_does_not() -> None:
    blocking = Unknown(**_base(id="UNK-1", question="What is the threshold?", blocking=True))
    non_blocking = Unknown(**_base(id="UNK-2", question="Preferred color?", blocking=False))
    blocked = evaluate_closure(_state(_intent(), _constraint(), blocking), SCOPE)
    allowed = evaluate_closure(_state(_intent(), _constraint(), non_blocking), SCOPE)
    assert any(blocker.code == "BLOCKING_UNKNOWN" for blocker in blocked.blockers)
    assert allowed.closed is True


def test_material_noncanonical_requirement_blocks() -> None:
    for materiality in (Materiality.MEDIUM, Materiality.HIGH, Materiality.CRITICAL):
        requirement = _requirement(
            id=f"REQ-{materiality}",
            materiality=materiality,
            authority=Authority.PROPOSED,
        )
        result = evaluate_closure(_state(_intent(), _constraint(), requirement), SCOPE)
        assert any(blocker.code == "NON_CANONICAL_REQUIREMENT" for blocker in result.blockers)


def test_low_noncanonical_requirement_does_not_trigger_requirement_blocker() -> None:
    requirement = _requirement(materiality=Materiality.LOW, authority=Authority.PROPOSED)
    result = evaluate_closure(_state(_intent(), _constraint(), requirement), SCOPE)
    assert result.closed is True
    assert all(blocker.code != "NON_CANONICAL_REQUIREMENT" for blocker in result.blockers)


def test_noncanonical_constraint_blocks() -> None:
    constraint = _constraint(authority=Authority.PROPOSED)
    result = evaluate_closure(_state(_intent(), constraint, _requirement()), SCOPE)
    assert any(blocker.code == "NON_CANONICAL_OBLIGATION" for blocker in result.blockers)


def test_noncanonical_contract_blocks() -> None:
    contract = Contract(**_base(id="CTR-1", statement="Must stay observable.", observable=True))
    proposed = Contract(
        **_base(
            id="CTR-2",
            statement="Must stay observable.",
            observable=True,
            authority=Authority.PROPOSED,
        )
    )
    result = evaluate_closure(_state(_intent(), contract, proposed), SCOPE)
    assert any(
        blocker.code == "NON_CANONICAL_OBLIGATION" and blocker.object_ids == ("CTR-2",)
        for blocker in result.blockers
    )


def test_valid_canonical_metric_relation_closes() -> None:
    metric = Metric(
        **_base(id="METRIC-1", name="interruption", definition="Regional loss.", target="< 1%")
    )
    requirement = _requirement(
        requires_metric=True,
        relations=(Relation(relation_type=RelationType.MEASURED_BY, target_id="METRIC-1"),),
    )
    result = evaluate_closure(_state(_intent(), requirement, metric), SCOPE)
    assert result.closed is True


def test_missing_metric_blocks() -> None:
    requirement = _requirement(requires_metric=True)
    result = evaluate_closure(_state(_intent(), requirement), SCOPE)
    assert any(blocker.code == "MISSING_METRIC" for blocker in result.blockers)


def test_wrong_kind_metric_relation_target_blocks() -> None:
    requirement = _requirement(
        requires_metric=True,
        relations=(Relation(relation_type=RelationType.MEASURED_BY, target_id="CON-1"),),
    )
    result = evaluate_closure(_state(_intent(), requirement, _constraint()), SCOPE)
    assert any(blocker.code == "MISSING_METRIC" for blocker in result.blockers)


def test_proposed_metric_target_blocks() -> None:
    metric = Metric(
        **_base(
            id="METRIC-1",
            name="interruption",
            definition="Regional loss.",
            target="< 1%",
            authority=Authority.PROPOSED,
        )
    )
    requirement = _requirement(
        requires_metric=True,
        relations=(Relation(relation_type=RelationType.MEASURED_BY, target_id="METRIC-1"),),
    )
    result = evaluate_closure(_state(_intent(), requirement, metric), SCOPE)
    assert any(blocker.code == "MISSING_METRIC" for blocker in result.blockers)


def test_out_of_scope_metric_target_blocks() -> None:
    metric = Metric(
        **_base(
            id="METRIC-1",
            name="interruption",
            definition="Regional loss.",
            target="< 1%",
            scope=("other",),
        )
    )
    requirement = _requirement(
        requires_metric=True,
        relations=(Relation(relation_type=RelationType.MEASURED_BY, target_id="METRIC-1"),),
    )
    result = evaluate_closure(_state(_intent(), requirement, metric), SCOPE)
    assert any(blocker.code == "MISSING_METRIC" for blocker in result.blockers)


def test_metric_exemption_closes() -> None:
    requirement = _requirement(requires_metric=True, metric_exempt_reason="Qualitative only.")
    result = evaluate_closure(_state(_intent(), requirement), SCOPE)
    assert result.closed is True


def test_whitespace_only_metric_exemption_is_rejected() -> None:
    requirement = _requirement(requires_metric=True, metric_exempt_reason="   ")
    result = evaluate_closure(_state(_intent(), requirement), SCOPE)
    assert any(blocker.code == "MISSING_METRIC" for blocker in result.blockers)


def test_valid_canonical_verification_obligation_closes() -> None:
    verifier = VerificationObligation(
        **_base(
            id="VRF-1",
            statement="Simulate regional loss.",
            target_object_ids=("REQ-1",),
            method_class="simulation",
        )
    )
    requirement = _requirement(
        requires_verification=True,
        relations=(Relation(relation_type=RelationType.VERIFIED_BY, target_id="VRF-1"),),
    )
    result = evaluate_closure(_state(_intent(), requirement, verifier), SCOPE)
    assert result.closed is True


def test_missing_verifier_blocks() -> None:
    requirement = _requirement(requires_verification=True)
    result = evaluate_closure(_state(_intent(), requirement), SCOPE)
    assert any(blocker.code == "MISSING_VERIFICATION_OBLIGATION" for blocker in result.blockers)


def test_wrong_kind_verifier_blocks() -> None:
    metric = Metric(
        **_base(id="METRIC-1", name="interruption", definition="Regional loss.", target="< 1%")
    )
    requirement = _requirement(
        requires_verification=True,
        relations=(Relation(relation_type=RelationType.VERIFIED_BY, target_id="METRIC-1"),),
    )
    result = evaluate_closure(_state(_intent(), requirement, metric), SCOPE)
    assert any(blocker.code == "MISSING_VERIFICATION_OBLIGATION" for blocker in result.blockers)


def test_proposed_verifier_blocks() -> None:
    verifier = VerificationObligation(
        **_base(
            id="VRF-1",
            statement="Simulate regional loss.",
            target_object_ids=("REQ-1",),
            method_class="simulation",
            authority=Authority.PROPOSED,
        )
    )
    requirement = _requirement(
        requires_verification=True,
        relations=(Relation(relation_type=RelationType.VERIFIED_BY, target_id="VRF-1"),),
    )
    result = evaluate_closure(_state(_intent(), requirement, verifier), SCOPE)
    assert any(blocker.code == "MISSING_VERIFICATION_OBLIGATION" for blocker in result.blockers)


def test_verification_exemption_closes() -> None:
    requirement = _requirement(
        requires_verification=True,
        verification_exempt_reason="Owner accepted qualitative proof.",
    )
    result = evaluate_closure(_state(_intent(), requirement), SCOPE)
    assert result.closed is True


def test_whitespace_only_verification_exemption_is_rejected() -> None:
    requirement = _requirement(requires_verification=True, verification_exempt_reason="\n")
    result = evaluate_closure(_state(_intent(), requirement), SCOPE)
    assert any(blocker.code == "MISSING_VERIFICATION_OBLIGATION" for blocker in result.blockers)


def test_uncontrolled_high_and_critical_assumptions_block() -> None:
    high = Assumption(
        **_base(id="ASM-HIGH", statement="Region fails independently.", risk_level=RiskLevel.HIGH)
    )
    critical = Assumption(
        **_base(
            id="ASM-CRIT", statement="Failover is instantaneous.", risk_level=RiskLevel.CRITICAL
        )
    )
    high_result = evaluate_closure(_state(_intent(), _constraint(), high), SCOPE)
    critical_result = evaluate_closure(_state(_intent(), _constraint(), critical), SCOPE)
    assert any(
        blocker.code == "UNCONTROLLED_HIGH_RISK_ASSUMPTION" for blocker in high_result.blockers
    )
    assert any(
        blocker.code == "UNCONTROLLED_HIGH_RISK_ASSUMPTION" for blocker in critical_result.blockers
    )


def test_resolved_or_waived_gap_controls_assumption_but_open_gap_does_not() -> None:
    assumption = Assumption(
        **_base(id="ASM-1", statement="Region fails independently.", risk_level=RiskLevel.HIGH)
    )
    resolved = _gap(
        id="GAP-RES", affected_object_ids=("ASM-1",), status=GapStatus.RESOLVED, blocking=False
    )
    waived = _gap(
        id="GAP-WAV", affected_object_ids=("ASM-1",), status=GapStatus.WAIVED, blocking=False
    )
    opened = _gap(
        id="GAP-OPEN", affected_object_ids=("ASM-1",), status=GapStatus.OPEN, blocking=False
    )
    assert (
        evaluate_closure(
            _state(_intent(), _constraint(), assumption, gaps=(resolved,)), SCOPE
        ).closed
        is True
    )
    assert (
        evaluate_closure(_state(_intent(), _constraint(), assumption, gaps=(waived,)), SCOPE).closed
        is True
    )
    opened_result = evaluate_closure(
        _state(_intent(), _constraint(), assumption, gaps=(opened,)), SCOPE
    )
    assert any(
        blocker.code == "UNCONTROLLED_HIGH_RISK_ASSUMPTION" for blocker in opened_result.blockers
    )


def test_low_and_medium_assumptions_do_not_trigger_high_risk_blocker() -> None:
    low = Assumption(
        **_base(id="ASM-LOW", statement="Users prefer email.", risk_level=RiskLevel.LOW)
    )
    medium = Assumption(
        **_base(id="ASM-MED", statement="Traffic is diurnal.", risk_level=RiskLevel.MEDIUM)
    )
    result = evaluate_closure(_state(_intent(), _constraint(), low, medium), SCOPE)
    assert result.closed is True
    assert all(blocker.code != "UNCONTROLLED_HIGH_RISK_ASSUMPTION" for blocker in result.blockers)


def test_unresolved_conflict_blocks_and_resolved_conflict_does_not() -> None:
    unresolved = Conflict(
        **_base(
            id="CFL-1",
            statement="Two availability definitions.",
            object_ids=("REQ-1",),
            resolved=False,
        )
    )
    resolved = Conflict(
        **_base(
            id="CFL-2",
            statement="Resolved availability definition.",
            object_ids=("REQ-1",),
            resolved=True,
        )
    )
    blocked = evaluate_closure(_state(_intent(), _constraint(), unresolved), SCOPE)
    allowed = evaluate_closure(_state(_intent(), _constraint(), resolved), SCOPE)
    assert any(blocker.code == "UNRESOLVED_CONFLICT" for blocker in blocked.blockers)
    assert allowed.closed is True


def test_closed_scopes_does_not_override_current_blockers() -> None:
    result = evaluate_closure(
        _state(_intent(), closed_scopes={SCOPE: 4}),
        SCOPE,
    )
    assert result.closed is False
    assert any(blocker.code == "MISSING_CANONICAL_OBLIGATION" for blocker in result.blockers)


def test_absence_from_closed_scopes_does_not_force_open() -> None:
    result = evaluate_closure(_closed_state(), SCOPE)
    assert result.closed is True
    assert result.blockers == ()


def test_blockers_are_sorted_deterministically() -> None:
    unknown = Unknown(**_base(id="UNK-Z", question="Threshold?", blocking=True))
    gap_b = _gap(id="GAP-B")
    gap_a = _gap(id="GAP-A")
    result = evaluate_closure(_state(_intent(), unknown, gaps=(gap_b, gap_a)), SCOPE)
    keys = [(blocker.code, blocker.object_ids) for blocker in result.blockers]
    assert keys == sorted(keys)
    assert [
        blocker.object_ids for blocker in result.blockers if blocker.code == "OPEN_BLOCKING_GAP"
    ] == [
        ("GAP-A",),
        ("GAP-B",),
    ]


def test_rejected_and_superseded_objects_do_not_block() -> None:
    rejected = _requirement(
        id="REQ-REJ", authority=Authority.REJECTED, materiality=Materiality.CRITICAL
    )
    superseded = _requirement(
        id="REQ-SUP",
        authority=Authority.CANONICAL,
        lifecycle=LifecycleStatus.SUPERSEDED,
        materiality=Materiality.CRITICAL,
        requires_metric=True,
    )
    result = evaluate_closure(_state(_intent(), _constraint(), rejected, superseded), SCOPE)
    assert result.closed is True
