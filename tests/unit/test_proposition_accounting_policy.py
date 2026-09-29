"""The proposition-accounting policy ``intent-v2-locus-v4`` (IE2 v2 design §7.1.3).

Identity frozen by pasted literals; every earlier identity (prompts, both earlier output
contracts, the canonical-facet policy) byte-identical; only this policy renders the sentence
index and reads ``accountable_evidence_ids``. On the real pipeline (the production adapter,
``assimilate_delta`` and a governor under ``AdmissionPolicy(canonical_facets=True)``; only
the transport is scripted), C09, C8 and C6 are accounted for completely, and the two v4
failure shapes are refused before any judgment exists, leaving state exactly as Call 1 left
it. Grouping, binding and canonical facets are unchanged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count
from types import SimpleNamespace
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics import xai_reasoner as mod
from foundry.adapters.semantics.xai_reasoner import (
    ACCOUNTED_OUTPUT_SCHEMA_SHA256,
    CANONICAL_FACET_SYSTEM_INSTRUCTION,
    CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256,
    CONCERN_OUTPUT_SCHEMA_SHA256,
    GOVERNED_CONCERN_SYSTEM_INSTRUCTION,
    GOVERNED_CONCERN_SYSTEM_INSTRUCTION_SHA256,
    PROPOSITION_ACCOUNTING_POLICY_VERSION,
    PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION,
    PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION_SHA256,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    AccountedDraftPayload,
    ConcernDraftPayload,
    PropositionAccountingError,
    SemanticDraftPayload,
    XAICanonicalFacetSemanticReasoner,
    XAIContrastiveSemanticReasoner,
    XAIGovernedConcernSemanticReasoner,
    XAILocusSemanticReasoner,
    XAIPropositionAccountingSemanticReasoner,
    XAISemanticReasoner,
    accounted_output_schema_sha256,
    concern_output_schema_sha256,
    render_request,
    semantic_output_schema_sha256,
)
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import canonical_facet
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.source_text import numbered_sentences
from foundry.experiments.long_horizon_bounded.timeline import SECTION_TEXT
from foundry.ports.semantic_reasoner import ReasoningRequest
from tests.unit.test_xai_semantic_reasoner import FakeHarness

AT = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
PROJECT = "PROJ-ACCOUNTING"
SCOPE = "accounting"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ identity


def test_the_new_policy_has_its_own_frozen_identity() -> None:
    assert PROPOSITION_ACCOUNTING_POLICY_VERSION == "intent-v2-locus-v4"
    assert _sha(PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION) == (
        PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION_SHA256
    )
    assert PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION_SHA256 == (
        "cbf652fb3dc7a5864813c02f64373adc72faceddea0793409c34972a0adb1e2f"
    )
    assert (
        accounted_output_schema_sha256()
        == ACCOUNTED_OUTPUT_SCHEMA_SHA256
        == ("921171df25bbf4c64f3a2570ea64dc0b29d6618cf0c8c56f79e01abf1d34a142")
    )
    cls = XAIPropositionAccountingSemanticReasoner
    assert cls.policy_version == PROPOSITION_ACCOUNTING_POLICY_VERSION
    assert cls.system_instruction == PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION
    assert cls.draft_payload is AccountedDraftPayload
    assert cls.include_sentence_index is True and cls.include_comparison_context is True


def test_every_earlier_identity_is_byte_identical() -> None:
    assert (
        semantic_output_schema_sha256()
        == SEMANTIC_OUTPUT_SCHEMA_SHA256
        == ("ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851")
    )
    assert (
        concern_output_schema_sha256()
        == CONCERN_OUTPUT_SCHEMA_SHA256
        == ("08d881db080f87b45abebc3fb79ce53229ccf490b1ba331f75744efb55051b79")
    )
    assert _sha(CANONICAL_FACET_SYSTEM_INSTRUCTION) == CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256
    assert CANONICAL_FACET_SYSTEM_INSTRUCTION_SHA256 == (
        "83a717a9e11d26841b0538bcb781eb766b07bdfc94873213da0965be5ac2d803"
    )
    assert _sha(GOVERNED_CONCERN_SYSTEM_INSTRUCTION) == GOVERNED_CONCERN_SYSTEM_INSTRUCTION_SHA256
    for cls, payload in (
        (XAISemanticReasoner, SemanticDraftPayload),
        (XAIContrastiveSemanticReasoner, SemanticDraftPayload),
        (XAILocusSemanticReasoner, SemanticDraftPayload),
        (XAIGovernedConcernSemanticReasoner, SemanticDraftPayload),
        (XAICanonicalFacetSemanticReasoner, ConcernDraftPayload),
    ):
        assert cls.draft_payload is payload, cls.__name__
        assert cls.include_sentence_index is False, cls.__name__


def test_the_prompt_is_the_canonical_facet_prompt_plus_one_section() -> None:
    text = PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION
    assert text.startswith(CANONICAL_FACET_SYSTEM_INSTRUCTION + "\n")
    added = text.removeprefix(CANONICAL_FACET_SYSTEM_INSTRUCTION)
    assert added.lstrip("\n").startswith("PROPOSITION ACCOUNTING")
    assert text.count("A semantic address is") == 1
    for rule in (
        "sentences_to_account",
        "non_operative",
        "exactly one disposition",
        "explanatory prose",
        "CONFLICTS_WITH\n  relates two current claims and disposes of no proposition",
    ):
        assert rule in added, rule


def test_the_contract_names_the_proposition_every_claim_disposition_disposes_of() -> None:
    defs = AccountedDraftPayload.model_json_schema()["$defs"]
    for name in (
        "AccountedAssertClaimDraft",
        "AccountedSupportsClaimDraft",
        "AccountedSupersedeDraft",
    ):
        assert "proposition_id" in defs[name]["required"], name
    assert "proposition_id" not in defs["ConflictsWithDraft"]["properties"]
    for name in ("ConcernCreateAddressDraft", "ConcernBindToAddressDraft"):
        assert "facet" not in defs[name]["properties"], name
    assert set(AccountedDraftPayload.model_fields) == {"propositions", "non_operative", "drafts"}


# ------------------------------------------------------------------ rendering


def _evidence(evidence_id: str, text: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=text,
        observed_at=AT,
        scope=(SCOPE,),
    )


def _request(**overrides: Any) -> ReasoningRequest:
    fields: dict[str, Any] = {
        "project_id": PROJECT,
        "evidence": (
            _evidence("EV-1", "Operators may cancel a job. A cancelled job stays cancelled."),
        ),
        "allowed_judgment_kinds": frozenset(
            {JudgmentKind.ASSERT_CLAIM, JudgmentKind.SUPPORTS_CLAIM, JudgmentKind.SUPERSEDE}
        ),
        "accountable_evidence_ids": ("EV-1",),
    }
    fields.update(overrides)
    return ReasoningRequest(**fields)


def test_only_the_accounting_policy_renders_the_sentence_index() -> None:
    request = _request()
    historical = render_request(request, include_comparison_context=True)
    assert "sentences_to_account" not in historical
    assert historical == render_request(
        request.model_copy(update={"accountable_evidence_ids": ()}), include_comparison_context=True
    )
    rendered = json.loads(
        render_request(request, include_comparison_context=True, include_sentence_index=True)
    )
    assert rendered["sentences_to_account"] == [
        {"sentence_id": "EV-1#S1", "evidence_id": "EV-1", "text": "Operators may cancel a job."},
        {
            "sentence_id": "EV-1#S2",
            "evidence_id": "EV-1",
            "text": "A cancelled job stays cancelled.",
        },
    ]


def test_accountable_evidence_must_be_request_evidence() -> None:
    with pytest.raises(ValueError, match="accountable evidence not in the request"):
        _request(accountable_evidence_ids=("EV-9",))


# ------------------------------------------------------------------ the adapter boundary


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeHarness]:
    fake = FakeHarness()
    monkeypatch.setattr(mod, "Client", fake.client_cls)
    yield fake


def _adapter() -> XAISemanticReasoner:
    ticks = count(1)
    return XAIPropositionAccountingSemanticReasoner(
        api_key="k", clock=lambda: AT, id_factory=lambda p: f"{p}-{next(ticks):03d}"
    )


def _known() -> dict[str, Any]:
    from foundry.domain.common import Authority, Provenance
    from foundry.domain.semantic_identity import (
        ClaimValue,
        ClaimValueKind,
        SemanticAddress,
        SemanticClaim,
    )

    address = SemanticAddress(
        address_id="ADDR-1",
        project_id=PROJECT,
        subject="Job cancellation",
        facet=canonical_facet("Job cancellation"),
        scope=(SCOPE,),
        created_by_judgment_id="J-0",
    )
    claim = SemanticClaim(
        claim_id="CLAIM-1",
        project_id=PROJECT,
        address_id="ADDR-1",
        predicate="who may cancel",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="operators"),
        evidence_ids=("EV-0",),
        authority=Authority.INFERRED,
        provenance=Provenance(source_kind=SourceKind.DOCUMENT, source_ref="doc://EV-0"),
        created_by_judgment_id="J-1",
    )
    return {"known_addresses": (address,), "known_claims": (claim,)}


def _reply(drafts: list[dict[str, Any]], *, with_p2: bool = True) -> str:
    propositions = [
        {"proposition_id": "P1", "sentence_ids": ["EV-1#S1"], "statement": "operators cancel"}
    ]
    if with_p2:
        propositions.append(
            {
                "proposition_id": "P2",
                "sentence_ids": ["EV-1#S2"],
                "statement": "cancelled stays cancelled",
            }
        )
    return json.dumps({"propositions": propositions, "drafts": drafts})


SUPPORT_P1 = {
    "kind": "SUPPORTS_CLAIM",
    "proposition_id": "P1",
    "claim_id": "CLAIM-1",
    "evidence_ids": ["EV-1"],
    "rationale": "restates",
}
ASSERT_P2 = {
    "kind": "ASSERT_CLAIM",
    "proposition_id": "P2",
    "address_id": "ADDR-1",
    "predicate": "repeated cancellation",
    "value": {"kind": "TEXT", "text": "stays cancelled"},
    "evidence_ids": ["EV-1"],
    "rationale": "extends",
}


def test_a_fully_accounted_response_yields_its_judgments(harness: FakeHarness) -> None:
    harness.content = _reply([SUPPORT_P1, ASSERT_P2])
    reasoner = _adapter()
    judgments = reasoner.propose(_request(**_known()))
    assert [j.proposal.kind for j in judgments] == [
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
    ]
    rendered = json.loads(harness.chats[-1].messages[-1].content[0].text)
    assert [s["sentence_id"] for s in rendered["sentences_to_account"]] == ["EV-1#S1", "EV-1#S2"]
    assert harness.create_kwargs[-1]["response_format"] is AccountedDraftPayload


def test_an_omitted_proposition_refuses_the_whole_response_and_keeps_the_record(
    harness: FakeHarness,
) -> None:
    harness.content = _reply([SUPPORT_P1])
    reasoner = _adapter()
    with pytest.raises(PropositionAccountingError) as refused:
        reasoner.propose(_request(**_known()))
    assert refused.value.findings == ("UNACCOUNTED_PROPOSITION: P2",)
    assert "UNACCOUNTED_PROPOSITION: P2" in str(refused.value)
    assert len(reasoner.receipts) == 1
    (kept,) = reasoner.draft_payloads
    assert isinstance(kept, AccountedDraftPayload) and len(kept.drafts) == 1


def test_an_unlisted_sentence_refuses_the_whole_response(harness: FakeHarness) -> None:
    harness.content = _reply([SUPPORT_P1], with_p2=False)
    with pytest.raises(PropositionAccountingError) as refused:
        _adapter().propose(_request(**_known()))
    assert refused.value.findings == ("UNACCOUNTED_SENTENCE: EV-1#S2",)


def test_a_draft_without_its_proposition_id_violates_the_contract(harness: FakeHarness) -> None:
    unnamed = {k: v for k, v in ASSERT_P2.items() if k != "proposition_id"}
    harness.content = _reply([SUPPORT_P1, unnamed])
    with pytest.raises(mod.SemanticOutputError, match="violates the sealed output schema"):
        _adapter().propose(_request(**_known()))


# ------------------------------------------------------------------ the real pipeline

Action = tuple[str, str]
"""("ASSERT", concern) | ("SUPPORT", proposition id of the supported claim) | ("OMIT", "")."""


class Plan:
    """What the scripted model finds in each document and does with each proposition."""

    def __init__(
        self,
        concern_of: dict[str, str],
        propositions: dict[str, list[tuple[str, tuple[int, ...], Action]]],
        non_operative: dict[str, tuple[int, ...]],
        *,
        silent_call_2: frozenset[str] = frozenset(),
    ) -> None:
        self.concern_of = concern_of
        self.propositions = propositions
        self.non_operative = non_operative
        self.silent_call_2 = silent_call_2
        """Evidence ids for which Call 2 returns nothing at all (v4's C8 shape)."""

    def reply(self, request: ReasoningRequest) -> dict[str, Any]:
        known = {a.subject: a.address_id for a in request.known_addresses}
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            drafts: list[dict[str, Any]] = []
            new: dict[str, list[str]] = {}
            for item in request.evidence:
                concern = self.concern_of[item.evidence_id]
                if concern in known:
                    drafts.append(
                        {
                            "kind": "BIND_TO_ADDRESS",
                            "address_id": known[concern],
                            "subject": concern,
                            "evidence_ids": [item.evidence_id],
                            "rationale": "same concern",
                        }
                    )
                else:
                    new.setdefault(concern, []).append(item.evidence_id)
            drafts += [
                {"kind": "CREATE_ADDRESS", "subject": c, "evidence_ids": e, "rationale": "concern"}
                for c, e in new.items()
            ]
            return {"drafts": drafts}
        by_predicate = {c.predicate: c.claim_id for c in request.known_claims}
        propositions, silent, drafts = [], [], []
        for ev in request.accountable_evidence_ids:
            if ev in self.silent_call_2:
                continue
            ids = [sid for sid, _ in numbered_sentences(ev, _text(request, ev))]
            for pid, sentences, (action, target) in self.propositions.get(ev, []):
                propositions.append(
                    {
                        "proposition_id": pid,
                        "sentence_ids": [ids[s - 1] for s in sentences],
                        "statement": f"statement {pid}",
                    }
                )
                if action == "ASSERT":
                    drafts.append(
                        {
                            "kind": "ASSERT_CLAIM",
                            "proposition_id": pid,
                            "address_id": known[target],
                            "predicate": pid,
                            "value": {"kind": "TEXT", "text": f"claim {pid}"},
                            "evidence_ids": [ev],
                            "rationale": "one proposition",
                        }
                    )
                elif action == "SUPPORT":
                    drafts.append(
                        {
                            "kind": "SUPPORTS_CLAIM",
                            "proposition_id": pid,
                            "claim_id": by_predicate[target],
                            "evidence_ids": [ev],
                            "rationale": "restates",
                        }
                    )
            silent += [
                {"sentence_id": ids[s - 1], "reason": "an example"}
                for s in self.non_operative.get(ev, ())
            ]
        return {"propositions": propositions, "non_operative": silent, "drafts": drafts}


def _text(request: ReasoningRequest, evidence_id: str) -> str:
    (item,) = [e for e in request.evidence if e.evidence_id == evidence_id]
    return item.content


class Scripted(XAIPropositionAccountingSemanticReasoner):
    """The production accounting adapter with its transport replaced by a plan."""

    def __init__(self, reply: Callable[[ReasoningRequest], dict[str, Any]]) -> None:
        ticks = count(1)
        super().__init__(
            api_key="k", clock=lambda: AT, id_factory=lambda p: f"{p}-{next(ticks):04d}"
        )
        self._reply = reply
        self.requests: list[ReasoningRequest] = []

    def _call_model(self, request: ReasoningRequest) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            content=json.dumps(self._reply(request)),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            cost_usd=0.0,
        )


