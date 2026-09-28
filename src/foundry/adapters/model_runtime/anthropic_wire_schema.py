"""Anthropic provider wire schema: a deterministic representation of a canonical answer schema.

The canonical domain contract is the caller's Pydantic output type and the provider-neutral JSON
Schema it generates. The provider wire contract is what is transmitted to Anthropic structured
outputs (``output_config.format = {"type": "json_schema", "schema": ...}``). Pydantic stays the
source of truth and validates every returned answer again.

Anthropic's structured-output grammar supports a documented subset of JSON Schema: basic types,
``enum``, ``const``, ``anyOf``, ``allOf`` (not over ``$ref``), local ``$ref``/``$defs``,
``default``, ``description``, ``required`` and ``additionalProperties: false``. It does **not**
support ``oneOf``, ``discriminator``, ``pattern``, string length or numeric range constraints,
recursive schemas, or ``minItems`` above 1. The compiler therefore does exactly four things, all
mechanical, and refuses everything else:

1. **Proven ``oneOf`` -> ``anyOf``** (``wire_schema.translate_exclusive_unions``, the same proof
   the OpenAI compiler uses). Exact: no instance can match two branches.
2. **Inline a ``$ref`` that carries sibling keywords** (the union-boundary ``required: [tag]``).
   The referenced object is copied and the sibling constraints merged into it (``required`` as a
   union), which admits exactly the instances ``$ref`` + siblings admitted.
3. **Relax the constraints Anthropic cannot express** (``RELAXED_CONSTRAINTS``) by removing them,
   and drop the ``discriminator`` annotation, which has no validation effect. This is the one
   place the wire is *broader* than the canonical schema. Anthropic's decoder cannot promise a
   non-empty statement, an in-range confidence or a ``local_id`` matching its pattern; Pydantic
   still refuses any answer that violates one, so such an answer becomes a protocol failure
   and is never accepted.
4. **Close every object** that does not state ``additionalProperties`` (``false``, as Anthropic
   requires), then **audit** the result and refuse any construct with no proven wire form.

Unlike OpenAI strict mode, Anthropic does not require every property to be listed as required,
so the canonical ``required`` lists and ``default`` values are carried unchanged.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Final

from pydantic import BaseModel

from foundry.adapters.model_runtime.wire_schema import (
    WireSchemaError,
    resolve_ref,
    subschemas,
    translate_exclusive_unions,
)

__all__ = [
    "ANTHROPIC_WIRE_SCHEMA_COMPILER",
    "RELAXED_CONSTRAINTS",
    "AnthropicWireSchemaError",
    "anthropic_output_format",
    "compile_anthropic_wire_schema",
]

ANTHROPIC_WIRE_SCHEMA_COMPILER: Final[str] = "foundry.anthropic-structured-outputs.v3"
"""Identity of what turns a canonical answer type into the Anthropic wire, bound by a
certification with the wire schema hash. v3 = this compiler for every type except the graph
answer, which uses ``foundry.anthropic-graph-wire.v2`` (``anthropic_graph_wire``). v2 used graph
wire v1, whose gap object lacked the canonical gap description. v1 sent the compiled canonical
graph schema, which Anthropic refused as too large; it certified nothing."""

RELAXED_CONSTRAINTS: Final[tuple[str, ...]] = (
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
)
"""Validation keywords Anthropic structured outputs do not support. They are removed from the
wire and enforced by Pydantic alone, after the answer returns."""

_ANNOTATIONS_DROPPED: Final[tuple[str, ...]] = ("discriminator",)
"""OpenAPI metadata with no JSON Schema validation effect, unsupported by Anthropic."""

_SUPPORTED_FORMATS: Final[frozenset[str]] = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
)

_REFUSED_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "dependentSchemas",
        "dependentRequired",
        "patternProperties",
        "unevaluatedProperties",
        "unevaluatedItems",
        "$dynamicRef",
        "$dynamicAnchor",
        "propertyNames",
        "contains",
        "prefixItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
)


class AnthropicWireSchemaError(WireSchemaError):
    """The canonical schema has no proven Anthropic wire representation. Raised before a call."""


def anthropic_output_format(output_type: type[BaseModel]) -> dict[str, Any]:
    """The Messages API ``output_config.format`` for ``output_type``."""
    return {
        "type": "json_schema",
        "schema": compile_anthropic_wire_schema(output_type.model_json_schema()),
    }


def compile_anthropic_wire_schema(canonical: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic, pure: the input is never mutated, and equal inputs give equal outputs."""
    wire: dict[str, Any] = copy.deepcopy(dict(canonical))
    translate_exclusive_unions(wire, root=wire, path=(), error=AnthropicWireSchemaError)
    _inline_refs_with_siblings(wire, root=copy.deepcopy(wire), path=())
    _relax_and_close(wire, path=())
    _refuse_recursion(wire)
    _audit(wire, path=())
    return wire


