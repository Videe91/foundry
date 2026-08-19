"""Packet: P-015 — The Switchboard Learns to Search.

One job: define the switchboard call request, its chat messages and
attachments, and the response model returned to the caller.

Version: 0.15.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from switchboard.meter import Usage
from switchboard.tags import CallTags


class Message(BaseModel):
    """One chat message in a switchboard call."""

    role: Literal["system", "user", "assistant"]
    content: str


class Attachment(BaseModel):
    """A local file sent alongside the messages."""

    kind: Literal["image", "pdf", "text"]
    path: str


class WebSearchSpec(BaseModel):
    """Ask the provider to search the web while answering.

    `max_uses` is a SPEND control, not a hint: every use is billed at $10 per
    1,000 searches on top of the search results arriving as input tokens, and a
    single search can add thousands of those. Set it deliberately — the default
    of 5 is a ceiling, not a target.
    """

    max_uses: int = Field(default=5, ge=1, le=20)
    allowed_domains: list[str] = []
    blocked_domains: list[str] = []
    user_location: dict | None = None

    @model_validator(mode="after")
    def _one_domain_list_only(self) -> "WebSearchSpec":
        """Anthropic's docs: an allow list OR a block list, never both."""
        if self.allowed_domains and self.blocked_domains:
            raise ValueError(
                "allowed_domains and blocked_domains are mutually exclusive: "
                "set one or the other, never both"
            )
        return self


class SwitchboardRequest(BaseModel):
    """An LLM call presented to the switchboard, with its Foundry tags."""

    tags: CallTags
    messages: list[Message] = Field(min_length=1)
    system: str | None = None
    attachments: list[Attachment] = []
    web_search: WebSearchSpec | None = None


class SwitchboardResponse(BaseModel):
    """The switchboard's answer, naming the model that produced it."""

    status: str
    tags: CallTags
    received_at: datetime
    model_used: str
    content: str
    usage: Usage
