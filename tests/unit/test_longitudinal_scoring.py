"""Replay and deterministic structural scoring (9P Task 17; spec §29, §30, §31).

Fixtures are real ``run_arm_f`` / ``run_arm_r`` runs over a fake four-commit timeline
driven by scripted reasoners and a scripted authorizer — the same pattern as the arm
runner tests. The scorer under test never constructs a reasoner, never calls a model,
and never compares descriptor text. ZERO live calls.
"""

from __future__ import annotations

import hashlib
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

import foundry.experiments.longitudinal.scoring as scoring_module
from foundry.adapters.semantics.xai_reasoner import (
    SemanticDraftPayload,
    SemanticReasoningReceipt,
)
from foundry.application.replay import replay
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.events import EventEnvelope, EventType, SemanticJudgmentPayload, StoredEvent
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.state import IntentState
from foundry.experiments.intent_v2_dogfood import ReplayResult
from foundry.experiments.longitudinal.arm_f import PROJECT_ID, ArmFResult, run_arm_f
from foundry.experiments.longitudinal.arm_r import ArmRStep, run_arm_r
from foundry.experiments.longitudinal.authority import (
    HUMAN_FINGERPRINT,
    AuthorizationDecision,
)
from foundry.experiments.longitudinal.derivations import CONTROL_CHAIN, TRACK_A_CHAIN
from foundry.experiments.longitudinal.expectations import (
    EXPECTATIONS,
    LOCKED_CEILINGS,
    DecisionInputs,
    ExpectationVerdict,
    Verdict,
)
from foundry.experiments.longitudinal.scoring import (
    ScoringManifest,
    StructuralMetrics,
    deterministic_verdicts,
    replay_matches,
    structural_metrics,
)
from foundry.experiments.longitudinal.timeline import VersionedEvidence, load_timeline
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 11, tzinfo=UTC)
LOADED_PROJECT = "PROJ-9P"
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="9p-v1")
SCOPE = "intent-engine"

T1 = "097584a39dd76cf86510500acb548778ce00fad9"
T2 = "2539ff81f79f085c1eba42718947050c1b3ac61c"
T3 = "90246a8b986b0dcbcbae6a4f3484204f916afeb5"
T4 = "779a66ac90eceaea7eb7d4af0692ee4f167292fc"

CONSTITUTION = "FOUNDRY_CONSTITUTION.md"
SPEC = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER = "src/foundry/application/semantic_reducer.py"
IDENTITY = "src/foundry/domain/semantic_identity.py"

J_CREATE_A = "J-T1-create-A"
J_CREATE_B = "J-T1-create-B"
J_CREATE_N = "J-T1-create-N"
J_CLAIM_A = "J-T1-claim-A"
J_CLAIM_B = "J-T1-claim-B"
J_CLAIM_N = "J-T1-claim-N"
J_BIND_A = "J-T2-bind-A"
J_BIND_B = "J-T2-bind-B"
J_CLAIM_A_NEW = "J-T2-claim-A-new"
J_SUPERSEDE_A = "J-T2-supersede-A"
J_SUPPORT_B = "J-T2-support-B"
J_SUPPORT_A = "J-T2-support-A"
J_CREATE_C = "J-T3-create-C"
J_CLAIM_C = "J-T3-claim-C"
J_BIND_C = "J-T4-bind-C"
J_CLAIM_C_NEW = "J-T4-claim-C-new"

ADDR_A = address_id_for(PROJECT_ID, J_CREATE_A)
ADDR_B = address_id_for(PROJECT_ID, J_CREATE_B)
ADDR_N = address_id_for(PROJECT_ID, J_CREATE_N)
ADDR_C = address_id_for(PROJECT_ID, J_CREATE_C)
CLAIM_A = claim_id_for(PROJECT_ID, J_CLAIM_A)
CLAIM_B = claim_id_for(PROJECT_ID, J_CLAIM_B)
CLAIM_N = claim_id_for(PROJECT_ID, J_CLAIM_N)
CLAIM_A_NEW = claim_id_for(PROJECT_ID, J_CLAIM_A_NEW)

DETERMINISTIC_IDS = frozenset(e.id for e in EXPECTATIONS if e.adjudicator == "deterministic")
ARCHITECT_IDS = frozenset(e.id for e in EXPECTATIONS if e.adjudicator == "architect")

type Batch = list[SemanticJudgment] | Callable[[ReasoningRequest], list[SemanticJudgment]]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- fakes ------------------------------------------------------------------------


class FakeGit:
    def __init__(self, blobs: dict[tuple[str, str], bytes]) -> None:
        self._blobs = blobs

    def blob(self, sha: str, path: str) -> bytes:
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return self._blobs[(sha, path)]

    def blob_sha(self, sha: str, path: str) -> str:
        return hashlib.sha1(b"blob " + self.blob(sha, path)).hexdigest()


