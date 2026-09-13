"""48-cell three-arm runner with global fail-fast budgets and exact-request reference
snapshots for the 9P3 long-horizon bounded-memory experiment (spec §8, §9, §12,
§16–§18; T4 brief).

``run_experiment`` walks the frozen ``protocol.ARM_SCHEDULE`` exactly once -- 16
versions x 3 arms = 48 cells, position by position -- and never groups arms. F and A are
two persistent sessions (one ``InMemoryEventStore`` and one ``SemanticGovernor`` each,
project ids ``PROJ-9P3-F`` / ``PROJ-9P3-A``, one project-wide architect
``AuthorityRecord`` written before T1) that advance T1 -> T16 in schedule order; every R
cell is a fresh store/governor (``PROJ-9P3-R-T{t:02d}``) fed the cumulative corpus
through ``t`` and dropped after its record is captured. F and R run the frozen
production ``assimilate_delta``; A runs the reused, unmodified 9P2 ablation path
``assimilate_ablation_delta``. After a persistent arm's T1 all twelve loci roots are
designated mechanically from its own state. At every authority checkpoint T
(``protocol.AUTHORITY_CHECKPOINTS``) the arm's eligible targets are snapshotted from its
pre-T state BEFORE T's evidence is ingested and, after that arm's Call 2, offered to the
mechanical AGREE over that same immutable snapshot. Nothing happens at other T and
nothing ever happens for R.

Law of this module: it schedules, accounts, and records; it decides nothing about
meaning. It never grades a semantic checkpoint, never reads the sealed answer key
(``expectations``), never selects an architecture, and never imports the outer layers
(``artifacts``, ``integrity``, ``leakage``) -- the CLI owns those. It defines no
recorder, no ablation path and no measurement: ``RecordingReasoner``/``RequestRecord``,
``assimilate_ablation_delta`` and ``measure_step`` are reused by import only. A
semantically wrong but structurally valid response is an admission fact, not an
exception, and never stops the run.

Budget (spec §17): one shared ``ExperimentBudget`` is held by all three
``BudgetedReasoner`` wrappers. The 97th frontier call is refused BEFORE it is forwarded
(the recorder never sees it); ``frontier_calls`` is incremented exactly when a request
is forwarded, even if the call then raises; every receipt the inner adapter appends is
accounted exactly once as ``Decimal(str(cost_usd))`` (more than one new receipt for one
call is a runtime integrity failure); and a call whose accounted cost takes the
cumulative total above ``Decimal(str(MAX_COST_USD))`` is recorded and then refused
before its judgments reach governance. Human authorizations share the same object
through the ``authority`` module's own ceiling.

Exact-request reference closure: ``BudgetedReasoner.propose`` copies the four id tuples
(``snapshot_request_references``) from the very ``ReasoningRequest`` object BEFORE it is
delegated (RAW REFERENCE CAPTURE) and, in ``finally`` -- after the reused
``RecordingReasoner`` has appended its ``RequestRecord`` and delegated -- binds them to
that record's identity as exactly one ``RequestReferenceSnapshot`` (SNAPSHOT IDENTITY
BINDING). Nothing is appended while ``inner.propose`` runs; a forwarded call that
produced anything other than exactly one new ``RequestRecord`` is a
``ReferenceSnapshotMismatch``. A snapshot is never rebuilt from later state.

Cell shape: a COMPLETED cell must carry exactly two ``RequestRecord``s with call numbers
``(1, 2)``, exactly two snapshots bound to them and -- when the inner reasoner exposes
receipts -- exactly two receipts; anything else is a ``CALL_SHAPE`` runtime failure,
never a silently omitted measurement. ``measure_step`` runs only on a structurally valid
completed cell; F/A rows carry ``None`` for the R-only cumulative raw-evidence count.

Failure discipline (spec §16): exactly one catch site, ``_attempt``, applied once around
each scheduled cell (including its designation/authority sub-steps).
``XAIProviderError`` -> ``ABORTED_PROVIDER``; ``SemanticOutputError`` ->
``ABORTED_MODEL_CONTRACT``; ``AuthorizationCeilingExceeded`` ->
``ABORTED_AUTHORITY_CEILING``; ``ExperimentBudgetExceeded`` -> ``ABORTED_BUDGET``;
``KeyboardInterrupt`` -> ``ABORTED_RUNTIME`` with error ``INTERRUPTED:
KeyboardInterrupt``; every other ``Exception`` (including ``ContextUnsupported``,
identity-guard and integrity errors) -> ``ABORTED_RUNTIME``. ``SystemExit`` is never
caught. After the first failure no further cell runs, every remaining schedule position
is a structural ``NOT_RUN`` record carrying its enumerated position, and nothing is
retried, repaired, or re-attempted; ``RunResult.cells`` always has exactly 48 entries.

Preservation (spec §16 "preserve all artifacts already produced"): schedule walking and
summarisation are separate phases. Building a cell record or an arm summary makes NO
frontier call, so a failure there is recorded, never allowed to discard what the
schedule produced: a FAILED record that cannot be built in full is built without its
view snapshot, then without its state snapshot, then minimally; an arm summary that
cannot be built with replay is built without it (``replay=None``), then from the arm's
last captured snapshots. Each degradation is a different, smaller operation; the same
operation is never re-attempted. Every degradation is named in the run error; one after
a completed walk makes the run ``ABORTED_RUNTIME``, one after an aborted walk leaves the
first classification in place. ``run_experiment`` may also be given a caller-owned
``progress`` list that receives every attempted cell record as it is produced.

Gate 12 contract (static, ``integrity``): ``run_reconstruction_step`` takes ``t`` and
constructs ``InMemoryEventStore()`` in its own straight-line body; no store anywhere in
this file is constructed under a loop or comprehension -- the two persistent stores come
from two explicit ``_persistent_session`` calls.
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
from foundry.application.incremental_assimilation import DeltaOutcome, assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.events import StoredEvent
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState
from foundry.experiments.contrastive_unseen.ablation import (
    AblationOutcome,
    assimilate_ablation_delta,
)
from foundry.experiments.contrastive_unseen.records import RecordingReasoner, RequestRecord
from foundry.experiments.intent_v2_dogfood import ReplayResult
from foundry.experiments.long_horizon_bounded.authority import (
    AuthorizationCeilingExceeded,
    AuthorizationRecord,
    EligibleTargets,
    authorize_eligible_supersessions,
    record_architect_authority,
    snapshot_eligible_targets,
)
from foundry.experiments.long_horizon_bounded.designation import (
    RootDesignation,
    designate_t1_roots,
)
from foundry.experiments.long_horizon_bounded.measurements import CallMeasurement, measure_step
from foundry.experiments.long_horizon_bounded.protocol import (
    A_PROJECT_ID,
    ARM_SCHEDULE,
    AUTHORITY_CHECKPOINTS,
    F_PROJECT_ID,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    Arm,
    r_project_id,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    SCOPE,
    VERSION_COUNT,
    Locus,
    persistent_delta,
    reconstruction_corpus,
)
from foundry.experiments.longitudinal.scoring import replay_matches
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = [
    "ArmReasoners",
    "ArmSummary",
    "BudgetSnapshot",
    "BudgetedReasoner",
    "CellRecord",
    "CellStatus",
    "ExperimentBudget",
    "ExperimentBudgetExceeded",
    "PersistentArm",
    "ReferenceSnapshotMismatch",
    "RequestReferenceSnapshot",
    "RunResult",
    "RunStatus",
    "build_arm_reasoners",
    "run_experiment",
    "run_reconstruction_step",
    "snapshot_request_references",
]

PersistentArm = Literal["F", "A"]
CellStatus = Literal["COMPLETED", "FAILED", "NOT_RUN"]
_Snapshots = Literal["state_and_view", "state", "none"]
_Outcome = DeltaOutcome | AblationOutcome
_References = tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]

CELL_COUNT: Final[int] = len(ARM_SCHEDULE)
_COST_CEILING: Final = Decimal(str(MAX_COST_USD))
_INTERRUPTED: Final = "INTERRUPTED: KeyboardInterrupt"
_EXPECTED_CALL_NUMBERS: Final[tuple[int, ...]] = (1, 2)
_RECORD_DEGRADATIONS: Final[tuple[_Snapshots, ...]] = ("state_and_view", "state", "none")
"""The successively smaller forms of a FAILED record, tried in this order."""


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


class ReferenceSnapshotMismatch(RuntimeError):
    """A forwarded call produced other than exactly one new ``RequestRecord``, so no
    reference snapshot can be bound to a record identity."""


class ExperimentBudget:
    """The one mutable, run-scoped tally shared by every arm (spec §17).

    Structurally satisfies ``authority.AuthorizationBudget``; it is never durable
    state and never enters the ledger. ``judge_calls`` is always 0: no judge exists in
    this harness (``MAX_JUDGE_CALLS == 0``).
    """

    def __init__(self) -> None:
        self.frontier_calls: int = 0
        self.provider_cost_usd: Decimal = Decimal("0")
        self.human_authorizations: int = 0
        self.judge_calls: int = 0

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            frontier_calls=self.frontier_calls,
            provider_cost_usd=str(self.provider_cost_usd),
            human_authorizations=self.human_authorizations,
            judge_calls=self.judge_calls,
        )


class BudgetSnapshot(FrozenModel):
    """The budget as it stood when the result was assembled."""

    frontier_calls: int = Field(ge=0)
    provider_cost_usd: str
    human_authorizations: int = Field(ge=0)
    judge_calls: int = Field(ge=0, default=0)


# --------------------------------------------------------------------------- references


class RequestReferenceSnapshot(FrozenModel):
    """Experiment-only exact-request reference closure, captured from the very
    ``ReasoningRequest`` handed to the reused ``RecordingReasoner`` BEFORE it is
    forwarded; never rebuilt from later state. ``known_claim_creating_judgment_ids[i]``
    is the creating judgment of ``known_claim_ids[i]`` as the request carried it."""

    arm: Arm
    t: int = Field(ge=1)
    call_number: Literal[1, 2]
    request_sha256: str = Field(min_length=64, max_length=64)
    citable_evidence_ids: tuple[str, ...]
    known_address_ids: tuple[str, ...]
    known_claim_ids: tuple[str, ...]
    known_claim_creating_judgment_ids: tuple[str, ...]


def snapshot_request_references(request: ReasoningRequest) -> _References:
    """Frozen capture rule, structural only, in request order."""
    return (
        tuple(item.evidence_id for item in request.evidence),
        tuple(address.address_id for address in request.known_addresses),
        tuple(claim.claim_id for claim in request.known_claims),
        tuple(claim.created_by_judgment_id for claim in request.known_claims),
    )


class BudgetedReasoner:
    """A ``SemanticReasoner`` enforcing the shared call/cost ceilings around a reused
    ``RecordingReasoner`` and binding one reference snapshot per forwarded call; it
    changes neither the request nor the judgments.

    Two distinct moments must not be confused: RAW REFERENCE CAPTURE (the four id
    tuples are copied from the exact request object BEFORE delegation) and SNAPSHOT
    IDENTITY BINDING (the bound ``RequestReferenceSnapshot`` is appended in ``finally``,
    AFTER the reused recorder has supplied the ``RequestRecord`` identity).
    """

    def __init__(self, recording: RecordingReasoner, budget: ExperimentBudget) -> None:
        self._recording = recording
        self._budget = budget
        self._snapshots: list[RequestReferenceSnapshot] = []

    @property
    def recording(self) -> RecordingReasoner:
        return self._recording

    @property
    def budget(self) -> ExperimentBudget:
        return self._budget

    @property
    def snapshots(self) -> tuple[RequestReferenceSnapshot, ...]:
        return tuple(self._snapshots)

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._recording.fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        """The frozen sequence: (1) refuse past the call ceiling before forwarding;
        (2) raw reference capture from the exact request; (3) count the call and forward
        through the recorder, then in ``finally`` bind exactly one snapshot to the one
        new record and account every new receipt once; (4) refuse (after recording the
        spent call) once cost exceeds the ceiling; (5) return."""
        budget = self._budget
        if budget.frontier_calls >= MAX_FRONTIER_CALLS:
            raise ExperimentBudgetExceeded(
                f"frontier-call ceiling {MAX_FRONTIER_CALLS} reached; refusing call "
                f"{budget.frontier_calls + 1} before it is forwarded"
            )
        refs = snapshot_request_references(request)
        recording = self._recording
        records_before = len(recording.records)
        receipts_before = len(recording.receipts)
        budget.frontier_calls += 1
        try:
            result = recording.propose(request)
        finally:
            self._bind_snapshot(refs, records_before)
            self._account_new_receipts(receipts_before)
        if budget.provider_cost_usd > _COST_CEILING:
            raise ExperimentBudgetExceeded(
                f"cumulative provider cost {budget.provider_cost_usd} USD exceeds "
                f"{_COST_CEILING} USD after call {budget.frontier_calls}; that call is "
                "recorded and no later call is permitted"
            )
        return result

    def _bind_snapshot(self, refs: _References, records_before: int) -> None:
        """SNAPSHOT IDENTITY BINDING: exactly one new record, exactly one snapshot."""
        new_records = self._recording.records[records_before:]
        if len(new_records) != 1:
            raise ReferenceSnapshotMismatch(
                f"REFERENCE_SNAPSHOT: forwarded call appended {len(new_records)} "
                "RequestRecords; exactly one is required to bind a reference snapshot"
            )
        record = new_records[0]
        self._snapshots.append(
            RequestReferenceSnapshot(
                arm=record.arm,
                t=record.t,
                call_number=record.call_number,
                request_sha256=record.request_sha256,
                citable_evidence_ids=refs[0],
                known_address_ids=refs[1],
                known_claim_ids=refs[2],
                known_claim_creating_judgment_ids=refs[3],
            )
        )

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


# --------------------------------------------------------------------------- records


class CellRecord(FrozenModel):
    """One schedule position: what was shown, admitted, designated, authorized,
    measured, and what the ledger held afterwards. Raw material for artifacts and
    adjudication; never a claim of semantic truth."""

    arm: Arm
    t: int = Field(ge=1, le=VERSION_COUNT)
    position: int = Field(ge=0, le=CELL_COUNT - 1)
    status: CellStatus
    error: str | None
    project_id: str
    evidence_ids_shown: tuple[str, ...]
    requests: tuple[RequestRecord, ...]
    reference_snapshots: tuple[RequestReferenceSnapshot, ...]
    """Bound 1:1, in order, to ``requests``."""
    stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]
    neighborhood: tuple[str, ...]
    claim_neighborhood: tuple[str, ...]
    """F/R: the addresses Call 2 was shown; always ``()`` for A (no widening exists)."""
    pending_supersede_judgment_ids: tuple[str, ...]
    """As surfaced by the assimilation outcome, before any authority step."""
    root_designations: tuple[RootDesignation, ...]
    """Non-empty only after a persistent arm's T1."""
    eligible_targets: EligibleTargets | None
    """The pre-T snapshot at a persistent arm's checkpoint T; ``None`` elsewhere."""
    authorizations: tuple[AuthorizationRecord, ...]
    measurements: tuple[CallMeasurement, ...]
    """Two rows for a structurally valid COMPLETED cell with receipts; else ``()``."""
    receipts: tuple[Any, ...]
    draft_payloads: tuple[Any, ...]
    state_snapshot: IntentState | None
    view_snapshot: CurrentSemanticView | None
    ledger: tuple[StoredEvent, ...]
    """The arm's full ledger after this cell (F/A), or this R cell's whole ledger."""


