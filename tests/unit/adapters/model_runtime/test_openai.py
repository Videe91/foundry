"""MR5 — OpenAI as the second real provider behind the certified Model Runtime.

Everything Foundry owns is real here: a real ``ModelRuntime``, a real ``ModelRegistry``,
the real ``OpenAIModelProvider``. Only the OpenAI SDK boundary is doubled, because a test
that fakes the adapter proves nothing about the adapter.

These are transport and protocol laws, not quality claims. MR5 shows GPT-6 Astra can
execute correctly through the universal socket. It says nothing about whether Astra is
trustworthy for Intent Synthesis — that is a task-specific certification, and it is MR6,
run through the exact exam already used for Grok.

Several laws here are load-bearing rather than stylistic, and each has a negative control
that fails if the law is removed:

* ``max_retries=0`` — the installed SDK defaults to **2**, so a Foundry execution would
  silently become up to three provider attempts without this;
* ``store=False`` — the Responses API stores by default, which would turn a stateless
  bounded call into provider-side memory;
* ``reasoning.context="current_turn"`` — prior-turn reasoning must not leak into a call
  that claims to be bounded;
* identity read from ``response.model`` — echoing the request would make the runtime's
  substitution check agree with itself.
"""

from __future__ import annotations

from typing import Any

import openai
import pytest
from openai.lib._parsing._responses import parse_text, type_to_text_format_param
from pydantic import Field, ValidationError

from foundry.adapters.model_runtime.openai import OPENAI_PROVIDER_ID, OpenAIModelProvider
from foundry.adapters.model_runtime.openai_wire_schema import openai_text_format
from foundry.domain.common import FrozenModel
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.errors import (
    ModelProtocolError,
    ModelProviderError,
    ModelRequestError,
)
from foundry.model_runtime.ports import ModelProvider
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from tests.unit.adapters.model_runtime._fake_openai import (
    FakeIncompleteDetails,
    FakeMessage,
    FakeOutputText,
    FakeResponse,
    FakeUsage,
    RecordingClientFactory,
    parsed_response,
    refusal_response,
)

ASTRA = "gpt-6-astra"
IDENTITY = ModelIdentity(provider=OPENAI_PROVIDER_ID, model=ASTRA)
SECRET = "sk-test-do-not-leak-6f1a2b3c4d5e"


class Verdict(FrozenModel):
    """A caller-owned output type. The adapter never learns what it means."""

    statement: str = Field(min_length=1)
    score: int


def descriptor(
    *,
    model: str = ASTRA,
    tasks: frozenset[ModelTask] = frozenset({ModelTask.EVALUATION}),
) -> ModelDescriptor:
    return ModelDescriptor(
        identity=ModelIdentity(provider=OPENAI_PROVIDER_ID, model=model),
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
        ),
        certified_tasks=tasks,
    )


def request(
    *,
    messages: tuple[ModelMessage, ...] = (
        ModelMessage(role=MessageRole.SYSTEM, content="Be exact."),
        ModelMessage(role=MessageRole.USER, content="Score this."),
    ),
    constraints: ModelExecutionConstraints | None = None,
    task: ModelTask = ModelTask.EVALUATION,
) -> ModelRequest:
    return ModelRequest(
        task=task,
        tier=ModelTier.REASONER,
        messages=messages,
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id="mr5.transport",
        policy_version="mr5-openai-v1",
        constraints=constraints or ModelExecutionConstraints(),
        trace=ModelTraceContext(run_id="run-1", call_id="call-1"),
    )


def provider(
    factory: RecordingClientFactory,
    *,
    api_key: str = SECRET,
    reasoning_effort: Any = "high",
    reasoning_mode: Any = "standard",
    default_timeout_seconds: float | None = None,
    monotonic: Any = None,
) -> OpenAIModelProvider:
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "reasoning_effort": reasoning_effort,
        "reasoning_mode": reasoning_mode,
        "default_timeout_seconds": default_timeout_seconds,
        "client_factory": factory,
    }
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    return OpenAIModelProvider(**kwargs)


def runtime_for(
    factory: RecordingClientFactory,
    *,
    registry_model: str = ASTRA,
    tasks: frozenset[ModelTask] = frozenset({ModelTask.EVALUATION}),
    **provider_kwargs: Any,
) -> ModelRuntime:
    return ModelRuntime(
        registry=ModelRegistry(descriptors=(descriptor(model=registry_model, tasks=tasks),)),
        providers=(provider(factory, **provider_kwargs),),
    )


