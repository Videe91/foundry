"""Frozen Orion corpus for the 9P3 long-horizon bounded-memory experiment (T1).

Locks the 192 model-visible Orion evidence items (16 versions x 12 loci), their
lineage, document-order regimes, timestamps, the byte-exact section texts (checked
against the 38 fenced ``text`` blocks of the approved spec as a test-time oracle
only), the persistent/reconstruction projections, structural records and raw
character counts. Nothing here decides semantic meaning; ``timeline.py`` must not
import ``expectations`` or ``protocol`` (checked by parsing its source with ``ast``).
"""

from __future__ import annotations

import ast
import hashlib
import re
import socket
from pathlib import Path

import pytest

from foundry.experiments.long_horizon_bounded import timeline as timeline_module
from foundry.experiments.long_horizon_bounded.timeline import (
    ARTIFACT_REFS,
    DOCUMENT_ORDER,
    EXPERIMENT_VERSION,
    LOCI,
    PROJECT_ID,
    SCOPE,
    SECTION_TEXT,
    TIMELINE,
    VERSION_COUNT,
    evidence_records,
    observed_at,
    persistent_delta,
    raw_evidence_character_count,
    reconstruction_corpus,
)

SPEC = (
    Path(__file__).resolve().parents[2]
    / "docs/superpowers/specs/2026-09-13-9p3-long-horizon-bounded-memory-design.md"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _spec_section_texts() -> list[str]:
    # test-time oracle only: the 38 fenced ```text blocks that begin with "## "
    return re.findall(r"```text\n(## .*?)```", SPEC.read_text(encoding="utf-8"), re.S)


def test_constants_are_locked() -> None:
    assert EXPERIMENT_VERSION == "intent-v2-long-horizon-bounded-memory-v1"
    assert PROJECT_ID == "PROJ-9P3-ORION" and SCOPE == "orion-jobs" and VERSION_COUNT == 16
    assert tuple("ABCDEFGHIJKL") == LOCI


def test_timeline_has_192_items_with_exact_ids_and_stable_artifact_refs() -> None:
    assert len(TIMELINE) == 192
    assert [e.item.evidence_id for e in TIMELINE][:3] == ["EV-O-A01", "EV-O-B01", "EV-O-C01"]
    for e in TIMELINE:
        assert e.item.artifact_ref == ARTIFACT_REFS[e.locus]
        assert e.item.scope == ("orion-jobs",) and e.item.project_id == PROJECT_ID


def test_180_lineage_edges_each_to_same_locus_previous_version() -> None:
    edges = [
        (e.t, e.locus, e.item.supersedes_evidence_id)
        for e in TIMELINE
        if e.item.supersedes_evidence_id
    ]
    assert len(edges) == 180
    for t, locus, pred in edges:
        assert t >= 2 and pred == f"EV-O-{locus}{t - 1:02d}"
    assert all(e.item.supersedes_evidence_id is None for e in TIMELINE if e.t == 1)


def test_document_order_regimes_and_observed_at() -> None:
    assert DOCUMENT_ORDER[1] == tuple("ABCDEFGHIJKL")
    assert DOCUMENT_ORDER[4] == tuple("ACBFGHDEKIJL") and DOCUMENT_ORDER[12] == DOCUMENT_ORDER[4]
    assert DOCUMENT_ORDER[13] == tuple("ACBFGHDEIJKL") and DOCUMENT_ORDER[16] == DOCUMENT_ORDER[13]
    # C is position 1 at T4
    assert observed_at(4, "C").isoformat() == "2026-10-04T00:01:00+00:00"


def test_section_texts_are_byte_exact_to_the_spec_blocks() -> None:
    blocks = _spec_section_texts()
    assert len(blocks) == 38
    # block order in the spec: 0-11 = T1 (A..L), 12 = T2 C, 13 = T3 A,
    # 14-25 = T4 (document order), 26-37 = T5..T16
    t1 = blocks[:12]
    t4 = blocks[14:26]
    for locus, text in zip("ABCDEFGHIJKL", t1, strict=True):
        assert SECTION_TEXT[(1, locus)] == text
    for locus, text in zip("ACBFGHDEKIJL", t4, strict=True):
        assert SECTION_TEXT[(4, locus)] == text
    replacements = {
        2: "C",
        3: "A",
        5: "B",
        6: "A",
        7: "F",
        8: "B",
        9: "H",
        10: "D",
        11: "L",
        12: "G",
        13: "K",
        14: "J",
        15: "F",
        16: "I",
    }
    single = [blocks[12], blocks[13]] + blocks[26:]  # T2, T3, then T5..T16 in order
    for (t, locus), text in zip(sorted(replacements.items()), single, strict=True):
        assert SECTION_TEXT[(t, locus)] == text


def test_unchanged_sections_carry_forward_byte_identical() -> None:
    assert SECTION_TEXT[(2, "A")] == SECTION_TEXT[(1, "A")]
    assert SECTION_TEXT[(9, "B")] == SECTION_TEXT[(8, "B")]
    assert SECTION_TEXT[(16, "H")] == SECTION_TEXT[(9, "H")]


def test_t1_h_unchanged_and_t9_h_is_idempotent_repeat_cancellation() -> None:
    assert "no future execution attempt of that job may be started" in SECTION_TEXT[(1, "H")]
    t9 = SECTION_TEXT[(9, "H")]
    assert (
        "3. If Orion receives a cancellation for a job that is already cancelled, the job "
        "must remain cancelled and the repeated cancellation must not otherwise change the "
        "job's state."
    ) in t9
    assert "never begin execution" not in t9


def test_every_section_at_most_1400_chars_and_no_grading_labels() -> None:
    forbidden = (
        "correction",
        "restatement",
        "revert",
        "no-op",
        "compatible extension",
        "expected",
        "lifecycle",
        "checkpoint",
        "SELECT_",
        "material error",
    )
    for (t, locus), text in SECTION_TEXT.items():
        assert len(text) <= 1400, (t, locus)
        assert not any(w.lower() in text.lower() for w in forbidden), (t, locus)


def test_persistent_delta_and_reconstruction_corpus() -> None:
    assert [i.evidence_id for i in persistent_delta(4, project_id="X")] == [
        f"EV-O-{locus}04" for locus in "ACBFGHDEKIJL"
    ]
    assert all(i.project_id == "X" for i in persistent_delta(4, project_id="X"))
    for t in range(1, 17):
        assert len(reconstruction_corpus(t, project_id="X")) == 12 * t
    ids = [i.evidence_id for i in reconstruction_corpus(16, project_id="X")]
    assert ids[:12] == [f"EV-O-{locus}01" for locus in "ABCDEFGHIJKL"]
    assert ids[-1] == "EV-O-L16"


def test_evidence_records_hashes_and_raw_character_count() -> None:
    records = evidence_records()
    assert len(records) == 192
    for r in records:
        assert r.content_sha256 == hashlib.sha256(SECTION_TEXT[(r.t, r.locus)].encode()).hexdigest()
    assert raw_evidence_character_count(16) == sum(len(t) for t in SECTION_TEXT.values())
    assert raw_evidence_character_count(1) == sum(len(SECTION_TEXT[(1, locus)]) for locus in LOCI)


def test_timeline_does_not_import_expectations_or_protocol() -> None:
    tree = ast.parse(Path(timeline_module.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not any("expectations" in m or "protocol" in m for m in mods)
