"""The hidden answer key of locus validation v6 (design §6, §7, §8). Never model-visible.

Sealed as ``expectations.json`` before any live call and never edited afterwards.

**The concern oracle** is derived from G2 as clarified by the founder on 2026-09-30
(``2026-09-30-ie2-governed-concern-grain-clarification.md``), never from section count. A
concern lists the T1 documents it is formed from; several documents may form one concern (the
dense reservation, unlock-attempt, late-return-fee and service-credit concerns) and no document
forms two. Rules about quantity, limit, timing, retry timing, timeout, duration, expiry,
renewal, preconditions, repetition, effects, destination, deadlines and exceptions of one
concern are claims at its one address; nearby sections that share nouns but govern a different
act, entitlement, decision or record are different concerns.

It also holds the source-coverage map, the proposition inventory (per branch at T3), the
correction groups (1:1, N:1, 1:N, N:M in the held-out domain; the repeat and the changed basis
at T3), the pending-set locations per timepoint, the per-item expectations, the separations,
the cases and the timepoint-exact semantic questions.

Timepoints: ``T1`` and ``T2`` (every ledger); for the dense ledger also ``AGREED`` and
``DECLINED`` (after the scripted human's decisions, per branch) and ``T3-AGREE`` and
``T3-DECLINE`` (after the T3 delta in each branch).

The request path never imports this module (a test and a preflight gate enforce it).
"""

from __future__ import annotations

from typing import Final, Literal

from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_formation.source_coverage import (
    SentenceAccount,
    coverage_findings,
    source_sentences,
)
from foundry.experiments.locus_validation_v5 import expectations as v5
from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS, SEED_WORLDS
from foundry.experiments.locus_validation_v6.protocol import (
    EXPERIMENT_VERSION,
    LEDGERS,
    Branch,
    LedgerId,
)

__all__ = [
    "BANNED_FACETS",
    "CASES",
    "CONCERNS",
    "CORRECTIONS",
    "CRITICAL_CASES",
    "EXPECTED_ADDRESS_COUNTS",
    "EXPECTED_CONFLICTS",
    "EXPECTED_DISPOSITIONS",
    "EXPECTED_PENDING_SETS",
    "EXPECTED_SEPARATE",
    "ITEMS",
    "LIVE_CLAIMS",
    "PROPOSITIONS",
    "SEMANTIC_QUESTIONS",
    "SOURCE_COVERAGE",
    "STRUCTURAL_CHECKS",
    "TIMEPOINTS",
    "CaseExpectation",
    "Concern",
    "CorrectionExpectation",
    "ItemExpectation",
    "Proposition",
    "SemanticQuestion",
    "SeparateAddresses",
    "Timepoint",
    "adjudication_questions_document",
    "adjudication_questions_sha256",
    "concern_of_document",
    "expectations_document",
    "expectations_sha256",
    "source_coverage_document",
    "source_coverage_findings",
    "source_coverage_sha256",
    "timepoints_of",
]

Relation = Literal["SEED", "RESTATES", "EXTENDS", "CORRECTS", "NEW_CONCERN"]
Range = tuple[int, int]
Timepoint = Literal["T1", "T2", "AGREED", "DECLINED", "T3-AGREE", "T3-DECLINE"]
TIMEPOINTS: Final[tuple[Timepoint, ...]] = (
    "T1",
    "T2",
    "AGREED",
    "DECLINED",
    "T3-AGREE",
    "T3-DECLINE",
)
_BRANCH_TIMEPOINTS: Final[dict[Branch, tuple[Timepoint, Timepoint]]] = {
    "AGREE": ("AGREED", "T3-AGREE"),
    "DECLINE": ("DECLINED", "T3-DECLINE"),
}


def timepoints_of(ledger: LedgerId) -> tuple[Timepoint, ...]:
    return TIMEPOINTS if ledger == "dense" else ("T1", "T2")


class Concern(FrozenModel):
    """One governed concern: exactly one active address must hold all of its claims."""

    key: str
    ledger: LedgerId
    origin: Literal["MODEL_T1", "MODEL_T2", "AUTHOR_SEED"]
    documents: tuple[str, ...]
    """The documents whose one CREATE_ADDRESS forms the concern (it cites exactly these)."""


class Proposition(FrozenModel):
    id: str
    ledger: LedgerId
    document: str
    concern: str
    statement: str
    relation: Relation
    of: tuple[str, ...] = ()
    """The known propositions this one restates, or (with the rest of its group) replaces."""
    branch: Branch | None = None
    """Set only on T3 propositions: the branch whose current state they are judged against."""


class CorrectionExpectation(FrozenModel):
    """One correction: a set of obsolete propositions replaced by new ones at one concern."""

    id: str
    ledger: LedgerId
    at: Timepoint
    concern: str
    document: str
    cardinality: Literal["1:1", "N:1", "1:N", "N:M"]
    obsolete: tuple[str, ...]
    replacements: tuple[str, ...]
    outcome: Literal["PENDING", "SUPPRESSED_AS_DECLINED"]
    """At ``at``: one PENDING atomic correction set, or every member refused as a repeat of
    the DECLINED set of ``repeat_of``."""
    target_documents: tuple[str, ...]
    """The documents whose live claims (at the concern) the set may retire."""
    exact_targets: bool
    """Every live claim at the concern citing ``target_documents`` must be targeted, once."""
    repeat_of: str | None = None
    decided: dict[Branch, Literal["AGREED", "DECLINED"]] = {}
    """For a T2 correction of the dense ledger: its terminal status in each branch."""


class ItemExpectation(FrozenModel):
    """What the two calls of one delta must do with one revised document."""

    document: str
    ledger: LedgerId
    at: Timepoint
    binds: tuple[str, ...]
    creates: int
    new_live: dict[str, Range]
    """Range of new live claims citing the item, by concern; zero elsewhere."""
    held: dict[str, Range] = {}
    """Range of held (pending-set) ASSERT members citing the item, by concern; zero elsewhere."""
    support_documents: tuple[str, ...] = ()
    """Every live claim citing one of these documents at a bound concern (other than a target
    of the item's own correction) must receive an applied SUPPORTS_CLAIM citing the item."""


class SeparateAddresses(FrozenModel):
    case: str
    ledger: LedgerId
    a: str
    b: str


class CaseExpectation(FrozenModel):
    id: str
    title: str
    ledger: LedgerId
    structural: tuple[str, ...]
    semantic: tuple[str, ...]


class SemanticQuestion(FrozenModel):
    id: str
    case: str
    ledger: LedgerId
    after: Timepoint
    """The adjudicator sees exactly this ledger's frozen state at exactly this timepoint."""
    question: str


# ------------------------------------------------------------------ v5 regressions, carried


def _ledger_of(document: str) -> LedgerId:
    return DOCUMENTS[document].ledger


_V5_PROPOSITIONS: Final = tuple(
    Proposition(
        id=p.id,
        ledger=_ledger_of(p.document),
        document=p.document,
        concern=p.address,
        statement=p.statement,
        relation=p.relation,
        of=(p.of,) if p.of else (),
    )
    for p in v5.PROPOSITIONS
)
_V5_CONCERNS: Final = tuple(
    Concern(
        key=a.key,
        ledger=a.ledger,
        origin=a.origin,
        documents=(a.created_from,) if a.created_from else (),
    )
    for a in v5.ADDRESSES
)


# ------------------------------------------------------------------ the dense inventory


def _k(
    pid: str,
    document: str,
    concern: str,
    statement: str,
    relation: Relation = "SEED",
    of: tuple[str, ...] = (),
    branch: Branch | None = None,
) -> Proposition:
    return Proposition(
        id=f"K-{pid}",
        ledger="dense",
        document=f"K-{document}",
        concern=concern,
        statement=statement,
        relation=relation,
        of=tuple(f"K-{o}" for o in of),
        branch=branch,
    )


