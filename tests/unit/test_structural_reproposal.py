"""Production-only bounded re-proposal after a deterministic structural refusal.

Offline end to end: the production adapters with scripted transports, the real
``assimilate_delta`` / ``synthesize_intent_graph``, real governors and stores. It proves the
allowlists, the fixed notice (ids, never actions), the budget (one re-proposal, never a third
attempt), the audit record of every refused attempt (never overwritten), the state law (nothing
from a refused proposal is applied; Call 1's admissions stay), and isolation: no mode,
CERTIFICATION and EXPERIMENT measure the first answer only, and experiment and certification
code cannot enable a re-proposal.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_REPROPOSAL_POLICY_VERSION,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    render_graph_reproposal_notice,
)
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import (
    PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION,
    PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION_SHA256,
    REPROPOSAL_POLICY_VERSION,
    REPROPOSAL_SYSTEM_INSTRUCTION,
    REPROPOSAL_SYSTEM_INSTRUCTION_SHA256,
    AccountedDraftPayload,
    PropositionAccountingError,
    SemanticOutputError,
    XAICanonicalFacetSemanticReasoner,
    XAIPropositionAccountingSemanticReasoner,
    XAIReproposingSemanticReasoner,
    XAISemanticReasonerError,
    render_request,
)
from foundry.application import intent_graph_synthesis as graph_module
from foundry.application.incremental_assimilation import (
    MAX_PRODUCTION_CALLS_PER_DELTA,
    assimilate_delta,
)
from foundry.application.intent_graph_synthesis import synthesize_intent_graph
from foundry.application.intent_graph_synthesis_context import IntentGraphResultError
from foundry.application.replay import replay
from foundry.application.semantic_completeness import SemanticCompletenessRequired
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import SourceKind
from foundry.domain.events import EVENT_PAYLOAD_TYPES, EventType, StructuralRefusalPayload
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.intent_graph import IntentGraphSynthesisResult
from foundry.domain.semantic_judgment import JudgmentKind, ReasonerFingerprint
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.source_text import numbered_sentences
from foundry.domain.structural_refusal import (
    IE2_REPROPOSABLE_CODES,
    IE3_REPROPOSABLE_CODES,
    MAX_REPROPOSALS,
    REPROPOSAL_CONTRACT_SHA256,
    REPROPOSE_MODES,
    ExecutionMode,
    RefusalEngine,
    ReproposalNotice,
    StructuralRefusal,
    reproposable,
    reproposal_contract_sha256,
)
from foundry.experiments.long_horizon_bounded.timeline import SECTION_TEXT
from foundry.ports.intent_graph_synthesizer import IntentGraphSynthesisRequest
from foundry.ports.semantic_reasoner import ReasonerResponseRefused, ReasoningRequest
from tests.certification._intent_graph_exam import build_graph_case_c
from tests.unit._completeness_fixtures import ScriptedVerifier, all_complete

AT = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
PROJECT = "PROJ-REPROPOSE"
SCOPE = "reproposal"
ROOT = Path(__file__).resolve().parents[2]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ================================================================== the shared kernel


def test_the_contract_is_pinned_one_reproposal_production_only() -> None:
    assert (
        reproposal_contract_sha256()
        == REPROPOSAL_CONTRACT_SHA256
        == ("613ac28687a1ce020c4a2adc87d8efd3fc27e10301ce5a535f8ebac4a8bb9a84")
    )
    assert MAX_REPROPOSALS == 1
    assert frozenset({ExecutionMode.PRODUCTION}) == REPROPOSE_MODES


def test_the_allowlists_are_exactly_the_structural_contract_codes() -> None:
    assert {
        "UNACCOUNTED_SENTENCE",
        "UNKNOWN_SENTENCE",
        "DOUBLE_ACCOUNTED_SENTENCE",
        "UNACCOUNTED_PROPOSITION",
        "UNKNOWN_PROPOSITION",
        "DUPLICATE_PROPOSITION",
        "CONFLICTING_DISPOSITION",
        "PROPOSITION_EVIDENCE_MISMATCH",
    } == IE2_REPROPOSABLE_CODES
    assert {"PARALLEL_NODE"} == IE3_REPROPOSABLE_CODES
    assert "NON_CANONICAL_FACET" not in IE2_REPROPOSABLE_CODES


@pytest.mark.parametrize(
    ("engine", "findings", "expected"),
    [
        (RefusalEngine.IE2_CLAIM_ASSIMILATION, ("UNACCOUNTED_PROPOSITION: P5",), True),
        (
            RefusalEngine.IE2_CLAIM_ASSIMILATION,
            ("UNACCOUNTED_SENTENCE: EV#S1", "UNKNOWN_PROPOSITION: P9"),
            True,
        ),
        (
            RefusalEngine.IE2_CLAIM_ASSIMILATION,
            ("UNACCOUNTED_PROPOSITION: P5", "NON_CANONICAL_FACET: x"),
            False,
        ),
        (RefusalEngine.IE2_CLAIM_ASSIMILATION, ("PARALLEL_NODE: x",), False),
        (RefusalEngine.IE2_CLAIM_ASSIMILATION, (), False),
        (RefusalEngine.IE3_GRAPH_SYNTHESIS, ("PARALLEL_NODE: 'a' and 'b'",), True),
        (RefusalEngine.IE3_GRAPH_SYNTHESIS, ("NO_RELEVANCE: 'a'",), False),
        (RefusalEngine.IE3_GRAPH_SYNTHESIS, ("UNACCOUNTED_PROPOSITION: P5",), False),
    ],
)
def test_only_allowlisted_codes_are_reproposable(
    engine: RefusalEngine, findings: tuple[str, ...], expected: bool
) -> None:
    assert reproposable(engine, findings) is expected


def test_the_notice_states_the_refusal_and_never_an_action() -> None:
    text = ReproposalNotice(findings=("UNACCOUNTED_PROPOSITION: H-5",)).text()
    assert "UNACCOUNTED_PROPOSITION: H-5" in text
    assert "complete new proposal" in text
    for action in ("ASSERT", "SUPPORT", "SUPERSEDE", "delete", "keep", "remove", "add"):
        assert not re.search(rf"\b{action}\b", text, re.IGNORECASE), action
    with pytest.raises(ValueError):
        ReproposalNotice(findings=())


def test_the_refusal_event_is_audit_only_and_changes_no_state() -> None:
    assert EVENT_PAYLOAD_TYPES[EventType.STRUCTURAL_REFUSAL_RECORDED] is StructuralRefusalPayload
    world = World(_c8_plan(fail=("EV-NOTE",)))
    world.delta(REFUND_T1)
    before = world.governor.state()
    world.governor.record_structural_refusal(_any_refusal())
    after = world.governor.state()
    assert after.last_sequence == before.last_sequence + 1
    bookkeeping = {"revision", "last_sequence", "source_events"}
    for field in type(before).model_fields:
        if field not in bookkeeping:
            assert getattr(after, field) == getattr(before, field), field
    assert replay(PROJECT, world.store.load(PROJECT)) == after


def _any_refusal() -> StructuralRefusal:
    return StructuralRefusal(
        engine=RefusalEngine.IE2_CLAIM_ASSIMILATION,
        mode=ExecutionMode.PRODUCTION,
        attempt=1,
        request_sha256="0" * 64,
        reasoner=ReasonerFingerprint(provider="xai", model="m", policy_version="p"),
        findings=("UNACCOUNTED_PROPOSITION: P1",),
        codes=("UNACCOUNTED_PROPOSITION",),
        reproposable=True,
        proposal_json="{}",
    )


# ================================================================== IE2 policy identity


def test_the_ie2_reproposing_policy_has_its_own_identity() -> None:
    assert REPROPOSAL_POLICY_VERSION == "intent-v2-locus-v5"
    assert (
        _sha(REPROPOSAL_SYSTEM_INSTRUCTION)
        == REPROPOSAL_SYSTEM_INSTRUCTION_SHA256
        == ("cc913e3d7aee49e13e2e40745ddc791df0dee0e663893f42be39a475e16a09dc")
    )
    assert REPROPOSAL_SYSTEM_INSTRUCTION.startswith(PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION)
    assert "REFUSED PROPOSALS" in REPROPOSAL_SYSTEM_INSTRUCTION.removeprefix(
        PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION
    )
    assert _sha(PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION) == (
        PROPOSITION_ACCOUNTING_SYSTEM_INSTRUCTION_SHA256
    )
    cls = XAIReproposingSemanticReasoner
    assert cls.policy_version == REPROPOSAL_POLICY_VERSION
    assert cls.accepts_reproposal is True and cls.draft_payload is AccountedDraftPayload
    for earlier in (XAIPropositionAccountingSemanticReasoner, XAICanonicalFacetSemanticReasoner):
        assert earlier.accepts_reproposal is False, earlier.__name__


def _request(**overrides: Any) -> ReasoningRequest:
    fields: dict[str, Any] = {
        "project_id": PROJECT,
        "evidence": (_evidence("EV-1", "Operators may cancel a job."),),
        "allowed_judgment_kinds": frozenset({JudgmentKind.ASSERT_CLAIM}),
        "accountable_evidence_ids": ("EV-1",),
    }
    fields.update(overrides)
    return ReasoningRequest(**fields)


def test_only_the_reproposing_policy_renders_the_notice_and_only_on_attempt_two() -> None:
    notice = ReproposalNotice(findings=("UNACCOUNTED_PROPOSITION: P1",))
    retry = _request(reproposal=notice)
    first = _request()
    assert "previous_proposal_refused" not in render_request(retry, include_sentence_index=True)
    rendered = json.loads(
        render_request(retry, include_sentence_index=True, include_reproposal_notice=True)
    )
    assert rendered["previous_proposal_refused"] == {
        "refused_attempt": 1,
        "findings": ["UNACCOUNTED_PROPOSITION: P1"],
        "notice": notice.text(),
    }
    plain = render_request(first, include_sentence_index=True, include_reproposal_notice=True)
    assert "previous_proposal_refused" not in plain
    rendered.pop("previous_proposal_refused")
    assert rendered == json.loads(plain)


def test_a_policy_that_cannot_receive_a_notice_refuses_it_before_any_call() -> None:
    reasoner = Scripted(
        lambda request: {"drafts": []}, cls=XAIPropositionAccountingSemanticReasoner
    )
    with pytest.raises(XAISemanticReasonerError, match="cannot receive a re-proposal"):
        reasoner.propose(
            _request(reproposal=ReproposalNotice(findings=("UNACCOUNTED_PROPOSITION: P1",)))
        )
    assert reasoner.requests == []


# ================================================================== IE2 end to end


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


Action = tuple[str, str]


class Plan:
    """The scripted model: Call 1 names concerns; Call 2 accounts for every sentence, except
    that attempt 1 (no notice) omits ``omit`` propositions or answers nothing for ``fail``
    documents. ``fail_again`` makes attempt 2 repeat the defect."""

    def __init__(
        self,
        concern_of: dict[str, str],
        propositions: dict[str, list[tuple[str, tuple[int, ...], Action]]],
        non_operative: dict[str, tuple[int, ...]],
        *,
        omit: frozenset[str] = frozenset(),
        fail: tuple[str, ...] = (),
        fail_again: bool = False,
    ) -> None:
        self.concern_of = concern_of
        self.propositions = propositions
        self.non_operative = non_operative
        self.omit = omit
        self.fail = fail
        self.fail_again = fail_again

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
        defective = request.reproposal is None or self.fail_again
        by_predicate = {c.predicate: c.claim_id for c in request.known_claims}
        propositions, silent, drafts = [], [], []
        for ev in request.accountable_evidence_ids:
            if defective and ev in self.fail:
                continue
            text = next(e.content for e in request.evidence if e.evidence_id == ev)
            ids = [sid for sid, _ in numbered_sentences(ev, text)]
            for pid, sentences, (action, target) in self.propositions.get(ev, []):
                propositions.append(
                    {
                        "proposition_id": pid,
                        "sentence_ids": [ids[s - 1] for s in sentences],
                        "statement": f"statement {pid}",
                    }
                )
                if defective and pid in self.omit:
                    continue
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
                else:
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


class Scripted(XAIReproposingSemanticReasoner):
    """A production adapter (by default the re-proposing policy) with a scripted transport."""

    def __init__(
        self,
        reply: Callable[[ReasoningRequest], dict[str, Any]],
        cls: type[XAIPropositionAccountingSemanticReasoner] | None = None,
    ) -> None:
        if cls is not None:
            self.__class__ = type(
                f"Scripted{cls.__name__}",
                (Scripted, cls),
                {
                    "policy_version": cls.policy_version,
                    "system_instruction": cls.system_instruction,
                    "accepts_reproposal": cls.accepts_reproposal,
                },
            )
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
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            cost_usd=0.001,
        )


class World:
    def __init__(
        self, plan: Plan, *, cls: type[XAIPropositionAccountingSemanticReasoner] | None = None
    ) -> None:
        ids = count(1)
        self.store = InMemoryEventStore()
        self.governor = SemanticGovernor(
            store=self.store,
            project_id=PROJECT,
            policy=AdmissionPolicy(canonical_facets=True),
            clock=lambda: AT,
            id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
        )
        self.reasoner = Scripted(plan.reply, cls=cls)

    def delta(self, *items: EvidenceItem, mode: ExecutionMode | None = None) -> Any:
        # PRODUCTION requires semantic completeness verification (ie2-verified-assimilation-v1,
        # 2026-09-30): an independent scripted verifier that finds every proposition complete.
        return assimilate_delta(
            governor=self.governor,
            reasoner=self.reasoner,
            delta=items,
            scope=SCOPE,
            mode=mode,
            verifier=ScriptedVerifier(all_complete) if mode is ExecutionMode.PRODUCTION else None,
        )

    def live_predicates(self) -> set[str]:
        state = self.governor.state().semantic
        active = active_judgment_ids(state)
        return {c.predicate for c in state.claims.values() if c.created_by_judgment_id in active}

    def refusals(self) -> list[StructuralRefusal]:
        return [
            e.event.payload.refusal
            for e in self.store.load(PROJECT)
            if isinstance(e.event.payload, StructuralRefusalPayload)
        ]

    def refusal_events(self) -> list[Any]:
        return [
            e
            for e in self.store.load(PROJECT)
            if e.event.event_type is EventType.STRUCTURAL_REFUSAL_RECORDED
        ]

    def claim_calls(self) -> list[ReasoningRequest]:
        return [
            r
            for r in self.reasoner.requests
            if JudgmentKind.CREATE_ADDRESS not in r.allowed_judgment_kinds
        ]


H1 = _evidence("EV-H-T1", SECTION_TEXT[(1, "H")])
H9 = _evidence("EV-H-T9", SECTION_TEXT[(9, "H")])
CANCEL = "Job cancellation"


def _c09_plan(**kwargs: Any) -> Plan:
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
                ("H-5", (3,), ("ASSERT", CANCEL)),
            ],
        },
        non_operative={"EV-H-T1": (5, 6), "EV-H-T9": (7, 8)},
        **kwargs,
    )


def test_c09_production_omission_is_refused_then_one_reproposal_is_accepted() -> None:
    world = World(_c09_plan(omit=frozenset({"H-5"})))
    world.delta(H1, mode=ExecutionMode.PRODUCTION)
    assert world.live_predicates() == {"H-1", "H-2", "H-3"}
    outcome = world.delta(H9, mode=ExecutionMode.PRODUCTION)

    assert outcome.calls_made == MAX_PRODUCTION_CALLS_PER_DELTA == 4  # + Call 3 (verification)
    assert world.live_predicates() == {"H-1", "H-2", "H-3", "H-4", "H-5"}
    (refusal,) = world.refusals()
    assert refusal.attempt == 1 and refusal.mode is ExecutionMode.PRODUCTION
    assert refusal.findings == ("UNACCOUNTED_PROPOSITION: H-5",)
    assert refusal.codes == ("UNACCOUNTED_PROPOSITION",) and refusal.reproposable
    assert refusal.reasoner.policy_version == "intent-v2-locus-v5"
    assert refusal.invocation_id in {r.invocation_id for r in world.reasoner.receipts}
    refused = AccountedDraftPayload.model_validate_json(refusal.proposal_json)
    assert "H-5" in {p.proposition_id for p in refused.propositions}
    assert "H-5" not in {getattr(d, "proposition_id", None) for d in refused.drafts}
    assert outcome.refused_attempts == (refusal,)

    attempt_1, attempt_2 = world.claim_calls()[-2:]
    assert attempt_1.reproposal is None
    assert attempt_2.reproposal == ReproposalNotice(findings=("UNACCOUNTED_PROPOSITION: H-5",))
    assert attempt_2.model_copy(update={"reproposal": None}) == attempt_1


def test_the_refused_attempt_survives_in_history_and_nothing_of_it_was_applied() -> None:
    world = World(_c09_plan(omit=frozenset({"H-5"})))
    world.delta(H1, mode=ExecutionMode.PRODUCTION)
    world.delta(H9, mode=ExecutionMode.PRODUCTION)
    state = world.governor.state().semantic
    (refusal_event,) = world.refusal_events()
    applied_after = [
        e
        for e in world.store.load(PROJECT)
        if e.sequence > refusal_event.sequence
        and e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
    ]
    applied_before = [
        e
        for e in world.store.load(PROJECT)
        if e.sequence < refusal_event.sequence
        and e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
    ]
    kinds_before_refusal_in_delta = {
        e.event.payload.judgment.proposal.kind for e in applied_before[-1:]
    }
    assert kinds_before_refusal_in_delta == {JudgmentKind.BIND_TO_ADDRESS}
    assert len(applied_after) == 5
    assert (
        sum(1 for j in state.judgments.values() if j.proposal.kind is JudgmentKind.SUPPORTS_CLAIM)
        == 3
    )


@pytest.mark.parametrize("mode", [None, ExecutionMode.CERTIFICATION, ExecutionMode.EXPERIMENT])
def test_c09_certification_and_experiment_stop_after_attempt_one(
    mode: ExecutionMode | None,
) -> None:
    world = World(_c09_plan(omit=frozenset({"H-5"})))
    world.delta(H1, mode=mode)
    with pytest.raises(PropositionAccountingError) as refused:
        world.delta(H9, mode=mode)
    assert refused.value.findings == ("UNACCOUNTED_PROPOSITION: H-5",)
    assert len(world.claim_calls()) == 2
    assert world.refusals() == []
    assert world.live_predicates() == {"H-1", "H-2", "H-3"}


REFUND, SUPPLIER = "Refund of returned order items", "Supplier overpayment repayment"
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


def _c8_plan(**kwargs: Any) -> Plan:
    return Plan(
        concern_of={"EV-REFUND": REFUND, "EV-SUPPLIER": SUPPLIER, "EV-NOTE": REFUND},
        propositions={
            "EV-REFUND": [("CR-1", (1,), ("ASSERT", REFUND))],
            "EV-SUPPLIER": [("SO-1", (1,), ("ASSERT", SUPPLIER))],
            "EV-NOTE": [("CR-2", (1,), ("ASSERT", REFUND))],
        },
        non_operative={},
        **kwargs,
    )


def test_c8_production_empty_response_is_refused_then_one_reproposal_is_accepted() -> None:
    world = World(_c8_plan(fail=("EV-NOTE",)))
    world.delta(REFUND_T1, SUPPLIER_T1, mode=ExecutionMode.PRODUCTION)
    outcome = world.delta(NOTE, mode=ExecutionMode.PRODUCTION)
    assert outcome.calls_made == 4  # Call 1, Call 2, its one re-proposal, Call 3
    assert world.live_predicates() == {"CR-1", "SO-1", "CR-2"}
    (refusal,) = world.refusals()
    assert refusal.findings == ("UNACCOUNTED_SENTENCE: EV-NOTE#S1",)
    assert json.loads(refusal.proposal_json)["drafts"] == []


def test_a_second_refusal_stops_records_both_attempts_and_never_makes_a_third_call() -> None:
    world = World(_c8_plan(fail=("EV-NOTE",), fail_again=True))
    world.delta(REFUND_T1, SUPPLIER_T1, mode=ExecutionMode.PRODUCTION)
    before = world.live_predicates()
    with pytest.raises(PropositionAccountingError):
        world.delta(NOTE, mode=ExecutionMode.PRODUCTION)
    assert len(world.claim_calls()) == 3  # T1's Call 2, then attempts 1 and 2 of T2
    first, second = world.refusals()
    (first_event, _) = world.refusal_events()
    assert (first.attempt, second.attempt) == (1, 2)
    assert second.reproposal_of == first_event.event.event_id
    assert second.notice == ReproposalNotice(findings=first.findings)
    assert first.request_sha256 == second.request_sha256
    assert world.live_predicates() == before


def test_a_policy_that_cannot_reproposes_is_recorded_and_stops() -> None:
    world = World(_c8_plan(fail=("EV-NOTE",)), cls=XAIPropositionAccountingSemanticReasoner)
    world.delta(REFUND_T1, SUPPLIER_T1, mode=ExecutionMode.PRODUCTION)
    with pytest.raises(PropositionAccountingError):
        world.delta(NOTE, mode=ExecutionMode.PRODUCTION)
    (refusal,) = world.refusals()
    assert refusal.reasoner.policy_version == "intent-v2-locus-v4"
    assert len(world.claim_calls()) == 2


def test_a_schema_violation_is_not_reproposed() -> None:
    def bad(request: ReasoningRequest) -> dict[str, Any]:
        reply = _c8_plan().reply(request)
        if JudgmentKind.CREATE_ADDRESS not in request.allowed_judgment_kinds:
            reply["unexpected"] = True
        return reply

    world = World(_c8_plan())
    world.reasoner = Scripted(bad)
    with pytest.raises(SemanticOutputError) as refused:
        world.delta(REFUND_T1, mode=ExecutionMode.PRODUCTION)
    assert not isinstance(refused.value, ReasonerResponseRefused)
    assert world.refusals() == [] and len(world.claim_calls()) == 1


def test_a_scorer_or_reasoner_failure_that_is_not_a_structural_refusal_is_not_reproposed() -> None:
    def scorer_disagrees(request: ReasoningRequest) -> dict[str, Any]:
        if JudgmentKind.CREATE_ADDRESS not in request.allowed_judgment_kinds:
            raise ValueError("semantic scorer: undesirable meaning")
        return _c8_plan().reply(request)

    world = World(_c8_plan())
    world.reasoner = Scripted(scorer_disagrees)
    with pytest.raises(ValueError, match="semantic scorer"):
        world.delta(REFUND_T1, mode=ExecutionMode.PRODUCTION)
    assert world.refusals() == [] and len(world.claim_calls()) == 1


def test_an_admission_reject_is_never_reproposed() -> None:
    """A judgment-level REJECT (here: a byte-identical re-assertion of a live claim) is an
    admission outcome, not a response refusal: the delta completes in two calls."""

    def reassert(request: ReasoningRequest) -> dict[str, Any]:
        reply = _c8_plan().reply(request)
        if (
            JudgmentKind.CREATE_ADDRESS not in request.allowed_judgment_kinds
            and request.known_claims
        ):
            (claim,) = [c for c in request.known_claims if c.predicate == "CR-1"]
            reply["drafts"] = [
                {
                    "kind": "ASSERT_CLAIM",
                    "proposition_id": "CR-2",
                    "address_id": claim.address_id,
                    "predicate": "CR-1",
                    "value": {"kind": "TEXT", "text": "claim CR-1"},
                    "evidence_ids": ["EV-NOTE"],
                    "rationale": "x",
                }
            ]
        return reply

    world = World(_c8_plan())
    world.reasoner = Scripted(reassert)
    world.delta(REFUND_T1, mode=ExecutionMode.PRODUCTION)
    outcome = world.delta(NOTE, mode=ExecutionMode.PRODUCTION)
    routes = [d.route.value for d in outcome.stage_decisions[1]]
    assert routes == ["REJECT"] and outcome.calls_made == 3 and world.refusals() == []


# ================================================================== isolation


def test_experiment_and_certification_code_never_names_production_mode() -> None:
    roots = [ROOT / "src/foundry/experiments", ROOT / "tests/certification", ROOT / "scripts"]
    mutation_table = ROOT / "scripts/ie2_mutants.py"  # mutant text, never a caller
    offenders = [
        str(path.relative_to(ROOT))
        for root in roots
        for path in root.rglob("*.py")
        if path != mutation_table
        and (
            "ExecutionMode.PRODUCTION" in path.read_text()
            or "mode=ExecutionMode" in path.read_text()
        )
    ]
    assert offenders == []


def test_an_experiment_recording_wrapper_cannot_enable_a_reproposal() -> None:
    """Even if PRODUCTION were passed, the sealed-experiment recording wrapper is not a policy
    that accepts re-proposals, so the refusal is recorded and nothing is re-asked; and its
    budget refuses any third call per delta."""
    from foundry.experiments.locus_validation_v4.recording import RecordingReasoner, RunBudget

    world = World(_c8_plan(fail=("EV-NOTE",)))
    wrapper = RecordingReasoner(
        world.reasoner, ledger="core", budget=RunBudget(), guard_identity=False
    )
    assert getattr(type(wrapper), "accepts_reproposal", False) is False
    wrapper.begin_delta(1)
    # Since 2026-09-30 PRODUCTION verifies semantic completeness, and a sealed-experiment
    # wrapper exposes no proposition accounting: it cannot run PRODUCTION at all, so it can
    # never enable a re-proposal. Refused before anything is written.
    with pytest.raises(SemanticCompletenessRequired):
        assimilate_delta(
            governor=world.governor,
            reasoner=wrapper,
            delta=(REFUND_T1, SUPPLIER_T1),
            scope=SCOPE,
            mode=ExecutionMode.PRODUCTION,
            verifier=ScriptedVerifier(all_complete),
        )
    assert world.store.load(PROJECT) == () and world.claim_calls() == []


# ================================================================== IE3 end to end


class ScriptedGraph:
    """A re-proposing graph synthesizer with a scripted model: attempt 1 is the grounded C-1
    shape (a correct replacement plus a parallel NEW node from the same claim); attempt 2,
    asked with the notice, is the replacement alone."""

    def __init__(self, *, repeat: bool = False) -> None:
        self.repeat = repeat
        self.calls: list[tuple[IntentGraphSynthesisRequest, ReproposalNotice | None]] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return ReasonerFingerprint(
            provider="xai", model="grok-4.7", policy_version=GRAPH_SYNTHESIS_POLICY_VERSION
        )

    @property
    def reproposal_fingerprint(self) -> ReasonerFingerprint:
        return ReasonerFingerprint(
            provider="xai", model="grok-4.7", policy_version=GRAPH_REPROPOSAL_POLICY_VERSION
        )

    def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult:
        self.calls.append((request, None))
        return _graph(request, parallel=True)

    def resynthesize(
        self, request: IntentGraphSynthesisRequest, notice: ReproposalNotice
    ) -> IntentGraphSynthesisResult:
        self.calls.append((request, notice))
        return _graph(request, parallel=self.repeat)


def _graph(request: IntentGraphSynthesisRequest, *, parallel: bool) -> IntentGraphSynthesisResult:
    (claim,) = [c.claim_id for locus in request.basis for c in locus.live_claims]
    stale = next(o.object_id for o in request.known_objects if o.is_stale)
    goal = next(o.object_id for o in request.known_objects if o.kind.value == "GOAL")

    def wired(local: str) -> list[dict[str, Any]]:
        return [
            {
                "source": {"local_id": local},
                "relation_type": "DERIVED_FROM",
                "target": {"namespace": "basis", "claim_id": claim},
            },
            {
                "source": {"local_id": local},
                "relation_type": "SERVES",
                "target": {"namespace": "existing", "object_id": goal},
            },
        ]

    nodes = [
        {
            "local_id": {"local_id": "req-replaces"},
            "kind": "REQUIREMENT",
            "disposition": "REPLACES_STALE",
            "replaces": {"namespace": "existing", "object_id": stale},
            "proposal_rationale": "the corrected window",
            "statement": "Refund requests are accepted within fourteen days of purchase.",
        }
    ]
    relations = wired("req-replaces")
    if parallel:
        nodes.append(
            {
                "local_id": {"local_id": "req-new"},
                "kind": "REQUIREMENT",
                "disposition": "NEW",
                "proposal_rationale": "the same window",
                "statement": "Refund requests are accepted within fourteen days of purchase.",
            }
        )
        relations += wired("req-new")
    return IntentGraphSynthesisResult.model_validate({"nodes": nodes, "relations": relations})


def _run_graph(synthesizer: ScriptedGraph, mode: ExecutionMode | None) -> tuple[Any, Any]:
    substrate = build_graph_case_c()
    outcome = synthesize_intent_graph(
        substrate.store,
        project_id=substrate.project_id if hasattr(substrate, "project_id") else "PROJ-CERT",
        scope="payments",
        synthesizer=synthesizer,
        clock=lambda: AT,
        synthesis_run_id_factory=lambda: "RUN-1",
        mode=mode,
    )
    return substrate, outcome


def _graph_events(substrate: Any) -> list[Any]:
    return list(substrate.store.load("PROJ-CERT"))


@pytest.fixture
def certified_reproposal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for a future certification of the graph re-proposal identity."""
    monkeypatch.setattr(
        graph_module,
        "CERTIFIED_GRAPH_REPROPOSAL_POLICY_VERSIONS",
        frozenset({GRAPH_REPROPOSAL_POLICY_VERSION}),
    )


