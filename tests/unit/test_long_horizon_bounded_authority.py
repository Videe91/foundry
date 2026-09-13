"""Tests for the pre-T eligible-target authority protocol (9P3 T2 brief; spec §18).

Every governor here is a real ``SemanticGovernor`` over an ``InMemoryEventStore``; the
human AGREE is the only channel ``authority.py`` ever writes through. The B lineage
fixture models the spec §18.2 discriminator: a T1 claim at the designated B address,
corrected at T5 (model ASSERT of a new claim plus a model SUPERSEDE of the T1 judgment,
applied by this module's own mechanical AGREE), so that at the T8 revert the T5-created
judgment is the only eligible target and the T1 judgment is absent. Wording is opaque
(``SUBJECT_ALPHA`` / ``PREDICATE_ALPHA``); only evidence ids follow the spec §7 id law.
No frontier reasoner is constructed or called anywhere. ZERO live calls; sockets are
blocked.
"""

from __future__ import annotations

import ast
import inspect
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy, authority_record_is_live
from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import SemanticAdmissionPayload
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    proposal_signature,
)
from foundry.domain.semantic_view import derive_view
from foundry.experiments.long_horizon_bounded import authority as authority_module
from foundry.experiments.long_horizon_bounded.authority import (
    ARCHITECT_ACTOR,
    HUMAN_FINGERPRINT,
    AuthorizationCeilingExceeded,
    AuthorizationOutcome,
    AuthorizationRecord,
    EligibleTargets,
    authorize_eligible_supersessions,
    record_architect_authority,
    snapshot_eligible_targets,
)
from foundry.experiments.long_horizon_bounded.protocol import MAX_HUMAN_AUTHORIZATIONS
from foundry.experiments.long_horizon_bounded.timeline import evidence_id

PROJECT = "PROJ-9P3-AUTHORITY-TEST"
T0 = datetime(2026, 9, 13, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="test-v1")

FORBIDDEN_ATTRIBUTE_READS = frozenset(
    {"predicate", "value", "subject", "facet", "content", "rationale"}
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


class _Budget:
    """Tiny mutable stand-in satisfying the ``AuthorizationBudget`` protocol structurally."""

    def __init__(self, human_authorizations: int = 0) -> None:
        self.human_authorizations = human_authorizations


# --- builders (kept local per implementer contract; no shared helper module) --------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _governor() -> tuple[SemanticGovernor, InMemoryEventStore]:
    clock = _clock()
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )
    return governor, store


def _evidence(evidence_id: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=f"Opaque evidence body {evidence_id}.",
        observed_at=T0,
        scope=(),
        artifact_ref="doc/alpha.md",
    )


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    evidence_id: str,
    *,
    reasoner: ReasonerFingerprint = MODEL,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(
            candidate=SemanticCandidate(
                candidate_id=f"CAND-{judgment_id}",
                subject="SUBJECT_ALPHA",
                facet="lifecycle",
                evidence_ids=(evidence_id,),
            )
        ),
        evidence_id,
    )


def _claim(
    judgment_id: str, address_id: str, evidence_id: str, *, value: str = "7"
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="PREDICATE_ALPHA",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(value), unit="day"),
            evidence_ids=(evidence_id,),
            authority=Authority.OBSERVED,
        ),
        evidence_id,
    )


def _supersede(judgment_id: str, target: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupersedeProposal(target_judgment_id=target, reason="Opaque correction reason."),
        evidence_id,
    )


def _apply(governor: SemanticGovernor, judgment: SemanticJudgment) -> None:
    decision = governor.submit(judgment)
    assert decision.route is AdmissionRoute.APPLY


def _submit_pending_supersede(
    governor: SemanticGovernor, judgment_id: str, target: str, evidence_id: str
) -> None:
    """A model-originated SUPERSEDE is material: it is held pending, never applied by the model."""
    governor.ingest(_evidence(evidence_id))
    decision = governor.submit(_supersede(judgment_id, target, evidence_id))
    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert judgment_id in governor.view().pending_judgment_ids


