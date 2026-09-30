"""The scripted human authority of locus validation v6 (design §7.5).

Deterministic, and never the model. After dense T2 the runner clones the ledger once per
branch; in each clone the architect reads the production authority-work listing
(``application.authority_routing.list_authority_work``) and decides every PENDING correction
set it lists, one at a time, through the production decision API
(``decide_correction_set``), as of the ledger sequence it just read. The outcome is fixed per
branch before the run: AGREE in one, DECLINE in the other. There is no checkpoint schedule,
no eligibility rule and no model input: whatever the listing shows is decided, whole.
"""

from __future__ import annotations

from foundry.application.authority_routing import decide_correction_set, list_authority_work
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.common import FrozenModel
from foundry.experiments.locus_validation_v6.protocol import ARCHITECT, Branch

__all__ = ["HumanDecision", "decide_every_pending_set"]

_RATIONALE = {
    "AGREE": "the architect agrees with this correction as proposed",
    "DECLINE": "the architect declines this correction; the current meaning stands",
}


class HumanDecision(FrozenModel):
    work_id: str
    address_id: str
    outcome: Branch
    listed_at_sequence: int
    """The ``as_of_sequence`` of the listing that showed this set."""
    decided_at_sequence: int
    """The ledger sequence the decision was taken against (``expected_sequence``)."""
    status: str
    decision_event_id: str
    applied_judgment_ids: tuple[str, ...]


def decide_every_pending_set(
    governor: SemanticGovernor, outcome: Branch
) -> tuple[HumanDecision, ...]:
    """Decide every correction set the listing shows as PENDING, in listing order."""
    listed = list_authority_work(governor)
    decisions: list[HumanDecision] = []
    for item in listed.correction_sets:
        sequence = governor.state().last_sequence
        resolution = decide_correction_set(
            governor,
            work_id=item.work_id,
            outcome="AGREE" if outcome == "AGREE" else "DECLINE",
            human_actor_id=ARCHITECT,
            expected_sequence=sequence,
            rationale=_RATIONALE[outcome],
        )
        decisions.append(
            HumanDecision(
                work_id=item.work_id,
                address_id=item.address_id,
                outcome=outcome,
                listed_at_sequence=listed.as_of_sequence,
                decided_at_sequence=sequence,
                status=resolution.status,
                decision_event_id=resolution.decision_event_id,
                applied_judgment_ids=resolution.applied_judgment_ids,
            )
        )
    return tuple(decisions)
