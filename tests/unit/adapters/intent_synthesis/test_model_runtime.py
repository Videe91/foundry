"""MR3 — the Intent Synthesis port, wired to the shared Model Runtime.

Everything below is real except the provider: a real ``ModelRuntime``, a real registry,
the real adapter. Mocking the runtime would prove nothing about the integration this
slice exists to establish.

Two laws carry the weight.

**Authorship must stay truthful.** T8 reads ``synthesizer.fingerprint`` *before* the call
and writes it as durable authorship on the decision. So a runtime-backed synthesizer is
bound to one expected ``ModelIdentity``, and if the runtime executes a different model the
adapter fails closed rather than letting a decision record name a model that never ran.

**The model must not be able to say things it cannot honestly know.** The legacy
``GapProposal`` carries ``source_event_ids`` and a free ``GapKind``, but the Intent request
exposes no event ids at all. The model-facing draft therefore has no such fields — it
cannot express them, rather than being trusted not to.
"""

from __future__ import annotations

import hashlib

import pytest

from foundry.adapters.intent_synthesis.model_runtime import (
    INTENT_SYNTHESIS_POLICY_ID,
    INTENT_SYNTHESIS_POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
    IntentAmbiguityDraft,
    IntentSynthesisDraftPayload,
    ModelRuntimeIntentSynthesizer,
    render_intent_synthesis_request,
)
from foundry.domain.common import Authority, SourceKind
from foundry.domain.gaps import GapKind
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisResult,
    RequirementSynthesisProposal,
)
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, IssueEpistemicState
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.errors import ModelProtocolError
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from foundry.ports.intent_synthesizer import (
    BasisClaim,
    IntentSynthesisRequest,
    IntentSynthesizer,
    KnownIntentObject,
    LocusBasis,
)

PROVIDER_A = ModelIdentity(provider="provider-a", model="model-a")
PROVIDER_B = ModelIdentity(provider="provider-b", model="model-b")


def basis_claim(claim_id: str = "CLAIM-1") -> BasisClaim:
    return BasisClaim(
        claim_id=claim_id,
        predicate="refund_window",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="thirty days"),
        effective_evidence_ids=("EV-1",),
        authority=Authority.INFERRED,
        source_kinds=(SourceKind.HUMAN,),
    )


def synthesis_request(*, known: tuple[KnownIntentObject, ...] = ()) -> IntentSynthesisRequest:
    return IntentSynthesisRequest(
        project_id="PROJ-MR3",
        scope="payments",
        basis=(
            LocusBasis(
                locus_representative_id="ADDR-1",
                address_ids=("ADDR-1",),
                subject="Refund window",
                facet="How long?",
                live_claims=(basis_claim(),),
                epistemic_state=IssueEpistemicState.CLAIMED,
            ),
        ),
        known_intent_objects=known,
        allowed_target_kinds=frozenset({SemanticKind.REQUIREMENT}),
    )


def proposal(
    model_proposal_id: str = "p1", *, confidence: float | None = 0.61
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=model_proposal_id,
        disposition=IntentDisposition.NEW,
        statement="Refunds complete within thirty days.",
        rationale="The live claim states a thirty day window.",
        basis_claim_ids=("CLAIM-1",),
        confidence=confidence,
    )


def ambiguity(proposal_id: str = "g1", *, confidence: float = 0.4) -> IntentAmbiguityDraft:
    return IntentAmbiguityDraft(
        proposal_id=proposal_id,
        subject_key="refund-window",
        description="Calendar days and business days are both consistent with the basis.",
        confidence=confidence,
    )


def descriptor(identity: ModelIdentity) -> ModelDescriptor:
    return ModelDescriptor(
        identity=identity,
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
        ),
        # Test-local only. No production registry certifies any real model for this task.
        certified_tasks=frozenset({ModelTask.INTENT_SYNTHESIS}),
    )


def scripted(payload: IntentSynthesisDraftPayload, identity: ModelIdentity) -> ScriptedResponse:
    return ScriptedResponse(output=payload, model=identity.model, finish_reason="stop")


