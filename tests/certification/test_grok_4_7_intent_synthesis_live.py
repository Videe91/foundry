"""MR4 — live certification exam: xai/grok-4.7 for INTENT_SYNTHESIS.

Opt-in twice over. A developer holding an API key must not trigger fifteen live calls by
running the default suite, so this requires ``XAI_API_KEY`` **and**
``RUN_LIVE_MODEL_CERTIFICATION=1``.

Every case drives the real production path — real semantic substrate, real event store,
real ``synthesize_intent``, real T7 bounding, the real Model Runtime and the real xAI
adapter — and is scored deterministically by ``_intent_synthesis_exam``. Grok is never
asked whether it answered correctly, and its confidence is never a pass criterion.

Five scenarios × three independent runs = fifteen live calls. Each run gets a fresh
store, fresh substrate, fresh synthesis run id and fresh trace ids, so no case can pass
on conversational carry-over.
"""

from __future__ import annotations

import os
import pathlib
from itertools import count
from typing import Any

import pytest

from foundry.adapters.intent_synthesis.model_runtime import (
    INTENT_SYNTHESIS_POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
    ModelRuntimeIntentSynthesizer,
)
from foundry.adapters.model_runtime.xai import XAI_PROVIDER_ID, XAIModelProvider
from foundry.application.intent_synthesis import synthesize_intent
from foundry.domain.common import Authority, Materiality, RelationType, SourceKind
from foundry.domain.events import EventType
from foundry.domain.intent_synthesis import IntentSynthesisPolicy, IntentSynthesisRoute
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import Requirement
from foundry.model_runtime.domain import (
    ModelCapability,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.errors import ModelProviderError
from foundry.model_runtime.ports import ProviderExecutionResult
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from tests.certification._intent_synthesis_exam import (
    AT,
    CANDIDATE,
    EXPECTED_POLICY_VERSION,
    EXPECTED_PROMPT_SHA256,
    PROJECT,
    SCOPE,
    CallEvidence,
    ExamObservation,
    Substrate,
    build_case_a,
    build_case_b,
    build_case_c,
    build_case_d,
    build_case_e,
    score_case_a_new,
    score_case_b_existing_unchanged,
    score_case_c_replaces_stale,
    score_case_d_ambiguity,
    score_case_e_injection,
    score_global_gates,
    state_of,
)

RUNS_PER_CASE = 3
LIVE_LEDGER_ARTIFACT = "tests/certification/_live_case_a_ledger.json"

pytestmark = pytest.mark.skipif(
    not (os.environ.get("XAI_API_KEY") and os.environ.get("RUN_LIVE_MODEL_CERTIFICATION") == "1"),
    reason=(
        "LIVE_MODEL_CERTIFICATION_NOT_ENABLED: set XAI_API_KEY and "
        "RUN_LIVE_MODEL_CERTIFICATION=1 to sit the exam"
    ),
)

MEASUREMENTS: list[dict[str, Any]] = []


class RecordingXAIProvider:
    """Wraps the real adapter so the exam keeps provider metadata. Test-only.

    Production is untouched: this delegates to the real ``XAIModelProvider`` and only
    remembers what came back.
    """

    def __init__(self, inner: XAIModelProvider) -> None:
        self._inner = inner
        self.results: list[ProviderExecutionResult[Any]] = []

    @property
    def provider_id(self) -> str:
        return self._inner.provider_id

    @property
    def calls(self) -> int:
        return len(self.results)

    def execute(self, **kwargs: Any) -> ProviderExecutionResult[Any]:
        result = self._inner.execute(**kwargs)
        self.results.append(result)
        return result


def _candidate_registry() -> ModelRegistry:
    """Test-local descriptor. Permits the candidate to SIT the exam; not certification."""
    return ModelRegistry(
        descriptors=(
            ModelDescriptor(
                identity=CANDIDATE,
                tiers=frozenset({ModelTier.REASONER}),
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                ),
                certified_tasks=frozenset({ModelTask.INTENT_SYNTHESIS}),
            ),
        )
    )


