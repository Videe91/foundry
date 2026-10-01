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

**Contract-bound certification.** For a task in ``CONTRACT_BOUND_TASKS``, certification for the
task is not enough: a request names its exact output contract (``ModelContract``: the caller's
policy id and version, the digest of its instruction and of its canonical output schema) and a
model may serve it only if its descriptor certifies exactly that contract for that task
(``CertifiedContract``, optionally with the provider wire schema and compiler it was certified
under). The runtime still never interprets a policy: it compares identities.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, Field, model_validator

from foundry.domain.common import FrozenModel

__all__ = [
    "CONTRACT_BOUND_TASKS",
    "REQUIRED_TIER_BY_TASK",
    "CertifiedContract",
    "MessageRole",
    "ModelCapability",
    "ModelContract",
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
    "output_schema_sha256",
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
    INTENT_GRAPH_SYNTHESIS = "INTENT_GRAPH_SYNTHESIS"
    """IE3 R110: a distinct task. Certification for ``INTENT_SYNTHESIS`` never covers it."""
    RESEARCH_PLANNING = "RESEARCH_PLANNING"
    ARCHITECTURE = "ARCHITECTURE"
    PLANNING = "PLANNING"
    EVALUATION = "EVALUATION"
    GAP_ANALYSIS = "GAP_ANALYSIS"
    SEMANTIC_COMPLETENESS_VERIFICATION = "SEMANTIC_COMPLETENESS_VERIFICATION"
    """IE2 Call 3: verifying that claims preserve their propositions' meaning. A distinct task:
    certification for claim writing, or for any other task, never covers it."""

    CODING = "CODING"
    TESTING = "TESTING"
    RESEARCH_EXECUTION = "RESEARCH_EXECUTION"
    REPOSITORY_INSPECTION = "REPOSITORY_INSPECTION"
    DATA_TRANSFORMATION = "DATA_TRANSFORMATION"


REQUIRED_TIER_BY_TASK: Final[dict[ModelTask, ModelTier]] = {
    ModelTask.INTENT_SYNTHESIS: ModelTier.REASONER,
    ModelTask.INTENT_GRAPH_SYNTHESIS: ModelTier.REASONER,
    ModelTask.RESEARCH_PLANNING: ModelTier.REASONER,
    ModelTask.ARCHITECTURE: ModelTier.REASONER,
    ModelTask.PLANNING: ModelTier.REASONER,
    ModelTask.EVALUATION: ModelTier.REASONER,
    ModelTask.GAP_ANALYSIS: ModelTier.REASONER,
    ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION: ModelTier.REASONER,
    ModelTask.CODING: ModelTier.WORKER,
    ModelTask.TESTING: ModelTier.WORKER,
    ModelTask.RESEARCH_EXECUTION: ModelTier.WORKER,
    ModelTask.REPOSITORY_INSPECTION: ModelTier.WORKER,
    ModelTask.DATA_TRANSFORMATION: ModelTier.WORKER,
}
"""The single deterministic mapping. Every task pins exactly one legal tier."""


def required_tier(task: ModelTask) -> ModelTier:
    return REQUIRED_TIER_BY_TASK[task]


CONTRACT_BOUND_TASKS: Final[frozenset[ModelTask]] = frozenset(
    {ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION}
)
"""Tasks whose certification binds an exact output contract, not just the task: the semantic
completeness verifier has more than one policy (free-text v1, structured v2), and a model
certified for one must never serve the other."""

_SHA256: Final = r"^[0-9a-f]{64}$"


def output_schema_sha256(output_type: type[BaseModel]) -> str:
    """The canonical digest of an output contract: SHA-256 of its JSON schema serialised with
    sorted keys, no whitespace, UTF-8 -- the form every certification already binds."""
    canonical = json.dumps(
        output_type.model_json_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ModelContract(FrozenModel):
    """The exact contract one request runs under. The runtime compares it; never reads it."""

    policy_id: str = Field(min_length=1, pattern=r"\S")
    policy_version: str = Field(min_length=1, pattern=r"\S")
    instruction_sha256: str = Field(pattern=_SHA256)
    output_schema_sha256: str = Field(pattern=_SHA256)


class CertifiedContract(FrozenModel):
    """One contract a model is certified to serve for one task, and, when the certification was
    earned through a specific provider wire schema, that schema's digest and compiler."""

    task: ModelTask
    contract: ModelContract
    wire_schema_sha256: str | None = Field(default=None, pattern=_SHA256)
    wire_schema_compiler: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_wire_binding(self) -> CertifiedContract:
        if (self.wire_schema_sha256 is None) != (self.wire_schema_compiler is None):
            raise ValueError("a wire binding names both its schema digest and its compiler")
        return self


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
    certified_contracts: frozenset[CertifiedContract] = frozenset()
    """For contract-bound tasks: exactly which contracts this model may serve."""
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
    contract: ModelContract | None = None
    """Required for a contract-bound task; it repeats the policy label it is bound to."""

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
        if self.task in CONTRACT_BOUND_TASKS and self.contract is None:
            raise ValueError(f"task {self.task.value} is contract-bound: name its contract")
        if self.contract is not None and (
            self.contract.policy_id,
            self.contract.policy_version,
        ) != (
            self.policy_id,
            self.policy_version,
        ):
            raise ValueError("the contract must be the request's own policy id and version")
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
