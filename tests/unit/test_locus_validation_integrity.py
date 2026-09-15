"""T5: the 18-gate preflight (spec §8) and the post-run verdicts L1-L9 (spec §8, §14
rule 0, §17) of the locus-validation experiment.

``preflight`` is driven with a fake Git, a synthetic manifest built from the frozen
T1/T2 values and the ``MANIFEST_KEY_*`` names, injected request-path sources, the
real T6 leakage result and an injected observed ``GRPC_DNS_RESOLVER``; every gate is
proven to pass on correct input and to fail on one specific corruption each. The gate
list carries no test-suite gate (§8.1) and the module never shells out, reads the
environment or constructs the adapter (AST). ``integrity_verdicts`` is driven with
scripted ``RunResult``s produced by the T3 specification fakes through the real
governor path (reused from ``test_locus_validation_runner``); every verdict L1-L9 is
proven to PASS on a completed run and to FAIL under one mutation each, with per-ledger
attribution. ZERO live calls; sockets are blocked; no key is read.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_locus_validation_runner import (
    EconomicsFake,
    LocusFake,
    _run,
    _script,
)

from foundry.adapters.semantics.xai_reasoner import (
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    XAIProviderError,
)
from foundry.domain.events import (
    EventType,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.semantic_judgment import AdmissionRoute, JudgmentKind, SemanticJudgment
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.contrastive_unseen.integrity import GateResult, all_passed
from foundry.experiments.intent_v2_dogfood import ReplayResult
from foundry.experiments.locus_validation import integrity as integrity_module
from foundry.experiments.locus_validation.corpus import (
    LEDGERS,
    Ledger,
    corpus_sha256,
    evidence_records,
)
from foundry.experiments.locus_validation.evaluation import CaseResult, evaluate_run
from foundry.experiments.locus_validation.expectations import (
    CASE_IDS,
    FAILURE_TAGS,
    expectations_document,
)
from foundry.experiments.locus_validation.integrity import (
    GATE_NAMES,
    LOCKED_CEILINGS,
    MANIFEST_KEY_CALLS_PER_DELTA,
    MANIFEST_KEY_CEILINGS,
    MANIFEST_KEY_CORPUS_SHA256,
    MANIFEST_KEY_EVIDENCE,
    MANIFEST_KEY_EXPECTATIONS_SHA256,
    MANIFEST_KEY_GRPC_DNS_RESOLVER,
    MANIFEST_KEY_HARNESS_CODE_SHA,
    MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES,
    MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA,
    MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S,
    MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256,
    MANIFEST_KEY_MODEL,
    MANIFEST_KEY_OUTPUT_SCHEMA_SHA256,
    MANIFEST_KEY_POLICY_VERSION,
    MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA,
    MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA,
    MANIFEST_KEY_PROMPT_SHA256,
    MANIFEST_KEY_PROVIDER,
    MANIFEST_KEY_RAW_ARTIFACT_PATHS,
    MANIFEST_KEY_REASONING_EFFORT,
    PREREGISTRATION_FILES,
    RAW_ARTIFACT_PATH_COUNT,
    REQUIRED_MANIFEST_KEYS,
    VERDICT_IDS,
    IntegrityVerdict,
    integrity_verdicts,
    preflight,
)
from foundry.experiments.locus_validation.leakage import (
    REQUEST_PATH_MODULES,
    LeakageResult,
    run_leakage_gate,
)
from foundry.experiments.locus_validation.protocol import (
    BASELINE_SHA,
    CEILING_KEYS,
    DESIGN_BASE_SHA,
    EXPERIMENT_ARTIFACT_DIR,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PROMPT_SHA256S,
    MODEL,
    PREDECESSOR_ADJUDICATION_SHA,
    PREDECESSOR_ARTIFACT_DIR,
    PREDECESSOR_RAW_RUN_SHA,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.recording import IdentityDrift
from foundry.experiments.locus_validation.runner import (
    DeltaRecord,
    LedgerRecord,
    RunResult,
    RunStatus,
)
from foundry.experiments.long_horizon_bounded.runner import RequestReferenceSnapshot

PACKAGE_DIR = Path("src/foundry/experiments/locus_validation")
INTEGRITY_SOURCE = PACKAGE_DIR / "integrity.py"

SEAL_SHA = "a" * 40
HARNESS_SHA = "b" * 40
OTHER_SHA = "c" * 40

EXPERIMENT_DIR = "docs/superpowers/experiments/2026-09-15-locus-validation-v1/"
PREREG_FILES = (EXPERIMENT_DIR + "manifest.json", EXPERIMENT_DIR + "expectations.json")

EXPECTED_GATE_NAMES = (
    "head_equals_final_seal",
    "worktree_clean",
    "seal_descends_from_baseline",
    "locus_policy_frozen",
    "locus_prompt_hash_frozen",
    "output_schema_hash_frozen",
    "historical_prompts_unchanged",
    "model_configuration_frozen",
    "calls_per_delta_is_2",
    "evidence_manifest_frozen",
    "ceilings_frozen",
    "expectations_frozen",
    "answer_key_not_imported_by_request_path",
    "leakage_gate_passes",
    "grpc_dns_resolver_is_native",
    "historical_artifacts_unchanged",
    "predecessor_commits_unchanged",
    "no_raw_artifacts_exist",
)
EXPECTED_VERDICT_IDS = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9")
EXPECTED_HISTORICAL_DIRS = (
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
    "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/",
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/",
    "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/",
    "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/",
)
TREE_HASHES = {
    directory: hashlib.sha256(directory.encode("utf-8")).hexdigest()[:40]
    for directory in EXPECTED_HISTORICAL_DIRS
}
CHANGES_SINCE_ADJUDICATION = (
    "src/foundry/experiments/locus_validation/integrity.py",
    "docs/superpowers/plans/2026-09-15-locus-policy-live-validation.md",
)
# Spec §13: the 21 raw artifact paths, relative to the experiment directory.
RAW_PATHS = (
    "consumption.json",
    "preflight.json",
    "measurements.json",
    "verdicts.json",
    "report.md",
    *(
        f"L-{ledger}/{name}.json"
        for ledger in ("alpha", "beta")
        for name in (
            "requests",
            "drafts",
            "receipts",
            "decisions",
            "ledger",
            "state_T1",
            "state_T2",
            "result",
        )
    ),
)
COSTS = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]


def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sockets(monkeypatch)


@pytest.fixture(autouse=True)
def _no_provider_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    yield
    assert "XAI_API_KEY" not in os.environ


@pytest.fixture(scope="module")
def leakage_ok() -> LeakageResult:
    result = run_leakage_gate()
    assert result.passed
    return result


@pytest.fixture(scope="module")
def completed() -> Iterator[RunResult]:
    """One scripted, fully completed two-ledger walk through the real governor path,
    with one receipt and one draft payload per answered call."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        result, _budget = _run(EconomicsFake(_script(), COSTS))
        assert result.status is RunStatus.COMPLETED
        yield result


@pytest.fixture(scope="module")
def cases_ok(completed: RunResult) -> tuple[CaseResult, ...]:
    results = evaluate_run(completed)
    assert all(result.structural_passed is True for result in results)
    return results


@pytest.fixture(scope="module")
def gates_ok(
    leakage_ok: LeakageResult, tmp_path_factory: pytest.TempPathFactory
) -> tuple[GateResult, ...]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        gates = _preflight(leakage_ok, out_dir=tmp_path_factory.mktemp("empty-out"))
    assert all_passed(gates), [(g.name, g.detail) for g in gates if not g.passed]
    return gates


# --- fakes ------------------------------------------------------------------------