def build(
    *payloads: IntentSynthesisDraftPayload,
    identity: ModelIdentity = PROVIDER_A,
    registry_identity: ModelIdentity | None = None,
    constraints: ModelExecutionConstraints | None = None,
) -> tuple[ModelRuntimeIntentSynthesizer, FakeModelProvider]:
    routed = registry_identity or identity
    provider = FakeModelProvider(
        provider_id=routed.provider,
        responses=tuple(scripted(p, routed) for p in payloads),
    )
    runtime = ModelRuntime(
        registry=ModelRegistry(descriptors=(descriptor(routed),)), providers=(provider,)
    )
    traces = iter(ModelTraceContext(run_id="RUN-1", call_id=f"CALL-{n}") for n in range(1, 100))
    synthesizer = ModelRuntimeIntentSynthesizer(
        runtime=runtime,
        model_identity=identity,
        trace_factory=lambda: next(traces),
        execution_constraints=constraints or ModelExecutionConstraints(),
    )
    return synthesizer, provider


# --- port conformance and authorship ----------------------------------------------------------


def test_the_adapter_satisfies_the_certified_intent_port() -> None:
    """Structural conformance, without touching the certified port.

    ``IntentSynthesizer`` is not ``@runtime_checkable``, and making it so to satisfy an
    ``isinstance`` call would mean editing a certified contract for a test's convenience.
    The binding proof is static: the annotated assignment below is what mypy verifies on
    every run. The members are checked here so a signature drift fails loudly too.
    """
    import inspect

    synthesizer, _ = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))

    # mypy proves protocol conformance at this line.
    port: IntentSynthesizer = synthesizer

    assert isinstance(type(port).fingerprint, property)
    signature = inspect.signature(port.synthesize)
    assert list(signature.parameters) == ["request"]
    assert signature.return_annotation in (IntentSynthesisResult, "IntentSynthesisResult")


def test_the_fingerprint_is_the_configured_identity_never_the_models_claim() -> None:
    synthesizer, _ = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))
    fingerprint = synthesizer.fingerprint
    assert fingerprint.provider == PROVIDER_A.provider
    assert fingerprint.model == PROVIDER_A.model
    assert fingerprint.policy_version == INTENT_SYNTHESIS_POLICY_VERSION


def test_the_fingerprint_is_available_before_any_call_is_made() -> None:
    """T8 reads it first and writes it as durable authorship; it cannot depend on output."""
    synthesizer, provider = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))
    _ = synthesizer.fingerprint
    assert provider.calls == 0


def test_a_runtime_that_executes_another_model_fails_closed() -> None:
    """The decision record must never name a model that did not run.

    The runtime may consider the routed model perfectly valid; the adapter still refuses,
    because T8 has already read the configured identity as author.
    """
    synthesizer, provider = build(
        IntentSynthesisDraftPayload(proposals=(proposal(),)),
        identity=PROVIDER_A,
        registry_identity=PROVIDER_B,
    )
    with pytest.raises(ModelProtocolError, match="provider-b|provider-a"):
        synthesizer.synthesize(synthesis_request())


def test_a_matching_identity_succeeds() -> None:
    synthesizer, _ = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))
    result = synthesizer.synthesize(synthesis_request())
    assert len(result.proposals) == 1


# --- policy identity and the frozen prompt ----------------------------------------------------


def test_the_policy_labels_are_pinned() -> None:
    assert INTENT_SYNTHESIS_POLICY_ID
    assert INTENT_SYNTHESIS_POLICY_VERSION
    assert INTENT_SYNTHESIS_POLICY_ID != INTENT_SYNTHESIS_POLICY_VERSION


def test_the_system_instruction_matches_its_pasted_hash() -> None:
    """A prompt edit must force an explicit hash update and a policy-version bump.

    The expected digest is a pasted literal, never computed at import time: computing it
    would make this test agree with any prompt whatsoever.
    """
    actual = hashlib.sha256(SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    assert actual == SYSTEM_INSTRUCTION_SHA256


def test_the_system_instruction_states_the_slice_one_laws() -> None:
    text = SYSTEM_INSTRUCTION
    for law in (
        "REQUIREMENT",
        "claim_id",
        "known_intent_objects",
        "NEW",
        "EXISTING_UNCHANGED",
        "REPLACES_STALE",
        "is_stale",
    ):
        assert law in text, law
    for forbidden in ("CANONICAL", "PROPOSED", "authority", "materiality", "scope"):
        assert forbidden in text, f"the instruction must forbid emitting {forbidden}"


# --- the ModelRequest mapping -----------------------------------------------------------------


def test_the_request_is_mapped_to_an_intent_synthesis_reasoner_call() -> None:
    synthesizer, provider = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))
    synthesizer.synthesize(synthesis_request())

    sent = provider.requests[0].request
    assert sent.task is ModelTask.INTENT_SYNTHESIS
    assert sent.tier is ModelTier.REASONER
    assert sent.required_capabilities == frozenset(
        {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
    )
    assert sent.policy_id == INTENT_SYNTHESIS_POLICY_ID
    assert sent.policy_version == INTENT_SYNTHESIS_POLICY_VERSION
    assert sent.trace.run_id == "RUN-1"
    assert sent.trace.call_id == "CALL-1"


def test_exactly_two_messages_are_sent_system_then_user() -> None:
    synthesizer, provider = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))
    request = synthesis_request()
    synthesizer.synthesize(request)

    messages = provider.requests[0].request.messages
    assert len(messages) == 2
    assert messages[0].role is MessageRole.SYSTEM
    assert messages[0].content == SYSTEM_INSTRUCTION
    assert messages[1].role is MessageRole.USER
    assert messages[1].content == render_intent_synthesis_request(request)


