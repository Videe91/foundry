from __future__ import annotations

import re

from foundry.domain.gaps import GapKind
from foundry.intelligence.baseline import BaselineGap, BaselineResult
from foundry.intelligence.input import IntelligenceInput

_SUBJECT_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ALLOWED_KIND_VALUES = frozenset(kind.value for kind in GapKind)


class BaselineValidationError(ValueError):
    pass


def validate_baseline_result(
    request: IntelligenceInput,
    result: BaselineResult,
) -> BaselineResult:
    gaps = result.payload.gaps
    known_events = set(request.source_event_ids)
    _reject_duplicate(tuple(gap.gap_id for gap in gaps), "duplicate baseline gap_id: ")
    _reject_duplicate_identities(gaps)
    _reject_invalid_subject_keys(gaps)
    _reject_unknown_source_events(gaps, known_events)
    _reject_invalid_confidence(gaps)
    _reject_disallowed_kinds(gaps)
    return result


def _reject_duplicate(values: tuple[str, ...], prefix: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise BaselineValidationError(prefix + value)
        seen.add(value)


def _reject_duplicate_identities(gaps: tuple[BaselineGap, ...]) -> None:
    seen: set[tuple[str, str]] = set()
    for gap in gaps:
        identity = (_kind_value(gap.kind), gap.subject_key)
        if identity in seen:
            raise BaselineValidationError(
                "duplicate baseline gap identity: " + identity[0] + ":" + identity[1]
            )
        seen.add(identity)


def _reject_invalid_subject_keys(gaps: tuple[BaselineGap, ...]) -> None:
    for gap in gaps:
        if _SUBJECT_KEY.fullmatch(gap.subject_key) is None:
            raise BaselineValidationError("invalid subject_key: " + gap.subject_key)


def _reject_unknown_source_events(gaps: tuple[BaselineGap, ...], known_events: set[str]) -> None:
    for gap in gaps:
        for event_id in gap.source_event_ids:
            if event_id not in known_events:
                raise BaselineValidationError(
                    "unknown source_event_id on baseline gap " + gap.gap_id + ": " + event_id
                )


def _reject_invalid_confidence(gaps: tuple[BaselineGap, ...]) -> None:
    for gap in gaps:
        if not 0.0 <= gap.confidence <= 1.0:
            raise BaselineValidationError(
                "invalid confidence on baseline gap " + gap.gap_id + ": " + str(gap.confidence)
            )


def _reject_disallowed_kinds(gaps: tuple[BaselineGap, ...]) -> None:
    for gap in gaps:
        if _kind_value(gap.kind) not in _ALLOWED_KIND_VALUES:
            raise BaselineValidationError(
                "disallowed gap kind on baseline gap "
                + gap.gap_id
                + ": "
                + _kind_value(gap.kind)
            )


def _kind_value(kind: object) -> str:
    value = getattr(kind, "value", kind)
    return str(value)
