"""T8: the preregistration sealer, the preflight-only / live entry point and the
offline adjudication entry point of the locus-policy live-validation experiment (spec
§10, §11, §13, §15; the T8 brief and its eight clarifications).

Every git fact is an injected fake returning realistic values; every reasoner is a
scripted double carrying the locus identity, injected through ``reasoner_factory``;
every experiment directory is a throwaway under ``tmp_path`` sealed with the real
``build_manifest`` / ``write_preregistration``. ``--live`` never reaches a provider; no
real ``XAI_API_KEY`` is read (the poisoned env raises on it); no ``XAILocusSemanticReasoner``
is constructed (the factory test monkeypatches the class name); the real experiment
directory is never created; the frozen 9P3 directory is digest-snapshotted at import
and re-checked after every scenario. ZERO live calls; sockets are blocked.

The live order this module proves (spec §10, clarification 2): args -> seal files ->
resolver observed once -> leakage -> the 18 gates (exit 3 writes nothing, reads no key)
-> key (missing/empty: exit 2, nothing written) -> factory + construction-time identity
guard (drift: exit 2, nothing written) -> ``write_consumption`` (the first and only
write before any call) -> the run inside one abort boundary -> evaluation + verdicts
over the SAME gate tuple -> ``write_run_artifacts`` exactly once -> exit 0 iff
COMPLETED else 4.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import socket
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any, ClassVar, NamedTuple

import pytest

import scripts.adjudicate_locus_validation as adjudicate_entrypoint
import scripts.prepare_locus_validation as prepare_entrypoint
import scripts.run_locus_validation as entrypoint
from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_POLICY_VERSION,
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    SemanticOutputError,
    SemanticReasoningReceipt,
    XAIProviderError,
)
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.common import Authority
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
    SupportsClaimProposal,
)
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.locus_validation import runner as runner_module
from foundry.experiments.locus_validation.artifacts import (
    RAW_ARTIFACT_PATHS,
    SPEC_PATH,
    build_manifest,
    write_preregistration,
)
from foundry.experiments.locus_validation.corpus import (
    DOCUMENTS,
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    Ledger,
    evidence_id,
)
from foundry.experiments.locus_validation.expectations import SEMANTIC_ASSERTION_IDS
from foundry.experiments.locus_validation.integrity import GATE_NAMES, PREREGISTRATION_FILES
from foundry.experiments.locus_validation.leakage import REQUEST_PATH_MODULES
from foundry.experiments.locus_validation.protocol import (
    BASELINE_SHA,
    DESIGN_BASE_SHA,
    EXPERIMENT_ARTIFACT_DIR,
    EXPERIMENT_VERSION,
    GRPC_DNS_RESOLVER_ENV,
    HISTORICAL_ARTIFACT_DIRS,
    MAX_FRONTIER_CALLS,
    MODEL,
    PREDECESSOR_ADJUDICATION_SHA,
    PREDECESSOR_ARTIFACT_DIR,
    PREDECESSOR_RAW_RUN_SHA,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.recording import (
    BudgetExceeded,
    ExperimentBudget,
    IdentityDrift,
)
from foundry.experiments.locus_validation.runner import LedgerRecord, RunResult, RunStatus
from foundry.experiments.long_horizon_bounded.runner import ReferenceSnapshotMismatch
from foundry.ports.semantic_reasoner import ReasoningRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = "src/foundry/experiments/locus_validation/"
T0 = datetime(2026, 9, 15, tzinfo=UTC)
LOCUS_FINGERPRINT = ReasonerFingerprint(
    provider=PROVIDER, model=MODEL, policy_version=LOCUS_POLICY_VERSION
)
CONTRASTIVE_FINGERPRINT = ReasonerFingerprint(
    provider=PROVIDER, model=MODEL, policy_version=CONTRASTIVE_POLICY_VERSION
)
HARNESS_SHA = "b" * 40
SEAL_SHA = "a" * 40
RAW_RUN_SHA = "d" * 40
PREPARE_HEAD_SHA = "c" * 40
SPEC_SHA = "e" * 64
KEY_CANARY = "FAKE-KEY-CANARY-0123456789"
ENV_CANARY = "UNRELATED-ENV-CANARY-9876543210"
SECRET_SHAPED = "xai-abcdef123456"
API_KEY_ENV = "XAI_API_KEY"
INCONCLUSIVE = "EXPERIMENT_INCONCLUSIVE"
VALIDATED = "LOCUS_POLICY_" + "VALIDATED"
TREE_HASHES: dict[str, str] = {
    directory: hashlib.sha256(directory.encode("utf-8")).hexdigest()[:40]
    for directory in HISTORICAL_ARTIFACT_DIRS
}
CHANGES_SINCE_ADJUDICATION = (
    f"{PACKAGE_DIR}__init__.py",
    f"{PACKAGE_DIR}corpus.py",
    f"{PACKAGE_DIR}runner.py",
    "scripts/run_locus_validation.py",
    "tests/integration/test_locus_validation_entrypoint.py",
    "docs/superpowers/plans/2026-09-15-locus-policy-live-validation.md",
    SPEC_PATH,
    *PREREGISTRATION_FILES,
)
"""What changed since the 9P3 adjudication commit: nothing under the predecessor dir."""
SEAL_ONLY: set[str] = {"manifest.json", "expectations.json"}
CONSUMED_ONLY: set[str] = {*SEAL_ONLY, "consumption.json", "preflight.json"}
FULL_TREE: set[str] = {*SEAL_ONLY, *RAW_ARTIFACT_PATHS}
"""The two seal files plus the 21 raw artifact paths (23 files)."""
HISTORICAL_9P3_DIR = REPO_ROOT / PREDECESSOR_ARTIFACT_DIR
REAL_EXPERIMENT_DIR = REPO_ROOT / EXPERIMENT_ARTIFACT_DIR

type Drafts = tuple[SemanticJudgment, ...]
type Batch = Drafts | Callable[[ReasoningRequest], Drafts] | BaseException


def _tree_digest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


HISTORICAL_9P3_DIGEST_AT_IMPORT = _tree_digest(HISTORICAL_9P3_DIR)
REAL_EXPERIMENT_DIGEST_AT_IMPORT = _tree_digest(REAL_EXPERIMENT_DIR)
assert HISTORICAL_9P3_DIGEST_AT_IMPORT, "the frozen 9P3 directory must exist in the worktree"


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
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    yield
    assert API_KEY_ENV not in os.environ


@pytest.fixture(autouse=True)
def _frozen_directories_untouched() -> Iterator[None]:
    """After EVERY scenario: the 9P3 directory is byte-identical to its import-time
    digest, and the real experiment directory is exactly as it was at import (absent
    before the T10 seal; never created or touched by any scenario)."""
    yield
    assert _tree_digest(HISTORICAL_9P3_DIR) == HISTORICAL_9P3_DIGEST_AT_IMPORT
    assert _tree_digest(REAL_EXPERIMENT_DIR) == REAL_EXPERIMENT_DIGEST_AT_IMPORT


# --- injected git fakes (realistic values, never hard-coded success) --------------------


class FakeGit:
    """Every ``GitCliLike`` method, scripted for the 18 locus gates: the seal's single
    parent is the harness sha, the seal adds exactly the two preregistration paths, the
    four frozen shas are ancestors, the seven historical trees are equal at the design
    base and the seal, nothing under the predecessor directory changed since the 9P3
    adjudication, and ``show_bytes`` is keyed for adjudication."""

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
                    (BASELINE_SHA, SEAL_SHA),
                    (DESIGN_BASE_SHA, SEAL_SHA),
                    (PREDECESSOR_RAW_RUN_SHA, SEAL_SHA),
                    (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA),
                }
            )
        )
        self._changed = (
            changed
            if changed is not None
            else {
                (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
                (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA): CHANGES_SINCE_ADJUDICATION,
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
    """Tree ids equal at the design base and at the seal for all seven frozen
    directories; ``differing`` names one directory whose tree changed at the seal."""
    trees: dict[tuple[str, str], str] = {}
    for directory, tree in TREE_HASHES.items():
        trees[(DESIGN_BASE_SHA, directory)] = tree
        trees[(SEAL_SHA, directory)] = tree if directory != differing else "e" * 40
    return trees


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
            written = [name for name in SEAL_ONLY if (self._out / name).exists()]
            assert not written, f"git {argv} asked after {written} were written"
        if argv not in self._table:
            raise AssertionError(f"prepare ran a git operation outside its allowed set: {argv}")
        code, stdout, stderr = self._table[argv]
        self.answers[argv] = stdout
        return code, stdout, stderr


def _spec_bytes() -> bytes:
    return (REPO_ROOT / SPEC_PATH).read_bytes()


def _prepare_argvs() -> list[tuple[str, ...]]:
    """The allowed prepare git operations, in the brief's order (clarification 5)."""
    argvs: list[tuple[str, ...]] = [
        ("status", "--porcelain"),
        ("rev-parse", "HEAD"),
        ("merge-base", "--is-ancestor", BASELINE_SHA, "HEAD"),
        ("merge-base", "--is-ancestor", DESIGN_BASE_SHA, "HEAD"),
        ("merge-base", "--is-ancestor", PREDECESSOR_ADJUDICATION_SHA, "HEAD"),
        ("show", f"HEAD:{SPEC_PATH}"),
    ]
    for directory in HISTORICAL_ARTIFACT_DIRS:
        argvs.append(("rev-parse", f"{DESIGN_BASE_SHA}:{directory}"))
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
    for sha in (BASELINE_SHA, DESIGN_BASE_SHA, PREDECESSOR_ADJUDICATION_SHA):
        table[("merge-base", "--is-ancestor", sha, "HEAD")] = (
            (1, b"", b"") if sha in not_ancestors else ok
        )
    at_head = head_trees or {}
    for directory, tree in TREE_HASHES.items():
        table[("rev-parse", f"{DESIGN_BASE_SHA}:{directory}")] = (0, f"{tree}\n".encode(), b"")
        table[("rev-parse", f"HEAD:{directory}")] = (
            0,
            f"{at_head.get(directory, tree)}\n".encode(),
            b"",
        )
    return table


