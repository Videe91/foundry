"""Task 9P-5: xAI lifecycle drafts — BIND_TO_ADDRESS, SUPPORTS_CLAIM, SUPERSEDE.

Every test here runs against a FAKE xAI transport. ZERO live calls. The load-bearing
property is the reference law (9P Global Constraint 3): every id a draft references must
already exist in the ``ReasoningRequest``. A claim asserted in the same response has no
durable id and can be referenced by nothing. The correction pattern (9P-A) is therefore
``ASSERT_CLAIM(new, at known address)`` + ``SUPERSEDE(old claim's known judgment id)`` in
one response, neither draft referencing the other.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.adapters.semantics.xai_reasoner import (
    POLICY_VERSION,
    AssertClaimDraft,
    BindToAddressDraft,
    ClaimValueDraft,
    ConflictsWithDraft,
    CreateAddressDraft,
    DistinctDraft,
    EquivalentDraft,
    SemanticDraftPayload,
    SemanticOutputError,
    SupersedeDraft,
    SupportsClaimDraft,
    XAISemanticReasoner,
)
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticAddress,
    SemanticClaim,
)
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    JudgmentKind,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

PROJECT = "PROJ-9P-TEST"
SECRET = "test-secret-xai-key-000"
T0 = datetime(2026, 9, 11, tzinfo=UTC)


# --------------------------------------------------------------------------- guards


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any accidental socket use in this module is a test failure, not a slow test."""

    def blocked(*_: Any, **__: Any) -> None:
        raise AssertionError("a 9P lifecycle-draft unit test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield


# --------------------------------------------------------------------------- transport


class FakeHarness:
    """Records how the adapter drives the xAI SDK; never touches the network."""

    def __init__(self) -> None:
        self.client_inits: list[dict[str, Any]] = []
        self.create_kwargs: list[dict[str, Any]] = []
        self.chats: list[Any] = []
        self.payload: SemanticDraftPayload = SemanticDraftPayload(drafts=())
        self.usage: object | None = SimpleNamespace(prompt_tokens=120, completion_tokens=40)
        self.cost_usd: float | None = 0.0042
        self.parse_error: BaseException | None = None
        self.last_shape: object | None = None
        self.client_cls = self._client_type()

    def _client_type(self) -> type[object]:
        harness = self

        class FakeChat:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                self.messages: list[object] = []

            def append(self, message: object) -> FakeChat:
                self.messages.append(message)
                return self

            def parse(self, shape: object) -> tuple[object, SemanticDraftPayload]:
                harness.last_shape = shape
                if harness.parse_error is not None:
                    raise harness.parse_error
                response = SimpleNamespace(usage=harness.usage, cost_usd=harness.cost_usd)
                return response, harness.payload

        class FakeChatNamespace:
            def create(self, **kwargs: object) -> FakeChat:
                harness.create_kwargs.append(dict(kwargs))
                chat = FakeChat(**kwargs)
                harness.chats.append(chat)
                return chat

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                harness.client_inits.append(dict(kwargs))
                self.chat = FakeChatNamespace()

        return FakeClient


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> FakeHarness:
    from foundry.adapters.semantics import xai_reasoner as mod

    fake = FakeHarness()
    monkeypatch.setattr(mod, "Client", fake.client_cls)
    return fake


def _reasoner(**overrides: Any) -> XAISemanticReasoner:
    ticks = count(1)
    kwargs: dict[str, Any] = {
        "api_key": SECRET,
        "clock": lambda: T0,
        "id_factory": lambda prefix: f"{prefix}-{next(ticks):03d}",
    }
    kwargs.update(overrides)
    return XAISemanticReasoner(**kwargs)


# --------------------------------------------------------------------------- fixtures


def _evidence(
    evidence_id: str,
    content: str,
    kind: SourceKind = SourceKind.DOCUMENT,
    scope: tuple[str, ...] = ("intent-engine",),
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=kind,
        source_ref=f"repo://{evidence_id}",
        content=content,
        observed_at=T0,
        scope=scope,
    )


EV1 = _evidence("EV-1", "Audit records are retained for seven years.")
EV2 = _evidence("EV-2", "RETENTION_YEARS = 10", SourceKind.CODE, scope=("retention-service",))
EV3 = _evidence("EV-3", "Retention was extended to ten years in Q3.", scope=("intent-engine",))

ADDR_A = SemanticAddress(
    address_id="ADDR-A",
    project_id=PROJECT,
    subject="audit records",
    facet="retention period",
    scope=("intent-engine",),
    created_by_judgment_id="J-0",
)
CLAIM_1 = SemanticClaim(
    claim_id="CLAIM-1",
    project_id=PROJECT,
    address_id="ADDR-A",
    predicate="retention_period",
    value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
    evidence_ids=("EV-1",),
    authority=Authority.INFERRED,
    provenance=Provenance(source_kind=SourceKind.SYSTEM, source_ref="xai:grok-4.6"),
    created_by_judgment_id="JDG-OLD-1",
)
CLAIM_2 = CLAIM_1.model_copy(
    update={
        "claim_id": "CLAIM-2",
        "value": ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("10"), unit="year"),
        "evidence_ids": ("EV-2",),
        "created_by_judgment_id": "JDG-OLD-2",
    }
)


