"""Packet: P-012 — The meter learns addresses: receipts land in project ledgers.

One job: test MeterRouter and the project meter — routing, isolation, the
fallback that never raises, and that a line written here is indistinguishable
from one the Switchboard wrote.

All offline. Nothing here imports switchboard; the seam is the point.

Version: 0.1.0
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from workspace import (
    JsonlMeter,
    MeterRouter,
    create_project,
    workspace_resolver,
)

# R-019 fixture: a REAL line captured verbatim from ledger/meter.jsonl, written
# by the Switchboard's MeterLedger during the live matrix run of 2026-08-18.
# Copied byte-for-byte from the tail of that file — the fake models the API, and
# here the "API" is the receipt format the other package already writes.
CAPTURED_RECEIPT = (
    '{"tags":{"project_id":"foundry-smoke","department":"adversarial",'
    '"role":"matrix","packet_id":null,"ticket_id":null,"attempt_number":null},'
    '"model_used":"openrouter/deepseek/deepseek-v4-flash-0731",'
    '"usage":{"prompt_tokens":6495,"completion_tokens":33,"total_tokens":6528,'
    '"cost_usd":null,"cached_tokens":0,"cache_creation_tokens":0},'
    '"recorded_at":"2026-08-18T18:29:50.971682Z"}'
)


class FakeRecord:
    """A record shaped like the Switchboard's, encoding itself the same way.

    R-019: the fake models what the real object does — MeterLedger calls
    `model_dump_json()` and writes the result, so this does too.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.tags = SimpleNamespace(**payload["tags"])

    def model_dump_json(self) -> str:
        return json.dumps(self._payload, separators=(",", ":"))


def _record(project_id: str | None, model: str = "anthropic/x") -> FakeRecord:
    payload = json.loads(CAPTURED_RECEIPT)
    payload["tags"]["project_id"] = project_id
    payload["model_used"] = model
    return FakeRecord(payload)


def _lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- the round trip: our line is their line --------------------------------


def test_a_line_we_write_parses_identically_to_a_captured_real_one(
    tmp_path: Path,
) -> None:
    """The format is pinned on both sides. If these ever diverge, one package
    is writing receipts the other cannot read — and the ledger is the only
    thing the rest of the system trusts."""
    meter = JsonlMeter(tmp_path / "meter.jsonl")
    meter.record(FakeRecord(json.loads(CAPTURED_RECEIPT)))

    written = meter.path.read_text(encoding="utf-8").splitlines()
    assert len(written) == 1
    assert json.loads(written[0]) == json.loads(CAPTURED_RECEIPT)


def test_a_pydantic_style_record_is_byte_identical_not_merely_equivalent(
    tmp_path: Path,
) -> None:
    """Preferring the record's own encoder means a routed receipt is the same
    bytes MeterLedger would have written, not a re-serialisation of it."""
    meter = JsonlMeter(tmp_path / "meter.jsonl")
    meter.record(FakeRecord(json.loads(CAPTURED_RECEIPT)))
    assert meter.path.read_text(encoding="utf-8") == CAPTURED_RECEIPT + "\n"


def test_a_plain_mapping_record_still_writes_valid_jsonl(tmp_path: Path) -> None:
    """A decoded line replayed through the router must round-trip too."""
    meter = JsonlMeter(tmp_path / "meter.jsonl")
    meter.record(json.loads(CAPTURED_RECEIPT))
    assert _lines(meter.path) == [json.loads(CAPTURED_RECEIPT)]


def test_records_append_never_overwrite(tmp_path: Path) -> None:
    meter = JsonlMeter(tmp_path / "meter.jsonl")
    for index in range(3):
        meter.record(_record("p", model=f"m{index}"))
    assert [line["model_used"] for line in _lines(meter.path)] == ["m0", "m1", "m2"]


def test_the_meter_creates_its_parent_directory(tmp_path: Path) -> None:
    meter = JsonlMeter(tmp_path / "deep" / "nested" / "meter.jsonl")
    meter.record(_record("p"))
    assert meter.path.is_file()


# --- routing ----------------------------------------------------------------


def test_a_resolvable_id_lands_in_that_projects_meter(tmp_path: Path) -> None:
    project = create_project("alpha", "Alpha", root=tmp_path)
    router = MeterRouter(workspace_resolver(tmp_path))
    router.record(_record("alpha"))

    lines = _lines(project.meter_path)
    assert len(lines) == 1
    assert lines[0]["tags"]["project_id"] == "alpha"


def test_two_projects_stay_isolated(tmp_path: Path) -> None:
    """Contract 3: neither ledger contains the other's receipt."""
    alpha = create_project("alpha", "Alpha", root=tmp_path)
    beta = create_project("beta", "Beta", root=tmp_path)
    router = MeterRouter(workspace_resolver(tmp_path))

    router.record(_record("alpha", model="model-a"))
    router.record(_record("beta", model="model-b"))

    assert [line["model_used"] for line in _lines(alpha.meter_path)] == ["model-a"]
    assert [line["model_used"] for line in _lines(beta.meter_path)] == ["model-b"]