class FakeGit:
    """Read-only Git facts as a table; records every call it answers."""

    def __init__(
        self,
        *,
        head: str = SEAL_SHA,
        dirty: str = "",
        parents: dict[str, tuple[str, ...]] | None = None,
        ancestors: frozenset[tuple[str, str]] = frozenset(
            {
                (BASELINE_SHA, SEAL_SHA),
                (DESIGN_BASE_SHA, SEAL_SHA),
                (PREDECESSOR_RAW_RUN_SHA, SEAL_SHA),
                (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA),
            }
        ),
        changed: dict[tuple[str, str], tuple[str, ...]] | None = None,
        trees: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._head = head
        self._dirty = dirty
        self._parents = parents if parents is not None else {SEAL_SHA: (HARNESS_SHA,)}
        self._ancestors = ancestors
        self._changed = (
            changed
            if changed is not None
            else {
                (HARNESS_SHA, SEAL_SHA): PREREG_FILES,
                (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA): CHANGES_SINCE_ADJUDICATION,
            }
        )
        self._trees = trees if trees is not None else _default_trees()
        self.calls: list[tuple[str, ...]] = []

    def head(self) -> str:
        self.calls.append(("head",))
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

    def tree_sha(self, sha: str, path: str) -> str:
        self.calls.append(("tree_sha", sha, path))
        return self._trees[(sha, path)]


def _default_trees() -> dict[tuple[str, str], str]:
    trees: dict[tuple[str, str], str] = {}
    for directory, tree in TREE_HASHES.items():
        trees[(DESIGN_BASE_SHA, directory)] = tree
        trees[(SEAL_SHA, directory)] = tree
    return trees


class RaisingGit(FakeGit):
    def head(self) -> str:
        raise RuntimeError("GIT_UNAVAILABLE")


# --- builders ---------------------------------------------------------------------


def _manifest(leakage: LeakageResult) -> dict[str, Any]:
    manifest = {
        MANIFEST_KEY_HARNESS_CODE_SHA: HARNESS_SHA,
        MANIFEST_KEY_POLICY_VERSION: LOCUS_POLICY_VERSION,
        MANIFEST_KEY_PROMPT_SHA256: LOCUS_SYSTEM_INSTRUCTION_SHA256,
        MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S: dict(HISTORICAL_PROMPT_SHA256S),
        MANIFEST_KEY_OUTPUT_SCHEMA_SHA256: SEMANTIC_OUTPUT_SCHEMA_SHA256,
        MANIFEST_KEY_PROVIDER: PROVIDER,
        MANIFEST_KEY_MODEL: MODEL,
        MANIFEST_KEY_REASONING_EFFORT: REASONING_EFFORT,
        MANIFEST_KEY_GRPC_DNS_RESOLVER: "native",
        MANIFEST_KEY_CALLS_PER_DELTA: 2,
        MANIFEST_KEY_EVIDENCE: [record.model_dump(mode="json") for record in evidence_records()],
        MANIFEST_KEY_CORPUS_SHA256: corpus_sha256(),
        MANIFEST_KEY_CEILINGS: dict(LOCKED_CEILINGS),
        MANIFEST_KEY_EXPECTATIONS_SHA256: canonical_sha256(expectations_document()),
        MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256: leakage.needle_set_sha256,
        MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES: dict(TREE_HASHES),
        MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA: DESIGN_BASE_SHA,
        MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA: PREDECESSOR_RAW_RUN_SHA,
        MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA: PREDECESSOR_ADJUDICATION_SHA,
        MANIFEST_KEY_RAW_ARTIFACT_PATHS: list(RAW_PATHS),
    }
    loaded = json.loads(json.dumps(manifest))
    assert isinstance(loaded, dict)
    return loaded


def _manifest_with(leakage: LeakageResult, key: str, value: Any) -> dict[str, Any]:
    manifest = _manifest(leakage)
    manifest[key] = value
    return manifest


def _manifest_without(leakage: LeakageResult, key: str) -> dict[str, Any]:
    manifest = _manifest(leakage)
    del manifest[key]
    return manifest


def _expectations_bytes() -> bytes:
    return json.dumps(expectations_document(), indent=2).encode("utf-8")


def _real_source(name: str) -> str:
    return (PACKAGE_DIR / name).read_text(encoding="utf-8")


def _sources(**overrides: str | None) -> dict[str, str]:
    sources = {name: _real_source(name) for name in REQUEST_PATH_MODULES}
    for key, value in overrides.items():
        module = key.replace("_py", ".py")
        if value is None:
            sources.pop(module)
        else:
            sources[module] = value
    return sources


def _preflight(
    leakage: LeakageResult,
    *,
    out_dir: Path,
    git: FakeGit | None = None,
    frozen_sha: str = SEAL_SHA,
    manifest: dict[str, Any] | None = None,
    expectations_bytes: bytes | None = None,
    sources: dict[str, str] | None = None,
    leakage_override: LeakageResult | None = None,
    observed_grpc_dns_resolver: str | None = "native",
) -> tuple[GateResult, ...]:
    results = preflight(
        git=git or FakeGit(),
        frozen_sha=frozen_sha,
        manifest=manifest if manifest is not None else _manifest(leakage),
        expectations_bytes=(
            expectations_bytes if expectations_bytes is not None else _expectations_bytes()
        ),
        request_path_sources=sources if sources is not None else _sources(),
        leakage=leakage_override or leakage,
        observed_grpc_dns_resolver=observed_grpc_dns_resolver,
        out_dir=out_dir,
    )
    assert tuple(r.name for r in results) == EXPECTED_GATE_NAMES
    return results


def _gates(leakage: LeakageResult, out_dir: Path, **kwargs: Any) -> dict[str, GateResult]:
    return {r.name: r for r in _preflight(leakage, out_dir=out_dir, **kwargs)}


def _verdicts(
    run: RunResult,
    gates: tuple[GateResult, ...],
    cases: tuple[CaseResult, ...],
) -> dict[str, IntegrityVerdict]:
    verdicts = integrity_verdicts(run, preflight_gates=gates, case_results=cases)
    assert tuple(v.id for v in verdicts) == EXPECTED_VERDICT_IDS
    return {v.id: v for v in verdicts}


def _ledger(run: RunResult, ledger: Ledger) -> LedgerRecord:
    record = run.ledgers[LEDGERS.index(ledger)]
    assert record.ledger == ledger
    return record


def _with_ledger(run: RunResult, record: LedgerRecord) -> RunResult:
    alpha, beta = run.ledgers
    if record.ledger == "alpha":
        return run.model_copy(update={"ledgers": (record, beta)})
    return run.model_copy(update={"ledgers": (alpha, record)})


def _with_delta(run: RunResult, ledger: Ledger, t: int, delta: DeltaRecord) -> RunResult:
    record = _ledger(run, ledger)
    deltas = tuple(delta if d.t == t else d for d in record.deltas)
    return _with_ledger(run, record.model_copy(update={"deltas": deltas}))


def _delta(run: RunResult, ledger: Ledger, t: int) -> DeltaRecord:
    for delta in _ledger(run, ledger).deltas:
        if delta.t == t:
            return delta
    raise AssertionError(f"{ledger} has no delta T{t}")


def _with_budget(run: RunResult, **fields: Any) -> RunResult:
    return run.model_copy(update={"budget": run.budget.model_copy(update=fields)})


def _judgment_of(event: StoredEvent) -> SemanticJudgment | None:
    payload = event.event.payload
    if event.event.event_type is EventType.SEMANTIC_JUDGMENT_RECORDED and isinstance(
        payload, SemanticJudgmentPayload
    ):
        return payload.judgment
    return None


def _admission_of(event: StoredEvent) -> SemanticAdmissionPayload | None:
    payload = event.event.payload
    if event.event.event_type is EventType.SEMANTIC_ADMISSION_DECIDED and isinstance(
        payload, SemanticAdmissionPayload
    ):
        return payload
    return None


LedgerMap = Callable[[tuple[StoredEvent, ...]], tuple[StoredEvent, ...]]


def _rewrite_admission(judgment_id: str, route: AdmissionRoute) -> LedgerMap:
    def apply(ledger: tuple[StoredEvent, ...]) -> tuple[StoredEvent, ...]:
        out: list[StoredEvent] = []
        for stored in ledger:
            admission = _admission_of(stored)
            if admission is not None and admission.judgment_id == judgment_id:
                envelope = stored.event.model_copy(
                    update={"payload": admission.model_copy(update={"route": route})}
                )
                stored = stored.model_copy(update={"event": envelope})
            out.append(stored)
        return tuple(out)

    return apply


def _rewrite_judgment(
    judgment_id: str, mutate: Callable[[SemanticJudgment], SemanticJudgment]
) -> LedgerMap:
    def apply(ledger: tuple[StoredEvent, ...]) -> tuple[StoredEvent, ...]:
        out: list[StoredEvent] = []
        for stored in ledger:
            judgment = _judgment_of(stored)
            if judgment is not None and judgment.judgment_id == judgment_id:
                envelope = stored.event.model_copy(
                    update={"payload": SemanticJudgmentPayload(judgment=mutate(judgment))}
                )
                stored = stored.model_copy(update={"event": envelope})
            out.append(stored)
        return tuple(out)

    return apply


def _drop_judgment_event(judgment_id: str) -> LedgerMap:
    def apply(ledger: tuple[StoredEvent, ...]) -> tuple[StoredEvent, ...]:
        kept = [
            stored
            for stored in ledger
            if (j := _judgment_of(stored)) is None or j.judgment_id != judgment_id
        ]
        assert len(kept) == len(ledger) - 1
        return tuple(
            stored.model_copy(update={"sequence": index}) for index, stored in enumerate(kept, 1)
        )

    return apply


def _mutate_events(run: RunResult, ledger: Ledger, mapping: LedgerMap) -> RunResult:
    record = _ledger(run, ledger)
    rewritten = mapping(record.ledger_events)
    assert rewritten != record.ledger_events
    return _with_ledger(run, record.model_copy(update={"ledger_events": rewritten}))


def _supersede_id(run: RunResult, ledger: Ledger) -> str:
    ids = [
        j.judgment_id
        for e in _ledger(run, ledger).ledger_events
        if (j := _judgment_of(e)) is not None and j.kind is JudgmentKind.SUPERSEDE
    ]
    assert len(ids) == 1
    return ids[0]


def _case(ledger: Ledger, case_id: str, passed: bool | None, tags: tuple[str, ...]) -> CaseResult:
    return CaseResult(
        ledger=ledger,
        case_id=case_id,
        structural_passed=passed,
        tags=tags,
        detail="synthetic",
        evidence={},
    )


def _aborted_at_call_three() -> RunResult:
    result, _ = _run(LocusFake(_script((2, XAIProviderError("PROVIDER_FAILURE")))))
    assert result.status is RunStatus.ABORTED_PROVIDER
    assert _ledger(result, "alpha").status == "FAILED"
    assert _ledger(result, "beta").status == "NOT_RUN"
    return result


# --- shape ------------------------------------------------------------------------


def test_gate_names_are_the_eighteen_spec_gates_in_order_with_no_test_suite_gate() -> None:
    assert GATE_NAMES == EXPECTED_GATE_NAMES
    assert len(GATE_NAMES) == 18
    assert len(set(GATE_NAMES)) == 18
    for name in GATE_NAMES:
        assert "regression" not in name
        assert "test" not in name
        assert "pytest" not in name


def test_frozen_constants_are_the_brief_literals() -> None:
    assert VERDICT_IDS == EXPECTED_VERDICT_IDS
    assert PREREGISTRATION_FILES == PREREG_FILES
    assert EXPERIMENT_ARTIFACT_DIR == EXPERIMENT_DIR
    assert HISTORICAL_ARTIFACT_DIRS == EXPECTED_HISTORICAL_DIRS
    assert PREDECESSOR_ARTIFACT_DIR in HISTORICAL_ARTIFACT_DIRS
    assert CEILING_KEYS == (
        "max_frontier_calls",
        "max_judge_calls",
        "max_semantic_retries",
        "max_same_cell_reruns",
        "max_human_authorizations",
        "max_provider_cost_usd",
    )
    assert LOCKED_CEILINGS == {
        "max_frontier_calls": 8,
        "max_judge_calls": 0,
        "max_semantic_retries": 0,
        "max_same_cell_reruns": 0,
        "max_human_authorizations": 0,
        "max_provider_cost_usd": 2.0,
    }
    assert RAW_ARTIFACT_PATH_COUNT == 21 == len(RAW_PATHS)
    assert REQUIRED_MANIFEST_KEYS == (
        "harness_code_sha",
        "policy_version",
        "prompt_sha256",
        "historical_prompt_sha256s",
        "output_schema_sha256",
        "provider",
        "model",
        "reasoning_effort",
        "grpc_dns_resolver",
        "calls_per_delta",
        "evidence",
        "corpus_sha256",
        "ceilings",
        "expectations_sha256",
        "leakage_needle_set_sha256",
        "historical_artifact_tree_hashes",
        "historical_preservation_base_sha",
        "predecessor_raw_run_sha",
        "predecessor_adjudication_sha",
        "raw_artifact_paths",
    )
    assert len(set(REQUIRED_MANIFEST_KEYS)) == len(REQUIRED_MANIFEST_KEYS)
    for directory in HISTORICAL_ARTIFACT_DIRS:
        assert Path(directory).is_dir(), directory


def test_all_gates_pass_on_correct_input(leakage_ok: LeakageResult, tmp_path: Path) -> None:
    git = FakeGit()
    results = _gates(leakage_ok, tmp_path, git=git)
    failing = [(name, r.detail) for name, r in results.items() if not r.passed]
    assert failing == []
    assert all_passed(results.values())
    assert ("head",) in git.calls
    assert ("dirty",) in git.calls
    assert ("is_ancestor", BASELINE_SHA, SEAL_SHA) in git.calls
    assert ("is_ancestor", DESIGN_BASE_SHA, SEAL_SHA) in git.calls
    assert ("is_ancestor", PREDECESSOR_RAW_RUN_SHA, SEAL_SHA) in git.calls
    assert ("is_ancestor", PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA) in git.calls
    assert ("changed_paths", PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA) in git.calls
    for directory in EXPECTED_HISTORICAL_DIRS:
        assert ("tree_sha", DESIGN_BASE_SHA, directory) in git.calls
        assert ("tree_sha", SEAL_SHA, directory) in git.calls
    assert not any(call[0] == "show_bytes" for call in git.calls)


def test_preflight_never_writes(leakage_ok: LeakageResult, tmp_path: Path) -> None:
    out_dir = tmp_path / "experiment"
    out_dir.mkdir()
    results = _gates(leakage_ok, out_dir)
    assert all_passed(results.values())
    assert list(out_dir.iterdir()) == []
    assert list(tmp_path.iterdir()) == [out_dir]


def test_a_gate_that_raises_fails_closed_without_stopping_the_others(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    results = _gates(leakage_ok, tmp_path, git=RaisingGit())
    assert results["head_equals_final_seal"].passed is False
    assert "RuntimeError" in results["head_equals_final_seal"].detail
    assert "GIT_UNAVAILABLE" in results["head_equals_final_seal"].detail
    assert results["worktree_clean"].passed is True
    assert results["no_raw_artifacts_exist"].passed is True
    assert len(results) == 18


# --- gates 1-3: git ---------------------------------------------------------------


def test_gate_1_fails_when_head_is_not_the_seal(leakage_ok: LeakageResult, tmp_path: Path) -> None:
    results = _gates(leakage_ok, tmp_path, git=FakeGit(head=OTHER_SHA))
    assert results["head_equals_final_seal"].passed is False
    assert SEAL_SHA in results["head_equals_final_seal"].detail


def test_gate_1_fails_when_seal_parent_is_not_the_harness_commit_or_is_a_merge(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    results = _gates(leakage_ok, tmp_path, git=FakeGit(parents={SEAL_SHA: (OTHER_SHA,)}))
    assert results["head_equals_final_seal"].passed is False
    assert HARNESS_SHA in results["head_equals_final_seal"].detail
    results = _gates(
        leakage_ok, tmp_path, git=FakeGit(parents={SEAL_SHA: (HARNESS_SHA, OTHER_SHA)})
    )
    assert results["head_equals_final_seal"].passed is False


def test_gate_1_fails_when_seal_changes_anything_but_the_two_prereg_files(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    extra = {
        (HARNESS_SHA, SEAL_SHA): (*PREREG_FILES, EXPERIMENT_DIR + "consumption.json"),
        (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA): CHANGES_SINCE_ADJUDICATION,
    }
    results = _gates(leakage_ok, tmp_path, git=FakeGit(changed=extra))
    assert results["head_equals_final_seal"].passed is False
    fewer = {
        (HARNESS_SHA, SEAL_SHA): PREREG_FILES[:1],
        (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA): CHANGES_SINCE_ADJUDICATION,
    }
    results = _gates(leakage_ok, tmp_path, git=FakeGit(changed=fewer))
    assert results["head_equals_final_seal"].passed is False


def test_gate_2_fails_on_a_dirty_worktree(leakage_ok: LeakageResult, tmp_path: Path) -> None:
    results = _gates(leakage_ok, tmp_path, git=FakeGit(dirty=" M src/x.py\n?? y.txt\n"))
    assert results["worktree_clean"].passed is False
    assert "?? y.txt" in results["worktree_clean"].detail


def test_gate_3_fails_when_baseline_is_not_an_ancestor(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    ancestors = frozenset(
        {
            (DESIGN_BASE_SHA, SEAL_SHA),
            (PREDECESSOR_RAW_RUN_SHA, SEAL_SHA),
            (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA),
        }
    )
    results = _gates(leakage_ok, tmp_path, git=FakeGit(ancestors=ancestors))
    assert results["seal_descends_from_baseline"].passed is False
    assert BASELINE_SHA in results["seal_descends_from_baseline"].detail
    assert results["historical_artifacts_unchanged"].passed is True
    assert results["predecessor_commits_unchanged"].passed is True


# --- gates 4-9: identity ----------------------------------------------------------


def test_gate_4_fails_on_a_policy_version_drift(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = _gates(
        leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, MANIFEST_KEY_POLICY_VERSION, "x")
    )
    assert results["locus_policy_frozen"].passed is False
    monkeypatch.setattr(integrity_module, "LOCUS_POLICY_VERSION", "intent-v2-locus-v2")
    results = _gates(leakage_ok, tmp_path)
    assert results["locus_policy_frozen"].passed is False
    assert "intent-v2-locus-v2" in results["locus_policy_frozen"].detail


def test_gate_4_reads_the_adapter_class_attribute_without_constructing_it(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Drifted:
        policy_version = "intent-v2-locus-v0"
        include_comparison_context = True

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("the adapter must never be constructed by a gate")

    monkeypatch.setattr(integrity_module, "XAILocusSemanticReasoner", Drifted)
    results = _gates(leakage_ok, tmp_path)
    assert results["locus_policy_frozen"].passed is False
    assert "intent-v2-locus-v0" in results["locus_policy_frozen"].detail


def test_gate_5_fails_on_a_prompt_hash_drift(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_PROMPT_SHA256, "0" * 64),
    )
    assert results["locus_prompt_hash_frozen"].passed is False
    monkeypatch.setattr(
        integrity_module,
        "LOCUS_SYSTEM_INSTRUCTION",
        integrity_module.LOCUS_SYSTEM_INSTRUCTION + " ",
    )
    results = _gates(leakage_ok, tmp_path)
    assert results["locus_prompt_hash_frozen"].passed is False


def test_gate_6_fails_on_an_output_schema_hash_drift(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_OUTPUT_SCHEMA_SHA256, "0" * 64),
    )
    assert results["output_schema_hash_frozen"].passed is False
    monkeypatch.setattr(integrity_module, "semantic_output_schema_sha256", lambda: "1" * 64)
    results = _gates(leakage_ok, tmp_path)
    assert results["output_schema_hash_frozen"].passed is False


def test_gate_7_fails_when_a_historical_prompt_changed(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        integrity_module, "SYSTEM_INSTRUCTION", integrity_module.SYSTEM_INSTRUCTION + "\n"
    )
    results = _gates(leakage_ok, tmp_path)
    assert results["historical_prompts_unchanged"].passed is False
    assert results["locus_prompt_hash_frozen"].passed is True


def test_gate_7_fails_when_the_contrastive_prompt_changed(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        integrity_module,
        "CONTRASTIVE_SYSTEM_INSTRUCTION",
        integrity_module.CONTRASTIVE_SYSTEM_INSTRUCTION + "\n",
    )
    results = _gates(leakage_ok, tmp_path)
    assert results["historical_prompts_unchanged"].passed is False


def test_gate_7_fails_when_the_manifest_historical_hashes_differ(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    sealed = dict(HISTORICAL_PROMPT_SHA256S)
    sealed["intent-v2-9p-v4"] = "0" * 64
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_HISTORICAL_PROMPT_SHA256S, sealed),
    )
    assert results["historical_prompts_unchanged"].passed is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (MANIFEST_KEY_PROVIDER, "openai"),
        (MANIFEST_KEY_MODEL, "grok-3"),
        (MANIFEST_KEY_REASONING_EFFORT, "low"),
        (MANIFEST_KEY_GRPC_DNS_RESOLVER, "ares"),
    ],
)
def test_gate_8_fails_on_a_model_configuration_drift(
    leakage_ok: LeakageResult, tmp_path: Path, key: str, value: str
) -> None:
    results = _gates(leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, key, value))
    assert results["model_configuration_frozen"].passed is False
    assert key in results["model_configuration_frozen"].detail