def _request(
    *,
    allowed: frozenset[JudgmentKind],
    evidence: tuple[EvidenceItem, ...] = (EV1, EV2, EV3),
    addresses: tuple[SemanticAddress, ...] = (ADDR_A,),
    claims: tuple[SemanticClaim, ...] = (CLAIM_1,),
) -> ReasoningRequest:
    return ReasoningRequest(
        project_id=PROJECT,
        evidence=evidence,
        known_addresses=addresses,
        known_claims=claims,
        allowed_judgment_kinds=allowed,
    )


CALL_ONE = frozenset({JudgmentKind.CREATE_ADDRESS, JudgmentKind.BIND_TO_ADDRESS})
CALL_TWO = frozenset(
    {
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
        JudgmentKind.CONFLICTS_WITH,
    }
)

FORBIDDEN_RUNTIME_FIELDS = {
    "judgment_id",
    "candidate_id",
    "project_id",
    "provider",
    "model",
    "policy_version",
    "invocation_id",
    "proposed_at",
    "reasoner",
    "visible_evidence_ids",
    "compared_object_ids",
    "usage",
    "cost_usd",
    "authority",
    "confidence",
    "claim_id_new",
}


def _bind_draft(
    address_id: str = "ADDR-A", evidence_ids: tuple[str, ...] = ("EV-1", "EV-2")
) -> BindToAddressDraft:
    return BindToAddressDraft(
        address_id=address_id,
        subject="audit record retention",
        facet="how long records are kept",
        evidence_ids=evidence_ids,
        rationale="The new evidence denotes the same locus as the known address.",
    )


def _support_draft(
    claim_id: str = "CLAIM-1", evidence_ids: tuple[str, ...] = ("EV-3",)
) -> SupportsClaimDraft:
    return SupportsClaimDraft(
        claim_id=claim_id,
        evidence_ids=evidence_ids,
        rationale="The new document restates the retention period already claimed.",
    )


def _supersede_draft(target_judgment_id: str = "JDG-OLD-1") -> SupersedeDraft:
    return SupersedeDraft(
        target_judgment_id=target_judgment_id,
        reason="Newer evidence states the retention period was extended.",
    )


def _assert_draft(address_id: str = "ADDR-A") -> AssertClaimDraft:
    return AssertClaimDraft(
        address_id=address_id,
        predicate="retention_period",
        value=ClaimValueDraft(kind=ClaimValueKind.QUANTITY, quantity="10", unit="year"),
        evidence_ids=("EV-3",),
        rationale="Ten years is stated explicitly in the newer document.",
    )


