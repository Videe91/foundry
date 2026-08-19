"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: test the contradiction lifecycle (R-033a) — that a conflict with
settled content is recorded and demotes the box, reaches the Interviewer exactly
once, blocks completion until resolved, and is never manufactured out of
agreement.

Split from test_engine.py under R-017 when it reached the 300-line ceiling; per
R-026 the split inherits its parent's map entries.

Version: 0.1.0
"""

from __future__ import annotations

from intent import Contradiction, ScribeUpdate, is_complete, new_state, run_turn
from intent.skeleton import BOX_KEYS, CONFIRMED, PROPOSED
from test_engine import FULL, FakeInterviewer, ScriptedScribe, _fill_all


# --- contradictions (R-033a) ------------------------------------------------


def test_contradicting_a_confirmed_box_surfaces_and_demotes_it() -> None:
    state = new_state("demo")
    interviewer = FakeInterviewer(["Q1", "Q2", "Q3"])
    changed = {"summary": "a different tool",
               "victory_conditions": ["ships fast", "is loved"]}
    scribe = ScriptedScribe([
        ScribeUpdate(boxes={"goal": FULL["goal"]}, confirmed_by_user=["goal"]),
        ScribeUpdate(boxes={"goal": changed}),
        ScribeUpdate(confirmed_by_user=["goal"], resolved_contradictions=["goal"]),
    ])

    state, _ = run_turn(state, "the goal is X", interviewer, scribe)
    assert state.boxes["goal"].status == CONFIRMED

    state, _ = run_turn(state, "actually the goal is Y", interviewer, scribe)
    assert len(state.contradictions) == 1
    conflict = state.contradictions[0]
    assert conflict.box_key == "goal"
    assert "a tool" in conflict.earlier and "a different tool" in conflict.later
    assert state.boxes["goal"].status == PROPOSED, "a conflicted box is demoted"
    assert state.boxes["goal"].content == changed, "latest wins on content"

    state, _ = run_turn(state, "yes, Y is right", interviewer, scribe)
    assert state.contradictions[0].resolved is True
    assert is_complete(state) is False  # other boxes still empty


def test_an_unresolved_contradiction_blocks_completion_outright() -> None:
    """A signed constitution may not contain a conflict someone noticed."""
    state = new_state("demo")
    scribe = ScriptedScribe([_fill_all(confirm=True)])
    state, result = run_turn(state, "everything", FakeInterviewer(), scribe)
    assert result.complete is True

    state.contradictions.append(
        Contradiction(box_key="goal", earlier="X", later="Y")
    )
    assert is_complete(state) is False


def test_a_contradiction_reaches_the_interviewer_exactly_once() -> None:
    state = new_state("demo")
    interviewer = FakeInterviewer(["Q1", "Q2", "Q3"])
    scribe = ScriptedScribe([
        ScribeUpdate(contradictions=[
            Contradiction(box_key="goal", earlier="X", later="Y")
        ]),
    ])

    run_turn(state, "one", interviewer, scribe)
    first = interviewer.calls[0]["directives"]["unsurfaced_contradiction"]
    assert first is not None and first["box_key"] == "goal"
    assert state.contradictions[0].surfaced is True

    run_turn(state, "two", interviewer, scribe)
    assert interviewer.calls[1]["directives"]["unsurfaced_contradiction"] is None


def test_at_most_one_contradiction_is_carried_per_turn() -> None:
    state = new_state("demo")
    interviewer = FakeInterviewer()
    scribe = ScriptedScribe([
        ScribeUpdate(contradictions=[
            Contradiction(box_key="goal", earlier="X", later="Y"),
            Contradiction(box_key="users", earlier="A", later="B"),
        ]),
    ])
    run_turn(state, "both", interviewer, scribe)
    carried = interviewer.calls[0]["directives"]["unsurfaced_contradiction"]
    assert carried["box_key"] == "goal", "the oldest is surfaced first"
    assert sum(c.surfaced for c in state.contradictions) == 1


def test_restating_confirmed_content_unchanged_is_not_a_contradiction() -> None:
    """Discriminating: a scribe that re-reports the same box every turn must
    not manufacture a conflict out of agreement."""
    state = new_state("demo")
    scribe = ScriptedScribe([
        ScribeUpdate(boxes={"goal": FULL["goal"]}, confirmed_by_user=["goal"]),
        ScribeUpdate(boxes={"goal": dict(FULL["goal"])}),
    ])
    interviewer = FakeInterviewer()

    run_turn(state, "the goal is X", interviewer, scribe)
    run_turn(state, "as I said, X", interviewer, scribe)

    assert state.contradictions == []
    assert state.boxes["goal"].status == CONFIRMED, "agreement does not demote"


def test_an_unknown_box_key_from_the_scribe_is_ignored() -> None:
    """The Scribe is a model; the skeleton is the law."""
    state = new_state("demo")
    run_turn(state, "hi", FakeInterviewer(),
             ScriptedScribe([ScribeUpdate(boxes={"vibes": {"x": 1}})]))
    assert set(state.boxes) == set(BOX_KEYS)


def test_confirming_an_empty_box_does_nothing() -> None:
    """Consent to nothing is not consent."""
    state = new_state("demo")
    run_turn(state, "yes", FakeInterviewer(),
             ScriptedScribe([ScribeUpdate(confirmed_by_user=["goal"])]))
    assert state.boxes["goal"].status != CONFIRMED
