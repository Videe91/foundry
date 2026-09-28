"""Canonical graph answer -> its compact Anthropic wire form. Test-only: the inverse of
``parse_graph_wire``, written independently so round trips test the converter rather than
restate it. Production never needs this direction: Foundry only reads Claude's answers."""

from __future__ import annotations

from typing import Any

from foundry.adapters.intent_graph_synthesis.model_runtime import IntentGraphDraftPayload

_ID = {"local": "local_id", "existing": "object_id", "basis": "claim_id"}


def _ref(ref: dict[str, Any]) -> dict[str, str]:
    return {"namespace": ref["namespace"], "id": ref[_ID[ref["namespace"]]]}


def wire_node(node: dict[str, Any]) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "kind": node["kind"],
        "local_id": node["local_id"]["local_id"],
        "disposition": node["disposition"],
        "replaces": node["replaces"]["object_id"] if node.get("replaces") else "",
        "statement": node.get("statement", ""),
        "mission": node.get("mission", ""),
        "decision_rationale": node.get("decision_rationale", ""),
        "facet": node.get("facet"),
        "proposed_risk_level": node.get("proposed_risk_level"),
        "proposal_rationale": node["proposal_rationale"],
    }
    if node.get("confidence") is not None:
        wire["confidence"] = node["confidence"]
    return wire


def to_wire(value: IntentGraphDraftPayload) -> dict[str, Any]:
    canonical = value.model_dump(mode="json")
    gaps = []
    for gap in canonical["gaps"]:
        wire_gap = {
            "local_gap_id": gap["local_gap_id"],
            "kind": gap["kind"],
            "description": gap["description"],
            "missing_need": gap["missing_need"],
            "anchors": [_ref(anchor) for anchor in gap["anchors"]],
        }
        if gap.get("confidence") is not None:
            wire_gap["confidence"] = gap["confidence"]
        gaps.append(wire_gap)
    return {
        "nodes": [wire_node(node) for node in canonical["nodes"]],
        "relations": [
            {
                "source": relation["source"]["local_id"],
                "relation_type": relation["relation_type"],
                "target": _ref(relation["target"]),
            }
            for relation in canonical["relations"]
        ],
        "gaps": gaps,
        "unchanged_object_refs": [ref["object_id"] for ref in canonical["unchanged_object_refs"]],
    }
