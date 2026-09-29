"""The current semantic view of an ``IntentState``, with root Intents as staleness boundaries.

**A root INTENT is a staleness boundary (IE3 design §17.2, decision 2026-09-29).** For a root
Intent, ``DERIVED_FROM`` records provenance and evidential grounding; it is not a freshness
dependency. Superseding an operational claim the root cites therefore leaves the root current
and not stale, and staleness never passes through a root. Every other object keeps the existing
law (``derivation.stale_object_ids``): a Requirement or Constraint derived from a superseded
claim is stale and is replaced normally, and its replacement may serve the same root.

**What a root is.** Every ``INTENT`` object. Relation legality makes that exact rather than a
convention: an Intent is never a ``SERVES`` source and never a basis target
(``relation_legality``), so nothing is above it and nothing derives from it. Authority and
lifecycle do not enter: a PROPOSED model-authored root and a CANONICAL human-authorised root
obey one law, and a dead Intent's staleness is moot.

**What this does not decide.** Replacing or amending a root is a lifecycle operation of its own
(D8), still unbuilt. Until it exists, a root cannot change through synthesis, and no ordinary
claim correction may simulate an Intent amendment through transitive staleness. A true change
of purpose is not resolved here.

The ledger is untouched: this is a current-view projection over recorded edges, recomputed on
every replay, so no event is added or migrated.
"""

from __future__ import annotations

from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState

__all__ = ["derive_intent_view", "root_intent_ids"]


def root_intent_ids(state: IntentState) -> frozenset[str]:
    """Every Intent in ``state``: the staleness boundaries."""
    return frozenset(o.id for o in state.objects.values() if o.kind is SemanticKind.INTENT)


def derive_intent_view(state: IntentState) -> CurrentSemanticView:
    """``derive_view`` of ``state.semantic`` with every root Intent as a staleness boundary.

    The one view any reader holding ``IntentState`` uses."""
    return derive_view(state.semantic, staleness_boundary_ids=root_intent_ids(state))
