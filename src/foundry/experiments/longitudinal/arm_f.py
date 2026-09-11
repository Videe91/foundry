"""Persistent assimilation arm runner — Arm F (9P Task 12; spec §26, §28, §31, §32).

One governor, one ledger, one project id (``PROJECT_ID``) for the whole run. State
survives across T. Per T: the delta is ingested and assimilated by the two-call shape of
``assimilate_delta`` (Call 1 ``BIND_TO_ADDRESS | CREATE_ADDRESS``, Call 2
``SUPPORTS_CLAIM | ASSERT_CLAIM | SUPERSEDE | CONFLICTS_WITH``); then, and only then,
the step's governance act runs.

Sequence (plan Task 12):

* **T0** — ``record_architect_authority`` writes the project-wide ``AuthorityRecord``
  for the architect. It is the first event of the ledger. No frontier call.
* **T1** — ``assimilate_delta`` over ``persistent_delta(timeline, 1)``; then the
  architect's root selections for Track A, Track B and the control
  (``designate_track_a`` / ``designate_track_b`` / ``designate_control``, each read
  from T1 state) are recorded through ``designate_root`` and the preregistered chains
  (Track A + control, as Task 11 defines them) are attached by
  ``attach_preregistered_chains`` — after T1, before any T2 evidence exists, from T1
  state only.
* **T2..T4** — a structural guard refuses any delta that is empty or that carries an
  item whose ``(artifact_ref, content_sha256)`` already occurred at an earlier T or is
  already in the ledger (failure mode 13: the persistent arm re-reads zero unchanged
  evidence; the run aborts *before* the call); then ``assimilate_delta``; then every
  ``SUPERSEDE`` the outcome reports as pending is offered to the human through
  ``resolve_pending_supersessions`` under the locked ``AuthorizationBudget``.
* **After T3, before T4** — the Track C root (``designate_track_c``, read from T3
  state) is recorded through ``designate_root`` (``TRACK_C_DESIGNATION_T``). No chain
  is attached for it.

Two further structural guards (ruling R12-e), each a ``ValueError`` inside the step:
designated addresses are pairwise distinct across A, B, C and the control (a duplicate
names both tracks and records nothing); and the Track C address must not have been
present in the view at the end of the T before ``TRACK_C_DESIGNATION_T`` (spec §29
E1/E8: C does not exist until T3).

Track identification is structural, never human (ruling R12-d): a pending
``SUPERSEDE`` belongs to track X iff its target judgment is an ``ASSERT_CLAIM`` whose
``address_id`` is track X's designated address; otherwise it is untracked and
``resolve_pending_supersessions`` logs it ``NOT_OFFERED / UNTRACKED``. The control
designation identifies no track. Designations are instrumentation: they write nothing
to the ledger, pin the ledger sequence at which they were made, and are exposed on
``ArmFResult.designations`` — never counted as semantic success.

Failure (spec §32, live discipline): any exception inside a T — the guard, either call,
admission, designation, attachment, or the authority step — marks that T ``FAILED``
with whatever the ledger already holds, every later T ``NOT_RUN``, and the run stops.
Nothing is re-attempted; there is no second path to a call. An ``AuthorizationHalted``
keeps the authorization records completed before the halt.

Budget (plan constraint 13): ``MAX_F_CALLS`` frontier calls for the whole run. The
ceiling is checked before each T (a T that would exceed it is ``NOT_RUN``) and again
before every individual call by the request recorder, which refuses to forward a call
past the ceiling. ``calls_made`` is the number of requests actually handed to the
reasoner.

What was shown: ``assimilate_delta`` assembles both requests internally, so the runner
wraps the caller's reasoner in the shared ``RequestRecorder`` (from ``arm_r``) — a
delegating proxy that logs every ``ReasoningRequest`` it forwards and changes nothing
else (fingerprint and proposals pass through untouched). ``evidence_shown`` /
``addresses_shown`` / ``claims_shown`` are the ids in the two requests of that T, in
request order, de-duplicated; ``allowed_kinds_per_call`` is the sorted kind values of
each forwarded request, in call order (ruling R12-c). Receipts and raw drafts
are taken from the underlying reasoner when it exposes them (``CallRecording``); the
runner never invents either.

Evidence re-projection: the loaded timeline carries one project id; the delta at each
T is copied with only ``project_id`` replaced by ``PROJECT_ID`` (as Arm R does per T).

Readiness is reported per scope in ``scopes`` through the domain's own
``build_semantic_readiness``; the assimilation scope (which addresses Call 1 shows)
is the caller's ``scope``, exactly as in Arm R.

What this module does not do: no reasoner construction, no semantic decision of any
kind (no comparison, ranking or filtering of evidence, addresses or claims), no
authority logic of its own (the human path is ``resolve_pending_supersessions`` and
nothing else), no direct ``submit``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final, Literal

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
from foundry.domain.events import StoredEvent
from foundry.domain.evidence import EvidenceItem
from foundry.domain.handoff import SemanticReadiness, build_semantic_readiness, locus_in_scope
from foundry.domain.semantic_judgment import AssertClaimProposal, SupersedeProposal
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState
from foundry.experiments.longitudinal.arm_r import (
    RecordedCalls,
    RequestRecorder,
    ledger_admissions,
    ledger_judgment_ids,
    recorded_calls,
)
from foundry.experiments.longitudinal.authority import (
    AuthorizationBudget,
    AuthorizationCounter,
    AuthorizationHalted,
    AuthorizationRecord,
    Authorizer,
    record_architect_authority,
    resolve_pending_supersessions,
)
from foundry.experiments.longitudinal.derivations import (
    RootDesignation,
    Track,
    attach_preregistered_chains,
    designate_root,
)
from foundry.experiments.longitudinal.timeline import VersionedEvidence, persistent_delta
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = [
    "MAX_F_CALLS",
    "PROJECT_ID",
    "SYSTEM_INSTRUCTION_SHA256",
    "TRACK_C_DESIGNATION_T",
    "ArmFResult",
    "StepRecord",
    "run_arm_f",
]

MAX_F_CALLS: Final[int] = 8
"""Four T × two calls. Never exceeded; checked before each T and before each call."""

PROJECT_ID: Final[str] = "PROJ-9P-F"
"""The one project id of the one persistent ledger."""

TRACK_C_DESIGNATION_T: Final[int] = 3
"""Track C is introduced at T3 (spec §29); its root is designated after T3, before T4."""

T2_ARTIFACT_REFS_T: Final[int] = 2
"""The timeline step whose artifact refs guard chain attachment (Task 11)."""

_TRACKED: Final[frozenset[str]] = frozenset({"A", "B", "C"})
"""Tracks a pending SUPERSEDE may be offered under. The control identifies no track."""

type StepStatus = Literal["COMPLETED", "FAILED", "NOT_RUN"]
type AddressSelector = Callable[[IntentState], str]
"""The architect's selection of an existing address id, read from state (Task 11)."""


