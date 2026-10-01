"""Exam v5: two certification-scorer corrections, nothing else.

Exam v4 (live, NOT CERTIFIED 72/75, frozen) rejected three correct Astra answers:

* C05 attempts 2 and 3, "A/The member is the actor permitted to renew the loan.": the role
  triple ACTOR -> ROLE -> GOVERNED ACTION was there, but v4's constructions did not admit an
  appositive role noun between the copula and the licence;
* C17 attempt 1, "The proposition states a loan lasts two weeks (14 days), but CLM-1 states 21
  days.": v2's echo rule refused every item that contains the whole proposition.

v5 keeps the role-binding law and admits ``{actor} is/are [the] {role noun} {licence} to
{action}``; and replaces the echo rule: the proposition text is discounted, and what remains
must still identify the sealed region on its own. A contradiction must also name the claim's
conflicting side. Every v4 request, inventory and marker group is carried unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

import tests.certification._completeness_exam_v4 as v4
from foundry.domain.semantic_completeness import CompletenessReport, PropositionVerdict
from tests.certification._completeness_exam import render_request
from tests.certification._completeness_exam_v5 import (
    CASES,
    CLAIM_SIDES,
    RENEWER_ROLE,
    RESERVER_ROLE,
    OperativeAssertion,
    case_by_id,
    identifies_actor,
    score_completeness_report,
)
from tests.certification.test_semantic_completeness_exam_v3 import PASSING_FINDINGS

C05 = case_by_id("C05").request.propositions[0].statement
C16 = case_by_id("C16").request.propositions[0].statement
CONDITION = "Renewal is conditional on nobody else having reserved the book."
CANCELLED = "A reservation by a member with outstanding fines is cancelled."
_REGION = {"INCOMPLETE": "missing", "OVERREACH": "unsupported", "CONTRADICTORY": "contradictory"}


def _report(case_id: str, pid: str, items: tuple[str, ...]) -> CompletenessReport:
    case = case_by_id(case_id)
    sealed = {e.proposition_id: e.verdict for e in case.expected}
    out = []
    for p in case.request.propositions:
        verdict = sealed[p.proposition_id]
        found = (
            items
            if p.proposition_id == pid
            else PASSING_FINDINGS.get(case_id, {}).get(p.proposition_id, ())
        )
        out.append(
            PropositionVerdict(
                proposition_id=p.proposition_id,
                verdict=verdict,
                claim_refs=tuple(c.ref for c in p.claims),
                **({} if verdict == "COMPLETE" else {_REGION[verdict]: found}),
            )
        )
    return CompletenessReport(verdicts=tuple(out))


def _passes(case_id: str, *items: str, pid: str = "p1") -> bool:
    return score_completeness_report(case_by_id(case_id), _report(case_id, pid, items)) == ()


# --- v4 carried byte for byte -------------------------------------------------------------------


def test_every_model_visible_request_is_v4_byte_for_byte() -> None:
    assert [c.case_id for c in CASES] == [c.case_id for c in v4.CASES]
    for new, old in zip(CASES, v4.CASES, strict=True):
        assert render_request(new.request) == render_request(old.request), new.case_id


def test_every_inventory_and_marker_group_is_v4s_plus_the_claim_side_of_a_contradiction() -> None:
    for new, old in zip(CASES, v4.CASES, strict=True):
        for ni, oi in zip(new.inventory, old.inventory, strict=True):
            assert ni.forbidden == oi.forbidden
            for na, oa in zip(ni.assertions, oi.assertions, strict=True):
                assert isinstance(na, OperativeAssertion) and isinstance(oa, v4.OperativeAssertion)
                assert (na.kind, na.status, na.stated, na.claimed, na.by, na.role) == (
                    oa.kind, oa.status, oa.stated, oa.claimed, oa.by, oa.role,
                )  # fmt: skip
                assert all(g is h for g, h in zip(na.groups, oa.groups, strict=True))
                key = (new.case_id, ni.proposition_id)
                assert (na.claim_side is not None) == (na.status == "CONTRADICTED"), key
                if na.claim_side is not None:
                    assert na.claim_side is CLAIM_SIDES[key]
        for ne, oe in zip(new.expected, old.expected, strict=True):
            assert (ne.verdict, ne.forbidden) == (oe.verdict, oe.forbidden)
            assert [f.name for f in ne.findings] == [f.name for f in oe.findings]


# --- the actor law: the appositive role noun ---------------------------------------------------


@pytest.mark.parametrize(
    "finding",
    [
        "A member may renew a loan.",
        "A member is permitted to renew a loan.",
        "The permission to renew a loan is granted to a member.",
        "A member is the actor permitted to renew the loan.",
        "The member is the actor permitted to renew the loan.",
        "A member is the one permitted to renew the loan.",
        "Members are the people permitted to renew the loan.",
        "Members are the ones allowed to renew.",
    ],
)
def test_the_role_triple_with_or_without_an_appositive_role_noun_passes(finding: str) -> None:
    assert identifies_actor((finding,), RENEWER_ROLE, C05)
    assert _passes("C05", finding, CONDITION)


@pytest.mark.parametrize(
    "finding",
    [
        "A member was denied renewal.",
        "A member cannot renew.",
        "Members cannot renew.",
        "Renewal affects a member.",
        "Renewal is allowed if another member has not reserved the book.",
        "renewal is only allowed if no other member has reserved the book",
        "Renewal is permitted only when the book is not reserved by another member.",
        "A member is the actor who cancelled the renewal.",
        "A member is the actor not permitted to renew.",
        "Another member is the one permitted to renew.",
        "A member is the actor.",
        "Renewal permission is not granted to a member.",
        "Renewal is checked when the loan is granted to a member.",
    ],
)
def test_every_actor_safety_rule_still_holds(finding: str) -> None:
    assert not identifies_actor((finding,), RENEWER_ROLE, C05)
    assert not _passes("C05", finding, CONDITION)


def test_a_consequence_finding_still_never_satisfies_the_reserver() -> None:
    for finding in (CANCELLED, "Reservations by a member with fines can be cancelled."):
        assert not identifies_actor((finding,), RESERVER_ROLE, C16)
        assert not _passes("C16", finding)
    assert _passes("C16", "Members are the ones permitted to make reservations.", CANCELLED)


# --- the echo law -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "finding",
    [
        "The proposition states a loan lasts two weeks (14 days), but CLM-1 states 21 days.",
        "The proposition states a loan lasts two weeks, but CLM-1 states 21 days.",
        "The claim states 21 days, conflicting with the proposition's two weeks.",
        "The proposition says 14 days, but the claim says 21 days.",
        "The claim gives 21 days instead of the proposition's 14 days.",
    ],
)
def test_a_contradiction_quoting_the_proposition_but_naming_the_claim_side_passes(
    finding: str,
) -> None:
    assert _passes("C17", finding, pid="p2")


@pytest.mark.parametrize(
    "finding",
    [
        "The proposition states a loan lasts two weeks.",
        "A loan lasts two weeks.",
        "Missing: A loan lasts two weeks.",
        "The proposition says 14 days.",
        "The proposition says a loan lasts two weeks (14 days).",
        "There is a contradiction.",
        "The proposition is incomplete.",
        "two weeks 14 days 21 days fortnight 21 14",
    ],
)
def test_an_echo_the_proposition_side_alone_or_a_bag_of_markers_fails(finding: str) -> None:
    assert not _passes("C17", finding, pid="p2")


def test_the_claim_side_is_required_for_every_contradiction() -> None:
    assert _passes("C11", "JDG-2 sets the cap at 15 EUR per item.")
    assert not _passes("C11", "The proposition caps the late fine at 10 EUR per item.")
    assert _passes("C23", "JDG-1 restricts returns to the branch that issued the loan.")
    assert not _passes("C23", "The proposition allows returns to any branch.")


def test_the_echo_law_is_generic_across_incomplete_overreach_and_contradiction() -> None:
    (c05,) = case_by_id("C05").request.propositions
    (c10,) = case_by_id("C10").request.propositions
    (c21,) = case_by_id("C21").request.propositions
    # a pure echo, with or without a prefix, identifies nothing anywhere
    assert not _passes("C05", c05.statement, f"Missing: {c05.statement.upper()}")
    assert not _passes("C10", f"The proposition says: {c10.statement}")
    assert not _passes("C21", f"The proposition says {c21.statement}")
    # an echo followed by independent defect evidence passes
    assert _passes("C10", f"{c10.statement} The claim adds that the member is suspended.")
    assert _passes(
        "C21",
        f"{c21.statement} The claims omit the app channel.",
        "A claim made later than 48 hours after the reservation start is refused.",
    )
    assert _passes("C21", "The proposition requires the app, but the claim omits the app "
                   "channel.", "Late claims are refused.")  # fmt: skip


def test_echo_discounting_never_joins_the_text_on_either_side() -> None:
    """Removing the echo must not let the words before and after it form a phrase."""
    (c05,) = case_by_id("C05").request.propositions
    assert not _passes("C05", f"A member {c05.statement} may renew.", CONDITION)


# --- all gaps -----------------------------------------------------------------------------------


def test_every_sealed_missing_assertion_is_still_required() -> None:
    assert not _passes("C05", "A member is the actor permitted to renew the loan.")
    assert not _passes("C05", CONDITION)
    app, refusal = PASSING_FINDINGS["C21"]["p1"]
    assert not _passes("C21", app) and not _passes("C21", refusal) and _passes("C21", app, refusal)
    (c21,) = case_by_id("C21").request.propositions
    assert not _passes("C21", f"The proposition says {c21.statement}", app)


def test_v4s_perfect_findings_still_pass_every_case() -> None:
    for case in CASES:
        for e in case.expected:
            if e.verdict != "COMPLETE":
                items = PASSING_FINDINGS[case.case_id][e.proposition_id]
                assert _passes(case.case_id, *items, pid=e.proposition_id), case.case_id
        if all(e.verdict == "COMPLETE" for e in case.expected):
            report = CompletenessReport(
                verdicts=tuple(
                    PropositionVerdict(
                        proposition_id=p.proposition_id,
                        verdict="COMPLETE",
                        claim_refs=tuple(c.ref for c in p.claims),
                    )
                    for p in case.request.propositions
                )
            )
            assert score_completeness_report(case, report) == ()


SAFETY: Mapping[str, tuple[str, ...]] = {
    "condition-only C05": ("renewal is only allowed if no other member has reserved the book",),
    "consequence-only C16": ("Reservations by a member with fines can be cancelled.",),
}


@pytest.mark.parametrize("name", list(SAFETY))
def test_one_gaps_finding_never_satisfies_another(name: str) -> None:
    case_id = "C05" if "C05" in name else "C16"
    reasons = score_completeness_report(case_by_id(case_id), _report(case_id, "p1", SAFETY[name]))
    assert len(reasons) == 1 and "ACTOR" in reasons[0], reasons
