"""9P3 T4: 48-cell F/A/R runner, global budgets and exact-request reference snapshots
(spec §8, §9, §12, §16–§18; T4 brief).

Every reasoner here is a scripted fake that derives structurally valid judgments from
the request it is shown (or raises a scripted exception); every ledger is a real
``SemanticGovernor`` over an ``InMemoryEventStore``. The runner feeds the frozen Orion
evidence into those fakes; the fakes' own wording is opaque and only evidence ids
follow the spec §7 id law. After T1 the script acts on two tracked loci only, so the
ledgers stay small enough to walk 48 cells in a unit test; nothing about the runner
depends on that choice. ZERO live calls; sockets are blocked.
"""

from __future__ import annotations

import ast
import inspect
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import SemanticOutputError, XAIProviderError
from foundry.application.context_errors import ContextUnsupported
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionRoute
from foundry.domain.common import Authority, FrozenModel
from foundry.domain.events import EventType
from foundry.domain.evidence import EvidenceItem
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
from foundry.experiments.contrastive_unseen import integrity as contrastive_integrity
from foundry.experiments.contrastive_unseen.records import RecordingReasoner
from foundry.experiments.long_horizon_bounded import runner as runner_module
from foundry.experiments.long_horizon_bounded.authority import (
    HUMAN_FINGERPRINT,
    AuthorizationOutcome,
)
from foundry.experiments.long_horizon_bounded.protocol import (
    A_POLICY_VERSION,
    A_PROJECT_ID,
    ARM_SCHEDULE,
    AUTHORITY_CHECKPOINTS,
    F_PROJECT_ID,
    FR_POLICY_VERSION,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MODEL,
    PROVIDER,
    r_project_id,
)
from foundry.experiments.long_horizon_bounded.runner import (
    ArmReasoners,
    ArmSummary,
    BudgetedReasoner,
    BudgetSnapshot,
    CellRecord,
    ExperimentBudget,
    ExperimentBudgetExceeded,
    ReferenceSnapshotMismatch,
    RequestReferenceSnapshot,
    RunResult,
    RunStatus,
    build_arm_reasoners,
    run_experiment,
    run_reconstruction_step,
    snapshot_request_references,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    LOCI,
    TIMELINE,
    evidence_id,
    raw_evidence_character_count,
    reconstruction_corpus,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 13, tzinfo=UTC)
FR_FINGERPRINT = ReasonerFingerprint(
    provider=PROVIDER, model=MODEL, policy_version=FR_POLICY_VERSION
)
A_FINGERPRINT = ReasonerFingerprint(provider=PROVIDER, model=MODEL, policy_version=A_POLICY_VERSION)
RUNNER_PATH = Path(runner_module.__file__)
RUNNER_SOURCE = RUNNER_PATH.read_text(encoding="utf-8")

TRACKED_LOCI: frozenset[str] = frozenset({"A", "B"})
"""Loci the script keeps acting on after T1 (T3 and T5/T8 checkpoint loci)."""

CELL_COUNT = len(ARM_SCHEDULE)


def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sockets(monkeypatch)


# --- fakes ------------------------------------------------------------------------


class FakeReceipt(FrozenModel):
    """Adapter-style economics of one scripted call: the five attributes the
    measurement contract reads, of which ``cost_usd`` is what the budget reads."""

    invocation_id: str
    cost_usd: float
    input_tokens: int = 11
    output_tokens: int = 3
    wall_clock_ms: int = 5


def _locus(item_id: str) -> str:
    return item_id.removeprefix("EV-O-")[0]


def _create_id(item_id: str) -> str:
    return f"J-create-{item_id}"


def _bind_id(item_id: str) -> str:
    return f"J-bind-{item_id}"


def _claim_id(item_id: str) -> str:
    return f"J-claim-{item_id}"


def _supersede_id(item_id: str) -> str:
    return f"J-supersede-{item_id}"