class ScriptedReasoner:
    """One scripted batch per call; records every request; refuses extra calls."""

    def __init__(self, batches: list[Batch]) -> None:
        self._batches = batches
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return MODEL

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if callable(batch):
            return tuple(batch(request))
        return tuple(batch)


class RecordingReasoner(ScriptedReasoner):
    """Also exposes receipts and raw drafts, like the adapter; tokens = evidence count."""

    def __init__(self, batches: list[Batch], *, cost_per_call: float = 0.25) -> None:
        super().__init__(batches)
        self._cost = cost_per_call
        self._receipts: list[SemanticReasoningReceipt] = []
        self._drafts: list[SemanticDraftPayload] = []

    @property
    def receipts(self) -> tuple[SemanticReasoningReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[SemanticDraftPayload, ...]:
        return tuple(self._drafts)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self._receipts.append(
            SemanticReasoningReceipt(
                invocation_id=f"INV-{len(self.requests) + 1}",
                model="grok-4.6",
                reasoning_effort="high",
                input_tokens=100 * len(request.evidence),
                output_tokens=7,
                cost_usd=self._cost,
                wall_clock_ms=1,
                draft_count=0,
            )
        )
        self._drafts.append(SemanticDraftPayload(drafts=()))
        return super().propose(request)


class ScriptedAuthorizer:
    def __init__(self, answers: list[AuthorizationDecision]) -> None:
        self._answers = answers
        self.presented: list[SemanticJudgment] = []

    def __call__(self, pending: SemanticJudgment) -> AuthorizationDecision:
        self.presented.append(pending)
        index = len(self.presented) - 1
        if index >= len(self._answers):
            raise AssertionError(f"AUTHORIZATION {index + 1} ATTEMPTED: only {index} scripted")
        return self._answers[index]


# --- builders ---------------------------------------------------------------------


def _timeline() -> tuple[VersionedEvidence, ...]:
    blobs = {
        (T1, CONSTITUTION): b"constitution v1\n",
        (T1, SPEC): b"spec v1\n",
        (T2, SPEC): b"spec v2\n",
        (T3, REDUCER): b"reducer v1\n",
        (T3, IDENTITY): b"identity v1\n",
        (T4, REDUCER): b"reducer v2\n",
        (T4, SPEC): b"spec v3\n",
    }
    return load_timeline(
        FakeGit(blobs),
        project_id=LOADED_PROJECT,
        observed_at_for=lambda t: T0 + timedelta(days=t),
    )


def _clock() -> Callable[[], datetime]:
    ticks: Iterator[int] = count()
    return lambda: T0 + timedelta(minutes=next(ticks))


def _id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _judgment(
    judgment_id: str, request: ReasoningRequest, proposal: JudgmentProposal, evidence_id: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=request.project_id,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _candidate(candidate_id: str, request: ReasoningRequest, evidence_id: str) -> SemanticCandidate:
    item = next(item for item in request.evidence if item.evidence_id == evidence_id)
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="retention",
        scope=item.scope,
        evidence_ids=(evidence_id,),
    )


def _create(judgment_id: str, request: ReasoningRequest, evidence_id: str) -> SemanticJudgment:
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id)
    return _judgment(judgment_id, request, CreateAddressProposal(candidate=candidate), evidence_id)


def _bind(
    judgment_id: str, request: ReasoningRequest, address_id: str, evidence_id: str
) -> SemanticJudgment:
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id)
    proposal = BindToAddressProposal(candidate=candidate, address_id=address_id)
    return _judgment(judgment_id, request, proposal, evidence_id)


def _claim(
    judgment_id: str, request: ReasoningRequest, address_id: str, evidence_id: str, quantity: int
) -> SemanticJudgment:
    proposal = AssertClaimProposal(
        address_id=address_id,
        predicate="retention_period",
        value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="day"),
        evidence_ids=(evidence_id,),
        authority=Authority.OBSERVED,
    )
    return _judgment(judgment_id, request, proposal, evidence_id)


