"""Pins of exam v2's identity, of the verifier contract it certifies, and of exam v1 unchanged.

Kept apart from the behavioural proofs: a digest pin fails on any edit, so inside a mutation
slice it would kill every mutant without testing anything. Every value here is a full hash
recomputed from source and pasted; none is copied from a report.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_SYSTEM_INSTRUCTION,
    COMPLETENESS_SYSTEM_INSTRUCTION_SHA256,
)
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    CompletenessReport,
)
from tests.certification._completeness_exam import (
    COMPLETENESS_SEAL_PATH,
    EXPECTED_COMPLETENESS_EXAM_SHA256,
    EXPECTED_INSTRUCTION_SHA256,
    EXPECTED_OPENAI_WIRE_SCHEMA_COMPILER,
    EXPECTED_OPENAI_WIRE_SCHEMA_SHA256,
    EXPECTED_REPORT_SCHEMA_SHA256,
    EXPECTED_VERIFIER_POLICY_ID,
    EXPECTED_VERIFIER_POLICY_VERSION,
    completeness_exam_sha256,
    completeness_seal_problems,
)
from tests.certification._schema_identity import schema_sha256

EXAM_V2_SHA = "c6f9ca5bfc8e4c8f4705bc49ab7c7c65477bda933920b5b6a817a80a7502338d"
INSTRUCTION = "56b753a9156883264f9bdd070f9b5b63facb653c68bdb5fbcd0c0322814a0d7c"
CANONICAL_REPORT_SCHEMA = "3686a0fc213df48aa87f22a89c7f76be12ceec34cf95728360c39fe29f4e466d"
OPENAI_WIRE_SCHEMA = "cc39ac457748f60136a6f853a924a45041030763f79d7193a3964785e71bd6de"
EXAM_V1_SHA = "8eb4ea4ec254f5b4cdb3c164c94276fbd1efbe67989b3f2ad03088a0f5e4dad5"
EXAM_V1_SOURCE = "dbdc4b4ec0aeee0990a224e18bb895a284efe3064b1313436fe1355e3ba9f809"


def test_exam_v2_identity() -> None:
    assert completeness_exam_sha256() == EXPECTED_COMPLETENESS_EXAM_SHA256 == EXAM_V2_SHA
    assert EXAM_V2_SHA != EXAM_V1_SHA


def test_the_certified_verifier_contract_is_pinned() -> None:
    assert SEMANTIC_COMPLETENESS_POLICY_VERSION == EXPECTED_VERIFIER_POLICY_VERSION
    assert EXPECTED_VERIFIER_POLICY_VERSION == "ie2-semantic-completeness-v1"
    assert COMPLETENESS_POLICY_ID == EXPECTED_VERIFIER_POLICY_ID == "ie2-semantic-completeness"
    digest = hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == COMPLETENESS_SYSTEM_INSTRUCTION_SHA256 == EXPECTED_INSTRUCTION_SHA256
    assert digest == INSTRUCTION
    canonical = schema_sha256(CompletenessReport.model_json_schema())
    assert canonical == EXPECTED_REPORT_SCHEMA_SHA256 == CANONICAL_REPORT_SCHEMA
    wire = schema_sha256(OpenAIModelProvider.wire_schema(CompletenessReport))
    assert wire == EXPECTED_OPENAI_WIRE_SCHEMA_SHA256 == OPENAI_WIRE_SCHEMA
    assert OpenAIModelProvider.WIRE_SCHEMA_COMPILER == EXPECTED_OPENAI_WIRE_SCHEMA_COMPILER
    assert EXPECTED_OPENAI_WIRE_SCHEMA_COMPILER == "foundry.openai-structured-outputs.v1"


def test_exam_v1_is_historical_and_byte_identical() -> None:
    from foundry.experiments.completeness_verifier_exam import exam as v1

    source = Path("src/foundry/experiments/completeness_verifier_exam/exam.py").read_bytes()
    assert hashlib.sha256(source).hexdigest() == EXAM_V1_SOURCE
    assert v1.exam_sha256() == EXAM_V1_SHA
    assert v1.EXAM_VERSION == "ie2-semantic-completeness-exam-v1"


def test_a_committed_seal_is_exactly_the_current_exam() -> None:
    if COMPLETENESS_SEAL_PATH.exists():
        assert completeness_seal_problems() == ()
