"""IE3 Slice 4.1 — the adapter carries R111 ``unchanged_object_refs`` exactly (offline only)."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_ID,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
    IntentGraphDraftPayload,
)
from foundry.domain.intent_graph import ExistingObjectRef
from tests.unit.adapters.intent_graph_synthesis.test_graph_model_runtime import (
    build,
    draft_gap,
    graph_request,
)

PRIOR_SLICE_4_HASH = "c9fffd33e6cee9f59a5fc5b3d67b0f5253a71ca77e8d554e123b307e1dbc0f9a"


def _refs(*ids: str) -> tuple[ExistingObjectRef, ...]:
    return tuple(ExistingObjectRef(object_id=i) for i in ids)


def test_the_draft_schema_exposes_unchanged_object_refs_as_existing_refs() -> None:
    field = IntentGraphDraftPayload.model_fields["unchanged_object_refs"]
    assert field.annotation == tuple[ExistingObjectRef, ...]
    assert field.default == ()


def test_a_pure_unchanged_draft_maps_through_exactly() -> None:
    synthesizer, provider = build(IntentGraphDraftPayload(unchanged_object_refs=_refs("DEC-1")))
    result = synthesizer.synthesize(graph_request())
    assert provider.calls == 1
    assert result.unchanged_object_refs == _refs("DEC-1")
    assert result.nodes == ()
    assert result.gaps == ()


def test_refs_survive_beside_gaps_in_order() -> None:
    answer = IntentGraphDraftPayload(
        unchanged_object_refs=_refs("INTENT-1", "DEC-1"), gaps=(draft_gap(),)
    )
    synthesizer, _ = build(answer)
    result = synthesizer.synthesize(graph_request())
    assert result.unchanged_object_refs == _refs("INTENT-1", "DEC-1")
    assert result.gaps[0].blocking is True


def test_the_adapter_does_not_dedupe_or_repair_witnesses() -> None:
    synthesizer, _ = build(IntentGraphDraftPayload(unchanged_object_refs=_refs("DEC-1", "DEC-1")))
    with pytest.raises(ValidationError, match="duplicate unchanged"):
        synthesizer.synthesize(graph_request())


def test_an_unchanged_ref_is_only_an_existing_ref() -> None:
    with pytest.raises(ValidationError):
        IntentGraphDraftPayload.model_validate(
            {"unchanged_object_refs": [{"namespace": "local", "local_id": "x"}]}
        )
    with pytest.raises(ValidationError):
        IntentGraphDraftPayload.model_validate({"unchanged_object_refs": ["DEC-1"]})


@pytest.mark.parametrize(
    "field", ["authority", "scope", "blocking", "graph_contract_version", "route", "no_change"]
)
def test_no_additional_runtime_field_is_exposed(field: str) -> None:
    assert field not in IntentGraphDraftPayload.model_fields
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        IntentGraphDraftPayload.model_validate({field: "x", "unchanged_object_refs": []})


def test_the_prompt_makes_unchanged_object_refs_an_executable_contract() -> None:
    text = " ".join(GRAPH_SYSTEM_INSTRUCTION.split())
    assert (
        "If a visible current non-stale object already expresses the intended meaning "
        "adequately: do not create a new node merely to reword it; add that object to "
        "unchanged_object_refs."
    ) in text
    assert (
        'unchanged_object_refs is the explicit way to say "already represented; no change needed".'
    ) in text
    assert "Never place a stale object in unchanged_object_refs." in text
    assert "unchanged_object_refs alone when everything is already represented" in text


def test_the_prompt_hash_moved_with_the_text() -> None:
    """Slice 4.1 kept runtime-v1 (nothing examined yet); runtime-v2 superseded it once the
    first live exam made v1 durable authorship (clarification slice); runtime-v3 superseded v2
    when the node-kind ontology was made model-facing."""
    live = hashlib.sha256(GRAPH_SYSTEM_INSTRUCTION.encode("utf-8")).hexdigest()
    assert live == GRAPH_SYSTEM_INSTRUCTION_SHA256
    assert GRAPH_SYSTEM_INSTRUCTION_SHA256 != PRIOR_SLICE_4_HASH
    assert GRAPH_SYNTHESIS_POLICY_ID == "intent-synthesis.graph-v1"
    assert GRAPH_SYNTHESIS_POLICY_VERSION == "intent-graph-synthesis-runtime-v4"
