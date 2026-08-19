"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: test run_turn — the turn sequence, the merge rules, the contradiction
lifecycle, and the promise that the engine never writes a word of the interview.

Both brains are fakes here. That is the design, not a limitation: the engine has
to be correct with a mediocre model on the other end.

Version: 0.1.0
"""

from __future__ import annotations

from typing import Any

from intent import (
    ScribeUpdate,
    completeness,
    is_complete,
    new_state,
    run_turn,
)
from intent.skeleton import BOX_KEYS, BY_INTERVIEWER, BY_USER, CONFIRMED, PROPOSED

FULL: dict[str, dict[str, Any]] = {
    "goal": {"summary": "a tool", "victory_conditions": ["ships", "is used"]},
    "users": {"users": [{"name": "founder", "needs": "speed"}]},
    "workflows": {"workflows": [{"story": "uploads", "mode": "automate"}]},
    "data": {"entities": ["invoice"], "sensitive": []},
    "boundaries": {"exclusions": ["no payments"]},
    "non_negotiables": {"security_level": "standard", "scale": "small",
                        "budget": "$100/mo"},
    "website": {"needed": False},
}


class FakeInterviewer:
    """Returns a scripted line and records exactly what it was steered with."""

    def __init__(self, lines: list[str] | None = None) -> None:
        self.lines = lines or ["What are we building?"]
        self.calls: list[dict[str, Any]] = []

    def __call__(self, transcript, box_status, directives) -> str:
        self.calls.append(
            {"transcript": list(transcript), "box_status": dict(box_status),
             "directives": dict(directives)}
        )
        index = min(len(self.calls) - 1, len(self.lines) - 1)
        return self.lines[index]


class ScriptedScribe:
    """Returns a queued ScribeUpdate per turn; an empty queue extracts nothing."""

    def __init__(self, updates: list[ScribeUpdate]) -> None:
        self.updates = list(updates)
        self.calls = 0

    def __call__(self, transcript, current_boxes) -> ScribeUpdate:
        self.calls += 1
        return self.updates.pop(0) if self.updates else ScribeUpdate()


def _fill_all(confirm: bool) -> ScribeUpdate:
    return ScribeUpdate(
        boxes=dict(FULL),
        confirmed_by_user=list(FULL) if confirm else [],
    )


# --- the happy path ---------------------------------------------------------


def test_three_turns_to_a_complete_interview() -> None:
    state = new_state("demo")
    interviewer = FakeInterviewer(["Q1", "Q2", "Q3"])
    scribe = ScriptedScribe([
        ScribeUpdate(boxes={"goal": FULL["goal"]}, confirmed_by_user=["goal"]),
        ScribeUpdate(boxes={k: v for k, v in FULL.items() if k != "goal"}),
        ScribeUpdate(confirmed_by_user=[k for k in FULL if k != "goal"]),
    ])

    state, first = run_turn(state, "it is a tool", interviewer, scribe)
    assert first.complete is False and first.reply == "Q1"

    state, second = run_turn(state, "here is everything", interviewer, scribe)
    assert second.complete is False, "proposed content is not consent"
    assert set(second.pending_confirmations) == {k for k in FULL if k != "goal"}

    state, third = run_turn(state, "yes, all correct", interviewer, scribe)
    assert third.complete is True
    assert third.reply is None
    assert is_complete(state) is True


def test_completeness_flips_only_on_confirmation_not_on_content() -> None:
    """The discriminating moment: everything is present a full turn before the
    interview is allowed to end."""
    state = new_state("demo")
    scribe = ScriptedScribe([_fill_all(confirm=False), _fill_all(confirm=True)])
    interviewer = FakeInterviewer()

    state, result = run_turn(state, "all of it", interviewer, scribe)
    assert result.complete is False
    assert all(state.boxes[k].status == PROPOSED for k in FULL)
    assert not any(completeness(state)[k] for k in FULL)

    state, result = run_turn(state, "yes", interviewer, scribe)
    assert result.complete is True


def test_the_transcript_records_both_voices_in_order() -> None:
    state = new_state("demo")
    state, _ = run_turn(state, "hello", FakeInterviewer(["Q1"]), ScriptedScribe([]))
    assert [(t.role, t.content) for t in state.transcript] == [
        ("user", "hello"), ("interviewer", "Q1")
    ]
    assert state.turn_count == 1


def test_a_completed_turn_appends_no_interviewer_line() -> None:
    """Nothing is asked after the interview is done."""
    state = new_state("demo")
    scribe = ScriptedScribe([_fill_all(confirm=True)])
    state, result = run_turn(state, "everything", FakeInterviewer(), scribe)
    assert result.complete is True
    assert [t.role for t in state.transcript] == ["user"]


def test_attachments_are_stored_faithfully_and_otherwise_untouched() -> None:
    state = new_state("demo")
    state, _ = run_turn(
        state, "see this", FakeInterviewer(), ScriptedScribe([]),
        attachments=["/tmp/spec.pdf", "/tmp/logo.png"],
    )
    assert state.transcript[0].attachments == ["/tmp/spec.pdf", "/tmp/logo.png"]


# --- the engine writes no prose ---------------------------------------------


def test_the_reply_is_the_interviewers_string_verbatim() -> None:
    """Charm is the model's job. If the engine ever decorates a reply, the
    interview stops being the model's voice and starts being ours."""
    exact = "So — what are we actually building here?  (and why now?)\n\n…"
    state = new_state("demo")
    state, result = run_turn(state, "hi", FakeInterviewer([exact]), ScriptedScribe([]))
    assert result.reply == exact
    assert state.transcript[-1].content == exact


