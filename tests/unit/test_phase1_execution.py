"""Task 9K1-A execution-evidence schemas.

These tests own the Phase-1 evidence contract: terminal statuses, attempt outcomes,
digest safety, raw-evidence consistency, blind-output neutrality, execution-record
completeness, and output-manifest arithmetic.

Nothing here reaches a provider, and nothing here reaches the hidden judge.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from foundry.domain.gaps import GapKind
from foundry.evaluation.phase1_execution import (
    INFRASTRUCTURE_RETRY_POLICY,
    PAIRING_POLICY,
    PHASE1_OUTPUT_MANIFEST_VERSION,
    SCHEMA_INCOMPATIBILITY_POLICY,
    STRUCTURAL_FAILURE_POLICY,
    TOTAL_CONTESTANT_SLOTS,
    AttemptOutcome,
    AttemptRecord,
    AttemptStartedRecord,
    BaselineRawEvidence,
    BlindOutput,
    FoundryRawEvidence,
    Phase1ArtifactDigest,
    Phase1ExecutionRecord,
    Phase1OutputManifest,
    Phase1TerminalStatus,
    Phase1WriteConflict,
    create_attempt_started,
    phase1_canonical_bytes,
    phase1_canonical_json,
    sanitize_error_text,
    write_evidence,
)
from foundry.evaluation.sealed_exam_manifest import BlindSystemLabel, ContestantId
from foundry.intelligence.baseline import BaselineGap, BaselinePayload, BaselineResult
from foundry.intelligence.comparison import BlindPrediction
from foundry.intelligence.proposals import (
    GapProposal,
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
)

_T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64

CASE_SEQUENCE: tuple[str, ...] = (
    "H-011",
    "H-002",
    "H-003",
    "H-001",
    "H-007",
    "H-010",
    "H-008",
    "H-006",
    "H-004",
    "H-012",
    "H-005",
    "H-009",
)


def _execution_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def _usage() -> IntelligenceUsage:
    return IntelligenceUsage(
        frontier_model_jobs=1,
        input_tokens=1200,
        output_tokens=800,
        cost_usd=0.25,
        wall_clock_ms=45_000,
    )


def _foundry_result() -> IntentIntelligenceResult:
    return IntentIntelligenceResult(
        payload=IntentIntelligencePayload(
            semantic_proposals=(),
            gap_proposals=(
                GapProposal(
                    proposal_id="G-1",
                    kind=GapKind.MISSING_INFORMATION,
                    subject_key="alpha-subject",
                    description="alpha description",
                    blocking=True,
                    confidence=0.7,
                ),
            ),
        ),
        usage=_usage(),
    )


def _baseline_result() -> BaselineResult:
    return BaselineResult(
        payload=BaselinePayload(
            gaps=(
                BaselineGap(
                    gap_id="B-1",
                    kind=GapKind.AMBIGUITY,
                    subject_key="beta-subject",
                    description="beta description",
                    confidence=0.4,
                ),
            )
        ),
        usage=_usage(),
    )


def _prediction(index: int = 1) -> BlindPrediction:
    return BlindPrediction(
        prediction_id=f"P-{index:03d}",
        kind=GapKind.MISSING_INFORMATION,
        subject_key="alpha-subject",
        description="alpha description",
        confidence=0.7,
    )


def _attempt(**over: Any) -> AttemptRecord:
    payload: dict[str, Any] = {
        "execution_id": _execution_id(1),
        "case_id": "H-001",
        "contestant_id": ContestantId.FOUNDRY,
        "blind_label": BlindSystemLabel.SYSTEM_A,
        "execution_position": 1,
        "attempt_number": 1,
        "started_at": _T0,
        "completed_at": _T0 + timedelta(seconds=30),
        "outcome": AttemptOutcome.VALID_RESULT,
    }
    payload.update(over)
    return AttemptRecord(**payload)


def _valid_record(**over: Any) -> Phase1ExecutionRecord:
    payload: dict[str, Any] = {
        "case_id": "H-001",
        "contestant_id": ContestantId.FOUNDRY,
        "blind_label": BlindSystemLabel.SYSTEM_A,
        "execution_position": 1,
        "terminal_status": Phase1TerminalStatus.VALID,
        "attempt_execution_ids": (_execution_id(1),),
        "infrastructure_retry_count": 0,
        "raw_result_path": "evals/comparative/phase1/raw/H-001/FOUNDRY.json",
        "raw_result_sha256": _SHA_A,
        "blind_output_path": "evals/comparative/phase1/blind/H-001/SYSTEM-A.json",
        "blind_output_sha256": _SHA_B,
        "input_tokens": 1200,
        "output_tokens": 800,
        "cost_usd": 0.25,
        "wall_clock_ms": 45_000,
    }
    payload.update(over)
    return Phase1ExecutionRecord(**payload)


def _structural_record(**over: Any) -> Phase1ExecutionRecord:
    payload: dict[str, Any] = {
        "case_id": "H-001",
        "contestant_id": ContestantId.BASELINE,
        "blind_label": BlindSystemLabel.SYSTEM_B,
        "execution_position": 2,
        "terminal_status": Phase1TerminalStatus.STRUCTURAL_FAILURE,
        "attempt_execution_ids": (_execution_id(2),),
        "infrastructure_retry_count": 0,
        "raw_result_path": "evals/comparative/phase1/raw/H-001/BASELINE.json",
        "raw_result_sha256": _SHA_C,
        "blind_output_path": None,
        "blind_output_sha256": None,
        "input_tokens": 900,
        "output_tokens": 100,
        "cost_usd": 0.05,
        "wall_clock_ms": 9_000,
    }
    payload.update(over)
    return Phase1ExecutionRecord(**payload)


def _bundle() -> tuple[tuple[Phase1ExecutionRecord, ...], tuple[AttemptRecord, ...]]:
    executions: list[Phase1ExecutionRecord] = []
    attempts: list[AttemptRecord] = []
    counter = 0
    for case_index, case_id in enumerate(CASE_SEQUENCE):
        foundry_label = (
            BlindSystemLabel.SYSTEM_A if case_index % 2 == 0 else BlindSystemLabel.SYSTEM_B
        )
        baseline_label = (
            BlindSystemLabel.SYSTEM_B if case_index % 2 == 0 else BlindSystemLabel.SYSTEM_A
        )
        for position, contestant, label in (
            (1, ContestantId.FOUNDRY, foundry_label),
            (2, ContestantId.BASELINE, baseline_label),
        ):
            counter += 1
            execution_id = _execution_id(counter)
            attempts.append(
                _attempt(
                    execution_id=execution_id,
                    case_id=case_id,
                    contestant_id=contestant,
                    blind_label=label,
                    execution_position=position,
                )
            )
            executions.append(
                _valid_record(
                    case_id=case_id,
                    contestant_id=contestant,
                    blind_label=label,
                    execution_position=position,
                    attempt_execution_ids=(execution_id,),
                    raw_result_path=(
                        f"evals/comparative/phase1/raw/{case_id}/{contestant.value}.json"
                    ),
                    blind_output_path=(
                        f"evals/comparative/phase1/blind/{case_id}/{label.value}.json"
                    ),
                )
            )
    return tuple(executions), tuple(attempts)


def _manifest(**over: Any) -> Phase1OutputManifest:
    executions, attempts = _bundle()
    payload: dict[str, Any] = {
        "manifest_version": PHASE1_OUTPUT_MANIFEST_VERSION,
        "experiment_manifest_sha256": _SHA_A,
        "pre_exam_audit_sha256": _SHA_B,
        "runner_commit_sha": "0" * 40,
        "runner_artifacts": (
            Phase1ArtifactDigest(
                path="src/foundry/evaluation/phase1_execution.py", sha256=_SHA_A
            ),
            Phase1ArtifactDigest(path="src/foundry/evaluation/phase1_runner.py", sha256=_SHA_B),
            Phase1ArtifactDigest(path="src/foundry/evaluation/phase1_live.py", sha256=_SHA_C),
        ),
        "provider": "xAI",
        "model": "grok-4.6",
        "reasoning_effort": "high",
        "sdk_package": "xai-sdk",
        "sdk_version": "1.19.0",
        "provider_revision": None,
        "provider_revision_observable": False,
        "pairing_policy": PAIRING_POLICY,
        "infrastructure_retry_policy": INFRASTRUCTURE_RETRY_POLICY,
        "structural_failure_policy": STRUCTURAL_FAILURE_POLICY,
        "schema_incompatibility_policy": SCHEMA_INCOMPATIBILITY_POLICY,
        "case_sequence": CASE_SEQUENCE,
        "executions": executions,
        "attempts": attempts,
        "total_contestant_slots": TOTAL_CONTESTANT_SLOTS,
        "valid_results": 24,
        "structural_failures": 0,
        "infrastructure_failures": 0,
        "infrastructure_retries": 0,
        "started_at": _T0,
        "completed_at": _T0 + timedelta(hours=3),
    }
    payload.update(over)
    return Phase1OutputManifest(**payload)


def _schema_property_names(model: type[BaseModel]) -> set[str]:
    schema = model.model_json_schema()
    names: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(str(key) for key in properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return names


# 1. terminal statuses exact.
def test_terminal_statuses_are_exactly_valid_and_structural_failure() -> None:
    assert [status.value for status in Phase1TerminalStatus] == [
        "VALID",
        "STRUCTURAL_FAILURE",
    ]


# 2. attempt outcomes exact.
def test_attempt_outcomes_are_exactly_the_five_frozen_outcomes() -> None:
    assert [outcome.value for outcome in AttemptOutcome] == [
        "VALID_RESULT",
        "INFRASTRUCTURE_FAILURE",
        "STRUCTURAL_FAILURE",
        "PROVIDER_SCHEMA_INCOMPATIBILITY",
        "EXECUTOR_FAILURE",
    ]


# 3. invalid SHA rejected.
@pytest.mark.parametrize(
    "sha",
    ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, "0x" + "a" * 62],
)
def test_artifact_digest_rejects_non_lowercase_64_hex_sha256(sha: str) -> None:
    with pytest.raises(ValidationError):
        Phase1ArtifactDigest(path="evals/comparative/phase1/raw/H-001/FOUNDRY.json", sha256=sha)


# 4. unsafe relative path rejected.
@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "../.foundry-sealed-evals/hidden-judge.json",
        "evals/../../escape.json",
        "~/secret.json",
    ],
)
def test_artifact_digest_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        Phase1ArtifactDigest(path=path, sha256=_SHA_A)


def test_artifact_digest_accepts_a_safe_relative_path() -> None:
    digest = Phase1ArtifactDigest(
        path="evals/comparative/phase1/raw/H-001/FOUNDRY.json", sha256=_SHA_A
    )
    assert digest.sha256 == _SHA_A


# 5. attempts require completed_at >= started_at.
def test_attempt_rejects_completion_before_start() -> None:
    with pytest.raises(ValidationError):
        _attempt(completed_at=_T0 - timedelta(seconds=1))


def test_attempt_allows_equal_start_and_completion() -> None:
    assert _attempt(completed_at=_T0).completed_at == _T0


def test_attempt_rejects_attempt_number_below_one() -> None:
    with pytest.raises(ValidationError):
        _attempt(attempt_number=0)


def test_attempt_rejects_empty_execution_id() -> None:
    with pytest.raises(ValidationError):
        _attempt(execution_id="")


def test_attempt_rejects_non_uuid_execution_id() -> None:
    with pytest.raises(ValidationError):
        _attempt(execution_id="slot-H-001-FOUNDRY-1")


def test_attempt_rejects_execution_position_outside_the_pair() -> None:
    with pytest.raises(ValidationError):
        _attempt(execution_position=3)


def test_attempt_error_fields_are_sanitized_of_credentials() -> None:
    attempt = _attempt(
        outcome=AttemptOutcome.INFRASTRUCTURE_FAILURE,
        error_type="ConnectionError",
        error_message="failed with api_key=xai-abcdef1234567890 while connecting",
    )
    assert attempt.error_message is not None
    assert "xai-abcdef1234567890" not in attempt.error_message
    assert "[REDACTED]" in attempt.error_message


def test_sanitize_error_text_collapses_newlines_and_truncates() -> None:
    cleaned = sanitize_error_text("line one\nline two\r\nline three " + "x" * 5000)
    assert "\n" not in cleaned
    assert "\r" not in cleaned
    assert len(cleaned) <= 1024


def test_sanitize_error_text_redacts_authorization_headers() -> None:
    cleaned = sanitize_error_text("authorization: Bearer supersecretvalue")
    assert "supersecretvalue" not in cleaned


# 6. valid raw evidence consistency.
def test_valid_foundry_raw_evidence_forbids_a_structural_error() -> None:
    evidence = FoundryRawEvidence(
        case_id="H-001",
        contestant_id=ContestantId.FOUNDRY,
        blind_label=BlindSystemLabel.SYSTEM_A,
        result=_foundry_result(),
        structural_validation_passed=True,
        structural_error=None,
    )
    assert evidence.structural_error is None
    with pytest.raises(ValidationError):
        FoundryRawEvidence(
            case_id="H-001",
            contestant_id=ContestantId.FOUNDRY,
            blind_label=BlindSystemLabel.SYSTEM_A,
            result=_foundry_result(),
            structural_validation_passed=True,
            structural_error="something",
        )


def test_valid_baseline_raw_evidence_forbids_a_structural_error() -> None:
    with pytest.raises(ValidationError):
        BaselineRawEvidence(
            case_id="H-001",
            contestant_id=ContestantId.BASELINE,
            blind_label=BlindSystemLabel.SYSTEM_B,
            result=_baseline_result(),
            structural_validation_passed=True,
            structural_error="something",
        )


def test_raw_evidence_pins_its_contestant_identity() -> None:
    with pytest.raises(ValidationError):
        FoundryRawEvidence(
            case_id="H-001",
            contestant_id=ContestantId.BASELINE,
            blind_label=BlindSystemLabel.SYSTEM_A,
            result=_foundry_result(),
            structural_validation_passed=True,
            structural_error=None,
        )
    with pytest.raises(ValidationError):
        BaselineRawEvidence(
            case_id="H-001",
            contestant_id=ContestantId.FOUNDRY,
            blind_label=BlindSystemLabel.SYSTEM_B,
            result=_baseline_result(),
            structural_validation_passed=True,
            structural_error=None,
        )


# 7. structural raw evidence consistency.
def test_failed_foundry_raw_evidence_requires_a_non_empty_structural_error() -> None:
    for error in (None, ""):
        with pytest.raises(ValidationError):
            FoundryRawEvidence(
                case_id="H-001",
                contestant_id=ContestantId.FOUNDRY,
                blind_label=BlindSystemLabel.SYSTEM_A,
                result=_foundry_result(),
                structural_validation_passed=False,
                structural_error=error,
            )


def test_failed_baseline_raw_evidence_requires_a_non_empty_structural_error() -> None:
    for error in (None, ""):
        with pytest.raises(ValidationError):
            BaselineRawEvidence(
                case_id="H-001",
                contestant_id=ContestantId.BASELINE,
                blind_label=BlindSystemLabel.SYSTEM_B,
                result=_baseline_result(),
                structural_validation_passed=False,
                structural_error=error,
            )


def test_structural_failure_preserves_the_original_unrepaired_result() -> None:
    result = _foundry_result()
    evidence = FoundryRawEvidence(
        case_id="H-001",
        contestant_id=ContestantId.FOUNDRY,
        blind_label=BlindSystemLabel.SYSTEM_A,
        result=result,
        structural_validation_passed=False,
        structural_error="duplicate gap identity: AMBIGUITY:alpha-subject",
    )
    assert evidence.result == result


# 8. BlindOutput contains no contestant field.
def test_blind_output_has_exactly_the_neutral_fields() -> None:
    assert set(BlindOutput.model_fields) == {"case_id", "system_label", "predictions"}


def test_blind_output_rejects_a_contestant_field() -> None:
    with pytest.raises(ValidationError):
        BlindOutput(
            case_id="H-001",
            system_label=BlindSystemLabel.SYSTEM_A,
            predictions=(_prediction(),),
            contestant_id=ContestantId.FOUNDRY,
        )


# 9. BlindOutput schema contains no provider/cost/prompt/semantic proposal field.
def test_blind_output_schema_discloses_no_contestant_identity() -> None:
    schema_text = json.dumps(BlindOutput.model_json_schema())
    for forbidden in ("FOUNDRY", "BASELINE", "xAI", "grok", "Foundry"):
        assert forbidden not in schema_text


def test_blind_output_schema_has_no_provider_cost_prompt_or_proposal_fields() -> None:
    names = _schema_property_names(BlindOutput)
    forbidden = {
        "contestant_id",
        "provider",
        "model",
        "cost",
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "usage",
        "system_prompt",
        "prompt",
        "semantic_proposals",
        "gap_proposals",
        "proposal_id",
        "gap_id",
        "affected_proposal_ids",
        "blocking",
        "sdk_version",
        "reasoning_effort",
    }
    assert names & forbidden == set()


def test_blind_output_carries_only_frozen_neutral_predictions() -> None:
    output = BlindOutput(
        case_id="H-001",
        system_label=BlindSystemLabel.SYSTEM_A,
        predictions=(_prediction(1), _prediction(2)),
    )
    assert tuple(item.prediction_id for item in output.predictions) == ("P-001", "P-002")


# 10. valid execution record requires raw + blind hashes.
def test_valid_execution_record_requires_raw_and_blind_evidence() -> None:
    assert _valid_record().terminal_status is Phase1TerminalStatus.VALID
    for missing in (
        {"raw_result_path": None, "raw_result_sha256": None},
        {"blind_output_path": None, "blind_output_sha256": None},
    ):
        with pytest.raises(ValidationError):
            _valid_record(**missing)


def test_execution_record_requires_path_and_hash_together() -> None:
    with pytest.raises(ValidationError):
        _valid_record(raw_result_sha256=None)
    with pytest.raises(ValidationError):
        _valid_record(blind_output_path=None)


# 11. structural failure forbids blind output.
def test_structural_failure_record_forbids_blind_output() -> None:
    assert _structural_record().blind_output_path is None
    with pytest.raises(ValidationError):
        _structural_record(
            blind_output_path="evals/comparative/phase1/blind/H-001/SYSTEM-B.json",
            blind_output_sha256=_SHA_B,
        )


def test_structural_failure_record_may_omit_raw_output_and_usage() -> None:
    record = _structural_record(
        raw_result_path=None,
        raw_result_sha256=None,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
        wall_clock_ms=None,
    )
    assert record.terminal_status is Phase1TerminalStatus.STRUCTURAL_FAILURE
    assert record.raw_result_path is None


# 12. usage required on valid result.
@pytest.mark.parametrize(
    "field", ["input_tokens", "output_tokens", "cost_usd", "wall_clock_ms"]
)
def test_valid_execution_record_requires_every_usage_field(field: str) -> None:
    with pytest.raises(ValidationError):
        _valid_record(**{field: None})


def test_execution_record_requires_at_least_one_attempt() -> None:
    with pytest.raises(ValidationError):
        _valid_record(attempt_execution_ids=())


def test_execution_record_rejects_duplicate_attempt_ids() -> None:
    with pytest.raises(ValidationError):
        _valid_record(attempt_execution_ids=(_execution_id(1), _execution_id(1)))


# 13. output manifest requires exactly 24 slots.
def test_output_manifest_requires_exactly_twenty_four_executions() -> None:
    assert len(_manifest().executions) == TOTAL_CONTESTANT_SLOTS == 24
    executions, attempts = _bundle()
    with pytest.raises(ValidationError):
        _manifest(
            executions=executions[:-1],
            attempts=attempts[:-1],
            valid_results=23,
        )


def test_output_manifest_pins_the_slot_total_literal() -> None:
    with pytest.raises(ValidationError):
        _manifest(total_contestant_slots=23)


def test_output_manifest_requires_both_contestants_per_case() -> None:
    executions, attempts = _bundle()
    duplicated = (
        executions[0],
        executions[0].model_copy(update={"execution_position": 2}),
        *executions[2:],
    )
    with pytest.raises(ValidationError):
        _manifest(executions=duplicated, attempts=attempts)


# 14. valid + structural == 24.
def test_output_manifest_requires_valid_plus_structural_to_equal_the_slot_total() -> None:
    with pytest.raises(ValidationError):
        _manifest(valid_results=23, structural_failures=0)
    with pytest.raises(ValidationError):
        _manifest(valid_results=20, structural_failures=3)


def test_output_manifest_counts_must_match_the_recorded_terminal_statuses() -> None:
    with pytest.raises(ValidationError):
        _manifest(valid_results=23, structural_failures=1)


def test_output_manifest_accepts_a_mixed_valid_and_structural_bundle() -> None:
    executions, attempts = _bundle()
    failed = executions[1].model_copy(
        update={
            "terminal_status": Phase1TerminalStatus.STRUCTURAL_FAILURE,
            "blind_output_path": None,
            "blind_output_sha256": None,
        }
    )
    manifest = _manifest(
        executions=(executions[0], failed, *executions[2:]),
        attempts=attempts,
        valid_results=23,
        structural_failures=1,
    )
    assert manifest.structural_failures == 1


# 15. case sequence preserved.
def test_output_manifest_preserves_the_frozen_case_sequence() -> None:
    assert _manifest().case_sequence == CASE_SEQUENCE


def test_output_manifest_rejects_an_execution_outside_the_case_sequence() -> None:
    executions, attempts = _bundle()
    stray = executions[0].model_copy(update={"case_id": "H-999"})
    with pytest.raises(ValidationError):
        _manifest(executions=(stray, *executions[1:]), attempts=attempts)


def test_output_manifest_rejects_a_duplicated_case_in_the_sequence() -> None:
    with pytest.raises(ValidationError):
        _manifest(case_sequence=CASE_SEQUENCE[:-1] + (CASE_SEQUENCE[0],))


# 16. manifest serialization deterministic.
def test_manifest_serialization_is_byte_for_byte_deterministic() -> None:
    manifest = _manifest()
    first = phase1_canonical_bytes(manifest)
    second = phase1_canonical_bytes(_manifest())
    assert first == second
    assert phase1_canonical_json(manifest).endswith("\n")


def test_manifest_round_trips_through_canonical_json() -> None:
    manifest = _manifest()
    reloaded = Phase1OutputManifest.model_validate(
        json.loads(phase1_canonical_bytes(manifest).decode("utf-8"))
    )
    assert phase1_canonical_bytes(reloaded) == phase1_canonical_bytes(manifest)


def test_canonical_json_sorts_object_keys() -> None:
    text = phase1_canonical_json(
        BlindOutput(
            case_id="H-001",
            system_label=BlindSystemLabel.SYSTEM_A,
            predictions=(_prediction(),),
        )
    )
    payload = json.loads(text)
    assert list(payload) == sorted(payload)


# 17. no API key field exists anywhere.
@pytest.mark.parametrize(
    "model",
    [
        Phase1ArtifactDigest,
        AttemptStartedRecord,
        AttemptRecord,
        FoundryRawEvidence,
        BaselineRawEvidence,
        BlindOutput,
        Phase1ExecutionRecord,
        Phase1OutputManifest,
    ],
)
def test_no_phase1_evidence_model_carries_a_credential_field(model: type[BaseModel]) -> None:
    names = {name.lower() for name in _schema_property_names(model)}
    forbidden = {
        "api_key",
        "apikey",
        "api-key",
        "xai_api_key",
        "secret",
        "credential",
        "credentials",
        "authorization",
        "password",
        "access_token",
        "bearer",
        "environment",
        "headers",
        "request_headers",
    }
    assert names & forbidden == set()


def test_no_phase1_evidence_schema_mentions_a_key_environment_variable() -> None:
    for model in (AttemptRecord, Phase1ExecutionRecord, Phase1OutputManifest):
        assert "XAI_API_KEY" not in json.dumps(model.model_json_schema())


# 18. provider revision absence explicitly represented.
def test_provider_revision_absence_is_explicit() -> None:
    manifest = _manifest()
    assert manifest.provider_revision is None
    assert manifest.provider_revision_observable is False
    dumped = manifest.model_dump(mode="json")
    assert "provider_revision" in dumped
    assert dumped["provider_revision"] is None


def test_unobservable_provider_revision_must_stay_none() -> None:
    with pytest.raises(ValidationError):
        _manifest(provider_revision="rev-2026-09-10", provider_revision_observable=False)


# 19. retry policy exact string frozen.
def test_infrastructure_retry_policy_string_is_frozen() -> None:
    assert INFRASTRUCTURE_RETRY_POLICY == (
        "one-immediate-retry-then-pause-resume-same-slot-only"
    )
    assert _manifest().infrastructure_retry_policy == INFRASTRUCTURE_RETRY_POLICY
    with pytest.raises(ValidationError):
        _manifest(infrastructure_retry_policy="unlimited-retries")


# 20. structural policy exact string frozen.
def test_structural_failure_policy_string_is_frozen() -> None:
    assert STRUCTURAL_FAILURE_POLICY == "terminal-no-semantic-retry"
    with pytest.raises(ValidationError):
        _manifest(structural_failure_policy="retry-until-valid")


# 21. schema incompatibility policy exact string frozen.
def test_schema_incompatibility_policy_string_is_frozen() -> None:
    assert SCHEMA_INCOMPATIBILITY_POLICY == "abort-experiment"
    with pytest.raises(ValidationError):
        _manifest(schema_incompatibility_policy="downgrade-schema")


def test_pairing_policy_and_manifest_version_strings_are_frozen() -> None:
    assert PAIRING_POLICY == "back-to-back"
    assert PHASE1_OUTPUT_MANIFEST_VERSION == "intent-comparative-phase1-output-v1"
    with pytest.raises(ValidationError):
        _manifest(pairing_policy="batched-by-contestant")
    with pytest.raises(ValidationError):
        _manifest(manifest_version="intent-comparative-phase1-output-v2")


def test_manifest_provider_identity_is_frozen() -> None:
    for override in (
        {"provider": "OpenAI"},
        {"model": "grok-3"},
        {"reasoning_effort": "low"},
        {"sdk_package": "openai"},
    ):
        with pytest.raises(ValidationError):
            _manifest(**override)


def test_manifest_retry_totals_must_match_the_recorded_attempts() -> None:
    with pytest.raises(ValidationError):
        _manifest(infrastructure_retries=1)
    with pytest.raises(ValidationError):
        _manifest(infrastructure_failures=1)


def test_manifest_attempts_must_cover_exactly_the_referenced_executions() -> None:
    executions, attempts = _bundle()
    with pytest.raises(ValidationError):
        _manifest(executions=executions, attempts=attempts[:-1])


def test_manifest_rejects_completion_before_start() -> None:
    with pytest.raises(ValidationError):
        _manifest(completed_at=_T0 - timedelta(seconds=1))


# Append-only evidence writing.
def test_attempt_started_file_uses_exclusive_creation(tmp_path: Path) -> None:
    started = AttemptStartedRecord(
        execution_id=_execution_id(1),
        case_id="H-001",
        contestant_id=ContestantId.FOUNDRY,
        blind_label=BlindSystemLabel.SYSTEM_A,
        execution_position=1,
        attempt_number=1,
        started_at=_T0,
    )
    target = tmp_path / "attempts" / f"{_execution_id(1)}-started.json"
    create_attempt_started(target, started)
    assert json.loads(target.read_text())["execution_id"] == _execution_id(1)
    with pytest.raises(Phase1WriteConflict):
        create_attempt_started(target, started)


def test_write_evidence_refuses_to_overwrite_a_finalized_file(tmp_path: Path) -> None:
    output = BlindOutput(
        case_id="H-001",
        system_label=BlindSystemLabel.SYSTEM_A,
        predictions=(_prediction(),),
    )
    target = tmp_path / "blind" / "H-001" / "SYSTEM-A.json"
    digest = write_evidence(tmp_path, "blind/H-001/SYSTEM-A.json", output)
    assert digest.path == "blind/H-001/SYSTEM-A.json"
    assert target.read_bytes() == phase1_canonical_bytes(output)
    with pytest.raises(Phase1WriteConflict):
        write_evidence(tmp_path, "blind/H-001/SYSTEM-A.json", output)


def test_write_evidence_rejects_an_unsafe_relative_path(tmp_path: Path) -> None:
    output = BlindOutput(
        case_id="H-001",
        system_label=BlindSystemLabel.SYSTEM_A,
        predictions=(_prediction(),),
    )
    with pytest.raises(ValueError):
        write_evidence(tmp_path, "../escaped.json", output)
