"""Replay and deterministic structural scoring (9P Task 17; spec §29, §30, §31).

Everything here is computed from the two arm results — the persistent ledger, the
per-T records, the request log, the receipts, the authorization log — and from nothing
else. Zero model calls; no reasoner is constructed or invoked; no file is read. No
function compares descriptor text: identity is only ever read as ids that are already
in the ledger (Global Constraint 1; spec §30 "never scored by string equality").

Three surfaces:

* ``replay_matches`` — 9O's replay check, reused in shape: the recorded events are
  serialised, parsed back and reduced through a fresh store; the replayed
  ``IntentState`` and its derived view are compared with the live ones.
* ``structural_metrics`` — the deterministic metric set (spec §30): historical
  preservation, supersession-chain validity, support records, pending governance,
  stale descendants (E6, deterministic part), scope isolation (E7), requested kinds
  (E10, deterministic part), replay (E11), declined governance (E12, conditional),
  designation ordering (plan Task 11: roots designated before the evidence that could
  bias them was ingested), call counts, tokens and cost per T and cumulative (spec
  §31), the persistent arm's unchanged-raw-evidence re-read count taken from its
  actual requests, and Arm R's per-T address counts.
* ``deterministic_verdicts`` — exactly the expectations the sealed manifest marks
  ``deterministic`` (E6, E7, E10, E11, E12). Architect-adjudicated expectations are
  never produced here. E12 is ``NOT_APPLICABLE`` iff no supersession was declined.

Two facts are reported rather than decided. If the Track A root was never superseded
(for instance because the human declined), ``StaleDescendants.holds`` and
``ScopeIsolation.holds`` are ``None``: the metric says the precondition never arose.
The verdict layer must still record E6/E7 — they are unconditional (spec §29) — and it
records ``FAIL`` with that reason in the note, never ``PASS``. And E10 is one id with
two halves: this module fills the request-log half; the duplicate-address half is the
architect's, and the verdict note says so.

Re-read accounting (spec §19, §31, §32 failure mode 13): at T2-T4 the persistent arm
re-reads ZERO unchanged evidence. The count is taken from the ACTUAL requests the
recorder captured (``StepRecord.evidence_shown`` — the union of ``EvidenceItem`` ids in
that T's two real requests), not from the ledger alone. For T>1 the only raw evidence
allowed in either call is that T's persistent delta (the ``EVIDENCE_INGESTED`` events
in that T's ledger slice); every evidence id actually shown that is not in that T's
delta is an UNCHANGED_RAW_EVIDENCE_REREAD and is counted, as is a delta item that
re-ingests an already-ingested ``(artifact_ref, content_sha256)`` version. Address
descriptors, claims, a claim's ``evidence_ids`` references and a delta item's
``supersedes_evidence_id`` reference are not evidence content and are never counted.
Nothing sent twice is reported "separately": there is one honest count and the real
run's invariant is that it equals 0.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from pydantic import Field

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.domain.common import FrozenModel
from foundry.domain.events import (
    EventType,
    EvidencePayload,
    SemanticJudgmentPayload,
    StoredEvent,
    parse_event,
)
from foundry.domain.handoff import judgment_address_ids
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    JudgmentKind,
    SemanticJudgment,
)
from foundry.domain.semantic_view import active_judgment_ids, derive_view
from foundry.domain.state import IntentState
from foundry.experiments.intent_v2_dogfood import ReplayResult
from foundry.experiments.longitudinal.arm_f import ArmFResult, StepRecord
from foundry.experiments.longitudinal.arm_r import ArmRStep
from foundry.experiments.longitudinal.authority import AuthorizationDecision
from foundry.experiments.longitudinal.derivations import CONTROL_CHAIN, TRACK_A_CHAIN
from foundry.experiments.longitudinal.expectations import (
    LOCKED_CEILINGS,
    ExpectationVerdict,
    Verdict,
)

__all__ = [
    "ArmEconomics",
    "CallCounts",
    "DeclinedGovernance",
    "DesignationOrdering",
    "Economics",
    "HistoricalPreservation",
    "PendingGovernance",
    "ReplayCheck",
    "ReplayResult",
    "RequestedKinds",
    "ScopeIsolation",
    "ScoringManifest",
    "StaleDescendants",
    "StepEconomics",
    "StructuralMetrics",
    "SupersessionChain",
    "SupportRecords",
    "deterministic_verdicts",
    "replay_matches",
    "structural_metrics",
]

_FORBIDDEN_KINDS: Final[frozenset[str]] = frozenset(
    {JudgmentKind.EQUIVALENT.value, JudgmentKind.DISTINCT.value}
)
"""Never requested in 9P (Global Constraint 2; spec §29 E10)."""

_NO_BEARING_SCOPE: Final[str] = "NO_BEARING_SCOPE"

_T1_DESIGNATED_TRACKS: Final[tuple[str, ...]] = ("A", "B", "CONTROL")
"""Designated from T1 state; each must precede the first ``EV-T2-`` ingest."""
_T3_DESIGNATED_TRACK: Final[str] = "C"
"""Designated from T3 state; must precede the first ``EV-T4-`` ingest."""
"""E12 marker: no recorded readiness scope bears on the declined proposal at that T."""


# --- inputs ---------------------------------------------------------------------------------


class ScoringManifest(FrozenModel):
    """The preregistered constants the scorer needs; typed, never read from disk.

    Defaults are the locked ceilings and the preregistered chains (Task 11); the
    scopes are spec §24's affected (``intent-engine``) and unaffected
    (``constitution``) scopes.
    """

    max_cost_usd: float = Field(default=float(LOCKED_CEILINGS["max_cost_usd"]), ge=0.0)
    track_a_chain: tuple[str, ...] = TRACK_A_CHAIN
    control_chain: tuple[str, ...] = CONTROL_CHAIN
    affected_scope: str = Field(default="intent-engine", min_length=1)
    unaffected_scope: str = Field(default="constitution", min_length=1)


# --- metric records -------------------------------------------------------------------------


class HistoricalPreservation(FrozenModel):
    """Every claim id in F's T1 view is still a claim of F's final state."""

    t1_claim_ids: tuple[str, ...]
    missing_claim_ids: tuple[str, ...]
    holds: bool


class SupersessionChain(FrozenModel):
    """Every ``SupersessionRecord`` targets an applied judgment from an applied one."""

    records: tuple[tuple[str, str], ...]
    """``(target_judgment_id, superseding_judgment_id)`` per record, ledger order."""
    invalid: tuple[str, ...]
    """Superseding judgment ids of records that fail the rule."""
    record_count: int
    holds: bool


class SupportRecords(FrozenModel):
    """``ClaimSupportRecord``s survive replay and never mutate the claim (spec §12)."""

    records: tuple[tuple[str, str, tuple[str, ...]], ...]
    """``(judgment_id, claim_id, evidence_ids)`` per record, ledger order."""
    offenders: tuple[str, ...]
    record_count: int
    holds: bool


class PendingGovernance(FrozenModel):
    """Unresolved governance at the end of the run (spec §30), from the final view."""

    pending_judgment_ids: tuple[str, ...]
    satisfied_judgment_ids: tuple[str, ...]
    satisfied_by: dict[str, str]
    require_second_lens_count: int
    require_human_count: int
    rejected_count: int


class StaleDescendants(FrozenModel):
    """E6, deterministic part: the blast radius after the Track A root is superseded."""

    a_root_judgment_id: str | None
    a_root_superseded: bool
    superseded_at_t: int | None
    stale_ids: tuple[str, ...]
    track_a_chain_stale: bool
    control_chain_clean: bool
    holds: bool | None
    """``None`` iff the A root was never superseded: reported, not decided."""


class ScopeIsolation(FrozenModel):
    """E7: the affected scope reports the descendants; the unaffected scope is clean."""

    affected_scope: str
    unaffected_scope: str
    evaluated_at_t: int | None
    affected_stale_object_ids: tuple[str, ...]
    affected_pending_material_judgment_ids: tuple[str, ...]
    unaffected_stale_object_ids: tuple[str, ...]
    unaffected_pending_material_judgment_ids: tuple[str, ...]
    affected_reports_descendants: bool
    unaffected_clear: bool
    holds: bool | None
    """``None`` iff the A root was never superseded: reported, not decided."""


class RequestedKinds(FrozenModel):
    """E10, deterministic part: what the request log says was allowed per call."""

    f_requests: int
    r_requests: int
    forbidden_requests: tuple[str, ...]
    """``"<arm>:T<t>:call<n>:<KIND>"`` for every forbidden kind allowed in any call."""
    holds: bool


class ReplayCheck(FrozenModel):
    """E11: the F ledger reproduces the final state and every recorded step view.

    ``replay`` compares the JSON-round-trip replay with the live state the caller
    supplied to ``structural_metrics``; when none was supplied it is compared with a
    direct reduction of the same ledger, which checks serialisation fidelity and
    reducer determinism but not the live governor. The per-step recorded views and
    the recorded final revision are the checks that are independent of the ledger.
    """

    replay: ReplayResult
    step_views_reproduced: bool
    mismatched_steps: tuple[int, ...]
    final_revision_matches: bool
    """``replay(ledger).revision == f.final_state_revision``."""
    holds: bool


class DeclinedGovernance(FrozenModel):
    """E12 (conditional): a declined supersession stays visible and infers nothing."""

    declined_any: bool
    declined_judgment_ids: tuple[str, ...]
    readiness_missing: tuple[str, ...]
    """``"T<t>:<scope>:<judgment_id>"`` where a bearing scope's readiness omits the id, or
    ``"T<t>:NO_BEARING_SCOPE:<judgment_id>"`` where no recorded scope bears on it."""
    conflicts_without_reasoner_proposal: tuple[str, ...]
    """``CONFLICTS_WITH`` judgments in the ledger not authored by a semantic reasoner."""
    holds: bool | None
    """``None`` iff nothing was declined (precondition never arose)."""


class DesignationOrdering(FrozenModel):
    """Plan Task 11: root designations precede the evidence that could bias them.

    A, B and the control are designated from T1 state, so each
    ``ledger_sequence_at_designation`` must be strictly less than the sequence of the
    first ``EVIDENCE_INGESTED`` event whose evidence id starts with ``EV-T2-``; C is
    designated from T3 state, so its sequence must precede the first ``EV-T4-`` ingest.
    Ids are read by the structural ``EV-T<n>-`` prefix, the same convention
    ``derivations`` uses. A missing designation, or a missing T2/T4 ingest, is a
    failure with the reason recorded — never a vacuous pass.
    """

    designation_sequences: dict[str, int]
    """``track -> ledger_sequence_at_designation`` for every designation recorded."""
    first_t2_ingest_sequence: int | None
    first_t4_ingest_sequence: int | None
    missing_tracks: tuple[str, ...]
    designations_precede_t2_ingest: bool
    track_c_precedes_t4_ingest: bool
    holds: bool


class CallCounts(FrozenModel):
    f_per_t: dict[int, int]
    r_per_t: dict[int, int]
    f_total: int
    r_total: int
    total: int


class StepEconomics(FrozenModel):
    t: int
    calls: int
    """Receipts of this T (what the reasoner exposed; zero when it exposes nothing)."""
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ArmEconomics(FrozenModel):
    per_t: tuple[StepEconomics, ...]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    input_tokens_after_t1: int
    """Input tokens over every T > 1 — the spec §34 comparison window (T2–T4)."""


class Economics(FrozenModel):
    f: ArmEconomics
    r: ArmEconomics
    total_cost_usd: float
    max_cost_usd: float
    within_ceiling: bool


class StructuralMetrics(FrozenModel):
    historical_claims_preserved: HistoricalPreservation
    supersession_chain_valid: SupersessionChain
    support_records_replay: SupportRecords
    pending_governance: PendingGovernance
    stale_descendants_correct: StaleDescendants
    scope_isolation: ScopeIsolation
    e10_no_equivalence_requested: RequestedKinds
    e11_replay: ReplayCheck
    e12: DeclinedGovernance
    designation_ordering: DesignationOrdering
    call_counts: CallCounts
    economics: Economics
    persistent_unchanged_reread_count: int
    """UNCHANGED_RAW_EVIDENCE_REREADs at T>1, from the actual requests: every evidence id
    shown in either call that is not in that T's delta, plus every delta item that
    re-ingests an already-ingested ``(artifact_ref, content_sha256)`` version. Must be 0
    (spec §19)."""
    r_rediscovery_counts: dict[int, int]
    """Addresses present in Arm R's view at each T — every one created from scratch."""


