"""IE3 live certification exam: openai/gpt-6-astra for INTENT_GRAPH_SYNTHESIS.

A NEW certification. It inherits nothing from Astra's Slice-1 (INTENT_SYNTHESIS) record, from
Grok 4.7's graph records or from the runtime-v1 graph prompt: the certificate it writes binds
only this provider, model, task, policy id, policy version and prompt digest together.

Opt-in twice over, exactly as MR4/MR6: it requires ``OPENAI_API_KEY`` **and**
``RUN_LIVE_MODEL_CERTIFICATION=1``. Holding a key must never fire live calls from the default
suite.

The exam is the one Grok sat, unchanged: every substrate builder and scorer is imported from
``_intent_graph_exam``. Eight scenarios x three independent runs = twenty-four live calls, and
every run of every case must pass. This file contributes a contestant and nothing else.

The provider configuration is Astra's existing, already-certified one (``reasoning_effort=high``,
``reasoning_mode=standard``). The output guard is Astra's predeclared 16,000 rather than the
graph exam's 4,000, for the reason already recorded in its Slice-1 runner: for OpenAI reasoning
models that bound covers reasoning tokens as well as visible output. It is a transport bound,
not part of the semantic contestant, and it must stay non-binding
(``assert_guard_was_not_binding``). The timeout is the graph exam's predeclared
``GRAPH_TIMEOUT_SECONDS``.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import pytest

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_ID,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
)
from foundry.adapters.model_runtime.openai import OPENAI_PROVIDER_ID, OpenAIModelProvider
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from tests.certification._certification_run import (
    Contestant,
    ProtocolTaskFailure,
    assert_guard_was_not_binding,
    write_measurements,
)
from tests.certification._intent_graph_exam import (
    EXPECTED_GRAPH_POLICY_ID,
    EXPECTED_GRAPH_POLICY_VERSION,
    EXPECTED_GRAPH_PROMPT_SHA256,
    GRAPH_BUILDERS,
    GRAPH_CASES,
    GRAPH_EVIDENCE_NAMESPACE,
    GRAPH_RUNS_PER_CASE,
    GRAPH_TIMEOUT_SECONDS,
    attempt_evidence,
    production_base,
    run_graph_attempt,
    score_graph_attempt,
    write_graph_certification,
    write_graph_ledger,
)

CANDIDATE = ModelIdentity(provider=OPENAI_PROVIDER_ID, model="gpt-6-astra")

ASTRA_OUTPUT_GUARD = 16000
"""Astra's predeclared reasoning-inclusive guard, reused unchanged from its Slice-1 runner."""

ASTRA_GRAPH = Contestant(
    identity=CANDIDATE,
    credential_env="OPENAI_API_KEY",
    provider_factory=lambda api_key: OpenAIModelProvider(
        api_key=api_key,
        reasoning_effort="high",
        reasoning_mode="standard",
    ),
    reasoning_effort="high",
    max_output_tokens=ASTRA_OUTPUT_GUARD,
    timeout_seconds=GRAPH_TIMEOUT_SECONDS,
    task=ModelTask.INTENT_GRAPH_SYNTHESIS,
    evidence_namespace=GRAPH_EVIDENCE_NAMESPACE,
)

pytestmark = [
    pytest.mark.skipif(
        not (
            os.environ.get("OPENAI_API_KEY")
            and os.environ.get("RUN_LIVE_MODEL_CERTIFICATION") == "1"
        ),
        reason=(
            "LIVE_MODEL_CERTIFICATION_NOT_ENABLED: set OPENAI_API_KEY and "
            "RUN_LIVE_MODEL_CERTIFICATION=1 to sit the graph exam"
        ),
    )
]

ATTEMPTS: list[dict[str, Any]] = []
MEASUREMENTS: list[dict[str, Any]] = []
BASE: dict[str, str] = {}


