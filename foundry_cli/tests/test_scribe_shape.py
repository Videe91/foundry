"""Packet: T-012 — the Scribe's box-content shape.

One job: prove the Scribe cannot store a box shape the completeness rules
cannot read, and that the prompt teaches the shapes the rules actually require.

**R-019, learned the hard way.** Every offline scribe fake returned the correct
shape, so 701 green tests never touched the failure a real model produced on its
first turn. The fixtures here are the OBSERVED shape, copied from
`projects/uk-lead-verify/intent/interview-state.json` (2026-08-19), before they
are the corrected one.

Version: 0.1.0
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import SLUG, FakeRoute, fake_registry

from foundry_cli.brains import Brains, ScribeParseError
from foundry_cli.shapes import normalise_boxes, unwrap_box_content
from foundry_cli.prompts import scribe_system
from intent.rules import RULES
from intent.state import ScribeUpdate
from workspace import create_project

# Verbatim from the live state file — the shape a real Scribe produced when the
# prompt said only "{content object}" and the context showed it BoxState dumps.
OBSERVED_WRAPPED = {
    "content": (
        "Build a genuine lead verification solution for the UK market "
        "(similar to TrustedForm/Journaya available in the US)."
    ),
    "status": "proposed",
    "proposed_by": "user",
}

# What the rules actually require.
CORRECT_GOAL = {
    "summary": "UK lead verification, then lead management",
    "victory_conditions": ["buyers accept certificates", "a generator ships one"],
}


def _brains(route: FakeRoute, **kwargs: Any) -> Brains:
    return Brains(slug=SLUG, registry=fake_registry(), route=route, **kwargs)


def _reply(boxes: dict[str, Any]) -> str:
    return json.dumps({"boxes": boxes})


# --- the observed failure, rejected ----------------------------------------


def test_the_observed_live_shape_is_rejected_not_stored() -> None:
    """A box stored in this shape can never satisfy its rule, so the interview
    could never complete — and nothing would say why."""
    content, problem = unwrap_box_content("goal", OBSERVED_WRAPPED)
    assert content is None
    assert "goal" in problem and "BoxState shape" in problem


def test_the_observed_shape_fails_its_completeness_rule() -> None:
    """Why rejection is right: this content is unreadable to the rules, so
    accepting it would produce a box that looks answered and never counts."""
    assert RULES["goal"](OBSERVED_WRAPPED) is False


def test_a_wrapped_reply_triggers_exactly_one_corrective_retry() -> None:
    route = FakeRoute(replies=[_reply({"goal": OBSERVED_WRAPPED}),
                               _reply({"goal": CORRECT_GOAL})])
    update = _brains(route).scribe([], {})

    assert update.boxes["goal"] == CORRECT_GOAL
    assert len(route.calls) == 2


def test_the_correction_names_the_actual_problem() -> None:
    """A generic "that was not JSON" cannot fix a reply that WAS valid JSON in
    the wrong shape. The retry must say what was wrong."""
    route = FakeRoute(replies=[_reply({"goal": OBSERVED_WRAPPED}),
                               _reply({"goal": CORRECT_GOAL})])
    _brains(route).scribe([], {})

    correction = route.calls[1]["messages"][-1]
    assert "goal" in correction
    assert "BoxState shape" in correction


def test_two_wrapped_replies_fail_loudly_and_preserve_the_reply(
    tmp_path: Path,
) -> None:
    project = create_project(SLUG, "Demo", root=tmp_path)
    route = FakeRoute(replies=[_reply({"goal": OBSERVED_WRAPPED})] * 2)
    with pytest.raises(ScribeParseError) as excinfo:
        _brains(route, project=project).scribe([], {})

    assert "BoxState shape" in str(excinfo.value)
    assert "status" in Path(project.build_log_path).read_text(encoding="utf-8")


# --- what is recoverable, and what is not ----------------------------------


def test_a_wrapper_around_a_real_object_is_unwrapped_not_rejected() -> None:
    """The extraction is there; only the envelope is wrong. Rejecting it would
    throw away work the model actually did."""
    content, problem = unwrap_box_content(
        "goal", {"content": CORRECT_GOAL, "status": "proposed"})
    assert content == CORRECT_GOAL
    assert problem == ""


def test_the_correct_shape_passes_through_untouched() -> None:
    """Discriminating: an unwrapper that mangled correct input would be worse
    than the bug it fixes."""
    content, problem = unwrap_box_content("goal", CORRECT_GOAL)
    assert content == CORRECT_GOAL
    assert problem == ""


def test_a_non_object_content_is_rejected_by_name() -> None:
    content, problem = unwrap_box_content("goal", "just a sentence")
    assert content is None
    assert "goal" in problem and "must be an object" in problem


def test_normalise_reports_the_first_unreadable_box() -> None:
    update = ScribeUpdate(boxes={"goal": CORRECT_GOAL, "users": OBSERVED_WRAPPED})
    problem = normalise_boxes(update)
    assert "users" in problem
    assert update.boxes["goal"] == CORRECT_GOAL


def test_normalise_returns_empty_when_everything_is_readable() -> None:
    update = ScribeUpdate(boxes={"goal": CORRECT_GOAL})
    assert normalise_boxes(update) == ""


# --- the prompt teaches what the rules require -----------------------------

# One example per box, taken from the prompt's own schema list. The test below
# runs them through the REAL rules, so prompt and rules cannot drift apart
# without something going red.
PROMPT_EXAMPLES: dict[str, dict[str, Any]] = {
    "goal": {"summary": "a thing", "victory_conditions": ["one", "two"]},
    "users": {"users": [{"name": "a person", "needs": "a need"}]},
    "workflows": {"workflows": [{"story": "they do a thing", "mode": "automate"}]},
    "data": {"entities": ["a record"], "sensitive": []},
    "boundaries": {"exclusions": ["not this"]},
    "non_negotiables": {"security_level": "standard", "scale": "small",
                        "budget": "$100/mo"},
    "website": {"needed": False},
}


@pytest.mark.parametrize("key", sorted(PROMPT_EXAMPLES))
def test_every_schema_the_prompt_teaches_satisfies_its_rule(key: str) -> None:
    """The link that keeps prompt and rules honest.

    The prompt used to say "{content object}" and teach nothing, so the model
    copied the shape it was shown. Now it states a schema per box — and if a
    rule ever changes, this test fails until the prompt is updated too.
    """
    assert RULES[key](PROMPT_EXAMPLES[key]) is True


def test_the_prompt_names_every_box_it_must_teach() -> None:
    system = scribe_system()
    for key in PROMPT_EXAMPLES:
        assert key in system


def test_the_prompt_warns_against_the_shape_it_shows_the_model() -> None:
    """The trap was self-inflicted: `current_boxes` is a BoxState dump, so the
    context demonstrated the wrong shape while the prompt taught nothing."""
    system = scribe_system()
    assert "Do NOT wrap content" in system
    assert "Current boxes" in system


def test_the_prompt_prefers_an_absent_box_to_a_partial_one() -> None:
    assert "leave the box out" in scribe_system()
