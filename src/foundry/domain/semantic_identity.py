"""Durable semantic identity contracts (Intent Intelligence v2, spec §4.5, §7, §8).

Identity law
------------
``address_id`` is the identity of a ``SemanticAddress``. ``subject``, ``facet`` and
``scope`` are human-readable, versioned DESCRIPTORS (``descriptor_version``) and are
never equality keys. Two addresses, or two candidates, whose descriptors are
byte-identical are NOT the same thing until a semantic reasoner says so and Foundry
admits that judgment.

Referential identity (``ADDR-x == ADDR-x``) exists only after an admitted binding
judgment and only under the current admitted interpretation. It is a referential fact,
not a semantic inference, and it ends the moment the admitting judgment is superseded
(spec §4.5, §7.2.1). Addresses are immutable and are never destructively merged;
equivalence is recorded as an admitted judgment and surfaced on
``SemanticIssueVersion.equivalent_address_ids`` under the interpretation current at
minting.

Consequently this module deliberately exposes NO function that compares two addresses
or two candidates for semantic sameness. Deterministic code cannot originate meaning;
it only applies admitted judgments.

Every model here is immutable and append-only once recorded (plan §0.3). Confidence is
absent by design: it is judgment metadata, never claim authority (spec §8, Law 7).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from foundry.domain.common import Authority, FrozenModel, Provenance


class SemanticAddress(FrozenModel):
    """A durable semantic identity. Only ``address_id`` identifies it."""

    address_id: str
    project_id: str
    subject: str
    facet: str
    scope: tuple[str, ...] = ()
    descriptor_version: int = Field(default=1, ge=1)
    created_by_judgment_id: str


class ClaimValueKind(StrEnum):
    QUANTITY = "QUANTITY"
    TEXT = "TEXT"
    ENUMERATION = "ENUMERATION"
    UNDECIDED = "UNDECIDED"


class ClaimValue(FrozenModel):
    """A structured, AI-normalised claim value; shape is fixed by ``kind``."""

    kind: ClaimValueKind
    text: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def validate_shape_for_kind(self) -> ClaimValue:
        if self.unit is not None and self.kind is not ClaimValueKind.QUANTITY:
            raise ValueError(f"unit is only permitted for {ClaimValueKind.QUANTITY}")
        if self.kind is ClaimValueKind.QUANTITY:
            if self.quantity is None:
                raise ValueError(f"{self.kind} requires quantity")
            if self.text is not None:
                raise ValueError(f"{self.kind} must not carry text")
        elif self.kind in (ClaimValueKind.TEXT, ClaimValueKind.ENUMERATION):
            if self.text is None:
                raise ValueError(f"{self.kind} requires text")
            if self.quantity is not None:
                raise ValueError(f"{self.kind} must not carry quantity")
        else:
            if self.text is not None or self.quantity is not None:
                raise ValueError(f"{self.kind} must not carry text or quantity")
        return self


class SemanticClaim(FrozenModel):
    """An immutable assertion about one address. Never merged, rewritten or averaged."""

    claim_id: str
    project_id: str
    address_id: str
    predicate: str
    value: ClaimValue
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    authority: Authority
    provenance: Provenance
    created_by_judgment_id: str


class SemanticCandidate(FrozenModel):
    """An ephemeral discovery proposal. Lives only inside a judgment; has no identity."""

    candidate_id: str
    subject: str
    facet: str
    scope: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class IssueEpistemicState(StrEnum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class SemanticIssueVersion(FrozenModel):
    """An immutable snapshot of the consolidated issue at one address, minted by the reducer.

    ``created_by_judgment_id`` names the judgment whose ADMISSION minted this version
    (for a SUPERSEDE application, the SUPERSEDE judgment's own id). It is what lets the
    derivation primitive treat versions as blast-radius roots when that judgment is
    superseded (spec §19.1).
    """

    version_id: str
    project_id: str
    address_id: str
    claim_ids: tuple[str, ...]
    epistemic_state: IssueEpistemicState
    equivalent_address_ids: tuple[str, ...]
    supersedes_version_id: str | None
    created_by_event_id: str
    created_by_judgment_id: str = Field(min_length=1)
