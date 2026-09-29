"""The hidden answer key of locus validation v3 (design §6, §7, §8). Never model-visible.

Sealed as ``expectations.json`` before any live call and never edited afterwards. It holds:

* the **proposition inventory** of every document: each proposition, the address it
  belongs at and its relation to what is already known. A document is never assumed to
  carry one claim: the expected claim count of an address is the number of distinct
  propositions the inventory places there (a test enforces the equality);
* the **structural expectations** the deterministic evaluator checks: addresses and their
  claim counts after T1 and after T2, binds, creations, new claims, required supports,
  supersessions, conflicts, and the address pairs that must stay separate;
* the **semantic questions** an independent adjudicator answers. Every question names the
  ledger and the timepoint it judges (``after T1`` or ``after T2``) and is answered from the
  frozen state of exactly that ledger at exactly that timepoint (v2's adjudication defect).

The request path never imports this module (a test and a preflight gate enforce it).
"""

from __future__ import annotations

from typing import Final, Literal

from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v3.protocol import EXPERIMENT_VERSION, LedgerId

__all__ = [
    "ADDRESSES",
    "CASES",
    "CRITICAL_CASE",
    "EXPECTED_ADDRESS_COUNTS",
    "EXPECTED_CONFLICTS",
    "EXPECTED_SEPARATE",
    "EXPECTED_SUPERSEDES",
    "LARGE_KEYS",
    "PROPOSITIONS",
    "REVISED_ITEMS",
    "SEED_ITEMS",
    "SEMANTIC_QUESTIONS",
    "AddressExpectation",
    "CaseExpectation",
    "ItemExpectation",
    "Proposition",
    "SemanticQuestion",
    "SeparateAddresses",
    "adjudication_questions_document",
    "adjudication_questions_sha256",
    "expectations_document",
    "expectations_sha256",
]

Relation = Literal["SEED", "RESTATES", "EXTENDS", "CORRECTS", "NEW_CONCERN"]


class Proposition(FrozenModel):
    id: str
    document: str
    statement: str
    address: str
    relation: Relation
    of: str | None = None
    """The known proposition this one restates or corrects."""


class AddressExpectation(FrozenModel):
    key: str
    ledger: LedgerId
    origin: Literal["MODEL_T1", "MODEL_T2", "AUTHOR_SEED"]
    created_from: str | None
    """The document whose CREATE_ADDRESS makes the address (model origins only)."""
    live_claims_after_t1: int | None
    live_claims_after_t2: int


class ItemExpectation(FrozenModel):
    """What the two calls must do with one delta item."""

    document: str
    ledger: LedgerId
    t: Literal[1, 2]
    binds: tuple[str, ...]
    """Address keys the item must be bound to in Call 1, exactly one bind each."""
    creates: int
    """CREATE_ADDRESS drafts citing the item in Call 1."""
    new_claims: dict[str, int]
    """New live claims citing the item, by address key; zero everywhere else."""
    must_support: tuple[str, ...] = ()
    """Proposition ids whose existing claim the item must SUPPORT (restatement)."""


class SeparateAddresses(FrozenModel):
    """Two nearby governed concerns that must be two distinct addresses (under-split law)."""

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
    after: Literal[1, 2]
    """The timepoint judged: the adjudicator sees this ledger's frozen state after T``after``."""
    question: str


def _p(
    pid: str,
    document: str,
    address: str,
    statement: str,
    relation: Relation = "SEED",
    of: str | None = None,
) -> Proposition:
    return Proposition(
        id=pid, document=document, statement=statement, address=address, relation=relation, of=of
    )


# ------------------------------------------------------------------ the proposition inventory

