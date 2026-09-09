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
        permitted_executors=(ExecutorClass.CHEAP_MODEL, ExecutorClass.STRONG_MODEL),
        budget_usd=0.25,
        verification_requirement="Must return a schema-valid ambiguity classification.",
    )

    assert job.status is JobStatus.PENDING
    assert ExecutorClass.FRONTIER_MODEL not in job.permitted_executors
