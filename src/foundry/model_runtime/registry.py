"""The certified-model registry.

Built once from a fixed iterable and never mutated. There is no global registration hook
on purpose: a hidden mutable singleton would make eligibility depend on import order, and
"which models may do this work" is a governance fact that should be as reproducible as
the routing built on top of it.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import field_validator

from foundry.domain.common import FrozenModel
from foundry.model_runtime.domain import (
    CertifiedContract,
    ModelDescriptor,
    ModelIdentity,
    ModelRequest,
)
from foundry.model_runtime.errors import ModelRequestError

__all__ = ["ModelRegistry", "certified_contract"]


def _sort_key(descriptor: ModelDescriptor) -> tuple[str, str]:
    return (descriptor.identity.provider, descriptor.identity.model)


class ModelRegistry(FrozenModel):
    """Immutable set of certified models, held in deterministic order.

    Ordering is lexical by ``(provider, model)``. That is a reproducibility choice, not a
    quality ranking — MR1 has no certified pricing or benchmark data with which to claim
    one model is better, and pretending otherwise would bake a false preference into the
    seam that later policy has to replace.
    """

    descriptors: tuple[ModelDescriptor, ...] = ()

    @field_validator("descriptors", mode="after")
    @classmethod
    def reject_duplicates_and_order(
        cls, value: tuple[ModelDescriptor, ...]
    ) -> tuple[ModelDescriptor, ...]:
        seen: set[tuple[str, str]] = set()
        for descriptor in value:
            key = _sort_key(descriptor)
            if key in seen:
                raise ModelRequestError(
                    f"duplicate model identity {key[0]}/{key[1]} in registry; one "
                    "(provider, model) pair has exactly one certification"
                )
            seen.add(key)
        return tuple(sorted(value, key=_sort_key))

    def get(self, identity: ModelIdentity) -> ModelDescriptor | None:
        return next((d for d in self.descriptors if d.identity == identity), None)

    def eligible_models(self, request: ModelRequest) -> tuple[ModelDescriptor, ...]:
        """Every model certified for this exact tier, task and capability set.

        All three clauses are required together. A model that supports the tier but was
        never certified for the task is not eligible, and neither is one certified for
        the task that lacks a capability the caller declared it needs — being able to
        generate text says nothing about being authorised to do architecture. A request that
        names a contract is served only by a model certified for exactly that contract.
        """
        return tuple(
            descriptor
            for descriptor in self.descriptors
            if request.tier in descriptor.tiers
            and request.task in descriptor.certified_tasks
            and request.required_capabilities <= descriptor.capabilities
            and (request.contract is None or certified_contract(descriptor, request) is not None)
        )


def certified_contract(
    descriptor: ModelDescriptor, request: ModelRequest
) -> CertifiedContract | None:
    """The certification under which ``descriptor`` may serve ``request``'s exact contract."""
    return next(
        (
            c
            for c in sorted(descriptor.certified_contracts, key=lambda c: c.model_dump_json())
            if c.task is request.task and c.contract == request.contract
        ),
        None,
    )


def build_registry(descriptors: Iterable[ModelDescriptor]) -> ModelRegistry:
    return ModelRegistry(descriptors=tuple(descriptors))
