from datetime import UTC, datetime

import pytest

from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    RiskLevel,
    SourceKind,
)
from foundry.domain.events import (
    ClosurePayload,
    EventEnvelope,
    EventPayload,
    EventType,
    GapPayload,
    GapResolvedPayload,
    GapWaivedPayload,
    JobPayload,
    JobStatusChangedPayload,
    ReopenPayload,
    SemanticObjectPayload,
    StoredEvent,
    SupersessionPayload,
    UserStatedIntentPayload,
)
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.jobs import ExecutorClass, Job, JobStatus, JobType
from foundry.domain.semantic import Amendment, AuthorityRecord, Claim, Intent, Requirement
from foundry.domain.state import IntentState

OCCURRED_AT = datetime(2026, 9, 9, tzinfo=UTC)


def _provenance() -> Provenance:
    return Provenance(
        source_kind=SourceKind.CODE,
        source_ref="repo://svc/retry.py#L1-L5",
        source_event_ids=("EVT-1",),
    )


def _claim() -> Claim:
    return Claim(
        id="CLAIM-1",
        project_id="PROJ-1",
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def _requirement(*, object_id: str, statement: str) -> Requirement:
    return Requirement(
        id=object_id,
        project_id="PROJ-1",
        statement=statement,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref="human://owner",
            source_event_ids=("EVT-REQ",),
        ),
        created_at=OCCURRED_AT,
        materiality=Materiality.HIGH,
        requires_metric=True,
        requires_verification=True,
    )


def _gap() -> Gap:
    return Gap(
        id="GAP-1",
        project_id="PROJ-1",
        kind=GapKind.AMBIGUITY,
        description="The term fast has no threshold.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=("REQ-1",),
        blocking=True,
    )


def _job() -> Job:
    return Job(
        id="JOB-1",
        project_id="PROJ-1",
        gap_id="GAP-1",
        job_type=JobType.AMBIGUITY_ANALYSIS,
        target_object_ids=("REQ-1",),
        output_schema_ref="foundry://schemas/ambiguity-result/v1",
        risk=RiskLevel.HIGH,
        max_context_tokens=8_000,
        permitted_executors=(ExecutorClass.CHEAP_MODEL,),
        budget_usd=0.25,
        verification_requirement="Must return a schema-valid ambiguity classification.",
    )


def _stored(
    sequence: int,
    event_id: str,
    event_type: EventType,
    payload: EventPayload,
    *,
    project_id: str = "PROJ-1",
) -> StoredEvent:
    return StoredEvent(
        sequence=sequence,
        event=EventEnvelope(
            event_id=event_id,
            project_id=project_id,
            event_type=event_type,
            occurred_at=OCCURRED_AT,
            payload=payload,
        ),
    )


def test_replay_is_deterministic() -> None:
    claim = _claim()
    event = _stored(
        1,
        "EVT-2",
        EventType.CLAIM_INFERRED,
        SemanticObjectPayload(object=claim),
    )

    first = replay("PROJ-1", [event])
    second = replay("PROJ-1", [event])

    assert first == second
    assert first.objects["CLAIM-1"] == claim
    assert first.last_sequence == 1


def test_replay_json_is_byte_identical() -> None:
    event = _stored(
        1,
        "EVT-2",
        EventType.CLAIM_INFERRED,
        SemanticObjectPayload(object=_claim()),
    )

    first = replay("PROJ-1", [event])
    second = replay("PROJ-1", [event])

    assert first.model_dump_json() == second.model_dump_json()


def test_wrong_project_raises_value_error() -> None:
    event = _stored(
        1,
        "EVT-2",
        EventType.USER_STATED_INTENT,
        UserStatedIntentPayload(text="Need login.", actor_id="OWNER"),
        project_id="PROJ-B",
    )
    with pytest.raises(ValueError):
        reduce_event(IntentState(project_id="PROJ-A"), event)


def test_sequence_gap_raises_value_error() -> None:
    event = _stored(
        2,
        "EVT-2",
        EventType.CLAIM_INFERRED,
        SemanticObjectPayload(object=_claim()),
    )
    with pytest.raises(ValueError):
        reduce_event(IntentState(project_id="PROJ-1"), event)


