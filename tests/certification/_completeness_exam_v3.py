"""Certification exam v3 for SEMANTIC_COMPLETENESS_VERIFICATION (IE2 Call 3), test-only.

**Why v3 exists.** Exam v2 (``_completeness_exam``, sat live once by ``openai/gpt-6-astra``:
NOT CERTIFIED 66/75, frozen) hand-authored every expected verdict. Three of them contradicted
the approved verifier law ``ie2-semantic-completeness-v1``, which counts an actor among the
operative assertions and resolves several defects as CONTRADICTORY > INCOMPLETE > OVERREACH:
C02 and C24 were sealed COMPLETE though their claims never state the member actor, and C10 was
sealed OVERREACH though its claim also drops the "after return" anchor. The coherence audit
found a fourth (C22 p2, the C02 defect sealed OVERREACH) and a presupposed actor (C04). The
policy, its instruction, schema and runtime are unchanged: only the exam is corrected.

**The semantic inventory.** No verdict is authored. Every proposition carries a scorer-side
inventory of its operative assertions, each classified as REPRESENTED by named claims, MISSING,
UNSUPPORTED (added by a claim) or CONTRADICTED, and anchored to text: what the proposition
states, and what the named claims state, matched on v2's normalised whole-phrase boundaries.
The verdict is derived from the inventory by the sealed precedence, the required findings are
its assertions in that verdict's region, and a case whose inventory is incoherent cannot be
built. The inventory is certification metadata: it is never sent to the model.

**The scoring law** is v2's, generalised to several sealed assertions: for every non-COMPLETE
proposition, *each* required assertion must be identified by at least one finding item in the
region field of the verdict (every one of its marker groups, not keyword stuffing, not an echo
of the proposition); several items may jointly cover the inventory, and one item may cover more
than one assertion when it states them. Sealed forbidden interpretations fail. No model
adjudicates anything.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, get_args

from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_SYSTEM_INSTRUCTION,
)
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    CompletenessVerdict,
    PropositionReview,
    report_findings,
)
from foundry.model_runtime.domain import (
    ModelExecutionConstraints,
    ModelIdentity,
    ModelTask,
    ModelTier,
)
from tests.certification._certification_run import Contestant
from tests.certification._completeness_exam import (
    BINDING_FIELDS,
    CERTIFIED_CONFIGURATION,
    COMPLETENESS_ACCEPTANCE_RULE,
    COMPLETENESS_CERTIFICATION_RECORD_FORMAT,
    COMPLETENESS_EXAM_ID,
    COMPLETENESS_RUNS_PER_CASE,
    DEADLINE_MISREAD,
    EXPECTED_INSTRUCTION_SHA256,
    EXPECTED_VERIFIER_POLICY_ID,
    EXPECTED_VERIFIER_POLICY_VERSION,
    PRIOR_COMPLETENESS_EXAMS,
    CompletenessCase,
    CompletenessObservation,
    MarkerGroup,
    PriorExam,
    ProviderConfiguration,
    attempt_evidence,
    certificate_binds,
    identifies,
    mentions,
    render_request,
    score_completeness_global_gates,
)
from tests.certification._completeness_exam import _claim as claim
from tests.certification._completeness_exam import _prop as prop
from tests.certification._completeness_exam import _region as region_items
from tests.certification._completeness_exam import case_by_id as v2_case
from tests.certification._completeness_exam import (
    run_completeness_attempt as run_v2_attempt,
)
from tests.certification._exam_identity import canonical_digest, code_closure
from tests.certification._schema_identity import schema_sha256

PROJECT: Final = "PROJ-A"

COMPLETENESS_EXAM_VERSION: Final = "ie2-semantic-completeness-exam-v3"
COMPLETENESS_EVIDENCE_NAMESPACE: Final = "semantic_completeness_verification_exam_v3"
"""Where an exam-v3 certification's evidence is written. Exam v2's namespace is history."""
HISTORICAL_EXAM_V2_NAMESPACE: Final = "semantic_completeness_verification_exam_v2"
"""Exam v2 under ``ie2-semantic-completeness-v1``: Astra NOT CERTIFIED 66/75. Immutable."""
HISTORICAL_V2_RECORD_SHA256: Final = (
    "ec509dfcb371818d7c5f4e4863cb1712a4bb917ceac3319b6b7a3f2181e8aa86"
)
"""SHA-256 of exam v2's live record exactly as committed at e1833d4; never rewritten."""
COMPLETENESS_SEAL_PATH: Final = Path(
    "tests/certification/exam_manifests/ie2-semantic-completeness-exam-v3.seal.json"
)
COMPLETENESS_CALL_BUDGET: Final = 75
"""``len(CASES) * COMPLETENESS_RUNS_PER_CASE``, pasted and sealed before any live call."""
EXPECTED_COMPLETENESS_EXAM_SHA256: Final = (
    "267cfadf1303c43252439b34ed14366cb94467080e5c3256ac8db729d3becb65"
)
"""``completeness_exam_sha256()``, pasted, never computed at import."""


