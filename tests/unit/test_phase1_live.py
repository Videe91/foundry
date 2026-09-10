"""Task 9K1-A live CLI surface.

`preflight` and `verify` must make zero model calls. `execute` is the only command
that may construct a contestant, and it must refuse before construction when the key
is absent or the bundle is already frozen.

No test in this module constructs a real xAI client.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import foundry.evaluation.phase1_live as phase1_live
from foundry.evaluation.phase1_execution import (
    PHASE1_OUTPUT_MANIFEST_FILENAME,
    PHASE1_ROOT,
)
from foundry.evaluation.phase1_live import (
    API_KEY_ENV,
    EXIT_ABORT,
    EXIT_MISSING_KEY,
    EXIT_OK,
    EXIT_PAUSED,
    FROZEN_MODEL,
    FROZEN_REASONING_EFFORT,
    FROZEN_TIMEOUT_SECONDS,
    frozen_contestant_config,
    main,
)
from foundry.evaluation.phase1_runner import Phase1Abort, Phase1Paused

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_COMMIT = "1" * 40
API_KEY = "xai-do-not-log-this-value-0123456789"


@pytest.fixture(autouse=True)
def local_blob_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the frozen runner blobs from the copied tree instead of a git object."""

    def reader(repo_root: Path) -> Any:
        def read(commit: str, path: str) -> bytes:
            assert commit == RUNNER_COMMIT
            return (repo_root / path).read_bytes()

        return read

    monkeypatch.setattr(phase1_live, "git_blob_reader", reader)


@pytest.fixture
def sealed_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for tree in ("src", "evals", "docs"):
        shutil.copytree(REPO_ROOT / tree, root / tree, ignore=ignore)
    return root


class Recorder:
    """Stands in for a frozen xAI contestant. Constructing it is the observable event."""

    def __init__(self) -> None:
        self.instances: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Recorder:
        self.instances.append(kwargs)
        return self

    def analyze(self, request: Any) -> Any:
        raise AssertionError("a live contestant was called during a no-call command")


@pytest.fixture
def adapters(monkeypatch: pytest.MonkeyPatch) -> dict[str, Recorder]:
    created = {"foundry": Recorder(), "baseline": Recorder()}
    monkeypatch.setattr(phase1_live, "XAIIntentIntelligence", created["foundry"])
    monkeypatch.setattr(phase1_live, "XAIBaselineIntelligence", created["baseline"])
    return created


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return _stub_manifest()


def _stub_manifest() -> Any:
    class _Stub:
        total_contestant_slots = 24
        valid_results = 24
        structural_failures = 0
        infrastructure_failures = 0
        infrastructure_retries = 0
        case_sequence = tuple(f"H-{index:03d}" for index in range(1, 13))
        executions: tuple[Any, ...] = ()
        attempts: tuple[Any, ...] = ()

    return _Stub()


def _run(argv: list[str], out: list[str]) -> int:
    return main(argv, out=out.append)


# 57. preflight performs zero contestant calls.
def test_preflight_constructs_no_contestant(
    sealed_repo: Path, adapters: dict[str, Recorder]
) -> None:
    out: list[str] = []
    code = _run(
        [
            "preflight",
            "--runner-commit",
            RUNNER_COMMIT,
            "--repo-root",
            str(sealed_repo),
        ],
        out,
    )
    assert code == EXIT_OK
    assert "PHASE1 PREFLIGHT PASS" in "\n".join(out)
    assert adapters["foundry"].instances == []
    assert adapters["baseline"].instances == []


def test_preflight_reports_the_frozen_shape(sealed_repo: Path) -> None:
    out: list[str] = []
    _run(
        [
            "preflight",
            "--runner-commit",
            RUNNER_COMMIT,
            "--repo-root",
            str(sealed_repo),
        ],
        out,
    )
    text = "\n".join(out)
    assert "12" in text
    assert "24" in text