def test_tags_as_a_mapping_route_the_same_as_tags_as_an_object(
    tmp_path: Path,
) -> None:
    project = create_project("alpha", "Alpha", root=tmp_path)
    router = MeterRouter(workspace_resolver(tmp_path))

    router.record(_record("alpha"))                      # attribute-style tags
    router.record(json.loads(CAPTURED_RECEIPT) | {       # mapping-style tags
        "tags": {"project_id": "alpha", "department": "floor", "role": "builder"}
    })
    assert len(_lines(project.meter_path)) == 2


# --- failure containment: the meter must never kill a call -----------------


def test_an_unknown_id_falls_back_to_the_default(tmp_path: Path) -> None:
    create_project("alpha", "Alpha", root=tmp_path)
    fallback = tmp_path / "global-meter.jsonl"
    router = MeterRouter(workspace_resolver(tmp_path), default_path=fallback)

    router.record(_record("no-such-project"))
    assert len(_lines(fallback)) == 1


def test_an_unknown_id_with_no_default_is_dropped_with_a_warning(
    tmp_path: Path,
) -> None:
    router = MeterRouter(workspace_resolver(tmp_path))
    with pytest.warns(RuntimeWarning, match="no-such-project"):
        router.record(_record("no-such-project"))
    assert not list(tmp_path.rglob("meter.jsonl"))


def test_a_raising_resolver_is_contained_not_propagated(tmp_path: Path) -> None:
    """P-003's law, inherited: a receipt that cannot be filed is a warning."""

    def explode(_project_id: str) -> Path:
        raise RuntimeError("resolver exploded")

    fallback = tmp_path / "global-meter.jsonl"
    MeterRouter(explode, default_path=fallback).record(_record("alpha"))
    assert len(_lines(fallback)) == 1

    with pytest.warns(RuntimeWarning):
        MeterRouter(explode).record(_record("alpha"))


def test_a_record_with_no_project_id_falls_back(tmp_path: Path) -> None:
    fallback = tmp_path / "global-meter.jsonl"
    router = MeterRouter(workspace_resolver(tmp_path), default_path=fallback)
    router.record(_record(None))
    router.record(SimpleNamespace())  # no tags at all
    assert len(_lines(fallback)) == 2


def test_routing_never_double_writes(tmp_path: Path) -> None:
    """Contract 6: exactly one file, ever."""
    project = create_project("alpha", "Alpha", root=tmp_path)
    fallback = tmp_path / "global-meter.jsonl"
    router = MeterRouter(workspace_resolver(tmp_path), default_path=fallback)

    router.record(_record("alpha"))
    assert len(_lines(project.meter_path)) == 1
    assert _lines(fallback) == []


# --- the resolver -----------------------------------------------------------


def test_the_resolver_rejects_a_slug_with_no_ledger(tmp_path: Path) -> None:
    (tmp_path / "not-a-project").mkdir()
    with pytest.raises(KeyError):
        workspace_resolver(tmp_path)("not-a-project")


def test_the_resolver_points_at_the_projects_own_meter(tmp_path: Path) -> None:
    project = create_project("alpha", "Alpha", root=tmp_path)
    assert workspace_resolver(tmp_path)("alpha") == project.meter_path


# --- Project.meter() --------------------------------------------------------


def test_project_meter_writes_to_that_projects_ledger(tmp_path: Path) -> None:
    project = create_project("alpha", "Alpha", root=tmp_path)
    meter = project.meter()

    assert meter.path == project.meter_path
    meter.record(_record("alpha"))
    assert len(_lines(project.meter_path)) == 1


def test_project_meter_exposes_the_two_members_the_switchboard_asks_for() -> None:
    """The seam: `.path` and `.record` are the whole contract, and neither
    package imports the other to satisfy it."""
    assert hasattr(JsonlMeter, "path") or "path" in JsonlMeter.__init__.__code__.co_names
    assert callable(JsonlMeter.record)


def test_a_fresh_project_meter_starts_empty(tmp_path: Path) -> None:
    """create_project stamps meter.jsonl as an empty file: JSONL means one
    receipt per line, so any seed content would be an invalid first line."""
    project = create_project("alpha", "Alpha", root=tmp_path)
    assert project.meter_path.is_file()
    assert project.meter_path.read_text(encoding="utf-8") == ""


def test_no_warning_is_raised_on_the_happy_path(tmp_path: Path) -> None:
    """Discriminating: a router that warned on every record would satisfy the
    drop-with-warning tests while being useless."""
    create_project("alpha", "Alpha", root=tmp_path)
    router = MeterRouter(workspace_resolver(tmp_path))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        router.record(_record("alpha"))