def _run_attempt(substrate: Substrate, case_id: str, attempt: int) -> tuple[ExamObservation, Any]:
    """One live call through the whole production path, with fresh everything."""
    provider = RecordingXAIProvider(
        XAIModelProvider(api_key=os.environ["XAI_API_KEY"], reasoning_effort="high")
    )
    runtime = ModelRuntime(registry=_candidate_registry(), providers=(provider,))
    traces = count(1)
    synthesizer = ModelRuntimeIntentSynthesizer(
        runtime=runtime,
        model_identity=CANDIDATE,
        trace_factory=lambda: ModelTraceContext(
            run_id=f"CERT-{case_id}-{attempt}", call_id=f"CALL-{next(traces)}"
        ),
        execution_constraints=ModelExecutionConstraints(
            timeout_seconds=120.0, max_output_tokens=2000
        ),
    )

    from foundry.application.intent_synthesis_context import (
        compile_intent_synthesis_context,
    )

    before = state_of(substrate.store)
    context = compile_intent_synthesis_context(before, scope=SCOPE)
    assert context.request is not None, f"{case_id}: nothing eligible; the exam cannot run"
    visible_claims = tuple(c.claim_id for locus in context.request.basis for c in locus.live_claims)
    visible_objects = tuple(o.object_id for o in context.request.known_intent_objects)

    result_holder: dict[str, Any] = {}

    class CapturingSynthesizer:
        """Records exactly what the model returned, before T7/T8 act on it."""

        @property
        def fingerprint(self) -> Any:
            return synthesizer.fingerprint

        def synthesize(self, request: Any) -> Any:
            produced = synthesizer.synthesize(request)
            result_holder["result"] = produced
            return produced

    error: Exception | None = None
    try:
        synthesize_intent(
            substrate.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=CapturingSynthesizer(),  # type: ignore[arg-type]
            policy=IntentSynthesisPolicy(),
            clock=lambda: AT,
            synthesis_run_id_factory=lambda: f"RUN-{case_id}-{attempt}",
            human_actor_id=None,
        )
    except ModelProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - a governance rejection is exam evidence
        error = exc

    after = state_of(substrate.store)
    metadata = provider.results[0] if provider.results else None
    evidence = (
        CallEvidence(
            provider=metadata.identity.provider,
            model=metadata.identity.model,
            task=ModelTask.INTENT_SYNTHESIS.value,
            tier=ModelTier.REASONER.value,
            input_tokens=metadata.usage.input_tokens,
            output_tokens=metadata.usage.output_tokens,
            cost_usd=metadata.usage.cost_usd,
            wall_clock_ms=metadata.usage.wall_clock_ms,
            finish_reason=metadata.finish_reason,
        )
        if metadata is not None
        else None
    )

    produced = result_holder.get("result")
    assert produced is not None, f"{case_id} attempt {attempt}: no model result was captured"

    observation = ExamObservation(
        case_id=case_id,
        attempt=attempt,
        result=produced,
        state=after,
        provider_calls=provider.calls,
        evidence=evidence,
        visible_claim_ids=visible_claims,
        visible_object_ids=visible_objects,
        decision_authors=tuple(r.author for r in after.intent_synthesis.decisions.values()),
    )

    MEASUREMENTS.append(
        {
            "case": case_id,
            "attempt": attempt,
            "provider": evidence.provider if evidence else None,
            "model": evidence.model if evidence else None,
            "input_tokens": evidence.input_tokens if evidence else None,
            "output_tokens": evidence.output_tokens if evidence else None,
            "cost_usd": evidence.cost_usd if evidence else None,
            "wall_clock_ms": evidence.wall_clock_ms if evidence else None,
            "finish_reason": evidence.finish_reason if evidence else None,
            "outcome": (
                "AMBIGUITY"
                if produced.gap_proposals
                else produced.proposals[0].disposition.value
                if produced.proposals
                else "EMPTY"
            ),
            "governance_error": type(error).__name__ if error else None,
        }
    )
    return observation, error


# --- §24 freeze proof, asserted inside the exam itself ----------------------------------------


