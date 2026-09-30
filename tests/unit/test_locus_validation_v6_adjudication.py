"""Locus validation v6: timepoint-exact adjudication packets and the single standing.

Every question names its ledger and one of six timepoints; its packet is built from exactly
that frozen state: nothing later appears in an earlier packet, a branch packet never shows the
other branch, and a decision packet shows the scripted human's decisions. The standing is
all-or-nothing.
"""

from __future__ import annotations

import pytest

from foundry.experiments.locus_validation_v6.adjudication import (
    NOT_VALIDATED,
    VALIDATED,
    adjudication_bundle,
    packet,
    standing,
)
from foundry.experiments.locus_validation_v6.evaluation import CaseResult, evaluate
from foundry.experiments.locus_validation_v6.expectations import CRITICAL_CASES, SEMANTIC_QUESTIONS
from tests.unit.test_locus_validation_v6_evaluation import run_of

TIMEPOINTS = ("T1", "T2", "AGREED", "DECLINED", "T3-AGREE", "T3-DECLINE")


def _ledger(name: str):  # type: ignore[no-untyped-def]
    (lg,) = [lg for lg in run_of().ledgers if lg.ledger == name]
    return lg


def _judgments(p: dict) -> set[str]:  # type: ignore[type-arg]
    ids = {r["judgment_id"] for r in p["relations"]}
    return ids | {c["created_by_judgment_id"] for a in p["addresses"] for c in a["claims"]}


def test_every_dense_timepoint_has_its_own_packet() -> None:
    dense = _ledger("dense")
    for at in TIMEPOINTS:
        p = packet(dense, at)
        assert (p["ledger"], p["after"]) == ("dense", at)
        assert p["packet_id"] == f"dense-at-{at}"


def test_nothing_later_appears_in_an_earlier_packet_and_branches_do_not_mix() -> None:
    dense = _ledger("dense")
    t1, t2 = packet(dense, "T1"), packet(dense, "T2")
    agreed, declined = packet(dense, "AGREED"), packet(dense, "DECLINED")
    t3a, t3d = packet(dense, "T3-AGREE"), packet(dense, "T3-DECLINE")
    assert _judgments(t1) < _judgments(t2) <= _judgments(agreed) <= _judgments(t3a)
    assert _judgments(t2) <= _judgments(declined) <= _judgments(t3d)
    assert not (_judgments(t3a) - _judgments(agreed)) & _judgments(t3d)
    assert {d["key"] for d in t2["documents_received"]} >= {"K-CLEANING-T2", "K-TRIP-T2"}
    assert "K-CLEANING-T3" not in {d["key"] for d in agreed["documents_received"]}
    assert "K-CLEANING-T3" in {d["key"] for d in t3a["documents_received"]}


def test_decision_packets_show_the_architects_decisions_and_the_sets() -> None:
    dense = _ledger("dense")
    t2 = packet(dense, "T2")
    assert {s["status"] for s in t2["correction_sets"]} == {"PENDING"}
    assert t2["human_decisions"] == []
    for at, status in (("AGREED", "AGREED"), ("DECLINED", "DECLINED")):
        p = packet(dense, at)
        assert {s["status"] for s in p["correction_sets"]} == {status}
        assert len(p["human_decisions"]) == 4
        assert p["model_accounting"] is None
    assert packet(dense, "T3-AGREE")["model_accounting"] is not None


def test_a_carried_ledger_has_no_branch_packets() -> None:
    with pytest.raises(ValueError, match="no frozen state"):
        packet(_ledger("core"), "AGREED")


def test_the_bundle_holds_one_packet_per_question_of_its_own_timepoint() -> None:
    bundle = adjudication_bundle(run_of())
    assert [i["id"] for i in bundle["items"]] == [q.id for q in SEMANTIC_QUESTIONS]
    for item in bundle["items"]:
        assert item["packet"] is not None, item["id"]
        assert item["packet"]["after"] == item["after"]
        assert item["packet_sha256"]


def _all_pass() -> dict[str, CaseResult]:
    return evaluate(run_of())


def test_the_standing_is_validated_only_when_everything_passes() -> None:
    yes = {q.id: "YES" for q in SEMANTIC_QUESTIONS}
    assert standing(_all_pass(), yes).standing == VALIDATED
    one_no = dict(yes, **{SEMANTIC_QUESTIONS[0].id: "NO"})
    assert standing(_all_pass(), one_no).standing == NOT_VALIDATED
    missing = dict(yes)
    missing.pop(SEMANTIC_QUESTIONS[-1].id)
    assert standing(_all_pass(), missing).standing == NOT_VALIDATED
    broken = dict(_all_pass())
    broken["Z3-DECLINE"] = CaseResult(case_id="Z3-DECLINE", passed=False, findings=("X: y",))
    result = standing(broken, yes)
    assert result.standing == NOT_VALIDATED and result.cases["Z3-DECLINE"] is False
    assert result.critical_cases == CRITICAL_CASES
