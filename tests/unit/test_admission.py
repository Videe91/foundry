"""Deterministic admission routing tests (plan §6.2; spec §20.1, §22).

States are constructed directly (``SemanticState`` / ``IntentState``) rather than
replayed, because routing is a pure function over state and the shape of the
state is what each case is about.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypedDict, Unpack

import pytest

from foundry.domain.admission import AdmissionDecision, AdmissionPolicy, route_judgment
from foundry.domain.common import Authority, LifecycleStatus, Provenance, SourceKind
from foundry.domain.events import SemanticAdmissionPayload
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticAddress,
    SemanticCandidate,
    SemanticClaim,
)
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
)
from foundry.domain.semantic_state import EquivalenceRecord, SemanticState, SupersessionRecord
from foundry.domain.state import IntentState

PROJECT = "PROJ-1"
OCCURRED_AT = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")
MODEL_A_V2 = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p2")
MODEL_B = ReasonerFingerprint(provider="anthropic", model="claude-opus-5", policy_version="p1")
HUMAN_ALICE = ReasonerFingerprint(provider="human", model="human://alice", policy_version="p1")
HUMAN_BOB = ReasonerFingerprint(provider="human", model="human://bob", policy_version="p1")

COMPLIANCE = ("compliance",)


# --- builders -------------------------------------------------------------


class JudgmentOptions(TypedDict, total=False):
    reasoner: ReasonerFingerprint
    confidence: float | None
    invocation_id: str
    visible_evidence_ids: tuple[str, ...]


def _evidence(evidence_id: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.HUMAN,
        source_ref="human://alice",
        content=f"Statement {evidence_id}: audit records are retained.",
        observed_at=OCCURRED_AT,
    )


def _address(address_id: str, *, scope: tuple[str, ...] = COMPLIANCE) -> SemanticAddress:
    return SemanticAddress(
        address_id=address_id,
        project_id=PROJECT,
        subject="audit records",
        facet="retention period",
        scope=scope,
        created_by_judgment_id=f"JDG-create-{address_id}",
    )


def _claim(claim_id: str, address_id: str) -> SemanticClaim:
    return SemanticClaim(
        claim_id=claim_id,
        project_id=PROJECT,
        address_id=address_id,
        predicate="retention_period",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
        evidence_ids=("EV-1",),
        authority=Authority.OBSERVED,
        provenance=Provenance(source_kind=SourceKind.SYSTEM, source_ref="xai:grok-4"),
        created_by_judgment_id=f"JDG-claim-{claim_id}",
    )


def _candidate(
    candidate_id: str = "CAND-1",
    *,
    scope: tuple[str, ...] = COMPLIANCE,
    evidence_ids: tuple[str, ...] = ("EV-1",),
) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject="audit records",
        facet="retention period",
        scope=scope,
        evidence_ids=evidence_ids,
    )


def _judgment(
    judgment_id: str, proposal: JudgmentProposal, **options: Unpack[JudgmentOptions]
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=options.get("visible_evidence_ids", ("EV-1",)),
        rationale="EV-1 states a retention obligation for audit records.",
        confidence=options.get("confidence"),
        reasoner=options.get("reasoner", MODEL_A),
        invocation_id=options.get("invocation_id", f"INV-{judgment_id}"),
        proposed_at=OCCURRED_AT,
    )


def _create(judgment_id: str, **options: Unpack[JudgmentOptions]) -> SemanticJudgment:
    return _judgment(judgment_id, CreateAddressProposal(candidate=_candidate()), **options)


def _bind(
    judgment_id: str, address_id: str, **options: Unpack[JudgmentOptions]
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(candidate=_candidate(), address_id=address_id),
        **options,
    )


def _assert_claim(
    judgment_id: str,
    address_id: str = "ADDR-A",
    *,
    authority: Authority = Authority.PROPOSED,
    evidence_ids: tuple[str, ...] = ("EV-1",),
    **options: Unpack[JudgmentOptions],
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
            evidence_ids=evidence_ids,
            authority=authority,
        ),
        **options,
    )


def _equivalent(
    judgment_id: str, a: str = "ADDR-A", b: str = "ADDR-B", **options: Unpack[JudgmentOptions]
) -> SemanticJudgment:
    return _judgment(judgment_id, EquivalentProposal(address_a=a, address_b=b), **options)


def _distinct(
    judgment_id: str, a: str = "ADDR-A", b: str = "ADDR-B", **options: Unpack[JudgmentOptions]
) -> SemanticJudgment:
    return _judgment(judgment_id, DistinctProposal(address_a=a, address_b=b), **options)


def _conflict(
    judgment_id: str, a: str = "CLAIM-1", b: str = "CLAIM-2", **options: Unpack[JudgmentOptions]
) -> SemanticJudgment:
    return _judgment(judgment_id, ConflictsWithProposal(claim_a=a, claim_b=b), **options)


def _supersede(
    judgment_id: str, target: str, **options: Unpack[JudgmentOptions]
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupersedeProposal(target_judgment_id=target, reason="later evidence"),
        **options,
    )


def _admitted(judgment_id: str, route: AdmissionRoute) -> SemanticAdmissionPayload:
    return SemanticAdmissionPayload(judgment_id=judgment_id, route=route, reasons=("TEST",))


def _supersession(target: str, by: str) -> SupersessionRecord:
    return SupersessionRecord(
        target_judgment_id=target, superseding_judgment_id=by, recorded_by_event_id=f"EVT-{by}"
    )


def _authority_record(
    record_id: str,
    authorized_by: str,
    *,
    scope: tuple[str, ...] = (),
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
    authority: Authority = Authority.CANONICAL,
) -> AuthorityRecord:
    return AuthorityRecord(
        id=record_id,
        project_id=PROJECT,
        authority=authority,
        lifecycle=lifecycle,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="human://founder"),
        created_at=OCCURRED_AT,
        scope=scope,
        subject_id="ADDR-A",
        authorized_by=authorized_by,
        rationale="Owns compliance decisions.",
    )


def _claim_judgment(claim: SemanticClaim) -> SemanticJudgment:
    """The ``ASSERT_CLAIM`` judgment whose application makes ``claim`` live in the view."""
    return _judgment(
        claim.created_by_judgment_id,
        AssertClaimProposal(
            address_id=claim.address_id,
            predicate=claim.predicate,
            value=claim.value,
            evidence_ids=claim.evidence_ids,
            authority=claim.authority,
        ),
    )


def _state(
    *,
    addresses: tuple[SemanticAddress, ...] = (_address("ADDR-A"), _address("ADDR-B")),
    claims: tuple[SemanticClaim, ...] = (_claim("CLAIM-1", "ADDR-A"), _claim("CLAIM-2", "ADDR-A")),
    dead_claims: tuple[str, ...] = (),
    judgments: tuple[SemanticJudgment, ...] = (),
    applied: tuple[str, ...] = (),
    supersessions: tuple[SupersessionRecord, ...] = (),
    records: tuple[AuthorityRecord, ...] = (),
    admissions: tuple[SemanticAdmissionPayload, ...] = (),
) -> IntentState:
    """Every claim's asserting judgment is recorded and applied (the claim is LIVE)
    unless its id is listed in ``dead_claims``, in which case it is only recorded.
    An applied ``EQUIVALENT`` judgment gets the ``EquivalenceRecord`` replay would
    have written, so ``derive_view`` sees the merged locus."""
    claim_judgments = tuple(_claim_judgment(c) for c in claims)
    live = tuple(
        j.judgment_id
        for c, j in zip(claims, claim_judgments, strict=True)
        if c.claim_id not in dead_claims
    )
    equivalences = tuple(
        EquivalenceRecord(
            judgment_id=j.judgment_id,
            address_a=j.proposal.address_a,
            address_b=j.proposal.address_b,
        )
        for j in judgments
        if isinstance(j.proposal, EquivalentProposal) and j.judgment_id in applied
    )
    semantic = SemanticState(
        evidence={"EV-1": _evidence("EV-1")},
        addresses={a.address_id: a for a in addresses},
        claims={c.claim_id: c for c in claims},
        judgments={j.judgment_id: j for j in (*claim_judgments, *judgments)},
        admissions={a.judgment_id: a for a in admissions},
        applied_judgment_ids=(*live, *applied),
        supersessions=supersessions,
        equivalences=equivalences,
    )
    return IntentState(project_id=PROJECT, objects={r.id: r for r in records}, semantic=semantic)


def _route(judgment: SemanticJudgment, state: IntentState | None = None) -> AdmissionDecision:
    return route_judgment(state or _state(), judgment, AdmissionPolicy())


# --- policy / decision models --------------------------------------------


def test_policy_defaults_material_kinds_and_authority_requirement() -> None:
    policy = AdmissionPolicy()

    assert policy.material_kinds == frozenset(
        {JudgmentKind.EQUIVALENT, JudgmentKind.CONFLICTS_WITH, JudgmentKind.SUPERSEDE}
    )
    assert policy.canonical_requires_authority is True


def test_decision_requires_at_least_one_reason() -> None:
    with pytest.raises(ValueError):
        AdmissionDecision(judgment_id="JDG-1", route=AdmissionRoute.APPLY, reasons=())


def test_decision_carries_judgment_id_and_defaults_no_corroboration() -> None:
    decision = _route(_create("JDG-1"))

    assert decision.judgment_id == "JDG-1"
    assert decision.corroborating_judgment_ids == ()


# --- G: high confidence alone is not authority -----------------------------


def test_g_high_confidence_equivalent_alone_requires_second_lens() -> None:
    decision = _route(_equivalent("JDG-1", confidence=1.0))

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert decision.reasons == ("MATERIAL_REQUIRES_SECOND_LENS",)
    assert decision.corroborating_judgment_ids == ()


# --- H: low-risk kinds from a model apply ---------------------------------


def test_h_create_address_from_model_applies_low_risk() -> None:
    decision = _route(_create("JDG-1"))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_h_bind_from_model_applies_low_risk() -> None:
    decision = _route(_bind("JDG-1", "ADDR-A"))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_h_proposed_claim_from_model_applies_low_risk() -> None:
    decision = _route(_assert_claim("JDG-1", authority=Authority.PROPOSED))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_h_distinct_from_model_applies_low_risk() -> None:
    decision = _route(_distinct("JDG-1"))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


# --- I: one material judgment never applies alone -------------------------


def test_i_conflicts_with_alone_is_not_applied() -> None:
    decision = _route(_conflict("JDG-1"))

    assert decision.route is not AdmissionRoute.APPLY
    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


def test_i_supersede_alone_is_not_applied() -> None:
    state = _state(judgments=(_equivalent("JDG-1"),), applied=("JDG-1",))

    decision = _route(_supersede("JDG-2", "JDG-1"), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


# --- J: lens disagreement ---------------------------------------------------


def test_j_equivalent_then_independent_distinct_requires_human() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_A),))

    decision = _route(_distinct("JDG-2", reasoner=MODEL_B), state)

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN
    assert decision.reasons == ("LENS_DISAGREEMENT",)
    assert decision.corroborating_judgment_ids == ("JDG-1",)


def test_j_distinct_then_independent_equivalent_requires_human() -> None:
    state = _state(judgments=(_distinct("JDG-1", reasoner=MODEL_B),))

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN
    assert decision.reasons == ("LENS_DISAGREEMENT",)
    assert decision.corroborating_judgment_ids == ("JDG-1",)


def test_j_low_risk_distinct_never_auto_applies_over_a_contradicting_lens() -> None:
    """DISTINCT is low-risk by default; disagreement must still stop it (spec §21 #7)."""
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_A),))

    decision = _route(_distinct("JDG-2", reasoner=MODEL_B), state)

    assert decision.route is not AdmissionRoute.APPLY
    assert "LOW_RISK" not in decision.reasons


