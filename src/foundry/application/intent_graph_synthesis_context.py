"""Bounded context compilation and result validation for Intent Graph synthesis (IE3 Slice 3).

Design: ``docs/superpowers/specs/2026-09-26-ie3-graph-synthesis-design.md`` (§9, §21).

Two halves, both pure:

* **compile** decides exactly what a graph synthesizer may see for one scope:
  * current IE3-kind objects applicable to the scope, with stale ones shown and flagged;
  * the live semantic basis, under Slice-1's own eligibility law, reused rather than restated;
  * canonical roots and OPEN applicable gaps;
  * relations only on the four graph axes, and only toward something also shown.

  Over the Slice-1 bounds it is refused, never truncated. A silently shortened context changes
  what the proposer can conclude while looking identical.
* **validate** checks a returned graph against *that exact request*. The visibility surface is
  built from the request alone, so the model can only cite what it saw, and nothing is rescued
  from fresher state.

Nothing here writes events, routes, assigns authority, or calls a provider.
"""

from __future__ import annotations

import json
from typing import Final

from foundry.application.intent_synthesis_context import (
    KNOWN_INTENT_OBJECT_THRESHOLD,
    MAX_KNOWN_INTENT_CONTEXT_CHARS,
    _basis_claim,
    _blockers_for,
)
from foundry.domain.authority import object_is_current
from foundry.domain.common import FrozenModel, Relation, RelationType
from foundry.domain.gap_scope import gap_applies
from foundry.domain.gaps import GapStatus
from foundry.domain.handoff import locus_in_scope
from foundry.domain.intent_graph import (
    IE3_GRAPH_NODE_KINDS,
    IE3_PROPOSABLE_RELATIONS,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_graph_validation import (
    GraphVisibility,
    IntentGraphValidationError,
    VisibleObject,
    validate_intent_graph,
)
from foundry.domain.intent_view import derive_intent_view
from foundry.domain.relevance import canonical_roots
from foundry.domain.scope import scope_applies
from foundry.domain.semantic import Intent, SemanticBase
from foundry.domain.semantic_identity import IssueEpistemicState
from foundry.domain.state import IntentState
from foundry.ports.intent_graph_synthesizer import (
    IntentGraphSynthesisRequest,
    KnownGraphObject,
    KnownOpenGap,
    KnownRelation,
)
from foundry.ports.intent_synthesizer import LocusBasis

__all__ = [
    "IntentGraphContext",
    "IntentGraphResultError",
    "compile_intent_graph_context",
    "graph_visibility_from_request",
    "known_graph_context_character_count",
    "known_graph_context_json",
    "validate_graph_result",
]

_TEXT_FIELDS: Final = ("mission", "statement")


class IntentGraphResultError(RuntimeError):
    """A graph synthesizer returned something not grounded in the request it was shown."""


class IntentGraphContext(FrozenModel):
    """A request when there is something to show, or the reason the context was refused."""

    request: IntentGraphSynthesisRequest | None
    context_failure: str | None = None


def known_graph_context_json(objects: tuple[KnownGraphObject, ...]) -> str:
    """The exact canonical rendering the character bound is measured on."""
    return json.dumps(
        [o.model_dump(mode="json") for o in objects],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def known_graph_context_character_count(objects: tuple[KnownGraphObject, ...]) -> int:
    return len(known_graph_context_json(objects))


def _text(obj: SemanticBase) -> str:
    if isinstance(obj, Intent):
        return obj.mission
    for field in _TEXT_FIELDS:
        value = getattr(obj, field, None)
        if isinstance(value, str):
            return value
    raise ValueError(f"{obj.kind} exposes no text for the graph context")


def _shown_candidates(state: IntentState, scope: str) -> list[SemanticBase]:
    return sorted(
        (
            obj
            for obj in state.objects.values()
            if obj.kind in IE3_GRAPH_NODE_KINDS
            and object_is_current(obj)
            and scope_applies(tuple(obj.scope), scope)
        ),
        key=lambda o: o.id,
    )


def _basis(state: IntentState, scope: str) -> tuple[LocusBasis, ...]:
    """The live semantic basis, by Slice-1's eligibility law: not open, and no blocker."""
    view = derive_intent_view(state)
    loci = sorted(
        (locus for locus in view.loci if locus_in_scope(locus, scope)),
        key=lambda locus: locus.representative_id,
    )
    return tuple(
        LocusBasis(
            locus_representative_id=locus.representative_id,
            address_ids=tuple(sorted(locus.address_ids)),
            subject=state.semantic.addresses[locus.representative_id].subject,
            facet=state.semantic.addresses[locus.representative_id].facet,
            live_claims=tuple(
                _basis_claim(state, view, claim_id) for claim_id in sorted(locus.claim_ids)
            ),
            epistemic_state=locus.epistemic_state,
        )
        for locus in loci
        if locus.epistemic_state is not IssueEpistemicState.OPEN
        and not _blockers_for(state, view, locus)
    )


def compile_intent_graph_context(state: IntentState, *, scope: str) -> IntentGraphContext:
    """Compile exactly what a graph synthesizer may see for ``scope``. Pure; never truncates."""
    if not scope:
        raise ValueError("scope must be non-empty")
    candidates = _shown_candidates(state, scope)
    if len(candidates) > KNOWN_INTENT_OBJECT_THRESHOLD:
        # Checked before anything is compiled, so an oversized project is refused without
        # first building the context that would not be sent.
        return IntentGraphContext(
            request=None,
            context_failure=(
                f"{len(candidates)} in-scope intended-state objects in scope {scope!r} exceed "
                f"the known-object threshold of {KNOWN_INTENT_OBJECT_THRESHOLD}"
            ),
        )

    basis = _basis(state, scope)
    claim_ids = frozenset(c.claim_id for locus in basis for c in locus.live_claims)
    shown_ids = frozenset(o.id for o in candidates)
    stale = frozenset(derive_intent_view(state).stale_ids)

    def visible_relations(obj: SemanticBase) -> tuple[KnownRelation, ...]:
        return tuple(
            KnownRelation(relation_type=r.relation_type, target_id=r.target_id)
            for r in sorted(obj.relations, key=lambda r: (r.relation_type.value, r.target_id))
            if r.relation_type in IE3_PROPOSABLE_RELATIONS
            and (r.target_id in shown_ids or r.target_id in claim_ids)
        )

    known = tuple(
        KnownGraphObject(
            object_id=obj.id,
            kind=obj.kind,
            authority=obj.authority,
            is_stale=obj.id in stale,
            scope=tuple(obj.scope),
            text=_text(obj),
            facet=getattr(obj, "facet", None),
            risk_level=getattr(obj, "risk_level", None),
            relations=visible_relations(obj),
            basis_claim_ids=tuple(
                sorted(
                    {
                        r.target_id
                        for r in obj.relations
                        if r.relation_type is RelationType.DERIVED_FROM and r.target_id in claim_ids
                    }
                )
            ),
        )
        for obj in candidates
    )
    size = known_graph_context_character_count(known)
    if size > MAX_KNOWN_INTENT_CONTEXT_CHARS:
        return IntentGraphContext(
            request=None,
            context_failure=(
                f"the known-object context renders to {size} characters; the maximum is "
                f"{MAX_KNOWN_INTENT_CONTEXT_CHARS}"
            ),
        )
    if not basis and not known:
        return IntentGraphContext(request=None)

    open_gaps = tuple(
        KnownOpenGap(
            gap_id=gap.id,
            kind=gap.kind,
            description=gap.description,
            blocking=gap.blocking,
            affected_object_ids=tuple(sorted(i for i in gap.affected_object_ids if i in shown_ids)),
        )
        for _, gap in sorted(state.gaps.items())
        if gap.status is GapStatus.OPEN and gap_applies(state, gap, scope)
    )
    return IntentGraphContext(
        request=IntentGraphSynthesisRequest(
            project_id=state.project_id,
            scope=scope,
            basis=basis,
            known_objects=known,
            root_intent_ids=canonical_roots(state, scope),
            open_gaps=open_gaps,
        )
    )


def graph_visibility_from_request(request: IntentGraphSynthesisRequest) -> GraphVisibility:
    """The validation surface is exactly what was shown. Never fresh state."""
    return GraphVisibility(
        run_scope=request.scope,
        objects=tuple(
            VisibleObject(
                object_id=o.object_id,
                kind=o.kind,
                authority=o.authority,
                is_current=True,
                is_stale=o.is_stale,
                scope=o.scope,
                relations=tuple(
                    Relation(relation_type=r.relation_type, target_id=r.target_id)
                    for r in o.relations
                ),
            )
            for o in request.known_objects
        ),
        basis_claim_ids=frozenset(c.claim_id for locus in request.basis for c in locus.live_claims),
        root_intent_ids=request.root_intent_ids,
    )


def validate_graph_result(
    result: IntentGraphSynthesisResult,
    request: IntentGraphSynthesisRequest,
    *,
    author_is_human: bool,
) -> GraphVisibility:
    """Refuse ``result`` unless it is grounded in exactly ``request``. Returns the surface."""
    for node in result.nodes:
        if node.kind not in request.allowed_node_kinds:
            raise IntentGraphResultError(f"node kind {node.kind.value} is not allowed")
    for gap in result.gaps:
        if gap.kind not in request.allowed_gap_kinds:
            raise IntentGraphResultError(f"gap kind {gap.kind.value} is not allowed")
    limits = request.limits
    if (
        len(result.nodes) > limits.max_nodes
        or len(result.relations) > limits.max_relations
        or len(result.gaps) > limits.max_gaps
    ):
        raise IntentGraphResultError("the result exceeds the request's graph limits")
    visibility = graph_visibility_from_request(request)
    try:
        validate_intent_graph(result, visibility, author_is_human=author_is_human)
    except IntentGraphValidationError as exc:
        raise IntentGraphResultError(str(exc)) from exc
    return visibility
