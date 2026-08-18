"""Packet: P-009 — Family Four: xAI (Grok) Adapter.

One job: shape a call for the Gemini family — plain system message and
inline-data attachments for all three kinds.

Split from adapters.py under P-008's standing pre-authorisation, which was
conditional on the 300-line ceiling forcing it. The fourth family forced it.

Version: 0.9.0
"""

from __future__ import annotations

from typing import Any

from switchboard.adapters import (
    _IMAGE_MEDIA_TYPES,
    _TEXT_MEDIA_TYPES,
    PDF_MEDIA_TYPE,
    _assemble,
    _data_url,
    _existing_path,
    _media_type,
)
from switchboard.request import Attachment, Message


def _gemini_attachment_part(attachment: Attachment) -> dict[str, Any]:
    """Read one attachment as an inline-data part.

    Gemini is natively multimodal: image, pdf and text/plain all arrive as
    `inline_data` with their own mime_type, so text keeps its document
    semantics instead of being flattened into prose. Verified through
    LiteLLM's real Gemini body builder (R-022).
    """
    path = _existing_path(attachment)

    if attachment.kind == "pdf":
        return {"type": "file", "file": {"file_data": _data_url(path, PDF_MEDIA_TYPE)}}

    if attachment.kind == "text":
        media_type = _media_type(path, _TEXT_MEDIA_TYPES, "text")
        return {"type": "file", "file": {"file_data": _data_url(path, media_type)}}

    media_type = _media_type(path, _IMAGE_MEDIA_TYPES, "image")
    return {"type": "image_url", "image_url": {"url": _data_url(path, media_type)}}


class GeminiAdapter:
    """Gemini family: a plain system message and inline-data attachments.

    No cache marks. LiteLLM's Gemini path drops `cache_control` silently, so
    this family relies on implicit caching only (P-008 contract 1).

    Three thinking levels, not five: `xhigh` and `max` are rejected by the
    provider's own vocabulary (T-005, R-025).
    """

    EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high")

    def prepare(
        self,
        system: str | None,
        messages: list[Message],
        attachments: list[Attachment],
    ) -> list[dict]:
        system_message = {"role": "system", "content": system} if system else None
        return _assemble(
            system_message, messages, attachments, _gemini_attachment_part
        )
