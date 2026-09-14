"""9P3 T7: the preregistration sealer and the live-capable entry point, with their
preflight-before-construction and raw-preservation laws (spec §12, §14, §16, §17, §19;
T7 brief; controller clarifications 1-12).

Every git fact and regression command is an injected fake returning realistic values;
every reasoner is a scripted fake injected through ``reasoner_factory``; every
experiment directory is a throwaway under ``tmp_path`` sealed with the real
``build_manifest``/``write_preregistration``. ``--live`` is never run against a real
provider; no real ``XAI_API_KEY`` is read (the ``PoisonedEnv`` raises on it); no
``XAISemanticReasoner`` is constructed; the real experiment directory is never
created. ZERO live calls; sockets are blocked.

Gate 23 (I13 ⊙, sixteen fresh governors over the cumulative corpora) is evaluated once
for real per module and its result is handed to every other preflight in the module,
exactly as the T5 integrity tests do; the flagship preflight-only test and the fake
live-success run evaluate it for real. Nothing in the scripts under test changes.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import shutil
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import pytest

import scripts.prepare_long_horizon_bounded_memory as prepare_entrypoint
import scripts.run_long_horizon_bounded_memory as entrypoint
from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    POLICY_VERSION,
    SYSTEM_INSTRUCTION,
    XAIProviderError,
)
from foundry.application.semantic_reducer import address_id_for
from foundry.domain.common import Authority, FrozenModel
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.contrastive_unseen.integrity import (
    SCOPE_CLOSURE_REGRESSION_ARGV,
    TRACK_A_REGRESSION_ARGV,
)
from foundry.experiments.long_horizon_bounded import integrity as integrity_module
from foundry.experiments.long_horizon_bounded import runner as runner_module
from foundry.experiments.long_horizon_bounded.artifacts import (
    EXPERIMENT_ARTIFACT_DIR,
    RAW_ARTIFACT_PATHS,
    SPEC_PATH,
    Adjudication,
    AdjudicationRefused,
    build_manifest,
    write_adjudication,
    write_preregistration,
)
from foundry.experiments.long_horizon_bounded.expectations import CHECKPOINTS
from foundry.experiments.long_horizon_bounded.integrity import (
    GATE_NAMES,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PRESERVATION_BASE_SHA,
    PREDECESSOR_RAW_EVIDENCE_SHA,
    PREREGISTRATION_FILES,
)
from foundry.experiments.long_horizon_bounded.protocol import (
    A_POLICY_VERSION,
    ARM_SCHEDULE,
    FR_POLICY_VERSION,
    FROZEN_CORE_SHA,
    GRPC_DNS_RESOLVER_ENV,
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.long_horizon_bounded.runner import (
    ExperimentBudget,
    RunStatus,
    build_arm_reasoners,
)
from foundry.experiments.long_horizon_bounded.timeline import EXPERIMENT_VERSION
from foundry.ports.semantic_reasoner import ReasoningRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 9, 13, tzinfo=UTC)
FR_FINGERPRINT = ReasonerFingerprint(
    provider=PROVIDER, model=MODEL, policy_version=FR_POLICY_VERSION
)
A_FINGERPRINT = ReasonerFingerprint(provider=PROVIDER, model=MODEL, policy_version=A_POLICY_VERSION)
HARNESS_SHA = "a" * 40
SEAL_SHA = "5" * 40
RAW_RUN_SHA = "7" * 40
PREPARE_HEAD_SHA = "c" * 40
SPEC_SHA = "b" * 64
KEY_CANARY = "FAKE-KEY-CANARY-0123456789"
ENV_CANARY = "UNRELATED-ENV-CANARY-9876543210"
SECRET_SHAPED = "xai-abcdef123456"
CORE_PATH = "src/foundry/domain/semantic_judgment.py"
PACKAGE_DIR = "src/foundry/experiments/long_horizon_bounded/"
TREE_HASHES: dict[str, str] = {
    directory: hashlib.sha1(directory.encode("utf-8")).hexdigest()  # noqa: S324 - fake tree id
    for directory in HISTORICAL_ARTIFACT_DIRS
}
HARNESS_CHANGES = (
    f"{PACKAGE_DIR}__init__.py",
    f"{PACKAGE_DIR}timeline.py",
    f"{PACKAGE_DIR}protocol.py",
    f"{PACKAGE_DIR}runner.py",
    f"{PACKAGE_DIR}integrity.py",
    f"{PACKAGE_DIR}artifacts.py",
    "scripts/prepare_long_horizon_bounded_memory.py",
    "scripts/run_long_horizon_bounded_memory.py",
    "tests/unit/test_long_horizon_bounded_runner.py",
    "tests/integration/test_long_horizon_bounded_entrypoint.py",
    "docs/superpowers/plans/2026-09-13-9p3-long-horizon-bounded-memory.md",
    SPEC_PATH,
    *PREREGISTRATION_FILES,
)
"""What changed between the frozen core and the 9P3 seal: nothing under a core prefix."""
CHANGES_SINCE_PREDECESSOR = (
    f"{PACKAGE_DIR}timeline.py",
    f"{PACKAGE_DIR}runner.py",
    "scripts/run_long_horizon_bounded_memory.py",
    "tests/integration/test_long_horizon_bounded_entrypoint.py",
    *PREREGISTRATION_FILES,
)
"""What changed since the 9P2 v3 raw-evidence commit: nothing under the predecessor dir."""
CHECKPOINT_IDS = tuple(checkpoint.id for checkpoint in CHECKPOINTS)
TRACKED_LOCI: frozenset[str] = frozenset({"A", "B"})
"""Loci the script keeps acting on after T1 (the T4 idiom: small ledgers, 48 cells)."""
POSITION_20 = 20
assert ARM_SCHEDULE[POSITION_20] == (7, "R")
R_CALLS_BEFORE_POSITION_20 = sum(1 for t, arm in ARM_SCHEDULE[:POSITION_20] if arm == "R") * 2


def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sockets(monkeypatch)


REAL_R_CONTEXT = integrity_module.r_context_within_bounds


@pytest.fixture(scope="module")
def r_context_real() -> tuple[bool, str]:
    """Gate 23 evaluated once for real (several seconds)."""
    return REAL_R_CONTEXT()


def _cache_r_context(monkeypatch: pytest.MonkeyPatch, result: tuple[bool, str]) -> None:
    monkeypatch.setattr(integrity_module, "r_context_within_bounds", lambda: result)


@pytest.fixture(autouse=True)
def _cached_r_context(monkeypatch: pytest.MonkeyPatch, r_context_real: tuple[bool, str]) -> None:
    """Every preflight in this module consumes the one cached real gate-23 result unless
    a test restores ``REAL_R_CONTEXT`` explicitly. Test speed only."""
    _cache_r_context(monkeypatch, r_context_real)


def _use_real_r_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integrity_module, "r_context_within_bounds", REAL_R_CONTEXT)


# --- injected git / command fakes (realistic values, never hard-coded success) --------


class FakeGit:
    """Every ``GitCliLike`` method, scripted: the seal's single parent is the harness
    sha, the seal adds exactly the two preregistration paths, the three frozen shas are
    ancestors, the six historical trees are equal at base and seal, nothing under the
    predecessor directory changed, and ``show_bytes`` is keyed for adjudication."""

    def __init__(
        self,
        *,
        head: str = SEAL_SHA,
        dirty: str = "",
        parents: dict[str, tuple[str, ...]] | None = None,
        ancestors: frozenset[tuple[str, str]] | None = None,
        changed: dict[tuple[str, str], tuple[str, ...]] | None = None,
        trees: dict[tuple[str, str], str] | None = None,
        show: dict[tuple[str, str], bytes] | None = None,
    ) -> None:
        self._head = head
        self._dirty = dirty
        self._parents = parents if parents is not None else {SEAL_SHA: (HARNESS_SHA,)}
        self._ancestors = (
            ancestors
            if ancestors is not None
            else frozenset(
                {
                    (FROZEN_CORE_SHA, SEAL_SHA),
                    (PREDECESSOR_RAW_EVIDENCE_SHA, SEAL_SHA),
                    (HISTORICAL_PRESERVATION_BASE_SHA, SEAL_SHA),
                }
            )
        )
        self._changed = (
            changed
            if changed is not None
            else {
                (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
                (FROZEN_CORE_SHA, SEAL_SHA): HARNESS_CHANGES,
                (PREDECESSOR_RAW_EVIDENCE_SHA, SEAL_SHA): CHANGES_SINCE_PREDECESSOR,
            }
        )
        self._trees = trees if trees is not None else _equal_trees()
        self._show = show if show is not None else {}
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
        return self._show[(sha, path)]

    def tree_sha(self, sha: str, path: str) -> str:
        self.calls.append(("tree_sha", sha, path))
        return self._trees[(sha, path)]


def _equal_trees(*, differing: str | None = None) -> dict[tuple[str, str], str]:
    """Tree ids equal at the preservation base and at the seal for all six frozen
    directories; ``differing`` names one directory whose tree changed at the seal."""
    trees: dict[tuple[str, str], str] = {}
    for directory, tree in TREE_HASHES.items():
        trees[(HISTORICAL_PRESERVATION_BASE_SHA, directory)] = tree
        trees[(SEAL_SHA, directory)] = tree if directory != differing else "e" * 40
    return trees


class FakeCommands:
    def __init__(self, exit_codes: dict[tuple[str, ...], int] | None = None) -> None:
        self._exit_codes = exit_codes or {}
        self.argvs: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> tuple[int, str]:
        self.argvs.append(argv)
        code = self._exit_codes.get(argv, 0)
        return code, f"fake output for {' '.join(argv)} (exit {code})"


class FakePrepareGit:
    """The prepare script's injectable git runner: keyed by the exact argv tuple, it
    refuses any other argv (an ``AssertionError`` that escapes ``main``), records the
    order it was asked in, and -- given ``out`` -- proves no preregistration file existed
    yet when it was asked (every git operation precedes any write)."""

    def __init__(
        self, table: dict[tuple[str, ...], tuple[int, bytes, bytes]], *, out: Path | None = None
    ) -> None:
        self._table = table
        self._out = out
        self.argvs: list[tuple[str, ...]] = []
        self.answers: dict[tuple[str, ...], bytes] = {}

    def run(self, argv: tuple[str, ...]) -> tuple[int, bytes, bytes]:
        self.argvs.append(argv)
        if self._out is not None:
            written = [
                name
                for name in ("manifest.json", "expectations.json")
                if (self._out / name).exists()
            ]
            assert not written, f"git {argv} asked after {written} were written"
        if argv not in self._table:
            raise AssertionError(f"prepare ran a git operation outside its allowed set: {argv}")
        code, stdout, stderr = self._table[argv]
        self.answers[argv] = stdout
        return code, stdout, stderr


def _spec_bytes() -> bytes:
    return (REPO_ROOT / SPEC_PATH).read_bytes()


def _prepare_argvs() -> list[tuple[str, ...]]:
    """The allowed prepare git operations, in the brief's order."""
    argvs: list[tuple[str, ...]] = [
        ("status", "--porcelain"),
        ("rev-parse", "HEAD"),
        ("merge-base", "--is-ancestor", FROZEN_CORE_SHA, "HEAD"),
        ("merge-base", "--is-ancestor", PREDECESSOR_RAW_EVIDENCE_SHA, "HEAD"),
        ("merge-base", "--is-ancestor", HISTORICAL_PRESERVATION_BASE_SHA, "HEAD"),
        ("show", f"HEAD:{SPEC_PATH}"),
    ]
    for directory in HISTORICAL_ARTIFACT_DIRS:
        argvs.append(("rev-parse", f"{HISTORICAL_PRESERVATION_BASE_SHA}:{directory}"))
        argvs.append(("rev-parse", f"HEAD:{directory}"))
    return argvs


