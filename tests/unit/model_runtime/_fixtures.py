"""Shared builders for the Model Runtime suite. Test-local only."""

from __future__ import annotations

from pydantic import Field

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
    ModelUsage,
)


class Answer(FrozenModel):
    """A caller-owned output type. The runtime never knows what this means."""

    statement: str = Field(min_length=1)
    confidence: float | None = None


class OtherAnswer(FrozenModel):
    verdict: str = Field(min_length=1)


def identity(provider: str = "provider-a", model: str = "model-1") -> ModelIdentity:
    return ModelIdentity(provider=provider, model=model)


def descriptor(
    provider: str = "provider-a",
    model: str = "model-1",
    *,
    tiers: frozenset[ModelTier] = frozenset({ModelTier.REASONER}),
    capabilities: frozenset[ModelCapability] = frozenset(
        {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
    ),
    certified_tasks: frozenset[ModelTask] = frozenset({ModelTask.INTENT_SYNTHESIS}),
    max_context_tokens: int | None = None,
) -> ModelDescriptor:
    return ModelDescriptor(
        identity=identity(provider, model),
        tiers=tiers,
        capabilities=capabilities,
        certified_tasks=certified_tasks,
        max_context_tokens=max_context_tokens,
    )


def trace(call_id: str = "CALL-1", parent_call_id: str | None = None) -> ModelTraceContext:
    return ModelTraceContext(run_id="RUN-1", call_id=call_id, parent_call_id=parent_call_id)


def request(
    *,
    task: ModelTask = ModelTask.INTENT_SYNTHESIS,
    tier: ModelTier = ModelTier.REASONER,
    required_capabilities: frozenset[ModelCapability] = frozenset(
        {ModelCapability.STRUCTURED_OUTPUT}
    ),
    constraints: ModelExecutionConstraints | None = None,
    policy_id: str = "intent.synthesis",
    policy_version: str = "v1",
) -> ModelRequest:
    return ModelRequest(
        task=task,
        tier=tier,
        messages=(
            ModelMessage(role=MessageRole.SYSTEM, content="You are bound by the caller's policy."),
            ModelMessage(role=MessageRole.USER, content="Here is the bounded context."),
        ),
        required_capabilities=required_capabilities,
        policy_id=policy_id,
        policy_version=policy_version,
        constraints=constraints or ModelExecutionConstraints(),
        trace=trace(),
    )


def usage(**overrides: object) -> ModelUsage:
    base: dict[str, object] = {
        "input_tokens": 120,
        "output_tokens": 45,
        "cost_usd": 0.0031,
        "wall_clock_ms": 812,
    }
    base.update(overrides)
    return ModelUsage(**base)  # type: ignore[arg-type]
