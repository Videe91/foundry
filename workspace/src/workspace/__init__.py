"""Packet: P-011 — The Workspace: a project is a folder with a constitution.

One job: the package's public surface.

Dumb by design — pure structure, zero AI. No LLM call, no litellm import, no
network, and exactly one environment variable read anywhere inside it.

Version: 0.2.0
"""

from __future__ import annotations

from workspace.factory import create_project, open_project, workspace_root
from workspace.meter_router import JsonlMeter, MeterRouter, workspace_resolver
from workspace.project import Project, WorkspaceError

__all__ = [
    "JsonlMeter",
    "MeterRouter",
    "Project",
    "WorkspaceError",
    "create_project",
    "open_project",
    "workspace_resolver",
    "workspace_root",
]