def _f_script(*, support_a: bool = False) -> list[Batch]:
    """Eight batches: T1 creates A, B, N and claims; T2 binds A and B, corrects A,
    supports B (and, with ``support_a``, also supports the T1 claim at A that the same
    Call 2 proposes to supersede); T3 creates C; T4 binds C and asserts a new claim at C."""
    return [
        lambda r: [
            _create(J_CREATE_A, r, "EV-T1-02"),
            _create(J_CREATE_B, r, "EV-T1-02"),
            _create(J_CREATE_N, r, "EV-T1-01"),
        ],
        lambda r: [
            _claim(J_CLAIM_A, r, ADDR_A, "EV-T1-02", 7),
            _claim(J_CLAIM_B, r, ADDR_B, "EV-T1-02", 8),
            _claim(J_CLAIM_N, r, ADDR_N, "EV-T1-01", 1),
        ],
        lambda r: [_bind(J_BIND_A, r, ADDR_A, "EV-T2-01"), _bind(J_BIND_B, r, ADDR_B, "EV-T2-01")],
        lambda r: [
            _claim(J_CLAIM_A_NEW, r, ADDR_A, "EV-T2-01", 14),
            _judgment(
                J_SUPERSEDE_A,
                r,
                SupersedeProposal(target_judgment_id=J_CLAIM_A, reason="Corrected."),
                "EV-T2-01",
            ),
            _judgment(
                J_SUPPORT_B,
                r,
                SupportsClaimProposal(claim_id=CLAIM_B, evidence_ids=("EV-T2-01",)),
                "EV-T2-01",
            ),
            *(
                [
                    _judgment(
                        J_SUPPORT_A,
                        r,
                        SupportsClaimProposal(claim_id=CLAIM_A, evidence_ids=("EV-T2-01",)),
                        "EV-T2-01",
                    )
                ]
                if support_a
                else []
            ),
        ],
        lambda r: [_create(J_CREATE_C, r, "EV-T3-02")],
        lambda r: [_claim(J_CLAIM_C, r, ADDR_C, "EV-T3-02", 3)],
        lambda r: [_bind(J_BIND_C, r, ADDR_C, "EV-T4-01")],
        lambda r: [_claim(J_CLAIM_C_NEW, r, ADDR_C, "EV-T4-01", 4)],
    ]


def _r_script() -> list[Batch]:
    """Two batches per T: create one address from the last evidence item, assert at it."""

    def create(t: int) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
        def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
            item = request.evidence[-1]
            candidate = SemanticCandidate(
                candidate_id=f"CAND-T{t}",
                subject=f"subject T{t}",
                facet="retention",
                scope=item.scope,
                evidence_ids=(item.evidence_id,),
            )
            proposal = CreateAddressProposal(candidate=candidate)
            return [_judgment(f"J-T{t}-create", request, proposal, item.evidence_id)]

        return batch

    def assert_claim(t: int) -> Callable[[ReasoningRequest], list[SemanticJudgment]]:
        def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
            item = request.evidence[-1]
            return [
                _claim(
                    f"J-T{t}-assert",
                    request,
                    request.known_addresses[0].address_id,
                    item.evidence_id,
                    t,
                )
            ]

        return batch

    batches: list[Batch] = []
    for t in (1, 2, 3, 4):
        batches.extend((create(t), assert_claim(t)))
    return batches


def _select(address_id: str) -> Callable[[IntentState], str]:
    return lambda _state: address_id


def _run_f(
    reasoner: ScriptedReasoner | None = None,
    authorizer: ScriptedAuthorizer | None = None,
) -> ArmFResult:
    return run_arm_f(
        reasoner=reasoner or ScriptedReasoner(_f_script()),
        timeline=_timeline(),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        authorizer=authorizer or ScriptedAuthorizer([AuthorizationDecision.AGREE]),
        designate_track_a=_select(ADDR_A),
        designate_track_b=_select(ADDR_B),
        designate_track_c=_select(ADDR_C),
        designate_control=_select(ADDR_N),
        scope=SCOPE,
    )


def _run_r(reasoner: ScriptedReasoner | None = None) -> tuple[ArmRStep, ...]:
    return run_arm_r(
        reasoner=reasoner or ScriptedReasoner(_r_script()),
        timeline=_timeline(),
        policy=AdmissionPolicy(),
        clock=_clock(),
        id_factory=_id_factory(),
        scope=SCOPE,
    )


def _agreed() -> tuple[ArmFResult, tuple[ArmRStep, ...]]:
    return _run_f(), _run_r()


def _declined() -> tuple[ArmFResult, tuple[ArmRStep, ...]]:
    return _run_f(authorizer=ScriptedAuthorizer([AuthorizationDecision.DECLINE])), _run_r()


def _metrics(
    f: ArmFResult, r: tuple[ArmRStep, ...], manifest: ScoringManifest | None = None
) -> StructuralMetrics:
    return structural_metrics(f, r, manifest or ScoringManifest())


def _verdict(verdicts: tuple[ExpectationVerdict, ...], expectation_id: str) -> ExpectationVerdict:
    (verdict,) = [v for v in verdicts if v.id == expectation_id]
    return verdict


def _with_readiness(f: ArmFResult, t: int, scope: str, **update: Any) -> ArmFResult:
    """A copy of ``f`` whose step ``t`` readiness for ``scope`` is tampered with."""
    steps = list(f.steps)
    step = steps[t - 1]
    readiness = dict(step.readiness_by_scope)
    readiness[scope] = readiness[scope].model_copy(update=update)
    steps[t - 1] = step.model_copy(update={"readiness_by_scope": readiness})
    return f.model_copy(update={"steps": tuple(steps)})


# --- fixtures sanity ----------------------------------------------------------------


