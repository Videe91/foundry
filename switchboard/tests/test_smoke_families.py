"""Packet: P-010 — Family Five: OpenRouter (aggregator).

One job: test smoke_families.py — which families a registry contains, which
role demos each, whether a family has an adapter, and what its cache note and
cache expectation say.

Split from test_smoke.py under the R-017 precedent when that file reached the
300-line ceiling. Per R-026, the split inherits its parent's map entries.

No network, no keys. Structure, never values (R-014).

Version: 0.11.0
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from smoke_families import (_CACHE_MINIMUMS, _CACHE_PARAGRAPHS,
                            cache_expectation_for, cache_minimum_for_family,
                            cache_note_for, cache_paragraphs_for,
                            demo_role_for, families_in, family_has_adapter,
                            input_price_of)
from switchboard.registry import ModelRegistry, RoleRoute, load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry.toml"
SHARED = "anthropic/claude-haiku-4-5-20251001"
SONNET = "anthropic/claude-sonnet-5"


TWO_FAMILY_REGISTRY = ModelRegistry(
    roles={
        "floor_agent": RoleRoute(model=SHARED, fallbacks=[], max_tokens=64000),
        "architect": RoleRoute(model=SONNET, fallbacks=[], max_tokens=128000),
        "judge": RoleRoute(
            model="openai/gpt-5.6-terra", fallbacks=[], max_tokens=128000
        ),
        "judge_third": RoleRoute(
            model="gemini/gemini-3.7-flash", fallbacks=[], max_tokens=64000
        ),
        "judge_fourth": RoleRoute(
            model="xai/grok-4.6", fallbacks=[], max_tokens=64000
        ),
        "judge_fifth": RoleRoute(
            model="openrouter/moonshotai/kimi-k3", fallbacks=[], max_tokens=64000
        ),
        "scribe": RoleRoute(model="mistral/large", fallbacks=[], max_tokens=8000),
    }
)


def test_families_are_the_unique_primary_prefixes() -> None:
    assert families_in(TWO_FAMILY_REGISTRY) == [
        "anthropic",
        "openai",
        "gemini",
        "xai",
        "openrouter",
        "mistral",
    ]


def _registry(*roles: tuple[str, str, int]) -> ModelRegistry:
    return ModelRegistry(
        roles={
            name: RoleRoute(model=model, fallbacks=[], max_tokens=ceiling)
            for name, model, ceiling in roles
        }
    )


@pytest.fixture
def stub_cost_map(monkeypatch: pytest.MonkeyPatch):
    """Install a fake cost map — the fast tests never touch the real one."""

    def install(prices: dict[str, float]) -> None:
        module = types.ModuleType("litellm")
        module.model_cost = {
            key: {"input_cost_per_token": price} for key, price in prices.items()
        }
        monkeypatch.setitem(sys.modules, "litellm", module)

    return install


def test_demo_role_is_the_cheapest_priced_model(stub_cost_map) -> None:
    """The retired proxy would pick `pricey` here — it has the lower ceiling."""
    stub_cost_map({"cheap-model": 1e-06, "pricey-model": 2e-06})
    registry = _registry(
        ("pricey", "anthropic/pricey-model", 64000),
        ("cheap", "anthropic/cheap-model", 128000),
    )
    assert demo_role_for(registry, "anthropic") == "cheap"


def test_unpriced_model_sorts_last(stub_cost_map) -> None:
    stub_cost_map({"priced-model": 9e-06})
    registry = _registry(
        ("unpriced", "anthropic/absent-model", 1000),
        ("priced", "anthropic/priced-model", 128000),
    )
    assert demo_role_for(registry, "anthropic") == "priced"


def test_all_unpriced_family_falls_back_to_max_tokens(stub_cost_map) -> None:
    """The demo still runs when nothing in the family is priced."""
    stub_cost_map({})
    registry = _registry(
        ("big", "vendor/model-a", 128000),
        ("small", "vendor/model-b", 8000),
    )
    assert demo_role_for(registry, "vendor") == "small"


def test_equal_price_breaks_by_declaration_order(stub_cost_map) -> None:
    stub_cost_map({"twin-a": 3e-06, "twin-b": 3e-06})
    registry = _registry(
        ("first", "anthropic/twin-a", 128000),
        ("second", "anthropic/twin-b", 8000),
    )
    assert demo_role_for(registry, "anthropic") == "first"


def test_the_real_cost_map_prices_every_shipped_model() -> None:
    """R-022-style: the prefix-stripping lookup works against the real map.

    Structure, not values (R-014) — the human may repoint any role.
    """
    registry = load_registry(REGISTRY_PATH)
    for name, route in registry.roles.items():
        price = input_price_of(route.model)
        assert price is not None and price > 0, f"{name}: {route.model} unpriced"


def test_adapterless_family_is_reported_as_such() -> None:
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "anthropic") is True
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "openai") is True
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "gemini") is True
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "xai") is True
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "openrouter") is True
    assert family_has_adapter(TWO_FAMILY_REGISTRY, "mistral") is False


def test_every_adapter_family_has_its_own_cache_note() -> None:
    """P-008 contract 1: a family we understand must not print the fallback.

    The gemini note says what we know — implicit caching only — and what we
    merely observed, without dressing the observation up as an explanation.
    """
    fallback = cache_note_for("mistral")
    for family in ("anthropic", "openai", "gemini", "xai", "openrouter"):
        assert cache_note_for(family) != fallback, f"{family} fell back"
    gemini = cache_note_for("gemini")
    assert "implicit caching only" in gemini
    assert "reported, not" in gemini


def test_xai_cache_note_says_provider_side_and_promises_nothing() -> None:
    """P-009 contract 1: xAI prices cached input; we place no marks."""
    note = cache_note_for("xai")
    assert "provider-side" in note
    assert "no client marks" in note


def test_only_anthropic_is_promised_a_creation_counter() -> None:
    """The demo printed Anthropic's expectation at every family.

    Only Anthropic takes an explicit mark, so only Anthropic reports a
    creation counter — test_cache.py pins that openai, gemini, and xai read it
    as a structural zero. Printing "expected: call 1 creation > 0" beside them
    made a textbook provider-side cache hit read as a failure. Every test
    passed while the output said something false about families we understand
    precisely — the same defect shape as the missing Gemini cache label.
    """
    assert "creation > 0" in cache_expectation_for("anthropic")
    for family in ("openai", "gemini", "xai", "mistral"):
        expectation = cache_expectation_for(family)
        assert "creation > 0" not in expectation, f"{family} promised a counter"
        assert "no creation counter" in expectation


# --- T-007 / R-028: the cache block is per family, sized by measurement ------


def test_every_family_block_clears_that_familys_measured_minimum() -> None:
    """The defect T-007 was: one constant sized for Anthropic, silently below
    Gemini's real bar. Each family's own block must clear its own minimum."""
    from smoke_proves import cache_block_for
    import litellm

    probe = {
        "anthropic": "anthropic/claude-haiku-4-5-20251001",
        "openai": "openai/gpt-5.6-terra",
        "gemini": "gemini/gemini-3.7-flash",
        "xai": "xai/grok-4.6",
    }
    for family, model in probe.items():
        tokens = litellm.token_counter(model=model, text=cache_block_for(family))
        minimum = cache_minimum_for_family(family)
        assert tokens >= minimum, f"{family}: {tokens} tokens below {minimum}"


def test_the_retired_single_block_would_fail_gemini() -> None:
    """Discriminating: the guard above must not pass under the OLD rule.

    60 paragraphs was the one shared size. It clears anthropic, openai and xai
    and sits below gemini's measured minimum — which is exactly why twelve live
    calls cached nothing while every test passed.
    """
    from smoke_proves import _CACHE_PARAGRAPH
    import litellm

    retired = _CACHE_PARAGRAPH * 60
    gemini = litellm.token_counter(model="gemini/gemini-3.7-flash", text=retired)
    assert gemini < cache_minimum_for_family("gemini")
    for family, model in (("anthropic", "anthropic/claude-haiku-4-5-20251001"),
                          ("openai", "openai/gpt-5.6-terra"),
                          ("xai", "xai/grok-4.6")):
        assert litellm.token_counter(model=model, text=retired) >= \
            cache_minimum_for_family(family), f"{family} should still clear it"


def test_gemini_is_sized_above_its_measured_minimum_not_its_documented_one() -> None:
    """R-028: the documented 4,096 is necessary, not sufficient. A block sized
    to the docs would pass every offline test and cache nothing live."""
    assert cache_minimum_for_family("gemini") == 6109
    assert _CACHE_PARAGRAPHS["gemini"] > _CACHE_PARAGRAPHS["anthropic"]


def test_an_undeclared_family_falls_back_to_the_largest_never_the_smallest() -> None:
    """Oversized costs a little more and still demonstrates caching; undersized
    demonstrates nothing at all, silently. Never silently undersized."""
    assert cache_paragraphs_for("mistral") == max(_CACHE_PARAGRAPHS.values())
    assert cache_minimum_for_family("mistral") == max(_CACHE_MINIMUMS.values())


def test_each_familys_demo_uses_its_own_block() -> None:
    from smoke_proves import cache_block_for

    blocks = {family: cache_block_for(family) for family in _CACHE_PARAGRAPHS}
    assert len(blocks["gemini"]) > len(blocks["anthropic"])
    assert blocks["anthropic"] == blocks["openai"] == blocks["xai"]


def test_no_single_shared_cache_block_constant_survives() -> None:
    """R-028 retires it by name: a module-level constant is what made the
    undersizing invisible, since nothing named a family at the call site."""
    import smoke_proves

    assert not hasattr(smoke_proves, "CACHE_SYSTEM_BLOCK")


def test_the_xai_note_records_blocks_not_a_floor() -> None:
    """R-028 correction: 128 is the quantum, not a fixed system segment."""
    note = cache_note_for("xai")
    assert "128-TOKEN BLOCKS" in note
    assert "ASYNCHRONOUSLY" in note
    assert "floor" not in note.lower()


def test_the_openrouter_note_says_the_upstream_owns_caching() -> None:
    """P-010 contract 4: an aggregator cannot promise cache semantics."""
    note = cache_note_for("openrouter")
    assert "aggregator" in note
    assert "routed upstream" in note


def test_openrouter_is_deliberately_undeclared_and_gets_the_largest_block() -> None:
    """Contract 4: upstream minimums are unknowable in general, so the R-028
    fallback-to-largest rule is the correct behaviour rather than a gap."""
    assert "openrouter" not in _CACHE_PARAGRAPHS
    assert cache_paragraphs_for("openrouter") == max(_CACHE_PARAGRAPHS.values())
