"""9P3 T6: sealed preregistration, the write-once 116-path raw evidence tree and the
post-commit architect adjudication writer (spec §12, §14, §16, §17, §19; T6 brief;
clarifications 1-9).

Two phases with a hard boundary. The raw phase (``write_preflight``,
``write_run_artifacts``) is machine-produced and carries NO semantic decision: every
architect field of ``verdicts.json`` is ``null`` and ``select_architecture`` is never
reached (proven by monkeypatch and by AST). The adjudication phase
(``write_adjudication``) runs only against a committed, clean, byte-identical raw tree
and rewrites exactly ``verdicts.json`` and ``report.md``. Scripted ``RunResult``s come
from the T4 fakes through the real governor path; Git is a fake implementing every
``GitCliLike`` method; ZERO live calls; sockets are blocked; nothing here touches the
real experiment directory (every tree lives under ``tmp_path``).
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_long_horizon_bounded_runner import Harness, _cell, _position

from foundry.adapters.semantics.xai_reasoner import XAIProviderError
from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256, pretty_json
from foundry.experiments.contrastive_unseen.integrity import GateResult, all_passed
from foundry.experiments.long_horizon_bounded import artifacts as artifacts_module
from foundry.experiments.long_horizon_bounded import integrity as integrity_module
from foundry.experiments.long_horizon_bounded.artifacts import (
    ADJUDICATION_PENDING_LINE,
    ARTIFACT_FORMAT_VERSION,
    BOUNDED_GROWTH_RULE,
    ECONOMY_RULE,
    EXPERIMENT_ARTIFACT_DIR,
    EXPERIMENT_WIDE_VERDICT_IDS,
    FINAL_SEAL_RULE,
    PREREGISTRATION_FILE_NAMES,
    R_GROWTH_RULE,
    RAW_ARTIFACT_PATHS,
    SPEC_PATH,
    TOKEN_DIFF_RULE,
    Adjudication,
    AdjudicationRefused,
    Ceilings,
    ExperimentManifest,
    build_manifest,
    existing_raw_artifacts,
    manifest_sha256,
    write_adjudication,
    write_preflight,
    write_preregistration,
    write_run_artifacts,
)
from foundry.experiments.long_horizon_bounded.expectations import (
    CHECKPOINTS,
    DECISION_NAMES,
    SelectionInputs,
    expectations_document,
    select_architecture,
)
from foundry.experiments.long_horizon_bounded.integrity import (
    A_POLICY_VERSION_FROZEN,
    A_PROMPT_SHA256_FROZEN,
    CEILING_KEYS,
    FR_POLICY_VERSION_FROZEN,
    FR_PROMPT_SHA256_FROZEN,
    GATE_I13_NAME,
    GATE_I14_NAME,
    GATE_NAMES,
    HISTORICAL_ARTIFACT_DIRS,
    HISTORICAL_PRESERVATION_BASE_SHA,
    LOCKED_CEILINGS,
    OUTPUT_SCHEMA_SHA256_FROZEN,
    PREDECESSOR_ARTIFACT_DIR,
    PREDECESSOR_RAW_EVIDENCE_SHA,
    PREREGISTRATION_FILES,
    REQUIRED_MANIFEST_KEYS,
    VERDICT_IDS,
    IntegrityVerdict,
    integrity_verdicts,
    preflight,
)
from foundry.experiments.long_horizon_bounded.leakage import (
    REQUEST_PATH_MODULES,
    LeakageResult,
    needle_set_sha256,
    run_leakage_gate,
)
from foundry.experiments.long_horizon_bounded.measurements import CallMeasurement, summarize
from foundry.experiments.long_horizon_bounded.protocol import (
    ARM_SCHEDULE,
    EARLY_WINDOW,
    FROZEN_CORE_SHA,
    LATE_WINDOW,
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.long_horizon_bounded.runner import CellRecord, RunResult, RunStatus
from foundry.experiments.long_horizon_bounded.timeline import (
    EXPERIMENT_VERSION,
    PROJECT_ID,
    SCOPE,
    corpus_sha256,
    evidence_records,
)

ARTIFACTS_PATH = Path(artifacts_module.__file__)
ARTIFACTS_SOURCE = ARTIFACTS_PATH.read_text(encoding="utf-8")
PACKAGE_DIR = Path("src/foundry/experiments/long_horizon_bounded")

HARNESS_SHA = "a" * 40
SEAL_SHA = "5" * 40
RAW_RUN_SHA = "7" * 40
SPEC_SHA256 = hashlib.sha256(b"spec bytes").hexdigest()
SECRET_TOKEN = "xai-abcdef0123456789SECRETVALUE"
TREE_HASHES = {
    directory: hashlib.sha1(directory.encode()).hexdigest()
    for directory in HISTORICAL_ARTIFACT_DIRS
}
CHECKPOINT_IDS = tuple(checkpoint.id for checkpoint in CHECKPOINTS)
EXPECTED_MANIFEST_FIELDS = (
    "experiment_version",
    "artifact_format_version",
    "frozen_core_sha",
    "predecessor_raw_evidence_sha",
    "harness_code_sha",
    "final_seal_rule",
    "spec_path",
    "spec_sha256",
    "provider",
    "model",
    "reasoning_effort",
    "grpc_dns_resolver",
    "fr_policy_version",
    "fr_prompt_sha256",
    "a_policy_version",
    "a_prompt_sha256",
    "output_schema_sha256",
    "arm_schedule",
    "ceilings",
    "evidence",
    "corpus_sha256",
    "leakage_needle_set_sha256",
    "expectations_sha256",
    "economy_rule",
    "bounded_growth_rule",
    "r_growth_rule",
    "token_diff_rule",
    "early_window",
    "late_window",
    "decision_names",
    "historical_preservation_base_sha",
    "historical_artifact_dirs",
    "historical_artifact_tree_hashes",
    "predecessor_artifact_dir",
    "lifecycle_project_id",
    "scope",
)
EXPECTED_RAW_PATHS = (
    "preflight.json",
    "measurements.json",
    "verdicts.json",
    "report.md",
    *(
        f"{arm}/{name}.json"
        for arm in ("F", "A")
        for name in (
            "requests",
            "drafts",
            "receipts",
            "decisions",
            "eligible_targets",
            "authorizations",
            "ledger",
            "result",
        )
    ),
    *(
        f"R/T{t:02d}/{name}.json"
        for t in range(1, 17)
        for name in ("requests", "drafts", "receipts", "decisions", "ledger", "result")
    ),
)


def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_sockets(monkeypatch)


# --- fakes ------------------------------------------------------------------------


class FakeGit:
    """Every ``GitCliLike`` method, scripted. ``show`` is keyed by the repo-relative
    path strings ``write_adjudication`` derives from ``repo_root``."""

    def __init__(
        self,
        *,
        head: str = SEAL_SHA,
        dirty: str = "",
        show: dict[tuple[str, str], bytes] | None = None,
        parents: dict[str, tuple[str, ...]] | None = None,
        ancestors: frozenset[tuple[str, str]] | None = None,
        changed: dict[tuple[str, str], tuple[str, ...]] | None = None,
        trees: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._head = head
        self._dirty = dirty
        self._show = show if show is not None else {}
        self._parents = parents if parents is not None else {SEAL_SHA: (HARNESS_SHA,)}
        self._ancestors = (
            ancestors
            if ancestors is not None
            else frozenset(
                {
                    (FROZEN_CORE_SHA, SEAL_SHA),
                    (HISTORICAL_PRESERVATION_BASE_SHA, SEAL_SHA),
                    (PREDECESSOR_RAW_EVIDENCE_SHA, SEAL_SHA),
                }
            )
        )
        self._changed = (
            changed
            if changed is not None
            else {
                (HARNESS_SHA, SEAL_SHA): PREREGISTRATION_FILES,
                (FROZEN_CORE_SHA, SEAL_SHA): (
                    "src/foundry/experiments/long_horizon_bounded/artifacts.py",
                    *PREREGISTRATION_FILES,
                ),
                (PREDECESSOR_RAW_EVIDENCE_SHA, SEAL_SHA): PREREGISTRATION_FILES,
            }
        )
        self._trees = (
            trees
            if trees is not None
            else {
                (sha, directory): tree
                for directory, tree in TREE_HASHES.items()
                for sha in (HISTORICAL_PRESERVATION_BASE_SHA, SEAL_SHA)
            }
        )
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


class FakeCommands:
    def __init__(self) -> None:
        self.argvs: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> tuple[int, str]:
        self.argvs.append(argv)
        return 0, f"fake output for {' '.join(argv)} (exit 0)"


# --- fixtures -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def completed() -> Iterator[RunResult]:
    """One scripted, fully completed 48-cell walk through the real governor path."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        result = Harness().run()
        assert result.status is RunStatus.COMPLETED
        yield result