_RES: Final = "RESERVATION"
_UNL: Final = "UNLOCK"
_LATE: Final = "LATE-FEE"
_CLEAN: Final = "CLEANING-FEE"
_CREDIT: Final = "SERVICE-CREDIT"

_DENSE_T1: Final = (
    _k("RES-1", "BOOKING-T1", _RES, "a member reserves one specific vehicle for a fixed period "
       "before driving it"),
    _k("RES-2", "BOOKING-T1", _RES, "a reservation is made in the app and states its start and "
       "end time"),
    _k("RES-3", "BOOKING-T1", _RES, "a reservation may be made at most 14 days before its start"),
    _k("RES-4", "BOOKING-T1", _RES, "a reservation lasts at least 30 minutes"),
    _k("RES-5", "BOOKING-T1", _RES, "a reservation lasts no longer than 72 hours"),
    _k("RES-6", "BOOKING-T1", _RES, "a member may hold at most two reservations that have not "
       "yet started"),
    _k("RES-7", "HOLD-T1", _RES, "the reserved vehicle is kept for the member from the "
       "reservation start"),
    _k("RES-8", "HOLD-T1", _RES, "a reservation whose vehicle is not unlocked within 15 minutes "
       "after its start expires"),
    _k("RES-9", "HOLD-T1", _RES, "an expired reservation releases the vehicle to other members"),
    _k("RES-10", "PROLONG-T1", _RES, "a member may add time to a reservation that has already "
       "started"),
    _k("RES-11", "PROLONG-T1", _RES, "time is added from the trip screen of the app"),
    _k("RES-12", "PROLONG-T1", _RES, "time is added in steps of 30 minutes"),
    _k("RES-13", "PROLONG-T1", _RES, "time may be added only if no other reservation of the same "
       "vehicle begins within the added period"),
    _k("RES-14", "PROLONG-T1", _RES, "added time runs from the current end of the reservation"),
    _k("UNL-1", "UNLOCK-T1", _UNL, "the member unlocks the reserved vehicle by sending an unlock "
       "command from the app"),
    _k("UNL-2", "UNLOCK-T1", _UNL, "each command sent is one unlock attempt that opens the "
       "vehicle or fails"),
    _k("UNL-3", "UNLOCK-T1", _UNL, "at most five unlock attempts may be made for one reservation"),
    _k("UNL-4", "UNLOCK-T1", _UNL, "after the fifth failed attempt no further unlock command is "
       "sent and the member is directed to the support line"),
    _k("UNL-5", "UNLOCK-WAIT-T1", _UNL, "after a failed unlock attempt the app waits exactly "
       "10 seconds before the next command"),
    _k("UNL-6", "UNLOCK-WAIT-T1", _UNL, "the wait is the same for every attempt whatever its "
       "number"),
    _k("UNL-7", "UNLOCK-TIMEOUT-T1", _UNL, "an unlock command not confirmed within 20 seconds is "
       "treated as timed out"),
    _k("UNL-8", "UNLOCK-TIMEOUT-T1", _UNL, "a timed-out unlock command counts as one failed "
       "unlock attempt"),
    _k("LATE-1", "LATE-T1", _LATE, "a vehicle returned after the end of its reservation is "
       "charged a late-return fee"),
    _k("LATE-2", "LATE-T1", _LATE, "no fee is charged for a return within 10 minutes after the "
       "reservation end"),
    _k("LATE-3", "LATE-T1", _LATE, "beyond those 10 minutes the fee is 0.50 EUR per started "
       "minute"),
    _k("LATE-4", "LATE-T1", _LATE, "the late-return fee for one reservation does not exceed "
       "60 EUR"),
    _k("LATE-5", "LATE-WAIVER-T1", _LATE, "the late-return fee is not charged when the delay was "
       "caused by a vehicle fault"),
    _k("LATE-6", "LATE-WAIVER-T1", _LATE, "that waiver applies only if the fault was reported in "
       "the app before the reservation ended"),
    _k("CLEAN-1", "CLEANING-T1", _CLEAN, "a member who leaves rubbish or soiling in a vehicle is "
       "charged a cleaning fee of 30 EUR"),
    _k("CLEAN-2", "CLEANING-T1", _CLEAN, "the cleaning fee is charged only if the next member "
       "reports the vehicle's state with a photo within 15 minutes after unlocking it"),
    _k("CREDIT-1", "CREDIT-T1", _CREDIT, "a member whose reserved vehicle is missing or cannot "
       "be driven at the reservation start receives a service credit of 10 EUR"),
    _k("CREDIT-2", "CREDIT-T1", _CREDIT, "the service credit is added to the member's wallet and "
       "never paid out to a card"),
    _k("CREDIT-3", "CREDIT-CLAIM-T1", _CREDIT, "the service credit must be claimed in the app "
       "within 48 hours after the reservation start"),
    _k("CREDIT-4", "CREDIT-CLAIM-T1", _CREDIT, "a later claim for the service credit is refused"),
    _k("CREDIT-5", "CREDIT-CLAIM-T1", _CREDIT, "a claim names the reservation and includes a "
       "photo of the vehicle"),
    _k("BILL-1", "BILLING-T1", "BILLING-RUN", "a member's fees of one day are charged to the "
       "payment card in one billing run"),
    _k("BILL-2", "BILLING-T1", "BILLING-RUN", "the billing run takes place every night at 02:00"),
    _k("BILL-3", "BILLING-T1", "BILLING-RUN", "a declined charge is attempted again in the next "
       "night's billing run"),
    _k("SUSP-1", "SUSPENSION-T1", "SUSPENSION", "a suspended member is told about the "
       "suspension by e-mail"),
    _k("SUSP-2", "SUSPENSION-T1", "SUSPENSION", "an account whose charge was declined in three "
       "consecutive billing runs is suspended"),
    _k("SUSP-3", "SUSPENSION-T1", "SUSPENSION", "the suspension is lifted automatically once the "
       "outstanding amount is paid"),
    _k("TRIP-1", "TRIP-T1", "TRIP-RECORDS", "during a reservation the vehicle records its "
       "location once every minute as a trip record"),
    _k("TRIP-2", "TRIP-T1", "TRIP-RECORDS", "trip records are kept for 90 days after the "
       "reservation ends"),
    _k("TRIP-3", "TRIP-T1", "TRIP-RECORDS", "after 90 days a trip record is deleted"),
    _k("MEMB-1", "MEMBERSHIP-T1", "MEMBERSHIP", "a person becomes a member only after the "
       "membership application is approved"),
    _k("MEMB-2", "MEMBERSHIP-T1", "MEMBERSHIP", "applications are submitted in the app with a "
       "photo of the driving licence"),
    _k("MEMB-3", "MEMBERSHIP-T1", "MEMBERSHIP", "an application is approved only if the "
       "applicant is at least 21 years old"),
    _k("MEMB-4", "MEMBERSHIP-T1", "MEMBERSHIP", "an application is approved only if the "
       "applicant has held a full driving licence for at least two years"),
    _k("MEMB-5", "MEMBERSHIP-T1", "MEMBERSHIP", "every application is decided within two "
       "working days"),
)  # fmt: skip

