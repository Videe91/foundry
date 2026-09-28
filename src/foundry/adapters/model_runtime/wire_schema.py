"""Provider-neutral pieces of wire-schema compilation, shared by every provider's compiler.

A provider wire schema is a deterministic representation of a canonical answer schema. Some
providers reject ``oneOf`` (OpenAI and Anthropic both do), and ``anyOf`` differs from ``oneOf``
only on an instance that matches two or more branches. So the rewrite is exact precisely when no
instance can, and this module proves that per union from structure alone: every pair of branches
(and every pair of their leaves, through ``$ref`` and nested unions) must differ in the
``const``/``enum`` of some property that at least one of them requires. A union it cannot prove
is refused, never rewritten.

Each provider's compiler supplies its own error type, so a refusal names the provider whose wire
could not be built. Everything provider-specific stays in that provider's module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from foundry.model_runtime.errors import ModelRequestError

__all__ = [
    "WireSchemaError",
    "resolve_ref",
    "subschemas",
    "translate_exclusive_unions",
]


class WireSchemaError(ModelRequestError):
    """A canonical schema has no proven wire representation. Raised before any call."""


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


def subschemas(node: Mapping[str, Any]) -> list[tuple[tuple[str, ...], Any]]:
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


def translate_exclusive_unions(
    node: Any, *, root: dict[str, Any], path: tuple[str, ...], error: type[WireSchemaError]
) -> None:
    """Rewrite every provably exclusive ``oneOf`` in place as ``anyOf``; refuse any other."""
    if not isinstance(node, dict):
        return
    for relative, child in subschemas(node):
        translate_exclusive_unions(child, root=root, path=(*path, *relative), error=error)
    if "oneOf" in node:
        branches = node["oneOf"]
        _prove_exclusive(branches, root=root, path=path, error=error)
        rebuilt = {("anyOf" if key == "oneOf" else key): value for key, value in node.items()}
        node.clear()
        node.update(rebuilt)


def _prove_exclusive(
    branches: Sequence[Any],
    *,
    root: dict[str, Any],
    path: tuple[str, ...],
    error: type[WireSchemaError],
) -> None:
    leaves = [
        _leaves(branch, root=root, path=path, inherited=frozenset(), error=error)
        for branch in branches
    ]
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            for left in leaves[i]:
                for right in leaves[j]:
                    if not _disjoint(left, right):
                        raise error(
                            f"oneOf at {'/'.join(path) or '<root>'}: branches {i} and {j} are "
                            "not provably exclusive, so anyOf would not be equivalent; refused"
                        )


type _Leaf = tuple[Mapping[str, Any], frozenset[str]]
"""A branch leaf: its properties and everything it requires."""


def _leaves(
    branch: Any,
    *,
    root: dict[str, Any],
    path: tuple[str, ...],
    inherited: frozenset[str],
    error: type[WireSchemaError],
) -> list[_Leaf]:
    if not isinstance(branch, dict):
        raise error(f"unprovable union branch at {'/'.join(path)}: {branch!r}")
    required = inherited | frozenset(branch.get("required", ()))
    if "$ref" in branch:
        target = resolve_ref(root, branch["$ref"], error=error)
        return _leaves(target, root=root, path=path, inherited=required, error=error)
    for key in ("oneOf", "anyOf"):
        if key in branch:
            leaves: list[_Leaf] = []
            for sub in branch[key]:
                leaves += _leaves(sub, root=root, path=path, inherited=required, error=error)
            return leaves
    properties = branch.get("properties")
    if not isinstance(properties, dict):
        raise error(f"unprovable union branch at {'/'.join(path)}: no properties to tell it apart")
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


def resolve_ref(root: Mapping[str, Any], ref: str, *, error: type[WireSchemaError]) -> Any:
    if not ref.startswith("#/"):
        raise error(f"unsupported $ref {ref!r}: only local refs are compiled")
    resolved: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(resolved, dict) or part not in resolved:
            raise error(f"unresolvable $ref {ref!r}")
        resolved = resolved[part]
    return resolved
