"""Exam v3's scorer: v2's finding law, generalised to every sealed assertion (offline).

A non-COMPLETE proposition passes only with the right verdict AND, for every assertion its
inventory seals in that verdict's region, a finding item that identifies it (every marker group
of that assertion, not keyword stuffing, not an echo of the proposition). Several items may
jointly cover the inventory; one item that states two sealed assertions covers both. A COMPLETE
proposition is judged by its verdict alone and the number of claims never matters.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from foundry.domain.semantic_completeness import (
    CompletenessReport,
    PropositionReview,
    PropositionVerdict,
)
from tests.certification._completeness_exam_v3 import (
    CASES,
    InventoryCase,
    case_by_id,
    score_completeness_report,
)

KCREDIT = "C21"
_REGION = {"INCOMPLETE": "missing", "OVERREACH": "unsupported", "CONTRADICTORY": "contradictory"}

PASSING_FINDINGS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "C05": {"p1": ("only a member may renew a loan",
                   "renewal is only allowed if nobody else has reserved the book")},
    "C06": {"p1": ("borrowing is paused until the fine is paid",)},
    "C07": {"p1": ("the exception: reference books cannot be borrowed",)},
    "C08": {"p1": ("after five days the reservation lapses and passes to the next member",)},
    "C09": {"p1": ("the limit of at most five items", "the rule applies to members under 16")},
    "C10": {"p1": ("the claim adds that the member is suspended",)},
    "C11": {"p1": ("a cap of 15 EUR per item conflicts with the stated 10 EUR cap",)},
    "C12": {"p1": ("the follow-up by post when the email notice is unanswered for a week",)},
    "C15": {"p1": ("the 7 days are counted from return",
                   "a report made after that deadline is refused")},
    "C16": {"p1": ("only members may reserve a book",
                   "a reservation by a member with outstanding fines is cancelled")},
    "C17": {"p2": ("the supported claim states 21 days, but the proposition says two weeks",)},
    "C18": {"p1": ("the loan can be extended once by phone",)},
    "C20": {"p1": ("the cap of 12 EUR per item",)},
    KCREDIT: {"p1": ("the claim must be made in the app",
                     "a claim made later than 48 hours after the reservation start is refused")},
    "C22": {"p2": ("the requirement to show a photo ID",)},
    "C23": {"p1": ("returns are restricted to the issuing branch, not allowed at any branch",)},
}  # fmt: skip
"""Realistic findings covering every sealed assertion of every non-COMPLETE proposition:
together they are the perfect verifier."""


def _answer(
    case: InventoryCase,
    findings: Mapping[str, tuple[str, ...]] | None = None,
    *,
    verdicts: Mapping[str, str] | None = None,
    placed: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
) -> CompletenessReport:
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


def _reasons(case_id: str, *items: str) -> tuple[str, ...]:
    case = case_by_id(case_id)
    return score_completeness_report(case, _answer(case, {"p1": items}))


# --- the perfect verifier and COMPLETE propositions ---------------------------------------------


def test_the_passing_findings_cover_exactly_the_non_complete_propositions() -> None:
    non_complete = {
        (c.case_id, e.proposition_id) for c in CASES for e in c.expected if e.verdict != "COMPLETE"
    }
    assert {(c, p) for c, ps in PASSING_FINDINGS.items() for p in ps} == non_complete


def test_correct_findings_pass_on_every_case() -> None:
    for case in CASES:
        assert score_completeness_report(case, _answer(case)) == (), case.case_id


def test_complete_propositions_are_scored_by_verdict_alone() -> None:
    for case in CASES:
        if all(e.verdict == "COMPLETE" for e in case.expected):
            assert score_completeness_report(case, _answer(case)) == (), case.case_id


@pytest.mark.parametrize("case_id", ["C02", "C04", "C24"])
def test_a_faithful_explicit_actor_case_rejected_for_its_actor_fails(case_id: str) -> None:
    """The corrected cases now deserve COMPLETE; a verifier calling them INCOMPLETE fails."""
    case = case_by_id(case_id)
    report = _answer(
        case, {"p1": ("members are the actors of this rule",)}, verdicts={"p1": "INCOMPLETE"}
    )
    assert score_completeness_report(case, report) != ()


def test_a_faithful_condition_and_consequence_decomposition_must_be_complete() -> None:
    for case_id in ("C24", "C25"):
        case = case_by_id(case_id)
        assert score_completeness_report(case, _answer(case)) == ()
        wrong = _answer(case, {"p1": ("the second claim",)}, verdicts={"p1": "INCOMPLETE"})
        assert score_completeness_report(case, wrong) != (), case_id


# --- every sealed missing assertion must be found -----------------------------------------------


@pytest.mark.parametrize(
    ("case_id", "only_one_gap", "kind"),
    [
        ("C05", "renewal is only allowed if nobody else has reserved the book", "ACTOR"),
        ("C05", "only a member may renew a loan", "CONDITION"),
        ("C09", "the limit of at most five items", "ELIGIBILITY"),
        ("C09", "the rule applies to members under 16", "QUANTITY"),
        ("C15", "a report made after that deadline is refused", "TIME_ANCHOR"),
        ("C15", "the 7 days are counted from return", "CONSEQUENCE"),
        ("C16", "a reservation by a member with outstanding fines is cancelled", "ACTOR"),
        ("C16", "only members may reserve a book", "CONSEQUENCE"),
        (KCREDIT, "a claim made later than 48 hours after the start is refused", "CHANNEL"),
        (KCREDIT, "the claim must be made in the app", "CONSEQUENCE"),
    ],
)
def test_naming_only_one_gap_of_a_multi_gap_proposition_fails(
    case_id: str, only_one_gap: str, kind: str
) -> None:
    reasons = _reasons(case_id, only_one_gap)
    assert len(reasons) == 1 and f"sealed {kind}" in reasons[0], reasons


def test_several_items_jointly_cover_the_inventory_in_any_order() -> None:
    for case_id in ("C05", "C09", "C15", "C16", KCREDIT):
        items = PASSING_FINDINGS[case_id]["p1"]
        assert _passes(case_id, "p1", *items), case_id
        assert _passes(case_id, "p1", *reversed(items)), case_id
        assert _passes(case_id, "p1", "an unrelated remark", *items), case_id


def test_one_item_stating_two_sealed_assertions_covers_both() -> None:
    assert _passes("C05", "p1", "a member may renew only if nobody else has reserved the book")
    assert _passes("C09", "p1", "members under 16 may borrow at most five items")
    assert _passes("C15", "p1", "a report made more than 7 days after return is refused")
    assert _passes("C16", "p1", "only members may reserve, and a reservation by a member with "
                   "fines is cancelled")  # fmt: skip


def test_an_actor_word_inside_another_finding_does_not_identify_the_actor() -> None:
    """ "no other member has reserved" names the condition, not who may renew."""
    assert not _passes("C05", "p1", "renewal requires that no other member has reserved it")
    assert not _passes("C16", "p1", "a reservation by a member with fines is cancelled")


def test_an_actor_omission_is_detected_only_with_the_actor_and_its_role() -> None:
    for finding in ("the renewing member is not stated", "who may renew: a member",
                    "it omits that a member is the actor"):  # fmt: skip
        assert _passes("C05", "p1", finding, "nobody else may have reserved the book"), finding
    for finding in ("the member", "renewal", "the actor is unclear"):
        assert not _passes("C05", "p1", finding, "nobody else may have reserved the book")


def test_a_time_anchor_omission_is_detected() -> None:
    refusal = "a later report is refused"
    for finding in ("the 7 days run from return", "measured from the date of return"):
        assert _passes("C15", "p1", finding, refusal), finding
    assert not _passes("C15", "p1", "the 7 days are counted", refusal)


def test_keyword_stuffing_a_new_group_identifies_nothing() -> None:
    assert not _passes(
        "C05", "p1", "member may renew can renew allowed to renew actor",
        "nobody else has reserved the book",
    )  # fmt: skip


def test_a_gap_named_in_the_wrong_region_field_is_not_a_finding() -> None:
    case = case_by_id("C05")
    report = _answer(
        case,
        {"p1": ("nobody else has reserved the book",)},
        placed={"p1": {"unsupported": ("only a member may renew a loan",)}},
    )
    assert score_completeness_report(case, report) != ()


# --- overreach is distinguished from incomplete + overreach -----------------------------------


def test_corrected_c10_is_pure_overreach() -> None:
    assert _passes("C10", "p1", "the claim adds that the member is suspended")
    assert _passes("C10", "p1", "a suspension of the member")
    assert not _passes("C10", "p1", "the 7-day period")
    assert not _passes("C10", "p1", "the claim goes beyond the proposition")
    assert not _passes("C10", "p1", "the anchor after return is missing", verdict="INCOMPLETE"), (
        "nothing is missing from the corrected claim"
    )


def test_c22_p2_is_pure_overreach() -> None:
    assert _passes("C22", "p2", "only with a valid photo ID")
    assert not _passes("C22", "p2", "the limit of ten items")
    assert not _passes("C22", "p2", "the member actor is missing", verdict="INCOMPLETE")


# --- the v2 finding law is unchanged -----------------------------------------------------------


def test_k_credit_still_needs_lateness_with_refusal_and_refuses_the_deadline_misread() -> None:
    app = "the claim must be made in the app"
    assert _passes(KCREDIT, "p1", app, "late claims are rejected")
    assert not _passes(KCREDIT, "p1", app, "claims are refused"), "refusal without lateness"
    assert not _passes(KCREDIT, "p1", app, "claims after 48 hours"), "lateness without refusal"
    assert not _passes(KCREDIT, "p1", app, "the 48-hour deadline is missing")
    assert not _passes(
        KCREDIT, "p1", app, "the 48-hour deadline is missing", "a later claim is refused"
    ), "a forbidden interpretation fails beside a correct finding"
    assert not _passes(KCREDIT, "p1", app, "a claim for an unrelated reservation is refused")


def test_a_finding_that_restates_the_whole_proposition_names_no_region() -> None:
    for case_id in ("C05", "C06", KCREDIT):
        (p,) = case_by_id(case_id).request.propositions
        assert not _passes(case_id, "p1", p.statement), case_id


def test_contradictions_still_need_the_conflicting_value() -> None:
    assert _passes("C11", "p1", "the second claim caps the fine at fifteen EUR")
    assert not _passes("C11", "p1", "the claims conflict")
    assert not _passes("C23", "p1", "the claim conflicts with the proposition")


def test_the_verdict_itself_must_be_right() -> None:
    kc = case_by_id(KCREDIT)
    assert score_completeness_report(kc, _answer(kc, verdicts={"p1": "COMPLETE"})) != ()
    assert not _passes(KCREDIT, "p1", *PASSING_FINDINGS[KCREDIT]["p1"], verdict="OVERREACH")
    assert score_completeness_report(kc, None) != ()
    assert score_completeness_report(kc, CompletenessReport(verdicts=())) != ()
