"""Task 9K3-A the Phase-3 CLI: preflight-blind, reveal-and-score, verify.

No command in this module reaches xAI, OpenAI, the network, or an API key. The
import-closure tests prove that structurally by inspecting a FRESH interpreter, not by
trusting a convention.

Synthetic fixtures are reused from `test_phase3_runner` so the real execution
assignment is still never opened, and so a seventh Phase-3 file is not created.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_phase3_runner import (
    SCORER_COMMIT,
    _harness,
    _Spy,
    build_blob_reader,
    build_judge_path,
    build_scored_repo,
    forbid_network,
)

from foundry.evaluation import phase3_live, phase3_runner
from foundry.evaluation.phase3_live import (
    EXIT_FROZEN,
    EXIT_OK,
    EXIT_SEAL,
    build_parser,
    main,
)
from foundry.evaluation.phase3_runner import (
    REPORT_FILENAME,
    RESULT_FILENAME,
    RESULTS_ROOT,
    SCORER_MODULE_PATHS,
    reveal_and_score,
    verify_result,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_IDENTITY_TOKENS = ("FOUNDRY", "BASELINE", "SYSTEM-A", "SYSTEM-B", "Foundry", "Baseline")


@pytest.fixture
def scored_repo(tmp_path: Path) -> Path:
    return build_scored_repo(tmp_path)


@pytest.fixture
def judge_path(scored_repo: Path, tmp_path: Path) -> Path:
    return build_judge_path(scored_repo, tmp_path)


@pytest.fixture
def blob_reader(scored_repo: Path) -> Any:
    return build_blob_reader(scored_repo)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_network(monkeypatch)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    reader: Any,
    spy: _Spy,
    *,
    keep_assignment_door: bool = False,
) -> None:
    """Wire the CLI to synthetic evidence without changing production signatures."""
    harness = _harness(root, spy)
    if keep_assignment_door:
        harness.pop("assignment_reader")

    def _bind(target: Any, **injected: Any) -> Any:
        """Force the synthetic wiring, overriding whatever the CLI supplies."""

        def bound(**kwargs: Any) -> Any:
            return target(**{**kwargs, "blob_reader": reader, **injected})

        return bound

    monkeypatch.setattr(
        phase3_live,
        "blind_preflight",
        _bind(phase3_runner.blind_preflight, phase2_verifier=harness["phase2_verifier"]),
    )
    monkeypatch.setattr(phase3_live, "reveal_and_score", _bind(reveal_and_score, **harness))
    monkeypatch.setattr(phase3_live, "verify_result", _bind(verify_result, **harness))


def _argv(command: str, root: Path, judge: Path) -> list[str]:
    return [
        command,
        "--scorer-commit",
        SCORER_COMMIT,
        "--repo-root",
        str(root),
        "--judge-bundle",
        str(judge),
    ]


def _run(command: str, root: Path, judge: Path) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = main(_argv(command, root, judge), out=lines.append)
    return code, lines


# --------------------------------------------------------------------------- 60-61


def test_preflight_blind_never_invokes_the_assignment_loader(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    def forbidden(_path: Path) -> bytes:
        raise AssertionError("preflight-blind opened the sealed identity mapping")

    monkeypatch.setattr(phase3_runner, "default_assignment_reader", forbidden)
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    code, lines = _run("preflight-blind", scored_repo, judge_path)
    assert code == EXIT_OK
    assert "PHASE3 BLIND PREFLIGHT PASS" in lines
    assert "identity mapping accessed: false" in lines
    assert "model calls: 0" in lines


def test_preflight_blind_makes_no_provider_or_model_call(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    code, _ = _run("preflight-blind", scored_repo, judge_path)
    assert code == EXIT_OK


# --------------------------------------------------------------------------- 62-63


def test_reveal_and_score_runs_preflight_before_the_identity_loader(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    order: list[str] = []
    spy = _Spy()
    _install(monkeypatch, scored_repo, blob_reader, spy, keep_assignment_door=True)

    inner = phase3_live.blind_preflight

    def traced(**kwargs: Any) -> Any:
        order.append("preflight")
        return inner(**kwargs)

    original = phase3_runner.default_assignment_reader

    def door(path: Path) -> bytes:
        order.append("assignment")
        return original(path)

    monkeypatch.setattr(phase3_live, "blind_preflight", traced)
    monkeypatch.setattr(phase3_runner, "default_assignment_reader", door)
    code, _ = _run("reveal-and-score", scored_repo, judge_path)
    assert code == EXIT_OK
    assert order[0] == "preflight"
    assert "assignment" in order


def test_reveal_and_score_opens_the_assignment_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    opens: list[Path] = []
    original = phase3_runner.default_assignment_reader

    def door(path: Path) -> bytes:
        opens.append(path)
        return original(path)

    _install(monkeypatch, scored_repo, blob_reader, _Spy(), keep_assignment_door=True)
    monkeypatch.setattr(phase3_runner, "default_assignment_reader", door)
    code, _ = _run("reveal-and-score", scored_repo, judge_path)
    assert code == EXIT_OK
    assert len(opens) == 1


# --------------------------------------------------------------------------- 64


def test_verify_makes_no_model_call_and_never_rewrites(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    assert _run("reveal-and-score", scored_repo, judge_path)[0] == EXIT_OK
    before = {
        name: (scored_repo / RESULTS_ROOT / name).read_bytes()
        for name in (RESULT_FILENAME, REPORT_FILENAME)
    }
    code, lines = _run("verify", scored_repo, judge_path)
    assert code == EXIT_OK
    assert "PHASE3 COMPARATIVE RESULT VERIFIED" in lines
    assert {
        name: (scored_repo / RESULTS_ROOT / name).read_bytes()
        for name in (RESULT_FILENAME, REPORT_FILENAME)
    } == before


# --------------------------------------------------------------------------- 65-68


def _import_closure() -> set[str]:
    """Import the CLI in a FRESH interpreter and report every module it pulled in."""
    code = (
        "import sys, json; "
        "import foundry.evaluation.phase3_live; "
        "print(json.dumps(sorted(sys.modules)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        check=True,
        cwd=str(REPO_ROOT),
        text=True,
    )
    import json as _json

    return set(_json.loads(completed.stdout))


def test_no_phase3_module_imports_a_provider_adapter_or_sdk() -> None:
    """Phase-3 source reaches no provider.

    `xai_sdk` IS transitively present in the closure, and that is not a Phase-3 defect:
    the pre-existing frozen `foundry.evaluation.experiment_manifest` imports the xAI
    adapter to hash the contestant system instructions, and Phase 1 and Phase 2 already
    import that module for `sha256_bytes`. Phase 3 may not modify it. What Phase 3 MUST
    guarantee is that none of its own modules imports an adapter or an SDK, and that
    neither module permitted to construct a provider client is reachable.
    """
    source = _phase3_sources()
    for token in (
        "foundry.adapters",
        "xai_sdk",
        "XAIIntentIntelligence",
        "XAIBaselineIntelligence",
        "import openai",
        "importlib.import_module",
    ):
        assert token not in source

    modules = _import_closure()
    assert "foundry.evaluation.phase1_live" not in modules
    assert "foundry.evaluation.phase2_live" not in modules


def test_no_phase3_command_imports_the_openai_sdk() -> None:
    modules = _import_closure()
    assert not any(name == "openai" or name.startswith("openai.") for name in modules)


def _phase3_sources() -> str:
    return "\n".join(
        (REPO_ROOT / relative).read_text(encoding="utf-8") for relative in SCORER_MODULE_PATHS
    )


def test_no_phase3_module_reads_an_api_key() -> None:
    source = _phase3_sources()
    for token in ("API_KEY", "api_key", "apikey", "Authorization", "bearer"):
        assert token not in source


def test_no_phase3_module_opens_a_network_path() -> None:
    source = _phase3_sources()
    for token in ("import requests", "import httpx", "urllib.request", "http.client",
                  "import socket", "responses.create", "chat.completions"):
        assert token not in source


# --------------------------------------------------------------------------- 69-72


def test_the_safe_pre_reveal_output_contains_no_mapping_and_no_metric(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    _, lines = _run("preflight-blind", scored_repo, judge_path)
    blob = "\n".join(lines)
    for token in _IDENTITY_TOKENS:
        assert token not in blob
    for token in ("recall", "precision", "%", "DIRECTIONAL"):
        assert token not in blob
    for case_id in ("H-001", "H-012"):
        assert case_id not in blob


def test_the_final_output_prints_named_aggregate_metrics_after_reveal(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    code, lines = _run("reveal-and-score", scored_repo, judge_path)
    assert code == EXIT_OK
    blob = "\n".join(lines)
    for required in (
        "Foundry critical semantic recall",
        "Baseline critical semantic recall",
        "Foundry overall semantic recall",
        "Baseline overall semantic recall",
        "Foundry useful semantic precision",
        "Baseline useful semantic precision",
        "Foundry GapKind accuracy",
        "Baseline GapKind accuracy",
        "Foundry unsupported rate",
        "Baseline unsupported rate",
        "Foundry redundancy rate",
        "Baseline redundancy rate",
        "Foundry bundled prediction count",
        "Baseline bundled prediction count",
        "Foundry serious safety violations",
        "Baseline serious safety violations",
        "Foundry exact critical recall",
        "Baseline exact critical recall",
        "Foundry exact overall recall",
        "Baseline exact overall recall",
        "Foundry exact precision",
        "Baseline exact precision",
        "Foundry cost usd",
        "Baseline cost usd",
        "Foundry input tokens",
        "Baseline input tokens",
        "Foundry output tokens",
        "Baseline output tokens",
        "Foundry total wall clock",
        "Baseline total wall clock",
        "Foundry mean wall clock",
        "Baseline mean wall clock",
    ):
        assert required in blob


def test_the_final_cli_prints_the_frozen_directional_conclusion_exactly(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    _, lines = _run("reveal-and-score", scored_repo, judge_path)
    assert "DIRECTIONAL RULE:" in lines
    assert "FOUNDRY_DIRECTIONALLY_APPEARS_BETTER" in lines


def test_no_per_case_semantic_detail_is_ever_printed(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    _, lines = _run("reveal-and-score", scored_repo, judge_path)
    blob = "\n".join(lines)
    for forbidden in (
        "C-001",
        "C-002",
        "P-001",
        "P-002",
        "SYSTEM-A",
        "SYSTEM-B",
        "a material question remains open",
        "the prediction names the same unresolved issue",
        "MATCHED_EXPECTED",
    ):
        assert forbidden not in blob


# --------------------------------------------------------------------------- contract


def test_the_cli_exposes_exactly_the_three_frozen_commands() -> None:
    parser = build_parser()
    actions = [
        action for action in parser._subparsers._group_actions  # noqa: SLF001
    ]
    choices = sorted(actions[0].choices)
    assert choices == ["preflight-blind", "reveal-and-score", "verify"]


def test_a_frozen_result_makes_reveal_and_score_exit_frozen(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    assert _run("reveal-and-score", scored_repo, judge_path)[0] == EXIT_OK
    code, lines = _run("reveal-and-score", scored_repo, judge_path)
    assert code == EXIT_FROZEN
    assert any("ALREADY FROZEN" in line for line in lines)


def test_a_tampered_report_makes_verify_exit_seal(
    monkeypatch: pytest.MonkeyPatch,
    scored_repo: Path,
    judge_path: Path,
    blob_reader: Any,
    no_network: None,
) -> None:
    _install(monkeypatch, scored_repo, blob_reader, _Spy())
    assert _run("reveal-and-score", scored_repo, judge_path)[0] == EXIT_OK
    path = scored_repo / RESULTS_ROOT / REPORT_FILENAME
    path.write_text(path.read_text(encoding="utf-8") + "hand edited\n", encoding="utf-8")
    code, lines = _run("verify", scored_repo, judge_path)
    assert code == EXIT_SEAL
    assert any(REPORT_FILENAME in line for line in lines)
