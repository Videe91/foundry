"""Tests for the mechanical human-authority protocol over root supersessions
(9P2 unseen-lifecycle T2 brief; spec §8).

Every governor here is a real ``SemanticGovernor`` over an ``InMemoryEventStore``; the
human AGREE is the only channel ``authority.py`` ever writes through. No frontier
reasoner is constructed or called anywhere in this file or in the module under test.
ZERO live calls; sockets are blocked.
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
from foundry.experiments.contrastive_unseen import authority as authority_module
from foundry.experiments.contrastive_unseen.authority import (
    ARCHITECT_ACTOR,
    HUMAN_FINGERPRINT,
    AuthorizationCeilingExceeded,
    AuthorizationOutcome,
    authorize_root_supersessions,
    record_architect_authority,
)
from foundry.experiments.contrastive_unseen.designation import RootDesignation
from foundry.experiments.contrastive_unseen.timeline import MAX_HUMAN_AUTHORIZATIONS

PROJECT = "PROJ-9P2-AUTHORITY-TEST"
T0 = datetime(2026, 9, 12, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="test-v1")


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


def _governor() -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


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
                subject="subject ALPHA",
                facet="lifecycle",
                evidence_ids=(evidence_id,),
            )
        ),
        evidence_id,
    )


def _claim(judgment_id: str, address_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal("7"), unit="day"),
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


def _seed_root(governor: SemanticGovernor, *, key: str) -> RootDesignation:
    """One address, one seed-supported claim ``J-cl1`` -- mirrors ``designation.py``'s shape."""
    governor.ingest(_evidence("EV-SEED"))
    _apply(governor, _create("J-c1", "EV-SEED"))
    address_id = address_id_for(PROJECT, "J-c1")
    _apply(governor, _claim("J-cl1", address_id, "EV-SEED"))
    claim_id = claim_id_for(PROJECT, "J-cl1")
    return RootDesignation(
        key=key,  # type: ignore[arg-type]
        seed_evidence_id="EV-SEED",
        status="DESIGNATED",
        address_id=address_id,
        claim_ids=(claim_id,),
        creating_judgment_ids=("J-cl1",),
        reason="DESIGNATED",
    )


def _submit_pending_supersede(
    governor: SemanticGovernor, judgment_id: str, target: str, evidence_id: str
) -> None:
    governor.ingest(_evidence(evidence_id))
    decision = governor.submit(_supersede(judgment_id, target, evidence_id))
    assert decision.route in (AdmissionRoute.REQUIRE_SECOND_LENS, AdmissionRoute.REQUIRE_HUMAN)
    assert judgment_id in governor.view().pending_judgment_ids


# --- authority identity ---------------------------------------------------------------


