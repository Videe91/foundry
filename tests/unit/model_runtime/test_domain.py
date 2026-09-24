"""MR1 — provider-neutral domain contracts, and the WORKER/REASONER law.

The two tiers are a Foundry law rather than a naming convention: a WORKER builds and
executes inside a bounded task contract, a REASONER decides. Crossing them silently is
how a builder ends up quietly redesigning a system, so a request whose declared tier
disagrees with its task is a structural refusal — never an auto-correction.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from foundry.model_runtime.domain import (
    REQUIRED_TIER_BY_TASK,
    MessageRole,
    ModelCapability,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelMessage,
    ModelTask,
    ModelTier,
    ModelTraceContext,
    ModelUsage,
    required_tier,
)
from tests.unit.model_runtime._fixtures import request

# --- the two tiers ---------------------------------------------------------------------


def test_exactly_two_operational_tiers_exist() -> None:
    assert {t.value for t in ModelTier} == {"WORKER", "REASONER"}


def test_every_task_pins_exactly_one_legal_tier() -> None:
    assert set(REQUIRED_TIER_BY_TASK) == set(ModelTask)
    for task in ModelTask:
        assert required_tier(task) in ModelTier


@pytest.mark.parametrize(
    ("task", "tier"),
    [
        (ModelTask.INTENT_SYNTHESIS, ModelTier.REASONER),
        (ModelTask.RESEARCH_PLANNING, ModelTier.REASONER),
        (ModelTask.ARCHITECTURE, ModelTier.REASONER),
        (ModelTask.PLANNING, ModelTier.REASONER),
        (ModelTask.EVALUATION, ModelTier.REASONER),
        (ModelTask.GAP_ANALYSIS, ModelTier.REASONER),
        (ModelTask.CODING, ModelTier.WORKER),
        (ModelTask.TESTING, ModelTier.WORKER),
        (ModelTask.RESEARCH_EXECUTION, ModelTier.WORKER),
        (ModelTask.REPOSITORY_INSPECTION, ModelTier.WORKER),
        (ModelTask.DATA_TRANSFORMATION, ModelTier.WORKER),
    ],
)
def test_the_task_to_tier_mapping_is_pinned(task: ModelTask, tier: ModelTier) -> None:
    assert required_tier(task) is tier


@pytest.mark.parametrize(
    ("task", "tier"),
    [
        (ModelTask.CODING, ModelTier.WORKER),
        (ModelTask.ARCHITECTURE, ModelTier.REASONER),
        (ModelTask.INTENT_SYNTHESIS, ModelTier.REASONER),
        (ModelTask.TESTING, ModelTier.WORKER),
    ],
)
def test_a_request_whose_tier_matches_its_task_is_accepted(
    task: ModelTask, tier: ModelTier
) -> None:
    assert request(task=task, tier=tier).tier is tier


@pytest.mark.parametrize(
    ("task", "wrong_tier"),
    [
        (ModelTask.CODING, ModelTier.REASONER),
        (ModelTask.TESTING, ModelTier.REASONER),
        (ModelTask.ARCHITECTURE, ModelTier.WORKER),
        (ModelTask.INTENT_SYNTHESIS, ModelTier.WORKER),
        (ModelTask.GAP_ANALYSIS, ModelTier.WORKER),
        (ModelTask.REPOSITORY_INSPECTION, ModelTier.REASONER),
    ],
)
def test_a_request_whose_tier_contradicts_its_task_is_refused_structurally(
    task: ModelTask, wrong_tier: ModelTier
) -> None:
    """Never promoted, never demoted — the caller is told it asked for the wrong thing."""
    with pytest.raises(ValidationError, match="tier"):
        request(task=task, tier=wrong_tier)


# --- identity, messages, constraints, trace ----------------------------------------------


@pytest.mark.parametrize(("provider", "model"), [("", "m"), ("p", ""), (" ", "m")])
def test_model_identity_requires_real_names(provider: str, model: str) -> None:
    with pytest.raises(ValidationError):
        ModelIdentity(provider=provider, model=model)


def test_message_roles_are_provider_neutral() -> None:
    assert {r.value for r in MessageRole} == {"SYSTEM", "USER", "ASSISTANT"}
    assert ModelMessage(role=MessageRole.USER, content="hello").content == "hello"


def test_an_empty_message_is_refused() -> None:
    with pytest.raises(ValidationError):
        ModelMessage(role=MessageRole.USER, content="")


def test_a_request_must_carry_at_least_one_message() -> None:
    document = request().model_dump()
    document["messages"] = ()
    with pytest.raises(ValidationError):
        type(request()).model_validate(document)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_output_tokens": 0},
        {"max_output_tokens": -1},
        {"timeout_seconds": 0.0},
        {"timeout_seconds": -0.5},
        {"max_cost_usd": -0.01},
    ],
)
def test_execution_constraints_reject_impossible_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ModelExecutionConstraints(**kwargs)  # type: ignore[arg-type]


def test_an_explicit_zero_cost_budget_is_rejected() -> None:
    """A stated budget must be spendable.

    ``max_cost_usd=0.0`` reads as "this call may cost nothing", which no real call can
    satisfy — it is a caller bug, not a way of saying "unlimited". Absence says
    unlimited; the two must not be spelled the same way.
    """
    with pytest.raises(ValidationError):
        ModelExecutionConstraints(max_cost_usd=0.0)


@pytest.mark.parametrize("budget", [0.000001, 0.01, 1.0, 250.0])
def test_a_positive_cost_budget_is_accepted(budget: float) -> None:
    assert ModelExecutionConstraints(max_cost_usd=budget).max_cost_usd == budget


def test_an_absent_cost_budget_remains_legal() -> None:
    assert ModelExecutionConstraints(max_cost_usd=None).max_cost_usd is None
    assert ModelExecutionConstraints().max_cost_usd is None


def test_an_observed_provider_cost_of_zero_is_still_legitimate() -> None:
    """The repair applies to the caller's BUDGET, never to reported usage.

    A provider genuinely reporting a zero-cost call is a fact, and it stays
    distinguishable from a provider that could not report cost at all.
    """
    assert ModelUsage(cost_usd=0.0).cost_usd == 0.0
    assert ModelUsage().cost_usd is None


def test_execution_constraints_may_be_entirely_unset() -> None:
    constraints = ModelExecutionConstraints()
    assert constraints.max_output_tokens is None
    assert constraints.timeout_seconds is None
    assert constraints.max_cost_usd is None


def test_no_retry_or_fallback_policy_exists_yet() -> None:
    """MR1 owns single-call execution; retry and fallback are later work."""
    fields = set(ModelExecutionConstraints.model_fields)
    assert not {f for f in fields if "retry" in f or "fallback" in f or "attempt" in f}


@pytest.mark.parametrize(("run_id", "call_id"), [("", "c"), ("r", "")])
def test_trace_ids_must_be_non_empty(run_id: str, call_id: str) -> None:
    with pytest.raises(ValidationError):
        ModelTraceContext(run_id=run_id, call_id=call_id)


def test_parent_call_id_is_trace_structure_only() -> None:
    """It exists so future orchestration can be traced — MR1 never acts on it."""
    child = ModelTraceContext(run_id="RUN-1", call_id="CALL-2", parent_call_id="CALL-1")
    assert child.parent_call_id == "CALL-1"
    assert ModelTraceContext(run_id="RUN-1", call_id="CALL-1").parent_call_id is None


# --- usage is reported, never invented ----------------------------------------------------


def test_usage_may_be_entirely_unknown() -> None:
    """A provider that cannot report tokens or cost must not have numbers invented for it."""
    unknown = ModelUsage()
    assert unknown.input_tokens is None
    assert unknown.output_tokens is None
    assert unknown.cost_usd is None
    assert unknown.wall_clock_ms is None


@pytest.mark.parametrize(
    "kwargs",
    [{"input_tokens": -1}, {"output_tokens": -1}, {"cost_usd": -0.01}, {"wall_clock_ms": -1}],
)
def test_usage_rejects_negative_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ModelUsage(**kwargs)  # type: ignore[arg-type]


def test_zero_is_a_legitimate_usage_value_and_is_not_confused_with_unknown() -> None:
    zero = ModelUsage(input_tokens=0, cost_usd=0.0)
    assert zero.input_tokens == 0
    assert zero.cost_usd == 0.0
    assert zero.output_tokens is None


# --- capabilities are open to additive extension --------------------------------------------


def test_capability_matching_is_generic_rather_than_enumerated() -> None:
    """A future capability must be usable without editing matching logic."""
    assert {c.value for c in ModelCapability} >= {
        "STRUCTURED_OUTPUT",
        "TEXT_GENERATION",
        "TOOL_USE",
        "VISION",
    }
    assert len(set(ModelCapability)) == len(ModelCapability)
