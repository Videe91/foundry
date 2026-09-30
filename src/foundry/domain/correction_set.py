"""Atomic correction sets: forming them from one response and routing them (authority v2).

Design 2026-09-30 (architecture Option B). A correction that needs authority is decided as one
unit, so a correcting claim is never current before, or without, the retirement it depends on.

**Grouping (deterministic, from judgment fields only).** Within one non-human response, every
address that at least one SUPERSEDE retires a claim at forms one correction set: every
ASSERT_CLAIM at that address plus every SUPERSEDE of a claim there. Judgments carry no
proposition id, so a correcting ASSERT cannot be told from a compatible one at the same address
without guessing; the whole address is held (the conservative choice the design allows). A
SUPPORT, and every ASSERT at an address no SUPERSEDE of the response touches, follows the
ordinary law. A SUPERSEDE whose target is unknown (ordinary admission refuses it
structurally) or bears on several addresses (a relation judgment, not a claim; it stays a v1
per-signature item) is left to the ordinary law.

**Routing.** Every member is first checked by the unchanged admission rules; one structural
refusal refuses the whole set (``CORRECTION_SET_INVALID``). A set equivalent to a DECLINED set
is refused as already declined (``CORRECTION_DECLINED``); one equivalent to a PENDING set is
refused as a repeat of it (``CORRECTION_SET_REPEAT``), so a repeated proposal never makes a
second obligation. Otherwise every member is held ``REQUIRE_HUMAN`` (``CORRECTION_SET_MEMBER``)
and the set is PENDING. Nothing of a set is ever applied here.

**Identities.** Instance: ``CSET-`` + sha256(project, invocation, address), one per address per
response. Equivalence (decline and repeat): ``CEQ-`` + sha256(project, address, sorted target
judgment ids, sorted sha256 of the CONTENT of the evidence the assertions cite). Content, not
evidence ids: a byte-identical section redelivered under a new evidence id is the same basis;
changed text, or a different target set, is a new one. Wording of the model's claims never
enters either key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Final

from foundry.domain.admission import AdmissionDecision, AdmissionPolicy, route_judgment
from foundry.domain.correction_set_state import CORRECTION_SET_MEMBER, CorrectionSetRecord
from foundry.domain.evidence import sha256_of_content
from foundry.domain.handoff import judgment_address_ids
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_state import SemanticState
from foundry.domain.state import IntentState

__all__ = [
    "CORRECTION_DECLINED",
    "CORRECTION_SET_INVALID",
    "CORRECTION_SET_MEMBER",
    "CORRECTION_SET_REPEAT",
    "correction_set_id",
    "equivalence_key",
    "form_correction_sets",
    "route_correction_set",
]

CORRECTION_SET_INVALID: Final = "CORRECTION_SET_INVALID"
CORRECTION_SET_REPEAT: Final = "CORRECTION_SET_REPEAT"
CORRECTION_DECLINED: Final = "CORRECTION_DECLINED"


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()[:24]


def correction_set_id(project_id: str, invocation_id: str, address_id: str) -> str:
    return "CSET-" + _digest(project_id, invocation_id, address_id)


def equivalence_key(
    project_id: str, address_id: str, targets: Sequence[str], hashes: Sequence[str]
) -> str:
    return "CEQ-" + _digest(project_id, address_id, sorted(targets), sorted(hashes))


def _supersede_address(semantic: SemanticState, judgment: SemanticJudgment) -> str | None:
    assert isinstance(judgment.proposal, SupersedeProposal)
    target = semantic.judgments.get(judgment.proposal.target_judgment_id)
    if target is None:
        return None
    addresses = judgment_address_ids(semantic, target)
    return next(iter(addresses)) if len(addresses) == 1 else None


def form_correction_sets(
    semantic: SemanticState, judgments: Sequence[SemanticJudgment]
) -> tuple[tuple[tuple[str, tuple[SemanticJudgment, ...]], ...], tuple[SemanticJudgment, ...]]:
    """``((address, members), ...)`` in first-seen address order, and every other judgment in
    its original order. Members are the address's assertions then its supersessions."""
    corrected: dict[str, list[SemanticJudgment]] = {}
    for j in judgments:
        if isinstance(j.proposal, SupersedeProposal):
            address = _supersede_address(semantic, j)
            if address is not None:
                corrected.setdefault(address, []).append(j)
    members: dict[str, list[SemanticJudgment]] = {a: [] for a in corrected}
    for j in judgments:
        if isinstance(j.proposal, AssertClaimProposal) and j.proposal.address_id in corrected:
            members[j.proposal.address_id].append(j)
    grouped = {j.judgment_id for ms in (*members.values(), *corrected.values()) for j in ms}
    sets = tuple((a, (*members[a], *corrected[a])) for a in corrected)
    return sets, tuple(j for j in judgments if j.judgment_id not in grouped)


def route_correction_set(
    state: IntentState,
    members: Sequence[SemanticJudgment],
    policy: AdmissionPolicy,
    address_id: str,
) -> tuple[tuple[AdmissionDecision, ...], CorrectionSetRecord | None]:
    """The decision of every member (all recorded already) and the PENDING record, if any."""
    semantic = state.semantic
    first = members[0]
    refusals = [
        f"{m.judgment_id}: {'; '.join(d.reasons)}"
        for m in members
        if (d := route_judgment(state, m, policy)).route is AdmissionRoute.REJECT
    ]

    def all_members(route: AdmissionRoute, *reasons: str) -> tuple[AdmissionDecision, ...]:
        return tuple(
            AdmissionDecision(judgment_id=m.judgment_id, route=route, reasons=reasons)
            for m in members
        )

    if refusals:
        return all_members(AdmissionRoute.REJECT, CORRECTION_SET_INVALID, *refusals), None
    assertions = tuple(m for m in members if isinstance(m.proposal, AssertClaimProposal))
    supersedes = tuple(m for m in members if isinstance(m.proposal, SupersedeProposal))
    targets = tuple(
        sorted({m.proposal.target_judgment_id for m in supersedes})  # type: ignore[union-attr]
    )
    hashes = tuple(
        sorted(
            {
                sha256_of_content(semantic.evidence[e].content)
                for m in assertions
                for e in m.proposal.evidence_ids  # type: ignore[union-attr]
                if e in semantic.evidence
            }
        )
    )
    key = equivalence_key(state.project_id, address_id, targets, hashes)
    for existing in sorted(semantic.correction_sets.values(), key=lambda r: r.correction_set_id):
        if existing.equivalence_key != key:
            continue
        if existing.status == "DECLINED":
            return all_members(
                AdmissionRoute.REJECT, CORRECTION_DECLINED, existing.correction_set_id
            ), None
        if existing.status == "PENDING":
            return all_members(
                AdmissionRoute.REJECT, CORRECTION_SET_REPEAT, existing.correction_set_id
            ), None
    set_id = correction_set_id(state.project_id, first.invocation_id, address_id)
    r = first.reasoner
    record = CorrectionSetRecord(
        correction_set_id=set_id,
        address_id=address_id,
        invocation_id=first.invocation_id,
        proposer=f"{r.provider}:{r.model}@{r.policy_version}",
        assertion_judgment_ids=tuple(m.judgment_id for m in assertions),
        supersede_judgment_ids=tuple(m.judgment_id for m in supersedes),
        target_judgment_ids=targets,
        basis_content_hashes=hashes,
        equivalence_key=key,
    )
    return all_members(AdmissionRoute.REQUIRE_HUMAN, CORRECTION_SET_MEMBER, set_id), record