class World:
    def __init__(self, plan: Plan) -> None:
        ids = count(1)
        self.store = InMemoryEventStore()
        self.governor = SemanticGovernor(
            store=self.store,
            project_id=PROJECT,
            policy=AdmissionPolicy(canonical_facets=True),
            clock=lambda: AT,
            id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
        )
        self.reasoner = Scripted(plan.reply)

    def delta(self, *items: EvidenceItem) -> None:
        outcome = assimilate_delta(
            governor=self.governor, reasoner=self.reasoner, delta=items, scope=SCOPE
        )
        routes = {d.route.value for stage in outcome.stage_decisions for d in stage}
        assert routes <= {"APPLY", "REQUIRE_SECOND_LENS"}, routes

    def addresses(self) -> dict[str, tuple[str, str]]:
        state = self.governor.state().semantic
        return {a: (x.subject, x.facet) for a, x in state.addresses.items()}

    def live_predicates(self) -> dict[str, set[str]]:
        state = self.governor.state().semantic
        active = active_judgment_ids(state)
        out: dict[str, set[str]] = {}
        for c in state.claims.values():
            if c.created_by_judgment_id in active:
                out.setdefault(c.address_id, set()).add(c.predicate)
        return out

    def events(self) -> int:
        return len(tuple(self.store.load(PROJECT)))