# --- the semantic inventory -------------------------------------------------------------------

AssertionKind = Literal[
    "ACTOR",
    "OBLIGATION",
    "PERMISSION",
    "QUANTITY",
    "TIMING",
    "TIME_ANCHOR",
    "DEADLINE",
    "CONDITION",
    "ELIGIBILITY",
    "CONSEQUENCE",
    "EXCEPTION",
    "DESTINATION",
    "REPETITION",
    "CHANNEL",
]
"""The verifier contract's operative assertions ("an actor, an obligation or permission, a
quantity or limit, a timing, a deadline, a condition or eligibility rule, a consequence or
effect, an exception, a destination, a repetition rule"), with the time anchor a timing or
deadline is measured from, and the channel through which something is done."""
ASSERTION_KINDS: Final[tuple[str, ...]] = get_args(AssertionKind)

Status = Literal["REPRESENTED", "MISSING", "UNSUPPORTED", "CONTRADICTED"]
STATUSES: Final[tuple[str, ...]] = get_args(Status)


@dataclass(frozen=True)
class OperativeAssertion:
    """One operative assertion and how the claims dispose of it.

    ``stated``: phrases the proposition states it with (none for an UNSUPPORTED addition).
    ``claimed``: phrases the claims in ``by`` state it with (none when MISSING).
    ``groups``: what a finding must name to identify it (none when REPRESENTED).
    """

    kind: AssertionKind
    status: Status
    stated: tuple[str, ...] = ()
    claimed: tuple[str, ...] = ()
    by: tuple[str, ...] = ()
    groups: tuple[MarkerGroup, ...] = ()


@dataclass(frozen=True)
class PropositionInventory:
    proposition_id: str
    assertions: tuple[OperativeAssertion, ...]
    forbidden: tuple[str, ...] = ()


def _phrases(text: str | tuple[str, ...]) -> tuple[str, ...]:
    return (text,) if isinstance(text, str) else text


def held(
    kind: AssertionKind, stated: str | tuple[str, ...], claimed: str | tuple[str, ...], *by: str
) -> OperativeAssertion:
    """Stated by the proposition and represented by the named claims."""
    return OperativeAssertion(kind, "REPRESENTED", _phrases(stated), _phrases(claimed), by)


def lost(
    kind: AssertionKind, stated: str | tuple[str, ...], *groups: MarkerGroup
) -> OperativeAssertion:
    """Stated by the proposition, stated by none of its claims."""
    return OperativeAssertion(kind, "MISSING", _phrases(stated), groups=groups)


def added(
    kind: AssertionKind, claimed: str | tuple[str, ...], by: str, *groups: MarkerGroup
) -> OperativeAssertion:
    """Asserted by a claim, stated nowhere in the proposition."""
    return OperativeAssertion(kind, "UNSUPPORTED", (), _phrases(claimed), (by,), groups)


def clash(
    kind: AssertionKind,
    stated: str | tuple[str, ...],
    claimed: str | tuple[str, ...],
    by: str,
    *groups: MarkerGroup,
) -> OperativeAssertion:
    """Stated by the proposition and contradicted by a claim."""
    return OperativeAssertion(
        kind, "CONTRADICTED", _phrases(stated), _phrases(claimed), (by,), groups
    )


def _claim_text(review: PropositionReview, refs: tuple[str, ...]) -> str:
    return " ".join(f"{c.subject} {c.predicate} {c.value}" for c in review.claims if c.ref in refs)


