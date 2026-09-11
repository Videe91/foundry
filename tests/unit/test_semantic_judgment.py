from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from foundry.adapters.semantics.fake_reasoner import ScriptedSemanticReasoner
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    DistinctProposal,
    EquivalentProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    agrees,
    contradicts,
    independent,
    proposal_signature,
)
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
HUMAN_ALICE = ReasonerFingerprint(provider="human", model="human://alice", policy_version="p1")


def _candidate(candidate_id: str = "CAND-1") -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject="audit records",
        facet="retention period",
        scope=("compliance",),
        evidence_ids=("EV-1",),
    )


def _claim_proposal(**overrides: object) -> AssertClaimProposal:
    fields: dict[str, object] = {
        "address_id": "ADDR-1",
        "predicate": "retention_period",
        "value": ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
        "evidence_ids": ("EV-1",),
        "authority": Authority.OBSERVED,
    }
    fields.update(overrides)
    return AssertClaimProposal(**fields)  # type: ignore[arg-type]


def _judgment(
    proposal: JudgmentProposal,
    *,
    judgment_id: str = "JDG-1",
    reasoner: ReasonerFingerprint = MODEL_A,
    invocation_id: str = "INV-1",
    rationale: str = "Evidence EV-1 states a seven-year retention requirement.",
    confidence: float | None = None,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id="PROJ-1",
        proposal=proposal,
        visible_evidence_ids=("EV-1",),
        compared_object_ids=("ADDR-1",),
        rationale=rationale,
        confidence=confidence,
        reasoner=reasoner,
        invocation_id=invocation_id,
        proposed_at=datetime(2026, 9, 11, tzinfo=UTC),
    )


# --- enums ---------------------------------------------------------------


def test_judgment_kind_members() -> None:
    assert {k.value for k in JudgmentKind} == {
        "CREATE_ADDRESS",
        "BIND_TO_ADDRESS",
        "ASSERT_CLAIM",
        "EQUIVALENT",
        "DISTINCT",
        "CONFLICTS_WITH",
        "SUPERSEDE",
    }


def test_admission_route_members() -> None:
    assert {r.value for r in AdmissionRoute} == {
        "APPLY",
        "REQUIRE_SECOND_LENS",
        "REQUIRE_HUMAN",
        "REJECT",
    }


# --- fingerprint and independence ----------------------------------------


def test_fingerprint_fields_must_be_non_empty() -> None:
    for field in ("provider", "model", "policy_version"):
        with pytest.raises(ValidationError):
            ReasonerFingerprint(**{**MODEL_A.model_dump(), field: ""})


def test_is_human_is_provider_human() -> None:
    assert HUMAN_ALICE.is_human is True
    assert MODEL_A.is_human is False


def test_independent_same_fingerprint_different_invocation_is_false() -> None:
    same = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
    assert independent(MODEL_A, same) is False
    assert independent(MODEL_A, MODEL_A) is False
    a = _judgment(_claim_proposal(), invocation_id="INV-1")
    b = _judgment(_claim_proposal(), judgment_id="JDG-2", invocation_id="INV-2")
    assert independent(a.reasoner, b.reasoner) is False


def test_independent_same_model_different_policy_version_is_false() -> None:
    other_policy = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p2")
    assert independent(MODEL_A, other_policy) is False


def test_independent_provider_differs_is_true() -> None:
    other = ReasonerFingerprint(provider="anthropic", model="grok-4", policy_version="p1")
    assert independent(MODEL_A, other) is True


def test_independent_model_differs_is_true() -> None:
    other = ReasonerFingerprint(provider="xai", model="grok-3", policy_version="p1")
    assert independent(MODEL_A, other) is True


def test_independent_human_vs_model_is_true() -> None:
    assert independent(HUMAN_ALICE, MODEL_A) is True
    assert independent(MODEL_A, HUMAN_ALICE) is True


def test_independent_same_human_actor_is_false() -> None:
    again = ReasonerFingerprint(provider="human", model="human://alice", policy_version="p9")
    assert independent(HUMAN_ALICE, again) is False


def test_independent_different_humans_is_true() -> None:
    bob = ReasonerFingerprint(provider="human", model="human://bob", policy_version="p1")
    assert independent(HUMAN_ALICE, bob) is True


# --- proposal validation -------------------------------------------------


def test_create_address_proposal_valid() -> None:
    proposal = CreateAddressProposal(candidate=_candidate())
    assert proposal.kind is JudgmentKind.CREATE_ADDRESS


def test_bind_to_address_proposal_valid_and_requires_address() -> None:
    proposal = BindToAddressProposal(candidate=_candidate(), address_id="ADDR-1")
    assert proposal.kind is JudgmentKind.BIND_TO_ADDRESS
    with pytest.raises(ValidationError):
        BindToAddressProposal(candidate=_candidate(), address_id="")


