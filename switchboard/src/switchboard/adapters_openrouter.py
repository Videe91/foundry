"""Packet: P-010 — Family Five: OpenRouter (aggregator).

One job: shape a call for the OpenRouter family — plain system message, no
cache marks, and OpenAI-compatible content parts for all three attachment
kinds.

OpenRouter is an AGGREGATOR: one OpenAI-compatible API fronting hundreds of
models, routing each request to an upstream provider. Two consequences shape
this file. Caching belongs to the routed upstream, so the adapter places no
marks. And capability varies per MODEL rather than per family — so unlike xAI,
this adapter refuses nothing: it declares all three kinds and lets the matrix
judge each model's real acceptance, which is what the grid is for (R-024).

Split from adapters.py under the R-017 pre-authorisation the Dictionary names.

Version: 0.11.0
"""

from __future__ import annotations

from switchboard.adapters import _assemble
from switchboard.adapters_openai import _openai_attachment_part
from switchboard.request import Attachment, Message


class OpenRouterAdapter:
    """OpenRouter family: OpenAI-compatible shapes, no cache marks.

    Declares NO `EFFORT_LEVELS`. An aggregator has no family-wide effort
    vocabulary — it belongs to the routed model, and those differ (DeepSeek V4
    Pro documents high and xhigh; Kimi's is unpublished; hundreds of others
    vary). `load_registry` therefore skips effort validation for this family
    exactly as it does for a family with no adapter at all, and effort
    compatibility is the human's per-model responsibility under R-012 (R-031).

    Declares no `SUPPORTED_KINDS` either, so it inherits ALL_KINDS. The
    attachment shapes are OpenAI's, which is what OpenRouter's API accepts;
    whether a given routed model honours a PDF is per-model and per-plugin, and
    the matrix reports that per model rather than this adapter guessing it.
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