class ArmSummary(FrozenModel):
    arm: PersistentArm
    project_id: str
    roots: dict[Locus, RootDesignation]
    ledger: tuple[StoredEvent, ...]
    final_state: IntentState
    final_view: CurrentSemanticView
    replay: ReplayResult | None
    """Replay equality of the final ledger against the final state/view (F and A)."""
    eligible_targets: tuple[EligibleTargets, ...]
    authorizations: tuple[AuthorizationRecord, ...]
    requests: tuple[RequestRecord, ...]
    reference_snapshots: tuple[RequestReferenceSnapshot, ...]


class RunResult(FrozenModel):
    status: RunStatus
    error: str | None
    cells: tuple[CellRecord, ...] = Field(min_length=CELL_COUNT, max_length=CELL_COUNT)
    f: ArmSummary
    a: ArmSummary
    r_cells: dict[int, CellRecord]
    budget: BudgetSnapshot
    measurements: tuple[CallMeasurement, ...]
    """Every cell's rows, in cell order."""
    schedule: tuple[tuple[int, Arm], ...] = ARM_SCHEDULE


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
        self.roots: dict[Locus, RootDesignation] = {}
        self.eligible_targets: list[EligibleTargets] = []
        self.authorizations: list[AuthorizationRecord] = []

    def summary(self, *, replay: bool) -> ArmSummary:
        """The arm's final ledger, state and view from its governor; the replay check
        when ``replay`` is set."""
        ledger = tuple(self.store.load(self.project_id))
        state = self.governor.state()
        return ArmSummary(
            arm=self.arm,
            project_id=self.project_id,
            roots=dict(self.roots),
            ledger=ledger,
            final_state=state,
            final_view=derive_view(state.semantic),
            replay=replay_matches(ledger, state) if replay else None,
            eligible_targets=tuple(self.eligible_targets),
            authorizations=tuple(self.authorizations),
            requests=self.reasoner.recording.records,
            reference_snapshots=self.reasoner.snapshots,
        )

    def safest_summary(self, cells: tuple[CellRecord, ...]) -> ArmSummary:
        """The summary when the governor cannot derive state or view: the arm's last
        captured ledger/state/view snapshots (empty state, empty view when none)."""
        own = [cell for cell in cells if cell.arm == self.arm]
        with_state = [cell for cell in own if cell.state_snapshot is not None]
        with_view = [cell for cell in own if cell.view_snapshot is not None]
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
            eligible_targets=tuple(self.eligible_targets),
            authorizations=tuple(self.authorizations),
            requests=self.reasoner.recording.records,
            reference_snapshots=self.reasoner.snapshots,
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


