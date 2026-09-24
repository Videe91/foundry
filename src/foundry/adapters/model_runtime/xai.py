"""xAI provider adapter for the shared Model Runtime (MR2).

The first real provider behind Foundry's universal socket. It speaks xAI's protocol and
translates back into the neutral contract; nothing vendor-shaped travels upward and no
domain policy travels downward. The adapter carries no prompt, no schema and no task
meaning — the caller owns all three.

Transport laws preserved from Foundry's accepted xAI integrations:

* one Foundry call is one provider attempt — gRPC retries are disabled, so the transport
  cannot silently retry beneath a runtime that promises at most one call;
* every call is stateless (``store_messages=False``, no conversation id, no previous
  response id), because a provider that remembered would become project memory (Law 3);
* no tools, no search, no multi-agent — MR2 is a single bounded call, and tool use is a
  capability to be certified deliberately, not inherited because a vendor offers it;
* structured output through the SDK's own parse mechanism, never hand-repaired JSON;
* real telemetry only — an unreported value stays unknown rather than becoming zero.

**Identity is load-bearing.** The adapter reports what the provider says actually ran,
read from the response, never echoed back from the request. The runtime's certified
identity check is only meaningful if this value is genuinely the provider's.

Registration is not permission: nothing here certifies Grok for any task. That is a
task-specific evaluation decision recorded in a registry, elsewhere.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Final, Literal, Protocol

import grpc  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError
from xai_sdk import Client  # type: ignore[import-untyped]
from xai_sdk.chat import (  # type: ignore[import-untyped]
    assistant,
    cost_usd_from_usage,
    system,
    user,
)

from foundry.model_runtime.domain import (
    MessageRole,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelUsage,
)
from foundry.model_runtime.errors import ModelProtocolError, ModelRequestError
from foundry.model_runtime.ports import ProviderExecutionResult

__all__ = ["XAI_PROVIDER_ID", "ReasoningEffort", "XAIModelProvider"]

XAI_PROVIDER_ID: Final[str] = "xai"

type ReasoningEffort = Literal["low", "medium", "high", "xhigh"]

_MESSAGE_BUILDERS: Final[dict[MessageRole, Callable[[str], Any]]] = {
    MessageRole.SYSTEM: system,
    MessageRole.USER: user,
    MessageRole.ASSISTANT: assistant,
}
"""One builder per neutral role. A missing role is a structural gap, never a fallback."""


class _ClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


def _default_client_factory(**kwargs: Any) -> Any:
    return Client(**kwargs)


class XAIModelProvider:
    """Executes one bounded ``ModelRequest`` against one xAI model.

    Deliberately **not** pinned to a particular model: the registry decides which model
    is certified for a task and the adapter executes what it is handed. Hardcoding a
    model here would move a certification decision into transport code.

    The API key is construction state only. It never enters a request, a descriptor, a
    result or an error message, which is what keeps the future BYOK seam open.
    """

    def __init__(
        self,
        *,
        api_key: str,
        reasoning_effort: ReasoningEffort = "high",
        default_timeout_seconds: float | None = None,
        client_factory: _ClientFactory | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._api_key = api_key
        self._reasoning_effort: ReasoningEffort = reasoning_effort
        self._default_timeout_seconds = default_timeout_seconds
        self._client_factory: _ClientFactory = client_factory or _default_client_factory
        self._monotonic = monotonic

    def __repr__(self) -> str:
        """Never renders the credential."""
        return (
            f"XAIModelProvider(provider_id={XAI_PROVIDER_ID!r}, effort={self._reasoning_effort!r})"
        )

    @property
    def provider_id(self) -> str:
        return XAI_PROVIDER_ID

    def execute[T: BaseModel](
        self,
        *,
        model: ModelIdentity,
        request: ModelRequest,
        output_type: type[T],
    ) -> ProviderExecutionResult[T]:
        self._reject_unsupported(model, request)

        client = self._client_factory(
            api_key=self._api_key,
            timeout=self._timeout_for(request),
            # One Foundry call is one provider attempt. Without this the transport could
            # retry underneath a runtime that guarantees it will not.
            channel_options=[("grpc.enable_retries", 0)],
        )

        create_kwargs: dict[str, Any] = {
            "model": model.model,
            "messages": _as_provider_messages(request.messages),
            "reasoning_effort": self._reasoning_effort,
            # Law 3: no provider-side memory of any kind.
            "store_messages": False,
        }
        max_output_tokens = request.constraints.max_output_tokens
        if max_output_tokens is not None:
            create_kwargs["max_tokens"] = max_output_tokens
        # No tools, tool_choice, search_parameters, agent_count or include: a single
        # bounded call, with tool use left to a later deliberate certification.

        started = self._monotonic()
        chat = client.chat.create(**create_kwargs)
        try:
            response, parsed = chat.parse(output_type)
        except grpc.RpcError:
            # The call never produced an answer. That is a transport fault, and it is
            # deliberately NOT converted here: the runtime maps it to ModelProviderError.
            # Reporting it as an output-contract failure would send an operator looking
            # for a schema bug when the network was the problem — observed in practice
            # during MR2's first live run.
            raise
        except Exception as exc:
            # The provider answered, but not in a shape that satisfies the caller's
            # contract. That is a protocol failure, not a transport one, and it is never
            # repaired, coerced or re-asked.
            raise ModelProtocolError(
                f"xAI returned output that could not be parsed as {output_type.__name__}"
            ) from exc
        elapsed_ms = int((self._monotonic() - started) * 1000)

        try:
            return ProviderExecutionResult[output_type](  # type: ignore[valid-type]
                identity=ModelIdentity(provider=XAI_PROVIDER_ID, model=_executed_model(response)),
                output=parsed,
                usage=_as_usage(response, elapsed_ms),
                finish_reason=_finish_reason(response),
            )
        except ValidationError as exc:
            # The SDK returned an object that does not satisfy the caller's type. That is
            # an output-contract failure at the provider boundary, not a transport fault,
            # and conflating the two would send an operator looking for a network problem.
            raise ModelProtocolError(
                f"xAI returned a result that does not satisfy {output_type.__name__}"
            ) from exc

    def _reject_unsupported(self, model: ModelIdentity, request: ModelRequest) -> None:
        """Everything refusable without a network call is refused here.

        A constraint that cannot be honoured is refused rather than dropped: silently
        ignoring a caller's stated bound is the failure mode worth preventing, because
        the caller would believe a limit applied that never did.
        """
        if model.provider != XAI_PROVIDER_ID:
            raise ModelRequestError(
                f"the xai adapter cannot execute provider {model.provider!r}; it never "
                "runs another provider's identity"
            )
        if request.constraints.max_cost_usd is not None:
            raise ModelRequestError(
                "max_cost_usd cannot be enforced by the xai adapter in MR2: there is no "
                "trusted pre-call cost engine, and the budget is refused rather than "
                "pretended. Cost-aware routing will honour it later."
            )

    def _timeout_for(self, request: ModelRequest) -> float | None:
        """The request's timeout wins; the adapter default applies only when it has none.

        xAI's timeout is client-level, so a client is built per call rather than reused,
        which is what lets a per-request timeout actually take effect instead of being
        silently widened to a shared one.
        """
        requested = request.constraints.timeout_seconds
        return requested if requested is not None else self._default_timeout_seconds


def _as_provider_messages(messages: Sequence[ModelMessage]) -> list[Any]:
    """Same order, same role, same content. No augmentation of any kind."""
    built: list[Any] = []
    for message in messages:
        builder = _MESSAGE_BUILDERS.get(message.role)
        if builder is None:
            raise ModelRequestError(f"no xAI message builder for role {message.role.value}")
        built.append(builder(message.content))
    return built


def _executed_model(response: Any) -> str:
    """What the provider says actually ran — read from the response, never the request.

    Echoing the requested model would make the runtime's identity check vacuous: a
    substitution would agree with itself. An empty or absent value is refused for the
    same reason, since silence is not permission to assume the request was honoured.
    """
    executed = getattr(getattr(response, "proto", None), "model", "")
    if not executed:
        raise ModelProtocolError(
            "the xAI response reported no executed model identity; the runtime's identity "
            "check cannot be satisfied by assuming the requested model ran"
        )
    return str(executed)


def _as_usage(response: Any, elapsed_ms: int) -> ModelUsage:
    """Normalize real telemetry. Unreported stays ``None`` — never zero.

    A provider that could not report cost did not make a free call, and recording it as
    free would corrupt every budget built on top of it later.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return ModelUsage(wall_clock_ms=elapsed_ms)
    return ModelUsage(
        input_tokens=_optional_field(usage, "prompt_tokens"),
        output_tokens=_optional_field(usage, "completion_tokens"),
        cost_usd=cost_usd_from_usage(usage),
        wall_clock_ms=elapsed_ms,
    )


