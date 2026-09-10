from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import inspect
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.adapters.intelligence.xai import _SYSTEM_INSTRUCTION, _render_worker_input
from foundry.adapters.intelligence.xai import _source_record as _foundry_source_record
from foundry.adapters.intelligence.xai_baseline import _BASELINE_SYSTEM_INSTRUCTION
from foundry.evaluation.experiment_manifest import (
    BASELINE_RENDERER_ARTIFACT_ID,
    BASELINE_SCHEMA_ARTIFACT_ID,
    BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID,
    COMPARATIVE_SPEC_COMMIT,
    COMPARATIVE_SPEC_PATH,
    COMPARISON_MODULE_PATH,
    CONTESTANT_A_COMMIT,
    CONTESTANT_B_COMMIT,
    FOUNDRY_RENDERER_ARTIFACT_ID,
    FOUNDRY_SCHEMA_ARTIFACT_ID,
    FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID,
    SDK_PACKAGE,
    ArtifactDigest,
    ContestantFreeze,
    ContestantFreezeManifest,
    EvaluationBaseFreeze,
    ExperimentFreezeViolation,
    build_current_contestant_freeze,
    canonical_json_bytes,
    load_contestant_freeze,
    sha256_bytes,
    sha256_json,
    sha256_source,
    sha256_text,
    verify_contestant_freeze,
    verify_contestant_freeze_file,
    write_contestant_freeze,
)
from foundry.intelligence.baseline import BaselinePayload
from foundry.intelligence.comparison import BlindPrediction
from foundry.intelligence.proposals import IntentIntelligencePayload
from foundry.intelligence.source_records import _source_record as _baseline_source_record
from foundry.intelligence.source_records import render_source_records

REPO_ROOT = Path(__file__).resolve().parents[2]

_SDK_VERSION = "sdk-version-under-test"

_FOUNDRY_FILE_ARTIFACT_IDS = (
    "file:src/foundry/intelligence/input.py",
    "file:src/foundry/intelligence/compiler.py",
    "file:src/foundry/intelligence/proposals.py",
    "file:src/foundry/intelligence/validation.py",
    "file:src/foundry/intelligence/eval_adapter.py",
    "file:src/foundry/adapters/intelligence/xai.py",
    "file:src/foundry/domain/gaps.py",
)

_BASELINE_FILE_ARTIFACT_IDS = (
    "file:src/foundry/intelligence/input.py",
    "file:src/foundry/intelligence/baseline.py",
    "file:src/foundry/intelligence/baseline_validation.py",
    "file:src/foundry/intelligence/source_records.py",
    "file:src/foundry/adapters/intelligence/xai_baseline.py",
    "file:src/foundry/domain/gaps.py",
)

_EXPECTED_FOUNDRY_ARTIFACT_IDS = _FOUNDRY_FILE_ARTIFACT_IDS + (
    FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID,
    FOUNDRY_SCHEMA_ARTIFACT_ID,
    FOUNDRY_RENDERER_ARTIFACT_ID,
)

_EXPECTED_BASELINE_ARTIFACT_IDS = _BASELINE_FILE_ARTIFACT_IDS + (
    BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID,
    BASELINE_SCHEMA_ARTIFACT_ID,
    BASELINE_RENDERER_ARTIFACT_ID,
)

_TREE_FILES = (
    "src/foundry/intelligence/input.py",
    "src/foundry/intelligence/compiler.py",
    "src/foundry/intelligence/proposals.py",
    "src/foundry/intelligence/validation.py",
    "src/foundry/intelligence/eval_adapter.py",
    "src/foundry/intelligence/baseline.py",
    "src/foundry/intelligence/baseline_validation.py",
    "src/foundry/intelligence/source_records.py",
    COMPARISON_MODULE_PATH,
    "src/foundry/adapters/intelligence/xai.py",
    "src/foundry/adapters/intelligence/xai_baseline.py",
    "src/foundry/domain/gaps.py",
    COMPARATIVE_SPEC_PATH,
)

_SHA_ZERO = "0" * 64
_COMMIT_ZERO = "0" * 40


@pytest.fixture
def repo_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in _TREE_FILES:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPO_ROOT / relative).read_bytes())
    return root


@pytest.fixture
def manifest(repo_tree: Path) -> ContestantFreezeManifest:
    return build_current_contestant_freeze(repo_tree, sdk_version=_SDK_VERSION)


