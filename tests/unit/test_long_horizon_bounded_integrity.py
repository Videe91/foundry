"""9P3 T5: the 23-gate preflight and the post-run integrity verdicts I1-I15 (spec §12,
§15, §18.3; T5 brief; clarifications 6-10).

``preflight`` is driven with fake Git / command runners, a synthetic manifest built
from the frozen T1/T5 values, injected request-path sources and an injected observed
``GRPC_DNS_RESOLVER``; every gate is proven to pass on correct input and to fail on
one specific corruption. ``integrity_verdicts`` is driven with a scripted ``RunResult``
produced by the T4 fakes through the real governor path (reused from
``test_long_horizon_bounded_runner``), and every verdict I1-I15 is proven to PASS on
it and to FAIL under one mutation each; the 47 -> 48 -> 49 authorization-ceiling case
proves that a durable human AGREE absent from ``CellRecord.authorizations`` is still
recognised from the ledger. Nothing here shells out, reads the environment or
constructs a provider client; ZERO live calls; sockets are blocked.
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_long_horizon_bounded_runner import (
    FR_FINGERPRINT,
    Harness,
    _bind_id,
    _cell,
    _claim_id,
    _human_judgments,
    _position,
    _supersede_id,
)

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    POLICY_VERSION,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SYSTEM_INSTRUCTION_SHA256,
    XAIProviderError,
)
from foundry.domain.admission import AdmissionRoute
from foundry.domain.common import Authority
from foundry.domain.events import (
    EventType,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    StoredEvent,
)
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    ConflictsWithProposal,
    EquivalentProposal,
    JudgmentProposal,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.contrastive_unseen.integrity import (
    SCOPE_CLOSURE_REGRESSION_ARGV,
    TRACK_A_REGRESSION_ARGV,
    GateResult,
    all_passed,
)
from foundry.experiments.intent_v2_dogfood import ReplayResult
from foundry.experiments.long_horizon_bounded import integrity as integrity_module
from foundry.experiments.long_horizon_bounded.authority import AuthorizationOutcome
from foundry.experiments.long_horizon_bounded.expectations import expectations_document
from foundry.experiments.long_horizon_bounded.integrity import (
    CEILING_KEYS,
    CORE_PATH_PREFIXES,
    EXPERIMENT_ARTIFACT_DIR,
    GATE_I13_NAME,
    GATE_I14_NAME,
    GATE_NAMES,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PRESERVATION_BASE_SHA,
    LOCKED_CEILINGS,
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
    MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES,
    MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256,
    MANIFEST_KEY_OUTPUT_SCHEMA_SHA256,
    MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA,
    PREDECESSOR_ARTIFACT_DIR,
    PREDECESSOR_RAW_EVIDENCE_SHA,
    PREREGISTRATION_FILES,
    R_CONTEXT_CHAR_BOUND,
    REQUIRED_MANIFEST_KEYS,
    VERDICT_IDS,
    CallJudgments,
    IntegrityVerdict,
    PreflightGateMissing,
    integrity_verdicts,
    preflight,
    r_context_within_bounds,
    request_only_reference_check,
)
from foundry.experiments.long_horizon_bounded.leakage import (
    REQUEST_PATH_MODULES,
    LeakageResult,
    run_leakage_gate,
)
from foundry.experiments.long_horizon_bounded.protocol import (
    ARM_SCHEDULE,
    AUTHORITY_CHECKPOINTS,
    F_PROJECT_ID,
    FROZEN_CORE_SHA,
    MAX_HUMAN_AUTHORIZATIONS,
)
from foundry.experiments.long_horizon_bounded.runner import (
    CellRecord,
    ExperimentBudget,
    ReferenceSnapshotMismatch,
    RequestReferenceSnapshot,
    RunResult,
    RunStatus,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    LOCI,
    evidence_id,
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
    "leakage_gate_passes",
    "track_a_regression_passes",
    "scope_closure_regression_passes",
    "historical_artifacts_unchanged",
    "grpc_dns_resolver_is_native",
    "predecessor_raw_evidence_unchanged",
    "r_cumulative_context_within_bounds",
)
EXPECTED_HISTORICAL_DIRS = (
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
    "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/",
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/",
    "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/",
)
EXPECTED_VERDICT_IDS = tuple(f"I{n}" for n in range(1, 16))
EXPECTED_APPLIES_TO = {
    "I1": ("F", "A"),
    "I2": ("F", "A", "R"),
    "I3": ("F", "A", "R"),
    "I4": ("F", "A", "R"),
    "I5": ("F", "R"),
    "I6": ("F", "A", "R"),
    "I7": ("F", "A"),
    "I8": ("F", "A"),
    "I9": ("F", "A", "R"),
    "I10": ("F", "A", "R"),
    "I11": ("F", "A"),
    "I12": ("F", "A", "R"),
    "I13": ("R",),
    "I14": ("F", "A", "R"),
    "I15": ("F", "A"),
}

HARNESS_SHA = "a" * 40
SEAL_SHA = "5" * 40
BASE_SHA = "43e5ea60cd92b700db4c58314a5ce68c50028169"
PREDECESSOR_SHA = "201198f60c51e16269451e7d582027361d7e8a24"
PREDECESSOR_DIR = "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/"
EXPERIMENT_DIR = "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"
PACKAGE_DIR = Path("src/foundry/experiments/long_horizon_bounded")
HARNESS_CHANGES = (
    "src/foundry/experiments/long_horizon_bounded/__init__.py",
    "src/foundry/experiments/long_horizon_bounded/timeline.py",
    "src/foundry/experiments/long_horizon_bounded/runner.py",
    "src/foundry/experiments/contrastive_unseen/integrity.py",
    "scripts/run_long_horizon_bounded_memory.py",
    "tests/unit/test_long_horizon_bounded_runner.py",
    "docs/superpowers/plans/2026-09-13-9p3-long-horizon-bounded-memory.md",
    *PREREGISTRATION_FILES,
)
"""What changed between the frozen core and the 9P3 seal: experiment code, scripts,
tests, docs and the two seal files -- nothing under a core prefix."""
CHANGES_SINCE_PREDECESSOR = (
    "src/foundry/experiments/long_horizon_bounded/timeline.py",
    "src/foundry/experiments/long_horizon_bounded/runner.py",
    "tests/unit/test_long_horizon_bounded_runner.py",
    *PREREGISTRATION_FILES,
)
"""What changed between the 9P2 v3 raw-evidence commit and the 9P3 seal: nothing
under the predecessor directory."""
TREE_HASHES = {
    directory: hashlib.sha1(directory.encode()).hexdigest()
    for directory in EXPECTED_HISTORICAL_DIRS
}

ABLATION_SOURCE_THREE_CALLS = """
def assimilate_ablation_delta(governor, reasoner, delta):
    governor.propose_and_submit(reasoner, delta)
    governor.propose_and_submit(reasoner, delta)
    governor.propose_and_submit(reasoner, delta)