def test_human_fingerprint_and_actor_satisfy_governor_trust_boundary() -> None:
    assert HUMAN_FINGERPRINT.provider == "human"
    assert HUMAN_FINGERPRINT.model == "human://architect"
    assert HUMAN_FINGERPRINT.policy_version == "intent-v2-9p2-unseen-v1"
    assert ARCHITECT_ACTOR == "architect"

    governor = _governor()
    governor.ingest(_evidence("EV-1"))
    judgment = _judgment(
        "J-human",
        CreateAddressProposal(
            candidate=SemanticCandidate(
                candidate_id="CAND-J-human",
                subject="subject ALPHA",
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
    governor = _governor()

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


def test_agree_is_refused_before_any_authority_record_exists() -> None:
    governor = _governor()
    root = _seed_root(governor, key="A")
    _submit_pending_supersede(governor, "J-sup", "J-cl1", "EV-2")
    ledger_length_before = governor.state().last_sequence
    budget = _Budget()

    with pytest.raises(ValueError):
        authorize_root_supersessions(
            governor=governor,
            arm="F",
            t=2,
            root=root,
            pending_judgment_ids=("J-sup",),
            budget=budget,
            clock=lambda: T0,
            id_factory=_counter_id_factory(),
        )

    assert budget.human_authorizations == 0
    assert governor.state().last_sequence == ledger_length_before


# --- exactly one root-target proposal --------------------------------------------------


def test_exact_one_root_target_supersede_is_agreed_with_identical_signature() -> None:
    governor = _governor()
    record_architect_authority(governor, clock=lambda: T0, id_factory=_counter_id_factory())
    root = _seed_root(governor, key="A")
    _submit_pending_supersede(governor, "J-sup", "J-cl1", "EV-2")
    pending = governor.state().semantic.judgments["J-sup"]
    expected_signature = proposal_signature(pending.proposal)
    budget = _Budget()

    records = authorize_root_supersessions(
        governor=governor,
        arm="F",
        t=2,
        root=root,
        pending_judgment_ids=("J-sup",),
        budget=budget,
        clock=lambda: T0,
        id_factory=_counter_id_factory(),
    )

    assert len(records) == 1
    record = records[0]
    assert record.arm == "F"
    assert record.t == 2
    assert record.root_key == "A"
    assert record.target_judgment_id == "J-cl1"
    assert record.outcome is AuthorizationOutcome.AGREED
    assert record.pending_judgment_ids == ("J-sup",)
    assert record.submitted_judgment_id is not None
    assert record.proposal_signature == expected_signature
    assert record.actor_id == "architect"
    assert budget.human_authorizations == 1
    # J-cl1 is no longer live: the human's AGREE superseded it.
    view = governor.view()
    assert "J-cl1" not in view.pending_judgment_ids
    submitted = governor.state().semantic.judgments[record.submitted_judgment_id]
    assert submitted.reasoner == HUMAN_FINGERPRINT
    assert proposal_signature(submitted.proposal) == expected_signature
    assert submitted.proposal == pending.proposal


# --- no-proposal / ambiguous -----------------------------------------------------------


def test_no_pending_proposal_targeting_root_submits_nothing() -> None:
    governor = _governor()
    record_architect_authority(governor, clock=lambda: T0, id_factory=_counter_id_factory())
    root = _seed_root(governor, key="A")
    ledger_length_before = governor.state().last_sequence
    budget = _Budget()

    records = authorize_root_supersessions(
        governor=governor,
        arm="F",
        t=2,
        root=root,
        pending_judgment_ids=(),
        budget=budget,
        clock=lambda: T0,
        id_factory=_counter_id_factory(),
    )

    assert len(records) == 1
    assert records[0].outcome is AuthorizationOutcome.NO_PROPOSAL
    assert records[0].target_judgment_id == "J-cl1"
    assert records[0].pending_judgment_ids == ()
    assert records[0].submitted_judgment_id is None
    assert records[0].proposal_signature is None
    assert budget.human_authorizations == 0
    assert governor.state().last_sequence == ledger_length_before


def test_ambiguous_pending_proposals_targeting_root_submit_nothing() -> None:
    governor = _governor()
    record_architect_authority(governor, clock=lambda: T0, id_factory=_counter_id_factory())
    root = _seed_root(governor, key="B")
    _submit_pending_supersede(governor, "J-sup-x", "J-cl1", "EV-2")
    _submit_pending_supersede(governor, "J-sup-y", "J-cl1", "EV-3")
    ledger_length_before = governor.state().last_sequence
    budget = _Budget()

    records = authorize_root_supersessions(
        governor=governor,
        arm="A",
        t=4,
        root=root,
        pending_judgment_ids=("J-sup-x", "J-sup-y"),
        budget=budget,
        clock=lambda: T0,
        id_factory=_counter_id_factory(),
    )

    assert len(records) == 1
    record = records[0]
    assert record.outcome is AuthorizationOutcome.AMBIGUOUS_PROPOSALS
    assert record.target_judgment_id == "J-cl1"
    assert record.pending_judgment_ids == ("J-sup-x", "J-sup-y")
    assert record.submitted_judgment_id is None
    assert record.proposal_signature is None
    assert budget.human_authorizations == 0
    assert governor.state().last_sequence == ledger_length_before


# --- non-root ---------------------------------------------------------------------------


def test_non_root_supersede_is_never_authorized() -> None:
    governor = _governor()
    record_architect_authority(governor, clock=lambda: T0, id_factory=_counter_id_factory())
    root = _seed_root(governor, key="A")
    governor.ingest(_evidence("EV-OTHER"))
    _apply(governor, _create("J-c2", "EV-OTHER"))
    other_address = address_id_for(PROJECT, "J-c2")
    _apply(governor, _claim("J-cl-other", other_address, "EV-OTHER"))
    _submit_pending_supersede(governor, "J-sup-other", "J-cl-other", "EV-4")
    ledger_length_before = governor.state().last_sequence
    budget = _Budget()

    records = authorize_root_supersessions(
        governor=governor,
        arm="F",
        t=2,
        root=root,
        pending_judgment_ids=("J-sup-other",),
        budget=budget,
        clock=lambda: T0,
        id_factory=_counter_id_factory(),
    )

    assert len(records) == 2
    root_record, non_root_record = records
    assert root_record.outcome is AuthorizationOutcome.NO_PROPOSAL
    assert root_record.target_judgment_id == "J-cl1"
    assert non_root_record.outcome is AuthorizationOutcome.NON_ROOT_NOT_AUTHORIZED
    assert non_root_record.target_judgment_id == "J-cl-other"
    assert non_root_record.pending_judgment_ids == ("J-sup-other",)
    assert non_root_record.submitted_judgment_id is None
    assert budget.human_authorizations == 0
    assert governor.state().last_sequence == ledger_length_before


# --- ceiling ------------------------------------------------------------------------------


def test_16_ceiling_refuses_the_17th_before_any_write() -> None:
    governor = _governor()
    record_architect_authority(governor, clock=lambda: T0, id_factory=_counter_id_factory())
    root = _seed_root(governor, key="A")
    _submit_pending_supersede(governor, "J-sup", "J-cl1", "EV-2")
    budget = _Budget(human_authorizations=MAX_HUMAN_AUTHORIZATIONS)
    ledger_length_before = governor.state().last_sequence

    with pytest.raises(AuthorizationCeilingExceeded):
        authorize_root_supersessions(
            governor=governor,
            arm="F",
            t=2,
            root=root,
            pending_judgment_ids=("J-sup",),
            budget=budget,
            clock=lambda: T0,
            id_factory=_counter_id_factory(),
        )

    assert budget.human_authorizations == MAX_HUMAN_AUTHORIZATIONS
    assert governor.state().last_sequence == ledger_length_before


# --- N is never a checkpoint --------------------------------------------------------------


def test_root_key_n_is_never_an_authority_checkpoint() -> None:
    governor = _governor()
    root = RootDesignation(
        key="N",
        seed_evidence_id="EV-SEED",
        status="UNDESIGNATED",
        address_id=None,
        claim_ids=(),
        creating_judgment_ids=(),
        reason="NO_LIVE_SEED_SUPPORTED_CLAIM",
    )

    with pytest.raises(ValueError):
        authorize_root_supersessions(
            governor=governor,
            arm="F",
            t=2,
            root=root,
            pending_judgment_ids=(),
            budget=_Budget(),
            clock=lambda: T0,
            id_factory=_counter_id_factory(),
        )


# --- no frontier reasoner -------------------------------------------------------------------


def test_no_frontier_reasoner_is_called_by_authority() -> None:
    """Structural (AST) proof: authority.py imports and calls nothing reasoner-shaped.

    Prose in the module's own docstring may legitimately name ``SemanticReasoner`` or
    ``propose_and_submit`` to explain the law it follows; only actual import and call
    nodes are checked here, never comments or docstrings.
    """
    tree = ast.parse(inspect.getsource(authority_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "foundry.ports.semantic_reasoner"
            assert "SemanticReasoner" not in {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            assert "SemanticReasoner" not in {alias.name for alias in node.names}
        elif isinstance(node, ast.Call):
            func = node.func
            called_name = (
                func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            )
            assert called_name not in {"propose", "propose_and_submit"}
