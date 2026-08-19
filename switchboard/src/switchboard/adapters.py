"""Packet: P-015 — The Switchboard Learns to Search.

One job: convert a call's system block, messages, and attachments into a
provider family's message format — Anthropic (cache-marked system, native
document blocks) or OpenAI (plain system message, OpenAI-native parts).

Every emitted shape is verified through the provider's real LiteLLM
transformation in the test suite, per R-022.

Version: 0.15.0
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
XAI_PREFIX = "xai/"
OPENROUTER_PREFIX = "openrouter/"

# Families carry all three kinds unless their adapter narrows the set.
ALL_KINDS: tuple[str, ...] = ("image", "pdf", "text")
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
    """Anthropic family: a cache-marked system block plus inline attachments.

    The only family that can search, for now. Others join docs-first, in their
    own amendments (P-015 family law).
    """

    EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

    def search_tool(self, spec: Any) -> dict[str, Any]:
        """This family can search. Presence of this method IS the capability.

        The gate in route_call asks whether an adapter has this method rather
        than consulting a list of family names, so a future family that learns
        to search opens the gate by defining it — nobody has to remember to edit
        a list somewhere else (P-015 contract 3).
        """
        from switchboard.adapters_search import search_tool_block

        return search_tool_block(spec)

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


def _framed_text_part(path: Path) -> dict[str, Any]:
    """An inline, framed text part — the shape OpenAI accepts for text."""
    return {
        "type": "text",
        "text": _TEXT_ATTACHMENT_FRAME.format(
            name=path.name, body=path.read_text(encoding="utf-8")
        ),
    }












def adapter_for(model: str) -> FamilyAdapter | None:
    """Pick the adapter for a model string, or None for plain dict conversion."""
    if model.startswith(ANTHROPIC_PREFIX):
        return AnthropicAdapter()
    if model.startswith(OPENAI_PREFIX):
        return _split_adapter("OpenAIAdapter")()
    if model.startswith(GEMINI_PREFIX):
        return _split_adapter("GeminiAdapter")()
    if model.startswith(XAI_PREFIX):
        return _split_adapter("GrokAdapter")()
    if model.startswith(OPENROUTER_PREFIX):
        return _split_adapter("OpenRouterAdapter")()
    return None


def effort_levels_for(model: str) -> tuple[str, ...] | None:
    """The effort levels this model's family accepts, or None if unvalidated.

    A family without an adapter has no declared ceiling, so its roles are not
    checked — we do not know its vocabulary (R-025).
    """
    adapter = adapter_for(model)
    return getattr(adapter, "EFFORT_LEVELS", None) if adapter is not None else None


def supported_kinds_for(model: str) -> tuple[str, ...] | None:
    """The attachment kinds this model's family accepts, or None if unknown."""
    adapter = adapter_for(model)
    if adapter is None:
        return None
    return getattr(adapter, "SUPPORTED_KINDS", ALL_KINDS)


# Families split into their own modules to stay under the 300-line ceiling.
# They import helpers from here, so they are loaded on demand rather than at
# module level — a top-level import either way would close the cycle.
_SPLIT_ADAPTERS = {
    "GeminiAdapter": "switchboard.adapters_gemini",
    "OpenAIAdapter": "switchboard.adapters_openai",
    "GrokAdapter": "switchboard.adapters_xai",
    "OpenRouterAdapter": "switchboard.adapters_openrouter",
}


def _split_adapter(name: str) -> type:
    import importlib

    return getattr(importlib.import_module(_SPLIT_ADAPTERS[name]), name)


def __getattr__(name: str) -> object:
    """Re-export the split-out adapters, keeping the public surface whole."""
    if name in _SPLIT_ADAPTERS:
        return _split_adapter(name)
    raise AttributeError(name)








