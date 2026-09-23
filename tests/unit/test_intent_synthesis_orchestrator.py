"""T8 — the orchestrator that connects compile → synthesize → validate → govern → apply.

This is the first task where the finished pieces become one uninterrupted path, so the
tests are mostly about *boundaries* rather than happy-path plumbing:

* the synthesizer is never called when nothing is eligible (the T7/T8 no-call fence);
* nothing a model returned becomes durable before the whole result has been validated;
* the decision is appended against exactly the state it was computed from (C12);
* the effect is built from the DURABLE decision record, never from ephemeral context;
* a changed world after DECIDED leaves the proposal *incomplete* — T8 never invalidates
  and never retries, because terminalisation is T9's.
"""

from __future__ import annotations

import pytest

from foundry.application.intent_synthesis import (
    IntentSynthesisEffectPreconditionChanged,
    IntentSynthesisRunOutcome,
    IntentSynthesisSnapshotChanged,
    _append_at_state,
    _revalidate_snapshot,
    effect_invalidation_reason,
    synthesize_intent,
)
from foundry.application.intent_synthesis_context import (
    IntentSynthesisResultError,
    compile_intent_synthesis_context,
    validate_intent_synthesis_result,
)
from foundry.application.semantic_reducer import claim_id_for
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    RelationType,
    SourceKind,
)
from foundry.domain.events import (
    DerivationPayload,
    EventEnvelope,
    EventType,
    IntentObjectPayload,
)
from foundry.domain.gaps import GapKind, GapStatus
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisPolicy,
    IntentSynthesisResult,
    IntentSynthesisRoute,
    InvalidationReason,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
    replacement_scope_covers,
    validate_synthesis_actor,
)
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.intent_synthesis_state import incomplete_proposal_ids
from foundry.domain.semantic import Requirement
from foundry.domain.semantic_judgment import SupersedeProposal
from foundry.intelligence.proposals import GapProposal
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError
from tests.unit._t8_fixtures import (
    AI,
    CLAIM,
    DECIDED_AT,
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

POLICY = IntentSynthesisPolicy()


def proposal(
    model_proposal_id: str = "p1",
    *,
    disposition: IntentDisposition = IntentDisposition.NEW,
    statement: str = "Refunds must complete within thirty days.",
    basis_claim_ids: tuple[str, ...] = (CLAIM,),
    relates_to_object_id: str | None = None,
    confidence: float | None = None,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=model_proposal_id,
        disposition=disposition,
        statement=statement,
        rationale="the live claim states thirty days",
        basis_claim_ids=basis_claim_ids,
        relates_to_object_id=relates_to_object_id,
        confidence=confidence,
    )


def gap_proposal(
    proposal_id: str = "g1",
    *,
    kind: GapKind = GapKind.AMBIGUITY,
    subject_key: str = "refund-window",
    description: str = "Cannot tell whether thirty days is calendar or business days.",
    blocking: bool = True,
    confidence: float = 0.4,
    source_event_ids: tuple[str, ...] = (),
    affected_proposal_ids: tuple[str, ...] = (),
) -> GapProposal:
    return GapProposal(
        proposal_id=proposal_id,
        kind=kind,
        subject_key=subject_key,
        description=description,
        blocking=blocking,
        confidence=confidence,
        source_event_ids=source_event_ids,
        affected_proposal_ids=affected_proposal_ids,
    )


def run(
    ledger: Ledger,
    *results: IntentSynthesisResult,
    fingerprint=AI,  # type: ignore[no-untyped-def]
    human_actor_id: str | None = None,
    scope: str = SCOPE,
    run_ids: tuple[str, ...] = (RUN_ID,),
    policy: IntentSynthesisPolicy = POLICY,
) -> tuple[IntentSynthesisRunOutcome, ScriptedSynthesizer]:
    synthesizer = ScriptedSynthesizer(*results, fingerprint=fingerprint)
    outcome = synthesize_intent(
        ledger.store,
        project_id=PROJECT,
        scope=scope,
        synthesizer=synthesizer,
        policy=policy,
        clock=fixed_clock(),
        synthesis_run_id_factory=run_id_factory(*run_ids),
        human_actor_id=human_actor_id,
    )
    return outcome, synthesizer


def synthesis_gaps(ledger: Ledger) -> dict[str, IntentSynthesisGap]:
    return {
        gap_id: gap
        for gap_id, gap in ledger.state().gaps.items()
        if isinstance(gap, IntentSynthesisGap)
    }


def identity_for(model_proposal_id: str = "p1", run_id: str = RUN_ID) -> SynthesisIdentity:
    return SynthesisIdentity(
        project_id=PROJECT, synthesis_run_id=run_id, model_proposal_id=model_proposal_id
    )


# --- no eligible request: the provider is never reached ---------------------------------------


def test_an_open_locus_yields_no_request_no_gap_and_no_provider_call() -> None:
    """OPEN has nothing to synthesize and is not a gap either (spec §16)."""
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))

    outcome, synthesizer = run(ledger)

    assert synthesizer.calls == 0
    assert outcome.decisions == ()
    assert outcome.recorded_gap_ids == ()
    assert synthesis_gaps(ledger) == {}


