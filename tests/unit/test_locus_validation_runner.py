"""The single-ledger runner and the two-ledger fail-fast walk (T3).

Spec §4 (a fresh project, store and governor per ledger; nothing shared but the
budget), §10 (everything after consumption is recorded, never retried), §15 (the first
operational failure stops the walk; the failing ledger keeps its cells; the unreached
ledger is ``NOT_RUN``) and §18 (exactly 8 calls: α T1 c1, c2, T2 c1, c2, then β).

No provider, no network, no key: the inner reasoner is a scripted double carrying the
locus identity whose batches inspect the REAL ``ReasoningRequest`` and mint the drafts
the locus policy prescribes, so the state the real governor reaches is meaningful. The
real adapter classes are never constructed; sockets are blocked for the module.
"""

from __future__ import annotations

import ast
import os
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any, ClassVar

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    SemanticOutputError,
    XAIProviderError,
)
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.common import Authority
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.state import IntentState
from foundry.experiments.locus_validation import runner as runner_module
from foundry.experiments.locus_validation.corpus import (
    DOCUMENTS,
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    Ledger,
    evidence_id,
)
from foundry.experiments.locus_validation.expectations import (
    CASE_IDS,
    FAILURE_TAGS,
    OUTCOMES,
)
from foundry.experiments.locus_validation.expectations import (
    __all__ as expectations_names,
)
from foundry.experiments.locus_validation.protocol import (
    DELTAS,
    MAX_FRONTIER_CALLS,
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.recording import (
    BudgetExceeded,
    ExperimentBudget,
    IdentityDrift,
    LocusRecordingReasoner,
)
from foundry.experiments.locus_validation.runner import (
    DeltaRecord,
    LedgerRecord,
    RunResult,
    RunStatus,
    run_experiment,
    run_ledger,
)
from foundry.experiments.long_horizon_bounded.runner import ReferenceSnapshotMismatch
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 15, tzinfo=UTC)
LOCUS_FINGERPRINT = ReasonerFingerprint(
    provider=PROVIDER, model=MODEL, policy_version=LOCUS_POLICY_VERSION
)
LEDGER_OF_PROJECT: dict[str, Ledger] = {project: ledger for ledger, project in PROJECT_IDS.items()}

type Drafts = tuple[SemanticJudgment, ...]
type Batch = Drafts | Callable[[ReasoningRequest], Drafts] | BaseException


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_provider_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    yield
    assert "XAI_API_KEY" not in os.environ


# --- fakes --------------------------------------------------------------------------


class LocusFake:
    """Mirrors the real locus adapter's observable identity; a scripted ``propose``
    that records every forwarded request and returns the scripted batch, calls it
    with the request, or raises it. Refuses any call beyond the script."""

    policy_version: ClassVar[str] = LOCUS_POLICY_VERSION
    system_instruction: ClassVar[str] = LOCUS_SYSTEM_INSTRUCTION
    include_comparison_context: ClassVar[bool] = True
    reasoning_effort: ClassVar[str] = REASONING_EFFORT

    def __init__(self, batches: list[Batch]) -> None:
        self._batches = batches
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return LOCUS_FINGERPRINT

    def propose(self, request: ReasoningRequest) -> Drafts:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        return batch(request) if callable(batch) else batch


class _Receipt:
    def __init__(self, cost_usd: float) -> None:
        self.cost_usd = cost_usd