def inventory_problems(
    review: PropositionReview, inventory: PropositionInventory
) -> tuple[str, ...]:
    """Every way ``inventory`` fails to classify ``review`` coherently; empty means coherent.

    Each assertion is anchored: what it states is in the proposition, what it claims is in
    the claims it names, a MISSING assertion is stated by no claim, and an UNSUPPORTED one is
    not in the proposition. Every claim is classified by some assertion.
    """
    where = review.proposition_id
    refs = tuple(c.ref for c in review.claims)
    every_claim = _claim_text(review, refs)
    problems: list[str] = []
    if not any(a.status != "UNSUPPORTED" for a in inventory.assertions):
        problems.append(f"{where}: no operative assertion of the proposition is inventoried")
    for a in inventory.assertions:
        label = f"{where} {a.kind} {a.status}"
        if a.kind not in ASSERTION_KINDS:
            problems.append(f"{label}: unknown kind")
        if a.status not in STATUSES:
            problems.append(f"{label}: unknown status")
        for ref in a.by:
            if ref not in refs:
                problems.append(f"{label}: {ref} is not a claim of {where}")
        if a.status in ("REPRESENTED", "UNSUPPORTED", "CONTRADICTED") and not a.by:
            problems.append(f"{label}: names no claim")
        if a.status == "REPRESENTED" and a.groups:
            problems.append(f"{label}: a represented assertion seals no finding")
        if a.status != "REPRESENTED" and not a.groups:
            problems.append(f"{label}: no finding markers")
        if a.status != "UNSUPPORTED" and not a.stated:
            problems.append(f"{label}: states nothing of the proposition")
        for phrase in a.stated:
            if not mentions(review.statement, phrase):
                problems.append(f"{label}: {phrase!r} is not in the proposition")
        for phrase in a.claimed:
            if not mentions(_claim_text(review, a.by), phrase):
                problems.append(f"{label}: {phrase!r} is not in its claims")
        if a.status == "MISSING":
            for phrase in a.stated:
                if mentions(every_claim, phrase):
                    problems.append(f"{label}: {phrase!r} is stated by a claim")
        if a.status == "UNSUPPORTED":
            for phrase in a.claimed:
                if mentions(review.statement, phrase):
                    problems.append(f"{label}: {phrase!r} is in the proposition")
    classified = {ref for a in inventory.assertions for ref in a.by}
    for ref in refs:
        if ref not in classified:
            problems.append(f"{where}: claim {ref} is unclassified")
    if inventory.forbidden and derive_verdict(inventory) == "COMPLETE":
        problems.append(f"{where}: a forbidden interpretation on a COMPLETE proposition")
    return tuple(problems)


# --- the derived expectation ------------------------------------------------------------------


def derive_verdict(inventory: PropositionInventory) -> CompletenessVerdict:
    """The verifier instruction's precedence: CONTRADICTORY, then INCOMPLETE, then OVERREACH."""
    statuses = {a.status for a in inventory.assertions}
    if "CONTRADICTED" in statuses:
        return "CONTRADICTORY"
    if "MISSING" in statuses:
        return "INCOMPLETE"
    if "UNSUPPORTED" in statuses:
        return "OVERREACH"
    return "COMPLETE"


_REGION_STATUS: Final = {
    "INCOMPLETE": "MISSING",
    "OVERREACH": "UNSUPPORTED",
    "CONTRADICTORY": "CONTRADICTED",
}


@dataclass(frozen=True)
class RequiredFinding:
    """One sealed assertion a finding must identify."""

    name: str
    groups: tuple[MarkerGroup, ...]


@dataclass(frozen=True)
class DerivedExpectation:
    proposition_id: str
    verdict: CompletenessVerdict
    findings: tuple[RequiredFinding, ...]
    forbidden: tuple[str, ...]


def expectation(inventory: PropositionInventory) -> DerivedExpectation:
    verdict = derive_verdict(inventory)
    region = _REGION_STATUS.get(verdict)
    findings = tuple(
        RequiredFinding(f"{a.kind} {' / '.join(a.stated or a.claimed)}", a.groups)
        for a in inventory.assertions
        if a.status == region
    )
    return DerivedExpectation(inventory.proposition_id, verdict, findings, inventory.forbidden)


@dataclass(frozen=True)
class InventoryCase:
    case_id: str
    category: str
    request: CompletenessRequest
    inventory: tuple[PropositionInventory, ...]
    expected: tuple[DerivedExpectation, ...]


