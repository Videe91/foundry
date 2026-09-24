"""MR1 — the registry, and the law that certification is task-specific.

Registration is not permission. A model appears in the registry because Foundry has
certified it for particular tiers, particular tasks and particular capabilities; being
able to generate text says nothing about being allowed to do architecture. Eligibility
is therefore a conjunction, and every clause of it is load-bearing.
"""

from __future__ import annotations

import pytest

from foundry.model_runtime.domain import ModelCapability, ModelTask, ModelTier
from foundry.model_runtime.errors import ModelRequestError
from foundry.model_runtime.registry import ModelRegistry
from tests.unit.model_runtime._fixtures import descriptor, identity, request

ALL_REASONING = frozenset({ModelTask.INTENT_SYNTHESIS, ModelTask.ARCHITECTURE})


# --- construction is immutable and deterministic ----------------------------------------------


def test_a_registry_is_built_from_a_fixed_iterable() -> None:
    registry = ModelRegistry(descriptors=(descriptor(), descriptor("provider-b", "model-2")))
    assert len(registry.descriptors) == 2


def test_duplicate_provider_model_identity_is_a_structural_error() -> None:
    with pytest.raises(ModelRequestError, match="duplicate"):
        ModelRegistry(descriptors=(descriptor(), descriptor()))


def test_lookup_finds_a_registered_model_and_misses_cleanly() -> None:
    registry = ModelRegistry(descriptors=(descriptor(),))
    assert registry.get(identity()) == descriptor()
    assert registry.get(identity("provider-z", "model-9")) is None


def test_registry_ordering_is_deterministic_regardless_of_input_order() -> None:
    """Lexical by (provider, model). Deterministic, and explicitly NOT a quality ranking."""
    a = descriptor("provider-a", "model-1")
    b = descriptor("provider-a", "model-2")
    c = descriptor("provider-b", "model-1")
    forward = ModelRegistry(descriptors=(a, b, c))
    shuffled = ModelRegistry(descriptors=(c, a, b))
    order = [(d.identity.provider, d.identity.model) for d in forward.descriptors]
    assert order == [
        ("provider-a", "model-1"),
        ("provider-a", "model-2"),
        ("provider-b", "model-1"),
    ]
    assert [d.identity for d in shuffled.descriptors] == [d.identity for d in forward.descriptors]


# --- eligibility is a conjunction -------------------------------------------------------------


def test_a_fully_certified_model_is_eligible() -> None:
    registry = ModelRegistry(descriptors=(descriptor(),))
    assert registry.eligible_models(request()) == (descriptor(),)


def test_a_model_not_certified_for_the_requested_tier_is_ineligible() -> None:
    """A WORKER-only model may not do architecture, however capable it is."""
    worker_only = descriptor(
        tiers=frozenset({ModelTier.WORKER}),
        certified_tasks=frozenset({ModelTask.ARCHITECTURE, ModelTask.CODING}),
    )
    registry = ModelRegistry(descriptors=(worker_only,))
    assert registry.eligible_models(request(task=ModelTask.ARCHITECTURE)) == ()


def test_a_model_not_certified_for_the_requested_task_is_ineligible() -> None:
    """Supporting the tier is not enough; the exact task must be certified."""
    reasoner = descriptor(certified_tasks=frozenset({ModelTask.PLANNING}))
    registry = ModelRegistry(descriptors=(reasoner,))
    assert registry.eligible_models(request(task=ModelTask.INTENT_SYNTHESIS)) == ()


def test_a_model_missing_a_required_capability_is_ineligible() -> None:
    no_structured = descriptor(capabilities=frozenset({ModelCapability.TEXT_GENERATION}))
    registry = ModelRegistry(descriptors=(no_structured,))
    assert (
        registry.eligible_models(
            request(required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}))
        )
        == ()
    )


def test_extra_capabilities_never_disqualify_a_model() -> None:
    generous = descriptor(
        capabilities=frozenset(
            {
                ModelCapability.TEXT_GENERATION,
                ModelCapability.STRUCTURED_OUTPUT,
                ModelCapability.TOOL_USE,
                ModelCapability.VISION,
            }
        )
    )
    registry = ModelRegistry(descriptors=(generous,))
    assert registry.eligible_models(request()) == (generous,)


def test_a_request_requiring_no_capabilities_matches_on_tier_and_task_alone() -> None:
    registry = ModelRegistry(descriptors=(descriptor(),))
    assert registry.eligible_models(request(required_capabilities=frozenset())) == (descriptor(),)


def test_eligible_models_are_returned_in_registry_order() -> None:
    a = descriptor("provider-a", "model-1", certified_tasks=ALL_REASONING)
    b = descriptor("provider-b", "model-2", certified_tasks=ALL_REASONING)
    registry = ModelRegistry(descriptors=(b, a))
    eligible = registry.eligible_models(request())
    assert [d.identity.provider for d in eligible] == ["provider-a", "provider-b"]


# --- one model may hold two certified roles ---------------------------------------------------


def test_a_model_certified_for_both_roles_may_execute_both() -> None:
    """Role belongs to certification and task, never to the model's brand."""
    dual = descriptor(
        tiers=frozenset({ModelTier.WORKER, ModelTier.REASONER}),
        certified_tasks=frozenset({ModelTask.CODING, ModelTask.ARCHITECTURE}),
    )
    registry = ModelRegistry(descriptors=(dual,))

    assert registry.eligible_models(
        request(task=ModelTask.ARCHITECTURE, tier=ModelTier.REASONER)
    ) == (dual,)
    assert registry.eligible_models(request(task=ModelTask.CODING, tier=ModelTier.WORKER)) == (
        dual,
    )


def test_a_dual_role_model_is_still_bound_by_its_certified_task_list() -> None:
    dual = descriptor(
        tiers=frozenset({ModelTier.WORKER, ModelTier.REASONER}),
        certified_tasks=frozenset({ModelTask.CODING}),
    )
    registry = ModelRegistry(descriptors=(dual,))
    assert registry.eligible_models(request(task=ModelTask.ARCHITECTURE)) == ()
