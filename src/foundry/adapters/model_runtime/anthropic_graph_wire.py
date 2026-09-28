"""The compact Anthropic wire representation of the IE3 graph answer.

A transport representation only. Foundry's contract is ``IntentGraphDraftPayload`` and its
canonical schema (``GRAPH_ANSWER_SCHEMA_SHA256``); nothing here redefines it. The pipeline is::

    canonical contract -> compact wire schema -> Claude response
      -> parse_graph_wire (this module; deterministic, mechanical)
      -> IntentGraphDraftPayload validation (the canonical authority, as for every provider)
      -> existing graph validation / compiler -> existing exam scorer

Why a separate representation: Anthropic compiles a structured-output schema to a grammar, and the
canonical graph schema (nine node kinds x two dispositions as a union, three-way reference
unions, nullable fields) compiles to a grammar Anthropic refuses as too large
(``tests/certification/evidence/_compatibility/anthropic/schema_probe.json``). This form removes
every union and every ``$ref``:

* **One node envelope** carries the fields of every kind. Every field is required. A kind-specific
  string that does not apply to the node's kind is the empty string, and a kind-specific enum that
  does not apply is ``null``. Canonically none of these strings may be empty and neither enum may
  be null, so the neutral value can never be mistaken for a real one. It converts to *absent*.
* **One reference shape** ``{namespace, id}`` stands for the canonical local, existing and basis
  references. The namespace decides the canonical field name (``local_id``, ``object_id``,
  ``claim_id``).
* **Bare ids** stand for references whose namespace is fixed canonically (a node's ``local_id``,
  a relation ``source``, ``replaces``, ``unchanged_object_refs``).
* ``confidence`` is the only optional property; absent means absent, exactly as canonically.

The conversion is mechanical: renaming and re-nesting. It never picks a kind, never fills a
missing decision, never drops a value the model gave, and never repairs. A value the model gave
where its kind does not allow it is carried into the canonical form, where canonical validation
refuses it. Every canonical law the grammar does not enforce (``DEFERRED_TO_CANONICAL``) is still
enforced, by the same Pydantic types every other provider's answer passes through.

The field names are the canonical ones the runtime-v3 prompt uses. The descriptions state only
what the canonical schema and that prompt already state.
"""

from __future__ import annotations

import copy
from typing import Any, Final, Literal

from pydantic import ConfigDict, field_validator

from foundry.domain.common import FrozenModel, RiskLevel
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    IE3_PROPOSABLE_RELATIONS,
    LOCAL_ID_PATTERN,
    GraphNodeDisposition,
    MissingNeed,
)
from foundry.domain.semantic import ConstraintFacet, SemanticKind

__all__ = [
    "ANTHROPIC_GRAPH_WIRE_REPRESENTATION",
    "DEFERRED_TO_CANONICAL",
    "GRAMMAR_ENFORCED",
    "GraphWireShapeError",
    "anthropic_graph_wire_schema",
    "parse_graph_wire",
]

ANTHROPIC_GRAPH_WIRE_REPRESENTATION: Final[str] = "foundry.anthropic-graph-wire.v1"
"""Identity of this schema *and* its converter. Changing either requires a new version; a test
pins this module's source digest to this identity."""

GRAMMAR_ENFORCED: Final[tuple[str, ...]] = (
    "the four top-level arrays are present and nothing else is",
    "every object is closed (no unknown property) and states every required property",
    "JSON types of every field (string, number, array, object)",
    "node kind is one of the nine proposable SemanticKinds",
    "disposition is NEW or REPLACES_STALE",
    "facet is a ConstraintFacet or null",
    "proposed_risk_level is a RiskLevel or null",
    "relation_type is DERIVED_FROM, AFFECTS, SERVES or EXCLUDES",
    "reference namespace is local, existing or basis",
    "gap kind is a GapKind",
    "missing_need is PROJECT_CHOICE, EXTERNAL_FACT or UNDETERMINED",
)
"""What Anthropic's decoder guarantees for this representation."""

DEFERRED_TO_CANONICAL: Final[tuple[str, ...]] = (
    f"local ids (node, relation source, local reference, gap id) match {LOCAL_ID_PATTERN}",
    "statement, mission, decision_rationale, proposal_rationale, gap description and every "
    "referenced id are non-empty",
    "confidence lies in [0, 1]",
    "an INTENT has a mission and no statement; every other kind has a statement and no mission",
    "only a DECISION has a decision_rationale, and a DECISION must have one",
    "only a CONSTRAINT has a facet, and a CONSTRAINT must have one",
    "only an ASSUMPTION may carry proposed_risk_level",
    "NEW names no replacement; REPLACES_STALE names one; INTENT and ASSUMPTION are never replaced",
    "every IntentGraphDraftPayload validator, exactly as for every other provider",
)
"""What only canonical validation enforces. A wire-valid answer violating any of these is a
protocol failure; it never reaches graph validation or scoring."""

