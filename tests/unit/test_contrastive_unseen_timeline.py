"""9P2 T1: frozen Kestrel timeline (spec §5; plan/brief Task T1).

Locks the six model-visible Kestrel evidence items, their lineage, the
persistent/reconstruction projections, the 12-entry arm schedule, and the
locked ceilings. Nothing here decides semantic meaning; ``timeline.py`` must
not import ``expectations`` (checked by parsing its source with ``ast``).
"""

from __future__ import annotations

import ast
import hashlib
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foundry.domain.common import SourceKind
from foundry.experiments.contrastive_unseen import timeline as timeline_module
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    FROZEN_CORE_SHA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    PROJECT_ID,
    SCOPE,
    SCOPE_TUPLE,
    TIMELINE,
    evidence_records,
    persistent_delta,
    reconstruction_corpus,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


_DELIVERY_ATTEMPT_ARTIFACT = "kestrel/delivery-attempt-policy.md"
_RETRY_WAIT_ARTIFACT = "kestrel/retry-wait-policy.md"
_FINAL_FAILURE_ARTIFACT = "kestrel/final-failure-policy.md"

_A1_CONTENT = (
    "# Delivery attempt allowance\n"
    "\n"
    "For each delivery job, the worker may make no more than three delivery "
    "attempts in total. The first delivery attempt is included in that limit.\n"
)
_B1_CONTENT = (
    "# Retry wait\n"
    "\n"
    "Before starting any retry attempt, the worker waits five seconds after "
    "the preceding failed attempt.\n"
)
_N1_CONTENT = (
    "# Final failure handling\n"
    "\n"
    "If a delivery job still has not succeeded after its last permitted "
    "attempt, leave the job in failed state and require operator review. Do "
    "not automatically discard the job.\n"
)
_A2_CONTENT = (
    "# Delivery attempt allowance\n"
    "\n"
    "Each delivery job begins with one original delivery attempt. If that "
    "attempt fails, the worker may make up to three additional retry attempts.\n"
)
_A3_CONTENT = (
    "# Delivery attempt allowance\n"
    "\n"
    "A job gets one initial delivery attempt. After that initial attempt "
    "fails, no more than three retry attempts may follow.\n"
)
_B2_CONTENT = (
    "# Retry wait\n"
    "\n"
    "Retry waits are not fixed. Before the first retry, wait two seconds. "
    "Before each later retry, double the previous wait, but never wait more "
    "than thirty seconds.\n"
)

# (t, evidence_id, source_ref, artifact_ref, supersedes_evidence_id, observed_at, content)
_EXPECTED = (
    (
        1,
        "EV-K-A1",
        "experiment://kestrel/T1/A1",
        _DELIVERY_ATTEMPT_ARTIFACT,
        None,
        datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC),
        _A1_CONTENT,
    ),
    (
        1,
        "EV-K-B1",
        "experiment://kestrel/T1/B1",
        _RETRY_WAIT_ARTIFACT,
        None,
        datetime(2026, 9, 1, 0, 1, 0, tzinfo=UTC),
        _B1_CONTENT,
    ),
    (
        1,
        "EV-K-N1",
        "experiment://kestrel/T1/N1",
        _FINAL_FAILURE_ARTIFACT,
        None,
        datetime(2026, 9, 1, 0, 2, 0, tzinfo=UTC),
        _N1_CONTENT,
    ),
    (
        2,
        "EV-K-A2",
        "experiment://kestrel/T2/A2",
        _DELIVERY_ATTEMPT_ARTIFACT,
        "EV-K-A1",
        datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC),
        _A2_CONTENT,
    ),
    (
        3,
        "EV-K-A3",
        "experiment://kestrel/T3/A3",
        _DELIVERY_ATTEMPT_ARTIFACT,
        "EV-K-A2",
        datetime(2026, 9, 3, 0, 0, 0, tzinfo=UTC),
        _A3_CONTENT,
    ),
    (
        4,
        "EV-K-B2",
        "experiment://kestrel/T4/B2",
        _RETRY_WAIT_ARTIFACT,
        "EV-K-B1",
        datetime(2026, 9, 4, 0, 0, 0, tzinfo=UTC),
        _B2_CONTENT,
    ),
)


def test_constants_are_locked() -> None:
    assert timeline_module.EXPERIMENT_VERSION == "intent-v2-contrastive-unseen-lifecycle-v1"
    assert PROJECT_ID == "PROJ-9P2-UNSEEN-KESTREL"
    assert SCOPE == "kestrel-delivery"
    assert SCOPE_TUPLE == ("kestrel-delivery",)
    assert FROZEN_CORE_SHA == "1f89fc86cda463da676bf45603b86a7dcb458452"
    assert MAX_FRONTIER_CALLS == 24
    assert MAX_JUDGE_CALLS == 0
    assert MAX_HUMAN_AUTHORIZATIONS == 16
    assert MAX_COST_USD == 8.0
    assert isinstance(MAX_COST_USD, float)


