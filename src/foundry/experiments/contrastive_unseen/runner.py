"""Interleaved three-arm runner with global fail-fast budgets (spec §4, §7-§9, §12,
§16; T5 brief; clarifications C2, C4, C5).

``run_experiment`` walks the frozen ``ARM_SCHEDULE`` exactly once, position by
position, and never groups arms: F and A are two persistent sessions (one
``InMemoryEventStore`` and one ``SemanticGovernor`` each, project ids ``PROJ-9P2-F`` /
``PROJ-9P2-A``, one project-wide architect ``AuthorityRecord`` written before T1) that
advance T1 -> T4 in schedule order; every R entry is a fresh store/governor
(``PROJ-9P2-R-T{t}``) fed the cumulative corpus through ``t`` and discarded after its
record is captured. F and R run the frozen production ``assimilate_delta``; A runs the
experiment-only ``assimilate_ablation_delta``. After a persistent arm's T1, its A/B/N
roots are designated mechanically from its own state; after its T2 Call 2 the ``A``
root -- and after its T4 Call 2 the ``B`` root -- is offered to the mechanical
authority protocol, before the next scheduled arm. Nothing happens at T3 and nothing
ever happens for R.

Law of this module: it schedules, accounts, and records; it decides nothing about
meaning. It never grades a semantic checkpoint, never reads the sealed answer key
(``expectations``), never calls ``decision_rule``, and never imports the outer layers
(``artifacts``, ``integrity``, ``leakage``) -- the CLI owns those. A semantically wrong
but structurally valid response is an admission fact, not an exception, and never
stops the run.

Budget (spec §12; Controller Ruling 2): one shared ``ExperimentBudget`` is held by all
three ``BudgetedReasoner`` wrappers. A 25th frontier call is refused BEFORE it is
forwarded; ``frontier_calls`` is incremented exactly when a request is forwarded, even
if the call then raises; every receipt the inner adapter appends is accounted exactly
once as ``Decimal(str(cost_usd))`` (more than one new receipt for one call is a runtime
integrity failure); and a call whose accounted cost takes the cumulative total above
``Decimal(str(MAX_COST_USD))`` is recorded and then refused before its judgments reach
governance. Human authorizations share the same object through the ``authority``
module's own ceiling.

Failure discipline (spec §16): exactly one catch site, ``_attempt``, applied once around
each scheduled arm/T operation (including its designation/authority sub-steps).
``XAIProviderError`` -> ``ABORTED_PROVIDER``; ``SemanticOutputError`` ->
``ABORTED_MODEL_CONTRACT``; ``AuthorizationCeilingExceeded`` ->
``ABORTED_AUTHORITY_CEILING``; ``ExperimentBudgetExceeded`` -> ``ABORTED_BUDGET``;
``KeyboardInterrupt`` -> ``ABORTED_RUNTIME`` with error ``INTERRUPTED:
KeyboardInterrupt``; every other ``Exception`` (including ``ContextUnsupported``,
identity-guard and integrity errors) -> ``ABORTED_RUNTIME``. ``SystemExit`` is never
caught. After the first failure no further arm/T runs, every remaining schedule
position is a structural ``NOT_RUN`` record, and nothing is retried, repaired, or
re-attempted.

Preservation (spec §16 "preserve all artifacts already produced"; whole-branch review
Finding 1): schedule walking and summarisation are separate phases. Building a step
record or an arm summary makes NO frontier call, so a failure there is recorded, never
allowed to discard what the schedule produced: a FAILED record that cannot be built in
full is built without its view snapshot, then without its state snapshot, then
minimally (arm, t, position, project id, requests, error); an arm summary that cannot
be built with replay is built without it (``replay=None``), then from the arm's last
captured snapshots. Each degradation is a different, smaller operation; the same
operation is never re-attempted, and no frontier call is involved. Every degradation
is named in the run error; one after a completed walk makes the run
``ABORTED_RUNTIME``, one after an aborted walk leaves the first classification in
place. ``run_experiment`` may
also be given a caller-owned ``progress`` list that receives every step record as it is
produced, so the caller can persist them even if this function still raised.

Gate 12 contract (``integrity.py``): ``run_reconstruction_step`` takes ``t`` and
constructs ``InMemoryEventStore()`` in its own straight-line body; no store anywhere in
this file is constructed under a loop or comprehension -- the two persistent stores
come from two explicit ``_persistent_session`` calls.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from functools import partial
from typing import Any, Final, Literal, NamedTuple

from pydantic import Field

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import SemanticOutputError, XAIProviderError
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.domain.semantic_view import CurrentSemanticView
from foundry.domain.state import IntentState
from foundry.experiments.contrastive_unseen.ablation import assimilate_ablation_delta
from foundry.experiments.contrastive_unseen.authority import (
    AuthorizationCeilingExceeded,
    AuthorizationRecord,
    authorize_root_supersessions,
    record_architect_authority,
)
from foundry.experiments.contrastive_unseen.designation import (
    RootDesignation,
    designate_seed_root,
)
from foundry.experiments.contrastive_unseen.records import Arm, RecordingReasoner, RequestRecord
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    SCOPE,
    persistent_delta,
    reconstruction_corpus,
)
from foundry.experiments.intent_v2_dogfood import ReplayResult
from foundry.experiments.longitudinal.scoring import replay_matches
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = [
    "A_PROJECT_ID",
    "F_PROJECT_ID",
    "ROOT_SEEDS",
    "ArmReasoners",
    "ArmSummary",
    "BudgetSnapshot",
    "BudgetedReasoner",
    "ExperimentBudget",
    "ExperimentBudgetExceeded",
    "PersistentArm",
    "RootKey",
    "RunResult",
    "RunStatus",
    "StepRecord",
    "StepStatus",
    "build_arm_reasoners",
    "r_project_id",
    "run_experiment",
    "run_reconstruction_step",
]

PersistentArm = Literal["F", "A"]
RootKey = Literal["A", "B", "N"]
StepStatus = Literal["COMPLETED", "FAILED", "NOT_RUN"]
_Snapshots = Literal["state_and_view", "state", "none"]

F_PROJECT_ID: Final = "PROJ-9P2-F"
A_PROJECT_ID: Final = "PROJ-9P2-A"
_R_PROJECT_ID_PREFIX: Final = "PROJ-9P2-R-T"

ROOT_SEEDS: Final[tuple[tuple[RootKey, str], ...]] = (
    ("A", "EV-K-A1"),
    ("B", "EV-K-B1"),
    ("N", "EV-K-N1"),
)
"""Spec §7: the three T1 seed evidence ids whose roots F and A designate. Ids only."""

_AUTHORITY_CHECKPOINTS: Final[dict[int, tuple[Literal[2, 4], Literal["A", "B"]]]] = {
    2: (2, "A"),
    4: (4, "B"),
}
"""Spec §8: T2 -> designated ``A`` root; T4 -> designated ``B`` root. Nothing at T3."""

_ARMS: Final[dict[str, Arm]] = {"F": "F", "A": "A", "R": "R"}
_COST_CEILING: Final = Decimal(str(MAX_COST_USD))
_INTERRUPTED: Final = "INTERRUPTED: KeyboardInterrupt"
_RECORD_DEGRADATIONS: Final[tuple[_Snapshots, ...]] = ("state_and_view", "state", "none")
"""Finding 1: the successively smaller forms of a FAILED record, tried in this order."""


def r_project_id(t: int) -> str:
    """Controller Ruling 6: ``PROJ-9P2-R-T{t}`` -- one fresh project id per R entry."""
    return f"{_R_PROJECT_ID_PREFIX}{t}"


# --------------------------------------------------------------------------- status


class RunStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    ABORTED_PREFLIGHT = "ABORTED_PREFLIGHT"
    ABORTED_PROVIDER = "ABORTED_PROVIDER"
    ABORTED_MODEL_CONTRACT = "ABORTED_MODEL_CONTRACT"
    ABORTED_RUNTIME = "ABORTED_RUNTIME"
    ABORTED_AUTHORITY_CEILING = "ABORTED_AUTHORITY_CEILING"
    ABORTED_BUDGET = "ABORTED_BUDGET"
    COMPLETED = "COMPLETED"


# --------------------------------------------------------------------------- budget


class ExperimentBudgetExceeded(RuntimeError):
    """A frontier call or cost ceiling would be (or has just been) breached."""


class ExperimentBudget:
    """The one mutable, run-scoped tally shared by every arm (spec §12).

    Structurally satisfies ``authority.AuthorizationBudget``; it is never durable
    state and never enters the ledger.
    """

    def __init__(self) -> None:
        self.frontier_calls: int = 0
        self.provider_cost_usd: Decimal = Decimal("0")
        self.human_authorizations: int = 0

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            frontier_calls=self.frontier_calls,
            provider_cost_usd=str(self.provider_cost_usd),
            human_authorizations=self.human_authorizations,
        )


class BudgetSnapshot(FrozenModel):
    """The budget as it stood when the result was assembled. ``judge_calls`` is always
    0: no judge exists in this harness (``MAX_JUDGE_CALLS == 0``)."""

    frontier_calls: int = Field(ge=0)
    provider_cost_usd: str
    human_authorizations: int = Field(ge=0)
    judge_calls: int = 0


class BudgetedReasoner:
    """A ``SemanticReasoner`` enforcing the shared call/cost ceilings around a
    ``RecordingReasoner``; it changes neither the request nor the judgments."""

    def __init__(self, recording: RecordingReasoner, budget: ExperimentBudget) -> None:
        self._recording = recording
        self._budget = budget

    @property
    def recording(self) -> RecordingReasoner:
        return self._recording

    @property
    def budget(self) -> ExperimentBudget:
        return self._budget

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._recording.fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        """Refuse past the call ceiling before forwarding; account every receipt once;
        refuse (after recording the spent call) once cost exceeds the ceiling."""
        budget = self._budget
        if budget.frontier_calls >= MAX_FRONTIER_CALLS:
            raise ExperimentBudgetExceeded(
                f"frontier-call ceiling {MAX_FRONTIER_CALLS} reached; refusing call "
                f"{budget.frontier_calls + 1} before it is forwarded"
            )
        receipts_before = len(self._recording.receipts)
        budget.frontier_calls += 1
        try:
            result = self._recording.propose(request)
        finally:
            self._account_new_receipts(receipts_before)
        if budget.provider_cost_usd > _COST_CEILING:
            raise ExperimentBudgetExceeded(
                f"cumulative provider cost {budget.provider_cost_usd} USD exceeds "
                f"{_COST_CEILING} USD after call {budget.frontier_calls}; that call is "
                "recorded and no later call is permitted"
            )
        return result

    def _account_new_receipts(self, receipts_before: int) -> None:
        new_receipts = self._recording.receipts[receipts_before:]
        if len(new_receipts) > 1:
            raise RuntimeError(
                f"RECEIPT_INTEGRITY: {len(new_receipts)} receipts appended for one propose "
                "call; at most one is possible"
            )
        for receipt in new_receipts:
            cost = getattr(receipt, "cost_usd", None)
            if cost is None:
                raise RuntimeError("RECEIPT_INTEGRITY: receipt carries no cost_usd")
            self._budget.provider_cost_usd += Decimal(str(cost))


class ArmReasoners(NamedTuple):
    f: BudgetedReasoner
    a: BudgetedReasoner
    r: BudgetedReasoner


def build_arm_reasoners(
    *,
    inner_f: SemanticReasoner,
    inner_a: SemanticReasoner,
    inner_r: SemanticReasoner,
    budget: ExperimentBudget,
) -> ArmReasoners:
    """Wrap each arm's reasoner: ``RecordingReasoner(inner, arm=...)`` inside a
    ``BudgetedReasoner`` sharing ``budget``. Constructs no provider client."""
    return ArmReasoners(
        f=BudgetedReasoner(RecordingReasoner(inner_f, arm="F"), budget),
        a=BudgetedReasoner(RecordingReasoner(inner_a, arm="A"), budget),
        r=BudgetedReasoner(RecordingReasoner(inner_r, arm="R"), budget),
    )


# --------------------------------------------------------------------------- records (C4)


class StepRecord(FrozenModel):
    """One schedule position: what was shown, admitted, designated, authorized, and
    what the ledger held afterwards. Raw material for artifacts and adjudication."""

    arm: Arm
    t: int = Field(ge=1, le=4)
    position: int = Field(ge=0, le=11)
    status: StepStatus
    error: str | None
    project_id: str
    evidence_ids_shown: tuple[str, ...]
    requests: tuple[RequestRecord, ...]
    stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]
    neighborhood: tuple[str, ...]
    claim_neighborhood: tuple[str, ...]
    """F/R: the addresses Call 2 was shown; always ``()`` for A (no widening exists)."""
    pending_supersede_judgment_ids: tuple[str, ...]
    """As surfaced by the assimilation outcome, before any authority step."""
    root_designations: tuple[RootDesignation, ...]
    """Non-empty only after a persistent arm's T1."""
    authorizations: tuple[AuthorizationRecord, ...]
    receipts: tuple[Any, ...]
    draft_payloads: tuple[Any, ...]
    state_snapshot: IntentState | None
    view_snapshot: CurrentSemanticView | None
    ledger: tuple[StoredEvent, ...]
    """The arm's full ledger after this step (F/A), or this R entry's whole ledger."""