def _project_id_for(arm: Arm, t: int) -> str:
    if arm == "F":
        return F_PROJECT_ID
    if arm == "A":
        return A_PROJECT_ID
    return r_project_id(t)


# --------------------------------------------------------------------------- one cell


class _StepCapture:
    """Mutable per-cell capture, opened before ingestion, so a FAILED cell still
    records everything produced before the failure (records, bound snapshots,
    receipts, drafts, the pre-T eligible snapshot, the outcome, the ledger)."""

    def __init__(self, *, arm: Arm, t: int, position: int, project_id: str) -> None:
        self.arm: Arm = arm
        self.t = t
        self.position = position
        self.project_id = project_id
        self.store: InMemoryEventStore | None = None
        self.governor: SemanticGovernor | None = None
        self.reasoner: BudgetedReasoner | None = None
        self._records_before = 0
        self._snapshots_before = 0
        self._receipts_before = 0
        self._drafts_before = 0
        self.outcome: _Outcome | None = None
        self.eligible: EligibleTargets | None = None
        self.root_designations: tuple[RootDesignation, ...] = ()
        self.authorizations: tuple[AuthorizationRecord, ...] = ()

    def attach(
        self, *, store: InMemoryEventStore, governor: SemanticGovernor, reasoner: BudgetedReasoner
    ) -> None:
        """Bind the cell to its ledger and reasoner and pin the offsets it starts at."""
        self.store = store
        self.governor = governor
        self.reasoner = reasoner
        recording = reasoner.recording
        self._records_before = len(recording.records)
        self._snapshots_before = len(reasoner.snapshots)
        self._receipts_before = len(recording.receipts)
        self._drafts_before = len(recording.draft_payloads)

    def record(
        self,
        *,
        status: CellStatus,
        error: str | None,
        snapshots: _Snapshots = "state_and_view",
    ) -> CellRecord:
        """The cell's record. ``snapshots`` names the derived parts to include: the
        replayed state and its view, the state only, or neither (the ledger itself is
        always copied) -- for a record whose fuller form could not be built."""
        requests: tuple[RequestRecord, ...] = ()
        reference_snapshots: tuple[RequestReferenceSnapshot, ...] = ()
        receipts: tuple[Any, ...] = ()
        drafts: tuple[Any, ...] = ()
        if self.reasoner is not None:
            recording = self.reasoner.recording
            requests = recording.records[self._records_before :]
            reference_snapshots = self.reasoner.snapshots[self._snapshots_before :]
            receipts = recording.receipts[self._receipts_before :]
            drafts = recording.draft_payloads[self._drafts_before :]
        ledger: tuple[StoredEvent, ...] = ()
        state: IntentState | None = None
        view: CurrentSemanticView | None = None
        if self.store is not None and self.governor is not None:
            ledger = tuple(self.store.load(self.project_id))
            if snapshots != "none":
                state = self.governor.state()
            if state is not None and snapshots == "state_and_view":
                view = derive_view(state.semantic)
        measurements = self._measurements(status, requests, reference_snapshots, receipts)
        outcome = self.outcome
        return CellRecord(
            arm=self.arm,
            t=self.t,
            position=self.position,
            status=status,
            error=error,
            project_id=self.project_id,
            evidence_ids_shown=_evidence_ids_shown(requests),
            requests=requests,
            reference_snapshots=reference_snapshots,
            stage_decisions=outcome.stage_decisions if outcome is not None else ((), ()),
            neighborhood=outcome.neighborhood if outcome is not None else (),
            claim_neighborhood=(
                outcome.claim_neighborhood if isinstance(outcome, DeltaOutcome) else ()
            ),
            pending_supersede_judgment_ids=(
                outcome.pending_supersede_judgment_ids if outcome is not None else ()
            ),
            root_designations=self.root_designations,
            eligible_targets=self.eligible,
            authorizations=self.authorizations,
            measurements=measurements,
            receipts=receipts,
            draft_payloads=drafts,
            state_snapshot=state,
            view_snapshot=view,
            ledger=ledger,
        )

    def minimal(self, *, status: CellStatus, error: str | None) -> CellRecord:
        """The least a record can hold when nothing else can be read: identity, the
        request records and their bound snapshots, and the error."""
        requests: tuple[RequestRecord, ...] = ()
        reference_snapshots: tuple[RequestReferenceSnapshot, ...] = ()
        if self.reasoner is not None:
            requests = self.reasoner.recording.records[self._records_before :]
            reference_snapshots = self.reasoner.snapshots[self._snapshots_before :]
        return CellRecord(
            arm=self.arm,
            t=self.t,
            position=self.position,
            status=status,
            error=error,
            project_id=self.project_id,
            evidence_ids_shown=_evidence_ids_shown(requests),
            requests=requests,
            reference_snapshots=reference_snapshots,
            stage_decisions=((), ()),
            neighborhood=(),
            claim_neighborhood=(),
            pending_supersede_judgment_ids=(),
            root_designations=self.root_designations,
            eligible_targets=self.eligible,
            authorizations=self.authorizations,
            measurements=(),
            receipts=(),
            draft_payloads=(),
            state_snapshot=None,
            view_snapshot=None,
            ledger=(),
        )

    def _measurements(
        self,
        status: CellStatus,
        requests: tuple[RequestRecord, ...],
        reference_snapshots: tuple[RequestReferenceSnapshot, ...],
        receipts: tuple[Any, ...],
    ) -> tuple[CallMeasurement, ...]:
        """Rows for a COMPLETED cell only, after its call shape is verified; ``()`` when
        the inner reasoner exposes no receipts. Never a silent omission."""
        if status != "COMPLETED":
            return ()
        exposed = self.reasoner is not None and _receipts_exposed(self.reasoner)
        _require_call_shape(
            arm=self.arm,
            t=self.t,
            requests=requests,
            reference_snapshots=reference_snapshots,
            receipts=receipts if exposed else None,
        )
        if not exposed:
            return ()
        return measure_step(arm=self.arm, t=self.t, records=requests, receipts=receipts)