# --- environment fakes ------------------------------------------------------------------


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


class KeyPresentEnv(Mapping[str, str]):
    """An adjudication environment that carries the provider key NAME; reading its
    value is a test failure (presence-only law)."""

    def __contains__(self, key: object) -> bool:
        return key == API_KEY_ENV

    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"environment value {key!r} was read")

    def __iter__(self) -> Iterator[str]:
        return iter((API_KEY_ENV,))

    def __len__(self) -> int:
        return 1


def _live_env(**overrides: str) -> RecordingEnv:
    return RecordingEnv({GRPC_DNS_RESOLVER_ENV: "native", API_KEY_ENV: KEY_CANARY, **overrides})


# --- the scripted locus double (the T3 runner-test fake, with adapter economics) -------


class LocusFake:
    """Mirrors the real locus adapter's observable identity; a scripted ``propose``
    that records every forwarded request and returns the scripted batch, calls it with
    the request, or raises it; like the adapter, appends one receipt and one draft
    payload per ANSWERED call. ``hooks`` run when a call arrives, before it is answered.
    Refuses any call beyond the script."""

    policy_version: ClassVar[str] = LOCUS_POLICY_VERSION
    system_instruction: ClassVar[str] = LOCUS_SYSTEM_INSTRUCTION
    include_comparison_context: ClassVar[bool] = True
    reasoning_effort: ClassVar[str] = REASONING_EFFORT

    def __init__(
        self,
        batches: list[Batch],
        *,
        fingerprint: ReasonerFingerprint = LOCUS_FINGERPRINT,
        hooks: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self._batches = batches
        self._fingerprint = fingerprint
        self._hooks = hooks or {}
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[SemanticReasoningReceipt] = []
        self._payloads: list[dict[str, Any]] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    @property
    def receipts(self) -> tuple[SemanticReasoningReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._payloads)

    def propose(self, request: ReasoningRequest) -> Drafts:
        self.requests.append(request)
        index = len(self.requests) - 1
        hook = self._hooks.get(index)
        if hook is not None:
            hook()
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        result = batch(request) if callable(batch) else batch
        n = len(self.requests)
        self._receipts.append(
            SemanticReasoningReceipt(
                invocation_id=f"INV-{n}",
                model=MODEL,
                reasoning_effort="high",
                input_tokens=1000 + n,
                output_tokens=100 + n,
                cost_usd=n / 100,
                wall_clock_ms=50 * n,
                draft_count=len(result),
            )
        )
        self._payloads.append({"call": n, "drafts": len(result)})
        return result


class ContrastiveFake(LocusFake):
    """A fake carrying the historical 9p2-v1 contrastive identity: refused by the
    construction-time guard before any call."""

    policy_version: ClassVar[str] = CONTRASTIVE_POLICY_VERSION
    system_instruction: ClassVar[str] = CONTRASTIVE_SYSTEM_INSTRUCTION

    def __init__(self, batches: list[Batch]) -> None:
        super().__init__(batches, fingerprint=CONTRASTIVE_FINGERPRINT)


class FakeFactory:
    """Hands out one scripted reasoner; records every api_key it was handed (never
    printed) and how many times it was called."""

    def __init__(self, fake: LocusFake) -> None:
        self.fake = fake
        self.calls: list[str] = []

    def __call__(self, *, api_key: str) -> LocusFake:
        self.calls.append(api_key)
        return self.fake


def _poisoned_factory(*, api_key: str) -> Any:
    raise AssertionError("reasoner_factory must not be called on this path")


# --- draft builders (copied from the T3 runner test) ----------------------------------


def _judgment(
    ledger: Ledger, judgment_id: str, proposal: JudgmentProposal, cited: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT_IDS[ledger],
        proposal=proposal,
        visible_evidence_ids=(cited,),
        rationale=f"Scripted draft {judgment_id}.",
        reasoner=LOCUS_FINGERPRINT,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _candidate(ledger: Ledger, judgment_id: str, cited: str, label: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=f"CAND-{judgment_id}",
        subject=f"{label} subject",
        facet=f"{label} facet",
        scope=(SCOPES[ledger],),
        evidence_ids=(cited,),
    )


def _create(ledger: Ledger, judgment_id: str, cited: str, label: str) -> SemanticJudgment:
    proposal = CreateAddressProposal(candidate=_candidate(ledger, judgment_id, cited, label))
    return _judgment(ledger, judgment_id, proposal, cited)


def _bind(
    ledger: Ledger, judgment_id: str, address_id: str, cited: str, label: str
) -> SemanticJudgment:
    proposal = BindToAddressProposal(
        candidate=_candidate(ledger, judgment_id, cited, label), address_id=address_id
    )
    return _judgment(ledger, judgment_id, proposal, cited)


def _assert(
    ledger: Ledger, judgment_id: str, address_id: str, cited: str, predicate: str, value: str
) -> SemanticJudgment:
    proposal = AssertClaimProposal(
        address_id=address_id,
        predicate=predicate,
        value=ClaimValue(kind=ClaimValueKind.TEXT, text=value),
        evidence_ids=(cited,),
        authority=Authority.INFERRED,
    )
    return _judgment(ledger, judgment_id, proposal, cited)


def _support(ledger: Ledger, judgment_id: str, claim_id: str, cited: str) -> SemanticJudgment:
    proposal = SupportsClaimProposal(claim_id=claim_id, evidence_ids=(cited,))
    return _judgment(ledger, judgment_id, proposal, cited)


def _supersede(ledger: Ledger, judgment_id: str, target: str, cited: str) -> SemanticJudgment:
    proposal = SupersedeProposal(target_judgment_id=target, reason="Scripted supersession.")
    return _judgment(ledger, judgment_id, proposal, cited)


def _seed_create_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T1-create-{document}"


def _seed_claim_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T1-claim-{document}"


def _extra_create_id(ledger: Ledger) -> str:
    return f"J-{ledger}-T2-create-{DOCUMENTS[ledger][1]}-new"


def _supersede_id(ledger: Ledger) -> str:
    return f"J-{ledger}-T2-supersede-{DOCUMENTS[ledger][3]}"


def _seed_address(ledger: Ledger, document: str) -> str:
    return address_id_for(PROJECT_IDS[ledger], _seed_create_id(ledger, document))


def _extra_address(ledger: Ledger) -> str:
    return address_id_for(PROJECT_IDS[ledger], _extra_create_id(ledger))


def _seed_claim(ledger: Ledger, document: str) -> str:
    return claim_id_for(PROJECT_IDS[ledger], _seed_claim_id(ledger, document))


LEDGER_OF_PROJECT: dict[str, Ledger] = {project: ledger for ledger, project in PROJECT_IDS.items()}


def _ledger_and_t(request: ReasoningRequest) -> tuple[Ledger, int]:
    ledger = LEDGER_OF_PROJECT[request.project_id]
    t = 1 if all(item.supersedes_evidence_id is None for item in request.evidence) else 2
    return ledger, t


def _document_of_address(ledger: Ledger, address_id: str) -> str:
    for document in DOCUMENTS[ledger]:
        if _seed_address(ledger, document) == address_id:
            return document
    raise AssertionError(f"unknown seed address {address_id}")


def _prescribed(request: ReasoningRequest) -> Drafts:
    """Per call, the drafts the locus policy prescribes for the sealed corpus, minted
    from what the request actually shows (evidence, known addresses, known claims)."""
    ledger, t = _ledger_and_t(request)
    first_call = JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds
    documents = DOCUMENTS[ledger]
    if t == 1 and first_call:
        assert request.known_addresses == ()
        return tuple(
            _create(ledger, _seed_create_id(ledger, doc), item.evidence_id, doc)
            for doc, item in zip(documents, request.evidence, strict=True)
        )
    if t == 1:
        return tuple(
            _assert(
                ledger,
                _seed_claim_id(ledger, doc),
                address.address_id,
                evidence_id(doc, 1),
                f"{doc} rule",
                f"{doc} first value",
            )
            for address in request.known_addresses
            for doc in (_document_of_address(ledger, address.address_id),)
        )
    if first_call:
        binds = tuple(
            _bind(
                ledger,
                f"J-{ledger}-T2-bind-{doc}",
                address.address_id,
                evidence_id(doc, 2),
                doc,
            )
            for address in request.known_addresses
            for doc in (_document_of_address(ledger, address.address_id),)
        )
        extra = _create(
            ledger, _extra_create_id(ledger), evidence_id(documents[1], 2), f"{documents[1]} new"
        )
        return (*binds, extra)
    d1, d2, d3, d4 = documents
    known = {address.address_id for address in request.known_addresses}
    assert known == {*(_seed_address(ledger, doc) for doc in documents), _extra_address(ledger)}
    return (
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d1}",
            _seed_address(ledger, d1),
            evidence_id(d1, 2),
            f"{d1} addition",
            f"{d1} added value",
        ),
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d2}",
            _seed_address(ledger, d2),
            evidence_id(d2, 2),
            f"{d2} addition",
            f"{d2} added value",
        ),
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d2}-new",
            _extra_address(ledger),
            evidence_id(d2, 2),
            f"{d2} new rule",
            f"{d2} new value",
        ),
        _support(
            ledger, f"J-{ledger}-T2-support-{d3}", _seed_claim(ledger, d3), evidence_id(d3, 2)
        ),
        _assert(
            ledger,
            f"J-{ledger}-T2-claim-{d4}",
            _seed_address(ledger, d4),
            evidence_id(d4, 2),
            f"{d4} rule",
            f"{d4} second value",
        ),
        _supersede(ledger, _supersede_id(ledger), _seed_claim_id(ledger, d4), evidence_id(d4, 2)),
    )


