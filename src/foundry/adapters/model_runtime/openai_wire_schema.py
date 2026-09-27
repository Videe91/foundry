"""OpenAI provider wire schema: a deterministic representation of a canonical answer schema.

Two contract levels, never conflated:

* **Canonical domain contract**: the caller's Pydantic output type and the provider-neutral JSON
  Schema it generates (``output_type.model_json_schema()``). Pydantic is the source of truth, and
  every returned answer is validated by it again.
* **Provider wire contract**: the schema actually transmitted to OpenAI Structured Outputs. It
  may be syntactically stricter than the canonical schema where OpenAI requires it, and it is
  sound: anything it admits, Pydantic accepts.

The compiler does exactly three things and refuses everything else.

1. **Proven ``oneOf`` -> ``anyOf``.** OpenAI rejects ``oneOf`` (observed: ``400
   invalid_json_schema``, "'oneOf' is not permitted"). ``anyOf`` differs from ``oneOf`` only on
   an instance that matches two or more branches, so the rewrite is exact precisely when no
   instance can. The compiler proves that per union from structure alone: every pair of
   branches (and every pair of their leaves, through ``$ref`` and nested unions) must differ in
   the ``const``/``enum`` of some property that at least one of them requires. A union it cannot
   prove is refused, never rewritten.
2. **OpenAI's strict form**, reproduced exactly as the ``openai`` SDK's own ``parse`` builds it
   (``openai.lib._pydantic._ensure_strict_json_schema``, pinned by a byte-equality test): every
   property is listed in ``required``, objects without ``additionalProperties`` get ``false``,
   ``default: null`` is dropped, and a ``$ref`` with siblings is inlined. Requiring a property
   that the canonical contract lets a producer omit only removes the omitted spelling: the
   defaulted value itself remains admissible, so every canonical value keeps a wire
   representation ("default materialization").
3. **A fail-closed audit** of the result. Any construct without a representation proof here
   (``oneOf`` left over, ``allOf`` with more than one entry, ``not``, conditionals, dependent or
   pattern properties, unevaluated keywords, dynamic refs, ``propertyNames``, ``contains``,
   ``prefixItems``) refuses the compilation.

Metadata the compiler has no evidence against (``discriminator``, titles, descriptions,
non-null defaults) is carried through unchanged. Whether OpenAI accepts it is established by the
compatibility probe, not guessed here.

For a schema with no ``oneOf`` the result is byte-identical to what the SDK sent before this
compiler existed, so an existing caller's wire contract is unchanged.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import BaseModel

from foundry.model_runtime.errors import ModelRequestError

__all__ = [
    "OPENAI_WIRE_SCHEMA_COMPILER",
    "OpenAIWireSchemaError",
    "compile_openai_wire_schema",
    "openai_text_format",
]

OPENAI_WIRE_SCHEMA_COMPILER: Final[str] = "foundry.openai-structured-outputs.v1"
"""Identity of this compiler. A certification binds it with the wire schema hash, so a change
to what this module emits can never inherit a certificate earned under the old wire."""

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
    }
)


_SCHEMA_MAPS: Final[frozenset[str]] = frozenset({"properties", "$defs", "definitions"})
"""Keywords whose value maps names to schemas: the names are data, never keywords."""
_SCHEMA_LISTS: Final[frozenset[str]] = frozenset({"anyOf", "oneOf", "allOf", "prefixItems"})
_SCHEMA_VALUES: Final[frozenset[str]] = frozenset(
    {
        "items",
        "not",
        "if",
        "then",
        "else",
        "contains",
        "propertyNames",
        "additionalProperties",
        "unevaluatedProperties",
        "unevaluatedItems",
    }
)


def _subschemas(node: Mapping[str, Any]) -> list[tuple[tuple[str, ...], Any]]:
    """Every schema directly nested in ``node``, with its relative path. Values are skipped."""
    found: list[tuple[tuple[str, ...], Any]] = []
    for key, value in node.items():
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            found += [((key, name), child) for name, child in value.items()]
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            found += [((key, str(i)), child) for i, child in enumerate(value)]
        elif key in _SCHEMA_VALUES and isinstance(value, dict):
            found.append(((key,), value))
    return found


class OpenAIWireSchemaError(ModelRequestError):
    """The canonical schema has no proven OpenAI wire representation. Raised before any call."""


def openai_text_format(output_type: type[BaseModel]) -> dict[str, Any]:
    """The Responses API ``text.format`` for ``output_type``: the same envelope the SDK builds."""
    return {
        "type": "json_schema",
        "strict": True,
        "name": output_type.__name__,
        "schema": compile_openai_wire_schema(output_type.model_json_schema()),
    }


def compile_openai_wire_schema(canonical: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic, pure: the input is never mutated, and equal inputs give equal outputs."""
    wire: dict[str, Any] = copy.deepcopy(dict(canonical))
    _translate_exclusive_unions(wire, root=wire, path=())
    wire = _ensure_strict(wire, path=(), root=wire)
    _audit(wire, path=())
    return wire


