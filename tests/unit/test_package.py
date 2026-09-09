from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.application.package import (
    IntentNotClosedError,
    build_intent_package,
)
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    RiskLevel,
    SourceKind,
)
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


def _state(*objects: object, **overrides: object) -> IntentState:
    return IntentState(
        project_id="PROJ-1",
        objects={obj.id: obj for obj in objects},  # type: ignore[union-attr]
        **overrides,
    )


def _closed(*objects: object, **overrides: object) -> IntentState:
    return _state(_intent(), _constraint(), *objects, **overrides)


def test_package_uses_project_id_revision_and_history_order() -> None:
    state = _closed(revision=7, source_events=("EVT-2", "EVT-1", "EVT-3"))
    package = build_intent_package(state, SCOPE)
    assert package.project_id == "PROJ-1"
    assert package.intent_version == 7
    assert package.scope == SCOPE
    assert package.history_event_ids == ("EVT-2", "EVT-1", "EVT-3")


def test_purpose_and_boundary_include_current_noncanonical_signals() -> None:
    state = _closed(
        Goal(
            **_base(id="GOAL-B", statement="Survive regional loss.", authority=Authority.PROPOSED)
        ),
        Actor(**_base(id="ACTOR-A", name="Operator", description="Runs failover.")),
        Outcome(**_base(id="OUT-A", statement="Checkout remains available.")),
        NonGoal(**_base(id="NG-A", statement="No multi-cloud rewrite.")),
        Preference(
            **_base(id="PREF-A", statement="Prefer active-active.", authority=Authority.INFERRED)
        ),
    )
    package = build_intent_package(state, SCOPE)
    assert package.purpose_ids == ("ACTOR-A", "GOAL-B", "INTENT-1", "OUT-A")
    assert package.boundary_ids == ("NG-A", "PREF-A")


def test_obligation_ids_include_only_canonical_hard_obligations() -> None:
    proposed = Requirement(
        **_base(
            id="REQ-P",
            statement="Nice to have.",
            materiality=Materiality.LOW,
            requires_metric=False,
            requires_verification=False,
            authority=Authority.PROPOSED,
        )
    )
    canonical_req = Requirement(
        **_base(
            id="REQ-C",
            statement="Must remain available.",
            materiality=Materiality.HIGH,
            requires_metric=False,
            requires_verification=False,
        )
    )
    contract = Contract(**_base(id="CTR-1", statement="Observable failover.", observable=True))
    package = build_intent_package(_closed(proposed, canonical_req, contract), SCOPE)
    assert package.obligation_ids == ("CON-1", "CTR-1", "REQ-C")


def test_decision_buckets_and_supersession() -> None:
    canonical = Decision(
        **_base(id="DEC-C", statement="Use two regions.", rationale="Availability.")
    )
    proposed = Decision(
        **_base(
            id="DEC-P",
            statement="Maybe three regions.",
            rationale="Extra.",
            authority=Authority.PROPOSED,
        )
    )
    disputed = Decision(
        **_base(
            id="DEC-D", statement="Use one region.", rationale="Cost.", authority=Authority.DISPUTED
        )
    )
    superseded_life = Decision(
        **_base(
            id="DEC-SL",
            statement="Old topology.",
            rationale="Replaced.",
            lifecycle=LifecycleStatus.SUPERSEDED,
        )
    )
    superseded_auth = Decision(
        **_base(
            id="DEC-SA",
            statement="Old auth.",
            rationale="Replaced.",
            authority=Authority.SUPERSEDED,
        )
    )
    rejected = Decision(
        **_base(
            id="DEC-R",
            statement="Rejected topology.",
            rationale="Unsafe.",
            authority=Authority.REJECTED,
        )
    )
    package = build_intent_package(
        _closed(canonical, proposed, disputed, superseded_life, superseded_auth, rejected),
        SCOPE,
    )
    assert package.canonical_decision_ids == ("DEC-C",)
    assert package.proposed_decision_ids == ("DEC-D", "DEC-P")
    assert package.superseded_decision_ids == ("DEC-SA", "DEC-SL")
    assert "DEC-R" not in package.canonical_decision_ids
    assert "DEC-R" not in package.proposed_decision_ids
    assert "DEC-R" not in package.superseded_decision_ids