"""

RUNNER_SOURCE_SHARED_LEDGER = '''"""Synthetic runner whose R path reuses a shared store."""

from foundry.adapters.memory.event_store import InMemoryEventStore

SHARED = InMemoryEventStore()


def run_reconstruction_step(t: int) -> object:
    return SHARED
'''

T0 = datetime(2026, 9, 13, tzinfo=UTC)


def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sockets(monkeypatch)


REAL_R_CONTEXT = integrity_module.r_context_within_bounds
"""The real gate-23 function, kept so tests can restore it under the cache below."""


@pytest.fixture(scope="module")
def r_context_real() -> tuple[bool, str]:
    """Gate 23 evaluated once for real (sixteen fresh governors over the cumulative
    corpora, several seconds)."""
    return REAL_R_CONTEXT()


@pytest.fixture(autouse=True)
def _cached_r_context(monkeypatch: pytest.MonkeyPatch, r_context_real: tuple[bool, str]) -> None:
    """Every preflight run in this module consumes the one cached real gate-23 result;
    the gate-23 tests and the all-gates test restore ``REAL_R_CONTEXT`` explicitly so
    the gate is exercised for real there. Test speed only; nothing in the module
    under test changes."""
    monkeypatch.setattr(integrity_module, "r_context_within_bounds", lambda: r_context_real)


def _use_real_r_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integrity_module, "r_context_within_bounds", REAL_R_CONTEXT)


@pytest.fixture(scope="module")
def leakage_ok() -> LeakageResult:
    result = run_leakage_gate()
    assert result.passed
    return result


@pytest.fixture(scope="module")
def completed() -> Iterator[tuple[Harness, RunResult]]:
    """One scripted, fully completed 48-cell walk through the real governor path."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        harness = Harness()
        result = harness.run()
        assert result.status is RunStatus.COMPLETED
        yield harness, result


@pytest.fixture(scope="module")
def gates_ok(leakage_ok: LeakageResult) -> tuple[GateResult, ...]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        gates = _preflight(leakage_ok)
    assert all_passed(gates), [(g.name, g.detail) for g in gates if not g.passed]
    return gates


# --- fakes ------------------------------------------------------------------------


class FakeGit:
    def __init__(
        self,
        *,
        head: str = SEAL_SHA,
        dirty: str = "",
        parents: dict[str, tuple[str, ...]] | None = None,
        ancestors: frozenset[tuple[str, str]] = frozenset(
            {(FROZEN_CORE_SHA, SEAL_SHA), (BASE_SHA, SEAL_SHA), (PREDECESSOR_SHA, SEAL_SHA)}
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
                (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
                (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
                (PREDECESSOR_SHA, SEAL_SHA): CHANGES_SINCE_PREDECESSOR,
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
        trees[(BASE_SHA, directory)] = tree
        trees[(SEAL_SHA, directory)] = tree
    return trees


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
        MANIFEST_KEY_CEILINGS: dict(LOCKED_CEILINGS),
        MANIFEST_KEY_EVIDENCE: [record.model_dump(mode="json") for record in evidence_records()],
        MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256: leakage.needle_set_sha256,
        MANIFEST_KEY_EXPECTATIONS_SHA256: canonical_sha256(expectations_document()),
        MANIFEST_KEY_GRPC_DNS_RESOLVER: "native",
        MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES: dict(TREE_HASHES),
        MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA: PREDECESSOR_SHA,
    }
    loaded = json.loads(json.dumps(manifest))
    assert isinstance(loaded, dict)
    return loaded


def _manifest_with(leakage: LeakageResult, key: str, value: Any) -> dict[str, Any]:
    manifest = _manifest(leakage)
    manifest[key] = value
    return manifest


def _expectations_bytes() -> bytes:
    return json.dumps(expectations_document(), indent=2).encode("utf-8")


def _real_source(name: str) -> str:
    return (PACKAGE_DIR / name).read_text(encoding="utf-8")


def _sources(**overrides: str | None) -> dict[str, str]:
    sources = {name: _real_source(name) for name in REQUEST_PATH_MODULES}
    for key, value in overrides.items():
        if value is None:
            sources.pop(key)
        else:
            sources[key] = value
    return sources


def _preflight(
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
) -> tuple[GateResult, ...]:
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
    return results


def _run(leakage: LeakageResult, **kwargs: Any) -> dict[str, GateResult]:
    return {r.name: r for r in _preflight(leakage, **kwargs)}


def _verdicts(run: RunResult, gates: tuple[GateResult, ...]) -> dict[str, IntegrityVerdict]:
    verdicts = integrity_verdicts(run, preflight_gates=gates)
    assert tuple(v.id for v in verdicts) == EXPECTED_VERDICT_IDS
    return {v.id: v for v in verdicts}


def _with_cells(run: RunResult, cells: list[CellRecord]) -> RunResult:
    return run.model_copy(
        update={"cells": tuple(cells), "r_cells": {c.t: c for c in cells if c.arm == "R"}}
    )


def _replace_cell(run: RunResult, cell: CellRecord) -> RunResult:
    cells = list(run.cells)
    cells[cell.position] = cell
    return _with_cells(run, cells)


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


def _drop_judgment_event(judgment_id: str) -> LedgerMap:
    """Remove the recorded-judgment event and renumber, so the ledger still looks
    append-only and only the judgment itself is missing."""

    def apply(ledger: tuple[StoredEvent, ...]) -> tuple[StoredEvent, ...]:
        kept = [
            stored
            for stored in ledger
            if (j := _judgment_of(stored)) is None or j.judgment_id != judgment_id
        ]
        return tuple(
            stored.model_copy(update={"sequence": index}) for index, stored in enumerate(kept, 1)
        )

    return apply


def _mutate_arm_ledgers(run: RunResult, arm: str, mapping: LedgerMap) -> RunResult:
    """Apply ``mapping`` to the arm summary ledger and to every cell ledger of ``arm``
    (a prefix-consistent rewrite: a cell recorded before the affected event is
    unchanged). The summary ledger must actually change."""
    cells = [
        c.model_copy(update={"ledger": mapping(c.ledger)}) if c.arm == arm and c.ledger else c
        for c in run.cells
    ]
    run = _with_cells(run, cells)
    summary = run.f if arm == "F" else run.a
    rewritten = mapping(summary.ledger)
    assert rewritten != summary.ledger
    summary = summary.model_copy(update={"ledger": rewritten})
    return run.model_copy(update={arm.lower(): summary})


def _mutate_cell_ledger(run: RunResult, arm: str, t: int, mapping: LedgerMap) -> RunResult:
    cell = _cell(run, arm, t)
    return _replace_cell(run, cell.model_copy(update={"ledger": mapping(cell.ledger)}))


def _judgment(
    proposal: JudgmentProposal,
    *,
    judgment_id: str = "J-test",
    visible: tuple[str, ...],
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=F_PROJECT_ID,
        proposal=proposal,
        visible_evidence_ids=visible,
        rationale="Opaque test rationale.",
        reasoner=FR_FINGERPRINT,
        invocation_id="INV-test",
        proposed_at=T0,
    )


def _assert(address_id: str, evidence: tuple[str, ...]) -> AssertClaimProposal:
    return AssertClaimProposal(
        address_id=address_id,
        predicate="policy_value",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="opaque"),
        evidence_ids=evidence,
        authority=Authority.OBSERVED,
    )


def _f_t3_call2(result: RunResult) -> tuple[Any, RequestReferenceSnapshot]:
    cell = _cell(result, "F", 3)
    record, snapshot = cell.requests[1], cell.reference_snapshots[1]
    assert record.call_number == 2 and snapshot.call_number == 2
    assert len(snapshot.known_claim_ids) >= 2
    assert len(snapshot.known_address_ids) >= 2
    return record, snapshot


# --- shape ------------------------------------------------------------------------


def test_gate_names_are_the_twenty_three_9p3_gates_in_order() -> None:
    assert GATE_NAMES == EXPECTED_GATE_NAMES
    assert len(GATE_NAMES) == 23
    assert len(set(GATE_NAMES)) == 23
    assert GATE_I13_NAME == "r_cumulative_context_within_bounds"
    assert GATE_I14_NAME == "leakage_gate_passes"
    assert GATE_I13_NAME in GATE_NAMES and GATE_I14_NAME in GATE_NAMES


def test_frozen_constants_are_the_brief_literals() -> None:
    assert HISTORICAL_PRESERVATION_BASE_SHA == "43e5ea60cd92b700db4c58314a5ce68c50028169"
    assert HISTORICAL_ARTIFACT_DIRS == EXPECTED_HISTORICAL_DIRS
    assert PREDECESSOR_RAW_EVIDENCE_SHA == "201198f60c51e16269451e7d582027361d7e8a24"
    assert PREDECESSOR_ARTIFACT_DIR == PREDECESSOR_DIR
    assert PREDECESSOR_ARTIFACT_DIR in HISTORICAL_ARTIFACT_DIRS
    assert EXPERIMENT_ARTIFACT_DIR == EXPERIMENT_DIR
    assert PREREGISTRATION_FILES == (
        EXPERIMENT_DIR + "manifest.json",
        EXPERIMENT_DIR + "expectations.json",
    )
    assert CORE_PATH_PREFIXES == (
        "src/foundry/domain/",
        "src/foundry/application/",
        "src/foundry/ports/",
        "src/foundry/adapters/",
    )
    assert CEILING_KEYS == (
        "max_frontier_calls",
        "max_judge_calls",
        "max_semantic_retries",
        "max_same_cell_reruns",
        "max_human_authorizations",
        "max_provider_cost_usd",
    )
    assert LOCKED_CEILINGS == {
        "max_frontier_calls": 96,
        "max_judge_calls": 0,
        "max_semantic_retries": 0,
        "max_same_cell_reruns": 0,
        "max_human_authorizations": 48,
        "max_provider_cost_usd": 10.0,
    }
    assert R_CONTEXT_CHAR_BOUND == 100_000
    assert VERDICT_IDS == EXPECTED_VERDICT_IDS
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
        "historical_artifact_tree_hashes",
        "predecessor_raw_evidence_sha",
    )
    for directory in HISTORICAL_ARTIFACT_DIRS:
        assert Path(directory).is_dir(), directory


def test_all_gates_pass_on_correct_input(
    leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_real_r_context(monkeypatch)
    git = FakeGit()
    commands = FakeCommands()
    results = _run(leakage_ok, git=git, commands=commands)
    failing = [(name, r.detail) for name, r in results.items() if not r.passed]
    assert failing == []
    assert all_passed(results.values())
    assert commands.argvs == [TRACK_A_REGRESSION_ARGV, SCOPE_CLOSURE_REGRESSION_ARGV]
    assert ("tree_sha", BASE_SHA, EXPECTED_HISTORICAL_DIRS[0]) in git.calls
    assert ("tree_sha", SEAL_SHA, EXPECTED_HISTORICAL_DIRS[-1]) in git.calls


# --- gates 1-4: git ---------------------------------------------------------------


def test_gate_1_fails_when_head_is_not_the_seal(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, git=FakeGit(head="9" * 40))
    assert results["head_equals_final_seal"].passed is False
    assert SEAL_SHA in results["head_equals_final_seal"].detail


def test_gate_1_fails_when_seal_parent_is_not_the_harness_commit_or_is_a_merge(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok, git=FakeGit(parents={SEAL_SHA: ("c" * 40,)}))
    assert results["head_equals_final_seal"].passed is False
    assert HARNESS_SHA in results["head_equals_final_seal"].detail
    results = _run(leakage_ok, git=FakeGit(parents={SEAL_SHA: (HARNESS_SHA, "c" * 40)}))
    assert results["head_equals_final_seal"].passed is False


def test_gate_1_fails_when_seal_changes_anything_but_the_two_prereg_files(
    leakage_ok: LeakageResult,
) -> None:
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): (*PREREGISTRATION_FILES, HARNESS_CHANGES[0]),
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
            (PREDECESSOR_SHA, SEAL_SHA): CHANGES_SINCE_PREDECESSOR,
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["head_equals_final_seal"].passed is False
    assert HARNESS_CHANGES[0] in results["head_equals_final_seal"].detail
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): tuple(reversed(PREREGISTRATION_FILES)),
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
            (PREDECESSOR_SHA, SEAL_SHA): CHANGES_SINCE_PREDECESSOR,
        }
    )
    assert _run(leakage_ok, git=git)["head_equals_final_seal"].passed is True