_NODE_KINDS: Final[tuple[str, ...]] = tuple(
    kind.value
    for kind in (
        SemanticKind.INTENT,
        SemanticKind.GOAL,
        SemanticKind.OUTCOME,
        SemanticKind.REQUIREMENT,
        SemanticKind.CONSTRAINT,
        SemanticKind.NON_GOAL,
        SemanticKind.PREFERENCE,
        SemanticKind.DECISION,
        SemanticKind.ASSUMPTION,
    )
)
_DISPOSITIONS: Final[tuple[str, ...]] = tuple(d.value for d in GraphNodeDisposition)
_FACETS: Final[tuple[str, ...]] = tuple(f.value for f in ConstraintFacet)
_RISK_LEVELS: Final[tuple[str, ...]] = tuple(r.value for r in RiskLevel)
_RELATIONS: Final[tuple[str, ...]] = tuple(
    r.value for r in sorted(IE3_PROPOSABLE_RELATIONS, key=lambda r: r.value)
)
_NAMESPACES: Final[tuple[str, ...]] = ("local", "existing", "basis")
_GAP_KINDS: Final[tuple[str, ...]] = tuple(k.value for k in GapKind)
_MISSING_NEEDS: Final[tuple[str, ...]] = tuple(m.value for m in MissingNeed)

_ID_FIELD: Final[dict[str, str]] = {
    "local": "local_id",
    "existing": "object_id",
    "basis": "claim_id",
}
_KIND_SPECIFIC_TEXT: Final[tuple[str, ...]] = ("statement", "mission", "decision_rationale")


# --------------------------------------------------------------------------- the wire schema


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _enum(values: tuple[str, ...], description: str, *, nullable: bool = False) -> dict[str, Any]:
    if nullable:
        return {"enum": [*values, None], "description": description}
    return {"type": "string", "enum": list(values), "description": description}


def _object(properties: dict[str, Any], *, optional: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": [name for name in properties if name not in optional],
        "additionalProperties": False,
    }


def _reference(description: str) -> dict[str, Any]:
    return {
        **_object(
            {
                "namespace": _enum(
                    _NAMESPACES,
                    "local: a node you create in this answer; existing: an object shown in "
                    "request.known_objects; basis: a claim shown in request.basis.",
                ),
                "id": _string("The local id, the existing object id or the basis claim id."),
            }
        ),
        "description": description,
    }


_CONFIDENCE: Final[dict[str, Any]] = {
    "type": "number",
    "description": "Optional metadata only, between 0 and 1. It is never authority.",
}

_WIRE_SCHEMA: Final[dict[str, Any]] = _object(
    {
        "nodes": {
            "type": "array",
            "items": _object(
                {
                    "kind": _enum(_NODE_KINDS, "The node kind."),
                    "local_id": _string(
                        f"Your local id for this new node, matching {LOCAL_ID_PATTERN}."
                    ),
                    "disposition": _enum(
                        _DISPOSITIONS,
                        "NEW, or REPLACES_STALE when this node supersedes the stale existing "
                        "object named in replaces. An INTENT or an ASSUMPTION is always NEW.",
                    ),
                    "replaces": _string(
                        "The existing object id this node replaces when disposition is "
                        "REPLACES_STALE; the empty string when disposition is NEW."
                    ),
                    "statement": _string(
                        "The statement of any kind except INTENT; the empty string for an INTENT."
                    ),
                    "mission": _string(
                        "The mission of an INTENT; the empty string for every other kind."
                    ),
                    "decision_rationale": _string(
                        "The project's reason for the choice, for a DECISION; the empty string "
                        "for every other kind."
                    ),
                    "facet": _enum(
                        _FACETS,
                        "Required for a CONSTRAINT: what can relax it. null for every other kind.",
                        nullable=True,
                    ),
                    "proposed_risk_level": _enum(
                        _RISK_LEVELS,
                        "An optional risk estimate for an ASSUMPTION, or null. Always null for "
                        "every other kind.",
                        nullable=True,
                    ),
                    "proposal_rationale": _string("Why this node is proposed."),
                    "confidence": _CONFIDENCE,
                },
                optional=("confidence",),
            ),
        },
        "relations": {
            "type": "array",
            "items": _object(
                {
                    "source": _string("The local id of one of the new nodes you propose."),
                    "relation_type": _enum(_RELATIONS, "The relation type."),
                    "target": _reference("The relation target."),
                }
            ),
        },
        "gaps": {
            "type": "array",
            "items": _object(
                {
                    "local_gap_id": _string(
                        f"Your local id for this gap, matching {LOCAL_ID_PATTERN}."
                    ),
                    "kind": _enum(_GAP_KINDS, "The gap kind."),
                    "description": _string("What is unresolved."),
                    "missing_need": _enum(_MISSING_NEEDS, "What the unresolved region is missing."),
                    "anchors": {"type": "array", "items": _reference("A gap anchor.")},
                    "confidence": _CONFIDENCE,
                },
                optional=("confidence",),
            ),
        },
        "unchanged_object_refs": {
            "type": "array",
            "items": _string(
                "The id of a shown existing object that already represents a meaning asserted "
                "by the supplied claims."
            ),
        },
    }
)


