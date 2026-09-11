"""Real Foundry four-commit timeline loader (spec §15, §20, §25; plan Task 10).

Evidence is read from named commits only, never the working tree. Lineage
(``artifact_ref`` / ``supersedes_evidence_id``) is deterministic Git data. Scope is
per path (preflight ruling P5): the constitution is ``("constitution",)``, every
other path is ``("intent-engine",)``.

The Git reader is a fake keyed by ``(commit, path)``; there is no network and no
repository access in this module.
"""

from __future__ import annotations

import hashlib
import socket
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import SourceKind
from foundry.experiments.longitudinal.timeline import (
    TIMELINE,
    TimelinePath,
    TimelineStep,
    VersionedEvidence,
    evidence_hashes,
    load_timeline,
    persistent_delta,
    reconstruction_corpus,
)

T0 = datetime(2026, 9, 11, tzinfo=UTC)
PROJECT = "PROJ-9P"

T1 = "097584a39dd76cf86510500acb548778ce00fad9"
T2 = "2539ff81f79f085c1eba42718947050c1b3ac61c"
T3 = "90246a8b986b0dcbcbae6a4f3484204f916afeb5"
T4 = "779a66ac90eceaea7eb7d4af0692ee4f167292fc"

CONSTITUTION = "FOUNDRY_CONSTITUTION.md"
SPEC = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER = "src/foundry/application/semantic_reducer.py"
IDENTITY = "src/foundry/domain/semantic_identity.py"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)


class FakeGit:
    """Serves bytes for exact ``(commit, path)`` pairs; anything else does not exist."""

    def __init__(self, blobs: dict[tuple[str, str], bytes]) -> None:
        self._blobs = blobs
        self.requests: list[tuple[str, str]] = []

    def blob(self, sha: str, path: str) -> bytes:
        self.requests.append((sha, path))
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return self._blobs[(sha, path)]

    def blob_sha(self, sha: str, path: str) -> str:
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return hashlib.sha1(b"blob " + self._blobs[(sha, path)]).hexdigest()


def _blobs(*, spec_t2_same_as_t1: bool = False) -> dict[tuple[str, str], bytes]:
    spec_t2 = b"spec v1\n" if spec_t2_same_as_t1 else b"spec v2\n"
    return {
        (T1, CONSTITUTION): b"constitution v1\n",
        (T1, SPEC): b"spec v1\n",
        (T2, SPEC): spec_t2,
        (T3, REDUCER): b"reducer v1\n",
        (T3, IDENTITY): b"identity v1\n",
        (T4, REDUCER): b"reducer v2\n",
        (T4, SPEC): b"spec v3\n",
    }


def _observed_at(t: int) -> datetime:
    return T0 + timedelta(days=t)


@pytest.fixture
def git() -> FakeGit:
    return FakeGit(_blobs())


@pytest.fixture
def loaded(git: FakeGit) -> tuple[VersionedEvidence, ...]:
    return load_timeline(git, project_id=PROJECT, observed_at_for=_observed_at)


def _by_id(items: tuple[VersionedEvidence, ...]) -> dict[str, VersionedEvidence]:
    return {v.item.evidence_id: v for v in items}


# --------------------------------------------------------------------------- timeline


def test_timeline_is_the_four_approved_commits_and_paths() -> None:
    approved = (
        TimelineStep(
            t=1,
            commit=T1,
            paths=(
                TimelinePath(
                    repo_path=CONSTITUTION,
                    source_kind=SourceKind.DOCUMENT,
                    scope=("constitution",),
                ),
                TimelinePath(
                    repo_path=SPEC, source_kind=SourceKind.DOCUMENT, scope=("intent-engine",)
                ),
            ),
        ),
        TimelineStep(
            t=2,
            commit=T2,
            paths=(
                TimelinePath(
                    repo_path=SPEC, source_kind=SourceKind.DOCUMENT, scope=("intent-engine",)
                ),
            ),
        ),
        TimelineStep(
            t=3,
            commit=T3,
            paths=(
                TimelinePath(
                    repo_path=REDUCER, source_kind=SourceKind.CODE, scope=("intent-engine",)
                ),
                TimelinePath(
                    repo_path=IDENTITY, source_kind=SourceKind.CODE, scope=("intent-engine",)
                ),
            ),
        ),
        TimelineStep(
            t=4,
            commit=T4,
            paths=(
                TimelinePath(
                    repo_path=REDUCER, source_kind=SourceKind.CODE, scope=("intent-engine",)
                ),
                TimelinePath(
                    repo_path=SPEC, source_kind=SourceKind.DOCUMENT, scope=("intent-engine",)
                ),
            ),
        ),
    )
    assert approved == TIMELINE
    assert [step.t for step in TIMELINE] == [1, 2, 3, 4]


