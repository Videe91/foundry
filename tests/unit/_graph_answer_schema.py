"""Standards-compliant validation of the graph-answer schemas, and the corpora that exercise them.

Test-only. ``jsonschema`` is a dev dependency; production never validates JSON Schema itself,
because Pydantic is the final authority on every returned answer.

Regex dialect: JSON Schema's ``pattern`` is ECMA-262, where ``$`` without the ``m`` flag matches
only at the end of the input. Python's ``re`` (which ``jsonschema`` uses) also lets ``$`` match
before a final newline, so ``"abc\\n"`` would wrongly satisfy ``^[a-z]+$``. The validator below
evaluates ``pattern`` with ECMA semantics instead, and refuses any pattern it cannot translate
exactly, rather than approximating it.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator, Mapping
from typing import Any

from jsonschema import Draft202012Validator, ValidationError, validators
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    IntentGraphDraftPayload,
    IntentGraphGapDraft,
)
from foundry.domain.common import RelationType, RiskLevel
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    AssumptionNodeProposal,
    BasisClaimRef,
    ConstraintNodeProposal,
    DecisionNodeProposal,
    ExistingObjectRef,
    GoalNodeProposal,
    GraphNodeDisposition,
    GraphRelationProposal,
    IntentNodeProposal,
    LocalNodeRef,
    MissingNeed,
    NonGoalNodeProposal,
    OutcomeNodeProposal,
    PreferenceNodeProposal,
    RequirementNodeProposal,
)
from foundry.domain.semantic import ConstraintFacet, SemanticKind

# --------------------------------------------------------------------------- validation

_TRAILING_DOLLAR = re.compile(r"^(?P<body>(?:[^\\$\[]|\\.|\[(?:[^\]\\]|\\.)*\])*)\$$")


def ecma_pattern_to_python(pattern: str) -> str:
    """ECMA ``$`` (no ``m`` flag) is Python ``\\Z``. Only a single trailing anchor is supported."""
    if "$" not in pattern:
        return pattern
    match = _TRAILING_DOLLAR.match(pattern)
    if match is None:
        raise NotImplementedError(f"pattern {pattern!r} has a '$' this translator cannot prove")
    return match.group("body") + r"\Z"


def _ecma_pattern(
    validator: Any, pattern: str, instance: Any, schema: Mapping[str, Any]
) -> Iterator[ValidationError]:
    if not validator.is_type(instance, "string"):
        return
    if re.search(ecma_pattern_to_python(pattern), instance) is None:
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


EcmaValidator = validators.extend(Draft202012Validator, {"pattern": _ecma_pattern})


_VALIDATORS: dict[int, tuple[Mapping[str, Any], Any]] = {}
"""Keyed by identity; the schema is held so its id can never be reused by another object."""


def is_valid(schema: Mapping[str, Any], instance: Any) -> bool:
    cached = _VALIDATORS.get(id(schema))
    if cached is None or cached[0] is not schema:
        cached = _VALIDATORS[id(schema)] = (schema, EcmaValidator(schema))
    return bool(cached[1].is_valid(instance))


def patterns_in(schema: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        if isinstance(schema.get("pattern"), str):
            found.add(schema["pattern"])
        for value in schema.values():
            found |= patterns_in(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= patterns_in(value)
    return found


def pydantic_accepts(instance: Any) -> bool:
    """The adapter's own path: JSON text through ``model_validate_json``."""
    try:
        IntentGraphDraftPayload.model_validate_json(json.dumps(instance))
    except PydanticValidationError:
        return False
    return True


def with_defs(root: Mapping[str, Any], sub: Mapping[str, Any]) -> dict[str, Any]:
    """A sub-schema made standalone by carrying the root's ``$defs``."""
    return {"$defs": root.get("$defs", {}), **sub}


def union_branches(root: Mapping[str, Any], def_name: str) -> list[dict[str, Any]]:
    union = root["$defs"][def_name]
    key = "oneOf" if "oneOf" in union else "anyOf"
    return list(union[key])


_BRANCHES: dict[tuple[int, str], tuple[Mapping[str, Any], list[dict[str, Any]]]] = {}


def branch_schemas(root: Mapping[str, Any], def_name: str) -> list[dict[str, Any]]:
    """Each branch of a union, made standalone once and reused (identity-cached)."""
    cached = _BRANCHES.get((id(root), def_name))
    if cached is None or cached[0] is not root:
        built = [with_defs(root, branch) for branch in union_branches(root, def_name)]
        cached = _BRANCHES[(id(root), def_name)] = (root, built)
    return cached[1]


def matching_branches(root: Mapping[str, Any], def_name: str, instance: Any) -> list[int]:
    return [
        i for i, branch in enumerate(branch_schemas(root, def_name)) if is_valid(branch, instance)
    ]


# --------------------------------------------------------------------------- lawful values