def _live_claim_ids(governor: SemanticGovernor) -> frozenset[str]:
    return frozenset(derive_view(governor.state().semantic).effective_evidence)


def _snapshot(
    governor: SemanticGovernor,
    store: InMemoryEventStore,
    *,
    t: int,
    address_id: str | None,
    arm: str = "F",
) -> EligibleTargets:
    return snapshot_eligible_targets(
        governor.state(),
        arm=arm,  # type: ignore[arg-type]
        t=t,
        target_locus="B",
        designated_address_id=address_id,
        ledger_length=store.current_sequence(PROJECT),
    )


def _authorize(
    governor: SemanticGovernor,
    eligible: EligibleTargets,
    pending: tuple[str, ...],
    budget: _Budget,
) -> tuple[AuthorizationRecord, ...]:
    return authorize_eligible_supersessions(
        governor=governor,
        eligible=eligible,
        pending_judgment_ids=pending,
        budget=budget,
        clock=lambda: T0,
        id_factory=_counter_id_factory(),
    )


def _t1_root_b(governor: SemanticGovernor, *, with_authority: bool = True) -> str:
    """Authority record, then the T1 B root: one address ``ADDR_B``, one claim ``J-b1``."""
    if with_authority:
        record_architect_authority(governor, clock=lambda: T0, id_factory=_counter_id_factory())
    seed = evidence_id(1, "B")
    governor.ingest(_evidence(seed))
    _apply(governor, _create("J-cB", seed))
    address_b = address_id_for(PROJECT, "J-cB")
    _apply(governor, _claim("J-b1", address_b, seed))
    return address_b


def _t5_correction(
    governor: SemanticGovernor, store: InMemoryEventStore, address_b: str
) -> tuple[AuthorizationRecord, ...]:
    """T5 corrects B: pre-T5 snapshot, model ASSERT ``J-b5`` at ``ADDR_B``, model
    SUPERSEDE(``J-b1``) held pending, then this module's own mechanical AGREE applies it."""
    eligible_5 = _snapshot(governor, store, t=5, address_id=address_b)
    assert eligible_5.eligible_judgment_ids == ("J-b1",)
    ev5 = evidence_id(5, "B")
    governor.ingest(_evidence(ev5))
    _apply(governor, _claim("J-b5", address_b, ev5, value="9"))
    decision = governor.submit(_supersede("J-sup5", "J-b1", ev5))
    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    records = _authorize(governor, eligible_5, ("J-sup5",), _Budget())
    assert [record.outcome for record in records] == [AuthorizationOutcome.AGREED]
    live = _live_claim_ids(governor)
    assert claim_id_for(PROJECT, "J-b1") not in live
    assert claim_id_for(PROJECT, "J-b5") in live
    return records


def _admission_for(store: InMemoryEventStore, judgment_id: str) -> SemanticAdmissionPayload:
    admissions = [
        stored.event.payload
        for stored in store.load(PROJECT)
        if isinstance(stored.event.payload, SemanticAdmissionPayload)
        and stored.event.payload.judgment_id == judgment_id
    ]
    assert len(admissions) == 1
    return admissions[0]


# --- authority identity ---------------------------------------------------------------


def test_human_fingerprint_and_actor_satisfy_governor_trust_boundary() -> None:
    assert HUMAN_FINGERPRINT.provider == "human"
    assert HUMAN_FINGERPRINT.model == "human://architect"
    assert HUMAN_FINGERPRINT.policy_version == "intent-v2-9p3-long-horizon-v1"
    assert HUMAN_FINGERPRINT.is_human
    assert ARCHITECT_ACTOR == "architect"

    governor, _store = _governor()
    governor.ingest(_evidence("EV-1"))
    judgment = _judgment(
        "J-human",
        CreateAddressProposal(
            candidate=SemanticCandidate(
                candidate_id="CAND-J-human",
                subject="SUBJECT_ALPHA",
                facet="lifecycle",
                evidence_ids=("EV-1",),
            )
        ),
        "EV-1",
        reasoner=HUMAN_FINGERPRINT,
    )
    # The authenticated actor MUST equal the fingerprint's model, "human://architect" --
    # the logical display id "architect" alone does not satisfy the governor.
    with pytest.raises(ValueError):
        governor.submit(judgment, human_actor_id=ARCHITECT_ACTOR)
    decision = governor.submit(judgment, human_actor_id=HUMAN_FINGERPRINT.model)
    assert decision.route is AdmissionRoute.APPLY


