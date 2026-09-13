"""9P2 T4: the 22-gate scientific preflight (spec §15; brief T4; clarification C2;
v2 revision: gates 21-22).

``preflight`` emits exactly the twenty spec §15 gates followed by the two v2
operational gates, in order, evaluating each against injected Git / command-runner
fakes, a synthetic manifest built from the frozen timeline/expectations/leakage
values, an injected observed ``GRPC_DNS_RESOLVER`` value, and injected request-path
sources. Every gate is proven to pass on correct input and to fail on one specific
corruption. Nothing here shells out, reads the environment, or constructs a provider
client; ZERO live calls.
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION_SHA256,
)
from foundry.experiments.contrastive_unseen import integrity as integrity_module
from foundry.experiments.contrastive_unseen.expectations import expectations_document
from foundry.experiments.contrastive_unseen.integrity import (
    GATE_NAMES,
    GRPC_DNS_RESOLVER_ENV,
    GRPC_DNS_RESOLVER_FROZEN,
    MANIFEST_KEY_A_POLICY_VERSION,
    MANIFEST_KEY_A_PROMPT_SHA256,
    MANIFEST_KEY_ARM_SCHEDULE,
    MANIFEST_KEY_CEILINGS,
    MANIFEST_KEY_EVIDENCE,
    MANIFEST_KEY_EXPECTATIONS_SHA256,
    MANIFEST_KEY_FR_POLICY_VERSION,
    MANIFEST_KEY_FR_PROMPT_SHA256,
    MANIFEST_KEY_GRPC_DNS_RESOLVER,
    MANIFEST_KEY_HARNESS_CODE_SHA,
    MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256,
    MANIFEST_KEY_OUTPUT_SCHEMA_SHA256,
    MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA,
    PREREGISTRATION_FILES,
    REQUIRED_MANIFEST_KEYS,
    REQUIRED_REQUEST_PATH_MODULES,
    SCOPE_CLOSURE_REGRESSION_ARGV,
    TRACK_A_REGRESSION_ARGV,
    V1_ABORT_EVIDENCE_SHA,
    V1_ARTIFACT_DIR,
    GateResult,
    all_passed,
    canonical_sha256,
    preflight,
    request_path_import_gate,
)
from foundry.experiments.contrastive_unseen.leakage import LeakageResult, run_leakage_gate
from foundry.experiments.contrastive_unseen.timeline import (
    ARM_SCHEDULE,
    FROZEN_CORE_SHA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MAX_HUMAN_AUTHORIZATIONS,
    MAX_JUDGE_CALLS,
    evidence_records,
)

EXPECTED_GATE_NAMES = (
    "head_equals_final_seal",
    "worktree_clean",
    "seal_descends_from_frozen_core",
    "core_paths_unchanged_since_frozen_core",
    "fr_policy_is_9p2",
    "fr_prompt_hash_frozen",
    "a_policy_is_9p",
    "a_prompt_hash_frozen",
    "output_schema_hash_frozen",
    "f_calls_per_delta_is_2",
    "a_two_calls_no_retry",
    "r_uses_fresh_ledger_per_t",
    "evidence_manifest_frozen",
    "arm_schedule_frozen",
    "ceilings_frozen",
    "answer_key_not_imported_by_request_path",
    "contrastive_leakage_gate_passes",
    "track_a_regression_passes",
    "scope_closure_regression_passes",
    "historical_9p_artifacts_unchanged",
    "grpc_dns_resolver_is_native",
    "v1_abort_artifacts_unchanged",
)

HARNESS_SHA = "a" * 40
SEAL_SHA = "5" * 40
V1_SHA = "53b7bf15fc51bf573f34efb1d98d370586423097"
EXPERIMENT_DIR = "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/"
V1_DIR = "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/"
HISTORICAL_DIR = (
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/"
)
HISTORICAL_V1_DIR = (
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/"
)
NOT_9P_DIR = "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/"
PACKAGE_DIR = Path("src/foundry/experiments/contrastive_unseen")
HARNESS_CHANGES = (
    "src/foundry/experiments/contrastive_unseen/records.py",
    "src/foundry/experiments/contrastive_unseen/runner.py",
    "tests/unit/test_contrastive_unseen_records.py",
    "scripts/run_contrastive_unseen.py",
    "docs/superpowers/plans/2026-09-12-9p2-unseen-lifecycle-experiment.md",
    *PREREGISTRATION_FILES,
)
V2_CHANGES_SINCE_V1_ABORT = (
    "src/foundry/experiments/contrastive_unseen/integrity.py",
    "src/foundry/experiments/contrastive_unseen/artifacts.py",
    "scripts/run_contrastive_unseen_lifecycle.py",
    "tests/unit/test_contrastive_unseen_integrity.py",
    *PREREGISTRATION_FILES,
)
"""What the v2 revision changed between the v1 abort commit and the v2 seal: harness
source, scripts, tests and the v2 seal files -- nothing under the v1 directory."""

RUNNER_SOURCE_OK = '''"""Synthetic runner fixture (T5 does not exist yet at T4)."""

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_governance import SemanticGovernor


def run_reconstruction_step(t: int) -> SemanticGovernor:
    store = InMemoryEventStore()
    return SemanticGovernor(store=store, project_id="P", policy=None, clock=None)
'''

RUNNER_SOURCE_SHARED_LEDGER = '''"""Synthetic runner whose R path reuses a shared store."""

from foundry.adapters.memory.event_store import InMemoryEventStore

SHARED = InMemoryEventStore()


def run_persistent_step(t: int) -> None:
    fresh = InMemoryEventStore()
    del fresh


def run_reconstruction_step(t: int) -> object:
    return SHARED
'''

ABLATION_SOURCE_THREE_CALLS = """
def assimilate_ablation_delta(governor, reasoner, delta):
    governor.propose_and_submit(reasoner, delta)
    governor.propose_and_submit(reasoner, delta)
    governor.propose_and_submit(reasoner, delta)
"""

ABLATION_SOURCE_WITH_TRY = """
def assimilate_ablation_delta(governor, reasoner, delta):
    try:
        governor.propose_and_submit(reasoner, delta)
    except Exception:
        pass
    governor.propose_and_submit(reasoner, delta)
