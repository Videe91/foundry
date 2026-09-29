"""Intent Synthesis orchestration — the normal uninterrupted path (Slice-1 task T8).

This is the first layer where the finished pieces become one story:

    replay → compile bounded context → persist deterministic blockers
           → (only if something is eligible) synthesize → validate whole result
           → derive authorship/origin → route against exact state N
           → append DECIDED at expected_sequence = N
           → for APPLY: revalidate live, build the object from the DURABLE record,
             append SYNTHESIZED

Three boundaries are deliberate and load-bearing.

**The provider is the last thing reached, never the first.** Every structural condition
Slice 1 can decide — dispute, staleness, pending governance, an undecided claim — is
settled deterministically *before* a synthesizer exists in the story, and a scope with
nothing eligible reaches zero provider calls. A model is never asked to reason about a
locus runtime had already refused.

**Nothing model-derived becomes durable before the whole result has been validated.**
Whole-result structural validation and effect preflight both complete before the first
``INTENT_SYNTHESIS_DECIDED`` is written, so a malformed later proposal can never leave an
earlier one from the same batch half-accepted.

**T8 never terminalises and never retries.** If the world moved after a durable APPLY,
the effect is refused and the proposal is left *incomplete* — a legal, delivery-blocking
state. Appending ``INTENT_SYNTHESIS_INVALIDATED`` and bounded concurrency retry are T9's,
and the classifier below is written so T9 can reuse it with no provider call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from foundry.application.intent_synthesis_context import (
    IntentSynthesisResultError,
    SynthesisContextBlocker,
    ValidatedSynthesisProposal,
    compile_intent_synthesis_context,
    validate_intent_synthesis_result,
)
from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.domain.authority import covering_authority_record
from foundry.domain.common import (
    Authority,
    FrozenModel,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    SourceKind,
)
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    GapPayload,
    IntentObjectPayload,
    IntentSynthesisDecidedPayload,
    IntentSynthesisInvalidatedPayload,
    StoredEvent,
)
from foundry.domain.gaps import GapKind
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisDecision,
    IntentSynthesisDecisionRecord,
    IntentSynthesisPolicy,
    IntentSynthesisResult,
    IntentSynthesisRoute,
    InvalidationReason,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
    replacement_scope_covers,
    route_intent_synthesis,
    synthesis_digest,
    validate_synthesis_actor,
)
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.intent_synthesis_state import incomplete_proposal_ids
from foundry.domain.intent_view import derive_intent_view
from foundry.domain.semantic import Requirement
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.state import IntentState
from foundry.intelligence.proposals import GapProposal
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError, EventStore
from foundry.ports.intent_synthesizer import BasisClaim, IntentSynthesizer

__all__ = [
    "MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS",
    "IntentSynthesisConcurrencyExhausted",
    "IntentSynthesisEffectPreconditionChanged",
    "IntentSynthesisRecoveryOutcome",
    "IntentSynthesisRunOutcome",
    "IntentSynthesisSnapshotChanged",
    "effect_invalidation_reason",
    "resume_incomplete_synthesis",
    "synthesize_intent",
]

_SLICE_1_MATERIALITY = Materiality.LOW

MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS = 3
"""TOTAL append attempts for one step — not one attempt plus three retries.

