"""Packet: P-009.5 + R-028 — the matrix's column vocabulary.

One job: name the matrix columns and cell verdicts, in one leaf module both the
prober and the renderer can import without a cycle.

Version: 0.10.1
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("image", "pdf", "text")
COLUMNS: tuple[str, ...] = (*KINDS, "cache c1", "cache c2", "cost")

OK = "OK"
REFUSED = "REFUSED-by-design"
UNAVAILABLE = "UNAVAILABLE"