_UNL_OLD: Final = ("UNL-5", "UNL-6")
_DENSE_T2: Final = (
    _k("CLEAN-1C", "CLEANING-T2", _CLEAN, "the cleaning fee is 40 EUR", "CORRECTS", ("CLEAN-1",)),
    _k("CLEAN-2R", "CLEANING-T2", _CLEAN, "the fee needs the next member's photo report within "
       "15 minutes after unlocking", "RESTATES", ("CLEAN-2",)),
    _k("LATE-1R", "LATE-T2", _LATE, "a vehicle returned after its reservation end is charged a "
       "late-return fee", "RESTATES", ("LATE-1",)),
    _k("LATE-7", "LATE-T2", _LATE, "the late-return fee is a flat 25 EUR for any delay, however "
       "short", "CORRECTS", ("LATE-2", "LATE-3")),
    _k("LATE-4R", "LATE-T2", _LATE, "the late-return fee for one reservation does not exceed "
       "60 EUR", "RESTATES", ("LATE-4",)),
    _k("CREDIT-6", "CREDIT-T2", _CREDIT, "the service credit for an unavailable vehicle is 10 EUR "
       "when the reservation lasts up to four hours", "CORRECTS", ("CREDIT-1",)),
    _k("CREDIT-7", "CREDIT-T2", _CREDIT, "the service credit is 20 EUR when the reservation lasts "
       "longer than four hours", "CORRECTS", ("CREDIT-1",)),
    _k("CREDIT-2R", "CREDIT-T2", _CREDIT, "the service credit goes to the wallet, never to a "
       "card", "RESTATES", ("CREDIT-2",)),
    _k("UNL-9", "UNLOCK-WAIT-T2", _UNL, "after the first failed unlock attempt the app waits "
       "5 seconds before the next command", "CORRECTS", _UNL_OLD),
    _k("UNL-10", "UNLOCK-WAIT-T2", _UNL, "after every further failed attempt the wait is twice "
       "the previous wait", "CORRECTS", _UNL_OLD),
    _k("UNL-11", "UNLOCK-WAIT-T2", _UNL, "no wait between unlock attempts is longer than "
       "40 seconds", "CORRECTS", _UNL_OLD),
    _k("TRIP-1R", "TRIP-T2", "TRIP-RECORDS", "location recorded every minute as a trip record",
       "RESTATES", ("TRIP-1",)),
    _k("TRIP-2R", "TRIP-T2", "TRIP-RECORDS", "trip records kept 90 days after the reservation "
       "ends", "RESTATES", ("TRIP-2",)),
    _k("TRIP-3R", "TRIP-T2", "TRIP-RECORDS", "trip records deleted after 90 days", "RESTATES",
       ("TRIP-3",)),
    _k("TRIP-4", "TRIP-T2", "TRIP-RECORDS", "a member may download the trip records of their own "
       "reservations from the app", "EXTENDS"),
)  # fmt: skip

_DENSE_T3: Final = (
    # AGREE branch: the redelivered unlock-wait text restates the agreed claims; the cleaning
    # fee changes again (40 -> 35 EUR).
    _k("UNL-9-T3A", "UNLOCK-WAIT-T3", _UNL, "first wait 5 seconds", "RESTATES", ("UNL-9",),
       "AGREE"),
    _k("UNL-10-T3A", "UNLOCK-WAIT-T3", _UNL, "each further wait doubles", "RESTATES",
       ("UNL-10",), "AGREE"),
    _k("UNL-11-T3A", "UNLOCK-WAIT-T3", _UNL, "no wait longer than 40 seconds", "RESTATES",
       ("UNL-11",), "AGREE"),
    _k("CLEAN-1E-T3A", "CLEANING-T3", _CLEAN, "the cleaning fee is 35 EUR", "CORRECTS",
       ("CLEAN-1C",), "AGREE"),
    _k("CLEAN-2-T3A", "CLEANING-T3", _CLEAN, "the fee needs the next member's photo report "
       "within 15 minutes after unlocking", "RESTATES", ("CLEAN-2",), "AGREE"),
    # DECLINE branch: the declined unlock-wait correction is proposed again on the same basis;
    # the cleaning fee changes on a new basis (30 -> 35 EUR).
    _k("UNL-9-T3D", "UNLOCK-WAIT-T3", _UNL, "after the first failed unlock attempt the app waits "
       "5 seconds before the next command", "CORRECTS", _UNL_OLD, "DECLINE"),
    _k("UNL-10-T3D", "UNLOCK-WAIT-T3", _UNL, "after every further failed attempt the wait is "
       "twice the previous wait", "CORRECTS", _UNL_OLD, "DECLINE"),
    _k("UNL-11-T3D", "UNLOCK-WAIT-T3", _UNL, "no wait between unlock attempts is longer than "
       "40 seconds", "CORRECTS", _UNL_OLD, "DECLINE"),
    _k("CLEAN-1E-T3D", "CLEANING-T3", _CLEAN, "the cleaning fee is 35 EUR", "CORRECTS",
       ("CLEAN-1",), "DECLINE"),
    _k("CLEAN-2-T3D", "CLEANING-T3", _CLEAN, "the fee needs the next member's photo report "
       "within 15 minutes after unlocking", "RESTATES", ("CLEAN-2",), "DECLINE"),
)  # fmt: skip

PROPOSITIONS: Final[tuple[Proposition, ...]] = (
    *_V5_PROPOSITIONS,
    *_DENSE_T1,
    *_DENSE_T2,
    *_DENSE_T3,
)
_BY_ID: Final = {p.id: p for p in PROPOSITIONS}


def _dense_concern(key: str, *documents: str) -> Concern:
    return Concern(
        key=key, ledger="dense", origin="MODEL_T1", documents=tuple(f"K-{d}" for d in documents)
    )


CONCERNS: Final[tuple[Concern, ...]] = (
    *_V5_CONCERNS,
    _dense_concern(_RES, "BOOKING-T1", "HOLD-T1", "PROLONG-T1"),
    _dense_concern(_UNL, "UNLOCK-T1", "UNLOCK-WAIT-T1", "UNLOCK-TIMEOUT-T1"),
    _dense_concern(_LATE, "LATE-T1", "LATE-WAIVER-T1"),
    _dense_concern(_CLEAN, "CLEANING-T1"),
    _dense_concern(_CREDIT, "CREDIT-T1", "CREDIT-CLAIM-T1"),
    _dense_concern("BILLING-RUN", "BILLING-T1"),
    _dense_concern("SUSPENSION", "SUSPENSION-T1"),
    _dense_concern("TRIP-RECORDS", "TRIP-T1"),
    _dense_concern("MEMBERSHIP", "MEMBERSHIP-T1"),
)
"""Every governed concern. The dense grain: 15 T1 sections, 9 concerns (design §6.1)."""


def concern_of_document(document: str) -> str | None:
    """The concern a forming document belongs to (``None`` for a revision or a seed doc)."""
    for concern in CONCERNS:
        if document in concern.documents:
            return concern.key
    return None


# ------------------------------------------------------------------ source coverage

_EXAMPLE: Final = "illustrative example that restates listed rules and adds none"
_CONTEXT: Final = "context: describes a circumstance and states no rule"
_RATIONALE: Final = "rationale: says why the rules exist and adds none"


def _accounts(document: str, *entries: tuple[str, ...] | str) -> tuple[SentenceAccount, ...]:
    """One entry per sentence of ``document``, in order: proposition ids or a reason."""
    return tuple(
        SentenceAccount(sentence=sentence, propositions=entry)
        if isinstance(entry, tuple)
        else SentenceAccount(sentence=sentence, non_operative_reason=entry)
        for sentence, entry in zip(source_sentences(DOCUMENTS[document].text), entries, strict=True)
    )


def _ids(*pids: str) -> tuple[str, ...]:
    return tuple(f"K-{p}" for p in pids)


_E: Final = _EXAMPLE

