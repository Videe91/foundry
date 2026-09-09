from __future__ import annotations

from pathlib import Path

import typer

from foundry.adapters.postgres.database import create_database_engine
from foundry.adapters.postgres.event_store import PostgresEventStore
from foundry.application.replay import replay
from foundry.domain.closure import evaluate_closure
from foundry.domain.state import IntentState
from foundry.evaluation.models import EvalExpectation, EvalPrediction
from foundry.evaluation.scorer import score_prediction

app = typer.Typer(no_args_is_help=True)
events_app = typer.Typer(no_args_is_help=True)
intent_app = typer.Typer(no_args_is_help=True)
eval_app = typer.Typer(no_args_is_help=True)

app.add_typer(events_app, name="events")
app.add_typer(intent_app, name="intent")
app.add_typer(eval_app, name="eval")


def _replayed_state(project_id: str, database_url: str) -> IntentState:
    engine = create_database_engine(database_url)
    try:
        events = PostgresEventStore(engine).load(project_id)
        return replay(project_id, events)
    finally:
        engine.dispose()


@events_app.command("replay")
def events_replay(
    project_id: str,
    database_url: str = typer.Option(..., "--database-url"),
) -> None:
    state = _replayed_state(project_id, database_url)
    typer.echo(state.model_dump_json(indent=2))


@intent_app.command("closure")
def intent_closure(
    project_id: str,
    scope: str = typer.Option(..., "--scope"),
    database_url: str = typer.Option(..., "--database-url"),
) -> None:
    result = evaluate_closure(_replayed_state(project_id, database_url), scope)
    typer.echo(result.model_dump_json(indent=2))
    if not result.closed:
        raise typer.Exit(code=2)


@eval_app.command("score")
def eval_score(prediction_json: Path, judge_json: Path) -> None:
    prediction = EvalPrediction.model_validate_json(prediction_json.read_text())
    expectation = EvalExpectation.model_validate_json(judge_json.read_text())
    score = score_prediction(expectation, prediction)
    typer.echo(score.model_dump_json(indent=2))
