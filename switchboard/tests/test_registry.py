"""Packet: P-002 — Switchboard Routing.

One job: test registry parsing and role resolution.

Version: 0.2.0
"""

from __future__ import annotations

from pathlib import Path

import pytest

from switchboard.registry import UnknownRoleError, load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry.toml"


def test_registry_file_parses_and_architect_resolves() -> None:
    registry = load_registry(REGISTRY_PATH)

    route = registry.resolve("architect")

    assert route.model == "anthropic/claude-sonnet-4-6"
    assert route.fallbacks == ["openai/gpt-4o"]
    assert route.max_tokens == 4096


def test_every_declared_role_is_present() -> None:
    registry = load_registry(REGISTRY_PATH)

    assert set(registry.roles) == {"architect", "judge", "floor_agent", "default"}


def test_unknown_role_resolves_to_default_entry() -> None:
    registry = load_registry(REGISTRY_PATH)

    route = registry.resolve("marketing_intern")

    assert route.model == registry.roles["default"].model
    assert route.max_tokens == 1024
    assert route.fallbacks == []


def test_unknown_role_without_default_raises_unknown_role_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "registry.toml"
    path.write_text(
        '[roles.architect]\nmodel = "a/b"\nfallbacks = []\nmax_tokens = 10\n',
        encoding="utf-8",
    )
    registry = load_registry(path)

    with pytest.raises(UnknownRoleError) as excinfo:
        registry.resolve("judge")

    assert "judge" in str(excinfo.value)


def test_entry_missing_model_field_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "registry.toml"
    path.write_text(
        "[roles.judge]\nfallbacks = []\nmax_tokens = 10\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    assert "judge" in str(excinfo.value)


def test_entry_with_non_list_fallbacks_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "registry.toml"
    path.write_text(
        '[roles.judge]\nmodel = "a/b"\nfallbacks = "nope"\nmax_tokens = 10\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    assert "judge" in str(excinfo.value)


def test_missing_registry_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "absent.toml")