def test_j_disagreement_beats_agreement() -> None:
    state = _state(
        judgments=(
            _equivalent("JDG-1", reasoner=MODEL_B),
            _distinct("JDG-2", reasoner=HUMAN_BOB),
        )
    )

    decision = _route(_equivalent("JDG-3", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN
    assert decision.corroborating_judgment_ids == ("JDG-2",)


def test_j_disagreement_on_a_different_pair_is_irrelevant() -> None:
    state = _state(
        addresses=(_address("ADDR-A"), _address("ADDR-B"), _address("ADDR-C")),
        judgments=(_distinct("JDG-1", "ADDR-A", "ADDR-C", reasoner=MODEL_B),),
    )

    decision = _route(_equivalent("JDG-2", "ADDR-A", "ADDR-B", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


# --- independence is never faked --------------------------------------------


def test_same_fingerprint_second_equivalent_is_not_corroboration() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_A, invocation_id="INV-1"),))

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A, invocation_id="INV-2"), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert decision.corroborating_judgment_ids == ()


def test_same_model_different_policy_version_is_not_corroboration() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_A),))

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A_V2), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


def test_same_fingerprint_distinct_does_not_count_as_disagreement() -> None:
    state = _state(judgments=(_distinct("JDG-1", reasoner=MODEL_A),))

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


