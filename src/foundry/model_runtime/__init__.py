"""Foundry Model Runtime — the shared, provider-neutral socket to models.

A root primitive, peer to ``domain``, ``application``, ``ports`` and ``adapters``,
because every Foundry domain will eventually use it: Intent, Research, Architecture,
Planning, Evaluation, Coding and Testing workers, Operations.

The split it enforces:

* the **domain** decides what work is needed, what bounded context is supplied, what
  output schema is legal, what policy applies, and what authority a result may have;
* the **runtime** decides which certified model may execute it, which adapter to call,
  how to invoke it, and how to normalize the metadata that comes back.

It is not an agent framework. Single-call execution only — delegation, critics, parallel
lenses, escalation and reasoning budgets belong to a future Reasoning Orchestrator that
sits above this package, and a model never controls provider-to-provider calls itself.
"""

from foundry.model_runtime.domain import (
    REQUIRED_TIER_BY_TASK,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelExecutionResult,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelResultMetadata,
    ModelTask,
    ModelTier,
    ModelTraceContext,
    ModelUsage,
    required_tier,
)
from foundry.model_runtime.errors import (
    ModelProtocolError,
    ModelProviderError,
    ModelProviderUnavailableError,
    ModelRequestError,
    ModelRuntimeError,
    ModelUnavailableError,
)
from foundry.model_runtime.ports import ModelProvider, ProviderExecutionResult
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.routing import select_model
from foundry.model_runtime.runtime import ModelRuntime

__all__ = [
    "REQUIRED_TIER_BY_TASK",
    "MessageRole",
    "ModelCapability",
    "ModelDescriptor",
    "ModelExecutionConstraints",
    "ModelExecutionResult",
    "ModelIdentity",
    "ModelMessage",
    "ModelProtocolError",
    "ModelProvider",
    "ModelProviderError",
    "ModelProviderUnavailableError",
    "ModelRegistry",
    "ModelRequest",
    "ModelRequestError",
    "ModelResultMetadata",
    "ModelRuntime",
    "ModelRuntimeError",
    "ModelTask",
    "ModelTier",
    "ModelTraceContext",
    "ModelUnavailableError",
    "ModelUsage",
    "ProviderExecutionResult",
    "required_tier",
    "select_model",
]
