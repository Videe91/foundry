"""The hidden answer key of locus validation v4 (design §6, §7, §8). Never model-visible.

Sealed as ``expectations.json`` before any live call and never edited afterwards. It holds:

* the **source-coverage map**: every sentence of every document (``source_sentences``) is
  accounted for, carrying proposition ids or an explicit reason it carries none. v3's
  inventory missed a semantically operative prose sentence of 9P3 H-T9 ("a repeated
  cancellation is simply acknowledged"); preparing the seal refuses an incomplete map;
* the **proposition inventory** of every document: each proposition, the address it
  belongs at and its relation to what is already known;
* the **structural expectations**: addresses, claim-count RANGES after T1 and after T2,
  binds, creations, new-claim ranges, required supports, supersessions, conflicts and the
  address pairs that must stay separate. A document adds, per address, at least one claim and
  at most one per proposition it places there: one claim may state two tightly coupled
  propositions (v3's H-4 claim did), and every proposition must still be stated, which the
  independent adjudicator checks;
* the **semantic questions**, each naming its ledger and timepoint and answered from the
  frozen state of exactly that ledger at exactly that timepoint.

The facet is not judged semantically: under ``intent-v2-locus-v3`` it is Foundry's
deterministic ``canonical_facet(subject)`` and is checked structurally. The concern decision
the model makes is the subject, and that is what the questions judge.

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
from foundry.experiments.locus_validation_v5.corpus import DOCUMENTS, SEED_WORLDS
from foundry.experiments.locus_validation_v5.protocol import EXPERIMENT_VERSION, LedgerId

__all__ = [
    "ADDRESSES",
    "BANNED_FACETS",
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
    "SOURCE_COVERAGE",
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
    "source_coverage_document",
    "source_coverage_findings",
    "source_coverage_sha256",
]

Relation = Literal["SEED", "RESTATES", "EXTENDS", "CORRECTS", "NEW_CONCERN"]
Range = tuple[int, int]


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
    live_claims_after_t1: Range | None
    live_claims_after_t2: Range


class ItemExpectation(FrozenModel):
    """What the two calls must do with one delta item."""

    document: str
    ledger: LedgerId
    t: Literal[1, 2]
    binds: tuple[str, ...]
    """Address keys the item must be bound to in Call 1, exactly one bind each."""
    creates: int
    """CREATE_ADDRESS drafts citing the item in Call 1."""
    new_claims: dict[str, Range]
    """Allowed range of new live claims citing the item, by address key; zero elsewhere."""
    must_support: tuple[str, ...] = ()
    """Proposition ids whose existing claims the item must SUPPORT (every live claim at the
    bound address that predates the item)."""


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
    _p("H-5", "H-T9", "H", "a repeated cancellation (one received for an already-cancelled "
       "job) is acknowledged", "EXTENDS"),
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


# ------------------------------------------------------------------ source coverage

_EXAMPLE: Final = "illustrative example that restates listed rules and adds none"
_QUESTION: Final = "the question the following answer responds to; it asserts nothing"


def _accounts(document: str, *entries: tuple[str, ...] | str) -> tuple[SentenceAccount, ...]:
    """One entry per sentence of ``document``, in order: proposition ids or a reason. The
    count must match the document's sentences exactly (``strict``)."""
    return tuple(
        SentenceAccount(sentence=sentence, propositions=entry)
        if isinstance(entry, tuple)
        else SentenceAccount(sentence=sentence, non_operative_reason=entry)
        for sentence, entry in zip(source_sentences(DOCUMENTS[document].text), entries, strict=True)
    )


def _one_each(document: str, *pids: str) -> tuple[SentenceAccount, ...]:
    return _accounts(document, *((pid,) for pid in pids))


