"""Machine-verifiable contestant freeze for the Intent Intelligence comparative exam.

This is evaluation infrastructure, not Intent Intelligence. It deliberately lives under
``foundry.evaluation`` because it must inspect both provider adapters; the core
``foundry.intelligence`` package stays provider-neutral.

Scope note: this module freezes CONTESTANTS ONLY. Holdout inputs, the hidden judge
bundle, the judge commitment, the adjudication mechanism, and the execution-order
assignment do not exist yet and are therefore absent by design. Task 9J completes the
full ``ExperimentManifest`` on top of this record.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from foundry.adapters.intelligence.xai import _SYSTEM_INSTRUCTION as _FOUNDRY_INSTRUCTION
from foundry.adapters.intelligence.xai import _render_worker_input
from foundry.adapters.intelligence.xai import _source_record as _foundry_source_record
from foundry.adapters.intelligence.xai_baseline import (
    _BASELINE_SYSTEM_INSTRUCTION as _BASELINE_INSTRUCTION,
)
from foundry.domain.common import FrozenModel
from foundry.intelligence.baseline import BaselinePayload
from foundry.intelligence.comparison import BlindPrediction
from foundry.intelligence.proposals import IntentIntelligencePayload
from foundry.intelligence.source_records import _source_record as _baseline_source_record
from foundry.intelligence.source_records import render_source_records

MANIFEST_VERSION = "contestant-freeze-v1"

# Declared experimental identities. These are commit identities, not values this module
# derives from the working tree. Content digests are the executable proof that the files
# still correspond to the frozen behaviour.
CONTESTANT_A_COMMIT = "2d75532afbbe25913d5550483d3363f3df4cb754"
CONTESTANT_B_COMMIT = "11dd47485bb6f7079cf2b31077ee7cbe988936fc"
COMPARATIVE_SPEC_COMMIT = "ed11848e322dd9be8e1e606c2e2fcc59d89c086a"

COMPARATIVE_SPEC_PATH = (
    "docs/superpowers/specs/2026-09-10-intent-intelligence-comparative-exam-design.md"
)
COMPARISON_MODULE_PATH = "src/foundry/intelligence/comparison.py"

PROVIDER = "xAI"
MODEL = "grok-4.6"
REASONING_EFFORT = "high"
TIMEOUT_SECONDS = 3600
SDK_PACKAGE = "xai-sdk"

FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID = "component:foundry-system-instruction"
FOUNDRY_SCHEMA_ARTIFACT_ID = "component:foundry-payload-schema"
FOUNDRY_RENDERER_ARTIFACT_ID = "component:foundry-input-renderer"

BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID = "component:baseline-system-instruction"
BASELINE_SCHEMA_ARTIFACT_ID = "component:baseline-payload-schema"
BASELINE_RENDERER_ARTIFACT_ID = "component:baseline-source-renderer"

FOUNDRY_FILES: tuple[str, ...] = (
    "src/foundry/intelligence/input.py",
    "src/foundry/intelligence/compiler.py",
    "src/foundry/intelligence/proposals.py",
    "src/foundry/intelligence/validation.py",
    "src/foundry/intelligence/eval_adapter.py",
    "src/foundry/adapters/intelligence/xai.py",
    "src/foundry/domain/gaps.py",
)

BASELINE_FILES: tuple[str, ...] = (
    "src/foundry/intelligence/input.py",
    "src/foundry/intelligence/baseline.py",
    "src/foundry/intelligence/baseline_validation.py",
    "src/foundry/intelligence/source_records.py",
    "src/foundry/adapters/intelligence/xai_baseline.py",
    "src/foundry/domain/gaps.py",
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"

_CONTESTANT_FIELDS: tuple[str, ...] = (
    "contestant_id",
    "commit_sha",
    "provider",
    "model",
    "reasoning_effort",
    "timeout_seconds",
    "tools_enabled",
    "research_enabled",
    "persistent_conversation",
    "sdk_retries_enabled",
    "semantic_retries_enabled",
    "sdk_package",
    "sdk_version",
)

_EVALUATION_BASE_FIELDS: tuple[str, ...] = (
    "comparative_spec_commit",
    "comparative_spec_sha256",
    "comparison_module_sha256",
    "blind_prediction_schema_sha256",
)


class ExperimentFreezeViolation(RuntimeError):
    """Raised when current artifacts do not match the committed freeze."""


class ArtifactDigest(FrozenModel):
    artifact_id: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class ContestantFreeze(FrozenModel):
    contestant_id: Literal["FOUNDRY", "BASELINE"]
    commit_sha: str = Field(pattern=_COMMIT_PATTERN)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    timeout_seconds: int = Field(gt=0)

    tools_enabled: bool
    research_enabled: bool
    persistent_conversation: bool
    sdk_retries_enabled: bool
    semantic_retries_enabled: bool

    sdk_package: str = Field(min_length=1)
    sdk_version: str = Field(min_length=1)

    artifacts: tuple[ArtifactDigest, ...]


class EvaluationBaseFreeze(FrozenModel):
    comparative_spec_commit: str = Field(pattern=_COMMIT_PATTERN)
    comparative_spec_sha256: str = Field(pattern=_SHA256_PATTERN)
    comparison_module_sha256: str = Field(pattern=_SHA256_PATTERN)
    blind_prediction_schema_sha256: str = Field(pattern=_SHA256_PATTERN)


class ContestantFreezeManifest(FrozenModel):
    manifest_version: Literal["contestant-freeze-v1"]
    contestant_a: ContestantFreeze
    contestant_b: ContestantFreeze
    evaluation_base: EvaluationBaseFreeze


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_source(*targets: Callable[..., object]) -> str:
    return sha256_text("\n".join(inspect.getsource(target) for target in targets))


def build_current_contestant_freeze(
    repo_root: Path,
    *,
    sdk_version: str | None = None,
) -> ContestantFreezeManifest:
    """Compute the CURRENT contestant state. Loads no committed manifest."""
    resolved = sdk_version if sdk_version is not None else importlib.metadata.version(SDK_PACKAGE)
    return ContestantFreezeManifest(
        manifest_version="contestant-freeze-v1",
        contestant_a=_build_contestant_a(repo_root, resolved),
        contestant_b=_build_contestant_b(repo_root, resolved),
        evaluation_base=_build_evaluation_base(repo_root),
    )


def load_contestant_freeze(path: Path) -> ContestantFreezeManifest:
    """Parse a committed freeze artifact. Malformed input fails; it is never repaired."""
    return ContestantFreezeManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def write_contestant_freeze(path: Path, manifest: ContestantFreezeManifest) -> None:
    """The ONLY function permitted to emit a freeze artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    path.write_text(serialized + "\n", encoding="utf-8")