def test_the_contestant_is_frozen() -> None:
    import hashlib

    assert hashlib.sha256(SYSTEM_INSTRUCTION.encode()).hexdigest() == EXPECTED_PROMPT_SHA256
    assert SYSTEM_INSTRUCTION_SHA256 == EXPECTED_PROMPT_SHA256
    assert INTENT_SYNTHESIS_POLICY_VERSION == EXPECTED_POLICY_VERSION


# --- the five certification cases -------------------------------------------------------------


@pytest.mark.parametrize("attempt", range(1, RUNS_PER_CASE + 1))
def test_case_a_new_requirement(attempt: int) -> None:
    substrate = build_case_a()
    claim_id = substrate.claim_ids["refund"]
    observation, error = _run_attempt(substrate, "A", attempt)

    score_global_gates(observation)
    score_case_a_new(observation, claim_id=claim_id)
    assert error is None, f"governance rejected a live result: {error}"

    state = observation.state
    record = next(iter(state.intent_synthesis.decisions.values()))
    requirement = state.objects[record.identity.object_id("REQ")]
    assert isinstance(requirement, Requirement)

    if attempt == 1:
        # Preserve this genuinely model-authored ledger so the replay and containment
        # proofs can run later with no provider and no credential present.
        import json

        pathlib.Path(LIVE_LEDGER_ARTIFACT).write_text(
            json.dumps(
                [
                    {"sequence": s.sequence, "event": s.event.model_dump(mode="json")}
                    for s in substrate.store.load(PROJECT)
                ],
                indent=2,
            )
        )
    assert requirement.authority is Authority.PROPOSED
    assert requirement.materiality is Materiality.LOW
    assert [(r.relation_type, r.target_id) for r in requirement.relations] == [
        (RelationType.DERIVED_FROM, claim_id)
    ]
    assert requirement.provenance.source_kind is SourceKind.SYSTEM
    assert record.author.provider == XAI_PROVIDER_ID
    assert record.author.model == CANDIDATE.model
    assert record.author.policy_version == EXPECTED_POLICY_VERSION


@pytest.mark.parametrize("attempt", range(1, RUNS_PER_CASE + 1))
def test_case_b_existing_intent_is_unchanged(attempt: int) -> None:
    substrate = build_case_b()
    observation, error = _run_attempt(substrate, "B", attempt)

    score_global_gates(observation)
    score_case_b_existing_unchanged(
        observation,
        claim_id=substrate.claim_ids["refund"],
        existing_object_id=substrate.object_ids["existing"],
    )
    assert error is None, f"governance rejected a live result: {error}"

    state = observation.state
    record = next(iter(state.intent_synthesis.decisions.values()))
    assert record.decision.route is IntentSynthesisRoute.NO_CHANGE
    assert record.identity.object_id("REQ") not in state.objects
    assert state.objects["REQ-existing"].authority is Authority.PROPOSED


@pytest.mark.parametrize("attempt", range(1, RUNS_PER_CASE + 1))
def test_case_c_stale_requirement_is_replaced(attempt: int) -> None:
    substrate = build_case_c()
    observation, error = _run_attempt(substrate, "C", attempt)

    score_global_gates(observation)
    score_case_c_replaces_stale(
        observation,
        corrected_claim_id=substrate.claim_ids["corrected"],
        stale_object_id=substrate.object_ids["stale"],
    )
    assert error is None, f"governance rejected a live result: {error}"

    state = observation.state
    record = next(iter(state.intent_synthesis.decisions.values()))
    assert record.decision.route is IntentSynthesisRoute.APPLY
    replacement = state.objects[record.identity.object_id("REQ")]
    assert replacement.authority is Authority.PROPOSED
    assert [r.target_id for r in replacement.relations] == [substrate.claim_ids["corrected"]]
    assert [r.retired_object_id for r in state.intent_synthesis.retirements] == ["REQ-stale"]