_DENSE_COVERAGE: Final[dict[str, tuple[SentenceAccount, ...]]] = {
    "K-BOOKING-T1": _accounts("K-BOOKING-T1", _ids("RES-1"), _ids("RES-2"), _ids("RES-3"),
                              _ids("RES-4"), _ids("RES-5"), _ids("RES-6"), _E, _E, _E),
    "K-HOLD-T1": _accounts("K-HOLD-T1", _ids("RES-7"), _ids("RES-8"), _ids("RES-9"), _E, _E, _E),
    "K-PROLONG-T1": _accounts("K-PROLONG-T1", _CONTEXT, _ids("RES-10"), _ids("RES-11"),
                              _ids("RES-12"), _ids("RES-13"), _ids("RES-14"), _E, _E, _E),
    "K-UNLOCK-T1": _accounts("K-UNLOCK-T1", _ids("UNL-1"), _ids("UNL-2"), _ids("UNL-3"),
                             _ids("UNL-4"), _E, _E, _E),
    "K-UNLOCK-WAIT-T1": _accounts("K-UNLOCK-WAIT-T1", _RATIONALE, _RATIONALE, _ids("UNL-5"),
                                  _ids("UNL-6"), _E, _E),
    "K-UNLOCK-TIMEOUT-T1": _accounts("K-UNLOCK-TIMEOUT-T1", _CONTEXT, _ids("UNL-7"),
                                     _ids("UNL-8"), _E, _E),
    "K-LATE-T1": _accounts("K-LATE-T1", _RATIONALE, _ids("LATE-1"), _ids("LATE-2"),
                           _ids("LATE-3"), _ids("LATE-4"), _E, _E, _E),
    "K-LATE-WAIVER-T1": _accounts("K-LATE-WAIVER-T1", _ids("LATE-5"), _ids("LATE-6"), _E, _E, _E),
    "K-CLEANING-T1": _accounts("K-CLEANING-T1", _ids("CLEAN-1"), _ids("CLEAN-2"), _E, _E, _E),
    "K-CREDIT-T1": _accounts("K-CREDIT-T1", _CONTEXT, _ids("CREDIT-1"), _ids("CREDIT-2"), _E, _E),
    "K-CREDIT-CLAIM-T1": _accounts("K-CREDIT-CLAIM-T1", _ids("CREDIT-3"), _ids("CREDIT-4"),
                                   _ids("CREDIT-5"), _E, _E),
    "K-BILLING-T1": _accounts("K-BILLING-T1", _ids("BILL-1"), _ids("BILL-2"), _ids("BILL-3"),
                              _E, _E, _E),
    "K-SUSPENSION-T1": _accounts("K-SUSPENSION-T1", _ids("SUSP-1"), _ids("SUSP-2"),
                                 _ids("SUSP-3"), _E, _E),
    "K-TRIP-T1": _accounts("K-TRIP-T1", _RATIONALE, _ids("TRIP-1"), _ids("TRIP-2"),
                           _ids("TRIP-3"), _E),
    "K-MEMBERSHIP-T1": _accounts("K-MEMBERSHIP-T1", _ids("MEMB-1"), _ids("MEMB-2"),
                                 _ids("MEMB-3", "MEMB-4"), _ids("MEMB-5"), _E, _E),
    "K-CLEANING-T2": _accounts("K-CLEANING-T2", _ids("CLEAN-1C"), _ids("CLEAN-2R"), _E, _E, _E),
    "K-LATE-T2": _accounts("K-LATE-T2", _RATIONALE, _ids("LATE-1R"), _ids("LATE-7"),
                           _ids("LATE-4R"), _E, _E),
    "K-CREDIT-T2": _accounts("K-CREDIT-T2", _CONTEXT, _ids("CREDIT-6"), _ids("CREDIT-7"),
                             _ids("CREDIT-2R"), _E, _E),
    "K-UNLOCK-WAIT-T2": _accounts("K-UNLOCK-WAIT-T2", _RATIONALE, _RATIONALE, _ids("UNL-9"),
                                  _ids("UNL-10"), _ids("UNL-11"), _E, _E),
    "K-TRIP-T2": _accounts("K-TRIP-T2", _RATIONALE, _ids("TRIP-1R"), _ids("TRIP-2R"),
                           _ids("TRIP-3R"), _ids("TRIP-4"), _E),
    "K-UNLOCK-WAIT-T3": _accounts("K-UNLOCK-WAIT-T3", _RATIONALE, _RATIONALE,
                                  _ids("UNL-9-T3A", "UNL-9-T3D"), _ids("UNL-10-T3A", "UNL-10-T3D"),
                                  _ids("UNL-11-T3A", "UNL-11-T3D"), _E, _E),
    "K-CLEANING-T3": _accounts("K-CLEANING-T3", _ids("CLEAN-1E-T3A", "CLEAN-1E-T3D"),
                               _ids("CLEAN-2-T3A", "CLEAN-2-T3D"), _E, _E, _E),
}  # fmt: skip
"""Every sentence of every T3 document carries both branches' propositions: the same sentence
is judged against the branch's own current state."""

SOURCE_COVERAGE: Final[dict[str, tuple[SentenceAccount, ...]]] = {
    **v5.SOURCE_COVERAGE,
    **_DENSE_COVERAGE,
}
"""Every sentence of every document, accounted for. Sealed; ``prepare`` refuses a gap."""


def source_coverage_findings() -> tuple[str, ...]:
    findings: list[str] = []
    seed_claims = {c.key: c.document for w in SEED_WORLDS.values() for a in w for c in a.claims}
    placed = {p.id: p.document for p in PROPOSITIONS} | seed_claims
    for key, doc in DOCUMENTS.items():
        accounts = SOURCE_COVERAGE.get(key)
        if accounts is None:
            findings.append(f"UNMAPPED_DOCUMENT: {key}")
            continue
        findings += [f"{key}: {f}" for f in coverage_findings(doc.text, accounts)]
        carried = {pid for a in accounts for pid in a.propositions}
        for pid in sorted(carried):
            if placed.get(pid) != key:
                findings.append(f"{key}: UNKNOWN_PROPOSITION: {pid}")
        for pid, document in placed.items():
            if document == key and pid not in carried:
                findings.append(f"{key}: UNSOURCED_PROPOSITION: {pid}")
    for key in SOURCE_COVERAGE:
        if key not in DOCUMENTS:
            findings.append(f"UNKNOWN_DOCUMENT: {key}")
    return tuple(findings)


def source_coverage_document() -> dict[str, object]:
    return {
        key: [a.model_dump(mode="json") for a in accounts]
        for key, accounts in SOURCE_COVERAGE.items()
    }


def source_coverage_sha256() -> str:
    return canonical_sha256(source_coverage_document())


# ------------------------------------------------------------------ corrections


def _cardinality(obsolete: int, replacements: int) -> Literal["1:1", "N:1", "1:N", "N:M"]:
    if obsolete == 1:
        return "1:1" if replacements == 1 else "1:N"
    return "N:1" if replacements == 1 else "N:M"


def _correction(
    cid: str,
    ledger: LedgerId,
    at: Timepoint,
    concern: str,
    document: str,
    obsolete: tuple[str, ...],
    replacements: tuple[str, ...],
    target_documents: tuple[str, ...],
    *,
    exact_targets: bool,
    outcome: Literal["PENDING", "SUPPRESSED_AS_DECLINED"] = "PENDING",
    repeat_of: str | None = None,
    decided: bool = False,
) -> CorrectionExpectation:
    return CorrectionExpectation(
        id=cid,
        ledger=ledger,
        at=at,
        concern=concern,
        document=document,
        cardinality=_cardinality(len(obsolete), len(replacements)),
        obsolete=obsolete,
        replacements=replacements,
        outcome=outcome,
        target_documents=target_documents,
        exact_targets=exact_targets,
        repeat_of=repeat_of,
        decided={"AGREE": "AGREED", "DECLINE": "DECLINED"} if decided else {},
    )


