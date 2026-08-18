"""Packet: P-010 — Family Five: OpenRouter (aggregator).

One job: prove no redirect slug reaches the repository.

`kimi-latest`, `deepseek-v4-flash-latest`, and any `-latest` pattern auto-
redirect to whatever is newest — a silent model swap in production, where the
receipt names a slug and the work was done by something else. Pinned explicit
slugs only.

This is the gemini-2.5-pro lesson inverted: there a pin dodged a deprecation;
here a pin dodges an UNREQUESTED UPGRADE, which is the harder one to notice
because nothing fails.

Version: 0.11.0
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent

# A model slug ending in -latest. Matched inside quotes so ordinary prose in a
# docstring ("the latest run") cannot trip it, and neither can this file.
_REDIRECT = re.compile(r"""["'][\w./:-]+-latest["']""")

_SCANNED_SUFFIXES = (".py", ".toml", ".md", ".example")
_SKIP_DIRS = {".venv", "__pycache__", ".git", ".pytest_cache", "node_modules"}


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in _SCANNED_SUFFIXES:
            files.append(path)
    for name in (".env.example",):
        candidate = PROJECT_ROOT / name
        if candidate.is_file():
            files.append(candidate)
    return files


def test_the_scan_actually_reaches_the_shipped_registry() -> None:
    """A grep-style guard that scans nothing passes vacuously. Prove reach."""
    scanned = {p.name for p in _scanned_files()}
    assert "registry.toml" in scanned
    assert "smoke.py" in scanned
    assert ".env.example" in scanned


def test_the_pattern_catches_a_real_redirect_slug() -> None:
    """Discriminating: prove the matcher matches before trusting its silence."""
    assert _REDIRECT.search('model = "openrouter/moonshotai/kimi-latest"')
    assert _REDIRECT.search("'deepseek/deepseek-v4-flash-latest'")
    assert _REDIRECT.search('"xai/grok-3-latest"')


def test_the_pattern_does_not_fire_on_ordinary_prose() -> None:
    assert not _REDIRECT.search("reporting the latest observed values")
    assert not _REDIRECT.search('model = "openrouter/moonshotai/kimi-k3"')


@pytest.mark.parametrize("path", _scanned_files(), ids=lambda p: p.name)
def test_no_redirect_slug_anywhere_in_the_repository(path: Path) -> None:
    """Fixtures, tests, comments, suggestions — everywhere (P-010 forbidden)."""
    if path.name == Path(__file__).name:
        return  # this file names them on purpose, to prove the matcher works
    hits = _REDIRECT.findall(path.read_text(encoding="utf-8", errors="ignore"))
    assert not hits, f"redirect slug(s) in {path}: {hits}"