# --- replay ---------------------------------------------------------------------------------


def _replayed_through_fresh_store(ledger: Sequence[StoredEvent], project_id: str) -> IntentState:
    """Serialise, parse back, append to a new store, reduce. The 9O replay path."""
    fresh = InMemoryEventStore()
    for stored in ledger:
        document = json.loads(json.dumps(stored.event.model_dump(mode="json")))
        fresh.append(parse_event(document), expected_sequence=fresh.current_sequence(project_id))
    return replay(project_id, fresh.load(project_id))


def replay_matches(ledger: Sequence[StoredEvent], live_state: IntentState) -> ReplayResult:
    """Replay the recorded events through a FRESH store and reducer. Zero model calls.

    Each event is serialised to JSON, parsed back and appended to a new
    ``InMemoryEventStore`` before reduction, so the check covers serialisation
    fidelity as well as reducer determinism. The project id is the live state's.
    """
    replayed = _replayed_through_fresh_store(ledger, live_state.project_id)
    state_matches = replayed == live_state
    view_matches = derive_view(replayed.semantic) == derive_view(live_state.semantic)
    return ReplayResult(
        status="REPLAY_MATCH" if state_matches and view_matches else "REPLAY_MISMATCH",
        event_count=len(ledger),
        state_matches=state_matches,
        view_matches=view_matches,
    )