def test_the_directives_are_structure_never_text() -> None:
    state = new_state("demo")
    interviewer = FakeInterviewer()
    run_turn(state, "hi", interviewer, ScriptedScribe([]))
    directives = interviewer.calls[0]["directives"]

    assert directives["ask_one_question"] is True
    assert directives["incomplete_boxes"] == [k for k in BOX_KEYS if k != "research"]
    assert directives["unsurfaced_contradiction"] is None
    assert set(directives) == {
        "incomplete_boxes", "pending_confirmations",
        "unsurfaced_contradiction", "ask_one_question",
    }


def test_incomplete_boxes_arrive_in_skeleton_order() -> None:
    state = new_state("demo")
    interviewer = FakeInterviewer()
    run_turn(state, "hi", interviewer, ScriptedScribe([
        ScribeUpdate(boxes={"website": FULL["website"]},
                     confirmed_by_user=["website"])
    ]))
    incomplete = interviewer.calls[0]["directives"]["incomplete_boxes"]
    assert incomplete == [k for k in BOX_KEYS if k not in ("research", "website")]


# --- deflection: proposed defaults (R-033b) ---------------------------------


def test_a_deflected_box_is_proposed_by_the_interviewer_and_awaits_a_yes() -> None:
    state = new_state("demo")
    scribe = ScriptedScribe([
        ScribeUpdate(
            boxes={"non_negotiables": FULL["non_negotiables"]},
            proposed_by={"non_negotiables": BY_INTERVIEWER},
        ),
        ScribeUpdate(confirmed_by_user=["non_negotiables"]),
    ])
    interviewer = FakeInterviewer()

    state, result = run_turn(state, "you decide", interviewer, scribe)
    box = state.boxes["non_negotiables"]
    assert box.status == PROPOSED
    assert box.proposed_by == BY_INTERVIEWER
    assert "non_negotiables" in result.pending_confirmations

    state, result = run_turn(state, "yes that's fine", interviewer, scribe)
    assert state.boxes["non_negotiables"].status == CONFIRMED
    assert state.boxes["non_negotiables"].proposed_by == BY_INTERVIEWER
    assert "non_negotiables" not in result.pending_confirmations


def test_there_is_no_path_from_proposed_to_confirmed_without_a_user_turn() -> None:
    """Asserted by exhaustion: many turns of the Scribe proposing, and nothing
    is ever confirmed until confirmed_by_user names it."""
    state = new_state("demo")
    scribe = ScriptedScribe([_fill_all(confirm=False) for _ in range(5)])
    for _ in range(5):
        state, result = run_turn(state, "more detail", FakeInterviewer(), scribe)
        assert result.complete is False
    assert all(state.boxes[k].status == PROPOSED for k in FULL)


def test_content_authored_by_the_user_is_recorded_as_theirs() -> None:
    state = new_state("demo")
    run_turn(state, "the goal is X", FakeInterviewer(),
             ScriptedScribe([ScribeUpdate(boxes={"goal": FULL["goal"]})]))
    assert state.boxes["goal"].proposed_by == BY_USER
