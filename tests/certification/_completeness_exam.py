"""Certification exam v2 for SEMANTIC_COMPLETENESS_VERIFICATION (IE2 Call 3), test-only.

A sibling of the IE3 exams, not a parallel system: it reuses ``_certification_run``'s contestant,
failure taxonomy and guard check, and ``_exam_identity``'s code closure and canonical digest.

**Why v2 exists.** Exam v1 (``foundry.experiments.completeness_verifier_exam``, prepared, never
sat, unchanged) scored the top-level verdict only, so a verifier could be certified while
naming the wrong region, or none; its K-CREDIT case paraphrased the recorded v6 loss under an
invented subject; and no live-certification harness or certificate bound it.

**The scoring law.** For every proposition of every case the verdict must equal the sealed one.
For every non-COMPLETE proposition the finding must also identify the actual semantic region:
at least one finding item, in the region field of that verdict (``missing`` / ``unsupported``
/ ``contradictory``), must satisfy **every** mandatory marker group sealed for the case; no
finding of that proposition may state a sealed forbidden interpretation; and an item that is a
bare list of markers (keyword stuffing) identifies nothing. Matching is on normalised
whole-word / phrase boundaries (case, punctuation and whitespace folded; no stemming, no
substring). A COMPLETE proposition is judged by its verdict alone: the number of claims is
never a criterion. No model adjudicates anything.

**Model-visible material** is exactly one ``CompletenessRequest`` per case, rendered by the
production verifier. Its ids are neutral; the case id, category, expected verdict, finding
category and markers live only here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel

from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_SYSTEM_INSTRUCTION,
    ModelRuntimeCompletenessVerifier,
)
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    CompletenessVerdict,
    PropositionReview,
    PropositionVerdict,
    ReviewedClaim,
    VerifierIdentity,
    report_findings,
)
from foundry.model_runtime.domain import (
    ModelExecutionConstraints,
    ModelIdentity,
    ModelRequest,
    ModelTask,
    ModelTier,
)
from foundry.model_runtime.errors import ModelProtocolError, ModelProviderError
from foundry.model_runtime.ports import ProviderExecutionResult
from foundry.model_runtime.runtime import ModelRuntime
from tests.certification._certification_run import Contestant, classify_execution_failure
from tests.certification._exam_identity import canonical_digest, code_closure
from tests.certification._schema_identity import schema_sha256

REQUIRED_COVERAGE: Final = (
    "FAITHFUL_PARAPHRASE",
    "FAITHFUL_DECOMPOSITION",
    "JOINTLY_COMPLETE_THREE_CLAIMS",
    "MISSING_CONDITION",
    "MISSING_CONSEQUENCE",
    "MISSING_EXCEPTION",
    "MISSING_SECOND_SENTENCE",
    "MISSING_SECOND_CLAUSE",
    "UNSUPPORTED_ADDITION",
    "CONTRADICTION",
    "LEXICAL_OVERLAP_INCOMPLETE",
    "LEXICAL_OVERLAP_COMPLETE",
    "DEADLINE_VS_REFUSAL",
    "ELIGIBILITY_VS_CONSEQUENCE",
    "SUPPORT_DISPOSITION",
    "ASSERT_DISPOSITION",
    "ASSERT_SUPERSEDE_DISPOSITION",
    "K_CREDIT_REGRESSION",
)

PROJECT: Final = "PROJ-A"

COMPLETENESS_EXAM_ID: Final = "ie2.semantic-completeness-verification.certification-exam"
COMPLETENESS_EXAM_VERSION: Final = "ie2-semantic-completeness-exam-v2"
COMPLETENESS_EVIDENCE_NAMESPACE: Final = "semantic_completeness_verification_exam_v2"
"""Where an exam-v2 certification's evidence is written; a new, task-specific namespace."""
COMPLETENESS_CERTIFICATION_RECORD_FORMAT: Final = "ie2-semantic-completeness-certification.v1"
COMPLETENESS_SEAL_PATH: Final = Path(
    "tests/certification/exam_manifests/ie2-semantic-completeness-exam-v2.seal.json"
)

EXPECTED_VERIFIER_POLICY_ID: Final = "ie2-semantic-completeness"
EXPECTED_VERIFIER_POLICY_VERSION: Final = "ie2-semantic-completeness-v1"
EXPECTED_INSTRUCTION_SHA256: Final = (
    "56b753a9156883264f9bdd070f9b5b63facb653c68bdb5fbcd0c0322814a0d7c"
)
"""The contestant's instruction, frozen before any live call: an edit breaks the exam."""

COMPLETENESS_RUNS_PER_CASE: Final = 3
"""The existing MR4/MR6 rule: three independent runs per case, every one passing. No
averaging, no majority."""
COMPLETENESS_CALL_BUDGET: Final = 75
"""``len(CASES) * COMPLETENESS_RUNS_PER_CASE``, pasted and sealed before any live call."""
COMPLETENESS_ACCEPTANCE_RULE: Final = "every case passes all of its independent runs (MR4/MR6)"
EXPECTED_REPORT_SCHEMA_SHA256: Final = (
    "3686a0fc213df48aa87f22a89c7f76be12ceec34cf95728360c39fe29f4e466d"
)
"""``schema_sha256(CompletenessReport.model_json_schema())``: the canonical output contract."""
EXPECTED_OPENAI_WIRE_SCHEMA_SHA256: Final = (
    "cc39ac457748f60136a6f853a924a45041030763f79d7193a3964785e71bd6de"
)
EXPECTED_OPENAI_WIRE_SCHEMA_COMPILER: Final = "foundry.openai-structured-outputs.v1"
EXPECTED_COMPLETENESS_EXAM_SHA256: Final = (
    "c6f9ca5bfc8e4c8f4705bc49ab7c7c65477bda933920b5b6a817a80a7502338d"
)
"""``completeness_exam_sha256()``, pasted, never computed at import. A change to what the exam
asks, builds, scores, accepts or binds fails the build until the version and digest are
reviewed."""
COMPLETENESS_TIMEOUT_SECONDS: Final = 180.0
"""The IE3 predeclared transport timeout. The production verifier sends a request with no
execution constraints, so the timeout is the provider adapter's own default and no output
guard reaches the transport; the certification examines that production request unchanged."""

