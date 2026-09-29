"""The IE3 ``PARALLEL_NODE`` law (``intent_graph_validation._check_parallel_nodes``).

Exactly: one answer, one ``REPLACES_STALE`` node and one ``NEW`` node of the same kind, both
deriving directly (``DERIVED_FROM``) from the same shown claim. Decided on disposition, kind
and edges; no statement is read. Everything else is left to the existing laws.

The recorded Grok exam-v5 case C attempt 1 is the motivating answer. Its NEW node carried no
relation at all, so it did not derive from the claim: the exam refused it as ``NO_RELEVANCE``
and this law, which reads only edges, does not fire on those bytes. Its grounded form (the same
NEW node also deriving from the claim and serving the goal) passed every earlier law and is
exactly what this law refuses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from foundry.application.intent_graph_synthesis_context import (
    IntentGraphResultError,
    validate_graph_result,
)
from foundry.domain.common import Authority, Relation, RelationType
from foundry.domain.intent_graph import IntentGraphSynthesisResult
from foundry.domain.intent_graph_validation import (
    GraphVisibility,
    IntentGraphValidationError,
    VisibleObject,
    validate_intent_graph,
)
from foundry.domain.semantic import SemanticKind
from foundry.ports.intent_graph_synthesizer import IntentGraphSynthesisRequest

CERT = Path(
    "tests/certification/evidence/xai/grok-4.7/intent_graph_synthesis_exam_v5/certification.json"
)
C1, C2 = "CLAIM-1", "CLAIM-2"


def _visibility() -> GraphVisibility:
    return GraphVisibility(
        run_scope="payments",
        objects=(
            VisibleObject(
                object_id="INTENT-payments",
                kind=SemanticKind.INTENT,
                authority=Authority.CANONICAL,
                is_current=True,
                is_stale=False,
                scope=("payments",),
            ),
            VisibleObject(
                object_id="GOAL-refunds",
                kind=SemanticKind.GOAL,
                authority=Authority.CANONICAL,
                is_current=True,
                is_stale=False,
                scope=("payments",),
                relations=(
                    Relation(relation_type=RelationType.SERVES, target_id="INTENT-payments"),
                ),
            ),
            VisibleObject(
                object_id="REQ-old",
                kind=SemanticKind.REQUIREMENT,
                authority=Authority.PROPOSED,
                is_current=True,
                is_stale=True,
                scope=("payments",),
            ),
            VisibleObject(
                object_id="REQ-old-2",
                kind=SemanticKind.REQUIREMENT,
                authority=Authority.PROPOSED,
                is_current=True,
                is_stale=True,
                scope=("payments",),
            ),
        ),
        basis_claim_ids=frozenset({C1, C2}),
        root_intent_ids=("INTENT-payments",),
    )


def _node(local_id: str, kind: str = "REQUIREMENT", replaces: str | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {
        "local_id": {"local_id": local_id},
        "kind": kind,
        "disposition": "REPLACES_STALE" if replaces else "NEW",
        "proposal_rationale": "r",
        "statement": "Refund requests are accepted within fourteen days of purchase.",
    }
    if replaces:
        node["replaces"] = {"namespace": "existing", "object_id": replaces}
    if kind == "CONSTRAINT":
        node["facet"] = "EVIDENCE_BOUND"
    return node


def _wired(local_id: str, claim: str) -> list[dict[str, Any]]:
    return [
        {
            "source": {"local_id": local_id},
            "relation_type": "DERIVED_FROM",
            "target": {"namespace": "basis", "claim_id": claim},
        },
        {
            "source": {"local_id": local_id},
            "relation_type": "SERVES",
            "target": {"namespace": "existing", "object_id": "GOAL-refunds"},
        },
    ]


def _result(
    nodes: list[dict[str, Any]], relations: list[dict[str, Any]]
) -> IntentGraphSynthesisResult:
    return IntentGraphSynthesisResult.model_validate({"nodes": nodes, "relations": relations})


def _validate(nodes: list[dict[str, Any]], relations: list[dict[str, Any]]) -> None:
    validate_intent_graph(_result(nodes, relations), _visibility(), author_is_human=False)


def _code(nodes: list[dict[str, Any]], relations: list[dict[str, Any]]) -> str | None:
    try:
        _validate(nodes, relations)
    except IntentGraphValidationError as exc:
        return exc.code
    return None


REPLACEMENT = _node("req-replaces", replaces="REQ-old")
NEW = _node("req-new")


def test_1_a_replacement_alone_passes() -> None:
    assert _code([REPLACEMENT], _wired("req-replaces", C1)) is None


def test_2_a_new_node_alone_passes() -> None:
    assert _code([NEW], _wired("req-new", C1)) is None


def test_3_replacement_plus_new_of_one_kind_from_one_claim_is_a_parallel_node() -> None:
    with pytest.raises(IntentGraphValidationError) as refused:
        _validate([REPLACEMENT, NEW], _wired("req-replaces", C1) + _wired("req-new", C1))
    assert refused.value.code == "PARALLEL_NODE"
    assert "'req-new' (NEW)" in str(refused.value) and "'req-replaces'" in str(refused.value)
    assert "CLAIM-1" in str(refused.value)


def test_4_the_order_of_the_pair_does_not_matter() -> None:
    first = _node("a-new")
    second = _node("z-replaces", replaces="REQ-old")
    for nodes in ([first, second], [second, first]):
        assert _code(nodes, _wired("a-new", C1) + _wired("z-replaces", C1)) == "PARALLEL_NODE"
    swapped_names = [_node("z-new"), _node("a-replaces", replaces="REQ-old")]
    assert _code(swapped_names, _wired("z-new", C1) + _wired("a-replaces", C1)) == "PARALLEL_NODE"


def test_5_one_claim_may_ground_a_different_kind_beside_a_replacement() -> None:
    constraint = _node("con-new", kind="CONSTRAINT")
    assert (
        _code([REPLACEMENT, constraint], _wired("req-replaces", C1) + _wired("con-new", C1)) is None
    )


def test_6_the_same_kind_from_different_claims_is_not_parallel() -> None:
    assert _code([REPLACEMENT, NEW], _wired("req-replaces", C1) + _wired("req-new", C2)) is None


def test_7_two_new_nodes_are_left_to_the_other_laws() -> None:
    two = [_node("req-a"), _node("req-b")]
    assert _code(two, _wired("req-a", C1) + _wired("req-b", C1)) is None


def test_8_two_replacements_are_left_to_the_replacement_laws() -> None:
    same_target = [_node("req-a", replaces="REQ-old"), _node("req-b", replaces="REQ-old")]
    assert _code(same_target, _wired("req-a", C1) + _wired("req-b", C1)) == "DOUBLE_REPLACEMENT"
    two_targets = [_node("req-a", replaces="REQ-old"), _node("req-b", replaces="REQ-old-2")]
    assert _code(two_targets, _wired("req-a", C1) + _wired("req-b", C1)) is None


def test_a_new_node_deriving_from_the_claim_only_indirectly_is_not_this_law() -> None:
    """Direct DERIVED_FROM edges only: a NEW node derived from the replacement node is a
    different shape (it builds on the replacement) and is left to the other laws."""
    relations = _wired("req-replaces", C1) + [
        {
            "source": {"local_id": "req-new"},
            "relation_type": "DERIVED_FROM",
            "target": {"namespace": "local", "local_id": "req-replaces"},
        },
        {
            "source": {"local_id": "req-new"},
            "relation_type": "SERVES",
            "target": {"namespace": "existing", "object_id": "GOAL-refunds"},
        },
    ]
    assert _code([REPLACEMENT, NEW], relations) != "PARALLEL_NODE"


# ------------------------------------------------------------------ the recorded Grok answer


def _recorded() -> tuple[IntentGraphSynthesisRequest, dict[str, Any]]:
    attempt = json.loads(CERT.read_text())["attempts"][6]
    assert attempt["case"] == "C" and attempt["attempt"] == 1 and attempt["verdict"] == "FAIL"
    request = IntentGraphSynthesisRequest.model_validate_json(attempt["request_json"])
    return request, attempt["result"]


def _refusal(result: dict[str, Any]) -> str:
    request, _ = _recorded()
    with pytest.raises(IntentGraphResultError) as refused:
        validate_graph_result(
            IntentGraphSynthesisResult.model_validate(result), request, author_is_human=False
        )
    cause = refused.value.__cause__
    assert isinstance(cause, IntentGraphValidationError)
    return cause.code


def test_9_the_recorded_c1_bytes_stay_refused_and_are_not_a_parallel_node_by_edges() -> None:
    _, result = _recorded()
    new, replacement = result["nodes"]
    assert (new["disposition"], replacement["disposition"]) == ("NEW", "REPLACES_STALE")
    assert new["kind"] == replacement["kind"] == "REQUIREMENT"
    assert not [
        r for r in result["relations"] if r["source"]["local_id"] == new["local_id"]["local_id"]
    ]
    assert _refusal(result) == "NO_RELEVANCE"


def test_9_the_grounded_c1_shape_is_refused_as_a_parallel_node() -> None:
    """The recorded answer with its NEW node also deriving from the claim and serving the
    goal: every law before this one passes, and the answer is refused as PARALLEL_NODE."""
    _, result = _recorded()
    new_id = result["nodes"][0]["local_id"]["local_id"]
    (claim,) = [
        r["target"]["claim_id"] for r in result["relations"] if r["relation_type"] == "DERIVED_FROM"
    ]
    grounded = {
        **result,
        "relations": [
            *result["relations"],
            {"source": {"local_id": new_id}, "relation_type": "DERIVED_FROM",
             "target": {"namespace": "basis", "claim_id": claim}},
            {"source": {"local_id": new_id}, "relation_type": "SERVES",
             "target": {"namespace": "existing", "object_id": "GOAL-refunds"}},
        ],
    }  # fmt: skip
    assert _refusal(grounded) == "PARALLEL_NODE"
    only_replacement = {
        **result,
        "nodes": result["nodes"][1:],
    }
    request, _ = _recorded()
    validate_graph_result(
        IntentGraphSynthesisResult.model_validate(only_replacement), request, author_is_human=False
    )


def test_12_no_scorer_and_no_wording_decide_it() -> None:
    """Identical statements are not the trigger and different statements do not escape it."""
    other_words = {**NEW, "statement": "Something else entirely."}
    assert (
        _code([REPLACEMENT, other_words], _wired("req-replaces", C1) + _wired("req-new", C1))
        == "PARALLEL_NODE"
    )
    assert _code([REPLACEMENT, NEW], _wired("req-replaces", C1) + _wired("req-new", C2)) is None
