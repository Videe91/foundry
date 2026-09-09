from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer
from typer.testing import CliRunner

from foundry.adapters.postgres.database import create_database_engine
from foundry.adapters.postgres.event_store import PostgresEventStore
from foundry.application.package import build_intent_package
from foundry.application.replay import replay
from foundry.cli import app
from foundry.domain.closure import ClosureResult, evaluate_closure
from foundry.domain.common import (
    Authority,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    SourceKind,
)
from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload
from foundry.domain.gaps import GapKind
from foundry.domain.semantic import Goal, Intent, Metric, Requirement, VerificationObligation
from foundry.domain.state import IntentState
from foundry.evaluation.models import (
    EvalExpectation,
    EvalPrediction,
    EvalScore,
    ExpectedGap,
    PredictedGap,
)
from foundry.evaluation.scorer import score_prediction

OCCURRED_AT = datetime(2026, 9, 9, tzinfo=UTC)
PROJECT_ID = "PROJ-E2E"
SCOPE = "core"
RUNNER = CliRunner()


def _upgrade(database_url: str) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _provenance(event_id: str, source_ref: str) -> Provenance:
    return Provenance(
        source_kind=SourceKind.HUMAN if source_ref.startswith("human://") else SourceKind.SYSTEM,
        source_ref=source_ref,
        source_event_ids=(event_id,),
    )


def _envelope(event_id: str, event_type: EventType, semantic_object: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        project_id=PROJECT_ID,
        event_type=event_type,
        occurred_at=OCCURRED_AT,
        payload=SemanticObjectPayload(object=semantic_object),
    )


def _e2e_events() -> tuple[EventEnvelope, ...]:
    intent = Intent(
        id="INTENT-E2E",
        project_id=PROJECT_ID,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance("EVT-INTENT", "human://e2e-owner"),
        created_at=OCCURRED_AT,
        scope=("core",),
        mission="Keep checkout available after regional loss.",
    )
    goal = Goal(
        id="GOAL-E2E",
        project_id=PROJECT_ID,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance("EVT-GOAL", "human://e2e-owner"),
        created_at=OCCURRED_AT,
        scope=("core",),
        statement="Survive loss of one region.",
    )
    requirement = Requirement(
        id="REQ-E2E",
        project_id=PROJECT_ID,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance("EVT-REQ", "human://e2e-owner"),
        created_at=OCCURRED_AT,
        scope=("core",),
        statement="Regional loss must not interrupt checkout.",
        materiality=Materiality.HIGH,
        requires_metric=True,
        requires_verification=True,
        relations=(
            Relation(relation_type=RelationType.MEASURED_BY, target_id="METRIC-E2E"),
            Relation(relation_type=RelationType.VERIFIED_BY, target_id="VERIFY-E2E"),
        ),
    )
    metric = Metric(
        id="METRIC-E2E",
        project_id=PROJECT_ID,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance("EVT-METRIC", "system://e2e"),
        created_at=OCCURRED_AT,
        scope=("core",),
        name="regional-interruption",
        definition="Checkout interruption after loss of one region.",
        target="below authorized threshold",
    )
    verifier = VerificationObligation(
        id="VERIFY-E2E",
        project_id=PROJECT_ID,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=_provenance("EVT-VERIFY", "system://e2e"),
        created_at=OCCURRED_AT,
        scope=("core",),
        statement="Simulate regional loss and measure interruption.",
        target_object_ids=("REQ-E2E",),
        method_class="simulation",
    )
    return (
        _envelope("EVT-INTENT", EventType.SEMANTIC_OBJECT_RECORDED, intent),
        _envelope("EVT-GOAL", EventType.SEMANTIC_OBJECT_RECORDED, goal),
        _envelope("EVT-REQ", EventType.REQUIREMENT_CANONICALIZED, requirement),
        _envelope("EVT-METRIC", EventType.SUCCESS_METRIC_DEFINED, metric),
        _envelope("EVT-VERIFY", EventType.VERIFICATION_OBLIGATION_DEFINED, verifier),
    )


def test_cli_help_lists_command_groups() -> None:
    result = RUNNER.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "events" in result.stdout
    assert "intent" in result.stdout
    assert "eval" in result.stdout


def test_cli_contains_no_model_provider_imports() -> None:
    source = Path("src/foundry/cli.py").read_text()
    for vendor in ("openai", "anthropic", "grok", "google.generativeai", "vertexai"):
        assert vendor not in source