def _script(*overrides: tuple[int, Batch], length: int = MAX_FRONTIER_CALLS) -> list[Batch]:
    """``length`` prescribed batches (eight by default), with ``(index, batch)`` overrides."""
    batches: list[Batch] = [_prescribed] * length
    for index, batch in overrides:
        batches[index] = batch
    return batches


# --- fixtures and helpers ---------------------------------------------------------------


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
    return {name: (out / name).read_bytes() for name in sorted(SEAL_ONLY)}


def _dir_snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _relative_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
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
) -> int:
    return entrypoint.main(
        [mode, "--frozen-sha", frozen_sha, "--out", str(out)],
        cwd=cwd,
        env=PoisonedEnv() if env is None else env,
        reasoner_factory=factory,
        git=git if git is not None else FakeGit(),
    )


def _gate_table(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {gate["name"]: gate for gate in document["gates"]}


def _failed_gates(document: dict[str, Any]) -> list[str]:
    return [gate["name"] for gate in document["gates"] if not gate["passed"]]


def _request_count(out: Path) -> int:
    return sum(len(_read_json(out / f"L-{ledger}/requests.json")["entries"]) for ledger in LEDGERS)


def _result(out: Path, ledger: str) -> dict[str, Any]:
    return _read_json(out / f"L-{ledger}/result.json")


def _all_artifact_text(out: Path) -> Iterator[tuple[str, str]]:
    for path in RAW_ARTIFACT_PATHS:
        file = out / path
        if file.exists():
            yield path, file.read_text(encoding="utf-8")


class LiveRun(NamedTuple):
    out: Path
    code: int
    factory: FakeFactory
    env: RecordingEnv
    git: FakeGit
    stdout: str
    seal_before: dict[str, bytes]


def _live_success_run(out: Path) -> LiveRun:
    seal_before = _seal_bytes(out)
    factory = FakeFactory(LocusFake(_script()))
    env = _live_env(UNRELATED=ENV_CANARY)
    git = FakeGit()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = _main("--live", out, env=env, factory=factory, git=git)
    return LiveRun(out, code, factory, env, git, buffer.getvalue(), seal_before)


@pytest.fixture(scope="module")
def live_success(tmp_path_factory: pytest.TempPathFactory) -> LiveRun:
    """One fake ``--live`` success (8 forwarded calls), shared read-only by the tests
    that inspect its tree."""
    out = _seal(tmp_path_factory.mktemp("live-success") / EXPERIMENT_ARTIFACT_DIR)
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        monkeypatch.delenv(API_KEY_ENV, raising=False)
        return _live_success_run(out)


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


def _answers_file(tmp_path: Path, answers: Any = None) -> Path:
    path = tmp_path / "answers.json"
    content = (
        {ledger: dict.fromkeys(SEMANTIC_ASSERTION_IDS, True) for ledger in LEDGERS}
        if answers is None
        else answers
    )
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return path


def _adjudicate(
    out_dir: Path,
    repo_root: Path,
    *,
    answers: Path,
    git: FakeGit,
    env: Mapping[str, str] | None = None,
    raw_run_sha: str = RAW_RUN_SHA,
) -> int:
    return adjudicate_entrypoint.main(
        [
            "--raw-run-sha",
            raw_run_sha,
            "--out",
            str(out_dir),
            "--answers",
            str(answers),
            "--notes",
            "scripted adjudication over the fake live run",
        ],
        cwd=repo_root,
        env={} if env is None else env,
        git=git,
    )


# =====================================================================================
# prepare
# =====================================================================================


def _prepare(out: Path, git: FakePrepareGit, *, cwd: Path = REPO_ROOT) -> int:
    return prepare_entrypoint.main(["--out", str(out)], cwd=cwd, git=git)


def test_prepare_seals_exactly_two_files_using_only_the_allowed_git_operations_in_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: prepare success -- the allowed git argv, in the brief's order, all
    before any write; exactly the two files; both canonical hashes printed; exit 0."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(), out=out)

    code = _prepare(out, git)

    assert code == 0
    assert git.argvs == _prepare_argvs()
    assert _relative_files(out) == SEAL_ONLY
    printed = dict(line.split(" ", 1) for line in capsys.readouterr().out.strip().splitlines())
    assert set(printed) == SEAL_ONLY
    for name, digest in printed.items():
        assert digest == canonical_sha256(_read_json(out / name))
    manifest = _read_json(out / "manifest.json")
    assert manifest["harness_code_sha"] == PREPARE_HEAD_SHA
    assert manifest["spec_sha256"] == hashlib.sha256(_spec_bytes()).hexdigest()
    assert manifest["experiment_version"] == EXPERIMENT_VERSION
    assert manifest["historical_preservation_base_sha"] == DESIGN_BASE_SHA
    assert manifest["baseline_sha"] == BASELINE_SHA
    assert manifest["predecessor_adjudication_sha"] == PREDECESSOR_ADJUDICATION_SHA
    assert len(manifest["raw_artifact_paths"]) == 21


def test_prepare_refuses_a_dirty_worktree_before_anything_else(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(dirty=" M src/foundry/x.py\n"), out=out)

    code = _prepare(out, git)

    assert code == 2
    assert git.argvs == [("status", "--porcelain")]
    assert not out.exists()
    assert "REFUSED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "missing_ancestor", [BASELINE_SHA, DESIGN_BASE_SHA, PREDECESSOR_ADJUDICATION_SHA]
)
def test_prepare_refuses_when_a_frozen_sha_is_not_an_ancestor_of_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing_ancestor: str
) -> None:
    """Matrix: non-ancestor x3 -- baseline, design base, predecessor adjudication."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(not_ancestors=frozenset({missing_ancestor})), out=out)

    code = _prepare(out, git)

    assert code == 2
    assert not out.exists()
    assert git.argvs[-1] == ("merge-base", "--is-ancestor", missing_ancestor, "HEAD")
    output = capsys.readouterr().out
    assert "REFUSED" in output and missing_ancestor in output


def test_prepare_refuses_when_working_tree_spec_differs_from_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: spec differs -- the sealed spec hash is the working-tree bytes, which
    must equal ``HEAD:<SPEC_PATH>``."""
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(committed_spec=_spec_bytes() + b"\n# drift\n"), out=out)

    code = _prepare(out, git)

    assert code == 2
    assert not out.exists()
    assert git.argvs[-1] == ("show", f"HEAD:{SPEC_PATH}")
    assert "spec" in capsys.readouterr().out


def test_prepare_refuses_when_the_spec_is_missing_from_the_working_tree(tmp_path: Path) -> None:
    elsewhere = tmp_path / "not-the-repo"
    elsewhere.mkdir()
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(), out=out)

    assert _prepare(out, git, cwd=elsewhere) == 2
    assert not out.exists()


