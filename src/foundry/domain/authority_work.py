"""Authority work: every judgment awaiting an authorized decision, discoverable by stable id.

Design 2026-09-30 (authority routing). The long-horizon run (``a0ee2f7``) showed a lawful
SUPERSEDE proposed off an experiment checkpoint staying pending for good: production held the
fact (``derive_view(...).pending_judgment_ids``) but offered nothing to find it by, so its
resolution depended on a harness choosing to look. This module names that fact.

It is a pure, deterministic **projection** of ``IntentState``: nothing is stored, no event is
added, no ledger is migrated, and replay of any ledger (old ones included) yields the same
work. The judgments stay the only semantic truth; a work item copies no meaning, only ids and
the context an authorized principal needs to decide.

* **Routing** (this module): which judgments need an authorized decision. A judgment whose
  latest admission holds it (``REQUIRE_SECOND_LENS`` / ``REQUIRE_HUMAN``) and that no applied
  active judgment ``agrees()`` with is pending (``semantic_view._pending_governance``). One
  work item stands for all pending judgments with the same kind and ``proposal_signature``:
  one agreement satisfies every one of them, so a repeated proposal never becomes a second
  obligation. ``required_resolution`` restates the existing admission law: a
  ``REQUIRE_HUMAN`` hold needs human authority; a ``REQUIRE_SECOND_LENS`` hold is satisfied
  by human authority or an independent lens (rules 4 and 7).
* **Decision** (``application.authority_routing``): an authenticated human's AGREE, a new
  judgment with the identical proposal, routed by unchanged admission.

A recorded judgment with no admission decision at all is **unrouted**, not pending: it can
never apply and nothing would ever surface it. It is reported apart, so pending by design is
never confused with lost.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Final, Literal

from foundry.domain.common import FrozenModel
from foundry.domain.handoff import judgment_address_ids
from foundry.domain.intent_view import derive_intent_view
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    JudgmentKind,
    SemanticJudgment,
    SupersedeProposal,
    proposal_signature,
)
from foundry.domain.state import IntentState

__all__ = [
    "AuthorityWorkItem",
    "AuthorityWorkQueue",
    "RequiredResolution",
    "authority_routing_findings",
    "authority_work",
    "work_id",
]

RequiredResolution = Literal["HUMAN_AUTHORITY", "HUMAN_AUTHORITY_OR_INDEPENDENT_LENS"]

_HUMAN_ONLY: Final = AdmissionRoute.REQUIRE_HUMAN
_CORRECTION_KINDS: Final = frozenset({JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPERSEDE})


class AuthorityWorkItem(FrozenModel):
    """One obligation: an authorized decision on one proposal signature."""

    work_id: str
    kind: str
    proposal_signature: tuple[str, ...]
    pending_judgment_ids: tuple[str, ...]
    """Every pending judgment carrying this signature, sorted. One AGREE satisfies all."""
    routes: tuple[str, ...]
    reasons: tuple[str, ...]
    required_resolution: RequiredResolution
    address_ids: tuple[str, ...]
    target_judgment_id: str | None
    """A SUPERSEDE's target judgment; ``None`` for every other kind."""
    target_claim_ids: tuple[str, ...]
    """The claims the target judgment created (what would stop being current)."""
    proposed_by: tuple[str, ...]
    invocation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    correction_context_judgment_ids: tuple[str, ...]
    """The other judgments of the same invocations that bear on the same addresses (the rest
    of a correction: its ASSERTs and sibling SUPERSEDEs), so a correction set is decided with
    its whole shape in view. Context only; never decided with this item."""


class AuthorityWorkQueue(FrozenModel):
    project_id: str
    as_of_sequence: int
    """The ledger sequence this projection was computed at: the version a decision names."""
    items: tuple[AuthorityWorkItem, ...]
    unrouted_judgment_ids: tuple[str, ...]


def work_id(project_id: str, judgment: SemanticJudgment) -> str:
    """Stable across replays and turns: the project, the kind and the proposal signature."""
    key = json.dumps(
        [project_id, judgment.proposal.kind.value, list(proposal_signature(judgment.proposal))],
        separators=(",", ":"),
    )
    return "AUTH-" + hashlib.sha256(key.encode()).hexdigest()[:24]


