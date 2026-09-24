"""MR3 — the vertical bridge: Intent governance driven by a Model Runtime synthesizer.

The production stack, end to end, with a fake only at the provider boundary:

    InMemoryEventStore → semantic substrate → synthesize_intent
      → ModelRuntimeIntentSynthesizer → real ModelRuntime → FakeModelProvider
      → T7 validation → routing → durable Requirement

What matters is what the model *cannot* do. It cannot create a Requirement, assign
authority, own provenance, invent event provenance, bypass T7's grounding checks or
C24's exclusivity law, or touch the ledger. Every one of those remains with deterministic
Foundry code, and the tests below try to violate each and prove it fails.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest

from foundry.adapters.intent_synthesis.model_runtime import (
    INTENT_SYNTHESIS_POLICY_VERSION,
    IntentAmbiguityDraft,
    IntentSynthesisDraftPayload,
    ModelRuntimeIntentSynthesizer,
)
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.intent_synthesis import synthesize_intent
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    RelationType,
    SourceKind,
)
from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload
from foundry.domain.evidence import evidence_item
from foundry.domain.gaps import GapKind
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisPolicy,
    IntentSynthesisRoute,
    RequirementSynthesisProposal,
)
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import Intent, Requirement
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.domain.state import IntentState
from foundry.model_runtime.domain import (
    ModelCapability,
    ModelDescriptor,
    ModelIdentity,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime

PROJECT = "PROJ-MR3-INT"
SCOPE = "payments"
AT = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
ALICE = "human://alice"
HUMAN = ReasonerFingerprint(provider="human", model=ALICE, policy_version="p1")
MODEL = ModelIdentity(provider="provider-a", model="model-a")
RUN = "RUN-MR3"
POLICY = IntentSynthesisPolicy()
PROV = Provenance(source_kind=SourceKind.HUMAN, source_ref=ALICE)


def _refuse_network(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("network access is forbidden in the MR3 integration bridge")


@pytest.fixture(autouse=True, scope="module")
def socket_guard() -> Iterator[None]:
    patcher = pytest.MonkeyPatch()
    patcher.setattr(socket.socket, "connect", _refuse_network)
    patcher.setattr(socket, "create_connection", _refuse_network)
    try:
        yield
    finally:
        patcher.undo()


def _clock() -> Callable[[], datetime]:
    ticks = count()
    return lambda: AT.replace(minute=next(ticks) % 60)


def _judgment(jid: str, proposal: JudgmentProposal, ev: tuple[str, ...]) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=jid,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=ev,
        rationale="stated by the product owner",
        reasoner=HUMAN,
        invocation_id=f"INV-{jid}",
        proposed_at=AT,
    )


def substrate(store: InMemoryEventStore) -> str:
    """Evidence → address → claim → canonical Intent. Returns the live claim id."""
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=lambda prefix: f"{prefix}-{next(_IDS):03d}",
    )
    governor.ingest(
        evidence_item(
            evidence_id="EV-1",
            project_id=PROJECT,
            source_kind=SourceKind.HUMAN,
            source_ref=ALICE,
            content="Refunds must complete within thirty days.",
            observed_at=AT,
            scope=(SCOPE,),
        )
    )
    decision = governor.submit(
        _judgment(
            "J-addr",
            CreateAddressProposal(
                candidate=SemanticCandidate(
                    candidate_id="CAND-1",
                    subject="Refund window",
                    facet="How long?",
                    scope=(SCOPE,),
                    evidence_ids=("EV-1",),
                )
            ),
            ("EV-1",),
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY
    address = address_id_for(PROJECT, "J-addr")
    decision = governor.submit(
        _judgment(
            "J-claim",
            AssertClaimProposal(
                address_id=address,
                predicate="refund_window",
                value=ClaimValue(kind=ClaimValueKind.TEXT, text="thirty days"),
                evidence_ids=("EV-1",),
                authority=Authority.INFERRED,
            ),
            ("EV-1",),
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY

    store.append(
        EventEnvelope(
            event_id="object-INTENT",
            project_id=PROJECT,
            event_type=EventType.SEMANTIC_OBJECT_RECORDED,
            occurred_at=AT,
            payload=SemanticObjectPayload(
                object=Intent(
                    id="INTENT-payments",
                    project_id=PROJECT,
                    authority=Authority.CANONICAL,
                    confidence=1.0,
                    provenance=PROV,
                    created_at=AT,
                    scope=(SCOPE,),
                    mission="Refunds are fast and predictable.",
                )
            ),
        ),
        expected_sequence=store.current_sequence(PROJECT),
    )
    return claim_id_for(PROJECT, "J-claim")


_IDS = count(1)


def build_synthesizer(
    store: InMemoryEventStore, *payloads: IntentSynthesisDraftPayload
) -> tuple[ModelRuntimeIntentSynthesizer, FakeModelProvider]:
    provider = FakeModelProvider(
        provider_id=MODEL.provider,
        responses=tuple(
            ScriptedResponse(output=p, model=MODEL.model, finish_reason="stop") for p in payloads
        ),
    )
    runtime = ModelRuntime(
        registry=ModelRegistry(
            descriptors=(
                ModelDescriptor(
                    identity=MODEL,
                    tiers=frozenset({ModelTier.REASONER}),
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                    ),
                    # Test-local certification only; no real model is certified here.
                    certified_tasks=frozenset({ModelTask.INTENT_SYNTHESIS}),
                ),
            )
        ),
        providers=(provider,),
    )
    traces = iter(ModelTraceContext(run_id="T", call_id=f"C-{n}") for n in range(1, 50))
    return (
        ModelRuntimeIntentSynthesizer(
            runtime=runtime, model_identity=MODEL, trace_factory=lambda: next(traces)
        ),
        provider,
    )


def run_synthesis(store: InMemoryEventStore, synthesizer: ModelRuntimeIntentSynthesizer) -> Any:
    return synthesize_intent(
        store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=synthesizer,
        policy=POLICY,
        clock=lambda: AT,
        synthesis_run_id_factory=lambda: RUN,
        human_actor_id=None,
    )


def state_of(store: InMemoryEventStore) -> IntentState:
    return replay(PROJECT, store.load(PROJECT))


def proposal(
    claim_id: str,
    *,
    disposition: IntentDisposition = IntentDisposition.NEW,
    relates_to: str | None = None,
    confidence: float | None = 0.58,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id="p1",
        disposition=disposition,
        statement="Refunds complete within thirty days.",
        rationale="The live claim states a thirty day window.",
        basis_claim_ids=(claim_id,),
        relates_to_object_id=relates_to,
        confidence=confidence,
    )


# --- §19 the Requirement vertical --------------------------------------------------------


def test_a_model_proposal_becomes_a_durable_requirement_through_the_real_t8_path() -> None:
    store = InMemoryEventStore()
    claim_id = substrate(store)
    synthesizer, provider = build_synthesizer(
        store, IntentSynthesisDraftPayload(proposals=(proposal(claim_id),))
    )

    outcome = run_synthesis(store, synthesizer)

    assert provider.calls == 1
    assert [d.route for d in outcome.decisions] == [IntentSynthesisRoute.APPLY]

    state = state_of(store)
    record = next(iter(state.intent_synthesis.decisions.values()))
    requirement_id = record.identity.object_id("REQ")
    requirement = state.objects[requirement_id]
    assert isinstance(requirement, Requirement)

    # Authorship is the configured runtime identity, and it is truthful.
    assert record.author.provider == MODEL.provider
    assert record.author.model == MODEL.model
    assert record.author.policy_version == INTENT_SYNTHESIS_POLICY_VERSION
    assert record.author == synthesizer.fingerprint

    # Everything the model may not own stayed with runtime.
    assert requirement.authority is Authority.PROPOSED  # assigned by routing, not the model
    assert requirement.materiality is Materiality.LOW
    assert tuple(requirement.scope) == (SCOPE,)
    assert requirement.created_at == record.decided_at
    assert requirement.provenance.source_kind is SourceKind.SYSTEM
    assert requirement.provenance.source_event_ids == (record.decision_event_id,)
    assert [(r.relation_type, r.target_id) for r in requirement.relations] == [
        (RelationType.DERIVED_FROM, claim_id)
    ]
    assert requirement.confidence == 0.58
    assert requirement.lifecycle is LifecycleStatus.ACTIVE


# --- §20 the ambiguity vertical -------------------------------------------------------------


def test_a_model_ambiguity_becomes_a_durable_synthesis_gap_and_no_requirement() -> None:
    store = InMemoryEventStore()
    substrate(store)
    synthesizer, provider = build_synthesizer(
        store,
        IntentSynthesisDraftPayload(
            ambiguity_gaps=(
                IntentAmbiguityDraft(
                    proposal_id="g1",
                    subject_key="refund-window",
                    description="Calendar and business days are both consistent.",
                    confidence=0.4,
                ),
            )
        ),
    )

    outcome = run_synthesis(store, synthesizer)

    assert provider.calls == 1
    assert outcome.decisions == ()
    state = state_of(store)
    gaps = [g for g in state.gaps.values() if isinstance(g, IntentSynthesisGap)]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.kind is GapKind.AMBIGUITY
    assert gap.blocking is True
    assert gap.scope == (SCOPE,)  # runtime-owned
    assert gap.materiality is None  # never invented
    assert gap.risk is None
    assert gap.confidence == 0.4
    assert gap.subject_key == "refund-window"
    assert gap.model_gap_proposal_id == "g1"
    assert state.objects.get("REQ") is None
    assert EventType.INTENT_OBJECT_SYNTHESIZED not in [
        s.event.event_type for s in store.load(PROJECT)
    ]


# --- §21 malformed model output stays non-durable ----------------------------------------------


def _durable_synthesis_events(store: InMemoryEventStore) -> list[EventType]:
    return [
        s.event.event_type
        for s in store.load(PROJECT)
        if s.event.event_type
        in {
            EventType.INTENT_SYNTHESIS_DECIDED,
            EventType.INTENT_OBJECT_SYNTHESIZED,
            EventType.GAP_RECORDED,
        }
    ]


def test_a_proposal_citing_an_invisible_claim_is_refused_by_t7() -> None:
    store = InMemoryEventStore()
    substrate(store)
    synthesizer, _ = build_synthesizer(
        store, IntentSynthesisDraftPayload(proposals=(proposal("CLAIM-never-shown"),))
    )
    with pytest.raises(Exception, match="invisible|not shown|absent"):
        run_synthesis(store, synthesizer)
    assert _durable_synthesis_events(store) == []


def test_a_proposal_naming_an_object_absent_from_the_snapshot_is_refused() -> None:
    store = InMemoryEventStore()
    claim_id = substrate(store)
    synthesizer, _ = build_synthesizer(
        store,
        IntentSynthesisDraftPayload(
            proposals=(
                proposal(
                    claim_id,
                    disposition=IntentDisposition.REPLACES_STALE,
                    relates_to="REQ-does-not-exist",
                ),
            )
        ),
    )
    with pytest.raises(Exception, match="known-intent snapshot|not in the known"):
        run_synthesis(store, synthesizer)
    assert _durable_synthesis_events(store) == []


def test_a_mixed_result_is_refused_by_c24() -> None:
    store = InMemoryEventStore()
    claim_id = substrate(store)
    synthesizer, _ = build_synthesizer(
        store,
        IntentSynthesisDraftPayload(
            proposals=(proposal(claim_id),),
            ambiguity_gaps=(
                IntentAmbiguityDraft(
                    proposal_id="g1", subject_key="s", description="d", confidence=0.2
                ),
            ),
        ),
    )
    with pytest.raises(Exception, match="C24|both"):
        run_synthesis(store, synthesizer)
    assert _durable_synthesis_events(store) == []


def test_an_empty_result_is_refused_by_c24() -> None:
    store = InMemoryEventStore()
    substrate(store)
    synthesizer, _ = build_synthesizer(store, IntentSynthesisDraftPayload())
    with pytest.raises(Exception, match="C24|empty"):
        run_synthesis(store, synthesizer)
    assert _durable_synthesis_events(store) == []


# --- §22 the no-call fence survives ---------------------------------------------------------------


def test_a_scope_with_nothing_eligible_never_reaches_the_model_runtime() -> None:
    """T8 must not create model work merely because a runtime-backed synthesizer exists."""
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=lambda prefix: f"{prefix}-{next(_IDS):03d}",
    )
    governor.ingest(
        evidence_item(
            evidence_id="EV-1",
            project_id=PROJECT,
            source_kind=SourceKind.HUMAN,
            source_ref=ALICE,
            content="nothing claimed yet",
            observed_at=AT,
            scope=(SCOPE,),
        )
    )
    governor.submit(
        _judgment(
            "J-addr",
            CreateAddressProposal(
                candidate=SemanticCandidate(
                    candidate_id="CAND-1",
                    subject="Refund window",
                    facet="How long?",
                    scope=(SCOPE,),
                    evidence_ids=("EV-1",),
                )
            ),
            ("EV-1",),
        ),
        human_actor_id=ALICE,
    )
    # An address with no claim leaves the locus OPEN: nothing is eligible.
    synthesizer, provider = build_synthesizer(store)

    outcome = run_synthesis(store, synthesizer)

    assert provider.calls == 0
    assert outcome.decisions == ()
    assert _durable_synthesis_events(store) == []
