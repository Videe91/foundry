"""Packet: P-009.5 + R-028 — the matrix's column vocabulary.

One job: name the matrix columns and cell verdicts, in one leaf module both the
prober and the renderer can import without a cycle.

Version: 0.11.1
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("image", "pdf", "text")
COLUMNS: tuple[str, ...] = (*KINDS, "cache c1", "cache c2", "cost")

OK = "OK"
REFUSED = "REFUSED-by-design"
UNAVAILABLE = "UNAVAILABLE"

# A cost cell for a model litellm cannot price. NEVER 0.000000: zero claims the
# call was free, None means we do not know what it cost. Same class of defect as
# the Gemini cache note that printed "unknown" about a family we understood —
# a label that misstates what we know is worse than a missing one.
UNPRICED_COST = "unpriced"
