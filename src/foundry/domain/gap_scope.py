"""Does a gap apply to an evaluated scope? One law for closure and readiness (IE2.5, R88).

Extracted verbatim from ``closure._gap_applies`` so readiness never grows a second definition:

* an ``IntentSynthesisGap`` states its own scope, and that is authoritative and checked first --
  falling through to the affected-object rule would let an unknown id there promote a
  scope-local gap into a project-wide one;
* a gap naming no objects is project-wide;
* otherwise it applies if any named object applies to the scope, and an id that names nothing
  in state counts as applying -- a gap about something unknown is never quietly dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.scope import scope_applies

if TYPE_CHECKING:
    from foundry.domain.gaps import Gap
    from foundry.domain.state import IntentState

__all__ = ["gap_applies"]


def gap_applies(state: IntentState, gap: Gap, scope: str) -> bool:
    if isinstance(gap, IntentSynthesisGap) and gap.scope != () and scope not in gap.scope:
        return False
    if gap.affected_object_ids == ():
        return True
    for object_id in gap.affected_object_ids:
        obj = state.objects.get(object_id)
        if obj is None:
            return True
        if scope_applies(tuple(obj.scope), scope):
            return True
    return False