def test_gate_8_fails_when_the_contrastive_path_is_off(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NotContrastive:
        policy_version = LOCUS_POLICY_VERSION
        include_comparison_context = False

    monkeypatch.setattr(integrity_module, "XAILocusSemanticReasoner", NotContrastive)
    results = _gates(leakage_ok, tmp_path)
    assert results["model_configuration_frozen"].passed is False
    assert "include_comparison_context" in results["model_configuration_frozen"].detail
    assert results["locus_policy_frozen"].passed is True


def test_gate_9_fails_when_calls_per_delta_is_not_two(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = _gates(
        leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, MANIFEST_KEY_CALLS_PER_DELTA, 3)
    )
    assert results["calls_per_delta_is_2"].passed is False
    monkeypatch.setattr(integrity_module, "CALLS_PER_DELTA", 3)
    results = _gates(leakage_ok, tmp_path)
    assert results["calls_per_delta_is_2"].passed is False


# --- gates 10-12: sealed documents ------------------------------------------------


def test_gate_10_fails_when_the_evidence_manifest_differs(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    evidence = [record.model_dump(mode="json") for record in evidence_records()]
    assert len(evidence) == 16
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_EVIDENCE, evidence[:-1]),
    )
    assert results["evidence_manifest_frozen"].passed is False
    tampered = [dict(record) for record in evidence]
    tampered[3]["content_sha256"] = "0" * 64
    results = _gates(
        leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, MANIFEST_KEY_EVIDENCE, tampered)
    )
    assert results["evidence_manifest_frozen"].passed is False
    assert "index 3" in results["evidence_manifest_frozen"].detail


