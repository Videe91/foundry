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
  whatever its own ledger already holds, and the run continues with the next T from its
  own empty ledger. Failure isolates to the T it happened in.

Budget (plan constraint 13): ``MAX_R_CALLS`` frontier calls for the whole run. Every T
attempted is budgeted at ``CALLS_PER_DELTA`` calls whether or not both were made; a T
that would exceed the ceiling is never attempted and is recorded ``NOT_RUN``.

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
from foundry.domain.semantic_view import CurrentSemanticView
from foundry.experiments.longitudinal.timeline import VersionedEvidence, reconstruction_corpus
from foundry.ports.semantic_reasoner import SemanticReasoner

__all__ = [
    "MAX_R_CALLS",
    "SYSTEM_INSTRUCTION_SHA256",
    "ArmRStep",
    "CallRecording",
    "project_id_for",
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


class ArmRStep(FrozenModel):
    """One T of Arm R: what was shown, what was recorded, what the ledger says."""

    t: int
    status: StepStatus
    evidence_shown: tuple[str, ...]
    """Evidence ids of the corpus at T, in timeline order (all versions ``<= T``)."""
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


class _Recorded(FrozenModel):
    """What the reasoner exposed (receipts, raw drafts) — empty when it exposes nothing."""

    receipts: tuple[SemanticReasoningReceipt, ...] = ()
    drafts: tuple[SemanticDraftPayload, ...] = ()

    def since(self, earlier: _Recorded) -> _Recorded:
        """The entries appended after ``earlier`` was taken — one T's worth."""
        return _Recorded(
            receipts=self.receipts[len(earlier.receipts) :],
            drafts=self.drafts[len(earlier.drafts) :],
        )


def _recorded(reasoner: SemanticReasoner) -> _Recorded:
    if isinstance(reasoner, CallRecording):
        return _Recorded(receipts=tuple(reasoner.receipts), drafts=tuple(reasoner.draft_payloads))
    return _Recorded()


def _judgment_ids(ledger: tuple[StoredEvent, ...]) -> tuple[str, ...]:
    return tuple(
        stored.event.payload.judgment.judgment_id
        for stored in ledger
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
        and isinstance(stored.event.payload, SemanticJudgmentPayload)
    )


def _admissions(ledger: tuple[StoredEvent, ...]) -> tuple[AdmissionDecision, ...]:
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
        draft_outputs=(),
        judgment_ids=(),
        admissions=(),
        view=CurrentSemanticView(),
        receipts=(),
        ledger=(),
        error=reason,
    )


def _run_step(
    *,
    t: int,
    reasoner: SemanticReasoner,
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
    before = _recorded(reasoner)
    error: str | None = None
    try:
        assimilate_delta(governor=governor, reasoner=reasoner, delta=corpus, scope=scope)
    except Exception as exc:  # noqa: BLE001 - recorded as this T's failure, never re-attempted
        error = f"{type(exc).__name__}: {exc}"
    recorded = _recorded(reasoner).since(before)
    ledger = tuple(store.load(project_id))
    return ArmRStep(
        t=t,
        status="COMPLETED" if error is None else "FAILED",
        evidence_shown=tuple(item.evidence_id for item in corpus),
        draft_outputs=recorded.drafts,
        judgment_ids=_judgment_ids(ledger),
        admissions=_admissions(ledger),
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
    though every T is its own project. The budget is checked before each T; a T that
    would push the run past ``MAX_R_CALLS`` is recorded ``NOT_RUN`` and never calls.
    """
    steps: list[ArmRStep] = []
    calls_made = 0
    for t in sorted({version.t for version in timeline}):
        if calls_made + CALLS_PER_DELTA > MAX_R_CALLS:
            shown = tuple(item.evidence_id for item in reconstruction_corpus(timeline, t))
            steps.append(
                _not_run(
                    t,
                    shown,
                    f"budget: {calls_made} calls made, T{t} needs {CALLS_PER_DELTA}, "
                    f"MAX_R_CALLS is {MAX_R_CALLS}",
                )
            )
            continue
        calls_made += CALLS_PER_DELTA
        steps.append(
            _run_step(
                t=t,
                reasoner=reasoner,
                timeline=timeline,
                policy=policy,
                clock=clock,
                id_factory=id_factory,
                scope=scope,
            )
        )
    return tuple(steps)
