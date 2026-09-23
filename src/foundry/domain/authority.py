"""The one shared AuthorityRecord coverage law (Slice-1 task T5).

Semantic Admission and Intent Synthesis both need to answer the same question:

    does this actor hold a live ``AuthorityRecord`` covering this target scope?

Before T5 that law lived privately inside ``domain/admission.py``. A second copy in the
synthesis router would have been an authority bug neither side's tests could catch, so
the law lives here once and both paths call it.

Why a separate leaf module
--------------------------
``admission.py`` depends on ``IntentState``, and ``IntentState`` now reaches Intent
Synthesis state and types. An ``intent_synthesis -> admission`` import would therefore
run the wrong way and risk a cycle. ``domain/authority.py`` is the common leaf both
governance paths may depend on, and it imports only leaf domain primitives.

``IntentState`` is imported under ``TYPE_CHECKING`` for exactly that reason: the runtime
body touches only ``state.objects``, so no runtime edge is created and typing stays
precise (never ``Any``).

What this module does NOT decide
--------------------------------
It does not decide whether the actor is human. That stays with the caller: admission
reads it from a ``ReasonerFingerprint``, and synthesis will read it from its own
authorship contract. The helper never inspects a ``SemanticJudgment`` or a fingerprint.

Behaviour-preserving: every rule below is today's admission law, unchanged. No
``Authority`` ordering is introduced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from foundry.domain.common import Authority, LifecycleStatus
from foundry.domain.semantic import AuthorityRecord

if TYPE_CHECKING:
    from foundry.domain.state import IntentState

__all__ = [
    "authority_record_is_live",
    "covering_authority_record",
    "record_covers_scope",
]

_DEAD_AUTHORITIES: Final[frozenset[Authority]] = frozenset(
    {Authority.REJECTED, Authority.SUPERSEDED}
)


def authority_record_is_live(record: AuthorityRecord) -> bool:
    """The single liveness rule: ACTIVE lifecycle and not REJECTED/SUPERSEDED authority.

    Re-exported from ``domain.admission`` so the eight existing call sites keep working;
    there is exactly one implementation, never a second body.
    """
    return record.lifecycle is LifecycleStatus.ACTIVE and record.authority not in _DEAD_AUTHORITIES


def record_covers_scope(record: AuthorityRecord, target_scope: tuple[str, ...] | None) -> bool:
    """Does ``record``'s authority reach ``target_scope``? Today's law, unchanged.

    * a project-wide record (``scope == ()``) covers every target, including ``None``;
    * ``target_scope is None`` means the judgment has no single target — only
      project-wide authority covers it, which is what keeps relation and supersession
      kinds requiring project-wide authority;
    * otherwise coverage is **intersection**, not containment. A record scoped
      ``("billing", "security")`` covers a target ``("security", "identity")``. This is
      deliberately NOT the subset rule used by the C21 replacement-scope guard —
      authority coverage and replacement applicability are different concepts, and
      conflating them would silently change admission outcomes.

    A scoped record does not cover a project-wide target ``()``, which falls out of the
    intersection being empty.
    """
    if record.scope == ():
        return True
    if target_scope is None:
        return False
    return bool(frozenset(record.scope) & frozenset(target_scope))


def covering_authority_record(
    state: IntentState,
    *,
    actor_id: str,
    target_scope: tuple[str, ...] | None,
) -> AuthorityRecord | None:
    """The live ``AuthorityRecord`` by which ``actor_id`` covers ``target_scope``, if any.

    Selection is deterministic: objects are scanned in sorted id order and the first
    match wins, so replay and pure routing never depend on how a mapping happened to be
    built. Where several records match, the lexically earliest object id is returned.

    An empty ``actor_id`` fails closed with ``ValueError`` rather than matching nothing:
    silently returning ``None`` would disguise a caller bug as a plausible "no authority"
    answer.
    """
    if not actor_id:
        raise ValueError("actor_id must be non-empty")
    for _, obj in sorted(state.objects.items()):
        if (
            isinstance(obj, AuthorityRecord)
            and obj.authorized_by == actor_id
            and authority_record_is_live(obj)
            and record_covers_scope(obj, target_scope)
        ):
            return obj
    return None
