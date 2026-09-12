"""Tests for mechanical Kestrel root designation (9P2 unseen-lifecycle T2 brief; spec §7).

Every address/claim here is built through a real ``SemanticGovernor`` over an
``InMemoryEventStore`` -- the same idiom as ``tests/unit/test_incremental_assimilation.py``.
Wording is deliberately opaque (subject ALPHA/BETA, predicate ``retention_period``): the
point of several tests is that ``designate_seed_root`` never looks at it. ZERO live calls;
sockets are blocked.
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
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.experiments.contrastive_unseen import designation as designation_module
from foundry.experiments.contrastive_unseen.designation import RootDesignation, designate_seed_root

PROJECT = "PROJ-9P2-DESIGNATION-TEST"
T0 = datetime(2026, 9, 12, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="test-v1")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


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


def _judgment(judgment_id: str, proposal: JudgmentProposal, evidence_id: str) -> SemanticJudgment:
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


def _claim(
    judgment_id: str,
    address_id: str,
    evidence_id: str,
    *,
    predicate: str = "retention_period",
    value: str = "7",
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate=predicate,
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(value), unit="day"),
            evidence_ids=(evidence_id,),
            authority=Authority.OBSERVED,
        ),
        evidence_id,
    )


def _apply(governor: SemanticGovernor, judgment: SemanticJudgment) -> None:
    decision = governor.submit(judgment)
    assert decision.route is AdmissionRoute.APPLY


# --- designation ----------------------------------------------------------------------


def test_zero_seed_supported_claims_is_undesignated() -> None:
    governor = _governor()
    governor.ingest(_evidence("EV-SEED"))

    designation = designate_seed_root(governor.state(), key="A", seed_evidence_id="EV-SEED")

    assert designation == RootDesignation(
        key="A",
        seed_evidence_id="EV-SEED",
        status="UNDESIGNATED",
        address_id=None,
        claim_ids=(),
        creating_judgment_ids=(),
        reason="NO_LIVE_SEED_SUPPORTED_CLAIM",
    )


def test_one_address_one_seed_supported_claim_is_designated() -> None:
    governor = _governor()
    governor.ingest(_evidence("EV-SEED"))
    _apply(governor, _create("J-c1", "EV-SEED"))
    address_id = address_id_for(PROJECT, "J-c1")
    _apply(governor, _claim("J-cl1", address_id, "EV-SEED"))
    claim_id = claim_id_for(PROJECT, "J-cl1")

    designation = designate_seed_root(governor.state(), key="A", seed_evidence_id="EV-SEED")

    assert designation.key == "A"
    assert designation.seed_evidence_id == "EV-SEED"
    assert designation.status == "DESIGNATED"
    assert designation.address_id == address_id
    assert designation.claim_ids == (claim_id,)
    assert designation.creating_judgment_ids == ("J-cl1",)


def test_multiple_seed_supported_claims_at_one_address_are_all_designated_sorted() -> None:
    governor = _governor()
    governor.ingest(_evidence("EV-SEED"))
    _apply(governor, _create("J-c1", "EV-SEED"))
    address_id = address_id_for(PROJECT, "J-c1")
    # Two claims at the SAME address with different predicate/value/wording. Representation
    # granularity (spec §6) must not affect grouping -- submitted out of id order on purpose.
    _apply(
        governor, _claim("J-cl2", address_id, "EV-SEED", predicate="retention_period", value="7")
    )
    _apply(
        governor, _claim("J-cl1", address_id, "EV-SEED", predicate="another_predicate", value="9")
    )

    designation = designate_seed_root(governor.state(), key="B", seed_evidence_id="EV-SEED")

    claim_1 = claim_id_for(PROJECT, "J-cl1")
    claim_2 = claim_id_for(PROJECT, "J-cl2")
    assert designation.status == "DESIGNATED"
    assert designation.address_id == address_id
    assert designation.claim_ids == tuple(sorted((claim_1, claim_2)))
    assert designation.creating_judgment_ids == ("J-cl1", "J-cl2")


def test_seed_supported_claims_spanning_two_addresses_is_undesignated() -> None:
    governor = _governor()
    governor.ingest(_evidence("EV-SEED"))
    _apply(governor, _create("J-c1", "EV-SEED"))
    _apply(governor, _create("J-c2", "EV-SEED"))
    address_1 = address_id_for(PROJECT, "J-c1")
    address_2 = address_id_for(PROJECT, "J-c2")
    _apply(governor, _claim("J-cl1", address_1, "EV-SEED"))
    _apply(governor, _claim("J-cl2", address_2, "EV-SEED"))

    designation = designate_seed_root(governor.state(), key="N", seed_evidence_id="EV-SEED")

    assert designation == RootDesignation(
        key="N",
        seed_evidence_id="EV-SEED",
        status="UNDESIGNATED",
        address_id=None,
        claim_ids=(),
        creating_judgment_ids=(),
        reason="MULTIPLE_SEED_SUPPORTED_ADDRESSES",
    )


def test_no_frontier_reasoner_is_called_by_designation() -> None:
    """Structural (AST) proof: designation.py imports and calls nothing reasoner-shaped.

    Prose in the module's own docstring may legitimately name ``SemanticReasoner`` or
    ``propose_and_submit`` to explain the law it follows; only actual import and call
    nodes are checked here, never comments or docstrings.
    """
    tree = ast.parse(inspect.getsource(designation_module))
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