def test_fixtures_run_clean_with_zero_live_calls() -> None:
    f, r = _agreed()
    assert [s.status for s in f.steps] == ["COMPLETED"] * 4
    assert [s.status for s in r] == ["COMPLETED"] * 4
    assert f.calls_made == 8
    (record,) = f.steps[1].authorizations
    assert record.decision is AuthorizationDecision.AGREE


# --- replay -----------------------------------------------------------------------


def test_replay_matches_reproduces_state_and_view() -> None:
    f, _ = _agreed()
    live = replay(PROJECT_ID, f.ledger)

    result = replay_matches(f.ledger, live)

    assert isinstance(result, ReplayResult)
    assert result.status == "REPLAY_MATCH"
    assert result.event_count == len(f.ledger) == f.final_state_revision
    assert result.state_matches is True and result.view_matches is True

    # A truncated ledger against the full live state is a mismatch, reported as such.
    truncated = replay_matches(f.ledger[:-1], live)
    assert truncated.status == "REPLAY_MISMATCH"
    assert truncated.event_count == len(f.ledger) - 1
    assert truncated.state_matches is False


# --- one test per metric -------------------------------------------------------------


def test_historical_claims_preserved() -> None:
    f, r = _agreed()

    metrics = _metrics(f, r)

    preserved = metrics.historical_claims_preserved
    assert set(preserved.t1_claim_ids) == {CLAIM_A, CLAIM_B, CLAIM_N}
    assert preserved.missing_claim_ids == ()
    assert preserved.holds is True
    # The superseded T1 claim at A is still in state even though it left the view.
    final = replay(PROJECT_ID, f.ledger)
    assert CLAIM_A in final.semantic.claims
    assert CLAIM_A not in {c for locus in f.steps[-1].view.loci for c in locus.claim_ids}

    # A ledger with the T1 claim events removed loses the claim: reported, not hidden.
    pruned = tuple(
        stored
        for stored in f.ledger
        if not (
            stored.event.event_type is EventType.SEMANTIC_ADMISSION_DECIDED
            and stored.event.payload.judgment_id == J_CLAIM_N  # type: ignore[union-attr]
        )
    )
    pruned = tuple(
        stored.model_copy(update={"sequence": index}) for index, stored in enumerate(pruned, 1)
    )
    broken = _metrics(f.model_copy(update={"ledger": pruned}), r)
    assert broken.historical_claims_preserved.holds is False
    assert broken.historical_claims_preserved.missing_claim_ids == (CLAIM_N,)


def test_supersession_chain_valid() -> None:
    f, r = _agreed()

    metrics = _metrics(f, r)

    chain = metrics.supersession_chain_valid
    assert chain.record_count == 1
    (human_id,) = [
        rec.submitted_judgment_id for rec in f.steps[1].authorizations if rec.submitted_judgment_id
    ]
    assert chain.records == ((J_CLAIM_A, human_id),)
    assert chain.invalid == ()
    assert chain.holds is True

    # A declined run has no supersession record at all; the chain is trivially valid.
    declined = _metrics(*_declined())
    assert declined.supersession_chain_valid.record_count == 0
    assert declined.supersession_chain_valid.holds is True


def test_support_records_replay() -> None:
    f, r = _agreed()

    metrics = _metrics(f, r)

    support = metrics.support_records_replay
    assert support.record_count == 1
    assert support.records == ((J_SUPPORT_B, CLAIM_B, ("EV-T2-01",)),)
    assert support.offenders == ()
    assert support.holds is True
    # The claim itself was never mutated; the view derives the effective evidence.
    final = replay(PROJECT_ID, f.ledger)
    assert final.semantic.claims[CLAIM_B].evidence_ids == ("EV-T1-02",)
    assert f.steps[-1].view.effective_evidence[CLAIM_B] == ("EV-T1-02", "EV-T2-01")

    # An ACTIVE support record on a claim whose asserting judgment was superseded (the
    # AGREEd correction of A) is legitimate: the record survives replay and names
    # existing ids; the view simply has no effective evidence for a non-live claim.
    supported_a = _run_f(ScriptedReasoner(_f_script(support_a=True)))
    assert [s.status for s in supported_a.steps] == ["COMPLETED"] * 4
    view = supported_a.steps[-1].view
    assert J_SUPPORT_A in view.active_support_judgment_ids
    assert CLAIM_A not in view.effective_evidence
    support_a = _metrics(supported_a, r).support_records_replay
    assert support_a.record_count == 2
    assert {rec[0] for rec in support_a.records} == {J_SUPPORT_B, J_SUPPORT_A}
    assert support_a.offenders == ()
    assert support_a.holds is True


