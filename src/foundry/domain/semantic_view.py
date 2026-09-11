"""Current semantic interpretation, derived — never stored (spec §4.5, §7.2.1, §8).

``derive_view`` folds the ACTIVE admitted judgments over the append-only
``SemanticState`` into a replayable ``CurrentSemanticView``:

* addresses are grouped into loci by union-find over active ``EQUIVALENT`` records;
  the representative of a locus is its minimum ``address_id``;
* a locus' claims are the union of the ACTIVE claims at its member addresses — a
  claim counts only while the ``ASSERT_CLAIM`` judgment that created it is active;
  nothing is copied or moved in the durable state;
* ``active_bindings`` holds candidate -> address for bindings whose creating
  ``CREATE_ADDRESS`` / ``BIND_TO_ADDRESS`` judgment is active, in applied order;
* epistemic state per locus: no claims -> OPEN; any active ``CONFLICTS_WITH`` between
  two member claims -> DISPUTED; else any member claim with authority CANONICAL ->
  SETTLED; else CLAIMED. A conflict beats a canonical claim: an unresolved dispute
  is never SETTLED (spec §13).

A judgment is *active* when it was applied and no active supersession targets it.
Supersession ends a judgment's effect on the current interpretation for EVERY kind
(spec §4.5, §19); addresses alone stay in the view because they are immutable
identities (spec §7.2.1). A ``SUPERSEDE`` judgment that is itself superseded
restores its target, which may then be superseded again by a new record.

``stale_ids`` is the supersession blast radius (spec §19.1, plan §7.1). Roots are
every judgment that is applied but no longer active, PLUS every issue version minted
by such a judgment; those versions are themselves returned as stale, together with
every transitive DERIVED_FROM descendant of any root, sorted for determinism.
Historical derivation edges and versions are never changed; only this current-view
field moves.

Pure function over domain models: no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from pydantic import Field, field_serializer, field_validator

from foundry.domain.common import Authority, FrozenModel
from foundry.domain.derivation import stale_object_ids
from foundry.domain.semantic_identity import IssueEpistemicState, SemanticClaim
from foundry.domain.semantic_judgment import BindToAddressProposal, CreateAddressProposal
from foundry.domain.semantic_state import SemanticState


class SemanticLocus(FrozenModel):
    representative_id: str
    address_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    epistemic_state: IssueEpistemicState
    disputed_claim_pairs: tuple[tuple[str, str], ...]
    scope: tuple[str, ...]


class CurrentSemanticView(FrozenModel):
    representatives: Mapping[str, str] = Field(default_factory=dict, validate_default=True)
    active_bindings: Mapping[str, str] = Field(default_factory=dict, validate_default=True)
    loci: tuple[SemanticLocus, ...] = ()
    active_equivalence_judgment_ids: tuple[str, ...] = ()
    active_conflict_judgment_ids: tuple[str, ...] = ()
    stale_ids: tuple[str, ...] = ()

    @field_validator("representatives", "active_bindings", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(value))

    @field_serializer("representatives", "active_bindings")
    def serialize_mappings(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


def active_judgment_ids(state: SemanticState) -> frozenset[str]:
    """Applied judgments not currently superseded.

    A target is inactive while ANY of its superseders is itself active, so
    superseding a supersession restores the original target, and a fresh
    supersession record can end it again.
    """
    applied = frozenset(state.applied_judgment_ids)
    superseders: dict[str, list[str]] = {}
    for record in state.supersessions:
        superseders.setdefault(record.target_judgment_id, []).append(record.superseding_judgment_id)
    memo: dict[str, bool] = {}

    def is_active(judgment_id: str) -> bool:
        if judgment_id not in applied:
            return False
        if judgment_id in memo:
            return memo[judgment_id]
        memo[judgment_id] = False  # guard: a cycle can never activate anything
        memo[judgment_id] = not any(is_active(s) for s in superseders.get(judgment_id, ()))
        return memo[judgment_id]

    return frozenset(judgment_id for judgment_id in applied if is_active(judgment_id))


def _find(parents: dict[str, str], node: str) -> str:
    root = node
    while parents[root] != root:
        root = parents[root]
    while parents[node] != root:
        parents[node], node = root, parents[node]
    return root


def _union(parents: dict[str, str], a: str, b: str) -> None:
    root_a, root_b = _find(parents, a), _find(parents, b)
    if root_a == root_b:
        return
    # representative = min address_id
    if root_a < root_b:
        parents[root_b] = root_a
    else:
        parents[root_a] = root_b


def _representatives(state: SemanticState, active: frozenset[str]) -> dict[str, str]:
    parents = {address_id: address_id for address_id in state.addresses}
    for record in state.equivalences:
        if record.judgment_id in active:
            parents.setdefault(record.address_a, record.address_a)
            parents.setdefault(record.address_b, record.address_b)
            _union(parents, record.address_a, record.address_b)
    return {address_id: _find(parents, address_id) for address_id in parents}


def _epistemic_state(
    claims: Iterable[SemanticClaim], disputed_pairs: tuple[tuple[str, str], ...]
) -> IssueEpistemicState:
    claim_list = list(claims)
    if not claim_list:
        return IssueEpistemicState.OPEN
    if disputed_pairs:
        return IssueEpistemicState.DISPUTED
    if any(claim.authority is Authority.CANONICAL for claim in claim_list):
        return IssueEpistemicState.SETTLED
    return IssueEpistemicState.CLAIMED


def _active_bindings(state: SemanticState, active: frozenset[str]) -> dict[str, str]:
    address_by_judgment = {
        address.created_by_judgment_id: address_id
        for address_id, address in state.addresses.items()
    }
    bindings: dict[str, str] = {}
    for judgment_id in state.applied_judgment_ids:
        judgment = state.judgments.get(judgment_id)
        if judgment is None or judgment_id not in active:
            continue
        proposal = judgment.proposal
        if isinstance(proposal, CreateAddressProposal):
            bindings[proposal.candidate.candidate_id] = address_by_judgment[judgment_id]
        elif isinstance(proposal, BindToAddressProposal):
            bindings[proposal.candidate.candidate_id] = proposal.address_id
    return bindings


def _locus(
    state: SemanticState,
    representative_id: str,
    address_ids: tuple[str, ...],
    active_claims: tuple[SemanticClaim, ...],
    active_conflicts: tuple[tuple[str, str], ...],
) -> SemanticLocus:
    members = frozenset(address_ids)
    claims = tuple(claim for claim in active_claims if claim.address_id in members)
    claim_ids = frozenset(claim.claim_id for claim in claims)
    disputed_pairs = tuple(
        sorted(
            (min(a, b), max(a, b)) for a, b in active_conflicts if a in claim_ids and b in claim_ids
        )
    )
    scope = tuple(
        sorted({s for address_id in address_ids for s in state.addresses[address_id].scope})
    )
    return SemanticLocus(
        representative_id=representative_id,
        address_ids=address_ids,
        claim_ids=tuple(claim.claim_id for claim in claims),
        epistemic_state=_epistemic_state(claims, disputed_pairs),
        disputed_claim_pairs=disputed_pairs,
        scope=scope,
    )


def derive_view(state: SemanticState) -> CurrentSemanticView:
    active = active_judgment_ids(state)
    representatives = _representatives(state, active)
    active_claims = tuple(
        claim for _, claim in sorted(state.claims.items()) if claim.created_by_judgment_id in active
    )
    active_conflicts = tuple(
        (record.claim_a, record.claim_b)
        for record in state.conflicts
        if record.judgment_id in active
    )
    members_by_representative: dict[str, list[str]] = {}
    for address_id, representative_id in representatives.items():
        members_by_representative.setdefault(representative_id, []).append(address_id)
    loci = tuple(
        _locus(state, representative_id, tuple(sorted(members)), active_claims, active_conflicts)
        for representative_id, members in sorted(members_by_representative.items())
    )
    return CurrentSemanticView(
        representatives=representatives,
        active_bindings=_active_bindings(state, active),
        loci=loci,
        active_equivalence_judgment_ids=tuple(
            record.judgment_id for record in state.equivalences if record.judgment_id in active
        ),
        active_conflict_judgment_ids=tuple(
            record.judgment_id for record in state.conflicts if record.judgment_id in active
        ),
        stale_ids=tuple(sorted(stale_object_ids(state, active))),
    )
