"""Manifest, preregistration, consumption, the write-once raw tree and the guarded
adjudication writer (T7).

Spec §10 (consumption is one atomic write; nothing raw exists without it), §11 (the raw
writer fills only deterministic facts; adjudication changes only ``verdicts.json`` and
``report.md``), §13 (21 raw paths, write-once, secret-scanned), §14 (scoring at
adjudication only) and §16 (preregistration contents).

No provider, no network, no key: runs come from the T3 runner over scripted locus
doubles; verdicts and case results are the real T5/T4 functions; git is a table. The
real adapter classes are never constructed; sockets are blocked for the module.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_locus_validation_integrity import (
    HARNESS_SHA,
    SEAL_SHA,
    TREE_HASHES,
    FakeGit,
    _sources,
)
from test_locus_validation_runner import LocusFake, _run, _script

from foundry.adapters.semantics.xai_reasoner import (
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
    SEMANTIC_OUTPUT_SCHEMA_SHA256,
    SemanticReasoningReceipt,
    XAIProviderError,
)
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256
from foundry.experiments.contrastive_unseen.integrity import GateResult, all_passed
from foundry.experiments.locus_validation import artifacts as artifacts_module
from foundry.experiments.locus_validation.artifacts import (
    CONSUMPTION_PATHS,
    FINAL_SEAL_RULE,
    RAW_ARTIFACT_PATHS,
    SPEC_PATH,
    Adjudication,
    AdjudicationRefused,
    Ceilings,
    ConsumptionRefused,
    ExperimentManifest,
    build_manifest,
    existing_raw_artifacts,
    render_report,
    verdicts_document,
    write_adjudication,
    write_consumption,
    write_preregistration,
    write_run_artifacts,
)
from foundry.experiments.locus_validation.corpus import (
    DOCUMENTS,
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    Ledger,
    corpus_sha256,
    evidence_records,
)
from foundry.experiments.locus_validation.evaluation import CaseResult, evaluate_run
from foundry.experiments.locus_validation.expectations import (
    CASE_IDS,
    SEMANTIC_ASSERTION_IDS,
    expectations_document,
)
from foundry.experiments.locus_validation.integrity import (
    GATE_NAMES,
    LOCKED_CEILINGS,
    RAW_ARTIFACT_PATH_COUNT,
    REQUIRED_MANIFEST_KEYS,
    VERDICT_IDS,
    IntegrityVerdict,
    integrity_verdicts,
    preflight,
)
from foundry.experiments.locus_validation.leakage import (
    LeakageResult,
    needle_set_sha256,
    run_leakage_gate,
)
from foundry.experiments.locus_validation.protocol import (
    ARTIFACT_FORMAT_VERSION,
    BASELINE_SHA,
    CEILING_KEYS,
    DESIGN_BASE_SHA,
    EXPERIMENT_ARTIFACT_DIR,
    EXPERIMENT_VERSION,
    GRPC_DNS_RESOLVER_FROZEN,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PROMPT_SHA256S,
    MODEL,
    OUTPUT_SCHEMA_SHA256_FROZEN,
    POLICY_VERSION_FROZEN,
    PREDECESSOR_ADJUDICATION_SHA,
    PREDECESSOR_RAW_RUN_SHA,
    PROMPT_SHA256_FROZEN,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.runner import RunResult, RunStatus
from foundry.experiments.longitudinal.artifacts import contains_secret_shape
from foundry.ports.semantic_reasoner import ReasoningRequest

ARTIFACTS_SOURCE = Path("src/foundry/experiments/locus_validation/artifacts.py").read_text(
    encoding="utf-8"
)
RAW_RUN_SHA = "d" * 40
CONSUMED_AT = datetime(2026, 9, 16, 12, 30, 45, tzinfo=UTC)
SECRET = "api_key=sk-abcdefghijklmnop"
BEARER = "bearer abcdefghijklmnop"
EXPECTED_RAW_PATHS = (
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
RAW_WRITER_FUNCTIONS = {
    "write_consumption",
    "write_run_artifacts",
    "verdicts_document",
    "render_report",
}
PENDING_LINE = "experiment_outcome = null (architect adjudication pending)"
INCONCLUSIVE = "EXPERIMENT_INCONCLUSIVE"
VALIDATED = "LOCUS_POLICY_" + "VALIDATED"
NOT_VALIDATED = "LOCUS_POLICY_NOT_" + "VALIDATED"


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


# --- fakes ------------------------------------------------------------------------


class MeasuredFake(LocusFake):
    """A locus fake that, like the adapter, appends one full receipt and one draft
    payload per ANSWERED call (a raised call leaves neither)."""

    def __init__(self, batches: list[Any]) -> None:
        super().__init__(batches)
        self._receipts: list[SemanticReasoningReceipt] = []
        self._payloads: list[dict[str, Any]] = []

    @property
    def receipts(self) -> tuple[SemanticReasoningReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._payloads)

    def propose(self, request: ReasoningRequest) -> Any:
        result = super().propose(request)
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


class CommittedGit(FakeGit):
    """The integrity FakeGit with ``show_bytes`` keyed by ``(sha, repo-relative path)``."""

    def __init__(self, *, head: str, show: dict[tuple[str, str], bytes], dirty: str = "") -> None:
        super().__init__(head=head, dirty=dirty)
        self._show = show

    def show_bytes(self, sha: str, path: str) -> bytes:
        self.calls.append(("show_bytes", sha, path))
        return self._show[(sha, path)]


class PoisonedEnv(Mapping[str, str]):
    """An environment that carries the provider key NAME; reading its value is a
    test failure (presence-only law)."""

    def __contains__(self, key: object) -> bool:
        return key == "XAI_API_KEY"

    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"environment value {key!r} was read")

    def __iter__(self) -> Iterator[str]:
        return iter(("XAI_API_KEY",))

    def __len__(self) -> int:
        return 1


# --- fixtures ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def leakage_ok() -> LeakageResult:
    result = run_leakage_gate()
    assert result.passed
    return result


@pytest.fixture(scope="module")
def completed() -> Iterator[RunResult]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        result, _budget = _run(MeasuredFake(_script()))
        assert result.status is RunStatus.COMPLETED
        yield result


@pytest.fixture(scope="module")
def aborted() -> Iterator[RunResult]:
    """Provider failure at the third call: alpha FAILED at T2 call 1, beta NOT_RUN."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        result, _budget = _run(MeasuredFake(_script((2, XAIProviderError("PROVIDER_FAILURE")))))
        assert result.status is RunStatus.ABORTED_PROVIDER
        assert [record.status for record in result.ledgers] == ["FAILED", "NOT_RUN"]
        yield result


