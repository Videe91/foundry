"""MR1 — single-call execution, and the errors that must stay distinguishable.

Runtime success means exactly two things: the provider call completed, and the transport,
identity and output contracts held. It never means the answer is right — generation does
not certify itself (Law 5), so nothing here reports verification.

The error taxonomy is deliberately not collapsed. "No model is certified for this" and
"the certified model's adapter is not installed" and "the provider substituted a
different model" are different operational failures with different fixes, and flattening
them would make the runtime unoperable at exactly the moment it matters.
"""

from __future__ import annotations

import pytest

from foundry.model_runtime.domain import (
    ModelCapability,
    ModelTask,
    ModelTier,
)
from foundry.model_runtime.errors import (
    ModelProtocolError,
    ModelProviderError,
    ModelProviderUnavailableError,
    ModelRequestError,
    ModelRuntimeError,
    ModelUnavailableError,
)
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from tests.unit.model_runtime._fixtures import (
    Answer,
    OtherAnswer,
    descriptor,
    identity,
    request,
    usage,
)

BOTH = frozenset({ModelTask.INTENT_SYNTHESIS, ModelTask.ARCHITECTURE})


def _runtime(
    *providers: FakeModelProvider, descriptors: tuple[object, ...] | None = None
) -> ModelRuntime:
    return ModelRuntime(
        registry=ModelRegistry(descriptors=descriptors or (descriptor(),)),  # type: ignore[arg-type]
        providers=providers,
    )


def _provider(provider_id: str = "provider-a", *responses: ScriptedResponse) -> FakeModelProvider:
    return FakeModelProvider(provider_id=provider_id, responses=responses)


def _ok(model: str = "model-1", output: object | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        output=output if output is not None else Answer(statement="refunds in thirty days"),
        model=model,
        usage=usage(),
        finish_reason="stop",
    )


# --- the happy path ---------------------------------------------------------------------------


def test_a_certified_request_reaches_exactly_one_provider_and_returns_typed_output() -> None:
    provider = _provider("provider-a", _ok())
    runtime = _runtime(provider)

    result = runtime.execute(request(), output_type=Answer)

    assert provider.calls == 1
    assert isinstance(result.output, Answer)
    assert result.output.statement == "refunds in thirty days"
    assert result.metadata.identity == identity()
    assert result.metadata.task is ModelTask.INTENT_SYNTHESIS
    assert result.metadata.tier is ModelTier.REASONER
    assert result.metadata.trace.run_id == "RUN-1"
    assert result.metadata.trace.call_id == "CALL-1"
    assert result.metadata.usage.input_tokens == 120
    assert result.metadata.finish_reason == "stop"


def test_the_provider_receives_the_caller_request_untouched() -> None:
    provider = _provider("provider-a", _ok())
    outgoing = request()
    _runtime(provider).execute(outgoing, output_type=Answer)

    seen = provider.requests[0]
    assert seen.request == outgoing
    assert seen.model == identity()
    assert seen.output_type is Answer


def test_one_execute_call_makes_at_most_one_provider_call() -> None:
    """MR1 has no retry and no fallback; a failure is reported, not re-attempted."""
    provider = _provider("provider-a", _ok())
    _runtime(provider).execute(request(), output_type=Answer)
    assert provider.calls == 1


# --- failure taxonomy -------------------------------------------------------------------------


def test_no_certified_model_raises_unavailable_without_calling_any_provider() -> None:
    provider = _provider("provider-a", _ok())
    runtime = ModelRuntime(
        registry=ModelRegistry(
            descriptors=(descriptor(certified_tasks=frozenset({ModelTask.PLANNING})),)
        ),
        providers=(provider,),
    )
    with pytest.raises(ModelUnavailableError):
        runtime.execute(request(), output_type=Answer)
    assert provider.calls == 0


def test_a_certified_model_whose_adapter_is_absent_raises_provider_unavailable() -> None:
    """Never silently routed to a different, uncertified model."""
    runtime = ModelRuntime(registry=ModelRegistry(descriptors=(descriptor(),)), providers=())
    with pytest.raises(ModelProviderUnavailableError, match="provider-a"):
        runtime.execute(request(), output_type=Answer)


def test_an_absent_adapter_does_not_fall_through_to_an_installed_one() -> None:
    other = _provider("provider-b", _ok("model-2"))
    runtime = ModelRuntime(registry=ModelRegistry(descriptors=(descriptor(),)), providers=(other,))
    with pytest.raises(ModelProviderUnavailableError):
        runtime.execute(request(), output_type=Answer)
    assert other.calls == 0


def test_a_provider_transport_failure_is_wrapped_and_preserves_its_cause() -> None:
    boom = RuntimeError("connection reset")
    provider = FakeModelProvider(provider_id="provider-a", responses=(), raises=boom)
    with pytest.raises(ModelProviderError) as excinfo:
        _runtime(provider).execute(request(), output_type=Answer)
    assert excinfo.value.__cause__ is boom