def test_assert_claim_proposal_valid() -> None:
    proposal = _claim_proposal()
    assert proposal.kind is JudgmentKind.ASSERT_CLAIM
    assert proposal.authority is Authority.OBSERVED


def test_assert_claim_proposal_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        _claim_proposal(evidence_ids=())


def test_equivalent_proposal_valid_and_rejects_self_pair() -> None:
    proposal = EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2")
    assert proposal.kind is JudgmentKind.EQUIVALENT
    with pytest.raises(ValidationError):
        EquivalentProposal(address_a="ADDR-1", address_b="ADDR-1")


def test_distinct_proposal_valid_and_rejects_self_pair() -> None:
    proposal = DistinctProposal(address_a="ADDR-1", address_b="ADDR-2")
    assert proposal.kind is JudgmentKind.DISTINCT
    with pytest.raises(ValidationError):
        DistinctProposal(address_a="ADDR-1", address_b="ADDR-1")


def test_conflicts_with_proposal_valid_and_rejects_self_pair() -> None:
    proposal = ConflictsWithProposal(claim_a="CLM-1", claim_b="CLM-2")
    assert proposal.kind is JudgmentKind.CONFLICTS_WITH
    with pytest.raises(ValidationError):
        ConflictsWithProposal(claim_a="CLM-1", claim_b="CLM-1")


def test_supersede_proposal_valid_and_requires_reason() -> None:
    proposal = SupersedeProposal(target_judgment_id="JDG-1", reason="Evidence retracted.")
    assert proposal.kind is JudgmentKind.SUPERSEDE
    with pytest.raises(ValidationError):
        SupersedeProposal(target_judgment_id="JDG-1", reason="")


def test_proposal_kind_cannot_be_overridden() -> None:
    with pytest.raises(ValidationError):
        EquivalentProposal(kind="DISTINCT", address_a="ADDR-1", address_b="ADDR-2")  # type: ignore[arg-type]


# --- signatures, agreement, contradiction --------------------------------


def test_equivalent_and_distinct_share_pair_signature_regardless_of_order() -> None:
    equivalent = EquivalentProposal(address_a="ADDR-2", address_b="ADDR-1")
    distinct = DistinctProposal(address_a="ADDR-1", address_b="ADDR-2")
    assert proposal_signature(equivalent) == ("PAIR", "ADDR-1", "ADDR-2")
    assert proposal_signature(equivalent) == proposal_signature(distinct)


def test_other_signatures() -> None:
    assert proposal_signature(ConflictsWithProposal(claim_a="CLM-2", claim_b="CLM-1")) == (
        "CONFLICT",
        "CLM-1",
        "CLM-2",
    )
    assert proposal_signature(SupersedeProposal(target_judgment_id="JDG-1", reason="r")) == (
        "SUPERSEDE",
        "JDG-1",
    )
    assert proposal_signature(CreateAddressProposal(candidate=_candidate("CAND-9"))) == (
        "CREATE",
        "CAND-9",
    )
    assert proposal_signature(
        BindToAddressProposal(candidate=_candidate("CAND-9"), address_id="ADDR-3")
    ) == ("BIND", "CAND-9", "ADDR-3")
    claim_signature = proposal_signature(_claim_proposal())
    assert claim_signature[0] == "CLAIM"
    assert claim_signature[1:3] == ("ADDR-1", "retention_period")
    assert claim_signature[4] == "OBSERVED"
    assert len(claim_signature) == 5


def test_agrees_same_kind_same_signature() -> None:
    assert agrees(
        EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2"),
        EquivalentProposal(address_a="ADDR-2", address_b="ADDR-1"),
    )
    assert agrees(_claim_proposal(), _claim_proposal())
    assert not agrees(
        _claim_proposal(),
        _claim_proposal(
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("10"), unit="year")
        ),
    )
    assert not agrees(_claim_proposal(), _claim_proposal(authority=Authority.PROPOSED))


def test_agrees_requires_same_kind_even_with_equal_signature() -> None:
    assert not agrees(
        EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2"),
        DistinctProposal(address_a="ADDR-1", address_b="ADDR-2"),
    )


def test_contradicts_equivalent_vs_distinct_same_pair() -> None:
    equivalent = EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2")
    distinct = DistinctProposal(address_a="ADDR-1", address_b="ADDR-2")
    assert contradicts(equivalent, distinct) is True
    assert contradicts(distinct, equivalent) is True


def test_contradicts_reversed_pair_order_still_true() -> None:
    equivalent = EquivalentProposal(address_a="ADDR-2", address_b="ADDR-1")
    distinct = DistinctProposal(address_a="ADDR-1", address_b="ADDR-2")
    assert contradicts(equivalent, distinct) is True


