"""T9 — crash recovery, terminal invalidation and bounded concurrency.

T8 built the uninterrupted path. T9 is about everything that interrupts it: a crash
between the decision and its effect, unrelated events landing mid-append, two workers
racing on the same deterministic id, and a world that moves while recovery is deciding
what to do.

One rule governs the whole task and every test below is a consequence of it:

    before DECIDED is durable  → the decision may be recomputed against fresh state
    after  DECIDED is durable  → it is NEVER recomputed and the provider is NEVER called;
                                 recovery may only APPLY it or INVALIDATE it

The asymmetry is the point. Re-routing before durability is safe because nothing has
been committed; re-routing after durability would silently replace a decision someone
could already have read.
"""

from __future__ import annotations

import pathlib

import pytest

from foundry.application.intent_synthesis import (
    MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS,
    IntentSynthesisConcurrencyExhausted,
    IntentSynthesisRecoveryOutcome,
    IntentSynthesisSnapshotChanged,
    resume_incomplete_synthesis,
    synthesize_intent,
)
from foundry.application.replay import replay
from foundry.application.semantic_reducer import claim_id_for
from foundry.domain.common import Authority, LifecycleStatus, SourceKind
from foundry.domain.events import DerivationPayload, EventEnvelope, EventType, StoredEvent
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisPolicy,
    IntentSynthesisResult,
    IntentSynthesisRoute,
    InvalidationReason,
    SynthesisIdentity,
    SynthesisOrigin,
)
from foundry.domain.intent_synthesis_state import incomplete_proposal_ids
from foundry.domain.semantic_judgment import ConflictsWithProposal, SupersedeProposal
from foundry.domain.state import IntentState
from foundry.ports.event_store import DuplicateEventError
from tests.unit._t8_fixtures import (
    AI,
    CLAIM,
    HUMAN,
    HUMAN_ACTOR,
    PROJECT,
    RUN_ID,
    SCOPE,
    Ledger,
    RecordingStore,
    ScriptedSynthesizer,
    assert_claim,
    authority_record,
    create_address,
    eligible_ledger,
    existing_requirement,
    fixed_clock,
    judgment,
    run_id_factory,
)
from tests.unit.test_intent_synthesis_orchestrator import proposal

POLICY = IntentSynthesisPolicy()


class Interrupted(RuntimeError):
    """Stands in for a crash: the process dies before this append is issued."""


class CrashingStore(RecordingStore):
    """Dies just before appending ``crash_on``, leaving everything earlier durable."""

    def __init__(self, crash_on: EventType) -> None:
        super().__init__()
        self._crash_on = crash_on

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        if event.event_type is self._crash_on:
            raise Interrupted(f"crashed before {event.event_type.value}")
        return super().append(event, expected_sequence)


class InjectingStore(RecordingStore):
    """Lands an unrelated event immediately BEFORE our nth append of ``trigger``.

    That is the real race: our expected sequence was read before the interloper
    arrived, so our append collides rather than silently overwriting.
    """

    def __init__(self, trigger: EventType, inject, times: int = 1) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._trigger = trigger
        self._inject = inject
        self._remaining = times

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        if event.event_type is self._trigger and self._remaining > 0:
            self._remaining -= 1
            self._inject(self)
        return super().append(event, expected_sequence)