_CORE: Final = (
    # T1 (model): seven documents, two propositions each
    _p("PICKUP-1", "PICKUP-T1", "PICKUP", "a pickup requested before 14:00 is collected the same "
       "working day"),
    _p("PICKUP-2", "PICKUP-T1", "PICKUP", "a pickup requested at or after 14:00 is collected the "
       "next working day"),
    _p("LABEL-1", "LABEL-T1", "LABEL", "every parcel carries a printed label before collection"),
    _p("LABEL-2", "LABEL-T1", "LABEL", "the label shows the destination postcode"),
    _p("WEIGHT-1", "WEIGHT-T1", "WEIGHT", "a single parcel may weigh at most 30 kg"),
    _p("WEIGHT-2", "WEIGHT-T1", "WEIGHT", "a parcel over the weight limit is refused at pickup"),
    _p("ATTEMPTS-1", "ATTEMPTS-T1", "ATTEMPTS", "a courier makes at most two delivery attempts per "
       "parcel"),
    _p("ATTEMPTS-2", "ATTEMPTS-T1", "ATTEMPTS", "after the second failed attempt the parcel is "
       "taken to the local depot"),
    _p("LATE-1", "LATE-T1", "LATE", "a sender whose parcel is delivered later than the promised "
       "date is refunded the shipping fee"),
    _p("LATE-2", "LATE-T1", "LATE", "the late-delivery refund is paid to the payment method used "
       "for the booking"),
    _p("DAMAGE-1", "DAMAGE-T1", "DAMAGE", "a sender whose parcel arrives damaged is refunded "
       "the declared value of the contents"),
    _p("DAMAGE-2", "DAMAGE-T1", "DAMAGE", "the damage must be reported within 48 hours of "
       "delivery"),
    _p("SETTLEMENT-1", "SETTLEMENT-T1", "SETTLEMENT", "approved compensation payments are sent to "
       "the bank in a settlement run at 17:00 each working day"),
    _p("SETTLEMENT-2", "SETTLEMENT-T1", "SETTLEMENT", "a payment approved after 17:00 is sent in "
       "the next working day's settlement run"),
    # T2 (model)
    _p("PICKUP-1R", "PICKUP-T2", "PICKUP", "same-day collection for a pickup booked before 2 p.m.",
       "RESTATES", "PICKUP-1"),
    _p("PICKUP-2R", "PICKUP-T2", "PICKUP", "next-day collection for a pickup booked at or after "
       "2 p.m.", "RESTATES", "PICKUP-2"),
    _p("LABEL-1R", "LABEL-T2", "LABEL", "printed label before collection", "RESTATES", "LABEL-1"),
    _p("LABEL-2R", "LABEL-T2", "LABEL", "label shows the destination postcode", "RESTATES",
       "LABEL-2"),
    _p("LABEL-3", "LABEL-T2", "LABEL", "the label also carries a barcode that encodes the "
       "parcel's tracking number", "EXTENDS"),
    _p("WEIGHT-1C", "WEIGHT-T2", "WEIGHT", "a single parcel may weigh at most 25 kg", "CORRECTS",
       "WEIGHT-1"),
    _p("WEIGHT-2R", "WEIGHT-T2", "WEIGHT", "an overweight parcel is refused at pickup", "RESTATES",
       "WEIGHT-2"),
    _p("ATTEMPTS-1R", "ATTEMPTS-T2", "ATTEMPTS", "at most two delivery attempts", "RESTATES",
       "ATTEMPTS-1"),
    _p("ATTEMPTS-2R", "ATTEMPTS-T2", "ATTEMPTS", "depot after the second failed attempt",
       "RESTATES", "ATTEMPTS-2"),
    _p("POD-1", "ATTEMPTS-T2", "POD", "a delivered parcel is recorded with the recipient's "
       "signature", "NEW_CONCERN"),
    _p("POD-2", "ATTEMPTS-T2", "POD", "signature records are kept for 90 days", "NEW_CONCERN"),
    _p("LATE-3", "LATE-NOTE-T2", "LATE", "the late-delivery refund must be requested within 14 "
       "days of the promised delivery date", "EXTENDS"),
)  # fmt: skip

_ORION: Final = (
    _p("H-1", "H-T1", "H", "a producer or operator may cancel a job"),
    _p("H-2", "H-T1", "H", "after cancellation no future execution attempt of the job may start"),
    _p("H-3", "H-T1", "H", "cancellation does not interrupt a running attempt, which runs to its "
       "own completion, failure or timeout"),
    _p("H-1R", "H-T9", "H", "producers and operators can cancel jobs", "RESTATES", "H-1"),
    _p("H-2R", "H-T9", "H", "no future attempt after cancellation", "RESTATES", "H-2"),
    _p("H-3R", "H-T9", "H", "a running attempt is not interrupted", "RESTATES", "H-3"),
    _p("H-4", "H-T9", "H", "a cancellation received for an already-cancelled job leaves it "
       "cancelled and changes nothing else about its state", "EXTENDS"),
)  # fmt: skip