def test_gate_2_fails_on_a_dirty_worktree(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, git=FakeGit(dirty=" M src/foundry/x.py\n"))
    assert results["worktree_clean"].passed is False
    assert "src/foundry/x.py" in results["worktree_clean"].detail


def test_gate_3_fails_when_seal_does_not_descend_from_frozen_core(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(
        leakage_ok,
        git=FakeGit(ancestors=frozenset({(BASE_SHA, SEAL_SHA), (PREDECESSOR_SHA, SEAL_SHA)})),
    )
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
            (PREDECESSOR_SHA, SEAL_SHA): CHANGES_SINCE_PREDECESSOR,
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["core_paths_unchanged_since_frozen_core"].passed is False
    assert core_path in results["core_paths_unchanged_since_frozen_core"].detail


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
    assert [name for name, r in results.items() if not r.passed] == [gate]


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


def test_gate_11_passes_on_the_reused_9p2_ablation_source_and_fails_on_three_calls(
    leakage_ok: LeakageResult,
) -> None:
    results = _run(leakage_ok)
    assert results["a_two_calls_no_retry"].passed is True
    assert "ablation.py" in results["a_two_calls_no_retry"].detail
    results = _run(leakage_ok, sources=_sources(**{"ablation.py": ABLATION_SOURCE_THREE_CALLS}))
    assert results["a_two_calls_no_retry"].passed is False
    assert "3" in results["a_two_calls_no_retry"].detail


def test_gate_12_passes_on_the_real_runner_and_fails_when_missing_or_shared(
    leakage_ok: LeakageResult,
) -> None:
    assert _run(leakage_ok)["r_uses_fresh_ledger_per_t"].passed is True
    results = _run(leakage_ok, sources=_sources(**{"runner.py": None}))
    assert results["r_uses_fresh_ledger_per_t"].passed is False
    assert "runner.py" in results["r_uses_fresh_ledger_per_t"].detail
    results = _run(leakage_ok, sources=_sources(**{"runner.py": RUNNER_SOURCE_SHARED_LEDGER}))
    assert results["r_uses_fresh_ledger_per_t"].passed is False


# --- gates 13-15: sealed design data ----------------------------------------------


def test_gate_13_fails_when_a_sealed_evidence_record_differs(leakage_ok: LeakageResult) -> None:
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_EVIDENCE][3]["content_sha256"] = "0" * 64
    assert _run(leakage_ok, manifest=manifest)["evidence_manifest_frozen"].passed is False
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_EVIDENCE].pop()
    assert _run(leakage_ok, manifest=manifest)["evidence_manifest_frozen"].passed is False
    detail = _run(leakage_ok)["evidence_manifest_frozen"].detail
    assert "192" in detail


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
        ("max_frontier_calls", 97),
        ("max_judge_calls", 1),
        ("max_semantic_retries", 1),
        ("max_same_cell_reruns", 1),
        ("max_human_authorizations", 47),
        ("max_provider_cost_usd", 11.0),
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
    del manifest[MANIFEST_KEY_CEILINGS]["max_same_cell_reruns"]
    assert _run(leakage_ok, manifest=manifest)["ceilings_frozen"].passed is False
    manifest = _manifest(leakage_ok)
    manifest[MANIFEST_KEY_CEILINGS]["max_retries"] = 0
    assert _run(leakage_ok, manifest=manifest)["ceilings_frozen"].passed is False