def test_out_of_order_stream_is_not_silently_sorted() -> None:
    first = _stored(
        1,
        "EVT-1",
        EventType.CLAIM_INFERRED,
        SemanticObjectPayload(object=_claim()),
    )
    third = _stored(
        3,
        "EVT-3",
        EventType.USER_STATED_INTENT,
        UserStatedIntentPayload(text="Need login.", actor_id="OWNER"),
    )
    second = _stored(
        2,
        "EVT-2",
        EventType.USER_STATED_INTENT,
        UserStatedIntentPayload(text="Need login.", actor_id="OWNER"),
    )

    with pytest.raises(ValueError):
        replay("PROJ-1", [first, third, second])


def test_semantic_event_adds_its_object() -> None:
    claim = _claim()
    state = replay(
        "PROJ-1",
        [_stored(1, "EVT-2", EventType.CLAIM_INFERRED, SemanticObjectPayload(object=claim))],
    )

    assert state.objects["CLAIM-1"] == claim


def test_ambiguity_detected_does_not_add_a_gap() -> None:
    gap = _gap()
    state = replay(
        "PROJ-1",
        [_stored(1, "EVT-3", EventType.AMBIGUITY_DETECTED, GapPayload(gap=gap))],
    )

    assert gap.id not in state.gaps
    assert state.revision == 1
    assert state.source_events == ("EVT-3",)


def test_gap_recorded_adds_the_gap() -> None:
    gap = _gap()
    state = replay(
        "PROJ-1",
        [_stored(1, "EVT-4", EventType.GAP_RECORDED, GapPayload(gap=gap))],
    )

    assert state.gaps["GAP-1"] == gap


def test_gap_resolved_records_current_event_id() -> None:
    gap = _gap()
    state = replay(
        "PROJ-1",
        [
            _stored(1, "EVT-4", EventType.GAP_RECORDED, GapPayload(gap=gap)),
            _stored(2, "EVT-5", EventType.GAP_RESOLVED, GapResolvedPayload(gap_id=gap.id)),
        ],
    )

    resolved = state.gaps["GAP-1"]
    assert resolved.status is GapStatus.RESOLVED
    assert resolved.resolution_event_id == "EVT-5"
    assert gap.status is GapStatus.OPEN


def test_gap_waived_records_current_event_id() -> None:
    gap = _gap()
    state = replay(
        "PROJ-1",
        [
            _stored(1, "EVT-4", EventType.GAP_RECORDED, GapPayload(gap=gap)),
            _stored(
                2,
                "EVT-6",
                EventType.GAP_WAIVED,
                GapWaivedPayload(
                    gap_id=gap.id,
                    reason="Accepted residual ambiguity for this scope.",
                    authorized_by="OWNER",
                ),
            ),
        ],
    )

    waived = state.gaps["GAP-1"]
    assert waived.status is GapStatus.WAIVED
    assert waived.resolution_event_id == "EVT-6"


def test_resolving_unknown_gap_raises_value_error() -> None:
    with pytest.raises(ValueError):
        reduce_event(
            IntentState(project_id="PROJ-1"),
            _stored(1, "EVT-5", EventType.GAP_RESOLVED, GapResolvedPayload(gap_id="GAP-MISSING")),
        )


def test_waiving_unknown_gap_raises_value_error() -> None:
    with pytest.raises(ValueError):
        reduce_event(
            IntentState(project_id="PROJ-1"),
            _stored(
                1,
                "EVT-6",
                EventType.GAP_WAIVED,
                GapWaivedPayload(
                    gap_id="GAP-MISSING",
                    reason="Not in state.",
                    authorized_by="OWNER",
                ),
            ),
        )


def test_job_created_records_the_job() -> None:
    job = _job()
    state = replay(
        "PROJ-1",
        [_stored(1, "EVT-7", EventType.JOB_CREATED, JobPayload(job=job))],
    )

    assert state.jobs["JOB-1"] == job


def test_job_status_changed_updates_status_and_attempt() -> None:
    job = _job()
    state = replay(
        "PROJ-1",
        [
            _stored(1, "EVT-7", EventType.JOB_CREATED, JobPayload(job=job)),
            _stored(
                2,
                "EVT-8",
                EventType.JOB_STATUS_CHANGED,
                JobStatusChangedPayload(job_id=job.id, status=JobStatus.RUNNING, attempt=1),
            ),
        ],
    )

    updated = state.jobs["JOB-1"]
    assert updated.status is JobStatus.RUNNING
    assert updated.attempt == 1
    assert job.status is JobStatus.PENDING
    assert job.attempt == 0


