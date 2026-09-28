"""Governed-concern grain: adversarial fixtures and a deterministic grouping grader.

The IE2 address grain is one governed concern (IE2 v2 design §7.1.1); its dimensions are
claims. Whether a model groups propositions at that grain is a live question and belongs to
a sealed validation. What is decidable offline, and fixed here:

* **the fixtures**: groups of propositions with the concern each belongs to, covering both
  failure directions (a concern split by dimension; independent concerns merged by topic);
* **the grader**: given where propositions were placed (proposition -> address), it reports
  ``OVER_SPLIT`` (one concern across several addresses), ``UNDER_SPLIT`` (several concerns at
  one address) and ``UNPLACED``. It reads no wording;
* **the facet screen**: a deterministic check that flags facets shaped as a single
  dimension question (who / when / how long / whether / how ...). It is a screen for the
  commonest proposition-level shape, not a semantic judge: a dimension-named facet that is
  not phrased as a question passes it, and the grader, not the screen, decides grain.

It never calls a model and is never part of admission.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Final, Literal

from foundry.domain.common import FrozenModel

__all__ = [
    "FIXTURES",
    "GrainFixture",
    "GrainProposition",
    "dimension_shaped",
    "grade_grouping",
]


class GrainProposition(FrozenModel):
    id: str
    text: str
    concern: str
    """The governed concern the proposition belongs to (the expected grouping key)."""


class GrainFixture(FrozenModel):
    id: str
    title: str
    kind: Literal["ONE_CONCERN", "SEPARATE_CONCERNS"]
    propositions: tuple[GrainProposition, ...]
    rule: str
    """The contract rule the fixture exercises, quoted from the model-facing prompt."""


def _p(pid: str, concern: str, text: str) -> GrainProposition:
    return GrainProposition(id=pid, concern=concern, text=text)


_DIMENSIONS_ARE_CLAIMS: Final = "The dimensions of a concern are claims at its one address"
_SEPARATE: Final = "independently governed act, entity or record, entitlement, decision"
_TOPIC: Final = "Sharing a topic word, a document or a subject area with a known address"
_STAGES: Final = "A deadline for doing something"

FIXTURES: Final[tuple[GrainFixture, ...]] = (
    GrainFixture(
        id="G1-JOB-CANCELLATION",
        title="9P3 C09: who may cancel, future attempts, running attempt, repeat",
        kind="ONE_CONCERN",
        rule=_DIMENSIONS_ARE_CLAIMS,
        propositions=(
            _p("H-1", "job cancellation", "a producer or operator may cancel a job"),
            _p("H-2", "job cancellation", "after cancellation no future attempt may start"),
            _p("H-3", "job cancellation", "a running attempt is not interrupted"),
            _p(
                "H-4",
                "job cancellation",
                "cancelling an already-cancelled job leaves it cancelled and changes nothing else",
            ),
        ),
    ),
    GrainFixture(
        id="G2-LATE-DELIVERY-COMPENSATION",
        title="locus v2 C6: refund, destination and 14-day request deadline",
        kind="ONE_CONCERN",
        rule=_STAGES,
        propositions=(
            _p("LATE-1", "late-delivery compensation", "a late delivery refunds the shipping fee"),
            _p(
                "LATE-2", "late-delivery compensation", "it is paid to the booking's payment method"
            ),
            _p(
                "LATE-3",
                "late-delivery compensation",
                "it must be requested within 14 days of the promised delivery date",
            ),
        ),
    ),
    GrainFixture(
        id="G3-CREDENTIAL-REVOCATION",
        title="who may revoke, immediate effect, irreversibility, repeated revocation",
        kind="ONE_CONCERN",
        rule=_DIMENSIONS_ARE_CLAIMS,
        propositions=(
            _p(
                "REV-1",
                "credential revocation",
                "a credential may be revoked by its owner or an operator",
            ),
            _p("REV-2", "credential revocation", "revocation takes effect immediately"),
            _p("REV-3", "credential revocation", "the client cannot undo a revocation"),
            _p(
                "REV-4",
                "credential revocation",
                "revoking an already-revoked credential leaves it revoked and changes nothing else",
            ),
        ),
    ),
    GrainFixture(
        id="G4-CANCELLATION-VS-AUDIT-DELETION",
        title="cancelling a job is not deleting its audit record",
        kind="SEPARATE_CONCERNS",
        rule=_SEPARATE,
        propositions=(
            _p("CX-1", "job cancellation", "an operator may cancel a job"),
            _p("CX-2", "job cancellation", "a cancelled job starts no further attempt"),
            _p(
                "AUD-1",
                "audit record deletion",
                "a job's audit record is deleted 30 days after the job ends",
            ),
            _p(
                "AUD-2",
                "audit record deletion",
                "only a compliance officer may delete an audit record early",
            ),
        ),
    ),
    GrainFixture(
        id="G5-LATE-VS-DAMAGE-COMPENSATION",
        title="two entitlements with independent triggers and rules",
        kind="SEPARATE_CONCERNS",
        rule=_SEPARATE,
        propositions=(
            _p("LT-1", "late-delivery compensation", "a late delivery refunds the shipping fee"),
            _p("LT-2", "late-delivery compensation", "it must be requested within 14 days"),
            _p(
                "DM-1",
                "damage compensation",
                "a damaged parcel is reimbursed up to its declared value",
            ),
            _p(
                "DM-2",
                "damage compensation",
                "damage must be reported with photographs within 48 hours",
            ),
        ),
    ),
    GrainFixture(
        id="G6-COMPENSATION-VS-SETTLEMENT",
        title="requesting compensation is not the independently governed bank settlement run",
        kind="SEPARATE_CONCERNS",
        rule=_SEPARATE,
        propositions=(
            _p(
                "CMP-1",
                "late-delivery compensation",
                "a sender may request compensation for a late delivery",
            ),
            _p("CMP-2", "late-delivery compensation", "compensation is the shipping fee"),
            _p(
                "SET-1",
                "bank settlement run",
                "approved payouts are settled with the partner bank every Monday",
            ),
            _p(
                "SET-2",
                "bank settlement run",
                "a settlement batch that the bank rejects is retried the next working day",
            ),
        ),
    ),
    GrainFixture(
        id="G7-TWO-REFUND-CONCERNS",
        title="shared vocabulary, independently governed: customer vs supplier overpayment refunds",
        kind="SEPARATE_CONCERNS",
        rule=_TOPIC,
        propositions=(
            _p(
                "CR-1",
                "customer order refunds",
                "a customer may request a refund up to 30 days after purchase",
            ),
            _p(
                "CR-2",
                "customer order refunds",
                "a customer refund is paid to the original payment method",
            ),
            _p(
                "SR-1",
                "supplier overpayment refunds",
                "a supplier must refund an overpaid invoice within 10 days",
            ),
            _p(
                "SR-2",
                "supplier overpayment refunds",
                "a supplier refund is offset against the next invoice",
            ),
        ),
    ),
)


def grade_grouping(fixture: GrainFixture, placement: Mapping[str, str]) -> tuple[str, ...]:
    """Where each proposition was placed (proposition id -> address) against the fixture.

    ``OVER_SPLIT``: one concern's propositions sit at more than one address.
    ``UNDER_SPLIT``: propositions of different concerns share an address.
    ``UNPLACED``: a proposition was placed nowhere. No wording is read."""
    findings: list[str] = []
    by_concern: dict[str, set[str]] = defaultdict(set)
    by_address: dict[str, set[str]] = defaultdict(set)
    for proposition in fixture.propositions:
        address = placement.get(proposition.id)
        if address is None:
            findings.append(f"UNPLACED: {proposition.id}")
            continue
        by_concern[proposition.concern].add(address)
        by_address[address].add(proposition.concern)
    for concern, addresses in sorted(by_concern.items()):
        if len(addresses) > 1:
            findings.append(f"OVER_SPLIT: {concern!r} spread over {len(addresses)} addresses")
    for address, concerns in sorted(by_address.items()):
        if len(concerns) > 1:
            findings.append(f"UNDER_SPLIT: {address} holds {sorted(concerns)}")
    return tuple(findings)


_DIMENSION_QUESTION: Final = re.compile(
    r"^\s*(who|whom|whose|when|where|whether|which|how(\s+(long|many|much|often|soon|quickly))?"
    r"|what\s+happens|is|are|can|may|must|does|do)\b",
    re.IGNORECASE,
)


def dimension_shaped(facet: str) -> bool:
    """True when a facet is phrased as a single-dimension question (who/when/how/whether...).

    A screen, not a judge: it catches the commonest proposition-level facet shape; a
    concern-level question ("What governs ...?", "What are the rules ...?") opens with a
    bare "what" and is never matched."""
    return bool(_DIMENSION_QUESTION.match(facet))
