"""The hidden answer key of locus validation v2 (design §6, §7). Never model-visible.

Sealed as ``expectations.json`` before any live call and never edited afterwards. It holds:

* the **proposition inventory** of every document: each proposition, the address it
  belongs at and its relation to what is already known. A document is never assumed to
  carry one claim (v1's defect): the expected claim count of an address is the number of
  distinct propositions the inventory places there;
* the **structural expectations** the deterministic evaluator checks (addresses, claims
  per address, binds, creations, new claims, required supports, supersessions, conflicts);
* the **semantic questions** an independent adjudicator answers from the frozen claims.

The request path never imports this module (a test enforces it).
"""

from __future__ import annotations

from typing import Final, Literal

from foundry.domain.common import FrozenModel
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v2.protocol import EXPERIMENT_VERSION, LedgerId

__all__ = [
    "ADDRESSES",
    "CASES",
    "PROPOSITIONS",
    "REVISED_ITEMS",
    "SEED_ITEMS",
    "SEMANTIC_QUESTIONS",
    "AddressExpectation",
    "CaseExpectation",
    "ItemExpectation",
    "Proposition",
    "SemanticQuestion",
    "expectations_document",
    "expectations_sha256",
]

Relation = Literal["SEED", "RESTATES", "EXTENDS", "CORRECTS", "NEW_LOCUS"]


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


class CaseExpectation(FrozenModel):
    id: str
    title: str
    ledger: LedgerId
    structural: tuple[str, ...]
    semantic: tuple[str, ...]


class SemanticQuestion(FrozenModel):
    id: str
    case: str
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