# --- ledger reading -------------------------------------------------------------------------


def _project_id(f: ArmFResult) -> str:
    return f.ledger[0].event.project_id


def _state_at(f: ArmFResult, revision: int) -> IntentState:
    return replay(_project_id(f), f.ledger[:revision])


def _ledger_judgments(ledger: Sequence[StoredEvent]) -> tuple[SemanticJudgment, ...]:
    return tuple(
        stored.event.payload.judgment
        for stored in ledger
        if stored.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED
        and isinstance(stored.event.payload, SemanticJudgmentPayload)
    )


def _ingested(ledger: Sequence[StoredEvent]) -> tuple[tuple[str, str | None, str], ...]:
    """``(evidence_id, artifact_ref, content_sha256)`` of every ingest, ledger order."""
    return tuple(
        (
            stored.event.payload.evidence.evidence_id,
            stored.event.payload.evidence.artifact_ref,
            stored.event.payload.evidence.content_sha256,
        )
        for stored in ledger
        if stored.event.event_type is EventType.EVIDENCE_INGESTED
        and isinstance(stored.event.payload, EvidencePayload)
    )


def _step_slices(f: ArmFResult) -> tuple[tuple[StepRecord, int, int], ...]:
    """``(step, ledger_from, ledger_to)`` — the ledger events appended during each T."""
    slices: list[tuple[StepRecord, int, int]] = []
    previous = 0
    for step in f.steps:
        slices.append((step, previous, step.state_snapshot_revision))
        previous = step.state_snapshot_revision
    return tuple(slices)