def test_a_disputed_locus_records_a_scoped_contradiction_gap_without_calling_the_provider() -> None:
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.ingest("EV-2")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-c1", ADDRESS, "EV-1", text="seven days"))
    ledger.apply(assert_claim("J-c2", ADDRESS, "EV-2", text="thirty days"))
    from foundry.domain.semantic_judgment import ConflictsWithProposal

    ledger.apply(
        judgment(
            "J-conf",
            ConflictsWithProposal(
                claim_a=claim_id_for(PROJECT, "J-c1"), claim_b=claim_id_for(PROJECT, "J-c2")
            ),
            ("EV-1",),
        )
    )

    outcome, synthesizer = run(ledger)

    assert synthesizer.calls == 0
    assert outcome.decisions == ()
    gaps = synthesis_gaps(ledger)
    assert len(gaps) == 1
    gap = next(iter(gaps.values()))
    assert gap.kind is GapKind.CONTRADICTION
    assert gap.scope == (SCOPE,)
    assert gap.blocking is True
    assert gap.status is GapStatus.OPEN
    assert gap.materiality is None
    assert gap.risk is None
    assert gap.confidence is None
    assert gap.affected_object_ids == ()
    assert gap.subject_key is None
    assert gap.model_gap_proposal_id is None
    assert outcome.recorded_gap_ids == (gap.id,)


def test_an_undecided_claim_records_a_scoped_missing_information_gap() -> None:
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-c1", ADDRESS, "EV-1", undecided=True))

    outcome, synthesizer = run(ledger)

    assert synthesizer.calls == 0
    gaps = synthesis_gaps(ledger)
    kinds = {gap.kind for gap in gaps.values()}
    assert GapKind.MISSING_INFORMATION in kinds
    blocker_gap = next(g for g in gaps.values() if g.kind is GapKind.MISSING_INFORMATION)
    assert blocker_gap.scope == (SCOPE,)
    assert blocker_gap.locus_representative_id is not None
    assert blocker_gap.affected_claim_ids == (claim_id_for(PROJECT, "J-c1"),)
    assert outcome.recorded_gap_ids == tuple(sorted(gaps))


def test_a_runtime_blocker_gap_uses_gap_recorded_never_ambiguity_detected() -> None:
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-c1", ADDRESS, "EV-1", undecided=True))

    run(ledger)

    appended = ledger.store.appended_types
    assert EventType.GAP_RECORDED in appended
    assert EventType.AMBIGUITY_DETECTED not in appended


def test_blocked_and_eligible_loci_coexist_and_the_provider_sees_only_the_eligible_basis() -> None:
    """A blocked locus is recorded AND withheld; the model never learns it existed."""
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.ingest("EV-2")
    ledger.apply(create_address("J-good", "EV-1", subject="Refund window"))
    ledger.apply(create_address("J-bad", "EV-2", subject="Chargeback window"))
    from foundry.application.semantic_reducer import address_id_for

    good = address_id_for(PROJECT, "J-good")
    bad = address_id_for(PROJECT, "J-bad")
    ledger.apply(assert_claim("J-c-good", good, "EV-1"))
    ledger.apply(assert_claim("J-c-bad", bad, "EV-2", undecided=True))
    good_claim = claim_id_for(PROJECT, "J-c-good")

    outcome, synthesizer = run(
        ledger,
        IntentSynthesisResult(proposals=(proposal(basis_claim_ids=(good_claim,)),)),
    )

    assert synthesizer.calls == 1
    request = synthesizer.requests[0]
    shown = {b.locus_representative_id for b in request.basis}
    assert shown == {good}
    assert bad not in shown
    gaps = synthesis_gaps(ledger)
    assert {g.locus_representative_id for g in gaps.values()} == {bad}
    assert outcome.recorded_gap_ids == tuple(sorted(gaps))


# --- exactly one invocation, with exactly the bounded request ---------------------------------


def test_an_eligible_scope_invokes_the_synthesizer_exactly_once_with_the_t7_request() -> None:
    from foundry.application.intent_synthesis_context import compile_intent_synthesis_context

    ledger = eligible_ledger()
    expected = compile_intent_synthesis_context(ledger.state(), scope=SCOPE).request

    _, synthesizer = run(ledger, IntentSynthesisResult(proposals=(proposal(),)))

    assert synthesizer.calls == 1
    assert synthesizer.requests[0] == expected


def test_an_empty_scope_is_refused() -> None:
    ledger = eligible_ledger()
    with pytest.raises(ValueError, match="scope"):
        run(ledger, scope="")


def test_the_run_id_factory_is_called_exactly_once_and_must_return_a_non_empty_id() -> None:
    ledger = eligible_ledger()
    factory = run_id_factory(RUN_ID)
    synthesize_intent(
        ledger.store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),))),
        policy=POLICY,
        clock=fixed_clock(),
        synthesis_run_id_factory=factory,
        human_actor_id=None,
    )
    assert factory.calls == [RUN_ID]  # type: ignore[attr-defined]