def test_pending_governance() -> None:
    f, r = _agreed()

    agreed = _metrics(f, r).pending_governance
    (human_id,) = [
        rec.submitted_judgment_id for rec in f.steps[1].authorizations if rec.submitted_judgment_id
    ]
    assert agreed.pending_judgment_ids == ()
    assert agreed.satisfied_judgment_ids == (J_SUPERSEDE_A,)
    assert agreed.satisfied_by == {J_SUPERSEDE_A: human_id}
    assert agreed.require_second_lens_count == 1
    assert agreed.require_human_count == 0
    assert agreed.rejected_count == 0

    declined = _metrics(*_declined()).pending_governance
    assert declined.pending_judgment_ids == (J_SUPERSEDE_A,)
    assert declined.satisfied_judgment_ids == ()
    assert declined.satisfied_by == {}


def test_stale_descendants_correct() -> None:
    f, r = _agreed()

    stale = _metrics(f, r).stale_descendants_correct

    assert stale.a_root_judgment_id == J_CLAIM_A
    assert stale.a_root_superseded is True
    assert stale.superseded_at_t == 2
    assert set(stale.stale_ids) >= set(TRACK_A_CHAIN)
    assert set(stale.stale_ids).isdisjoint(CONTROL_CHAIN)
    assert stale.track_a_chain_stale is True
    assert stale.control_chain_clean is True
    assert stale.holds is True

    # Never superseded (declined): the fact is reported and no verdict is invented.
    never = _metrics(*_declined()).stale_descendants_correct
    assert never.a_root_judgment_id == J_CLAIM_A
    assert never.a_root_superseded is False
    assert never.superseded_at_t is None
    assert never.stale_ids == ()
    assert never.holds is None

    # A manifest naming a chain the ledger never attached is reported as not stale.
    other = _metrics(f, r, ScoringManifest(track_a_chain=("artifact:nowhere",)))
    assert other.stale_descendants_correct.track_a_chain_stale is False
    assert other.stale_descendants_correct.holds is False


def test_scope_isolation() -> None:
    f, r = _agreed()

    isolation = _metrics(f, r).scope_isolation

    assert isolation.affected_scope == "intent-engine"
    assert isolation.unaffected_scope == "constitution"
    assert isolation.evaluated_at_t == 2
    assert set(isolation.affected_stale_object_ids) >= set(TRACK_A_CHAIN)
    assert isolation.unaffected_stale_object_ids == ()
    assert isolation.unaffected_pending_material_judgment_ids == ()
    assert isolation.affected_reports_descendants is True
    assert isolation.unaffected_clear is True
    assert isolation.holds is True

    # Tampered: the affected scope no longer lists the descendants -> does not hold.
    tampered = _with_readiness(f, 2, "intent-engine", stale_object_ids=())
    assert _metrics(tampered, r).scope_isolation.holds is False
    # Tampered: the unaffected scope reports a stale id -> does not hold.
    leaked = _with_readiness(f, 2, "constitution", stale_object_ids=(CONTROL_CHAIN[0],))
    assert _metrics(leaked, r).scope_isolation.unaffected_clear is False
    assert _metrics(leaked, r).scope_isolation.holds is False

    # Never superseded: nothing to isolate; reported, not invented.
    never = _metrics(*_declined()).scope_isolation
    assert never.evaluated_at_t is None
    assert never.holds is None


def test_e10_no_equivalence_requested() -> None:
    f, r = _agreed()

    e10 = _metrics(f, r).e10_no_equivalence_requested

    assert e10.f_requests == 8 and e10.r_requests == 8
    assert e10.forbidden_requests == ()
    assert e10.holds is True

    # A request log that shows EQUIVALENT was allowed is caught, wherever it occurs.
    step = f.steps[2]
    kinds = (step.allowed_kinds_per_call[0], (*step.allowed_kinds_per_call[1], "EQUIVALENT"))
    steps = list(f.steps)
    steps[2] = step.model_copy(update={"allowed_kinds_per_call": kinds})
    bad_f = f.model_copy(update={"steps": tuple(steps)})
    assert _metrics(bad_f, r).e10_no_equivalence_requested.forbidden_requests == (
        "F:T3:call2:EQUIVALENT",
    )
    assert _metrics(bad_f, r).e10_no_equivalence_requested.holds is False

    r_step = r[0].model_copy(
        update={"allowed_kinds_per_call": ((JudgmentKind.DISTINCT.value,), ())}
    )
    assert _metrics(f, (r_step, *r[1:])).e10_no_equivalence_requested.forbidden_requests == (
        "R:T1:call1:DISTINCT",
    )