def inventory_case(
    number: int, category: str, *items: tuple[PropositionReview, PropositionInventory]
) -> InventoryCase:
    """Neutral model-visible ids only; refuses an incoherent inventory rather than build it."""
    for review, inventory in items:
        if review.proposition_id != inventory.proposition_id:
            raise ValueError("an inventory names its own proposition")
        problems = inventory_problems(review, inventory)
        if problems:
            raise ValueError(f"C{number:02d}: {'; '.join(problems)}")
    return InventoryCase(
        case_id=f"C{number:02d}",
        category=category,
        request=CompletenessRequest(
            project_id=PROJECT,
            subject_invocation_id=f"INV-{number:04d}",
            propositions=tuple(review for review, _ in items),
        ),
        inventory=tuple(inventory for _, inventory in items),
        expected=tuple(expectation(inventory) for _, inventory in items),
    )


def _inventory(*assertions: OperativeAssertion, forbidden: tuple[str, ...] = ()) -> Any:
    return PropositionInventory("p1", assertions, forbidden)


def _carried(case_id: str, pid: str = "p1") -> PropositionReview:
    """Exam v2's model-visible proposition, carried forward unchanged (the same object)."""
    (review,) = [p for p in v2_case(case_id).request.propositions if p.proposition_id == pid]
    return review


# --- finding markers ----------------------------------------------------------------------------
# Every v2 group is carried unchanged; new groups exist only for assertions v2 never sealed.

ACTOR_MEMBER: Final = MarkerGroup(
    "member", ("member", "members"), ("borrower", "borrowers", "patron", "patrons")
)
AS_RENEWER: Final = MarkerGroup(
    "as the one who may renew",
    ("may renew", "can renew", "allowed to renew", "permitted to renew", "entitled to renew",
     "actor"),
    ("who renews", "who may renew", "who can renew", "renewing member", "renewer", "renewers"),
)  # fmt: skip
AS_RESERVER: Final = MarkerGroup(
    "as the only ones who may reserve",
    ("only members", "may reserve", "can reserve", "allowed to reserve", "permitted to reserve",
     "entitled to reserve", "actor"),
    ("members only", "non member", "non members", "who may reserve", "who can reserve"),
)  # fmt: skip
SIXTEEN: Final = MarkerGroup("sixteen", ("16", "sixteen"))
AGE_LIMIT: Final = MarkerGroup(
    "age threshold",
    ("under", "below", "younger", "age", "aged"),
    ("years old", "minor", "minors", "underage"),
)
FROM_RETURN: Final = MarkerGroup(
    "measured from return",
    ("return", "returned", "returning"),
    ("return date", "date of return", "handed back", "given back"),
)
IN_THE_APP: Final = MarkerGroup("in the app", ("app", "in app", "in the app"), ("mobile app",))


def _v2_groups(case_id: str, pid: str = "p1") -> tuple[MarkerGroup, ...]:
    """Exam v2's sealed marker groups for a designed gap, carried by reference, never copied."""
    (sealed,) = [e for e in v2_case(case_id).expected if e.proposition_id == pid]
    return sealed.groups


# --- the corpus -------------------------------------------------------------------------------

LOANS: Final = "Library loans"
RESERVATIONS: Final = "Library reservations"
DAMAGE: Final = "Damage reports"

CHANGED_FROM_V2: Final = frozenset({"C02", "C04", "C10", "C22", "C24"})
"""The only cases whose model-visible payload differs from exam v2 (C22: p2 only)."""

