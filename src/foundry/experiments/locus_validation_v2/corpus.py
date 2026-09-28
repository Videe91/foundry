"""Model-visible world of locus validation v2 (design §4, §5).

Only what the model may see lives here: documents (with ids, lineage and scope) and the
deterministic seed worlds, whose addresses and claims the model is shown as known state.
It never imports the hidden answer key (``expectations``). Every text is a literal.

Ledger ``orion`` reproduces 9P3 locus H verbatim (T1 section 8 and T9 "cancelling a job"),
a regression case exempt from v1's non-reuse rule. Every other text is new.
"""

from __future__ import annotations

from typing import Final

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v2.protocol import (
    OBSERVED_AT,
    PROJECT_IDS,
    SCOPES,
    LedgerId,
)
from foundry.experiments.long_horizon_bounded.timeline import SECTION_TEXT

__all__ = [
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
        evidence_id=f"EV-LV2-{key}",
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
        "INSURANCE-T1",
        "core",
        "dispatch/spec/insurance.md",
        "## Parcel insurance cover\n\n"
        "Rules\n"
        "1. Every parcel is insured against loss or damage up to 500 GBP of declared value.\n"
        "2. Cover above 500 GBP can be bought when the pickup is booked.",
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
        supersedes="EV-LV2-PICKUP-T1",
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
        supersedes="EV-LV2-LABEL-T1",
    ),
    _doc(
        "WEIGHT-T2",
        "core",
        "dispatch/spec/weight-limit.md",
        "## Parcel weight limit\n\n"
        "Rules\n"
        "1. A single parcel may weigh at most 25 kg.\n"
        "2. A parcel over the weight limit is refused at pickup.",
        supersedes="EV-LV2-WEIGHT-T1",
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
        supersedes="EV-LV2-ATTEMPTS-T1",
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
        supersedes="EV-LV2-H-T1",
    ),
)
"""9P3's sealed T9 locus-H bytes (EV-O-H09): the repeated-cancellation compatible extension."""


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
        supersedes="EV-LV2-HANDBOOK-T1",
    ),
    _doc(
        "FAQ-T2",
        "conflict",
        "portal/product-faq.md",
        "# Customer portal FAQ\n\n"
        "Q: How long can a portal session stay idle?\n"
        "A: A session that stays idle for 30 minutes is ended.",
        supersedes="EV-LV2-FAQ-T1",
    ),
)

_CONFLICT_WORLD: Final = (
    SeedAddress(
        key="SESSION",
        subject="Customer portal session",
        facet="When does an idle customer-portal session expire?",
        claims=(
            SeedClaim(
                key="SESSION-15",
                predicate="idle session expiry",
                text="an idle session expires after 15 minutes",
                document="HANDBOOK-T1",
            ),
            SeedClaim(
                key="SESSION-30",
                predicate="idle session expiry",
                text="an idle session expires after 30 minutes",
                document="FAQ-T1",
            ),
        ),
    ),
)


# --------------------------------------------------------------------------- large world


