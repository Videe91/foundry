"""Authority routing: find pending authority work and record an authorized decision.

Design 2026-09-30 (``AUTHORITY_ROUTING_VERSION``). Two operations, provider- and transport-
neutral, over the existing governor:

* ``list_authority_work`` reads. It writes nothing and decides nothing: it is
  ``domain.authority_work.authority_work`` over replayed state.
* ``agree`` records one authenticated human's AGREE on one work item: a new judgment carrying
  the item's proposal unchanged, under the human's own fingerprint, routed by the unchanged
  admission policy. Admission, not this module, decides whether it applies (human authority
  with a covering ``AuthorityRecord``; otherwise the existing lens rules). It works at any
  time, for any pending item: nothing depends on the turn or checkpoint the proposal came
  from.

Nothing here automates a decision, lets a model approve (the AGREE's reasoner is always the
named human, and the actor must be a ``human://`` principal), or approves in bulk: one call,
one item. There is no DISAGREE: the domain has no decline decision (a declined or unanswered
proposal stays pending, ``semantic_view``), and inventing one is an architecture decision this
module does not make.

Concurrency uses the ledger sequence the caller decided against (``expected_sequence``): if
anything was appended since, the decision is refused before anything is written
(``StaleAuthorityDecision``); a decision on an item that is no longer pending is refused
(``AuthorityWorkNotPending``). Both leave the ledger untouched, so a repeated or racing AGREE
cannot land twice.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final

from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.authority_work import AuthorityWorkQueue, authority_work
from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment

__all__ = [
    "AUTHORITY_ROUTING_VERSION",
    "AuthorityResolution",
    "AuthorityWorkNotPending",
    "StaleAuthorityDecision",
    "agree",
    "list_authority_work",
]

AUTHORITY_ROUTING_VERSION: Final = "ie2-authority-routing-v1"
"""The protocol identity an AGREE carries as its fingerprint's policy version."""

_HUMAN_PREFIX: Final = "human://"


class StaleAuthorityDecision(RuntimeError):
    """The ledger moved after the decision was taken; nothing was written."""


class AuthorityWorkNotPending(RuntimeError):
    """The item is not pending (resolved already, or never existed); nothing was written."""


class AuthorityResolution(FrozenModel):
    work_id: str
    agree_judgment_id: str
    route: str
    reasons: tuple[str, ...]
    resolved: bool
    """True when no judgment of the item is pending any more after the AGREE."""


def list_authority_work(governor: SemanticGovernor) -> AuthorityWorkQueue:
    return authority_work(governor.state())


def agree(
    governor: SemanticGovernor,
    *,
    work_id: str,
    human_actor_id: str,
    expected_sequence: int,
    rationale: str,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> AuthorityResolution:
    """Record ``human_actor_id``'s AGREE on ``work_id`` as of ``expected_sequence``."""
    if not human_actor_id.startswith(_HUMAN_PREFIX):
        raise ValueError(f"only a human principal ({_HUMAN_PREFIX}...) may decide authority")
    if not rationale.strip():
        raise ValueError("an authority decision records its rationale")
    state = governor.state()
    if state.last_sequence != expected_sequence:
        raise StaleAuthorityDecision(
            f"decided at sequence {expected_sequence}, the ledger is at {state.last_sequence}"
        )
    queue = authority_work(state)
    item = next((i for i in queue.items if i.work_id == work_id), None)
    if item is None:
        raise AuthorityWorkNotPending(f"{work_id} is not pending authority work")
    pending = state.semantic.judgments[item.pending_judgment_ids[0]]
    judgment = SemanticJudgment(
        judgment_id=id_factory("judgment"),
        project_id=pending.project_id,
        proposal=pending.proposal,
        visible_evidence_ids=(),
        rationale=f"AGREE {work_id}: {rationale}",
        reasoner=ReasonerFingerprint(
            provider="human", model=human_actor_id, policy_version=AUTHORITY_ROUTING_VERSION
        ),
        invocation_id=id_factory("authorization"),
        proposed_at=clock(),
    )
    decision = governor.submit(judgment, human_actor_id=human_actor_id)
    after = authority_work(governor.state())
    return AuthorityResolution(
        work_id=work_id,
        agree_judgment_id=judgment.judgment_id,
        route=decision.route.value,
        reasons=tuple(decision.reasons),
        resolved=all(i.work_id != work_id for i in after.items),
    )