SOURCE_COVERAGE: Final[dict[str, tuple[SentenceAccount, ...]]] = {
    "PICKUP-T1": _one_each("PICKUP-T1", "PICKUP-1", "PICKUP-2"),
    "LABEL-T1": _one_each("LABEL-T1", "LABEL-1", "LABEL-2"),
    "WEIGHT-T1": _one_each("WEIGHT-T1", "WEIGHT-1", "WEIGHT-2"),
    "ATTEMPTS-T1": _one_each("ATTEMPTS-T1", "ATTEMPTS-1", "ATTEMPTS-2"),
    "LATE-T1": _one_each("LATE-T1", "LATE-1", "LATE-2"),
    "DAMAGE-T1": _one_each("DAMAGE-T1", "DAMAGE-1", "DAMAGE-2"),
    "SETTLEMENT-T1": _one_each("SETTLEMENT-T1", "SETTLEMENT-1", "SETTLEMENT-2"),
    "H-T1": _accounts(
        "H-T1",
        ("H-1",),
        ("H-2", "H-3"),  # stops further effort (no future attempt); no forcible abort
        ("H-2",),
        ("H-3",),
        _EXAMPLE,
        _EXAMPLE,
    ),
    "CANCEL-T1": _one_each("CANCEL-T1", "CANCEL-1", "CANCEL-2"),
    "AUDIT-T1": _one_each("AUDIT-T1", "AUDIT-1", "AUDIT-2"),
    "HANDBOOK-T1": _one_each("HANDBOOK-T1", "SESSION-15"),
    "FAQ-T1": _accounts("FAQ-T1", _QUESTION, ("SESSION-30",)),
    **{f"{k}-T1": _one_each(f"{k}-T1", *(pid for key, pid, _ in _LARGE_SEED if key == k))
       for k in LARGE_KEYS},
    "PICKUP-T2": _one_each("PICKUP-T2", "PICKUP-1R", "PICKUP-2R"),
    "LABEL-T2": _one_each("LABEL-T2", "LABEL-1R", "LABEL-2R", "LABEL-3"),
    "WEIGHT-T2": _one_each("WEIGHT-T2", "WEIGHT-1C", "WEIGHT-2R"),
    "ATTEMPTS-T2": _one_each("ATTEMPTS-T2", "ATTEMPTS-1R", "ATTEMPTS-2R", "POD-1", "POD-2"),
    "LATE-NOTE-T2": _one_each("LATE-NOTE-T2", "LATE-3"),
    "H-T9": _accounts(
        "H-T9",
        ("H-1R",),
        ("H-2R", "H-3R"),  # stop investing (no future attempt); no abort of work under way
        ("H-5",),  # the same cancellation may arrive again; a repeat is simply acknowledged
        ("H-2R",),
        ("H-3R",),
        ("H-4",),
        _EXAMPLE,
        _EXAMPLE,
    ),
    "CANCEL-NOTE-T2": _one_each("CANCEL-NOTE-T2", "CANCEL-3"),
    "HANDBOOK-T2": _one_each("HANDBOOK-T2", "SESSION-15R"),
    "FAQ-T2": _accounts("FAQ-T2", _QUESTION, ("SESSION-30R",)),
    "RETURNS-NOTE-T2": _one_each("RETURNS-NOTE-T2", "CR-2"),
}  # fmt: skip
"""Every sentence of every document, accounted for. Sealed; ``prepare`` refuses a gap."""


def source_coverage_findings() -> tuple[str, ...]:
    """Coverage gaps: a document without a map, a sentence without an account, an omission
    without a reason, an account naming an unknown proposition, and a proposition of a
    document that no sentence of that document carries."""
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


# ------------------------------------------------------------------ addresses and claim ranges

_ADDS: Final = ("EXTENDS", "CORRECTS", "NEW_CONCERN")


def _range(document: str, address: str) -> Range:
    """New claims ``document`` may add at ``address``: at least one, at most one per
    proposition it places there; (0, 0) when it places none."""
    n = sum(
        1
        for p in PROPOSITIONS
        if p.document == document and p.address == address and p.relation in ("SEED", *_ADDS)
    )
    return (1, n) if n else (0, 0)


def _sum(ranges: list[Range]) -> Range:
    return (sum(r[0] for r in ranges), sum(r[1] for r in ranges))


def _live(address: str, t: int) -> Range:
    docs = {
        p.document
        for p in PROPOSITIONS
        if p.address == address and (p.relation == "SEED" or (t == 2 and p.relation in _ADDS))
    }
    return _sum([_range(d, address) for d in sorted(docs)])