class EconomicsFake(LocusFake):
    """A locus fake that, like the adapter, appends one receipt and one draft payload
    per answered call."""

    def __init__(self, batches: list[Batch], costs: list[float]) -> None:
        super().__init__(batches)
        self._costs = costs
        self._receipts: list[_Receipt] = []
        self._payloads: list[str] = []

    @property
    def receipts(self) -> tuple[_Receipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[str, ...]:
        return tuple(self._payloads)

    def propose(self, request: ReasoningRequest) -> Drafts:
        result = super().propose(request)
        self._receipts.append(_Receipt(self._costs[len(self.requests) - 1]))
        self._payloads.append(f"PAYLOAD-{len(self.requests)}")
        return result


# --- draft builders -----------------------------------------------------------------


def _judgment(
    ledger: Ledger, judgment_id: str, proposal: JudgmentProposal, cited: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT_IDS[ledger],
        proposal=proposal,
        visible_evidence_ids=(cited,),
        rationale=f"Scripted draft {judgment_id}.",
        reasoner=LOCUS_FINGERPRINT,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _candidate(ledger: Ledger, judgment_id: str, cited: str, label: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=f"CAND-{judgment_id}",
        subject=f"{label} subject",
        facet=f"{label} facet",
        scope=(SCOPES[ledger],),
        evidence_ids=(cited,),
    )


def _create(ledger: Ledger, judgment_id: str, cited: str, label: str) -> SemanticJudgment:
    proposal = CreateAddressProposal(candidate=_candidate(ledger, judgment_id, cited, label))
    return _judgment(ledger, judgment_id, proposal, cited)


def _bind(
    ledger: Ledger, judgment_id: str, address_id: str, cited: str, label: str
) -> SemanticJudgment:
    proposal = BindToAddressProposal(
        candidate=_candidate(ledger, judgment_id, cited, label), address_id=address_id
    )
    return _judgment(ledger, judgment_id, proposal, cited)


def _assert(
    ledger: Ledger, judgment_id: str, address_id: str, cited: str, predicate: str, value: str
) -> SemanticJudgment:
    proposal = AssertClaimProposal(
        address_id=address_id,
        predicate=predicate,
        value=ClaimValue(kind=ClaimValueKind.TEXT, text=value),
        evidence_ids=(cited,),
        authority=Authority.INFERRED,
    )
    return _judgment(ledger, judgment_id, proposal, cited)


def _support(ledger: Ledger, judgment_id: str, claim_id: str, cited: str) -> SemanticJudgment:
    proposal = SupportsClaimProposal(claim_id=claim_id, evidence_ids=(cited,))
    return _judgment(ledger, judgment_id, proposal, cited)


def _supersede(ledger: Ledger, judgment_id: str, target: str, cited: str) -> SemanticJudgment:
    proposal = SupersedeProposal(target_judgment_id=target, reason="Scripted supersession.")
    return _judgment(ledger, judgment_id, proposal, cited)


# --- the scripted specification: drafts derived from the real request ---------------


def _seed_create_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T1-create-{document}"


def _seed_claim_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T1-claim-{document}"


def _extra_create_id(ledger: Ledger) -> str:
    return f"J-{ledger}-T2-create-{DOCUMENTS[ledger][1]}-new"


def _seed_address(ledger: Ledger, document: str) -> str:
    return address_id_for(PROJECT_IDS[ledger], _seed_create_id(ledger, document))


def _extra_address(ledger: Ledger) -> str:
    return address_id_for(PROJECT_IDS[ledger], _extra_create_id(ledger))


def _seed_claim(ledger: Ledger, document: str) -> str:
    return claim_id_for(PROJECT_IDS[ledger], _seed_claim_id(ledger, document))


def _ledger_and_t(request: ReasoningRequest) -> tuple[Ledger, int]:
    ledger = LEDGER_OF_PROJECT[request.project_id]
    t = 1 if all(item.supersedes_evidence_id is None for item in request.evidence) else 2
    return ledger, t


def _document_of_address(ledger: Ledger, address_id: str) -> str:
    for document in DOCUMENTS[ledger]:
        if _seed_address(ledger, document) == address_id:
            return document
    raise AssertionError(f"unknown seed address {address_id}")


def _prescribed(request: ReasoningRequest) -> Drafts:
    """Per call, the drafts the locus policy prescribes for the sealed corpus, minted
    from what the request actually shows (evidence, known addresses, known claims)."""
    ledger, t = _ledger_and_t(request)
    first_call = JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds
    documents = DOCUMENTS[ledger]
    if t == 1 and first_call:
        assert request.known_addresses == ()
        return tuple(
            _create(ledger, _seed_create_id(ledger, doc), item.evidence_id, doc)
            for doc, item in zip(documents, request.evidence, strict=True)
        )
    if t == 1:
        return tuple(
            _assert(
                ledger,
                _seed_claim_id(ledger, doc),
                address.address_id,
                evidence_id(doc, 1),
                f"{doc} rule",
                f"{doc} first value",
            )
            for address in request.known_addresses
            for doc in (_document_of_address(ledger, address.address_id),)
        )
    if first_call:
        binds = tuple(
            _bind(
                ledger,
                f"J-{ledger}-T2-bind-{doc}",
                address.address_id,
                evidence_id(doc, 2),
                doc,
            )
            for address in request.known_addresses
            for doc in (_document_of_address(ledger, address.address_id),)
        )
        extra = _create(
            ledger, _extra_create_id(ledger), evidence_id(documents[1], 2), f"{documents[1]} new"
        )
        return (*binds, extra)
    d1, d2, d3, d4 = documents
    known = {address.address_id for address in request.known_addresses}
    assert known == {*(_seed_address(ledger, doc) for doc in documents), _extra_address(ledger)}
    return (
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d1}",
            _seed_address(ledger, d1),
            evidence_id(d1, 2),
            f"{d1} addition",
            f"{d1} added value",
        ),
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d2}",
            _seed_address(ledger, d2),
            evidence_id(d2, 2),
            f"{d2} addition",
            f"{d2} added value",
        ),
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d2}-new",
            _extra_address(ledger),
            evidence_id(d2, 2),
            f"{d2} new rule",
            f"{d2} new value",
        ),
        _support(
            ledger, f"J-{ledger}-T2-support-{d3}", _seed_claim(ledger, d3), evidence_id(d3, 2)
        ),
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d4}",
            _seed_address(ledger, d4),
            evidence_id(d4, 2),
            f"{d4} rule",
            f"{d4} second value",
        ),
        _supersede(
            ledger,
            f"J-{ledger}-T2-supersede-{d4}",
            _seed_claim_id(ledger, d4),
            evidence_id(d4, 2),
        ),
    )