# --------------------------------------------------------------------------- BIND


def test_bind_draft_wraps_to_bind_proposal_with_runtime_candidate_and_derived_scope(
    harness: FakeHarness,
) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_bind_draft(),))
    (judgment,) = _reasoner().propose(_request(allowed=CALL_ONE))
    proposal = judgment.proposal
    assert isinstance(proposal, BindToAddressProposal)
    assert proposal.address_id == "ADDR-A"
    # INV-001 is minted first; the candidate then mints CAND-002 before JDG-003
    assert proposal.candidate.candidate_id == "CAND-002"
    assert judgment.judgment_id == "JDG-003"
    assert judgment.invocation_id == "INV-001"
    assert proposal.candidate.subject == "audit record retention"
    assert proposal.candidate.facet == "how long records are kept"
    assert proposal.candidate.evidence_ids == ("EV-1", "EV-2")
    # scope is runtime-derived as the union of the cited evidence scopes, sorted
    assert proposal.candidate.scope == ("intent-engine", "retention-service")
    assert judgment.compared_object_ids == ("ADDR-A",)
    assert judgment.visible_evidence_ids == ("EV-1", "EV-2", "EV-3")
    assert judgment.rationale == _bind_draft().rationale
    assert judgment.project_id == PROJECT
    assert judgment.proposed_at == T0
    assert judgment.reasoner.policy_version == POLICY_VERSION


def test_bind_to_unknown_address_fails_whole_batch(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(
        drafts=(_bind_draft(), _bind_draft(address_id="ADDR-NOPE"))
    )
    reasoner = _reasoner()
    with pytest.raises(SemanticOutputError, match="ADDR-NOPE"):
        reasoner.propose(_request(allowed=CALL_ONE))
    # paid-for call is still recorded; nothing from the batch is returned
    assert len(reasoner.receipts) == 1
    assert reasoner.receipts[0].draft_count == 2


def test_bind_with_unknown_evidence_fails_whole_batch(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_bind_draft(evidence_ids=("EV-1", "EV-404")),))
    with pytest.raises(SemanticOutputError, match="EV-404"):
        _reasoner().propose(_request(allowed=CALL_ONE))


# --------------------------------------------------------------------------- SUPPORT


def test_support_draft_wraps_and_unknown_claim_fails(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_support_draft(),))
    (judgment,) = _reasoner().propose(_request(allowed=CALL_TWO))
    proposal = judgment.proposal
    assert isinstance(proposal, SupportsClaimProposal)
    assert proposal.claim_id == "CLAIM-1"
    assert proposal.evidence_ids == ("EV-3",)
    assert judgment.compared_object_ids == ("CLAIM-1",)
    assert judgment.rationale == _support_draft().rationale
    assert judgment.judgment_id == "JDG-002"  # no candidate is minted for a support

    harness.payload = SemanticDraftPayload(drafts=(_support_draft(claim_id="CLAIM-9"),))
    with pytest.raises(SemanticOutputError, match="CLAIM-9"):
        _reasoner().propose(_request(allowed=CALL_TWO))


def test_support_with_unknown_evidence_fails(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_support_draft(evidence_ids=("EV-404",)),))
    with pytest.raises(SemanticOutputError, match="EV-404"):
        _reasoner().propose(_request(allowed=CALL_TWO))


# --------------------------------------------------------------------------- SUPERSEDE