def test_timeline_step_requires_a_full_commit_sha() -> None:
    with pytest.raises(ValueError):
        TimelineStep(t=1, commit="097584a", paths=())


def test_constitution_is_scoped_constitution_and_others_intent_engine(
    loaded: tuple[VersionedEvidence, ...],
) -> None:
    for version in loaded:
        expected = ("constitution",) if version.repo_path == CONSTITUTION else ("intent-engine",)
        assert version.scope == expected
        assert version.item.scope == expected
    assert sum(1 for v in loaded if v.scope == ("constitution",)) == 1


# --------------------------------------------------------------------------- reading


def test_reads_only_from_named_commits_never_working_tree(git: FakeGit) -> None:
    loaded = load_timeline(git, project_id=PROJECT, observed_at_for=_observed_at)

    assert git.requests == [
        (T1, CONSTITUTION),
        (T1, SPEC),
        (T2, SPEC),
        (T3, REDUCER),
        (T3, IDENTITY),
        (T4, REDUCER),
        (T4, SPEC),
    ]
    assert {sha for sha, _ in git.requests} == {T1, T2, T3, T4}
    assert [(v.commit, v.repo_path) for v in loaded] == git.requests
    for version in loaded:
        assert version.item.source_ref == f"git://{version.commit}/{version.repo_path}"
        assert version.item.content == _blobs()[(version.commit, version.repo_path)].decode()
        assert version.item.project_id == PROJECT
        assert version.item.observed_at == _observed_at(version.t)
        assert version.item.source_kind == version.source_kind


def test_loader_fails_if_a_named_commit_is_unavailable() -> None:
    blobs = _blobs()
    del blobs[(T3, IDENTITY)]
    with pytest.raises(RuntimeError, match="no blob"):
        load_timeline(FakeGit(blobs), project_id=PROJECT, observed_at_for=_observed_at)


def test_evidence_ids_follow_the_ev_t_convention(loaded: tuple[VersionedEvidence, ...]) -> None:
    assert [v.item.evidence_id for v in loaded] == [
        "EV-T1-01",
        "EV-T1-02",
        "EV-T2-01",
        "EV-T3-01",
        "EV-T3-02",
        "EV-T4-01",
        "EV-T4-02",
    ]
    assert [v.t for v in loaded] == [1, 1, 2, 3, 3, 4, 4]


# --------------------------------------------------------------------------- lineage


def test_lineage_links_versions_of_the_same_artifact_linearly(
    loaded: tuple[VersionedEvidence, ...],
) -> None:
    by_id = _by_id(loaded)
    for version in loaded:
        assert version.artifact_ref == f"repo:{version.repo_path}"
        assert version.item.artifact_ref == version.artifact_ref

    # spec: T1 -> T2 -> T4
    assert by_id["EV-T1-02"].item.supersedes_evidence_id is None
    assert by_id["EV-T2-01"].item.supersedes_evidence_id == "EV-T1-02"
    assert by_id["EV-T4-02"].item.supersedes_evidence_id == "EV-T2-01"
    # reducer: T3 -> T4
    assert by_id["EV-T3-01"].item.supersedes_evidence_id is None
    assert by_id["EV-T4-01"].item.supersedes_evidence_id == "EV-T3-01"
    # first (only) versions
    assert by_id["EV-T1-01"].item.supersedes_evidence_id is None
    assert by_id["EV-T3-02"].item.supersedes_evidence_id is None

    for version in loaded:
        previous = version.item.supersedes_evidence_id
        if previous is not None:
            assert by_id[previous].artifact_ref == version.artifact_ref
            assert by_id[previous].t < version.t


