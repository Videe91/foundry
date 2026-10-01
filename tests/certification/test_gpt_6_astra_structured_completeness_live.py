"""Structured live certification: openai/gpt-6-astra for SEMANTIC_COMPLETENESS_VERIFICATION under
the structured verifier ``ie2-semantic-completeness-v2``, on ``ie2-semantic-completeness-
structured-exam-v1``.

A new lineage. It inherits nothing from the free-text completeness exams (v1-v5, all NOT
CERTIFIED) or from Astra's IE3 graph certificate. The contestant sits exactly the structured
verifier contract through exactly the OpenAI wire schema it is certified under: the runtime
refuses to route anything else. The certificate it writes binds the provider, model, task,
verifier policy, instruction, report format, canonical and wire schemas, compiler, this exam,
the provider configuration, the repetition rule and the call budget.

Opt-in twice over: ``OPENAI_API_KEY`` **and** ``RUN_LIVE_MODEL_CERTIFICATION=1``. It refuses to
start unless the structured exam is sealed and the sealed exam is the current one. Every case is
run three independent times; every run must pass.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import pytest

from foundry.adapters.model_runtime.openai import OPENAI_PROVIDER_ID, OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_V2_CONTRACT,
    STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION,
)
from foundry.domain.semantic_completeness import StructuredCompletenessReport
from foundry.model_runtime.domain import CertifiedContract, ModelIdentity, ModelTask
from tests.certification._certification_run import Contestant, ProtocolTaskFailure
from tests.certification._completeness_exam import (
    CERTIFIED_CONFIGURATION,
    attempt_evidence,
)
from tests.certification._intent_graph_exam import production_base
from tests.certification._schema_identity import schema_sha256
from tests.certification._structured_completeness_exam import (
    CALL_BUDGET,
    CASES,
    EXPECTED_EXAM_SHA256,
    EXPECTED_INSTRUCTION_SHA256,
    RUNS_PER_CASE,
    STRUCTURED_EVIDENCE_NAMESPACE,
    case_by_id,
    run_structured_attempt,
    score_structured_attempt,
    structured_exam_sha256,
    structured_seal_problems,
    write_structured_certification,
)

CANDIDATE = ModelIdentity(provider=OPENAI_PROVIDER_ID, model="gpt-6-astra")

ASTRA_STRUCTURED = Contestant(
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
    evidence_namespace=STRUCTURED_EVIDENCE_NAMESPACE,
    wire_schema=OpenAIModelProvider.wire_schema,
    wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    contracts=(
        CertifiedContract(
            task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
            contract=COMPLETENESS_V2_CONTRACT,
            wire_schema_sha256=schema_sha256(
                OpenAIModelProvider.wire_schema(StructuredCompletenessReport)
            ),
            wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
        ),
    ),
)

pytestmark = [
    pytest.mark.skipif(
        not (
            os.environ.get("OPENAI_API_KEY")
            and os.environ.get("RUN_LIVE_MODEL_CERTIFICATION") == "1"
        ),
        reason=(
            "LIVE_MODEL_CERTIFICATION_NOT_ENABLED: set OPENAI_API_KEY and "
            "RUN_LIVE_MODEL_CERTIFICATION=1 to sit the structured completeness exam"
        ),
    )
]

ATTEMPTS: list[dict[str, Any]] = []
BASE: dict[str, str] = {}


def test_the_contestant_is_frozen() -> None:
    """Asserted inside the exam itself, before any call."""
    assert structured_seal_problems() == ()
    assert structured_exam_sha256() == EXPECTED_EXAM_SHA256
    digest = hashlib.sha256(STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == EXPECTED_INSTRUCTION_SHA256 == COMPLETENESS_V2_CONTRACT.instruction_sha256
    assert len(CASES) * RUNS_PER_CASE == CALL_BUDGET
    BASE["frozen_production_base"] = production_base()


@pytest.mark.parametrize("attempt", range(1, RUNS_PER_CASE + 1))
@pytest.mark.parametrize("case_id", [c.case_id for c in CASES])
def test_structured_case(case_id: str, attempt: int) -> None:
    case = case_by_id(case_id)
    provider = ASTRA_STRUCTURED.provider_factory(os.environ[ASTRA_STRUCTURED.credential_env])
    try:
        observation = run_structured_attempt(ASTRA_STRUCTURED, case, attempt, provider=provider)
    except Exception as exc:
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
    failures = score_structured_attempt(observation, case, candidate=CANDIDATE)
    ATTEMPTS.append(
        attempt_evidence(observation, verdict="FAIL" if failures else "PASS", failures=failures)
    )
    assert not failures, failures


def test_zz_report_certification() -> None:
    """Writes every attempt's evidence and the verdict. Asserts only on completeness."""
    payload = write_structured_certification(
        ASTRA_STRUCTURED,
        ATTEMPTS,
        frozen_production_base=BASE.get("frozen_production_base", "UNPINNED"),
        configuration=CERTIFIED_CONFIGURATION,
    )
    print(f"\n=== IE2 structured completeness exam v1: {ASTRA_STRUCTURED.label} ===")
    for a in ATTEMPTS:
        print(
            f"  {a['case']}/{a['attempt']}  {a['verdict']:10s} "
            f"in={a['input_tokens']} out={a['output_tokens']} ms={a['wall_clock_ms']}"
            + (f"\n      failures: {a['failures']}" if a["failures"] else "")
        )
    print(f"  verdict: {payload['verdict']} ({payload['passed_attempts']}/{CALL_BUDGET})")
    assert len(ATTEMPTS) == CALL_BUDGET