# --------------------------------------------------------------------------- 1. unions


def _translate_exclusive_unions(node: Any, *, root: dict[str, Any], path: tuple[str, ...]) -> None:
    if not isinstance(node, dict):
        return
    for relative, child in _subschemas(node):
        _translate_exclusive_unions(child, root=root, path=(*path, *relative))
    if "oneOf" in node:
        branches = node["oneOf"]
        _prove_exclusive(branches, root=root, path=path)
        rebuilt = {("anyOf" if key == "oneOf" else key): value for key, value in node.items()}
        node.clear()
        node.update(rebuilt)


def _prove_exclusive(
    branches: Sequence[Any], *, root: dict[str, Any], path: tuple[str, ...]
) -> None:
    leaves = [_leaves(branch, root=root, path=path, inherited=frozenset()) for branch in branches]
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            for left in leaves[i]:
                for right in leaves[j]:
                    if not _disjoint(left, right):
                        raise OpenAIWireSchemaError(
                            f"oneOf at {'/'.join(path) or '<root>'}: branches {i} and {j} are "
                            "not provably exclusive, so anyOf would not be equivalent; refused"
                        )


type _Leaf = tuple[Mapping[str, Any], frozenset[str]]
"""A branch leaf: its properties and everything it requires."""


def _leaves(
    branch: Any, *, root: dict[str, Any], path: tuple[str, ...], inherited: frozenset[str]
) -> list[_Leaf]:
    if not isinstance(branch, dict):
        raise OpenAIWireSchemaError(f"unprovable union branch at {'/'.join(path)}: {branch!r}")
    required = inherited | frozenset(branch.get("required", ()))
    if "$ref" in branch:
        return _leaves(_resolve(root, branch["$ref"]), root=root, path=path, inherited=required)
    for key in ("oneOf", "anyOf"):
        if key in branch:
            leaves: list[_Leaf] = []
            for sub in branch[key]:
                leaves += _leaves(sub, root=root, path=path, inherited=required)
            return leaves
    properties = branch.get("properties")
    if not isinstance(properties, dict):
        raise OpenAIWireSchemaError(
            f"unprovable union branch at {'/'.join(path)}: no properties to tell it apart"
        )
    return [(properties, required)]


def _admitted(schema: Any) -> frozenset[str] | None:
    """The JSON values a property schema admits, when it is a finite ``const``/``enum``."""
    if not isinstance(schema, dict):
        return None
    if "const" in schema:
        return frozenset({json.dumps(schema["const"], sort_keys=True)})
    if isinstance(schema.get("enum"), list):
        return frozenset(json.dumps(value, sort_keys=True) for value in schema["enum"])
    return None