def test_e11_replay() -> None:
    f, r = _agreed()

    e11 = _metrics(f, r).e11_replay

    assert e11.replay.status == "REPLAY_MATCH"
    assert e11.replay.event_count == len(f.ledger)
    assert e11.step_views_reproduced is True
    assert e11.mismatched_steps == ()
    assert e11.holds is True

    # A recorded view that the ledger cannot reproduce is a mismatch at that step.
    steps = list(f.steps)
    steps[3] = steps[3].model_copy(update={"view": steps[0].view})
    broken = _metrics(f.model_copy(update={"steps": tuple(steps)}), r).e11_replay
    assert broken.mismatched_steps == (4,)
    assert broken.step_views_reproduced is False
    assert broken.final_revision_matches is True
    assert broken.holds is False

    # A recorded final revision the ledger does not reach is its own named failure.
    drifted = _metrics(f.model_copy(update={"final_state_revision": len(f.ledger) + 1}), r)
    assert drifted.e11_replay.final_revision_matches is False
    assert drifted.e11_replay.step_views_reproduced is True
    assert drifted.e11_replay.holds is False
    note = _verdict(deterministic_verdicts(drifted), "E11").note
    assert "final_revision_matches=False" in note

    # With a caller-supplied live state, the replay is compared against it — not
    # against a second replay of the same ledger.
    live = replay(PROJECT_ID, f.ledger)
    with_live = structural_metrics(f, r, ScoringManifest(), live_state=live).e11_replay
    assert with_live.replay.status == "REPLAY_MATCH"
    assert with_live.holds is True
    stale_live = replay(PROJECT_ID, f.ledger[:-1])
    against_stale = structural_metrics(f, r, ScoringManifest(), live_state=stale_live).e11_replay
    assert against_stale.replay.status == "REPLAY_MISMATCH"
    assert against_stale.replay.state_matches is False
    assert against_stale.holds is False


def test_e12_not_applicable_when_no_decline() -> None:
    f, r = _agreed()

    metrics = _metrics(f, r)

    assert metrics.e12.declined_any is False
    assert metrics.e12.declined_judgment_ids == ()
    assert metrics.e12.holds is None
    # No CONFLICTS_WITH exists at all in this run; the informational check still runs.
    assert metrics.e12.conflicts_without_reasoner_proposal == ()

    verdicts = deterministic_verdicts(metrics)
    e12 = _verdict(verdicts, "E12")
    assert e12.verdict is Verdict.NOT_APPLICABLE
    assert e12.adjudicator == "deterministic"
    # The sealed decision-input contract accepts this pairing.
    DecisionInputs(
        verdicts=verdicts,
        f_input_tokens_t2_t4=0,
        r_input_tokens_t2_t4=1,
        f_material_errors=0,
        r_material_errors=0,
        declined_any=metrics.e12.declined_any,
    )


def test_e12_holds_when_declined_and_readiness_lists_pending() -> None:
    f, r = _declined()

    metrics = _metrics(f, r)

    assert metrics.e12.declined_any is True
    assert metrics.e12.declined_judgment_ids == (J_SUPERSEDE_A,)
    assert metrics.e12.readiness_missing == ()
    assert metrics.e12.conflicts_without_reasoner_proposal == ()
    assert metrics.e12.holds is True
    e12 = _verdict(deterministic_verdicts(metrics), "E12")
    assert e12.verdict is Verdict.PASS
    assert J_SUPERSEDE_A in e12.evidence_refs
    DecisionInputs(
        verdicts=deterministic_verdicts(metrics),
        f_input_tokens_t2_t4=0,
        r_input_tokens_t2_t4=1,
        f_material_errors=0,
        r_material_errors=0,
        declined_any=True,
    )


def test_e12_fail_when_declined_and_readiness_missing_pending_id() -> None:
    f, r = _declined()
    # Tamper a copy: at T2 the intent-engine readiness no longer lists the pending id.
    tampered = _with_readiness(f, 2, "intent-engine", pending_material_judgment_ids=())

    metrics = _metrics(tampered, r)

    assert metrics.e12.declined_any is True
    assert metrics.e12.readiness_missing == (f"T2:intent-engine:{J_SUPERSEDE_A}",)
    assert metrics.e12.holds is False
    assert _verdict(deterministic_verdicts(metrics), "E12").verdict is Verdict.FAIL


def test_e12_fail_when_no_recorded_scope_bears_on_the_declined_id() -> None:
    f, r = _declined()
    # Tamper a copy: from T2 on, the only recorded readiness scope is one the declined
    # proposal does not bear on. E12 must not pass vacuously.
    steps = list(f.steps)
    for index in (1, 2, 3):
        readiness = {"constitution": steps[index].readiness_by_scope["constitution"]}
        steps[index] = steps[index].model_copy(update={"readiness_by_scope": readiness})
    unscoped = f.model_copy(update={"steps": tuple(steps)})

    metrics = _metrics(unscoped, r)

    assert metrics.e12.declined_any is True
    assert metrics.e12.readiness_missing == tuple(
        f"T{t}:NO_BEARING_SCOPE:{J_SUPERSEDE_A}" for t in (2, 3, 4)
    )
    assert metrics.e12.holds is False
    assert _verdict(deterministic_verdicts(metrics), "E12").verdict is Verdict.FAIL