def test_changing_unknown_job_raises_value_error() -> None:
    with pytest.raises(ValueError):
        reduce_event(
            IntentState(project_id="PROJ-1"),
            _stored(
                1,
                "EVT-8",
                EventType.JOB_STATUS_CHANGED,
                JobStatusChangedPayload(job_id="JOB-MISSING", status=JobStatus.RUNNING, attempt=1),
            ),
        )


def test_requirement_superseded_marks_old_requirement() -> None:
    old = _requirement(object_id="REQ-1", statement="Old availability rule.")
    replacement = _requirement(object_id="REQ-2", statement="New availability rule.")
    state = replay(
        "PROJ-1",
        [
            _stored(
                1,
                "EVT-9",
                EventType.REQUIREMENT_CANONICALIZED,
                SemanticObjectPayload(object=old),
            ),
            _stored(
                2,
                "EVT-10",
                EventType.REQUIREMENT_CANONICALIZED,
                SemanticObjectPayload(object=replacement),
            ),
            _stored(
                3,
                "EVT-11",
                EventType.REQUIREMENT_SUPERSEDED,
                SupersessionPayload(
                    object_id=old.id,
                    superseded_by=replacement.id,
                    reason="Owner replaced the threshold.",
                ),
            ),
        ],
    )

    superseded = state.objects["REQ-1"]
    assert isinstance(superseded, Requirement)
    assert superseded.lifecycle is LifecycleStatus.SUPERSEDED
    assert superseded.revision == old.revision + 1
    assert state.objects["REQ-2"] == replacement


def test_superseding_unknown_object_raises_value_error() -> None:
    replacement = _requirement(object_id="REQ-2", statement="New availability rule.")
    state = replay(
        "PROJ-1",
        [
            _stored(
                1,
                "EVT-10",
                EventType.REQUIREMENT_CANONICALIZED,
                SemanticObjectPayload(object=replacement),
            )
        ],
    )
    with pytest.raises(ValueError):
        reduce_event(
            state,
            _stored(
                2,
                "EVT-11",
                EventType.REQUIREMENT_SUPERSEDED,
                SupersessionPayload(
                    object_id="REQ-MISSING",
                    superseded_by=replacement.id,
                    reason="Unknown source requirement.",
                ),
            ),
        )


def test_superseding_non_requirement_raises_value_error() -> None:
    claim = _claim()
    replacement = _requirement(object_id="REQ-2", statement="New availability rule.")
    state = replay(
        "PROJ-1",
        [
            _stored(1, "EVT-2", EventType.CLAIM_INFERRED, SemanticObjectPayload(object=claim)),
            _stored(
                2,
                "EVT-10",
                EventType.REQUIREMENT_CANONICALIZED,
                SemanticObjectPayload(object=replacement),
            ),
        ],
    )
    with pytest.raises(ValueError):
        reduce_event(
            state,
            _stored(
                3,
                "EVT-11",
                EventType.REQUIREMENT_SUPERSEDED,
                SupersessionPayload(
                    object_id=claim.id,
                    superseded_by=replacement.id,
                    reason="Claim is not a requirement.",
                ),
            ),
        )


def test_missing_superseded_by_requirement_raises_value_error() -> None:
    old = _requirement(object_id="REQ-1", statement="Old availability rule.")
    state = replay(
        "PROJ-1",
        [
            _stored(
                1,
                "EVT-9",
                EventType.REQUIREMENT_CANONICALIZED,
                SemanticObjectPayload(object=old),
            )
        ],
    )
    with pytest.raises(ValueError):
        reduce_event(
            state,
            _stored(
                2,
                "EVT-11",
                EventType.REQUIREMENT_SUPERSEDED,
                SupersessionPayload(
                    object_id=old.id,
                    superseded_by="REQ-MISSING",
                    reason="Replacement is not present.",
                ),
            ),
        )


def test_closure_event_records_scope_revision() -> None:
    state = replay(
        "PROJ-1",
        [
            _stored(
                1,
                "EVT-12",
                EventType.INTENT_CLOSURE_REACHED,
                ClosurePayload(scope="core", package_revision=4),
            )
        ],
    )

    assert state.closed_scopes["core"] == 4