# --- metrics --------------------------------------------------------------------------------


def _historical_preservation(f: ArmFResult, final: IntentState) -> HistoricalPreservation:
    if not f.steps:
        return HistoricalPreservation(t1_claim_ids=(), missing_claim_ids=(), holds=True)
    t1_claim_ids = tuple(claim_id for locus in f.steps[0].view.loci for claim_id in locus.claim_ids)
    missing = tuple(claim_id for claim_id in t1_claim_ids if claim_id not in final.semantic.claims)
    return HistoricalPreservation(
        t1_claim_ids=t1_claim_ids, missing_claim_ids=missing, holds=not missing
    )


def _supersession_chain(final: IntentState) -> SupersessionChain:
    semantic = final.semantic
    applied = frozenset(semantic.applied_judgment_ids)
    records = tuple(
        (record.target_judgment_id, record.superseding_judgment_id)
        for record in semantic.supersessions
    )
    invalid = tuple(
        superseding
        for target, superseding in records
        if target not in applied
        or superseding not in applied
        or target not in semantic.judgments
        or superseding not in semantic.judgments
    )
    return SupersessionChain(
        records=records, invalid=invalid, record_count=len(records), holds=not invalid
    )


def _support_records(final: IntentState, replayed: IntentState) -> SupportRecords:
    """Records survive replay; each names an applied judgment and an existing claim whose
    own ``evidence_ids`` still equal its asserting proposal's (never mutated); for a LIVE
    claim (asserting judgment active) an active record's evidence appears in the view's
    effective evidence. A record on a claim whose asserting judgment was superseded is
    legitimate — the view carries no effective evidence for a non-live claim (spec §12),
    so no inclusion is required of it."""
    semantic = final.semantic
    applied = frozenset(semantic.applied_judgment_ids)
    active = active_judgment_ids(semantic)
    effective = derive_view(semantic).effective_evidence
    records = tuple(
        (record.judgment_id, record.claim_id, record.evidence_ids)
        for record in semantic.claim_supports
    )
    offenders: list[str] = []
    if replayed.semantic.claim_supports != semantic.claim_supports:
        offenders.append("REPLAY:claim_supports differ")
    for judgment_id, claim_id, evidence_ids in records:
        claim = semantic.claims.get(claim_id)
        if judgment_id not in applied or claim is None:
            offenders.append(judgment_id)
            continue
        creator = semantic.judgments.get(claim.created_by_judgment_id)
        if (
            creator is None
            or not isinstance(creator.proposal, AssertClaimProposal)
            or creator.proposal.evidence_ids != claim.evidence_ids
        ):
            offenders.append(judgment_id)
            continue
        live = claim.created_by_judgment_id in active
        if (
            judgment_id in active
            and live
            and not set(evidence_ids) <= set(effective.get(claim_id, ()))
        ):
            offenders.append(judgment_id)
    return SupportRecords(
        records=records,
        offenders=tuple(offenders),
        record_count=len(records),
        holds=not offenders,
    )


def _pending_governance(f: ArmFResult, final: IntentState) -> PendingGovernance:
    view = f.steps[-1].view if f.steps else derive_view(final.semantic)
    routes = [admission.route for admission in final.semantic.admissions.values()]
    return PendingGovernance(
        pending_judgment_ids=view.pending_judgment_ids,
        satisfied_judgment_ids=tuple(sorted(view.satisfied_by)),
        satisfied_by=dict(view.satisfied_by),
        require_second_lens_count=routes.count(AdmissionRoute.REQUIRE_SECOND_LENS),
        require_human_count=routes.count(AdmissionRoute.REQUIRE_HUMAN),
        rejected_count=routes.count(AdmissionRoute.REJECT),
    )


