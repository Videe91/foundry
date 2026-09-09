from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from foundry.domain.events import parse_event
from foundry.evaluation.models import EvalExpectation, EvalInput


def load_input(fixture_dir: Path) -> EvalInput:
    raw = _read_json(fixture_dir / "input.json")
    events = tuple(parse_event(event) for event in _raw_events(raw))
    payload = dict(raw)
    payload["events"] = events
    payload["artifact_refs"] = tuple(raw.get("artifact_refs", ()))
    return EvalInput.model_validate(payload)


def load_judge(fixture_dir: Path) -> EvalExpectation:
    raw = _read_json(fixture_dir / "judge.json")
    return EvalExpectation.model_validate(raw)


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _raw_events(raw: dict[str, Any]) -> list[Mapping[str, object]]:
    events = raw.get("events", [])
    if not isinstance(events, list):
        raise ValueError("input events must be a list")
    parsed: list[Mapping[str, object]] = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("each input event must be a JSON object")
        parsed.append(event)
    return parsed
