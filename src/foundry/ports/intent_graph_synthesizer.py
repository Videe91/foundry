"""Intent Graph Synthesizer port (IE3 Slice 3, design §21-§22).

A graph synthesizer is compute, not memory and not authority. It receives one bounded
``IntentGraphSynthesisRequest`` compiled fresh from current state for exactly one call, and
returns an ``IntentGraphSynthesisResult``. It never receives an ``IntentState``, an
``EventStore``, a judgment body, a Decision's rationale or any evidence content.

Request-only, always. Nothing here is canonical state, an event payload or persisted truth. It
is temporary reasoning context, discarded after the call. It is a new, versioned DTO beside the
frozen Slice-1 ``IntentSynthesisRequest``, which stays untouched.

Nothing here names a durable id for anything new. New nodes are ``LocalNodeRef`` handles in the
result, and runtime mints every durable id.

Provider-neutral: no vendor name, payload shape or transport appears here.
"""

from __future__ import annotations

from typing import Final, Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from foundry.domain.common import Authority, FrozenModel, RelationType, RiskLevel
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    IE3_GRAPH_NODE_KINDS,
    IE3_MODEL_GAP_KINDS,
    IE3_PROPOSABLE_RELATIONS,
    MAX_GRAPH_GAPS,
    MAX_GRAPH_NODES,
    MAX_GRAPH_RELATIONS,
    IntentGraphSynthesisResult,
)
from foundry.domain.semantic import ConstraintFacet, SemanticKind
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.structural_refusal import ReproposalNotice
from foundry.ports.intent_synthesizer import LocusBasis

__all__ = [
    "GraphLimits",
    "IntentGraphSynthesisRequest",
    "IntentGraphSynthesizer",
    "KnownGraphObject",
    "KnownOpenGap",
    "KnownRelation",
]

_PINNED_LIMITS: Final = (MAX_GRAPH_NODES, MAX_GRAPH_RELATIONS, MAX_GRAPH_GAPS)


class GraphLimits(FrozenModel):
    """The graph-v1 caps, echoed so the proposer knows them. Pinned: 32 / 128 / 16 (Q6)."""

    max_nodes: int = MAX_GRAPH_NODES
    max_relations: int = MAX_GRAPH_RELATIONS
    max_gaps: int = MAX_GRAPH_GAPS

    @model_validator(mode="after")
    def pinned(self) -> GraphLimits:
        if (self.max_nodes, self.max_relations, self.max_gaps) != _PINNED_LIMITS:
            raise ValueError(f"graph-v1 limits are pinned to {_PINNED_LIMITS}")
        return self


class KnownRelation(FrozenModel):
    """One object-local relation whose target was also shown."""

    relation_type: RelationType
    target_id: str = Field(min_length=1)

    @field_validator("relation_type", mode="after")
    @classmethod
    def only_graph_axes(cls, value: RelationType) -> RelationType:
        if value not in IE3_PROPOSABLE_RELATIONS:
            raise ValueError(f"{value.value} is not shown to a graph synthesizer")
        return value


class KnownGraphObject(FrozenModel):
    """One current, in-scope intended-state object. Staleness is flagged, never filtered.

    ``text`` is the mission or statement. A Decision's rationale is deliberately absent: it is
    deliberation, not meaning to compare against.
    """

    object_id: str = Field(min_length=1)
    kind: SemanticKind
    authority: Authority
    is_stale: bool
    scope: tuple[str, ...]
    text: str = Field(min_length=1)
    facet: ConstraintFacet | None = None
    risk_level: RiskLevel | None = None
    relations: tuple[KnownRelation, ...] = ()
    basis_claim_ids: tuple[str, ...] = ()

    @field_validator("kind", mode="after")
    @classmethod
    def ie3_kind(cls, value: SemanticKind) -> SemanticKind:
        if value not in IE3_GRAPH_NODE_KINDS:
            raise ValueError(f"{value.value} is not an IE3 graph kind")
        return value


class KnownOpenGap(FrozenModel):
    """An OPEN gap applicable to the scope, so the proposer does not restate it."""

    gap_id: str = Field(min_length=1)
    kind: GapKind
    description: str
    blocking: bool
    affected_object_ids: tuple[str, ...] = ()


class IntentGraphSynthesisRequest(FrozenModel):
    """Bounded, deterministic, scope-limited context for exactly one graph synthesis call."""

    project_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    basis: tuple[LocusBasis, ...] = ()
    known_objects: tuple[KnownGraphObject, ...] = ()
    root_intent_ids: tuple[str, ...] = ()
    open_gaps: tuple[KnownOpenGap, ...] = ()
    allowed_node_kinds: frozenset[SemanticKind] = IE3_GRAPH_NODE_KINDS
    allowed_gap_kinds: frozenset[GapKind] = IE3_MODEL_GAP_KINDS
    limits: GraphLimits = Field(default_factory=GraphLimits)

    @model_validator(mode="after")
    def validate_request(self) -> IntentGraphSynthesisRequest:
        if not self.basis and not self.known_objects:
            raise ValueError(
                "a graph request needs basis or known_objects; there is nothing to show"
            )
        ids = [o.object_id for o in self.known_objects]
        if ids != sorted(set(ids)):
            raise ValueError("known_objects must be unique and sorted by object_id")
        intents = {o.object_id for o in self.known_objects if o.kind is SemanticKind.INTENT}
        if not set(self.root_intent_ids) <= intents:
            raise ValueError("every root must be a shown Intent")
        if not self.allowed_node_kinds <= IE3_GRAPH_NODE_KINDS:
            raise ValueError("allowed_node_kinds may not exceed the IE3 kinds")
        if not self.allowed_gap_kinds <= IE3_MODEL_GAP_KINDS:
            raise ValueError("allowed_gap_kinds may not exceed the IE3 model gap kinds")
        return self


class IntentGraphSynthesizer(Protocol):
    """Bounded request in, untrusted graph out. The fingerprint is read, never supplied."""

    @property
    def fingerprint(self) -> ReasonerFingerprint: ...

    def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult: ...


@runtime_checkable
class ReproposingIntentGraphSynthesizer(IntentGraphSynthesizer, Protocol):
    """A synthesizer that can answer ONE production re-proposal after a structural refusal.

    ``resynthesize`` receives the refused attempt's exact request and the fixed notice with the
    refusal findings, and returns a complete new result. Its answers are authored under
    ``reproposal_fingerprint``: a distinct policy identity, because the model saw more than the
    certified request."""

    @property
    def reproposal_fingerprint(self) -> ReasonerFingerprint: ...

    def resynthesize(
        self, request: IntentGraphSynthesisRequest, notice: ReproposalNotice
    ) -> IntentGraphSynthesisResult: ...