STUFFING_MIN_DISTINCT: Final = 4
STUFFING_MAX_DENSITY_PERCENT: Final = 50
"""An item naming at least 4 distinct phrases of one group, whose tokens are more than half
marker tokens, is a list of markers rather than a finding."""


# --- sealed expectations ----------------------------------------------------------------------


@dataclass(frozen=True)
class MarkerGroup:
    """One meaning a finding must name: any of ``markers`` or ``synonyms`` satisfies it."""

    name: str
    markers: tuple[str, ...]
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Expectation:
    proposition_id: str
    verdict: CompletenessVerdict
    finding: str | None = None
    """The finding category (hidden): what region a non-COMPLETE finding is about."""
    groups: tuple[MarkerGroup, ...] = ()
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompletenessCase:
    case_id: str
    category: str
    request: CompletenessRequest
    expected: tuple[Expectation, ...]


# --- the matcher ------------------------------------------------------------------------------

_APOSTROPHE = re.compile(r"['‘’`]")
_SEPARATOR = re.compile(r"[\W_]+")


def normalise(text: str) -> str:
    """Case folded, apostrophes removed, every other non-word run one space, trimmed."""
    return " ".join(_SEPARATOR.sub(" ", _APOSTROPHE.sub("", text.casefold())).split())


def mentions(text: str, phrase: str) -> bool:
    """Does ``text`` contain ``phrase`` as whole tokens? Never a substring of a word."""
    return f" {normalise(phrase)} " in f" {normalise(text)} "


def _occurrences(tokens: list[str], phrase: str) -> list[int]:
    words = normalise(phrase).split()
    n = len(words)
    return [i for i in range(len(tokens) - n + 1) if tokens[i : i + n] == words]


def _is_stuffed(item: str, groups: tuple[MarkerGroup, ...]) -> bool:
    tokens = normalise(item).split()
    covered: set[int] = set()
    most_distinct = 0
    for group in groups:
        distinct = 0
        for phrase in (*group.markers, *group.synonyms):
            starts = _occurrences(tokens, phrase)
            if starts:
                distinct += 1
                width = len(normalise(phrase).split())
                for start in starts:
                    covered.update(range(start, start + width))
        most_distinct = max(most_distinct, distinct)
    return (
        most_distinct >= STUFFING_MIN_DISTINCT
        and len(covered) * 100 > len(tokens) * STUFFING_MAX_DENSITY_PERCENT
    )


def _satisfies(item: str, group: MarkerGroup) -> bool:
    return any(mentions(item, phrase) for phrase in (*group.markers, *group.synonyms))


def _restates(item: str, statement: str) -> bool:
    return f" {normalise(statement)} " in f" {normalise(item)} "


def identifies(items: tuple[str, ...], groups: tuple[MarkerGroup, ...], statement: str) -> bool:
    """One item that names every mandatory meaning, is not a bare list of markers, and does not
    merely restate the whole proposition (which names no region)."""
    return any(
        all(_satisfies(item, g) for g in groups)
        and not _is_stuffed(item, groups)
        and not _restates(item, statement)
        for item in items
    )


def _region(verdict: PropositionVerdict) -> tuple[str, ...]:
    if verdict.verdict == "INCOMPLETE":
        return verdict.missing
    if verdict.verdict == "OVERREACH":
        return verdict.unsupported
    return verdict.contradictory


# --- the scorer -------------------------------------------------------------------------------


def score_completeness_report(
    case: CompletenessCase, report: CompletenessReport | None
) -> tuple[str, ...]:
    """Every reason this report fails its case; empty means the attempt passes."""
    if report is None:
        return ("no parseable CompletenessReport",)
    problems = report_findings(case.request, report)
    if problems:
        return problems
    got = {v.proposition_id: v for v in report.verdicts}
    statements = {p.proposition_id: p.statement for p in case.request.propositions}
    failures: list[str] = []
    for expected in case.expected:
        verdict = got[expected.proposition_id]
        if verdict.verdict != expected.verdict:
            failures.append(
                f"{expected.proposition_id}: verdict {verdict.verdict}, sealed {expected.verdict}"
            )
            continue
        if expected.verdict == "COMPLETE":
            continue
        if not identifies(_region(verdict), expected.groups, statements[expected.proposition_id]):
            names = ", ".join(g.name for g in expected.groups)
            failures.append(
                f"{expected.proposition_id}: the finding does not identify the "
                f"{expected.finding} region (groups: {names})"
            )
        stated = (*verdict.missing, *verdict.unsupported, *verdict.contradictory)
        for phrase in expected.forbidden:
            if any(mentions(item, phrase) for item in stated):
                failures.append(f"{expected.proposition_id}: forbidden interpretation {phrase!r}")
    return tuple(failures)


# --- the case builder -------------------------------------------------------------------------

Role = Literal["ASSERTED", "SUPPORTED", "RETIRED"]


def _claim(
    ref: str, subject: str, predicate: str, value: str, role: Role = "ASSERTED"
) -> ReviewedClaim:
    return ReviewedClaim(ref=ref, role=role, subject=subject, predicate=predicate, value=value)


def _prop(
    pid: str,
    statement: str,
    claims: tuple[ReviewedClaim, ...],
    *,
    sentences: tuple[str, ...] | None = None,
    retired: tuple[ReviewedClaim, ...] = (),
) -> PropositionReview:
    supported = all(c.role == "SUPPORTED" for c in claims)
    return PropositionReview(
        proposition_id=pid,
        statement=statement,
        source_sentences=sentences or (statement,),
        disposition="SUPPORT" if supported else ("ASSERT_SUPERSEDE" if retired else "ASSERT"),
        claims=claims,
        retired=retired,
    )


def _case(
    number: int, category: str, *items: tuple[PropositionReview, Expectation]
) -> CompletenessCase:
    """Neutral model-visible ids only: the request carries a sequence number, never a label."""
    for review, expectation in items:
        if review.proposition_id != expectation.proposition_id:
            raise ValueError("an expectation names its own proposition")
    return CompletenessCase(
        case_id=f"C{number:02d}",
        category=category,
        request=CompletenessRequest(
            project_id=PROJECT,
            subject_invocation_id=f"INV-{number:04d}",
            propositions=tuple(review for review, _ in items),
        ),
        expected=tuple(expectation for _, expectation in items),
    )