def test_a_provider_returning_a_different_model_is_a_protocol_error() -> None:
    """A provider may not substitute a model; MR1 has no alias resolution."""
    provider = _provider("provider-a", _ok(model="model-9"))
    with pytest.raises(ModelProtocolError, match="model-9"):
        _runtime(provider).execute(request(), output_type=Answer)


def test_a_provider_returning_a_different_provider_id_is_a_protocol_error() -> None:
    provider = FakeModelProvider(
        provider_id="provider-a", responses=(_ok(),), reported_provider="provider-b"
    )
    with pytest.raises(ModelProtocolError):
        _runtime(provider).execute(request(), output_type=Answer)


def test_output_of_the_wrong_type_is_a_protocol_error_and_is_never_repaired() -> None:
    provider = _provider("provider-a", _ok(output=OtherAnswer(verdict="nope")))
    with pytest.raises(ModelProtocolError):
        _runtime(provider).execute(request(), output_type=Answer)


def test_structurally_invalid_output_is_a_protocol_error() -> None:
    provider = _provider("provider-a", _ok(output={"statement": ""}))
    with pytest.raises(ModelProtocolError):
        _runtime(provider).execute(request(), output_type=Answer)


def test_every_runtime_failure_shares_one_base_but_keeps_its_own_meaning() -> None:
    for error in (
        ModelRequestError,
        ModelUnavailableError,
        ModelProviderUnavailableError,
        ModelProviderError,
        ModelProtocolError,
    ):
        assert issubclass(error, ModelRuntimeError)
    distinct = {
        ModelRequestError,
        ModelUnavailableError,
        ModelProviderUnavailableError,
        ModelProviderError,
        ModelProtocolError,
    }
    assert len(distinct) == 5


# --- construction -----------------------------------------------------------------------------


def test_duplicate_provider_ids_are_refused_at_construction() -> None:
    with pytest.raises(ModelRequestError, match="duplicate"):
        ModelRuntime(
            registry=ModelRegistry(descriptors=(descriptor(),)),
            providers=(_provider("provider-a"), _provider("provider-a")),
        )


def test_a_runtime_may_be_built_with_no_providers_at_all() -> None:
    runtime = ModelRuntime(registry=ModelRegistry(descriptors=()), providers=())
    with pytest.raises(ModelUnavailableError):
        runtime.execute(request(), output_type=Answer)


# --- plug and play ----------------------------------------------------------------------------


def test_changing_only_the_registry_changes_which_provider_executes() -> None:
    """The core proof: the caller's request, output type and runtime API are identical."""
    a = _provider("provider-a", _ok("model-1"))
    b = _provider("provider-b", _ok("model-2"))
    descriptor_a = descriptor("provider-a", "model-1")
    descriptor_b = descriptor("provider-b", "model-2")
    outgoing = request()

    first = ModelRuntime(
        registry=ModelRegistry(descriptors=(descriptor_a, descriptor_b)), providers=(a, b)
    ).execute(outgoing, output_type=Answer)
    assert (a.calls, b.calls) == (1, 0)
    assert first.metadata.identity.provider == "provider-a"

    a2 = _provider("provider-a", _ok("model-1"))
    b2 = _provider("provider-b", _ok("model-2"))
    second = ModelRuntime(
        registry=ModelRegistry(descriptors=(descriptor_b,)), providers=(a2, b2)
    ).execute(outgoing, output_type=Answer)

    assert (a2.calls, b2.calls) == (0, 1)
    assert second.metadata.identity.provider == "provider-b"
    # Same caller contract, different executor.
    assert type(first.output) is type(second.output)


def test_one_model_certified_for_both_roles_executes_both_requests() -> None:
    dual = descriptor(
        tiers=frozenset({ModelTier.WORKER, ModelTier.REASONER}),
        certified_tasks=frozenset({ModelTask.CODING, ModelTask.ARCHITECTURE}),
    )
    provider = _provider("provider-a", _ok(), _ok())
    runtime = ModelRuntime(registry=ModelRegistry(descriptors=(dual,)), providers=(provider,))

    reasoning = runtime.execute(
        request(task=ModelTask.ARCHITECTURE, tier=ModelTier.REASONER), output_type=Answer
    )
    working = runtime.execute(
        request(
            task=ModelTask.CODING,
            tier=ModelTier.WORKER,
            required_capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        ),
        output_type=Answer,
    )

    assert provider.calls == 2
    assert reasoning.metadata.tier is ModelTier.REASONER
    assert working.metadata.tier is ModelTier.WORKER
    assert reasoning.metadata.identity == working.metadata.identity


# --- generation does not certify itself -------------------------------------------------------


def test_nothing_in_the_result_claims_the_answer_is_correct() -> None:
    provider = _provider("provider-a", _ok())
    result = _runtime(provider).execute(request(), output_type=Answer)
    for model in (type(result), type(result.metadata), type(result.metadata.usage)):
        forbidden = {
            name
            for name in getattr(model, "model_fields", {})
            if any(k in name for k in ("verified", "correct", "accepted", "certified", "valid"))
        }
        assert forbidden == set(), forbidden
