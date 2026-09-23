"""T11 — the complete Intent Synthesis vertical, end to end through production code.

This is a proof task, not a new subsystem. Everything below runs the real machinery:

    EvidenceItem → SemanticAddress → SemanticClaim → IntentSynthesisRequest
        → scripted IntentSynthesizer → proposal → governance → DECIDED
        → Requirement → closure → CanonicalIntentPackage → IntentDecisionHandoffV2

The only fake is the synthesizer, and it implements the real ``IntentSynthesizer`` port
and receives the genuine compiled ``IntentSynthesisRequest``. There is no provider, no
network and no hand-built ``IntentState``: every assertion is made against a fresh
``replay`` of the one event store, because the point of the exercise is to certify the
machine around the model rather than any particular model's output.

The architecturally interesting proofs are the ones where the layers disagree on
purpose. A stale canonical Requirement still closes and still appears in the contract,
while v2 delivery refuses it (P4). An AI may propose a replacement for a canonical
obligation and be routed to a human without the contract shifting by a single id (I23).
One corrected claim stales every object derived from it, not just the first (I4).
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.handoff_v2 import (
    IntentDeliveryNotReadyError,
    build_intent_decision_handoff_v2,
)
from foundry.application.intent_synthesis import synthesize_intent
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
    RelationType,
    SourceKind,
)
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    SemanticObjectPayload,
    StoredEvent,
)
from foundry.domain.evidence import evidence_item
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisPolicy,
    IntentSynthesisResult,
    IntentSynthesisRoute,
    RequirementSynthesisProposal,
    SynthesisIdentity,
)
from foundry.domain.semantic import Actor, AuthorityRecord, Intent, Requirement, SemanticKind
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
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.ports.intent_synthesizer import IntentSynthesisRequest

PROJECT = "PROJ-SLICE1"
SCOPE = "payments"
AT = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
ALICE = "human://alice"
HUMAN = ReasonerFingerprint(provider="human", model=ALICE, policy_version="p1")
AI = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")
RUN = "RUN-T11"
SYNTHESIS_POLICY = IntentSynthesisPolicy()


# --- no network, ever ------------------------------------------------------------------


def _refuse_network(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("network access is forbidden in the intent synthesis vertical")


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


# --- test-local determinism only; the system under test is all production --------------


def _clock() -> Callable[[], datetime]:
    ticks = count()
    return lambda: AT.replace(minute=next(ticks) % 60)


def _id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks):03d}"


def _governor(store: InMemoryEventStore) -> SemanticGovernor:
    return SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
    )


def _append_object(store: InMemoryEventStore, event_type: EventType, obj: Any) -> StoredEvent:
    """Seed a pre-existing v0 semantic object through the same ledger the governor uses.

    There is no governor method for these events and inventing a second ledger
    abstraction to place them would defeat the point of the exercise.
    """
    event = EventEnvelope(
        event_id=f"object-{obj.id}-{store.current_sequence(PROJECT)}",
        project_id=PROJECT,
        event_type=event_type,
        occurred_at=AT,
        payload=SemanticObjectPayload(object=obj),
    )
    return store.append(event, expected_sequence=store.current_sequence(PROJECT))


def _state(store: InMemoryEventStore) -> IntentState:
    """Always a fresh replay. No mutable state is carried between checkpoints."""
    return replay(PROJECT, store.load(PROJECT))


class ScriptedIntentSynthesizer:
    """The real port, a scripted answer, and a record of exactly what it was shown."""

    def __init__(
        self, *results: IntentSynthesisResult, fingerprint: ReasonerFingerprint = HUMAN
    ) -> None:
        self._results = list(results)
        self._fingerprint = fingerprint
        self.requests: list[IntentSynthesisRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    @property
    def calls(self) -> int:
        return len(self.requests)

    def synthesize(self, request: IntentSynthesisRequest) -> IntentSynthesisResult:
        self.requests.append(request)
        if not self._results:
            raise AssertionError("synthesizer called more often than the story scripted")
        return self._results.pop(0)


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    evidence_ids: tuple[str, ...],
    reasoner: ReasonerFingerprint = HUMAN,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=evidence_ids,
        rationale="stated by the product owner",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=AT,
    )


def _ingest(governor: SemanticGovernor, evidence_id: str, content: str) -> None:
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


def _create_address(governor: SemanticGovernor, judgment_id: str, evidence_id: str) -> str:
    decision = governor.submit(
        _judgment(
            judgment_id,
            CreateAddressProposal(
                candidate=SemanticCandidate(
                    candidate_id=f"CAND-{judgment_id}",
                    subject="Refund window",
                    facet="How long may a refund take?",
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


def _assert_claim(
    governor: SemanticGovernor,
    judgment_id: str,
    address_id: str,
    evidence_id: str,
    text: str,
) -> str:
    decision = governor.submit(
        _judgment(
            judgment_id,
            AssertClaimProposal(
                address_id=address_id,
                predicate="refund_window",
                value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
                evidence_ids=(evidence_id,),
                authority=Authority.INFERRED,
            ),
            (evidence_id,),
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY
    return claim_id_for(PROJECT, judgment_id)


def _authority_record(object_id: str, scope: tuple[str, ...], subject: str) -> AuthorityRecord:
    return AuthorityRecord(
        id=object_id,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=ALICE),
        created_at=AT,
        scope=scope,
        subject_id=subject,
        authorized_by=ALICE,
        rationale=f"alice owns {subject}",
    )


def _authority(governor: SemanticGovernor) -> None:
    """Alice holds two records, and the distinction is the existing admission law.

    Payments-scoped authority is what lets her synthesized intent be CANONICAL. But a
    ``SUPERSEDE`` judgment has no single target address, so ``_target_scope`` is ``None``
    and only a project-wide record covers it — that is deliberately how relation and
    supersession kinds are kept behind project-wide authority. Correcting the semantic
    substrate is therefore a strictly broader permission than owning one scope's intent,
    and the story gives her both rather than pretending one implies the other.
    """
    governor.record_authority(_authority_record("AUTH-payments", (SCOPE,), "payments intent"))
    governor.record_authority(_authority_record("AUTH-project", (), "semantic substrate"))


def _intent_object() -> Intent:
    return Intent(
        id="INTENT-payments",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=ALICE),
        created_at=AT,
        scope=(SCOPE,),
        mission="Refunds are fast and predictable.",
    )


def _actor_object() -> Actor:
    return Actor(
        id="ACTOR-customer",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=ALICE),
        created_at=AT,
        scope=(SCOPE,),
        name="Customer",
        description="A person who requests a refund.",
    )


def _seeded_requirement(
    object_id: str,
    *,
    authority: Authority = Authority.CANONICAL,
    materiality: Materiality = Materiality.LOW,
    statement: str = "A pre-existing obligation.",
) -> Requirement:
    return Requirement(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=ALICE),
        created_at=AT,
        scope=(SCOPE,),
        statement=statement,
        materiality=materiality,
        requires_metric=False,
        requires_verification=False,
    )


def _proposal(
    model_proposal_id: str,
    claim_id: str,
    *,
    statement: str = "Refunds must complete within thirty days.",
    disposition: IntentDisposition = IntentDisposition.NEW,
    relates_to_object_id: str | None = None,
    confidence: float | None = 0.82,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=model_proposal_id,
        disposition=disposition,
        statement=statement,
        rationale="the live claim states the refund window",
        basis_claim_ids=(claim_id,),
        relates_to_object_id=relates_to_object_id,
        confidence=confidence,
    )


def _synthesize(
    store: InMemoryEventStore,
    synthesizer: ScriptedIntentSynthesizer,
    *,
    run_id: str = RUN,
    human_actor_id: str | None = ALICE,
) -> Any:
    return synthesize_intent(
        store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=synthesizer,
        policy=SYNTHESIS_POLICY,
        clock=lambda: AT,
        synthesis_run_id_factory=lambda: run_id,
        human_actor_id=human_actor_id,
    )


def _object_id(model_proposal_id: str, run_id: str = RUN) -> str:
    return SynthesisIdentity(
        project_id=PROJECT, synthesis_run_id=run_id, model_proposal_id=model_proposal_id
    ).object_id("REQ")


def _substrate(store: InMemoryEventStore) -> tuple[SemanticGovernor, str, str]:
    """Evidence → address → claim → authority → canonical Intent and Actor."""
    governor = _governor(store)
    _ingest(governor, "EV-policy", "Refunds must complete within thirty days.")
    address_id = _create_address(governor, "J-address", "EV-policy")
    claim_id = _assert_claim(governor, "J-claim", address_id, "EV-policy", "thirty days")
    _authority(governor)
    _append_object(store, EventType.SEMANTIC_OBJECT_RECORDED, _intent_object())
    _append_object(store, EventType.SEMANTIC_OBJECT_RECORDED, _actor_object())
    return governor, address_id, claim_id


def _semantic_fingerprint(semantic: SemanticState) -> dict[str, Any]:
    """Everything in the semantic substrate EXCEPT derivation edges."""
    return {
        "evidence": sorted(semantic.evidence),
        "judgments": sorted(semantic.judgments),
        "applied_judgment_ids": tuple(semantic.applied_judgment_ids),
        "addresses": sorted(semantic.addresses),
        "claims": sorted(semantic.claims),
        "issue_versions": sorted(semantic.issue_versions),
        "issue_heads": dict(semantic.issue_heads),
        "equivalences": tuple(semantic.equivalences),
        "conflicts": tuple(semantic.conflicts),
        "claim_supports": tuple(semantic.claim_supports),
        "bindings": dict(semantic.bindings),
        "supersessions": tuple(semantic.supersessions),
        "admissions": sorted(semantic.admissions),
    }


# --- A. the human canonical vertical ---------------------------------------------------


def test_a_human_synthesis_carries_evidence_all_the_way_to_a_delivered_handoff() -> None:
    store = InMemoryEventStore()
    _, address_id, claim_id = _substrate(store)

    before = _state(store)
    # Nothing yet obliges anything: the scope cannot close without an obligation.
    assert evaluate_closure(before, SCOPE).closed is False
    assert "MISSING_CANONICAL_OBLIGATION" in {
        b.code for b in evaluate_closure(before, SCOPE).blockers
    }
    semantic_before = _semantic_fingerprint(before.semantic)
    events_before = len(store.load(PROJECT))

    synthesizer = ScriptedIntentSynthesizer(
        IntentSynthesisResult(proposals=(_proposal("p1", claim_id),)), fingerprint=HUMAN
    )
    outcome = _synthesize(store, synthesizer)

    # --- the scripted model boundary (§20): exactly the real compiled request
    assert synthesizer.calls == 1
    request = synthesizer.requests[0]
    assert request.project_id == PROJECT
    assert request.scope == SCOPE
    assert request.allowed_target_kinds == frozenset({SemanticKind.REQUIREMENT})
    assert [c.claim_id for locus in request.basis for c in locus.live_claims] == [claim_id]
    assert {locus.locus_representative_id for locus in request.basis} == {address_id}
    assert len(request.known_intent_objects) <= 200
    assert {o.object_id for o in request.known_intent_objects} == {"INTENT-payments"}

    # --- one decision, one effect, no recovery needed
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]
    appended = [s.event.event_type for s in store.load(PROJECT)][events_before:]
    assert appended.count(EventType.INTENT_SYNTHESIS_DECIDED) == 1
    assert appended.count(EventType.INTENT_OBJECT_SYNTHESIZED) == 1
    assert EventType.INTENT_SYNTHESIS_INVALIDATED not in appended

    state = _state(store)
    requirement_id = _object_id("p1")
    requirement = state.objects[requirement_id]
    assert isinstance(requirement, Requirement)

    # --- §6: the object the real path produced
    assert requirement.authority is Authority.CANONICAL
    assert requirement.materiality is Materiality.LOW
    assert requirement.requires_metric is False
    assert requirement.requires_verification is False
    assert requirement.lifecycle is LifecycleStatus.ACTIVE
    assert tuple(requirement.scope) == (SCOPE,)
    assert requirement.confidence == 0.82
    assert requirement.statement == "Refunds must complete within thirty days."

    # --- §7: dual provenance survived integration
    assert [(r.relation_type, r.target_id) for r in requirement.relations] == [
        (RelationType.DERIVED_FROM, claim_id)
    ]
    edges = [e for e in state.semantic.derivations if e.child_id == requirement_id]
    assert [e.parent_id for e in edges] == ["J-claim"]
    assert edges[0].parent_id == state.semantic.claims[claim_id].created_by_judgment_id
    # The relation targets the CLAIM; the edge targets the asserting JUDGMENT. A claim id
    # is never a blast-radius root, so an edge pointing at one would never propagate.
    assert edges[0].parent_id != claim_id

    # --- §8/G: I14 altitude separation, end to end
    assert _semantic_fingerprint(state.semantic) == semantic_before
    assert EventType.SEMANTIC_JUDGMENT_RECORDED not in appended
    assert EventType.SEMANTIC_ADMISSION_DECIDED not in appended
    assert len(state.semantic.derivations) == len(before.semantic.derivations) + 1

    # --- §9/§10: closure now succeeds, with no Metric and no VerificationObligation
    closure = evaluate_closure(state, SCOPE)
    assert closure.closed is True
    assert closure.blockers == ()
    assert not any(o.kind is SemanticKind.METRIC for o in state.objects.values())
    assert not any(o.kind is SemanticKind.VERIFICATION_OBLIGATION for o in state.objects.values())

    # --- §11: I8 on the real vertical
    package = build_intent_package(state, SCOPE)
    assert requirement_id in package.obligation_ids
    assert "ACTOR-customer" in package.purpose_ids
    assert "INTENT-payments" in package.purpose_ids

    # --- §12: v2 delivers the real package
    handoff = build_intent_decision_handoff_v2(state, SCOPE)
    assert handoff.readiness.deliverable is True
    assert handoff.contract == package
    assert requirement_id in handoff.canonical_intent_object_ids
    basis_ref = next(r for r in handoff.intent_basis if r.object_id == requirement_id)
    assert basis_ref.basis_claim_ids == (claim_id,)
    assert basis_ref.basis_locus_ids == (address_id,)


# --- B. I8 — an AI proposal is visible but non-contractual ------------------------------


def test_an_ai_proposal_is_visible_to_review_but_never_becomes_an_obligation() -> None:
    store = InMemoryEventStore()
    _, _, claim_id = _substrate(store)
    # The scope can already close on its own, so the AI proposal is not asked to.
    _append_object(
        store,
        EventType.REQUIREMENT_CANONICALIZED,
        _seeded_requirement("REQ-seeded", statement="Refund requests are acknowledged."),
    )

    synthesizer = ScriptedIntentSynthesizer(
        IntentSynthesisResult(proposals=(_proposal("ai1", claim_id),)), fingerprint=AI
    )
    outcome = _synthesize(store, synthesizer, human_actor_id=None)

    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]
    state = _state(store)
    ai_id = _object_id("ai1")
    ai_requirement = state.objects[ai_id]
    assert ai_requirement.authority is Authority.PROPOSED
    assert isinstance(ai_requirement, Requirement)
    assert ai_requirement.materiality is Materiality.LOW

    assert evaluate_closure(state, SCOPE).closed is True
    package = build_intent_package(state, SCOPE)
    assert ai_id not in package.obligation_ids
    assert "REQ-seeded" in package.obligation_ids

    handoff = build_intent_decision_handoff_v2(state, SCOPE)
    assert ai_id in handoff.proposed_intent_object_ids
    assert ai_id not in handoff.canonical_intent_object_ids
    assert ai_id not in handoff.contract.obligation_ids


# --- C. the pre-existing materiality rule still bites -----------------------------------


def test_a_medium_proposed_requirement_still_blocks_closure() -> None:
    store = InMemoryEventStore()
    _substrate(store)
    _append_object(store, EventType.REQUIREMENT_CANONICALIZED, _seeded_requirement("REQ-seeded"))
    assert evaluate_closure(_state(store), SCOPE).closed is True

    _append_object(
        store,
        EventType.REQUIREMENT_CANONICALIZED,
        _seeded_requirement(
            "REQ-medium",
            authority=Authority.PROPOSED,
            materiality=Materiality.MEDIUM,
            statement="A material obligation nobody has ratified.",
        ),
    )

    closure = evaluate_closure(_state(store), SCOPE)
    assert closure.closed is False
    assert "NON_CANONICAL_REQUIREMENT" in {b.code for b in closure.blockers}


# --- D. P4 — staleness changes delivery, not closure -------------------------------------


def _stale_canonical_story() -> tuple[InMemoryEventStore, str, str]:
    """The human vertical, then its basis corrected. Returns (store, requirement, new claim)."""
    store = InMemoryEventStore()
    governor, address_id, claim_id = _substrate(store)
    _synthesize(
        store,
        ScriptedIntentSynthesizer(
            IntentSynthesisResult(proposals=(_proposal("p1", claim_id),)), fingerprint=HUMAN
        ),
    )
    requirement_id = _object_id("p1")

    _ingest(governor, "EV-correction", "Refunds must complete within seven days.")
    corrected_claim = _assert_claim(
        governor, "J-corrected", address_id, "EV-correction", "seven days"
    )
    decision = governor.submit(
        _judgment(
            "J-supersede",
            SupersedeProposal(target_judgment_id="J-claim", reason="policy was corrected"),
            ("EV-correction",),
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY
    return store, requirement_id, corrected_claim


def test_p4_a_stale_requirement_leaves_closure_and_the_package_alone_but_stops_delivery() -> None:
    store, requirement_id, _ = _stale_canonical_story()
    state = _state(store)

    assert requirement_id in derive_view(state.semantic).stale_ids
    # §19: corrected evidence does not rewrite old intent.
    requirement = state.objects[requirement_id]
    assert requirement.lifecycle is LifecycleStatus.ACTIVE
    assert requirement.authority is Authority.CANONICAL
    assert requirement.statement == "Refunds must complete within thirty days."

    # Closure knows nothing about synthesis staleness, and must not learn.
    assert evaluate_closure(state, SCOPE).closed is True

    # The package is the contract projection, not the freshness gate.
    package = build_intent_package(state, SCOPE)
    assert requirement_id in package.obligation_ids

    # Only v2 delivery refuses.
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    assert excinfo.value.blocker_codes == ("UNRECONCILED_STALE_OBJECT",)


# --- E. I23 — no AI path can delete a canonical obligation --------------------------------


def test_i23_an_ai_replacement_of_a_canonical_obligation_is_routed_to_a_human() -> None:
    store, requirement_id, corrected_claim = _stale_canonical_story()
    obligations_before = build_intent_package(_state(store), SCOPE).obligation_ids
    assert requirement_id in obligations_before

    synthesizer = ScriptedIntentSynthesizer(
        IntentSynthesisResult(
            proposals=(
                _proposal(
                    "ai-replace",
                    corrected_claim,
                    statement="Refunds must complete within seven days.",
                    disposition=IntentDisposition.REPLACES_STALE,
                    relates_to_object_id=requirement_id,
                ),
            )
        ),
        fingerprint=AI,
    )
    outcome = _synthesize(store, synthesizer, run_id="RUN-ai", human_actor_id=None)

    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.REQUIRE_HUMAN]
    assert "CANONICAL_REPLACEMENT_REQUIRED" in outcome.decisions[0].reasons

    state = _state(store)
    assert _object_id("ai-replace", "RUN-ai") not in state.objects
    assert state.intent_synthesis.retirements == ()
    assert state.objects[requirement_id].lifecycle is LifecycleStatus.ACTIVE
    assert state.objects[requirement_id].authority is Authority.CANONICAL

    obligations_after = build_intent_package(state, SCOPE).obligation_ids
    assert obligations_after == obligations_before

    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    assert "UNRECONCILED_STALE_OBJECT" in excinfo.value.blocker_codes


# --- F. I4 — one claim fans staleness out to every object derived from it -----------------


def test_i4_one_corrected_claim_stales_every_requirement_derived_from_it() -> None:
    store = InMemoryEventStore()
    governor, address_id, claim_id = _substrate(store)

    synthesizer = ScriptedIntentSynthesizer(
        IntentSynthesisResult(
            proposals=(
                _proposal("p1", claim_id, statement="Refunds complete within thirty days."),
                _proposal("p2", claim_id, statement="Refund status is visible within thirty days."),
            )
        ),
        fingerprint=HUMAN,
    )
    outcome = _synthesize(store, synthesizer)
    assert [d.route for d in outcome.decisions] == [
        IntentSynthesisRoute.APPLY,
        IntentSynthesisRoute.APPLY,
    ]

    first, second = _object_id("p1"), _object_id("p2")
    state = _state(store)
    assert first != second
    assert {first, second} <= set(state.objects)
    view = derive_view(state.semantic)
    assert first not in view.stale_ids
    assert second not in view.stale_ids
    # Two distinct objects, one shared basis — nothing collapsed them.
    assert {e.parent_id for e in state.semantic.derivations if e.child_id in {first, second}} == {
        "J-claim"
    }

    _ingest(governor, "EV-correction", "Refunds must complete within seven days.")
    _assert_claim(governor, "J-corrected", address_id, "EV-correction", "seven days")
    governor.submit(
        _judgment(
            "J-supersede",
            SupersedeProposal(target_judgment_id="J-claim", reason="policy was corrected"),
            ("EV-correction",),
        ),
        human_actor_id=ALICE,
    )

    state = _state(store)
    stale = set(derive_view(state.semantic).stale_ids)
    assert first in stale
    assert second in stale

    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    assert "UNRECONCILED_STALE_OBJECT" in excinfo.value.blocker_codes


# --- the ledger is the only truth ----------------------------------------------------------


def test_the_entire_vertical_is_reconstructable_from_the_event_store_alone() -> None:
    store = InMemoryEventStore()
    _, _, claim_id = _substrate(store)
    _synthesize(
        store,
        ScriptedIntentSynthesizer(
            IntentSynthesisResult(proposals=(_proposal("p1", claim_id),)), fingerprint=HUMAN
        ),
    )

    first = replay(PROJECT, store.load(PROJECT))
    second = replay(PROJECT, store.load(PROJECT))
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert _object_id("p1") in first.objects
    assert build_intent_decision_handoff_v2(first, SCOPE) == build_intent_decision_handoff_v2(
        second, SCOPE
    )