Bounded on purpose. Unbounded retry under sustained contention is a livelock that looks
like progress; leaving the proposal incomplete is honest, detectable and retriable by a
later invocation, which is a strictly better failure than spinning.
"""


class IntentSynthesisRunOutcome(FrozenModel):
    """What one ``synthesize_intent`` invocation did. An execution result, not truth.

    Durable state is reconstructable from the event store alone; this carries no
    ``IntentState`` and is never consulted as a cache.
    """

    synthesis_run_id: str
    decisions: tuple[IntentSynthesisDecision, ...] = ()
    recorded_gap_ids: tuple[str, ...] = ()


class IntentSynthesisRecoveryOutcome(FrozenModel):
    """What one recovery pass did. An execution report, never durable truth.

    Four disjoint outcomes per proposal, all of them legitimate: applied, invalidated,
    or still contended. ``remaining_incomplete_proposal_ids`` is re-read from a fresh
    replay at the end rather than inferred from the other three, so it reports the
    ledger rather than this process's beliefs about it.
    """

    applied_proposal_ids: tuple[str, ...] = ()
    invalidated_proposal_ids: tuple[str, ...] = ()
    contention_exhausted_proposal_ids: tuple[str, ...] = ()
    remaining_incomplete_proposal_ids: tuple[str, ...] = ()


class IntentSynthesisConcurrencyExhausted(RuntimeError):
    """A step lost every one of its bounded attempts to unrelated concurrent writes.

    Raised only for the INITIAL ``DECIDED`` append, where exhaustion means *no synthesis
    decision for this proposal became durable at all* — so there is nothing to recover
    and a fresh ``synthesize_intent`` may simply try again. Effect-stage exhaustion is
    deliberately NOT an error: that proposal has a durable decision, so it is reported
    as contended and left for the next recovery pass.
    """

    def __init__(self, proposal_instance_id: str, step: str, attempts: int) -> None:
        super().__init__(
            f"{step} for proposal {proposal_instance_id} lost {attempts} attempts to "
            "concurrent writes"
        )
        self.proposal_instance_id = proposal_instance_id
        self.step = step
        self.attempts = attempts


class IntentSynthesisSnapshotChanged(RuntimeError):
    """The provider reasoned against a snapshot that no longer holds.

    Raised BEFORE any decision is written for that proposal: a decision computed from
    obsolete provider context would be durable and unreviewable. A fresh
    ``synthesize_intent`` invocation is the remedy.
    """


class IntentSynthesisEffectPreconditionChanged(RuntimeError):
    """A durable ``DECIDED(APPLY)`` can no longer be safely effected.

    T8 stops here on purpose. It does not reroute, re-call the provider, append
    ``SYNTHESIZED`` or append ``INTENT_SYNTHESIS_INVALIDATED``; the proposal stays
    incomplete, which is legal and blocks delivery until T9 terminalises or completes it.
    """

    def __init__(self, proposal_instance_id: str, reason: InvalidationReason) -> None:
        super().__init__(
            f"proposal {proposal_instance_id} can no longer be applied: {reason.value}"
        )
        self.proposal_instance_id = proposal_instance_id
        self.reason = reason


# --- the synthesis appender (P2) --------------------------------------------------------------


def _append_at_state(
    store: EventStore, state: IntentState, event: EventEnvelope
) -> tuple[StoredEvent, IntentState]:
    """Append ``event`` expecting exactly the prefix ``state`` was built from.

    Deliberately NOT ``SemanticGovernor._append``: that mints random ids and asks the
    store for its own expected sequence. Both are wrong here. Durable synthesis ids are
    deterministic so recovery recomputes them, and the expected sequence must be the
    caller's state — the exact event-stream prefix the decision was computed against
    (C12). Asking the store afterwards would silently adopt whatever landed in between
    and destroy the guarantee.

    The reducer dry-run keeps the P2 discipline the semantic governor already obeys:
    a reducer refusal means no ledger write. Reducer laws are not copied here; the
    reducer stays the final appendability authority.
    """
    expected_sequence = state.last_sequence
    reduce_event(state, StoredEvent(sequence=expected_sequence + 1, event=event))
    stored = store.append(event, expected_sequence=expected_sequence)
    return stored, reduce_event(state, stored)


# --- durable gap identity ---------------------------------------------------------------------


def _gap_event(
    gap: IntentSynthesisGap, project_id: str, at: datetime, run_id: str
) -> EventEnvelope:
    return EventEnvelope(
        # Deterministic, never random: a re-run of the same logical gap must not mint a
        # second ledger entry, and ``event_id`` uniqueness is global.
        event_id="EVT-" + synthesis_digest("gap_event", gap.id, EventType.GAP_RECORDED.value),
        project_id=project_id,
        event_type=EventType.GAP_RECORDED,
        occurred_at=at,
        correlation_id=run_id,
        payload=GapPayload(gap=gap),
    )


def _runtime_blocker_gap(
    blocker: SynthesisContextBlocker, *, project_id: str, run_id: str, scope: str
) -> IntentSynthesisGap:
    """A deterministic runtime blocker, worded by runtime and classified by nobody.

    ``materiality`` and ``risk`` stay ``None``: a structural fact about the substrate is
    not a graded judgement, and inventing ``LOW`` would fabricate a classification. The
    description is runtime-generated because asking a model to word a condition runtime
    already decided would make the wording unreproducible on recovery.
    """
    return IntentSynthesisGap(
        id="GAP-SYN-"
        + synthesis_digest(
            "runtime_gap",
            project_id,
            run_id,
            blocker.locus_representative_id,
            blocker.gap_kind.value,
        ),
        project_id=project_id,
        kind=blocker.gap_kind,
        description=(
            f"Intent synthesis blocked at locus {blocker.locus_representative_id!r}: "
            f"{blocker.gap_kind.value}."
        ),
        affected_object_ids=(),
        blocking=True,
        scope=(scope,),
        locus_representative_id=blocker.locus_representative_id,
        affected_claim_ids=blocker.affected_claim_ids,
    )


def _model_gap(
    gap_proposal: GapProposal, *, project_id: str, run_id: str, scope: str
) -> IntentSynthesisGap:
    return IntentSynthesisGap(
        # The raw model id is metadata; it is never a durable id by itself, because it
        # can repeat across projects and runs while event ids are globally unique.
        id="GAP-SYN-" + synthesis_digest("model_gap", project_id, run_id, gap_proposal.proposal_id),
        project_id=project_id,
        kind=GapKind.AMBIGUITY,
        description=gap_proposal.description,
        affected_object_ids=(),
        blocking=True,
        scope=(scope,),
        confidence=gap_proposal.confidence,
        subject_key=gap_proposal.subject_key,
        model_gap_proposal_id=gap_proposal.proposal_id,
        # ``source_event_ids`` is deliberately not carried: see _validate_model_gaps.
    )


# --- C24 and the model-gap trust fence --------------------------------------------------------


def _validate_result_exclusivity(result: IntentSynthesisResult) -> None:
    """C24: Slice 1 accepts proposals XOR ambiguity gaps, never both and never neither.

    The frozen ``GapProposal`` carries no ``basis_claim_ids`` and no
    ``locus_representative_id``, so for a multi-locus request there is no sound way to
    say which part of the request a model gap belongs to. Rather than guess an owner,
    the slice refuses the mixed shape outright. An empty result is refused too: synthesis
    must not silently decline with no proposal and no stated reason.
    """
    proposals = result.proposals
    gap_proposals = result.gap_proposals
    if proposals and gap_proposals:
        raise IntentSynthesisResultError(
            "C24: a Slice-1 result carries proposals XOR gap_proposals, never both; the "
            "frozen GapProposal cannot say which locus its gap belongs to"
        )
    if not proposals and not gap_proposals:
        raise IntentSynthesisResultError(
            "C24: an empty result is a structural failure; synthesis must not refuse "
            "without stating a reason"
        )


def _validate_model_gaps(gap_proposals: tuple[GapProposal, ...]) -> None:
    """Every rule fails closed. Nothing is silently repaired, dropped or coerced."""
    seen_ids: set[str] = set()
    seen_identities: set[tuple[GapKind, str]] = set()
    for gap_proposal in gap_proposals:
        if gap_proposal.kind is not GapKind.AMBIGUITY:
            raise IntentSynthesisResultError(
                f"model gap {gap_proposal.proposal_id!r} claims {gap_proposal.kind.value}; a "
                "Slice-1 synthesizer may only report AMBIGUITY, because every other gap "
                "condition was decided deterministically before it was invoked"
            )
        if gap_proposal.blocking is not True:
            raise IntentSynthesisResultError(
                f"model gap {gap_proposal.proposal_id!r} is non-blocking; spec §16 defines "
                "unformable commitment ambiguity as blocking and it is not silently coerced"
            )
        if gap_proposal.source_event_ids != ():
            raise IntentSynthesisResultError(
                f"model gap {gap_proposal.proposal_id!r} supplies source_event_ids "
                f"{gap_proposal.source_event_ids}; the synthesis request exposes no event "
                "ids, so any it returned were invented and are never persisted"
            )
        if gap_proposal.affected_proposal_ids != ():
            raise IntentSynthesisResultError(
                f"model gap {gap_proposal.proposal_id!r} names affected_proposal_ids; the "
                "durable subtype has no approved mapping for them and C24 forbids a mixed "
                "result, so they are refused rather than discarded"
            )
        if gap_proposal.proposal_id in seen_ids:
            raise IntentSynthesisResultError(
                f"duplicate model gap proposal_id {gap_proposal.proposal_id!r} would derive "
                "one durable gap identity"
            )
        identity = (gap_proposal.kind, gap_proposal.subject_key)
        if identity in seen_identities:
            raise IntentSynthesisResultError(
                f"duplicate model gap identity {identity[0].value}/{identity[1]!r} in one result"
            )
        seen_ids.add(gap_proposal.proposal_id)
        seen_identities.add(identity)


# --- runtime-owned origin ---------------------------------------------------------------------


def _derive_origin(*, author_is_human: bool, cited: tuple[BasisClaim, ...]) -> SynthesisOrigin:
    """Origin follows the AUTHOR, then the cited evidence. Never the basis authority.

    Reading a basis claim's ``authority`` to choose origin is exactly the laundering
    I22 forbids: canonical human-authored evidence must not make a model-written
    statement ``HUMAN_STATED``. Only the evidence's SOURCE KIND distinguishes
    ``RESEARCH_DERIVED`` from ``AI_INFERRED``, and only for a non-human author.
    """
    if author_is_human:
        return SynthesisOrigin.HUMAN_STATED
    all_research = all(
        all(kind is SourceKind.RESEARCH for kind in claim.source_kinds) for claim in cited
    )
    return SynthesisOrigin.RESEARCH_DERIVED if all_research else SynthesisOrigin.AI_INFERRED


def _runtime_scope(state: IntentState, basis_claim_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Union of the cited claims' ADDRESS scopes (I6), rebuilt from durable basis ids.

    Rebuilt rather than carried so recovery reconstructs exactly the same scope from the
    durable record with no request, no model text and no stored locus ids. The reducer
    derives it independently and checks equality — deliberately a second body, because a
    verifier that called the producer's function would be checking nothing.
    """
    scopes: set[str] = set()
    for claim_id in basis_claim_ids:
        claim = state.semantic.claims.get(claim_id)
        if claim is None:
            raise IntentSynthesisSnapshotChanged(f"basis claim {claim_id!r} no longer exists")
        address = state.semantic.addresses.get(claim.address_id)
        if address is None:
            raise IntentSynthesisSnapshotChanged(
                f"basis claim {claim_id!r} references address {claim.address_id!r}, which no "
                "longer exists"
            )
        scopes.update(address.scope)
    return tuple(sorted(scopes))


