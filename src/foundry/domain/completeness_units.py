"""The minimal safe admission unit for semantic completeness (Intent Engine runtime reset).

A Call-2 response is no longer applied or refused whole. Each proposition the verifier judged
``COMPLETE`` may apply; each judged ``NOT_COMPLETE`` is held as a gap. But nothing semantically
atomic may be split, so the unit held is not the bare proposition. It is the smallest group
closed under two links, both read from judgment fields only:

* **one proposition** -- every judgment disposing of it (a proposition expressed by several
  claims is preserved or lost together);
* **one correction set** -- every judgment ``form_correction_sets`` puts in the same set (an
  address some SUPERSEDE of the response retires a claim at, with every ASSERT there), however
  the policy routes correction sets, so a correcting assertion is never applied without the
  retirement it depends on, or the reverse.

A unit applies only if every proposition in it is ``COMPLETE``. Judgments that dispose of no
proposition are never verified; they apply exactly as before unless a correction set ties them
to a held unit. Other links cannot arise within one response: every other judgment references
only addresses, claims and judgments already in state (admission refuses anything else), so
applying one unit never depends on another.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from foundry.domain.common import FrozenModel
from foundry.domain.correction_set import form_correction_sets
from foundry.domain.semantic_judgment import SemanticJudgment
from foundry.domain.semantic_state import SemanticState

__all__ = ["CompletenessUnit", "completeness_units"]


class CompletenessUnit(FrozenModel):
    """One group that applies whole or is held whole. Ids in response order."""

    proposition_ids: tuple[str, ...]
    judgment_ids: tuple[str, ...]


def completeness_units(
    semantic: SemanticState,
    judgments: Sequence[SemanticJudgment],
    disposed_by: Mapping[str, str],
) -> tuple[CompletenessUnit, ...]:
    """Partition the response into minimal safe units, in first-seen order."""
    parent = {j.judgment_id: j.judgment_id for j in judgments}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    first_of: dict[str, str] = {}
    for j in judgments:
        proposition = disposed_by.get(j.judgment_id)
        if proposition is None:
            continue
        if proposition in first_of:
            union(j.judgment_id, first_of[proposition])
        else:
            first_of[proposition] = j.judgment_id
    sets, _ = form_correction_sets(semantic, judgments)
    for _, correction in sets:
        for member in correction[1:]:
            union(member.judgment_id, correction[0].judgment_id)

    order: list[str] = []
    grouped: dict[str, list[SemanticJudgment]] = {}
    for j in judgments:
        root = find(j.judgment_id)
        if root not in grouped:
            order.append(root)
            grouped[root] = []
        grouped[root].append(j)
    units = []
    for root in order:
        members = grouped[root]
        propositions: list[str] = []
        for j in members:
            proposition = disposed_by.get(j.judgment_id)
            if proposition is not None and proposition not in propositions:
                propositions.append(proposition)
        units.append(
            CompletenessUnit(
                proposition_ids=tuple(propositions),
                judgment_ids=tuple(j.judgment_id for j in members),
            )
        )
    return tuple(units)
