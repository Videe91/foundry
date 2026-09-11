"""Bounded assimilation context assembly (9P Task 7; spec §18, §19, §34).

This module is the *tiny assembly function* of spec §19 — NOT the Context Compiler. It
is subordinate to a future Context Compiler, which will own candidate retrieval above the
threshold (the deferred lexical branch of spec §18) and will render richer context; until
then this module decides only what the model **sees**, never what anything **means**.

Two frontier calls per delta (spec §6), each assembled here as one ``ReasoningRequest``:

* **Call 1 — assimilation.** ``assemble_assimilation_request`` sends the delta evidence
  plus *descriptors* of every ACTIVE in-scope address (the ``SemanticAddress`` records
  themselves: address_id, subject, facet, scope). ``known_claims`` is always empty and
  the allowed kinds are exactly ``BIND_TO_ADDRESS | CREATE_ADDRESS``. When the active
  in-scope address count exceeds ``CANDIDATE_ADDRESS_THRESHOLD`` the function raises
  ``ContextUnsupported`` (``UNSUPPORTED_ABOVE_THRESHOLD``). That is a hard stop: there is
  no lexical top-K, no embedding, no truncation and no silent fallback (spec §18).
* **Neighbourhood.** ``neighborhood_from_decisions`` is a deterministic *selection*
  (spec §6): the addresses touched by ``APPLY``-routed ``CREATE_ADDRESS`` /
  ``BIND_TO_ADDRESS`` judgments in the Call 1 decisions — the minted address or the
  bound address — sorted and de-duplicated. Rejected, held and non-binding judgments
  touch nothing.
* **Call 2 — claim assimilation.** ``assemble_claim_request`` sends the delta evidence,
  the neighbourhood addresses, the LIVE claims at those addresses (a claim is live while
  its asserting judgment is active — the view's own liveness rule) and the evidence
  *versions* those claims cite through the view's ``effective_evidence`` (own evidence
  plus active ``SUPPORTS_CLAIM`` records), content included, so lineage
  (``artifact_ref`` / ``supersedes_evidence_id``) is visible to the model as data. The
  allowed kinds are exactly ``SUPPORTS_CLAIM | ASSERT_CLAIM | SUPERSEDE | CONFLICTS_WITH``.
  Unchanged evidence outside the neighbourhood — including in-scope evidence cited by no
  live claim — is never included (spec §19: the persistent arm re-reads zero unchanged
  evidence).

In-scope membership follows ``foundry.domain.handoff.locus_in_scope`` applied at the
address level: an address is in scope when its ``scope`` is project-wide (``()``) or
names the given scope string.

Law of this module: selection never decides meaning. Nothing here compares text, ranks,
scores, truncates, reads judgment metadata, constructs a judgment, filters a reasoner's
output or mutates state. Every function is a pure function of its inputs with a
deterministic output order (sorted by id; delta first for Call 2 evidence).
"""

from __future__ import annotations

from typing import Final

from foundry.domain.admission import AdmissionDecision
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_identity import SemanticAddress, SemanticClaim
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
)
from foundry.domain.semantic_view import active_judgment_ids, derive_view
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import ReasoningRequest

CANDIDATE_ADDRESS_THRESHOLD: Final[int] = 200
"""Maximum active in-scope addresses Call 1 will show in full (spec §18)."""

ASSIMILATION_JUDGMENT_KINDS: Final[frozenset[JudgmentKind]] = frozenset(
    {JudgmentKind.BIND_TO_ADDRESS, JudgmentKind.CREATE_ADDRESS}
)
"""Call 1 may only bind to an existing address or create a new one."""

CLAIM_ASSIMILATION_JUDGMENT_KINDS: Final[frozenset[JudgmentKind]] = frozenset(
    {
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
        JudgmentKind.CONFLICTS_WITH,
    }
)
"""Call 2 may support, assert, supersede or dispute claims; never bind or relate addresses."""


class ContextUnsupported(RuntimeError):
    """The active in-scope address set exceeds the threshold.

    Raised instead of falling back to any narrowing strategy: the above-threshold
    branch is a deferred seam owned by the future Context Compiler (spec §18).
    """


def _address_in_scope(address: SemanticAddress, scope: str) -> bool:
    return address.scope == () or scope in address.scope


def active_in_scope_addresses(state: IntentState, scope: str) -> tuple[SemanticAddress, ...]:
    """Every address whose CREATE judgment is active and whose scope covers ``scope``.

    Sorted by ``address_id``. Pure lookup over the semantic plane: no descriptor is
    compared to anything, no address is preferred over another.
    """
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    return tuple(
        address
        for _, address in sorted(semantic.addresses.items())
        if address.created_by_judgment_id in active and _address_in_scope(address, scope)
    )


