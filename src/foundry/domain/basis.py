"""Grounding: when is a declared basis lawful? (IE2.2b, spec §4-§5a, §10)

One law, evaluated in two places. The IE2 seam refuses a new ``CANONICAL`` object whose
declared basis breaks it, before anything is appended; readiness evaluates the identical
function over current state, so history -- which is never refused and always replays --
turns an unlawful basis into a deterministic blocker instead. Timing differs; semantic
truth does not.

What a chain may pass through and end at:

* a **lawful evidential terminal** is a v2 ``SemanticClaim`` whose asserting judgment is
  active, whose cited evidence is all present, and whose authority is ``CANONICAL`` (R35,
  R42). Present, not newest: evidence supersession is untouched.
* a **lawful authoritative terminal** is a current ``CANONICAL`` ``ProjectDecision``. Its
  rationale is optional; a declared one must itself be lawful (R34).
* ``GOAL``, ``OUTCOME``, ``REQUIREMENT`` and ``CONSTRAINT`` are **intermediates**: current,
  ``CANONICAL``, and grounded further. A canonical Goal with no basis of its own is not a
  terminal (I-BASIS-2) -- nothing but a claim or a decision ends a chain.
* ``ASSUMPTION`` may appear nowhere (I-BASIS-3). ``EvidenceItem`` is never a direct
  terminal: a claim must say what evidence means before intent may rest on it. Every other
  kind -- ``NON_GOAL``, ``PREFERENCE``, ``INTENT``, legacy ``Claim``/``Evidence`` objects --
  grounds nothing.

Authority is read, never re-proved: a node that is ``CANONICAL`` *is* the record of the act
that made it so (R33). A strong basis never raises an object's authority and a weak one
never lowers it (R45, R49); a weak basis only blocks delivery.

Traversal is iterative and memoised, so a long historical chain cannot exhaust the stack and
a diamond is walked once. The object's own id starts on the path, so a historical cycle
through it is reported rather than followed forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from foundry.domain.authority import object_is_current
from foundry.domain.common import Authority, FrozenModel
from foundry.domain.events import derivation_parents_of
from foundry.domain.relation_legality import RelationLegalityError, resolve_target_kind
from foundry.domain.semantic import Constraint, ConstraintFacet, SemanticKind
from foundry.domain.semantic_view import active_judgment_ids

if TYPE_CHECKING:
    from foundry.domain.semantic import SemanticObject
    from foundry.domain.state import IntentState

__all__ = [
    "ASSUMPTION_IN_BASIS",
    "BASIS_BLOCKER_CODES",
    "BASIS_CYCLE",
    "DEAD_BASIS",
    "UNGROUNDED_CANONICAL_OBJECT",
    "UNLAWFUL_BASIS_AUTHORITY",
    "BasisBlocker",
    "BasisDefect",
    "UnlawfulBasisError",
    "assert_lawful_basis",
    "basis_defects",
]

UNGROUNDED_CANONICAL_OBJECT: Final = "UNGROUNDED_CANONICAL_OBJECT"
DEAD_BASIS: Final = "DEAD_BASIS"
UNLAWFUL_BASIS_AUTHORITY: Final = "UNLAWFUL_BASIS_AUTHORITY"
ASSUMPTION_IN_BASIS: Final = "ASSUMPTION_IN_BASIS"
BASIS_CYCLE: Final = "BASIS_CYCLE"

BASIS_BLOCKER_CODES: Final[tuple[str, ...]] = (
    UNGROUNDED_CANONICAL_OBJECT,
    DEAD_BASIS,
    UNLAWFUL_BASIS_AUTHORITY,
    ASSUMPTION_IN_BASIS,
    BASIS_CYCLE,
)
"""The five IE2.2b codes, in v2's deterministic refusal order (R54)."""

_INTERMEDIATE_KINDS: Final[frozenset[SemanticKind]] = frozenset(
    {
        SemanticKind.GOAL,
        SemanticKind.OUTCOME,
        SemanticKind.REQUIREMENT,
        SemanticKind.CONSTRAINT,
    }
)
"""Kinds a chain may pass *through*. Written out, never derived from a frozen kind set."""

_EVIDENCE_REQUIRING_FACETS: Final[frozenset[ConstraintFacet]] = frozenset(
    {ConstraintFacet.EVIDENCE_BOUND, ConstraintFacet.EXTERNAL_MANDATE}
)
"""§4/§11: these canonical Constraints must rest on evidence, not only on a project choice."""


class BasisDefect(FrozenModel):
    """Why ``object_id``'s declared basis is unlawful, and the node where it fails."""

    code: str
    object_id: str
    node_id: str
    reason: str


class BasisBlocker(FrozenModel):
    """An ids-only readiness diagnosis: this canonical object's basis fails at this node.

    Deliberately not a ``ClosureBlocker``. A basis defect never reopens closure or stops
    the package from building (P4, R52); it only makes the closed contract unsafe to hand
    downstream now.
    """

    code: str
    object_ids: tuple[str, ...]


class UnlawfulBasisError(ValueError):
    """A new canonical object's declared basis is unlawful; nothing was appended."""


@dataclass(frozen=True)
class _Verdict:
    """A node's grounding. ``evidential``: some lawful path below it reaches a claim."""

    code: str | None
    node_id: str
    reason: str
    evidential: bool = False


@dataclass
class _Frame:
    node_id: str
    parents: tuple[str, ...]
    index: int = 0
    evidential: bool = False


