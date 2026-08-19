"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: the package's public surface.

The engine is fully offline. Its two brains — the Interviewer and the Scribe —
arrive as injected callables, matched by SHAPE. This package may import
`workspace` (it works on projects, one direction, downward). It must never
import `switchboard` or `litellm`, and subprocess guards enforce both.

Version: 0.1.0
"""

from __future__ import annotations

from intent.engine import build_directives, merge_update, pending_confirmations, run_turn
from intent.rules import box_complete, completeness, is_complete
from intent.skeleton import BOX_KEYS, BOXES, SKELETON, Box
from intent.state import (
    BoxState,
    Contradiction,
    InterviewState,
    ScribeUpdate,
    Turn,
    TurnResult,
    new_state,
)
from intent.store import IntentStoreError, load_state, save_state, state_path

__all__ = [
    "BOXES",
    "BOX_KEYS",
    "SKELETON",
    "Box",
    "BoxState",
    "Contradiction",
    "IntentStoreError",
    "InterviewState",
    "ScribeUpdate",
    "Turn",
    "TurnResult",
    "box_complete",
    "build_directives",
    "completeness",
    "is_complete",
    "load_state",
    "merge_update",
    "new_state",
    "pending_confirmations",
    "run_turn",
    "save_state",
    "state_path",
]