CORRECTIONS: Final[tuple[CorrectionExpectation, ...]] = (
    _correction("X0-WEIGHT", "core", "T2", "WEIGHT", "WEIGHT-T2", ("WEIGHT-1",), ("WEIGHT-1C",),
                ("WEIGHT-T1",), exact_targets=False),
    _correction("X1-ONE-TO-ONE", "dense", "T2", _CLEAN, "K-CLEANING-T2", _ids("CLEAN-1"),
                _ids("CLEAN-1C"), ("K-CLEANING-T1",), exact_targets=False, decided=True),
    _correction("X2-MANY-TO-ONE", "dense", "T2", _LATE, "K-LATE-T2", _ids("LATE-2", "LATE-3"),
                _ids("LATE-7"), ("K-LATE-T1",), exact_targets=False, decided=True),
    _correction("X3-ONE-TO-MANY", "dense", "T2", _CREDIT, "K-CREDIT-T2", _ids("CREDIT-1"),
                _ids("CREDIT-6", "CREDIT-7"), ("K-CREDIT-T1",), exact_targets=False,
                decided=True),
    _correction("X4-MANY-TO-MANY", "dense", "T2", _UNL, "K-UNLOCK-WAIT-T2", _ids(*_UNL_OLD),
                _ids("UNL-9", "UNL-10", "UNL-11"), ("K-UNLOCK-WAIT-T1",), exact_targets=True,
                decided=True),
    _correction("Z4-REPEAT-SUPPRESSED", "dense", "T3-DECLINE", _UNL, "K-UNLOCK-WAIT-T3",
                _ids(*_UNL_OLD), _ids("UNL-9-T3D", "UNL-10-T3D", "UNL-11-T3D"),
                ("K-UNLOCK-WAIT-T1",), exact_targets=True, outcome="SUPPRESSED_AS_DECLINED",
                repeat_of="X4-MANY-TO-MANY"),
    _correction("Z5-CHANGED-BASIS-DECLINE", "dense", "T3-DECLINE", _CLEAN, "K-CLEANING-T3",
                _ids("CLEAN-1"), _ids("CLEAN-1E-T3D"), ("K-CLEANING-T1",), exact_targets=False),
    _correction("Z5-CHANGED-BASIS-AGREE", "dense", "T3-AGREE", _CLEAN, "K-CLEANING-T3",
                _ids("CLEAN-1C"), _ids("CLEAN-1E-T3A"), ("K-CLEANING-T2",), exact_targets=True),
)  # fmt: skip
"""Structural target law: every SUPERSEDE of a set targets a live claim at the concern citing
one of ``target_documents``; the distinct targets number between 1 and ``len(obsolete)``
(a model may state two obsolete propositions in one claim) and, when ``exact_targets``, are
every such claim. Which claims they are, and what the replacements say, is judged
semantically."""


def _applied(group: CorrectionExpectation, at: Timepoint) -> bool:
    """Is ``group`` applied in the state at ``at``?"""
    return bool(group.decided) and at in _BRANCH_TIMEPOINTS["AGREE"]


# ------------------------------------------------------------------ pending sets and counts


def _pending_at(ledger: LedgerId, at: Timepoint) -> tuple[str, ...]:
    return tuple(
        sorted(
            g.concern
            for g in CORRECTIONS
            if g.ledger == ledger and g.outcome == "PENDING" and g.at == at
        )
    )


EXPECTED_PENDING_SETS: Final[dict[LedgerId, dict[Timepoint, tuple[str, ...]]]] = {
    ledger: {at: _pending_at(ledger, at) for at in timepoints_of(ledger)} for ledger in LEDGERS
}
"""The concerns holding exactly one PENDING correction set at each timepoint; none elsewhere.
A decision of the scripted human resolves every T2 set (AGREED / DECLINED); T3's are new."""

EXPECTED_ADDRESS_COUNTS: Final[dict[LedgerId, dict[Timepoint, int]]] = {
    **{ledger: {"T1": t1, "T2": t2} for ledger, (t1, t2) in v5.EXPECTED_ADDRESS_COUNTS.items()},
    "dense": dict.fromkeys(TIMEPOINTS, 9),
}
"""Active in-scope addresses, exactly. Any other count is a duplicate or a merge."""


def _in(p: Proposition, at: Timepoint) -> bool:
    """Is ``p``'s document part of the state at ``at``?"""
    t = DOCUMENTS[p.document].t
    if t == 1:
        return True
    if t == 2:
        return at != "T1"
    return p.branch is not None and at == f"T3-{p.branch}"


def _group_of(p: Proposition) -> CorrectionExpectation | None:
    for g in CORRECTIONS:
        if p.id in g.replacements and g.ledger == p.ledger:
            return g
    return None


def _retired(pid: str, at: Timepoint) -> bool:
    return any(pid in g.obsolete and _applied(g, at) for g in CORRECTIONS)


def _current(p: Proposition, at: Timepoint) -> bool:
    """Is ``p`` stated by a live claim at ``at``?"""
    if not _in(p, at) or p.relation == "RESTATES" or _retired(p.id, at):
        return False
    if p.relation == "CORRECTS":
        group = _group_of(p)
        return group is not None and _applied(group, at)
    return True


def _live_range(ledger: LedgerId, concern: str, at: Timepoint) -> Range:
    """Per document: at least one and at most one live claim per current proposition."""
    per_document: dict[str, int] = {}
    for p in PROPOSITIONS:
        if p.ledger == ledger and p.concern == concern and _current(p, at):
            per_document[p.document] = per_document.get(p.document, 0) + 1
    return (len(per_document), sum(per_document.values()))


LIVE_CLAIMS: Final[dict[str, Range]] = {
    f"{c.ledger}/{c.key}/{at}": _live_range(c.ledger, c.key, at)
    for c in CONCERNS
    for at in timepoints_of(c.ledger)
    if c.origin != "AUTHOR_SEED" and not (c.origin == "MODEL_T2" and at == "T1")
}
"""Live claims per concern and timepoint (``ledger/concern/timepoint``), as a sealed range."""
LIVE_CLAIMS["conflict/SESSION/T1"] = (2, 2)
LIVE_CLAIMS["conflict/SESSION/T2"] = (2, 2)


# ------------------------------------------------------------------ per-item expectations


def _items_at(document: str, at: Timepoint, support: tuple[str, ...] = ()) -> ItemExpectation:
    props = [p for p in PROPOSITIONS if p.document == document and _in(p, at)]
    binds = sorted({p.concern for p in props if p.relation != "NEW_CONCERN"})
    creates = len({p.concern for p in props if p.relation == "NEW_CONCERN"})
    new_live: dict[str, Range] = {}
    held: dict[str, Range] = {}
    for concern in sorted({p.concern for p in props}):
        adds = [
            p for p in props if p.concern == concern and p.relation in ("EXTENDS", "NEW_CONCERN")
        ]
        if adds:
            new_live[concern] = (1, len(adds))
        corrects = [p for p in props if p.concern == concern and p.relation == "CORRECTS"]
        group = _group_of(corrects[0]) if corrects else None
        if group is not None and group.outcome == "PENDING":
            held[concern] = (1, len(corrects))
    return ItemExpectation(
        document=document,
        ledger=DOCUMENTS[document].ledger,
        at=at,
        binds=tuple(binds),
        creates=creates,
        new_live=new_live,
        held=held,
        support_documents=support,
    )


ITEMS: Final[tuple[ItemExpectation, ...]] = (
    _items_at("PICKUP-T2", "T2", ("PICKUP-T1",)),
    _items_at("LABEL-T2", "T2"),
    _items_at("WEIGHT-T2", "T2"),
    _items_at("ATTEMPTS-T2", "T2"),
    _items_at("LATE-NOTE-T2", "T2"),
    _items_at("H-T9", "T2", ("H-T1",)),
    _items_at("CANCEL-NOTE-T2", "T2"),
    _items_at("HANDBOOK-T2", "T2"),
    _items_at("FAQ-T2", "T2"),
    _items_at("RETURNS-NOTE-T2", "T2"),
    _items_at("K-CLEANING-T2", "T2", ("K-CLEANING-T1",)),
    _items_at("K-LATE-T2", "T2", ("K-LATE-T1",)),
    _items_at("K-CREDIT-T2", "T2", ("K-CREDIT-T1",)),
    _items_at("K-UNLOCK-WAIT-T2", "T2"),
    _items_at("K-TRIP-T2", "T2", ("K-TRIP-T1",)),
    _items_at("K-UNLOCK-WAIT-T3", "T3-AGREE", ("K-UNLOCK-WAIT-T2",)),
    _items_at("K-CLEANING-T3", "T3-AGREE", ("K-CLEANING-T1",)),
    _items_at("K-UNLOCK-WAIT-T3", "T3-DECLINE"),
    _items_at("K-CLEANING-T3", "T3-DECLINE", ("K-CLEANING-T1",)),
)
"""Every revised document per timepoint. T1 formation is checked per concern (``CONCERNS``)."""