def _digest(freeze: ContestantFreeze, artifact_id: str) -> str:
    for artifact in freeze.artifacts:
        if artifact.artifact_id == artifact_id:
            return artifact.sha256
    raise AssertionError(f"missing artifact {artifact_id}")


def _flip(value: str) -> str:
    return ("1" if value[0] == "0" else "0") + value[1:]


def _tamper_digest(freeze: ContestantFreeze, artifact_id: str) -> ContestantFreeze:
    artifacts = tuple(
        artifact.model_copy(update={"sha256": _flip(artifact.sha256)})
        if artifact.artifact_id == artifact_id
        else artifact
        for artifact in freeze.artifacts
    )
    return freeze.model_copy(update={"artifacts": artifacts})


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _artifact_digest(artifact_id: str = "file:a.py", sha256: str = _SHA_ZERO) -> ArtifactDigest:
    return ArtifactDigest(artifact_id=artifact_id, sha256=sha256)


def _contestant(**overrides: object) -> ContestantFreeze:
    fields: dict[str, object] = {
        "contestant_id": "FOUNDRY",
        "commit_sha": CONTESTANT_A_COMMIT,
        "provider": "xAI",
        "model": "grok-4.6",
        "reasoning_effort": "high",
        "timeout_seconds": 3600,
        "tools_enabled": False,
        "research_enabled": False,
        "persistent_conversation": False,
        "sdk_retries_enabled": False,
        "semantic_retries_enabled": False,
        "sdk_package": SDK_PACKAGE,
        "sdk_version": _SDK_VERSION,
        "artifacts": (_artifact_digest(),),
    }
    fields.update(overrides)
    return ContestantFreeze(**fields)  # type: ignore[arg-type]


def _evaluation_base(**overrides: object) -> EvaluationBaseFreeze:
    fields: dict[str, object] = {
        "comparative_spec_commit": COMPARATIVE_SPEC_COMMIT,
        "comparative_spec_sha256": _SHA_ZERO,
        "comparison_module_sha256": _SHA_ZERO,
        "blind_prediction_schema_sha256": _SHA_ZERO,
    }
    fields.update(overrides)
    return EvaluationBaseFreeze(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# 1-4  model contracts
# --------------------------------------------------------------------------------------


def test_artifact_digest_is_immutable() -> None:
    digest = _artifact_digest()
    with pytest.raises(ValidationError):
        digest.sha256 = _SHA_ZERO  # type: ignore[misc]


def test_contestant_freeze_is_immutable() -> None:
    freeze = _contestant()
    with pytest.raises(ValidationError):
        freeze.model = "other"  # type: ignore[misc]


def test_manifest_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ArtifactDigest(artifact_id="a", sha256=_SHA_ZERO, note="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        _contestant(note="x")
    with pytest.raises(ValidationError):
        _evaluation_base(note="x")
    with pytest.raises(ValidationError):
        ContestantFreezeManifest(  # type: ignore[call-arg]
            manifest_version="contestant-freeze-v1",
            contestant_a=_contestant(),
            contestant_b=_contestant(contestant_id="BASELINE"),
            evaluation_base=_evaluation_base(),
            holdout_bundle_sha256=_SHA_ZERO,
        )


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "abc",
        "A" * 64,
        "ABCDEF1234567890" + "0" * 48,
        "0" * 63,
        "0" * 65,
        "g" * 64,
        " " + "0" * 63,
    ],
)
def test_invalid_sha256_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        ArtifactDigest(artifact_id="a", sha256=bad)


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "0" * 39, "0" * 41, CONTESTANT_A_COMMIT.upper(), "g" * 40],
)
def test_invalid_commit_sha_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _contestant(commit_sha=bad)
    with pytest.raises(ValidationError):
        _evaluation_base(comparative_spec_commit=bad)


def test_manifest_version_literal_is_enforced() -> None:
    with pytest.raises(ValidationError):
        ContestantFreezeManifest(
            manifest_version="experiment-manifest-v1",  # type: ignore[arg-type]
            contestant_a=_contestant(),
            contestant_b=_contestant(contestant_id="BASELINE"),
            evaluation_base=_evaluation_base(),
        )


def test_contestant_id_literal_is_enforced() -> None:
    with pytest.raises(ValidationError):
        _contestant(contestant_id="FOUNDRY_V2")


# --------------------------------------------------------------------------------------
# 5-8  hashing primitives
# --------------------------------------------------------------------------------------


