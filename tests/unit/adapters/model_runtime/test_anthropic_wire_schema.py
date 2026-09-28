"""The Anthropic wire schema: exactly the canonical contract minus what Anthropic cannot express.

Anthropic structured outputs cannot enforce ``pattern``, string lengths or numeric ranges. The
wire is therefore *broader* than the canonical schema, but only there, and this file proves it:

A. **Exact relaxation.** Over the adversarial corpus, the wire admits exactly what the canonical
   schema admits once ``RELAXED_CONSTRAINTS`` are removed. Nothing else is loosened.
B. **Bounded unsoundness.** Every wire-admitted instance Pydantic rejects violates a relaxed
   constraint (the canonical schema, which agrees with Pydantic, rejects it too). There is no
   other way for the wire to admit what Foundry refuses, and Pydantic still refuses it.
C. **Representability.** Every lawful value's explicit form is wire-valid and decodes to itself.
D. **Uniqueness.** A wire-valid union member matches exactly one branch.
E. **Fail closed** on constructs without a proven Anthropic form.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

import tests.unit._graph_answer_schema as g
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    IntentGraphDraftPayload,
)
from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
from foundry.adapters.model_runtime.anthropic_wire_schema import (
    ANTHROPIC_WIRE_SCHEMA_COMPILER,
    RELAXED_CONSTRAINTS,
    AnthropicWireSchemaError,
    compile_anthropic_wire_schema,
)
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.model_runtime.xai import XAIModelProvider
from tests.certification._schema_identity import schema_sha256

CANONICAL: dict[str, Any] = IntentGraphDraftPayload.model_json_schema()
WIRE: dict[str, Any] = compile_anthropic_wire_schema(CANONICAL)

ANTHROPIC_GRAPH_WIRE_SCHEMA_SHA256 = (
    "ca63b550c1d030be7ca403e1a51aec6ad7878b448266fc3981d3e7158c92222e"
)


def _strip(node: Any, keywords: set[str]) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v, keywords) for k, v in node.items() if k not in keywords}
    if isinstance(node, list):
        return [_strip(v, keywords) for v in node]
    return node


RELAXED_CANONICAL: dict[str, Any] = _strip(CANONICAL, set(RELAXED_CONSTRAINTS))
"""The canonical schema with exactly the relaxed constraints removed: the reference for A."""


def _keys(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        found |= set(node)
        for value in node.values():
            found |= _keys(value)
    elif isinstance(node, list):
        for value in node:
            found |= _keys(value)
    return found


# --------------------------------------------------------------------------- identity


def test_the_wire_hash_is_pinned_and_distinct_from_every_other_provider() -> None:
    assert schema_sha256(WIRE) == ANTHROPIC_GRAPH_WIRE_SCHEMA_SHA256
    others = {
        schema_sha256(OpenAIModelProvider.wire_schema(IntentGraphDraftPayload)),
        schema_sha256(XAIModelProvider.wire_schema(IntentGraphDraftPayload)),
        GRAPH_ANSWER_SCHEMA_SHA256,
    }
    assert ANTHROPIC_GRAPH_WIRE_SCHEMA_SHA256 not in others
    assert ANTHROPIC_WIRE_SCHEMA_COMPILER == "foundry.anthropic-structured-outputs.v1"
    assert AnthropicModelProvider.WIRE_SCHEMA_COMPILER == ANTHROPIC_WIRE_SCHEMA_COMPILER
    assert AnthropicModelProvider.wire_schema(IntentGraphDraftPayload) == WIRE


def test_compilation_is_deterministic_and_pure() -> None:
    before = copy.deepcopy(CANONICAL)
    assert compile_anthropic_wire_schema(CANONICAL) == compile_anthropic_wire_schema(CANONICAL)
    assert before == CANONICAL


def test_the_relaxed_set_is_exactly_what_anthropic_documents_as_unsupported() -> None:
    assert set(RELAXED_CONSTRAINTS) == {
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }


def test_the_wire_has_no_unsupported_construct() -> None:
    present = _keys(WIRE)
    assert not present & {"oneOf", "discriminator", *RELAXED_CONSTRAINTS}
    assert "anyOf" in present


def test_the_graph_relaxes_only_the_three_canonical_constraints_it_uses() -> None:
    """What the graph loses: the local_id pattern, non-empty strings, the confidence range."""
    used = _keys(CANONICAL) & set(RELAXED_CONSTRAINTS)
    assert used == {"pattern", "minLength", "minimum", "maximum"}


# --------------------------------------------------------------------------- A, B soundness


def test_a_the_wire_admits_exactly_the_relaxed_canonical_language() -> None:
    corpus = g.adversarial_payloads() + [g.explicit(p) for p in g.lawful_payloads()]
    mismatches = [x for x in corpus if g.is_valid(WIRE, x) != g.is_valid(RELAXED_CANONICAL, x)]
    assert mismatches == []


def test_b_every_wire_admitted_pydantic_rejection_violates_only_a_relaxed_constraint() -> None:
    corpus = g.adversarial_payloads()
    loose = [x for x in corpus if g.is_valid(WIRE, x) and not g.pydantic_accepts(x)]
    assert loose, "the corpus should exercise the relaxation, or B is vacuous"
    for x in loose:
        assert not g.is_valid(CANONICAL, x), x
        assert g.is_valid(RELAXED_CANONICAL, x), x
    others = [x for x in corpus if g.is_valid(WIRE, x) and g.is_valid(CANONICAL, x)]
    assert all(g.pydantic_accepts(x) for x in others)


@pytest.mark.parametrize(
    ("field", "value"),
    [("statement", ""), ("proposal_rationale", ""), ("confidence", 1.5)],
)
def test_b_examples_are_wire_valid_yet_refused_by_pydantic(field: str, value: Any) -> None:
    lawful = g.explicit(IntentGraphDraftPayload(nodes=(g.lawful_nodes()[1],)))
    lawful["nodes"][0][field] = value
    assert g.is_valid(WIRE, lawful)
    assert not g.pydantic_accepts(lawful)


def test_b_a_pattern_breaking_local_id_is_wire_valid_yet_refused() -> None:
    lawful = g.explicit(IntentGraphDraftPayload(nodes=(g.lawful_nodes()[1],)))
    lawful["nodes"][0]["local_id"]["local_id"] = "Not A Local Id"
    assert g.is_valid(WIRE, lawful)
    assert not g.pydantic_accepts(lawful)


# --------------------------------------------------------------------------- C, D


@pytest.mark.parametrize("value", g.lawful_payloads(), ids=lambda _: "")
def test_c_every_lawful_value_is_wire_valid_explicitly_and_minimally(value: Any) -> None:
    for form in (g.explicit(value), g.minimal(value)):
        assert g.is_valid(WIRE, form), form
        assert IntentGraphDraftPayload.model_validate_json(json.dumps(form)) == value


def test_d_no_member_matches_two_wire_branches() -> None:
    for ref in g.REFS:
        assert len(g.matching_branches(WIRE, "GraphRef", g.explicit(ref))) == 1
    for lawful in g.lawful_nodes():
        assert len(g.matching_branches(WIRE, "GraphNodeProposal", g.explicit(lawful))) == 1
    from tests.unit.test_ie3_graph_answer_schema import assert_unique

    refs, nodes = assert_unique(WIRE, g.adversarial_payloads())
    assert refs > 0 and nodes > 0


def test_d_a_ref_without_its_tag_is_still_refused_at_the_union_boundary() -> None:
    rel = {"source": {"local_id": "n1"}, "relation_type": "SERVES", "target": {"local_id": "a"}}
    payload = {"relations": [rel]}
    assert not g.is_valid(WIRE, payload)
    assert not g.pydantic_accepts(payload)


# --------------------------------------------------------------------------- E fail closed


def _schema(value: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": {"value": value}, "additionalProperties": False}


@pytest.mark.parametrize(
    "construct",
    [
        {"not": {"type": "string"}},
        {"if": {"type": "string"}, "then": {"type": "string"}},
        {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        {"type": "array", "items": {"type": "string"}, "minItems": 2},
        {"type": "string", "format": "credit-card"},
        {"enum": [{"a": 1}]},
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": True},
        {"oneOf": [{"type": "string"}, {"type": "integer"}]},
        {"type": "object", "patternProperties": {"^a": {"type": "string"}}},
    ],
)
def test_e_an_unproven_construct_is_refused(construct: dict[str, Any]) -> None:
    with pytest.raises(AnthropicWireSchemaError):
        compile_anthropic_wire_schema(_schema(construct))


def test_e_a_recursive_schema_is_refused() -> None:
    recursive = {
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"child": {"anyOf": [{"$ref": "#/$defs/Node"}, {"type": "null"}]}},
                "additionalProperties": False,
            }
        },
        "$ref": "#/$defs/Node",
    }
    with pytest.raises(AnthropicWireSchemaError, match="recursive"):
        compile_anthropic_wire_schema(recursive)


def test_e_a_conflicting_ref_sibling_is_refused() -> None:
    schema = {
        "$defs": {"A": {"type": "object", "properties": {"x": {"type": "string"}}}},
        "type": "object",
        "properties": {"value": {"$ref": "#/$defs/A", "type": "string"}},
        "additionalProperties": False,
    }
    with pytest.raises(AnthropicWireSchemaError, match="conflicts"):
        compile_anthropic_wire_schema(schema)


def test_property_names_are_data_not_keywords() -> None:
    wire = compile_anthropic_wire_schema(
        _schema({"type": "object", "properties": {"pattern": {"type": "string"}}})
    )
    assert "pattern" in wire["properties"]["value"]["properties"]