class LifecycleScript:
    """Structurally valid judgments derived only from the request shown to it.

    Acts on the request's *latest* items (those no other shown item supersedes) that
    are T1 items or belong to a tracked locus. Call 1 (CREATE/BIND allowed): BIND to
    the address this script remembers for the item's predecessor when that address is
    among the request's known addresses, else CREATE a fresh address. Call 2: ASSERT
    one claim per acted item at the address chosen in Call 1 and, when the
    predecessor's claim is among the request's known claims, propose one SUPERSEDE
    targeting the predecessor's creating judgment. Wording is opaque; ids are structural.
    """

    def __init__(
        self, fingerprint: ReasonerFingerprint, *, tracked: frozenset[str] = TRACKED_LOCI
    ) -> None:
        self._fingerprint = fingerprint
        self._tracked = tracked
        self._address_of: dict[tuple[str, str], str] = {}

    def __call__(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            return self._call_one(request)
        return self._call_two(request)

    def _acted(self, request: ReasoningRequest) -> tuple[EvidenceItem, ...]:
        superseded = {item.supersedes_evidence_id for item in request.evidence}
        return tuple(
            item
            for item in request.evidence
            if item.evidence_id not in superseded
            and (item.supersedes_evidence_id is None or _locus(item.evidence_id) in self._tracked)
        )

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
        for item in self._acted(request):
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
        for item in self._acted(request):
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
    after each forwarded call; optionally logs to ``trace``. Its fingerprint carries
    the policy of the arm named by ``label`` (A: the historical 9P policy; F/R: the
    9P2 contrastive policy) and the frozen provider/model.
    """

    def __init__(
        self,
        *,
        label: str,
        overrides: dict[int, Batch] | None = None,
        cost: float = 0.0,
        receipts_per_call: int = 1,
        trace: list[str] | None = None,
        tracked: frozenset[str] = TRACKED_LOCI,
    ) -> None:
        self._label = label
        self._script = LifecycleScript(self.fingerprint, tracked=tracked)
        self._overrides = overrides or {}
        self._cost = cost
        self._receipts_per_call = receipts_per_call
        self._trace = trace
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[FakeReceipt] = []
        self._drafts: list[str] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return A_FINGERPRINT if self._label == "A" else FR_FINGERPRINT

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
        for extra in range(self._receipts_per_call):
            self._receipts.append(
                FakeReceipt(invocation_id=f"{self._label}-{index + 1}-{extra}", cost_usd=self._cost)
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


class BareReasoner:
    """A reasoner exposing neither ``receipts`` nor ``draft_payloads``."""

    def __init__(self, inner: ScriptedReasoner) -> None:
        self._inner = inner

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        return self._inner.propose(request)


class Harness:
    """Three scripted inner reasoners wrapped through ``build_arm_reasoners``."""

    def __init__(
        self,
        *,
        f_overrides: dict[int, Batch] | None = None,
        a_overrides: dict[int, Batch] | None = None,
        r_overrides: dict[int, Batch] | None = None,
        cost: float = 0.0,
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

    def run(self, *, progress: list[CellRecord] | None = None) -> RunResult:
        clock = _clock()
        return run_experiment(
            reasoners=self.reasoners,
            clock=lambda: next(clock),
            id_factory=_counter_id_factory(),
            progress=progress,
        )


# --- builders ---------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0 + timedelta(minutes=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _cells_for(result: RunResult, arm: str) -> list[CellRecord]:
    return [cell for cell in result.cells if cell.arm == arm]


def _cell(result: RunResult, arm: str, t: int) -> CellRecord:
    (cell,) = [c for c in result.cells if c.arm == arm and c.t == t]
    return cell


def _position(arm: str, t: int) -> int:
    return ARM_SCHEDULE.index((t, arm))


def _pid(arm: str, t: int) -> str:
    return {"F": F_PROJECT_ID, "A": A_PROJECT_ID}.get(arm) or r_project_id(t)


def _budgeted(inner: Any, budget: ExperimentBudget, *, arm: str = "F") -> BudgetedReasoner:
    return BudgetedReasoner(RecordingReasoner(inner, arm=arm), budget)


def _request(project_id: str = F_PROJECT_ID) -> ReasoningRequest:
    return ReasoningRequest(
        project_id=project_id,
        evidence=tuple(
            le.item.model_copy(update={"project_id": project_id}) for le in TIMELINE[:2]
        ),
    )


def _judgment_ids_recorded(cell: CellRecord) -> list[str]:
    return [
        e.event.payload.judgment.judgment_id  # type: ignore[union-attr]
        for e in cell.ledger
        if e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
    ]


def _human_judgments(cell: CellRecord) -> list[SemanticJudgment]:
    return [
        e.event.payload.judgment  # type: ignore[union-attr]
        for e in cell.ledger
        if e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
        and e.event.payload.judgment.reasoner == HUMAN_FINGERPRINT  # type: ignore[union-attr]
    ]


@pytest.fixture(scope="module")
def completed() -> Iterator[tuple[Harness, RunResult]]:
    """One scripted, fully completed 48-cell walk shared by the read-only assertions."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        harness = Harness()
        yield harness, harness.run()


# --- success shape and positions ------------------------------------------------------


def test_completed_run_has_48_completed_cells_and_96_calls(
    completed: tuple[Harness, RunResult],
) -> None:
    harness, result = completed

    assert result.status is RunStatus.COMPLETED
    assert result.error is None
    assert result.schedule == ARM_SCHEDULE
    assert len(result.cells) == CELL_COUNT == 48
    assert [(c.position, c.t, c.arm) for c in result.cells] == [
        (i, t, arm) for i, (t, arm) in enumerate(ARM_SCHEDULE)
    ]
    assert all(c.status == "COMPLETED" and c.error is None for c in result.cells)
    assert all([r.call_number for r in c.requests] == [1, 2] for c in result.cells)
    assert all(len(c.reference_snapshots) == 2 for c in result.cells)
    assert all(c.project_id == _pid(c.arm, c.t) for c in result.cells)
    assert sum(len(c.requests) for c in result.cells) == 96
    assert harness.call_counts() == (32, 32, 32)
    assert harness.budget.frontier_calls == MAX_FRONTIER_CALLS == 96
    assert result.budget == BudgetSnapshot(
        frontier_calls=96,
        provider_cost_usd="0.0",
        human_authorizations=harness.budget.human_authorizations,
        judge_calls=0,
    )
    assert len(result.f.requests) == 32 and len(result.a.requests) == 32
    assert len(result.f.reference_snapshots) == 32 and len(result.a.reference_snapshots) == 32


def test_r_cells_carry_their_schedule_index_as_position(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed

    r_positions = {c.position for c in result.cells if c.arm == "R"}
    assert r_positions == {i for i, (_, arm) in enumerate(ARM_SCHEDULE) if arm == "R"}
    assert len(r_positions) == 16
    assert set(result.r_cells) == set(range(1, 17))
    for t in range(1, 17):
        cell = result.r_cells[t]
        assert cell.arm == "R" and cell.t == t
        assert cell.position == ARM_SCHEDULE.index((t, "R"))
        assert result.cells[cell.position] == cell


def test_run_reconstruction_step_called_directly_carries_the_given_position() -> None:
    inner = ScriptedReasoner(label="R")
    reasoner = _budgeted(inner, ExperimentBudget(), arm="R")
    clock = _clock()

    cell = run_reconstruction_step(
        t=3,
        position=6,
        reasoner=reasoner,
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )

    assert cell.position == 6
    assert cell.arm == "R" and cell.t == 3
    assert cell.status == "COMPLETED"
    assert cell.project_id == "PROJ-9P3-R-T03"
    assert [r.call_number for r in cell.requests] == [1, 2]
    assert len(cell.reference_snapshots) == 2
    assert cell.ledger[0].sequence == 1
    assert len(inner.requests) == 2


# --- persistence versus fresh reconstruction ----------------------------------------


def test_persistent_arms_keep_one_ledger_across_all_sixteen_versions(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed

    for arm, project_id in (("F", F_PROJECT_ID), ("A", A_PROJECT_ID)):
        cells = _cells_for(result, arm)
        assert [c.t for c in cells] == list(range(1, 17))
        assert [c.project_id for c in cells] == [project_id] * 16
        lengths = [len(c.ledger) for c in cells]
        assert lengths == sorted(lengths) and len(set(lengths)) == 16
        for earlier, later in zip(cells, cells[1:], strict=False):
            assert later.ledger[: len(earlier.ledger)] == earlier.ledger
        assert cells[0].ledger[0].sequence == 1
        assert cells[0].ledger[0].event.event_type is EventType.SEMANTIC_OBJECT_RECORDED
        # T2's Call 1 sees the addresses T1 created (persistence).
        t1_addresses = {
            address_id_for(project_id, _create_id(evidence_id(1, locus))) for locus in LOCI
        }
        assert t1_addresses <= set(cells[1].requests[0].known_address_ids)
        assert cells[1].evidence_ids_shown == tuple(sorted(evidence_id(2, locus) for locus in LOCI))


def test_no_state_crosses_between_f_and_a(completed: tuple[Harness, RunResult]) -> None:
    harness, result = completed

    f_addresses = {a for r in result.f.requests for a in r.known_address_ids}
    a_addresses = {a for r in result.a.requests for a in r.known_address_ids}
    assert f_addresses and a_addresses
    assert f_addresses.isdisjoint(a_addresses)
    assert f_addresses <= set(result.f.final_state.semantic.addresses)
    assert a_addresses <= set(result.a.final_state.semantic.addresses)
    assert all(r.project_id == F_PROJECT_ID for r in harness.inner_f.requests)
    assert all(r.project_id == A_PROJECT_ID for r in harness.inner_a.requests)
    assert {r.project_id for r in harness.inner_r.requests} == {
        r_project_id(t) for t in range(1, 17)
    }


def test_every_r_cell_is_a_fresh_store_with_no_prior_claims(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed

    r_cells = _cells_for(result, "R")
    assert [c.project_id for c in r_cells] == [f"PROJ-9P3-R-T{t:02d}" for t in range(1, 17)]
    assert len({c.project_id for c in r_cells}) == 16
    for cell in r_cells:
        corpus = reconstruction_corpus(cell.t, project_id=cell.project_id)
        assert cell.ledger[0].sequence == 1
        assert cell.ledger[0].event.event_type is EventType.EVIDENCE_INGESTED
        ingested = [e for e in cell.ledger if e.event.event_type is EventType.EVIDENCE_INGESTED]
        assert len(ingested) == len(corpus) == 12 * cell.t
        assert cell.requests[0].known_address_ids == ()
        assert cell.requests[0].known_claim_ids == ()
        assert cell.evidence_ids_shown == tuple(sorted(item.evidence_id for item in corpus))
        assert cell.root_designations == ()
        assert cell.eligible_targets is None
        assert cell.authorizations == ()
        assert cell.state_snapshot is not None
        assert not any(isinstance(o, AuthorityRecord) for o in cell.state_snapshot.objects.values())
    # No R ledger is a continuation of an earlier R ledger.
    assert all(
        c.ledger[0].event.event_id != r_cells[0].ledger[0].event.event_id for c in r_cells[1:]
    )


def test_f_and_r_use_the_production_path_and_a_the_ablation_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    # F's 7th call is its T4 Call 1 (position 9): stop there, cheaply.
    harness = Harness(f_overrides={6: XAIProviderError("stop")})

    result = harness.run()

    assert result.status is RunStatus.ABORTED_PROVIDER
    stop = _position("F", 4)
    assert seen == [
        ("assimilate_ablation_delta" if arm == "A" else "assimilate_delta", _pid(arm, t))
        for t, arm in ARM_SCHEDULE[: stop + 1]
    ]
    f_t2, a_t2, r_t2 = _cell(result, "F", 2), _cell(result, "A", 2), _cell(result, "R", 2)
    f_call1, a_call1 = harness.inner_f.requests[2], harness.inner_a.requests[2]
    assert f_call1.known_claims != ()
    assert f_t2.requests[0].known_claim_ids != ()
    assert f_t2.claim_neighborhood != ()
    assert a_call1.known_claims == ()
    assert all(r.known_claim_ids == () for c in _cells_for(result, "A") for r in c.requests[:1])
    assert a_t2.claim_neighborhood == ()
    assert all(r.comparison_context_chars == 0 for c in _cells_for(result, "A") for r in c.requests)
    assert all(r.policy_version == FR_POLICY_VERSION for r in f_t2.requests)
    assert all(r.policy_version == A_POLICY_VERSION for r in a_t2.requests)
    assert all(r.policy_version == FR_POLICY_VERSION for r in r_t2.requests)


# --- roots and authority --------------------------------------------------------------


def test_all_twelve_roots_are_designated_after_f_and_a_t1(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed

    for arm, project_id, summary in (("F", F_PROJECT_ID, result.f), ("A", A_PROJECT_ID, result.a)):
        t1 = _cell(result, arm, 1)
        assert [r.locus for r in t1.root_designations] == list(LOCI)
        for root in t1.root_designations:
            assert root.status == "DESIGNATED"
            assert root.seed_evidence_id == evidence_id(1, root.locus)
            assert root.address_id == address_id_for(project_id, _create_id(root.seed_evidence_id))
            assert root.claim_ids == (claim_id_for(project_id, _claim_id(root.seed_evidence_id)),)
            assert root.creating_judgment_ids == (_claim_id(root.seed_evidence_id),)
        assert summary.roots == {r.locus: r for r in t1.root_designations}
        assert set(summary.roots) == set(LOCI)
        for t in range(2, 17):
            assert _cell(result, arm, t).root_designations == ()


def test_eligible_targets_are_snapshotted_before_ingestion_at_checkpoints_only(
    completed: tuple[Harness, RunResult],
) -> None:
    harness, result = completed

    for arm in ("F", "A"):
        cells = _cells_for(result, arm)
        for cell in cells:
            if cell.t not in AUTHORITY_CHECKPOINTS:
                assert cell.eligible_targets is None
                assert cell.authorizations == ()
                continue
            locus = AUTHORITY_CHECKPOINTS[cell.t]
            eligible = cell.eligible_targets
            assert eligible is not None
            assert (eligible.arm, eligible.t, eligible.target_locus) == (arm, cell.t, locus)
            before = cells[cell.t - 2]  # the same arm's previous cell
            assert eligible.snapshot_sequence == len(before.ledger)
            assert eligible.snapshot_sequence < len(cell.ledger)
            roots = (result.f if arm == "F" else result.a).roots
            assert eligible.designated_address_id == roots[locus].address_id
            # Claims created during T are never eligible: the snapshot precedes ingestion.
            created_during_t = claim_id_for(cell.project_id, _claim_id(evidence_id(cell.t, locus)))
            assert created_during_t not in eligible.live_claim_ids
            assert _claim_id(evidence_id(cell.t, locus)) not in eligible.eligible_judgment_ids
            assert all(a.t == cell.t and a.arm == arm for a in cell.authorizations)
        summary = result.f if arm == "F" else result.a
        assert summary.eligible_targets == tuple(
            c.eligible_targets for c in cells if c.eligible_targets is not None
        )
        assert len(summary.eligible_targets) == len(AUTHORITY_CHECKPOINTS)
        assert summary.authorizations == tuple(a for c in cells for a in c.authorizations)
    for cell in _cells_for(result, "R"):
        assert cell.eligible_targets is None and cell.authorizations == ()
    agreed = sum(
        1
        for c in result.cells
        for a in c.authorizations
        if a.outcome is AuthorizationOutcome.AGREED
    )
    assert agreed == harness.budget.human_authorizations == result.budget.human_authorizations
    assert 0 < agreed <= MAX_HUMAN_AUTHORIZATIONS


def test_t3_agrees_both_eligible_targets_and_writes_them_into_that_cells_ledger(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed

    for arm in ("F", "A"):
        t3 = _cell(result, arm, 3)
        a01, a02, a03 = (evidence_id(t, "A") for t in (1, 2, 3))
        assert [
            (a.outcome, a.target_judgment_id, a.pending_judgment_ids) for a in t3.authorizations
        ][:2] == [
            (AuthorizationOutcome.AGREED, _claim_id(a01), (_supersede_id(a02),)),
            (AuthorizationOutcome.AGREED, _claim_id(a02), (_supersede_id(a03),)),
        ]
        assert set(t3.pending_supersede_judgment_ids) >= {_supersede_id(a02), _supersede_id(a03)}
        human = _human_judgments(t3)
        assert len(human) == 2
        assert t3.state_snapshot is not None
        assert all(j.judgment_id in t3.state_snapshot.semantic.applied_judgment_ids for j in human)
        assert _cell(result, arm, 2).authorizations == ()
        assert _human_judgments(_cell(result, arm, 2)) == []


def test_snapshot_calls_and_authority_interleave_in_frozen_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(r_overrides={10: XAIProviderError("stop")})  # R's T6 Call 1
    real_snapshot = runner_module.snapshot_eligible_targets
    real_authorize = runner_module.authorize_eligible_supersessions

    def _spy_snapshot(*args: Any, **kwargs: Any) -> Any:
        harness.trace.append(f"snapshot:{kwargs['arm']}:T{kwargs['t']}")
        return real_snapshot(*args, **kwargs)

    def _spy_authorize(**kwargs: Any) -> Any:
        eligible = kwargs["eligible"]
        harness.trace.append(f"authority:{eligible.arm}:T{eligible.t}")
        return real_authorize(**kwargs)

    monkeypatch.setattr(runner_module, "snapshot_eligible_targets", _spy_snapshot)
    monkeypatch.setattr(runner_module, "authorize_eligible_supersessions", _spy_authorize)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_PROVIDER
    expected: list[str] = []
    calls = {"F": 0, "A": 0, "R": 0}
    for t, arm in ARM_SCHEDULE[: _position("R", 6)]:
        if arm in ("F", "A") and t in AUTHORITY_CHECKPOINTS:
            expected.append(f"snapshot:{arm}:T{t}")
        for _ in range(2):
            calls[arm] += 1
            expected.append(f"call:{arm}:{calls[arm]}")
        if arm in ("F", "A") and t in AUTHORITY_CHECKPOINTS:
            expected.append(f"authority:{arm}:T{t}")
    expected.append("call:R:11")
    assert harness.trace == expected


def test_authorization_ceiling_47_48_49_multi_target_boundary() -> None:
    """Shared budget preset to 47; F's T3 checkpoint offers two eligible targets, each
    with exactly one pending SUPERSEDE: the first AGREE is #48 and durable, the second
    hits the ceiling before any write, and nothing after that position runs."""
    budget = ExperimentBudget()
    budget.human_authorizations = MAX_HUMAN_AUTHORIZATIONS - 1
    harness = Harness(budget=budget)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_AUTHORITY_CEILING
    assert result.error is not None and result.error.startswith("AuthorizationCeilingExceeded: ")
    failing = _position("F", 3)
    assert failing == 7
    assert [c.status for c in result.cells[:failing]] == ["COMPLETED"] * failing
    failed = result.cells[failing]
    assert failed.status == "FAILED" and failed.arm == "F" and failed.t == 3
    assert [r.call_number for r in failed.requests] == [1, 2]
    assert len(failed.reference_snapshots) == 2
    assert failed.authorizations == ()
    assert failed.eligible_targets is not None
    a01, a02, a03 = (evidence_id(t, "A") for t in (1, 2, 3))
    assert failed.eligible_targets.eligible_judgment_ids == (_claim_id(a01), _claim_id(a02))
    # #48: exactly one human AGREE, durable in the ledger and applied.
    human = _human_judgments(failed)
    assert [j.rationale for j in human] == [f"AGREE: {_supersede_id(a02)}"]
    assert failed.state_snapshot is not None
    assert human[0].judgment_id in failed.state_snapshot.semantic.applied_judgment_ids
    # #49 was never written: the second proposal is still pending.
    view = derive_view(failed.state_snapshot.semantic)
    assert _supersede_id(a03) in view.pending_judgment_ids
    assert _supersede_id(a02) not in view.pending_judgment_ids
    assert budget.human_authorizations == MAX_HUMAN_AUTHORIZATIONS == 48
    assert result.budget.human_authorizations == 48
    assert [c.status for c in result.cells[failing + 1 :]] == ["NOT_RUN"] * (
        CELL_COUNT - failing - 1
    )
    assert harness.call_counts() == (6, 4, 6)
    # The #48 AGREE remains durable in the arm summary ledger.
    assert result.f.ledger == failed.ledger
    assert any(
        e.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
        and e.event.payload.judgment.judgment_id == human[0].judgment_id  # type: ignore[union-attr]
        for e in result.f.ledger
    )
    assert result.f.replay is not None and result.f.replay.status == "REPLAY_MATCH"


# --- cell and arm records -------------------------------------------------------------


def test_cell_records_capture_raw_state_and_measurements(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed

    f_t1 = _cell(result, "F", 1)
    assert f_t1.evidence_ids_shown == tuple(sorted(evidence_id(1, locus) for locus in LOCI))
    assert tuple(len(stage) for stage in f_t1.stage_decisions) == (12, 12)
    assert all(d.route is AdmissionRoute.APPLY for stage in f_t1.stage_decisions for d in stage)
    assert f_t1.neighborhood == f_t1.claim_neighborhood
    assert len(f_t1.neighborhood) == 12
    assert f_t1.pending_supersede_judgment_ids == ()
    assert f_t1.state_snapshot is not None and f_t1.view_snapshot is not None
    assert f_t1.state_snapshot.revision == len(f_t1.ledger)
    assert f_t1.view_snapshot == derive_view(f_t1.state_snapshot.semantic)
    assert [r.invocation_id for r in f_t1.receipts] == ["F-1-0", "F-2-0"]
    assert f_t1.draft_payloads == ("draft:F:1", "draft:F:2")
    f_t2 = _cell(result, "F", 2)
    assert [r.invocation_id for r in f_t2.receipts] == ["F-3-0", "F-4-0"]
    assert f_t2.draft_payloads == ("draft:F:3", "draft:F:4")

    for cell in result.cells:
        assert [(m.arm, m.t, m.call_number) for m in cell.measurements] == [
            (cell.arm, cell.t, 1),
            (cell.arm, cell.t, 2),
        ]
        assert [m.request_sha256 for m in cell.measurements] == [
            r.request_sha256 for r in cell.requests
        ]
        assert [m.invocation_id for m in cell.measurements] == [
            r.invocation_id for r in cell.receipts
        ]
        expected_chars = raw_evidence_character_count(cell.t) if cell.arm == "R" else None
        assert all(m.r_cumulative_raw_evidence_chars == expected_chars for m in cell.measurements)
    assert result.measurements == tuple(m for c in result.cells for m in c.measurements)
    assert len(result.measurements) == 96

    assert isinstance(result.f, ArmSummary) and isinstance(result.a, ArmSummary)
    assert result.f.project_id == F_PROJECT_ID and result.a.project_id == A_PROJECT_ID
    for arm, summary in (("F", result.f), ("A", result.a)):
        last = _cell(result, arm, 16)
        assert summary.arm == arm
        assert summary.ledger == last.ledger
        assert summary.final_state == last.state_snapshot
        assert summary.final_view == last.view_snapshot
        assert summary.requests == tuple(r for c in _cells_for(result, arm) for r in c.requests)
        assert summary.reference_snapshots == tuple(
            s for c in _cells_for(result, arm) for s in c.reference_snapshots
        )


def test_replay_is_exact_for_f_and_a(completed: tuple[Harness, RunResult]) -> None:
    _, result = completed

    for summary in (result.f, result.a):
        assert summary.replay is not None
        assert summary.replay.status == "REPLAY_MATCH"
        assert summary.replay.state_matches and summary.replay.view_matches
        assert summary.replay.event_count == len(summary.ledger)


def test_cost_is_accounted_per_receipt_as_decimal_of_str() -> None:
    harness = Harness(cost=0.05, f_overrides={4: XAIProviderError("stop")})  # F T3 Call 1

    result = harness.run()

    assert result.status is RunStatus.ABORTED_PROVIDER
    calls = harness.budget.frontier_calls
    assert calls == sum(harness.call_counts()) == 15
    assert harness.budget.provider_cost_usd == Decimal("0.05") * calls
    assert result.budget.provider_cost_usd == str(Decimal("0.05") * calls)


# --- reference snapshots (exact-request reference closure) -----------------------------


def test_snapshot_request_references_is_the_frozen_structural_capture_rule() -> None:
    request = _request()

    refs = snapshot_request_references(request)

    assert refs == (
        tuple(item.evidence_id for item in request.evidence),
        tuple(address.address_id for address in request.known_addresses),
        tuple(claim.claim_id for claim in request.known_claims),
        tuple(claim.created_by_judgment_id for claim in request.known_claims),
    )
    assert refs[0] != () and refs[1] == () and refs[2] == () and refs[3] == ()


def test_raw_references_are_captured_before_inner_delegation_and_bound_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    real_capture = runner_module.snapshot_request_references

    def spy_capture(request: ReasoningRequest) -> Any:
        events.append("RAW_REFERENCE_CAPTURE")
        return real_capture(request)

    monkeypatch.setattr(runner_module, "snapshot_request_references", spy_capture)

    class Inner(ScriptedReasoner):
        def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
            events.append("INNER_DELEGATION")
            assert wrapped.snapshots == ()
            return super().propose(request)

    inner = Inner(label="F", overrides={0: ()})
    budget = ExperimentBudget()
    wrapped = BudgetedReasoner(RecordingReasoner(inner, arm="F"), budget)
    wrapped.recording.begin_step(1)
    request = _request()

    wrapped.propose(request)

    assert events == ["RAW_REFERENCE_CAPTURE", "INNER_DELEGATION"]
    assert len(wrapped.snapshots) == 1 and len(wrapped.recording.records) == 1
    snap, record = wrapped.snapshots[0], wrapped.recording.records[0]
    assert (snap.arm, snap.t, snap.call_number, snap.request_sha256) == (
        record.arm,
        record.t,
        record.call_number,
        record.request_sha256,
    )
    assert snap.citable_evidence_ids == record.citable_evidence_ids
    assert snap.known_address_ids == record.known_address_ids
    assert snap.known_claim_ids == record.known_claim_ids
    assert budget.frontier_calls == 1
    assert wrapped.recording is not None and wrapped.budget is budget
    assert wrapped.fingerprint == FR_FINGERPRINT


def test_provider_failure_keeps_exactly_one_record_and_one_bound_snapshot() -> None:
    inner = ScriptedReasoner(label="F", overrides={0: XAIProviderError("boom")})
    wrapped = BudgetedReasoner(RecordingReasoner(inner, arm="F"), ExperimentBudget())
    wrapped.recording.begin_step(1)
    request = _request()

    with pytest.raises(XAIProviderError):
        wrapped.propose(request)

    assert len(wrapped.recording.records) == 1 and len(wrapped.snapshots) == 1
    assert wrapped.snapshots[0].request_sha256 == wrapped.recording.records[0].request_sha256
    assert wrapped.budget.frontier_calls == 1
    assert wrapped.budget.provider_cost_usd == Decimal("0.0")


def test_failed_cell_keeps_one_record_bound_to_one_snapshot() -> None:
    harness = Harness(a_overrides={2: XAIProviderError("opaque provider failure")})  # A T2 Call 1

    result = harness.run()

    assert result.status is RunStatus.ABORTED_PROVIDER
    failed = result.cells[_position("A", 2)]
    assert failed.status == "FAILED"
    assert failed.error == "XAIProviderError: opaque provider failure"
    assert len(failed.requests) == 1 and len(failed.reference_snapshots) == 1
    record, snap = failed.requests[0], failed.reference_snapshots[0]
    assert (snap.arm, snap.t, snap.call_number, snap.request_sha256) == (
        "A",
        2,
        1,
        record.request_sha256,
    )
    assert snap.citable_evidence_ids == record.citable_evidence_ids
    assert snap.known_address_ids == record.known_address_ids
    assert snap.known_claim_ids == record.known_claim_ids == ()
    assert failed.measurements == ()
    assert failed.stage_decisions == ((), ())
    assert failed.state_snapshot is not None
    assert evidence_id(2, "A") in failed.state_snapshot.semantic.evidence
    assert len(failed.ledger) > len(_cell(result, "A", 1).ledger)


def test_every_snapshot_equals_its_records_tuples_and_creating_judgments_of_the_request(
    completed: tuple[Harness, RunResult],
) -> None:
    harness, result = completed

    inner_by_arm = {"F": harness.inner_f, "A": harness.inner_a, "R": harness.inner_r}
    seen = {"F": 0, "A": 0, "R": 0}
    for cell in result.cells:
        assert len(cell.reference_snapshots) == len(cell.requests) == 2
        for record, snap in zip(cell.requests, cell.reference_snapshots, strict=True):
            assert isinstance(snap, RequestReferenceSnapshot)
            assert (snap.arm, snap.t, snap.call_number) == (
                record.arm,
                record.t,
                record.call_number,
            )
            assert (snap.arm, snap.t) == (cell.arm, cell.t)
            assert snap.request_sha256 == record.request_sha256
            assert snap.citable_evidence_ids == record.citable_evidence_ids
            assert snap.known_address_ids == record.known_address_ids
            assert snap.known_claim_ids == record.known_claim_ids
            request = inner_by_arm[cell.arm].requests[seen[cell.arm]]
            seen[cell.arm] += 1
            assert snap.known_claim_ids == tuple(c.claim_id for c in request.known_claims)
            assert snap.known_claim_creating_judgment_ids == tuple(
                c.created_by_judgment_id for c in request.known_claims
            )
            assert len(snap.known_claim_creating_judgment_ids) == len(snap.known_claim_ids)
    assert seen == {"F": 32, "A": 32, "R": 32}
    f_t2_call1 = _cell(result, "F", 2).reference_snapshots[0]
    assert f_t2_call1.known_claim_ids != ()
    assert _claim_id(evidence_id(1, "A")) in f_t2_call1.known_claim_creating_judgment_ids


@pytest.mark.parametrize("records_appended", [0, 2])
def test_forwarded_call_producing_other_than_one_record_is_a_reference_mismatch(
    records_appended: int,
) -> None:
    class BrokenRecorder(RecordingReasoner):
        def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
            for _ in range(records_appended):
                self._records.append(self._record(request, t=1, call_number=1))
            return self.inner.propose(request)

    inner = ScriptedReasoner(label="F", overrides={0: ()})
    budget = ExperimentBudget()
    wrapped = BudgetedReasoner(BrokenRecorder(inner, arm="F"), budget)  # type: ignore[arg-type]
    wrapped.recording.begin_step(1)

    with pytest.raises(ReferenceSnapshotMismatch):
        wrapped.propose(_request())

    assert len(inner.requests) == 1
    assert wrapped.snapshots == ()
    assert budget.frontier_calls == 1


# --- fail-fast ----------------------------------------------------------------------


def test_failure_in_call_two_preserves_call_one_admissions_in_the_cell_ledger() -> None:
    harness = Harness(
        f_overrides={3: SemanticOutputError("opaque contract failure")}
    )  # F T2 Call 2

    result = harness.run()

    assert result.status is RunStatus.ABORTED_MODEL_CONTRACT
    assert result.error == "SemanticOutputError: opaque contract failure"
    failed = _cell(result, "F", 2)
    assert failed.status == "FAILED"
    assert [r.call_number for r in failed.requests] == [1, 2]
    assert len(failed.reference_snapshots) == 2
    recorded = _judgment_ids_recorded(failed)
    assert _bind_id(evidence_id(2, "A")) in recorded
    assert _claim_id(evidence_id(2, "A")) not in recorded
    assert failed.measurements == ()
    failing = _position("F", 2)
    assert [c.status for c in result.cells[failing + 1 :]] == ["NOT_RUN"] * (
        CELL_COUNT - failing - 1
    )
    for cell in result.cells[failing + 1 :]:
        assert cell.error is None
        assert cell.requests == () and cell.reference_snapshots == ()
        assert cell.ledger == () and cell.state_snapshot is None and cell.view_snapshot is None
        assert cell.project_id == _pid(cell.arm, cell.t)
    assert harness.call_counts() == (4, 4, 4)
    assert harness.budget.frontier_calls == 12
    assert result.f.replay is not None and result.f.replay.status == "REPLAY_MATCH"


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
    assert result.cells[0].status == "COMPLETED"
    assert result.cells[1].status == "FAILED" and result.cells[1].error == error
    assert [c.status for c in result.cells[2:]] == ["NOT_RUN"] * (CELL_COUNT - 2)
    assert len(result.cells) == CELL_COUNT
    assert harness.call_counts() == (2, 1, 0)


def _sink_is_idle() -> bool:
    sink = runner_module._ACTIVE_CAPTURE
    return sink._expected is None and sink._capture is None


def test_system_exit_is_never_caught() -> None:
    harness = Harness(r_overrides={0: SystemExit(3)})

    with pytest.raises(SystemExit):
        harness.run()

    assert _sink_is_idle()


def test_system_exit_leaves_the_capture_sink_idle_and_standalone_calls_usable() -> None:
    """The one exception the catch site lets through must still close the per-call sink:
    no entry, no capture (and so no interrupted store/governor) survives the run, and a
    standalone step call afterwards is not refused."""
    harness = Harness(r_overrides={0: SystemExit(3)})
    with pytest.raises(SystemExit):
        harness.run()

    assert _sink_is_idle()
    inner = ScriptedReasoner(label="R")
    reasoner = _budgeted(inner, ExperimentBudget(), arm="R")
    clock = _clock()

    cell = run_reconstruction_step(
        t=1,
        position=2,
        reasoner=reasoner,
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )

    assert cell.status == "COMPLETED"
    assert [r.call_number for r in cell.requests] == [1, 2]
    assert _sink_is_idle()


def test_opening_the_capture_sink_while_another_entry_is_open_is_refused() -> None:
    sink = runner_module._ActiveCapture()
    sink.open(("F", 1, 0, F_PROJECT_ID))

    with pytest.raises(RuntimeError, match="CAPTURE_IDENTITY: sink not idle"):
        sink.open(("A", 1, 1, A_PROJECT_ID))

    assert sink.close() is None
    sink.open(("A", 1, 1, A_PROJECT_ID))
    assert sink.close() is None


def test_completed_cell_with_a_malformed_call_shape_fails_instead_of_omitting_measurement() -> None:
    harness = Harness(cost=0.0, receipts_per_call=0)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error is not None and result.error.startswith("RuntimeError: CALL_SHAPE")
    failed = result.cells[0]
    assert failed.status == "FAILED"
    assert [r.call_number for r in failed.requests] == [1, 2]
    assert len(failed.reference_snapshots) == 2
    assert failed.receipts == () and failed.measurements == ()
    assert [c.status for c in result.cells[1:]] == ["NOT_RUN"] * (CELL_COUNT - 1)
    assert harness.call_counts() == (2, 0, 0)


def test_reasoner_without_receipts_completes_with_no_measurements() -> None:
    inner = ScriptedReasoner(label="R")
    reasoner = _budgeted(BareReasoner(inner), ExperimentBudget(), arm="R")
    clock = _clock()

    cell = run_reconstruction_step(
        t=1,
        position=2,
        reasoner=reasoner,
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )

    assert cell.status == "COMPLETED"
    assert [r.call_number for r in cell.requests] == [1, 2]
    assert cell.receipts == () and cell.draft_payloads == ()
    assert cell.measurements == ()


def test_progress_list_receives_each_cell_as_it_is_produced() -> None:
    harness = Harness(f_overrides={2: XAIProviderError("opaque provider failure")})
    progress: list[CellRecord] = []

    result = harness.run(progress=progress)

    assert result.status is RunStatus.ABORTED_PROVIDER
    assert tuple(progress) == result.cells[: len(progress)]
    assert [c.status for c in progress][-1] == "FAILED"
    assert all(c.status == "COMPLETED" for c in progress[:-1])


# --- budget ---------------------------------------------------------------------------


def test_experiment_budget_starts_at_zero_and_snapshots_judge_calls() -> None:
    budget = ExperimentBudget()

    assert (budget.frontier_calls, budget.provider_cost_usd, budget.human_authorizations) == (
        0,
        Decimal("0"),
        0,
    )
    assert budget.judge_calls == 0
    assert budget.snapshot() == BudgetSnapshot(
        frontier_calls=0, provider_cost_usd="0", human_authorizations=0, judge_calls=0
    )


def test_97th_call_is_refused_before_forwarding() -> None:
    inner = ScriptedReasoner(label="F")
    budget = ExperimentBudget()
    budget.frontier_calls = MAX_FRONTIER_CALLS
    reasoner = _budgeted(inner, budget)
    reasoner.recording.begin_step(1)

    with pytest.raises(ExperimentBudgetExceeded):
        reasoner.propose(_request())

    assert inner.requests == []
    assert reasoner.recording.records == ()
    assert reasoner.snapshots == ()
    assert budget.frontier_calls == MAX_FRONTIER_CALLS == 96


def test_budget_preset_at_ceiling_aborts_run_before_any_call() -> None:
    budget = ExperimentBudget()
    budget.frontier_calls = MAX_FRONTIER_CALLS
    harness = Harness(budget=budget)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_BUDGET
    assert result.cells[0].status == "FAILED"
    assert result.cells[0].requests == () and result.cells[0].reference_snapshots == ()
    assert [c.status for c in result.cells[1:]] == ["NOT_RUN"] * (CELL_COUNT - 1)
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


def test_cost_exactly_at_ceiling_is_not_a_breach_and_uses_decimal_of_str() -> None:
    inner = ScriptedReasoner(label="F", cost=MAX_COST_USD)
    budget = ExperimentBudget()
    reasoner = _budgeted(inner, budget)
    reasoner.recording.begin_step(1)

    reasoner.propose(_request())

    assert budget.provider_cost_usd == Decimal(str(MAX_COST_USD)) == Decimal("10.0")


def test_call_pushing_cost_above_ceiling_is_accounted_then_refused_and_stops_the_run() -> None:
    # 2.0 per call: 5 calls = 10.0 (no breach), the 6th (R T1 Call 2) = 12.0 > 10.0.
    harness = Harness(cost=2.0)

    result = harness.run()

    assert result.status is RunStatus.ABORTED_BUDGET
    assert result.error is not None and result.error.startswith("ExperimentBudgetExceeded: ")
    assert harness.call_counts() == (2, 2, 2)
    assert harness.budget.frontier_calls == 6
    assert harness.budget.provider_cost_usd == Decimal("12.0")
    assert result.budget.provider_cost_usd == "12.0"
    failed = result.cells[2]
    assert failed.status == "FAILED" and failed.arm == "R" and failed.t == 1
    assert [r.invocation_id for r in failed.receipts] == ["R-1-0", "R-2-0"]
    assert [r.call_number for r in failed.requests] == [1, 2]
    assert len(failed.reference_snapshots) == 2
    # The breaching call's judgments never reached governance.
    recorded = _judgment_ids_recorded(failed)
    assert _create_id(evidence_id(1, "A")) in recorded
    assert _claim_id(evidence_id(1, "A")) not in recorded
    assert [c.status for c in result.cells[3:]] == ["NOT_RUN"] * (CELL_COUNT - 3)


def test_more_than_one_receipt_for_one_call_is_a_runtime_integrity_failure() -> None:
    inner = ScriptedReasoner(label="F", cost=0.1, receipts_per_call=2)
    budget = ExperimentBudget()
    reasoner = _budgeted(inner, budget)
    reasoner.recording.begin_step(1)

    with pytest.raises(RuntimeError, match="RECEIPT_INTEGRITY"):
        reasoner.propose(_request())

    harness = Harness(cost=0.1, receipts_per_call=2)
    result = harness.run()
    assert result.status is RunStatus.ABORTED_RUNTIME
    assert harness.call_counts() == (1, 0, 0)


def test_build_arm_reasoners_share_one_budget_and_carry_arm_identity() -> None:
    harness = Harness()

    reasoners = harness.reasoners
    assert isinstance(reasoners, ArmReasoners)
    assert (reasoners.f.recording.arm, reasoners.a.recording.arm, reasoners.r.recording.arm) == (
        "F",
        "A",
        "R",
    )
    assert reasoners.f.budget is reasoners.a.budget is reasoners.r.budget is harness.budget
    assert reasoners.f.recording.inner is harness.inner_f
    assert reasoners.f.fingerprint == FR_FINGERPRINT
    assert reasoners.a.fingerprint == A_FINGERPRINT
    assert reasoners.r.fingerprint == FR_FINGERPRINT


def test_run_experiment_refuses_reasoners_that_do_not_share_one_budget() -> None:
    harness = Harness()
    stray = _budgeted(ScriptedReasoner(label="R"), ExperimentBudget(), arm="R")
    clock = _clock()

    with pytest.raises(ValueError, match="budget"):
        run_experiment(
            reasoners=ArmReasoners(f=harness.reasoners.f, a=harness.reasoners.a, r=stray),
            clock=lambda: next(clock),
            id_factory=_counter_id_factory(),
        )
    assert harness.call_counts() == (0, 0, 0)


# --- summarisation failure after the walk ------------------------------------------------


def test_replay_failure_after_the_walk_returns_aborted_runtime_with_all_48_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("replay exploded")

    monkeypatch.setattr(runner_module, "replay_matches", _explode)
    harness = Harness()

    result = harness.run()

    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error == (
        "RuntimeError: replay exploded; SUMMARY_FAILED (A): RuntimeError: replay exploded"
    )
    assert [c.status for c in result.cells] == ["COMPLETED"] * CELL_COUNT
    assert all(c.error is None for c in result.cells)
    assert sum(len(c.requests) for c in result.cells) == 96
    assert harness.call_counts() == (32, 32, 32)
    assert result.budget.frontier_calls == 96
    for arm, summary in (("F", result.f), ("A", result.a)):
        last = _cell(result, arm, 16)
        assert summary.ledger and summary.ledger == last.ledger
        assert summary.final_state == last.state_snapshot
        assert summary.final_view == last.view_snapshot
        assert summary.replay is None
        assert len(summary.requests) == 32 and len(summary.reference_snapshots) == 32
        assert set(summary.roots) == set(LOCI)
        assert summary.authorizations == tuple(
            a for c in _cells_for(result, arm) for a in c.authorizations
        )
        assert summary.authorizations
    assert set(result.r_cells) == set(range(1, 17))
    assert len(result.measurements) == 96


def test_cell_record_failure_inside_the_failed_handler_preserves_earlier_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner's own view derivation raises once T2 evidence is in a ledger: the
    cell's COMPLETED record fails, the FAILED record degrades to no view, and the run
    still returns with the earlier records intact."""
    real_derive_view = runner_module.derive_view

    def _explode_once_t2_is_admitted(semantic: Any) -> Any:
        if evidence_id(2, "A") in semantic.evidence:
            raise RuntimeError("view exploded")
        return real_derive_view(semantic)

    monkeypatch.setattr(runner_module, "derive_view", _explode_once_t2_is_admitted)
    harness = Harness()
    failing = _position("A", 2)  # the first T2 position
    assert failing == 3

    result = harness.run()

    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error is not None and result.error.startswith("RuntimeError: view exploded")
    assert [c.status for c in result.cells[:failing]] == ["COMPLETED"] * failing
    assert all(c.view_snapshot is not None for c in result.cells[:failing])
    failed = result.cells[failing]
    assert failed.status == "FAILED" and failed.arm == "A" and failed.t == 2
    assert failed.error is not None and failed.error.startswith("RuntimeError: view exploded")
    assert result.error.startswith(failed.error)
    assert [r.call_number for r in failed.requests] == [1, 2]
    assert len(failed.reference_snapshots) == 2
    assert failed.view_snapshot is None
    assert failed.state_snapshot is not None
    assert evidence_id(2, "A") in failed.state_snapshot.semantic.evidence
    assert len(failed.ledger) > len(_cell(result, "A", 1).ledger)
    assert [c.status for c in result.cells[failing + 1 :]] == ["NOT_RUN"] * (
        CELL_COUNT - failing - 1
    )
    assert harness.call_counts() == (2, 4, 2)
    assert result.budget.frontier_calls == 8
    # A's summary cannot derive its view either: safest values, and the error says so.
    assert result.a.final_state == failed.state_snapshot
    assert result.a.final_view == _cell(result, "A", 1).view_snapshot
    assert result.a.ledger == failed.ledger
    assert len(result.a.requests) == 4
    assert result.a.replay is None
    assert "SUMMARY" in result.error
    # F never saw T2: its summary is complete and replays.
    assert result.f.replay is not None and result.f.replay.status == "REPLAY_MATCH"
    assert result.f.final_view == _cell(result, "F", 1).view_snapshot


# --- capture identity (review fix) -------------------------------------------------------


def test_run_reconstruction_step_has_the_briefs_public_signature_and_no_capture_kwarg() -> None:
    parameters = inspect.signature(run_reconstruction_step).parameters
    assert list(parameters) == ["t", "position", "reasoner", "clock", "id_factory"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    inner = ScriptedReasoner(label="R")
    reasoner = _budgeted(inner, ExperimentBudget(), arm="R")
    clock = _clock()

    with pytest.raises(TypeError, match="capture"):
        run_reconstruction_step(  # type: ignore[call-arg]
            t=1,
            position=2,
            reasoner=reasoner,
            clock=lambda: next(clock),
            id_factory=_counter_id_factory(),
            capture=object(),
        )
    assert inner.requests == []


def test_capture_whose_identity_does_not_match_the_schedule_entry_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The R step builds its capture for position+1: the scheduler's sink refuses it before
    any frontier call, the cell FAILS as CAPTURE_IDENTITY, and the run aborts (runtime)."""
    real = runner_module.run_reconstruction_step

    def _shifted(**kwargs: Any) -> Any:
        return real(**{**kwargs, "position": kwargs["position"] + 1})

    monkeypatch.setattr(runner_module, "run_reconstruction_step", _shifted)
    harness = Harness()

    result = harness.run()

    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error is not None and result.error.startswith("RuntimeError: CAPTURE_IDENTITY")
    failed = result.cells[_position("R", 1)]
    assert failed.status == "FAILED" and failed.position == 2 and failed.arm == "R"
    assert failed.error == result.error
    assert failed.requests == () and failed.reference_snapshots == ()
    assert [c.status for c in result.cells[:2]] == ["COMPLETED", "COMPLETED"]
    assert [c.status for c in result.cells[3:]] == ["NOT_RUN"] * (CELL_COUNT - 3)
    assert harness.call_counts() == (2, 2, 0)


def test_persistent_capture_with_a_foreign_t_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    real = runner_module._run_persistent_step

    def _shifted(session: Any, t: int, **kwargs: Any) -> Any:
        return real(session, t + 1, **kwargs)

    monkeypatch.setattr(runner_module, "_run_persistent_step", _shifted)
    harness = Harness()

    result = harness.run()

    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error is not None and result.error.startswith("RuntimeError: CAPTURE_IDENTITY")
    assert result.cells[0].status == "FAILED" and (result.cells[0].arm, result.cells[0].t) == (
        "F",
        1,
    )
    assert [c.status for c in result.cells[1:]] == ["NOT_RUN"] * (CELL_COUNT - 1)
    assert harness.call_counts() == (0, 0, 0)


def test_capture_sink_is_write_once_per_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """A step that registers a second capture for the same open position is refused."""
    real = runner_module.run_reconstruction_step

    def _twice(**kwargs: Any) -> Any:
        real(**kwargs)
        return real(**kwargs)

    monkeypatch.setattr(runner_module, "run_reconstruction_step", _twice)
    harness = Harness()

    result = harness.run()

    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error is not None and result.error.startswith("RuntimeError: CAPTURE_IDENTITY")
    failed = result.cells[_position("R", 1)]
    assert failed.status == "FAILED"
    # The first, identity-valid capture is the one recovered: its two calls are kept.
    assert [r.call_number for r in failed.requests] == [1, 2]
    assert harness.call_counts() == (2, 2, 2)


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


def test_runner_imports_no_answer_key_or_outer_layer_module_and_forks_nothing() -> None:
    tree = ast.parse(RUNNER_SOURCE)
    for name in _imported_modules(tree):
        last = name.rsplit(".", 1)[-1]
        assert last not in FORBIDDEN_RUNNER_IMPORTS, name
    defined_classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    defined_functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "RecordingReasoner" not in defined_classes
    assert "RequestRecord" not in defined_classes
    assert "assimilate_ablation_delta" not in defined_functions
    assert "assimilate_delta" not in defined_functions
    assert "measure_step" not in defined_functions
    imported = _imported_modules(tree)
    assert "foundry.experiments.contrastive_unseen.records.RecordingReasoner" in imported
    assert "foundry.experiments.contrastive_unseen.ablation.assimilate_ablation_delta" in imported
    assert "foundry.application.incremental_assimilation.assimilate_delta" in imported
    assert "foundry.experiments.long_horizon_bounded.measurements.measure_step" in imported


def test_gate_12_fresh_ledger_contract_holds_on_the_runner_source() -> None:
    passed, detail = contrastive_integrity._r_uses_fresh_ledger({"runner.py": RUNNER_SOURCE})
    assert passed, detail


def test_runner_has_exactly_two_frontier_paths_one_catch_site_and_no_retry() -> None:
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
    (assimilate,) = [
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_assimilate"
    ]
    assert "arm" in {a.arg for a in assimilate.args.args + assimilate.args.kwonlyargs}
    assert not any(
        isinstance(n, ast.Attribute) and n.attr == "arm" for n in ast.walk(assimilate)
    ), "_assimilate selects the frontier path from its explicit arm argument only"
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
    assert not any(len(h.body) == 1 and isinstance(h.body[0], ast.Pass) for h in handlers)
    catching = [node for node in ast.walk(tree) if isinstance(node, ast.Try) and node.handlers]
    assert len(catching) == 1, "the runner catches once, around each scheduled cell"
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