def _a_root_superseded_at(f: ArmFResult, root_judgment_id: str) -> StepRecord | None:
    """The first step after which the A root judgment is no longer active, if any."""
    for step in f.steps:
        state = _state_at(f, step.state_snapshot_revision)
        semantic = state.semantic
        if (
            root_judgment_id in semantic.applied_judgment_ids
            and root_judgment_id not in active_judgment_ids(semantic)
        ):
            return step
    return None


def _stale_descendants(
    f: ArmFResult, manifest: ScoringManifest, at: StepRecord | None, root: str | None
) -> StaleDescendants:
    if root is None or at is None:
        return StaleDescendants(
            a_root_judgment_id=root,
            a_root_superseded=False,
            superseded_at_t=None,
            stale_ids=(),
            track_a_chain_stale=False,
            control_chain_clean=True,
            holds=None,
        )
    stale = frozenset(at.view.stale_ids)
    chain_stale = set(manifest.track_a_chain) <= stale
    control_clean = stale.isdisjoint(manifest.control_chain)
    return StaleDescendants(
        a_root_judgment_id=root,
        a_root_superseded=True,
        superseded_at_t=at.t,
        stale_ids=at.view.stale_ids,
        track_a_chain_stale=chain_stale,
        control_chain_clean=control_clean,
        holds=chain_stale and control_clean,
    )


def _scope_isolation(manifest: ScoringManifest, at: StepRecord | None) -> ScopeIsolation:
    affected_scope, unaffected_scope = manifest.affected_scope, manifest.unaffected_scope
    if at is None:
        return ScopeIsolation(
            affected_scope=affected_scope,
            unaffected_scope=unaffected_scope,
            evaluated_at_t=None,
            affected_stale_object_ids=(),
            affected_pending_material_judgment_ids=(),
            unaffected_stale_object_ids=(),
            unaffected_pending_material_judgment_ids=(),
            affected_reports_descendants=False,
            unaffected_clear=True,
            holds=None,
        )
    affected = at.readiness_by_scope.get(affected_scope)
    unaffected = at.readiness_by_scope.get(unaffected_scope)
    affected_stale = affected.stale_object_ids if affected is not None else ()
    affected_pending = affected.pending_material_judgment_ids if affected is not None else ()
    unaffected_stale = unaffected.stale_object_ids if unaffected is not None else ()
    unaffected_pending = unaffected.pending_material_judgment_ids if unaffected is not None else ()
    reports = affected is not None and set(manifest.track_a_chain) <= set(affected_stale)
    clear = unaffected is not None and not unaffected_stale and not unaffected_pending
    return ScopeIsolation(
        affected_scope=affected_scope,
        unaffected_scope=unaffected_scope,
        evaluated_at_t=at.t,
        affected_stale_object_ids=affected_stale,
        affected_pending_material_judgment_ids=affected_pending,
        unaffected_stale_object_ids=unaffected_stale,
        unaffected_pending_material_judgment_ids=unaffected_pending,
        affected_reports_descendants=reports,
        unaffected_clear=clear,
        holds=reports and clear,
    )


def _requested_kinds(f: ArmFResult, r: tuple[ArmRStep, ...]) -> RequestedKinds:
    forbidden: list[str] = []
    arms: tuple[tuple[str, Sequence[StepRecord | ArmRStep]], ...] = (("F", f.steps), ("R", r))
    for arm, steps in arms:
        for step in steps:
            for index, kinds in enumerate(step.allowed_kinds_per_call, start=1):
                forbidden.extend(
                    f"{arm}:T{step.t}:call{index}:{kind}"
                    for kind in kinds
                    if kind in _FORBIDDEN_KINDS
                )
    return RequestedKinds(
        f_requests=sum(len(step.allowed_kinds_per_call) for step in f.steps),
        r_requests=sum(len(step.allowed_kinds_per_call) for step in r),
        forbidden_requests=tuple(forbidden),
        holds=not forbidden,
    )


def _replay_check(f: ArmFResult, final: IntentState, live_state: IntentState | None) -> ReplayCheck:
    result = replay_matches(f.ledger, live_state if live_state is not None else final)
    mismatched = tuple(
        step.t
        for step in f.steps
        if derive_view(_state_at(f, step.state_snapshot_revision).semantic) != step.view
    )
    reproduced = not mismatched
    revision_matches = final.revision == f.final_state_revision
    return ReplayCheck(
        replay=result,
        step_views_reproduced=reproduced,
        mismatched_steps=mismatched,
        final_revision_matches=revision_matches,
        holds=result.status == "REPLAY_MATCH" and reproduced and revision_matches,
    )