_JOBS: Final = (
    _p("CANCEL-1", "CANCEL-T1", "CANCEL", "the owner of a scheduled job, or an administrator, may "
       "cancel it"),
    _p("CANCEL-2", "CANCEL-T1", "CANCEL", "once a job is cancelled none of its future runs is "
       "started"),
    _p("AUDIT-1", "AUDIT-T1", "AUDIT", "a job's audit record is deleted automatically 30 days "
       "after the job ends"),
    _p("AUDIT-2", "AUDIT-T1", "AUDIT", "only a compliance officer may delete a job's audit record "
       "earlier"),
    _p("CANCEL-3", "CANCEL-NOTE-T2", "CANCEL", "a request to cancel a job that has already "
       "finished is refused", "EXTENDS"),
)  # fmt: skip

_CONFLICT: Final = (
    _p("SESSION-15R", "HANDBOOK-T2", "SESSION", "an idle session ends after 15 minutes",
       "RESTATES", "SESSION-15"),
    _p("SESSION-30R", "FAQ-T2", "SESSION", "an idle session ends after 30 minutes", "RESTATES",
       "SESSION-30"),
)  # fmt: skip

_LARGE_SEED: Final[tuple[tuple[str, str, str], ...]] = (
    ("CUSTOMER-REFUND", "CR-1", "a customer who returns an order is refunded the price "
     "paid for the returned items"),
    ("SUPPLIER-OVERPAYMENT", "SO-1", "a supplier paid more than its invoice total must pay the "
     "excess back"),
    ("CHARGEBACK", "CB-1", "a chargeback must be answered within 7 days of the card network's "
     "notice"),
    ("PAYOUT", "PO-1", "sellers are paid out every Friday"),
    ("PAYOUT", "PO-2", "a payout is made only when the seller's balance is at least 20 GBP"),
    ("CONVERSION", "CV-1", "a foreign-currency payment is converted at that day's reference "
     "exchange rate"),
    ("STORE-CREDIT", "SC-1", "store credit expires 12 months after it is issued"),
    ("GIFT-CARD", "GC-1", "a gift card can pay for any order"),
    ("GIFT-CARD", "GC-2", "a gift card balance never expires"),
    ("INVOICE", "IN-1", "every order placed by a business customer receives a VAT invoice"),
    ("RETRY", "RT-1", "a failed subscription payment is tried again 3 days later"),
    ("RETRY", "RT-2", "a failed subscription payment is tried again at most three times"),
    ("CARD-CHECK", "CC-1", "a new payment card is checked with a zero-amount authorisation before "
     "it is saved"),
    ("FRAUD-HOLD", "FH-1", "an order flagged by fraud screening is held until an analyst has "
     "reviewed it"),
    ("CAPTURE", "CP-1", "a card payment is captured when the order is dispatched, not when it is "
     "placed"),
    ("SELLER-LIMIT", "SL-1", "a new seller account may receive at most 1,000 GBP in payments "
     "during its first 30 days"),
    ("PRICE-VAT", "PV-1", "prices shown to consumers include VAT"),
    ("INSTALMENTS", "IP-1", "an order may be paid in three monthly instalments"),
    ("PROMO", "PR-1", "only one promotional code can be applied to an order"),
)  # fmt: skip

LARGE_KEYS: Final = tuple(dict.fromkeys(key for key, _, _ in _LARGE_SEED))

_LARGE: Final = (
    *(_p(pid, f"{key}-T1", key, statement) for key, pid, statement in _LARGE_SEED),
    _p("CR-2", "RETURNS-NOTE-T2", "CUSTOMER-REFUND", "the original delivery charge is also repaid "
       "to a customer who returns an order", "EXTENDS"),
)  # fmt: skip

PROPOSITIONS: Final[tuple[Proposition, ...]] = (*_CORE, *_ORION, *_JOBS, *_CONFLICT, *_LARGE)


# ------------------------------------------------------------------ addresses and claim counts


def _count(address: str, t: int) -> int:
    """Live claims the inventory places at ``address`` after T``t``: its SEED propositions,
    plus (after T2) its EXTENDS, CORRECTS and NEW_CONCERN propositions. A correction adds a
    live claim: the corrected claim stays live under a pending SUPERSEDE (second lens)."""
    added = ("EXTENDS", "CORRECTS", "NEW_CONCERN")
    return sum(
        1
        for p in PROPOSITIONS
        if p.address == address and (p.relation == "SEED" or (t == 2 and p.relation in added))
    )