def test_sha256_bytes_is_deterministic_and_matches_hashlib() -> None:
    assert sha256_bytes(b"") == hashlib.sha256(b"").hexdigest()
    assert sha256_bytes(b"foundry") == sha256_bytes(b"foundry")
    assert sha256_bytes(b"foundry") == hashlib.sha256(b"foundry").hexdigest()
    assert sha256_bytes(b"foundry") != sha256_bytes(b"foundrY")


def test_sha256_text_hashes_utf8_bytes_exactly() -> None:
    text = "gap: café — naïve ✅"
    assert sha256_text(text) == sha256_bytes(text.encode("utf-8"))
    assert sha256_text(text) == sha256_text(text)
    assert sha256_text("") == hashlib.sha256(b"").hexdigest()


def test_canonical_json_is_invariant_to_insertion_order() -> None:
    first = {"b": 1, "a": {"d": 2, "c": 3}}
    second = {"a": {"c": 3, "d": 2}, "b": 1}
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert sha256_json(first) == sha256_json(second)


def test_canonical_json_uses_compact_separators_and_utf8() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert canonical_json_bytes({"k": "café"}) == '{"k":"café"}'.encode()
    assert b"\n" not in canonical_json_bytes({"a": {"b": [1, 2]}})
    assert b", " not in canonical_json_bytes({"a": 1, "b": 2})
    assert b": " not in canonical_json_bytes({"a": 1})


def test_sha256_source_covers_every_supplied_function() -> None:
    def variant(request: object) -> str:
        return "a completely different renderer body"

    combined = sha256_source(render_source_records, _baseline_source_record)
    assert combined != sha256_source(render_source_records)
    assert combined != sha256_source(_baseline_source_record)
    assert combined != sha256_source(variant, _baseline_source_record)
    assert combined == sha256_source(render_source_records, _baseline_source_record)


# --------------------------------------------------------------------------------------
# 9-10  deterministic serialization
# --------------------------------------------------------------------------------------


def test_serialization_is_byte_identical_across_writes(
    manifest: ContestantFreezeManifest, tmp_path: Path
) -> None:
    first = tmp_path / "a" / "freeze.json"
    second = tmp_path / "b" / "freeze.json"
    write_contestant_freeze(first, manifest)
    write_contestant_freeze(second, manifest)
    write_contestant_freeze(first, manifest)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("}\n")


def test_serialization_contains_no_environment_or_secret_material(
    manifest: ContestantFreezeManifest, tmp_path: Path
) -> None:
    path = tmp_path / "freeze.json"
    write_contestant_freeze(path, manifest)
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    for forbidden in (
        "api_key",
        "apikey",
        "xai_api_key",
        "secret",
        "token=",
        "password",
        "created_at",
        "generated_at",
        "timestamp",
        "hostname",
        "username",
        "/users/",
        "/home/",
        str(Path.home()).lower(),
        str(REPO_ROOT).lower(),
    ):
        assert forbidden not in lowered, forbidden
    assert "/" not in json.loads(text)["contestant_a"]["sdk_version"]


# --------------------------------------------------------------------------------------
# 11-27  build behaviour
# --------------------------------------------------------------------------------------


def test_contestant_a_declares_frozen_foundry_identity(
    manifest: ContestantFreezeManifest,
) -> None:
    assert manifest.contestant_a.contestant_id == "FOUNDRY"
    assert manifest.contestant_a.commit_sha == "2d75532afbbe25913d5550483d3363f3df4cb754"


def test_contestant_b_declares_frozen_baseline_identity(
    manifest: ContestantFreezeManifest,
) -> None:
    assert manifest.contestant_b.contestant_id == "BASELINE"
    assert manifest.contestant_b.commit_sha == "11dd47485bb6f7079cf2b31077ee7cbe988936fc"


def test_contestant_commits_are_distinct(manifest: ContestantFreezeManifest) -> None:
    assert manifest.contestant_a.commit_sha != manifest.contestant_b.commit_sha


def test_both_contestants_share_frozen_provider_configuration(
    manifest: ContestantFreezeManifest,
) -> None:
    for freeze in (manifest.contestant_a, manifest.contestant_b):
        assert freeze.provider == "xAI"
        assert freeze.model == "grok-4.6"
        assert freeze.reasoning_effort == "high"
        assert freeze.timeout_seconds == 3600
        assert freeze.tools_enabled is False
        assert freeze.research_enabled is False
        assert freeze.persistent_conversation is False
        assert freeze.sdk_retries_enabled is False
        assert freeze.semantic_retries_enabled is False
        assert freeze.sdk_package == "xai-sdk"


