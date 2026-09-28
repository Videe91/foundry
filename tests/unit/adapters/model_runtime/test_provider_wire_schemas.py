"""Each provider publishes the wire schema it actually transmits, and the paths stay independent.

xAI receives the canonical answer schema unchanged (proven here through the real ``xai_sdk``
request builder, offline). OpenAI receives its compiled wire schema (proven through the real
adapter with the SDK double). Neither provider's representation leaks into the other's path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from xai_sdk.chat import user
from xai_sdk.sync.chat import Chat

import tests.unit._graph_answer_schema as g
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    IntentGraphDraftPayload,
)
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.model_runtime.openai_wire_schema import compile_openai_wire_schema
from foundry.adapters.model_runtime.xai import XAIModelProvider
from foundry.model_runtime.domain import (
    MessageRole,
    ModelCapability,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from tests.certification._schema_identity import schema_sha256
from tests.unit.adapters.model_runtime._fake_openai import (
    FakeMessage,
    FakeOutputText,
    FakeResponse,
    RecordingClientFactory,
)

SRC = Path(__file__).resolve().parents[4] / "src" / "foundry"


class _Captured(Exception):
    pass


class _CapturingStub:
    request: Any = None

    def GetCompletion(self, request: Any) -> Any:  # noqa: N802 - the gRPC method name
        self.request = request
        raise _Captured


def test_xai_transmits_the_canonical_schema_unchanged() -> None:
    stub = _CapturingStub()
    with pytest.raises(_Captured):
        Chat(stub, None, None, model="grok-4.7", messages=[user("hi")]).parse(
            IntentGraphDraftPayload
        )
    sent = stub.request.response_format.schema
    assert sent == json.dumps(IntentGraphDraftPayload.model_json_schema())
    assert json.loads(sent) == XAIModelProvider.wire_schema(IntentGraphDraftPayload)
    assert schema_sha256(json.loads(sent)) == GRAPH_ANSWER_SCHEMA_SHA256


def test_the_two_providers_publish_different_wire_identities() -> None:
    xai = XAIModelProvider.wire_schema(IntentGraphDraftPayload)
    openai = OpenAIModelProvider.wire_schema(IntentGraphDraftPayload)
    assert schema_sha256(xai) == GRAPH_ANSWER_SCHEMA_SHA256
    assert schema_sha256(openai) != schema_sha256(xai)
    assert XAIModelProvider.WIRE_SCHEMA_COMPILER != OpenAIModelProvider.WIRE_SCHEMA_COMPILER


def test_xai_never_receives_the_openai_compiled_schema() -> None:
    source = (SRC / "adapters" / "model_runtime" / "xai.py").read_text()
    assert "openai" not in source.lower().replace("openai's", "")
    assert XAIModelProvider.wire_schema(IntentGraphDraftPayload) != compile_openai_wire_schema(
        IntentGraphDraftPayload.model_json_schema()
    )


def test_no_domain_or_application_module_knows_a_provider_wire_form() -> None:
    for layer in ("domain", "application", "ports"):
        for path in (SRC / layer).rglob("*.py"):
            text = path.read_text()
            assert "openai_wire_schema" not in text, path
            assert "anthropic_wire_schema" not in text, path
            for sdk in ("openai", "anthropic", "xai_sdk"):
                assert f"import {sdk}" not in text and f"from {sdk}" not in text, path


def test_each_adapter_imports_only_its_own_sdk_and_compiler() -> None:
    adapters = SRC / "adapters" / "model_runtime"
    anthropic_source = (adapters / "anthropic.py").read_text()
    for foreign in ("openai", "xai_sdk", "openai_wire_schema"):
        assert f"import {foreign}" not in anthropic_source
        assert f"from {foreign}" not in anthropic_source
        assert f"model_runtime.{foreign}" not in anthropic_source
    for other in ("openai.py", "xai.py", "openai_wire_schema.py"):
        assert "anthropic" not in (adapters / other).read_text().lower(), other


def _graph_request() -> ModelRequest:
    return ModelRequest(
        task=ModelTask.INTENT_GRAPH_SYNTHESIS,
        tier=ModelTier.REASONER,
        messages=(ModelMessage(role=MessageRole.USER, content="graph"),),
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id="probe",
        policy_version="probe-v1",
        constraints=ModelExecutionConstraints(),
        trace=ModelTraceContext(run_id="run-1", call_id="call-1"),
    )


@pytest.mark.parametrize("value", g.lawful_payloads()[::9], ids=lambda _: "")
def test_openai_sends_the_compiled_graph_wire_and_returns_the_same_value(
    value: IntentGraphDraftPayload,
) -> None:
    answer = FakeResponse(
        model="gpt-6-astra",
        status="completed",
        output=[FakeMessage(content=[FakeOutputText(text=json.dumps(g.explicit(value)))])],
    )
    factory = RecordingClientFactory(answer)
    provider = OpenAIModelProvider(api_key="sk-test", client_factory=factory)
    result = provider.execute(
        model=ModelIdentity(provider="openai", model="gpt-6-astra"),
        request=_graph_request(),
        output_type=IntentGraphDraftPayload,
    )
    sent = factory.only_parse_call["text"]["format"]
    assert sent["schema"] == OpenAIModelProvider.wire_schema(IntentGraphDraftPayload)
    assert sent["strict"] is True and sent["name"] == "IntentGraphDraftPayload"
    assert result.output == value
