"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: the package's public surface.

This is the composition edge and the ONLY module family allowed to import all
three Foundry packages at once — the engine, the Workspace and the Switchboard.
The seam law inverts here by design: composition is the whole job, so there is
no leaf guard on this package. The three packages below it keep theirs.

Version: 0.1.0
"""

from __future__ import annotations

from foundry_cli.brains import Brains, ScribeParseError, attachment_for
from foundry_cli.research_cmd import start as run_research_command
from foundry_cli.session import Session, receipt_line, start, status_table

__all__ = [
    "Brains",
    "ScribeParseError",
    "Session",
    "attachment_for",
    "receipt_line",
    "run_research_command",
    "start",
    "status_table",
]
