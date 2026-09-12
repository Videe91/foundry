"""Task 9P-5: xAI lifecycle drafts — BIND_TO_ADDRESS, SUPPORTS_CLAIM, SUPERSEDE.

Every test here runs against a FAKE xAI transport. ZERO live calls. The load-bearing
property is the reference law (9P Global Constraint 3): every id a draft references must
already exist in the ``ReasoningRequest``. A claim asserted in the same response has no
durable id and can be referenced by nothing. The correction pattern (9P-A) is therefore
``ASSERT_CLAIM(new, at known address)`` + ``SUPERSEDE(old claim's known judgment id)`` in
one response, neither draft referencing the other.

9P2 (plan T5): the same fake transport proves that the historical ``XAISemanticReasoner``
still sends the historical system instruction and four-key payload, that the isolated
``XAIContrastiveSemanticReasoner`` sends the contrastive instruction and opts in to
``comparison_context`` rendering, and that a predecessor evidence id shown only inside
comparison context is NON-CITABLE (spec §8) for either class.
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
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    AssertClaimDraft,
    BindToAddressDraft,
    ConflictsWithDraft,
    CreateAddressDraft,
    DistinctDraft,
    EquivalentDraft,
    QuantityClaimValueDraft,
    SemanticDraftPayload,
    SemanticOutputError,
    SupersedeDraft,
    SupportsClaimDraft,
    XAIContrastiveSemanticReasoner,
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
from foundry.ports.semantic_reasoner import (
    ComparisonContext,
    ContextInclusionEdge,
    ContextRelation,
    EvidenceTransitionContext,
    ReasoningRequest,
)

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
        # The model's reply. Tests normally set ``payload`` (serialised to JSON text by the
        # fake); ``content`` overrides it with raw text so a reply that violates the sealed
        # schema can be delivered exactly as the provider would deliver it.
        self.payload: SemanticDraftPayload = SemanticDraftPayload(drafts=())
        self.content: str | None = None
        self.usage: object | None = SimpleNamespace(prompt_tokens=120, completion_tokens=40)
        self.cost_usd: float | None = 0.0042
        self.sample_error: BaseException | None = None
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

            def sample(self) -> object:
                # Mirrors ``xai_sdk`` ``Chat.sample()``: one ``Response`` whose ``content`` is
                # the model's text. No SDK-side parsing happens here; the adapter parses.
                if harness.sample_error is not None:
                    raise harness.sample_error
                content = harness.content
                if content is None:
                    content = harness.payload.model_dump_json()
                return SimpleNamespace(
                    content=content, usage=harness.usage, cost_usd=harness.cost_usd
                )

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


def _reasoner(
    cls: type[XAISemanticReasoner] = XAISemanticReasoner, **overrides: Any
) -> XAISemanticReasoner:
    ticks = count(1)
    kwargs: dict[str, Any] = {
        "api_key": SECRET,
        "clock": lambda: T0,
        "id_factory": lambda prefix: f"{prefix}-{next(ticks):03d}",
    }
    kwargs.update(overrides)
    return cls(**kwargs)


def _system_text(harness: FakeHarness) -> str:
    return _message_text(harness.chats[-1].messages[0])


def _user_payload(harness: FakeHarness) -> dict[str, Any]:
    payload = json.loads(_message_text(harness.chats[-1].messages[1]))
    assert isinstance(payload, dict)
    return payload


def _message_text(message: object) -> str:
    # xai_sdk message objects expose their text as repeated `.content` parts.
    if isinstance(message, str):
        return message
    parts = getattr(message, "content", ())
    return "".join(getattr(part, "text", "") for part in parts)


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


# 9P2 comparison material. EV-NEW supersedes EV-OLD (same artifact); CLAIM-OLD at ADDR-A
# was created from EV-OLD. Tests put EV-OLD into ``comparison_context`` and, unless a test
# says otherwise, deliberately NOT into ``request.evidence``.
EV_OLD = evidence_item(
    evidence_id="EV-OLD",
    project_id=PROJECT,
    source_kind=SourceKind.DOCUMENT,
    source_ref="repo://docs/retention.md",
    content="Retention: 7 years.",
    observed_at=T0,
    scope=("intent-engine",),
    artifact_ref="docs/retention.md",
)
EV_NEW = evidence_item(
    evidence_id="EV-NEW",
    project_id=PROJECT,
    source_kind=SourceKind.DOCUMENT,
    source_ref="repo://docs/retention.md",
    content="Retention: 10 years.",
    observed_at=T0,
    scope=("intent-engine",),
    artifact_ref="docs/retention.md",
    supersedes_evidence_id="EV-OLD",
)
CLAIM_OLD = CLAIM_1.model_copy(update={"claim_id": "CLAIM-OLD", "evidence_ids": ("EV-OLD",)})
HISTORICAL_DIFF = "\n".join(
    (
        "--- evidence:EV-OLD",
        "+++ evidence:EV-NEW",
        "@@ -1 +1 @@",
        "-Retention: 7 years.",
        "+Retention: 10 years.",
    )
)
COMPARISON = ComparisonContext(
    transitions=(
        EvidenceTransitionContext(
            current_evidence_id="EV-NEW",
            predecessor_evidence_id="EV-OLD",
            artifact_ref="docs/retention.md",
            historical_diff=HISTORICAL_DIFF,
            touched_claim_ids=("CLAIM-OLD",),
            touched_address_ids=("ADDR-A",),
            inclusion_edges=(
                ContextInclusionEdge(
                    source_id="EV-NEW", relation=ContextRelation.SUPERSEDES, target_id="EV-OLD"
                ),
                ContextInclusionEdge(
                    source_id="EV-OLD",
                    relation=ContextRelation.EFFECTIVE_EVIDENCE_OF,
                    target_id="CLAIM-OLD",
                ),
                ContextInclusionEdge(
                    source_id="CLAIM-OLD",
                    relation=ContextRelation.CLAIM_AT_ADDRESS,
                    target_id="ADDR-A",
                ),
            ),
        ),
    ),
    active_claim_profile_edges=(
        ContextInclusionEdge(
            source_id="ADDR-A",
            relation=ContextRelation.ACTIVE_CLAIM_PROFILE,
            target_id="CLAIM-OLD",
        ),
    ),
)
HISTORICAL_KEYS = {"allowed_judgment_kinds", "evidence", "known_addresses", "known_claims"}


def _request(
    *,
    allowed: frozenset[JudgmentKind],
    evidence: tuple[EvidenceItem, ...] = (EV1, EV2, EV3),
    addresses: tuple[SemanticAddress, ...] = (ADDR_A,),
    claims: tuple[SemanticClaim, ...] = (CLAIM_1,),
    comparison_context: ComparisonContext | None = None,
) -> ReasoningRequest:
    kwargs: dict[str, Any] = {
        "project_id": PROJECT,
        "evidence": evidence,
        "known_addresses": addresses,
        "known_claims": claims,
        "allowed_judgment_kinds": allowed,
    }
    if comparison_context is not None:
        kwargs["comparison_context"] = comparison_context
    return ReasoningRequest(**kwargs)


def _contrastive_request(
    *,
    allowed: frozenset[JudgmentKind],
    evidence: tuple[EvidenceItem, ...] = (EV_NEW,),
) -> ReasoningRequest:
    """Call-2 shaped request: EV-OLD is visible ONLY inside ``comparison_context``."""
    return _request(
        allowed=allowed,
        evidence=evidence,
        addresses=(ADDR_A,),
        claims=(CLAIM_OLD,),
        comparison_context=COMPARISON,
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
        kind="BIND_TO_ADDRESS",
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
        kind="SUPPORTS_CLAIM",
        claim_id=claim_id,
        evidence_ids=evidence_ids,
        rationale="The new document restates the retention period already claimed.",
    )


def _supersede_draft(target_judgment_id: str = "JDG-OLD-1") -> SupersedeDraft:
    return SupersedeDraft(
        kind="SUPERSEDE",
        target_judgment_id=target_judgment_id,
        reason="Newer evidence states the retention period was extended.",
    )


def _assert_draft(address_id: str = "ADDR-A") -> AssertClaimDraft:
    return AssertClaimDraft(
        kind="ASSERT_CLAIM",
        address_id=address_id,
        predicate="retention_period",
        value=QuantityClaimValueDraft(kind="QUANTITY", quantity="10", unit="year"),
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
            ConflictsWithDraft(
                kind="CONFLICTS_WITH", claim_ids=("CLAIM-1", "CLAIM-NEW"), rationale="7 vs 10"
            ),
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
        drafts=(
            ConflictsWithDraft(
                kind="CONFLICTS_WITH", claim_ids=("CLAIM-2", "CLAIM-1"), rationale="7 vs 10"
            ),
        )
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
            kind="BIND_TO_ADDRESS",
            address_id="ADDR-A",
            subject="s",
            facet="f",
            evidence_ids=(),
            rationale="r",
        )
    with pytest.raises(ValidationError):
        SupportsClaimDraft(
            kind="SUPPORTS_CLAIM", claim_id="CLAIM-1", evidence_ids=(), rationale="r"
        )
    with pytest.raises(ValidationError):
        SupersedeDraft(kind="SUPERSEDE", target_judgment_id="JDG-OLD-1", reason="")
    with pytest.raises(ValidationError):
        SupersedeDraft(kind="SUPERSEDE", target_judgment_id="JDG-OLD-1", reason="x" * 2001)


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
    assert POLICY_VERSION == "intent-v2-9p-v4"
    assert _reasoner().fingerprint.policy_version == "intent-v2-9p-v4"


def test_schema_still_cannot_express_canonical() -> None:
    schema = json.dumps(SemanticDraftPayload.model_json_schema())
    assert "CANONICAL" not in schema
    assert "authority" not in schema
    for draft_type in (BindToAddressDraft, SupportsClaimDraft, SupersedeDraft):
        assert "authority" not in draft_type.model_fields


# --------------------------------------------------------------------------- 9P2 policy isolation


def test_historical_reasoner_sends_historical_instruction_and_four_key_payload(
    harness: FakeHarness,
) -> None:
    """Plan §0.13/§0.14: the 9P class is untouched even when the request carries context."""
    harness.payload = SemanticDraftPayload(drafts=(_support_draft("CLAIM-OLD", ("EV-NEW",)),))
    reasoner = _reasoner()
    (judgment,) = reasoner.propose(_contrastive_request(allowed=CALL_TWO))
    assert reasoner.fingerprint.policy_version == "intent-v2-9p-v4"
    assert judgment.reasoner.policy_version == "intent-v2-9p-v4"
    assert _system_text(harness) == SYSTEM_INSTRUCTION
    payload = _user_payload(harness)
    assert set(payload) == HISTORICAL_KEYS
    assert "comparison_context" not in _message_text(harness.chats[-1].messages[1])


def test_contrastive_reasoner_sends_contrastive_instruction_and_five_key_payload(
    harness: FakeHarness,
) -> None:
    harness.payload = SemanticDraftPayload(drafts=(_support_draft("CLAIM-OLD", ("EV-NEW",)),))
    reasoner = _reasoner(XAIContrastiveSemanticReasoner)
    request = _contrastive_request(allowed=CALL_TWO)
    (judgment,) = reasoner.propose(request)
    assert isinstance(reasoner, XAISemanticReasoner)
    assert reasoner.fingerprint.provider == "xai"
    assert reasoner.fingerprint.policy_version == CONTRASTIVE_POLICY_VERSION == "intent-v2-9p2-v1"
    assert judgment.reasoner.policy_version == "intent-v2-9p2-v1"
    assert _system_text(harness) == CONTRASTIVE_SYSTEM_INSTRUCTION
    payload = _user_payload(harness)
    assert set(payload) == HISTORICAL_KEYS | {"comparison_context"}
    assert payload["comparison_context"] == request.comparison_context.model_dump(mode="json")
    # Predecessor material is context only: it is not inserted into evidence.
    assert [e["evidence_id"] for e in payload["evidence"]] == ["EV-NEW"]
    assert judgment.visible_evidence_ids == ("EV-NEW",)


def test_contrastive_reasoner_keeps_the_transport_contract(harness: FakeHarness) -> None:
    """No transport, schema or session change: only the system text and the user payload differ."""
    _reasoner().propose(_contrastive_request(allowed=CALL_TWO))
    _reasoner(XAIContrastiveSemanticReasoner).propose(_contrastive_request(allowed=CALL_TWO))
    historical_init, contrastive_init = harness.client_inits
    assert historical_init == contrastive_init
    historical_create, contrastive_create = harness.create_kwargs
    assert historical_create == contrastive_create
    assert contrastive_create["response_format"] is SemanticDraftPayload
    assert contrastive_create["store_messages"] is False
    assert [len(chat.messages) for chat in harness.chats] == [2, 2]


@pytest.mark.parametrize("cls", [XAISemanticReasoner, XAIContrastiveSemanticReasoner])
def test_predecessor_id_only_in_comparison_context_is_non_citable_for_support(
    harness: FakeHarness, cls: type[XAISemanticReasoner]
) -> None:
    """Spec §8: EV-OLD appears in comparison_context but not in request.evidence."""
    harness.payload = SemanticDraftPayload(drafts=(_support_draft("CLAIM-OLD", ("EV-OLD",)),))
    reasoner = _reasoner(cls)
    with pytest.raises(SemanticOutputError, match="unknown evidence id.*EV-OLD"):
        reasoner.propose(_contrastive_request(allowed=CALL_TWO))
    # Paid-for call is recorded; nothing from the batch is returned.
    assert len(reasoner.receipts) == 1
    assert reasoner.receipts[0].draft_count == 1
    assert len(reasoner.draft_payloads) == 1


@pytest.mark.parametrize("cls", [XAISemanticReasoner, XAIContrastiveSemanticReasoner])
def test_predecessor_id_only_in_comparison_context_is_non_citable_for_assert(
    harness: FakeHarness, cls: type[XAISemanticReasoner]
) -> None:
    draft = _assert_draft().model_copy(update={"evidence_ids": ("EV-NEW", "EV-OLD")})
    harness.payload = SemanticDraftPayload(drafts=(draft, _supersede_draft()))
    reasoner = _reasoner(cls)
    with pytest.raises(SemanticOutputError, match="unknown evidence id.*EV-OLD"):
        reasoner.propose(_contrastive_request(allowed=CALL_TWO))
    assert len(reasoner.receipts) == 1
    assert reasoner.receipts[0].draft_count == 2


def test_predecessor_id_is_citable_only_when_explicitly_in_request_evidence(
    harness: FakeHarness,
) -> None:
    """Control for the non-citable rule: the SAME drafts are admissible once EV-OLD is
    explicitly in ``request.evidence`` as well as in ``comparison_context``."""
    harness.payload = SemanticDraftPayload(drafts=(_support_draft("CLAIM-OLD", ("EV-OLD",)),))
    reasoner = _reasoner(XAIContrastiveSemanticReasoner)
    (judgment,) = reasoner.propose(
        _contrastive_request(allowed=CALL_TWO, evidence=(EV_OLD, EV_NEW))
    )
    proposal = judgment.proposal
    assert isinstance(proposal, SupportsClaimProposal)
    assert proposal.evidence_ids == ("EV-OLD",)
    assert judgment.visible_evidence_ids == ("EV-OLD", "EV-NEW")
    payload = _user_payload(harness)
    assert [e["evidence_id"] for e in payload["evidence"]] == ["EV-OLD", "EV-NEW"]
    assert payload["comparison_context"] == COMPARISON.model_dump(mode="json")

    draft = _assert_draft().model_copy(update={"evidence_ids": ("EV-NEW", "EV-OLD")})
    harness.payload = SemanticDraftPayload(drafts=(draft, _supersede_draft()))
    asserted, superseded = _reasoner(XAIContrastiveSemanticReasoner).propose(
        _contrastive_request(allowed=CALL_TWO, evidence=(EV_OLD, EV_NEW))
    )
    assert isinstance(asserted.proposal, AssertClaimProposal)
    assert asserted.proposal.evidence_ids == ("EV-NEW", "EV-OLD")
    assert isinstance(superseded.proposal, SupersedeProposal)


def test_touched_claim_and_address_ids_grant_no_reference_authority(
    harness: FakeHarness,
) -> None:
    """Ids inside comparison_context are non-citable for every reference kind: a claim
    or address named only by a transition (not in known_claims/known_addresses) fails."""
    orphan = COMPARISON.model_copy(
        update={
            "transitions": (
                COMPARISON.transitions[0].model_copy(
                    update={
                        "touched_claim_ids": ("CLAIM-OLD", "CLAIM-GHOST"),
                        "touched_address_ids": ("ADDR-A", "ADDR-GHOST"),
                    }
                ),
            )
        }
    )
    request = _request(
        allowed=CALL_TWO,
        evidence=(EV_NEW,),
        addresses=(ADDR_A,),
        claims=(CLAIM_OLD,),
        comparison_context=orphan,
    )
    harness.payload = SemanticDraftPayload(drafts=(_support_draft("CLAIM-GHOST", ("EV-NEW",)),))
    with pytest.raises(SemanticOutputError, match="CLAIM-GHOST"):
        _reasoner(XAIContrastiveSemanticReasoner).propose(request)
    harness.payload = SemanticDraftPayload(drafts=(_assert_draft("ADDR-GHOST"),))
    with pytest.raises(SemanticOutputError, match="ADDR-GHOST"):
        _reasoner(XAIContrastiveSemanticReasoner).propose(
            request.model_copy(update={"evidence": (EV_NEW, EV3)})
        )


@pytest.mark.parametrize("cls", [XAISemanticReasoner, XAIContrastiveSemanticReasoner])
def test_call_one_still_refuses_assert_and_supersede_with_visible_claims_and_context(
    harness: FakeHarness, cls: type[XAISemanticReasoner]
) -> None:
    """9P2 Call 1 sees known_claims (active claim profiles) and comparison context, but
    ``allowed_judgment_kinds`` still bounds the task: ASSERT/SUPERSEDE are refused."""
    request = _contrastive_request(allowed=CALL_ONE, evidence=(EV_NEW, EV1, EV2))
    harness.payload = SemanticDraftPayload(drafts=(_bind_draft(), _assert_draft()))
    reasoner = _reasoner(cls)
    with pytest.raises(SemanticOutputError, match="forbidden judgment kind ASSERT_CLAIM"):
        reasoner.propose(request)
    assert len(reasoner.receipts) == 1
    harness.payload = SemanticDraftPayload(drafts=(_bind_draft(), _supersede_draft()))
    with pytest.raises(SemanticOutputError, match="forbidden judgment kind SUPERSEDE"):
        _reasoner(cls).propose(request)
    harness.payload = SemanticDraftPayload(drafts=(_support_draft("CLAIM-OLD", ("EV-NEW",)),))
    with pytest.raises(SemanticOutputError, match="forbidden judgment kind SUPPORTS_CLAIM"):
        _reasoner(cls).propose(request)
    # The bounded Call-1 kinds still wrap normally under the same request.
    harness.payload = SemanticDraftPayload(drafts=(_bind_draft(),))
    (judgment,) = _reasoner(cls).propose(request)
    assert isinstance(judgment.proposal, BindToAddressProposal)