def test_injected_sdk_version_is_recorded_identically_for_both(
    manifest: ContestantFreezeManifest,
) -> None:
    assert manifest.contestant_a.sdk_version == _SDK_VERSION
    assert manifest.contestant_b.sdk_version == _SDK_VERSION


def test_default_sdk_version_comes_from_installed_package_metadata(repo_tree: Path) -> None:
    built = build_current_contestant_freeze(repo_tree)
    installed = importlib.metadata.version(SDK_PACKAGE)
    assert built.contestant_a.sdk_version == installed
    assert built.contestant_b.sdk_version == installed


def test_file_artifact_digests_are_actual_sha256_of_file_bytes(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    for freeze, ids in (
        (manifest.contestant_a, _FOUNDRY_FILE_ARTIFACT_IDS),
        (manifest.contestant_b, _BASELINE_FILE_ARTIFACT_IDS),
    ):
        for artifact_id in ids:
            relative = artifact_id.removeprefix("file:")
            expected = hashlib.sha256((repo_tree / relative).read_bytes()).hexdigest()
            assert _digest(freeze, artifact_id) == expected


def test_artifact_order_is_fixed_and_deterministic(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    assert tuple(a.artifact_id for a in manifest.contestant_a.artifacts) == (
        _EXPECTED_FOUNDRY_ARTIFACT_IDS
    )
    assert tuple(a.artifact_id for a in manifest.contestant_b.artifacts) == (
        _EXPECTED_BASELINE_ARTIFACT_IDS
    )
    rebuilt = build_current_contestant_freeze(repo_tree, sdk_version=_SDK_VERSION)
    assert rebuilt == manifest


def test_shared_files_are_recorded_independently_for_each_contestant(
    manifest: ContestantFreezeManifest,
) -> None:
    for shared in ("file:src/foundry/intelligence/input.py", "file:src/foundry/domain/gaps.py"):
        assert _digest(manifest.contestant_a, shared) == _digest(manifest.contestant_b, shared)


# --------------------------------------------------------------------------------------
# 28-34  semantic treatment digests
# --------------------------------------------------------------------------------------


def test_foundry_system_instruction_digest_matches_frozen_constant(
    manifest: ContestantFreezeManifest,
) -> None:
    assert _digest(manifest.contestant_a, FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID) == sha256_text(
        _SYSTEM_INSTRUCTION
    )


def test_baseline_system_instruction_digest_matches_frozen_constant(
    manifest: ContestantFreezeManifest,
) -> None:
    assert _digest(manifest.contestant_b, BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID) == sha256_text(
        _BASELINE_SYSTEM_INSTRUCTION
    )


def test_system_instruction_digests_differ_between_contestants(
    manifest: ContestantFreezeManifest,
) -> None:
    assert _digest(manifest.contestant_a, FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID) != _digest(
        manifest.contestant_b, BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID
    )


def test_foundry_schema_digest_is_canonical_hash_of_payload_schema(
    manifest: ContestantFreezeManifest,
) -> None:
    assert _digest(manifest.contestant_a, FOUNDRY_SCHEMA_ARTIFACT_ID) == sha256_json(
        IntentIntelligencePayload.model_json_schema()
    )


def test_baseline_schema_digest_is_canonical_hash_of_baseline_schema(
    manifest: ContestantFreezeManifest,
) -> None:
    assert _digest(manifest.contestant_b, BASELINE_SCHEMA_ARTIFACT_ID) == sha256_json(
        BaselinePayload.model_json_schema()
    )


def test_foundry_renderer_digest_covers_both_renderer_functions(
    manifest: ContestantFreezeManifest,
) -> None:
    recorded = _digest(manifest.contestant_a, FOUNDRY_RENDERER_ARTIFACT_ID)
    assert recorded == sha256_source(_render_worker_input, _foundry_source_record)
    assert recorded != sha256_source(_render_worker_input)
    assert recorded != sha256_source(_foundry_source_record)


def test_foundry_renderer_digest_changes_when_renderer_source_changes(
    manifest: ContestantFreezeManifest,
) -> None:
    def _render_worker_input_variant(request: object) -> str:
        return "different rendering of the worker input"

    recorded = _digest(manifest.contestant_a, FOUNDRY_RENDERER_ARTIFACT_ID)
    assert recorded != sha256_source(_render_worker_input_variant, _foundry_source_record)


def test_baseline_renderer_digest_covers_both_renderer_functions(
    manifest: ContestantFreezeManifest,
) -> None:
    recorded = _digest(manifest.contestant_b, BASELINE_RENDERER_ARTIFACT_ID)
    assert recorded == sha256_source(render_source_records, _baseline_source_record)
    assert recorded != sha256_source(render_source_records)
    assert recorded != sha256_source(_baseline_source_record)


def test_whole_adapter_files_are_hashed_independently_of_components(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    foundry_file = _digest(manifest.contestant_a, "file:src/foundry/adapters/intelligence/xai.py")
    baseline_file = _digest(
        manifest.contestant_b, "file:src/foundry/adapters/intelligence/xai_baseline.py"
    )
    assert foundry_file == sha256_bytes(
        (repo_tree / "src/foundry/adapters/intelligence/xai.py").read_bytes()
    )
    assert baseline_file == sha256_bytes(
        (repo_tree / "src/foundry/adapters/intelligence/xai_baseline.py").read_bytes()
    )
    assert foundry_file != _digest(manifest.contestant_a, FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID)
    assert foundry_file != _digest(manifest.contestant_a, FOUNDRY_RENDERER_ARTIFACT_ID)
    assert baseline_file != _digest(manifest.contestant_b, BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID)
    assert baseline_file != _digest(manifest.contestant_b, BASELINE_RENDERER_ARTIFACT_ID)


def test_source_record_renderers_are_distinct_module_level_functions() -> None:
    assert _foundry_source_record is not _baseline_source_record


# --------------------------------------------------------------------------------------
# 35-39  evaluation base
# --------------------------------------------------------------------------------------


def test_evaluation_base_declares_approved_comparative_spec_commit(
    manifest: ContestantFreezeManifest,
) -> None:
    assert manifest.evaluation_base.comparative_spec_commit == (
        "ed11848e322dd9be8e1e606c2e2fcc59d89c086a"
    )
    assert COMPARATIVE_SPEC_COMMIT == "ed11848e322dd9be8e1e606c2e2fcc59d89c086a"


def test_evaluation_base_captures_comparative_spec_file_digest(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    assert manifest.evaluation_base.comparative_spec_sha256 == sha256_bytes(
        (repo_tree / COMPARATIVE_SPEC_PATH).read_bytes()
    )


def test_evaluation_base_captures_comparison_module_digest(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    assert manifest.evaluation_base.comparison_module_sha256 == sha256_bytes(
        (repo_tree / COMPARISON_MODULE_PATH).read_bytes()
    )


def test_evaluation_base_captures_blind_prediction_schema_digest(
    manifest: ContestantFreezeManifest,
) -> None:
    assert manifest.evaluation_base.blind_prediction_schema_sha256 == sha256_json(
        BlindPrediction.model_json_schema()
    )


def test_manifest_declares_no_holdout_judge_or_execution_commitments(
    manifest: ContestantFreezeManifest, tmp_path: Path
) -> None:
    assert set(ContestantFreezeManifest.model_fields) == {
        "manifest_version",
        "contestant_a",
        "contestant_b",
        "evaluation_base",
    }
    assert set(EvaluationBaseFreeze.model_fields) == {
        "comparative_spec_commit",
        "comparative_spec_sha256",
        "comparison_module_sha256",
        "blind_prediction_schema_sha256",
    }
    path = tmp_path / "freeze.json"
    write_contestant_freeze(path, manifest)
    corpus = (
        path.read_text(encoding="utf-8")
        + json.dumps(ContestantFreezeManifest.model_json_schema())
    ).lower()
    for forbidden in (
        "holdout",
        "judge",
        "adjudicat",
        "execution_order",
        "execution-order",
        "score",
        "result",
        "concept",
    ):
        assert forbidden not in corpus, forbidden


# --------------------------------------------------------------------------------------
# 40-44  verification success
# --------------------------------------------------------------------------------------


def test_freshly_built_manifest_verifies(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    assert verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION) is None


def test_write_load_round_trip_preserves_equality(
    manifest: ContestantFreezeManifest, tmp_path: Path
) -> None:
    path = tmp_path / "freeze.json"
    write_contestant_freeze(path, manifest)
    assert load_contestant_freeze(path) == manifest


def test_committed_format_json_verifies_without_mutation(
    manifest: ContestantFreezeManifest, repo_tree: Path, tmp_path: Path
) -> None:
    path = tmp_path / "freeze.json"
    write_contestant_freeze(path, manifest)
    before = path.read_bytes()
    assert verify_contestant_freeze_file(path, repo_tree, sdk_version=_SDK_VERSION) is None
    assert path.read_bytes() == before


def test_verification_does_not_write_any_file(
    manifest: ContestantFreezeManifest, repo_tree: Path, tmp_path: Path
) -> None:
    freeze_path = tmp_path / "freeze.json"
    write_contestant_freeze(freeze_path, manifest)
    tree_before = _tree_snapshot(repo_tree)
    freeze_before = freeze_path.read_bytes()
    verify_contestant_freeze_file(freeze_path, repo_tree, sdk_version=_SDK_VERSION)
    verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION)
    assert _tree_snapshot(repo_tree) == tree_before
    assert freeze_path.read_bytes() == freeze_before


def test_verification_never_touches_write_apis(
    manifest: ContestantFreezeManifest,
    repo_tree: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_path = tmp_path / "freeze.json"
    write_contestant_freeze(freeze_path, manifest)

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("verification must never write")

    monkeypatch.setattr(Path, "write_text", _forbidden)
    monkeypatch.setattr(Path, "write_bytes", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)
    monkeypatch.setattr(Path, "unlink", _forbidden)
    monkeypatch.setattr(Path, "rename", _forbidden)
    assert verify_contestant_freeze_file(freeze_path, repo_tree, sdk_version=_SDK_VERSION) is None


def test_only_the_writer_uses_write_apis() -> None:
    writer_source = inspect.getsource(write_contestant_freeze)
    assert "write_text" in writer_source
    for reader in (
        verify_contestant_freeze,
        verify_contestant_freeze_file,
        load_contestant_freeze,
        build_current_contestant_freeze,
    ):
        source = inspect.getsource(reader)
        assert "write_text" not in source
        assert "write_bytes" not in source
        assert "mkdir" not in source


def test_verification_never_regenerates_the_committed_freeze(
    repo_tree: Path, tmp_path: Path
) -> None:
    stale = build_current_contestant_freeze(repo_tree, sdk_version=_SDK_VERSION)
    tampered = stale.model_copy(
        update={"contestant_a": _tamper_digest(stale.contestant_a, _FOUNDRY_FILE_ARTIFACT_IDS[0])}
    )
    path = tmp_path / "freeze.json"
    write_contestant_freeze(path, tampered)
    before = path.read_bytes()
    with pytest.raises(ExperimentFreezeViolation):
        verify_contestant_freeze_file(path, repo_tree, sdk_version=_SDK_VERSION)
    assert path.read_bytes() == before
    assert load_contestant_freeze(path) == tampered


# --------------------------------------------------------------------------------------
# 45-60  tamper detection
# --------------------------------------------------------------------------------------


def test_tampering_foundry_adapter_file_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    target = repo_tree / "src/foundry/adapters/intelligence/xai.py"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION)
    assert "adapters/intelligence/xai.py" in str(excinfo.value)


def test_tampering_baseline_adapter_file_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    target = repo_tree / "src/foundry/adapters/intelligence/xai_baseline.py"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION)
    assert "xai_baseline.py" in str(excinfo.value)


def test_tampering_source_renderer_file_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    target = repo_tree / "src/foundry/intelligence/source_records.py"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION)
    assert "source_records.py" in str(excinfo.value)


def test_tampering_comparison_module_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    target = repo_tree / COMPARISON_MODULE_PATH
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION)
    assert "comparison_module_sha256" in str(excinfo.value)


def test_tampering_comparative_spec_file_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    target = repo_tree / COMPARATIVE_SPEC_PATH
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION)
    assert "comparative_spec_sha256" in str(excinfo.value)


