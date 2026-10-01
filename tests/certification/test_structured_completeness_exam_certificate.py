"""The structured exam's certificate, its binding, its standing, the routing it grants, and what
no other certificate can grant (offline).

A structured certificate binds the exact structured verifier contract (policy, instruction,
report format, canonical schema, provider wire schema and compiler) and this exam. Only a CURRENT
one yields a routing descriptor, and that descriptor serves exactly the v2 contract. A free-text
(v1-lineage) record, Astra's IE3 graph certificate, or anything else yields nothing; and no
committed record of either completeness lineage is a PASS.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import tests.certification._structured_completeness_exam as exam
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_V1_CONTRACT,
    COMPLETENESS_V2_CONTRACT,
)
from foundry.model_runtime.domain import (
    CONTRACT_BOUND_TASKS,
    CertifiedContract,
    MessageRole,
    ModelCapability,
    ModelContract,
    ModelDescriptor,
    ModelIdentity,
    ModelMessage,
    ModelRequest,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.registry import build_registry
from tests.certification._certification_run import EVIDENCE_ROOT, Contestant
from tests.certification._completeness_exam import CERTIFIED_CONFIGURATION
from tests.certification._structured_completeness_exam import (
    STRUCTURED_BINDING_FIELDS,
    STRUCTURED_EVIDENCE_NAMESPACE,
    STRUCTURED_EXAM_VERSION,
    STRUCTURED_RECORD_FORMAT,
    certified_descriptor,
    current_structured_identity,
    perfect_findings,
    structured_certificate_binds,
    structured_certificate_standing,
    structured_evidence_problems,
    structured_exam_manifest,
    structured_exam_sha256,
    structured_seal_problems,
    write_structured_certification,
    write_structured_seal,
)
from tests.certification.test_structured_completeness_exam_harness import (
    SCRIPTED,
    V2_SITTING,
    answering,
    sit,
)

ASTRA = ModelIdentity(provider="openai", model="gpt-6-astra")
SCV = ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION


def _record(tmp_path: Path, attempts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    contestant = Contestant(
        identity=SCRIPTED,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        reasoning_effort=CERTIFIED_CONFIGURATION.reasoning_effort,
        timeout_seconds=CERTIFIED_CONFIGURATION.timeout_seconds,
        task=SCV,
        evidence_namespace=str(tmp_path / "record"),
        wire_schema=OpenAIModelProvider.wire_schema,
        wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
        contracts=V2_SITTING,
    )
    return write_structured_certification(
        contestant,
        sit(answering(perfect_findings))[0] if attempts is None else attempts,
        frozen_production_base="0" * 40,
        configuration=CERTIFIED_CONFIGURATION,
    )


def _as_astra(record: dict[str, Any]) -> dict[str, Any]:
    relabelled = copy.deepcopy(record)
    relabelled.update(provider=ASTRA.provider, model=ASTRA.model, candidate="openai/gpt-6-astra")
    return relabelled


def _request(contract: ModelContract | None, task: ModelTask = SCV) -> ModelRequest:
    return ModelRequest(
        task=task,
        tier=ModelTier.REASONER,
        messages=(ModelMessage(role=MessageRole.USER, content="x"),),
        required_capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        policy_id=contract.policy_id if contract else "graph",
        policy_version=contract.policy_version if contract else "graph-v6",
        contract=contract,
        trace=ModelTraceContext(run_id="R", call_id="C"),
    )


def _serves(descriptor: ModelDescriptor, request: ModelRequest) -> bool:
    return bool(build_registry((descriptor,)).eligible_models(request))


# --- identity -------------------------------------------------------------------------------------


def test_a_new_lineage_never_a_free_text_exam_version() -> None:
    import tests.certification._completeness_exam_v5 as v5

    assert STRUCTURED_EXAM_VERSION == "ie2-semantic-completeness-structured-exam-v1"
    assert STRUCTURED_RECORD_FORMAT == "ie2-semantic-completeness-structured-certification.v1"
    assert STRUCTURED_EVIDENCE_NAMESPACE == "semantic_completeness_structured_exam_v1"
    assert "v6" not in STRUCTURED_EXAM_VERSION
    assert str(STRUCTURED_EVIDENCE_NAMESPACE) != str(v5.COMPLETENESS_EVIDENCE_NAMESPACE)


def test_the_manifest_seals_corpus_answer_key_scorer_contract_routing_and_binding() -> None:
    manifest = structured_exam_manifest()
    assert (
        manifest["acceptance"]["call_budget"] == 84 and manifest["acceptance"]["runs_per_case"] == 3
    )
    identity = manifest["identity"]
    assert identity["verifier_policy_version"] == "ie2-semantic-completeness-v2"
    assert identity["report_format"] == "ie2-semantic-completeness-report.v2"
    assert identity["routing_contract"] == COMPLETENESS_V2_CONTRACT.model_dump(mode="json")
    for function in (
        "finding_matches",
        "score_structured_report",
        "score_global_gates",
        "run_structured_attempt",
        "structured_verdict",
        "certified_descriptor",
    ):
        assert f"tests.certification._structured_completeness_exam.{function}" in manifest["code"]
    kc = next(c for c in manifest["cases"] if c["case_id"] == "S26")
    assert [r["kinds"] for r in kc["expected"]["p1"]["regions"]] == [["CHANNEL"], ["CONSEQUENCE"]]
    assert manifest["binding_fields"] == list(STRUCTURED_BINDING_FIELDS)
    assert "report_format" in STRUCTURED_BINDING_FIELDS


def test_any_change_to_the_answer_key_moves_the_exam_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    before = structured_exam_sha256()
    kc = exam.case_by_id("S26")
    fewer = exam.StructuredCase(
        kc.case_id, kc.category, kc.request, {"p1": exam.incomplete(kc.expected["p1"].regions[0])}
    )
    monkeypatch.setattr(exam, "CASES", tuple(fewer if c is kc else c for c in exam.CASES))
    assert structured_exam_sha256() != before


# --- the certificate --------------------------------------------------------------------------


def test_the_written_record_binds_every_field(tmp_path: Path) -> None:
    record = _record(tmp_path)
    assert (record["verdict"], record["passed_attempts"], record["call_budget"]) == ("PASS", 84, 84)
    for field in STRUCTURED_BINDING_FIELDS:
        assert field in record, field
    assert record["report_format"] == "ie2-semantic-completeness-report.v2"
    assert record["instruction_sha256"] == COMPLETENESS_V2_CONTRACT.instruction_sha256
    assert record["canonical_schema_sha256"] == COMPLETENESS_V2_CONTRACT.output_schema_sha256


@pytest.mark.parametrize("field", STRUCTURED_BINDING_FIELDS)
def test_binding_fails_closed_on_any_changed_or_missing_field(tmp_path: Path, field: str) -> None:
    record = _as_astra(_record(tmp_path))
    current = current_structured_identity(ASTRA)
    assert current is not None and structured_certificate_binds(record, current)
    assert not structured_certificate_binds(dict(record, **{field: "something else"}), current)
    assert not structured_certificate_binds(
        {k: v for k, v in record.items() if k != field}, current
    )
    if field not in ("provider", "model"):
        assert structured_certificate_standing(dict(record, **{field: "x"})) != "CURRENT"


# --- the routing a certificate grants ---------------------------------------------------------


def test_a_current_structured_certificate_serves_exactly_the_v2_contract(tmp_path: Path) -> None:
    record = _as_astra(_record(tmp_path))
    assert structured_certificate_standing(record) == "CURRENT"
    descriptor = certified_descriptor(record)
    assert descriptor is not None and descriptor.identity == ASTRA
    assert _serves(descriptor, _request(COMPLETENESS_V2_CONTRACT))
    assert not _serves(descriptor, _request(COMPLETENESS_V1_CONTRACT)), "v2 never serves v1"
    assert not _serves(descriptor, _request(None, ModelTask.ARCHITECTURE))
    (certified,) = descriptor.certified_contracts
    assert certified.wire_schema_compiler == OpenAIModelProvider.WIRE_SCHEMA_COMPILER


def test_a_failed_or_foreign_record_grants_no_routing(tmp_path: Path) -> None:
    record = _as_astra(_record(tmp_path))
    assert certified_descriptor(dict(record, verdict="NOT CERTIFIED")) is None
    assert certified_descriptor(dict(record, exam_sha256="f" * 64)) is None
    assert (
        certified_descriptor(dict(record, verifier_policy_version="ie2-semantic-completeness-v1"))
        is None
    )


def test_a_free_text_v1_certificate_can_never_authorize_v2(tmp_path: Path) -> None:
    """Even a PASS of the free-text lineage (none exists) yields no structured routing, and the
    v1 contract it would certify never serves a v2 request."""
    import tests.certification._completeness_exam as freetext
    import tests.certification._completeness_exam_v5 as v5

    v1_pass = dict(
        _as_astra(_record(tmp_path)),
        record_format=freetext.COMPLETENESS_CERTIFICATION_RECORD_FORMAT,
        exam_version=v5.COMPLETENESS_EXAM_VERSION,
        exam_sha256=v5.EXPECTED_COMPLETENESS_EXAM_SHA256,
        verifier_policy_version="ie2-semantic-completeness-v1",
    )
    assert structured_certificate_standing(v1_pass) == "NOT_BINDING"
    assert certified_descriptor(v1_pass) is None
    v1_routing = ModelDescriptor(
        identity=ASTRA,
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        certified_tasks=frozenset({SCV}),
        certified_contracts=frozenset(
            {CertifiedContract(task=SCV, contract=COMPLETENESS_V1_CONTRACT)}
        ),
    )
    assert _serves(v1_routing, _request(COMPLETENESS_V1_CONTRACT))
    assert not _serves(v1_routing, _request(COMPLETENESS_V2_CONTRACT))


def test_no_committed_completeness_record_of_either_lineage_is_a_pass() -> None:
    records = sorted(EVIDENCE_ROOT.glob("*/*/semantic_completeness_*/certification.json"))
    assert len(records) == 4, records  # free-text v2, v3, v4, v5
    for path in records:
        record = json.loads(path.read_text())
        assert record["verdict"] == "NOT CERTIFIED", path
        assert structured_certificate_standing(record) == "NOT_CERTIFIED"
        assert certified_descriptor(record) is None


def test_astras_ie3_graph_certificate_keeps_its_meaning_and_grants_nothing_here() -> None:
    from tests.certification._intent_graph_exam import graph_certificate_standing

    path = EVIDENCE_ROOT / "openai/gpt-6-astra/intent_graph_synthesis_exam_v6/certification.json"
    record = json.loads(path.read_text())
    assert record["verdict"] == "PASS"
    assert graph_certificate_standing(record) == "CURRENT", "its own standing is unchanged"
    assert structured_certificate_standing(record) == "NOT_BINDING"
    assert certified_descriptor(record) is None
    assert ModelTask.INTENT_GRAPH_SYNTHESIS not in CONTRACT_BOUND_TASKS, "IE3 routes as before"
    other = ModelDescriptor(
        identity=ASTRA,
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset({ModelCapability.STRUCTURED_OUTPUT}),
        certified_tasks=frozenset({ModelTask.ARCHITECTURE}),
    )
    assert _serves(other, _request(None, ModelTask.ARCHITECTURE)), "unrelated tasks unchanged"
    assert not _serves(other, _request(COMPLETENESS_V2_CONTRACT))


def test_every_committed_certification_record_still_parses() -> None:
    paths = sorted(EVIDENCE_ROOT.rglob("certification.json"))
    assert paths
    for path in paths:
        assert isinstance(json.loads(path.read_text()), dict), path


# --- evidence integrity and the seal -------------------------------------------------------


def test_integrity_catches_rewritten_evidence(tmp_path: Path) -> None:
    record = _record(tmp_path)
    assert structured_evidence_problems(record) == ()
    i = next(i for i, a in enumerate(record["attempts"]) if a["case"] == "S26")
    wrong = copy.deepcopy(record["attempts"][i]["parsed_report"])
    wrong["verdicts"][0]["findings"] = wrong["verdicts"][0]["findings"][:1]
    forged = copy.deepcopy(record)
    forged["attempts"][i].update(parsed_report=wrong, raw_output=wrong)
    assert structured_evidence_problems(forged) != ()
    assert structured_evidence_problems(dict(record, passed_attempts=85)) != ()
    assert structured_evidence_problems(dict(record, exam_sha256="f" * 64)) != ()


def test_the_seal_is_absent_until_written_and_then_exactly_the_exam(tmp_path: Path) -> None:
    seal = tmp_path / "seal.json"
    assert structured_seal_problems(seal) != ()
    write_structured_seal(seal, harness_sha="a" * 40)
    assert structured_seal_problems(seal) == ()
    document = json.loads(seal.read_text())
    document["manifest"]["acceptance"]["runs_per_case"] = 1
    seal.write_text(json.dumps(document))
    assert structured_seal_problems(seal) != ()
