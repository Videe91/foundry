"""Model-visible world of locus validation v6 (design §4, §5).

Only what the model may see lives here: documents (with ids, lineage and scope) and the one
deterministic seed world (``conflict``). It never imports the hidden answer key
(``expectations``). Every text is a literal or an import of already-sealed bytes.

* ``core``, ``orion``, ``jobs``, ``conflict`` and ``large`` carry validation v5's documents
  byte for byte under new evidence ids (``EV-LV6-``): the C09 (9P3 locus H), C6 late-delivery
  and U1-U4 separation regressions, measured again under the current architecture;
* ``dense`` is a new held-out domain (a car-sharing service specification): fifteen T1
  sections of long-horizon T1 density, a T2 delta and a T3 delta. Its sections were written so
  that several sections govern one thing and nearby sections govern different things; the
  answer key that says which is which lives in ``expectations`` only.
"""

from __future__ import annotations

from typing import Final

from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation_v5 import corpus as v5
from foundry.experiments.locus_validation_v6.protocol import (
    OBSERVED_AT,
    PROJECT_IDS,
    SCOPES,
    LedgerId,
)

__all__ = [
    "AUTHOR",
    "DOCUMENTS",
    "REVISION",
    "SEED_DOCUMENTS",
    "SEED_WORLDS",
    "T3_DOCUMENTS",
    "V5_REUSED",
    "Document",
    "SeedAddress",
    "SeedClaim",
    "corpus_record",
    "corpus_sha256",
    "evidence",
    "revision_delta",
    "seed_delta",
    "t3_delta",
]

AUTHOR: Final = "human://validation-author"


class Document(FrozenModel):
    key: str
    ledger: LedgerId
    t: int
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


def _evidence_id(key: str) -> str:
    return f"EV-LV6-{key}"


# --------------------------------------------------------------------------- v5 regressions


def _reuse(t: int, old: v5.Document) -> Document:
    return Document(
        key=old.key,
        ledger=old.ledger,
        t=t,
        evidence_id=_evidence_id(old.key),
        artifact_ref=old.artifact_ref,
        text=old.text,
        supersedes=None if old.supersedes is None else _evidence_id(_V5_KEY[old.supersedes]),
    )


_V5_KEY: Final = {d.evidence_id: d.key for d in v5.DOCUMENTS.values()}

V5_REUSED: Final[dict[str, str]] = {key: key for key in v5.DOCUMENTS}
"""v6 document key -> v5 document key: every v5 text, byte for byte (verified by a test)."""

_V5_T1: Final[dict[LedgerId, tuple[Document, ...]]] = {
    ledger: tuple(_reuse(1, d) for d in docs) for ledger, docs in v5.SEED_DOCUMENTS.items()
}
_V5_T2: Final[dict[LedgerId, tuple[Document, ...]]] = {
    ledger: tuple(_reuse(2, d) for d in docs) for ledger, docs in v5.REVISION.items()
}
_CONFLICT_WORLD: Final = tuple(
    SeedAddress(
        key=a.key,
        subject=a.subject,
        facet=a.facet,
        claims=tuple(
            SeedClaim(key=c.key, predicate=c.predicate, text=c.text, document=c.document)
            for c in a.claims
        ),
    )
    for a in v5.SEED_WORLDS["conflict"]
)


# --------------------------------------------------------------------------- dense (held out)


def _dense(key: str, t: int, ref: str, text: str, supersedes: str | None = None) -> Document:
    return Document(
        key=key,
        ledger="dense",
        t=t,
        evidence_id=_evidence_id(key),
        artifact_ref=f"kestrel/spec/{ref}.md",
        text=text,
        supersedes=None if supersedes is None else _evidence_id(supersedes),
    )


