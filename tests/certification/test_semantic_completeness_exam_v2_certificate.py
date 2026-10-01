"""Exam v2's identity, certificate, binding, standing, evidence integrity and seal (offline).

A certificate for SEMANTIC_COMPLETENESS_VERIFICATION is its own task certificate: it binds the
provider, model, task, verifier policy, instruction digest, canonical report schema, provider
wire schema, compiler, exam v2 (id, version, hash), provider configuration, repetition rule and
call budget together, fail-closed. Astra's IE3 graph certificate can never stand for it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import tests.certification._completeness_exam as exam
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.domain.semantic_completeness import CompletenessReport
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from tests.certification._certification_run import (
    EVIDENCE_ROOT,
    Contestant,
    free_text_completeness_sitting,
)
from tests.certification._completeness_exam import (
    BINDING_FIELDS,
    CERTIFIED_CONFIGURATION,
    COMPLETENESS_CERTIFICATION_RECORD_FORMAT,
    COMPLETENESS_EVIDENCE_NAMESPACE,
    COMPLETENESS_EXAM_ID,
    COMPLETENESS_EXAM_VERSION,
    PRIOR_COMPLETENESS_EXAMS,
    certificate_binds,
    completeness_certificate_standing,
    completeness_evidence_problems,
    completeness_exam_manifest,
    completeness_exam_sha256,
    completeness_seal_problems,
    current_completeness_identity,
    write_completeness_certification,
    write_completeness_seal,
)
from tests.certification._schema_identity import schema_sha256
from tests.certification.test_semantic_completeness_exam_v2_harness import (
    SCRIPTED,
    perfect,
    sit,
)

ASTRA = ModelIdentity(provider="openai", model="gpt-6-astra")


def _contestant(tmp_path: Path, identity: ModelIdentity = SCRIPTED) -> Contestant:
    return Contestant(
        identity=identity,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        reasoning_effort=CERTIFIED_CONFIGURATION.reasoning_effort,
        timeout_seconds=CERTIFIED_CONFIGURATION.timeout_seconds,
        task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
        contracts=free_text_completeness_sitting(),
        evidence_namespace=str(tmp_path / "record"),
        wire_schema=OpenAIModelProvider.wire_schema,
        wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    )


def _record(tmp_path: Path, attempts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return write_completeness_certification(
        _contestant(tmp_path),
        sit(perfect)[0] if attempts is None else attempts,
        frozen_production_base="0" * 40,
        configuration=CERTIFIED_CONFIGURATION,
    )


def _current(identity: ModelIdentity) -> dict[str, Any]:
    current = current_completeness_identity(identity)
    assert current is not None
    return current


def _as_astra(record: dict[str, Any]) -> dict[str, Any]:
    """The same record as if the OpenAI candidate had earned it (synthetic, offline only)."""
    relabelled = copy.deepcopy(record)
    relabelled.update(provider=ASTRA.provider, model=ASTRA.model, candidate="openai/gpt-6-astra")
    return relabelled


# --- identity ---------------------------------------------------------------------------------


def test_the_exam_is_a_new_identity_beside_the_unchanged_prepared_v1() -> None:
    from foundry.experiments.completeness_verifier_exam import exam as v1

    assert COMPLETENESS_EXAM_ID == "ie2.semantic-completeness-verification.certification-exam"
    assert COMPLETENESS_EXAM_VERSION == "ie2-semantic-completeness-exam-v2"
    (prior,) = PRIOR_COMPLETENESS_EXAMS
    assert prior.exam_version == v1.EXAM_VERSION == "ie2-semantic-completeness-exam-v1"
    assert prior.exam_sha256 == v1.exam_sha256()
    assert prior.status == "PREPARED_NEVER_SAT" and prior.superseded_by == COMPLETENESS_EXAM_VERSION
    assert completeness_exam_sha256() != prior.exam_sha256


def test_the_manifest_freezes_corpus_verdicts_markers_scorer_rule_budget_and_binding() -> None:
    manifest = completeness_exam_manifest()
    assert manifest["exam_id"] == COMPLETENESS_EXAM_ID
    assert manifest["exam_version"] == COMPLETENESS_EXAM_VERSION
    assert [c["case_id"] for c in manifest["cases"]] == [c.case_id for c in exam.CASES]
    regression = next(c for c in manifest["cases"] if c["case_id"] == "C21")
    assert regression["request"] == exam.case_by_id("C21").request.model_dump(mode="json")
    (sealed,) = regression["expected"]
    assert sealed["verdict"] == "INCOMPLETE"
    assert [g["name"] for g in sealed["groups"]] == ["lateness", "refusal"]
    assert sealed["forbidden"] == list(exam.DEADLINE_MISREAD)
    code = manifest["code"]
    for function in (
        "score_completeness_report",
        "score_completeness_global_gates",
        "run_completeness_attempt",
        "completeness_verdict",
        "render_request",
        "_case",
        "normalise",
        "identifies",
    ):
        assert f"tests.certification._completeness_exam.{function}" in code, function
    assert manifest["acceptance"] == {
        "rule": exam.COMPLETENESS_ACCEPTANCE_RULE,
        "cases": [c.case_id for c in exam.CASES],
        "runs_per_case": 3,
        "call_budget": 75,
    }
    assert manifest["identity"] == {
        "task": "SEMANTIC_COMPLETENESS_VERIFICATION",
        "tier": "REASONER",
        "verifier_policy_id": "ie2-semantic-completeness",
        "verifier_policy_version": "ie2-semantic-completeness-v1",
        "instruction_sha256": exam.EXPECTED_INSTRUCTION_SHA256,
        "canonical_schema_sha256": schema_sha256(CompletenessReport.model_json_schema()),
        "openai_wire_schema_sha256": schema_sha256(
            OpenAIModelProvider.wire_schema(CompletenessReport)
        ),
        "openai_wire_schema_compiler": "foundry.openai-structured-outputs.v1",
        "configuration": {
            "reasoning_effort": "high",
            "reasoning_mode": "standard",
            "timeout_seconds": 180.0,
            "output_guard": None,
        },
    }
    assert manifest["binding_fields"] == list(BINDING_FIELDS)


def test_any_change_to_a_marker_group_or_a_verdict_moves_the_exam_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = completeness_exam_sha256()
    regression = exam.case_by_id("C21")
    fewer = exam.Expectation("p1", "INCOMPLETE", "MISSING_REFUSAL_CONSEQUENCE", (exam.LATENESS_48,))
    edited = exam.CompletenessCase(
        regression.case_id, regression.category, regression.request, (fewer,)
    )
    monkeypatch.setattr(
        exam, "CASES", tuple(edited if c.case_id == "C21" else c for c in exam.CASES)
    )
    assert completeness_exam_sha256() != before


# --- the certificate --------------------------------------------------------------------------


def test_the_binding_fields_are_the_task_certificate_identity() -> None:
    assert set(BINDING_FIELDS) == {
        "record_format",
        "verdict",
        "provider",
        "model",
        "task",
        "verifier_policy_id",
        "verifier_policy_version",
        "instruction_sha256",
        "canonical_schema_sha256",
        "wire_schema_sha256",
        "wire_schema_compiler",
        "exam_id",
        "exam_version",
        "exam_sha256",
        "reasoning_effort",
        "reasoning_mode",
        "timeout_seconds",
        "output_guard",
        "runs_per_case",
        "call_budget",
    }


def test_the_written_record_carries_every_binding_field_and_every_attempt(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path)
    assert json.loads((tmp_path / "record" / "certification.json").read_text()) == record
    assert record["record_format"] == COMPLETENESS_CERTIFICATION_RECORD_FORMAT
    assert (record["exam_id"], record["exam_version"], record["exam_sha256"]) == (
        COMPLETENESS_EXAM_ID,
        COMPLETENESS_EXAM_VERSION,
        completeness_exam_sha256(),
    )
    assert (record["verifier_policy_id"], record["verifier_policy_version"]) == (
        "ie2-semantic-completeness",
        "ie2-semantic-completeness-v1",
    )
    assert record["instruction_sha256"] == exam.EXPECTED_INSTRUCTION_SHA256
    assert record["task"] == "SEMANTIC_COMPLETENESS_VERIFICATION"
    assert (record["runs_per_case"], record["call_budget"]) == (3, 75)
    assert (record["required_attempts"], record["recorded_attempts"]) == (75, 75)
    assert (record["passed_attempts"], record["verdict"]) == (75, "PASS")
    assert record["frozen_production_base"] == "0" * 40
    for field in BINDING_FIELDS:
        assert field in record, field


def test_the_writer_refuses_an_unbound_wire_schema_or_a_mismatched_configuration(
    tmp_path: Path,
) -> None:
    unbound = Contestant(
        identity=SCRIPTED,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
        contracts=free_text_completeness_sitting(),
        evidence_namespace=str(tmp_path / "x"),
    )
    with pytest.raises(ValueError, match="wire schema"):
        write_completeness_certification(
            unbound, [], frozen_production_base="x", configuration=CERTIFIED_CONFIGURATION
        )
    wrong_task = Contestant(
        identity=SCRIPTED,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        evidence_namespace=str(tmp_path / "y"),
        wire_schema=OpenAIModelProvider.wire_schema,
        wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    )
    with pytest.raises(ValueError, match="SEMANTIC_COMPLETENESS_VERIFICATION"):
        write_completeness_certification(
            wrong_task, [], frozen_production_base="x", configuration=CERTIFIED_CONFIGURATION
        )


def test_a_pass_binds_its_own_identity_and_nothing_else(tmp_path: Path) -> None:
    record = _as_astra(_record(tmp_path))
    current = _current(ASTRA)
    assert certificate_binds(record, **current)
    assert completeness_certificate_standing(record) == "CURRENT"
    other = _current(ModelIdentity(provider="openai", model="gpt-6-other"))
    assert not certificate_binds(record, **other)


@pytest.mark.parametrize("field", BINDING_FIELDS)
def test_binding_fails_closed_on_any_changed_or_missing_field(tmp_path: Path, field: str) -> None:
    record = _as_astra(_record(tmp_path))
    current = _current(ASTRA)
    changed = dict(record, **{field: "something else"})
    assert not certificate_binds(changed, **current)
    missing = {k: v for k, v in record.items() if k != field}
    assert not certificate_binds(missing, **current)
    if field not in ("provider", "model"):
        # standing reads the model a record names; renaming it names another candidate,
        # which the record then speaks for (and never for Astra, asserted above)
        assert completeness_certificate_standing(changed) != "CURRENT"
        assert completeness_certificate_standing(missing) != "CURRENT"


def test_standing_for_failed_superseded_foreign_and_unknown_records(tmp_path: Path) -> None:
    passed = _as_astra(_record(tmp_path))
    assert completeness_certificate_standing(dict(passed, verdict="NOT CERTIFIED")) == (
        "NOT_CERTIFIED"
    )
    (prior,) = PRIOR_COMPLETENESS_EXAMS
    on_v1 = dict(passed, exam_version=prior.exam_version, exam_sha256=prior.exam_sha256)
    assert completeness_certificate_standing(on_v1) == "SUPERSEDED"
    assert completeness_certificate_standing(dict(passed, exam_sha256="f" * 64)) == "NOT_BINDING"
    foreign = dict(passed, record_format="ie3-graph-certification.v3")
    assert completeness_certificate_standing(foreign) == "NOT_BINDING"


def test_astras_ie3_graph_certificate_never_stands_for_this_task() -> None:
    path = EVIDENCE_ROOT / "openai/gpt-6-astra/intent_graph_synthesis_exam_v6/certification.json"
    record = json.loads(path.read_text())
    assert record["verdict"] == "PASS"
    assert not certificate_binds(record, **_current(ASTRA))
    assert completeness_certificate_standing(record) == "NOT_BINDING"


def test_the_evidence_namespace_is_new_and_task_specific() -> None:
    from tests.certification._intent_graph_exam import (
        GRAPH_EVIDENCE_NAMESPACE,
        HISTORICAL_GRAPH_NAMESPACES,
    )

    assert COMPLETENESS_EVIDENCE_NAMESPACE == "semantic_completeness_verification_exam_v2"
    assert COMPLETENESS_EVIDENCE_NAMESPACE not in (
        GRAPH_EVIDENCE_NAMESPACE,
        *HISTORICAL_GRAPH_NAMESPACES,
    )


# --- evidence integrity -----------------------------------------------------------------------


def test_an_honest_record_has_no_integrity_problem(tmp_path: Path) -> None:
    assert completeness_evidence_problems(_record(tmp_path)) == ()


def _tamper(record: dict[str, Any], index: int, **changes: Any) -> dict[str, Any]:
    forged = copy.deepcopy(record)
    forged["attempts"][index].update(changes)
    return forged


def test_integrity_catches_every_kind_of_rewritten_evidence(tmp_path: Path) -> None:
    record = _record(tmp_path)
    kc = next(i for i, a in enumerate(record["attempts"]) if a["case"] == "C21")
    wrong = copy.deepcopy(record["attempts"][kc]["parsed_report"])
    wrong["verdicts"][0]["missing"] = ["the 48-hour deadline is missing"]
    forgeries = {
        "report rewritten under a PASS": _tamper(record, kc, parsed_report=wrong),
        "report and raw response rewritten under a PASS": _tamper(
            record, kc, parsed_report=wrong, raw_output=wrong
        ),
        "report removed under a PASS": _tamper(record, kc, parsed_report=None),
        "request rewritten": _tamper(record, kc, request_json="{}"),
        "another model's answer": _tamper(record, kc, model="gpt-6-other"),
        "verdict flipped": _tamper(record, 0, verdict="FAIL"),
        "attempt dropped": dict(record, attempts=record["attempts"][:-1]),
        "count inflated": dict(record, passed_attempts=76),
        "verdict forged": dict(record, verdict="PASS", attempts=record["attempts"][:3]),
        "earned on another exam": dict(record, exam_sha256="f" * 64),
    }
    for name, forged in forgeries.items():
        assert completeness_evidence_problems(forged) != (), name


def test_every_committed_certificate_in_this_namespace_is_internally_consistent() -> None:
    for path in sorted(
        EVIDENCE_ROOT.glob(f"*/*/{COMPLETENESS_EVIDENCE_NAMESPACE}/certification.json")
    ):
        assert completeness_evidence_problems(json.loads(path.read_text())) == (), path


# --- the seal ---------------------------------------------------------------------------------


def test_the_seal_is_absent_until_written_and_then_exactly_the_exam(tmp_path: Path) -> None:
    seal = tmp_path / "seal.json"
    assert completeness_seal_problems(seal) != ()
    write_completeness_seal(seal, harness_sha="a" * 40)
    assert completeness_seal_problems(seal) == ()
    document = json.loads(seal.read_text())
    assert document["harness_sha"] == "a" * 40
    assert document["exam_sha256"] == completeness_exam_sha256()
    assert document["manifest"] == completeness_exam_manifest()
    document["manifest"]["acceptance"]["runs_per_case"] = 1
    seal.write_text(json.dumps(document))
    assert completeness_seal_problems(seal) != ()


def test_an_attempt_that_never_produced_an_answer_is_recorded_without_a_request(
    tmp_path: Path,
) -> None:
    attempts = sit(perfect)[0]
    attempts[0] = {
        "case": "C01",
        "attempt": 1,
        "verdict": "INCOMPLETE",
        "failures": ["TransportFailure: connection reset"],
        "request_json": None,
        "raw_output": None,
        "parsed_report": None,
    }
    record = _record(tmp_path, attempts)
    assert record["verdict"] == "NOT CERTIFIED"
    assert completeness_evidence_problems(record) == ()
    forged_pass = _tamper(record, 0, verdict="PASS")
    assert completeness_evidence_problems(dict(forged_pass, passed_attempts=75)) != ()
