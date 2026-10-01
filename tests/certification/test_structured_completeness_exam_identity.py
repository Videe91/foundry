"""Pins of the structured exam's identity and of the structured verifier contract it certifies.

Kept apart from the behavioural proofs: a digest pin fails on any edit, so inside a mutation
slice it would kill every mutant without testing anything.
"""

from __future__ import annotations

import hashlib

from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_V2_CONTRACT,
    STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION,
)
from foundry.domain.semantic_completeness import StructuredCompletenessReport
from tests.certification._schema_identity import schema_sha256
from tests.certification._structured_completeness_exam import (
    EXPECTED_EXAM_SHA256,
    STRUCTURED_SEAL_PATH,
    structured_exam_sha256,
    structured_seal_problems,
)

EXAM_SHA = "0998671b7c742642a2ddef71b76b1d3a6e8798dc604375d7d1fb999c8332e8d1"
INSTRUCTION = "07296c5ec2b1f2fee616b3e3a80c762b5882e78c3cd223eba899b1fd74739710"


def test_the_structured_exam_identity() -> None:
    assert structured_exam_sha256() == EXPECTED_EXAM_SHA256 == EXAM_SHA


def test_the_structured_verifier_contract_is_pinned() -> None:
    digest = hashlib.sha256(STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == COMPLETENESS_V2_CONTRACT.instruction_sha256 == INSTRUCTION
    canonical = schema_sha256(StructuredCompletenessReport.model_json_schema())
    assert canonical == COMPLETENESS_V2_CONTRACT.output_schema_sha256
    assert COMPLETENESS_V2_CONTRACT.policy_version == "ie2-semantic-completeness-v2"
    assert OpenAIModelProvider.wire_schema(StructuredCompletenessReport)


def test_a_committed_seal_is_exactly_the_current_exam() -> None:
    if STRUCTURED_SEAL_PATH.exists():
        assert structured_seal_problems() == ()
