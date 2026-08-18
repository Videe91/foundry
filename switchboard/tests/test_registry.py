"""Packet: P-004 — Family One: Anthropic Adapter (T-001 amendment).

One job: test registry parsing and role resolution.

Per R-014, this file asserts STRUCTURE, never VALUES. The shipped
registry.toml is user configuration (R-012) — the human may change any
role→model assignment at any time, and doing so must never turn this suite
red. Behaviour is therefore proven against synthetic fixtures written to
tmp_path; the real file is only checked for well-formedness.

Version: 0.4.0
"""

from __future__ import annotations

from pathlib import Path

import pytest

from switchboard.registry import ALLOWED_EFFORTS, UnknownRoleError, load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry.toml"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "registry.toml"
    path.write_text(body, encoding="utf-8")
    return path


# --- the shipped file: structure only, never values -----------------------


def test_the_shipped_registry_parses() -> None:
    registry = load_registry(REGISTRY_PATH)

    assert registry.roles, "the shipped registry declares at least one role"


def test_every_shipped_entry_is_well_formed() -> None:
    registry = load_registry(REGISTRY_PATH)

    for role, route in registry.roles.items():
        assert isinstance(route.model, str) and route.model, (
            f"role '{role}' must name a non-empty model"
        )
        assert isinstance(route.fallbacks, list), f"role '{role}' fallbacks is a list"
        assert all(isinstance(item, str) and item for item in route.fallbacks), (
            f"role '{role}' fallbacks are non-empty strings"
        )
        assert isinstance(route.max_tokens, int) and route.max_tokens > 0, (
            f"role '{role}' must set a positive max_tokens"
        )


def test_any_shipped_effort_is_a_valid_level() -> None:
    """R-014: the VALUES are the human's business; only validity is asserted."""
    registry = load_registry(REGISTRY_PATH)

    for role, route in registry.roles.items():
        if route.effort is not None:
            assert route.effort in ALLOWED_EFFORTS, (
                f"role '{role}' sets an effort outside the allowed levels"
            )


def test_the_shipped_registry_declares_a_default_role() -> None:
    registry = load_registry(REGISTRY_PATH)

    assert "default" in registry.roles


# --- behaviour: synthetic fixtures, so config edits are never load-bearing -


def test_a_known_role_resolves_to_its_own_entry(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[roles.architect]\nmodel = "vendor/model-a"\n'
        'fallbacks = ["vendor/model-b"]\nmax_tokens = 100\n'
        '\n[roles.default]\nmodel = "vendor/model-z"\n'
        "fallbacks = []\nmax_tokens = 10\n",
    )
    registry = load_registry(path)

    route = registry.resolve("architect")

    assert route.model == "vendor/model-a"
    assert route.fallbacks == ["vendor/model-b"]
    assert route.max_tokens == 100


def test_an_unknown_role_resolves_to_the_default_entry(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[roles.architect]\nmodel = "vendor/model-a"\nfallbacks = []\n'
        "max_tokens = 100\n"
        '\n[roles.default]\nmodel = "vendor/model-z"\nfallbacks = []\n'
        "max_tokens = 10\n",
    )
    registry = load_registry(path)

    route = registry.resolve("no-such-role")

    assert route is registry.roles["default"]


def test_an_unknown_role_without_a_default_raises_naming_the_role(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        '[roles.architect]\nmodel = "vendor/model-a"\nfallbacks = []\n'
        "max_tokens = 100\n",
    )
    registry = load_registry(path)

    with pytest.raises(UnknownRoleError) as excinfo:
        registry.resolve("judge")

    assert "judge" in str(excinfo.value)


def test_an_entry_missing_model_raises_naming_the_role(tmp_path: Path) -> None:
    path = _write(tmp_path, "[roles.judge]\nfallbacks = []\nmax_tokens = 10\n")

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    assert "judge" in str(excinfo.value)


def test_an_entry_with_non_list_fallbacks_raises_naming_the_role(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        '[roles.judge]\nmodel = "vendor/model-a"\nfallbacks = "nope"\n'
        "max_tokens = 10\n",
    )

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    assert "judge" in str(excinfo.value)


def test_a_missing_registry_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "absent.toml")


def test_a_valid_effort_is_parsed_onto_the_route(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[roles.architect]\nmodel = "vendor/model-a"\nfallbacks = []\n'
        'max_tokens = 100\neffort = "high"\n',
    )

    assert load_registry(path).roles["architect"].effort == "high"


def test_an_omitted_effort_stays_none(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[roles.architect]\nmodel = "vendor/model-a"\nfallbacks = []\n'
        "max_tokens = 100\n",
    )

    assert load_registry(path).roles["architect"].effort is None


def test_an_invalid_effort_raises_naming_the_role_and_the_value(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        '[roles.judge]\nmodel = "vendor/model-a"\nfallbacks = []\n'
        'max_tokens = 100\neffort = "turbo"\n',
    )

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    message = str(excinfo.value)
    assert "judge" in message
    assert "turbo" in message


@pytest.mark.parametrize("level", ALLOWED_EFFORTS)
def test_every_allowed_level_is_accepted(tmp_path: Path, level: str) -> None:
    path = _write(
        tmp_path,
        f'[roles.architect]\nmodel = "vendor/model-a"\nfallbacks = []\n'
        f'max_tokens = 100\neffort = "{level}"\n',
    )

    assert load_registry(path).roles["architect"].effort == level