def _model_t1(key: str, ledger: LedgerId) -> AddressExpectation:
    return AddressExpectation(
        key=key,
        ledger=ledger,
        origin="MODEL_T1",
        created_from=f"{key}-T1",
        live_claims_after_t1=_count(key, 1),
        live_claims_after_t2=_count(key, 2),
    )


ADDRESSES: Final[tuple[AddressExpectation, ...]] = (
    *(
        _model_t1(k, "core")
        for k in ("PICKUP", "LABEL", "WEIGHT", "ATTEMPTS", "LATE", "DAMAGE", "SETTLEMENT")
    ),
    AddressExpectation(
        key="POD",
        ledger="core",
        origin="MODEL_T2",
        created_from="ATTEMPTS-T2",
        live_claims_after_t1=None,
        live_claims_after_t2=2,
    ),
    _model_t1("H", "orion"),
    _model_t1("CANCEL", "jobs"),
    _model_t1("AUDIT", "jobs"),
    AddressExpectation(
        key="SESSION",
        ledger="conflict",
        origin="AUTHOR_SEED",
        created_from=None,
        live_claims_after_t1=2,
        live_claims_after_t2=2,
    ),
    *(_model_t1(k, "large") for k in LARGE_KEYS),
)

EXPECTED_ADDRESS_COUNTS: Final[dict[LedgerId, tuple[int, int]]] = {
    "core": (7, 8),
    "orion": (1, 1),
    "jobs": (2, 2),
    "conflict": (1, 1),
    "large": (16, 16),
}
"""Active in-scope addresses after T1 and after T2. Any other count is a duplicate
(over-split) or a merge (under-split) of a governed concern."""


# ------------------------------------------------------------------ per-item expectations


def _seed_item(key: str, ledger: LedgerId) -> ItemExpectation:
    return ItemExpectation(
        document=f"{key}-T1",
        ledger=ledger,
        t=1,
        binds=(),
        creates=1,
        new_claims={key: _count(key, 1)},
    )


SEED_ITEMS: Final[tuple[ItemExpectation, ...]] = (
    *(
        _seed_item(k, "core")
        for k in ("PICKUP", "LABEL", "WEIGHT", "ATTEMPTS", "LATE", "DAMAGE", "SETTLEMENT")
    ),
    _seed_item("H", "orion"),
    _seed_item("CANCEL", "jobs"),
    _seed_item("AUDIT", "jobs"),
    *(_seed_item(k, "large") for k in LARGE_KEYS),
)
"""The model-formed T1 items: one creation each, holding the inventory's claims."""

REVISED_ITEMS: Final[tuple[ItemExpectation, ...]] = (
    ItemExpectation(
        document="PICKUP-T2",
        ledger="core",
        t=2,
        binds=("PICKUP",),
        creates=0,
        new_claims={},
        must_support=("PICKUP-1", "PICKUP-2"),
    ),
    ItemExpectation(
        document="LABEL-T2", ledger="core", t=2, binds=("LABEL",), creates=0,
        new_claims={"LABEL": 1},
    ),
    ItemExpectation(
        document="WEIGHT-T2", ledger="core", t=2, binds=("WEIGHT",), creates=0,
        new_claims={"WEIGHT": 1},
    ),
    ItemExpectation(
        document="ATTEMPTS-T2", ledger="core", t=2, binds=("ATTEMPTS",), creates=1,
        new_claims={"POD": 2},
    ),
    ItemExpectation(
        document="LATE-NOTE-T2", ledger="core", t=2, binds=("LATE",), creates=0,
        new_claims={"LATE": 1},
    ),
    ItemExpectation(
        document="H-T9", ledger="orion", t=2, binds=("H",), creates=0, new_claims={"H": 1}
    ),
    ItemExpectation(
        document="CANCEL-NOTE-T2", ledger="jobs", t=2, binds=("CANCEL",), creates=0,
        new_claims={"CANCEL": 1},
    ),
    ItemExpectation(
        document="HANDBOOK-T2", ledger="conflict", t=2, binds=("SESSION",), creates=0,
        new_claims={},
    ),
    ItemExpectation(
        document="FAQ-T2", ledger="conflict", t=2, binds=("SESSION",), creates=0, new_claims={}
    ),
    ItemExpectation(
        document="RETURNS-NOTE-T2", ledger="large", t=2, binds=("CUSTOMER-REFUND",), creates=0,
        new_claims={"CUSTOMER-REFUND": 1},
    ),
)  # fmt: skip
"""SUPPORTS_CLAIM is required only where ``must_support`` says so (the restatement case);
elsewhere a SUPPORTS_CLAIM of a restated proposition is permitted, provided it supports a
claim at an address the item is bound to."""