def _complete(pid: str = "p1") -> Expectation:
    return Expectation(proposition_id=pid, verdict="COMPLETE")


# --- the corpus -------------------------------------------------------------------------------

LOANS: Final = "Library loans"
RESERVATIONS: Final = "Library reservations"
FINES: Final = "Late fines"
DAMAGE: Final = "Damage reports"
CREDIT: Final = "Service credit for an unavailable reserved vehicle"
"""The real governed concern subject of the recorded v6 K-CREDIT section."""

RENEW: Final = "A member may renew a loan twice, online, if nobody else has reserved the book."

LATENESS_7: Final = MarkerGroup(
    "lateness",
    ("later", "late", "after", "beyond", "past", "7 days", "deadline"),
    ("seven days", "7 day", "seven day", "overdue"),
)
REFUSAL: Final = MarkerGroup(
    "refusal",
    ("refused", "rejected", "denied", "not accepted", "cannot be accepted", "ineligible"),
    ("refusal", "refuses", "rejects", "rejection", "denies", "denial", "not be accepted",
     "declined"),
)  # fmt: skip
LATENESS_48: Final = MarkerGroup(
    "lateness",
    ("later", "late", "after", "beyond", "past", "48 hours", "deadline"),
    ("48 hour", "overdue", "too late"),
)
DEADLINE_MISREAD: Final = (
    "deadline is missing",
    "missing deadline",
    "no deadline",
    "deadline is not stated",
    "deadline not stated",
    "48 hours is missing",
)
"""Forbidden for the regression: the deadline IS stated by the claim; saying it is missing is
the wrong interpretation of what the claim set lacks."""

