"""Bounded assimilation context assembly (9P Task 7 -> 9P2 Task T4; spec §11, §12, §18).

This module is the *tiny assembly function* of 9P spec §19 — NOT the Context Compiler.
It is subordinate to a future Context Compiler, which will own candidate retrieval above
the threshold (the deferred lexical branch of 9P spec §18); the structural comparison
compiler of 9P2 (``foundry.application.contrastive_context``) is called from here for
the request-only ``ComparisonContext``. This module decides only what the model
**sees**, never what anything **means**.

9P2 rule (supersedes the 9P rule that no historical material was ever shown): current
citable evidence remains delta-only; structurally selected predecessor material may
appear only in the non-citable comparison context. Only ids in
``ReasoningRequest.evidence`` are admissible evidence references in model drafts.

Two frontier calls per delta (9P spec §6), each assembled here as one ``ReasoningRequest``:

* **Call 1 — assimilation.** ``assemble_assimilation_request`` sends the delta evidence,
  *descriptors* of every ACTIVE in-scope address (the ``SemanticAddress`` records
  themselves: address_id, subject, facet, scope), the LIVE claims at those addresses
  (their active claim profiles, 9P2 spec §11) and the compiled comparison context with
  those addresses as profile addresses. The allowed kinds are exactly
  ``BIND_TO_ADDRESS | CREATE_ADDRESS``: seeing claims does not let Call 1 assert or
  supersede one. When the active in-scope address count exceeds
  ``CANDIDATE_ADDRESS_THRESHOLD`` the function raises ``ContextUnsupported``
  (``UNSUPPORTED_ABOVE_THRESHOLD``) BEFORE any context is compiled. That is a hard
  stop: there is no lexical top-K, no embedding, no truncation and no silent fallback.
* **Neighbourhood.** ``neighborhood_from_decisions`` is a deterministic *selection*
  (9P spec §6): the addresses touched by ``APPLY``-routed ``CREATE_ADDRESS`` /
  ``BIND_TO_ADDRESS`` judgments in the Call 1 decisions — the minted address or the
  bound address — sorted and de-duplicated. Rejected, held and non-binding judgments
  touch nothing. The orchestrator widens this structurally (union with the addresses
  the comparison context touched) before Call 2; this module does not.
* **Call 2 — claim assimilation.** ``assemble_claim_request`` sends the SAME delta as
  its ONLY evidence, the already-widened neighbourhood addresses, the LIVE claims at
  those addresses (a claim is live while its asserting judgment is active — the view's
  own liveness rule) and a call-specific comparison context with those addresses as
  profile addresses. The allowed kinds are exactly ``SUPPORTS_CLAIM | ASSERT_CLAIM |
  SUPERSEDE | CONFLICTS_WITH``. Predecessor evidence is never inserted into
  ``evidence``; a known claim carries its ``evidence_ids``, a delta item carries
  ``artifact_ref`` / ``supersedes_evidence_id``, and the old-to-new transition (id,
  diff, structural edges) is shown only as non-citable comparison context. Durable
  evidence stays in state and claim evidence is never mutated.

In-scope membership follows ``foundry.domain.handoff.locus_in_scope`` applied at the
address level: an address is in scope when its ``scope`` is project-wide (``()``) or
names the given scope string.

Law of this module: selection never decides meaning. Nothing here compares text, ranks,
scores, truncates, reads judgment metadata, constructs a judgment, filters a reasoner's
output or mutates state. Every function is a pure function of its inputs with a
deterministic output order (sorted by id; Call 2 evidence is the delta in the caller's
order). Any ``ContextUnsupported`` raised by the compiler propagates unchanged.
"""

from __future__ import annotations

from typing import Final

from foundry.application.context_errors import ContextUnsupported
from foundry.application.contrastive_context import compile_comparison_context
from foundry.domain.admission import AdmissionDecision
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_identity import SemanticAddress, SemanticClaim
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
)
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import ReasoningRequest

__all__ = [
    "ASSIMILATION_JUDGMENT_KINDS",
    "CANDIDATE_ADDRESS_THRESHOLD",
    "CLAIM_ASSIMILATION_JUDGMENT_KINDS",
    "ContextUnsupported",
    "active_in_scope_addresses",
    "assemble_assimilation_request",
    "assemble_claim_request",
    "live_claims_at",
    "neighborhood_from_decisions",
]

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


def live_claims_at(
    state: IntentState, address_ids: tuple[str, ...] | frozenset[str]
) -> tuple[SemanticClaim, ...]:
    """LIVE claims (active ``ASSERT_CLAIM``) whose address is in ``address_ids``.

    Sorted by ``claim_id``. ``address_ids`` may be a tuple or a frozenset; order and
    duplicates in it are irrelevant.
    """
    wanted = frozenset(address_ids)
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    return tuple(
        claim
        for _, claim in sorted(semantic.claims.items())
        if claim.address_id in wanted and claim.created_by_judgment_id in active
    )


def assemble_assimilation_request(
    *,
    project_id: str,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    scope: str,
) -> ReasoningRequest:
    """Call 1: delta evidence, all active in-scope addresses, their live claims, context.

    Raises ``ContextUnsupported`` when more than ``CANDIDATE_ADDRESS_THRESHOLD``
    addresses are active in scope — before any comparison context is compiled. Never
    narrows the set by any other means. A compiler refusal propagates unchanged.
    """
    addresses = active_in_scope_addresses(state, scope)
    if len(addresses) > CANDIDATE_ADDRESS_THRESHOLD:
        raise ContextUnsupported(
            f"UNSUPPORTED_ABOVE_THRESHOLD: {len(addresses)} active addresses in scope "
            f"{scope!r} exceed the candidate threshold of {CANDIDATE_ADDRESS_THRESHOLD}; "
            "the above-threshold retrieval branch is deferred to the Context Compiler"
        )
    address_ids = tuple(address.address_id for address in addresses)
    return ReasoningRequest(
        project_id=project_id,
        evidence=delta,
        known_addresses=addresses,
        known_claims=live_claims_at(state, address_ids),
        allowed_judgment_kinds=ASSIMILATION_JUDGMENT_KINDS,
        comparison_context=compile_comparison_context(
            delta=delta, state=state, profile_address_ids=address_ids
        ),
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


def assemble_claim_request(
    *,
    project_id: str,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    neighborhood: tuple[str, ...],
) -> ReasoningRequest:
    """Call 2: the delta ONLY, the neighbourhood addresses, their live claims, context.

    ``evidence`` is exactly ``delta`` (in the caller's order); predecessor evidence is
    never inserted. ``neighborhood`` is the already-widened claim neighbourhood chosen
    by the orchestrator. Raises ``KeyError`` for a neighbourhood address unknown to
    ``state``; a compiler refusal propagates unchanged.
    """
    semantic = state.semantic
    address_ids = tuple(sorted(frozenset(neighborhood)))
    addresses = tuple(semantic.addresses[address_id] for address_id in address_ids)
    return ReasoningRequest(
        project_id=project_id,
        evidence=delta,
        known_addresses=addresses,
        known_claims=live_claims_at(state, address_ids),
        allowed_judgment_kinds=CLAIM_ASSIMILATION_JUDGMENT_KINDS,
        comparison_context=compile_comparison_context(
            delta=delta, state=state, profile_address_ids=address_ids
        ),
    )