REFS: tuple[Any, ...] = (
    LocalNodeRef(local_id="n1"),
    ExistingObjectRef(object_id="OBJ-1"),
    BasisClaimRef(claim_id="CLAIM-1"),
)

_STATEMENT_KINDS: tuple[type[Any], ...] = (
    GoalNodeProposal,
    OutcomeNodeProposal,
    RequirementNodeProposal,
    NonGoalNodeProposal,
    PreferenceNodeProposal,
)
REPLACEABLE_KINDS: tuple[SemanticKind, ...] = (
    SemanticKind.GOAL,
    SemanticKind.OUTCOME,
    SemanticKind.REQUIREMENT,
    SemanticKind.CONSTRAINT,
    SemanticKind.NON_GOAL,
    SemanticKind.PREFERENCE,
    SemanticKind.DECISION,
)
IRREPLACEABLE_KINDS: tuple[SemanticKind, ...] = (SemanticKind.INTENT, SemanticKind.ASSUMPTION)
NODE_KINDS: tuple[SemanticKind, ...] = (*IRREPLACEABLE_KINDS, *REPLACEABLE_KINDS)


def _replacement_states() -> list[dict[str, Any]]:
    return [
        {},
        {
            "disposition": GraphNodeDisposition.REPLACES_STALE,
            "replaces": ExistingObjectRef(object_id="OBJ-old"),
        },
    ]


def lawful_nodes() -> list[Any]:
    """Every node family in every lawful disposition state, with optional metadata varied."""
    nodes: list[Any] = []
    handle = LocalNodeRef(local_id="n1")
    for confidence in (None, 0.0, 0.5, 1.0):
        common = {"local_id": handle, "proposal_rationale": "why", "confidence": confidence}
        nodes.append(IntentNodeProposal(**common, mission="m"))
        for risk in (None, *RiskLevel):
            nodes.append(AssumptionNodeProposal(**common, statement="s", proposed_risk_level=risk))
        for state in _replacement_states():
            for cls in _STATEMENT_KINDS:
                nodes.append(cls(**common, statement="s", **state))
            for facet in ConstraintFacet:
                nodes.append(ConstraintNodeProposal(**common, statement="s", facet=facet, **state))
            nodes.append(
                DecisionNodeProposal(**common, statement="s", decision_rationale="d", **state)
            )
    return nodes


def lawful_relations() -> list[GraphRelationProposal]:
    proposable = (
        RelationType.DERIVED_FROM,
        RelationType.SERVES,
        RelationType.EXCLUDES,
        RelationType.AFFECTS,
    )
    return [
        GraphRelationProposal(
            source=LocalNodeRef(local_id="n1"), relation_type=relation, target=target
        )
        for relation in proposable
        for target in REFS
    ]


def lawful_gaps() -> list[IntentGraphGapDraft]:
    gaps = []
    for kind in GapKind:
        for need in MissingNeed:
            gaps.append(
                IntentGraphGapDraft(
                    local_gap_id="g1", kind=kind, description="d", missing_need=need
                )
            )
    gaps.append(
        IntentGraphGapDraft(
            local_gap_id="g-2",
            kind=GapKind.AMBIGUITY,
            description="d",
            missing_need=MissingNeed.UNDETERMINED,
            anchors=REFS,
            confidence=0.25,
        )
    )
    return gaps


def lawful_payloads() -> list[IntentGraphDraftPayload]:
    payloads = [IntentGraphDraftPayload()]
    payloads += [IntentGraphDraftPayload(nodes=(node,)) for node in lawful_nodes()]
    payloads += [IntentGraphDraftPayload(relations=(rel,)) for rel in lawful_relations()]
    payloads += [IntentGraphDraftPayload(gaps=(gap,)) for gap in lawful_gaps()]
    payloads.append(
        IntentGraphDraftPayload(
            unchanged_object_refs=(
                ExistingObjectRef(object_id="A"),
                ExistingObjectRef(object_id="B"),
            )
        )
    )
    payloads.append(
        IntentGraphDraftPayload(
            nodes=tuple(lawful_nodes()[:12]),
            relations=tuple(lawful_relations()),
            gaps=tuple(lawful_gaps()[-2:]),
            unchanged_object_refs=(ExistingObjectRef(object_id="A"),),
        )
    )
    return payloads


def explicit(value: Any) -> Any:
    """Every field present, defaults materialized: the form a strict provider wire requires."""
    return value.model_dump(mode="json")


