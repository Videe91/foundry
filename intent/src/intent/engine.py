"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: run one interview turn — Scribe updates the boxes, code checks them,
and either the Interviewer's next question comes back or the interview is done.

**The engine never writes question text.** It hands the Interviewer a small
structured directive and returns whatever comes back, verbatim. Charm is the
model's job; truth is the code's — the Mediocre-Model Test pointed at ourselves.

The two brains arrive as injected callables, by SHAPE. This module imports
neither switchboard nor litellm, and subprocess guards enforce it.

Version: 0.2.0
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from intent.rules import completeness, is_complete
from intent.skeleton import (
    BOX_KEYS,
    BY_USER,
    CONFIRMED,
    CONVERSATIONAL_KEYS,
    PROPOSED,
)
from intent.state import Contradiction, InterviewState, ScribeUpdate, Turn, TurnResult

InterviewerFn = Callable[[list[Turn], dict[str, str], dict[str, Any]], str]
ScribeFn = Callable[[list[Turn], dict[str, Any]], ScribeUpdate]

USER = "user"
INTERVIEWER = "interviewer"


def _describe(content: dict[str, Any]) -> str:
    """A stable one-line rendering of box content, for contradiction records."""
    return json.dumps(content, sort_keys=True, default=str)


def pending_confirmations(state: InterviewState) -> list[str]:
    """Boxes holding content nobody has yet said yes to, in skeleton order.

    Conversational boxes only: nobody may be asked to confirm a box that is not
    theirs to confirm (T-009).
    """
    return [
        key
        for key in CONVERSATIONAL_KEYS
        if state.boxes[key].status == PROPOSED
    ]


def merge_update(state: InterviewState, update: ScribeUpdate) -> None:
    """Fold the Scribe's extraction into the boxes (contract 2).

    Latest wins on content — but a conflict with anything already CONFIRMED
    also emits a Contradiction and demotes the box, so the founder is told
    rather than quietly overruled (R-033a).
    """
    for key, content in update.boxes.items():
        if key not in state.boxes:
            continue
        box = state.boxes[key]
        if box.status == CONFIRMED and box.content == content:
            continue  # restating what is already settled changes nothing
        if box.status == CONFIRMED:
            state.contradictions.append(
                Contradiction(
                    box_key=key,
                    earlier=_describe(box.content),
                    later=_describe(content),
                )
            )
        box.content = content
        box.status = PROPOSED
        box.proposed_by = update.proposed_by.get(key, BY_USER)

    # Contradictions the Scribe itself spotted.
    state.contradictions.extend(update.contradictions)

    # Only a user turn can confirm. There is no other path (R-033b).
    for key in update.confirmed_by_user:
        box = state.boxes.get(key)
        if box is not None and box.content:
            box.status = CONFIRMED

    for key in update.resolved_contradictions:
        for contradiction in state.contradictions:
            if contradiction.box_key == key:
                contradiction.resolved = True


def next_contradiction(state: InterviewState) -> Contradiction | None:
    """The oldest contradiction nobody has raised yet — at most one."""
    for contradiction in state.contradictions:
        if not contradiction.surfaced and not contradiction.resolved:
            return contradiction
    return None


def build_directives(state: InterviewState) -> dict[str, Any]:
    """The engine's only steering. Structure, never prose (contract 4).

    Everything here is model-visible, so everything here is filtered to
    conversational boxes. `incomplete_boxes` used to exclude `research` only by
    accident — research is complete, so it fell out of the list. An internal box
    that was ever INCOMPLETE would have leaked straight into the prompt (T-009).
    """
    done = completeness(state)
    unsurfaced = next_contradiction(state)
    return {
        "incomplete_boxes": [
            key for key in CONVERSATIONAL_KEYS if not done[key]
        ],
        "pending_confirmations": pending_confirmations(state),
        "unsurfaced_contradiction": (
            unsurfaced.model_dump() if unsurfaced is not None else None
        ),
        "ask_one_question": True,
    }


def box_status(state: InterviewState) -> dict[str, str]:
    """The status map handed to the Interviewer — conversational boxes only.

    This was the leak T-009 found: a full status map put `"research":
    "confirmed"` in front of the model on every single turn.
    """
    return {key: state.boxes[key].status for key in CONVERSATIONAL_KEYS}


def run_turn(
    state: InterviewState,
    user_message: str,
    interviewer_fn: InterviewerFn,
    scribe_fn: ScribeFn,
    *,
    project: Any | None = None,
    attachments: list[str] | None = None,
) -> tuple[InterviewState, TurnResult]:
    """One interview turn, in the order contract 1 lays down.

    `project` is optional so the engine stays testable without a workspace; when
    given, the state is saved after the turn (contract 6). `attachments` are
    stored on the user's Turn and otherwise untouched in this packet.
    """
    state.transcript.append(
        Turn(role=USER, content=user_message, attachments=list(attachments or []))
    )
    state.turn_count += 1

    # Conversational boxes only — the Scribe is a model, and a model shown an
    # internal box will eventually restate it back into the conversation, which
    # is how T-009 became visible to the founder in the first place.
    update = scribe_fn(
        state.transcript,
        {key: state.boxes[key].model_dump() for key in CONVERSATIONAL_KEYS},
    )
    merge_update(state, update)

    if is_complete(state):
        _persist(project, state)
        return state, TurnResult(reply=None, complete=True, pending_confirmations=[])

    directives = build_directives(state)
    reply = interviewer_fn(state.transcript, box_status(state), directives)

    # Marked only once it has actually been handed over — surfacing is an event,
    # not an intention.
    surfaced = next_contradiction(state)
    if surfaced is not None:
        surfaced.surfaced = True

    state.transcript.append(Turn(role=INTERVIEWER, content=reply))
    _persist(project, state)
    return state, TurnResult(
        reply=reply,
        complete=False,
        pending_confirmations=pending_confirmations(state),
    )


def _persist(project: Any | None, state: InterviewState) -> None:
    if project is None:
        return
    from intent.store import save_state

    save_state(project, state)
