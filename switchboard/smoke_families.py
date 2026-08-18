"""Packet: P-007 — Family Two: OpenAI Adapter.

One job: what the smoke run needs to know about the models in a registry —
which provider families are present, which role demos each, whether a family
has an adapter, what its caching note says, and whether a model is priced.

Split from smoke.py under the R-017 precedent so both stay under the ceiling.
Prescribes no role→model choices (R-012) — it only reads the registry.

Version: 0.7.0
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
    """The cheapest-max_tokens role whose primary belongs to this family."""
    candidates = [
        (name, route)
        for name, route in registry.roles.items()
        if family_of(route.model) == family
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[1].max_tokens)[0]


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


def is_priced(model: str) -> bool:
    """Whether LiteLLM's cost map prices this model.

    The map is keyed without the provider prefix (`claude-opus-5`, not
    `anthropic/claude-opus-5`), so both forms are checked.
    """
    import litellm

    cost_map = getattr(litellm, "model_cost", {})
    bare = model.split("/", 1)[1] if "/" in model else model
    return model in cost_map or bare in cost_map