# --- effect feasibility, shared with T9 -------------------------------------------------------


def _basis_is_live(state: IntentState, basis_claim_ids: tuple[str, ...]) -> bool:
    active = active_judgment_ids(state.semantic)
    for claim_id in basis_claim_ids:
        claim = state.semantic.claims.get(claim_id)
        if claim is None or claim.address_id not in state.semantic.addresses:
            return False
        if claim.created_by_judgment_id not in active:
            return False
    return True


def effect_invalidation_reason(
    state: IntentState, record: IntentSynthesisDecisionRecord
) -> InvalidationReason | None:
    """Can the decision ALREADY MADE still be safely effected? Classification only.

    It appends nothing and never re-decides: the durable routing decision is not
    recomputed under later state, because a decision that could silently change meaning
    between being taken and being applied is not a decision. The precedence below is
    fixed so T8 and T9 classify identically.

    ``None`` means the effect is still feasible.
    """
    proposal = record.proposal

    # A. The basis itself. Claims are immutable, so a live claim id IS the unchanged
    #    claim; what can change is whether it is still asserted by an ACTIVE judgment.
    if not _basis_is_live(state, proposal.basis_claim_ids):
        return InvalidationReason.BASIS_CHANGED

    target_scope = _runtime_scope(state, proposal.basis_claim_ids)

    # B. The replacement target. NEW has no target to check.
    target = None
    if proposal.disposition is IntentDisposition.REPLACES_STALE:
        target = state.objects.get(proposal.relates_to_object_id or "")
        if target is None:
            return InvalidationReason.TARGET_CHANGED
        if target.lifecycle is not LifecycleStatus.ACTIVE:
            return InvalidationReason.TARGET_CHANGED
        if target.authority in (Authority.REJECTED, Authority.SUPERSEDED):
            return InvalidationReason.TARGET_CHANGED
        if target.kind is not proposal.target_kind:
            return InvalidationReason.TARGET_CHANGED
        if any(r.retired_object_id == target.id for r in state.intent_synthesis.retirements):
            return InvalidationReason.TARGET_CHANGED
        if target.id not in derive_intent_view(state).stale_ids:
            # Reconciling something no longer stale would retire sound intent.
            return InvalidationReason.TARGET_CHANGED
        if not replacement_scope_covers(target_scope, tuple(target.scope)):
            return InvalidationReason.TARGET_CHANGED

    # C. The authority the durable APPLY rested on.
    if (
        record.origin is SynthesisOrigin.HUMAN_STATED
        and covering_authority_record(
            state, actor_id=record.author.model, target_scope=target_scope
        )
        is None
    ):
        return InvalidationReason.AUTHORITY_CHANGED
    if (
        target is not None
        and target.authority is Authority.CANONICAL
        and record.assigned_authority is not Authority.CANONICAL
    ):
        # C11 again: a canonical target may be retired only by a canonical replacement.
        return InvalidationReason.AUTHORITY_CHANGED
    return None