def anthropic_graph_wire_schema() -> dict[str, Any]:
    """The exact schema sent as ``output_config.format.schema``. A fresh copy every call."""
    return copy.deepcopy(_WIRE_SCHEMA)


# --------------------------------------------------------------------------- the parser


class GraphWireShapeError(ValueError):
    """The text is not an instance of the compact wire schema. Raised before any conversion."""


class _Wire(FrozenModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _WireReference(_Wire):
    namespace: Literal["local", "existing", "basis"]
    id: str


class _WithConfidence(_Wire):
    confidence: float | None = None
    """Optional on the wire, never null there: absent means absent."""

    @field_validator("confidence", mode="before")
    @classmethod
    def _no_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("confidence is a number when present; absent means absent")
        return value


class _WireNode(_WithConfidence):
    kind: Literal[
        "INTENT",
        "GOAL",
        "OUTCOME",
        "REQUIREMENT",
        "CONSTRAINT",
        "NON_GOAL",
        "PREFERENCE",
        "DECISION",
        "ASSUMPTION",
    ]
    local_id: str
    disposition: Literal["NEW", "REPLACES_STALE"]
    replaces: str
    statement: str
    mission: str
    decision_rationale: str
    facet: Literal["EXTERNAL_MANDATE", "PROJECT_BOUNDARY", "EVIDENCE_BOUND"] | None
    proposed_risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None
    proposal_rationale: str


class _WireRelation(_Wire):
    source: str
    relation_type: Literal["AFFECTS", "DERIVED_FROM", "EXCLUDES", "SERVES"]
    target: _WireReference


class _WireGap(_WithConfidence):
    local_gap_id: str
    kind: Literal[
        "MISSING_INFORMATION",
        "AMBIGUITY",
        "CONTRADICTION",
        "UNSUPPORTED_ASSUMPTION",
        "MISSING_AUTHORITY",
        "MISSING_SUCCESS_METRIC",
        "MISSING_VERIFICATION_OBLIGATION",
        "UNRESOLVED_RISK",
        "STALE_EVIDENCE",
        "INSUFFICIENT_EVIDENCE",
        "UNDERSPECIFIED_SCOPE",
        "UNRESOLVED_DEPENDENCY",
        "WORKER_DIVERGENCE",
        "CONTEXT_FAILURE",
    ]
    description: str
    missing_need: Literal["PROJECT_CHOICE", "EXTERNAL_FACT", "UNDETERMINED"]
    anchors: tuple[_WireReference, ...]


class _WirePayload(_Wire):
    nodes: tuple[_WireNode, ...]
    relations: tuple[_WireRelation, ...]
    gaps: tuple[_WireGap, ...]
    unchanged_object_refs: tuple[str, ...]


def _reference_to_canonical(ref: _WireReference) -> dict[str, str]:
    return {"namespace": ref.namespace, _ID_FIELD[ref.namespace]: ref.id}


def _node_to_canonical(node: _WireNode) -> dict[str, Any]:
    canonical: dict[str, Any] = {
        "kind": node.kind,
        "local_id": {"namespace": "local", "local_id": node.local_id},
        "disposition": node.disposition,
        "proposal_rationale": node.proposal_rationale,
    }
    if node.replaces != "":
        canonical["replaces"] = {"namespace": "existing", "object_id": node.replaces}
    for name in _KIND_SPECIFIC_TEXT:
        value = getattr(node, name)
        if value != "":
            canonical[name] = value
    if node.facet is not None:
        canonical["facet"] = node.facet
    if node.proposed_risk_level is not None:
        canonical["proposed_risk_level"] = node.proposed_risk_level
    if "confidence" in node.model_fields_set:
        canonical["confidence"] = node.confidence
    return canonical


def _gap_to_canonical(gap: _WireGap) -> dict[str, Any]:
    canonical: dict[str, Any] = {
        "local_gap_id": gap.local_gap_id,
        "kind": gap.kind,
        "description": gap.description,
        "missing_need": gap.missing_need,
        "anchors": [_reference_to_canonical(anchor) for anchor in gap.anchors],
    }
    if "confidence" in gap.model_fields_set:
        canonical["confidence"] = gap.confidence
    return canonical


def parse_graph_wire(text: str) -> dict[str, Any]:
    """Wire JSON text -> the canonical JSON form of the same answer. Nothing is validated
    canonically here: the caller validates the result as ``IntentGraphDraftPayload``."""
    try:
        wire = _WirePayload.model_validate_json(text)
    except ValueError as exc:
        raise GraphWireShapeError(str(exc)) from exc
    return {
        "nodes": [_node_to_canonical(node) for node in wire.nodes],
        "relations": [
            {
                "source": {"namespace": "local", "local_id": relation.source},
                "relation_type": relation.relation_type,
                "target": _reference_to_canonical(relation.target),
            }
            for relation in wire.relations
        ],
        "gaps": [_gap_to_canonical(gap) for gap in wire.gaps],
        "unchanged_object_refs": [
            {"namespace": "existing", "object_id": object_id}
            for object_id in wire.unchanged_object_refs
        ],
    }
