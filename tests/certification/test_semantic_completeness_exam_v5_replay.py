"""Exam v5's pre-seal gate: every recorded Astra finding of exams v2, v3 and v4, replayed.

DIAGNOSTIC ONLY. Each historical live record keeps its formal standing (v2 66/75, v3 74/75,
v4 72/75, all NOT CERTIFIED); nothing is re-scored. The replay proves the v5 scorer treats
already-observed language exactly as the scorer that judged it did, except for the four
demonstrated scorer false negatives it exists to correct. Any other change blocks the seal.
"""

from __future__ import annotations

import hashlib
import json

import tests.certification._completeness_exam_v5 as exam
from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._completeness_exam_v5 import (
    EXPECTED_REPLAY_CHANGES,
    HISTORICAL_RECORDS,
    NOT_REPLAYABLE,
    ReplayRow,
    historical_replay,
    replay_problems,
)


def test_the_replay_reads_exactly_the_pinned_v2_v3_and_v4_records() -> None:
    assert [(r.exam, r.namespace, r.sha256) for r in HISTORICAL_RECORDS] == [
        ("v2", "semantic_completeness_verification_exam_v2",
         "ec509dfcb371818d7c5f4e4863cb1712a4bb917ceac3319b6b7a3f2181e8aa86"),
        ("v3", "semantic_completeness_verification_exam_v3",
         "0548fd47ae106b9592530e35776324bf0abe31bf2d90f713bdf07124c62a0319"),
        ("v4", "semantic_completeness_verification_exam_v4",
         "e1285e6d2ae6add059d20ed9386721b807d90746ccc422aae6f5d4624a641e06"),
    ]  # fmt: skip
    for r in HISTORICAL_RECORDS:
        path = EVIDENCE_ROOT / f"openai/gpt-6-astra/{r.namespace}/certification.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == r.sha256


def test_every_recorded_finding_is_replayed_or_named_as_not_replayable() -> None:
    rows = historical_replay()
    replayed = {(r.exam, r.case, r.attempt) for r in rows}
    for record in HISTORICAL_RECORDS:
        path = EVIDENCE_ROOT / f"openai/gpt-6-astra/{record.namespace}/certification.json"
        attempts = json.loads(path.read_text())["attempts"]
        assert len(attempts) == 75
        for a in attempts:
            key = (record.exam, a["case"], a["attempt"])
            assert (key in replayed) != ((record.exam, a["case"]) in NOT_REPLAYABLE), key
    assert frozenset(("v2", c) for c in ("C02", "C04", "C10", "C22", "C24")) == NOT_REPLAYABLE, (
        "exactly the payloads exam v3 replaced"
    )
    assert len({(r.exam, r.case, r.attempt) for r in rows}) == 60 + 75 + 75


def test_each_historical_result_is_the_one_its_own_exam_recorded() -> None:
    by_attempt: dict[tuple[str, str, int], list[ReplayRow]] = {}
    for row in historical_replay():
        by_attempt.setdefault((row.exam, row.case, row.attempt), []).append(row)
    for (_, _, _), rows in by_attempt.items():
        recorded = {r.recorded_verdict for r in rows}
        assert len(recorded) == 1
        assert ("PASS" in recorded) == all(r.historical == "PASS" for r in rows), rows


def test_only_the_four_demonstrated_scorer_false_negatives_change() -> None:
    changed = {
        (r.exam, r.case, r.attempt, r.proposition_id): (r.historical, r.v5)
        for r in historical_replay()
        if r.historical != r.v5
    }
    assert changed == {
        ("v3", "C05", 1, "p1"): ("FAIL", "PASS"),
        ("v4", "C05", 2, "p1"): ("FAIL", "PASS"),
        ("v4", "C05", 3, "p1"): ("FAIL", "PASS"),
        ("v4", "C17", 1, "p2"): ("FAIL", "PASS"),
    }
    assert set(changed) == EXPECTED_REPLAY_CHANGES
    assert replay_problems(historical_replay()) == ()


def test_the_gate_reports_any_unexpected_change() -> None:
    rows = list(historical_replay())
    i = next(i for i, r in enumerate(rows) if (r.exam, r.case) == ("v3", "C09"))
    rows[i] = rows[i]._replace(v5="FAIL", reason="synthetic")
    j = next(i for i, r in enumerate(rows) if (r.exam, r.case, r.attempt) == ("v4", "C17", 1))
    rows[j] = rows[j]._replace(v5="FAIL")
    problems = replay_problems(tuple(rows))
    assert any("v3 C09" in p for p in problems) and any("v4 C17/1" in p for p in problems)


def test_the_seal_cannot_be_written_while_the_replay_gate_fails(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(exam, "replay_problems", lambda rows: ("an unexpected change",))
    try:
        exam.write_completeness_seal(tmp_path / "seal.json", harness_sha="a" * 40)
    except RuntimeError as exc:
        assert "replay" in str(exc)
    else:
        raise AssertionError("sealed past a failing replay gate")
    assert not (tmp_path / "seal.json").exists()


def test_the_audit_table_names_every_changed_result_and_its_reason() -> None:
    for row in historical_replay():
        if row.historical != row.v5:
            assert row.reason and row.findings, row
        assert row.findings is not None
