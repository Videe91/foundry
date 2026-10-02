"""End-to-end Intent Engine validation, run offline through the real IE2 pipeline.

The held-out Larkspur project is walked step by step through the real governor, admission,
correction sets, the v3 completeness verifier law and founder authority. The writer, the
verifier and the adjudicator are scripted (no model, no provider); the scoring is the real
final-outcome scorer. The scripted writer is faithful except where a case says otherwise, so
what remains is what the runtime itself does with a faithful writer.
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

import ast
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.gaps import GapStatus
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
    VerifierIdentity,
)
from foundry.domain.semantic_holds import PropositionConflict, SemanticHoldGap
from foundry.experiments.intent_engine_e2e.expectations import EXPECTED
from foundry.experiments.intent_engine_e2e.harness import run_scenario
from foundry.experiments.intent_engine_e2e.outcome import (
    Adjudication,
    AdjudicationPacket,
    ClaimReading,
    DefectCategory,
    adjudication_packet,
    final_outcome,
    score,
)
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.ports.semantic_completeness import VerifierUnavailable
from foundry.ports.semantic_reasoner import AccountedProposal, ReasoningRequest
from tests.unit._completeness_fixtures import Prop, ScriptedAccountingReasoner, ScriptedVerifier
from tests.unit._ie21_fixtures import authority_record
from tests.unit.test_semantic_completeness_v3_pipeline import verdicts

AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
PROJECT = "PROJ-LARKSPUR"
FOUNDER = "human://founder"
V3 = VerifierIdentity(
    provider="verifier", model="v", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION_V3
)
D = DefectCategory


def _a(pid: str, n: tuple[int, ...], *drafts: tuple[str, ...]) -> Prop:
    return (pid, n, f"proposition {pid}", drafts)


# The faithful writer's Call-2 answer per step (predicates are the writer's own wording).
FAITHFUL: dict[str, tuple[Prop, ...]] = {
    "T01-membership": (
        _a("p1", (1,), ("ASSERT", "minimum_age", "18 or older")),
        _a("p2", (2,), ("ASSERT", "annual_fee", "20 EUR")),
        _a("p3", (3,), ("ASSERT", "proof_of_address", "required to join")),
    ),
    "T01-loan": (
        _a("p1", (1,), ("ASSERT", "loan_period", "7 days")),
        _a("p2", (2,), ("ASSERT", "renewal", "one renewal of 7 days if not reserved")),
    ),
    "T01-late": (
        _a("p1", (1,), ("ASSERT", "late_fee", "1 EUR per day")),
        _a("p2", (2,), ("ASSERT", "suspension", "30 days after three late returns")),
    ),
    "T01-deposit": (_a("p1", (1,), ("ASSERT", "deposit", "50 EUR, refunded on return")),),
    "T01-damage": (
        _a("p1", (1,), ("ASSERT", "repair_cost", "borrower pays the repair cost")),
        _a("p2", (2,), ("ASSERT", "report_deadline", "within 24 hours of the return")),
    ),
    "T01-reservations": (_a("p1", (1,), ("ASSERT", "hold_period", "2 days")),),
    "T02-loan": (
        _a("p1", (1,), ("SUPPORT", "loan_period")),
        _a("p2", (2,), ("SUPPORT", "renewal")),
    ),
    "T03-loan": (
        _a("p1", (1,), ("ASSERT", "loan_period_v2", "14 days"), ("SUPERSEDE", "loan_period")),
        _a("p2", (2,), ("SUPPORT", "renewal")),
    ),
    "T04-late": (
        _a("p1", (1,), ("ASSERT", "late_block", "no borrowing until the tool is back"),
           ("SUPERSEDE", "late_fee"), ("SUPERSEDE", "suspension")),
    ),
    "T05-deposit": (
        _a("p1", (1,), ("ASSERT", "handheld_deposit", "30 EUR"), ("SUPERSEDE", "deposit")),
        _a("p2", (2,), ("ASSERT", "stationary_deposit", "80 EUR")),
    ),
    "T06-damage": (
        _a("p1", (1,), ("ASSERT", "repair_liability", "up to replacement value"),
           ("SUPERSEDE", "repair_cost")),
        _a("p2", (2,), ("ASSERT", "damage_report", "at the return desk on return"),
           ("SUPERSEDE", "report_deadline")),
    ),
    # The handbook contradicts the spec: the writer names the conflict with the current claim.
    "T07-reservations": (
        _a("p1", (1,), ("ASSERT", "hold_period_handbook", "3 days"),
           ("CONFLICT_CLAIM", "hold_period")),
    ),
    "T08-loan": (
        _a("p1", (1, 3), ("SUPPORT", "loan_period_v2")),
        _a("p2", (2,), ("SUPPORT", "renewal")),
    ),
    "T09-loan": (
        _a("p1", (1,), ("ASSERT", "loan_period_v3", "10 days"), ("SUPERSEDE", "loan_period_v2")),
        _a("p2", (2,), ("SUPPORT", "renewal")),
    ),
    # The first proposal of the revision drops "members under 25 pay 10 EUR".
    "T10-membership": (
        _a("p1", (1,), ("SUPPORT", "minimum_age")),
        _a("p2", (2,), ("ASSERT", "annual_fee_v2", "25 EUR"), ("SUPERSEDE", "annual_fee")),
        _a("p3", (3,), ("SUPPORT", "proof_of_address")),
    ),
    "T11-membership": (
        _a("p1", (1,), ("SUPPORT", "minimum_age")),
        _a("p2", (2,), ("ASSERT", "annual_fee_v2", "25 EUR"),
           ("ASSERT", "under_25_fee", "10 EUR"), ("SUPERSEDE", "annual_fee")),
        _a("p3", (3,), ("SUPPORT", "proof_of_address")),
    ),
}  # fmt: skip

# What the scripted adjudicator reads each (predicate, value) as.
TRUTH_OF = {
    "minimum_age": "M1", "annual_fee": "M2", "proof_of_address": "M3", "annual_fee_v2": "M4",
    "under_25_fee": "M5", "loan_period": "L1", "renewal": "L2", "loan_period_v2": "L3",
    "loan_period_v3": "L4", "late_fee": "F1", "suspension": "F2", "late_block": "F3",
    "deposit": "D1", "handheld_deposit": "D2", "stationary_deposit": "D3",
    "repair_cost": "X1", "report_deadline": "X2", "repair_liability": "X3",
    "damage_report": "X4", "hold_period": "R1", "hold_period_handbook": "R2",
}  # fmt: skip
CONTRADICTING = {frozenset(("R1", "R2"))}


class ScenarioWriter(ScriptedAccountingReasoner):
    """One scripted writer for the whole project: the step's concern is the subject."""

    def __init__(self, script: dict[str, tuple[Prop, ...]]) -> None:
        super().__init__("", [])
        self.script = script

    def propose_accounted(self, request: ReasoningRequest) -> AccountedProposal:
        (item,) = request.evidence
        step = SCENARIO_BY_EVIDENCE[item.evidence_id]
        self.subject = step.concern
        if any(k.value == "CREATE_ADDRESS" for k in request.allowed_judgment_kinds):
            return super().propose_accounted(request)
        by_predicate = {c.predicate: c for c in request.known_claims}
        conflicts: list[PropositionConflict] = []
        clean: list[Prop] = []
        for pid, numbers, statement, drafts in self.script[step.step_id]:
            for d in drafts:
                if d[0] == "CONFLICT_CLAIM":
                    conflicts.append(
                        PropositionConflict(
                            proposition_id=pid, with_claim_id=by_predicate[d[1]].claim_id
                        )
                    )
            clean.append(
                (pid, numbers, statement, tuple(d for d in drafts if d[0] != "CONFLICT_CLAIM"))
            )
        self.call_2.append(tuple(clean))
        proposal = super().propose_accounted(request)
        return proposal.model_copy(update={"conflicts": tuple(conflicts)})