def verdict_response(*, model: str = ASTRA, usage: FakeUsage | None = None) -> FakeResponse:
    return parsed_response(Verdict(statement="ok", score=7), model=model, usage=usage)


# --- provider identity and port conformance ---------------------------------------------------


def test_the_provider_id_is_openai() -> None:
    assert provider(RecordingClientFactory()).provider_id == OPENAI_PROVIDER_ID
    assert OPENAI_PROVIDER_ID == "openai"


def test_the_adapter_satisfies_the_shared_provider_port() -> None:
    """Structural conformance to the port the runtime already certified."""
    instance: ModelProvider = provider(RecordingClientFactory())
    assert isinstance(instance, ModelProvider)


# --- refusals that happen before any network call ---------------------------------------------


def test_another_providers_identity_is_refused_before_any_client_is_built() -> None:
    factory = RecordingClientFactory()
    with pytest.raises(ModelRequestError, match="never"):
        provider(factory).execute(
            model=ModelIdentity(provider="xai", model="grok-4.7"),
            request=request(),
            output_type=Verdict,
        )
    assert factory.calls == [], "a wrong-provider request must not construct a client"
    assert factory.parse_calls == [], "a wrong-provider request must not reach the network"


def test_a_cost_budget_is_refused_before_the_network_rather_than_pretended() -> None:
    """MR5 has no trusted pre-call cost engine, so a budget is refused, never approximated."""
    factory = RecordingClientFactory()
    with pytest.raises(ModelRequestError, match="max_cost_usd"):
        provider(factory).execute(
            model=IDENTITY,
            request=request(constraints=ModelExecutionConstraints(max_cost_usd=5.0)),
            output_type=Verdict,
        )
    assert factory.calls == []
    assert factory.parse_calls == []


# --- the model string stays generic -----------------------------------------------------------


def test_the_adapter_executes_any_openai_model_it_is_handed() -> None:
    """Astra must not be hardcoded: which model is certified is a registry decision."""
    factory = RecordingClientFactory(verdict_response(model="gpt-6-luna"))
    result = runtime_for(factory, registry_model="gpt-6-luna").execute(
        request(), output_type=Verdict
    )
    assert result.metadata.identity.model == "gpt-6-luna"
    assert factory.only_parse_call["model"] == "gpt-6-luna"


# --- message fidelity -------------------------------------------------------------------------


def test_messages_reach_the_provider_in_the_same_order_roles_and_content() -> None:
    factory = RecordingClientFactory(verdict_response())
    messages = (
        ModelMessage(role=MessageRole.SYSTEM, content="First, be exact."),
        ModelMessage(role=MessageRole.USER, content="Second, score this."),
        ModelMessage(role=MessageRole.ASSISTANT, content="Third, prior turn."),
        ModelMessage(role=MessageRole.USER, content="Fourth, continue."),
    )
    runtime_for(factory).execute(request(messages=messages), output_type=Verdict)

    assert factory.only_parse_call["input"] == [
        {"role": "system", "content": "First, be exact."},
        {"role": "user", "content": "Second, score this."},
        {"role": "assistant", "content": "Third, prior turn."},
        {"role": "user", "content": "Fourth, continue."},
    ]


def test_no_hidden_prompt_or_instructions_are_added() -> None:
    """The model receives exactly what the domain supplied — nothing appended."""
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)
    call = factory.only_parse_call

    assert len(call["input"]) == 2, "the adapter must not add a message"
    assert "instructions" not in call, "system messages are not rewritten into instructions"


# --- statelessness ----------------------------------------------------------------------------


def test_every_call_is_stateless() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)
    call = factory.only_parse_call

    assert call["store"] is False, "the Responses API stores by default; Foundry must not"
    assert "previous_response_id" not in call
    assert "conversation" not in call
    assert call["reasoning"]["context"] == "current_turn"


def test_a_second_call_carries_nothing_from_the_first() -> None:
    first = parsed_response(Verdict(statement="first", score=1), model=ASTRA)
    second = parsed_response(Verdict(statement="second", score=2), model=ASTRA)
    factory = RecordingClientFactory(first, second)
    runtime = runtime_for(factory)

    runtime.execute(request(), output_type=Verdict)
    runtime.execute(request(), output_type=Verdict)

    assert len(factory.parse_calls) == 2
    for call in factory.parse_calls:
        assert call["store"] is False
        assert "previous_response_id" not in call
        assert "conversation" not in call
        assert len(call["input"]) == 2, "no prior output may be replayed into a later call"
    assert factory.parse_calls[0]["input"] == factory.parse_calls[1]["input"]