def test_e12_fail_when_a_conflict_has_no_reasoner_proposal() -> None:
    f, r = _declined()
    # Append a CONFLICTS_WITH judgment authored under the human fingerprint: a conflict
    # that no semantic reasoner proposed. The ledger is otherwise untouched.
    conflict = SemanticJudgment(
        judgment_id="J-human-conflict",
        project_id=PROJECT_ID,
        proposal=ConflictsWithProposal(claim_a=CLAIM_A, claim_b=CLAIM_A_NEW),
        visible_evidence_ids=(),
        rationale="Inferred.",
        reasoner=HUMAN_FINGERPRINT,
        invocation_id="INV-human",
        proposed_at=T0,
    )
    stored = StoredEvent(
        sequence=len(f.ledger) + 1,
        event=EventEnvelope(
            event_id="event-human-conflict",
            project_id=PROJECT_ID,
            event_type=EventType.SEMANTIC_JUDGMENT_RECORDED,
            occurred_at=T0,
            payload=SemanticJudgmentPayload(judgment=conflict),
        ),
    )
    extended = f.model_copy(update={"ledger": (*f.ledger, stored)})

    metrics = _metrics(extended, r)

    assert metrics.e12.readiness_missing == ()
    assert metrics.e12.conflicts_without_reasoner_proposal == ("J-human-conflict",)
    assert metrics.e12.holds is False
    assert _verdict(deterministic_verdicts(metrics), "E12").verdict is Verdict.FAIL


def test_call_counts() -> None:
    f, r = _agreed()

    counts = _metrics(f, r).call_counts

    assert counts.f_per_t == {1: 2, 2: 2, 3: 2, 4: 2}
    assert counts.r_per_t == {1: 2, 2: 2, 3: 2, 4: 2}
    assert counts.f_total == 8 == f.calls_made
    assert counts.r_total == 8
    assert counts.total == 16 == LOCKED_CEILINGS["max_frontier_calls"]


def test_economics_tokens_and_cost_per_t_and_cumulative() -> None:
    f = _run_f(RecordingReasoner(_f_script(), cost_per_call=0.25))
    r = _run_r(RecordingReasoner(_r_script(), cost_per_call=0.5))

    economics = _metrics(f, r, ScoringManifest(max_cost_usd=8.0)).economics

    # F per T: sums of the receipts of that T, nothing else.
    assert [e.t for e in economics.f.per_t] == [1, 2, 3, 4]
    assert [e.calls for e in economics.f.per_t] == [2, 2, 2, 2]
    f_inputs = [sum(rc.input_tokens for rc in s.receipts) for s in f.steps]
    assert all(tokens > 0 for tokens in f_inputs)
    assert [e.input_tokens for e in economics.f.per_t] == f_inputs
    assert [e.output_tokens for e in economics.f.per_t] == [14, 14, 14, 14]
    assert [e.cost_usd for e in economics.f.per_t] == [0.5, 0.5, 0.5, 0.5]
    assert economics.f.input_tokens == sum(f_inputs)
    assert economics.f.output_tokens == 56
    assert economics.f.cost_usd == pytest.approx(2.0)
    assert economics.f.input_tokens_after_t1 == sum(f_inputs[1:])
    # R per T: the corpus grows, so input grows monotonically.
    r_inputs = [e.input_tokens for e in economics.r.per_t]
    assert r_inputs == [sum(rc.input_tokens for rc in s.receipts) for s in r]
    assert r_inputs == sorted(r_inputs) and r_inputs[0] < r_inputs[-1]
    assert economics.r.cost_usd == pytest.approx(4.0)
    assert economics.r.input_tokens_after_t1 == sum(r_inputs[1:])
    assert economics.total_cost_usd == pytest.approx(6.0)
    assert economics.max_cost_usd == 8.0
    assert economics.within_ceiling is True
    assert economics.f.input_tokens < economics.r.input_tokens

    # Exactly at the ceiling is within it; any amount over is not.
    at_ceiling = _metrics(f, r, ScoringManifest(max_cost_usd=6.0)).economics
    assert at_ceiling.total_cost_usd == pytest.approx(6.0)
    assert at_ceiling.within_ceiling is True
    just_over = _metrics(f, r, ScoringManifest(max_cost_usd=5.999)).economics
    assert just_over.within_ceiling is False
    over = _metrics(f, r, ScoringManifest(max_cost_usd=5.0)).economics
    assert over.within_ceiling is False

    # A reasoner that exposes no receipts yields zero economics, never invented numbers.
    plain = _metrics(*_agreed()).economics
    assert plain.f.cost_usd == 0.0 and plain.r.input_tokens == 0
    assert all(e.calls == 0 for e in plain.f.per_t)


def _ingest_events(f: ArmFResult, prefix: str) -> list[StoredEvent]:
    return [
        stored
        for stored in f.ledger
        if stored.event.event_type is EventType.EVIDENCE_INGESTED
        and stored.event.payload.evidence.evidence_id.startswith(prefix)  # type: ignore[union-attr]
    ]