SCENARIO_BY_EVIDENCE = {f"EV-{s.step_id}": s for s in SCENARIO.steps}


class ScriptedAdjudicator:
    def __init__(self) -> None:
        self.packets: list[AdjudicationPacket] = []

    def adjudicate(self, packet: AdjudicationPacket) -> Adjudication:
        self.packets.append(packet)
        current = [c for c in packet.claims if c.current]
        return Adjudication(
            readings=tuple(
                ClaimReading(claim_id=c.claim_id, truth_id=TRUTH_OF.get(c.predicate),
                             faithful=True)
                for c in packet.claims
            ),
            contradictions=tuple(
                (a.claim_id, b.claim_id)
                for i, a in enumerate(current) for b in current[i + 1:]
                if frozenset((TRUTH_OF.get(a.predicate), TRUTH_OF.get(b.predicate)))
                in CONTRADICTING
            ),
        )  # fmt: skip


def _governor() -> tuple[InMemoryEventStore, SemanticGovernor]:
    ids = count(1)
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(canonical_facets=True, correction_sets=True),
        clock=lambda: AT,
        id_factory=lambda p: f"{p}-{next(ids):05d}",
    )
    governor.record_authority(
        authority_record("AUTH-founder", project_id=PROJECT, scope=(), subject_id="larkspur",
                         authorized_by=FOUNDER, authority=Authority.CANONICAL)
    )  # fmt: skip
    return store, governor


