"""Packet: P-006 — Attachments: Text Kind (.md / .txt).

One job: test adapter selection and the Anthropic message shaping — cache
marking and attachment encoding for every attachment kind.

Version: 0.6.0
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from switchboard.adapters import AnthropicAdapter, OpenAIAdapter, adapter_for
from switchboard.request import Attachment, Message

USER_TURN = [Message(role="user", content="ping")]
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _png(tmp_path: Path, name: str = "pixel.png") -> Path:
    path = tmp_path / name
    path.write_bytes(PNG_BYTES)
    return path


def test_anthropic_model_selects_the_anthropic_adapter() -> None:
    assert isinstance(adapter_for("anthropic/claude-opus-5"), AnthropicAdapter)


def test_openai_model_selects_the_openai_adapter() -> None:
    assert isinstance(adapter_for("openai/gpt-5.6-terra"), OpenAIAdapter)


def test_unknown_family_selects_no_adapter() -> None:
    assert adapter_for("mistral/large") is None


def test_system_becomes_a_cache_marked_block() -> None:
    prepared = AnthropicAdapter().prepare("stable instructions", USER_TURN, [])
    first = prepared[0]
    assert first["role"] == "system"
    assert isinstance(first["content"], list)
    assert first["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert first["content"][-1]["text"] == "stable instructions"


def test_no_system_emits_no_system_message() -> None:
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [])
    assert [message["role"] for message in prepared] == ["user"]


def test_user_messages_are_never_cache_marked() -> None:
    prepared = AnthropicAdapter().prepare("stable", USER_TURN, [])
    assert prepared[-1]["content"] == "ping"


def test_image_attachment_becomes_a_base64_image_part(tmp_path: Path) -> None:
    attachment = Attachment(kind="image", path=str(_png(tmp_path)))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    parts = prepared[-1]["content"]
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "ping"}
    image = next(part for part in parts if part["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/png;base64,")
    assert base64.b64encode(PNG_BYTES).decode() in image["image_url"]["url"]


def test_pdf_attachment_becomes_a_base64_pdf_part(tmp_path: Path) -> None:
    path = tmp_path / "page.pdf"
    path.write_bytes(b"%PDF-1.4 minimal")
    attachment = Attachment(kind="pdf", path=str(path))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    parts = prepared[-1]["content"]
    document = next(part for part in parts if part["type"] == "file")
    assert document["file"]["file_data"].startswith(
        "data:application/pdf;base64,"
    )


def test_both_attachments_ride_the_last_user_message(tmp_path: Path) -> None:
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")
    prepared = AnthropicAdapter().prepare(
        "stable",
        USER_TURN,
        [
            Attachment(kind="image", path=str(_png(tmp_path))),
            Attachment(kind="pdf", path=str(pdf)),
        ],
    )
    kinds = [part["type"] for part in prepared[-1]["content"]]
    assert kinds == ["text", "image_url", "file"]


def test_missing_attachment_file_raises_naming_the_path(tmp_path: Path) -> None:
    missing = str(tmp_path / "absent.png")
    attachment = Attachment(kind="image", path=missing)
    with pytest.raises(FileNotFoundError) as excinfo:
        AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    assert missing in str(excinfo.value)


def test_unknown_image_extension_raises_naming_it(tmp_path: Path) -> None:
    path = tmp_path / "photo.bmp"
    path.write_bytes(PNG_BYTES)
    attachment = Attachment(kind="image", path=str(path))
    with pytest.raises(ValueError) as excinfo:
        AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    assert ".bmp" in str(excinfo.value)


# --- P-006: the text kind (.md / .txt) ------------------------------------


def _text_file(tmp_path: Path, name: str, body: str = "# Foundry test\nP-006") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _parts(prepared: list[dict]) -> list[dict]:
    return prepared[-1]["content"]


def _document(prepared: list[dict]) -> dict:
    return next(part for part in _parts(prepared) if part["type"] == "document")


def test_markdown_attachment_becomes_a_text_source_document(tmp_path: Path) -> None:
    """T-003 shape, observed through AnthropicConfig.transform_request (R-022).

    A base64 document source is PDF-only at the API, so text rides raw under
    source.type "text" — not as a base64 data URL.
    """
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.md")))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    source = _document(prepared)["source"]
    assert source["type"] == "text"
    assert source["media_type"] == "text/plain"


def test_markdown_carries_its_content_raw_not_base64(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.md")))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    assert _document(prepared)["source"]["data"] == "# Foundry test\nP-006"


def test_txt_is_accepted_identically(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.txt")))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    source = _document(prepared)["source"]
    assert source["type"] == "text" and source["media_type"] == "text/plain"


def test_unknown_text_extension_raises_naming_it(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.rst")))
    with pytest.raises(ValueError) as excinfo:
        AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    assert ".rst" in str(excinfo.value)


def test_missing_text_file_raises_naming_the_path(tmp_path: Path) -> None:
    missing = str(tmp_path / "absent.md")
    with pytest.raises(FileNotFoundError) as excinfo:
        AnthropicAdapter().prepare(None, USER_TURN, [Attachment(kind="text", path=missing)])
    assert missing in str(excinfo.value)


def test_base64_payloads_contain_no_newlines(tmp_path: Path) -> None:
    """The API requires newline-free base64 — assert it, never assume it.

    Void for the text kind after T-003 (it carries raw content, no base64);
    still binding for pdf and image, which do.
    """
    pdf = tmp_path / "long.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"filler bytes for a multi-line document " * 200)
    prepared = AnthropicAdapter().prepare(
        None,
        USER_TURN,
        [
            Attachment(kind="image", path=str(_png(tmp_path))),
            Attachment(kind="pdf", path=str(pdf)),
        ],
    )
    urls = [part["image_url"]["url"] for part in _parts(prepared) if part["type"] == "image_url"]
    urls += [part["file"]["file_data"] for part in _parts(prepared) if part["type"] == "file"]
    for url in urls:
        payload = url.split("base64,", 1)[1]
        assert "\n" not in payload and "\r" not in payload


def test_all_three_kinds_ride_the_last_user_message_in_order(tmp_path: Path) -> None:
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")
    prepared = AnthropicAdapter().prepare(
        "stable",
        USER_TURN,
        [
            Attachment(kind="image", path=str(_png(tmp_path))),
            Attachment(kind="pdf", path=str(pdf)),
            Attachment(kind="text", path=str(_text_file(tmp_path, "notes.md"))),
        ],
    )
    parts = _parts(prepared)
    assert [part["type"] for part in parts] == ["text", "image_url", "file", "document"]
    assert parts[2]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert parts[3]["source"]["type"] == "text"


# --- R-022: verify shapes through the provider's real transformation ------
#
# The offline suite was green while the live call was malformed (T-003),
# because the fixtures asserted our implementation's shape rather than the
# API's. These run the adapter's real output through LiteLLM's real Anthropic
# transformation — the same check that refuted H1 in T-002 — so a payload the
# provider would reject fails here instead of on the human's smoke run.


def _transformed(prepared: list[dict]) -> list[dict]:
    """Our adapter output, as Anthropic would actually receive it."""
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    request = AnthropicConfig().transform_request(
        model="claude-haiku-4-5-20251001",
        messages=prepared,
        optional_params={},
        litellm_params={},
        headers={},
    )
    return request["messages"][-1]["content"]


def test_transformation_keeps_text_documents_on_a_text_source(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.md")))
    blocks = _transformed(AnthropicAdapter().prepare(None, USER_TURN, [attachment]))
    document = next(b for b in blocks if b["type"] == "document")
    assert document["source"]["type"] == "text"
    assert document["source"]["data"] == "# Foundry test\nP-006"


def test_transformation_emits_no_illegal_base64_document(tmp_path: Path) -> None:
    """The exact defect T-003 hit: base64 document sources are PDF-only."""
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")
    blocks = _transformed(
        AnthropicAdapter().prepare(
            None,
            USER_TURN,
            [
                Attachment(kind="image", path=str(_png(tmp_path))),
                Attachment(kind="pdf", path=str(pdf)),
                Attachment(kind="text", path=str(_text_file(tmp_path, "notes.md"))),
            ],
        )
    )
    sources = [b["source"] for b in blocks if b["type"] == "document"]
    assert sorted((s["type"], s["media_type"]) for s in sources) == [
        ("base64", "application/pdf"),
        ("text", "text/plain"),
    ]
    illegal = [
        s for s in sources if s["type"] == "base64" and s["media_type"] != "application/pdf"
    ]
    assert not illegal, f"provider would reject: {illegal}"


def test_transformation_keeps_the_cache_mark_on_the_system_block() -> None:
    prepared = AnthropicAdapter().prepare("stable instructions", USER_TURN, [])
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    request = AnthropicConfig().transform_request(
        model="claude-haiku-4-5-20251001",
        messages=prepared,
        optional_params={},
        litellm_params={},
        headers={},
    )
    assert request["system"][-1]["cache_control"] == {"type": "ephemeral"}
