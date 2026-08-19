"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: persist an interview into the project's own intent/ directory, and
read it back exactly.

Crash-safety matters more here than almost anywhere: an interview is a
conversation a founder will not want to have twice. The write is atomic — temp
file then rename, the P-011 pattern — and a corrupt file is a named error, never
a silent re-init (P-011's open_project philosophy: a broken thing is a finding).

The path comes from the Workspace handle. It is never computed here.

Version: 0.1.0
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from intent.state import InterviewState

STATE_FILENAME = "interview-state.json"


class IntentStoreError(Exception):
    """The interview on disk is unreadable. Names the file, never repairs it."""


def state_path(project: Any) -> Path:
    """Where this project's interview lives — asked for, never computed."""
    return Path(project.intent_dir) / STATE_FILENAME


def save_state(project: Any, state: InterviewState) -> Path:
    """Write the interview atomically. Returns the path written."""
    target = state_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp, target)
    return target


def load_state(project: Any) -> InterviewState | None:
    """Resume an interview, or None if there is not one yet."""
    path = state_path(project)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntentStoreError(
            f"interview state is not readable JSON: {path} ({exc})"
        ) from exc
    try:
        return InterviewState.model_validate(payload)
    except Exception as exc:
        raise IntentStoreError(
            f"interview state does not match the expected shape: {path} ({exc})"
        ) from exc
