"""Packet: P-008 — Family Three: Gemini Adapter.

One job: convert a call's system block, messages, and attachments into a
provider family's message format — Anthropic (cache-marked system, native
document blocks) or OpenAI (plain system message, OpenAI-native parts).

Every emitted shape is verified through the provider's real LiteLLM
transformation in the test suite, per R-022.

Version: 0.8.0
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from switchboard.request import Attachment, Message

ANTHROPIC_PREFIX = "anthropic/"
OPENAI_PREFIX = "openai/"
GEMINI_PREFIX = "gemini/"
PDF_MEDIA_TYPE = "application/pdf"

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Markdown has no media type of its own; it rides as plain text.
# T-003: a base64 document source is PDF-only at the API, so text documents
# carry raw content under source.type "text" instead. Verified through
# LiteLLM's AnthropicConfig.transform_request (R-022).
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


def _existing_path(attachment: Attachment) -> Path:
    """Resolve an attachment's path, failing loudly when it is not there."""
    path = Path(attachment.path)
    if not path.is_file():
        raise FileNotFoundError(f"attachment file not found: {attachment.path}")
    return path


def _attachment_part(attachment: Attachment) -> dict[str, Any]:
    """Read one attachment off disk as an Anthropic content part."""
    path = _existing_path(attachment)

    if attachment.kind == "pdf":
        return _file_part(path, PDF_MEDIA_TYPE)

    if attachment.kind == "text":
        return {
            "type": "document",
            "source": {
                "type": "text",
                "media_type": _media_type(path, _TEXT_MEDIA_TYPES, "text"),
                "data": path.read_text(encoding="utf-8"),
            },
        }

    media_type = _media_type(path, _IMAGE_MEDIA_TYPES, "image")
    return {"type": "image_url", "image_url": {"url": _data_url(path, media_type)}}


def _last_user_index(prepared: list[dict[str, Any]]) -> int:
    for index in range(len(prepared) - 1, -1, -1):
        if prepared[index].get("role") == "user":
            return index
    raise ValueError("attachments require at least one user message to carry them")


def _assemble(
    system_message: dict[str, Any] | None,
    messages: list[Message],
    attachments: list[Attachment],
    part_builder: Callable[[Attachment], dict[str, Any]],
) -> list[dict]:
    """Lay out one family's payload: system first, attachments on the last user turn."""
    prepared: list[dict[str, Any]] = []
    if system_message is not None:
        prepared.append(system_message)

    prepared.extend(message.model_dump() for message in messages)

    if attachments:
        target = prepared[_last_user_index(prepared)]
        parts: list[dict[str, Any]] = [{"type": "text", "text": target["content"]}]
        parts.extend(part_builder(item) for item in attachments)
        target["content"] = parts

    return prepared


class AnthropicAdapter:
    """Anthropic family: a cache-marked system block plus inline attachments."""

    def prepare(
        self,
        system: str | None,
        messages: list[Message],
        attachments: list[Attachment],
    ) -> list[dict]:
        system_message = None
        if system:
            # The system block is Foundry's stable prefix, so it is the cache
            # breakpoint. User turns change every call and are never marked.
            system_message = {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        return _assemble(system_message, messages, attachments, _attachment_part)


# T-004: OpenAI's file part accepts application/pdf only, so a text
# attachment travels as an inline text part. This frame is the only signal
# separating an attached file from the user's own words — chosen once, pinned
# by test, never varied.
_TEXT_ATTACHMENT_FRAME = (
    "--- attached file: {name} ---\n{body}\n--- end of file: {name} ---"
)


def _openai_text_part(path: Path) -> dict[str, Any]:
    """An inline, framed text part — the shape OpenAI accepts for text."""
    return {
        "type": "text",
        "text": _TEXT_ATTACHMENT_FRAME.format(
            name=path.name, body=path.read_text(encoding="utf-8")
        ),
    }


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
        return _openai_text_part(path)

    media_type = _media_type(path, _IMAGE_MEDIA_TYPES, "image")
    return {"type": "image_url", "image_url": {"url": _data_url(path, media_type)}}


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
    """

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


class OpenAIAdapter:
    """OpenAI family: a plain system message and OpenAI-native content parts.

    No cache_control anywhere — OpenAI caching is provider-side on repeated
    prefixes, not a mark the caller places.
    """

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


def adapter_for(model: str) -> FamilyAdapter | None:
    """Pick the adapter for a model string, or None for plain dict conversion."""
    if model.startswith(ANTHROPIC_PREFIX):
        return AnthropicAdapter()
    if model.startswith(OPENAI_PREFIX):
        return OpenAIAdapter()
    if model.startswith(GEMINI_PREFIX):
        return GeminiAdapter()
    return None
