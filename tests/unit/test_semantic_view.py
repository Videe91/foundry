from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.derivation import DerivationEdge
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    IssueEpistemicState,
    SemanticAddress,
    SemanticCandidate,
    SemanticClaim,
)
from foundry.domain.semantic_judgment import (
    BindToAddressProposal,
    CreateAddressProposal,
    EquivalentProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_state import (
    ConflictRecord,
    EquivalenceRecord,
    SemanticState,
    SupersessionRecord,
)
from foundry.domain.semantic_view import (
    CurrentSemanticView,
    SemanticLocus,
    active_judgment_ids,
    derive_view,
)
from foundry.domain.state import IntentState

OCCURRED_AT = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4", policy_version="p1")


def _address(address_id: str, *, scope: tuple[str, ...] = ()) -> SemanticAddress:
    return SemanticAddress(
        address_id=address_id,
        project_id="PROJ-1",
        subject="audit records",
        facet="retention period",
        scope=scope,
        created_by_judgment_id=f"JDG-create-{address_id}",
    )


def _claim(
    claim_id: str, address_id: str, *, authority: Authority = Authority.OBSERVED
) -> SemanticClaim:
    return SemanticClaim(
        claim_id=claim_id,
        project_id="PROJ-1",
        address_id=address_id,
        predicate="retention_period",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
        evidence_ids=("EV-1",),
        authority=authority,
        provenance=Provenance(source_kind=SourceKind.SYSTEM, source_ref="xai:grok-4"),
        created_by_judgment_id=f"JDG-claim-{claim_id}",
    )


def _judgment(judgment_id: str, proposal: JudgmentProposal) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id="PROJ-1",
        proposal=proposal,
        visible_evidence_ids=("EV-1",),
        rationale="Both statements describe the same retention obligation.",
        reasoner=MODEL_A,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=OCCURRED_AT,
    )


def _sup(target: str, by: str) -> SupersessionRecord:
    return SupersessionRecord(
        target_judgment_id=target, superseding_judgment_id=by, recorded_by_event_id=f"EVT-{by}"
    )


def _equivalent(judgment_id: str, a: str, b: str) -> SemanticJudgment:
    return _judgment(judgment_id, EquivalentProposal(address_a=a, address_b=b))


def _candidate(candidate_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject="audit records",
        facet="retention period",
        evidence_ids=("EV-1",),
    )


def _create(judgment_id: str, candidate_id: str) -> SemanticJudgment:
    return _judgment(judgment_id, CreateAddressProposal(candidate=_candidate(candidate_id)))


def _bind(judgment_id: str, candidate_id: str, address_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(candidate=_candidate(candidate_id), address_id=address_id),
    )


def _supersede(judgment_id: str, target: str) -> SemanticJudgment:
    return _judgment(judgment_id, SupersedeProposal(target_judgment_id=target, reason="wrong"))


# --- models ---------------------------------------------------------------


def test_semantic_state_defaults_are_empty_and_frozen() -> None:
    state = SemanticState()

    assert isinstance(state.addresses, MappingProxyType)
    assert isinstance(state.issue_heads, MappingProxyType)
    assert state.applied_judgment_ids == ()
    assert state.equivalences == ()
    assert state.conflicts == ()
    assert state.derivations == ()
    with pytest.raises(TypeError):
        state.addresses["ADDR-1"] = _address("ADDR-1")  # type: ignore[index]


def test_semantic_state_mappings_serialize_as_dicts() -> None:
    state = SemanticState(addresses={"ADDR-1": _address("ADDR-1")})

    dumped = state.model_dump(mode="json")

    assert isinstance(dumped["addresses"], dict)
    assert dumped["addresses"]["ADDR-1"]["address_id"] == "ADDR-1"


def test_intent_state_carries_empty_semantic_state_by_default() -> None:
    state = IntentState(project_id="PROJ-1")

    assert state.semantic == SemanticState()


def test_derivation_edge_rejects_self_reference_and_empty_ids() -> None:
    edge = DerivationEdge(child_id="D-1", parent_id="JDG-1", recorded_by_event_id="EVT-1")
    assert edge.child_id == "D-1"
    with pytest.raises(ValidationError):
        DerivationEdge(child_id="D-1", parent_id="D-1", recorded_by_event_id="EVT-1")
    with pytest.raises(ValidationError):
        DerivationEdge(child_id="", parent_id="JDG-1", recorded_by_event_id="EVT-1")


