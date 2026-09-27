"""OpenAI Structured Outputs compatibility probe for the IE3 graph-answer wire schema.

SCHEMA TRANSPORT COMPATIBILITY, not model certification. It asks only whether OpenAI accepts the
compiled wire schema (no ``oneOf``; nested ``anyOf``; retained ``discriminator`` metadata) and
whether one structured answer travels through the real adapter and passes Pydantic. It never
touches the certification registry, the graph exam, its scorers or any verdict; a schema or API
rejection here is an infrastructure result, never a semantic judgement of any model.

Two calls, and no more:

1. **Acceptance.** One lawful graph answer through ``OpenAIModelProvider.execute``.
2. **Regex boundary.** Pydantic refuses a ``local_id`` ending in a newline; JSON Schema's ECMA
   ``$`` does too; whether OpenAI's ``pattern`` implementation does cannot be proven offline.
   The model is asked for exactly such a value. A trailing newline that comes back (and is
   refused by Pydantic in the adapter) is a wire-soundness counterexample. Anything else is
   "no counterexample observed", which is evidence, not proof.

Opt-in twice: ``OPENAI_API_KEY`` and ``RUN_LIVE_OPENAI_SCHEMA_PROBE=1``. Neither the default suite
nor the certification flag runs it. Evidence is written to
``tests/certification/evidence/_compatibility/openai/schema_probe.json``, outside every model's
certification namespace.
"""

from __future__ import annotations

import json
import os
from typing import Any

import openai
import pytest

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    IntentGraphDraftPayload,
)
from foundry.adapters.model_runtime.openai import OPENAI_PROVIDER_ID, OpenAIModelProvider
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
from foundry.model_runtime.errors import ModelProtocolError
from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._schema_identity import schema_sha256

ASTRA = ModelIdentity(provider=OPENAI_PROVIDER_ID, model="gpt-6-astra")
PROBE_PATH = EVIDENCE_ROOT / "_compatibility" / "openai" / "schema_probe.json"

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_API_KEY") and os.environ.get("RUN_LIVE_OPENAI_SCHEMA_PROBE") == "1"
    ),
    reason=(
        "LIVE_OPENAI_SCHEMA_PROBE_NOT_ENABLED: set OPENAI_API_KEY and "
        "RUN_LIVE_OPENAI_SCHEMA_PROBE=1 to probe schema compatibility"
    ),
)

RESULTS: dict[str, Any] = {}


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node).union(*(_keys(v) for v in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(_keys(v) for v in node)) if node else set()
    return set()


def _request(call_id: str, instruction: str) -> ModelRequest:
    return ModelRequest(
        task=ModelTask.INTENT_GRAPH_SYNTHESIS,
        tier=ModelTier.REASONER,
        messages=(
            ModelMessage(
                role=MessageRole.SYSTEM,
                content=(
                    "This is a structured-output transport probe. Return exactly the graph "
                    "answer described by the user, in the required schema."
                ),
            ),
            ModelMessage(role=MessageRole.USER, content=instruction),
        ),
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id="schema-compatibility-probe",
        policy_version="schema-compatibility-probe-v1",
        constraints=ModelExecutionConstraints(max_output_tokens=16000, timeout_seconds=180.0),
        trace=ModelTraceContext(run_id="openai-schema-probe", call_id=call_id),
    )


def _provider() -> OpenAIModelProvider:
    return OpenAIModelProvider(
        api_key=os.environ["OPENAI_API_KEY"], reasoning_effort="high", reasoning_mode="standard"
    )


def _outcome(call_id: str, instruction: str) -> dict[str, Any]:
    try:
        result = _provider().execute(
            model=ASTRA, request=_request(call_id, instruction), output_type=IntentGraphDraftPayload
        )
    except openai.APIError as exc:
        return {"outcome": "API_REJECTED", "error": f"{type(exc).__name__}: {exc}"}
    except ModelProtocolError as exc:
        cause = exc.__cause__
        return {
            "outcome": "PYDANTIC_REFUSED_ANSWER",
            "error": str(exc),
            "cause": f"{type(cause).__name__}: {cause}" if cause is not None else None,
        }
    return {
        "outcome": "ACCEPTED_AND_VALIDATED",
        "executed_model": result.identity.model,
        "answer": result.output.model_dump(mode="json"),
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
    }


def test_1_openai_accepts_the_compiled_graph_wire_schema() -> None:
    wire = OpenAIModelProvider.wire_schema(IntentGraphDraftPayload)
    RESULTS["schema"] = {
        "canonical_schema_sha256": GRAPH_ANSWER_SCHEMA_SHA256,
        "wire_schema_sha256": schema_sha256(wire),
        "wire_schema_compiler": OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
        "contains_oneOf": "oneOf" in _keys(wire),
        "contains_anyOf": "anyOf" in _keys(wire),
        "contains_discriminator": "discriminator" in _keys(wire),
        "nested_anyOf_defs": sorted(name for name, d in wire["$defs"].items() if "anyOf" in d),
    }
    RESULTS["acceptance"] = _outcome(
        "acceptance",
        'Return exactly one node: an INTENT with local_id "probe-root", mission "Probe the '
        'structured output contract.", proposal_rationale "Compatibility probe.", disposition '
        "NEW, replaces null and confidence null. Return no relations, no gaps and no "
        "unchanged_object_refs.",
    )
    assert RESULTS["acceptance"]["outcome"] == "ACCEPTED_AND_VALIDATED", RESULTS["acceptance"]


def test_2_the_local_id_pattern_boundary() -> None:
    RESULTS["trailing_newline"] = _outcome(
        "trailing-newline",
        "Return exactly one INTENT node whose local_id is the letter a followed by a single "
        'newline character (the JSON string "a\\n"), mission "Probe.", proposal_rationale '
        '"Probe.", disposition NEW, replaces null, confidence null. No relations, gaps or '
        "unchanged_object_refs.",
    )
    outcome = RESULTS["trailing_newline"]
    assert outcome["outcome"] != "PYDANTIC_REFUSED_ANSWER", (
        "WIRE SOUNDNESS COUNTEREXAMPLE: OpenAI's wire admitted a value Pydantic refuses"
    )


def test_zz_record_the_probe() -> None:
    PROBE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROBE_PATH.write_text(
        json.dumps(
            {
                "kind": "SCHEMA_TRANSPORT_COMPATIBILITY_PROBE (not a model certification)",
                "provider": ASTRA.provider,
                "model": ASTRA.model,
                "reasoning_effort": "high",
                "reasoning_mode": "standard",
                **RESULTS,
            },
            indent=2,
            sort_keys=True,
        )
    )