def _script(*overrides: tuple[int, Batch]) -> list[Batch]:
    """Eight prescribed batches, with ``(index, batch)`` overrides."""
    batches: list[Batch] = [_prescribed] * MAX_FRONTIER_CALLS
    for index, batch in overrides:
        batches[index] = batch
    return batches


# --- harness ------------------------------------------------------------------------


def _clock() -> Callable[[], datetime]:
    tick = count()
    return lambda: T0.replace(minute=next(tick) % 60, hour=next(tick) // 60 % 24)


def _ids() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _run(
    fake: LocusFake, *, budget: ExperimentBudget | None = None
) -> tuple[RunResult, ExperimentBudget]:
    shared = budget if budget is not None else ExperimentBudget()
    result = run_experiment(inner=fake, budget=shared, clock=_clock(), id_factory=_ids())
    return result, shared


def _success() -> tuple[RunResult, LocusFake, ExperimentBudget]:
    fake = LocusFake(_script())
    result, budget = _run(fake)
    return result, fake, budget


def _in_scope_addresses(ledger: Ledger, state: IntentState) -> list[str]:
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    return sorted(
        address_id
        for address_id, address in semantic.addresses.items()
        if address.created_by_judgment_id in active and SCOPES[ledger] in address.scope
    )


def _live_claim_counts(state: IntentState, address_ids: list[str]) -> list[int]:
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    return [
        sum(
            1
            for claim in semantic.claims.values()
            if claim.address_id == address_id and claim.created_by_judgment_id in active
        )
        for address_id in address_ids
    ]


def _routes(delta: DeltaRecord) -> tuple[list[AdmissionRoute], list[AdmissionRoute]]:
    return (
        [d.route for d in delta.stage_decisions[0]],
        [d.route for d in delta.stage_decisions[1]],
    )


# --- the scripted success -----------------------------------------------------------


def test_scripted_success_makes_exactly_eight_calls_in_ledger_delta_call_order() -> None:
    result, fake, budget = _success()

    assert result.status is RunStatus.COMPLETED
    assert result.error is None
    assert len(fake.requests) == MAX_FRONTIER_CALLS == 8
    assert budget.frontier_calls == 8
    assert result.budget.frontier_calls == 8
    assert [request.project_id for request in fake.requests] == [PROJECT_IDS["alpha"]] * 4 + [
        PROJECT_IDS["beta"]
    ] * 4
    assert [JudgmentKind.CREATE_ADDRESS in r.allowed_judgment_kinds for r in fake.requests] == [
        True,
        False,
    ] * 4
    alpha, beta = result.ledgers
    assert (alpha.ledger, beta.ledger) == LEDGERS == ("alpha", "beta")
    for record in result.ledgers:
        assert [(r.t, r.call_number) for d in record.deltas for r in d.requests] == [
            (1, 1),
            (1, 2),
            (2, 1),
            (2, 2),
        ]


def test_both_ledgers_completed_with_two_deltas_each_bound_one_to_one() -> None:
    result, _, _ = _success()

    for record in result.ledgers:
        assert record.status == "COMPLETED"
        assert record.error is None
        assert record.project_id == PROJECT_IDS[record.ledger]
        assert record.scope == SCOPES[record.ledger]
        assert [d.t for d in record.deltas] == list(DELTAS) == [1, 2]
        for delta in record.deltas:
            assert len(delta.requests) == len(delta.reference_snapshots) == 2
            for request, snapshot in zip(delta.requests, delta.reference_snapshots, strict=True):
                assert request.t == snapshot.t == delta.t
                assert request.call_number == snapshot.call_number
                assert request.request_sha256 == snapshot.request_sha256
                assert request.known_address_ids == snapshot.known_address_ids
                assert request.known_claim_ids == snapshot.known_claim_ids
            assert delta.state_snapshot is not None
            assert delta.view_snapshot is not None
        assert record.final_state == record.deltas[-1].state_snapshot
        assert record.final_view == record.deltas[-1].view_snapshot


def test_seed_call_one_shows_no_addresses_and_revision_call_one_shows_the_four_seed_addresses() -> (
    None
):
    result, fake, _ = _success()

    for offset, record in zip((0, 4), result.ledgers, strict=True):
        ledger = record.ledger
        seed, revision = record.deltas
        assert seed.requests[0].known_address_ids == ()
        assert seed.requests[0].known_claim_ids == ()
        assert seed.state_snapshot is not None
        seed_addresses = _in_scope_addresses(ledger, seed.state_snapshot)
        assert len(seed_addresses) == 4
        assert sorted(revision.requests[0].known_address_ids) == seed_addresses
        assert sorted(revision.requests[0].known_claim_ids) == sorted(
            _seed_claim(ledger, doc) for doc in DOCUMENTS[ledger]
        )
        shown = fake.requests[offset + 2]
        assert sorted(a.address_id for a in shown.known_addresses) == seed_addresses
        assert {c.address_id for c in shown.known_claims} == set(seed_addresses)
        for claim in shown.known_claims:
            document = _document_of_address(ledger, claim.address_id)
            assert claim.evidence_ids == (evidence_id(document, 1),)


def test_revision_evidence_is_the_revision_delta_only_and_context_carries_four_transitions() -> (
    None
):
    result, fake, _ = _success()

    for offset, record in zip((0, 4), result.ledgers, strict=True):
        ledger = record.ledger
        t1_ids = tuple(evidence_id(doc, 1) for doc in DOCUMENTS[ledger])
        t2_ids = tuple(evidence_id(doc, 2) for doc in DOCUMENTS[ledger])
        seed, revision = record.deltas
        for request in seed.requests:
            assert request.citable_evidence_ids == t1_ids
            assert request.historical_comparison_evidence_ids == ()
        for request in revision.requests:
            assert request.citable_evidence_ids == t2_ids
            assert sorted(request.historical_comparison_evidence_ids) == sorted(t1_ids)
            assert request.comparison_context_chars > 0
        for shown in fake.requests[offset + 2 : offset + 4]:
            assert tuple(item.evidence_id for item in shown.evidence) == t2_ids
            transitions = shown.comparison_context.transitions
            assert len(transitions) == 4
            assert sorted(
                (x.current_evidence_id, x.predecessor_evidence_id) for x in transitions
            ) == sorted(zip(t2_ids, t1_ids, strict=True))


def test_each_ledger_runs_on_a_fresh_store_and_project() -> None:
    result, fake, _ = _success()
    alpha, beta = result.ledgers

    assert beta.deltas[0].requests[0].known_address_ids == ()
    assert fake.requests[4].known_addresses == ()
    assert alpha.final_state is not None and beta.final_state is not None
    assert alpha.final_state.project_id == PROJECT_IDS["alpha"]
    assert beta.final_state.project_id == PROJECT_IDS["beta"]
    assert not set(alpha.final_state.semantic.addresses) & set(beta.final_state.semantic.addresses)
    assert {e.event.project_id for e in alpha.ledger_events} == {PROJECT_IDS["alpha"]}
    assert {e.event.project_id for e in beta.ledger_events} == {PROJECT_IDS["beta"]}
    assert len(alpha.ledger_events) == len(beta.ledger_events) > 0


def test_scripted_success_reaches_the_prescribed_state_shape_through_the_real_governor() -> None:
    result, _, budget = _success()

    for record in result.ledgers:
        ledger = record.ledger
        seed, revision = record.deltas
        assert _routes(seed) == ([AdmissionRoute.APPLY] * 4, [AdmissionRoute.APPLY] * 4)
        assert _routes(revision)[0] == [AdmissionRoute.APPLY] * 5
        assert _routes(revision)[1] == [AdmissionRoute.APPLY] * 5 + [
            AdmissionRoute.REQUIRE_SECOND_LENS
        ]
        assert seed.pending_supersede_judgment_ids == ()
        assert revision.pending_supersede_judgment_ids == (
            f"J-{ledger}-T2-supersede-{DOCUMENTS[ledger][3]}",
        )
        assert record.final_state is not None
        addresses = [*(_seed_address(ledger, d) for d in DOCUMENTS[ledger]), _extra_address(ledger)]
        assert _in_scope_addresses(ledger, record.final_state) == sorted(addresses)
        assert _live_claim_counts(record.final_state, addresses) == [2, 2, 1, 2, 1]
        assert record.final_state.semantic.supersessions == ()
        assert record.final_view is not None
        assert record.final_view.pending_judgment_ids == revision.pending_supersede_judgment_ids
    assert budget.human_authorizations == 0
    assert result.budget.human_authorizations == 0
    assert result.budget.judge_calls == 0


def test_replay_of_each_completed_ledger_matches() -> None:
    result, _, _ = _success()

    for record in result.ledgers:
        assert record.replay is not None
        assert record.replay.status == "REPLAY_MATCH"
        assert record.replay.state_matches and record.replay.view_matches
        assert record.replay.event_count == len(record.ledger_events)


def test_receipts_and_payloads_are_sliced_per_delta_and_cost_is_accounted() -> None:
    costs = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]
    fake = EconomicsFake(_script(), costs)
    result, budget = _run(fake)

    assert result.status is RunStatus.COMPLETED
    for record in result.ledgers:
        for delta in record.deltas:
            assert len(delta.receipts) == len(delta.draft_payloads) == 2
    payloads = [p for r in result.ledgers for d in r.deltas for p in d.draft_payloads]
    assert payloads == [f"PAYLOAD-{n}" for n in range(1, 9)]
    assert budget.provider_cost_usd == Decimal("0.36")
    assert result.budget.provider_cost_usd == "0.36"