def test_current_view_has_empty_stale_ids_placeholder() -> None:
    view = derive_view(SemanticState())

    assert isinstance(view, CurrentSemanticView)
    assert view.stale_ids == ()
    assert view.loci == ()


# --- active judgments -------------------------------------------------------


def test_active_judgment_ids_excludes_superseded() -> None:
    state = SemanticState(
        judgments={"J1": _equivalent("J1", "ADDR-1", "ADDR-2"), "J2": _supersede("J2", "J1")},
        applied_judgment_ids=("J1", "J2"),
        supersessions=(_sup("J1", "J2"),),
    )

    assert active_judgment_ids(state) == frozenset({"J2"})


def test_superseding_a_supersession_restores_its_target() -> None:
    state = SemanticState(
        judgments={
            "J1": _equivalent("J1", "ADDR-1", "ADDR-2"),
            "J2": _supersede("J2", "J1"),
            "J3": _supersede("J3", "J2"),
        },
        applied_judgment_ids=("J1", "J2", "J3"),
        supersessions=(_sup("J1", "J2"), _sup("J2", "J3")),
    )

    assert active_judgment_ids(state) == frozenset({"J1", "J3"})


def test_restored_target_can_be_superseded_again() -> None:
    state = SemanticState(
        judgments={
            "J1": _equivalent("J1", "ADDR-1", "ADDR-2"),
            "J2": _supersede("J2", "J1"),
            "J3": _supersede("J3", "J2"),
            "J4": _supersede("J4", "J1"),
        },
        applied_judgment_ids=("J1", "J2", "J3", "J4"),
        supersessions=(_sup("J1", "J2"), _sup("J2", "J3"), _sup("J1", "J4")),
    )

    assert active_judgment_ids(state) == frozenset({"J3", "J4"})
    assert len(state.judgments) == 4
    assert len(state.supersessions) == 3


def test_recorded_but_unapplied_judgment_is_not_active() -> None:
    state = SemanticState(judgments={"J1": _equivalent("J1", "ADDR-1", "ADDR-2")})

    assert active_judgment_ids(state) == frozenset()


# --- loci and representatives -----------------------------------------------


def test_singleton_addresses_each_form_a_locus_sorted_by_representative() -> None:
    state = SemanticState(addresses={"ADDR-b": _address("ADDR-b"), "ADDR-a": _address("ADDR-a")})

    view = derive_view(state)

    assert [locus.representative_id for locus in view.loci] == ["ADDR-a", "ADDR-b"]
    assert dict(view.representatives) == {"ADDR-a": "ADDR-a", "ADDR-b": "ADDR-b"}
    assert all(locus.epistemic_state is IssueEpistemicState.OPEN for locus in view.loci)


def test_representative_is_min_address_id_and_scope_is_union() -> None:
    state = SemanticState(
        addresses={
            "ADDR-z": _address("ADDR-z", scope=("billing",)),
            "ADDR-m": _address("ADDR-m", scope=("compliance",)),
            "ADDR-a": _address("ADDR-a", scope=("compliance", "audit")),
        },
        judgments={
            "J1": _equivalent("J1", "ADDR-z", "ADDR-m"),
            "J2": _equivalent("J2", "ADDR-m", "ADDR-a"),
        },
        applied_judgment_ids=("J1", "J2"),
        equivalences=(
            EquivalenceRecord(judgment_id="J1", address_a="ADDR-z", address_b="ADDR-m"),
            EquivalenceRecord(judgment_id="J2", address_a="ADDR-m", address_b="ADDR-a"),
        ),
    )

    view = derive_view(state)

    assert len(view.loci) == 1
    locus = view.loci[0]
    assert isinstance(locus, SemanticLocus)
    assert locus.representative_id == "ADDR-a"
    assert locus.address_ids == ("ADDR-a", "ADDR-m", "ADDR-z")
    assert locus.scope == ("audit", "billing", "compliance")
    assert view.representatives["ADDR-z"] == "ADDR-a"
    assert view.active_equivalence_judgment_ids == ("J1", "J2")