# ------------------------------------------------------------------ governance and separation

EXPECTED_SUPERSEDES: Final[dict[LedgerId, tuple[str, ...]]] = {
    "core": ("WEIGHT",),
    "orion": (),
    "jobs": (),
    "conflict": (),
    "large": (),
}
"""Address keys of the claims a model SUPERSEDE must target: exactly one supersede per
entry, pending (``REQUIRE_SECOND_LENS``), never applied. None anywhere else."""

EXPECTED_CONFLICTS: Final[dict[LedgerId, tuple[tuple[str, str], ...]]] = {
    "core": (),
    "orion": (),
    "jobs": (),
    "conflict": (("SESSION-15", "SESSION-30"),),
    "large": (),
}
"""Seeded-claim key pairs a model CONFLICTS_WITH must name (at least once, pending, never
applied). A conflict naming any other pair, or in any other ledger, fails."""

EXPECTED_SEPARATE: Final[tuple[SeparateAddresses, ...]] = (
    SeparateAddresses(case="U1-CANCEL-VS-AUDIT", ledger="jobs", a="CANCEL", b="AUDIT"),
    SeparateAddresses(case="U2-LATE-VS-DAMAGE", ledger="core", a="LATE", b="DAMAGE"),
    SeparateAddresses(
        case="U3-COMPENSATION-VS-SETTLEMENT", ledger="core", a="LATE", b="SETTLEMENT"
    ),
    SeparateAddresses(
        case="U4-CUSTOMER-VS-SUPPLIER-REFUND",
        ledger="large",
        a="CUSTOMER-REFUND",
        b="SUPPLIER-OVERPAYMENT",
    ),
)


# ------------------------------------------------------------------ cases