def test_an_empty_synthesis_run_id_is_refused() -> None:
    ledger = eligible_ledger()
    with pytest.raises(ValueError, match="synthesis_run_id"):
        run(ledger, IntentSynthesisResult(proposals=(proposal(),)), run_ids=("",))


# --- authorship is checked BEFORE the provider is reached -------------------------------------


def test_a_malformed_human_pairing_is_refused_before_the_synthesizer_is_called() -> None:
    """A gap-only result must not let a malformed caller past the authorship contract."""
    ledger = eligible_ledger()
    synthesizer = ScriptedSynthesizer(
        IntentSynthesisResult(gap_proposals=(gap_proposal(),)), fingerprint=HUMAN
    )
    with pytest.raises(ValueError):
        synthesize_intent(
            ledger.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=synthesizer,
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
            human_actor_id="human://mallory",
        )
    assert synthesizer.calls == 0


def test_a_non_human_author_may_not_carry_a_human_actor_id() -> None:
    ledger = eligible_ledger()
    synthesizer = ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),)))
    with pytest.raises(ValueError):
        synthesize_intent(
            ledger.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=synthesizer,
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
            human_actor_id=HUMAN_ACTOR,
        )
    assert synthesizer.calls == 0


def test_the_shared_actor_validator_states_only_the_pairing_law() -> None:
    validate_synthesis_actor(AI, None)
    validate_synthesis_actor(HUMAN, HUMAN_ACTOR)
    with pytest.raises(ValueError):
        validate_synthesis_actor(HUMAN, None)
    with pytest.raises(ValueError):
        validate_synthesis_actor(HUMAN, "human://mallory")
    with pytest.raises(ValueError):
        validate_synthesis_actor(AI, HUMAN_ACTOR)


# --- C24: Slice-1 result exclusivity ----------------------------------------------------------


def test_an_empty_result_is_a_structural_failure() -> None:
    """Synthesis must not silently refuse with no reason."""
    ledger = eligible_ledger()
    with pytest.raises(IntentSynthesisResultError, match="C24|empty"):
        run(ledger, IntentSynthesisResult())


def test_a_mixed_result_is_a_structural_failure() -> None:
    """Frozen GapProposal cannot say which locus its gap belongs to, so Slice 1 refuses."""
    ledger = eligible_ledger()
    with pytest.raises(IntentSynthesisResultError, match="C24|both"):
        run(
            ledger,
            IntentSynthesisResult(proposals=(proposal(),), gap_proposals=(gap_proposal(),)),
        )


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(gap_proposal(kind=GapKind.STALE_EVIDENCE), id="non-ambiguity-kind"),
        pytest.param(gap_proposal(kind=GapKind.MISSING_AUTHORITY), id="runtime-structural-kind"),
        pytest.param(gap_proposal(blocking=False), id="non-blocking"),
        pytest.param(gap_proposal(source_event_ids=("EVT-seed-1",)), id="invented-source-events"),
        pytest.param(gap_proposal(affected_proposal_ids=("p1",)), id="affected-proposals"),
    ],
)
def test_a_malformed_model_gap_is_refused_and_nothing_model_derived_is_written(
    bad: GapProposal,
) -> None:
    ledger = eligible_ledger()
    before = len(ledger.store.appends)
    with pytest.raises(IntentSynthesisResultError):
        run(ledger, IntentSynthesisResult(gap_proposals=(bad,)))
    assert ledger.store.appends[before:] == []


def test_duplicate_model_gap_ids_are_refused() -> None:
    ledger = eligible_ledger()
    with pytest.raises(IntentSynthesisResultError, match="duplicate"):
        run(
            ledger,
            IntentSynthesisResult(
                gap_proposals=(gap_proposal("g1"), gap_proposal("g1", subject_key="other"))
            ),
        )


def test_duplicate_kind_and_subject_key_identities_are_refused() -> None:
    ledger = eligible_ledger()
    with pytest.raises(IntentSynthesisResultError, match="duplicate"):
        run(
            ledger,
            IntentSynthesisResult(
                gap_proposals=(gap_proposal("g1"), gap_proposal("g2", subject_key="refund-window"))
            ),
        )


# --- model AMBIGUITY becomes a durable synthesis gap ------------------------------------------


def test_a_legal_model_ambiguity_becomes_a_durable_intent_synthesis_gap() -> None:
    ledger = eligible_ledger()
    outcome, _ = run(ledger, IntentSynthesisResult(gap_proposals=(gap_proposal(confidence=0.73),)))

    gaps = synthesis_gaps(ledger)
    assert len(gaps) == 1
    gap = next(iter(gaps.values()))
    assert gap.kind is GapKind.AMBIGUITY
    assert gap.description == "Cannot tell whether thirty days is calendar or business days."
    assert gap.blocking is True
    assert gap.scope == (SCOPE,)
    assert gap.confidence == 0.73
    assert gap.subject_key == "refund-window"
    assert gap.model_gap_proposal_id == "g1"
    assert gap.materiality is None
    assert gap.risk is None
    assert gap.affected_object_ids == ()
    assert gap.locus_representative_id is None
    assert gap.affected_claim_ids == ()
    assert outcome.recorded_gap_ids == (gap.id,)
    assert outcome.decisions == ()
    assert EventType.AMBIGUITY_DETECTED not in ledger.store.appended_types
    assert EventType.INTENT_SYNTHESIS_DECIDED not in ledger.store.appended_types


