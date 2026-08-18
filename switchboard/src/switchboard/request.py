"""Packet: P-001 — Switchboard Scaffold.

One job: define the switchboard call request and its stub response model.

Version: 0.1.0
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from switchboard.tags import CallTags


class SwitchboardRequest(BaseModel):
    """An LLM call presented to the switchboard, with its Foundry tags."""

    tags: CallTags
    prompt: str = ""


class SwitchboardResponse(BaseModel):
    """The switchboard's answer. In P-001 this is always a stub."""

    status: str
    tags: CallTags
    received_at: datetime
