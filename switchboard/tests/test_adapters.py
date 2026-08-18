"""Packet: P-006 — Attachments: Text Kind (.md / .txt).

One job: test adapter selection and the Anthropic message shaping — cache
marking and attachment encoding for every attachment kind.

Version: 0.6.0
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from switchboard.adapters import AnthropicAdapter, adapter_for
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


def test_non_anthropic_model_selects_no_adapter() -> None:
    assert adapter_for("openai/gpt-5.2") is None


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


def test_markdown_attachment_becomes_a_plain_text_file_part(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.md")))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    document = next(part for part in _parts(prepared) if part["type"] == "file")
    assert document["file"]["file_data"].startswith("data:text/plain;base64,")


def test_markdown_payload_round_trips_to_the_original_text(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.md")))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    document = next(part for part in _parts(prepared) if part["type"] == "file")
    payload = document["file"]["file_data"].split("base64,", 1)[1]
    assert base64.b64decode(payload).decode("utf-8") == "# Foundry test\nP-006"


def test_txt_is_accepted_identically(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text_file(tmp_path, "notes.txt")))
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    document = next(part for part in _parts(prepared) if part["type"] == "file")
    assert document["file"]["file_data"].startswith("data:text/plain;base64,")


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


def test_encoded_payload_contains_no_newlines(tmp_path: Path) -> None:
    """The API requires newline-free base64 — assert it, never assume it."""
    long_body = "# Foundry\n" + ("filler line for a multi-line document\n" * 200)
    attachment = Attachment(
        kind="text", path=str(_text_file(tmp_path, "long.md", long_body))
    )
    prepared = AnthropicAdapter().prepare(None, USER_TURN, [attachment])
    document = next(part for part in _parts(prepared) if part["type"] == "file")
    payload = document["file"]["file_data"].split("base64,", 1)[1]
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
    assert [part["type"] for part in parts] == ["text", "image_url", "file", "file"]
    assert parts[2]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert parts[3]["file"]["file_data"].startswith("data:text/plain;base64,")
