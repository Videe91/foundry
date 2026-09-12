"""Deterministic bounded old-to-new evidence diff (9P2 Task T2; spec §10).

The unified diff is a *transport* representation of an evidence transition, not a
semantic judgment. It is the standard-library ``difflib.unified_diff`` over
``content.splitlines()`` with exactly ``DIFF_CONTEXT_LINES`` unchanged context lines
per hunk and evidence-id labels. Output is deterministic for identical old/new content.

Support bound: a rendered transition diff longer than ``MAX_TRANSITION_DIFF_CHARS``
Unicode characters raises ``ContextUnsupported`` (``UNSUPPORTED_TRANSITION_DIFF``).
That is a hard stop before any provider call. This module never normalizes text,
filters or ranks hunks, truncates, summarizes, classifies, or calls a model.
"""

from __future__ import annotations

import difflib
from typing import Final

from foundry.application.context_errors import ContextUnsupported
from foundry.domain.evidence import EvidenceItem

DIFF_CONTEXT_LINES: Final[int] = 3
MAX_TRANSITION_DIFF_CHARS: Final[int] = 65_536


def render_unified_diff(predecessor: EvidenceItem, current: EvidenceItem) -> str:
    lines = difflib.unified_diff(
        predecessor.content.splitlines(),
        current.content.splitlines(),
        fromfile=f"evidence:{predecessor.evidence_id}",
        tofile=f"evidence:{current.evidence_id}",
        n=DIFF_CONTEXT_LINES,
        lineterm="",
    )
    rendered = "\n".join(lines)
    if len(rendered) > MAX_TRANSITION_DIFF_CHARS:
        raise ContextUnsupported(
            "UNSUPPORTED_TRANSITION_DIFF: rendered diff "
            f"has {len(rendered)} characters; maximum is {MAX_TRANSITION_DIFF_CHARS}"
        )
    return rendered