def test_independent_agreeing_second_lens_applies_with_corroboration() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_A),))

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_B), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("INDEPENDENT_CORROBORATION",)
    assert decision.corroborating_judgment_ids == ("JDG-1",)


def test_independent_agreeing_conflicts_with_applies() -> None:
    state = _state(judgments=(_conflict("JDG-1", "CLAIM-2", "CLAIM-1", reasoner=MODEL_B),))

    decision = _route(_conflict("JDG-2", "CLAIM-1", "CLAIM-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.corroborating_judgment_ids == ("JDG-1",)


def test_corroborating_ids_are_sorted_and_complete() -> None:
    state = _state(
        judgments=(
            _equivalent("JDG-9", reasoner=MODEL_B),
            _equivalent("JDG-2", reasoner=HUMAN_BOB),
        )
    )

    decision = _route(_equivalent("JDG-5", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.corroborating_judgment_ids == ("JDG-2", "JDG-9")


def test_superseded_prior_judgment_is_not_corroboration() -> None:
    state = _state(
        judgments=(_equivalent("JDG-1", reasoner=MODEL_B), _supersede("JDG-2", "JDG-1")),
        applied=("JDG-1", "JDG-2"),
        supersessions=(_supersession("JDG-1", "JDG-2"),),
    )

    decision = _route(_equivalent("JDG-3", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert decision.corroborating_judgment_ids == ()


def test_unapplied_recorded_judgment_counts_as_a_lens() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_B),), applied=())

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.corroborating_judgment_ids == ("JDG-1",)


def test_judgment_already_recorded_does_not_corroborate_itself() -> None:
    judgment = _equivalent("JDG-1", reasoner=MODEL_A)
    state = _state(judgments=(judgment,), applied=())

    decision = _route(judgment, state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


# --- K: canonical claims and authority -------------------------------------


def test_k_human_canonical_claim_without_record_requires_human() -> None:
    decision = _route(_assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE))

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN
    assert decision.reasons == ("AUTHORITY_UNRESOLVED",)


def test_k_human_canonical_claim_with_active_record_applies() -> None:
    state = _state(records=(_authority_record("AUTH-1", "human://alice", scope=COMPLIANCE),))

    decision = _route(
        _assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE), state
    )

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)


def test_k_human_canonical_claim_with_project_wide_record_applies() -> None:
    state = _state(records=(_authority_record("AUTH-1", "human://alice", scope=()),))

    decision = _route(
        _assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE), state
    )

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)


