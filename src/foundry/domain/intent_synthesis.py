"""Intent Synthesis vocabulary and durable identity (Slice-1 task T1).

Design spec: ``docs/superpowers/specs/2026-09-22-intent-synthesis-bridge-design.md``.

This module is the *altitude boundary* made concrete. Intent synthesis asks what the
human means; semantic reasoning asks what the evidence says. They never share a
vocabulary, so ``JudgmentKind``, ``JudgmentProposal`` and ``AdmissionRoute`` are not
extended or reused here — ``IntentSynthesisRoute`` is a separate enum (spec §3, I14).

Trust boundary (spec §9.2, C17)
-------------------------------
A synthesizer proposes MEANING and nothing else. The model-facing schema cannot
express ``authority``, ``author``, ``basis_locus_ids``, ``scope``, ``object_id``,
``project_id``, ``provenance``, ``relations``, ``lifecycle``, ``revision``,
``materiality``, ``requires_metric``, ``requires_verification`` or any identity —
``FrozenModel``'s ``extra="forbid"`` is the enforcement. Runtime owns every one of them.

In particular ``authority`` is absent BY DESIGN and must stay absent: the
anti-invention guard (spec §10.3) is tested by injecting an illegal authority at the
runtime routing layer, never by adding a field here for test convenience (C17).

Durable identity (spec §9.4, I21)
---------------------------------
``event_id`` uniqueness is GLOBAL — ``uq_intent_events_event_id`` carries no
``project_id`` and ``InMemoryEventStore`` keeps one process-wide id set — so a
model-chosen id can repeat across projects, across synthesis runs and across retries.
The raw ``model_proposal_id`` is therefore never a durable identity by itself. Every
durable id derives from ``proposal_instance_id``, which is a deterministic function of
``(project_id, synthesis_run_id, model_proposal_id)``. Because ``synthesis_run_id`` is
persisted in ``INTENT_SYNTHESIS_DECIDED``, an interrupted run recomputes byte-identical
ids on recovery with no provider call.

Pure domain: no I/O, no clock, no randomness, no provider import.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from foundry.domain.authority import covering_authority_record
from foundry.domain.common import Authority, FrozenModel, Materiality
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.intelligence.proposals import GapProposal

if TYPE_CHECKING:
    from foundry.domain.state import IntentState

__all__ = [
    "INTENT_BEARING_SEMANTIC_KINDS",
    "IntentDisposition",
    "IntentSynthesisDecision",
    "IntentSynthesisDecisionRecord",
    "IntentSynthesisPolicy",
    "IntentSynthesisProposal",
    "IntentSynthesisResult",
    "IntentSynthesisRoute",
    "IntentSynthesisRoutingOutcome",
    "InvalidationReason",
    "RequirementSynthesisProposal",
    "SynthesisIdentity",
    "SynthesisOrigin",
    "route_intent_synthesis",
]


INTENT_BEARING_SEMANTIC_KINDS: Final[frozenset[SemanticKind]] = frozenset(
    {
        SemanticKind.INTENT,
        SemanticKind.GOAL,
        SemanticKind.OUTCOME,
        SemanticKind.REQUIREMENT,
        SemanticKind.CONSTRAINT,
        SemanticKind.NON_GOAL,
        SemanticKind.PREFERENCE,
        SemanticKind.DECISION,
        SemanticKind.ASSUMPTION,
        SemanticKind.CONTRACT,
    }
)
"""The ten kinds ``INTENT_OBJECT_SYNTHESIZED`` may carry (spec §4, D1, I15).

``ACTOR`` is deliberately absent: it is canonical intent CONTEXT and stays in
``CanonicalIntentPackage.purpose_ids``, but it is not an intent-bearing commitment.
``Claim``, ``Evidence``, ``Unknown``, ``Question``, ``Conflict``, ``Risk``, ``Metric``,
``VerificationObligation``, ``AuthorityRecord`` and ``Amendment`` are supporting
semantic, epistemic or governance objects and are never synthesized intent.

