"""``ModelRuntime`` — Foundry's universal socket to models.

One call in, one typed result out. The flow is deliberately short:

    validate request ↔ tier  →  route to a certified model  →  find its adapter
        →  execute once  →  verify the returned identity  →  return a typed result

What it does **not** do is as load-bearing as what it does. It never decides domain
meaning, never assigns authority, never touches a ledger, and never keeps anything from
one call to the next (Law 3): a runtime that remembered would quietly become the
project's memory, which is the exact failure the constitution forbids. It holds immutable
configuration and adapter instances, and nothing else.

Success here means the call completed and the transport, identity and output contracts
held. It does **not** mean the answer is correct — generation cannot certify itself
(Law 5), so nothing in the result reports verification. Whether any of this becomes
durable truth is the calling domain's decision, taken elsewhere.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from foundry.model_runtime.domain import (
    ModelExecutionResult,
    ModelRequest,
    ModelResultMetadata,
)
from foundry.model_runtime.errors import (
    ModelProtocolError,
    ModelProviderError,
    ModelProviderUnavailableError,
    ModelRequestError,
    ModelRuntimeError,
)
from foundry.model_runtime.ports import ModelProvider, ProviderExecutionResult
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.routing import select_model

__all__ = ["ModelRuntime"]


class ModelRuntime:
    """Executes one provider-neutral request against one certified model."""

    def __init__(
        self, *, registry: ModelRegistry, providers: tuple[ModelProvider, ...] = ()
    ) -> None:
        by_id: dict[str, ModelProvider] = {}
        for provider in providers:
            provider_id = provider.provider_id
            if provider_id in by_id:
                raise ModelRequestError(
                    f"duplicate provider adapter for {provider_id!r}; one provider id has "
                    "exactly one adapter"
                )
            by_id[provider_id] = provider
        self._registry = registry
        self._providers = by_id

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    def execute[T: BaseModel](
        self, request: ModelRequest, *, output_type: type[T]
    ) -> ModelExecutionResult[T]:
        """Route, execute once, and verify what came back.

        The caller owns ``output_type``. The runtime never defines domain output schemas
        and never unions them: it checks that what returned satisfies the type the caller
        asked for, and refuses anything else rather than repairing it.
        """
        descriptor = select_model(self._registry, request)
        identity = descriptor.identity

        provider = self._providers.get(identity.provider)
        if provider is None:
            raise ModelProviderUnavailableError(
                f"model {identity.provider}/{identity.model} is certified for task "
                f"{request.task.value} but no adapter for provider {identity.provider!r} is "
                "installed; a different, uncertified model is never substituted"
            )

        try:
            provided = provider.execute(model=identity, request=request, output_type=output_type)
        except ModelRuntimeError:
            # Already a runtime-level failure with its own meaning; do not re-wrap.
            raise
        except Exception as exc:  # noqa: BLE001 - any adapter failure is a provider error
            raise ModelProviderError(
                f"provider {identity.provider!r} failed executing "
                f"{identity.model!r} for task {request.task.value}"
            ) from exc

        return self._verify(
            provided, request=request, descriptor_identity=identity, output_type=output_type
        )

    def _verify[T: BaseModel](
        self,
        provided: ProviderExecutionResult[T],
        *,
        request: ModelRequest,
        descriptor_identity: object,
        output_type: type[T],
    ) -> ModelExecutionResult[T]:
        if provided.identity != descriptor_identity:
            raise ModelProtocolError(
                f"runtime selected {descriptor_identity} but the provider reported "
                f"{provided.identity}; a provider may not substitute a model, and MR1 "
                "resolves no aliases"
            )

        output = provided.output
        if not isinstance(output, output_type):
            try:
                output = output_type.model_validate(output)
            except ValidationError as exc:
                raise ModelProtocolError(
                    f"provider {provided.identity.provider!r} returned output that does not "
                    f"satisfy {output_type.__name__}; output is never repaired or coerced"
                ) from exc

        return ModelExecutionResult[output_type](  # type: ignore[valid-type]
            output=output,
            metadata=ModelResultMetadata(
                identity=provided.identity,
                task=request.task,
                tier=request.tier,
                trace=request.trace,
                usage=provided.usage,
                finish_reason=provided.finish_reason,
            ),
        )
