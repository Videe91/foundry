"""Adapters for IE2 Call 3, offline: the accounting reasoner's proposal and the verifier.

* ``propose_accounted`` exposes exactly what the accounting adapter already parsed (the model's
  propositions and which judgment disposes of which) without changing ``propose``, the prompt or
  the output contract.
* ``ModelRuntimeCompletenessVerifier`` runs the verifier through the provider-neutral Model
  Runtime under its own certified task and policy; it names no provider or model.

The K-CREDIT regression replays the exact recorded v6 model payload of that section through the
real adapter (a stand-in transport, no network).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics import xai_reasoner as mod
from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_SYSTEM_INSTRUCTION,
    COMPLETENESS_SYSTEM_INSTRUCTION_SHA256,
    COMPLETENESS_V1_CONTRACT,
    ModelRuntimeCompletenessVerifier,
)
from foundry.adapters.semantics.xai_reasoner import (
    XAIContrastiveSemanticReasoner,
    XAICorrectionSetSemanticReasoner,
)
from foundry.application.semantic_completeness import build_completeness_request
from foundry.domain.common import SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    CompletenessReport,
    PropositionVerdict,
)
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS
from foundry.experiments.locus_validation_v6.runner import RunRecord
from foundry.model_runtime.domain import (
    CertifiedContract,
    ModelCapability,
    ModelDescriptor,
    ModelIdentity,
    ModelTask,
    ModelTier,
    ModelUsage,
)
from foundry.model_runtime.fake import FakeModelProvider, ScriptedResponse
from foundry.model_runtime.registry import build_registry
from foundry.model_runtime.runtime import ModelRuntime
from foundry.ports.semantic_reasoner import ReasoningRequest
from tests.unit.test_correction_set_policy import _Transport

V6 = Path("docs/superpowers/experiments/2026-09-30-locus-validation-v6")
AT = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
CLAIM_KINDS = frozenset(
    {
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
        JudgmentKind.CONFLICTS_WITH,
    }
)


@pytest.fixture(scope="module")
def recorded() -> dict[str, Any]:
    """The frozen v6 dense T1 Call 2, restricted to the K-CREDIT-CLAIM section."""
    run = RunRecord.model_validate(json.loads((V6 / "run.json").read_text()))
    (dense,) = [lg for lg in run.ledgers if lg.ledger == "dense"]
    call = next(c for c in dense.calls if c.t == 1 and "ASSERT_CLAIM" in c.allowed_kinds)
    ev = DOCUMENTS["K-CREDIT-CLAIM-T1"].evidence_id
    payload = call.model_payload or {}
    props = [p for p in payload["propositions"] if all(s.startswith(ev) for s in p["sentence_ids"])]
    pids = {p["proposition_id"] for p in props}
    drafts = [d for d in payload["drafts"] if d.get("proposition_id") in pids]
    silent = [n for n in payload["non_operative"] if n["sentence_id"].startswith(ev)]
    state = dense.deltas[0].state_after
    (address,) = {d["address_id"] for d in drafts}
    return {
        "payload": {"propositions": props, "non_operative": silent, "drafts": drafts},
        "address": state.semantic.addresses[address],
        "state": state,
        "ev": ev,
    }


def _request(recorded: dict[str, Any]) -> ReasoningRequest:
    doc = DOCUMENTS["K-CREDIT-CLAIM-T1"]
    item = evidence_item(
        evidence_id=recorded["ev"],
        project_id="PROJ-LV6-DENSE",
        source_kind=SourceKind.HUMAN,
        source_ref="human://validation-author",
        content=doc.text,
        observed_at=AT,
        scope=("carshare",),
        artifact_ref=doc.artifact_ref,
    )
    return ReasoningRequest(
        project_id="PROJ-LV6-DENSE",
        evidence=(item,),
        known_addresses=(recorded["address"],),
        allowed_judgment_kinds=CLAIM_KINDS,
        accountable_evidence_ids=(recorded["ev"],),
    )


def _reasoner(cls: type, transport: _Transport) -> Any:
    ids = iter(range(1, 10_000))
    return cls(api_key="k", clock=lambda: AT, id_factory=lambda p: f"{p}-{next(ids)}")


def test_propose_accounted_exposes_the_models_own_accounting_unchanged(
    recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _Transport()
    monkeypatch.setattr(mod, "Client", transport.client())
    reply = json.dumps(recorded["payload"])
    transport.replies.extend([reply, reply])
    reasoner = _reasoner(XAICorrectionSetSemanticReasoner, transport)
    proposal = reasoner.propose_accounted(_request(recorded))
    plain = reasoner.propose(_request(recorded))
    assert [j.proposal for j in proposal.judgments] == [j.proposal for j in plain]
    statements = {p.proposition_id: p.statement for p in proposal.propositions}
    assert "later claim is refused" in statements["p13"]
    (deadline,) = [
        j for j in proposal.judgments if proposal.disposed_by.get(j.judgment_id) == "p13"
    ]
    assert deadline.proposal.predicate == "claim_deadline_after_reservation_start"  # type: ignore[union-attr]
    assert set(proposal.disposed_by) == {j.judgment_id for j in proposal.judgments}


def test_the_recorded_k_credit_proposal_is_reviewed_exactly_as_it_was_written(
    recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _Transport()
    monkeypatch.setattr(mod, "Client", transport.client())
    transport.replies.append(json.dumps(recorded["payload"]))
    reasoner = _reasoner(XAICorrectionSetSemanticReasoner, transport)
    proposal = reasoner.propose_accounted(_request(recorded))
    check = build_completeness_request(recorded["state"], _request(recorded), proposal)
    assert check is not None
    p13 = next(p for p in check.propositions if p.proposition_id == "p13")
    assert p13.disposition == "ASSERT"
    assert p13.source_sentences == (
        "The service credit for an unavailable vehicle must be claimed in the app within 48 "
        "hours after the reservation start.",
        "A claim made later is refused.",
    )
    assert [(c.predicate, c.value) for c in p13.claims] == [
        ("claim_deadline_after_reservation_start", "48 hours")
    ]


def test_a_policy_without_proposition_accounting_cannot_be_verified(
    monkeypatch: pytest.MonkeyPatch, recorded: dict[str, Any]
) -> None:
    transport = _Transport()
    monkeypatch.setattr(mod, "Client", transport.client())
    reasoner = _reasoner(XAIContrastiveSemanticReasoner, transport)
    with pytest.raises(TypeError, match="proposition accounting"):
        reasoner.propose_accounted(_request(recorded))


# ------------------------------------------------------------------ the runtime verifier


def _runtime(
    output: object, model: str = "verifier-model"
) -> tuple[ModelRuntime, FakeModelProvider]:
    provider = FakeModelProvider(
        provider_id="provider-v",
        responses=(
            ScriptedResponse(
                output=output,
                model=model,
                usage=ModelUsage(input_tokens=10, output_tokens=5, wall_clock_ms=7),
            ),
        ),
    )
    registry = build_registry(
        (
            ModelDescriptor(
                identity=ModelIdentity(provider="provider-v", model=model),
                tiers=frozenset({ModelTier.REASONER}),
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                ),
                certified_tasks=frozenset({ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION}),
                certified_contracts=frozenset(
                    {
                        CertifiedContract(
                            task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
                            contract=COMPLETENESS_V1_CONTRACT,
                        )
                    }
                ),
            ),
        )
    )
    return ModelRuntime(registry=registry, providers=(provider,)), provider


def _check(recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Any:
    transport = _Transport()
    monkeypatch.setattr(mod, "Client", transport.client())
    transport.replies.append(json.dumps(recorded["payload"]))
    reasoner = _reasoner(XAICorrectionSetSemanticReasoner, transport)
    proposal = reasoner.propose_accounted(_request(recorded))
    return build_completeness_request(recorded["state"], _request(recorded), proposal)


def test_the_runtime_verifier_is_its_own_certified_task_and_names_no_model(
    recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    check = _check(recorded, monkeypatch)
    report = CompletenessReport(
        verdicts=tuple(
            PropositionVerdict(
                proposition_id=p.proposition_id,
                verdict="COMPLETE",
                claim_refs=tuple(c.ref for c in p.claims),
            )
            for p in check.propositions
        )
    )
    runtime, provider = _runtime(report.model_dump(mode="json"))
    verifier = ModelRuntimeCompletenessVerifier(runtime=runtime, run_id="RUN-V")
    result = verifier.verify(check)
    (call,) = provider.requests
    assert call.request.task is ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION
    assert call.request.tier is ModelTier.REASONER
    assert call.request.policy_version == SEMANTIC_COMPLETENESS_POLICY_VERSION
    assert call.request.messages[0].content == COMPLETENESS_SYSTEM_INSTRUCTION
    assert json.loads(call.request.messages[1].content) == check.model_dump(mode="json")
    assert call.output_type is CompletenessReport
    assert call.request.contract == COMPLETENESS_V1_CONTRACT
    assert result.report == report
    assert (result.verifier.provider, result.verifier.model) == ("provider-v", "verifier-model")
    assert result.verifier.policy_version == SEMANTIC_COMPLETENESS_POLICY_VERSION
    assert (result.input_tokens, result.output_tokens, result.wall_clock_ms) == (10, 5, 7)
    digest = hashlib.sha256(COMPLETENESS_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == COMPLETENESS_SYSTEM_INSTRUCTION_SHA256
    source = Path("src/foundry/adapters/semantics/completeness_verifier.py").read_text()
    assert "grok" not in source and "gpt" not in source and "claude" not in source


def test_an_answer_that_is_not_a_report_is_recorded_as_no_report(
    recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    check = _check(recorded, monkeypatch)
    runtime, _ = _runtime({"verdicts": [{"proposition_id": "p13", "verdict": "PROBABLY"}]})
    result = ModelRuntimeCompletenessVerifier(runtime=runtime, run_id="RUN-V").verify(check)
    assert result.report is None
    assert (result.verifier.provider, result.verifier.model) == ("provider-v", "verifier-model")


def test_the_instruction_asks_for_meaning_coverage_and_forbids_rewriting() -> None:
    text = COMPLETENESS_SYSTEM_INSTRUCTION
    for phrase in (
        "every operative",
        "union",
        "paraphrase",
        "INCOMPLETE",
        "OVERREACH",
        "CONTRADICTORY",
        "never propose",
        "consequence",
    ):
        assert phrase in text, phrase
