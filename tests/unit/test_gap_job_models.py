import pytest
from pydantic import ValidationError

from foundry.domain.common import Materiality, RiskLevel
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.jobs import ExecutorClass, Job, JobStatus, JobType


def test_gap_carries_materiality_scope_and_blocking_state() -> None:
    gap = Gap(
        id="GAP-1",
        project_id="PROJ-1",
        kind=GapKind.AMBIGUITY,
        description="The term fast has no threshold.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=("REQ-1",),
        blocking=True,
    )

    assert gap.status is GapStatus.OPEN
    assert gap.blocking is True


def test_job_has_bounded_context_budget_and_executor_classes() -> None:
    job = Job(
        id="JOB-1",
        project_id="PROJ-1",
        gap_id="GAP-1",
        job_type=JobType.AMBIGUITY_ANALYSIS,
        target_object_ids=("REQ-1",),
        output_schema_ref="foundry://schemas/ambiguity-result/v1",
        risk=RiskLevel.HIGH,
        max_context_tokens=8_000,
        permitted_executors=(
            ExecutorClass.CHEAP_MODEL,
            ExecutorClass.STRONG_MODEL,
        ),
        budget_usd=0.25,
        verification_requirement=(
            "Must return a schema-valid ambiguity classification."
        ),
    )

    assert job.status is JobStatus.PENDING
    assert ExecutorClass.FRONTIER_MODEL not in job.permitted_executors
    assert job.attempt == 0


def test_gap_kind_values_match_approved_vocabulary() -> None:
    assert {kind.value for kind in GapKind} == {
        "MISSING_INFORMATION",
        "AMBIGUITY",
        "CONTRADICTION",
        "UNSUPPORTED_ASSUMPTION",
        "MISSING_AUTHORITY",
        "MISSING_SUCCESS_METRIC",
        "MISSING_VERIFICATION_OBLIGATION",
        "UNRESOLVED_RISK",
        "STALE_EVIDENCE",
        "INSUFFICIENT_EVIDENCE",
        "UNDERSPECIFIED_SCOPE",
        "UNRESOLVED_DEPENDENCY",
        "WORKER_DIVERGENCE",
        "CONTEXT_FAILURE",
    }


def test_gap_status_values_match_approved_vocabulary() -> None:
    assert {status.value for status in GapStatus} == {"OPEN", "RESOLVED", "WAIVED"}


def test_executor_class_values_match_approved_vocabulary() -> None:
    assert {executor.value for executor in ExecutorClass} == {
        "DETERMINISTIC",
        "CHEAP_MODEL",
        "STANDARD_MODEL",
        "STRONG_MODEL",
        "FRONTIER_MODEL",
        "HUMAN",
    }


def test_job_type_values_match_approved_vocabulary() -> None:
    assert {job_type.value for job_type in JobType} == {
        "DETERMINISTIC_EXTRACTION",
        "SEMANTIC_CLASSIFICATION",
        "AMBIGUITY_ANALYSIS",
        "CONTRADICTION_ANALYSIS",
        "RESEARCH_PLANNING",
        "EVIDENCE_COLLECTION",
        "EVIDENCE_RECONCILIATION",
        "REQUIREMENT_REFINEMENT",
        "METRIC_DESIGN",
        "VERIFICATION_OBLIGATION_DESIGN",
        "TRADE_OFF_ANALYSIS",
        "STRONG_REASONING_RESOLUTION",
        "HUMAN_CLARIFICATION",
        "HUMAN_AUTHORIZATION",
        "CONTEXT_RECOMPILE",
    }


def test_job_status_values_match_approved_vocabulary() -> None:
    assert {status.value for status in JobStatus} == {
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "ESCALATED",
        "CANCELLED",
    }


def _job(**overrides: object) -> Job:
    payload: dict[str, object] = {
        "id": "JOB-1",
        "project_id": "PROJ-1",
        "gap_id": "GAP-1",
        "job_type": JobType.AMBIGUITY_ANALYSIS,
        "target_object_ids": ("REQ-1",),
        "output_schema_ref": "foundry://schemas/ambiguity-result/v1",
        "risk": RiskLevel.HIGH,
        "max_context_tokens": 8_000,
        "permitted_executors": (ExecutorClass.CHEAP_MODEL,),
        "budget_usd": 0.25,
        "verification_requirement": "Must return a schema-valid ambiguity classification.",
    }
    payload.update(overrides)
    return Job.model_validate(payload)


def test_empty_permitted_executors_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _job(permitted_executors=())


def test_empty_output_schema_ref_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _job(output_schema_ref="")


def test_empty_verification_requirement_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _job(verification_requirement="")


def test_max_context_tokens_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _job(max_context_tokens=0)
    with pytest.raises(ValidationError):
        _job(max_context_tokens=-1)


def test_negative_budget_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _job(budget_usd=-0.01)


def test_zero_budget_is_valid() -> None:
    assert _job(budget_usd=0.0).budget_usd == 0.0


def test_negative_attempt_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _job(attempt=-1)


def test_gap_is_immutable() -> None:
    gap = Gap(
        id="GAP-1",
        project_id="PROJ-1",
        kind=GapKind.AMBIGUITY,
        description="The term fast has no threshold.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=("REQ-1",),
        blocking=True,
    )

    with pytest.raises(ValidationError):
        gap.blocking = False
