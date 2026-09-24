"""MR5 live smoke — a real credential, a real model, through the real Model Runtime.

Opt-in. Skips cleanly without ``OPENAI_API_KEY`` so the default suite never needs a secret
or a network. Deliberately **not** gated on ``RUN_LIVE_MODEL_CERTIFICATION``: that flag
guards the expensive fifteen-call Intent exam, and this is one cheap transport call.

What this proves is narrow and worth stating precisely: that a real credential reaches a
real ``gpt-6-astra`` through ``ModelRuntime`` → ``OpenAIModelProvider`` → the Responses API
and returns a typed object with normalized metadata. It proves **transport and protocol**,
nothing else.

It makes no claim about answer quality. The only fact checked is deterministic arithmetic,
chosen because it can be verified without judgement; deciding whether Astra is trustworthy
for a Foundry task by eyeballing one reply would be exactly the "generation certifies
itself" failure Law 5 forbids. The descriptor below grants the single task this smoke
needs — ``EVALUATION`` — and that entry is test-local transport permission, **not** an
``INTENT_SYNTHESIS`` certification. Certifying Astra for Intent Synthesis is MR6, run
through the same frozen five-case exam already used for Grok.
"""

from __future__ import annotations

import os

import pytest
from pydantic import Field

from foundry.adapters.model_runtime.openai import OPENAI_PROVIDER_ID, OpenAIModelProvider
from foundry.domain.common import FrozenModel
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime

GPT_6_ASTRA = "gpt-6-astra"

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="LIVE_OPENAI_NOT_RUN_NO_CREDENTIAL: set OPENAI_API_KEY to run the live smoke",
)


class ArithmeticAnswer(FrozenModel):
    """A tiny caller-owned schema. Deliberately NOT an Intent domain type."""

    answer: int
    units: str = Field(min_length=1)


def test_gpt_6_astra_executes_through_the_shared_model_runtime() -> None:
    api_key = os.environ["OPENAI_API_KEY"]
    registry = ModelRegistry(
        descriptors=(
            ModelDescriptor(
                identity=ModelIdentity(provider=OPENAI_PROVIDER_ID, model=GPT_6_ASTRA),
                tiers=frozenset({ModelTier.REASONER}),
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                ),
                # Transport permission for this smoke only. Not an Intent certification.
                certified_tasks=frozenset({ModelTask.EVALUATION}),
            ),
        )
    )
    runtime = ModelRuntime(
        registry=registry,
        providers=(
            OpenAIModelProvider(
                api_key=api_key,
                reasoning_effort="high",
                reasoning_mode="standard",
            ),
        ),
    )

    request = ModelRequest(
        task=ModelTask.EVALUATION,
        tier=ModelTier.REASONER,
        messages=(
            ModelMessage(
                role=MessageRole.SYSTEM,
                content="You compute exactly and answer only in the requested structure.",
            ),
            ModelMessage(role=MessageRole.USER, content="17 × 4"),
        ),
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id="mr5.transport-smoke",
        policy_version="mr5-openai-v1",
        constraints=ModelExecutionConstraints(timeout_seconds=120.0),
        trace=ModelTraceContext(run_id="mr5-live", call_id="mr5-live-1"),
    )

    result = runtime.execute(request, output_type=ArithmeticAnswer)

    # The deterministic fact, and the only quality claim made anywhere in MR5.
    assert result.output.answer == 68
    assert result.output.units

    metadata = result.metadata
    assert metadata.identity.provider == OPENAI_PROVIDER_ID
    assert metadata.identity.model == GPT_6_ASTRA, (
        "the runtime compares the provider's reported model against the selected "
        "descriptor; a mismatch here is a substitution, not a naming detail"
    )
    assert metadata.task is ModelTask.EVALUATION
    assert metadata.tier is ModelTier.REASONER

    usage = metadata.usage
    assert usage.wall_clock_ms is not None and usage.wall_clock_ms > 0
    if usage.input_tokens is not None:
        assert usage.input_tokens > 0
    if usage.output_tokens is not None:
        assert usage.output_tokens > 0
    assert usage.cost_usd is None, (
        "the Responses API reports no authoritative dollar cost, and MR5 never estimates one"
    )

    # The credential is transport state and must not have travelled into the result.
    assert api_key not in result.model_dump_json()
    assert api_key not in str(metadata)