def _model_t1(key: str, ledger: LedgerId) -> AddressExpectation:
    return AddressExpectation(
        key=key,
        ledger=ledger,
        origin="MODEL_T1",
        created_from=f"{key}-T1",
        live_claims_after_t1=_live(key, 1),
        live_claims_after_t2=_live(key, 2),
    )


_CORE_KEYS: Final = ("PICKUP", "LABEL", "WEIGHT", "ATTEMPTS", "LATE", "DAMAGE", "SETTLEMENT")

ADDRESSES: Final[tuple[AddressExpectation, ...]] = (
    *(_model_t1(k, "core") for k in _CORE_KEYS),
    AddressExpectation(
        key="POD",
        ledger="core",
        origin="MODEL_T2",
        created_from="ATTEMPTS-T2",
        live_claims_after_t1=None,
        live_claims_after_t2=_live("POD", 2),
    ),
    _model_t1("H", "orion"),
    _model_t1("CANCEL", "jobs"),
    _model_t1("AUDIT", "jobs"),
    AddressExpectation(
        key="SESSION",
        ledger="conflict",
        origin="AUTHOR_SEED",
        created_from=None,
        live_claims_after_t1=(2, 2),
        live_claims_after_t2=(2, 2),
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
"""Active in-scope addresses after T1 and after T2, exactly. Any other count is a duplicate
(over-split) or a merge (under-split) of a governed concern."""


# ------------------------------------------------------------------ per-item expectations


def _seed_item(key: str, ledger: LedgerId) -> ItemExpectation:
    document = f"{key}-T1"
    return ItemExpectation(
        document=document,
        ledger=ledger,
        t=1,
        binds=(),
        creates=1,
        new_claims={key: _range(document, key)},
    )


def _revised(
    document: str,
    ledger: LedgerId,
    bind: str,
    *,
    creates: int = 0,
    must_support: tuple[str, ...] = (),
) -> ItemExpectation:
    addresses = {p.address for p in PROPOSITIONS if p.document == document and p.relation in _ADDS}
    return ItemExpectation(
        document=document,
        ledger=ledger,
        t=2,
        binds=(bind,),
        creates=creates,
        new_claims={a: _range(document, a) for a in sorted(addresses)},
        must_support=must_support,
    )


SEED_ITEMS: Final[tuple[ItemExpectation, ...]] = (
    *(_seed_item(k, "core") for k in _CORE_KEYS),
    _seed_item("H", "orion"),
    _seed_item("CANCEL", "jobs"),
    _seed_item("AUDIT", "jobs"),
    *(_seed_item(k, "large") for k in LARGE_KEYS),
)
"""The model-formed T1 items: one creation each, holding the inventory's claims."""

REVISED_ITEMS: Final[tuple[ItemExpectation, ...]] = (
    _revised("PICKUP-T2", "core", "PICKUP", must_support=("PICKUP-1", "PICKUP-2")),
    _revised("LABEL-T2", "core", "LABEL"),
    _revised("WEIGHT-T2", "core", "WEIGHT"),
    _revised("ATTEMPTS-T2", "core", "ATTEMPTS", creates=1),
    _revised("LATE-NOTE-T2", "core", "LATE"),
    _revised("H-T9", "orion", "H", must_support=("H-1", "H-2", "H-3")),
    _revised("CANCEL-NOTE-T2", "jobs", "CANCEL"),
    _revised("HANDBOOK-T2", "conflict", "SESSION"),
    _revised("FAQ-T2", "conflict", "SESSION"),
    _revised("RETURNS-NOTE-T2", "large", "CUSTOMER-REFUND"),
)
"""SUPPORTS_CLAIM is required where ``must_support`` says so (the restatement C1 and the
restated C09 material); elsewhere a SUPPORTS_CLAIM of a restated proposition is permitted,
provided it supports a claim at an address the item is bound to."""


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

BANNED_FACETS: Final = (
    "Sender refund entitlement",
    "How it is governed",
    "Governance",
    "Lifecycle",
    "Who may cancel a job?",
    "Who may cancel a job",
    "How cancellation affects execution attempts",
)
"""Facets v2 and v3 recorded that the canonical projection must make impossible."""


# ------------------------------------------------------------------ cases


_BASE_CASES: Final[tuple[CaseExpectation, ...]] = (
    CaseExpectation(
        id="C0-CORE-SEED",
        title="core formation: pickup, label, weight and delivery-attempt concerns",
        ledger="core",
        structural=(
            "7 active core addresses after T1; one CREATE per T1 document, citing only it",
            "each created address holds 1-2 live claims of its document",
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
            "no new claim cites PICKUP-T2",
            "every earlier live PICKUP claim receives an applied SUPPORTS_CLAIM citing PICKUP-T2",
        ),
        semantic=("Q-T2-PICKUP",),
    ),
    CaseExpectation(
        id="C2-EXTENSION",
        title="compatible extension: LABEL-T2 adds the tracking barcode",
        ledger="core",
        structural=(
            "LABEL-T2 bound once, to LABEL; no CREATE cites it",
            "exactly one new claim cites LABEL-T2, at LABEL; earlier claims stay live",
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
            "POD holds 1-2 claims citing ATTEMPTS-T2; no new claim at ATTEMPTS",
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
            "exactly one new claim cites WEIGHT-T2, at WEIGHT",
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
            "T1: LATE-T1 makes exactly one address",
            "T2: LATE-NOTE-T2 bound once, to LATE; no CREATE cites it (no deadline address)",
            "exactly one new claim cites LATE-NOTE-T2, at LATE; no SUPERSEDE there",
        ),
        semantic=("Q-T1-LATE", "Q-T2-LATE"),
    ),
    CaseExpectation(
        id="C7-C09-REGRESSION",
        title="9P3 C09 (critical gate): repeated cancellation at locus H",
        ledger="orion",
        structural=(
            "T1: exactly one address, holding 1-3 claims citing H-T1",
            "T2: H-T9 bound once, to H; no CREATE; 1-2 new claims, all at H",
            "every T1 claim at H receives an applied SUPPORTS_CLAIM citing H-T9",
            "no SUPERSEDE, no CONFLICTS_WITH, no rejected admission",
        ),
        semantic=("Q-T1-H", "Q-T2-H"),
    ),
    CaseExpectation(
        id="C8-LARGE-WORLD",
        title="scale: 16 model-formed nearby payment concerns, one extension without lineage",
        ledger="large",
        structural=(
            "T1: 16 active addresses, one CREATE per document citing only it",
            "T2: RETURNS-NOTE-T2 bound once, to CUSTOMER-REFUND, to no other; no CREATE",
            "exactly one new claim, at CUSTOMER-REFUND; all 15 others unchanged; "
            "no SUPERSEDE, no CONFLICTS_WITH",
        ),
        semantic=(*(f"Q-T1-{k}" for k in LARGE_KEYS), "Q-T2-CUSTOMER-REFUND"),
    ),
    CaseExpectation(
        id="U1-CANCEL-VS-AUDIT",
        title="separate: job cancellation versus audit-record deletion",
        ledger="jobs",
        structural=(
            "T1: CANCEL-T1 and AUDIT-T1 make two distinct addresses",
            "T2: CANCEL-NOTE-T2 (no lineage) bound once, to CANCEL, never to AUDIT; no CREATE",
            "exactly one new claim, at CANCEL; AUDIT unchanged; no SUPERSEDE",
        ),
        semantic=("Q-T1-CANCEL", "Q-T1-AUDIT", "Q-T2-CANCEL"),
    ),
    CaseExpectation(
        id="U2-LATE-VS-DAMAGE",
        title="separate: late-delivery compensation versus damaged-parcel compensation",
        ledger="core",
        structural=(
            "T1: LATE-T1 and DAMAGE-T1 make two distinct addresses",
            "T2: LATE-NOTE-T2 never bound to DAMAGE; DAMAGE unchanged",
        ),
        semantic=("Q-T1-DAMAGE",),
    ),
    CaseExpectation(
        id="U3-COMPENSATION-VS-SETTLEMENT",
        title="separate: requesting compensation versus the daily bank settlement run",
        ledger="core",
        structural=(
            "T1: LATE-T1 and SETTLEMENT-T1 make two distinct addresses",
            "T2: LATE-NOTE-T2 never bound to SETTLEMENT; SETTLEMENT unchanged",
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

_DISPOSITION_ITEMS: Final[tuple[tuple[str, LedgerId, str], ...]] = (
    ("PICKUP-T2", "core", "C1-RESTATEMENT"),
    ("LABEL-T2", "core", "C2-EXTENSION"),
    ("ATTEMPTS-T2", "core", "C3-NEW-CONCERN"),
    ("WEIGHT-T2", "core", "C4-CORRECTION"),
    ("HANDBOOK-T2", "conflict", "C5-EXISTING-CONFLICT"),
    ("FAQ-T2", "conflict", "C5-EXISTING-CONFLICT"),
    ("LATE-NOTE-T2", "core", "C6-LATE-DELIVERY"),
    ("H-T9", "orion", "C7-C09-REGRESSION"),
    ("RETURNS-NOTE-T2", "large", "C8-LARGE-WORLD"),
    ("CANCEL-NOTE-T2", "jobs", "U1-CANCEL-VS-AUDIT"),
)
"""Every T2 document whose propositions Call 2 must account for, and the case it serves."""

_ACCOUNTING_CASES: Final[tuple[tuple[str, LedgerId, tuple[Literal[1, 2], ...]], ...]] = (
    ("A-CORE-SOURCE-ACCOUNTING", "core", (1, 2)),
    ("A-ORION-SOURCE-ACCOUNTING", "orion", (1, 2)),
    ("A-JOBS-SOURCE-ACCOUNTING", "jobs", (1, 2)),
    ("A-CONFLICT-SOURCE-ACCOUNTING", "conflict", (2,)),
    ("A-LARGE-SOURCE-ACCOUNTING", "large", (1, 2)),
)
"""Per ledger, the timepoints whose Call 2 accounted for sentences (conflict's T1 is seeded)."""

CASES: Final[tuple[CaseExpectation, ...]] = (
    *(
        c.model_copy(
            update={
                "semantic": c.semantic
                + tuple(f"Q-T2-DISP-{d}" for d, _, case in _DISPOSITION_ITEMS if case == c.id)
            }
        )
        for c in _BASE_CASES
    ),
    *(
        CaseExpectation(
            id=case_id,
            title=f"source accounting in ledger {ledger}: no operative sentence set aside",
            ledger=ledger,
            structural=(
                "no call of the ledger refused structurally (PROPOSITION-ACCOUNTING)",
                "every accepted Call 2 recomputes to zero accounting findings",
            ),
            semantic=tuple(f"Q-T{t}-NONOP-{ledger.upper()}" for t in times),
        )
        for case_id, ledger, times in _ACCOUNTING_CASES
    ),
)

CRITICAL_CASE: Final = "C7-C09-REGRESSION"
"""If this case fails the standing is NOT_VALIDATED whatever else passes (also implied by the
all-or-nothing rule; recorded separately so the report cannot bury it)."""

STRUCTURAL_CHECKS: Final = (
    "CANONICAL-FACETS",
    "SOURCE-COVERAGE",
    "PROPOSITION-ACCOUNTING",
)
"""Run-wide structural checks beside the cases, the ledgers and run integrity: every
address and every CREATE/BIND candidate has ``facet == canonical_facet(subject)``, no banned
facet, pairwise-distinct facets per ledger, and no model payload carrying a facet; and the
sealed source-coverage map is complete."""


# ------------------------------------------------------------------ semantic questions


def _statements(ids: tuple[str, ...]) -> str:
    by_id = {p.id: p for p in PROPOSITIONS}
    return "; ".join(f"{i}: {by_id[i].statement}" for i in ids)


def _inventory(address: str) -> tuple[str, ...]:
    """The propositions the address holds after T2 (restatements excluded)."""
    return tuple(p.id for p in PROPOSITIONS if p.address == address and p.relation != "RESTATES")


_CLAIMS_RULE: Final = (
    "is every one of these propositions stated by at least one live claim (a claim may state "
    "more than one of them), and does no live claim state anything that is not one of them "
    "[{listed}]"
)
_SUBJECT_RULE: Final = (
    "does the address subject name the governed concern itself (an act, entity or record, "
    "entitlement, state, decision or operational concern) such that every proposition of the "
    "concern's full sealed inventory [{inventory}] is about it, rather than naming only one "
    "dimension of it (one who, when, limit, amount, deadline, destination, effect or "
    "repetition rule) or a generic word (such as governance, policy, rules or lifecycle)?"
)


def _t1_question(key: str, ledger: LedgerId, case: str) -> SemanticQuestion:
    seeds = tuple(p.id for p in PROPOSITIONS if p.document == f"{key}-T1")
    return SemanticQuestion(
        id=f"Q-T1-{key}",
        case=case,
        ledger=ledger,
        after=1,
        question=(
            f"After T1, in ledger {ledger}, at the address whose CREATE_ADDRESS cites "
            f"{key}-T1: "
            + _CLAIMS_RULE.format(listed=_statements(seeds))
            + "; and "
            + _SUBJECT_RULE.format(inventory=_statements(_inventory(key)))
        ),
    )


def _t2_question(key: str, ledger: LedgerId, case: str, created_from: str) -> SemanticQuestion:
    return SemanticQuestion(
        id=f"Q-T2-{key}",
        case=case,
        ledger=ledger,
        after=2,
        question=(
            f"After T2, in ledger {ledger}, at the address whose CREATE_ADDRESS cites "
            f"{created_from}: " + _CLAIMS_RULE.format(listed=_statements(_inventory(key))) + "?"
        ),
    )


EXPECTED_DISPOSITIONS: Final[dict[str, str]] = {
    p.id: {
        "SEED": "ASSERT_CLAIM",
        "EXTENDS": "ASSERT_CLAIM",
        "NEW_CONCERN": "ASSERT_CLAIM",
        "RESTATES": "SUPPORTS_CLAIM",
        "CORRECTS": "ASSERT_CLAIM + SUPERSEDE",
    }[p.relation]
    for p in PROPOSITIONS
}
"""The sealed disposition of every proposition (design §6): from the existing claim laws."""


def _disposition_question(document: str, ledger: LedgerId, case: str) -> SemanticQuestion:
    listed = "; ".join(
        f"{p.id}: {p.statement} -> {EXPECTED_DISPOSITIONS[p.id]}"
        + (f" (of {p.of})" if p.of else "")
        for p in PROPOSITIONS
        if p.document == document
    )
    return SemanticQuestion(
        id=f"Q-T2-DISP-{document}",
        case=case,
        ledger=ledger,
        after=2,
        question=(
            f"After T2, in ledger {ledger}, in the model's accounting of {document} (its listed "
            "propositions with their sentences, and each disposition's proposition_id): is each "
            "of these sealed propositions represented by a listed proposition whose disposition "
            f"is the one given, with no listed proposition disposed of otherwise [{listed}]? A "
            "SUPPORTS_CLAIM must support the current claim stating the proposition it restates; "
            "an ASSERT_CLAIM must be at the address holding that concern."
        ),
    )


def _non_operative_question(ledger: LedgerId, t: Literal[1, 2], case: str) -> SemanticQuestion:
    documents = [d.key for d in DOCUMENTS.values() if d.ledger == ledger]
    listed = "; ".join(f"{p.id}: {p.statement}" for p in PROPOSITIONS if p.document in documents)
    return SemanticQuestion(
        id=f"Q-T{t}-NONOP-{ledger.upper()}",
        case=case,
        ledger=ledger,
        after=t,
        question=(
            f"After T{t}, in ledger {ledger}, in the model's accounting of this delta: does every "
            "sentence it declared non_operative state none of these sealed propositions, so that "
            f"no operative sentence was set aside [{listed}]?"
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
    _t2_question("PICKUP", "core", "C1-RESTATEMENT", "PICKUP-T1"),
    _t2_question("LABEL", "core", "C2-EXTENSION", "LABEL-T1"),
    SemanticQuestion(
        id="Q-T2-POD",
        case="C3-NEW-CONCERN",
        ledger="core",
        after=2,
        question=(
            "After T2, in ledger core, at the address whose CREATE_ADDRESS cites ATTEMPTS-T2: "
            "does its subject name proof of delivery (the delivery record), not delivery "
            "attempts; and " + _CLAIMS_RULE.format(listed=_statements(("POD-1", "POD-2"))) + "?"
        ),
    ),
    SemanticQuestion(
        id="Q-T2-WEIGHT",
        case="C4-CORRECTION",
        ledger="core",
        after=2,
        question=(
            "After T2, in ledger core, at the address whose CREATE_ADDRESS cites WEIGHT-T1: "
            + _CLAIMS_RULE.format(listed=_statements(("WEIGHT-1", "WEIGHT-2", "WEIGHT-1C")))
            + "; and does the pending SUPERSEDE target the claim stating the 30 kg maximum "
            "(WEIGHT-1), not a claim stating the refusal at pickup (WEIGHT-2)?"
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
    _t2_question("LATE", "core", "C6-LATE-DELIVERY", "LATE-T1"),
    _t2_question("H", "orion", "C7-C09-REGRESSION", "H-T1"),
    _t2_question("CANCEL", "jobs", "U1-CANCEL-VS-AUDIT", "CANCEL-T1"),
    _t2_question("CUSTOMER-REFUND", "large", "C8-LARGE-WORLD", "CUSTOMER-REFUND-T1"),
    *(_disposition_question(d, ledger, case) for d, ledger, case in _DISPOSITION_ITEMS),
    *(
        _non_operative_question(ledger, t, case_id)
        for case_id, ledger, times in _ACCOUNTING_CASES
        for t in times
    ),
)


def expectations_document() -> dict[str, object]:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "propositions": [p.model_dump(mode="json") for p in PROPOSITIONS],
        "source_coverage": source_coverage_document(),
        "addresses": [a.model_dump(mode="json") for a in ADDRESSES],
        "seed_items": [i.model_dump(mode="json") for i in SEED_ITEMS],
        "revised_items": [i.model_dump(mode="json") for i in REVISED_ITEMS],
        "address_counts": {k: list(v) for k, v in EXPECTED_ADDRESS_COUNTS.items()},
        "supersedes": {k: list(v) for k, v in EXPECTED_SUPERSEDES.items()},
        "conflicts": {k: [list(p) for p in v] for k, v in EXPECTED_CONFLICTS.items()},
        "separate": [s.model_dump(mode="json") for s in EXPECTED_SEPARATE],
        "banned_facets": list(BANNED_FACETS),
        "structural_checks": list(STRUCTURAL_CHECKS),
        "expected_dispositions": EXPECTED_DISPOSITIONS,
        "execution_mode": "EXPERIMENT: one attempt per semantic call; a structural refusal "
        "fails the attempt and is never re-proposed",
        "support_rule": "SUPPORTS_CLAIM is required for must_support items (every earlier live "
        "claim at the bound address); elsewhere a support is permitted only at an address the "
        "item is bound to",
        "claim_range_rule": "a document adds, per address, at least one and at most one live "
        "claim per proposition it places there; every proposition must be stated (semantic)",
        "cases": [c.model_dump(mode="json") for c in CASES],
        "critical_case": CRITICAL_CASE,
        "semantic_questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS],
        "standing_rule": "LOCUS_POLICY_VALIDATED iff every case, ledger, canonical-facet, "
        "source-coverage and run-integrity structural check passes (so zero over- and "
        "under-splits), every semantic question is answered YES by the independent "
        "adjudicator from the frozen state of its own ledger and timepoint (so zero missing "
        "propositions), and the critical case C7-C09-REGRESSION passes; otherwise "
        "LOCUS_POLICY_NOT_VALIDATED. No partial pass.",
    }


def adjudication_questions_document() -> dict[str, object]:
    return {"questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS]}


def expectations_sha256() -> str:
    return canonical_sha256(expectations_document())


def adjudication_questions_sha256() -> str:
    return canonical_sha256(adjudication_questions_document())
