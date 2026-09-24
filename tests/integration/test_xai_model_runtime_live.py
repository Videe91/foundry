"""MR2 live smoke — a real credential, a real model, through the real Model Runtime.

Opt-in. Skips cleanly without ``XAI_API_KEY`` so the default suite never needs a secret
or a network.

What this proves is narrow and worth stating precisely: that a real credential reaches a
real ``grok-4.7`` through ``ModelRuntime`` → ``XAIModelProvider`` and returns a typed
object with normalized metadata. It proves **transport and protocol**, nothing else.

It deliberately makes no assertion about answer quality. Whether Grok is trustworthy for
a given Foundry task is a task-specific evaluation question, and answering it by eyeballing
one arithmetic reply would be exactly the "generation certifies itself" failure Law 5
forbids. The registry below certifies the single task this smoke needs and nothing more.
"""

from __future__ import annotations

import os

import pytest
from pydantic import Field

from foundry.adapters.model_runtime.xai import XAI_PROVIDER_ID, XAIModelProvider
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

GROK_4_7 = "grok-4.7"

pytestmark = pytest.mark.skipif(
    not os.environ.get("XAI_API_KEY"),
    reason="LIVE_XAI_NOT_RUN_NO_CREDENTIAL: set XAI_API_KEY to run the live smoke",
)


class ArithmeticAnswer(FrozenModel):
    """A tiny caller-owned schema. Deliberately NOT an Intent domain type."""

    answer: int
    units: str = Field(min_length=1)


def test_grok_4_7_executes_through_the_shared_model_runtime() -> None:
    registry = ModelRegistry(
        descriptors=(
            ModelDescriptor(
                identity=ModelIdentity(provider=XAI_PROVIDER_ID, model=GROK_4_7),
                tiers=frozenset({ModelTier.REASONER}),
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                ),
                # The minimum certification this transport proof needs. Grok is NOT
                # certified here for INTENT_SYNTHESIS or for every reasoner task.
                certified_tasks=frozenset({ModelTask.EVALUATION}),
            ),
        )
    )
    provider = XAIModelProvider(api_key=os.environ["XAI_API_KEY"], reasoning_effort="high")
    runtime = ModelRuntime(registry=registry, providers=(provider,))

    request = ModelRequest(
        task=ModelTask.EVALUATION,
        tier=ModelTier.REASONER,
        messages=(
            ModelMessage(
                role=MessageRole.SYSTEM,
                content="Answer with the requested structured fields only.",
            ),
            ModelMessage(
                role=MessageRole.USER,
                content="What is 17 multiplied by 4? Give the number and the units 'units'.",
            ),
        ),
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id="mr2.live.smoke",
        policy_version="v1",
        constraints=ModelExecutionConstraints(timeout_seconds=120.0),
        trace=ModelTraceContext(run_id="RUN-live", call_id="CALL-live"),
    )

    result = runtime.execute(request, output_type=ArithmeticAnswer)

    # --- transport and protocol facts only ---
    assert isinstance(result.output, ArithmeticAnswer)
    assert result.metadata.identity.provider == XAI_PROVIDER_ID
    assert result.metadata.identity.model == GROK_4_7
    assert result.metadata.task is ModelTask.EVALUATION
    assert result.metadata.tier is ModelTier.REASONER
    assert result.metadata.trace.run_id == "RUN-live"
    assert result.metadata.usage.wall_clock_ms is not None
    assert result.metadata.usage.wall_clock_ms >= 0
    if result.metadata.usage.input_tokens is not None:
        assert result.metadata.usage.input_tokens > 0

    # No credential may survive into anything the caller can hold.
    assert os.environ["XAI_API_KEY"] not in result.model_dump_json()
