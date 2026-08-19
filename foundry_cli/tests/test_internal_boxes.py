"""Packet: T-009 — the research-box leak.

One job: prove no internal box name reaches a model, at the level a model
actually sees — the rendered prompt string.

Honest about its reach: this is a STRING check over the prompts this code
builds. It cannot prove a model will never say "research" (it might, from its
own priors, or because a founder does), and it cannot see a prompt some future
composer builds elsewhere. What it does prove is that nothing here puts the word
in front of a model, which is what T-009 actually was.

Version: 0.1.0
"""

from __future__ import annotations

import json

import pytest
from conftest import FULL_BOXES, SLUG, FakeRoute, fake_registry, scribe_json

from foundry_cli.brains import (
    INTERVIEWER_SYSTEM,
    Brains,
    scribe_system,
)
from intent import build_directives, new_state, run_turn
from intent.engine import box_status
from intent.skeleton import CONVERSATIONAL_KEYS, INTERNAL_KEYS, SKELETON


def _brains(route: FakeRoute) -> Brains:
    return Brains(slug=SLUG, registry=fake_registry(), route=route)


def _model_visible_text(call: dict) -> str:
    """Everything in one call a model can read: system block and messages."""
    return (call["system"] or "") + "\n" + "\n".join(call["messages"])


# --- the declaration --------------------------------------------------------


def test_research_is_declared_internal_in_the_skeleton() -> None:
    assert INTERNAL_KEYS == ("research",)
    assert "research" not in CONVERSATIONAL_KEYS


def test_conversational_keys_are_derived_not_listed_again() -> None:
    """A second hand-written list is a second thing to forget to update."""
    assert CONVERSATIONAL_KEYS == tuple(
        box.key for box in SKELETON if not box.internal
    )


# --- the leak, at the string level -----------------------------------------


@pytest.mark.parametrize("internal_key", INTERNAL_KEYS)
def test_the_rendered_interviewer_prompt_names_no_internal_box(
    internal_key: str,
) -> None:
    """The exact leak: a full status map put "research": "confirmed" in front
    of the Interviewer on every single turn."""
    state = new_state(SLUG)
    rendered = (
        INTERVIEWER_SYSTEM
        + json.dumps({"box_status": box_status(state), **build_directives(state)})
    )
    assert internal_key not in rendered


@pytest.mark.parametrize("internal_key", INTERNAL_KEYS)
def test_the_scribe_system_prompt_names_no_internal_box(
    internal_key: str,
) -> None:
    """The second door: the prompt spelled the eight keys inline, research
    among them, so the Scribe was told about a box that is not the founder's."""
    assert internal_key not in scribe_system()


def test_the_scribe_prompt_still_names_every_conversational_box() -> None:
    """Discriminating: a prompt that named NO boxes would pass the leak test
    and leave the Scribe unable to do its job."""
    system = scribe_system()
    for key in CONVERSATIONAL_KEYS:
        assert key in system, f"the Scribe was not told about {key}"


@pytest.mark.parametrize("internal_key", INTERNAL_KEYS)
def test_no_internal_box_reaches_either_brain_on_a_real_turn(
    internal_key: str,
) -> None:
    """End to end through run_turn: every call, system block and messages."""
    route = FakeRoute(replies=[scribe_json(boxes={"goal": FULL_BOXES["goal"]}),
                               "and who is it for?"])
    brains = _brains(route)
    run_turn(new_state(SLUG), "I want a tool", brains.interviewer, brains.scribe)

    assert route.roles() == ["scribe", "interviewer"]
    for call in route.calls:
        assert internal_key not in _model_visible_text(call), (
            f"'{internal_key}' reached the {call['role']}"
        )


def test_the_boxes_shown_to_the_scribe_exclude_internal_ones() -> None:
    """The engine hands the Scribe current_boxes — that map was unfiltered."""
    seen: dict[str, dict] = {}

    def capture_scribe(transcript, current_boxes):
        seen.update(current_boxes)
        from intent.state import ScribeUpdate

        return ScribeUpdate()

    run_turn(new_state(SLUG), "hi", lambda *a: "q?", capture_scribe)
    assert set(seen) == set(CONVERSATIONAL_KEYS)


def test_an_incomplete_internal_box_would_not_leak_either() -> None:
    """incomplete_boxes excluded research only BY ACCIDENT — research is
    complete, so it fell out of the list. Forced incomplete, the old code would
    have put it straight into the directives."""
    state = new_state(SLUG)
    state.boxes["research"].status = "empty"  # break the seeding on purpose

    directives = build_directives(state)
    assert "research" not in directives["incomplete_boxes"]
    assert "research" not in directives["pending_confirmations"]


def test_a_proposed_internal_box_is_never_asked_to_be_confirmed() -> None:
    state = new_state(SLUG)
    state.boxes["research"].status = "proposed"
    assert "research" not in build_directives(state)["pending_confirmations"]


# --- the human's view is honest too (the R-030 sweep) ----------------------


def test_the_status_table_counts_only_what_the_founder_can_answer() -> None:
    from foundry_cli.session import status_table

    table = status_table(new_state(SLUG))
    assert f"0 of {len(CONVERSATIONAL_KEYS)} boxes complete" in table
    assert "1 of 8" not in table, "the reserved slot was padding the count"


def test_the_human_is_still_told_the_reserved_slot_exists() -> None:
    """Not hidden — a founder is entitled to see their own project's state.
    The fix is that it is labelled as ours, not counted as theirs."""
    from foundry_cli.session import status_table

    table = status_table(new_state(SLUG))
    assert "reserved internally" in table
    assert "research" in table
    assert "not yours to answer" in table


def test_the_reserved_box_claims_no_author() -> None:
    """It was seeded proposed_by='user', so the table told the founder they had
    confirmed something nobody ever asked them about."""
    assert new_state(SLUG).boxes["research"].proposed_by is None
