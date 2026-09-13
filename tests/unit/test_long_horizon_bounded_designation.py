"""Tests for mechanical 12-locus root designation (9P3 T2 brief; spec §10.1).

Every address/claim here is built through a real ``SemanticGovernor`` over an
``InMemoryEventStore``. Wording is deliberately opaque (subject ``SUBJECT_ALPHA``,
predicate ``PREDICATE_ALPHA``): several tests exist to prove ``designate_seed_root``
never reads it. Only the seed evidence ids follow the spec §7 id law
(``EV-O-<locus>01``) because ``designate_t1_roots`` derives them from ``timeline``;
no Orion evidence text appears anywhere in this file. ZERO live calls; sockets are
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
from foundry.experiments.long_horizon_bounded import designation as designation_module
from foundry.experiments.long_horizon_bounded.designation import (
    RootDesignation,
    designate_seed_root,
    designate_t1_roots,
)
from foundry.experiments.long_horizon_bounded.timeline import LOCI, evidence_id

PROJECT = "PROJ-9P3-DESIGNATION-TEST"
T0 = datetime(2026, 9, 13, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="test-v1")
SEED = "EV-SEED"

FORBIDDEN_ATTRIBUTE_READS = frozenset(
    {"predicate", "value", "subject", "facet", "content", "rationale"}
)
ALLOWED_ATTRIBUTE_READS = frozenset({"address_id", "created_by_judgment_id", "effective_evidence"})


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
                subject="SUBJECT_ALPHA",
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
    predicate: str = "PREDICATE_ALPHA",
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


# --- designate_seed_root ----------------------------------------------------------------


def test_zero_seed_supported_claims_is_undesignated() -> None:
    governor = _governor()
    governor.ingest(_evidence(SEED))

    designation = designate_seed_root(governor.state(), locus="A", seed_evidence_id=SEED)

    assert designation == RootDesignation(
        locus="A",
        seed_evidence_id=SEED,
        status="UNDESIGNATED",
        address_id=None,
        claim_ids=(),
        creating_judgment_ids=(),
        reason="NO_LIVE_SEED_SUPPORTED_CLAIM",
    )


def test_one_address_one_seed_supported_claim_is_designated() -> None:
    governor = _governor()
    governor.ingest(_evidence(SEED))
    _apply(governor, _create("J-c1", SEED))
    address_id = address_id_for(PROJECT, "J-c1")
    _apply(governor, _claim("J-cl1", address_id, SEED))
    claim_id = claim_id_for(PROJECT, "J-cl1")

    designation = designate_seed_root(governor.state(), locus="C", seed_evidence_id=SEED)

    assert designation == RootDesignation(
        locus="C",
        seed_evidence_id=SEED,
        status="DESIGNATED",
        address_id=address_id,
        claim_ids=(claim_id,),
        creating_judgment_ids=("J-cl1",),
        reason="DESIGNATED",
    )


def test_three_seed_supported_claims_at_one_address_are_all_designated_sorted() -> None:
    governor = _governor()
    governor.ingest(_evidence(SEED))
    _apply(governor, _create("J-c1", SEED))
    address_id = address_id_for(PROJECT, "J-c1")
    # Three claims at the SAME address with different predicate/value. Representation
    # granularity must not affect grouping -- submitted out of id order on purpose.
    _apply(governor, _claim("J-cl3", address_id, SEED, predicate="PREDICATE_GAMMA", value="3"))
    _apply(governor, _claim("J-cl1", address_id, SEED, predicate="PREDICATE_ALPHA", value="7"))
    _apply(governor, _claim("J-cl2", address_id, SEED, predicate="PREDICATE_BETA", value="9"))

    designation = designate_seed_root(governor.state(), locus="B", seed_evidence_id=SEED)

    expected_claim_ids = tuple(
        sorted(claim_id_for(PROJECT, judgment_id) for judgment_id in ("J-cl1", "J-cl2", "J-cl3"))
    )
    assert designation.status == "DESIGNATED"
    assert designation.address_id == address_id
    assert designation.claim_ids == expected_claim_ids
    assert designation.creating_judgment_ids == ("J-cl1", "J-cl2", "J-cl3")
    assert designation.reason == "DESIGNATED"


def test_seed_supported_claims_spanning_two_addresses_is_undesignated() -> None:
    governor = _governor()
    governor.ingest(_evidence(SEED))
    _apply(governor, _create("J-c1", SEED))
    _apply(governor, _create("J-c2", SEED))
    address_1 = address_id_for(PROJECT, "J-c1")
    address_2 = address_id_for(PROJECT, "J-c2")
    _apply(governor, _claim("J-cl1", address_1, SEED))
    _apply(governor, _claim("J-cl2", address_2, SEED))

    designation = designate_seed_root(governor.state(), locus="L", seed_evidence_id=SEED)

    assert designation == RootDesignation(
        locus="L",
        seed_evidence_id=SEED,
        status="UNDESIGNATED",
        address_id=None,
        claim_ids=(),
        creating_judgment_ids=(),
        reason="MULTIPLE_SEED_SUPPORTED_ADDRESSES",
    )


# --- designate_t1_roots -------------------------------------------------------------------


def test_designate_t1_roots_returns_all_twelve_loci_seeded_by_t1_evidence_ids() -> None:
    governor = _governor()
    seed_b = evidence_id(1, "B")
    assert seed_b == "EV-O-B01"
    governor.ingest(_evidence(seed_b))
    _apply(governor, _create("J-cB", seed_b))
    address_b = address_id_for(PROJECT, "J-cB")
    _apply(governor, _claim("J-b1", address_b, seed_b))

    roots = designate_t1_roots(governor.state())

    assert tuple(roots) == LOCI
    assert len(roots) == 12
    for locus in LOCI:
        assert roots[locus].locus == locus
        assert roots[locus].seed_evidence_id == f"EV-O-{locus}01"
    assert roots["B"].status == "DESIGNATED"
    assert roots["B"].address_id == address_b
    assert roots["B"].claim_ids == (claim_id_for(PROJECT, "J-b1"),)
    assert roots["B"].creating_judgment_ids == ("J-b1",)
    for locus in LOCI:
        if locus == "B":
            continue
        assert roots[locus].status == "UNDESIGNATED"
        assert roots[locus].reason == "NO_LIVE_SEED_SUPPORTED_CLAIM"
        assert roots[locus].address_id is None


# --- structural proofs -----------------------------------------------------------------------


def _attribute_reads(tree: ast.AST) -> set[str]:
    """Attribute names READ (``ast.Load``) anywhere in ``tree``; keyword arguments are not reads."""
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    }


def test_designation_reads_only_ids_addresses_and_effective_evidence() -> None:
    """Structural (AST) proof: designation.py never reads claim wording or values.

    Only attribute *reads* are checked. The three structural attributes named in the
    brief must all be present (the algorithm cannot work without them); the six
    semantic attributes must be absent.
    """
    tree = ast.parse(inspect.getsource(designation_module))
    reads = _attribute_reads(tree)
    assert not (reads & FORBIDDEN_ATTRIBUTE_READS), sorted(reads & FORBIDDEN_ATTRIBUTE_READS)
    assert reads >= ALLOWED_ATTRIBUTE_READS


def test_no_frontier_reasoner_is_called_by_designation() -> None:
    """Structural (AST) proof: designation.py imports and calls nothing reasoner-shaped,
    and never imports the hidden ``expectations`` module."""
    tree = ast.parse(inspect.getsource(designation_module))
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
