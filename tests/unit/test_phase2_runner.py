"""Task 9K2-A deterministic Phase-2 orchestration.

Every test here runs against a FAKE adjudicator and a synthetic sealed tree that
contains no Phase-1 raw output, no Phase-1 execution record, and NO execution
assignment file at all. If the runner ever reached one of those surfaces, these tests
would fail with a missing file rather than pass quietly.

No test in this module reaches OpenAI, xAI, or the sealed hidden judge on disk.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from foundry.domain.gaps import GapKind
from foundry.evaluation.comparative_protocol import (
    AdjudicationState,
    BlindAdjudicationPacket,
    ConceptCriticality,
    ConceptJudgment,
    ExpectedConcept,
    HiddenJudgeBundle,
    HiddenJudgeCase,
    PredictionDisposition,
    PredictionJudgment,
    SystemAdjudication,
)
from foundry.evaluation.experiment_manifest import sha256_bytes
from foundry.evaluation.loader import load_input
from foundry.evaluation.phase2_adjudication import (
    PHASE2_ROOT,
    AdjudicationAttemptStarted,
    BlindPredictionIdentityLeak,
    Phase2OutputManifest,
    attempt_completed_relative,
    attempt_started_relative,
    blind_output_relative,
    create_adjudication_started,
    manifest_relative,
    phase2_canonical_bytes,
    primary_relative,
    record_relative,
)
from foundry.evaluation.phase2_runner import (
    PHASE1_OUTPUT_COMMIT,
    PHASE1_RUNNER_COMMIT,
    PHASE2_RUNNER_MODULE_PATHS,
    AmbiguousInFlightAdjudication,
    Phase1BundleSummary,
    Phase2AlreadyFrozen,
    Phase2Paused,
    Phase2SealViolation,
    Phase2StructuralFailure,
    RawAdjudicationResponse,
    preflight,
    run_phase2,
    verify_phase2_output,
)
from foundry.evaluation.sealed_exam_manifest import (
    canonical_hidden_judge_bytes,
    load_holdout_input_manifest,
)
from foundry.intelligence.comparison import BlindPrediction

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_COMMIT = "2" * 40
SDK_VERSION = "2.9.0"
_T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)

EXPERIMENT_MANIFEST = "evals/comparative/experiment-manifest.json"
HOLDOUT_MANIFEST = "evals/comparative/holdout-inputs.json"


# --------------------------------------------------------------------------- fixtures


_BASE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


@pytest.fixture
def sealed_repo(tmp_path: Path) -> Path:
    """A synthetic Phase-2 tree: real visible holdouts, a synthetic judge, blind outputs.

    The Phase-1 raw tree, the Phase-1 record tree and `execution-assignment.json` are
    deliberately ABSENT. Their absence is the proof that adjudication never reads them.
    """
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "src", root / "src", ignore=_BASE_IGNORE)
    for relative in (
        HOLDOUT_MANIFEST,
        EXPERIMENT_MANIFEST,
        "evals/comparative/protocol/adjudication-mechanism.json",
        "evals/comparative/protocol/semantic-rubric.json",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    shutil.copytree(
        REPO_ROOT / "evals/comparative/holdouts",
        root / "evals/comparative/holdouts",
        ignore=_BASE_IGNORE,
    )
    assert not (root / "evals/comparative/execution-assignment.json").exists()
    assert not (root / "evals/comparative/phase1/raw").exists()

    bundle = _synthetic_judge(root)
    _rewrite_judge_commitment(root, bundle)
    _write_blind_outputs(root, bundle)
    return root


@pytest.fixture
def judge_path(sealed_repo: Path, tmp_path: Path) -> Path:
    """The judge bundle lives OUTSIDE the repository, exactly as it does in production."""
    outside = tmp_path / "sealed" / "hidden-judge.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    bundle = _synthetic_judge(sealed_repo)
    outside.write_bytes(canonical_hidden_judge_bytes(bundle))
    return outside


def _case_ids(root: Path) -> tuple[str, ...]:
    manifest = load_holdout_input_manifest(root / HOLDOUT_MANIFEST)
    return tuple(sorted(case.case_id for case in manifest.cases))


def _first_event_id(root: Path, case_id: str) -> str:
    manifest = load_holdout_input_manifest(root / HOLDOUT_MANIFEST)
    commitment = next(case for case in manifest.cases if case.case_id == case_id)
    return load_input((root / commitment.input_path).parent).events[0].event_id


def _synthetic_judge(root: Path) -> HiddenJudgeBundle:
    """One grounded expected concept per real visible case. Never the sealed judge."""
    cases = tuple(
        HiddenJudgeCase(
            case_id=case_id,
            expected_concepts=(
                ExpectedConcept(
                    concept_id="C-001",
                    semantic_description="a material question remains open",
                    primary_gap_kind=GapKind.MISSING_INFORMATION,
                    criticality=ConceptCriticality.CRITICAL,
                    exact_subject_key="open-question",
                    evidence_event_ids=(_first_event_id(root, case_id),),
                    evidence_basis="the first visible event",
                    materiality_rationale="downstream work cannot proceed without it",
                ),
            ),
        )
        for case_id in _case_ids(root)
    )
    return HiddenJudgeBundle(bundle_version="hidden-judge-v1", cases=cases)


def _rewrite_judge_commitment(root: Path, bundle: HiddenJudgeBundle) -> None:
    path = root / EXPERIMENT_MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["judge_commitment"]["bundle_sha256"] = sha256_bytes(
        canonical_hidden_judge_bytes(bundle)
    )
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _prediction(index: int, description: str = "an open material question") -> BlindPrediction:
    return BlindPrediction(
        prediction_id=f"P-{index:03d}",
        kind=GapKind.MISSING_INFORMATION,
        subject_key=f"subject-{index}",
        description=description,
        source_event_ids=(),
        confidence=0.6,
    )


def _write_blind_outputs(
    root: Path,
    bundle: HiddenJudgeBundle,
    *,
    leaking_case: str | None = None,
) -> None:
    for case in bundle.cases:
        for label in ("SYSTEM-A", "SYSTEM-B"):
            description = "an open material question"
            if leaking_case == case.case_id and label == "SYSTEM-A":
                description = "emitted by the Foundry pipeline"
            target = root / blind_output_relative(case.case_id, label)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "system_label": label,
                        "predictions": [_prediction(1, description).model_dump(mode="json")],
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )


def _blob_reader(root: Path) -> Callable[[str, str], bytes]:
    def read(commit: str, path: str) -> bytes:
        return (root / path).read_bytes()

    return read


def _phase1_verifier(root: Path) -> Callable[..., Phase1BundleSummary]:
    """Stand in for the real Phase-1 bundle verifier. Makes zero model calls."""
    digest = sha256_bytes((root / EXPERIMENT_MANIFEST).read_bytes())

    def verify(**_: Any) -> Phase1BundleSummary:
        return Phase1BundleSummary(
            experiment_manifest_sha256=digest,
            bundle_sha256="a" * 64,
            runner_commit_sha=PHASE1_RUNNER_COMMIT,
            case_count=12,
        )

    return verify


def _clock() -> Callable[[], datetime]:
    counter = {"n": 0}

    def now() -> datetime:
        counter["n"] += 1
        return _T0 + timedelta(seconds=counter["n"])

    return now


_ID_COUNTER = {"n": 0}


def _execution_ids() -> Callable[[], str]:
    def next_id() -> str:
        _ID_COUNTER["n"] += 1
        return f"00000000-0000-4000-8000-{_ID_COUNTER['n']:012d}"

    return next_id


def _kwargs(root: Path, judge: Path, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "repo_root": root,
        "runner_commit_sha": RUNNER_COMMIT,
        "judge_bundle_path": judge,
        "blob_reader": _blob_reader(root),
        "phase1_verifier": _phase1_verifier(root),
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- fake judges


class FakeAdjudicator:
    """Records every packet it is shown. Never reaches a network."""

    def __init__(
        self,
        *,
        failures: dict[str, list[BaseException]] | None = None,
        payload: Callable[[BlindAdjudicationPacket], str] | None = None,
    ) -> None:
        self.packets: list[BlindAdjudicationPacket] = []
        self.failures = failures or {}
        self.payload = payload or _resolved_payload
        self.calls = 0

    def __call__(self, packet: BlindAdjudicationPacket) -> RawAdjudicationResponse:
        self.calls += 1
        self.packets.append(packet)
        queued = self.failures.get(packet.case_id)
        if queued:
            raise queued.pop(0)
        return RawAdjudicationResponse(
            output_text=self.payload(packet),
            provider_response_id="resp_" + packet.case_id,
            input_tokens=100,
            output_tokens=50,
            wall_clock_ms=1234,
        )


def _adjudication(
    packet: BlindAdjudicationPacket,
    label: str,
    predictions: tuple[BlindPrediction, ...],
    *,
    state: AdjudicationState = AdjudicationState.RESOLVED,
) -> SystemAdjudication:
    concept = packet.expected_concepts[0]
    matched = predictions[0]
    return SystemAdjudication(
        case_id=packet.case_id,
        system_label=label,  # type: ignore[arg-type]
        concept_judgments=(
            ConceptJudgment(
                concept_id=concept.concept_id,
                matched_prediction_id=matched.prediction_id,
                semantic_match=True,
                gap_kind_correct=matched.kind is concept.primary_gap_kind,
                state=state,
                rationale="the same underlying unresolved issue",
            ),
        ),
        prediction_judgments=(
            PredictionJudgment(
                prediction_id=matched.prediction_id,
                disposition=PredictionDisposition.MATCHED_EXPECTED,
                state=state,
                rationale="credited match",
            ),
        ),
    )


def _payload(packet: BlindAdjudicationPacket, state: AdjudicationState) -> str:
    return json.dumps(
        {
            "case_id": packet.case_id,
            "system_a": _adjudication(
                packet, "SYSTEM-A", packet.system_a_predictions, state=state
            ).model_dump(mode="json"),
            "system_b": _adjudication(
                packet, "SYSTEM-B", packet.system_b_predictions, state=state
            ).model_dump(mode="json"),
        }
    )


def _resolved_payload(packet: BlindAdjudicationPacket) -> str:
    return _payload(packet, AdjudicationState.RESOLVED)


def _uncertain_payload(packet: BlindAdjudicationPacket) -> str:
    if packet.case_id != "H-003":
        return _resolved_payload(packet)
    return _payload(packet, AdjudicationState.ADJUDICATION_UNCERTAIN)


def _run(root: Path, judge: Path, adjudicator: Any, **overrides: Any) -> Phase2OutputManifest:
    return run_phase2(
        **_kwargs(root, judge),
        adjudicator=adjudicator,
        openai_sdk_version=SDK_VERSION,
        clock=_clock(),
        execution_id_factory=_execution_ids(),
        **overrides,
    )


# --------------------------------------------------------------------------- preflight


def test_preflight_makes_zero_model_calls_and_covers_twelve_cases(
    sealed_repo: Path, judge_path: Path
) -> None:
    report = preflight(**_kwargs(sealed_repo, judge_path), sdk_version=SDK_VERSION)
    assert len(report.case_sequence) == 12
    assert report.blind_output_count == 24
    assert report.adjudication_runner_commit == RUNNER_COMMIT
    assert len(report.packet_digests) == 12
    assert report.phase1_output_commit == PHASE1_OUTPUT_COMMIT


def test_preflight_pins_the_three_phase2_runner_artifacts() -> None:
    assert PHASE2_RUNNER_MODULE_PATHS == (
        "src/foundry/evaluation/phase2_adjudication.py",
        "src/foundry/evaluation/phase2_live.py",
        "src/foundry/evaluation/phase2_runner.py",
    )


def test_preflight_rejects_a_drifted_runner_module(sealed_repo: Path, judge_path: Path) -> None:
    target = sealed_repo / PHASE2_RUNNER_MODULE_PATHS[0]
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    def frozen_reader(commit: str, path: str) -> bytes:
        return (REPO_ROOT / path).read_bytes()

    with pytest.raises(Phase2SealViolation, match="RUNNER FREEZE VIOLATION"):
        preflight(**_kwargs(sealed_repo, judge_path, blob_reader=frozen_reader))


def test_preflight_verifies_the_hidden_judge_commitment_before_any_packet(
    sealed_repo: Path, judge_path: Path
) -> None:
    tampered = json.loads(judge_path.read_text(encoding="utf-8"))
    tampered["cases"][0]["expected_concepts"][0]["semantic_description"] = "changed"
    judge_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(Phase2SealViolation, match="judge"):
        preflight(**_kwargs(sealed_repo, judge_path))


def test_preflight_requires_the_phase1_bundle_to_verify(
    sealed_repo: Path, judge_path: Path
) -> None:
    def broken(**_: Any) -> Phase1BundleSummary:
        raise RuntimeError("phase-1 bundle does not verify")

    with pytest.raises(Phase2SealViolation, match="Phase-1"):
        preflight(**_kwargs(sealed_repo, judge_path, phase1_verifier=broken))


def test_preflight_rejects_a_phase1_bundle_built_on_another_experiment(
    sealed_repo: Path, judge_path: Path
) -> None:
    def mismatched(**_: Any) -> Phase1BundleSummary:
        return Phase1BundleSummary(
            experiment_manifest_sha256="b" * 64,
            bundle_sha256="a" * 64,
            runner_commit_sha=PHASE1_RUNNER_COMMIT,
            case_count=12,
        )

    with pytest.raises(Phase2SealViolation, match="experiment manifest"):
        preflight(**_kwargs(sealed_repo, judge_path, phase1_verifier=mismatched))


def test_preflight_aborts_on_a_blind_prediction_identity_leak(
    sealed_repo: Path, judge_path: Path
) -> None:
    _write_blind_outputs.__call__  # noqa: B018 - keep the helper referenced for readers
    target = sealed_repo / blind_output_relative("H-001", "SYSTEM-A")
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["predictions"][0]["description"] = "produced by the Foundry intent pipeline"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BlindPredictionIdentityLeak, match="IDENTITY LEAK"):
        preflight(**_kwargs(sealed_repo, judge_path))


def test_preflight_requires_both_blind_outputs_for_every_case(
    sealed_repo: Path, judge_path: Path
) -> None:
    (sealed_repo / blind_output_relative("H-005", "SYSTEM-B")).unlink()
    with pytest.raises(Exception, match="blind output"):
        preflight(**_kwargs(sealed_repo, judge_path))


def test_preflight_refuses_when_phase2_output_is_already_frozen(
    sealed_repo: Path, judge_path: Path
) -> None:
    frozen = sealed_repo / manifest_relative()
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_text("{}", encoding="utf-8")
    with pytest.raises(Phase2AlreadyFrozen):
        preflight(**_kwargs(sealed_repo, judge_path))


# --------------------------------------------------------------------------- execution


def test_run_phase2_issues_exactly_one_fresh_call_per_case(
    sealed_repo: Path, judge_path: Path
) -> None:
    adjudicator = FakeAdjudicator()
    manifest = _run(sealed_repo, judge_path, adjudicator)
    assert adjudicator.calls == 12
    assert len(manifest.calls) == 12
    assert len(manifest.attempts) == 12
    assert {packet.case_id for packet in adjudicator.packets} == set(manifest.case_sequence)
    assert len(adjudicator.packets) == len(
        {packet.case_id for packet in adjudicator.packets}
    )


def test_every_packet_shown_to_the_judge_is_blind(
    sealed_repo: Path, judge_path: Path
) -> None:
    adjudicator = FakeAdjudicator()
    _run(sealed_repo, judge_path, adjudicator)
    for packet in adjudicator.packets:
        assert set(packet.model_fields_set) <= {
            "case_id",
            "source_evidence",
            "expected_concepts",
            "system_a_predictions",
            "system_b_predictions",
        }
        serialized = json.dumps(packet.model_dump(mode="json")).lower()
        for banned in ("foundry", "baseline", "grok", "cost_usd", "prompt"):
            assert banned not in serialized


def test_run_phase2_writes_the_started_marker_before_calling_the_provider(
    sealed_repo: Path, judge_path: Path
) -> None:
    seen: list[bool] = []

    class Watcher(FakeAdjudicator):
        def __call__(self, packet: BlindAdjudicationPacket) -> RawAdjudicationResponse:
            attempts = sealed_repo / PHASE2_ROOT / "attempts"
            seen.append(any(attempts.glob("*-started.json")))
            return super().__call__(packet)

    _run(sealed_repo, judge_path, Watcher())
    assert seen and all(seen)


def test_completed_marker_follows_every_started_marker(
    sealed_repo: Path, judge_path: Path
) -> None:
    manifest = _run(sealed_repo, judge_path, FakeAdjudicator())
    attempts = sealed_repo / PHASE2_ROOT / "attempts"
    started = {path.name.removesuffix("-started.json") for path in attempts.glob("*-started.json")}
    completed = {
        path.name.removesuffix("-completed.json") for path in attempts.glob("*-completed.json")
    }
    assert started == completed
    assert started == {attempt.execution_id for attempt in manifest.attempts}


def test_one_immediate_infrastructure_retry_is_allowed(
    sealed_repo: Path, judge_path: Path
) -> None:
    adjudicator = FakeAdjudicator(failures={"H-004": [ConnectionError("transient")]})
    manifest = _run(sealed_repo, judge_path, adjudicator)
    assert adjudicator.calls == 13
    assert manifest.infrastructure_failures == 1
    assert manifest.infrastructure_retries == 1
    retried = next(call for call in manifest.calls if call.case_id == "H-004")
    assert retried.infrastructure_retry_count == 1
    assert len(retried.attempt_execution_ids) == 2


def test_a_second_infrastructure_failure_pauses_instead_of_rerolling(
    sealed_repo: Path, judge_path: Path
) -> None:
    adjudicator = FakeAdjudicator(
        failures={"H-004": [ConnectionError("transient"), TimeoutError("again")]}
    )
    with pytest.raises(Phase2Paused, match="H-004"):
        _run(sealed_repo, judge_path, adjudicator)


def test_resume_completes_only_the_unresolved_case(
    sealed_repo: Path, judge_path: Path
) -> None:
    paused = FakeAdjudicator(
        failures={"H-004": [ConnectionError("transient"), TimeoutError("again")]}
    )
    with pytest.raises(Phase2Paused):
        _run(sealed_repo, judge_path, paused)
    resumed = FakeAdjudicator()
    manifest = _run(sealed_repo, judge_path, resumed, resume=True)
    assert len(manifest.calls) == 12
    assert resumed.calls < 12


def test_a_started_marker_without_a_completion_aborts_the_resume(
    sealed_repo: Path, judge_path: Path
) -> None:
    orphan = "00000000-0000-4000-8000-999999999999"
    create_adjudication_started(
        sealed_repo / attempt_started_relative(orphan),
        AdjudicationAttemptStarted(
            execution_id=orphan, case_id="H-002", attempt_number=1, started_at=_T0
        ),
    )
    with pytest.raises(AmbiguousInFlightAdjudication, match="AMBIGUOUS IN-FLIGHT"):
        _run(sealed_repo, judge_path, FakeAdjudicator(), resume=True)
    assert not (sealed_repo / attempt_completed_relative(orphan)).exists()


def test_schema_invalid_output_stops_and_is_never_repaired(
    sealed_repo: Path, judge_path: Path
) -> None:
    adjudicator = FakeAdjudicator(payload=lambda packet: '{"case_id": "H-001"}')
    with pytest.raises(Phase2StructuralFailure, match="STRUCTURAL FAILURE"):
        _run(sealed_repo, judge_path, adjudicator)
    assert not list((sealed_repo / PHASE2_ROOT / "primary").glob("*.json"))


def test_output_failing_the_frozen_validator_stops_without_a_second_attempt(
    sealed_repo: Path, judge_path: Path
) -> None:
    def bad_one_to_one(packet: BlindAdjudicationPacket) -> str:
        payload = json.loads(_resolved_payload(packet))
        # Credit a concept to a prediction that was never dispositioned MATCHED_EXPECTED.
        payload["system_a"]["prediction_judgments"][0]["disposition"] = "SUPPORTED_EXTRA"
        return json.dumps(payload)

    adjudicator = FakeAdjudicator(payload=bad_one_to_one)
    with pytest.raises(Phase2StructuralFailure):
        _run(sealed_repo, judge_path, adjudicator)
    assert adjudicator.calls == 1


def test_a_mislabelled_system_is_a_structural_failure(
    sealed_repo: Path, judge_path: Path
) -> None:
    def swapped(packet: BlindAdjudicationPacket) -> str:
        payload = json.loads(_resolved_payload(packet))
        payload["system_a"]["system_label"] = "SYSTEM-B"
        return json.dumps(payload)

    with pytest.raises(Phase2StructuralFailure):
        _run(sealed_repo, judge_path, FakeAdjudicator(payload=swapped))


def test_run_phase2_refuses_to_run_twice_over_a_frozen_bundle(
    sealed_repo: Path, judge_path: Path
) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    with pytest.raises(Phase2AlreadyFrozen):
        _run(sealed_repo, judge_path, FakeAdjudicator())


# --------------------------------------------------------------------------- uncertainty


def test_zero_uncertainty_does_not_trigger_human_review(
    sealed_repo: Path, judge_path: Path
) -> None:
    manifest = _run(sealed_repo, judge_path, FakeAdjudicator())
    assert manifest.uncertain_item_count == 0
    assert manifest.human_review_required is False


def test_any_uncertain_item_triggers_human_review_and_is_never_re_asked(
    sealed_repo: Path, judge_path: Path
) -> None:
    adjudicator = FakeAdjudicator(payload=_uncertain_payload)
    manifest = _run(sealed_repo, judge_path, adjudicator)
    assert manifest.uncertain_item_count > 0
    assert manifest.human_review_required is True
    assert adjudicator.calls == 12
    uncertain = next(call for call in manifest.calls if call.case_id == "H-003")
    assert uncertain.uncertain_item_count == 4


# --------------------------------------------------------------------------- manifest


def test_manifest_records_the_frozen_call_contract(
    sealed_repo: Path, judge_path: Path
) -> None:
    manifest = _run(sealed_repo, judge_path, FakeAdjudicator())
    assert manifest.provider == "OpenAI"
    assert manifest.model == "gpt-5.6-sol"
    assert manifest.reasoning_effort == "high"
    assert manifest.api == "Responses"
    assert manifest.store is False
    assert manifest.tools_enabled is False
    assert manifest.conversation_reuse is False
    assert manifest.calls_per_case == 1
    assert manifest.openai_sdk_version == SDK_VERSION
    assert manifest.phase1_output_commit == PHASE1_OUTPUT_COMMIT
    assert manifest.phase1_runner_commit == PHASE1_RUNNER_COMMIT


def test_manifest_carries_no_identity_no_metric_and_no_winner(
    sealed_repo: Path, judge_path: Path
) -> None:
    manifest = _run(sealed_repo, judge_path, FakeAdjudicator())
    payload = manifest.model_dump(mode="json")
    # `runner_artifacts` pins this repository's own module paths, which necessarily
    # contain the package name. Every other field must be free of treatment identity.
    assert all(
        digest["path"].startswith("src/foundry/evaluation/phase2_")
        for digest in payload.pop("runner_artifacts")
    )
    serialized = json.dumps(payload).lower()
    for banned in (
        "foundry",
        "baseline",
        "xai",
        "grok",
        "winner",
        "recall",
        "precision",
        "score",
        "system-a",
        "system-b",
    ):
        assert banned not in serialized


def test_manifest_commits_to_packets_and_results_without_containing_them(
    sealed_repo: Path, judge_path: Path
) -> None:
    manifest = _run(sealed_repo, judge_path, FakeAdjudicator())
    for call in manifest.calls:
        assert len(call.packet_sha256) == 64
        assert call.primary_result_path == primary_relative(call.case_id)
        result = (sealed_repo / call.primary_result_path).read_bytes()
        assert sha256_bytes(result) == call.primary_result_sha256
        assert call.provider_response_id == "resp_" + call.case_id


def test_every_case_has_a_primary_and_a_record_file(
    sealed_repo: Path, judge_path: Path
) -> None:
    manifest = _run(sealed_repo, judge_path, FakeAdjudicator())
    for case_id in manifest.case_sequence:
        assert (sealed_repo / primary_relative(case_id)).exists()
        assert (sealed_repo / record_relative(case_id)).exists()


def test_no_packet_file_is_ever_written(sealed_repo: Path, judge_path: Path) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    written = {path.name for path in (sealed_repo / PHASE2_ROOT).rglob("*.json")}
    assert not any("packet" in name for name in written)
    for path in (sealed_repo / PHASE2_ROOT).rglob("*.json"):
        assert "semantic_description" not in path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- verification


def test_verify_reproduces_every_hash_and_makes_zero_model_calls(
    sealed_repo: Path, judge_path: Path
) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    manifest = verify_phase2_output(**_kwargs(sealed_repo, judge_path))
    assert len(manifest.calls) == 12
    assert manifest.human_review_required is False


def test_verify_rejects_a_mutated_primary_judgment(
    sealed_repo: Path, judge_path: Path
) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    target = sealed_repo / primary_relative("H-001")
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["system_a"]["concept_judgments"][0]["rationale"] = "rewritten after the fact"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Phase2SealViolation, match="H-001"):
        verify_phase2_output(**_kwargs(sealed_repo, judge_path))


def test_verify_rejects_a_mutated_blind_output(sealed_repo: Path, judge_path: Path) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    target = sealed_repo / blind_output_relative("H-002", "SYSTEM-B")
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["predictions"][0]["description"] = "a different claim entirely"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Phase2SealViolation, match="packet"):
        verify_phase2_output(**_kwargs(sealed_repo, judge_path))


def test_verify_rejects_a_judge_bundle_that_no_longer_matches_the_commitment(
    sealed_repo: Path, judge_path: Path
) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    tampered = json.loads(judge_path.read_text(encoding="utf-8"))
    tampered["cases"][0]["expected_concepts"][0]["materiality_rationale"] = "changed"
    judge_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(Phase2SealViolation):
        verify_phase2_output(**_kwargs(sealed_repo, judge_path))


def test_verify_rejects_an_orphaned_attempt_marker(
    sealed_repo: Path, judge_path: Path
) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    orphan = "00000000-0000-4000-8000-888888888888"
    create_adjudication_started(
        sealed_repo / attempt_started_relative(orphan),
        AdjudicationAttemptStarted(
            execution_id=orphan, case_id="H-002", attempt_number=1, started_at=_T0
        ),
    )
    with pytest.raises(Phase2SealViolation, match="attempt"):
        verify_phase2_output(**_kwargs(sealed_repo, judge_path))


def test_verify_rejects_a_record_that_drifted_from_the_manifest(
    sealed_repo: Path, judge_path: Path
) -> None:
    _run(sealed_repo, judge_path, FakeAdjudicator())
    target = sealed_repo / record_relative("H-006")
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["uncertain_item_count"] = 7
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Phase2SealViolation, match="H-006"):
        verify_phase2_output(**_kwargs(sealed_repo, judge_path))


def test_runner_module_never_names_a_contestant_surface() -> None:
    import foundry.evaluation.phase2_runner as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "execution-assignment",
        "load_execution_assignment",
        "CaseExecutionAssignment",
        "foundry_blind_label",
        "baseline_blind_label",
        "ContestantId",
        "phase1/raw",
        "phase1/records",
    ):
        assert forbidden not in source


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any accidental socket use in this module is a test failure, not a slow test."""
    import socket

    def blocked(*_: Any, **__: Any) -> None:
        raise AssertionError("a Phase-2 unit test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    yield


def test_canonical_bytes_of_a_manifest_round_trip(
    sealed_repo: Path, judge_path: Path
) -> None:
    manifest = _run(sealed_repo, judge_path, FakeAdjudicator())
    on_disk = (sealed_repo / manifest_relative()).read_bytes()
    assert on_disk == phase2_canonical_bytes(manifest)
