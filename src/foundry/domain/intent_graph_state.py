"""Durable Intent Graph decisions and their projection (IE3 Slice 2).

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§14-§17; R103,
R108).

**One event decides and applies (R103).** ``INTENT_GRAPH_SYNTHESIS_DECIDED`` carries the whole
graph result, the runtime's per-node assignments, the route and, iff the route is ``APPLY``, the
compiled graph. The reducer applies it as one state transition, so there is no incomplete state,
no applied marker and no invalidation event for a graph. Every durable decision is terminal at
its own event.

This module holds the durable shapes: the compiled graph the event carries, the decision and its
record, and the ``IntentGraphSynthesisState`` plane keyed by ``graph_instance_id``. The compiled
graph lives here rather than in the compiler so that ``events`` can carry it without importing
the compiler, which depends on IE2 laws that themselves import ``events``.

**R108 derivation convention.** ``CompiledIntentGraph.derivation_parents`` records, per object,
the sorted unique ids that object names through ``DERIVED_FROM``. That is the actual durable
target: a claim id, an existing object id or a resolved new object id, never translated to a
judgment id. R105-R107 make claim-id edges propagate supersession correctly.

Pure domain: no I/O, no clock, no randomness, no provider import.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Final, Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from foundry.domain.common import Authority, FrozenModel
from foundry.domain.intent_graph import (
    GRAPH_CONTRACT_VERSION,
    LOCAL_ID_PATTERN,
    IntentGraphGap,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_synthesis import IntentSynthesisRoute, SynthesisOrigin
from foundry.domain.semantic import SemanticObject
from foundry.domain.semantic_judgment import ReasonerFingerprint

__all__ = [
    "GRAPH_DECISION_STEP",
    "GRAPH_ROUTES",
    "CompiledIntentGraph",
    "GraphNodeAssignment",
    "IntentGraphDecision",
    "IntentGraphDecisionRecord",
    "IntentGraphSynthesisState",
    "NodeAssignment",
    "ObjectDerivationParents",
    "RetirementPlanEntry",
    "graph_decision_event_id",
    "validate_graph_decision_shape",
]

GRAPH_DECISION_STEP: Final = "DECIDED"
"""The one pinned durable step of a graph. Its event id is ``identity.event_id("DECIDED")``."""

GRAPH_ROUTES: Final[frozenset[IntentSynthesisRoute]] = frozenset(
    {
        IntentSynthesisRoute.APPLY,
        IntentSynthesisRoute.NO_CHANGE,
        IntentSynthesisRoute.REQUIRE_HUMAN,
        IntentSynthesisRoute.REJECT,
    }
)
"""The existing route vocabulary, minus ``REQUIRE_SECOND_LENS``: no graph corroboration exists."""


def graph_decision_event_id(identity: IntentGraphIdentity) -> str:
    return identity.event_id(GRAPH_DECISION_STEP)


# --------------------------------------------------------------------------- compiled graph


class NodeAssignment(FrozenModel):
    """Runtime's decision for one node: who it came from and what authority it gets."""

    origin: SynthesisOrigin
    authority: Authority


class RetirementPlanEntry(FrozenModel):
    """One planned retirement, recorded by the atomic graph event."""

    retired_object_id: str = Field(min_length=1)
    replaced_by_object_id: str = Field(min_length=1)
    node_instance_id: str = Field(min_length=1)


class ObjectDerivationParents(FrozenModel):
    """R108: the durable DERIVED_FROM targets of one object, canonically ordered."""

    object_id: str = Field(min_length=1)
    parent_ids: tuple[str, ...] = ()

    @field_validator("parent_ids", mode="after")
    @classmethod
    def canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("parent_ids must be sorted and unique")
        return value


class CompiledIntentGraph(FrozenModel):
    """Everything one graph durably means, canonically ordered."""

    identity: IntentGraphIdentity
    objects: tuple[SemanticObject, ...]
    local_to_object_id: tuple[tuple[str, str], ...]
    derivation_parents: tuple[ObjectDerivationParents, ...]
    retirements: tuple[RetirementPlanEntry, ...] = ()
    gaps: tuple[IntentGraphGap, ...] = ()

    @model_validator(mode="after")
    def parents_cover_every_object(self) -> CompiledIntentGraph:
        if [p.object_id for p in self.derivation_parents] != [o.id for o in self.objects]:
            raise ValueError(
                "derivation_parents must name every compiled object exactly once, in object order"
            )
        return self