@pytest.fixture(scope="module")
def bare() -> Iterator[RunResult]:
    """A completed run whose inner reasoner exposes no receipts and no payloads."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        result, _budget = _run(LocusFake(_script()))
        assert result.status is RunStatus.COMPLETED
        yield result


@pytest.fixture(scope="module")
def manifest() -> ExperimentManifest:
    return _manifest()


# --- builders ---------------------------------------------------------------------


def _spec_sha256() -> str:
    return hashlib.sha256(Path(SPEC_PATH).read_bytes()).hexdigest()


def _manifest(tree_hashes: Mapping[str, str] | None = None) -> ExperimentManifest:
    return build_manifest(
        harness_code_sha=HARNESS_SHA,
        spec_sha256=_spec_sha256(),
        historical_tree_hashes=tree_hashes if tree_hashes is not None else TREE_HASHES,
    )


def _gates(*, failing: str | None = None, detail: str = "ok") -> tuple[GateResult, ...]:
    return tuple(
        GateResult(name=name, passed=name != failing, detail=detail) for name in GATE_NAMES
    )


def _relative_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _tree_digest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def _consume(
    out_dir: Path,
    leakage: LeakageResult,
    *,
    gates: tuple[GateResult, ...] | None = None,
    observed: str | None = "native",
    consumed_at: datetime = CONSUMED_AT,
) -> tuple[Path, Path]:
    return write_consumption(
        out_dir,
        gates=gates if gates is not None else _gates(),
        frozen_sha=SEAL_SHA,
        harness_code_sha=HARNESS_SHA,
        leakage=leakage,
        observed_grpc_dns_resolver=observed,
        consumed_at=consumed_at,
    )


def _verdicts(
    run: RunResult, cases: tuple[CaseResult, ...], gates: tuple[GateResult, ...] | None = None
) -> tuple[IntegrityVerdict, ...]:
    return integrity_verdicts(
        run, preflight_gates=gates if gates is not None else _gates(), case_results=cases
    )


def _write_raw(
    out_dir: Path,
    run: RunResult,
    leakage: LeakageResult,
    *,
    cases: tuple[CaseResult, ...] | None = None,
    verdicts: tuple[IntegrityVerdict, ...] | None = None,
) -> tuple[str, ...]:
    _consume(out_dir, leakage)
    cases = cases if cases is not None else evaluate_run(run)
    verdicts = verdicts if verdicts is not None else _verdicts(run, cases)
    return write_run_artifacts(out_dir, run, verdicts, cases)


def _commit(out_dir: Path, repo_root: Path, sha: str = RAW_RUN_SHA) -> CommittedGit:
    """A fake raw-run commit: HEAD is ``sha`` and every raw path shows the on-disk bytes."""
    show = {
        (sha, (out_dir / name).relative_to(repo_root).as_posix()): (out_dir / name).read_bytes()
        for name in RAW_ARTIFACT_PATHS
    }
    return CommittedGit(head=sha, show=show)


def _answers(**overrides: dict[str, bool]) -> dict[str, dict[str, bool]]:
    answers: dict[str, dict[str, bool]] = {
        ledger: dict.fromkeys(SEMANTIC_ASSERTION_IDS, True) for ledger in LEDGERS
    }
    for ledger, values in overrides.items():
        answers[ledger] = {**answers[ledger], **values}
    return answers


def _adjudication(**overrides: Any) -> Adjudication:
    fields: dict[str, Any] = {
        "semantic_answers": _answers(),
        "notes": "scripted adjudication | with a pipe\nand a newline",
    }
    fields.update(overrides)
    return Adjudication(**fields)


def _adjudicate(
    out_dir: Path,
    repo_root: Path,
    *,
    adjudication: Adjudication | None = None,
    git: CommittedGit | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    return write_adjudication(
        out_dir,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=git if git is not None else _commit(out_dir, repo_root),
        adjudication=adjudication if adjudication is not None else _adjudication(),
        repo_root=repo_root,
        env=env if env is not None else {},
    )


def _with_verdict(
    verdicts: tuple[IntegrityVerdict, ...], verdict_id: str, **fields: Any
) -> tuple[IntegrityVerdict, ...]:
    return tuple(v.model_copy(update=fields) if v.id == verdict_id else v for v in verdicts)


def _with_case(
    cases: tuple[CaseResult, ...], ledger: Ledger, case_id: str, **fields: Any
) -> tuple[CaseResult, ...]:
    return tuple(
        c.model_copy(update=fields) if (c.ledger, c.case_id) == (ledger, case_id) else c
        for c in cases
    )


def _module_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(ARTIFACTS_SOURCE)
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _functions_referencing(name: str) -> set[str]:
    found: set[str] = set()
    for function_name, node in _module_functions().items():
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id == name:
                found.add(function_name)
            if isinstance(inner, ast.Attribute) and inner.attr == name:
                found.add(function_name)
    return found


def _transitive_callees(roots: set[str]) -> set[str]:
    """Every module-level function reachable from ``roots`` by direct calls."""
    functions = _module_functions()
    seen: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        for inner in ast.walk(functions[name]):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                pending.append(inner.func.id)
    return seen


# --- manifest ---------------------------------------------------------------------


def test_manifest_canonical_hash_is_stable_across_tree_hash_insertion_order() -> None:
    forward = _manifest(dict(TREE_HASHES))
    backward = _manifest(dict(reversed(list(TREE_HASHES.items()))))

    assert canonical_sha256(forward) == canonical_sha256(backward)
    assert tuple(forward.historical_artifact_tree_hashes) == HISTORICAL_ARTIFACT_DIRS
    assert tuple(backward.historical_artifact_tree_hashes) == HISTORICAL_ARTIFACT_DIRS


def test_manifest_hashes_and_evidence_come_from_corpus_leakage_and_expectations(
    manifest: ExperimentManifest,
) -> None:
    assert manifest.expectations_sha256 == canonical_sha256(expectations_document())
    assert manifest.corpus_sha256 == corpus_sha256()
    assert manifest.leakage_needle_set_sha256 == needle_set_sha256()
    assert manifest.evidence == evidence_records()
    assert len(manifest.evidence) == 16


def test_manifest_identity_fields_are_the_frozen_literals(manifest: ExperimentManifest) -> None:
    assert manifest.experiment_version == EXPERIMENT_VERSION
    assert manifest.artifact_format_version == ARTIFACT_FORMAT_VERSION == 1
    assert manifest.harness_code_sha == HARNESS_SHA
    assert manifest.baseline_sha == BASELINE_SHA
    assert manifest.final_seal_rule == FINAL_SEAL_RULE
    assert FINAL_SEAL_RULE == (
        "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; "
        "parent..HEAD may add only manifest.json and expectations.json"
    )
    assert manifest.spec_path == SPEC_PATH
    assert SPEC_PATH == "docs/superpowers/specs/2026-09-15-locus-policy-live-validation-design.md"
    assert manifest.spec_sha256 == _spec_sha256()
    assert (manifest.provider, manifest.model, manifest.reasoning_effort) == (
        PROVIDER,
        MODEL,
        REASONING_EFFORT,
    )
    assert manifest.grpc_dns_resolver == GRPC_DNS_RESOLVER_FROZEN == "native"
    assert manifest.policy_version == POLICY_VERSION_FROZEN == LOCUS_POLICY_VERSION
    assert manifest.prompt_sha256 == PROMPT_SHA256_FROZEN == LOCUS_SYSTEM_INSTRUCTION_SHA256
    assert manifest.historical_prompt_sha256s == HISTORICAL_PROMPT_SHA256S
    assert manifest.output_schema_sha256 == OUTPUT_SCHEMA_SHA256_FROZEN
    assert manifest.output_schema_sha256 == SEMANTIC_OUTPUT_SCHEMA_SHA256
    assert manifest.calls_per_delta == 2
    assert [spec.id for spec in manifest.ledgers] == list(LEDGERS)
    for spec in manifest.ledgers:
        assert spec.project_id == PROJECT_IDS[spec.id]
        assert spec.scope == SCOPES[spec.id]
        assert spec.documents == DOCUMENTS[spec.id]
    assert manifest.ceilings.model_dump(mode="json") == LOCKED_CEILINGS
    assert manifest.ceilings.max_provider_cost_usd == 2.0
    assert manifest.ceilings.max_frontier_calls == 8
    assert manifest.historical_preservation_base_sha == DESIGN_BASE_SHA
    assert manifest.historical_artifact_dirs == HISTORICAL_ARTIFACT_DIRS
    assert len(manifest.historical_artifact_dirs) == 7
    assert manifest.historical_artifact_tree_hashes == TREE_HASHES
    assert manifest.predecessor_raw_run_sha == PREDECESSOR_RAW_RUN_SHA
    assert manifest.predecessor_adjudication_sha == PREDECESSOR_ADJUDICATION_SHA
    assert manifest.raw_artifact_paths == RAW_ARTIFACT_PATHS


def test_manifest_fields_cover_every_gate_read_key_and_ceilings_are_numbers() -> None:
    fields = set(ExperimentManifest.model_fields)
    assert set(REQUIRED_MANIFEST_KEYS) <= fields
    assert {
        "experiment_version",
        "artifact_format_version",
        "baseline_sha",
        "final_seal_rule",
        "spec_path",
        "spec_sha256",
        "ledgers",
        "historical_artifact_dirs",
    } <= fields
    assert tuple(Ceilings.model_fields) == CEILING_KEYS
    dumped = _manifest().model_dump(mode="json")
    for key in CEILING_KEYS:
        assert isinstance(dumped["ceilings"][key], int | float)
        assert not isinstance(dumped["ceilings"][key], bool)
    assert dumped["ceilings"] == LOCKED_CEILINGS


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda h: {k: v for k, v in h.items() if k != HISTORICAL_ARTIFACT_DIRS[0]}, "missing"),
        (lambda h: {**h, "docs/superpowers/experiments/other/": "e" * 40}, "unexpected"),
        (lambda h: {**h, HISTORICAL_ARTIFACT_DIRS[3]: "not-a-sha"}, "40-hex"),
        (lambda h: {**h, HISTORICAL_ARTIFACT_DIRS[6]: "A" * 40}, "40-hex"),
    ],
)
def test_build_manifest_refuses_missing_extra_or_malformed_tree_hashes(
    mutate: Any, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _manifest(mutate(dict(TREE_HASHES)))


@pytest.mark.parametrize("name", ["PROMPT_SHA256_FROZEN", "POLICY_VERSION_FROZEN"])
def test_build_manifest_refuses_a_frozen_identity_drift(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(artifacts_module, name, "drifted")
    with pytest.raises(RuntimeError, match="drift"):
        _manifest()


def test_build_manifest_requires_a_40_hex_harness_sha() -> None:
    with pytest.raises(ValidationError):
        build_manifest(
            harness_code_sha="HEAD", spec_sha256=_spec_sha256(), historical_tree_hashes=TREE_HASHES
        )


def test_raw_artifact_paths_are_the_21_path_contract() -> None:
    assert RAW_ARTIFACT_PATHS == EXPECTED_RAW_PATHS
    assert len(RAW_ARTIFACT_PATHS) == RAW_ARTIFACT_PATH_COUNT == 21
    assert len(set(RAW_ARTIFACT_PATHS)) == 21
    assert CONSUMPTION_PATHS == ("consumption.json", "preflight.json")
    assert set(CONSUMPTION_PATHS) < set(RAW_ARTIFACT_PATHS)
    for path in RAW_ARTIFACT_PATHS:
        assert not Path(path).is_absolute() and ".." not in Path(path).parts


def test_manifest_written_here_passes_all_eighteen_preflight_gates(
    tmp_path: Path, manifest: ExperimentManifest, leakage_ok: LeakageResult
) -> None:
    """The manifest <-> integrity contract: T5's real ``preflight`` over the sealed
    pair this module writes passes every one of the 18 gates on a consistent fake
    git table."""
    write_preregistration(tmp_path, manifest)
    sealed = _read_json(tmp_path / "manifest.json")
    expectations_bytes = (tmp_path / "expectations.json").read_bytes()

    gates = preflight(
        git=FakeGit(),
        frozen_sha=SEAL_SHA,
        manifest=sealed,
        expectations_bytes=expectations_bytes,
        request_path_sources=_sources(),
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
        out_dir=tmp_path,
    )

    assert tuple(gate.name for gate in gates) == GATE_NAMES
    assert len(gates) == 18
    for gate in gates:
        assert gate.passed is True, (gate.name, gate.detail)
    assert all_passed(gates)
    assert _relative_files(tmp_path) == {"manifest.json", "expectations.json"}


# --- preregistration --------------------------------------------------------------


def test_write_preregistration_writes_exactly_two_files_with_canonical_hashes(
    tmp_path: Path, manifest: ExperimentManifest
) -> None:
    hashes = write_preregistration(tmp_path, manifest)

    assert set(hashes) == {"manifest.json", "expectations.json"}
    assert _relative_files(tmp_path) == {"manifest.json", "expectations.json"}
    assert hashes["manifest.json"] == canonical_sha256(_read_json(tmp_path / "manifest.json"))
    assert hashes["manifest.json"] == canonical_sha256(manifest)
    assert _read_json(tmp_path / "expectations.json") == expectations_document()
    assert hashes["expectations.json"] == manifest.expectations_sha256
    sealed = _read_json(tmp_path / "manifest.json")
    assert sealed["raw_artifact_paths"] == list(RAW_ARTIFACT_PATHS)
    assert sealed["ceilings"] == LOCKED_CEILINGS
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("existing", ["manifest.json", "expectations.json"])
def test_write_preregistration_is_all_or_nothing_when_either_file_exists(
    tmp_path: Path, manifest: ExperimentManifest, existing: str
) -> None:
    (tmp_path / existing).write_text("stray", encoding="utf-8")
    before = _tree_digest(tmp_path)

    with pytest.raises(FileExistsError):
        write_preregistration(tmp_path, manifest)

    assert _tree_digest(tmp_path) == before
    assert _relative_files(tmp_path) == {existing}


def test_write_preregistration_refuses_a_manifest_whose_expectations_hash_drifted(
    tmp_path: Path, manifest: ExperimentManifest
) -> None:
    drifted = manifest.model_copy(update={"expectations_sha256": "0" * 64})

    with pytest.raises(ValueError, match="expectations_sha256"):
        write_preregistration(tmp_path, drifted)

    assert _relative_files(tmp_path) == set()


# --- consumption ------------------------------------------------------------------


def test_write_consumption_writes_exactly_the_two_records(
    tmp_path: Path, leakage_ok: LeakageResult
) -> None:
    written = _consume(tmp_path, leakage_ok)

    assert written == (tmp_path / "preflight.json", tmp_path / "consumption.json")
    assert _relative_files(tmp_path) == set(CONSUMPTION_PATHS)
    assert existing_raw_artifacts(tmp_path) == CONSUMPTION_PATHS
    consumption = _read_json(tmp_path / "consumption.json")
    assert consumption == {
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_sha": SEAL_SHA,
        "harness_code_sha": HARNESS_SHA,
        "policy_version": POLICY_VERSION_FROZEN,
        "prompt_sha256": PROMPT_SHA256_FROZEN,
        "provider": PROVIDER,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "grpc_dns_resolver": GRPC_DNS_RESOLVER_FROZEN,
        "consumed_at": "2026-09-16T12:30:45+00:00",
    }
    document = _read_json(tmp_path / "preflight.json")
    assert document["all_passed"] is True
    assert document["frontier_calls"] == 0
    assert document["frozen_sha"] == SEAL_SHA
    assert document["harness_code_sha"] == HARNESS_SHA
    assert document["experiment_version"] == EXPERIMENT_VERSION
    assert [gate["name"] for gate in document["gates"]] == list(GATE_NAMES)
    assert all(gate["passed"] is True for gate in document["gates"])
    assert document["leakage"] == leakage_ok.model_dump(mode="json")
    assert document["observed_grpc_dns_resolver"] == "native"
    assert not list(tmp_path.rglob("*.tmp"))


def test_write_consumption_converts_the_timestamp_to_utc_and_refuses_a_naive_one(
    tmp_path: Path, leakage_ok: LeakageResult
) -> None:
    from datetime import timedelta, timezone

    plus_two = datetime(2026, 9, 16, 14, 30, 45, tzinfo=timezone(timedelta(hours=2)))
    _consume(tmp_path / "zoned", leakage_ok, consumed_at=plus_two)
    assert _read_json(tmp_path / "zoned" / "consumption.json")["consumed_at"] == (
        "2026-09-16T12:30:45+00:00"
    )

    with pytest.raises(ValueError, match="timezone"):
        _consume(tmp_path / "naive", leakage_ok, consumed_at=datetime(2026, 9, 16, 12, 30, 45))
    assert not (tmp_path / "naive").exists()


@pytest.mark.parametrize("stray", ["consumption.json", "preflight.json", "L-beta/ledger.json"])
def test_write_consumption_refuses_when_any_raw_artifact_exists(
    tmp_path: Path, leakage_ok: LeakageResult, stray: str
) -> None:
    (tmp_path / stray).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / stray).write_text("stray", encoding="utf-8")
    before = _tree_digest(tmp_path)

    with pytest.raises(ConsumptionRefused, match=stray):
        _consume(tmp_path, leakage_ok)

    assert _tree_digest(tmp_path) == before
    assert existing_raw_artifacts(tmp_path) == (stray,)
    assert issubclass(ConsumptionRefused, RuntimeError)


def test_write_consumption_refuses_a_failed_or_malformed_gate_set(
    tmp_path: Path, leakage_ok: LeakageResult
) -> None:
    with pytest.raises(ConsumptionRefused, match="worktree_clean"):
        _consume(tmp_path, leakage_ok, gates=_gates(failing="worktree_clean"))
    assert _relative_files(tmp_path) == set()

    with pytest.raises(ConsumptionRefused):
        _consume(tmp_path, leakage_ok, gates=())
    assert _relative_files(tmp_path) == set()

    with pytest.raises(ValueError, match="GATE_NAMES"):
        _consume(tmp_path, leakage_ok, gates=_gates()[:-1])
    assert _relative_files(tmp_path) == set()


def test_write_consumption_never_persists_secret_shaped_text(
    tmp_path: Path, leakage_ok: LeakageResult
) -> None:
    poisoned = tmp_path / "poisoned"
    _consume(poisoned, leakage_ok, gates=_gates(detail=f"XAI_API_KEY: {SECRET} and {BEARER}"))
    for name in CONSUMPTION_PATHS:
        assert not contains_secret_shape((poisoned / name).read_text(encoding="utf-8")), name
    preflight_text = (poisoned / "preflight.json").read_text(encoding="utf-8")
    assert "[REDACTED]" in preflight_text
    assert SECRET not in preflight_text and BEARER not in preflight_text
    consumption_text = (poisoned / "consumption.json").read_text(encoding="utf-8")
    assert "XAI_API_KEY" not in consumption_text
    assert "[REDACTED]" not in consumption_text

    refused = tmp_path / "refused"
    with pytest.raises(ValueError, match="secret"):
        _consume(refused, leakage_ok, observed=f"native {BEARER}")
    assert not refused.exists() or _relative_files(refused) == set()


def test_write_consumption_writes_preflight_before_consumption(
    tmp_path: Path, leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    original = artifacts_module._write_atomic

    def _recording(path: Path, text: str) -> None:
        order.append(path.name)
        original(path, text)

    monkeypatch.setattr(artifacts_module, "_write_atomic", _recording)
    _consume(tmp_path, leakage_ok)
    assert order == ["preflight.json", "consumption.json"]


# --- raw write --------------------------------------------------------------------


@pytest.mark.parametrize("present", [(), ("preflight.json",), ("consumption.json",)])
def test_write_run_artifacts_refuses_without_both_consumption_files(
    tmp_path: Path, completed: RunResult, present: tuple[str, ...]
) -> None:
    for name in present:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    cases = evaluate_run(completed)
    before = _tree_digest(tmp_path)

    with pytest.raises(ValueError, match="consumption"):
        write_run_artifacts(tmp_path, completed, _verdicts(completed, cases), cases)

    assert _tree_digest(tmp_path) == before
    assert _relative_files(tmp_path) == set(present)


def test_completed_run_writes_exactly_the_21_paths(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    written = _write_raw(tmp_path, completed, leakage_ok)

    assert written == tuple(p for p in RAW_ARTIFACT_PATHS if p not in CONSUMPTION_PATHS)
    assert len(written) == 19
    assert _relative_files(tmp_path) == set(RAW_ARTIFACT_PATHS)
    assert existing_raw_artifacts(tmp_path) == RAW_ARTIFACT_PATHS
    assert not list(tmp_path.rglob("*.tmp"))
    for name in RAW_ARTIFACT_PATHS:
        if name.endswith(".json"):
            _read_json(tmp_path / name)


def test_requests_pair_the_eight_records_with_their_snapshots_bound_exactly(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage_ok)

    total = 0
    for record in completed.ledgers:
        document = _read_json(tmp_path / f"L-{record.ledger}" / "requests.json")
        assert document["ledger"] == record.ledger
        assert document["project_id"] == PROJECT_IDS[record.ledger]
        entries = document["entries"]
        expected = [
            (request, snapshot)
            for delta in record.deltas
            for request, snapshot in zip(delta.requests, delta.reference_snapshots, strict=True)
        ]
        assert len(entries) == len(expected) == 4
        for entry, (request, snapshot) in zip(entries, expected, strict=True):
            assert set(entry) == {"record", "reference_snapshot"}
            assert entry["record"] == request.model_dump(mode="json")
            assert entry["reference_snapshot"] == snapshot.model_dump(mode="json")
            assert entry["record"]["arm"] == entry["reference_snapshot"]["arm"] == "F"
            for key in ("t", "call_number", "request_sha256"):
                assert entry["record"][key] == entry["reference_snapshot"][key]
            assert entry["record"]["rendered_user_request"] == request.rendered_user_request
        assert [(e["record"]["t"], e["record"]["call_number"]) for e in entries] == [
            (1, 1),
            (1, 2),
            (2, 1),
            (2, 2),
        ]
        total += len(entries)
    assert total == 8


def test_requests_refuse_on_a_count_or_identity_mismatch(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    alpha, beta = completed.ledgers
    seed = alpha.deltas[0]
    cases = evaluate_run(completed)
    verdicts = _verdicts(completed, cases)

    fewer = seed.model_copy(update={"reference_snapshots": seed.reference_snapshots[:1]})
    swapped = seed.model_copy(
        update={"reference_snapshots": tuple(reversed(seed.reference_snapshots))}
    )
    for broken, match in ((fewer, "bound"), (swapped, "identity")):
        out_dir = tmp_path / match
        _consume(out_dir, leakage_ok)
        run = completed.model_copy(
            update={
                "ledgers": (
                    alpha.model_copy(update={"deltas": (broken, alpha.deltas[1])}),
                    beta,
                )
            }
        )
        before = _tree_digest(out_dir)
        with pytest.raises(ValueError, match=match):
            write_run_artifacts(out_dir, run, verdicts, cases)
        assert _tree_digest(out_dir) == before
        assert _relative_files(out_dir) == set(CONSUMPTION_PATHS)


def test_aborted_run_writes_the_not_run_ledger_with_all_eight_files(
    tmp_path: Path, aborted: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, aborted, leakage_ok)

    assert _relative_files(tmp_path) == set(RAW_ARTIFACT_PATHS)
    beta = tmp_path / "L-beta"
    result = _read_json(beta / "result.json")
    assert result["status"] == "NOT_RUN"
    assert result["error"] is None
    assert result["delta_count"] == 0
    assert result["request_count"] == 0
    assert result["run_status"] == "ABORTED_PROVIDER"
    assert _read_json(beta / "requests.json")["entries"] == []
    assert _read_json(beta / "drafts.json")["deltas"] == []
    assert _read_json(beta / "receipts.json")["deltas"] == []
    assert _read_json(beta / "decisions.json")["deltas"] == []
    assert _read_json(beta / "ledger.json")["events"] == []
    for t in (1, 2):
        assert _read_json(beta / f"state_T{t}.json") == {
            "ledger": "beta",
            "t": t,
            "present": False,
            "state": None,
            "view": None,
        }

    alpha = tmp_path / "L-alpha"
    result = _read_json(alpha / "result.json")
    assert result["status"] == "FAILED"
    assert result["error"] == "XAIProviderError: PROVIDER_FAILURE"
    assert result["delta_count"] == 2
    assert result["request_count"] == 2
    assert len(_read_json(alpha / "requests.json")["entries"]) == 2
    assert _read_json(alpha / "state_T1.json")["present"] is True
    assert _read_json(alpha / "decisions.json")["deltas"][1]["stage_decisions"] == [[], []]


def test_state_files_carry_the_state_and_view_of_each_delta(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage_ok)

    for record in completed.ledgers:
        for delta in record.deltas:
            document = _read_json(tmp_path / f"L-{record.ledger}" / f"state_T{delta.t}.json")
            assert delta.state_snapshot is not None and delta.view_snapshot is not None
            assert document["present"] is True
            assert document["state"] == delta.state_snapshot.model_dump(mode="json")
            assert document["view"] == delta.view_snapshot.model_dump(mode="json")
        ledger = _read_json(tmp_path / f"L-{record.ledger}" / "ledger.json")
        assert ledger["event_count"] == len(record.ledger_events)
        assert len(ledger["events"]) == len(record.ledger_events)
        result = _read_json(tmp_path / f"L-{record.ledger}" / "result.json")
        assert result["status"] == "COMPLETED"
        assert result["replay"]["status"] == "REPLAY_MATCH"
        assert result["receipt_count"] == 4
        decisions = _read_json(tmp_path / f"L-{record.ledger}" / "decisions.json")
        assert [d["t"] for d in decisions["deltas"]] == [1, 2]
        for entry, delta in zip(decisions["deltas"], record.deltas, strict=True):
            assert entry["stage_decisions"] == [
                [d.model_dump(mode="json") for d in stage] for stage in delta.stage_decisions
            ]


def test_measurements_carry_one_row_per_request_from_its_own_receipt(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage_ok)

    document = _read_json(tmp_path / "measurements.json")
    rows = document["rows"]
    assert document["row_count"] == len(rows) == 8
    assert [(r["ledger"], r["t"], r["call_number"]) for r in rows] == [
        (ledger, t, call) for ledger in LEDGERS for t in (1, 2) for call in (1, 2)
    ]
    index = 0
    for record in completed.ledgers:
        for delta in record.deltas:
            for request, receipt in zip(delta.requests, delta.receipts, strict=True):
                row = rows[index]
                assert row["input_tokens"] == receipt.input_tokens
                assert row["output_tokens"] == receipt.output_tokens
                assert row["wall_clock_ms"] == receipt.wall_clock_ms
                assert row["provider_cost_usd"] == str(Decimal(str(receipt.cost_usd)))
                assert row["rendered_request_chars"] == len(request.rendered_user_request)
                assert row["request_sha256"] == request.request_sha256
                index += 1
    total = sum(Decimal(row["provider_cost_usd"]) for row in rows)
    assert total == Decimal(completed.budget.provider_cost_usd)
    receipts = _read_json(tmp_path / "L-alpha" / "receipts.json")
    assert [len(d["receipts"]) for d in receipts["deltas"]] == [2, 2]
    drafts = _read_json(tmp_path / "L-alpha" / "drafts.json")
    assert [p["payload"]["call"] for d in drafts["deltas"] for p in d["payloads"]] == [1, 2, 3, 4]


def test_measurement_economics_are_null_when_no_receipt_was_recorded(
    tmp_path: Path, bare: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, bare, leakage_ok)

    rows = _read_json(tmp_path / "measurements.json")["rows"]
    assert len(rows) == 8
    for row in rows:
        assert row["receipt_recorded"] is False
        for key in ("input_tokens", "output_tokens", "provider_cost_usd", "wall_clock_ms"):
            assert row[key] is None
        assert row["rendered_request_chars"] > 0


def test_raw_verdicts_are_null_on_a_clean_run(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    cases = evaluate_run(completed)
    verdicts = _verdicts(completed, cases)
    _write_raw(tmp_path, completed, leakage_ok, cases=cases, verdicts=verdicts)

    document = _read_json(tmp_path / "verdicts.json")
    assert document["phase"] == "raw"
    assert document["status"] == "COMPLETED"
    assert document["error"] is None
    assert document["budget"] == completed.budget.model_dump(mode="json")
    assert list(document["integrity"]) == list(VERDICT_IDS)
    for verdict in verdicts:
        entry = document["integrity"][verdict.id]
        assert entry == {
            "passed": True,
            "detail": verdict.detail,
            "applies_to": ["alpha", "beta"],
            "failed_ledgers": [],
        }
    assert document["case_assertions"] == [c.model_dump(mode="json") for c in cases]
    assert len(document["case_assertions"]) == 12
    assert document["semantic_assertions"] is None
    assert document["semantic_notes"] is None
    assert document["case_outcomes"] is None
    assert document["experiment_outcome"] is None
    assert document == verdicts_document(completed, verdicts, cases)


def test_raw_verdicts_record_inconclusive_on_an_aborted_run_with_case_outcomes_null(
    tmp_path: Path, aborted: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, aborted, leakage_ok)

    document = _read_json(tmp_path / "verdicts.json")
    assert document["phase"] == "raw"
    assert document["status"] == "ABORTED_PROVIDER"
    assert document["error"] == "XAIProviderError: PROVIDER_FAILURE"
    assert document["experiment_outcome"] == INCONCLUSIVE
    assert document["case_outcomes"] is None
    assert document["semantic_assertions"] is None
    assert document["semantic_notes"] is None
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert PENDING_LINE not in report
    assert f"experiment_outcome = {INCONCLUSIVE}" in report
    assert "rule 0" in report


def test_raw_verdicts_record_inconclusive_on_an_l_failure_but_not_on_l9(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    cases = evaluate_run(completed)
    verdicts = _verdicts(completed, cases)

    l8 = _with_verdict(verdicts, "L8", passed=False, detail="cost 3 USD exceeds ceiling")
    _write_raw(tmp_path / "l8", completed, leakage_ok, cases=cases, verdicts=l8)
    document = _read_json(tmp_path / "l8" / "verdicts.json")
    assert document["experiment_outcome"] == INCONCLUSIVE
    assert document["case_outcomes"] is None
    assert document["integrity"]["L8"]["passed"] is False

    l9 = _with_verdict(
        verdicts, "L9", passed=False, detail="alpha V05 FAILED", failed_ledgers=("alpha",)
    )
    _write_raw(tmp_path / "l9", completed, leakage_ok, cases=cases, verdicts=l9)
    document = _read_json(tmp_path / "l9" / "verdicts.json")
    assert document["experiment_outcome"] is None
    assert document["integrity"]["L9"]["failed_ledgers"] == ["alpha"]
    assert PENDING_LINE in (tmp_path / "l9" / "report.md").read_text(encoding="utf-8")


def test_raw_report_carries_the_pending_line_and_the_facts(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    cases = evaluate_run(completed)
    verdicts = _verdicts(completed, cases)
    _write_raw(tmp_path, completed, leakage_ok, cases=cases, verdicts=verdicts)

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report.count(PENDING_LINE) == 1
    assert report == render_report(completed, verdicts, cases)
    assert EXPERIMENT_VERSION in report
    assert "COMPLETED" in report
    for verdict_id in VERDICT_IDS:
        assert f"| {verdict_id} |" in report
    for ledger in LEDGERS:
        for case_id in CASE_IDS:
            assert f"| {ledger} | {case_id} |" in report
    assert VALIDATED not in report and NOT_VALIDATED not in report
    assert INCONCLUSIVE not in report


def test_raw_writers_never_call_experiment_outcome(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("experiment_outcome must never run on the raw path")

    monkeypatch.setattr(artifacts_module, "experiment_outcome", _forbidden)
    _write_raw(tmp_path, completed, leakage_ok)
    assert _relative_files(tmp_path) == set(RAW_ARTIFACT_PATHS)
    assert _read_json(tmp_path / "verdicts.json")["experiment_outcome"] is None


def test_raw_writer_functions_never_reference_the_outcome_machinery() -> None:
    assert _functions_referencing("experiment_outcome") == {"write_adjudication"}
    raw_closure = _transitive_callees(RAW_WRITER_FUNCTIONS)
    assert raw_closure >= RAW_WRITER_FUNCTIONS
    assert "write_adjudication" not in raw_closure
    for name in ("experiment_outcome", "CASE_OUTCOME_RULES", "case_passes", "Adjudication"):
        assert not raw_closure & _functions_referencing(name), name
    assert VALIDATED not in ARTIFACTS_SOURCE
    assert NOT_VALIDATED not in ARTIFACTS_SOURCE
    assert "VALIDATED" not in ARTIFACTS_SOURCE
    functions = _module_functions()
    for name in raw_closure:
        for inner in ast.walk(functions[name]):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                assert "experiment_outcome" not in inner.value, name
    assert {"write_consumption", "write_run_artifacts", "write_adjudication"} <= set(functions)


def test_write_once_is_all_or_nothing(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _consume(tmp_path, leakage_ok)
    stray = tmp_path / "L-beta" / "ledger.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("stray", encoding="utf-8")
    cases = evaluate_run(completed)
    before = _tree_digest(tmp_path)

    with pytest.raises(FileExistsError, match="L-beta/ledger.json"):
        write_run_artifacts(tmp_path, completed, _verdicts(completed, cases), cases)

    assert _tree_digest(tmp_path) == before
    assert _relative_files(tmp_path) == {*CONSUMPTION_PATHS, "L-beta/ledger.json"}
    assert not list(tmp_path.rglob("*.tmp"))


def test_secret_shaped_rendered_request_refuses_the_whole_write(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _consume(tmp_path, leakage_ok)
    alpha, beta = completed.ledgers
    revision = alpha.deltas[1]
    poisoned_request = revision.requests[1].model_copy(
        update={"rendered_user_request": revision.requests[1].rendered_user_request + BEARER}
    )
    poisoned = completed.model_copy(
        update={
            "ledgers": (
                alpha.model_copy(
                    update={
                        "deltas": (
                            alpha.deltas[0],
                            revision.model_copy(
                                update={"requests": (revision.requests[0], poisoned_request)}
                            ),
                        )
                    }
                ),
                beta,
            )
        }
    )
    cases = evaluate_run(completed)
    before = _tree_digest(tmp_path)

    with pytest.raises(ValueError, match="secret"):
        write_run_artifacts(tmp_path, poisoned, _verdicts(completed, cases), cases)

    assert _tree_digest(tmp_path) == before
    assert _relative_files(tmp_path) == set(CONSUMPTION_PATHS)


def test_secret_shaped_diagnostics_are_redacted_and_never_persist(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    alpha, beta = completed.ledgers
    run = completed.model_copy(
        update={
            "error": f"provider said {SECRET}",
            "ledgers": (alpha.model_copy(update={"error": f"alpha saw {BEARER}"}), beta),
        }
    )
    cases = _with_case(evaluate_run(completed), "beta", "V02", detail=f"note {SECRET}")
    verdicts = _with_verdict(_verdicts(completed, cases), "L7", detail=f"guard {BEARER}")
    _write_raw(tmp_path, run, leakage_ok, cases=cases, verdicts=verdicts)

    for name in RAW_ARTIFACT_PATHS:
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert not contains_secret_shape(text), name
    document = _read_json(tmp_path / "verdicts.json")
    assert document["error"] == "provider said [REDACTED]"
    assert document["integrity"]["L7"]["detail"] == "guard [REDACTED]"
    assert "[REDACTED]" in next(
        c["detail"]
        for c in document["case_assertions"]
        if c["case_id"] == "V02" and c["ledger"] == "beta"
    )
    assert _read_json(tmp_path / "L-alpha" / "result.json")["error"] == "alpha saw [REDACTED]"
    assert "[REDACTED]" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_raw_verdicts_require_l1_to_l9_in_order(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _consume(tmp_path, leakage_ok)
    cases = evaluate_run(completed)
    verdicts = _verdicts(completed, cases)
    before = _tree_digest(tmp_path)

    for broken in (verdicts[:-1], tuple(reversed(verdicts))):
        with pytest.raises(ValueError, match="L1"):
            write_run_artifacts(tmp_path, completed, broken, cases)
        with pytest.raises(ValueError, match="L1"):
            verdicts_document(completed, broken, cases)
    assert _tree_digest(tmp_path) == before


# --- adjudication -----------------------------------------------------------------


def test_adjudication_model_requires_exactly_both_ledgers_and_the_semantic_ids() -> None:
    assert _adjudication().semantic_answers == _answers()
    assert SEMANTIC_ASSERTION_IDS == ("A-S01", "A-V01", "A-V02", "A-V03", "A-V05")

    answers = _answers()
    del answers["beta"]
    with pytest.raises(ValidationError, match="beta"):
        _adjudication(semantic_answers=answers)

    with pytest.raises(ValidationError, match="A-V04"):
        _adjudication(semantic_answers=_answers(alpha={"A-V04": True}))

    with pytest.raises(ValidationError, match="A-X99"):
        _adjudication(semantic_answers=_answers(beta={"A-X99": False}))

    answers = _answers()
    del answers["alpha"]["A-V03"]
    with pytest.raises(ValidationError, match="A-V03"):
        _adjudication(semantic_answers=answers)

    with pytest.raises(ValidationError):
        _adjudication(
            semantic_answers={**_answers(), "gamma": dict.fromkeys(SEMANTIC_ASSERTION_IDS, True)}
        )

    with pytest.raises(ValidationError):
        _adjudication(semantic_answers=_answers(alpha={"A-S01": "yes"}))


def test_write_adjudication_refuses_when_head_differs(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    git = _commit(out_dir, tmp_path)
    git._head = "e" * 40
    before = _tree_digest(out_dir)

    with pytest.raises(AdjudicationRefused, match="HEAD"):
        _adjudicate(out_dir, tmp_path, git=git)

    assert _tree_digest(out_dir) == before
    assert issubclass(AdjudicationRefused, RuntimeError)


def test_write_adjudication_refuses_a_dirty_worktree(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    git = _commit(out_dir, tmp_path)
    git._dirty = " M src/foundry/experiments/locus_validation/artifacts.py\n"
    before = _tree_digest(out_dir)

    with pytest.raises(AdjudicationRefused, match="dirty"):
        _adjudicate(out_dir, tmp_path, git=git)

    assert _tree_digest(out_dir) == before


def test_write_adjudication_refuses_a_missing_or_differing_raw_byte(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    git = _commit(out_dir, tmp_path)

    target = out_dir / "L-beta" / "receipts.json"
    original = target.read_bytes()
    target.write_bytes(original[:-1] + b" ")
    before = _tree_digest(out_dir)
    with pytest.raises(AdjudicationRefused, match="L-beta/receipts.json"):
        _adjudicate(out_dir, tmp_path, git=git)
    assert _tree_digest(out_dir) == before

    target.write_bytes(original)
    (out_dir / "measurements.json").unlink()
    before = _tree_digest(out_dir)
    with pytest.raises(AdjudicationRefused, match="measurements.json"):
        _adjudicate(out_dir, tmp_path, git=git)
    assert _tree_digest(out_dir) == before


def test_write_adjudication_refuses_when_the_provider_key_is_present(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    git = _commit(out_dir, tmp_path)
    before = _tree_digest(out_dir)

    with pytest.raises(AdjudicationRefused, match="XAI_API_KEY"):
        _adjudicate(out_dir, tmp_path, git=git, env=PoisonedEnv())
    with pytest.raises(AdjudicationRefused, match="XAI_API_KEY"):
        _adjudicate(out_dir, tmp_path, git=git, env={"XAI_API_KEY": "dummy-value"})

    assert _tree_digest(out_dir) == before
    assert git.calls == []


def test_write_adjudication_is_write_once(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    _adjudicate(out_dir, tmp_path)
    assert _read_json(out_dir / "verdicts.json")["phase"] == "adjudicated"
    before = _tree_digest(out_dir)

    with pytest.raises(AdjudicationRefused, match="adjudicated"):
        _adjudicate(out_dir, tmp_path, git=_commit(out_dir, tmp_path, sha=RAW_RUN_SHA))

    assert _tree_digest(out_dir) == before


def test_write_adjudication_rewrites_only_verdicts_and_report(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    git = _commit(out_dir, tmp_path)
    before = _tree_digest(out_dir)
    assert set(before) == set(RAW_ARTIFACT_PATHS)

    written = _adjudicate(out_dir, tmp_path, git=git)
    after = _tree_digest(out_dir)

    assert written == ("verdicts.json", "report.md")
    assert set(after) == set(RAW_ARTIFACT_PATHS)
    assert {name for name in before if before[name] != after[name]} == {
        "verdicts.json",
        "report.md",
    }
    assert not list(out_dir.rglob("*.tmp"))
    assert ("head",) in git.calls and ("dirty",) in git.calls
    shown = {call[2] for call in git.calls if call[0] == "show_bytes"}
    assert shown == {f"{EXPERIMENT_ARTIFACT_DIR}{name}" for name in RAW_ARTIFACT_PATHS}


def test_write_adjudication_requires_out_dir_inside_repo_root(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "elsewhere" / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    before = _tree_digest(out_dir)

    with pytest.raises(ValueError, match="repo_root"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=CommittedGit(head=RAW_RUN_SHA, show={}),
            adjudication=_adjudication(),
            repo_root=repo_root,
            env={},
        )
    assert _tree_digest(out_dir) == before


def _case_outcomes(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    outcomes = document["case_outcomes"]
    assert len(outcomes) == 12
    assert [(o["ledger"], o["case_id"]) for o in outcomes] == [
        (ledger, case_id) for ledger in LEDGERS for case_id in CASE_IDS
    ]
    return {(o["ledger"], o["case_id"]): o for o in outcomes}


def test_all_structural_passes_and_true_answers_validate(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    raw = _read_json(out_dir / "verdicts.json")

    _adjudicate(out_dir, tmp_path)

    document = _read_json(out_dir / "verdicts.json")
    assert document["phase"] == "adjudicated"
    assert document["raw_run_commit_sha"] == RAW_RUN_SHA
    assert document["experiment_outcome"] == VALIDATED
    assert document["semantic_assertions"] == _answers()
    assert document["semantic_notes"] == "scripted adjudication | with a pipe\nand a newline"
    assert document["rule_zero"] is False
    outcomes = _case_outcomes(document)
    for (_ledger, case_id), outcome in outcomes.items():
        assert outcome["structural_passed"] is True
        assert outcome["passed"] is True
        assert outcome["semantic_answer"] == (None if case_id == "V04" else True)
        assert outcome["semantic_assertion_id"] == (None if case_id == "V04" else f"A-{case_id}")
        assert outcome["tags"] == []
    filled = {
        "phase",
        "semantic_assertions",
        "semantic_notes",
        "case_outcomes",
        "experiment_outcome",
    }
    for key in raw:
        if key not in filled:
            assert document[key] == raw[key], key
    assert set(raw) <= set(document)
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert PENDING_LINE not in report
    assert f"experiment_outcome = {VALIDATED}" in report
    assert RAW_RUN_SHA in report
    assert "## Adjudication" in report
    assert "with a pipe" in report


def test_one_false_answer_is_not_validated_naming_the_case(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)

    _adjudicate(
        out_dir,
        tmp_path,
        adjudication=_adjudication(semantic_answers=_answers(beta={"A-V03": False})),
    )

    document = _read_json(out_dir / "verdicts.json")
    assert document["experiment_outcome"] == NOT_VALIDATED
    outcomes = _case_outcomes(document)
    assert outcomes[("beta", "V03")] == {
        "ledger": "beta",
        "case_id": "V03",
        "structural_passed": True,
        "semantic_assertion_id": "A-V03",
        "semantic_answer": False,
        "passed": False,
        "tags": [],
    }
    assert outcomes[("alpha", "V03")]["passed"] is True
    assert sum(1 for o in outcomes.values() if o["passed"] is False) == 1
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert f"experiment_outcome = {NOT_VALIDATED}" in report
    assert "| beta | V03 |" in report
    assert "beta V03" in report


def test_one_structural_failure_is_not_validated_with_its_tags(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    cases = _with_case(
        evaluate_run(completed),
        "alpha",
        "V05",
        structural_passed=False,
        tags=("MISSING_SUPERSEDE", "EXTRA_DRAFT"),
        detail="MISSING_SUPERSEDE: synthetic; EXTRA_DRAFT: synthetic",
    )
    verdicts = _verdicts(completed, cases)
    assert next(v for v in verdicts if v.id == "L9").passed is False
    _write_raw(out_dir, completed, leakage_ok, cases=cases, verdicts=verdicts)
    assert _read_json(out_dir / "verdicts.json")["experiment_outcome"] is None

    _adjudicate(out_dir, tmp_path)

    document = _read_json(out_dir / "verdicts.json")
    assert document["experiment_outcome"] == NOT_VALIDATED
    assert document["rule_zero"] is False
    outcome = _case_outcomes(document)[("alpha", "V05")]
    assert outcome["structural_passed"] is False
    assert outcome["semantic_answer"] is True
    assert outcome["passed"] is False
    assert outcome["tags"] == ["MISSING_SUPERSEDE", "EXTRA_DRAFT"]
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "MISSING_SUPERSEDE" in report and "alpha V05" in report


def test_rule_zero_is_inconclusive_regardless_of_answers(
    tmp_path: Path, completed: RunResult, aborted: RunResult, leakage_ok: LeakageResult
) -> None:
    aborted_dir = tmp_path / "aborted" / EXPERIMENT_ARTIFACT_DIR
    _write_raw(aborted_dir, aborted, leakage_ok)
    _adjudicate(aborted_dir, tmp_path / "aborted")
    document = _read_json(aborted_dir / "verdicts.json")
    assert document["phase"] == "adjudicated"
    assert document["experiment_outcome"] == INCONCLUSIVE
    assert document["rule_zero"] is True
    outcomes = _case_outcomes(document)
    assert outcomes[("alpha", "S01")]["passed"] is True
    for case_id in ("V01", "V02", "V03", "V04", "V05"):
        assert outcomes[("alpha", case_id)]["structural_passed"] is None
        assert outcomes[("alpha", case_id)]["passed"] is None
    for case_id in CASE_IDS:
        assert outcomes[("beta", case_id)]["passed"] is None
    report = (aborted_dir / "report.md").read_text(encoding="utf-8")
    assert report.count("experiment_outcome = ") == 1
    assert f"experiment_outcome = {INCONCLUSIVE}" in report

    failed_dir = tmp_path / "l3" / EXPERIMENT_ARTIFACT_DIR
    cases = evaluate_run(completed)
    verdicts = _with_verdict(
        _verdicts(completed, cases),
        "L3",
        passed=False,
        detail="cite outside",
        failed_ledgers=("beta",),
    )
    _write_raw(failed_dir, completed, leakage_ok, cases=cases, verdicts=verdicts)
    _adjudicate(failed_dir, tmp_path / "l3")
    document = _read_json(failed_dir / "verdicts.json")
    assert document["experiment_outcome"] == INCONCLUSIVE
    assert document["rule_zero"] is True
    assert all(o["passed"] is True for o in _case_outcomes(document).values())


def test_write_adjudication_proves_the_other_nineteen_files_unchanged(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage_ok)
    original = artifacts_module._write_atomic

    def _leaking(path: Path, text: str) -> None:
        original(path, text)
        (out_dir / "measurements.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(artifacts_module, "_write_atomic", _leaking)
    with pytest.raises(AdjudicationRefused, match="measurements.json"):
        _adjudicate(out_dir, tmp_path)


def test_write_adjudication_refuses_committed_evidence_it_cannot_score(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    cases = evaluate_run(completed)
    verdicts = _with_verdict(_verdicts(completed, cases), "L6", passed=None)
    _write_raw(out_dir, completed, leakage_ok, cases=cases, verdicts=verdicts)
    before = _tree_digest(out_dir)

    with pytest.raises(AdjudicationRefused, match="L6"):
        _adjudicate(out_dir, tmp_path)
    assert _tree_digest(out_dir) == before

    incomplete = tmp_path / "incomplete" / EXPERIMENT_ARTIFACT_DIR
    _write_raw(
        incomplete,
        completed,
        leakage_ok,
        cases=cases[:-1],
        verdicts=_verdicts(completed, cases[:-1]),
    )
    before = _tree_digest(incomplete)
    with pytest.raises(AdjudicationRefused, match="V05"):
        _adjudicate(incomplete, tmp_path / "incomplete")
    assert _tree_digest(incomplete) == before


def test_module_law_and_exports() -> None:
    doc = artifacts_module.__doc__ or ""
    assert "decides nothing" in doc
    assert set(artifacts_module.__all__) >= {
        "CONSUMPTION_PATHS",
        "FINAL_SEAL_RULE",
        "RAW_ARTIFACT_PATHS",
        "SPEC_PATH",
        "Adjudication",
        "AdjudicationRefused",
        "Ceilings",
        "ConsumptionRefused",
        "ExperimentManifest",
        "build_manifest",
        "existing_raw_artifacts",
        "render_report",
        "verdicts_document",
        "write_adjudication",
        "write_consumption",
        "write_preregistration",
        "write_run_artifacts",
    }
    tree = ast.parse(ARTIFACTS_SOURCE)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert "subprocess" not in imported
    assert "XAILocusSemanticReasoner" not in imported
    assert "os.environ" not in ARTIFACTS_SOURCE
    assert "getenv" not in ARTIFACTS_SOURCE
