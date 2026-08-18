"""Packet: P-010 — Family Five: OpenRouter (aggregator).

One job: test load-time effort validation across families — that a family
declaring a ceiling rejects above it (R-025), and that an aggregator declaring
none is skipped entirely (R-031).

Split from test_registry.py under the R-017 precedent when the R-031 cases
pushed it past the 300-line ceiling. Per R-026 the split inherits its parent's
map entries.

Version: 0.11.0
"""

from __future__ import annotations

from pathlib import Path

import pytest

from switchboard.registry import load_registry


# --- P-010 contract 3 / R-031: an aggregator has no effort vocabulary -------


def _role_toml(model: str, effort: str) -> str:
    return (
        "[roles.judge]\n"
        f'model = "{model}"\n'
        "fallbacks = []\n"
        "max_tokens = 64000\n"
        f'effort = "{effort}"\n'
    )


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_an_openrouter_role_loads_at_every_effort_level(
    tmp_path: Path, effort: str
) -> None:
    """R-031: the vocabulary belongs to the ROUTED MODEL, not the family.

    DeepSeek V4 Pro documents high and xhigh; Kimi's is unpublished; hundreds of
    other routable models vary. A family-wide ceiling would be invented, and an
    invented ceiling either blocks a lawful config or licenses an unlawful one.
    So load-time validation skips this family exactly as it skips a family with
    no adapter, and effort compatibility is the human's per-model responsibility
    under R-012.
    """
    path = tmp_path / "registry.toml"
    path.write_text(_role_toml("openrouter/moonshotai/kimi-k3", effort), encoding="utf-8")
    assert load_registry(path).resolve("judge").effort == effort


def test_the_skip_is_the_absence_of_a_vocabulary_not_a_special_case() -> None:
    """The mechanism, pinned: OpenRouterAdapter declares no EFFORT_LEVELS, so
    effort_levels_for returns None and the existing guard has nothing to check.
    Nothing in load_registry names openrouter."""
    from switchboard.adapters import effort_levels_for
    import switchboard.registry as registry_module
    import inspect

    assert effort_levels_for("openrouter/moonshotai/kimi-k3") is None
    assert "openrouter" not in inspect.getsource(registry_module).lower()


@pytest.mark.parametrize(
    ("model", "effort", "family"),
    [
        ("gemini/gemini-3.7-flash", "xhigh", "gemini"),
        ("xai/grok-4.6", "max", "xai"),
    ],
)
def test_families_that_declare_a_ceiling_still_reject_above_it(
    tmp_path: Path, model: str, effort: str, family: str
) -> None:
    """The discriminating half: R-031 must not have widened the skip.

    If validation were skipped for everyone, this test would pass vacuously and
    R-025 would be dead. Each of these is a real ceiling breach.
    """
    path = tmp_path / "registry.toml"
    path.write_text(_role_toml(model, effort), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    message = str(excinfo.value)
    assert "judge" in message and family in message and effort in message


def test_anthropic_validation_is_unchanged(tmp_path: Path) -> None:
    """Anthropic accepts all five, so the same file that fails on gemini loads."""
    path = tmp_path / "registry.toml"
    path.write_text(_role_toml("anthropic/claude-opus-5", "max"), encoding="utf-8")
    assert load_registry(path).resolve("judge").effort == "max"