def test_missing_manifest_key_fails_only_the_gate_that_needs_it(
    leakage_ok: LeakageResult,
) -> None:
    manifest = _manifest(leakage_ok)
    del manifest[MANIFEST_KEY_ARM_SCHEDULE]
    results = _run(leakage_ok, manifest=manifest)
    assert [n for n, r in results.items() if not r.passed] == ["arm_schedule_frozen"]
    assert MANIFEST_KEY_ARM_SCHEDULE in results["arm_schedule_frozen"].detail


# --- gate 16: request-path import hygiene ----------------------------------------


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
    failed = run_leakage_gate(extra_harness_text=("checkpoint C02 failed",))
    assert failed.passed is False
    results = _run(leakage_ok, leakage_override=failed)
    assert results["leakage_gate_passes"].passed is False
    assert "C02" in results["leakage_gate_passes"].detail
    assert "CHECKPOINT_LABEL" in results["leakage_gate_passes"].detail
    assert "EXTRA_HARNESS_TEXT_0" in results["leakage_gate_passes"].detail


def test_gate_17_fails_when_needle_set_sha_or_expectations_differ(
    leakage_ok: LeakageResult,
) -> None:
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_LEAKAGE_NEEDLE_SET_SHA256, "0" * 64)
    assert _run(leakage_ok, manifest=manifest)["leakage_gate_passes"].passed is False
    document = expectations_document()
    document["tampered"] = "x"
    results = _run(leakage_ok, expectations_bytes=json.dumps(document).encode("utf-8"))
    assert results["leakage_gate_passes"].passed is False
    assert "expectations" in results["leakage_gate_passes"].detail
    assert _run(leakage_ok, expectations_bytes=b"{not json")["leakage_gate_passes"].passed is False
    reformatted = json.dumps(expectations_document(), indent=4, sort_keys=True).encode("utf-8")
    assert _run(leakage_ok, expectations_bytes=reformatted)["leakage_gate_passes"].passed is True


def test_gate_17_fails_when_leakage_prompt_hashes_are_not_the_frozen_ones(
    leakage_ok: LeakageResult,
) -> None:
    drifted = leakage_ok.model_copy(update={"fr_prompt_sha256": "1" * 64})
    assert _run(leakage_ok, leakage_override=drifted)["leakage_gate_passes"].passed is False
    drifted = leakage_ok.model_copy(update={"a_prompt_sha256": "1" * 64})
    assert _run(leakage_ok, leakage_override=drifted)["leakage_gate_passes"].passed is False


# --- gates 18-19: regression commands ---------------------------------------------


def test_gates_18_and_19_fail_on_a_non_zero_exit(leakage_ok: LeakageResult) -> None:
    results = _run(leakage_ok, commands=FakeCommands({TRACK_A_REGRESSION_ARGV: 1}))
    assert results["track_a_regression_passes"].passed is False
    assert "exit 1" in results["track_a_regression_passes"].detail
    assert results["scope_closure_regression_passes"].passed is True
    results = _run(leakage_ok, commands=FakeCommands({SCOPE_CLOSURE_REGRESSION_ARGV: 2}))
    assert results["scope_closure_regression_passes"].passed is False
    assert results["track_a_regression_passes"].passed is True


# --- gate 20: historical artifact preservation --------------------------------------


@pytest.mark.parametrize("directory", EXPECTED_HISTORICAL_DIRS)
def test_gate_20_fails_when_a_historical_tree_differs_between_base_and_seal(
    leakage_ok: LeakageResult, directory: str
) -> None:
    trees = _default_trees()
    trees[(SEAL_SHA, directory)] = "f" * 40
    results = _run(leakage_ok, git=FakeGit(trees=trees))
    assert results["historical_artifacts_unchanged"].passed is False
    assert directory in results["historical_artifacts_unchanged"].detail


def test_gate_20_fails_when_the_manifest_tree_hash_differs_or_a_dir_is_missing(
    leakage_ok: LeakageResult,
) -> None:
    hashes = dict(TREE_HASHES)
    hashes[EXPECTED_HISTORICAL_DIRS[2]] = "e" * 40
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES, hashes)
    results = _run(leakage_ok, manifest=manifest)
    assert results["historical_artifacts_unchanged"].passed is False
    assert EXPECTED_HISTORICAL_DIRS[2] in results["historical_artifacts_unchanged"].detail
    hashes = dict(TREE_HASHES)
    del hashes[EXPECTED_HISTORICAL_DIRS[4]]
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_HISTORICAL_ARTIFACT_TREE_HASHES, hashes)
    results = _run(leakage_ok, manifest=manifest)
    assert results["historical_artifacts_unchanged"].passed is False
    assert EXPECTED_HISTORICAL_DIRS[4] in results["historical_artifacts_unchanged"].detail


def test_gate_20_fails_when_the_preservation_base_is_not_an_ancestor(
    leakage_ok: LeakageResult,
) -> None:
    git = FakeGit(ancestors=frozenset({(FROZEN_CORE_SHA, SEAL_SHA), (PREDECESSOR_SHA, SEAL_SHA)}))
    results = _run(leakage_ok, git=git)
    assert results["historical_artifacts_unchanged"].passed is False
    assert BASE_SHA in results["historical_artifacts_unchanged"].detail


def test_gate_20_never_computes_the_baseline_from_head(leakage_ok: LeakageResult) -> None:
    git = FakeGit()
    _run(leakage_ok, git=git)
    tree_calls = [c for c in git.calls if c[0] == "tree_sha"]
    assert {c[1] for c in tree_calls} == {BASE_SHA, SEAL_SHA}
    assert len(tree_calls) == 2 * len(EXPECTED_HISTORICAL_DIRS)


# --- gate 21: GRPC_DNS_RESOLVER ---------------------------------------------------------


@pytest.mark.parametrize("observed", [None, "", "ares", "Native", "native "])
def test_gate_21_fails_for_every_non_native_observed_value(
    leakage_ok: LeakageResult, observed: str | None
) -> None:
    results = _run(leakage_ok, observed_grpc_dns_resolver=observed)
    assert results["grpc_dns_resolver_is_native"].passed is False
    assert repr(observed) in results["grpc_dns_resolver_is_native"].detail


def test_gate_21_fails_when_the_manifest_value_is_not_native(leakage_ok: LeakageResult) -> None:
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_GRPC_DNS_RESOLVER, "ares")
    assert _run(leakage_ok, manifest=manifest)["grpc_dns_resolver_is_native"].passed is False


# --- gate 22: predecessor raw evidence ------------------------------------------------


def test_gate_22_fails_when_a_predecessor_path_changed_since_the_raw_evidence_commit(
    leakage_ok: LeakageResult,
) -> None:
    touched = PREDECESSOR_DIR + "raw/run.json"
    git = FakeGit(
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
            (PREDECESSOR_SHA, SEAL_SHA): (*CHANGES_SINCE_PREDECESSOR, touched),
        }
    )
    results = _run(leakage_ok, git=git)
    assert results["predecessor_raw_evidence_unchanged"].passed is False
    assert touched in results["predecessor_raw_evidence_unchanged"].detail