def verify_contestant_freeze(
    expected: ContestantFreezeManifest,
    repo_root: Path,
    *,
    sdk_version: str | None = None,
) -> None:
    """Compare a committed freeze against independently recomputed current state.

    Read-only. Never regenerates, repairs, or rewrites the committed freeze.
    """
    current = build_current_contestant_freeze(repo_root, sdk_version=sdk_version)
    _require_equal("manifest_version", expected.manifest_version, current.manifest_version)
    _compare_evaluation_base(expected.evaluation_base, current.evaluation_base)
    _compare_contestant("contestant_a", expected.contestant_a, current.contestant_a)
    _compare_contestant("contestant_b", expected.contestant_b, current.contestant_b)


def verify_contestant_freeze_file(
    freeze_path: Path,
    repo_root: Path,
    *,
    sdk_version: str | None = None,
) -> None:
    """Load the committed freeze, recompute current state, compare. Read-only."""
    expected = load_contestant_freeze(freeze_path)
    verify_contestant_freeze(expected, repo_root, sdk_version=sdk_version)


def _build_contestant_a(repo_root: Path, sdk_version: str) -> ContestantFreeze:
    artifacts = _file_digests(repo_root, FOUNDRY_FILES) + (
        ArtifactDigest(
            artifact_id=FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID,
            sha256=sha256_text(_FOUNDRY_INSTRUCTION),
        ),
        ArtifactDigest(
            artifact_id=FOUNDRY_SCHEMA_ARTIFACT_ID,
            sha256=sha256_json(IntentIntelligencePayload.model_json_schema()),
        ),
        ArtifactDigest(
            artifact_id=FOUNDRY_RENDERER_ARTIFACT_ID,
            sha256=sha256_source(_render_worker_input, _foundry_source_record),
        ),
    )
    return _contestant_freeze("FOUNDRY", CONTESTANT_A_COMMIT, sdk_version, artifacts)


