"""Post-run forensic audit of locus validation v6: DIAGNOSTIC / COUNTERFACTUAL ONLY.

Nothing here rescores v6. The sealed verdict stays ``LOCUS_POLICY_NOT_VALIDATED``; the
diagnostic never emits a standing, never writes into the frozen experiment directory, and may
remove only findings that the audit demonstrates to be harness defects. It never excuses an
omitted meaning, a wrong concern, a wrong correction or an inadequate subject.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.experiments.locus_validation_v6.runner import RunRecord
from foundry.experiments.locus_validation_v6_audit.claim_coverage import (
    ClaimCoverage,
    ExpectedMeaning,
    coverage_findings,
)
from foundry.experiments.locus_validation_v6_audit.diagnostic import (
    DIAGNOSTIC_LABEL,
    corrected_repeat_findings,
    diagnose,
)

V6 = Path("docs/superpowers/experiments/2026-09-30-locus-validation-v6")


@pytest.fixture(scope="module")
def run() -> RunRecord:
    return RunRecord.model_validate(json.loads((V6 / "run.json").read_text()))


@pytest.fixture(scope="module")
def answers() -> dict[str, str]:
    raw = json.loads((V6 / "adjudication_answers.json").read_text())
    return {a["id"]: a["answer"] for a in raw["answers"]}


# ------------------------------------------------------------------ the coverage law


def _m(mid: str, concern: str = "C", *incompatible: str) -> ExpectedMeaning:
    return ExpectedMeaning(id=mid, concern=concern, incompatible_with=incompatible)


def test_one_meaning_stated_by_two_faithful_claims_is_covered() -> None:
    expected = (_m("RES-2"), _m("RES-3"))
    claims = (
        ClaimCoverage(claim_id="c1", concern="C", states=("RES-2",)),
        ClaimCoverage(claim_id="c2", concern="C", states=("RES-2",)),
        ClaimCoverage(claim_id="c3", concern="C", states=("RES-3",)),
    )
    assert coverage_findings(expected, claims) == ()


def test_a_compound_meaning_with_a_clause_omitted_is_missing() -> None:
    """The meaning is split into its clauses; one clause stated by no claim fails."""
    expected = (_m("CREDIT-3"), _m("CREDIT-4"))
    claims = (ClaimCoverage(claim_id="deadline", concern="C", states=("CREDIT-3",)),)
    assert coverage_findings(expected, claims) == ("MISSING_MEANING: CREDIT-4",)


def test_an_extra_or_incompatible_claim_fails() -> None:
    expected = (_m("LATE-7"),)
    extra = ClaimCoverage(claim_id="x", concern="C", states=())
    wrong = ClaimCoverage(claim_id="w", concern="C", states=("LATE-7",), incompatible=True)
    ok = ClaimCoverage(claim_id="ok", concern="C", states=("LATE-7",))
    assert coverage_findings(expected, (ok, extra)) == ("EXTRA_MEANING: x",)
    assert coverage_findings(expected, (ok, wrong)) == ("INCOMPATIBLE_CLAIM: w",)


def test_one_claim_cannot_satisfy_two_incompatible_expectations() -> None:
    expected = (_m("OLD", "C", "NEW"), _m("NEW", "C", "OLD"))
    both = ClaimCoverage(claim_id="both", concern="C", states=("OLD", "NEW"))
    assert coverage_findings(expected, (both,)) == (
        "DOUBLE_COUNTED: both states OLD and NEW",
        "MISSING_MEANING: OLD",
        "MISSING_MEANING: NEW",
    )


def test_a_claim_at_the_wrong_concern_does_not_cover() -> None:
    expected = (_m("A-1", "A"),)
    misplaced = ClaimCoverage(claim_id="m", concern="B", states=("A-1",))
    assert coverage_findings(expected, (misplaced,)) == (
        "WRONG_CONCERN: m at B states A-1 of A",
        "MISSING_MEANING: A-1",
    )


# ------------------------------------------------------------------ the recorded run


def test_the_diagnostic_is_labelled_and_never_a_standing(run: RunRecord, answers: dict) -> None:  # type: ignore[type-arg]
    result = diagnose(run, answers)
    assert result.label == DIAGNOSTIC_LABEL
    assert "counterfactual" in DIAGNOSTIC_LABEL.lower() and "not a rescore" in DIAGNOSTIC_LABEL
    dumped = json.dumps(result.model_dump(mode="json"))
    assert "LOCUS_POLICY_VALIDATED" not in dumped
    assert not hasattr(result, "standing")


def test_faithful_compound_splits_are_harness_findings_and_are_removed(
    run: RunRecord,
    answers: dict,  # type: ignore[type-arg]
) -> None:
    result = diagnose(run, answers)
    removed = {r.case for r in result.removed}
    assert {"D0-DENSE-FORMATION", "D1-RESERVATION-ONE-CONCERN"} <= removed
    assert {"D2-UNLOCK-ATTEMPTS-ONE-CONCERN", "X2-MANY-TO-ONE"} <= removed
    for r in result.removed:
        assert r.defect in ("CLAIM_CARDINALITY_ORACLE", "Z4_VISIBLE_EVIDENCE_SCORER"), r
    assert all(
        "CLAIM_COUNT" in r.finding or "HELD_COUNT" in r.finding or "REOPENED" in r.finding
        for r in result.removed
    )


def test_the_corrected_repeat_law_passes_the_recorded_suppression(run: RunRecord) -> None:
    assert corrected_repeat_findings(run) == ()


def test_the_corrected_repeat_law_still_sees_a_genuine_reopening(run: RunRecord) -> None:
    (dense,) = [lg for lg in run.ledgers if lg.ledger == "dense"]
    (decline,) = [b for b in dense.branches if b.branch == "DECLINE"]
    assert decline.t3 is not None
    semantic = decline.t3.state_after.semantic
    declined = next(
        r
        for r in semantic.correction_sets.values()
        if r.status == "DECLINED" and len(r.assertion_judgment_ids) == 3
    )
    reopened = declined.model_copy(
        update={
            "correction_set_id": "CSET-DOCTORED",
            "status": "PENDING",
            "decided_by": None,
            "decision_event_id": None,
            "authority_record_id": None,
            "rationale": None,
        }
    )
    doctored = semantic.model_copy(
        update={"correction_sets": {**semantic.correction_sets, "CSET-DOCTORED": reopened}}
    )
    t3 = decline.t3.model_copy(
        update={"state_after": decline.t3.state_after.model_copy(update={"semantic": doctored})}
    )
    branches = tuple(
        b.model_copy(update={"t3": t3}) if b.branch == "DECLINE" else b for b in dense.branches
    )
    bad = run.model_copy(
        update={
            "ledgers": tuple(
                lg.model_copy(update={"branches": branches}) if lg.ledger == "dense" else lg
                for lg in run.ledgers
            )
        }
    )
    assert any(f.startswith("REOPENED:") for f in corrected_repeat_findings(bad))


def test_the_changed_cleaning_fee_is_not_read_as_the_declined_unlock_repeat(
    run: RunRecord,
) -> None:
    """The legitimate new cleaning-fee set is PENDING and the corrected law ignores it."""
    (dense,) = [lg for lg in run.ledgers if lg.ledger == "dense"]
    (decline,) = [b for b in dense.branches if b.branch == "DECLINE"]
    assert decline.t3 is not None
    pending = [
        r for r in decline.t3.state_after.semantic.correction_sets.values() if r.status == "PENDING"
    ]
    assert len(pending) == 1 and len(pending[0].assertion_judgment_ids) == 1
    assert corrected_repeat_findings(run) == ()


def test_k_credit_4_is_judged_missing_and_every_question_listing_it_fails(
    run: RunRecord,
    answers: dict,  # type: ignore[type-arg]
) -> None:
    result = diagnose(run, answers)
    overridden = {o.question for o in result.semantic_overrides}
    assert overridden == {
        "Q-T1-DENSE-SERVICE-CREDIT",
        "Q-AGREED-X3-ONE-TO-MANY",
        "Q-DECLINED-X3-ONE-TO-MANY",
    }
    assert all(o.to == "NO" and o.frozen == "YES" for o in result.semantic_overrides)
    assert "Q-T2-X3-ONE-TO-MANY" in result.remaining_semantic_no


def test_the_four_subject_answers_stand_under_the_g2_subject_contract(
    run: RunRecord,
    answers: dict,  # type: ignore[type-arg]
) -> None:
    result = diagnose(run, answers)
    for q in (
        "Q-T1-CORE-PICKUP",
        "Q-T1-CORE-WEIGHT",
        "Q-T1-LARGE-CUSTOMER-REFUND",
        "Q-T1-LARGE-SELLER-LIMIT",
    ):
        assert q in result.remaining_semantic_no


def test_no_no_answer_is_ever_turned_into_yes(run: RunRecord, answers: dict) -> None:  # type: ignore[type-arg]
    result = diagnose(run, answers)
    frozen_no = {q for q, a in answers.items() if a != "YES"}
    assert frozen_no <= set(result.remaining_semantic_no)


def test_what_remains_after_removing_only_the_two_harness_defects(
    run: RunRecord,
    answers: dict,  # type: ignore[type-arg]
) -> None:
    result = diagnose(run, answers)
    assert result.remaining_structural == {}
    assert set(result.remaining_failed_cases) == {
        "C0-CORE-SEED",
        "C8-LARGE-WORLD",
        "U4-CUSTOMER-VS-SUPPLIER-REFUND",
        "X3-ONE-TO-MANY",
        "D4-SERVICE-CREDIT-ONE-CONCERN",
        "Z2-AGREE",
        "Z3-DECLINE",
    }


def test_the_frozen_v6_evidence_is_untouched_by_the_audit() -> None:
    names = sorted(p.name for p in V6.iterdir())
    assert "diagnostic.json" not in names and "counterfactual.json" not in names
    verdict = json.loads((V6 / "verdicts.json").read_text())
    assert verdict["standing"] == "LOCUS_POLICY_NOT_VALIDATED"
