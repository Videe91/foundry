"""Origin, authority and whole-graph routing for IE3 (Slice 3; design §13; R102, R109; Q4).

Pure domain: same inputs, same outcome, and the state is only read.

**The graph is one decision unit.** Precedence is ``REJECT`` > ``REQUIRE_HUMAN`` > ``APPLY``,
using the existing ``IntentSynthesisRoute`` vocabulary; no equivalent enum is introduced.

**Origin follows the author, then the evidence (R109).**
* A human author makes every node ``HUMAN_STATED``.
* A non-human node is ``RESEARCH_DERIVED`` only when it cites at least one claim directly and
  every directly cited claim's effective evidence is entirely ``RESEARCH``. Otherwise it is
  ``AI_INFERRED``. An empty direct-claim set is ``AI_INFERRED``: Slice-1's vacuous ``all([])`` is
  not inherited, because Slice-1 always has a basis and IE3 need not.

Basis authority is never read, and neither existing-object nor same-batch basis makes a node
research-derived. Either would be laundering.

**Authority comes from origin alone (R102).** A non-human node is ``PROPOSED``. A human node is
``CANONICAL`` only when a live ``AuthorityRecord`` covers the run scope; otherwise the graph needs
a human. Model capability, provider and certification are never consulted.

``route_graph_with_assigned_authority`` is independently callable. It gives anti-invention a
negative control: a runtime bug that assigned ``CANONICAL`` to a non-human node is ``REJECT``
even though normal assignment can never produce it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from foundry.domain.authority import covering_authority_record
from foundry.domain.common import Authority, FrozenModel, RelationType, SourceKind
from foundry.domain.intent_graph import (
    BasisClaimRef,
    ConstraintNodeProposal,
    GraphNodeDisposition,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_graph_state import GraphNodeAssignment, IntentGraphDecision
from foundry.domain.intent_synthesis import (
    IntentSynthesisRoute,
    SynthesisOrigin,
    validate_synthesis_actor,
)
from foundry.domain.semantic import ConstraintFacet
from foundry.domain.semantic_judgment import ReasonerFingerprint

if TYPE_CHECKING:
    from foundry.domain.state import IntentState

__all__ = [
    "GraphRoutingOutcome",
    "assign_graph_authorities",
    "derive_graph_origins",
    "route_graph_with_assigned_authority",
    "route_intent_graph",
]

_NON_HUMAN: Final = frozenset({SynthesisOrigin.AI_INFERRED, SynthesisOrigin.RESEARCH_DERIVED})


class GraphRoutingOutcome(FrozenModel):
    """Runtime-only: the assignment recorded for every node, and the whole graph's route."""

    node_assignments: tuple[GraphNodeAssignment, ...]
    decision: IntentGraphDecision


def derive_graph_origins(
    result: IntentGraphSynthesisResult,
    *,
    claim_source_kinds: Mapping[str, tuple[SourceKind, ...]],
    author_is_human: bool,
) -> dict[str, SynthesisOrigin]:
    """R109, per node. ``claim_source_kinds`` is each shown claim's effective-evidence kinds."""
    origins: dict[str, SynthesisOrigin] = {}
    for proposal in result.nodes:
        local_id = proposal.local_id.local_id
        if author_is_human:
            origins[local_id] = SynthesisOrigin.HUMAN_STATED
            continue
        cited = [
            relation.target.claim_id
            for relation in result.relations
            if relation.source.local_id == local_id
            and relation.relation_type is RelationType.DERIVED_FROM
            and isinstance(relation.target, BasisClaimRef)
        ]
        research = bool(cited) and all(
            bool(claim_source_kinds.get(claim_id))
            and all(kind is SourceKind.RESEARCH for kind in claim_source_kinds[claim_id])
            for claim_id in cited
        )
        origins[local_id] = (
            SynthesisOrigin.RESEARCH_DERIVED if research else SynthesisOrigin.AI_INFERRED
        )
    return origins


def assign_graph_authorities(
    state: IntentState,
    *,
    result: IntentGraphSynthesisResult,
    origins: Mapping[str, SynthesisOrigin],
    human_actor_id: str | None,
    run_scope: str,
) -> dict[str, Authority | None]:
    """From origin alone. ``None`` means a human's authority for this scope is unresolved."""
    authorities: dict[str, Authority | None] = {}
    for proposal in result.nodes:
        local_id = proposal.local_id.local_id
        if origins[local_id] in _NON_HUMAN:
            authorities[local_id] = Authority.PROPOSED
            continue
        assert human_actor_id is not None  # authorship validation proved it
        record = covering_authority_record(
            state, actor_id=human_actor_id, target_scope=(run_scope,)
        )
        authorities[local_id] = Authority.CANONICAL if record is not None else None
    return authorities


