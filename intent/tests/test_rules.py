"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: test every completeness rule, each with the pair that makes it
discriminating — a minimal passing content, and the NEAREST failing mutation.

A rule tested only against something obviously good proves nothing: the whole
point of code-owned completeness is that it says no where a model would say yes.

Version: 0.1.0
"""

from __future__ import annotations

from typing import Any

import pytest

from intent import BOX_KEYS, box_complete, completeness, is_complete, new_state
from intent.rules import RULES
from intent.skeleton import CONFIRMED, PROPOSED

# (box key, content that PASSES, the nearest content that FAILS, why)
PAIRS: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
    (
        "goal",
        {"summary": "a tool", "victory_conditions": ["ships", "is used"]},
        {"summary": "a tool", "victory_conditions": ["ships"]},
        "one victory condition restates the goal; the second is falsifiable",
    ),
    (
        "goal",
        {"summary": "a tool", "victory_conditions": ["ships", "is used"]},
        {"summary": "", "victory_conditions": ["ships", "is used"]},
        "an empty summary is not a summary",
    ),
    (
        "users",
        {"users": [{"name": "founder", "needs": "speed"}]},
        {"users": [{"name": "founder", "needs": ""}]},
        "a named user with no stated need is a label, not a user",
    ),
    (
        "users",
        {"users": [{"name": "founder", "needs": "speed"}]},
        {"users": []},
        "nobody is not somebody",
    ),
    (
        "workflows",
        {"workflows": [{"story": "uploads a file", "mode": "automate"}]},
        {"workflows": [{"story": "uploads a file", "mode": "magic"}]},
        "mode must be one we can actually build",
    ),
    (
        "workflows",
        {"workflows": [{"story": "uploads a file", "mode": "human_in_loop"}]},
        {"workflows": [{"story": "", "mode": "human_in_loop"}]},
        "a mode without a story is a setting, not a workflow",
    ),
    (
        "data",
        {"entities": ["invoice"], "sensitive": []},
        {"entities": ["invoice"]},
        "an ABSENT sensitive key means nobody asked; empty means we asked",
    ),
    (
        "data",
        {"entities": ["invoice"], "sensitive": ["email"]},
        {"entities": [], "sensitive": ["email"]},
        "sensitive data about no entities is incoherent",
    ),
    (
        "boundaries",
        {"exclusions": ["no payments"]},
        {"exclusions": [""]},
        "an empty exclusion excludes nothing",
    ),
    (
        "non_negotiables",
        {"security_level": "standard", "scale": "small", "budget": "$100/mo"},
        {"security_level": "standard", "scale": "small"},
        "budget missing entirely",
    ),
    (
        "non_negotiables",
        {"security_level": "standard", "scale": "small", "budget": "$100/mo"},
        {"security_level": "", "scale": "small", "budget": "$100/mo"},
        "a blank answer is not an answer",
    ),
    (
        "website",
        {"needed": False},
        {"needed": "no"},
        "needed must be a real boolean, not the word",
    ),
    (
        "website",
        {"needed": True, "kind": "marketing"},
        {"needed": True},
        "a site that is needed must say what kind",
    ),
]


@pytest.mark.parametrize(
    ("key", "passing", "failing", "why"),
    PAIRS,
    ids=[f"{p[0]}-{i}" for i, p in enumerate(PAIRS)],
)
def test_each_rule_discriminates(
    key: str, passing: dict[str, Any], failing: dict[str, Any], why: str
) -> None:
    assert RULES[key](passing) is True, f"should pass: {why}"
    assert RULES[key](failing) is False, f"should fail: {why}"


def test_every_box_has_a_rule() -> None:
    assert set(RULES) == set(BOX_KEYS)


def test_research_is_always_complete() -> None:
    """The reserved slot — a department fills it, never the founder."""
    assert RULES["research"]({}) is True
    assert RULES["research"]({"anything": "at all"}) is True


def test_research_is_born_confirmed_so_it_needs_no_exception() -> None:
    """Both stated rules hold at once: research is always complete, AND only
    confirmed boxes count. Seeding it settled is what avoids a special case."""
    state = new_state("demo")
    assert state.boxes["research"].status == CONFIRMED
    assert completeness(state)["research"] is True


# --- consent is not content -------------------------------------------------


def test_proposed_content_does_not_count_however_good_it_is() -> None:
    """R-033b: Foundry never self-signs a constitution."""
    state = new_state("demo")
    box = state.boxes["goal"]
    box.content = {"summary": "a tool", "victory_conditions": ["ships", "used"]}

    box.status = PROPOSED
    assert box_complete(state, "goal") is False
    box.status = CONFIRMED
    assert box_complete(state, "goal") is True


def test_confirmed_but_structurally_empty_still_fails() -> None:
    """The other direction: consent to nothing is not completeness."""
    state = new_state("demo")
    state.boxes["goal"].status = CONFIRMED
    assert box_complete(state, "goal") is False


def test_a_fresh_interview_has_exactly_one_complete_box() -> None:
    state = new_state("demo")
    done = completeness(state)
    assert [k for k, v in done.items() if v] == ["research"]
    assert is_complete(state) is False


def test_completeness_reports_in_skeleton_order() -> None:
    assert list(completeness(new_state("demo"))) == list(BOX_KEYS)
