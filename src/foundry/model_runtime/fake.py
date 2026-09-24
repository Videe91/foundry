"""A strict deterministic provider double.

It lives in the production package because the repository already ships fake adapters
beside their ports, and because a double that drifts from the port it doubles is worse
than no double at all. It performs no I/O of any kind.

Strictness is the point: it records exactly what it was shown, returns exactly what was
scripted, and fails loudly when called more often than the script allows. A lenient fake
would let a test pass while the runtime called a provider twice, which is precisely the
behaviour MR1 forbids.
"""

from __future__ import annotations

from pydantic import BaseModel

from foundry.domain.common import FrozenModel
from foundry.model_runtime.domain import ModelIdentity, ModelRequest, ModelUsage
from foundry.model_runtime.ports import ProviderExecutionResult

__all__ = ["FakeModelProvider", "RecordedCall", "ScriptedResponse"]


class ScriptedResponse(FrozenModel):
    """One prepared answer.

    ``model`` is what this response claims to have run, so a test can reproduce a
    provider substituting a model without needing a real provider that misbehaves.
    ``output`` is deliberately untyped here: a test must be able to script the wrong
    type and prove the runtime refuses it.
    """

    model_config = FrozenModel.model_config | {"arbitrary_types_allowed": True}

    output: object
    model: str
    usage: ModelUsage = ModelUsage()
    finish_reason: str | None = None


class RecordedCall(FrozenModel):
    """Exactly what the runtime handed the adapter."""

    model_config = FrozenModel.model_config | {"arbitrary_types_allowed": True}

    model: ModelIdentity
    request: ModelRequest
    output_type: type


class FakeModelProvider:
    """Deterministic, no network, no memory beyond its own recording."""

    def __init__(
        self,
        *,
        provider_id: str,
        responses: tuple[ScriptedResponse, ...] = (),
        raises: Exception | None = None,
        reported_provider: str | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._responses = list(responses)
        self._raises = raises
        self._reported_provider = reported_provider or provider_id
        self.requests: list[RecordedCall] = []

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def calls(self) -> int:
        return len(self.requests)

    def execute[T: BaseModel](
        self, *, model: ModelIdentity, request: ModelRequest, output_type: type[T]
    ) -> ProviderExecutionResult[T]:
        self.requests.append(RecordedCall(model=model, request=request, output_type=output_type))
        if self._raises is not None:
            raise self._raises
        if not self._responses:
            raise AssertionError(
                f"fake provider {self._provider_id!r} was called more times than scripted"
            )
        scripted = self._responses.pop(0)
        # ``model_construct`` deliberately skips validation here. The fake's job is to
        # hand the runtime EXACTLY what was scripted, including output that does not
        # satisfy the caller's type — that is how a misbehaving provider is simulated.
        # Validating here would move the type boundary into the double and leave the
        # runtime's own enforcement, which is the thing MR1 must prove, untested.
        return ProviderExecutionResult[output_type].model_construct(  # type: ignore[valid-type]
            identity=ModelIdentity(provider=self._reported_provider, model=scripted.model),
            output=scripted.output,
            usage=scripted.usage,
            finish_reason=scripted.finish_reason,
        )
