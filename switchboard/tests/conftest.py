"""Packet: P-004 — Family One: Anthropic Adapter.

One job: shared offline fakes and fixtures for the switchboard test suite.
Created under R-009 so the individual test files stay well under 300 lines.

Version: 0.4.0
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.request import Attachment, Message, SwitchboardRequest
from switchboard.tags import CallTags

PRIMARY = "primary/model-a"
FALLBACK = "backup/model-b"
LAST_RESORT = "backup/model-c"
ANTHROPIC_MODEL = "anthropic/claude-haiku-4-5-20251001"

REGISTRY = ModelRegistry(
    roles={
        "builder": RoleRoute(
            model=PRIMARY, fallbacks=[FALLBACK, LAST_RESORT], max_tokens=4096
        ),
        "default": RoleRoute(model="default/model-d", fallbacks=[], max_tokens=1024),
    }
)

ANTHROPIC_REGISTRY = ModelRegistry(
    roles={
        "builder": RoleRoute(model=ANTHROPIC_MODEL, fallbacks=[], max_tokens=64000),
        "default": RoleRoute(model=ANTHROPIC_MODEL, fallbacks=[], max_tokens=64000),
    }
)


def provider_response(
    content: str,
    usage: tuple[int, int, int] | None,
    cached_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
) -> SimpleNamespace:
    """Mimic the LiteLLM response shape; omit `usage` entirely when None."""
    payload = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    if usage is not None:
        payload.usage = SimpleNamespace(
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            total_tokens=usage[2],
        )
        if cached_tokens is not None:
            payload.usage.prompt_tokens_details = SimpleNamespace(
                cached_tokens=cached_tokens
            )
        if cache_creation_tokens is not None:
            payload.usage.cache_creation_input_tokens = cache_creation_tokens
    return payload


class FakeCompletion:
    """Record every call received, and fail for the named models."""

    def __init__(
        self,
        answer: str = "an answer",
        failing: tuple[str, ...] = (),
        usage: tuple[int, int, int] | None = (10, 5, 15),
        cached_tokens: int | None = None,
        cache_creation_tokens: int | None = None,
    ) -> None:
        self.answer = answer
        self.failing = failing
        self.usage = usage
        self.cached_tokens = cached_tokens
        self.cache_creation_tokens = cache_creation_tokens
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        """Capture every kwarg, so a test can assert one was NOT sent.

        Streaming is the router's default (P-010), so this fake models BOTH
        shapes the real API returns — an iterator of chunks when `stream=True`,
        a single response object otherwise. R-019: the fake follows the API,
        not the implementation.
        """
        self.calls.append(dict(kwargs))
        model = kwargs["model"]
        if model in self.failing:
            raise RuntimeError(f"provider {model} is unavailable")
        response = provider_response(
            self.answer, self.usage, self.cached_tokens, self.cache_creation_tokens
        )
        if not kwargs.get("stream"):
            return response
        return self._stream(response)

    def _stream(self, response: SimpleNamespace) -> Any:
        return streamed(response)


def streamed(response: SimpleNamespace) -> Any:
    """Turn a provider response into the chunk sequence the API would stream.

    The delta chunks, then a terminal usage chunk with EMPTY choices. Empty
    choices on the terminal chunk is what LiteLLM really sends when
    stream_options asks for usage — established in P-005 and pinned here so
    every streamed test meets the shape the provider actually produces (R-019).
    """
    content = response.choices[0].message.content
    if content:
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
        )
    yield SimpleNamespace(choices=[], usage=getattr(response, "usage", None))


def provider(response: SimpleNamespace) -> Callable[..., Any]:
    """A completion_fn returning one fixed response in whichever shape is asked.

    Streaming is the router's default, so a fake that only ever returns a
    response object would test a path the system no longer takes by default.
    """

    def _fn(**kwargs: Any) -> Any:
        return streamed(response) if kwargs.get("stream") else response

    return _fn


def fixed_cost(value: float) -> Callable[[object], float]:
    def _cost_fn(_completion: object) -> float:
        return value

    return _cost_fn


def raising_cost(_completion: object) -> float:
    raise RuntimeError("cost lookup exploded")


FREE = fixed_cost(0.0)


def make_request(
    system: str | None = None,
    attachments: list[Attachment] | None = None,
    web_search: object = None,
    **tag_values: object,
) -> SwitchboardRequest:
    tag_values.setdefault("project_id", "foundry")
    tag_values.setdefault("department", "floor")
    tag_values.setdefault("role", "builder")
    return SwitchboardRequest(
        tags=CallTags(**tag_values),
        messages=[Message(role="user", content="ping")],
        system=system,
        attachments=attachments or [],
        web_search=web_search,
    )