class ExplodingSynthesizer:
    """A provider that fails the test if recovery so much as looks at it."""

    @property
    def fingerprint(self):  # type: ignore[no-untyped-def]
        raise AssertionError("recovery must not read a synthesizer fingerprint")

    def synthesize(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("recovery must never call a provider")


def unrelated(store: RecordingStore, marker: str = "EV-unrelated") -> None:
    """Append an event that has nothing to do with the proposal under test."""
    interloper = Ledger(store)
    interloper._n = abs(hash(marker)) % 10_000 + 5_000
    interloper.ingest(marker)


def identity_for(model_proposal_id: str = "p1", run_id: str = RUN_ID) -> SynthesisIdentity:
    return SynthesisIdentity(
        project_id=PROJECT, synthesis_run_id=run_id, model_proposal_id=model_proposal_id
    )


PID = identity_for().proposal_instance_id
REQ_ID = identity_for().object_id("REQ")


def run_until_crash(ledger: Ledger, *results: IntentSynthesisResult, **kw):  # type: ignore[no-untyped-def]
    synthesizer = ScriptedSynthesizer(*results, fingerprint=kw.pop("fingerprint", AI))
    with pytest.raises(Interrupted):
        synthesize_intent(
            ledger.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=synthesizer,
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
            **kw,
        )
    return synthesizer


def resume(ledger: Ledger) -> IntentSynthesisRecoveryOutcome:
    return resume_incomplete_synthesis(ledger.store, project_id=PROJECT, clock=fixed_clock())


def state_of(ledger: Ledger) -> IntentState:
    return replay(PROJECT, ledger.store.load(PROJECT))


def stored_types(ledger: Ledger) -> list[EventType]:
    return [s.event.event_type for s in ledger.store.load(PROJECT)]


def decided_only(store_factory=lambda: CrashingStore(EventType.INTENT_OBJECT_SYNTHESIZED)):  # type: ignore[no-untyped-def]
    """A ledger interrupted between DECIDED(APPLY) and SYNTHESIZED."""
    ledger = Ledger(store_factory())
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    ledger.apply(assert_claim("J-claim", "ADDR-placeholder", "EV-1"))
    return ledger


def crashed_apply_ledger(store: RecordingStore | None = None) -> Ledger:
    """Seeds an eligible scope, runs synthesis, and crashes before the effect lands."""
    ledger = eligible_ledger()
    ledger.store = store or CrashingStore(EventType.INTENT_OBJECT_SYNTHESIZED)
    # Re-seed onto the crashing store so the whole history lives in one place.
    seed = Ledger(ledger.store)
    seed.ingest("EV-1")
    seed.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    seed.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    run_until_crash(seed, IntentSynthesisResult(proposals=(proposal(confidence=0.72),)))
    return seed


# --- the retry constant -----------------------------------------------------------------------


def test_the_retry_bound_is_three_total_attempts() -> None:
    assert MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS == 3


# --- I16: interruption BEFORE DECIDED leaves nothing durable ----------------------------


def test_an_interruption_before_decided_leaves_no_synthesis_lifecycle_at_all() -> None:
    ledger = eligible_ledger()
    ledger.store = CrashingStore(EventType.INTENT_SYNTHESIS_DECIDED)
    seed = Ledger(ledger.store)
    seed.ingest("EV-1")
    seed.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    seed.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    run_until_crash(seed, IntentSynthesisResult(proposals=(proposal(),)))

    state = state_of(seed)
    assert state.intent_synthesis.decisions == {}
    assert state.intent_synthesis.applied_proposal_ids == ()
    assert state.intent_synthesis.invalidated_proposal_ids == ()
    assert incomplete_proposal_ids(state.intent_synthesis) == ()
    assert REQ_ID not in state.objects


def test_decided_concurrency_exhaustion_leaves_no_durable_decision() -> None:
    """Three unrelated collisions before DECIDED: typed failure, nothing durable."""
    counter = {"n": 0}

    def inject(store: RecordingStore) -> None:
        counter["n"] += 1
        unrelated(store, f"EV-interloper-{counter['n']}")

    store = InjectingStore(EventType.INTENT_SYNTHESIS_DECIDED, inject, times=3)
    ledger = Ledger(store)
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    synthesizer = ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),)))

    with pytest.raises(IntentSynthesisConcurrencyExhausted) as excinfo:
        synthesize_intent(
            ledger.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=synthesizer,
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
        )

    assert excinfo.value.step == "DECIDED"
    assert excinfo.value.attempts == MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS
    assert excinfo.value.proposal_instance_id == PID
    # The provider was consulted once, before the first attempt — never again.
    assert synthesizer.calls == 1
    state = state_of(ledger)
    assert state.intent_synthesis.decisions == {}
    assert incomplete_proposal_ids(state.intent_synthesis) == ()
    assert EventType.INTENT_SYNTHESIS_DECIDED not in stored_types(ledger)
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in stored_types(ledger)
    assert EventType.INTENT_SYNTHESIS_INVALIDATED not in stored_types(ledger)


# --- pre-DECIDED concurrency: reload, revalidate, reroute, retry — provider called once ---


def test_an_unrelated_event_before_decided_is_retried_without_recalling_the_provider() -> None:
    store = InjectingStore(
        EventType.INTENT_SYNTHESIS_DECIDED, lambda s: unrelated(s, "EV-mid"), times=1
    )
    ledger = Ledger(store)
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    synthesizer = ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),)))

    outcome = synthesize_intent(
        ledger.store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=synthesizer,
        policy=POLICY,
        clock=fixed_clock(),
        synthesis_run_id_factory=run_id_factory(RUN_ID),
    )

    assert synthesizer.calls == 1
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]
    state = state_of(ledger)
    assert PID in state.intent_synthesis.applied_proposal_ids
    assert REQ_ID in state.objects
    decided_attempts = [
        e for e, _ in ledger.store.appends if e.event_type is EventType.INTENT_SYNTHESIS_DECIDED
    ]
    assert len(decided_attempts) == 2


