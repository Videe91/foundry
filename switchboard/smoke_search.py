"""Packet: P-015 — The Switchboard Learns to Search.

One job: PROVE 5 — one live searched answer on a family that can search.

Split from smoke_proves.py under the R-017 precedent when the fifth phase
pushed it past the 300-line ceiling. Per R-026 the split inherits its parent's
map entries.

Version: 0.15.0
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from smoke_families import note_if_not_primary
from smoke_proves import _smoke_request
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry
from switchboard.request import WebSearchSpec
from switchboard.adapters_search import supports_search
from switchboard.router import route_call


SEARCH_QUESTION = (
    "In one sentence: what is the Bank of England's current base rate? "
    "Cite the source."
)


def prove_search(
    registry: ModelRegistry,
    meter: MeterLedger,
    role: str,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> Any:
    """Ask something that cannot be answered from training data alone.

    Streaming, because that is the path P-016's interviewer will use. Reported,
    never asserted (R-014): whether the model chooses to search is its decision,
    and a run that answers without searching is data, not a failure.
    """
    print("\n=== PROVE 5: WEB SEARCH ===")
    model = registry.resolve(role).model
    print(f"  {model}: server-side search, max_uses=2")
    print("  expected: searches >= 1 and a cited answer (reported, not asserted)")
    print("  ", end="", flush=True)

    def emit(delta: str) -> None:
        print(delta, end="", flush=True)

    response = route_call(
        _smoke_request(role, SEARCH_QUESTION, None,
                       web_search=WebSearchSpec(max_uses=2)),
        registry,
        completion_fn,
        cost_fn,
        meter,
        emit,
    )
    usage = response.usage
    note_if_not_primary(registry, role, response.model_used)
    print(
        f"\n  receipt: {response.model_used} "
        f"tokens={usage.prompt_tokens}/{usage.completion_tokens} "
        f"searches={usage.web_search_requests} cost={usage.cost_usd}"
    )
    print("  (cost INCLUDES the $0.01-per-search fee — measured 2026-08-19)")
    return response


def prove_search_or_skip(
    registry: ModelRegistry,
    meter: MeterLedger,
    role: str,
    family: str,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> Any:
    """Run PROVE 5, or say plainly why this family sits it out.

    The decision lives here rather than in prove_families: whether a family can
    search is search's business, and asking the adapter keeps the answer in one
    place as other families join.
    """
    if supports_search(registry.resolve(role).model):
        return prove_search(registry, meter, role, completion_fn, cost_fn)
    print(f"\n=== PROVE 5: WEB SEARCH ===\n  [skip] {family}: "
          "this family cannot search (P-015 is Anthropic-first)")
    return None
