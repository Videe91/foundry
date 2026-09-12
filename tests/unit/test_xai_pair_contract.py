"""Task 9P-C-R3-R1: semantic pair uniqueness must be encoded in the provider-facing
output schema, not only in local runtime validation.

R3 added ``@model_validator`` "must differ" rules to the three pair drafts. A Pydantic
model validator is local runtime validation: it does not appear in
``SemanticDraftPayload.model_json_schema()``, so the sealed contract handed to the
provider as ``response_format`` still advertised ``address_a == address_b`` /
``claim_a == claim_b`` as legal. That is the hidden-contract class R3 exists to eliminate.

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
    ConflictsWithDraft,
    DistinctDraft,
    EquivalentDraft,
    SemanticDraftPayload,
    SemanticOutputError,
    XAISemanticReasoner,
)
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticAddress,
    SemanticClaim,
)
from foundry.domain.semantic_judgment import (
    ConflictsWithProposal,
    DistinctProposal,
    EquivalentProposal,
    JudgmentKind,
    proposal_signature,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

# --------------------------------------------------------------------------- JSON schema
#
# (name, collection field) for each pair draft. The RED here is taken over the actual
# generated JSON Schema, never over ``model_validate``: the defect is what the schema
# ADVERTISES, not what the runtime accepts.

PAIR_DRAFTS: dict[str, str] = {
    "EquivalentDraft": "address_ids",
    "DistinctDraft": "address_ids",
    "ConflictsWithDraft": "claim_ids",
}


def _defs() -> dict[str, Any]:
    defs = SemanticDraftPayload.model_json_schema()["$defs"]
    assert isinstance(defs, dict)
    return defs


@pytest.mark.parametrize("name", sorted(PAIR_DRAFTS))
def test_pair_draft_schema_exposes_one_collection_of_exactly_two_unique_ids(name: str) -> None:
    field = PAIR_DRAFTS[name]
    draft_schema = _defs()[name]
    assert set(draft_schema["properties"]) == {"kind", field, "rationale"}, name
    assert set(draft_schema["required"]) == {"kind", field, "rationale"}, name
    assert draft_schema["additionalProperties"] is False, name
    collection = draft_schema["properties"][field]
    assert collection["type"] == "array", name
    assert collection["items"] == {"type": "string", "minLength": 1}, name
    assert collection["minItems"] == 2, name
    assert collection["maxItems"] == 2, name
    assert collection["uniqueItems"] is True, name


@pytest.mark.parametrize("name", sorted(PAIR_DRAFTS))
def test_pair_draft_schema_no_longer_advertises_two_independent_fields(name: str) -> None:
    properties = set(_defs()[name]["properties"])
    assert properties.isdisjoint({"address_a", "address_b", "claim_a", "claim_b"}), name


# --------------------------------------------------------------------------- draft shapes

KINDS: dict[str, tuple[str, str, type[Any]]] = {
    # label -> (kind literal, collection field, draft type)
    "equivalent": ("EQUIVALENT", "address_ids", EquivalentDraft),
    "distinct": ("DISTINCT", "address_ids", DistinctDraft),
    "conflicts_with": ("CONFLICTS_WITH", "claim_ids", ConflictsWithDraft),
}


def _draft(label: str, ids: object, **extra: Any) -> dict[str, Any]:
    kind, field, _ = KINDS[label]
    draft: dict[str, Any] = {"kind": kind, field: ids, "rationale": "r"}
    draft.update(extra)
    return draft


def _payload(draft: dict[str, Any]) -> dict[str, Any]:
    return {"drafts": [draft]}


@pytest.mark.parametrize("label", sorted(KINDS))
def test_two_distinct_ids_parse(label: str) -> None:
    _, field, draft_type = KINDS[label]
    payload = SemanticDraftPayload.model_validate(_payload(_draft(label, ["X-1", "X-2"])))
    (draft,) = payload.drafts
    assert type(draft) is draft_type
    assert getattr(draft, field) == frozenset({"X-1", "X-2"})


@pytest.mark.parametrize("label", sorted(KINDS))
def test_same_id_twice_is_refused_before_any_set_coercion(label: str) -> None:
    """A duplicate must never be silently collapsed into a one-member set."""
    with pytest.raises(ValidationError, match="exactly two distinct ids"):
        SemanticDraftPayload.model_validate(_payload(_draft(label, ["X-1", "X-1"])))


@pytest.mark.parametrize("label", sorted(KINDS))
def test_one_id_is_refused(label: str) -> None:
    with pytest.raises(ValidationError, match="exactly two distinct ids"):
        SemanticDraftPayload.model_validate(_payload(_draft(label, ["X-1"])))


@pytest.mark.parametrize("label", sorted(KINDS))
def test_three_ids_are_refused(label: str) -> None:
    with pytest.raises(ValidationError, match="exactly two distinct ids"):
        SemanticDraftPayload.model_validate(_payload(_draft(label, ["X-1", "X-2", "X-3"])))


@pytest.mark.parametrize("label", sorted(KINDS))
def test_empty_collection_is_refused(label: str) -> None:
    with pytest.raises(ValidationError, match="exactly two distinct ids"):
        SemanticDraftPayload.model_validate(_payload(_draft(label, [])))


@pytest.mark.parametrize("label", sorted(KINDS))
def test_missing_pair_field_is_refused(label: str) -> None:
    kind, field, _ = KINDS[label]
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_payload({"kind": kind, "rationale": "r"}))


@pytest.mark.parametrize("label", sorted(KINDS))
def test_old_two_field_shape_is_refused_as_extra(label: str) -> None:
    kind, field, _ = KINDS[label]
    prefix = field.removesuffix("_ids")
    old = {"kind": kind, f"{prefix}_a": "X-1", f"{prefix}_b": "X-2", "rationale": "r"}
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_payload(old))
    # ...and the old names cannot ride alongside the new field either.
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(
            _payload(_draft(label, ["X-1", "X-2"], **{f"{prefix}_a": "X-1"}))
        )


@pytest.mark.parametrize("label", sorted(KINDS))
@pytest.mark.parametrize("bad", [["X-1", 2], [None, "X-1"], ["X-1", ["X-2"]], "X-1X-2", None])
def test_non_string_members_and_non_collections_are_refused(label: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_payload(_draft(label, bad)))


@pytest.mark.parametrize("label", sorted(KINDS))
def test_empty_string_member_is_refused(label: str) -> None:
    with pytest.raises(ValidationError):
        SemanticDraftPayload.model_validate(_payload(_draft(label, ["", "X-1"])))


@pytest.mark.parametrize("label", sorted(KINDS))
def test_direct_construction_with_a_duplicate_is_refused(label: str) -> None:
    kind, field, draft_type = KINDS[label]
    with pytest.raises(ValidationError, match="exactly two distinct ids"):
        draft_type(kind=kind, rationale="r", **{field: ("X-1", "X-1")})


@pytest.mark.parametrize("label", sorted(KINDS))
def test_pair_drafts_carry_no_model_validator(label: str) -> None:
    """The invariant lives in the field (and so in the schema); no redundant after-hook."""
    _, _, draft_type = KINDS[label]
    assert not hasattr(draft_type, "validate_distinct_pair")


# --------------------------------------------------------------------------- transport fake

PROJECT = "PROJ-9P-R3-R1"
T0 = datetime(2026, 9, 12, tzinfo=UTC)


class FakeHarness:
    """Minimal stand-in for the xAI SDK ``Client``: never touches the network."""

    def __init__(self) -> None:
        self.content: str = SemanticDraftPayload(drafts=()).model_dump_json()
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
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                    cost_usd=0.0,
                )

        class FakeChatNamespace:
            def create(self, **kwargs: object) -> FakeChat:
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


def _address(address_id: str) -> SemanticAddress:
    return SemanticAddress(
        address_id=address_id,
        project_id=PROJECT,
        subject="audit records",
        facet="retention period",
        scope=("intent-engine",),
        created_by_judgment_id="J-0",
    )


def _claim(claim_id: str, years: str) -> SemanticClaim:
    return SemanticClaim(
        claim_id=claim_id,
        project_id=PROJECT,
        address_id="ADDR-A",
        predicate="retention_period",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(years), unit="year"),
        evidence_ids=("EV-1",),
        authority=Authority.INFERRED,
        provenance=Provenance(source_kind=SourceKind.SYSTEM, source_ref="xai:grok-4.6"),
        created_by_judgment_id=f"J-{claim_id}",
    )


ADDR_A, ADDR_B = _address("ADDR-A"), _address("ADDR-B")
CLAIM_1, CLAIM_2 = _claim("CLAIM-1", "7"), _claim("CLAIM-2", "10")
RECONCILE = frozenset({JudgmentKind.EQUIVALENT, JudgmentKind.DISTINCT, JudgmentKind.CONFLICTS_WITH})


def _request() -> ReasoningRequest:
    return ReasoningRequest(
        project_id=PROJECT,
        evidence=(EV1,),
        known_addresses=(ADDR_A, ADDR_B),
        known_claims=(CLAIM_1, CLAIM_2),
        allowed_judgment_kinds=RECONCILE,
    )


# --------------------------------------------------------------------------- conversion

PROPOSALS: dict[str, tuple[type[Any], str, str, tuple[str, str]]] = {
    "equivalent": (EquivalentProposal, "address_a", "address_b", ("ADDR-A", "ADDR-B")),
    "distinct": (DistinctProposal, "address_a", "address_b", ("ADDR-A", "ADDR-B")),
    "conflicts_with": (ConflictsWithProposal, "claim_a", "claim_b", ("CLAIM-1", "CLAIM-2")),
}


@pytest.mark.parametrize("label", sorted(KINDS))
def test_both_orientations_produce_the_same_durable_proposal(
    label: str, harness: FakeHarness
) -> None:
    proposal_type, field_a, field_b, (first, second) = PROPOSALS[label]
    outcomes = []
    for ids in ([first, second], [second, first]):
        harness.content = json.dumps(_payload(_draft(label, ids)))
        (judgment,) = _reasoner().propose(_request())
        proposal = judgment.proposal
        assert isinstance(proposal, proposal_type)
        assert getattr(proposal, field_a) == first  # sorted, deterministic
        assert getattr(proposal, field_b) == second
        assert judgment.compared_object_ids == (first, second)
        outcomes.append((proposal, proposal_signature(proposal)))
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("label", sorted(KINDS))
def test_reference_law_still_applies_to_both_members(label: str, harness: FakeHarness) -> None:
    _, _, _, (first, _) = PROPOSALS[label]
    for ids in ([first, "NOPE-9"], ["NOPE-9", first]):
        harness.content = json.dumps(_payload(_draft(label, ids)))
        reasoner = _reasoner()
        with pytest.raises(SemanticOutputError, match="NOPE-9"):
            reasoner.propose(_request())
        # the call was paid for: the receipt and raw payload are still recorded
        assert len(reasoner.receipts) == 1
        assert reasoner.receipts[0].draft_count == 1


@pytest.mark.parametrize("label", sorted(KINDS))
def test_live_duplicate_pair_is_a_structural_refusal_with_receipt(
    label: str, harness: FakeHarness
) -> None:
    _, _, _, (first, _) = PROPOSALS[label]
    harness.content = json.dumps(_payload(_draft(label, [first, first])))
    reasoner = _reasoner()
    with pytest.raises(SemanticOutputError, match="violates the sealed output schema"):
        reasoner.propose(_request())
    assert len(reasoner.receipts) == 1
    assert reasoner.receipts[0].draft_count == 0


# --------------------------------------------------------------------------- seal / policy

# The R3 seal (the 9p policy version before v3, commit f1a22c9): the pair drafts carried
# the "must differ" rule only as a runtime ``model_validator``. Pasted so the test needs
# no git history at runtime.
R3_SCHEMA_SHA256 = "cc19baf73fc1b35853251fb20e2bf724342da31b4bc91e95a7a1761b01b032c3"


def test_sealed_hash_is_not_the_r3_contract_hash() -> None:
    assert len(R3_SCHEMA_SHA256) == 64
    assert mod.SEMANTIC_OUTPUT_SCHEMA_SHA256 != R3_SCHEMA_SHA256
    assert mod.semantic_output_schema_sha256() != R3_SCHEMA_SHA256
    assert mod.semantic_output_schema_sha256() == mod.SEMANTIC_OUTPUT_SCHEMA_SHA256


def test_policy_version_bumped_for_the_pair_contract() -> None:
    assert mod.POLICY_VERSION == "intent-v2-9p-v4"


def test_system_instruction_is_byte_identical_to_r3() -> None:
    """The pair representation changed; the prompt did not."""
    assert (
        mod.SYSTEM_INSTRUCTION_SHA256
        == "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
    )