def test_k_record_with_non_intersecting_scope_requires_human() -> None:
    state = _state(records=(_authority_record("AUTH-1", "human://alice", scope=("billing",)),))

    decision = _route(
        _assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE), state
    )

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN
    assert decision.reasons == ("AUTHORITY_UNRESOLVED",)


def test_k_record_for_another_actor_does_not_confer_authority() -> None:
    state = _state(records=(_authority_record("AUTH-1", "human://bob"),))

    decision = _route(
        _assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE), state
    )

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN


@pytest.mark.parametrize(
    ("lifecycle", "authority"),
    [
        (LifecycleStatus.SUPERSEDED, Authority.CANONICAL),
        (LifecycleStatus.REJECTED, Authority.CANONICAL),
        (LifecycleStatus.RESOLVED, Authority.CANONICAL),
        (LifecycleStatus.ACTIVE, Authority.REJECTED),
        (LifecycleStatus.ACTIVE, Authority.SUPERSEDED),
    ],
)
def test_k_inactive_record_does_not_confer_authority(
    lifecycle: LifecycleStatus, authority: Authority
) -> None:
    record = _authority_record("AUTH-1", "human://alice", lifecycle=lifecycle, authority=authority)
    state = _state(records=(record,))

    decision = _route(
        _assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE), state
    )

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN
    assert decision.reasons == ("AUTHORITY_UNRESOLVED",)


def test_k_ai_canonical_claim_is_rejected_as_authority_invention() -> None:
    state = _state(records=(_authority_record("AUTH-1", "grok-4"),))

    decision = _route(
        _assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=MODEL_A), state
    )

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("AUTHORITY_INVENTION",)


def test_k_ai_canonical_claim_is_rejected_even_with_independent_corroboration() -> None:
    state = _state(
        judgments=(_assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=MODEL_B),)
    )

    decision = _route(
        _assert_claim("JDG-2", authority=Authority.CANONICAL, reasoner=MODEL_A), state
    )

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("AUTHORITY_INVENTION",)


def test_k_policy_can_disable_canonical_authority_rule() -> None:
    policy = AdmissionPolicy(canonical_requires_authority=False)

    decision = route_judgment(
        _state(), _assert_claim("JDG-1", authority=Authority.CANONICAL, reasoner=MODEL_A), policy
    )

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


# --- human authority path for other kinds -----------------------------------


