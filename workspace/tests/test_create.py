"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: test create_project — the skeleton it stamps, the birth certificate it
writes, and the slugs it refuses.

All offline, all against tmp_path roots. No keys, no network, no AI.

Version: 0.1.0
"""

from __future__ import annotations

import tomllib
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from workspace import WorkspaceError, create_project
from workspace.factory import DEFAULT_ROOT_NAME
from workspace.skeleton import DIRECTORIES, FILES, GITKEEP, NEVER_CREATED

REPO_ROOT = Path(__file__).resolve().parents[2]

SLUG = "demo-app"
NAME = "Demo App"


def test_every_dictionary_path_exists_after_create(tmp_path: Path) -> None:
    """The skeleton is complete on the first day, with one exception."""
    project = create_project(SLUG, NAME, root=tmp_path)
    for prop in (*DIRECTORIES, *FILES):
        path = getattr(project, prop)
        if FILES.get(prop) in NEVER_CREATED:
            continue
        assert path.exists(), f"{prop} was not created: {path}"


def test_registry_toml_is_deliberately_absent(tmp_path: Path) -> None:
    """Its absence IS the design: absent means "inherit the global brains".

    An empty registry.toml would not be a harmless placeholder — it would
    override the global with nothing (design doc 16.2 rule 2, R-012).
    """
    project = create_project(SLUG, NAME, root=tmp_path)
    assert not project.registry_path.exists()
    assert "registry.toml" in NEVER_CREATED


def test_directories_are_directories_and_files_are_files(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    for prop in DIRECTORIES:
        assert getattr(project, prop).is_dir(), prop
    for prop, relative in FILES.items():
        if relative in NEVER_CREATED:
            continue
        assert getattr(project, prop).is_file(), prop


def test_project_toml_round_trips(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    data = tomllib.loads(project.project_toml_path.read_text(encoding="utf-8"))

    assert uuid.UUID(data["id"]).version == 4
    assert data["slug"] == SLUG
    assert data["name"] == NAME
    assert data["status"] == "draft"
    assert data.get("signatures", []) == []

    created = datetime.fromisoformat(data["created"])
    assert created.tzinfo is not None
    assert created.utcoffset().total_seconds() == 0


def test_each_project_gets_its_own_id(tmp_path: Path) -> None:
    first = create_project("one", "One", root=tmp_path)
    second = create_project("two", "Two", root=tmp_path)
    assert first.id != second.id


@pytest.mark.parametrize(
    "slug", ["MyApp", "my_app", "-x", "", "my app", "app/", "Ünicode"]
)
def test_bad_slugs_are_rejected_naming_the_offense(
    tmp_path: Path, slug: str
) -> None:
    with pytest.raises(ValueError) as excinfo:
        create_project(slug, NAME, root=tmp_path)
    message = str(excinfo.value)
    assert "kebab" in message or "empty" in message


@pytest.mark.parametrize("slug", ["demo-app", "app2", "a", "x-y-z", "0-start"])
def test_good_slugs_are_accepted(tmp_path: Path, slug: str) -> None:
    assert create_project(slug, NAME, root=tmp_path).slug == slug


def test_creating_over_an_existing_directory_is_refused(tmp_path: Path) -> None:
    create_project(SLUG, NAME, root=tmp_path)
    with pytest.raises(WorkspaceError) as excinfo:
        create_project(SLUG, NAME, root=tmp_path)
    assert "existing directory" in str(excinfo.value)


def test_an_existing_but_empty_directory_is_still_refused(
    tmp_path: Path,
) -> None:
    """Refusing only non-empty directories would let a half-made project be
    silently completed — the repair open_project is forbidden to do."""
    (tmp_path / SLUG).mkdir()
    with pytest.raises(WorkspaceError):
        create_project(SLUG, NAME, root=tmp_path)


def test_empty_directories_carry_a_gitkeep(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    for prop in DIRECTORIES:
        directory = getattr(project, prop)
        contents = [p.name for p in directory.iterdir()]
        if contents == [GITKEEP]:
            continue
        assert contents, f"{prop} is empty and has no {GITKEEP}"


def test_a_populated_directory_gets_no_gitkeep(tmp_path: Path) -> None:
    """Discriminating: a blanket .gitkeep everywhere would prove nothing."""
    project = create_project(SLUG, NAME, root=tmp_path)
    assert not (project.ledger_dir / GITKEEP).exists()
    assert (project.tickets_dir / GITKEEP).exists()


def test_the_build_log_records_the_birth(tmp_path: Path) -> None:
    project = create_project(SLUG, NAME, root=tmp_path)
    text = project.build_log_path.read_text(encoding="utf-8")
    assert NAME in text
    assert SLUG in text
    assert "draft" in text


# --- the git law (design doc 16.3, P-011 contract 7) -----------------------


def test_the_default_workspace_root_is_gitignored() -> None:
    """Projects are deliverables, not factory source.

    create_project stamps directories into the workspace root, so the moment
    that root is inside the repo, the law has to hold — nothing a department
    produces for a project may reach the factory's history.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")

    # Probe paths INSIDE the root, never the bare name. The rule is
    # `projects/` — directory-only, which is correct — and git can only match a
    # bare `projects` when the directory happens to exist on disk. Since the
    # root is untracked, that made the check pass locally and fail on a fresh
    # clone: a test whose result depended on local state rather than on the
    # rule it claims to verify.
    for probe in (
        f"{DEFAULT_ROOT_NAME}/anything-at-all",
        f"{DEFAULT_ROOT_NAME}/some-project/src/main.py",
        f"{DEFAULT_ROOT_NAME}/some-project/ledger/meter.jsonl",
    ):
        result = subprocess.run(
            ["git", "check-ignore", probe],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, f"{probe} is NOT gitignored"


def test_the_law_is_specific_and_not_a_blanket_ignore() -> None:
    """Discriminating: an over-broad rule would pass the test above while
    hiding the factory's own source from git."""
    import shutil
    import subprocess

    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")

    for tracked in ("workspace/src/workspace/factory.py", "switchboard/smoke.py"):
        result = subprocess.run(
            ["git", "check-ignore", tracked],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0, f"{tracked} is wrongly ignored"
