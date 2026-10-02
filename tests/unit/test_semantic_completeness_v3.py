"""Semantic completeness policy v3 (Intent Engine runtime reset): one verdict per proposition.

The verifier answers one question per proposition -- is it fully preserved in its claims? --
with COMPLETE or NOT_COMPLETE and an optional note. Deterministic code checks only the shape:
schema, every proposition judged exactly once, known ids, the verifier's independence and the
policy's format. It never reads the note. v1 and v2 records stay readable and replayable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_V1_CONTRACT,
    COMPLETENESS_V2_CONTRACT,
    COMPLETENESS_V3_CONTRACT,
    VERDICT_COMPLETENESS_SYSTEM_INSTRUCTION,
    VERDICT_COMPLETENESS_SYSTEM_INSTRUCTION_SHA256,
    ModelRuntimeVerdictCompletenessVerifier,
)
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
    VERDICT_REPORT_FORMAT,
    CompletenessRecord,
    PropositionCheck,
    VerdictCompletenessReport,
    VerifierIdentity,
    completeness_outcome,
    completeness_request_sha256,
    not_complete_proposition_ids,
    report_findings,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.model_runtime.domain import (
    CertifiedContract,
    ModelCapability,
    ModelDescriptor,
    ModelIdentity,
    ModelTask,
    ModelTier,
    ModelUsage,
    output_schema_sha256,
)
from foundry.model_runtime.errors import ModelUnavailableError
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.registry import build_registry
from foundry.model_runtime.runtime import ModelRuntime
from tests.unit.test_semantic_completeness_v2_domain import REQUEST

WRITER = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v6")
V3 = VerifierIdentity(
    provider="verifier", model="m", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION_V3
)
SCV = ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION


def _report(*checks: tuple[str, str, str | None]) -> VerdictCompletenessReport:
    return VerdictCompletenessReport(
        report_format=VERDICT_REPORT_FORMAT,
        verdicts=tuple(PropositionCheck(proposition_id=p, verdict=v, note=n) for p, v, n in checks),  # type: ignore[arg-type]
    )


# --- the contract ---------------------------------------------------------------------------


def test_v3_is_a_new_policy_with_a_two_valued_verdict_and_an_optional_note() -> None:
    assert SEMANTIC_COMPLETENESS_POLICY_VERSION_V3 == "ie2-semantic-completeness-v3"
    assert VERDICT_REPORT_FORMAT == "ie2-semantic-completeness-report.v3"
    PropositionCheck(proposition_id="p1", verdict="COMPLETE")
    PropositionCheck(proposition_id="p1", verdict="NOT_COMPLETE", note=None)
    PropositionCheck(proposition_id="p1", verdict="NOT_COMPLETE", note="anything at all")
    for bad in ("INCOMPLETE", "OVERREACH", "CONTRADICTORY", "MAYBE"):
        with pytest.raises(ValidationError):
            PropositionCheck(proposition_id="p1", verdict=bad)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        PropositionCheck(proposition_id="p1", verdict="COMPLETE", findings=())  # type: ignore[call-arg]


def test_the_shape_checks_are_ids_and_cardinality_only() -> None:
    good = _report(("p13", "NOT_COMPLETE", "x"), ("p2", "COMPLETE", None))
    assert report_findings(REQUEST, good) == ()
    assert report_findings(REQUEST, _report(("p13", "COMPLETE", None))) == ("MISSING_VERDICT: p2",)
    assert "UNKNOWN_PROPOSITION: p9" in report_findings(
        REQUEST,
        _report(("p13", "COMPLETE", None), ("p2", "COMPLETE", None), ("p9", "COMPLETE", None)),
    )
    assert "DUPLICATE_VERDICT: p2" in report_findings(
        REQUEST,
        _report(("p13", "COMPLETE", None), ("p2", "COMPLETE", None), ("p2", "NOT_COMPLETE", None)),
    )


def test_the_outcome_never_reads_the_note() -> None:
    for note in (None, "", "late refusal missing", "the consequence was not retained",
                 "something about refusal", "purple elephants"):  # fmt: skip
        failing = _report(("p13", "NOT_COMPLETE", note), ("p2", "COMPLETE", note))
        assert completeness_outcome(REQUEST, failing, verifier=V3, writer=WRITER) == (
            "FAIL",
            ("INCOMPLETE_PROPOSITION_MEANING",),
        )
        assert not_complete_proposition_ids(failing) == ("p13",)
        passing = _report(("p13", "COMPLETE", note), ("p2", "COMPLETE", note))
        assert completeness_outcome(REQUEST, passing, verifier=V3, writer=WRITER) == ("PASS", ())


def test_invalid_output_wrong_format_or_a_dependent_verifier_fails_safe() -> None:
    complete = _report(("p13", "COMPLETE", None), ("p2", "COMPLETE", None))
    same = VerifierIdentity(provider="xai", model="grok-4.6", policy_version=V3.policy_version)
    v2 = V3.model_copy(update={"policy_version": "ie2-semantic-completeness-v2"})
    assert completeness_outcome(REQUEST, None, verifier=V3, writer=WRITER)[1] == (
        "VERIFIER_OUTPUT_INVALID",
    )
    assert completeness_outcome(REQUEST, complete, verifier=v2, writer=WRITER)[1] == (
        "VERIFIER_OUTPUT_INVALID",
    )
    assert completeness_outcome(REQUEST, complete, verifier=same, writer=WRITER)[1] == (
        "VERIFIER_NOT_INDEPENDENT",
    )
    partial = _report(("p13", "COMPLETE", None))
    assert completeness_outcome(REQUEST, partial, verifier=V3, writer=WRITER)[1] == (
        "VERIFIER_OUTPUT_INVALID",
    )


def test_a_v3_record_round_trips_and_formats_cannot_be_mixed() -> None:
    report = _report(("p13", "NOT_COMPLETE", "note"), ("p2", "COMPLETE", None))

    def record(r: object, verifier: VerifierIdentity) -> CompletenessRecord:
        return CompletenessRecord(
            verification_id="VER-1",
            project_id="P",
            subject_invocation_id="INV-1",
            writer=WRITER,
            verifier=verifier,
            verifier_invocation_id="V-1",
            request_sha256=completeness_request_sha256(REQUEST),
            request=REQUEST,
            proposed_judgment_ids=("JDG-1",),
            report=r,  # type: ignore[arg-type]
            outcome="FAIL",
            failure_codes=("INCOMPLETE_PROPOSITION_MEANING",),
            held_proposition_ids=("p13",),
            gap_ids=("GAP-1",),
        )

    again = CompletenessRecord.model_validate_json(record(report, V3).model_dump_json())
    assert isinstance(again.report, VerdictCompletenessReport) and again.held_proposition_ids == (
        "p13",
    )
    with pytest.raises(ValidationError):
        record(report, V3.model_copy(update={"policy_version": "ie2-semantic-completeness-v1"}))


# --- the adapter ----------------------------------------------------------------------------


def _runtime(
    output: object, contracts: tuple[CertifiedContract, ...]
) -> tuple[ModelRuntime, FakeModelProvider]:
    provider = FakeModelProvider(
        provider_id="provider-v",
        responses=(
            ScriptedResponse(
                output=output,
                model="verifier-model",
                usage=ModelUsage(input_tokens=10, output_tokens=5, wall_clock_ms=7),
            ),
        ),
    )
    registry = build_registry(
        (
            ModelDescriptor(
                identity=ModelIdentity(provider="provider-v", model="verifier-model"),
                tiers=frozenset({ModelTier.REASONER}),
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                ),
                certified_tasks=frozenset({SCV}),
                certified_contracts=frozenset(contracts),
            ),
        )
    )
    return ModelRuntime(registry=registry, providers=(provider,)), provider


def test_the_v3_adapter_binds_its_exact_contract_and_names_no_provider() -> None:
    report = _report(("p13", "NOT_COMPLETE", "x"), ("p2", "COMPLETE", None))
    runtime, provider = _runtime(
        report.model_dump(mode="json"),
        (CertifiedContract(task=SCV, contract=COMPLETENESS_V3_CONTRACT),),
    )
    result = ModelRuntimeVerdictCompletenessVerifier(runtime=runtime, run_id="R").verify(REQUEST)
    (call,) = provider.requests
    assert call.request.contract == COMPLETENESS_V3_CONTRACT
    assert (call.request.policy_id, call.request.policy_version) == (
        COMPLETENESS_POLICY_ID,
        SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
    )
    assert call.request.messages[0].content == VERDICT_COMPLETENESS_SYSTEM_INSTRUCTION
    assert json.loads(call.request.messages[1].content) == REQUEST.model_dump(mode="json")
    assert call.output_type is VerdictCompletenessReport and result.report == report
    assert result.verifier.policy_version == SEMANTIC_COMPLETENESS_POLICY_VERSION_V3
    assert COMPLETENESS_V3_CONTRACT.output_schema_sha256 == output_schema_sha256(
        VerdictCompletenessReport
    )
    digest = hashlib.sha256(VERDICT_COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert (
        digest
        == VERDICT_COMPLETENESS_SYSTEM_INSTRUCTION_SHA256
        == COMPLETENESS_V3_CONTRACT.instruction_sha256
    )
    assert len({COMPLETENESS_V1_CONTRACT, COMPLETENESS_V2_CONTRACT, COMPLETENESS_V3_CONTRACT}) == 3
    source = Path("src/foundry/adapters/semantics/completeness_verifier.py").read_text().lower()
    for name in ("grok", "gpt", "claude", "astra", "openai", "anthropic", "xai"):
        assert name not in source, name


def test_a_model_registered_for_another_verifier_contract_is_never_asked() -> None:
    for other in (COMPLETENESS_V1_CONTRACT, COMPLETENESS_V2_CONTRACT):
        runtime, provider = _runtime({}, (CertifiedContract(task=SCV, contract=other),))
        with pytest.raises(ModelUnavailableError):
            ModelRuntimeVerdictCompletenessVerifier(runtime=runtime, run_id="R").verify(REQUEST)
        assert provider.calls == 0


def test_an_answer_that_is_not_a_v3_report_is_recorded_as_no_report() -> None:
    runtime, _ = _runtime(
        {"verdicts": [{"proposition_id": "p13", "verdict": "INCOMPLETE"}]},
        (CertifiedContract(task=SCV, contract=COMPLETENESS_V3_CONTRACT),),
    )
    result = ModelRuntimeVerdictCompletenessVerifier(runtime=runtime, run_id="R").verify(REQUEST)
    assert result.report is None


def test_the_v3_instruction_asks_one_question_and_says_the_note_is_never_read() -> None:
    text = " ".join(VERDICT_COMPLETENESS_SYSTEM_INSTRUCTION.split())
    for phrase in ("COMPLETE", "NOT_COMPLETE", "union", "paraphrase", "never propose",
                   "note", "never read", VERDICT_REPORT_FORMAT):  # fmt: skip
        assert phrase in text, phrase
