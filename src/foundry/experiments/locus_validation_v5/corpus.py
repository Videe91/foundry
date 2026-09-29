"""Model-visible world of locus validation v5 (design §4, §5).

Only what the model may see lives here: documents (with ids, lineage and scope) and the one
deterministic seed world (``conflict``), whose address and claims the model is shown as
known state. It never imports the hidden answer key (``expectations``). Every text is a
literal.

Every text is validation v3's and v4's, byte for byte (only the evidence ids are new), so
the model, the inputs and the two-call pipeline are those under which ``intent-v2-locus-v1``
(v2), ``-v2`` (v3) and ``-v3`` (v4) were measured, and the policy is the only variable:

* ``orion`` reproduces 9P3 locus H byte for byte (T1 section 8 and T9 "cancelling a job"),
  the historical C09 regression;
* ``core``'s late-delivery documents are the exact bytes that over-split in v2 (C6);
* ``jobs`` and ``large`` are v3's and v4's; every ``large`` address is formed by the model.

The one seeded address (``conflict``) is written with the canonical facet of its subject,
because every governor runs ``AdmissionPolicy(canonical_facets=True)``.
"""

from __future__ import annotations

from typing import Final

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import canonical_facet
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v5.protocol import (
    OBSERVED_AT,
    PROJECT_IDS,
    SCOPES,
    LedgerId,
)
from foundry.experiments.long_horizon_bounded.timeline import SECTION_TEXT

__all__ = [
    "AUTHOR",
    "DOCUMENTS",
    "REVISION",
    "SEED_DOCUMENTS",
    "SEED_WORLDS",
    "Document",
    "SeedAddress",
    "SeedClaim",
    "corpus_record",
    "corpus_sha256",
    "evidence",
    "revision_delta",
    "seed_delta",
]

AUTHOR: Final = "human://validation-author"


class Document(FrozenModel):
    key: str
    ledger: LedgerId
    evidence_id: str
    artifact_ref: str
    text: str
    supersedes: str | None = None
    """``evidence_id`` of the earlier version of the same artifact, when this is a revision."""


class SeedClaim(FrozenModel):
    key: str
    predicate: str
    text: str
    document: str


class SeedAddress(FrozenModel):
    key: str
    subject: str
    facet: str
    claims: tuple[SeedClaim, ...]


def _doc(
    key: str, ledger: LedgerId, ref: str, text: str, *, supersedes: str | None = None
) -> Document:
    return Document(
        key=key,
        ledger=ledger,
        evidence_id=f"EV-LV5-{key}",
        artifact_ref=ref,
        text=text,
        supersedes=supersedes,
    )


# --------------------------------------------------------------------------- core


_CORE_T1: Final = (
    _doc(
        "PICKUP-T1",
        "core",
        "dispatch/spec/pickup-cutoff.md",
        "## Pickup cut-off\n\n"
        "Rules\n"
        "1. A pickup requested before 14:00 local time is collected on the same working day.\n"
        "2. A pickup requested at or after 14:00 local time is collected on the next working day.",
    ),
    _doc(
        "LABEL-T1",
        "core",
        "dispatch/spec/parcel-label.md",
        "## Parcel label\n\n"
        "Rules\n"
        "1. Every parcel must carry a printed label before it is collected.\n"
        "2. The label shows the destination postcode.",
    ),
    _doc(
        "WEIGHT-T1",
        "core",
        "dispatch/spec/weight-limit.md",
        "## Parcel weight limit\n\n"
        "Rules\n"
        "1. A single parcel may weigh at most 30 kg.\n"
        "2. A parcel over the weight limit is refused at pickup.",
    ),
    _doc(
        "ATTEMPTS-T1",
        "core",
        "dispatch/spec/delivery-attempts.md",
        "## Delivery attempts\n\n"
        "Rules\n"
        "1. A courier makes at most two delivery attempts per parcel.\n"
        "2. After the second failed attempt the parcel is taken to the local depot.",
    ),
    _doc(
        "LATE-T1",
        "core",
        "dispatch/spec/late-delivery-compensation.md",
        "## Late delivery compensation\n\n"
        "Rules\n"
        "1. If a parcel is delivered later than the promised date, the sender is refunded the "
        "shipping fee.\n"
        "2. The refund is paid to the payment method used for the booking.",
    ),
    _doc(
        "DAMAGE-T1",
        "core",
        "dispatch/spec/damaged-parcel-compensation.md",
        "## Damaged parcel compensation\n\n"
        "Rules\n"
        "1. A sender whose parcel arrives damaged is refunded the declared value of the "
        "contents.\n"
        "2. The damage must be reported within 48 hours of delivery.",
    ),
    _doc(
        "SETTLEMENT-T1",
        "core",
        "dispatch/finance/daily-bank-settlement.md",
        "## Daily bank settlement\n\n"
        "Rules\n"
        "1. Approved compensation payments are sent to the bank in a settlement run at 17:00 "
        "on each working day.\n"
        "2. A payment approved after 17:00 is sent in the next working day's settlement run.",
    ),
)

