"""Packet: P-009 — Family Four: xAI (Grok) Adapter.

One job: shape a call for the xAI family — plain system message, image and
text attachments, and a loud refusal for the PDF kind its chat API does not
accept.

Split from adapters.py under the R-017 pre-authorisation: that file held three
families at 297 lines and could not take a fourth.

Version: 0.9.0
"""

from __future__ import annotations

from typing import Any

from switchboard.adapters import (
    _IMAGE_MEDIA_TYPES,
    _TEXT_MEDIA_TYPES,
    _assemble,
    _data_url,
    _existing_path,
    _framed_text_part,
    _media_type,
)
from switchboard.request import Attachment, Message


def _xai_attachment_part(attachment: Attachment) -> dict[str, Any]:
    """Read one attachment as an xAI content part.

    xAI's chat API documents text and image input and no document part
    (P-009 contract 4). LiteLLM will happily forward a file part — fidelity is
    not acceptance (R-024) — so the refusal lives here rather than being
    discovered by the provider.
    """
    if attachment.kind == "pdf":
        raise ValueError(
            f"attachment kind 'pdf' is not supported by the 'xai' family: its "
            f"chat API accepts text and image input only "
            f"(refused: {attachment.path})"
        )

    path = _existing_path(attachment)

    if attachment.kind == "text":
        # The extension is validated; the media type never reaches the wire —
        # text rides the same labelled frame T-004 fixed for OpenAI.
        _media_type(path, _TEXT_MEDIA_TYPES, "text")
        return _framed_text_part(path)

    media_type = _media_type(path, _IMAGE_MEDIA_TYPES, "image")
    return {"type": "image_url", "image_url": {"url": _data_url(path, media_type)}}


class GrokAdapter:
    """xAI family: a plain system message, image and text only.

    Caching is provider-side (xAI prices cached input), so no marks are
    placed. The effort vocabulary is the intersection safe across every
    current Grok model — see P-009 contract 5 and R-025.
    """

    EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high")
    SUPPORTED_KINDS: tuple[str, ...] = ("image", "text")

    def prepare(
        self,
        system: str | None,
        messages: list[Message],
        attachments: list[Attachment],
    ) -> list[dict]:
        system_message = {"role": "system", "content": system} if system else None
        return _assemble(system_message, messages, attachments, _xai_attachment_part)