# --- pre-decision snapshot revalidation -------------------------------------------------------


def _revalidate_snapshot(state: IntentState, validated: ValidatedSynthesisProposal) -> None:
    """The facts this proposal relied on must still hold before any decision is written."""
    proposal = validated.proposal
    if not _basis_is_live(state, proposal.basis_claim_ids):
        raise IntentSynthesisSnapshotChanged(
            f"proposal {proposal.model_proposal_id!r} cites a basis claim that is no longer "
            "live; the provider reasoned against a snapshot that has since moved"
        )
    if proposal.disposition is IntentDisposition.NEW:
        return

    target = state.objects.get(proposal.relates_to_object_id or "")
    if target is None or target.lifecycle is not LifecycleStatus.ACTIVE:
        raise IntentSynthesisSnapshotChanged(
            f"proposal {proposal.model_proposal_id!r} names {proposal.relates_to_object_id!r}, "
            "which is missing or no longer current"
        )
    if any(r.retired_object_id == target.id for r in state.intent_synthesis.retirements):
        raise IntentSynthesisSnapshotChanged(f"target {target.id!r} is already retired")
    stale = target.id in derive_intent_view(state).stale_ids
    if proposal.disposition is IntentDisposition.EXISTING_UNCHANGED and stale:
        raise IntentSynthesisSnapshotChanged(
            f"target {target.id!r} became stale; it must be reconciled, not affirmed"
        )
    if proposal.disposition is IntentDisposition.REPLACES_STALE:
        if not stale:
            raise IntentSynthesisSnapshotChanged(
                f"target {target.id!r} is no longer stale; replacing it would retire sound intent"
            )
        if target.kind is not proposal.target_kind:
            raise IntentSynthesisSnapshotChanged(
                f"target {target.id!r} is no longer a {proposal.target_kind.value}"
            )
        if not replacement_scope_covers(validated.target_scope, tuple(target.scope)):
            raise IntentSynthesisSnapshotChanged(
                f"replacement scope {validated.target_scope} no longer covers target scope "
                f"{tuple(target.scope)}"
            )