@pytest.mark.parametrize("value", [0.0, 0.73, 1.0])
def test_model_gap_confidence_is_preserved_exactly(value: float) -> None:
    ledger = eligible_ledger()
    run(ledger, IntentSynthesisResult(gap_proposals=(gap_proposal(confidence=value),)))
    gap = next(iter(synthesis_gaps(ledger).values()))
    assert gap.confidence == value
    assert gap.risk is None
    assert gap.materiality is None


def test_the_raw_model_gap_id_never_becomes_the_durable_gap_id() -> None:
    ledger = eligible_ledger()
    run(ledger, IntentSynthesisResult(gap_proposals=(gap_proposal("g1"),)))
    gap = next(iter(synthesis_gaps(ledger).values()))
    assert gap.id != "g1"
    assert gap.id.startswith("GAP-SYN-")
    assert len(gap.id) == len("GAP-SYN-") + 64


def test_model_supplied_source_event_ids_are_never_persisted() -> None:
    """Rejected outright rather than silently dropped — see the malformed-gap suite."""
    ledger = eligible_ledger()
    with pytest.raises(IntentSynthesisResultError):
        run(
            ledger,
            IntentSynthesisResult(gap_proposals=(gap_proposal(source_event_ids=("EVT-seed-1",)),)),
        )
    assert "source_event_ids" not in IntentSynthesisGap.model_fields


# --- deterministic durable ids ----------------------------------------------------------------


def test_the_same_run_reproduces_byte_identical_gap_and_event_ids() -> None:
    first = eligible_ledger()
    second = eligible_ledger()
    run(first, IntentSynthesisResult(gap_proposals=(gap_proposal(),)))
    run(second, IntentSynthesisResult(gap_proposals=(gap_proposal(),)))
    assert tuple(synthesis_gaps(first)) == tuple(synthesis_gaps(second))
    gap_events_first = [
        e.event_id for e, _ in first.store.appends if e.event_type is EventType.GAP_RECORDED
    ]
    gap_events_second = [
        e.event_id for e, _ in second.store.appends if e.event_type is EventType.GAP_RECORDED
    ]
    assert gap_events_first == gap_events_second
    assert all(e.startswith("EVT-") and len(e) == len("EVT-") + 64 for e in gap_events_first)


def test_the_same_model_gap_id_in_a_different_run_yields_a_different_durable_id() -> None:
    first = eligible_ledger()
    second = eligible_ledger()
    run(first, IntentSynthesisResult(gap_proposals=(gap_proposal(),)), run_ids=("RUN-1",))
    run(second, IntentSynthesisResult(gap_proposals=(gap_proposal(),)), run_ids=("RUN-2",))
    assert set(synthesis_gaps(first)).isdisjoint(set(synthesis_gaps(second)))


def test_a_runtime_blocker_gap_id_is_derived_not_the_locus_id() -> None:
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-c1", ADDRESS, "EV-1", undecided=True))
    run(ledger)
    gap = next(iter(synthesis_gaps(ledger).values()))
    assert gap.id != ADDRESS
    assert gap.id.startswith("GAP-SYN-")
    assert gap.locus_representative_id == ADDRESS


def test_every_t8_event_carries_the_synthesis_run_id_as_correlation() -> None:
    ledger = eligible_ledger()
    before = len(ledger.store.appends)
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    produced = [event for event, _ in ledger.store.appends[before:]]
    assert produced
    assert all(event.correlation_id == RUN_ID for event in produced)
    synthesized = [e for e in produced if e.event_type is EventType.INTENT_OBJECT_SYNTHESIZED]
    decided = [e for e in produced if e.event_type is EventType.INTENT_SYNTHESIS_DECIDED]
    assert len(synthesized) == 1 and len(decided) == 1
    assert synthesized[0].causation_id == decided[0].event_id


# --- origin derivation ------------------------------------------------------------------------


def _origin_of(ledger: Ledger) -> SynthesisOrigin:
    record = ledger.state().intent_synthesis.decisions[identity_for().proposal_instance_id]
    return record.origin


