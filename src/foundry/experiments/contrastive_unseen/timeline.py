"""Frozen Kestrel lifecycle timeline for the 9P2 unseen-lifecycle experiment.

Spec §5, §9, §12. This module owns only model-visible evidence and
deterministic schedule/ceiling data. It may record structural facts about that
evidence (ids, lineage, timestamps, scope, content hashes/byte lengths) and
must never decide or encode semantic meaning, and it must never import
``expectations`` — the hidden answer key, rubric, and leakage needles live
there exclusively, so a request-path module built from this file alone cannot
see them. No file, git history, environment variable, or current time may
influence the evidence: every value below is a literal locked in the approved
spec.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from pydantic import Field

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item

__all__ = [
    "ARM_SCHEDULE",
    "EXPERIMENT_VERSION",
    "FROZEN_CORE_SHA",
    "MAX_COST_USD",
    "MAX_FRONTIER_CALLS",
    "MAX_HUMAN_AUTHORIZATIONS",
    "MAX_JUDGE_CALLS",
    "PROJECT_ID",
    "SCOPE",
    "SCOPE_TUPLE",
    "TIMELINE",
    "EvidenceRecord",
    "LifecycleEvidence",
    "evidence_records",
    "persistent_delta",
    "reconstruction_corpus",
]

EXPERIMENT_VERSION: Final = "intent-v2-contrastive-unseen-lifecycle-v2"
PROJECT_ID: Final = "PROJ-9P2-UNSEEN-KESTREL"
SCOPE: Final = "kestrel-delivery"
SCOPE_TUPLE: Final[tuple[str, ...]] = (SCOPE,)
FROZEN_CORE_SHA: Final = "1f89fc86cda463da676bf45603b86a7dcb458452"

ARM_SCHEDULE: Final[tuple[tuple[int, str], ...]] = (
    (1, "F"),
    (1, "A"),
    (1, "R"),
    (2, "A"),
    (2, "R"),
    (2, "F"),
    (3, "R"),
    (3, "F"),
    (3, "A"),
    (4, "F"),
    (4, "A"),
    (4, "R"),
)

MAX_FRONTIER_CALLS: Final = 24
MAX_JUDGE_CALLS: Final = 0
MAX_HUMAN_AUTHORIZATIONS: Final = 16
MAX_COST_USD: Final = 8.0

_DELIVERY_ATTEMPT_ARTIFACT: Final = "kestrel/delivery-attempt-policy.md"
_RETRY_WAIT_ARTIFACT: Final = "kestrel/retry-wait-policy.md"
_FINAL_FAILURE_ARTIFACT: Final = "kestrel/final-failure-policy.md"


class LifecycleEvidence(FrozenModel):
    t: int = Field(ge=1, le=4)
    item: EvidenceItem


class EvidenceRecord(FrozenModel):
    """Structural facts only — no hidden answer-key semantics (spec §5)."""

    t: int = Field(ge=1, le=4)
    evidence_id: str = Field(min_length=1)
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    artifact_ref: str | None
    supersedes_evidence_id: str | None
    observed_at: str
    scope: tuple[str, ...]
    content_sha256: str
    content_bytes: int = Field(ge=0)


def _iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


_EV_K_A1: Final = evidence_item(
    evidence_id="EV-K-A1",
    project_id=PROJECT_ID,
    source_kind=SourceKind.DOCUMENT,
    source_ref="experiment://kestrel/T1/A1",
    content=(
        "# Delivery attempt allowance\n"
        "\n"
        "For each delivery job, the worker may make no more than three delivery "
        "attempts in total. The first delivery attempt is included in that limit.\n"
    ),
    observed_at=datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC),
    scope=SCOPE_TUPLE,
    artifact_ref=_DELIVERY_ATTEMPT_ARTIFACT,
    supersedes_evidence_id=None,
)

_EV_K_B1: Final = evidence_item(
    evidence_id="EV-K-B1",
    project_id=PROJECT_ID,
    source_kind=SourceKind.DOCUMENT,
    source_ref="experiment://kestrel/T1/B1",
    content=(
        "# Retry wait\n"
        "\n"
        "Before starting any retry attempt, the worker waits five seconds after "
        "the preceding failed attempt.\n"
    ),
    observed_at=datetime(2026, 9, 1, 0, 1, 0, tzinfo=UTC),
    scope=SCOPE_TUPLE,
    artifact_ref=_RETRY_WAIT_ARTIFACT,
    supersedes_evidence_id=None,
)

_EV_K_N1: Final = evidence_item(
    evidence_id="EV-K-N1",
    project_id=PROJECT_ID,
    source_kind=SourceKind.DOCUMENT,
    source_ref="experiment://kestrel/T1/N1",
    content=(
        "# Final failure handling\n"
        "\n"
        "If a delivery job still has not succeeded after its last permitted "
        "attempt, leave the job in failed state and require operator review. Do "
        "not automatically discard the job.\n"
    ),
    observed_at=datetime(2026, 9, 1, 0, 2, 0, tzinfo=UTC),
    scope=SCOPE_TUPLE,
    artifact_ref=_FINAL_FAILURE_ARTIFACT,
    supersedes_evidence_id=None,
)

_EV_K_A2: Final = evidence_item(
    evidence_id="EV-K-A2",
    project_id=PROJECT_ID,
    source_kind=SourceKind.DOCUMENT,
    source_ref="experiment://kestrel/T2/A2",
    content=(
        "# Delivery attempt allowance\n"
        "\n"
        "Each delivery job begins with one original delivery attempt. If that "
        "attempt fails, the worker may make up to three additional retry attempts.\n"
    ),
    observed_at=datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC),
    scope=SCOPE_TUPLE,
    artifact_ref=_DELIVERY_ATTEMPT_ARTIFACT,
    supersedes_evidence_id="EV-K-A1",
)

_EV_K_A3: Final = evidence_item(
    evidence_id="EV-K-A3",
    project_id=PROJECT_ID,
    source_kind=SourceKind.DOCUMENT,
    source_ref="experiment://kestrel/T3/A3",
    content=(
        "# Delivery attempt allowance\n"
        "\n"
        "A job gets one initial delivery attempt. After that initial attempt "
        "fails, no more than three retry attempts may follow.\n"
    ),
    observed_at=datetime(2026, 9, 3, 0, 0, 0, tzinfo=UTC),
    scope=SCOPE_TUPLE,
    artifact_ref=_DELIVERY_ATTEMPT_ARTIFACT,
    supersedes_evidence_id="EV-K-A2",
)

_EV_K_B2: Final = evidence_item(
    evidence_id="EV-K-B2",
    project_id=PROJECT_ID,
    source_kind=SourceKind.DOCUMENT,
    source_ref="experiment://kestrel/T4/B2",
    content=(
        "# Retry wait\n"
        "\n"
        "Retry waits are not fixed. Before the first retry, wait two seconds. "
        "Before each later retry, double the previous wait, but never wait more "
        "than thirty seconds.\n"
    ),
    observed_at=datetime(2026, 9, 4, 0, 0, 0, tzinfo=UTC),
    scope=SCOPE_TUPLE,
    artifact_ref=_RETRY_WAIT_ARTIFACT,
    supersedes_evidence_id="EV-K-B1",
)

TIMELINE: Final[tuple[LifecycleEvidence, ...]] = (
    LifecycleEvidence(t=1, item=_EV_K_A1),
    LifecycleEvidence(t=1, item=_EV_K_B1),
    LifecycleEvidence(t=1, item=_EV_K_N1),
    LifecycleEvidence(t=2, item=_EV_K_A2),
    LifecycleEvidence(t=3, item=_EV_K_A3),
    LifecycleEvidence(t=4, item=_EV_K_B2),
)


def persistent_delta(t: int, *, project_id: str) -> tuple[EvidenceItem, ...]:
    """Arm F/A input at ``t``: the new evidence introduced exactly at that step.

    T1 -> (A1, B1, N1); T2 -> (A2,); T3 -> (A3,); T4 -> (B2,). Only ``project_id``
    is replaced; every other field is byte-identical to the frozen timeline item.
    """
    return tuple(
        le.item.model_copy(update={"project_id": project_id}) for le in TIMELINE if le.t == t
    )


def reconstruction_corpus(t: int, *, project_id: str) -> tuple[EvidenceItem, ...]:
    """Arm R input at ``t``: every version with step ``<= t``, in frozen timeline order."""
    return tuple(
        le.item.model_copy(update={"project_id": project_id}) for le in TIMELINE if le.t <= t
    )


def evidence_records() -> tuple[EvidenceRecord, ...]:
    """Structural evidence facts for the manifest/artifact layer (Controller Ruling 1).

    Records id/kind/ref/lineage/timestamp/scope/hash/byte-length only. It does not
    duplicate hidden answer-key semantics.
    """
    return tuple(
        EvidenceRecord(
            t=le.t,
            evidence_id=le.item.evidence_id,
            source_kind=le.item.source_kind,
            source_ref=le.item.source_ref,
            artifact_ref=le.item.artifact_ref,
            supersedes_evidence_id=le.item.supersedes_evidence_id,
            observed_at=_iso_z(le.item.observed_at),
            scope=le.item.scope,
            content_sha256=le.item.content_sha256,
            content_bytes=len(le.item.content.encode("utf-8")),
        )
        for le in TIMELINE
    )