CASES: Final[tuple[CaseExpectation, ...]] = (
    CaseExpectation(
        id="C0-CORE-SEED",
        title="core formation: pickup, label, weight and delivery-attempt concerns",
        ledger="core",
        structural=(
            "7 active core addresses after T1; one CREATE per T1 document, citing only it",
            "each created address holds exactly its document's 2 inventory claims",
            "0 BIND, SUPERSEDE, CONFLICTS_WITH or rejected admissions at T1",
        ),
        semantic=("Q-T1-PICKUP", "Q-T1-LABEL", "Q-T1-WEIGHT", "Q-T1-ATTEMPTS"),
    ),
    CaseExpectation(
        id="C1-RESTATEMENT",
        title="restatement: PICKUP-T2 rewords both current propositions",
        ledger="core",
        structural=(
            "PICKUP-T2 bound once, to PICKUP; no CREATE cites it",
            "no new claim cites PICKUP-T2; PICKUP keeps exactly its 2 claims",
            "each PICKUP claim receives at least one applied SUPPORTS_CLAIM citing PICKUP-T2",
        ),
        semantic=("Q-T2-PICKUP",),
    ),
    CaseExpectation(
        id="C2-EXTENSION",
        title="compatible extension: LABEL-T2 adds the tracking barcode",
        ledger="core",
        structural=(
            "LABEL-T2 bound once, to LABEL; no CREATE cites it",
            "exactly one new claim cites LABEL-T2, at LABEL; both earlier claims stay live (3)",
            "no SUPERSEDE targets a LABEL claim",
        ),
        semantic=("Q-T2-LABEL",),
    ),
    CaseExpectation(
        id="C3-NEW-CONCERN",
        title="genuine new concern inside a known document: proof of delivery",
        ledger="core",
        structural=(
            "ATTEMPTS-T2 bound once, to ATTEMPTS, and exactly one CREATE cites it (POD)",
            "POD holds exactly 2 claims, both citing ATTEMPTS-T2; no new claim at ATTEMPTS",
            "8 active core addresses after T2",
        ),
        semantic=("Q-T2-POD",),
    ),
    CaseExpectation(
        id="C4-CORRECTION",
        title="correction: WEIGHT-T2 lowers the limit from 30 kg to 25 kg",
        ledger="core",
        structural=(
            "WEIGHT-T2 bound once, to WEIGHT; no CREATE cites it",
            "exactly one new claim cites WEIGHT-T2, at WEIGHT; WEIGHT live claims == 3",
            "exactly one SUPERSEDE in the ledger, targeting a WEIGHT claim, routed "
            "REQUIRE_SECOND_LENS and never applied; no CONFLICTS_WITH",
        ),
        semantic=("Q-T2-WEIGHT",),
    ),
    CaseExpectation(
        id="C5-EXISTING-CONFLICT",
        title="contradiction already in state: two live incompatible session-expiry claims",
        ledger="conflict",
        structural=(
            "each T2 item bound once, to SESSION; no CREATE",
            "no new claim; both seeded claims stay live",
            "at least one CONFLICTS_WITH naming exactly the two seeded claims, pending; no "
            "other conflict; no SUPERSEDE",
        ),
        semantic=("Q-T2-SESSION",),
    ),
    CaseExpectation(
        id="C6-LATE-DELIVERY",
        title="v2 regression: the 14-day request deadline joins late-delivery compensation",
        ledger="core",
        structural=(
            "T1: LATE-T1 makes exactly one address holding its 2 inventory claims",
            "T2: LATE-NOTE-T2 bound once, to LATE; no CREATE cites it (no deadline address)",
            "exactly one new claim cites LATE-NOTE-T2, at LATE (3 live); no SUPERSEDE there",
        ),
        semantic=("Q-T1-LATE", "Q-T2-LATE"),
    ),
    CaseExpectation(
        id="C7-C09-REGRESSION",
        title="9P3 C09 (critical gate): repeated cancellation at locus H",
        ledger="orion",
        structural=(
            "T1: exactly one address, holding exactly the 3 inventory claims citing H-T1",
            "T2: H-T9 bound once, to H; no CREATE; exactly one new claim at H (4 live)",
            "no SUPERSEDE, no CONFLICTS_WITH, no rejected admission",
        ),
        semantic=("Q-T1-H", "Q-T2-H"),
    ),
    CaseExpectation(
        id="C8-LARGE-WORLD",
        title="scale: 16 model-formed nearby payment concerns, one extension without lineage",
        ledger="large",
        structural=(
            "T1: 16 active addresses, one CREATE per document citing only it, inventory claims",
            "T2: RETURNS-NOTE-T2 bound once, to CUSTOMER-REFUND, to no other; no CREATE",
            "exactly one new claim, at CUSTOMER-REFUND (2 live); all 15 others unchanged; "
            "no SUPERSEDE, no CONFLICTS_WITH",
        ),
        semantic=(
            *(f"Q-T1-{k}" for k in LARGE_KEYS),
            "Q-T2-CUSTOMER-REFUND",
        ),
    ),
    CaseExpectation(
        id="U1-CANCEL-VS-AUDIT",
        title="separate: job cancellation versus audit-record deletion",
        ledger="jobs",
        structural=(
            "T1: CANCEL-T1 and AUDIT-T1 make two distinct addresses, 2 claims each",
            "T2: CANCEL-NOTE-T2 (no lineage) bound once, to CANCEL, never to AUDIT; no CREATE",
            "exactly one new claim, at CANCEL (3 live); AUDIT unchanged (2); no SUPERSEDE",
        ),
        semantic=("Q-T1-CANCEL", "Q-T1-AUDIT", "Q-T2-CANCEL"),
    ),
    CaseExpectation(
        id="U2-LATE-VS-DAMAGE",
        title="separate: late-delivery compensation versus damaged-parcel compensation",
        ledger="core",
        structural=(
            "T1: LATE-T1 and DAMAGE-T1 make two distinct addresses, 2 claims each",
            "T2: LATE-NOTE-T2 never bound to DAMAGE; DAMAGE unchanged (2)",
        ),
        semantic=("Q-T1-DAMAGE",),
    ),
    CaseExpectation(
        id="U3-COMPENSATION-VS-SETTLEMENT",
        title="separate: requesting compensation versus the daily bank settlement run",
        ledger="core",
        structural=(
            "T1: LATE-T1 and SETTLEMENT-T1 make two distinct addresses, 2 claims each",
            "T2: LATE-NOTE-T2 never bound to SETTLEMENT; SETTLEMENT unchanged (2)",
        ),
        semantic=("Q-T1-SETTLEMENT",),
    ),
    CaseExpectation(
        id="U4-CUSTOMER-VS-SUPPLIER-REFUND",
        title="separate: customer refund of a returned order versus supplier overpayment",
        ledger="large",
        structural=(
            "T1: CUSTOMER-REFUND-T1 and SUPPLIER-OVERPAYMENT-T1 make two distinct addresses",
            "T2: RETURNS-NOTE-T2 never bound to SUPPLIER-OVERPAYMENT (checked under C8)",
        ),
        semantic=("Q-T1-CUSTOMER-REFUND", "Q-T1-SUPPLIER-OVERPAYMENT"),
    ),
)

