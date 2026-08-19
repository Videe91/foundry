"""Packet: P-016 — Research Both Ways: auto-attach.

One job: test that a role configured to search gets a search spec attached, that
an explicit request spec beats the config, and that a role which is not
configured to search sends no tools kwarg at all.

Split from test_search.py under R-017 when it reached the 300-line ceiling; per
R-026 the split inherits its parent's map entries.

Version: 0.16.0
"""

from __future__ import annotations

import pytest
from conftest import FREE, FakeCompletion, make_request

from switchboard.adapters_search import WEB_SEARCH_TOOL_NAME, WEB_SEARCH_TOOL_TYPE
from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.request import WebSearchSpec
from switchboard.router import ProviderCallError, route_call

ANTHROPIC = "anthropic/claude-sonnet-5"
OPENAI = "openai/gpt-5.6-terra"


def _searched(**kwargs):
    return make_request(web_search=WebSearchSpec(**kwargs))


# --- P-016: auto-attach from the role's own config -------------------------


def _searching_registry(model: str = ANTHROPIC, max_uses: int = 3,
                        enabled: bool = True) -> ModelRegistry:
    return ModelRegistry(roles={"builder": RoleRoute(
        model=model, fallbacks=[], max_tokens=4096,
        web_search=enabled, web_search_max_uses=max_uses)})


def test_a_searching_role_attaches_its_own_max_uses() -> None:
    fake = FakeCompletion()
    route_call(make_request(), _searching_registry(max_uses=8), fake, FREE)
    assert fake.calls[0]["tools"] == [{
        "type": WEB_SEARCH_TOOL_TYPE, "name": WEB_SEARCH_TOOL_NAME, "max_uses": 8
    }]


def test_an_explicit_request_spec_beats_the_role_config() -> None:
    """Precedence, asserted where it matters: a caller who asked for something
    specific is not overruled by configuration."""
    fake = FakeCompletion()
    route_call(_searched(max_uses=1), _searching_registry(max_uses=8), fake, FREE)
    assert fake.calls[0]["tools"][0]["max_uses"] == 1


def test_a_non_searching_role_sends_no_tools_kwarg_at_all() -> None:
    """The byte-identical law: absence, not an empty list (R-018 pattern)."""
    fake = FakeCompletion()
    route_call(make_request(), _searching_registry(enabled=False), fake, FREE)
    assert "tools" not in fake.calls[0]


def test_the_role_default_max_uses_is_three() -> None:
    fake = FakeCompletion()
    route_call(make_request(), ModelRegistry(roles={"builder": RoleRoute(
        model=ANTHROPIC, fallbacks=[], max_tokens=4096, web_search=True)}),
        fake, FREE)
    assert fake.calls[0]["tools"][0]["max_uses"] == 3


def test_a_role_configured_to_search_still_meets_the_family_gate() -> None:
    """Config cannot buy a capability the family lacks. The load check catches
    this first, but the runtime gate is what protects a fallback."""
    fake = FakeCompletion()
    registry = ModelRegistry(roles={"builder": RoleRoute(
        model=OPENAI, fallbacks=[], max_tokens=4096, web_search=True)})
    with pytest.raises(ProviderCallError) as excinfo:
        route_call(make_request(), registry, fake, FREE)
    assert "openai" in str(excinfo.value)
    assert fake.calls == []