_LARGE_ROWS: Final[tuple[tuple[str, str, str, str, str, str], ...]] = (
    # key, artifact, subject, facet, predicate, proposition
    (
        "REQUEST-WINDOW",
        "payments/policy/refund-request-window.md",
        "Refund request window",
        "Within how long after purchase may a refund be requested?",
        "refund request deadline",
        "a refund may be requested up to 30 days after purchase",
    ),
    (
        "COMPLETION",
        "payments/policy/refund-completion.md",
        "Refund completion time",
        "How quickly is an approved refund completed?",
        "refund completion time",
        "an approved refund is completed within 10 working days",
    ),
    (
        "METHOD",
        "payments/policy/refund-method.md",
        "Refund payment method",
        "Where is a refund paid?",
        "refund destination",
        "a refund is paid to the original payment method",
    ),
    (
        "PARTIAL",
        "payments/policy/partial-refunds.md",
        "Partial refunds",
        "When and how may part of an order be refunded?",
        "partial refund availability",
        "a refund may cover only part of an order",
    ),
    (
        "APPROVAL",
        "payments/policy/refund-approval.md",
        "Refund approval",
        "Who must approve a refund?",
        "supervisor approval threshold",
        "a refund above 200 GBP needs a supervisor's approval",
    ),
    (
        "FEE",
        "payments/policy/refund-fee.md",
        "Refund processing fee",
        "Is a fee charged for processing a refund?",
        "refund processing fee",
        "no fee is charged for processing a refund",
    ),
    (
        "CHARGEBACK-TIME",
        "payments/policy/chargeback-response-time.md",
        "Chargeback response time",
        "How quickly must a chargeback be answered?",
        "chargeback response deadline",
        "a chargeback must be answered within 7 days of the notice",
    ),
    (
        "CHARGEBACK-EVIDENCE",
        "payments/policy/chargeback-evidence.md",
        "Chargeback evidence",
        "What must a chargeback response contain?",
        "required chargeback evidence",
        "a chargeback response must include the order's delivery record",
    ),
    (
        "PAYOUT-SCHEDULE",
        "payments/policy/payout-schedule.md",
        "Seller payout schedule",
        "When are sellers paid out?",
        "payout day",
        "seller payouts are made every Friday",
    ),
    (
        "PAYOUT-MINIMUM",
        "payments/policy/payout-minimum.md",
        "Seller payout minimum",
        "What balance is needed before a payout is made?",
        "minimum payout balance",
        "a payout is made only when the balance is at least 20 GBP",
    ),
    (
        "PAYOUT-CURRENCY",
        "payments/policy/payout-currency.md",
        "Seller payout currency",
        "In which currency are payouts made?",
        "payout currency",
        "payouts are made in the seller's registered currency",
    ),
    (
        "CONVERSION",
        "payments/policy/currency-conversion.md",
        "Currency conversion",
        "Which exchange rate is used for conversions?",
        "conversion rate source",
        "a conversion uses the daily reference rate at the time of payment",
    ),
    (
        "SHIPPING-REFUND",
        "payments/policy/shipping-cost-refunds.md",
        "Refund of shipping costs",
        "When are shipping costs refunded?",
        "shipping cost refund condition",
        "shipping costs are refunded only when the whole order is returned",
    ),
    (
        "STORE-CREDIT",
        "payments/policy/store-credit.md",
        "Store credit instead of a refund",
        "May a customer take store credit instead of a refund?",
        "store credit option",
        "a customer may choose store credit instead of a refund",
    ),
    (
        "CANCELLED-ORDER",
        "payments/policy/cancelled-order-refunds.md",
        "Refunds for cancelled orders",
        "How is an order cancelled before dispatch refunded?",
        "cancelled order refund",
        "an order cancelled before dispatch is refunded in full automatically",
    ),
    (
        "NOTIFICATION",
        "payments/policy/refund-notifications.md",
        "Refund notifications",
        "How is a customer told about a refund?",
        "refund completion notice",
        "the customer is emailed when a refund is completed",
    ),
)

_LARGE_SEED_DOCS: Final = tuple(
    _doc(f"{key}-T1", "large", ref, f"## {subject}\n\n{text[0].upper()}{text[1:]}.")
    for key, ref, subject, _facet, _predicate, text in _LARGE_ROWS
)

_LARGE_WORLD: Final = tuple(
    SeedAddress(
        key=key,
        subject=subject,
        facet=facet,
        claims=(SeedClaim(key=key, predicate=predicate, text=text, document=f"{key}-T1"),),
    )
    for key, _ref, subject, facet, predicate, text in _LARGE_ROWS
)

_LARGE_T2: Final = (
    _doc(
        "REFUND-UPDATE-T2",
        "large",
        "payments/ops/refund-handling-update.md",
        "## Refund handling update\n\nSeveral partial refunds may be issued for the same order.",
    ),
)


# --------------------------------------------------------------------------- index


SEED_DOCUMENTS: Final[dict[LedgerId, tuple[Document, ...]]] = {
    "core": _CORE_T1,
    "orion": _ORION_T1,
    "conflict": _CONFLICT_SEED_DOCS,
    "large": _LARGE_SEED_DOCS,
}
"""T1 documents: a model delta for ``MODEL_SEEDED`` ledgers, ingested by the seed author
for the others."""

SEED_WORLDS: Final[dict[LedgerId, tuple[SeedAddress, ...]]] = {
    "conflict": _CONFLICT_WORLD,
    "large": _LARGE_WORLD,
}
"""The deterministically seeded addresses and claims (design §4.3, §4.4)."""

REVISION: Final[dict[LedgerId, tuple[Document, ...]]] = {
    "core": _CORE_T2,
    "orion": _ORION_T2,
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
    """Everything model-visible, canonically: documents and seed worlds."""
    return {
        "documents": [d.model_dump(mode="json") for d in DOCUMENTS.values()],
        "seed_worlds": {
            ledger: [a.model_dump(mode="json") for a in world]
            for ledger, world in SEED_WORLDS.items()
        },
    }


def corpus_sha256() -> str:
    return canonical_sha256(corpus_record())
