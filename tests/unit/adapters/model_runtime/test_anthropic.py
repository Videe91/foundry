"""The Anthropic adapter behind the shared Model Runtime: offline, against an SDK double.

Covers request construction, exact identity, the frozen graph prompt, the wire schema, parsing,
refusal and truncation, transport failures (timeout, rate limit, overload, authentication),
usage, credential hygiene and certification binding. No test here reaches the network.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import Field

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYSTEM_INSTRUCTION,
    IntentGraphDraftPayload,
    ModelRuntimeIntentGraphSynthesizer,
)
from foundry.adapters.model_runtime.anthropic import (
    ANTHROPIC_PROVIDER_ID,
    AnthropicModelProvider,
)
from foundry.adapters.model_runtime.anthropic_wire_schema import (
    ANTHROPIC_WIRE_SCHEMA_COMPILER,
    anthropic_output_format,
)
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
from foundry.model_runtime.errors import ModelProtocolError, ModelProviderError, ModelRequestError
from foundry.model_runtime.ports import ModelProvider
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from tests.unit.adapters.model_runtime._fake_anthropic import (
    FakeMessage,
    FakeStopDetails,
    FakeText,
    FakeThinking,
    FakeUsage,
    RecordingClientFactory,
    answer,
)

OPUS = "claude-opus-5-5"
SECRET = "sk-ant-test-0000000000000000000000000000"
REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class Verdict(FrozenModel):
    statement: str = Field(min_length=1)
    score: int


def descriptor(model: str = OPUS, task: ModelTask = ModelTask.EVALUATION) -> ModelDescriptor:
    return ModelDescriptor(
        identity=ModelIdentity(provider=ANTHROPIC_PROVIDER_ID, model=model),
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
        ),
        certified_tasks=frozenset({task}),
    )


def request(
    *,
    messages: tuple[ModelMessage, ...] = (
        ModelMessage(role=MessageRole.SYSTEM, content="Be exact."),
        ModelMessage(role=MessageRole.USER, content="Score this."),
    ),
    constraints: ModelExecutionConstraints | None = None,
) -> ModelRequest:
    return ModelRequest(
        task=ModelTask.EVALUATION,
        tier=ModelTier.REASONER,
        messages=messages,
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id="anthropic.transport",
        policy_version="anthropic-v1",
        constraints=constraints or ModelExecutionConstraints(),
        trace=ModelTraceContext(run_id="run-1", call_id="call-1"),
    )


def provider(factory: RecordingClientFactory, **kwargs: Any) -> AnthropicModelProvider:
    return AnthropicModelProvider(api_key=SECRET, effort="max", client_factory=factory, **kwargs)


def runtime(factory: RecordingClientFactory, model: str = OPUS) -> ModelRuntime:
    return ModelRuntime(
        registry=ModelRegistry(descriptors=(descriptor(model),)), providers=(provider(factory),)
    )


def verdict(model: str = OPUS, usage: FakeUsage | None = None) -> FakeMessage:
    return answer(Verdict(statement="ok", score=7).model_dump_json(), model=model, usage=usage)


# --------------------------------------------------------------------------- 1-4 the request


def test_the_adapter_satisfies_the_shared_provider_port() -> None:
    adapter: ModelProvider = provider(RecordingClientFactory())
    assert adapter.provider_id == "anthropic"


def test_1_request_construction_is_exact_and_hides_no_prompt() -> None:
    factory = RecordingClientFactory(verdict())
    runtime(factory).execute(
        request(
            constraints=ModelExecutionConstraints(max_output_tokens=64000, timeout_seconds=600)
        ),
        output_type=Verdict,
    )
    call = factory.only_call
    assert call["system"] == [{"type": "text", "text": "Be exact."}]
    assert call["messages"] == [{"role": "user", "content": "Score this."}]
    assert call["max_tokens"] == 64000 and call["timeout"] == 600
    assert call["output_config"] == {"format": anthropic_output_format(Verdict), "effort": "max"}
    for absent in ("thinking", "tools", "tool_choice", "temperature", "top_p", "fallbacks"):
        assert absent not in call, absent


def test_one_call_is_one_attempt_with_sdk_retries_disabled() -> None:
    factory = RecordingClientFactory(verdict())
    runtime(factory).execute(request(), output_type=Verdict)
    assert factory.calls[0]["max_retries"] == 0
    assert len(factory.stream_calls) == 1


def test_2_the_exact_model_identity_is_sent_and_read_back() -> None:
    factory = RecordingClientFactory(verdict(model="claude-sonnet-5"))
    result = runtime(factory, model="claude-sonnet-5").execute(request(), output_type=Verdict)
    assert factory.only_call["model"] == "claude-sonnet-5"
    assert result.metadata.identity == ModelIdentity(provider="anthropic", model="claude-sonnet-5")


def test_a_late_system_message_is_refused_not_moved() -> None:
    late = (
        ModelMessage(role=MessageRole.USER, content="hi"),
        ModelMessage(role=MessageRole.SYSTEM, content="late"),
    )
    factory = RecordingClientFactory()
    with pytest.raises(ModelRequestError, match="system message after"):
        provider(factory).execute(
            model=ModelIdentity(provider="anthropic", model=OPUS),
            request=request(messages=late),
            output_type=Verdict,
        )
    assert factory.stream_calls == []


def test_another_providers_identity_and_a_cost_budget_are_refused_before_the_network() -> None:
    factory = RecordingClientFactory()
    with pytest.raises(ModelRequestError, match="cannot execute provider"):
        provider(factory).execute(
            model=ModelIdentity(provider="openai", model=OPUS),
            request=request(),
            output_type=Verdict,
        )
    with pytest.raises(ModelRequestError, match="max_cost_usd"):
        provider(factory).execute(
            model=ModelIdentity(provider="anthropic", model=OPUS),
            request=request(constraints=ModelExecutionConstraints(max_cost_usd=1.0)),
            output_type=Verdict,
        )
    assert factory.stream_calls == []


def _graph_request() -> Any:
    from tests.certification.test_intent_graph_exam_harness import _request

    return _request("A")


def test_3_the_graph_task_sends_the_frozen_runtime_v3_prompt_and_4_the_compiled_wire() -> None:
    payload = IntentGraphDraftPayload()
    factory = RecordingClientFactory(answer(payload.model_dump_json(), model=OPUS))
    graph_runtime = ModelRuntime(
        registry=ModelRegistry(descriptors=(descriptor(task=ModelTask.INTENT_GRAPH_SYNTHESIS),)),
        providers=(provider(factory),),
    )
    synthesizer = ModelRuntimeIntentGraphSynthesizer(
        runtime=graph_runtime,
        model_identity=ModelIdentity(provider="anthropic", model=OPUS),
        trace_factory=lambda: ModelTraceContext(run_id="r", call_id="c"),
    )
    # An empty draft may be refused downstream; the outgoing call is what this test inspects.
    with contextlib.suppress(Exception):
        synthesizer.synthesize(_graph_request())
    call = factory.only_call
    assert call["system"] == [{"type": "text", "text": GRAPH_SYSTEM_INSTRUCTION}]
    assert call["output_config"]["format"] == {
        "type": "json_schema",
        "schema": AnthropicModelProvider.wire_schema(IntentGraphDraftPayload),
    }


# --------------------------------------------------------------------------- 5-9 the response


def test_5_6_a_valid_structured_answer_is_parsed_by_the_callers_type() -> None:
    result = runtime(RecordingClientFactory(verdict())).execute(request(), output_type=Verdict)
    assert result.output == Verdict(statement="ok", score=7)


def test_6_a_valid_graph_answer_round_trips() -> None:
    from tests.unit._graph_answer_schema import lawful_payloads
    from tests.unit.adapters.model_runtime._anthropic_graph_forms import to_wire

    value = lawful_payloads()[-1]
    factory = RecordingClientFactory(answer(json.dumps(to_wire(value)), model=OPUS))
    result = provider(factory).execute(
        model=ModelIdentity(provider="anthropic", model=OPUS),
        request=request(),
        output_type=IntentGraphDraftPayload,
    )
    assert result.output == value


@pytest.mark.parametrize(
    "text", ['{"score": 1}', '{"statement": "", "score": 1}', "not json", '{"statement":"x"}']
)
def test_7_output_failing_the_callers_type_is_refused_never_repaired(text: str) -> None:
    factory = RecordingClientFactory(answer(text, model=OPUS))
    with pytest.raises(ModelProtocolError, match="could not be parsed"):
        runtime(factory).execute(request(), output_type=Verdict)


def test_8_a_truncated_response_names_the_output_bound() -> None:
    cut = FakeMessage(model=OPUS, content=[FakeText('{"statement": "o')], stop_reason="max_tokens")
    with pytest.raises(ModelProtocolError, match="max_output_tokens") as error:
        runtime(RecordingClientFactory(cut)).execute(request(), output_type=Verdict)
    from tests.certification._certification_run import (
        HarnessLimitReached,
        classify_execution_failure,
    )

    with pytest.raises(HarnessLimitReached):
        classify_execution_failure(error.value)


def test_9_a_refusal_is_not_a_typed_success_and_leaks_no_prose() -> None:
    refused = FakeMessage(
        model=OPUS,
        content=[FakeText("I won't help with the classified plan BLUEJAY.")],
        stop_reason="refusal",
        stop_details=FakeStopDetails(category="cyber", explanation="BLUEJAY"),
    )
    with pytest.raises(ModelProtocolError, match="refusal") as error:
        runtime(RecordingClientFactory(refused)).execute(request(), output_type=Verdict)
    assert "BLUEJAY" not in str(error.value)
    assert "refusal (category: cyber)" in str(error.value)
    from tests.certification._certification_run import (
        ProtocolTaskFailure,
        classify_execution_failure,
    )

    with pytest.raises(ProtocolTaskFailure):
        classify_execution_failure(error.value)


@pytest.mark.parametrize(
    "shape",
    [
        FakeMessage(model=OPUS, content=[], stop_reason="end_turn"),
        FakeMessage(model=OPUS, content=[FakeThinking()], stop_reason="end_turn"),
        FakeMessage(model=OPUS, content=[FakeText("{}"), FakeText("{}")], stop_reason="end_turn"),
        FakeMessage(model=OPUS, content=[FakeText("{}")], stop_reason="pause_turn"),
        FakeMessage(model=OPUS, content=[FakeText("{}")], stop_reason="tool_use"),
    ],
)
def test_no_answer_or_an_unexpected_stop_fails_closed(shape: FakeMessage) -> None:
    with pytest.raises(ModelProtocolError):
        runtime(RecordingClientFactory(shape)).execute(request(), output_type=Verdict)


def test_two_individually_valid_answers_are_never_resolved_by_picking_one() -> None:
    good = Verdict(statement="ok", score=1).model_dump_json()
    shape = FakeMessage(model=OPUS, content=[FakeText(good), FakeText(good)])
    with pytest.raises(ModelProtocolError, match="2 text blocks"):
        runtime(RecordingClientFactory(shape)).execute(request(), output_type=Verdict)


def test_a_substituted_model_is_rejected_by_the_runtime() -> None:
    factory = RecordingClientFactory(verdict(model="claude-opus-5"))
    with pytest.raises(ModelProtocolError):
        runtime(factory).execute(request(), output_type=Verdict)


# --------------------------------------------------------------------------- 10-12 transport


@pytest.mark.parametrize(
    "boom",
    [
        anthropic.APITimeoutError(request=REQ),
        anthropic.APIConnectionError(request=REQ),
        anthropic.RateLimitError("rate", response=httpx2.Response(429, request=REQ), body=None),
        anthropic.OverloadedError(
            "overloaded", response=httpx2.Response(529, request=REQ), body=None
        ),
        anthropic.AuthenticationError(
            "auth", response=httpx2.Response(401, request=REQ), body=None
        ),
        anthropic.BadRequestError("schema", response=httpx2.Response(400, request=REQ), body=None),
    ],
    ids=["timeout", "connection", "rate-limit", "overloaded", "authentication", "bad-request"],
)
def test_10_11_12_provider_failures_are_transport_not_semantic(boom: BaseException) -> None:
    factory = RecordingClientFactory(boom)
    with pytest.raises(ModelProviderError) as error:
        runtime(factory).execute(request(), output_type=Verdict)
    assert error.value.__cause__ is boom
    from tests.certification._certification_run import TransportFailure, classify_execution_failure

    with pytest.raises(TransportFailure):
        classify_execution_failure(error.value)
    assert len(factory.stream_calls) == 1, "never retried"


# --------------------------------------------------------------------------- 13, 14


def test_13_usage_is_extracted_and_cost_stays_unknown() -> None:
    factory = RecordingClientFactory(
        verdict(usage=FakeUsage(input_tokens=5800, output_tokens=2400))
    )
    result = runtime(factory).execute(request(), output_type=Verdict)
    usage = result.metadata.usage
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (5800, 2400, None)
    assert usage.wall_clock_ms is not None


def test_absent_usage_stays_unknown() -> None:
    result = runtime(RecordingClientFactory(verdict())).execute(request(), output_type=Verdict)
    usage = result.metadata.usage
    assert usage.input_tokens is None or usage.input_tokens == 0
    assert usage.cost_usd is None


def test_14_the_credential_never_leaks() -> None:
    factory = RecordingClientFactory(
        anthropic.AuthenticationError("auth", response=httpx2.Response(401, request=REQ), body=None)
    )
    adapter = provider(factory)
    assert SECRET not in repr(adapter) and SECRET not in str(vars(adapter).get("_effort"))
    with pytest.raises(anthropic.AuthenticationError) as error:
        adapter.execute(
            model=ModelIdentity(provider="anthropic", model=OPUS),
            request=request(),
            output_type=Verdict,
        )
    assert SECRET not in str(error.value)
    assert all(SECRET not in json.dumps(call, default=str) for call in factory.stream_calls)
    assert factory.calls[0]["api_key"] == SECRET, "handed to the transport and nowhere else"


# --------------------------------------------------------------------------- 15, 16 identity


def test_15_the_certification_identity_binds_the_anthropic_wire_and_compiler() -> None:
    from tests.certification._intent_graph_exam import _current_graph_identity
    from tests.certification._schema_identity import schema_sha256

    identity = _current_graph_identity(ModelIdentity(provider="anthropic", model=OPUS))
    assert identity["wire_schema_compiler"] == ANTHROPIC_WIRE_SCHEMA_COMPILER
    assert identity["wire_schema_sha256"] == schema_sha256(
        AnthropicModelProvider.wire_schema(IntentGraphDraftPayload)
    )


def _record(model: str) -> dict[str, Any]:
    from tests.certification._intent_graph_exam import (
        GRAPH_CERTIFICATION_RECORD_FORMAT,
        _current_graph_identity,
    )

    identity = _current_graph_identity(ModelIdentity(provider="anthropic", model=model))
    return {
        "record_format": GRAPH_CERTIFICATION_RECORD_FORMAT,
        "verdict": "PASS",
        "provider": "anthropic",
        "model": model,
        "task": identity["task"].value,
        **{k: v for k, v in identity.items() if k not in ("identity", "task")},
    }


@pytest.mark.parametrize(
    ("certified", "other"),
    [
        ("claude-opus-5-5", "claude-sonnet-5"),
        ("claude-sonnet-5", "claude-fable-5-1"),
        ("claude-fable-5-1", "claude-opus-5-5"),
    ],
)
def test_16_one_claude_certificate_never_binds_another_model_or_provider(
    certified: str, other: str
) -> None:
    from tests.certification._intent_graph_exam import _current_graph_identity, certificate_binds

    record = _record(certified)
    assert certificate_binds(
        record, **_current_graph_identity(ModelIdentity(provider="anthropic", model=certified))
    )
    assert not certificate_binds(
        record, **_current_graph_identity(ModelIdentity(provider="anthropic", model=other))
    )
    for provider_id in ("openai", "xai"):
        assert not certificate_binds(
            record, **_current_graph_identity(ModelIdentity(provider=provider_id, model=certified))
        )
