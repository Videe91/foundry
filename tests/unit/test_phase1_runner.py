"""Task 9K1-A deterministic Phase-1 orchestration.

Every test here runs against FAKE contestants and a copied sealed exam tree. No test
in this module reaches xAI, OpenAI, or any other provider, and none of them reaches
the hidden judge.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import foundry.evaluation.phase1_runner as phase1_runner
from foundry.domain.gaps import GapKind
from foundry.evaluation.phase1_execution import (
    AttemptOutcome,
    Phase1ExecutionRecord,
    Phase1OutputManifest,
    Phase1TerminalStatus,
    phase1_canonical_bytes,
)
from foundry.evaluation.phase1_runner import (
    RUNNER_MODULE_PATHS,
    AmbiguousInFlightAttempt,
    Phase1Abort,
    Phase1AlreadyFrozen,
    Phase1Paused,
    Phase1SealViolation,
    classify_exception,
    preflight,
    run_phase1,
    verify_phase1_output,
)
from foundry.evaluation.sealed_exam_manifest import ContestantId
from foundry.intelligence.baseline import BaselineGap, BaselinePayload, BaselineResult
from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.proposals import (
    GapProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
    RequirementProposal,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_COMMIT = "1" * 40
_T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)

CASE_SEQUENCE: tuple[str, ...] = (
    "H-011",
    "H-002",
    "H-003",
    "H-001",
    "H-007",
    "H-010",
    "H-008",
    "H-006",
    "H-004",
    "H-012",
    "H-005",
    "H-009",
)

AUDIT_PATH = "evals/comparative/audit/9j3-pre-exam-audit.json"
ASSIGNMENT_PATH = "evals/comparative/execution-assignment.json"
PHASE1 = "evals/comparative/phase1"


# --------------------------------------------------------------------------- fixtures


_BASE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")
_COMPARATIVE_ROOT = (REPO_ROOT / "evals" / "comparative").resolve()


def _sealed_repo_ignore(path: str, names: list[str]) -> set[str]:
    """Copy the sealed exam faithfully, minus the frozen Phase-1 output bundle.

    `sealed_repo` must represent the repository *before* Phase-1 executed. Only
    `REPO_ROOT/evals/comparative/phase1` is excluded; a directory named `phase1`
    anywhere else is copied normally.
    """
    ignored = set(_BASE_IGNORE(path, names))
    if Path(path).resolve() == _COMPARATIVE_ROOT and "phase1" in names:
        ignored.add("phase1")
    return ignored


@pytest.fixture
def sealed_repo(tmp_path: Path) -> Path:
    """A pre-Phase-1 copy of the sealed exam tree, isolated from the hidden judge."""
    root = tmp_path / "repo"
    root.mkdir()
    for tree in ("src", "evals", "docs"):
        shutil.copytree(REPO_ROOT / tree, root / tree, ignore=_sealed_repo_ignore)
    return root


def _blob_reader(root: Path) -> Callable[[str, str], bytes]:
    """Stand in for `git show <commit>:<path>` using the copied working tree."""

    def read(commit: str, path: str) -> bytes:
        return (root / path).read_bytes()

    return read


def _clock() -> Callable[[], datetime]:
    counter = {"n": 0}

    def now() -> datetime:
        counter["n"] += 1
        return _T0 + timedelta(seconds=counter["n"])

    return now


_ID_COUNTER = {"n": 0}


def _execution_ids() -> Callable[[], str]:
    """Monotonic across the whole session: a resume must never reuse an attempt id."""

    def next_id() -> str:
        _ID_COUNTER["n"] += 1
        return f"00000000-0000-4000-8000-{_ID_COUNTER['n']:012d}"

    return next_id


def _usage() -> IntelligenceUsage:
    return IntelligenceUsage(
        frontier_model_jobs=1,
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.1,
        wall_clock_ms=1000,
    )


def foundry_ok() -> IntentIntelligenceResult:
    return IntentIntelligenceResult(
        payload=IntentIntelligencePayload(
            semantic_proposals=(
                RequirementProposal(
                    proposal_id="S-1",
                    confidence=0.6,
                    statement="internal-foundry-only-semantic-statement",
                ),
            ),
            gap_proposals=(
                GapProposal(
                    proposal_id="internal-foundry-gap-id",
                    kind=GapKind.MISSING_INFORMATION,
                    subject_key="alpha-subject",
                    description="alpha description",
                    blocking=True,
                    confidence=0.7,
                ),
            ),
        ),
        usage=_usage(),
    )


def foundry_empty() -> IntentIntelligenceResult:
    return IntentIntelligenceResult(
        payload=IntentIntelligencePayload(), usage=_usage()
    )


def foundry_invalid() -> IntentIntelligenceResult:
    return IntentIntelligenceResult(
        payload=IntentIntelligencePayload(
            gap_proposals=(
                GapProposal(
                    proposal_id="G-1",
                    kind=GapKind.AMBIGUITY,
                    subject_key="Not_Kebab_Case",
                    description="structurally invalid subject key",
                    blocking=False,
                    confidence=0.5,
                ),
            )
        ),
        usage=_usage(),
    )


def baseline_ok() -> BaselineResult:
    return BaselineResult(
        payload=BaselinePayload(
            gaps=(
                BaselineGap(
                    gap_id="internal-baseline-gap-id",
                    kind=GapKind.AMBIGUITY,
                    subject_key="beta-subject",
                    description="beta description",
                    confidence=0.4,
                ),
            )
        ),
        usage=_usage(),
    )


def baseline_invalid() -> BaselineResult:
    return BaselineResult(
        payload=BaselinePayload(
            gaps=(
                BaselineGap(
                    gap_id="B-1",
                    kind=GapKind.AMBIGUITY,
                    subject_key="Not_Kebab_Case",
                    description="structurally invalid subject key",
                    confidence=0.4,
                ),
            )
        ),
        usage=_usage(),
    )


class ScriptedContestant:
    """A fake contestant. Records every request; never touches a network."""

    def __init__(
        self,
        contestant_id: ContestantId,
        default: Callable[[], Any],
        log: list[tuple[str, ContestantId]],
        script: list[Any] | None = None,
    ) -> None:
        self.contestant_id = contestant_id
        self._default = default
        self._log = log
        self._script = list(script or ())
        self.requests: list[IntelligenceInput] = []

    def analyze(self, request: IntelligenceInput) -> Any:
        self.requests.append(request)
        self._log.append((str(request.fixture_id), self.contestant_id))
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                return item()
            return item
        return self._default()


class Harness:
    def __init__(
        self,
        root: Path,
        foundry_script: list[Any] | None = None,
        baseline_script: list[Any] | None = None,
    ) -> None:
        self.root = root
        self.log: list[tuple[str, ContestantId]] = []
        self.foundry = ScriptedContestant(
            ContestantId.FOUNDRY, foundry_ok, self.log, foundry_script
        )
        self.baseline = ScriptedContestant(
            ContestantId.BASELINE, baseline_ok, self.log, baseline_script
        )
        self.progress: list[str] = []

    def run(self, *, resume: bool = False) -> Phase1OutputManifest:
        return run_phase1(
            repo_root=self.root,
            runner_commit_sha=RUNNER_COMMIT,
            foundry=self.foundry,
            baseline=self.baseline,
            resume=resume,
            blob_reader=_blob_reader(self.root),
            clock=_clock(),
            execution_id_factory=_execution_ids(),
            progress=self.progress.append,
        )

    def verify(self) -> Phase1OutputManifest:
        return verify_phase1_output(
            repo_root=self.root,
            runner_commit_sha=RUNNER_COMMIT,
            blob_reader=_blob_reader(self.root),
        )


def _assignments(root: Path) -> dict[str, dict[str, str]]:
    raw = json.loads((root / ASSIGNMENT_PATH).read_text())
    return {item["case_id"]: item for item in raw["assignments"]}


def _record(root: Path, case_id: str, contestant: ContestantId) -> Phase1ExecutionRecord:
    path = root / PHASE1 / "records" / f"{case_id}-{contestant.value}.json"
    return Phase1ExecutionRecord.model_validate(json.loads(path.read_text()))


def _patch_audit(root: Path, **over: Any) -> None:
    path = root / AUDIT_PATH
    payload = json.loads(path.read_text())
    payload.update(over)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def _attempt_files(root: Path, suffix: str) -> list[Path]:
    directory = root / PHASE1 / "attempts"
    if not directory.exists():
        return []
    return sorted(directory.glob(f"*-{suffix}.json"))


def _completed_attempts(root: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in _attempt_files(root, "completed")]


class _Spy:
    def __init__(self, wrapped: Callable[..., Any]) -> None:
        self._wrapped = wrapped
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(args)
        return self._wrapped(*args, **kwargs)


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, _Spy]]:
    names = (
        "validate_intelligence_result",
        "validate_baseline_result",
        "neutralize_foundry",
        "neutralize_baseline",
        "compile_intelligence_input",
    )
    created = {name: _Spy(getattr(phase1_runner, name)) for name in names}
    for name, spy in created.items():
        monkeypatch.setattr(phase1_runner, name, spy)
    yield created


# ---------------------------------------------------------------- seal and audit gates


# The fixture itself must represent a pre-Phase-1 repository: the sealed exam is
# present, post-execution evidence is not. Guards against the frozen Phase-1 output
# bundle leaking back into the temporary repositories.
def test_sealed_repo_fixture_represents_pre_phase1_state(sealed_repo: Path) -> None:
    assert (sealed_repo / "evals/comparative/experiment-manifest.json").is_file()
    assert (sealed_repo / "evals/comparative/holdout-inputs.json").is_file()
    assert (sealed_repo / "evals/comparative/execution-assignment.json").is_file()

    assert not (sealed_repo / "evals/comparative/phase1").exists()


# 22. Phase-1 seal verification happens before any fake contestant call.
def test_seal_verification_precedes_every_contestant_call(sealed_repo: Path) -> None:
    tampered = json.loads((sealed_repo / ASSIGNMENT_PATH).read_text())
    tampered["assignments"][0]["first_contestant"] = "BASELINE"
    tampered["assignments"][0]["second_contestant"] = "FOUNDRY"
    (sealed_repo / ASSIGNMENT_PATH).write_text(json.dumps(tampered, sort_keys=True, indent=2))
    harness = Harness(sealed_repo)
    with pytest.raises(Phase1SealViolation):
        harness.run()
    assert harness.foundry.requests == []
    assert harness.baseline.requests == []


def test_tampered_holdout_input_refuses_execution(sealed_repo: Path) -> None:
    target = sealed_repo / "evals/comparative/holdouts/case-001/input.json"
    payload = json.loads(target.read_text())
    payload["project_id"] = payload["project_id"] + "-tampered"
    target.write_text(json.dumps(payload, indent=2))
    harness = Harness(sealed_repo)
    with pytest.raises(Phase1SealViolation):
        harness.run()
    assert harness.foundry.requests == []


# 23. audit PASS is required.
def test_audit_must_declare_pass(sealed_repo: Path) -> None:
    _patch_audit(sealed_repo, result="FAIL")
    harness = Harness(sealed_repo)
    with pytest.raises(Phase1SealViolation):
        harness.run()
    assert harness.foundry.requests == []


def test_audit_version_must_be_the_frozen_version(sealed_repo: Path) -> None:
    _patch_audit(sealed_repo, audit_version="9j3-pre-exam-audit-v2")
    with pytest.raises(Phase1SealViolation):
        Harness(sealed_repo).run()


def test_audit_must_report_zero_contestant_calls_before_the_audit(sealed_repo: Path) -> None:
    _patch_audit(sealed_repo, contestant_calls_before_audit=1)
    with pytest.raises(Phase1SealViolation):
        Harness(sealed_repo).run()


def test_audit_must_report_the_frozen_case_counts(sealed_repo: Path) -> None:
    for override in (
        {"case_count": 11},
        {"greenfield_count": 5},
        {"brownfield_count": 7},
    ):
        root = sealed_repo
        _patch_audit(root, **override)
        with pytest.raises(Phase1SealViolation):
            Harness(root).run()
        _patch_audit(root, case_count=12, greenfield_count=6, brownfield_count=6)


# 24. audit with blocking finding refuses execution.
def test_blocking_audit_finding_refuses_execution(sealed_repo: Path) -> None:
    _patch_audit(sealed_repo, blocking_findings=1)
    harness = Harness(sealed_repo)
    with pytest.raises(Phase1SealViolation):
        harness.run()
    assert harness.foundry.requests == []


def test_unverified_audit_flags_refuse_execution(sealed_repo: Path) -> None:
    for flag in (
        "public_seal_verified",
        "contestant_freeze_verified",
        "hidden_judge_commitment_verified",
    ):
        _patch_audit(sealed_repo, **{flag: False})
        with pytest.raises(Phase1SealViolation):
            Harness(sealed_repo).run()
        _patch_audit(sealed_repo, **{flag: True})


# 25. audit's experiment-manifest hash must match.
def test_audit_experiment_manifest_hash_must_match(sealed_repo: Path) -> None:
    _patch_audit(sealed_repo, audited_experiment_manifest_sha256="0" * 64)
    harness = Harness(sealed_repo)
    with pytest.raises(Phase1SealViolation):
        harness.run()
    assert harness.foundry.requests == []


def test_preflight_makes_no_contestant_call_and_reports_the_frozen_shape(
    sealed_repo: Path,
) -> None:
    report = preflight(
        repo_root=sealed_repo,
        runner_commit_sha=RUNNER_COMMIT,
        blob_reader=_blob_reader(sealed_repo),
    )
    assert report.case_sequence == CASE_SEQUENCE
    assert report.total_contestant_slots == 24
    assert tuple(item.path for item in report.runner_artifacts) == RUNNER_MODULE_PATHS


def test_preflight_refuses_when_the_hidden_judge_sits_beside_the_execution_tree(
    sealed_repo: Path,
) -> None:
    (sealed_repo.parent / ".foundry-sealed-evals").mkdir()
    with pytest.raises(Phase1SealViolation):
        preflight(
            repo_root=sealed_repo,
            runner_commit_sha=RUNNER_COMMIT,
            blob_reader=_blob_reader(sealed_repo),
        )


# ------------------------------------------------------------------- ordering and pairing


# 26. case sequence follows committed holdout tuple order.
def test_case_sequence_follows_the_committed_holdout_tuple_order(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    manifest = harness.run()
    assert manifest.case_sequence == CASE_SEQUENCE
    seen: list[str] = []
    for case_id, _ in harness.log:
        if case_id not in seen:
            seen.append(case_id)
    assert tuple(seen) == CASE_SEQUENCE


# 27. case assignment controls first contestant.
def test_frozen_assignment_controls_which_contestant_runs_first(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    assignments = _assignments(sealed_repo)
    for index, case_id in enumerate(CASE_SEQUENCE):
        pair = harness.log[index * 2 : index * 2 + 2]
        assert [item[0] for item in pair] == [case_id, case_id]
        assert pair[0][1].value == assignments[case_id]["first_contestant"]
        assert pair[1][1].value == assignments[case_id]["second_contestant"]


# 28. same compiled IntelligenceInput goes to both contestants.
def test_both_contestants_receive_the_same_compiled_input_object(
    sealed_repo: Path, spies: dict[str, _Spy]
) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    assert len(spies["compile_intelligence_input"].calls) == 12
    assert len(harness.foundry.requests) == 12
    for foundry_request, baseline_request in zip(
        harness.foundry.requests, harness.baseline.requests, strict=True
    ):
        assert foundry_request is baseline_request


# 29. pair is back-to-back.
def test_each_case_pair_runs_back_to_back(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    assert len(harness.log) == 24
    for index in range(0, 24, 2):
        first, second = harness.log[index], harness.log[index + 1]
        assert first[0] == second[0]
        assert {first[1], second[1]} == {ContestantId.FOUNDRY, ContestantId.BASELINE}


def test_progress_output_discloses_no_semantic_content(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    text = "\n".join(harness.progress)
    for forbidden in (
        "alpha-subject",
        "beta-subject",
        "alpha description",
        "internal-foundry-gap-id",
        "internal-baseline-gap-id",
        "internal-foundry-only-semantic-statement",
        "FOUNDRY",
        "BASELINE",
    ):
        assert forbidden not in text
    assert "case 1/12 slot 1/2 started" in text


# ------------------------------------------------------------ validation and neutralization


# 30/31. deterministic validators run for both contestants.
def test_both_deterministic_validators_run_on_every_slot(
    sealed_repo: Path, spies: dict[str, _Spy]
) -> None:
    Harness(sealed_repo).run()
    assert len(spies["validate_intelligence_result"].calls) == 12
    assert len(spies["validate_baseline_result"].calls) == 12


# 32/33. valid results neutralize through the frozen neutralizers.
def test_valid_results_use_the_frozen_neutralizers(
    sealed_repo: Path, spies: dict[str, _Spy]
) -> None:
    Harness(sealed_repo).run()
    assert len(spies["neutralize_foundry"].calls) == 12
    assert len(spies["neutralize_baseline"].calls) == 12


# 34. correct blind label path used.
def test_blind_output_is_written_under_the_frozen_label(sealed_repo: Path) -> None:
    Harness(sealed_repo).run()
    assignments = _assignments(sealed_repo)
    for case_id in CASE_SEQUENCE:
        assignment = assignments[case_id]
        blind = sealed_repo / PHASE1 / "blind" / case_id
        assert {path.name for path in blind.iterdir()} == {"SYSTEM-A.json", "SYSTEM-B.json"}
        foundry_record = _record(sealed_repo, case_id, ContestantId.FOUNDRY)
        assert foundry_record.blind_label.value == assignment["foundry_blind_label"]
        assert foundry_record.blind_output_path is not None
        assert foundry_record.blind_output_path.endswith(
            f"{case_id}/{assignment['foundry_blind_label']}.json"
        )
        baseline_record = _record(sealed_repo, case_id, ContestantId.BASELINE)
        assert baseline_record.blind_label.value == assignment["baseline_blind_label"]


# 35. semantic proposals absent from blind output.
def test_blind_outputs_disclose_no_semantic_proposal_or_original_id(
    sealed_repo: Path,
) -> None:
    Harness(sealed_repo).run()
    for path in (sealed_repo / PHASE1 / "blind").rglob("*.json"):
        text = path.read_text()
        for forbidden in (
            "semantic_proposals",
            "internal-foundry-only-semantic-statement",
            "internal-foundry-gap-id",
            "internal-baseline-gap-id",
            "proposal_id",
            "gap_id",
            "FOUNDRY",
            "BASELINE",
            "cost_usd",
            "usage",
        ):
            assert forbidden not in text
        payload = json.loads(text)
        assert set(payload) == {"case_id", "system_label", "predictions"}


def test_raw_foundry_evidence_still_preserves_its_semantic_proposals(
    sealed_repo: Path,
) -> None:
    Harness(sealed_repo).run()
    raw = json.loads(
        (sealed_repo / PHASE1 / "raw" / "H-011" / "FOUNDRY.json").read_text()
    )
    assert raw["result"]["payload"]["semantic_proposals"]


def test_neutral_prediction_ids_follow_original_gap_order(sealed_repo: Path) -> None:
    Harness(sealed_repo).run()
    for path in (sealed_repo / PHASE1 / "blind").rglob("*.json"):
        payload = json.loads(path.read_text())
        ids = [item["prediction_id"] for item in payload["predictions"]]
        assert ids == [f"P-{index:03d}" for index in range(1, len(ids) + 1)]


# --------------------------------------------------------------------- failure treatment


# 36. structurally invalid Foundry result is terminal, no retry.
def test_structurally_invalid_foundry_result_is_terminal_without_retry(
    sealed_repo: Path,
) -> None:
    harness = Harness(sealed_repo, foundry_script=[foundry_invalid])
    manifest = harness.run()
    first_case = CASE_SEQUENCE[0]
    record = _record(sealed_repo, first_case, ContestantId.FOUNDRY)
    assert record.terminal_status is Phase1TerminalStatus.STRUCTURAL_FAILURE
    assert record.blind_output_path is None
    assert record.raw_result_path is not None
    assert len(record.attempt_execution_ids) == 1
    assert record.infrastructure_retry_count == 0
    assert len(harness.foundry.requests) == 12
    assert manifest.structural_failures == 1
    assert manifest.valid_results == 23
    blind = sealed_repo / PHASE1 / "blind" / first_case
    assert not (blind / f"{record.blind_label.value}.json").exists()


def test_structural_failure_preserves_the_unrepaired_raw_result(sealed_repo: Path) -> None:
    Harness(sealed_repo, foundry_script=[foundry_invalid]).run()
    raw = json.loads(
        (sealed_repo / PHASE1 / "raw" / CASE_SEQUENCE[0] / "FOUNDRY.json").read_text()
    )
    assert raw["structural_validation_passed"] is False
    assert raw["structural_error"]
    assert raw["result"]["payload"]["gap_proposals"][0]["subject_key"] == "Not_Kebab_Case"


# 37. structurally invalid baseline result is terminal, no retry.
def test_structurally_invalid_baseline_result_is_terminal_without_retry(
    sealed_repo: Path,
) -> None:
    harness = Harness(sealed_repo, baseline_script=[baseline_invalid])
    manifest = harness.run()
    record = _record(sealed_repo, CASE_SEQUENCE[0], ContestantId.BASELINE)
    assert record.terminal_status is Phase1TerminalStatus.STRUCTURAL_FAILURE
    assert record.blind_output_path is None
    assert len(harness.baseline.requests) == 12
    assert manifest.structural_failures == 1


# 38. valid-but-poor result is never retried.
def test_structurally_valid_but_empty_result_is_final(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo, foundry_script=[foundry_empty])
    manifest = harness.run()
    record = _record(sealed_repo, CASE_SEQUENCE[0], ContestantId.FOUNDRY)
    assert record.terminal_status is Phase1TerminalStatus.VALID
    assert len(record.attempt_execution_ids) == 1
    assert manifest.valid_results == 24
    blind = json.loads(
        (
            sealed_repo
            / PHASE1
            / "blind"
            / CASE_SEQUENCE[0]
            / f"{record.blind_label.value}.json"
        ).read_text()
    )
    assert blind["predictions"] == []


# 39/40. one immediate infrastructure retry occurs and can become terminal.
def test_one_immediate_infrastructure_retry_is_allowed_and_can_succeed(
    sealed_repo: Path,
) -> None:
    harness = Harness(sealed_repo, foundry_script=[ConnectionError("transport reset")])
    manifest = harness.run()
    record = _record(sealed_repo, CASE_SEQUENCE[0], ContestantId.FOUNDRY)
    assert record.terminal_status is Phase1TerminalStatus.VALID
    assert record.infrastructure_retry_count == 1
    assert len(record.attempt_execution_ids) == 2
    assert manifest.infrastructure_failures == 1
    assert manifest.infrastructure_retries == 1
    assert len(harness.foundry.requests) == 13


# 41. two infrastructure failures pause the runner.
def test_two_infrastructure_failures_pause_the_runner(sealed_repo: Path) -> None:
    harness = Harness(
        sealed_repo,
        foundry_script=[TimeoutError("deadline"), TimeoutError("deadline")],
    )
    with pytest.raises(Phase1Paused):
        harness.run()
    assert len(harness.foundry.requests) == 2
    assert harness.baseline.requests == []
    assert not (sealed_repo / PHASE1 / "records").exists()
    assert not (sealed_repo / PHASE1 / "phase1-output-manifest.json").exists()
    outcomes = [item["outcome"] for item in _completed_attempts(sealed_repo)]
    assert outcomes == ["INFRASTRUCTURE_FAILURE", "INFRASTRUCTURE_FAILURE"]


# 42/43/44. resume retries only the unresolved slot and preserves prior attempts.
def test_resume_retries_only_the_unresolved_slot(sealed_repo: Path) -> None:
    first = Harness(
        sealed_repo,
        foundry_script=[TimeoutError("deadline"), TimeoutError("deadline")],
    )
    with pytest.raises(Phase1Paused):
        first.run()

    second = Harness(sealed_repo)
    manifest = second.run(resume=True)

    assert len(second.foundry.requests) == 12
    assert len(second.baseline.requests) == 12
    record = _record(sealed_repo, CASE_SEQUENCE[0], ContestantId.FOUNDRY)
    assert record.terminal_status is Phase1TerminalStatus.VALID
    assert record.infrastructure_retry_count == 2
    assert len(record.attempt_execution_ids) == 3
    assert manifest.infrastructure_failures == 2
    assert manifest.infrastructure_retries == 2
    assert len(manifest.attempts) == 26


def test_resume_preserves_every_previous_attempt_file(sealed_repo: Path) -> None:
    first = Harness(
        sealed_repo,
        foundry_script=[TimeoutError("deadline"), TimeoutError("deadline")],
    )
    with pytest.raises(Phase1Paused):
        first.run()
    before = {path.name: path.read_bytes() for path in _attempt_files(sealed_repo, "completed")}
    started_before = {
        path.name: path.read_bytes() for path in _attempt_files(sealed_repo, "started")
    }

    Harness(sealed_repo).run(resume=True)

    after = {path.name: path.read_bytes() for path in _attempt_files(sealed_repo, "completed")}
    started_after = {
        path.name: path.read_bytes() for path in _attempt_files(sealed_repo, "started")
    }
    for name, payload in before.items():
        assert after[name] == payload
    for name, payload in started_before.items():
        assert started_after[name] == payload


def test_resume_never_calls_a_completed_terminal_slot_again(sealed_repo: Path) -> None:
    first = Harness(
        sealed_repo,
        foundry_script=[
            foundry_ok,
            baseline_ok,
            TimeoutError("deadline"),
            TimeoutError("deadline"),
        ],
    )
    # Pause part-way: case 1 completes fully, case 2's Foundry slot stalls.
    first.foundry._script = [foundry_ok, TimeoutError("deadline"), TimeoutError("deadline")]
    with pytest.raises(Phase1Paused):
        first.run()
    assert _record(sealed_repo, CASE_SEQUENCE[0], ContestantId.FOUNDRY)

    second = Harness(sealed_repo)
    second.run(resume=True)
    resumed_cases = [case_id for case_id, _ in second.log]
    assert CASE_SEQUENCE[0] not in resumed_cases
    assert resumed_cases[0] == CASE_SEQUENCE[1]


def test_resume_is_required_to_continue_a_partially_executed_bundle(
    sealed_repo: Path,
) -> None:
    first = Harness(
        sealed_repo,
        foundry_script=[TimeoutError("deadline"), TimeoutError("deadline")],
    )
    with pytest.raises(Phase1Paused):
        first.run()
    with pytest.raises(Phase1SealViolation):
        Harness(sealed_repo).run()


# 45. started-without-completed attempt aborts as ambiguous.
def test_started_attempt_without_completion_aborts_as_ambiguous(sealed_repo: Path) -> None:
    Harness(sealed_repo).run()
    shutil.rmtree(sealed_repo / PHASE1)
    attempts = sealed_repo / PHASE1 / "attempts"
    attempts.mkdir(parents=True)
    orphan = "00000000-0000-4000-8000-000000000099"
    (attempts / f"{orphan}-started.json").write_text(
        json.dumps(
            {
                "execution_id": orphan,
                "case_id": CASE_SEQUENCE[0],
                "contestant_id": "FOUNDRY",
                "blind_label": "SYSTEM-A",
                "execution_position": 1,
                "attempt_number": 1,
                "started_at": "2026-09-10T12:00:00Z",
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    harness = Harness(sealed_repo)
    with pytest.raises(AmbiguousInFlightAttempt):
        harness.run(resume=True)
    assert harness.foundry.requests == []


# 46. provider schema incompatibility aborts.
def test_provider_schema_incompatibility_aborts_the_experiment(sealed_repo: Path) -> None:
    failure = RuntimeError("PROVIDER_SCHEMA_INCOMPATIBILITY: json schema not supported")
    harness = Harness(sealed_repo, foundry_script=[failure])
    with pytest.raises(Phase1Abort) as caught:
        harness.run()
    assert caught.value.outcome is AttemptOutcome.PROVIDER_SCHEMA_INCOMPATIBILITY
    assert len(harness.foundry.requests) == 1
    assert harness.baseline.requests == []


# 47. unknown executor failure aborts.
def test_unknown_executor_failure_aborts_the_experiment(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo, foundry_script=[AttributeError("runner defect")])
    with pytest.raises(Phase1Abort) as caught:
        harness.run()
    assert caught.value.outcome is AttemptOutcome.EXECUTOR_FAILURE
    assert len(harness.foundry.requests) == 1


# 48. no later case executes after abort.
def test_no_later_case_executes_after_an_abort(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo, foundry_script=[AttributeError("runner defect")])
    with pytest.raises(Phase1Abort):
        harness.run()
    assert {case_id for case_id, _ in harness.log} == {CASE_SEQUENCE[0]}
    assert not (sealed_repo / PHASE1 / "records").exists()
    assert not (sealed_repo / PHASE1 / "phase1-output-manifest.json").exists()
    outcomes = [item["outcome"] for item in _completed_attempts(sealed_repo)]
    assert outcomes == ["EXECUTOR_FAILURE"]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TimeoutError("t"), AttemptOutcome.INFRASTRUCTURE_FAILURE),
        (ConnectionError("c"), AttemptOutcome.INFRASTRUCTURE_FAILURE),
        (
            RuntimeError("PROVIDER_SCHEMA_INCOMPATIBILITY: bad"),
            AttemptOutcome.PROVIDER_SCHEMA_INCOMPATIBILITY,
        ),
        (AttributeError("defect"), AttemptOutcome.EXECUTOR_FAILURE),
        (ValueError("something odd"), AttemptOutcome.EXECUTOR_FAILURE),
    ],
)
def test_exception_classification_is_conservative(
    exc: BaseException, expected: AttemptOutcome
) -> None:
    assert classify_exception(exc) is expected


def test_chained_causes_are_inspected_for_classification() -> None:
    try:
        try:
            raise TimeoutError("deadline exceeded")
        except TimeoutError as inner:
            raise RuntimeError("provider call failed") from inner
    except RuntimeError as outer:
        assert classify_exception(outer) is AttemptOutcome.INFRASTRUCTURE_FAILURE


def test_grpc_like_status_codes_are_recognised_as_infrastructure() -> None:
    class _Code:
        def __init__(self, name: str) -> None:
            self.name = name

    class _RpcError(Exception):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self._name = name

        def code(self) -> _Code:
            return _Code(self._name)

    for name in ("DEADLINE_EXCEEDED", "UNAVAILABLE", "RESOURCE_EXHAUSTED"):
        assert classify_exception(_RpcError(name)) is AttemptOutcome.INFRASTRUCTURE_FAILURE
    assert classify_exception(_RpcError("INVALID_ARGUMENT")) is AttemptOutcome.EXECUTOR_FAILURE


def test_structured_parsing_failure_is_structural_not_infrastructure() -> None:
    from pydantic import ValidationError

    try:
        IntelligenceUsage.model_validate({"input_tokens": "not-an-int"})
    except ValidationError as inner:
        wrapped = RuntimeError("provider call failed")
        wrapped.__cause__ = inner
        assert classify_exception(wrapped) is AttemptOutcome.STRUCTURAL_FAILURE


def test_parsing_failure_during_a_call_is_terminal_without_retry(sealed_repo: Path) -> None:
    from pydantic import ValidationError

    try:
        IntelligenceUsage.model_validate({"input_tokens": "not-an-int"})
    except ValidationError as inner:
        wrapped = RuntimeError("provider payload rejected")
        wrapped.__cause__ = inner
    harness = Harness(sealed_repo, foundry_script=[wrapped])
    manifest = harness.run()
    record = _record(sealed_repo, CASE_SEQUENCE[0], ContestantId.FOUNDRY)
    assert record.terminal_status is Phase1TerminalStatus.STRUCTURAL_FAILURE
    assert record.raw_result_path is None
    assert record.blind_output_path is None
    assert record.input_tokens is None
    assert len(record.attempt_execution_ids) == 1
    assert manifest.structural_failures == 1


# ------------------------------------------------------------------- freeze and verification


# 49. final output manifest only exists after all 24 slots terminal.
def test_output_manifest_appears_only_after_all_twenty_four_slots_are_terminal(
    sealed_repo: Path,
) -> None:
    manifest_path = sealed_repo / PHASE1 / "phase1-output-manifest.json"
    harness = Harness(
        sealed_repo, foundry_script=[TimeoutError("d"), TimeoutError("d")]
    )
    with pytest.raises(Phase1Paused):
        harness.run()
    assert not manifest_path.exists()

    manifest = Harness(sealed_repo).run(resume=True)
    assert manifest_path.exists()
    assert len(manifest.executions) == 24
    assert manifest.total_contestant_slots == 24


# 50. output manifest existing causes execute to refuse further calls.
def test_a_frozen_output_manifest_permanently_refuses_further_execution(
    sealed_repo: Path,
) -> None:
    Harness(sealed_repo).run()
    for resume in (False, True):
        harness = Harness(sealed_repo)
        with pytest.raises(Phase1AlreadyFrozen):
            harness.run(resume=resume)
        assert harness.foundry.requests == []
        assert harness.baseline.requests == []


# 51. verifier reconstructs and validates blind output from raw valid output.
def test_verifier_reconstructs_blind_output_from_the_raw_valid_output(
    sealed_repo: Path,
) -> None:
    harness = Harness(sealed_repo)
    manifest = harness.run()
    verified = harness.verify()
    assert phase1_canonical_bytes(verified) == phase1_canonical_bytes(manifest)


def test_verifier_accepts_a_bundle_containing_a_structural_failure(
    sealed_repo: Path,
) -> None:
    harness = Harness(sealed_repo, foundry_script=[foundry_invalid])
    harness.run()
    assert harness.verify().structural_failures == 1


def test_verifier_rejects_a_blind_output_that_does_not_match_its_raw_result(
    sealed_repo: Path,
) -> None:
    harness = Harness(sealed_repo)
    manifest = harness.run()
    record = manifest.executions[0]
    assert record.blind_output_path is not None
    target = sealed_repo / record.blind_output_path
    payload = json.loads(target.read_text())
    payload["predictions"][0]["description"] = "rewritten by hand"
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    with pytest.raises(Phase1SealViolation):
        harness.verify()


# 52. tampered raw file fails verification.
def test_tampered_raw_file_fails_verification(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    manifest = harness.run()
    record = manifest.executions[0]
    assert record.raw_result_path is not None
    target = sealed_repo / record.raw_result_path
    payload = json.loads(target.read_text())
    payload["case_id"] = "H-999"
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    with pytest.raises(Phase1SealViolation):
        harness.verify()


# 53. tampered blind file fails verification.
def test_tampered_blind_file_fails_verification(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    manifest = harness.run()
    record = manifest.executions[0]
    assert record.blind_output_path is not None
    target = sealed_repo / record.blind_output_path
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(Phase1SealViolation):
        harness.verify()


# 54. tampered record fails verification.
def test_tampered_record_fails_verification(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    target = (
        sealed_repo / PHASE1 / "records" / f"{CASE_SEQUENCE[0]}-FOUNDRY.json"
    )
    payload = json.loads(target.read_text())
    payload["cost_usd"] = 999.0
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    with pytest.raises(Phase1SealViolation):
        harness.verify()


def test_tampered_output_manifest_fails_verification(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    target = sealed_repo / PHASE1 / "phase1-output-manifest.json"
    payload = json.loads(target.read_text())
    payload["case_sequence"] = list(reversed(payload["case_sequence"]))
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    with pytest.raises(Phase1SealViolation):
        harness.verify()


def test_tampered_attempt_record_fails_verification(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    target = _attempt_files(sealed_repo, "completed")[0]
    payload = json.loads(target.read_text())
    payload["outcome"] = "INFRASTRUCTURE_FAILURE"
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    with pytest.raises(Phase1SealViolation):
        harness.verify()


# 55. changed runner source hash fails verification.
def test_changed_runner_source_hash_fails_verification(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    target = sealed_repo / "src/foundry/evaluation/phase1_runner.py"
    target.write_bytes(target.read_bytes() + b"\n# drift\n")
    with pytest.raises(Phase1SealViolation):
        harness.verify()


def test_runner_commit_must_match_the_frozen_manifest(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    with pytest.raises(Phase1SealViolation):
        verify_phase1_output(
            repo_root=sealed_repo,
            runner_commit_sha="2" * 40,
            blob_reader=_blob_reader(sealed_repo),
        )


# 56. output bundle verifier never accesses judge.
def test_runner_module_never_reaches_the_hidden_judge() -> None:
    source = Path(phase1_runner.__file__).read_text()
    for forbidden in (
        "hidden-judge",
        "hidden_judge.json",
        "hidden_judge_bundle",
        "HiddenJudgeBundle",
        "HiddenJudgeCase",
        "ExpectedConcept",
        "verify_revealed_judge_bundle",
        "load_judge",
        "judge.json",
        "SystemAdjudication",
        "BlindAdjudicationPacket",
    ):
        assert forbidden not in source, forbidden
    for attribute in (
        "HiddenJudgeBundle",
        "HiddenJudgeCase",
        "ExpectedConcept",
        "verify_revealed_judge_bundle",
    ):
        assert not hasattr(phase1_runner, attribute)


def test_verification_reads_no_file_outside_the_repository(sealed_repo: Path) -> None:
    harness = Harness(sealed_repo)
    harness.run()
    opened: list[str] = []
    real_open = Path.read_bytes

    def tracking_read(self: Path) -> bytes:
        opened.append(str(self))
        return real_open(self)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(Path, "read_bytes", tracking_read)
    try:
        harness.verify()
    finally:
        monkey.undo()
    root = str(sealed_repo.resolve())
    for path in opened:
        assert Path(path).resolve().is_relative_to(root)