@pytest.fixture(scope="module")
def aborted() -> Iterator[RunResult]:
    """F fails at its very first call (position 0); every later cell is NOT_RUN. The
    provider error echoes a key so the redaction path is exercised."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _block_sockets(monkeypatch)
        error = XAIProviderError(f"provider rejected key {SECRET_TOKEN}")
        result = Harness(f_overrides={0: error}).run()
        assert result.status is RunStatus.ABORTED_PROVIDER
        yield result


@pytest.fixture(scope="module")
def leakage_ok() -> LeakageResult:
    result = run_leakage_gate()
    assert result.passed
    return result


@pytest.fixture
def manifest() -> ExperimentManifest:
    return _manifest()


# --- builders ----------------------------------------------------------------------


def _manifest(tree_hashes: dict[str, str] | None = None) -> ExperimentManifest:
    return build_manifest(
        harness_code_sha=HARNESS_SHA,
        spec_sha256=SPEC_SHA256,
        historical_tree_hashes=tree_hashes if tree_hashes is not None else dict(TREE_HASHES),
    )


def _gates(*, failing: str | None = None, detail: str = "ok") -> tuple[GateResult, ...]:
    return tuple(
        GateResult(name=name, passed=name != failing, detail=detail if name == failing else "ok")
        for name in GATE_NAMES
    )


def _verdicts(run: RunResult, gates: tuple[GateResult, ...]) -> tuple[IntegrityVerdict, ...]:
    return integrity_verdicts(run, preflight_gates=gates)


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


def _write_raw(
    out_dir: Path,
    run: RunResult,
    *,
    gates: tuple[GateResult, ...] | None = None,
    leakage: LeakageResult,
    observed: str | None = "native",
) -> tuple[GateResult, ...]:
    gates = gates if gates is not None else _gates()
    write_preflight(
        out_dir, gates, frozen_sha=SEAL_SHA, leakage=leakage, observed_grpc_dns_resolver=observed
    )
    write_run_artifacts(out_dir, run, _verdicts(run, gates))
    return gates


def _commit(out_dir: Path, repo_root: Path, sha: str = RAW_RUN_SHA) -> FakeGit:
    """A fake raw-run commit: HEAD is ``sha`` and every raw path shows the on-disk bytes."""
    show = {
        (sha, (out_dir / name).relative_to(repo_root).as_posix()): (out_dir / name).read_bytes()
        for name in RAW_ARTIFACT_PATHS
    }
    return FakeGit(head=sha, show=show)


def _adjudication(**overrides: Any) -> Adjudication:
    fields: dict[str, Any] = {
        "checkpoints": {arm: dict.fromkeys(CHECKPOINT_IDS, True) for arm in ("F", "A", "R")},
        "control_errors": {"F": 0, "A": 0, "R": 1},
        "material_errors": {"F": 0, "A": 1, "R": 2},
        "notes": "scripted adjudication | with a pipe\nand a newline",
    }
    fields.update(overrides)
    return Adjudication(**fields)


def _with_cell(run: RunResult, cell: CellRecord) -> RunResult:
    cells = list(run.cells)
    cells[cell.position] = cell
    return run.model_copy(
        update={"cells": tuple(cells), "r_cells": {c.t: c for c in cells if c.arm == "R"}}
    )


def _functions_referencing(name: str) -> set[str]:
    tree = ast.parse(ARTIFACTS_SOURCE)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and inner.id == name:
                    found.add(node.name)
                if isinstance(inner, ast.Attribute) and inner.attr == name:
                    found.add(node.name)
    return found


# --- manifest (1-8) ---------------------------------------------------------------------


def test_manifest_canonical_hash_is_stable_across_tree_hash_insertion_order() -> None:
    forward = _manifest(dict(TREE_HASHES))
    reversed_hashes = dict(reversed(list(TREE_HASHES.items())))
    backward = _manifest(reversed_hashes)

    assert list(reversed_hashes) != list(TREE_HASHES)
    assert manifest_sha256(forward) == manifest_sha256(backward) == canonical_sha256(forward)
    assert len(manifest_sha256(forward)) == 64
    assert forward.historical_artifact_tree_hashes == TREE_HASHES


def test_manifest_expectations_sha256_is_the_canonical_expectations_document(
    manifest: ExperimentManifest,
) -> None:
    assert manifest.expectations_sha256 == canonical_sha256(expectations_document())
    assert manifest.expectations_sha256 == canonical_sha256(
        json.loads(pretty_json(expectations_document()))
    )


def test_manifest_corpus_evidence_and_needle_hashes_come_from_timeline_and_leakage(
    manifest: ExperimentManifest,
) -> None:
    assert manifest.corpus_sha256 == corpus_sha256()
    assert manifest.evidence == evidence_records()
    assert len(manifest.evidence) == 192
    assert manifest.leakage_needle_set_sha256 == needle_set_sha256()
    dumped = manifest.model_dump(mode="json")
    assert dumped["evidence"] == [record.model_dump(mode="json") for record in evidence_records()]


def test_manifest_historical_and_predecessor_fields_are_the_frozen_literals(
    manifest: ExperimentManifest,
) -> None:
    assert manifest.historical_preservation_base_sha == "43e5ea60cd92b700db4c58314a5ce68c50028169"
    assert manifest.historical_preservation_base_sha == HISTORICAL_PRESERVATION_BASE_SHA
    assert manifest.historical_preservation_base_sha != manifest.harness_code_sha
    assert manifest.historical_artifact_dirs == HISTORICAL_ARTIFACT_DIRS
    assert len(manifest.historical_artifact_dirs) == 6
    assert tuple(manifest.historical_artifact_tree_hashes) == HISTORICAL_ARTIFACT_DIRS
    assert manifest.predecessor_artifact_dir == PREDECESSOR_ARTIFACT_DIR
    assert manifest.predecessor_raw_evidence_sha == PREDECESSOR_RAW_EVIDENCE_SHA
    assert manifest.frozen_core_sha == FROZEN_CORE_SHA
    assert manifest.harness_code_sha == HARNESS_SHA
    assert manifest.spec_sha256 == SPEC_SHA256


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda h: {k: v for k, v in h.items() if k != HISTORICAL_ARTIFACT_DIRS[2]}, "missing"),
        (lambda h: {**h, "docs/superpowers/experiments/extra-dir/": "b" * 40}, "unexpected"),
        (lambda h: {**h, HISTORICAL_ARTIFACT_DIRS[0]: "not-a-sha"}, "40-hex"),
        (lambda h: {**h, HISTORICAL_ARTIFACT_DIRS[5]: "A" * 40}, "40-hex"),
    ],
    ids=["missing-dir", "extra-dir", "malformed-value", "uppercase-value"],
)
def test_build_manifest_refuses_missing_extra_or_malformed_tree_hashes(
    mutate: Any, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _manifest(mutate(dict(TREE_HASHES)))


def test_manifest_fields_keys_ceilings_schedule_and_rule_strings_are_the_contract(
    manifest: ExperimentManifest,
) -> None:
    assert tuple(ExperimentManifest.model_fields) == EXPECTED_MANIFEST_FIELDS
    dumped = manifest.model_dump(mode="json")
    assert set(REQUIRED_MANIFEST_KEYS) <= set(dumped)
    assert tuple(Ceilings.model_fields) == CEILING_KEYS
    assert dumped["ceilings"] == dict(LOCKED_CEILINGS)
    assert dumped["arm_schedule"] == [[t, arm] for t, arm in ARM_SCHEDULE]
    assert len(dumped["arm_schedule"]) == 48
    assert manifest.economy_rule == ECONOMY_RULE
    assert ECONOMY_RULE == "4*X_TOTAL <= 3*R_TOTAL for X in {F, A}, T2..T16 input tokens"
    assert BOUNDED_GROWTH_RULE == "X_LATE_MEAN <= 27/20 * X_EARLY_MEAN"
    assert R_GROWTH_RULE == "R_LATE_MEAN >= 3/2 * R_EARLY_MEAN"
    assert TOKEN_DIFF_RULE == "abs(F_TOTAL-A_TOTAL)/min(F_TOTAL,A_TOTAL) >= 1/20 is meaningful"
    assert manifest.bounded_growth_rule == BOUNDED_GROWTH_RULE
    assert manifest.r_growth_rule == R_GROWTH_RULE
    assert manifest.token_diff_rule == TOKEN_DIFF_RULE
    assert manifest.early_window == EARLY_WINDOW == (2, 3, 4, 5)
    assert manifest.late_window == LATE_WINDOW == (13, 14, 15, 16)
    assert manifest.decision_names == DECISION_NAMES
    assert manifest.experiment_version == EXPERIMENT_VERSION
    assert manifest.artifact_format_version == ARTIFACT_FORMAT_VERSION == 1
    assert manifest.spec_path == SPEC_PATH
    assert (
        SPEC_PATH == "docs/superpowers/specs/2026-09-13-9p3-long-horizon-bounded-memory-design.md"
    )
    assert manifest.final_seal_rule == FINAL_SEAL_RULE
    assert FINAL_SEAL_RULE == (
        "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; "
        "parent..HEAD may add only manifest.json and expectations.json"
    )
    assert manifest.lifecycle_project_id == PROJECT_ID
    assert manifest.scope == SCOPE
    assert manifest.grpc_dns_resolver == "native"
    assert (manifest.provider, manifest.model, manifest.reasoning_effort) == (
        PROVIDER,
        MODEL,
        REASONING_EFFORT,
    )
    assert EXPERIMENT_ARTIFACT_DIR == (
        "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"
    )
    sha_keys = [key for key in dumped if key.endswith(("_sha", "_sha256"))]
    assert not any("seal" in key for key in sha_keys)  # no self-referential seal sha


def test_manifest_identity_equals_the_frozen_literals(manifest: ExperimentManifest) -> None:
    assert manifest.fr_policy_version == FR_POLICY_VERSION_FROZEN == "intent-v2-9p2-v1"
    assert manifest.a_policy_version == A_POLICY_VERSION_FROZEN == "intent-v2-9p-v4"
    assert (
        manifest.fr_prompt_sha256
        == FR_PROMPT_SHA256_FROZEN
        == "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410"
    )
    assert (
        manifest.a_prompt_sha256
        == A_PROMPT_SHA256_FROZEN
        == "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"
    )
    assert (
        manifest.output_schema_sha256
        == OUTPUT_SCHEMA_SHA256_FROZEN
        == "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
    )


def test_manifest_built_here_passes_every_manifest_reading_preflight_gate(
    tmp_path: Path, manifest: ExperimentManifest, leakage_ok: LeakageResult, monkeypatch: Any
) -> None:
    """The manifest <-> integrity contract: the sealed pair written by this module is
    what T5's gates read. Gate 23 (offline R compilation) is stubbed for speed only."""
    monkeypatch.setattr(
        integrity_module, "r_context_within_bounds", lambda: (True, "stubbed for speed")
    )
    write_preregistration(tmp_path, manifest)
    expectations_bytes = (tmp_path / "expectations.json").read_bytes()
    sealed = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    sources = {
        name: (PACKAGE_DIR / name).read_text(encoding="utf-8") for name in REQUEST_PATH_MODULES
    }

    gates = preflight(
        git=FakeGit(),
        commands=FakeCommands(),
        frozen_sha=SEAL_SHA,
        manifest=sealed,
        expectations_bytes=expectations_bytes,
        request_path_sources=sources,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )
    by_name = {gate.name: gate for gate in gates}
    for name in (
        "fr_policy_is_9p2",
        "fr_prompt_hash_frozen",
        "a_policy_is_9p",
        "a_prompt_hash_frozen",
        "output_schema_hash_frozen",
        "evidence_manifest_frozen",
        "arm_schedule_frozen",
        "ceilings_frozen",
        "leakage_gate_passes",
        "historical_artifacts_unchanged",
        "grpc_dns_resolver_is_native",
        "predecessor_raw_evidence_unchanged",
    ):
        assert by_name[name].passed is True, (name, by_name[name].detail)
    assert all_passed(gates), [(g.name, g.detail) for g in gates if not g.passed]