def _preflight(state: IntentState, validated: tuple[ValidatedSynthesisProposal, ...]) -> None:
    """Whole-result effect feasibility, BEFORE the first model-derived decision is written.

    T7 validates the proposal against the request snapshot; this is the first layer that
    can see whether the reducer could ever accept the resulting effect. Discovering a
    structurally impossible replacement only after ``DECIDED`` is durable would leave a
    decision that can never be completed.
    """
    replacing: dict[str, str] = {}
    for item in validated:
        proposal = item.proposal
        if proposal.disposition is not IntentDisposition.REPLACES_STALE:
            continue
        target_id = proposal.relates_to_object_id or ""
        if target_id in replacing:
            raise IntentSynthesisResultError(
                f"proposals {replacing[target_id]!r} and {proposal.model_proposal_id!r} both "
                f"replace the same target {target_id!r}; whichever ran first would retire it "
                "and make the other impossible purely because of batch order"
            )
        replacing[target_id] = proposal.model_proposal_id
        target = state.objects.get(target_id)
        if target is None:
            raise IntentSynthesisResultError(f"replacement target {target_id!r} does not exist")
        if target.kind is not proposal.target_kind:
            raise IntentSynthesisResultError(
                f"replacement target {target_id!r} is a {target.kind.value}, but the proposal "
                f"targets {proposal.target_kind.value}"
            )
        if not replacement_scope_covers(item.target_scope, tuple(target.scope)):
            raise IntentSynthesisResultError(
                f"replacement scope {item.target_scope} does not cover target scope "
                f"{tuple(target.scope)} (C21); a narrower replacement cannot retire broader intent"
            )


# --- the synthesized object, built only from the durable record -------------------------------


def _build_requirement(state: IntentState, record: IntentSynthesisDecisionRecord) -> Requirement:
    """Construct the effect from ``state + durable record`` — never from ephemeral context.

    T9 recovery must be able to call this with no provider and no T7 request, so every
    input is either the durable decision or current state. Confidence is carried across
    exactly (D12): ``None`` stays ``None`` and is never replaced by a fallback number.
    """
    if record.assigned_authority is None:
        raise ValueError("an APPLY decision must carry an assigned authority")
    if record.origin is SynthesisOrigin.HUMAN_STATED:
        provenance = Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref=record.author.model,
            source_event_ids=(record.decision_event_id,),
        )
    else:
        # RESEARCH_DERIVED deliberately stores SYSTEM, not RESEARCH: research-derivedness
        # is a property of the basis evidence and is derived from it later. Recording it
        # as the object's own source kind would let basis provenance elevate the author.
        provenance = Provenance(
            source_kind=SourceKind.SYSTEM,
            source_ref=record.identity.synthesis_run_id,
            source_event_ids=(record.decision_event_id,),
        )
    return Requirement(
        id=record.identity.object_id("REQ"),
        project_id=record.identity.project_id,
        statement=record.proposal.statement,
        authority=record.assigned_authority,
        confidence=record.proposal.confidence,
        provenance=provenance,
        created_at=record.decided_at,
        scope=_runtime_scope(state, record.proposal.basis_claim_ids),
        relations=tuple(
            Relation(relation_type=RelationType.DERIVED_FROM, target_id=claim_id)
            for claim_id in record.proposal.basis_claim_ids
        ),
        materiality=_SLICE_1_MATERIALITY,
        requires_metric=False,
        requires_verification=False,
    )


def _synthesized_event(
    state: IntentState, record: IntentSynthesisDecisionRecord, at: datetime
) -> EventEnvelope:
    """The effect event, built from ``state + durable record`` and nothing else.

    One body shared by the normal path and recovery. If recovery built its own, a
    proposal completed after a crash could differ from the same proposal completed
    without one — and the difference would be invisible until someone compared two
    ledgers. Everything identifying here is derived from the record, so running later
    changes nothing.
    """
    identity = record.identity
    return EventEnvelope(
        event_id=identity.event_id("SYNTHESIZED"),
        project_id=identity.project_id,
        event_type=EventType.INTENT_OBJECT_SYNTHESIZED,
        occurred_at=at,
        correlation_id=identity.synthesis_run_id,
        causation_id=record.decision_event_id,
        payload=IntentObjectPayload(
            object=_build_requirement(state, record),
            basis_claim_ids=record.proposal.basis_claim_ids,
            replaces_object_id=(
                record.proposal.relates_to_object_id
                if record.proposal.disposition is IntentDisposition.REPLACES_STALE
                else None
            ),
            proposal_instance_id=identity.proposal_instance_id,
        ),
    )


