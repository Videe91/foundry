"""Task 9P-C-R3-R2: the finite decimal grammar of an AI-output quantity must be encoded in
the provider-facing output schema, not only in local runtime parsing.

R3 made ``QuantityClaimValueDraft.quantity`` a decimal STRING while ``_decimal_of`` refused
malformed and non-finite ``Decimal`` text at conversion time. A local parse is invisible to
``SemanticDraftPayload.model_json_schema()``, so the sealed contract handed to the provider
as ``response_format`` still advertised ``"NaN"`` / ``"1e3"`` / ``"seven"`` as legal.

The repair is a REPRESENTATION decision only: one authoritative literal
(``FINITE_DECIMAL_PATTERN``) carried as ``pattern`` on the field itself. No normalisation,
trimming or repair anywhere; an invalid representation is a structural refusal with the
receipt kept. Durable ``ClaimValue`` is unchanged (the adapter is deliberately stricter).

Every test here is pure schema/contract work over a FAKE transport at most. ZERO live
calls, no real client construction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.adapters.semantics import xai_reasoner as mod
from foundry.adapters.semantics.xai_reasoner import (
    AssertClaimDraft,
    QuantityClaimValueDraft,
    SemanticDraftPayload,
    SemanticOutputError,
    XAISemanticReasoner,
)
from foundry.domain.common import SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticAddress
from foundry.domain.semantic_judgment import AssertClaimProposal, JudgmentKind
from foundry.ports.semantic_reasoner import ReasoningRequest

# --------------------------------------------------------------------------- JSON schema
#
# The RED is taken over the actual generated JSON Schema, never over ``model_validate``:
# the defect is what the schema ADVERTISES, not what the runtime accepts.

EXPECTED_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"


def _quantity_schema() -> dict[str, Any]:
    defs = SemanticDraftPayload.model_json_schema()["$defs"]
    quantity = defs["QuantityClaimValueDraft"]["properties"]["quantity"]
    assert isinstance(quantity, dict)
    return quantity


def test_quantity_schema_carries_the_finite_decimal_pattern() -> None:
    quantity = _quantity_schema()
    assert quantity["type"] == "string"
    assert quantity["pattern"] == mod.FINITE_DECIMAL_PATTERN
    assert mod.FINITE_DECIMAL_PATTERN == EXPECTED_PATTERN


def test_pattern_is_one_authoritative_literal_exported_by_the_adapter() -> None:
    assert "FINITE_DECIMAL_PATTERN" in mod.__all__
    assert isinstance(mod.FINITE_DECIMAL_PATTERN, str)
    # the field carries the SAME literal (not a copy that could drift)
    field = QuantityClaimValueDraft.model_fields["quantity"]
    patterns = [getattr(meta, "pattern", None) for meta in field.metadata]
    assert mod.FINITE_DECIMAL_PATTERN in patterns


def test_quantity_grammar_is_not_carried_by_a_validator_hook() -> None:
    """The primary rule lives in the field (and so in the schema); there is no
    ``field_validator`` / ``model_validator`` standing in for it."""
    decorators = QuantityClaimValueDraft.__pydantic_decorators__
    assert decorators.field_validators == {}
    assert decorators.model_validators == {}


def test_quantity_schema_is_still_closed_and_required() -> None:
    variant = SemanticDraftPayload.model_json_schema()["$defs"]["QuantityClaimValueDraft"]
    assert variant["additionalProperties"] is False
    assert set(variant["properties"]) == {"kind", "quantity", "unit"}
    assert set(variant["required"]) == {"kind", "quantity"}


# --------------------------------------------------------------------------- payload helpers


def _assert_claim_payload(quantity: Any, unit: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": "QUANTITY", "quantity": quantity}
    if unit is not None:
        value["unit"] = unit
    return {
        "drafts": [
            {
                "kind": "ASSERT_CLAIM",
                "address_id": "ADDR-A",
                "predicate": "retention_period",
                "value": value,
                "evidence_ids": ["EV-1"],
                "rationale": "The document states a retention period.",
            }
        ]
    }


def _parsed_quantity_draft(quantity: str) -> QuantityClaimValueDraft:
    payload = SemanticDraftPayload.model_validate(_assert_claim_payload(quantity))
    (draft,) = payload.drafts
    assert isinstance(draft, AssertClaimDraft)
    assert isinstance(draft.value, QuantityClaimValueDraft)
    return draft.value


# --------------------------------------------------------------------------- legal shapes

LEGAL_QUANTITIES: tuple[str, ...] = (
    "0",
    "-0",
    "7",
    "-7",
    "7.5",
    "-7.5",
    "0.001",
    "-0.25",
    "123456789",
    "123456789.0001",
)


@pytest.mark.parametrize("quantity", LEGAL_QUANTITIES)
def test_legal_quantity_validates_converts_and_is_a_finite_decimal(quantity: str) -> None:
    draft = _parsed_quantity_draft(quantity)
    durable = mod._claim_value(draft)
    assert isinstance(durable, ClaimValue)
    assert durable.kind is ClaimValueKind.QUANTITY
    assert type(durable.quantity) is Decimal
    assert durable.quantity is not None
    assert durable.quantity.is_finite()
    assert durable.quantity == Decimal(quantity)


@pytest.mark.parametrize("quantity", LEGAL_QUANTITIES)
def test_legal_quantity_is_stored_byte_identical_on_the_parsed_draft(quantity: str) -> None:
    """No normalisation: the string on the parsed draft is exactly the input bytes."""
    draft = _parsed_quantity_draft(quantity)
    assert draft.quantity == quantity
    assert draft.quantity.encode("utf-8") == quantity.encode("utf-8")
    assert draft.model_dump(mode="json")["quantity"] == quantity


def test_legal_quantity_with_unit_round_trips_the_unit_verbatim() -> None:
    payload = SemanticDraftPayload.model_validate(_assert_claim_payload("7.5", unit="year"))
    (draft,) = payload.drafts
    assert isinstance(draft, AssertClaimDraft)
    assert isinstance(draft.value, QuantityClaimValueDraft)
    durable = mod._claim_value(draft.value)
    assert durable.quantity == Decimal("7.5")
    assert durable.unit == "year"


def test_precision_is_exact_and_never_routed_through_float() -> None:
    durable = mod._claim_value(_parsed_quantity_draft("0.1"))
    assert type(durable.quantity) is Decimal
    assert durable.quantity == Decimal("0.1")
    assert durable.quantity != Decimal(0.1)  # the float would be 0.1000000000000000055511...
    assert str(durable.quantity) == "0.1"


def test_negative_zero_is_preserved_as_decimal_text_not_normalised() -> None:
    durable = mod._claim_value(_parsed_quantity_draft("-0"))
    assert type(durable.quantity) is Decimal
    assert durable.quantity == Decimal("-0")
    assert str(durable.quantity) == "-0"


# --------------------------------------------------------------------------- illegal shapes

ILLEGAL_QUANTITIES: tuple[str, ...] = (
    "",
    " ",
    " 1",
    "1 ",
    "1\n",
    "+1",
    ".5",
    "-.5",
    "1.",
    "-1.",
    "01",
    "-01",
    "00",
    "00.1",
    "1e3",
    "1E3",
    "-2.5e-4",
    "NaN",
    "nan",
    "sNaN",
    "Infinity",
    "-Infinity",
    "inf",
    "-inf",
    "1_000",
    "1,000",
    "seven",
    "--1",
    "1.2.3",
)


@pytest.mark.parametrize("quantity", ILLEGAL_QUANTITIES, ids=repr)
def test_illegal_quantity_is_refused_by_the_model_facing_contract(quantity: str) -> None:
    """The refusal happens in ``SemanticDraftPayload.model_validate`` - BEFORE
    ``_claim_value`` / ``_decimal_of`` could ever see the value."""
    with pytest.raises(ValidationError) as excinfo:
        SemanticDraftPayload.model_validate(_assert_claim_payload(quantity))
    errors = excinfo.value.errors()
    assert any(error["type"] == "string_pattern_mismatch" for error in errors), errors
    assert any(error["loc"][-1] == "quantity" for error in errors), errors


@pytest.mark.parametrize("quantity", ILLEGAL_QUANTITIES, ids=repr)
def test_illegal_quantity_is_refused_on_direct_variant_construction(quantity: str) -> None:
    with pytest.raises(ValidationError):
        QuantityClaimValueDraft(kind="QUANTITY", quantity=quantity)


@pytest.mark.parametrize("quantity", ILLEGAL_QUANTITIES, ids=repr)
def test_illegal_quantity_is_refused_from_json_text_too(quantity: str) -> None:
    """The adapter parses the provider's TEXT (``model_validate_json``); the grammar must
    hold on that path identically."""
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate_json(json.dumps(_assert_claim_payload(quantity)))


@pytest.mark.parametrize("quantity", [7, 7.5, -0.25, 0, True, None, ["7"], {"v": "7"}])
def test_non_string_quantity_is_refused(quantity: object) -> None:
    """A JSON number is not a decimal string; nothing is coerced."""
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_assert_claim_payload(quantity))


# --------------------------------------------------------------------------- second line
#
# ``_decimal_of`` (``Decimal`` parse + ``is_finite``) is unchanged and independent. It can
# no longer be reached with a malformed string through the sealed contract, but it must
# still refuse the same inputs on its own.

DECIMAL_PARSE_FAILURES = ("", " ", "seven", "--1", "1.2.3", "1,000", "+ 1")
DECIMAL_NON_FINITE = ("NaN", "nan", "sNaN", "Infinity", "-Infinity", "inf", "-inf")


@pytest.mark.parametrize("quantity", DECIMAL_PARSE_FAILURES, ids=repr)
def test_decimal_of_still_refuses_malformed_text_independently(quantity: str) -> None:
    with pytest.raises(SemanticOutputError, match="malformed quantity"):
        mod._decimal_of(quantity)


@pytest.mark.parametrize("quantity", DECIMAL_NON_FINITE, ids=repr)
def test_decimal_of_still_refuses_non_finite_text_independently(quantity: str) -> None:
    with pytest.raises(SemanticOutputError, match="non-finite quantity"):
        mod._decimal_of(quantity)


@pytest.mark.parametrize("quantity", LEGAL_QUANTITIES)
def test_decimal_of_accepts_every_legal_shape(quantity: str) -> None:
    parsed = mod._decimal_of(quantity)
    assert type(parsed) is Decimal
    assert parsed == Decimal(quantity)


# --------------------------------------------------------------------------- transport fake

PROJECT = "PROJ-9P-R3-R2"
T0 = datetime(2026, 9, 12, tzinfo=UTC)


class FakeHarness:
    """Minimal stand-in for the xAI SDK ``Client``: never touches the network."""

    def __init__(self) -> None:
        self.content: str = SemanticDraftPayload(drafts=()).model_dump_json()
        self.create_kwargs: list[dict[str, Any]] = []
        self.client_cls = self._client_type()

    def _client_type(self) -> type[object]:
        harness = self

        class FakeChat:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def append(self, message: object) -> FakeChat:
                return self

            def sample(self) -> object:
                return SimpleNamespace(
                    content=harness.content,
                    usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40),
                    cost_usd=0.0042,
                )

        class FakeChatNamespace:
            def create(self, **kwargs: object) -> FakeChat:
                harness.create_kwargs.append(dict(kwargs))
                return FakeChat(**kwargs)

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                self.chat = FakeChatNamespace()

        return FakeClient


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> FakeHarness:
    fake = FakeHarness()
    monkeypatch.setattr(mod, "Client", fake.client_cls)
    return fake


def _reasoner() -> XAISemanticReasoner:
    ticks = count(1)
    return XAISemanticReasoner(
        api_key="test-secret-xai-key-000",
        clock=lambda: T0,
        id_factory=lambda prefix: f"{prefix}-{next(ticks):03d}",
    )


EV1 = evidence_item(
    evidence_id="EV-1",
    project_id=PROJECT,
    source_kind=SourceKind.DOCUMENT,
    source_ref="repo://EV-1",
    content="Audit records are retained for seven years.",
    observed_at=T0,
    scope=("intent-engine",),
)

ADDR_A = SemanticAddress(
    address_id="ADDR-A",
    project_id=PROJECT,
    subject="audit records",
    facet="retention period",
    scope=("intent-engine",),
    created_by_judgment_id="J-0",
)


def _request() -> ReasoningRequest:
    return ReasoningRequest(
        project_id=PROJECT,
        evidence=(EV1,),
        known_addresses=(ADDR_A,),
        known_claims=(),
        allowed_judgment_kinds=frozenset({JudgmentKind.ASSERT_CLAIM}),
    )


@pytest.mark.parametrize("quantity", ["NaN", "1e3"], ids=repr)
def test_live_illegal_quantity_is_a_structural_refusal_with_receipt_and_no_repair(
    harness: FakeHarness, quantity: str
) -> None:
    harness.content = json.dumps(_assert_claim_payload(quantity, unit="year"))
    reasoner = _reasoner()
    with pytest.raises(SemanticOutputError, match="violates the sealed output schema") as exc:
        reasoner.propose(_request())
    assert "quantity" in str(exc.value)
    # the call was paid for: exactly one receipt, with no admissible draft count
    (receipt,) = reasoner.receipts
    assert receipt.invocation_id == "INV-001"
    assert receipt.input_tokens == 120
    assert receipt.output_tokens == 40
    assert receipt.cost_usd == pytest.approx(0.0042)
    assert receipt.draft_count == 0
    # nothing was accepted, repaired or partially wrapped
    assert reasoner.draft_payloads == ()
    # the sealed contract itself was what the provider received
    assert harness.create_kwargs[0]["response_format"] is SemanticDraftPayload


@pytest.mark.parametrize("quantity", ILLEGAL_QUANTITIES, ids=repr)
def test_live_every_illegal_quantity_is_refused_at_parse_time(
    harness: FakeHarness, quantity: str
) -> None:
    harness.content = json.dumps(_assert_claim_payload(quantity))
    reasoner = _reasoner()
    with pytest.raises(SemanticOutputError, match="violates the sealed output schema"):
        reasoner.propose(_request())
    assert len(reasoner.receipts) == 1
    assert reasoner.receipts[0].draft_count == 0
    assert reasoner.draft_payloads == ()


@pytest.mark.parametrize("quantity", LEGAL_QUANTITIES)
def test_live_legal_quantity_becomes_the_exact_durable_decimal(
    harness: FakeHarness, quantity: str
) -> None:
    harness.content = json.dumps(_assert_claim_payload(quantity, unit="year"))
    reasoner = _reasoner()
    (judgment,) = reasoner.propose(_request())
    proposal = judgment.proposal
    assert isinstance(proposal, AssertClaimProposal)
    assert proposal.value == ClaimValue(
        kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="year"
    )
    assert type(proposal.value.quantity) is Decimal
    assert str(proposal.value.quantity) == quantity
    assert reasoner.receipts[0].draft_count == 1


# --------------------------------------------------------------------------- seal / policy

# The R3 seal (commit f1a22c9, ``intent-v2-9p-v2``): pair "must differ" only as a runtime
# ``model_validator``. Pasted so the test needs no git history at runtime.
R3_SCHEMA_SHA256 = "cc19baf73fc1b35853251fb20e2bf724342da31b4bc91e95a7a1761b01b032c3"

# The R3-R1 seal (commit c8bcf6a, ``intent-v2-9p-v3``): pair drafts carried as one
# ``minItems 2 / maxItems 2 / uniqueItems`` collection, but ``quantity`` still a free string.
R3_R1_SCHEMA_SHA256 = "32dd2e4c3d9879a607c73ded63d0939f80bdc3e1f2e5e1e6133830216f5010f0"


def test_sealed_hash_differs_from_every_previous_contract() -> None:
    previous = {R3_SCHEMA_SHA256, R3_R1_SCHEMA_SHA256}
    assert all(len(h) == 64 for h in previous)
    assert len(previous) == 2
    assert mod.SEMANTIC_OUTPUT_SCHEMA_SHA256 not in previous
    assert mod.semantic_output_schema_sha256() not in previous
    assert mod.semantic_output_schema_sha256() == mod.SEMANTIC_OUTPUT_SCHEMA_SHA256


def test_policy_version_bumped_for_the_decimal_contract() -> None:
    assert mod.POLICY_VERSION == "intent-v2-9p-v4"


def test_system_instruction_is_byte_identical_to_r3() -> None:
    """The quantity representation changed; the prompt did not."""
    assert (
        mod.SYSTEM_INSTRUCTION_SHA256
        == "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
    )