def test_superseded_equivalence_is_ignored_by_union_find() -> None:
    state = SemanticState(
        addresses={"ADDR-1": _address("ADDR-1"), "ADDR-2": _address("ADDR-2")},
        judgments={"J1": _equivalent("J1", "ADDR-1", "ADDR-2"), "J2": _supersede("J2", "J1")},
        applied_judgment_ids=("J1", "J2"),
        supersessions=(_sup("J1", "J2"),),
        equivalences=(EquivalenceRecord(judgment_id="J1", address_a="ADDR-1", address_b="ADDR-2"),),
    )

    view = derive_view(state)

    assert len(view.loci) == 2
    assert view.active_equivalence_judgment_ids == ()


# --- epistemic rules ---------------------------------------------------------


def _one_locus_state(
    claims: dict[str, SemanticClaim],
    *,
    conflicts: tuple[ConflictRecord, ...] = (),
    applied: tuple[str, ...] = (),
    supersessions: tuple[SupersessionRecord, ...] = (),
) -> SemanticState:
    judgments = {jid: _equivalent(jid, "ADDR-x", "ADDR-y") for jid in applied}
    claim_judgments = tuple(claim.created_by_judgment_id for claim in claims.values())
    return SemanticState(
        addresses={"ADDR-1": _address("ADDR-1")},
        claims=claims,
        judgments=judgments,
        applied_judgment_ids=(*claim_judgments, *applied),
        supersessions=supersessions,
        conflicts=conflicts,
    )


def test_no_claims_is_open() -> None:
    view = derive_view(_one_locus_state({}))

    assert view.loci[0].epistemic_state is IssueEpistemicState.OPEN
    assert view.loci[0].claim_ids == ()


def test_claims_without_authority_is_claimed() -> None:
    view = derive_view(_one_locus_state({"C-1": _claim("C-1", "ADDR-1")}))

    assert view.loci[0].epistemic_state is IssueEpistemicState.CLAIMED
    assert view.loci[0].claim_ids == ("C-1",)


def test_canonical_claim_is_settled() -> None:
    view = derive_view(
        _one_locus_state(
            {
                "C-1": _claim("C-1", "ADDR-1"),
                "C-2": _claim("C-2", "ADDR-1", authority=Authority.CANONICAL),
            }
        )
    )

    assert view.loci[0].epistemic_state is IssueEpistemicState.SETTLED


def test_active_conflict_is_disputed_and_beats_canonical() -> None:
    state = _one_locus_state(
        {
            "C-1": _claim("C-1", "ADDR-1"),
            "C-2": _claim("C-2", "ADDR-1", authority=Authority.CANONICAL),
        },
        conflicts=(ConflictRecord(judgment_id="J-conf", claim_a="C-2", claim_b="C-1"),),
        applied=("J-conf",),
    )

    view = derive_view(state)

    assert view.loci[0].epistemic_state is IssueEpistemicState.DISPUTED
    assert view.loci[0].disputed_claim_pairs == (("C-1", "C-2"),)
    assert view.active_conflict_judgment_ids == ("J-conf",)


def test_superseded_conflict_no_longer_disputes() -> None:
    state = _one_locus_state(
        {"C-1": _claim("C-1", "ADDR-1"), "C-2": _claim("C-2", "ADDR-1")},
        conflicts=(ConflictRecord(judgment_id="J-conf", claim_a="C-1", claim_b="C-2"),),
        applied=("J-conf", "J-sup"),
        supersessions=(_sup("J-conf", "J-sup"),),
    )

    view = derive_view(state)

    assert view.loci[0].epistemic_state is IssueEpistemicState.CLAIMED
    assert view.loci[0].disputed_claim_pairs == ()
    assert view.active_conflict_judgment_ids == ()


def test_conflict_across_a_merged_locus_disputes_the_locus() -> None:
    state = SemanticState(
        addresses={"ADDR-1": _address("ADDR-1"), "ADDR-2": _address("ADDR-2")},
        claims={"C-1": _claim("C-1", "ADDR-1"), "C-2": _claim("C-2", "ADDR-2")},
        judgments={"J-eq": _equivalent("J-eq", "ADDR-1", "ADDR-2")},
        applied_judgment_ids=("JDG-claim-C-1", "JDG-claim-C-2", "J-eq", "J-conf"),
        equivalences=(
            EquivalenceRecord(judgment_id="J-eq", address_a="ADDR-1", address_b="ADDR-2"),
        ),
        conflicts=(ConflictRecord(judgment_id="J-conf", claim_a="C-1", claim_b="C-2"),),
    )

    view = derive_view(state)

    assert len(view.loci) == 1
    assert view.loci[0].claim_ids == ("C-1", "C-2")
    assert view.loci[0].epistemic_state is IssueEpistemicState.DISPUTED


