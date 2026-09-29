"""Pins of exam v6's identity, and of runtime-v4 staying byte-identical under it.

Kept apart from the behavioural proofs in ``test_intent_graph_exam_v6.py``: a digest pin fails
on any edit, so inside a mutation slice it would kill every mutant without testing anything.
Exam v6 moved because the production root-Intent lifecycle moved (IE3 §17.2); the model-facing
runtime did not, so its policy version, prompt and schemas are pinned unchanged here.
"""

from __future__ import annotations

import hashlib

import tests.certification._intent_graph_exam as exam
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_ANSWER_SCHEMA_SHA256,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
)
from tests.certification._intent_graph_exam import (
    EXPECTED_GRAPH_EXAM_SHA256,
    GRAPH_EXAM_VERSION,
    graph_exam_sha256,
)

EXAM_V5_SHA = "b8fe070ebddb580721fb4b741d43d3da276b59e40e0ee5840fb13b37ce43a90d"
EXAM_V6_SHA = "818f6f87a81a66680625da1563496bf0844efff19b1fe9e6686803aecbd7243c"
RUNTIME_V4_PROMPT = "fd395605ecd12f39430a9bb0140bf1a3ce6dc43643859e94485a23970856a6e4"
CANONICAL_SCHEMA = "6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494"


def test_exam_v6_identity() -> None:
    assert GRAPH_EXAM_VERSION == "6"
    assert graph_exam_sha256() == EXPECTED_GRAPH_EXAM_SHA256 == EXAM_V6_SHA != EXAM_V5_SHA
    assert exam.GRAPH_EVIDENCE_NAMESPACE == "intent_graph_synthesis_exam_v6"
    assert exam.GRAPH_EVIDENCE_NAMESPACE not in exam.HISTORICAL_GRAPH_NAMESPACES


def test_runtime_v4_is_byte_identical_under_exam_v6() -> None:
    assert GRAPH_SYNTHESIS_POLICY_VERSION == exam.EXPECTED_GRAPH_POLICY_VERSION
    assert GRAPH_SYNTHESIS_POLICY_VERSION == "intent-graph-synthesis-runtime-v4"
    digest = hashlib.sha256(GRAPH_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == GRAPH_SYSTEM_INSTRUCTION_SHA256 == RUNTIME_V4_PROMPT
    assert (
        GRAPH_ANSWER_SCHEMA_SHA256 == exam.EXPECTED_GRAPH_ANSWER_SCHEMA_SHA256 == CANONICAL_SCHEMA
    )