CASES: Final[tuple[InventoryCase, ...]] = (
    inventory_case(1, "FAITHFUL_PARAPHRASE", (_carried("C01"), _inventory(
        held("PERMISSION", "may be borrowed", "loan period", "JDG-1"),
        held("TIMING", "three weeks", "21 days", "JDG-1"),
    ))),
    inventory_case(2, "FAITHFUL_PARAPHRASE", (
        prop("p1", "A member may hold at most four reservations at once.",
             (claim("JDG-1", RESERVATIONS, "maximum_active_reservations_per_member", "4"),)),
        _inventory(
            held("ACTOR", "a member", "per member", "JDG-1"),
            held("PERMISSION", "may hold", "active reservations", "JDG-1"),
            held("QUANTITY", ("at most", "four"), ("maximum", "4"), "JDG-1"),
            held("TIMING", "at once", "active", "JDG-1"),
        ))),
    inventory_case(3, "FAITHFUL_DECOMPOSITION", (_carried("C03"), _inventory(
        held("DESTINATION", "at the issue desk", "the issue desk", "JDG-1"),
        held("CONSEQUENCE", "recorded on the member's card", "recorded on the member's card",
             "JDG-2"),
    ))),
    inventory_case(4, "JOINTLY_COMPLETE_THREE_CLAIMS", (
        prop("p1", "A member may renew a loan twice, online, if nobody else has reserved the "
             "book.",
             (claim("JDG-1", "Loan renewals", "maximum_renewals_per_member", "2"),
              claim("JDG-2", "Loan renewals", "renewal_channel", "online"),
              claim("JDG-3", "Loan renewals", "renewal_condition",
                    "no other member has reserved the book"))),
        _inventory(
            held("ACTOR", "a member", "per member", "JDG-1"),
            held("PERMISSION", "may renew", "renewals", "JDG-1"),
            held("REPETITION", "twice", "2", "JDG-1"),
            held("CHANNEL", "online", "online", "JDG-2"),
            held("CONDITION", "nobody else has reserved", "no other member has reserved",
                 "JDG-3"),
        ))),
    inventory_case(5, "MISSING_CONDITION", (_carried("C05"), _inventory(
        lost("ACTOR", "a member", ACTOR_MEMBER, AS_RENEWER),
        held("PERMISSION", "may renew", "renewals", "JDG-1"),
        held("REPETITION", "twice", "2", "JDG-1"),
        held("CHANNEL", "online", "online", "JDG-2"),
        lost("CONDITION", "if nobody else has reserved the book", *_v2_groups("C05")),
    ))),
    inventory_case(6, "MISSING_CONSEQUENCE", (_carried("C06"), _inventory(
        held("CONDITION", "returned late", "late fine", "JDG-1"),
        held("QUANTITY", "0.20 EUR per day", "0.20 EUR per day", "JDG-1"),
        lost("CONSEQUENCE", ("borrowing is paused", "until the fine is paid"),
             *_v2_groups("C06")),
    ))),
    inventory_case(7, "MISSING_EXCEPTION", (_carried("C07"), _inventory(
        held("TIMING", "three weeks", "3 weeks", "JDG-1"),
        lost("EXCEPTION", ("except reference books", "cannot be borrowed"),
             *_v2_groups("C07")),
    ))),
    inventory_case(8, "MISSING_SECOND_SENTENCE", (_carried("C08"), _inventory(
        held("TIMING", "held for five days", ("reservation hold", "5 days"), "JDG-1"),
        lost("CONSEQUENCE", ("lapses", "passes to the next member"), *_v2_groups("C08")),
    ))),
    inventory_case(9, "MISSING_SECOND_CLAUSE", (_carried("C09"), _inventory(
        held("ACTOR", "members", "membership", "JDG-1"),
        lost("ELIGIBILITY", "under 16", SIXTEEN, AGE_LIMIT),
        held("OBLIGATION", "need a guardian's signature", "a guardian's signature", "JDG-1"),
        lost("QUANTITY", "at most five items", *_v2_groups("C09")),
    ))),
    inventory_case(10, "UNSUPPORTED_ADDITION", (
        prop("p1", "A damage report made more than 7 days after return is refused.",
             (claim("JDG-1", DAMAGE, "late_damage_report",
                    "refused if made more than 7 days after return, and the member is "
                    "suspended"),)),
        _inventory(
            held("DEADLINE", "more than 7 days", "more than 7 days", "JDG-1"),
            held("TIME_ANCHOR", "after return", "after return", "JDG-1"),
            held("CONSEQUENCE", "is refused", "refused", "JDG-1"),
            added("CONSEQUENCE", "suspended", "JDG-1", *_v2_groups("C10")),
        ))),
    inventory_case(11, "CONTRADICTION", (_carried("C11"), _inventory(
        held("QUANTITY", "capped at 10 EUR per item", "10 EUR per item", "JDG-1"),
        clash("QUANTITY", "10 EUR", "15 EUR", "JDG-2", *_v2_groups("C11")),
    ))),
    inventory_case(12, "LEXICAL_OVERLAP_INCOMPLETE", (_carried("C12"), _inventory(
        held("CHANNEL", "by email", "by email", "JDG-1"),
        lost("CHANNEL", ("by post", "if unanswered after a week"), *_v2_groups("C12")),
    ))),
    inventory_case(13, "LEXICAL_OVERLAP_COMPLETE", (_carried("C13"), _inventory(
        held("PERMISSION", "can be kept", "loan period", "JDG-1"),
        held("TIMING", "a fortnight", "14 days", "JDG-1"),
        held("ELIGIBILITY", "children's books", "childrens book", "JDG-1"),
    ))),
    inventory_case(14, "LEXICAL_OVERLAP_COMPLETE", (_carried("C14"), _inventory(
        held("ACTOR", "members", "members", "JDG-1"),
        held("ELIGIBILITY", "over 65", "over 65", "JDG-1"),
        held("CONSEQUENCE", "pay no late fines", "waived", "JDG-1"),
    ))),
    inventory_case(15, "DEADLINE_VS_REFUSAL", (_carried("C15"), _inventory(
        held("OBLIGATION", "must be made", "damage report deadline", "JDG-1"),
        held("DEADLINE", "within 7 days", "7 days", "JDG-1"),
        lost("TIME_ANCHOR", "of return", FROM_RETURN),
        lost("CONSEQUENCE", "a later report is refused", *_v2_groups("C15")),
    ))),
    inventory_case(16, "ELIGIBILITY_VS_CONSEQUENCE", (_carried("C16"), _inventory(
        lost("ACTOR", "only members", ACTOR_MEMBER, AS_RESERVER),
        held("ELIGIBILITY", "no outstanding fines", "no outstanding fines", "JDG-1"),
        held("PERMISSION", "may reserve", "reservation eligibility", "JDG-1"),
        lost("CONSEQUENCE", "is cancelled", *_v2_groups("C16")),
    ))),
    inventory_case(17, "SUPPORT_DISPOSITION", (_carried("C17"), _inventory(
        held("TIMING", "three weeks", "21 days", "CLM-1"),
    )), (_carried("C17", "p2"), PropositionInventory("p2", (
        clash("TIMING", "two weeks", "21 days", "CLM-1", *_v2_groups("C17", "p2")),
    )))),
    inventory_case(18, "SUPPORT_DISPOSITION", (_carried("C18"), _inventory(
        held("TIMING", "three weeks", "21 days", "CLM-1"),
        lost("PERMISSION", ("can be extended", "once", "by phone"), *_v2_groups("C18")),
    ))),
    inventory_case(19, "ASSERT_SUPERSEDE_DISPOSITION", (_carried("C19"), _inventory(
        held("QUANTITY", "0.30 EUR per day", "0.30 EUR per day", "JDG-1"),
    ))),
    inventory_case(20, "ASSERT_SUPERSEDE_DISPOSITION", (_carried("C20"), _inventory(
        held("QUANTITY", "0.30 EUR per day", "0.30 EUR per day", "JDG-1"),
        lost("QUANTITY", "capped at 12 EUR per item", *_v2_groups("C20")),
    ))),
    inventory_case(21, "K_CREDIT_REGRESSION", (_carried("C21"), _inventory(
        held("OBLIGATION", "must be claimed", "claim deadline", "JDG-1"),
        held("DEADLINE", "within 48 hours", "48 hours", "JDG-1"),
        held("TIME_ANCHOR", "after the reservation start", "after reservation start", "JDG-1"),
        lost("CHANNEL", "in the app", IN_THE_APP),
        lost("CONSEQUENCE", "a later claim is refused", *_v2_groups("C21")),
        forbidden=DEADLINE_MISREAD,
    ))),
    inventory_case(22, "ASSERT_DISPOSITION", (_carried("C22"), _inventory(
        held("CONDITION", "outside opening hours", "after hours", "JDG-1"),
        held("DESTINATION", "the drop box", "the drop box", "JDG-1"),
        held("TIMING", ("checked in", "the next morning"), ("check in", "the next morning"),
             "JDG-2"),
    )), (
        prop("p2", "A member may borrow up to ten items at once.",
             (claim("JDG-3", LOANS, "maximum_loans_per_member",
                    "10 items at once, only with a valid photo ID"),)),
        PropositionInventory("p2", (
            held("ACTOR", "a member", "per member", "JDG-3"),
            held("PERMISSION", "may borrow", "maximum loans", "JDG-3"),
            held("QUANTITY", "up to ten", "10 items", "JDG-3"),
            held("TIMING", "at once", "at once", "JDG-3"),
            added("CONDITION", "photo id", "JDG-3", *_v2_groups("C22", "p2")),
        )))),
    inventory_case(23, "CONTRADICTION", (_carried("C23"), _inventory(
        held("PERMISSION", "may be returned", "return branch", "JDG-1"),
        clash("DESTINATION", "any branch", "only the branch that issued", "JDG-1",
              *_v2_groups("C23")),
    ))),
    inventory_case(24, "COMPLETE_CONDITION_AND_CONSEQUENCE", (
        prop("p1", "Members may print up to 20 pages a day free of charge; further pages cost "
             "0.10 EUR each.",
             (claim("JDG-1", "Printing", "free_print_quota_per_member",
                    "20 pages per day at no charge"),
              claim("JDG-2", "Printing", "additional_page_price_per_member",
                    "0.10 EUR per page beyond 20 pages in a day"))),
        _inventory(
            held("ACTOR", "members", "per member", "JDG-1", "JDG-2"),
            held("PERMISSION", "may print", "print quota", "JDG-1"),
            held("QUANTITY", "up to 20 pages a day", "20 pages per day", "JDG-1"),
            held("CONSEQUENCE", "free of charge", "no charge", "JDG-1"),
            held("CONDITION", "further pages", "beyond 20 pages", "JDG-2"),
            held("CONSEQUENCE", "0.10 EUR each", "0.10 EUR per page", "JDG-2"),
        ))),
    inventory_case(25, "COMPLETE_DEADLINE_AND_CONSEQUENCE", (_carried("C25"), _inventory(
        held("OBLIGATION", "must be confirmed", "confirmation deadline", "JDG-1"),
        held("DEADLINE", "at least 24 hours", "at least 24 hours", "JDG-1"),
        held("TIME_ANCHOR", "ahead", "before the booking", "JDG-1"),
        held("CONDITION", "unconfirmed booking", "unconfirmed booking", "JDG-2"),
        held("CONSEQUENCE", "is cancelled", "cancelled", "JDG-2"),
    ))),
)  # fmt: skip