def _receipts_exposed(reasoner: BudgetedReasoner) -> bool:
    """Whether the inner reasoner carries adapter receipts at all (a live adapter does;
    a bare fake may not). Exposure, not count: an exposed-but-empty tally is a shape
    defect, never a reason to skip measurement."""
    return hasattr(reasoner.recording.inner, "receipts")


def _require_call_shape(
    *,
    arm: Arm,
    t: int,
    requests: tuple[RequestRecord, ...],
    reference_snapshots: tuple[RequestReferenceSnapshot, ...],
    receipts: tuple[Any, ...] | None,
) -> None:
    """A COMPLETED cell is exactly calls (1, 2), two bound snapshots and -- when
    receipts are exposed -- two receipts; anything else is a runtime failure."""
    call_numbers = tuple(record.call_number for record in requests)
    if call_numbers != _EXPECTED_CALL_NUMBERS:
        raise RuntimeError(
            f"CALL_SHAPE: arm {arm} T{t} completed with call numbers {call_numbers}; "
            f"exactly {_EXPECTED_CALL_NUMBERS} are required"
        )
    if len(reference_snapshots) != len(requests):
        raise RuntimeError(
            f"CALL_SHAPE: arm {arm} T{t} completed with {len(reference_snapshots)} reference "
            f"snapshots for {len(requests)} requests; they are bound one to one"
        )
    for record, snapshot in zip(requests, reference_snapshots, strict=True):
        bound = (snapshot.arm, snapshot.t, snapshot.call_number, snapshot.request_sha256)
        if bound != (record.arm, record.t, record.call_number, record.request_sha256):
            raise RuntimeError(
                f"CALL_SHAPE: arm {arm} T{t} reference snapshot {bound} is not bound to its "
                f"record ({record.arm}, {record.t}, {record.call_number}, "
                f"{record.request_sha256})"
            )
    if receipts is not None and len(receipts) != len(requests):
        raise RuntimeError(
            f"CALL_SHAPE: arm {arm} T{t} completed with {len(receipts)} receipts for "
            f"{len(requests)} requests; the inner reasoner exposes receipts, so exactly one "
            "per call is required"
        )


