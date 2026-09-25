"""Object scope applicability: one predicate, one home (IE2.2 §7, R39).

``scope_descriptor`` is the ``scope`` tuple an object, address or locus declares;
``evaluated_scope`` is the delivery scope being asked about. An empty descriptor is
project-wide and applies everywhere; otherwise the evaluated scope must be named.

This is **applicability, not containment**: a ``("billing",)`` Requirement may serve a
project-wide Goal. It is deliberately *not* AuthorityRecord coverage, replacement coverage
or target-scope authorization -- those answer different questions and keep their own rules.
"""

from __future__ import annotations

__all__ = ["scope_applies"]


def scope_applies(scope_descriptor: tuple[str, ...], evaluated_scope: str) -> bool:
    """Does something declaring ``scope_descriptor`` apply to ``evaluated_scope``?"""
    return scope_descriptor == () or evaluated_scope in scope_descriptor