def assemble_assimilation_request(
    *,
    project_id: str,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    scope: str,
) -> ReasoningRequest:
    """Call 1: delta evidence plus descriptors of all active in-scope addresses.

    Raises ``ContextUnsupported`` when more than ``CANDIDATE_ADDRESS_THRESHOLD``
    addresses are active in scope. Never narrows the set by any other means.
    """
    addresses = active_in_scope_addresses(state, scope)
    if len(addresses) > CANDIDATE_ADDRESS_THRESHOLD:
        raise ContextUnsupported(
            f"UNSUPPORTED_ABOVE_THRESHOLD: {len(addresses)} active addresses in scope "
            f"{scope!r} exceed the candidate threshold of {CANDIDATE_ADDRESS_THRESHOLD}; "
            "the above-threshold retrieval branch is deferred to the Context Compiler"
        )
    return ReasoningRequest(
        project_id=project_id,
        evidence=delta,
        known_addresses=addresses,
        known_claims=(),
        allowed_judgment_kinds=ASSIMILATION_JUDGMENT_KINDS,
    )


def neighborhood_from_decisions(
    state_after: IntentState, decisions: tuple[AdmissionDecision, ...]
) -> tuple[str, ...]:
    """Addresses touched by ``APPLY``-routed CREATE/BIND judgments among ``decisions``.

    A ``CREATE_ADDRESS`` touches the address it minted (looked up by
    ``created_by_judgment_id`` in ``state_after``); a ``BIND_TO_ADDRESS`` touches the
    address it bound to. Any other route or kind touches nothing. Sorted, de-duplicated,
    independent of the order of ``decisions``.
    """
    semantic = state_after.semantic
    minted_by_judgment = {
        address.created_by_judgment_id: address_id
        for address_id, address in semantic.addresses.items()
    }
    touched: set[str] = set()
    for decision in decisions:
        if decision.route is not AdmissionRoute.APPLY:
            continue
        judgment = semantic.judgments.get(decision.judgment_id)
        if judgment is None:
            continue
        proposal = judgment.proposal
        if isinstance(proposal, CreateAddressProposal):
            minted = minted_by_judgment.get(judgment.judgment_id)
            if minted is not None:
                touched.add(minted)
        elif isinstance(proposal, BindToAddressProposal):
            touched.add(proposal.address_id)
    return tuple(sorted(touched))


def _live_claims_at(state: IntentState, address_ids: frozenset[str]) -> tuple[SemanticClaim, ...]:
    """LIVE claims whose address is in ``address_ids``, sorted by ``claim_id``."""
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    return tuple(
        claim
        for _, claim in sorted(semantic.claims.items())
        if claim.address_id in address_ids and claim.created_by_judgment_id in active
    )


def _cited_evidence(
    state: IntentState, claims: tuple[SemanticClaim, ...], exclude: frozenset[str]
) -> tuple[EvidenceItem, ...]:
    """Evidence versions cited by ``claims``' effective evidence, sorted, minus ``exclude``."""
    semantic = state.semantic
    effective = derive_view(semantic).effective_evidence
    cited = {evidence_id for claim in claims for evidence_id in effective.get(claim.claim_id, ())}
    return tuple(
        semantic.evidence[evidence_id]
        for evidence_id in sorted(cited - exclude)
        if evidence_id in semantic.evidence
    )


def assemble_claim_request(
    *,
    project_id: str,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    neighborhood: tuple[str, ...],
) -> ReasoningRequest:
    """Call 2: delta, neighbourhood addresses, their live claims and cited evidence.

    ``evidence`` is the delta (in the caller's order) followed by every evidence version
    cited by the neighbourhood's live claims (sorted by id, content included, delta ids
    never repeated). Raises ``KeyError`` for a neighbourhood address unknown to ``state``.
    """
    semantic = state.semantic
    address_ids = frozenset(neighborhood)
    addresses = tuple(semantic.addresses[address_id] for address_id in sorted(address_ids))
    claims = _live_claims_at(state, address_ids)
    delta_ids = frozenset(item.evidence_id for item in delta)
    return ReasoningRequest(
        project_id=project_id,
        evidence=delta + _cited_evidence(state, claims, delta_ids),
        known_addresses=addresses,
        known_claims=claims,
        allowed_judgment_kinds=CLAIM_ASSIMILATION_JUDGMENT_KINDS,
    )
