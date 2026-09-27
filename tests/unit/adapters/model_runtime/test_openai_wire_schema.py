"""The OpenAI wire schema is a sound, faithful representation of the canonical answer contract.

Not raw-language equality: OpenAI strict mode requires every property to be present, so the wire
is syntactically stricter than the canonical schema. What is proven instead:

A. Soundness: every instance the wire admits, Pydantic accepts (zero counterexamples).
B. Representability: every lawful value has an explicit wire form the wire admits, and it
   decodes back to the same value.
C. Uniqueness: a wire-valid union member matches exactly one branch, so ``anyOf`` introduces
   no ambiguity that ``oneOf`` excluded.
D. Default materialization: omitting a defaulted field and sending its default explicitly give
   the same Pydantic value, so requiring presence on the wire creates no semantic distinction.
E. Invalid shapes stay refused, and the compiler refuses what it cannot prove.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from openai.lib._parsing._responses import type_to_text_format_param
from openai.lib._pydantic import _ensure_strict_json_schema, to_strict_json_schema
from pydantic import BaseModel, ConfigDict, Field

import tests.unit._graph_answer_schema as g
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    IntentGraphDraftPayload,
)
from foundry.adapters.intent_synthesis.model_runtime import IntentSynthesisDraftPayload
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.model_runtime.openai_wire_schema import (
    OPENAI_WIRE_SCHEMA_COMPILER,
    OpenAIWireSchemaError,
    compile_openai_wire_schema,
    openai_text_format,
)
from tests.certification._schema_identity import schema_sha256

CANONICAL: dict[str, Any] = IntentGraphDraftPayload.model_json_schema()
WIRE: dict[str, Any] = compile_openai_wire_schema(CANONICAL)

OPENAI_GRAPH_WIRE_SCHEMA_SHA256 = "7b8257300ee6c18fa0d772ffd53cf354bb23a773d25e0dabff91076209249afa"
"""Pinned literal, never computed at import: a digest derived from the output agrees with any
output. A change to the canonical schema or to the compiler fails here until reviewed."""


def wire_valid(instance: Any) -> bool:
    return g.is_valid(WIRE, instance)


# --------------------------------------------------------------------------- identity


def test_the_wire_schema_hash_is_pinned_and_distinct_from_the_canonical() -> None:
    assert schema_sha256(WIRE) == OPENAI_GRAPH_WIRE_SCHEMA_SHA256
    assert OPENAI_GRAPH_WIRE_SCHEMA_SHA256 != GRAPH_ANSWER_SCHEMA_SHA256


def test_the_compiler_identity_is_named() -> None:
    assert OPENAI_WIRE_SCHEMA_COMPILER == "foundry.openai-structured-outputs.v1"
    assert OpenAIModelProvider.WIRE_SCHEMA_COMPILER == OPENAI_WIRE_SCHEMA_COMPILER


def test_compilation_is_deterministic_and_pure() -> None:
    before = copy.deepcopy(CANONICAL)
    first = compile_openai_wire_schema(CANONICAL)
    second = compile_openai_wire_schema(CANONICAL)
    assert before == CANONICAL, "the canonical schema must never be mutated"
    assert first == second == WIRE
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert schema_sha256(first) == schema_sha256(second)


def test_the_provider_publishes_exactly_what_it_sends() -> None:
    assert OpenAIModelProvider.wire_schema(IntentGraphDraftPayload) == WIRE
    assert openai_text_format(IntentGraphDraftPayload) == {
        "type": "json_schema",
        "strict": True,
        "name": "IntentGraphDraftPayload",
        "schema": WIRE,
    }


# --------------------------------------------------------------------------- transformation


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


def test_no_oneof_survives_and_every_translated_union_is_anyof() -> None:
    assert "oneOf" not in _keys(WIRE)
    defs = WIRE["$defs"]
    assert len(defs["GraphRef"]["anyOf"]) == 3
    assert len(defs["GraphNodeProposal"]["anyOf"]) == 9
    for name in ("Goal", "Outcome", "Requirement", "Constraint", "NonGoal", "Preference"):
        assert len(defs[f"{name}NodeProposal"]["anyOf"]) == 2
    assert len(defs["DecisionNodeProposal"]["anyOf"]) == 2


def test_only_the_unions_and_the_strict_form_differ_from_the_canonical() -> None:
    """Undo oneOf->anyOf and the result is exactly the SDK's own strict form of the canonical."""
    translated = copy.deepcopy(CANONICAL)
    for definition in translated["$defs"].values():
        if "oneOf" in definition:
            definition["anyOf"] = definition.pop("oneOf")
    sdk_strict = _ensure_strict_json_schema(translated, path=(), root=translated)
    assert sdk_strict == WIRE