H1 = _evidence("EV-H-T1", SECTION_TEXT[(1, "H")])
H9 = _evidence("EV-H-T9", SECTION_TEXT[(9, "H")])
CANCEL = "Job cancellation"


def _c09_plan(*, omit_h5: bool = False) -> Plan:
    """H-T1: S1 who may cancel; S2 stop effort + no abort; S3 no future attempt; S4 running
    attempt continues; S5-S6 example. H-T9: S1 restates who; S2 restates both effects; S3 a
    repeat is simply acknowledged; S4-S5 restate the effects; S6 the repeat leaves the job
    cancelled and unchanged; S7-S8 example."""
    return Plan(
        concern_of={"EV-H-T1": CANCEL, "EV-H-T9": CANCEL},
        propositions={
            "EV-H-T1": [
                ("H-1", (1,), ("ASSERT", CANCEL)),
                ("H-2", (2, 3), ("ASSERT", CANCEL)),
                ("H-3", (2, 4), ("ASSERT", CANCEL)),
            ],
            "EV-H-T9": [
                ("R1", (1,), ("SUPPORT", "H-1")),
                ("R2", (2, 4), ("SUPPORT", "H-2")),
                ("R3", (2, 5), ("SUPPORT", "H-3")),
                ("H-4", (6,), ("ASSERT", CANCEL)),
                ("H-5", (3,), ("OMIT", "") if omit_h5 else ("ASSERT", CANCEL)),
            ],
        },
        non_operative={"EV-H-T1": (5, 6), "EV-H-T9": (7, 8)},
    )