_BOOKING = (
    "## 1. Reservations\n"
    "\n"
    "A member reserves one specific vehicle for a fixed period before driving it. The reservation "
    "is made in the Kestrel app and states its start time and its end time.\n"
    "\n"
    "Rules\n"
    "1. A reservation may be made at most 14 days before its start time.\n"
    "2. A reservation must last at least 30 minutes.\n"
    "3. A reservation must not last longer than 72 hours.\n"
    "4. A member may hold at most two reservations that have not yet started.\n"
    "\n"
    "Example\n"
    "On 1 June a member may reserve a vehicle for a period that starts on 15 June at the latest. "
    "A reservation from 09:00 to 09:20 on the same day is too short and is not accepted by the "
    "app. A member who already holds two future reservations cannot make a third until one of "
    "them has started.\n"
)
_HOLD = (
    "## 2. Reservation no-show\n"
    "\n"
    "The reserved vehicle is kept for the member from the start of the reservation.\n"
    "\n"
    "Rules\n"
    "1. If the member has not unlocked the vehicle within 15 minutes after the reservation start, "
    "the reservation expires.\n"
    "2. An expired reservation releases the vehicle, which may then be reserved by any other "
    "member.\n"
    "\n"
    "Example\n"
    "A reservation starts at 18:00 and the vehicle is still locked at 18:15. The reservation "
    "expires at 18:15 and the vehicle is shown as free to the other members. A member who "
    "unlocks the vehicle at 18:14 keeps the reservation.\n"
)
_PROLONG = (
    "## 3. Prolonging a reservation\n"
    "\n"
    "Trips sometimes take longer than planned. A member who needs the vehicle longer may add "
    "time to a reservation that has already started. Time is added from the trip screen of the "
    "app.\n"
    "\n"
    "Rules\n"
    "1. Time may be added in steps of 30 minutes.\n"
    "2. Time may be added only if no other reservation of the same vehicle begins within the "
    "added period.\n"
    "3. Added time runs from the current end of the reservation.\n"
    "\n"
    "Example\n"
    "A reservation ends at 12:00 and the member adds one step at 11:40. The reservation now ends "
    "at 12:30, because the step is counted from 12:00 and not from 11:40. A second step added at "
    "12:10 moves the end to 13:00.\n"
)
_UNLOCK = (
    "## 4. Unlocking the vehicle\n"
    "\n"
    "The member unlocks the reserved vehicle by sending an unlock command from the app. Each "
    "command sent is one unlock attempt, which either opens the vehicle or fails.\n"
    "\n"
    "Rules\n"
    "1. At most five unlock attempts may be made for one reservation.\n"
    "2. After the fifth failed attempt the app must not send another unlock command for that "
    "reservation, and the member is directed to the support line.\n"
    "\n"
    "Example\n"
    "A member whose first four attempts fail may try a fifth time. If the fifth attempt also "
    "fails, the app shows the support number in place of the unlock button. A member who opens "
    "the vehicle at the second attempt has used two of the five attempts.\n"
)
_UNLOCK_WAIT_T1 = (
    "## 5. Wait between unlock attempts\n"
    "\n"
    "The lock module of a vehicle needs a moment to reset after a command it could not carry "
    "out. Sending commands too quickly makes a later attempt fail as well.\n"
    "\n"
    "Rules\n"
    "1. After an unlock attempt fails, the app must wait exactly 10 seconds before it sends the "
    "next unlock command.\n"
    "2. The wait must be the same for every attempt, whatever the attempt number.\n"
    "\n"
    "Example\n"
    "An attempt fails at 08:00:00. The next attempt may be sent at 08:00:10 at the earliest, and "
    "the one after it no sooner than 10 seconds after that attempt has failed.\n"
)
_UNLOCK_TIMEOUT = (
    "## 6. Unlock timeout\n"
    "\n"
    "A vehicle in a poorly covered car park may never answer a command.\n"
    "\n"
    "Rules\n"
    "1. An unlock command that the vehicle has not confirmed within 20 seconds must be treated "
    "as timed out.\n"
    "2. A timed-out unlock command counts as one failed unlock attempt.\n"
    "\n"
    "Example\n"
    "A command is sent at 08:10:00 and no confirmation has arrived by 08:10:20. It is recorded "
    "as a failed attempt at 08:10:20, and the member may send the next command after the usual "
    "wait.\n"
)
_LATE_T1 = (
    "## 7. Late return\n"
    "\n"
    "A vehicle that comes back late delays the next member who reserved it.\n"
    "\n"
    "Rules\n"
    "1. A vehicle returned after the end of its reservation is charged a late-return fee.\n"
    "2. No fee is charged if the vehicle is returned within 10 minutes after the reservation "
    "end.\n"
    "3. Beyond those 10 minutes the fee is 0.50 EUR for every started minute.\n"
    "4. The late-return fee for one reservation must not exceed 60 EUR.\n"
    "\n"
    "Example\n"
    "A reservation ends at 17:00 and the vehicle is returned at 17:14. The member pays 2 EUR for "
    "the four minutes after 17:10. A vehicle returned at 19:30 after the same reservation costs "
    "60 EUR, not 70 EUR.\n"
)
_LATE_WAIVER = (
    "## 8. Late return after a vehicle fault\n"
    "\n"
    "Rules\n"
    "1. The late-return fee is not charged when the delay was caused by a fault of the vehicle.\n"
    "2. This applies only if the member reported the fault in the app before the reservation "
    "ended.\n"
    "\n"
    "Example\n"
    "A member reports a flat tyre at 16:30 and returns the vehicle at 18:00 after a reservation "
    "that ended at 17:00. No late-return fee is charged. Had the flat tyre been reported at "
    "17:20, the fee would have been charged.\n"
)
_CLEANING_T1 = (
    "## 9. Cleaning fee\n"
    "\n"
    "Rules\n"
    "1. A member who leaves rubbish or soiling in a vehicle is charged a cleaning fee of 30 EUR.\n"
    "2. The fee is charged only if the next member reports the state of the vehicle with a photo "
    "in the app within 15 minutes after unlocking it.\n"
    "\n"
    "Example\n"
    "A member finds food waste on the back seat, photographs it five minutes after unlocking and "
    "reports it. The previous member is charged the cleaning fee. A report sent 40 minutes after "
    "unlocking leads to no fee.\n"
)
_CREDIT_T1 = (
    "## 10. Vehicle not available\n"
    "\n"
    "A reserved vehicle can occasionally be missing from its zone or unable to start.\n"
    "\n"
    "Rules\n"
    "1. If the reserved vehicle is missing or cannot be driven at the start of the reservation, "
    "the member receives a service credit of 10 EUR.\n"
    "2. The service credit is added to the member's Kestrel wallet and is never paid out to a "
    "card.\n"
    "\n"
    "Example\n"
    "A member arrives at 09:00 and the reserved vehicle has a flat battery. The member's wallet "
    "is credited with 10 EUR.\n"
)
_CREDIT_CLAIM = (
    "## 11. Claiming the service credit\n"
    "\n"
    "Rules\n"
    "1. The service credit for an unavailable vehicle must be claimed in the app within 48 hours "
    "after the reservation start.\n"
    "2. A claim made later is refused.\n"
    "3. The claim must name the reservation and include a photo of the vehicle.\n"
    "\n"
    "Example\n"
    "A reservation started on Monday at 10:00. A claim on Wednesday at 09:00 is accepted, and a "
    "claim on Wednesday at 11:00 is refused.\n"
)
_BILLING = (
    "## 12. Billing run\n"
    "\n"
    "Rules\n"
    "1. Fees incurred by a member during a day are charged to the member's payment card in one "
    "billing run.\n"
    "2. The billing run takes place every night at 02:00.\n"
    "3. A charge that the card issuer declines is attempted again in the next night's billing "
    "run.\n"
    "\n"
    "Example\n"
    "A late-return fee incurred on Tuesday afternoon is charged at 02:00 on Wednesday. If that "
    "charge is declined, it is attempted again at 02:00 on Thursday. Two fees incurred on the "
    "same day appear as one charge on the member's card.\n"
)
_SUSPENSION = (
    "## 13. Account suspension\n"
    "\n"
    "A suspended member is told about the suspension by e-mail.\n"
    "\n"
    "Rules\n"
    "1. When a charge has been declined in three consecutive billing runs, the member's account "
    "must be suspended.\n"
    "2. The suspension is lifted automatically as soon as the outstanding amount has been paid.\n"
    "\n"
    "Example\n"
    "A charge is declined on Monday, Tuesday and Wednesday night. The account is suspended after "
    "the Wednesday run and usable again on the day the member pays.\n"
)
_TRIP_T1 = (
    "## 14. Trip records\n"
    "\n"
    "Trip records help Kestrel find vehicles and settle disputes about where a vehicle was "
    "left.\n"
    "\n"
    "Rules\n"
    "1. During a reservation the vehicle records its location once every minute as a trip "
    "record.\n"
    "2. Trip records must be kept for 90 days after the reservation ends.\n"
    "3. After 90 days a trip record must be deleted.\n"
    "\n"
    "Example\n"
    "The trip records of a reservation that ended on 1 March are deleted on 30 May.\n"
)
_MEMBERSHIP = (
    "## 15. Membership approval\n"
    "\n"
    "A person becomes a member only after Kestrel approves the membership application. "
    "Applications are submitted in the app together with a photo of the driving licence.\n"
    "\n"
    "Rules\n"
    "1. An application is approved only if the applicant is at least 21 years old and has held a "
    "full driving licence for at least two years.\n"
    "2. Kestrel must decide every application within two working days.\n"
    "\n"
    "Example\n"
    "An applicant aged 23 whose licence was issued 18 months ago is not approved. An applicant "
    "aged 25 who has held a licence for three years is approved within two working days of "
    "applying.\n"
)