# --- preregistration (9-10) ----------------------------------------------------------------


def test_write_preregistration_writes_exactly_two_files_with_canonical_hashes(
    tmp_path: Path, manifest: ExperimentManifest
) -> None:
    hashes = write_preregistration(tmp_path, manifest)

    assert PREREGISTRATION_FILE_NAMES == ("manifest.json", "expectations.json")
    assert _relative_files(tmp_path) == set(PREREGISTRATION_FILE_NAMES)
    assert set(hashes) == set(PREREGISTRATION_FILE_NAMES)
    manifest_text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    expectations_text = (tmp_path / "expectations.json").read_text(encoding="utf-8")
    assert manifest_text == pretty_json(manifest.model_dump(mode="json"))
    assert expectations_text == pretty_json(expectations_document())
    assert hashes["manifest.json"] == manifest_sha256(manifest)
    assert hashes["manifest.json"] == canonical_sha256(json.loads(manifest_text))
    assert hashes["expectations.json"] == manifest.expectations_sha256
    assert hashes["expectations.json"] == canonical_sha256(json.loads(expectations_text))
    assert manifest_text.endswith("\n") and expectations_text.endswith("\n")
    assert ExperimentManifest.model_validate(json.loads(manifest_text)) == manifest


def test_write_preregistration_is_all_or_nothing_when_either_file_exists(
    tmp_path: Path, manifest: ExperimentManifest
) -> None:
    (tmp_path / "manifest.json").write_text("opaque\n", encoding="utf-8")
    before = _tree_digest(tmp_path)
    with pytest.raises(FileExistsError, match="manifest.json"):
        write_preregistration(tmp_path, manifest)
    assert _tree_digest(tmp_path) == before
    (tmp_path / "manifest.json").unlink()

    (tmp_path / "expectations.json").write_text("opaque\n", encoding="utf-8")
    before = _tree_digest(tmp_path)
    with pytest.raises(FileExistsError, match="expectations.json"):
        write_preregistration(tmp_path, manifest)
    assert _tree_digest(tmp_path) == before
    (tmp_path / "expectations.json").unlink()

    drifted = manifest.model_copy(update={"expectations_sha256": "0" * 64})
    with pytest.raises(ValueError, match="expectations_sha256"):
        write_preregistration(tmp_path, drifted)
    assert _relative_files(tmp_path) == set()

    write_preregistration(tmp_path, manifest)
    before = _tree_digest(tmp_path)
    with pytest.raises(FileExistsError):
        write_preregistration(tmp_path, manifest)
    assert _tree_digest(tmp_path) == before


# --- requests (11-14) -------------------------------------------------------------------


def test_every_requests_entry_pairs_a_record_with_its_snapshot_in_cell_order(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage=leakage_ok)

    for arm in ("F", "A"):
        document = _read_json(tmp_path / arm / "requests.json")
        assert document["arm"] == arm
        cells = [cell for cell in completed.cells if cell.arm == arm]
        expected = [
            {
                "record": record.model_dump(mode="json"),
                "reference_snapshot": snapshot.model_dump(mode="json"),
            }
            for cell in cells
            for record, snapshot in zip(cell.requests, cell.reference_snapshots, strict=True)
        ]
        assert document["entries"] == expected
        assert len(document["entries"]) == 32
        assert [(e["record"]["t"], e["record"]["call_number"]) for e in document["entries"]] == [
            (t, c) for t in range(1, 17) for c in (1, 2)
        ]
    for t in range(1, 17):
        document = _read_json(tmp_path / "R" / f"T{t:02d}" / "requests.json")
        cell = completed.r_cells[t]
        assert document["arm"] == "R" and document["t"] == t
        assert len(document["entries"]) == 2
        for entry, record, snapshot in zip(
            document["entries"], cell.requests, cell.reference_snapshots, strict=True
        ):
            assert entry["record"] == record.model_dump(mode="json")
            assert entry["reference_snapshot"] == snapshot.model_dump(mode="json")
    for path in tmp_path.rglob("requests.json"):
        for entry in _read_json(path)["entries"]:
            record, snapshot = entry["record"], entry["reference_snapshot"]
            assert (
                record["arm"],
                record["t"],
                record["call_number"],
                record["request_sha256"],
            ) == (
                snapshot["arm"],
                snapshot["t"],
                snapshot["call_number"],
                snapshot["request_sha256"],
            )


def test_requests_preserve_exact_rendered_text_and_sha(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage=leakage_ok)

    f_document = _read_json(tmp_path / "F" / "requests.json")
    f_records = [record for cell in completed.cells if cell.arm == "F" for record in cell.requests]
    assert f_records == list(completed.f.requests)
    for entry, record in zip(f_document["entries"], f_records, strict=True):
        written = entry["record"]
        assert written["rendered_user_request"] == record.rendered_user_request
        assert written["request_sha256"] == record.request_sha256
        assert (
            hashlib.sha256(written["rendered_user_request"].encode("utf-8")).hexdigest()
            == record.request_sha256
        )
        assert json.loads(written["rendered_user_request"])
    r_document = _read_json(tmp_path / "R" / "T16" / "requests.json")
    r_records = completed.r_cells[16].requests
    for entry, record in zip(r_document["entries"], r_records, strict=True):
        assert entry["record"]["rendered_user_request"] == record.rendered_user_request
        assert entry["record"]["request_sha256"] == record.request_sha256


