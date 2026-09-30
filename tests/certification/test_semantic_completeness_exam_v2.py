"""Exam v2 for SEMANTIC_COMPLETENESS_VERIFICATION: corpus, finding matcher and scorer (offline).

Exam v1 scored the top-level verdict only, so a verifier could be certified while naming the
wrong region, or none. Exam v2's law: every proposition's verdict must be right AND every
non-COMPLETE finding must identify the actual semantic region, by deterministic, sealed,
case-specific mandatory marker groups matched on normalised whole-word / phrase boundaries.
No model adjudicates. A COMPLETE proposition is judged by its verdict alone, and the number of
claims never matters.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from foundry.domain.semantic_completeness import (
    CompletenessReport,
    PropositionReview,
    PropositionVerdict,
)
from tests.certification._completeness_exam import (
    CASES,
    REQUIRED_COVERAGE,
    CompletenessCase,
    case_by_id,
    mentions,
    normalise,
    score_completeness_report,
)

KCREDIT = "C21"
"""The exact v6 regression. Its id is neutral; this name exists only in the scorer's tests."""

_REGION = {"INCOMPLETE": "missing", "OVERREACH": "unsupported", "CONTRADICTORY": "contradictory"}

PASSING_FINDINGS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "C05": {"p1": ("renewal is only allowed if no other member has reserved the book",)},
    "C06": {"p1": ("borrowing is paused until the fine is paid",)},
    "C07": {"p1": ("the exception: reference books cannot be borrowed",)},
    "C08": {"p1": ("after five days the reservation lapses and passes to the next member",)},
    "C09": {"p1": ("the limit of at most five items for members under 16",)},
    "C10": {"p1": ("the claim adds that the member is suspended",)},
    "C11": {"p1": ("a cap of 15 EUR per item conflicts with the stated 10 EUR cap",)},
    "C12": {"p1": ("the follow-up by post when the email notice is unanswered for a week",)},
    "C15": {"p1": ("a damage report made later than 7 days after return is refused",)},
    "C16": {"p1": ("a reservation by a member with outstanding fines is cancelled",)},
    "C17": {"p2": ("the supported claim states 21 days, but the proposition says two weeks",)},
    "C18": {"p1": ("the loan can be extended once by phone",)},
    "C20": {"p1": ("the cap of 12 EUR per item",)},
    KCREDIT: {"p1": ("a claim made later than 48 hours after the reservation start is refused",)},
    "C22": {"p2": ("the requirement to show a photo ID",)},
    "C23": {"p1": ("returns are restricted to the issuing branch, not allowed at any branch",)},
}
"""One realistic finding per non-COMPLETE proposition. Together they are the perfect verifier."""


def _answer(
    case: CompletenessCase,
    findings: Mapping[str, tuple[str, ...]] | None = None,
    *,
    verdicts: Mapping[str, str] | None = None,
    placed: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
) -> CompletenessReport:
    """A structurally valid report: expected verdicts unless overridden; ``findings`` go in the
    region of each verdict, ``placed`` names the field explicitly."""
    expected = {e.proposition_id: e.verdict for e in case.expected}
    out = []
    for p in case.request.propositions:
        pid = p.proposition_id
        verdict = (verdicts or {}).get(pid, expected[pid])
        regions: dict[str, tuple[str, ...]] = {}
        if verdict != "COMPLETE":
            regions[_REGION[verdict]] = (findings or PASSING_FINDINGS[case.case_id]).get(
                pid, ("placeholder",)
            )
        for field, items in ((placed or {}).get(pid) or {}).items():
            regions[field] = items
        out.append(_verdict(p, verdict, regions))
    return CompletenessReport(verdicts=tuple(out))


def _verdict(
    p: PropositionReview, verdict: str, regions: Mapping[str, tuple[str, ...]]
) -> PropositionVerdict:
    return PropositionVerdict(
        proposition_id=p.proposition_id,
        verdict=verdict,  # type: ignore[arg-type]
        claim_refs=tuple(c.ref for c in p.claims),
        missing=regions.get("missing", ()),
        unsupported=regions.get("unsupported", ()),
        contradictory=regions.get("contradictory", ()),
    )


