"""Pins of runtime-v4's prompt and exam v5's identity.

Kept apart from the behavioural proofs in ``test_intent_graph_exam_v5.py``: a digest pin fails
on any edit, so inside a mutation slice it would kill every mutant without testing anything.
Here it does its job: a change to the prompt or the exam fails the build until the version and
digest are reviewed on purpose, which changes every certificate that binds them.
"""

from __future__ import annotations

import hashlib

import tests.certification._intent_graph_exam as exam
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
)
from foundry.application import intent_graph_synthesis as orchestrator
from tests.certification._intent_graph_exam import (
    EXPECTED_GRAPH_EXAM_SHA256,
    GRAPH_EXAM_VERSION,
    graph_exam_sha256,
)

V4_SHA = "2c676e555286577284e6d50116b99b43f6527ef1c595b7faa4b84b5929442519"
RUNTIME_V3_PROMPT = "504b6080656253630d1c1e752ed499a23b864cf2ff290ca190941b94db140e5b"
RUNTIME_V4_PROMPT = "fd395605ecd12f39430a9bb0140bf1a3ce6dc43643859e94485a23970856a6e4"
EXAM_V5_SHA = "b8fe070ebddb580721fb4b741d43d3da276b59e40e0ee5840fb13b37ce43a90d"


def test_runtime_v4_identity() -> None:
    assert GRAPH_SYNTHESIS_POLICY_VERSION == "intent-graph-synthesis-runtime-v4"
    assert orchestrator.GRAPH_SYNTHESIS_POLICY_VERSION == GRAPH_SYNTHESIS_POLICY_VERSION
    digest = hashlib.sha256(GRAPH_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == GRAPH_SYSTEM_INSTRUCTION_SHA256 == RUNTIME_V4_PROMPT != RUNTIME_V3_PROMPT


def test_exam_v5_identity() -> None:
    assert GRAPH_EXAM_VERSION == "5"
    assert graph_exam_sha256() == EXPECTED_GRAPH_EXAM_SHA256 == EXAM_V5_SHA != V4_SHA
    assert exam.EXPECTED_GRAPH_POLICY_VERSION == "intent-graph-synthesis-runtime-v4"
    assert exam.GRAPH_EVIDENCE_NAMESPACE == "intent_graph_synthesis_exam_v5"
    assert "intent_graph_synthesis_exam_v4" in exam.HISTORICAL_GRAPH_NAMESPACES
