"""Human authorization protocol for supersession (9P Task 9; spec §17, §28; 9P-A §4–5).

The architect may only AGREE — submit the identical ``proposal_signature`` under the
human fingerprint, which routes ``APPLY`` under human authority and derives the AI
proposal ``SATISFIED_BY`` — or DECLINE. Nothing else. Every test drives the real
``SemanticGovernor`` over an ``InMemoryEventStore``; the pending ``SUPERSEDE`` is an AI
judgment submitted through the ordinary path so its admission is the reducer's own.
"""

from __future__ import annotations

import inspect
import socket
import typing
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

import pytest

import foundry.experiments.longitudinal.authority as authority_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.handoff import build_intent_decision_handoff
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, LifecycleStatus, SourceKind
from foundry.domain.events import EventType, SemanticObjectPayload
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    EquivalentProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    proposal_signature,
)
from foundry.domain.semantic_view import SemanticLocus, active_judgment_ids
from foundry.experiments.longitudinal.authority import (
    ARCHITECT_ACTOR,
    HUMAN_FINGERPRINT,
    AuthorizationBudget,
    AuthorizationCounter,
    AuthorizationDecision,
    AuthorizationHalted,
    AuthorizationRecord,
    Authorizer,
    NotOfferedReason,
    record_architect_authority,
    resolve_pending_supersessions,
)