def test_record_architect_authority_writes_a_live_project_wide_record() -> None:
    governor, _store = _governor()

    record_architect_authority(governor, clock=lambda: T0, id_factory=_counter_id_factory())

    live_records = [
        obj
        for obj in governor.state().objects.values()
        if isinstance(obj, AuthorityRecord)
        and obj.authorized_by == HUMAN_FINGERPRINT.model
        and obj.scope == ()
    ]
    assert len(live_records) == 1
    assert authority_record_is_live(live_records[0])
    assert live_records[0].subject_id == "material-semantic-change"
    assert live_records[0].confidence == 1.0


def test_agree_is_refused_before_any_authority_record_exists() -> None:
    governor, store = _governor()
    address_b = _t1_root_b(governor, with_authority=False)
    eligible = _snapshot(governor, store, t=3, address_id=address_b)
    _submit_pending_supersede(governor, "J-sup", "J-b1", "EV-2")
    before = store.current_sequence(PROJECT)
    budget = _Budget()

    with pytest.raises(ValueError):
        _authorize(governor, eligible, ("J-sup",), budget)

    assert budget.human_authorizations == 0
    assert store.current_sequence(PROJECT) == before


# --- the pre-T snapshot -------------------------------------------------------------------


def test_t8_snapshot_contains_t5_claim_and_excludes_t1_claim() -> None:
    governor, store = _governor()
    address_b = _t1_root_b(governor)
    _t5_correction(governor, store, address_b)

    eligible = snapshot_eligible_targets(
        governor.state(),
        arm="F",
        t=8,
        target_locus="B",
        designated_address_id=address_b,
        ledger_length=len(store.load(PROJECT)),
    )

    assert eligible.eligible_judgment_ids == ("J-b5",)
    assert "J-b1" not in eligible.eligible_judgment_ids
    assert eligible.live_claim_ids == (claim_id_for(PROJECT, "J-b5"),)
    assert eligible == EligibleTargets(
        arm="F",
        t=8,
        target_locus="B",
        designated_address_id=address_b,
        eligible_judgment_ids=("J-b5",),
        live_claim_ids=(claim_id_for(PROJECT, "J-b5"),),
        snapshot_sequence=store.current_sequence(PROJECT),
    )


def test_snapshot_is_taken_before_ingesting_t_and_ignores_claims_created_during_t() -> None:
    governor, store = _governor()
    address_b = _t1_root_b(governor)
    _t5_correction(governor, store, address_b)
    eligible = _snapshot(governor, store, t=8, address_id=address_b)
    sequence_at_snapshot = store.current_sequence(PROJECT)

    # T8 runs: the model asserts a NEW claim at the designated address, then proposes
    # to supersede that new claim's judgment. Neither was live pre-T8.
    ev8 = evidence_id(8, "B")
    governor.ingest(_evidence(ev8))
    _apply(governor, _claim("J-b8", address_b, ev8, value="7"))
    decision = governor.submit(_supersede("J-sup8-new", "J-b8", ev8))
    assert decision.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert claim_id_for(PROJECT, "J-b8") in _live_claim_ids(governor)

    # The snapshot object is frozen pre-T state: unchanged by anything ingested at T.
    assert eligible.eligible_judgment_ids == ("J-b5",)
    assert eligible.live_claim_ids == (claim_id_for(PROJECT, "J-b5"),)
    assert claim_id_for(PROJECT, "J-b8") not in eligible.live_claim_ids
    assert "J-b8" not in eligible.eligible_judgment_ids
    assert eligible.snapshot_sequence == sequence_at_snapshot
    assert store.current_sequence(PROJECT) > sequence_at_snapshot
    # A fresh snapshot WOULD see it -- which is exactly why the pre-T one is authoritative.
    assert "J-b8" in _snapshot(governor, store, t=8, address_id=address_b).eligible_judgment_ids

    # Authority over the pre-T snapshot: the target that became live only during T is
    # recorded not-eligible and nothing is written.
    before = store.current_sequence(PROJECT)
    budget = _Budget()
    records = _authorize(governor, eligible, ("J-sup8-new",), budget)
    assert [(record.target_judgment_id, record.outcome) for record in records] == [
        ("J-b5", AuthorizationOutcome.NO_PROPOSAL),
        ("J-b8", AuthorizationOutcome.NOT_ELIGIBLE_NOT_AUTHORIZED),
    ]
    assert budget.human_authorizations == 0
    assert store.current_sequence(PROJECT) == before
    assert "J-sup8-new" in governor.view().pending_judgment_ids