def _evidence_ids_shown(requests: tuple[RequestRecord, ...]) -> tuple[str, ...]:
    """Citable evidence ids across the cell's requests, sorted, de-duplicated."""
    return tuple(sorted({e for record in requests for e in record.citable_evidence_ids}))


def _assimilate(
    capture: _StepCapture,
    *,
    governor: SemanticGovernor,
    reasoner: BudgetedReasoner,
    delta: tuple[EvidenceItem, ...],
) -> _Outcome:
    """Exactly two frontier calls through the arm's frozen path (A: the reused
    ablation path; F and R: production); the outcome is captured as it is produced."""
    outcome: _Outcome
    if capture.arm == "A":
        outcome = assimilate_ablation_delta(
            governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE
        )
    else:
        outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE)
    capture.outcome = outcome
    return outcome


def _run_persistent_step(
    session: _PersistentSession,
    t: int,
    *,
    position: int,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    budget: ExperimentBudget,
    capture: _StepCapture | None = None,
) -> CellRecord:
    """One persistent T: (checkpoint) snapshot eligible targets from pre-T state;
    ingest and make exactly two calls through the arm's frozen path; (T1) designate
    the twelve roots; (checkpoint) offer the snapshot to the mechanical AGREE."""
    if capture is None:
        capture = _StepCapture(
            arm=session.arm, t=t, position=position, project_id=session.project_id
        )
    capture.attach(store=session.store, governor=session.governor, reasoner=session.reasoner)
    if t in AUTHORITY_CHECKPOINTS:
        locus = AUTHORITY_CHECKPOINTS[t]
        root = session.roots.get(locus)
        eligible = snapshot_eligible_targets(
            session.governor.state(),
            arm=session.arm,
            t=t,
            target_locus=locus,
            designated_address_id=root.address_id if root is not None else None,
            ledger_length=session.store.current_sequence(session.project_id),
        )
        session.eligible_targets.append(eligible)
        capture.eligible = eligible
    session.reasoner.recording.begin_step(t)
    outcome = _assimilate(
        capture,
        governor=session.governor,
        reasoner=session.reasoner,
        delta=persistent_delta(t, project_id=session.project_id),
    )
    if t == 1:
        session.roots = designate_t1_roots(session.governor.state())
        capture.root_designations = tuple(session.roots.values())
    if capture.eligible is not None:
        authorizations = authorize_eligible_supersessions(
            governor=session.governor,
            eligible=capture.eligible,
            pending_judgment_ids=outcome.pending_supersede_judgment_ids,
            budget=budget,
            clock=clock,
            id_factory=id_factory,
        )
        session.authorizations.extend(authorizations)
        capture.authorizations = authorizations
    return capture.record(status="COMPLETED", error=None)


