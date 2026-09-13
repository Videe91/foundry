"""Per-call measurements and window totals for the 9P3 long-horizon experiment (spec §13–§14).

Law of this module: it records structural and economic facts only -- token counts,
provider cost, wall clock, rendered-request length, id counts, hashes -- and never
meaning. It decides nothing about what a request said, what a judgment proposed, or
whether any claim matched the answer key. It is a request-path module and must never
import ``expectations``.

The measurement law is strictly positional: ``records[i]`` is paired with
``receipts[i]`` in call order, and the pairing is never inferred, searched for, or
repaired. A count mismatch raises ``MeasurementMismatch`` BEFORE any row is produced.
Every record must carry the step's ``arm`` and ``t``; an Arm A record that shows a
non-zero ``comparison_context_chars`` is a contract violation (A never renders
comparison context) and is refused, never silently zeroed. Arm R rows carry the
cumulative raw-evidence character count ``timeline.raw_evidence_character_count(t)``;
Arm F/A rows carry ``None`` -- "not applicable", never ``0`` -- which serialises as
JSON ``null``.

The summary covers the scientific window ``protocol.MEASURED_WINDOW`` (T2..T16); T1 is
never totalled. Exactly one measured value is required per ``(arm, T)`` in the window
and exactly two calls per ``(arm, T)`` present; a missing, duplicate or ambiguous shape
is refused rather than filled. Means over ``EARLY_WINDOW`` / ``LATE_WINDOW`` are exact
``Fraction``s serialised as ``str(fraction)`` (``"11"``, ``"23/2"``) so that
``Fraction(value)`` round-trips; no float ever enters a comparison.

Reuse boundary: ``RequestRecord`` and ``RecordingReasoner`` come from the frozen 9P2
package ``foundry.experiments.contrastive_unseen.records`` and are re-exported here so
that request capture and reasoner identity checking are never forked.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from fractions import Fraction
from typing import Any, Final, Literal

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen.records import RecordingReasoner, RequestRecord
from foundry.experiments.long_horizon_bounded.protocol import (
    EARLY_WINDOW,
    LATE_WINDOW,
    MEASURED_WINDOW,
    Arm,
)
from foundry.experiments.long_horizon_bounded.timeline import raw_evidence_character_count

__all__ = [
    "ARMS",
    "CallMeasurement",
    "MeasurementMismatch",
    "RecordingReasoner",
    "RequestRecord",
    "TokenSummary",
    "measure_step",
    "summarize",
    "window_mean",
]

ARMS: Final[tuple[Arm, ...]] = ("F", "A", "R")
_CALL_NUMBERS: Final[frozenset[int]] = frozenset({1, 2})


class MeasurementMismatch(RuntimeError):
    """Records and receipts cannot be paired, or a summary shape is not exactly complete."""


class CallMeasurement(FrozenModel):
    """Spec §13 per-call row: structural facts from the record, economics from the receipt."""

    arm: Arm
    t: int = Field(ge=1)
    call_number: Literal[1, 2]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    provider_cost_usd: str = Field(min_length=1)
    wall_clock_ms: int = Field(ge=0)
    rendered_request_chars: int = Field(ge=0)
    known_address_count: int = Field(ge=0)
    known_claim_count: int = Field(ge=0)
    comparison_context_chars: int = Field(ge=0)
    r_cumulative_raw_evidence_chars: int | None
    request_sha256: str = Field(min_length=64, max_length=64)
    invocation_id: str = Field(min_length=1)


class TokenSummary(FrozenModel):
    """Spec §14 window totals (T2..T16) and exact early/late means as ``Fraction`` strings."""

    f_total: int = Field(ge=0)
    a_total: int = Field(ge=0)
    r_total: int = Field(ge=0)
    f_early_mean: str = Field(min_length=1)
    f_late_mean: str = Field(min_length=1)
    a_early_mean: str = Field(min_length=1)
    a_late_mean: str = Field(min_length=1)
    r_early_mean: str = Field(min_length=1)
    r_late_mean: str = Field(min_length=1)
    per_arm_per_t: dict[str, dict[int, int]]


def measure_step(
    *,
    arm: Arm,
    t: int,
    records: tuple[RequestRecord, ...],
    receipts: tuple[Any, ...],
) -> tuple[CallMeasurement, ...]:
    """Pair ``records[i]`` with ``receipts[i]`` and copy their facts into rows.

    Fails closed on any count, arm, or step disagreement before a row is produced.
    """
    if len(records) != len(receipts):
        raise MeasurementMismatch(
            f"RECORD_RECEIPT_COUNT: arm {arm} T{t} has {len(records)} records but "
            f"{len(receipts)} receipts; pairing is positional and never inferred"
        )
    for index, record in enumerate(records):
        if record.arm != arm or record.t != t:
            raise MeasurementMismatch(
                f"RECORD_STEP: records[{index}] is arm {record.arm} T{record.t}, "
                f"not the measured step arm {arm} T{t}"
            )
        if arm == "A" and record.comparison_context_chars != 0:
            raise MeasurementMismatch(
                f"ARM_A_COMPARISON_CONTEXT: records[{index}] carries "
                f"{record.comparison_context_chars} comparison-context chars; Arm A "
                "never renders comparison context"
            )
    r_chars = raw_evidence_character_count(t) if arm == "R" else None
    return tuple(
        _row(record, receipt, r_chars=r_chars)
        for record, receipt in zip(records, receipts, strict=True)
    )


def _row(record: RequestRecord, receipt: Any, *, r_chars: int | None) -> CallMeasurement:
    return CallMeasurement(
        arm=record.arm,
        t=record.t,
        call_number=record.call_number,
        input_tokens=receipt.input_tokens,
        output_tokens=receipt.output_tokens,
        provider_cost_usd=str(Decimal(str(receipt.cost_usd))),
        wall_clock_ms=receipt.wall_clock_ms,
        rendered_request_chars=len(record.rendered_user_request),
        known_address_count=len(record.known_address_ids),
        known_claim_count=len(record.known_claim_ids),
        comparison_context_chars=record.comparison_context_chars,
        r_cumulative_raw_evidence_chars=r_chars,
        request_sha256=record.request_sha256,
        invocation_id=receipt.invocation_id,
    )


def window_mean(values: Iterable[int]) -> Fraction:
    """Exact arithmetic mean ``Fraction(sum, count)``; an empty window is a ``ValueError``."""
    collected = tuple(values)
    if not collected:
        raise ValueError("window_mean of an empty window is undefined")
    return Fraction(sum(collected), len(collected))


def summarize(measurements: tuple[CallMeasurement, ...]) -> TokenSummary:
    """Total input tokens per arm over ``MEASURED_WINDOW`` and take exact window means.

    Requires exactly two calls (1 and 2) for every ``(arm, T)`` present and exactly one
    such pair for every ``(arm, T)`` in the measured window; refuses anything else.
    """
    _require_exact_shape(measurements)
    per_arm_per_t: dict[str, dict[int, int]] = {arm: {} for arm in ARMS}
    for row in measurements:
        if row.t in MEASURED_WINDOW:
            bucket = per_arm_per_t[row.arm]
            bucket[row.t] = bucket.get(row.t, 0) + row.input_tokens
    per_arm_per_t = {arm: dict(sorted(per_t.items())) for arm, per_t in per_arm_per_t.items()}

    def mean(arm: Arm, window: tuple[int, ...]) -> str:
        return str(window_mean(per_arm_per_t[arm][t] for t in window))

    return TokenSummary(
        f_total=sum(per_arm_per_t["F"].values()),
        a_total=sum(per_arm_per_t["A"].values()),
        r_total=sum(per_arm_per_t["R"].values()),
        f_early_mean=mean("F", EARLY_WINDOW),
        f_late_mean=mean("F", LATE_WINDOW),
        a_early_mean=mean("A", EARLY_WINDOW),
        a_late_mean=mean("A", LATE_WINDOW),
        r_early_mean=mean("R", EARLY_WINDOW),
        r_late_mean=mean("R", LATE_WINDOW),
        per_arm_per_t=per_arm_per_t,
    )


def _require_exact_shape(measurements: tuple[CallMeasurement, ...]) -> None:
    """Refuse duplicates, any ``(arm, T)`` without exactly calls {1, 2}, and any
    ``(arm, T)`` of the measured window that is absent."""
    keys = Counter((row.arm, row.t, row.call_number) for row in measurements)
    duplicates = sorted(key for key, n in keys.items() if n > 1)
    if duplicates:
        raise MeasurementMismatch(f"DUPLICATE_CALL: {duplicates}")
    calls_by_step: dict[tuple[str, int], set[int]] = {}
    for arm, t, call_number in keys:
        calls_by_step.setdefault((arm, t), set()).add(call_number)
    malformed = sorted(step for step, calls in calls_by_step.items() if calls != _CALL_NUMBERS)
    if malformed:
        raise MeasurementMismatch(
            f"CALL_SHAPE: {malformed} do not carry exactly calls 1 and 2; nothing is filled"
        )
    missing = sorted(
        (arm, t) for arm in ARMS for t in MEASURED_WINDOW if (arm, t) not in calls_by_step
    )
    if missing:
        raise MeasurementMismatch(
            f"MISSING_STEP: no measurement for {missing} in the measured window; "
            "nothing is filled with 0"
        )
