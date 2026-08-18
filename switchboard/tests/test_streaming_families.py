"""Packet: P-010 — Streaming by default, all families.

One job: prove the streamed path is family-agnostic — each family's terminal
usage chunk reaches the response and the meter through the same code.

These fixtures are the offline half of P-010's acceptance rider: streaming was
live-proven on Anthropic only, and making it the default puts every family on
this path. Shapes mirror the real API per R-019; the live per-family PROVE 4
is the R-024 gate.

Split from test_streaming.py under the R-017 precedent when the P-010 contract
tests pushed it past the 300-line ceiling. Per R-026 the split inherits its
parent's map entries.

Version: 0.10.0
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from conftest import FREE, make_request

from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.router import route_call


OPENAI_MODEL = "openai/gpt-5.6-terra"


def _openai_registry() -> ModelRegistry:
    return ModelRegistry(
        roles={"builder": RoleRoute(model=OPENAI_MODEL, fallbacks=[], max_tokens=128000)}
    )


def test_streamed_openai_call_meters_from_the_terminal_chunk(tmp_path: Path) -> None:
    """Contract 6: streaming is family-agnostic; the receipt still lands."""

    def stream_fake(**kwargs: object) -> object:
        stream_fake.calls.append(dict(kwargs))  # type: ignore[attr-defined]
        usage = SimpleNamespace(
            prompt_tokens=30,
            completion_tokens=12,
            total_tokens=42,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )

        def emit() -> object:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"))]
            )
            yield SimpleNamespace(choices=[], usage=usage)

        return emit()

    stream_fake.calls = []  # type: ignore[attr-defined]
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    received: list[str] = []
    response = route_call(
        make_request(), _openai_registry(), stream_fake, FREE, ledger, received.append
    )
    assert received == ["hi"]
    assert response.usage.total_tokens == 42
    records = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["model_used"] == OPENAI_MODEL


# --- P-008: streaming stays family-agnostic -------------------------------

GEMINI_MODEL = "gemini/gemini-3.7-flash"


def test_streamed_gemini_call_meters_from_the_terminal_chunk(tmp_path: Path) -> None:
    registry = ModelRegistry(
        roles={"builder": RoleRoute(model=GEMINI_MODEL, fallbacks=[], max_tokens=64000)}
    )
    usage = SimpleNamespace(
        prompt_tokens=40,
        completion_tokens=8,
        total_tokens=48,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )

    def stream_fake(**_kwargs: object) -> object:
        def emit() -> object:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))]
            )
            yield SimpleNamespace(choices=[], usage=usage)

        return emit()

    ledger = MeterLedger(tmp_path / "meter.jsonl")
    received: list[str] = []
    response = route_call(
        make_request(), registry, stream_fake, FREE, ledger, received.append
    )
    assert received == ["ok"]
    assert response.usage.total_tokens == 48
    records = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(records[0])["model_used"] == GEMINI_MODEL


# --- P-009: still family-agnostic at the fourth family --------------------

XAI_MODEL = "xai/grok-4.6"


def test_streamed_xai_call_meters_from_the_terminal_chunk(tmp_path: Path) -> None:
    """Contract 8: xAI is OpenAI-compatible, so streaming needs no change —
    asserted rather than assumed, at a fourth prefix."""
    registry = ModelRegistry(
        roles={"builder": RoleRoute(model=XAI_MODEL, fallbacks=[], max_tokens=64000)}
    )
    usage = SimpleNamespace(
        prompt_tokens=31, completion_tokens=9, total_tokens=40,
        prompt_tokens_details=SimpleNamespace(cached_tokens=16),
    )

    def stream_fake(**_kwargs: object) -> object:
        def emit() -> object:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))]
            )
            yield SimpleNamespace(choices=[], usage=usage)
        return emit()

    ledger = MeterLedger(tmp_path / "meter.jsonl")
    received: list[str] = []
    response = route_call(
        make_request(), registry, stream_fake, FREE, ledger, received.append
    )
    assert (received, response.usage.total_tokens, response.usage.cached_tokens) == (
        ["ok"], 40, 16
    )
    assert json.loads(
        ledger.path.read_text(encoding="utf-8").strip().splitlines()[0]
    )["model_used"] == XAI_MODEL