def _bearing_scopes(final: IntentState, judgment_id: str, scopes: Sequence[str]) -> tuple[str, ...]:
    """The scopes (of those recorded) that the judgment's bearing addresses fall in."""
    judgment = final.semantic.judgments.get(judgment_id)
    if judgment is None:
        return ()
    addresses = [
        final.semantic.addresses[address_id]
        for address_id in judgment_address_ids(final.semantic, judgment)
        if address_id in final.semantic.addresses
    ]
    return tuple(
        scope
        for scope in scopes
        if any(address.scope == () or scope in address.scope for address in addresses)
    )


def _declined_governance(f: ArmFResult, final: IntentState) -> DeclinedGovernance:
    declined: list[tuple[int, str]] = []
    for step in f.steps:
        declined.extend(
            (step.t, record.pending_judgment_id)
            for record in step.authorizations
            if record.decision is AuthorizationDecision.DECLINE
        )
    missing: list[str] = []
    for declined_t, judgment_id in declined:
        for step in f.steps:
            if step.t < declined_t:
                continue
            scopes = _bearing_scopes(final, judgment_id, tuple(step.readiness_by_scope))
            if not scopes:
                # No recorded scope bears on the declined proposal: nothing could have
                # reported it, so the check cannot pass vacuously (mirrors E7).
                missing.append(f"T{step.t}:{_NO_BEARING_SCOPE}:{judgment_id}")
                continue
            missing.extend(
                f"T{step.t}:{scope}:{judgment_id}"
                for scope in scopes
                if judgment_id not in step.readiness_by_scope[scope].pending_material_judgment_ids
            )
    conflicts = tuple(
        judgment.judgment_id
        for judgment in _ledger_judgments(f.ledger)
        if judgment.kind is JudgmentKind.CONFLICTS_WITH and judgment.reasoner.is_human
    )
    declined_any = bool(declined)
    return DeclinedGovernance(
        declined_any=declined_any,
        declined_judgment_ids=tuple(judgment_id for _, judgment_id in declined),
        readiness_missing=tuple(missing),
        conflicts_without_reasoner_proposal=conflicts,
        holds=(not missing and not conflicts) if declined_any else None,
    )


def _first_ingest_sequence(ledger: Sequence[StoredEvent], prefix: str) -> int | None:
    sequences = [
        stored.sequence
        for stored in ledger
        if stored.event.event_type is EventType.EVIDENCE_INGESTED
        and isinstance(stored.event.payload, EvidencePayload)
        and stored.event.payload.evidence.evidence_id.startswith(prefix)
    ]
    return min(sequences) if sequences else None


def _precedes(sequence: int | None, boundary: int | None) -> bool:
    return sequence is not None and boundary is not None and sequence < boundary


def _designation_ordering(f: ArmFResult) -> DesignationOrdering:
    sequences: dict[str, int] = {d.track: d.ledger_sequence_at_designation for d in f.designations}
    first_t2 = _first_ingest_sequence(f.ledger, "EV-T2-")
    first_t4 = _first_ingest_sequence(f.ledger, "EV-T4-")
    missing = tuple(
        track for track in (*_T1_DESIGNATED_TRACKS, _T3_DESIGNATED_TRACK) if track not in sequences
    )
    precede_t2 = all(_precedes(sequences.get(track), first_t2) for track in _T1_DESIGNATED_TRACKS)
    c_precedes_t4 = _precedes(sequences.get(_T3_DESIGNATED_TRACK), first_t4)
    return DesignationOrdering(
        designation_sequences=sequences,
        first_t2_ingest_sequence=first_t2,
        first_t4_ingest_sequence=first_t4,
        missing_tracks=missing,
        designations_precede_t2_ingest=precede_t2,
        track_c_precedes_t4_ingest=c_precedes_t4,
        holds=not missing and precede_t2 and c_precedes_t4,
    )


def _call_counts(f: ArmFResult, r: tuple[ArmRStep, ...]) -> CallCounts:
    """Per-T counts are the request log of each step (what the reasoner received).

    ``f_total`` is ``ArmFResult.calls_made`` — the run-level count the F recorder kept
    across its single ledger. Arm R has no run-level result object (its output is the
    tuple of per-T steps), so ``r_total`` can only be the sum of its per-T logs. Both
    arms' recorders log every forwarded request, so the two derivations agree whenever
    the records are intact.
    """
    f_per_t = {step.t: len(step.allowed_kinds_per_call) for step in f.steps}
    r_per_t = {step.t: len(step.allowed_kinds_per_call) for step in r}
    r_total = sum(r_per_t.values())
    return CallCounts(
        f_per_t=f_per_t,
        r_per_t=r_per_t,
        f_total=f.calls_made,
        r_total=r_total,
        total=f.calls_made + r_total,
    )


