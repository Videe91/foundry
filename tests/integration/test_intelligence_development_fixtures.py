from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.evaluation.loader import load_judge
from foundry.evaluation.models import EvalPrediction, EvalScore
from foundry.evaluation.scorer import score_prediction
from foundry.intelligence.errors import IntelligenceValidationError
from foundry.intelligence.fake import FakeIntentIntelligence
from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.port import IntentIntelligence
from foundry.intelligence.proposals import (
    ClaimProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
    IntentProposal,
)
from foundry.intelligence.runs import DevelopmentFixtureRun, run_development_fixture

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
GREENFIELD = FIXTURES / "greenfield" / "payments_vague"
BROWNFIELD = FIXTURES / "brownfield" / "retry_conflict"


def _greenfield_payload() -> IntentIntelligencePayload:
    return IntentIntelligencePayload(
        semantic_proposals=(
            IntentProposal(
                proposal_id="P-1",
                confidence=0.8,
                source_event_ids=("EVT-GF-1",),
                mission="Build a payment platform.",
            ),
        ),
        gap_proposals=(),
    )


def _brownfield_payload() -> IntentIntelligencePayload:
    return IntentIntelligencePayload(
        semantic_proposals=(
            ClaimProposal(
                proposal_id="P-1",
                confidence=0.9,
                source_event_ids=("EVT-BF-1",),
                statement="Legacy retry count is 3.",
            ),
            ClaimProposal(
                proposal_id="P-2",
                confidence=0.9,
                source_event_ids=("EVT-BF-2",),
                statement="Legacy retry count is 5.",
            ),
        ),
        gap_proposals=(),
    )


class RecordingExecutor:
    def __init__(self, payload: IntentIntelligencePayload, spy: SimpleNamespace) -> None:
        self._payload = payload
        self._spy = spy

    def analyze(self, request: IntelligenceInput) -> IntentIntelligenceResult:
        assert isinstance(request, IntelligenceInput)
        assert self._spy.judge_calls == []
        dumped = request.model_dump()
        assert "expected_gaps" not in dumped
        assert "forbidden_gap_fingerprints" not in dumped
        assert "fingerprint" not in dumped
        self._spy.events.append("analyze")
        return IntentIntelligenceResult(payload=self._payload, usage=IntelligenceUsage())


class ProviderFailureExecutor:
    def analyze(self, request: IntelligenceInput) -> IntentIntelligenceResult:
        raise RuntimeError("provider unavailable")