def test_a_locus_that_became_disputed_before_decided_refuses_the_stale_provider_answer() -> None:
    """The retry must revalidate against a FRESH request, not merely re-append."""

    def inject(store: RecordingStore) -> None:
        interloper = Ledger(store)
        interloper._n = 7000
        interloper.ingest("EV-2")
        from tests.unit._t8_fixtures import ADDRESS

        interloper.apply(assert_claim("J-rival", ADDRESS, "EV-2", text="seven days"))
        interloper.apply(
            judgment(
                "J-conflict",
                ConflictsWithProposal(claim_a=CLAIM, claim_b=claim_id_for(PROJECT, "J-rival")),
                ("EV-2",),
            )
        )

    store = InjectingStore(EventType.INTENT_SYNTHESIS_DECIDED, inject, times=1)
    ledger = Ledger(store)
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    synthesizer = ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),)))

    with pytest.raises(IntentSynthesisSnapshotChanged):
        synthesize_intent(
            ledger.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=synthesizer,
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
        )

    assert synthesizer.calls == 1
    state = state_of(ledger)
    assert state.intent_synthesis.decisions == {}
    assert REQ_ID not in state.objects
    assert EventType.INTENT_SYNTHESIS_DECIDED not in stored_types(ledger)
    assert EventType.INTENT_SYNTHESIS_INVALIDATED not in stored_types(ledger)


def test_a_superseded_basis_before_decided_refuses_the_stale_provider_answer() -> None:
    def inject(store: RecordingStore) -> None:
        interloper = Ledger(store)
        interloper._n = 7100
        interloper.apply(
            judgment(
                "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="wrong"), ("EV-1",)
            )
        )

    store = InjectingStore(EventType.INTENT_SYNTHESIS_DECIDED, inject, times=1)
    ledger = Ledger(store)
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    synthesizer = ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),)))

    with pytest.raises(IntentSynthesisSnapshotChanged):
        synthesize_intent(
            ledger.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=synthesizer,
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
        )

    assert synthesizer.calls == 1
    assert state_of(ledger).intent_synthesis.decisions == {}


# --- same-item DECIDED race -------------------------------------------------------------------


def test_another_worker_landing_the_same_decided_is_accepted_as_authoritative() -> None:
    """Deterministic ids mean two workers mint the SAME DECIDED id. The durable one wins.

    The rival here is a HUMAN author holding covering authority, so its durable decision
    is CANONICAL/HUMAN_AUTHORITY while ours would have been PROPOSED/LOW_RISK. The two
    are genuinely different, which is what makes this a real test: reporting our own
    losing calculation would be indistinguishable from reporting the durable one if both
    sides happened to agree.
    """

    def inject(store: RecordingStore) -> None:
        rival = ScriptedSynthesizer(
            IntentSynthesisResult(proposals=(proposal(),)), fingerprint=HUMAN
        )
        synthesize_intent(
            store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=rival,
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
            human_actor_id=HUMAN_ACTOR,
        )

    store = InjectingStore(EventType.INTENT_SYNTHESIS_DECIDED, inject, times=1)
    ledger = Ledger(store)
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    ledger.record_object(authority_record("AUTH-1"))
    synthesizer = ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),)))

    outcome = synthesize_intent(
        ledger.store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=synthesizer,
        policy=POLICY,
        clock=fixed_clock(),
        synthesis_run_id_factory=run_id_factory(RUN_ID),
    )

    state = state_of(ledger)
    record = state.intent_synthesis.decisions[PID]
    # The durable decision is the human one, not the PROPOSED/LOW_RISK we computed.
    assert record.origin is SynthesisOrigin.HUMAN_STATED
    assert record.assigned_authority is Authority.CANONICAL
    assert record.decision.reasons == ("HUMAN_AUTHORITY",)
    assert list(outcome.decisions) == [record.decision]
    assert record.decision_event_id == identity_for().event_id("DECIDED")
    assert PID in state.intent_synthesis.applied_proposal_ids
    assert state.objects[REQ_ID].authority is Authority.CANONICAL


# --- I16: interruption AFTER DECIDED, then recovery ------------------------------------------


def test_an_interruption_after_decided_leaves_the_proposal_incomplete() -> None:
    ledger = crashed_apply_ledger()
    state = state_of(ledger)

    assert PID in state.intent_synthesis.decisions
    assert incomplete_proposal_ids(state.intent_synthesis) == (PID,)
    assert REQ_ID not in state.objects
    assert [e for e in state.semantic.derivations if e.child_id == REQ_ID] == []
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in stored_types(ledger)


def test_recovery_finishes_an_interrupted_apply_without_a_synthesizer() -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]

    outcome = resume(ledger)

    assert outcome.applied_proposal_ids == (PID,)
    assert outcome.invalidated_proposal_ids == ()
    assert outcome.contention_exhausted_proposal_ids == ()
    assert outcome.remaining_incomplete_proposal_ids == ()
    state = state_of(ledger)
    assert PID in state.intent_synthesis.applied_proposal_ids
    assert REQ_ID in state.objects
    assert incomplete_proposal_ids(state.intent_synthesis) == ()


