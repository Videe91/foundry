"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: test advance() — lawful transitions only, the signature chain, atomic
rewrite of the birth certificate, and the package's dumbness.

Version: 0.1.0
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from workspace import WorkspaceError, create_project, open_project
from workspace.skeleton import STATUSES, TRANSITIONS

SLUG = "demo-app"
NAME = "Demo App"
SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _project(tmp_path: Path):
    return create_project(SLUG, NAME, root=tmp_path)


def _walk_to(project, target: str, signature: str = "cortex") -> None:
    """Advance along the lawful path until the project reaches `target`."""
    seen = set()
    while project.status != target:
        assert project.status not in seen, f"looped without reaching {target}"
        seen.add(project.status)
        project.advance(TRANSITIONS[project.status][0], signature)


# --- the first gate ---------------------------------------------------------


def test_draft_to_intent_signed_advances_and_records(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.advance("intent_signed", "cortex")

    assert project.status == "intent_signed"
    entry = project.signatures[-1]
    assert entry["status"] == "intent_signed"
    assert entry["signature"] == "cortex"
    assert entry["at"]


def test_the_advance_is_durable_not_just_in_memory(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.advance("intent_signed", "cortex")

    reopened = open_project(SLUG, root=tmp_path)
    assert reopened.status == "intent_signed"
    assert reopened.signatures[-1]["signature"] == "cortex"


@pytest.mark.parametrize("signature", ["", "   ", "\n\t"])
def test_the_first_gate_demands_a_real_signature(
    tmp_path: Path, signature: str
) -> None:
    project = _project(tmp_path)
    with pytest.raises(WorkspaceError) as excinfo:
        project.advance("intent_signed", signature)
    assert "signature" in str(excinfo.value)
    assert project.status == "draft"
    assert open_project(SLUG, root=tmp_path).status == "draft"


def test_no_other_transition_is_gated_yet(tmp_path: Path) -> None:
    """Design doc 16.2 rule 4: structure now, gates as they are earned.

    An empty signature past the first gate is permitted TODAY — departments add
    their own checks as they are built. This test is the record of that, so the
    day a gate arrives, one assertion has to be deliberately changed.
    """
    project = _project(tmp_path)
    project.advance("intent_signed", "cortex")
    project.advance("building", "")
    assert project.status == "building"


# --- order ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frm", "to"),
    [("draft", "building"), ("draft", "live"), ("draft", "deployed"),
     ("intent_signed", "adversarial"), ("building", "deployed")],
)
def test_skipping_states_is_refused_naming_from_and_to(
    tmp_path: Path, frm: str, to: str
) -> None:
    project = _project(tmp_path)
    _walk_to(project, frm)
    with pytest.raises(WorkspaceError) as excinfo:
        project.advance(to, "cortex")
    message = str(excinfo.value)
    assert f"'{frm}'" in message and f"'{to}'" in message
    assert project.status == frm


def test_going_backwards_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _walk_to(project, "building")
    with pytest.raises(WorkspaceError):
        project.advance("draft", "cortex")


def test_an_unknown_status_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(WorkspaceError) as excinfo:
        project.advance("shipped", "cortex")
    assert "unknown status" in str(excinfo.value)


def test_every_declared_status_is_reachable_except_the_first(
    tmp_path: Path,
) -> None:
    """Discriminating: a transition map with an unreachable state would be a
    lifecycle nobody can complete, and no single-transition test would show it.
    """
    reachable = {"draft"}
    frontier = ["draft"]
    while frontier:
        for nxt in TRANSITIONS.get(frontier.pop(), ()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    assert reachable == set(STATUSES)


# --- the long-haul loop (design doc Section 13) -----------------------------


def test_live_to_amended_to_building_is_permitted(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _walk_to(project, "live")
    project.advance("amended", "cortex")
    project.advance("building", "cortex")
    assert project.status == "building"


def test_amended_to_deployed_is_refused(tmp_path: Path) -> None:
    """Amending re-enters the build; it does not shortcut back to shipped."""
    project = _project(tmp_path)
    _walk_to(project, "amended")
    with pytest.raises(WorkspaceError) as excinfo:
        project.advance("deployed", "cortex")
    assert "'amended'" in str(excinfo.value) and "'deployed'" in str(excinfo.value)


def test_the_loop_keeps_every_signing_of_a_repeated_state(
    tmp_path: Path,
) -> None:
    """Why signatures are an ARRAY of tables rather than a table keyed by
    status: the loop signs `building` twice, and a signature chain that
    forgets its earlier links is not a chain."""
    project = _project(tmp_path)
    _walk_to(project, "building", "first-pass")
    _walk_to(project, "amended", "first-pass")
    project.advance("building", "second-pass")

    buildings = [s for s in project.signatures if s["status"] == "building"]
    assert [s["signature"] for s in buildings] == ["first-pass", "second-pass"]


# --- atomicity --------------------------------------------------------------


def test_the_rewrite_leaves_no_partial_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _walk_to(project, "live")

    text = project.project_toml_path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["status"] == "live"
    assert data["id"] == project.id
    assert len(data["signatures"]) == len(STATUSES) - 2
    assert not list(project.root_dir.glob("*.tmp")), "a temp file was left behind"


def test_a_failed_advance_does_not_touch_the_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = project.project_toml_path.read_text(encoding="utf-8")
    with pytest.raises(WorkspaceError):
        project.advance("live", "cortex")
    assert project.project_toml_path.read_text(encoding="utf-8") == before


# --- the dumbness clause ----------------------------------------------------


def test_the_workspace_imports_no_litellm() -> None:
    """P-003's subprocess pattern: zero AI, asserted rather than promised."""
    probe = (
        "import sys\n"
        "import workspace\n"
        "from workspace import create_project, open_project\n"
        "sys.exit(1 if 'litellm' in sys.modules else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC_DIR)},
        check=False,
    )
    assert result.returncode == 0, f"litellm was imported.\n{result.stderr}"


def test_the_workspace_imports_no_switchboard() -> None:
    """The Workspace must not depend on the Switchboard — the global registry
    path is a parameter for exactly this reason."""
    probe = (
        "import sys\n"
        "import workspace\n"
        "from workspace import create_project, open_project\n"
        "bad = [m for m in sys.modules if m.startswith('switchboard')]\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC_DIR)},
        check=False,
    )
    assert result.returncode == 0, f"switchboard was imported.\n{result.stderr}"
