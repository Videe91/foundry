"""Exam v2's certification harness, offline: every attempt through the production verifier.

Each attempt runs the real ``ModelRuntimeCompletenessVerifier`` through the real
``ModelRuntime`` against a scripted provider (no network). The proofs: a perfect verifier is
certified on all ``case_count * 3`` attempts; always-COMPLETE, always-INCOMPLETE, correct labels
with empty, echoed or wrong findings, an unparseable answer, a verifier failing faithful
decomposition, and one failing a single repetition are not. The leakage gate runs over every
request the provider was actually sent. The regression case is checked against the frozen v6
evidence, replayed through the real accounting adapter.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import COMPLETENESS_SYSTEM_INSTRUCTION
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    PropositionVerdict,
)
from foundry.model_runtime.domain import ModelIdentity, ModelRequest, ModelTask, ModelUsage
from foundry.model_runtime.errors import ModelProtocolError
from foundry.model_runtime.ports import ProviderExecutionResult
from tests.certification._certification_run import (
    Contestant,
    HarnessLimitReached,
    ProtocolTaskFailure,
    TransportFailure,
)
from tests.certification._completeness_exam import (
    CASES,
    COMPLETENESS_CALL_BUDGET,
    COMPLETENESS_RUNS_PER_CASE,
    COMPLETENESS_TIMEOUT_SECONDS,
    CompletenessCase,
    attempt_evidence,
    case_by_id,
    completeness_verdict,
    render_request,
    run_completeness_attempt,
    score_completeness_attempt,
)
from tests.certification.test_semantic_completeness_exam_v2 import PASSING_FINDINGS

SCRIPTED = ModelIdentity(provider="scripted", model="verifier-model")
_REGION = {"INCOMPLETE": "missing", "OVERREACH": "unsupported", "CONTRADICTORY": "contradictory"}

Answer = Callable[[CompletenessRequest], Any]


class ScriptedVerifierProvider:
    """Answers from what it was actually shown; records every request. No I/O."""

    provider_id = "scripted"

    def __init__(self, answer: Answer) -> None:
        self._answer = answer
        self.requests: list[ModelRequest] = []

    def execute(self, *, model: ModelIdentity, request: ModelRequest, output_type: type) -> Any:
        self.requests.append(request)
        shown = CompletenessRequest.model_validate_json(request.messages[1].content)
        output = self._answer(shown)
        if isinstance(output, Exception):
            raise output
        return ProviderExecutionResult[output_type].model_construct(  # type: ignore[valid-type]
            identity=model,
            output=output,
            usage=ModelUsage(input_tokens=900, output_tokens=120, wall_clock_ms=40),
            finish_reason="completed",
        )


def _contestant(namespace: str = "unused") -> Contestant:
    return Contestant(
        identity=SCRIPTED,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        timeout_seconds=COMPLETENESS_TIMEOUT_SECONDS,
        task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
        evidence_namespace=namespace,
        wire_schema=OpenAIModelProvider.wire_schema,
        wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    )


def _case_of(request: CompletenessRequest) -> CompletenessCase:
    (case,) = [c for c in CASES if c.request == request]
    return case


def _report(
    request: CompletenessRequest,
    verdict_of: Callable[[str, str], str],
    finding_of: Callable[[CompletenessCase, str], tuple[str, ...]],
) -> CompletenessReport:
    case = _case_of(request)
    sealed = {e.proposition_id: e.verdict for e in case.expected}
    out = []
    for p in request.propositions:
        verdict = verdict_of(p.proposition_id, sealed[p.proposition_id])
        regions = (
            {} if verdict == "COMPLETE" else {_REGION[verdict]: finding_of(case, p.proposition_id)}
        )
        out.append(
            PropositionVerdict(
                proposition_id=p.proposition_id,
                verdict=verdict,  # type: ignore[arg-type]
                claim_refs=tuple(c.ref for c in p.claims),
                **regions,
            )
        )
    return CompletenessReport(verdicts=tuple(out))


def _true_finding(case: CompletenessCase, pid: str) -> tuple[str, ...]:
    return PASSING_FINDINGS[case.case_id][pid]


def perfect(request: CompletenessRequest) -> Any:
    return _report(request, lambda _, v: v, _true_finding).model_dump(mode="json")


def sit(answer: Answer) -> tuple[list[dict[str, Any]], ScriptedVerifierProvider]:
    """Every case, every repetition, each attempt with a fresh runtime and verifier."""
    provider = ScriptedVerifierProvider(answer)
    contestant = _contestant()
    attempts: list[dict[str, Any]] = []
    for case in CASES:
        for attempt in range(1, COMPLETENESS_RUNS_PER_CASE + 1):
            observation = run_completeness_attempt(contestant, case, attempt, provider=provider)
            failures = score_completeness_attempt(observation, case, candidate=SCRIPTED)
            attempts.append(
                attempt_evidence(
                    observation, verdict="FAIL" if failures else "PASS", failures=failures
                )
            )
    return attempts, provider


# --- the budget and the repetition rule --------------------------------------------------------


def test_the_call_budget_is_case_count_times_three() -> None:
    assert COMPLETENESS_RUNS_PER_CASE == 3
    assert len(CASES) == 25
    assert COMPLETENESS_CALL_BUDGET == len(CASES) * COMPLETENESS_RUNS_PER_CASE == 75


def test_a_perfect_verifier_is_certified_on_every_attempt_in_exactly_the_budget() -> None:
    attempts, provider = sit(perfect)
    assert len(provider.requests) == COMPLETENESS_CALL_BUDGET
    assert [a["failures"] for a in attempts if a["verdict"] != "PASS"] == []
    assert completeness_verdict(attempts) == "PASS"


def test_fewer_attempts_than_the_rule_requires_are_never_a_pass() -> None:
    attempts, _ = sit(perfect)
    first_runs = [a for a in attempts if a["attempt"] == 1]
    assert completeness_verdict(first_runs) == "NOT CERTIFIED"
    assert completeness_verdict(attempts[:-1]) == "NOT CERTIFIED"
    assert completeness_verdict([]) == "NOT CERTIFIED"


def test_one_failed_repetition_is_not_certified() -> None:
    calls = {"n": 0}

    def flaky(request: CompletenessRequest) -> Any:
        calls["n"] += 1
        if calls["n"] == 63:  # C21 (the regression) third attempt
            return _report(
                request, lambda _, v: v, lambda c, p: ("the 48-hour deadline is missing",)
            ).model_dump(mode="json")
        return perfect(request)

    attempts, _ = sit(flaky)
    failed = [(a["case"], a["attempt"]) for a in attempts if a["verdict"] != "PASS"]
    assert failed == [("C21", 3)]
    assert completeness_verdict(attempts) == "NOT CERTIFIED"


# --- scripted bad verifiers ------------------------------------------------------------------


def _bad(answer: Answer) -> set[str]:
    attempts, _ = sit(answer)
    assert completeness_verdict(attempts) == "NOT CERTIFIED"
    return {a["case"] for a in attempts if a["verdict"] != "PASS"}


def test_always_complete_is_not_certified() -> None:
    failed = _bad(lambda r: _report(r, lambda *_: "COMPLETE", _true_finding).model_dump())
    assert {"C05", "C06", "C10", "C11", "C21"} <= failed


def test_always_incomplete_is_not_certified() -> None:
    failed = _bad(
        lambda r: _report(
            r, lambda *_: "INCOMPLETE", lambda c, p: ("a later claim is refused",)
        ).model_dump()
    )
    assert {"C01", "C03", "C04", "C24", "C25"} <= failed


def test_correct_labels_with_empty_findings_are_not_certified() -> None:
    failed = _bad(lambda r: _report(r, lambda _, v: v, lambda c, p: ("",)).model_dump())
    assert failed == {c.case_id for c in CASES if any(e.verdict != "COMPLETE" for e in c.expected)}


def test_correct_labels_with_the_proposition_echoed_as_the_finding_are_not_certified() -> None:
    def echo(case: CompletenessCase, pid: str) -> tuple[str, ...]:
        (p,) = [p for p in case.request.propositions if p.proposition_id == pid]
        return (p.statement,)

    failed = _bad(lambda r: _report(r, lambda _, v: v, echo).model_dump())
    assert "C21" in failed and "C05" in failed


def test_correct_labels_with_wrong_findings_are_not_certified() -> None:
    order = [cid for cid in PASSING_FINDINGS]

    def someone_elses(case: CompletenessCase, pid: str) -> tuple[str, ...]:
        other = order[(order.index(case.case_id) + 1) % len(order)]
        return next(iter(PASSING_FINDINGS[other].values()))

    failed = _bad(lambda r: _report(r, lambda _, v: v, someone_elses).model_dump())
    assert failed == set(order)


def test_an_unparseable_verifier_is_not_certified() -> None:
    attempts, _ = sit(lambda r: {"verdicts": "all fine"})
    assert completeness_verdict(attempts) == "NOT CERTIFIED"
    assert all(a["verdict"] == "FAIL" and a["parsed_report"] is None for a in attempts)
    assert all(a["raw_output"] == {"verdicts": "all fine"} for a in attempts)


def test_a_verifier_failing_faithful_decomposition_is_not_certified() -> None:
    def splits(r: CompletenessRequest) -> Any:
        many = {p.proposition_id for p in r.propositions if len(p.claims) > 1}
        return _report(
            r,
            lambda pid, v: "INCOMPLETE" if pid in many and v == "COMPLETE" else v,
            lambda c, p: PASSING_FINDINGS.get(c.case_id, {}).get(p, ("the second claim",)),
        ).model_dump()

    assert {"C03", "C04", "C22", "C24", "C25"} <= _bad(splits)


# --- what the model saw -----------------------------------------------------------------------

_VERDICT_WORDS = ("complete", "incomplete", "overreach", "contradictory", "contradiction")
_HINT_WORDS = (
    "k credit",
    "kcredit",
    "regression",
    "expected",
    "verdict",
    "category",
    "difficulty",
    "hint",
    "exam",
    "marker",
    "missing",
    "unsupported",
    "sealed",
)


def test_no_request_the_provider_was_sent_leaks_a_verdict_label_or_hint() -> None:
    from tests.certification._completeness_exam import normalise

    _, provider = sit(perfect)
    assert len(provider.requests) == COMPLETENESS_CALL_BUDGET
    labels = {normalise(c.category) for c in CASES} | {
        normalise(e.finding) for c in CASES for e in c.expected if e.finding
    }
    ids = {c.case_id.lower() for c in CASES}
    for sent in provider.requests:
        system, user = sent.messages
        assert system.content == COMPLETENESS_SYSTEM_INSTRUCTION
        text = f" {normalise(user.content)} "
        for word in (*_VERDICT_WORDS, *_HINT_WORDS, *labels, *ids):
            assert f" {word} " not in text, (word, user.content[:120])


def test_every_attempt_sends_exactly_the_sealed_request_through_the_production_verifier() -> None:
    attempts, provider = sit(perfect)
    rendered = [render_request(c.request) for c in CASES for _ in range(COMPLETENESS_RUNS_PER_CASE)]
    assert [r.messages[1].content for r in provider.requests] == rendered
    assert [a["request_json"] for a in attempts] == rendered
    for sent in provider.requests:
        assert sent.task is ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION
        assert sent.policy_version == "ie2-semantic-completeness-v1"
    ids = [r.trace.run_id for r in provider.requests]
    assert len(set(ids)) == len(ids), "every attempt is a fresh, independent run"


def test_the_request_ids_are_neutral_sequence_numbers() -> None:
    assert {c.request.project_id for c in CASES} == {"PROJ-A"}
    assert [c.request.subject_invocation_id for c in CASES] == [
        f"INV-{n:04d}" for n in range(1, len(CASES) + 1)
    ]


# --- evidence recorded per attempt ------------------------------------------------------------


def test_every_attempt_records_the_raw_response_and_the_parsed_report() -> None:
    attempts, _ = sit(perfect)
    for a in attempts:
        assert a["raw_output"] == perfect(
            CompletenessRequest.model_validate_json(a["request_json"])
        )
        assert CompletenessReport.model_validate(a["parsed_report"]).verdicts
        assert (a["provider"], a["model"], a["task"]) == (
            "scripted",
            "verifier-model",
            "SEMANTIC_COMPLETENESS_VERIFICATION",
        )
        assert (a["input_tokens"], a["output_tokens"], a["finish_reason"]) == (
            900,
            120,
            "completed",
        )
        assert a["request_constraints"] == {
            "max_cost_usd": None,
            "max_output_tokens": None,
            "timeout_seconds": None,
        }


def test_an_answer_from_another_model_fails_the_global_gates() -> None:
    other = ModelIdentity(provider="scripted", model="other-model")
    case = case_by_id("C01")
    observation = run_completeness_attempt(
        _contestant(), case, 1, provider=ScriptedVerifierProvider(perfect)
    )
    assert score_completeness_attempt(observation, case, candidate=SCRIPTED) == ()
    assert score_completeness_attempt(observation, case, candidate=other) != ()


# --- execution failures are classified, never scored -----------------------------------------


def test_transport_failure_is_incomplete_not_a_verdict() -> None:
    provider = ScriptedVerifierProvider(lambda r: RuntimeError("connection reset"))
    with pytest.raises(TransportFailure):
        run_completeness_attempt(_contestant(), case_by_id("C01"), 1, provider=provider)


def test_a_length_stop_is_a_harness_limit_and_a_contract_break_is_a_protocol_failure() -> None:
    truncated = ScriptedVerifierProvider(
        lambda r: ModelProtocolError("response incomplete: max_output_tokens reached")
    )
    with pytest.raises(HarnessLimitReached):
        run_completeness_attempt(_contestant(), case_by_id("C01"), 1, provider=truncated)
    broken = ScriptedVerifierProvider(lambda r: ModelProtocolError("answer is not JSON"))
    with pytest.raises(ProtocolTaskFailure):
        run_completeness_attempt(_contestant(), case_by_id("C01"), 1, provider=broken)


# --- the regression is the frozen v6 evidence --------------------------------------------------

V6 = Path("docs/superpowers/experiments/2026-09-30-locus-validation-v6")
AT = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)


def test_the_regression_case_is_the_recorded_v6_proposition_and_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foundry.adapters.semantics import xai_reasoner as mod
    from foundry.adapters.semantics.xai_reasoner import XAICorrectionSetSemanticReasoner
    from foundry.application.semantic_completeness import build_completeness_request
    from foundry.domain.common import SourceKind
    from foundry.domain.evidence import evidence_item
    from foundry.domain.semantic_judgment import JudgmentKind
    from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS
    from foundry.experiments.locus_validation_v6.runner import RunRecord
    from foundry.ports.semantic_reasoner import ReasoningRequest
    from tests.unit.test_correction_set_policy import _Transport

    run = RunRecord.model_validate(json.loads((V6 / "run.json").read_text()))
    (dense,) = [lg for lg in run.ledgers if lg.ledger == "dense"]
    call = next(c for c in dense.calls if c.t == 1 and "ASSERT_CLAIM" in c.allowed_kinds)
    doc = DOCUMENTS["K-CREDIT-CLAIM-T1"]
    payload = call.model_payload or {}
    props = [
        p
        for p in payload["propositions"]
        if all(s.startswith(doc.evidence_id) for s in p["sentence_ids"])
    ]
    pids = {p["proposition_id"] for p in props}
    drafts = [d for d in payload["drafts"] if d.get("proposition_id") in pids]
    silent = [n for n in payload["non_operative"] if n["sentence_id"].startswith(doc.evidence_id)]
    state = dense.deltas[0].state_after
    (address,) = {d["address_id"] for d in drafts}
    transport = _Transport()
    monkeypatch.setattr(mod, "Client", transport.client())
    transport.replies.append(
        json.dumps({"propositions": props, "non_operative": silent, "drafts": drafts})
    )
    ids = iter(range(1, 10_000))
    reasoner = XAICorrectionSetSemanticReasoner(
        api_key="k", clock=lambda: AT, id_factory=lambda p: f"{p}-{next(ids)}"
    )
    item = evidence_item(
        evidence_id=doc.evidence_id,
        project_id="PROJ-LV6-DENSE",
        source_kind=SourceKind.HUMAN,
        source_ref="human://validation-author",
        content=doc.text,
        observed_at=AT,
        scope=("carshare",),
        artifact_ref=doc.artifact_ref,
    )
    request = ReasoningRequest(
        project_id="PROJ-LV6-DENSE",
        evidence=(item,),
        known_addresses=(state.semantic.addresses[address],),
        allowed_judgment_kinds=frozenset(
            {
                JudgmentKind.SUPPORTS_CLAIM,
                JudgmentKind.ASSERT_CLAIM,
                JudgmentKind.SUPERSEDE,
                JudgmentKind.CONFLICTS_WITH,
            }
        ),
        accountable_evidence_ids=(doc.evidence_id,),
    )
    recorded = build_completeness_request(state, request, reasoner.propose_accounted(request))
    assert recorded is not None
    (real,) = [p for p in recorded.propositions if p.proposition_id == "p13"]
    (sealed,) = case_by_id("C21").request.propositions

    def shape(p: Any) -> Any:
        return (
            p.statement,
            p.source_sentences,
            p.disposition,
            [(c.role, c.subject, c.predicate, c.value) for c in p.claims],
            p.retired,
        )

    assert shape(sealed) == shape(real)
    assert real.claims[0].subject == "Service credit for an unavailable reserved vehicle"


def test_every_other_case_is_held_out_from_the_validation_corpus() -> None:
    from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS

    corpus = " ".join(d.text for d in DOCUMENTS.values()).lower()
    for case in CASES:
        if case.case_id == "C21":
            continue
        for p in case.request.propositions:
            assert p.statement.lower() not in corpus, case.case_id
