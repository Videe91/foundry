"""MR1 — routing: a deterministic seam, honestly labelled.

Selection is deterministic given the same registry and request. That is a property of
MR1's policy, not a claim about model output, and the ordering is lexical because it is
reproducible — not because it is best. Cost- and quality-aware policy replaces this seam
later without touching a single domain caller.
"""

from __future__ import annotations

import pytest

from foundry.model_runtime.domain import ModelTask, ModelTier
from foundry.model_runtime.errors import ModelUnavailableError
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.routing import select_model
from tests.unit.model_runtime._fixtures import descriptor, request

BOTH = frozenset({ModelTask.INTENT_SYNTHESIS, ModelTask.ARCHITECTURE})


def test_a_single_eligible_candidate_is_selected() -> None:
    registry = ModelRegistry(descriptors=(descriptor(),))
    assert select_model(registry, request()) == descriptor()


def test_the_first_eligible_candidate_wins_deterministically() -> None:
    a = descriptor("provider-a", "model-1", certified_tasks=BOTH)
    b = descriptor("provider-b", "model-2", certified_tasks=BOTH)
    registry = ModelRegistry(descriptors=(b, a))
    assert select_model(registry, request()).identity.provider == "provider-a"


def test_selection_is_stable_across_repeated_calls() -> None:
    registry = ModelRegistry(
        descriptors=(
            descriptor("provider-b", "model-2", certified_tasks=BOTH),
            descriptor("provider-a", "model-1", certified_tasks=BOTH),
            descriptor("provider-a", "model-2", certified_tasks=BOTH),
        )
    )
    chosen = {select_model(registry, request()).identity for _ in range(20)}
    assert len(chosen) == 1


def test_no_eligible_candidate_raises_rather_than_falling_back() -> None:
    registry = ModelRegistry(
        descriptors=(descriptor(certified_tasks=frozenset({ModelTask.PLANNING})),)
    )
    with pytest.raises(ModelUnavailableError) as excinfo:
        select_model(registry, request(task=ModelTask.INTENT_SYNTHESIS))
    message = str(excinfo.value)
    assert "INTENT_SYNTHESIS" in message
    assert "REASONER" in message


def test_an_empty_registry_raises_unavailable() -> None:
    with pytest.raises(ModelUnavailableError):
        select_model(ModelRegistry(descriptors=()), request())


def test_routing_never_crosses_the_tier_boundary_to_find_a_candidate() -> None:
    """A WORKER-certified model is not quietly used to satisfy a REASONER request."""
    worker = descriptor(
        tiers=frozenset({ModelTier.WORKER}), certified_tasks=frozenset({ModelTask.CODING})
    )
    registry = ModelRegistry(descriptors=(worker,))
    with pytest.raises(ModelUnavailableError):
        select_model(registry, request(task=ModelTask.ARCHITECTURE, tier=ModelTier.REASONER))
