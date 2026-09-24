"""MR2 — the first real provider behind Foundry's certified Model Runtime.

Everything here is the real thing except the network: a real ``ModelRuntime``, a real
``ModelRegistry``, the real ``XAIModelProvider``, and a double only at the xAI SDK
boundary. Mocking the runtime would prove nothing about the adapter; mocking the adapter
would prove nothing at all.

The laws under test are transport laws, not quality claims. MR2 shows Grok can execute
correctly through the universal socket. It does not show Grok is trustworthy for Intent
Synthesis — that is task-specific evaluation, and it belongs to MR3/MR4.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import Field

from foundry.adapters.model_runtime.xai import XAI_PROVIDER_ID, XAIModelProvider
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
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from tests.unit.adapters.model_runtime._fake_xai import (
    FakeChat,
    FakeResponse,
    RecordingClientFactory,
    sampling_usage,
)

GROK = "grok-4.7"
IDENTITY = ModelIdentity(provider=XAI_PROVIDER_ID, model=GROK)


class Verdict(FrozenModel):
    """A caller-owned output type. The adapter never learns what it means."""

    statement: str = Field(min_length=1)
    score: int


def descriptor(
    *,
    model: str = GROK,
    tasks: frozenset[ModelTask] = frozenset({ModelTask.EVALUATION}),
) -> ModelDescriptor:
    return ModelDescriptor(
        identity=ModelIdentity(provider=XAI_PROVIDER_ID, model=model),
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
        ),
        certified_tasks=tasks,
    )


def request(
    *,
    messages: tuple[ModelMessage, ...] | None = None,
    constraints: ModelExecutionConstraints | None = None,
    task: ModelTask = ModelTask.EVALUATION,
) -> ModelRequest:
    return ModelRequest(
        task=task,
        tier=ModelTier.REASONER,
        messages=messages
        or (
            ModelMessage(role=MessageRole.SYSTEM, content="Follow the caller's policy."),
            ModelMessage(role=MessageRole.USER, content="Assess this."),
        ),
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id="mr2.transport",
        policy_version="v1",
        constraints=constraints or ModelExecutionConstraints(),
        trace=ModelTraceContext(run_id="RUN-1", call_id="CALL-1"),
    )


def chat_returning(
    parsed: object | None = None,
    *,
    model: str = GROK,
    usage: Any = None,
    finish_reason: str | None = "FINISH_REASON_STOP",
    parse_raises: Exception | None = None,
    finish_reason_raises: Exception | None = None,
) -> FakeChat:
    return FakeChat(
        response=FakeResponse(
            model=model,
            usage=usage,
            finish_reason=finish_reason,
            finish_reason_raises=finish_reason_raises,
        ),
        parsed=parsed if parsed is not None else Verdict(statement="sound", score=7),
        parse_raises=parse_raises,
    )


def provider(factory: RecordingClientFactory, **kwargs: Any) -> XAIModelProvider:
    return XAIModelProvider(api_key="sk-test-not-a-real-key", client_factory=factory, **kwargs)


def runtime_for(
    prov: XAIModelProvider, *, model: str = GROK, tasks: frozenset[ModelTask] | None = None
) -> ModelRuntime:
    return ModelRuntime(
        registry=ModelRegistry(
            descriptors=(descriptor(model=model, tasks=tasks or frozenset({ModelTask.EVALUATION})),)
        ),
        providers=(prov,),
    )


# --- identity ---------------------------------------------------------------------------------


def test_the_provider_id_is_pinned() -> None:
    assert XAI_PROVIDER_ID == "xai"
    assert provider(RecordingClientFactory()).provider_id == "xai"


def test_the_adapter_satisfies_the_shared_provider_port() -> None:
    from foundry.model_runtime.ports import ModelProvider

    assert isinstance(provider(RecordingClientFactory()), ModelProvider)


def test_another_providers_identity_is_refused_before_any_network_call() -> None:
    """An xAI adapter must never execute someone else's model."""
    factory = RecordingClientFactory(chat_returning())
    with pytest.raises(ModelRequestError, match="xai"):
        provider(factory).execute(
            model=ModelIdentity(provider="openai", model="gpt-x"),
            request=request(),
            output_type=Verdict,
        )
    assert factory.constructions == []
    assert factory.create_calls == []