def test_the_caller_owned_output_type_reaches_the_runtime() -> None:
    synthesizer, provider = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))
    synthesizer.synthesize(synthesis_request())
    assert provider.requests[0].output_type is IntentSynthesisDraftPayload


def test_configured_execution_constraints_are_carried_through() -> None:
    constraints = ModelExecutionConstraints(max_output_tokens=4096, timeout_seconds=90.0)
    synthesizer, provider = build(
        IntentSynthesisDraftPayload(proposals=(proposal(),)), constraints=constraints
    )
    synthesizer.synthesize(synthesis_request())
    assert provider.requests[0].request.constraints == constraints


# --- rendering: exactly the approved request, nothing more ------------------------------------


def test_rendering_is_deterministic() -> None:
    request = synthesis_request()
    assert render_intent_synthesis_request(request) == render_intent_synthesis_request(request)


def test_rendering_contains_the_approved_request_fields() -> None:
    rendered = render_intent_synthesis_request(synthesis_request())
    for field in (
        "PROJ-MR3",
        "payments",
        "ADDR-1",
        "Refund window",
        "How long?",
        "CLAIM-1",
        "refund_window",
        "thirty days",
        "EV-1",
        "CLAIMED",
        "REQUIREMENT",
    ):
        assert field in rendered, field


def test_rendering_adds_no_context_beyond_the_request() -> None:
    """The adapter renders what T7 approved. It fetches nothing and enriches nothing."""
    import json

    request = synthesis_request()
    rendered = render_intent_synthesis_request(request)
    assert json.loads(rendered) == request.model_dump(mode="json")


def test_rendering_carries_no_ledger_or_evidence_content() -> None:
    rendered = render_intent_synthesis_request(synthesis_request()).lower()
    for leak in ("eventstore", "intentstate", "judgment", "rationale_text", "event_id"):
        assert leak not in rendered, leak


# --- the model-facing draft cannot express what it cannot know --------------------------------


def test_the_ambiguity_draft_has_no_field_for_invented_provenance() -> None:
    """§7: the request exposes no event ids, so the model gets no way to supply any."""
    fields = set(IntentAmbiguityDraft.model_fields)
    assert fields == {"proposal_id", "subject_key", "description", "confidence"}
    for forbidden in ("source_event_ids", "affected_proposal_ids", "blocking", "kind"):
        assert forbidden not in fields


def test_the_draft_payload_carries_no_authority_or_durable_identity() -> None:
    for model in (IntentSynthesisDraftPayload, IntentAmbiguityDraft):
        for forbidden in (
            "authority",
            "assigned_authority",
            "materiality",
            "scope",
            "object_id",
            "event_id",
            "provenance",
            "relations",
            "proposal_instance_id",
            "created_at",
        ):
            assert forbidden not in model.model_fields, (model.__name__, forbidden)


# --- mapping into the certified domain result -------------------------------------------------


def test_a_requirement_proposal_round_trips_without_field_loss() -> None:
    original = proposal(confidence=0.61)
    synthesizer, _ = build(IntentSynthesisDraftPayload(proposals=(original,)))
    result = synthesizer.synthesize(synthesis_request())
    assert result.proposals == (original,)


@pytest.mark.parametrize("confidence", [None, 0.0, 0.61, 1.0])
def test_proposal_confidence_is_preserved_exactly(confidence: float | None) -> None:
    synthesizer, _ = build(
        IntentSynthesisDraftPayload(proposals=(proposal(confidence=confidence),))
    )
    result = synthesizer.synthesize(synthesis_request())
    assert result.proposals[0].confidence == confidence