def test_21_c09_accounted_completely_keeps_one_address_and_one_canonical_facet() -> None:
    world = World(_c09_plan())
    world.delta(H1)
    world.delta(H9)
    ((address_id, (subject, facet)),) = world.addresses().items()
    assert subject == CANCEL and facet == canonical_facet(CANCEL)
    assert world.live_predicates() == {address_id: {"H-1", "H-2", "H-3", "H-4", "H-5"}}
    call_2 = world.reasoner.requests[-1]
    assert call_2.accountable_evidence_ids == ("EV-H-T9",)


def test_the_v4_c09_shape_is_refused_and_state_stays_as_call_1_left_it() -> None:
    world = World(_c09_plan(omit_h5=True))
    world.delta(H1)
    before = world.live_predicates()
    with pytest.raises(PropositionAccountingError) as refused:
        world.delta(H9)
    assert refused.value.findings == ("UNACCOUNTED_PROPOSITION: H-5",)
    assert world.live_predicates() == before
    state = world.governor.state().semantic
    kinds = [j.proposal.kind for j in state.judgments.values()]
    assert JudgmentKind.SUPPORTS_CLAIM not in kinds
    assert kinds.count(JudgmentKind.BIND_TO_ADDRESS) == 1


REFUND = "Refund of returned order items"
SUPPLIER = "Supplier overpayment repayment"
REFUND_T1 = _evidence(
    "EV-REFUND",
    "A customer who returns an order is refunded the price paid for the returned items.",
)
SUPPLIER_T1 = _evidence(
    "EV-SUPPLIER",
    "A supplier that has been paid more than its invoice total must pay the excess back.",
)
NOTE = _evidence(
    "EV-NOTE", "The original delivery charge is also repaid to a customer who returns an order."
)


