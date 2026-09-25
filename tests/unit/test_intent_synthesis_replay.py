"""T12 — replay exactness, determinism and backward compatibility. Slice-1 certification.

One question: **if the ledger is the only durable truth, can Foundry reconstruct exactly
the same Intent Engine state and exactly the same downstream contract without asking a
model again?**

The law being certified is that a model is compute used *before* durability. Once
``INTENT_SYNTHESIS_DECIDED`` and its effect exist, replay **reads** the decision; it never
re-derives it. So no ``IntentSynthesizer``, ``SemanticReasoner``, provider or prompt takes
part in reconstruction — only the reducer, applied to durable events.

Three independent reconstructions are compared: the ordinary one, one rebuilt purely from
each event's JSON document through the production ``parse_event``, and a second fresh
replay. "Byte-identical" here means canonical serialized value identity — never object
identity, never ``repr``, never pickle.

Backward compatibility is certified alongside it: a stream written before this slice
existed must replay unchanged, a state document without the additive ``intent_synthesis``
field must still validate, a legacy ``Gap`` must not be promoted to ``IntentSynthesisGap``
by the T7.1 union, and ``AMBIGUITY_DETECTED`` must remain detection-only.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.handoff import build_intent_decision_handoff
from foundry.application.handoff_v2 import (
    IntentDeliveryNotReadyError,
    build_intent_decision_handoff_v2,
)
from foundry.application.intent_synthesis import (
    resume_incomplete_synthesis,
    synthesize_intent,
)
from foundry.application.package import build_intent_package
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    RiskLevel,
    SourceKind,
)
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    GapPayload,
    SemanticObjectPayload,
    StoredEvent,
    parse_event,
)
from foundry.domain.evidence import evidence_item
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.handoff import (
    HANDOFF_VERSION,
    build_semantic_readiness,
    locus_in_scope,
)
from foundry.domain.handoff_v2 import build_intent_delivery_readiness
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisPolicy,
    IntentSynthesisResult,
    IntentSynthesisRoute,
    RequirementSynthesisProposal,
    SynthesisIdentity,
)
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.intent_synthesis_state import (
    IntentSynthesisState,
    incomplete_proposal_ids,
)
from foundry.domain.semantic import Actor, AuthorityRecord, Intent, Requirement
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.ports.intent_synthesizer import IntentSynthesisRequest

PROJECT = "PROJ-T12"
LEGACY_PROJECT = "PROJ-T12-LEGACY"
SCOPE = "payments"
AT = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
ALICE = "human://alice"
HUMAN = ReasonerFingerprint(provider="human", model=ALICE, policy_version="p1")
SYNTHESIS_POLICY = IntentSynthesisPolicy()
PROV = Provenance(source_kind=SourceKind.HUMAN, source_ref=ALICE)


# --- no network, ever ----------------------------------------------------------------


def _refuse_network(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("network access is forbidden in the replay certification")


@pytest.fixture(autouse=True, scope="module")
def socket_guard() -> Iterator[None]:
    patcher = pytest.MonkeyPatch()
    patcher.setattr(socket.socket, "connect", _refuse_network)
    patcher.setattr(socket, "create_connection", _refuse_network)
    try:
        yield
    finally:
        patcher.undo()


def test_socket_guard_is_live() -> None:
    with pytest.raises(RuntimeError, match="forbidden"), socket.socket() as sock:
        sock.connect(("127.0.0.1", 9))
    with pytest.raises(RuntimeError, match="forbidden"):
        socket.create_connection(("127.0.0.1", 9))


# --- canonical value identity ---------------------------------------------------------


def canonical_bytes(value: Any) -> bytes:
    """The ONE definition of "byte-identical" in this module.

    Canonical serialized value identity: the JSON document a model produces, rendered
    with sorted keys and no incidental whitespace. Never object identity, never ``repr``,
    never pickle — each of those can agree while the durable document differs, or differ
    while it does not.
    """
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def all_equal(*values: Any) -> bool:
    rendered = [canonical_bytes(v) for v in values]
    return all(r == rendered[0] for r in rendered)


# --- deterministic test-local scaffolding ---------------------------------------------


def _clock() -> Callable[[], datetime]:
    ticks = count()
    return lambda: AT.replace(minute=next(ticks) % 60)


def _id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks):03d}"


class Interrupted(RuntimeError):
    """Stands in for a crash between DECIDED and its effect."""


class CrashingStore:
    """Fault injection ONLY, to open the DECIDED→effect window. Not a second ledger."""

    def __init__(self, inner: InMemoryEventStore, crash_on: EventType | None) -> None:
        self._inner = inner
        self.crash_on = crash_on

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        if event.event_type is self.crash_on:
            raise Interrupted(f"crashed before {event.event_type.value}")
        return self._inner.append(event, expected_sequence)

    def load(self, project_id: str, after_sequence: int = 0) -> Any:
        return self._inner.load(project_id, after_sequence)

    def current_sequence(self, project_id: str) -> int:
        return self._inner.current_sequence(project_id)


class ScriptedIntentSynthesizer:
    """Deterministic double for the real port; counts calls so replay can prove zero."""

    def __init__(self, fingerprint: ReasonerFingerprint = HUMAN) -> None:
        self._fingerprint = fingerprint
        self._queue: list[IntentSynthesisResult] = []
        self.requests: list[IntentSynthesisRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    @property
    def calls(self) -> int:
        return len(self.requests)

    def script(self, result: IntentSynthesisResult) -> None:
        self._queue.append(result)

    def synthesize(self, request: IntentSynthesisRequest) -> IntentSynthesisResult:
        self.requests.append(request)
        return self._queue.pop(0)


def _judgment(
    judgment_id: str, proposal: JudgmentProposal, evidence_ids: tuple[str, ...]
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=evidence_ids,
        rationale="stated by the product owner",
        reasoner=HUMAN,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=AT,
    )


def _authority(
    object_id: str, scope: tuple[str, ...], project_id: str = PROJECT
) -> AuthorityRecord:
    return AuthorityRecord(
        id=object_id,
        project_id=project_id,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROV,
        created_at=AT,
        scope=scope,
        subject_id="intent",
        authorized_by=ALICE,
        rationale="alice owns this",
    )


def _intent(project_id: str = PROJECT) -> Intent:
    return Intent(
        id="INTENT-payments",
        project_id=project_id,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROV,
        created_at=AT,
        scope=(SCOPE,),
        mission="Refunds are fast and predictable.",
    )


def _actor(project_id: str = PROJECT) -> Actor:
    return Actor(
        id="ACTOR-customer",
        project_id=project_id,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROV,
        created_at=AT,
        scope=(SCOPE,),
        name="Customer",
        description="A person who requests a refund.",
    )


def _append_object(store: Any, project_id: str, event_type: EventType, obj: Any) -> StoredEvent:
    event = EventEnvelope(
        event_id=f"object-{obj.id}-{store.current_sequence(project_id)}",
        project_id=project_id,
        event_type=event_type,
        occurred_at=AT,
        payload=SemanticObjectPayload(object=obj),
    )
    return store.append(event, expected_sequence=store.current_sequence(project_id))


def _proposal(
    model_proposal_id: str,
    claim_id: str,
    *,
    statement: str,
    disposition: IntentDisposition = IntentDisposition.NEW,
    relates_to_object_id: str | None = None,
    confidence: float | None = 0.64,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=model_proposal_id,
        disposition=disposition,
        statement=statement,
        rationale="the live claim states it",
        basis_claim_ids=(claim_id,),
        relates_to_object_id=relates_to_object_id,
        confidence=confidence,
    )


def _object_id(model_proposal_id: str, run_id: str) -> str:
    return SynthesisIdentity(
        project_id=PROJECT, synthesis_run_id=run_id, model_proposal_id=model_proposal_id
    ).object_id("REQ")


def _instance_id(model_proposal_id: str, run_id: str) -> str:
    return SynthesisIdentity(
        project_id=PROJECT, synthesis_run_id=run_id, model_proposal_id=model_proposal_id
    ).proposal_instance_id


# --- the representative ledger: all four durable synthesis planes ----------------------

RUN_NEW = "RUN-new"
RUN_REPLACE = "RUN-replace"
RUN_DOOMED = "RUN-doomed"
REQ_A = _object_id("p-new", RUN_NEW)
REQ_B = _object_id("p-replace", RUN_REPLACE)
PID_A = _instance_id("p-new", RUN_NEW)
PID_B = _instance_id("p-replace", RUN_REPLACE)
PID_DOOMED = _instance_id("p-doomed", RUN_DOOMED)


def _build_representative_ledger() -> tuple[InMemoryEventStore, ScriptedIntentSynthesizer]:
    """Applied NEW, applied REPLACES_STALE with retirement, and an INVALIDATED APPLY.

    Built entirely through production orchestration so no plane passes merely by being
    empty and no ``IntentState`` is ever hand-assembled.
    """
    inner = InMemoryEventStore()
    store = CrashingStore(inner, crash_on=None)
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
    )
    synthesizer = ScriptedIntentSynthesizer()

    def ingest(evidence_id: str, content: str) -> None:
        governor.ingest(
            evidence_item(
                evidence_id=evidence_id,
                project_id=PROJECT,
                source_kind=SourceKind.HUMAN,
                source_ref=ALICE,
                content=content,
                observed_at=AT,
                scope=(SCOPE,),
            )
        )

    def create_address(judgment_id: str, evidence_id: str, subject: str) -> str:
        decision = governor.submit(
            _judgment(
                judgment_id,
                CreateAddressProposal(
                    candidate=SemanticCandidate(
                        candidate_id=f"CAND-{judgment_id}",
                        subject=subject,
                        facet="What is the rule?",
                        scope=(SCOPE,),
                        evidence_ids=(evidence_id,),
                    )
                ),
                (evidence_id,),
            ),
            human_actor_id=ALICE,
        )
        assert decision.route is AdmissionRoute.APPLY
        return address_id_for(PROJECT, judgment_id)

    def assert_claim(
        judgment_id: str,
        address_id: str,
        evidence_id: str,
        text: str,
        authority: Authority = Authority.INFERRED,
    ) -> str:
        decision = governor.submit(
            _judgment(
                judgment_id,
                AssertClaimProposal(
                    address_id=address_id,
                    predicate="rule",
                    value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
                    evidence_ids=(evidence_id,),
                    authority=authority,
                ),
                (evidence_id,),
            ),
            human_actor_id=ALICE,
        )
        assert decision.route is AdmissionRoute.APPLY
        return claim_id_for(PROJECT, judgment_id)

    def supersede(judgment_id: str, target: str, evidence_id: str) -> None:
        decision = governor.submit(
            _judgment(
                judgment_id,
                SupersedeProposal(target_judgment_id=target, reason="corrected"),
                (evidence_id,),
            ),
            human_actor_id=ALICE,
        )
        assert decision.route is AdmissionRoute.APPLY

    def synthesize(run_id: str, proposal: RequirementSynthesisProposal) -> Any:
        synthesizer.script(IntentSynthesisResult(proposals=(proposal,)))
        return synthesize_intent(
            store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=synthesizer,
            policy=SYNTHESIS_POLICY,
            clock=lambda: AT,
            synthesis_run_id_factory=lambda: run_id,
            human_actor_id=ALICE,
        )

    # substrate
    ingest("EV-1", "Refunds must complete within thirty days.")
    addr_refund = create_address("J-addr-refund", "EV-1", "Refund window")
    claim_a = assert_claim("J-claim-a", addr_refund, "EV-1", "thirty days")
    governor.record_authority(_authority("AUTH-payments", (SCOPE,)))
    governor.record_authority(_authority("AUTH-project", ()))
    _append_object(store, PROJECT, EventType.SEMANTIC_OBJECT_RECORDED, _intent())
    _append_object(store, PROJECT, EventType.SEMANTIC_OBJECT_RECORDED, _actor())

    # A. applied NEW
    outcome = synthesize(
        RUN_NEW, _proposal("p-new", claim_a, statement="Refunds complete within thirty days.")
    )
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]

    # B. correct the basis, then applied REPLACES_STALE
    ingest("EV-2", "Refunds must complete within seven days.")
    # The replacement is the one live canonical obligation the final state delivers, so its
    # basis must be lawful: a CANONICAL claim, asserted after authority exists (R46, R47).
    claim_a2 = assert_claim("J-claim-a2", addr_refund, "EV-2", "seven days", Authority.CANONICAL)
    supersede("J-sup-a", "J-claim-a", "EV-2")
    outcome = synthesize(
        RUN_REPLACE,
        _proposal(
            "p-replace",
            claim_a2,
            statement="Refunds complete within seven days.",
            disposition=IntentDisposition.REPLACES_STALE,
            relates_to_object_id=REQ_A,
        ),
    )
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]

    # C. a decision that becomes durable and is then invalidated, at its own locus so
    #    nothing else derives from the basis we are about to withdraw.
    ingest("EV-3", "Chargebacks are acknowledged within one day.")
    addr_charge = create_address("J-addr-charge", "EV-3", "Chargeback window")
    claim_c = assert_claim("J-claim-c", addr_charge, "EV-3", "one day")
    store.crash_on = EventType.INTENT_OBJECT_SYNTHESIZED
    with pytest.raises(Interrupted):
        synthesize(
            RUN_DOOMED,
            _proposal("p-doomed", claim_c, statement="Chargebacks acknowledged within one day."),
        )
    store.crash_on = None
    supersede("J-sup-c", "J-claim-c", "EV-3")
    recovery = resume_incomplete_synthesis(store, project_id=PROJECT, clock=lambda: AT)
    assert recovery.invalidated_proposal_ids == (PID_DOOMED,)
    assert recovery.remaining_incomplete_proposal_ids == ()

    return inner, synthesizer


@pytest.fixture(scope="module")
def ledger() -> tuple[InMemoryEventStore, int]:
    """The representative store, plus the synthesizer call count at the moment of freeze."""
    store, synthesizer = _build_representative_ledger()
    return store, synthesizer.calls


# --- the three independent reconstructions ---------------------------------------------


def _json_round_tripped(store: InMemoryEventStore) -> tuple[StoredEvent, ...]:
    """Rebuild every event from its serialized document through production parsing."""
    return tuple(
        StoredEvent(
            sequence=stored.sequence,
            event=parse_event(json.loads(json.dumps(stored.event.model_dump(mode="json")))),
        )
        for stored in store.load(PROJECT)
    )


def _three_states(store: InMemoryEventStore) -> tuple[IntentState, IntentState, IntentState]:
    state_a = replay(PROJECT, tuple(store.load(PROJECT)))
    state_b = replay(PROJECT, _json_round_tripped(store))
    state_c = replay(PROJECT, store.load(PROJECT))
    return state_a, state_b, state_c


def _readiness(state: IntentState) -> Any:
    view = derive_view(state.semantic)
    loci = tuple(locus for locus in view.loci if locus_in_scope(locus, SCOPE))
    return build_intent_delivery_readiness(
        state, view, SCOPE, loci, build_semantic_readiness(state, view, SCOPE, loci)
    )


# --- the representative ledger is what it claims to be ----------------------------------


def test_the_representative_ledger_exercises_all_four_durable_planes(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    store, _ = ledger
    state = replay(PROJECT, store.load(PROJECT))
    synthesis = state.intent_synthesis

    assert set(synthesis.decisions) == {PID_A, PID_B, PID_DOOMED}
    assert set(synthesis.applied_proposal_ids) == {PID_A, PID_B}
    assert synthesis.invalidated_proposal_ids == (PID_DOOMED,)
    assert [r.retired_object_id for r in synthesis.retirements] == [REQ_A]
    assert synthesis.retirements[0].replaced_by_object_id == REQ_B
    # No plane passes merely by being empty.
    assert all(
        plane
        for plane in (
            synthesis.decisions,
            synthesis.applied_proposal_ids,
            synthesis.invalidated_proposal_ids,
            synthesis.retirements,
        )
    )

    types = [s.event.event_type for s in store.load(PROJECT)]
    assert types.count(EventType.INTENT_SYNTHESIS_DECIDED) == 3
    assert types.count(EventType.INTENT_OBJECT_SYNTHESIZED) == 2
    assert types.count(EventType.INTENT_SYNTHESIS_INVALIDATED) == 1


def _refusal(state: IntentState) -> tuple[str, ...]:
    """The v2 refusal codes. The representative ledger is built by the frozen synthesis
    writer, which emits no SERVES edge, so its canonical Requirement is relevance-incomplete
    (IE2.2c) and v2 always refuses; reconstruction must reproduce that refusal exactly."""
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    return excinfo.value.blocker_codes


def test_the_representative_final_state_closes_and_is_blocked_only_by_relevance(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    """Re-expected in IE2.2c: the replacement's basis is lawful and its staleness is
    reconciled; the only remaining blocker is that the frozen writer gave it no SERVES."""
    store, _ = ledger
    state = replay(PROJECT, store.load(PROJECT))
    assert evaluate_closure(state, SCOPE).closed is True
    assert _refusal(state) == ("ORPHANED_CANONICAL_OBJECT",)
    readiness = _readiness(state)
    assert readiness.basis_blockers == ()
    assert [(b.code, b.object_ids) for b in readiness.relevance_blockers] == [
        ("ORPHANED_CANONICAL_OBJECT", (REQ_B,))
    ]


# --- I7: whole-state exactness across all three paths -------------------------------------


def test_i7_the_whole_intent_state_reconstructs_byte_identically(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    state_a, state_b, state_c = _three_states(ledger[0])
    assert all_equal(state_a, state_b, state_c)


@pytest.mark.parametrize(
    "plane",
    [
        "objects",
        "gaps",
        "jobs",
        "closed_scopes",
        "source_events",
        "revision",
        "last_sequence",
    ],
)
def test_each_top_level_plane_reconstructs_byte_identically(
    ledger: tuple[InMemoryEventStore, int], plane: str
) -> None:
    states = _three_states(ledger[0])
    assert all_equal(*(getattr(s, plane) for s in states))


def test_the_semantic_substrate_reconstructs_byte_identically(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    states = _three_states(ledger[0])
    assert all_equal(*(s.semantic for s in states))
    assert all_equal(*(s.semantic.derivations for s in states))


def test_the_synthesis_lifecycle_reconstructs_byte_identically(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    states = _three_states(ledger[0])
    assert all_equal(*(s.intent_synthesis for s in states))
    assert all_equal(*(s.intent_synthesis.decisions for s in states))
    assert all_equal(*(s.intent_synthesis.applied_proposal_ids for s in states))
    assert all_equal(*(s.intent_synthesis.invalidated_proposal_ids for s in states))
    assert all_equal(*(s.intent_synthesis.retirements for s in states))


# --- retired projection, derivation, decision record ---------------------------------------


def test_the_retired_projection_reproduces_exactly_under_every_replay(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    """C2/I5: immutability belongs to the LOG; the projection legitimately moved once."""
    for state in _three_states(ledger[0]):
        old = state.objects[REQ_A]
        new = state.objects[REQ_B]
        assert old.id == REQ_A
        assert old.lifecycle is LifecycleStatus.SUPERSEDED
        assert old.revision == 2  # incremented exactly once from 1
        assert new.id == REQ_B != REQ_A
        assert new.lifecycle is LifecycleStatus.ACTIVE
        assert new.authority is Authority.CANONICAL


def test_derivation_edges_point_at_the_asserting_judgment_under_every_replay(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    for state in _three_states(ledger[0]):
        by_child = {
            e.child_id: e.parent_id
            for e in state.semantic.derivations
            if e.child_id.startswith("REQ-")
        }
        assert by_child[REQ_A] == "J-claim-a"
        assert by_child[REQ_B] == "J-claim-a2"
        for child, parent in by_child.items():
            assert parent not in state.semantic.claims, (
                f"{child} derives from a CLAIM id; a claim is never a blast-radius root"
            )


def test_every_durable_decision_record_reproduces_field_for_field(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    """The durable record alone suffices: no provider cache, no T7 request, no routing rerun."""
    state_a, state_b, state_c = _three_states(ledger[0])
    for pid in (PID_A, PID_B, PID_DOOMED):
        records = [s.intent_synthesis.decisions[pid] for s in (state_a, state_b, state_c)]
        assert all_equal(*records)
        first = records[0]
        for field in (
            "proposal",
            "author",
            "identity",
            "origin",
            "assigned_authority",
            "decision",
            "decision_event_id",
            "decided_at",
        ):
            assert all_equal(*(getattr(r, field) for r in records)), field
        assert first.decision_event_id == first.identity.event_id("DECIDED")
        assert first.decided_at == AT


def test_each_applied_object_still_matches_the_decision_that_authorised_it(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    """C20 re-verified under replay: the effect must still BE the decision's outcome.

    Cross-replay equality alone cannot catch this — a reducer that rewrote a field would
    rewrite it identically every time, so all three reconstructions would agree on the
    same wrong value. The object is therefore checked against the durable record rather
    than only against its own copies.
    """
    for state in _three_states(ledger[0]):
        for pid in state.intent_synthesis.applied_proposal_ids:
            record = state.intent_synthesis.decisions[pid]
            obj = state.objects[record.identity.object_id("REQ")]
            assert obj.statement == record.proposal.statement
            assert obj.authority is record.assigned_authority
            assert obj.created_at == record.decided_at
            # D12 exactly: None stays None, a number stays that number.
            assert obj.confidence == record.proposal.confidence
            assert obj.provenance.source_event_ids == (record.decision_event_id,)
            assert [r.target_id for r in obj.relations] == list(record.proposal.basis_claim_ids)


def test_every_retirement_record_still_describes_a_real_replacement(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    """A retirement is only meaningful if both ends of it survive reconstruction."""
    for state in _three_states(ledger[0]):
        assert state.intent_synthesis.retirements != ()
        for retirement in state.intent_synthesis.retirements:
            retired = state.objects[retirement.retired_object_id]
            replacement = state.objects[retirement.replaced_by_object_id]
            assert retired.lifecycle is LifecycleStatus.SUPERSEDED
            assert replacement.lifecycle is LifecycleStatus.ACTIVE
            assert retirement.proposal_instance_id in state.intent_synthesis.applied_proposal_ids
            assert retirement.retired_object_id != retirement.replaced_by_object_id


def test_the_incomplete_set_is_empty_and_identical_across_replays(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    states = _three_states(ledger[0])
    sets = [incomplete_proposal_ids(s.intent_synthesis) for s in states]
    assert sets[0] == sets[1] == sets[2] == ()


# --- downstream artefacts --------------------------------------------------------------------


def test_closure_reproduces_exactly(ledger: tuple[InMemoryEventStore, int]) -> None:
    results = [evaluate_closure(s, SCOPE) for s in _three_states(ledger[0])]
    assert all_equal(*results)
    assert results[0].closed is True
    assert results[0].blockers == ()


def test_delivery_readiness_reproduces_exactly(ledger: tuple[InMemoryEventStore, int]) -> None:
    readinesses = [_readiness(s) for s in _three_states(ledger[0])]
    assert all_equal(*readinesses)
    first = readinesses[0]
    # IE2.2c: relevance-incomplete (frozen writer, no SERVES), and nothing else.
    assert first.deliverable is False
    assert [b.code for b in first.relevance_blockers] == ["ORPHANED_CANONICAL_OBJECT"]
    assert first.basis_blockers == ()
    assert first.blocking_stale_object_ids == ()
    assert first.incomplete_synthesis_proposal_ids == ()
    # D6-R: the retired historical object stays visible rather than being erased.
    assert REQ_A in first.reconciled_stale_object_ids
    assert first.semantic_readiness.ready is False


def test_the_canonical_package_reproduces_exactly(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    packages = [build_intent_package(s, SCOPE) for s in _three_states(ledger[0])]
    assert all_equal(*packages)
    first = packages[0]
    assert REQ_B in first.obligation_ids
    assert REQ_A not in first.obligation_ids
    # The invalidated proposal contributes no obligation and no object at all.
    assert _object_id("p-doomed", RUN_DOOMED) not in first.obligation_ids
    assert "ACTOR-customer" in first.purpose_ids
    assert "INTENT-payments" in first.purpose_ids


def test_the_v2_refusal_reproduces_exactly(ledger: tuple[InMemoryEventStore, int]) -> None:
    """Re-expected in IE2.2c: v2 now refuses (no SERVES from the frozen writer), so what
    must reproduce across all three reconstructions is the refusal and its readiness."""
    states = _three_states(ledger[0])
    refusals = [_refusal(s) for s in states]
    assert all_equal(*refusals)
    assert refusals[0] == ("ORPHANED_CANONICAL_OBJECT",)
    for state in states:
        readiness = _readiness(state)
        assert REQ_A in readiness.reconciled_stale_object_ids
        assert REQ_A not in readiness.blocking_stale_object_ids
        assert REQ_B in build_intent_package(state, SCOPE).obligation_ids


def test_repeated_derivation_from_one_state_is_stable(
    ledger: tuple[InMemoryEventStore, int],
) -> None:
    """No clock, no random id, no mutation, no I/O anywhere in the derivation path."""
    state = replay(PROJECT, ledger[0].load(PROJECT))
    for build in (
        lambda: evaluate_closure(state, SCOPE),
        lambda: build_intent_package(state, SCOPE),
        lambda: _refusal(state),
        lambda: _readiness(state),
    ):
        assert all_equal(build(), build(), build())


# --- no model participates in reconstruction ---------------------------------------------------


def test_reconstruction_invokes_no_synthesizer(ledger: tuple[InMemoryEventStore, int]) -> None:
    """The scripted calls that BUILT the ledger are the deliberate pre-durability boundary.

    What must be zero is calls during reconstruction — this whole function holds no
    synthesizer reference at all, which is the strongest form of the claim.
    """
    store, calls_before_replay = ledger
    states = _three_states(store)
    for state in states:
        evaluate_closure(state, SCOPE)
        _readiness(state)
        build_intent_package(state, SCOPE)
        _refusal(state)
    _, calls_after = ledger
    assert calls_after == calls_before_replay == 3


# --- backward compatibility: a stream written before this slice existed --------------------------

LEGACY_GAP = Gap(
    id="GAP-legacy",
    project_id=LEGACY_PROJECT,
    kind=GapKind.AMBIGUITY,
    description="An old ambiguity, recorded the old way.",
    materiality=Materiality.LOW,
    risk=RiskLevel.LOW,
    affected_object_ids=(),
    blocking=False,
)


def _legacy_requirement() -> Requirement:
    return Requirement(
        id="REQ-legacy",
        project_id=LEGACY_PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROV,
        created_at=AT,
        scope=(SCOPE,),
        statement="Refunds are acknowledged.",
        materiality=Materiality.LOW,
        requires_metric=False,
        requires_verification=False,
    )


def _legacy_store() -> InMemoryEventStore:
    """A useful closed pre-synthesis story: objects, a legacy Gap, and an AMBIGUITY event."""
    store = InMemoryEventStore()

    def append(event_id: str, event_type: EventType, payload: Any) -> None:
        store.append(
            EventEnvelope(
                event_id=event_id,
                project_id=LEGACY_PROJECT,
                event_type=event_type,
                occurred_at=AT,
                payload=payload,
            ),
            expected_sequence=store.current_sequence(LEGACY_PROJECT),
        )

    append(
        "L1",
        EventType.SEMANTIC_OBJECT_RECORDED,
        SemanticObjectPayload(object=_intent(LEGACY_PROJECT)),
    )
    append(
        "L2",
        EventType.SEMANTIC_OBJECT_RECORDED,
        SemanticObjectPayload(object=_actor(LEGACY_PROJECT)),
    )
    append(
        "L3",
        EventType.REQUIREMENT_CANONICALIZED,
        SemanticObjectPayload(object=_legacy_requirement()),
    )
    append(
        "L4",
        EventType.SEMANTIC_OBJECT_RECORDED,
        SemanticObjectPayload(object=_authority("AUTH-legacy", (SCOPE,), LEGACY_PROJECT)),
    )
    append("L5", EventType.GAP_RECORDED, GapPayload(gap=LEGACY_GAP))
    append("L6", EventType.AMBIGUITY_DETECTED, GapPayload(gap=LEGACY_GAP))
    return store


def _legacy_state(store: InMemoryEventStore) -> IntentState:
    return replay(LEGACY_PROJECT, store.load(LEGACY_PROJECT))


def test_a_pre_synthesis_stream_replays_with_an_empty_synthesis_plane() -> None:
    state = _legacy_state(_legacy_store())
    assert state.intent_synthesis == IntentSynthesisState()
    assert incomplete_proposal_ids(state.intent_synthesis) == ()


def test_legacy_projections_are_untouched_by_the_new_plane() -> None:
    store = _legacy_store()
    state = _legacy_state(store)
    assert set(state.objects) == {"INTENT-payments", "ACTOR-customer", "REQ-legacy", "AUTH-legacy"}
    assert set(state.gaps) == {"GAP-legacy"}
    assert state.jobs == {}
    assert state.closed_scopes == {}
    assert state.source_events == ("L1", "L2", "L3", "L4", "L5", "L6")
    assert state.revision == 6
    assert state.last_sequence == 6
    assert state.semantic == type(state.semantic)()


def test_the_legacy_gap_stays_a_base_gap_through_json_and_replay() -> None:
    """T7.1's union order must survive final certification: base first, always."""
    store = _legacy_store()
    for stored in store.load(LEGACY_PROJECT):
        if stored.event.event_type is EventType.GAP_RECORDED:
            revived = parse_event(stored.event.model_dump(mode="json"))
            assert isinstance(revived.payload, GapPayload)
            assert type(revived.payload.gap) is Gap
            assert not isinstance(revived.payload.gap, IntentSynthesisGap)
    state = _legacy_state(store)
    assert type(state.gaps["GAP-legacy"]) is Gap
    assert state.gaps["GAP-legacy"] == LEGACY_GAP