CASES: Final[tuple[CompletenessCase, ...]] = (
    _case(1, "FAITHFUL_PARAPHRASE", (
        _prop("p1", "A book may be borrowed for three weeks.",
              (_claim("JDG-1", LOANS, "loan_period", "21 days"),)),
        _complete())),
    _case(2, "FAITHFUL_PARAPHRASE", (
        _prop("p1", "A member may hold at most four reservations at once.",
              (_claim("JDG-1", RESERVATIONS, "maximum_active_reservations", "4"),)),
        _complete())),
    _case(3, "FAITHFUL_DECOMPOSITION", (
        _prop("p1", "A loan is made at the issue desk and is recorded on the member's card.",
              (_claim("JDG-1", LOANS, "loan_channel", "the issue desk"),
               _claim("JDG-2", LOANS, "loan_record", "recorded on the member's card"))),
        _complete())),
    _case(4, "JOINTLY_COMPLETE_THREE_CLAIMS", (
        _prop("p1", RENEW,
              (_claim("JDG-1", "Loan renewals", "maximum_renewals", "2"),
               _claim("JDG-2", "Loan renewals", "renewal_channel", "online"),
               _claim("JDG-3", "Loan renewals", "renewal_condition",
                      "no other member has reserved the book"))),
        _complete())),
    _case(5, "MISSING_CONDITION", (
        _prop("p1", RENEW,
              (_claim("JDG-1", "Loan renewals", "maximum_renewals", "2"),
               _claim("JDG-2", "Loan renewals", "renewal_channel", "online"))),
        Expectation("p1", "INCOMPLETE", "MISSING_CONDITION", (
            MarkerGroup("not reserved by another member",
                        ("reserved", "reservation", "reservations", "reserve", "reserves"),
                        ("hold", "holds", "on hold", "requested", "waiting list", "queue")),
        )))),
    _case(6, "MISSING_CONSEQUENCE", (
        _prop("p1", "A book returned late is charged 0.20 EUR per day, and borrowing is paused "
              "until the fine is paid.",
              (_claim("JDG-1", FINES, "late_fine", "0.20 EUR per day"),)),
        Expectation("p1", "INCOMPLETE", "MISSING_CONSEQUENCE", (
            MarkerGroup("borrowing paused",
                        ("paused", "pause", "pauses", "suspended", "suspension", "blocked",
                         "barred"),
                        ("block", "blocks", "suspends", "halted", "frozen", "stopped",
                         "cannot borrow", "may not borrow", "not allowed to borrow",
                         "no borrowing", "no further borrowing", "restricted")),
        )))),
    _case(7, "MISSING_EXCEPTION", (
        _prop("p1", "Loans last three weeks, except reference books, which cannot be borrowed.",
              (_claim("JDG-1", LOANS, "loan_period", "3 weeks"),)),
        Expectation("p1", "INCOMPLETE", "MISSING_EXCEPTION", (
            MarkerGroup("reference books", ("reference", "reference book", "reference books")),
            MarkerGroup("not borrowable",
                        ("cannot be borrowed", "not be borrowed", "may not be borrowed",
                         "excluded", "exception", "except"),
                        ("can not be borrowed", "not borrowable", "exempt", "exempted",
                         "excepted", "exclusion", "exclude", "excludes", "not lent",
                         "not loaned", "not for loan", "cannot be lent", "not loanable",
                         "non loanable")),
        )))),
    _case(8, "MISSING_SECOND_SENTENCE", (
        _prop("p1", "A reserved book is held for five days, and after that the reservation "
              "lapses and passes to the next member.",
              (_claim("JDG-1", RESERVATIONS, "reservation_hold", "5 days"),),
              sentences=("A reserved book is held for five days.",
                         "After that the reservation lapses and passes to the next member.")),
        Expectation("p1", "INCOMPLETE", "MISSING_SECOND_SENTENCE", (
            MarkerGroup("lapses and passes on",
                        ("lapses", "lapse", "lapsed", "expires", "expired", "next member"),
                        ("expire", "expiry", "passes", "passed", "passes to", "next person",
                         "next in line", "next borrower", "released", "release", "cancelled",
                         "canceled", "ends", "goes to", "given to", "offered to", "moves to",
                         "queue")),
        )))),
    _case(9, "MISSING_SECOND_CLAUSE", (
        _prop("p1", "Members under 16 need a guardian's signature and may borrow at most five "
              "items.",
              (_claim("JDG-1", "Junior membership", "junior_membership_signature",
                      "a guardian's signature"),)),
        Expectation("p1", "INCOMPLETE", "MISSING_SECOND_CLAUSE", (
            MarkerGroup("five", ("five", "5")),
            MarkerGroup("borrowing limit",
                        ("items", "item", "limit", "at most", "maximum"),
                        ("books", "borrow", "borrowing", "loans", "up to", "no more than",
                         "max")),
        )))),
    _case(10, "UNSUPPORTED_ADDITION", (
        _prop("p1", "A damage report made more than 7 days after return is refused.",
              (_claim("JDG-1", DAMAGE, "late_damage_report",
                      "refused after 7 days, and the member is suspended"),)),
        Expectation("p1", "OVERREACH", "UNSUPPORTED_ADDITION", (
            MarkerGroup("member suspension",
                        ("suspended", "suspension", "suspend", "suspends"),
                        ("suspending", "barred", "banned", "ban", "blocked")),
        )))),
    _case(11, "CONTRADICTION", (
        _prop("p1", "The late fine is capped at 10 EUR per item.",
              (_claim("JDG-1", FINES, "fine_cap", "10 EUR per item"),
               _claim("JDG-2", FINES, "fine_cap_per_item", "15 EUR"))),
        Expectation("p1", "CONTRADICTORY", "CONFLICTING_CAP", (
            MarkerGroup("fifteen", ("15", "fifteen")),
        )))),
    _case(12, "LEXICAL_OVERLAP_INCOMPLETE", (
        _prop("p1", "Overdue notices are sent by email and, if unanswered after a week, by post.",
              (_claim("JDG-1", "Overdue notices", "overdue_notice_channel",
                      "overdue notices are sent by email"),)),
        Expectation("p1", "INCOMPLETE", "MISSING_FOLLOW_UP", (
            MarkerGroup("by post", ("post", "postal", "letter", "by post"),
                        ("letters", "posted", "by mail", "paper", "printed")),
        )))),
    _case(13, "LEXICAL_OVERLAP_COMPLETE", (
        _prop("p1", "Children's books can be kept for a fortnight.",
              (_claim("JDG-1", "Children's loans", "childrens_book_loan_period", "14 days"),)),
        _complete())),
    _case(14, "LEXICAL_OVERLAP_COMPLETE", (
        _prop("p1", "Members over 65 pay no late fines.",
              (_claim("JDG-1", FINES, "late_fines_for_members_over_65", "waived"),)),
        _complete())),
    _case(15, "DEADLINE_VS_REFUSAL", (
        _prop("p1", "A damage report must be made within 7 days of return, and a later report "
              "is refused.",
              (_claim("JDG-1", DAMAGE, "damage_report_deadline", "7 days"),),
              sentences=("A damage report must be made within 7 days of return.",
                         "A later report is refused.")),
        Expectation("p1", "INCOMPLETE", "MISSING_REFUSAL_CONSEQUENCE",
                    (LATENESS_7, REFUSAL)))),
    _case(16, "ELIGIBILITY_VS_CONSEQUENCE", (
        _prop("p1", "Only members with no outstanding fines may reserve a book, and a "
              "reservation by a member with fines is cancelled.",
              (_claim("JDG-1", RESERVATIONS, "reservation_eligibility",
                      "no outstanding fines"),)),
        Expectation("p1", "INCOMPLETE", "MISSING_CANCELLATION_CONSEQUENCE", (
            MarkerGroup("cancelled",
                        ("cancelled", "canceled", "cancellation", "cancel"),
                        ("cancels", "voided", "void", "revoked", "annulled", "withdrawn",
                         "removed")),
        )))),
    _case(17, "SUPPORT_DISPOSITION", (
        _prop("p1", "A loan lasts three weeks.",
              (_claim("CLM-1", LOANS, "loan_period", "21 days", "SUPPORTED"),)),
        _complete("p1")), (
        _prop("p2", "A loan lasts two weeks.",
              (_claim("CLM-1", LOANS, "loan_period", "21 days", "SUPPORTED"),)),
        Expectation("p2", "CONTRADICTORY", "CONFLICTING_LOAN_PERIOD", (
            MarkerGroup("loan length",
                        ("two weeks", "2 weeks", "14 days", "fortnight", "21 days",
                         "three weeks", "3 weeks"),
                        ("21", "14")),
        )))),
    _case(18, "SUPPORT_DISPOSITION", (
        _prop("p1", "A loan lasts three weeks and can be extended once by phone.",
              (_claim("CLM-1", LOANS, "loan_period", "21 days", "SUPPORTED"),)),
        Expectation("p1", "INCOMPLETE", "MISSING_EXTENSION", (
            MarkerGroup("extension",
                        ("extended", "extend", "extension", "renewed", "renewal"),
                        ("extends", "renew", "renews", "renewable", "prolonged", "prolong",
                         "prolongation")),
        )))),
    _case(19, "ASSERT_SUPERSEDE_DISPOSITION", (
        _prop("p1", "The late fine is now 0.30 EUR per day.",
              (_claim("JDG-1", FINES, "late_fine", "0.30 EUR per day"),),
              retired=(_claim("CLM-2", FINES, "late_fine", "0.20 EUR per day", "RETIRED"),)),
        _complete())),
    _case(20, "ASSERT_SUPERSEDE_DISPOSITION", (
        _prop("p1", "The late fine is now 0.30 EUR per day and is capped at 12 EUR per item.",
              (_claim("JDG-1", FINES, "late_fine_rate", "0.30 EUR per day"),),
              retired=(_claim("CLM-3", FINES, "late_fine", "0.20 EUR per day", "RETIRED"),)),
        Expectation("p1", "INCOMPLETE", "MISSING_CAP", (
            MarkerGroup("twelve", ("12", "twelve")),
        )))),
    _case(21, "K_CREDIT_REGRESSION", (
        _prop("p1", "The service credit for an unavailable vehicle must be claimed in the app "
              "within 48 hours after the reservation start, and a later claim is refused.",
              (_claim("JDG-1", CREDIT, "claim_deadline_after_reservation_start", "48 hours"),),
              sentences=("The service credit for an unavailable vehicle must be claimed in the "
                         "app within 48 hours after the reservation start.",
                         "A claim made later is refused.")),
        Expectation("p1", "INCOMPLETE", "MISSING_REFUSAL_CONSEQUENCE",
                    (LATENESS_48, REFUSAL), DEADLINE_MISREAD))),
    _case(22, "ASSERT_DISPOSITION", (
        _prop("p1", "Books returned outside opening hours go in the drop box and are checked "
              "in the next morning.",
              (_claim("JDG-1", "Library returns", "after_hours_return_channel", "the drop box"),
               _claim("JDG-2", "Library returns", "after_hours_check_in", "the next morning"))),
        _complete("p1")), (
        _prop("p2", "A member may borrow up to ten items at once.",
              (_claim("JDG-3", LOANS, "maximum_loans",
                      "10 items, only with a valid photo ID"),)),
        Expectation("p2", "OVERREACH", "UNSUPPORTED_IDENTIFICATION_CONDITION", (
            MarkerGroup("photo ID",
                        ("photo", "photo id", "id", "identification"),
                        ("identity", "identity card", "id card", "passport",
                         "proof of identity")),
        )))),
    _case(23, "CONTRADICTION", (
        _prop("p1", "A book may be returned to any branch of the library.",
              (_claim("JDG-1", "Library returns", "return_branch",
                      "only the branch that issued the loan"),)),
        Expectation("p1", "CONTRADICTORY", "CONFLICTING_RETURN_BRANCH", (
            MarkerGroup("which branch",
                        ("issuing branch", "issuing", "same branch", "any branch"),
                        ("issued", "original branch", "home branch", "lending branch",
                         "one branch", "every branch", "all branches")),
        )))),
    _case(24, "COMPLETE_CONDITION_AND_CONSEQUENCE", (
        _prop("p1", "Members may print up to 20 pages a day free of charge; further pages cost "
              "0.10 EUR each.",
              (_claim("JDG-1", "Printing", "free_print_quota", "20 pages per day at no charge"),
               _claim("JDG-2", "Printing", "additional_page_price",
                      "0.10 EUR per page beyond 20 pages in a day"))),
        _complete())),
    _case(25, "COMPLETE_DEADLINE_AND_CONSEQUENCE", (
        _prop("p1", "A study room booking must be confirmed at least 24 hours ahead, and an "
              "unconfirmed booking is cancelled.",
              (_claim("JDG-1", "Study room bookings", "confirmation_deadline",
                      "at least 24 hours before the booking"),
               _claim("JDG-2", "Study room bookings", "unconfirmed_booking_outcome",
                      "cancelled")),
              sentences=("A study room booking must be confirmed at least 24 hours ahead.",
                         "An unconfirmed booking is cancelled.")),
        _complete())),
)  # fmt: skip