CRITICAL_CASE: Final = "C7-C09-REGRESSION"
"""If this case fails the standing is NOT_VALIDATED whatever else passes (it is also
implied by the all-or-nothing rule; recorded separately so the report cannot bury it)."""


# ------------------------------------------------------------------ semantic questions

_FACET_RULE: Final = (
    "does the address facet ask about the governed concern as a whole, so that every "
    "proposition in this concern's full sealed inventory [{inventory}] answers part of it, "
    "rather than asking only what one of those propositions answers (one who, when, limit, "
    "amount, deadline, destination, effect or repetition rule)?"
)


def _statements(ids: tuple[str, ...]) -> str:
    by_id = {p.id: p for p in PROPOSITIONS}
    return "; ".join(f"{i}: {by_id[i].statement}" for i in ids)


def _inventory(address: str) -> tuple[str, ...]:
    """The propositions the address holds after T2 (restatements excluded)."""
    return tuple(p.id for p in PROPOSITIONS if p.address == address and p.relation != "RESTATES")


def _t1_question(key: str, ledger: LedgerId, case: str) -> SemanticQuestion:
    seeds = tuple(p.id for p in PROPOSITIONS if p.document == f"{key}-T1")
    return SemanticQuestion(
        id=f"Q-T1-{key}",
        case=case,
        ledger=ledger,
        after=1,
        question=(
            f"After T1, in ledger {ledger}, at the address whose CREATE_ADDRESS cites "
            f"{key}-T1: does each live claim state exactly one of these propositions, with "
            f"every proposition stated by exactly one claim and no claim stating anything "
            f"else [{_statements(seeds)}]; and "
            + _FACET_RULE.format(inventory=_statements(_inventory(key)))
        ),
    )


def _t2_state_question(
    key: str, ledger: LedgerId, case: str, created_from: str
) -> SemanticQuestion:
    return SemanticQuestion(
        id=f"Q-T2-{key}",
        case=case,
        ledger=ledger,
        after=2,
        question=(
            f"After T2, in ledger {ledger}, at the address whose CREATE_ADDRESS cites "
            f"{created_from}: do its live claims state exactly these propositions, each stated "
            f"by exactly one live claim, and no live claim state anything else "
            f"[{_statements(_inventory(key))}]?"
        ),
    )