def test_contradicts_false_for_different_pairs_and_kinds() -> None:
    equivalent = EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2")
    other_pair = DistinctProposal(address_a="ADDR-1", address_b="ADDR-3")
    conflict = ConflictsWithProposal(claim_a="ADDR-1", claim_b="ADDR-2")
    same_equivalent = EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2")
    assert contradicts(equivalent, other_pair) is False
    assert contradicts(equivalent, conflict) is False
    assert contradicts(equivalent, same_equivalent) is False
    assert contradicts(_claim_proposal(), _claim_proposal()) is False


# --- SemanticJudgment ----------------------------------------------------


def test_judgment_kind_property_comes_from_proposal() -> None:
    assert _judgment(_claim_proposal()).kind is JudgmentKind.ASSERT_CLAIM
    assert (
        _judgment(EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2")).kind
        is JudgmentKind.EQUIVALENT
    )


def test_rationale_length_bounds() -> None:
    assert len(_judgment(_claim_proposal(), rationale="x" * 2000).rationale) == 2000
    with pytest.raises(ValidationError):
        _judgment(_claim_proposal(), rationale="x" * 2001)
    with pytest.raises(ValidationError):
        _judgment(_claim_proposal(), rationale="")


def test_confidence_bounds_and_optional() -> None:
    assert _judgment(_claim_proposal()).confidence is None
    assert _judgment(_claim_proposal(), confidence=0.0).confidence == 0.0
    assert _judgment(_claim_proposal(), confidence=1.0).confidence == 1.0
    with pytest.raises(ValidationError):
        _judgment(_claim_proposal(), confidence=1.01)
    with pytest.raises(ValidationError):
        _judgment(_claim_proposal(), confidence=-0.01)


def test_judgment_requires_invocation_id() -> None:
    with pytest.raises(ValidationError):
        _judgment(_claim_proposal(), invocation_id="")


def test_judgment_json_round_trip_through_discriminated_union() -> None:
    proposals: tuple[JudgmentProposal, ...] = (
        CreateAddressProposal(candidate=_candidate()),
        BindToAddressProposal(candidate=_candidate(), address_id="ADDR-1"),
        _claim_proposal(),
        EquivalentProposal(address_a="ADDR-1", address_b="ADDR-2"),
        DistinctProposal(address_a="ADDR-1", address_b="ADDR-2"),
        ConflictsWithProposal(claim_a="CLM-1", claim_b="CLM-2"),
        SupersedeProposal(target_judgment_id="JDG-0", reason="Evidence retracted."),
    )
    for proposal in proposals:
        original = _judgment(proposal, confidence=0.5)
        restored = SemanticJudgment.model_validate(original.model_dump(mode="json"))
        assert restored == original
        assert type(restored.proposal) is type(proposal)
        assert restored.kind is original.kind


def test_judgment_is_frozen() -> None:
    judgment = _judgment(_claim_proposal())
    with pytest.raises(ValidationError):
        judgment.rationale = "changed"  # type: ignore[misc]


# --- reasoner port and fake ----------------------------------------------


def test_reasoning_request_carries_no_store_or_state() -> None:
    names = set(ReasoningRequest.model_fields)
    assert names == {
        "project_id",
        "evidence",
        "focus_object_ids",
        "known_addresses",
        "known_claims",
        "allowed_judgment_kinds",  # 9O: the task is explicit, never inferred
    }
    for forbidden in ("store", "event_store", "state", "intent_state", "events"):
        assert forbidden not in names


def test_scripted_reasoner_returns_scripted_judgments_and_records_requests() -> None:
    judgments = (_judgment(_claim_proposal()),)
    reasoner: SemanticReasoner = ScriptedSemanticReasoner(MODEL_A, judgments)
    request = ReasoningRequest(
        project_id="PROJ-1",
        evidence=(
            evidence_item(
                evidence_id="EV-1",
                project_id="PROJ-1",
                source_kind=SourceKind.DOCUMENT,
                source_ref="doc://retention.md",
                content="Audit records must be retained for seven years.",
                observed_at=datetime(2026, 9, 11, tzinfo=UTC),
            ),
        ),
        focus_object_ids=("ADDR-1",),
    )
    assert reasoner.fingerprint == MODEL_A
    assert reasoner.propose(request) == judgments
    assert reasoner.propose(request) == judgments
    scripted = ScriptedSemanticReasoner(MODEL_A, ())
    assert scripted.propose(request) == ()
    assert scripted.requests == [request]
    assert isinstance(reasoner, ScriptedSemanticReasoner)
    assert reasoner.requests == [request, request]