@pytest.fixture
def pipeline_spy(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    import foundry.intelligence.runs as runs

    spy = SimpleNamespace(events=[], judge_calls=[], score_calls=[])
    real_prediction = runs.to_eval_prediction
    real_judge = runs.load_judge
    real_score = runs.score_prediction

    def prediction(result: IntentIntelligenceResult) -> EvalPrediction:
        out = real_prediction(result)
        spy.events.append("prediction")
        return out

    def judge(path: Path) -> Any:
        spy.events.append("judge")
        spy.judge_calls.append(path)
        return real_judge(path)

    def score(expectation: Any, prediction_value: EvalPrediction) -> EvalScore:
        spy.events.append("score")
        spy.score_calls.append((expectation, prediction_value))
        return real_score(expectation, prediction_value)

    monkeypatch.setattr(runs, "to_eval_prediction", prediction)
    monkeypatch.setattr(runs, "load_judge", judge)
    monkeypatch.setattr(runs, "score_prediction", score)
    return spy


def test_development_fixture_run_is_immutable(pipeline_spy: SimpleNamespace) -> None:
    run = run_development_fixture(GREENFIELD, FakeIntentIntelligence(_greenfield_payload()))
    with pytest.raises(ValidationError):
        run.fixture_id = "mutated"


def test_greenfield_fake_pipeline_retains_result_prediction_and_score(
    pipeline_spy: SimpleNamespace,
) -> None:
    payload = _greenfield_payload()
    usage = IntelligenceUsage(
        cheap_model_jobs=1,
        input_tokens=40,
        output_tokens=8,
        cost_usd=0.25,
        wall_clock_ms=17,
    )
    executor: IntentIntelligence = FakeIntentIntelligence(payload, usage)
    run = run_development_fixture(GREENFIELD, executor)
    assert isinstance(run, DevelopmentFixtureRun)
    assert run.fixture_id == "greenfield-payments-vague-v1"
    assert run.family == "greenfield"
    assert isinstance(run.intelligence_result, IntentIntelligenceResult)
    assert run.intelligence_result.payload is payload
    assert isinstance(run.prediction, EvalPrediction)
    assert isinstance(run.score, EvalScore)
    assert run.prediction.gaps == ()
    assert run.score.cost == run.prediction.cost
    assert run.score.cost.cost_usd == 0.25
    assert run.score.cost.input_tokens == 40
    assert run.score.cost.output_tokens == 8
    assert run.score.cost.wall_clock_ms == 17


def test_brownfield_fake_pipeline_preserves_both_claims(
    pipeline_spy: SimpleNamespace,
) -> None:
    payload = _brownfield_payload()
    run = run_development_fixture(BROWNFIELD, FakeIntentIntelligence(payload))
    assert run.fixture_id == "brownfield-retry-conflict-v1"
    assert run.family == "brownfield"
    proposals = run.intelligence_result.payload.semantic_proposals
    statements = [proposal.statement for proposal in proposals]
    assert statements == ["Legacy retry count is 3.", "Legacy retry count is 5."]
    assert run.intelligence_result.payload.gap_proposals == ()
    assert isinstance(run.prediction, EvalPrediction)
    assert isinstance(run.score, EvalScore)


def test_judge_loads_only_after_prediction_and_analyze(
    pipeline_spy: SimpleNamespace,
) -> None:
    executor: IntentIntelligence = RecordingExecutor(_greenfield_payload(), pipeline_spy)
    run_development_fixture(GREENFIELD, executor)
    assert pipeline_spy.events.index("analyze") < pipeline_spy.events.index("prediction")
    assert pipeline_spy.events.index("prediction") < pipeline_spy.events.index("judge")
    assert pipeline_spy.events.index("judge") < pipeline_spy.events.index("score")


def test_invalid_worker_output_never_loads_judge(pipeline_spy: SimpleNamespace) -> None:
    payload = IntentIntelligencePayload(
        semantic_proposals=(
            IntentProposal(
                proposal_id="P-1",
                confidence=0.8,
                source_event_ids=("EVT-NOT-THERE",),
                mission="Build a payment platform.",
            ),
        )
    )
    with pytest.raises(IntelligenceValidationError, match="EVT-NOT-THERE"):
        run_development_fixture(GREENFIELD, FakeIntentIntelligence(payload))
    assert pipeline_spy.judge_calls == []
    assert "judge" not in pipeline_spy.events
    assert "score" not in pipeline_spy.events


def test_provider_failure_never_loads_judge(pipeline_spy: SimpleNamespace) -> None:
    with pytest.raises(RuntimeError, match="provider unavailable"):
        run_development_fixture(GREENFIELD, ProviderFailureExecutor())
    assert pipeline_spy.judge_calls == []
    assert "judge" not in pipeline_spy.events
    assert "score" not in pipeline_spy.events


def test_prediction_failure_never_loads_judge(
    pipeline_spy: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import foundry.intelligence.runs as runs

    def fail_prediction(_result: IntentIntelligenceResult) -> EvalPrediction:
        raise RuntimeError("prediction failed")

    monkeypatch.setattr(runs, "to_eval_prediction", fail_prediction)
    with pytest.raises(RuntimeError, match="prediction failed"):
        run_development_fixture(GREENFIELD, FakeIntentIntelligence(_greenfield_payload()))
    assert pipeline_spy.judge_calls == []
    assert "judge" not in pipeline_spy.events


def test_score_uses_existing_score_prediction(pipeline_spy: SimpleNamespace) -> None:
    run = run_development_fixture(GREENFIELD, FakeIntentIntelligence(_greenfield_payload()))
    assert len(pipeline_spy.score_calls) == 1
    expectation, prediction = pipeline_spy.score_calls[0]
    assert prediction is run.prediction
    independent = score_prediction(load_judge(GREENFIELD), run.prediction)
    assert run.score == independent


def test_runner_does_not_mutate_intelligence_result(pipeline_spy: SimpleNamespace) -> None:
    payload = _greenfield_payload()
    snapshot = payload.model_dump()
    run = run_development_fixture(GREENFIELD, FakeIntentIntelligence(payload))
    assert payload.model_dump() == snapshot
    assert run.intelligence_result.payload is payload


def test_runner_has_no_forbidden_imports_or_answers() -> None:
    import foundry.intelligence.runs as runs

    source = Path(runs.__file__).read_text()
    for token in (
        "xai_sdk",
        "XAIIntentIntelligence",
        "XAI_API_KEY",
        "grok-4.6",
        "PostgresEventStore",
        "load_dotenv",
        "detector",
        "never-loses-money",
        "very-fast",
        "currency-scope",
        "money-conservation",
        "legacy-retry-count",
        "EventEnvelope",
        "SemanticObject",
        "evaluate_closure",
        "build_intent_package",
        "append",
        "reducer",
    ):
        assert token not in source
    assert not (Path(runs.__file__).resolve().parent / "detectors.py").exists()
