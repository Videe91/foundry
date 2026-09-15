"""The recording, budgeted, identity-guarded locus reasoner (T2).

Spec §8 (identity gates 4, 5, 8), §10 (guarded construction, drift before a call),
§12 (8 / 0 / 0 / 0 / 0 / 2.00: the 9th call and a third call in one delta are refused
BEFORE forwarding; cost above 2.00 refuses the next call) and §8 L3 (one
``RequestRecord`` bound 1:1 to one ``RequestReferenceSnapshot`` per forwarded call).

No provider, no network, no key: every reasoner here is a scripted fake carrying the
same observable identity attributes as the real adapter classes. The real adapter
classes are never imported for construction; sockets are blocked for the module.
"""

from __future__ import annotations

import ast
import hashlib
import os
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    SemanticOutputError,
    XAIProviderError,
    render_request,
)
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    SemanticAddress,
    SemanticClaim,
)
from foundry.domain.semantic_judgment import JudgmentKind, ReasonerFingerprint, SemanticJudgment
from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.locus_validation import recording as recording_module
from foundry.experiments.locus_validation.protocol import (
    CALLS_PER_DELTA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.recording import (
    BudgetExceeded,
    BudgetSnapshot,
    ExperimentBudget,
    IdentityDrift,
    LocusRecordingReasoner,
    observed_identity,
    require_locus_identity,
)
from foundry.experiments.long_horizon_bounded.runner import RequestReferenceSnapshot
from foundry.ports.semantic_reasoner import (
    ComparisonContext,
    ContextInclusionEdge,
    ContextRelation,
    EvidenceTransitionContext,
    ReasoningRequest,
)

PROJECT = "PROJ-RECORDING-ALPHA"
SCOPE = "SCOPE_ALPHA"
T0 = datetime(2026, 9, 15, tzinfo=UTC)
LOCUS_FINGERPRINT = ReasonerFingerprint(
    provider=PROVIDER, model=MODEL, policy_version=LOCUS_POLICY_VERSION
)


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


class _ScriptedLocusFake:
    """Mirrors the real locus adapter's observable identity: three class-level policy
    attributes and a fingerprint; a scripted ``propose`` that records every forwarded
    request and returns the scripted batch or raises it. Carries no reasoning effort:
    subclasses expose one either as a public attribute or the adapter's private one."""

    policy_version: ClassVar[str] = LOCUS_POLICY_VERSION
    system_instruction: ClassVar[str] = LOCUS_SYSTEM_INSTRUCTION
    include_comparison_context: ClassVar[bool] = True

    def __init__(
        self,
        batches: list[tuple[SemanticJudgment, ...] | BaseException] | None = None,
        *,
        fingerprint: ReasonerFingerprint = LOCUS_FINGERPRINT,
    ) -> None:
        self._batches = batches
        self._fingerprint = fingerprint
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        if self._batches is None:
            return ()
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        return batch


class LocusFake(_ScriptedLocusFake):
    """The locus identity with a public ``reasoning_effort`` attribute."""

    reasoning_effort: ClassVar[str] = REASONING_EFFORT


class UnderscoreEffortFake(_ScriptedLocusFake):
    """Stores the effort the way the frozen adapter does (``_reasoning_effort`` only)."""

    def __init__(self, effort: str) -> None:
        super().__init__()
        self._reasoning_effort = effort


class _Receipt:
    def __init__(self, cost_usd: float) -> None:
        self.cost_usd = cost_usd


class EconomicsFake(LocusFake):
    """A locus fake that, like the adapter, appends one receipt and one draft payload
    per answered call."""

    def __init__(self, costs: list[float]) -> None:
        super().__init__()
        self._costs = costs
        self._receipts: list[_Receipt] = []
        self._payloads: list[str] = []

    @property
    def receipts(self) -> tuple[_Receipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[str, ...]:
        return tuple(self._payloads)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        result = super().propose(request)
        self._receipts.append(_Receipt(self._costs[len(self.requests) - 1]))
        self._payloads.append(f"PAYLOAD-{len(self.requests)}")
        return result


class ContrastiveFake(LocusFake):
    """The historical 9P2 contrastive identity."""

    policy_version: ClassVar[str] = CONTRASTIVE_POLICY_VERSION
    system_instruction: ClassVar[str] = CONTRASTIVE_SYSTEM_INSTRUCTION

    def __init__(self) -> None:
        super().__init__(
            fingerprint=ReasonerFingerprint(
                provider=PROVIDER, model=MODEL, policy_version=CONTRASTIVE_POLICY_VERSION
            )
        )


class HistoricalFake(LocusFake):
    """The historical 9P identity (no comparison context)."""

    policy_version: ClassVar[str] = POLICY_VERSION
    system_instruction: ClassVar[str] = SYSTEM_INSTRUCTION
    include_comparison_context: ClassVar[bool] = False

    def __init__(self) -> None:
        super().__init__(
            fingerprint=ReasonerFingerprint(
                provider=PROVIDER, model=MODEL, policy_version=POLICY_VERSION
            )
        )


# --- request builders ---------------------------------------------------------------


def _request(n: int, *, t: int = 1) -> ReasoningRequest:
    current = f"EV-LV-X{n}-T{t}"
    predecessor = f"EV-LV-X{n}-T{t - 1}"
    evidence = evidence_item(
        evidence_id=current,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"ref://{current}",
        content=f"<CONTENT:{current}>",
        observed_at=T0,
        scope=(SCOPE,),
        artifact_ref=f"artifact/{n}.md",
        supersedes_evidence_id=predecessor,
    )
    address = SemanticAddress(
        address_id=f"ADDR-{n}",
        project_id=PROJECT,
        subject="SUBJECT_ALPHA",
        facet="FACET_ALPHA",
        scope=(SCOPE,),
        created_by_judgment_id=f"J-ADDR-{n}",
    )
    claim = SemanticClaim(
        claim_id=f"CLAIM-{n}",
        project_id=PROJECT,
        address_id=address.address_id,
        predicate="PREDICATE_ALPHA",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="VALUE_ALPHA"),
        evidence_ids=(predecessor,),
        authority=Authority.OBSERVED,
        provenance=Provenance(source_kind=SourceKind.DOCUMENT, source_ref=f"ref://{predecessor}"),
        created_by_judgment_id=f"J-CLAIM-{n}",
    )
    context = ComparisonContext(
        transitions=(
            EvidenceTransitionContext(
                current_evidence_id=current,
                predecessor_evidence_id=predecessor,
                artifact_ref=f"artifact/{n}.md",
                historical_diff="",
                touched_claim_ids=(claim.claim_id,),
                touched_address_ids=(address.address_id,),
                inclusion_edges=(
                    ContextInclusionEdge(
                        source_id=current,
                        relation=ContextRelation.SUPERSEDES,
                        target_id=predecessor,
                    ),
                ),
            ),
        )
    )
    return ReasoningRequest(
        project_id=PROJECT,
        evidence=(evidence,),
        known_addresses=(address,),
        known_claims=(claim,),
        allowed_judgment_kinds=frozenset(
            {JudgmentKind.SUPERSEDE, JudgmentKind.ASSERT_CLAIM, JudgmentKind.CREATE_ADDRESS}
        ),
        comparison_context=context,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _wrapped(
    inner: LocusFake | None = None, *, budget: ExperimentBudget | None = None
) -> tuple[LocusRecordingReasoner, LocusFake, ExperimentBudget]:
    fake = inner if inner is not None else LocusFake()
    shared = budget if budget is not None else ExperimentBudget()
    return LocusRecordingReasoner(fake, ledger="alpha", budget=shared), fake, shared


# --- observed identity ---------------------------------------------------------------


def test_observed_identity_reads_every_frozen_field_from_the_instance() -> None:
    observed = observed_identity(LocusFake())
    assert observed == {
        "provider": PROVIDER,
        "model": MODEL,
        "fingerprint_policy_version": LOCUS_POLICY_VERSION,
        "policy_version": LOCUS_POLICY_VERSION,
        "system_prompt_sha256": LOCUS_SYSTEM_INSTRUCTION_SHA256,
        "include_comparison_context": True,
        "reasoning_effort": REASONING_EFFORT,
    }


def test_observed_identity_reads_the_adapter_style_underscore_effort() -> None:
    assert observed_identity(UnderscoreEffortFake("low"))["reasoning_effort"] == "low"


def test_observed_identity_is_instance_resolved() -> None:
    fake = LocusFake()
    fake.system_instruction = LOCUS_SYSTEM_INSTRUCTION + "\nTAMPERED"  # type: ignore[misc]
    observed = observed_identity(fake)
    assert observed["system_prompt_sha256"] == _sha256(LOCUS_SYSTEM_INSTRUCTION + "\nTAMPERED")
    assert observed["system_prompt_sha256"] != LOCUS_SYSTEM_INSTRUCTION_SHA256


def test_require_locus_identity_accepts_the_locus_identity() -> None:
    require_locus_identity(LocusFake())
    require_locus_identity(UnderscoreEffortFake(REASONING_EFFORT))


# --- construction-time refusal --------------------------------------------------------


def _tampered_instruction() -> LocusFake:
    fake = LocusFake()
    fake.system_instruction = LOCUS_SYSTEM_INSTRUCTION + "\nTAMPERED"  # type: ignore[misc]
    return fake


def _wrong_model() -> LocusFake:
    return LocusFake(
        fingerprint=ReasonerFingerprint(
            provider=PROVIDER, model="grok-3", policy_version=LOCUS_POLICY_VERSION
        )
    )


def _wrong_provider() -> LocusFake:
    return LocusFake(
        fingerprint=ReasonerFingerprint(
            provider="fake", model=MODEL, policy_version=LOCUS_POLICY_VERSION
        )
    )


def _wrong_effort() -> LocusFake:
    fake = LocusFake()
    fake.reasoning_effort = "low"  # type: ignore[misc]
    return fake


def _no_comparison_context() -> LocusFake:
    fake = LocusFake()
    fake.include_comparison_context = False  # type: ignore[misc]
    return fake


def _fingerprint_policy_only_drift() -> LocusFake:
    return LocusFake(
        fingerprint=ReasonerFingerprint(
            provider=PROVIDER, model=MODEL, policy_version=CONTRASTIVE_POLICY_VERSION
        )
    )


@pytest.mark.parametrize(
    ("label", "build"),
    [
        ("9p2-v1", ContrastiveFake),
        ("9p-v4", HistoricalFake),
        ("tampered-instruction", _tampered_instruction),
        ("wrong-model", _wrong_model),
        ("wrong-provider", _wrong_provider),
        ("wrong-effort", _wrong_effort),
        ("no-comparison-context", _no_comparison_context),
        ("fingerprint-policy-drift", _fingerprint_policy_only_drift),
        ("no-effort-exposed", _ScriptedLocusFake),
    ],
)
def test_construction_refuses_a_non_locus_identity(label: str, build: Any) -> None:
    fake = build()
    with pytest.raises(IdentityDrift):
        LocusRecordingReasoner(fake, ledger="alpha", budget=ExperimentBudget())
    assert fake.requests == [], label


def test_require_locus_identity_names_the_drifted_field() -> None:
    with pytest.raises(IdentityDrift, match="system_prompt_sha256"):
        require_locus_identity(_tampered_instruction())
    with pytest.raises(IdentityDrift, match="model"):
        require_locus_identity(_wrong_model())
    with pytest.raises(IdentityDrift, match="reasoning_effort"):
        require_locus_identity(_wrong_effort())


# --- per-call drift ----------------------------------------------------------------------


def test_drift_after_construction_is_refused_before_forwarding() -> None:
    wrapper, fake, budget = _wrapped()
    wrapper.begin_delta(1)
    fake.system_instruction = CONTRASTIVE_SYSTEM_INSTRUCTION  # type: ignore[misc]
    with pytest.raises(IdentityDrift):
        wrapper.propose(_request(1))
    assert fake.requests == []
    assert budget.frontier_calls == 0
    assert wrapper.records == ()
    assert wrapper.snapshots == ()


def test_drift_check_precedes_every_ceiling_check() -> None:
    wrapper, fake, budget = _wrapped()
    fake.reasoning_effort = "low"  # type: ignore[misc]
    with pytest.raises(IdentityDrift):
        wrapper.propose(_request(1))  # no delta begun either: identity is checked first
    assert fake.requests == []
    assert budget.frontier_calls == 0


# --- budget object -----------------------------------------------------------------------


def test_budget_starts_at_zero_and_snapshots_as_a_frozen_document() -> None:
    budget = ExperimentBudget()
    assert budget.frontier_calls == 0
    assert budget.provider_cost_usd == Decimal("0")
    assert budget.judge_calls == 0
    assert budget.human_authorizations == 0
    snapshot = budget.snapshot()
    assert isinstance(snapshot, BudgetSnapshot)
    assert snapshot == BudgetSnapshot(
        frontier_calls=0, provider_cost_usd="0", judge_calls=0, human_authorizations=0
    )
    with pytest.raises(Exception):  # noqa: B017 - FrozenModel refuses assignment
        snapshot.frontier_calls = 1  # type: ignore[misc]


def test_budget_has_no_judge_or_authorization_mutator() -> None:
    public = {name for name in dir(ExperimentBudget) if not name.startswith("_")}
    assert public == {"snapshot"}
    wrapper_public = {name for name in dir(LocusRecordingReasoner) if not name.startswith("_")}
    assert not any("judge" in name or "authoriz" in name for name in wrapper_public)


# --- ceilings before forwarding ------------------------------------------------------------


def test_propose_before_begin_delta_is_refused_before_forwarding() -> None:
    wrapper, fake, budget = _wrapped()
    with pytest.raises(BudgetExceeded, match="NO_DELTA_BEGUN"):
        wrapper.propose(_request(1))
    assert fake.requests == []
    assert budget.frontier_calls == 0


def test_third_call_in_one_delta_is_refused_before_forwarding() -> None:
    wrapper, fake, budget = _wrapped()
    wrapper.begin_delta(1)
    wrapper.propose(_request(1))
    wrapper.propose(_request(2))
    with pytest.raises(BudgetExceeded, match="THIRD_CALL_REFUSED"):
        wrapper.propose(_request(3))
    assert len(fake.requests) == CALLS_PER_DELTA == 2
    assert budget.frontier_calls == 2
    assert [record.call_number for record in wrapper.records] == [1, 2]


def test_begin_delta_resets_the_per_delta_counter() -> None:
    wrapper, fake, _budget = _wrapped()
    wrapper.begin_delta(1)
    wrapper.propose(_request(1, t=1))
    wrapper.propose(_request(2, t=1))
    wrapper.begin_delta(2)
    wrapper.propose(_request(1, t=2))
    wrapper.propose(_request(2, t=2))
    assert len(fake.requests) == 4
    assert [(record.t, record.call_number) for record in wrapper.records] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (2, 2),
    ]


def test_ninth_call_is_refused_before_forwarding() -> None:
    budget = ExperimentBudget()
    alpha, alpha_fake, _ = _wrapped(budget=budget)
    beta_fake = LocusFake()
    beta = LocusRecordingReasoner(beta_fake, ledger="beta", budget=budget)
    for wrapper in (alpha, beta):
        for t in (1, 2):
            wrapper.begin_delta(t)
            wrapper.propose(_request(1, t=t))
            wrapper.propose(_request(2, t=t))
    assert budget.frontier_calls == MAX_FRONTIER_CALLS == 8
    beta.begin_delta(3)
    with pytest.raises(BudgetExceeded, match="FRONTIER_CEILING"):
        beta.propose(_request(9, t=3))
    assert len(alpha_fake.requests) + len(beta_fake.requests) == 8
    assert budget.frontier_calls == 8
    assert len(alpha.records) + len(beta.records) == 8


def test_frontier_ceiling_check_precedes_the_per_delta_check() -> None:
    budget = ExperimentBudget()
    budget.frontier_calls = MAX_FRONTIER_CALLS
    wrapper, fake, _ = _wrapped(budget=budget)
    with pytest.raises(BudgetExceeded, match="FRONTIER_CEILING"):
        wrapper.propose(_request(1))
    assert fake.requests == []


def test_cost_above_the_ceiling_refuses_the_next_call_before_forwarding() -> None:
    fake = EconomicsFake([2.01, 0.05])
    wrapper, _, budget = _wrapped(fake)
    wrapper.begin_delta(1)
    wrapper.propose(_request(1))
    assert budget.provider_cost_usd == Decimal("2.01")
    assert budget.provider_cost_usd > Decimal(str(MAX_COST_USD))
    with pytest.raises(BudgetExceeded, match="COST_CEILING"):
        wrapper.propose(_request(2))
    assert len(fake.requests) == 1
    assert budget.frontier_calls == 1
    assert len(wrapper.records) == 1


def test_cost_exactly_at_the_ceiling_does_not_refuse() -> None:
    fake = EconomicsFake([1.5, 0.5, 0.01])
    wrapper, _, budget = _wrapped(fake)
    wrapper.begin_delta(1)
    wrapper.propose(_request(1))
    wrapper.propose(_request(2))
    assert budget.provider_cost_usd == Decimal("2.00")
    wrapper.begin_delta(2)
    wrapper.propose(_request(3, t=2))
    assert len(fake.requests) == 3
    assert budget.provider_cost_usd == Decimal("2.01")


def test_cost_is_accumulated_as_exact_decimals() -> None:
    fake = EconomicsFake([0.1, 0.2])
    wrapper, _, budget = _wrapped(fake)
    wrapper.begin_delta(1)
    wrapper.propose(_request(1))
    wrapper.propose(_request(2))
    assert budget.provider_cost_usd == Decimal("0.3")
    assert budget.snapshot().provider_cost_usd == "0.3"


# --- record and snapshot capture --------------------------------------------------------------


def test_each_forwarded_call_yields_one_record_bound_to_one_snapshot() -> None:
    wrapper, fake, budget = _wrapped()
    wrapper.begin_delta(1)
    first = _request(1)
    second = _request(2)
    wrapper.propose(first)
    wrapper.propose(second)
    assert fake.requests[0] is first
    assert fake.requests[1] is second
    assert len(wrapper.records) == len(wrapper.snapshots) == 2
    for request, record, snapshot, call_number in zip(
        (first, second), wrapper.records, wrapper.snapshots, (1, 2), strict=True
    ):
        assert isinstance(record, RequestRecord)
        assert isinstance(snapshot, RequestReferenceSnapshot)
        assert record.arm == snapshot.arm == "F"
        assert record.t == snapshot.t == 1
        assert record.call_number == snapshot.call_number == call_number
        assert record.request_sha256 == snapshot.request_sha256
        assert record.citable_evidence_ids == snapshot.citable_evidence_ids
        assert record.known_address_ids == snapshot.known_address_ids
        assert record.known_claim_ids == snapshot.known_claim_ids
        assert snapshot.citable_evidence_ids == tuple(e.evidence_id for e in request.evidence)
        assert snapshot.known_address_ids == tuple(a.address_id for a in request.known_addresses)
        assert snapshot.known_claim_ids == tuple(c.claim_id for c in request.known_claims)
        assert snapshot.known_claim_creating_judgment_ids == tuple(
            c.created_by_judgment_id for c in request.known_claims
        )
    assert budget.frontier_calls == 2


def test_record_carries_the_exact_rendered_request_and_locus_identity() -> None:
    wrapper, _, _ = _wrapped()
    wrapper.begin_delta(2)
    request = _request(4, t=2)
    wrapper.propose(request)
    (record,) = wrapper.records
    rendered = render_request(request, include_comparison_context=True)
    assert record.rendered_user_request == rendered
    assert record.rendered_user_request != render_request(request)
    assert record.request_sha256 == _sha256(rendered)
    assert record.policy_version == LOCUS_POLICY_VERSION
    assert record.system_prompt_sha256 == LOCUS_SYSTEM_INSTRUCTION_SHA256
    assert record.t == 2
    assert record.citable_evidence_ids == ("EV-LV-X4-T2",)
    assert record.historical_comparison_evidence_ids == ("EV-LV-X4-T1",)
    assert record.known_address_ids == ("ADDR-4",)
    assert record.known_claim_ids == ("CLAIM-4",)
    assert record.allowed_judgment_kinds == ("ASSERT_CLAIM", "CREATE_ADDRESS", "SUPERSEDE")
    assert record.comparison_context_chars > 0
    assert '"comparison_context"' in record.rendered_user_request


def test_judgments_are_returned_unchanged() -> None:
    sentinel: tuple[SemanticJudgment, ...] = ()
    fake = LocusFake([sentinel])
    wrapper, _, _ = _wrapped(fake)
    wrapper.begin_delta(1)
    assert wrapper.propose(_request(1)) is sentinel


def test_provider_error_leaves_no_record_no_snapshot_and_counts_the_admitted_call() -> None:
    error = XAIProviderError("PROVIDER_FAILURE_ALPHA")
    fake = LocusFake([error])
    wrapper, _, budget = _wrapped(fake)
    wrapper.begin_delta(1)
    with pytest.raises(XAIProviderError) as info:
        wrapper.propose(_request(1))
    assert info.value is error
    assert len(fake.requests) == 1
    assert wrapper.records == ()
    assert wrapper.snapshots == ()
    assert budget.frontier_calls == 1


def test_model_contract_error_is_re_raised_unchanged() -> None:
    error = SemanticOutputError("OUTPUT_FAILURE_ALPHA")
    fake = LocusFake([error])
    wrapper, _, budget = _wrapped(fake)
    wrapper.begin_delta(1)
    with pytest.raises(SemanticOutputError) as info:
        wrapper.propose(_request(1))
    assert info.value is error
    assert wrapper.records == ()
    assert budget.frontier_calls == 1


# --- pass-through ----------------------------------------------------------------------------


def test_fingerprint_ledger_and_economics_pass_through() -> None:
    fake = EconomicsFake([0.01, 0.02])
    wrapper, _, _ = _wrapped(fake)
    assert wrapper.fingerprint == LOCUS_FINGERPRINT
    assert wrapper.ledger == "alpha"
    assert wrapper.inner is fake
    assert wrapper.receipts == ()
    assert wrapper.draft_payloads == ()
    wrapper.begin_delta(1)
    wrapper.propose(_request(1))
    assert wrapper.receipts == fake.receipts
    assert wrapper.draft_payloads == ("PAYLOAD-1",)


def test_reasoner_without_economics_exposes_empty_tuples() -> None:
    wrapper, _, _ = _wrapped()
    wrapper.begin_delta(1)
    wrapper.propose(_request(1))
    assert wrapper.receipts == ()
    assert wrapper.draft_payloads == ()


# --- request-path hygiene ----------------------------------------------------------------------


def test_recording_never_imports_the_answer_key_or_a_grading_module() -> None:
    tree = ast.parse(Path(recording_module.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    package = "foundry.experiments.locus_validation."
    for name in ("expectations", "evaluation", "leakage", "integrity", "artifacts"):
        assert package + name not in mods, name
    assert "foundry.experiments.locus_validation.protocol" in mods
    assert "foundry.experiments.contrastive_unseen.records" in mods
    assert "foundry.experiments.long_horizon_bounded.runner" in mods
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "RecordingReasoner" not in names
    assert "BudgetedReasoner" not in names