# --- one call is one attempt ------------------------------------------------------------------


def test_sdk_retries_are_disabled() -> None:
    """The installed SDK defaults ``max_retries`` to 2; Foundry promises one attempt."""
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)

    assert factory.calls[0]["max_retries"] == 0


def test_the_installed_sdk_really_does_retry_by_default() -> None:
    """Pins the reason the law above exists, so it cannot be dismissed as ceremony."""
    import inspect

    default = inspect.signature(openai.OpenAI.__init__).parameters["max_retries"].default
    assert default != 0, "if the SDK stopped retrying by default, this law needs rereading"


def test_one_runtime_execution_is_exactly_one_provider_call() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)
    assert len(factory.parse_calls) == 1


# --- no tools, no sampling knobs --------------------------------------------------------------


def test_no_tool_or_agent_capability_is_enabled() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)
    call = factory.only_parse_call

    assert call.get("tools", []) == []
    for forbidden in (
        "tool_choice",
        "max_tool_calls",
        "parallel_tool_calls",
        "background",
        "stream",
        "conversation",
        "prompt",
    ):
        assert forbidden not in call, f"MR5 is a single bounded call; {forbidden} is not MR5"


def test_temperature_and_top_p_are_never_sent() -> None:
    """Astra does not support custom values; reasoning effort is the only quality knob."""
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)
    call = factory.only_parse_call

    assert "temperature" not in call
    assert "top_p" not in call


# --- reasoning configuration ------------------------------------------------------------------


def test_the_first_configuration_sends_high_effort_in_standard_mode() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)

    assert factory.only_parse_call["reasoning"] == {
        "effort": "high",
        "mode": "standard",
        "context": "current_turn",
    }


def test_reasoning_configuration_is_adapter_state_not_request_state() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory, reasoning_effort="max", reasoning_mode="pro").execute(
        request(), output_type=Verdict
    )
    reasoning = factory.only_parse_call["reasoning"]

    assert reasoning["effort"] == "max"
    assert reasoning["mode"] == "pro"
    assert reasoning["context"] == "current_turn"


# --- structured output ------------------------------------------------------------------------


def test_the_callers_output_type_reaches_the_wire_and_the_parsed_value_comes_back() -> None:
    factory = RecordingClientFactory(verdict_response())
    result = runtime_for(factory).execute(request(), output_type=Verdict)

    call = factory.only_parse_call
    assert "text_format" not in call, "the SDK refuses text_format beside a compiled schema"
    assert call["text"] == {"format": openai_text_format(Verdict)}
    assert result.output == Verdict(statement="ok", score=7)


def test_a_schema_without_oneof_goes_out_exactly_as_text_format_sent_it() -> None:
    """Existing callers keep a byte-identical wire contract."""
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)

    assert factory.only_parse_call["text"]["format"] == type_to_text_format_param(Verdict)


def test_the_answer_is_validated_exactly_as_the_sdk_parse_would() -> None:
    text = Verdict(statement="ok", score=7).model_dump_json()
    ours = runtime_for(RecordingClientFactory(verdict_response())).execute(
        request(), output_type=Verdict
    )
    assert ours.output == parse_text(text, text_format=Verdict, phase="final_answer")


def test_the_first_final_answer_wins_and_every_final_answer_is_validated() -> None:
    """The SDK's rule: all final texts are parsed (any failure refuses), the first is returned."""

    def two(second: str) -> FakeResponse:
        first = Verdict(statement="first", score=1).model_dump_json()
        return FakeResponse(
            model=ASTRA,
            status="completed",
            output=[FakeMessage(content=[FakeOutputText(text=first), FakeOutputText(text=second)])],
        )

    ok = runtime_for(
        RecordingClientFactory(two(Verdict(statement="second", score=2).model_dump_json()))
    )
    assert ok.execute(request(), output_type=Verdict).output == Verdict(statement="first", score=1)
    with pytest.raises(ModelProtocolError, match="could not be parsed"):
        runtime_for(RecordingClientFactory(two('{"score":2}'))).execute(
            request(), output_type=Verdict
        )