# ------------------------------------------------------------------ separation and governance

EXPECTED_SEPARATE: Final[tuple[SeparateAddresses, ...]] = (
    *(
        SeparateAddresses(case=s.case, ledger=s.ledger, a=s.a, b=s.b)
        for s in v5.EXPECTED_SEPARATE
    ),
    SeparateAddresses(case="S1-LATE-VS-CLEANING", ledger="dense", a=_LATE, b=_CLEAN),
    SeparateAddresses(case="S2-FEES-VS-BILLING", ledger="dense", a=_LATE, b="BILLING-RUN"),
    SeparateAddresses(case="S2-FEES-VS-BILLING", ledger="dense", a=_CLEAN, b="BILLING-RUN"),
    SeparateAddresses(case="S3-BILLING-VS-SUSPENSION", ledger="dense", a="BILLING-RUN",
                      b="SUSPENSION"),
    SeparateAddresses(case="S4-RESERVATION-VS-UNLOCK", ledger="dense", a=_RES, b=_UNL),
    SeparateAddresses(case="S5-RESERVATION-VS-TRIP-RECORDS", ledger="dense", a=_RES,
                      b="TRIP-RECORDS"),
    SeparateAddresses(case="S6-CREDIT-VS-LATE-FEE", ledger="dense", a=_CREDIT, b=_LATE),
)  # fmt: skip

EXPECTED_CONFLICTS: Final[dict[LedgerId, tuple[tuple[str, str], ...]]] = {
    **{ledger: pairs for ledger, pairs in v5.EXPECTED_CONFLICTS.items()},
    "dense": (),
}

BANNED_FACETS: Final = v5.BANNED_FACETS


# ------------------------------------------------------------------ dispositions


def _disposition(p: Proposition) -> str:
    if p.relation == "RESTATES":
        return "SUPPORTS_CLAIM"
    if p.relation != "CORRECTS":
        return "ASSERT_CLAIM"
    group = _group_of(p)
    carries = group is None or len(group.replacements) <= len(group.obsolete)
    return "ASSERT_CLAIM + SUPERSEDE" if carries else "ASSERT_CLAIM (+ SUPERSEDE)"


EXPECTED_DISPOSITIONS: Final[dict[str, str]] = {p.id: _disposition(p) for p in PROPOSITIONS}
"""The sealed disposition of every proposition. ``ASSERT_CLAIM + SUPERSEDE`` carries at least
one SUPERSEDE; in a group with more replacements than obsolete claims each replacement is an
``ASSERT_CLAIM (+ SUPERSEDE)``: the group's SUPERSEDEs are distributed so that each obsolete
claim is superseded exactly once, by one of them (the TARGET_SET law)."""


# ------------------------------------------------------------------ cases

_DENSE_CONCERNS: Final = tuple(c.key for c in CONCERNS if c.ledger == "dense")
_CASE_OF_CONCERN_T1: Final[dict[str, str]] = {
    _RES: "D1-RESERVATION-ONE-CONCERN",
    _UNL: "D2-UNLOCK-ATTEMPTS-ONE-CONCERN",
    _LATE: "D3-LATE-FEE-ONE-CONCERN",
    _CREDIT: "D4-SERVICE-CREDIT-ONE-CONCERN",
}

STRUCTURAL_CHECKS: Final = (
    "CANONICAL-FACETS",
    "SOURCE-COVERAGE",
    "PROPOSITION-ACCOUNTING",
    "AUTHORITY-ROUTING",
)
"""Run-wide checks beside the cases, the ledgers and run integrity."""


def _case(cid: str, title: str, ledger: LedgerId, *structural: str) -> CaseExpectation:
    return CaseExpectation(id=cid, title=title, ledger=ledger, structural=structural, semantic=())


_C4_UNDER_CORRECTION_SETS: Final = (
    "WEIGHT-T2 bound once, to WEIGHT; no CREATE cites it",
    "exactly one PENDING correction set at WEIGHT: one held assertion citing WEIGHT-T2 and one "
    "SUPERSEDE of a WEIGHT claim, both REQUIRE_HUMAN; no correcting claim live; no "
    "CONFLICTS_WITH",
)
_V5_CASES: Final = tuple(
    CaseExpectation(
        id=c.id,
        title=c.title,
        ledger=c.ledger,
        structural=_C4_UNDER_CORRECTION_SETS if c.id == "C4-CORRECTION" else c.structural,
        semantic=(),
    )
    for c in v5.CASES
    if not c.id.startswith("A-")
)
"""v5's cases, carried: under correction sets C4's correction is one PENDING set (its correcting
claim is held, not live) and nothing of it is decided."""

_DENSE_CASES: Final = (
    _case("D0-DENSE-FORMATION", "fifteen sections, nine governed concerns, one Call 1", "dense",
          "exactly 9 active addresses at every timepoint", "one CREATE per concern citing exactly "
          "its documents", "no CREATE cites the documents of two concerns"),
    _case("D1-RESERVATION-ONE-CONCERN", "booking window and length, no-show expiry and adding "
          "time are one reservation concern", "dense", "one address for three sections"),
    _case("D2-UNLOCK-ATTEMPTS-ONE-CONCERN", "attempt limit, retry wait and timeout-as-failure are "
          "one unlock-attempt concern", "dense", "one address for three sections"),
    _case("D3-LATE-FEE-ONE-CONCERN", "the fee, its grace, rate and cap, and its fault waiver are "
          "one entitlement", "dense", "one address for two sections"),
    _case("D4-SERVICE-CREDIT-ONE-CONCERN", "the credit, its destination and its claim deadline "
          "are one entitlement (C6 shape)", "dense", "one address for two sections"),
    _case("D5-SINGLE-SECTION-CONCERNS", "cleaning fee, billing run, suspension, trip records and "
          "membership approval each form their own address", "dense", "one address each"),
    *(
        _case(case, f"separate: {case.split('-', 1)[1].lower().replace('-', ' ')}", "dense",
              "two distinct addresses")
        for case in dict.fromkeys(s.case for s in EXPECTED_SEPARATE if s.ledger == "dense")
    ),
    _case("X1-ONE-TO-ONE", "1:1: the cleaning fee 30 -> 40 EUR", "dense",
          "one PENDING set at the cleaning-fee address after T2"),
    _case("X2-MANY-TO-ONE", "N:1: grace period and per-minute rate -> one flat fee", "dense",
          "one PENDING set at the late-fee address after T2"),
    _case("X3-ONE-TO-MANY", "1:N: one flat credit -> credit by reservation length", "dense",
          "one PENDING set at the service-credit address after T2"),
    _case("X4-MANY-TO-MANY", "N:M: fixed 10-second wait -> 5 seconds, doubling, 40-second cap",
          "dense", "one PENDING set retiring every claim of the old wait section"),
    _case("Z1-PENDING-ATOMIC", "while PENDING nothing of a correction is current", "dense",
          "no correcting claim live and no target retired after T2"),
    _case("Z2-AGREE", "the scripted human AGREEs every set: all members apply atomically",
          "dense", "every set AGREED, every member applied, every target retired"),
    _case("Z3-DECLINE", "the scripted human DECLINEs every set: nothing applies", "dense",
          "every set DECLINED, no member applied, every target live, no set pending"),
    _case("Z4-REPEAT-SUPPRESSED", "after DECLINE the same correction on the same basis makes "
          "no new work", "dense", "no PENDING set at the unlock address after T3-DECLINE"),
    _case("Z5-CHANGED-BASIS-REOPENS", "a changed basis makes new work in both branches", "dense",
          "one new PENDING set at the cleaning-fee address after T3"),
    _case("Z6-AUTHORITY-ROUTING", "authority work is discovered, decided later by a human, and "
          "unrelated concerns continue", "dense", "stable ids, no self-approval, the trip "
          "extension applies while sets are pending"),
    _case("A-DENSE-SOURCE-ACCOUNTING", "source accounting in ledger dense", "dense",
          "no structural refusal; every accepted Call 2 recomputes to zero findings"),
)  # fmt: skip


