"""Packet: P-002 — Switchboard Routing.

One job: after the tag gate passes, resolve the caller's role to a model and
execute the call, walking the fallback chain until one model answers.

Version: 0.2.0
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import litellm

from switchboard.registry import ModelRegistry
from switchboard.request import SwitchboardRequest, SwitchboardResponse
from switchboard.tags import validate_tags

OK_STATUS = "ok"


class ProviderCallError(Exception):
    """Raised when every model in a role's chain failed to answer."""

    def __init__(self, message: str, models_tried: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.models_tried = models_tried


def route_call(
    request: SwitchboardRequest,
    registry: ModelRegistry,
    completion_fn: Callable[..., Any] | None = None,
) -> SwitchboardResponse:
    """Gate the call on its tags, then route it to the role's model.

    Raises MissingTagsError when the tags are bad, UnknownRoleError when the
    role cannot be resolved, and ProviderCallError when every model failed.
    """
    validate_tags(request.tags)

    route = registry.resolve(request.tags.role)
    caller = litellm.completion if completion_fn is None else completion_fn
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

        return SwitchboardResponse(
            status=OK_STATUS,
            tags=request.tags,
            received_at=datetime.now(timezone.utc),
            model_used=model,
            content=completion.choices[0].message.content,
        )

    raise ProviderCallError(
        f"all models failed for role '{request.tags.role}': tried "
        f"{', '.join(models_tried)}; last error: {last_error}",
        tuple(models_tried),
    )