_CORE_T2: Final = (
    _doc(
        "PICKUP-T2",
        "core",
        "dispatch/spec/pickup-cutoff.md",
        "## Pickup cut-off\n\n"
        "Rules\n"
        "1. Collection happens on the same working day for any pickup booked earlier than 2 p.m. "
        "local time.\n"
        "2. Pickups booked at 2 p.m. local time or later are collected on the following working "
        "day.",
        supersedes="EV-LV5-PICKUP-T1",
    ),
    _doc(
        "LABEL-T2",
        "core",
        "dispatch/spec/parcel-label.md",
        "## Parcel label\n\n"
        "Rules\n"
        "1. Every parcel must carry a printed label before it is collected.\n"
        "2. The label shows the destination postcode.\n"
        "3. The label also carries a barcode that encodes the parcel's tracking number.",
        supersedes="EV-LV5-LABEL-T1",
    ),
    _doc(
        "WEIGHT-T2",
        "core",
        "dispatch/spec/weight-limit.md",
        "## Parcel weight limit\n\n"
        "Rules\n"
        "1. A single parcel may weigh at most 25 kg.\n"
        "2. A parcel over the weight limit is refused at pickup.",
        supersedes="EV-LV5-WEIGHT-T1",
    ),
    _doc(
        "ATTEMPTS-T2",
        "core",
        "dispatch/spec/delivery-attempts.md",
        "## Delivery attempts\n\n"
        "Rules\n"
        "1. A courier makes at most two delivery attempts per parcel.\n"
        "2. After the second failed attempt the parcel is taken to the local depot.\n\n"
        "## Proof of delivery\n\n"
        "Rules\n"
        "3. A delivered parcel is recorded with the recipient's signature.\n"
        "4. Signature records are kept for 90 days.",
        supersedes="EV-LV5-ATTEMPTS-T1",
    ),
    _doc(
        "LATE-NOTE-T2",
        "core",
        "dispatch/support/claims-handling-note.md",
        "## Late delivery claims\n\n"
        "A sender must ask for the late-delivery refund within 14 days of the promised delivery "
        "date.",
    ),
)


# --------------------------------------------------------------------------- orion (9P3 H)


_ORION_T1: Final = (_doc("H-T1", "orion", "orion/spec/H-cancellation.md", SECTION_TEXT[(1, "H")]),)
"""9P3's sealed T1 locus-H bytes (EV-O-H01, sha256 verified by a test), imported, not retyped."""

_ORION_T2: Final = (
    _doc(
        "H-T9",
        "orion",
        "orion/spec/H-cancellation.md",
        SECTION_TEXT[(9, "H")],
        supersedes="EV-LV5-H-T1",
    ),
)
"""9P3's sealed T9 locus-H bytes (EV-O-H09): the repeated-cancellation proposition."""


# --------------------------------------------------------------------------- jobs


_JOBS_T1: Final = (
    _doc(
        "CANCEL-T1",
        "jobs",
        "scheduler/spec/job-cancellation.md",
        "## Cancelling a scheduled job\n\n"
        "Rules\n"
        "1. The owner of a scheduled job, or an administrator, may cancel it.\n"
        "2. Once a job is cancelled, none of its future runs is started.",
    ),
    _doc(
        "AUDIT-T1",
        "jobs",
        "scheduler/spec/job-audit-records.md",
        "## Job audit records\n\n"
        "Rules\n"
        "1. A job's audit record is deleted automatically 30 days after the job ends.\n"
        "2. Only a compliance officer may delete a job's audit record earlier.",
    ),
)