def test_gate_10_fails_when_the_corpus_hash_differs(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_CORPUS_SHA256, "0" * 64),
    )
    assert results["evidence_manifest_frozen"].passed is False
    assert corpus_sha256() in results["evidence_manifest_frozen"].detail


def test_gate_11_fails_on_a_ceiling_drift(
    leakage_ok: LeakageResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ceilings = dict(LOCKED_CEILINGS)
    ceilings["max_provider_cost_usd"] = 2.5
    results = _gates(
        leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, MANIFEST_KEY_CEILINGS, ceilings)
    )
    assert results["ceilings_frozen"].passed is False
    missing = dict(LOCKED_CEILINGS)
    del missing["max_judge_calls"]
    results = _gates(
        leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, MANIFEST_KEY_CEILINGS, missing)
    )
    assert results["ceilings_frozen"].passed is False
    extra = dict(LOCKED_CEILINGS)
    extra["max_extra"] = 1
    results = _gates(
        leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, MANIFEST_KEY_CEILINGS, extra)
    )
    assert results["ceilings_frozen"].passed is False
    monkeypatch.setattr(integrity_module, "MAX_FRONTIER_CALLS", 9)
    results = _gates(leakage_ok, tmp_path)
    assert results["ceilings_frozen"].passed is False


def test_gate_12_fails_on_tampered_or_unparsable_expectations(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    document = expectations_document()
    document["case_ids"] = list(document["case_ids"])[:-1]
    tampered = json.dumps(document).encode("utf-8")
    results = _gates(leakage_ok, tmp_path, expectations_bytes=tampered)
    assert results["expectations_frozen"].passed is False
    results = _gates(leakage_ok, tmp_path, expectations_bytes=b"{not json")
    assert results["expectations_frozen"].passed is False
    assert "JSONDecodeError" in results["expectations_frozen"].detail
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_EXPECTATIONS_SHA256, "0" * 64),
    )
    assert results["expectations_frozen"].passed is False


