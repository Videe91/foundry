"""Packet: P-004 — Family One: Anthropic Adapter.

One job: model a call's token usage and cost, and append meter records to an
append-only JSONL ledger file.

Known scope boundary: failed calls (every fallback exhausted) are NOT metered
in this packet. Metering the partial cost of failed attempts is a future
packet.

Version: 0.4.0
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from switchboard.tags import CallTags


class Usage(BaseModel):
    """Token counts for one call, plus its best-effort cost."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float | None = None
    cached_tokens: int = Field(default=0, ge=0)
    cache_creation_tokens: int = Field(default=0, ge=0)


class MeterRecord(BaseModel):
    """One metered call: what it cost, and which tagged work incurred it."""

    tags: CallTags
    model_used: str
    usage: Usage
    recorded_at: datetime


class MeterLedger:
    """Appends meter records to a JSONL file, one JSON object per line.

    The file is opened per record and no state is held between calls, so
    concurrent appenders stay safe at this stage.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, record: MeterRecord) -> None:
        """Append exactly one JSON line for this record."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