def run_reconstruction_step(
    *,
    t: int,
    position: int,
    reasoner: BudgetedReasoner,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    capture: _StepCapture | None = None,
) -> CellRecord:
    """Arm R at ``t``: a FRESH store and governor (``PROJ-9P3-R-T{t:02d}``), the
    cumulative corpus through ``t`` as one batch, exactly two calls through the frozen
    production path, no authority record, no root, no authorization, no memory of any
    earlier R cell. ``position`` is the cell's index in ``ARM_SCHEDULE``.

    The store is constructed here, in straight-line code, so gate 12 can verify it
    statically; the store and governor are dropped when the call returns. ``capture``
    lets the scheduler keep a failed cell's partial record; a standalone call may omit
    it.
    """
    project_id = r_project_id(t)
    if capture is None:
        capture = _StepCapture(arm="R", t=t, position=position, project_id=project_id)
    store = InMemoryEventStore()
    governor = _governor(store, project_id, clock=clock, id_factory=id_factory)
    capture.attach(store=store, governor=governor, reasoner=reasoner)
    reasoner.recording.begin_step(t)
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


def _failure_text(exc: BaseException) -> str:
    return _INTERRUPTED if isinstance(exc, KeyboardInterrupt) else _error_text(exc)


def _not_run(*, arm: Arm, t: int, position: int, project_id: str) -> CellRecord:
    """The structural fill for a position the walk never reached."""
    return _StepCapture(arm=arm, t=t, position=position, project_id=project_id).minimal(
        status="NOT_RUN", error=None
    )