def test_a_non_final_phase_is_never_taken_as_the_answer() -> None:
    commentary = FakeResponse(
        model=ASTRA,
        status="completed",
        output=[
            FakeMessage(
                phase="commentary",
                content=[FakeOutputText(text=Verdict(statement="x", score=1).model_dump_json())],
            )
        ],
    )
    with pytest.raises(ModelProtocolError, match="structured output"):
        runtime_for(RecordingClientFactory(commentary)).execute(request(), output_type=Verdict)


def test_a_refusal_is_not_a_typed_success() -> None:
    factory = RecordingClientFactory(refusal_response(model=ASTRA))
    with pytest.raises(ModelProtocolError, match="refusal"):
        runtime_for(factory).execute(request(), output_type=Verdict)


def test_a_refusal_is_distinguished_from_merely_missing_output() -> None:
    """The SDK's ``output_parsed`` returns ``None`` for both; the adapter must not.

    Reporting a refusal as "no structured output" would send an operator looking for a
    schema bug when the model actually declined.
    """
    refused = RecordingClientFactory(refusal_response(model=ASTRA))
    with pytest.raises(ModelProtocolError) as refusal_error:
        runtime_for(refused).execute(request(), output_type=Verdict)

    empty = RecordingClientFactory(FakeResponse(model=ASTRA, status="completed", output=[]))
    with pytest.raises(ModelProtocolError) as missing_error:
        runtime_for(empty).execute(request(), output_type=Verdict)

    assert "refusal" in str(refusal_error.value)
    assert "refusal" not in str(missing_error.value)


def test_a_refusal_does_not_leak_the_refusal_text() -> None:
    """A bounded diagnostic: the operator learns the category, not the model's prose."""
    secret_prose = "I will not discuss the classified payload codenamed BLUEJAY"
    factory = RecordingClientFactory(refusal_response(model=ASTRA, refusal=secret_prose))
    with pytest.raises(ModelProtocolError) as error:
        runtime_for(factory).execute(request(), output_type=Verdict)

    assert "BLUEJAY" not in str(error.value)


def test_a_completed_response_with_no_parsed_output_is_a_protocol_failure() -> None:
    factory = RecordingClientFactory(FakeResponse(model=ASTRA, status="completed", output=[]))
    with pytest.raises(ModelProtocolError, match="structured output"):
        runtime_for(factory).execute(request(), output_type=Verdict)


def test_text_that_fails_the_callers_type_is_refused_never_repaired() -> None:
    """Text that merely looks like the schema is not a result: the missing field is not filled."""
    unparsed = FakeResponse(
        model=ASTRA,
        status="completed",
        output=[FakeMessage(content=[FakeOutputText(parsed=None, text='{"score":1}')])],
    )
    factory = RecordingClientFactory(unparsed)
    with pytest.raises(ModelProtocolError, match="could not be parsed") as error:
        runtime_for(factory).execute(request(), output_type=Verdict)
    assert isinstance(error.value.__cause__, ValidationError)


# --- incomplete and other non-completed responses ---------------------------------------------


@pytest.mark.parametrize("reason", ["max_output_tokens", "content_filter", "max_messages"])
def test_an_incomplete_response_is_never_a_success(reason: str) -> None:
    incomplete = FakeResponse(
        model=ASTRA,
        status="incomplete",
        incomplete_details=FakeIncompleteDetails(reason=reason),
        output=[
            FakeMessage(content=[FakeOutputText(parsed=Verdict(statement="partial", score=1))])
        ],
    )
    factory = RecordingClientFactory(incomplete)
    with pytest.raises(ModelProtocolError) as error:
        runtime_for(factory).execute(request(), output_type=Verdict)

    assert reason in str(error.value), "the operator needs to know why it was incomplete"


@pytest.mark.parametrize("status", ["failed", "cancelled", "in_progress", "queued"])
def test_any_non_completed_status_fails_closed(status: str) -> None:
    """The SDK defines several non-completed states; none of them is a success."""
    factory = RecordingClientFactory(
        FakeResponse(
            model=ASTRA,
            status=status,
            output=[FakeMessage(content=[FakeOutputText(parsed=Verdict(statement="x", score=1))])],
        )
    )
    with pytest.raises(ModelProtocolError, match=status):
        runtime_for(factory).execute(request(), output_type=Verdict)


