"""Model selection: a deterministic seam, honestly labelled.

Given the same registry and request, selection is reproducible. That is a property of
MR1's policy — not a claim about model output, which is not deterministic in general, and
not a claim about durability, which lives entirely outside this package.

Deliberately absent: cost optimisation, quality ranking, fallback and retry. Foundry has
no certified pricing or benchmark data yet, and a "cheapest" rule invented without it
would be a guess wearing the costume of Law 4. What MR1 establishes is the seam those
policies will replace without any domain caller changing.
"""

from __future__ import annotations

from foundry.model_runtime.domain import ModelDescriptor, ModelRequest
from foundry.model_runtime.errors import ModelUnavailableError
from foundry.model_runtime.registry import ModelRegistry

__all__ = ["select_model"]


def select_model(registry: ModelRegistry, request: ModelRequest) -> ModelDescriptor:
    """The first eligible candidate in registry order.

    Pure: no provider call, no clock, no randomness. Zero candidates is a refusal rather
    than a relaxation — there is no widening of the request and no crossing of the tier
    boundary to find something that will do.
    """
    candidates = registry.eligible_models(request)
    if not candidates:
        required = sorted(c.value for c in request.required_capabilities)
        raise ModelUnavailableError(
            f"no registered model is certified for task {request.task.value} at tier "
            f"{request.tier.value} with capabilities {required}"
        )
    return candidates[0]
