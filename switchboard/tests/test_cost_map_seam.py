"""Packet: P-010 — Family Five: OpenRouter (aggregator).

One job: test the R-023 priced-lookup seam — that a model string resolves in the
cost map however many provider prefixes it carries.

Written BEFORE the adapter, per P-010 contract 1, and it failed: stripping
exactly one prefix was an assumption no one had tested on an aggregator, whose
strings carry two.

Split from test_smoke_families.py under R-017 when that file reached the ceiling;
per R-026 the split inherits its parent's map entries.

Version: 0.11.0
"""

from __future__ import annotations

from pathlib import Path

from conftest import FakeCompletion
from smoke import ping_model
from smoke_families import _cost_entry, input_price_of, is_priced
from switchboard.registry import load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry.toml"


# --- P-010 contract 1: the R-023 double-prefix seam -------------------------
#
# OpenRouter is an aggregator, so its model strings carry TWO prefixes:
# `openrouter/moonshotai/kimi-k3`. The priced lookup stripped exactly one, which
# is an assumption no one had tested on a double-prefixed family.


def test_the_cost_map_keys_openrouter_models_with_the_full_prefix() -> None:
    """Observed keying in litellm 1.97.0, structure not values (R-014)."""
    import litellm

    keys = [k for k in litellm.model_cost if k.startswith("openrouter/")]
    assert keys, "no openrouter keys at all — the seam premise changed"
    assert all(k.count("/") >= 2 for k in keys), "expected org-qualified slugs"


def test_a_double_prefixed_model_priced_only_by_its_bare_slug_is_found() -> None:
    """The seam, demonstrated on a real entry rather than a synthetic one.

    Routing a model we already ship through OpenRouter is an ordinary thing for
    a human to do under R-012. The map prices it bare (`claude-opus-5`), so a
    lookup that strips exactly one prefix reaches `anthropic/claude-opus-5`,
    misses, and reports UNPRICED with cost=None on every receipt.
    """
    import litellm

    assert "claude-opus-5" in litellm.model_cost
    assert "anthropic/claude-opus-5" not in litellm.model_cost
    assert is_priced("openrouter/anthropic/claude-opus-5")


def test_progressive_stripping_stops_at_the_first_hit() -> None:
    """Full string first, then each progressively-stripped form (contract 1)."""
    import litellm

    entry = _cost_entry("openrouter/anthropic/claude-opus-5")
    assert entry == litellm.model_cost["claude-opus-5"]


def test_single_prefix_families_are_unchanged_by_the_fix() -> None:
    """Discriminating: the four certified families must keep resolving."""
    for model in ("anthropic/claude-opus-5", "openai/gpt-5.6-terra",
                  "gemini/gemini-3.7-flash", "xai/grok-4.6"):
        assert is_priced(model), model


def test_a_model_absent_from_the_map_is_still_unpriced() -> None:
    """Progressive stripping must not invent a hit — UNPRICED is the honest
    answer, and P-010's four targets are all absent from litellm 1.97.0."""
    for model in ("openrouter/moonshotai/kimi-k3",
                  "openrouter/moonshotai/kimi-k2.7-code",
                  "openrouter/deepseek/deepseek-v4-pro-0813",
                  "openrouter/deepseek/deepseek-v4-flash-0731"):
        assert not is_priced(model), f"{model} unexpectedly priced"
    assert not is_priced("vendor/org/not-a-real-model")


def test_the_lookup_answers_structurally_for_every_shipped_model() -> None:
    """R-022-style: the prefix-stripping lookup works against the real map.

    This test used to assert that every shipped model IS priced, under a
    docstring claiming "structure, not values". That was the tell: being priced
    is a VALUE of the human's config, not a structural property, and R-012 lets
    the human route anywhere. OpenRouter's models are absent from litellm
    1.97.0's map under every form, so the old assertion made a lawful registry
    edit fail the suite — the R-014 corollary again, config-independence holding
    in every dimension and not just the asserted one.

    What is genuinely structural: the lookup answers, and answers coherently.
    """
    registry = load_registry(REGISTRY_PATH)
    for name, route in registry.roles.items():
        for model in (route.model, *route.fallbacks):
            price = input_price_of(model)
            assert price is None or (isinstance(price, float) and price > 0), (
                f"{name}: {model} priced incoherently ({price!r})"
            )
            assert is_priced(model) is (price is not None), (
                f"{name}: {model} — is_priced and input_price_of disagree"
            )


def test_an_unpriced_shipped_model_is_surfaced_rather_than_hidden() -> None:
    """Where the typo-catching value actually belongs.

    Dropping "everything is priced" must not mean nobody notices an unpriced
    model. The ping table's priced column is the surface, and it fires for the
    same models this test finds — so a typo'd slug still shows up loudly at the
    one moment a human is looking.
    """
    registry = load_registry(REGISTRY_PATH)
    unpriced = [
        model
        for route in registry.roles.values()
        for model in (route.model, *route.fallbacks)
        if not is_priced(model)
    ]
    # Not asserted as a count or a list — the human may repoint any role. What
    # is asserted is that whatever is unpriced is REPORTED as unpriced.
    for model in unpriced:
        assert ping_model(model, FakeCompletion()).priced is False