def test_gate_12_accepts_reformatted_but_equal_expectations(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    compact = json.dumps(expectations_document(), separators=(",", ":")).encode("utf-8")
    results = _gates(leakage_ok, tmp_path, expectations_bytes=compact)
    assert results["expectations_frozen"].passed is True


# --- gates 13-15: leakage, imports, resolver --------------------------------------


def test_gate_13_fails_on_a_missing_request_path_source(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    results = _gates(leakage_ok, tmp_path, sources=_sources(runner_py=None))
    assert results["answer_key_not_imported_by_request_path"].passed is False
    assert "runner.py" in results["answer_key_not_imported_by_request_path"].detail


def test_gate_13_fails_on_an_answer_key_import(leakage_ok: LeakageResult, tmp_path: Path) -> None:
    leaking = (
        _real_source("runner.py")
        + "\nfrom foundry.experiments.locus_validation.expectations import CASE_IDS\n"
    )
    results = _gates(leakage_ok, tmp_path, sources=_sources(runner_py=leaking))
    assert results["answer_key_not_imported_by_request_path"].passed is False
    assert "expectations" in results["answer_key_not_imported_by_request_path"].detail


def test_gate_14_fails_when_the_leakage_gate_failed(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    failed = leakage_ok.model_copy(
        update={
            "passed": False,
            "matched_needle": "opaque",
            "matched_needle_kind": "PROSE",
            "matched_skeleton_id": "ALPHA_SEED_CALL1",
        }
    )
    results = _gates(leakage_ok, tmp_path, leakage_override=failed)
    assert results["leakage_gate_passes"].passed is False
    assert "ALPHA_SEED_CALL1" in results["leakage_gate_passes"].detail


def test_gate_14_fails_when_the_needle_set_or_prompt_differs(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256, "0" * 64),
    )
    assert results["leakage_gate_passes"].passed is False
    other_prompt = leakage_ok.model_copy(update={"prompt_sha256": "1" * 64})
    results = _gates(leakage_ok, tmp_path, leakage_override=other_prompt)
    assert results["leakage_gate_passes"].passed is False
    assert "prompt" in results["leakage_gate_passes"].detail


@pytest.mark.parametrize("observed", [None, "", "ares", "Native", " native", "native\n"])
def test_gate_15_requires_exactly_native(
    leakage_ok: LeakageResult, tmp_path: Path, observed: str | None
) -> None:
    results = _gates(leakage_ok, tmp_path, observed_grpc_dns_resolver=observed)
    assert results["grpc_dns_resolver_is_native"].passed is False
    assert repr(observed) in results["grpc_dns_resolver_is_native"].detail


# --- gates 16-18: preservation, predecessor, raw absence --------------------------


def test_gate_16_fails_when_one_historical_tree_differs(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    trees = _default_trees()
    trees[(SEAL_SHA, EXPECTED_HISTORICAL_DIRS[-1])] = "d" * 40
    results = _gates(leakage_ok, tmp_path, git=FakeGit(trees=trees))
    assert results["historical_artifacts_unchanged"].passed is False
    assert EXPECTED_HISTORICAL_DIRS[-1] in results["historical_artifacts_unchanged"].detail


def test_gate_16_fails_when_the_manifest_hash_or_base_differs(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    hashes = dict(TREE_HASHES)
    hashes[EXPECTED_HISTORICAL_DIRS[0]] = "d" * 40
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES, hashes),
    )
    assert results["historical_artifacts_unchanged"].passed is False
    missing = dict(TREE_HASHES)
    del missing[EXPECTED_HISTORICAL_DIRS[2]]
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES, missing),
    )
    assert results["historical_artifacts_unchanged"].passed is False
    assert EXPECTED_HISTORICAL_DIRS[2] in results["historical_artifacts_unchanged"].detail
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(
            leakage_ok, MANIFEST_KEY_HISTORICAL_PRESERVATION_BASE_SHA, OTHER_SHA
        ),
    )
    assert results["historical_artifacts_unchanged"].passed is False


def test_gate_16_fails_when_the_design_base_is_not_an_ancestor(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    ancestors = frozenset(
        {
            (BASELINE_SHA, SEAL_SHA),
            (PREDECESSOR_RAW_RUN_SHA, SEAL_SHA),
            (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA),
        }
    )
    results = _gates(leakage_ok, tmp_path, git=FakeGit(ancestors=ancestors))
    assert results["historical_artifacts_unchanged"].passed is False
    assert DESIGN_BASE_SHA in results["historical_artifacts_unchanged"].detail


def test_gate_17_fails_when_the_9p3_directory_changed_since_adjudication(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    changed = {
        (HARNESS_SHA, SEAL_SHA): PREREG_FILES,
        (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA): (
            *CHANGES_SINCE_ADJUDICATION,
            PREDECESSOR_ARTIFACT_DIR + "verdicts.json",
        ),
    }
    results = _gates(leakage_ok, tmp_path, git=FakeGit(changed=changed))
    assert results["predecessor_commits_unchanged"].passed is False
    assert "verdicts.json" in results["predecessor_commits_unchanged"].detail


@pytest.mark.parametrize("missing", [PREDECESSOR_RAW_RUN_SHA, PREDECESSOR_ADJUDICATION_SHA])
def test_gate_17_fails_when_a_predecessor_commit_is_not_an_ancestor(
    leakage_ok: LeakageResult, tmp_path: Path, missing: str
) -> None:
    ancestors = frozenset(
        {
            (BASELINE_SHA, SEAL_SHA),
            (DESIGN_BASE_SHA, SEAL_SHA),
            (PREDECESSOR_RAW_RUN_SHA, SEAL_SHA),
            (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA),
        }
        - {(missing, SEAL_SHA)}
    )
    results = _gates(leakage_ok, tmp_path, git=FakeGit(ancestors=ancestors))
    assert results["predecessor_commits_unchanged"].passed is False
    assert missing in results["predecessor_commits_unchanged"].detail


@pytest.mark.parametrize(
    "key", [MANIFEST_KEY_PREDECESSOR_RAW_RUN_SHA, MANIFEST_KEY_PREDECESSOR_ADJUDICATION_SHA]
)
def test_gate_17_fails_when_the_manifest_names_another_predecessor(
    leakage_ok: LeakageResult, tmp_path: Path, key: str
) -> None:
    results = _gates(leakage_ok, tmp_path, manifest=_manifest_with(leakage_ok, key, OTHER_SHA))
    assert results["predecessor_commits_unchanged"].passed is False
    assert key in results["predecessor_commits_unchanged"].detail


@pytest.mark.parametrize("stray", ["consumption.json", "L-beta/ledger.json"])
def test_gate_18_fails_when_a_raw_artifact_exists(
    leakage_ok: LeakageResult, tmp_path: Path, stray: str
) -> None:
    target = tmp_path / stray
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    results = _gates(leakage_ok, tmp_path)
    assert results["no_raw_artifacts_exist"].passed is False
    assert stray in results["no_raw_artifacts_exist"].detail


def test_gate_18_ignores_the_seal_files_and_unrelated_files(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "expectations.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    results = _gates(leakage_ok, tmp_path)
    assert results["no_raw_artifacts_exist"].passed is True


def test_gate_18_fails_when_the_frozen_path_list_is_missing_or_malformed(
    leakage_ok: LeakageResult, tmp_path: Path
) -> None:
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_without(leakage_ok, MANIFEST_KEY_RAW_ARTIFACT_PATHS),
    )
    assert results["no_raw_artifacts_exist"].passed is False
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_RAW_ARTIFACT_PATHS, "consumption.json"),
    )
    assert results["no_raw_artifacts_exist"].passed is False
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(leakage_ok, MANIFEST_KEY_RAW_ARTIFACT_PATHS, list(RAW_PATHS[:-1])),
    )
    assert results["no_raw_artifacts_exist"].passed is False
    assert "21" in results["no_raw_artifacts_exist"].detail
    results = _gates(
        leakage_ok,
        tmp_path,
        manifest=_manifest_with(
            leakage_ok, MANIFEST_KEY_RAW_ARTIFACT_PATHS, [*RAW_PATHS[:-1], "/etc/hosts"]
        ),
    )
    assert results["no_raw_artifacts_exist"].passed is False