def test_human_equivalent_with_project_wide_record_applies() -> None:
    state = _state(records=(_authority_record("AUTH-1", "human://alice", scope=()),))

    decision = _route(_equivalent("JDG-1", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)


def test_human_equivalent_with_scoped_record_is_a_lens_not_authority() -> None:
    state = _state(records=(_authority_record("AUTH-1", "human://alice", scope=COMPLIANCE),))

    decision = _route(_equivalent("JDG-1", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


def test_human_supersede_with_project_wide_record_applies() -> None:
    state = _state(
        judgments=(_equivalent("JDG-1"),),
        applied=("JDG-1",),
        records=(_authority_record("AUTH-1", "human://alice", scope=()),),
    )

    decision = _route(_supersede("JDG-2", "JDG-1", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)


def test_human_bind_with_scoped_record_covering_address_applies_as_authority() -> None:
    state = _state(records=(_authority_record("AUTH-1", "human://alice", scope=COMPLIANCE),))

    decision = _route(_bind("JDG-1", "ADDR-A", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)


def test_human_equivalent_without_record_requires_second_lens() -> None:
    decision = _route(_equivalent("JDG-1", reasoner=HUMAN_ALICE))

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


def test_human_without_record_corroborates_independent_model_lens() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_A),))

    decision = _route(_equivalent("JDG-2", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("INDEPENDENT_CORROBORATION",)
    assert decision.corroborating_judgment_ids == ("JDG-1",)


def test_human_lens_disagreeing_with_model_requires_human() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_A),))

    decision = _route(_distinct("JDG-2", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.REQUIRE_HUMAN
    assert decision.reasons == ("LENS_DISAGREEMENT",)


# --- rejected judgments are never lenses (spec §22.11) ------------------------


def test_rejected_prior_judgment_is_not_corroboration() -> None:
    state = _state(
        judgments=(_equivalent("JDG-1", reasoner=MODEL_B),),
        admissions=(_admitted("JDG-1", AdmissionRoute.REJECT),),
    )

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert decision.corroborating_judgment_ids == ()


def test_rejected_prior_distinct_is_not_disagreement() -> None:
    state = _state(
        judgments=(_distinct("JDG-1", reasoner=MODEL_B),),
        admissions=(_admitted("JDG-1", AdmissionRoute.REJECT),),
    )

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert decision.reasons == ("MATERIAL_REQUIRES_SECOND_LENS",)


@pytest.mark.parametrize(
    "route", [AdmissionRoute.REQUIRE_SECOND_LENS, AdmissionRoute.REQUIRE_HUMAN]
)
def test_pending_prior_judgment_still_counts_as_a_lens(route: AdmissionRoute) -> None:
    state = _state(
        judgments=(_equivalent("JDG-1", reasoner=MODEL_B),),
        admissions=(_admitted("JDG-1", route),),
    )

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.corroborating_judgment_ids == ("JDG-1",)


# --- contradiction with an active applied judgment -------------------------------


def _active_equivalent_state(*, records: tuple[AuthorityRecord, ...] = ()) -> IntentState:
    return _state(
        judgments=(_equivalent("JDG-1", reasoner=MODEL_A),),
        applied=("JDG-1",),
        admissions=(_admitted("JDG-1", AdmissionRoute.APPLY),),
        records=records,
    )


def test_model_distinct_over_active_applied_equivalent_is_rejected() -> None:
    decision = _route(_distinct("JDG-2", reasoner=MODEL_B), _active_equivalent_state())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("CONTRADICTS_ACTIVE_JUDGMENT:JDG-1",)


def test_same_fingerprint_distinct_over_active_applied_equivalent_is_rejected() -> None:
    decision = _route(_distinct("JDG-2", reasoner=MODEL_A), _active_equivalent_state())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("CONTRADICTS_ACTIVE_JUDGMENT:JDG-1",)


def test_human_authority_distinct_over_active_applied_equivalent_is_rejected() -> None:
    state = _active_equivalent_state(
        records=(_authority_record("AUTH-1", "human://alice", scope=()),)
    )

    decision = _route(_distinct("JDG-2", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("CONTRADICTS_ACTIVE_JUDGMENT:JDG-1",)


def test_equivalent_over_active_applied_distinct_is_rejected() -> None:
    state = _state(
        judgments=(_distinct("JDG-1", reasoner=MODEL_A),),
        applied=("JDG-1",),
        admissions=(_admitted("JDG-1", AdmissionRoute.APPLY),),
    )

    decision = _route(_equivalent("JDG-2", reasoner=MODEL_B), state)

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("CONTRADICTS_ACTIVE_JUDGMENT:JDG-1",)


def test_distinct_routes_normally_once_contradicting_equivalent_is_superseded() -> None:
    state = _state(
        judgments=(_equivalent("JDG-1", reasoner=MODEL_A), _supersede("JDG-S", "JDG-1")),
        applied=("JDG-1", "JDG-S"),
        admissions=(
            _admitted("JDG-1", AdmissionRoute.APPLY),
            _admitted("JDG-S", AdmissionRoute.APPLY),
        ),
        supersessions=(_supersession("JDG-1", "JDG-S"),),
    )

    decision = _route(_distinct("JDG-2", reasoner=MODEL_B), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_contradiction_with_active_judgment_precedes_authority_rules() -> None:
    """Structural problems still come first; active contradiction beats everything after."""
    state = _active_equivalent_state(
        records=(_authority_record("AUTH-1", "human://alice", scope=()),)
    )

    decision = _route(_distinct("JDG-2", "ADDR-A", "ADDR-MISSING", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.REJECT
    assert all(reason.startswith("STRUCTURAL:") for reason in decision.reasons)


# --- structural rejection ---------------------------------------------------


def _assert_structural_reject(decision: AdmissionDecision) -> None:
    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons
    assert all(reason.startswith("STRUCTURAL:") for reason in decision.reasons)
    assert decision.corroborating_judgment_ids == ()


def test_missing_address_in_bind_is_rejected() -> None:
    _assert_structural_reject(_route(_bind("JDG-1", "ADDR-MISSING")))


def test_missing_address_in_equivalent_is_rejected() -> None:
    _assert_structural_reject(_route(_equivalent("JDG-1", "ADDR-A", "ADDR-MISSING")))


def test_missing_address_in_distinct_is_rejected() -> None:
    _assert_structural_reject(_route(_distinct("JDG-1", "ADDR-MISSING", "ADDR-B")))


def test_missing_address_in_assert_claim_is_rejected() -> None:
    _assert_structural_reject(_route(_assert_claim("JDG-1", "ADDR-MISSING")))


def test_missing_claim_in_conflicts_with_is_rejected() -> None:
    _assert_structural_reject(_route(_conflict("JDG-1", "CLAIM-1", "CLAIM-MISSING")))


def test_missing_claim_evidence_is_rejected() -> None:
    _assert_structural_reject(_route(_assert_claim("JDG-1", evidence_ids=("EV-MISSING",))))


def test_missing_visible_evidence_is_rejected() -> None:
    _assert_structural_reject(_route(_create("JDG-1", visible_evidence_ids=("EV-1", "EV-404"))))


def test_missing_candidate_evidence_is_rejected() -> None:
    proposal = CreateAddressProposal(candidate=_candidate(evidence_ids=("EV-404",)))

    _assert_structural_reject(_route(_judgment("JDG-1", proposal)))


def test_supersede_of_unknown_judgment_is_rejected() -> None:
    _assert_structural_reject(_route(_supersede("JDG-2", "JDG-MISSING")))


def test_supersede_of_recorded_but_unapplied_judgment_is_rejected() -> None:
    state = _state(judgments=(_equivalent("JDG-1"),), applied=())

    _assert_structural_reject(_route(_supersede("JDG-2", "JDG-1"), state))


def test_supersede_of_already_superseded_judgment_is_rejected() -> None:
    state = _state(
        judgments=(_equivalent("JDG-1"), _supersede("JDG-2", "JDG-1")),
        applied=("JDG-1", "JDG-2"),
        supersessions=(_supersession("JDG-1", "JDG-2"),),
    )

    _assert_structural_reject(_route(_supersede("JDG-3", "JDG-1"), state))


def test_already_applied_judgment_id_is_rejected() -> None:
    judgment = _create("JDG-1")
    state = _state(judgments=(judgment,), applied=("JDG-1",))

    _assert_structural_reject(_route(judgment, state))


def test_structural_rejection_precedes_authority_rules() -> None:
    judgment = _assert_claim(
        "JDG-1", "ADDR-MISSING", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE
    )
    state = _state(records=(_authority_record("AUTH-1", "human://alice"),))

    _assert_structural_reject(_route(judgment, state))


def test_structural_rejection_lists_every_missing_reference() -> None:
    decision = _route(_equivalent("JDG-1", "ADDR-X", "ADDR-Y"))

    _assert_structural_reject(decision)
    assert any("ADDR-X" in reason for reason in decision.reasons)
    assert any("ADDR-Y" in reason for reason in decision.reasons)


# --- confidence blindness ----------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda c: _equivalent("JDG-1", confidence=c),
        lambda c: _create("JDG-1", confidence=c),
        lambda c: _conflict("JDG-1", confidence=c),
        lambda c: _assert_claim(
            "JDG-1", authority=Authority.CANONICAL, reasoner=HUMAN_ALICE, confidence=c
        ),
    ],
    ids=["equivalent", "create", "conflict", "human-canonical-claim"],
)
def test_confidence_never_changes_the_route(
    build: Callable[[float | None], SemanticJudgment],
) -> None:
    confident = _route(build(1.0))
    silent = _route(build(None))
    doubtful = _route(build(0.0))

    assert confident == silent == doubtful


def test_admission_module_never_reads_confidence() -> None:
    import foundry.domain.admission as admission

    source = inspect.getsource(admission)
    docstring = ast.get_docstring(ast.parse(source), clean=False) or ""
    body = source.replace(docstring, "", 1)

    assert "confidence" not in body


# --- purity / determinism ------------------------------------------------------


def test_routing_is_deterministic_and_leaves_state_untouched() -> None:
    state = _state(judgments=(_equivalent("JDG-1", reasoner=MODEL_B),))
    before = state.model_dump(mode="json")
    judgment = _equivalent("JDG-2", reasoner=MODEL_A)

    first = route_judgment(state, judgment, AdmissionPolicy())
    second = route_judgment(state, judgment, AdmissionPolicy())

    assert first == second
    assert state.model_dump(mode="json") == before


# --- rebinding requires supersession (spec §4.5, §20.1, §21 #10) --------------------


def _bound_state(
    *,
    by_create: bool = False,
    superseded: bool = False,
    records: tuple[AuthorityRecord, ...] = (),
) -> IntentState:
    """CAND-1 bound to ADDR-A by an applied judgment JDG-b1 (BIND, or CREATE when
    ``by_create``); when ``superseded`` that binding judgment is no longer active."""
    binder = _create("JDG-b1") if by_create else _bind("JDG-b1", "ADDR-A")
    judgments: tuple[SemanticJudgment, ...] = (binder,)
    applied: tuple[str, ...] = ("JDG-b1",)
    supersessions: tuple[SupersessionRecord, ...] = ()
    if superseded:
        judgments += (_supersede("JDG-S", "JDG-b1", reasoner=MODEL_B),)
        applied += ("JDG-S",)
        supersessions = (_supersession("JDG-b1", "JDG-S"),)
    return _state(
        judgments=judgments, applied=applied, supersessions=supersessions, records=records
    )


REBIND_REASON = "STRUCTURAL: candidate CAND-1 already bound by JDG-b1; supersede it first"


def test_rebind_of_actively_bound_candidate_by_a_model_is_rejected() -> None:
    decision = _route(_bind("JDG-b2", "ADDR-B", reasoner=MODEL_A), _bound_state())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (REBIND_REASON,)
    assert decision.corroborating_judgment_ids == ()


def test_rebind_of_actively_bound_candidate_by_an_independent_model_is_rejected() -> None:
    decision = _route(_bind("JDG-b2", "ADDR-B", reasoner=MODEL_B), _bound_state())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (REBIND_REASON,)


def test_rebind_to_the_same_address_while_binding_is_active_is_rejected() -> None:
    decision = _route(_bind("JDG-b2", "ADDR-A", reasoner=MODEL_B), _bound_state())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (REBIND_REASON,)


def test_create_address_for_actively_bound_candidate_is_rejected() -> None:
    decision = _route(_create("JDG-b2", reasoner=MODEL_B), _bound_state())

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (REBIND_REASON,)


def test_rebind_over_an_active_create_address_binding_is_rejected() -> None:
    decision = _route(_bind("JDG-b2", "ADDR-B", reasoner=MODEL_B), _bound_state(by_create=True))

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (REBIND_REASON,)


def test_human_authority_cannot_rebind_without_superseding_first() -> None:
    state = _bound_state(records=(_authority_record("AUTH-1", "human://alice", scope=()),))

    decision = _route(_bind("JDG-b2", "ADDR-B", reasoner=HUMAN_ALICE), state)

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (REBIND_REASON,)


def test_rebind_routes_normally_once_original_binding_is_superseded() -> None:
    decision = _route(_bind("JDG-b2", "ADDR-B", reasoner=MODEL_A), _bound_state(superseded=True))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_create_address_routes_normally_once_original_binding_is_superseded() -> None:
    decision = _route(_create("JDG-b2", reasoner=MODEL_A), _bound_state(superseded=True))

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_recorded_but_unapplied_bind_does_not_block_a_binding() -> None:
    state = _state(judgments=(_bind("JDG-b1", "ADDR-A", reasoner=MODEL_B),), applied=())

    decision = _route(_bind("JDG-b2", "ADDR-B", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_binding_of_a_different_candidate_is_not_blocked() -> None:
    proposal = BindToAddressProposal(candidate=_candidate("CAND-2"), address_id="ADDR-B")

    decision = _route(_judgment("JDG-b2", proposal), _bound_state())

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


# --- CONFLICTS_WITH needs two live claims at one locus (spec §22.6, §22.7) ----------


CROSS_LOCUS_CLAIMS = (_claim("CLAIM-1", "ADDR-A"), _claim("CLAIM-2", "ADDR-B"))
NOT_ONE_LOCUS_REASON = "STRUCTURAL: claims CLAIM-1, CLAIM-2 are not live claims at one locus"


def test_cross_locus_conflict_with_independent_corroboration_is_rejected() -> None:
    state = _state(
        claims=CROSS_LOCUS_CLAIMS,
        judgments=(_conflict("JDG-1", "CLAIM-2", "CLAIM-1", reasoner=MODEL_B),),
    )

    decision = _route(_conflict("JDG-2", "CLAIM-1", "CLAIM-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (NOT_ONE_LOCUS_REASON,)
    assert decision.corroborating_judgment_ids == ()


def test_cross_locus_conflict_alone_is_rejected_not_held() -> None:
    decision = _route(_conflict("JDG-1"), _state(claims=CROSS_LOCUS_CLAIMS))

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (NOT_ONE_LOCUS_REASON,)


def test_conflict_routes_normally_once_an_equivalent_merges_the_loci() -> None:
    state = _state(
        claims=CROSS_LOCUS_CLAIMS,
        judgments=(
            _equivalent("JDG-eq", "ADDR-A", "ADDR-B", reasoner=MODEL_B),
            _conflict("JDG-1", "CLAIM-2", "CLAIM-1", reasoner=MODEL_B),
        ),
        applied=("JDG-eq",),
        admissions=(_admitted("JDG-eq", AdmissionRoute.APPLY),),
    )

    decision = _route(_conflict("JDG-2", "CLAIM-1", "CLAIM-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("INDEPENDENT_CORROBORATION",)
    assert decision.corroborating_judgment_ids == ("JDG-1",)


def test_conflict_alone_across_a_merged_locus_requires_second_lens() -> None:
    state = _state(
        claims=CROSS_LOCUS_CLAIMS,
        judgments=(_equivalent("JDG-eq", "ADDR-A", "ADDR-B"),),
        applied=("JDG-eq",),
    )

    decision = _route(_conflict("JDG-1"), state)

    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS


def test_conflict_naming_a_claim_whose_assertion_was_superseded_is_rejected() -> None:
    state = _state(
        judgments=(
            _supersede("JDG-S", "JDG-claim-CLAIM-2", reasoner=MODEL_B),
            _conflict("JDG-1", "CLAIM-1", "CLAIM-2", reasoner=MODEL_B),
        ),
        applied=("JDG-S",),
        supersessions=(_supersession("JDG-claim-CLAIM-2", "JDG-S"),),
    )

    decision = _route(_conflict("JDG-2", "CLAIM-1", "CLAIM-2", reasoner=MODEL_A), state)

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (NOT_ONE_LOCUS_REASON,)


def test_conflict_naming_a_claim_whose_assertion_was_never_applied_is_rejected() -> None:
    state = _state(dead_claims=("CLAIM-1",))

    decision = _route(_conflict("JDG-1"), state)

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == (NOT_ONE_LOCUS_REASON,)


def test_conflict_with_a_missing_claim_reports_only_the_missing_reference() -> None:
    decision = _route(_conflict("JDG-1", "CLAIM-1", "CLAIM-MISSING"))

    assert decision.route is AdmissionRoute.REJECT
    assert decision.reasons == ("STRUCTURAL: claim CLAIM-MISSING does not exist",)


# --- structural duplicate of a live claim (Option 3(a) backstop) --------------------
#
# Deterministic governance never judges semantic equivalence; that stays with the
# reasoner (SUPPORTS_CLAIM for a restatement). What it CAN refuse structurally is a
# proposition that is byte-for-byte the one a LIVE claim at the same address already
# carries: same address_id, predicate, structured value and authority — exactly the
# ``proposal_signature`` of the claim. Such an ASSERT_CLAIM never becomes a second
# live claim. A superseded (dead) claim is not live, so re-asserting its proposition
# — the revert shape — remains admissible.

DUPLICATE_REASON = (
    "STRUCTURAL: claim CLAIM-1 already asserts this proposition at ADDR-A; support it instead"
)


def _live_claim_shaped_assert(
    judgment_id: str = "JDG-dup",
    *,
    address_id: str = "ADDR-A",
    predicate: str = "retention_period",
    quantity: str = "7",
    authority: Authority = Authority.OBSERVED,
    **options: Unpack[JudgmentOptions],
) -> SemanticJudgment:
    """An ASSERT_CLAIM shaped like the fixture's live ``CLAIM-1`` unless overridden."""
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate=predicate,
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="year"),
            evidence_ids=("EV-1",),
            authority=authority,
        ),
        **options,
    )


def test_byte_identical_assert_of_a_live_claim_is_structurally_rejected() -> None:
    state = _state(claims=(_claim("CLAIM-1", "ADDR-A"),))

    decision = _route(_live_claim_shaped_assert(), state)

    _assert_structural_reject(decision)
    assert decision.reasons == (DUPLICATE_REASON,)


def test_duplicate_rejection_names_the_earliest_live_claim_only() -> None:
    """Two live identical claims (legacy state) still yield one deterministic reason."""
    decision = _route(_live_claim_shaped_assert())

    _assert_structural_reject(decision)
    assert decision.reasons == (DUPLICATE_REASON,)


def test_duplicate_rejection_applies_to_humans_too() -> None:
    state = _state(
        claims=(_claim("CLAIM-1", "ADDR-A"),),
        records=(_authority_record("AUTH-1", "human://alice", scope=()),),
    )

    decision = _route(_live_claim_shaped_assert(reasoner=HUMAN_ALICE), state)

    _assert_structural_reject(decision)
    assert decision.reasons == (DUPLICATE_REASON,)


def test_same_proposition_at_another_address_is_not_a_duplicate() -> None:
    state = _state(claims=(_claim("CLAIM-1", "ADDR-A"),))

    decision = _route(_live_claim_shaped_assert(address_id="ADDR-B"), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_same_predicate_with_a_different_value_is_a_correction_not_a_duplicate() -> None:
    state = _state(claims=(_claim("CLAIM-1", "ADDR-A"),))

    decision = _route(_live_claim_shaped_assert(quantity="9"), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_same_value_with_a_different_predicate_is_an_additional_claim() -> None:
    state = _state(claims=(_claim("CLAIM-1", "ADDR-A"),))

    decision = _route(_live_claim_shaped_assert(predicate="review_period"), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_same_proposition_with_a_different_authority_is_not_a_structural_duplicate() -> None:
    """Authority is part of the claim's structural identity: a different authority is a
    different proposition, and authority changes are governed elsewhere (rule 3 for
    CANONICAL), never silently folded into the duplicate rule."""
    state = _state(claims=(_claim("CLAIM-1", "ADDR-A"),))

    decision = _route(_live_claim_shaped_assert(authority=Authority.PROPOSED), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_reasserting_a_superseded_claims_proposition_is_admissible() -> None:
    """The revert shape: the historical proposition returns as a NEW claim; the dead
    claim object is never resurrected and never counts as a live duplicate."""
    state = _state(claims=(_claim("CLAIM-1", "ADDR-A"),), dead_claims=("CLAIM-1",))

    decision = _route(_live_claim_shaped_assert(), state)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("LOW_RISK",)


def test_duplicate_rule_is_documented_as_structural() -> None:
    import foundry.domain.admission as admission

    docstring = ast.get_docstring(ast.parse(inspect.getsource(admission)), clean=False) or ""

    assert "byte-for-byte" in docstring or "structurally identical" in docstring
    assert "support it instead" in docstring
