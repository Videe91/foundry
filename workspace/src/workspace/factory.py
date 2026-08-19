"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: create a project's skeleton, and open an existing one after validating
it. Never repairs — a broken workspace is a finding, not a fix-up.

Version: 0.1.0
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from workspace.project import Project, WorkspaceError, read_project_toml, render_project_toml
from workspace.skeleton import (
    BIRTH_FILE_CONTENT,
    DIRECTORIES,
    DRAFT,
    GITKEEP,
    REQUIRED_DIRECTORIES,
    REQUIRED_FILES,
)

WORKSPACE_ROOT_ENV = "FOUNDRY_WORKSPACE_ROOT"
DEFAULT_ROOT_NAME = "projects"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _repo_root() -> Path | None:
    """The Foundry repo this package was installed from, or None if unsure.

    The package lives at `<repo>/workspace/src/workspace/`. If that shape does
    not hold — an installed wheel in site-packages, say — we do not know where
    the repo is, and guessing would stamp a project into a random directory.
    """
    here = Path(__file__).resolve()
    parents = here.parents
    if len(parents) >= 4 and parents[1].name == "src" and parents[2].name == "workspace":
        return parents[3]
    return None


def workspace_root(root: Path | str | None = None) -> Path:
    """Explicit argument, then FOUNDRY_WORKSPACE_ROOT, then <repo>/projects/.

    R-013 analogue: this is the ONLY environment variable the package reads.
    """
    import os

    if root is not None:
        return Path(root)

    from_env = os.environ.get(WORKSPACE_ROOT_ENV)
    if from_env:
        return Path(from_env)

    repo = _repo_root()
    if repo is None:
        raise WorkspaceError(
            "cannot determine the workspace root: this package is not laid out "
            f"as <repo>/workspace/src/workspace, so set {WORKSPACE_ROOT_ENV} "
            "or pass an explicit root"
        )
    return repo / DEFAULT_ROOT_NAME


def _validate_slug(slug: str) -> None:
    if not slug:
        raise ValueError("slug is empty: expected lowercase kebab-case")
    if not SLUG_PATTERN.match(slug):
        raise ValueError(
            f"slug {slug!r} is not lowercase kebab-case: expected "
            "[a-z0-9][a-z0-9-]* (lowercase letters, digits and hyphens, "
            "not starting with a hyphen)"
        )


def create_project(
    slug: str, name: str, root: Path | str | None = None
) -> Project:
    """Stamp the standard skeleton for a new project and return its handle."""
    _validate_slug(slug)
    base = workspace_root(root)
    root_dir = base / slug
    if root_dir.exists():
        raise WorkspaceError(
            f"refusing to create over an existing directory: {root_dir}"
        )

    for relative in DIRECTORIES.values():
        (root_dir / relative).mkdir(parents=True, exist_ok=True)

    data = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "name": name,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": DRAFT,
        "signatures": [],
    }
    (root_dir / "project.toml").write_text(
        render_project_toml(data), encoding="utf-8"
    )
    (root_dir / "ledger" / "build-log.md").write_text(
        f"# Build log — {name}\n\n"
        f"- {data['created']} — project created as `{slug}`, status `{DRAFT}`.\n",
        encoding="utf-8",
    )
    for relative, content in BIRTH_FILE_CONTENT.items():
        (root_dir / relative).write_text(content, encoding="utf-8")

    # A .gitkeep in every directory that is still empty. registry.toml is
    # deliberately not written: its absence means "inherit the global" (R-012).
    for relative in DIRECTORIES.values():
        directory = root_dir / relative
        if not any(directory.iterdir()):
            (directory / GITKEEP).write_text("", encoding="utf-8")

    return Project(root_dir, data)


def open_project(
    slug_or_path: str | Path, root: Path | str | None = None
) -> Project:
    """Validate an existing project directory and return its handle.

    Accepts a slug (resolved against the workspace root) or a path directly.
    Names exactly what is missing; never creates anything.
    """
    candidate = Path(slug_or_path)
    root_dir = candidate if candidate.is_absolute() or candidate.exists() else None
    if root_dir is None:
        root_dir = workspace_root(root) / str(slug_or_path)

    if not root_dir.is_dir():
        raise WorkspaceError(f"project directory does not exist: {root_dir}")

    missing = [
        relative
        for relative in REQUIRED_DIRECTORIES
        if not (root_dir / relative).is_dir()
    ]
    missing += [
        relative
        for relative in REQUIRED_FILES
        if not (root_dir / relative).is_file()
    ]
    if missing:
        raise WorkspaceError(
            f"project at {root_dir} is missing: {', '.join(sorted(missing))}"
        )

    return Project(root_dir, read_project_toml(root_dir / "project.toml"))