# --- supersession ends every judgment's effect on the view -------------------


def test_claim_from_unapplied_judgment_is_not_in_view() -> None:
    state = SemanticState(
        addresses={"ADDR-1": _address("ADDR-1")},
        claims={"C-1": _claim("C-1", "ADDR-1")},
    )

    view = derive_view(state)

    assert view.loci[0].claim_ids == ()
    assert view.loci[0].epistemic_state is IssueEpistemicState.OPEN


def test_superseded_claim_judgment_removes_claim_from_view_but_not_from_state() -> None:
    state = _one_locus_state(
        {
            "C-1": _claim("C-1", "ADDR-1"),
            "C-2": _claim("C-2", "ADDR-1", authority=Authority.CANONICAL),
        },
        applied=("J-sup",),
        supersessions=(_sup("JDG-claim-C-2", "J-sup"),),
    )

    view = derive_view(state)

    assert view.loci[0].claim_ids == ("C-1",)
    assert view.loci[0].epistemic_state is IssueEpistemicState.CLAIMED
    assert set(state.claims) == {"C-1", "C-2"}


def test_superseding_only_claim_reopens_locus() -> None:
    state = _one_locus_state(
        {"C-2": _claim("C-2", "ADDR-1", authority=Authority.CANONICAL)},
        applied=("J-sup",),
        supersessions=(_sup("JDG-claim-C-2", "J-sup"),),
    )

    view = derive_view(state)

    assert view.loci[0].claim_ids == ()
    assert view.loci[0].epistemic_state is IssueEpistemicState.OPEN


def test_active_bindings_follow_active_binding_judgments() -> None:
    state = SemanticState(
        addresses={
            "ADDR-1": SemanticAddress(
                address_id="ADDR-1",
                project_id="PROJ-1",
                subject="audit records",
                facet="retention period",
                created_by_judgment_id="J-create",
            )
        },
        judgments={
            "J-create": _create("J-create", "CAND-1"),
            "J-bind": _bind("J-bind", "CAND-2", "ADDR-1"),
            "J-bind-old": _bind("J-bind-old", "CAND-3", "ADDR-1"),
            "J-sup": _supersede("J-sup", "J-bind-old"),
        },
        applied_judgment_ids=("J-create", "J-bind", "J-bind-old", "J-sup"),
        supersessions=(_sup("J-bind-old", "J-sup"),),
        bindings={"CAND-1": "ADDR-1", "CAND-2": "ADDR-1", "CAND-3": "ADDR-1"},
    )

    view = derive_view(state)

    assert dict(view.active_bindings) == {"CAND-1": "ADDR-1", "CAND-2": "ADDR-1"}
    assert dict(state.bindings) == {"CAND-1": "ADDR-1", "CAND-2": "ADDR-1", "CAND-3": "ADDR-1"}


def test_superseded_create_address_keeps_address_but_deactivates_binding() -> None:
    state = SemanticState(
        addresses={
            "ADDR-1": SemanticAddress(
                address_id="ADDR-1",
                project_id="PROJ-1",
                subject="audit records",
                facet="retention period",
                created_by_judgment_id="J-create",
            )
        },
        judgments={
            "J-create": _create("J-create", "CAND-1"),
            "J-sup": _supersede("J-sup", "J-create"),
        },
        applied_judgment_ids=("J-create", "J-sup"),
        supersessions=(_sup("J-create", "J-sup"),),
        bindings={"CAND-1": "ADDR-1"},
    )

    view = derive_view(state)

    assert dict(view.representatives) == {"ADDR-1": "ADDR-1"}
    assert len(view.loci) == 1
    assert dict(view.active_bindings) == {}
    assert "ADDR-1" in state.addresses


def test_derive_view_is_deterministic_for_equal_states() -> None:
    def build() -> SemanticState:
        return _one_locus_state({"C-1": _claim("C-1", "ADDR-1")})

    assert derive_view(build()) == derive_view(build())