def test_a_human_author_with_a_matching_actor_yields_human_stated() -> None:
    ledger = eligible_ledger()
    ledger.record_object(authority_record())
    run(
        ledger,
        IntentSynthesisResult(proposals=(proposal(),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    assert _origin_of(ledger) is SynthesisOrigin.HUMAN_STATED


def test_research_only_basis_with_a_non_human_author_yields_research_derived() -> None:
    ledger = eligible_ledger(evidence_kind=SourceKind.RESEARCH)
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    assert _origin_of(ledger) is SynthesisOrigin.RESEARCH_DERIVED


def test_any_non_research_evidence_in_the_cited_basis_yields_ai_inferred() -> None:
    ledger = eligible_ledger(evidence_kind=SourceKind.DOCUMENT)
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    assert _origin_of(ledger) is SynthesisOrigin.AI_INFERRED


def test_a_canonical_human_authored_basis_does_not_launder_an_ai_author_into_human_stated() -> None:
    """C9/I22 anti-laundering: origin follows the AUTHOR, never the basis."""
    ledger = eligible_ledger(evidence_kind=SourceKind.HUMAN, claim_authority=Authority.CANONICAL)
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    assert _origin_of(ledger) is SynthesisOrigin.AI_INFERRED


# --- routing outcomes -------------------------------------------------------------------------


def test_a_human_author_with_covering_authority_applies_as_canonical() -> None:
    ledger = eligible_ledger()
    ledger.record_object(authority_record())
    outcome, _ = run(
        ledger,
        IntentSynthesisResult(proposals=(proposal(),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]
    obj = ledger.state().objects[identity_for().object_id("REQ")]
    assert obj.authority is Authority.CANONICAL


def test_an_ai_author_applies_as_proposed() -> None:
    ledger = eligible_ledger()
    outcome, _ = run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]
    obj = ledger.state().objects[identity_for().object_id("REQ")]
    assert obj.authority is Authority.PROPOSED


def test_a_human_author_without_covering_authority_requires_a_human() -> None:
    ledger = eligible_ledger()
    outcome, _ = run(
        ledger,
        IntentSynthesisResult(proposals=(proposal(),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.REQUIRE_HUMAN]
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in ledger.store.appended_types


# --- C12: the decision is appended against exactly the state it was computed from -------------


def test_the_decided_event_is_appended_at_the_sequence_the_decision_was_computed_against() -> None:
    ledger = eligible_ledger()
    sequence_before = ledger.state().last_sequence
    ledger.store.current_sequence_calls.clear()

    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))

    decided = [
        (event, expected)
        for event, expected in ledger.store.appends
        if event.event_type is EventType.INTENT_SYNTHESIS_DECIDED
    ]
    assert len(decided) == 1
    assert decided[0][1] == sequence_before


def test_the_appender_never_asks_the_store_for_a_sequence() -> None:
    """The caller's state IS the expected prefix; asking the store would erase C12."""
    ledger = eligible_ledger()
    ledger.store.current_sequence_calls.clear()
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    assert ledger.store.current_sequence_calls == []


def test_a_reducer_invalid_event_never_reaches_the_store() -> None:
    """P2: reducer refusal means no ledger write — proven where the store would say yes.

    The event below is well-formed, uniquely identified and at the right sequence, so
    the store would accept it happily. Only the reducer knows it is unapplicable: it
    names a proposal that has no durable decision. If the dry run were removed, the
    ledger would take it.
    """
    ledger = eligible_ledger()
    state = ledger.state()
    orphan = SynthesisIdentity(
        project_id=PROJECT, synthesis_run_id="RUN-orphan", model_proposal_id="ghost"
    )
    event = EventEnvelope(
        event_id=orphan.event_id("SYNTHESIZED"),
        project_id=PROJECT,
        event_type=EventType.INTENT_OBJECT_SYNTHESIZED,
        occurred_at=DECIDED_AT,
        correlation_id="RUN-orphan",
        payload=IntentObjectPayload(
            object=existing_requirement(orphan.object_id("REQ")),
            basis_claim_ids=(CLAIM,),
            proposal_instance_id=orphan.proposal_instance_id,
        ),
    )
    before = len(ledger.store.appends)
    stream_before = len(ledger.store.load(PROJECT))

    with pytest.raises(ValueError, match="no durable decision"):
        _append_at_state(ledger.store, state, event)

    assert ledger.store.appends[before:] == []
    assert len(ledger.store.load(PROJECT)) == stream_before


def test_the_same_proposal_decided_twice_does_not_extend_the_ledger() -> None:
    """P2 dry-run discipline, shared with SemanticGovernor.

    The same proposal decided twice in one project would mint the same deterministic
    DECIDED event id, which the reducer refuses. The refusal must happen in the dry run,
    so the ledger is left exactly as it was rather than carrying a rejected event.
    """
    ledger = eligible_ledger()
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    settled = len(ledger.store.appends)
    stream_length = len(ledger.store.load(PROJECT))

    with pytest.raises((ValueError, DuplicateEventError)):
        run(ledger, IntentSynthesisResult(proposals=(proposal(),)))

    assert len(ledger.store.load(PROJECT)) == stream_length
    assert ledger.state().last_sequence == stream_length
    assert len(ledger.store.appends) >= settled


# --- NO_CHANGE is terminal at DECIDED ---------------------------------------------------------


def test_existing_unchanged_decides_no_change_and_produces_no_object_and_no_gap() -> None:
    ledger = eligible_ledger()
    ledger.canonicalize(existing_requirement("REQ-OLD", basis_claim_ids=(CLAIM,)))
    outcome, _ = run(
        ledger,
        IntentSynthesisResult(
            proposals=(
                proposal(
                    disposition=IntentDisposition.EXISTING_UNCHANGED,
                    relates_to_object_id="REQ-OLD",
                ),
            )
        ),
    )
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.NO_CHANGE]
    state = ledger.state()
    assert identity_for().object_id("REQ") not in state.objects
    assert synthesis_gaps(ledger) == {}
    assert outcome.recorded_gap_ids == ()
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in ledger.store.appended_types


# --- Requirement construction from the durable record -----------------------------------------


def test_the_synthesized_requirement_is_built_exactly_from_the_durable_decision() -> None:
    ledger = eligible_ledger()
    run(ledger, IntentSynthesisResult(proposals=(proposal(confidence=0.72),)))

    state = ledger.state()
    identity = identity_for()
    record = state.intent_synthesis.decisions[identity.proposal_instance_id]
    obj = state.objects[identity.object_id("REQ")]
    assert isinstance(obj, Requirement)

    assert obj.id == identity.object_id("REQ")
    assert obj.statement == "Refunds must complete within thirty days."
    assert obj.authority is record.assigned_authority is Authority.PROPOSED
    assert obj.confidence == 0.72
    assert obj.materiality is Materiality.LOW
    assert obj.requires_metric is False
    assert obj.requires_verification is False
    assert obj.created_at == record.decided_at == DECIDED_AT
    assert obj.lifecycle is LifecycleStatus.ACTIVE
    assert obj.revision == 1
    assert tuple(obj.scope) == (SCOPE,)
    assert sorted((r.relation_type, r.target_id) for r in obj.relations) == [
        (RelationType.DERIVED_FROM, CLAIM)
    ]
    assert obj.provenance.source_kind is SourceKind.SYSTEM
    assert obj.provenance.source_ref == RUN_ID
    assert obj.provenance.source_event_ids == (record.decision_event_id,)


def test_a_human_stated_requirement_records_human_provenance_pointing_at_the_actor() -> None:
    ledger = eligible_ledger()
    ledger.record_object(authority_record())
    run(
        ledger,
        IntentSynthesisResult(proposals=(proposal(),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    state = ledger.state()
    record = state.intent_synthesis.decisions[identity_for().proposal_instance_id]
    obj = state.objects[identity_for().object_id("REQ")]
    assert obj.provenance.source_kind is SourceKind.HUMAN
    assert obj.provenance.source_ref == HUMAN_ACTOR
    assert obj.provenance.source_event_ids == (record.decision_event_id,)


def test_research_derived_still_stores_system_provenance_not_research() -> None:
    """Research-derivedness is derived later from the basis evidence, never stored here."""
    ledger = eligible_ledger(evidence_kind=SourceKind.RESEARCH)
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    obj = ledger.state().objects[identity_for().object_id("REQ")]
    assert obj.provenance.source_kind is SourceKind.SYSTEM


@pytest.mark.parametrize("value", [None, 0.0, 0.72, 1.0])
def test_requirement_confidence_carries_the_proposal_value_exactly(value: float | None) -> None:
    ledger = eligible_ledger()
    run(ledger, IntentSynthesisResult(proposals=(proposal(confidence=value),)))
    obj = ledger.state().objects[identity_for().object_id("REQ")]
    assert obj.confidence == value if value is not None else obj.confidence is None


# --- the uninterrupted APPLY effect -----------------------------------------------------------


def test_an_uninterrupted_apply_lands_object_edges_and_the_applied_marker() -> None:
    ledger = eligible_ledger()
    outcome, _ = run(ledger, IntentSynthesisResult(proposals=(proposal(),)))

    state = ledger.state()
    identity = identity_for()
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]
    assert identity.object_id("REQ") in state.objects
    assert identity.proposal_instance_id in state.intent_synthesis.applied_proposal_ids
    assert identity.proposal_instance_id not in state.intent_synthesis.invalidated_proposal_ids
    children = {edge.child_id for edge in state.semantic.derivations}
    assert identity.object_id("REQ") in children
    assert incomplete_proposal_ids(state.intent_synthesis) == ()


def _replacement_ledger(store: RecordingStore | None = None) -> tuple[Ledger, str]:
    """A stale REQ-OLD plus a live replacement basis claim at the same locus."""
    ledger = Ledger(store)
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
        DerivationPayload and EventType.DERIVATION_RECORDED,
        DerivationPayload(child_id="REQ-OLD", parent_id="J-old"),
    )
    ledger.apply(
        judgment(
            "J-sup", SupersedeProposal(target_judgment_id="J-old", reason="corrected"), ("EV-2",)
        )
    )
    return ledger, new_claim


def test_a_replacement_retires_its_target_and_records_the_retirement() -> None:
    ledger, new_claim = _replacement_ledger()
    outcome, _ = run(
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
    state = ledger.state()
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]
    assert state.objects["REQ-OLD"].lifecycle is LifecycleStatus.SUPERSEDED
    assert [r.retired_object_id for r in state.intent_synthesis.retirements] == ["REQ-OLD"]
    assert state.intent_synthesis.retirements[0].replaced_by_object_id == identity_for().object_id(
        "REQ"
    )


# --- preflight before any model-derived DECIDED -----------------------------------------------


def test_two_proposals_replacing_the_same_target_are_refused_before_any_decision() -> None:
    ledger, new_claim = _replacement_ledger()
    before = len(ledger.store.appends)
    with pytest.raises(IntentSynthesisResultError, match="same target|twice"):
        run(
            ledger,
            IntentSynthesisResult(
                proposals=(
                    proposal(
                        "p1",
                        disposition=IntentDisposition.REPLACES_STALE,
                        relates_to_object_id="REQ-OLD",
                        basis_claim_ids=(new_claim,),
                    ),
                    proposal(
                        "p2",
                        disposition=IntentDisposition.REPLACES_STALE,
                        relates_to_object_id="REQ-OLD",
                        basis_claim_ids=(new_claim,),
                        statement="Refunds within thirty calendar days.",
                    ),
                )
            ),
        )
    assert ledger.store.appends[before:] == []


def test_a_replacement_that_would_narrow_scope_is_refused_before_any_decision() -> None:
    """C21 preflight: discovered before DECIDED, not after, by the reducer."""
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.ingest("EV-2")
    ledger.apply(create_address("J-addr", "EV-1", scope=(SCOPE,)))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-old", ADDRESS, "EV-1", text="seven days"))
    ledger.apply(assert_claim("J-new", ADDRESS, "EV-2", text="thirty days"))
    old_claim = claim_id_for(PROJECT, "J-old")
    new_claim = claim_id_for(PROJECT, "J-new")
    # A project-wide target: a (SCOPE,) replacement must not delete it.
    ledger.canonicalize(existing_requirement("REQ-OLD", scope=(), basis_claim_ids=(old_claim,)))
    ledger.append(
        EventType.DERIVATION_RECORDED, DerivationPayload(child_id="REQ-OLD", parent_id="J-old")
    )
    ledger.apply(
        judgment(
            "J-sup", SupersedeProposal(target_judgment_id="J-old", reason="corrected"), ("EV-2",)
        )
    )
    before = len(ledger.store.appends)
    with pytest.raises(IntentSynthesisResultError, match="cover|scope"):
        run(
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
    assert ledger.store.appends[before:] == []


def test_the_shared_c21_scope_law_has_one_implementation() -> None:
    assert replacement_scope_covers((), ()) is True
    assert replacement_scope_covers((), ("a",)) is True
    assert replacement_scope_covers(("a",), ()) is False
    assert replacement_scope_covers(("a", "b"), ("a",)) is True
    assert replacement_scope_covers(("a",), ("a", "b")) is False


# --- post-DECIDED change: T8 refuses the effect and leaves the decision incomplete ------------


class InterferingStore(RecordingStore):
    """Injects an external event immediately after the DECIDED append lands.

    This is how a test reproduces the real hazard: the world moved between the durable
    decision and its effect.
    """

    def __init__(self, inject) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._inject = inject
        self._fired = False

    def append(self, event, expected_sequence):  # type: ignore[no-untyped-def]
        stored = super().append(event, expected_sequence)
        if not self._fired and event.event_type is EventType.INTENT_SYNTHESIS_DECIDED:
            self._fired = True
            self._inject(self)
        return stored


def _ledger_on(store: RecordingStore) -> Ledger:
    ledger = Ledger(store)
    ledger.ingest("EV-1")
    ledger.apply(create_address("J-addr", "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    return ledger


def _run_with_interference(inject) -> tuple[Ledger, pytest.ExceptionInfo]:  # type: ignore[no-untyped-def]
    store = InterferingStore(inject)
    ledger = _ledger_on(store)
    with pytest.raises(IntentSynthesisEffectPreconditionChanged) as excinfo:
        run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    return ledger, excinfo


def test_a_basis_superseded_after_decided_refuses_the_effect_without_invalidating() -> None:
    def inject(store: RecordingStore) -> None:
        ledger = Ledger(store)
        ledger._n = 900
        ledger.apply(
            judgment(
                "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="wrong"), ("EV-1",)
            )
        )

    ledger, excinfo = _run_with_interference(inject)

    assert excinfo.value.reason is InvalidationReason.BASIS_CHANGED
    assert excinfo.value.proposal_instance_id == identity_for().proposal_instance_id
    state = ledger.state()
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in ledger.store.appended_types
    assert EventType.INTENT_SYNTHESIS_INVALIDATED not in ledger.store.appended_types
    assert identity_for().proposal_instance_id in incomplete_proposal_ids(state.intent_synthesis)


def test_an_unrelated_event_after_decided_fails_the_effect_append_with_concurrency() -> None:
    """Live preconditions still hold, but the expected prefix is still the DECIDED one."""

    def inject(store: RecordingStore) -> None:
        ledger = Ledger(store)
        ledger._n = 800
        ledger.ingest("EV-unrelated")

    store = InterferingStore(inject)
    ledger = _ledger_on(store)
    with pytest.raises(ConcurrencyError):
        run(ledger, IntentSynthesisResult(proposals=(proposal(),)))

    state = ledger.state()
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in stored_types(ledger)
    assert EventType.INTENT_SYNTHESIS_INVALIDATED not in stored_types(ledger)
    assert identity_for().proposal_instance_id in incomplete_proposal_ids(state.intent_synthesis)


def stored_types(ledger: Ledger) -> list[EventType]:
    """Event types that actually LANDED, as opposed to append attempts."""
    return [stored.event.event_type for stored in ledger.store.load(PROJECT)]


def test_a_target_that_stops_being_stale_after_decided_refuses_the_effect() -> None:
    """Restoring the superseded basis un-stales the target, so replacing it would now
    retire sound intent. The decision stands; only its effect is refused."""

    def inject(store: RecordingStore) -> None:
        interloper = Ledger(store)
        interloper._n = 600
        # Superseding the superseder restores J-old, so REQ-OLD is no longer stale.
        interloper.apply(
            judgment(
                "J-unsup",
                SupersedeProposal(target_judgment_id="J-sup", reason="the correction was wrong"),
                ("EV-2",),
            )
        )

    store = InterferingStore(inject)
    ledger, new_claim = _replacement_ledger(store)

    with pytest.raises(IntentSynthesisEffectPreconditionChanged) as excinfo:
        run(
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

    assert excinfo.value.reason is InvalidationReason.TARGET_CHANGED
    state = ledger.state()
    assert state.objects["REQ-OLD"].lifecycle is LifecycleStatus.ACTIVE
    assert state.intent_synthesis.retirements == ()
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in stored_types(ledger)
    assert EventType.INTENT_SYNTHESIS_INVALIDATED not in stored_types(ledger)
    assert identity_for().proposal_instance_id in incomplete_proposal_ids(state.intent_synthesis)


def test_t8_never_emits_an_invalidation_event() -> None:
    ledger = eligible_ledger()
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    assert EventType.INTENT_SYNTHESIS_INVALIDATED not in ledger.store.appended_types


# --- the shared effect-precondition classifier ------------------------------------------------


def test_effect_invalidation_reason_returns_none_when_the_effect_is_still_feasible() -> None:
    ledger = eligible_ledger()
    run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    state = ledger.state()
    record = state.intent_synthesis.decisions[identity_for().proposal_instance_id]
    assert effect_invalidation_reason(state, record) is None


def test_effect_invalidation_reason_reports_authority_changed_when_the_record_dies() -> None:
    ledger = eligible_ledger()
    ledger.record_object(authority_record("AUTH-1"))
    run(
        ledger,
        IntentSynthesisResult(proposals=(proposal(),)),
        fingerprint=HUMAN,
        human_actor_id=HUMAN_ACTOR,
    )
    state = ledger.state()
    record = state.intent_synthesis.decisions[identity_for().proposal_instance_id]
    assert effect_invalidation_reason(state, record) is None

    ledger.record_object(authority_record("AUTH-1", lifecycle=LifecycleStatus.SUPERSEDED))
    assert (
        effect_invalidation_reason(ledger.state(), record) is InvalidationReason.AUTHORITY_CHANGED
    )


# --- I13 negative control ---------------------------------------------------------------------


def test_a_compatible_extension_does_not_make_an_existing_requirement_stale() -> None:
    """Slice-1 deliberate behaviour until D5: more compatible information is not staleness."""
    ledger = eligible_ledger()
    ledger.canonicalize(existing_requirement("REQ-OLD", basis_claim_ids=(CLAIM,)))
    ledger.append(
        EventType.DERIVATION_RECORDED, DerivationPayload(child_id="REQ-OLD", parent_id="J-claim")
    )
    ledger.ingest("EV-2")
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-extra", ADDRESS, "EV-2", text="thirty days, calendar"))

    from foundry.application.intent_synthesis_context import compile_intent_synthesis_context

    context = compile_intent_synthesis_context(ledger.state(), scope=SCOPE)
    assert context.request is not None
    known = {k.object_id: k for k in context.request.known_intent_objects}
    assert known["REQ-OLD"].is_stale is False
    assert synthesis_gaps(ledger) == {}


# --- no direct state writes -------------------------------------------------------------------


def test_the_whole_run_is_reconstructable_from_the_event_store_alone() -> None:
    ledger = eligible_ledger()
    outcome, _ = run(ledger, IntentSynthesisResult(proposals=(proposal(),)))
    from foundry.application.replay import replay

    rebuilt = replay(PROJECT, ledger.store.load(PROJECT))
    assert identity_for().object_id("REQ") in rebuilt.objects
    assert isinstance(outcome, IntentSynthesisRunOutcome)
    assert outcome.synthesis_run_id == RUN_ID


def test_a_dead_basis_at_routing_time_refuses_to_write_a_decision() -> None:
    """The pre-decision snapshot guard, exercised directly.

    Within one ``synthesize_intent`` the request and the routing state are the same
    replay, so this guard cannot fire through the public path today — appending gaps
    does not move semantic state. It is kept as defence in depth for the moment T9
    completes a decision from a record whose request it never saw, and it is tested
    here rather than left as an unexercised claim.
    """
    ledger = eligible_ledger()
    state = ledger.state()
    validated = validate_intent_synthesis_result(
        state=state,
        request=compile_intent_synthesis_context(state, scope=SCOPE).request,
        result=IntentSynthesisResult(proposals=(proposal(),)),
    )
    _revalidate_snapshot(state, validated[0])

    ledger.apply(
        judgment(
            "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="withdrawn"), ("EV-1",)
        )
    )
    with pytest.raises(IntentSynthesisSnapshotChanged):
        _revalidate_snapshot(ledger.state(), validated[0])