def test_a_missing_status_fails_closed() -> None:
    factory = RecordingClientFactory(
        FakeResponse(
            model=ASTRA,
            status=None,
            output=[FakeMessage(content=[FakeOutputText(parsed=Verdict(statement="x", score=1))])],
        )
    )
    with pytest.raises(ModelProtocolError):
        runtime_for(factory).execute(request(), output_type=Verdict)


# --- executed identity ------------------------------------------------------------------------


def test_the_reported_identity_is_read_from_the_response_not_the_request() -> None:
    factory = RecordingClientFactory(verdict_response(model=ASTRA))
    result = runtime_for(factory).execute(request(), output_type=Verdict)

    assert result.metadata.identity == IDENTITY


def test_a_substituted_model_is_rejected_by_the_runtime() -> None:
    """If the adapter echoed the request, this substitution would pass unnoticed."""
    factory = RecordingClientFactory(verdict_response(model="gpt-6-luna"))
    with pytest.raises(ModelProtocolError, match="substitute"):
        runtime_for(factory).execute(request(), output_type=Verdict)


@pytest.mark.parametrize("missing", ["", None])
def test_a_response_without_a_model_identity_is_a_protocol_failure(missing: Any) -> None:
    factory = RecordingClientFactory(
        parsed_response(Verdict(statement="ok", score=1), model=missing)
    )
    with pytest.raises(ModelProtocolError, match="identity"):
        runtime_for(factory).execute(request(), output_type=Verdict)


# --- telemetry --------------------------------------------------------------------------------


def test_reported_usage_is_preserved() -> None:
    factory = RecordingClientFactory(
        verdict_response(usage=FakeUsage(input_tokens=321, output_tokens=45, total_tokens=366))
    )
    result = runtime_for(factory).execute(request(), output_type=Verdict)

    assert result.metadata.usage.input_tokens == 321
    assert result.metadata.usage.output_tokens == 45


def test_absent_usage_stays_unknown_rather_than_becoming_zero() -> None:
    """Unknown is not zero. A false zero corrupts every budget built on this metadata."""
    factory = RecordingClientFactory(verdict_response(usage=None))
    result = runtime_for(factory).execute(request(), output_type=Verdict)

    assert result.metadata.usage.input_tokens is None
    assert result.metadata.usage.output_tokens is None


def test_cost_is_unknown_because_the_responses_api_reports_none() -> None:
    """The adapter must not estimate from public pricing: that is a later cost engine."""
    factory = RecordingClientFactory(
        verdict_response(usage=FakeUsage(input_tokens=1000, output_tokens=500))
    )
    result = runtime_for(factory).execute(request(), output_type=Verdict)

    assert result.metadata.usage.cost_usd is None


def test_wall_clock_is_measured() -> None:
    ticks = iter([10.0, 12.5])
    factory = RecordingClientFactory(verdict_response())
    result = runtime_for(factory, monotonic=lambda: next(ticks)).execute(
        request(), output_type=Verdict
    )

    assert result.metadata.usage.wall_clock_ms == 2500


def test_no_finish_reason_is_invented() -> None:
    """The Responses API exposes status, not a Chat Completions finish reason."""
    factory = RecordingClientFactory(verdict_response())
    result = runtime_for(factory).execute(request(), output_type=Verdict)

    assert result.metadata.finish_reason is None


# --- constraints reach the transport ----------------------------------------------------------


def test_a_requested_timeout_reaches_the_transport() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(
        request(constraints=ModelExecutionConstraints(timeout_seconds=12.5)),
        output_type=Verdict,
    )
    assert factory.only_parse_call["timeout"] == 12.5


def test_the_configured_default_timeout_applies_when_the_request_has_none() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory, default_timeout_seconds=30.0).execute(request(), output_type=Verdict)
    assert factory.only_parse_call["timeout"] == 30.0


def test_a_requested_timeout_is_never_widened_to_the_default() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory, default_timeout_seconds=300.0).execute(
        request(constraints=ModelExecutionConstraints(timeout_seconds=5.0)),
        output_type=Verdict,
    )
    assert factory.only_parse_call["timeout"] == 5.0


def test_no_timeout_is_sent_when_neither_is_configured() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)
    assert "timeout" not in factory.only_parse_call


def test_max_output_tokens_is_passed_through() -> None:
    """For reasoning models this bound covers reasoning tokens too; it is not reinterpreted."""
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(
        request(constraints=ModelExecutionConstraints(max_output_tokens=4096)),
        output_type=Verdict,
    )
    assert factory.only_parse_call["max_output_tokens"] == 4096