def test_the_c1_parallel_node_is_refused_then_one_certified_reproposal_is_decided(
    certified_reproposal: None,
) -> None:
    synthesizer = ScriptedGraph()
    substrate, outcome = _run_graph(synthesizer, ExecutionMode.PRODUCTION)
    (first, _), (second, notice) = synthesizer.calls
    assert first == second and notice is not None
    assert notice.findings[0].startswith("PARALLEL_NODE: 'req-new' (NEW) and 'req-replaces'")
    events = _graph_events(substrate)
    refusal_event, decision_event = events[-2:]
    assert refusal_event.event.event_type is EventType.STRUCTURAL_REFUSAL_RECORDED
    refusal = refusal_event.event.payload.refusal
    assert refusal.engine is RefusalEngine.IE3_GRAPH_SYNTHESIS
    assert refusal.codes == ("PARALLEL_NODE",) and refusal.attempt == 1
    assert refusal.reasoner.policy_version == GRAPH_SYNTHESIS_POLICY_VERSION
    assert len(json.loads(refusal.proposal_json)["nodes"]) == 2
    assert decision_event.event.event_type is EventType.INTENT_GRAPH_SYNTHESIS_DECIDED
    payload = decision_event.event.payload
    assert payload.author.policy_version == GRAPH_REPROPOSAL_POLICY_VERSION
    assert [n.local_id.local_id for n in payload.result.nodes] == ["req-replaces"]
    assert outcome.decision is not None


