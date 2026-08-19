"""Packet: P-016 — Research Both Ways.

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

Version: 0.16.0
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from switchboard.adapters import adapter_for
from switchboard.adapters_search import search_tool_for, supports_search
from switchboard.meter import MeterLedger, MeterRecord, Usage
from switchboard.registry import ModelRegistry
from switchboard.request import SwitchboardRequest, SwitchboardResponse, WebSearchSpec
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
    # Discovered, not guessed (R-019): litellm 1.97.0 exposes
    # litellm.types.utils.ServerToolUse with field `web_search_requests`,
    # reachable at usage.server_tool_use. Absent on every non-searched call, so
    # it defaults to 0 like every other counter here.
    server_tools = getattr(raw, "server_tool_use", None)

    return Usage(
        **counts,
        cost_usd=cost_usd,
        cached_tokens=_int_or_zero(getattr(details, "cached_tokens", 0)),
        cache_creation_tokens=_int_or_zero(
            getattr(raw, "cache_creation_input_tokens", 0)
        ),
        web_search_requests=_int_or_zero(
            getattr(server_tools, "web_search_requests", 0)
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

    # Precedence: an explicit spec on the request always wins; otherwise a role
    # configured to search supplies one. A role that is not configured to search
    # adds nothing at all — no tools kwarg reaches the wire (P-016 contract 1).
    search_spec = request.web_search
    if search_spec is None and route.web_search:
        search_spec = WebSearchSpec(max_uses=route.web_search_max_uses)

    models_tried: list[str] = []
    last_error: Exception | None = None

    for model in (route.model, *route.fallbacks):
        models_tried.append(model)

        # Capability gate, before any provider call. A searched request never
        # silently becomes an unsearched one — not on the primary, and not by
        # falling back into a family that cannot search (P-015 contract 3).
        # Driven by adapter capability, never a family list: a family that
        # learns to search opens this gate by defining search_tool.
        if search_spec is not None and not supports_search(model):
            last_error = ProviderCallError(
                f"web search is not supported by the "
                f"'{model.split('/', 1)[0]}' family (model {model})"
            )
            continue

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
        # The tools kwarg is omitted ENTIRELY when no search was asked for, so
        # an ordinary call is byte-identical to a pre-P-015 one (R-018 pattern).
        if search_spec is not None:
            call_kwargs["tools"] = [search_tool_for(model, search_spec)]
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
