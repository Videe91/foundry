"""Relation legality for the Intent Graph (IE2.1, spec §3/§3f).

Two properties shape everything in this module.

**Legality is a property of a resolved pair, not of a relation.** ``Relation`` carries a
type and a target id and *no source kind*, so nothing can be decided from the relation
alone: both endpoints must be resolved against state before the matrix means anything.

**Validation is forward-only.** It runs when a new object is admitted, never during
parsing, reduction or replay. Historical objects predate these rules and may carry
relations IE2 would now refuse; validating during reconstruction would make the event log
unreplayable, which is precisely the property the MR4–MR6 certifications rest on. A law
that rewrites history to satisfy itself is not a law, it is a migration.

Target ids span **two semantic planes**, and the certified path already crosses them: a
Slice-1 ``Requirement`` derives from a v2 ``SemanticClaim`` living in
``state.semantic.claims``, which is absent from ``state.objects``. A resolver that looked
only at ``state.objects`` would reject the certified path outright.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from foundry.domain.common import RelationType
from foundry.domain.semantic import SemanticKind

if TYPE_CHECKING:
    from foundry.domain.semantic import SemanticObject
    from foundry.domain.state import IntentState

__all__ = [
    "LEGAL_RELATION_TARGETS",
    "AmbiguousTargetError",
    "IllegalRelationError",
    "RelationLegalityError",
    "UnresolvedTargetError",
    "resolve_target_kind",
    "validate_relations",
]


class RelationLegalityError(ValueError):
    """Base for every forward-write relation refusal."""


class UnresolvedTargetError(RelationLegalityError):
    """The target id exists in no permitted namespace.

    Refused rather than ignored: a relation pointing at nothing is not a weaker relation,
    it is an unverifiable one, and silently dropping it would let a basis claim reference
    something that was never recorded.
    """


class AmbiguousTargetError(RelationLegalityError):
    """The target id resolves in more than one plane.

    The repository enforces no global cross-plane id uniqueness — the ``CLAIM-``/``REQ-``
    prefixes are conventions, not constraints — so a collision is representable. Choosing a
    namespace would make legality depend on scan order; failing closed keeps it deterministic.
    """


class IllegalRelationError(RelationLegalityError):
    """This source kind may not point at this target kind with this relation."""


_NORMATIVE: Final[frozenset[SemanticKind]] = frozenset(
    {
        SemanticKind.INTENT,
        SemanticKind.GOAL,
        SemanticKind.OUTCOME,
        SemanticKind.REQUIREMENT,
        SemanticKind.CONSTRAINT,
        SemanticKind.NON_GOAL,
        SemanticKind.PREFERENCE,
        SemanticKind.DECISION,
    }
)
"""Kinds that assert desired state. The strength lives in the type itself (R5)."""

_BASIS_TARGETS: Final[frozenset[SemanticKind]] = frozenset(
    {
        SemanticKind.CLAIM,
        SemanticKind.EVIDENCE,
        SemanticKind.CONSTRAINT,
        SemanticKind.GOAL,
        SemanticKind.OUTCOME,
        SemanticKind.REQUIREMENT,
        SemanticKind.DECISION,
    }
)
"""What may ground an object.

``INTENT`` is deliberately absent (``I-SEP-1``): relevance is never expressed as basis.
``DECISION`` is an *intermediate* basis only — a choice may explain a Constraint, but the
chain must continue past it to evidence, which ``I-BASIS-2`` enforces in IE2.2.
"""

type _KindSet = frozenset[SemanticKind]

LEGAL_RELATION_TARGETS: Final[dict[RelationType, tuple[_KindSet, _KindSet]]] = {
    RelationType.DERIVED_FROM: (frozenset(_NORMATIVE), _BASIS_TARGETS),
    RelationType.SERVES: (
        frozenset(_NORMATIVE - {SemanticKind.INTENT}),
        frozenset({SemanticKind.GOAL, SemanticKind.OUTCOME, SemanticKind.INTENT}),
    ),
    RelationType.EXCLUDES: (
        frozenset({SemanticKind.NON_GOAL}),
        frozenset(
            {
                SemanticKind.GOAL,
                SemanticKind.OUTCOME,
                SemanticKind.REQUIREMENT,
                SemanticKind.CONSTRAINT,
            }
        ),
    ),
    RelationType.CONSTRAINS: (
        frozenset({SemanticKind.CONSTRAINT}),
        frozenset(
            {
                SemanticKind.REQUIREMENT,
                SemanticKind.GOAL,
                SemanticKind.OUTCOME,
                SemanticKind.INTENT,
            }
        ),
    ),
    RelationType.CONFLICTS_WITH: (frozenset(_NORMATIVE), frozenset(_NORMATIVE)),
    RelationType.MEASURED_BY: (
        frozenset({SemanticKind.REQUIREMENT, SemanticKind.OUTCOME}),
        frozenset({SemanticKind.METRIC}),
    ),
    RelationType.VERIFIED_BY: (
        frozenset({SemanticKind.REQUIREMENT, SemanticKind.CONTRACT}),
        frozenset({SemanticKind.VERIFICATION_OBLIGATION}),
    ),
    RelationType.SUPPORTS: (
        frozenset({SemanticKind.EVIDENCE}),
        frozenset({SemanticKind.CLAIM}),
    ),
    RelationType.CHALLENGES: (
        frozenset({SemanticKind.EVIDENCE}),
        frozenset({SemanticKind.CLAIM}),
    ),
    RelationType.AFFECTS: (
        frozenset({SemanticKind.PREFERENCE, SemanticKind.ASSUMPTION}),
        frozenset(_NORMATIVE),
    ),
}
"""``relation -> (legal source kinds, legal target kinds)``.