def test_discriminator_metadata_is_carried_unchanged() -> None:
    """Not guessed away: whether OpenAI accepts it is the compatibility probe's question."""
    for name in ("GraphRef", "GraphNodeProposal"):
        assert WIRE["$defs"][name]["discriminator"] == CANONICAL["$defs"][name]["discriminator"]


def test_every_wire_object_requires_every_property_and_forbids_extras() -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                assert node["required"] == list(node["properties"])
                assert node["additionalProperties"] is False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(WIRE)


# --------------------------------------------------------------------------- A. soundness


def test_the_wire_never_admits_what_pydantic_rejects() -> None:
    corpus = g.adversarial_payloads()
    counterexamples = [x for x in corpus if wire_valid(x) and not g.pydantic_accepts(x)]
    admitted = sum(1 for x in corpus if wire_valid(x))
    assert counterexamples == []
    assert 0 < admitted < len(corpus), "a vacuous corpus proves nothing"


def test_the_wire_never_admits_what_the_canonical_schema_rejects() -> None:
    corpus = g.adversarial_payloads()
    assert [x for x in corpus if wire_valid(x) and not g.is_valid(CANONICAL, x)] == []


# --------------------------------------------------------------------------- B. round trip


@pytest.mark.parametrize("value", g.lawful_payloads(), ids=lambda _: "")
def test_every_lawful_value_has_a_wire_form_that_decodes_to_it(value: BaseModel) -> None:
    form = g.explicit(value)
    assert wire_valid(form), form
    assert IntentGraphDraftPayload.model_validate_json(json.dumps(form)) == value


def test_the_minimal_canonical_form_is_not_a_wire_form_but_means_the_same() -> None:
    """Omission is a canonical spelling only; the wire spells the same value explicitly."""
    checked = 0
    for value in g.lawful_payloads():
        minimal, explicit = g.minimal(value), g.explicit(value)
        if minimal == explicit:
            continue
        checked += 1
        assert not wire_valid(minimal)
        assert IntentGraphDraftPayload.model_validate_json(json.dumps(minimal)) == (
            IntentGraphDraftPayload.model_validate_json(json.dumps(explicit))
        )
    assert checked > 0


# --------------------------------------------------------------------------- C. uniqueness


def test_every_lawful_union_member_matches_exactly_one_wire_branch() -> None:
    for ref in g.REFS:
        assert len(g.matching_branches(WIRE, "GraphRef", g.explicit(ref))) == 1
    for lawful in g.lawful_nodes():
        assert len(g.matching_branches(WIRE, "GraphNodeProposal", g.explicit(lawful))) == 1


def test_no_adversarial_member_matches_two_wire_branches() -> None:
    from tests.unit.test_ie3_graph_answer_schema import assert_unique

    refs, nodes = assert_unique(WIRE, g.adversarial_payloads())
    assert refs > 0 and nodes > 0


# --------------------------------------------------------------------------- D. defaults


@pytest.mark.parametrize("value", g.lawful_payloads()[:60], ids=lambda _: "")
def test_omitting_any_defaulted_field_means_the_same_as_sending_its_default(
    value: IntentGraphDraftPayload,
) -> None:
    explicit = g.explicit(value)
    for container, key in g.defaulted_fields(value, explicit):
        omitted = copy.deepcopy(explicit)
        target: Any = omitted
        for step in container:
            target = target[step]
        del target[key]
        assert IntentGraphDraftPayload.model_validate_json(json.dumps(omitted)) == value
        assert not wire_valid(omitted), f"the wire must require {key!r} at {container}"


@pytest.mark.parametrize(
    ("field", "wrong"),
    [("disposition", "REPLACES_STALE"), ("replaces", {"namespace": "existing", "object_id": "X"})],
)
def test_a_malformed_materialized_default_is_refused(field: str, wrong: Any) -> None:
    lawful = g.explicit(IntentGraphDraftPayload(nodes=(g.lawful_nodes()[0],)))  # an INTENT
    lawful["nodes"][0][field] = wrong
    assert not wire_valid(lawful)
    assert not g.pydantic_accepts(lawful)


