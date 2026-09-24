"""MR6 — live certification exam: openai/gpt-6-astra for INTENT_SYNTHESIS.

Opt-in twice over. A developer holding an API key must not trigger fifteen live calls by
running the default suite, so this requires ``OPENAI_API_KEY`` **and**
``RUN_LIVE_MODEL_CERTIFICATION=1``.

The same exam Grok sat, against the same frozen Intent Engine. Every semantic scorer and
every substrate builder is imported from ``_intent_synthesis_exam`` unchanged — this file
contributes a contestant and nothing else. That is the whole point: comparing providers is
only meaningful if they face an identical Intent Engine, so there is no OpenAI-specific
prompt, no relaxed expectation and no model-specific concession anywhere below.

Five scenarios × three independent runs = fifteen live calls. Each run gets a fresh store,
fresh substrate, fresh synthesis run id and fresh trace ids, so no case can pass on
conversational carry-over.

The one difference from Grok's runner is the predeclared transport guard: 16,000 output
tokens rather than 2,000, because for OpenAI reasoning models that bound covers reasoning
tokens as well as visible output. It is a transport safety bound, not part of the semantic
contestant, and it is required to stay under 80% utilisation — a run pressed against our own
artificial bound cannot support a clean verdict either way.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from foundry.adapters.intent_synthesis.model_runtime import (
    INTENT_SYNTHESIS_POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
)
from foundry.adapters.model_runtime.openai import OPENAI_PROVIDER_ID, OpenAIModelProvider
from foundry.domain.common import Authority, Materiality, RelationType, SourceKind
from foundry.domain.events import EventType
from foundry.domain.intent_synthesis import IntentSynthesisRoute
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import Requirement
from foundry.model_runtime.domain import ModelIdentity
from tests.certification._certification_run import (
    Contestant,
    assert_guard_was_not_binding,
    run_attempt,
    write_case_a_ledger,
    write_measurements,
)
from tests.certification._intent_synthesis_exam import (
    EXPECTED_POLICY_VERSION,
    EXPECTED_PROMPT_SHA256,
    PROJECT,
    SCOPE,
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
)

RUNS_PER_CASE = 3

CANDIDATE = ModelIdentity(provider=OPENAI_PROVIDER_ID, model="gpt-6-astra")
"""This runner's contestant. The exam module holds no default: every runner names its own."""

ASTRA = Contestant(
    identity=CANDIDATE,
    credential_env="OPENAI_API_KEY",
    provider_factory=lambda api_key: OpenAIModelProvider(
        api_key=api_key,
        reasoning_effort="high",
        reasoning_mode="standard",
    ),
    reasoning_effort="high",
    # Predeclared before the first live call and never adjusted afterwards. For OpenAI
    # reasoning models this bound covers reasoning tokens as well as visible output, so it
    # is set far above anything the task should need; the headroom law then proves it never
    # came close to binding.
    max_output_tokens=16000,
    timeout_seconds=120.0,
)

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_API_KEY") and os.environ.get("RUN_LIVE_MODEL_CERTIFICATION") == "1"
    ),
    reason=(
        "LIVE_MODEL_CERTIFICATION_NOT_ENABLED: set OPENAI_API_KEY and "
        "RUN_LIVE_MODEL_CERTIFICATION=1 to sit the exam"
    ),
)

MEASUREMENTS: list[dict[str, Any]] = []


def _run_attempt(substrate: Substrate, case_id: str, attempt: int) -> tuple[ExamObservation, Any]:
    """One live call through the shared, contestant-neutral runner."""
    record = run_attempt(
        ASTRA, substrate, case_id, attempt, api_key=os.environ[ASTRA.credential_env]
    )
    MEASUREMENTS.append(record.measurement)
    return record.observation, record.governance_error


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

    score_global_gates(observation, candidate=CANDIDATE)
    score_case_a_new(observation, claim_id=claim_id)
    assert error is None, f"governance rejected a live result: {error}"

    state = observation.state
    record = next(iter(state.intent_synthesis.decisions.values()))
    requirement = state.objects[record.identity.object_id("REQ")]
    assert isinstance(requirement, Requirement)

    if attempt == 1:
        # Preserve this genuinely model-authored ledger so the replay and containment
        # proofs can run later with no provider and no credential present.
        write_case_a_ledger(ASTRA, substrate)
    assert requirement.authority is Authority.PROPOSED
    assert requirement.materiality is Materiality.LOW
    assert [(r.relation_type, r.target_id) for r in requirement.relations] == [
        (RelationType.DERIVED_FROM, claim_id)
    ]
    assert requirement.provenance.source_kind is SourceKind.SYSTEM
    assert record.author.provider == OPENAI_PROVIDER_ID
    assert record.author.model == CANDIDATE.model
    assert record.author.policy_version == EXPECTED_POLICY_VERSION


@pytest.mark.parametrize("attempt", range(1, RUNS_PER_CASE + 1))
def test_case_b_existing_intent_is_unchanged(attempt: int) -> None:
    substrate = build_case_b()
    observation, error = _run_attempt(substrate, "B", attempt)

    score_global_gates(observation, candidate=CANDIDATE)
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

    score_global_gates(observation, candidate=CANDIDATE)
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

    score_global_gates(observation, candidate=CANDIDATE)
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

    score_global_gates(observation, candidate=CANDIDATE)
    score_case_e_injection(observation, real_claim_id=substrate.claim_ids["refund"])
    assert error is None, f"governance rejected a live result: {error}"

    state = observation.state
    for requirement in state.objects.values():
        if isinstance(requirement, Requirement) and requirement.id != "INTENT-payments":
            assert requirement.authority is Authority.PROPOSED


def test_zz_report_measurements() -> None:
    """Writes this contestant's measured baseline. Asserts only on completeness."""
    assert len(MEASUREMENTS) == 5 * RUNS_PER_CASE, (
        f"expected {5 * RUNS_PER_CASE} live calls, recorded {len(MEASUREMENTS)}"
    )
    # The predeclared transport guard must not have bound any call; if it did, the run is
    # a harness limit rather than a verdict about the model.
    assert_guard_was_not_binding(ASTRA, MEASUREMENTS)

    payload = write_measurements(
        ASTRA,
        MEASUREMENTS,
        policy_version=EXPECTED_POLICY_VERSION,
        prompt_sha256=EXPECTED_PROMPT_SHA256,
        runs_per_case=RUNS_PER_CASE,
    )

    print(f"\n=== live certification measurements: {ASTRA.label} ===")
    for m in MEASUREMENTS:
        print(
            f"  {m['case']}/{m['attempt']}  {m['outcome']:20s} "
            f"in={m['input_tokens']} out={m['output_tokens']} "
            f"cost={m['cost_usd']} ms={m['wall_clock_ms']} finish={m['finish_reason']}"
        )
    print(f"  evidence written to    : {ASTRA.measurements_path}")
    print(f"  known cost total       : {payload['known_cost_total']}")
    print(f"  unknown cost samples   : {payload['unknown_cost_samples']}")
    print(
        f"  output token high water: {payload['output_token_high_water']} "
        f"(guard {payload['output_token_guard']})"
    )
