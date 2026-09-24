"""Provider-neutral contracts for Foundry's Model Runtime.

Nothing here knows what any task *means*. The Runtime transports a bounded request to a
certified model and returns a typed result; deciding what the result is allowed to do is
the calling domain's business, and stays there.

The WORKER / REASONER split is a Foundry law rather than a naming convention. A WORKER
builds and executes inside a bounded task contract — coding, testing, extraction,
mechanical analysis — and reports a blockage upward rather than redesigning around it. A
REASONER decides: intent, architecture, planning, evaluation, critique. Crossing the two
silently is precisely how a builder ends up quietly re-architecting a system, so a
request whose declared tier disagrees with its task is refused structurally and is never
promoted or demoted to fit.

Tier is a **role certification, not a brand assumption**. No model is a reasoner because
of who made it; it is a reasoner for a task because Foundry certified it for that task.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, Field, model_validator

from foundry.domain.common import FrozenModel

__all__ = [
    "REQUIRED_TIER_BY_TASK",
    "MessageRole",
    "ModelCapability",
    "ModelDescriptor",
    "ModelExecutionConstraints",
    "ModelExecutionResult",
    "ModelIdentity",
    "ModelMessage",
    "ModelRequest",
    "ModelResultMetadata",
    "ModelTask",
    "ModelTier",
    "ModelTraceContext",
    "ModelUsage",
    "required_tier",
]


class ModelTier(StrEnum):
    """The two operational tiers. Exactly two, by law."""

    WORKER = "WORKER"
    REASONER = "REASONER"


class ModelCapability(StrEnum):
    """Only what the shared runtime must actually reason about when matching.

    Kept small on purpose. Matching is a generic subset test, so a future member is an
    additive change to this enum and to registry data — never an edit to routing logic.
    """

    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    TEXT_GENERATION = "TEXT_GENERATION"
    TOOL_USE = "TOOL_USE"
    VISION = "VISION"


class ModelTask(StrEnum):
    """Semantic task identity for certification and routing — never domain policy.

    The runtime needs to know *which* job this is so it can check certification. It does
    not know, and must not learn, what the job means.
    """

    INTENT_SYNTHESIS = "INTENT_SYNTHESIS"
    RESEARCH_PLANNING = "RESEARCH_PLANNING"
    ARCHITECTURE = "ARCHITECTURE"
    PLANNING = "PLANNING"
    EVALUATION = "EVALUATION"
    GAP_ANALYSIS = "GAP_ANALYSIS"

    CODING = "CODING"
    TESTING = "TESTING"
    RESEARCH_EXECUTION = "RESEARCH_EXECUTION"
    REPOSITORY_INSPECTION = "REPOSITORY_INSPECTION"
    DATA_TRANSFORMATION = "DATA_TRANSFORMATION"


REQUIRED_TIER_BY_TASK: Final[dict[ModelTask, ModelTier]] = {
    ModelTask.INTENT_SYNTHESIS: ModelTier.REASONER,
    ModelTask.RESEARCH_PLANNING: ModelTier.REASONER,
    ModelTask.ARCHITECTURE: ModelTier.REASONER,
    ModelTask.PLANNING: ModelTier.REASONER,
    ModelTask.EVALUATION: ModelTier.REASONER,
    ModelTask.GAP_ANALYSIS: ModelTier.REASONER,
    ModelTask.CODING: ModelTier.WORKER,
    ModelTask.TESTING: ModelTier.WORKER,
    ModelTask.RESEARCH_EXECUTION: ModelTier.WORKER,
    ModelTask.REPOSITORY_INSPECTION: ModelTier.WORKER,
    ModelTask.DATA_TRANSFORMATION: ModelTier.WORKER,
}
"""The single deterministic mapping. Every task pins exactly one legal tier."""


def required_tier(task: ModelTask) -> ModelTier:
    return REQUIRED_TIER_BY_TASK[task]


class ModelIdentity(FrozenModel):
    """Which model, at which provider. No SDK object, no endpoint, no credential."""

    provider: str = Field(min_length=1, pattern=r"\S")
    model: str = Field(min_length=1, pattern=r"\S")


class ModelDescriptor(FrozenModel):
    """What Foundry has certified this model to do.

    Certification is task-specific: being registered is not permission to perform every
    task, and supporting a tier is not permission to perform every task in it. A model
    may legitimately hold both tiers if Foundry certified it for both.
    """

    identity: ModelIdentity
    tiers: frozenset[ModelTier] = Field(min_length=1)
    capabilities: frozenset[ModelCapability] = frozenset()
    certified_tasks: frozenset[ModelTask] = frozenset()
    max_context_tokens: int | None = Field(default=None, gt=0)


class MessageRole(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class ModelMessage(FrozenModel):
    """One message. The caller owns the prompt bytes; the runtime only carries them."""

    role: MessageRole
    content: str = Field(min_length=1)


class ModelExecutionConstraints(FrozenModel):
    """Bounds the caller places on this one call.

    Every bound is optional because a caller may genuinely have none, but a stated bound
    must be meaningful: a zero or negative budget is a caller bug, not a way of saying
    "unlimited" — absence says that, and the two must not be spelled the same way. This
    constrains the caller's BUDGET only; an observed ``ModelUsage.cost_usd`` of ``0.0``
    is a legitimate fact and stays distinct from unknown.

    There is deliberately no retry or fallback policy here — MR1 owns single-call
    execution, and re-attempt policy is later work that belongs where the cost of
    re-attempting is understood.
    """

    max_output_tokens: int | None = Field(default=None, gt=0)
    timeout_seconds: float | None = Field(default=None, gt=0.0)
    max_cost_usd: float | None = Field(default=None, gt=0.0)


class ModelTraceContext(FrozenModel):
    """Trace structure, and only that.

    ``parent_call_id`` exists so a future Reasoning Orchestrator's delegation is
    traceable. MR1 never reads it to decide anything and never spawns a child call from
    it: a model must not be able to cause provider-to-provider calls by describing one.
    """

    run_id: str = Field(min_length=1, pattern=r"\S")
    call_id: str = Field(min_length=1, pattern=r"\S")
    parent_call_id: str | None = Field(default=None, min_length=1)


class ModelRequest(FrozenModel):
    """One provider-neutral call.

    ``policy_id`` and ``policy_version`` identify the *caller's* policy so a result can be
    attributed to it later. Their content stays with the domain that owns them; the
    runtime records the label and never interprets it.
    """

    task: ModelTask
    tier: ModelTier
    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    required_capabilities: frozenset[ModelCapability] = frozenset()
    policy_id: str = Field(min_length=1, pattern=r"\S")
    policy_version: str = Field(min_length=1, pattern=r"\S")
    constraints: ModelExecutionConstraints = Field(default_factory=ModelExecutionConstraints)
    trace: ModelTraceContext

    @model_validator(mode="after")
    def validate_tier_matches_task(self) -> ModelRequest:
        """A WORKER task submitted as REASONER (or the reverse) is a structural refusal.

        Auto-correcting would hide a caller bug behind a plausible-looking execution, and
        the two tiers carry different authority over the work they perform.
        """
        expected = required_tier(self.task)
        if self.tier is not expected:
            raise ValueError(
                f"task {self.task.value} requires tier {expected.value}, but the request "
                f"declares {self.tier.value}; the tier is never promoted or demoted to fit"
            )
        return self


class ModelUsage(FrozenModel):
    """Normalized runtime metering. Absent means unknown — never zero, never invented.

    ``None`` and ``0`` are deliberately distinguishable: a provider that cannot report
    cost is not a free call, and recording it as free would corrupt every budget built on
    top of it later.
    """

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    wall_clock_ms: int | None = Field(default=None, ge=0)


class ModelResultMetadata(FrozenModel):
    """Exactly what executed, under what request, and what it cost.

    Carries no verdict on the answer. Runtime success means the call completed and the
    contracts held — whether the answer is *right* is a separate concern by Law 5, and
    nothing here may be mistaken for a verification result.
    """

    identity: ModelIdentity
    task: ModelTask
    tier: ModelTier
    trace: ModelTraceContext
    usage: ModelUsage = Field(default_factory=ModelUsage)
    finish_reason: str | None = None


class ModelExecutionResult[T: BaseModel](FrozenModel):
    """The caller's typed output plus normalized metadata. No vendor object escapes."""

    output: T
    metadata: ModelResultMetadata
