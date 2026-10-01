"""Exam v4's identity, certificate, binding, standing, evidence integrity, seal and history.

The certificate format, binding fields and fail-closed binding are exam v2's, unchanged; only
the exam identity moves. Exams v2 (NOT CERTIFIED 66/75) and v3 (NOT CERTIFIED 74/75) are
history: their live records are pinned byte for byte, each internally consistent under its own
exam, NOT_CERTIFIED under every standing, and never re-scored against exam v4. v4 succeeds v3;
it never replaces it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import tests.certification._completeness_exam as v2
import tests.certification._completeness_exam_v3 as v3
import tests.certification._completeness_exam_v4 as exam
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.domain.semantic_completeness import CompletenessReport
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from tests.certification._certification_run import EVIDENCE_ROOT, Contestant
from tests.certification._completeness_exam import (
    BINDING_FIELDS,
    CERTIFIED_CONFIGURATION,
    certificate_binds,
)
from tests.certification._completeness_exam_v4 import (
    COMPLETENESS_EVIDENCE_NAMESPACE,
    COMPLETENESS_EXAM_VERSION,
    HISTORICAL_EXAM_V3_NAMESPACE,
    HISTORICAL_V3_RECORD_SHA256,
    PRIOR_EXAMS,
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
from tests.certification.test_semantic_completeness_exam_v4_harness import (
    SCRIPTED,
    perfect,
    sit,
)

ASTRA = ModelIdentity(provider="openai", model="gpt-6-astra")
V2_RECORD = (
    EVIDENCE_ROOT / f"openai/gpt-6-astra/{v3.HISTORICAL_EXAM_V2_NAMESPACE}/certification.json"
)
V3_RECORD = EVIDENCE_ROOT / f"openai/gpt-6-astra/{HISTORICAL_EXAM_V3_NAMESPACE}/certification.json"


def _contestant(tmp_path: Path) -> Contestant:
    return Contestant(
        identity=SCRIPTED,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        reasoning_effort=CERTIFIED_CONFIGURATION.reasoning_effort,
        timeout_seconds=CERTIFIED_CONFIGURATION.timeout_seconds,
        task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
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
    relabelled = copy.deepcopy(record)
    relabelled.update(provider=ASTRA.provider, model=ASTRA.model, candidate="openai/gpt-6-astra")
    return relabelled


# --- identity ---------------------------------------------------------------------------------


def test_v4_succeeds_v1_v2_and_v3_and_never_replaces_them() -> None:
    assert COMPLETENESS_EXAM_VERSION == "ie2-semantic-completeness-exam-v4"
    assert PRIOR_EXAMS[:-1] == v3.PRIOR_EXAMS, "v4 keeps every exam v3 already succeeded"
    assert [(p.exam_version, p.status) for p in PRIOR_EXAMS] == [
        ("ie2-semantic-completeness-exam-v1", "PREPARED_NEVER_SAT"),
        ("ie2-semantic-completeness-exam-v2", "LIVE_NOT_CERTIFIED"),
        ("ie2-semantic-completeness-exam-v3", "LIVE_NOT_CERTIFIED"),
    ]
    v3_prior = PRIOR_EXAMS[-1]
    assert v3_prior.exam_sha256 == v3.completeness_exam_sha256()
    assert v3_prior.exam_sha256 == v3.EXPECTED_COMPLETENESS_EXAM_SHA256
    assert v3_prior.superseded_by == COMPLETENESS_EXAM_VERSION and "74/75" in v3_prior.defect
    assert completeness_exam_sha256() not in {p.exam_sha256 for p in PRIOR_EXAMS}


def test_the_manifest_seals_corpus_inventory_derivation_markers_scorer_and_binding() -> None:
    manifest = completeness_exam_manifest()
    assert manifest["exam_version"] == COMPLETENESS_EXAM_VERSION
    assert [c["case_id"] for c in manifest["cases"]] == [c.case_id for c in exam.CASES]
    regression = next(c for c in manifest["cases"] if c["case_id"] == "C21")
    (inventory,) = regression["inventory"]
    assert {a["status"] for a in inventory["assertions"]} == {"REPRESENTED", "MISSING"}
    (sealed,) = regression["expected"]
    assert sealed["verdict"] == "INCOMPLETE" and len(sealed["findings"]) == 2
    code = manifest["code"]
    for function in (
        "_completeness_exam_v4.inventory_problems",
        "_completeness_exam_v3.derive_verdict",
        "_completeness_exam_v4.expectation",
        "_completeness_exam_v4.identifies_actor",
        "_completeness_exam_v4._actor_then_role",
        "_completeness_exam_v4._role_then_actor",
        "_completeness_exam_v4._complement_denied",
        "_completeness_exam_v4.score_completeness_report",
        "_completeness_exam_v4.completeness_verdict",
        "_completeness_exam.identifies",
        "_completeness_exam.normalise",
        "_completeness_exam.score_completeness_global_gates",
        "_completeness_exam.run_completeness_attempt",
    ):
        assert f"tests.certification.{function}" in code, function
    assert manifest["acceptance"]["call_budget"] == 75
    assert manifest["acceptance"]["runs_per_case"] == 3
    assert manifest["identity"]["verifier_policy_version"] == "ie2-semantic-completeness-v1"
    assert manifest["identity"]["canonical_schema_sha256"] == schema_sha256(
        CompletenessReport.model_json_schema()
    )
    assert manifest["binding_fields"] == list(BINDING_FIELDS)
    assert [p["status"] for p in manifest["prior_exams"]] == [
        "PREPARED_NEVER_SAT",
        "LIVE_NOT_CERTIFIED",
        "LIVE_NOT_CERTIFIED",
    ]
    c05 = next(c for c in manifest["cases"] if c["case_id"] == "C05")
    (actor,) = [a for a in c05["inventory"][0]["assertions"] if a["kind"] == "ACTOR"]
    assert actor["groups"] == [] and set(actor["role"]) == {
        "actor", "action", "action_noun", "modal", "licensed", "grant", "complement",
    }  # fmt: skip


def test_any_change_to_an_inventory_or_a_role_moves_the_exam_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = completeness_exam_sha256()
    c21 = exam.case_by_id("C21")
    (inventory,) = c21.inventory
    fewer = v3.PropositionInventory(
        "p1",
        tuple(a for a in inventory.assertions if a.kind != "CHANNEL"),
        inventory.forbidden,
    )
    edited = v3.InventoryCase(
        c21.case_id, c21.category, c21.request, (fewer,), (exam.expectation(fewer),)
    )
    monkeypatch.setattr(exam, "CASES", tuple(edited if c is c21 else c for c in exam.CASES))
    assert completeness_exam_sha256() != before
    monkeypatch.undo()
    weaker = exam.ActorRole(**{**vars(exam.RENEWER_ROLE), "grant": exam.MAY})
    monkeypatch.setattr(exam, "ACTOR_ROLES", {**exam.ACTOR_ROLES, "C05": weaker})
    monkeypatch.setattr(exam, "CASES", tuple(exam._carried(c) for c in v3.CASES))
    assert completeness_exam_sha256() != before


# --- the certificate --------------------------------------------------------------------------


def test_the_written_record_carries_every_binding_field_of_exam_v3(tmp_path: Path) -> None:
    record = _record(tmp_path)
    assert json.loads((tmp_path / "record" / "certification.json").read_text()) == record
    assert record["record_format"] == "ie2-semantic-completeness-certification.v1"
    assert (record["exam_version"], record["exam_sha256"]) == (
        COMPLETENESS_EXAM_VERSION,
        completeness_exam_sha256(),
    )
    assert (record["runs_per_case"], record["call_budget"]) == (3, 75)
    assert (record["passed_attempts"], record["verdict"]) == (75, "PASS")
    for field in BINDING_FIELDS:
        assert field in record, field


def test_a_pass_binds_its_own_identity_and_nothing_else(tmp_path: Path) -> None:
    record = _as_astra(_record(tmp_path))
    assert certificate_binds(record, **_current(ASTRA))
    assert completeness_certificate_standing(record) == "CURRENT"
    other = _current(ModelIdentity(provider="openai", model="gpt-6-other"))
    assert not certificate_binds(record, **other)


@pytest.mark.parametrize("field", BINDING_FIELDS)
def test_binding_fails_closed_on_any_changed_or_missing_field(tmp_path: Path, field: str) -> None:
    record = _as_astra(_record(tmp_path))
    current = _current(ASTRA)
    assert not certificate_binds(dict(record, **{field: "something else"}), **current)
    assert not certificate_binds({k: v for k, v in record.items() if k != field}, **current)


def test_standing_for_failed_superseded_and_foreign_records(tmp_path: Path) -> None:
    passed = _as_astra(_record(tmp_path))
    assert completeness_certificate_standing(dict(passed, verdict="NOT CERTIFIED")) == (
        "NOT_CERTIFIED"
    )
    for prior in PRIOR_EXAMS:
        on_prior = dict(passed, exam_version=prior.exam_version, exam_sha256=prior.exam_sha256)
        assert completeness_certificate_standing(on_prior) == "SUPERSEDED"
    assert completeness_certificate_standing(dict(passed, exam_sha256="f" * 64)) == "NOT_BINDING"
    foreign = dict(passed, record_format="ie3-graph-certification.v3")
    assert completeness_certificate_standing(foreign) == "NOT_BINDING"


def test_astras_ie3_graph_certificate_never_stands_for_this_task() -> None:
    path = EVIDENCE_ROOT / "openai/gpt-6-astra/intent_graph_synthesis_exam_v6/certification.json"
    record = json.loads(path.read_text())
    assert record["verdict"] == "PASS"
    assert not certificate_binds(record, **_current(ASTRA))
    assert completeness_certificate_standing(record) == "NOT_BINDING"


def test_the_evidence_namespace_is_new() -> None:
    from tests.certification._intent_graph_exam import (
        GRAPH_EVIDENCE_NAMESPACE,
        HISTORICAL_GRAPH_NAMESPACES,
    )

    assert COMPLETENESS_EVIDENCE_NAMESPACE == "semantic_completeness_verification_exam_v4"
    assert COMPLETENESS_EVIDENCE_NAMESPACE not in (
        HISTORICAL_EXAM_V3_NAMESPACE,
        v3.HISTORICAL_EXAM_V2_NAMESPACE,
        v2.COMPLETENESS_EVIDENCE_NAMESPACE,
        GRAPH_EVIDENCE_NAMESPACE,
        *HISTORICAL_GRAPH_NAMESPACES,
    )


# --- evidence integrity -----------------------------------------------------------------------


def _tamper(record: dict[str, Any], index: int, **changes: Any) -> dict[str, Any]:
    forged = copy.deepcopy(record)
    forged["attempts"][index].update(changes)
    return forged


def test_integrity_catches_every_kind_of_rewritten_evidence(tmp_path: Path) -> None:
    record = _record(tmp_path)
    assert completeness_evidence_problems(record) == ()
    kc = next(i for i, a in enumerate(record["attempts"]) if a["case"] == "C21")
    only_refusal = copy.deepcopy(record["attempts"][kc]["parsed_report"])
    only_refusal["verdicts"][0]["missing"] = ["a claim made later is refused"]
    forgeries = {
        "a report naming only the designed gap under a PASS": _tamper(
            record, kc, parsed_report=only_refusal, raw_output=only_refusal
        ),
        "report removed under a PASS": _tamper(record, kc, parsed_report=None),
        "request rewritten": _tamper(record, kc, request_json="{}"),
        "another model's answer": _tamper(record, kc, model="gpt-6-other"),
        "verdict flipped": _tamper(record, 0, verdict="FAIL"),
        "attempt dropped": dict(record, attempts=record["attempts"][:-1]),
        "count inflated": dict(record, passed_attempts=76),
        "earned on another exam": dict(record, exam_sha256="f" * 64),
    }
    for name, forged in forgeries.items():
        assert completeness_evidence_problems(forged) != (), name


def test_every_committed_record_in_the_v4_namespace_is_internally_consistent() -> None:
    for path in sorted(
        EVIDENCE_ROOT.glob(f"*/*/{COMPLETENESS_EVIDENCE_NAMESPACE}/certification.json")
    ):
        assert completeness_evidence_problems(json.loads(path.read_text())) == (), path


# --- exams v2 and v3's live records are frozen history -------------------------------------------


def test_the_v2_and_v3_live_records_are_byte_identical_to_their_evidence_commits() -> None:
    assert hashlib.sha256(V2_RECORD.read_bytes()).hexdigest() == v3.HISTORICAL_V2_RECORD_SHA256
    assert hashlib.sha256(V3_RECORD.read_bytes()).hexdigest() == HISTORICAL_V3_RECORD_SHA256


def test_the_v2_record_stands_as_recorded() -> None:
    record = json.loads(V2_RECORD.read_text())
    assert (record["verdict"], record["passed_attempts"], record["recorded_attempts"]) == (
        "NOT CERTIFIED",
        66,
        75,
    )
    assert v2.completeness_evidence_problems(record) == ()
    assert completeness_certificate_standing(record) == "NOT_CERTIFIED"


def test_the_v3_record_stands_as_recorded_and_is_never_rescored_by_v4() -> None:
    record = json.loads(V3_RECORD.read_text())
    assert (record["exam_version"], record["exam_sha256"]) == (
        "ie2-semantic-completeness-exam-v3",
        v3.EXPECTED_COMPLETENESS_EXAM_SHA256,
    )
    assert (record["verdict"], record["passed_attempts"], record["recorded_attempts"]) == (
        "NOT CERTIFIED",
        74,
        75,
    )
    failed = [
        (a["case"], a["attempt"], a["failures"])
        for a in record["attempts"]
        if a["verdict"] != "PASS"
    ]
    assert [(c, n) for c, n, _ in failed] == [("C05", 1)]
    (c05,) = [a for a in record["attempts"] if (a["case"], a["attempt"]) == ("C05", 1)]
    assert (
        "The permission to renew a loan is granted to a member."
        in (c05["parsed_report"]["verdicts"][0]["missing"])
    )
    assert v3.completeness_evidence_problems(record) == (), "consistent under its own exam"
    assert v3.completeness_certificate_standing(record) == "NOT_CERTIFIED"
    assert completeness_certificate_standing(record) == "NOT_CERTIFIED"
    assert completeness_evidence_problems(record) == (
        "earned on a different exam; it cannot be re-scored against this one",
    )


# --- the seal ---------------------------------------------------------------------------------


def test_the_seal_is_absent_until_written_and_then_exactly_the_exam(tmp_path: Path) -> None:
    seal = tmp_path / "seal.json"
    assert completeness_seal_problems(seal) != ()
    write_completeness_seal(seal, harness_sha="a" * 40)
    assert completeness_seal_problems(seal) == ()
    document = json.loads(seal.read_text())
    assert document["exam_version"] == COMPLETENESS_EXAM_VERSION
    assert document["manifest"] == completeness_exam_manifest()
    document["manifest"]["cases"][20]["inventory"][0]["assertions"].pop()
    seal.write_text(json.dumps(document))
    assert completeness_seal_problems(seal) != ()


def test_exams_v2_and_v3s_seals_still_match_their_exams() -> None:
    assert v2.completeness_seal_problems() == ()
    assert v3.completeness_seal_problems() == ()