def test_undesignated_locus_snapshot_is_empty() -> None:
    governor, store = _governor()
    _t1_root_b(governor)

    eligible = _snapshot(governor, store, t=3, address_id=None, arm="A")

    assert eligible == EligibleTargets(
        arm="A",
        t=3,
        target_locus="B",
        designated_address_id=None,
        eligible_judgment_ids=(),
        live_claim_ids=(),
        snapshot_sequence=store.current_sequence(PROJECT),
    )


# --- AGREE ------------------------------------------------------------------------------------


def test_exactly_one_matching_proposal_agrees_with_identical_signature_no_visible_evidence() -> (
    None
):
    governor, store = _governor()
    address_b = _t1_root_b(governor)
    eligible = _snapshot(governor, store, t=3, address_id=address_b)
    _submit_pending_supersede(governor, "J-sup", "J-b1", "EV-2")
    pending = governor.state().semantic.judgments["J-sup"]
    expected_signature = proposal_signature(pending.proposal)
    budget = _Budget()

    records = _authorize(governor, eligible, ("J-sup",), budget)

    assert len(records) == 1
    record = records[0]
    assert record == AuthorizationRecord(
        arm="F",
        t=3,
        target_locus="B",
        target_judgment_id="J-b1",
        outcome=AuthorizationOutcome.AGREED,
        pending_judgment_ids=("J-sup",),
        submitted_judgment_id=record.submitted_judgment_id,
        proposal_signature=expected_signature,
        actor_id="architect",
    )
    assert record.submitted_judgment_id is not None
    assert budget.human_authorizations == 1

    submitted = governor.state().semantic.judgments[record.submitted_judgment_id]
    assert submitted.reasoner == HUMAN_FINGERPRINT
    assert submitted.visible_evidence_ids == ()
    assert submitted.proposal == pending.proposal
    assert proposal_signature(submitted.proposal) == expected_signature
    admission = _admission_for(store, record.submitted_judgment_id)
    assert admission.route is AdmissionRoute.APPLY
    assert "HUMAN_AUTHORITY" in admission.reasons
    # J-b1's claim is retired by the AGREE; the model's proposal is no longer pending.
    assert claim_id_for(PROJECT, "J-b1") not in _live_claim_ids(governor)
    assert "J-sup" not in governor.view().pending_judgment_ids


def test_several_eligible_claims_at_one_address_each_get_one_agree() -> None:
    governor, store = _governor()
    address_b = _t1_root_b(governor)
    _apply(governor, _claim("J-b1-second", address_b, evidence_id(1, "B"), value="9"))
    eligible = _snapshot(governor, store, t=3, address_id=address_b)
    assert eligible.eligible_judgment_ids == ("J-b1", "J-b1-second")
    _submit_pending_supersede(governor, "J-sup-second", "J-b1-second", "EV-2")
    _submit_pending_supersede(governor, "J-sup-first", "J-b1", "EV-3")
    budget = _Budget()

    records = _authorize(governor, eligible, ("J-sup-second", "J-sup-first"), budget)

    assert [(record.target_judgment_id, record.outcome) for record in records] == [
        ("J-b1", AuthorizationOutcome.AGREED),
        ("J-b1-second", AuthorizationOutcome.AGREED),
    ]
    assert records[0].pending_judgment_ids == ("J-sup-first",)
    assert records[1].pending_judgment_ids == ("J-sup-second",)
    assert budget.human_authorizations == 2
    submitted_ids = {record.submitted_judgment_id for record in records}
    assert len(submitted_ids) == 2 and None not in submitted_ids
    live = _live_claim_ids(governor)
    assert claim_id_for(PROJECT, "J-b1") not in live
    assert claim_id_for(PROJECT, "J-b1-second") not in live