def test_prepare_refuses_when_a_historical_tree_differs_at_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: one tree differs -- HEAD's tree must equal the design-base tree for
    every frozen directory; the base value is never taken from HEAD."""
    touched = HISTORICAL_ARTIFACT_DIRS[6]
    assert touched == PREDECESSOR_ARTIFACT_DIR
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
    """Matrix: prereg exists -- nothing written, the existing file untouched."""
    out = tmp_path / "experiment"
    out.mkdir()
    (out / existing).write_text("{}\n", encoding="utf-8")
    git = FakePrepareGit(_prepare_table())

    code = _prepare(out, git)

    assert code == 2
    assert _relative_files(out) == {existing}
    assert (out / existing).read_text(encoding="utf-8") == "{}\n"


def test_prepare_records_the_design_base_tree_values_never_heads(tmp_path: Path) -> None:
    out = tmp_path / "experiment"
    git = FakePrepareGit(_prepare_table(), out=out)

    assert _prepare(out, git) == 0

    sealed = _read_json(out / "manifest.json")["historical_artifact_tree_hashes"]
    assert set(sealed) == set(HISTORICAL_ARTIFACT_DIRS)
    for directory in HISTORICAL_ARTIFACT_DIRS:
        base_argv = ("rev-parse", f"{DESIGN_BASE_SHA}:{directory}")
        head_argv = ("rev-parse", f"HEAD:{directory}")
        assert base_argv in git.argvs and head_argv in git.argvs
        assert sealed[directory] == git.answers[base_argv].decode("utf-8").strip()
        assert sealed[directory] == TREE_HASHES[directory]
    assert _read_json(out / "manifest.json")["historical_artifact_dirs"] == list(
        HISTORICAL_ARTIFACT_DIRS
    )


def test_prepare_defaults_to_the_real_experiment_directory_which_no_scenario_touches() -> None:
    """The repaired tripwire: the parser default IS the real experiment directory; before
    the T10 seal that directory does not exist, and no scenario in this module creates
    or touches it (the autouse fixture re-checks after every test). Prepare is never run
    against the default here -- that would create it."""
    parser = prepare_entrypoint.build_parser()
    assert parser.parse_args([]).out == EXPERIMENT_ARTIFACT_DIR.rstrip("/")
    assert EXPERIMENT_ARTIFACT_DIR.rstrip("/") == prepare_entrypoint.DEFAULT_OUT
    assert _tree_digest(REAL_EXPERIMENT_DIR) == REAL_EXPERIMENT_DIGEST_AT_IMPORT


# =====================================================================================
# preflight-only (non-consuming)
# =====================================================================================


def test_preflight_only_passes_all_18_gates_writes_nothing_and_reads_no_key(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: preflight-only -- directory digest unchanged, ``env.reads`` is exactly
    the resolver, the factory untouched, 18 gates, ``frontier_calls`` 0, resolver
    verbatim; the real leakage gate and the real 18 gates."""
    before = _tree_digest(sealed)
    env = PoisonedEnv(resolver="native")
    git = FakeGit()

    code = _main("--preflight-only", sealed, env=env, git=git, factory=_poisoned_factory)

    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert set(document) == {
        "frozen_sha",
        "gates",
        "all_passed",
        "frontier_calls",
        "observed_grpc_dns_resolver",
    }
    assert document["all_passed"] is True
    assert document["frozen_sha"] == SEAL_SHA
    assert tuple(gate["name"] for gate in document["gates"]) == GATE_NAMES
    assert len(document["gates"]) == 18
    assert all(gate["passed"] for gate in document["gates"]), _failed_gates(document)
    assert document["frontier_calls"] == 0
    assert document["observed_grpc_dns_resolver"] == "native"
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _tree_digest(sealed) == before
    assert _relative_files(sealed) == SEAL_ONLY
    assert git.calls.count(("head",)) == 1
    assert ("dirty",) in git.calls
    assert ("is_ancestor", BASELINE_SHA, SEAL_SHA) in git.calls
    assert ("is_ancestor", DESIGN_BASE_SHA, SEAL_SHA) in git.calls
    assert ("is_ancestor", PREDECESSOR_RAW_RUN_SHA, SEAL_SHA) in git.calls
    assert ("is_ancestor", PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA) in git.calls
    for directory in HISTORICAL_ARTIFACT_DIRS:
        assert ("tree_sha", DESIGN_BASE_SHA, directory) in git.calls
        assert ("tree_sha", SEAL_SHA, directory) in git.calls
    assert str(sealed) in _gate_table(document)["no_raw_artifacts_exist"]["detail"]


@pytest.mark.parametrize("resolver", [None, "", "ares", "Native"])
def test_preflight_only_fails_only_gate_15_when_the_resolver_is_not_native(
    sealed: Path, capsys: pytest.CaptureFixture[str], resolver: str | None
) -> None:
    """Matrix: resolver variants fail only gate 15; still nothing written, no key."""
    before = _tree_digest(sealed)
    env = PoisonedEnv(resolver=resolver)

    code = _main("--preflight-only", sealed, env=env)

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    gates = _gate_table(document)
    assert gates["grpc_dns_resolver_is_native"]["passed"] is False
    assert repr(resolver) in gates["grpc_dns_resolver_is_native"]["detail"]
    assert _failed_gates(document) == ["grpc_dns_resolver_is_native"]
    assert document["observed_grpc_dns_resolver"] == resolver
    assert document["all_passed"] is False
    assert document["frontier_calls"] == 0
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _tree_digest(sealed) == before


