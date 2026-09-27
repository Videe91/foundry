"""OpenAI provider adapter for the shared Model Runtime (MR5).

The second real provider behind Foundry's universal socket. It speaks OpenAI's Responses
protocol and translates back into the neutral contract; nothing vendor-shaped travels
upward and no domain policy travels downward. The adapter carries no prompt, no schema and
no task meaning — the caller owns all three.

Transport laws, each of which is load-bearing rather than decorative:

* one Foundry call is one provider attempt — the installed SDK retries connection errors,
  timeouts, 408/409/429 and 5xx **twice by default**, so ``max_retries=0`` is what makes
  the runtime's one-attempt promise true rather than aspirational;
* every call is stateless — the Responses API *stores by default*, so ``store=False`` is
  sent explicitly, with no ``previous_response_id``, no ``conversation`` and no replayed
  prior items. A provider that remembered would become project memory (Law 3);
* reasoning is bounded to ``context="current_turn"``, so prior-turn reasoning cannot leak
  into a call that claims to be self-contained;
* no tools, no agents, no background execution, no streaming — MR5 is a single bounded
  call, and tool use is a capability to be certified deliberately, not inherited because a
  vendor offers it;
* structured output constrained by a Foundry-compiled wire schema
  (``openai_wire_schema``), and the answer validated by the caller's own Pydantic type exactly
  as the SDK's ``parse`` would validate it: never repaired, coerced or re-asked;
* real telemetry only — an unreported value stays unknown rather than becoming zero.

**Identity is load-bearing.** The adapter reports what the provider says actually ran, read
from ``response.model``, never echoed back from the request. The runtime's certified
identity check is only meaningful if this value is genuinely the provider's; echoing the
request would make a substitution agree with itself.

Two failure distinctions are deliberate, both learned the expensive way:

*Transport is not protocol.* An ``openai.APIError`` (connection, timeout, status) means the
call never produced an answer, and it propagates unconverted so the runtime reports it as
``ModelProviderError``. Reporting a network fault as an output-contract failure sends an
operator hunting a schema bug — exactly the misdiagnosis MR2 hit live.

*A refusal is not an empty answer.* The SDK's ``output_parsed`` walks straight past refusal
content and returns ``None``, making "the model declined" indistinguishable from "the model
returned nothing parseable". The adapter separates them, because they have different fixes.

Registration is not permission: nothing here certifies any OpenAI model for any task. MR5
proves transport and protocol only. Certifying GPT-6 Astra for Intent Synthesis is MR6, run
through the exact exam already used for Grok.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Final, Literal, Protocol

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from foundry.adapters.model_runtime.openai_wire_schema import (
    OPENAI_WIRE_SCHEMA_COMPILER,
    compile_openai_wire_schema,
    openai_text_format,
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
    "OPENAI_PROVIDER_ID",
    "OpenAIModelProvider",
    "OpenAIReasoningEffort",
    "OpenAIReasoningMode",
]

OPENAI_PROVIDER_ID: Final[str] = "openai"

type OpenAIReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
"""Model-dependent. GPT-6 Astra does not support ``none``; the registry decides the model,
and an unsupported pairing is the provider's refusal to make, not this adapter's to guess."""

type OpenAIReasoningMode = Literal["standard", "pro"]

_ROLE_NAMES: Final[dict[MessageRole, str]] = {
    MessageRole.SYSTEM: "system",
    MessageRole.USER: "user",
    MessageRole.ASSISTANT: "assistant",
}
"""One name per neutral role. A missing role is a structural gap, never a fallback."""

_COMPLETED: Final[str] = "completed"


class _ClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


def _default_client_factory(**kwargs: Any) -> Any:
    return OpenAI(**kwargs)


class OpenAIModelProvider:
    """Executes one bounded ``ModelRequest`` against one OpenAI model.

    Deliberately **not** pinned to a particular model: the registry decides which model is
    certified for a task and the adapter executes what it is handed. Hardcoding Astra here
    would move a certification decision into transport code.

    The API key is construction state only. It never enters a request, a descriptor, a
    result, a repr or an error message, which is what keeps the future BYOK seam open.

    Unlike the xAI adapter, one client is built per provider rather than per call. That
    difference is not cosmetic: xAI's timeout is client-scoped, so a per-call client is the
    only way a per-request timeout can take effect there. The Responses API accepts an
    exact per-request ``timeout``, so the requested bound reaches the transport directly
    and a shared client cannot silently widen it.
    """

    def __init__(
        self,
        *,
        api_key: str,
        reasoning_effort: OpenAIReasoningEffort = "high",
        reasoning_mode: OpenAIReasoningMode = "standard",
        default_timeout_seconds: float | None = None,
        client_factory: _ClientFactory | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._api_key = api_key
        self._reasoning_effort: OpenAIReasoningEffort = reasoning_effort
        self._reasoning_mode: OpenAIReasoningMode = reasoning_mode
        self._default_timeout_seconds = default_timeout_seconds
        self._client_factory: _ClientFactory = client_factory or _default_client_factory
        self._monotonic = monotonic
        self._client: Any | None = None

    def __repr__(self) -> str:
        """Never renders the credential."""
        return (
            f"OpenAIModelProvider(provider_id={OPENAI_PROVIDER_ID!r}, "
            f"effort={self._reasoning_effort!r}, mode={self._reasoning_mode!r})"
        )

    WIRE_SCHEMA_COMPILER: Final[str] = OPENAI_WIRE_SCHEMA_COMPILER
    """What turns a canonical answer schema into what this adapter transmits."""

    @staticmethod
    def wire_schema(output_type: type[BaseModel]) -> dict[str, Any]:
        """The exact structured-output schema ``execute`` sends for ``output_type``."""
        return compile_openai_wire_schema(output_type.model_json_schema())

    @property
    def provider_id(self) -> str:
        return OPENAI_PROVIDER_ID

    def execute[T: BaseModel](
        self,
        *,
        model: ModelIdentity,
        request: ModelRequest,
        output_type: type[T],
    ) -> ProviderExecutionResult[T]:
        self._reject_unsupported(model, request)

        parse_kwargs: dict[str, Any] = {
            "model": model.model,
            "input": _as_provider_input(request.messages),
            # The compiled wire schema, not ``text_format``: the SDK refuses both at once, and
            # its own derivation cannot express a proven union rewrite. For a schema with no
            # ``oneOf`` this envelope is byte-identical to the one ``text_format`` produced.
            "text": {"format": openai_text_format(output_type)},
            "reasoning": {
                "effort": self._reasoning_effort,
                "mode": self._reasoning_mode,
                # Bounded call: prior-turn reasoning is never carried in.
                "context": "current_turn",
            },
            # Law 3: the Responses API stores by default, so refusing is explicit.
            "store": False,
            # A single bounded call. Tool use is certified deliberately, never inherited.
            "tools": [],
        }

        max_output_tokens = request.constraints.max_output_tokens
        if max_output_tokens is not None:
            # For reasoning models this bound covers reasoning tokens as well as visible
            # output. It is passed through as stated rather than reinterpreted.
            parse_kwargs["max_output_tokens"] = max_output_tokens

        timeout = self._timeout_for(request)
        if timeout is not None:
            parse_kwargs["timeout"] = timeout

        started = self._monotonic()
        try:
            response = self._responses().parse(**parse_kwargs)
        except openai.APIError:
            # The call never produced an answer: connection, timeout or status failure.
            # Deliberately NOT converted here — the runtime maps it to ModelProviderError.
            # Reporting it as an output-contract failure would send an operator looking for
            # a schema bug when the network was the problem, which is precisely what MR2's
            # first live run did before this distinction existed.
            raise
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
            # These are OpenAIError but *not* APIError: the request reached the model and
            # the model's output was cut short. That is an output-contract failure, and it
            # is never retried, repaired or partially accepted.
            raise ModelProtocolError(
                "OpenAI stopped the response before the requested structure was complete; "
                "partial structured output is never accepted"
            ) from exc
        elapsed_ms = int((self._monotonic() - started) * 1000)

        _require_completed(response)
        parsed = _require_parsed_output(response, output_type)

        return ProviderExecutionResult[output_type](  # type: ignore[valid-type]
            identity=ModelIdentity(
                provider=OPENAI_PROVIDER_ID,
                model=_executed_model(response),
            ),
            output=parsed,
            usage=_as_usage(response, elapsed_ms),
            # The Responses API exposes status, not a Chat Completions finish reason.
            # Inventing "stop" to resemble another provider would be fabricated telemetry.
            finish_reason=None,
        )

    def _responses(self) -> Any:
        """One client per provider, built on first use and reused.

        The credential is handed to the transport here and nowhere else.
        """
        if self._client is None:
            self._client = self._client_factory(
                api_key=self._api_key,
                # One Foundry call is one provider attempt. The SDK defaults this to 2, so
                # without it the transport would retry beneath a runtime that guarantees it
                # will not — and the caller would be billed for attempts it never approved.
                max_retries=0,
            )
        return self._client.responses

    def _reject_unsupported(self, model: ModelIdentity, request: ModelRequest) -> None:
        """Everything refusable without a network call is refused here.

        A constraint that cannot be honoured is refused rather than dropped: silently
        ignoring a caller's stated bound is the failure mode worth preventing, because the
        caller would believe a limit applied that never did.
        """
        if model.provider != OPENAI_PROVIDER_ID:
            raise ModelRequestError(
                f"the openai adapter cannot execute provider {model.provider!r}; it never "
                "runs another provider's identity"
            )
        if request.constraints.max_cost_usd is not None:
            raise ModelRequestError(
                "max_cost_usd cannot be enforced by the openai adapter in MR5: there is no "
                "trusted pre-call cost engine, and the budget is refused rather than "
                "pretended. Estimating from public list prices would be a guess presented "
                "as an enforced limit."
            )

    def _timeout_for(self, request: ModelRequest) -> float | None:
        """The request's timeout wins; the adapter default applies only when it has none.

        Returning ``None`` leaves the SDK's own default in force, which is different from
        imposing one. A requested timeout is never widened.
        """
        requested = request.constraints.timeout_seconds
        return requested if requested is not None else self._default_timeout_seconds


def _as_provider_input(messages: Sequence[ModelMessage]) -> list[dict[str, str]]:
    """Same order, same role, same content. No augmentation of any kind.

    System messages stay messages rather than being folded into ``instructions``: the model
    receives exactly the sequence the domain supplied.
    """
    built: list[dict[str, str]] = []
    for message in messages:
        role = _ROLE_NAMES.get(message.role)
        if role is None:
            raise ModelRequestError(f"no OpenAI role mapping for role {message.role.value}")
        built.append({"role": role, "content": message.content})
    return built


def _require_completed(response: Any) -> None:
    """Only a completed response can satisfy a structured call.

    An incomplete response may still carry partial output, and returning it would present
    a truncated answer as a whole one.
    """
    status = getattr(response, "status", None)
    if status == _COMPLETED:
        return

    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None)
    if status == "incomplete":
        raise ModelProtocolError(
            f"OpenAI returned an incomplete response (reason: {reason}); partial structured "
            "output is never accepted and the call is never silently retried"
        )
    raise ModelProtocolError(
        f"OpenAI returned a response with status {status!r} rather than {_COMPLETED!r}; "
        "anything other than a completed response fails closed"
    )


_FINAL_ANSWER: Final[str] = "final_answer"


def _require_parsed_output(response: Any, output_type: type[BaseModel]) -> Any:
    """The caller's type, validated from the answer text, or a failure that says which kind.

    This is the SDK's own final step, performed here because the compiled schema cannot travel
    with ``text_format``: every ``output_text`` of a message whose phase is absent or
    ``final_answer`` is validated by ``output_type.model_validate_json`` (any failure refuses the
    response), and the first is returned. Other phases are not structured results. Nothing is
    repaired, coerced, filled in or re-asked; Pydantic is the final authority.

    A refusal and an absent answer have different fixes, so they get different errors.
    """
    parsed: Any = None
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        phase = getattr(item, "phase", None)
        if phase is not None and phase != _FINAL_ANSWER:
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) != "output_text":
                continue
            try:
                value = output_type.model_validate_json(content.text)
            except ValidationError as exc:
                raise ModelProtocolError(
                    f"OpenAI returned output that could not be parsed as {output_type.__name__}"
                ) from exc
            if parsed is None:
                parsed = value
    if parsed is not None:
        return parsed

    if _contains_refusal(response):
        # The refusal text itself is deliberately not interpolated: it is model prose about
        # possibly sensitive input, and the operator needs the category, not the content.
        raise ModelProtocolError(
            "OpenAI returned a refusal instead of the requested structured output; a "
            "refusal is never treated as a typed success and commentary is never "
            "substituted for the schema"
        )

    raise ModelProtocolError(
        f"OpenAI returned no parsed structured output for {output_type.__name__}; output is "
        "never repaired, filled in or re-requested"
    )


def _contains_refusal(response: Any) -> bool:
    """True when any output message carries explicit refusal content."""
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def _executed_model(response: Any) -> str:
    """What the provider says actually ran — read from the response, never the request.

    Echoing the requested model would make the runtime's identity check vacuous: a
    substitution would agree with itself. An empty or absent value is refused for the same
    reason, since silence is not permission to assume the request was honoured.
    """
    executed = getattr(response, "model", "")
    if not executed:
        raise ModelProtocolError(
            "the OpenAI response reported no executed model identity; the runtime's "
            "identity check cannot be satisfied by assuming the requested model ran"
        )
    return str(executed)


def _as_usage(response: Any, elapsed_ms: int) -> ModelUsage:
    """Normalize real telemetry. Unreported stays ``None`` — never zero.

    ``cost_usd`` is always ``None``: the Responses API reports no authoritative dollar cost,
    and estimating one from public list prices inside a transport adapter would be a guess
    that later budgets would treat as a measurement. Price depends on model, cached tokens,
    processing tier and context length, and it changes; cost belongs to a trusted cost
    engine, not here. Unknown is not zero, and it is not a plausible number either.

    Unlike xAI's proto3 counters, ``input_tokens`` and ``output_tokens`` are required fields
    on ``ResponseUsage``, so a reported value is genuinely reported and is preserved as
    given. Only a wholly absent ``usage`` object yields unknowns.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return ModelUsage(wall_clock_ms=elapsed_ms)
    return ModelUsage(
        input_tokens=_optional_int(usage, "input_tokens"),
        output_tokens=_optional_int(usage, "output_tokens"),
        cost_usd=None,
        wall_clock_ms=elapsed_ms,
    )


def _optional_int(usage: Any, name: str) -> int | None:
    """Read a token count without inventing one."""
    value = getattr(usage, name, None)
    return None if value is None else int(value)
