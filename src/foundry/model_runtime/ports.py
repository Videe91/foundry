"""The provider-neutral port every model adapter implements.

This file imports no SDK, no transport and no vendor type, which is what makes the rest
of Foundry substitutable at the adapter boundary rather than at the call site. An adapter
turns this contract into whatever its provider actually speaks, and turns the response
back into the caller's own output type; nothing provider-shaped travels upward.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from foundry.domain.common import FrozenModel
from foundry.model_runtime.domain import ModelIdentity, ModelRequest, ModelUsage

__all__ = ["ModelProvider", "ProviderExecutionResult"]


class ProviderExecutionResult[T: BaseModel](FrozenModel):
    """What an adapter returns.

    ``identity`` is what the provider says it actually ran, which the runtime checks
    against what it selected. Reporting it is the adapter's obligation: a provider that
    quietly served a different model would otherwise be indistinguishable from one that
    honoured the request.
    """

    identity: ModelIdentity
    output: T
    usage: ModelUsage = ModelUsage()
    finish_reason: str | None = None


@runtime_checkable
class ModelProvider(Protocol):
    """A single-call executor for one provider.

    Adapters may hold transport clients and credentials supplied out of band; they must
    not hold project state. Every call receives its complete bounded request.
    """

    @property
    def provider_id(self) -> str: ...

    def execute[T: BaseModel](
        self,
        *,
        model: ModelIdentity,
        request: ModelRequest,
        output_type: type[T],
    ) -> ProviderExecutionResult[T]: ...
