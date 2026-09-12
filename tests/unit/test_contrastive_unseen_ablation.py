"""Frozen 9P ablation arm (Arm A; spec §4; T3 brief).

Arm A must reproduce the historical, pre-9P2 model-visible treatment: Call 1 sees
every active in-scope address and NEVER a claim or comparison context; Call 2 sees
exactly the Call-1 decision neighbourhood (never widened by any structural touch,
because there is no comparison context here to widen from). Every ledger here is the
real ``SemanticGovernor`` over an ``InMemoryEventStore``; the only reasoner is a
scripted fake that records the requests it received. ZERO live calls.
"""

from __future__ import annotations

import ast
import json
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path

import pytest

import foundry.experiments.contrastive_unseen.ablation as ablation_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import render_request
from foundry.application.assimilation_context import CANDIDATE_ADDRESS_THRESHOLD
from foundry.application.context_errors import ContextUnsupported
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
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
)
from foundry.experiments.contrastive_unseen.ablation import (
    ABLATION_CALLS_PER_DELTA,
    AblationOutcome,
    assemble_ablation_call1,
    assimilate_ablation_delta,
)
from foundry.ports.semantic_reasoner import ComparisonContext, ReasoningRequest

PROJECT = "PROJ-9P-ABLATION"
SCOPE = "A"
T0 = datetime(2026, 9, 12, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-historical", policy_version="9p-v4")
ARTIFACT = "docs/retention.md"

ADDR_1 = address_id_for(PROJECT, "J-c1")
ADDR_2 = address_id_for(PROJECT, "J-c2")
CLAIM_1 = claim_id_for(PROJECT, "J-cl1")
CLAIM_2 = claim_id_for(PROJECT, "J-cl2")

CALL1_KINDS = frozenset({JudgmentKind.BIND_TO_ADDRESS, JudgmentKind.CREATE_ADDRESS})
CALL2_KINDS = frozenset(
    {
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
        JudgmentKind.CONFLICTS_WITH,
    }
)

type Batch = list[SemanticJudgment] | Callable[[ReasoningRequest], list[SemanticJudgment]]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- fakes ------------------------------------------------------------------------


class ScriptedReasoner:
    """Returns one scripted batch per call, records every request, refuses extra calls."""

    def __init__(
        self, batches: list[Batch | BaseException], fingerprint: ReasonerFingerprint = MODEL
    ) -> None:
        self._batches = batches
        self._fingerprint = fingerprint
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        if callable(batch):
            return tuple(batch(request))
        return tuple(batch)


# --- builders ---------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0 + timedelta(minutes=next(tick))


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


def _evidence(
    evidence_id: str, *, artifact_ref: str = ARTIFACT, supersedes: str | None = None
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=f"Evidence body {evidence_id}.",
        observed_at=T0,
        scope=(SCOPE,),
        artifact_ref=artifact_ref,
        supersedes_evidence_id=supersedes,
    )


def _candidate(candidate_id: str, evidence_id: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=f"subject {candidate_id}",
        facet="retention",
        scope=(SCOPE,),
        evidence_ids=(evidence_id,),
    )


def _judgment(
    judgment_id: str, proposal: JudgmentProposal, *, evidence_id: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(f"CAND-{judgment_id}", evidence_id)),
        evidence_id=evidence_id,
    )