PROPOSITIONS: Final[tuple[Proposition, ...]] = (
    # core, T1 (model seed): two propositions per document
    _p(
        "PICKUP-1",
        "PICKUP-T1",
        "PICKUP",
        "a pickup requested before 14:00 is collected the same working day",
    ),  # noqa: E501
    _p(
        "PICKUP-2",
        "PICKUP-T1",
        "PICKUP",
        "a pickup requested at or after 14:00 is collected the next working day",
    ),  # noqa: E501
    _p("LABEL-1", "LABEL-T1", "LABEL", "every parcel carries a printed label before collection"),
    _p("LABEL-2", "LABEL-T1", "LABEL", "the label shows the destination postcode"),
    _p("WEIGHT-1", "WEIGHT-T1", "WEIGHT", "a single parcel may weigh at most 30 kg"),
    _p("WEIGHT-2", "WEIGHT-T1", "WEIGHT", "a parcel over the weight limit is refused at pickup"),
    _p("ATTEMPTS-1", "ATTEMPTS-T1", "ATTEMPTS", "a courier makes at most two delivery attempts"),
    _p(
        "ATTEMPTS-2",
        "ATTEMPTS-T1",
        "ATTEMPTS",
        "after the second failed attempt the parcel goes to the local depot",
    ),  # noqa: E501
    _p(
        "INSURANCE-1",
        "INSURANCE-T1",
        "INSURANCE",
        "every parcel is insured against loss or damage up to 500 GBP of declared value",
    ),  # noqa: E501
    _p(
        "INSURANCE-2",
        "INSURANCE-T1",
        "INSURANCE",
        "cover above 500 GBP can be bought when the pickup is booked",
    ),  # noqa: E501
    _p(
        "LATE-1",
        "LATE-T1",
        "LATE",
        "a sender whose parcel is delivered late is refunded the shipping fee",
    ),  # noqa: E501
    _p(
        "LATE-2",
        "LATE-T1",
        "LATE",
        "the late-delivery refund is paid to the booking's payment method",
    ),  # noqa: E501
    # core, T2 (revision)
    _p(
        "PICKUP-1R",
        "PICKUP-T2",
        "PICKUP",
        "same-day collection before 2 p.m.",
        "RESTATES",
        "PICKUP-1",
    ),  # noqa: E501
    _p(
        "PICKUP-2R",
        "PICKUP-T2",
        "PICKUP",
        "next-day collection at or after 2 p.m.",
        "RESTATES",
        "PICKUP-2",
    ),  # noqa: E501
    _p("LABEL-1R", "LABEL-T2", "LABEL", "printed label before collection", "RESTATES", "LABEL-1"),
    _p(
        "LABEL-2R",
        "LABEL-T2",
        "LABEL",
        "label shows the destination postcode",
        "RESTATES",
        "LABEL-2",
    ),  # noqa: E501
    _p(
        "LABEL-3",
        "LABEL-T2",
        "LABEL",
        "the label also carries a barcode encoding the tracking number",
        "EXTENDS",
    ),  # noqa: E501
    _p(
        "WEIGHT-1C",
        "WEIGHT-T2",
        "WEIGHT",
        "a single parcel may weigh at most 25 kg",
        "CORRECTS",
        "WEIGHT-1",
    ),  # noqa: E501
    _p(
        "WEIGHT-2R",
        "WEIGHT-T2",
        "WEIGHT",
        "an overweight parcel is refused at pickup",
        "RESTATES",
        "WEIGHT-2",
    ),  # noqa: E501
    _p(
        "ATTEMPTS-1R",
        "ATTEMPTS-T2",
        "ATTEMPTS",
        "at most two delivery attempts",
        "RESTATES",
        "ATTEMPTS-1",
    ),  # noqa: E501
    _p(
        "ATTEMPTS-2R",
        "ATTEMPTS-T2",
        "ATTEMPTS",
        "depot after the second failed attempt",
        "RESTATES",
        "ATTEMPTS-2",
    ),  # noqa: E501
    _p(
        "POD-1",
        "ATTEMPTS-T2",
        "POD",
        "a delivered parcel is recorded with the recipient's signature",
        "NEW_LOCUS",
    ),  # noqa: E501
    _p("POD-2", "ATTEMPTS-T2", "POD", "signature records are kept for 90 days", "NEW_LOCUS"),
    _p(
        "LATE-3",
        "LATE-NOTE-T2",
        "LATE",
        "the late-delivery refund must be requested within 14 days of the promised delivery date",
        "EXTENDS",
    ),  # noqa: E501
    # orion (9P3 locus H), T1 then T9
    _p("H-1", "H-T1", "H", "a producer or operator may cancel a job"),
    _p("H-2", "H-T1", "H", "after cancellation no future execution attempt of the job may start"),
    _p(
        "H-3",
        "H-T1",
        "H",
        "cancellation does not interrupt a running attempt, which runs to its own completion, "
        "failure or timeout",
    ),
    _p("H-1R", "H-T9", "H", "producers and operators can cancel jobs", "RESTATES", "H-1"),
    _p("H-2R", "H-T9", "H", "no future attempt after cancellation", "RESTATES", "H-2"),
    _p("H-3R", "H-T9", "H", "a running attempt is not interrupted", "RESTATES", "H-3"),
    _p(
        "H-4",
        "H-T9",
        "H",
        "a cancellation received for an already-cancelled job leaves it cancelled and changes "
        "nothing else about its state",
        "EXTENDS",
    ),
    # conflict: seeded by the author; T2 restates each side
    _p(
        "SESSION-15R",
        "HANDBOOK-T2",
        "SESSION",
        "an idle session ends after 15 minutes",
        "RESTATES",
        "SESSION-15",
    ),  # noqa: E501
    _p(
        "SESSION-30R",
        "FAQ-T2",
        "SESSION",
        "an idle session ends after 30 minutes",
        "RESTATES",
        "SESSION-30",
    ),  # noqa: E501
    # large world: seeded by the author; T2 extends one of sixteen
    _p(
        "PARTIAL-2",
        "REFUND-UPDATE-T2",
        "PARTIAL",
        "several partial refunds may be issued for the same order",
        "EXTENDS",
    ),  # noqa: E501
)

_LARGE_KEYS: Final = (
    "REQUEST-WINDOW",
    "COMPLETION",
    "METHOD",
    "PARTIAL",
    "APPROVAL",
    "FEE",
    "CHARGEBACK-TIME",
    "CHARGEBACK-EVIDENCE",
    "PAYOUT-SCHEDULE",
    "PAYOUT-MINIMUM",
    "PAYOUT-CURRENCY",
    "CONVERSION",
    "SHIPPING-REFUND",
    "STORE-CREDIT",
    "CANCELLED-ORDER",
    "NOTIFICATION",
)