# --- fail closed ----------------------------------------------------------------------------


def test_zero_matching_is_no_proposal_and_two_competing_is_ambiguous_with_no_write() -> None:
    governor, store = _governor()
    address_b = _t1_root_b(governor)
    eligible = _snapshot(governor, store, t=3, address_id=address_b)

    # zero matching proposals
    before = store.current_sequence(PROJECT)
    budget = _Budget()
    records = _authorize(governor, eligible, (), budget)
    assert records == (
        AuthorizationRecord(
            arm="F",
            t=3,
            target_locus="B",
            target_judgment_id="J-b1",
            outcome=AuthorizationOutcome.NO_PROPOSAL,
            pending_judgment_ids=(),
            submitted_judgment_id=None,
            proposal_signature=None,
        ),
    )
    assert budget.human_authorizations == 0
    assert store.current_sequence(PROJECT) == before

    # two competing proposals for the same eligible id
    _submit_pending_supersede(governor, "J-sup-y", "J-b1", "EV-2")
    _submit_pending_supersede(governor, "J-sup-x", "J-b1", "EV-3")
    before = store.current_sequence(PROJECT)
    records = _authorize(governor, eligible, ("J-sup-y", "J-sup-x"), budget)
    assert records == (
        AuthorizationRecord(
            arm="F",
            t=3,
            target_locus="B",
            target_judgment_id="J-b1",
            outcome=AuthorizationOutcome.AMBIGUOUS_PROPOSALS,
            pending_judgment_ids=("J-sup-x", "J-sup-y"),
            submitted_judgment_id=None,
            proposal_signature=None,
        ),
    )
    assert budget.human_authorizations == 0
    assert store.current_sequence(PROJECT) == before
    assert claim_id_for(PROJECT, "J-b1") in _live_claim_ids(governor)
    assert {"J-sup-x", "J-sup-y"} <= set(governor.view().pending_judgment_ids)


def test_non_eligible_pending_targets_are_recorded_not_authorized_and_never_retargeted() -> None:
    governor, store = _governor()
    address_b = _t1_root_b(governor)
    governor.ingest(_evidence("EV-OTHER"))
    _apply(governor, _create("J-cOther", "EV-OTHER"))
    other_address = address_id_for(PROJECT, "J-cOther")
    _apply(governor, _claim("J-other", other_address, "EV-OTHER"))
    eligible = _snapshot(governor, store, t=3, address_id=address_b)
    assert eligible.eligible_judgment_ids == ("J-b1",)
    _submit_pending_supersede(governor, "J-sup-other", "J-other", "EV-4")
    before = store.current_sequence(PROJECT)
    budget = _Budget()

    records = _authorize(governor, eligible, ("J-sup-other",), budget)

    assert records == (
        AuthorizationRecord(
            arm="F",
            t=3,
            target_locus="B",
            target_judgment_id="J-b1",
            outcome=AuthorizationOutcome.NO_PROPOSAL,
            pending_judgment_ids=(),
            submitted_judgment_id=None,
            proposal_signature=None,
        ),
        AuthorizationRecord(
            arm="F",
            t=3,
            target_locus="B",
            target_judgment_id="J-other",
            outcome=AuthorizationOutcome.NOT_ELIGIBLE_NOT_AUTHORIZED,
            pending_judgment_ids=("J-sup-other",),
            submitted_judgment_id=None,
            proposal_signature=None,
        ),
    )
    assert budget.human_authorizations == 0
    assert store.current_sequence(PROJECT) == before
    # Never retargeted: the eligible T1 claim stays live, the proposal stays pending.
    assert claim_id_for(PROJECT, "J-b1") in _live_claim_ids(governor)
    assert claim_id_for(PROJECT, "J-other") in _live_claim_ids(governor)
    assert "J-sup-other" in governor.view().pending_judgment_ids


