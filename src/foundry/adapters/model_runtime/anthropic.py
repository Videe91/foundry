"""Anthropic provider adapter for the shared Model Runtime.

The third real provider behind Foundry's universal socket. It speaks Anthropic's Messages API
through the official ``anthropic`` SDK and translates back into the neutral contract; nothing
vendor-shaped travels upward and no domain policy travels downward. The adapter carries no
prompt and no task meaning; the caller owns both, and the answer schema is the caller's type,
represented on the wire by ``anthropic_wire_schema``.

Transport laws, each load-bearing:

* **One Foundry call is one provider attempt.** The SDK retries connection errors, 408, 409,
  429 and 5xx twice by default, so ``max_retries=0``.
* **Stateless.** The full bounded request is sent every time; nothing is carried between calls.
* **No hidden prompt.** Leading system messages become the ``system`` parameter in order, and
  every other message is sent unchanged in role and order. A system message after the
  conversation has begun is refused rather than moved, because not every model accepts one.
* **Streaming**, collected with ``get_final_message()``, so a large output guard (thinking
  counts toward it) cannot hit an HTTP timeout. It is the same single call either way.
* **Structured output** through ``output_config.format`` with the wire schema, and the answer
  validated by the caller's own Pydantic type. Nothing is repaired, coerced or re-asked. The
  graph answer (``IntentGraphDraftPayload``) travels in its compact representation
  (``anthropic_graph_wire``), because Anthropic refuses the grammar of the compiled canonical
  graph schema as too large: the reply is converted mechanically to canonical form and then
  validated as ``IntentGraphDraftPayload`` exactly as any provider's answer is. Every other type
  uses ``compile_anthropic_wire_schema``.
* **Reasoning** is ``output_config.effort`` (adapter state, like OpenAI's reasoning effort).
  ``thinking`` is omitted, which on current Claude models means adaptive thinking; several of
  them reject any explicit disabled or budgeted setting.
* **No server-side fallbacks.** A fallback would let a different model answer under a
  certified identity. The runtime refuses substitutions anyway; the adapter never invites one.
* **Real telemetry only.** Anthropic reports token counts (thinking included in output) but no
  cost, so ``cost_usd`` stays unknown rather than estimated from list prices.

Failure distinctions:

* ``anthropic.APIError`` (connection, timeout, rate limit, overload, authentication, bad
  request, any status) means no answer was produced. It propagates unconverted, and the runtime
  reports it as a provider error. It is never a semantic failure of the model.
* ``stop_reason == "refusal"`` is a refusal, not an answer; its text is never interpolated.
* ``stop_reason == "max_tokens"`` means our own output bound was reached (the message says
  ``max_output_tokens``, which certification classifies as a harness limit, never a verdict).
* Any other non-``end_turn`` stop, a missing or extra text block, or text that fails the
  caller's type is a protocol failure.

Registration is not permission: nothing here certifies any Anthropic model for any task.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from typing import Any, Final, Literal, Protocol

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from foundry.adapters.intent_graph_synthesis.model_runtime import IntentGraphDraftPayload
from foundry.adapters.model_runtime.anthropic_graph_wire import (
    GraphWireShapeError,
    anthropic_graph_wire_schema,
    parse_graph_wire,
)
from foundry.adapters.model_runtime.anthropic_wire_schema import (
    ANTHROPIC_WIRE_SCHEMA_COMPILER,
    compile_anthropic_wire_schema,
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

__all__ = [
    "ANTHROPIC_PROVIDER_ID",
    "AnthropicEffort",
    "AnthropicModelProvider",
]

ANTHROPIC_PROVIDER_ID: Final[str] = "anthropic"

type AnthropicEffort = Literal["low", "medium", "high", "xhigh", "max"]

_DEFAULT_MAX_TOKENS: Final[int] = 16000
"""Used only when a request states no output bound; Anthropic requires one on every call."""

_ROLE_NAMES: Final[dict[MessageRole, str]] = {
    MessageRole.USER: "user",
    MessageRole.ASSISTANT: "assistant",
}


class _ClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


def _default_client_factory(**kwargs: Any) -> Any:
    return Anthropic(**kwargs)


class AnthropicModelProvider:
    """Executes one bounded ``ModelRequest`` against one Anthropic model.

    Not pinned to a model: the registry decides which model is certified for a task and the
    adapter executes what it is handed. The API key is construction state only; it never
    enters a request, a descriptor, a result, a repr or an error message.
    """

    WIRE_SCHEMA_COMPILER: Final[str] = ANTHROPIC_WIRE_SCHEMA_COMPILER
    """What turns a canonical answer schema into what this adapter transmits."""

    def __init__(
        self,
        *,
        api_key: str,
        effort: AnthropicEffort = "high",
        default_timeout_seconds: float | None = None,
        client_factory: _ClientFactory | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._api_key = api_key
        self._effort: AnthropicEffort = effort
        self._default_timeout_seconds = default_timeout_seconds
        self._client_factory: _ClientFactory = client_factory or _default_client_factory
        self._monotonic = monotonic
        self._client: Any | None = None

    def __repr__(self) -> str:
        """Never renders the credential."""
        return (
            f"AnthropicModelProvider(provider_id={ANTHROPIC_PROVIDER_ID!r}, "
            f"effort={self._effort!r})"
        )

    @staticmethod
    def wire_schema(output_type: type[BaseModel]) -> dict[str, Any]:
        """The exact structured-output schema ``execute`` sends for ``output_type``."""
        if output_type is IntentGraphDraftPayload:
            return anthropic_graph_wire_schema()
        return compile_anthropic_wire_schema(output_type.model_json_schema())

    @property
    def provider_id(self) -> str:
        return ANTHROPIC_PROVIDER_ID

    def execute[T: BaseModel](
        self,
        *,
        model: ModelIdentity,
        request: ModelRequest,
        output_type: type[T],
    ) -> ProviderExecutionResult[T]:
        self._reject_unsupported(model, request)
        system, messages = _as_provider_messages(request.messages)
        max_tokens = request.constraints.max_output_tokens or _DEFAULT_MAX_TOKENS

        params: dict[str, Any] = {
            "model": model.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "output_config": {
                "format": {"type": "json_schema", "schema": self.wire_schema(output_type)},
                "effort": self._effort,
            },
        }
        if system:
            params["system"] = system
        timeout = self._timeout_for(request)
        if timeout is not None:
            params["timeout"] = timeout

        started = self._monotonic()
        # anthropic.APIError propagates unconverted: no answer exists, and the runtime reports it
        # as a provider error, never as a failure of the model's answer.
        with self._messages().stream(**params) as stream:
            response = stream.get_final_message()
        elapsed_ms = int((self._monotonic() - started) * 1000)

        parsed = _parse_answer(_require_answer_text(response, max_tokens), output_type)

        return ProviderExecutionResult[output_type](  # type: ignore[valid-type]
            identity=ModelIdentity(provider=ANTHROPIC_PROVIDER_ID, model=_executed_model(response)),
            output=parsed,
            usage=_as_usage(response, elapsed_ms),
            finish_reason=str(response.stop_reason),
        )

    def _messages(self) -> Any:
        """One client per provider, built on first use and reused. The credential goes here only."""
        if self._client is None:
            self._client = self._client_factory(api_key=self._api_key, max_retries=0)
        return self._client.messages

    def _reject_unsupported(self, model: ModelIdentity, request: ModelRequest) -> None:
        """Everything refusable without a network call is refused here."""
        if model.provider != ANTHROPIC_PROVIDER_ID:
            raise ModelRequestError(
                f"the anthropic adapter cannot execute provider {model.provider!r}; it never "
                "runs another provider's identity"
            )
        if request.constraints.max_cost_usd is not None:
            raise ModelRequestError(
                "max_cost_usd cannot be enforced by the anthropic adapter: there is no trusted "
                "pre-call cost engine, and the budget is refused rather than pretended"
            )

    def _timeout_for(self, request: ModelRequest) -> float | None:
        """The request's timeout wins; the adapter default applies only when it has none."""
        requested = request.constraints.timeout_seconds
        return requested if requested is not None else self._default_timeout_seconds


