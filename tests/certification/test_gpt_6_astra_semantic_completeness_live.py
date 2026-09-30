"""IE2 live certification exam v2: openai/gpt-6-astra for SEMANTIC_COMPLETENESS_VERIFICATION.

A NEW task certificate. It inherits nothing from Astra's IE3 graph certification or Slice-1
record: the certificate it writes (``semantic_completeness_verification_exam_v2``) binds only
this provider, model, task, verifier policy ``ie2-semantic-completeness-v1``, instruction
digest, canonical ``CompletenessReport`` schema, OpenAI wire schema and compiler, exam v2,
provider configuration, repetition rule and call budget together.

Opt-in twice over, exactly as MR4/MR6: it requires ``OPENAI_API_KEY`` **and**
``RUN_LIVE_MODEL_CERTIFICATION=1``. Holding a key must never fire live calls from the default
suite. It refuses to start unless exam v2 is sealed and the sealed exam is the current one.

Every attempt runs the production ``ModelRuntimeCompletenessVerifier`` through the Model Runtime
with a fresh runtime and verifier: 25 cases x 3 independent runs = 75 live calls, and every run
of every case must pass (no averaging, no majority). The provider configuration is Astra's
existing one (``reasoning_effort=high``, ``reasoning_mode=standard``) with the IE3 predeclared
180 s timeout as the adapter's default. The production verifier sends no execution
constraints, so no output guard reaches the transport and none is added: the certificate
records ``output_guard: null`` and the headroom rule (which measures a guard) has nothing to
measure. ``Contestant.max_output_tokens`` is therefore unused here.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import pytest

from foundry.adapters.model_runtime.openai import OPENAI_PROVIDER_ID, OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_SYSTEM_INSTRUCTION,
)
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    CompletenessReport,
)
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from tests.certification._certification_run import Contestant, ProtocolTaskFailure
from tests.certification._completeness_exam import (
    CASES,
    CERTIFIED_CONFIGURATION,
    COMPLETENESS_CALL_BUDGET,
    COMPLETENESS_EVIDENCE_NAMESPACE,
    COMPLETENESS_RUNS_PER_CASE,
    EXPECTED_COMPLETENESS_EXAM_SHA256,
    EXPECTED_INSTRUCTION_SHA256,
    EXPECTED_OPENAI_WIRE_SCHEMA_COMPILER,
    EXPECTED_OPENAI_WIRE_SCHEMA_SHA256,
    EXPECTED_REPORT_SCHEMA_SHA256,
    EXPECTED_VERIFIER_POLICY_ID,
    EXPECTED_VERIFIER_POLICY_VERSION,
    attempt_evidence,
    case_by_id,
    completeness_exam_sha256,
    completeness_seal_problems,
    run_completeness_attempt,
    score_completeness_attempt,
    write_completeness_certification,
)
from tests.certification._intent_graph_exam import production_base
from tests.certification._schema_identity import schema_sha256

CANDIDATE = ModelIdentity(provider=OPENAI_PROVIDER_ID, model="gpt-6-astra")

ASTRA_COMPLETENESS = Contestant(
    identity=CANDIDATE,
    credential_env="OPENAI_API_KEY",
    provider_factory=lambda api_key: OpenAIModelProvider(
        api_key=api_key,
        reasoning_effort="high",
        reasoning_mode="standard",
        default_timeout_seconds=CERTIFIED_CONFIGURATION.timeout_seconds,
    ),
    reasoning_effort="high",
    timeout_seconds=CERTIFIED_CONFIGURATION.timeout_seconds,
    task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
    evidence_namespace=COMPLETENESS_EVIDENCE_NAMESPACE,
    wire_schema=OpenAIModelProvider.wire_schema,
    wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
)

pytestmark = [
    pytest.mark.skipif(
        not (
            os.environ.get("OPENAI_API_KEY")
            and os.environ.get("RUN_LIVE_MODEL_CERTIFICATION") == "1"
        ),
        reason=(
            "LIVE_MODEL_CERTIFICATION_NOT_ENABLED: set OPENAI_API_KEY and "
            "RUN_LIVE_MODEL_CERTIFICATION=1 to sit the semantic completeness exam"
        ),
    )
]

ATTEMPTS: list[dict[str, Any]] = []
BASE: dict[str, str] = {}


def test_the_contestant_is_frozen() -> None:
    """Asserted inside the exam itself, before any call, and pinned to an unmodified src/."""
    assert completeness_seal_problems() == ()
    assert completeness_exam_sha256() == EXPECTED_COMPLETENESS_EXAM_SHA256
    digest = hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == EXPECTED_INSTRUCTION_SHA256
    assert COMPLETENESS_POLICY_ID == EXPECTED_VERIFIER_POLICY_ID
    assert SEMANTIC_COMPLETENESS_POLICY_VERSION == EXPECTED_VERIFIER_POLICY_VERSION
    assert schema_sha256(CompletenessReport.model_json_schema()) == EXPECTED_REPORT_SCHEMA_SHA256
    wire = schema_sha256(OpenAIModelProvider.wire_schema(CompletenessReport))
    assert wire == EXPECTED_OPENAI_WIRE_SCHEMA_SHA256
    assert OpenAIModelProvider.WIRE_SCHEMA_COMPILER == EXPECTED_OPENAI_WIRE_SCHEMA_COMPILER
    assert len(CASES) * COMPLETENESS_RUNS_PER_CASE == COMPLETENESS_CALL_BUDGET
    BASE["frozen_production_base"] = production_base()


@pytest.mark.parametrize("attempt", range(1, COMPLETENESS_RUNS_PER_CASE + 1))
@pytest.mark.parametrize("case_id", [c.case_id for c in CASES])
def test_completeness_case(case_id: str, attempt: int) -> None:
    case = case_by_id(case_id)
    provider = ASTRA_COMPLETENESS.provider_factory(os.environ[ASTRA_COMPLETENESS.credential_env])
    try:
        observation = run_completeness_attempt(ASTRA_COMPLETENESS, case, attempt, provider=provider)
    except Exception as exc:
        # Transport and harness limits are INCOMPLETE (not verdicts); a protocol fault is
        # NOT CERTIFIED. Either way the attempt is recorded under its own category.
        category = "FAIL" if isinstance(exc, ProtocolTaskFailure) else "INCOMPLETE"
        ATTEMPTS.append(
            {
                "case": case_id,
                "attempt": attempt,
                "verdict": category,
                "failures": [f"{type(exc).__name__}: {exc}"],
                "request_json": None,
                "raw_output": None,
                "parsed_report": None,
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
                "wall_clock_ms": None,
                "finish_reason": None,
            }
        )
        raise
    failures = score_completeness_attempt(observation, case, candidate=CANDIDATE)
    ATTEMPTS.append(
        attempt_evidence(observation, verdict="FAIL" if failures else "PASS", failures=failures)
    )
    assert not failures, failures


def test_zz_report_certification() -> None:
    """Writes every attempt's evidence and the verdict. Asserts only on completeness."""
    payload = write_completeness_certification(
        ASTRA_COMPLETENESS,
        ATTEMPTS,
        frozen_production_base=BASE.get("frozen_production_base", "UNPINNED"),
        configuration=CERTIFIED_CONFIGURATION,
    )
    print(f"\n=== IE2 semantic completeness certification: {ASTRA_COMPLETENESS.label} ===")
    for a in ATTEMPTS:
        print(
            f"  {a['case']}/{a['attempt']}  {a['verdict']:10s} "
            f"in={a['input_tokens']} out={a['output_tokens']} cost={a['cost_usd']} "
            f"ms={a['wall_clock_ms']} finish={a['finish_reason']}"
            + (f"\n      failures: {a['failures']}" if a["failures"] else "")
        )
    print(
        f"  verdict: {payload['verdict']} ({payload['passed_attempts']}/{COMPLETENESS_CALL_BUDGET})"
    )
    assert len(ATTEMPTS) == COMPLETENESS_CALL_BUDGET, (
        f"expected {COMPLETENESS_CALL_BUDGET} live calls, recorded {len(ATTEMPTS)}"
    )