def test_the_recovered_projection_matches_the_uninterrupted_one_exactly() -> None:
    """I20/I21: recovery is not allowed to build a different object because it ran later."""
    uninterrupted = eligible_ledger()
    synthesize_intent(
        uninterrupted.store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=ScriptedSynthesizer(
            IntentSynthesisResult(proposals=(proposal(confidence=0.72),))
        ),
        policy=POLICY,
        clock=fixed_clock(),
        synthesis_run_id_factory=run_id_factory(RUN_ID),
    )

    recovered = crashed_apply_ledger()
    recovered.store._crash_on = None  # type: ignore[attr-defined]
    resume(recovered)

    assert state_of(recovered).model_dump(mode="json") == state_of(uninterrupted).model_dump(
        mode="json"
    )


def test_recovery_reuses_every_deterministic_id() -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    resume(ledger)

    identity = identity_for()
    state = state_of(ledger)
    record = state.intent_synthesis.decisions[identity.proposal_instance_id]
    assert record.identity.synthesis_run_id == RUN_ID
    assert record.decision_event_id == identity.event_id("DECIDED")
    synthesized = [
        s.event
        for s in ledger.store.load(PROJECT)
        if s.event.event_type is EventType.INTENT_OBJECT_SYNTHESIZED
    ]
    assert [e.event_id for e in synthesized] == [identity.event_id("SYNTHESIZED")]
    assert synthesized[0].causation_id == record.decision_event_id
    assert synthesized[0].correlation_id == RUN_ID
    assert state.objects[identity.object_id("REQ")].created_at == record.decided_at


