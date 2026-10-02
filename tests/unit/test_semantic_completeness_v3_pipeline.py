"""The verified IE2 pipeline under the runtime verifier (policy v3), end to end and offline.

Writer proposal -> deterministic structure / accounting -> independent completeness check ->
COMPLETE: normal admission and authority; NOT_COMPLETE: a durable, blocking, visible gap and no
canonical application. The unit held is the minimal safe unit: a proposition with every
proposition its judgments share a correction set with. Anything else in the response applies.
An invalid verifier answer holds the whole response. The verifier's note is never read. Replay
reads the record and never calls the verifier.
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from foundry.application.authority_routing import list_authority_work
from foundry.application.replay import replay
from foundry.domain.closure import evaluate_closure
from foundry.domain.gaps import GapKind, GapStatus
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
    VERDICT_REPORT_FORMAT,
    CompletenessRequest,
    PropositionCheck,
    VerdictCompletenessReport,
    VerifierIdentity,
)
from foundry.domain.structural_refusal import ExecutionMode
from tests.unit._completeness_fixtures import (
    ScriptedAccountingReasoner,
    ScriptedVerifier,
    event_types,
)
from tests.unit.test_semantic_completeness_pipeline import (
    _LATE_NM,
    CREDIT_CLAIM,
    K_CREDIT_CALL_2,
    LATE_T2,
    PROJECT,
    SCOPE,
    _call_2_judgments,
    _run,
    _seeded,
    _world,
)

V3 = VerifierIdentity(
    provider="openai", model="gpt-6-astra", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION_V3
)
Answer = Callable[[CompletenessRequest], Any]


def verdicts(not_complete: set[str] = frozenset(), note: str | None = None) -> Answer:  # type: ignore[assignment]
    def answer(request: CompletenessRequest) -> VerdictCompletenessReport:
        return VerdictCompletenessReport(
            report_format=VERDICT_REPORT_FORMAT,
            verdicts=tuple(
                PropositionCheck(
                    proposition_id=p.proposition_id,
                    verdict="NOT_COMPLETE" if p.proposition_id in not_complete else "COMPLETE",
                    note=note,
                )
                for p in request.propositions
            ),
        )

    return answer


def v3(answer: Answer, identity: VerifierIdentity = V3) -> ScriptedVerifier:
    return ScriptedVerifier(answer, identity)


def _open_gaps(governor: Any) -> list[Any]:
    return [g for g in governor.state().gaps.values() if g.status is GapStatus.OPEN]


def _predicates(governor: Any) -> set[str]:
    return {c.predicate for c in governor.state().semantic.claims.values()}


def _blocked_by(governor: Any, gap_id: str) -> bool:
    closure = evaluate_closure(governor.state(), SCOPE)
    return any(
        b.code == "OPEN_BLOCKING_GAP" and b.object_ids == (gap_id,) for b in closure.blockers
    )


K_CREDIT_COMPLETE = (
    (
        "p13",
        (1, 2),
        "The service credit for an unavailable vehicle must be claimed in the app within 48 hours "
        "after the reservation start, and a later claim is refused.",
        (
            ("ASSERT", "claim_deadline_after_reservation_start", "48 hours"),
            ("ASSERT", "late_claim_outcome", "a claim made later is refused"),
            ("ASSERT", "claim_channel", "in the app"),
        ),
    ),
    K_CREDIT_CALL_2[1],
)


# --- K-CREDIT -----------------------------------------------------------------------------------


def test_k_credit_not_complete_is_held_as_a_blocking_gap_and_the_rest_applies() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    outcome = _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v3(verdicts({"p13"})))
    assert outcome.calls_made == 3, "no retry, no second verification"
    assert "claim_deadline_after_reservation_start" not in _predicates(governor)
    assert _predicates(governor) == {"claim_contents"}, "the independent p14 applies"
    (gap,) = _open_gaps(governor)
    assert gap.kind is GapKind.WORKER_DIVERGENCE and gap.blocking and "p13" in gap.description
    assert _blocked_by(governor, gap.id)
    (record,) = governor.state().semantic.completeness_records.values()
    assert record.outcome == "FAIL" and record.held_proposition_ids == ("p13",)
    assert record.gap_ids == (gap.id,)
    assert governor.state().semantic.correction_sets == {}
    queue = list_authority_work(governor)
    assert queue.items == () and queue.correction_sets == ()
    types = event_types(store, PROJECT)
    assert types.index("SEMANTIC_COMPLETENESS_RECORDED") < types.index("GAP_RECORDED")


def test_k_credit_complete_admits_normally() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_COMPLETE])
    _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v3(verdicts()))
    assert _predicates(governor) == {
        "claim_deadline_after_reservation_start", "late_claim_outcome", "claim_channel",
        "claim_contents",
    }  # fmt: skip
    assert _open_gaps(governor) == []
    (record,) = governor.state().semantic.completeness_records.values()
    assert record.outcome == "PASS" and record.held_proposition_ids == () and record.gap_ids == ()


# --- the note never matters ----------------------------------------------------------------------

NOTES = (
    "late refusal missing",
    "the consequence was not retained",
    "something about refusal",
    "Purple elephants negotiate the tide at dawn.",
    None,
)


def _outcome(answer: Answer, call_2: tuple[Any, ...] = K_CREDIT_CALL_2) -> tuple[Any, ...]:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [call_2])
    _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v3(answer))
    state = governor.state()
    return (
        sorted(_predicates(governor)),
        sorted((g.id, g.kind, g.blocking, g.status, g.description) for g in state.gaps.values()),
        sorted(state.semantic.correction_sets),
        list_authority_work(governor),
        evaluate_closure(state, SCOPE),
        [
            (r.outcome, r.failure_codes, r.held_proposition_ids, r.gap_ids)
            for r in state.semantic.completeness_records.values()
        ],
    )


def test_the_note_wording_never_changes_the_runtime_result() -> None:
    failing = {repr(_outcome(verdicts({"p13"}, note))) for note in NOTES}
    assert len(failing) == 1
    passing = {repr(_outcome(verdicts(set(), note), K_CREDIT_COMPLETE)) for note in NOTES}
    assert len(passing) == 1


# --- a partial response ------------------------------------------------------------------------

THREE_RULES = (
    "## 3. Parking\n\nRules\n"
    "1. A vehicle must be parked in a marked bay.\n"
    "2. A vehicle left outside a bay is towed at the member's cost.\n"
    "3. Parking is free for the first 30 minutes.\n"
)
THREE_CALL_2 = (
    (
        "p1",
        (1,),
        "A vehicle must be parked in a marked bay.",
        (("ASSERT", "parking_location", "a marked bay"),),
    ),
    (
        "p2",
        (2,),
        "A vehicle left outside a bay is towed at the member's cost.",
        (("ASSERT", "outside_bay_outcome", "towed"),),
    ),
    (
        "p3",
        (3,),
        "Parking is free for the first 30 minutes.",
        (("ASSERT", "free_parking_period", "30 minutes"),),
    ),
)


def test_independent_complete_propositions_apply_and_the_failed_one_becomes_a_gap() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Parking", [THREE_CALL_2])
    decisions = _run(governor, reasoner, "PARK-T1", THREE_RULES, v3(verdicts({"p2"})))
    assert decisions is not None
    assert _predicates(governor) == {"parking_location", "free_parking_period"}
    (gap,) = _open_gaps(governor)
    assert "p2" in gap.description and "p1" not in gap.description and "p3" not in gap.description
    assert _blocked_by(governor, gap.id), "closure stays blocked by p2"


# --- correction sets stay atomic ---------------------------------------------------------------


def test_one_incomplete_member_holds_the_whole_correction_set() -> None:
    store, governor, reasoner = _seeded()
    before = _predicates(governor)
    reasoner.call_2.append(_LATE_NM)
    _run(governor, reasoner, "LATE-T2", LATE_T2, v3(verdicts({"p-flat"})), sup="EV-LATE-T1")
    semantic = governor.state().semantic
    assert semantic.correction_sets == {}, (
        "no correction set formed, nothing for a human to approve"
    )
    assert "CORRECTION_SET_PROPOSED" not in event_types(store, PROJECT)
    assert {"rate", "grace", "cap"} <= _predicates(
        governor
    ) and "flat_fee_amount" not in _predicates(governor)
    assert "charged_for_any_delay" not in _predicates(governor), "the other member is held too"
    assert _predicates(governor) == before, "old state remains current"
    (gap,) = _open_gaps(governor)
    assert "p-flat" in gap.description and "p-any" in gap.description
    queue = list_authority_work(governor)
    assert queue.correction_sets == () and queue.items == ()
    (record,) = [r for r in semantic.completeness_records.values() if r.verifier == V3]
    assert set(record.held_proposition_ids) == {"p-flat", "p-any"}


def test_a_complete_correction_set_behaves_exactly_as_before() -> None:
    _, governor, reasoner = _seeded()
    reasoner.call_2.append(_LATE_NM)
    _run(governor, reasoner, "LATE-T2", LATE_T2, v3(verdicts()), sup="EV-LATE-T1")
    (pending,) = [
        r for r in governor.state().semantic.correction_sets.values() if r.status == "PENDING"
    ]
    assert len(pending.assertion_judgment_ids) == 2 and len(pending.supersede_judgment_ids) == 2
    assert _open_gaps(governor) == []


# --- invalid verifier answers fail safe ---------------------------------------------------------


def _drop(request: CompletenessRequest) -> VerdictCompletenessReport:
    return verdicts()(request).model_copy(update={"verdicts": verdicts()(request).verdicts[:1]})


def _duplicate(request: CompletenessRequest) -> VerdictCompletenessReport:
    report = verdicts()(request)
    return report.model_copy(update={"verdicts": (*report.verdicts, report.verdicts[0])})


def _unknown(request: CompletenessRequest) -> VerdictCompletenessReport:
    report = verdicts()(request)
    extra = PropositionCheck(proposition_id="p99", verdict="COMPLETE")
    return report.model_copy(update={"verdicts": (*report.verdicts, extra)})


def _v1_format(request: CompletenessRequest) -> Any:
    from tests.unit._completeness_fixtures import all_complete

    return all_complete(request)


@pytest.mark.parametrize(
    ("answer", "identity", "code"),
    [
        (lambda r: None, V3, "VERIFIER_OUTPUT_INVALID"),
        (_drop, V3, "VERIFIER_OUTPUT_INVALID"),
        (_duplicate, V3, "VERIFIER_OUTPUT_INVALID"),
        (_unknown, V3, "VERIFIER_OUTPUT_INVALID"),
        (_v1_format, V3, "VERIFIER_OUTPUT_INVALID"),
        (
            verdicts(),
            V3.model_copy(update={"provider": "xai", "model": "grok-4.6"}),
            "VERIFIER_NOT_INDEPENDENT",
        ),
    ],
    ids=[
        "missing",
        "dropped-proposition",
        "duplicate",
        "unknown-proposition",
        "wrong-format",
        "same-model",
    ],
)
def test_an_invalid_verifier_answer_holds_the_whole_response(
    answer: Answer, identity: VerifierIdentity, code: str
) -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v3(answer, identity))
    assert _call_2_judgments(governor) == [] and governor.state().semantic.claims == {}
    (gap,) = _open_gaps(governor)
    assert "p13" in gap.description and "p14" in gap.description and gap.blocking
    (record,) = governor.state().semantic.completeness_records.values()
    assert record.failure_codes == (code,) and set(record.held_proposition_ids) == {"p13", "p14"}


def test_no_semantic_retry_and_a_structural_reproposal_stays_structural() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2, K_CREDIT_CALL_2])
    verifier = v3(verdicts({"p13"}))
    _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier, mode=ExecutionMode.PRODUCTION)
    assert reasoner.calls == 2 and len(verifier.requests) == 1


# --- replay -------------------------------------------------------------------------------------


def test_replay_reads_the_recorded_verdicts_and_never_calls_the_verifier() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    verifier = v3(verdicts({"p13"}))
    _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier)
    calls = len(verifier.requests)
    replayed = replay(PROJECT, store.load(PROJECT))
    assert replayed == governor.state() and len(verifier.requests) == calls
    (record,) = replayed.semantic.completeness_records.values()
    assert isinstance(record.report, VerdictCompletenessReport)


def test_v1_and_v3_records_replay_side_by_side() -> None:
    store, governor, reasoner = _seeded()  # LATE-T1 verified under v1
    reasoner.call_2.append(_LATE_NM)
    _run(governor, reasoner, "LATE-T2", LATE_T2, v3(verdicts({"p-cap"})), sup="EV-LATE-T1")
    replayed = replay(PROJECT, store.load(PROJECT))
    assert replayed == governor.state()
    assert sorted(
        r.verifier.policy_version for r in replayed.semantic.completeness_records.values()
    ) == [
        "ie2-semantic-completeness-v1",
        "ie2-semantic-completeness-v3",
    ]


def test_replay_keeps_a_recorded_fail_where_recomputing_from_the_report_would_pass() -> None:
    from foundry.application.semantic_completeness import recorded_outcome

    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    same = V3.model_copy(update={"provider": "xai", "model": "grok-4.6"})
    _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, v3(verdicts(), same))
    replayed = replay(PROJECT, store.load(PROJECT))
    (record,) = replayed.semantic.completeness_records.values()
    assert {v.verdict for v in record.report.verdicts} == {"COMPLETE"}  # type: ignore[union-attr]
    assert recorded_outcome(replayed, record.subject_invocation_id) == "FAIL"