def test_the_adapter_is_not_hardcoded_to_one_model() -> None:
    """The registry chooses the model; the adapter executes what it is given."""
    factory = RecordingClientFactory(chat_returning(model="grok-4.6"))
    result = runtime_for(provider(factory), model="grok-4.6").execute(
        request(), output_type=Verdict
    )
    assert factory.create_calls[0]["model"] == "grok-4.6"
    assert result.metadata.identity.model == "grok-4.6"


# --- message fidelity -------------------------------------------------------------------------


def test_every_message_arrives_in_the_same_order_with_the_same_role_and_content() -> None:
    factory = RecordingClientFactory(chat_returning())
    sent = (
        ModelMessage(role=MessageRole.SYSTEM, content="S1"),
        ModelMessage(role=MessageRole.USER, content="U1"),
        ModelMessage(role=MessageRole.ASSISTANT, content="A1"),
        ModelMessage(role=MessageRole.USER, content="U2"),
    )
    runtime_for(provider(factory)).execute(request(messages=sent), output_type=Verdict)

    delivered = factory.create_calls[0]["messages"]
    assert len(delivered) == 4
    roles = [m.role for m in delivered]
    contents = [m.content[0].text for m in delivered]
    assert contents == ["S1", "U1", "A1", "U2"]
    assert roles[0] != roles[1]
    assert roles[1] == roles[3]
    assert len({roles[0], roles[1], roles[2]}) == 3


def test_no_prompt_is_added_rewritten_or_injected() -> None:
    factory = RecordingClientFactory(chat_returning())
    only = (ModelMessage(role=MessageRole.USER, content="exactly this"),)
    runtime_for(provider(factory)).execute(request(messages=only), output_type=Verdict)
    delivered = factory.create_calls[0]["messages"]
    assert len(delivered) == 1
    assert delivered[0].content[0].text == "exactly this"


def test_the_adapter_carries_no_domain_instruction() -> None:
    import pathlib

    source = pathlib.Path("src/foundry/adapters/model_runtime/xai.py").read_text()
    for marker in ("You are", "You must", "Requirement", "SemanticJudgment", "Intent"):
        assert marker not in source, marker


# --- statelessness, retries, tools ------------------------------------------------------------


def test_every_call_is_stateless() -> None:
    """Law 3: no provider conversation memory, ever."""
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    call = factory.create_calls[0]
    assert call["store_messages"] is False
    assert "conversation_id" not in call
    assert "previous_response_id" not in call


def test_grpc_retries_are_disabled_so_one_call_stays_one_attempt() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    options = dict(factory.constructions[0]["channel_options"])
    assert options["grpc.enable_retries"] == 0


def test_no_tool_search_or_multi_agent_option_is_enabled() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    call = factory.create_calls[0]
    for forbidden in (
        "tools",
        "tool_choice",
        "search_parameters",
        "agent_count",
        "parallel_tool_calls",
        "include",
    ):
        assert forbidden not in call, f"{forbidden} was configured"


def test_one_runtime_execution_makes_exactly_one_provider_attempt() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert len(factory.create_calls) == 1
    assert len(factory.clients[0].chats) == 0


# --- reasoning effort -------------------------------------------------------------------------


def test_reasoning_effort_defaults_to_high_and_is_adapter_configuration() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert factory.create_calls[0]["reasoning_effort"] == "high"
    # It is deliberately NOT part of the shared request contract in this slice.
    assert "reasoning_effort" not in ModelRequest.model_fields


def test_reasoning_effort_is_configurable_on_the_adapter() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory, reasoning_effort="low")).execute(request(), output_type=Verdict)
    assert factory.create_calls[0]["reasoning_effort"] == "low"


# --- structured output ------------------------------------------------------------------------


def test_the_callers_type_reaches_the_sdk_parse_mechanism_and_returns_typed() -> None:
    chat = chat_returning(Verdict(statement="sound", score=7))
    factory = RecordingClientFactory(chat)
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)

    assert chat.parse_shapes == [Verdict]
    assert isinstance(result.output, Verdict)
    assert result.output.statement == "sound"
    assert result.output.score == 7


def test_output_that_cannot_satisfy_the_callers_type_is_a_protocol_error() -> None:
    """Never repaired, never coerced, never re-asked."""
    factory = RecordingClientFactory(chat_returning({"statement": "", "score": "seven"}))
    with pytest.raises(ModelProtocolError):
        runtime_for(provider(factory)).execute(request(), output_type=Verdict)