def test_recovery_applies_the_durable_origin_and_authority_not_a_recomputed_one() -> None:
    """C12: after DECIDED, origin, authority and provenance come from the record alone.

    The recovering process has no author, no actor id and no policy, so anything it
    "recomputed" would be a fabrication. A HUMAN_STATED decision must still produce HUMAN
    provenance naming the actor, even though recovery never saw a human.
    """
    ledger = Ledger(CrashingStore(EventType.INTENT_OBJECT_SYNTHESIZED))
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    ledger.record_object(authority_record("AUTH-1"))
    run_until_crash(
        ledger,
        IntentSynthesisResult(proposals=(proposal(confidence=0.72),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    ledger.store._crash_on = None  # type: ignore[attr-defined]

    outcome = resume(ledger)

    assert outcome.applied_proposal_ids == (PID,)
    state = state_of(ledger)
    record = state.intent_synthesis.decisions[PID]
    assert record.origin is SynthesisOrigin.HUMAN_STATED
    obj = state.objects[REQ_ID]
    assert obj.authority is Authority.CANONICAL
    assert obj.provenance.source_kind is SourceKind.HUMAN
    assert obj.provenance.source_ref == HUMAN_ACTOR
    assert obj.provenance.source_event_ids == (record.decision_event_id,)
    assert obj.confidence == 0.72


def test_a_proposal_finished_by_another_worker_mid_retry_is_reported_as_success() -> None:
    """The top-of-loop reload is what makes this safe: after losing an append we must
    re-ask whether the work still needs doing, not blindly try again."""
    fired = {"done": False}

    def inject(store: RecordingStore) -> None:
        if fired["done"]:
            return
        fired["done"] = True
        # A rival finishes the whole proposal while our first append is in flight.
        resume_incomplete_synthesis(store, project_id=PROJECT, clock=fixed_clock())
        # ...and an unrelated event lands too, so OUR append collides.
        unrelated(store, "EV-rival-tail")

    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    ledger.store._trigger = EventType.INTENT_OBJECT_SYNTHESIZED  # type: ignore[attr-defined]
    ledger.store._inject = inject  # type: ignore[attr-defined]
    ledger.store._remaining = 1  # type: ignore[attr-defined]
    ledger.store.__class__ = InjectingStore

    outcome = resume(ledger)

    assert outcome.applied_proposal_ids == (PID,)
    assert outcome.contention_exhausted_proposal_ids == ()
    state = state_of(ledger)
    assert PID in state.intent_synthesis.applied_proposal_ids
    synthesized = [t for t in stored_types(ledger) if t is EventType.INTENT_OBJECT_SYNTHESIZED]
    assert len(synthesized) == 1


def test_a_proposal_invalidated_by_a_rival_mid_retry_is_not_re_applied() -> None:
    """The asymmetric race, which is the one that actually needs the reload.

    A rival INVALIDATES the proposal while our SYNTHESIZED append is in flight, and the
    condition that justified its invalidation is then reverted. Our ids do not collide —
    the rival wrote INVALIDATED, we were about to write SYNTHESIZED — so nothing else
    catches this: only re-asking "does this still need doing?" at the top of the retry
    stops recovery from applying an effect to an already-terminal proposal.
    """
    ledger = Ledger(CrashingStore(EventType.INTENT_OBJECT_SYNTHESIZED))
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    ledger.record_object(authority_record("AUTH-1"))
    run_until_crash(
        ledger,
        IntentSynthesisResult(proposals=(proposal(),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    ledger.store._crash_on = None  # type: ignore[attr-defined]

    fired = {"done": False}

    def inject(store: RecordingStore) -> None:
        if fired["done"]:
            return
        fired["done"] = True
        rival = Ledger(store)
        rival._n = 7400
        # Revoke authority, let a rival terminalise it, then put authority back.
        rival.record_object(authority_record("AUTH-1", lifecycle=LifecycleStatus.SUPERSEDED))
        resume_incomplete_synthesis(store, project_id=PROJECT, clock=fixed_clock())
        rival.record_object(authority_record("AUTH-1"))

    ledger.store._trigger = EventType.INTENT_OBJECT_SYNTHESIZED  # type: ignore[attr-defined]
    ledger.store._inject = inject  # type: ignore[attr-defined]
    ledger.store._remaining = 1  # type: ignore[attr-defined]
    ledger.store.__class__ = InjectingStore

    outcome = resume(ledger)

    assert outcome.invalidated_proposal_ids == (PID,)
    assert outcome.applied_proposal_ids == ()
    state = state_of(ledger)
    assert PID in state.intent_synthesis.invalidated_proposal_ids
    assert PID not in state.intent_synthesis.applied_proposal_ids
    assert REQ_ID not in state.objects
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in stored_types(ledger)


def test_recovery_never_touches_a_provider() -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    exploding = ExplodingSynthesizer()
    outcome = resume(ledger)
    assert outcome.applied_proposal_ids == (PID,)
    with pytest.raises(TypeError):
        resume_incomplete_synthesis(  # type: ignore[call-arg]
            ledger.store, project_id=PROJECT, clock=fixed_clock(), synthesizer=exploding
        )


# --- I20 atomicity ----------------------------------------------------------------------------


def test_a_new_requirement_recovers_with_every_derivation_edge_at_once() -> None:
    ledger = crashed_apply_ledger()
    before = state_of(ledger)
    assert REQ_ID not in before.objects
    assert [e for e in before.semantic.derivations if e.child_id == REQ_ID] == []

    ledger.store._crash_on = None  # type: ignore[attr-defined]
    resume(ledger)

    after = state_of(ledger)
    assert REQ_ID in after.objects
    assert [e.parent_id for e in after.semantic.derivations if e.child_id == REQ_ID] == ["J-claim"]
    assert PID in after.intent_synthesis.applied_proposal_ids


def _crashed_replacement_ledger(store: RecordingStore | None = None) -> tuple[Ledger, str]:
    ledger = Ledger(store or CrashingStore(EventType.INTENT_OBJECT_SYNTHESIZED))
    ledger.ingest("EV-1")
    ledger.ingest("EV-2")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-old", ADDRESS, "EV-1", text="seven days"))
    ledger.apply(assert_claim("J-new", ADDRESS, "EV-2", text="thirty days"))
    old_claim = claim_id_for(PROJECT, "J-old")
    new_claim = claim_id_for(PROJECT, "J-new")
    ledger.canonicalize(existing_requirement("REQ-OLD", basis_claim_ids=(old_claim,)))
    ledger.append(
        EventType.DERIVATION_RECORDED, DerivationPayload(child_id="REQ-OLD", parent_id="J-old")
    )
    ledger.apply(
        judgment(
            "J-sup", SupersedeProposal(target_judgment_id="J-old", reason="corrected"), ("EV-2",)
        )
    )
    run_until_crash(
        ledger,
        IntentSynthesisResult(
            proposals=(
                proposal(
                    disposition=IntentDisposition.REPLACES_STALE,
                    relates_to_object_id="REQ-OLD",
                    basis_claim_ids=(new_claim,),
                ),
            )
        ),
    )
    return ledger, new_claim


def test_an_interrupted_replacement_never_shows_a_replacement_without_its_retirement() -> None:
    ledger, _ = _crashed_replacement_ledger()
    before = state_of(ledger)

    assert REQ_ID not in before.objects
    assert before.objects["REQ-OLD"].lifecycle is LifecycleStatus.ACTIVE
    assert before.intent_synthesis.retirements == ()
    assert incomplete_proposal_ids(before.intent_synthesis) == (PID,)

    ledger.store._crash_on = None  # type: ignore[attr-defined]
    resume(ledger)

    after = state_of(ledger)
    assert after.objects[REQ_ID].lifecycle is LifecycleStatus.ACTIVE
    assert after.objects["REQ-OLD"].lifecycle is LifecycleStatus.SUPERSEDED
    assert after.objects["REQ-OLD"].revision == before.objects["REQ-OLD"].revision + 1
    assert [r.retired_object_id for r in after.intent_synthesis.retirements] == ["REQ-OLD"]
    assert after.intent_synthesis.retirements[0].replaced_by_object_id == REQ_ID
    assert PID in after.intent_synthesis.applied_proposal_ids


# --- terminal invalidation (C13) --------------------------------------------------------------


def test_a_superseded_basis_recovers_as_invalidated_basis_changed() -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    ledger.apply(
        judgment(
            "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="wrong"), ("EV-1",)
        )
    )

    outcome = resume(ledger)

    assert outcome.invalidated_proposal_ids == (PID,)
    assert outcome.applied_proposal_ids == ()
    state = state_of(ledger)
    assert PID in state.intent_synthesis.invalidated_proposal_ids
    assert PID not in state.intent_synthesis.applied_proposal_ids
    assert incomplete_proposal_ids(state.intent_synthesis) == ()
    assert REQ_ID not in state.objects
    assert state.intent_synthesis.retirements == ()
    invalidated = [
        s.event
        for s in ledger.store.load(PROJECT)
        if s.event.event_type is EventType.INTENT_SYNTHESIS_INVALIDATED
    ]
    assert len(invalidated) == 1
    assert invalidated[0].event_id == identity_for().event_id("INVALIDATED")
    assert invalidated[0].causation_id == state.intent_synthesis.decisions[PID].decision_event_id
    assert invalidated[0].correlation_id == RUN_ID
    assert invalidated[0].payload.reason is InvalidationReason.BASIS_CHANGED


def test_a_target_that_stopped_being_stale_recovers_as_invalidated_target_changed() -> None:
    ledger, _ = _crashed_replacement_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    # Superseding the superseder restores J-old, so REQ-OLD is sound again.
    ledger.apply(
        judgment(
            "J-unsup", SupersedeProposal(target_judgment_id="J-sup", reason="reverted"), ("EV-2",)
        )
    )

    outcome = resume(ledger)

    assert outcome.invalidated_proposal_ids == (PID,)
    state = state_of(ledger)
    assert PID in state.intent_synthesis.invalidated_proposal_ids
    assert state.objects["REQ-OLD"].lifecycle is LifecycleStatus.ACTIVE
    assert state.intent_synthesis.retirements == ()
    assert REQ_ID not in state.objects
    invalidated = [
        s.event
        for s in ledger.store.load(PROJECT)
        if s.event.event_type is EventType.INTENT_SYNTHESIS_INVALIDATED
    ]
    assert invalidated[0].payload.reason is InvalidationReason.TARGET_CHANGED


def test_a_revoked_authority_recovers_as_invalidated_authority_changed() -> None:
    ledger = eligible_ledger()
    ledger.store = CrashingStore(EventType.INTENT_OBJECT_SYNTHESIZED)
    seed = Ledger(ledger.store)
    seed.ingest("EV-1")
    seed.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    seed.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    seed.record_object(authority_record("AUTH-1"))
    run_until_crash(
        seed,
        IntentSynthesisResult(proposals=(proposal(),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    state = state_of(seed)
    assert state.intent_synthesis.decisions[PID].origin is SynthesisOrigin.HUMAN_STATED
    assert state.intent_synthesis.decisions[PID].assigned_authority is Authority.CANONICAL

    seed.store._crash_on = None  # type: ignore[attr-defined]
    seed.record_object(authority_record("AUTH-1", lifecycle=LifecycleStatus.SUPERSEDED))

    outcome = resume(seed)

    assert outcome.invalidated_proposal_ids == (PID,)
    final = state_of(seed)
    assert PID in final.intent_synthesis.invalidated_proposal_ids
    assert REQ_ID not in final.objects
    invalidated = [
        s.event
        for s in seed.store.load(PROJECT)
        if s.event.event_type is EventType.INTENT_SYNTHESIS_INVALIDATED
    ]
    assert invalidated[0].payload.reason is InvalidationReason.AUTHORITY_CHANGED


def test_recovery_never_reactivates_an_invalidated_proposal() -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    ledger.apply(
        judgment(
            "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="wrong"), ("EV-1",)
        )
    )
    resume(ledger)
    before = len(ledger.store.load(PROJECT))

    again = resume(ledger)

    assert again == IntentSynthesisRecoveryOutcome()
    assert len(ledger.store.load(PROJECT)) == before


# --- idempotence ------------------------------------------------------------------------------


def test_a_second_recovery_is_a_no_op_success() -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    first = resume(ledger)
    assert first.applied_proposal_ids == (PID,)
    stream = len(ledger.store.load(PROJECT))

    second = resume(ledger)

    assert second.applied_proposal_ids == ()
    assert second.invalidated_proposal_ids == ()
    assert second.contention_exhausted_proposal_ids == ()
    assert second.remaining_incomplete_proposal_ids == ()
    assert len(ledger.store.load(PROJECT)) == stream


def test_recovery_on_a_ledger_with_nothing_incomplete_does_nothing() -> None:
    ledger = eligible_ledger()
    synthesize_intent(
        ledger.store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),))),
        policy=POLICY,
        clock=fixed_clock(),
        synthesis_run_id_factory=run_id_factory(RUN_ID),
    )
    stream = len(ledger.store.load(PROJECT))
    assert resume(ledger) == IntentSynthesisRecoveryOutcome()
    assert len(ledger.store.load(PROJECT)) == stream


# --- same-item races during recovery ----------------------------------------------------------


@pytest.mark.parametrize("terminal", ["applied", "invalidated"])
def test_another_worker_landing_the_terminal_event_first_is_treated_as_success(
    terminal: str,
) -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    if terminal == "invalidated":
        ledger.apply(
            judgment(
                "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="wrong"), ("EV-1",)
            )
        )

    fired = {"done": False}

    def inject(store: RecordingStore) -> None:
        if fired["done"]:
            return
        fired["done"] = True
        resume_incomplete_synthesis(store, project_id=PROJECT, clock=fixed_clock())

    target = (
        EventType.INTENT_SYNTHESIS_INVALIDATED
        if terminal == "invalidated"
        else EventType.INTENT_OBJECT_SYNTHESIZED
    )
    ledger.store.__class__ = type(
        "Racing", (RecordingStore,), {"append": _racing_append(target, inject)}
    )

    outcome = resume(ledger)

    state = state_of(ledger)
    if terminal == "applied":
        assert outcome.applied_proposal_ids == (PID,)
        assert PID in state.intent_synthesis.applied_proposal_ids
    else:
        assert outcome.invalidated_proposal_ids == (PID,)
        assert PID in state.intent_synthesis.invalidated_proposal_ids
    assert outcome.remaining_incomplete_proposal_ids == ()


def _racing_append(target: EventType, inject):  # type: ignore[no-untyped-def]
    def append(self, event, expected_sequence):  # type: ignore[no-untyped-def]
        if event.event_type is target:
            inject(self)
        return RecordingStore.append(self, event, expected_sequence)

    return append


def test_a_duplicate_id_without_a_terminal_projection_is_re_raised() -> None:
    """A duplicate that does NOT correspond to a legitimate completion is a real fault."""
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    poisoned = ledger.store._event_ids if hasattr(ledger.store, "_event_ids") else None
    assert poisoned is None
    ledger.store._inner._event_ids.add(identity_for().event_id("SYNTHESIZED"))

    with pytest.raises(DuplicateEventError):
        resume(ledger)

    assert incomplete_proposal_ids(state_of(ledger).intent_synthesis) == (PID,)


# --- bounded contention during recovery -------------------------------------------------------


def test_repeated_contention_leaves_the_proposal_incomplete_and_retriable() -> None:
    """Three collisions: no fatal error, no false terminality, still recoverable later."""
    counter = {"n": 0}

    def inject(store: RecordingStore) -> None:
        counter["n"] += 1
        unrelated(store, f"EV-contend-{counter['n']}")

    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    ledger.store._trigger = EventType.INTENT_OBJECT_SYNTHESIZED  # type: ignore[attr-defined]
    ledger.store._inject = inject  # type: ignore[attr-defined]
    ledger.store._remaining = 3  # type: ignore[attr-defined]
    ledger.store.__class__ = InjectingStore

    outcome = resume(ledger)

    assert outcome.contention_exhausted_proposal_ids == (PID,)
    assert outcome.applied_proposal_ids == ()
    assert outcome.invalidated_proposal_ids == ()
    assert outcome.remaining_incomplete_proposal_ids == (PID,)
    state = state_of(ledger)
    assert PID not in state.intent_synthesis.applied_proposal_ids
    assert PID not in state.intent_synthesis.invalidated_proposal_ids
    assert incomplete_proposal_ids(state.intent_synthesis) == (PID,)

    # The whole point: a later invocation must be able to finish it.
    ledger.store._remaining = 0  # type: ignore[attr-defined]
    later = resume(ledger)
    assert later.applied_proposal_ids == (PID,)
    assert later.remaining_incomplete_proposal_ids == ()


def test_a_relevant_change_during_contention_switches_the_planned_effect() -> None:
    """Attempt 1 plans SYNTHESIZED; the basis dies; attempt 2 appends INVALIDATED."""
    fired = {"done": False}

    def inject(store: RecordingStore) -> None:
        if fired["done"]:
            return
        fired["done"] = True
        interloper = Ledger(store)
        interloper._n = 7300
        interloper.apply(
            judgment(
                "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="wrong"), ("EV-1",)
            )
        )

    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    ledger.store._trigger = EventType.INTENT_OBJECT_SYNTHESIZED  # type: ignore[attr-defined]
    ledger.store._inject = inject  # type: ignore[attr-defined]
    ledger.store._remaining = 1  # type: ignore[attr-defined]
    ledger.store.__class__ = InjectingStore

    outcome = resume(ledger)

    assert outcome.invalidated_proposal_ids == (PID,)
    assert outcome.applied_proposal_ids == ()
    state = state_of(ledger)
    assert PID in state.intent_synthesis.invalidated_proposal_ids
    assert REQ_ID not in state.objects
    invalidated = [
        s.event
        for s in ledger.store.load(PROJECT)
        if s.event.event_type is EventType.INTENT_SYNTHESIS_INVALIDATED
    ]
    assert invalidated[0].payload.reason is InvalidationReason.BASIS_CHANGED


# --- C18: matched-baseline concurrency equivalence ---------------------------------------------


def test_c18_a_raced_recovery_produces_the_same_projection_as_a_serialized_one() -> None:
    """Same events, same durable order — the race must leave no trace in the projection."""
    # Baseline: the unrelated event lands FIRST, recovery reads after it, then appends.
    baseline = crashed_apply_ledger()
    baseline.store._crash_on = None  # type: ignore[attr-defined]
    unrelated(baseline.store, "EV-shared")
    resume(baseline)

    # Race: recovery reads, THEN the unrelated event lands, the append collides, retry wins.
    race = crashed_apply_ledger()
    race.store._crash_on = None  # type: ignore[attr-defined]
    race.store._trigger = EventType.INTENT_OBJECT_SYNTHESIZED  # type: ignore[attr-defined]
    race.store._inject = lambda s: unrelated(s, "EV-shared")  # type: ignore[attr-defined]
    race.store._remaining = 1  # type: ignore[attr-defined]
    race.store.__class__ = InjectingStore
    resume(race)

    baseline_types = stored_types(baseline)
    race_types = stored_types(race)
    assert baseline_types == race_types
    assert baseline_types[-3:] == [
        EventType.INTENT_SYNTHESIS_DECIDED,
        EventType.EVIDENCE_INGESTED,
        EventType.INTENT_OBJECT_SYNTHESIZED,
    ]
    assert state_of(race).model_dump(mode="json") == state_of(baseline).model_dump(mode="json")


# --- ordering and reporting -------------------------------------------------------------------


def test_recovery_reports_in_processing_order_and_reloads_the_remaining_set() -> None:
    ledger = crashed_apply_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    outcome = resume(ledger)
    assert isinstance(outcome.applied_proposal_ids, tuple)
    assert isinstance(outcome.invalidated_proposal_ids, tuple)
    assert isinstance(outcome.contention_exhausted_proposal_ids, tuple)
    assert isinstance(outcome.remaining_incomplete_proposal_ids, tuple)
    assert outcome.remaining_incomplete_proposal_ids == incomplete_proposal_ids(
        state_of(ledger).intent_synthesis
    )


def test_the_lifecycle_projection_still_has_exactly_four_planes() -> None:
    from foundry.domain.intent_synthesis_state import IntentSynthesisState

    assert set(IntentSynthesisState.model_fields) == {
        "decisions",
        "applied_proposal_ids",
        "invalidated_proposal_ids",
        "retirements",
    }


def test_no_retry_or_recovery_event_type_was_added() -> None:
    names = {e.name for e in EventType}
    assert not {n for n in names if "RETRY" in n or "RECOVERY" in n}


# --- structural guarantees, asserted against the source itself ---------------------------


def _recovery_source() -> str:
    """The body of the recovery functions only, excluding the T8 normal path."""
    import inspect

    from foundry.application import intent_synthesis as module

    return "\n".join(
        inspect.getsource(fn)
        for fn in (
            module.resume_incomplete_synthesis,
            module._recover_one,
            module._invalidated_event,
            module._synthesized_event,
        )
    )


def test_recovery_never_reroutes() -> None:
    """C12 as a structural fact, not merely an observed behaviour.

    After DECIDED is durable the decision is a settled fact; recovery reads it from the
    record. Calling the router again would recompute it under whatever state happens to
    hold later, which is exactly the silent replacement C12 forbids.
    """
    assert "route_intent_synthesis" not in _recovery_source()


def test_recovery_never_reaches_a_provider() -> None:
    assert ".synthesize(" not in _recovery_source()
    assert "IntentSynthesizer" not in _recovery_source()


def test_the_recovery_api_cannot_even_accept_a_synthesizer() -> None:
    import inspect

    from foundry.application.intent_synthesis import resume_incomplete_synthesis

    params = set(inspect.signature(resume_incomplete_synthesis).parameters)
    assert params == {"store", "project_id", "clock"}
    assert not params & {"synthesizer", "policy", "human_actor_id", "synthesis_run_id_factory"}


def test_the_only_provider_call_site_is_the_t8_normal_path() -> None:
    source = pathlib.Path("src/foundry/application/intent_synthesis.py").read_text()
    assert source.count(".synthesize(") == 1
    assert "result = synthesizer.synthesize(context.request)" in source


def test_no_recovery_metadata_leaked_into_the_durable_projection() -> None:
    source = pathlib.Path("src/foundry/domain/intent_synthesis_state.py").read_text()
    for forbidden in ("retries", "recovery_jobs", "attempts", "locks", "leases", "errors"):
        assert f"{forbidden}:" not in source
