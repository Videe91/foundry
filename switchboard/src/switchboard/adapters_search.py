"""Packet: P-015 — The Switchboard Learns to Search.

One job: render a web-search spec into Anthropic's server-side tool block, and
answer whether a given model's family can search at all.

Split from adapters.py under the R-017 precedent when the fourth capability
pushed it past the 300-line ceiling. Per R-026 the split inherits its parent's
map entries.

Version: 0.15.0
"""

from __future__ import annotations

from typing import Any

from switchboard.adapters import adapter_for

# Anthropic's stable server-side search tool. `web_search_20260209` (dynamic
# filtering) is BOOKED, not built — a future amendment, docs-first.
WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
WEB_SEARCH_TOOL_NAME = "web_search"


def search_tool_block(spec: Any) -> dict[str, Any]:
    """Render a WebSearchSpec as Anthropic's documented tool block.

    Optional fields are omitted ENTIRELY when empty rather than sent as empty
    lists: `"allowed_domains": []` reads to a provider as "allow nothing", which
    is the opposite of "no restriction".
    """
    block: dict[str, Any] = {
        "type": WEB_SEARCH_TOOL_TYPE,
        "name": WEB_SEARCH_TOOL_NAME,
        "max_uses": spec.max_uses,
    }
    if spec.allowed_domains:
        block["allowed_domains"] = list(spec.allowed_domains)
    if spec.blocked_domains:
        block["blocked_domains"] = list(spec.blocked_domains)
    if spec.user_location:
        block["user_location"] = dict(spec.user_location)
    return block


def search_tool_for(model: str, spec: Any) -> dict[str, Any] | None:
    """This model's family's search tool block, or None if it cannot search."""
    adapter = adapter_for(model)
    renderer = getattr(adapter, "search_tool", None)
    return renderer(spec) if callable(renderer) else None


def supports_search(model: str) -> bool:
    """Whether this model's family can search at all."""
    return callable(getattr(adapter_for(model), "search_tool", None))