def _model_t1(key: str, t1: int, t2: int) -> AddressExpectation:
    ledger: LedgerId = "orion" if key == "H" else "core"
    return AddressExpectation(
        key=key,
        ledger=ledger,
        origin="MODEL_T1",
        created_from=f"{key}-T1",
        live_claims_after_t1=t1,
        live_claims_after_t2=t2,
    )


ADDRESSES: Final[tuple[AddressExpectation, ...]] = (
    _model_t1("PICKUP", 2, 2),
    _model_t1("LABEL", 2, 3),
    _model_t1("WEIGHT", 2, 3),
    _model_t1("ATTEMPTS", 2, 2),
    _model_t1("INSURANCE", 2, 2),
    _model_t1("LATE", 2, 3),
    AddressExpectation(
        key="POD",
        ledger="core",
        origin="MODEL_T2",
        created_from="ATTEMPTS-T2",
        live_claims_after_t1=None,
        live_claims_after_t2=2,
    ),
    _model_t1("H", 3, 4),
    AddressExpectation(
        key="SESSION",
        ledger="conflict",
        origin="AUTHOR_SEED",
        created_from=None,
        live_claims_after_t1=2,
        live_claims_after_t2=2,
    ),
    *(
        AddressExpectation(
            key=key,
            ledger="large",
            origin="AUTHOR_SEED",
            created_from=None,
            live_claims_after_t1=1,
            live_claims_after_t2=2 if key == "PARTIAL" else 1,
        )
        for key in _LARGE_KEYS
    ),
)

SEED_ITEMS: Final[tuple[ItemExpectation, ...]] = tuple(
    ItemExpectation(
        document=f"{key}-T1",
        ledger="orion" if key == "H" else "core",
        t=1,
        binds=(),
        creates=1,
        new_claims={key: n},
    )
    for key, n in (
        ("PICKUP", 2),
        ("LABEL", 2),
        ("WEIGHT", 2),
        ("ATTEMPTS", 2),
        ("INSURANCE", 2),
        ("LATE", 2),
        ("H", 3),
    )
)
"""The model-seeded T1 items: one creation each, the inventory's claims at that address."""

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
        document="LABEL-T2",
        ledger="core",
        t=2,
        binds=("LABEL",),
        creates=0,
        new_claims={"LABEL": 1},
    ),
    ItemExpectation(
        document="WEIGHT-T2",
        ledger="core",
        t=2,
        binds=("WEIGHT",),
        creates=0,
        new_claims={"WEIGHT": 1},
    ),
    ItemExpectation(
        document="ATTEMPTS-T2",
        ledger="core",
        t=2,
        binds=("ATTEMPTS",),
        creates=1,
        new_claims={"POD": 2},
    ),
    ItemExpectation(
        document="LATE-NOTE-T2",
        ledger="core",
        t=2,
        binds=("LATE",),
        creates=0,
        new_claims={"LATE": 1},
    ),
    ItemExpectation(
        document="H-T9", ledger="orion", t=2, binds=("H",), creates=0, new_claims={"H": 1}
    ),
    ItemExpectation(
        document="HANDBOOK-T2", ledger="conflict", t=2, binds=("SESSION",), creates=0, new_claims={}
    ),
    ItemExpectation(
        document="FAQ-T2", ledger="conflict", t=2, binds=("SESSION",), creates=0, new_claims={}
    ),
    ItemExpectation(
        document="REFUND-UPDATE-T2",
        ledger="large",
        t=2,
        binds=("PARTIAL",),
        creates=0,
        new_claims={"PARTIAL": 1},
    ),
)

EXPECTED_ADDRESS_COUNTS: Final[dict[LedgerId, tuple[int, int]]] = {
    "core": (6, 7),
    "orion": (1, 1),
    "conflict": (1, 1),
    "large": (16, 16),
}
"""Active in-scope addresses after T1 and after T2."""

EXPECTED_SUPERSEDES: Final[dict[LedgerId, tuple[str, ...]]] = {
    "core": ("WEIGHT",),
    "orion": (),
    "conflict": (),
    "large": (),
}
"""Address keys of the claims a model SUPERSEDE must target: exactly one supersede per
entry, pending (``REQUIRE_SECOND_LENS``), never applied. None anywhere else."""