def test_progress_receives_each_ledger_record_as_it_is_produced() -> None:
    progress: list[LedgerRecord] = []
    fake = LocusFake(_script())
    result = run_experiment(
        inner=fake, budget=ExperimentBudget(), clock=_clock(), id_factory=_ids(), progress=progress
    )
    assert progress == list(result.ledgers)


# --- fail-fast ----------------------------------------------------------------------


def _not_run(record: LedgerRecord, ledger: Ledger) -> None:
    assert record.ledger == ledger
    assert record.status == "NOT_RUN"
    assert record.error is None
    assert record.project_id == PROJECT_IDS[ledger]
    assert record.scope == SCOPES[ledger]
    assert record.deltas == ()
    assert record.ledger_events == ()
    assert record.final_state is None
    assert record.final_view is None
    assert record.replay is None


def test_provider_failure_at_call_three_fails_alpha_keeps_seed_and_leaves_beta_not_run() -> None:
    fake = LocusFake(_script((2, XAIProviderError("PROVIDER_FAILURE_ALPHA"))))
    result, budget = _run(fake)

    assert result.status is RunStatus.ABORTED_PROVIDER
    assert result.error == "XAIProviderError: PROVIDER_FAILURE_ALPHA"
    assert len(fake.requests) == 3
    assert budget.frontier_calls == 3
    alpha, beta = result.ledgers
    assert alpha.status == "FAILED"
    assert alpha.error == result.error
    seed, revision = alpha.deltas
    assert seed.t == 1 and len(seed.requests) == len(seed.reference_snapshots) == 2
    assert _routes(seed) == ([AdmissionRoute.APPLY] * 4, [AdmissionRoute.APPLY] * 4)
    assert revision.t == 2
    assert revision.requests == () and revision.reference_snapshots == ()
    assert revision.stage_decisions == ((), ())
    assert revision.pending_supersede_judgment_ids == ()
    assert revision.state_snapshot is not None
    assert len(_in_scope_addresses("alpha", revision.state_snapshot)) == 4
    assert alpha.final_state == revision.state_snapshot
    assert alpha.replay is None
    assert len(alpha.ledger_events) > 0
    _not_run(beta, "beta")