def _build_contestant_b(repo_root: Path, sdk_version: str) -> ContestantFreeze:
    artifacts = _file_digests(repo_root, BASELINE_FILES) + (
        ArtifactDigest(
            artifact_id=BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID,
            sha256=sha256_text(_BASELINE_INSTRUCTION),
        ),
        ArtifactDigest(
            artifact_id=BASELINE_SCHEMA_ARTIFACT_ID,
            sha256=sha256_json(BaselinePayload.model_json_schema()),
        ),
        ArtifactDigest(
            artifact_id=BASELINE_RENDERER_ARTIFACT_ID,
            sha256=sha256_source(render_source_records, _baseline_source_record),
        ),
    )
    return _contestant_freeze("BASELINE", CONTESTANT_B_COMMIT, sdk_version, artifacts)


def _contestant_freeze(
    contestant_id: Literal["FOUNDRY", "BASELINE"],
    commit_sha: str,
    sdk_version: str,
    artifacts: tuple[ArtifactDigest, ...],
) -> ContestantFreeze:
    return ContestantFreeze(
        contestant_id=contestant_id,
        commit_sha=commit_sha,
        provider=PROVIDER,
        model=MODEL,
        reasoning_effort=REASONING_EFFORT,
        timeout_seconds=TIMEOUT_SECONDS,
        tools_enabled=False,
        research_enabled=False,
        persistent_conversation=False,
        sdk_retries_enabled=False,
        semantic_retries_enabled=False,
        sdk_package=SDK_PACKAGE,
        sdk_version=sdk_version,
        artifacts=artifacts,
    )


def _build_evaluation_base(repo_root: Path) -> EvaluationBaseFreeze:
    return EvaluationBaseFreeze(
        comparative_spec_commit=COMPARATIVE_SPEC_COMMIT,
        comparative_spec_sha256=_sha256_file(repo_root, COMPARATIVE_SPEC_PATH),
        comparison_module_sha256=_sha256_file(repo_root, COMPARISON_MODULE_PATH),
        blind_prediction_schema_sha256=sha256_json(BlindPrediction.model_json_schema()),
    )


def _file_digests(repo_root: Path, relatives: tuple[str, ...]) -> tuple[ArtifactDigest, ...]:
    return tuple(
        ArtifactDigest(artifact_id="file:" + relative, sha256=_sha256_file(repo_root, relative))
        for relative in relatives
    )


def _sha256_file(repo_root: Path, relative: str) -> str:
    try:
        data = (repo_root / relative).read_bytes()
    except OSError as exc:
        raise ExperimentFreezeViolation(
            "EXPERIMENT FREEZE VIOLATION: missing frozen artifact: " + relative
        ) from exc
    return sha256_bytes(data)


def _compare_evaluation_base(
    expected: EvaluationBaseFreeze,
    current: EvaluationBaseFreeze,
) -> None:
    for field in _EVALUATION_BASE_FIELDS:
        _require_equal(
            "evaluation_base." + field,
            getattr(expected, field),
            getattr(current, field),
        )


def _compare_contestant(
    label: str,
    expected: ContestantFreeze,
    current: ContestantFreeze,
) -> None:
    for field in _CONTESTANT_FIELDS:
        _require_equal(label + "." + field, getattr(expected, field), getattr(current, field))
    _require_equal(
        label + ".artifacts.count",
        len(expected.artifacts),
        len(current.artifacts),
    )
    for index, (expected_artifact, current_artifact) in enumerate(
        zip(expected.artifacts, current.artifacts, strict=True)
    ):
        position = label + ".artifacts[" + str(index) + "]"
        _require_equal(
            position + ".artifact_id",
            expected_artifact.artifact_id,
            current_artifact.artifact_id,
        )
        _require_equal(
            position + "(" + expected_artifact.artifact_id + ").sha256",
            expected_artifact.sha256,
            current_artifact.sha256,
        )


def _require_equal(field: str, expected: object, current: object) -> None:
    if expected != current:
        raise ExperimentFreezeViolation(
            "EXPERIMENT FREEZE VIOLATION: "
            + field
            + " mismatch; expected="
            + repr(expected)
            + " current="
            + repr(current)
        )
