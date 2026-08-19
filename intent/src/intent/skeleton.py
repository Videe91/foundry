"""Packet: P-013 — Intent, Part One: The Engine (Offline).

One job: hold the eight boxes of an Intent File as DATA — key, title, the
layman hint an interviewer may lean on, and which completeness rule owns it.

Design doc v2.2 Section 4 is the authority for the boxes. Everything else in
the package reads this table, in the same spirit as the Workspace's layout: one
place to be right about what an intent IS.

Version: 0.1.0
"""

from __future__ import annotations

from typing import NamedTuple


class Box(NamedTuple):
    """One of the eight boxes an intent must fill."""

    key: str
    title: str
    hint: str
    rule: str


SKELETON: tuple[Box, ...] = (
    Box("goal", "The goal",
        "what are we building, and how will we know it worked?", "goal"),
    Box("users", "Who it is for",
        "which kinds of people use this, and what does each need?", "users"),
    Box("workflows", "What it does",
        "walk me through what someone actually does with it", "workflows"),
    Box("data", "What it knows",
        "what does it store, and is any of it sensitive?", "data"),
    Box("boundaries", "What it is NOT",
        "what should this deliberately not do?", "boundaries"),
    Box("research", "Research",
        "reserved — filled by the research department, not the founder",
        "research"),
    Box("non_negotiables", "Non-negotiables",
        "security level, scale, and budget", "non_negotiables"),
    Box("website", "Website",
        "does this need a public site, and what kind?", "website"),
)

BOX_KEYS: tuple[str, ...] = tuple(box.key for box in SKELETON)
BOXES: dict[str, Box] = {box.key: box for box in SKELETON}

# Box statuses. `proposed` content, however good, is not consent (R-033b).
EMPTY = "empty"
PROPOSED = "proposed"
CONFIRMED = "confirmed"
STATUSES: tuple[str, ...] = (EMPTY, PROPOSED, CONFIRMED)

# Who put the content there.
BY_USER = "user"
BY_INTERVIEWER = "interviewer"

# The research box is the reserved slot (design doc box 6): nobody interviews
# the founder about it, so it is born already settled. Seeding it confirmed is
# what lets "research is always complete" and "only confirmed boxes count" both
# be true without an exception carved into the completeness code.
RESEARCH_KEY = "research"
RESEARCH_CONTENT: dict[str, str] = {"status": "reserved"}