def _arm_economics(steps: Sequence[StepRecord | ArmRStep]) -> ArmEconomics:
    per_t = tuple(
        StepEconomics(
            t=step.t,
            calls=len(step.receipts),
            input_tokens=sum(receipt.input_tokens for receipt in step.receipts),
            output_tokens=sum(receipt.output_tokens for receipt in step.receipts),
            cost_usd=sum(receipt.cost_usd for receipt in step.receipts),
        )
        for step in steps
    )
    return ArmEconomics(
        per_t=per_t,
        input_tokens=sum(e.input_tokens for e in per_t),
        output_tokens=sum(e.output_tokens for e in per_t),
        cost_usd=sum(e.cost_usd for e in per_t),
        input_tokens_after_t1=sum(e.input_tokens for e in per_t if e.t > 1),
    )


def _economics(f: ArmFResult, r: tuple[ArmRStep, ...], manifest: ScoringManifest) -> Economics:
    f_economics = _arm_economics(f.steps)
    r_economics = _arm_economics(r)
    total = f_economics.cost_usd + r_economics.cost_usd
    return Economics(
        f=f_economics,
        r=r_economics,
        total_cost_usd=total,
        max_cost_usd=manifest.max_cost_usd,
        within_ceiling=total <= manifest.max_cost_usd,
    )


def _unchanged_reread_count(f: ArmFResult) -> int:
    """UNCHANGED_RAW_EVIDENCE_REREADs at T>1, measured on the actual requests.

    Per T after the first: the allowed raw evidence is that T's delta (the ingests in
    that T's ledger slice). Counted: every id in ``step.evidence_shown`` — the evidence
    the recorder saw handed to the reasoner across that T's two calls — that is not in
    the delta; and every delta item whose ``(artifact_ref, content_sha256)`` version was
    already ingested at an earlier T. Ids referenced by claims or by
    ``supersedes_evidence_id`` are not evidence content and are not counted.
    """
    count = 0
    versions_before: set[tuple[str | None, str]] = set()
    first_t = f.steps[0].t if f.steps else 0
    for step, ledger_from, ledger_to in _step_slices(f):
        delta = _ingested(f.ledger[ledger_from:ledger_to])
        delta_ids = {evidence_id for evidence_id, _, _ in delta}
        if step.t > first_t:
            count += sum(
                1 for _, artifact_ref, sha in delta if (artifact_ref, sha) in versions_before
            )
            count += sum(1 for evidence_id in step.evidence_shown if evidence_id not in delta_ids)
        versions_before.update((artifact_ref, sha) for _, artifact_ref, sha in delta)
    return count


def structural_metrics(
    f: ArmFResult,
    r: tuple[ArmRStep, ...],
    manifest: ScoringManifest,
    *,
    live_state: IntentState | None = None,
) -> StructuralMetrics:
    """The deterministic metric set over both arms. Zero model calls; ids only.

    ``live_state`` is the F governor's live ``IntentState`` when the caller has it; the
    replay is then compared against it. Without it the replay is compared against a
    direct reduction of the ledger (see ``ReplayCheck``).
    """
    project_id = _project_id(f)
    final = replay(project_id, f.ledger)
    replay_check = _replay_check(f, final, live_state)
    replayed = _replayed_through_fresh_store(f.ledger, project_id)
    a_root = next((d.judgment_id for d in f.designations if d.track == "A"), None)
    superseded_at = _a_root_superseded_at(f, a_root) if a_root is not None else None
    return StructuralMetrics(
        historical_claims_preserved=_historical_preservation(f, final),
        supersession_chain_valid=_supersession_chain(final),
        support_records_replay=_support_records(final, replayed),
        pending_governance=_pending_governance(f, final),
        stale_descendants_correct=_stale_descendants(f, manifest, superseded_at, a_root),
        scope_isolation=_scope_isolation(manifest, superseded_at),
        e10_no_equivalence_requested=_requested_kinds(f, r),
        e11_replay=replay_check,
        e12=_declined_governance(f, final),
        designation_ordering=_designation_ordering(f),
        call_counts=_call_counts(f, r),
        economics=_economics(f, r, manifest),
        persistent_unchanged_reread_count=_unchanged_reread_count(f),
        r_rediscovery_counts={
            step.t: sum(len(locus.address_ids) for locus in step.view.loci) for step in r
        },
    )


# --- verdicts -------------------------------------------------------------------------------


def _pass_or_fail(holds: bool) -> Verdict:
    return Verdict.PASS if holds else Verdict.FAIL