# ------------------------------------------------------------------ semantic questions


def _statements(ids: tuple[str, ...]) -> str:
    return "; ".join(f"{i}: {_BY_ID[i].statement}" for i in ids)


def _current_ids(ledger: LedgerId, concern: str, at: Timepoint) -> tuple[str, ...]:
    return tuple(
        p.id
        for p in PROPOSITIONS
        if p.ledger == ledger and p.concern == concern and _current(p, at)
    )


def _full_inventory(ledger: LedgerId, concern: str) -> tuple[str, ...]:
    return tuple(
        p.id
        for p in PROPOSITIONS
        if p.ledger == ledger
        and p.concern == concern
        and p.relation != "RESTATES"
        and p.branch is None
    )


_CLAIMS_RULE: Final = (
    "is every one of these propositions stated by at least one live claim (a claim may state "
    "more than one of them), and does no live claim state anything that is not one of them "
    "[{listed}]"
)
_SUBJECT_RULE: Final = (
    "does the address subject name the governed concern itself (an act, entity or record, "
    "entitlement, state, decision or operational concern) such that every proposition of the "
    "concern's full sealed inventory [{inventory}] is about it, rather than naming only one "
    "dimension of it (one who, when, limit, amount, timing, timeout, duration, expiry, "
    "renewal, deadline, destination, effect or repetition rule) or a generic word (such as "
    "governance, policy, rules or lifecycle)?"
)


def _where(concern: Concern) -> str:
    docs = ", ".join(concern.documents)
    return f"at the address whose CREATE_ADDRESS cites {docs}"


def _concern(ledger: LedgerId, key: str) -> Concern:
    (hit,) = [c for c in CONCERNS if c.ledger == ledger and c.key == key]
    return hit


def _formation_question(c: Concern, case: str) -> SemanticQuestion:
    return SemanticQuestion(
        id=f"Q-T1-{c.ledger.upper()}-{c.key}",
        case=case,
        ledger=c.ledger,
        after="T1",
        question=(
            f"At T1, in ledger {c.ledger}, {_where(c)}: "
            + _CLAIMS_RULE.format(listed=_statements(_current_ids(c.ledger, c.key, "T1")))
            + "; and "
            + _SUBJECT_RULE.format(inventory=_statements(_full_inventory(c.ledger, c.key)))
        ),
    )


def _state_question(
    qid: str, case: str, c: Concern, at: Timepoint, extra: str = ""
) -> SemanticQuestion:
    return SemanticQuestion(
        id=qid,
        case=case,
        ledger=c.ledger,
        after=at,
        question=(
            f"At {at}, in ledger {c.ledger}, {_where(c)}: "
            + _CLAIMS_RULE.format(listed=_statements(_current_ids(c.ledger, c.key, at)))
            + (f"; and {extra}" if extra else "")
            + "?"
        ),
    )


def _correction_question(g: CorrectionExpectation, case: str) -> SemanticQuestion:
    c = _concern(g.ledger, g.concern)
    if g.outcome == "SUPPRESSED_AS_DECLINED":
        extra = (
            f"is no correction pending at this address, so that the declined correction "
            f"({_statements(g.replacements)}) has not become authority work again and no claim "
            f"stating it is live"
        )
    else:
        extra = (
            f"does exactly one PENDING correction set hold this correction of {g.document}: its "
            f"SUPERSEDE judgments retire exactly the claims stating [{_statements(g.obsolete)}] "
            f"(each once, none other), its held assertions state exactly "
            f"[{_statements(g.replacements)}], and none of those assertions is a live claim yet"
        )
    return _state_question(f"Q-{g.at}-{g.id}", case, c, g.at, extra)


def _disposition_question(document: str, at: Timepoint, case: str) -> SemanticQuestion:
    branch = at.removeprefix("T3-") if at.startswith("T3-") else None
    props = [p for p in PROPOSITIONS if p.document == document and p.branch == branch]
    listed = "; ".join(
        f"{p.id}: {p.statement} -> {EXPECTED_DISPOSITIONS[p.id]}"
        + (f" (of {', '.join(p.of)})" if p.of else "")
        for p in props
    )
    ledger = DOCUMENTS[document].ledger
    return SemanticQuestion(
        id=f"Q-{at}-DISP-{document}",
        case=case,
        ledger=ledger,
        after=at,
        question=(
            f"At {at}, in ledger {ledger}, in the model's accounting of {document} (its listed "
            "propositions with their sentences, and each disposition's proposition_id): is each "
            "of these sealed propositions represented by a listed proposition whose disposition "
            f"is the one given, with no listed proposition disposed of otherwise [{listed}]? A "
            "SUPPORTS_CLAIM must support the current claim stating the proposition it restates; "
            "an ASSERT_CLAIM must be at the address holding that concern; a SUPERSEDE must name "
            "a current claim stating one of the propositions its proposition replaces, and "
            "together the SUPERSEDEs of one correction name each replaced claim exactly once."
        ),
    )


def _non_operative_question(ledger: LedgerId, at: Timepoint, case: str) -> SemanticQuestion:
    t = {"T1": 1, "T2": 2}.get(at, 3)
    branch = at.removeprefix("T3-") if t == 3 else None
    documents = {d.key for d in DOCUMENTS.values() if d.ledger == ledger and d.t == t}
    listed = "; ".join(
        f"{p.id}: {p.statement}"
        for p in PROPOSITIONS
        if p.document in documents and p.branch == branch
    )
    return SemanticQuestion(
        id=f"Q-{at}-NONOP-{ledger.upper()}",
        case=case,
        ledger=ledger,
        after=at,
        question=(
            f"At {at}, in ledger {ledger}, in the model's accounting of this delta: does every "
            "sentence it declared non_operative state none of these sealed propositions, so that "
            f"no operative sentence was set aside [{listed}]?"
        ),
    )


def _v5_questions() -> tuple[SemanticQuestion, ...]:
    """v5's questions for the carried ledgers, re-derived under v6's timepoint wording."""
    out: list[SemanticQuestion] = []
    for c in CONCERNS:
        if c.ledger == "dense" or c.origin != "MODEL_T1":
            continue
        (case,) = [q.case for q in v5.SEMANTIC_QUESTIONS if q.id == f"Q-T1-{c.key}"]
        out.append(_formation_question(c, case))
    t2_cases = {
        "PICKUP": "C1-RESTATEMENT",
        "LABEL": "C2-EXTENSION",
        "LATE": "C6-LATE-DELIVERY",
        "H": "C7-C09-REGRESSION",
        "CANCEL": "U1-CANCEL-VS-AUDIT",
        "CUSTOMER-REFUND": "C8-LARGE-WORLD",
        "POD": "C3-NEW-CONCERN",
    }
    for key, case in t2_cases.items():
        c = next(c for c in CONCERNS if c.key == key and c.ledger != "dense")
        out.append(_state_question(f"Q-T2-{c.ledger.upper()}-{key}", case, c, "T2"))
    weight = next(g for g in CORRECTIONS if g.id == "X0-WEIGHT")
    out.append(_correction_question(weight, "C4-CORRECTION"))
    session = next(c for c in CONCERNS if c.key == "SESSION")
    out.append(
        SemanticQuestion(
            id="Q-T2-CONFLICT-SESSION",
            case="C5-EXISTING-CONFLICT",
            ledger="conflict",
            after="T2",
            question=(
                f"At T2, in ledger {session.ledger}, at the seeded session address: do exactly "
                "two live claims remain, one stating a 15-minute and one a 30-minute idle expiry, "
                "and does a pending CONFLICTS_WITH name exactly those two claims, with no "
                "SUPERSEDE or correction set pending against either?"
            ),
        )
    )
    for document, _ledger, case in v5._DISPOSITION_ITEMS:  # noqa: SLF001 - the sealed v5 list
        out.append(_disposition_question(document, "T2", case))
    return tuple(out)


