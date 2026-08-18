"""Packet: P-009 — Family Four: xAI (Grok) Adapter.

One job: test the xAI family's message shaping — plain system message, image
and text attachments, a loud refusal for PDFs — with every emitted shape run
through LiteLLM's real xAI transformation per R-022, and the family's effort
ceiling enforced at registry load per R-025.

R-024 note: these checks prove translation fidelity only. LiteLLM carries a
file part for xai without complaint (see the pdf test), so provider docs are
the acceptance authority; the live smoke run is the final gate.

Version: 0.9.0
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from switchboard.adapters import (
    AnthropicAdapter,
    GeminiAdapter,
    GrokAdapter,
    OpenAIAdapter,
    adapter_for,
    supported_kinds_for,
)
from switchboard.registry import ModelRegistry, RoleRoute, load_registry
from switchboard.request import Attachment, Message

MODEL = "grok-4.6"
USER_TURN = [Message(role="user", content="name them")]
BODY = "# Foundry test\nP-009"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _png(tmp_path: Path, name: str = "pixel.png") -> Path:
    path = tmp_path / name
    path.write_bytes(PNG_BYTES)
    return path


def _text(tmp_path: Path, name: str = "notes.md") -> Path:
    path = tmp_path / name
    path.write_text(BODY, encoding="utf-8")
    return path


def _parts(prepared: list[dict]) -> list[dict]:
    return prepared[-1]["content"]


def _xai_body(prepared: list[dict], optional_params: dict | None = None) -> dict:
    """Our adapter output, as xAI would actually receive it (R-022).

    Entry point, recorded per the packet: `XAIChatConfig.transform_request` in
    litellm/llms/xai/chat/transformation.py. Unlike Gemini's — which raises
    NotImplementedError — this one is the real path and is usable directly.
    """
    from litellm.llms.xai.chat.transformation import XAIChatConfig

    return XAIChatConfig().transform_request(
        model=MODEL,
        messages=prepared,
        optional_params=optional_params or {},
        litellm_params={},
        headers={},
    )


# --- routing ---------------------------------------------------------------


def test_xai_prefix_selects_the_grok_adapter() -> None:
    assert isinstance(adapter_for("xai/grok-4.6"), GrokAdapter)
    assert isinstance(adapter_for("xai/grok-4.1-fast"), GrokAdapter)


def test_the_other_families_are_unchanged() -> None:
    assert isinstance(adapter_for("anthropic/claude-opus-5"), AnthropicAdapter)
    assert isinstance(adapter_for("openai/gpt-5.6-terra"), OpenAIAdapter)
    assert isinstance(adapter_for("gemini/gemini-3.7-flash"), GeminiAdapter)
    assert adapter_for("mistral/large") is None


def test_only_xai_narrows_the_attachment_kinds() -> None:
    """Contract 4: the narrowing is declared, not inferred at call time."""
    assert supported_kinds_for("xai/grok-4.6") == ("image", "text")
    for model in ("anthropic/claude-opus-5", "openai/gpt-5.6-terra",
                  "gemini/gemini-3.7-flash"):
        assert supported_kinds_for(model) == ("image", "pdf", "text")
    assert supported_kinds_for("mistral/large") is None


# --- R-022: shapes through xAI's real transformation -----------------------


def test_system_becomes_a_plain_leading_message_with_no_cache_marks() -> None:
    prepared = GrokAdapter().prepare("stable instructions", USER_TURN, [])
    body = _xai_body(prepared)
    assert body["messages"][0] == {"role": "system", "content": "stable instructions"}
    assert "cache_control" not in str(body)


def test_no_system_means_no_system_message() -> None:
    body = _xai_body(GrokAdapter().prepare(None, USER_TURN, []))
    assert [m["role"] for m in body["messages"]] == ["user"]


def test_image_survives_the_transformation_as_a_base64_data_url(
    tmp_path: Path,
) -> None:
    """Contract 2: the OpenAI-compatible image part, carried through intact."""
    prepared = GrokAdapter().prepare(
        None, USER_TURN, [Attachment(kind="image", path=str(_png(tmp_path)))]
    )
    parts = _xai_body(prepared)["messages"][-1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url"]
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG_BYTES


def test_text_travels_as_a_labelled_frame_with_the_body_intact(
    tmp_path: Path,
) -> None:
    """Contract 3: candidate (b), the T-004 frame, won.

    Both candidates survive transformation — LiteLLM validates no MIME type —
    so fidelity could not decide it. Docs did (R-024): xAI documents text and
    image input, with no documented file/document input type, so candidate (a)
    would have relied on an undocumented shape. The frame is plain text, which
    the API does document.
    """
    prepared = GrokAdapter().prepare(
        None, USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
    )
    parts = _xai_body(prepared)["messages"][-1]["content"]
    assert [p["type"] for p in parts] == ["text", "text"]
    frame = parts[1]["text"]
    assert frame.startswith("--- attached file: notes.md ---")
    assert frame.endswith("--- end of file: notes.md ---")
    assert BODY in frame
    assert "base64" not in frame


def test_both_kinds_ride_the_same_last_user_message(tmp_path: Path) -> None:
    prepared = GrokAdapter().prepare(
        "be brief",
        [Message(role="user", content="first"), Message(role="assistant", content="ok"),
         Message(role="user", content="name them")],
        [Attachment(kind="image", path=str(_png(tmp_path))),
         Attachment(kind="text", path=str(_text(tmp_path)))],
    )
    messages = _xai_body(prepared)["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert [p["type"] for p in messages[-1]["content"]] == ["text", "image_url", "text"]
    assert messages[1]["content"] == "first"


# --- contract 4: the prediction's inverse case -----------------------------


def test_pdf_is_refused_loudly_naming_kind_family_and_reason(
    tmp_path: Path,
) -> None:
    """The registered cross-provider prediction inverts here.

    Anthropic, OpenAI, and Gemini all accept a document part. xAI's chat API
    documents text and image input only, so the adapter refuses rather than
    letting the provider discover it.
    """
    path = tmp_path / "page.pdf"
    path.write_bytes(b"%PDF-1.4 minimal")
    with pytest.raises(ValueError) as excinfo:
        GrokAdapter().prepare(
            None, USER_TURN, [Attachment(kind="pdf", path=str(path))]
        )
    message = str(excinfo.value)
    assert "pdf" in message
    assert "xai" in message
    assert "text and image" in message
    assert str(path) in message


def test_litellm_would_have_carried_a_pdf_part_without_complaint() -> None:
    """R-024, demonstrated: fidelity is not acceptance.

    A file part for an xai model passes transformation untouched — LiteLLM
    even fills in a filename. Had we trusted the transformation check alone,
    this packet would have shipped a shape the provider does not document.
    That is precisely why the refusal above is ours to make.
    """
    smuggled = [{"role": "user", "content": [
        {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0="}}
    ]}]
    part = _xai_body(smuggled)["messages"][-1]["content"][0]
    assert part["type"] == "file"
    assert part["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_missing_and_wrong_extension_files_fail_the_same_way(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        GrokAdapter().prepare(
            None, USER_TURN, [Attachment(kind="image", path=str(tmp_path / "gone.png"))]
        )
    odd = tmp_path / "notes.rtf"
    odd.write_text(BODY, encoding="utf-8")
    with pytest.raises(ValueError, match="text"):
        GrokAdapter().prepare(
            None, USER_TURN, [Attachment(kind="text", path=str(odd))]
        )


# --- contract 5: the effort ceiling, enforced at load (R-025) --------------


def _registry_text(effort: str) -> str:
    return (
        '[roles.judge]\n'
        'model = "xai/grok-4.6"\n'
        'fallbacks = []\n'
        'max_tokens = 64000\n'
        f'effort = "{effort}"\n'
    )


def test_the_declared_ceiling_is_the_intersection_not_the_superset() -> None:
    """Grok 4.6 accepts xhigh; Grok 4.5 does not. We declare the intersection.

    Declaring the superset would let a lawful config — 4.5 at xhigh — load
    clean and explode at call time, the exact failure R-025 exists to prevent.
    """
    assert GrokAdapter.EFFORT_LEVELS == ("low", "medium", "high")


def test_effort_above_the_xai_ceiling_fails_at_load(tmp_path: Path) -> None:
    path = tmp_path / "registry.toml"
    path.write_text(_registry_text("xhigh"), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    message = str(excinfo.value)
    assert "judge" in message
    assert "xai" in message
    assert "xhigh" in message
    assert "low, medium, high" in message


def test_the_same_registry_loads_clean_at_high(tmp_path: Path) -> None:
    """The discriminating half: only the level differs between these two."""
    path = tmp_path / "registry.toml"
    path.write_text(_registry_text("high"), encoding="utf-8")
    assert load_registry(path).resolve("judge").effort == "high"


def test_litellm_itself_would_not_have_caught_it() -> None:
    """Why load-time validation is the only guard (contract 5's reasoning).

    LiteLLM passes every level straight through for xai, validating none of
    them — including levels no Grok model accepts. Nothing below our registry
    stands between a typo and a provider error.
    """
    from litellm.llms.xai.chat.transformation import XAIChatConfig

    for level in ("xhigh", "max", "not-a-level"):
        body = XAIChatConfig().transform_request(
            model=MODEL,
            messages=[{"role": "user", "content": "hi"}],
            optional_params={"reasoning_effort": level},
            litellm_params={},
            headers={},
        )
        assert body["reasoning_effort"] == level