EXPECTED_CONFLICTS: Final[dict[LedgerId, tuple[tuple[str, str], ...]]] = {
    "core": (),
    "orion": (),
    "conflict": (("SESSION-15", "SESSION-30"),),
    "large": (),
}
"""Seeded-claim key pairs a model CONFLICTS_WITH must name (at least once, pending, never
applied). A conflict naming any other pair, or in any other ledger, fails."""


CASES: Final[tuple[CaseExpectation, ...]] = (
    CaseExpectation(
        id="C0-CORE-SEED",
        title="core world creation: six loci, two propositions each",
        ledger="core",
        structural=(
            "6 active addresses after T1; one CREATE per T1 document, citing only that document",
            "each created address holds exactly its document's 2 inventory claims, all citing it",
            "0 BIND, SUPERSEDE, CONFLICTS_WITH or rejected admissions at T1",
        ),
        semantic=tuple(
            f"Q-SEED-{k}" for k in ("PICKUP", "LABEL", "WEIGHT", "ATTEMPTS", "INSURANCE", "LATE")
        ),
    ),
    CaseExpectation(
        id="C1-RESTATEMENT",
        title="restatement: PICKUP-T2 rewords both current propositions",
        ledger="core",
        structural=(
            "PICKUP-T2 bound once, to PICKUP; no CREATE cites it",
            "no new claim cites PICKUP-T2; PICKUP keeps exactly its 2 claims",
            "each PICKUP claim receives at least one SUPPORTS_CLAIM citing PICKUP-T2",
        ),
        semantic=(),
    ),
    CaseExpectation(
        id="C2-EXTENSION",
        title="compatible extension: LABEL-T2 adds the tracking barcode",
        ledger="core",
        structural=(
            "LABEL-T2 bound once, to LABEL; no CREATE cites it",
            "exactly one new claim cites LABEL-T2, at LABEL; both seed claims stay live (3)",
            "no SUPERSEDE targets a LABEL claim",
        ),
        semantic=("Q-LABEL-EXT",),
    ),
    CaseExpectation(
        id="C3-NEW-LOCUS",
        title="genuine new locus inside a known document: proof of delivery",
        ledger="core",
        structural=(
            "ATTEMPTS-T2 bound once, to ATTEMPTS, and exactly one CREATE cites it (POD)",
            "POD holds exactly 2 claims, both citing ATTEMPTS-T2; no new claim at ATTEMPTS",
            "7 active addresses after T2",
        ),
        semantic=("Q-POD",),
    ),
    CaseExpectation(
        id="C4-CORRECTION",
        title="correction: WEIGHT-T2 lowers the limit from 30 kg to 25 kg",
        ledger="core",
        structural=(
            "WEIGHT-T2 bound once, to WEIGHT; no CREATE cites it",
            "exactly one new claim cites WEIGHT-T2, at WEIGHT; WEIGHT live claims == 3",
            "exactly one SUPERSEDE in the ledger, targeting a WEIGHT seed claim, routed "
            "REQUIRE_SECOND_LENS and never applied; no CONFLICTS_WITH",
        ),
        semantic=("Q-WEIGHT-CORR",),
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
        semantic=(),
    ),
    CaseExpectation(
        id="C6-NEARBY",
        title="nearby but different: late-delivery refund versus insurance cover",
        ledger="core",
        structural=(
            "INSURANCE-T1 and LATE-T1 created as two distinct addresses",
            "LATE-NOTE-T2 bound once, to LATE, never to INSURANCE; no CREATE cites it",
            "exactly one new claim cites LATE-NOTE-T2, at LATE; INSURANCE unchanged (2)",
        ),
        semantic=("Q-LATE-EXT",),
    ),
    CaseExpectation(
        id="C7-C09-REGRESSION",
        title="9P3 C09: repeated cancellation at locus H",
        ledger="orion",
        structural=(
            "T1: exactly one address H, holding exactly the 3 inventory claims citing H-T1",
            "T2: H-T9 bound once, to H; no CREATE; exactly one new claim at H (4 live)",
            "no SUPERSEDE, no CONFLICTS_WITH, no rejected admission",
        ),
        semantic=("Q-H-SEED", "Q-H-EXT"),
    ),
    CaseExpectation(
        id="C8-LARGE-WORLD",
        title="scale: one compatible extension among 16 nearby refund and payout loci",
        ledger="large",
        structural=(
            "REFUND-UPDATE-T2 bound once, to PARTIAL, and to no distractor; no CREATE",
            "exactly one new claim, at PARTIAL (2 live); every other address unchanged (1)",
            "16 active addresses; no SUPERSEDE, no CONFLICTS_WITH",
        ),
        semantic=("Q-LARGE-EXT",),
    ),
)