def test_reopen_removes_scope() -> None:
    state = replay(
        "PROJ-1",
        [
            _stored(
                1,
                "EVT-12",
                EventType.INTENT_CLOSURE_REACHED,
                ClosurePayload(scope="core", package_revision=4),
            ),
            _stored(
                2,
                "EVT-13",
                EventType.INTENT_REOPENED,
                ReopenPayload(scope="core", reason="New conflicting evidence."),
            ),
        ],
    )

    assert "core" not in state.closed_scopes


def test_reducer_does_not_mutate_input_state() -> None:
    state = IntentState(project_id="PROJ-1")
    snapshot = state.model_dump()
    reduce_event(
        state,
        _stored(1, "EVT-2", EventType.CLAIM_INFERRED, SemanticObjectPayload(object=_claim())),
    )

    assert state.model_dump() == snapshot
    assert state.revision == 0
    assert dict(state.objects) == {}


def test_intent_state_mappings_reject_direct_mutation() -> None:
    state = replay(
        "PROJ-1",
        [_stored(1, "EVT-2", EventType.CLAIM_INFERRED, SemanticObjectPayload(object=_claim()))],
    )

    with pytest.raises(TypeError):
        state.objects["CLAIM-X"] = _claim()
    with pytest.raises(TypeError):
        state.gaps["GAP-X"] = _gap()
    with pytest.raises(TypeError):
        state.jobs["JOB-X"] = _job()
    with pytest.raises(TypeError):
        state.closed_scopes["core"] = 1


def test_intent_state_json_round_trip() -> None:
    state = replay(
        "PROJ-1",
        [
            _stored(1, "EVT-2", EventType.CLAIM_INFERRED, SemanticObjectPayload(object=_claim())),
            _stored(2, "EVT-4", EventType.GAP_RECORDED, GapPayload(gap=_gap())),
            _stored(3, "EVT-7", EventType.JOB_CREATED, JobPayload(job=_job())),
            _stored(
                4,
                "EVT-12",
                EventType.INTENT_CLOSURE_REACHED,
                ClosurePayload(scope="core", package_revision=4),
            ),
        ],
    )

    restored = IntentState.model_validate(state.model_dump(mode="json"))

    assert restored == state


def test_each_successful_event_increments_revision_and_history_once() -> None:
    state = replay(
        "PROJ-1",
        [
            _stored(
                1,
                "EVT-0",
                EventType.USER_STATED_INTENT,
                UserStatedIntentPayload(text="Need login.", actor_id="OWNER"),
            ),
            _stored(2, "EVT-2", EventType.CLAIM_INFERRED, SemanticObjectPayload(object=_claim())),
        ],
    )

    assert state.revision == 2
    assert state.last_sequence == 2
    assert state.source_events == ("EVT-0", "EVT-2")


def _intent() -> Intent:
    return Intent(
        id="INTENT-1",
        project_id="PROJ-1",
        mission="Keep payments available after regional loss.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def _authority_record() -> AuthorityRecord:
    return AuthorityRecord(
        id="AUTH-1",
        project_id="PROJ-1",
        subject_id="REQ-1",
        authorized_by="OWNER",
        rationale="Owner authorized the availability requirement.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def _amendment() -> Amendment:
    return Amendment(
        id="AMD-1",
        project_id="PROJ-1",
        subject_id="REQ-1",
        change_statement="Raise the availability threshold.",
        rationale="New evidence about regional loss.",
        authority=Authority.PROPOSED,
        confidence=0.8,
        provenance=_provenance(),
        created_at=OCCURRED_AT,
    )


def test_semantic_object_recorded_replays_generic_objects() -> None:
    intent = _intent()
    authority_record = _authority_record()
    amendment = _amendment()
    state = replay(
        "PROJ-1",
        [
            _stored(
                1,
                "EVT-INT",
                EventType.SEMANTIC_OBJECT_RECORDED,
                SemanticObjectPayload(object=intent),
            ),
            _stored(
                2,
                "EVT-AUTH",
                EventType.SEMANTIC_OBJECT_RECORDED,
                SemanticObjectPayload(object=authority_record),
            ),
            _stored(
                3,
                "EVT-AMD",
                EventType.SEMANTIC_OBJECT_RECORDED,
                SemanticObjectPayload(object=amendment),
            ),
        ],
    )

    assert state.objects["INTENT-1"] == intent
    assert state.objects["AUTH-1"] == authority_record
    assert state.objects["AMD-1"] == amendment
    assert state.objects["AUTH-1"].kind.value == "AUTHORITY_RECORD"
    assert "REQ-1" not in state.objects