class ArmSummary(FrozenModel):
    arm: PersistentArm
    project_id: str
    roots: dict[RootKey, RootDesignation]
    ledger: tuple[StoredEvent, ...]
    final_state: IntentState
    final_view: CurrentSemanticView
    replay: ReplayResult | None
    """Replay equality of the final ledger against the final state/view; F only."""
    authorizations: tuple[AuthorizationRecord, ...]
    requests: tuple[RequestRecord, ...]


class RunResult(FrozenModel):
    status: RunStatus
    error: str | None
    steps: tuple[StepRecord, ...] = Field(min_length=12, max_length=12)
    f: ArmSummary
    a: ArmSummary
    r_steps: dict[int, StepRecord]
    budget: BudgetSnapshot
    schedule: tuple[tuple[int, str], ...] = ARM_SCHEDULE


# --------------------------------------------------------------------------- sessions


class _PersistentSession:
    """One persistent arm's store, governor, reasoner, roots and authority log."""

    def __init__(
        self,
        *,
        arm: PersistentArm,
        project_id: str,
        store: InMemoryEventStore,
        governor: SemanticGovernor,
        reasoner: BudgetedReasoner,
    ) -> None:
        self.arm: PersistentArm = arm
        self.project_id = project_id
        self.store = store
        self.governor = governor
        self.reasoner = reasoner
        self.roots: dict[RootKey, RootDesignation] = {}
        self.authorizations: list[AuthorizationRecord] = []

    def summary(self, *, replay: bool) -> ArmSummary:
        """The arm's final ledger, state and view from its governor; the replay check
        (F only) when ``replay`` is set."""
        ledger = tuple(self.store.load(self.project_id))
        state = self.governor.state()
        return ArmSummary(
            arm=self.arm,
            project_id=self.project_id,
            roots=dict(self.roots),
            ledger=ledger,
            final_state=state,
            final_view=self.governor.view(),
            replay=replay_matches(ledger, state) if replay and self.arm == "F" else None,
            authorizations=tuple(self.authorizations),
            requests=self.reasoner.recording.records,
        )

    def safest_summary(self, steps: tuple[StepRecord, ...]) -> ArmSummary:
        """The summary when the governor cannot derive state or view: the arm's last
        captured ledger/state/view snapshots (empty state, empty view when none)."""
        own = [step for step in steps if step.arm == self.arm]
        with_state = [step for step in own if step.state_snapshot is not None]
        with_view = [step for step in own if step.view_snapshot is not None]
        ledger = with_state[-1].ledger if with_state else ()
        state = with_state[-1].state_snapshot if with_state else None
        view = with_view[-1].view_snapshot if with_view else None
        return ArmSummary(
            arm=self.arm,
            project_id=self.project_id,
            roots=dict(self.roots),
            ledger=ledger,
            final_state=state if state is not None else IntentState(project_id=self.project_id),
            final_view=view if view is not None else CurrentSemanticView(),
            replay=None,
            authorizations=tuple(self.authorizations),
            requests=self.reasoner.recording.records,
        )


