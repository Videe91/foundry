"""Packet: T-007 / R-028 — per-family cache blocks.

One job: what the smoke run needs to know about the models in a registry —
which provider families are present, which role demos each, whether a family
has an adapter, what its caching note says, and whether a model is priced.

Split from smoke.py under the R-017 precedent so both stay under the ceiling.
Prescribes no role→model choices (R-012) — it only reads the registry.

Version: 0.9.1
"""

from __future__ import annotations

from switchboard.adapters import adapter_for
from switchboard.registry import ModelRegistry

# Reported, never assumed — the smoke run prints observed values beside these.
_CACHE_NOTES = {
    "anthropic": "explicit cache_control mark; minimum cacheable prefix applies",
    "openai": (
        "reads discounted on repeated prefix >=1024 tokens; recently reworked "
        "— reporting observed values."
    ),
    "gemini": (
        "implicit caching only; explicit marks not supported via this path. "
        "No cache hits observed on back-to-back identical ~3.7k-token prefixes "
        "(2026-08-18); mechanism threshold/timing unknown — reported, not "
        "explained."
    ),
    "xai": (
        "provider-side cached input pricing; no client marks — reporting "
        "observed values. Measured 2026-08-18: caching is quantised into "
        "128-TOKEN BLOCKS (7 of 7 observed values exact multiples of 128) and "
        "committed ASYNCHRONOUSLY — one byte-identical pair went backwards, "
        "2560 then 128, which a synchronous cache cannot do. Engages from "
        "prefixes as small as ~1.4k. Not reproducible within a run."
    ),
}

# Cache-demo prefix size per family, in repeats of _CACHE_PARAGRAPH.
#
# Retired as one shared constant under T-007/R-028. A single 3,721-token block
# was sized for Anthropic's 2,048 minimum (T-002), cleared OpenAI's 1,024
# comfortably, and sat silently below Gemini's real bar — one constant, four
# families, one invisible failure.
#
# Sizes come from MEASUREMENT, not from vendor documentation. Google documents
# 4,096 for gemini-3.7-flash; a 4,584-token prefix cleared that and still cached
# nothing. Engagement was measured between 5,682 and 6,109 tokens, in whole
# ~4,096-token blocks, so 105 repeats (~6,511 tokens) buys one block with margin.
# Each family's EFFECTIVE minimum cacheable prefix, in tokens — what was
# measured, not what was documented. Gemini is the cautionary entry: Google
# documents 4,096 and a 4,584-token prefix cleared that while caching nothing.
_CACHE_MINIMUMS = {
    "anthropic": 2048,  # haiku's; larger Anthropic models cache from 1024
    "openai": 1024,
    "gemini": 6109,     # MEASURED engagement; documented minimum is 4096
    "xai": 128,         # one 128-token block; engages from tiny prefixes
}

_CACHE_PARAGRAPHS = {
    "anthropic": 60,   # ~3,721 tokens; minimum 2,048, measured hit (T-002)
    "openai": 60,      # ~3,721 tokens; minimum 1,024, measured hit
    "xai": 60,         # ~3,721 tokens; 128-token blocks engage far below this
    "gemini": 105,     # ~6,511 tokens; docs say 4,096, MEASURED 5,682-6,109
}

# Only Anthropic reports a cache-CREATION counter, because only Anthropic takes
# an explicit mark. Printing its expectation at the other families made correct
# behaviour read as failure: "expected call 1 creation > 0" beside a textbook
# provider-side hit of creation=0. Family knowledge lives here, in one place.
_CREATION_COUNTER_FAMILIES = frozenset({"anthropic"})


def family_of(model: str) -> str:
    """The provider family a model string belongs to."""
    return model.split("/", 1)[0]


def families_in(registry: ModelRegistry) -> list[str]:
    """Unique families among the role primaries, in first-seen order."""
    seen: dict[str, None] = {}
    for route in registry.roles.values():
        seen.setdefault(family_of(route.model), None)
    return list(seen)


def demo_role_for(registry: ModelRegistry, family: str) -> str | None:
    """The cheapest role whose primary belongs to this family, by real price.

    Price comes from the cost map, not max_tokens. A ceiling is not a price:
    using it as a proxy silently moved the demos from a $1 model to a $2 one
    when an unrelated fallback-ceiling change created a tie.

    Unpriced models sort last. If every model in the family is unpriced, the
    old max_tokens rule still picks one so the demo runs. Ties break by
    declaration order, which is harmless once equal price means equal cost.
    """
    candidates = [
        (name, route)
        for name, route in registry.roles.items()
        if family_of(route.model) == family
    ]
    if not candidates:
        return None

    prices = {name: input_price_of(route.model) for name, route in candidates}
    if all(price is None for price in prices.values()):
        return min(candidates, key=lambda item: item[1].max_tokens)[0]

    def rank(item: tuple[str, object]) -> tuple[bool, float]:
        price = prices[item[0]]
        return (price is None, price if price is not None else 0.0)

    return min(candidates, key=rank)[0]


def family_has_adapter(registry: ModelRegistry, family: str) -> bool:
    """Whether this family's primaries route through a family adapter."""
    return any(
        adapter_for(route.model) is not None
        for route in registry.roles.values()
        if family_of(route.model) == family
    )


def cache_note_for(family: str) -> str:
    """The honest caching note printed beside this family's observed values."""
    return _CACHE_NOTES.get(family, "caching behaviour unknown for this family")


def cache_minimum_for_family(family: str) -> int:
    """This family's measured minimum cacheable prefix, in tokens."""
    return _CACHE_MINIMUMS.get(family, max(_CACHE_MINIMUMS.values()))


def cache_paragraphs_for(family: str) -> int:
    """How many paragraphs this family's cache demo needs.

    An undeclared family falls back to the LARGEST declared size, never the
    default or the smallest: an oversized prefix costs a little more and still
    demonstrates caching, while an undersized one silently demonstrates nothing.
    That is the failure T-007 was.
    """
    return _CACHE_PARAGRAPHS.get(family, max(_CACHE_PARAGRAPHS.values()))


def cache_expectation_for(family: str) -> str:
    """What this family's cache demo can honestly be expected to show."""
    if family in _CREATION_COUNTER_FAMILIES:
        return "call 1 creation > 0, call 2 cached > 0"
    return (
        "no creation counter on this family — cached > 0 once the provider's "
        "own cache engages, on either call"
    )


def _cost_entry(model: str) -> dict | None:
    """This model's cost-map entry, or None when it is not priced.

    The map is keyed without the provider prefix (`claude-opus-5`, not
    `anthropic/claude-opus-5`), so both forms are checked. R-023 books this
    stripping lookup as a known seam — verify it on double-prefixed families.
    """
    import litellm

    cost_map = getattr(litellm, "model_cost", {})
    bare = model.split("/", 1)[1] if "/" in model else model
    for key in (model, bare):
        entry = cost_map.get(key)
        if isinstance(entry, dict):
            return entry
    return None


def is_priced(model: str) -> bool:
    """Whether LiteLLM's cost map prices this model."""
    return _cost_entry(model) is not None


def input_price_of(model: str) -> float | None:
    """Input price per token, or None when the model carries no usable price."""
    entry = _cost_entry(model)
    if entry is None:
        return None
    price = entry.get("input_cost_per_token")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    return float(price)
