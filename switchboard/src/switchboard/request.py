"""Packet: P-004 — Family One: Anthropic Adapter.

One job: define the switchboard call request, its chat messages and
attachments, and the response model returned to the caller.

Version: 0.4.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from switchboard.meter import Usage
from switchboard.tags import CallTags


class Message(BaseModel):
    """One chat message in a switchboard call."""

    role: Literal["system", "user", "assistant"]
    content: str


class Attachment(BaseModel):
    """A local file sent alongside the messages."""

    kind: Literal["image", "pdf"]
    path: str


class SwitchboardRequest(BaseModel):
    """An LLM call presented to the switchboard, with its Foundry tags."""

    tags: CallTags
    messages: list[Message] = Field(min_length=1)
    system: str | None = None
    attachments: list[Attachment] = []


class SwitchboardResponse(BaseModel):
    """The switchboard's answer, naming the model that produced it."""

    status: str
    tags: CallTags
    received_at: datetime
    model_used: str
    content: str
    usage: Usage