# --------------------------------------------------------------------------- E. fail closed


class _Loose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str = "a"


def _schema_with_union(branches: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"value": {"oneOf": branches}},
        "required": ["value"],
        "additionalProperties": False,
    }


def _obj(tag: Any, *, required: bool = True, extra: str = "x") -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"tag": tag, extra: {"type": "string"}},
        "required": ["tag", extra] if required else [extra],
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    ("label", "branches"),
    [
        (
            "tag optional on both sides",
            [_obj({"const": "a"}, required=False), _obj({"const": "b"}, required=False)],
        ),
        ("same tag", [_obj({"const": "a"}), _obj({"const": "a"})]),
        ("overlapping enums", [_obj({"enum": ["a", "b"]}), _obj({"enum": ["b", "c"]})]),
        ("no finite tag", [_obj({"type": "string"}), _obj({"type": "string"})]),
        ("no properties", [{"type": "string"}, {"type": "integer"}]),
    ],
)
def test_an_unprovable_oneof_is_refused_not_rewritten(label: str, branches: list[Any]) -> None:
    with pytest.raises(OpenAIWireSchemaError, match="not provably exclusive|unprovable"):
        compile_openai_wire_schema(_schema_with_union(branches))


def test_a_provable_oneof_is_translated() -> None:
    wire = compile_openai_wire_schema(
        _schema_with_union([_obj({"const": "a"}, required=False), _obj({"const": "b"})])
    )
    assert "anyOf" in wire["properties"]["value"] and "oneOf" not in _keys(wire)


@pytest.mark.parametrize(
    "construct",
    [
        {"not": {"type": "string"}},
        {"if": {"type": "string"}, "then": {"minLength": 1}},
        {"allOf": [{"type": "string"}, {"minLength": 1}]},
        {"type": "object", "patternProperties": {"^a": {"type": "string"}}},
        {"type": "array", "prefixItems": [{"type": "string"}]},
        {"type": "array", "contains": {"type": "string"}},
        {"type": "object", "propertyNames": {"maxLength": 3}},
        {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": True},
    ],
)
def test_an_unproven_construct_is_refused(construct: dict[str, Any]) -> None:
    schema = {
        "type": "object",
        "properties": {"value": construct},
        "additionalProperties": False,
    }
    with pytest.raises(OpenAIWireSchemaError):
        compile_openai_wire_schema(schema)


def test_property_names_are_data_not_keywords() -> None:
    schema = {
        "type": "object",
        "properties": {"oneOf": {"type": "string"}, "not": {"type": "integer"}},
        "additionalProperties": False,
    }
    wire = compile_openai_wire_schema(schema)
    assert list(wire["properties"]) == ["oneOf", "not"]


def test_a_refused_compilation_is_a_request_error_before_any_network() -> None:
    from foundry.model_runtime.errors import ModelRequestError

    assert issubclass(OpenAIWireSchemaError, ModelRequestError)


# --------------------------------------------------------------------------- existing callers


class Verdict(BaseModel):
    statement: str = Field(min_length=1)
    score: int


@pytest.mark.parametrize("output_type", [IntentSynthesisDraftPayload, Verdict, _Loose])
def test_a_schema_without_oneof_is_sent_exactly_as_the_sdk_sent_it(
    output_type: type[BaseModel],
) -> None:
    """Slice-1 (Astra's certified INTENT_SYNTHESIS contract) and every other existing caller."""
    assert "oneOf" not in _keys(output_type.model_json_schema())
    assert openai_text_format(output_type) == type_to_text_format_param(output_type)
    assert compile_openai_wire_schema(output_type.model_json_schema()) == to_strict_json_schema(
        output_type
    )


@pytest.mark.parametrize(
    ("label", "schema"),
    [
        (
            "a property not required",
            {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            },
        ),
        (
            "extras admitted",
            {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": True,
            },
        ),
        ("required without properties", {"anyOf": [{"type": "string"}], "required": ["a"]}),
        ("$ref with siblings", {"$ref": "#/$defs/A", "description": "x"}),
    ],
)
def test_the_audit_refuses_a_wire_the_strict_step_should_never_produce(
    label: str, schema: dict[str, Any]
) -> None:
    """The audit is an independent layer: it holds even if the strict step ever regresses."""
    from foundry.adapters.model_runtime.openai_wire_schema import _audit

    with pytest.raises(OpenAIWireSchemaError):
        _audit(schema, path=())