def _as_provider_messages(
    messages: Sequence[ModelMessage],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Leading system messages become ``system`` blocks; the rest are sent unchanged."""
    system: list[dict[str, str]] = []
    conversation: list[dict[str, str]] = []
    for message in messages:
        if message.role is MessageRole.SYSTEM:
            if conversation:
                raise ModelRequestError(
                    "a system message after the conversation has begun cannot be sent to "
                    "every Anthropic model; it is refused rather than moved"
                )
            system.append({"type": "text", "text": message.content})
            continue
        role = _ROLE_NAMES.get(message.role)
        if role is None:
            raise ModelRequestError(f"no Anthropic role mapping for role {message.role.value}")
        conversation.append({"role": role, "content": message.content})
    if not conversation:
        raise ModelRequestError("an Anthropic request needs at least one non-system message")
    return system, conversation


def _require_answer_text(response: Any, max_tokens: int) -> str:
    """The single text block that carries the structured answer, or a named failure."""
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        raise ModelProtocolError(
            f"Anthropic returned a refusal (category: {category}) instead of the requested "
            "structured output; a refusal is never treated as a typed success"
        )
    if stop_reason == "max_tokens":
        raise ModelProtocolError(
            f"Anthropic stopped at max_tokens={max_tokens} (the request's max_output_tokens "
            "bound); partial structured output is never accepted"
        )
    if stop_reason != "end_turn":
        raise ModelProtocolError(
            f"Anthropic stopped with {stop_reason!r} rather than 'end_turn'; anything else "
            "fails closed"
        )
    texts = [
        block.text
        for block in getattr(response, "content", []) or []
        if getattr(block, "type", None) == "text"
    ]
    if len(texts) != 1:
        raise ModelProtocolError(
            f"Anthropic returned {len(texts)} text blocks where exactly one structured answer "
            "was required; output is never merged, repaired or re-requested"
        )
    return str(texts[0])


def _parse_answer[T: BaseModel](text: str, output_type: type[T]) -> T:
    """The caller's type, validated canonically. A compact graph answer is converted first."""
    failure = f"Anthropic returned output that could not be parsed as {output_type.__name__}"
    if output_type is IntentGraphDraftPayload:
        try:
            text = json.dumps(parse_graph_wire(text))
        except GraphWireShapeError as exc:
            raise ModelProtocolError(
                f"{failure}: it is not an instance of the wire schema"
            ) from exc
        failure += ": its canonical form violates the Foundry graph contract"
    try:
        return output_type.model_validate_json(text)
    except ValidationError as exc:
        raise ModelProtocolError(failure) from exc


def _executed_model(response: Any) -> str:
    """What the provider says actually ran, read from the response, never the request."""
    executed = getattr(response, "model", "")
    if not executed:
        raise ModelProtocolError(
            "the Anthropic response reported no executed model identity; the runtime's "
            "identity check cannot be satisfied by assuming the requested model ran"
        )
    return str(executed)


def _as_usage(response: Any, elapsed_ms: int) -> ModelUsage:
    """Normalize real telemetry. Unreported stays ``None``; cost is never estimated."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return ModelUsage(wall_clock_ms=elapsed_ms)

    def count(name: str) -> int | None:
        value = getattr(usage, name, None)
        return None if value is None else int(value)

    return ModelUsage(
        input_tokens=count("input_tokens"),
        output_tokens=count("output_tokens"),
        cost_usd=None,
        wall_clock_ms=elapsed_ms,
    )