def _e6(metrics: StructuralMetrics) -> ExpectationVerdict:
    stale = metrics.stale_descendants_correct
    refs = tuple(
        ref for ref in (stale.a_root_judgment_id, *stale.stale_ids) if ref is not None
    ) or ("ledger:no-track-a-designation",)
    if stale.holds is None:
        return ExpectationVerdict(
            id="E6",
            verdict=Verdict.FAIL,
            adjudicator="deterministic",
            evidence_refs=refs,
            note=(
                "Track A root judgment was never superseded during the run; the "
                "unconditional expectation did not hold (no blast radius to check)."
            ),
        )
    return ExpectationVerdict(
        id="E6",
        verdict=_pass_or_fail(stale.holds),
        adjudicator="deterministic",
        evidence_refs=refs,
        note=(
            f"superseded at T{stale.superseded_at_t}; track A chain stale="
            f"{stale.track_a_chain_stale}; control chain clean={stale.control_chain_clean}"
        ),
    )


def _e7(metrics: StructuralMetrics) -> ExpectationVerdict:
    isolation = metrics.scope_isolation
    if isolation.holds is None:
        return ExpectationVerdict(
            id="E7",
            verdict=Verdict.FAIL,
            adjudicator="deterministic",
            evidence_refs=("ledger:track-a-root-never-superseded",),
            note=(
                "Track A root judgment was never superseded during the run; no stale "
                "descendants existed for the affected scope to report."
            ),
        )
    t = isolation.evaluated_at_t
    return ExpectationVerdict(
        id="E7",
        verdict=_pass_or_fail(isolation.holds),
        adjudicator="deterministic",
        evidence_refs=(
            f"T{t}:{isolation.affected_scope}",
            f"T{t}:{isolation.unaffected_scope}",
            *isolation.affected_stale_object_ids,
        ),
        note=(
            f"affected reports descendants={isolation.affected_reports_descendants}; "
            f"unaffected clear={isolation.unaffected_clear}"
        ),
    )


def _e10(metrics: StructuralMetrics) -> ExpectationVerdict:
    kinds = metrics.e10_no_equivalence_requested
    return ExpectationVerdict(
        id="E10",
        verdict=_pass_or_fail(kinds.holds),
        adjudicator="deterministic",
        evidence_refs=kinds.forbidden_requests
        or (f"F:requests={kinds.f_requests}", f"R:requests={kinds.r_requests}"),
        note=(
            "Deterministic half only (request log: no EQUIVALENT/DISTINCT allowed in any "
            "call). The duplicate-address count for tracked loci is architect-adjudicated "
            "and is not decided here."
        ),
    )


def _e11(metrics: StructuralMetrics) -> ExpectationVerdict:
    check = metrics.e11_replay
    return ExpectationVerdict(
        id="E11",
        verdict=_pass_or_fail(check.holds),
        adjudicator="deterministic",
        evidence_refs=(
            f"ledger:events={check.replay.event_count}",
            f"replay:{check.replay.status}",
            *(f"T{t}:view-mismatch" for t in check.mismatched_steps),
        ),
        note=(
            f"state_matches={check.replay.state_matches}; "
            f"view_matches={check.replay.view_matches}; "
            f"step_views_reproduced={check.step_views_reproduced}; "
            f"final_revision_matches={check.final_revision_matches}"
        ),
    )


def _e12(metrics: StructuralMetrics) -> ExpectationVerdict:
    governance = metrics.e12
    if governance.holds is None:
        return ExpectationVerdict(
            id="E12",
            verdict=Verdict.NOT_APPLICABLE,
            adjudicator="deterministic",
            evidence_refs=("authorizations:no-decline",),
            note="No supersession was declined during the run; precondition never arose.",
        )
    return ExpectationVerdict(
        id="E12",
        verdict=_pass_or_fail(governance.holds),
        adjudicator="deterministic",
        evidence_refs=(
            *governance.declined_judgment_ids,
            *governance.readiness_missing,
            *governance.conflicts_without_reasoner_proposal,
        ),
        note=(
            f"declined={len(governance.declined_judgment_ids)}; readiness omissions="
            f"{len(governance.readiness_missing)}; conflicts without a reasoner proposal="
            f"{len(governance.conflicts_without_reasoner_proposal)}"
        ),
    )


def deterministic_verdicts(metrics: StructuralMetrics) -> tuple[ExpectationVerdict, ...]:
    """E6 (deterministic part), E7, E10 (deterministic part), E11, E12.

    Only the expectations the sealed manifest marks ``deterministic`` are produced;
    architect-adjudicated ones (E1–E5, E8, E9) are never emitted here. E12 is
    ``NOT_APPLICABLE`` iff no supersession was declined.
    """
    return (_e6(metrics), _e7(metrics), _e10(metrics), _e11(metrics), _e12(metrics))
