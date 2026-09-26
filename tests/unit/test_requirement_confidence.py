"""D12 then Q1 — an intent object may honestly carry unknown confidence.

**D12** let a synthesized ``Requirement`` carry no confidence: T8 builds a concrete
``Requirement`` from a proposal that may supply none, and ``SemanticBase.confidence`` could
not move for one construction mismatch.

Inventing a number would be the wrong fix. ``0.0`` asserts no confidence, ``1.0``
asserts certainty, ``0.5`` asserts a coin flip — each fabricates an epistemic statement
the model never made, attributes it to the model, and makes it durable. ``None`` means
**no numeric confidence was supplied**, which is the truth.

**IE3 Q1** (``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md``) superseded
D12's "Requirement alone" deliberately, not silently: graph synthesis compiles all nine IE3
kinds, and runtime must never invent a number for a human's direct choice. The widening is
still exactly bounded, which is what this file now protects:

* the nine IE3 kinds — Intent, Goal, Outcome, Requirement, Constraint, NonGoal, Preference,
  ProjectDecision, Assumption — declare an optional confidence;
* ``SemanticBase`` and every other semantic kind still require one. Broadening the whole
  semantic domain would let every future object silently omit confidence without anyone
  deciding that.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain import semantic
from foundry.domain.common import Authority, Materiality, Provenance, SourceKind
from foundry.domain.semantic import Claim, Goal, Requirement, SemanticBase

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


# --- Q1: exactly the nine IE3 kinds, never the whole domain ---------------------------

IE3_KIND_NAMES = frozenset(
    {
        "Intent",
        "Goal",
        "Outcome",
        "Requirement",
        "Constraint",
        "NonGoal",
        "Preference",
        "ProjectDecision",
        "Assumption",
    }
)


def _semantic_classes() -> list[type[SemanticBase]]:
    """Every concrete semantic kind, discovered rather than listed, so a new kind is covered."""
    classes = {
        obj
        for obj in vars(semantic).values()
        if isinstance(obj, type) and issubclass(obj, SemanticBase) and obj is not SemanticBase
    }
    return sorted(classes, key=lambda c: c.__name__)


def test_goal_may_omit_confidence_under_q1() -> None:
    assert Goal(**_BASE, statement="s").confidence is None  # type: ignore[arg-type]
    assert Goal(**_BASE, statement="s", confidence=None).confidence is None  # type: ignore[arg-type]


def test_goal_none_is_not_zero() -> None:
    absent = Goal(**_BASE, statement="s")  # type: ignore[arg-type]
    zero = Goal(**_BASE, statement="s", confidence=0.0)  # type: ignore[arg-type]
    assert zero.confidence == 0.0
    assert absent != zero
    assert Goal.model_validate(absent.model_dump(mode="json")).confidence is None


def test_the_base_contract_is_unchanged() -> None:
    assert SemanticBase.model_fields["confidence"].is_required() is True


def test_claim_still_requires_confidence() -> None:
    """The epistemic kinds were never part of Q1."""
    with pytest.raises(ValidationError):
        Claim(**_BASE, statement="s")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Claim(**_BASE, statement="s", confidence=None)  # type: ignore[arg-type]


def test_exactly_the_nine_ie3_kinds_declare_an_optional_confidence() -> None:
    classes = _semantic_classes()
    assert {c.__name__ for c in classes} >= IE3_KIND_NAMES
    optional = {c.__name__ for c in classes if not c.model_fields["confidence"].is_required()}
    assert optional == IE3_KIND_NAMES


@pytest.mark.parametrize(
    "cls",
    [c for c in _semantic_classes() if c.__name__ not in IE3_KIND_NAMES],
    ids=lambda c: c.__name__,
)
def test_every_non_ie3_kind_still_requires_confidence(cls: type[SemanticBase]) -> None:
    assert cls.model_fields["confidence"].is_required() is True


# --- serialization -------------------------------------------------------------------


def test_an_unknown_confidence_serializes_as_null_not_a_sentinel() -> None:
    dumped = _requirement().model_dump(mode="json")
    assert dumped["confidence"] is None
    assert Requirement.model_validate(dumped) == _requirement()
