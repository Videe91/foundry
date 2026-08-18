"""Packet: P-008 — Family Three: Gemini Adapter.

One job: test the Gemini family's message shaping — plain system message,
inline-data attachments for all three kinds — with every emitted shape verified
through LiteLLM's real Gemini body builder per R-022.

R-024 note: these checks prove translation fidelity. Provider docs are the
acceptance authority, and the live smoke run is the final gate.

Version: 0.8.0
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from switchboard.adapters import AnthropicAdapter, GeminiAdapter, OpenAIAdapter, adapter_for
from switchboard.request import Attachment, Message

MODEL = "gemini-3.7-flash"
USER_TURN = [Message(role="user", content="name them")]
BODY = "# Foundry test\nP-008"
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


def _parts(prepared: list[dict]) -> list[dict]:
    return prepared[-1]["content"]


def _gemini_body(prepared: list[dict], optional_params: dict | None = None) -> dict:
    """Our adapter output, as Gemini would actually receive it (R-022).

    Gemini has a custom body builder — `transform_request` on the config raises
    NotImplementedError, so the real path is `sync_transform_request_body`.
    """
    from litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini import (
        sync_transform_request_body,
    )

    return sync_transform_request_body(
        gemini_api_key="not-a-key",
        messages=prepared,
        api_base=None,
        model=MODEL,
        client=None,
        timeout=None,
        extra_headers=None,
        optional_params=optional_params or {},
        logging_obj=None,
        custom_llm_provider="gemini",
        litellm_params={},
        vertex_project=None,
        vertex_location=None,
        vertex_auth_header=None,
    )


def _inline(part: dict) -> dict:
    return part.get("inline_data") or part.get("inlineData") or {}


def _mime(part: dict) -> str | None:
    data = _inline(part)
    return data.get("mime_type") or data.get("mimeType")


# --- routing --------------------------------------------------------------


def test_gemini_model_selects_the_gemini_adapter() -> None:
    assert isinstance(adapter_for("gemini/gemini-3.7-flash"), GeminiAdapter)


def test_other_families_are_unchanged() -> None:
    assert isinstance(adapter_for("openai/gpt-5.6-luna"), OpenAIAdapter)
    assert isinstance(adapter_for("anthropic/claude-opus-5"), AnthropicAdapter)


def test_unknown_family_selects_no_adapter() -> None:
    assert adapter_for("mistral/large") is None


# --- system + cache marks -------------------------------------------------


def test_system_becomes_a_plain_leading_message() -> None:
    prepared = GeminiAdapter().prepare("be brief", USER_TURN, [])
    assert prepared[0] == {"role": "system", "content": "be brief"}


def test_system_reaches_gemini_as_system_instruction() -> None:
    body = _gemini_body(GeminiAdapter().prepare("be brief", USER_TURN, []))
    assert body["system_instruction"]["parts"][0]["text"] == "be brief"


def test_no_cache_marks_are_emitted(tmp_path: Path) -> None:
    """Contract 1 outcome: LiteLLM's Gemini path drops cache_control silently,
    so this family emits none and relies on implicit caching."""
    prepared = GeminiAdapter().prepare(
        "stable block", USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
    )
    assert "cache_control" not in json.dumps(prepared)
    assert "cache_control" not in json.dumps(_gemini_body(prepared), default=str)


def test_the_adapter_contributes_no_sampling_parameters() -> None:
    """Gemini 3.6+ dropped temperature/top_p/top_k. Nothing we emit adds them.

    The full contract-4 assertion — that the *outgoing* payload carries none —
    cannot pass today: LiteLLM injects `temperature: 1.0` unconditionally.
    Filed as T-005; this test covers our half of it.
    """
    prepared = GeminiAdapter().prepare("be brief", USER_TURN, [])
    emitted = json.dumps(prepared)
    for banned in ("temperature", "top_p", "topP", "top_k", "topK"):
        assert banned not in emitted


# --- attachments: the registered prediction under test --------------------


def test_image_becomes_inline_data(tmp_path: Path) -> None:
    body = _gemini_body(
        GeminiAdapter().prepare(
            None, USER_TURN, [Attachment(kind="image", path=str(_png(tmp_path)))]
        )
    )
    assert _mime(body["contents"][0]["parts"][-1]) == "image/png"


def test_pdf_becomes_inline_data(tmp_path: Path) -> None:
    body = _gemini_body(
        GeminiAdapter().prepare(
            None, USER_TURN, [Attachment(kind="pdf", path=str(_pdf(tmp_path)))]
        )
    )
    assert _mime(body["contents"][0]["parts"][-1]) == "application/pdf"


def test_text_becomes_inline_data_breaking_the_prediction(tmp_path: Path) -> None:
    """R-024's registered prediction — 'document and file parts are PDF-only;
    text travels as text' — BREAKS here.

    Gemini is natively multimodal: text/plain rides as `inline_data` exactly
    like image and pdf, so the text kind keeps its document semantics rather
    than being flattened into a labelled prose frame (contract 2 prefers this
    shape when both candidates stand).
    """
    body = _gemini_body(
        GeminiAdapter().prepare(
            None, USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
        )
    )
    part = body["contents"][0]["parts"][-1]
    assert _mime(part) == "text/plain"
    assert base64.b64decode(_inline(part)["data"]).decode("utf-8") == BODY


def test_all_three_kinds_arrive_as_inline_data(tmp_path: Path) -> None:
    body = _gemini_body(
        GeminiAdapter().prepare(
            "be brief",
            USER_TURN,
            [
                Attachment(kind="image", path=str(_png(tmp_path))),
                Attachment(kind="pdf", path=str(_pdf(tmp_path))),
                Attachment(kind="text", path=str(_text(tmp_path))),
            ],
        )
    )
    parts = body["contents"][0]["parts"]
    assert [_mime(p) for p in parts[1:]] == [
        "image/png",
        "application/pdf",
        "text/plain",
    ]
    assert parts[0]["text"] == "name them"


# --- error behaviour is identical across families -------------------------


def test_missing_file_raises_naming_the_path(tmp_path: Path) -> None:
    missing = str(tmp_path / "absent.md")
    with pytest.raises(FileNotFoundError) as excinfo:
        GeminiAdapter().prepare(None, USER_TURN, [Attachment(kind="text", path=missing)])
    assert missing in str(excinfo.value)


def test_unknown_text_extension_raises_naming_it(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text(tmp_path, "notes.rst")))
    with pytest.raises(ValueError) as excinfo:
        GeminiAdapter().prepare(None, USER_TURN, [attachment])
    assert ".rst" in str(excinfo.value)


def test_unknown_image_extension_raises_naming_it(tmp_path: Path) -> None:
    attachment = Attachment(kind="image", path=str(_png(tmp_path, "photo.bmp")))
    with pytest.raises(ValueError) as excinfo:
        GeminiAdapter().prepare(None, USER_TURN, [attachment])
    assert ".bmp" in str(excinfo.value)


# --- contract 3: the observed effort mapping ------------------------------


def _map_effort(level: str) -> dict:
    from litellm.llms.gemini.chat.transformation import GoogleAIStudioGeminiConfig

    return GoogleAIStudioGeminiConfig().map_openai_params(
        non_default_params={"reasoning_effort": level},
        optional_params={},
        model=MODEL,
        drop_params=False,
    )


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_effort_maps_onto_geminis_thinking_level(level: str) -> None:
    """Observed, not invented: our three lower levels land on Gemini's own
    thinkingLevel one-for-one.

    `xhigh` and `max` raise `ValueError: Invalid reasoning effort` in LiteLLM
    and are NOT pinned here — inventing a client-side collapse to `high` is
    forbidden without a ruling (T-005).
    """
    assert _map_effort(level)["thinkingConfig"]["thinkingLevel"] == level