def _passes(case_id: str, pid: str, *items: str, verdict: str | None = None) -> bool:
    case = case_by_id(case_id)
    report = _answer(case, {pid: items}, verdicts={pid: verdict} if verdict else None)
    return score_completeness_report(case, report) == ()


# --- the matcher ------------------------------------------------------------------------------


def test_normalise_folds_case_punctuation_and_whitespace() -> None:
    assert normalise("  A Claim, made LATER -- is\n refused! ") == "a claim made later is refused"
    assert normalise("the member's 48-hour window") == "the members 48 hour window"


def test_matching_is_on_whole_word_and_phrase_boundaries_without_stemming() -> None:
    assert mentions("Late claims are refused.", "late")
    assert mentions("it is NOT  accepted", "not accepted")
    assert mentions("claims after 48 hours", "48 hours")
    assert not mentions("an unrelated claim", "late"), "no naive substring"
    assert not mentions("sent by email", "mail"), "no naive substring"
    assert not mentions("claims after 148 hours", "48 hours"), "numbers are whole tokens"
    assert not mentions("they refuse it", "refused"), "no stemming"
    assert not mentions("cannot", "not"), "a word is not its own suffix"


# --- the corpus -------------------------------------------------------------------------------


def test_the_exam_covers_every_required_category_with_a_sensible_balance() -> None:
    covered = {c.category for c in CASES}
    assert covered >= set(REQUIRED_COVERAGE), set(REQUIRED_COVERAGE) - covered
    verdicts = [e.verdict for c in CASES for e in c.expected]
    assert set(verdicts) == {"COMPLETE", "INCOMPLETE", "OVERREACH", "CONTRADICTORY"}
    complete = verdicts.count("COMPLETE")
    assert complete >= 10 and complete * 2 >= len(verdicts) - complete, "both directions"
    dispositions = {p.disposition for c in CASES for p in c.request.propositions}
    assert dispositions == {"ASSERT", "SUPPORT", "ASSERT_SUPERSEDE"}
    for disposition in dispositions:
        verdicts_seen = {
            e.verdict
            for c in CASES
            for p, e in zip(c.request.propositions, c.expected, strict=True)
            if p.disposition == disposition
        }
        assert "COMPLETE" in verdicts_seen and len(verdicts_seen) > 1, disposition
    decomposed = [
        p
        for c in CASES
        for p, e in zip(c.request.propositions, c.expected, strict=True)
        if e.verdict == "COMPLETE" and len(p.claims) > 1
    ]
    assert len(decomposed) >= 3, "several claims can jointly be COMPLETE"