def test_a_parse_failure_inside_the_sdk_surfaces_as_a_protocol_error_with_its_cause() -> None:
    boom = ValueError("model emitted malformed JSON")
    factory = RecordingClientFactory(chat_returning(parse_raises=boom))
    with pytest.raises(ModelProtocolError) as excinfo:
        runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert excinfo.value.__cause__ is boom


# --- provider-reported identity is load-bearing -----------------------------------------------


def test_the_actual_provider_reported_model_is_propagated_not_the_requested_one() -> None:
    factory = RecordingClientFactory(chat_returning(model=GROK))
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert result.metadata.identity == IDENTITY


def test_a_substituted_model_is_rejected_by_the_runtime() -> None:
    """The adapter reports what ran; MR1's certified identity law does the rejecting."""
    factory = RecordingClientFactory(chat_returning(model="grok-3-mini"))
    with pytest.raises(ModelProtocolError, match="grok-3-mini"):
        runtime_for(provider(factory)).execute(request(), output_type=Verdict)


def test_a_response_without_a_reported_model_is_a_protocol_error() -> None:
    """Silence is not permission to assume the requested model ran.

    The message matters as much as the exception type: an operator must be told the
    provider reported no identity, not merely that some contract failed.
    """
    factory = RecordingClientFactory(chat_returning(model=""))
    with pytest.raises(ModelProtocolError, match="reported no executed model identity"):
        runtime_for(provider(factory)).execute(request(), output_type=Verdict)


# --- usage normalization ----------------------------------------------------------------------


def test_reported_telemetry_is_preserved_exactly() -> None:
    factory = RecordingClientFactory(
        chat_returning(
            usage=sampling_usage(
                prompt_tokens=1200, completion_tokens=350, cost_in_usd_ticks=31_000
            )
        )
    )
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    usage = result.metadata.usage
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 350
    assert usage.cost_usd is not None and usage.cost_usd > 0
    assert usage.wall_clock_ms is not None and usage.wall_clock_ms >= 0


def test_unreported_cost_stays_unknown_rather_than_becoming_zero() -> None:
    """A provider that did not report cost did not make a free call."""
    factory = RecordingClientFactory(
        chat_returning(usage=sampling_usage(prompt_tokens=10, completion_tokens=5))
    )
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert result.metadata.usage.cost_usd is None
    assert result.metadata.usage.input_tokens == 10


def test_unreported_token_counts_stay_unknown_rather_than_becoming_zero() -> None:
    """``prompt_tokens`` has no proto presence, so a bare default must not read as data.

    A successful completion never consumes zero prompt tokens; reporting one would inject
    a false measurement into every budget built on this metadata.
    """
    factory = RecordingClientFactory(chat_returning(usage=sampling_usage()))
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert result.metadata.usage.input_tokens is None
    assert result.metadata.usage.output_tokens is None
    assert result.metadata.usage.cost_usd is None


def test_a_genuinely_reported_zero_cost_is_still_preserved() -> None:
    """``cost_in_usd_ticks`` DOES carry presence, so zero there is a real measurement."""
    factory = RecordingClientFactory(
        chat_returning(usage=sampling_usage(prompt_tokens=5, cost_in_usd_ticks=0))
    )
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert result.metadata.usage.cost_usd == 0.0
    assert result.metadata.usage.input_tokens == 5


def test_wall_clock_is_measured_around_the_provider_call() -> None:
    ticks = iter([10.0, 10.75])
    factory = RecordingClientFactory(chat_returning())
    result = runtime_for(provider(factory, monotonic=lambda: next(ticks))).execute(
        request(), output_type=Verdict
    )
    assert result.metadata.usage.wall_clock_ms == 750


# --- finish reason ----------------------------------------------------------------------------


def test_a_reported_finish_reason_is_preserved() -> None:
    factory = RecordingClientFactory(chat_returning(finish_reason="FINISH_REASON_STOP"))
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert result.metadata.finish_reason == "FINISH_REASON_STOP"


def test_an_unavailable_finish_reason_stays_none_rather_than_being_invented() -> None:
    factory = RecordingClientFactory(
        chat_returning(finish_reason_raises=AttributeError("no outputs"))
    )
    result = runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert result.metadata.finish_reason is None


# --- execution constraints are enforced or refused, never ignored -----------------------------


def test_a_supplied_timeout_reaches_the_transport() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(
        request(constraints=ModelExecutionConstraints(timeout_seconds=12.5)),
        output_type=Verdict,
    )
    assert factory.constructions[0]["timeout"] == 12.5