def test_supersede_target_must_be_a_known_claims_judgment_id(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_supersede_draft("JDG-UNKNOWN"),))
    with pytest.raises(SemanticOutputError, match="JDG-UNKNOWN"):
        _reasoner().propose(_request(allowed=CALL_TWO))

    # a claim id is not a judgment id: naming the claim itself must also fail
    harness.payload = SemanticDraftPayload(drafts=(_supersede_draft("CLAIM-1"),))
    with pytest.raises(SemanticOutputError, match="CLAIM-1"):
        _reasoner().propose(_request(allowed=CALL_TWO))

    harness.payload = SemanticDraftPayload(drafts=(_supersede_draft("JDG-OLD-1"),))
    (judgment,) = _reasoner().propose(_request(allowed=CALL_TWO))
    proposal = judgment.proposal
    assert isinstance(proposal, SupersedeProposal)
    assert proposal.target_judgment_id == "JDG-OLD-1"
    assert proposal.reason == _supersede_draft().reason
    assert judgment.rationale == _supersede_draft().reason
    assert judgment.compared_object_ids == ("JDG-OLD-1",)


# --------------------------------------------------------------------------- reference law


def test_same_response_reference_to_a_new_claim_is_impossible(harness: FakeHarness) -> None:
    """A claim asserted in this response has no durable id; nothing may reference it."""
    harness.payload = SemanticDraftPayload(
        drafts=(
            _assert_draft(),
            ConflictsWithDraft(claim_a="CLAIM-1", claim_b="CLAIM-NEW", rationale="7 vs 10"),
        )
    )
    reasoner = _reasoner()
    with pytest.raises(SemanticOutputError, match="CLAIM-NEW"):
        reasoner.propose(_request(allowed=CALL_TWO))
    assert len(reasoner.receipts) == 1
    assert reasoner.receipts[0].draft_count == 2
    assert len(reasoner.draft_payloads) == 1


def test_conflicts_with_needs_two_known_claims(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(
        drafts=(ConflictsWithDraft(claim_a="CLAIM-2", claim_b="CLAIM-1", rationale="7 vs 10"),)
    )
    (judgment,) = _reasoner().propose(_request(allowed=CALL_TWO, claims=(CLAIM_1, CLAIM_2)))
    assert judgment.compared_object_ids == ("CLAIM-1", "CLAIM-2")


# --------------------------------------------------------------------------- correction


def test_correction_pattern_assert_plus_supersede_wraps_in_one_response(
    harness: FakeHarness,
) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_assert_draft(), _supersede_draft()))
    judgments = _reasoner().propose(_request(allowed=CALL_TWO))
    assert len(judgments) == 2
    asserted, superseded = judgments
    assert asserted.invocation_id == "INV-001" == superseded.invocation_id
    assert asserted.judgment_id != superseded.judgment_id

    assert isinstance(asserted.proposal, AssertClaimProposal)
    assert asserted.proposal.address_id == "ADDR-A"
    assert asserted.proposal.authority is Authority.INFERRED
    assert asserted.proposal.value == ClaimValue(
        kind=ClaimValueKind.QUANTITY, quantity=Decimal("10"), unit="year"
    )
    assert asserted.compared_object_ids == ("ADDR-A",)

    assert isinstance(superseded.proposal, SupersedeProposal)
    assert superseded.proposal.target_judgment_id == "JDG-OLD-1"
    assert superseded.compared_object_ids == ("JDG-OLD-1",)

    # neither judgment references the other: the new claim has no id anywhere
    assert asserted.judgment_id not in superseded.compared_object_ids
    assert superseded.judgment_id not in asserted.compared_object_ids
    assert asserted.judgment_id != superseded.proposal.target_judgment_id


# --------------------------------------------------------------------------- allowed kinds


def test_forbidden_kind_for_call_one_fails(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_bind_draft(), _supersede_draft()))
    reasoner = _reasoner()
    with pytest.raises(SemanticOutputError, match="SUPERSEDE"):
        reasoner.propose(_request(allowed=CALL_ONE))
    assert len(reasoner.receipts) == 1


def test_support_is_forbidden_for_call_one(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_support_draft(),))
    with pytest.raises(SemanticOutputError, match="SUPPORTS_CLAIM"):
        _reasoner().propose(_request(allowed=CALL_ONE))


