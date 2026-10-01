# mypy: disable-error-code="no-untyped-call"
"""The verified IE2 pipeline with a structured (policy v2) verifier, end to end and offline.

Call 2 proposal -> structured semantic completeness verification -> PASS only -> admission /
correction-set authority. Nothing in this pipeline reads English: an INCOMPLETE answer is a set
of grounded structured findings, an ungrounded one is invalid output, and either way nothing of
Call 2 applies. Replay reads the recorded structured result and never calls the verifier; v1
records stay replayable beside v2 records. The reasoner and verifier are scripted.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from foundry.application.authority_routing import list_authority_work
from foundry.application.replay import replay
from foundry.application.semantic_completeness import (
    SemanticCompletenessRefused,
    recorded_outcome,
)
from foundry.domain.semantic_completeness import (
    INCOMPLETE_PROPOSITION_MEANING,
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
    STRUCTURED_REPORT_FORMAT,
    CompletenessRequest,
    SemanticFinding,
    StructuredCompletenessReport,
    StructuredPropositionVerdict,
    VerifierIdentity,
)
from foundry.domain.structural_refusal import ExecutionMode
from tests.unit._completeness_fixtures import (
    ScriptedAccountingReasoner,
    ScriptedVerifier,
    all_complete,
    event_types,
)
from tests.unit.test_semantic_completeness_pipeline import (  # untyped v1 helpers
    _LATE_NM,
    CREDIT_CLAIM,
    K_CREDIT_CALL_2,
    LATE_T2,
    PROJECT,
    _call_2_judgments,
    _run,
    _seeded,
    _world,
)

V2 = VerifierIdentity(
    provider="openai", model="gpt-6-astra", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION_V2
)
Answer = Callable[[CompletenessRequest], StructuredCompletenessReport | None]


def structured(findings: dict[str, tuple[SemanticFinding, ...]]) -> Answer:
    """COMPLETE everywhere except the propositions given findings; the verdict follows."""

    def answer(request: CompletenessRequest) -> StructuredCompletenessReport:
        verdicts = []
        for p in request.propositions:
            found = findings.get(p.proposition_id, ())
            directions = {f.direction for f in found}
            verdict = (
                "CONTRADICTORY"
                if "CONTRADICTORY" in directions
                else "INCOMPLETE"
                if "MISSING" in directions
                else "OVERREACH"
                if "UNSUPPORTED" in directions
                else "COMPLETE"
            )
            verdicts.append(
                StructuredPropositionVerdict(
                    proposition_id=p.proposition_id,
                    verdict=verdict,  # type: ignore[arg-type]
                    claim_refs=tuple(c.ref for c in p.claims),
                    findings=found,
                )
            )
        return StructuredCompletenessReport(
            report_format=STRUCTURED_REPORT_FORMAT, verdicts=tuple(verdicts)
        )

    return answer


def v2(answer: Answer) -> ScriptedVerifier:
    return ScriptedVerifier(answer, V2)  # type: ignore[arg-type]


K_CREDIT_FINDINGS = (
    SemanticFinding(kind="CHANNEL", direction="MISSING", proposition_evidence="claimed in the app"),
    SemanticFinding(
        kind="CONSEQUENCE",
        direction="MISSING",
        proposition_evidence="A claim made later is refused",
    ),
)


# --- K-CREDIT -----------------------------------------------------------------------------------


def test_k_credit_is_caught_structurally_and_nothing_of_call_2_applies() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(
            governor,
            reasoner,
            "CREDIT-T1",
            CREDIT_CLAIM,
            v2(structured({"p13": K_CREDIT_FINDINGS})),
        )
    (failure,) = refused.value.failures
    assert failure.code == INCOMPLETE_PROPOSITION_MEANING and failure.proposition_id == "p13"
    assert failure.findings == K_CREDIT_FINDINGS
    assert [(f.kind, f.direction) for f in failure.findings] == [
        ("CHANNEL", "MISSING"),
        ("CONSEQUENCE", "MISSING"),
    ]
    semantic = governor.state().semantic
    assert _call_2_judgments(governor) == [] and semantic.claims == {}
    (record,) = semantic.completeness_records.values()
    assert record.outcome == "FAIL" and isinstance(record.report, StructuredCompletenessReport)
    assert record.verifier.policy_version == SEMANTIC_COMPLETENESS_POLICY_VERSION_V2
    assert event_types(store, PROJECT)[-1] == "SEMANTIC_COMPLETENESS_RECORDED"


def test_a_structured_verifier_that_quotes_text_that_is_not_there_applies_nothing() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    invented = SemanticFinding(
        kind="CONSEQUENCE", direction="MISSING", proposition_evidence="a late claim is fined"
    )
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v2(structured({"p13": (invented,)})))
    assert refused.value.record.failure_codes == ("VERIFIER_OUTPUT_INVALID",)
    assert governor.state().semantic.claims == {}


def test_a_v2_verifier_answering_in_the_v1_format_applies_nothing() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, ScriptedVerifier(all_complete, V2))
    assert refused.value.record.failure_codes == ("VERIFIER_OUTPUT_INVALID",)
    assert governor.state().semantic.claims == {}


def test_an_unparseable_structured_answer_applies_nothing() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v2(lambda r: None))
    assert refused.value.record.failure_codes == ("VERIFIER_OUTPUT_INVALID",)


def test_a_structured_complete_answer_passes_and_admission_continues() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    outcome = _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v2(structured({})))
    assert outcome.calls_made == 3 and len(governor.state().semantic.claims) == 2
    (record,) = governor.state().semantic.completeness_records.values()
    assert record.outcome == "PASS"
    assert all(v.findings == () for v in record.report.verdicts)  # type: ignore[union-attr]


# --- faithful splits ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "props"),
    [
        (
            "## R\n\nRules\n1. The reservation is made in the Kestrel app and states its start "
            "time and its end time.\n",
            (  # K-RES-2
                ("p05", (1,), "The reservation is made in the Kestrel app.",
                 (("ASSERT", "booking_channel", "Kestrel app"),)),
                ("p06", (1,), "The reservation states its start time and its end time.",
                 (("ASSERT", "stated_start_and_end_times", "start time and end time"),)),
            ),
        ),
        (
            "## U\n\nRules\n1. After the fifth failed attempt the app must not send another unlock "
            "command for that reservation, and the member is directed to the support line.\n",
            (  # K-UNL-4
                ("p45", (1,), "After the fifth failed attempt no further unlock command is sent.",
                 (("ASSERT", "further_commands_after_fifth_failure", "no further command"),)),
                ("p46", (1,), "After the fifth failed attempt the member is directed to support.",
                 (("ASSERT", "support_redirection_after_fifth_failure", "support line"),)),
            ),
        ),
        (
            "## R\n\nRules\n1. The reservation is made in the Kestrel app and states its start "
            "time and its end time.\n",
            (  # one proposition, judged on the union of two claims
                ("p05", (1,), "The reservation is made in the Kestrel app and states its start "
                 "and end time.", (("ASSERT", "booking_channel", "Kestrel app"),
                                   ("ASSERT", "stated_start_and_end_times",
                                    "start time and end time"))),
            ),
        ),
    ],
)  # fmt: skip
def test_faithful_splits_pass_under_the_structured_verifier(text: str, props: tuple) -> None:  # type: ignore[type-arg]
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Concern", [props])
    verifier = v2(structured({}))
    _run(governor, reasoner, "SPLIT-T1", text, verifier)
    (shown,) = verifier.requests
    assert [p.proposition_id for p in shown.propositions] == [p[0] for p in props]
    assert len(governor.state().semantic.claims) == 2


# --- correction sets ----------------------------------------------------------------------------


def test_k_late_7_complete_correction_becomes_one_correction_set_under_v2() -> None:
    _, governor, reasoner = _seeded()
    reasoner.call_2.append(_LATE_NM)
    _run(governor, reasoner, "LATE-T2", LATE_T2, v2(structured({})), sup="EV-LATE-T1")
    (pending,) = [
        r for r in governor.state().semantic.correction_sets.values() if r.status == "PENDING"
    ]
    assert len(pending.assertion_judgment_ids) == 2 and len(pending.supersede_judgment_ids) == 2


def test_a_structured_failure_creates_no_correction_set_and_no_authority_work() -> None:
    store, governor, reasoner = _seeded()
    before = governor.state().semantic
    reasoner.call_2.append(_LATE_NM)
    gap = SemanticFinding(
        kind="QUANTITY_LIMIT", direction="MISSING", proposition_evidence="does not exceed 60 EUR"
    )
    with pytest.raises(SemanticCompletenessRefused):
        _run(governor, reasoner, "LATE-T2", LATE_T2, v2(structured({"p-cap": (gap,)})),
             sup="EV-LATE-T1")  # fmt: skip
    after = governor.state().semantic
    assert after.correction_sets == {} == before.correction_sets and after.claims == before.claims
    assert "CORRECTION_SET_PROPOSED" not in event_types(store, PROJECT)
    queue = list_authority_work(governor)
    assert queue.correction_sets == () and queue.items == ()


def test_a_structured_failure_is_never_reproposed_in_production() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2, K_CREDIT_CALL_2])
    verifier = v2(structured({"p13": K_CREDIT_FINDINGS}))
    with pytest.raises(SemanticCompletenessRefused):
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier, mode=ExecutionMode.PRODUCTION)
    assert reasoner.calls == 2 and len(verifier.requests) == 1


# --- replay -----------------------------------------------------------------------------------


def test_replay_reads_the_recorded_structured_result_and_never_calls_the_verifier() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    verifier = v2(structured({"p13": K_CREDIT_FINDINGS}))
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier)
    calls = len(verifier.requests)
    replayed = replay(PROJECT, store.load(PROJECT))
    assert replayed == governor.state() and len(verifier.requests) == calls
    (record,) = replayed.semantic.completeness_records.values()
    assert record == refused.value.record
    assert record.report.verdicts[0].findings == K_CREDIT_FINDINGS  # type: ignore[union-attr]
    assert recorded_outcome(replayed, record.subject_invocation_id) == "FAIL"


def test_v1_and_v2_records_replay_side_by_side() -> None:
    store, governor, reasoner = _seeded()  # LATE-T1 verified under v1
    reasoner.call_2.append(_LATE_NM)
    _run(governor, reasoner, "LATE-T2", LATE_T2, v2(structured({})), sup="EV-LATE-T1")
    replayed = replay(PROJECT, store.load(PROJECT))
    assert replayed == governor.state()
    policies = sorted(
        r.verifier.policy_version for r in replayed.semantic.completeness_records.values()
    )
    assert policies == ["ie2-semantic-completeness-v1", "ie2-semantic-completeness-v2"]


def test_replay_keeps_the_recorded_outcome_even_where_recomputing_would_differ() -> None:
    """A structured all-COMPLETE answer from the writer's own model is recorded FAIL (not
    independent). Replay reads that FAIL; it never re-derives an outcome from the report."""
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    same = VerifierIdentity(
        provider="xai", model="grok-4.6", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION_V2
    )
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, ScriptedVerifier(structured({}), same))  # type: ignore[arg-type]
    record = refused.value.record
    assert record.failure_codes == ("VERIFIER_NOT_INDEPENDENT",)
    assert {v.verdict for v in record.report.verdicts} == {"COMPLETE"}  # type: ignore[union-attr]
    replayed = replay(PROJECT, store.load(PROJECT))
    assert recorded_outcome(replayed, record.subject_invocation_id) == "FAIL"