def test_the_contestant_is_frozen() -> None:
    """Asserted inside the exam itself, before any call, and pinned to an unmodified src/."""
    assert hashlib.sha256(GRAPH_SYSTEM_INSTRUCTION.encode()).hexdigest() == (
        EXPECTED_GRAPH_PROMPT_SHA256
    )
    assert GRAPH_SYSTEM_INSTRUCTION_SHA256 == EXPECTED_GRAPH_PROMPT_SHA256
    assert GRAPH_SYNTHESIS_POLICY_ID == EXPECTED_GRAPH_POLICY_ID
    assert GRAPH_SYNTHESIS_POLICY_VERSION == EXPECTED_GRAPH_POLICY_VERSION
    BASE["frozen_production_base"] = production_base()


@pytest.mark.parametrize("attempt", range(1, GRAPH_RUNS_PER_CASE + 1))
@pytest.mark.parametrize("case_id", GRAPH_CASES)
def test_graph_case(case_id: str, attempt: int) -> None:
    substrate = GRAPH_BUILDERS[case_id]()
    provider = ASTRA_GRAPH.provider_factory(os.environ[ASTRA_GRAPH.credential_env])
    try:
        observation = run_graph_attempt(ASTRA_GRAPH, substrate, case_id, attempt, provider=provider)
    except Exception as exc:
        # Transport and harness limits are INCOMPLETE (not verdicts); a protocol fault is
        # NOT CERTIFIED. Either way the attempt is recorded under its own category.
        category = "FAIL" if isinstance(exc, ProtocolTaskFailure) else "INCOMPLETE"
        ATTEMPTS.append(
            {
                "case": case_id,
                "attempt": attempt,
                "verdict": category,
                "failure": f"{type(exc).__name__}: {exc}",
                "outcome": "NO_ANSWER",
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
                "wall_clock_ms": None,
                "finish_reason": None,
            }
        )
        raise
    verdict, failure = "FAIL", None
    try:
        score_graph_attempt(observation, substrate, candidate=CANDIDATE)
        verdict = "PASS"
    except AssertionError as exc:
        failure = str(exc)
        raise
    finally:
        record = attempt_evidence(observation, verdict=verdict, failure=failure)
        ATTEMPTS.append(record)
        MEASUREMENTS.append(record)
        if attempt == 1:
            write_graph_ledger(ASTRA_GRAPH, case_id, substrate)


def test_zz_report_certification() -> None:
    """Writes every attempt's evidence and the verdict. Asserts only on completeness."""
    required = len(GRAPH_CASES) * GRAPH_RUNS_PER_CASE
    payload = write_graph_certification(
        ASTRA_GRAPH,
        ATTEMPTS,
        frozen_production_base=BASE.get("frozen_production_base", "UNPINNED"),
    )
    write_measurements(
        ASTRA_GRAPH,
        MEASUREMENTS,
        policy_version=GRAPH_SYNTHESIS_POLICY_VERSION,
        prompt_sha256=GRAPH_SYSTEM_INSTRUCTION_SHA256,
        runs_per_case=GRAPH_RUNS_PER_CASE,
    )
    print(f"\n=== IE3 graph certification: {ASTRA_GRAPH.label} ===")
    for a in ATTEMPTS:
        print(
            f"  {a['case']}/{a['attempt']}  {a['verdict']:4s} {a['outcome']:14s} "
            f"in={a['input_tokens']} out={a['output_tokens']} cost={a['cost_usd']} "
            f"ms={a['wall_clock_ms']} finish={a['finish_reason']}"
            + (f"\n      failure: {a['failure']}" if a["failure"] else "")
        )
    print(f"  verdict: {payload['verdict']} ({payload['passed_attempts']}/{required})")
    assert len(ATTEMPTS) == required, f"expected {required} live calls, recorded {len(ATTEMPTS)}"
    assert_guard_was_not_binding(ASTRA_GRAPH, MEASUREMENTS)