def test_model_contract_failure_at_call_six_keeps_alpha_completed_and_beta_call_one() -> None:
    fake = LocusFake(_script((5, SemanticOutputError("OUTPUT_FAILURE_BETA"))))
    result, budget = _run(fake)

    assert result.status is RunStatus.ABORTED_MODEL_CONTRACT
    assert result.error == "SemanticOutputError: OUTPUT_FAILURE_BETA"
    assert len(fake.requests) == 6
    assert budget.frontier_calls == 6
    alpha, beta = result.ledgers
    assert alpha.status == "COMPLETED" and alpha.error is None
    assert len(alpha.deltas) == 2
    assert alpha.replay is not None and alpha.replay.status == "REPLAY_MATCH"
    assert beta.status == "FAILED"
    assert beta.error == result.error
    (seed,) = beta.deltas
    assert seed.t == 1
    assert [r.call_number for r in seed.requests] == [1]
    assert len(seed.reference_snapshots) == 1
    assert seed.stage_decisions == ((), ())
    assert seed.state_snapshot is not None
    # Call-1 admissions are already appended events: they survive in the ledger.
    assert len(_in_scope_addresses("beta", seed.state_snapshot)) == 4
    assert beta.final_state == seed.state_snapshot
    assert beta.replay is None


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (XAIProviderError("PROVIDER_FAILURE"), RunStatus.ABORTED_PROVIDER),
        (SemanticOutputError("OUTPUT_FAILURE"), RunStatus.ABORTED_MODEL_CONTRACT),
        (ReferenceSnapshotMismatch("SNAPSHOT_FAILURE"), RunStatus.ABORTED_MODEL_CONTRACT),
        (BudgetExceeded("FRONTIER_CEILING", "scripted"), RunStatus.ABORTED_BUDGET),
        (IdentityDrift("IDENTITY_DRIFT: scripted"), RunStatus.ABORTED_IDENTITY),
        (RuntimeError("RUNTIME_FAILURE"), RunStatus.ABORTED_RUNTIME),
        (ValueError("VALUE_FAILURE"), RunStatus.ABORTED_RUNTIME),
    ],
)
def test_status_is_classified_from_the_failing_exception_type(
    error: Exception, status: RunStatus
) -> None:
    fake = LocusFake(_script((0, error)))
    result, _ = _run(fake)

    assert result.status is status
    assert result.error == f"{type(error).__name__}: {error}"
    assert len(fake.requests) == 1
    alpha, beta = result.ledgers
    assert alpha.status == "FAILED"
    (seed,) = alpha.deltas
    assert seed.requests == ()
    assert seed.state_snapshot is not None
    assert _in_scope_addresses("alpha", seed.state_snapshot) == []
    _not_run(beta, "beta")