def test_preflight_only_exits_3_on_dirty_tree_and_still_prints_the_document(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _tree_digest(sealed)

    code = _main("--preflight-only", sealed, git=FakeGit(dirty=" M src/foundry/x.py"))

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    assert document["all_passed"] is False
    assert document["frontier_calls"] == 0
    gates = _gate_table(document)
    assert gates["worktree_clean"]["passed"] is False
    assert "src/foundry/x.py" in gates["worktree_clean"]["detail"]
    assert _tree_digest(sealed) == before


def test_preflight_only_refuses_without_seal_files_or_with_an_unparsable_manifest(
    tmp_path: Path, sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "unsealed"
    out.mkdir()
    assert _main("--preflight-only", out) == 2
    assert _relative_files(out) == set()
    assert "REFUSED" in capsys.readouterr().out

    (sealed / "manifest.json").write_bytes(b"{not json")
    before = _tree_digest(sealed)
    assert _main("--preflight-only", sealed) == 2
    assert _tree_digest(sealed) == before
    assert "REFUSED" in capsys.readouterr().out

    (sealed / "manifest.json").write_bytes(b"[]\n")
    assert _main("--preflight-only", sealed) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_repeated_preflight_only_never_consumes_and_a_later_live_is_not_refused(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: repeated preflight-only does not consume -- run three times: no file
    appears; a subsequent ``--live`` is NOT refused for raw artifacts (gate 18 passes
    inside the live preflight and the run proceeds to the fake success)."""
    before = _tree_digest(sealed)
    for _ in range(3):
        env = PoisonedEnv()
        assert _main("--preflight-only", sealed, env=env) == 0
        assert json.loads(capsys.readouterr().out)["all_passed"] is True
        assert env.reads == [GRPC_DNS_RESOLVER_ENV]
        assert _tree_digest(sealed) == before
        assert _relative_files(sealed) == SEAL_ONLY

    factory = FakeFactory(LocusFake(_script()))
    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 0
    assert factory.calls == [KEY_CANARY]
    assert len(factory.fake.requests) == 8
    assert _relative_files(sealed) == FULL_TREE
    assert _gate_table(_read_json(sealed / "preflight.json"))["no_raw_artifacts_exist"]["passed"]


def test_one_historical_tree_differing_at_the_seal_fails_only_gate_16(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    touched = HISTORICAL_ARTIFACT_DIRS[4]
    git = FakeGit(trees=_equal_trees(differing=touched))

    code = _main("--preflight-only", sealed, git=git)

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    gates = _gate_table(document)
    assert _failed_gates(document) == ["historical_artifacts_unchanged"]
    assert touched in gates["historical_artifacts_unchanged"]["detail"]
    assert ("tree_sha", DESIGN_BASE_SHA, touched) in git.calls
    assert ("tree_sha", SEAL_SHA, touched) in git.calls


def test_gates_use_injected_git_results_not_hard_coded_success(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git = FakeGit(
        parents={SEAL_SHA: ("c" * 40,)},
        changed={
            (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            (PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA): (
                *CHANGES_SINCE_ADJUDICATION,
                f"{PREDECESSOR_ARTIFACT_DIR}verdicts.json",
            ),
        },
    )

    code = _main("--preflight-only", sealed, git=git)

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    gates = _gate_table(document)
    assert _failed_gates(document) == [
        "head_equals_final_seal",
        "predecessor_commits_unchanged",
    ]
    assert HARNESS_SHA in gates["head_equals_final_seal"]["detail"]
    assert (
        f"{PREDECESSOR_ARTIFACT_DIR}verdicts.json"
        in (gates["predecessor_commits_unchanged"]["detail"])
    )
    assert ("changed_paths", PREDECESSOR_ADJUDICATION_SHA, SEAL_SHA) in git.calls


def test_missing_request_path_file_fails_gate_13_without_fabrication(
    sealed: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The four request-path sources are read from the package directory; a missing one
    is passed as missing (never fabricated) so gate 13 fails on its own terms."""
    elsewhere = tmp_path / "not-the-package"
    elsewhere.mkdir()
    monkeypatch.setattr(entrypoint, "REQUEST_PATH_DIR", elsewhere)

    code = _main("--preflight-only", sealed)

    assert code == 3
    document = json.loads(capsys.readouterr().out)
    assert _failed_gates(document) == ["answer_key_not_imported_by_request_path"]
    detail = _gate_table(document)["answer_key_not_imported_by_request_path"]["detail"]
    assert "missing" in detail and "runner.py" in detail


def test_request_path_sources_are_the_real_four_package_files() -> None:
    package = REPO_ROOT / PACKAGE_DIR
    assert Path(entrypoint.REQUEST_PATH_DIR).resolve() == package.resolve()
    sources = entrypoint.request_path_sources()
    assert (
        set(sources)
        == set(REQUEST_PATH_MODULES)
        == {
            "corpus.py",
            "protocol.py",
            "recording.py",
            "runner.py",
        }
    )
    for name, text in sources.items():
        assert text == (package / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_sha", ["abc", "A" * 40, "g" * 40, "5" * 39, "5" * 41])
def test_frozen_sha_must_be_forty_lowercase_hex(sealed: Path, bad_sha: str) -> None:
    assert _main("--preflight-only", sealed, frozen_sha=bad_sha) == 2
    assert _relative_files(sealed) == SEAL_ONLY


def test_modes_are_mutually_exclusive_and_required(sealed: Path) -> None:
    argv_common = ["--frozen-sha", SEAL_SHA, "--out", str(sealed)]
    kwargs: dict[str, Any] = {
        "cwd": REPO_ROOT,
        "env": PoisonedEnv(),
        "reasoner_factory": _poisoned_factory,
        "git": FakeGit(),
    }

    assert entrypoint.main(argv_common, **kwargs) == 2
    assert entrypoint.main(["--preflight-only", "--live", *argv_common], **kwargs) == 2
    assert entrypoint.main(["--live", "--frozen-sha", SEAL_SHA], **kwargs) == 2
    assert _relative_files(sealed) == SEAL_ONLY


def test_entrypoint_never_sets_or_reads_the_resolver_from_os_environ_directly() -> None:
    """The CLI injects ``env.get("GRPC_DNS_RESOLVER")``; it never writes it and never
    bypasses the injected env. ``os.environ`` is only the injectable default."""
    source = Path(entrypoint.__file__).read_text(encoding="utf-8")
    assert "os.environ[" not in source
    assert "putenv" not in source
    assert "setdefault" not in source
    assert "getenv" not in source
    assert source.count("os.environ") == 1
    assert "GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation.py" in source
    assert "2026-09-15-locus-validation-v1" in source
    assert (entrypoint.EXIT_OK, entrypoint.EXIT_REFUSED) == (0, 2)
    assert (entrypoint.EXIT_PREFLIGHT_FAILED, entrypoint.EXIT_ABORTED) == (3, 4)
    assert entrypoint.API_KEY_ENV == API_KEY_ENV


# =====================================================================================
# live: nothing before consumption writes, reads the key early, or constructs
# =====================================================================================


def test_live_refuses_without_seal_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "unsealed"
    out.mkdir()

    assert _main("--live", out) == 2
    assert _relative_files(out) == set()
    assert "REFUSED" in capsys.readouterr().out


def test_live_failed_preflight_does_not_consume_then_a_repaired_tree_proceeds(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: failed preflight in ``--live`` does not consume -- dirty tree: exit 3,
    no files, key never read, factory never called; then fix the fake and the same
    seal proceeds to a live run (nothing was consumed)."""
    seal_before = _seal_bytes(sealed)
    env = PoisonedEnv()

    code = _main(
        "--live", sealed, env=env, factory=_poisoned_factory, git=FakeGit(dirty="?? scratch.txt")
    )

    assert code == 3
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _relative_files(sealed) == SEAL_ONLY
    out = capsys.readouterr().out
    assert "worktree_clean" in out and "scratch.txt" in out
    assert _seal_bytes(sealed) == seal_before

    factory = FakeFactory(LocusFake(_script()))
    code = _main("--live", sealed, env=_live_env(), factory=factory, git=FakeGit())

    assert code == 0
    assert factory.calls == [KEY_CANARY]
    assert _relative_files(sealed) == FULL_TREE
    assert _seal_bytes(sealed) == seal_before


def test_live_failed_ancestry_gates_stop_before_key_and_construction(sealed: Path) -> None:
    env = RecordingEnv({GRPC_DNS_RESOLVER_ENV: "native", API_KEY_ENV: KEY_CANARY})

    code = _main("--live", sealed, env=env, git=FakeGit(ancestors=frozenset()))

    assert code == 3
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _relative_files(sealed) == SEAL_ONLY


@pytest.mark.parametrize("resolver", [None, "", "ares", "Native"])
def test_live_with_a_non_native_resolver_fails_gate_15_before_key_and_construction(
    sealed: Path, capsys: pytest.CaptureFixture[str], resolver: str | None
) -> None:
    values = {API_KEY_ENV: KEY_CANARY, "UNRELATED": ENV_CANARY}
    if resolver is not None:
        values[GRPC_DNS_RESOLVER_ENV] = resolver
    env = RecordingEnv(values)

    code = _main("--live", sealed, env=env, factory=_poisoned_factory)

    assert code == 3
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _relative_files(sealed) == SEAL_ONLY
    out = capsys.readouterr().out
    assert "grpc_dns_resolver_is_native" in out
    assert KEY_CANARY not in out and ENV_CANARY not in out


@pytest.mark.parametrize("key", [None, ""])
def test_live_missing_or_empty_key_after_passed_preflight_does_not_consume(
    sealed: Path, capsys: pytest.CaptureFixture[str], key: str | None
) -> None:
    """Matrix: missing key does not consume -- the key is read exactly once, only after
    all 18 gates passed; ``REFUSED``, exit 2, nothing written, factory never called."""
    values = {GRPC_DNS_RESOLVER_ENV: "native", "UNRELATED": ENV_CANARY}
    if key is not None:
        values[API_KEY_ENV] = key
    env = RecordingEnv(values)
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=env, factory=_poisoned_factory)

    assert code == 2
    assert env.reads == [GRPC_DNS_RESOLVER_ENV, API_KEY_ENV]
    assert _relative_files(sealed) == SEAL_ONLY
    out = capsys.readouterr().out
    assert "REFUSED" in out and API_KEY_ENV in out
    assert ENV_CANARY not in out
    assert _seal_bytes(sealed) == seal_before


def test_live_construction_time_identity_drift_does_not_consume(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: a 9p2-v1 fake as the factory result -> ``REFUSED``, exit 2, no files,
    zero forwarded calls."""
    factory = FakeFactory(ContrastiveFake(_script()))
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 2
    assert factory.calls == [KEY_CANARY]
    assert factory.fake.requests == []
    assert _relative_files(sealed) == SEAL_ONLY
    out = capsys.readouterr().out
    assert "REFUSED" in out and "IdentityDrift" in out and CONTRASTIVE_POLICY_VERSION in out
    assert KEY_CANARY not in out
    assert _seal_bytes(sealed) == seal_before


def test_live_factory_failure_does_not_consume_and_is_redacted(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def _bootstrap_fails(*, api_key: str) -> Any:
        raise RuntimeError(f"client bootstrap failed for key {SECRET_SHAPED}")

    code = _main("--live", sealed, env=_live_env(), factory=_bootstrap_fails)

    assert code == 2
    assert _relative_files(sealed) == SEAL_ONLY
    out = capsys.readouterr().out
    assert "REFUSED" in out and "RuntimeError" in out
    assert SECRET_SHAPED not in out and KEY_CANARY not in out
    assert "[REDACTED]" in out


def test_live_consumes_immediately_before_the_first_provider_call_attempt(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix: live consumes immediately before the first provider-call attempt -- an
    observing fake asserts that at the moment of the first ``propose`` exactly
    ``consumption.json`` + ``preflight.json`` exist beside the seal and nothing else,
    and the consumption wrapper records that no call had been forwarded when the two
    files were written (order recorded)."""
    order: list[tuple[str, Any]] = []
    real_write_consumption = entrypoint.write_consumption

    def _observing_write_consumption(*args: Any, **kwargs: Any) -> tuple[Path, Path]:
        order.append(("before-consumption", _relative_files(sealed), len(fake.requests)))
        written = real_write_consumption(*args, **kwargs)
        order.append(("consumed", _relative_files(sealed), len(fake.requests)))
        return written

    def _first_call() -> None:
        order.append(("first-call", _relative_files(sealed), len(fake.requests)))

    monkeypatch.setattr(entrypoint, "write_consumption", _observing_write_consumption)
    fake = LocusFake(_script(), hooks={0: _first_call})
    factory = FakeFactory(fake)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 0
    assert [step for step, _, _ in order] == ["before-consumption", "consumed", "first-call"]
    assert order[0][1] == SEAL_ONLY and order[0][2] == 0
    assert order[1][1] == CONSUMED_ONLY and order[1][2] == 0
    # The first call has arrived (counted by the fake) but nothing else exists yet.
    assert order[2][1] == CONSUMED_ONLY and order[2][2] == 1
    assert _relative_files(sealed) == FULL_TREE


def test_live_hands_the_same_gate_tuple_to_consumption_and_verdicts(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate tuple written to ``preflight.json`` is the very object handed to
    ``integrity_verdicts``; the preflight is evaluated exactly once (HEAD read once)."""
    seen: list[Any] = []
    real_write_consumption = entrypoint.write_consumption
    real_integrity_verdicts = entrypoint.integrity_verdicts

    def _observing_write_consumption(*args: Any, **kwargs: Any) -> tuple[Path, Path]:
        seen.append(kwargs["gates"])
        return real_write_consumption(*args, **kwargs)

    def _observing_verdicts(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["preflight_gates"])
        return real_integrity_verdicts(*args, **kwargs)

    monkeypatch.setattr(entrypoint, "write_consumption", _observing_write_consumption)
    monkeypatch.setattr(entrypoint, "integrity_verdicts", _observing_verdicts)
    git = FakeGit()

    code = _main(
        "--live", sealed, env=_live_env(), factory=FakeFactory(LocusFake(_script())), git=git
    )

    assert code == 0
    assert len(seen) == 2 and seen[0] is seen[1]
    assert tuple(gate.name for gate in seen[0]) == GATE_NAMES
    assert git.calls.count(("head",)) == 1
    assert _read_json(sealed / "preflight.json")["gates"] == [
        gate.model_dump(mode="json") for gate in seen[0]
    ]


# =====================================================================================
# live: after consumption everything is recorded, written in full, never rerun
# =====================================================================================


def test_provider_failure_after_consumption_writes_the_full_tree_and_blocks_a_second_live(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: provider failure after consumption (scripted at call 3): exit 4, the
    full 21-path tree, alpha partial preserved, beta NOT_RUN, the raw outcome already
    inconclusive with ``case_outcomes`` null; a second ``--live`` is refused by
    ``no_raw_artifacts_exist`` (exit 3), the factory never called."""
    failure = XAIProviderError(f"provider rejected key {SECRET_SHAPED}")
    factory = FakeFactory(LocusFake(_script((2, failure))))
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert factory.calls == [KEY_CANARY]
    assert len(factory.fake.requests) == 3
    assert _relative_files(sealed) == FULL_TREE
    alpha, beta = _result(sealed, "alpha"), _result(sealed, "beta")
    assert alpha["status"] == "FAILED" and alpha["run_status"] == "ABORTED_PROVIDER"
    assert alpha["error"].startswith("XAIProviderError: provider rejected key ")
    assert SECRET_SHAPED not in alpha["error"] and "[REDACTED]" in alpha["error"]
    assert [d["t"] for d in alpha["deltas"]] == [1, 2]
    assert [d["request_count"] for d in alpha["deltas"]] == [2, 0]
    assert [d["completed"] for d in alpha["deltas"]] == [True, False]
    assert alpha["ledger_event_count"] > 0
    assert beta["status"] == "NOT_RUN" and beta["deltas"] == []
    assert beta["ledger_event_count"] == 0 and beta["request_count"] == 0
    assert _request_count(sealed) == 2
    assert _read_json(sealed / "measurements.json")["row_count"] == 2
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["phase"] == "raw"
    assert verdicts["status"] == "ABORTED_PROVIDER"
    assert verdicts["budget"]["frontier_calls"] == 3
    assert verdicts["experiment_outcome"] == INCONCLUSIVE
    assert verdicts["case_outcomes"] is None
    assert verdicts["semantic_assertions"] is None
    assert verdicts["semantic_notes"] is None
    assert set(verdicts["integrity"]) == {f"L{n}" for n in range(1, 10)}
    assert INCONCLUSIVE in (sealed / "report.md").read_text(encoding="utf-8")
    for path, text in _all_artifact_text(sealed):
        assert KEY_CANARY not in text, path
        assert SECRET_SHAPED not in text, path
    out = capsys.readouterr().out
    assert "ABORTED_PROVIDER" in out
    assert KEY_CANARY not in out and SECRET_SHAPED not in out
    assert _seal_bytes(sealed) == seal_before

    after_first = _dir_snapshot(sealed)
    git = FakeGit()
    code = _main("--live", sealed, env=PoisonedEnv(), factory=_poisoned_factory, git=git)

    assert code == 3
    assert _dir_snapshot(sealed) == after_first
    out = capsys.readouterr().out
    assert "no_raw_artifacts_exist" in out
    assert ("head",) in git.calls


def test_semantic_output_error_after_consumption_is_aborted_model_contract_with_no_rerun(
    sealed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: ``SemanticOutputError`` at call 6: alpha COMPLETED, beta FAILED at its
    seed Call 2, ``ABORTED_MODEL_CONTRACT``, exit 4, the full tree; no rerun."""
    factory = FakeFactory(LocusFake(_script((5, SemanticOutputError("OUTPUT_FAILURE_BETA")))))

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert len(factory.fake.requests) == 6
    assert _relative_files(sealed) == FULL_TREE
    alpha, beta = _result(sealed, "alpha"), _result(sealed, "beta")
    assert alpha["status"] == "COMPLETED" and alpha["replay"] is not None
    assert beta["status"] == "FAILED" and beta["run_status"] == "ABORTED_MODEL_CONTRACT"
    assert beta["error"] == "SemanticOutputError: OUTPUT_FAILURE_BETA"
    assert [d["request_count"] for d in beta["deltas"]] == [1]
    assert _request_count(sealed) == 5
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["status"] == "ABORTED_MODEL_CONTRACT"
    assert verdicts["budget"]["frontier_calls"] == 6
    assert verdicts["experiment_outcome"] == INCONCLUSIVE
    assert verdicts["case_outcomes"] is None
    assert "ABORTED_MODEL_CONTRACT" in capsys.readouterr().out

    after_first = _dir_snapshot(sealed)
    assert _main("--live", sealed, env=PoisonedEnv(), factory=_poisoned_factory) == 3
    assert _dir_snapshot(sealed) == after_first


def test_live_fake_success_makes_8_calls_completes_both_ledgers_and_writes_21_files(
    live_success: LiveRun,
) -> None:
    """Matrix: fake live success -- 8 calls, both ledgers COMPLETED, 21 raw files,
    semantic fields null, exit 0; zero judges / retries / authorizations."""
    out = live_success.out
    assert live_success.code == 0
    assert live_success.factory.calls == [KEY_CANARY]
    assert live_success.env.reads == [GRPC_DNS_RESOLVER_ENV, API_KEY_ENV]
    assert _relative_files(out) == FULL_TREE
    preflight = _read_json(out / "preflight.json")
    assert preflight["all_passed"] is True
    assert len(preflight["gates"]) == 18
    assert preflight["frontier_calls"] == 0
    assert preflight["observed_grpc_dns_resolver"] == "native"
    assert preflight["frozen_sha"] == SEAL_SHA
    assert preflight["harness_code_sha"] == HARNESS_SHA
    consumption = _read_json(out / "consumption.json")
    assert consumption["frozen_sha"] == SEAL_SHA
    assert consumption["harness_code_sha"] == HARNESS_SHA
    assert consumption["policy_version"] == LOCUS_POLICY_VERSION
    assert consumption["consumed_at"].endswith("+00:00")
    assert len(live_success.factory.fake.requests) == 8
    assert _request_count(out) == 8
    for ledger in LEDGERS:
        result = _result(out, ledger)
        assert result["status"] == "COMPLETED" and result["error"] is None
        assert result["run_status"] == "COMPLETED"
        assert [d["request_count"] for d in result["deltas"]] == [2, 2]
        assert result["receipt_count"] == 4
        assert result["replay"]["status"] == "REPLAY_MATCH"
    measurements = _read_json(out / "measurements.json")
    assert measurements["row_count"] == 8 and len(measurements["rows"]) == 8
    verdicts = _read_json(out / "verdicts.json")
    assert verdicts["phase"] == "raw"
    assert verdicts["status"] == "COMPLETED"
    assert verdicts["budget"] == {
        "frontier_calls": 8,
        "provider_cost_usd": "0.36",
        "judge_calls": 0,
        "human_authorizations": 0,
    }
    assert verdicts["semantic_assertions"] is None
    assert verdicts["semantic_notes"] is None
    assert verdicts["case_outcomes"] is None
    assert verdicts["experiment_outcome"] is None
    assert set(verdicts["integrity"]) == {f"L{n}" for n in range(1, 10)}
    assert all(v["passed"] is True for v in verdicts["integrity"].values()), verdicts["integrity"]
    assert all(v["failed_ledgers"] == [] for v in verdicts["integrity"].values())
    assert len(verdicts["case_assertions"]) == 12
    assert all(c["structural_passed"] is True for c in verdicts["case_assertions"])
    assert "architect adjudication pending" in (out / "report.md").read_text(encoding="utf-8")
    for path, text in _all_artifact_text(out):
        assert KEY_CANARY not in text, path
        assert ENV_CANARY not in text, path
    assert "COMPLETED" in live_success.stdout
    assert KEY_CANARY not in live_success.stdout and ENV_CANARY not in live_success.stdout
    assert _seal_bytes(out) == live_success.seal_before
    assert live_success.git.calls.count(("head",)) == 1


def test_raw_artifacts_make_a_second_live_impossible_even_after_a_success(
    live_success: LiveRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: the identity is consumed; gate 18 is the refusal (exit 3), the factory
    is never called, the key never read, the tree untouched."""
    after_first = _dir_snapshot(live_success.out)
    env = PoisonedEnv()

    code = _main("--live", live_success.out, env=env, factory=_poisoned_factory)

    assert code == 3
    assert env.reads == [GRPC_DNS_RESOLVER_ENV]
    assert _dir_snapshot(live_success.out) == after_first
    out = capsys.readouterr().out
    assert "no_raw_artifacts_exist" in out and "consumption.json" in out


def test_eight_call_ceiling_a_ninth_call_is_never_requested_or_forwarded(
    sealed: Path,
) -> None:
    """Matrix: a factory whose fake would answer a 9th call never receives it; with the
    scripted protocol the 9th call cannot even be requested: ``frontier_calls == 8``,
    the fake saw 8, zero judges / retries / authorizations recorded."""
    factory = FakeFactory(LocusFake(_script(length=MAX_FRONTIER_CALLS + 1)))

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 0
    assert len(factory.fake.requests) == 8 == MAX_FRONTIER_CALLS
    assert len(factory.fake.receipts) == 8
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["budget"]["frontier_calls"] == 8
    assert verdicts["budget"]["judge_calls"] == 0
    assert verdicts["budget"]["human_authorizations"] == 0
    assert verdicts["integrity"]["L2"]["passed"] is True
    assert verdicts["integrity"]["L6"]["passed"] is True
    assert verdicts["integrity"]["L8"]["passed"] is True
    assert _read_json(sealed / "measurements.json")["row_count"] == 8


def test_pending_model_supersede_is_never_applied(live_success: LiveRun) -> None:
    """Matrix: in the fake success the V05 supersede is routed ``REQUIRE_SECOND_LENS``
    and is absent from the applied judgment ids in ``L-*/ledger.json``; no supersession
    exists in either ledger's T2 state; ``human_authorizations == 0``."""
    out = live_success.out
    for ledger in LEDGERS:
        supersede = _supersede_id(ledger)
        decisions = _read_json(out / f"L-{ledger}/decisions.json")
        revision = decisions["deltas"][1]
        assert revision["t"] == 2
        assert revision["pending_supersede_judgment_ids"] == [supersede]
        call_two = revision["stage_decisions"][1]
        routes = {d["judgment_id"]: d["route"] for d in call_two}
        assert routes[supersede] == "REQUIRE_SECOND_LENS"
        assert [r for r in routes.values() if r != "APPLY"] == ["REQUIRE_SECOND_LENS"]
        events = _read_json(out / f"L-{ledger}/ledger.json")["events"]
        admissions = [
            e["event"]["payload"]
            for e in events
            if e["event"]["event_type"] == "SEMANTIC_ADMISSION_DECIDED"
        ]
        applied = {a["judgment_id"] for a in admissions if a["route"] == "APPLY"}
        assert supersede not in applied
        assert supersede in {a["judgment_id"] for a in admissions}
        state = _read_json(out / f"L-{ledger}/state_T2.json")
        assert state["present"] is True
        assert state["state"]["semantic"]["supersessions"] == []
        assert state["view"]["pending_judgment_ids"] == [supersede]
    assert _read_json(out / "verdicts.json")["budget"]["human_authorizations"] == 0
    assert _read_json(out / "verdicts.json")["integrity"]["L6"]["passed"] is True


def test_raw_preservation_failure_after_8_calls_exits_4_with_one_writer_attempt(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: the writer refuses after the run -- called exactly once, never again; no
    replacement run; ``consumption.json`` / ``preflight.json`` untouched; no other raw
    file; the secret never reaches the console; exit 4."""
    writer_calls: list[tuple[Path, Any, Any, Any]] = []
    consumed_bytes: dict[str, bytes] = {}

    def _refusing_writer(out_dir: Path, run: Any, verdicts: Any, case_results: Any) -> Any:
        writer_calls.append((out_dir, run, verdicts, case_results))
        consumed_bytes.update(
            {name: (out_dir / name).read_bytes() for name in ("consumption.json", "preflight.json")}
        )
        raise ValueError(f"secret-shaped token inside rendered_user_request {SECRET_SHAPED}")

    monkeypatch.setattr(entrypoint, "write_run_artifacts", _refusing_writer)
    factory = FakeFactory(LocusFake(_script()))
    seal_before = _seal_bytes(sealed)

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert factory.calls == [KEY_CANARY]
    assert len(factory.fake.requests) == 8
    assert len(writer_calls) == 1
    out_dir, run, verdicts, case_results = writer_calls[0]
    assert out_dir == sealed
    assert run.status is RunStatus.COMPLETED
    assert run.budget.frontier_calls == 8
    assert len(verdicts) == 9 and len(case_results) == 12
    assert _relative_files(sealed) == CONSUMED_ONLY
    for name, before in consumed_bytes.items():
        assert (sealed / name).read_bytes() == before
    assert _read_json(sealed / "preflight.json")["all_passed"] is True
    assert _seal_bytes(sealed) == seal_before
    captured = capsys.readouterr()
    assert "RAW ARTIFACT PRESERVATION FAILED" in captured.out
    assert "ValueError" in captured.out
    assert SECRET_SHAPED not in captured.out and SECRET_SHAPED not in captured.err
    assert KEY_CANARY not in captured.out and KEY_CANARY not in captured.err
    assert "[REDACTED]" in captured.out


def test_exception_escaping_the_runner_after_consumption_is_recorded_and_preserved(
    sealed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failure escaping the runner after consumption: recorded (never retried), the
    full tree written, both ledgers NOT_RUN, ``ABORTED_RUNTIME``, exit 4."""

    def _explode(**_kwargs: Any) -> Any:
        raise RuntimeError(f"session construction failed {SECRET_SHAPED}")

    monkeypatch.setattr(entrypoint, "run_experiment", _explode)
    factory = FakeFactory(LocusFake(_script()))

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    assert factory.fake.requests == []
    for ledger in LEDGERS:
        result = _result(sealed, ledger)
        assert result["status"] == "NOT_RUN" and result["run_status"] == "ABORTED_RUNTIME"
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["status"] == "ABORTED_RUNTIME"
    assert verdicts["error"].startswith("RuntimeError: session construction failed ")
    assert SECRET_SHAPED not in verdicts["error"] and "[REDACTED]" in verdicts["error"]
    assert verdicts["budget"]["frontier_calls"] == 0
    assert verdicts["experiment_outcome"] == INCONCLUSIVE
    out = capsys.readouterr().out
    assert "ABORTED_RUNTIME" in out and SECRET_SHAPED not in out


def test_interrupt_escaping_the_runner_after_consumption_is_preserved(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _interrupt(**_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(entrypoint, "run_experiment", _interrupt)

    code = _main("--live", sealed, env=_live_env(), factory=FakeFactory(LocusFake(_script())))

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["status"] == "ABORTED_RUNTIME"
    assert verdicts["error"] == "INTERRUPTED: KeyboardInterrupt"


def test_exception_escaping_the_runner_keeps_the_ledger_records_it_produced(
    sealed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner's ``progress`` records fill their ledgers; only the unreached ledger is
    NOT_RUN. The runner is made to raise OUTSIDE its catch site (while handing over the
    alpha record): four forwarded calls, alpha COMPLETED, beta NOT_RUN."""
    real_run = runner_module.run_experiment

    def _run_then_escape(**kwargs: Any) -> Any:
        original: list[Any] = kwargs["progress"]

        class _CutProgress(list[Any]):
            def append(self, record: Any) -> None:
                original.append(record)
                super().append(record)
                raise RuntimeError("escaped mid-walk")

        return real_run(**{**kwargs, "progress": _CutProgress()})

    monkeypatch.setattr(entrypoint, "run_experiment", _run_then_escape)
    factory = FakeFactory(LocusFake(_script()))

    code = _main("--live", sealed, env=_live_env(), factory=factory)

    assert code == 4
    assert _relative_files(sealed) == FULL_TREE
    assert len(factory.fake.requests) == 4
    alpha, beta = _result(sealed, "alpha"), _result(sealed, "beta")
    assert alpha["status"] == "COMPLETED" and alpha["request_count"] == 4
    assert alpha["replay"]["status"] == "REPLAY_MATCH"
    assert beta["status"] == "NOT_RUN"
    verdicts = _read_json(sealed / "verdicts.json")
    assert verdicts["status"] == "ABORTED_RUNTIME"
    assert verdicts["error"] == "RuntimeError: escaped mid-walk"
    assert verdicts["budget"]["frontier_calls"] == 4
    assert _request_count(sealed) == 4


@pytest.mark.parametrize(
    ("error", "status", "text"),
    [
        (
            XAIProviderError("PROVIDER_FAILURE"),
            RunStatus.ABORTED_PROVIDER,
            "XAIProviderError: PROVIDER_FAILURE",
        ),
        (
            SemanticOutputError("OUTPUT_FAILURE"),
            RunStatus.ABORTED_MODEL_CONTRACT,
            "SemanticOutputError: OUTPUT_FAILURE",
        ),
        (
            ReferenceSnapshotMismatch("SNAPSHOT_FAILURE"),
            RunStatus.ABORTED_MODEL_CONTRACT,
            "ReferenceSnapshotMismatch: SNAPSHOT_FAILURE",
        ),
        (
            BudgetExceeded("FRONTIER_CEILING", "scripted"),
            RunStatus.ABORTED_BUDGET,
            "BudgetExceeded: FRONTIER_CEILING: scripted",
        ),
        (
            IdentityDrift("IDENTITY_DRIFT: scripted"),
            RunStatus.ABORTED_IDENTITY,
            "IdentityDrift: IDENTITY_DRIFT: scripted",
        ),
        (
            RuntimeError(f"runtime {SECRET_SHAPED}"),
            RunStatus.ABORTED_RUNTIME,
            "RuntimeError: runtime [REDACTED]",
        ),
        (KeyboardInterrupt(), RunStatus.ABORTED_RUNTIME, "INTERRUPTED: KeyboardInterrupt"),
    ],
)
def test_aborted_result_fills_unreached_ledgers_and_classifies_as_the_runner_does(
    error: BaseException, status: RunStatus, text: str
) -> None:
    """``_aborted_result`` over one captured ledger: alpha kept as recorded, beta
    NOT_RUN, the status classified exactly as the runner classifies, the budget as it
    stood, the error text redacted."""
    fake = LocusFake(_script())
    budget = ExperimentBudget()
    progress: list[LedgerRecord] = []
    ticks = count(1)
    real = runner_module.run_experiment(
        inner=fake,
        budget=budget,
        clock=lambda: T0,
        id_factory=lambda prefix: f"{prefix}-{next(ticks)}",
        progress=progress,
    )
    assert real.status is RunStatus.COMPLETED

    run = entrypoint._aborted_result(progress[:1], budget, error)

    assert isinstance(run, RunResult)
    assert run.status is status
    assert run.error == text
    assert run.ledgers[0] == progress[0]
    assert run.ledgers[0].status == "COMPLETED"
    beta = run.ledgers[1]
    assert beta.ledger == "beta" and beta.status == "NOT_RUN" and beta.error is None
    assert beta.project_id == PROJECT_IDS["beta"] and beta.scope == SCOPES["beta"]
    assert beta.deltas == () and beta.ledger_events == ()
    assert beta.final_state is None and beta.final_view is None and beta.replay is None
    assert run.budget == budget.snapshot()
    assert run.budget.frontier_calls == 8

    empty = entrypoint._aborted_result([], ExperimentBudget(), RuntimeError("nothing ran"))
    assert [record.status for record in empty.ledgers] == ["NOT_RUN", "NOT_RUN"]
    assert [record.ledger for record in empty.ledgers] == list(LEDGERS)
    assert empty.budget.frontier_calls == 0


def test_manifest_and_expectations_bytes_are_unchanged_across_every_mode(
    tmp_path: Path, live_success: LiveRun
) -> None:
    """Matrix: manifest / expectations bytes unchanged across every mode -- passed and
    failed preflight-only, failed live preflight, missing key, identity drift, provider
    abort and the fake success."""
    assert _seal_bytes(live_success.out) == live_success.seal_before
    scenarios: list[tuple[str, Callable[[Path], int], int]] = [
        ("preflight-only-pass", lambda out: _main("--preflight-only", out), 0),
        (
            "preflight-only-fail",
            lambda out: _main("--preflight-only", out, git=FakeGit(dirty=" M x")),
            3,
        ),
        ("live-preflight-fail", lambda out: _main("--live", out, git=FakeGit(dirty=" M x")), 3),
        (
            "live-missing-key",
            lambda out: _main("--live", out, env=RecordingEnv({GRPC_DNS_RESOLVER_ENV: "native"})),
            2,
        ),
        (
            "live-identity-drift",
            lambda out: _main(
                "--live", out, env=_live_env(), factory=FakeFactory(ContrastiveFake(_script()))
            ),
            2,
        ),
        (
            "live-provider-abort",
            lambda out: _main(
                "--live",
                out,
                env=_live_env(),
                factory=FakeFactory(LocusFake(_script((0, XAIProviderError("opaque"))))),
            ),
            4,
        ),
    ]
    for name, scenario, expected in scenarios:
        out = _seal(tmp_path / name)
        before = _seal_bytes(out)
        with contextlib.redirect_stdout(io.StringIO()):
            code = scenario(out)
        assert code == expected, name
        assert _seal_bytes(out) == before, name


# =====================================================================================
# adjudication after the raw freeze
# =====================================================================================


def test_adjudicate_end_to_end_on_the_fake_success_tree(
    live_success: LiveRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: the raw tree of the fake live success loaded into a FakeGit at a raw
    commit (clean, every file shown byte-identical), adjudicated with all-True answers
    -> validated, the outcome printed, only ``verdicts.json`` and ``report.md`` changed;
    a second adjudication is refused (write-once)."""
    out_dir = _copy_tree(live_success.out, tmp_path)
    git = _committed(out_dir, tmp_path)
    before = _dir_snapshot(out_dir)
    assert set(before) == FULL_TREE

    code = _adjudicate(out_dir, tmp_path, answers=_answers_file(tmp_path), git=git)
    after = _dir_snapshot(out_dir)

    assert code == 0
    assert f"experiment_outcome = {VALIDATED}" in capsys.readouterr().out
    assert set(after) == set(before)
    assert {name for name in before if before[name] != after[name]} == {
        "verdicts.json",
        "report.md",
    }
    verdicts = _read_json(out_dir / "verdicts.json")
    assert verdicts["phase"] == "adjudicated"
    assert verdicts["raw_run_commit_sha"] == RAW_RUN_SHA
    assert verdicts["experiment_outcome"] == VALIDATED
    assert verdicts["rule_zero"] is False
    assert len(verdicts["case_outcomes"]) == 12
    assert all(c["passed"] is True for c in verdicts["case_outcomes"])
    assert verdicts["semantic_assertions"] == {
        ledger: dict.fromkeys(SEMANTIC_ASSERTION_IDS, True) for ledger in LEDGERS
    }
    assert verdicts["semantic_notes"] == "scripted adjudication over the fake live run"
    assert f"experiment_outcome = {VALIDATED}" in (out_dir / "report.md").read_text("utf-8")
    shown = {call[2] for call in git.calls if call[0] == "show_bytes"}
    assert shown == {f"{EXPERIMENT_ARTIFACT_DIR}{name}" for name in RAW_ARTIFACT_PATHS}

    second = _adjudicate(
        out_dir, tmp_path, answers=_answers_file(tmp_path), git=_committed(out_dir, tmp_path)
    )
    assert second == 2
    assert "REFUSED" in capsys.readouterr().out
    assert _dir_snapshot(out_dir) == after
    # A consumed identity stays consumed: the adjudicated tree still refuses --live.
    assert _main("--live", out_dir, env=PoisonedEnv(), factory=_poisoned_factory) == 3
    assert _dir_snapshot(out_dir) == after


def test_adjudicate_refuses_when_the_provider_key_is_present_before_anything_else(
    live_success: LiveRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: ``XAI_API_KEY`` present in env -> refused by name (its value never read),
    before git is consulted or the answers file is opened; nothing written."""
    out_dir = _copy_tree(live_success.out, tmp_path)
    git = _committed(out_dir, tmp_path)
    before = _dir_snapshot(out_dir)

    code = _adjudicate(
        out_dir, tmp_path, answers=tmp_path / "never-opened.json", git=git, env=KeyPresentEnv()
    )

    assert code == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and API_KEY_ENV in out
    assert git.calls == []
    assert _dir_snapshot(out_dir) == before


def test_adjudicate_refuses_when_head_moved_or_the_tree_is_dirty_or_differs(
    live_success: LiveRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matrix: HEAD moved -> refused; a dirty worktree and a differing raw byte too."""
    out_dir = _copy_tree(live_success.out, tmp_path)
    before = _dir_snapshot(out_dir)
    answers = _answers_file(tmp_path)

    assert _adjudicate(out_dir, tmp_path, answers=answers, git=FakeGit(head=SEAL_SHA)) == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "HEAD" in out
    assert _dir_snapshot(out_dir) == before

    dirty = _committed(out_dir, tmp_path, dirty=" M something")
    assert _adjudicate(out_dir, tmp_path, answers=answers, git=dirty) == 2
    assert "dirty" in capsys.readouterr().out
    assert _dir_snapshot(out_dir) == before

    git = _committed(out_dir, tmp_path)
    (out_dir / "L-alpha/ledger.json").write_text("{}\n", encoding="utf-8")
    assert _adjudicate(out_dir, tmp_path, answers=answers, git=git) == 2
    assert "differs" in capsys.readouterr().out
    assert (out_dir / "verdicts.json").read_bytes() == before["verdicts.json"]
    assert (out_dir / "report.md").read_bytes() == before["report.md"]


def test_adjudicate_refuses_malformed_arguments_and_answers(
    live_success: LiveRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = _copy_tree(live_success.out, tmp_path)
    before = _dir_snapshot(out_dir)
    git = _committed(out_dir, tmp_path)

    assert _adjudicate(out_dir, tmp_path, answers=tmp_path / "missing.json", git=git) == 2
    assert "REFUSED" in capsys.readouterr().out

    only_alpha = _answers_file(tmp_path, {"alpha": dict.fromkeys(SEMANTIC_ASSERTION_IDS, True)})
    assert _adjudicate(out_dir, tmp_path, answers=only_alpha, git=git) == 2
    assert "beta" in capsys.readouterr().out

    stringly = _answers_file(
        tmp_path,
        {
            ledger: {id_: ("yes" if id_ == "A-V01" else True) for id_ in SEMANTIC_ASSERTION_IDS}
            for ledger in LEDGERS
        },
    )
    assert _adjudicate(out_dir, tmp_path, answers=stringly, git=git) == 2
    assert "REFUSED" in capsys.readouterr().out

    not_an_object = tmp_path / "list.json"
    not_an_object.write_text("[]\n", encoding="utf-8")
    assert _adjudicate(out_dir, tmp_path, answers=not_an_object, git=git) == 2

    bad_sha = _adjudicate(
        out_dir, tmp_path, answers=_answers_file(tmp_path), git=git, raw_run_sha="abc"
    )
    assert bad_sha == 2
    assert _dir_snapshot(out_dir) == before


# =====================================================================================
# default factory shape and public-surface discipline
# =====================================================================================


def test_default_factory_constructs_the_locus_reasoner_with_the_frozen_model_and_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The class name is monkeypatched: construction arguments are proved and the real
    adapter is never constructed."""
    constructed: list[dict[str, Any]] = []

    class FakeLocus:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append(kwargs)

    monkeypatch.setattr(entrypoint, "XAILocusSemanticReasoner", FakeLocus)

    reasoner = entrypoint.default_reasoner_factory(api_key="opaque-key")

    assert isinstance(reasoner, FakeLocus)
    assert constructed == [
        {"api_key": "opaque-key", "model": "grok-4.6", "reasoning_effort": "high"}
    ]
    assert (MODEL, REASONING_EFFORT) == ("grok-4.6", "high")


def test_scripts_import_only_public_names_from_the_experiment_package() -> None:
    """Clarification 7: no ``_``-prefixed name is imported from any package module."""
    for module in (entrypoint, prepare_entrypoint, adjudicate_entrypoint):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "foundry.experiments"
            ):
                private = [alias.name for alias in node.names if alias.name.startswith("_")]
                assert not private, (module.__name__, private)


def test_scripts_construct_no_adapter_and_read_no_key_outside_the_declared_points() -> None:
    """``XAILocusSemanticReasoner(`` appears exactly once in the run script (inside the
    default factory) and never in the other two; the adjudication script never reads a
    key value (presence check only)."""
    run_source = Path(entrypoint.__file__).read_text(encoding="utf-8")
    assert run_source.count("XAILocusSemanticReasoner(") == 1
    for module in (prepare_entrypoint, adjudicate_entrypoint):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "XAILocusSemanticReasoner(" not in source
        assert "XAISemanticReasoner" not in source
    adjudicate_source = Path(adjudicate_entrypoint.__file__).read_text(encoding="utf-8")
    assert "getenv" not in adjudicate_source
    assert "os.environ[" not in adjudicate_source
    assert 'env.get("XAI_API_KEY")' not in adjudicate_source
    assert 'env["XAI_API_KEY"]' not in adjudicate_source
    prepare_source = Path(prepare_entrypoint.__file__).read_text(encoding="utf-8")
    assert "XAI_API_KEY" not in prepare_source
    assert "os.environ" not in prepare_source