def case_by_id(case_id: str) -> CompletenessCase:
    (case,) = [c for c in CASES if c.case_id == case_id]
    return case


# --- one attempt through the production verifier ----------------------------------------------


def render_request(request: CompletenessRequest) -> str:
    """The user message, as the production verifier renders it."""
    return json.dumps(request.model_dump(mode="json"), sort_keys=True)


class _RecordingProvider:
    """Delegates to the real adapter; remembers every request, result and raised error."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.requests: list[ModelRequest] = []
        self.results: list[ProviderExecutionResult[Any]] = []
        self.errors: list[BaseException] = []

    @property
    def provider_id(self) -> str:
        return str(self._inner.provider_id)

    def execute(self, **kwargs: Any) -> ProviderExecutionResult[Any]:
        self.requests.append(kwargs["request"])
        try:
            result: ProviderExecutionResult[Any] = self._inner.execute(**kwargs)
        except BaseException as exc:
            self.errors.append(exc)
            raise
        self.results.append(result)
        return result


@dataclass(frozen=True)
class CompletenessObservation:
    case_id: str
    attempt: int
    sent: tuple[ModelRequest, ...]
    result: ProviderExecutionResult[Any] | None
    report: CompletenessReport | None
    verifier: VerifierIdentity


def _jsonable(value: Any) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def run_completeness_attempt(
    contestant: Contestant, case: CompletenessCase, attempt: int, *, provider: Any
) -> CompletenessObservation:
    """One verification through the production verifier and Model Runtime, fresh each time.

    Execution failures are classified by the existing taxonomy (transport and harness limits
    are INCOMPLETE; a protocol fault is NOT CERTIFIED), including those the production
    verifier records as "no report": the recording provider sees the error the verifier
    swallows. An answer the runtime refuses as not a report is scored, as ``None``.
    """
    recording = _RecordingProvider(provider)
    runtime = ModelRuntime(registry=contestant.registry(), providers=(recording,))
    verifier = ModelRuntimeCompletenessVerifier(
        runtime=runtime, run_id=f"SCV-CERT-{case.request.subject_invocation_id}-{attempt}"
    )
    try:
        verification = verifier.verify(case.request)
    except (ModelProviderError, ModelProtocolError) as exc:
        classify_execution_failure(exc)
        raise  # unreachable; classify_execution_failure always raises
    if recording.errors:
        classify_execution_failure(recording.errors[0])
        raise AssertionError(f"unclassified provider failure: {recording.errors[0]!r}")
    return CompletenessObservation(
        case_id=case.case_id,
        attempt=attempt,
        sent=tuple(recording.requests),
        result=recording.results[0] if recording.results else None,
        report=verification.report,
        verifier=verification.verifier,
    )


def score_completeness_global_gates(
    observation: CompletenessObservation, case: CompletenessCase, *, candidate: ModelIdentity
) -> tuple[str, ...]:
    """Applied to every live call, whatever the case expects. ``candidate`` has no default."""
    if len(observation.sent) != 1 or observation.result is None:
        return (f"one verification must be one answered call, saw {len(observation.sent)}",)
    (sent,) = observation.sent
    ran = observation.result.identity
    failures: list[str] = []
    if (ran.provider, ran.model) != (candidate.provider, candidate.model):
        failures.append(f"executed {ran.provider}/{ran.model}, not the candidate")
    if sent.task is not ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION:
        failures.append(f"task was {sent.task.value}")
    if sent.tier is not ModelTier.REASONER:
        failures.append(f"tier was {sent.tier.value}")
    if (sent.policy_id, sent.policy_version) != (
        EXPECTED_VERIFIER_POLICY_ID,
        EXPECTED_VERIFIER_POLICY_VERSION,
    ):
        failures.append(f"policy was {sent.policy_id}/{sent.policy_version}")
    system, user = sent.messages
    if hashlib.sha256(system.content.encode()).hexdigest() != EXPECTED_INSTRUCTION_SHA256:
        failures.append("the instruction is not the frozen one")
    if user.content != render_request(case.request):
        failures.append("the request sent is not the sealed request")
    if sent.constraints != ModelExecutionConstraints():
        failures.append("the request is not the production request")
    reported = observation.verifier
    if (reported.provider, reported.model, reported.policy_version) != (
        candidate.provider,
        candidate.model,
        EXPECTED_VERIFIER_POLICY_VERSION,
    ):
        failures.append(f"verifier identity reported as {reported}")
    return tuple(failures)


def score_completeness_attempt(
    observation: CompletenessObservation, case: CompletenessCase, *, candidate: ModelIdentity
) -> tuple[str, ...]:
    return (
        *score_completeness_global_gates(observation, case, candidate=candidate),
        *score_completeness_report(case, observation.report),
    )


def attempt_evidence(
    observation: CompletenessObservation, *, verdict: str, failures: tuple[str, ...]
) -> dict[str, Any]:
    """Every input and output of one attempt, as data. Unknown telemetry stays null."""
    sent = observation.sent[0] if observation.sent else None
    result = observation.result
    usage = result.usage if result is not None else None
    return {
        "case": observation.case_id,
        "attempt": observation.attempt,
        "request_json": sent.messages[1].content if sent else None,
        "instruction_sha256": (
            hashlib.sha256(sent.messages[0].content.encode()).hexdigest() if sent else None
        ),
        "task": sent.task.value if sent else None,
        "tier": sent.tier.value if sent else None,
        "policy_id": sent.policy_id if sent else None,
        "policy_version": sent.policy_version if sent else None,
        "request_constraints": sent.constraints.model_dump(mode="json") if sent else None,
        "raw_output": _jsonable(result.output) if result is not None else None,
        "parsed_report": (
            observation.report.model_dump(mode="json") if observation.report else None
        ),
        "verifier": observation.verifier.model_dump(mode="json"),
        "provider": result.identity.provider if result is not None else None,
        "model": result.identity.model if result is not None else None,
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
        "cost_usd": usage.cost_usd if usage else None,
        "wall_clock_ms": usage.wall_clock_ms if usage else None,
        "finish_reason": result.finish_reason if result is not None else None,
        "verdict": verdict,
        "failures": list(failures),
    }


def completeness_verdict(attempts: list[dict[str, Any]]) -> str:
    """PASS only when every case's every required run was recorded exactly once and passed."""
    required = {(c.case_id, n) for c in CASES for n in range(1, COMPLETENESS_RUNS_PER_CASE + 1)}
    recorded = [(a["case"], a["attempt"]) for a in attempts]
    complete = len(recorded) == len(required) == COMPLETENESS_CALL_BUDGET
    if not complete or set(recorded) != required:
        return "NOT CERTIFIED"
    return "PASS" if all(a["verdict"] == "PASS" for a in attempts) else "NOT CERTIFIED"