def _prepare_table(
    *,
    dirty: str = "",
    head: str = PREPARE_HEAD_SHA,
    not_ancestors: frozenset[str] = frozenset(),
    committed_spec: bytes | None = None,
    head_trees: dict[str, str] | None = None,
) -> dict[tuple[str, ...], tuple[int, bytes, bytes]]:
    ok = (0, b"", b"")
    table: dict[tuple[str, ...], tuple[int, bytes, bytes]] = {
        ("status", "--porcelain"): (0, dirty.encode("utf-8"), b""),
        ("rev-parse", "HEAD"): (0, f"{head}\n".encode(), b""),
        ("show", f"HEAD:{SPEC_PATH}"): (
            0,
            committed_spec if committed_spec is not None else _spec_bytes(),
            b"",
        ),
    }
    for sha in (FROZEN_CORE_SHA, PREDECESSOR_RAW_EVIDENCE_SHA, HISTORICAL_PRESERVATION_BASE_SHA):
        table[("merge-base", "--is-ancestor", sha, "HEAD")] = (
            (1, b"", b"") if sha in not_ancestors else ok
        )
    at_head = head_trees or {}
    for directory, tree in TREE_HASHES.items():
        table[("rev-parse", f"{HISTORICAL_PRESERVATION_BASE_SHA}:{directory}")] = (
            0,
            f"{tree}\n".encode(),
            b"",
        )
        table[("rev-parse", f"HEAD:{directory}")] = (
            0,
            f"{at_head.get(directory, tree)}\n".encode(),
            b"",
        )
    return table


# --- environment fakes ---------------------------------------------------------------


class PoisonedEnv(dict[str, str]):
    """Any read other than ``GRPC_DNS_RESOLVER`` is a violation: the key must not be
    touched on this path. The resolver read is the one preregistered, non-secret read
    made before the gates; it answers ``resolver`` (``None`` = unset)."""

    def __init__(self, resolver: str | None = "native") -> None:
        super().__init__()
        self._resolver = resolver
        self.reads: list[str] = []

    def _answer(self, key: str) -> Any:
        if key == GRPC_DNS_RESOLVER_ENV:
            self.reads.append(key)
            return self._resolver
        raise AssertionError(f"environment read of {key!r} is forbidden on this path")

    def __getitem__(self, key: str) -> str:
        value = self._answer(key)
        if value is None:
            raise KeyError(key)
        return str(value)

    def get(self, key: str, default: Any = None) -> Any:
        value = self._answer(key)
        return default if value is None else value

    def __contains__(self, key: object) -> bool:
        raise AssertionError(f"environment probe of {key!r} is forbidden on this path")


class RecordingEnv(dict[str, str]):
    """Records which names were read so a test can prove the key was read only once."""

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        self.reads.append(key)
        return super().get(key, default)


# --- scripted fake reasoners (the T4 idiom, carrying adapter-shaped identity) ----------


class FakeReceipt(FrozenModel):
    invocation_id: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    wall_clock_ms: int


def _locus(item_id: str) -> str:
    return item_id.removeprefix("EV-O-")[0]


def _create_id(item_id: str) -> str:
    return f"J-create-{item_id}"


def _bind_id(item_id: str) -> str:
    return f"J-bind-{item_id}"


def _claim_id(item_id: str) -> str:
    return f"J-claim-{item_id}"


def _supersede_id(item_id: str) -> str:
    return f"J-supersede-{item_id}"