def test_persistent_unchanged_reread_count() -> None:
    f, r = _agreed()

    metrics = _metrics(f, r)

    assert metrics.persistent_unchanged_reread_count == 0
    # Call 2 legitimately re-sends the evidence cited by neighbourhood claims (spec §19,
    # §31); that is reported separately and is not a re-read of the delta.
    assert "EV-T1-02" in f.steps[1].evidence_shown
    assert metrics.neighborhood_evidence_resent_count >= 1

    # A ledger in which T3's delta re-ingests the T1 constitution (same artifact, same
    # content hash, fresh id) is a re-read of unchanged evidence: counted once.
    (original,) = _ingest_events(f, "EV-T1-01")
    t3_first = min(stored.sequence for stored in _ingest_events(f, "EV-T3-"))
    payload: Any = original.event.payload
    duplicate = original.model_copy(
        update={
            "event": original.event.model_copy(
                update={
                    "event_id": "event-dup",
                    "payload": payload.model_copy(
                        update={
                            "evidence": payload.evidence.model_copy(
                                update={"evidence_id": "EV-T3-99"}
                            )
                        }
                    ),
                }
            )
        }
    )
    ledger = list(f.ledger)
    ledger.insert(t3_first - 1, duplicate)
    renumbered = tuple(s.model_copy(update={"sequence": i}) for i, s in enumerate(ledger, 1))
    steps = list(f.steps)
    for index in (2, 3):
        steps[index] = steps[index].model_copy(
            update={"state_snapshot_revision": steps[index].state_snapshot_revision + 1}
        )
    rerun = f.model_copy(
        update={
            "steps": tuple(steps),
            "ledger": renumbered,
            "final_state_revision": f.final_state_revision + 1,
        }
    )
    assert _metrics(rerun, r).persistent_unchanged_reread_count == 1


def test_r_rediscovery_counts() -> None:
    f, r = _agreed()

    metrics = _metrics(f, r)

    # R creates one address at every T from an empty ledger; nothing is ever reused.
    assert metrics.r_rediscovery_counts == {1: 1, 2: 1, 3: 1, 4: 1}
    for step in r:
        assert sum(len(locus.address_ids) for locus in step.view.loci) == 1


# --- verdicts -------------------------------------------------------------------------


def test_deterministic_verdicts_cover_exactly_the_deterministic_set() -> None:
    f, r = _agreed()
    metrics = _metrics(f, r)

    verdicts = deterministic_verdicts(metrics)

    assert {v.id for v in verdicts} == DETERMINISTIC_IDS == {"E6", "E7", "E10", "E11", "E12"}
    assert not ({v.id for v in verdicts} & ARCHITECT_IDS)
    assert all(v.adjudicator == "deterministic" for v in verdicts)
    by_id = {v.id: v for v in verdicts}
    assert by_id["E6"].verdict is Verdict.PASS
    assert set(by_id["E6"].evidence_refs) >= {J_CLAIM_A, *TRACK_A_CHAIN}
    assert by_id["E7"].verdict is Verdict.PASS
    assert by_id["E10"].verdict is Verdict.PASS
    assert "architect" in by_id["E10"].note
    assert by_id["E11"].verdict is Verdict.PASS
    assert by_id["E12"].verdict is Verdict.NOT_APPLICABLE
    for verdict in verdicts:
        assert verdict.evidence_refs, f"{verdict.id} carries no ledger evidence"
    DecisionInputs(
        verdicts=verdicts,
        f_input_tokens_t2_t4=0,
        r_input_tokens_t2_t4=1,
        f_material_errors=0,
        r_material_errors=0,
        declined_any=False,
    )

    # A never-superseded run cannot PASS the unconditional E6/E7: FAIL, with the reason.
    declined = deterministic_verdicts(_metrics(*_declined()))
    assert _verdict(declined, "E6").verdict is Verdict.FAIL
    assert "never superseded" in _verdict(declined, "E6").note
    assert _verdict(declined, "E7").verdict is Verdict.FAIL
    assert _verdict(declined, "E12").verdict is Verdict.PASS


# --- source discipline -------------------------------------------------------------------


def test_no_lexical_identity_comparison_in_source() -> None:
    source = Path(scoring_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "subject ==",
        ".facet ==",
        ".subject",
        ".facet",
        "difflib",
        "SequenceMatcher",
        ".lower()",
        ".casefold()",
        "predicate ==",
    ):
        assert forbidden not in source, f"lexical comparison {forbidden!r} found in scoring source"
    # Zero model calls: no reasoner is constructed or invoked, no adapter is built.
    for forbidden in ("XaiSemanticReasoner", ".propose(", "assimilate_delta", "grpc", "httpx"):
        assert forbidden not in source
    assert "def replay_matches" in source
    assert "def structural_metrics" in source
    assert "def deterministic_verdicts" in source