def _governor(
    store: InMemoryEventStore,
    project_id: str,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> SemanticGovernor:
    return SemanticGovernor(
        store=store,
        project_id=project_id,
        policy=AdmissionPolicy(),
        clock=clock,
        id_factory=id_factory,
    )


def _persistent_session(
    arm: PersistentArm,
    project_id: str,
    reasoner: BudgetedReasoner,
    *,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> _PersistentSession:
    """A fresh persistent session with its architect authority recorded before T1."""
    store = InMemoryEventStore()
    governor = _governor(store, project_id, clock=clock, id_factory=id_factory)
    record_architect_authority(governor, clock=clock, id_factory=id_factory)
    return _PersistentSession(
        arm=arm, project_id=project_id, store=store, governor=governor, reasoner=reasoner
    )


# --------------------------------------------------------------------------- one step


class _StepCapture:
    """Mutable per-step capture so a failed step still records what it produced."""

    def __init__(self, *, arm: Arm, t: int, position: int, project_id: str) -> None:
        self.arm: Arm = arm
        self.t = t
        self.position = position
        self.project_id = project_id
        self.store: InMemoryEventStore | None = None
        self.governor: SemanticGovernor | None = None
        self.records_before = 0
        self.receipts_before = 0
        self.drafts_before = 0
        self.reasoner: BudgetedReasoner | None = None
        self.stage_decisions: tuple[
            tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]
        ] = ((), ())
        self.neighborhood: tuple[str, ...] = ()
        self.claim_neighborhood: tuple[str, ...] = ()
        self.pending_supersede_judgment_ids: tuple[str, ...] = ()
        self.root_designations: tuple[RootDesignation, ...] = ()
        self.authorizations: tuple[AuthorizationRecord, ...] = ()

    def attach(
        self, *, store: InMemoryEventStore, governor: SemanticGovernor, reasoner: BudgetedReasoner
    ) -> None:
        """Bind the step to its ledger and reasoner and pin the counters it starts at."""
        self.store = store
        self.governor = governor
        self.reasoner = reasoner
        recording = reasoner.recording
        self.records_before = len(recording.records)
        self.receipts_before = len(recording.receipts)
        self.drafts_before = len(recording.draft_payloads)
        recording.begin_step(self.t)

    def record(
        self,
        *,
        status: StepStatus,
        error: str | None,
        snapshots: _Snapshots = "state_and_view",
    ) -> StepRecord:
        """The step's record. ``snapshots`` names the derived parts to include: the
        replayed state and its view, the state only, or neither (the ledger itself is
        always copied) -- for a record whose fuller form could not be built."""
        requests: tuple[RequestRecord, ...] = ()
        receipts: tuple[Any, ...] = ()
        drafts: tuple[Any, ...] = ()
        if self.reasoner is not None:
            recording = self.reasoner.recording
            requests = recording.records[self.records_before :]
            receipts = recording.receipts[self.receipts_before :]
            drafts = recording.draft_payloads[self.drafts_before :]
        ledger: tuple[StoredEvent, ...] = ()
        state: IntentState | None = None
        view: CurrentSemanticView | None = None
        if self.store is not None and self.governor is not None:
            ledger = tuple(self.store.load(self.project_id))
            if snapshots != "none":
                state = self.governor.state()
            if snapshots == "state_and_view":
                view = self.governor.view()
        return StepRecord(
            arm=self.arm,
            t=self.t,
            position=self.position,
            status=status,
            error=error,
            project_id=self.project_id,
            evidence_ids_shown=_evidence_ids_shown(requests),
            requests=requests,
            stage_decisions=self.stage_decisions,
            neighborhood=self.neighborhood,
            claim_neighborhood=self.claim_neighborhood,
            pending_supersede_judgment_ids=self.pending_supersede_judgment_ids,
            root_designations=self.root_designations,
            authorizations=self.authorizations,
            receipts=receipts,
            draft_payloads=drafts,
            state_snapshot=state,
            view_snapshot=view,
            ledger=ledger,
        )

    def minimal(self, *, status: StepStatus, error: str | None) -> StepRecord:
        """The least a record can hold when nothing else can be read: identity, the
        request records (plain copies of what was rendered), and the error."""
        requests: tuple[RequestRecord, ...] = ()
        if self.reasoner is not None:
            requests = self.reasoner.recording.records[self.records_before :]
        return StepRecord(
            arm=self.arm,
            t=self.t,
            position=self.position,
            status=status,
            error=error,
            project_id=self.project_id,
            evidence_ids_shown=_evidence_ids_shown(requests),
            requests=requests,
            stage_decisions=self.stage_decisions,
            neighborhood=self.neighborhood,
            claim_neighborhood=self.claim_neighborhood,
            pending_supersede_judgment_ids=self.pending_supersede_judgment_ids,
            root_designations=self.root_designations,
            authorizations=self.authorizations,
            receipts=(),
            draft_payloads=(),
            state_snapshot=None,
            view_snapshot=None,
            ledger=(),
        )


def _evidence_ids_shown(requests: tuple[RequestRecord, ...]) -> tuple[str, ...]:
    """Citable evidence ids across the step's requests, request order, de-duplicated."""
    return tuple(
        dict.fromkeys(
            evidence_id for record in requests for evidence_id in record.citable_evidence_ids
        )
    )


def _assimilate(
    capture: _StepCapture,
    *,
    governor: SemanticGovernor,
    reasoner: BudgetedReasoner,
    delta: tuple[EvidenceItem, ...],
) -> None:
    """Exactly two frontier calls through the arm's frozen path; capture the outcome."""
    if capture.arm == "A":
        ablation = assimilate_ablation_delta(
            governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE
        )
        capture.stage_decisions = ablation.stage_decisions
        capture.neighborhood = ablation.neighborhood
        capture.claim_neighborhood = ()
        capture.pending_supersede_judgment_ids = ablation.pending_supersede_judgment_ids
        return
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE)
    capture.stage_decisions = outcome.stage_decisions
    capture.neighborhood = outcome.neighborhood
    capture.claim_neighborhood = outcome.claim_neighborhood
    capture.pending_supersede_judgment_ids = outcome.pending_supersede_judgment_ids


