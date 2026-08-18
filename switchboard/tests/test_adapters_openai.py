"""Packet: P-007 — Family Two: OpenAI Adapter.

One job: test the OpenAI family's message shaping — plain system message, no
cache marks, and all three attachment kinds — with every emitted shape verified
through LiteLLM's real OpenAI transformation per R-022.

Split from test_adapters.py under the R-017 precedent; that file was at 284
lines and holds the Anthropic family.

Version: 0.7.0
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from switchboard.adapters import OpenAIAdapter
from switchboard.request import Attachment, Message

USER_TURN = [Message(role="user", content="name them")]
BODY = "# Foundry test\nP-007"
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


def _transformed(prepared: list[dict]) -> dict:
    """Our adapter output, as OpenAI would actually receive it (R-022)."""
    from litellm.llms.openai.chat.gpt_transformation import OpenAIGPTConfig

    return OpenAIGPTConfig().transform_request(
        model="gpt-5.6-terra",
        messages=prepared,
        optional_params={},
        litellm_params={},
        headers={},
    )


# --- system handling ------------------------------------------------------


def test_system_becomes_a_plain_leading_message() -> None:
    prepared = OpenAIAdapter().prepare("be brief", USER_TURN, [])
    assert prepared[0] == {"role": "system", "content": "be brief"}


def test_no_system_emits_no_system_message() -> None:
    prepared = OpenAIAdapter().prepare(None, USER_TURN, [])
    assert [message["role"] for message in prepared] == ["user"]


def test_no_cache_control_anywhere(tmp_path: Path) -> None:
    """OpenAI caching is provider-side on repeated prefixes, never a mark."""
    prepared = OpenAIAdapter().prepare(
        "be brief", USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
    )
    assert "cache_control" not in json.dumps(prepared)
    assert "cache_control" not in json.dumps(_transformed(prepared))


# --- attachments, all three kinds ----------------------------------------


def test_image_becomes_a_base64_data_url(tmp_path: Path) -> None:
    prepared = OpenAIAdapter().prepare(
        None, USER_TURN, [Attachment(kind="image", path=str(_png(tmp_path)))]
    )
    image = next(part for part in _parts(prepared) if part["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


def test_pdf_becomes_a_file_part_named_for_the_file(tmp_path: Path) -> None:
    prepared = OpenAIAdapter().prepare(
        None, USER_TURN, [Attachment(kind="pdf", path=str(_pdf(tmp_path)))]
    )
    document = next(part for part in _parts(prepared) if part["type"] == "file")
    assert document["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert document["file"]["filename"] == "page.pdf"


def test_text_becomes_a_text_plain_file_part(tmp_path: Path) -> None:
    """R-022 discovery: of the two candidate shapes, the file part with a
    text/plain data URL survives LiteLLM's OpenAI transformation with its
    content intact — see test_transformation_preserves_text_content below."""
    prepared = OpenAIAdapter().prepare(
        None, USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
    )
    document = next(part for part in _parts(prepared) if part["type"] == "file")
    assert document["file"]["file_data"].startswith("data:text/plain;base64,")
    assert document["file"]["filename"] == "notes.md"


def test_all_three_kinds_ride_the_last_user_message_in_order(tmp_path: Path) -> None:
    prepared = OpenAIAdapter().prepare(
        "be brief",
        USER_TURN,
        [
            Attachment(kind="image", path=str(_png(tmp_path))),
            Attachment(kind="pdf", path=str(_pdf(tmp_path))),
            Attachment(kind="text", path=str(_text(tmp_path))),
        ],
    )
    assert [part["type"] for part in _parts(prepared)] == [
        "text",
        "image_url",
        "file",
        "file",
    ]


def test_missing_file_raises_naming_the_path(tmp_path: Path) -> None:
    missing = str(tmp_path / "absent.md")
    with pytest.raises(FileNotFoundError) as excinfo:
        OpenAIAdapter().prepare(None, USER_TURN, [Attachment(kind="text", path=missing)])
    assert missing in str(excinfo.value)


def test_unknown_text_extension_raises_naming_it(tmp_path: Path) -> None:
    attachment = Attachment(kind="text", path=str(_text(tmp_path, "notes.rst")))
    with pytest.raises(ValueError) as excinfo:
        OpenAIAdapter().prepare(None, USER_TURN, [attachment])
    assert ".rst" in str(excinfo.value)


def test_unknown_image_extension_raises_naming_it(tmp_path: Path) -> None:
    attachment = Attachment(kind="image", path=str(_png(tmp_path, "photo.bmp")))
    with pytest.raises(ValueError) as excinfo:
        OpenAIAdapter().prepare(None, USER_TURN, [attachment])
    assert ".bmp" in str(excinfo.value)


# --- R-022: verified through LiteLLM's real OpenAI transformation ---------


def test_transformation_keeps_the_system_message_plain() -> None:
    request = _transformed(OpenAIAdapter().prepare("be brief", USER_TURN, []))
    assert request["messages"][0] == {"role": "system", "content": "be brief"}


def test_transformation_preserves_text_content(tmp_path: Path) -> None:
    """The discriminating check: the payload round-trips to the original text."""
    prepared = OpenAIAdapter().prepare(
        None, USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
    )
    part = next(
        p for p in _transformed(prepared)["messages"][-1]["content"] if p["type"] == "file"
    )
    payload = part["file"]["file_data"].split("base64,", 1)[1]
    assert base64.b64decode(payload).decode("utf-8") == BODY


def test_transformation_keeps_the_real_filename(tmp_path: Path) -> None:
    """R-022 finding: LiteLLM injects filename 'my_file.pdf' when none is
    given, mislabelling a text file as a PDF. Ours must survive instead."""
    prepared = OpenAIAdapter().prepare(
        None, USER_TURN, [Attachment(kind="text", path=str(_text(tmp_path)))]
    )
    part = next(
        p for p in _transformed(prepared)["messages"][-1]["content"] if p["type"] == "file"
    )
    assert part["file"]["filename"] == "notes.md"
    assert part["file"]["filename"] != "my_file.pdf"


def test_transformation_keeps_all_three_kinds_intact(tmp_path: Path) -> None:
    prepared = OpenAIAdapter().prepare(
        "be brief",
        USER_TURN,
        [
            Attachment(kind="image", path=str(_png(tmp_path))),
            Attachment(kind="pdf", path=str(_pdf(tmp_path))),
            Attachment(kind="text", path=str(_text(tmp_path))),
        ],
    )
    parts = _transformed(prepared)["messages"][-1]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url", "file", "file"]
    media = sorted(
        part["file"]["file_data"].split(";", 1)[0] for part in parts if part["type"] == "file"
    )
    assert media == ["data:application/pdf", "data:text/plain"]


def test_an_openai_route_reaches_this_adapter() -> None:
    """End to end through route_call: an openai/ model gets the plain system
    message and no cache mark."""
    from conftest import FREE, FakeCompletion, make_request

    from switchboard.registry import ModelRegistry, RoleRoute
    from switchboard.router import route_call

    registry = ModelRegistry(
        roles={
            "builder": RoleRoute(
                model="openai/gpt-5.6-terra", fallbacks=[], max_tokens=128000
            )
        }
    )
    fake = FakeCompletion()
    route_call(make_request(system="be brief"), registry, fake, FREE)
    messages = fake.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "be brief"}
    assert "cache_control" not in json.dumps(messages)