@pytest.mark.parametrize("attempt", range(1, RUNS_PER_CASE + 1))
def test_case_d_genuine_ambiguity_is_reported(attempt: int) -> None:
    substrate = build_case_d()
    observation, error = _run_attempt(substrate, "D", attempt)

    score_global_gates(observation)
    score_case_d_ambiguity(observation)
    assert error is None, f"governance rejected a live result: {error}"

    state = observation.state
    gaps = [g for g in state.gaps.values() if isinstance(g, IntentSynthesisGap)]
    assert gaps, "no durable synthesis gap was recorded"
    gap = gaps[0]
    assert gap.blocking is True
    assert gap.materiality is None
    assert gap.risk is None
    assert gap.scope == (SCOPE,)
    assert state.intent_synthesis.decisions == {}
    types = [s.event.event_type for s in substrate.store.load(PROJECT)]
    assert EventType.INTENT_SYNTHESIS_DECIDED not in types
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in types


@pytest.mark.parametrize("attempt", range(1, RUNS_PER_CASE + 1))
def test_case_e_prompt_injection_is_not_followed(attempt: int) -> None:
    substrate = build_case_e()
    observation, error = _run_attempt(substrate, "E", attempt)

    score_global_gates(observation)
    score_case_e_injection(observation, real_claim_id=substrate.claim_ids["refund"])
    assert error is None, f"governance rejected a live result: {error}"

    state = observation.state
    for requirement in state.objects.values():
        if isinstance(requirement, Requirement) and requirement.id != "INTENT-payments":
            assert requirement.authority is Authority.PROPOSED


def test_zz_report_measurements() -> None:
    """Prints the measured baseline. Named to sort last; asserts only on completeness."""
    assert len(MEASUREMENTS) == 5 * RUNS_PER_CASE, (
        f"expected {5 * RUNS_PER_CASE} live calls, recorded {len(MEASUREMENTS)}"
    )
    costs = [m["cost_usd"] for m in MEASUREMENTS if m["cost_usd"] is not None]
    latencies = sorted(m["wall_clock_ms"] for m in MEASUREMENTS if m["wall_clock_ms"] is not None)
    inputs = [m["input_tokens"] for m in MEASUREMENTS if m["input_tokens"] is not None]
    outputs = [m["output_tokens"] for m in MEASUREMENTS if m["output_tokens"] is not None]

    # Durable evidence: the certification document cites this file, not scrollback.
    import json

    artifact = pathlib.Path("tests/certification/_last_run_measurements.json")
    artifact.write_text(
        json.dumps(
            {
                "candidate": f"{CANDIDATE.provider}/{CANDIDATE.model}",
                "policy_version": EXPECTED_POLICY_VERSION,
                "prompt_sha256": EXPECTED_PROMPT_SHA256,
                "runs_per_case": RUNS_PER_CASE,
                "calls": MEASUREMENTS,
                "known_cost_total": sum(costs) if costs else None,
                "known_cost_samples": len(costs),
                "unknown_cost_samples": len(MEASUREMENTS) - len(costs),
                "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
                "input_tokens_total": sum(inputs) if inputs else None,
                "output_tokens_total": sum(outputs) if outputs else None,
            },
            indent=2,
            sort_keys=True,
        )
    )

    print("\n=== MR4 live certification measurements ===")
    for m in MEASUREMENTS:
        print(
            f"  {m['case']}/{m['attempt']}  {m['outcome']:20s} "
            f"in={m['input_tokens']} out={m['output_tokens']} "
            f"cost={m['cost_usd']} ms={m['wall_clock_ms']} finish={m['finish_reason']}"
        )
    print(f"  total calls            : {len(MEASUREMENTS)}")
    print(f"  known cost total       : {sum(costs) if costs else None}")
    print(f"  known cost/call avg    : {(sum(costs) / len(costs)) if costs else None}")
    print(f"  median latency ms      : {latencies[len(latencies) // 2] if latencies else None}")
    print(f"  input tokens total     : {sum(inputs) if inputs else None}")
    print(f"  output tokens total    : {sum(outputs) if outputs else None}")
    print(f"  unknown cost samples   : {len(MEASUREMENTS) - len(costs)}")
    print(f"  finish reasons         : {sorted({m['finish_reason'] for m in MEASUREMENTS})}")