def test_persisted_events_replay_to_identical_closed_package() -> None:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        database_url = postgres.get_connection_url()
        _upgrade(database_url)
        store = PostgresEventStore(create_database_engine(database_url))
        events = _e2e_events()
        for expected_sequence, event in enumerate(events):
            stored = store.append(event, expected_sequence=expected_sequence)
            assert stored.sequence == expected_sequence + 1
        assert store.current_sequence(PROJECT_ID) == 5

        events_1 = store.load(PROJECT_ID)
        assert [item.sequence for item in events_1] == [1, 2, 3, 4, 5]
        state_1 = replay(PROJECT_ID, events_1)
        closure_1 = evaluate_closure(state_1, SCOPE)
        assert closure_1.closed is True
        assert closure_1.blockers == ()
        package_1 = build_intent_package(state_1, SCOPE)
        assert package_1.project_id == PROJECT_ID
        assert package_1.intent_version == 5
        assert "INTENT-E2E" in package_1.purpose_ids
        assert "GOAL-E2E" in package_1.purpose_ids
        assert package_1.obligation_ids == ("REQ-E2E",)
        assert package_1.quality_ids == ("METRIC-E2E", "VERIFY-E2E")
        assert package_1.history_event_ids == (
            "EVT-INTENT",
            "EVT-GOAL",
            "EVT-REQ",
            "EVT-METRIC",
            "EVT-VERIFY",
        )

        events_2 = store.load(PROJECT_ID)
        state_2 = replay(PROJECT_ID, events_2)
        closure_2 = evaluate_closure(state_2, SCOPE)
        package_2 = build_intent_package(state_2, SCOPE)
        assert events_2 == events_1
        assert state_2 == state_1
        assert closure_2 == closure_1
        assert package_2 == package_1
        assert state_1.model_dump_json() == state_2.model_dump_json()
        assert package_1.model_dump_json() == package_2.model_dump_json()

        replay_1 = RUNNER.invoke(
            app, ["events", "replay", PROJECT_ID, "--database-url", database_url]
        )
        replay_2 = RUNNER.invoke(
            app, ["events", "replay", PROJECT_ID, "--database-url", database_url]
        )
        assert replay_1.exit_code == 0
        assert replay_2.exit_code == 0
        assert replay_1.stdout == replay_2.stdout
        cli_state = IntentState.model_validate_json(replay_1.stdout)
        assert cli_state == state_1

        closed = RUNNER.invoke(
            app,
            [
                "intent",
                "closure",
                PROJECT_ID,
                "--scope",
                SCOPE,
                "--database-url",
                database_url,
            ],
        )
        assert closed.exit_code == 0
        closed_result = ClosureResult.model_validate_json(closed.stdout)
        assert closed_result.closed is True

        empty = RUNNER.invoke(
            app,
            [
                "intent",
                "closure",
                "PROJ-EMPTY",
                "--scope",
                SCOPE,
                "--database-url",
                database_url,
            ],
        )
        assert empty.exit_code == 2
        empty_result = ClosureResult.model_validate_json(empty.stdout)
        codes = {blocker.code for blocker in empty_result.blockers}
        assert "MISSING_CANONICAL_INTENT" in codes
        assert "MISSING_CANONICAL_OBLIGATION" in codes


def test_eval_score_cli_uses_judge_files_only(tmp_path: Path) -> None:
    expectation = EvalExpectation(
        expected_gaps=(
            ExpectedGap(
                fingerprint="AMBIGUITY:test",
                kind=GapKind.AMBIGUITY,
                critical=True,
            ),
        )
    )
    prediction = EvalPrediction(
        gaps=(
            PredictedGap(
                fingerprint="AMBIGUITY:test",
                kind=expectation.expected_gaps[0].kind,
            ),
        )
    )
    prediction_path = tmp_path / "prediction.json"
    judge_path = tmp_path / "judge.json"
    prediction_path.write_text(prediction.model_dump_json())
    judge_path.write_text(expectation.model_dump_json())
    result = RUNNER.invoke(app, ["eval", "score", str(prediction_path), str(judge_path)])
    assert result.exit_code == 0
    score = EvalScore.model_validate_json(result.stdout)
    assert score.critical_gaps_detected == 1
    assert score.critical_gaps_missed == 0
    assert score.false_gaps == 0
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score == score_prediction(expectation, prediction)
    assert not (tmp_path / "input.json").exists()
