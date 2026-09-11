"""Intent -> Decision handoff contract (Intent Intelligence v2, plan §8.2; spec §17.1, §25.1).

The handoff is the versioned, SCOPED shape the future Decision/Architecture Engine
consumes. It points at durable truth by stable ID and copies nothing that could
become a second ledger: no rationale, no evidence content, no judgment bodies. Context
is bounded to ONE scope.

Scope membership
----------------
A locus is in scope ``S`` iff its ``scope`` descriptor is ``()`` (project-wide) or
contains ``S`` — the same convention ``evaluate_closure`` uses for semantic objects.

Readiness
---------
``semantic_blockers_clear`` is ``no DISPUTED in-scope locus and no in-scope stale object
and no in-scope pending material judgment``. ``ready`` is ``closure.closed and
semantic_blockers_clear``. Closure is the existing scoped ``evaluate_closure`` unchanged
(spec §17.1); the semantic conditions are added, never substituted. The two are reported
separately so the semantic effect stays visible where v0 closure is not met (spec §24).

Pending material governance (spec §17, §24)
--------------------------------------------
``pending_material_judgment_ids`` is ``view.pending_judgment_ids`` — judgments whose
latest admission is ``REQUIRE_SECOND_LENS`` / ``REQUIRE_HUMAN`` and that are not
``SATISFIED_BY`` an applied active judgment — restricted to those that bear on an
in-scope address by the same ``judgment_address_ids`` attribution used for stale
objects. A declined or unanswered ``SUPERSEDE`` therefore blocks exactly the scope it
bears on, with the reason visible as the pending proposal id; no conflict is inferred and
no workflow state exists.

Stale attribution rule (documented here because ids derived downstream are opaque)
-------------------------------------------------------------------------------
``view.stale_ids`` is project-wide. A stale id is attributed to scope ``S`` iff

(a) it is the CURRENT HEAD issue version of an in-scope address; or
(b) it is a transitive DERIVED_FROM descendant of ANY issue version (head or
    historical) of an in-scope address; or
(c) it is a transitive DERIVED_FROM descendant of any JUDGMENT whose proposal bears
    on an in-scope address. A judgment bears on: CREATE_ADDRESS -> the address it
    minted (``created_by_judgment_id``); BIND_TO_ADDRESS / ASSERT_CLAIM ->
    ``address_id``; EQUIVALENT / DISTINCT -> both addresses; CONFLICTS_WITH -> both
    claims' addresses; SUPPORTS_CLAIM -> its claim's address; SUPERSEDE -> the
    addresses its target bears on (recursive).

Stale downstream objects MUST block the readiness of the scope they belong to — that
is the purpose of the blast radius (spec §19.1): every derived descendant of a
superseded basis is NEEDS_RECONCILIATION until reconciled. A superseded issue version
that is no longer its address's head is itself history, not current-state staleness:
supersession always mints a fresh head for every address it touches, so the corrected
interpretation is current and the old version stays readable (spec §19, §22.10)
without blocking the scope forever.

Pure domain: no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Literal

from foundry.domain.closure import ClosureResult, evaluate_closure
from foundry.domain.common import FrozenModel
from foundry.domain.derivation import descendants
from foundry.domain.semantic_identity import IssueEpistemicState
from foundry.domain.semantic_judgment import (
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
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import CurrentSemanticView, SemanticLocus
from foundry.domain.state import IntentState

type HandoffVersion = Literal["intent-decision-handoff-v1"]
HANDOFF_VERSION: Final[HandoffVersion] = "intent-decision-handoff-v1"


class SemanticReadiness(FrozenModel):
    closure: ClosureResult
    disputed_locus_ids: tuple[str, ...]
    stale_object_ids: tuple[str, ...]
    open_locus_ids: tuple[str, ...]
    pending_material_judgment_ids: tuple[str, ...]
    semantic_blockers_clear: bool
    ready: bool


class IntentDecisionHandoff(FrozenModel):
    """What the Decision Engine receives for ONE scope. IDs only; never bodies."""

    handoff_version: HandoffVersion = HANDOFF_VERSION
    project_id: str
    scope: str
    semantic_state_revision: int
    loci: tuple[SemanticLocus, ...]
    claim_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    authority_record_ids: tuple[str, ...]
    superseded_judgment_ids: tuple[str, ...]
    stale_object_ids: tuple[str, ...]
    pending_material_judgment_ids: tuple[str, ...]
    readiness: SemanticReadiness


def locus_in_scope(locus: SemanticLocus, scope: str) -> bool:
    return locus.scope == () or scope in locus.scope


def in_scope_address_ids(loci: Iterable[SemanticLocus]) -> frozenset[str]:
    return frozenset(address_id for locus in loci for address_id in locus.address_ids)


def judgment_address_ids(semantic: SemanticState, judgment: SemanticJudgment) -> frozenset[str]:
    """Addresses a judgment bears on — the address it created, named, or (for a
    conflict) the addresses of the claims it names; a SUPERSEDE bears on whatever its
    target bore on. Pure lookup; unknown references contribute nothing."""
    proposal = judgment.proposal
    match proposal:
        case CreateAddressProposal():
            return frozenset(
                address_id
                for address_id, address in semantic.addresses.items()
                if address.created_by_judgment_id == judgment.judgment_id
            )
        case BindToAddressProposal() | AssertClaimProposal():
            return frozenset({proposal.address_id})
        case EquivalentProposal() | DistinctProposal():
            return frozenset({proposal.address_a, proposal.address_b})
        case ConflictsWithProposal():
            return frozenset(
                semantic.claims[claim_id].address_id
                for claim_id in (proposal.claim_a, proposal.claim_b)
                if claim_id in semantic.claims
            )
        case SupersedeProposal():
            target = semantic.judgments.get(proposal.target_judgment_id)
            return frozenset() if target is None else judgment_address_ids(semantic, target)
        case SupportsClaimProposal():
            claim = semantic.claims.get(proposal.claim_id)
            return frozenset() if claim is None else frozenset({claim.address_id})


def scoped_stale_object_ids(
    semantic: SemanticState, view: CurrentSemanticView, in_scope_loci: Iterable[SemanticLocus]
) -> tuple[str, ...]:
    """``view.stale_ids`` attributed to the given loci by the rule in the module docstring."""
    addresses = in_scope_address_ids(in_scope_loci)
    in_scope_versions = frozenset(
        version_id
        for version_id, version in semantic.issue_versions.items()
        if version.address_id in addresses
    )
    in_scope_heads = frozenset(
        head for address_id, head in semantic.issue_heads.items() if address_id in addresses
    )
    in_scope_judgments = frozenset(
        judgment_id
        for judgment_id, judgment in semantic.judgments.items()
        if judgment_address_ids(semantic, judgment) & addresses
    )
    roots = in_scope_versions | in_scope_judgments
    attributed = in_scope_heads | descendants(semantic.derivations, roots)
    return tuple(sorted(frozenset(view.stale_ids) & attributed))


def scoped_pending_material_judgment_ids(
    semantic: SemanticState, view: CurrentSemanticView, in_scope_loci: Iterable[SemanticLocus]
) -> tuple[str, ...]:
    """``view.pending_judgment_ids`` that bear on an in-scope address (spec §24)."""
    addresses = in_scope_address_ids(in_scope_loci)
    return tuple(
        judgment_id
        for judgment_id in view.pending_judgment_ids
        if judgment_id in semantic.judgments
        and judgment_address_ids(semantic, semantic.judgments[judgment_id]) & addresses
    )


def build_semantic_readiness(
    state: IntentState,
    view: CurrentSemanticView,
    scope: str,
    in_scope_loci: tuple[SemanticLocus, ...],
) -> SemanticReadiness:
    closure = evaluate_closure(state, scope)
    disputed = tuple(
        locus.representative_id
        for locus in in_scope_loci
        if locus.epistemic_state is IssueEpistemicState.DISPUTED
    )
    open_loci = tuple(
        locus.representative_id
        for locus in in_scope_loci
        if locus.epistemic_state is IssueEpistemicState.OPEN
    )
    stale = scoped_stale_object_ids(state.semantic, view, in_scope_loci)
    pending = scoped_pending_material_judgment_ids(state.semantic, view, in_scope_loci)
    semantic_blockers_clear = not disputed and not stale and not pending
    return SemanticReadiness(
        closure=closure,
        disputed_locus_ids=disputed,
        stale_object_ids=stale,
        open_locus_ids=open_loci,
        pending_material_judgment_ids=pending,
        semantic_blockers_clear=semantic_blockers_clear,
        ready=closure.closed and semantic_blockers_clear,
    )
