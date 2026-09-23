"""D12 — a synthesized Requirement may honestly carry unknown confidence.

``RequirementSynthesisProposal.confidence`` is optional; ``SemanticBase.confidence`` is
not. T8 must construct a concrete ``Requirement`` from a proposal that may carry none,
so one of the two has to move.

Inventing a number would be the wrong fix. ``0.0`` asserts no confidence, ``1.0``
asserts certainty, ``0.5`` asserts a coin flip — each fabricates an epistemic statement
the model never made, attributes it to the model, and makes it durable. ``None`` means
**no numeric confidence was supplied**, which is the truth.

The widening is deliberately narrow: ``Requirement`` alone, not ``SemanticBase``.
Broadening the whole semantic domain to solve one Slice-1 construction mismatch would
let every future object silently omit confidence without anyone deciding that.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, Materiality, Provenance, SourceKind
from foundry.domain.semantic import Claim, Goal, Requirement

AT = datetime(2026, 9, 23, tzinfo=UTC)
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref="human://alice")
_BASE = {
    "id": "REQ-1",
    "project_id": "PROJ-A",
    "authority": Authority.CANONICAL,
    "provenance": PROVENANCE,
    "created_at": AT,
}


def _requirement(**overrides: object) -> Requirement:
    return Requirement(
        **{**_BASE, **overrides},  # type: ignore[arg-type]
        statement="Revocation is immediate.",
        materiality=Materiality.LOW,
        requires_metric=False,
        requires_verification=False,
    )


# --- the Requirement contract -------------------------------------------------------


def test_an_omitted_confidence_is_none() -> None:
    assert _requirement().confidence is None


def test_an_explicit_none_confidence_is_preserved() -> None:
    assert _requirement(confidence=None).confidence is None


@pytest.mark.parametrize("value", [0.0, 0.72, 1.0])
def test_a_supplied_confidence_is_preserved_exactly(value: float) -> None:
    """No normalization, no rounding, no substitution."""
    assert _requirement(confidence=value).confidence == value


def test_none_is_not_zero() -> None:
    """The distinction D12 exists to protect: absent metadata is not low confidence."""
    assert _requirement(confidence=None).confidence is not 0.0  # noqa: F632
    assert _requirement(confidence=0.0).confidence == 0.0
    assert _requirement(confidence=None) != _requirement(confidence=0.0)


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_a_confidence_outside_the_unit_interval_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        _requirement(confidence=value)


# --- narrowness: the global contract is unchanged ------------------------------------


def test_another_semantic_object_still_requires_confidence() -> None:
    """D12 widened Requirement ALONE; every other kind keeps today's contract."""
    with pytest.raises(ValidationError):
        Claim(**_BASE, statement="s")  # type: ignore[arg-type]


def test_a_second_object_kind_also_still_requires_confidence() -> None:
    with pytest.raises(ValidationError):
        Goal(**_BASE, statement="s")  # type: ignore[arg-type]


def test_only_requirement_declares_an_optional_confidence() -> None:
    from foundry.domain.semantic import SemanticBase

    assert Requirement.model_fields["confidence"].is_required() is False
    assert SemanticBase.model_fields["confidence"].is_required() is True
    assert Claim.model_fields["confidence"].is_required() is True
    assert Goal.model_fields["confidence"].is_required() is True


# --- serialization -------------------------------------------------------------------


def test_an_unknown_confidence_serializes_as_null_not_a_sentinel() -> None:
    dumped = _requirement().model_dump(mode="json")
    assert dumped["confidence"] is None
    assert Requirement.model_validate(dumped) == _requirement()