# --------------------------------------------------------------------------- 2. $ref siblings


def _merge_into(target: dict[str, Any], siblings: Mapping[str, Any], where: str) -> None:
    for key, value in siblings.items():
        if key == "required":
            merged = list(target.get("required", []))
            merged += [name for name in value if name not in merged]
            target["required"] = merged
        elif key in ("title", "description", "default"):
            target[key] = value
        elif key in target and target[key] != value:
            raise AnthropicWireSchemaError(
                f"$ref sibling {key!r} at {where} conflicts with its target; not merged"
            )
        else:
            target[key] = value


def _inline_refs_with_siblings(node: Any, *, root: dict[str, Any], path: tuple[str, ...]) -> None:
    if not isinstance(node, dict):
        return
    for relative, child in subschemas(node):
        _inline_refs_with_siblings(child, root=root, path=(*path, *relative))
    ref = node.get("$ref")
    if ref and len(node) > 1:
        target = resolve_ref(root, ref, error=AnthropicWireSchemaError)
        if not isinstance(target, dict):
            raise AnthropicWireSchemaError(f"$ref {ref!r} does not resolve to a schema object")
        inlined = copy.deepcopy(target)
        _merge_into(inlined, {k: v for k, v in node.items() if k != "$ref"}, "/".join(path))
        node.clear()
        node.update(inlined)


# --------------------------------------------------------------------------- 3, 4. relax, close


def _relax_and_close(node: Any, *, path: tuple[str, ...]) -> None:
    if not isinstance(node, dict):
        return
    for keyword in (*RELAXED_CONSTRAINTS, *_ANNOTATIONS_DROPPED):
        node.pop(keyword, None)
    if isinstance(node.get("properties"), dict) and "additionalProperties" not in node:
        node["additionalProperties"] = False
    for relative, child in subschemas(node):
        _relax_and_close(child, path=(*path, *relative))


def _refuse_recursion(wire: dict[str, Any]) -> None:
    """A definition that reaches itself through ``$ref`` is a recursive schema: unsupported."""

    def refs(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            if isinstance(node.get("$ref"), str):
                found.add(node["$ref"])
            for _, child in subschemas(node):
                found |= refs(child)
        return found

    definitions = wire.get("$defs", {})
    edges = {f"#/$defs/{name}": refs(body) for name, body in definitions.items()}
    for start in edges:
        seen: set[str] = set()
        pending = list(edges[start])
        while pending:
            current = pending.pop()
            if current == start:
                raise AnthropicWireSchemaError(f"recursive schema through {start}; unsupported")
            if current in seen:
                continue
            seen.add(current)
            pending += list(edges.get(current, ()))


def _audit(node: Any, *, path: tuple[str, ...]) -> None:
    if not isinstance(node, dict):
        return
    where = "/".join(path) or "<root>"
    refused = _REFUSED_KEYWORDS & node.keys()
    if refused:
        raise AnthropicWireSchemaError(f"{sorted(refused)} at {where} has no proven wire form")
    left = (set(RELAXED_CONSTRAINTS) | set(_ANNOTATIONS_DROPPED)) & node.keys()
    if left:
        raise AnthropicWireSchemaError(f"{sorted(left)} at {where} survived relaxation")
    if "$ref" in node and len(node) > 1:
        raise AnthropicWireSchemaError(f"$ref with siblings at {where} survived inlining")
    all_of = node.get("allOf")
    if isinstance(all_of, list) and any(isinstance(e, dict) and "$ref" in e for e in all_of):
        raise AnthropicWireSchemaError(f"allOf over $ref at {where} is unsupported")
    if node.get("format") is not None and node["format"] not in _SUPPORTED_FORMATS:
        raise AnthropicWireSchemaError(f"string format {node['format']!r} at {where} unsupported")
    if isinstance(node.get("minItems"), int) and node["minItems"] > 1:
        raise AnthropicWireSchemaError(f"minItems {node['minItems']} at {where} is unsupported")
    if isinstance(node.get("enum"), list) and any(isinstance(v, dict | list) for v in node["enum"]):
        raise AnthropicWireSchemaError(f"complex enum value at {where} is unsupported")
    if isinstance(node.get("properties"), dict) and node.get("additionalProperties") is not False:
        raise AnthropicWireSchemaError(f"object at {where} admits additional properties")
    if "required" in node and not isinstance(node.get("properties"), dict):
        raise AnthropicWireSchemaError(f"'required' without 'properties' at {where} is refused")
    for relative, child in subschemas(node):
        _audit(child, path=(*path, *relative))
