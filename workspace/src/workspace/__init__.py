"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: the package's public surface.

Dumb by design — pure structure, zero AI. No LLM call, no litellm import, no
network, and exactly one environment variable read anywhere inside it.

Version: 0.1.0
"""

from __future__ import annotations

from workspace.factory import create_project, open_project, workspace_root
from workspace.project import Project, WorkspaceError

__all__ = [
    "Project",
    "WorkspaceError",
    "create_project",
    "open_project",
    "workspace_root",
]
