"""The conflict-naming Call-2 policy ``intent-v2-locus-v7`` at the adapter. No live call.

v7 is ``intent-v2-locus-v6`` with ONE instruction section appended and ONE output field added:
``conflicts``, each naming a proposition of the response and what it conflicts with -- a known
current claim, or another proposition of the same response. A conflict is not a disposition:
every proposition still receives exactly one. The model-facing contract changes, so this is a
new identity; v6 and every earlier identity are byte-for-byte unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    ACCOUNTED_OUTPUT_SCHEMA_SHA256,
    CONFLICT_ACCOUNTED_OUTPUT_SCHEMA_SHA256,
    CONFLICT_POLICY_VERSION,
    CONFLICT_SYSTEM_INSTRUCTION,
    CONFLICT_SYSTEM_INSTRUCTION_SHA256,
    CORRECTION_SET_SYSTEM_INSTRUCTION,
    CORRECTION_SET_SYSTEM_INSTRUCTION_SHA256,
    ConflictAccountedDraftPayload,
    SemanticOutputError,
    XAIConflictSemanticReasoner,
    XAICorrectionSetSemanticReasoner,
    accounted_output_schema_sha256,
    conflict_accounted_output_schema_sha256,
)
from foundry.domain.semantic_holds import PropositionConflict
from tests.unit.test_correction_set_policy import (
    _assert,
    _reasoner,
    _reply,
    _request,
    _sup,
    _Transport,
    transport,  # noqa: F401 - the fixture
)


def _conflict_reply(drafts: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> str:
    body = json.loads(_reply(drafts))
    body["conflicts"] = conflicts
    return json.dumps(body)


def test_v7_is_a_new_identity_and_v6_is_unchanged() -> None:
    assert CONFLICT_POLICY_VERSION == "intent-v2-locus-v7"
    assert XAIConflictSemanticReasoner.policy_version == CONFLICT_POLICY_VERSION
    assert CONFLICT_SYSTEM_INSTRUCTION.startswith(CORRECTION_SET_SYSTEM_INSTRUCTION + "\n")
    digest = hashlib.sha256(CONFLICT_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == CONFLICT_SYSTEM_INSTRUCTION_SHA256
    assert hashlib.sha256(CORRECTION_SET_SYSTEM_INSTRUCTION.encode()).hexdigest() == (
        CORRECTION_SET_SYSTEM_INSTRUCTION_SHA256
    )
    assert CORRECTION_SET_SYSTEM_INSTRUCTION_SHA256 == (
        "13aa87743ed7a3f3ca8620d1ceec914a26bcf916196cd592b2aa713b34af5190"
    )
    assert accounted_output_schema_sha256() == ACCOUNTED_OUTPUT_SCHEMA_SHA256
    assert conflict_accounted_output_schema_sha256() == CONFLICT_ACCOUNTED_OUTPUT_SCHEMA_SHA256
    assert CONFLICT_ACCOUNTED_OUTPUT_SCHEMA_SHA256 != ACCOUNTED_OUTPUT_SCHEMA_SHA256
    assert XAICorrectionSetSemanticReasoner.draft_payload.__name__ == "AccountedDraftPayload"
    assert XAIConflictSemanticReasoner.draft_payload is ConflictAccountedDraftPayload
    assert XAIConflictSemanticReasoner.correction_law == "TARGET_SET"


def test_the_v7_prompt_names_both_conflict_targets_and_keeps_one_disposition() -> None:
    text = " ".join(CONFLICT_SYSTEM_INSTRUCTION.split())
    for phrase in ("CONFLICTS", "conflicts_with_claim_id", "conflicts_with_proposition_id",
                   "never decide which", "not a disposition"):  # fmt: skip
        assert phrase in text, phrase


def test_v7_reports_conflicts_with_a_current_claim_and_with_a_sibling(
    transport: _Transport,  # noqa: F811
) -> None:
    transport.replies.append(
        _conflict_reply(
            [_assert("P1", "five seconds"), _assert("P2", "never varies")],
            [
                {"proposition_id": "P1", "conflicts_with_claim_id": "C-2S", "rationale": "r"},
                {"proposition_id": "P2", "conflicts_with_proposition_id": "P1", "rationale": "r"},
            ],
        )
    )
    proposal = _reasoner(XAIConflictSemanticReasoner).propose_accounted(_request())
    assert proposal.conflicts == (
        PropositionConflict(proposition_id="P1", with_claim_id="C-2S"),
        PropositionConflict(proposition_id="P2", with_proposition_id="P1"),
    )
    assert len(proposal.judgments) == 2, "a conflict is not a judgment"


def test_without_conflicts_v7_proposes_exactly_what_v6_proposes(
    transport: _Transport,  # noqa: F811
) -> None:
    drafts = [_assert("P1", "a"), _sup("P1", "J-2S"), _assert("P2", "b")]
    transport.replies.append(_reply(drafts))
    six = _reasoner().propose_accounted(_request())
    transport.replies.append(_conflict_reply(drafts, []))
    seven = _reasoner(XAIConflictSemanticReasoner).propose_accounted(_request())
    assert [j.proposal for j in six.judgments] == [j.proposal for j in seven.judgments]
    assert seven.conflicts == ()


@pytest.mark.parametrize(
    "conflict",
    [
        {"proposition_id": "P9", "conflicts_with_claim_id": "C-2S"},
        {"proposition_id": "P1", "conflicts_with_claim_id": "C-GHOST"},
        {"proposition_id": "P1", "conflicts_with_proposition_id": "P9"},
        {"proposition_id": "P1", "conflicts_with_proposition_id": "P1"},
        {"proposition_id": "P1"},
        {"proposition_id": "P1", "conflicts_with_claim_id": "C-2S",
         "conflicts_with_proposition_id": "P2"},
    ],
    ids=["unknown-proposition", "unknown-claim", "unknown-sibling", "self", "no-target",
         "two-targets"],
)  # fmt: skip
def test_a_malformed_conflict_refuses_the_whole_response(
    transport: _Transport,  # noqa: F811
    conflict: dict[str, Any],
) -> None:
    transport.replies.append(
        _conflict_reply([_assert("P1", "a"), _assert("P2", "b")], [{**conflict, "rationale": "r"}])
    )
    with pytest.raises(SemanticOutputError):
        _reasoner(XAIConflictSemanticReasoner).propose_accounted(_request())


def test_a_response_naming_conflicts_cannot_bypass_the_verified_pipeline(
    transport: _Transport,  # noqa: F811
) -> None:
    transport.replies.append(
        _conflict_reply(
            [_assert("P1", "a"), _assert("P2", "b")],
            [{"proposition_id": "P1", "conflicts_with_claim_id": "C-2S", "rationale": "r"}],
        )
    )
    with pytest.raises(SemanticOutputError):
        _reasoner(XAIConflictSemanticReasoner).propose(_request())