def test_requests_refuse_when_record_and_snapshot_counts_differ(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    cell = _cell(completed, "R", 9)
    short = cell.model_copy(update={"reference_snapshots": cell.reference_snapshots[:1]})
    gates = _gates()
    verdicts = _verdicts(completed, gates)
    write_preflight(
        tmp_path,
        gates,
        frozen_sha=SEAL_SHA,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )
    before = _tree_digest(tmp_path)

    with pytest.raises(ValueError, match="R T9"):
        write_run_artifacts(tmp_path, _with_cell(completed, short), verdicts)
    assert _tree_digest(tmp_path) == before
    assert _relative_files(tmp_path) == {"preflight.json"}

    f_cell = _cell(completed, "F", 4)
    long = f_cell.model_copy(
        update={"reference_snapshots": (*f_cell.reference_snapshots, f_cell.reference_snapshots[0])}
    )
    with pytest.raises(ValueError, match="F T4"):
        write_run_artifacts(tmp_path, _with_cell(completed, long), verdicts)
    assert _tree_digest(tmp_path) == before


def test_requests_refuse_when_record_and_snapshot_identity_disagree(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    cell = _cell(completed, "A", 7)
    first, second = cell.reference_snapshots
    wrong_sha = first.model_copy(update={"request_sha256": "f" * 64})
    verdicts = _verdicts(completed, _gates())

    with pytest.raises(ValueError, match="A T7"):
        write_run_artifacts(
            tmp_path,
            _with_cell(
                completed, cell.model_copy(update={"reference_snapshots": (wrong_sha, second)})
            ),
            verdicts,
        )
    assert _relative_files(tmp_path) == set()

    swapped = cell.model_copy(update={"reference_snapshots": (second, first)})
    with pytest.raises(ValueError, match="A T7"):
        write_run_artifacts(tmp_path, _with_cell(completed, swapped), verdicts)
    assert _relative_files(tmp_path) == set()


# --- measurements (15-16) -----------------------------------------------------------------


def test_measurements_rows_carry_null_for_persistent_arms_and_integers_for_r(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage=leakage_ok)
    document = _read_json(tmp_path / "measurements.json")

    rows = document["rows"]
    assert len(rows) == 96
    assert document["run_status"] == "COMPLETED"
    for row in rows:
        if row["arm"] in ("F", "A"):
            assert row["r_cumulative_raw_evidence_chars"] is None
        else:
            assert isinstance(row["r_cumulative_raw_evidence_chars"], int)
            assert row["r_cumulative_raw_evidence_chars"] > 0
    text = (tmp_path / "measurements.json").read_text(encoding="utf-8")
    assert '"r_cumulative_raw_evidence_chars": null' in text
    r_values = [r["r_cumulative_raw_evidence_chars"] for r in rows if r["arm"] == "R"]
    assert r_values == sorted(r_values)


def test_measurements_rows_round_trip_to_call_measurements_and_summarize(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage=leakage_ok)
    rows = _read_json(tmp_path / "measurements.json")["rows"]

    assert rows == [row.model_dump(mode="json") for row in completed.measurements]
    parsed = tuple(CallMeasurement.model_validate(row) for row in rows)
    assert parsed == completed.measurements
    assert summarize(parsed) == summarize(completed.measurements)


# --- raw tree (17-21) -----------------------------------------------------------------------


def test_raw_artifact_paths_are_the_116_path_contract() -> None:
    assert RAW_ARTIFACT_PATHS == EXPECTED_RAW_PATHS
    assert len(RAW_ARTIFACT_PATHS) == 116 == 4 + 16 + 96
    assert len(set(RAW_ARTIFACT_PATHS)) == 116
    assert RAW_ARTIFACT_PATHS[:4] == (
        "preflight.json",
        "measurements.json",
        "verdicts.json",
        "report.md",
    )
    assert sum(p.startswith("F/") for p in RAW_ARTIFACT_PATHS) == 8
    assert sum(p.startswith("A/") for p in RAW_ARTIFACT_PATHS) == 8
    assert sum(p.startswith("R/") for p in RAW_ARTIFACT_PATHS) == 96
    assert (
        "R/T09/ledger.json" in RAW_ARTIFACT_PATHS and "R/T9/ledger.json" not in RAW_ARTIFACT_PATHS
    )


def test_raw_tree_from_a_completed_run_equals_raw_artifact_paths_exactly(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    assert existing_raw_artifacts(tmp_path) == ()
    gates = _gates()
    path = write_preflight(
        tmp_path,
        gates,
        frozen_sha=SEAL_SHA,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )
    assert path == tmp_path / "preflight.json"
    assert existing_raw_artifacts(tmp_path) == ("preflight.json",)
    written = write_run_artifacts(tmp_path, completed, _verdicts(completed, gates))

    assert set(written) == set(RAW_ARTIFACT_PATHS) - {"preflight.json"}
    assert len(written) == 115
    assert _relative_files(tmp_path) == set(RAW_ARTIFACT_PATHS)
    assert existing_raw_artifacts(tmp_path) == RAW_ARTIFACT_PATHS
    assert not list(tmp_path.rglob("*.tmp"))
    for name in RAW_ARTIFACT_PATHS:
        if name.endswith(".json"):
            _read_json(tmp_path / name)


def test_f_and_a_folders_aggregate_sixteen_steps_and_r_folders_hold_one_cell_each(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage=leakage_ok)

    for arm, summary in (("F", completed.f), ("A", completed.a)):
        result = _read_json(tmp_path / arm / "result.json")
        assert result["arm"] == arm
        assert result["run_status"] == "COMPLETED"
        assert result["project_id"] == summary.project_id
        assert [s["t"] for s in result["steps"]] == list(range(1, 17))
        assert [s["status"] for s in result["steps"]] == ["COMPLETED"] * 16
        assert [s["position"] for s in result["steps"]] == [_position(arm, t) for t in range(1, 17)]
        assert all(len(s["calls"]) == 2 for s in result["steps"])
        assert sorted(result["roots"]) == sorted("ABCDEFGHIJKL")
        assert result["replay"]["status"] == "REPLAY_MATCH"
        assert result["request_count"] == 32
        assert result["ledger_event_count"] == len(summary.ledger)
        assert result["budget"] == completed.budget.model_dump(mode="json")
        ledger = _read_json(tmp_path / arm / "ledger.json")
        assert ledger["event_count"] == len(summary.ledger)
        assert ledger["events"] == [e.model_dump(mode="json") for e in summary.ledger]
        authorizations = _read_json(tmp_path / arm / "authorizations.json")
        assert authorizations["records"] == [
            a.model_dump(mode="json") for a in summary.authorizations
        ]
        eligible = _read_json(tmp_path / arm / "eligible_targets.json")
        assert eligible["snapshots"] == [
            e.model_dump(mode="json") for e in summary.eligible_targets
        ]
        assert [e["t"] for e in eligible["snapshots"]] == [3, 5, 7, 8, 10, 12, 14, 16]
        drafts = _read_json(tmp_path / arm / "drafts.json")
        assert len(drafts["drafts"]) == 32
        receipts = _read_json(tmp_path / arm / "receipts.json")
        assert len(receipts["receipts"]) == 32
        decisions = _read_json(tmp_path / arm / "decisions.json")
        assert [s["t"] for s in decisions["steps"]] == list(range(1, 17))
    for t in range(1, 17):
        cell = completed.r_cells[t]
        result = _read_json(tmp_path / "R" / f"T{t:02d}" / "result.json")
        assert (result["arm"], result["t"], result["status"]) == ("R", t, "COMPLETED")
        assert result["position"] == _position("R", t)
        assert result["project_id"] == f"PROJ-9P3-R-T{t:02d}"
        assert result["ledger_event_count"] == len(cell.ledger)
        assert len(result["calls"]) == 2
        ledger = _read_json(tmp_path / "R" / f"T{t:02d}" / "ledger.json")
        assert ledger["event_count"] == len(cell.ledger)
        assert ledger["project_id"] == cell.project_id


def test_aborted_run_writes_every_cell_with_not_run_results_and_measurements(
    tmp_path: Path, aborted: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, aborted, leakage=leakage_ok)

    assert _relative_files(tmp_path) == set(RAW_ARTIFACT_PATHS)
    for t in range(1, 17):
        result = _read_json(tmp_path / "R" / f"T{t:02d}" / "result.json")
        assert result["status"] == "NOT_RUN"
        assert result["run_status"] == "ABORTED_PROVIDER"
        assert result["error"] is None
        assert result["calls"] == []
        assert result["position"] == _position("R", t)
        assert _read_json(tmp_path / "R" / f"T{t:02d}" / "requests.json")["entries"] == []
        assert _read_json(tmp_path / "R" / f"T{t:02d}" / "ledger.json")["events"] == []
    f_result = _read_json(tmp_path / "F" / "result.json")
    assert f_result["run_status"] == "ABORTED_PROVIDER"
    assert [s["status"] for s in f_result["steps"]] == ["FAILED", *(["NOT_RUN"] * 15)]
    assert f_result["steps"][0]["error"] is not None
    assert len(_read_json(tmp_path / "F" / "requests.json")["entries"]) == 1
    a_result = _read_json(tmp_path / "A" / "result.json")
    assert [s["status"] for s in a_result["steps"]] == ["NOT_RUN"] * 16
    measurements = _read_json(tmp_path / "measurements.json")
    assert measurements["rows"] == []
    assert measurements["run_status"] == "ABORTED_PROVIDER"


def test_overwrite_refusal_is_all_or_nothing(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    gates = _gates(failing="worktree_clean", detail="dirty")
    write_preflight(
        tmp_path,
        gates,
        frozen_sha=SEAL_SHA,
        leakage=leakage_ok,
        observed_grpc_dns_resolver="native",
    )
    failed_preflight = _read_json(tmp_path / "preflight.json")
    assert failed_preflight["all_passed"] is False
    assert failed_preflight["run_status"] == "ABORTED_PREFLIGHT"
    assert failed_preflight["frontier_calls"] == 0
    before = _tree_digest(tmp_path)
    with pytest.raises(FileExistsError, match="preflight.json"):
        write_preflight(
            tmp_path,
            _gates(),
            frozen_sha=SEAL_SHA,
            leakage=leakage_ok,
            observed_grpc_dns_resolver="native",
        )
    assert _tree_digest(tmp_path) == before
    assert existing_raw_artifacts(tmp_path) == ("preflight.json",)

    stray = tmp_path / "R" / "T09" / "ledger.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("opaque\n", encoding="utf-8")
    before = _tree_digest(tmp_path)
    verdicts = _verdicts(completed, _gates())
    with pytest.raises(FileExistsError, match="R/T09/ledger.json"):
        write_run_artifacts(tmp_path, completed, verdicts)
    assert _tree_digest(tmp_path) == before
    assert existing_raw_artifacts(tmp_path) == ("preflight.json", "R/T09/ledger.json")

    stray.unlink()
    write_run_artifacts(tmp_path, completed, verdicts)
    before = _tree_digest(tmp_path)
    with pytest.raises(FileExistsError):
        write_run_artifacts(tmp_path, completed, verdicts)
    assert _tree_digest(tmp_path) == before


# --- secrets (22-23) -------------------------------------------------------------------


def test_secret_shaped_rendered_request_refuses_the_whole_write(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    verdicts = _verdicts(completed, _gates())
    cell = _cell(completed, "F", 2)
    poisoned_record = cell.requests[0].model_copy(
        update={"rendered_user_request": f'{{"api_key": "{SECRET_TOKEN}"}}'}
    )
    poisoned = _with_cell(
        completed, cell.model_copy(update={"requests": (poisoned_record, cell.requests[1])})
    )
    with pytest.raises(ValueError, match="rendered_user_request"):
        write_run_artifacts(tmp_path, poisoned, verdicts)
    assert _relative_files(tmp_path) == set()

    r_cell = _cell(completed, "R", 11)
    bearer = r_cell.requests[1].model_copy(
        update={"rendered_user_request": f"Authorization: Bearer {SECRET_TOKEN}"}
    )
    with pytest.raises(ValueError, match="rendered_user_request"):
        write_run_artifacts(
            tmp_path,
            _with_cell(
                completed, r_cell.model_copy(update={"requests": (r_cell.requests[0], bearer)})
            ),
            verdicts,
        )
    assert _relative_files(tmp_path) == set()

    summary_record = completed.a.requests[5].model_copy(
        update={"rendered_user_request": f"api_key={SECRET_TOKEN}"}
    )
    summary = completed.a.model_copy(
        update={
            "requests": (*completed.a.requests[:5], summary_record, *completed.a.requests[6:]),
        }
    )
    with pytest.raises(ValueError, match="rendered_user_request"):
        write_run_artifacts(tmp_path, completed.model_copy(update={"a": summary}), verdicts)
    assert _relative_files(tmp_path) == set()


def test_secret_shaped_error_text_is_redacted_and_never_persists(
    tmp_path: Path, aborted: RunResult, leakage_ok: LeakageResult
) -> None:
    assert SECRET_TOKEN in (aborted.error or "")
    failed_cell = _cell(aborted, "F", 1)
    assert failed_cell.error is not None and SECRET_TOKEN in failed_cell.error
    gates = _gates(failing="track_a_regression_passes", detail=f"auth failed for {SECRET_TOKEN}")
    _write_raw(tmp_path, aborted, gates=gates, leakage=leakage_ok)

    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET_TOKEN not in path.read_text(encoding="utf-8"), path
    verdicts = _read_json(tmp_path / "verdicts.json")
    assert verdicts["status"] == "ABORTED_PROVIDER"
    assert verdicts["error"].startswith("XAIProviderError: provider rejected key ")
    assert "[REDACTED]" in verdicts["error"]
    f_result = _read_json(tmp_path / "F" / "result.json")
    assert "[REDACTED]" in f_result["steps"][0]["error"]
    assert "[REDACTED]" in f_result["run_error"]
    preflight_document = _read_json(tmp_path / "preflight.json")
    failing = [g for g in preflight_document["gates"] if not g["passed"]]
    assert failing and "[REDACTED]" in failing[0]["detail"]
    assert "[REDACTED]" in (tmp_path / "report.md").read_text(encoding="utf-8")


# --- raw verdicts (24-31) ----------------------------------------------------------------


def test_raw_verdicts_carry_i1_to_i15_with_applicability(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    gates = _write_raw(tmp_path, completed, leakage=leakage_ok)
    verdicts = _read_json(tmp_path / "verdicts.json")
    expected = _verdicts(completed, gates)

    # pretty_json sorts keys on disk; the id set is the contract.
    assert set(verdicts["integrity"]) == set(VERDICT_IDS) == {f"I{n}" for n in range(1, 16)}
    assert len(verdicts["integrity"]) == 15
    for verdict in expected:
        written = verdicts["integrity"][verdict.id]
        assert written["passed"] is verdict.passed
        assert written["passed"] is True
        assert written["detail"] == verdict.detail
        assert written["applies_to"] == list(verdict.applies_to)
        # Matrix 26 / 28: failed_arms is serialised as a list for every id; [] on pass.
        assert written["failed_arms"] == list(verdict.failed_arms) == []
        assert set(written) == {"passed", "detail", "applies_to", "failed_arms"}
    assert verdicts["integrity"]["I13"]["applies_to"] == ["R"]
    assert verdicts["integrity"]["I1"]["applies_to"] == ["F", "A"]
    assert verdicts["artifact_format_version"] == ARTIFACT_FORMAT_VERSION
    assert verdicts["experiment_version"] == EXPERIMENT_VERSION


def test_raw_verdicts_semantic_fields_are_null_after_a_completed_run(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage=leakage_ok)
    verdicts = _read_json(tmp_path / "verdicts.json")

    assert verdicts["status"] == "COMPLETED"
    assert verdicts["error"] is None
    assert verdicts["budget"] == completed.budget.model_dump(mode="json")
    assert verdicts["budget"]["frontier_calls"] == 96
    for field in (
        "semantic_checkpoints",
        "material_errors",
        "control_errors",
        "errors_total",
        "architecture_selection",
    ):
        assert field in verdicts and verdicts[field] is None, field
    assert verdicts["adjudication"] == "architect adjudication pending"
    assert "selection_inputs" not in verdicts or verdicts["selection_inputs"] is None


def test_raw_report_names_the_pending_adjudication(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    _write_raw(tmp_path, completed, leakage=leakage_ok)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert (
        ADJUDICATION_PENDING_LINE
        == "architecture_selection = null (architect adjudication pending)"
    )
    assert ADJUDICATION_PENDING_LINE in report.splitlines()
    assert "COMPLETED" in report
    assert EXPERIMENT_VERSION in report
    assert report.count("| R |") >= 16 and report.count("| F |") >= 16
    for verdict_id in VERDICT_IDS:
        assert f"| {verdict_id} |" in report
    assert "frontier_calls: 96" in report
    for decision in DECISION_NAMES:
        assert f"architecture_selection = {decision}" not in report


def test_raw_writer_never_calls_select_architecture(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult, monkeypatch: Any
) -> None:
    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("select_architecture must never run on the raw path")

    monkeypatch.setattr(artifacts_module, "select_architecture", _forbidden)
    _write_raw(tmp_path, completed, leakage=leakage_ok)
    assert _relative_files(tmp_path) == set(RAW_ARTIFACT_PATHS)
    assert _read_json(tmp_path / "verdicts.json")["architecture_selection"] is None


def test_raw_writer_functions_never_reference_select_architecture_by_ast() -> None:
    referencing = _functions_referencing("select_architecture")
    assert referencing == {"write_adjudication"}
    raw_writers = {
        "write_preflight",
        "write_run_artifacts",
        "render_report",
        "verdicts_document",
        "_run_documents",
    }
    assert not raw_writers & referencing
    assert not raw_writers & _functions_referencing("SelectionInputs")
    assert not raw_writers & _functions_referencing("write_adjudication")
    tree = ast.parse(ARTIFACTS_SOURCE)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {
        "write_preflight",
        "write_run_artifacts",
        "write_adjudication",
        "render_report",
    } <= names


def test_raw_verdicts_require_the_fifteen_verdict_ids_in_order(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    verdicts = _verdicts(completed, _gates())
    with pytest.raises(ValueError, match="I1"):
        write_run_artifacts(tmp_path, completed, verdicts[1:])
    assert _relative_files(tmp_path) == set()
    with pytest.raises(ValueError):
        write_run_artifacts(tmp_path, completed, tuple(reversed(verdicts)))
    assert _relative_files(tmp_path) == set()


def test_aborted_run_verdicts_record_the_operational_status_and_stay_null(
    tmp_path: Path, aborted: RunResult, leakage_ok: LeakageResult
) -> None:
    gates = _write_raw(tmp_path, aborted, leakage=leakage_ok)
    verdicts = _read_json(tmp_path / "verdicts.json")
    expected = {v.id: v for v in _verdicts(aborted, gates)}

    assert verdicts["status"] == "ABORTED_PROVIDER"
    assert verdicts["integrity"]["I1"]["passed"] is False
    assert verdicts["integrity"]["I12"]["passed"] is expected["I12"].passed
    assert all(v["passed"] is not None for v in verdicts["integrity"].values())
    for field in ("semantic_checkpoints", "material_errors", "control_errors", "errors_total"):
        assert verdicts[field] is None
    assert verdicts["architecture_selection"] is None
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert ADJUDICATION_PENDING_LINE in report
    assert "ABORTED_PROVIDER" in report


def test_preflight_json_records_gates_leakage_and_the_observed_resolver_verbatim(
    tmp_path: Path, leakage_ok: LeakageResult
) -> None:
    gates = _gates()
    write_preflight(
        tmp_path, gates, frozen_sha=SEAL_SHA, leakage=leakage_ok, observed_grpc_dns_resolver=None
    )
    document = _read_json(tmp_path / "preflight.json")

    assert _relative_files(tmp_path) == {"preflight.json"}
    assert document["all_passed"] is True
    assert document["run_status"] is None
    assert document["frontier_calls"] == 0
    assert document["frozen_sha"] == SEAL_SHA
    assert document["observed_grpc_dns_resolver"] is None
    assert document["gates"] == [gate.model_dump(mode="json") for gate in gates]
    assert [g["name"] for g in document["gates"]] == list(GATE_NAMES)
    assert document["leakage"] == leakage_ok.model_dump(mode="json")
    assert document["experiment_version"] == EXPERIMENT_VERSION
    assert document["artifact_format_version"] == ARTIFACT_FORMAT_VERSION


# --- adjudication (32-40) ---------------------------------------------------------------


def test_adjudication_model_requires_exact_checkpoint_ids_and_nonnegative_counts() -> None:
    full = _adjudication()
    assert (
        tuple(full.checkpoints["F"]) == CHECKPOINT_IDS == tuple(f"C{t:02d}" for t in range(2, 17))
    )
    assert set(full.checkpoints) == set(full.control_errors) == set(full.material_errors)
    assert set(full.checkpoints) == {"F", "A", "R"}

    base = full.model_dump()
    for label, mutation in (
        ("missing-C16", lambda d: d["checkpoints"]["F"].pop("C16")),
        ("extra-C17", lambda d: d["checkpoints"]["A"].__setitem__("C17", True)),
        ("extra-C01", lambda d: d["checkpoints"]["A"].__setitem__("C01", True)),
        ("negative-control", lambda d: d["control_errors"].__setitem__("F", -1)),
        ("negative-material", lambda d: d["material_errors"].__setitem__("A", -2)),
        ("missing-A-checkpoints", lambda d: d["checkpoints"].pop("A")),
        ("missing-F-control", lambda d: d["control_errors"].pop("F")),
        ("missing-A-material", lambda d: d["material_errors"].pop("A")),
        ("missing-R-checkpoints", lambda d: d["checkpoints"].pop("R")),
        ("missing-R-control", lambda d: d["control_errors"].pop("R")),
        ("missing-R-material", lambda d: d["material_errors"].pop("R")),
        ("unknown-arm", lambda d: d["material_errors"].__setitem__("X", 0)),
        ("non-bool-checkpoint", lambda d: d["checkpoints"]["F"].__setitem__("C02", "PASS")),
    ):
        mutated = json.loads(json.dumps(base))
        mutation(mutated)
        with pytest.raises(ValidationError):
            Adjudication.model_validate(mutated)
            pytest.fail(f"{label}: accepted")


def test_write_adjudication_refuses_when_head_differs(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage=leakage_ok)
    git = _commit(out_dir, tmp_path)
    git._head = "9" * 40
    before = _tree_digest(out_dir)

    with pytest.raises(AdjudicationRefused, match="HEAD"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=git,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert _tree_digest(out_dir) == before
    assert _read_json(out_dir / "verdicts.json")["architecture_selection"] is None


def test_write_adjudication_refuses_a_dirty_worktree(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage=leakage_ok)
    git = _commit(out_dir, tmp_path)
    git._dirty = " M src/foundry/experiments/long_horizon_bounded/runner.py\n"
    before = _tree_digest(out_dir)

    with pytest.raises(AdjudicationRefused, match="dirty"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=git,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert _tree_digest(out_dir) == before


def test_write_adjudication_refuses_when_a_raw_file_is_missing_or_differs(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage=leakage_ok)
    git = _commit(out_dir, tmp_path)

    drafts = out_dir / "R" / "T05" / "drafts.json"
    original = drafts.read_bytes()
    drafts.unlink()
    before = _tree_digest(out_dir)
    with pytest.raises(AdjudicationRefused, match="R/T05/drafts.json"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=git,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert _tree_digest(out_dir) == before
    drafts.write_bytes(original)

    ledger = out_dir / "F" / "ledger.json"
    ledger.write_bytes(ledger.read_bytes() + b"\n")
    before = _tree_digest(out_dir)
    with pytest.raises(AdjudicationRefused, match="F/ledger.json"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=git,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert _tree_digest(out_dir) == before
    assert _read_json(out_dir / "verdicts.json")["architecture_selection"] is None

    unknown = FakeGit(head=RAW_RUN_SHA, show={})
    with pytest.raises(AdjudicationRefused):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=unknown,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )
    assert _tree_digest(out_dir) == before


def test_write_adjudication_rewrites_only_verdicts_and_report(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage=leakage_ok)
    git = _commit(out_dir, tmp_path)
    before = _tree_digest(out_dir)
    assert set(before) == set(RAW_ARTIFACT_PATHS)

    written = write_adjudication(
        out_dir,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=git,
        adjudication=_adjudication(),
        repo_root=tmp_path,
    )
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


def test_write_adjudication_fills_semantic_fields_and_selection_from_committed_measurements(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    gates = _write_raw(out_dir, completed, leakage=leakage_ok)
    raw_verdicts = _read_json(out_dir / "verdicts.json")
    git = _commit(out_dir, tmp_path)
    adjudication = _adjudication()

    write_adjudication(
        out_dir,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=git,
        adjudication=adjudication,
        repo_root=tmp_path,
    )
    verdicts = _read_json(out_dir / "verdicts.json")

    assert verdicts["semantic_checkpoints"] == adjudication.checkpoints
    assert verdicts["material_errors"] == adjudication.material_errors
    assert verdicts["control_errors"] == adjudication.control_errors
    assert verdicts["errors_total"] == {"F": 0, "A": 1, "R": 3}
    assert verdicts["errors_total"]["R"] == 3
    assert verdicts["selection_inputs"]["errors_R"] == 3
    assert verdicts["adjudication_notes"] == adjudication.notes
    assert verdicts["raw_run_commit_sha"] == RAW_RUN_SHA
    assert verdicts["integrity"] == raw_verdicts["integrity"]
    assert verdicts["status"] == "COMPLETED" and verdicts["budget"] == raw_verdicts["budget"]

    rows = tuple(
        CallMeasurement.model_validate(row)
        for row in _read_json(out_dir / "measurements.json")["rows"]
    )
    tokens = summarize(rows)
    expected_verdicts = _verdicts(completed, gates)
    inputs = SelectionInputs(
        completed=True,
        scientifically_valid=True,
        errors_F=0,
        errors_A=1,
        errors_R=3,
        # Spec §16.1: attribution, never static scope. Every verdict passed here, so
        # no arm-attributable failed verdict names F or A.
        integrity_F=not any(v.passed is False and "F" in v.failed_arms for v in expected_verdicts),
        integrity_A=not any(v.passed is False and "A" in v.failed_arms for v in expected_verdicts),
        f_total=tokens.f_total,
        a_total=tokens.a_total,
        r_total=tokens.r_total,
        f_early_mean=tokens.f_early_mean,
        f_late_mean=tokens.f_late_mean,
        a_early_mean=tokens.a_early_mean,
        a_late_mean=tokens.a_late_mean,
        r_early_mean=tokens.r_early_mean,
        r_late_mean=tokens.r_late_mean,
    )
    assert inputs.integrity_F and inputs.integrity_A
    outcome = select_architecture(inputs)
    assert verdicts["selection_inputs"] == inputs.model_dump(mode="json")
    assert verdicts["architecture_selection"] == outcome.model_dump(mode="json")
    # Scripted receipts carry equal token counts for every call: F is the only acceptable
    # arm (A has one material error), bounded but not economical, and R does not grow.
    assert tokens.f_total == tokens.a_total == tokens.r_total > 0
    assert outcome.decision == "SCALE_NOT_YET_PROVEN" and outcome.matched_rule == "2C"
    assert verdicts["architecture_selection"]["decision"] == "SCALE_NOT_YET_PROVEN"
    assert verdicts["token_summary"] == tokens.model_dump(mode="json")
    assert "token_summary_error" not in verdicts

    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert ADJUDICATION_PENDING_LINE not in report
    assert "architecture_selection = SCALE_NOT_YET_PROVEN" in report
    assert "2C" in report and RAW_RUN_SHA in report
    assert "scripted adjudication \\| with a pipe and a newline" in report
    assert "| C16 |" in report


def test_write_adjudication_derives_scientific_validity_from_preflight_and_verdicts(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    # (a) a failed preflight gate outside I13/I14 -> all_passed false -> rule 0.
    repo_a = tmp_path / "a"
    out_a = repo_a / EXPERIMENT_ARTIFACT_DIR
    _write_raw(
        out_a, completed, gates=_gates(failing="track_a_regression_passes"), leakage=leakage_ok
    )
    write_adjudication(
        out_a,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=_commit(out_a, repo_a),
        adjudication=_adjudication(material_errors={"F": 0, "A": 0, "R": 0}),
        repo_root=repo_a,
    )
    verdicts_a = _read_json(out_a / "verdicts.json")
    assert verdicts_a["selection_inputs"]["completed"] is True
    assert verdicts_a["selection_inputs"]["scientifically_valid"] is False
    assert verdicts_a["architecture_selection"]["decision"] == "EXPERIMENT_INCONCLUSIVE"
    assert verdicts_a["architecture_selection"]["matched_rule"] == "0"

    # (b) an experiment-wide verdict (I14 via its preflight gate) fails -> rule 0.
    repo_b = tmp_path / "b"
    out_b = repo_b / EXPERIMENT_ARTIFACT_DIR
    gates_b = _gates(failing="leakage_gate_passes")
    _write_raw(out_b, completed, gates=gates_b, leakage=leakage_ok)
    assert _read_json(out_b / "verdicts.json")["integrity"]["I14"]["passed"] is False
    write_adjudication(
        out_b,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=_commit(out_b, repo_b),
        adjudication=_adjudication(material_errors={"F": 0, "A": 0, "R": 0}),
        repo_root=repo_b,
    )
    verdicts_b = _read_json(out_b / "verdicts.json")
    assert verdicts_b["integrity"]["I14"]["failed_arms"] == []
    assert verdicts_b["selection_inputs"]["scientifically_valid"] is False
    # I14 is experiment-wide and names no arm (spec §12.1): it invalidates the
    # experiment through rule 0, not F's per-arm integrity (T8A; formerly asserted
    # False through the static-applicability contamination).
    assert verdicts_b["selection_inputs"]["integrity_F"] is True
    assert verdicts_b["selection_inputs"]["integrity_A"] is True
    assert verdicts_b["architecture_selection"]["decision"] == "EXPERIMENT_INCONCLUSIVE"
    assert verdicts_b["architecture_selection"]["matched_rule"] == "0"

    # (c) a clean raw tree with both arms perfect -> the tie/economy rules are reached.
    repo_c = tmp_path / "c"
    out_c = repo_c / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_c, completed, leakage=leakage_ok)
    write_adjudication(
        out_c,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=_commit(out_c, repo_c),
        adjudication=_adjudication(material_errors={"F": 0, "A": 0, "R": 0}),
        repo_root=repo_c,
    )
    verdicts_c = _read_json(out_c / "verdicts.json")
    assert verdicts_c["selection_inputs"]["scientifically_valid"] is True
    assert verdicts_c["selection_inputs"]["errors_F"] == 0
    assert verdicts_c["selection_inputs"]["errors_A"] == 0
    assert verdicts_c["architecture_selection"]["matched_rule"] == "3C.a"
    assert verdicts_c["architecture_selection"]["decision"] == "SCALE_NOT_YET_PROVEN"
    assert set(verdicts_c["architecture_selection"]["predicates"]) == {
        "acceptable_F",
        "acceptable_A",
        "bounded_F",
        "bounded_A",
        "economy_F",
        "economy_A",
        "r_grows",
        "token_diff",
    }


def test_write_adjudication_refuses_a_non_completed_run_with_nothing_written(
    tmp_path: Path, aborted: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, aborted, leakage=leakage_ok)
    assert _read_json(out_dir / "verdicts.json")["status"] == "ABORTED_PROVIDER"
    fake = _commit(out_dir, tmp_path)
    before = _tree_digest(out_dir)
    assert set(before) == set(RAW_ARTIFACT_PATHS)

    with pytest.raises(AdjudicationRefused, match="ABORTED_PROVIDER"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=fake,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )

    assert _tree_digest(out_dir) == before
    assert not list(out_dir.rglob("*.tmp"))
    verdicts = _read_json(out_dir / "verdicts.json")
    assert verdicts["phase"] == "raw"
    assert verdicts["architecture_selection"] is None
    assert verdicts["selection_inputs"] is None
    assert "token_summary" not in verdicts and "token_summary_error" not in verdicts
    assert ADJUDICATION_PENDING_LINE in (out_dir / "report.md").read_text(encoding="utf-8")


def test_write_adjudication_refuses_unsummarisable_committed_measurements(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage=leakage_ok)
    measurements_path = out_dir / "measurements.json"
    document = _read_json(measurements_path)
    assert len(document["rows"]) == 96
    document["rows"] = document["rows"][:-1]  # one call removed: summarize must refuse
    measurements_path.write_text(pretty_json(document), encoding="utf-8")
    fake = _commit(out_dir, tmp_path)  # the truncated bytes ARE the committed bytes
    before = _tree_digest(out_dir)
    assert _read_json(out_dir / "verdicts.json")["status"] == "COMPLETED"

    with pytest.raises(AdjudicationRefused, match="MeasurementMismatch"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=fake,
            adjudication=_adjudication(),
            repo_root=tmp_path,
        )

    assert _tree_digest(out_dir) == before
    assert not list(out_dir.rglob("*.tmp"))
    verdicts = _read_json(out_dir / "verdicts.json")
    assert verdicts["phase"] == "raw" and verdicts["architecture_selection"] is None
    assert verdicts["selection_inputs"] is None
    assert "token_summary" not in verdicts and "token_summary_error" not in verdicts
    assert ADJUDICATION_PENDING_LINE in (out_dir / "report.md").read_text(encoding="utf-8")


def test_no_historical_experiment_dir_is_touched_by_raw_or_adjudication_writes(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    for index, directory in enumerate(HISTORICAL_ARTIFACT_DIRS):
        historical = tmp_path / directory
        historical.mkdir(parents=True)
        (historical / "manifest.json").write_text(f'{{"frozen": {index}}}\n', encoding="utf-8")
        (historical / "verdicts.json").write_text('{"frozen": true}\n', encoding="utf-8")
    predecessor = tmp_path / PREDECESSOR_ARTIFACT_DIR
    assert predecessor.exists()
    docs = tmp_path / "docs"
    before = _tree_digest(docs)
    assert len(before) == 12

    out_dir = tmp_path / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage=leakage_ok)
    write_adjudication(
        out_dir,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=_commit(out_dir, tmp_path),
        adjudication=_adjudication(),
        repo_root=tmp_path,
    )

    after = _tree_digest(docs)
    experiment_prefix = EXPERIMENT_ARTIFACT_DIR.removeprefix("docs/")
    assert {k: v for k, v in after.items() if not k.startswith(experiment_prefix)} == before
    assert all(k.startswith(experiment_prefix) for k in set(after) - set(before))
    assert not any(EXPERIMENT_ARTIFACT_DIR.startswith(d) for d in HISTORICAL_ARTIFACT_DIRS)
    tree = ast.parse(ARTIFACTS_SOURCE)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not any(directory in literals for directory in HISTORICAL_ARTIFACT_DIRS)


def test_write_adjudication_requires_out_dir_inside_repo_root_and_is_the_only_selector(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "elsewhere" / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, completed, leakage=leakage_ok)
    before = _tree_digest(out_dir)
    with pytest.raises(ValueError, match="repo_root"):
        write_adjudication(
            out_dir,
            raw_run_commit_sha=RAW_RUN_SHA,
            git=FakeGit(head=RAW_RUN_SHA),
            adjudication=_adjudication(),
            repo_root=repo_root,
        )
    assert _tree_digest(out_dir) == before
    assert _functions_referencing("select_architecture") == {"write_adjudication"}
    assert issubclass(AdjudicationRefused, RuntimeError)


# --- T8A: failed_arms serialisation and attribution-based selection inputs -----------------
# (spec §10.5, §12.1, §16.1, §16.2 rule 0; architect amendment 562ea45)


def _adjudicated_with(
    repo: Path,
    run: RunResult,
    leakage: LeakageResult,
    *,
    edits: dict[str, dict[str, Any]] | None = None,
    gates: tuple[GateResult, ...] | None = None,
    adjudication: Adjudication | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write the raw tree, rewrite the COMMITTED ``verdicts.json`` integrity entries in
    ``edits`` (``{id: {"passed": ..., "failed_arms": [...], ...}}``) identically on disk
    and in the FakeGit table (so the byte-identity guard still passes), adjudicate with
    F/A/R error counts of zero unless given, and return ``(committed raw document,
    adjudicated document)``."""
    out_dir = repo / EXPERIMENT_ARTIFACT_DIR
    _write_raw(out_dir, run, gates=gates, leakage=leakage)
    path = out_dir / "verdicts.json"
    document = _read_json(path)
    for verdict_id, fields in (edits or {}).items():
        document["integrity"][verdict_id].update(fields)
    path.write_text(pretty_json(document), encoding="utf-8")
    git = _commit(out_dir, repo)  # the rewritten bytes ARE the committed bytes
    committed = _read_json(path)
    write_adjudication(
        out_dir,
        raw_run_commit_sha=RAW_RUN_SHA,
        git=git,
        adjudication=adjudication
        if adjudication is not None
        else _adjudication(
            material_errors={"F": 0, "A": 0, "R": 0}, control_errors={"F": 0, "A": 0, "R": 0}
        ),
        repo_root=repo,
    )
    return committed, _read_json(path)


def _selection(document: dict[str, Any]) -> tuple[bool, bool, bool, str, str]:
    inputs = document["selection_inputs"]
    outcome = document["architecture_selection"]
    return (
        inputs["integrity_F"],
        inputs["integrity_A"],
        inputs["scientifically_valid"],
        outcome["decision"],
        outcome["matched_rule"],
    )


def test_experiment_wide_verdict_ids_are_pinned_and_the_raw_contract_is_unchanged() -> None:
    assert EXPERIMENT_WIDE_VERDICT_IDS == ("I2", "I3", "I12", "I13", "I14")
    assert len(RAW_ARTIFACT_PATHS) == 116
    assert ARTIFACT_FORMAT_VERSION == 1
    # One definition only: the constant is assigned exactly once in the module.
    tree = ast.parse(ARTIFACTS_SOURCE)
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "EXPERIMENT_WIDE_VERDICT_IDS"
    ]
    assert len(assignments) == 1


def test_raw_verdicts_serialise_failed_arms_for_every_id_including_a_failed_one(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 26 / 28: a list for all fifteen ids; [] on pass; the attributed tuple
    on a failure (I13 via its preflight gate -> ["R"]; I14 -> [])."""
    for failing, expected in ((GATE_I13_NAME, ["R"]), (GATE_I14_NAME, [])):
        out_dir = tmp_path / failing
        _write_raw(out_dir, completed, gates=_gates(failing=failing), leakage=leakage_ok)
        integrity = _read_json(out_dir / "verdicts.json")["integrity"]
        assert set(integrity) == set(VERDICT_IDS)
        for verdict_id, entry in integrity.items():
            assert isinstance(entry["failed_arms"], list), verdict_id
            if entry["passed"] is True:
                assert entry["failed_arms"] == [], verdict_id
        failed_id = "I13" if failing == GATE_I13_NAME else "I14"
        assert integrity[failed_id]["passed"] is False
        assert integrity[failed_id]["failed_arms"] == expected


def test_raw_report_table_carries_the_failed_arms_column(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 27."""
    _write_raw(tmp_path, completed, gates=_gates(failing=GATE_I13_NAME), leakage=leakage_ok)
    report = (tmp_path / "report.md").read_text(encoding="utf-8").splitlines()
    assert "| id | passed | applies_to | failed_arms | detail |" in report
    header = report.index("| id | passed | applies_to | failed_arms | detail |")
    assert report[header + 1] == "|---|---|---|---|---|"
    rows = {line.split(" | ")[0].strip("| "): line for line in report[header + 2 : header + 17]}
    assert set(rows) == set(VERDICT_IDS)
    assert rows["I13"].startswith("| I13 | false | R | R | ")
    assert rows["I1"].startswith("| I1 | true | F,A | - | ")


def test_f_only_arm_local_failure_disqualifies_f_only(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 29 (spec §16.1 example 1): I10 failed, failed_arms (F,) -> A proceeds
    under rule 2."""
    _, document = _adjudicated_with(
        tmp_path, completed, leakage_ok, edits={"I10": {"passed": False, "failed_arms": ["F"]}}
    )
    integrity_f, integrity_a, valid, decision, rule = _selection(document)
    assert (integrity_f, integrity_a, valid) == (False, True, True)
    assert rule.startswith("2") and decision != "EXPERIMENT_INCONCLUSIVE"
    assert document["architecture_selection"]["predicates"]["acceptable_F"] is False
    assert document["architecture_selection"]["predicates"]["acceptable_A"] is True


def test_a_only_arm_local_failure_disqualifies_a_only(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 30 (example 2): I9 failed, failed_arms (A,) -> rule 2 with X = F."""
    _, document = _adjudicated_with(
        tmp_path, completed, leakage_ok, edits={"I9": {"passed": False, "failed_arms": ["A"]}}
    )
    integrity_f, integrity_a, valid, decision, rule = _selection(document)
    assert (integrity_f, integrity_a, valid) == (True, False, True)
    assert rule.startswith("2") and decision != "EXPERIMENT_INCONCLUSIVE"
    assert document["architecture_selection"]["predicates"]["acceptable_F"] is True
    assert document["architecture_selection"]["predicates"]["acceptable_A"] is False


def test_f_and_a_arm_local_failure_reaches_rule_1(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 31 (example 3): I6 failed, failed_arms (F, A) -> rule 1."""
    _, document = _adjudicated_with(
        tmp_path, completed, leakage_ok, edits={"I6": {"passed": False, "failed_arms": ["F", "A"]}}
    )
    assert _selection(document) == (False, False, True, "REDESIGN_PERSISTENT_CONTEXT", "1")


@pytest.mark.parametrize(
    ("verdict_id", "failed_arms", "label"),
    [
        ("I10", ["R"], "matrix 32: R-only"),
        ("I10", ["F", "R"], "matrix 33: F+R, R attribution dominates"),
        ("I4", [], "matrix 34: unattributed failure"),
        ("I3", ["F"], "matrix 35: experiment-wide despite naming F"),
    ],
)
def test_r_attributed_unattributed_and_experiment_wide_failures_invoke_rule_0(
    tmp_path: Path,
    completed: RunResult,
    leakage_ok: LeakageResult,
    verdict_id: str,
    failed_arms: list[str],
    label: str,
) -> None:
    _, document = _adjudicated_with(
        tmp_path,
        completed,
        leakage_ok,
        edits={verdict_id: {"passed": False, "failed_arms": failed_arms}},
    )
    _, _, valid, decision, rule = _selection(document)
    assert (valid, decision, rule) == (False, "EXPERIMENT_INCONCLUSIVE", "0"), label
    assert document["integrity"][verdict_id]["failed_arms"] == failed_arms


def test_i13_and_i14_failures_invoke_rule_0(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 36 / 37, through the real preflight-gate consumption."""
    for gate_name, verdict_id, expected in (
        (GATE_I13_NAME, "I13", ["R"]),
        (GATE_I14_NAME, "I14", []),
    ):
        _, document = _adjudicated_with(
            tmp_path / gate_name, completed, leakage_ok, gates=_gates(failing=gate_name)
        )
        assert document["integrity"][verdict_id]["passed"] is False
        assert document["integrity"][verdict_id]["failed_arms"] == expected
        integrity_f, integrity_a, valid, decision, rule = _selection(document)
        assert (integrity_f, integrity_a) == (True, True)  # not arm-attributable
        assert (valid, decision, rule) == (False, "EXPERIMENT_INCONCLUSIVE", "0")


def test_errors_r_is_report_only_and_never_a_selection_input(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 38 (example 8)."""
    _, clean = _adjudicated_with(tmp_path / "zero", completed, leakage_ok)
    _, with_r = _adjudicated_with(
        tmp_path / "one",
        completed,
        leakage_ok,
        adjudication=_adjudication(
            material_errors={"F": 0, "A": 0, "R": 0}, control_errors={"F": 0, "A": 0, "R": 1}
        ),
    )
    assert all(v["passed"] is True for v in with_r["integrity"].values())
    assert with_r["errors_total"]["R"] == 1 and clean["errors_total"]["R"] == 0
    assert with_r["selection_inputs"]["errors_R"] == 1
    assert with_r["selection_inputs"]["scientifically_valid"] is True
    assert with_r["architecture_selection"] == clean["architecture_selection"]
    differing = {
        key
        for key in clean["selection_inputs"]
        if clean["selection_inputs"][key] != with_r["selection_inputs"][key]
    }
    assert differing == {"errors_R"}
    assert clean["selection_inputs"]["integrity_F"] is True
    assert clean["selection_inputs"]["integrity_A"] is True


def test_static_applicability_never_contaminates_a_sibling_arm(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 39 -- the core regression for the architecture ambiguity: I10 failed
    with applies_to [F, A, R] but failed_arms [F] leaves A's integrity intact."""
    _, document = _adjudicated_with(
        tmp_path,
        completed,
        leakage_ok,
        edits={"I10": {"passed": False, "failed_arms": ["F"], "applies_to": ["F", "A", "R"]}},
    )
    assert document["integrity"]["I10"]["applies_to"] == ["F", "A", "R"]
    assert document["selection_inputs"]["integrity_A"] is True
    assert document["selection_inputs"]["integrity_F"] is False
    assert document["selection_inputs"]["scientifically_valid"] is True
    assert document["architecture_selection"]["matched_rule"] != "0"


def test_adjudication_keeps_every_raw_integrity_entry_semantically_identical(
    tmp_path: Path, completed: RunResult, leakage_ok: LeakageResult
) -> None:
    """Matrix 40: the adjudicated document keeps every raw ``integrity[<id>]`` entry
    (``passed``, ``applies_to``, ``failed_arms``, ``detail``) semantically identical to
    the committed raw document while adding the semantic fields and the selection."""
    committed, document = _adjudicated_with(
        tmp_path, completed, leakage_ok, edits={"I9": {"passed": False, "failed_arms": ["A"]}}
    )
    assert committed["phase"] == "raw" and document["phase"] == "adjudicated"
    assert set(committed["integrity"]) == set(document["integrity"]) == set(VERDICT_IDS)
    for verdict_id in VERDICT_IDS:
        raw_entry, adjudicated_entry = (
            committed["integrity"][verdict_id],
            document["integrity"][verdict_id],
        )
        assert set(raw_entry) == {"passed", "detail", "applies_to", "failed_arms"}, verdict_id
        assert adjudicated_entry == raw_entry, verdict_id
    assert document["integrity"]["I9"]["passed"] is False
    assert document["integrity"]["I9"]["failed_arms"] == ["A"]
    assert document["integrity"]["I9"]["applies_to"] == ["F", "A", "R"]
    assert document["selection_inputs"]["integrity_A"] is False
    for field in ("semantic_checkpoints", "material_errors", "control_errors", "errors_total"):
        assert committed[field] is None and document[field] is not None, field
    assert committed["architecture_selection"] is None
    assert document["architecture_selection"]["matched_rule"] != "0"


def _called_module_functions(
    function: ast.FunctionDef, module: ast.Module
) -> list[ast.FunctionDef]:
    """``function`` plus every module-level function it calls, transitively."""
    by_name = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
    seen: dict[str, ast.FunctionDef] = {}
    pending = [function]
    while pending:
        current = pending.pop()
        if current.name in seen:
            continue
        seen[current.name] = current
        for node in ast.walk(current):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                callee = by_name.get(node.func.id)
                if callee is not None and callee.name not in seen:
                    pending.append(callee)
    return list(seen.values())


def test_selection_inputs_never_consult_applies_to() -> None:
    """The old contamination path is impossible: neither ``_selection_inputs`` nor
    any helper it calls subscripts or reads ``applies_to``; ``failed_arms`` is read."""
    module = ast.parse(ARTIFACTS_SOURCE)
    (selection,) = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_selection_inputs"
    ]
    reads: set[str] = set()
    for function in _called_module_functions(selection, module):
        for node in ast.walk(function):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                reads.add(node.value)
            if isinstance(node, ast.Attribute):
                reads.add(node.attr)
    assert "applies_to" not in reads
    assert "failed_arms" in reads
    assert "EXPERIMENT_WIDE_VERDICT_IDS" in {
        node.id for node in ast.walk(selection) if isinstance(node, ast.Name)
    }