def test_timeline_has_exactly_six_items_in_frozen_order() -> None:
    assert len(TIMELINE) == 6
    assert tuple(le.item.evidence_id for le in TIMELINE) == tuple(e[1] for e in _EXPECTED)


def test_timeline_ids_order_metadata_content_lineage_exact() -> None:
    for lifecycle_evidence, expected in zip(TIMELINE, _EXPECTED, strict=True):
        (
            t,
            evidence_id,
            source_ref,
            artifact_ref,
            supersedes_evidence_id,
            observed_at,
            content,
        ) = expected
        item = lifecycle_evidence.item
        assert lifecycle_evidence.t == t
        assert item.evidence_id == evidence_id
        assert item.project_id == PROJECT_ID
        assert item.source_kind is SourceKind.DOCUMENT
        assert item.source_ref == source_ref
        assert item.artifact_ref == artifact_ref
        assert item.supersedes_evidence_id == supersedes_evidence_id
        assert item.observed_at == observed_at
        assert item.scope == SCOPE_TUPLE
        assert item.content == content


def test_content_hashes_recompute_from_literal_content() -> None:
    for lifecycle_evidence, expected in zip(TIMELINE, _EXPECTED, strict=True):
        content = expected[-1]
        expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert lifecycle_evidence.item.content_sha256 == expected_sha


def test_persistent_delta_t1_is_a1_b1_n1() -> None:
    delta = persistent_delta(1, project_id="PROJ-OTHER")
    assert tuple(item.evidence_id for item in delta) == ("EV-K-A1", "EV-K-B1", "EV-K-N1")
    assert all(item.project_id == "PROJ-OTHER" for item in delta)


def test_persistent_delta_t2_is_a2_only() -> None:
    delta = persistent_delta(2, project_id="PROJ-OTHER")
    assert tuple(item.evidence_id for item in delta) == ("EV-K-A2",)


def test_persistent_delta_t3_is_a3_only() -> None:
    delta = persistent_delta(3, project_id="PROJ-OTHER")
    assert tuple(item.evidence_id for item in delta) == ("EV-K-A3",)


def test_persistent_delta_t4_is_b2_only() -> None:
    delta = persistent_delta(4, project_id="PROJ-OTHER")
    assert tuple(item.evidence_id for item in delta) == ("EV-K-B2",)


def test_persistent_delta_replaces_only_project_id() -> None:
    frozen = next(le.item for le in TIMELINE if le.item.evidence_id == "EV-K-A1")
    (projected,) = persistent_delta(1, project_id="PROJ-OTHER")[:1]
    assert projected.project_id == "PROJ-OTHER"
    assert projected.model_copy(update={"project_id": frozen.project_id}) == frozen


def test_reconstruction_corpus_is_cumulative_in_timeline_order() -> None:
    assert tuple(i.evidence_id for i in reconstruction_corpus(1, project_id="P")) == (
        "EV-K-A1",
        "EV-K-B1",
        "EV-K-N1",
    )
    assert tuple(i.evidence_id for i in reconstruction_corpus(2, project_id="P")) == (
        "EV-K-A1",
        "EV-K-B1",
        "EV-K-N1",
        "EV-K-A2",
    )
    assert tuple(i.evidence_id for i in reconstruction_corpus(3, project_id="P")) == (
        "EV-K-A1",
        "EV-K-B1",
        "EV-K-N1",
        "EV-K-A2",
        "EV-K-A3",
    )
    assert tuple(i.evidence_id for i in reconstruction_corpus(4, project_id="P")) == (
        "EV-K-A1",
        "EV-K-B1",
        "EV-K-N1",
        "EV-K-A2",
        "EV-K-A3",
        "EV-K-B2",
    )
    assert all(i.project_id == "P" for i in reconstruction_corpus(4, project_id="P"))


def test_arm_schedule_is_exact_12_entry_rotation() -> None:
    assert ARM_SCHEDULE == (
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
    assert len(ARM_SCHEDULE) == 12


def test_timeline_source_does_not_import_expectations() -> None:
    source = Path(timeline_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "expectations" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "expectations" not in module
            for alias in node.names:
                assert "expectations" not in alias.name


def test_evidence_records_reports_structural_facts_only() -> None:
    records = evidence_records()
    assert len(records) == 6
    for record, expected in zip(records, _EXPECTED, strict=True):
        (
            t,
            evidence_id,
            _source_ref,
            artifact_ref,
            supersedes_evidence_id,
            observed_at,
            content,
        ) = expected
        assert record.t == t
        assert record.evidence_id == evidence_id
        assert record.source_kind is SourceKind.DOCUMENT
        assert record.artifact_ref == artifact_ref
        assert record.supersedes_evidence_id == supersedes_evidence_id
        assert record.observed_at == observed_at.isoformat().replace("+00:00", "Z")
        assert record.scope == SCOPE_TUPLE
        assert record.content_sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert record.content_bytes == len(content.encode("utf-8"))
