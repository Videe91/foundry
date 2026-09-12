"""Reconstruction arm runner — Arm R (9P Task 13; spec §27, §28).

A **fresh** governor, ledger and project id at every T. Input at T is every evidence
version with step ``<= T`` — old and new, with Git lineage — so the model can in
principle reason about change from raw material alone. The two-call shape is exactly
Arm F's (``assimilate_delta``: Call 1 ``BIND_TO_ADDRESS | CREATE_ADDRESS``, Call 2
``SUPPORTS_CLAIM | ASSERT_CLAIM | SUPERSEDE | CONFLICTS_WITH``) run over that corpus as
the "delta" with **empty** known state: Call 1 can only create, Call 2 sees the addresses
Call 1 created and no known claims. No supersession, support or conflict is possible in
R because R has no prior claim or judgment to refer to — that is the thesis, not a
handicap (spec §27).

What this module deliberately does not do:

* no authority step and no human path — nothing here records an authority object,
  submits a judgment directly, or offers anything to a human (spec §28: authorizations
  occur only in F);
* no reasoner construction — the caller supplies the ``SemanticReasoner``; the same
  adapter, model, effort and system instruction (``SYSTEM_INSTRUCTION_SHA256`` is
  re-exported from the one adapter, never restated) serve both arms;
* no re-attempt — a failure at one T is recorded as that T's ``FAILED`` step, with
  whatever its own ledger already holds, and the arm stops: every later T is recorded
  ``NOT_RUN`` with the error ``"stopped: T<n> failed"`` and causes no call (9P-C-R2:
  the first failed frontier step ends all frontier calls; nothing is re-attempted). A
  ``KeyboardInterrupt`` mid-step is recorded the same way with the error
  ``"INTERRUPTED: KeyboardInterrupt"`` and the result is returned normally (ruling
  R2-b, as R12-f in Arm F); ``SystemExit`` is never caught.

Budget (plan constraint 13): ``MAX_R_CALLS`` frontier calls for the whole run. The
ceiling is checked before each T against the number of requests actually forwarded so
far (``len(recorder.requests)`` — a T that failed on Call 1 counts one, never
``CALLS_PER_DELTA``); a T whose two calls would exceed the ceiling is never attempted
and is recorded ``NOT_RUN``. The recorder refuses any single call past the ceiling.

Request log (ruling R12-c): the caller's reasoner is wrapped once per run in a
``RequestRecorder`` — a delegating proxy that logs every ``ReasoningRequest`` it forwards
and changes nothing else (fingerprint and proposals pass through untouched). Each step's
``allowed_kinds_per_call`` is the sorted ``JudgmentKind`` values of every request the
reasoner actually received in that T, in call order, so a later deterministic check can
read what was requested (E10) from the record rather than from the harness's intent.
The recorder also refuses to forward a call past its ceiling — a second line behind
the per-T budget check.

Evidence re-projection: the loaded timeline carries one project id; each T here is its
own project (``PROJ-9P-R-T{t}``). Items are copied with only ``project_id`` replaced —
evidence id, content, content hash, scope, observation time and lineage are untouched —
so the corpus at T is exactly ``reconstruction_corpus(timeline, t)`` re-addressed to
that T's ledger. Nothing here compares, ranks, filters or interprets evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final, Literal, Protocol, runtime_checkable

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import (
    SYSTEM_INSTRUCTION_SHA256,
    SemanticDraftPayload,
    SemanticReasoningReceipt,
)
from foundry.application.incremental_assimilation import CALLS_PER_DELTA, assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import FrozenModel
from foundry.domain.events import (
    EventType,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.domain.semantic_view import CurrentSemanticView
from foundry.experiments.longitudinal.timeline import VersionedEvidence, reconstruction_corpus
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = [
    "MAX_R_CALLS",
    "SYSTEM_INSTRUCTION_SHA256",
    "ArmRStep",
    "CallRecording",
    "RecordedCalls",
    "RequestRecorder",
    "ledger_admissions",
    "ledger_judgment_ids",
    "not_run_steps",
    "project_id_for",
    "recorded_calls",
    "run_arm_r",
]

MAX_R_CALLS: Final[int] = 8
"""Four T × two calls. Never exceeded; a T that would exceed it is ``NOT_RUN``."""

PROJECT_ID_PREFIX: Final[str] = "PROJ-9P-R-T"

type StepStatus = Literal["COMPLETED", "FAILED", "NOT_RUN"]


@runtime_checkable
class CallRecording(Protocol):
    """What a reasoner *may* expose about its calls (the xAI adapter does).

    Optional by design: a reasoner without these surfaces yields empty tuples. The
    runner never invents a receipt or a draft.
    """

    @property
    def receipts(self) -> tuple[SemanticReasoningReceipt, ...]: ...

    @property
    def draft_payloads(self) -> tuple[SemanticDraftPayload, ...]: ...


class RequestRecorder:
    """Delegating proxy: logs every request forwarded to the reasoner; changes nothing.

    Shared by both arms. ``allowed_kinds_since`` renders the log as sorted kind values
    per call. Refuses to forward a call once ``max_calls`` have been forwarded.
    """

    def __init__(self, inner: SemanticReasoner, *, max_calls: int) -> None:
        self._inner = inner
        self._max_calls = max_calls
        self.requests: list[ReasoningRequest] = []

    @property
    def inner(self) -> SemanticReasoner:
        return self._inner

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if len(self.requests) >= self._max_calls:
            raise RuntimeError(
                f"budget: {len(self.requests)} calls already made; max_calls is {self._max_calls}"
            )
        self.requests.append(request)
        return self._inner.propose(request)

    def since(self, index: int) -> tuple[ReasoningRequest, ...]:
        """The requests forwarded after ``index`` were already logged — one T's worth."""
        return tuple(self.requests[index:])

    def allowed_kinds_since(self, index: int) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(sorted(kind.value for kind in request.allowed_judgment_kinds))
            for request in self.since(index)
        )