def test_every_case_is_valid_and_every_non_complete_expectation_seals_a_finding() -> None:
    ids = [c.case_id for c in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        assert [e.proposition_id for e in case.expected] == [
            p.proposition_id for p in case.request.propositions
        ], case.case_id
        for e in case.expected:
            if e.verdict == "COMPLETE":
                assert not e.groups and not e.forbidden and e.finding is None, case.case_id
            else:
                assert e.finding and e.groups, case.case_id
                for group in e.groups:
                    assert group.markers, (case.case_id, group.name)
                    for phrase in (*group.markers, *group.synonyms):
                        assert normalise(phrase) == phrase, (case.case_id, phrase)


def test_the_regression_is_the_exact_recorded_v6_shape() -> None:
    (p,) = case_by_id(KCREDIT).request.propositions
    assert p.statement == (
        "The service credit for an unavailable vehicle must be claimed in the app within 48 "
        "hours after the reservation start, and a later claim is refused."
    )
    assert p.source_sentences == (
        "The service credit for an unavailable vehicle must be claimed in the app within 48 "
        "hours after the reservation start.",
        "A claim made later is refused.",
    )
    assert p.disposition == "ASSERT"
    assert [(c.role, c.subject, c.predicate, c.value) for c in p.claims] == [
        (
            "ASSERTED",
            "Service credit for an unavailable reserved vehicle",
            "claim_deadline_after_reservation_start",
            "48 hours",
        )
    ]
    (e,) = case_by_id(KCREDIT).expected
    assert e.verdict == "INCOMPLETE"
    groups = {g.name: set(g.markers) for g in e.groups}
    assert groups == {
        "lateness": {"later", "late", "after", "beyond", "past", "48 hours", "deadline"},
        "refusal": {
            "refused",
            "rejected",
            "denied",
            "not accepted",
            "cannot be accepted",
            "ineligible",
        },
    }


def test_complete_propositions_are_scored_by_verdict_alone() -> None:
    for case in CASES:
        if all(e.verdict == "COMPLETE" for e in case.expected):
            assert score_completeness_report(case, _answer(case)) == (), case.case_id


# --- 13.1-13.14 and section 3: the finding scorer ---------------------------------------------


def test_1_exact_correct_findings_pass_on_every_case() -> None:
    for case in CASES:
        assert score_completeness_report(case, _answer(case)) == (), case.case_id


@pytest.mark.parametrize(
    ("case_id", "pid", "finding"),
    [
        (KCREDIT, "p1", "claims submitted beyond the deadline are rejected"),
        (KCREDIT, "p1", "a late claim is not accepted"),
        (KCREDIT, "p1", "past 48 hours the claim cannot be accepted"),
        ("C15", "p1", "late reports are denied"),
        ("C06", "p1", "the member is blocked from borrowing until payment"),
        ("C16", "p1", "such a reservation is voided"),
        ("C12", "p1", "a postal reminder follows"),
        ("C23", "p1", "returns are limited to the same branch"),
    ],
)
def test_2_a_synonym_finding_passes(case_id: str, pid: str, finding: str) -> None:
    assert _passes(case_id, pid, finding)


@pytest.mark.parametrize(
    ("case_id", "pid", "finding"),
    [
        (
            KCREDIT,
            "p1",
            "The consequence of missing the 48-hour window is absent: such a credit request "
            "is denied.",
        ),
        (
            KCREDIT,
            "p1",
            "Missing: what happens to a claim made after the 48 hours have passed, namely that "
            "the app refuses it, i.e. the claim is refused.",
        ),
        ("C07", "p1", "Reference books are excluded from lending altogether."),
        ("C09", "p1", "It does not say that juniors may borrow up to 5 books."),
    ],
)
def test_3_a_paraphrased_finding_passes(case_id: str, pid: str, finding: str) -> None:
    assert _passes(case_id, pid, finding)


@pytest.mark.parametrize(
    ("case_id", "pid", "finding"),
    [
        (KCREDIT, "p1", "a consequence is missing"),
        ("C05", "p1", "incomplete"),
        ("C05", "p1", "a condition is not captured by the claims"),
        ("C06", "p1", "the consequence is missing"),
        ("C10", "p1", "the claim goes beyond the proposition"),
        ("C11", "p1", "the claims contradict each other"),
        ("C07", "p1", "an exception is missing"),
    ],
)
def test_4_a_correct_verdict_with_a_vague_finding_fails(
    case_id: str, pid: str, finding: str
) -> None:
    assert not _passes(case_id, pid, finding)


@pytest.mark.parametrize(
    ("case_id", "pid", "finding"),
    [
        ("C06", "p1", "the fine amount of 0.20 EUR per day"),
        (KCREDIT, "p1", "the claim must name the reservation and include a photo"),
        (KCREDIT, "p1", "the claim must be made in the app"),
        ("C07", "p1", "the loan period of three weeks"),
        ("C09", "p1", "the guardian must sign"),
        ("C16", "p1", "only members without fines may reserve"),
    ],
)
def test_5_a_correct_verdict_naming_the_wrong_fact_fails(
    case_id: str, pid: str, finding: str
) -> None:
    assert not _passes(case_id, pid, finding)


@pytest.mark.parametrize(
    ("case_id", "pid", "finding"),
    [
        (KCREDIT, "p1", "claims made after 48 hours"),
        (KCREDIT, "p1", "the refusal"),
        ("C07", "p1", "reference books"),
        ("C15", "p1", "a report made later than 7 days"),
        ("C09", "p1", "the number five"),
    ],
)
def test_6_half_of_the_required_meaning_fails(case_id: str, pid: str, finding: str) -> None:
    assert not _passes(case_id, pid, finding)


def test_7_keyword_bait_in_an_unrelated_phrase_fails() -> None:
    kc = case_by_id(KCREDIT)
    assert not _passes(KCREDIT, "p1", "a claim for an unrelated reservation is refused")
    # the two meanings in two different findings: neither identifies the region
    assert not _passes(KCREDIT, "p1", "late claims", "a claim without a photo is refused")
    # the right words in the wrong region field
    wrong_field = _answer(
        kc,
        {"p1": ("the in-app channel",)},
        placed={"p1": {"unsupported": ("a claim made later is refused",)}},
    )
    assert score_completeness_report(kc, wrong_field) != ()
    # keyword stuffing: every marker listed, nothing identified
    assert not _passes(
        KCREDIT, "p1", "late later after beyond past deadline refused rejected denied"
    )
    assert not _passes(
        KCREDIT,
        "p1",
        "late, later, after, beyond, past the deadline, and refused, rejected, denied",
    )


def test_8_the_unsupported_addition_correctly_identified_passes() -> None:
    assert _passes("C10", "p1", "the claim adds that the member is suspended")
    assert _passes("C10", "p1", "a suspension of the member")
    assert _passes("C22", "p2", "only with a valid photo ID")


def test_9_the_wrong_unsupported_addition_fails() -> None:
    assert not _passes("C10", "p1", "the 7-day period")
    assert not _passes("C10", "p1", "the damage report is refused")
    assert not _passes("C22", "p2", "the limit of ten items")


def test_10_the_contradiction_correctly_identified_passes() -> None:
    assert _passes("C11", "p1", "the second claim caps the fine at fifteen EUR")
    assert _passes("C23", "p1", "returns only at the issuing branch")
    assert _passes("C17", "p2", "the existing claim says 21 days, not a fortnight")


def test_11_a_contradiction_label_with_vague_text_fails() -> None:
    assert not _passes("C11", "p1", "the claims conflict")
    assert not _passes("C23", "p1", "the claim conflicts with the proposition")
    assert not _passes("C17", "p2", "the supported claim disagrees with the proposition")


def test_12_the_regression_naming_48_hours_but_not_refusal_fails() -> None:
    assert not _passes(KCREDIT, "p1", "the 48-hour deadline is missing")
    assert not _passes(KCREDIT, "p1", "claims must be made within 48 hours")
    # a forbidden interpretation fails even beside a correct finding
    assert not _passes(KCREDIT, "p1", "the 48-hour deadline is missing", "a later claim is refused")


def test_13_the_regression_naming_refusal_without_lateness_fails() -> None:
    assert not _passes(KCREDIT, "p1", "claims are refused")
    assert not _passes(KCREDIT, "p1", "a claim without a photo is refused")


def test_14_the_regression_identifying_both_passes() -> None:
    assert _passes(KCREDIT, "p1", "a claim made after the 48 hours is refused")
    assert _passes(KCREDIT, "p1", "late claims are rejected")


def test_the_verdict_itself_must_be_right() -> None:
    kc = case_by_id(KCREDIT)
    assert not _passes(KCREDIT, "p1", "a later claim is refused", verdict="OVERREACH")
    assert not _passes(KCREDIT, "p1", "a later claim is refused", verdict="CONTRADICTORY")
    assert score_completeness_report(kc, _answer(kc, verdicts={"p1": "COMPLETE"})) != ()
    decomposition = case_by_id("C03")
    assert (
        score_completeness_report(
            decomposition,
            _answer(decomposition, {"p1": ("the card",)}, verdicts={"p1": "INCOMPLETE"}),
        )
        != ()
    )


def test_an_invalid_or_absent_report_fails() -> None:
    kc = case_by_id(KCREDIT)
    assert score_completeness_report(kc, None) != ()
    assert score_completeness_report(kc, CompletenessReport(verdicts=())) != ()


def test_a_finding_that_restates_the_whole_proposition_names_no_region() -> None:
    for case_id in ("C05", "C06", KCREDIT):
        (p,) = case_by_id(case_id).request.propositions
        assert not _passes(case_id, "p1", p.statement), case_id
        assert not _passes(case_id, "p1", f"Missing: {p.statement.upper()}"), case_id
    # quoting only the omitted source sentence is a precise finding, not an echo
    assert _passes(KCREDIT, "p1", "A claim made later is refused.")
