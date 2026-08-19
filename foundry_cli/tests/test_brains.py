"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: test the composition edge — that the Interviewer streams while
returning the Switchboard's own assembled content, that the Scribe's JSON is
parsed with exactly one corrective retry, and that every call carries its tags.

Version: 0.1.0
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import (
    FULL_BOXES,
    SLUG,
    FakeRoute,
    fake_registry,
    scribe_json,
)

from foundry_cli.brains import (
    RETRY_INSTRUCTION,
    Brains,
    ScribeParseError,
    attachment_for,
    strip_fences,
)
from intent.state import ScribeUpdate, Turn

TRANSCRIPT = [Turn(role="user", content="I want a tool")]


def _brains(route: FakeRoute, **kwargs) -> Brains:
    return Brains(slug=SLUG, registry=fake_registry(), route=route, **kwargs)


# --- the Interviewer streams, but the record is route_call's ---------------


def test_deltas_reach_the_callback_as_they_arrive() -> None:
    seen: list[str] = []
    route = FakeRoute(replies=["Hello?"])
    brains = _brains(route, on_delta=seen.append)

    brains.interviewer(TRANSCRIPT, {}, {"ask_one_question": True})
    assert "".join(seen) == "Hello?"


def test_the_stored_reply_is_route_calls_content_not_a_rejoined_buffer() -> None:
    """Discriminating: the fake streams deltas that differ from the returned
    content by one character. If the engine ever stores the join of what it
    printed, the two drift and nobody notices until a transcript is wrong.
    One source of truth — the R-018 lesson."""
    route = FakeRoute(replies=["the real reply"], stream_text="the real replyX")
    seen: list[str] = []
    brains = _brains(route, on_delta=seen.append)

    stored = brains.interviewer(TRANSCRIPT, {}, {})
    assert "".join(seen) == "the real replyX"
    assert stored == "the real reply"


def test_the_interviewer_is_told_the_state_but_writes_its_own_words() -> None:
    route = FakeRoute()
    _brains(route).interviewer(
        TRANSCRIPT, {"goal": "empty"},
        {"incomplete_boxes": ["goal"], "ask_one_question": True},
    )
    system = route.calls[0]["system"]
    assert "incomplete_boxes" in system and "goal" in system
    assert "ask one good question" in system.lower()


def test_the_transcript_reaches_the_model_with_roles_translated() -> None:
    route = FakeRoute()
    transcript = [
        Turn(role="user", content="first"),
        Turn(role="interviewer", content="a question"),
    ]
    _brains(route).interviewer(transcript, {}, {})
    roles = [m.role for m in route.calls[0]["request"].messages]
    assert roles == ["user", "assistant"]


# --- the Scribe's JSON discipline ------------------------------------------


def test_valid_json_becomes_a_scribe_update() -> None:
    route = FakeRoute(replies=[scribe_json(boxes={"goal": FULL_BOXES["goal"]},
                                           confirmed_by_user=["goal"])])
    update = _brains(route).scribe(TRANSCRIPT, {})
    assert isinstance(update, ScribeUpdate)
    assert update.confirmed_by_user == ["goal"]


def test_fenced_json_is_unwrapped() -> None:
    fenced = "```json\n" + scribe_json(confirmed_by_user=["goal"]) + "\n```"
    update = _brains(FakeRoute(replies=[fenced])).scribe(TRANSCRIPT, {})
    assert update.confirmed_by_user == ["goal"]


@pytest.mark.parametrize(
    "text",
    ["```json\n{}\n```", "```\n{}\n```", "{}", "  {}  "],
)
def test_strip_fences_handles_the_shapes_models_actually_emit(text: str) -> None:
    assert json.loads(strip_fences(text)) == {}


def test_a_malformed_reply_gets_exactly_one_corrective_retry() -> None:
    route = FakeRoute(replies=["I think the goal is a tool!",
                               scribe_json(confirmed_by_user=["goal"])])
    update = _brains(route).scribe(TRANSCRIPT, {})

    assert update.confirmed_by_user == ["goal"]
    assert len(route.calls) == 2
    assert RETRY_INSTRUCTION in route.calls[1]["messages"][-1]
    assert RETRY_INSTRUCTION not in " ".join(route.calls[0]["messages"])


def test_two_failures_raise_naming_the_role_and_keeping_the_reply(
    project,
) -> None:
    """A lost extraction is a lost user answer — never a silent empty update."""
    route = FakeRoute(replies=["nope", "still nope"])
    brains = _brains(route, project=project)

    with pytest.raises(ScribeParseError) as excinfo:
        brains.scribe(TRANSCRIPT, {})
    message = str(excinfo.value)
    assert "scribe" in message
    assert "still nope" in message

    logged = Path(project.build_log_path).read_text(encoding="utf-8")
    assert "still nope" in logged, "the raw reply was not preserved"


def test_a_never_valid_scribe_does_not_retry_forever() -> None:
    route = FakeRoute(replies=["a", "b", "c", "d"])
    with pytest.raises(ScribeParseError):
        _brains(route).scribe(TRANSCRIPT, {})
    assert len(route.calls) == 2, "one retry, not a loop"


# --- tags and receipts ------------------------------------------------------


def test_every_call_carries_the_full_tag_set() -> None:
    route = FakeRoute(replies=[scribe_json(), "a question"])
    brains = _brains(route)
    brains.turn_number = 3
    brains.scribe(TRANSCRIPT, {})
    brains.interviewer(TRANSCRIPT, {}, {})

    assert route.roles() == ["scribe", "interviewer"]
    for call in route.calls:
        tags = call["tags"]
        assert tags.project_id == SLUG
        assert tags.department == "intent"
        assert tags.role in ("scribe", "interviewer")
        assert tags.attempt_number == 3


def test_receipts_are_collected_for_the_session_summary() -> None:
    route = FakeRoute(replies=[scribe_json(), "q"])
    brains = _brains(route)
    brains.scribe(TRANSCRIPT, {})
    brains.interviewer(TRANSCRIPT, {}, {})
    assert len(brains.receipts) == 2


# --- attachments ------------------------------------------------------------


def test_a_queued_attachment_rides_both_brains(tmp_path: Path) -> None:
    """The Scribe needs the document too — it is the one doing the extracting."""
    doc = tmp_path / "spec.md"
    doc.write_text("# spec", encoding="utf-8")
    route = FakeRoute(replies=[scribe_json(), "q"])
    brains = _brains(route)
    brains.attachments = [attachment_for(doc)]

    brains.scribe(TRANSCRIPT, {})
    brains.interviewer(TRANSCRIPT, {}, {})
    assert all(len(call["attachments"]) == 1 for call in route.calls)
    assert {call["attachments"][0].kind for call in route.calls} == {"text"}


@pytest.mark.parametrize(
    ("name", "kind"),
    [("a.png", "image"), ("a.pdf", "pdf"), ("a.md", "text"), ("a.txt", "text")],
)
def test_known_extensions_map_to_kinds(tmp_path: Path, name: str, kind: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"x")
    assert attachment_for(path).kind == kind


def test_a_missing_file_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no such file"):
        attachment_for(tmp_path / "ghost.png")


def test_an_unknown_extension_is_refused_and_says_what_is_known(
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.rtf"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        attachment_for(path)
    assert ".rtf" in str(excinfo.value) and ".pdf" in str(excinfo.value)