This is a SYNTHESIS-specific set. ``SPECIALIZED_SEMANTIC_KIND_BY_EVENT`` and
``GENERIC_SEMANTIC_KINDS`` keep their own membership and meaning, untouched.
"""


class SynthesisOrigin(StrEnum):
    """Who authored the proposal. Determined by runtime from the author, NEVER from
    the basis: human-authored basis claims do not make a model-written statement
    ``HUMAN_STATED`` (spec §10.1, C9/I22 anti-laundering law)."""

    HUMAN_STATED = "HUMAN_STATED"
    DETERMINISTIC_NORMALIZATION = "DETERMINISTIC_NORMALIZATION"
    AI_INFERRED = "AI_INFERRED"
    RESEARCH_DERIVED = "RESEARCH_DERIVED"


class IntentDisposition(StrEnum):
    """What the proposal does to existing intent (spec §9.3, C3).

    ``EXISTING_UNCHANGED`` is a SUCCESS, not a refusal: the correct outcome is that no
    duplicate durable intent is created.
    """

    NEW = "NEW"
    EXISTING_UNCHANGED = "EXISTING_UNCHANGED"
    REPLACES_STALE = "REPLACES_STALE"


class IntentSynthesisRoute(StrEnum):
    """Where governance sends a synthesis proposal.

    Deliberately NOT ``AdmissionRoute``: the semantic vocabulary stays untouched
    (spec §3, I14), and synthesis needs ``NO_CHANGE``, which has no semantic analogue.
    """

    APPLY = "APPLY"
    NO_CHANGE = "NO_CHANGE"
    REQUIRE_SECOND_LENS = "REQUIRE_SECOND_LENS"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"
    REJECT = "REJECT"


class InvalidationReason(StrEnum):
    """Why a durable ``DECIDED(APPLY)`` was terminally not applied (spec §10.8, C13).

    Bounded by design: the ledger stays analysable, so this is never free text.
    """

    BASIS_CHANGED = "BASIS_CHANGED"
    TARGET_CHANGED = "TARGET_CHANGED"
    AUTHORITY_CHANGED = "AUTHORITY_CHANGED"


def _digest(*parts: str) -> str:
    """Deterministic 16-hex digest over an UNAMBIGUOUS encoding of ``parts``.

    Two properties are load-bearing, and both exist because ``model_proposal_id`` is
    UNTRUSTED model output while ``event_id`` uniqueness is GLOBAL (spec §9.4, I21).

    *Unambiguous encoding.* A canonical JSON array is used rather than the
    ``f"{a}|{b}"`` join of ``semantic_reducer._minted_id``: a bare separator join lets
    a crafted id shift a boundary — ``("P|R", "X", "Y")``, ``("P", "R|X", "Y")`` and
    ``("P", "R", "X|Y")`` all collapse to one digest — forging a durable-id collision.
    JSON string escaping removes that class of collision. ``_minted_id``'s inputs are
    both runtime-owned ids, so its simpler join is safe in its own context and is left
    unchanged; it is a separate path outside this slice.

    *Full width.* The FULL 64-hex SHA-256 is returned, never a truncation. An earlier
    draft truncated to 16 hex (64 bits), which was never approved: having removed
    boundary forgery through the encoding, there is no reason to discard most of the
    digest immediately afterwards and reintroduce birthday-collision headroom on ids
    that are globally unique and partly attacker-influenced.
    """
    canonical = json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SynthesisIdentity(FrozenModel):
    """Runtime-owned durable identity for one proposal (spec §9.4, I21).

    Every component is runtime-owned except ``model_proposal_id``, which is
    model-local and never a durable identity on its own.
    """

    project_id: str = Field(min_length=1)
    synthesis_run_id: str = Field(min_length=1)
    model_proposal_id: str = Field(min_length=1)

    @property
    def proposal_instance_id(self) -> str:
        return "SYN-" + _digest(
            "proposal_instance", self.project_id, self.synthesis_run_id, self.model_proposal_id
        )

    def object_id(self, prefix: str) -> str:
        """The durable id of the object this proposal would mint, if applied."""
        return f"{prefix}-" + _digest("object", self.proposal_instance_id, prefix)

    def event_id(self, step: str) -> str:
        """The durable id of one event in this proposal's lifecycle.

        ``step`` is a plain string rather than an enum so T1 does not pre-empt the
        event vocabulary introduced by T3.
        """
        return "EVT-" + _digest("event", self.proposal_instance_id, step)


class IntentSynthesisProposal(FrozenModel):
    """Shared fields of a synthesis proposal. Meaning only — never authority.

    ``model_proposal_id`` is named for what it is: the model's own local handle,
    meaningful ONLY within one result. Durable identity comes from
    ``SynthesisIdentity``.
    """

    model_proposal_id: str = Field(min_length=1)
    target_kind: SemanticKind
    disposition: IntentDisposition
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    basis_claim_ids: tuple[str, ...] = Field(min_length=1)
    relates_to_object_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_disposition_matrix(self) -> IntentSynthesisProposal:
        """The STRUCTURAL half of the §9.3 matrix.

        The remaining rules — the named object must exist in ``known_intent_objects``,
        ``REPLACES_STALE`` may name only a stale object, and ``EXISTING_UNCHANGED`` may
        not name a stale one — all require request or governed state and are enforced
        at request assembly (T7) and routing (T6). They are not knowable here.
        """
        if self.disposition is IntentDisposition.NEW:
            if self.relates_to_object_id is not None:
                raise ValueError("disposition NEW must not name relates_to_object_id")
        elif self.relates_to_object_id is None:
            raise ValueError(f"disposition {self.disposition} requires relates_to_object_id")
        return self


class RequirementSynthesisProposal(IntentSynthesisProposal):
    """The ONLY Slice-1 variant (spec §9.1, C5).

    A single generic proposal cannot honestly instantiate ten kinds, because the domain
    types carry required kind-specific fields — ``Assumption.risk_level``,
    ``Contract.observable``, ``Decision.rationale``. Each further kind needs its own
    variant and its own design before entering ``allowed_target_kinds``.
    """

    target_kind: Literal[SemanticKind.REQUIREMENT] = SemanticKind.REQUIREMENT


class IntentSynthesisResult(FrozenModel):
    """What one synthesizer invocation returns: proposals, or gaps explaining why not."""

    proposals: tuple[RequirementSynthesisProposal, ...] = ()
    gap_proposals: tuple[GapProposal, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_model_proposal_ids(self) -> IntentSynthesisResult:
        """Two proposals sharing a model id would derive ONE durable identity (§9.4)."""
        seen: set[str] = set()
        for proposal in self.proposals:
            if proposal.model_proposal_id in seen:
                raise ValueError(
                    f"duplicate model_proposal_id in one result: {proposal.model_proposal_id}"
                )
            seen.add(proposal.model_proposal_id)
        return self


class IntentSynthesisPolicy(FrozenModel):
    """Governance knobs. Defaults are the Slice-1 pinning of spec §17.4.

    No kind and no materiality level is material in Slice 1, which is safe because the
    slice admits only ``HUMAN_STATED`` (which needs a covering ``AuthorityRecord``
    regardless) and ``AI_INFERRED`` at ``LOW`` materiality (``PROPOSED``,
    non-contractual, non-blocking). The general policy is open decision D3.
    """

    material_target_kinds: frozenset[SemanticKind] = frozenset()
    material_materiality_levels: frozenset[Materiality] = frozenset()
    canonical_requires_authority: bool = True


class IntentSynthesisDecision(FrozenModel):
    """The route taken for one proposal, with its reasons. Mirrors ``AdmissionDecision``."""

    proposal_instance_id: str = Field(min_length=1)
    route: IntentSynthesisRoute
    reasons: tuple[str, ...] = Field(min_length=1)
    corroborating_proposal_instance_ids: tuple[str, ...] = ()


class IntentSynthesisDecisionRecord(FrozenModel):
    """The whole durable decision: everything needed to FINISH it later (C19).

    Recovery after a durable ``DECIDED(APPLY)`` must **complete the decision already
    made**, never reconstruct a new one from whatever state happens to hold later. A
    bare ``IntentSynthesisDecision`` classifies lifecycle but cannot be effected: it
    carries no statement, no basis claims, no disposition, no origin and no authority.
    Storing only that would force recovery to re-call a provider or rescan raw event
    history, and both are excluded — recovery makes no provider call (spec §10.6), and
    state is read from the projection.

    Each field is here because it **cannot safely be recomputed at recovery time**:

    * ``identity`` — the runtime-owned ``(project_id, synthesis_run_id,
      model_proposal_id)`` triple every durable id derives from (§9.4, I21);
    * ``proposal`` — the meaning itself; recomputing it means calling the model again;
    * ``author`` / ``origin`` — origin follows the AUTHOR, never the basis (C9/I22), and
      the basis may have evolved since the decision was taken;
    * ``assigned_authority`` — the authority assigned WHEN the decision was made.
      Recomputing it under later routing or policy state could silently change it.
      ``None`` is legitimate: a ``REQUIRE_HUMAN``, ``REJECT`` or ``NO_CHANGE`` decision
      assigns none;
    * ``decision`` — the route and its reasons, exactly as recorded;
    * ``decision_event_id`` — exact provenance back to the ``INTENT_SYNTHESIS_DECIDED``
      envelope;
    * ``decided_at`` — the runtime timestamp of the decision, so recovery does not mint
      a different ``created_at`` merely because it ran later.

    **It deliberately does NOT carry a synthesized object.** The object does not exist
    yet; ``INTENT_OBJECT_SYNTHESIZED`` is the only event that establishes it. This
    record is the durable *effect input*, never a prematurely applied object.

    ``author``, ``origin`` and ``assigned_authority`` are runtime-owned. None of them is
    added to the model-facing proposal schema, which still cannot express any of them
    (§9.2, C17). ``decision_event_id`` and ``decided_at`` come from the
    ``INTENT_SYNTHESIS_DECIDED`` envelope's ``event_id`` and ``occurred_at``, never from
    a synthesizer.
    """

    identity: SynthesisIdentity
    proposal: RequirementSynthesisProposal
    author: ReasonerFingerprint
    origin: SynthesisOrigin
    assigned_authority: Authority | None
    decision: IntentSynthesisDecision
    decision_event_id: str = Field(min_length=1)
    decided_at: datetime

    @model_validator(mode="after")
    def validate_identity_agreement(self) -> IntentSynthesisDecisionRecord:
        """Three-way identity coherence (T2.2).

        Two agreements are required, and the second is not implied by the first:

        1. ``decision.proposal_instance_id == identity.proposal_instance_id`` — the
           decision is about this proposal;
        2. ``proposal.model_proposal_id == identity.model_proposal_id`` — the proposal
           BODY belongs to this identity.

        Without (2) a malformed record could pair the identity and decision of proposal
        A with the body of proposal B. Every durable id would agree, so nothing
        downstream would notice, and recovery would faithfully execute the **wrong
        meaning** under an entirely valid durable identity.
        """
        if self.decision.proposal_instance_id != self.identity.proposal_instance_id:
            raise ValueError(
                f"decision names {self.decision.proposal_instance_id!r} but identity derives "
                f"{self.identity.proposal_instance_id!r}"
            )
        if self.proposal.model_proposal_id != self.identity.model_proposal_id:
            raise ValueError(
                f"proposal body carries model_proposal_id "
                f"{self.proposal.model_proposal_id!r} but identity carries "
                f"{self.identity.model_proposal_id!r}; the body does not belong to this record"
            )
        return self


# --------------------------------------------------------------------------- routing (T6)
#
# Pure domain: no I/O, no clock, no provider, no EventStore, no state mutation, no
# semantic-view derivation, and no reuse of ``route_judgment`` — the semantic admission
# vocabulary stays untouched (§3, I14). The authority law is the ONE shared primitive
# from ``domain.authority``; it is never reached through ``domain.admission``, which
# depends on ``IntentState`` and would invert the dependency.

_SLICE_1_MATERIALITY: Final[Materiality] = Materiality.LOW


class IntentSynthesisRoutingOutcome(FrozenModel):
    """What routing decided, plus the authority runtime assigned.

    Runtime-only: this is NOT model-facing. T8 puts both halves into the durable
    ``INTENT_SYNTHESIS_DECIDED`` event. The synthesizer's proposal still cannot express
    authority (§9.2, C17).

    ``assigned_authority`` is retained even when the decision is ``REJECT``: it is the
    audit evidence of what was assigned, which is exactly what an anti-invention
    rejection is about.
    """

    assigned_authority: Authority | None
    decision: IntentSynthesisDecision


def _reject_malformed_authorship(
    author: ReasonerFingerprint, origin: SynthesisOrigin, human_actor_id: str | None
) -> None:
    """I22: origin follows the AUTHOR, never the basis — checked before any rule.

    A malformed combination is a structural failure, never a silently downgraded route:
    quietly turning a bad ``HUMAN_STATED`` into an AI proposal would hide a caller bug
    behind a plausible-looking decision.
    """
    if origin is SynthesisOrigin.DETERMINISTIC_NORMALIZATION:
        raise ValueError(
            "origin DETERMINISTIC_NORMALIZATION is unsupported in Slice 1; §11 defines the "
            "fence but builds nothing under it, and authority inheritance is not implemented"
        )
    if origin is SynthesisOrigin.HUMAN_STATED:
        if not author.is_human:
            raise ValueError("origin HUMAN_STATED requires a human author")
        if human_actor_id is None:
            raise ValueError("origin HUMAN_STATED requires an authenticated human_actor_id")
        if human_actor_id != author.model:
            raise ValueError(
                f"human_actor_id {human_actor_id!r} does not match the author's actor id "
                f"{author.model!r}"
            )
        return
    # AI_INFERRED and RESEARCH_DERIVED share one authorship shape.
    if author.is_human:
        raise ValueError(f"origin {origin.value} requires a non-human author")
    if human_actor_id is not None:
        raise ValueError(f"origin {origin.value} must not carry a human_actor_id")


def _reject_beyond_slice_1(materiality: Materiality, policy: IntentSynthesisPolicy) -> None:
    """The D3/D4 expansion gates stay real rather than silently activating.

    Slice 1 supports LOW ``Requirement`` synthesis under the pinned empty material sets
    (§17.4). Anything wider would require a corroboration algorithm and a materiality
    policy that have not been decided, so it fails closed instead of being guessed.
    """
    if materiality is not _SLICE_1_MATERIALITY:
        raise ValueError(
            f"materiality {materiality.value} is outside Slice 1, which is pinned to "
            f"{_SLICE_1_MATERIALITY.value}; widening it is open decision D4"
        )
    if (
        policy.material_target_kinds != frozenset()
        or policy.material_materiality_levels != frozenset()
        or policy.canonical_requires_authority is not True
    ):
        raise ValueError(
            "policy is wider than the Slice-1 pinning; no corroboration algorithm exists "
            "yet and inventing one is open decision D3"
        )


def _route_with_assigned_authority(
    state: IntentState,
    *,
    identity: SynthesisIdentity,
    proposal: RequirementSynthesisProposal,
    origin: SynthesisOrigin,
    assigned_authority: Authority | None,
) -> IntentSynthesisDecision:
    """Govern an ALREADY-assigned authority. Separated deliberately (C17/I2).

    Keeping this stage callable on its own is what gives the anti-invention guard an
    independent negative control: a test can simulate a runtime-assignment bug by
    passing ``AI_INFERRED`` with ``CANONICAL`` and prove it fails closed, without
    adding an authority field to the model-facing proposal.
    """

    def decide(route: IntentSynthesisRoute, reason: str) -> IntentSynthesisDecision:
        return IntentSynthesisDecision(
            proposal_instance_id=identity.proposal_instance_id, route=route, reasons=(reason,)
        )

    # FIRST rule, always. DETERMINISTIC_NORMALIZATION is not an exception in Slice 1,
    # because that path is unsupported rather than trusted.
    if origin is not SynthesisOrigin.HUMAN_STATED and assigned_authority is Authority.CANONICAL:
        return decide(IntentSynthesisRoute.REJECT, "AUTHORITY_INVENTION")

    # C11: a CANONICAL target may be retired only by a CANONICAL replacement. One
    # equality check; no Authority ordering. Staleness is NOT re-derived here — that was
    # settled before the decision and is T7's to validate.
    if proposal.disposition is IntentDisposition.REPLACES_STALE:
        target = state.objects.get(proposal.relates_to_object_id or "")
        if target is None:
            raise ValueError(
                f"REPLACES_STALE names {proposal.relates_to_object_id!r}, which does not exist"
            )
        if target.authority is Authority.CANONICAL and assigned_authority is not (
            Authority.CANONICAL
        ):
            return decide(IntentSynthesisRoute.REQUIRE_HUMAN, "CANONICAL_REPLACEMENT_REQUIRED")

    if origin is SynthesisOrigin.HUMAN_STATED and assigned_authority is Authority.CANONICAL:
        return decide(IntentSynthesisRoute.APPLY, "HUMAN_AUTHORITY")
    return decide(IntentSynthesisRoute.APPLY, "LOW_RISK")


def route_intent_synthesis(
    state: IntentState,
    *,
    identity: SynthesisIdentity,
    proposal: RequirementSynthesisProposal,
    author: ReasonerFingerprint,
    origin: SynthesisOrigin,
    human_actor_id: str | None,
    target_scope: tuple[str, ...],
    materiality: Materiality,
    policy: IntentSynthesisPolicy,
) -> IntentSynthesisRoutingOutcome:
    """Route one synthesis proposal. Pure: same inputs, same outcome, state untouched.

    Rule order, and it is load-bearing:

    1. structural identity — the call may not pair one proposal body with another
       identity, so a malformed durable decision is never manufactured here;
    2. authorship / origin (I22);
    3. Slice-1 fences — no ``DETERMINISTIC_NORMALIZATION``, ``LOW`` only, pinned policy;
    4. ``EXISTING_UNCHANGED`` → ``NO_CHANGE``, **before** any authority lookup, because
       no object will be written and so no ``AuthorityRecord`` is needed;
    5. authority assignment from ORIGIN — never from the basis claims' authority;
    6. the governance stage above, whose first rule is anti-invention.
    """
    if identity.project_id != state.project_id:
        raise ValueError(
            f"identity project {identity.project_id!r} does not match state project "
            f"{state.project_id!r}"
        )
    if identity.model_proposal_id != proposal.model_proposal_id:
        raise ValueError(
            f"proposal carries model_proposal_id {proposal.model_proposal_id!r} but identity "
            f"carries {identity.model_proposal_id!r}"
        )
    _reject_malformed_authorship(author, origin, human_actor_id)
    _reject_beyond_slice_1(materiality, policy)

    if proposal.disposition is IntentDisposition.EXISTING_UNCHANGED:
        # A success, not a refusal: the correct outcome is that no duplicate intent is
        # created. Whether the named object exists and is non-stale is T7's to validate.
        return IntentSynthesisRoutingOutcome(
            assigned_authority=None,
            decision=IntentSynthesisDecision(
                proposal_instance_id=identity.proposal_instance_id,
                route=IntentSynthesisRoute.NO_CHANGE,
                reasons=("EXISTING_UNCHANGED",),
            ),
        )

    assigned_authority: Authority | None
    if origin is SynthesisOrigin.HUMAN_STATED:
        # ``human_actor_id`` is non-None here: authorship validation proved it.
        assert human_actor_id is not None
        record = covering_authority_record(
            state, actor_id=human_actor_id, target_scope=target_scope
        )
        if record is None:
            # More fundamental than any replacement rule: the human has not established
            # authority for this scope at all.
            return IntentSynthesisRoutingOutcome(
                assigned_authority=None,
                decision=IntentSynthesisDecision(
                    proposal_instance_id=identity.proposal_instance_id,
                    route=IntentSynthesisRoute.REQUIRE_HUMAN,
                    reasons=("AUTHORITY_UNRESOLVED",),
                ),
            )
        assigned_authority = Authority.CANONICAL
    else:
        # AI_INFERRED and RESEARCH_DERIVED alike. Research supplies evidence, never
        # privileged authority, and the basis claims' own authority is never consulted:
        # reading it is exactly the laundering I22 forbids.
        assigned_authority = Authority.PROPOSED

    return IntentSynthesisRoutingOutcome(
        assigned_authority=assigned_authority,
        decision=_route_with_assigned_authority(
            state,
            identity=identity,
            proposal=proposal,
            origin=origin,
            assigned_authority=assigned_authority,
        ),
    )
