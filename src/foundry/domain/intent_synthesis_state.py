"""Governed Intent Synthesis state (Slice-1 task T2).

Design spec: ``docs/superpowers/specs/2026-09-22-intent-synthesis-bridge-design.md``
(§10.5, §10.6, §10.8, §15.6, I24, I24a).

``IntentSynthesisState`` is the replayable, append-only projection of the synthesis
lifecycle, in the same shape ``SemanticState`` already establishes: frozen mappings
through ``MappingProxyType``, ordered tuples, deterministic serialization, no I/O.

Four planes and no more
-----------------------
* ``decisions`` — every durable ``INTENT_SYNTHESIS_DECIDED``, keyed by the runtime-owned
  ``proposal_instance_id``. **There is no ``admissions`` field** (C15): proposal and
  admission were collapsed into one decision event by C12, and the older formulation
  over ``admissions`` — which also omitted invalidation — is gone.
* ``applied_proposal_ids`` / ``invalidated_proposal_ids`` — the two TERMINAL outcomes.
* ``retirements`` — the durable evidence that a stale object was validly replaced,
  which §15.6 reads to decide whether historical staleness still blocks delivery.

The lifecycle partition (I24)
-----------------------------
At ANY snapshot, every durable ``DECIDED(APPLY)`` is in exactly one of **applied**,
**invalidated** or **incomplete** (neither marker). The three are mutually exclusive
and jointly cover every ``APPLY``; non-``APPLY`` routes are terminal at the decision and
belong to none of them.

``incomplete`` is a LEGAL non-terminal state — delivery-blocking, detectable and
retriable — not a defect and not an error. This module therefore represents it happily
and refuses only *impossible* bookkeeping. Nothing here asserts that progress has
happened, and nothing here forecloses either terminal outcome (I24a, T2 half). The
executable legal exit is ``resume_incomplete_synthesis``, which belongs to T9 and is
deliberately absent from this module.

Pure domain: no I/O, no event store, no reducer, no orchestration, no provider import,
no clock, no randomness, and no T3 event vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import Field, field_serializer, field_validator, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.intent_synthesis import IntentSynthesisDecision, IntentSynthesisRoute

__all__ = [
    "IntentSynthesisState",
    "RetirementRecord",
    "incomplete_proposal_ids",
]


def _freeze_mapping[T](value: Mapping[str, T]) -> Mapping[str, T]:
    return MappingProxyType(dict(value))


class RetirementRecord(FrozenModel):
    """Durable evidence that one intent object was retired by a valid replacement.

    Written ONLY by the reducer, inside the single ``INTENT_OBJECT_SYNTHESIZED`` event
    that mints the replacement (spec §10.5, C7) — so it can never exist without the
    replacement it names, nor the replacement without it. That indivisibility is what
    makes §15.6's reconciliation check sound rather than merely plausible.

    T2 owns the immutable representation; the reducer transition that appends these is
    T4.
    """

    retired_object_id: str = Field(min_length=1)
    replaced_by_object_id: str = Field(min_length=1)
    proposal_instance_id: str = Field(min_length=1)
    recorded_by_event_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_not_self_replacing(self) -> RetirementRecord:
        """An object never replaces itself; reconciliation always mints a new id."""
        if self.retired_object_id == self.replaced_by_object_id:
            raise ValueError("retired_object_id and replaced_by_object_id must differ")
        return self


class IntentSynthesisState(FrozenModel):
    decisions: Mapping[str, IntentSynthesisDecision] = Field(
        default_factory=dict, validate_default=True
    )
    applied_proposal_ids: tuple[str, ...] = ()
    invalidated_proposal_ids: tuple[str, ...] = ()
    retirements: tuple[RetirementRecord, ...] = ()

    @field_validator("decisions", mode="after")
    @classmethod
    def freeze_decisions(
        cls, value: Mapping[str, IntentSynthesisDecision]
    ) -> Mapping[str, IntentSynthesisDecision]:
        return _freeze_mapping(value)

    @field_serializer("decisions")
    def serialize_decisions(
        self, value: Mapping[str, IntentSynthesisDecision]
    ) -> dict[str, object]:
        return dict(value)

    @model_validator(mode="after")
    def validate_terminal_bookkeeping(self) -> IntentSynthesisState:
        """Fail closed on bookkeeping the lifecycle cannot produce (I24).

        Rejecting these is not the same as rejecting ``incomplete``: an unmarked
        ``APPLY`` is legal and expected. What cannot exist is a proposal that is both
        terminal outcomes at once, a terminal marker with no decision behind it, a
        terminal marker on a route that was already terminal at the decision, or the
        same terminal outcome recorded twice.
        """
        for key, decision in self.decisions.items():
            if key != decision.proposal_instance_id:
                raise ValueError(
                    f"decision keyed {key!r} carries proposal_instance_id "
                    f"{decision.proposal_instance_id!r}"
                )

        applied = self.applied_proposal_ids
        invalidated = self.invalidated_proposal_ids

        for name, markers in (
            ("applied_proposal_ids", applied),
            ("invalidated_proposal_ids", invalidated),
        ):
            if len(set(markers)) != len(markers):
                raise ValueError(f"{name} records the same proposal twice")
            for proposal_instance_id in markers:
                marked = self.decisions.get(proposal_instance_id)
                if marked is None:
                    raise ValueError(
                        f"{name} names {proposal_instance_id!r}, which has no durable decision"
                    )
                if marked.route is not IntentSynthesisRoute.APPLY:
                    raise ValueError(
                        f"{name} names {proposal_instance_id!r}, whose route is "
                        f"{marked.route.value}; only APPLY has a terminal outcome"
                    )

        both = frozenset(applied) & frozenset(invalidated)
        if both:
            raise ValueError(
                f"applied and invalidated overlap: {', '.join(sorted(both))}; "
                "the two terminal outcomes are mutually exclusive"
            )
        return self


def incomplete_proposal_ids(state: IntentSynthesisState) -> tuple[str, ...]:
    """The single definition of incomplete (spec §10.8, C15).

    ``DECIDED(APPLY)`` and neither applied nor invalidated. Reads ``decisions``; there
    is no ``admissions`` plane and no second formulation anywhere.

    Returns a TUPLE in durable projection order — the order decisions were recorded,
    which is event order under replay — rather than an unordered structure. The spec
    writes this with set notation for concision; the projection is ordered, and order
    is part of replay exactness (I7).
    """
    applied = frozenset(state.applied_proposal_ids)
    invalidated = frozenset(state.invalidated_proposal_ids)
    return tuple(
        proposal_instance_id
        for proposal_instance_id, decision in state.decisions.items()
        if decision.route is IntentSynthesisRoute.APPLY
        and proposal_instance_id not in applied
        and proposal_instance_id not in invalidated
    )