class ArmRStep(FrozenModel):
    """One T of Arm R: what was shown, what was recorded, what the ledger says."""

    t: int
    status: StepStatus
    evidence_shown: tuple[str, ...]
    """Evidence ids of the corpus at T, in timeline order (all versions ``<= T``)."""
    allowed_kinds_per_call: tuple[tuple[str, ...], ...]
    """Sorted ``JudgmentKind`` values of each request the reasoner received in this T."""
    draft_outputs: tuple[SemanticDraftPayload, ...]
    """Raw draft payloads received during this T, if the reasoner exposes them."""
    judgment_ids: tuple[str, ...]
    """Every judgment recorded in this T's ledger, in submission order."""
    admissions: tuple[AdmissionDecision, ...]
    """Every admission decided in this T's ledger, in submission order."""
    view: CurrentSemanticView
    receipts: tuple[SemanticReasoningReceipt, ...]
    """Receipts of the calls made during this T, if the reasoner exposes them."""
    ledger: tuple[StoredEvent, ...]
    """This T's whole ledger — its own store, its own project, sequence from 1."""
    error: str | None = None


def project_id_for(t: int) -> str:
    return f"{PROJECT_ID_PREFIX}{t}"


def _reprojected_corpus(
    timeline: tuple[VersionedEvidence, ...], t: int, project_id: str
) -> tuple[EvidenceItem, ...]:
    """``reconstruction_corpus(timeline, t)`` re-addressed to ``project_id``; nothing else."""
    return tuple(
        item.model_copy(update={"project_id": project_id})
        for item in reconstruction_corpus(timeline, t)
    )


class RecordedCalls(FrozenModel):
    """What the reasoner exposed (receipts, raw drafts) — empty when it exposes nothing.

    Shared by both arms; nothing here is ever invented by a runner.
    """

    receipts: tuple[SemanticReasoningReceipt, ...] = ()
    drafts: tuple[SemanticDraftPayload, ...] = ()

    def since(self, earlier: RecordedCalls) -> RecordedCalls:
        """The entries appended after ``earlier`` was taken — one T's worth."""
        return RecordedCalls(
            receipts=self.receipts[len(earlier.receipts) :],
            drafts=self.drafts[len(earlier.drafts) :],
        )


def recorded_calls(reasoner: SemanticReasoner) -> RecordedCalls:
    """Snapshot of the reasoner's exposed receipts/drafts; empty if it exposes none."""
    if isinstance(reasoner, CallRecording):
        return RecordedCalls(
            receipts=tuple(reasoner.receipts), drafts=tuple(reasoner.draft_payloads)
        )
    return RecordedCalls()


def ledger_judgment_ids(ledger: tuple[StoredEvent, ...]) -> tuple[str, ...]:
    """Every judgment id recorded in ``ledger``, in order. Read-only."""
    return tuple(
        stored.event.payload.judgment.judgment_id
        for stored in ledger
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
        and isinstance(stored.event.payload, SemanticJudgmentPayload)
    )


def ledger_admissions(ledger: tuple[StoredEvent, ...]) -> tuple[AdmissionDecision, ...]:
    """Every admission decided in ``ledger``, in order, as ``AdmissionDecision``s."""
    return tuple(
        AdmissionDecision(
            judgment_id=stored.event.payload.judgment_id,
            route=stored.event.payload.route,
            reasons=stored.event.payload.reasons,
            corroborating_judgment_ids=stored.event.payload.corroborating_judgment_ids,
        )
        for stored in ledger
        if stored.event.event_type is EventType.SEMANTIC_ADMISSION_DECIDED
        and isinstance(stored.event.payload, SemanticAdmissionPayload)
    )