def _run(script: dict[str, tuple[Prop, ...]], verifier: Any) -> tuple[Any, Any, Any]:
    store, governor = _governor()
    run = run_scenario(
        scenario=SCENARIO,
        governor=governor,
        reasoner=ScenarioWriter(script),
        verifier=verifier,
        human_actor_id=FOUNDER,
        observed_at=AT,
    )
    return store, governor, run


def _score(governor: SemanticGovernor, run: Any) -> Any:
    outcome = final_outcome(
        governor.state(),
        scenario_id=SCENARIO.scenario_id,
        scope=SCENARIO.scope,
        ie3_evaluated=False,
        refused_steps=run.refused_steps,
    )
    adjudicator = ScriptedAdjudicator()
    return score(outcome, EXPECTED, adjudicator.adjudicate(adjudication_packet(outcome, EXPECTED)))


def _verifier_catching_t10() -> ScriptedVerifier:
    """Answers COMPLETE everywhere except the T10 proposal that lost the under-25 fee."""
    complete, t10 = verdicts(), verdicts({"p2"}, note="the under-25 fee is not in any claim")
    return ScriptedVerifier(lambda r: t10(r) if _is_t10(r) else complete(r), V3)


def _is_t10(request: Any) -> bool:
    p2 = [p for p in request.propositions if p.proposition_id == "p2"]
    return bool(p2) and [c.predicate for c in p2[0].claims] == ["annual_fee_v2"]


# --- the faithful writer --------------------------------------------------------------------


def test_the_faithful_run_walks_every_step_and_holds_only_the_conflict_and_the_lost_fee() -> None:
    _, governor, run = _run(FAITHFUL, _verifier_catching_t10())
    status = {s.step_id: s.status for s in run.steps}
    assert status.pop("T07-reservations") == "HELD"
    assert status.pop("T10-membership") == "HELD"
    assert set(status.values()) == {"APPLIED"}
    decided = {s.step_id: s.decision_status for s in run.steps if s.decision_status}
    assert decided == {
        "T03-loan": "AGREED", "T04-late": "AGREED", "T05-deposit": "DECLINED",
        "T06-damage": "AGREED", "T09-loan": "AGREED", "T11-membership": "AGREED",
    }  # fmt: skip
    assert run.refused_steps == ()


def test_the_faithful_run_ends_with_every_ie2_outcome_correct() -> None:
    """Every truth, correction, decline and authority outcome is right; the handbook's
    contradiction is held, never current, and keeps the project from closing; the lost fee's
    gap closed when the complete revision was admitted. IE3 is not run offline, so the verdict
    is INCOMPLETE, never PASS."""
    _, governor, run = _run(FAITHFUL, _verifier_catching_t10())
    report = _score(governor, run)
    assert report.defects == ()
    assert report.counts["CONTRADICTORY_CURRENT_TRUTHS"] == 0
    assert report.counts["INCORRECT_CLOSURE"] == 0
    assert report.verdict == "INCOMPLETE" and not report.ie3_evaluated
    holds = {g.cause: g for g in governor.state().gaps.values() if isinstance(g, SemanticHoldGap)}
    assert set(holds) == {"CONFLICT", "NOT_COMPLETE"}
    assert holds["NOT_COMPLETE"].status is GapStatus.RESOLVED
    assert holds["CONFLICT"].status is GapStatus.OPEN


def test_replay_reproduces_the_scored_final_state() -> None:
    store, governor, run = _run(FAITHFUL, _verifier_catching_t10())
    replayed = replay(PROJECT, store.load(PROJECT))
    assert replayed == governor.state()
    outcome = final_outcome(replayed, scenario_id="x", scope=SCENARIO.scope, ie3_evaluated=False)
    assert outcome == final_outcome(
        governor.state(), scenario_id="x", scope=SCENARIO.scope, ie3_evaluated=False
    )


# --- the admission verifier (v4) as the contradiction backstop -------------------------------


