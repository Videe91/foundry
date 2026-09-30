"""Sealed-ready certification exam for the IE2 semantic completeness verifier (offline only).

Every case is one ``CompletenessRequest`` (exactly what a verifier is shown in production) and a
hidden expected verdict per proposition. A verifier is ``CERTIFIED`` only if, on every case, its
report is valid (every proposition judged once, on exactly its own claims) and every verdict
equals the expected one. All-or-nothing.

The cases are a held-out library domain (never seen by any IE2 validation) plus one named
regression, the recorded v6 ``K-CREDIT-4`` loss. They examine both directions: a verifier must
accept paraphrase and faithful decomposition (by the union of claims) as ``COMPLETE``, and
catch a missing condition, consequence, exception, second sentence or clause, an unsupported
addition, a contradiction, misleading lexical overlap, a deadline mistaken for its refusal, an
eligibility rule mistaken for its consequence, and the same laws under SUPPORT and
ASSERT + SUPERSEDE dispositions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Final, Literal

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    CompletenessVerdict,
    PropositionReview,
    ReviewedClaim,
    report_findings,
)

__all__ = [
    "CASES",
    "CATEGORIES",
    "CERTIFIED",
    "EXAM_VERSION",
    "NOT_CERTIFIED",
    "ExamCase",
    "ExamResult",
    "exam_sha256",
    "score",
]

EXAM_VERSION: Final = "ie2-semantic-completeness-exam-v1"
CERTIFIED: Final = "SEMANTIC_COMPLETENESS_VERIFIER_CERTIFIED"
NOT_CERTIFIED: Final = "SEMANTIC_COMPLETENESS_VERIFIER_NOT_CERTIFIED"

Category = Literal[
    "COMPLETE_PARAPHRASE",
    "FAITHFUL_DECOMPOSITION",
    "JOINTLY_COMPLETE_THREE_CLAIMS",
    "MISSING_CONDITION",
    "MISSING_CONSEQUENCE",
    "MISSING_EXCEPTION",
    "MISSING_SECOND_SENTENCE",
    "MISSING_CLAUSE",
    "UNSUPPORTED_ADDITION",
    "CONTRADICTION",
    "LEXICAL_OVERLAP",
    "DEADLINE_VS_REFUSAL",
    "ELIGIBILITY_VS_CONSEQUENCE",
    "SUPPORT_DISPOSITION",
    "CORRECTION_DISPOSITION",
]
CATEGORIES: Final[tuple[str, ...]] = Category.__args__  # type: ignore[attr-defined]


class ExamCase(FrozenModel):
    id: str
    category: Category
    request: CompletenessRequest
    expected: tuple[tuple[str, CompletenessVerdict], ...]


class ExamResult(FrozenModel):
    standing: str
    failures: tuple[str, ...]


def _c(
    ref: str,
    predicate: str,
    value: str,
    role: Literal["ASSERTED", "SUPPORTED", "RETIRED"] = "ASSERTED",
) -> ReviewedClaim:
    return ReviewedClaim(
        ref=ref, role=role, subject="Library loans", predicate=predicate, value=value
    )


def _p(
    pid: str,
    statement: str,
    claims: tuple[ReviewedClaim, ...],
    *,
    sentences: tuple[str, ...] | None = None,
    retired: tuple[ReviewedClaim, ...] = (),
) -> PropositionReview:
    support = all(c.role == "SUPPORTED" for c in claims)
    return PropositionReview(
        proposition_id=pid,
        statement=statement,
        source_sentences=sentences or (statement,),
        disposition="SUPPORT" if support else ("ASSERT_SUPERSEDE" if retired else "ASSERT"),
        claims=claims,
        retired=retired,
    )


def _case(
    cid: str, category: Category, *props: tuple[PropositionReview, CompletenessVerdict]
) -> ExamCase:
    return ExamCase(
        id=cid,
        category=category,
        request=CompletenessRequest(
            project_id="PROJ-EXAM",
            subject_invocation_id=f"INV-{cid}",
            propositions=tuple(p for p, _ in props),
        ),
        expected=tuple((p.proposition_id, v) for p, v in props),
    )


_RENEW = "A member may renew a loan twice, online, if nobody else has reserved the book."

CASES: Final[tuple[ExamCase, ...]] = (
    _case("E01", "COMPLETE_PARAPHRASE", (
        _p("a", "A book may be borrowed for three weeks.", (_c("c1", "loan_period", "21 days"),)),
        "COMPLETE")),
    _case("E02", "FAITHFUL_DECOMPOSITION", (
        _p("a", "A loan is made at the issue desk and is recorded on the member's card.",
           (_c("c1", "loan_channel", "the issue desk"),
            _c("c2", "loan_record", "recorded on the member's card"))),
        "COMPLETE")),
    _case("E03", "JOINTLY_COMPLETE_THREE_CLAIMS", (
        _p("a", _RENEW, (_c("c1", "maximum_renewals", "2"), _c("c2", "renewal_channel", "online"),
                         _c("c3", "renewal_condition", "no other member has reserved the book"))),
        "COMPLETE")),
    _case("E04", "MISSING_CONDITION", (
        _p("a", _RENEW, (_c("c1", "maximum_renewals", "2"), _c("c2", "renewal_channel", "online"))),
        "INCOMPLETE")),
    _case("E05", "MISSING_CONSEQUENCE", (
        _p("a", "A book returned late is charged 0.20 EUR per day, and borrowing is paused until "
           "the fine is paid.", (_c("c1", "late_fine", "0.20 EUR per day"),)),
        "INCOMPLETE")),
    _case("E06", "MISSING_EXCEPTION", (
        _p("a", "Loans last three weeks, except reference books, which cannot be borrowed.",
           (_c("c1", "loan_period", "3 weeks"),)),
        "INCOMPLETE")),
    _case("E07", "MISSING_SECOND_SENTENCE", (
        _p("a", "A reserved book is held for five days, and after that the reservation lapses and "
           "passes to the next member.",
           (_c("c1", "reservation_hold", "5 days"),),
           sentences=("A reserved book is held for five days.",
                      "After that the reservation lapses and passes to the next member.")),
        "INCOMPLETE")),
    _case("E08", "MISSING_CLAUSE", (
        _p("a", "Members under 16 need a guardian's signature and may borrow at most five items.",
           (_c("c1", "junior_membership_signature", "a guardian's signature"),)),
        "INCOMPLETE")),
    _case("E09", "UNSUPPORTED_ADDITION", (
        _p("a", "A damage report made more than 7 days after return is refused.",
           (_c("c1", "late_damage_report", "refused after 7 days, and the member is suspended"),)),
        "OVERREACH")),
    _case("E10", "CONTRADICTION", (
        _p("a", "The late fine is capped at 10 EUR per item.",
           (_c("c1", "fine_cap", "10 EUR per item"), _c("c2", "fine_cap_per_item", "15 EUR"))),
        "CONTRADICTORY")),
    _case("E11", "LEXICAL_OVERLAP", (
        _p("a", "Fines are waived for members over 65.",
           (_c("c1", "fines_for_members_over_65", "fines are charged to members over 65"),)),
        "CONTRADICTORY"),
        (_p("b", "A book may be returned to any branch of the library.",
            (_c("c2", "return_branch", "the branch that issued the loan"),)),
         "CONTRADICTORY")),
    _case("E12", "DEADLINE_VS_REFUSAL", (
        _p("a", "A damage report must be made within 7 days of return, and a later report is "
           "refused.", (_c("c1", "damage_report_deadline", "7 days"),),
           sentences=("A damage report must be made within 7 days of return.",
                      "A later report is refused.")),
        "INCOMPLETE")),
    _case("E12-K-CREDIT", "DEADLINE_VS_REFUSAL", (
        _p("p13", "The service credit for an unavailable vehicle must be claimed in the app within "
           "48 hours after the reservation start, and a later claim is refused.",
           (_c("JDG-p13", "claim_deadline_after_reservation_start", "48 hours"),),
           sentences=("The service credit for an unavailable vehicle must be claimed in the app "
                      "within 48 hours after the reservation start.",
                      "A claim made later is refused.")),
        "INCOMPLETE")),
    _case("E13", "ELIGIBILITY_VS_CONSEQUENCE", (
        _p("a", "Only members with no outstanding fines may reserve a book, and a reservation by a "
           "member with fines is cancelled.",
           (_c("c1", "reservation_eligibility", "no outstanding fines"),)),
        "INCOMPLETE")),
    _case("E14", "SUPPORT_DISPOSITION", (
        _p("a", "A loan lasts three weeks.", (_c("L1", "loan_period", "21 days", "SUPPORTED"),)),
        "COMPLETE"),
        (_p("b", "A loan lasts two weeks.", (_c("L1", "loan_period", "21 days", "SUPPORTED"),)),
         "CONTRADICTORY")),
    _case("E15", "CORRECTION_DISPOSITION", (
        _p("a", "The late fine is now 0.30 EUR per day.",
           (_c("c1", "late_fine", "0.30 EUR per day"),),
           retired=(_c("F1", "late_fine", "0.20 EUR per day", "RETIRED"),)),
        "COMPLETE"),
        (_p("b", "The late fine is 0.30 EUR per day and is capped at 12 EUR per item.",
            (_c("c2", "late_fine_rate", "0.30 EUR per day"),),
            retired=(_c("F2", "late_fine_old", "0.20 EUR per day", "RETIRED"),)),
         "INCOMPLETE")),
    _case("E16", "COMPLETE_PARAPHRASE", (
        _p("a", "A member may hold at most four reservations at once.",
           (_c("c1", "maximum_active_reservations", "4"),)),
        "COMPLETE")),
    _case("E17", "LEXICAL_OVERLAP", (
        _p("a", "Children's books can be kept for a fortnight.",
           (_c("c1", "childrens_book_loan_period", "14 days"),)),
        "COMPLETE")),
)  # fmt: skip


def score(verify: Callable[[CompletenessRequest], CompletenessReport | None]) -> ExamResult:
    failures: list[str] = []
    for case in CASES:
        report = verify(case.request)
        if report is None:
            failures.append(f"{case.category}: {case.id}: no report")
            continue
        problems = report_findings(case.request, report)
        if problems:
            failures.append(f"{case.category}: {case.id}: {'; '.join(problems)}")
            continue
        got = {v.proposition_id: v.verdict for v in report.verdicts}
        for pid, want in case.expected:
            if got[pid] != want:
                failures.append(f"{case.category}: {case.id}/{pid}: {got[pid]} (expected {want})")
    return ExamResult(standing=NOT_CERTIFIED if failures else CERTIFIED, failures=tuple(failures))


def exam_sha256() -> str:
    document = {
        "exam_version": EXAM_VERSION,
        "cases": [c.model_dump(mode="json") for c in CASES],
    }
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
