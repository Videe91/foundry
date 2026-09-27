"""Deterministic identity of a certification exam's executable meaning.

A certification certifies a contestant *on an exam*. Case C of the first IE3 graph exam showed
that the exam itself can be defective, so an exam change must change the identity a certificate
binds. This module fingerprints the parts of an exam that decide what is asked and what passes:

* **code**: every exam function reachable from the given roots (builders, scorers, gates,
  dispatch, attempt runner, verdict), followed transitively through names they reference in
  ``tests.*`` modules, and every simple constant they read. Each function contributes its
  ``ast.dump`` with docstrings removed, so whitespace, comments, docstrings and line numbers
  never move the digest, while any change to what the code does always does;
* **values**: the constants and data those functions read (strings, numbers, enums, regexes,
  timestamps, and containers of them). A container of functions queues those functions.

Production code is deliberately not followed. It is bound separately by the prompt, policy,
schema and compiler identities and by the frozen production base.
"""

from __future__ import annotations

import ast
import datetime
import enum
import hashlib
import importlib
import inspect
import json
import re
import textwrap
from collections.abc import Callable, Iterable
from typing import Any

__all__ = ["canonical_digest", "code_closure", "source_fingerprint"]

_EXAM_PREFIX = "tests."


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def source_fingerprint(source: str) -> str:
    """The semantic form of a piece of source: its docstring-free AST, without positions."""
    tree = _strip_docstrings(ast.parse(textwrap.dedent(source)))
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _is_exam_function(value: Any) -> bool:
    return inspect.isfunction(value) and str(value.__module__).startswith(_EXAM_PREFIX)


def _value(value: Any, queue: list[Callable[..., Any]]) -> Any:
    """A JSON-able canonical form of a constant, or ``None`` when it is not exam data."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, enum.Enum):
        return {
            "enum": f"{type(value).__qualname__}.{value.name}",
            "value": _value(value.value, queue),
        }
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": value.flags}
    if isinstance(value, datetime.datetime | datetime.date):
        return {"time": value.isoformat()}
    if _is_exam_function(value):
        queue.append(value)
        return {"function": f"{value.__module__}.{value.__qualname__}"}
    if isinstance(value, dict):
        items = {str(k): _value(v, queue) for k, v in value.items()}
        return {"dict": dict(sorted(items.items()))}
    if isinstance(value, list | tuple):
        return {"seq": [_value(v, queue) for v in value]}
    if isinstance(value, frozenset | set):
        return {"set": sorted(json.dumps(_value(v, queue), sort_keys=True) for v in value)}
    return None


def _referenced(tree: ast.AST, function: Callable[..., Any]) -> list[tuple[str, Any]]:
    """Names the function reads, resolved in its globals or its own ``tests.*`` imports."""
    local_imports: dict[str, Any] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith(_EXAM_PREFIX)
        ):
            module = importlib.import_module(node.module)
            for alias in node.names:
                local_imports[alias.asname or alias.name] = getattr(module, alias.name)
    names = sorted(
        {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | set(local_imports)
    )
    resolved: list[tuple[str, Any]] = []
    for name in names:
        if name in local_imports:
            resolved.append((name, local_imports[name]))
        elif name in function.__globals__:
            resolved.append((name, function.__globals__[name]))
    return resolved


def code_closure(roots: Iterable[Callable[..., Any]]) -> dict[str, Any]:
    """Every exam function reachable from ``roots`` and every constant they read."""
    closure: dict[str, Any] = {}
    queue: list[Callable[..., Any]] = list(roots)
    while queue:
        function = queue.pop()
        key = f"{function.__module__}.{function.__qualname__}"
        if key in closure:
            continue
        tree = _strip_docstrings(ast.parse(textwrap.dedent(inspect.getsource(function))))
        closure[key] = ast.dump(tree, annotate_fields=True, include_attributes=False)
        for name, value in _referenced(tree, function):
            if _is_exam_function(value):
                queue.append(value)
                continue
            data = _value(value, queue)
            if data is not None:
                closure[f"{function.__module__}:{name}"] = data
    return dict(sorted(closure.items()))


def canonical_digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