def _not_run(t: int, evidence_shown: tuple[str, ...], reason: str) -> ArmRStep:
    return ArmRStep(
        t=t,
        status="NOT_RUN",
        evidence_shown=evidence_shown,
        allowed_kinds_per_call=(),
        draft_outputs=(),
        judgment_ids=(),
        admissions=(),
        view=CurrentSemanticView(),
        receipts=(),
        ledger=(),
        error=reason,
    )


def _corpus_ids(timeline: tuple[VersionedEvidence, ...], t: int) -> tuple[str, ...]:
    return tuple(item.evidence_id for item in reconstruction_corpus(timeline, t))


def not_run_steps(timeline: tuple[VersionedEvidence, ...], reason: str) -> tuple[ArmRStep, ...]:
    """A structural ``NOT_RUN`` record for every T of ``timeline``; no reasoner, no ledger.

    For the caller that must not start Arm R at all (the entry point after any Arm F
    step ``FAILED``, 9P-C-R2). ``evidence_shown`` is the corpus each T *would* have
    received — structural reporting only; nothing was shown to anything.
    """
    return tuple(
        _not_run(t, _corpus_ids(timeline, t), reason)
        for t in sorted({version.t for version in timeline})
    )


def _run_step(
    *,
    t: int,
    recorder: RequestRecorder,
    timeline: tuple[VersionedEvidence, ...],
    policy: AdmissionPolicy,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    scope: str,
) -> ArmRStep:
    """One T from a fresh store and governor; any exception becomes this T's ``FAILED``."""
    project_id = project_id_for(t)
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store, project_id=project_id, policy=policy, clock=clock, id_factory=id_factory
    )
    corpus = _reprojected_corpus(timeline, t, project_id)
    request_from = len(recorder.requests)
    before = recorded_calls(recorder.inner)
    error: str | None = None
    try:
        assimilate_delta(governor=governor, reasoner=recorder, delta=corpus, scope=scope)
    except KeyboardInterrupt:
        # R12-f applied to R (ruling R2-b): an interrupt during a live call is recorded
        # like any failure so this T's ledger and every earlier T reach the artifacts;
        # SystemExit is deliberately not caught.
        error = "INTERRUPTED: KeyboardInterrupt"
    except Exception as exc:  # noqa: BLE001 - recorded as this T's failure, never re-attempted
        error = f"{type(exc).__name__}: {exc}"
    recorded = recorded_calls(recorder.inner).since(before)
    ledger = tuple(store.load(project_id))
    return ArmRStep(
        t=t,
        status="COMPLETED" if error is None else "FAILED",
        evidence_shown=tuple(item.evidence_id for item in corpus),
        allowed_kinds_per_call=recorder.allowed_kinds_since(request_from),
        draft_outputs=recorded.drafts,
        judgment_ids=ledger_judgment_ids(ledger),
        admissions=ledger_admissions(ledger),
        view=governor.view(),
        receipts=recorded.receipts,
        ledger=ledger,
        error=error,
    )


def run_arm_r(
    *,
    reasoner: SemanticReasoner,
    timeline: tuple[VersionedEvidence, ...],
    policy: AdmissionPolicy,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    scope: str,
) -> tuple[ArmRStep, ...]:
    """Run Arm R over every T in ``timeline``, each from its own empty ledger.

    ``id_factory`` is shared across T's on purpose: event ids stay globally unique even
    though every T is its own project. After a ``FAILED`` T every later T is ``NOT_RUN``
    and never calls. The budget is checked before each T against the requests actually
    forwarded so far; a T that would push the run past ``MAX_R_CALLS`` is recorded
    ``NOT_RUN`` and never calls.
    """
    steps: list[ArmRStep] = []
    recorder = RequestRecorder(reasoner, max_calls=MAX_R_CALLS)
    failed_at: int | None = None
    for t in sorted({version.t for version in timeline}):
        if failed_at is not None:
            steps.append(_not_run(t, _corpus_ids(timeline, t), f"stopped: T{failed_at} failed"))
            continue
        calls_made = len(recorder.requests)
        if calls_made + CALLS_PER_DELTA > MAX_R_CALLS:
            steps.append(
                _not_run(
                    t,
                    _corpus_ids(timeline, t),
                    f"budget: {calls_made} calls made, T{t} needs {CALLS_PER_DELTA}, "
                    f"MAX_R_CALLS is {MAX_R_CALLS}",
                )
            )
            continue
        step = _run_step(
            t=t,
            recorder=recorder,
            timeline=timeline,
            policy=policy,
            clock=clock,
            id_factory=id_factory,
            scope=scope,
        )
        steps.append(step)
        if step.status == "FAILED":
            failed_at = t
    return tuple(steps)