# 58. verify performs zero contestant calls.
def test_verify_constructs_no_contestant(
    sealed_repo: Path, adapters: dict[str, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    out: list[str] = []
    _run(
        [
            "verify",
            "--runner-commit",
            RUNNER_COMMIT,
            "--repo-root",
            str(sealed_repo),
        ],
        out,
    )
    assert adapters["foundry"].instances == []
    assert adapters["baseline"].instances == []


# 59. execute refuses missing XAI_API_KEY before constructing contestants.
def test_execute_refuses_a_missing_api_key_before_constructing_contestants(
    sealed_repo: Path, adapters: dict[str, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    out: list[str] = []
    code = _run(
        [
            "execute",
            "--runner-commit",
            RUNNER_COMMIT,
            "--repo-root",
            str(sealed_repo),
        ],
        out,
    )
    assert code == EXIT_MISSING_KEY
    assert "STOP - XAI_API_KEY NOT AVAILABLE IN ENVIRONMENT" in "\n".join(out)
    assert adapters["foundry"].instances == []
    assert adapters["baseline"].instances == []


def test_execute_refuses_an_empty_api_key(
    sealed_repo: Path, adapters: dict[str, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "")
    out: list[str] = []
    assert (
        _run(
            [
                "execute",
                "--runner-commit",
                RUNNER_COMMIT,
                "--repo-root",
                str(sealed_repo),
                ],
            out,
        )
        == EXIT_MISSING_KEY
    )
    assert adapters["foundry"].instances == []


# 60. API key never appears in serialized output.
def test_api_key_never_reaches_terminal_output_or_evidence(
    sealed_repo: Path,
    adapters: dict[str, Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    runner = FakeRunner()
    monkeypatch.setattr(phase1_live, "run_phase1", runner)
    out: list[str] = []
    _run(
        [
            "execute",
            "--runner-commit",
            RUNNER_COMMIT,
            "--repo-root",
            str(sealed_repo),
        ],
        out,
    )
    text = "\n".join(out)
    assert API_KEY not in text
    for call in runner.calls:
        assert API_KEY not in json.dumps({k: str(v) for k, v in call.items()})
    for path in sealed_repo.rglob("*.json"):
        assert API_KEY not in path.read_text(encoding="utf-8", errors="ignore")


def test_api_key_is_never_written_into_a_failure_message(
    sealed_repo: Path,
    adapters: dict[str, Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)

    def explode(**kwargs: Any) -> Any:
        raise Phase1Abort(
            "provider rejected api_key=" + API_KEY,
            phase1_live.AttemptOutcome.EXECUTOR_FAILURE,
        )

    monkeypatch.setattr(phase1_live, "run_phase1", explode)
    out: list[str] = []
    code = _run(
        [
            "execute",
            "--runner-commit",
            RUNNER_COMMIT,
            "--repo-root",
            str(sealed_repo),
        ],
        out,
    )
    assert code == EXIT_ABORT
    assert API_KEY not in "\n".join(out)


# 61/62/63. exactly one adapter each, constructed with the frozen configuration.
def test_execute_constructs_exactly_one_adapter_of_each_contestant(
    sealed_repo: Path,
    adapters: dict[str, Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    runner = FakeRunner()
    monkeypatch.setattr(phase1_live, "run_phase1", runner)
    out: list[str] = []
    assert (
        _run(
            [
                "execute",
                "--runner-commit",
                RUNNER_COMMIT,
                "--repo-root",
                str(sealed_repo),
                ],
            out,
        )
        == EXIT_OK
    )
    assert len(adapters["foundry"].instances) == 1
    assert len(adapters["baseline"].instances) == 1


def test_execute_passes_the_frozen_model_reasoning_and_timeout_explicitly(
    sealed_repo: Path,
    adapters: dict[str, Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    monkeypatch.setattr(phase1_live, "run_phase1", FakeRunner())
    _run(
        [
            "execute",
            "--runner-commit",
            RUNNER_COMMIT,
            "--repo-root",
            str(sealed_repo),
        ],
        [],
    )
    for recorder in adapters.values():
        kwargs = recorder.instances[0]
        assert kwargs["model"] == FROZEN_MODEL == "grok-4.6"
        assert kwargs["reasoning_effort"] == FROZEN_REASONING_EFFORT == "high"
        assert kwargs["timeout_seconds"] == FROZEN_TIMEOUT_SECONDS == 3600
        assert kwargs["api_key"] == API_KEY


def test_frozen_contestant_config_is_read_from_the_committed_freeze(
    sealed_repo: Path,
) -> None:
    config = frozen_contestant_config(sealed_repo)
    assert config.model == "grok-4.6"
    assert config.reasoning_effort == "high"
    assert config.timeout_seconds == 3600


def test_frozen_contestant_config_rejects_a_drifted_freeze(sealed_repo: Path) -> None:
    target = sealed_repo / "evals/comparative/contestant-freeze.json"
    payload = json.loads(target.read_text())
    payload["contestant_a"]["reasoning_effort"] = "low"
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    with pytest.raises(ValueError):
        frozen_contestant_config(sealed_repo)


def test_execute_reports_a_pause_without_claiming_completion(
    sealed_repo: Path,
    adapters: dict[str, Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)

    def pause(**kwargs: Any) -> Any:
        raise Phase1Paused("two infrastructure failures")

    monkeypatch.setattr(phase1_live, "run_phase1", pause)
    out: list[str] = []
    assert (
        _run(
            [
                "execute",
                "--runner-commit",
                RUNNER_COMMIT,
                "--repo-root",
                str(sealed_repo),
                ],
            out,
        )
        == EXIT_PAUSED
    )
    assert "PAUSED_INFRASTRUCTURE" in "\n".join(out)


# 64/65/66. the live module never reaches the hidden judge or adjudication models.
def test_live_module_has_no_hidden_judge_loader() -> None:
    source = Path(phase1_live.__file__).read_text()
    for forbidden in (
        "hidden-judge",
        "hidden_judge",
        "HiddenJudgeBundle",
        "HiddenJudgeCase",
        "ExpectedConcept",
        "load_judge",
        "judge.json",
        ".foundry-sealed-evals",
    ):
        assert forbidden not in source, forbidden


def test_live_module_does_not_import_verify_revealed_judge_bundle() -> None:
    assert "verify_revealed_judge_bundle" not in Path(phase1_live.__file__).read_text()
    assert not hasattr(phase1_live, "verify_revealed_judge_bundle")


def test_live_module_imports_no_adjudication_model() -> None:
    source = Path(phase1_live.__file__).read_text()
    for forbidden in (
        "comparative_protocol",
        "SystemAdjudication",
        "BlindAdjudicationPacket",
        "ConceptJudgment",
        "PredictionJudgment",
        "SemanticAdjudicationRubric",
        "AdjudicationMechanism",
        "SafetyLabel",
    ):
        assert forbidden not in source, forbidden
    for attribute in (
        "HiddenJudgeBundle",
        "ExpectedConcept",
        "SystemAdjudication",
        "build_semantic_rubric",
    ):
        assert not hasattr(phase1_live, attribute)


# 67. --resume routes to resume behavior.
def test_resume_flag_routes_to_resume_behaviour(
    sealed_repo: Path,
    adapters: dict[str, Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    runner = FakeRunner()
    monkeypatch.setattr(phase1_live, "run_phase1", runner)
    base = [
        "execute",
        "--runner-commit",
        RUNNER_COMMIT,
        "--repo-root",
        str(sealed_repo),
    ]
    _run(base, [])
    assert runner.calls[-1]["resume"] is False
    _run([*base, "--resume"], [])
    assert runner.calls[-1]["resume"] is True


# 68. output already frozen prevents adapter construction.
def test_a_frozen_output_manifest_prevents_adapter_construction(
    tmp_path: Path, adapters: dict[str, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    root = tmp_path / "repo"
    frozen = root / PHASE1_ROOT / PHASE1_OUTPUT_MANIFEST_FILENAME
    frozen.parent.mkdir(parents=True)
    frozen.write_text("{}")
    out: list[str] = []
    code = _run(
        ["execute", "--runner-commit", RUNNER_COMMIT, "--repo-root", str(root)], out
    )
    assert code != EXIT_OK
    assert adapters["foundry"].instances == []
    assert adapters["baseline"].instances == []
    assert "already frozen" in "\n".join(out).lower()


def test_execute_requires_a_runner_commit() -> None:
    with pytest.raises(SystemExit):
        main(["execute"], out=lambda _message: None)
