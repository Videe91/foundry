"""Intent Synthesizer port (Slice-1 task T7).

The synthesizer is compute, not memory — the same law the semantic reasoner already
obeys. It receives a bounded ``IntentSynthesisRequest``: the exact loci it may reason
over and the exact existing intent it may compare against, and nothing else. It never
receives an ``IntentState``, a ``SemanticState``, an ``EventStore``, a judgment body, a
rationale, an event id, or any evidence CONTENT.

Request-only, always
--------------------
Every model here is temporary reasoning context compiled fresh for one call and then
discarded. None of it is canonical state, an event payload, a returned proposal, a
handoff field, or persisted truth. ``KnownIntentObject`` matters most: it carries
statement text so the synthesizer can recognise that a proposal duplicates, extends or
reconciles existing intent, and it must never become durable truth. Durable truth stays
in ``state.objects``.

Trust boundary
--------------
Nothing here can express a fact runtime owns after synthesis — no ``assigned_authority``,
``object_id``, ``proposal_instance_id``, ``event_id``, ``created_at``, ``provenance`` or
``relations``. Those are decided by routing (T6) and the reducer (T4), never proposed.

Provider-neutral: no vendor name, payload shape or transport appears here.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import Field, field_validator

from foundry.domain.common import Authority, FrozenModel, LifecycleStatus, Materiality, SourceKind
from foundry.domain.intent_synthesis import IntentSynthesisResult
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_identity import ClaimValue, IssueEpistemicState
from foundry.domain.semantic_judgment import ReasonerFingerprint

__all__ = [
    "PRESENTABLE_EPISTEMIC_STATES",
    "BasisClaim",
    "IntentSynthesisRequest",
    "IntentSynthesizer",
    "KnownIntentObject",
    "LocusBasis",
]

PRESENTABLE_EPISTEMIC_STATES: frozenset[IssueEpistemicState] = frozenset(
    {IssueEpistemicState.CLAIMED, IssueEpistemicState.SETTLED}
)
"""The only states a locus may be in when shown to a synthesizer.

``OPEN`` has nothing to synthesize and ``DISPUTED`` is an unresolved contradiction;
both are filtered out before model context exists (spec §16), so neither can reach a
``LocusBasis``.
"""


class BasisClaim(FrozenModel):
    """One live claim, as the synthesizer sees it. No evidence content, ever.

    ``source_kinds`` is metadata derived from the claim's EFFECTIVE evidence — its own
    plus any active ``SUPPORTS_CLAIM`` — and is what later lets runtime derive
    ``RESEARCH_DERIVED`` origin without the model asserting it.
    """

    claim_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: ClaimValue
    effective_evidence_ids: tuple[str, ...] = Field(min_length=1)
    authority: Authority
    source_kinds: tuple[SourceKind, ...] = Field(min_length=1)


class LocusBasis(FrozenModel):
    """One semantic locus, keyed on its representative (I12).

    Addresses merged by an active ``EQUIVALENT`` are ONE locus and therefore one basis;
    ``address_ids`` still exposes every member. The singular ``subject`` and ``facet``
    come from the representative address (C22) — deterministically the minimum address
    id under ``derive_view`` — never from whichever member happens to be encountered
    first.
    """

    locus_representative_id: str = Field(min_length=1)
    address_ids: tuple[str, ...] = Field(min_length=1)
    subject: str = Field(min_length=1)
    facet: str = Field(min_length=1)
    live_claims: tuple[BasisClaim, ...] = Field(min_length=1)
    epistemic_state: IssueEpistemicState

    @field_validator("epistemic_state", mode="after")
    @classmethod
    def only_presentable_states(cls, value: IssueEpistemicState) -> IssueEpistemicState:
        if value not in PRESENTABLE_EPISTEMIC_STATES:
            raise ValueError(
                f"a locus in {value.value} is filtered before model context exists and "
                "cannot appear in a LocusBasis"
            )
        return value


class KnownIntentObject(FrozenModel):
    """Existing intent in this scope — request-only, never durable truth.

    It exists so the synthesizer can tell a genuinely new commitment from one that is
    already represented or needs reconciling. ``is_stale`` is runtime-derived from the
    current view: a derived object stays ``ACTIVE`` while its basis is superseded, so
    ``lifecycle`` alone cannot distinguish a sound object from one awaiting
    reconciliation, and without this flag ``REPLACES_STALE`` would be undecidable.
    """

    object_id: str = Field(min_length=1)
    kind: SemanticKind
    authority: Authority
    lifecycle: LifecycleStatus
    is_stale: bool
    scope: tuple[str, ...]
    statement: str = Field(min_length=1)
    materiality: Materiality | None
    basis_claim_ids: tuple[str, ...]
    basis_locus_ids: tuple[str, ...]


class IntentSynthesisRequest(FrozenModel):
    """Bounded, scope-limited context for exactly one synthesis call."""

    project_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    basis: tuple[LocusBasis, ...] = Field(min_length=1)
    known_intent_objects: tuple[KnownIntentObject, ...] = ()
    allowed_target_kinds: frozenset[SemanticKind]


class IntentSynthesizer(Protocol):
    """Mirrors ``SemanticReasoner``: bounded request in, untrusted proposals out.

    The model never supplies its own fingerprint; runtime reads it from the connected
    synthesizer, which is what makes authorship unspoofable (C9/I22).
    """

    @property
    def fingerprint(self) -> ReasonerFingerprint: ...

    def synthesize(self, request: IntentSynthesisRequest) -> IntentSynthesisResult: ...
