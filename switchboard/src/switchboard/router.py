"""Packet: P-010 — Streaming by default, all families.

One job: after the tag gate passes, resolve the caller's role to a model,
shape the payload for that model's family, execute the call through the
fallback chain, and meter what it cost.

Streaming is the DEFAULT for every call and every family. Pass `on_chunk` to
receive text deltas as they arrive; without one the deltas are consumed
internally and the assembled text is returned, so the surface is unchanged.
Pass `stream=False` for a single blocking call — the escape hatch for a
provider or feature that cannot stream. If a model
fails after already delivering deltas, the fallback starts a fresh stream and
its deltas continue arriving through the same callback. The returned
SwitchboardResponse.content holds ONLY the successful model's full text, so the
receipt is always truthful. A caller wanting clean UX should treat a changed
`model_used` as "rerender from response.content".

litellm is imported lazily inside route_call — a module-level import costs
every importer the provider stack's load time, and is forbidden.

Version: 0.10.0
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from switchboard.adapters import adapter_for
from switchboard.meter import MeterLedger, MeterRecord, Usage
from switchboard.registry import ModelRegistry
from switchboard.request import SwitchboardRequest, SwitchboardResponse
from switchboard.tags import validate_tags

OK_STATUS = "ok"

_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


class ProviderCallError(Exception):
    """Raised when every model in a role's chain failed to answer."""

    def __init__(self, message: str, models_tried: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.models_tried = models_tried


def _int_or_zero(value: Any) -> int:
    """Coerce a provider-supplied count to a usable non-negative int."""
    usable = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return value if usable else 0


def _extract_usage(completion: Any, cost_usd: float | None) -> Usage:
    """Read token counts off the provider response, defaulting to zero.

    The meter must never kill a successful call, so anything missing or
    unusable is recorded as 0 rather than raised.
    """
    raw = getattr(completion, "usage", None)
    counts = {field: _int_or_zero(getattr(raw, field, 0)) for field in _TOKEN_FIELDS}
    details = getattr(raw, "prompt_tokens_details", None)

    return Usage(
        **counts,
        cost_usd=cost_usd,
        cached_tokens=_int_or_zero(getattr(details, "cached_tokens", 0)),
        cache_creation_tokens=_int_or_zero(
            getattr(raw, "cache_creation_input_tokens", 0)
        ),
    )


def _payload_for(request: SwitchboardRequest, model: str) -> list[dict]:
    """Shape the messages for this model's family.

    A family with no adapter gets P-002's plain dicts. Attachments are never
    silently dropped: a family that cannot carry them is an error, not a
    downgrade.
    """
    adapter = adapter_for(model)
    if adapter is not None:
        return adapter.prepare(request.system, request.messages, request.attachments)

    if request.attachments:
        raise ProviderCallError(
            f"attachments are unsupported for the model family of '{model}'; "
            f"{len(request.attachments)} attachment(s) would have been dropped"
        )

    payload = [message.model_dump() for message in request.messages]
    if request.system:
        payload.insert(0, {"role": "system", "content": request.system})
    return payload


def _compute_cost(completion: Any, cost_fn: Callable[..., Any] | None) -> float | None:
    """Best-effort cost. Any failure yields None rather than killing the call."""
    try:
        caller = cost_fn
        if caller is None:
            from litellm import completion_cost

            caller = completion_cost
        value = caller(completion)
    except Exception:
        return None

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _meter_call(
    meter: MeterLedger,
    request: SwitchboardRequest,
    model_used: str,
    usage: Usage,
) -> None:
    """Append one meter record. A write failure warns; it never raises."""
    record = MeterRecord(
        tags=request.tags,
        model_used=model_used,
        usage=usage,
        recorded_at=datetime.now(timezone.utc),
    )
    try:
        meter.record(record)
    except Exception as exc:
        warnings.warn(
            f"meter write failed for model '{model_used}': {exc}",
            RuntimeWarning,
            stacklevel=2,
        )


def _chunk_text(chunk: Any) -> str:
    """Pull the text delta off one stream chunk, tolerating empty chunks."""
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    return getattr(delta, "content", None) or ""


def _stream_call(
    caller: Callable[..., Any],
    call_kwargs: dict[str, Any],
    on_chunk: Callable[[str], None] | None,
) -> tuple[str, Any]:
    """Consume a streamed call, returning its full text and usage carrier.

    `on_chunk` is optional: streaming is the default, so most calls have no
    consumer for the deltas and simply want the assembled text. A callback that
    raises is converted to a warning and no further callbacks are made — the
    stream is still drained so the receipt stays complete.
    """
    deltas: list[str] = []
    usage_carrier: Any = None
    callbacks_live = True

    # stream_options is what makes the provider attach usage to the terminal
    # chunk; without it a streamed call reports zero tokens (R-018).
    for chunk in caller(
        **call_kwargs, stream=True, stream_options={"include_usage": True}
    ):
        if getattr(chunk, "usage", None) is not None:
            usage_carrier = chunk

        delta = _chunk_text(chunk)
        if not delta:
            continue
        deltas.append(delta)

        if on_chunk is not None and callbacks_live:
            try:
                on_chunk(delta)
            except Exception as exc:
                warnings.warn(
                    f"on_chunk callback failed, streaming continues: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                callbacks_live = False

    return "".join(deltas), usage_carrier


def route_call(
    request: SwitchboardRequest,
    registry: ModelRegistry,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
    meter: MeterLedger | None = None,
    on_chunk: Callable[[str], None] | None = None,
    stream: bool = True,
) -> SwitchboardResponse:
    """Gate the call on its tags, route it to the role's model, then meter it.

    Streams by default. `stream=False` makes exactly the single blocking call
    this used to make when no `on_chunk` was supplied.

    Raises MissingTagsError when the tags are bad, UnknownRoleError when the
    role cannot be resolved, and ProviderCallError when every model failed.
    """
    validate_tags(request.tags)

    route = registry.resolve(request.tags.role)
    caller = completion_fn
    if caller is None:
        import litellm

        caller = litellm.completion

    models_tried: list[str] = []
    last_error: Exception | None = None

    for model in (route.model, *route.fallbacks):
        models_tried.append(model)
        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": _payload_for(request, model),
            "max_tokens": route.max_tokens,
        }
        # Reasoning effort is sent only when the role configures it. The
        # kwarg is omitted entirely otherwise, and no thinking field is ever
        # sent.
        if route.effort is not None:
            call_kwargs["reasoning_effort"] = route.effort
        try:
            if stream:
                content, completion = _stream_call(caller, call_kwargs, on_chunk)
            else:
                completion = caller(**call_kwargs)
                content = completion.choices[0].message.content
        except Exception as exc:
            last_error = exc
            continue

        usage = _extract_usage(completion, _compute_cost(completion, cost_fn))
        response = SwitchboardResponse(
            status=OK_STATUS,
            tags=request.tags,
            received_at=datetime.now(timezone.utc),
            model_used=model,
            content=content,
            usage=usage,
        )

        if meter is not None:
            _meter_call(meter, request, model, usage)

        return response

    raise ProviderCallError(
        f"all models failed for role '{request.tags.role}': tried "
        f"{', '.join(models_tried)}; last error: {last_error}",
        tuple(models_tried),
    )
