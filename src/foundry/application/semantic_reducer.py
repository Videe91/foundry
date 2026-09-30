"""Governed semantic state transitions (Intent Intelligence v2, plan §5.4; spec §22).

Laws enforced here, independent of what any reasoner returned:

* Only an admission whose ``route is AdmissionRoute.APPLY`` mutates addresses, claims,
  bindings, equivalences, conflicts or supersession. Every other route records the
  decision and nothing else (spec §22.1, §22.11).
* Nothing is ever removed or rewritten. Addresses, claims, judgments, issue versions
  and derivation edges only accumulate (spec §22.2, §22.10).
* IDs minted by the reducer derive from ``(project_id, judgment_id)`` or
  ``(event_id, address_id)`` so replay reproduces identical state (spec §22.14).
* Every referenced evidence, address, claim and judgment must exist (spec §22.6).
* ``EQUIVALENT`` never copies or moves claims; it appends a record and the current
  view unions the locus (spec §7.2.1, §12).
* ``SUPPORTS_CLAIM`` appends a ``ClaimSupportRecord`` for a LIVE claim citing existing
  evidence and mints a fresh issue version at the claim's address. It never rewrites
  ``SemanticClaim.evidence_ids``; the view derives effective evidence from the claim
  plus its active support records (spec §12).
* ``SUPERSEDE`` appends a ``SupersessionRecord`` (target must be currently active) and
  mints fresh issue versions for every address the target touched; the target remains
  readable (spec §19). Supersession ends the target's effect on the current view for
  every judgment kind — claims and bindings included — while addresses stay (spec §4.5,
  §7.2.1).
* A candidate bound by an ACTIVE ``CREATE_ADDRESS`` / ``BIND_TO_ADDRESS`` judgment
  cannot be bound again — by anyone — until that judgment is superseded. Referential
  identity ends only when the binding judgment is superseded; "last writer wins" is
  never how a binding changes (spec §4.5, §20.1, §21 #10). ``SemanticState.bindings``
  is candidate -> address for the LATEST ADMITTED binding of each candidate: it is
  only ever written when no active binding exists, so a superseded binding may be
  followed by a new one. The authority for the CURRENT interpretation is
  ``derive_view(state).active_bindings``, which follows active judgments only.

The epistemic state of a minted issue version is computed by ``semantic_view`` over the
post-transition state, so the version carries the interpretation current at minting.
"""

from __future__ import annotations

import hashlib

