"""Exam v4's certification harness, offline: every attempt through the production verifier.

Each attempt runs exam v2's unchanged runner (the real ``ModelRuntimeCompletenessVerifier``
through the real ``ModelRuntime``) against a scripted provider: no network, no model. The
proofs: a perfect verifier is certified on all ``case_count * 3`` attempts; always-COMPLETE,
always-INCOMPLETE, correct labels with bad findings, one that names only the designed gap of a
multi-gap proposition, one that misses an actor or a time anchor, one that calls pure overreach
INCOMPLETE and one that rejects a faithful decomposition are not. The leakage gate runs over
every request the provider was actually sent and over the inventory itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.semantics.completeness_verifier import COMPLETENESS_SYSTEM_INSTRUCTION
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    PropositionVerdict,
)
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from tests.certification._certification_run import Contestant, free_text_completeness_sitting
from tests.certification._completeness_exam import (
    COMPLETENESS_RUNS_PER_CASE,
    COMPLETENESS_TIMEOUT_SECONDS,
    attempt_evidence,
    normalise,
    render_request,
)
from tests.certification._completeness_exam_v3 import (
    InventoryCase,
    run_completeness_attempt,
)
from tests.certification._completeness_exam_v4 import (
    CASES,
    COMPLETENESS_CALL_BUDGET,
    COMPLETENESS_EVIDENCE_NAMESPACE,
    case_by_id,
    completeness_verdict,
    score_completeness_attempt,
)
from tests.certification.test_semantic_completeness_exam_v2_harness import (
    ScriptedVerifierProvider,
)
from tests.certification.test_semantic_completeness_exam_v3 import PASSING_FINDINGS

SCRIPTED = ModelIdentity(provider="scripted", model="verifier-model")
_REGION = {"INCOMPLETE": "missing", "OVERREACH": "unsupported", "CONTRADICTORY": "contradictory"}

Answer = Callable[[CompletenessRequest], Any]


def _contestant() -> Contestant:
    return Contestant(
        identity=SCRIPTED,
        credential_env="UNUSED",
        provider_factory=lambda key: None,
        timeout_seconds=COMPLETENESS_TIMEOUT_SECONDS,
        task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
        contracts=free_text_completeness_sitting(),
        evidence_namespace="unused",
        wire_schema=OpenAIModelProvider.wire_schema,
        wire_schema_compiler=OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    )


def _case_of(request: CompletenessRequest) -> InventoryCase:
    (case,) = [c for c in CASES if c.request == request]
    return case


def _report(
    request: CompletenessRequest,
    verdict_of: Callable[[InventoryCase, str, str], str],
    finding_of: Callable[[InventoryCase, str], tuple[str, ...]],
) -> dict[str, Any]:
    case = _case_of(request)
    sealed = {e.proposition_id: e.verdict for e in case.expected}
    out = []
    for p in request.propositions:
        verdict = verdict_of(case, p.proposition_id, sealed[p.proposition_id])
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
    return CompletenessReport(verdicts=tuple(out)).model_dump(mode="json")


def _true_finding(case: InventoryCase, pid: str) -> tuple[str, ...]:
    return PASSING_FINDINGS.get(case.case_id, {}).get(pid, ("the second claim",))


def _sealed(case: InventoryCase, pid: str, verdict: str) -> str:
    return verdict


def perfect(request: CompletenessRequest) -> Any:
    return _report(request, _sealed, _true_finding)


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


def _bad(answer: Answer) -> set[str]:
    attempts, _ = sit(answer)
    assert completeness_verdict(attempts) == "NOT CERTIFIED"
    return {a["case"] for a in attempts if a["verdict"] != "PASS"}


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


def test_fewer_attempts_or_one_failed_repetition_is_never_a_pass() -> None:
    attempts, _ = sit(perfect)
    assert completeness_verdict([a for a in attempts if a["attempt"] == 1]) == "NOT CERTIFIED"
    assert completeness_verdict(attempts[:-1]) == "NOT CERTIFIED"
    assert completeness_verdict([]) == "NOT CERTIFIED"
    flipped = [dict(a) for a in attempts]
    flipped[62]["verdict"] = "FAIL"
    assert completeness_verdict(flipped) == "NOT CERTIFIED"


# --- scripted bad verifiers ------------------------------------------------------------------


def test_always_complete_is_not_certified() -> None:
    failed = _bad(lambda r: _report(r, lambda *_: "COMPLETE", _true_finding))
    assert {"C05", "C06", "C10", "C11", "C21", "C22"} <= failed


def test_always_incomplete_is_not_certified() -> None:
    failed = _bad(
        lambda r: _report(r, lambda *_: "INCOMPLETE", lambda c, p: ("a later claim is refused",))
    )
    assert {"C01", "C02", "C03", "C04", "C10", "C24", "C25"} <= failed


def test_correct_verdicts_with_bad_findings_are_not_certified() -> None:
    non_complete = {c.case_id for c in CASES if any(e.verdict != "COMPLETE" for e in c.expected)}
    assert _bad(lambda r: _report(r, _sealed, lambda c, p: ("",))) == non_complete
    order = list(PASSING_FINDINGS)

    def someone_elses(case: InventoryCase, pid: str) -> tuple[str, ...]:
        other = order[(order.index(case.case_id) + 1) % len(order)]
        return next(iter(PASSING_FINDINGS[other].values()))

    assert _bad(lambda r: _report(r, _sealed, someone_elses)) == non_complete


def test_a_verifier_naming_only_the_originally_designed_gap_is_not_certified() -> None:
    """v2's finding for each multi-gap case, alone: the secondary assertion goes unfound."""
    designed = {
        "C05": ("renewal is only allowed if no other member has reserved the book",),
        "C09": ("the limit of at most five items",),
        "C15": ("a report made later than the deadline is refused",),
        "C16": ("a reservation by a member with outstanding fines is cancelled",),
        "C21": ("a claim made later than 48 hours after the reservation start is refused",),
    }

    def only_designed(case: InventoryCase, pid: str) -> tuple[str, ...]:
        return designed.get(case.case_id, _true_finding(case, pid))

    assert _bad(lambda r: _report(r, _sealed, only_designed)) == set(designed)