def route_graph_with_assigned_authority(
    state: IntentState,
    *,
    result: IntentGraphSynthesisResult,
    origins: Mapping[str, SynthesisOrigin],
    authorities: Mapping[str, Authority | None],
) -> IntentGraphDecision:
    """Govern ALREADY-assigned authority for the whole graph. The anti-invention stage."""
    reject: set[str] = set()
    human: set[str] = set()
    for proposal in result.nodes:
        local_id = proposal.local_id.local_id
        origin = origins[local_id]
        authority = authorities[local_id]
        if origin is not SynthesisOrigin.HUMAN_STATED and authority is Authority.CANONICAL:
            reject.add("AUTHORITY_INVENTION")
        if origin is SynthesisOrigin.HUMAN_STATED and authority is None:
            human.add("AUTHORITY_UNRESOLVED")
        if (
            origin is SynthesisOrigin.HUMAN_STATED
            and isinstance(proposal, ConstraintNodeProposal)
            and proposal.facet is ConstraintFacet.EXTERNAL_MANDATE
        ):
            # Q4: graph-v1 cannot represent the lawful external-provenance path; defer it.
            human.add("EXTERNAL_MANDATE_DEFERRED")
        if proposal.disposition is GraphNodeDisposition.REPLACES_STALE and proposal.replaces:
            target = state.objects.get(proposal.replaces.object_id)
            if (
                target is not None
                and target.authority is Authority.CANONICAL
                and authority is not Authority.CANONICAL
            ):
                human.add("CANONICAL_REPLACEMENT_REQUIRED")
    if reject:
        return IntentGraphDecision(route=IntentSynthesisRoute.REJECT, reasons=tuple(sorted(reject)))
    if human:
        return IntentGraphDecision(
            route=IntentSynthesisRoute.REQUIRE_HUMAN, reasons=tuple(sorted(human))
        )
    # R111: a result that only witnesses already-represented intent changes nothing.
    if not result.nodes and not result.gaps and result.unchanged_object_refs:
        return IntentGraphDecision(
            route=IntentSynthesisRoute.NO_CHANGE, reasons=("EXISTING_UNCHANGED",)
        )
    # Blocking model gaps do not force a human route (R104): they apply with the safe graph and
    # keep blocking closure until resolved. A gap-only graph applies so the work becomes durable.
    if not result.nodes:
        reason = "UNRESOLVED_WORK_RECORDED"
    elif all(origins[n.local_id.local_id] is SynthesisOrigin.HUMAN_STATED for n in result.nodes):
        reason = "HUMAN_AUTHORITY"
    else:
        reason = "NON_HUMAN_PROPOSED"
    return IntentGraphDecision(route=IntentSynthesisRoute.APPLY, reasons=(reason,))


def route_intent_graph(
    state: IntentState,
    *,
    result: IntentGraphSynthesisResult,
    origins: Mapping[str, SynthesisOrigin],
    author: ReasonerFingerprint,
    human_actor_id: str | None,
    run_scope: str,
) -> GraphRoutingOutcome:
    """Authorship, then authority from origin, then the whole-graph route."""
    validate_synthesis_actor(author, human_actor_id)
    if set(origins) != {n.local_id.local_id for n in result.nodes}:
        raise ValueError("every node needs exactly one origin")
    for local_id, origin in origins.items():
        if origin is SynthesisOrigin.DETERMINISTIC_NORMALIZATION:
            raise ValueError("origin DETERMINISTIC_NORMALIZATION is unsupported")
        if (origin is SynthesisOrigin.HUMAN_STATED) is not author.is_human:
            raise ValueError(
                f"{local_id!r} carries origin {origin.value}; origin follows the author"
            )
    authorities = assign_graph_authorities(
        state,
        result=result,
        origins=origins,
        human_actor_id=human_actor_id,
        run_scope=run_scope,
    )
    decision = route_graph_with_assigned_authority(
        state, result=result, origins=origins, authorities=authorities
    )
    return GraphRoutingOutcome(
        node_assignments=tuple(
            GraphNodeAssignment(local_id=lid, origin=origins[lid], authority=authorities[lid])
            for lid in sorted(origins)
        ),
        decision=decision,
    )