def _failed_record(capture: _StepCapture, *, error: str) -> tuple[CellRecord, str]:
    """The FAILED record for a cell, degraded only as far as necessary: in full; else
    without its view; else without state and view; else minimal. Returns the record and
    the run error, extended with each record-construction failure that occurred."""
    for snapshots in _RECORD_DEGRADATIONS:
        record = _attempt(
            partial(capture.record, status="FAILED", error=error, snapshots=snapshots)
        )
        if not isinstance(record, BaseException):
            return record, error
        error = f"{error}; CELL_RECORD_FAILED ({snapshots}): {_failure_text(record)}"
    return capture.minimal(status="FAILED", error=error), error


def _summarise(
    session: _PersistentSession, cells: tuple[CellRecord, ...]
) -> tuple[ArmSummary, str | None]:
    """The arm's summary, degraded only as far as necessary: with the replay check;
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
    return session.safest_summary(cells), error


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


def run_experiment(
    *,
    reasoners: ArmReasoners,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    progress: list[CellRecord] | None = None,
) -> RunResult:
    """Walk ``ARM_SCHEDULE`` once; stop at the first operational failure; never retry;
    then summarise without ever discarding what the walk produced. ``progress``, when
    given, receives every attempted cell record as it is produced."""
    budget = _require_shared_budget(reasoners)
    f = _persistent_session("F", F_PROJECT_ID, reasoners.f, clock=clock, id_factory=id_factory)
    a = _persistent_session("A", A_PROJECT_ID, reasoners.a, clock=clock, id_factory=id_factory)
    sessions: dict[str, _PersistentSession] = {"F": f, "A": a}

    status = RunStatus.COMPLETED
    error: str | None = None
    cells: list[CellRecord] = []
    for position, (t, arm) in enumerate(ARM_SCHEDULE):
        project_id = _project_id_for(arm, t)
        if status is not RunStatus.COMPLETED:
            cells.append(_not_run(arm=arm, t=t, position=position, project_id=project_id))
            continue
        capture = _StepCapture(arm=arm, t=t, position=position, project_id=project_id)
        operation: Callable[[], CellRecord]
        if arm == "R":
            operation = partial(
                run_reconstruction_step,
                t=t,
                position=position,
                reasoner=reasoners.r,
                clock=clock,
                id_factory=id_factory,
                capture=capture,
            )
        else:
            operation = partial(
                _run_persistent_step,
                sessions[arm],
                t,
                position=position,
                clock=clock,
                id_factory=id_factory,
                budget=budget,
                capture=capture,
            )
        outcome = _attempt(operation)
        if isinstance(outcome, BaseException):
            status = _classify(outcome)
            cell, error = _failed_record(capture, error=_failure_text(outcome))
        else:
            cell = outcome
        cells.append(cell)
        if progress is not None:
            progress.append(cell)

    walked = tuple(cells)
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
        cells=walked,
        f=summaries["F"],
        a=summaries["A"],
        r_cells={cell.t: cell for cell in walked if cell.arm == "R"},
        budget=budget.snapshot(),
        measurements=tuple(row for cell in walked for row in cell.measurements),
        schedule=ARM_SCHEDULE,
    )