_DENSE_T1: Final = (
    _dense("K-BOOKING-T1", 1, "01-reservations", _BOOKING),
    _dense("K-HOLD-T1", 1, "02-reservation-no-show", _HOLD),
    _dense("K-PROLONG-T1", 1, "03-prolonging-a-reservation", _PROLONG),
    _dense("K-UNLOCK-T1", 1, "04-unlocking", _UNLOCK),
    _dense("K-UNLOCK-WAIT-T1", 1, "05-wait-between-unlock-attempts", _UNLOCK_WAIT_T1),
    _dense("K-UNLOCK-TIMEOUT-T1", 1, "06-unlock-timeout", _UNLOCK_TIMEOUT),
    _dense("K-LATE-T1", 1, "07-late-return", _LATE_T1),
    _dense("K-LATE-WAIVER-T1", 1, "08-late-return-after-a-vehicle-fault", _LATE_WAIVER),
    _dense("K-CLEANING-T1", 1, "09-cleaning-fee", _CLEANING_T1),
    _dense("K-CREDIT-T1", 1, "10-vehicle-not-available", _CREDIT_T1),
    _dense("K-CREDIT-CLAIM-T1", 1, "11-claiming-the-service-credit", _CREDIT_CLAIM),
    _dense("K-BILLING-T1", 1, "12-billing-run", _BILLING),
    _dense("K-SUSPENSION-T1", 1, "13-account-suspension", _SUSPENSION),
    _dense("K-TRIP-T1", 1, "14-trip-records", _TRIP_T1),
    _dense("K-MEMBERSHIP-T1", 1, "15-membership-approval", _MEMBERSHIP),
)

