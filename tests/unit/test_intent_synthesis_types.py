"""T1 — Intent Synthesis vocabulary and durable identity.

Covers the Slice-1 T1 contract of
``docs/superpowers/plans/2026-09-22-intent-synthesis-slice-1.md``:
the proposal vocabulary, the runtime-owned durable identity law (spec §9.4, I21),
and the C17 boundary that the model-facing schema can never express authority.

Nothing here exercises routing, state, events, reduction, context assembly,
orchestration, recovery or handoff; those are T2+.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from foundry.domain.common import Materiality
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisDecision,
    IntentSynthesisPolicy,
    IntentSynthesisProposal,
    IntentSynthesisResult,
    IntentSynthesisRoute,
    InvalidationReason,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
)
from foundry.domain.semantic import SemanticKind

PROJECT = "PROJ-A"
RUN = "RUN-1"


def _proposal(
    *,
    model_proposal_id: str = "p1",
    disposition: IntentDisposition = IntentDisposition.NEW,
    statement: str = "Revocation is immediate and irreversible by the client.",
    rationale: str = "Stated by the credential owner.",
    basis_claim_ids: tuple[str, ...] = ("CLAIM-1",),
    relates_to_object_id: str | None = None,
    confidence: float | None = None,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=model_proposal_id,
        disposition=disposition,
        statement=statement,
        rationale=rationale,
        basis_claim_ids=basis_claim_ids,
        relates_to_object_id=relates_to_object_id,
        confidence=confidence,
    )


def _identity(
    *,
    project_id: str = PROJECT,
    synthesis_run_id: str = RUN,
    model_proposal_id: str = "p1",
) -> SynthesisIdentity:
    return SynthesisIdentity(
        project_id=project_id,
        synthesis_run_id=synthesis_run_id,
        model_proposal_id=model_proposal_id,
    )


# --- enums ---------------------------------------------------------------------------


def test_the_four_synthesis_enums_carry_exactly_the_specified_members() -> None:
    assert {member.value for member in SynthesisOrigin} == {
        "HUMAN_STATED",
        "DETERMINISTIC_NORMALIZATION",
        "AI_INFERRED",
        "RESEARCH_DERIVED",
    }
    assert {member.value for member in IntentDisposition} == {
        "NEW",
        "EXISTING_UNCHANGED",
        "REPLACES_STALE",
    }
    assert {member.value for member in IntentSynthesisRoute} == {
        "APPLY",
        "NO_CHANGE",
        "REQUIRE_SECOND_LENS",
        "REQUIRE_HUMAN",
        "REJECT",
    }
    assert {member.value for member in InvalidationReason} == {
        "BASIS_CHANGED",
        "TARGET_CHANGED",
        "AUTHORITY_CHANGED",
    }


def test_route_vocabulary_is_distinct_from_the_semantic_admission_route() -> None:
    """Altitude separation (I14): synthesis never reuses AdmissionRoute."""
    from foundry.domain.semantic_judgment import AdmissionRoute

    assert IntentSynthesisRoute.__name__ != AdmissionRoute.__name__
    assert "NO_CHANGE" not in {member.value for member in AdmissionRoute}
    assert {m.value for m in IntentSynthesisRoute} != {m.value for m in AdmissionRoute}


# --- the only Slice-1 variant (C5) ----------------------------------------------------


def test_requirement_is_the_only_slice_one_proposal_variant() -> None:
    proposal = _proposal()
    assert isinstance(proposal, IntentSynthesisProposal)
    assert proposal.target_kind is SemanticKind.REQUIREMENT


def test_requirement_target_kind_is_fixed_and_cannot_be_overridden() -> None:
    with pytest.raises(ValidationError):
        RequirementSynthesisProposal.model_validate(
            {
                "model_proposal_id": "p1",
                "target_kind": SemanticKind.CONSTRAINT,
                "disposition": IntentDisposition.NEW,
                "statement": "s",
                "rationale": "r",
                "basis_claim_ids": ("CLAIM-1",),
            }
        )


def test_a_result_accepts_only_requirement_proposals() -> None:
    base = IntentSynthesisProposal(
        model_proposal_id="p1",
        target_kind=SemanticKind.CONSTRAINT,
        disposition=IntentDisposition.NEW,
        statement="s",
        rationale="r",
        basis_claim_ids=("CLAIM-1",),
    )
    with pytest.raises(ValidationError):
        IntentSynthesisResult.model_validate({"proposals": (base,)})


# --- runtime-owned fields are unexpressible (§9.2, C17) -------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authority", "CANONICAL"),
        ("author", "human://alice"),
        ("basis_locus_ids", ("ADDR-1",)),
        ("scope", ("keyring",)),
        ("object_id", "REQ-1"),
        ("provenance", {"source_kind": "HUMAN", "source_ref": "human://alice"}),
        ("materiality", Materiality.LOW),
        ("project_id", PROJECT),
        ("proposal_instance_id", "SYN-1"),
        ("synthesis_run_id", RUN),
        ("requires_metric", False),
        ("requires_verification", False),
        ("lifecycle", "ACTIVE"),
        ("revision", 1),
    ],
)
def test_the_model_facing_schema_cannot_express_a_runtime_owned_field(
    field: str, value: object
) -> None:
    """Runtime owns every one of these (spec §9.2). ``extra='forbid'`` is the enforcement."""
    payload: dict[str, object] = {
        "model_proposal_id": "p1",
        "disposition": IntentDisposition.NEW,
        "statement": "s",
        "rationale": "r",
        "basis_claim_ids": ("CLAIM-1",),
        field: value,
    }
    with pytest.raises(ValidationError):
        RequirementSynthesisProposal.model_validate(payload)


def test_authority_stays_unexpressible_so_the_c17_boundary_is_not_weakened() -> None:
    """C17: no authority field may be added to the proposal for test convenience."""
    assert "authority" not in RequirementSynthesisProposal.model_fields
    assert "author" not in RequirementSynthesisProposal.model_fields
    assert "authority" not in IntentSynthesisProposal.model_fields


# --- basis ----------------------------------------------------------------------------


def test_a_proposal_requires_at_least_one_basis_claim() -> None:
    with pytest.raises(ValidationError):
        _proposal(basis_claim_ids=())


def test_a_proposal_is_frozen() -> None:
    proposal = _proposal()
    with pytest.raises(ValidationError):
        proposal.statement = "mutated"


# --- disposition legality matrix, structural half (§9.3) ------------------------------


def test_new_must_not_name_a_related_object() -> None:
    with pytest.raises(ValidationError):
        _proposal(disposition=IntentDisposition.NEW, relates_to_object_id="REQ-1")


@pytest.mark.parametrize(
    "disposition",
    [IntentDisposition.EXISTING_UNCHANGED, IntentDisposition.REPLACES_STALE],
)
def test_a_non_new_disposition_must_name_a_related_object(
    disposition: IntentDisposition,
) -> None:
    with pytest.raises(ValidationError):
        _proposal(disposition=disposition, relates_to_object_id=None)


@pytest.mark.parametrize(
    "disposition",
    [IntentDisposition.EXISTING_UNCHANGED, IntentDisposition.REPLACES_STALE],
)
def test_a_non_new_disposition_is_accepted_with_a_related_object(
    disposition: IntentDisposition,
) -> None:
    proposal = _proposal(disposition=disposition, relates_to_object_id="REQ-1")
    assert proposal.relates_to_object_id == "REQ-1"


# --- durable identity (spec §9.4, I21) ------------------------------------------------


def test_the_same_model_id_in_two_projects_yields_different_durable_ids() -> None:
    a = _identity(project_id="PROJ-A")
    b = _identity(project_id="PROJ-B")
    assert a.proposal_instance_id != b.proposal_instance_id
    assert a.object_id("REQ") != b.object_id("REQ")
    assert a.event_id("DECIDED") != b.event_id("DECIDED")


def test_the_same_model_id_in_two_runs_of_one_project_yields_different_durable_ids() -> None:
    a = _identity(synthesis_run_id="RUN-1")
    b = _identity(synthesis_run_id="RUN-2")
    assert a.proposal_instance_id != b.proposal_instance_id
    assert a.object_id("REQ") != b.object_id("REQ")
    assert a.event_id("DECIDED") != b.event_id("DECIDED")


def test_the_same_triple_reproduces_byte_identical_durable_identity() -> None:
    """Recovery determinism: an interrupted run recomputes the same ids."""
    a = _identity()
    b = _identity()
    assert a.proposal_instance_id == b.proposal_instance_id
    assert a.object_id("REQ") == b.object_id("REQ")
    assert a.event_id("DECIDED") == b.event_id("DECIDED")
    assert a.event_id("SYNTHESIZED") == b.event_id("SYNTHESIZED")


def test_distinct_steps_yield_distinct_event_ids() -> None:
    identity = _identity()
    step_ids = {identity.event_id(step) for step in ("DECIDED", "SYNTHESIZED", "INVALIDATED")}
    assert len(step_ids) == 3


def test_object_and_event_ids_are_distinct_from_the_proposal_instance_id() -> None:
    identity = _identity()
    assert identity.object_id("REQ") != identity.proposal_instance_id
    assert identity.event_id("DECIDED") != identity.proposal_instance_id
    assert identity.object_id("REQ") != identity.event_id("DECIDED")


def test_no_durable_id_is_derived_solely_from_the_raw_model_proposal_id() -> None:
    """I21 negative control: the raw model id never appears in, nor determines, a durable id."""
    identity = _identity(model_proposal_id="p1")
    for durable in (
        identity.proposal_instance_id,
        identity.object_id("REQ"),
        identity.event_id("DECIDED"),
    ):
        assert "p1" not in durable.removeprefix("REQ-").removeprefix("SYN-").removeprefix("EVT-")


def test_separator_injection_in_the_untrusted_model_id_cannot_forge_a_collision() -> None:
    """The model id is untrusted; a naive ``a|b`` join would let it collide across fields."""
    a = SynthesisIdentity(project_id="P", synthesis_run_id="R", model_proposal_id="X|Y")
    b = SynthesisIdentity(project_id="P", synthesis_run_id="R|X", model_proposal_id="Y")
    c = SynthesisIdentity(project_id="P|R", synthesis_run_id="X", model_proposal_id="Y")
    assert len({a.proposal_instance_id, b.proposal_instance_id, c.proposal_instance_id}) == 3


def test_identity_is_frozen_and_requires_every_component() -> None:
    identity = _identity()
    with pytest.raises(ValidationError):
        identity.project_id = "PROJ-B"
    for missing in ("project_id", "synthesis_run_id", "model_proposal_id"):
        components: dict[str, object] = {
            "project_id": PROJECT,
            "synthesis_run_id": RUN,
            "model_proposal_id": "p1",
        }
        components[missing] = ""
        with pytest.raises(ValidationError):
            SynthesisIdentity.model_validate(components)


# --- result: duplicate model ids within one batch -------------------------------------


def test_duplicate_model_proposal_ids_within_one_result_are_a_structural_failure() -> None:
    """Two proposals sharing a model id would derive one durable identity (§9.4)."""
    with pytest.raises(ValidationError):
        IntentSynthesisResult(
            proposals=(_proposal(model_proposal_id="p1"), _proposal(model_proposal_id="p1"))
        )


def test_distinct_model_proposal_ids_within_one_result_are_accepted() -> None:
    result = IntentSynthesisResult(
        proposals=(_proposal(model_proposal_id="p1"), _proposal(model_proposal_id="p2"))
    )
    assert len(result.proposals) == 2


def test_an_empty_result_is_legal() -> None:
    result = IntentSynthesisResult()
    assert result.proposals == ()
    assert result.gap_proposals == ()


# --- policy and decision ---------------------------------------------------------------


def test_the_slice_one_policy_default_is_the_conservative_pinning() -> None:
    """Spec §17.4: no kind and no materiality level is material in Slice 1."""
    policy = IntentSynthesisPolicy()
    assert policy.material_target_kinds == frozenset()
    assert policy.material_materiality_levels == frozenset()
    assert policy.canonical_requires_authority is True


def test_a_decision_records_a_route_and_at_least_one_reason() -> None:
    decision = IntentSynthesisDecision(
        proposal_instance_id="SYN-1",
        route=IntentSynthesisRoute.APPLY,
        reasons=("HUMAN_AUTHORITY",),
    )
    assert decision.route is IntentSynthesisRoute.APPLY
    assert decision.corroborating_proposal_instance_ids == ()
    with pytest.raises(ValidationError):
        IntentSynthesisDecision(
            proposal_instance_id="SYN-1", route=IntentSynthesisRoute.APPLY, reasons=()
        )