@pytest.mark.parametrize(
    ("attribute", "artifact_id"),
    [
        ("contestant_a", FOUNDRY_SYSTEM_INSTRUCTION_ARTIFACT_ID),
        ("contestant_b", BASELINE_SYSTEM_INSTRUCTION_ARTIFACT_ID),
        ("contestant_a", FOUNDRY_SCHEMA_ARTIFACT_ID),
        ("contestant_b", BASELINE_SCHEMA_ARTIFACT_ID),
        ("contestant_a", FOUNDRY_RENDERER_ARTIFACT_ID),
        ("contestant_b", BASELINE_RENDERER_ARTIFACT_ID),
    ],
)
def test_tampering_expected_component_digest_fails_verification(
    manifest: ContestantFreezeManifest,
    repo_tree: Path,
    attribute: str,
    artifact_id: str,
) -> None:
    freeze: ContestantFreeze = getattr(manifest, attribute)
    tampered = manifest.model_copy(update={attribute: _tamper_digest(freeze, artifact_id)})
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
    assert artifact_id in str(excinfo.value)


def test_tampering_expected_blind_prediction_schema_digest_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    base = manifest.evaluation_base
    tampered = manifest.model_copy(
        update={
            "evaluation_base": base.model_copy(
                update={
                    "blind_prediction_schema_sha256": _flip(base.blind_prediction_schema_sha256)
                }
            )
        }
    )
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
    assert "blind_prediction_schema_sha256" in str(excinfo.value)


