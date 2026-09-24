"""Shared builders for the IE2.1 graph-semantics tests.

Deliberately thin. The point of these tests is the *rules*, so the fixtures stay close to
the real shapes rather than wrapping them in a DSL that could hide a mismatch with
repository reality.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from foundry.domain.common import (
    Authority,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    SourceKind,
)
from foundry.domain.semantic import (
    AuthorityRecord,
    Constraint,
    Goal,
    Intent,
    NonGoal,
    Outcome,
    Preference,
    ProjectDecision,
    Requirement,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint

AT = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
PROJECT = "PROJ-IE21"
SCOPE = "payments"
ALICE = "human://alice"

HUMAN = ReasonerFingerprint(provider="human", model=ALICE, policy_version="p1")
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.7", policy_version="p1")

HUMAN_PROV = Provenance(source_kind=SourceKind.HUMAN, source_ref=ALICE)
SYSTEM_PROV = Provenance(source_kind=SourceKind.SYSTEM, source_ref="system://synthesis")


def _base(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": PROJECT,
        "authority": Authority.PROPOSED,
        "confidence": 1.0,
        "provenance": HUMAN_PROV,
        "created_at": AT,
        "scope": (SCOPE,),
    }
    payload.update(overrides)
    return payload


def intent(object_id: str = "INTENT-payments", **overrides: Any) -> Intent:
    payload = _base(**overrides)
    payload.setdefault("mission", "Refunds are predictable.")
    return Intent(id=object_id, **payload)


def goal(object_id: str = "GOAL-1", **overrides: Any) -> Goal:
    payload = _base(**overrides)
    payload.setdefault("statement", "Refunds settle quickly.")
    return Goal(id=object_id, **payload)


def outcome(object_id: str = "OUT-1", **overrides: Any) -> Outcome:
    payload = _base(**overrides)
    payload.setdefault("statement", "Refunds settle in a month.")
    return Outcome(id=object_id, **payload)


def requirement(object_id: str = "REQ-1", **overrides: Any) -> Requirement:
    payload = _base(**overrides)
    payload.setdefault("materiality", Materiality.LOW)
    payload.setdefault("requires_metric", False)
    payload.setdefault("requires_verification", False)
    payload.setdefault("statement", "Refunds must complete within thirty calendar days.")
    return Requirement(id=object_id, **payload)


def constraint(object_id: str = "CON-1", **overrides: Any) -> Constraint:
    payload = _base(**overrides)
    payload.setdefault("statement", "Data stays in the EU.")
    return Constraint(id=object_id, **payload)


def non_goal(object_id: str = "NG-1", **overrides: Any) -> NonGoal:
    payload = _base(**overrides)
    payload.setdefault("statement", "We will not build billing.")
    return NonGoal(id=object_id, **payload)


def preference(object_id: str = "PREF-1", **overrides: Any) -> Preference:
    payload = _base(**overrides)
    payload.setdefault("statement", "Prefer boring technology.")
    return Preference(id=object_id, **payload)


def project_decision(object_id: str = "DEC-1", **overrides: Any) -> ProjectDecision:
    payload = _base(**overrides)
    payload.setdefault("statement", "We chose PostgreSQL.")
    payload.setdefault("rationale", "Operational familiarity.")
    return ProjectDecision(id=object_id, **payload)


def authority_record(object_id: str = "AUTH-1", **overrides: Any) -> AuthorityRecord:
    payload = _base(**overrides)
    payload["authority"] = payload.get("authority", Authority.CANONICAL)
    return AuthorityRecord(
        id=object_id,
        subject_id=payload.pop("subject_id", "REQ-1"),
        authorized_by=payload.pop("authorized_by", ALICE),
        rationale="Alice owns payments intent.",
        **payload,
    )


def rel(relation_type: RelationType, target_id: str) -> Relation:
    return Relation(relation_type=relation_type, target_id=target_id)