def test_bind_is_forbidden_for_call_two(harness: FakeHarness) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_bind_draft(),))
    with pytest.raises(SemanticOutputError, match="BIND_TO_ADDRESS"):
        _reasoner().propose(_request(allowed=CALL_TWO))


# --------------------------------------------------------------------------- schema


def test_drafts_still_carry_no_runtime_metadata_fields() -> None:
    for draft_type in (
        CreateAddressDraft,
        AssertClaimDraft,
        EquivalentDraft,
        DistinctDraft,
        ConflictsWithDraft,
        BindToAddressDraft,
        SupportsClaimDraft,
        SupersedeDraft,
    ):
        names = set(draft_type.model_fields)
        assert names.isdisjoint(FORBIDDEN_RUNTIME_FIELDS), (
            f"{draft_type.__name__} leaks {names & FORBIDDEN_RUNTIME_FIELDS}"
        )


def test_new_drafts_reject_smuggled_runtime_fields() -> None:
    with pytest.raises(ValidationError):
        BindToAddressDraft.model_validate(
            {
                "kind": "BIND_TO_ADDRESS",
                "address_id": "ADDR-A",
                "subject": "s",
                "facet": "f",
                "evidence_ids": ["EV-1"],
                "rationale": "r",
                "candidate_id": "CAND-EVIL",
            }
        )
    with pytest.raises(ValidationError):
        SupportsClaimDraft.model_validate(
            {
                "kind": "SUPPORTS_CLAIM",
                "claim_id": "CLAIM-1",
                "evidence_ids": ["EV-1"],
                "rationale": "r",
                "judgment_id": "JDG-EVIL",
            }
        )
    with pytest.raises(ValidationError):
        SupersedeDraft.model_validate(
            {
                "kind": "SUPERSEDE",
                "target_judgment_id": "JDG-OLD-1",
                "reason": "r",
                "authority": "x",
            }
        )


def test_new_drafts_require_evidence_and_bounded_text() -> None:
    with pytest.raises(ValidationError):
        BindToAddressDraft(
            address_id="ADDR-A", subject="s", facet="f", evidence_ids=(), rationale="r"
        )
    with pytest.raises(ValidationError):
        SupportsClaimDraft(claim_id="CLAIM-1", evidence_ids=(), rationale="r")
    with pytest.raises(ValidationError):
        SupersedeDraft(target_judgment_id="JDG-OLD-1", reason="")
    with pytest.raises(ValidationError):
        SupersedeDraft(target_judgment_id="JDG-OLD-1", reason="x" * 2001)


def test_payload_discriminates_the_new_kinds() -> None:
    payload = SemanticDraftPayload.model_validate(
        {
            "drafts": [
                {
                    "kind": "BIND_TO_ADDRESS",
                    "address_id": "ADDR-A",
                    "subject": "s",
                    "facet": "f",
                    "evidence_ids": ["EV-1"],
                    "rationale": "r",
                },
                {
                    "kind": "SUPPORTS_CLAIM",
                    "claim_id": "CLAIM-1",
                    "evidence_ids": ["EV-1"],
                    "rationale": "r",
                },
                {"kind": "SUPERSEDE", "target_judgment_id": "JDG-OLD-1", "reason": "r"},
            ]
        }
    )
    assert [type(d) for d in payload.drafts] == [
        BindToAddressDraft,
        SupportsClaimDraft,
        SupersedeDraft,
    ]


def test_policy_version_is_9p(harness: FakeHarness) -> None:
    assert POLICY_VERSION == "intent-v2-9p-v1"
    assert _reasoner().fingerprint.policy_version == "intent-v2-9p-v1"


def test_schema_still_cannot_express_canonical() -> None:
    schema = json.dumps(SemanticDraftPayload.model_json_schema())
    assert "CANONICAL" not in schema
    assert "authority" not in schema
    for draft_type in (BindToAddressDraft, SupportsClaimDraft, SupersedeDraft):
        assert "authority" not in draft_type.model_fields