def _invalidated_event(
    record: IntentSynthesisDecisionRecord, reason: InvalidationReason, at: datetime
) -> EventEnvelope:
    """The terminal non-effect. Bounded reason, no free text, no new routing."""
    identity = record.identity
    return EventEnvelope(
        event_id=identity.event_id("INVALIDATED"),
        project_id=identity.project_id,
        event_type=EventType.INTENT_SYNTHESIS_INVALIDATED,
        occurred_at=at,
        correlation_id=identity.synthesis_run_id,
        causation_id=record.decision_event_id,
        payload=IntentSynthesisInvalidatedPayload(
            proposal_instance_id=identity.proposal_instance_id, reason=reason
        ),
    )


# --- the orchestrator -------------------------------------------------------------------------


def synthesize_intent(
    store: EventStore,
    *,
    project_id: str,
    scope: str,
    synthesizer: IntentSynthesizer,
    policy: IntentSynthesisPolicy,
    clock: Callable[[], datetime],
    synthesis_run_id_factory: Callable[[], str],
    human_actor_id: str | None = None,
) -> IntentSynthesisRunOutcome:
    """Run one governed synthesis pass over ``scope``. See the module docstring."""
    if not scope:
        raise ValueError("scope must be non-empty")
    synthesis_run_id = synthesis_run_id_factory()
    if not synthesis_run_id:
        raise ValueError("synthesis_run_id_factory must return a non-empty id")

    # Before the provider, always. A malformed caller must not reach a synthesizer and
    # then be excused because the result happened to contain only gaps.
    author = synthesizer.fingerprint
    validate_synthesis_actor(author, human_actor_id)

    state = replay(project_id, store.load(project_id))
    context = compile_intent_synthesis_context(state, scope=scope)

    recorded_gap_ids: list[str] = []
    for blocker in context.blockers:
        gap = _runtime_blocker_gap(
            blocker, project_id=project_id, run_id=synthesis_run_id, scope=scope
        )
        _, state = _append_at_state(
            store, state, _gap_event(gap, project_id, clock(), synthesis_run_id)
        )
        recorded_gap_ids.append(gap.id)

    if context.request is None:
        # The T7/T8 no-call fence: nothing eligible means the synthesizer is never reached.
        return IntentSynthesisRunOutcome(
            synthesis_run_id=synthesis_run_id, recorded_gap_ids=tuple(recorded_gap_ids)
        )

    result = synthesizer.synthesize(context.request)
    _validate_result_exclusivity(result)

    if result.gap_proposals:
        _validate_model_gaps(result.gap_proposals)
        for gap_proposal in result.gap_proposals:
            gap = _model_gap(
                gap_proposal, project_id=project_id, run_id=synthesis_run_id, scope=scope
            )
            _, state = _append_at_state(
                store, state, _gap_event(gap, project_id, clock(), synthesis_run_id)
            )
            recorded_gap_ids.append(gap.id)
        # A gap-only result decides nothing: there is no proposal to route.
        return IntentSynthesisRunOutcome(
            synthesis_run_id=synthesis_run_id, recorded_gap_ids=tuple(recorded_gap_ids)
        )

    validated = validate_intent_synthesis_result(
        state=state, request=context.request, result=result
    )
    _preflight(state, validated)

    cited_by_id = {
        basis_claim.claim_id: basis_claim
        for locus in context.request.basis
        for basis_claim in locus.live_claims
    }

    decisions: list[IntentSynthesisDecision] = []
    for item in validated:
        state = _decide_and_apply(
            store,
            state,
            item=item,
            cited_by_id=cited_by_id,
            project_id=project_id,
            scope=scope,
            synthesis_run_id=synthesis_run_id,
            author=author,
            human_actor_id=human_actor_id,
            policy=policy,
            clock=clock,
            decisions=decisions,
        )

    return IntentSynthesisRunOutcome(
        synthesis_run_id=synthesis_run_id,
        decisions=tuple(decisions),
        recorded_gap_ids=tuple(recorded_gap_ids),
    )