def minimal(value: IntentGraphDraftPayload) -> dict[str, Any]:
    """Every default omitted except a tag at a discriminated-union position, which Pydantic's
    union dispatch requires: the least a canonical producer may send."""
    dump = value.model_dump(mode="json", exclude_defaults=True)
    for node, source in zip(dump.get("nodes", []), value.nodes, strict=True):
        node["kind"] = source.kind.value
    for rel, source in zip(dump.get("relations", []), value.relations, strict=True):
        rel["target"]["namespace"] = source.target.namespace
    for gap, source in zip(dump.get("gaps", []), value.gaps, strict=True):
        for anchor, ref in zip(gap.get("anchors", []), source.anchors, strict=True):
            anchor["namespace"] = ref.namespace
    return dump


def _union_tag(path: tuple[Any, ...]) -> str | None:
    """The tag Pydantic's union dispatch requires at this position, if it is a union member."""
    if len(path) == 2 and path[0] == "nodes":
        return "kind"
    if len(path) == 3 and path[0] == "relations" and path[2] == "target":
        return "namespace"
    if len(path) == 4 and path[0] == "gaps" and path[2] == "anchors":
        return "namespace"
    return None


def defaulted_fields(value: BaseModel, dump: Any) -> list[tuple[tuple[Any, ...], str]]:
    """Every (container path, key) whose explicit value equals that field's Pydantic default,
    excluding a union tag, which dispatch requires. Omitting any of them is a lawful spelling."""
    found: list[tuple[tuple[Any, ...], str]] = []

    def walk(model: BaseModel, path: tuple[Any, ...]) -> None:
        tag = _union_tag(path)
        for name, info in type(model).model_fields.items():
            current = getattr(model, name)
            if not info.is_required() and name != tag and current == info.get_default():
                found.append((path, name))
            if isinstance(current, BaseModel):
                walk(current, (*path, name))
            elif isinstance(current, tuple):
                for index, item in enumerate(current):
                    if isinstance(item, BaseModel):
                        walk(item, (*path, name, index))

    walk(value, ())
    return found


# --------------------------------------------------------------------------- adversarial corpus

_SCALARS: tuple[Any, ...] = (None, "", "X", 0, 1.5, -1, True, [], {})
_TAGS: tuple[str, ...] = (
    *(k.value for k in SemanticKind),
    "local",
    "existing",
    "basis",
    *(d.value for d in GraphNodeDisposition),
    *(r.value for r in RelationType),
    "bogus",
)
_IDS: tuple[str, ...] = ("A", "a\n", "1a", "a" * 65, "a-b_c", "a b")
_REF_SHAPES: tuple[Any, ...] = (
    {"namespace": "local", "local_id": "a"},
    {"namespace": "existing", "object_id": "X"},
    {"namespace": "basis", "claim_id": "C"},
    {"local_id": "a"},
    {"object_id": "X"},
    {"namespace": "existing", "local_id": "a"},
    {"namespace": "local", "local_id": "a", "object_id": "X"},
    {"namespace": "existing", "object_id": ""},
    None,
)


def _node_field_donors() -> list[dict[str, Any]]:
    donors: dict[str, dict[str, Any]] = {}
    for node in lawful_nodes():
        donors.setdefault(type(node).__name__ + str(node.disposition), explicit(node))
    return list(donors.values())


def _mutations(value: Any, donors: list[dict[str, Any]]) -> Iterator[Any]:
    """One-step mutations at every position of a JSON tree."""
    if isinstance(value, dict):
        for key in value:
            without = {k: v for k, v in value.items() if k != key}
            yield without
            for replacement in (*_SCALARS, *_TAGS, *_IDS, *_REF_SHAPES):
                yield {**value, key: replacement}
            for inner in _mutations(value[key], donors):
                yield {**value, key: inner}
        yield {**value, "zzz": 1}
        if "kind" in value:
            for donor in donors:
                yield {**donor, **value}  # this node's tag and fields plus another family's
                yield {**value, **donor}  # another family's tag and fields plus this node's
    elif isinstance(value, list):
        for i, item in enumerate(value):
            for inner in _mutations(item, donors):
                yield [*value[:i], inner, *value[i + 1 :]]


def adversarial_payloads() -> list[Any]:
    """Every one-step mutation of a representative set of explicit and minimal payloads."""
    donors = _node_field_donors()
    bases: list[Any] = []
    for node in donors:  # one explicit node per family and disposition state: all 16
        bases.append({"nodes": [node], "relations": [], "gaps": [], "unchanged_object_refs": []})
    for rel in lawful_relations()[:3]:
        bases.append(explicit(IntentGraphDraftPayload(relations=(rel,))))
    bases.append(explicit(IntentGraphDraftPayload(gaps=(lawful_gaps()[-1],))))
    bases.append(
        explicit(IntentGraphDraftPayload(unchanged_object_refs=(ExistingObjectRef(object_id="A"),)))
    )
    corpus: dict[str, Any] = {}
    for base in bases:
        for candidate in (base, *_mutations(base, donors)):
            corpus.setdefault(json.dumps(candidate, sort_keys=True), candidate)
    return [copy.deepcopy(v) for v in corpus.values()]