def _admission_verifier() -> Any:
    """A scripted v4 verifier: it catches the lost under-25 fee at T10 (NOT_COMPLETE) and the
    handbook's 3-day hold at T07 (CONFLICT with the current 2-day claim it is shown)."""
    from foundry.domain.semantic_completeness import (
        ADMISSION_REPORT_FORMAT,
        AdmissionReport,
        AdmissionVerdict,
    )
    from tests.unit.test_semantic_admission_v4 import AdmissionVerifier

    def answer(request: Any) -> AdmissionReport:
        shown = {c.predicate: c.claim_id for c in request.current_claims}
        out = []
        for p in request.propositions:
            asserted = {c.predicate for c in p.claims}
            conflict = (
                (shown["hold_period"],)
                if "hold_period_handbook" in asserted and "hold_period" in shown
                else ()
            )
            out.append(
                AdmissionVerdict(
                    proposition_id=p.proposition_id,
                    completeness="NOT_COMPLETE"
                    if _is_t10(request) and p.proposition_id == "p2"
                    else "COMPLETE",
                    consistency="CONFLICT" if conflict else "NO_CONFLICT",
                    conflicting_claim_ids=conflict,
                )
            )
        return AdmissionReport(report_format=ADMISSION_REPORT_FORMAT, verdicts=tuple(out))

    return AdmissionVerifier(answer)


WRITER_MISSES_T07 = {
    **FAITHFUL,
    "T07-reservations": (_a("p1", (1,), ("ASSERT", "hold_period_handbook", "3 days")),),
}


@pytest.mark.parametrize("script", [WRITER_MISSES_T07, FAITHFUL], ids=["writer-misses", "both"])
def test_the_admission_verifier_catches_the_contradiction_the_writer_misses(
    script: dict[str, tuple[Prop, ...]],
) -> None:
    _, governor, run = _run(script, _admission_verifier())
    report = _score(governor, run)
    assert report.defects == ()
    assert report.counts["CONTRADICTORY_CURRENT_TRUTHS"] == 0
    assert report.counts["INCORRECT_CLOSURE"] == 0
    assert report.verdict == "INCOMPLETE"
    holds = [g for g in governor.state().gaps.values() if isinstance(g, SemanticHoldGap)]
    assert sorted((g.cause, g.status.value) for g in holds) == [
        ("CONFLICT", "OPEN"),
        ("NOT_COMPLETE", "RESOLVED"),
    ], "one contradiction gap, never two"


# --- outcome failures the harness must catch ------------------------------------------------


def test_a_verifier_that_misses_the_lost_fee_leaves_a_missing_truth() -> None:
    script = dict(FAITHFUL)
    script["T11-membership"] = FAITHFUL["T10-membership"]  # the writer drops it both times
    _, governor, run = _run(script, ScriptedVerifier(verdicts(), V3))
    categories = {d.subject[0] for d in _score(governor, run).defects
                  if d.category is D.MISSING_TRUTH}  # fmt: skip
    assert categories == {"M5"}


def test_a_founder_agreeing_to_the_declined_deposit_change_is_caught() -> None:
    scenario = SCENARIO.model_copy(
        update={
            "steps": tuple(
                s.model_copy(update={"decision": "AGREE"}) if s.step_id == "T05-deposit" else s
                for s in SCENARIO.steps
            )
        }
    )
    _, governor = _governor()
    run = run_scenario(scenario=scenario, governor=governor, reasoner=ScenarioWriter(FAITHFUL),
                       verifier=_verifier_catching_t10(), human_actor_id=FOUNDER,
                       observed_at=AT)  # fmt: skip
    report = _score(governor, run)
    assert {d.subject[0] for d in report.defects
            if d.category is D.DECLINED_CHANGE_APPLIED} == {"D2", "D3"}  # fmt: skip
    assert any(d.category is D.WRONG_CORRECTION_TARGET and d.subject == ("D1",)
               for d in report.defects)  # fmt: skip


def test_an_unreachable_verifier_holds_every_step_visibly_and_applies_nothing() -> None:
    class Unreachable:
        def verify(self, request: Any) -> Any:
            raise VerifierUnavailable("no model holds the v3 contract")

    founding = SCENARIO.model_copy(  # the dense spec: later steps restate claims never applied
        update={"steps": tuple(s for s in SCENARIO.steps if s.step_id.startswith("T01-"))}
    )
    _, governor = _governor()
    run = run_scenario(scenario=founding, governor=governor, reasoner=ScenarioWriter(FAITHFUL),
                       verifier=Unreachable(), human_actor_id=FOUNDER, observed_at=AT)  # fmt: skip
    assert run.refused_steps == () and len(run.steps) == 6
    assert {s.status for s in run.steps} == {"HELD"}
    state = governor.state()
    causes = {g.cause for g in state.gaps.values() if isinstance(g, SemanticHoldGap)}
    assert causes == {"VERIFICATION_UNAVAILABLE"}
    assert state.semantic.claims == {} and state.semantic.completeness_records == {}
    report = _score(governor, run)
    assert report.counts["SILENT_GAP"] == 0 and report.verdict == "FAIL"