def _disjoint(left: _Leaf, right: _Leaf) -> bool:
    """True if no instance can satisfy both leaves.

    Sufficient condition: some property has disjoint finite admitted values in both leaves, and
    at least one leaf requires it. Present, the values conflict; absent, the requiring leaf fails.
    """
    (left_props, left_required), (right_props, right_required) = left, right
    for name in left_props.keys() & right_props.keys():
        a, b = _admitted(left_props[name]), _admitted(right_props[name])
        if a is None or b is None or a & b:
            continue
        if name in left_required or name in right_required:
            return True
    return False


def _resolve(root: Mapping[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise OpenAIWireSchemaError(f"unsupported $ref {ref!r}: only local refs are compiled")
    resolved: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(resolved, dict) or part not in resolved:
            raise OpenAIWireSchemaError(f"unresolvable $ref {ref!r}")
        resolved = resolved[part]
    return resolved


# --------------------------------------------------------------------------- 2. strict form


def _ensure_strict(schema: Any, *, path: tuple[str, ...], root: dict[str, Any]) -> dict[str, Any]:
    """OpenAI's strict form, reproduced exactly as the SDK's ``parse`` builds it."""
    if not isinstance(schema, dict):
        raise OpenAIWireSchemaError(f"expected a schema object at {'/'.join(path)}")
    for container in ("$defs", "definitions"):
        defs = schema.get(container)
        if isinstance(defs, dict):
            for name, definition in defs.items():
                _ensure_strict(definition, path=(*path, container, name), root=root)
    if schema.get("type") == "object" and "additionalProperties" not in schema:
        schema["additionalProperties"] = False
    properties = schema.get("properties")
    if isinstance(properties, dict):
        schema["required"] = list(properties)
        schema["properties"] = {
            key: _ensure_strict(value, path=(*path, "properties", key), root=root)
            for key, value in properties.items()
        }
    items = schema.get("items")
    if isinstance(items, dict):
        schema["items"] = _ensure_strict(items, path=(*path, "items"), root=root)
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        schema["anyOf"] = [
            _ensure_strict(variant, path=(*path, "anyOf", str(i)), root=root)
            for i, variant in enumerate(any_of)
        ]
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        if len(all_of) == 1:
            schema.update(_ensure_strict(all_of[0], path=(*path, "allOf", "0"), root=root))
            schema.pop("allOf")
        else:
            schema["allOf"] = [
                _ensure_strict(entry, path=(*path, "allOf", str(i)), root=root)
                for i, entry in enumerate(all_of)
            ]
    if "default" in schema and schema["default"] is None:
        schema.pop("default")
    ref = schema.get("$ref")
    if ref and len(schema) > 1:
        resolved = _resolve(root, ref)
        if not isinstance(resolved, dict):
            raise OpenAIWireSchemaError(f"$ref {ref!r} does not resolve to a schema object")
        schema.update({**resolved, **schema})
        schema.pop("$ref")
        return _ensure_strict(schema, path=path, root=root)
    return schema


# --------------------------------------------------------------------------- 3. audit


def _audit(node: Any, *, path: tuple[str, ...]) -> None:
    if not isinstance(node, dict):
        return
    where = "/".join(path) or "<root>"
    refused = _REFUSED_KEYWORDS & node.keys()
    if refused:
        raise OpenAIWireSchemaError(f"{sorted(refused)} at {where} has no proven wire form")
    if isinstance(node.get("allOf"), list):
        raise OpenAIWireSchemaError(f"allOf with several entries at {where} is refused")
    if "$ref" in node and len(node) > 1:
        raise OpenAIWireSchemaError(f"$ref with siblings at {where} survived strict compilation")
    properties = node.get("properties")
    if "required" in node and not isinstance(properties, dict):
        raise OpenAIWireSchemaError(f"'required' without 'properties' at {where} is refused")
    if isinstance(properties, dict):
        if node.get("required") != list(properties):
            raise OpenAIWireSchemaError(f"object at {where} does not require every property")
        if node.get("additionalProperties") is not False:
            raise OpenAIWireSchemaError(f"object at {where} admits additional properties")
    for relative, child in _subschemas(node):
        _audit(child, path=(*path, *relative))