def test_max_output_tokens_is_omitted_when_unset() -> None:
    factory = RecordingClientFactory(verdict_response())
    runtime_for(factory).execute(request(), output_type=Verdict)
    assert "max_output_tokens" not in factory.only_parse_call


# --- error boundary ---------------------------------------------------------------------------


def test_a_transport_failure_becomes_a_provider_error_not_a_schema_error() -> None:
    """MR2's lesson: a network fault must never read as 'the output could not be parsed'."""
    boom = openai.APIConnectionError(message="connection reset", request=None)  # type: ignore[arg-type]
    factory = RecordingClientFactory(boom)
    with pytest.raises(ModelProviderError) as error:
        runtime_for(factory).execute(request(), output_type=Verdict)

    assert error.value.__cause__ is boom, "the transport cause must stay diagnosable"


def test_a_timeout_is_transport_not_protocol() -> None:
    boom = openai.APITimeoutError(request=None)  # type: ignore[arg-type]
    factory = RecordingClientFactory(boom)
    with pytest.raises(ModelProviderError) as error:
        runtime_for(factory).execute(request(), output_type=Verdict)

    assert error.value.__cause__ is boom


def test_a_validation_failure_is_a_protocol_error_with_its_cause() -> None:
    invalid = FakeResponse(
        model=ASTRA,
        status="completed",
        output=[FakeMessage(content=[FakeOutputText(text='{"statement":"","score":0}')])],
    )
    factory = RecordingClientFactory(invalid)
    with pytest.raises(ModelProtocolError) as error:
        runtime_for(factory).execute(request(), output_type=Verdict)

    assert isinstance(error.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    "error_type",
    [openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError],
)
def test_sdk_truncation_errors_are_protocol_failures_not_transport(error_type: type) -> None:
    """These are ``OpenAIError`` but not ``APIError``: the call reached the model."""
    boom = error_type.__new__(error_type)
    BaseException.__init__(boom, "truncated")
    factory = RecordingClientFactory(boom)
    with pytest.raises(ModelProtocolError) as error:
        runtime_for(factory).execute(request(), output_type=Verdict)

    assert error.value.__cause__ is boom


def test_the_sdk_truncation_errors_really_are_outside_apierror() -> None:
    """Pins the classification above to the installed SDK rather than to belief."""
    assert not issubclass(openai.LengthFinishReasonError, openai.APIError)
    assert not issubclass(openai.ContentFilterFinishReasonError, openai.APIError)
    assert issubclass(openai.APITimeoutError, openai.APIError)
    assert issubclass(openai.APIConnectionError, openai.APIError)


# --- the credential never becomes visible -----------------------------------------------------


def test_the_api_key_is_construction_state_and_never_public() -> None:
    instance = provider(RecordingClientFactory())

    assert SECRET not in repr(instance)
    assert SECRET not in str(instance)
    assert not any(SECRET in str(value) for value in vars(instance).values() if value is not SECRET)


def test_the_api_key_reaches_the_client_and_nothing_else() -> None:
    factory = RecordingClientFactory(verdict_response())
    result = runtime_for(factory).execute(request(), output_type=Verdict)

    assert factory.calls[0]["api_key"] == SECRET, "the key must reach the transport"
    assert SECRET not in str(factory.only_parse_call), "but never the request payload"
    assert SECRET not in result.model_dump_json()
    assert SECRET not in str(result.metadata)


@pytest.mark.parametrize(
    "outcome",
    [
        openai.APIConnectionError(message="connection reset", request=None),  # type: ignore[arg-type]
        "refusal",
        "incomplete",
        "missing",
    ],
)
def test_the_api_key_never_reaches_a_failure_message(outcome: Any) -> None:
    responses: dict[str, Any] = {
        "refusal": refusal_response(model=ASTRA),
        "incomplete": FakeResponse(
            model=ASTRA, status="incomplete", incomplete_details=FakeIncompleteDetails(reason="x")
        ),
        "missing": FakeResponse(model=ASTRA, status="completed", output=[]),
    }
    factory = RecordingClientFactory(responses.get(outcome, outcome))
    with pytest.raises(Exception) as error:  # noqa: PT011 - the category varies by outcome
        runtime_for(factory).execute(request(), output_type=Verdict)

    assert SECRET not in str(error.value)
    assert SECRET not in repr(error.value)