_ACCOUNTING_TIMEPOINTS: Final[dict[LedgerId, tuple[Timepoint, ...]]] = {
    "core": ("T1", "T2"),
    "orion": ("T1", "T2"),
    "jobs": ("T1", "T2"),
    "conflict": ("T2",),
    "large": ("T1", "T2"),
    "dense": ("T1", "T2", "T3-AGREE", "T3-DECLINE"),
}


def _dense_questions() -> tuple[SemanticQuestion, ...]:
    out: list[SemanticQuestion] = []
    for key in _DENSE_CONCERNS:
        out.append(
            _formation_question(
                _concern("dense", key), _CASE_OF_CONCERN_T1.get(key, "D5-SINGLE-SECTION-CONCERNS")
            )
        )
    t2_groups = [g for g in CORRECTIONS if g.ledger == "dense" and g.at == "T2"]
    for g in t2_groups:
        out.append(_correction_question(g, g.id))
    trip = _concern("dense", "TRIP-RECORDS")
    out.append(
        _state_question(
            "Q-T2-DENSE-TRIP-RECORDS",
            "Z6-AUTHORITY-ROUTING",
            trip,
            "T2",
            "is the new download proposition (K-TRIP-4) a live claim while the corrections "
            "elsewhere in this ledger are still pending",
        )
    )
    for g in t2_groups:
        c = _concern("dense", g.concern)
        out.append(
            _state_question(
                f"Q-AGREED-{g.id}",
                "Z2-AGREE",
                c,
                "AGREED",
                f"is none of [{_statements(g.obsolete)}] stated by a live claim any more",
            )
        )
        out.append(
            _state_question(
                f"Q-DECLINED-{g.id}",
                "Z3-DECLINE",
                c,
                "DECLINED",
                f"is none of [{_statements(g.replacements)}] stated by a live claim",
            )
        )
    for g in CORRECTIONS:
        if g.at.startswith("T3-"):
            out.append(
                _correction_question(
                    g,
                    g.id.removesuffix("-AGREE")
                    .removesuffix("-DECLINE")
                    .replace("Z5-CHANGED-BASIS", "Z5-CHANGED-BASIS-REOPENS"),
                )
            )
    unlock = _concern("dense", _UNL)
    out.append(
        _state_question(
            "Q-T3-AGREE-UNLOCK",
            "Z4-REPEAT-SUPPRESSED",
            unlock,
            "T3-AGREE",
            "has the redelivered wait text (K-UNLOCK-WAIT-T3) created no correction and no new "
            "claim, only supports of the agreed wait claims",
        )
    )
    for document in ("K-CLEANING-T2", "K-LATE-T2", "K-CREDIT-T2", "K-UNLOCK-WAIT-T2", "K-TRIP-T2"):
        case = {
            "K-CLEANING-T2": "X1-ONE-TO-ONE",
            "K-LATE-T2": "X2-MANY-TO-ONE",
            "K-CREDIT-T2": "X3-ONE-TO-MANY",
            "K-UNLOCK-WAIT-T2": "X4-MANY-TO-MANY",
            "K-TRIP-T2": "Z6-AUTHORITY-ROUTING",
        }[document]
        out.append(_disposition_question(document, "T2", case))
    for at in ("T3-AGREE", "T3-DECLINE"):
        out.append(_disposition_question("K-UNLOCK-WAIT-T3", at, "Z4-REPEAT-SUPPRESSED"))
        out.append(_disposition_question("K-CLEANING-T3", at, "Z5-CHANGED-BASIS-REOPENS"))
    return tuple(out)


def _accounting_questions() -> tuple[SemanticQuestion, ...]:
    return tuple(
        _non_operative_question(ledger, at, f"A-{ledger.upper()}-SOURCE-ACCOUNTING")
        for ledger, times in _ACCOUNTING_TIMEPOINTS.items()
        for at in times
    )


SEMANTIC_QUESTIONS: Final[tuple[SemanticQuestion, ...]] = (
    *_v5_questions(),
    *_dense_questions(),
    *_accounting_questions(),
)

_ACCOUNTING_CASES: Final = tuple(
    _case(f"A-{ledger.upper()}-SOURCE-ACCOUNTING", f"source accounting in ledger {ledger}", ledger,
          "no structural refusal; every accepted Call 2 recomputes to zero findings")
    for ledger in _ACCOUNTING_TIMEPOINTS
    if ledger != "dense"
)  # fmt: skip


def _with_questions(cases: tuple[CaseExpectation, ...]) -> tuple[CaseExpectation, ...]:
    return tuple(
        c.model_copy(update={"semantic": tuple(q.id for q in SEMANTIC_QUESTIONS if q.case == c.id)})
        for c in cases
    )


CASES: Final[tuple[CaseExpectation, ...]] = _with_questions(
    (*_V5_CASES, *_ACCOUNTING_CASES, *_DENSE_CASES)
)

CRITICAL_CASES: Final = ("C7-C09-REGRESSION", "C6-LATE-DELIVERY", "D0-DENSE-FORMATION")
"""Named so a report cannot bury them; the standing is all-or-nothing anyway."""


def expectations_document() -> dict[str, object]:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "timepoints": list(TIMEPOINTS),
        "concerns": [c.model_dump(mode="json") for c in CONCERNS],
        "propositions": [p.model_dump(mode="json") for p in PROPOSITIONS],
        "source_coverage": source_coverage_document(),
        "corrections": [g.model_dump(mode="json") for g in CORRECTIONS],
        "pending_sets": {
            k: {t: list(v) for t, v in m.items()} for k, m in EXPECTED_PENDING_SETS.items()
        },
        "address_counts": {k: dict(v) for k, v in EXPECTED_ADDRESS_COUNTS.items()},
        "live_claims": {k: list(v) for k, v in LIVE_CLAIMS.items()},
        "items": [i.model_dump(mode="json") for i in ITEMS],
        "separate": [s.model_dump(mode="json") for s in EXPECTED_SEPARATE],
        "conflicts": {k: [list(p) for p in v] for k, v in EXPECTED_CONFLICTS.items()},
        "banned_facets": list(BANNED_FACETS),
        "expected_dispositions": EXPECTED_DISPOSITIONS,
        "structural_checks": list(STRUCTURAL_CHECKS),
        "cases": [c.model_dump(mode="json") for c in CASES],
        "critical_cases": list(CRITICAL_CASES),
        "semantic_questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS],
        "grain_rule": "concerns are derived from G2 as clarified on 2026-09-30: the rules of "
        "one act, entity, entitlement, state, decision or operational concern are claims at its "
        "one address whatever section they appear in; section boundaries, headings, predicates "
        "and triggers are never address boundaries",
        "authority_rule": "the scripted human (a live project-wide AuthorityRecord) decides "
        "every PENDING correction set listed by list_authority_work after dense T2: AGREE in "
        "one branch, DECLINE in the other; the model never decides",
        "standing_rule": "LOCUS_POLICY_VALIDATED iff every case, ledger, canonical-facet, "
        "source-coverage, proposition-accounting, authority-routing and run-integrity "
        "structural check passes (so zero over- and under-splits, the four correction "
        "cardinalities, atomic AGREE and DECLINE, and no declined correction reopening), every "
        "semantic question is answered YES by the independent adjudicator from the frozen state "
        "of its own ledger and timepoint (so zero missing propositions), and every critical case "
        "passes; otherwise LOCUS_POLICY_NOT_VALIDATED. No partial pass.",
    }


def adjudication_questions_document() -> dict[str, object]:
    return {"questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS]}


def expectations_sha256() -> str:
    return canonical_sha256(expectations_document())


def adjudication_questions_sha256() -> str:
    return canonical_sha256(adjudication_questions_document())