def case_by_id(case_id: str) -> InventoryCase:
    (case,) = [c for c in CASES if c.case_id == case_id]
    return case


# --- the scorer -------------------------------------------------------------------------------


def score_completeness_report(
    case: InventoryCase, report: CompletenessReport | None
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
        items = region_items(verdict)
        for finding in expected.findings:
            if not identifies(items, finding.groups, statements[expected.proposition_id]):
                names = ", ".join(g.name for g in finding.groups)
                failures.append(
                    f"{expected.proposition_id}: no finding identifies the sealed "
                    f"{finding.name} assertion (groups: {names})"
                )
        stated = (*verdict.missing, *verdict.unsupported, *verdict.contradictory)
        for phrase in expected.forbidden:
            if any(mentions(item, phrase) for item in stated):
                failures.append(f"{expected.proposition_id}: forbidden interpretation {phrase!r}")
    return tuple(failures)


# --- one attempt through the production verifier (exam v2's runner, unchanged) -----------------


def executable(case: InventoryCase) -> CompletenessCase:
    """What the runner and the global gates read: the case id and the sealed request only."""
    return CompletenessCase(case.case_id, case.category, case.request, ())


def run_completeness_attempt(
    contestant: Contestant, case: InventoryCase, attempt: int, *, provider: Any
) -> CompletenessObservation:
    return run_v2_attempt(contestant, executable(case), attempt, provider=provider)


def score_completeness_attempt(
    observation: CompletenessObservation, case: InventoryCase, *, candidate: ModelIdentity
) -> tuple[str, ...]:
    return (
        *score_completeness_global_gates(observation, executable(case), candidate=candidate),
        *score_completeness_report(case, observation.report),
    )


def completeness_verdict(attempts: list[dict[str, Any]]) -> str:
    """PASS only when every case's every required run was recorded exactly once and passed."""
    required = {(c.case_id, n) for c in CASES for n in range(1, COMPLETENESS_RUNS_PER_CASE + 1)}
    recorded = [(a["case"], a["attempt"]) for a in attempts]
    complete = len(recorded) == len(required) == COMPLETENESS_CALL_BUDGET
    if not complete or set(recorded) != required:
        return "NOT CERTIFIED"
    return "PASS" if all(a["verdict"] == "PASS" for a in attempts) else "NOT CERTIFIED"


# --- exam identity ----------------------------------------------------------------------------

PRIOR_EXAMS: Final[tuple[PriorExam, ...]] = (
    *PRIOR_COMPLETENESS_EXAMS,
    PriorExam(
        exam_version="ie2-semantic-completeness-exam-v2",
        exam_sha256="c6f9ca5bfc8e4c8f4705bc49ab7c7c65477bda933920b5b6a817a80a7502338d",
        status="LIVE_NOT_CERTIFIED",
        superseded_by=COMPLETENESS_EXAM_VERSION,
        defect="sat live by openai/gpt-6-astra: NOT CERTIFIED 66/75 (evidence e1833d4). Its "
        "expected verdicts were hand-authored: C02 and C24 sealed COMPLETE though no claim "
        "states the member actor, C10 sealed OVERREACH though its claim also drops the "
        "'after return' anchor (INCOMPLETE takes precedence), and C22 p2 sealed OVERREACH "
        "with the C02 actor defect. Frozen unchanged; never re-scored",
    ),
)
"""Exams v1 (prepared, never sat) and v2 (sat, not certified) are history: never rewritten."""


def _group_document(group: MarkerGroup) -> dict[str, Any]:
    return {"name": group.name, "markers": list(group.markers), "synonyms": list(group.synonyms)}


def _case_document(case: InventoryCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "request": case.request.model_dump(mode="json"),
        "inventory": [
            {
                "proposition_id": i.proposition_id,
                "assertions": [
                    {
                        "kind": a.kind,
                        "status": a.status,
                        "stated": list(a.stated),
                        "claimed": list(a.claimed),
                        "by": list(a.by),
                        "groups": [_group_document(g) for g in a.groups],
                    }
                    for a in i.assertions
                ],
                "forbidden": list(i.forbidden),
            }
            for i in case.inventory
        ],
        "expected": [
            {
                "proposition_id": e.proposition_id,
                "verdict": e.verdict,
                "findings": [
                    {"name": f.name, "groups": [_group_document(g) for g in f.groups]}
                    for f in e.findings
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
                inventory_case,
                inventory_problems,
                derive_verdict,
                expectation,
                held,
                lost,
                added,
                clash,
                executable,
                render_request,
                run_completeness_attempt,
                score_completeness_report,
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
        "prior_exams": [
            {
                "exam_version": p.exam_version,
                "exam_sha256": p.exam_sha256,
                "status": p.status,
                "superseded_by": p.superseded_by,
            }
            for p in PRIOR_EXAMS
        ],
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
    """``NOT_CERTIFIED`` (never PASS), ``CURRENT`` (binds every exam-v3 field), ``SUPERSEDED``
    (a PASS on a prior exam) or ``NOT_BINDING`` (any other PASS, including every record of
    another task or format)."""
    if record.get("verdict") != "PASS":
        return "NOT_CERTIFIED"
    if record.get("record_format") != COMPLETENESS_CERTIFICATION_RECORD_FORMAT:
        return "NOT_BINDING"
    current = current_completeness_identity(
        ModelIdentity(provider=str(record.get("provider")), model=str(record.get("model")))
    )
    if current is not None and certificate_binds(record, **current):
        return "CURRENT"
    prior = {(p.exam_version, p.exam_sha256) for p in PRIOR_EXAMS}
    if (record.get("exam_version"), record.get("exam_sha256")) in prior:
        return "SUPERSEDED"
    return "NOT_BINDING"


# --- evidence integrity -----------------------------------------------------------------------


def completeness_evidence_problems(record: dict[str, Any]) -> tuple[str, ...]:
    """Re-derive a record from its own attempts. Any disagreement is a problem, never fixed."""
    if record.get("record_format") != COMPLETENESS_CERTIFICATION_RECORD_FORMAT:
        return ("not a semantic completeness certification record",)
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
        return (f"exam v3 is not sealed: {path} is absent",)
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