class LifecycleScript:
    """Structurally valid judgments derived only from the request shown to it (the T4
    runner-test script: acts on the latest T1 items and on two tracked loci)."""

    def __init__(self, fingerprint: ReasonerFingerprint) -> None:
        self._fingerprint = fingerprint
        self._address_of: dict[tuple[str, str], str] = {}

    def __call__(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            return self._call_one(request)
        return self._call_two(request)

    def _acted(self, request: ReasoningRequest) -> tuple[EvidenceItem, ...]:
        superseded = {item.supersedes_evidence_id for item in request.evidence}
        return tuple(
            item
            for item in request.evidence
            if item.evidence_id not in superseded
            and (item.supersedes_evidence_id is None or _locus(item.evidence_id) in TRACKED_LOCI)
        )

    def _judgment(
        self, request: ReasoningRequest, judgment_id: str, proposal: JudgmentProposal
    ) -> SemanticJudgment:
        return SemanticJudgment(
            judgment_id=judgment_id,
            project_id=request.project_id,
            proposal=proposal,
            visible_evidence_ids=tuple(item.evidence_id for item in request.evidence),
            rationale=f"Opaque rationale for {judgment_id}.",
            reasoner=self._fingerprint,
            invocation_id=f"INV-{judgment_id}",
            proposed_at=T0,
        )

    def _call_one(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        known = {address.address_id for address in request.known_addresses}
        judgments: list[SemanticJudgment] = []
        for item in self._acted(request):
            candidate = SemanticCandidate(
                candidate_id=f"CAND-{item.evidence_id}",
                subject=f"subject {item.evidence_id}",
                facet="lifecycle",
                scope=item.scope,
                evidence_ids=(item.evidence_id,),
            )
            predecessor = item.supersedes_evidence_id
            prior = (
                self._address_of.get((request.project_id, predecessor))
                if predecessor is not None
                else None
            )
            if prior is not None and prior in known:
                judgment_id = _bind_id(item.evidence_id)
                proposal: JudgmentProposal = BindToAddressProposal(
                    candidate=candidate, address_id=prior
                )
                address_id = prior
            else:
                judgment_id = _create_id(item.evidence_id)
                proposal = CreateAddressProposal(candidate=candidate)
                address_id = address_id_for(request.project_id, judgment_id)
            self._address_of[(request.project_id, item.evidence_id)] = address_id
            judgments.append(self._judgment(request, judgment_id, proposal))
        return tuple(judgments)

    def _call_two(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        known_creators = {claim.created_by_judgment_id for claim in request.known_claims}
        judgments: list[SemanticJudgment] = []
        for item in self._acted(request):
            address_id = self._address_of[(request.project_id, item.evidence_id)]
            judgments.append(
                self._judgment(
                    request,
                    _claim_id(item.evidence_id),
                    AssertClaimProposal(
                        address_id=address_id,
                        predicate="policy_value",
                        value=ClaimValue(
                            kind=ClaimValueKind.TEXT, text=f"value {item.evidence_id}"
                        ),
                        evidence_ids=(item.evidence_id,),
                        authority=Authority.OBSERVED,
                    ),
                )
            )
            predecessor = item.supersedes_evidence_id
            if predecessor is not None and _claim_id(predecessor) in known_creators:
                judgments.append(
                    self._judgment(
                        request,
                        _supersede_id(item.evidence_id),
                        SupersedeProposal(
                            target_judgment_id=_claim_id(predecessor),
                            reason="Opaque supersession reason.",
                        ),
                    )
                )
        return tuple(judgments)


def _fingerprint_for(label: str) -> ReasonerFingerprint:
    return A_FINGERPRINT if label == "A" else FR_FINGERPRINT


class ScriptedReasoner:
    """Runs ``LifecycleScript`` per forwarded call unless a failure is scripted for that
    call; ``hooks`` run after the call is forwarded (so a test can drift the identity
    mid-run). Counts every forwarded request; appends one receipt per forwarded call."""

    reasoning_effort = REASONING_EFFORT

    def __init__(
        self,
        *,
        label: str,
        failures: dict[int, BaseException] | None = None,
        fingerprint: ReasonerFingerprint | None = None,
        hooks: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self._fingerprint = fingerprint if fingerprint is not None else _fingerprint_for(label)
        self._script = LifecycleScript(self._fingerprint)
        self._failures = failures or {}
        self._hooks = hooks or {}
        self._label = label
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[FakeReceipt] = []
        self._drafts: list[str] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    @property
    def receipts(self) -> tuple[FakeReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[str, ...]:
        return tuple(self._drafts)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        hook = self._hooks.get(index)
        if hook is not None:
            hook()
        failure = self._failures.get(index)
        if failure is not None:
            raise failure
        self._receipts.append(
            FakeReceipt(
                invocation_id=f"{self._label}-{index + 1}",
                cost_usd=0.01,
                input_tokens=100 + index,
                output_tokens=10 + index,
                wall_clock_ms=5,
            )
        )
        self._drafts.append(f"draft:{self._label}:{index + 1}")
        return self._script(request)


class ContrastiveFake(ScriptedReasoner):
    """A fake carrying the contrastive adapter's class-level identity (F and R)."""

    policy_version = CONTRASTIVE_POLICY_VERSION
    system_instruction = CONTRASTIVE_SYSTEM_INSTRUCTION
    include_comparison_context = True


class HistoricalFake(ScriptedReasoner):
    """A fake carrying the historical adapter's class-level identity (A)."""

    policy_version = POLICY_VERSION
    system_instruction = SYSTEM_INSTRUCTION
    include_comparison_context = False


class FakeFactory:
    """Builds the three scripted arms; records every api_key it was handed (never
    printed) and how many times it was called."""

    def __init__(
        self,
        *,
        f_failures: dict[int, BaseException] | None = None,
        a_failures: dict[int, BaseException] | None = None,
        r_failures: dict[int, BaseException] | None = None,
        fingerprints: dict[str, ReasonerFingerprint] | None = None,
        f_type: type[ScriptedReasoner] = ContrastiveFake,
        a_type: type[ScriptedReasoner] = HistoricalFake,
        r_type: type[ScriptedReasoner] = ContrastiveFake,
        f_hooks: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self.calls: list[str] = []
        overrides = fingerprints or {}
        self.f = f_type(
            label="F", failures=f_failures, fingerprint=overrides.get("F"), hooks=f_hooks
        )
        self.a = a_type(label="A", failures=a_failures, fingerprint=overrides.get("A"))
        self.r = r_type(label="R", failures=r_failures, fingerprint=overrides.get("R"))

    def __call__(
        self, *, api_key: str
    ) -> tuple[ScriptedReasoner, ScriptedReasoner, ScriptedReasoner]:
        self.calls.append(api_key)
        return self.f, self.a, self.r

    @property
    def total_requests(self) -> int:
        """Every request actually forwarded to a fake (the guard refuses before this)."""
        return len(self.f.requests) + len(self.a.requests) + len(self.r.requests)


def _poisoned_factory(*, api_key: str) -> tuple[Any, Any, Any]:
    raise AssertionError("reasoner_factory must not be called on this path")


def _raising_factory(*, api_key: str) -> tuple[Any, Any, Any]:
    raise RuntimeError("client bootstrap failed")


def _live_env(**overrides: str) -> dict[str, str]:
    return {GRPC_DNS_RESOLVER_ENV: "native", "XAI_API_KEY": KEY_CANARY, **overrides}


# --- fixtures and helpers -------------------------------------------------------------


def _seal(out: Path) -> Path:
    out.mkdir(parents=True)
    write_preregistration(
        out,
        build_manifest(
            harness_code_sha=HARNESS_SHA,
            spec_sha256=SPEC_SHA,
            historical_tree_hashes=dict(TREE_HASHES),
        ),
    )
    return out


@pytest.fixture
def sealed(tmp_path: Path) -> Path:
    return _seal(tmp_path / "experiment")


def _seal_bytes(out: Path) -> dict[str, bytes]:
    return {name: (out / name).read_bytes() for name in ("manifest.json", "expectations.json")}


def _dir_snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _relative_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _main(
    mode: str,
    out: Path,
    *,
    frozen_sha: str = SEAL_SHA,
    cwd: Path = REPO_ROOT,
    env: Any = None,
    factory: Callable[..., Any] = _poisoned_factory,
    git: FakeGit | None = None,
    commands: FakeCommands | None = None,
) -> int:
    return entrypoint.main(
        [mode, "--frozen-sha", frozen_sha, "--out", str(out)],
        cwd=cwd,
        env=PoisonedEnv() if env is None else env,
        reasoner_factory=factory,
        git=git if git is not None else FakeGit(),
        commands=commands if commands is not None else FakeCommands(),
    )


def _gate_table(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {gate["name"]: gate for gate in document["gates"]}


def _failed_gates(document: dict[str, Any]) -> list[str]:
    return [gate["name"] for gate in document["gates"] if not gate["passed"]]


def _request_paths() -> tuple[str, ...]:
    return (
        "F/requests.json",
        "A/requests.json",
        *(f"R/T{t:02d}/requests.json" for t in range(1, 17)),
    )


def _request_count(out: Path) -> int:
    return sum(len(_read_json(out / path)["entries"]) for path in _request_paths())


def _all_artifact_text(out: Path) -> Iterator[tuple[str, str]]:
    for path in RAW_ARTIFACT_PATHS:
        file = out / path
        if file.exists():
            yield path, file.read_text(encoding="utf-8")


FULL_TREE: set[str] = {"manifest.json", "expectations.json", *RAW_ARTIFACT_PATHS}
"""The two seal files plus the 116 raw artifact paths (118 files)."""


def _statuses(out: Path, arm: str) -> list[str]:
    return [step["status"] for step in _read_json(out / f"{arm}/result.json")["steps"]]


def _r_statuses(out: Path) -> list[str]:
    return [_read_json(out / f"R/T{t:02d}/result.json")["status"] for t in range(1, 17)]


class LiveRun(NamedTuple):
    out: Path
    code: int
    factory: FakeFactory
    env: RecordingEnv
    git: FakeGit
    stdout: str
    seal_before: dict[str, bytes]


@pytest.fixture(scope="module")
def live_success(
    tmp_path_factory: pytest.TempPathFactory, r_context_real: tuple[bool, str]
) -> LiveRun:
    """One fake ``--live`` success (96 forwarded calls, gate 23 evaluated for real),
    shared read-only by the tests that inspect its tree."""
    out = _seal(tmp_path_factory.mktemp("live-success") / EXPERIMENT_ARTIFACT_DIR)
    seal_before = _seal_bytes(out)
    factory = FakeFactory()
    env = RecordingEnv(_live_env(UNRELATED=ENV_CANARY))
    git = FakeGit()
    buffer = io.StringIO()
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        _use_real_r_context(monkeypatch)
        with contextlib.redirect_stdout(buffer):
            code = _main("--live", out, env=env, factory=factory, git=git)
    return LiveRun(out, code, factory, env, git, buffer.getvalue(), seal_before)


def _copy_tree(source: Path, tmp_path: Path) -> Path:
    """A private copy of a raw tree at the real experiment path under ``tmp_path``."""
    destination = tmp_path / EXPERIMENT_ARTIFACT_DIR
    shutil.copytree(source, destination)
    return destination


def _committed(
    out_dir: Path, repo_root: Path, sha: str = RAW_RUN_SHA, *, dirty: str = ""
) -> FakeGit:
    """A fake raw-run commit: HEAD is ``sha``, every raw path shows its on-disk bytes."""
    show = {
        (sha, (out_dir / name).relative_to(repo_root).as_posix()): (out_dir / name).read_bytes()
        for name in RAW_ARTIFACT_PATHS
    }
    return FakeGit(head=sha, dirty=dirty, show=show)


def _adjudication() -> Adjudication:
    return Adjudication(
        checkpoints={arm: dict.fromkeys(CHECKPOINT_IDS, True) for arm in ("F", "A", "R")},
        control_errors={"F": 0, "A": 0, "R": 0},
        material_errors={"F": 0, "A": 0, "R": 0},
        notes="scripted adjudication over the fake live run",
    )


# =====================================================================================
# prepare (matrix 1-9)
# =====================================================================================


def _prepare(out: Path, git: FakePrepareGit, *, cwd: Path = REPO_ROOT) -> int:
    return prepare_entrypoint.main(["--out", str(out)], cwd=cwd, git=git)


def test_prepare_seals_exactly_two_files_using_only_the_allowed_git_operations_in_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 1: success -- the allowed git argv, in the brief's order, all before any
    write; exactly the two files; both canonical hashes printed; exit 0."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(), out=out)

    code = _prepare(out, git)

    assert code == 0
    assert git.argvs == _prepare_argvs()
    assert _relative_files(out) == {"manifest.json", "expectations.json"}
    printed = dict(line.split(" ", 1) for line in capsys.readouterr().out.strip().splitlines())
    assert set(printed) == {"manifest.json", "expectations.json"}
    for name, digest in printed.items():
        assert digest == canonical_sha256(_read_json(out / name))
    manifest = _read_json(out / "manifest.json")
    assert manifest["harness_code_sha"] == PREPARE_HEAD_SHA
    assert manifest["spec_sha256"] == hashlib.sha256(_spec_bytes()).hexdigest()
    assert manifest["experiment_version"] == EXPERIMENT_VERSION
    assert manifest["historical_preservation_base_sha"] == HISTORICAL_PRESERVATION_BASE_SHA


def test_prepare_refuses_a_dirty_worktree_before_anything_else(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 2."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(dirty=" M src/foundry/x.py\n"), out=out)

    code = _prepare(out, git)

    assert code == 2
    assert git.argvs == [("status", "--porcelain")]
    assert not out.exists()
    assert "REFUSED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "missing_ancestor",
    [FROZEN_CORE_SHA, PREDECESSOR_RAW_EVIDENCE_SHA, HISTORICAL_PRESERVATION_BASE_SHA],
)
def test_prepare_refuses_when_a_frozen_sha_is_not_an_ancestor_of_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing_ancestor: str
) -> None:
    """Matrix 3-5: frozen core, predecessor raw evidence, historical preservation base."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(not_ancestors=frozenset({missing_ancestor})), out=out)

    code = _prepare(out, git)

    assert code == 2
    assert not out.exists()
    assert ("merge-base", "--is-ancestor", missing_ancestor, "HEAD") == git.argvs[-1]
    output = capsys.readouterr().out
    assert "REFUSED" in output and missing_ancestor in output


def test_prepare_refuses_when_working_tree_spec_differs_from_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 6: the sealed spec hash is the working-tree bytes, which must equal HEAD."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(committed_spec=_spec_bytes() + b"\n# drift\n"), out=out)

    code = _prepare(out, git)

    assert code == 2
    assert not out.exists()
    assert git.argvs[-1] == ("show", f"HEAD:{SPEC_PATH}")
    assert "spec" in capsys.readouterr().out


def test_prepare_refuses_when_the_spec_is_missing_from_the_working_tree(tmp_path: Path) -> None:
    """Matrix 6 (variant): nothing is fabricated for an absent spec."""
    elsewhere = tmp_path / "not-the-repo"
    elsewhere.mkdir()
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(), out=out)

    assert _prepare(out, git, cwd=elsewhere) == 2
    assert not out.exists()


def test_prepare_refuses_when_a_historical_tree_differs_at_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 7: HEAD's tree must equal the baseline tree for every frozen directory;
    the baseline is never taken from HEAD."""
    touched = HISTORICAL_ARTIFACT_DIRS[3]
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(head_trees={touched: "d" * 40}), out=out)

    code = _prepare(out, git)

    assert code == 2
    assert not out.exists()
    assert git.argvs[-1] == ("rev-parse", f"HEAD:{touched}")
    output = capsys.readouterr().out
    assert "REFUSED" in output and touched in output


@pytest.mark.parametrize("existing", ["manifest.json", "expectations.json"])
def test_prepare_refuses_when_either_preregistration_file_exists(
    tmp_path: Path, existing: str
) -> None:
    """Matrix 8: nothing written, the existing file untouched."""
    out = tmp_path / "experiment"
    out.mkdir()
    (out / existing).write_text("{}\n", encoding="utf-8")
    git = FakePrepareGit(_prepare_table())

    code = _prepare(out, git)

    assert code == 2
    assert _relative_files(out) == {existing}
    assert (out / existing).read_text(encoding="utf-8") == "{}\n"


def test_prepare_records_the_baseline_tree_values_never_heads(tmp_path: Path) -> None:
    """Matrix 9: every sealed tree hash is the value the BASE lookup produced, and both
    the BASE and the HEAD lookup were made for every frozen directory."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(), out=out)

    assert _prepare(out, git) == 0

    sealed = _read_json(out / "manifest.json")["historical_artifact_tree_hashes"]
    assert set(sealed) == set(HISTORICAL_ARTIFACT_DIRS)
    for directory in HISTORICAL_ARTIFACT_DIRS:
        base_argv = ("rev-parse", f"{HISTORICAL_PRESERVATION_BASE_SHA}:{directory}")
        head_argv = ("rev-parse", f"HEAD:{directory}")
        assert base_argv in git.argvs and head_argv in git.argvs
        assert sealed[directory] == git.answers[base_argv].decode("utf-8").strip()
        assert sealed[directory] == TREE_HASHES[directory]
    assert _read_json(out / "manifest.json")["historical_artifact_dirs"] == list(
        HISTORICAL_ARTIFACT_DIRS
    )


def test_prepare_defaults_to_the_real_experiment_directory_but_is_never_run_against_it() -> None:
    parser = prepare_entrypoint.build_parser()
    assert parser.parse_args([]).out == EXPERIMENT_ARTIFACT_DIR.rstrip("/")
    assert not (REPO_ROOT / EXPERIMENT_ARTIFACT_DIR).exists()


# =====================================================================================
# preflight-only (matrix 10-20)
# =====================================================================================


def test_preflight_only_passes_all_23_gates_writes_nothing_and_constructs_nothing(
    sealed: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix 10: gate 23 for real; poisoned env answers only the resolver; poisoned
    factory; 23 gates; ``frontier_calls`` 0; the observed resolver verbatim."""
    _use_real_r_context(monkeypatch)
    before = _dir_snapshot(sealed)
    env = PoisonedEnv(resolver="native")
    git = FakeGit()
    commands = FakeCommands()

    code = _main("--preflight-only", sealed, env=env, git=git, commands=commands)

    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["all_passed"] is True
    assert document["frozen_sha"] == SEAL_SHA
    assert tuple(gate["name"] for gate in document["gates"]) == GATE_NAMES
    assert len(document["gates"]) == 23
    assert all(gate["passed"] for gate in document["gates"]), _failed_gates(document)
    assert document["leakage"]["passed"] is True
    assert document["run_status"] is None
    assert document["frontier_calls"] == 0
    assert document["observed_grpc_dns_resolver"] == "native"
    assert document["experiment_version"] == EXPERIMENT_VERSION
    assert set(document) == {
        "artifact_format_version",
        "experiment_version",
        "frozen_sha",
        "all_passed",
        "run_status",
        "frontier_calls",
        "gates",
        "leakage",
        "observed_grpc_dns_resolver",
    }
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _dir_snapshot(sealed) == before
    assert ("head",) in git.calls and ("dirty",) in git.calls
    assert ("is_ancestor", HISTORICAL_PRESERVATION_BASE_SHA, SEAL_SHA) in git.calls
    assert ("is_ancestor", PREDECESSOR_RAW_EVIDENCE_SHA, SEAL_SHA) in git.calls
    assert TRACK_A_REGRESSION_ARGV in commands.argvs
    assert SCOPE_CLOSURE_REGRESSION_ARGV in commands.argvs
    gates = _gate_table(document)
    assert "T16=" in gates["r_cumulative_context_within_bounds"]["detail"]


def test_preflight_only_exits_3_on_dirty_tree_and_still_prints_the_document(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 11."""
    before = _dir_snapshot(sealed)

    code = _main("--preflight-only", sealed, git=FakeGit(dirty=" M src/foundry/x.py"))

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    assert document["all_passed"] is False
    assert document["run_status"] == "ABORTED_PREFLIGHT"
    assert document["frontier_calls"] == 0
    gates = _gate_table(document)
    assert gates["worktree_clean"]["passed"] is False
    assert "src/foundry/x.py" in gates["worktree_clean"]["detail"]
    assert _dir_snapshot(sealed) == before


def test_preflight_only_refuses_without_seal_files_or_with_an_unparsable_manifest(
    tmp_path: Path, sealed: Path
) -> None:
    """Matrix 12."""
    out = tmp_path / "unsealed"
    out.mkdir()
    assert _main("--preflight-only", out) == 2
    assert _relative_files(out) == set()

    (sealed / "manifest.json").write_bytes(b"{not json")
    before = _dir_snapshot(sealed)
    assert _main("--preflight-only", sealed) == 2
    assert _dir_snapshot(sealed) == before


def test_gates_use_injected_git_results_not_hard_coded_success(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 13."""
    git = FakeGit(
        parents={SEAL_SHA: ("c" * 40,)},
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (FROZEN_CORE_SHA, SEAL_SHA): (*HARNESS_CHANGES, CORE_PATH),
            (PREDECESSOR_RAW_EVIDENCE_SHA, SEAL_SHA): CHANGES_SINCE_PREDECESSOR,
        },
    )

    code = _main("--preflight-only", sealed, git=git)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["head_equals_final_seal"]["passed"] is False
    assert HARNESS_SHA in gates["head_equals_final_seal"]["detail"]
    assert gates["core_paths_unchanged_since_frozen_core"]["passed"] is False
    assert CORE_PATH in gates["core_paths_unchanged_since_frozen_core"]["detail"]
    assert gates["worktree_clean"]["passed"] is True
    assert gates["predecessor_raw_evidence_unchanged"]["passed"] is True
    assert ("changed_paths", FROZEN_CORE_SHA, SEAL_SHA) in git.calls


def test_failing_regression_command_fails_its_gate(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 14."""
    commands = FakeCommands({TRACK_A_REGRESSION_ARGV: 1})

    code = _main("--preflight-only", sealed, commands=commands)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["track_a_regression_passes"]["passed"] is False
    assert gates["scope_closure_regression_passes"]["passed"] is True


def test_tampered_manifest_prompt_hash_fails_gate_6_from_real_bytes(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 15."""
    manifest = _read_json(sealed / "manifest.json")
    manifest["fr_prompt_sha256"] = "0" * 64
    (sealed / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    code = _main("--preflight-only", sealed)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["fr_prompt_hash_frozen"]["passed"] is False
    assert "0" * 64 in gates["fr_prompt_hash_frozen"]["detail"]
    assert gates["a_prompt_hash_frozen"]["passed"] is True


def test_missing_request_path_file_fails_gate_16_without_fabrication(
    sealed: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matrix 16: the six request-path sources are read from the package directory; a
    missing one is passed as missing (never fabricated) so gate 16 fails on its own."""
    elsewhere = tmp_path / "not-the-package"
    elsewhere.mkdir()
    monkeypatch.setattr(entrypoint, "REQUEST_PATH_DIR", elsewhere)

    code = _main("--preflight-only", sealed)

    assert code == 3
    gates = _gate_table(json.loads(capsys.readouterr().out))
    assert gates["answer_key_not_imported_by_request_path"]["passed"] is False
    assert "missing" in gates["answer_key_not_imported_by_request_path"]["detail"]
    assert "runner.py" in gates["answer_key_not_imported_by_request_path"]["detail"]


def test_request_path_sources_are_the_real_six_package_files() -> None:
    package = REPO_ROOT / PACKAGE_DIR
    assert Path(entrypoint.REQUEST_PATH_DIR).resolve() == package.resolve()
    sources = entrypoint._request_path_sources()
    assert set(sources) == set(entrypoint.REQUEST_PATH_MODULES)
    for name, text in sources.items():
        assert text == (package / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("resolver", [None, "", "ares", "Native"])
def test_preflight_only_fails_only_gate_21_when_the_resolver_is_not_native(
    sealed: Path, capsys: pytest.CaptureFixture[str], resolver: str | None
) -> None:
    """Matrix 17."""
    before = _dir_snapshot(sealed)
    env = PoisonedEnv(resolver=resolver)

    code = _main("--preflight-only", sealed, env=env)

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    gates = _gate_table(document)
    assert gates["grpc_dns_resolver_is_native"]["passed"] is False
    assert repr(resolver) in gates["grpc_dns_resolver_is_native"]["detail"]
    assert _failed_gates(document) == ["grpc_dns_resolver_is_native"]
    assert document["observed_grpc_dns_resolver"] == resolver
    assert document["run_status"] == "ABORTED_PREFLIGHT"
    assert document["frontier_calls"] == 0
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _dir_snapshot(sealed) == before


def test_one_historical_tree_differing_at_the_seal_fails_only_gate_20(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 18: the FakeGit variant where a single frozen directory's tree differs
    at the seal; only ``historical_artifacts_unchanged`` fails."""
    touched = HISTORICAL_ARTIFACT_DIRS[4]
    git = FakeGit(trees=_equal_trees(differing=touched))

    code = _main("--preflight-only", sealed, git=git)

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    gates = _gate_table(document)
    assert _failed_gates(document) == ["historical_artifacts_unchanged"]
    assert touched in gates["historical_artifacts_unchanged"]["detail"]
    assert ("tree_sha", HISTORICAL_PRESERVATION_BASE_SHA, touched) in git.calls
    assert ("tree_sha", SEAL_SHA, touched) in git.calls


@pytest.mark.parametrize("bad_sha", ["abc", "A" * 40, "g" * 40, "5" * 39, "5" * 41])
def test_frozen_sha_must_be_forty_lowercase_hex(sealed: Path, bad_sha: str) -> None:
    """Matrix 19."""
    code = _main("--preflight-only", sealed, frozen_sha=bad_sha)

    assert code == 2
    assert _relative_files(sealed) == {"manifest.json", "expectations.json"}


def test_modes_are_mutually_exclusive_and_required(sealed: Path) -> None:
    """Matrix 19 (variant)."""
    argv_common = ["--frozen-sha", SEAL_SHA, "--out", str(sealed)]
    kwargs: dict[str, Any] = {
        "cwd": REPO_ROOT,
        "env": PoisonedEnv(),
        "reasoner_factory": _poisoned_factory,
        "git": FakeGit(),
        "commands": FakeCommands(),
    }

    assert entrypoint.main(argv_common, **kwargs) == 2
    assert entrypoint.main(["--preflight-only", "--live", *argv_common], **kwargs) == 2
    assert entrypoint.main(["--live", "--frozen-sha", SEAL_SHA], **kwargs) == 2
    assert _relative_files(sealed) == {"manifest.json", "expectations.json"}


def test_entrypoint_never_sets_or_reads_the_resolver_from_os_environ_directly() -> None:
    """Matrix 20: the CLI injects ``env.get("GRPC_DNS_RESOLVER")``; it never writes it
    and never bypasses the injected env. ``os.environ`` is only the injectable default."""
    source = Path(entrypoint.__file__).read_text(encoding="utf-8")
    assert "os.environ[" not in source
    assert "putenv" not in source
    assert "setdefault" not in source
    assert "getenv" not in source
    assert source.count("os.environ") == 1
    assert "GRPC_DNS_RESOLVER=native uv run python scripts/run_long_horizon_bounded_memory.py" in (
        source
    )
    assert "2026-09-13-long-horizon-bounded-memory-v1" in source
    assert (entrypoint.EXIT_OK, entrypoint.EXIT_REFUSED) == (0, 2)
    assert (entrypoint.EXIT_PREFLIGHT_FAILED, entrypoint.EXIT_ABORTED) == (3, 4)


# =====================================================================================
# live: refusals and preflight before the key and before construction (matrix 21-25)
# =====================================================================================


def test_live_refuses_without_seal_files(tmp_path: Path) -> None:
    """Matrix 21."""
    out = tmp_path / "unsealed"
    out.mkdir()

    assert _main("--live", out) == 2
    assert _relative_files(out) == set()


def test_live_refuses_when_a_raw_artifact_exists_before_any_gate_or_factory(sealed: Path) -> None:
    """Matrix 22: a preserved ``preflight.json`` suffices; no git fact is consulted."""
    (sealed / "preflight.json").write_text("{}\n", encoding="utf-8")
    before = _dir_snapshot(sealed)
    git = FakeGit()

    code = _main("--live", sealed, git=git, env=PoisonedEnv(), factory=_poisoned_factory)

    assert code == 2
    assert _dir_snapshot(sealed) == before
    assert git.calls == []


def test_live_refuses_when_a_nested_raw_artifact_exists(sealed: Path) -> None:
    """Matrix 22 (variant)."""
    (sealed / "R" / "T03").mkdir(parents=True)
    (sealed / "R" / "T03" / "result.json").write_text("{}\n", encoding="utf-8")
    before = _dir_snapshot(sealed)

    assert _main("--live", sealed) == 2
    assert _dir_snapshot(sealed) == before


def test_live_failed_preflight_writes_preflight_only_and_never_reads_key_or_factory(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 23: a failing gate with a poisoned env and a poisoned factory."""
    seal_before = _seal_bytes(sealed)

    code = _main(
        "--live",
        sealed,
        env=PoisonedEnv(),
        factory=_poisoned_factory,
        git=FakeGit(dirty="?? scratch.txt"),
    )

    assert code == 3
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}
    preflight = _read_json(sealed / "preflight.json")
    assert preflight["all_passed"] is False
    assert preflight["run_status"] == "ABORTED_PREFLIGHT"
    assert preflight["frontier_calls"] == 0
    assert _gate_table(preflight)["worktree_clean"]["passed"] is False
    assert "ABORTED_PREFLIGHT" in capsys.readouterr().out
    assert _seal_bytes(sealed) == seal_before


def test_live_failed_ancestry_gate_stops_before_key_and_construction(sealed: Path) -> None:
    """Matrix 23 (variant)."""
    code = _main("--live", sealed, git=FakeGit(ancestors=frozenset()))

    assert code == 3
    gates = _gate_table(_read_json(sealed / "preflight.json"))
    assert gates["seal_descends_from_frozen_core"]["passed"] is False
    assert gates["historical_artifacts_unchanged"]["passed"] is False
    assert gates["predecessor_raw_evidence_unchanged"]["passed"] is False
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}


@pytest.mark.parametrize("resolver", [None, "", "ares", "Native"])
def test_live_with_a_non_native_resolver_aborts_preflight_before_key_and_construction(
    sealed: Path, capsys: pytest.CaptureFixture[str], resolver: str | None
) -> None:
    """Matrix 24: exit 3, ``preflight.json`` with only gate 21 failed, factory never
    called, key never read, nothing else written."""
    values = {"XAI_API_KEY": KEY_CANARY, "UNRELATED": ENV_CANARY}
    if resolver is not None:
        values[GRPC_DNS_RESOLVER_ENV] = resolver
    env = RecordingEnv(values)
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=env, factory=_poisoned_factory)

    assert code == 3
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}
    preflight = _read_json(sealed / "preflight.json")
    assert preflight["all_passed"] is False
    assert preflight["run_status"] == "ABORTED_PREFLIGHT"
    assert preflight["frontier_calls"] == 0
    assert preflight["observed_grpc_dns_resolver"] == resolver
    assert _failed_gates(preflight) == ["grpc_dns_resolver_is_native"]
    out = capsys.readouterr().out
    assert "ABORTED_PREFLIGHT" in out
    assert "grpc_dns_resolver_is_native" in out
    assert KEY_CANARY not in out and ENV_CANARY not in out
    assert KEY_CANARY not in (sealed / "preflight.json").read_text(encoding="utf-8")
    assert _seal_bytes(sealed) == seal_before


def test_live_missing_key_after_passed_preflight_is_aborted_runtime_with_zero_calls(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 25: the key is read exactly once, only after all 23 gates passed; the
    full raw tree records ``ABORTED_RUNTIME`` / ``MISSING_API_KEY`` with zero calls."""
    env = RecordingEnv({GRPC_DNS_RESOLVER_ENV: "native", "UNRELATED": ENV_CANARY})
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=env, factory=_poisoned_factory)

    assert code == 4
    assert env.reads == [GRPC_DNS_RESOLVER_ENV, "XAI_API_KEY"]
    assert _relative_files(sealed) == FULL_TREE
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"] == "MISSING_API_KEY"
    assert f_result["budget"]["frontier_calls"] == 0
    assert f_result["budget"]["provider_cost_usd"] == "0"
    assert _statuses(sealed, "F") == ["NOT_RUN"] * 16
    assert _statuses(sealed, "A") == ["NOT_RUN"] * 16
    assert _r_statuses(sealed) == ["NOT_RUN"] * 16
    assert [step["position"] for step in f_result["steps"]] == [
        position for position, (_, arm) in enumerate(ARM_SCHEDULE) if arm == "F"
    ]
    assert _request_count(sealed) == 0
    assert _read_json(sealed / "measurements.json")["row_count"] == 0
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["status"] == "ABORTED_RUNTIME"
    assert verdicts["architecture_selection"] is None
    assert verdicts["semantic_checkpoints"] is None
    assert set(verdicts["integrity"]) == {f"I{n}" for n in range(1, 16)}
    for path, text in _all_artifact_text(sealed):
        assert ENV_CANARY not in text, path
        assert "UNRELATED" not in text, path
    out = capsys.readouterr().out
    assert "ABORTED_RUNTIME" in out and "MISSING_API_KEY" in out
    assert ENV_CANARY not in out
    assert _seal_bytes(sealed) == seal_before


def test_live_empty_key_is_the_same_runtime_abort(sealed: Path) -> None:
    """Matrix 25 (variant)."""
    code = _main("--live", sealed, env=RecordingEnv(_live_env(XAI_API_KEY="")))

    assert code == 4
    assert _read_json(sealed / "F/result.json")["run_error"] == "MISSING_API_KEY"
    assert _request_count(sealed) == 0


# =====================================================================================
# identity guard on the inner reasoners (matrix 26-28)
# =====================================================================================


def test_reasoner_with_the_historical_identity_supplied_as_f_is_refused_at_construction(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 26: a 9p-v4-fingerprinted fake handed over as arm F is refused before any
    forwarded call: ``ABORTED_RUNTIME``, zero calls, the full tree, exit 4."""
    factory = FakeFactory(fingerprints={"F": A_FINGERPRINT}, f_type=HistoricalFake)
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert factory.calls == [KEY_CANARY]
    assert factory.total_requests == 0
    assert _relative_files(sealed) == FULL_TREE
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert "intent-v2-9p-v4" in f_result["run_error"]
    assert "fr_policy_version" in f_result["run_error"]
    assert f_result["budget"]["frontier_calls"] == 0
    assert _statuses(sealed, "F") == ["NOT_RUN"] * 16
    assert _request_count(sealed) == 0
    assert "ABORTED_RUNTIME" in capsys.readouterr().out
    assert _seal_bytes(sealed) == seal_before


def test_identity_guard_observes_the_inner_reasoners_provider_model_and_effort(
    sealed: Path,
) -> None:
    """Matrix 26 (variant): the fingerprint's model and the exposed reasoning effort."""
    other_model = ReasonerFingerprint(
        provider=PROVIDER, model="grok-3", policy_version=CONTRASTIVE_POLICY_VERSION
    )
    factory = FakeFactory(fingerprints={"R": other_model})

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert "model" in f_result["run_error"] and "grok-3" in f_result["run_error"]
    assert "arm R" in f_result["run_error"]
    assert factory.total_requests == 0
    assert _statuses(sealed, "F") == ["NOT_RUN"] * 16


def test_identity_guard_refuses_a_drifted_reasoning_effort(sealed: Path) -> None:
    class LowEffort(ContrastiveFake):
        reasoning_effort = "low"

    factory = FakeFactory(f_type=LowEffort)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert "reasoning_effort" in f_result["run_error"] and "low" in f_result["run_error"]
    assert factory.total_requests == 0


@pytest.mark.parametrize(
    ("attribute", "value", "field"),
    [
        ("system_instruction", "tampered after seal", "fr_prompt_sha256"),
        ("policy_version", "intent-v2-9p2-v2", "fr_policy_version"),
        ("include_comparison_context", False, "include_comparison_context"),
    ],
)
def test_adapter_attribute_drift_is_identity_drift_before_any_forwarded_call(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, attribute: str, value: object, field: str
) -> None:
    """Matrix 27: the class-level attributes of the innermost reasoner drift after the
    guard accepted it at construction (so the check is per call, on the instance's
    class, not on module constants): refused before forwarding; nothing rendered by
    the fake; the cell FAILED and every later cell NOT_RUN."""

    class Tamperable(ContrastiveFake):
        pass

    real_build = entrypoint.build_arm_reasoners

    def _build_then_tamper(**kwargs: Any) -> Any:
        arms = real_build(**kwargs)
        setattr(Tamperable, attribute, value)
        return arms

    monkeypatch.setattr(entrypoint, "build_arm_reasoners", _build_then_tamper)
    factory = FakeFactory(f_type=Tamperable)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert field in f_result["run_error"]
    assert factory.total_requests == 0
    assert _statuses(sealed, "F") == ["FAILED"] + ["NOT_RUN"] * 15
    assert _statuses(sealed, "A") == ["NOT_RUN"] * 16


@pytest.mark.parametrize(
    ("name", "value", "field"),
    [
        ("SYSTEM_INSTRUCTION", "tampered", "a_prompt_sha256"),
        ("CONTRASTIVE_SYSTEM_INSTRUCTION", "tampered", "fr_prompt_sha256"),
        ("POLICY_VERSION", "intent-v2-9p-v5", "a_policy_version"),
        ("CONTRASTIVE_POLICY_VERSION", "intent-v2-9p2-v2", "fr_policy_version"),
        ("MAX_FRONTIER_CALLS", 97, "ceilings"),
        ("MAX_COST_USD", 9.0, "ceilings"),
        ("MAX_HUMAN_AUTHORIZATIONS", 47, "ceilings"),
    ],
)
def test_in_process_identity_drift_after_preflight_aborts_before_any_forwarded_call(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: object, field: str
) -> None:
    """Matrix 27 (variant): this module's own references are re-checked per call."""
    monkeypatch.setattr(entrypoint, name, value)
    factory = FakeFactory()

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert field in f_result["run_error"]
    assert factory.total_requests == 0


def test_identity_guard_schema_drift_aborts_before_forwarding(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entrypoint, "semantic_output_schema_sha256", lambda: "0" * 64)
    factory = FakeFactory()

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert "output_schema_sha256" in f_result["run_error"]
    assert factory.total_requests == 0


def test_per_call_identity_drift_mid_run_is_never_forwarded(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 28: F's class identity drifts after its second forwarded call (T1 done);
    its next call (T2, schedule position 5) is refused by the guard before the fake
    sees it: F forwarded exactly 2; A and R completed T1 and T2 (4 each); the refused
    call was counted by the budget; the cell is FAILED and every later cell NOT_RUN."""

    class Drifting(ContrastiveFake):
        pass

    def _drift() -> None:
        Drifting.policy_version = "intent-v2-9p2-v2"

    factory = FakeFactory(f_type=Drifting, f_hooks={1: _drift})
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert len(factory.f.requests) == 2
    assert len(factory.a.requests) == 4
    assert len(factory.r.requests) == 4
    assert factory.total_requests == 10
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("IdentityDrift:")
    assert "fr_policy_version" in f_result["run_error"]
    assert f_result["budget"]["frontier_calls"] == 11
    assert _statuses(sealed, "F") == ["COMPLETED", "FAILED"] + ["NOT_RUN"] * 14
    assert _statuses(sealed, "A") == ["COMPLETED", "COMPLETED"] + ["NOT_RUN"] * 14
    assert _r_statuses(sealed) == ["COMPLETED", "COMPLETED"] + ["NOT_RUN"] * 14
    assert len(_read_json(sealed / "A/requests.json")["entries"]) == 4
    assert len(_read_json(sealed / "R/T02/requests.json")["entries"]) == 2
    assert "ABORTED_RUNTIME" in capsys.readouterr().out
    assert _seal_bytes(sealed) == seal_before


def test_identity_guard_is_transparent_when_identity_holds() -> None:
    manifest = build_manifest(
        harness_code_sha=HARNESS_SHA, spec_sha256=SPEC_SHA, historical_tree_hashes=TREE_HASHES
    ).model_dump(mode="json")
    inner = ContrastiveFake(label="F")

    guarded = entrypoint.IdentityGuardReasoner(inner, arm="F", manifest=manifest)

    assert guarded.fingerprint == inner.fingerprint == FR_FINGERPRINT
    assert guarded.receipts == () and guarded.draft_payloads == ()
    assert guarded.inner is inner and guarded.arm == "F"
    budget = ExperimentBudget()
    arms = build_arm_reasoners(
        inner_f=guarded,
        inner_a=entrypoint.IdentityGuardReasoner(
            HistoricalFake(label="A"), arm="A", manifest=manifest
        ),
        inner_r=entrypoint.IdentityGuardReasoner(
            ContrastiveFake(label="R"), arm="R", manifest=manifest
        ),
        budget=budget,
    )
    assert arms.f.recording.inner is guarded
    assert arms.f.budget is budget


def test_identity_guard_reads_the_instance_resolved_prompt_and_path() -> None:
    """The real adapter sends ``self.system_instruction`` and consults
    ``self.include_comparison_context``; the guard must observe the values the
    INSTANCE resolves (an instance attribute shadowing the ClassVar changes what is
    sent), not the class's. The untampered fake still passes."""
    manifest = build_manifest(
        harness_code_sha=HARNESS_SHA, spec_sha256=SPEC_SHA, historical_tree_hashes=TREE_HASHES
    ).model_dump(mode="json")
    entrypoint.IdentityGuardReasoner(ContrastiveFake(label="F"), arm="F", manifest=manifest)

    tampered_prompt = ContrastiveFake(label="F")
    tampered_prompt.system_instruction = "TAMPERED"  # type: ignore[misc]
    with pytest.raises(entrypoint.IdentityDrift, match="fr_prompt_sha256"):
        entrypoint.IdentityGuardReasoner(tampered_prompt, arm="F", manifest=manifest)

    tampered_path = ContrastiveFake(label="F")
    tampered_path.include_comparison_context = False  # type: ignore[misc]
    with pytest.raises(entrypoint.IdentityDrift, match="include_comparison_context"):
        entrypoint.IdentityGuardReasoner(tampered_path, arm="F", manifest=manifest)


def test_identity_guard_without_receipts_exposes_none() -> None:
    """The guard neither adds nor hides adapter economics: a reasoner without receipts
    stays a reasoner without receipts (the runner then records no measurements)."""

    class Bare:
        policy_version = CONTRASTIVE_POLICY_VERSION
        system_instruction = CONTRASTIVE_SYSTEM_INSTRUCTION
        include_comparison_context = True

        @property
        def fingerprint(self) -> ReasonerFingerprint:
            return FR_FINGERPRINT

        def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
            return ()

    manifest = build_manifest(
        harness_code_sha=HARNESS_SHA, spec_sha256=SPEC_SHA, historical_tree_hashes=TREE_HASHES
    ).model_dump(mode="json")
    guarded = entrypoint.IdentityGuardReasoner(Bare(), arm="R", manifest=manifest)
    assert not hasattr(guarded, "receipts")
    assert not hasattr(guarded, "draft_payloads")


# =====================================================================================
# live: fake success and failure discipline (matrix 29-31)
# =====================================================================================


def test_live_fake_success_writes_full_tree_96_records_48_cells_and_96_measurements(
    live_success: LiveRun,
) -> None:
    """Matrix 29."""
    out = live_success.out
    assert live_success.code == 0
    assert live_success.factory.calls == [KEY_CANARY]
    assert live_success.env.reads == [GRPC_DNS_RESOLVER_ENV, "XAI_API_KEY"]
    assert _relative_files(out) == FULL_TREE
    preflight = _read_json(out / "preflight.json")
    assert preflight["all_passed"] is True
    assert len(preflight["gates"]) == 23
    assert preflight["observed_grpc_dns_resolver"] == "native"
    assert _request_count(out) == 96
    assert live_success.factory.total_requests == 96
    assert (len(live_success.factory.f.requests), len(live_success.factory.a.requests)) == (32, 32)
    f_result = _read_json(out / "F/result.json")
    assert f_result["run_status"] == "COMPLETED"
    assert f_result["run_error"] is None
    assert f_result["budget"]["frontier_calls"] == 96
    assert f_result["budget"]["judge_calls"] == 0
    assert _statuses(out, "F") == ["COMPLETED"] * 16
    assert _statuses(out, "A") == ["COMPLETED"] * 16
    assert _r_statuses(out) == ["COMPLETED"] * 16
    assert f_result["replay"] is not None
    assert len(f_result["roots"]) == 12
    measurements = _read_json(out / "measurements.json")
    assert measurements["row_count"] == 96 and len(measurements["rows"]) == 96
    verdicts = _read_json(out / "verdicts.json")
    assert verdicts["phase"] == "raw"
    assert verdicts["status"] == "COMPLETED"
    assert verdicts["semantic_checkpoints"] is None
    assert verdicts["material_errors"] is None
    assert verdicts["control_errors"] is None
    assert verdicts["errors_total"] is None
    assert verdicts["architecture_selection"] is None
    assert set(verdicts["integrity"]) == {f"I{n}" for n in range(1, 16)}
    assert verdicts["integrity"]["I13"]["passed"] is True
    assert verdicts["integrity"]["I14"]["passed"] is True
    for path, text in _all_artifact_text(out):
        assert KEY_CANARY not in text, path
        assert ENV_CANARY not in text, path
    assert "COMPLETED" in live_success.stdout
    assert KEY_CANARY not in live_success.stdout
    assert _seal_bytes(out) == live_success.seal_before
    # The gates written to preflight.json are the ones handed to integrity_verdicts:
    # evaluated exactly once (gate 1 reads HEAD once).
    assert live_success.git.calls.count(("head",)) == 1


def test_preflight_only_document_matches_the_live_preflight_json_exactly(
    live_success: LiveRun, sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 20/29: the same manifest sealed elsewhere yields the same printed
    document as the live run's ``preflight.json``."""
    assert _main("--preflight-only", sealed) == 0
    printed = json.loads(capsys.readouterr().out)

    assert _read_json(live_success.out / "preflight.json") == printed


def test_exception_escaping_the_runner_is_recorded_as_aborted_runtime(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix 30."""

    def _explode(**_kwargs: Any) -> Any:
        raise RuntimeError("session construction failed")

    monkeypatch.setattr(entrypoint, "run_experiment", _explode)
    factory = FakeFactory()

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"] == "RuntimeError: session construction failed"
    assert _request_count(sealed) == 0
    assert factory.total_requests == 0


def test_reasoner_construction_failure_is_recorded_as_aborted_runtime(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 30 (variant): a raising factory is recorded, never a traceback."""

    def _bootstrap_fails(*, api_key: str) -> tuple[Any, Any, Any]:
        raise RuntimeError(f"client bootstrap failed for key {SECRET_SHAPED}")

    seal_before = _seal_bytes(sealed)
    code = _main("--live", sealed, env=_live_env(), factory=_bootstrap_fails)

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"].startswith("RuntimeError: client bootstrap failed for key ")
    assert "MISSING" not in f_result["run_error"]
    assert SECRET_SHAPED not in f_result["run_error"]
    assert "[REDACTED]" in f_result["run_error"]
    assert f_result["budget"]["frontier_calls"] == 0
    assert _statuses(sealed, "F") == ["NOT_RUN"] * 16
    assert _request_count(sealed) == 0
    for path, text in _all_artifact_text(sealed):
        assert KEY_CANARY not in text, path
        assert SECRET_SHAPED not in text, path
    out = capsys.readouterr().out
    assert "ABORTED_RUNTIME" in out
    assert KEY_CANARY not in out and SECRET_SHAPED not in out
    assert _seal_bytes(sealed) == seal_before


def test_interrupt_escaping_the_runner_is_preserved_as_aborted_runtime(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _interrupt(**_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(entrypoint, "run_experiment", _interrupt)

    code = _main("--live", sealed, env=_live_env(), factory=FakeFactory())

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"] == "INTERRUPTED: KeyboardInterrupt"


def test_exception_escaping_the_runner_keeps_the_cell_records_it_produced(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix 30 (variant): the runner's ``progress`` records fill their positions; only
    the positions it never reached are NOT_RUN. The runner is made to raise OUTSIDE
    its per-cell catch site (while handing over the sixth record) so the test stays
    small: twelve forwarded calls, six completed cells."""
    real_run = runner_module.run_experiment

    def _run_then_escape(**kwargs: Any) -> Any:
        original: list[Any] = kwargs["progress"]

        class _CutProgress(list[Any]):
            def append(self, cell: Any) -> None:
                original.append(cell)
                super().append(cell)
                if len(self) >= 6:
                    raise RuntimeError("escaped mid-schedule")

        return real_run(**{**kwargs, "progress": _CutProgress()})

    monkeypatch.setattr(entrypoint, "run_experiment", _run_then_escape)
    factory = FakeFactory()

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_RUNTIME"
    assert f_result["run_error"] == "RuntimeError: escaped mid-schedule"
    assert f_result["budget"]["frontier_calls"] == 12
    assert _statuses(sealed, "F") == ["COMPLETED", "COMPLETED"] + ["NOT_RUN"] * 14
    assert _statuses(sealed, "A") == ["COMPLETED", "COMPLETED"] + ["NOT_RUN"] * 14
    assert _r_statuses(sealed) == ["COMPLETED", "COMPLETED"] + ["NOT_RUN"] * 14
    assert _request_count(sealed) == 12
    assert factory.total_requests == 12
    assert f_result["ledger_event_count"] > 0
    assert f_result["request_count"] == 4
    assert _read_json(sealed / "measurements.json")["row_count"] == 12


def test_partial_cells_fill_only_the_missing_positions_with_not_run() -> None:
    """Matrix 30 (unit): ``_aborted_runtime_result`` over three captured cells."""
    factory = FakeFactory(a_failures={4: XAIProviderError("opaque")})
    budget = ExperimentBudget()
    arms = build_arm_reasoners(
        inner_f=factory.f, inner_a=factory.a, inner_r=factory.r, budget=budget
    )
    progress: list[Any] = []
    real = runner_module.run_experiment(
        reasoners=arms, clock=entrypoint._utc_now, id_factory=entrypoint._mint, progress=progress
    )
    assert real.status is RunStatus.ABORTED_PROVIDER
    captured = progress[:3]  # F T1, A T1, R T1 -- as if the runner raised at A T2

    run = entrypoint._aborted_runtime_result(
        error="RuntimeError: escaped", budget=budget, arms=arms, cells=captured
    )

    assert run.status is RunStatus.ABORTED_RUNTIME
    assert run.cells[:3] == tuple(captured)
    assert [c.status for c in run.cells] == ["COMPLETED"] * 3 + ["NOT_RUN"] * 45
    assert [(c.t, c.arm, c.position) for c in run.cells] == [
        (t, arm, position) for position, (t, arm) in enumerate(ARM_SCHEDULE)
    ]
    assert run.f.ledger == captured[0].ledger and run.f.final_state == captured[0].state_snapshot
    assert run.a.ledger == captured[1].ledger and run.a.final_view == captured[1].view_snapshot
    assert len(run.f.roots) == 12
    assert run.f.replay is None
    assert run.r_cells[1] == captured[2]
    assert set(run.r_cells) == set(range(1, 17))
    assert run.f.requests == real.f.requests
    assert run.f.reference_snapshots == real.f.reference_snapshots
    assert run.budget.frontier_calls == real.budget.frontier_calls
    assert run.measurements == tuple(row for cell in captured for row in cell.measurements)


def test_provider_failure_at_position_20_preserves_earlier_cells_and_stops_later_calls(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 31: schedule position 20 is R T7; its Call 1 is the 41st forwarded call
    (R's thirteenth). Positions 0-19 COMPLETED, 20 FAILED, 21-47 NOT_RUN; exit 4."""
    assert R_CALLS_BEFORE_POSITION_20 == 12
    failure = XAIProviderError(f"provider rejected key {SECRET_SHAPED}")
    factory = FakeFactory(r_failures={R_CALLS_BEFORE_POSITION_20: failure})
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    f_result = _read_json(sealed / "F/result.json")
    assert f_result["run_status"] == "ABORTED_PROVIDER"
    assert f_result["run_error"].startswith("XAIProviderError: provider rejected key ")
    assert SECRET_SHAPED not in f_result["run_error"]
    assert "[REDACTED]" in f_result["run_error"]
    assert f_result["budget"]["frontier_calls"] == 41
    assert factory.total_requests == 41
    assert _statuses(sealed, "F") == ["COMPLETED"] * 7 + ["NOT_RUN"] * 9
    assert _statuses(sealed, "A") == ["COMPLETED"] * 7 + ["NOT_RUN"] * 9
    assert _r_statuses(sealed) == ["COMPLETED"] * 6 + ["FAILED"] + ["NOT_RUN"] * 9
    r7 = _read_json(sealed / "R/T07/result.json")
    assert r7["position"] == POSITION_20
    assert r7["request_count"] == 1 and r7["receipt_count"] == 0
    assert SECRET_SHAPED not in (r7["error"] or "")
    assert len(_read_json(sealed / "F/requests.json")["entries"]) == 14
    assert len(_read_json(sealed / "A/requests.json")["entries"]) == 14
    assert len(_read_json(sealed / "R/T06/requests.json")["entries"]) == 2
    assert len(_read_json(sealed / "R/T07/requests.json")["entries"]) == 1
    assert len(_read_json(sealed / "R/T08/requests.json")["entries"]) == 0
    assert _request_count(sealed) == 41
    assert _read_json(sealed / "measurements.json")["row_count"] == 40
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["status"] == "ABORTED_PROVIDER"
    assert verdicts["architecture_selection"] is None
    for path, text in _all_artifact_text(sealed):
        assert KEY_CANARY not in text, path
        assert SECRET_SHAPED not in text, path
    out = capsys.readouterr().out
    assert "ABORTED_PROVIDER" in out
    assert KEY_CANARY not in out and SECRET_SHAPED not in out
    assert _seal_bytes(sealed) == seal_before


# =====================================================================================
# raw-preservation failure after the run (matrix 32)
# =====================================================================================


def test_raw_preservation_failure_after_96_calls_never_rewrites_and_exits_4(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 32 (CRITICAL): the writer refuses after the run -- it is called exactly
    once, never again; no replacement run; ``preflight.json`` untouched; no other raw
    file exists (the writer is all-or-nothing); the secret never reaches the console;
    exit 4 because frontier calls were consumed."""
    writer_calls: list[tuple[Path, Any, Any]] = []

    def _refusing_writer(out_dir: Path, run: Any, verdicts: Any) -> tuple[str, ...]:
        writer_calls.append((out_dir, run, verdicts))
        raise ValueError(f"secret-shaped token inside rendered_user_request {SECRET_SHAPED}")

    monkeypatch.setattr(entrypoint, "write_run_artifacts", _refusing_writer)
    factory = FakeFactory()
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert factory.calls == [KEY_CANARY]
    assert factory.total_requests == 96
    assert len(writer_calls) == 1
    _, run, verdicts = writer_calls[0]
    assert run.status is RunStatus.COMPLETED
    assert run.budget.frontier_calls == 96
    assert len(verdicts) == 15
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}
    preflight_after = (sealed / "preflight.json").read_bytes()
    assert json.loads(preflight_after)["all_passed"] is True
    assert _seal_bytes(sealed) == seal_before
    captured = capsys.readouterr()
    assert "RAW ARTIFACT PRESERVATION FAILED" in captured.out
    assert "ValueError" in captured.out
    assert "frontier_calls=96" in captured.out
    assert SECRET_SHAPED not in captured.out and SECRET_SHAPED not in captured.err
    assert KEY_CANARY not in captured.out and KEY_CANARY not in captured.err


def test_raw_preservation_failure_leaves_the_first_preflight_bytes_untouched(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix 32 (variant): the preflight bytes are those of the first (only) write."""
    first_write: list[bytes] = []
    real_write_preflight = entrypoint.write_preflight

    def _observing_write_preflight(*args: Any, **kwargs: Any) -> Path:
        path = real_write_preflight(*args, **kwargs)
        first_write.append(path.read_bytes())
        return path

    def _refusing_writer(*_args: Any, **_kwargs: Any) -> tuple[str, ...]:
        raise ValueError("stray target")

    monkeypatch.setattr(entrypoint, "write_preflight", _observing_write_preflight)
    monkeypatch.setattr(entrypoint, "write_run_artifacts", _refusing_writer)

    code = _main("--live", sealed, env=_live_env(), factory=FakeFactory())

    assert code == 4
    assert len(first_write) == 1
    assert (sealed / "preflight.json").read_bytes() == first_write[0]
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}


def test_raw_preservation_failure_with_zero_calls_is_a_refusal(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix 32 (variant): the missing-key tree cannot be written -- no live attempt
    began, so exit 2, the writer called once, nothing but ``preflight.json`` written."""
    writer_calls: list[Any] = []

    def _refusing_writer(out_dir: Path, run: Any, verdicts: Any) -> tuple[str, ...]:
        writer_calls.append(run)
        raise ValueError("binding failure")

    monkeypatch.setattr(entrypoint, "write_run_artifacts", _refusing_writer)
    env = RecordingEnv({GRPC_DNS_RESOLVER_ENV: "native"})

    code = _main("--live", sealed, env=env, factory=_poisoned_factory)

    assert code == 2
    assert len(writer_calls) == 1
    assert writer_calls[0].error == "MISSING_API_KEY"
    assert env.reads == [GRPC_DNS_RESOLVER_ENV, "XAI_API_KEY"]
    assert _relative_files(sealed) == {"manifest.json", "expectations.json", "preflight.json"}
    out = capsys.readouterr().out
    assert "RAW ARTIFACT PRESERVATION FAILED" in out and "frontier_calls=0" in out


# =====================================================================================
# immutability (matrix 33-34)
# =====================================================================================


def test_second_live_attempt_after_success_refuses_before_the_factory(
    live_success: LiveRun,
) -> None:
    """Matrix 33: the identity is consumed; a preserved raw tree refuses ``--live``."""
    after_first = _dir_snapshot(live_success.out)

    code = _main(
        "--live",
        live_success.out,
        env=PoisonedEnv(),
        factory=_poisoned_factory,
        git=FakeGit(dirty="?? would-fail-anyway"),
    )

    assert code == 2
    assert _dir_snapshot(live_success.out) == after_first


def test_second_live_attempt_after_a_failed_preflight_refuses(sealed: Path) -> None:
    """Matrix 33 (variant): a preserved failed preflight alone consumes the identity."""
    assert _main("--live", sealed, git=FakeGit(dirty="?? scratch")) == 3
    after_first = _dir_snapshot(sealed)

    code = _main("--live", sealed, env=PoisonedEnv(), factory=_poisoned_factory)

    assert code == 2
    assert _dir_snapshot(sealed) == after_first


def test_manifest_and_expectations_bytes_are_unchanged_after_every_run_mode(
    tmp_path: Path, live_success: LiveRun
) -> None:
    """Matrix 34: passed and failed preflight-only, failed live preflight, missing key,
    provider abort and factory failure all leave the seal bytes byte-identical; the
    fake success did too."""
    assert _seal_bytes(live_success.out) == live_success.seal_before
    scenarios: list[tuple[str, Callable[[Path], int]]] = [
        ("preflight-only-pass", lambda out: _main("--preflight-only", out)),
        (
            "preflight-only-fail",
            lambda out: _main("--preflight-only", out, git=FakeGit(dirty=" M x")),
        ),
        ("live-preflight-fail", lambda out: _main("--live", out, git=FakeGit(dirty=" M x"))),
        (
            "live-missing-key",
            lambda out: _main("--live", out, env=RecordingEnv({GRPC_DNS_RESOLVER_ENV: "native"})),
        ),
        (
            "live-provider-abort",
            lambda out: _main(
                "--live",
                out,
                env=_live_env(),
                factory=FakeFactory(f_failures={0: XAIProviderError("opaque")}),
            ),
        ),
        (
            "live-factory-failure",
            lambda out: _main(
                "--live",
                out,
                env=_live_env(),
                factory=_raising_factory,
            ),
        ),
    ]
    expected = {"preflight-only-pass": 0, "preflight-only-fail": 3, "live-preflight-fail": 3}
    for name, scenario in scenarios:
        out = _seal(tmp_path / name)
        before = _seal_bytes(out)
        code = scenario(out)
        assert code == expected.get(name, 4), name
        assert _seal_bytes(out) == before, name


# =====================================================================================
# adjudication after the raw freeze (matrix 35-36)
# =====================================================================================


def test_write_adjudication_end_to_end_on_the_fake_run_tree(
    live_success: LiveRun, tmp_path: Path
) -> None:
    """Matrix 35: the raw tree of the fake live success, committed (FakeGit at the raw
    commit, clean, every file shown byte-identical), adjudicated: success, and only
    ``verdicts.json`` and ``report.md`` change."""
    out_dir = _copy_tree(live_success.out, tmp_path)
    git = _committed(out_dir, tmp_path)
    before = _dir_snapshot(out_dir)
    assert set(before) == FULL_TREE

    written = write_adjudication(
        out_dir,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=git,
        adjudication=_adjudication(),
        repo_root=tmp_path,
    )
    after = _dir_snapshot(out_dir)

    assert written == ("verdicts.json", "report.md")
    assert set(after) == set(before)
    assert {name for name in before if before[name] != after[name]} == {
        "verdicts.json",
        "report.md",
    }
    verdicts = _read_json(out_dir / "verdicts.json")
    assert verdicts["phase"] == "adjudicated"
    assert verdicts["raw_run_commit_sha"] == RAW_RUN_SHA
    assert verdicts["errors_total"] == {"F": 0, "A": 0, "R": 0}
    assert verdicts["architecture_selection"]["decision"] in set(
        _read_json(out_dir / "manifest.json")["decision_names"]
    )
    assert verdicts["selection_inputs"]["completed"] is True
    assert verdicts["token_summary"]["f_total"] > 0
    shown = {call[2] for call in git.calls if call[0] == "show_bytes"}
    assert shown == {f"{EXPERIMENT_ARTIFACT_DIR}{name}" for name in RAW_ARTIFACT_PATHS}
    # A consumed identity stays consumed: the adjudicated tree still refuses --live.
    assert _main("--live", out_dir, env=PoisonedEnv(), factory=_poisoned_factory) == 2
    assert _dir_snapshot(out_dir) == after


def test_write_adjudication_refuses_an_uncommitted_or_moved_tree_with_nothing_written(
    live_success: LiveRun, tmp_path: Path
) -> None:
    """Matrix 36: HEAD is not the raw-run commit / a raw file differs from the commit /
    the worktree is dirty -- refused, nothing written."""
    out_dir = _copy_tree(live_success.out, tmp_path)
    before = _dir_snapshot(out_dir)

    with pytest.raises(AdjudicationRefused, match="HEAD"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=FakeGit(head=SEAL_SHA),
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert _dir_snapshot(out_dir) == before

    with pytest.raises(AdjudicationRefused, match="dirty"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=_committed(out_dir, tmp_path, dirty=" M something"),
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert _dir_snapshot(out_dir) == before

    git = _committed(out_dir, tmp_path)
    (out_dir / "A/ledger.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(AdjudicationRefused, match="differs"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=git,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert (out_dir / "verdicts.json").read_bytes() == before["verdicts.json"]
    assert (out_dir / "report.md").read_bytes() == before["report.md"]


# =====================================================================================
# default factory shape (adapters are monkeypatched; nothing real is constructed)
# =====================================================================================


def test_default_factory_constructs_f_a_r_with_the_frozen_model_and_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[str, dict[str, Any]]] = []

    class FakeBase:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(("base", kwargs))

    class FakeContrastive:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(("contrastive", kwargs))

    monkeypatch.setattr(entrypoint, "XAISemanticReasoner", FakeBase)
    monkeypatch.setattr(entrypoint, "XAIContrastiveSemanticReasoner", FakeContrastive)

    f, a, r = entrypoint.default_reasoner_factory(api_key="opaque-key")

    assert isinstance(f, FakeContrastive)
    assert isinstance(a, FakeBase)
    assert isinstance(r, FakeContrastive)
    assert [kind for kind, _ in constructed] == ["contrastive", "base", "contrastive"]
    for _, kwargs in constructed:
        assert kwargs == {"api_key": "opaque-key", "model": "grok-4.6", "reasoning_effort": "high"}


def test_scripts_import_only_public_names_from_the_experiment_package() -> None:
    """Clarification 2: no ``_``-prefixed name is imported from any 9P3 module."""
    for module in (entrypoint, prepare_entrypoint):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "foundry.experiments.long_horizon_bounded"
            ):
                private = [alias.name for alias in node.names if alias.name.startswith("_")]
                assert not private, (module.__name__, private)