def test_epistemic_quality_and_governance_mapping() -> None:
    assumption = Assumption(
        **_base(id="ASM-1", statement="Regions fail independently.", risk_level=RiskLevel.LOW)
    )
    claim = Claim(
        **_base(id="CLAIM-1", statement="Retries are three.", authority=Authority.INFERRED)
    )
    evidence = Evidence(
        **_base(
            id="EVD-1",
            statement="Code shows three retries.",
            retrieved_at=OCCURRED_AT,
            authority=Authority.OBSERVED,
        )
    )
    unknown = Unknown(**_base(id="UNK-1", question="Preferred color?", blocking=False))
    question = Question(**_base(id="Q-1", prompt="What is the SLO?", target_object_ids=("REQ-C",)))
    conflict = Conflict(
        **_base(
            id="CFL-1",
            statement="Two SLOs.",
            object_ids=("REQ-C",),
            resolved=True,
            authority=Authority.DISPUTED,
        )
    )
    metric = Metric(**_base(id="METRIC-1", name="interruption", definition="Loss.", target="<1%"))
    proposed_metric = Metric(
        **_base(
            id="METRIC-P",
            name="other",
            definition="Other.",
            target="<2%",
            authority=Authority.PROPOSED,
        )
    )
    verifier = VerificationObligation(
        **_base(
            id="VRF-1", statement="Simulate loss.", target_object_ids=("REQ-C",), method_class="sim"
        )
    )
    risk = Risk(**_base(id="RISK-1", statement="Regional outage.", risk_level=RiskLevel.HIGH))
    authority_record = AuthorityRecord(
        **_base(id="AUTH-1", subject_id="CON-1", authorized_by="OWNER", rationale="Owner signed.")
    )
    amendment = Amendment(
        **_base(
            id="AMD-1",
            subject_id="CON-1",
            change_statement="Tighten SLO.",
            rationale="New evidence.",
        )
    )
    package = build_intent_package(
        _closed(
            assumption,
            claim,
            evidence,
            unknown,
            question,
            conflict,
            metric,
            proposed_metric,
            verifier,
            risk,
            authority_record,
            amendment,
        ),
        SCOPE,
    )
    assert package.epistemic_ids == ("ASM-1", "CFL-1", "CLAIM-1", "EVD-1", "Q-1", "UNK-1")
    assert package.quality_ids == ("METRIC-1", "VRF-1")
    assert package.governance_ids == ("AMD-1", "AUTH-1", "RISK-1")


def test_scope_filtering_excludes_out_of_scope_objects() -> None:
    other_goal = Goal(**_base(id="GOAL-X", statement="Other work.", scope=("other",)))
    package = build_intent_package(_closed(other_goal), SCOPE)
    assert "GOAL-X" not in package.purpose_ids


def test_ids_are_sorted_except_history() -> None:
    state = _closed(
        Goal(**_base(id="GOAL-Z", statement="Z")),
        Goal(**_base(id="GOAL-A", statement="A")),
        source_events=("EVT-9", "EVT-1"),
    )
    package = build_intent_package(state, SCOPE)
    assert package.purpose_ids == ("GOAL-A", "GOAL-Z", "INTENT-1")
    assert package.history_event_ids == ("EVT-9", "EVT-1")


def test_insertion_order_does_not_change_package() -> None:
    first = _closed(
        Goal(**_base(id="GOAL-Z", statement="Z")),
        Goal(**_base(id="GOAL-A", statement="A")),
        revision=3,
        source_events=("EVT-1", "EVT-2"),
    )
    second = IntentState(
        project_id="PROJ-1",
        revision=3,
        source_events=("EVT-1", "EVT-2"),
        objects={
            "GOAL-A": Goal(**_base(id="GOAL-A", statement="A")),
            "CON-1": _constraint(),
            "GOAL-Z": Goal(**_base(id="GOAL-Z", statement="Z")),
            "INTENT-1": _intent(),
        },
    )
    package_a = build_intent_package(first, SCOPE)
    package_b = build_intent_package(second, SCOPE)
    assert package_a == package_b
    assert package_a.model_dump_json() == package_b.model_dump_json()


def test_package_is_immutable() -> None:
    package = build_intent_package(_closed(), SCOPE)
    with pytest.raises(ValidationError):
        package.scope = "other"


def test_build_intent_package_does_not_mutate_state() -> None:
    state = _closed(revision=2, source_events=("EVT-1",))
    snapshot = state.model_dump()
    build_intent_package(state, SCOPE)
    assert state.model_dump() == snapshot


def test_build_intent_package_refuses_open_state() -> None:
    with pytest.raises(IntentNotClosedError) as raised:
        build_intent_package(_state(_intent()), SCOPE)
    assert raised.value.blocker_codes == ("MISSING_CANONICAL_OBLIGATION",)


def test_intent_not_closed_error_codes_are_unique_and_sorted() -> None:
    with pytest.raises(IntentNotClosedError) as raised:
        build_intent_package(IntentState(project_id="PROJ-1"), SCOPE)
    assert raised.value.blocker_codes == (
        "MISSING_CANONICAL_INTENT",
        "MISSING_CANONICAL_OBLIGATION",
    )


def test_closed_scopes_do_not_authorize_package_build() -> None:
    with pytest.raises(IntentNotClosedError):
        build_intent_package(_state(_intent(), closed_scopes={SCOPE: 1}), SCOPE)
