"""Timepoint-exact adjudication and the all-or-nothing standing of locus validation v3.

v2's sealed questions asked about T1 but were answered against the final state (Q-SEED-LABEL
and Q-SEED-WEIGHT then said NO for claims added at T2). Here every question names its ledger
and timepoint, and its packet is that ledger's frozen state after exactly that delta: these
tests prove that nothing later can reach an earlier packet, and that the standing admits no
partial pass and never passes without the critical C09 case.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import count

import pytest

from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v3.adjudication import (
    NOT_VALIDATED,
    VALIDATED,
    adjudication_bundle,
    packet,
    packet_id,
    standing,
)
from foundry.experiments.locus_validation_v3.evaluation import CaseResult, evaluate
from foundry.experiments.locus_validation_v3.expectations import (
    CASES,
    CRITICAL_CASE,
    SEMANTIC_QUESTIONS,
)
from foundry.experiments.locus_validation_v3.runner import LedgerRun, RunRecord, run_validation
from tests.unit._locus_v3_oracle import Oracle


@pytest.fixture(scope="module")
def lawful() -> RunRecord:
    ids = count(1)
    return run_validation(
        inner=Oracle(),
        guard_identity=False,
        clock=lambda: datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
    )


def _ledger(run: RunRecord, name: str) -> LedgerRun:
    (hit,) = [lg for lg in run.ledgers if lg.ledger == name]
    return hit


def _address(frozen: dict, document: str) -> dict:  # type: ignore[type-arg]
    (hit,) = [a for a in frozen["addresses"] if document in a["created_from_documents"]]
    return hit


def _live(address: dict) -> list[dict]:  # type: ignore[type-arg]
    return [c for c in address["claims"] if c["live"]]


# ------------------------------------------------------------------ the questions


def test_every_question_names_its_ledger_and_timepoint() -> None:
    for q in SEMANTIC_QUESTIONS:
        assert q.after in (1, 2)
        assert q.question.startswith(f"After T{q.after}, in ledger {q.ledger}"), q.id
        other = 2 if q.after == 1 else 1
        assert not re.search(rf"\bafter T{other}\b", q.question, re.IGNORECASE), q.id


def test_question_ids_carry_the_timepoint_they_judge() -> None:
    for q in SEMANTIC_QUESTIONS:
        assert q.id.startswith(f"Q-T{q.after}-"), q.id


# ------------------------------------------------------------------ packets


def test_a_t1_packet_holds_exactly_the_t1_state(lawful: RunRecord) -> None:
    core = _ledger(lawful, "core")
    t1 = packet(core, 1)
    assert t1["after"] == "T1" and t1["packet_id"] == "core-after-T1"
    assert len(t1["addresses"]) == 7
    assert {d["key"] for d in t1["documents_received"]} == {
        "PICKUP-T1",
        "LABEL-T1",
        "WEIGHT-T1",
        "ATTEMPTS-T1",
        "LATE-T1",
        "DAMAGE-T1",
        "SETTLEMENT-T1",
    }
    for address in t1["addresses"]:
        for claim in address["claims"]:
            assert all(c.endswith("-T1") for c in claim["cites"]), claim
    assert not t1["relations"]


def test_v2s_defect_cannot_recur_label_and_weight_are_judged_at_t1(lawful: RunRecord) -> None:
    """v2 judged Q-SEED-LABEL/WEIGHT on the final state and saw the T2 claims."""
    core = _ledger(lawful, "core")
    t1, t2 = packet(core, 1), packet(core, 2)
    assert len(_live(_address(t1, "LABEL-T1"))) == 2
    assert len(_live(_address(t2, "LABEL-T1"))) == 3
    assert len(_live(_address(t1, "WEIGHT-T1"))) == 2
    assert len(_live(_address(t2, "WEIGHT-T1"))) == 3
    assert [r["kind"] for r in t2["relations"] if r["kind"] == "SUPERSEDE"] == ["SUPERSEDE"]
    (supersede,) = [r for r in t2["relations"] if r["kind"] == "SUPERSEDE"]
    assert supersede["route"] == "REQUIRE_SECOND_LENS" and supersede["applied"] is False


def test_a_t2_packet_holds_the_t2_state(lawful: RunRecord) -> None:
    core = _ledger(lawful, "core")
    t2 = packet(core, 2)
    assert t2["after"] == "T2" and len(t2["addresses"]) == 8
    assert len(_live(_address(t2, "LATE-T1"))) == 3
    assert "LATE-NOTE-T2" in {d["key"] for d in t2["documents_received"]}


def test_the_orion_packets_split_c09_at_the_right_moment(lawful: RunRecord) -> None:
    orion = _ledger(lawful, "orion")
    assert len(_live(_address(packet(orion, 1), "H-T1"))) == 3
    assert len(_live(_address(packet(orion, 2), "H-T1"))) == 4


def test_a_packet_for_a_timepoint_that_does_not_exist_is_refused(lawful: RunRecord) -> None:
    core = _ledger(lawful, "core")
    with pytest.raises(ValueError):
        packet(core, 3)
    truncated = core.model_copy(update={"deltas": core.deltas[:1]})
    with pytest.raises(ValueError):
        packet(truncated, 2)


def test_the_bundle_gives_every_question_the_packet_of_its_own_timepoint(
    lawful: RunRecord,
) -> None:
    items = adjudication_bundle(lawful)["items"]
    assert [i["id"] for i in items] == [q.id for q in SEMANTIC_QUESTIONS]
    for item, q in zip(items, SEMANTIC_QUESTIONS, strict=True):
        expected = packet(_ledger(lawful, q.ledger), q.after)
        assert item["packet_id"] == packet_id(q.ledger, q.after)
        assert item["packet"] == expected
        assert item["packet"]["after"] == f"T{q.after}"
        assert item["packet_sha256"] == canonical_sha256(expected)


# ------------------------------------------------------------------ the standing


def _all_yes() -> dict[str, str]:
    return {q.id: "YES" for q in SEMANTIC_QUESTIONS}


def _structural(lawful: RunRecord) -> dict[str, CaseResult]:
    return evaluate(lawful)


def test_validated_only_when_everything_passes(lawful: RunRecord) -> None:
    result = standing(_structural(lawful), _all_yes())
    assert result.standing == VALIDATED
    assert result.semantic_all_yes and result.structural_all_passed
    assert result.critical_passed and all(result.cases.values())


def test_one_no_answer_is_not_validated(lawful: RunRecord) -> None:
    for q in SEMANTIC_QUESTIONS:
        answers = {**_all_yes(), q.id: "NO"}
        result = standing(_structural(lawful), answers)
        assert result.standing == NOT_VALIDATED, q.id
        assert result.semantic_no == (q.id,)
        assert result.semantic_all_yes is False, q.id


def test_a_missing_answer_is_not_validated(lawful: RunRecord) -> None:
    answers = _all_yes()
    del answers[SEMANTIC_QUESTIONS[-1].id]
    result = standing(_structural(lawful), answers)
    assert result.standing == NOT_VALIDATED
    assert result.semantic_missing == (SEMANTIC_QUESTIONS[-1].id,)
    assert result.semantic_all_yes is False


def test_any_structural_failure_is_not_validated(lawful: RunRecord) -> None:
    structural = _structural(lawful)
    for name in structural:
        broken = {**structural, name: CaseResult(case_id=name, passed=False, findings=("X",))}
        assert standing(broken, _all_yes()).standing == NOT_VALIDATED, name


def test_a_c09_failure_is_not_validated_and_is_named(lawful: RunRecord) -> None:
    structural = {
        **_structural(lawful),
        CRITICAL_CASE: CaseResult(case_id=CRITICAL_CASE, passed=False, findings=("OVER_SPLIT",)),
    }
    result = standing(structural, _all_yes())
    assert result.standing == NOT_VALIDATED
    assert result.critical_case == "C7-C09-REGRESSION" and result.critical_passed is False


def test_a_c09_semantic_no_alone_fails_the_critical_case(lawful: RunRecord) -> None:
    (critical,) = [c for c in CASES if c.id == CRITICAL_CASE]
    result = standing(_structural(lawful), {**_all_yes(), critical.semantic[-1]: "NO"})
    assert result.critical_passed is False and result.standing == NOT_VALIDATED


def test_no_structural_verdicts_is_not_validated() -> None:
    assert standing({}, _all_yes()).standing == NOT_VALIDATED


def test_an_answer_other_than_yes_counts_as_no(lawful: RunRecord) -> None:
    answers = {**_all_yes(), SEMANTIC_QUESTIONS[0].id: "yes"}
    result = standing(_structural(lawful), answers)
    assert result.standing == NOT_VALIDATED
    assert result.semantic_all_yes is False and result.semantic_no == (SEMANTIC_QUESTIONS[0].id,)