from foundry.domain.common import Provenance, SourceKind
from foundry.domain.correction_set_state import CORRECTION_SET_MEMBER, CorrectionSetRecord
from foundry.domain.derivation import DerivationEdge
from foundry.domain.events import (
    CorrectionSetDecidedPayload,
    CorrectionSetProposedPayload,
    DerivationPayload,
    EventEnvelope,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_identity import (
    SemanticAddress,
    SemanticClaim,
    SemanticIssueVersion,
)
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    DistinctProposal,
    EquivalentProposal,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_state import (
    ClaimSupportRecord,
    ConflictRecord,
    EquivalenceRecord,
    SemanticState,
    SupersessionRecord,
)
from foundry.domain.semantic_view import active_judgment_ids, derive_view


def _minted_id(prefix: str, project_id: str, judgment_id: str) -> str:
    digest = hashlib.sha256(f"{project_id}|{judgment_id}".encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def address_id_for(project_id: str, judgment_id: str) -> str:
    return _minted_id("ADDR", project_id, judgment_id)


def claim_id_for(project_id: str, judgment_id: str) -> str:
    return _minted_id("CLAIM", project_id, judgment_id)


def _updated(state: SemanticState, **changes: object) -> SemanticState:
    """Rebuild through validation so every mapping stays a frozen proxy."""
    return SemanticState.model_validate({**dict(state), **changes})


def reduce_semantic_event(state: SemanticState, stored: StoredEvent) -> SemanticState:
    event = stored.event
    match event.event_type:
        case EventType.EVIDENCE_INGESTED:
            return _ingest_evidence(state, event)
        case EventType.SEMANTIC_JUDGMENT_RECORDED:
            return _record_judgment(state, event)
        case EventType.SEMANTIC_ADMISSION_DECIDED:
            return _decide_admission(state, event)
        case EventType.DERIVATION_RECORDED:
            return _record_derivation(state, event)
        case EventType.CORRECTION_SET_PROPOSED:
            return _propose_correction_set(state, event)
        case EventType.CORRECTION_SET_DECIDED:
            return _decide_correction_set(state, event)
        case _:
            raise ValueError(f"{event.event_type} is not a semantic event")


# --- atomic correction sets (authority v2) ----------------------------------------


def _propose_correction_set(state: SemanticState, event: EventEnvelope) -> SemanticState:
    payload = event.payload
    if not isinstance(payload, CorrectionSetProposedPayload):
        raise ValueError("CORRECTION_SET_PROPOSED requires CorrectionSetProposedPayload")
    record = payload.correction_set
    if record.status != "PENDING":
        raise ValueError("a correction set is proposed PENDING")
    if record.correction_set_id in state.correction_sets:
        raise ValueError(f"correction set {record.correction_set_id} already proposed")
    in_other = {m for r in state.correction_sets.values() for m in r.member_judgment_ids}
    for member in record.member_judgment_ids:
        judgment = state.judgments.get(member)
        admission = state.admissions.get(member)
        if judgment is None or admission is None:
            raise ValueError(f"correction set member {member} is not recorded and admitted")
        if member in state.applied_judgment_ids or member in in_other:
            raise ValueError(f"correction set member {member} is applied or in another set")
        if admission.route is not AdmissionRoute.REQUIRE_HUMAN or admission.reasons[:1] != (
            CORRECTION_SET_MEMBER,
        ):
            raise ValueError(f"correction set member {member} is not held as a member")
    sets = dict(state.correction_sets)
    sets[record.correction_set_id] = record
    return _updated(state, correction_sets=sets)


def _decide_correction_set(state: SemanticState, event: EventEnvelope) -> SemanticState:
    payload = event.payload
    if not isinstance(payload, CorrectionSetDecidedPayload):
        raise ValueError("CORRECTION_SET_DECIDED requires CorrectionSetDecidedPayload")
    record = state.correction_sets.get(payload.correction_set_id)
    if record is None:
        raise ValueError(f"unknown correction set {payload.correction_set_id}")
    if record.status != "PENDING":
        raise ValueError(f"correction set {record.correction_set_id} is already {record.status}")
    decided = record.model_copy(
        update={
            "status": "AGREED" if payload.outcome == "AGREE" else "DECLINED",
            "decided_by": payload.decided_by,
            "decision_event_id": event.event_id,
            "authority_record_id": payload.authority_record_id,
            "rationale": payload.rationale,
        }
    )
    sets = dict(state.correction_sets)
    sets[record.correction_set_id] = decided
    transitioned = _updated(state, correction_sets=sets)
    if payload.outcome == "DECLINE":
        return transitioned
    return _apply_correction_set(transitioned, record, event.event_id)


def _apply_correction_set(
    state: SemanticState, record: CorrectionSetRecord, event_id: str
) -> SemanticState:
    """AGREE: every member applies inside this one event, or the event is refused whole.

    One issue version per touched address, minted once over the FINAL state, so history
    never holds a snapshot of a partly applied set. The version names the last member (a
    SUPERSEDE, as for any supersession) and is recorded DERIVED_FROM every other member, so
    the ordinary staleness law marks it stale if any member's effect later ends."""
    applied = state
    touched: set[str] = set()
    for member in record.member_judgment_ids:
        applied, member_touched = _transition(applied, state.judgments[member], event_id)
        touched.update(member_touched)
    creator = record.member_judgment_ids[-1]
    minted = _mint_issue_versions(
        applied, _expand_to_loci(tuple(sorted(touched)), state, applied), event_id, creator
    )
    new_versions = sorted(set(minted.issue_versions) - set(state.issue_versions))
    edges = tuple(
        DerivationEdge(child_id=version_id, parent_id=member, recorded_by_event_id=event_id)
        for version_id in new_versions
        for member in record.member_judgment_ids[:-1]
    )
    return _updated(minted, derivations=(*minted.derivations, *edges))


# --- evidence, judgments, derivations ------------------------------------------


def _ingest_evidence(state: SemanticState, event: EventEnvelope) -> SemanticState:
    payload = event.payload
    if not isinstance(payload, EvidencePayload):
        raise ValueError("EVIDENCE_INGESTED requires EvidencePayload")
    item = payload.evidence
    evidence_id = item.evidence_id
    if evidence_id in state.evidence:
        raise ValueError(f"evidence {evidence_id} already ingested")
    _check_evidence_lineage(state, item)
    evidence = dict(state.evidence)
    evidence[evidence_id] = item
    return _updated(state, evidence=evidence)


def _check_evidence_lineage(state: SemanticState, item: EvidenceItem) -> None:
    """State-aware evidence lineage rules (spec §15): one linear chain per artifact.

    The model validator on ``EvidenceItem`` only checks shape; it cannot see state.
    Lineage is deterministic data and carries no semantic authority — nothing here
    touches claims or judgments.
    """
    target_id = item.supersedes_evidence_id
    if target_id is None:
        return
    target = state.evidence.get(target_id)
    if target is None:
        raise ValueError(f"evidence {item.evidence_id} supersedes unknown evidence {target_id}")
    if target.artifact_ref != item.artifact_ref:
        raise ValueError(
            f"evidence {item.evidence_id} (artifact_ref {item.artifact_ref!r}) cannot supersede "
            f"evidence {target_id} (artifact_ref {target.artifact_ref!r}): artifact_ref differs"
        )
    for existing in state.evidence.values():
        if existing.supersedes_evidence_id == target_id:
            raise ValueError(
                f"evidence {target_id} is already superseded by {existing.evidence_id}; "
                f"{item.evidence_id} cannot supersede it again"
            )


def _record_judgment(state: SemanticState, event: EventEnvelope) -> SemanticState:
    payload = event.payload
    if not isinstance(payload, SemanticJudgmentPayload):
        raise ValueError("SEMANTIC_JUDGMENT_RECORDED requires SemanticJudgmentPayload")
    judgment = payload.judgment
    if judgment.judgment_id in state.judgments:
        raise ValueError(f"judgment {judgment.judgment_id} already recorded")
    judgments = dict(state.judgments)
    judgments[judgment.judgment_id] = judgment
    return _updated(state, judgments=judgments)


def _record_derivation(state: SemanticState, event: EventEnvelope) -> SemanticState:
    payload = event.payload
    if not isinstance(payload, DerivationPayload):
        raise ValueError("DERIVATION_RECORDED requires DerivationPayload")
    edge = DerivationEdge(
        child_id=payload.child_id,
        parent_id=payload.parent_id,
        recorded_by_event_id=event.event_id,
    )
    return _updated(state, derivations=(*state.derivations, edge))


# --- admission ----------------------------------------------------------------------


def _decide_admission(state: SemanticState, event: EventEnvelope) -> SemanticState:
    payload = event.payload
    if not isinstance(payload, SemanticAdmissionPayload):
        raise ValueError("SEMANTIC_ADMISSION_DECIDED requires SemanticAdmissionPayload")
    judgment = state.judgments.get(payload.judgment_id)
    if judgment is None:
        raise ValueError(f"admission references unknown judgment {payload.judgment_id}")
    if payload.judgment_id in state.applied_judgment_ids:
        raise ValueError(f"judgment {payload.judgment_id} already applied")
    admissions = dict(state.admissions)
    admissions[payload.judgment_id] = payload
    recorded = _updated(state, admissions=admissions)
    if payload.route is not AdmissionRoute.APPLY:
        return recorded
    return _apply(recorded, judgment, event.event_id)


def _apply(state: SemanticState, judgment: SemanticJudgment, event_id: str) -> SemanticState:
    applied, touched = _transition(state, judgment, event_id)
    if isinstance(
        judgment.proposal, EquivalentProposal | ConflictsWithProposal | SupersedeProposal
    ):
        touched = _expand_to_loci(touched, state, applied)
    return _mint_issue_versions(applied, touched, event_id, judgment.judgment_id)


def _transition(
    state: SemanticState, judgment: SemanticJudgment, event_id: str
) -> tuple[SemanticState, tuple[str, ...]]:
    """Apply one judgment's effect and record it applied; mint nothing (the caller does)."""
    if judgment.judgment_id in state.applied_judgment_ids:
        raise ValueError(f"judgment {judgment.judgment_id} already applied")
    proposal = judgment.proposal
    match proposal:
        case CreateAddressProposal():
            transitioned, touched = _apply_create_address(state, judgment, proposal)
        case BindToAddressProposal():
            transitioned, touched = _apply_bind(state, proposal)
        case AssertClaimProposal():
            transitioned, touched = _apply_assert_claim(state, judgment, proposal)
        case EquivalentProposal():
            transitioned, touched = _apply_equivalent(state, judgment, proposal)
        case DistinctProposal():
            transitioned, touched = _apply_distinct(state, proposal)
        case ConflictsWithProposal():
            transitioned, touched = _apply_conflict(state, judgment, proposal)
        case SupersedeProposal():
            transitioned, touched = _apply_supersede(state, judgment, proposal, event_id)
        case SupportsClaimProposal():
            transitioned, touched = _apply_support_claim(state, judgment, proposal, event_id)
    applied = _updated(
        transitioned,
        applied_judgment_ids=(*state.applied_judgment_ids, judgment.judgment_id),
    )
    return applied, touched


def _expand_to_loci(
    touched: tuple[str, ...], before: SemanticState, after: SemanticState
) -> tuple[str, ...]:
    """Widen ``touched`` to every member of its loci under BOTH the pre- and
    post-transition views, so no head can disagree with the current interpretation
    (spec §18: the head IS the current interpretation)."""
    expanded = set(touched)
    for state in (before, after):
        members = {
            a: locus.address_ids for locus in derive_view(state).loci for a in locus.address_ids
        }
        for address_id in touched:
            expanded.update(members.get(address_id, ()))
    return tuple(sorted(expanded))


def _require_address(state: SemanticState, address_id: str) -> SemanticAddress:
    address = state.addresses.get(address_id)
    if address is None:
        raise ValueError(f"unknown address {address_id}")
    return address


def _require_claim(state: SemanticState, claim_id: str) -> SemanticClaim:
    claim = state.claims.get(claim_id)
    if claim is None:
        raise ValueError(f"unknown claim {claim_id}")
    return claim


def _active_binding_judgment(state: SemanticState, candidate_id: str) -> str | None:
    """The active applied CREATE/BIND judgment currently binding ``candidate_id``, if any.

    Mirrors ``semantic_view._active_bindings`` (applied order, active judgments only)
    and ``admission._active_binding_judgment``; admission refuses what this refuses.
    """
    active = active_judgment_ids(state)
    bound_by: str | None = None
    for judgment_id in state.applied_judgment_ids:
        prior = state.judgments.get(judgment_id)
        if prior is None or judgment_id not in active:
            continue
        p = prior.proposal
        if (
            isinstance(p, CreateAddressProposal | BindToAddressProposal)
            and p.candidate.candidate_id == candidate_id
        ):
            bound_by = judgment_id
    return bound_by


def _require_unbound(state: SemanticState, candidate_id: str) -> None:
    bound_by = _active_binding_judgment(state, candidate_id)
    if bound_by is not None:
        raise ValueError(
            f"candidate {candidate_id} already bound by {bound_by}; supersede it first"
        )


def _apply_create_address(
    state: SemanticState, judgment: SemanticJudgment, proposal: CreateAddressProposal
) -> tuple[SemanticState, tuple[str, ...]]:
    address_id = address_id_for(judgment.project_id, judgment.judgment_id)
    if address_id in state.addresses:
        raise ValueError(f"address {address_id} already exists")
    candidate = proposal.candidate
    _require_unbound(state, candidate.candidate_id)
    address = SemanticAddress(
        address_id=address_id,
        project_id=judgment.project_id,
        subject=candidate.subject,
        facet=candidate.facet,
        scope=candidate.scope,
        created_by_judgment_id=judgment.judgment_id,
    )
    addresses = dict(state.addresses)
    addresses[address_id] = address
    bindings = dict(state.bindings)
    bindings[candidate.candidate_id] = address_id
    return _updated(state, addresses=addresses, bindings=bindings), (address_id,)


def _apply_bind(
    state: SemanticState, proposal: BindToAddressProposal
) -> tuple[SemanticState, tuple[str, ...]]:
    _require_address(state, proposal.address_id)
    _require_unbound(state, proposal.candidate.candidate_id)
    bindings = dict(state.bindings)
    bindings[proposal.candidate.candidate_id] = proposal.address_id
    return _updated(state, bindings=bindings), ()


def _claim_provenance(judgment: SemanticJudgment) -> Provenance:
    """Provenance of the asserting reasoner. Never carries EvidenceItem IDs.

    ``Provenance.source_event_ids`` means EventEnvelope IDs only. The evidence edge
    of a claim is the explicit ``SemanticClaim.evidence_ids`` relationship (EvidenceItem
    IDs). No ingestion-event index exists at claim construction time in this slice, so
    the field is left empty rather than filled with identifiers of the wrong type.
    """
    reasoner = judgment.reasoner
    return Provenance(
        source_kind=SourceKind.HUMAN if reasoner.is_human else SourceKind.SYSTEM,
        source_ref=f"{reasoner.provider}:{reasoner.model}",
        source_event_ids=(),
    )


def _apply_assert_claim(
    state: SemanticState, judgment: SemanticJudgment, proposal: AssertClaimProposal
) -> tuple[SemanticState, tuple[str, ...]]:
    _require_address(state, proposal.address_id)
    for evidence_id in proposal.evidence_ids:
        if evidence_id not in state.evidence:
            raise ValueError(f"unknown evidence {evidence_id}")
    claim_id = claim_id_for(judgment.project_id, judgment.judgment_id)
    if claim_id in state.claims:
        raise ValueError(f"claim {claim_id} already exists")
    claim = SemanticClaim(
        claim_id=claim_id,
        project_id=judgment.project_id,
        address_id=proposal.address_id,
        predicate=proposal.predicate,
        value=proposal.value,
        evidence_ids=proposal.evidence_ids,
        authority=proposal.authority,
        provenance=_claim_provenance(judgment),
        created_by_judgment_id=judgment.judgment_id,
    )
    claims = dict(state.claims)
    claims[claim_id] = claim
    return _updated(state, claims=claims), (proposal.address_id,)


def _apply_equivalent(
    state: SemanticState, judgment: SemanticJudgment, proposal: EquivalentProposal
) -> tuple[SemanticState, tuple[str, ...]]:
    _require_address(state, proposal.address_a)
    _require_address(state, proposal.address_b)
    record = EquivalenceRecord(
        judgment_id=judgment.judgment_id,
        address_a=proposal.address_a,
        address_b=proposal.address_b,
    )
    transitioned = _updated(state, equivalences=(*state.equivalences, record))
    return transitioned, (proposal.address_a, proposal.address_b)


def _apply_distinct(
    state: SemanticState, proposal: DistinctProposal
) -> tuple[SemanticState, tuple[str, ...]]:
    _require_address(state, proposal.address_a)
    _require_address(state, proposal.address_b)
    return state, ()


def _apply_conflict(
    state: SemanticState, judgment: SemanticJudgment, proposal: ConflictsWithProposal
) -> tuple[SemanticState, tuple[str, ...]]:
    claim_a = _require_claim(state, proposal.claim_a)
    claim_b = _require_claim(state, proposal.claim_b)
    view = derive_view(state)
    representative_id = view.representatives[claim_a.address_id]
    locus = next(locus for locus in view.loci if locus.representative_id == representative_id)
    if proposal.claim_a not in locus.claim_ids or proposal.claim_b not in locus.claim_ids:
        raise ValueError(
            f"claims {proposal.claim_a} and {proposal.claim_b} are not live claims "
            "sharing a representative locus"
        )
    record = ConflictRecord(
        judgment_id=judgment.judgment_id, claim_a=proposal.claim_a, claim_b=proposal.claim_b
    )
    transitioned = _updated(state, conflicts=(*state.conflicts, record))
    return transitioned, (claim_a.address_id, claim_b.address_id)


def _apply_supersede(
    state: SemanticState, judgment: SemanticJudgment, proposal: SupersedeProposal, event_id: str
) -> tuple[SemanticState, tuple[str, ...]]:
    target_id = proposal.target_judgment_id
    if target_id not in state.applied_judgment_ids:
        raise ValueError(f"supersede target {target_id} is not an applied judgment")
    if target_id not in active_judgment_ids(state):
        raise ValueError(f"supersede target {target_id} is not currently active")
    record = SupersessionRecord(
        target_judgment_id=target_id,
        superseding_judgment_id=judgment.judgment_id,
        recorded_by_event_id=event_id,
    )
    transitioned = _updated(state, supersessions=(*state.supersessions, record))
    return transitioned, _touched_addresses(state, state.judgments[target_id])


def _apply_support_claim(
    state: SemanticState,
    judgment: SemanticJudgment,
    proposal: SupportsClaimProposal,
    event_id: str,
) -> tuple[SemanticState, tuple[str, ...]]:
    """Append a support record for a live claim. ``claims[...]`` is never written."""
    claim = _require_claim(state, proposal.claim_id)
    if claim.created_by_judgment_id not in active_judgment_ids(state):
        raise ValueError(f"claim {claim.claim_id} is not live")
    for evidence_id in proposal.evidence_ids:
        if evidence_id not in state.evidence:
            raise ValueError(f"unknown evidence {evidence_id}")
    record = ClaimSupportRecord(
        judgment_id=judgment.judgment_id,
        claim_id=claim.claim_id,
        evidence_ids=proposal.evidence_ids,
        recorded_by_event_id=event_id,
    )
    transitioned = _updated(state, claim_supports=(*state.claim_supports, record))
    return transitioned, (claim.address_id,)


def _touched_addresses(state: SemanticState, judgment: SemanticJudgment) -> tuple[str, ...]:
    """Addresses whose interpretation an applied judgment bears on."""
    proposal = judgment.proposal
    match proposal:
        case CreateAddressProposal():
            return (address_id_for(judgment.project_id, judgment.judgment_id),)
        case BindToAddressProposal() | AssertClaimProposal():
            return (proposal.address_id,)
        case EquivalentProposal() | DistinctProposal():
            return (proposal.address_a, proposal.address_b)
        case ConflictsWithProposal():
            return (
                state.claims[proposal.claim_a].address_id,
                state.claims[proposal.claim_b].address_id,
            )
        case SupersedeProposal():
            return _touched_addresses(state, state.judgments[proposal.target_judgment_id])
        case SupportsClaimProposal():
            return (state.claims[proposal.claim_id].address_id,)


# --- issue versions -------------------------------------------------------------------


def _mint_issue_versions(
    state: SemanticState, touched: tuple[str, ...], event_id: str, judgment_id: str
) -> SemanticState:
    """Mint one immutable issue version per touched address and move its head.

    ``epistemic_state`` is the LOCUS state under the post-transition view, while
    ``claim_ids`` are only the address's own active claims.
    """
    if not touched:
        return state
    view = derive_view(state)
    loci_by_address = {address_id: locus for locus in view.loci for address_id in locus.address_ids}
    versions = dict(state.issue_versions)
    heads = dict(state.issue_heads)
    for address_id in sorted(set(touched)):
        locus = loci_by_address[address_id]
        version_id = f"{event_id}:{address_id}"
        if version_id in versions:
            raise ValueError(f"issue version {version_id} already exists")
        version = SemanticIssueVersion(
            version_id=version_id,
            project_id=state.addresses[address_id].project_id,
            address_id=address_id,
            claim_ids=tuple(
                claim_id
                for claim_id in locus.claim_ids
                if state.claims[claim_id].address_id == address_id
            ),
            epistemic_state=locus.epistemic_state,
            equivalent_address_ids=tuple(a for a in locus.address_ids if a != address_id),
            supersedes_version_id=heads.get(address_id),
            created_by_event_id=event_id,
            created_by_judgment_id=judgment_id,
        )
        versions[version_id] = version
        heads[address_id] = version_id
    return _updated(state, issue_versions=versions, issue_heads=heads)
