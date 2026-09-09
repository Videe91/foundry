from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.semantic import Claim, Requirement, SemanticKind


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