def test_production_graph_reproposal_is_not_certified_so_it_records_and_stops() -> None:
    synthesizer = ScriptedGraph()
    with pytest.raises(IntentGraphResultError, match="PARALLEL_NODE"):
        _run_graph(synthesizer, ExecutionMode.PRODUCTION)
    assert len(synthesizer.calls) == 1


@pytest.mark.parametrize("mode", [None, ExecutionMode.CERTIFICATION, ExecutionMode.EXPERIMENT])
def test_c1_stays_a_single_attempt_failure_outside_production(
    mode: ExecutionMode | None, certified_reproposal: None
) -> None:
    synthesizer = ScriptedGraph()
    substrate = build_graph_case_c()
    before = len(list(substrate.store.load("PROJ-CERT")))
    with pytest.raises(IntentGraphResultError, match="PARALLEL_NODE"):
        synthesize_intent_graph(
            substrate.store,
            project_id="PROJ-CERT",
            scope="payments",
            synthesizer=synthesizer,
            clock=lambda: AT,
            synthesis_run_id_factory=lambda: "RUN-1",
            mode=mode,
        )
    assert len(synthesizer.calls) == 1
    assert len(list(substrate.store.load("PROJ-CERT"))) == before  # refused before any mutation


def test_a_second_graph_refusal_is_recorded_and_there_is_no_third_attempt(
    certified_reproposal: None,
) -> None:
    synthesizer = ScriptedGraph(repeat=True)
    substrate = build_graph_case_c()
    with pytest.raises(IntentGraphResultError, match="PARALLEL_NODE"):
        synthesize_intent_graph(
            substrate.store,
            project_id="PROJ-CERT",
            scope="payments",
            synthesizer=synthesizer,
            clock=lambda: AT,
            synthesis_run_id_factory=lambda: "RUN-1",
            mode=ExecutionMode.PRODUCTION,
        )
    assert len(synthesizer.calls) == 2
    refusals = [
        e.event.payload.refusal
        for e in substrate.store.load("PROJ-CERT")
        if e.event.event_type is EventType.STRUCTURAL_REFUSAL_RECORDED
    ]
    assert [r.attempt for r in refusals] == [1, 2]
    assert refusals[1].reasoner.policy_version == GRAPH_REPROPOSAL_POLICY_VERSION
    assert refusals[1].notice is not None and refusals[1].reproposal_of is not None
    assert not [
        e
        for e in substrate.store.load("PROJ-CERT")
        if e.event.event_type is EventType.INTENT_GRAPH_SYNTHESIS_DECIDED
    ]