``SUPERSEDES`` is handled separately: it is legal only between objects of the *same* kind,
which a fixed target set cannot express.

Absence from this table is a **refusal on new writes**, not permission. ``REQUIRES`` and
``RELATES_TO`` remain in the serialized enum so historical streams parse, but Foundry has
never defined what they mean, and inventing rules for them here would be worse than
refusing them. A relation added to the enum later inherits the same protection without
anyone remembering to come back: undefined is closed until someone decides otherwise.
"""


def resolve_target_kind(state: IntentState, target_id: str) -> SemanticKind:
    """Resolve a target id to its kind across every permitted plane.

    Never inspects the id's text. Prefix conventions such as ``CLAIM-`` are not identity,
    and an object whose id merely looks like a claim must resolve to what it actually is.
    """
    found: list[SemanticKind] = []

    obj = state.objects.get(target_id)
    if obj is not None:
        found.append(obj.kind)
    if target_id in state.semantic.claims:
        found.append(SemanticKind.CLAIM)
    if target_id in state.semantic.evidence:
        found.append(SemanticKind.EVIDENCE)

    if not found:
        raise UnresolvedTargetError(
            f"relation target {target_id!r} exists in no permitted namespace; a relation "
            "pointing at nothing is never silently accepted"
        )
    if len(set(found)) > 1 or len(found) > 1:
        raise AmbiguousTargetError(
            f"relation target {target_id!r} resolves in more than one plane ({found}); "
            "no namespace is chosen for you"
        )
    return found[0]


def validate_relations(state: IntentState, obj: SemanticObject) -> None:
    """Refuse any relation this object may not hold. Forward-write only.

    Raises on the first illegal relation rather than collecting: an admission is all-or-
    nothing, so there is no partial acceptance for a caller to act on.
    """
    source_kind = obj.kind
    for relation in obj.relations:
        target_kind = resolve_target_kind(state, relation.target_id)

        if relation.relation_type is RelationType.SUPERSEDES:
            if target_kind is not source_kind:
                raise IllegalRelationError(
                    f"{source_kind.value} may not SUPERSEDES {target_kind.value}; "
                    "supersession replaces like with like"
                )
            continue

        allowed = LEGAL_RELATION_TARGETS.get(relation.relation_type)
        if allowed is None:
            # Fail closed. `REQUIRES` and `RELATES_TO` survive in the serialized enum so old
            # streams parse, but Foundry has never defined what they mean, and a new governed
            # write must not assert a semantics nobody has decided. Permitting them would let
            # undefined meaning accumulate in the graph faster than anyone rules on it -- and
            # the same protection applies automatically to any relation added to the enum
            # later but not to this matrix.
            raise IllegalRelationError(
                f"{relation.relation_type.value} has no IE2 legality and may not be written "
                "on a newly admitted object; historical streams carrying it still replay"
            )

        legal_sources, legal_targets = allowed
        if source_kind not in legal_sources:
            raise IllegalRelationError(
                f"{source_kind.value} may not be the source of {relation.relation_type.value}"
            )
        if target_kind not in legal_targets:
            raise IllegalRelationError(
                f"{source_kind.value} may not {relation.relation_type.value} a "
                f"{target_kind.value} (target {relation.target_id!r})"
            )
