"""9P2 T5: interleaved three-arm runner and global fail-fast budgets (spec §4, §7-§9,
§12, §16; brief T5; clarifications C2, C4, C5).

Every reasoner here is a scripted fake that derives structurally valid judgments from
the request it is shown (or raises a scripted exception); every ledger is a real
``SemanticGovernor`` over an ``InMemoryEventStore``. The runner feeds the frozen
Kestrel evidence into those fakes; the fakes' own wording is opaque. ZERO live calls;
sockets are blocked.
"""

from __future__ import annotations

import ast
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    POLICY_VERSION,
    SemanticOutputError,
    XAIProviderError,
)
from foundry.application.context_errors import ContextUnsupported
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionRoute
from foundry.domain.common import Authority, FrozenModel
from foundry.domain.events import EventType
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.experiments.contrastive_unseen import integrity
from foundry.experiments.contrastive_unseen import runner as runner_module
from foundry.experiments.contrastive_unseen.authority import (
    HUMAN_FINGERPRINT,
    AuthorizationOutcome,
)
from foundry.experiments.contrastive_unseen.records import RecordingReasoner
from foundry.experiments.contrastive_unseen.runner import (
    A_PROJECT_ID,
    F_PROJECT_ID,
    ROOT_SEEDS,
    ArmSummary,
    BudgetedReasoner,
    BudgetSnapshot,
    ExperimentBudget,
    ExperimentBudgetExceeded,
    RunResult,
    RunStatus,
    StepRecord,
    build_arm_reasoners,
    r_project_id,
    run_experiment,
)
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    TIMELINE,
)
from foundry.ports.semantic_reasoner import ComparisonContext, ReasoningRequest

T0 = datetime(2026, 9, 12, tzinfo=UTC)
FINGERPRINT = ReasonerFingerprint(provider="fake", model="fake-model", policy_version="fake-v0")
PACKAGE_DIR = Path(runner_module.__file__).parent
RUNNER_SOURCE = Path(runner_module.__file__).read_text(encoding="utf-8")

SEED_A, SEED_B, SEED_N = "EV-K-A1", "EV-K-B1", "EV-K-N1"
T1_EVIDENCE_IDS = (SEED_A, SEED_B, SEED_N)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- fakes ------------------------------------------------------------------------


class FakeReceipt(FrozenModel):
    """Adapter-style economics of one scripted call; ``cost_usd`` is what the runner reads."""

    invocation_id: str
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0


def _create_id(evidence_id: str) -> str:
    return f"J-create-{evidence_id}"


def _bind_id(evidence_id: str) -> str:
    return f"J-bind-{evidence_id}"


def _claim_id(evidence_id: str) -> str:
    return f"J-claim-{evidence_id}"


def _supersede_id(evidence_id: str) -> str:
    return f"J-supersede-{evidence_id}"


