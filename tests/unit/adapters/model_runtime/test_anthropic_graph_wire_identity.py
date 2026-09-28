"""Pins of the compact Anthropic graph wire's identity.

Kept apart from the behavioural proofs in ``test_anthropic_graph_wire.py`` because a digest pin
fails on *any* edit: inside a mutation slice it would kill every mutant without testing
anything. Here it does its real job: a change to the schema or the converter fails the build
until the representation identity is deliberately reviewed (and its version bumped if the
wire or its meaning changed), which in turn changes every certificate that binds it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from foundry.adapters.intent_graph_synthesis.model_runtime import IntentGraphDraftPayload
from foundry.adapters.model_runtime import anthropic_graph_wire
from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
from foundry.adapters.model_runtime.anthropic_graph_wire import (
    ANTHROPIC_GRAPH_WIRE_REPRESENTATION,
    anthropic_graph_wire_schema,
)
from foundry.adapters.model_runtime.anthropic_wire_schema import ANTHROPIC_WIRE_SCHEMA_COMPILER
from tests.certification._schema_identity import schema_sha256

ANTHROPIC_GRAPH_WIRE_SCHEMA_SHA256 = (
    "885a90ec45a778148254a853fcfabcf0e4e154e9200c68977a2e911790f950cb"
)
CONVERTER_SOURCE_SHA256 = "cdc6fcddd6463a3db82f7ef8f5c95b3d385a09749dd6d39ffa69fada68a01e44"


def test_the_wire_identity_is_pinned() -> None:
    wire = anthropic_graph_wire_schema()
    assert schema_sha256(wire) == ANTHROPIC_GRAPH_WIRE_SCHEMA_SHA256
    assert ANTHROPIC_GRAPH_WIRE_REPRESENTATION == "foundry.anthropic-graph-wire.v2"
    assert ANTHROPIC_WIRE_SCHEMA_COMPILER == "foundry.anthropic-structured-outputs.v3"
    assert AnthropicModelProvider.WIRE_SCHEMA_COMPILER == ANTHROPIC_WIRE_SCHEMA_COMPILER
    assert AnthropicModelProvider.wire_schema(IntentGraphDraftPayload) == wire


def test_the_converter_source_is_pinned_to_its_representation_identity() -> None:
    source = Path(anthropic_graph_wire.__file__).read_bytes()
    assert hashlib.sha256(source).hexdigest() == CONVERTER_SOURCE_SHA256
