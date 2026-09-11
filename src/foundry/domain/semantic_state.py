"""Governed semantic state (Intent Intelligence v2, plan §5.2; spec §18, §22).

``SemanticState`` is the replayable, append-only projection of every admitted
semantic transition. It records three planes and never rewrites any of them:

* evidence and judgments — what was seen and what was proposed (evidence plane);
* admissions — the deterministic decision taken for each judgment;
* addresses, claims, bindings, equivalences, conflicts, issue versions, derivations —
  the interpretation plane, mutated ONLY by an admission whose route is ``APPLY``.

Supersession is recorded as an append-only ``SupersessionRecord`` (target,
superseding judgment, recording event); the superseded judgment, and everything it
produced, remains readable. A judgment restored by superseding its superseder can be
superseded again — each supersession is a new record, never an overwrite.
The *current* interpretation is not stored here — it is derived by
``foundry.domain.semantic_view.derive_view`` from active judgments.

Mappings are frozen through ``MappingProxyType`` exactly as ``IntentState`` does.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import Field, field_serializer, field_validator

from foundry.domain.common import FrozenModel
from foundry.domain.derivation import DerivationEdge
from foundry.domain.events import SemanticAdmissionPayload
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_identity import SemanticAddress, SemanticClaim, SemanticIssueVersion
from foundry.domain.semantic_judgment import SemanticJudgment


def _freeze_mapping[T](value: Mapping[str, T]) -> Mapping[str, T]:
    return MappingProxyType(dict(value))


class EquivalenceRecord(FrozenModel):
    """An admitted EQUIVALENT judgment between two addresses. Never merges records."""

    judgment_id: str = Field(min_length=1)
    address_a: str = Field(min_length=1)
    address_b: str = Field(min_length=1)


class ConflictRecord(FrozenModel):
    """An admitted CONFLICTS_WITH judgment between two claims at one locus."""

    judgment_id: str = Field(min_length=1)
    claim_a: str = Field(min_length=1)
    claim_b: str = Field(min_length=1)


class SupersessionRecord(FrozenModel):
    """An admitted SUPERSEDE judgment. Ends the target's effect on the current view."""

    target_judgment_id: str = Field(min_length=1)
    superseding_judgment_id: str = Field(min_length=1)
    recorded_by_event_id: str = Field(min_length=1)


class SemanticState(FrozenModel):
    evidence: Mapping[str, EvidenceItem] = Field(default_factory=dict, validate_default=True)
    addresses: Mapping[str, SemanticAddress] = Field(default_factory=dict, validate_default=True)
    claims: Mapping[str, SemanticClaim] = Field(default_factory=dict, validate_default=True)
    judgments: Mapping[str, SemanticJudgment] = Field(default_factory=dict, validate_default=True)
    admissions: Mapping[str, SemanticAdmissionPayload] = Field(
        default_factory=dict, validate_default=True
    )
    applied_judgment_ids: tuple[str, ...] = ()
    supersessions: tuple[SupersessionRecord, ...] = ()
    bindings: Mapping[str, str] = Field(default_factory=dict, validate_default=True)
    equivalences: tuple[EquivalenceRecord, ...] = ()
    conflicts: tuple[ConflictRecord, ...] = ()
    issue_versions: Mapping[str, SemanticIssueVersion] = Field(
        default_factory=dict, validate_default=True
    )
    issue_heads: Mapping[str, str] = Field(default_factory=dict, validate_default=True)
    derivations: tuple[DerivationEdge, ...] = ()

    @field_validator("evidence", mode="after")
    @classmethod
    def freeze_evidence(cls, value: Mapping[str, EvidenceItem]) -> Mapping[str, EvidenceItem]:
        return _freeze_mapping(value)

    @field_validator("addresses", mode="after")
    @classmethod
    def freeze_addresses(
        cls, value: Mapping[str, SemanticAddress]
    ) -> Mapping[str, SemanticAddress]:
        return _freeze_mapping(value)

    @field_validator("claims", mode="after")
    @classmethod
    def freeze_claims(cls, value: Mapping[str, SemanticClaim]) -> Mapping[str, SemanticClaim]:
        return _freeze_mapping(value)

    @field_validator("judgments", mode="after")
    @classmethod
    def freeze_judgments(
        cls, value: Mapping[str, SemanticJudgment]
    ) -> Mapping[str, SemanticJudgment]:
        return _freeze_mapping(value)

    @field_validator("admissions", mode="after")
    @classmethod
    def freeze_admissions(
        cls, value: Mapping[str, SemanticAdmissionPayload]
    ) -> Mapping[str, SemanticAdmissionPayload]:
        return _freeze_mapping(value)

    @field_validator("bindings", "issue_heads", mode="after")
    @classmethod
    def freeze_id_mappings(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return _freeze_mapping(value)

    @field_validator("issue_versions", mode="after")
    @classmethod
    def freeze_issue_versions(
        cls, value: Mapping[str, SemanticIssueVersion]
    ) -> Mapping[str, SemanticIssueVersion]:
        return _freeze_mapping(value)

    @field_serializer(
        "evidence",
        "addresses",
        "claims",
        "judgments",
        "admissions",
        "bindings",
        "issue_versions",
        "issue_heads",
    )
    def serialize_mappings(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)