# --------------------------------------------------------------------------- arms


def test_persistent_delta_excludes_unchanged_artifacts() -> None:
    git = FakeGit(_blobs(spec_t2_same_as_t1=True))
    loaded = load_timeline(git, project_id=PROJECT, observed_at_for=_observed_at)

    assert [i.evidence_id for i in persistent_delta(loaded, 1)] == ["EV-T1-01", "EV-T1-02"]
    # T2's spec bytes are identical to T1's: not a delta. Constitution never re-sent.
    assert persistent_delta(loaded, 2) == ()
    assert [i.evidence_id for i in persistent_delta(loaded, 3)] == ["EV-T3-01", "EV-T3-02"]
    assert [i.evidence_id for i in persistent_delta(loaded, 4)] == ["EV-T4-01", "EV-T4-02"]

    for t in (2, 3, 4):
        assert all(i.artifact_ref != f"repo:{CONSTITUTION}" for i in persistent_delta(loaded, t))


def test_persistent_delta_sends_a_changed_version(loaded: tuple[VersionedEvidence, ...]) -> None:
    assert [i.evidence_id for i in persistent_delta(loaded, 2)] == ["EV-T2-01"]
    assert persistent_delta(loaded, 2)[0].supersedes_evidence_id == "EV-T1-02"
    assert persistent_delta(loaded, 5) == ()


def test_reconstruction_corpus_is_cumulative_all_versions(
    loaded: tuple[VersionedEvidence, ...],
) -> None:
    ids = [v.item.evidence_id for v in loaded]
    assert [i.evidence_id for i in reconstruction_corpus(loaded, 1)] == ids[:2]
    assert [i.evidence_id for i in reconstruction_corpus(loaded, 2)] == ids[:3]
    assert [i.evidence_id for i in reconstruction_corpus(loaded, 3)] == ids[:5]
    assert [i.evidence_id for i in reconstruction_corpus(loaded, 4)] == ids
    assert reconstruction_corpus(loaded, 4) == tuple(v.item for v in loaded)
    assert reconstruction_corpus(loaded, 0) == ()


def test_hashes_recorded_per_version(loaded: tuple[VersionedEvidence, ...]) -> None:
    blobs = _blobs()
    recorded = evidence_hashes(loaded)
    assert len(recorded) == len(loaded)
    for entry, version in zip(recorded, loaded, strict=True):
        raw = blobs[(version.commit, version.repo_path)]
        assert entry == {
            "t": str(version.t),
            "artifact_ref": version.artifact_ref,
            "commit": version.commit,
            "git_blob_sha": hashlib.sha1(b"blob " + raw).hexdigest(),
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }
        assert version.git_blob_sha == entry["git_blob_sha"]
        assert version.content_sha256 == entry["content_sha256"]
        assert version.item.content_sha256 == entry["content_sha256"]
    assert len({e["content_sha256"] for e in recorded}) == len(recorded)


# --------------------------------------------------------------------------- reducer


def test_items_ingest_through_the_reducer_lineage_checks(
    loaded: tuple[VersionedEvidence, ...],
) -> None:
    ticks = count(1)
    governor = SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: T0,
        id_factory=lambda prefix: f"{prefix}-{next(ticks):04d}",
    )
    for version in loaded:
        governor.ingest(version.item)  # any ValueError here is a lineage defect

    view = governor.view()
    assert view.current_evidence_ids == ("EV-T1-01", "EV-T3-02", "EV-T4-01", "EV-T4-02")
    assert view.superseded_evidence_ids == ("EV-T1-02", "EV-T2-01", "EV-T3-01")
    assert len(governor.state().semantic.evidence) == len(loaded)