def _refresh_for_retry(
    store: EventStore, *, project_id: str, scope: str, proposal: RequirementSynthesisProposal
) -> tuple[IntentState, ValidatedSynthesisProposal, dict[str, BasisClaim]]:
    """Reload and re-validate THIS proposal against a freshly compiled request.

    Merely re-appending after a collision would be the real bug: the provider answered a
    question about a world that has since changed, and an id still existing is not the
    same as the proposal still being sound. Compiling a fresh T7 request and running the
    same validator catches a locus that has become DISPUTED, a basis no longer shown, or
    a target whose staleness flipped.

    Nothing is repaired. A proposal the fresh request rejects is a stale provider answer,
    and the only honest response is a new synthesis run.
    """
    state = replay(project_id, store.load(project_id))
    context = compile_intent_synthesis_context(state, scope=scope)
    if context.request is None:
        raise IntentSynthesisSnapshotChanged(
            f"after concurrent writes no locus in scope {scope!r} is eligible any more; the "
            "provider's answer can no longer support a decision"
        )
    try:
        revalidated = validate_intent_synthesis_result(
            state=state,
            request=context.request,
            result=IntentSynthesisResult(proposals=(proposal,)),
        )
    except IntentSynthesisResultError as exc:
        raise IntentSynthesisSnapshotChanged(
            f"proposal {proposal.model_proposal_id!r} is no longer grounded in the current "
            f"request after concurrent writes: {exc}"
        ) from exc
    cited_by_id = {
        basis_claim.claim_id: basis_claim
        for locus in context.request.basis
        for basis_claim in locus.live_claims
    }
    return state, revalidated[0], cited_by_id


def _decide_and_apply(
    store: EventStore,
    state: IntentState,
    *,
    item: ValidatedSynthesisProposal,
    cited_by_id: dict[str, BasisClaim],
    project_id: str,
    scope: str,
    synthesis_run_id: str,
    author: ReasonerFingerprint,
    human_actor_id: str | None,
    policy: IntentSynthesisPolicy,
    clock: Callable[[], datetime],
    decisions: list[IntentSynthesisDecision],
) -> IntentState:
    """One proposal's whole governed lifecycle. Each is independent after preflight.

    The DECIDED step retries under unrelated contention; the effect step does not. That
    asymmetry is the T8/T9 rule made executable: before DECIDED is durable nothing has
    been committed, so recomputing against fresh state is not only safe but required;
    once it is durable the decision is a fact others may already have read.
    """
    proposal = item.proposal
    identity = SynthesisIdentity(
        project_id=project_id,
        synthesis_run_id=synthesis_run_id,
        model_proposal_id=proposal.model_proposal_id,
    )
    decided_event_id = identity.event_id("DECIDED")
    durable_decision: IntentSynthesisDecision | None = None

    for attempt in range(1, MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS + 1):
        _revalidate_snapshot(state, item)
        origin = _derive_origin(
            author_is_human=author.is_human,
            cited=tuple(cited_by_id[cid] for cid in proposal.basis_claim_ids),
        )
        routing = route_intent_synthesis(
            state,
            identity=identity,
            proposal=proposal,
            author=author,
            origin=origin,
            human_actor_id=human_actor_id,
            target_scope=item.target_scope,
            materiality=_SLICE_1_MATERIALITY,
            policy=policy,
        )
        decided_event = EventEnvelope(
            event_id=decided_event_id,
            project_id=project_id,
            event_type=EventType.INTENT_SYNTHESIS_DECIDED,
            occurred_at=clock(),
            correlation_id=synthesis_run_id,
            payload=IntentSynthesisDecidedPayload(
                proposal=proposal,
                author=author,
                identity=identity,
                origin=origin,
                assigned_authority=routing.assigned_authority,
                decision=routing.decision,
            ),
        )
        try:
            # C12: expected_sequence is the sequence this decision was computed against.
            _, state = _append_at_state(store, state, decided_event)
            durable_decision = routing.decision
            break
        except DuplicateEventError:
            # Deterministic ids mean another worker mints the SAME event. If its decision
            # is durable, that decision wins outright — ours is discarded unexamined,
            # because comparing them would invite "re-deciding" a settled fact.
            state = replay(project_id, store.load(project_id))
            existing = state.intent_synthesis.decisions.get(identity.proposal_instance_id)
            if existing is not None and existing.decision_event_id == decided_event_id:
                durable_decision = existing.decision
                break
            # A duplicate id with no matching durable decision is not a same-item race;
            # it suggests a global id collision or a broken store, and is not swallowed.
            raise
        except ConcurrencyError:
            if attempt == MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS:
                raise IntentSynthesisConcurrencyExhausted(
                    identity.proposal_instance_id, "DECIDED", attempt
                ) from None
            state, item, cited_by_id = _refresh_for_retry(
                store, project_id=project_id, scope=scope, proposal=proposal
            )

    assert durable_decision is not None
    # Reported only once durable: never a local calculation that lost a race.
    decisions.append(durable_decision)

    settled = _terminal_outcome(state, identity.proposal_instance_id)
    if settled is not None:
        # A same-item race we lost outright: the other worker already carried this
        # decision to a terminal state. Re-attempting the effect would raise on a
        # decision that is, from the ledger's point of view, correctly finished.
        return state

    if durable_decision.route is not IntentSynthesisRoute.APPLY:
        # NO_CHANGE, REQUIRE_HUMAN, REQUIRE_SECOND_LENS and REJECT are complete at
        # DECIDED. No object, no gap, no invalidation: routing refusing is not a defect.
        return state

    record = state.intent_synthesis.decisions[identity.proposal_instance_id]

    # Read the ledger again purely to REVALIDATE. The local prefix is deliberately kept
    # as the expected sequence below: adopting this newer state would be a silent
    # concurrency retry, which is T9's decision to make, not T8's.
    live_state = replay(project_id, store.load(project_id))
    reason = effect_invalidation_reason(live_state, record)
    if reason is not None:
        raise IntentSynthesisEffectPreconditionChanged(identity.proposal_instance_id, reason)

    _, state = _append_at_state(store, state, _synthesized_event(state, record, clock()))
    return state


