"""Packet: P-005 — Anthropic Polish: Cache Fix + Streaming.

One job: diagnostic helpers for the smoke run — what was sent, what came back.
Split from smoke.py under the R-017 precedent so both stay under the ceiling.

Nothing here is imported by library code under src/, and nothing here prints a
key or an environment value.

Version: 0.5.0
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

DEBUG_ENV = "FOUNDRY_SMOKE_DEBUG"
HAIKU_CACHE_MINIMUM = 2048
OTHER_CACHE_MINIMUM = 1024


def debug_on() -> bool:
    """True when the human asked for diagnostic output."""
    return os.environ.get(DEBUG_ENV) == "1"


def cache_minimum_for(model: str) -> int:
    """Anthropic's minimum cacheable prefix — family specific (T-002)."""
    return HAIKU_CACHE_MINIMUM if "haiku" in model else OTHER_CACHE_MINIMUM


def describe_messages(messages: list[dict]) -> list[dict]:
    """Structural view of an outgoing message list, text truncated.

    Shows whether a cache_control mark is present without dumping thousands of
    tokens of block text. Structure and short excerpts only.
    """
    described: list[dict] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            described.append(
                {
                    "role": message.get("role"),
                    "blocks": [
                        {
                            "type": part.get("type"),
                            "cache_control": part.get("cache_control"),
                            "text_head": str(part.get("text"))[:40],
                        }
                        for part in content
                    ],
                }
            )
        else:
            described.append(
                {"role": message.get("role"), "text_head": str(content)[:40]}
            )
    return described


def has_system_block(messages: list[dict]) -> bool:
    """Whether a system message actually survived into the outgoing request."""
    return any(message.get("role") == "system" for message in messages)


class Recorder:
    """Wraps the real provider call so debug mode sees what was sent and got."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[Any] = []

    def __call__(self, **kwargs: Any) -> Any:
        import litellm

        self.calls.append(kwargs)
        response = litellm.completion(**kwargs)
        self.responses.append(response)
        return response


def print_cache_diagnostics(
    recorder: Recorder, usage_dumper: Callable[[Any], dict]
) -> None:
    """Print the outgoing structure of call 1 and the raw usage of both calls."""
    print("\n  [debug] messages handed to completion_fn on call 1:")
    if recorder.calls:
        print(
            "  "
            + json.dumps(
                describe_messages(recorder.calls[0].get("messages", [])), indent=2
            ).replace("\n", "\n  ")
        )
    for index, response in enumerate(recorder.responses, start=1):
        print(f"\n  [debug] raw usage fields, call {index}:")
        print("  " + json.dumps(usage_dumper(response), indent=2, default=str).replace("\n", "\n  "))


def print_role_system_check(recorder: Recorder, role: str) -> None:
    """Print whether this role's outgoing request actually carried a system block."""
    if not recorder.calls:
        return
    present = has_system_block(recorder.calls[-1].get("messages", []))
    verdict = "present" if present else "ABSENT — that is a bug"
    print(f"    [debug] {role}: system block {verdict}")
