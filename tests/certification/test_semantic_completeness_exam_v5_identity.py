"""Pins of exam v5's identity, of the unchanged verifier contract it certifies, and of exams v2,
v3 and v4 unchanged.

Kept apart from the behavioural proofs: a digest pin fails on any edit, so inside a mutation
slice it would kill every mutant without testing anything. Every value here is a full hash
recomputed from source and pasted; none is copied from a report.
"""

from __future__ import annotations

import hashlib

from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_SYSTEM_INSTRUCTION,
)
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    CompletenessReport,
)
from tests.certification._completeness_exam import (
    completeness_exam_sha256 as v2_exam_sha256,
)
from tests.certification._completeness_exam_v3 import (
    completeness_exam_sha256 as v3_exam_sha256,
)
from tests.certification._completeness_exam_v4 import (
    completeness_exam_sha256 as v4_exam_sha256,
)
from tests.certification._completeness_exam_v5 import (
    COMPLETENESS_SEAL_PATH,
    EXPECTED_COMPLETENESS_EXAM_SHA256,
    completeness_exam_sha256,
    completeness_seal_problems,
)
from tests.certification._schema_identity import schema_sha256

EXAM_V5_SHA = "88b69c45dd7f508c4068f753b3942febe2d39f4548fc1e30995dfbb8cd9ed99a"
EXAM_V4_SHA = "415f142fdea1e1c64fc1b937155f244909abcda6d5f0992ea03856e0781a176f"
EXAM_V3_SHA = "267cfadf1303c43252439b34ed14366cb94467080e5c3256ac8db729d3becb65"
EXAM_V2_SHA = "c6f9ca5bfc8e4c8f4705bc49ab7c7c65477bda933920b5b6a817a80a7502338d"
INSTRUCTION = "56b753a9156883264f9bdd070f9b5b63facb653c68bdb5fbcd0c0322814a0d7c"
CANONICAL_REPORT_SCHEMA = "3686a0fc213df48aa87f22a89c7f76be12ceec34cf95728360c39fe29f4e466d"
OPENAI_WIRE_SCHEMA = "cc39ac457748f60136a6f853a924a45041030763f79d7193a3964785e71bd6de"


def test_exam_v5_identity() -> None:
    assert completeness_exam_sha256() == EXPECTED_COMPLETENESS_EXAM_SHA256 == EXAM_V5_SHA
    assert EXAM_V5_SHA not in (EXAM_V4_SHA, EXAM_V3_SHA, EXAM_V2_SHA)


def test_exams_v2_v3_and_v4_are_unchanged() -> None:
    assert v2_exam_sha256() == EXAM_V2_SHA
    assert v3_exam_sha256() == EXAM_V3_SHA
    assert v4_exam_sha256() == EXAM_V4_SHA


def test_the_verifier_contract_v3_certifies_is_unchanged() -> None:
    assert SEMANTIC_COMPLETENESS_POLICY_VERSION == "ie2-semantic-completeness-v1"
    assert COMPLETENESS_POLICY_ID == "ie2-semantic-completeness"
    assert hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest() == INSTRUCTION
    assert schema_sha256(CompletenessReport.model_json_schema()) == CANONICAL_REPORT_SCHEMA
    assert schema_sha256(OpenAIModelProvider.wire_schema(CompletenessReport)) == OPENAI_WIRE_SCHEMA
    assert OpenAIModelProvider.WIRE_SCHEMA_COMPILER == "foundry.openai-structured-outputs.v1"


def test_a_committed_seal_is_exactly_the_current_exam() -> None:
    if COMPLETENESS_SEAL_PATH.exists():
        assert completeness_seal_problems() == ()