def test_nothing_is_retried_after_a_failure() -> None:
    fake = LocusFake(_script((3, XAIProviderError("PROVIDER_FAILURE"))))
    result, budget = _run(fake)

    assert result.status is RunStatus.ABORTED_PROVIDER
    assert len(fake.requests) == 4
    assert budget.frontier_calls == 4
    assert result.ledgers[1].status == "NOT_RUN"


def test_error_text_is_redacted() -> None:
    fake = LocusFake(_script((0, XAIProviderError("refused: api_key=SECRETVALUE0123"))))
    result, _ = _run(fake)

    assert result.error is not None
    assert "SECRETVALUE0123" not in result.error
    assert "[REDACTED]" in result.error
    assert result.ledgers[0].error == result.error


def test_a_ninth_call_is_refused_by_the_ceiling_before_forwarding() -> None:
    result, fake, budget = _success()
    assert budget.frontier_calls == MAX_FRONTIER_CALLS

    extra = LocusRecordingReasoner(fake, ledger="beta", budget=budget)
    extra.begin_delta(1)
    with pytest.raises(BudgetExceeded, match="FRONTIER_CEILING"):
        extra.propose(fake.requests[0])
    assert len(fake.requests) == 8
    assert budget.frontier_calls == 8
    assert result.budget.frontier_calls == 8