def _c8_plan(*, silent: bool = False) -> Plan:
    return Plan(
        concern_of={"EV-REFUND": REFUND, "EV-SUPPLIER": SUPPLIER, "EV-NOTE": REFUND},
        propositions={
            "EV-REFUND": [("CR-1", (1,), ("ASSERT", REFUND))],
            "EV-SUPPLIER": [("SO-1", (1,), ("ASSERT", SUPPLIER))],
            "EV-NOTE": [("CR-2", (1,), ("ASSERT", REFUND))],
        },
        non_operative={},
        silent_call_2=frozenset({"EV-NOTE"}) if silent else frozenset(),
    )


def test_22_c8_accounted_completely_adds_the_extension_at_the_bound_address() -> None:
    world = World(_c8_plan())
    world.delta(REFUND_T1, SUPPLIER_T1)
    world.delta(NOTE)
    by_subject = {s: a for a, (s, _) in world.addresses().items()}
    assert world.live_predicates()[by_subject[REFUND]] == {"CR-1", "CR-2"}
    assert world.live_predicates()[by_subject[SUPPLIER]] == {"SO-1"}


def test_the_v4_c8_shape_zero_drafts_is_refused_and_state_is_unchanged() -> None:
    world = World(_c8_plan(silent=True))
    world.delta(REFUND_T1, SUPPLIER_T1)
    before_claims = world.live_predicates()
    with pytest.raises(PropositionAccountingError) as refused:
        world.delta(NOTE)
    assert refused.value.findings == ("UNACCOUNTED_SENTENCE: EV-NOTE#S1",)
    assert world.live_predicates() == before_claims
    call_2 = world.reasoner.requests[-1]
    assert call_2.accountable_evidence_ids == ("EV-NOTE",)