PROJECT = "PROJ-AUTHORITY"
T0 = datetime(2026, 9, 11, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")

ADDR_A = address_id_for(PROJECT, "J-cA")
ADDR_A2 = address_id_for(PROJECT, "J-cA2")
ADDR_B = address_id_for(PROJECT, "J-cB")
ADDR_C = address_id_for(PROJECT, "J-cC")
ADDR_D = address_id_for(PROJECT, "J-cD")
CLAIM_A_OLD = claim_id_for(PROJECT, "J-clA")
CLAIM_A_NEW = claim_id_for(PROJECT, "J-clA-new")

TRACKS: dict[str, str | None] = {
    "J-supA": "A",
    "J-supA-second": "A",
    "J-supB": "B",
    "J-supC": "C",
    "J-supD": "D",
    "J-supU": None,
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any accidental socket use in this module is a test failure, not a slow test."""

    def blocked(*_: Any, **__: Any) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


# --- builders ---------------------------------------------------------------------


def _ticking_clock() -> Callable[[], datetime]:
    ticks = count()

    def clock() -> datetime:
        return T0 + timedelta(seconds=next(ticks))

    return clock


def _counter_id_factory(prefix_tag: str = "") -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix_tag}{prefix}-{next(ticks)}"


def _governor(store: InMemoryEventStore) -> SemanticGovernor:
    return SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=_ticking_clock(),
        id_factory=_counter_id_factory("EVT-"),
    )


def _evidence(evidence_id: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=f"Evidence body {evidence_id}.",
        observed_at=T0,
    )


def _candidate(candidate_id: str, scope: tuple[str, ...], evidence_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="retention",
        scope=scope,
        evidence_ids=(evidence_id,),
    )


def _judgment(
    judgment_id: str, proposal: JudgmentProposal, *, evidence_id: str = "EV-A"
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=MODEL_A,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, scope: tuple[str, ...], evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(f"CAND-{judgment_id}", scope, evidence_id)),
        evidence_id=evidence_id,
    )


def _claim(judgment_id: str, address_id: str, evidence_id: str, quantity: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="day"),
            evidence_ids=(evidence_id,),
            authority=Authority.OBSERVED,
        ),
        evidence_id=evidence_id,
    )


def _supersede(judgment_id: str, target: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupersedeProposal(target_judgment_id=target, reason="The older claim is corrected."),
    )


def _correction(governor: SemanticGovernor, scope: str, suffix: str) -> None:
    """One tracked correction: address, old claim, new claim, pending AI SUPERSEDE."""
    old_ev, new_ev = f"EV-{suffix}", f"EV-{suffix}2"
    for evidence_id in (old_ev, new_ev):
        governor.ingest(_evidence(evidence_id))
    address_id = address_id_for(PROJECT, f"J-c{suffix}")
    assert governor.submit(_create(f"J-c{suffix}", (scope,), old_ev)).route is AdmissionRoute.APPLY
    assert governor.submit(_claim(f"J-cl{suffix}", address_id, old_ev, "7")).route is (
        AdmissionRoute.APPLY
    )
    assert governor.submit(_claim(f"J-cl{suffix}-new", address_id, new_ev, "14")).route is (
        AdmissionRoute.APPLY
    )
    pending = governor.submit(_supersede(f"J-sup{suffix}", f"J-cl{suffix}"))
    assert pending.route is AdmissionRoute.REQUIRE_SECOND_LENS


def _story() -> tuple[InMemoryEventStore, SemanticGovernor]:
    """Track A only: ``J-supA`` is the one pending SUPERSEDE; authority is recorded."""
    store = InMemoryEventStore()
    governor = _governor(store)
    _correction(governor, "A", "A")
    record_architect_authority(
        governor, clock=_ticking_clock(), id_factory=_counter_id_factory("AUTH-")
    )
    assert governor.view().pending_judgment_ids == ("J-supA",)
    return store, governor


def _resolve(
    governor: SemanticGovernor,
    pending_ids: tuple[str, ...],
    authorizer: Authorizer,
    *,
    counter: AuthorizationCounter | None = None,
    track_of: Callable[[str], str | None] = TRACKS.get,
    id_factory: Callable[[str], str] | None = None,
) -> tuple[AuthorizationRecord, ...]:
    return resolve_pending_supersessions(
        governor=governor,
        pending_ids=pending_ids,
        authorizer=authorizer,
        track_of=track_of,
        budget=AuthorizationBudget(),
        counter=counter if counter is not None else AuthorizationCounter(),
        clock=_ticking_clock(),
        id_factory=id_factory if id_factory is not None else _counter_id_factory("HUM-"),
    )


def _agree(_: SemanticJudgment) -> AuthorizationDecision:
    return AuthorizationDecision.AGREE


def _decline(_: SemanticJudgment) -> AuthorizationDecision:
    return AuthorizationDecision.DECLINE


def _locus(governor: SemanticGovernor, representative_id: str) -> SemanticLocus:
    return next(
        locus for locus in governor.view().loci if locus.representative_id == representative_id
    )


# --- AGREE ---------------------------------------------------------------------------


def test_agree_submits_identical_signature_under_human_fingerprint_and_applies() -> None:
    _, governor = _story()
    pending = governor.state().semantic.judgments["J-supA"]

    records = _resolve(governor, ("J-supA",), _agree)

    assert len(records) == 1
    record = records[0]
    assert record.track == "A"
    assert record.pending_judgment_id == "J-supA"
    assert record.decision is AuthorizationDecision.AGREE
    assert record.not_offered is None
    assert record.submitted_judgment_id is not None
    assert record.proposal_signature == proposal_signature(pending.proposal)
    assert record.proposal_signature == ("SUPERSEDE", "J-clA")

    semantic = governor.state().semantic
    submitted = semantic.judgments[record.submitted_judgment_id]
    # Identical proposal object: same target, same reason, same kind, same signature.
    assert submitted.proposal == pending.proposal
    assert proposal_signature(submitted.proposal) == proposal_signature(pending.proposal)
    assert submitted.reasoner == HUMAN_FINGERPRINT
    assert submitted.reasoner.is_human is True
    assert submitted.reasoner.model == ARCHITECT_ACTOR
    assert submitted.rationale == "AGREE: J-supA"
    assert submitted.project_id == PROJECT
    # Applied under human authority — rule 4 — not as a second lens.
    admission = semantic.admissions[submitted.judgment_id]
    assert admission.route is AdmissionRoute.APPLY
    assert admission.reasons == ("HUMAN_AUTHORITY",)
    assert submitted.judgment_id in semantic.applied_judgment_ids
    # The AI proposal itself is never re-routed or applied.
    assert semantic.admissions["J-supA"].route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert "J-supA" not in semantic.applied_judgment_ids


def test_agree_derives_satisfied_by_and_clears_readiness_block() -> None:
    _, governor = _story()
    blocked = build_intent_decision_handoff(governor.state(), "A").readiness
    assert blocked.pending_material_judgment_ids == ("J-supA",)
    assert blocked.semantic_blockers_clear is False

    (record,) = _resolve(governor, ("J-supA",), _agree)

    view = governor.view()
    assert dict(view.satisfied_by) == {"J-supA": record.submitted_judgment_id}
    assert view.pending_judgment_ids == ()
    locus = _locus(governor, ADDR_A)
    assert CLAIM_A_OLD not in locus.claim_ids
    assert CLAIM_A_NEW in locus.claim_ids
    assert "J-clA" not in governor.view().active_bindings.values()
    readiness = build_intent_decision_handoff(governor.state(), "A").readiness
    assert readiness.pending_material_judgment_ids == ()
    assert readiness.disputed_locus_ids == ()
    assert readiness.stale_object_ids == ()
    assert readiness.semantic_blockers_clear is True


# --- DECLINE -------------------------------------------------------------------------


def test_decline_creates_no_judgment_and_leaves_proposal_pending() -> None:
    store, governor = _story()
    sequence_before = store.current_sequence(PROJECT)
    judgments_before = set(governor.state().semantic.judgments)

    records = _resolve(governor, ("J-supA",), _decline)

    assert len(records) == 1
    record = records[0]
    assert record.track == "A"
    assert record.pending_judgment_id == "J-supA"
    assert record.decision is AuthorizationDecision.DECLINE
    assert record.not_offered is None
    assert record.submitted_judgment_id is None
    assert record.proposal_signature == ("SUPERSEDE", "J-clA")
    # Nothing was appended: no judgment, no admission, no event of any kind.
    assert store.current_sequence(PROJECT) == sequence_before
    assert set(governor.state().semantic.judgments) == judgments_before

    view = governor.view()
    assert view.pending_judgment_ids == ("J-supA",)
    assert dict(view.satisfied_by) == {}
    assert "J-clA" in governor.state().semantic.applied_judgment_ids
    locus = _locus(governor, ADDR_A)
    assert set(locus.claim_ids) == {CLAIM_A_OLD, CLAIM_A_NEW}
    assert locus.disputed_claim_pairs == ()
    assert governor.state().semantic.conflicts == ()
    readiness = build_intent_decision_handoff(governor.state(), "A").readiness
    assert readiness.pending_material_judgment_ids == ("J-supA",)
    assert readiness.semantic_blockers_clear is False


# --- budget ----------------------------------------------------------------------------


def test_budget_per_track_and_total_enforced() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    for scope, suffix in (("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("U", "U")):
        _correction(governor, scope, suffix)
    # A second pending SUPERSEDE on track A with a different target.
    governor.ingest(_evidence("EV-A3"))
    assert governor.submit(_claim("J-clA-third", ADDR_A, "EV-A3", "21")).route is (
        AdmissionRoute.APPLY
    )
    assert governor.submit(_supersede("J-supA-second", "J-clA-third")).route is (
        AdmissionRoute.REQUIRE_SECOND_LENS
    )
    record_architect_authority(
        governor, clock=_ticking_clock(), id_factory=_counter_id_factory("AUTH-")
    )
    presented: list[str] = []

    def always_agree(judgment: SemanticJudgment) -> AuthorizationDecision:
        presented.append(judgment.judgment_id)
        return AuthorizationDecision.AGREE

    counter = AuthorizationCounter()
    ids = _counter_id_factory("HUM-")
    assert AuthorizationBudget() == AuthorizationBudget(per_track=1, total=3)

    first = _resolve(
        governor,
        ("J-supA", "J-supA-second", "J-supU"),
        always_agree,
        counter=counter,
        id_factory=ids,
    )

    assert [(r.pending_judgment_id, r.decision, r.not_offered) for r in first] == [
        ("J-supA", AuthorizationDecision.AGREE, None),
        ("J-supA-second", None, NotOfferedReason.TRACK_BUDGET_EXHAUSTED),
        ("J-supU", None, NotOfferedReason.UNTRACKED),
    ]
    assert first[1].track == "A"
    assert first[1].submitted_judgment_id is None
    assert first[2].track is None
    assert presented == ["J-supA"]

    # The same counter carries across calls: two more AGREEs reach the total of 3.
    second = _resolve(
        governor, ("J-supB", "J-supC", "J-supD"), always_agree, counter=counter, id_factory=ids
    )

    assert [(r.pending_judgment_id, r.decision, r.not_offered) for r in second] == [
        ("J-supB", AuthorizationDecision.AGREE, None),
        ("J-supC", AuthorizationDecision.AGREE, None),
        ("J-supD", None, NotOfferedReason.TOTAL_BUDGET_EXHAUSTED),
    ]
    assert second[2].track == "D"
    assert presented == ["J-supA", "J-supB", "J-supC"]
    assert counter.total == 3
    assert counter.answered("A") == 1
    assert counter.answered("D") == 0

    # Exactly three human judgments exist in the ledger; not-offered ids stay pending.
    semantic = governor.state().semantic
    human_judgments = [j for j in semantic.judgments.values() if j.reasoner == HUMAN_FINGERPRINT]
    assert len(human_judgments) == 3
    assert governor.view().pending_judgment_ids == ("J-supA-second", "J-supD", "J-supU")
    assert set(governor.view().satisfied_by) == {"J-supA", "J-supB", "J-supC"}


# --- the authorizer's input surface -----------------------------------------------------


def test_authorizer_receives_the_verbatim_proposal_and_nothing_else() -> None:
    _, governor = _story()
    pending = governor.state().semantic.judgments["J-supA"]
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def spy(*args: Any, **kwargs: Any) -> AuthorizationDecision:
        calls.append((args, kwargs))
        return AuthorizationDecision.DECLINE

    _resolve(governor, ("J-supA",), spy)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs == {}
    assert len(args) == 1
    seen = args[0]
    assert isinstance(seen, SemanticJudgment)
    assert seen == pending
    assert seen.proposal == pending.proposal
    assert seen.reasoner == MODEL_A


def test_no_api_exists_to_edit_target_reason_or_author_a_supersession() -> None:
    forbidden_names = {
        "proposal",
        "target",
        "target_judgment_id",
        "reason",
        "rationale",
        "judgment",
        "claim",
        "claim_id",
        "address",
        "address_id",
        "candidate",
        "evidence_ids",
        "signature",
    }
    forbidden_types = {SemanticJudgment, SupersedeProposal, JudgmentProposal}
    public_functions = {
        name: obj
        for name, obj in vars(authority_module).items()
        if not name.startswith("_")
        and inspect.isfunction(obj)
        and obj.__module__ == authority_module.__name__
    }
    assert set(public_functions) == {"record_architect_authority", "resolve_pending_supersessions"}
    for name, function in public_functions.items():
        hints = typing.get_type_hints(function)
        for parameter in inspect.signature(function).parameters.values():
            assert parameter.name not in forbidden_names, f"{name}({parameter.name})"
            assert hints.get(parameter.name) not in forbidden_types, f"{name}({parameter.name})"
    # The only human input path is the Authorizer: it sees a judgment and returns a decision.
    authorizer_args, authorizer_return = typing.get_args(Authorizer)
    assert authorizer_args == [SemanticJudgment]
    assert authorizer_return is AuthorizationDecision
    assert {member.value for member in AuthorizationDecision} == {"AGREE", "DECLINE"}
    # No public method on any exported class accepts a proposal, target or reason either.
    public_classes = {
        name: obj
        for name, obj in vars(authority_module).items()
        if not name.startswith("_")
        and inspect.isclass(obj)
        and obj.__module__ == authority_module.__name__
    }
    for class_name, cls in public_classes.items():
        for method_name, method in inspect.getmembers(cls, inspect.isfunction):
            if method_name.startswith("_") or method.__module__ != authority_module.__name__:
                continue
            for parameter in inspect.signature(method).parameters.values():
                assert parameter.name not in forbidden_names, f"{class_name}.{method_name}"


# --- authority record ---------------------------------------------------------------------


def test_authority_record_is_project_wide_and_recorded_as_event() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    governor.ingest(_evidence("EV-A"))
    sequence_before = store.current_sequence(PROJECT)

    stored = record_architect_authority(
        governor, clock=_ticking_clock(), id_factory=_counter_id_factory("AUTH-")
    )

    assert stored.sequence == sequence_before + 1
    assert stored.event.event_type is EventType.SEMANTIC_OBJECT_RECORDED
    assert stored.event.project_id == PROJECT
    payload = stored.event.payload
    assert isinstance(payload, SemanticObjectPayload)
    record = payload.object
    assert isinstance(record, AuthorityRecord)
    assert record.scope == ()
    assert record.project_id == PROJECT
    assert record.authorized_by == ARCHITECT_ACTOR
    assert record.lifecycle is LifecycleStatus.ACTIVE
    assert record.authority is Authority.CANONICAL
    assert record.created_at == T0
    assert record.provenance.source_kind is SourceKind.HUMAN
    assert record.provenance.source_ref == ARCHITECT_ACTOR
    # It is in the ledger and in replayed state, and covers every scope.
    assert store.load(PROJECT)[-1] == stored
    assert governor.state().objects[record.id] == record
    for scope in ("A", "constitution", "intent-engine"):
        handoff = build_intent_decision_handoff(governor.state(), scope)
        assert record.id in handoff.authority_record_ids
    # Without the record an AGREE is refused BEFORE any ledger write: nothing is
    # appended, the target judgment and its claim stay active, no human judgment exists.
    fresh_store = InMemoryEventStore()
    fresh = _governor(fresh_store)
    _correction(fresh, "A", "A")
    sequence_before = fresh_store.current_sequence(PROJECT)
    with pytest.raises(AuthorizationHalted, match="AuthorityRecord") as info:
        _resolve(fresh, ("J-supA",), _agree)
    assert info.value.records == ()
    assert isinstance(info.value.__cause__, ValueError)
    assert fresh_store.current_sequence(PROJECT) == sequence_before
    semantic = fresh.state().semantic
    assert "J-clA" in active_judgment_ids(semantic)
    assert CLAIM_A_OLD in _locus(fresh, ADDR_A).claim_ids
    assert not any(j.reasoner == HUMAN_FINGERPRINT for j in semantic.judgments.values())
    assert fresh.view().pending_judgment_ids == ("J-supA",)


def test_equivalent_pending_is_never_offered() -> None:
    _, governor = _story()
    governor.ingest(_evidence("EV-A3"))
    assert governor.submit(_create("J-cA2", ("A",), "EV-A3")).route is AdmissionRoute.APPLY
    assert (
        governor.submit(
            _judgment("J-eq", EquivalentProposal(address_a=ADDR_A, address_b=ADDR_A2))
        ).route
        is AdmissionRoute.REQUIRE_SECOND_LENS
    )
    presented: list[str] = []

    def spy(judgment: SemanticJudgment) -> AuthorizationDecision:
        presented.append(judgment.judgment_id)
        return AuthorizationDecision.AGREE

    records = _resolve(governor, ("J-eq",), spy, track_of=lambda _: "A")

    assert presented == []
    assert [(r.pending_judgment_id, r.decision, r.not_offered) for r in records] == [
        ("J-eq", None, NotOfferedReason.NOT_SUPERSEDE)
    ]
    assert governor.view().pending_judgment_ids == ("J-eq", "J-supA")


# --- R9-b: an answered proposal consumes its slot; a declined id is never re-presented -----


def test_decline_consumes_the_track_slot_and_total_budget() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    for scope, suffix in (("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")):
        _correction(governor, scope, suffix)
    governor.ingest(_evidence("EV-A3"))
    assert governor.submit(_claim("J-clA-third", ADDR_A, "EV-A3", "21")).route is (
        AdmissionRoute.APPLY
    )
    assert governor.submit(_supersede("J-supA-second", "J-clA-third")).route is (
        AdmissionRoute.REQUIRE_SECOND_LENS
    )
    record_architect_authority(
        governor, clock=_ticking_clock(), id_factory=_counter_id_factory("AUTH-")
    )
    sequence_before = store.current_sequence(PROJECT)
    presented: list[str] = []

    def always_decline(judgment: SemanticJudgment) -> AuthorizationDecision:
        presented.append(judgment.judgment_id)
        return AuthorizationDecision.DECLINE

    counter = AuthorizationCounter()

    first = _resolve(governor, ("J-supA",), always_decline, counter=counter)

    assert [(r.pending_judgment_id, r.decision, r.not_offered) for r in first] == [
        ("J-supA", AuthorizationDecision.DECLINE, None)
    ]
    assert counter.answered("A") == 1
    assert counter.total == 1

    second = _resolve(
        governor,
        ("J-supA", "J-supA-second", "J-supB", "J-supC", "J-supD"),
        always_decline,
        counter=counter,
    )

    assert [(r.pending_judgment_id, r.decision, r.not_offered) for r in second] == [
        ("J-supA", None, NotOfferedReason.ALREADY_DECLINED),
        ("J-supA-second", None, NotOfferedReason.TRACK_BUDGET_EXHAUSTED),
        ("J-supB", AuthorizationDecision.DECLINE, None),
        ("J-supC", AuthorizationDecision.DECLINE, None),
        ("J-supD", None, NotOfferedReason.TOTAL_BUDGET_EXHAUSTED),
    ]
    assert presented == ["J-supA", "J-supB", "J-supC"]
    assert counter.total == 3
    # The ledger is untouched throughout; every proposal is still pending.
    assert store.current_sequence(PROJECT) == sequence_before
    assert governor.view().pending_judgment_ids == (
        "J-supA",
        "J-supA-second",
        "J-supB",
        "J-supC",
        "J-supD",
    )
    assert all(r.submitted_judgment_id is None for r in first + second)


# --- R9-c: a mid-batch failure halts with the records completed so far -----------------


def test_halt_mid_batch_preserves_completed_records() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    _correction(governor, "A", "A")
    _correction(governor, "B", "B")
    record_architect_authority(
        governor, clock=_ticking_clock(), id_factory=_counter_id_factory("AUTH-")
    )
    presented: list[str] = []

    def spy(judgment: SemanticJudgment) -> AuthorizationDecision:
        presented.append(judgment.judgment_id)
        return AuthorizationDecision.AGREE

    with pytest.raises(AuthorizationHalted, match="J-missing") as info:
        _resolve(governor, ("J-supA", "J-missing", "J-supB"), spy)

    halted = info.value
    assert isinstance(halted, RuntimeError)
    assert isinstance(halted.__cause__, ValueError)
    assert len(halted.records) == 1
    assert halted.records[0].pending_judgment_id == "J-supA"
    assert halted.records[0].decision is AuthorizationDecision.AGREE
    assert halted.records[0].submitted_judgment_id is not None
    # The batch stopped at the failure: J-supB was never presented and stays pending.
    assert presented == ["J-supA"]
    assert governor.view().pending_judgment_ids == ("J-supB",)


# --- refusals that write nothing -----------------------------------------------------------


def test_agree_twice_is_not_pending_and_yields_exactly_one_human_judgment() -> None:
    store, governor = _story()
    presented: list[str] = []

    def spy(judgment: SemanticJudgment) -> AuthorizationDecision:
        presented.append(judgment.judgment_id)
        return AuthorizationDecision.AGREE

    (first,) = _resolve(governor, ("J-supA",), spy)
    sequence_after_first = store.current_sequence(PROJECT)
    (second,) = _resolve(governor, ("J-supA",), spy)

    assert first.decision is AuthorizationDecision.AGREE
    assert second.decision is None
    assert second.not_offered is NotOfferedReason.NOT_PENDING
    assert second.submitted_judgment_id is None
    assert presented == ["J-supA"]
    assert store.current_sequence(PROJECT) == sequence_after_first
    semantic = governor.state().semantic
    human = [j for j in semantic.judgments.values() if j.reasoner == HUMAN_FINGERPRINT]
    assert len(human) == 1
    assert dict(governor.view().satisfied_by) == {"J-supA": first.submitted_judgment_id}


def test_unknown_id_raises_and_writes_nothing() -> None:
    store, governor = _story()
    sequence_before = store.current_sequence(PROJECT)

    with pytest.raises(AuthorizationHalted, match="J-nope") as info:
        _resolve(governor, ("J-nope",), _agree)

    assert info.value.records == ()
    assert isinstance(info.value.__cause__, ValueError)
    assert store.current_sequence(PROJECT) == sequence_before
    assert governor.view().pending_judgment_ids == ("J-supA",)


def test_authorizer_returning_a_plain_string_is_refused_and_writes_nothing() -> None:
    store, governor = _story()
    sequence_before = store.current_sequence(PROJECT)

    def stringly(_: SemanticJudgment) -> AuthorizationDecision:
        return "AGREE"  # type: ignore[return-value]

    with pytest.raises(AuthorizationHalted, match="AGREE or DECLINE") as info:
        _resolve(governor, ("J-supA",), stringly)

    assert info.value.records == ()
    assert isinstance(info.value.__cause__, ValueError)
    assert store.current_sequence(PROJECT) == sequence_before
    semantic = governor.state().semantic
    assert not any(j.reasoner == HUMAN_FINGERPRINT for j in semantic.judgments.values())
    assert governor.view().pending_judgment_ids == ("J-supA",)
