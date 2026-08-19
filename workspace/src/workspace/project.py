"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: the Project handle — typed paths, lifecycle transitions, and registry
layering. Dumb by design: pure structure, zero AI, no network.

Version: 0.1.0
"""

from __future__ import annotations

import os
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workspace.skeleton import (
    DIRECTORIES,
    FILES,
    SIGNATURE_REQUIRED,
    STATUSES,
    TRANSITIONS,
)


class WorkspaceError(Exception):
    """A workspace is missing or malformed. Names what, never repairs it."""


def _toml_string(value: str) -> str:
    """A TOML basic string. Hand-rolled: the pins carry no TOML writer."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'


def render_project_toml(data: dict[str, Any]) -> str:
    """Serialise the birth certificate.

    `signatures` is an ARRAY of tables, not a table keyed by status. The
    long-haul loop revisits states — live -> amended -> building -> ... -> live
    — so a status-keyed table would silently overwrite the previous signing of
    the same state, losing exactly the history a signature chain exists to keep.
    Appending is the only reading that survives the documented lifecycle.
    """
    lines = [
        f"id = {_toml_string(data['id'])}",
        f"slug = {_toml_string(data['slug'])}",
        f"name = {_toml_string(data['name'])}",
        f"created = {_toml_string(data['created'])}",
        f"status = {_toml_string(data['status'])}",
    ]
    for entry in data.get("signatures", []):
        lines.append("")
        lines.append("[[signatures]]")
        lines.append(f"status = {_toml_string(entry['status'])}")
        lines.append(f"at = {_toml_string(entry['at'])}")
        lines.append(f"signature = {_toml_string(entry['signature'])}")
    return "\n".join(lines) + "\n"


def read_project_toml(path: Path) -> dict[str, Any]:
    """Parse and validate the birth certificate, naming any missing key."""
    if not path.is_file():
        raise WorkspaceError(f"project.toml is missing: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise WorkspaceError(f"project.toml is not parseable TOML: {path} ({exc})")

    for key in ("id", "slug", "name", "created", "status"):
        if key not in data:
            raise WorkspaceError(f"project.toml is missing the key '{key}': {path}")
    if data["status"] not in STATUSES:
        raise WorkspaceError(
            f"project.toml has an unknown status '{data['status']}': "
            f"expected one of {', '.join(STATUSES)}"
        )
    data.setdefault("signatures", [])
    return data


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Project:
    """A handle on one project directory.

    Every standard path is a property here, so no department computes one.
    Paths are handed out whether or not the file exists yet — an address is not
    a claim that something has been written to it.
    """

    def __init__(self, root_dir: Path, data: dict[str, Any]) -> None:
        self.root_dir = Path(root_dir)
        self._data = data

    # --- identity -----------------------------------------------------------

    @property
    def slug(self) -> str:
        return str(self._data["slug"])

    @property
    def name(self) -> str:
        return str(self._data["name"])

    @property
    def id(self) -> str:
        return str(self._data["id"])

    @property
    def created(self) -> str:
        return str(self._data["created"])

    @property
    def status(self) -> str:
        return str(self._data["status"])

    @property
    def signatures(self) -> list[dict[str, str]]:
        return list(self._data.get("signatures", []))

    # --- typed paths, generated from the one layout table --------------------

    def path(self, prop: str) -> Path:
        """The path for a Dictionary property name."""
        relative = DIRECTORIES.get(prop) or FILES.get(prop)
        if relative is None:
            raise WorkspaceError(f"no such workspace path: '{prop}'")
        return self.root_dir / relative

    def __getattr__(self, item: str) -> Any:
        # Only reached when normal attribute lookup fails, so the explicit
        # properties above always win and this never shadows them.
        if item in DIRECTORIES or item in FILES:
            return self.path(item)
        raise AttributeError(item)

    def __repr__(self) -> str:
        return f"Project(slug={self.slug!r}, status={self.status!r}, root={self.root_dir})"

    # --- registry layering ---------------------------------------------------

    def effective_registry_path(self, global_registry: Path | None = None) -> Path:
        """This project's registry.toml if it exists, else the global one.

        Layering resolves WHICH file, never what is in it (R-012). The global
        path is a parameter rather than a switchboard import: the Workspace must
        not depend on the Switchboard.
        """
        own = self.registry_path
        if own.is_file():
            return own
        if global_registry is None:
            raise WorkspaceError(
                f"project '{self.slug}' has no registry.toml and no global "
                "registry path was supplied to fall back to"
            )
        return Path(global_registry)

    # --- lifecycle -----------------------------------------------------------

    def advance(self, to: str, signature: str) -> None:
        """Move the project one lawful step, recording who signed for it."""
        if to not in STATUSES:
            raise WorkspaceError(
                f"unknown status '{to}': expected one of {', '.join(STATUSES)}"
            )
        current = self.status
        if to not in TRANSITIONS.get(current, ()):
            raise WorkspaceError(
                f"invalid transition from '{current}' to '{to}': "
                f"'{current}' may advance only to "
                f"{', '.join(TRANSITIONS.get(current, ())) or '(nothing)'}"
            )
        if (current, to) in SIGNATURE_REQUIRED and not signature.strip():
            raise WorkspaceError(
                f"transition '{current}' -> '{to}' requires a non-empty signature"
            )

        self._data["status"] = to
        self._data.setdefault("signatures", []).append(
            {"status": to, "at": _utc_now(), "signature": signature}
        )
        self._write()

    def _write(self) -> None:
        """Rewrite project.toml atomically: temp file, then rename.

        A half-written birth certificate is worse than none — it would parse as
        a different project, or not at all, and the folder IS the project.
        """
        target = self.project_toml_path
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(render_project_toml(self._data), encoding="utf-8")
        os.replace(temp, target)

    def reload(self) -> None:
        self._data = read_project_toml(self.project_toml_path)
