from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.semantic import Claim, Requirement, SemanticKind, SemanticObject


def test_claim_keeps_authority_confidence_and_provenance_separate() -> None:
    provenance = Provenance(
        source_kind=SourceKind.CODE,
        source_ref="repo://envd/rpc.go#L10-L20",
        source_event_ids=("EVT-1",),
    )
    claim = Claim(
        id="CLAIM-1",
        project_id="PROJ-1",
        statement="Legacy dispatch uses three retries.",
        authority=Authority.INFERRED,
        confidence=0.98,
        provenance=provenance,
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )

    assert claim.kind is SemanticKind.CLAIM
    assert claim.authority is Authority.INFERRED
    assert claim.confidence == 0.98
    assert claim.provenance.source_ref.endswith("#L10-L20")


def test_confidence_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="CLAIM-2",
            project_id="PROJ-1",
            statement="Invalid confidence.",
            authority=Authority.INFERRED,
            confidence=1.01,
            provenance=Provenance(
                source_kind=SourceKind.HUMAN,
                source_ref="human://owner",
                source_event_ids=("EVT-2",),
            ),
            created_at=datetime(2026, 9, 9, tzinfo=UTC),
        )


def test_material_requirement_can_demand_measurement_and_verification() -> None:
    requirement = Requirement(
        id="REQ-1",
        project_id="PROJ-1",
        statement="Regional loss must not materially interrupt service.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref="human://owner",
            source_event_ids=("EVT-3",),
        ),
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
        requires_metric=True,
        requires_verification=True,
    )

    assert requirement.requires_metric is True
    assert requirement.requires_verification is True


def test_semantic_objects_are_immutable() -> None:
    claim = Claim(
        id="CLAIM-3",
        project_id="PROJ-1",
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=Provenance(
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/retry.py#L1-L5",
            source_event_ids=("EVT-4",),
        ),
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )

    with pytest.raises(ValidationError):
        claim.confidence = 0.5


def test_unknown_semantic_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim.model_validate(
            {
                "id": "CLAIM-4",
                "project_id": "PROJ-1",
                "statement": "Retries are three.",
                "authority": Authority.INFERRED,
                "confidence": 0.9,
                "provenance": {
                    "source_kind": SourceKind.CODE,
                    "source_ref": "repo://svc/retry.py#L1-L5",
                    "source_event_ids": ("EVT-5",),
                },
                "created_at": datetime(2026, 9, 9, tzinfo=UTC),
                "invented_field": "x",
            }
        )


def test_semantic_object_union_reconstructs_claim() -> None:
    claim = Claim(
        id="CLAIM-5",
        project_id="PROJ-1",
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=Provenance(
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/retry.py#L1-L5",
            source_event_ids=("EVT-6",),
        ),
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )

    restored = TypeAdapter(SemanticObject).validate_python(claim.model_dump(mode="json"))

    assert isinstance(restored, Claim)
    assert restored == claim