def test_an_unexpected_failure_refuses_the_step_once_and_is_never_retried() -> None:
    class Broken:
        calls = 0

        def verify(self, request: Any) -> Any:
            Broken.calls += 1
            raise RuntimeError("verifier crashed")

    founding = SCENARIO.model_copy(
        update={"steps": tuple(s for s in SCENARIO.steps if s.step_id.startswith("T01-"))}
    )
    _, governor = _governor()
    run = run_scenario(scenario=founding, governor=governor, reasoner=ScenarioWriter(FAITHFUL),
                       verifier=Broken(), human_actor_id=FOUNDER, observed_at=AT)  # fmt: skip
    assert run.refused_steps == tuple(s.step_id for s in founding.steps)
    assert {s.detail for s in run.steps} == {"RuntimeError"}
    assert Broken.calls == len(founding.steps), "one attempt per step, never a retry"
    assert _score(governor, run).counts["SILENT_GAP"] == len(founding.steps)


# --- isolation --------------------------------------------------------------------------------


def test_executors_never_see_the_expectations() -> None:
    package = Path("src/foundry/experiments/intent_engine_e2e")
    for module in ("scenario.py", "harness.py"):
        tree = ast.parse((package / module).read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any("expectations" in m or m.endswith(".outcome") for m in imported), module
    writer = ScenarioWriter(FAITHFUL)
    seen: list[str] = []
    original = writer.propose_accounted

    def spy(request: ReasoningRequest) -> AccountedProposal:
        seen.append(request.model_dump_json())
        return original(request)

    writer.propose_accounted = spy  # type: ignore[method-assign]
    _, governor = _governor()
    run_scenario(scenario=SCENARIO, governor=governor, reasoner=writer,
                 verifier=_verifier_catching_t10(), human_actor_id=FOUNDER,
                 observed_at=AT)  # fmt: skip
    text = " ".join(seen)
    for truth in EXPECTED.truths:
        if truth.final in ("RETIRED", "NEVER"):
            continue
        assert truth.truth_id not in {w for w in text.split() if w.isalnum()}
    for status in ("HELD", "NEVER", "RETIRED"):
        assert status not in text


@pytest.mark.parametrize("step", SCENARIO.steps, ids=lambda s: s.step_id)
def test_every_step_has_a_faithful_script(step: Any) -> None:
    assert step.step_id in FAITHFUL


def test_the_founder_decides_only_when_exactly_one_set_is_pending_at_the_concern() -> None:
    steps = {s.step_id: s for s in SCENARIO.steps}
    second = steps["T05-deposit"].model_copy(
        update={"step_id": "T05b-deposit", "supersedes_step": "T05-deposit", "decision": "AGREE",
                "text": steps["T05-deposit"].text.replace("80 EUR", "90 EUR")}
    )  # fmt: skip
    scenario = SCENARIO.model_copy(
        update={"steps": (steps["T01-deposit"],
                          steps["T05-deposit"].model_copy(update={"decision": None}), second)}
    )  # fmt: skip
    script = dict(FAITHFUL)
    script["T05b-deposit"] = (
        _a("p1", (1,), ("ASSERT", "handheld_deposit", "30 EUR"), ("SUPERSEDE", "deposit")),
        _a("p2", (2,), ("ASSERT", "stationary_deposit", "90 EUR")),
    )
    SCENARIO_BY_EVIDENCE["EV-T05b-deposit"] = second
    try:
        _, governor = _governor()
        run = run_scenario(scenario=scenario, governor=governor, reasoner=ScenarioWriter(script),
                           verifier=ScriptedVerifier(verdicts(), V3), human_actor_id=FOUNDER,
                           observed_at=AT)  # fmt: skip
    finally:
        del SCENARIO_BY_EVIDENCE["EV-T05b-deposit"]
    pending = [r for r in governor.state().semantic.correction_sets.values()
               if r.status == "PENDING"]  # fmt: skip
    assert len(pending) == 2
    assert run.steps[-1].decision_status == "NOT_DECIDED: 2 pending correction sets at Deposits"
