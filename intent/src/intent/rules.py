"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: decide whether each box is genuinely filled. Pure code, one rule per
box, no model opinion anywhere.

Completeness is the one judgement an interview cannot delegate. A model asked
"is this good enough?" will say yes to be agreeable, and a constitution signed
on an agreeable answer is worth nothing. Charm is the model's job; truth is the
code's.

Version: 0.1.0
"""

from __future__ import annotations

from typing import Any

from intent.skeleton import BOX_KEYS, CONFIRMED
from intent.state import InterviewState

WORKFLOW_MODES: tuple[str, ...] = ("automate", "human_in_loop")


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _entries(content: dict[str, Any], key: str) -> list[Any]:
    value = content.get(key)
    return value if isinstance(value, list) else []


def goal_rule(content: dict[str, Any]) -> bool:
    """A summary, and at least two ways to know it worked.

    Two, not one: a single victory condition is a restatement of the goal, and
    the second is where a founder has to say something falsifiable.
    """
    conditions = _entries(content, "victory_conditions")
    return (
        _nonempty_str(content.get("summary"))
        and len(conditions) >= 2
        and all(_nonempty_str(c) for c in conditions)
    )


def users_rule(content: dict[str, Any]) -> bool:
    users = _entries(content, "users")
    return bool(users) and all(
        isinstance(u, dict)
        and _nonempty_str(u.get("name"))
        and _nonempty_str(u.get("needs"))
        for u in users
    )


def workflows_rule(content: dict[str, Any]) -> bool:
    flows = _entries(content, "workflows")
    return bool(flows) and all(
        isinstance(f, dict)
        and _nonempty_str(f.get("story"))
        and f.get("mode") in WORKFLOW_MODES
        for f in flows
    )


def data_rule(content: dict[str, Any]) -> bool:
    """Entities, and the sensitive question having been ASKED.

    `sensitive` may be an empty list — "we asked and there is none" is a real
    answer. What is not acceptable is the key being absent, which means nobody
    raised it.
    """
    entities = _entries(content, "entities")
    return (
        bool(entities)
        and all(_nonempty_str(e) or isinstance(e, dict) for e in entities)
        and "sensitive" in content
        and isinstance(content.get("sensitive"), list)
    )


def boundaries_rule(content: dict[str, Any]) -> bool:
    exclusions = _entries(content, "exclusions")
    return bool(exclusions) and all(_nonempty_str(x) for x in exclusions)


def research_rule(_content: dict[str, Any]) -> bool:
    """Always complete — the reserved slot, filled by a department, not a
    founder. It is seeded confirmed at birth so this needs no exception."""
    return True


def non_negotiables_rule(content: dict[str, Any]) -> bool:
    return all(
        _nonempty_str(content.get(key))
        for key in ("security_level", "scale", "budget")
    )


def website_rule(content: dict[str, Any]) -> bool:
    needed = content.get("needed")
    if not isinstance(needed, bool):
        return False
    return _nonempty_str(content.get("kind")) if needed else True


RULES = {
    "goal": goal_rule,
    "users": users_rule,
    "workflows": workflows_rule,
    "data": data_rule,
    "boundaries": boundaries_rule,
    "research": research_rule,
    "non_negotiables": non_negotiables_rule,
    "website": website_rule,
}


def box_complete(state: InterviewState, key: str) -> bool:
    """A box counts ONLY when confirmed AND structurally filled (R-033b)."""
    box = state.boxes.get(key)
    if box is None or box.status != CONFIRMED:
        return False
    return RULES[key](box.content)


def completeness(state: InterviewState) -> dict[str, bool]:
    """Per-box completeness, in skeleton order."""
    return {key: box_complete(state, key) for key in BOX_KEYS}


def is_complete(state: InterviewState) -> bool:
    """Every box filled AND no known conflict left standing.

    A signed constitution may not contain a contradiction someone already
    noticed (R-033a) — so an unresolved one blocks completion outright, however
    full the boxes look.
    """
    if state.unresolved_contradictions:
        return False
    return all(completeness(state).values())
