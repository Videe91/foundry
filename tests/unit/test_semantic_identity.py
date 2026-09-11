import inspect
from decimal import Decimal

import pytest
from pydantic import ValidationError

import foundry.domain.semantic_identity as semantic_identity
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    IssueEpistemicState,
    SemanticAddress,
    SemanticCandidate,
    SemanticClaim,
    SemanticIssueVersion,
)


def _provenance() -> Provenance:
    return Provenance(
        source_kind=SourceKind.DOCUMENT,
        source_ref="doc://compliance/retention.md#L4",
        source_event_ids=("EVT-1",),
    )


def _address(address_id: str) -> SemanticAddress:
    return SemanticAddress(
        address_id=address_id,
        project_id="PROJ-1",
        subject="audit records",
        facet="retention period",
        scope=("compliance",),
        created_by_judgment_id="JDG-1",
    )


def _claim(*, evidence_ids: tuple[str, ...]) -> SemanticClaim:
    return SemanticClaim(
        claim_id="CLM-1",
        project_id="PROJ-1",
        address_id="ADDR-1",
        predicate="at_least",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year"),
        evidence_ids=evidence_ids,
        authority=Authority.PROPOSED,
        provenance=_provenance(),
        created_by_judgment_id="JDG-1",
    )


# --- SemanticAddress -----------------------------------------------------------


def test_semantic_address_round_trip_and_defaults() -> None:
    address = SemanticAddress(
        address_id="ADDR-1",
        project_id="PROJ-1",
        subject="audit records",
        facet="retention period",
        created_by_judgment_id="JDG-1",
    )

    assert address.scope == ()
    assert address.descriptor_version == 1
    assert SemanticAddress.model_validate(address.model_dump(mode="json")) == address


def test_semantic_address_descriptor_version_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        SemanticAddress(
            address_id="ADDR-1",
            project_id="PROJ-1",
            subject="audit records",
            facet="retention period",
            descriptor_version=0,
            created_by_judgment_id="JDG-1",
        )


def test_semantic_address_is_immutable() -> None:
    address = _address("ADDR-1")
    with pytest.raises(ValidationError):
        address.subject = "something else"


def test_a_identical_descriptors_with_different_ids_are_distinct_addresses() -> None:
    left = _address("ADDR-17")
    right = _address("ADDR-42")

    assert (left.subject, left.facet, left.scope) == (right.subject, right.facet, right.scope)
    assert left != right
    assert left.address_id != right.address_id
    assert left == _address("ADDR-17")


def _takes_two_of(callable_obj: object, model_type: type) -> bool:
    try:
        signature = inspect.signature(callable_obj)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    matching = 0
    for parameter in signature.parameters.values():
        annotation = parameter.annotation
        if annotation is model_type or annotation == model_type.__name__:
            matching += 1
    return matching >= 2


def test_a_module_exposes_no_descriptor_equality_helper() -> None:
    public_callables = [
        member
        for name, member in inspect.getmembers(semantic_identity)
        if not name.startswith("_") and callable(member) and not inspect.isclass(member)
    ]
    for model_type in (SemanticAddress, SemanticCandidate):
        for member in public_callables:
            assert not _takes_two_of(member, model_type), (
                f"{member} accepts two {model_type.__name__} parameters; "
                "deterministic code may not judge semantic sameness"
            )
        for name, method in inspect.getmembers(model_type, callable):
            if name.startswith("_"):
                continue
            assert not _takes_two_of(method, model_type), (
                f"{model_type.__name__}.{name} accepts two {model_type.__name__} parameters"
            )


def test_a_module_docstring_states_identity_law() -> None:
    docstring = semantic_identity.__doc__ or ""
    assert "address_id" in docstring
    assert "descriptor" in docstring.lower()
    assert "admitted" in docstring.lower()


# --- ClaimValue --------------------------------------------------------------


def test_claim_value_quantity_with_unit_is_valid() -> None:
    value = ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="year")
    assert value.quantity == Decimal("7")
    assert value.unit == "year"
    assert value.text is None


def test_claim_value_quantity_without_unit_is_valid() -> None:
    value = ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("3"))
    assert value.unit is None


def test_claim_value_quantity_requires_quantity() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.QUANTITY)


def test_claim_value_quantity_rejects_text() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), text="seven")


def test_claim_value_text_is_valid() -> None:
    value = ClaimValue(kind=ClaimValueKind.TEXT, text="encrypted at rest")
    assert value.text == "encrypted at rest"
    assert value.quantity is None


def test_claim_value_text_requires_text() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.TEXT)


def test_claim_value_text_rejects_quantity() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.TEXT, text="seven", quantity=Decimal("7"))


def test_claim_value_text_rejects_unit() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.TEXT, text="seven", unit="year")


def test_claim_value_enumeration_is_valid() -> None:
    value = ClaimValue(kind=ClaimValueKind.ENUMERATION, text="AES-256")
    assert value.text == "AES-256"


def test_claim_value_enumeration_requires_text() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.ENUMERATION)


def test_claim_value_enumeration_rejects_quantity() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.ENUMERATION, text="AES-256", quantity=Decimal("256"))


def test_claim_value_enumeration_rejects_unit() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.ENUMERATION, text="AES-256", unit="bit")