class _Selectors(FrozenModel):
    """The four root selectors, bundled so they travel together."""

    track_a: AddressSelector
    track_b: AddressSelector
    track_c: AddressSelector
    control: AddressSelector


class StepRecord(FrozenModel):
    """One T of Arm F: what was shown, what was recorded, what the ledger says now."""

    t: int
    status: StepStatus
    evidence_shown: tuple[str, ...]
    """Evidence ids in this T's two requests, request order, de-duplicated (delta first)."""
    addresses_shown: tuple[str, ...]
    """Address ids in this T's two requests, request order, de-duplicated."""
    claims_shown: tuple[str, ...]
    """Claim ids in this T's Call 2 request, request order."""
    allowed_kinds_per_call: tuple[tuple[str, ...], ...]
    """Sorted ``JudgmentKind`` values of each request the reasoner received in this T."""
    draft_outputs: tuple[SemanticDraftPayload, ...]
    """Raw draft payloads received during this T, if the reasoner exposes them."""
    judgment_ids: tuple[str, ...]
    """Every judgment appended to the ledger during this T, in submission order."""
    admissions: tuple[AdmissionDecision, ...]
    """Every admission appended to the ledger during this T, in submission order."""
    authorizations: tuple[AuthorizationRecord, ...]
    """What was presented to the human and answered (or withheld) during this T."""
    state_snapshot_revision: int
    """``state.revision`` after this T; equals the ledger length at that point."""
    view: CurrentSemanticView
    readiness_by_scope: dict[str, SemanticReadiness]
    receipts: tuple[SemanticReasoningReceipt, ...]
    """Receipts of the calls made during this T, if the reasoner exposes them."""
    error: str | None = None


class ArmFResult(FrozenModel):
    steps: tuple[StepRecord, ...]
    calls_made: int
    """Requests actually handed to the reasoner over the whole run."""
    ledger: tuple[StoredEvent, ...]
    """The one persistent ledger, sequence from 1."""
    final_state_revision: int
    designations: tuple[RootDesignation, ...]
    """Root designations in the order recorded (A, B, CONTROL after T1; C after T3)."""


# --- request recording ---------------------------------------------------------------


def _unique(ids: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))