def _bind(judgment_id: str, address_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(
            candidate=_candidate(f"CAND-{judgment_id}", evidence_id), address_id=address_id
        ),
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


def _seed_address(
    governor: SemanticGovernor, judgment_id: str = "J-c1", evidence_id: str = "EV-1"
) -> str:
    governor.ingest(_evidence(evidence_id))
    decision = governor.submit(_create(judgment_id, evidence_id))
    assert decision.route is AdmissionRoute.APPLY
    return address_id_for(PROJECT, judgment_id)


def _seed_address_and_claim(governor: SemanticGovernor) -> None:
    """``ADDR_1`` with one live claim ``CLAIM_1`` (7 days) citing EV-1."""
    _seed_address(governor)
    assert governor.submit(_claim("J-cl1", ADDR_1, "EV-1", "7")).route is AdmissionRoute.APPLY


def _delta_v2() -> tuple[EvidenceItem, ...]:
    return (_evidence("EV-2", supersedes="EV-1"),)


def _address_ids(request: ReasoningRequest) -> list[str]:
    return [address.address_id for address in request.known_addresses]


def _claim_ids(request: ReasoningRequest) -> list[str]:
    return [claim.claim_id for claim in request.known_claims]


def _routes(decisions: tuple[AdmissionDecision, ...]) -> list[AdmissionRoute]:
    return [decision.route for decision in decisions]


# --- Call 1: addresses, never claims, never context ---------------------------------


def test_call_one_sees_addresses_but_zero_claims_and_empty_context() -> None:
    governor = _governor()
    _seed_address(governor)
    reasoner = ScriptedReasoner([[_bind("J-b2", ADDR_1, "EV-2")], []])

    outcome = assimilate_ablation_delta(
        governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE
    )

    call1 = reasoner.requests[0]
    assert call1.project_id == PROJECT
    assert call1.evidence == _delta_v2()
    assert _address_ids(call1) == [ADDR_1]
    assert call1.known_claims == ()
    assert call1.comparison_context == ComparisonContext()
    assert call1.allowed_judgment_kinds == CALL1_KINDS
    assert outcome.calls_made == 2


def test_call_one_never_sees_claims_even_when_a_prior_claim_exists() -> None:
    """Contrast with 9P2 production: a live claim at an active address is invisible
    to Arm A's Call 1, even though the address itself is shown."""
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner([[_bind("J-b2", ADDR_1, "EV-2")], []])

    assimilate_ablation_delta(governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE)

    call1 = reasoner.requests[0]
    assert _address_ids(call1) == [ADDR_1]
    assert call1.known_claims == ()
    assert call1.comparison_context == ComparisonContext()


# --- Call 2: exactly the decision neighbourhood, never widened -----------------------


def test_call_two_sees_only_call_one_decision_neighborhood_claims() -> None:
    governor = _governor()
    _seed_address_and_claim(governor)
    # A second, unrelated address+claim exists and is active/in-scope but is never
    # touched by Call 1's decision.
    governor.ingest(_evidence("EV-9", artifact_ref="docs/other.md"))
    assert governor.submit(_create("J-c2", "EV-9")).route is AdmissionRoute.APPLY
    assert governor.submit(_claim("J-cl2", ADDR_2, "EV-9", "9")).route is AdmissionRoute.APPLY
    reasoner = ScriptedReasoner([[_bind("J-b2", ADDR_1, "EV-2")], []])

    outcome = assimilate_ablation_delta(
        governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE
    )

    call1 = reasoner.requests[0]
    assert set(_address_ids(call1)) == {ADDR_1, ADDR_2}
    call2 = reasoner.requests[1]
    assert _address_ids(call2) == [ADDR_1]
    assert _claim_ids(call2) == [CLAIM_1]
    assert call2.comparison_context == ComparisonContext()
    assert call2.allowed_judgment_kinds == CALL2_KINDS
    assert outcome.neighborhood == (ADDR_1,)


def test_structurally_touched_address_outside_neighborhood_does_not_widen_call_two() -> None:
    """EV-2 supersedes EV-1, and EV-1 is effective evidence of the live claim at
    ``ADDR_1``. Production's contrastive orchestrator would structurally widen Call 2
    to include ``ADDR_1`` and its claim; Arm A has no comparison context to widen
    from, so when Call 1 CREATEs a fresh address instead of binding, Call 2 must see
    only that new address, and its ``known_claims`` must be empty."""
    governor = _governor()
    _seed_address_and_claim(governor)
    reasoner = ScriptedReasoner([[_create("J-c2", "EV-2")], []])

    outcome = assimilate_ablation_delta(
        governor=governor, reasoner=reasoner, delta=_delta_v2(), scope=SCOPE
    )

    assert set(governor.state().semantic.addresses) == {ADDR_1, ADDR_2}
    assert outcome.neighborhood == (ADDR_2,)
    call2 = reasoner.requests[1]
    assert _address_ids(call2) == [ADDR_2]
    assert call2.known_claims == ()
    assert call2.comparison_context == ComparisonContext()


# --- historical wire shape ------------------------------------------------------------


def test_render_request_has_historical_four_key_shape_with_no_comparison_context() -> None:
    governor = _governor()
    _seed_address(governor)
    request = assemble_ablation_call1(
        project_id=governor.project_id, delta=_delta_v2(), state=governor.state(), scope=SCOPE
    )

    rendered = json.loads(render_request(request, include_comparison_context=False))

    assert set(rendered) == {
        "allowed_judgment_kinds",
        "evidence",
        "known_addresses",
        "known_claims",
    }
    assert "comparison_context" not in rendered


# --- exactly two calls; no retry ------------------------------------------------------


def test_success_makes_exactly_two_calls() -> None:
    assert ABLATION_CALLS_PER_DELTA == 2
    governor = _governor()
    delta = (_evidence("EV-1"),)
    reasoner = ScriptedReasoner([[_create("J-c1", "EV-1")], []])

    outcome = assimilate_ablation_delta(
        governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE
    )

    assert isinstance(outcome, AblationOutcome)
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2
    assert set(AblationOutcome.model_fields) == {
        "stage_decisions",
        "neighborhood",
        "pending_supersede_judgment_ids",
        "calls_made",
    }
    assert outcome.pending_supersede_judgment_ids == ()


def test_call_two_exception_propagates_and_call_one_state_is_kept_with_no_retry() -> None:
    governor = _governor()
    delta = (_evidence("EV-1"),)
    reasoner = ScriptedReasoner([[_create("J-c1", "EV-1")], RuntimeError("provider failure")])

    with pytest.raises(RuntimeError, match="provider failure"):
        assimilate_ablation_delta(governor=governor, reasoner=reasoner, delta=delta, scope=SCOPE)

    assert len(reasoner.requests) == 2
    assert reasoner.requests[1].allowed_judgment_kinds == CALL2_KINDS
    state = governor.state()
    assert set(state.semantic.addresses) == {ADDR_1}
    assert state.semantic.applied_judgment_ids == ("J-c1",)


# --- context-limit refusal -------------------------------------------------------------


def test_201_active_in_scope_addresses_refuse_before_first_reasoner_call() -> None:
    governor = _governor()
    assert CANDIDATE_ADDRESS_THRESHOLD == 200
    for i in range(1, CANDIDATE_ADDRESS_THRESHOLD + 2):
        evidence_id = f"EV-SEED-{i}"
        governor.ingest(_evidence(evidence_id))
        decision = governor.submit(_create(f"J-seed-{i}", evidence_id))
        assert decision.route is AdmissionRoute.APPLY
    assert len(governor.state().semantic.addresses) == CANDIDATE_ADDRESS_THRESHOLD + 1
    reasoner = ScriptedReasoner([[], []])

    with pytest.raises(ContextUnsupported, match="UNSUPPORTED_ABOVE_THRESHOLD"):
        assimilate_ablation_delta(
            governor=governor, reasoner=reasoner, delta=(_evidence("EV-OVER"),), scope=SCOPE
        )

    assert reasoner.requests == []
    # The delta was ingested before the refusal (an appended event, never rolled back).
    assert "EV-OVER" in governor.state().semantic.evidence


# --- source law: no contrastive machinery, no answer-key import -----------------------


def test_source_has_no_contrastive_reasoner_no_semantic_matching_no_expectations_import() -> None:
    source = Path(ablation_module.__file__).read_text(encoding="utf-8")
    forbidden_substrings = (
        "XAIContrastiveSemanticReasoner",
        "compile_comparison_context",
        "contrastive_address_ids",
        "difflib",
        "similar",
        "embedding",
    )
    for needle in forbidden_substrings:
        assert needle not in source, f"forbidden name {needle!r} found in ablation.py"

    tree = ast.parse(source, filename=ablation_module.__file__)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "expectations" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "expectations" not in module
            for alias in node.names:
                assert "expectations" not in alias.name

    assert source.count("propose_and_submit(") == 2
    assert "ABLATION_CALLS_PER_DELTA: Final[int] = 2" in source