_CLEANING_T2 = _CLEANING_T1.replace("cleaning fee of 30 EUR", "cleaning fee of 40 EUR")
_LATE_T2 = (
    "## 7. Late return\n"
    "\n"
    "A vehicle that comes back late delays the next member who reserved it.\n"
    "\n"
    "Rules\n"
    "1. A vehicle returned after the end of its reservation is charged a late-return fee.\n"
    "2. The fee is a flat 25 EUR for any delay, however short.\n"
    "3. The late-return fee for one reservation must not exceed 60 EUR.\n"
    "\n"
    "Example\n"
    "A reservation ends at 17:00 and the vehicle is returned at 17:03. The member pays 25 EUR.\n"
)
_CREDIT_T2 = (
    "## 10. Vehicle not available\n"
    "\n"
    "A reserved vehicle can occasionally be missing from its zone or unable to start.\n"
    "\n"
    "Rules\n"
    "1. If the reserved vehicle is missing or cannot be driven at the start of the reservation, "
    "the member receives a service credit of 10 EUR when the reservation lasts up to four "
    "hours.\n"
    "2. The service credit is 20 EUR when the reservation lasts longer than four hours.\n"
    "3. The service credit is added to the member's Kestrel wallet and is never paid out to a "
    "card.\n"
    "\n"
    "Example\n"
    "A member arrives at 09:00 for a six-hour reservation and the reserved vehicle has a flat "
    "battery. The member's wallet is credited with 20 EUR.\n"
)
_UNLOCK_WAIT_T2 = (
    "## 5. Wait between unlock attempts\n"
    "\n"
    "The lock module of a vehicle needs a moment to reset after a command it could not carry "
    "out. Sending commands too quickly makes a later attempt fail as well.\n"
    "\n"
    "Rules\n"
    "1. After the first failed unlock attempt, the app must wait 5 seconds before it sends the "
    "next unlock command.\n"
    "2. After every further failed attempt the wait is twice as long as the previous wait.\n"
    "3. No wait may be longer than 40 seconds.\n"
    "\n"
    "Example\n"
    "An attempt fails at 08:00:00. The following waits are 5, 10, 20 and then 40 seconds.\n"
)
_TRIP_T2 = _TRIP_T1.replace(
    "3. After 90 days a trip record must be deleted.\n",
    "3. After 90 days a trip record must be deleted.\n"
    "4. A member may download the trip records of their own reservations from the app.\n",
)