class LifecycleScript:
    """Structurally valid judgments derived only from the request shown to it.

    Call 1 (CREATE/BIND allowed): for each cited evidence item, BIND to the address
    this script remembers for the item's predecessor when that address is among the
    request's known addresses, else CREATE a fresh address. Call 2: ASSERT one claim per
    cited item at the address chosen in Call 1 and, when the predecessor's claim is
    among the request's known claims, propose one SUPERSEDE targeting the predecessor's
    creating judgment. Wording is opaque; ids are structural.
    """

    def __init__(self, fingerprint: ReasonerFingerprint = FINGERPRINT) -> None:
        self._fingerprint = fingerprint
        self._address_of: dict[tuple[str, str], str] = {}

    def __call__(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            return self._call_one(request)
        return self._call_two(request)

    def _judgment(
        self, request: ReasoningRequest, judgment_id: str, proposal: JudgmentProposal
    ) -> SemanticJudgment:
        return SemanticJudgment(
            judgment_id=judgment_id,
            project_id=request.project_id,
            proposal=proposal,
            visible_evidence_ids=tuple(item.evidence_id for item in request.evidence),
            rationale=f"Opaque rationale for {judgment_id}.",
            reasoner=self._fingerprint,
            invocation_id=f"INV-{judgment_id}",
            proposed_at=T0,
        )

    def _call_one(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        known = {address.address_id for address in request.known_addresses}
        judgments: list[SemanticJudgment] = []
        for item in request.evidence:
            candidate = SemanticCandidate(
                candidate_id=f"CAND-{item.evidence_id}",
                subject=f"subject {item.evidence_id}",
                facet="lifecycle",
                scope=item.scope,
                evidence_ids=(item.evidence_id,),
            )
            predecessor = item.supersedes_evidence_id
            prior = (
                self._address_of.get((request.project_id, predecessor))
                if predecessor is not None
                else None
            )
            if prior is not None and prior in known:
                judgment_id = _bind_id(item.evidence_id)
                proposal: JudgmentProposal = BindToAddressProposal(
                    candidate=candidate, address_id=prior
                )
                address_id = prior
            else:
                judgment_id = _create_id(item.evidence_id)
                proposal = CreateAddressProposal(candidate=candidate)
                address_id = address_id_for(request.project_id, judgment_id)
            self._address_of[(request.project_id, item.evidence_id)] = address_id
            judgments.append(self._judgment(request, judgment_id, proposal))
        return tuple(judgments)

    def _call_two(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        known_creators = {claim.created_by_judgment_id for claim in request.known_claims}
        judgments: list[SemanticJudgment] = []
        for item in request.evidence:
            address_id = self._address_of[(request.project_id, item.evidence_id)]
            judgments.append(
                self._judgment(
                    request,
                    _claim_id(item.evidence_id),
                    AssertClaimProposal(
                        address_id=address_id,
                        predicate="policy_value",
                        value=ClaimValue(
                            kind=ClaimValueKind.TEXT, text=f"value {item.evidence_id}"
                        ),
                        evidence_ids=(item.evidence_id,),
                        authority=Authority.OBSERVED,
                    ),
                )
            )
            predecessor = item.supersedes_evidence_id
            if predecessor is not None and _claim_id(predecessor) in known_creators:
                judgments.append(
                    self._judgment(
                        request,
                        _supersede_id(item.evidence_id),
                        SupersedeProposal(
                            target_judgment_id=_claim_id(predecessor),
                            reason="Opaque supersession reason.",
                        ),
                    )
                )
        return tuple(judgments)


type Batch = (
    tuple[SemanticJudgment, ...]
    | Callable[[ReasoningRequest], tuple[SemanticJudgment, ...]]
    | BaseException
)


class ScriptedReasoner:
    """Runs ``LifecycleScript`` per call unless an override is scripted for that call.

    Records every request; appends ``receipts_per_call`` fake receipts of ``cost``
    after each forwarded call when ``cost`` is given; optionally logs to ``trace``.
    """

    def __init__(
        self,
        *,
        label: str,
        overrides: dict[int, Batch] | None = None,
        cost: float | None = None,
        receipts_per_call: int = 1,
        trace: list[str] | None = None,
    ) -> None:
        self._script = LifecycleScript()
        self._overrides = overrides or {}
        self._cost = cost
        self._receipts_per_call = receipts_per_call
        self._trace = trace
        self._label = label
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[FakeReceipt] = []
        self._drafts: list[str] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return FINGERPRINT

    @property
    def receipts(self) -> tuple[FakeReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[str, ...]:
        return tuple(self._drafts)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if self._trace is not None:
            self._trace.append(f"call:{self._label}:{index + 1}")
        if self._cost is not None:
            for extra in range(self._receipts_per_call):
                self._receipts.append(
                    FakeReceipt(
                        invocation_id=f"{self._label}-{index + 1}-{extra}", cost_usd=self._cost
                    )
                )
        self._drafts.append(f"draft:{self._label}:{index + 1}")
        batch = self._overrides.get(index)
        if batch is None:
            return self._script(request)
        if isinstance(batch, BaseException):
            raise batch
        if callable(batch):
            return batch(request)
        return batch


class Harness:
    """Three scripted inner reasoners wrapped through ``build_arm_reasoners``."""

    def __init__(
        self,
        *,
        f_overrides: dict[int, Batch] | None = None,
        a_overrides: dict[int, Batch] | None = None,
        r_overrides: dict[int, Batch] | None = None,
        cost: float | None = None,
        receipts_per_call: int = 1,
        budget: ExperimentBudget | None = None,
    ) -> None:
        self.trace: list[str] = []
        self.inner_f = ScriptedReasoner(
            label="F",
            overrides=f_overrides,
            cost=cost,
            receipts_per_call=receipts_per_call,
            trace=self.trace,
        )
        self.inner_a = ScriptedReasoner(
            label="A",
            overrides=a_overrides,
            cost=cost,
            receipts_per_call=receipts_per_call,
            trace=self.trace,
        )
        self.inner_r = ScriptedReasoner(
            label="R",
            overrides=r_overrides,
            cost=cost,
            receipts_per_call=receipts_per_call,
            trace=self.trace,
        )
        self.budget = budget if budget is not None else ExperimentBudget()
        self.reasoners = build_arm_reasoners(
            inner_f=self.inner_f, inner_a=self.inner_a, inner_r=self.inner_r, budget=self.budget
        )

    def call_counts(self) -> tuple[int, int, int]:
        return len(self.inner_f.requests), len(self.inner_a.requests), len(self.inner_r.requests)

    def run(self) -> RunResult:
        clock = _clock()
        return run_experiment(
            reasoner_f=self.reasoners.f,
            reasoner_a=self.reasoners.a,
            reasoner_r=self.reasoners.r,
            clock=lambda: next(clock),
            id_factory=_counter_id_factory(),
        )


# --- builders ---------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0 + timedelta(minutes=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _steps_for(result: RunResult, arm: str) -> list[StepRecord]:
    return [step for step in result.steps if step.arm == arm]


def _step(result: RunResult, arm: str, t: int) -> StepRecord:
    (step,) = [s for s in result.steps if s.arm == arm and s.t == t]
    return step


def _position(arm: str, t: int) -> int:
    return ARM_SCHEDULE.index((t, arm))


def _budgeted(
    inner: ScriptedReasoner, budget: ExperimentBudget, *, arm: str = "F"
) -> BudgetedReasoner:
    return BudgetedReasoner(RecordingReasoner(inner, arm=arm), budget)


def _request(project_id: str = F_PROJECT_ID) -> ReasoningRequest:
    return ReasoningRequest(project_id=project_id, evidence=(TIMELINE[0].item,))


# --- schedule and calls -----------------------------------------------------------


def test_completed_run_follows_frozen_schedule_and_makes_exactly_24_calls() -> None:
    harness = Harness()

    result = harness.run()

    assert result.status is RunStatus.COMPLETED
    assert result.error is None
    assert result.schedule == ARM_SCHEDULE
    assert [(step.t, step.arm) for step in result.steps] == list(ARM_SCHEDULE)
    assert [step.position for step in result.steps] == list(range(12))
    assert all(step.status == "COMPLETED" for step in result.steps)
    assert all(step.error is None for step in result.steps)
    assert all([r.call_number for r in step.requests] == [1, 2] for step in result.steps)
    assert harness.call_counts() == (8, 8, 8)
    assert harness.budget.frontier_calls == MAX_FRONTIER_CALLS
    assert result.budget == BudgetSnapshot(
        frontier_calls=24, provider_cost_usd="0", human_authorizations=4, judge_calls=0
    )
    assert set(result.r_steps) == {1, 2, 3, 4}
    assert all(result.r_steps[t].arm == "R" and result.r_steps[t].t == t for t in (1, 2, 3, 4))


def test_scheduled_calls_and_authority_interleave_in_frozen_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness()
    real_authorize = runner_module.authorize_root_supersessions

    def _spy(**kwargs: Any) -> Any:
        harness.trace.append(f"authority:{kwargs['arm']}:T{kwargs['t']}")
        return real_authorize(**kwargs)

    monkeypatch.setattr(runner_module, "authorize_root_supersessions", _spy)

    harness.run()

    expected: list[str] = []
    calls = {"F": 0, "A": 0, "R": 0}
    for t, arm in ARM_SCHEDULE:
        for _ in range(2):
            calls[arm] += 1
            expected.append(f"call:{arm}:{calls[arm]}")
        if arm in ("F", "A") and t in (2, 4):
            expected.append(f"authority:{arm}:T{t}")
    assert harness.trace == expected


# --- persistence versus fresh reconstruction ----------------------------------------


def test_persistent_arms_keep_one_ledger_while_each_r_step_is_fresh() -> None:
    result = Harness().run()

    for arm, project_id in (("F", F_PROJECT_ID), ("A", A_PROJECT_ID)):
        steps = _steps_for(result, arm)
        assert [step.project_id for step in steps] == [project_id] * 4
        lengths = [len(step.ledger) for step in steps]
        assert lengths == sorted(lengths) and len(set(lengths)) == 4
        for earlier, later in zip(steps, steps[1:], strict=False):
            assert later.ledger[: len(earlier.ledger)] == earlier.ledger
        assert steps[0].ledger[0].sequence == 1
        assert steps[0].ledger[0].event.event_type is EventType.SEMANTIC_OBJECT_RECORDED
        # T2's Call 1 sees the T1 addresses and their live claims (persistence).
        assert steps[1].requests[0].known_address_ids != ()

    r_steps = _steps_for(result, "R")
    assert [step.project_id for step in r_steps] == [r_project_id(t) for t in (1, 2, 3, 4)]
    assert len({step.project_id for step in r_steps}) == 4
    for step in r_steps:
        assert step.ledger[0].sequence == 1
        assert step.ledger[0].event.event_type is EventType.EVIDENCE_INGESTED
        assert step.requests[0].known_address_ids == ()
        assert step.requests[0].known_claim_ids == ()
        assert step.root_designations == ()
        assert step.authorizations == ()
        assert step.state_snapshot is not None
        assert not any(isinstance(o, AuthorityRecord) for o in step.state_snapshot.objects.values())
    assert r_steps[1].evidence_ids_shown == (*T1_EVIDENCE_IDS, "EV-K-A2")
    assert r_steps[3].evidence_ids_shown == tuple(le.item.evidence_id for le in TIMELINE)


def test_f_uses_frozen_9p2_path_and_a_uses_ablation_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []
    real_delta, real_ablation = (
        runner_module.assimilate_delta,
        runner_module.assimilate_ablation_delta,
    )

    def _spy_delta(**kwargs: Any) -> Any:
        seen.append(("assimilate_delta", kwargs["governor"].project_id))
        return real_delta(**kwargs)

    def _spy_ablation(**kwargs: Any) -> Any:
        seen.append(("assimilate_ablation_delta", kwargs["governor"].project_id))
        return real_ablation(**kwargs)

    monkeypatch.setattr(runner_module, "assimilate_delta", _spy_delta)
    monkeypatch.setattr(runner_module, "assimilate_ablation_delta", _spy_ablation)
    harness = Harness()

    result = harness.run()

    assert result.status is RunStatus.COMPLETED
    expected = [
        ("assimilate_ablation_delta" if arm == "A" else "assimilate_delta", _pid(arm, t))
        for t, arm in ARM_SCHEDULE
    ]
    assert seen == expected

    f_t2, a_t2 = _step(result, "F", 2), _step(result, "A", 2)
    f_call1, a_call1 = harness.inner_f.requests[2], harness.inner_a.requests[2]
    assert f_call1.known_claims != ()
    assert f_call1.comparison_context != ComparisonContext()
    assert f_t2.claim_neighborhood != ()
    assert a_call1.known_claims == ()
    assert a_call1.comparison_context == ComparisonContext()
    assert a_t2.claim_neighborhood == ()
    assert all(r.policy_version == CONTRASTIVE_POLICY_VERSION for r in f_t2.requests)
    assert all(r.policy_version == POLICY_VERSION for r in a_t2.requests)
    assert all(r.policy_version == CONTRASTIVE_POLICY_VERSION for r in result.r_steps[2].requests)


def _pid(arm: str, t: int) -> str:
    return {"F": F_PROJECT_ID, "A": A_PROJECT_ID}.get(arm) or r_project_id(t)


# --- roots and authority --------------------------------------------------------------


def test_t1_roots_are_designated_mechanically_for_f_and_a() -> None:
    result = Harness().run()

    assert ROOT_SEEDS == (("A", SEED_A), ("B", SEED_B), ("N", SEED_N))
    for arm, project_id, summary in (("F", F_PROJECT_ID, result.f), ("A", A_PROJECT_ID, result.a)):
        t1 = _step(result, arm, 1)
        assert [r.key for r in t1.root_designations] == ["A", "B", "N"]
        for root in t1.root_designations:
            assert root.status == "DESIGNATED"
            assert root.address_id == address_id_for(project_id, _create_id(root.seed_evidence_id))
            assert root.claim_ids == (claim_id_for(project_id, _claim_id(root.seed_evidence_id)),)
            assert root.creating_judgment_ids == (_claim_id(root.seed_evidence_id),)
        assert summary.roots == {r.key: r for r in t1.root_designations}
        for t in (2, 3, 4):
            assert _step(result, arm, t).root_designations == ()


def test_authority_executes_only_after_persistent_t2_and_t4() -> None:
    harness = Harness()

    result = harness.run()

    for arm in ("F", "A"):
        assert _step(result, arm, 1).authorizations == ()
        assert _step(result, arm, 3).authorizations == ()
        t2 = _step(result, arm, 2)
        assert [(r.root_key, r.outcome, r.target_judgment_id) for r in t2.authorizations] == [
            ("A", AuthorizationOutcome.AGREED, _claim_id(SEED_A))
        ]
        assert t2.authorizations[0].pending_judgment_ids == (_supersede_id("EV-K-A2"),)
        assert t2.pending_supersede_judgment_ids == (_supersede_id("EV-K-A2"),)
        t4 = _step(result, arm, 4)
        assert [(r.root_key, r.outcome, r.target_judgment_id) for r in t4.authorizations] == [
            ("B", AuthorizationOutcome.AGREED, _claim_id(SEED_B)),
            ("B", AuthorizationOutcome.NON_ROOT_NOT_AUTHORIZED, _claim_id("EV-K-A2")),
        ]
        # The AGREE is in the ledger snapshot of the very step that authorized it.
        human = [
            e
            for e in t2.ledger
            if e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
            and e.event.payload.judgment.reasoner == HUMAN_FINGERPRINT  # type: ignore[union-attr]
        ]
        assert len(human) == 1
        assert t2.state_snapshot is not None
        assert human[0].event.payload.judgment.judgment_id in (  # type: ignore[union-attr]
            t2.state_snapshot.semantic.applied_judgment_ids
        )
    assert harness.budget.human_authorizations == 4
    assert (
        result.f.authorizations
        == _step(result, "F", 2).authorizations + _step(result, "F", 4).authorizations
    )
    for step in _steps_for(result, "R"):
        assert step.authorizations == ()


# --- step and arm records -----------------------------------------------------------


def test_step_records_capture_raw_state_for_later_artifacts() -> None:
    harness = Harness(cost=0.25)

    result = harness.run()

    f_t1 = _step(result, "F", 1)
    assert f_t1.evidence_ids_shown == T1_EVIDENCE_IDS
    assert tuple(len(stage) for stage in f_t1.stage_decisions) == (3, 3)
    assert all(d.route is AdmissionRoute.APPLY for stage in f_t1.stage_decisions for d in stage)
    assert f_t1.neighborhood == f_t1.claim_neighborhood
    assert len(f_t1.neighborhood) == 3
    assert f_t1.pending_supersede_judgment_ids == ()
    assert f_t1.state_snapshot is not None and f_t1.view_snapshot is not None
    assert f_t1.state_snapshot.revision == len(f_t1.ledger)
    assert f_t1.view_snapshot == derive_view(f_t1.state_snapshot.semantic)
    assert [r.invocation_id for r in f_t1.receipts] == ["F-1-0", "F-2-0"]
    assert f_t1.draft_payloads == ("draft:F:1", "draft:F:2")
    f_t2 = _step(result, "F", 2)
    assert [r.invocation_id for r in f_t2.receipts] == ["F-3-0", "F-4-0"]
    assert f_t2.draft_payloads == ("draft:F:3", "draft:F:4")

    assert isinstance(result.f, ArmSummary) and isinstance(result.a, ArmSummary)
    assert result.f.project_id == F_PROJECT_ID and result.a.project_id == A_PROJECT_ID
    assert result.f.ledger == _step(result, "F", 4).ledger
    assert result.f.final_state == _step(result, "F", 4).state_snapshot
    assert result.f.final_view == _step(result, "F", 4).view_snapshot
    assert result.f.replay is not None and result.f.replay.status == "REPLAY_MATCH"
    assert result.f.replay.event_count == len(result.f.ledger)
    assert result.a.replay is None
    assert len(result.f.requests) == 8 and len(result.a.requests) == 8
    assert result.budget.provider_cost_usd == str(Decimal("0.25") * 24)


# --- fail-fast ----------------------------------------------------------------------


def test_failure_mid_schedule_marks_later_positions_not_run_and_stops_calls() -> None:
    failing = _position("F", 2)
    harness = Harness(f_overrides={2: XAIProviderError("opaque provider failure")})

    result = harness.run()

    assert result.status is RunStatus.ABORTED_PROVIDER
    assert result.error == "XAIProviderError: opaque provider failure"
    assert [s.status for s in result.steps[:failing]] == ["COMPLETED"] * failing
    failed = result.steps[failing]
    assert failed.status == "FAILED"
    assert failed.error == result.error
    assert [r.call_number for r in failed.requests] == [1]
    assert failed.stage_decisions == ((), ())
    assert failed.state_snapshot is not None
    assert "EV-K-A2" in failed.state_snapshot.semantic.evidence
    assert len(failed.ledger) > len(result.steps[0].ledger)
    for step in result.steps[failing + 1 :]:
        assert step.status == "NOT_RUN"
        assert step.error is None
        assert step.requests == () and step.ledger == () and step.state_snapshot is None
    assert harness.call_counts() == (3, 4, 4)
    assert harness.budget.frontier_calls == 11
    assert result.budget.frontier_calls == 11
    assert result.f.replay is not None and result.f.replay.status == "REPLAY_MATCH"


def test_failure_in_call_two_preserves_call_one_admissions_in_the_step_ledger() -> None:
    harness = Harness(f_overrides={5: SemanticOutputError("opaque contract failure")})

    result = harness.run()

    assert result.status is RunStatus.ABORTED_MODEL_CONTRACT
    failed = _step(result, "F", 3)
    assert failed.status == "FAILED"
    assert [r.call_number for r in failed.requests] == [1, 2]
    recorded = [
        e.event.payload.judgment.judgment_id  # type: ignore[union-attr]
        for e in failed.ledger
        if e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
    ]
    assert _bind_id("EV-K-A3") in recorded
    assert _claim_id("EV-K-A3") not in recorded
    assert harness.call_counts() == (6, 4, 6)


@pytest.mark.parametrize(
    ("exc", "status", "error"),
    [
        (XAIProviderError("p"), RunStatus.ABORTED_PROVIDER, "XAIProviderError: p"),
        (SemanticOutputError("m"), RunStatus.ABORTED_MODEL_CONTRACT, "SemanticOutputError: m"),
        (ContextUnsupported("c"), RunStatus.ABORTED_RUNTIME, "ContextUnsupported: c"),
        (ValueError("v"), RunStatus.ABORTED_RUNTIME, "ValueError: v"),
        (RuntimeError("r"), RunStatus.ABORTED_RUNTIME, "RuntimeError: r"),
        (KeyboardInterrupt(), RunStatus.ABORTED_RUNTIME, "INTERRUPTED: KeyboardInterrupt"),
    ],
)
def test_operational_exceptions_classify_and_abort(
    exc: BaseException, status: RunStatus, error: str
) -> None:
    harness = Harness(a_overrides={0: exc})

    result = harness.run()

    assert result.status is status
    assert result.error == error
    assert result.steps[0].status == "COMPLETED"
    assert result.steps[1].status == "FAILED" and result.steps[1].error == error
    assert [s.status for s in result.steps[2:]] == ["NOT_RUN"] * 10
    assert harness.call_counts() == (2, 1, 0)


def test_system_exit_is_never_caught() -> None:
    harness = Harness(r_overrides={0: SystemExit(3)})

    with pytest.raises(SystemExit):
        harness.run()


def test_authority_ceiling_breach_aborts_after_that_steps_calls() -> None:
    budget = ExperimentBudget()
    budget.human_authorizations = MAX_HUMAN_AUTHORIZATIONS
    harness = Harness(budget=budget)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_AUTHORITY_CEILING
    assert result.error is not None and result.error.startswith("AuthorizationCeilingExceeded: ")
    failing = _position("A", 2)
    failed = result.steps[failing]
    assert failed.status == "FAILED"
    assert [r.call_number for r in failed.requests] == [1, 2]
    assert failed.authorizations == ()
    assert [s.status for s in result.steps[failing + 1 :]] == ["NOT_RUN"] * (11 - failing)
    assert harness.call_counts() == (2, 4, 2)
    assert budget.human_authorizations == MAX_HUMAN_AUTHORIZATIONS


def test_semantic_wrongness_and_structural_rejects_do_not_abort() -> None:
    """A CREATE where a BIND was expected, an empty Call 2, and a claim at an unknown
    address are all structurally valid responses; admission records them and the run
    goes on."""
    script = LifecycleScript()

    def _wrong_create(request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        judgment = script._call_one(
            request.model_copy(update={"known_addresses": ()})
        )  # forgets the prior address -> CREATE
        assert judgment[0].kind is JudgmentKind.CREATE_ADDRESS
        return judgment

    def _claim_at_unknown_address(request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        return (
            SemanticJudgment(
                judgment_id="J-orphan",
                project_id=request.project_id,
                proposal=AssertClaimProposal(
                    address_id="ADDR-does-not-exist",
                    predicate="policy_value",
                    value=ClaimValue(kind=ClaimValueKind.TEXT, text="opaque"),
                    evidence_ids=(request.evidence[0].evidence_id,),
                    authority=Authority.OBSERVED,
                ),
                visible_evidence_ids=tuple(i.evidence_id for i in request.evidence),
                rationale="Opaque rationale.",
                reasoner=FINGERPRINT,
                invocation_id="INV-orphan",
                proposed_at=T0,
            ),
        )

    harness = Harness(
        f_overrides={2: _wrong_create, 3: ()},
        a_overrides={5: _claim_at_unknown_address},
    )

    result = harness.run()

    assert result.status is RunStatus.COMPLETED
    assert harness.call_counts() == (8, 8, 8)
    f_t2 = _step(result, "F", 2)
    assert [r.outcome for r in f_t2.authorizations] == [AuthorizationOutcome.NO_PROPOSAL]
    a_t3 = _step(result, "A", 3)
    assert [d.route for d in a_t3.stage_decisions[1]] == [AdmissionRoute.REJECT]


# --- budget ---------------------------------------------------------------------------


def test_25th_call_is_refused_before_forwarding() -> None:
    inner = ScriptedReasoner(label="F")
    budget = ExperimentBudget()
    budget.frontier_calls = MAX_FRONTIER_CALLS
    reasoner = _budgeted(inner, budget)
    reasoner.recording.begin_step(1)

    with pytest.raises(ExperimentBudgetExceeded):
        reasoner.propose(_request())

    assert inner.requests == []
    assert reasoner.recording.records == ()
    assert budget.frontier_calls == MAX_FRONTIER_CALLS


def test_budget_preset_at_ceiling_aborts_run_before_any_call() -> None:
    budget = ExperimentBudget()
    budget.frontier_calls = MAX_FRONTIER_CALLS
    harness = Harness(budget=budget)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_BUDGET
    assert result.steps[0].status == "FAILED"
    assert result.steps[0].requests == ()
    assert [s.status for s in result.steps[1:]] == ["NOT_RUN"] * 11
    assert harness.call_counts() == (0, 0, 0)


def test_frontier_calls_increment_exactly_when_forwarded_even_if_the_call_raises() -> None:
    inner = ScriptedReasoner(label="F", overrides={0: XAIProviderError("opaque")})
    budget = ExperimentBudget()
    reasoner = _budgeted(inner, budget)
    reasoner.recording.begin_step(1)

    with pytest.raises(XAIProviderError):
        reasoner.propose(_request())

    assert budget.frontier_calls == 1
    assert len(inner.requests) == 1


def test_cost_exactly_at_ceiling_is_not_a_breach_and_cost_uses_decimal_of_str() -> None:
    inner = ScriptedReasoner(label="F", cost=MAX_COST_USD)
    budget = ExperimentBudget()
    reasoner = _budgeted(inner, budget)
    reasoner.recording.begin_step(1)

    reasoner.propose(_request())

    assert budget.provider_cost_usd == Decimal(str(MAX_COST_USD))
    assert budget.provider_cost_usd == Decimal("8.0")


def test_call_pushing_cost_above_ceiling_is_accounted_then_refused_and_stops_the_run() -> None:
    # 1.5 per call: 6 calls = 9.0 > 8.0 -> the 6th call (R T1 Call 2) is the breach.
    harness = Harness(cost=1.5)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_BUDGET
    assert result.error is not None and result.error.startswith("ExperimentBudgetExceeded: ")
    assert harness.call_counts() == (2, 2, 2)
    assert harness.budget.frontier_calls == 6
    assert harness.budget.provider_cost_usd == Decimal("9.0")
    assert result.budget.provider_cost_usd == "9.0"
    failed = result.steps[2]
    assert failed.status == "FAILED"
    assert [r.invocation_id for r in failed.receipts] == ["R-1-0", "R-2-0"]
    assert [r.call_number for r in failed.requests] == [1, 2]
    # The breaching call's judgments never reached governance.
    recorded = [
        e.event.payload.judgment.judgment_id  # type: ignore[union-attr]
        for e in failed.ledger
        if e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
    ]
    assert _create_id(SEED_A) in recorded
    assert _claim_id(SEED_A) not in recorded
    assert [s.status for s in result.steps[3:]] == ["NOT_RUN"] * 9


def test_more_than_one_receipt_for_one_call_is_a_runtime_integrity_failure() -> None:
    inner = ScriptedReasoner(label="F", cost=0.1, receipts_per_call=2)
    budget = ExperimentBudget()
    reasoner = _budgeted(inner, budget)
    reasoner.recording.begin_step(1)

    with pytest.raises(RuntimeError, match="receipt"):
        reasoner.propose(_request())

    harness = Harness(cost=0.1, receipts_per_call=2)
    result = harness.run()
    assert result.status is RunStatus.ABORTED_RUNTIME
    assert harness.call_counts() == (1, 0, 0)


def test_build_arm_reasoners_share_one_budget_and_carry_arm_identity() -> None:
    harness = Harness()

    reasoners = harness.reasoners
    assert (reasoners.f.recording.arm, reasoners.a.recording.arm, reasoners.r.recording.arm) == (
        "F",
        "A",
        "R",
    )
    assert reasoners.f.budget is reasoners.a.budget is reasoners.r.budget is harness.budget
    assert reasoners.f.recording.inner is harness.inner_f
    assert reasoners.f.fingerprint == FINGERPRINT


def test_run_experiment_refuses_reasoners_that_do_not_share_one_budget() -> None:
    harness = Harness()
    stray = _budgeted(ScriptedReasoner(label="R"), ExperimentBudget(), arm="R")
    clock = _clock()

    with pytest.raises(ValueError, match="budget"):
        run_experiment(
            reasoner_f=harness.reasoners.f,
            reasoner_a=harness.reasoners.a,
            reasoner_r=stray,
            clock=lambda: next(clock),
            id_factory=_counter_id_factory(),
        )
    assert harness.call_counts() == (0, 0, 0)


# --- source-level guarantees ---------------------------------------------------------


FORBIDDEN_RUNNER_IMPORTS = ("expectations", "leakage", "integrity", "artifacts")


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module or ''}.{alias.name}" for alias in node.names)
    return names


def test_runner_imports_no_answer_key_grading_or_outer_layer_module() -> None:
    tree = ast.parse(RUNNER_SOURCE)
    for name in _imported_modules(tree):
        last = name.rsplit(".", 1)[-1]
        assert last not in FORBIDDEN_RUNNER_IMPORTS, name
    sources = {
        name: (PACKAGE_DIR / name).read_text(encoding="utf-8")
        for name in integrity.REQUIRED_REQUEST_PATH_MODULES
    }
    passed, detail = integrity.request_path_import_gate(sources)
    assert passed, detail


def test_gate_12_fresh_ledger_contract_passes_on_the_real_runner_source() -> None:
    passed, detail = integrity._r_uses_fresh_ledger({"runner.py": RUNNER_SOURCE})
    assert passed, detail


def test_runner_has_exactly_two_frontier_paths_no_third_call_retry_or_fallback() -> None:
    tree = ast.parse(RUNNER_SOURCE)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(c.func, ast.Attribute) and c.func.attr == "propose_and_submit" for c in calls
    )
    frontier = sorted(
        c.func.id
        for c in calls
        if isinstance(c.func, ast.Name) and c.func.id.startswith("assimilate_")
    )
    assert frontier == ["assimilate_ablation_delta", "assimilate_delta"]
    propose_calls = [
        c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "propose"
    ]
    assert len(propose_calls) == 1
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    identifiers |= {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert not any("retry" in n.casefold() or "fallback" in n.casefold() for n in identifiers)
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    assert handlers, "the fail-fast catch must exist"
    assert not any(len(h.body) == 1 and isinstance(h.body[0], ast.Pass) for h in handlers), (
        "an exception is never swallowed"
    )
    catching = [node for node in ast.walk(tree) if isinstance(node, ast.Try) and node.handlers]
    assert len(catching) == 1, "the runner catches once, around each scheduled arm/T"
    assert not any(isinstance(h.type, ast.Name) and h.type.id == "SystemExit" for h in handlers)


def test_run_status_members_are_exactly_the_spec_statuses() -> None:
    assert [s.value for s in RunStatus] == [
        "NOT_RUN",
        "ABORTED_PREFLIGHT",
        "ABORTED_PROVIDER",
        "ABORTED_MODEL_CONTRACT",
        "ABORTED_RUNTIME",
        "ABORTED_AUTHORITY_CEILING",
        "ABORTED_BUDGET",
        "COMPLETED",
    ]