# --- exam identity ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderConfiguration:
    """How the candidate provider is configured for the certification (not the exam itself)."""

    reasoning_effort: str
    reasoning_mode: str
    timeout_seconds: float
    output_guard: int | None
    """``None``: the production verifier sends no output bound, and none is added."""


CERTIFIED_CONFIGURATION: Final = ProviderConfiguration(
    reasoning_effort="high",
    reasoning_mode="standard",
    timeout_seconds=COMPLETENESS_TIMEOUT_SECONDS,
    output_guard=None,
)

BINDING_FIELDS: Final = (
    "record_format",
    "verdict",
    "provider",
    "model",
    "task",
    "verifier_policy_id",
    "verifier_policy_version",
    "instruction_sha256",
    "canonical_schema_sha256",
    "wire_schema_sha256",
    "wire_schema_compiler",
    "exam_id",
    "exam_version",
    "exam_sha256",
    "reasoning_effort",
    "reasoning_mode",
    "timeout_seconds",
    "output_guard",
    "runs_per_case",
    "call_budget",
)
"""Every field a certificate must match, exactly and present, to certify anything."""


@dataclass(frozen=True)
class PriorExam:
    exam_version: str
    exam_sha256: str
    status: str
    superseded_by: str
    defect: str


PRIOR_COMPLETENESS_EXAMS: Final[tuple[PriorExam, ...]] = (
    PriorExam(
        exam_version="ie2-semantic-completeness-exam-v1",
        exam_sha256="8eb4ea4ec254f5b4cdb3c164c94276fbd1efbe67989b3f2ad03088a0f5e4dad5",
        status="PREPARED_NEVER_SAT",
        superseded_by=COMPLETENESS_EXAM_VERSION,
        defect="scored the top-level verdict only (a correct label with a wrong or empty "
        "finding passed); its K-CREDIT case paraphrased the recorded v6 loss under an invented "
        "subject; no certification harness or certificate bound it. Frozen unchanged in "
        "foundry.experiments.completeness_verifier_exam; no model ever sat it",
    ),
)
"""Exam v1 is historical and prepared: never sat, no certificate exists, never rewritten."""


def _case_document(case: CompletenessCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "request": case.request.model_dump(mode="json"),
        "expected": [
            {
                "proposition_id": e.proposition_id,
                "verdict": e.verdict,
                "finding": e.finding,
                "groups": [
                    {"name": g.name, "markers": list(g.markers), "synonyms": list(g.synonyms)}
                    for g in e.groups
                ],
                "forbidden": list(e.forbidden),
            }
            for e in case.expected
        ],
    }


def _openai_wire() -> tuple[str, str]:
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider

    return (
        schema_sha256(OpenAIModelProvider.wire_schema(CompletenessReport)),
        OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    )