def test_an_absent_timeout_uses_the_adapters_configured_default() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory, default_timeout_seconds=600.0)).execute(
        request(), output_type=Verdict
    )
    assert factory.constructions[0]["timeout"] == 600.0


def test_max_output_tokens_is_mapped_to_the_supported_sdk_field() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(
        request(constraints=ModelExecutionConstraints(max_output_tokens=256)),
        output_type=Verdict,
    )
    assert factory.create_calls[0]["max_tokens"] == 256


def test_an_absent_output_limit_sets_no_token_ceiling() -> None:
    factory = RecordingClientFactory(chat_returning())
    runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert "max_tokens" not in factory.create_calls[0]


def test_a_monetary_ceiling_is_refused_before_the_network_rather_than_pretended() -> None:
    """MR2 has no trusted pre-call cost engine, and will not pretend otherwise."""
    factory = RecordingClientFactory(chat_returning())
    with pytest.raises(ModelRequestError, match="max_cost_usd"):
        runtime_for(provider(factory)).execute(
            request(constraints=ModelExecutionConstraints(max_cost_usd=5.0)),
            output_type=Verdict,
        )
    assert factory.constructions == []
    assert factory.create_calls == []


# --- transport failure and secrets ------------------------------------------------------------


def test_a_transport_failure_becomes_a_provider_error_with_its_cause() -> None:
    boom = RuntimeError("grpc unavailable")
    factory = RecordingClientFactory(raises=boom)
    factory._chats = []  # noqa: SLF001 - deliberate: no chat is scripted

    class Exploding(RecordingClientFactory):
        def __call__(self, **kwargs: Any) -> Any:
            raise boom

    with pytest.raises(ModelProviderError) as excinfo:
        runtime_for(provider(Exploding())).execute(request(), output_type=Verdict)
    assert excinfo.value.__cause__ is boom


def test_a_transport_fault_during_parse_is_not_reported_as_a_schema_failure() -> None:
    """Observed in MR2's first live run: a transient gRPC fault was surfacing as
    "output could not be parsed", which sends an operator hunting a schema bug while the
    network is the real problem. Transport faults must keep their own meaning."""
    import grpc

    class FakeRpcError(grpc.RpcError):
        pass

    boom = FakeRpcError("transient unavailable")
    factory = RecordingClientFactory(chat_returning(parse_raises=boom))
    with pytest.raises(ModelProviderError) as excinfo:
        runtime_for(provider(factory)).execute(request(), output_type=Verdict)
    assert excinfo.value.__cause__ is boom
    assert not isinstance(excinfo.value, ModelProtocolError)


def test_no_credential_appears_in_any_public_contract_or_error_text() -> None:
    secret = "sk-super-secret-value"
    factory = RecordingClientFactory(chat_returning())
    prov = XAIModelProvider(api_key=secret, client_factory=factory)
    result = runtime_for(prov).execute(request(), output_type=Verdict)

    assert secret not in result.model_dump_json()
    assert secret not in repr(prov)
    assert secret not in str(prov)

    boom = RuntimeError("grpc unavailable")

    class Exploding(RecordingClientFactory):
        def __call__(self, **kwargs: Any) -> Any:
            raise boom

    failing = XAIModelProvider(api_key=secret, client_factory=Exploding())
    with pytest.raises(ModelProviderError) as excinfo:
        runtime_for(failing).execute(request(), output_type=Verdict)
    assert secret not in str(excinfo.value)

    # Pre-network refusals must be just as clean: provider mismatch...
    with pytest.raises(ModelRequestError) as mismatch:
        prov.execute(
            model=ModelIdentity(provider="openai", model="gpt-x"),
            request=request(),
            output_type=Verdict,
        )
    assert secret not in str(mismatch.value)

    # ...and an unenforceable constraint.
    with pytest.raises(ModelRequestError) as budget:
        prov.execute(
            model=IDENTITY,
            request=request(constraints=ModelExecutionConstraints(max_cost_usd=1.0)),
            output_type=Verdict,
        )
    assert secret not in str(budget.value)


def test_the_adapter_imports_no_foundry_durable_truth() -> None:
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("src/foundry/adapters/model_runtime/xai.py").read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    banned = {
        "foundry.domain.state",
        "foundry.domain.events",
        "foundry.domain.semantic",
        "foundry.domain.semantic_judgment",
        "foundry.ports.event_store",
        "foundry.ports.intent_synthesizer",
    }
    assert mods & banned == set()
