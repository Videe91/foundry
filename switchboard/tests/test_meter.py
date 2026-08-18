"""Packet: P-003 — Switchboard Meter.

One job: test Usage validation, MeterRecord, and MeterLedger's append-only
JSONL writing.

Version: 0.3.0
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from switchboard.meter import MeterLedger, MeterRecord, Usage
from switchboard.tags import CallTags

TAGS = CallTags(
    project_id="foundry",
    department="floor",
    role="builder",
    packet_id="P-003",
)


def _record(model_used: str = "primary/model-a") -> MeterRecord:
    return MeterRecord(
        tags=TAGS,
        model_used=model_used,
        usage=Usage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0042,
        ),
        recorded_at=datetime.now(timezone.utc),
    )


def test_record_appends_exactly_one_json_line(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")

    ledger.record(_record())

    lines = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["model_used"] == "primary/model-a"


def test_second_record_appends_a_second_line(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")

    ledger.record(_record("primary/model-a"))
    ledger.record(_record("backup/model-b"))

    lines = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert [entry["model_used"] for entry in parsed] == [
        "primary/model-a",
        "backup/model-b",
    ]


def test_parent_directory_is_created_when_absent(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "deep/nested/meter.jsonl")

    ledger.record(_record())

    assert ledger.path.exists()
    assert len(ledger.path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_written_json_round_trips_into_a_meter_record(tmp_path: Path) -> None:
    ledger = MeterLedger(tmp_path / "meter.jsonl")
    original = _record()

    ledger.record(original)

    line = ledger.path.read_text(encoding="utf-8").strip()
    restored = MeterRecord.model_validate_json(line)

    assert restored.tags == original.tags
    assert restored.model_used == original.model_used
    assert restored.usage == original.usage


def test_usage_rejects_negative_prompt_tokens() -> None:
    with pytest.raises(ValidationError):
        Usage(prompt_tokens=-1, completion_tokens=0, total_tokens=0)


def test_usage_rejects_negative_completion_and_total_tokens() -> None:
    with pytest.raises(ValidationError):
        Usage(prompt_tokens=0, completion_tokens=-5, total_tokens=0)

    with pytest.raises(ValidationError):
        Usage(prompt_tokens=0, completion_tokens=0, total_tokens=-5)


def test_cost_usd_is_optional() -> None:
    usage = Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2)

    assert usage.cost_usd is None