"""

ABLATION_SOURCE_WITH_RETRY = """
def _retry(call):
    return call()


def assimilate_ablation_delta(governor, reasoner, delta):
    _retry(lambda: governor.propose_and_submit(reasoner, delta))
    governor.propose_and_submit(reasoner, delta)
"""

ABLATION_SOURCE_LOOPED_CALLS = """
def assimilate_ablation_delta(governor, reasoner, delta):
    for _ in range(3):
        governor.propose_and_submit(reasoner, delta)
    governor.propose_and_submit(reasoner, delta)
"""

ABLATION_SOURCE_WHILE_CALL = """
def assimilate_ablation_delta(governor, reasoner, delta):
    done = False
    while not done:
        done = governor.propose_and_submit(reasoner, delta)
    governor.propose_and_submit(reasoner, delta)
"""

ABLATION_SOURCE_COMPREHENSION_CALL = """
def assimilate_ablation_delta(governor, reasoner, delta):
    decisions = [governor.propose_and_submit(reasoner, request) for request in delta]
    governor.propose_and_submit(reasoner, delta)
    return decisions
"""

RUNNER_SOURCE_SHARED_STORE_LOOPED_GOVERNORS = '''"""One store across every T (must fail)."""

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_governance import SemanticGovernor


def run_reconstruction_arm(steps: tuple[int, ...]) -> list[SemanticGovernor]:
    store = InMemoryEventStore()
    governors = []
    for t in steps:
        governors.append(SemanticGovernor(store=store, project_id="P", policy=None, clock=None))
    return governors
'''

RUNNER_SOURCE_STORE_UNDER_LOOP = '''"""Store constructed under a loop in the T function."""

from foundry.adapters.memory.event_store import InMemoryEventStore


def run_reconstruction_step(t: int) -> object:
    stores = []
    for _ in range(1):
        stores.append(InMemoryEventStore())
    return stores[0]
'''

RUNNER_SOURCE_NO_T_PARAMETER = '''"""A reconstruction function without a ``t`` parameter."""

from foundry.adapters.memory.event_store import InMemoryEventStore


def run_reconstruction_step(step: int) -> object:
    return InMemoryEventStore()
'''

RUNNER_SOURCE_LOOPED_STORE_ELSEWHERE = '''"""T function clean; another function loops stores."""

from foundry.adapters.memory.event_store import InMemoryEventStore


def run_reconstruction_step(t: int) -> object:
    return InMemoryEventStore()


def warm_pool(n: int) -> list[object]:
    return [InMemoryEventStore() for _ in range(n)]
'''


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(scope="module")
def leakage_ok() -> LeakageResult:
    result = run_leakage_gate()
    assert result.passed
    return result


# --- fakes ------------------------------------------------------------------------


class FakeGit:
    def __init__(
        self,
        *,
        head: str = SEAL_SHA,
        dirty: str = "",
        parents: dict[str, tuple[str, ...]] | None = None,
        ancestors: frozenset[tuple[str, str]] = frozenset(
            {(FROZEN_CORE_SHA, SEAL_SHA), (V1_SHA, SEAL_SHA)}
        ),
        changed: dict[tuple[str, str], tuple[str, ...]] | None = None,
        head_error: BaseException | None = None,
    ) -> None:
        self._head = head
        self._dirty = dirty
        self._parents = parents if parents is not None else {SEAL_SHA: (HARNESS_SHA,)}
        self._ancestors = ancestors
        self._changed = (
            changed
            if changed is not None
            else {
                (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
                (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
                (V1_SHA, SEAL_SHA): V2_CHANGES_SINCE_V1_ABORT,
            }
        )
        self._head_error = head_error
        self.calls: list[tuple[str, ...]] = []

    def head(self) -> str:
        self.calls.append(("head",))
        if self._head_error is not None:
            raise self._head_error
        return self._head

    def dirty(self) -> str:
        self.calls.append(("dirty",))
        return self._dirty

    def parents(self, sha: str) -> tuple[str, ...]:
        self.calls.append(("parents", sha))
        return self._parents.get(sha, ())

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        self.calls.append(("is_ancestor", ancestor, descendant))
        return (ancestor, descendant) in self._ancestors

    def changed_paths(self, base: str, head: str) -> tuple[str, ...]:
        self.calls.append(("changed_paths", base, head))
        return self._changed.get((base, head), ())

    def show_bytes(self, sha: str, path: str) -> bytes:
        self.calls.append(("show_bytes", sha, path))
        return b""


class FakeCommands:
    def __init__(self, exit_codes: dict[tuple[str, ...], int] | None = None) -> None:
        self._exit_codes = exit_codes or {}
        self.argvs: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> tuple[int, str]:
        self.argvs.append(argv)
        code = self._exit_codes.get(argv, 0)
        return code, f"fake output for {' '.join(argv)} (exit {code})"


# --- builders ---------------------------------------------------------------------


def _manifest(leakage: LeakageResult) -> dict[str, Any]:
    manifest = {
        MANIFEST_KEY_HARNESS_CODE_SHA: HARNESS_SHA,
        MANIFEST_KEY_FR_POLICY_VERSION: CONTRASTIVE_POLICY_VERSION,
        MANIFEST_KEY_FR_PROMPT_SHA256: CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
        MANIFEST_KEY_A_POLICY_VERSION: POLICY_VERSION,
        MANIFEST_KEY_A_PROMPT_SHA256: SYSTEM_INSTRUCTION_SHA256,
        MANIFEST_KEY_OUTPUT_SCHEMA_SHA256: SEMANTIC_OUTPUT_SCHEMA_SHA256,
        MANIFEST_KEY_ARM_SCHEDULE: [[t, arm] for t, arm in ARM_SCHEDULE],
        MANIFEST_KEY_CEILINGS: {
            "max_frontier_calls": MAX_FRONTIER_CALLS,
            "max_judge_calls": MAX_JUDGE_CALLS,
            "max_human_authorizations": MAX_HUMAN_AUTHORIZATIONS,
            "max_cost_usd": MAX_COST_USD,
        },
        MANIFEST_KEY_EVIDENCE: [record.model_dump(mode="json") for record in evidence_records()],
        MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256: leakage.needle_set_sha256,
        MANIFEST_KEY_EXPECTATIONS_SHA256: canonical_sha256(expectations_document()),
        MANIFEST_KEY_GRPC_DNS_RESOLVER: "native",
        MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA: V1_SHA,
    }
    # Round-trip as the on-disk manifest would arrive.
    loaded = json.loads(json.dumps(manifest))
    assert isinstance(loaded, dict)
    return loaded


def _expectations_bytes() -> bytes:
    return json.dumps(expectations_document(), indent=2).encode("utf-8")


def _real_source(name: str) -> str:
    return (PACKAGE_DIR / name).read_text(encoding="utf-8")


def _sources(**overrides: str | None) -> dict[str, str]:
    sources: dict[str, str] = {
        "timeline.py": _real_source("timeline.py"),
        "designation.py": _real_source("designation.py"),
        "authority.py": _real_source("authority.py"),
        "ablation.py": _real_source("ablation.py"),
        "records.py": _real_source("records.py"),
        "runner.py": RUNNER_SOURCE_OK,
    }
    for key, value in overrides.items():
        if value is None:
            sources.pop(key)
        else:
            sources[key] = value
    return sources


def _run(
    leakage: LeakageResult,
    *,
    git: FakeGit | None = None,
    commands: FakeCommands | None = None,
    frozen_sha: str = SEAL_SHA,
    manifest: dict[str, Any] | None = None,
    expectations_bytes: bytes | None = None,
    sources: dict[str, str] | None = None,
    leakage_override: LeakageResult | None = None,
    observed_grpc_dns_resolver: str | None = "native",
) -> dict[str, GateResult]:
    results = preflight(
        git=git or FakeGit(),
        commands=commands or FakeCommands(),
        frozen_sha=frozen_sha,
        manifest=manifest if manifest is not None else _manifest(leakage),
        expectations_bytes=(
            expectations_bytes if expectations_bytes is not None else _expectations_bytes()
        ),
        request_path_sources=sources if sources is not None else _sources(),
        leakage=leakage_override or leakage,
        observed_grpc_dns_resolver=observed_grpc_dns_resolver,
    )
    assert tuple(r.name for r in results) == EXPECTED_GATE_NAMES
    return {r.name: r for r in results}


def _manifest_with(leakage: LeakageResult, key: str, value: Any) -> dict[str, Any]:
    manifest = _manifest(leakage)
    manifest[key] = value
    return manifest


# --- shape ------------------------------------------------------------------------


def test_gate_names_are_the_twenty_spec_gates_then_the_two_v2_gates_in_order() -> None:
    assert GATE_NAMES == EXPECTED_GATE_NAMES
    assert len(GATE_NAMES) == 22
    assert GATE_NAMES[:20] == EXPECTED_GATE_NAMES[:20]
    assert GATE_NAMES[20:] == ("grpc_dns_resolver_is_native", "v1_abort_artifacts_unchanged")


def test_exported_constants_name_the_request_path_and_preregistration_files() -> None:
    assert REQUIRED_REQUEST_PATH_MODULES == (
        "timeline.py",
        "designation.py",
        "authority.py",
        "ablation.py",
        "records.py",
        "runner.py",
    )
    assert PREREGISTRATION_FILES == (
        EXPERIMENT_DIR + "manifest.json",
        EXPERIMENT_DIR + "expectations.json",
    )
    assert REQUIRED_MANIFEST_KEYS == (
        "harness_code_sha",
        "fr_policy_version",
        "fr_prompt_sha256",
        "a_policy_version",
        "a_prompt_sha256",
        "output_schema_sha256",
        "arm_schedule",
        "ceilings",
        "evidence",
        "leakage_needle_set_sha256",
        "expectations_sha256",
        "grpc_dns_resolver",
        "v1_abort_evidence_sha",
    )
    assert TRACK_A_REGRESSION_ARGV == (
        "uv",
        "run",
        "pytest",
        "-q",
        "tests/unit/test_9p2_track_a_regression.py",
    )
    assert SCOPE_CLOSURE_REGRESSION_ARGV == (
        "uv",
        "run",
        "pytest",
        "-q",
        "tests/unit/test_incremental_assimilation.py",
        "-k",
        "shared_predecessor_never_widens_call_two_into_another_scope or "
        "project_wide_address_remains_eligible_for_a_scoped_delta",
    )


def test_all_gates_pass_on_correct_input(leakage_ok: LeakageResult) -> None:
    git = FakeGit()
    commands = FakeCommands()
    results = _run(leakage_ok, git=git, commands=commands)
    failing = [(name, r.detail) for name, r in results.items() if not r.passed]
    assert failing == []
    assert all_passed(results.values())
    assert commands.argvs == [TRACK_A_REGRESSION_ARGV, SCOPE_CLOSURE_REGRESSION_ARGV]


def test_all_passed_is_false_for_no_results_or_any_failure() -> None:
    assert all_passed(()) is False
    ok = GateResult(name="x", passed=True, detail="")
    bad = GateResult(name="y", passed=False, detail="")
    assert all_passed((ok,)) is True
    assert all_passed((ok, bad)) is False


def test_gate_result_is_frozen() -> None:
    result = GateResult(name="x", passed=True, detail="")
    with pytest.raises(Exception, match="frozen"):
        result.passed = False  # type: ignore[misc]


# --- gates 1-4: git ---------------------------------------------------------------


def test_gate_1_fails_when_head_is_not_the_seal(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, git=FakeGit(head="9" * 40))
    assert results["head_equals_final_seal"].passed is False
    assert SEAL_SHA in results["head_equals_final_seal"].detail


def test_gate_1_fails_when_seal_parent_is_not_the_harness_code_commit(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, git=FakeGit(parents={SEAL_SHA: ("c" * 40,)}))
    assert results["head_equals_final_seal"].passed is False
    assert HARNESS_SHA in results["head_equals_final_seal"].detail


def test_gate_1_fails_when_seal_is_a_merge_commit(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, git=FakeGit(parents={SEAL_SHA: (HARNESS_SHA, "c" * 40)}))
    assert results["head_equals_final_seal"].passed is False


def test_gate_1_fails_when_seal_changes_anything_but_the_two_prereg_files(
    leakage_ok: LeakageResult,
) -> None:
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): (*PREREGISTRATION_FILES, HARNESS_CHANGES[0]),
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["head_equals_final_seal"].passed is False
    assert HARNESS_CHANGES[0] in results["head_equals_final_seal"].detail

    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): (PREREGISTRATION_FILES[0],),
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
        }
    )
    assert _run(leakage_ok, git=git)["head_equals_final_seal"].passed is False


def test_gate_1_accepts_prereg_files_in_any_order(leakage_ok: LeakageResult) -> None:
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): tuple(reversed(PREREGISTRATION_FILES)),
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
        }
    )
    assert _run(leakage_ok, git=git)["head_equals_final_seal"].passed is True


def test_gate_2_fails_on_a_dirty_worktree(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, git=FakeGit(dirty=" M src/foundry/x.py\n"))
    assert results["worktree_clean"].passed is False
    assert "src/foundry/x.py" in results["worktree_clean"].detail
    assert _run(leakage_ok, git=FakeGit(dirty="\n"))["worktree_clean"].passed is True


def test_gate_3_fails_when_seal_does_not_descend_from_frozen_core(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, git=FakeGit(ancestors=frozenset()))
    assert results["seal_descends_from_frozen_core"].passed is False
    assert FROZEN_CORE_SHA in results["seal_descends_from_frozen_core"].detail


@pytest.mark.parametrize(
    "core_path",
    [
        "src/foundry/domain/evidence.py",
        "src/foundry/application/assimilation_context.py",
        "src/foundry/ports/semantic_reasoner.py",
        "src/foundry/adapters/semantics/xai_reasoner.py",
    ],
)
def test_gate_4_fails_when_a_core_path_changed_since_frozen_core(
    leakage_ok: LeakageResult, core_path: str
) -> None:
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): (*HARNESS_CHANGES, core_path),
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["core_paths_unchanged_since_frozen_core"].passed is False
    assert core_path in results["core_paths_unchanged_since_frozen_core"].detail


def test_gate_4_allows_experiment_scripts_tests_and_docs(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok)
    assert results["core_paths_unchanged_since_frozen_core"].passed is True
    # ``src/foundry/experiments/`` is not a core prefix even though it starts with src/foundry/.
    assert "src/foundry/experiments/contrastive_unseen/records.py" in HARNESS_CHANGES


# --- gates 5-9: policy identity ---------------------------------------------------


@pytest.mark.parametrize(
    ("gate", "key"),
    [
        ("fr_policy_is_9p2", MANIFEST_KEY_FR_POLICY_VERSION),
        ("fr_prompt_hash_frozen", MANIFEST_KEY_FR_PROMPT_SHA256),
        ("a_policy_is_9p", MANIFEST_KEY_A_POLICY_VERSION),
        ("a_prompt_hash_frozen", MANIFEST_KEY_A_PROMPT_SHA256),
        ("output_schema_hash_frozen", MANIFEST_KEY_OUTPUT_SCHEMA_SHA256),
    ],
)
def test_identity_gate_fails_when_manifest_value_differs(
    leakage_ok: LeakageResult, gate: str, key: str
) -> None:
    results = _run(leakage_ok, manifest=_manifest_with(leakage_ok, key, "corrupted-value"))
    assert results[gate].passed is False
    assert "corrupted-value" in results[gate].detail
    others = [name for name, r in results.items() if not r.passed and name != gate]
    assert others == []


def test_identity_gates_compare_against_the_frozen_literals(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok)
    assert "intent-v2-9p2-v1" in results["fr_policy_is_9p2"].detail
    assert (
        "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410"
        in results["fr_prompt_hash_frozen"].detail
    )
    assert "intent-v2-9p-v4" in results["a_policy_is_9p"].detail
    assert (
        "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
        in results["a_prompt_hash_frozen"].detail
    )
    assert (
        "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
        in results["output_schema_hash_frozen"].detail
    )


def test_prompt_hash_gate_recomputes_from_the_in_process_instruction(
    leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(integrity_module, "CONTRASTIVE_SYSTEM_INSTRUCTION", "tampered prompt")
    results = _run(leakage_ok)
    assert results["fr_prompt_hash_frozen"].passed is False
    assert hashlib.sha256(b"tampered prompt").hexdigest() in results["fr_prompt_hash_frozen"].detail


# --- gates 10-12: call discipline -------------------------------------------------


def test_gate_10_reads_calls_per_delta(
    leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(leakage_ok)["f_calls_per_delta_is_2"].passed is True
    monkeypatch.setattr(integrity_module, "CALLS_PER_DELTA", 3)
    results = _run(leakage_ok)
    assert results["f_calls_per_delta_is_2"].passed is False
    assert "3" in results["f_calls_per_delta_is_2"].detail


def test_gate_11_passes_on_the_real_ablation_source(leakage_ok: LeakageResult) -> None:
    assert _run(leakage_ok)["a_two_calls_no_retry"].passed is True


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (ABLATION_SOURCE_THREE_CALLS, "3"),
        (ABLATION_SOURCE_WITH_TRY, "try"),
        (ABLATION_SOURCE_WITH_RETRY, "retry"),
    ],
)
def test_gate_11_fails_on_a_third_call_a_try_block_or_a_retry_name(
    leakage_ok: LeakageResult, source: str, reason: str
) -> None:
    results = _run(leakage_ok, sources=_sources(**{"ablation.py": source}))
    assert results["a_two_calls_no_retry"].passed is False
    assert reason in results["a_two_calls_no_retry"].detail


@pytest.mark.parametrize(
    "source",
    [ABLATION_SOURCE_LOOPED_CALLS, ABLATION_SOURCE_WHILE_CALL, ABLATION_SOURCE_COMPREHENSION_CALL],
)
def test_gate_11_fails_when_a_call_site_is_enclosed_by_a_loop_or_comprehension(
    leakage_ok: LeakageResult, source: str
) -> None:
    """Two call SITES under a loop are not two CALLS."""
    results = _run(leakage_ok, sources=_sources(**{"ablation.py": source}))
    assert results["a_two_calls_no_retry"].passed is False
    assert "loop" in results["a_two_calls_no_retry"].detail


def test_gate_11_falls_back_to_the_sibling_file_when_not_injected(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, sources=_sources(**{"ablation.py": None}))
    assert results["a_two_calls_no_retry"].passed is True
    # ... while gate 16 still refuses the incomplete mapping (C2).
    assert results["answer_key_not_imported_by_request_path"].passed is False


def test_gate_12_passes_when_runner_creates_a_fresh_store_in_its_reconstruction_path(
    leakage_ok: LeakageResult,
) -> None:
    assert _run(leakage_ok)["r_uses_fresh_ledger_per_t"].passed is True


def test_gate_12_fails_when_runner_source_is_absent(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, sources=_sources(**{"runner.py": None}))
    assert results["r_uses_fresh_ledger_per_t"].passed is False
    assert "runner.py" in results["r_uses_fresh_ledger_per_t"].detail


def test_gate_12_fails_when_the_reconstruction_path_reuses_a_store(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, sources=_sources(**{"runner.py": RUNNER_SOURCE_SHARED_LEDGER}))
    assert results["r_uses_fresh_ledger_per_t"].passed is False


def test_gate_12_fails_when_one_store_is_shared_across_per_t_governors(
    leakage_ok: LeakageResult,
) -> None:
    """The named violation: one ``InMemoryEventStore()`` then a governor per T in a loop."""
    results = _run(
        leakage_ok, sources=_sources(**{"runner.py": RUNNER_SOURCE_SHARED_STORE_LOOPED_GOVERNORS})
    )
    assert results["r_uses_fresh_ledger_per_t"].passed is False


def test_gate_12_fails_when_the_store_construction_sits_under_a_loop(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, sources=_sources(**{"runner.py": RUNNER_SOURCE_STORE_UNDER_LOOP}))
    assert results["r_uses_fresh_ledger_per_t"].passed is False
    assert "loop" in results["r_uses_fresh_ledger_per_t"].detail


def test_gate_12_fails_when_the_reconstruction_function_has_no_t_parameter(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, sources=_sources(**{"runner.py": RUNNER_SOURCE_NO_T_PARAMETER}))
    assert results["r_uses_fresh_ledger_per_t"].passed is False
    assert "t" in results["r_uses_fresh_ledger_per_t"].detail


def test_gate_12_fails_when_any_store_construction_in_runner_is_under_a_loop(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(
        leakage_ok, sources=_sources(**{"runner.py": RUNNER_SOURCE_LOOPED_STORE_ELSEWHERE})
    )
    assert results["r_uses_fresh_ledger_per_t"].passed is False
    assert "warm_pool" in results["r_uses_fresh_ledger_per_t"].detail


def test_gate_12_fails_on_unparsable_runner_source(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, sources=_sources(**{"runner.py": "def broken(:\n"}))
    assert results["r_uses_fresh_ledger_per_t"].passed is False


# --- gates 13-15: sealed design data ----------------------------------------------


def test_gate_13_fails_when_a_sealed_evidence_hash_differs(leakage_ok: LeakageResult) -> None:
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_EVIDENCE][3]["content_sha256"] = "0" * 64
    results = _run(leakage_ok, manifest=manifest)
    assert results["evidence_manifest_frozen"].passed is False


def test_gate_13_fails_when_evidence_order_or_count_differs(leakage_ok: LeakageResult) -> None:
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_EVIDENCE].reverse()
    assert _run(leakage_ok, manifest=manifest)["evidence_manifest_frozen"].passed is False
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_EVIDENCE].pop()
    assert _run(leakage_ok, manifest=manifest)["evidence_manifest_frozen"].passed is False


def test_gate_14_fails_when_arm_schedule_differs(leakage_ok: LeakageResult) -> None:
    schedule = [[t, arm] for t, arm in ARM_SCHEDULE]
    schedule[0], schedule[1] = schedule[1], schedule[0]
    results = _run(
        leakage_ok, manifest=_manifest_with(leakage_ok, MANIFEST_KEY_ARM_SCHEDULE, schedule)
    )
    assert results["arm_schedule_frozen"].passed is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_frontier_calls", 25),
        ("max_judge_calls", 1),
        ("max_human_authorizations", 15),
        ("max_cost_usd", 9.0),
    ],
)
def test_gate_15_fails_when_a_ceiling_differs(
    leakage_ok: LeakageResult, key: str, value: float
) -> None:
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_CEILINGS][key] = value
    results = _run(leakage_ok, manifest=manifest)
    assert results["ceilings_frozen"].passed is False
    assert key in results["ceilings_frozen"].detail


def test_gate_15_fails_when_a_ceiling_key_is_missing_or_extra(
    leakage_ok: LeakageResult,
) -> None:
    manifest = _manifest(leakage_ok)
    del manifest[MANIFEST_KEY_CEILINGS]["max_judge_calls"]
    assert _run(leakage_ok, manifest=manifest)["ceilings_frozen"].passed is False
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_CEILINGS]["max_retries"] = 0
    assert _run(leakage_ok, manifest=manifest)["ceilings_frozen"].passed is False


def test_gate_15_reports_the_locked_values(leakage_ok: LeakageResult) -> None:
    detail = _run(leakage_ok)["ceilings_frozen"].detail
    for value in ("24", "0", "16", "8.0"):
        assert value in detail


def test_missing_manifest_key_fails_only_the_gate_that_needs_it(
    leakage_ok: LeakageResult,
) -> None:
    manifest = _manifest(leakage_ok)
    del manifest[MANIFEST_KEY_ARM_SCHEDULE]
    results = _run(leakage_ok, manifest=manifest)
    assert results["arm_schedule_frozen"].passed is False
    assert MANIFEST_KEY_ARM_SCHEDULE in results["arm_schedule_frozen"].detail
    assert [n for n, r in results.items() if not r.passed] == ["arm_schedule_frozen"]


# --- gate 16: request-path import hygiene (C2) ------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "import foundry.experiments.contrastive_unseen.expectations",
        "import foundry.experiments.contrastive_unseen.expectations as e",
        "from foundry.experiments.contrastive_unseen.expectations import decision_rule",
        "from foundry.experiments.contrastive_unseen.expectations import GRADING_LABELS as L",
        "from foundry.experiments.contrastive_unseen import expectations",
        "from foundry.experiments.contrastive_unseen import decision_rule",
        "from foundry.experiments.contrastive_unseen import timeline, expectations",
        "from .expectations import GRADING_LABELS",
        "from . import expectations",
        "from . import decision_rule",
        "from ..contrastive_unseen.expectations import ANSWER_KEY_SENTENCES",
        "from ..contrastive_unseen import expectations",
    ],
)
def test_request_path_import_gate_rejects_every_answer_key_import_form(statement: str) -> None:
    sources = {name: "" for name in REQUIRED_REQUEST_PATH_MODULES}
    sources["records.py"] = f"from __future__ import annotations\n{statement}\n"
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "records.py" in detail
    assert "expectations" in detail or "decision_rule" in detail


def test_request_path_import_gate_accepts_clean_sources() -> None:
    sources = {name: "" for name in REQUIRED_REQUEST_PATH_MODULES}
    sources["records.py"] = (
        "from __future__ import annotations\n"
        "import hashlib\n"
        "from foundry.experiments.contrastive_unseen.timeline import TIMELINE\n"
        "from .ablation import assemble_ablation_call1\n"
        "from foundry.ports.semantic_reasoner import ReasoningRequest\n"
    )
    passed, detail = request_path_import_gate(sources)
    assert passed is True
    for name in REQUIRED_REQUEST_PATH_MODULES:
        assert name in detail


def test_request_path_import_gate_passes_on_the_real_modules() -> None:
    passed, _detail = request_path_import_gate(_sources())
    assert passed is True


@pytest.mark.parametrize("missing", REQUIRED_REQUEST_PATH_MODULES)
def test_request_path_import_gate_fails_when_a_required_module_is_missing(
    missing: str,
) -> None:
    sources = _sources(**{missing: None})
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert missing in detail


def test_request_path_import_gate_fails_on_unparsable_source() -> None:
    sources = _sources(**{"authority.py": "def broken(:\n"})
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "authority.py" in detail


def test_request_path_import_gate_scans_extra_supplied_modules_too() -> None:
    sources = _sources()
    sources["integrity.py"] = "from foundry.experiments.contrastive_unseen import expectations\n"
    passed, detail = request_path_import_gate(sources)
    # Extra keys are scanned too: a supplied source is never silently ignored.
    assert passed is False
    assert "integrity.py" in detail


def test_gate_16_fails_when_a_request_path_module_imports_expectations(
    leakage_ok: LeakageResult,
) -> None:
    tainted = _real_source("designation.py") + "\nfrom .expectations import GRADING_LABELS\n"
    results = _run(leakage_ok, sources=_sources(**{"designation.py": tainted}))
    assert results["answer_key_not_imported_by_request_path"].passed is False
    assert "designation.py" in results["answer_key_not_imported_by_request_path"].detail


def test_gate_16_fails_when_runner_source_is_missing(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, sources=_sources(**{"runner.py": None}))
    assert results["answer_key_not_imported_by_request_path"].passed is False
    assert "runner.py" in results["answer_key_not_imported_by_request_path"].detail


# --- gate 17: leakage + seal identity ---------------------------------------------


def test_gate_17_fails_when_the_leakage_gate_failed(leakage_ok: LeakageResult) -> None:
    failed = run_leakage_gate(extra_harness_text=("harness guidance: maximum four total attempts",))
    assert failed.passed is False
    results = _run(leakage_ok, leakage_override=failed)
    assert results["contrastive_leakage_gate_passes"].passed is False
    assert "maximum four total attempts" in results["contrastive_leakage_gate_passes"].detail
    assert "EXTRA_HARNESS_TEXT_0" in results["contrastive_leakage_gate_passes"].detail


def test_gate_17_fails_when_needle_set_sha_differs_from_manifest(
    leakage_ok: LeakageResult,
) -> None:
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256, "0" * 64)
    results = _run(leakage_ok, manifest=manifest)
    assert results["contrastive_leakage_gate_passes"].passed is False


def test_gate_17_fails_when_expectations_bytes_do_not_match_the_sealed_sha(
    leakage_ok: LeakageResult,
) -> None:
    document = expectations_document()
    document["inconclusive_note"] = "tampered"
    tampered = json.dumps(document).encode("utf-8")
    results = _run(leakage_ok, expectations_bytes=tampered)
    assert results["contrastive_leakage_gate_passes"].passed is False
    assert "expectations" in results["contrastive_leakage_gate_passes"].detail


def test_gate_17_accepts_reformatted_expectations_bytes_with_the_same_content(
    leakage_ok: LeakageResult,
) -> None:
    reformatted = json.dumps(expectations_document(), indent=4, sort_keys=True).encode("utf-8")
    assert _run(leakage_ok, expectations_bytes=reformatted)[
        "contrastive_leakage_gate_passes"
    ].passed


def test_gate_17_fails_on_unparsable_expectations_bytes(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, expectations_bytes=b"{not json")
    assert results["contrastive_leakage_gate_passes"].passed is False


def test_gate_17_fails_when_leakage_prompt_hashes_are_not_the_frozen_ones(
    leakage_ok: LeakageResult,
) -> None:
    drifted = leakage_ok.model_copy(update={"fr_prompt_sha256": "1" * 64})
    results = _run(leakage_ok, leakage_override=drifted)
    assert results["contrastive_leakage_gate_passes"].passed is False


def test_canonical_sha256_is_sorted_compact_utf8_json() -> None:
    value = {"b": [1, 2], "a": "é"}
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert canonical_sha256(value) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- gates 18-19: regression commands ---------------------------------------------


def test_gate_18_fails_on_a_non_zero_track_a_exit(leakage_ok: LeakageResult) -> None:
    commands = FakeCommands({TRACK_A_REGRESSION_ARGV: 1})
    results = _run(leakage_ok, commands=commands)
    assert results["track_a_regression_passes"].passed is False
    assert "exit 1" in results["track_a_regression_passes"].detail
    assert results["scope_closure_regression_passes"].passed is True


def test_gate_19_fails_on_a_non_zero_scope_closure_exit(leakage_ok: LeakageResult) -> None:
    commands = FakeCommands({SCOPE_CLOSURE_REGRESSION_ARGV: 2})
    results = _run(leakage_ok, commands=commands)
    assert results["scope_closure_regression_passes"].passed is False
    assert results["track_a_regression_passes"].passed is True


def test_regression_gates_run_exactly_the_two_brief_commands(leakage_ok: LeakageResult) -> None:
    commands = FakeCommands()
    _run(leakage_ok, commands=commands)
    assert commands.argvs == [TRACK_A_REGRESSION_ARGV, SCOPE_CLOSURE_REGRESSION_ARGV]


# --- gate 20: historical 9P artifacts ---------------------------------------------


@pytest.mark.parametrize("historical_dir", [HISTORICAL_DIR, HISTORICAL_V1_DIR])
def test_gate_20_fails_when_a_historical_9p_artifact_changed(
    leakage_ok: LeakageResult, historical_dir: str
) -> None:
    touched = historical_dir + "manifest.json"
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): (*HARNESS_CHANGES, touched),
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["historical_9p_artifacts_unchanged"].passed is False
    assert touched in results["historical_9p_artifacts_unchanged"].detail


def test_gate_20_protects_exactly_the_two_historical_9p_directories() -> None:
    """Spec §15.20: both previous 9P experiment directories are protected; the self-dogfood
    directory is not 9P evidence. The v2 directory keeps its sealed manifest field."""
    assert integrity_module.HISTORICAL_9P_ARTIFACT_DIRS == (HISTORICAL_DIR, HISTORICAL_V1_DIR)
    assert integrity_module.HISTORICAL_9P_ARTIFACT_DIR == HISTORICAL_DIR
    assert NOT_9P_DIR not in integrity_module.HISTORICAL_9P_ARTIFACT_DIRS
    for directory in integrity_module.HISTORICAL_9P_ARTIFACT_DIRS:
        assert Path(directory).is_dir(), directory


def test_gate_20_ignores_the_non_9p_experiment_directory(leakage_ok: LeakageResult) -> None:
    touched = NOT_9P_DIR + "notes.md"
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): (*HARNESS_CHANGES, touched),
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["historical_9p_artifacts_unchanged"].passed is True


# --- v2 revision: frozen operational constants -------------------------------------


def test_v2_frozen_constants_are_the_preregistered_literals() -> None:
    assert GRPC_DNS_RESOLVER_ENV == "GRPC_DNS_RESOLVER"
    assert GRPC_DNS_RESOLVER_FROZEN == "native"
    assert MANIFEST_KEY_GRPC_DNS_RESOLVER == "grpc_dns_resolver"
    assert MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA == "v1_abort_evidence_sha"
    assert V1_ABORT_EVIDENCE_SHA == V1_SHA
    assert V1_ARTIFACT_DIR == V1_DIR
    assert integrity_module.EXPERIMENT_ARTIFACT_DIR == EXPERIMENT_DIR
    assert all(path.startswith(EXPERIMENT_DIR) for path in PREREGISTRATION_FILES)
    for name in (
        "GRPC_DNS_RESOLVER_ENV",
        "GRPC_DNS_RESOLVER_FROZEN",
        "MANIFEST_KEY_GRPC_DNS_RESOLVER",
        "MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA",
        "V1_ABORT_EVIDENCE_SHA",
        "V1_ARTIFACT_DIR",
    ):
        assert name in integrity_module.__all__, name
    # Gate 22 is separate from gate 20: the v1 directory is not a historical 9P dir.
    assert V1_DIR not in integrity_module.HISTORICAL_9P_ARTIFACT_DIRS
    assert Path(V1_DIR).is_dir()


def test_integrity_source_never_touches_the_environment() -> None:
    """The observed resolver value is injected by the CLI; integrity.py reads no env."""
    source = Path(integrity_module.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in source
    assert "getenv" not in source
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "os" not in imported


def test_no_package_module_sets_grpc_dns_resolver() -> None:
    """v2 preregisters the resolver; no module under the package sets or mutates the
    environment (``os.environ[...] =``, ``putenv``, ``environ.setdefault``). Plain
    ``dict.setdefault`` on a local mapping is not environment mutation."""
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "os.environ[" not in source, path
        assert "putenv" not in source, path
        assert "environ.setdefault" not in source, path
        for line in source.splitlines():
            if "setdefault" in line:
                assert "environ" not in line, (path, line)
                assert "GRPC_DNS_RESOLVER" not in line, (path, line)


# --- gate 21: GRPC_DNS_RESOLVER is native ------------------------------------------


def test_gate_21_passes_when_observed_and_sealed_are_both_native(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, observed_grpc_dns_resolver="native")
    gate = results["grpc_dns_resolver_is_native"]
    assert gate.passed is True
    assert gate.detail == "GRPC_DNS_RESOLVER=native (observed == sealed == frozen)"


@pytest.mark.parametrize("observed", [None, "", "ares", "Native", "native ", " native"])
def test_gate_21_fails_for_every_non_native_observed_value(
    leakage_ok: LeakageResult, observed: str | None
) -> None:
    results = _run(leakage_ok, observed_grpc_dns_resolver=observed)
    gate = results["grpc_dns_resolver_is_native"]
    assert gate.passed is False
    assert "observed" in gate.detail
    assert repr(observed) in gate.detail
    assert [n for n, r in results.items() if not r.passed] == ["grpc_dns_resolver_is_native"]


@pytest.mark.parametrize("sealed", ["ares", "Native", "", None])
def test_gate_21_fails_when_the_manifest_value_is_not_native(
    leakage_ok: LeakageResult, sealed: str | None
) -> None:
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_GRPC_DNS_RESOLVER, sealed)
    results = _run(leakage_ok, manifest=manifest, observed_grpc_dns_resolver="native")
    gate = results["grpc_dns_resolver_is_native"]
    assert gate.passed is False
    assert "manifest" in gate.detail
    assert MANIFEST_KEY_GRPC_DNS_RESOLVER in gate.detail
    assert [n for n, r in results.items() if not r.passed] == ["grpc_dns_resolver_is_native"]


def test_gate_21_fails_when_the_manifest_key_is_missing(leakage_ok: LeakageResult) -> None:
    manifest = _manifest(leakage_ok)
    del manifest[MANIFEST_KEY_GRPC_DNS_RESOLVER]
    results = _run(leakage_ok, manifest=manifest, observed_grpc_dns_resolver="native")
    gate = results["grpc_dns_resolver_is_native"]
    assert gate.passed is False
    assert MANIFEST_KEY_GRPC_DNS_RESOLVER in gate.detail
    assert [n for n, r in results.items() if not r.passed] == ["grpc_dns_resolver_is_native"]


def test_preflight_requires_the_observed_resolver_keyword(leakage_ok: LeakageResult) -> None:
    with pytest.raises(TypeError, match="observed_grpc_dns_resolver"):
        preflight(  # type: ignore[call-arg]
            git=FakeGit(),
            commands=FakeCommands(),
            frozen_sha=SEAL_SHA,
            manifest=_manifest(leakage_ok),
            expectations_bytes=_expectations_bytes(),
            request_path_sources=_sources(),
            leakage=leakage_ok,
        )


# --- gate 22: v1 abort evidence preserved ---------------------------------------


def test_gate_22_passes_when_v1_abort_is_an_ancestor_and_no_v1_path_changed(
    leakage_ok: LeakageResult,
) -> None:
    git = FakeGit()
    results = _run(leakage_ok, git=git)
    gate = results["v1_abort_artifacts_unchanged"]
    assert gate.passed is True, gate.detail
    assert V1_SHA in gate.detail
    assert ("is_ancestor", V1_SHA, SEAL_SHA) in git.calls
    assert ("changed_paths", V1_SHA, SEAL_SHA) in git.calls


@pytest.mark.parametrize(
    "touched",
    [
        V1_DIR + "F/result.json",
        V1_DIR + "manifest.json",
        V1_DIR + "preflight.json",
        V1_DIR + "R/T3/requests.json",
    ],
)
def test_gate_22_fails_when_a_v1_artifact_changed_since_the_abort(
    leakage_ok: LeakageResult, touched: str
) -> None:
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
            (V1_SHA, SEAL_SHA): (*V2_CHANGES_SINCE_V1_ABORT, touched),
        }
    )
    results = _run(leakage_ok, git=git)
    gate = results["v1_abort_artifacts_unchanged"]
    assert gate.passed is False
    assert touched in gate.detail
    assert [n for n, r in results.items() if not r.passed] == ["v1_abort_artifacts_unchanged"]


def test_gate_22_fails_when_the_v1_abort_is_not_an_ancestor_of_the_seal(
    leakage_ok: LeakageResult,
) -> None:
    git = FakeGit(ancestors=frozenset({(FROZEN_CORE_SHA, SEAL_SHA)}))
    results = _run(leakage_ok, git=git)
    gate = results["v1_abort_artifacts_unchanged"]
    assert gate.passed is False
    assert V1_SHA in gate.detail
    assert "ancestor" in gate.detail
    assert [n for n, r in results.items() if not r.passed] == ["v1_abort_artifacts_unchanged"]


@pytest.mark.parametrize("sealed", ["0" * 40, "53B7BF15FC51BF573F34EFB1D98D370586423097", ""])
def test_gate_22_fails_when_the_manifest_v1_sha_differs(
    leakage_ok: LeakageResult, sealed: str
) -> None:
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA, sealed)
    results = _run(leakage_ok, manifest=manifest)
    gate = results["v1_abort_artifacts_unchanged"]
    assert gate.passed is False
    assert MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA in gate.detail
    assert [n for n, r in results.items() if not r.passed] == ["v1_abort_artifacts_unchanged"]


def test_gate_22_fails_when_the_manifest_v1_sha_is_missing(leakage_ok: LeakageResult) -> None:
    manifest = _manifest(leakage_ok)
    del manifest[MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA]
    results = _run(leakage_ok, manifest=manifest)
    assert results["v1_abort_artifacts_unchanged"].passed is False
    assert MANIFEST_KEY_V1_ABORT_EVIDENCE_SHA in results["v1_abort_artifacts_unchanged"].detail
    assert [n for n, r in results.items() if not r.passed] == ["v1_abort_artifacts_unchanged"]


def test_gate_22_is_independent_of_gate_20(leakage_ok: LeakageResult) -> None:
    """A change under the v1 directory fails gate 22 only; a change under a historical
    9P directory fails gate 20 only. Neither gate reads the other's base commit."""
    v1_touched = V1_DIR + "verdicts.json"
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
            (V1_SHA, SEAL_SHA): (*V2_CHANGES_SINCE_V1_ABORT, v1_touched),
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["historical_9p_artifacts_unchanged"].passed is True
    assert results["v1_abort_artifacts_unchanged"].passed is False

    historical_touched = HISTORICAL_DIR + "manifest.json"
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): (*HARNESS_CHANGES, historical_touched),
            (V1_SHA, SEAL_SHA): V2_CHANGES_SINCE_V1_ABORT,
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["historical_9p_artifacts_unchanged"].passed is False
    assert results["v1_abort_artifacts_unchanged"].passed is True


# --- failure discipline -----------------------------------------------------------


def test_a_raising_gate_is_a_failed_gate_and_the_rest_still_run(
    leakage_ok: LeakageResult,
) -> None:
    git = FakeGit(head_error=OSError("GIT_UNAVAILABLE_ALPHA"))
    results = _run(leakage_ok, git=git)
    assert results["head_equals_final_seal"].passed is False
    assert "GIT_UNAVAILABLE_ALPHA" in results["head_equals_final_seal"].detail
    assert len(results) == 22
    assert results["worktree_clean"].passed is True


def test_preflight_never_shells_out_or_reads_the_network(leakage_ok: LeakageResult) -> None:
    commands = FakeCommands()
    git = FakeGit()
    _run(leakage_ok, git=git, commands=commands)
    # Every command ran through the injected runner; every git fact came from the fake.
    assert len(commands.argvs) == 2
    assert ("head",) in git.calls
    assert ("dirty",) in git.calls
