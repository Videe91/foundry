"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: test persistence — that an interview round-trips exactly, is written
atomically, resumes after a crash, and refuses to quietly restart itself.

Also the seam guards, both directions: `intent` imports neither switchboard nor
litellm, and `workspace` stays a leaf.

Version: 0.1.0
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from intent import (
    Contradiction,
    IntentStoreError,
    ScribeUpdate,
    load_state,
    new_state,
    run_turn,
    save_state,
    state_path,
)
from intent.store import STATE_FILENAME
from workspace import create_project

INTENT_SRC = Path(__file__).resolve().parents[1] / "src"
WORKSPACE_SRC = Path(__file__).resolve().parents[2] / "workspace" / "src"


class Fake:
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return "next question?"


class NoopScribe:
    def __call__(self, *args: Any, **kwargs: Any) -> ScribeUpdate:
        return ScribeUpdate()


def _project(tmp_path: Path):
    return create_project("demo-app", "Demo App", root=tmp_path)


def _populated(slug: str = "demo-app"):
    state = new_state(slug)
    state.transcript.append(
        __import__("intent").Turn(role="user", content="first", attachments=["/a.pdf"])
    )
    state.transcript.append(
        __import__("intent").Turn(role="interviewer", content="second")
    )
    state.boxes["goal"].content = {"summary": "a tool",
                                   "victory_conditions": ["ships", "used"]}
    state.boxes["goal"].status = "confirmed"
    state.boxes["goal"].proposed_by = "user"
    state.contradictions.append(
        Contradiction(box_key="users", earlier="X", later="Y", surfaced=True)
    )
    state.turn_count = 7
    return state


# --- the round trip ---------------------------------------------------------


def test_save_then_load_returns_an_identical_interview(tmp_path: Path) -> None:
    project = _project(tmp_path)
    original = _populated()
    save_state(project, original)

    restored = load_state(project)
    assert restored is not None
    assert restored.model_dump() == original.model_dump()


def test_the_transcript_keeps_its_order_and_its_attachments(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    save_state(project, _populated())
    restored = load_state(project)

    assert [t.role for t in restored.transcript] == ["user", "interviewer"]
    assert restored.transcript[0].attachments == ["/a.pdf"]


def test_contradictions_and_turn_count_survive(tmp_path: Path) -> None:
    project = _project(tmp_path)
    save_state(project, _populated())
    restored = load_state(project)

    assert restored.turn_count == 7
    assert len(restored.contradictions) == 1
    assert restored.contradictions[0].surfaced is True
    assert restored.contradictions[0].resolved is False


def test_an_absent_interview_is_none_not_an_error(tmp_path: Path) -> None:
    assert load_state(_project(tmp_path)) is None


# --- where it lives ---------------------------------------------------------


def test_the_state_lands_under_the_projects_intent_dir(tmp_path: Path) -> None:
    """The path is asked for, never computed — the Workspace owns layout."""
    project = _project(tmp_path)
    written = save_state(project, new_state("demo-app"))

    assert written == project.intent_dir / STATE_FILENAME
    assert written.parent == project.intent_dir
    assert state_path(project) == written


# --- atomicity --------------------------------------------------------------


def test_no_temp_file_is_left_behind(tmp_path: Path) -> None:
    project = _project(tmp_path)
    for _ in range(3):
        save_state(project, _populated())
    assert not list(project.intent_dir.glob("*.tmp"))


def test_a_failed_write_leaves_the_previous_interview_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conversation a founder will not want to have twice must not be lost to
    a half-written file. The rename is the commit point."""
    project = _project(tmp_path)
    save_state(project, _populated())
    before = state_path(project).read_text(encoding="utf-8")

    def explode(_src: Any, _dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    doomed = _populated()
    doomed.turn_count = 999
    with pytest.raises(OSError):
        save_state(project, doomed)

    assert state_path(project).read_text(encoding="utf-8") == before
    assert load_state(project).turn_count == 7


def test_every_saved_state_is_complete_json(tmp_path: Path) -> None:
    project = _project(tmp_path)
    save_state(project, _populated())
    payload = json.loads(state_path(project).read_text(encoding="utf-8"))
    assert set(payload) == {"slug", "boxes", "transcript", "contradictions",
                            "turn_count"}


# --- a broken interview is a finding ---------------------------------------


def test_corrupt_json_names_the_file_and_never_reinitialises(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    save_state(project, _populated())
    state_path(project).write_text("{not json", encoding="utf-8")

    with pytest.raises(IntentStoreError) as excinfo:
        load_state(project)
    assert str(state_path(project)) in str(excinfo.value)


def test_valid_json_of_the_wrong_shape_is_also_a_finding(
    tmp_path: Path,
) -> None:
    """Discriminating: parsing is not understanding. A JSON file that is not an
    interview must not load as an empty one."""
    project = _project(tmp_path)
    state_path(project).parent.mkdir(parents=True, exist_ok=True)
    state_path(project).write_text('{"hello": "world"}', encoding="utf-8")

    with pytest.raises(IntentStoreError) as excinfo:
        load_state(project)
    assert str(state_path(project)) in str(excinfo.value)


# --- resume after a crash ---------------------------------------------------


def test_an_interview_resumes_exactly_where_it_stopped(tmp_path: Path) -> None:
    project = _project(tmp_path)
    state = new_state("demo-app")
    scribe = NoopScribe()

    state, _ = run_turn(state, "first thing", Fake(), scribe, project=project)
    state, _ = run_turn(state, "second thing", Fake(), scribe, project=project)

    resumed = load_state(project)  # as if the process had died here
    assert resumed.turn_count == 2
    assert [t.content for t in resumed.transcript] == [
        "first thing", "next question?", "second thing", "next question?"
    ]

    resumed, _ = run_turn(resumed, "third thing", Fake(), scribe, project=project)
    assert resumed.turn_count == 3
    assert load_state(project).turn_count == 3


def test_the_engine_saves_after_every_turn_not_only_at_the_end(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    state = new_state("demo-app")
    run_turn(state, "one", Fake(), NoopScribe(), project=project)
    assert load_state(project).turn_count == 1


def test_without_a_project_the_engine_writes_nothing(tmp_path: Path) -> None:
    """Discriminating: the engine is testable offline precisely because
    persistence is opt-in."""
    project = _project(tmp_path)
    run_turn(new_state("demo-app"), "one", Fake(), NoopScribe())
    assert load_state(project) is None


# --- the seam, both directions ---------------------------------------------


def _probe(code: str, path: list[Path]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in path)},
        check=False,
    )


def test_intent_imports_neither_switchboard_nor_litellm() -> None:
    """The brains arrive as callables, by shape. If either name appears in
    sys.modules, the engine has stopped being offline."""
    result = _probe(
        "import sys\n"
        "import intent\n"
        "from intent import run_turn, new_state, save_state\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "('switchboard', 'litellm')]\n"
        "sys.exit(1 if bad else 0)\n",
        [INTENT_SRC, WORKSPACE_SRC],
    )
    assert result.returncode == 0, f"a forbidden import leaked.\n{result.stderr}"


def test_workspace_stays_a_leaf() -> None:
    """The dependency runs one way, downward: intent may know about projects;
    a project must never know about interviews."""
    result = _probe(
        "import sys\n"
        "import workspace\n"
        "from workspace import create_project, MeterRouter\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "('intent', 'switchboard', 'litellm')]\n"
        "sys.exit(1 if bad else 0)\n",
        [WORKSPACE_SRC, INTENT_SRC],
    )
    assert result.returncode == 0, f"workspace stopped being a leaf.\n{result.stderr}"