def completeness_exam_manifest() -> dict[str, Any]:
    """Everything that decides what the exam asks, how each run executes and what passes."""
    wire, compiler = _openai_wire()
    return {
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "cases": [_case_document(case) for case in CASES],
        "code": code_closure(
            [
                _case,
                _prop,
                _claim,
                _complete,
                render_request,
                run_completeness_attempt,
                score_completeness_report,
                score_completeness_global_gates,
                score_completeness_attempt,
                attempt_evidence,
                completeness_verdict,
                certificate_binds,
                write_completeness_certification,
            ]
        ),
        "acceptance": {
            "rule": COMPLETENESS_ACCEPTANCE_RULE,
            "cases": [case.case_id for case in CASES],
            "runs_per_case": COMPLETENESS_RUNS_PER_CASE,
            "call_budget": COMPLETENESS_CALL_BUDGET,
        },
        "identity": {
            "task": ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION.value,
            "tier": ModelTier.REASONER.value,
            "verifier_policy_id": EXPECTED_VERIFIER_POLICY_ID,
            "verifier_policy_version": EXPECTED_VERIFIER_POLICY_VERSION,
            "instruction_sha256": EXPECTED_INSTRUCTION_SHA256,
            "canonical_schema_sha256": schema_sha256(CompletenessReport.model_json_schema()),
            "openai_wire_schema_sha256": wire,
            "openai_wire_schema_compiler": compiler,
            "configuration": {
                "reasoning_effort": CERTIFIED_CONFIGURATION.reasoning_effort,
                "reasoning_mode": CERTIFIED_CONFIGURATION.reasoning_mode,
                "timeout_seconds": CERTIFIED_CONFIGURATION.timeout_seconds,
                "output_guard": CERTIFIED_CONFIGURATION.output_guard,
            },
        },
        "binding_fields": list(BINDING_FIELDS),
    }


def completeness_exam_sha256() -> str:
    return canonical_digest(completeness_exam_manifest())


# --- the certificate --------------------------------------------------------------------------


