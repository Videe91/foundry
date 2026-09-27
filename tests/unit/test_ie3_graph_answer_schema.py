"""The canonical graph-answer schema describes exactly what Pydantic accepts.

Hierarchy (Option A): Pydantic domain semantics are the source of truth; the canonical
graph-answer schema is a faithful, provider-neutral description of them; a provider wire schema
is a deterministic representation of the canonical one; every returned answer is parsed by
Pydantic again.

Before this correction the generated schema accepted values Pydantic rejects: a union member
without its discriminator, a relation type that is not proposable, and every disposition/
replacement combination that ``validate_disposition`` refuses. It now expresses each of those
laws, and a pinned fingerprint proves that Python validation itself did not change.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

import tests.unit._graph_answer_schema as g
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    IntentGraphDraftPayload,
)
from foundry.domain.common import RelationType
from foundry.domain.intent_graph import (
    LOCAL_ID_PATTERN,
    ExistingObjectRef,
    GoalNodeProposal,
    GraphNodeDisposition,
    GraphNodeProposal,
    LocalNodeRef,
)
from foundry.domain.semantic import SemanticKind
from tests.certification._schema_identity import schema_sha256

CANONICAL: dict[str, Any] = IntentGraphDraftPayload.model_json_schema()

HISTORICAL_CANONICAL_SHA256 = "83215cee9d4ed13bdf57f95ae770406a1f19b17604ff919cffb903306911837c"
"""The graph-answer schema as generated at 80ec454, before this correction."""

PYDANTIC_BEHAVIOUR_FINGERPRINT = "5f5322457e8936225a61723bd14a4a719bb204654bcb5c8da949e83b95589dbc"
"""Pydantic's accept/reject verdict on every corpus instance, computed at 80ec454 before any
source change. Equal afterwards means the correction touched schema generation only."""

PROPOSABLE = ["DERIVED_FROM", "AFFECTS", "SERVES", "EXCLUDES"]
"""Declaration order of ``RelationType``, filtered: deterministic, never set order."""
NODE_DEFS = {
    SemanticKind.INTENT: "IntentNodeProposal",
    SemanticKind.GOAL: "GoalNodeProposal",
    SemanticKind.OUTCOME: "OutcomeNodeProposal",
    SemanticKind.REQUIREMENT: "RequirementNodeProposal",
    SemanticKind.CONSTRAINT: "ConstraintNodeProposal",
    SemanticKind.NON_GOAL: "NonGoalNodeProposal",
    SemanticKind.PREFERENCE: "PreferenceNodeProposal",
    SemanticKind.DECISION: "DecisionNodeProposal",
    SemanticKind.ASSUMPTION: "AssumptionNodeProposal",
}


def canonical_valid(instance: Any) -> bool:
    return g.is_valid(CANONICAL, instance)


def payload(**parts: Any) -> dict[str, Any]:
    return {"nodes": [], "relations": [], "gaps": [], "unchanged_object_refs": [], **parts}


def node(kind: SemanticKind, **overrides: Any) -> dict[str, Any]:
    """An explicit lawful NEW node of ``kind``, then overridden."""
    family = next(
        n for n in g.lawful_nodes() if n.kind is kind and n.disposition is GraphNodeDisposition.NEW
    )
    return {**g.explicit(family), **overrides}


# --------------------------------------------------------------------------- identity


def test_the_canonical_schema_hash_is_pinned_and_moved() -> None:
    assert schema_sha256(CANONICAL) == GRAPH_ANSWER_SCHEMA_SHA256
    assert GRAPH_ANSWER_SCHEMA_SHA256 != HISTORICAL_CANONICAL_SHA256


def test_the_schema_hash_is_canonical_json() -> None:
    expected = hashlib.sha256(
        json.dumps(CANONICAL, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert schema_sha256(CANONICAL) == expected
    assert schema_sha256(dict(reversed(list(CANONICAL.items())))) == expected


def test_generation_is_deterministic() -> None:
    assert IntentGraphDraftPayload.model_json_schema() == CANONICAL
    assert schema_sha256(IntentGraphDraftPayload.model_json_schema()) == schema_sha256(CANONICAL)


def test_python_validation_behaviour_is_unchanged() -> None:
    corpus = g.adversarial_payloads() + [g.explicit(p) for p in g.lawful_payloads()]
    keys = sorted(json.dumps(x, sort_keys=True) for x in corpus)
    verdicts = "".join("1" if g.pydantic_accepts(json.loads(k)) else "0" for k in keys)
    digest = hashlib.sha256(("\n".join(keys) + "\n" + verdicts).encode()).hexdigest()
    assert digest == PYDANTIC_BEHAVIOUR_FINGERPRINT


def test_python_construction_ergonomics_are_unchanged() -> None:
    assert LocalNodeRef(local_id="a").namespace == "local"
    goal = GoalNodeProposal(
        local_id=LocalNodeRef(local_id="a"), proposal_rationale="r", statement="s"
    )
    assert goal.kind is SemanticKind.GOAL
    assert goal.disposition is GraphNodeDisposition.NEW
    assert goal.replaces is None


# --------------------------------------------------------------------------- A. discriminators


def _effective_required(root: dict[str, Any], branch: dict[str, Any]) -> set[str]:
    required = set(branch.get("required", []))
    if "$ref" in branch:
        target = root["$defs"][branch["$ref"].split("/")[-1]]
        required |= set(target.get("required", []))
    return required


def test_every_graph_ref_branch_requires_namespace_at_the_union_boundary() -> None:
    branches = g.union_branches(CANONICAL, "GraphRef")
    assert len(branches) == 3
    assert all("namespace" in _effective_required(CANONICAL, b) for b in branches)


def test_a_graph_ref_without_namespace_is_refused_by_schema_and_pydantic() -> None:
    target = {"local_id": "a"}
    rel = {"source": {"local_id": "n1"}, "relation_type": "SERVES", "target": target}
    candidate = payload(relations=[rel])
    assert not canonical_valid(candidate)
    assert not g.pydantic_accepts(candidate)


def test_standalone_refs_keep_their_default_namespace_in_schema_and_pydantic() -> None:
    """Outside a discriminated union Pydantic defaults the tag; the schema must allow omission."""
    rel = {
        "source": {"local_id": "n1"},
        "relation_type": "SERVES",
        "target": {"namespace": "existing", "object_id": "X"},
    }
    candidate = payload(relations=[rel], unchanged_object_refs=[{"object_id": "Y"}])
    assert canonical_valid(candidate)
    assert g.pydantic_accepts(candidate)


def test_a_node_without_kind_is_refused_by_schema_and_pydantic() -> None:
    kindless = {k: v for k, v in node(SemanticKind.GOAL).items() if k != "kind"}
    minimal = {"local_id": {"local_id": "n1"}, "proposal_rationale": "r", "statement": "s"}
    # Matches exactly one family, so oneOf alone never caught it: only a required tag does.
    intent_shaped = {"local_id": {"local_id": "n1"}, "proposal_rationale": "r", "mission": "m"}
    for candidate in (kindless, minimal, intent_shaped):
        assert not canonical_valid(payload(nodes=[candidate]))
        assert not g.pydantic_accepts(payload(nodes=[candidate]))


# --------------------------------------------------------------------------- B. relations


def test_relation_type_is_exactly_the_proposable_set() -> None:
    rel_schema = CANONICAL["$defs"]["GraphRelationProposal"]["properties"]["relation_type"]
    assert rel_schema["enum"] == PROPOSABLE
    assert len(RelationType) == 13, "the general domain enum is not narrowed"


@pytest.mark.parametrize("relation", [r.value for r in RelationType])
def test_every_relation_type_agrees_with_pydantic(relation: str) -> None:
    rel = {
        "source": {"namespace": "local", "local_id": "n1"},
        "relation_type": relation,
        "target": {"namespace": "existing", "object_id": "X"},
    }
    candidate = payload(relations=[rel])
    assert canonical_valid(candidate) is (relation in PROPOSABLE)
    assert g.pydantic_accepts(candidate) is (relation in PROPOSABLE)


# --------------------------------------------------------------------------- C. INTENT, ASSUMPTION

STALE_TARGET = {"namespace": "existing", "object_id": "OLD"}


@pytest.mark.parametrize("kind", [SemanticKind.INTENT, SemanticKind.ASSUMPTION])
def test_irreplaceable_kinds_admit_only_new_without_a_target(kind: SemanticKind) -> None:
    lawful = node(kind)
    omitted = {k: v for k, v in lawful.items() if k not in ("disposition", "replaces")}
    for candidate in (lawful, omitted):
        assert canonical_valid(payload(nodes=[candidate]))
        assert g.pydantic_accepts(payload(nodes=[candidate]))
    for bad in (
        {**lawful, "disposition": "REPLACES_STALE", "replaces": STALE_TARGET},
        {**lawful, "disposition": "REPLACES_STALE"},
        {**lawful, "replaces": STALE_TARGET},
        {**omitted, "replaces": STALE_TARGET},
    ):
        assert not canonical_valid(payload(nodes=[bad]))
        assert not g.pydantic_accepts(payload(nodes=[bad]))


@pytest.mark.parametrize("kind", [SemanticKind.INTENT, SemanticKind.ASSUMPTION])
def test_irreplaceable_kinds_are_one_variant(kind: SemanticKind) -> None:
    definition = CANONICAL["$defs"][NODE_DEFS[kind]]
    assert "oneOf" not in definition and "anyOf" not in definition
    props = definition["properties"]
    assert props["disposition"]["const"] == "NEW"
    assert props["replaces"]["type"] == "null"
    assert "kind" in definition["required"]
    assert "disposition" not in definition["required"]
    assert "replaces" not in definition["required"]


# --------------------------------------------------------------------------- D. replaceable kinds


@pytest.mark.parametrize("kind", g.REPLACEABLE_KINDS)
def test_each_replaceable_kind_is_exactly_two_variants(kind: SemanticKind) -> None:
    definition = CANONICAL["$defs"][NODE_DEFS[kind]]
    new, stale = definition["oneOf"]
    assert new["properties"]["disposition"]["const"] == "NEW"
    assert new["properties"]["replaces"]["type"] == "null"
    assert {"disposition", "replaces"}.isdisjoint(new["required"])
    assert stale["properties"]["disposition"]["const"] == "REPLACES_STALE"
    assert stale["properties"]["replaces"] == {"$ref": "#/$defs/ExistingObjectRef"}
    assert {"disposition", "replaces"} <= set(stale["required"])
    for variant in (new, stale):
        assert "kind" in variant["required"]
        assert variant["properties"]["kind"]["const"] == kind.value
        assert variant["additionalProperties"] is False


@pytest.mark.parametrize("kind", g.REPLACEABLE_KINDS)
def test_each_replaceable_kind_agrees_with_pydantic_on_every_state(kind: SemanticKind) -> None:
    lawful_new = node(kind)
    omitted_new = {k: v for k, v in lawful_new.items() if k not in ("disposition", "replaces")}
    lawful_stale = {**lawful_new, "disposition": "REPLACES_STALE", "replaces": STALE_TARGET}
    for candidate in (lawful_new, omitted_new, lawful_stale):
        assert canonical_valid(payload(nodes=[candidate]))
        assert g.pydantic_accepts(payload(nodes=[candidate]))
    for bad in (
        {**lawful_new, "replaces": STALE_TARGET},
        {**omitted_new, "replaces": STALE_TARGET},
        {**lawful_stale, "replaces": None},
        {k: v for k, v in lawful_stale.items() if k != "replaces"},
        {**lawful_stale, "replaces": {"namespace": "local", "local_id": "a"}},
        {**lawful_stale, "replaces": {"namespace": "basis", "claim_id": "C"}},
        {**lawful_stale, "disposition": "bogus"},
    ):
        assert not canonical_valid(payload(nodes=[bad]))
        assert not g.pydantic_accepts(payload(nodes=[bad]))


def test_the_node_union_has_sixteen_leaf_variants() -> None:
    leaves = 0
    for branch in g.union_branches(CANONICAL, "GraphNodeProposal"):
        definition = CANONICAL["$defs"][branch["$ref"].split("/")[-1]]
        leaves += len(definition.get("oneOf", [definition]))
    assert leaves == 16


# --------------------------------------------------------------------------- uniqueness


def _ref_positions(instance: Any) -> list[Any]:
    found: list[Any] = []
    if not isinstance(instance, dict):
        return found
    for rel in instance.get("relations", []) if isinstance(instance.get("relations"), list) else []:
        if isinstance(rel, dict) and "target" in rel:
            found.append(rel["target"])
    for gap in instance.get("gaps", []) if isinstance(instance.get("gaps"), list) else []:
        if isinstance(gap, dict) and isinstance(gap.get("anchors"), list):
            found += gap["anchors"]
    return found


def _node_positions(instance: Any) -> list[Any]:
    if isinstance(instance, dict) and isinstance(instance.get("nodes"), list):
        return list(instance["nodes"])
    return []


_VARIANTS: dict[tuple[int, str], tuple[dict[str, Any], list[dict[str, Any]]]] = {}


def _kind_variants(root: dict[str, Any], def_name: str) -> list[dict[str, Any]]:
    """Each lawful state of one node family, made standalone once (identity-cached)."""
    cached = _VARIANTS.get((id(root), def_name))
    if cached is None or cached[0] is not root:
        definition = root["$defs"][def_name]
        states = definition.get("oneOf", definition.get("anyOf", [definition]))
        cached = _VARIANTS[(id(root), def_name)] = (root, [g.with_defs(root, v) for v in states])
    return cached[1]


def assert_unique(root: dict[str, Any], instances: list[Any]) -> tuple[int, int]:
    """No instance matches two union branches, at either union level. Returns match counts."""
    refs = nodes = 0
    for instance in instances:
        for ref in _ref_positions(instance):
            matched = g.matching_branches(root, "GraphRef", ref)
            assert len(matched) <= 1, f"GraphRef overlap on {ref!r}: branches {matched}"
            refs += len(matched)
        for candidate in _node_positions(instance):
            matched = g.matching_branches(root, "GraphNodeProposal", candidate)
            assert len(matched) <= 1, f"node overlap on {candidate!r}: branches {matched}"
            nodes += len(matched)
            for branch in g.union_branches(root, "GraphNodeProposal"):
                variants = _kind_variants(root, branch["$ref"].split("/")[-1])
                hits = [v for v in variants if g.is_valid(v, candidate)]
                assert len(hits) <= 1, f"variant overlap on {candidate!r}"
    return refs, nodes


def test_every_lawful_union_member_matches_exactly_one_branch() -> None:
    for ref in g.REFS:
        assert len(g.matching_branches(CANONICAL, "GraphRef", g.explicit(ref))) == 1
    for lawful in g.lawful_nodes():
        assert len(g.matching_branches(CANONICAL, "GraphNodeProposal", g.explicit(lawful))) == 1


def test_no_adversarial_member_matches_two_branches() -> None:
    refs, nodes = assert_unique(CANONICAL, g.adversarial_payloads())
    assert refs > 0 and nodes > 0, "the corpus reached no union member; the proof is vacuous"


# --------------------------------------------------------------------------- agreement


def test_the_canonical_schema_never_accepts_what_pydantic_rejects() -> None:
    corpus = g.adversarial_payloads()
    counterexamples = [x for x in corpus if canonical_valid(x) and not g.pydantic_accepts(x)]
    accepted = sum(1 for x in corpus if canonical_valid(x))
    assert counterexamples == []
    assert accepted > 0 and accepted < len(corpus)


@pytest.mark.parametrize("value", g.lawful_payloads(), ids=lambda _: "")
def test_every_lawful_value_is_canonical_explicitly_and_minimally(value: BaseModel) -> None:
    for form in (g.explicit(value), g.minimal(value)):
        assert canonical_valid(form), form
        assert IntentGraphDraftPayload.model_validate_json(json.dumps(form)) == value


# --------------------------------------------------------------------------- inventory

VALIDATOR_INVENTORY = {
    ("IntentNodeProposal", "validate_disposition"): "INTENT: disposition const NEW, replaces null",
    ("AssumptionNodeProposal", "validate_disposition"): "ASSUMPTION: disposition const NEW, "
    "replaces null",
    **{
        (name, "validate_disposition"): "two variants: NEW (replaces null) | REPLACES_STALE "
        "(replaces ExistingObjectRef, both required)"
        for name in (
            "GoalNodeProposal",
            "OutcomeNodeProposal",
            "RequirementNodeProposal",
            "ConstraintNodeProposal",
            "NonGoalNodeProposal",
            "PreferenceNodeProposal",
            "DecisionNodeProposal",
        )
    },
    ("GraphRelationProposal", "only_proposable_relations"): "relation_type enum: the 4 "
    "proposable relations",
}
"""Every Pydantic validator reachable from ``IntentGraphDraftPayload``, and how the canonical
schema expresses it. Adding a validator fails this test until its schema form is decided."""


def _reachable_models(root: type[BaseModel]) -> set[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    pending: list[Any] = [root]
    while pending:
        tp = pending.pop()
        if isinstance(tp, type) and issubclass(tp, BaseModel):
            if tp in seen:
                continue
            seen.add(tp)
            pending += [f.annotation for f in tp.model_fields.values()]
            continue
        pending += list(getattr(tp, "__args__", ()))
        value = getattr(tp, "__value__", None)
        if value is not None:
            pending.append(value)
        origin = getattr(tp, "__origin__", None)
        if origin is not None:
            pending.append(origin)
    return seen


def test_the_validator_inventory_is_complete() -> None:
    found: set[tuple[str, str]] = set()
    functional: list[str] = []
    for model in _reachable_models(IntentGraphDraftPayload):
        decorators = model.__pydantic_decorators__
        for group in (
            decorators.field_validators,
            decorators.model_validators,
            decorators.validators,
            decorators.root_validators,
        ):
            found |= {(model.__name__, name) for name in group}
        for field_name, info in model.model_fields.items():
            for meta in info.metadata:
                if type(meta).__name__ in (
                    "AfterValidator",
                    "BeforeValidator",
                    "PlainValidator",
                    "WrapValidator",
                ):
                    functional.append(f"{model.__name__}.{field_name}")
    assert functional == [], f"functional validators need a schema decision: {functional}"
    assert found == set(VALIDATOR_INVENTORY)


def test_the_only_pattern_is_one_the_test_validator_translates_exactly() -> None:
    assert g.patterns_in(CANONICAL) == {LOCAL_ID_PATTERN}
    assert g.ecma_pattern_to_python(LOCAL_ID_PATTERN) == LOCAL_ID_PATTERN[:-1] + r"\Z"


def test_a_trailing_newline_is_refused_by_ecma_semantics_and_by_pydantic() -> None:
    """Python ``re`` would accept it; that is a property of the local engine, not the schema."""
    candidate = payload(
        unchanged_object_refs=[],
        nodes=[node(SemanticKind.GOAL, local_id={"namespace": "local", "local_id": "a\n"})],
    )
    assert not canonical_valid(candidate)
    assert not g.pydantic_accepts(candidate)
    assert Draft202012Validator(CANONICAL).is_valid(candidate), (
        "the stock Python-regex validator is expected to disagree; if it stops disagreeing, "
        "the ECMA translation is no longer load-bearing and this note should be revisited"
    )


def test_pydantic_union_dispatch_still_requires_the_tag() -> None:
    with pytest.raises(PydanticValidationError, match="union_tag_not_found|Unable to extract tag"):
        TypeAdapter(GraphNodeProposal).validate_python(
            {"local_id": {"local_id": "n1"}, "proposal_rationale": "r", "statement": "s"}
        )
    assert ExistingObjectRef.model_validate({"object_id": "X"}).namespace == "existing"