def _optional_field(usage: Any, name: str) -> int | None:
    """Read a token count without inventing one.

    Two cases, because the wire format distinguishes them and Foundry must too.

    Where the field has explicit proto presence, ``HasField`` answers truthfully and is
    used. ``prompt_tokens`` and ``completion_tokens`` do **not** have presence in
    ``SamplingUsage``: they are plain proto3 scalars that default to ``0``, so a server
    that reported nothing is indistinguishable on the wire from one that reported zero.

    For those, ``0`` is read as unreported. A successful completion never consumes zero
    prompt tokens, so treating the default as a real measurement would inject false
    zeros into every budget built on this metadata — precisely the invented telemetry the
    runtime contract forbids. Declining to assert a number the protocol cannot confirm is
    the honest option; ``cost_usd`` keeps full fidelity because its field does carry
    presence, so a genuine zero cost survives.
    """
    value = getattr(usage, name, None)
    if value is None:
        return None
    has_field = getattr(usage, "HasField", None)
    if callable(has_field):
        try:
            return int(value) if has_field(name) else None
        except ValueError:
            # No explicit presence for this field; fall through to the default rule.
            pass
    return int(value) or None


def _finish_reason(response: Any) -> str | None:
    """Preserved when reported, ``None`` when genuinely absent. Never invented."""
    try:
        reason = response.finish_reason
    except Exception:
        return None
    return str(reason) if reason else None