_DENSE_T2: Final = (
    _dense("K-CLEANING-T2", 2, "09-cleaning-fee", _CLEANING_T2, supersedes="K-CLEANING-T1"),
    _dense("K-LATE-T2", 2, "07-late-return", _LATE_T2, supersedes="K-LATE-T1"),
    _dense("K-CREDIT-T2", 2, "10-vehicle-not-available", _CREDIT_T2, supersedes="K-CREDIT-T1"),
    _dense(
        "K-UNLOCK-WAIT-T2",
        2,
        "05-wait-between-unlock-attempts",
        _UNLOCK_WAIT_T2,
        supersedes="K-UNLOCK-WAIT-T1",
    ),
    _dense("K-TRIP-T2", 2, "14-trip-records", _TRIP_T2, supersedes="K-TRIP-T1"),
)

T3_DOCUMENTS: Final[tuple[Document, ...]] = (
    _dense(
        "K-UNLOCK-WAIT-T3",
        3,
        "05-wait-between-unlock-attempts",
        _UNLOCK_WAIT_T2,
        supersedes="K-UNLOCK-WAIT-T2",
    ),
    _dense(
        "K-CLEANING-T3",
        3,
        "09-cleaning-fee",
        _CLEANING_T1.replace("cleaning fee of 30 EUR", "cleaning fee of 35 EUR"),
        supersedes="K-CLEANING-T2",
    ),
)
"""The dense T3 delta, assimilated once in each branch: the N:M unlock-wait text redelivered
byte for byte, and the cleaning-fee text with a changed amount."""


# --------------------------------------------------------------------------- index


SEED_DOCUMENTS: Final[dict[LedgerId, tuple[Document, ...]]] = {**_V5_T1, "dense": _DENSE_T1}
"""T1 documents: a model delta for ``MODEL_SEEDED`` ledgers, ingested by the seed author for
``conflict``."""

SEED_WORLDS: Final[dict[LedgerId, tuple[SeedAddress, ...]]] = {"conflict": _CONFLICT_WORLD}

REVISION: Final[dict[LedgerId, tuple[Document, ...]]] = {**_V5_T2, "dense": _DENSE_T2}
"""The T2 delta of every ledger: always two model calls."""

DOCUMENTS: Final[dict[str, Document]] = {
    d.key: d
    for group in (*SEED_DOCUMENTS.values(), *REVISION.values(), T3_DOCUMENTS)
    for d in group
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


def t3_delta() -> tuple[EvidenceItem, ...]:
    return tuple(evidence(d) for d in T3_DOCUMENTS)


def corpus_record() -> dict[str, object]:
    """Everything model-visible, canonically: documents and the seed world."""
    return {
        "documents": {key: d.model_dump(mode="json") for key, d in DOCUMENTS.items()},
        "seed_worlds": {
            ledger: [a.model_dump(mode="json") for a in world]
            for ledger, world in SEED_WORLDS.items()
        },
    }


def corpus_sha256() -> str:
    return canonical_sha256(corpus_record())
