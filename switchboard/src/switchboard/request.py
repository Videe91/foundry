"""Packet: P-002 — Switchboard Routing.

One job: define the switchboard call request, its chat messages, and the
response model returned to the caller.

Version: 0.2.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from switchboard.tags import CallTags


class Message(BaseModel):
    """One chat message in a switchboard call."""

    role: Literal["system", "user", "assistant"]
    content: str


class SwitchboardRequest(BaseModel):
    """An LLM call presented to the switchboard, with its Foundry tags."""

    tags: CallTags
    messages: list[Message] = Field(min_length=1)


class SwitchboardResponse(BaseModel):
    """The switchboard's answer, naming the model that produced it."""

    status: str
    tags: CallTags
    received_at: datetime
    model_used: str
    content: str