@dataclass
class _Walk:
    state: IntentState
    active_judgments: frozenset[str]
    on_path: set[str]
    results: dict[str, _Verdict] = field(default_factory=dict)

    def verdict(self, start: str) -> _Verdict:
        entered = self._enter(start)
        if isinstance(entered, _Verdict):
            return entered
        stack = [_Frame(start, entered)]
        child: _Verdict | None = None
        while stack:
            frame = stack[-1]
            if child is not None:
                if child.code is not None:
                    # A node is lawful only if every declared basis is; the first failure
                    # below it is the failure it reports.
                    stack.pop()
                    child = self._finish(frame.node_id, child)
                    continue
                frame.evidential = frame.evidential or child.evidential
                child = None
            if frame.index == len(frame.parents):
                stack.pop()
                child = self._finish(
                    frame.node_id,
                    _Verdict(None, frame.node_id, "lawful", evidential=frame.evidential),
                )
                continue
            parent = frame.parents[frame.index]
            frame.index += 1
            entered = self._enter(parent)
            if isinstance(entered, _Verdict):
                child = entered
            else:
                stack.append(_Frame(parent, entered))
        assert child is not None
        return child

    def _finish(self, node_id: str, verdict: _Verdict) -> _Verdict:
        self.results[node_id] = verdict
        self.on_path.discard(node_id)
        return verdict

    def _enter(self, node_id: str) -> _Verdict | tuple[str, ...]:
        """A settled verdict for ``node_id``, or the parents it must be grounded through."""
        if node_id in self.on_path:
            return _Verdict(BASIS_CYCLE, node_id, f"{node_id!r} is its own basis")
        cached = self.results.get(node_id)
        if cached is not None:
            return cached
        local = self._local(node_id)
        if isinstance(local, _Verdict):
            self.results[node_id] = local
            return local
        self.on_path.add(node_id)
        return local

    def _local(self, node_id: str) -> _Verdict | tuple[str, ...]:
        try:
            kind = resolve_target_kind(self.state, node_id)
        except RelationLegalityError as error:
            return _Verdict(UNGROUNDED_CANONICAL_OBJECT, node_id, str(error))

        claim = self.state.semantic.claims.get(node_id)
        if claim is not None:
            if claim.created_by_judgment_id not in self.active_judgments:
                return _Verdict(
                    DEAD_BASIS, node_id, "the judgment that asserted this claim is not active"
                )
            missing = [e for e in claim.evidence_ids if e not in self.state.semantic.evidence]
            if missing:
                return _Verdict(
                    UNGROUNDED_CANONICAL_OBJECT, node_id, f"cited evidence {missing} is absent"
                )
            if claim.authority is not Authority.CANONICAL:
                return _Verdict(
                    UNLAWFUL_BASIS_AUTHORITY,
                    node_id,
                    f"claim authority is {claim.authority.value}; only CANONICAL grounds intent",
                )
            return _Verdict(None, node_id, "lawful evidential terminal", evidential=True)

        obj = self.state.objects.get(node_id)
        if obj is None:
            return _Verdict(
                UNGROUNDED_CANONICAL_OBJECT,
                node_id,
                "evidence is never a direct terminal; a claim must say what it means",
            )
        if kind is SemanticKind.ASSUMPTION:
            return _Verdict(ASSUMPTION_IN_BASIS, node_id, "an assumption may ground nothing")
        if not object_is_current(obj):
            return _Verdict(DEAD_BASIS, node_id, "this basis object is no longer current")
        if obj.authority is not Authority.CANONICAL:
            return _Verdict(
                UNLAWFUL_BASIS_AUTHORITY,
                node_id,
                f"basis object authority is {obj.authority.value}; every node must be CANONICAL",
            )
        parents = derivation_parents_of(obj)
        if kind is SemanticKind.DECISION:
            if not parents:
                return _Verdict(None, node_id, "lawful authoritative terminal")
            return parents
        if kind in _INTERMEDIATE_KINDS:
            if not parents:
                return _Verdict(
                    UNGROUNDED_CANONICAL_OBJECT,
                    node_id,
                    f"{kind.value} is an intermediate with no further basis",
                )
            return parents
        return _Verdict(UNGROUNDED_CANONICAL_OBJECT, node_id, f"{kind.value} is never a basis")


def basis_defects(state: IntentState, obj: SemanticObject) -> tuple[BasisDefect, ...]:
    """Every way ``obj``'s declared basis is unlawful. Empty means lawful.

    Pure and deterministic: defects are deduplicated and ordered by ``(node_id, code)``.
    Liveness and authority gating of ``obj`` itself are the caller's concern.
    """
    walk = _Walk(state, active_judgment_ids(state.semantic), on_path={obj.id})
    verdicts = [walk.verdict(root) for root in derivation_parents_of(obj)]
    defects = {
        (v.node_id, v.code): BasisDefect(
            code=v.code, object_id=obj.id, node_id=v.node_id, reason=v.reason
        )
        for v in verdicts
        if v.code is not None
    }
    if (
        not defects
        and isinstance(obj, Constraint)
        and obj.facet in _EVIDENCE_REQUIRING_FACETS
        and not any(v.evidential for v in verdicts)
    ):
        defects[(obj.id, UNGROUNDED_CANONICAL_OBJECT)] = BasisDefect(
            code=UNGROUNDED_CANONICAL_OBJECT,
            object_id=obj.id,
            node_id=obj.id,
            reason=f"a {obj.facet} constraint must rest on a lawful evidential claim",
        )
    return tuple(defects[key] for key in sorted(defects))


def assert_lawful_basis(state: IntentState, obj: SemanticObject) -> None:
    """Refuse ``obj`` on its first basis defect."""
    defects = basis_defects(state, obj)
    if defects:
        first = defects[0]
        raise UnlawfulBasisError(
            f"{first.code}: {obj.id!r} rests on {first.node_id!r} -- {first.reason}"
        )
