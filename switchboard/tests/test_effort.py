"""Packet: P-004 — Family One: Anthropic Adapter (effort amendment).

One job: test that a role's configured reasoning effort reaches the provider,
and that nothing is sent when no effort is configured.

Split from test_router.py: that file was at the Law rule 3 ceiling, and effort
is its own job.

Version: 0.4.0
"""

from __future__ import annotations

from conftest import FALLBACK, FREE, PRIMARY, REGISTRY, FakeCompletion, make_request

from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.router import route_call

EFFORT_REGISTRY = ModelRegistry(
    roles={
        "builder": RoleRoute(
            model=PRIMARY, fallbacks=[], max_tokens=4096, effort="xhigh"
        ),
        "default": RoleRoute(model="default/model-d", fallbacks=[], max_tokens=1024),
    }
)


def test_configured_effort_is_sent_as_reasoning_effort() -> None:
    fake = FakeCompletion()
    route_call(make_request(), EFFORT_REGISTRY, fake, FREE)
    assert fake.calls[0]["reasoning_effort"] == "xhigh"


def test_no_effort_means_the_kwarg_is_never_sent() -> None:
    fake = FakeCompletion()
    route_call(make_request(), REGISTRY, fake, FREE)
    assert "reasoning_effort" not in fake.calls[0]


def test_a_thinking_field_is_never_sent() -> None:
    fake = FakeCompletion()
    route_call(make_request(), EFFORT_REGISTRY, fake, FREE)
    assert not any(key.startswith("thinking") for key in fake.calls[0])


def test_effort_rides_every_attempt_including_fallbacks() -> None:
    registry = ModelRegistry(
        roles={
            "builder": RoleRoute(
                model=PRIMARY, fallbacks=[FALLBACK], max_tokens=4096, effort="low"
            )
        }
    )
    fake = FakeCompletion(failing=(PRIMARY,))
    route_call(make_request(), registry, fake, FREE)
    assert [call["reasoning_effort"] for call in fake.calls] == ["low", "low"]
