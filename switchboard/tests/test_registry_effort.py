"""Packet: T-010 / R-035 — acceptance has three layers.

One job: test load-time effort validation across families — that a family
declaring a ceiling rejects above it (R-025), and that an aggregator declaring
none is skipped entirely (R-031).

Split from test_registry.py under the R-017 precedent when the R-031 cases
pushed it past the 300-line ceiling. Per R-026 the split inherits its parent's
map entries.

Version: 0.15.1
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
def test_an_openrouter_role_with_any_effort_is_rejected_at_load(
    tmp_path: Path, effort: str
) -> None:
    """R-035 narrows R-031, and the failure it prevents is total.

    R-031 was right that an aggregator has no LEVEL vocabulary — DeepSeek V4 Pro
    documents high and xhigh, Kimi's is unpublished, hundreds more vary. What it
    did not ask is whether the parameter can be SENT at all. LiteLLM's
    supported-params gate refuses `reasoning_effort` for the whole openrouter
    family, before any transformation runs, so such a role cannot make a single
    call — which is how T-010 killed a live run at PROVE 1.

    Every level fails, because the level was never the problem.
    """
    path = tmp_path / "registry.toml"
    path.write_text(_role_toml("openrouter/moonshotai/kimi-k3", effort), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    message = str(excinfo.value)
    assert "judge" in message and "openrouter" in message
    assert "reasoning_effort" in message, "the gate must be named as the reason"


def test_an_openrouter_role_without_effort_loads_fine(tmp_path: Path) -> None:
    """The other half of the pair: the family is not banned, the parameter is."""
    path = tmp_path / "registry.toml"
    path.write_text(
        '[roles.judge]\nmodel = "openrouter/moonshotai/kimi-k3"\n'
        "fallbacks = []\nmax_tokens = 64000\n",
        encoding="utf-8",
    )
    assert load_registry(path).resolve("judge").effort is None


def test_r031_survives_where_it_was_right(tmp_path: Path) -> None:
    """No LEVEL ceiling was invented for the aggregator, then or now.

    The rejection above cites the parameter gate, never a list of permitted
    levels — so if LiteLLM ever forwards reasoning_effort for openrouter, this
    reverts to R-031's original behaviour without anyone choosing a vocabulary.
    """
    from switchboard.adapters import effort_levels_for

    assert effort_levels_for("openrouter/moonshotai/kimi-k3") is None


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


# --- P-016: a role may only be told to search if its family can -------------


def _search_toml(model: str) -> str:
    return (
        "[roles.judge]\n"
        f'model = "{model}"\n'
        "fallbacks = []\n"
        "max_tokens = 64000\n"
        "web_search = true\n"
    )


@pytest.mark.parametrize(
    "model",
    ["openai/gpt-5.6-terra", "gemini/gemini-3.7-flash", "xai/grok-4.6",
     "openrouter/moonshotai/kimi-k3"],
)
def test_web_search_on_a_family_without_it_fails_at_load(
    tmp_path: Path, model: str
) -> None:
    """R-035 extended: capability checked where it is knowable. A role that
    cannot search must not discover it mid-run."""
    path = tmp_path / "registry.toml"
    path.write_text(_search_toml(model), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    message = str(excinfo.value)
    assert "judge" in message
    assert model.split("/", 1)[0] in message
    assert "search" in message


def test_web_search_on_anthropic_loads(tmp_path: Path) -> None:
    """The other half of the pair."""
    path = tmp_path / "registry.toml"
    path.write_text(_search_toml("anthropic/claude-sonnet-5"), encoding="utf-8")
    route = load_registry(path).resolve("judge")
    assert route.web_search is True
    assert route.web_search_max_uses == 3


def test_a_non_searching_role_on_any_family_loads(tmp_path: Path) -> None:
    """Discriminating: the check must fire on the flag, not on the family."""
    path = tmp_path / "registry.toml"
    path.write_text(
        '[roles.judge]\nmodel = "openrouter/moonshotai/kimi-k3"\n'
        "fallbacks = []\nmax_tokens = 64000\n", encoding="utf-8")
    assert load_registry(path).resolve("judge").web_search is False