# --- recovery (T9) ---------------------------------------------------------------------


def _terminal_outcome(state: IntentState, proposal_instance_id: str) -> str | None:
    """``"applied"``, ``"invalidated"``, or ``None`` when still incomplete."""
    if proposal_instance_id in state.intent_synthesis.applied_proposal_ids:
        return "applied"
    if proposal_instance_id in state.intent_synthesis.invalidated_proposal_ids:
        return "invalidated"
    return None


def _recover_one(
    store: EventStore,
    *,
    project_id: str,
    proposal_instance_id: str,
    clock: Callable[[], datetime],
) -> str | None:
    """Drive one incomplete proposal to a terminal state, or report contention.

    The decision is never re-made: it is read from the durable record. The only question
    recovery asks is whether that decision can still be effected, and it asks it again
    on every attempt — because the honest answer can change mid-flight. A basis
    superseded between attempt one and attempt two turns a planned SYNTHESIZED into an
    INVALIDATED, and forcing the original plan through would apply an effect whose
    preconditions no longer hold.
    """
    for attempt in range(1, MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS + 1):
        state = replay(project_id, store.load(project_id))
        settled = _terminal_outcome(state, proposal_instance_id)
        if settled is not None:
            # Another worker finished it. That is success, not a race we lost.
            return settled
        record = state.intent_synthesis.decisions.get(proposal_instance_id)
        if record is None:
            raise ValueError(
                f"proposal {proposal_instance_id} is incomplete but has no durable decision"
            )

        reason = effect_invalidation_reason(state, record)
        event = (
            _invalidated_event(record, reason, clock())
            if reason is not None
            else _synthesized_event(state, record, clock())
        )
        try:
            _append_at_state(store, state, event)
            return "invalidated" if reason is not None else "applied"
        except DuplicateEventError:
            fresh = replay(project_id, store.load(project_id))
            settled = _terminal_outcome(fresh, proposal_instance_id)
            if settled is not None:
                return settled
            # A duplicate id without the matching terminal projection is not a
            # legitimate completion by someone else, so it is not disguised as one.
            raise
        except ConcurrencyError:
            if attempt == MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS:
                break
    # One last look before reporting contention: our append may have failed precisely
    # because another worker completed the same proposal.
    final = replay(project_id, store.load(project_id))
    return _terminal_outcome(final, proposal_instance_id)


def resume_incomplete_synthesis(
    store: EventStore,
    *,
    project_id: str,
    clock: Callable[[], datetime],
) -> IntentSynthesisRecoveryOutcome:
    """Finish every durable ``DECIDED(APPLY)`` that never reached its effect.

    Deliberately takes no synthesizer, no policy, no actor and no run-id factory. There
    is nothing left to decide and nothing left to ask a model: every input comes from
    the durable ``IntentSynthesisDecisionRecord`` already projected in state. Making the
    absence structural — the parameters simply do not exist — is what guarantees a
    recovery path can never quietly re-open a settled decision.

    Idempotent by construction rather than by catching duplicates: each pass reloads,
    recomputes the incomplete set and does only what is missing, so calling it again
    after everything is finished appends nothing and raises nothing.

    Not every pass makes terminal progress. Under sustained contention a proposal stays
    incomplete and is reported as such — legal, detectable, and finishable by a later
    call. Claiming otherwise would be the dishonest option.
    """
    state = replay(project_id, store.load(project_id))
    applied: list[str] = []
    invalidated: list[str] = []
    exhausted: list[str] = []

    # Durable decision order — no sorting, no ranking. One contended proposal must not
    # block the ones behind it, so each gets its own bounded loop.
    for proposal_instance_id in incomplete_proposal_ids(state.intent_synthesis):
        outcome = _recover_one(
            store,
            project_id=project_id,
            proposal_instance_id=proposal_instance_id,
            clock=clock,
        )
        if outcome == "applied":
            applied.append(proposal_instance_id)
        elif outcome == "invalidated":
            invalidated.append(proposal_instance_id)
        else:
            exhausted.append(proposal_instance_id)

    final = replay(project_id, store.load(project_id))
    return IntentSynthesisRecoveryOutcome(
        applied_proposal_ids=tuple(applied),
        invalidated_proposal_ids=tuple(invalidated),
        contention_exhausted_proposal_ids=tuple(exhausted),
        remaining_incomplete_proposal_ids=incomplete_proposal_ids(final.intent_synthesis),
    )