def write_completeness_certification(
    contestant: Contestant,
    attempts: list[dict[str, Any]],
    *,
    frozen_production_base: str,
    configuration: ProviderConfiguration,
) -> dict[str, Any]:
    """The verdict record, bound to the task, verifier policy, contract and exam it was earned
    on. A separate task certificate: nothing is inherited from any other certification."""
    if contestant.wire_schema is None or contestant.wire_schema_compiler is None:
        raise ValueError("a completeness certification must bind the provider's wire schema")
    if contestant.task is not ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION:
        raise ValueError("the contestant must sit SEMANTIC_COMPLETENESS_VERIFICATION")
    if (contestant.reasoning_effort, contestant.timeout_seconds) != (
        configuration.reasoning_effort,
        configuration.timeout_seconds,
    ):
        raise ValueError("the recorded configuration is not the contestant's")
    passed = sum(1 for a in attempts if a["verdict"] == "PASS")
    payload: dict[str, Any] = {
        "record_format": COMPLETENESS_CERTIFICATION_RECORD_FORMAT,
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "exam_sha256": completeness_exam_sha256(),
        "candidate": contestant.label,
        "provider": contestant.identity.provider,
        "model": contestant.identity.model,
        "task": contestant.task.value,
        "tier": ModelTier.REASONER.value,
        "verifier_policy_id": COMPLETENESS_POLICY_ID,
        "verifier_policy_version": EXPECTED_VERIFIER_POLICY_VERSION,
        "instruction_sha256": hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest(),
        "canonical_schema_sha256": schema_sha256(CompletenessReport.model_json_schema()),
        "wire_schema_sha256": schema_sha256(contestant.wire_schema(CompletenessReport)),
        "wire_schema_compiler": contestant.wire_schema_compiler,
        "reasoning_effort": configuration.reasoning_effort,
        "reasoning_mode": configuration.reasoning_mode,
        "timeout_seconds": configuration.timeout_seconds,
        "output_guard": configuration.output_guard,
        "request_constraints": ModelExecutionConstraints().model_dump(mode="json"),
        "frozen_production_base": frozen_production_base,
        "acceptance_rule": COMPLETENESS_ACCEPTANCE_RULE,
        "cases": [case.case_id for case in CASES],
        "runs_per_case": COMPLETENESS_RUNS_PER_CASE,
        "call_budget": COMPLETENESS_CALL_BUDGET,
        "required_attempts": COMPLETENESS_CALL_BUDGET,
        "recorded_attempts": len(attempts),
        "passed_attempts": passed,
        "verdict": completeness_verdict(attempts),
        "attempts": attempts,
    }
    contestant.evidence_dir.mkdir(parents=True, exist_ok=True)
    (contestant.evidence_dir / "certification.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
    return payload


def certificate_binds(
    record: dict[str, Any],
    *,
    identity: ModelIdentity,
    task: ModelTask,
    verifier_policy_id: str,
    verifier_policy_version: str,
    instruction_sha256: str,
    canonical_schema_sha256: str,
    wire_schema_sha256: str,
    wire_schema_compiler: str,
    exam_id: str,
    exam_version: str,
    exam_sha256: str,
    reasoning_effort: str,
    reasoning_mode: str,
    timeout_seconds: float,
    output_guard: int | None,
    runs_per_case: int,
    call_budget: int,
) -> bool:
    """Does ``record`` certify exactly this contestant, task, verifier policy, contract, exam
    and configuration? Fail-closed: every binding field must be present and equal."""
    expected: dict[str, Any] = {
        "record_format": COMPLETENESS_CERTIFICATION_RECORD_FORMAT,
        "verdict": "PASS",
        "provider": identity.provider,
        "model": identity.model,
        "task": task.value,
        "verifier_policy_id": verifier_policy_id,
        "verifier_policy_version": verifier_policy_version,
        "instruction_sha256": instruction_sha256,
        "canonical_schema_sha256": canonical_schema_sha256,
        "wire_schema_sha256": wire_schema_sha256,
        "wire_schema_compiler": wire_schema_compiler,
        "exam_id": exam_id,
        "exam_version": exam_version,
        "exam_sha256": exam_sha256,
        "reasoning_effort": reasoning_effort,
        "reasoning_mode": reasoning_mode,
        "timeout_seconds": timeout_seconds,
        "output_guard": output_guard,
        "runs_per_case": runs_per_case,
        "call_budget": call_budget,
    }
    return all(key in record and record[key] == expected[key] for key in BINDING_FIELDS)


def current_completeness_identity(identity: ModelIdentity) -> dict[str, Any] | None:
    """The identity a certificate must bind today, or ``None`` for a provider with no adapter."""
    from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider
    from foundry.adapters.model_runtime.xai import XAIModelProvider

    providers: dict[str, Any] = {
        "xai": XAIModelProvider,
        "openai": OpenAIModelProvider,
        "anthropic": AnthropicModelProvider,
    }
    provider = providers.get(identity.provider)
    if provider is None:
        return None
    return {
        "identity": identity,
        "task": ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
        "verifier_policy_id": COMPLETENESS_POLICY_ID,
        "verifier_policy_version": EXPECTED_VERIFIER_POLICY_VERSION,
        "instruction_sha256": hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest(),
        "canonical_schema_sha256": schema_sha256(CompletenessReport.model_json_schema()),
        "wire_schema_sha256": schema_sha256(provider.wire_schema(CompletenessReport)),
        "wire_schema_compiler": provider.WIRE_SCHEMA_COMPILER,
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "exam_sha256": completeness_exam_sha256(),
        "reasoning_effort": CERTIFIED_CONFIGURATION.reasoning_effort,
        "reasoning_mode": CERTIFIED_CONFIGURATION.reasoning_mode,
        "timeout_seconds": CERTIFIED_CONFIGURATION.timeout_seconds,
        "output_guard": CERTIFIED_CONFIGURATION.output_guard,
        "runs_per_case": COMPLETENESS_RUNS_PER_CASE,
        "call_budget": COMPLETENESS_CALL_BUDGET,
    }


def completeness_certificate_standing(record: dict[str, Any]) -> str:
    """What a record means for the current task contract and exam.

    ``NOT_CERTIFIED``: its verdict was never PASS. ``CURRENT``: it binds every current field.
    ``SUPERSEDED``: a PASS on a prior exam; true history, no current authority. ``NOT_BINDING``:
    any other PASS, including every record of another task or format (an IE3 graph
    certificate is never a completeness certificate). There is no historical completeness
    format, so ``HISTORICAL_FORMAT`` cannot arise here.
    """
    if record.get("verdict") != "PASS":
        return "NOT_CERTIFIED"
    if record.get("record_format") != COMPLETENESS_CERTIFICATION_RECORD_FORMAT:
        return "NOT_BINDING"
    current = current_completeness_identity(
        ModelIdentity(provider=str(record.get("provider")), model=str(record.get("model")))
    )
    if current is not None and certificate_binds(record, **current):
        return "CURRENT"
    prior = {(p.exam_version, p.exam_sha256) for p in PRIOR_COMPLETENESS_EXAMS}
    if (record.get("exam_version"), record.get("exam_sha256")) in prior:
        return "SUPERSEDED"
    return "NOT_BINDING"


# --- evidence integrity -----------------------------------------------------------------------


def completeness_evidence_problems(record: dict[str, Any]) -> tuple[str, ...]:
    """Re-derive a record from its own attempts. Any disagreement is a problem, never fixed."""
    if record.get("record_format") != COMPLETENESS_CERTIFICATION_RECORD_FORMAT:
        return ("not an exam-v2 completeness certification record",)
    if record.get("exam_sha256") != completeness_exam_sha256():
        return ("earned on a different exam; it cannot be re-scored against this one",)
    attempts: list[dict[str, Any]] = list(record.get("attempts") or [])
    problems: list[str] = []
    passed = sum(1 for a in attempts if a.get("verdict") == "PASS")
    if record.get("recorded_attempts") != len(attempts):
        problems.append("recorded_attempts disagrees with the attempts")
    if record.get("passed_attempts") != passed:
        problems.append("passed_attempts disagrees with the attempts")
    if record.get("required_attempts") != COMPLETENESS_CALL_BUDGET:
        problems.append("required_attempts is not the sealed budget")
    if record.get("verdict") != completeness_verdict(attempts):
        problems.append("the verdict does not follow from the attempts")
    cases = {case.case_id: case for case in CASES}
    for a in attempts:
        where = f"{a.get('case')}/{a.get('attempt')}"
        case = cases.get(str(a.get("case")))
        if case is None:
            problems.append(f"{where}: not an exam case")
            continue
        answered = a.get("request_json") is not None or a.get("verdict") == "PASS"
        if answered and a.get("request_json") != render_request(case.request):
            problems.append(f"{where}: the recorded request is not the sealed request")
        if a.get("verdict") != "PASS":
            continue
        if (a.get("provider"), a.get("model")) != (record.get("provider"), record.get("model")):
            problems.append(f"{where}: answered by another model")
        if a.get("instruction_sha256") != EXPECTED_INSTRUCTION_SHA256:
            problems.append(f"{where}: not the frozen instruction")
        if a.get("parsed_report") is None:
            problems.append(f"{where}: a PASS without a report")
            continue
        report = CompletenessReport.model_validate(a["parsed_report"])
        if CompletenessReport.model_validate(a.get("raw_output")) != report:
            problems.append(f"{where}: the parsed report is not the raw response")
        if score_completeness_report(case, report):
            problems.append(f"{where}: the recorded report does not pass its case")
    return tuple(problems)


# --- the seal ---------------------------------------------------------------------------------


def write_completeness_seal(path: Path, *, harness_sha: str) -> None:
    manifest = completeness_exam_manifest()
    document = {
        "exam_id": COMPLETENESS_EXAM_ID,
        "exam_version": COMPLETENESS_EXAM_VERSION,
        "exam_sha256": canonical_digest(manifest),
        "harness_sha": harness_sha,
        "manifest": manifest,
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def completeness_seal_problems(path: Path = COMPLETENESS_SEAL_PATH) -> tuple[str, ...]:
    """Nothing may be called until the committed seal is exactly the current exam."""
    if not path.exists():
        return (f"exam v2 is not sealed: {path} is absent",)
    document = json.loads(path.read_text())
    problems: list[str] = []
    if document.get("manifest") != completeness_exam_manifest():
        problems.append("the sealed manifest is not the current exam")
    if document.get("exam_sha256") != canonical_digest(document.get("manifest")):
        problems.append("the sealed hash is not the digest of the sealed manifest")
    if document.get("exam_sha256") != completeness_exam_sha256():
        problems.append("the sealed hash is not the current exam hash")
    if not re.fullmatch(r"[0-9a-f]{40}", str(document.get("harness_sha"))):
        problems.append("the seal names no harness commit")
    return tuple(problems)
