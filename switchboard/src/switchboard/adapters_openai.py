"""Packet: P-015 — The Switchboard Learns to Search.

One job: shape a call for the OpenAI family — plain system message, no cache
marks, and OpenAI-native content parts for all three attachment kinds.

Split from adapters.py under the R-017 precedent when the search capability
pushed it past the 300-line ceiling. This also finishes a pattern the other
families already follow: Gemini, xAI and OpenRouter each own a module, and
OpenAI was the last one still inline. Per R-026 the split inherits its parent's
map entries.

Version: 0.15.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from switchboard.adapters import (
    _IMAGE_MEDIA_TYPES,
    _TEXT_MEDIA_TYPES,
    PDF_MEDIA_TYPE,
    _assemble,
    _data_url,
    _existing_path,
    _framed_text_part,
    _media_type,
)
from switchboard.request import Attachment, Message


def _openai_file_part(path: Path, media_type: str) -> dict[str, Any]:
    """An OpenAI file content part, with the filename set explicitly.

    R-022 finding: LiteLLM injects `filename: "my_file.pdf"` when none is
    given, which mislabels a text file as a PDF. Supplying the real name is
    preserved through the transformation.
    """
    return {
        "type": "file",
        "file": {"file_data": _data_url(path, media_type), "filename": path.name},
    }


def _openai_attachment_part(attachment: Attachment) -> dict[str, Any]:
    """Read one attachment off disk as an OpenAI content part."""
    path = _existing_path(attachment)

    if attachment.kind == "pdf":
        return _openai_file_part(path, PDF_MEDIA_TYPE)

    if attachment.kind == "text":
        # The extension is still validated — .rst is not a text attachment —
        # but the media type never reaches the wire: OpenAI rejects any
        # file part that is not application/pdf (T-004).
        _media_type(path, _TEXT_MEDIA_TYPES, "text")
        return _framed_text_part(path)

    media_type = _media_type(path, _IMAGE_MEDIA_TYPES, "image")
    return {"type": "image_url", "image_url": {"url": _data_url(path, media_type)}}


class OpenAIAdapter:
    """OpenAI family: a plain system message and OpenAI-native content parts.

    No cache_control anywhere — OpenAI caching is provider-side on repeated
    prefixes, not a mark the caller places.
    """

    EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

    def prepare(
        self,
        system: str | None,
        messages: list[Message],
        attachments: list[Attachment],
    ) -> list[dict]:
        system_message = {"role": "system", "content": system} if system else None
        return _assemble(
            system_message, messages, attachments, _openai_attachment_part
        )