@pytest.mark.parametrize("key", REQUIRED_MANIFEST_KEYS)
def test_a_missing_manifest_key_fails_at_least_one_gate_closed(
    leakage_ok: LeakageResult, tmp_path: Path, key: str
) -> None:
    results = _gates(leakage_ok, tmp_path, manifest=_manifest_without(leakage_ok, key))
    failing = [r for r in results.values() if not r.passed]
    assert failing, key
    assert any(key in r.detail for r in failing), key


# --- hygiene: no subprocess, no environment, no adapter construction -------------


def _integrity_tree() -> ast.Module:
    return ast.parse(INTEGRITY_SOURCE.read_text(encoding="utf-8"))


def test_integrity_module_never_shells_out_reads_the_environment_or_builds_the_adapter() -> None:
    tree = _integrity_tree()
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert "subprocess" not in imported
    assert "os" not in imported
    assert not any(m.startswith("os.") for m in imported)
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "environ" not in attributes
    assert "getenv" not in attributes
    calls = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "XAILocusSemanticReasoner" not in calls
    assert "XAIContrastiveSemanticReasoner" not in calls
    assert "XAISemanticReasoner" not in calls
    assert "open" not in calls
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "run_leakage_gate" not in names
    assert "request_only_reference_check" in names
    assert "CallJudgments" in names
    assert "replay_matches" in names
    assert "request_path_import_gate" in names
    assert "GitCliLike" in names
    assert "GateResult" in names
    assert "PreflightGateMissing" not in names
    package = "foundry.experiments.locus_validation."
    assert package + "artifacts" not in imported


def test_integrity_module_law_and_exports() -> None:
    public: Any = integrity_module.__all__
    for name in (
        "GATE_NAMES",
        "VERDICT_IDS",
        "LOCKED_CEILINGS",
        "PREREGISTRATION_FILES",
        "RAW_ARTIFACT_PATH_COUNT",
        "REQUIRED_MANIFEST_KEYS",
        "IntegrityVerdict",
        "integrity_verdicts",
        "preflight",
    ):
        assert name in public
    for key in REQUIRED_MANIFEST_KEYS:
        assert f"MANIFEST_KEY_{key.upper()}" in public, key
        assert getattr(integrity_module, f"MANIFEST_KEY_{key.upper()}") == key
    assert integrity_module.__doc__ is not None
    assert "never" in integrity_module.__doc__


# --- post-run verdicts: the completed run -----------------------------------------