def test_a_budget_already_holding_calls_aborts_the_walk_at_the_ceiling() -> None:
    budget = ExperimentBudget()
    budget.frontier_calls = MAX_FRONTIER_CALLS - 3
    fake = LocusFake(_script())
    result, _ = _run(fake, budget=budget)

    assert result.status is RunStatus.ABORTED_BUDGET
    assert result.error is not None and result.error.startswith("BudgetExceeded: FRONTIER_CEILING")
    assert len(fake.requests) == 3
    assert budget.frontier_calls == MAX_FRONTIER_CALLS
    alpha, beta = result.ledgers
    assert alpha.status == "FAILED"
    assert [d.t for d in alpha.deltas] == [1, 2]
    assert [r.call_number for r in alpha.deltas[1].requests] == [1]
    _not_run(beta, "beta")


def test_keyboard_interrupt_is_recorded_as_a_runtime_abort_and_returned_normally() -> None:
    progress: list[LedgerRecord] = []
    fake = LocusFake(_script((2, KeyboardInterrupt())))
    budget = ExperimentBudget()

    result = run_experiment(
        inner=fake, budget=budget, clock=_clock(), id_factory=_ids(), progress=progress
    )

    assert isinstance(result, RunResult)
    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error == "INTERRUPTED: KeyboardInterrupt"
    # No call was forwarded after the interrupt: the walk stopped at call 3.
    assert len(fake.requests) == 3
    assert budget.frontier_calls == 3
    assert result.budget.frontier_calls == 3
    alpha, beta = result.ledgers
    assert alpha.status == "FAILED"
    assert alpha.error == result.error
    assert [d.t for d in alpha.deltas] == [1, 2]
    assert len(alpha.deltas[0].requests) == 2
    assert alpha.deltas[1].requests == ()
    assert alpha.deltas[1].stage_decisions == ((), ())
    assert alpha.final_state is not None
    assert alpha.replay is None
    _not_run(beta, "beta")
    assert progress == list(result.ledgers)


def test_replay_failure_degrades_the_ledger_and_aborts_the_run_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("REPLAY_BROKEN")

    monkeypatch.setattr(runner_module, "replay_matches", _broken)
    fake = LocusFake(_script())
    result, _ = _run(fake)

    assert result.status is RunStatus.ABORTED_RUNTIME
    assert result.error is not None and "REPLAY_FAILED" in result.error
    assert "RuntimeError: REPLAY_BROKEN" in result.error
    assert len(fake.requests) == 8
    for record in result.ledgers:
        assert record.status == "COMPLETED"
        assert record.replay is None
        assert record.error is not None and "REPLAY_FAILED" in record.error
        assert len(record.deltas) == 2
        assert record.final_state is not None


# --- run_ledger ---------------------------------------------------------------------