_JOBS_T2: Final = (
    _doc(
        "CANCEL-NOTE-T2",
        "jobs",
        "scheduler/ops/operator-note.md",
        "## Operator note\n\nA request to cancel a job that has already finished is refused.",
    ),
)


# --------------------------------------------------------------------------- conflict


_CONFLICT_SEED_DOCS: Final = (
    _doc(
        "HANDBOOK-T1",
        "conflict",
        "portal/security-handbook.md",
        "## Session security\n\nAn idle customer-portal session expires after 15 minutes.",
    ),
    _doc(
        "FAQ-T1",
        "conflict",
        "portal/product-faq.md",
        "# Customer portal FAQ\n\n"
        "Q: How long can a portal session stay idle?\n"
        "A: An idle session expires after 30 minutes.",
    ),
)

_CONFLICT_T2: Final = (
    _doc(
        "HANDBOOK-T2",
        "conflict",
        "portal/security-handbook.md",
        "## Session security\n\n"
        "Customer-portal sessions are ended after 15 minutes without any activity.",
        supersedes="EV-LV5-HANDBOOK-T1",
    ),
    _doc(
        "FAQ-T2",
        "conflict",
        "portal/product-faq.md",
        "# Customer portal FAQ\n\n"
        "Q: How long can a portal session stay idle?\n"
        "A: A session that stays idle for 30 minutes is ended.",
        supersedes="EV-LV5-FAQ-T1",
    ),
)

_CONFLICT_WORLD: Final = (
    SeedAddress(
        key="SESSION",
        subject="Idle customer-portal session expiry",
        facet=canonical_facet("Idle customer-portal session expiry"),
        claims=(
            SeedClaim(
                key="SESSION-15",
                predicate="idle time before the session ends",
                text="an idle session expires after 15 minutes",
                document="HANDBOOK-T1",
            ),
            SeedClaim(
                key="SESSION-30",
                predicate="idle time before the session ends",
                text="an idle session expires after 30 minutes",
                document="FAQ-T1",
            ),
        ),
    ),
)


# --------------------------------------------------------------------------- large world


_LARGE_ROWS: Final[tuple[tuple[str, str, str], ...]] = (
    # key, artifact, text
    (
        "CUSTOMER-REFUND",
        "payments/policy/returned-order-refunds.md",
        "## Refunds for returned orders\n\n"
        "A customer who returns an order is refunded the price paid for the returned items.",
    ),
    (
        "SUPPLIER-OVERPAYMENT",
        "payments/policy/supplier-overpayments.md",
        "## Supplier overpayments\n\n"
        "A supplier that has been paid more than its invoice total must pay the excess back.",
    ),
    (
        "CHARGEBACK",
        "payments/policy/chargeback-responses.md",
        "## Chargeback responses\n\n"
        "A chargeback must be answered within 7 days of the card network's notice.",
    ),
    (
        "PAYOUT",
        "payments/policy/seller-payouts.md",
        "## Seller payouts\n\n"
        "Sellers are paid out every Friday. A payout is made only when the seller's balance is "
        "at least 20 GBP.",
    ),
    (
        "CONVERSION",
        "payments/policy/currency-conversion.md",
        "## Currency conversion\n\n"
        "A payment made in a foreign currency is converted at that day's reference exchange rate.",
    ),
    (
        "STORE-CREDIT",
        "payments/policy/store-credit.md",
        "## Store credit\n\nStore credit expires 12 months after it is issued.",
    ),
    (
        "GIFT-CARD",
        "payments/policy/gift-cards.md",
        "## Gift cards\n\nA gift card can pay for any order. A gift card balance never expires.",
    ),
    (
        "INVOICE",
        "payments/policy/business-invoices.md",
        "## Business invoices\n\nEvery order placed by a business customer receives a VAT invoice.",
    ),
    (
        "RETRY",
        "payments/policy/failed-subscription-payments.md",
        "## Failed subscription payments\n\n"
        "A failed subscription payment is tried again 3 days later. It is tried again at most "
        "three times.",
    ),
    (
        "CARD-CHECK",
        "payments/policy/saving-a-payment-card.md",
        "## Saving a payment card\n\n"
        "A new payment card is checked with a zero-amount authorisation before it is saved.",
    ),
    (
        "FRAUD-HOLD",
        "payments/policy/fraud-review-holds.md",
        "## Fraud review holds\n\n"
        "An order flagged by fraud screening is held until an analyst has reviewed it.",
    ),
    (
        "CAPTURE",
        "payments/policy/card-payment-capture.md",
        "## Card payment capture\n\n"
        "A card payment is captured when the order is dispatched, not when it is placed.",
    ),
    (
        "SELLER-LIMIT",
        "payments/policy/new-seller-payment-limit.md",
        "## New seller payment limit\n\n"
        "A new seller account may receive at most 1,000 GBP in payments during its first 30 days.",
    ),
    (
        "PRICE-VAT",
        "payments/policy/displayed-prices.md",
        "## Displayed prices\n\nPrices shown to consumers include VAT.",
    ),
    (
        "INSTALMENTS",
        "payments/policy/instalment-plans.md",
        "## Instalment plans\n\nAn order may be paid in three monthly instalments.",
    ),
    (
        "PROMO",
        "payments/policy/promotional-codes.md",
        "## Promotional codes\n\nOnly one promotional code can be applied to an order.",
    ),
)

