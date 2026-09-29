"""The certified Astra graph synthesizer, wired exactly as the exam-v6 contestant (design §4).

Provider ``openai``, model ``gpt-6-astra``, reasoning effort ``high``, mode ``standard``,
output guard 16,000, timeout 180 s, at tier ``REASONER``, through the shared Model Runtime and
the runtime-v4 graph adapter. The OpenAI adapter disables transport retries
(``max_retries=0``), so one synthesis is one provider execution.

No descriptor here names a certified task (R110: production never claims a graph
certification). The one descriptor is derived at run time from the exam-v6 certificate record,
which the entry point has proven ``CURRENT`` before calling ``registry_from_certificate``: the
certificate is the authority, and the registry only repeats what it binds.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import count
from typing import Any

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    ModelRuntimeIntentGraphSynthesizer,
)
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.experiments.long_horizon_ie2_ie3 import protocol
from foundry.experiments.long_horizon_ie2_ie3.recording import (
    IE3Budget,
    RecordingGraphProvider,
    RunBudget,
)
from foundry.model_runtime.domain import (
    ModelCapability,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime

__all__ = ["ASTRA", "astra_constraints", "build_synthesizer", "registry_from_certificate"]

ASTRA = ModelIdentity(provider=protocol.IE3_PROVIDER, model=protocol.IE3_MODEL)


def registry_from_certificate(record: Mapping[str, Any]) -> ModelRegistry:
    """The descriptor a CURRENT certificate binds: its provider, model and task, nothing else.

    Refuses a record that is not this experiment's certified identity."""
    if (record.get("provider"), record.get("model"), record.get("task"), record.get("verdict")) != (
        protocol.IE3_PROVIDER,
        protocol.IE3_MODEL,
        protocol.IE3_TASK,
        "PASS",
    ):
        raise ValueError("the certificate record is not this experiment's certified identity")
    return ModelRegistry(
        descriptors=(
            ModelDescriptor(
                identity=ASTRA,
                tiers=frozenset({ModelTier.REASONER}),
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                ),
                certified_tasks=frozenset({ModelTask(str(record["task"]))}),
            ),
        )
    )


def astra_constraints() -> ModelExecutionConstraints:
    return ModelExecutionConstraints(
        timeout_seconds=protocol.IE3_TIMEOUT_SECONDS,
        max_output_tokens=protocol.IE3_OUTPUT_GUARD,
        max_cost_usd=None,
    )


def build_synthesizer(
    provider: Any, budget: RunBudget, registry: ModelRegistry
) -> tuple[ModelRuntimeIntentGraphSynthesizer, RecordingGraphProvider]:
    """``provider`` is an ``OpenAIModelProvider`` (live) or a test double with its id;
    ``registry`` comes from ``registry_from_certificate``."""
    recording = RecordingGraphProvider(provider, IE3Budget(budget))
    runtime = ModelRuntime(registry=registry, providers=(recording,))
    calls = count(1)
    trace: Callable[[], ModelTraceContext] = lambda: ModelTraceContext(  # noqa: E731
        run_id="LH23-IE3", call_id=f"CALL-{next(calls)}"
    )
    synthesizer = ModelRuntimeIntentGraphSynthesizer(
        runtime=runtime,
        model_identity=ASTRA,
        trace_factory=trace,
        execution_constraints=astra_constraints(),
    )
    return synthesizer, recording


def live_provider(api_key: str) -> OpenAIModelProvider:
    return OpenAIModelProvider(
        api_key=api_key,
        reasoning_effort=protocol.IE3_REASONING_EFFORT,
        reasoning_mode=protocol.IE3_REASONING_MODE,
    )