def _run_persistent_step(
    session: _PersistentSession,
    *,
    t: int,
    capture: _StepCapture,
    budget: ExperimentBudget,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> StepRecord:
    """One persistent T: assimilate, then (T1) designate roots or (T2/T4) authorize."""
    capture.attach(store=session.store, governor=session.governor, reasoner=session.reasoner)
    _assimilate(
        capture,
        governor=session.governor,
        reasoner=session.reasoner,
        delta=persistent_delta(t, project_id=session.project_id),
    )
    if t == 1:
        state = session.governor.state()
        roots = tuple(
            designate_seed_root(state, key=key, seed_evidence_id=seed) for key, seed in ROOT_SEEDS
        )
        session.roots = {root.key: root for root in roots}
        capture.root_designations = roots
    checkpoint = _AUTHORITY_CHECKPOINTS.get(t)
    if checkpoint is not None:
        checkpoint_t, root_key = checkpoint
        records = authorize_root_supersessions(
            governor=session.governor,
            arm=session.arm,
            t=checkpoint_t,
            root=session.roots[root_key],
            pending_judgment_ids=capture.pending_supersede_judgment_ids,
            budget=budget,
            clock=clock,
            id_factory=id_factory,
        )
        session.authorizations.extend(records)
        capture.authorizations = records
    return capture.record(status="COMPLETED", error=None)


def run_reconstruction_step(
    *,
    t: int,
    reasoner: BudgetedReasoner,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    capture: _StepCapture | None = None,
) -> StepRecord:
    """Arm R at ``t``: a FRESH store and governor (``PROJ-9P2-R-T{t}``), the cumulative
    corpus through ``t`` as one batch, exactly two calls through the frozen production
    path, no authority record, no root, no memory of any earlier R entry.

    The store is constructed here, in straight-line code, so gate 12 can verify it
    statically. ``capture`` lets the scheduler keep a failed entry's partial record;
    a standalone call may omit it.
    """
    project_id = r_project_id(t)
    if capture is None:
        capture = _StepCapture(
            arm="R", t=t, position=ARM_SCHEDULE.index((t, "R")), project_id=project_id
        )
    store = InMemoryEventStore()
    governor = _governor(store, project_id, clock=clock, id_factory=id_factory)
    capture.attach(store=store, governor=governor, reasoner=reasoner)
    _assimilate(
        capture,
        governor=governor,
        reasoner=reasoner,
        delta=reconstruction_corpus(t, project_id=project_id),
    )
    return capture.record(status="COMPLETED", error=None)


# --------------------------------------------------------------------------- failure


def _attempt[T](operation: Callable[[], T]) -> T | BaseException:
    """The one catch site (spec §16): run ``operation`` once and return its result, or
    the ``KeyboardInterrupt``/``Exception`` it raised, for the caller to classify and
    record. ``SystemExit`` propagates. Nothing is re-attempted here."""
    try:
        return operation()
    except KeyboardInterrupt as interrupt:
        return interrupt
    except Exception as exc:  # noqa: BLE001 - returned for classification, never swallowed
        return exc


def _classify(exc: BaseException) -> RunStatus:
    if isinstance(exc, XAIProviderError):
        return RunStatus.ABORTED_PROVIDER
    if isinstance(exc, SemanticOutputError):
        return RunStatus.ABORTED_MODEL_CONTRACT
    if isinstance(exc, AuthorizationCeilingExceeded):
        return RunStatus.ABORTED_AUTHORITY_CEILING
    if isinstance(exc, ExperimentBudgetExceeded):
        return RunStatus.ABORTED_BUDGET
    return RunStatus.ABORTED_RUNTIME


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _not_run(*, arm: Arm, t: int, position: int, project_id: str) -> StepRecord:
    return _StepCapture(arm=arm, t=t, position=position, project_id=project_id).record(
        status="NOT_RUN", error=None
    )


def _failure_text(exc: BaseException) -> str:
    return _INTERRUPTED if isinstance(exc, KeyboardInterrupt) else _error_text(exc)


def _failed_record(capture: _StepCapture, *, error: str) -> tuple[StepRecord, str]:
    """The FAILED record for a step, degraded only as far as necessary: in full; else
    without its view; else without state and view; else minimal. Returns the record and
    the run error, extended with each record-construction failure that occurred."""
    for snapshots in _RECORD_DEGRADATIONS:
        record = _attempt(
            partial(capture.record, status="FAILED", error=error, snapshots=snapshots)
        )
        if not isinstance(record, BaseException):
            return record, error
        error = f"{error}; STEP_RECORD_FAILED ({snapshots}): {_failure_text(record)}"
    return capture.minimal(status="FAILED", error=error), error


def _summarise(
    session: _PersistentSession, steps: tuple[StepRecord, ...]
) -> tuple[ArmSummary, str | None]:
    """The arm's summary, degraded only as far as necessary: with the replay check (F);
    else without it; else from the arm's captured snapshots. Returns the summary and the
    failure text that forced a degradation, if any."""
    full = _attempt(partial(session.summary, replay=True))
    if not isinstance(full, BaseException):
        return full, None
    error = _failure_text(full)
    without_replay = _attempt(partial(session.summary, replay=False))
    if not isinstance(without_replay, BaseException):
        return without_replay, error
    error = f"{error}; SUMMARY_WITHOUT_REPLAY_FAILED: {_failure_text(without_replay)}"
    return session.safest_summary(steps), error


def _require_shared_budget(reasoners: ArmReasoners) -> ExperimentBudget:
    """Caller-contract check before any call: one budget, and each wrapper is the arm
    it will be scheduled as (its recorded policy identity depends on it)."""
    budget = reasoners.f.budget
    if reasoners.a.budget is not budget or reasoners.r.budget is not budget:
        raise ValueError("the three arm reasoners must share exactly one budget object")
    arms = (reasoners.f.recording.arm, reasoners.a.recording.arm, reasoners.r.recording.arm)
    if arms != ("F", "A", "R"):
        raise ValueError(f"arm reasoners are recorded as {arms}, expected ('F', 'A', 'R')")
    return budget


# --------------------------------------------------------------------------- the run


def _scheduled_step(
    arm: Arm,
    *,
    t: int,
    capture: _StepCapture,
    sessions: dict[str, _PersistentSession],
    reasoner_r: BudgetedReasoner,
    budget: ExperimentBudget,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
) -> StepRecord:
    """One schedule position: the R entry or the persistent arm's T, with its record."""
    if arm == "R":
        return run_reconstruction_step(
            t=t, reasoner=reasoner_r, clock=clock, id_factory=id_factory, capture=capture
        )
    return _run_persistent_step(
        sessions[arm], t=t, capture=capture, budget=budget, clock=clock, id_factory=id_factory
    )


def run_experiment(
    *,
    reasoner_f: BudgetedReasoner,
    reasoner_a: BudgetedReasoner,
    reasoner_r: BudgetedReasoner,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    progress: list[StepRecord] | None = None,
) -> RunResult:
    """Walk ``ARM_SCHEDULE`` once; stop at the first operational failure; never retry;
    then summarise without ever discarding what the walk produced. ``progress``, when
    given, receives every step record as it is produced."""
    reasoners = ArmReasoners(f=reasoner_f, a=reasoner_a, r=reasoner_r)
    budget = _require_shared_budget(reasoners)
    f = _persistent_session("F", F_PROJECT_ID, reasoner_f, clock=clock, id_factory=id_factory)
    a = _persistent_session("A", A_PROJECT_ID, reasoner_a, clock=clock, id_factory=id_factory)
    sessions: dict[str, _PersistentSession] = {"F": f, "A": a}

    status = RunStatus.COMPLETED
    error: str | None = None
    steps: list[StepRecord] = progress if progress is not None else []
    for position, (t, scheduled) in enumerate(ARM_SCHEDULE):
        arm = _ARMS[scheduled]
        project_id = sessions[arm].project_id if arm in sessions else r_project_id(t)
        if status is not RunStatus.COMPLETED:
            steps.append(_not_run(arm=arm, t=t, position=position, project_id=project_id))
            continue
        capture = _StepCapture(arm=arm, t=t, position=position, project_id=project_id)
        outcome = _attempt(
            partial(
                _scheduled_step,
                arm,
                t=t,
                capture=capture,
                sessions=sessions,
                reasoner_r=reasoner_r,
                budget=budget,
                clock=clock,
                id_factory=id_factory,
            )
        )
        if isinstance(outcome, BaseException):
            status = _classify(outcome)
            record, error = _failed_record(capture, error=_failure_text(outcome))
        else:
            record = outcome
        steps.append(record)

    walked = tuple(steps)
    summaries: dict[PersistentArm, ArmSummary] = {}
    for session in (f, a):
        summary, degraded = _summarise(session, walked)
        summaries[session.arm] = summary
        if degraded is None:
            continue
        # A degraded summary after a completed walk is the run's failure; after an
        # aborted walk the first classification stands and the degradation is appended.
        if status is RunStatus.COMPLETED:
            status, error = RunStatus.ABORTED_RUNTIME, degraded
        else:
            error = f"{error}; SUMMARY_FAILED ({session.arm}): {degraded}"
    return RunResult(
        status=status,
        error=error,
        steps=walked,
        f=summaries["F"],
        a=summaries["A"],
        r_steps={step.t: step for step in walked if step.arm == "R"},
        budget=budget.snapshot(),
        schedule=ARM_SCHEDULE,
    )
