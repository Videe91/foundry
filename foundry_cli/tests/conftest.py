"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: the shared fakes. Everything is injected at the route_call boundary —
the single point where this package touches the Switchboard — so no test needs
a key, a network, or a real model.

R-019: the fakes model the API. A fake response carries the same members
route_call really returns, and streaming really calls back before returning.

Version: 0.1.0
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from switchboard.registry import ModelRegistry, RoleRoute

SLUG = "demo-app"


def usage(cost: float | None = 0.0012, tokens: int = 100) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=tokens, completion_tokens=10, total_tokens=tokens + 10,
        cost_usd=cost, cached_tokens=0, cache_creation_tokens=0,
    )


def response(content: str, cost: float | None = 0.0012) -> SimpleNamespace:
    return SimpleNamespace(
        status="ok", content=content, model_used="fake/model",
        usage=usage(cost), tags=None,
    )


class FakeRoute:
    """Stands in for route_call. Records every request; replies from a queue.

    Streams by calling on_chunk with the reply's own characters, then returns
    the assembled content — which is what the real router does, and what makes
    the "never re-join deltas" test meaningful.
    """

    def __init__(self, replies: list[str] | None = None,
                 costs: list[float | None] | None = None,
                 stream_text: str | None = None) -> None:
        self.replies = list(replies or [])
        self.costs = list(costs or [])
        self.stream_text = stream_text
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request, registry, completion_fn=None, cost_fn=None,
                 meter=None, on_chunk=None, stream=True) -> Any:
        self.calls.append({
            "request": request, "registry": registry, "meter": meter,
            "on_chunk": on_chunk, "role": request.tags.role,
            "tags": request.tags, "attachments": list(request.attachments),
            "system": request.system,
            "messages": [m.content for m in request.messages],
        })
        reply = self.replies.pop(0) if self.replies else "next question?"
        cost = self.costs.pop(0) if self.costs else 0.0012
        if on_chunk is not None:
            for piece in (self.stream_text or reply):
                on_chunk(piece)
        if meter is not None:
            meter.record(_record(request))
        return response(reply, cost)

    def roles(self) -> list[str]:
        return [call["role"] for call in self.calls]


def _record(request) -> Any:
    """A meter record shaped like the Switchboard's, so MeterRouter can file it."""
    payload = {
        "tags": request.tags.model_dump(),
        "model_used": "fake/model",
        "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                  "total_tokens": 110, "cost_usd": 0.0012,
                  "cached_tokens": 0, "cache_creation_tokens": 0},
        "recorded_at": "2026-08-19T00:00:00Z",
    }
    return SimpleNamespace(
        tags=request.tags,
        model_dump_json=lambda: json.dumps(payload, separators=(",", ":")),
    )


FULL_BOXES: dict[str, dict[str, Any]] = {
    "goal": {"summary": "a tool", "victory_conditions": ["ships", "is used"]},
    "users": {"users": [{"name": "founder", "needs": "speed"}]},
    "workflows": {"workflows": [{"story": "uploads", "mode": "automate"}]},
    "data": {"entities": ["invoice"], "sensitive": []},
    "boundaries": {"exclusions": ["no payments"]},
    "non_negotiables": {"security_level": "standard", "scale": "small",
                        "budget": "$100/mo"},
    "website": {"needed": False},
}


def scribe_json(**kwargs: Any) -> str:
    return json.dumps(kwargs)


def fake_registry() -> ModelRegistry:
    return ModelRegistry(roles={
        "interviewer": RoleRoute(model="anthropic/claude-sonnet-5",
                                 fallbacks=[], max_tokens=64000, effort="high"),
        "scribe": RoleRoute(model="anthropic/claude-haiku-4-5-20251001",
                            fallbacks=[], max_tokens=64000, effort="high"),
    })


class Reader:
    """A scripted stand-in for input(); raises EOFError when exhausted."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class Printer:
    """Captures printed output, honouring end= so streamed deltas concatenate."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def __call__(self, *parts: Any, end: str = "\n", flush: bool = False) -> None:
        self.chunks.append(" ".join(str(p) for p in parts) + end)

    @property
    def text(self) -> str:
        return "".join(self.chunks)


@pytest.fixture
def project(tmp_path: Path):
    from workspace import create_project

    return create_project(SLUG, "Demo App", root=tmp_path)
