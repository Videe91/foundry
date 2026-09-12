"""Task 9P-C-R3: the model-facing claim-value contract must not advertise a shape the
durable ``ClaimValue`` contract declares illegal (MODEL_CONTRACT_MISMATCH).

Forensic root cause: in the first live run Grok returned an ``UNDECIDED`` value carrying
``text``. The model-facing ``ClaimValueDraft`` accepted it; durable ``ClaimValue`` refused
it. Foundry correctly refused the batch, but it had advertised a contradictory contract.

Every test here is pure schema/contract work. ZERO live calls, no client construction.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Any, Literal

import pytest
from pydantic import Field, ValidationError

from foundry.adapters.semantics import xai_reasoner as mod
from foundry.adapters.semantics.xai_reasoner import (
    AssertClaimDraft,
    EnumerationClaimValueDraft,
    QuantityClaimValueDraft,
    SemanticDraftPayload,
    TextClaimValueDraft,
    UndecidedClaimValueDraft,
    semantic_output_schema_sha256,
)
from foundry.domain.common import FrozenModel
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind
from foundry.domain.semantic_judgment import (
    ConflictsWithProposal,
    DistinctProposal,
    EquivalentProposal,
)

# The exact value object returned by the model in the first live run (verbatim).
OFFENDING_LIVE_VALUE: dict[str, Any] = {
    "kind": "UNDECIDED",
    "quantity": None,
    "text": (
        "blocked choice between a cleaner single-pass output experiment and the "
        "lifecycle experiment in section 25"
    ),
    "unit": None,
}


def _assert_claim_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "drafts": [
            {
                "kind": "ASSERT_CLAIM",
                "address_id": "ADDR-A",
                "predicate": "experiment_choice",
                "value": value,
                "evidence_ids": ["EV-1"],
                "rationale": "The document records a blocked choice.",
            }
        ]
    }


# --------------------------------------------------------------------------- forensic


def test_forensic_offending_live_value_is_rejected_by_the_model_facing_contract() -> None:
    """First line: the structured-output contract supplied as ``response_format`` refuses the
    exact live value BEFORE any durable conversion is attempted."""
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_assert_claim_payload(OFFENDING_LIVE_VALUE))


def test_forensic_offending_live_value_is_still_rejected_by_the_durable_contract() -> None:
    """Independent second line: durable ``ClaimValue`` is unchanged and still refuses it."""
    with pytest.raises(ValidationError, match="must not carry text or quantity"):
        ClaimValue.model_validate(OFFENDING_LIVE_VALUE)


# --------------------------------------------------------------------------- legal shapes

LEGAL_VALUES: dict[str, tuple[dict[str, Any], type[Any]]] = {
    "text": ({"kind": "TEXT", "text": "seven years"}, TextClaimValueDraft),
    "enumeration": ({"kind": "ENUMERATION", "text": "S3"}, EnumerationClaimValueDraft),
    "quantity": ({"kind": "QUANTITY", "quantity": "7"}, QuantityClaimValueDraft),
    "quantity+unit": (
        {"kind": "QUANTITY", "quantity": "7.5", "unit": "year"},
        QuantityClaimValueDraft,
    ),
    "undecided": ({"kind": "UNDECIDED"}, UndecidedClaimValueDraft),
}


@pytest.mark.parametrize("label", sorted(LEGAL_VALUES))
def test_legal_value_shape_parses_into_its_variant(label: str) -> None:
    value, variant = LEGAL_VALUES[label]
    payload = SemanticDraftPayload.model_validate(_assert_claim_payload(value))
    (draft,) = payload.drafts
    assert isinstance(draft, AssertClaimDraft)
    assert type(draft.value) is variant


@pytest.mark.parametrize("label", sorted(LEGAL_VALUES))
def test_every_legal_model_facing_shape_is_also_legal_durably(label: str) -> None:
    """The two contracts agree on the legal side too: every shape the model may emit is
    a shape ``ClaimValue`` accepts (quantity parsed from its decimal string)."""
    value, _ = LEGAL_VALUES[label]
    durable = dict(value)
    if "quantity" in durable:
        durable["quantity"] = Decimal(durable["quantity"])
    ClaimValue.model_validate(durable)


# --------------------------------------------------------------------------- illegal shapes

ILLEGAL_VALUES: dict[str, dict[str, Any]] = {
    "undecided+text": {"kind": "UNDECIDED", "text": "x"},
    "undecided+quantity": {"kind": "UNDECIDED", "quantity": "1"},
    "undecided+unit": {"kind": "UNDECIDED", "unit": "year"},
    "text-without-text": {"kind": "TEXT"},
    "text-empty": {"kind": "TEXT", "text": ""},
    "text+quantity": {"kind": "TEXT", "text": "x", "quantity": "1"},
    "text+unit": {"kind": "TEXT", "text": "x", "unit": "year"},
    "enumeration-without-text": {"kind": "ENUMERATION"},
    "enumeration+quantity": {"kind": "ENUMERATION", "text": "x", "quantity": "1"},
    "enumeration+unit": {"kind": "ENUMERATION", "text": "x", "unit": "year"},
    "quantity-without-quantity": {"kind": "QUANTITY", "unit": "year"},
    "quantity+text": {"kind": "QUANTITY", "quantity": "1", "text": "x"},
    "unknown-kind": {"kind": "BOOLEAN", "text": "true"},
    "no-kind": {"text": "x"},
}


@pytest.mark.parametrize("label", sorted(ILLEGAL_VALUES))
def test_illegal_value_shape_is_a_structural_failure_of_the_payload(label: str) -> None:
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_assert_claim_payload(ILLEGAL_VALUES[label]))


# The one shape the model-facing contract refuses that durable ``ClaimValue`` tolerates:
# durable ``text`` has no ``min_length``. Stricter-than-durable is permitted (it can never
# produce a durable rejection of an accepted draft); looser-than-durable is the defect.
ADAPTER_ONLY_REFUSALS = frozenset({"text-empty"})


@pytest.mark.parametrize("label", sorted(ILLEGAL_VALUES.keys() - ADAPTER_ONLY_REFUSALS))
def test_illegal_value_shape_is_also_refused_durably(label: str) -> None:
    """Every kind-shape the model-facing contract refuses is one the durable contract
    refuses as well: the adapter is never the only line and never a looser line."""
    with pytest.raises(ValidationError):
        ClaimValue.model_validate(ILLEGAL_VALUES[label])


def test_empty_text_is_the_only_adapter_only_refusal() -> None:
    ClaimValue.model_validate(ILLEGAL_VALUES["text-empty"])  # durable tolerates ""
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_assert_claim_payload(ILLEGAL_VALUES["text-empty"]))


def test_explicit_nulls_are_not_a_loophole() -> None:
    """The live value spelled its absent fields as explicit ``null``; ``extra="forbid"``
    refuses the key regardless of its value."""
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(
            _assert_claim_payload({"kind": "UNDECIDED", "text": None, "quantity": None})
        )
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(
            _assert_claim_payload({"kind": "TEXT", "text": "x", "quantity": None, "unit": None})
        )


# --------------------------------------------------------------------------- JSON schema

VARIANTS = (
    "TextClaimValueDraft",
    "EnumerationClaimValueDraft",
    "QuantityClaimValueDraft",
    "UndecidedClaimValueDraft",
)


def test_generated_schema_expresses_the_four_alternatives() -> None:
    schema = SemanticDraftPayload.model_json_schema()
    defs = schema["$defs"]
    assert defs["AssertClaimDraft"]["properties"]["value"] == {"$ref": "#/$defs/ClaimValueDraft"}
    union = defs["ClaimValueDraft"]
    assert union["discriminator"]["propertyName"] == "kind"
    assert union["discriminator"]["mapping"] == {
        "TEXT": "#/$defs/TextClaimValueDraft",
        "ENUMERATION": "#/$defs/EnumerationClaimValueDraft",
        "QUANTITY": "#/$defs/QuantityClaimValueDraft",
        "UNDECIDED": "#/$defs/UndecidedClaimValueDraft",
    }
    assert [ref["$ref"] for ref in union["oneOf"]] == [f"#/$defs/{v}" for v in VARIANTS]


def test_generated_schema_variants_are_closed_and_carry_only_legal_fields() -> None:
    defs = SemanticDraftPayload.model_json_schema()["$defs"]
    expected_fields = {
        "TextClaimValueDraft": ({"kind", "text"}, {"kind", "text"}),
        "EnumerationClaimValueDraft": ({"kind", "text"}, {"kind", "text"}),
        "QuantityClaimValueDraft": ({"kind", "quantity", "unit"}, {"kind", "quantity"}),
        "UndecidedClaimValueDraft": ({"kind"}, {"kind"}),
    }
    for name, (properties, required) in expected_fields.items():
        variant = defs[name]
        assert variant["additionalProperties"] is False, name
        assert set(variant["properties"]) == properties, name
        assert set(variant["required"]) == required, name
        assert (
            variant["properties"]["kind"]["const"] == name.removesuffix("ClaimValueDraft").upper()
        )


def test_generated_schema_still_cannot_express_authority() -> None:
    schema = json.dumps(SemanticDraftPayload.model_json_schema())
    assert "CANONICAL" not in schema
    assert "authority" not in schema


# --------------------------------------------------------------------------- draft kind (R3-b)
#
# The discriminated union refuses a draft without ``kind`` (``union_tag_not_found``), so
# the sealed schema must list ``kind`` as required on every draft rather than advertising
# it as optional-with-default.

DRAFT_SCHEMA_NAMES = (
    "CreateAddressDraft",
    "BindToAddressDraft",
    "AssertClaimDraft",
    "SupportsClaimDraft",
    "SupersedeDraft",
    "EquivalentDraft",
    "DistinctDraft",
    "ConflictsWithDraft",
)

MINIMAL_DRAFTS: dict[str, dict[str, Any]] = {
    "CreateAddressDraft": {
        "kind": "CREATE_ADDRESS",
        "subject": "s",
        "facet": "f",
        "evidence_ids": ["EV-1"],
        "rationale": "r",
    },
    "BindToAddressDraft": {
        "kind": "BIND_TO_ADDRESS",
        "address_id": "ADDR-A",
        "subject": "s",
        "facet": "f",
        "evidence_ids": ["EV-1"],
        "rationale": "r",
    },
    "AssertClaimDraft": {
        "kind": "ASSERT_CLAIM",
        "address_id": "ADDR-A",
        "predicate": "p",
        "value": {"kind": "UNDECIDED"},
        "evidence_ids": ["EV-1"],
        "rationale": "r",
    },
    "SupportsClaimDraft": {
        "kind": "SUPPORTS_CLAIM",
        "claim_id": "CLAIM-1",
        "evidence_ids": ["EV-1"],
        "rationale": "r",
    },
    "SupersedeDraft": {"kind": "SUPERSEDE", "target_judgment_id": "JDG-1", "reason": "r"},
    "EquivalentDraft": {
        "kind": "EQUIVALENT",
        "address_ids": ["ADDR-A", "ADDR-B"],
        "rationale": "r",
    },
    "DistinctDraft": {
        "kind": "DISTINCT",
        "address_ids": ["ADDR-A", "ADDR-B"],
        "rationale": "r",
    },
    "ConflictsWithDraft": {
        "kind": "CONFLICTS_WITH",
        "claim_ids": ["CLAIM-1", "CLAIM-2"],
        "rationale": "r",
    },
}


@pytest.mark.parametrize("name", DRAFT_SCHEMA_NAMES)
def test_every_draft_schema_requires_kind(name: str) -> None:
    draft_schema = SemanticDraftPayload.model_json_schema()["$defs"][name]
    assert "kind" in draft_schema["required"], name
    assert "default" not in draft_schema["properties"]["kind"], name


@pytest.mark.parametrize("name", DRAFT_SCHEMA_NAMES)
def test_every_draft_parses_with_kind_and_is_refused_without_it(name: str) -> None:
    with_kind = MINIMAL_DRAFTS[name]
    payload = SemanticDraftPayload.model_validate({"drafts": [with_kind]})
    assert type(payload.drafts[0]).__name__ == name
    without_kind = {k: v for k, v in with_kind.items() if k != "kind"}
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate({"drafts": [without_kind]})
    draft_type = getattr(mod, name)
    with pytest.raises(ValidationError):
        draft_type.model_validate(without_kind)


# --------------------------------------------------------------------------- pair drafts
#
# Contract-audit finding of the same mechanical class: ``EquivalentProposal``,
# ``DistinctProposal`` and ``ConflictsWithProposal`` each reject an identical pair
# (``validate_distinct_pair``) independent of any runtime context, so the model-facing
# draft must refuse the same shape before durable conversion. 9P-C-R3-R1: the refusal is
# carried by the SCHEMA (one collection of exactly two unique ids, see
# ``test_xai_pair_contract.py``), not by a runtime-only model validator.

IDENTICAL_PAIR_DRAFTS: dict[str, dict[str, Any]] = {
    "equivalent": {
        "kind": "EQUIVALENT",
        "address_ids": ["ADDR-A", "ADDR-A"],
        "rationale": "r",
    },
    "distinct": {
        "kind": "DISTINCT",
        "address_ids": ["ADDR-A", "ADDR-A"],
        "rationale": "r",
    },
    "conflicts_with": {
        "kind": "CONFLICTS_WITH",
        "claim_ids": ["CLAIM-1", "CLAIM-1"],
        "rationale": "r",
    },
}

PAIR_PROPOSALS: dict[str, tuple[type[Any], str, str, str]] = {
    "equivalent": (EquivalentProposal, "address_a", "address_b", "address_ids"),
    "distinct": (DistinctProposal, "address_a", "address_b", "address_ids"),
    "conflicts_with": (ConflictsWithProposal, "claim_a", "claim_b", "claim_ids"),
}


@pytest.mark.parametrize("label", sorted(IDENTICAL_PAIR_DRAFTS))
def test_identical_pair_is_rejected_by_the_model_facing_contract(label: str) -> None:
    with pytest.raises(ValidationError, match="exactly two distinct ids"):
        SemanticDraftPayload.model_validate({"drafts": [IDENTICAL_PAIR_DRAFTS[label]]})


@pytest.mark.parametrize("label", sorted(IDENTICAL_PAIR_DRAFTS))
def test_identical_pair_is_still_rejected_by_the_durable_proposal(label: str) -> None:
    proposal_type, field_a, field_b, _ = PAIR_PROPOSALS[label]
    with pytest.raises(ValidationError, match="must differ"):
        proposal_type(**{field_a: "X", field_b: "X"})


@pytest.mark.parametrize("label", sorted(IDENTICAL_PAIR_DRAFTS))
def test_distinct_pair_still_parses(label: str) -> None:
    draft = dict(IDENTICAL_PAIR_DRAFTS[label])
    _, _, _, collection = PAIR_PROPOSALS[label]
    first = draft[collection][0]
    draft[collection] = [first, first + "-OTHER"]
    payload = SemanticDraftPayload.model_validate({"drafts": [draft]})
    assert len(payload.drafts) == 1


# --------------------------------------------------------------------------- schema seal


def _canonical_schema_sha256(model: type[Any]) -> str:
    canonical = json.dumps(
        model.model_json_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_semantic_output_schema_is_sealed_by_a_pasted_literal() -> None:
    assert semantic_output_schema_sha256() == mod.SEMANTIC_OUTPUT_SCHEMA_SHA256
    assert semantic_output_schema_sha256() == _canonical_schema_sha256(SemanticDraftPayload)
    assert "SEMANTIC_OUTPUT_SCHEMA_SHA256" in mod.__all__
    assert "semantic_output_schema_sha256" in mod.__all__


def test_semantic_output_schema_hash_is_deterministic() -> None:
    assert semantic_output_schema_sha256() == semantic_output_schema_sha256()
    assert len(mod.SEMANTIC_OUTPUT_SCHEMA_SHA256) == 64
    assert all(c in "0123456789abcdef" for c in mod.SEMANTIC_OUTPUT_SCHEMA_SHA256)


def test_changing_the_contract_changes_the_hash() -> None:
    """A locally defined variant of the payload contract must not share the seal."""

    class LooserUndecidedClaimValueDraft(FrozenModel):
        kind: Literal["UNDECIDED"]
        text: str | None = None

    type LooserClaimValueDraft = Annotated[
        TextClaimValueDraft
        | EnumerationClaimValueDraft
        | QuantityClaimValueDraft
        | LooserUndecidedClaimValueDraft,
        Field(discriminator="kind"),
    ]

    class LooserAssertClaimDraft(FrozenModel):
        kind: Literal["ASSERT_CLAIM"] = "ASSERT_CLAIM"
        address_id: str = Field(min_length=1)
        predicate: str = Field(min_length=1)
        value: LooserClaimValueDraft
        evidence_ids: tuple[str, ...] = Field(min_length=1)
        rationale: str = Field(min_length=1, max_length=2000)

    class LooserSemanticDraftPayload(FrozenModel):
        drafts: tuple[LooserAssertClaimDraft, ...] = ()

    assert _canonical_schema_sha256(LooserSemanticDraftPayload) != semantic_output_schema_sha256()


def test_old_contract_shape_is_not_the_sealed_one() -> None:
    """The pre-R3 ``ClaimValueDraft`` (one class, all fields optional) advertised the
    illegal live shape; its seal must differ from the current one."""

    class OldClaimValueDraft(FrozenModel):
        kind: ClaimValueKind
        text: str | None = None
        quantity: str | None = None
        unit: str | None = None

    class OldAssertClaimDraft(FrozenModel):
        kind: Literal["ASSERT_CLAIM"] = "ASSERT_CLAIM"
        address_id: str = Field(min_length=1)
        predicate: str = Field(min_length=1)
        value: OldClaimValueDraft
        evidence_ids: tuple[str, ...] = Field(min_length=1)
        rationale: str = Field(min_length=1, max_length=2000)

    class OldPayload(FrozenModel):
        drafts: tuple[OldAssertClaimDraft, ...] = ()

    # the old shape accepts the forensic value; the sealed one does not
    OldPayload.model_validate(_assert_claim_payload(OFFENDING_LIVE_VALUE))
    assert _canonical_schema_sha256(OldPayload) != semantic_output_schema_sha256()


# The REAL pre-R3 seal: ``semantic_output_schema_sha256``'s canonical form applied to the
# ``SemanticDraftPayload`` of ``src/foundry/adapters/semantics/xai_reasoner.py`` at commit
# 55fe5c4 (POLICY_VERSION ``intent-v2-9p-v1``; the contract that ran the first live 9P call).
# Computed once by loading that revision as a module (``git show 55fe5c4:<path>``) and
# pasted here so the unit test needs no git history at runtime.
PRE_R3_SCHEMA_SHA256 = "a45a2d651f3883b372f1af619d04fd4553a8b40d7caa3291cba5eadde9681772"

# The R3 seal (the 9p policy version before v3, commit f1a22c9): the contract whose
# pair drafts still advertised ``address_a`` / ``address_b`` (``claim_a`` / ``claim_b``) as
# two independent fields, with "must differ" held only by a runtime ``model_validator``
# invisible to ``model_json_schema()``. Superseded by 9P-C-R3-R1.
R3_SCHEMA_SHA256 = "cc19baf73fc1b35853251fb20e2bf724342da31b4bc91e95a7a1761b01b032c3"


def test_sealed_hash_is_not_the_v1_contract_hash() -> None:
    assert len(PRE_R3_SCHEMA_SHA256) == 64
    assert mod.SEMANTIC_OUTPUT_SCHEMA_SHA256 != PRE_R3_SCHEMA_SHA256
    assert semantic_output_schema_sha256() != PRE_R3_SCHEMA_SHA256


def test_sealed_hash_is_not_the_r3_contract_hash() -> None:
    assert len(R3_SCHEMA_SHA256) == 64
    assert R3_SCHEMA_SHA256 != PRE_R3_SCHEMA_SHA256
    assert mod.SEMANTIC_OUTPUT_SCHEMA_SHA256 != R3_SCHEMA_SHA256
    assert semantic_output_schema_sha256() != R3_SCHEMA_SHA256