def _shown(
    requests: tuple[ReasoningRequest, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    evidence = [item.evidence_id for request in requests for item in request.evidence]
    addresses = [a.address_id for request in requests for a in request.known_addresses]
    claims = [c.claim_id for request in requests for c in request.known_claims]
    return _unique(evidence), _unique(addresses), _unique(claims)


# --- ledger reading ---------------------------------------------------------------


def _readiness_by_scope(
    state: IntentState, view: CurrentSemanticView, scopes: tuple[str, ...]
) -> dict[str, SemanticReadiness]:
    return {
        scope: build_semantic_readiness(
            state, view, scope, tuple(locus for locus in view.loci if locus_in_scope(locus, scope))
        )
        for scope in scopes
    }


# --- the delta ---------------------------------------------------------------------------


def _reprojected_delta(timeline: tuple[VersionedEvidence, ...], t: int) -> tuple[EvidenceItem, ...]:
    """``persistent_delta(timeline, t)`` re-addressed to ``PROJECT_ID``; nothing else.

    The loaded timeline carries one project id; this ledger has its own. Evidence id,
    content, content hash, scope, observation time and lineage are untouched.
    """
    return tuple(
        item.model_copy(update={"project_id": PROJECT_ID}) for item in persistent_delta(timeline, t)
    )


def _guard_delta_only(
    delta: tuple[EvidenceItem, ...],
    *,
    t: int,
    timeline: tuple[VersionedEvidence, ...],
    state: IntentState,
) -> None:
    """Refuse an empty delta or one carrying evidence the persistent arm already saw.

    Structural, deterministic data check (spec §32 failure mode 13): every item's
    ``(artifact_ref, content_sha256)`` must be absent from every earlier T of the
    timeline and from the ledger. Raises ``ValueError`` before any call is made.
    """
    if not delta:
        raise ValueError(f"T{t}: empty delta; the persistent arm has nothing to assimilate")
    earlier = {(v.artifact_ref, v.content_sha256) for v in timeline if v.t < t}
    ingested = {
        (item.artifact_ref, item.content_sha256) for item in state.semantic.evidence.values()
    }
    for item in delta:
        key = (item.artifact_ref, item.content_sha256)
        if key in earlier or key in ingested:
            raise ValueError(
                f"T{t}: delta item {item.evidence_id} ({item.artifact_ref}) is unchanged "
                "evidence already shown to the persistent arm; the run aborts before the call"
            )


# --- one T -------------------------------------------------------------------------------


class _Run:
    """Mutable per-run holders shared across T's; never written to the ledger."""

    __slots__ = (
        "addresses_at_end",
        "counter",
        "designations",
        "governor",
        "recorder",
        "store",
    )

    def __init__(
        self,
        *,
        reasoner: SemanticReasoner,
        policy: AdmissionPolicy,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str],
    ) -> None:
        self.store = InMemoryEventStore()
        self.governor = SemanticGovernor(
            store=self.store,
            project_id=PROJECT_ID,
            policy=policy,
            clock=clock,
            id_factory=id_factory,
        )
        self.recorder = RequestRecorder(reasoner, max_calls=MAX_F_CALLS)
        self.counter = AuthorizationCounter()
        self.designations: list[RootDesignation] = []
        self.addresses_at_end: dict[int, frozenset[str]] = {}

    def ledger(self) -> tuple[StoredEvent, ...]:
        return tuple(self.store.load(PROJECT_ID))

    def snapshot_addresses(self, t: int) -> None:
        """Pin the address ids present in the view at the end of ``t``."""
        view = self.governor.view()
        self.addresses_at_end[t] = frozenset(
            address_id for locus in view.loci for address_id in locus.address_ids
        )

    def require_undesignated(self, track: Track, address_id: str) -> None:
        """R12-e: designated addresses are pairwise distinct across A, B, C and the control.

        Raises ``ValueError`` naming both tracks if ``address_id`` is already designated.
        """
        for earlier in self.designations:
            if earlier.address_id == address_id:
                raise ValueError(
                    f"address {address_id} selected for track {track} is already designated "
                    f"for track {earlier.track}; designated addresses must be pairwise distinct"
                )

    def designate(
        self, track: Track, address_id: str, clock: Callable[[], datetime]
    ) -> RootDesignation:
        """Record one root selection from current state; kept even if a later one fails.

        Refuses a duplicate address (``require_undesignated``); nothing is recorded for it.
        """
        self.require_undesignated(track, address_id)
        designation = designate_root(self.governor, track=track, address_id=address_id, clock=clock)
        self.designations.append(designation)
        return designation

    def track_of(self, judgment_id: str) -> str | None:
        """Structural track identity of a pending SUPERSEDE, from state and designations."""
        return _structural_track(self.governor.state(), tuple(self.designations), judgment_id)


def _record(
    run: _Run,
    *,
    t: int,
    status: StepStatus,
    request_from: int,
    recorded: RecordedCalls,
    ledger_from: int,
    authorizations: tuple[AuthorizationRecord, ...],
    scopes: tuple[str, ...],
    error: str | None,
) -> StepRecord:
    state = run.governor.state()
    view = derive_view(state.semantic)
    appended = run.ledger()[ledger_from:]
    evidence, addresses, claims = _shown(run.recorder.since(request_from))
    return StepRecord(
        t=t,
        status=status,
        evidence_shown=evidence,
        addresses_shown=addresses,
        claims_shown=claims,
        allowed_kinds_per_call=run.recorder.allowed_kinds_since(request_from),
        draft_outputs=recorded.drafts,
        judgment_ids=ledger_judgment_ids(appended),
        admissions=ledger_admissions(appended),
        authorizations=authorizations,
        state_snapshot_revision=state.revision,
        view=view,
        readiness_by_scope=_readiness_by_scope(state, view, scopes),
        receipts=recorded.receipts,
        error=error,
    )


def _structural_track(
    state: IntentState, designations: tuple[RootDesignation, ...], judgment_id: str
) -> str | None:
    """Track X iff the pending SUPERSEDE targets an ASSERT_CLAIM at track X's address.

    Pure lookup over ids already in the ledger: no text is compared, nothing is
    inferred. Anything that is not a SUPERSEDE of a known ASSERT_CLAIM at a designated
    tracked address is ``None`` (untracked).
    """
    judgments = state.semantic.judgments
    pending = judgments.get(judgment_id)
    if pending is None or not isinstance(pending.proposal, SupersedeProposal):
        return None
    target = judgments.get(pending.proposal.target_judgment_id)
    if target is None or not isinstance(target.proposal, AssertClaimProposal):
        return None
    address_id = target.proposal.address_id
    for designation in designations:
        if designation.track in _TRACKED and designation.address_id == address_id:
            return designation.track
    return None


def _after_t1(
    run: _Run,
    *,
    timeline: tuple[VersionedEvidence, ...],
    clock: Callable[[], datetime],
    selectors: _Selectors,
) -> None:
    """T1 epilogue: designate A, B and the control from T1 state, then attach the chains."""
    state = run.governor.state()
    track_a = run.designate("A", selectors.track_a(state), clock)
    run.designate("B", selectors.track_b(state), clock)
    control = run.designate("CONTROL", selectors.control(state), clock)
    t2_artifact_refs = frozenset(v.artifact_ref for v in timeline if v.t == T2_ARTIFACT_REFS_T)
    attach_preregistered_chains(
        run.governor, track_a=track_a, control=control, t2_artifact_refs=t2_artifact_refs
    )


def _after_t3(run: _Run, *, clock: Callable[[], datetime], selectors: _Selectors) -> None:
    """T3 epilogue: designate the Track C root from T3 state. No chain is attached.

    Raises ``ValueError`` (R12-e) if the selected address is already designated for
    another track (checked first, naming both), or was already present in the view at
    the end of the previous T: C does not exist until T3 (spec §29 E1/E8).
    """
    previous_t = TRACK_C_DESIGNATION_T - 1
    address_id = selectors.track_c(run.governor.state())
    run.require_undesignated("C", address_id)
    if address_id in run.addresses_at_end.get(previous_t, frozenset()):
        raise ValueError(
            f"address {address_id} selected for track C was already present at the end of "
            f"T{previous_t}; the Track C root must be new at T{TRACK_C_DESIGNATION_T}"
        )
    run.designate("C", address_id, clock)


def _run_step(
    run: _Run,
    *,
    t: int,
    first_t: int,
    timeline: tuple[VersionedEvidence, ...],
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    authorizer: Authorizer,
    budget: AuthorizationBudget,
    selectors: _Selectors,
    scope: str,
    scopes: tuple[str, ...],
) -> StepRecord:
    """One T against the persistent ledger; any exception becomes this T's ``FAILED``."""
    ledger_from = len(run.ledger())
    request_from = len(run.recorder.requests)
    before = recorded_calls(run.recorder.inner)
    authorizations: tuple[AuthorizationRecord, ...] = ()
    error: str | None = None
    try:
        delta = _reprojected_delta(timeline, t)
        _guard_delta_only(delta, t=t, timeline=timeline, state=run.governor.state())
        outcome = assimilate_delta(
            governor=run.governor, reasoner=run.recorder, delta=delta, scope=scope
        )
        if t == first_t:
            _after_t1(run, timeline=timeline, clock=clock, selectors=selectors)
        else:
            authorizations = resolve_pending_supersessions(
                governor=run.governor,
                pending_ids=outcome.pending_supersede_judgment_ids,
                authorizer=authorizer,
                track_of=run.track_of,
                budget=budget,
                counter=run.counter,
                clock=clock,
                id_factory=id_factory,
            )
        if t == TRACK_C_DESIGNATION_T:
            _after_t3(run, clock=clock, selectors=selectors)
    except AuthorizationHalted as exc:
        authorizations = exc.records
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - recorded as this T's failure, never re-attempted
        error = f"{type(exc).__name__}: {exc}"
    run.snapshot_addresses(t)
    return _record(
        run,
        t=t,
        status="COMPLETED" if error is None else "FAILED",
        request_from=request_from,
        recorded=recorded_calls(run.recorder.inner).since(before),
        ledger_from=ledger_from,
        authorizations=authorizations,
        scopes=scopes,
        error=error,
    )


def _not_run(run: _Run, *, t: int, scopes: tuple[str, ...], reason: str) -> StepRecord:
    return _record(
        run,
        t=t,
        status="NOT_RUN",
        request_from=len(run.recorder.requests),
        recorded=RecordedCalls(),
        ledger_from=len(run.ledger()),
        authorizations=(),
        scopes=scopes,
        error=reason,
    )


# --- the run -------------------------------------------------------------------------------


def run_arm_f(
    *,
    reasoner: SemanticReasoner,
    timeline: tuple[VersionedEvidence, ...],
    policy: AdmissionPolicy,
    clock: Callable[[], datetime],
    id_factory: Callable[[str], str],
    authorizer: Authorizer,
    designate_track_a: AddressSelector,
    designate_track_b: AddressSelector,
    designate_track_c: AddressSelector,
    designate_control: AddressSelector,
    scope: str,
    scopes: tuple[str, ...] = ("intent-engine", "constitution"),
) -> ArmFResult:
    """Run Arm F over every T in ``timeline`` against one persistent ledger.

    ``scope`` is the assimilation scope handed to ``assimilate_delta`` (which active
    addresses Call 1 shows), as in Arm R; ``scopes`` are the scopes whose readiness is
    reported per step. The four selectors each return an existing address id from the
    state they are given: A, B and the control after T1; C after T3. T0
    (``record_architect_authority``) runs before the loop and makes no call; an
    exception there propagates, since no ledger worth preserving exists yet. After a
    ``FAILED`` T every later T is ``NOT_RUN``; a T that would push the run past
    ``MAX_F_CALLS`` is ``NOT_RUN`` and never calls.
    """
    run = _Run(reasoner=reasoner, policy=policy, clock=clock, id_factory=id_factory)
    selectors = _Selectors(
        track_a=designate_track_a,
        track_b=designate_track_b,
        track_c=designate_track_c,
        control=designate_control,
    )
    budget = AuthorizationBudget()
    record_architect_authority(run.governor, clock=clock, id_factory=id_factory)

    ts = sorted({version.t for version in timeline})
    first_t = ts[0] if ts else 0
    steps: list[StepRecord] = []
    failed_at: int | None = None
    for t in ts:
        if failed_at is not None:
            steps.append(_not_run(run, t=t, scopes=scopes, reason=f"stopped: T{failed_at} failed"))
            continue
        calls_made = len(run.recorder.requests)
        if calls_made + CALLS_PER_DELTA > MAX_F_CALLS:
            steps.append(
                _not_run(
                    run,
                    t=t,
                    scopes=scopes,
                    reason=(
                        f"budget: {calls_made} calls made, T{t} needs {CALLS_PER_DELTA}, "
                        f"MAX_F_CALLS is {MAX_F_CALLS}"
                    ),
                )
            )
            continue
        step = _run_step(
            run,
            t=t,
            first_t=first_t,
            timeline=timeline,
            clock=clock,
            id_factory=id_factory,
            authorizer=authorizer,
            budget=budget,
            selectors=selectors,
            scope=scope,
            scopes=scopes,
        )
        steps.append(step)
        if step.status == "FAILED":
            failed_at = t
    ledger = run.ledger()
    return ArmFResult(
        steps=tuple(steps),
        calls_made=len(run.recorder.requests),
        ledger=ledger,
        final_state_revision=run.governor.state().revision,
        designations=tuple(run.designations),
    )