def test_claim_value_undecided_is_valid() -> None:
    value = ClaimValue(kind=ClaimValueKind.UNDECIDED)
    assert value.text is None
    assert value.quantity is None
    assert value.unit is None


def test_claim_value_undecided_rejects_text() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.UNDECIDED, text="tbd")


def test_claim_value_undecided_rejects_quantity() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.UNDECIDED, quantity=Decimal("1"))


def test_claim_value_undecided_rejects_unit() -> None:
    with pytest.raises(ValidationError):
        ClaimValue(kind=ClaimValueKind.UNDECIDED, unit="year")


def test_claim_value_quantity_is_decimal_after_json_round_trip() -> None:
    value = ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7.5"), unit="year")
    restored = ClaimValue.model_validate(value.model_dump(mode="json"))
    assert restored == value
    assert isinstance(restored.quantity, Decimal)


# --- SemanticClaim -------------------------------------------------------------


def test_semantic_claim_round_trip() -> None:
    claim = _claim(evidence_ids=("EVT-1", "EVT-2"))
    assert claim.evidence_ids == ("EVT-1", "EVT-2")
    assert claim.authority is Authority.PROPOSED
    assert SemanticClaim.model_validate(claim.model_dump(mode="json")) == claim


def test_semantic_claim_requires_at_least_one_evidence_id() -> None:
    with pytest.raises(ValidationError):
        _claim(evidence_ids=())


def test_semantic_claim_requires_provenance_and_authority() -> None:
    with pytest.raises(ValidationError):
        SemanticClaim.model_validate(
            {
                "claim_id": "CLM-1",
                "project_id": "PROJ-1",
                "address_id": "ADDR-1",
                "predicate": "at_least",
                "value": {"kind": "UNDECIDED"},
                "evidence_ids": ["EVT-1"],
                "created_by_judgment_id": "JDG-1",
            }
        )


def test_semantic_claim_has_no_confidence_field() -> None:
    assert "confidence" not in SemanticClaim.model_fields


# --- SemanticCandidate ---------------------------------------------------------


def test_semantic_candidate_round_trip_and_defaults() -> None:
    candidate = SemanticCandidate(
        candidate_id="CAND-1",
        subject="audit records",
        facet="retention period",
        evidence_ids=("EVT-1",),
    )
    assert candidate.scope == ()
    assert SemanticCandidate.model_validate(candidate.model_dump(mode="json")) == candidate


def test_semantic_candidate_requires_at_least_one_evidence_id() -> None:
    with pytest.raises(ValidationError):
        SemanticCandidate(
            candidate_id="CAND-1",
            subject="audit records",
            facet="retention period",
            evidence_ids=(),
        )


def test_semantic_candidate_carries_no_address_id() -> None:
    assert "address_id" not in SemanticCandidate.model_fields


# --- SemanticIssueVersion ------------------------------------------------------


def test_issue_epistemic_state_values() -> None:
    assert {state.value for state in IssueEpistemicState} == {
        "OPEN",
        "CLAIMED",
        "DISPUTED",
        "SETTLED",
    }


def test_semantic_issue_version_round_trip() -> None:
    version = SemanticIssueVersion(
        version_id="VER-2",
        project_id="PROJ-1",
        address_id="ADDR-1",
        claim_ids=("CLM-1", "CLM-2"),
        epistemic_state=IssueEpistemicState.DISPUTED,
        equivalent_address_ids=("ADDR-42",),
        supersedes_version_id="VER-1",
        created_by_event_id="EVT-9",
        created_by_judgment_id="J-9",
    )
    restored = SemanticIssueVersion.model_validate(version.model_dump(mode="json"))
    assert restored == version
    assert restored.epistemic_state is IssueEpistemicState.DISPUTED
    assert restored.supersedes_version_id == "VER-1"
    assert restored.created_by_judgment_id == "J-9"


def test_semantic_issue_version_allows_empty_claims_and_no_predecessor() -> None:
    version = SemanticIssueVersion(
        version_id="VER-1",
        project_id="PROJ-1",
        address_id="ADDR-1",
        claim_ids=(),
        epistemic_state=IssueEpistemicState.OPEN,
        equivalent_address_ids=(),
        supersedes_version_id=None,
        created_by_event_id="EVT-1",
        created_by_judgment_id="J-1",
    )
    assert version.claim_ids == ()
    assert version.supersedes_version_id is None


def test_semantic_issue_version_requires_creating_judgment() -> None:
    base = {
        "version_id": "VER-1",
        "project_id": "PROJ-1",
        "address_id": "ADDR-1",
        "claim_ids": [],
        "epistemic_state": "OPEN",
        "equivalent_address_ids": [],
        "supersedes_version_id": None,
        "created_by_event_id": "EVT-1",
    }
    with pytest.raises(ValidationError):
        SemanticIssueVersion.model_validate(base)
    with pytest.raises(ValidationError):
        SemanticIssueVersion.model_validate({**base, "created_by_judgment_id": ""})


def test_semantic_issue_version_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SemanticIssueVersion.model_validate(
            {
                "version_id": "VER-1",
                "project_id": "PROJ-1",
                "address_id": "ADDR-1",
                "claim_ids": [],
                "epistemic_state": "OPEN",
                "equivalent_address_ids": [],
                "supersedes_version_id": None,
                "created_by_event_id": "EVT-1",
                "created_by_judgment_id": "J-1",
                "materiality": "HIGH",
            }
        )
