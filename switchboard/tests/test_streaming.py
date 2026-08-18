"""Packet: P-009 — Family Four: xAI (Grok) Adapter.

One job: test streaming delivery — deltas arrive in order, the receipt stays
complete and truthful, and failures degrade the way the contract says.

The fake chunk and usage shapes mirror the REAL LiteLLM structures observed
during T-002 diagnosis, not an invented convenience shape.

Version: 0.9.0
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import FALLBACK, FREE, PRIMARY, REGISTRY, make_request

from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.router import route_call
from switchboard.tags import MissingTagsError

DELTAS = ("Foun", "dry ", "online")


def real_usage(
    prompt: int = 30, completion: int = 12, cached: int = 0, creation: int = 0
) -> SimpleNamespace:
    """The usage shape LiteLLM actually builds for Anthropic (T-002 diagnosis)."""
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=cached, cache_creation_tokens=creation
        ),
        cache_creation_input_tokens=creation,
        cache_read_input_tokens=cached,
    )


def _chunk(content: str | None = None) -> SimpleNamespace:
    """One LiteLLM-shaped content chunk."""
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


def _usage_chunk(usage: Any) -> SimpleNamespace:
    """The terminal chunk the real API sends when stream_options asks for usage:
    empty choices, usage attached."""
    return SimpleNamespace(choices=[], usage=usage)


class FakeStream:
    """Yields LiteLLM-shaped chunks; the terminal chunk carries usage."""

    def __init__(
        self,
        deltas: tuple[str, ...] = DELTAS,
        failing: tuple[str, ...] = (),
        break_mid_stream: tuple[str, ...] = (),
    ) -> None:
        self.deltas = deltas
        self.failing = failing
        self.break_mid_stream = break_mid_stream
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        model = kwargs["model"]
        if model in self.failing:
            raise RuntimeError(f"provider {model} refused the connection")
        return self._emit(model)

    def _emit(self, model: str) -> Any:
        for index, delta in enumerate(self.deltas):
            if model in self.break_mid_stream and index == 1:
                raise RuntimeError(f"stream from {model} died mid-flight")
            yield _chunk(delta)
        yield _usage_chunk(real_usage())


def test_deltas_arrive_in_order_and_join_into_the_content() -> None:
    received: list[str] = []
    fake = FakeStream()
    response = route_call(make_request(), REGISTRY, fake, FREE, None, received.append)
    assert tuple(received) == DELTAS
    assert response.content == "".join(DELTAS)
    assert response.status == "ok"
    assert response.model_used == PRIMARY


def test_streaming_sets_the_stream_flag() -> None:
    fake = FakeStream()
    route_call(make_request(), REGISTRY, fake, FREE, None, lambda _d: None)
    assert fake.calls[0]["stream"] is True


def test_without_on_chunk_no_stream_kwargs_are_sent() -> None:
    from conftest import FakeCompletion

    fake = FakeCompletion()
    route_call(make_request(), REGISTRY, fake, FREE)
    assert "stream" not in fake.calls[0]
    assert "stream_options" not in fake.calls[0]


def test_streaming_asks_the_provider_for_terminal_usage() -> None:
    """R-018: without this the live run reported tokens=0/0."""
    fake = FakeStream()
    route_call(make_request(), REGISTRY, fake, FREE, None, lambda _d: None)
    assert fake.calls[0]["stream_options"] == {"include_usage": True}


def test_terminal_chunk_usage_reaches_response_and_one_meter_record(
    tmp_path: Path,
) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    response = route_call(
        make_request(), REGISTRY, FakeStream(), FREE, ledger, lambda _d: None
    )
    assert response.usage.prompt_tokens == 30
    assert response.usage.completion_tokens == 12
    lines = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["usage"]["total_tokens"] == 42


def test_streamed_cache_fields_are_read_from_the_real_shape(tmp_path: Path) -> None:
    class CachedStream(FakeStream):
        def _emit(self, model: str) -> Any:
            yield _chunk("hi")
            yield _usage_chunk(real_usage(prompt=3721, cached=3721, creation=0))

    response = route_call(
        make_request(), REGISTRY, CachedStream(), FREE, None, lambda _d: None
    )
    assert response.usage.cached_tokens == 3721
    assert response.usage.cache_creation_tokens == 0


def test_a_raising_callback_warns_stops_callbacks_and_still_completes(
    tmp_path: Path,
) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    received: list[str] = []

    def explode_on_second(delta: str) -> None:
        received.append(delta)
        if len(received) == 2:
            raise RuntimeError("renderer blew up")

    with pytest.warns(RuntimeWarning, match="on_chunk callback failed"):
        response = route_call(
            make_request(), REGISTRY, FakeStream(), FREE, ledger, explode_on_second
        )
    assert received == ["Foun", "dry "]
    assert response.content == "".join(DELTAS)
    assert len(ledger.path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_primary_failing_mid_stream_falls_back_cleanly() -> None:
    received: list[str] = []
    fake = FakeStream(break_mid_stream=(PRIMARY,))
    response = route_call(make_request(), REGISTRY, fake, FREE, None, received.append)
    assert response.model_used == FALLBACK
    assert response.content == "".join(DELTAS)
    assert [call["model"] for call in fake.calls] == [PRIMARY, FALLBACK]
    assert received == ["Foun", "Foun", "dry ", "online"]


def test_tag_gate_runs_before_any_streaming_call() -> None:
    fake = FakeStream()
    with pytest.raises(MissingTagsError):
        route_call(
            make_request(project_id=""), REGISTRY, fake, FREE, None, lambda _d: None
        )
    assert len(fake.calls) == 0


# --- P-007: streaming is family-agnostic ---------------------------------

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