def test_every_verdict_passes_on_the_completed_run(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    verdicts = _verdicts(completed, gates_ok, cases_ok)
    failing = [(v.id, v.detail) for v in verdicts.values() if v.passed is not True]
    assert failing == []
    for verdict in verdicts.values():
        assert verdict.applies_to == ("alpha", "beta")
        assert verdict.failed_ledgers == ()
        assert verdict.detail
    assert "8" in verdicts["L2"].detail
    assert "0.36" in verdicts["L8"].detail


def test_verdicts_are_deterministic(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    first = integrity_verdicts(completed, preflight_gates=gates_ok, case_results=cases_ok)
    second = integrity_verdicts(completed, preflight_gates=gates_ok, case_results=cases_ok)
    assert first == second


# --- L1: two calls per completed delta --------------------------------------------


def test_l1_fails_on_a_one_call_delta_and_names_the_ledger(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "beta", 2)
    truncated = delta.model_copy(
        update={
            "requests": delta.requests[:1],
            "reference_snapshots": delta.reference_snapshots[:1],
            "receipts": delta.receipts[:1],
            "draft_payloads": delta.draft_payloads[:1],
        }
    )
    verdicts = _verdicts(_with_delta(completed, "beta", 2, truncated), gates_ok, cases_ok)
    assert verdicts["L1"].passed is False
    assert verdicts["L1"].failed_ledgers == ("beta",)
    assert "T2" in verdicts["L1"].detail


def test_l1_fails_when_a_completed_run_carries_a_not_run_ledger(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    beta = _ledger(completed, "beta")
    not_run = beta.model_copy(
        update={
            "status": "NOT_RUN",
            "deltas": (),
            "ledger_events": (),
            "final_state": None,
            "final_view": None,
            "replay": None,
        }
    )
    verdicts = _verdicts(_with_ledger(completed, not_run), gates_ok, cases_ok)
    assert verdicts["L1"].passed is False
    assert verdicts["L1"].failed_ledgers == ("beta",)


def test_l1_skips_a_not_run_ledger_of_an_aborted_run_and_checks_completed_deltas_only(
    gates_ok: tuple[GateResult, ...],
) -> None:
    aborted = _aborted_at_call_three()
    verdicts = _verdicts(aborted, gates_ok, evaluate_run(aborted))
    assert verdicts["L1"].passed is True
    for verdict_id in ("L1", "L3", "L4", "L5"):
        assert "beta" not in verdicts[verdict_id].failed_ledgers, verdict_id


# --- L2: no third call, judge call or retry ---------------------------------------


def test_l2_fails_on_a_third_record_in_a_delta(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "alpha", 1)
    third = delta.requests[1].model_copy(update={"request_sha256": "e" * 64})
    snapshot = delta.reference_snapshots[1].model_copy(update={"request_sha256": "e" * 64})
    extended = delta.model_copy(
        update={
            "requests": (*delta.requests, third),
            "reference_snapshots": (*delta.reference_snapshots, snapshot),
        }
    )
    run = _with_budget(_with_delta(completed, "alpha", 1, extended), frontier_calls=9)
    verdicts = _verdicts(run, gates_ok, cases_ok)
    assert verdicts["L2"].passed is False
    assert verdicts["L2"].failed_ledgers == ("alpha",)
    assert "3" in verdicts["L2"].detail


def test_l2_fails_on_a_retry_shape_and_on_a_judge_call(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "beta", 2)
    first_sha = delta.requests[0].request_sha256
    repeated = delta.requests[1].model_copy(update={"request_sha256": first_sha})
    snapshot = delta.reference_snapshots[1].model_copy(update={"request_sha256": first_sha})
    retried = delta.model_copy(
        update={
            "requests": (delta.requests[0], repeated),
            "reference_snapshots": (delta.reference_snapshots[0], snapshot),
        }
    )
    verdicts = _verdicts(_with_delta(completed, "beta", 2, retried), gates_ok, cases_ok)
    assert verdicts["L2"].passed is False
    assert verdicts["L2"].failed_ledgers == ("beta",)
    verdicts = _verdicts(_with_budget(completed, judge_calls=1), gates_ok, cases_ok)
    assert verdicts["L2"].passed is False
    assert verdicts["L2"].failed_ledgers == ()
    assert "judge" in verdicts["L2"].detail


def test_l2_fails_when_frontier_calls_and_records_disagree(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    verdicts = _verdicts(_with_budget(completed, frontier_calls=7), gates_ok, cases_ok)
    assert verdicts["L2"].passed is False
    assert verdicts["L2"].failed_ledgers == ()
    aborted = _aborted_at_call_three()
    verdicts = _verdicts(aborted, gates_ok, evaluate_run(aborted))
    assert verdicts["L2"].passed is False
    assert "3" in verdicts["L2"].detail and "2" in verdicts["L2"].detail


# --- L3: request-only reference law -----------------------------------------------


def test_l3_fails_closed_on_a_reordered_snapshot(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "alpha", 2)
    first, second = delta.reference_snapshots
    swapped = delta.model_copy(update={"reference_snapshots": (second, first)})
    verdicts = _verdicts(_with_delta(completed, "alpha", 2, swapped), gates_ok, cases_ok)
    assert verdicts["L3"].passed is False
    assert verdicts["L3"].failed_ledgers == ("alpha",)
    assert "ReferenceSnapshotMismatch" in verdicts["L3"].detail
    assert "beta:" in verdicts["L3"].detail


def test_l3_fails_when_a_judgment_cites_outside_its_request(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "beta", 1)
    judgment_id = delta.stage_decisions[1][0].judgment_id

    def cite_elsewhere(judgment: SemanticJudgment) -> SemanticJudgment:
        return judgment.model_copy(update={"visible_evidence_ids": ("EV-UNKNOWN",)})

    run = _mutate_events(completed, "beta", _rewrite_judgment(judgment_id, cite_elsewhere))
    verdicts = _verdicts(run, gates_ok, cases_ok)
    assert verdicts["L3"].passed is False
    assert verdicts["L3"].failed_ledgers == ("beta",)
    assert judgment_id in verdicts["L3"].detail


def test_l3_fails_closed_when_a_decision_names_an_unrecorded_judgment(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    judgment_id = _delta(completed, "alpha", 2).stage_decisions[0][0].judgment_id
    run = _mutate_events(completed, "alpha", _drop_judgment_event(judgment_id))
    verdicts = _verdicts(run, gates_ok, cases_ok)
    assert verdicts["L3"].passed is False
    assert verdicts["L3"].failed_ledgers == ("alpha",)
    assert verdicts["L5"].passed is False
    assert verdicts["L5"].failed_ledgers == ("alpha",)


def test_l3_checks_the_records_of_a_failed_delta_too(gates_ok: tuple[GateResult, ...]) -> None:
    """Call 1 of the failed revision delta was answered and its judgments recorded:
    they are bound to the one recorded request, and a swapped snapshot is a mismatch."""
    result, _ = _run(LocusFake(_script((3, XAIProviderError("PROVIDER_FAILURE")))))
    alpha = _ledger(result, "alpha")
    assert alpha.status == "FAILED"
    revision = alpha.deltas[1]
    assert len(revision.requests) == 1 and revision.stage_decisions == ((), ())
    verdicts = _verdicts(result, gates_ok, evaluate_run(result))
    assert verdicts["L3"].passed is True
    seed_snapshot = alpha.deltas[0].reference_snapshots[0]
    swapped = revision.model_copy(update={"reference_snapshots": (seed_snapshot,)})
    verdicts = _verdicts(_with_delta(result, "alpha", 2, swapped), gates_ok, evaluate_run(result))
    assert verdicts["L3"].passed is False
    assert verdicts["L3"].failed_ledgers == ("alpha",)


# --- L4: replay per completed ledger ----------------------------------------------


def test_l4_recomputes_replay_and_fails_on_a_mismatch(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    beta = _ledger(completed, "beta")
    stale = beta.model_copy(update={"final_state": beta.deltas[0].state_snapshot})
    verdicts = _verdicts(_with_ledger(completed, stale), gates_ok, cases_ok)
    assert verdicts["L4"].passed is False
    assert verdicts["L4"].failed_ledgers == ("beta",)


def test_l4_fails_when_the_recorded_replay_is_absent_or_mismatched(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    alpha = _ledger(completed, "alpha")
    verdicts = _verdicts(
        _with_ledger(completed, alpha.model_copy(update={"replay": None})), gates_ok, cases_ok
    )
    assert verdicts["L4"].passed is False
    assert verdicts["L4"].failed_ledgers == ("alpha",)
    mismatch = ReplayResult(
        status="REPLAY_MISMATCH",
        event_count=len(alpha.ledger_events),
        state_matches=False,
        view_matches=True,
    )
    verdicts = _verdicts(
        _with_ledger(completed, alpha.model_copy(update={"replay": mismatch})), gates_ok, cases_ok
    )
    assert verdicts["L4"].passed is False
    assert verdicts["L4"].failed_ledgers == ("alpha",)


# --- L5: receipts / requests / events reconcile -----------------------------------


def test_l5_fails_on_a_receipt_count_mismatch(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "alpha", 1)
    assert len(delta.receipts) == 2
    fewer = delta.model_copy(update={"receipts": delta.receipts[:1]})
    verdicts = _verdicts(_with_delta(completed, "alpha", 1, fewer), gates_ok, cases_ok)
    assert verdicts["L5"].passed is False
    assert verdicts["L5"].failed_ledgers == ("alpha",)
    assert "receipt" in verdicts["L5"].detail


def test_l5_fails_on_a_snapshot_count_mismatch(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "beta", 2)
    fewer = delta.model_copy(update={"reference_snapshots": delta.reference_snapshots[:1]})
    verdicts = _verdicts(_with_delta(completed, "beta", 2, fewer), gates_ok, cases_ok)
    assert verdicts["L5"].passed is False
    assert verdicts["L5"].failed_ledgers == ("beta",)


def test_l5_fails_when_a_not_run_ledger_carries_material(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    beta = _ledger(completed, "beta")
    carrying = beta.model_copy(update={"status": "NOT_RUN"})
    run = _with_ledger(completed, carrying).model_copy(update={"status": RunStatus.ABORTED_RUNTIME})
    verdicts = _verdicts(run, gates_ok, cases_ok)
    assert verdicts["L5"].passed is False
    assert verdicts["L5"].failed_ledgers == ("beta",)


def test_l5_fails_when_the_ledger_records_a_judgment_no_decision_names(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    delta = _delta(completed, "alpha", 2)
    dropped = delta.model_copy(
        update={"stage_decisions": (delta.stage_decisions[0][1:], delta.stage_decisions[1])}
    )
    verdicts = _verdicts(_with_delta(completed, "alpha", 2, dropped), gates_ok, cases_ok)
    assert verdicts["L5"].passed is False
    assert verdicts["L5"].failed_ledgers == ("alpha",)


def test_l5_passes_without_receipts_when_the_reasoner_exposes_none(
    gates_ok: tuple[GateResult, ...],
) -> None:
    result, _ = _run(LocusFake(_script()))
    assert result.status is RunStatus.COMPLETED
    verdicts = _verdicts(result, gates_ok, evaluate_run(result))
    assert verdicts["L5"].passed is True
    assert verdicts["L8"].passed is True


# --- L6: no applied SUPERSEDE, no human authority ---------------------------------


def test_l6_fails_on_a_hand_built_applied_supersede(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    judgment_id = _supersede_id(completed, "alpha")
    run = _mutate_events(completed, "alpha", _rewrite_admission(judgment_id, AdmissionRoute.APPLY))
    verdicts = _verdicts(run, gates_ok, cases_ok)
    assert verdicts["L6"].passed is False
    assert verdicts["L6"].failed_ledgers == ("alpha",)
    assert judgment_id in verdicts["L6"].detail


def test_l6_fails_on_a_human_authorization(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    verdicts = _verdicts(_with_budget(completed, human_authorizations=1), gates_ok, cases_ok)
    assert verdicts["L6"].passed is False
    assert verdicts["L6"].failed_ledgers == ()
    assert "human" in verdicts["L6"].detail


# --- L7: identity guard never tripped ---------------------------------------------


def test_l7_fails_on_a_recorded_identity_drift(gates_ok: tuple[GateResult, ...]) -> None:
    result, _ = _run(LocusFake(_script((0, IdentityDrift("IDENTITY_DRIFT: scripted")))))
    assert result.status is RunStatus.ABORTED_IDENTITY
    verdicts = _verdicts(result, gates_ok, evaluate_run(result))
    assert verdicts["L7"].passed is False
    assert verdicts["L7"].failed_ledgers == ("alpha",)
    assert "IdentityDrift" in verdicts["L7"].detail


def test_l7_fails_on_an_identity_status_without_a_ledger_error(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    run = completed.model_copy(update={"status": RunStatus.ABORTED_IDENTITY})
    verdicts = _verdicts(run, gates_ok, cases_ok)
    assert verdicts["L7"].passed is False
    assert verdicts["L7"].failed_ledgers == ()


def test_l7_passes_on_a_non_identity_abort(gates_ok: tuple[GateResult, ...]) -> None:
    aborted = _aborted_at_call_three()
    verdicts = _verdicts(aborted, gates_ok, evaluate_run(aborted))
    assert verdicts["L7"].passed is True


# --- L8: cost and call ceilings ---------------------------------------------------


def test_l8_fails_above_the_cost_ceiling_or_the_call_ceiling(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    verdicts = _verdicts(_with_budget(completed, provider_cost_usd="2.01"), gates_ok, cases_ok)
    assert verdicts["L8"].passed is False
    assert verdicts["L8"].failed_ledgers == ()
    assert "2.01" in verdicts["L8"].detail
    verdicts = _verdicts(_with_budget(completed, frontier_calls=9), gates_ok, cases_ok)
    assert verdicts["L8"].passed is False
    assert "9" in verdicts["L8"].detail


def test_l8_passes_exactly_at_the_ceilings(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    verdicts = _verdicts(
        _with_budget(completed, provider_cost_usd="2.00", frontier_calls=8), gates_ok, cases_ok
    )
    assert verdicts["L8"].passed is True
    assert Decimal("2.00") == Decimal("2.0")


# --- L9: the deterministic case assertion sets ------------------------------------


def test_l9_fails_naming_ledger_case_and_tags(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    tags = (FAILURE_TAGS[4], FAILURE_TAGS[9])
    failing = _case("beta", CASE_IDS[5], False, tags)
    cases = tuple(
        failing if (c.ledger, c.case_id) == ("beta", CASE_IDS[5]) else c for c in cases_ok
    )
    verdicts = _verdicts(completed, gates_ok, cases)
    assert verdicts["L9"].passed is False
    assert verdicts["L9"].failed_ledgers == ("beta",)
    assert "beta" in verdicts["L9"].detail
    assert CASE_IDS[5] in verdicts["L9"].detail
    for tag in tags:
        assert tag in verdicts["L9"].detail


def test_l9_attributes_both_ledgers_in_canonical_order(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    replaced = {
        ("beta", CASE_IDS[1]): _case("beta", CASE_IDS[1], False, (FAILURE_TAGS[0],)),
        ("alpha", CASE_IDS[0]): _case("alpha", CASE_IDS[0], False, (FAILURE_TAGS[1],)),
    }
    cases = tuple(replaced.get((c.ledger, c.case_id), c) for c in reversed(cases_ok))
    verdicts = _verdicts(completed, gates_ok, cases)
    assert verdicts["L9"].passed is False
    assert verdicts["L9"].failed_ledgers == ("alpha", "beta")


def test_l9_does_not_fail_on_a_not_evaluated_case_but_requires_full_coverage(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    skipped = _case("alpha", CASE_IDS[2], None, ())
    cases = tuple(
        skipped if (c.ledger, c.case_id) == ("alpha", CASE_IDS[2]) else c for c in cases_ok
    )
    verdicts = _verdicts(completed, gates_ok, cases)
    assert verdicts["L9"].passed is True
    verdicts = _verdicts(completed, gates_ok, cases_ok[:-1])
    assert verdicts["L9"].passed is False
    assert verdicts["L9"].failed_ledgers == ()
    verdicts = _verdicts(completed, gates_ok, (*cases_ok, cases_ok[0]))
    assert verdicts["L9"].passed is False


# --- attribution and failure discipline -------------------------------------------


def test_per_ledger_verdicts_attribute_each_corrupted_ledger_in_canonical_order(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    run = completed
    for ledger in LEDGERS[::-1]:
        record = _ledger(run, ledger)
        run = _with_ledger(run, record.model_copy(update={"replay": None}))
    verdicts = _verdicts(run, gates_ok, cases_ok)
    assert verdicts["L4"].passed is False
    assert verdicts["L4"].failed_ledgers == ("alpha", "beta")
    assert verdicts["L1"].passed is True


def test_a_verdict_that_raises_fails_closed_unattributed(
    completed: RunResult,
    gates_ok: tuple[GateResult, ...],
    cases_ok: tuple[CaseResult, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken(_run: RunResult) -> object:
        raise RuntimeError("VERDICT_BROKEN")

    monkeypatch.setattr(integrity_module, "_l4", _broken)
    verdicts = _verdicts(completed, gates_ok, cases_ok)
    assert verdicts["L4"].passed is False
    assert verdicts["L4"].failed_ledgers == ()
    assert "RuntimeError: VERDICT_BROKEN" in verdicts["L4"].detail
    assert verdicts["L5"].passed is True


def test_integrity_verdicts_never_produce_none(
    completed: RunResult, gates_ok: tuple[GateResult, ...], cases_ok: tuple[CaseResult, ...]
) -> None:
    aborted = _aborted_at_call_three()
    for run, cases in ((completed, cases_ok), (aborted, evaluate_run(aborted))):
        for verdict in integrity_verdicts(run, preflight_gates=gates_ok, case_results=cases):
            assert verdict.passed is not None


# --- IntegrityVerdict validators --------------------------------------------------


def _verdict(**overrides: Any) -> IntegrityVerdict:
    fields: dict[str, Any] = {
        "id": "L1",
        "passed": False,
        "detail": "x",
        "applies_to": ("alpha", "beta"),
        "failed_ledgers": (),
    }
    fields.update(overrides)
    return IntegrityVerdict(**fields)


def test_verdict_accepts_canonical_attribution_and_unattributed_failure() -> None:
    assert _verdict(failed_ledgers=("alpha",)).failed_ledgers == ("alpha",)
    assert _verdict(failed_ledgers=("alpha", "beta")).failed_ledgers == ("alpha", "beta")
    assert _verdict(failed_ledgers=()).passed is False
    assert _verdict(passed=True).failed_ledgers == ()
    assert _verdict(passed=None).failed_ledgers == ()
    assert _verdict(applies_to=("beta",), failed_ledgers=("beta",)).applies_to == ("beta",)


def test_verdict_rejects_non_canonical_order_duplicates_and_out_of_scope_ledgers() -> None:
    with pytest.raises(ValidationError, match="canonical"):
        _verdict(failed_ledgers=("beta", "alpha"))
    with pytest.raises(ValidationError, match="more than once"):
        _verdict(failed_ledgers=("alpha", "alpha"))
    with pytest.raises(ValidationError, match="scope"):
        _verdict(applies_to=("alpha",), failed_ledgers=("beta",))
    with pytest.raises(ValidationError):
        _verdict(failed_ledgers=("gamma",))


def test_verdict_rejects_attribution_unless_failed() -> None:
    with pytest.raises(ValidationError, match="passed"):
        _verdict(passed=True, failed_ledgers=("alpha",))
    with pytest.raises(ValidationError, match="not-evaluated"):
        _verdict(passed=None, failed_ledgers=("alpha",))


def test_verdict_is_frozen_and_snapshot_type_is_the_reused_9p3_one(completed: RunResult) -> None:
    verdict = _verdict(passed=True)
    with pytest.raises(Exception):  # noqa: B017 - FrozenModel refuses assignment
        verdict.passed = False
    snapshot = _delta(completed, "alpha", 1).reference_snapshots[0]
    assert isinstance(snapshot, RequestReferenceSnapshot)
    assert snapshot.arm == "F"