def test_a_verifier_blind_to_actors_and_time_anchors_is_not_certified() -> None:
    def blind(case: InventoryCase, pid: str) -> tuple[str, ...]:
        dropped = ("only a member", "only members", "from return")
        return tuple(i for i in _true_finding(case, pid) if not any(d in i for d in dropped))

    assert _bad(lambda r: _report(r, _sealed, blind)) == {"C05", "C15", "C16"}


def test_a_verifier_calling_pure_overreach_incomplete_is_not_certified() -> None:
    pure = {("C10", "p1"), ("C22", "p2")}
    failed = _bad(
        lambda r: _report(
            r,
            lambda c, p, v: "INCOMPLETE" if (c.case_id, p) in pure else v,
            lambda c, p: (
                ("the anchor after return is missing",)
                if (c.case_id, p) in pure
                else _true_finding(c, p)
            ),
        )
    )
    assert failed == {"C10", "C22"}


def test_a_verifier_rejecting_faithful_decomposition_or_explicit_actors_is_not_certified() -> None:
    def suspicious(case: InventoryCase, pid: str, verdict: str) -> str:
        (p,) = [p for p in case.request.propositions if p.proposition_id == pid]
        many = len(p.claims) > 1 or "member" in p.statement.lower()
        return "INCOMPLETE" if verdict == "COMPLETE" and many else verdict

    failed = _bad(lambda r: _report(r, suspicious, _true_finding))
    assert {"C02", "C03", "C04", "C14", "C22", "C24", "C25"} <= failed


def test_an_unparseable_verifier_is_not_certified() -> None:
    attempts, _ = sit(lambda r: {"verdicts": "all fine"})
    assert completeness_verdict(attempts) == "NOT CERTIFIED"
    assert all(a["verdict"] == "FAIL" and a["parsed_report"] is None for a in attempts)


# --- what the model saw -----------------------------------------------------------------------

_HIDDEN_WORDS = (
    "complete", "incomplete", "overreach", "contradictory", "contradiction", "k credit",
    "kcredit", "regression", "expected", "verdict", "category", "hint", "exam", "marker",
    "missing", "unsupported", "represented", "contradicted", "inventory", "sealed",
    "time anchor", "v2", "v3", "v4", "bystander",
)  # fmt: skip


def test_no_request_the_provider_was_sent_leaks_the_inventory_a_verdict_or_history() -> None:
    _, provider = sit(perfect)
    assert len(provider.requests) == COMPLETENESS_CALL_BUDGET
    labels = {normalise(c.category) for c in CASES}
    labels |= {normalise(f.name) for c in CASES for e in c.expected for f in e.findings}
    ids = {c.case_id.lower() for c in CASES}
    for sent in provider.requests:
        system, user = sent.messages
        assert system.content == COMPLETENESS_SYSTEM_INSTRUCTION
        text = f" {normalise(user.content)} "
        for word in (*_HIDDEN_WORDS, *labels, *ids):
            assert f" {word} " not in text, (word, user.content[:120])


def test_the_request_is_a_function_of_the_reviews_alone() -> None:
    """The inventory, expectation and category never reach the model: rebuilding a request from
    the model-visible reviews alone reproduces it byte for byte."""
    for number, case in enumerate(CASES, start=1):
        rebuilt = CompletenessRequest(
            project_id="PROJ-A",
            subject_invocation_id=f"INV-{number:04d}",
            propositions=case.request.propositions,
        )
        assert render_request(rebuilt) == render_request(case.request), case.case_id


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


def test_an_answer_from_another_model_fails_the_global_gates() -> None:
    other = ModelIdentity(provider="scripted", model="other-model")
    case = case_by_id("C01")
    observation = run_completeness_attempt(
        _contestant(), case, 1, provider=ScriptedVerifierProvider(perfect)
    )
    assert score_completeness_attempt(observation, case, candidate=SCRIPTED) == ()
    assert score_completeness_attempt(observation, case, candidate=other) != ()


# --- the live module sits exam v4 ---------------------------------------------------------------


def test_exam_v4s_namespace_is_history_the_live_module_never_writes() -> None:
    """Exam v4 was sat once (NOT CERTIFIED 72/75); the live module has moved on to exam v5."""
    from tests.certification import test_gpt_6_astra_semantic_completeness_live as live

    assert COMPLETENESS_EVIDENCE_NAMESPACE == "semantic_completeness_verification_exam_v4"
    assert live.ASTRA_COMPLETENESS.evidence_namespace != COMPLETENESS_EVIDENCE_NAMESPACE
    assert vars(live)["CASES"] is not CASES


@pytest.mark.parametrize("case_id", ["C21"])
def test_the_k_credit_request_is_the_frozen_v2_and_v6_request(case_id: str) -> None:
    import tests.certification._completeness_exam as v2

    assert render_request(case_by_id(case_id).request) == render_request(
        v2.case_by_id(case_id).request
    )
