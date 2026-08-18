"""Packet: P-003 — Switchboard Meter.

One job: after the tag gate passes, resolve the caller's role to a model,
execute the call through the fallback chain, and meter what it cost.

litellm is imported lazily inside route_call — a module-level import costs
every importer the provider stack's load time, and is forbidden.

Version: 0.3.0
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

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


def _extract_usage(completion: Any, cost_usd: float | None) -> Usage:
    """Read token counts off the provider response, defaulting to zero.

    The meter must never kill a successful call, so anything missing or
    unusable is recorded as 0 rather than raised.
    """
    raw = getattr(completion, "usage", None)
    counts: dict[str, int] = {}
    for field in _TOKEN_FIELDS:
        value = getattr(raw, field, 0)
        usable = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        counts[field] = value if usable else 0

    return Usage(**counts, cost_usd=cost_usd)


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


def route_call(
    request: SwitchboardRequest,
    registry: ModelRegistry,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
    meter: MeterLedger | None = None,
) -> SwitchboardResponse:
    """Gate the call on its tags, route it to the role's model, then meter it.

    Raises MissingTagsError when the tags are bad, UnknownRoleError when the
    role cannot be resolved, and ProviderCallError when every model failed.
    """
    validate_tags(request.tags)

    route = registry.resolve(request.tags.role)
    caller = completion_fn
    if caller is None:
        import litellm

        caller = litellm.completion
    payload = [message.model_dump() for message in request.messages]

    models_tried: list[str] = []
    last_error: Exception | None = None

    for model in (route.model, *route.fallbacks):
        models_tried.append(model)
        try:
            completion = caller(
                model=model,
                messages=payload,
                max_tokens=route.max_tokens,
            )
        except Exception as exc:
            last_error = exc
            continue

        usage = _extract_usage(completion, _compute_cost(completion, cost_fn))
        response = SwitchboardResponse(
            status=OK_STATUS,
            tags=request.tags,
            received_at=datetime.now(timezone.utc),
            model_used=model,
            content=completion.choices[0].message.content,
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