@pytest.mark.parametrize("attribute", ["contestant_a", "contestant_b"])
def test_tampering_expected_commit_identity_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path, attribute: str
) -> None:
    freeze: ContestantFreeze = getattr(manifest, attribute)
    tampered = manifest.model_copy(
        update={attribute: freeze.model_copy(update={"commit_sha": _flip(freeze.commit_sha)})}
    )
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
    assert "commit_sha" in str(excinfo.value)


def test_tampering_expected_comparative_spec_commit_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    base = manifest.evaluation_base
    tampered = manifest.model_copy(
        update={
            "evaluation_base": base.model_copy(
                update={"comparative_spec_commit": _flip(base.comparative_spec_commit)}
            )
        }
    )
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
    assert "comparative_spec_commit" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "openai"),
        ("model", "grok-4"),
        ("reasoning_effort", "low"),
        ("timeout_seconds", 60),
        ("tools_enabled", True),
        ("research_enabled", True),
        ("persistent_conversation", True),
        ("sdk_retries_enabled", True),
        ("semantic_retries_enabled", True),
        ("sdk_package", "some-other-sdk"),
        ("contestant_id", "BASELINE"),
    ],
)
def test_tampering_expected_contestant_configuration_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path, field: str, value: object
) -> None:
    tampered = manifest.model_copy(
        update={"contestant_a": manifest.contestant_a.model_copy(update={field: value})}
    )
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
    assert field in str(excinfo.value)


