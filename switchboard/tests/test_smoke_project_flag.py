"""Packet: P-012 — The meter learns addresses.

One job: test `smoke.py --project <slug>` — that receipts land in that
project's ledger, that the project is created once and reused after, and that
a run WITHOUT the flag is unchanged and never touches the workspace at all.

The seam under test: no Switchboard source changed to make this work. A
MeterRouter is duck-typed into the meter slot, because `.record(...)` is the
whole of what route_call asks of a meter.

Split as its own file under R-017; per R-026 it inherits test_smoke_wiring's
map entries.

Version: 0.12.0
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from conftest import FREE

import smoke
from test_smoke_wiring import SmokeFake

WORKSPACE_SRC = Path(__file__).resolve().parents[2] / "workspace" / "src"
if str(WORKSPACE_SRC) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_SRC))

SLUG = "demo-project"


@pytest.fixture
def smoke_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake litellm, a tmp global ledger, and a tmp workspace root."""
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = SmokeFake()
    fake_litellm.completion_cost = lambda *_a, **_k: 0.0001
    fake_litellm.token_counter = lambda **_k: 4142
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    monkeypatch.setattr(smoke, "load_env", lambda: None)
    monkeypatch.setattr(smoke, "METER_PATH", tmp_path / "global-meter.jsonl")
    monkeypatch.setattr(smoke, "MATRIX_PATH", tmp_path / "matrix-runs.md")
    monkeypatch.setenv("FOUNDRY_WORKSPACE_ROOT", str(tmp_path / "projects"))
    # smoke's tagged project is module state; restore it so ordering cannot
    # leak a slug from one test into another.
    import smoke_proves

    monkeypatch.setattr(smoke_proves, "_TAGGED_PROJECT", smoke_proves.SMOKE_PROJECT)
    return tmp_path


def _lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _project_meter(root: Path) -> Path:
    return root / "projects" / SLUG / "ledger" / "meter.jsonl"


# --- with the flag ----------------------------------------------------------


def test_the_flag_routes_every_receipt_into_the_project_ledger(
    smoke_env: Path, capsys: pytest.CaptureFixture
) -> None:
    assert smoke.main(["--project", SLUG]) == 0
    receipts = _lines(_project_meter(smoke_env))

    assert receipts, "no receipts reached the project ledger"
    assert all(r["tags"]["project_id"] == SLUG for r in receipts)
    assert _lines(smoke_env / "global-meter.jsonl") == [], "global ledger was written"


def test_the_flag_creates_the_project_when_absent(
    smoke_env: Path, capsys: pytest.CaptureFixture
) -> None:
    assert not (smoke_env / "projects" / SLUG).exists()
    smoke.main(["--project", SLUG])
    assert (smoke_env / "projects" / SLUG / "project.toml").is_file()
    assert "(created)" in capsys.readouterr().out


def test_a_second_run_reuses_the_project_rather_than_failing(
    smoke_env: Path, capsys: pytest.CaptureFixture
) -> None:
    """create_project refuses an existing directory, so a naive implementation
    would blow up on the second run — the common case, not the rare one."""
    assert smoke.main(["--project", SLUG]) == 0
    first = len(_lines(_project_meter(smoke_env)))

    assert smoke.main(["--project", SLUG]) == 0
    out = capsys.readouterr().out
    assert "(existing)" in out
    assert len(_lines(_project_meter(smoke_env))) > first, "second run appended nothing"


def test_the_closing_line_names_the_ledger_and_counts_the_records(
    smoke_env: Path, capsys: pytest.CaptureFixture
) -> None:
    smoke.main(["--project", SLUG])
    out = capsys.readouterr().out
    count = len(_lines(_project_meter(smoke_env)))
    assert "Receipts appended to" in out
    assert str(_project_meter(smoke_env)) in out
    assert f"({count} records)" in out


def test_the_flag_composes_with_matrix(
    smoke_env: Path, capsys: pytest.CaptureFixture
) -> None:
    assert smoke.main(["--matrix", "--project", SLUG]) == 0
    assert _lines(_project_meter(smoke_env))
    assert "Receipts appended to" in capsys.readouterr().out


def test_a_missing_slug_is_refused_rather_than_guessed(smoke_env: Path) -> None:
    with pytest.raises(SystemExit):
        smoke.main(["--project"])


# --- without the flag: byte-identical to before -----------------------------


def test_no_flag_writes_the_global_ledger_and_never_touches_the_workspace(
    smoke_env: Path, capsys: pytest.CaptureFixture
) -> None:
    """Contract 5: without the flag the run is unchanged, and the project
    machinery is never invoked — not merely unused."""
    assert smoke.main([]) == 0

    assert _lines(smoke_env / "global-meter.jsonl"), "global ledger not written"
    assert not (smoke_env / "projects").exists(), "a workspace was created"
    out = capsys.readouterr().out
    assert "Meter records appended to" in out
    assert "PROJECT:" not in out


def test_no_flag_leaves_the_tagged_project_at_its_default(
    smoke_env: Path,
) -> None:
    import smoke_proves

    smoke.main([])
    assert smoke_proves.tagged_project() == smoke_proves.SMOKE_PROJECT
    receipts = _lines(smoke_env / "global-meter.jsonl")
    assert all(r["tags"]["project_id"] == smoke_proves.SMOKE_PROJECT for r in receipts)


# --- the seam ---------------------------------------------------------------


def test_the_switchboard_source_knows_nothing_about_projects() -> None:
    """The point of the packet, asserted rather than trusted.

    If `workspace` or `project` appears in the Switchboard's src/, the seam has
    leaked and the two packages are no longer independent.
    """
    src = Path(smoke.__file__).resolve().parent / "src" / "switchboard"
    for module in sorted(src.glob("*.py")):
        text = module.read_text(encoding="utf-8").lower()
        assert "workspace" not in text, f"{module.name} mentions the workspace"
        assert "create_project" not in text, f"{module.name} knows about projects"