def _seed_question(key: str, document: str) -> SemanticQuestion:
    listed = "; ".join(
        f"{p.id}: {p.statement}"
        for p in PROPOSITIONS
        if p.document == document and p.relation == "SEED"
    )
    return SemanticQuestion(
        id=f"Q-SEED-{key}",
        case="C0-CORE-SEED",
        question=(
            f"At the address created from {document}: does each live claim state exactly one of "
            f"these propositions, with every proposition stated by exactly one claim and no "
            f"claim stating anything else [{listed}]; and does the address facet name a "
            "locus-level question rather than one proposition's value?"
        ),
    )


SEMANTIC_QUESTIONS: Final[tuple[SemanticQuestion, ...]] = (
    *(
        _seed_question(k, f"{k}-T1")
        for k in ("PICKUP", "LABEL", "WEIGHT", "ATTEMPTS", "INSURANCE", "LATE")
    ),
    SemanticQuestion(
        id="Q-LABEL-EXT",
        case="C2-EXTENSION",
        question="Does the new claim at LABEL state that the label carries a barcode encoding "
        "the parcel's tracking number (LABEL-3), and nothing that contradicts LABEL-1/LABEL-2?",
    ),
    SemanticQuestion(
        id="Q-POD",
        case="C3-NEW-LOCUS",
        question="Do the new address's subject/facet denote proof of delivery (not delivery "
        "attempts), and do its two claims state POD-1 (signature recorded on delivery) and "
        "POD-2 (signature records kept 90 days), one each?",
    ),
    SemanticQuestion(
        id="Q-WEIGHT-CORR",
        case="C4-CORRECTION",
        question="Does the new claim at WEIGHT state a 25 kg maximum (WEIGHT-1C), and does the "
        "SUPERSEDE target the claim stating the 30 kg maximum (WEIGHT-1), not the refusal "
        "claim (WEIGHT-2)?",
    ),
    SemanticQuestion(
        id="Q-LATE-EXT",
        case="C6-NEARBY",
        question="Does the new claim at LATE state that the late-delivery refund must be "
        "requested within 14 days of the promised delivery date (LATE-3)?",
    ),
    SemanticQuestion(
        id="Q-H-SEED",
        case="C7-C09-REGRESSION",
        question="Do H's three T1 claims state H-1 (producer or operator may cancel), H-2 (no "
        "future attempt after cancellation) and H-3 (a running attempt is not interrupted), one "
        "each; and does H's facet name the locus-level question about cancellation rather than "
        "only its effect on execution attempts?",
    ),
    SemanticQuestion(
        id="Q-H-EXT",
        case="C7-C09-REGRESSION",
        question="Does the new claim at H state that a cancellation received for an "
        "already-cancelled job leaves it cancelled and changes nothing else about its state "
        "(H-4)?",
    ),
    SemanticQuestion(
        id="Q-LARGE-EXT",
        case="C8-LARGE-WORLD",
        question="Does the new claim at PARTIAL state that several partial refunds may be "
        "issued for the same order (PARTIAL-2)?",
    ),
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
        "cases": [c.model_dump(mode="json") for c in CASES],
        "semantic_questions": [q.model_dump(mode="json") for q in SEMANTIC_QUESTIONS],
        "standing_rule": "LOCUS_POLICY_VALIDATED iff every case's structural checks pass, every "
        "semantic question is answered YES by the independent adjudicator, and every run "
        "integrity check passes; otherwise LOCUS_POLICY_NOT_VALIDATED",
    }


def expectations_sha256() -> str:
    return canonical_sha256(expectations_document())