def test_gate_22_fails_when_the_raw_evidence_commit_is_not_an_ancestor(
    leakage_ok: LeakageResult,
) -> None:
    git = FakeGit(ancestors=frozenset({(FROZEN_CORE_SHA, SEAL_SHA), (BASE_SHA, SEAL_SHA)}))
    results = _run(leakage_ok, git=git)
    assert results["predecessor_raw_evidence_unchanged"].passed is False
    assert PREDECESSOR_SHA in results["predecessor_raw_evidence_unchanged"].detail


def test_gate_22_fails_when_the_manifest_names_another_commit(leakage_ok: LeakageResult) -> None:
    manifest = _manifest_with(leakage_ok, MANIFEST_KEY_PREDECESSOR_RAW_EVIDENCE_SHA, "b" * 40)
    assert _run(leakage_ok, manifest=manifest)["predecessor_raw_evidence_unchanged"].passed is False


# --- gate 23: R cumulative context bound (I13) -----------------------------------------


def test_gate_23_compiles_every_r_call_1_request_offline_and_reports_t16(
    leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_real_r_context(monkeypatch)
    passed, detail = r_context_within_bounds()
    assert passed is True
    for t in range(1, 17):
        assert f"T{t:02d}=" in detail
    assert "T16=" in detail
    assert "100000" in detail
    gate = _run(leakage_ok)["r_cumulative_context_within_bounds"]
    assert gate.passed is True
    assert gate.detail == detail


def test_gate_23_fails_when_t16_exceeds_the_bound(
    leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_real_r_context(monkeypatch)
    monkeypatch.setattr(integrity_module, "R_CONTEXT_CHAR_BOUND", 1)
    passed, detail = r_context_within_bounds()
    assert passed is False
    assert "T16" in detail and "exceeds bound 1" in detail
    assert _run(leakage_ok)["r_cumulative_context_within_bounds"].passed is False


def test_gate_23_fails_closed_when_assembly_raises(
    leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refuse(**_kwargs: object) -> object:
        raise integrity_module.ContextUnsupported("UNSUPPORTED_ABOVE_THRESHOLD: synthetic")

    monkeypatch.setattr(integrity_module, "assemble_assimilation_request", _refuse)
    passed, detail = r_context_within_bounds()
    assert passed is False
    assert "UNSUPPORTED_ABOVE_THRESHOLD" in detail


# --- module law -------------------------------------------------------------------------


def test_integrity_source_never_touches_the_environment_or_a_provider() -> None:
    source = Path(integrity_module.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in source
    assert "getenv" not in source
    assert "XAI_API_KEY" not in source
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "os" not in imported
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "XAISemanticReasoner" not in names
    assert "XAIContrastiveSemanticReasoner" not in names
    # Post-run integrity never re-runs the leakage gate: only the preflight gate is consumed.
    assert "run_leakage_gate" not in names
    assert "scan_skeletons" not in names
    assert "build_skeletons" not in names
    assert "expectations" not in {n.rsplit(".", 1)[-1] for n in imported}


# --- I13 / I14 consumption of preflight gates -----------------------------------------------


def test_i13_and_i14_consume_exactly_their_preflight_gates(
    completed: tuple[Harness, RunResult], leakage_ok: LeakageResult
) -> None:
    _, result = completed
    gates = _preflight(leakage_ok)
    assert all_passed(gates)
    verdicts = _verdicts(result, gates)
    assert verdicts["I13"].passed is True
    assert verdicts["I14"].passed is True
    assert verdicts["I13"].applies_to == ("R",)
    assert "T16=" in verdicts["I13"].detail
    for name in (GATE_I13_NAME, GATE_I14_NAME):
        absent = tuple(g for g in gates if g.name != name)
        with pytest.raises(PreflightGateMissing, match=name):
            integrity_verdicts(result, preflight_gates=absent)
        duplicated = (*gates, next(g for g in gates if g.name == name))
        with pytest.raises(PreflightGateMissing, match=name):
            integrity_verdicts(result, preflight_gates=duplicated)
    failed_i13 = tuple(
        g.model_copy(update={"passed": False, "detail": "T16 over bound"})
        if g.name == GATE_I13_NAME
        else g
        for g in gates
    )
    verdicts = _verdicts(result, failed_i13)
    assert verdicts["I13"].passed is False
    assert "T16 over bound" in verdicts["I13"].detail
    assert verdicts["I14"].passed is True
    failed_i14 = tuple(
        g.model_copy(update={"passed": False, "detail": "needle leaked"})
        if g.name == GATE_I14_NAME
        else g
        for g in gates
    )
    verdicts = _verdicts(result, failed_i14)
    assert verdicts["I14"].passed is False
    assert "needle leaked" in verdicts["I14"].detail
    assert verdicts["I13"].passed is True


# --- I10: request-only reference law ---------------------------------------------------------


def test_i10_supersede_of_a_sibling_drafts_claim_fails(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    sibling = _claim_id(evidence_id(3, "A"))
    assert sibling not in snapshot.known_claim_creating_judgment_ids
    judgment = _judgment(
        SupersedeProposal(target_judgment_id=sibling, reason="Opaque."),
        visible=snapshot.citable_evidence_ids,
    )
    passed, detail = request_only_reference_check((CallJudgments(record, snapshot, (judgment,)),))
    assert passed is False
    assert "J-test" in detail and "F T3 call 2" in detail


def test_i10_assert_at_an_unknown_address_fails(completed: tuple[Harness, RunResult]) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    judgment = _judgment(
        _assert("ADDR-not-in-request", snapshot.citable_evidence_ids[:1]),
        visible=snapshot.citable_evidence_ids,
    )
    passed, _ = request_only_reference_check((CallJudgments(record, snapshot, (judgment,)),))
    assert passed is False


def test_i10_supports_of_an_unknown_claim_fails(completed: tuple[Harness, RunResult]) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    judgment = _judgment(
        SupportsClaimProposal(
            claim_id="CLAIM-not-in-request", evidence_ids=snapshot.citable_evidence_ids[:1]
        ),
        visible=snapshot.citable_evidence_ids,
    )
    passed, _ = request_only_reference_check((CallJudgments(record, snapshot, (judgment,)),))
    assert passed is False


def test_i10_citing_evidence_outside_the_request_fails(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    judgment = _judgment(
        _assert(snapshot.known_address_ids[0], ("EV-O-Z99",)),
        visible=snapshot.citable_evidence_ids,
    )
    passed, _ = request_only_reference_check((CallJudgments(record, snapshot, (judgment,)),))
    assert passed is False
    judgment = _judgment(
        _assert(snapshot.known_address_ids[0], snapshot.citable_evidence_ids[:1]),
        visible=(*snapshot.citable_evidence_ids, "EV-O-Z99"),
    )
    passed, _ = request_only_reference_check((CallJudgments(record, snapshot, (judgment,)),))
    assert passed is False


def test_i10_legitimate_correction_shape_passes(completed: tuple[Harness, RunResult]) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    assertion = _judgment(
        _assert(snapshot.known_address_ids[0], snapshot.citable_evidence_ids[:1]),
        judgment_id="J-test-assert",
        visible=snapshot.citable_evidence_ids,
    )
    supersede = _judgment(
        SupersedeProposal(
            target_judgment_id=snapshot.known_claim_creating_judgment_ids[0], reason="Opaque."
        ),
        judgment_id="J-test-supersede",
        visible=snapshot.citable_evidence_ids,
    )
    conflict = _judgment(
        ConflictsWithProposal(
            claim_a=snapshot.known_claim_ids[0], claim_b=snapshot.known_claim_ids[1]
        ),
        judgment_id="J-test-conflict",
        visible=snapshot.citable_evidence_ids,
    )
    equivalent = _judgment(
        EquivalentProposal(
            address_a=snapshot.known_address_ids[0], address_b=snapshot.known_address_ids[1]
        ),
        judgment_id="J-test-equivalent",
        visible=snapshot.citable_evidence_ids,
    )
    calls = (CallJudgments(record, snapshot, (assertion, supersede, conflict, equivalent)),)
    passed, detail = request_only_reference_check(calls)
    assert passed is True
    assert "every reference resolves against its exact request" in detail
    unknown_conflict = conflict.model_copy(
        update={
            "proposal": ConflictsWithProposal(
                claim_a=snapshot.known_claim_ids[0], claim_b="CLAIM-x"
            )
        }
    )
    passed, _ = request_only_reference_check(
        (CallJudgments(record, snapshot, (unknown_conflict,)),)
    )
    assert passed is False
    assert request_only_reference_check(()) == (
        True,
        "every reference resolves against its exact request; no same-response id used",
    )


@pytest.mark.parametrize("field", ["request_sha256", "arm", "t", "call_number"])
def test_i10_snapshot_identity_differing_from_its_record_raises(
    completed: tuple[Harness, RunResult], field: str
) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    replacement: Any = {"request_sha256": "0" * 64, "arm": "A", "t": 4, "call_number": 1}[field]
    drifted = snapshot.model_copy(update={field: replacement})
    with pytest.raises(ReferenceSnapshotMismatch, match="identity"):
        request_only_reference_check((CallJudgments(record, drifted, ()),))


def test_i10_snapshot_claim_ids_in_a_different_order_raises(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    reordered = snapshot.model_copy(
        update={
            "known_claim_ids": tuple(reversed(snapshot.known_claim_ids)),
            "known_claim_creating_judgment_ids": tuple(
                reversed(snapshot.known_claim_creating_judgment_ids)
            ),
        }
    )
    assert set(reordered.known_claim_ids) == set(snapshot.known_claim_ids)
    with pytest.raises(ReferenceSnapshotMismatch, match="tuples"):
        request_only_reference_check((CallJudgments(record, reordered, ()),))


def test_i10_creating_judgment_tuple_length_differing_raises(
    completed: tuple[Harness, RunResult],
) -> None:
    _, result = completed
    record, snapshot = _f_t3_call2(result)
    short = snapshot.model_copy(
        update={
            "known_claim_creating_judgment_ids": snapshot.known_claim_creating_judgment_ids[:-1]
        }
    )
    with pytest.raises(ReferenceSnapshotMismatch, match="length"):
        request_only_reference_check((CallJudgments(record, short, ()),))


def test_i10_mismatch_inside_integrity_verdicts_is_rendered_as_fail(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "F", 3)
    drifted = cell.reference_snapshots[1].model_copy(update={"request_sha256": "0" * 64})
    mutated = _replace_cell(
        result,
        cell.model_copy(update={"reference_snapshots": (cell.reference_snapshots[0], drifted)}),
    )
    verdict = _verdicts(mutated, gates_ok)["I10"]
    assert verdict.passed is False
    assert "ReferenceSnapshotMismatch" in verdict.detail
    assert "F T3 call 2" in verdict.detail


# --- post-run verdicts on the completed scripted run --------------------------------------------


def test_every_verdict_passes_on_the_completed_scripted_run(
    completed: tuple[Harness, RunResult], leakage_ok: LeakageResult
) -> None:
    _, result = completed
    gates = _preflight(leakage_ok)
    verdicts = integrity_verdicts(result, preflight_gates=gates)
    assert tuple(v.id for v in verdicts) == EXPECTED_VERDICT_IDS
    assert all(isinstance(v, IntegrityVerdict) for v in verdicts)
    failing = [(v.id, v.detail) for v in verdicts if v.passed is not True]
    assert failing == []
    assert {v.id: v.applies_to for v in verdicts} == EXPECTED_APPLIES_TO
    assert integrity_verdicts(result, preflight_gates=gates) == verdicts


def test_verdict_is_frozen(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    verdict = _verdicts(result, gates_ok)["I1"]
    with pytest.raises(Exception, match="frozen"):
        verdict.passed = False  # type: ignore[misc]


def test_i1_fails_on_a_duplicate_root_address(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    roots = dict(result.f.roots)
    roots["B"] = roots["B"].model_copy(update={"address_id": roots["A"].address_id})
    mutated = result.model_copy(update={"f": result.f.model_copy(update={"roots": roots})})
    verdict = _verdicts(mutated, gates_ok)["I1"]
    assert verdict.passed is False
    assert "F" in verdict.detail
    assert _verdicts(result, gates_ok)["I1"].detail.count("12") >= 2


def test_i2_fails_on_a_completed_cell_with_one_request(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "A", 5)
    mutated = _replace_cell(
        result,
        cell.model_copy(
            update={
                "requests": cell.requests[:1],
                "reference_snapshots": cell.reference_snapshots[:1],
            }
        ),
    )
    verdict = _verdicts(mutated, gates_ok)["I2"]
    assert verdict.passed is False
    assert "A T5" in verdict.detail


def test_i3_fails_on_a_duplicate_request_identity(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "R", 7)
    retried = cell.requests[1].model_copy(
        update={"request_sha256": cell.requests[0].request_sha256}
    )
    mutated = _replace_cell(
        result, cell.model_copy(update={"requests": (cell.requests[0], retried)})
    )
    verdict = _verdicts(mutated, gates_ok)["I3"]
    assert verdict.passed is False
    assert "duplicate" in verdict.detail
    three = _replace_cell(
        result, cell.model_copy(update={"requests": (*cell.requests, cell.requests[1])})
    )
    assert _verdicts(three, gates_ok)["I3"].passed is False


def test_i4_fails_when_a_proposal_cites_a_non_request_evidence_id(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    target = _claim_id(evidence_id(2, "A"))
    mutated = _mutate_cell_ledger(
        result,
        "F",
        2,
        _rewrite_judgment(
            target,
            lambda j: j.model_copy(
                update={"visible_evidence_ids": (*j.visible_evidence_ids, "EV-O-Z99")}
            ),
        ),
    )
    verdict = _verdicts(mutated, gates_ok)["I4"]
    assert verdict.passed is False
    assert target in verdict.detail and "EV-O-Z99" in verdict.detail


def test_i5_fails_when_a_comparison_only_predecessor_is_cited(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "F", 2)
    predecessor = evidence_id(1, "A")
    call1 = cell.requests[0]
    assert predecessor in call1.historical_comparison_evidence_ids
    assert predecessor not in call1.citable_evidence_ids
    bind = _bind_id(evidence_id(2, "A"))
    mutated = _mutate_cell_ledger(
        result,
        "F",
        2,
        _rewrite_judgment(
            bind,
            lambda j: j.model_copy(
                update={"visible_evidence_ids": (*j.visible_evidence_ids, predecessor)}
            ),
        ),
    )
    verdict = _verdicts(mutated, gates_ok)["I5"]
    assert verdict.passed is False
    assert predecessor in verdict.detail and bind in verdict.detail


def test_i6_fails_on_an_out_of_scope_known_address(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "F", 2)
    state = cell.state_snapshot
    assert state is not None
    address_id = cell.requests[0].known_address_ids[0]
    address = state.semantic.addresses[address_id]
    semantic = state.semantic.model_copy(
        update={
            "addresses": {
                **state.semantic.addresses,
                address_id: address.model_copy(update={"scope": ("elsewhere",)}),
            }
        }
    )
    mutated = _replace_cell(
        result,
        cell.model_copy(update={"state_snapshot": state.model_copy(update={"semantic": semantic})}),
    )
    verdict = _verdicts(mutated, gates_ok)["I6"]
    assert verdict.passed is False
    assert address_id in verdict.detail


def test_i6_fails_when_a_touched_address_leaves_the_call_2_known_addresses(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "F", 4)
    mutated = _replace_cell(
        result,
        cell.model_copy(update={"claim_neighborhood": (*cell.claim_neighborhood, "ADDR-foreign")}),
    )
    verdict = _verdicts(mutated, gates_ok)["I6"]
    assert verdict.passed is False
    assert "ADDR-foreign" in verdict.detail


def test_i7_fails_when_a_model_supersede_is_routed_apply(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    pending = _supersede_id(evidence_id(2, "B"))
    assert pending in result.f.final_state.semantic.judgments
    mutated = _mutate_arm_ledgers(result, "F", _rewrite_admission(pending, AdmissionRoute.APPLY))
    verdict = _verdicts(mutated, gates_ok)["I7"]
    assert verdict.passed is False
    assert pending in verdict.detail


def test_i8_fails_when_an_applied_agree_has_no_matching_pending_signature(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    (agree, _) = _human_judgments(_cell(result, "F", 3))[:2]
    mutated = _mutate_arm_ledgers(
        result,
        "F",
        _rewrite_judgment(
            agree.judgment_id,
            lambda j: j.model_copy(
                update={
                    "proposal": SupersedeProposal(
                        target_judgment_id="J-no-such-pending", reason="x"
                    )
                }
            ),
        ),
    )
    verdict = _verdicts(mutated, gates_ok)["I8"]
    assert verdict.passed is False
    assert agree.judgment_id in verdict.detail
    positive = _verdicts(result, gates_ok)["I8"]
    assert positive.passed is True
    assert str(result.budget.human_authorizations) in positive.detail


def test_i8_fails_when_an_applied_supersede_is_not_human(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    (agree, _) = _human_judgments(_cell(result, "F", 3))[:2]
    mutated = _mutate_arm_ledgers(
        result,
        "F",
        _rewrite_judgment(
            agree.judgment_id, lambda j: j.model_copy(update={"reasoner": FR_FINGERPRINT})
        ),
    )
    assert _verdicts(mutated, gates_ok)["I8"].passed is False


def test_i9_fails_on_a_replay_mismatch(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    assert result.a.replay is not None
    mismatch = ReplayResult(
        status="REPLAY_MISMATCH",
        event_count=result.a.replay.event_count,
        state_matches=False,
        view_matches=True,
    )
    mutated = result.model_copy(update={"a": result.a.model_copy(update={"replay": mismatch})})
    verdict = _verdicts(mutated, gates_ok)["I9"]
    assert verdict.passed is False
    assert "A" in verdict.detail
    absent = result.model_copy(update={"a": result.a.model_copy(update={"replay": None})})
    assert _verdicts(absent, gates_ok)["I9"].passed is False
    r_cell = _cell(result, "R", 9)
    truncated = _replace_cell(result, r_cell.model_copy(update={"ledger": r_cell.ledger[:-1]}))
    verdict = _verdicts(truncated, gates_ok)["I9"]
    assert verdict.passed is False
    assert "R T9" in verdict.detail


def test_i11_fails_when_a_superseded_judgment_is_missing_from_the_final_ledger(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    superseded = _claim_id(evidence_id(1, "A"))
    assert any(
        s.target_judgment_id == superseded for s in result.f.final_state.semantic.supersessions
    )
    mutated = _mutate_arm_ledgers(result, "F", _drop_judgment_event(superseded))
    assert len(mutated.f.ledger) == len(result.f.ledger) - 1
    assert [e.sequence for e in mutated.f.ledger] == list(range(1, len(result.f.ledger)))
    verdict = _verdicts(mutated, gates_ok)["I11"]
    assert verdict.passed is False
    assert superseded in verdict.detail
    # A non-contiguous ledger (a silently removed event) fails on its own.
    holed = result.model_copy(
        update={
            "f": result.f.model_copy(update={"ledger": result.f.ledger[:5] + result.f.ledger[6:]})
        }
    )
    assert _verdicts(holed, gates_ok)["I11"].passed is False


def test_i12_fails_on_a_receipts_requests_count_mismatch(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "R", 11)
    mutated = _replace_cell(result, cell.model_copy(update={"receipts": cell.receipts[:1]}))
    verdict = _verdicts(mutated, gates_ok)["I12"]
    assert verdict.passed is False
    assert "R T11" in verdict.detail
    hidden = result.model_copy(
        update={"budget": result.budget.model_copy(update={"frontier_calls": 97})}
    )
    assert _verdicts(hidden, gates_ok)["I12"].passed is False
    assert "96" in _verdicts(result, gates_ok)["I12"].detail


def test_i15_fails_when_an_agree_target_is_outside_the_eligible_set(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    cell = _cell(result, "F", 3)
    eligible = cell.eligible_targets
    assert eligible is not None
    a01 = _claim_id(evidence_id(1, "A"))
    assert a01 in eligible.eligible_judgment_ids
    narrowed = eligible.model_copy(
        update={
            "eligible_judgment_ids": tuple(i for i in eligible.eligible_judgment_ids if i != a01)
        }
    )
    mutated = _replace_cell(result, cell.model_copy(update={"eligible_targets": narrowed}))
    verdict = _verdicts(mutated, gates_ok)["I15"]
    assert verdict.passed is False
    assert a01 in verdict.detail


def test_i15_fails_on_an_agree_at_a_non_checkpoint_t(
    completed: tuple[Harness, RunResult],
    gates_ok: tuple[GateResult, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, result = completed
    without_t3 = {t: locus for t, locus in AUTHORITY_CHECKPOINTS.items() if t != 3}
    monkeypatch.setattr(integrity_module, "AUTHORITY_CHECKPOINTS", without_t3)
    verdict = _verdicts(result, gates_ok)["I15"]
    assert verdict.passed is False
    assert "T3" in verdict.detail


def test_i15_fails_when_an_agree_carries_rationale_beyond_the_pending_id(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    (agree, _) = _human_judgments(_cell(result, "F", 3))[:2]
    assert agree.rationale == f"AGREE: {_supersede_id(evidence_id(2, 'A'))}"
    mutated = _mutate_arm_ledgers(
        result,
        "F",
        _rewrite_judgment(
            agree.judgment_id,
            lambda j: j.model_copy(
                update={"rationale": f"{j.rationale} (the proposal looks right)"}
            ),
        ),
    )
    verdict = _verdicts(mutated, gates_ok)["I15"]
    assert verdict.passed is False
    assert agree.judgment_id in verdict.detail
    with_evidence = _mutate_arm_ledgers(
        result,
        "F",
        _rewrite_judgment(
            agree.judgment_id,
            lambda j: j.model_copy(update={"visible_evidence_ids": (evidence_id(3, "A"),)}),
        ),
    )
    assert _verdicts(with_evidence, gates_ok)["I15"].passed is False


def test_i15_derives_agree_evidence_from_the_ledger_not_the_authorization_log(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    """Removing every AGREED ``AuthorizationRecord`` changes no verdict: durable ledger
    events are canonical for the applied AGREEs. (The not-authorized records are the
    only place a withheld proposal is *recorded* as not authorized, so those stay; a
    run stripped of them fails I15 on exactly that clause.)"""
    _, result = completed

    def _without_agreed(records: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(a for a in records if a.outcome is not AuthorizationOutcome.AGREED)

    assert any(
        a.outcome is AuthorizationOutcome.AGREED for c in result.cells for a in c.authorizations
    )
    cells = [
        c.model_copy(update={"authorizations": _without_agreed(c.authorizations)})
        for c in result.cells
    ]
    stripped = _with_cells(result, cells).model_copy(
        update={
            "f": result.f.model_copy(
                update={"authorizations": _without_agreed(result.f.authorizations)}
            ),
            "a": result.a.model_copy(
                update={"authorizations": _without_agreed(result.a.authorizations)}
            ),
        }
    )
    verdicts = _verdicts(stripped, gates_ok)
    assert verdicts["I8"].passed is True
    assert verdicts["I15"].passed is True
    assert f"{result.budget.human_authorizations} applied human AGREE" in verdicts["I15"].detail
    emptied = _with_cells(
        result, [c.model_copy(update={"authorizations": ()}) for c in result.cells]
    )
    verdict = _verdicts(emptied, gates_ok)["I15"]
    assert verdict.passed is False
    assert verdicts["I8"].passed is True
    assert "not authorized" in verdict.detail


def test_i15_verifies_the_pre_t_snapshot_sequence_against_the_ledger_segment(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    """The pre-T property is verified, not trusted: a snapshot whose sequence is not
    the start of that cell's ledger segment (the ledger length before T's ingestion)
    fails I15 even though every AGREE target is inside the recorded set."""
    _, result = completed
    assert _verdicts(result, gates_ok)["I15"].passed is True
    cell = _cell(result, "F", 3)
    eligible = cell.eligible_targets
    assert eligible is not None
    off_by_one = eligible.model_copy(update={"snapshot_sequence": eligible.snapshot_sequence + 1})
    mutated = _replace_cell(result, cell.model_copy(update={"eligible_targets": off_by_one}))
    verdict = _verdicts(mutated, gates_ok)["I15"]
    assert verdict.passed is False
    assert "F T3" in verdict.detail


def test_i15_recomputes_the_eligible_set_from_the_pre_t_ledger_prefix(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    """A recorded eligible set widened by a judgment created only during T (so not in
    the set replayed from the pre-T ledger prefix) fails I15."""
    _, result = completed
    cell = _cell(result, "A", 3)
    eligible = cell.eligible_targets
    assert eligible is not None
    created_during_t = _claim_id(evidence_id(3, "A"))
    assert created_during_t not in eligible.eligible_judgment_ids
    widened = eligible.model_copy(
        update={
            "eligible_judgment_ids": tuple(
                sorted((*eligible.eligible_judgment_ids, created_during_t))
            )
        }
    )
    mutated = _replace_cell(result, cell.model_copy(update={"eligible_targets": widened}))
    verdict = _verdicts(mutated, gates_ok)["I15"]
    assert verdict.passed is False
    assert "A T3" in verdict.detail
    assert created_during_t in verdict.detail


def test_i15_requires_a_not_authorized_record_for_every_non_eligible_pending_supersede(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    """Spec I15: every pending proposal outside ELIGIBLE_T was recorded as not
    authorized. On a COMPLETED checkpoint cell the record must exist; removing it
    fails I15 (the proposal is still never applied, which alone is not enough)."""
    _, result = completed
    cell = _cell(result, "F", 3)
    eligible = cell.eligible_targets
    assert eligible is not None
    b02 = _supersede_id(evidence_id(2, "B"))
    assert b02 in cell.pending_supersede_judgment_ids
    withheld = [a for a in cell.authorizations if b02 in a.pending_judgment_ids]
    assert [a.outcome for a in withheld] == [AuthorizationOutcome.NOT_ELIGIBLE_NOT_AUTHORIZED]
    assert withheld[0].target_judgment_id not in eligible.eligible_judgment_ids
    assert _verdicts(result, gates_ok)["I15"].passed is True
    kept = tuple(a for a in cell.authorizations if b02 not in a.pending_judgment_ids)
    mutated = _replace_cell(result, cell.model_copy(update={"authorizations": kept}))
    verdict = _verdicts(mutated, gates_ok)["I15"]
    assert verdict.passed is False
    assert "F T3" in verdict.detail
    assert b02 in verdict.detail


# --- the 47 -> 48 -> 49 authorization-ceiling boundary (clarification 6) -------------------------


def test_ceiling_abort_47_48_49_is_structurally_valid_evidence(
    gates_ok: tuple[GateResult, ...],
) -> None:
    budget = ExperimentBudget()
    budget.human_authorizations = MAX_HUMAN_AUTHORIZATIONS - 1
    result = Harness(budget=budget).run()
    assert result.status is RunStatus.ABORTED_AUTHORITY_CEILING
    failed = result.cells[_position("F", 3)]
    assert failed.status == "FAILED" and failed.authorizations == ()
    (agree,) = _human_judgments(failed)
    a01, a02, a03 = (evidence_id(t, "A") for t in (1, 2, 3))
    assert agree.rationale == f"AGREE: {_supersede_id(a02)}"
    assert failed.eligible_targets is not None
    assert failed.eligible_targets.eligible_judgment_ids == (_claim_id(a01), _claim_id(a02))

    verdicts = _verdicts(result, gates_ok)
    failing = [(v.id, v.detail) for v in verdicts.values() if v.passed is not True]
    assert failing == []
    # #48 is recognised from the ledger as a legitimate mechanical AGREE ...
    assert "1 applied human AGREE" in verdicts["I15"].detail
    assert "1 applied human AGREE" in verdicts["I8"].detail
    # ... #49 was never written, so its model proposal remains pending and unapplied.
    assert failed.state_snapshot is not None
    admissions = failed.state_snapshot.semantic.admissions
    assert admissions[_supersede_id(a03)].route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert _supersede_id(a03) not in failed.state_snapshot.semantic.applied_judgment_ids
    assert "16" in verdicts["I12"].detail


def test_verdicts_on_a_run_aborted_before_any_authority_are_evaluated_fail_closed(
    gates_ok: tuple[GateResult, ...],
) -> None:
    result = Harness(f_overrides={0: XAIProviderError("stop")}).run()
    assert result.status is RunStatus.ABORTED_PROVIDER
    verdicts = _verdicts(result, gates_ok)
    assert verdicts["I1"].passed is False
    assert all(v.passed is not None for v in verdicts.values())
    assert verdicts["I13"].passed is True and verdicts["I14"].passed is True
    assert verdicts["I15"].passed is True


def test_verdicts_are_the_spec_12_ids_with_their_applicability(
    completed: tuple[Harness, RunResult], gates_ok: tuple[GateResult, ...]
) -> None:
    _, result = completed
    verdicts = integrity_verdicts(result, preflight_gates=gates_ok)
    assert [v.id for v in verdicts] == [f"I{n}" for n in range(1, 16)]
    for verdict in verdicts:
        assert verdict.applies_to == EXPECTED_APPLIES_TO[verdict.id]
        assert verdict.detail
    assert tuple(result.f.roots) == LOCI