# --------------------------------------------------------------------------- decision


class IntentGraphDecision(FrozenModel):
    """The route taken for one whole graph, with its bounded reasons."""

    route: IntentSynthesisRoute
    reasons: tuple[str, ...] = Field(min_length=1)

    @field_validator("route", mode="after")
    @classmethod
    def graph_route(cls, value: IntentSynthesisRoute) -> IntentSynthesisRoute:
        if value not in GRAPH_ROUTES:
            raise ValueError(f"{value.value} is not a graph route")
        return value

    @field_validator("reasons", mode="after")
    @classmethod
    def non_empty_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not reason for reason in value):
            raise ValueError("a reason may not be empty")
        return value


class GraphNodeAssignment(FrozenModel):
    """One node's runtime assignment as recorded. ``authority`` is ``None`` only off ``APPLY``,
    where a route such as ``REQUIRE_HUMAN`` may have assigned none."""

    local_id: str = Field(pattern=LOCAL_ID_PATTERN)
    origin: SynthesisOrigin
    authority: Authority | None


def validate_graph_decision_shape(
    *,
    identity: IntentGraphIdentity,
    result: IntentGraphSynthesisResult,
    node_assignments: tuple[GraphNodeAssignment, ...],
    decision: IntentGraphDecision,
    compiled: CompiledIntentGraph | None,
) -> None:
    """The structural law every graph decision obeys, shared by payload and record.

    ``APPLY`` iff a compiled graph is present (R103): an applied decision without its effect
    would be the incomplete window R103 removed, and a compiled graph under another route would be
    an effect nobody decided.
    """
    is_apply = decision.route is IntentSynthesisRoute.APPLY
    if is_apply and compiled is None:
        raise ValueError("route APPLY requires the compiled graph it applies")
    if not is_apply and compiled is not None:
        raise ValueError(f"route {decision.route.value} must not carry a compiled graph")
    if compiled is not None and compiled.identity != identity:
        raise ValueError("BINDING_IDENTITY: the compiled graph belongs to another identity")
    assigned = [a.local_id for a in node_assignments]
    nodes = sorted(n.local_id.local_id for n in result.nodes)
    if assigned != nodes:
        raise ValueError(
            f"node assignments {assigned} must name each result node exactly once, sorted: {nodes}"
        )


class IntentGraphDecisionRecord(FrozenModel):
    """One durable graph decision: everything needed to audit it without a provider.

    ``decision_event_id`` and ``decided_at`` come from the envelope, never from the payload.
    """

    graph_contract_version: Literal["ie3.graph-v1"] = GRAPH_CONTRACT_VERSION
    identity: IntentGraphIdentity
    author: ReasonerFingerprint
    run_scope: str = Field(min_length=1)
    result: IntentGraphSynthesisResult
    node_assignments: tuple[GraphNodeAssignment, ...]
    decision: IntentGraphDecision
    compiled: CompiledIntentGraph | None
    decision_event_id: str = Field(min_length=1)
    decided_at: datetime

    @model_validator(mode="after")
    def validate_shape(self) -> IntentGraphDecisionRecord:
        validate_graph_decision_shape(
            identity=self.identity,
            result=self.result,
            node_assignments=self.node_assignments,
            decision=self.decision,
            compiled=self.compiled,
        )
        return self


# --------------------------------------------------------------------------- projection


class IntentGraphSynthesisState(FrozenModel):
    """Every durable graph decision, keyed by ``graph_instance_id``. Terminal at its event."""

    decisions: Mapping[str, IntentGraphDecisionRecord] = Field(
        default_factory=dict, validate_default=True
    )

    @field_validator("decisions", mode="after")
    @classmethod
    def freeze_decisions(
        cls, value: Mapping[str, IntentGraphDecisionRecord]
    ) -> Mapping[str, IntentGraphDecisionRecord]:
        for key, record in value.items():
            if key != record.identity.graph_instance_id:
                raise ValueError(
                    f"decision keyed {key!r} carries graph {record.identity.graph_instance_id!r}"
                )
        return MappingProxyType(dict(value))

    @field_serializer("decisions")
    def serialize_decisions(
        self, value: Mapping[str, IntentGraphDecisionRecord]
    ) -> dict[str, object]:
        return dict(value)