def test_legacy_ambiguity_detected_still_records_nothing() -> None:
    state = _legacy_state(_legacy_store())
    assert set(state.gaps) == {"GAP-legacy"}
    assert "GAP-legacy" in state.gaps
    # L6 was an AMBIGUITY_DETECTED for the same gap; it added no second entry and no
    # state change of its own.
    assert state.gaps["GAP-legacy"].status is GapStatus.OPEN


def test_a_legacy_state_document_without_the_additive_field_still_validates() -> None:
    """The additive-model guarantee, exercised on a document that predates the field."""
    state = _legacy_state(_legacy_store())
    document = state.model_dump(mode="json")
    assert "intent_synthesis" in document
    legacy_document = {k: v for k, v in document.items() if k != "intent_synthesis"}

    restored = IntentState.model_validate(legacy_document)

    assert restored.intent_synthesis == IntentSynthesisState()
    for field in ("objects", "gaps", "jobs", "closed_scopes", "source_events", "revision"):
        assert canonical_bytes(getattr(restored, field)) == canonical_bytes(getattr(state, field))
    assert canonical_bytes(restored.semantic) == canonical_bytes(state.semantic)


def test_the_legacy_package_and_v1_handoff_are_unchanged() -> None:
    store = _legacy_store()
    state = _legacy_state(store)

    package = build_intent_package(state, SCOPE)
    assert package.purpose_ids == ("ACTOR-customer", "INTENT-payments")
    assert package.boundary_ids == ()
    assert package.obligation_ids == ("REQ-legacy",)
    assert package.canonical_decision_ids == ()
    assert package.proposed_decision_ids == ()
    assert package.superseded_decision_ids == ()
    assert package.epistemic_ids == ()
    assert package.quality_ids == ()
    assert package.governance_ids == ("AUTH-legacy",)
    assert package.history_event_ids == ("L1", "L2", "L3", "L4", "L5", "L6")
    assert package.intent_version == 6
    assert package.scope == SCOPE

    v1 = build_intent_decision_handoff(state, SCOPE)
    assert v1.handoff_version == HANDOFF_VERSION == "intent-decision-handoff-v1"
    assert v1.loci == ()
    assert v1.claim_ids == ()
    assert v1.evidence_ids == ()
    assert v1.authority_record_ids == ("AUTH-legacy",)
    assert v1.superseded_judgment_ids == ()
    assert v1.stale_object_ids == ()
    assert v1.pending_material_judgment_ids == ()
    assert v1.readiness.ready is True

    # And it is stable under a second independent replay.
    again = _legacy_state(store)
    assert all_equal(package, build_intent_package(again, SCOPE))
    assert all_equal(v1, build_intent_decision_handoff(again, SCOPE))


def test_an_old_stream_never_needs_synthesis_recovery() -> None:
    store = _legacy_store()
    before = len(store.load(LEGACY_PROJECT))

    outcome = resume_incomplete_synthesis(store, project_id=LEGACY_PROJECT, clock=lambda: AT)

    assert outcome.applied_proposal_ids == ()
    assert outcome.invalidated_proposal_ids == ()
    assert outcome.contention_exhausted_proposal_ids == ()
    assert outcome.remaining_incomplete_proposal_ids == ()
    assert len(store.load(LEGACY_PROJECT)) == before


# --- no certification machinery leaked into production -------------------------------------------


def test_no_certification_event_type_was_added() -> None:
    names = {e.name for e in EventType}
    assert not {
        n for n in names if any(k in n for k in ("REPLAY", "CERTIF", "SNAPSHOT", "HANDOFF"))
    }


def test_no_replay_cache_helper_was_added_to_production() -> None:
    import foundry.application.replay as replay_module

    assert [n for n in dir(replay_module) if not n.startswith("_")] == [
        "IntentState",
        "Iterable",
        "StoredEvent",
        "annotations",
        "reduce_event",
        "replay",
    ]