def test_an_ambiguity_draft_maps_deterministically_to_a_blocking_ambiguity_gap() -> None:
    synthesizer, _ = build(IntentSynthesisDraftPayload(ambiguity_gaps=(ambiguity(),)))
    result = synthesizer.synthesize(synthesis_request())

    assert result.proposals == ()
    assert len(result.gap_proposals) == 1
    gap = result.gap_proposals[0]
    assert gap.proposal_id == "g1"
    assert gap.kind is GapKind.AMBIGUITY
    assert gap.subject_key == "refund-window"
    assert gap.blocking is True
    assert gap.source_event_ids == ()
    assert gap.affected_proposal_ids == ()
    assert gap.confidence == 0.4


# --- malformed output is preserved for the certified validators, never repaired ---------------


def test_a_mixed_result_is_passed_through_for_t8_to_reject() -> None:
    """C24 is T8's law. The adapter must not pick a branch or silently repair."""
    synthesizer, _ = build(
        IntentSynthesisDraftPayload(proposals=(proposal(),), ambiguity_gaps=(ambiguity(),))
    )
    result = synthesizer.synthesize(synthesis_request())
    assert len(result.proposals) == 1
    assert len(result.gap_proposals) == 1


def test_an_empty_result_is_passed_through_for_t8_to_reject() -> None:
    synthesizer, _ = build(IntentSynthesisDraftPayload())
    result = synthesizer.synthesize(synthesis_request())
    assert result.proposals == ()
    assert result.gap_proposals == ()


# --- provider neutrality ----------------------------------------------------------------------


def test_the_same_intent_adapter_works_across_two_different_providers() -> None:
    """The first proof that the Intent layer is genuinely plug-and-play."""
    request = synthesis_request()
    payload = IntentSynthesisDraftPayload(proposals=(proposal(),))

    a, provider_a = build(payload, identity=PROVIDER_A)
    b, provider_b = build(payload, identity=PROVIDER_B)

    result_a = a.synthesize(request)
    result_b = b.synthesize(request)

    assert provider_a.calls == 1
    assert provider_b.calls == 1
    assert result_a == result_b
    assert a.fingerprint.provider == "provider-a"
    assert b.fingerprint.provider == "provider-b"
    # Same request, same adapter class, same output schema, different executor.
    assert type(a) is type(b)
    assert provider_a.requests[0].request == provider_b.requests[0].request


# --- bounded, stateless, single-call ----------------------------------------------------------


def test_one_synthesis_is_exactly_one_provider_call() -> None:
    synthesizer, provider = build(IntentSynthesisDraftPayload(proposals=(proposal(),)))
    synthesizer.synthesize(synthesis_request())
    assert provider.calls == 1


def test_a_second_synthesis_carries_nothing_from_the_first() -> None:
    """Law 3: no conversation, no history, no prior output as context."""
    first_payload = IntentSynthesisDraftPayload(proposals=(proposal("p1"),))
    second_payload = IntentSynthesisDraftPayload(proposals=(proposal("p2"),))
    synthesizer, provider = build(first_payload, second_payload)

    synthesizer.synthesize(synthesis_request())
    synthesizer.synthesize(synthesis_request())

    assert provider.calls == 2
    first_sent, second_sent = (r.request for r in provider.requests)
    assert len(second_sent.messages) == 2
    assert [m.role for m in second_sent.messages] == [MessageRole.SYSTEM, MessageRole.USER]
    assert "p1" not in second_sent.messages[1].content
    assert first_sent.messages[1].content == second_sent.messages[1].content


def test_the_adapter_imports_no_durable_foundry_machinery() -> None:
    import ast
    import pathlib

    source = pathlib.Path("src/foundry/adapters/intent_synthesis/model_runtime.py").read_text()
    tree = ast.parse(source)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    banned = {
        "foundry.ports.event_store",
        "foundry.domain.state",
        "foundry.domain.events",
        "foundry.application.reducer",
        "foundry.application.replay",
        "foundry.domain.closure",
        "foundry.application.package",
        "foundry.application.handoff_v2",
        "foundry.application.intent_synthesis",
    }
    assert mods & banned == set()
    for forbidden in ("EventStore", "IntentState", "EventEnvelope", "evaluate_closure"):
        assert forbidden not in source, forbidden


def test_the_adapter_never_routes_or_validates_governance() -> None:
    import pathlib

    source = pathlib.Path("src/foundry/adapters/intent_synthesis/model_runtime.py").read_text()
    for forbidden in ("route_intent_synthesis", "validate_intent_synthesis_result"):
        assert forbidden not in source, forbidden