LATE = "Late delivery compensation"
LATE_T1 = _evidence(
    "EV-LATE",
    "## Late delivery compensation\n\nRules\n"
    "1. If a parcel is delivered later than the promised date, the sender is refunded the "
    "shipping fee.\n2. The refund is paid to the payment method used for the booking.",
)
LATE_NOTE = _evidence(
    "EV-LATE-NOTE",
    "## Late delivery claims\n\nA sender must ask for the late-delivery refund within 14 days "
    "of the promised delivery date.",
)


def test_23_c6_deadline_joins_late_delivery_compensation_fully_accounted() -> None:
    plan = Plan(
        concern_of={"EV-LATE": LATE, "EV-LATE-NOTE": LATE},
        propositions={
            "EV-LATE": [("LATE-1", (1,), ("ASSERT", LATE)), ("LATE-2", (2,), ("ASSERT", LATE))],
            "EV-LATE-NOTE": [("LATE-3", (1,), ("ASSERT", LATE))],
        },
        non_operative={},
    )
    world = World(plan)
    world.delta(LATE_T1)
    world.delta(LATE_NOTE)
    ((address_id, (_, facet)),) = world.addresses().items()
    assert facet == canonical_facet(LATE)
    assert world.live_predicates() == {address_id: {"LATE-1", "LATE-2", "LATE-3"}}


def test_24_grouping_is_unchanged_nearby_concerns_stay_separate_and_accountable() -> None:
    world = World(_c8_plan())
    world.delta(REFUND_T1, SUPPLIER_T1)
    assert sorted(s for s, _ in world.addresses().values()) == [REFUND, SUPPLIER]
    assert world.reasoner.requests[-1].accountable_evidence_ids == ("EV-REFUND", "EV-SUPPLIER")


def test_25_canonical_facets_are_unchanged() -> None:
    world = World(_c8_plan())
    world.delta(REFUND_T1, SUPPLIER_T1)
    for subject, facet in world.addresses().values():
        assert facet == canonical_facet(subject)


def test_evidence_call_1_did_not_place_is_not_accountable() -> None:
    """A NO_MATCH item (no CREATE, no BIND) has no address to hold a claim, so Call 2 is not
    asked to account for it; accountability follows Call 1's applied admissions only."""

    def ignore_supplier(request: ReasoningRequest) -> dict[str, Any]:
        reply = _c8_plan().reply(request)
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            reply["drafts"] = [d for d in reply["drafts"] if "EV-SUPPLIER" not in d["evidence_ids"]]
        return reply

    world = World(_c8_plan())
    world.reasoner = Scripted(ignore_supplier)
    world.delta(REFUND_T1, SUPPLIER_T1)
    assert world.reasoner.requests[-1].accountable_evidence_ids == ("EV-REFUND",)
