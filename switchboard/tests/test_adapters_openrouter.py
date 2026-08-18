"""Packet: P-010 — Family Five: OpenRouter (aggregator).

One job: test the OpenRouter family's message shaping — plain system message,
no cache marks, OpenAI-compatible parts for all three kinds — with every
emitted shape run through LiteLLM's real OpenRouter transformation per R-022.

R-024 note: these checks prove translation fidelity only. OpenRouter validates
no MIME type, so every candidate survives — docs decided the shapes, and on an
aggregator the final authority is per-MODEL acceptance, which the matrix
reports rather than this file asserting it.

Version: 0.11.0
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from switchboard.adapters import (
    AnthropicAdapter,
    GeminiAdapter,
    GrokAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
    adapter_for,
    supported_kinds_for,
)
from switchboard.request import Attachment, Message

KIMI = "openrouter/moonshotai/kimi-k3"
MODEL = "moonshotai/kimi-k3"
USER_TURN = [Message(role="user", content="name them")]
BODY = "# Foundry test\nP-010"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _png(tmp_path: Path, name: str = "pixel.png") -> Path:
    path = tmp_path / name
    path.write_bytes(PNG_BYTES)
    return path


def _pdf(tmp_path: Path, name: str = "page.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 minimal")
    return path


def _text(tmp_path: Path, name: str = "notes.md") -> Path:
    path = tmp_path / name
    path.write_text(BODY, encoding="utf-8")
    return path


def _openrouter_body(prepared: list[dict], optional_params: dict | None = None) -> dict:
    """Our adapter output, as OpenRouter would actually receive it (R-022).

    Entry point, recorded per the P-008/P-009 practice:
    `OpenrouterConfig.transform_request` in
    litellm/llms/openrouter/chat/transformation.py. It extends OpenAIGPTConfig
    and is directly usable, like xAI's and unlike Gemini's.
    """
    from litellm.llms.openrouter.chat.transformation import OpenrouterConfig

    return OpenrouterConfig().transform_request(
        model=MODEL,
        messages=prepared,
        optional_params=optional_params or {},
        litellm_params={},
        headers={},
    )


# --- routing ---------------------------------------------------------------


def test_openrouter_prefix_selects_the_adapter_despite_the_double_slug() -> None:
    for model in (KIMI, "openrouter/deepseek/deepseek-v4-pro-0813",
                  "openrouter/deepseek/deepseek-v4-flash-0731",
                  "openrouter/moonshotai/kimi-k2.7-code"):
        assert isinstance(adapter_for(model), OpenRouterAdapter), model


def test_all_four_prior_families_are_unchanged() -> None:
    assert isinstance(adapter_for("anthropic/claude-opus-5"), AnthropicAdapter)
    assert isinstance(adapter_for("openai/gpt-5.6-terra"), OpenAIAdapter)
    assert isinstance(adapter_for("gemini/gemini-3.7-flash"), GeminiAdapter)
    assert isinstance(adapter_for("xai/grok-4.6"), GrokAdapter)
    assert adapter_for("mistral/large") is None


def test_an_aggregator_declares_all_three_kinds() -> None:
    """Unlike xAI, this adapter refuses nothing.

    Capability on an aggregator is per-MODEL, not per family, so a family-wide
    refusal would be a guess. The matrix judges each routed model instead.
    """
    assert supported_kinds_for(KIMI) == ("image", "pdf", "text")


# --- R-022: shapes through OpenRouter's real transformation ----------------


def test_system_is_a_plain_leading_message_with_no_cache_marks() -> None:
    """Contract 2: the aggregator's upstream owns caching, so we mark nothing.

    LiteLLM's OpenRouter transformation will relocate cache_control into the
    content when a model supports it — all the more reason not to place one.
    """
    prepared = OpenRouterAdapter().prepare("stable instructions", USER_TURN, [])
    body = _openrouter_body(prepared)
    assert body["messages"][0] == {"role": "system", "content": "stable instructions"}
    assert "cache_control" not in json.dumps(body)


def test_no_system_means_no_system_message() -> None:
    body = _openrouter_body(OpenRouterAdapter().prepare(None, USER_TURN, []))
    assert [m["role"] for m in body["messages"]] == ["user"]


def test_image_survives_as_a_base64_data_url(tmp_path: Path) -> None:
    prepared = OpenRouterAdapter().prepare(
        None, USER_TURN, [Attachment(kind="image", path=str(_png(tmp_path)))]
    )
    parts = _openrouter_body(prepared)["messages"][-1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url"]
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG_BYTES


def test_pdf_travels_as_the_documented_file_part(tmp_path: Path) -> None:
    """Contract 2: OpenRouter documents exactly this shape for PDFs.

    `{"type": "file", "file": {"filename": ..., "file_data": "data:application/
    pdf;base64,..."}}`. Whether a routed model honours it natively or via a
    parsing plugin is per-model — that acceptance question belongs to the
    matrix, not to this adapter (R-024).
    """
    prepared = OpenRouterAdapter().prepare(
        None, USER_TURN, [Attachment(kind="pdf", path=str(_pdf(tmp_path)))]
    )
    parts = _openrouter_body(prepared)["messages"][-1]["content"]
    assert [p["type"] for p in parts] == ["text", "file"]
    assert parts[1]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert parts[1]["file"]["filename"] == "page.pdf"


def test_text_travels_as_a_labelled_frame_with_the_body_intact(
    tmp_path: Path,
) -> None:
    """Contract 2 tested both candidates; docs decided (R-024).

    Both survive the transformation — OpenRouter validates no MIME type, the
    same reason T-004 slipped through on OpenAI. OpenRouter's file docs cover
    PDFs and name no other format, so a text/plain file part would rely on an
    undocumented shape. The frame is plain text, which every model accepts.
    """
    prepared = OpenRouterAdapter().prepare(
        None, USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
    )
    parts = _openrouter_body(prepared)["messages"][-1]["content"]
    assert [p["type"] for p in parts] == ["text", "text"]
    frame = parts[1]["text"]
    assert frame.startswith("--- attached file: notes.md ---")
    assert frame.endswith("--- end of file: notes.md ---")
    assert BODY in frame
    assert "base64" not in frame


def test_the_rejected_text_candidate_would_also_have_survived() -> None:
    """R-024, demonstrated: fidelity could not have chosen between them.

    A text/plain file part passes the transformation untouched, exactly as the
    PDF one does. Had transformation fidelity been the deciding test, this
    packet could have shipped either shape — which is precisely why docs are
    the acceptance authority.
    """
    candidate = [{"role": "user", "content": [
        {"type": "file", "file": {"file_data": "data:text/plain;base64,Zm9v",
                                  "filename": "notes.md"}}
    ]}]
    part = _openrouter_body(candidate)["messages"][-1]["content"][0]
    assert part["file"]["file_data"].startswith("data:text/plain;base64,")


def test_all_three_kinds_ride_the_same_last_user_message(tmp_path: Path) -> None:
    prepared = OpenRouterAdapter().prepare(
        "be brief",
        [Message(role="user", content="first"), Message(role="assistant", content="ok"),
         Message(role="user", content="name them")],
        [Attachment(kind="image", path=str(_png(tmp_path))),
         Attachment(kind="pdf", path=str(_pdf(tmp_path))),
         Attachment(kind="text", path=str(_text(tmp_path)))],
    )
    messages = _openrouter_body(prepared)["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert [p["type"] for p in messages[-1]["content"]] == [
        "text", "image_url", "file", "text"
    ]
    assert messages[1]["content"] == "first"


def test_missing_and_wrong_extension_files_fail_the_same_way(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        OpenRouterAdapter().prepare(
            None, USER_TURN, [Attachment(kind="image", path=str(tmp_path / "gone.png"))]
        )
    odd = tmp_path / "notes.rtf"
    odd.write_text(BODY, encoding="utf-8")
    with pytest.raises(ValueError, match="text"):
        OpenRouterAdapter().prepare(
            None, USER_TURN, [Attachment(kind="text", path=str(odd))]
        )


# --- effort passthrough ----------------------------------------------------


def test_every_effort_level_passes_through_untouched() -> None:
    """Contract 3: the adapter still forwards effort; it simply does not
    validate it, because the vocabulary belongs to the routed model."""
    for level in ("low", "medium", "high", "xhigh", "max"):
        body = _openrouter_body(
            OpenRouterAdapter().prepare(None, USER_TURN, []),
            {"reasoning_effort": level},
        )
        assert body["reasoning_effort"] == level


def test_no_effort_means_no_kwarg() -> None:
    body = _openrouter_body(OpenRouterAdapter().prepare(None, USER_TURN, []))
    assert "reasoning_effort" not in body