def test_run_ledger_completes_one_ledger_over_a_fresh_governor() -> None:
    fake = LocusFake(_script())
    budget = ExperimentBudget()
    wrapper = LocusRecordingReasoner(fake, ledger="beta", budget=budget)

    record = run_ledger(ledger="beta", reasoner=wrapper, clock=_clock(), id_factory=_ids())

    assert record.status == "COMPLETED"
    assert record.ledger == "beta"
    assert len(fake.requests) == 4
    assert budget.frontier_calls == 4
    assert [(r.t, r.call_number) for d in record.deltas for r in d.requests] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (2, 2),
    ]
    assert record.deltas[0].requests[0].known_address_ids == ()
    assert record.final_state is not None
    assert len(_in_scope_addresses("beta", record.final_state)) == 5
    assert record.replay is not None and record.replay.status == "REPLAY_MATCH"


def test_run_ledger_records_an_interrupt_as_a_failed_ledger() -> None:
    fake = LocusFake(_script((1, KeyboardInterrupt())))
    wrapper = LocusRecordingReasoner(fake, ledger="alpha", budget=ExperimentBudget())

    record = run_ledger(ledger="alpha", reasoner=wrapper, clock=_clock(), id_factory=_ids())

    assert record.status == "FAILED"
    assert record.error == "INTERRUPTED: KeyboardInterrupt"
    assert len(fake.requests) == 2
    (seed,) = record.deltas
    assert [r.call_number for r in seed.requests] == [1]


def test_run_ledger_refuses_a_wrapper_recorded_for_another_ledger() -> None:
    fake = LocusFake(_script())
    wrapper = LocusRecordingReasoner(fake, ledger="alpha", budget=ExperimentBudget())

    with pytest.raises(ValueError, match="ledger"):
        run_ledger(ledger="beta", reasoner=wrapper, clock=_clock(), id_factory=_ids())
    assert fake.requests == []


# --- shape --------------------------------------------------------------------------


def test_run_status_vocabulary() -> None:
    assert [status.value for status in RunStatus] == [
        "NOT_RUN",
        "ABORTED_PROVIDER",
        "ABORTED_MODEL_CONTRACT",
        "ABORTED_RUNTIME",
        "ABORTED_BUDGET",
        "ABORTED_IDENTITY",
        "COMPLETED",
    ]


def test_records_are_frozen() -> None:
    result, _, _ = _success()
    with pytest.raises(Exception):  # noqa: B017 - FrozenModel refuses assignment
        result.status = RunStatus.NOT_RUN
    with pytest.raises(Exception):  # noqa: B017
        result.ledgers[0].status = "FAILED"
    assert isinstance(result.ledgers[0].deltas[0], DeltaRecord)


# --- request-path hygiene -----------------------------------------------------------


def _runner_tree() -> ast.Module:
    return ast.parse(Path(runner_module.__file__).read_text(encoding="utf-8"))


def test_runner_never_imports_the_answer_key_or_a_grading_module() -> None:
    tree = _runner_tree()
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    package = "foundry.experiments.locus_validation."
    for name in ("expectations", "evaluation", "leakage", "integrity", "artifacts"):
        assert package + name not in mods, name
    assert package + "corpus" in mods
    assert package + "protocol" in mods
    assert package + "recording" in mods
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "RecordingReasoner" not in names
    assert "BudgetedReasoner" not in names
    assert "assimilate_delta" in names
    assert "replay_matches" in names
    assert "redact_secrets" in names


def test_runner_names_no_outcome_case_or_failure_tag_and_calls_no_selection() -> None:
    tree = _runner_tree()
    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert not identifiers & set(expectations_names)
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    forbidden = set(OUTCOMES) | set(FAILURE_TAGS) | set(CASE_IDS)
    assert not strings & forbidden
    source = Path(runner_module.__file__).read_text(encoding="utf-8")
    for word in forbidden:
        assert word not in source, word
    public: Any = runner_module.__all__
    assert set(public) == {
        "DeltaRecord",
        "LedgerRecord",
        "LedgerStatus",
        "RunResult",
        "RunStatus",
        "run_experiment",
        "run_ledger",
    }
