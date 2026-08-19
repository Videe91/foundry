"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: the data an interview is made of — boxes, turns, contradictions, and
the Scribe's output contract.

Version: 0.1.0
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from intent.skeleton import (
    BY_USER,
    CONFIRMED,
    EMPTY,
    RESEARCH_CONTENT,
    RESEARCH_KEY,
    SKELETON,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Turn(BaseModel):
    """One utterance in the interview."""

    role: str  # "user" | "interviewer"
    content: str
    at: datetime = Field(default_factory=utc_now)
    # Stored faithfully for P-014 to feed to real models. This packet does no
    # attachment processing whatsoever (contract 7).
    attachments: list[str] = Field(default_factory=list)


class Contradiction(BaseModel):
    """A later statement that conflicts with an earlier, confirmed one.

    Surfaced, never silently reconciled: latest wins, but the founder is told
    and confirms (R-033a).
    """

    box_key: str
    earlier: str
    later: str
    surfaced: bool = False
    resolved: bool = False


class BoxState(BaseModel):
    """One box's content and how settled it is."""

    key: str
    content: dict[str, Any] = Field(default_factory=dict)
    status: str = EMPTY
    proposed_by: str | None = None


class InterviewState(BaseModel):
    """Everything one interview knows about itself."""

    slug: str
    boxes: dict[str, BoxState]
    transcript: list[Turn] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    turn_count: int = 0

    @property
    def unresolved_contradictions(self) -> list[Contradiction]:
        return [c for c in self.contradictions if not c.resolved]


def new_state(slug: str) -> InterviewState:
    """A fresh interview: eight empty boxes, and research already settled."""
    boxes = {box.key: BoxState(key=box.key) for box in SKELETON}
    boxes[RESEARCH_KEY] = BoxState(
        key=RESEARCH_KEY,
        content=dict(RESEARCH_CONTENT),
        status=CONFIRMED,
        proposed_by=BY_USER,
    )
    return InterviewState(slug=slug, boxes=boxes)


class ScribeUpdate(BaseModel):
    """What the Scribe extracted from the latest exchange.

    `boxes` is content it can now fill or update; `confirmed_by_user` names the
    boxes the user's message explicitly affirmed; `proposed_by` records who
    authored each proposal, so a default the interviewer offered can never be
    mistaken for something the founder said (R-033b).
    """

    boxes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    contradictions: list[Contradiction] = Field(default_factory=list)
    confirmed_by_user: list[str] = Field(default_factory=list)
    proposed_by: dict[str, str] = Field(default_factory=dict)
    resolved_contradictions: list[str] = Field(default_factory=list)


class TurnResult(BaseModel):
    """What one turn produced."""

    reply: str | None = None
    complete: bool = False
    pending_confirmations: list[str] = Field(default_factory=list)
