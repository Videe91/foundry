"""Packet: P-006 — Attachments: Text Kind (.md / .txt).

One job: convert a call's system block, messages, and attachments into one
provider family's message format, marking stable content for caching.

Version: 0.6.0
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Protocol

from switchboard.request import Attachment, Message

ANTHROPIC_PREFIX = "anthropic/"
PDF_MEDIA_TYPE = "application/pdf"

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Markdown has no media type of its own; it rides as plain text.
_TEXT_MEDIA_TYPES = {
    ".md": "text/plain",
    ".txt": "text/plain",
}


class FamilyAdapter(Protocol):
    """Turns a call into one provider family's message format."""

    def prepare(
        self,
        system: str | None,
        messages: list[Message],
        attachments: list[Attachment],
    ) -> list[dict]: ...


def _data_url(path: Path, media_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _file_part(path: Path, media_type: str) -> dict[str, Any]:
    """A document content part — the shape PDFs and text files both use."""
    return {"type": "file", "file": {"file_data": _data_url(path, media_type)}}


def _media_type(path: Path, table: dict[str, str], kind: str) -> str:
    """Map an extension to its media type, naming the extension when unknown."""
    media_type = table.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(
            f"unsupported {kind} extension '{path.suffix}' "
            f"for attachment {path}"
        )
    return media_type


def _attachment_part(attachment: Attachment) -> dict[str, Any]:
    """Read one attachment off disk as an inline base64 content part."""
    path = Path(attachment.path)
    if not path.is_file():
        raise FileNotFoundError(f"attachment file not found: {attachment.path}")

    if attachment.kind == "pdf":
        return _file_part(path, PDF_MEDIA_TYPE)

    if attachment.kind == "text":
        return _file_part(path, _media_type(path, _TEXT_MEDIA_TYPES, "text"))

    media_type = _media_type(path, _IMAGE_MEDIA_TYPES, "image")
    return {"type": "image_url", "image_url": {"url": _data_url(path, media_type)}}


def _last_user_index(prepared: list[dict[str, Any]]) -> int:
    for index in range(len(prepared) - 1, -1, -1):
        if prepared[index].get("role") == "user":
            return index
    raise ValueError("attachments require at least one user message to carry them")


class AnthropicAdapter:
    """Anthropic family: a cache-marked system block plus inline attachments."""

    def prepare(
        self,
        system: str | None,
        messages: list[Message],
        attachments: list[Attachment],
    ) -> list[dict]:
        prepared: list[dict[str, Any]] = []

        if system:
            # The system block is Foundry's stable prefix, so it is the cache
            # breakpoint. User turns change every call and are never marked.
            prepared.append(
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": system,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            )

        prepared.extend(message.model_dump() for message in messages)

        if attachments:
            target = prepared[_last_user_index(prepared)]
            parts: list[dict[str, Any]] = [
                {"type": "text", "text": target["content"]}
            ]
            parts.extend(_attachment_part(item) for item in attachments)
            target["content"] = parts

        return prepared


def adapter_for(model: str) -> FamilyAdapter | None:
    """Pick the adapter for a model string, or None for plain dict conversion."""
    if model.startswith(ANTHROPIC_PREFIX):
        return AnthropicAdapter()
    return None
