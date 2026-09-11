"""Task 9O-A: the controlled dogfood runner, exercised with fakes only. ZERO live calls.

The runner is not a product CLI. It exists to drive exactly three bounded reasoning
calls over frozen evidence through the real governor, record everything, replay the
ledger without a model, and emit deterministic structural checks. These tests prove
the harness discipline (frozen evidence by commit, hard call budget, failure
preservation, replay verification, artifact hygiene) before any real call is made.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    EquivalentProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.experiments.intent_v2_dogfood import (
    EVIDENCE_SOURCES,
    EXPERIMENT_VERSION,
    MAX_EXTERNAL_MODEL_CALLS,
    PROJECT_ID,
    SCOPE,
    STAGES,
    DogfoodRun,
    load_frozen_evidence,
    render_report,
    run_dogfood,
    write_artifacts,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
FROZEN_SHA = "f" * 40
FINGERPRINT = ReasonerFingerprint(
    provider="xai", model="grok-4.6", policy_version="intent-v2-9o-v1"
)
SECRET = "xai-secret-should-never-appear"


# --------------------------------------------------------------------------- fakes


class FakeGit:
    """Serves evidence bytes for a specific commit only; the working tree is invisible."""

    def __init__(self, contents: dict[str, bytes]) -> None:
        self._contents = contents
        self.requests: list[tuple[str, str]] = []

    def blob(self, sha: str, path: str) -> bytes:
        self.requests.append((sha, path))
        if sha != FROZEN_SHA:
            raise RuntimeError(f"unknown commit {sha}")
        return self._contents[path]

    def blob_sha(self, sha: str, path: str) -> str:
        return hashlib.sha1(b"blob " + self._contents[path]).hexdigest()


class SequencedReasoner:
    """Returns a scripted batch per call; refuses any call beyond its script."""

    def __init__(self, batches: list[Any]) -> None:
        self._batches = batches
        self.requests: list[ReasoningRequest] = []
        self.receipts: tuple[Any, ...] = ()
        self.draft_payloads: tuple[Any, ...] = ()

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return FINGERPRINT

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError("FOURTH CALL ATTEMPTED")
        batch = self._batches[index]
        self.receipts = (*self.receipts, _receipt(index + 1))
        self.draft_payloads = (*self.draft_payloads, {"drafts": [f"draft-{index + 1}"]})
        if isinstance(batch, BaseException):
            raise batch
        if callable(batch):
            return tuple(batch(request))
        return tuple(batch)


def _receipt(n: int) -> Any:
    from foundry.adapters.semantics.xai_reasoner import SemanticReasoningReceipt

    return SemanticReasoningReceipt(
        invocation_id=f"INV-{n:03d}",
        model="grok-4.6",
        reasoning_effort="high",
        input_tokens=1000 * n,
        output_tokens=100 * n,
        cost_usd=0.01 * n,
        wall_clock_ms=500 * n,
        draft_count=1,
    )


def _judgment(
    judgment_id: str, proposal: JudgmentProposal, visible: tuple[str, ...]
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT_ID,
        proposal=proposal,
        visible_evidence_ids=visible,
        rationale="scripted",
        reasoner=FINGERPRINT,
        invocation_id="INV-x",
        proposed_at=T0,
    )


def _create(
    judgment_id: str, candidate_id: str, subject: str, evidence: tuple[str, ...]
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(
            candidate=SemanticCandidate(
                candidate_id=candidate_id,
                subject=subject,
                facet="purpose",
                scope=SCOPE,
                evidence_ids=evidence,
            )
        ),
        evidence,
    )


@pytest.fixture
def git() -> FakeGit:
    return FakeGit({path: f"content of {path}\n".encode() for path, _ in EVIDENCE_SOURCES})


@pytest.fixture
def evidence(git: FakeGit) -> tuple[Any, ...]:
    return load_frozen_evidence(git, FROZEN_SHA, observed_at=T0)


def _ids() -> Any:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks):04d}"


def _run(reasoner: SequencedReasoner, evidence: tuple[Any, ...]) -> DogfoodRun:
    return run_dogfood(
        reasoner=reasoner,
        evidence=evidence,
        policy=AdmissionPolicy(),
        clock=lambda: T0,
        id_factory=_ids(),
        frozen_sha=FROZEN_SHA,
        branch="feat/intent-intelligence-v2",
    )


def _happy_batches() -> list[Any]:
    evidence_ids = tuple(f"EV-{i:02d}" for i in range(1, 6))

    def claims(request: ReasoningRequest) -> list[SemanticJudgment]:
        addresses = request.known_addresses
        out = []
        for i, address in enumerate(addresses, start=1):
            out.append(
                _judgment(
                    f"J-claim-{i}",
                    AssertClaimProposal(
                        address_id=address.address_id,
                        predicate="stated_purpose",
                        value=ClaimValue(kind=ClaimValueKind.TEXT, text=f"purpose {i}"),
                        evidence_ids=(evidence_ids[0],),
                        authority=Authority.INFERRED,
                    ),
                    evidence_ids,
                )
            )
        return out

    def reconcile(request: ReasoningRequest) -> list[SemanticJudgment]:
        a, b = request.known_addresses[0], request.known_addresses[1]
        return [
            _judgment(
                "J-eq",
                EquivalentProposal(address_a=a.address_id, address_b=b.address_id),
                evidence_ids,
            )
        ]

    return [
        [
            _create("J-c1", "CAND-1", "constitution", (evidence_ids[0],)),
            _create("J-c2", "CAND-2", "governance", (evidence_ids[2],)),
        ],
        claims,
        reconcile,
    ]


# --------------------------------------------------------------------------- frozen evidence


def test_evidence_sources_are_exactly_the_five_mandated_files() -> None:
    assert [p for p, _ in EVIDENCE_SOURCES] == [
        "FOUNDRY_CONSTITUTION.md",
        "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md",
        "src/foundry/application/semantic_governance.py",
        "src/foundry/domain/semantic_view.py",
        "tests/integration/test_semantic_lifecycle.py",
    ]
    assert [k for _, k in EVIDENCE_SOURCES] == [
        SourceKind.DOCUMENT,
        SourceKind.DOCUMENT,
        SourceKind.CODE,
        SourceKind.CODE,
        SourceKind.TEST,
    ]


def test_evidence_is_read_from_the_frozen_commit_not_the_working_tree(git: FakeGit) -> None:
    frozen = load_frozen_evidence(git, FROZEN_SHA, observed_at=T0)
    assert all(sha == FROZEN_SHA for sha, _ in git.requests)
    assert len(frozen) == 5
    first = frozen[0]
    assert first.repo_path == "FOUNDRY_CONSTITUTION.md"
    assert first.git_blob_sha == git.blob_sha(FROZEN_SHA, first.repo_path)
    assert (
        first.content_sha256 == hashlib.sha256(b"content of FOUNDRY_CONSTITUTION.md\n").hexdigest()
    )
    assert isinstance(first.item, EvidenceItem)
    assert first.item.scope == SCOPE
    assert first.item.project_id == PROJECT_ID
    assert first.item.source_ref == f"git://{FROZEN_SHA}/FOUNDRY_CONSTITUTION.md"


def test_evidence_from_another_commit_is_refused(git: FakeGit) -> None:
    with pytest.raises(RuntimeError, match="unknown commit"):
        load_frozen_evidence(git, "a" * 40, observed_at=T0)


# --------------------------------------------------------------------------- stages


def test_stage_plan_is_the_preregistered_three_calls() -> None:
    assert MAX_EXTERNAL_MODEL_CALLS == 3
    assert [s.name for s in STAGES] == ["discovery", "claims", "reconciliation"]
    assert STAGES[0].allowed_kinds == frozenset({JudgmentKind.CREATE_ADDRESS})
    assert STAGES[1].allowed_kinds == frozenset({JudgmentKind.ASSERT_CLAIM})
    assert STAGES[2].allowed_kinds == frozenset(
        {JudgmentKind.EQUIVALENT, JudgmentKind.DISTINCT, JudgmentKind.CONFLICTS_WITH}
    )


def test_happy_path_runs_exactly_three_bounded_calls(evidence: tuple[Any, ...]) -> None:
    reasoner = SequencedReasoner(_happy_batches())
    run = _run(reasoner, evidence)

    assert run.result.run_status == "COMPLETED"
    assert run.result.actual_external_call_count == 3
    assert len(reasoner.requests) == 3
    # call 1: no known objects, only CREATE_ADDRESS; the model never chose scope
    r1, r2, r3 = reasoner.requests
    assert r1.known_addresses == () and r1.known_claims == ()
    assert r1.allowed_judgment_kinds == frozenset({JudgmentKind.CREATE_ADDRESS})
    assert [e.evidence_id for e in r1.evidence] == [f"EV-{i:02d}" for i in range(1, 6)]
    # call 2: admitted addresses from call 1, no claims, only ASSERT_CLAIM
    assert len(r2.known_addresses) == 2 and r2.known_claims == ()
    assert r2.allowed_judgment_kinds == frozenset({JudgmentKind.ASSERT_CLAIM})
    # call 3: all addresses and live claims, only relations
    assert len(r3.known_addresses) == 2 and len(r3.known_claims) == 2
    assert r3.allowed_judgment_kinds == STAGES[2].allowed_kinds

    s1, s2, s3 = run.result.stages
    assert s1.status == "COMPLETED" and len(s1.addresses_created) == 2
    assert all(a.route is AdmissionRoute.APPLY for a in s1.admissions)
    assert s2.status == "COMPLETED" and len(s2.claims_created) == 2
    assert s3.status == "COMPLETED"
    assert s3.relation_proposals == {"EQUIVALENT": 1, "DISTINCT": 0, "CONFLICTS_WITH": 0}
    # governance was NOT overridden: a single-lens EQUIVALENT waits for a second lens
    assert [a.route for a in s3.admissions] == [AdmissionRoute.REQUIRE_SECOND_LENS]

    outcome = run.result.semantic_outcome
    assert outcome.address_count == 2 and outcome.claim_count == 2
    assert outcome.route_counts["APPLY"] == 4
    assert outcome.route_counts["REQUIRE_SECOND_LENS"] == 1
    assert outcome.pending_second_lens_judgment_ids == ("J-eq",)
    assert run.result.total_input_tokens == 6000
    assert run.result.total_cost_usd == pytest.approx(0.06)


def test_replay_of_the_recorded_ledger_reproduces_state(evidence: tuple[Any, ...]) -> None:
    run = _run(SequencedReasoner(_happy_batches()), evidence)
    assert run.result.replay.status == "REPLAY_MATCH"
    assert run.result.replay.event_count == len(run.ledger)
    assert run.result.replay.event_count == 5 + 2 * (2 + 2 + 1)


def test_structural_checks_all_pass_on_the_happy_path(evidence: tuple[Any, ...]) -> None:
    run = _run(SequencedReasoner(_happy_batches()), evidence)
    names = {c.name for c in run.result.structural_checks}
    assert {
        "every_claim_cites_ingested_evidence",
        "every_relation_references_known_objects",
        "no_non_human_claim_is_canonical",
        "no_material_kind_auto_applied",
        "no_same_model_corroboration",
        "no_address_or_claim_deleted",
        "replay_reproduced_state",
        "external_calls_within_budget",
    } <= names
    assert all(c.passed for c in run.result.structural_checks), run.result.structural_checks


# --------------------------------------------------------------------------- failure discipline


def test_failure_at_call_two_preserves_call_one_and_stops(evidence: tuple[Any, ...]) -> None:
    batches = _happy_batches()
    batches[1] = RuntimeError(f"provider exploded {SECRET}")
    reasoner = SequencedReasoner(batches)
    run = _run(reasoner, evidence)
    assert run.result.run_status == "FAILED"
    assert run.result.actual_external_call_count == 2
    assert len(reasoner.requests) == 2  # call 3 never attempted
    s1, s2, s3 = run.result.stages
    assert s1.status == "COMPLETED" and len(s1.addresses_created) == 2
    assert s2.status == "FAILED" and s2.error is not None and "provider exploded" in s2.error
    assert SECRET not in s2.error
    assert s3.status == "NOT_RUN"
    assert run.result.semantic_outcome.address_count == 2
    assert run.result.replay.status == "REPLAY_MATCH"


def test_zero_addresses_is_a_terminal_empirical_result(evidence: tuple[Any, ...]) -> None:
    reasoner = SequencedReasoner([[], [], []])
    run = _run(reasoner, evidence)
    assert run.result.run_status == "NO_ADDRESSES_PROPOSED"
    assert run.result.actual_external_call_count == 1
    assert [s.status for s in run.result.stages] == ["NO_ADDRESSES_PROPOSED", "NOT_RUN", "NOT_RUN"]


def test_structural_refusal_of_a_batch_is_recorded_not_retried(evidence: tuple[Any, ...]) -> None:
    from foundry.adapters.semantics.xai_reasoner import SemanticOutputError

    batches = _happy_batches()
    batches[2] = SemanticOutputError("model referenced unknown address id(s): ADDR-GHOST")
    run = _run(SequencedReasoner(batches), evidence)
    assert run.result.run_status == "FAILED"
    assert run.result.actual_external_call_count == 3
    assert run.result.stages[2].status == "FAILED"
    assert "ADDR-GHOST" in (run.result.stages[2].error or "")


# --------------------------------------------------------------------------- artifacts


def test_artifacts_are_written_and_contain_no_secret(
    evidence: tuple[Any, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", SECRET)
    run = _run(SequencedReasoner(_happy_batches()), evidence)
    out = tmp_path / "exp"
    write_artifacts(out, run)
    names = sorted(p.name for p in out.iterdir())
    assert names == ["ledger.json", "manifest.json", "report.md", "result.json"]
    for name in names:
        assert SECRET not in (out / name).read_text(encoding="utf-8")

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["experiment_version"] == EXPERIMENT_VERSION
    assert manifest["project_id"] == PROJECT_ID
    assert manifest["frozen_code_sha"] == FROZEN_SHA
    assert manifest["model"] == "grok-4.6"
    assert manifest["reasoning_effort"] == "high"
    assert manifest["store_messages"] is False
    assert manifest["tools_enabled"] is False
    assert manifest["search_enabled"] is False
    assert manifest["max_external_calls"] == 3
    assert len(manifest["evidence"]) == 5
    assert manifest["evidence"][0]["git_blob_sha"] and manifest["evidence"][0]["content_sha256"]
    assert manifest["allowed_kinds"]["discovery"] == ["CREATE_ADDRESS"]
    assert "api_key" not in json.dumps(manifest).lower()

    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["actual_external_call_count"] == 3
    assert result["stages"][0]["structured_model_draft_output"] == {"drafts": ["draft-1"]}

    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    assert len(ledger["events"]) == len(run.ledger)


def test_write_refuses_to_overwrite_a_recorded_run(
    evidence: tuple[Any, ...], tmp_path: Path
) -> None:
    run = _run(SequencedReasoner(_happy_batches()), evidence)
    out = tmp_path / "exp"
    write_artifacts(out, run)
    with pytest.raises(FileExistsError):
        write_artifacts(out, run)


def test_report_is_deterministic_and_unembellished(evidence: tuple[Any, ...]) -> None:
    run = _run(SequencedReasoner(_happy_batches()), evidence)
    report = render_report(run)
    assert report == render_report(run)
    for heading in (
        "# Intent Intelligence v2",
        "## Calls",
        "## Semantic State",
        "## Replay",
        "## Structural Checks",
    ):
        assert heading in report
    for banned in ("succeeded", "beat", "wins", "superior"):
        assert banned not in report.lower()


def test_decimal_claim_values_survive_the_ledger_round_trip(evidence: tuple[Any, ...]) -> None:
    batches = _happy_batches()
    original_claims = batches[1]

    def claims(request: ReasoningRequest) -> list[SemanticJudgment]:
        out = original_claims(request)
        first = out[0]
        proposal = first.proposal
        assert isinstance(proposal, AssertClaimProposal)
        quantified = proposal.model_copy(
            update={
                "value": ClaimValue(
                    kind=ClaimValueKind.QUANTITY, quantity=Decimal("7.5"), unit="day"
                )
            }
        )
        return [first.model_copy(update={"proposal": quantified}), *out[1:]]

    batches[1] = claims
    run = _run(SequencedReasoner(batches), evidence)
    assert run.result.replay.status == "REPLAY_MATCH"