SEMANTIC_QUESTIONS: Final[tuple[SemanticQuestion, ...]] = (
    # after T1
    _t1_question("PICKUP", "core", "C0-CORE-SEED"),
    _t1_question("LABEL", "core", "C0-CORE-SEED"),
    _t1_question("WEIGHT", "core", "C0-CORE-SEED"),
    _t1_question("ATTEMPTS", "core", "C0-CORE-SEED"),
    _t1_question("LATE", "core", "C6-LATE-DELIVERY"),
    _t1_question("DAMAGE", "core", "U2-LATE-VS-DAMAGE"),
    _t1_question("SETTLEMENT", "core", "U3-COMPENSATION-VS-SETTLEMENT"),
    _t1_question("H", "orion", "C7-C09-REGRESSION"),
    _t1_question("CANCEL", "jobs", "U1-CANCEL-VS-AUDIT"),
    _t1_question("AUDIT", "jobs", "U1-CANCEL-VS-AUDIT"),
    *(
        _t1_question(
            k,
            "large",
            "U4-CUSTOMER-VS-SUPPLIER-REFUND"
            if k in ("CUSTOMER-REFUND", "SUPPLIER-OVERPAYMENT")
            else "C8-LARGE-WORLD",
        )
        for k in LARGE_KEYS
    ),
    # after T2
    _t2_state_question("PICKUP", "core", "C1-RESTATEMENT", "PICKUP-T1"),
    _t2_state_question("LABEL", "core", "C2-EXTENSION", "LABEL-T1"),
    SemanticQuestion(
        id="Q-T2-POD",
        case="C3-NEW-CONCERN",
        ledger="core",
        after=2,
        question=(
            "After T2, in ledger core, at the address whose CREATE_ADDRESS cites ATTEMPTS-T2: "
            "do its subject and facet denote proof of delivery (the delivery record), not "
            "delivery attempts; and do its live claims state exactly "
            f"[{_statements(('POD-1', 'POD-2'))}], one claim each, and nothing else?"
        ),
    ),
    SemanticQuestion(
        id="Q-T2-WEIGHT",
        case="C4-CORRECTION",
        ledger="core",
        after=2,
        question=(
            "After T2, in ledger core, at the address whose CREATE_ADDRESS cites WEIGHT-T1: do "
            "its live claims state exactly "
            f"[{_statements(('WEIGHT-1', 'WEIGHT-2', 'WEIGHT-1C'))}], one claim each; and does "
            "the pending SUPERSEDE target the claim stating the 30 kg maximum (WEIGHT-1), not "
            "the refusal claim (WEIGHT-2)?"
        ),
    ),
    SemanticQuestion(
        id="Q-T2-SESSION",
        case="C5-EXISTING-CONFLICT",
        ledger="conflict",
        after=2,
        question=(
            "After T2, in ledger conflict, at the seeded session address: do exactly two live "
            "claims remain, one stating a 15-minute and one a 30-minute idle expiry, and does a "
            "pending CONFLICTS_WITH name exactly those two claims, with no SUPERSEDE pending "
            "against either?"
        ),
    ),
    _t2_state_question("LATE", "core", "C6-LATE-DELIVERY", "LATE-T1"),
    _t2_state_question("H", "orion", "C7-C09-REGRESSION", "H-T1"),
    _t2_state_question("CANCEL", "jobs", "U1-CANCEL-VS-AUDIT", "CANCEL-T1"),
    _t2_state_question("CUSTOMER-REFUND", "large", "C8-LARGE-WORLD", "CUSTOMER-REFUND-T1"),
)


def expectations_document() -> dict[str, object]:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "propositions": [p.model_dump(mode="json") for p in PROPOSITIONS],
        "addresses": [a.model_dump(mode="json") for a in ADDRESSES],
        "seed_items": [i.model_dump(mode="json") for i in SEED_ITEMS],
        "revised_items": [i.model_dump(mode="json") for i in REVISED_ITEMS],
        "address_counts": {k: list(v) for k, v in EXPECTED_ADDRESS_COUNTS.items()},
        "supersedes": {k: list(v) for k, v in EXPECTED_SUPERSEDES.items()},
        "conflicts": {k: [list(p) for p in v] for k, v in EXPECTED_CONFLICTS.items()},
        "separate": [s.model_dump(mode="json") for s in EXPECTED_SEPARATE],
        "support_rule": "SUPPORTS_CLAIM is required only for must_support propositions; "
        "elsewhere a support is permitted only at an address the item is bound to",
        "cases": [c.model_dump(mode="json") for c in CASES],
        "critical_case": CRITICAL_CASE,
        "semantic_questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS],
        "standing_rule": "LOCUS_POLICY_VALIDATED iff every case, ledger and run-integrity "
        "structural check passes, every semantic question is answered YES by the independent "
        "adjudicator from the frozen state of its own ledger and timepoint, and the critical "
        "case C7-C09-REGRESSION passes; otherwise LOCUS_POLICY_NOT_VALIDATED. No partial pass.",
    }


def adjudication_questions_document() -> dict[str, object]:
    return {"questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS]}


def expectations_sha256() -> str:
    return canonical_sha256(expectations_document())


def adjudication_questions_sha256() -> str:
    return canonical_sha256(adjudication_questions_document())