def test_sdk_version_change_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(manifest, repo_tree, sdk_version="0.0.0-upgraded")
    assert "sdk_version" in str(excinfo.value)


def test_tampering_manifest_version_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    tampered = manifest.model_copy(update={"manifest_version": "contestant-freeze-v2"})
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
    assert "manifest_version" in str(excinfo.value)


def test_dropping_an_expected_artifact_fails_verification(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    freeze = manifest.contestant_a
    tampered = manifest.model_copy(
        update={"contestant_a": freeze.model_copy(update={"artifacts": freeze.artifacts[:-1]})}
    )
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
    assert "artifacts" in str(excinfo.value)


def test_mismatch_reporting_order_is_stable(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    base = manifest.evaluation_base
    tampered = manifest.model_copy(
        update={
            "evaluation_base": base.model_copy(
                update={"comparison_module_sha256": _flip(base.comparison_module_sha256)}
            ),
            "contestant_b": _tamper_digest(
                manifest.contestant_b, _BASELINE_FILE_ARTIFACT_IDS[0]
            ),
        }
    )
    messages = set()
    for _ in range(5):
        with pytest.raises(ExperimentFreezeViolation) as excinfo:
            verify_contestant_freeze(tampered, repo_tree, sdk_version=_SDK_VERSION)
        messages.add(str(excinfo.value))
    assert len(messages) == 1
    assert "comparison_module_sha256" in messages.pop()


# --------------------------------------------------------------------------------------
# 61  unrelated files, missing artifacts
# --------------------------------------------------------------------------------------


def test_unrelated_files_do_not_invalidate_the_freeze(
    manifest: ContestantFreezeManifest, repo_tree: Path
) -> None:
    notes = repo_tree / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "unrelated.txt").write_text("scratch notes\n", encoding="utf-8")
    (repo_tree / "README.md").write_text("changed readme\n", encoding="utf-8")
    (repo_tree / "src/foundry/intelligence/fake.py").write_text("# unfrozen\n", encoding="utf-8")
    assert verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION) is None

    (notes / "unrelated.txt").write_text("changed again\n", encoding="utf-8")
    assert verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION) is None