def test_the_graph_notice_message_carries_the_findings_only() -> None:
    notice = ReproposalNotice(findings=("PARALLEL_NODE: 'req-new' (NEW) and 'req-replaces'",))
    rendered = json.loads(render_graph_reproposal_notice(notice))
    assert rendered == {
        "previous_proposal_refused": {
            "refused_attempt": 1,
            "findings": list(notice.findings),
            "notice": notice.text(),
        }
    }


class RecordedC1:
    """Returns the exact recorded Grok exam-v5 case C attempt 1 answer, rebased onto the
    substrate's ids (its NEW node has no relation; refused NO_RELEVANCE, not allowlisted)."""

    def __init__(self) -> None:
        self.calls = 0
        self.inner = ScriptedGraph()

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self.inner.fingerprint

    @property
    def reproposal_fingerprint(self) -> ReasonerFingerprint:
        return self.inner.reproposal_fingerprint

    def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult:
        self.calls += 1
        full = _graph(request, parallel=True).model_dump(mode="json")
        full["relations"] = [r for r in full["relations"] if r["source"]["local_id"] != "req-new"]
        return IntentGraphSynthesisResult.model_validate(full)

    def resynthesize(
        self, request: IntentGraphSynthesisRequest, notice: ReproposalNotice
    ) -> IntentGraphSynthesisResult:
        self.calls += 1
        return _graph(request, parallel=False)


def test_a_graph_refusal_off_the_allowlist_is_recorded_and_never_reproposed(
    certified_reproposal: None,
) -> None:
    synthesizer = RecordedC1()
    substrate = build_graph_case_c()
    with pytest.raises(IntentGraphResultError, match="NO_RELEVANCE"):
        synthesize_intent_graph(
            substrate.store,
            project_id="PROJ-CERT",
            scope="payments",
            synthesizer=synthesizer,
            clock=lambda: AT,
            synthesis_run_id_factory=lambda: "RUN-1",
            mode=ExecutionMode.PRODUCTION,
        )
    assert synthesizer.calls == 1
    (refusal,) = [
        e.event.payload.refusal
        for e in substrate.store.load("PROJ-CERT")
        if e.event.event_type is EventType.STRUCTURAL_REFUSAL_RECORDED
    ]
    assert refusal.codes == ("NO_RELEVANCE",) and refusal.reproposable is False