def test_undesignated_locus_authorizes_nothing() -> None:
    governor, store = _governor()
    _t1_root_b(governor)
    eligible = _snapshot(governor, store, t=3, address_id=None)
    _submit_pending_supersede(governor, "J-sup", "J-b1", "EV-2")
    before = store.current_sequence(PROJECT)
    budget = _Budget()

    records = _authorize(governor, eligible, ("J-sup",), budget)

    assert [(record.target_judgment_id, record.outcome) for record in records] == [
        ("J-b1", AuthorizationOutcome.NOT_ELIGIBLE_NOT_AUTHORIZED),
    ]
    assert records[0].pending_judgment_ids == ("J-sup",)
    assert budget.human_authorizations == 0
    assert store.current_sequence(PROJECT) == before
    assert "J-sup" in governor.view().pending_judgment_ids


def test_unknown_pending_judgment_id_is_a_caller_contract_error() -> None:
    governor, store = _governor()
    address_b = _t1_root_b(governor)
    eligible = _snapshot(governor, store, t=3, address_id=address_b)
    before = store.current_sequence(PROJECT)

    with pytest.raises(KeyError):
        _authorize(governor, eligible, ("J-does-not-exist",), _Budget())

    assert store.current_sequence(PROJECT) == before


# --- ceiling ------------------------------------------------------------------------------


def test_ceiling_allows_48th_and_refuses_49th_before_any_write() -> None:
    assert MAX_HUMAN_AUTHORIZATIONS == 48

    governor, store = _governor()
    address_b = _t1_root_b(governor)
    eligible = _snapshot(governor, store, t=3, address_id=address_b)
    _submit_pending_supersede(governor, "J-sup", "J-b1", "EV-2")
    budget = _Budget(human_authorizations=47)
    records = _authorize(governor, eligible, ("J-sup",), budget)
    assert [record.outcome for record in records] == [AuthorizationOutcome.AGREED]
    assert budget.human_authorizations == 48

    governor2, store2 = _governor()
    address_b2 = _t1_root_b(governor2)
    eligible2 = _snapshot(governor2, store2, t=3, address_id=address_b2)
    _submit_pending_supersede(governor2, "J-sup2", "J-b1", "EV-2")
    budget = _Budget(human_authorizations=48)
    before = store2.current_sequence(PROJECT)
    with pytest.raises(AuthorizationCeilingExceeded):
        _authorize(governor2, eligible2, ("J-sup2",), budget)
    assert store2.current_sequence(PROJECT) == before
    assert budget.human_authorizations == 48
    assert claim_id_for(PROJECT, "J-b1") in _live_claim_ids(governor2)
    assert "J-sup2" in governor2.view().pending_judgment_ids


# --- structural proofs ---------------------------------------------------------------------


def test_no_semantic_inspection_in_authority_source() -> None:
    """Structural (AST) proof: authority.py never READS claim wording or values.

    Only ``ast.Load`` attribute reads are checked; the ``rationale=`` keyword used to
    construct the AGREE judgment is a write, not a read, and is allowed.
    """
    tree = ast.parse(inspect.getsource(authority_module))
    reads = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    }
    assert not (reads & FORBIDDEN_ATTRIBUTE_READS), sorted(reads & FORBIDDEN_ATTRIBUTE_READS)


def test_no_frontier_reasoner_is_called_by_authority() -> None:
    """Structural (AST) proof: authority.py imports and calls nothing reasoner-shaped,
    and never imports the hidden ``expectations`` module."""
    tree = ast.parse(inspect.getsource(authority_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "foundry.ports.semantic_reasoner"
            assert node.module is None or not node.module.endswith("expectations")
            assert "SemanticReasoner" not in {alias.name for alias in node.names}
            assert "expectations" not in {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            assert "SemanticReasoner" not in {alias.name for alias in node.names}
            assert not any(alias.name.endswith("expectations") for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            called_name = (
                func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            )
            assert called_name not in {"propose", "propose_and_submit"}