@pytest.mark.parametrize(
    "relative",
    [
        "src/foundry/adapters/intelligence/xai.py",
        "src/foundry/adapters/intelligence/xai_baseline.py",
        "src/foundry/domain/gaps.py",
        COMPARISON_MODULE_PATH,
        COMPARATIVE_SPEC_PATH,
    ],
)
def test_missing_frozen_artifact_fails_visibly(
    manifest: ContestantFreezeManifest, repo_tree: Path, relative: str
) -> None:
    (repo_tree / relative).unlink()
    with pytest.raises(ExperimentFreezeViolation) as excinfo:
        verify_contestant_freeze(manifest, repo_tree, sdk_version=_SDK_VERSION)
    message = str(excinfo.value)
    assert relative in message
    assert "missing" in message.lower()


def test_missing_frozen_artifact_is_not_a_raw_file_not_found(repo_tree: Path) -> None:
    (repo_tree / "src/foundry/intelligence/compiler.py").unlink()
    with pytest.raises(ExperimentFreezeViolation):
        build_current_contestant_freeze(repo_tree, sdk_version=_SDK_VERSION)


def test_load_does_not_repair_a_malformed_freeze_file(tmp_path: Path) -> None:
    path = tmp_path / "freeze.json"
    path.write_text('{"manifest_version": "contestant-freeze-v1"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_contestant_freeze(path)

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_contestant_freeze(path)


def test_load_rejects_unknown_fields(
    manifest: ContestantFreezeManifest, tmp_path: Path
) -> None:
    path = tmp_path / "freeze.json"
    write_contestant_freeze(path, manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["judge_bundle_sha256"] = _SHA_ZERO
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_contestant_freeze(path)


# --------------------------------------------------------------------------------------
# module hygiene: no subprocess, no commit-tool dependency, no network
# --------------------------------------------------------------------------------------


def _module_path() -> Path:
    return REPO_ROOT / "src/foundry/evaluation/experiment_manifest.py"


def _imported_roots(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            yield node.module.split(".")[0]


def test_manifest_module_has_no_subprocess_or_commit_tool_dependency() -> None:
    source = _module_path().read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed = {
        "__future__",
        "collections",
        "foundry",
        "hashlib",
        "importlib",
        "inspect",
        "json",
        "pathlib",
        "pydantic",
        "typing",
    }
    assert set(_imported_roots(tree)) <= allowed
    for forbidden in (
        "subprocess",
        "os.system",
        "os.popen",
        "sha256sum",
        "openssl",
        "pygit2",
        "GitPython",
        ".git",
        "urllib",
        "socket",
        "requests",
        "httpx",
        "getpass",
        "platform",
        "environ",
    ):
        assert forbidden not in source, forbidden


def test_manifest_module_reads_no_environment_or_dotenv() -> None:
    source = _module_path().read_text(encoding="utf-8")
    for forbidden in ("XAI_API_KEY", "api_key", "dotenv", ".env", "load_dotenv"):
        assert forbidden not in source, forbidden


# --------------------------------------------------------------------------------------
# the committed freeze artifact
# --------------------------------------------------------------------------------------


def test_committed_contestant_freeze_verifies_against_the_repository() -> None:
    freeze_path = REPO_ROOT / "evals/comparative/contestant-freeze.json"
    assert freeze_path.is_file()
    assert verify_contestant_freeze_file(freeze_path, REPO_ROOT) is None


def test_committed_contestant_freeze_declares_the_frozen_identities() -> None:
    committed = load_contestant_freeze(REPO_ROOT / "evals/comparative/contestant-freeze.json")
    assert committed.manifest_version == "contestant-freeze-v1"
    assert committed.contestant_a.commit_sha == CONTESTANT_A_COMMIT
    assert committed.contestant_b.commit_sha == CONTESTANT_B_COMMIT
    assert committed.evaluation_base.comparative_spec_commit == COMPARATIVE_SPEC_COMMIT
    assert committed.contestant_a.sdk_version == importlib.metadata.version(SDK_PACKAGE)