_LARGE_T1: Final = tuple(_doc(f"{key}-T1", "large", ref, text) for key, ref, text in _LARGE_ROWS)

_LARGE_T2: Final = (
    _doc(
        "RETURNS-NOTE-T2",
        "large",
        "payments/ops/returns-desk-note.md",
        "## Returns desk note\n\n"
        "The original delivery charge is also repaid to a customer who returns an order.",
    ),
)


# --------------------------------------------------------------------------- index


SEED_DOCUMENTS: Final[dict[LedgerId, tuple[Document, ...]]] = {
    "core": _CORE_T1,
    "orion": _ORION_T1,
    "jobs": _JOBS_T1,
    "conflict": _CONFLICT_SEED_DOCS,
    "large": _LARGE_T1,
}
"""T1 documents: a model delta for ``MODEL_SEEDED`` ledgers, ingested by the seed author
for ``conflict``."""

SEED_WORLDS: Final[dict[LedgerId, tuple[SeedAddress, ...]]] = {
    "conflict": _CONFLICT_WORLD,
}
"""The one deterministically seeded address and its two claims (design §4.4)."""

REVISION: Final[dict[LedgerId, tuple[Document, ...]]] = {
    "core": _CORE_T2,
    "orion": _ORION_T2,
    "jobs": _JOBS_T2,
    "conflict": _CONFLICT_T2,
    "large": _LARGE_T2,
}
"""The T2 delta of every ledger: always two model calls."""

DOCUMENTS: Final[dict[str, Document]] = {
    d.key: d for group in (*SEED_DOCUMENTS.values(), *REVISION.values()) for d in group
}


def evidence(document: Document) -> EvidenceItem:
    return evidence_item(
        evidence_id=document.evidence_id,
        project_id=PROJECT_IDS[document.ledger],
        source_kind=SourceKind.HUMAN,
        source_ref=AUTHOR,
        content=document.text,
        observed_at=OBSERVED_AT,
        scope=(SCOPES[document.ledger],),
        artifact_ref=document.artifact_ref,
        supersedes_evidence_id=document.supersedes,
    )


def seed_delta(ledger: LedgerId) -> tuple[EvidenceItem, ...]:
    return tuple(evidence(d) for d in SEED_DOCUMENTS[ledger])


def revision_delta(ledger: LedgerId) -> tuple[EvidenceItem, ...]:
    return tuple(evidence(d) for d in REVISION[ledger])


def corpus_record() -> dict[str, object]:
    """Everything model-visible, canonically: documents and the seed world."""
    return {
        "documents": [d.model_dump(mode="json") for d in DOCUMENTS.values()],
        "seed_worlds": {
            ledger: [a.model_dump(mode="json") for a in world]
            for ledger, world in SEED_WORLDS.items()
        },
    }


def corpus_sha256() -> str:
    return canonical_sha256(corpus_record())
