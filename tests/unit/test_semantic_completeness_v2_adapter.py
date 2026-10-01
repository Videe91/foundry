"""The provider-neutral v2 (structured) verifier adapter, offline.

``ModelRuntimeStructuredCompletenessVerifier`` sends one ``CompletenessRequest`` through the Model
Runtime under policy ``ie2-semantic-completeness-v2`` with its own instruction, and asks for a
``StructuredCompletenessReport``. It names no provider and no model; every provider adapter can
compile the structured output contract. v1's adapter is untouched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.model_runtime.xai import XAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_SYSTEM_INSTRUCTION,
    COMPLETENESS_SYSTEM_INSTRUCTION_SHA256,
    STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION,
    STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION_SHA256,
    ModelRuntimeStructuredCompletenessVerifier,
)
from foundry.domain.semantic_completeness import (
    FINDING_KINDS,
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
    STRUCTURED_REPORT_FORMAT,
    StructuredCompletenessReport,
    StructuredPropositionVerdict,
)
from foundry.model_runtime.domain import (
    ModelCapability,
    ModelDescriptor,
    ModelIdentity,
    ModelTask,
    ModelTier,
    ModelUsage,
)
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.registry import build_registry
from foundry.model_runtime.runtime import ModelRuntime
from tests.unit.test_semantic_completeness_v2_domain import GOOD, REQUEST


def _runtime(output: object) -> tuple[ModelRuntime, FakeModelProvider]:
    provider = FakeModelProvider(
        provider_id="provider-v",
        responses=(
            ScriptedResponse(
                output=output,
                model="verifier-model",
                usage=ModelUsage(input_tokens=10, output_tokens=5, wall_clock_ms=7),
            ),
        ),
    )
    registry = build_registry(
        (
            ModelDescriptor(
                identity=ModelIdentity(provider="provider-v", model="verifier-model"),
                tiers=frozenset({ModelTier.REASONER}),
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                ),
                certified_tasks=frozenset({ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION}),
            ),
        )
    )
    return ModelRuntime(registry=registry, providers=(provider,)), provider


def test_the_structured_verifier_runs_policy_v2_and_returns_the_structured_report() -> None:
    runtime, provider = _runtime(GOOD.model_dump(mode="json"))
    result = ModelRuntimeStructuredCompletenessVerifier(runtime=runtime, run_id="RUN-V").verify(
        REQUEST
    )
    (call,) = provider.requests
    assert call.request.task is ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION
    assert call.request.tier is ModelTier.REASONER
    assert (call.request.policy_id, call.request.policy_version) == (
        COMPLETENESS_POLICY_ID,
        SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
    )
    assert call.request.messages[0].content == STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION
    assert json.loads(call.request.messages[1].content) == REQUEST.model_dump(mode="json")
    assert call.output_type is StructuredCompletenessReport
    assert result.report == GOOD
    assert result.verifier.policy_version == SEMANTIC_COMPLETENESS_POLICY_VERSION_V2
    assert (result.verifier.provider, result.verifier.model) == ("provider-v", "verifier-model")
    assert (result.input_tokens, result.output_tokens, result.wall_clock_ms) == (10, 5, 7)


def test_an_answer_that_is_not_a_structured_report_is_recorded_as_no_report() -> None:
    v1_shaped = {
        "verdicts": [{"proposition_id": "p13", "verdict": "COMPLETE", "claim_refs": ["JDG-1"]}]
    }
    runtime, _ = _runtime(v1_shaped)
    result = ModelRuntimeStructuredCompletenessVerifier(runtime=runtime, run_id="R").verify(REQUEST)
    assert result.report is None
    assert result.verifier.policy_version == SEMANTIC_COMPLETENESS_POLICY_VERSION_V2


def test_the_instruction_is_pinned_and_v1_is_unchanged() -> None:
    v2 = hashlib.sha256(STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert v2 == STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION_SHA256
    v1 = hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert v1 == COMPLETENESS_SYSTEM_INSTRUCTION_SHA256
    assert v1 == "56b753a9156883264f9bdd070f9b5b63facb653c68bdb5fbcd0c0322814a0d7c"


def test_the_instruction_asks_for_kinds_directions_and_verbatim_quotes() -> None:
    text = " ".join(STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION.split())
    for phrase in (
        "every operative assertion",
        "union",
        "paraphrase",
        "MISSING",
        "UNSUPPORTED",
        "CONTRADICTORY",
        "proposition_evidence",
        "claim_ref",
        "claim_evidence",
        "verbatim",
        "never propose",
        STRUCTURED_REPORT_FORMAT,
        "prefer CONTRADICTORY, then INCOMPLETE, then OVERREACH",
    ):
        assert phrase in text, phrase
    for kind in FINDING_KINDS:
        assert kind in text, kind


def test_every_provider_adapter_compiles_the_structured_contract() -> None:
    for provider in (OpenAIModelProvider, XAIModelProvider, AnthropicModelProvider):
        schema = provider.wire_schema(StructuredCompletenessReport)
        assert schema, provider.__name__
    assert StructuredPropositionVerdict.model_json_schema()


def test_the_adapter_names_no_provider_or_model() -> None:
    source = Path("src/foundry/adapters/semantics/completeness_verifier.py").read_text().lower()
    for name in ("grok", "gpt", "claude", "astra", "openai", "anthropic", "xai"):
        assert name not in source, name
