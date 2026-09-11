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
* ``SUPERSEDE`` appends a ``SupersessionRecord`` (target must be currently active) and
  mints fresh issue versions for every address the target touched; the target remains
  readable (spec §19). Supersession ends the target's effect on the current view for
  every judgment kind — claims and bindings included — while addresses stay (spec §4.5,
  §7.2.1).

The epistemic state of a minted issue version is computed by ``semantic_view`` over the
post-transition state, so the version carries the interpretation current at minting.
"""

from __future__ import annotations

import hashlib

from foundry.domain.common import Provenance, SourceKind
from foundry.domain.derivation import DerivationEdge
from foundry.domain.events import (
    DerivationPayload,
    EventEnvelope,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
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
)
from foundry.domain.semantic_state import (
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
        case _:
            raise ValueError(f"{event.event_type} is not a semantic event")


# --- evidence, judgments, derivations ------------------------------------------


def _ingest_evidence(state: SemanticState, event: EventEnvelope) -> SemanticState:
    payload = event.payload
    if not isinstance(payload, EvidencePayload):
        raise ValueError("EVIDENCE_INGESTED requires EvidencePayload")
    evidence_id = payload.evidence.evidence_id
    if evidence_id in state.evidence:
        raise ValueError(f"evidence {evidence_id} already ingested")
    evidence = dict(state.evidence)
    evidence[evidence_id] = payload.evidence
    return _updated(state, evidence=evidence)


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
    applied = _updated(
        transitioned,
        applied_judgment_ids=(*state.applied_judgment_ids, judgment.judgment_id),
    )
    return _mint_issue_versions(applied, touched, event_id)


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


def _apply_create_address(
    state: SemanticState, judgment: SemanticJudgment, proposal: CreateAddressProposal
) -> tuple[SemanticState, tuple[str, ...]]:
    address_id = address_id_for(judgment.project_id, judgment.judgment_id)
    if address_id in state.addresses:
        raise ValueError(f"address {address_id} already exists")
    candidate = proposal.candidate
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
    bindings = dict(state.bindings)
    bindings[proposal.candidate.candidate_id] = proposal.address_id
    return _updated(state, bindings=bindings), ()


def _claim_provenance(judgment: SemanticJudgment, evidence_ids: tuple[str, ...]) -> Provenance:
    reasoner = judgment.reasoner
    return Provenance(
        source_kind=SourceKind.HUMAN if reasoner.is_human else SourceKind.SYSTEM,
        source_ref=f"{reasoner.provider}:{reasoner.model}",
        source_event_ids=evidence_ids,
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
        provenance=_claim_provenance(judgment, proposal.evidence_ids),
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


# --- issue versions -------------------------------------------------------------------


def _mint_issue_versions(
    state: SemanticState, touched: tuple[str, ...], event_id: str
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
        )
        versions[version_id] = version
        heads[address_id] = version_id
    return _updated(state, issue_versions=versions, issue_heads=heads)