def _fingerprint(judgment: SemanticJudgment) -> str:
    r = judgment.reasoner
    return f"{r.provider}:{r.model}@{r.policy_version}"


def authority_work(state: IntentState) -> AuthorityWorkQueue:
    """Every pending authority obligation of ``state``, and every unrouted judgment."""
    semantic = state.semantic
    view = derive_intent_view(state)
    grouped: defaultdict[str, list[SemanticJudgment]] = defaultdict(list)
    for judgment_id in view.pending_judgment_ids:
        judgment = semantic.judgments[judgment_id]
        grouped[work_id(state.project_id, judgment)].append(judgment)

    items: list[AuthorityWorkItem] = []
    for wid, judgments in sorted(grouped.items()):
        judgments.sort(key=lambda j: j.judgment_id)
        first = judgments[0]
        admissions = [semantic.admissions[j.judgment_id] for j in judgments]
        routes = sorted({a.route.value for a in admissions})
        addresses = sorted({a for j in judgments for a in judgment_address_ids(semantic, j)})
        target = (
            first.proposal.target_judgment_id
            if isinstance(first.proposal, SupersedeProposal)
            else None
        )
        invocations = sorted({j.invocation_id for j in judgments})
        own = {j.judgment_id for j in judgments}
        context = sorted(
            other.judgment_id
            for other in semantic.judgments.values()
            if other.invocation_id in invocations
            and other.judgment_id not in own
            and other.proposal.kind in _CORRECTION_KINDS
            and judgment_address_ids(semantic, other) & set(addresses)
        )
        items.append(
            AuthorityWorkItem(
                work_id=wid,
                kind=first.proposal.kind.value,
                proposal_signature=proposal_signature(first.proposal),
                pending_judgment_ids=tuple(j.judgment_id for j in judgments),
                routes=tuple(routes),
                reasons=tuple(sorted({r for a in admissions for r in a.reasons})),
                required_resolution="HUMAN_AUTHORITY"
                if any(a.route is _HUMAN_ONLY for a in admissions)
                else "HUMAN_AUTHORITY_OR_INDEPENDENT_LENS",
                address_ids=tuple(addresses),
                target_judgment_id=target,
                target_claim_ids=tuple(
                    sorted(
                        c for c, x in semantic.claims.items() if x.created_by_judgment_id == target
                    )
                )
                if target is not None
                else (),
                proposed_by=tuple(sorted({_fingerprint(j) for j in judgments})),
                invocation_ids=tuple(invocations),
                evidence_ids=tuple(sorted({e for j in judgments for e in j.visible_evidence_ids})),
                correction_context_judgment_ids=tuple(context),
            )
        )
    unrouted = tuple(sorted(j for j in semantic.judgments if j not in semantic.admissions))
    return AuthorityWorkQueue(
        project_id=state.project_id,
        as_of_sequence=state.last_sequence,
        items=tuple(items),
        unrouted_judgment_ids=unrouted,
    )


def authority_routing_findings(state: IntentState, queue: AuthorityWorkQueue) -> tuple[str, ...]:
    """Pending never lost, never orphaned, never duplicated.

    Every pending judgment is in exactly one work item; every work item names only pending
    judgments of one kind and signature; no two items share an id."""
    pending = set(derive_intent_view(state).pending_judgment_ids)
    findings: list[str] = []
    seen: defaultdict[str, int] = defaultdict(int)
    for item in queue.items:
        for judgment_id in item.pending_judgment_ids:
            seen[judgment_id] += 1
            if judgment_id not in pending:
                findings.append(f"ORPHAN_WORK: {item.work_id} names {judgment_id}, not pending")
            elif work_id(state.project_id, state.semantic.judgments[judgment_id]) != item.work_id:
                findings.append(f"MIXED_WORK: {item.work_id} holds {judgment_id}")
    for judgment_id in sorted(pending):
        if seen[judgment_id] == 0:
            findings.append(f"INVISIBLE_PENDING: {judgment_id} has no authority work")
        elif seen[judgment_id] > 1:
            findings.append(f"DUPLICATE_WORK: {judgment_id} is in {seen[judgment_id]} items")
    ids = [item.work_id for item in queue.items]
    for wid in sorted({w for w in ids if ids.count(w) > 1}):
        findings.append(f"DUPLICATE_WORK_ID: {wid}")
    return tuple(findings)
