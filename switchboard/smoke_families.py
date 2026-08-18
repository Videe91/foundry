"""Packet: P-008 — Family Three: Gemini Adapter.

One job: what the smoke run needs to know about the models in a registry —
which provider families are present, which role demos each, whether a family
has an adapter, what its caching note says, and whether a model is priced.

Split from smoke.py under the R-017 precedent so both stay under the ceiling.
Prescribes no role→model choices (R-012) — it only reads the registry.

Version: 0.8.1
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
}


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
