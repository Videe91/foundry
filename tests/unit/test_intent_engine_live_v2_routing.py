"""Founder decisions route by runtime provenance, never by model wording (live e2e v2).

v1 routed a decision to "the pending correction set at this concern" by the writer's address
label, and lost six of seven decisions to harmless relabelling. The v2 harness binds a decision
to the correction work proposed inside the step's own ledger window, whose members saw exactly
the step's immutable evidence; it refuses to guess and stops on anything ambiguous.
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
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.semantic_completeness import (
    ADMISSION_REPORT_FORMAT_V5,
    AdmissionReportV5,
    AdmissionVerdictV5,
    ReplacementVerdict,
)
from foundry.domain.semantic_holds import PropositionConflict
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.experiments.intent_engine_e2e.scenario import SCENARIO, Scenario
from foundry.experiments.intent_engine_live_v2.harness import (
    RoutingAmbiguous,
    RoutingUnexplained,
    ScenarioRun,
    route_decision,
    run_scenario,
)
from foundry.ports.semantic_reasoner import AccountedProposal, ReasoningRequest
from tests.unit._completeness_fixtures import Prop, ScriptedAccountingReasoner
from tests.unit._ie21_fixtures import authority_record
from tests.unit.test_intent_engine_e2e_harness import FAITHFUL, WRITER_MISSES_T07
from tests.unit.test_semantic_admission_v5 import AdmissionVerifierV5

AT = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
PROJECT = "PROJ-ROUTING"
FOUNDER = "human://founder"

GROK_LABELS = {
    "Loan period": "Tool loan", "Late returns": "Late return", "Deposits": "Tool loan",
    "Damage": "Tool damage", "Reservations": "Tool reservation",
    "Opening hours": "Library opening hours",
}  # fmt: skip
"""The labels Grok chose in the live v1 run (deposits under the loan concern included)."""

# Grok's live T07 shape: the handbook's 3 days as a correction of the 2-day claim.
MISLABELLED_T07 = {
    **WRITER_MISSES_T07,
    "T07-reservations": (
        ("p1", (1,), "proposition p1",
         (("ASSERT", "hold_period_handbook", "3 days"), ("SUPERSEDE", "hold_period"))),
    ),
}  # fmt: skip


class LabelledWriter(ScriptedAccountingReasoner):
    """The scripted Larkspur writer under any concern labels and predicate spellings."""

    def __init__(
        self,
        script: dict[str, tuple[Prop, ...]],
        labels: dict[str, str] | None = None,
        rename: Any = None,
    ) -> None:
        super().__init__("", [])
        self.script = script
        self.labels = labels or {}
        self.rename = rename or (lambda p: p)
        self.by_evidence = {f"EV-{s.step_id}": s for s in SCENARIO.steps}

    def propose_accounted(self, request: ReasoningRequest) -> AccountedProposal:
        (item,) = request.evidence
        step = self.by_evidence[item.evidence_id]
        self.subject = self.labels.get(step.concern, step.concern)
        if any(k is JudgmentKind.CREATE_ADDRESS for k in request.allowed_judgment_kinds):
            return super().propose_accounted(request)
        by_predicate = {c.predicate: c for c in request.known_claims}
        conflicts: list[PropositionConflict] = []
        clean: list[Prop] = []
        for pid, numbers, statement, drafts in self.script[step.step_id]:
            kept: list[tuple[str, ...]] = []
            for d in drafts:
                if d[0] == "CONFLICT_CLAIM":
                    conflicts.append(
                        PropositionConflict(
                            proposition_id=pid,
                            with_claim_id=by_predicate[self.rename(d[1])].claim_id,
                        )
                    )
                else:
                    kept.append((d[0], self.rename(d[1]), *d[2:]))
            clean.append((pid, numbers, statement, tuple(kept)))
        self.call_2.append(tuple(clean))
        return super().propose_accounted(request).model_copy(update={"conflicts": tuple(conflicts)})


def larkspur_v5(rename: Any = None) -> AdmissionVerifierV5:
    """Scripted v5 verifier: the lost under-25 fee is NOT_COMPLETE; the handbook's replacement
    of the 2-day hold is CONFLICTING_EVIDENCE; every other replacement is SUPPORTED."""
    rename = rename or (lambda p: p)

    def answer(request: Any) -> AdmissionReportV5:
        out = []
        for p in request.propositions:
            asserted = [c.predicate for c in p.claims]
            handbook = rename("hold_period_handbook") in asserted
            lost_fee = asserted == [rename("annual_fee_v2")]
            out.append(AdmissionVerdictV5(
                proposition_id=p.proposition_id,
                completeness="NOT_COMPLETE" if lost_fee else "COMPLETE",
                consistency="NO_CONFLICT",
                replacements=tuple(
                    ReplacementVerdict(
                        claim_id=t.claim_id,
                        judgement="CONFLICTING_EVIDENCE" if handbook else "SUPPORTED_REPLACEMENT")
                    for t in request.replacement_targets if t.proposition_id == p.proposition_id
                ),
            ))  # fmt: skip
        return AdmissionReportV5(report_format=ADMISSION_REPORT_FORMAT_V5, verdicts=tuple(out))

    return AdmissionVerifierV5(answer)


def _world(policy: AdmissionPolicy | None = None) -> tuple[InMemoryEventStore, SemanticGovernor]:
    ids = count(1)
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=policy or AdmissionPolicy(canonical_facets=True, correction_sets=True),
        clock=lambda: AT,
        id_factory=lambda p: f"{p}-{next(ids):05d}",
    )
    governor.record_authority(
        authority_record("AUTH-founder", project_id=PROJECT, scope=(), subject_id="larkspur",
                         authorized_by=FOUNDER, authority=Authority.CANONICAL)
    )  # fmt: skip
    return store, governor


def _run(
    writer: Any,
    scenario: Scenario = SCENARIO,
    verifier: Any = None,
    policy: AdmissionPolicy | None = None,
) -> tuple[ScenarioRun, SemanticGovernor]:
    store, governor = _world(policy)
    run = run_scenario(scenario=scenario, store=store, governor=governor, reasoner=writer,
                       verifier=verifier or larkspur_v5(), human_actor_id=FOUNDER,
                       observed_at=AT)  # fmt: skip
    return run, governor


def _decisions(run: ScenarioRun) -> dict[str, str | None]:
    return {s.step_id: s.decision_status for s in run.steps if s.decision_status}


EXPECTED_DECISIONS = {
    "T03-loan": "AGREED", "T04-late": "AGREED", "T05-deposit": "DECLINED",
    "T06-damage": "AGREED", "T09-loan": "AGREED", "T11-membership": "AGREED",
    "T12-deposit": "NO_WORK: REFUSED (CORRECTION_DECLINED)",
}  # fmt: skip


@pytest.mark.parametrize("label", ["Loan period", "Tool loan", "Borrowing duration"])
def test_a_decision_lands_whatever_the_concern_is_called(label: str) -> None:
    run, governor = _run(LabelledWriter(FAITHFUL, {"Loan period": label}))
    t03 = next(s for s in run.steps if s.step_id == "T03-loan")
    assert t03.decision_status == "AGREED" and len(t03.decided_work_ids) == 1
    (work,) = t03.decided_work_ids
    assert governor.state().semantic.correction_sets[work].status == "AGREED"


def test_a_decision_lands_whatever_the_claims_are_called() -> None:
    def rename(p: str) -> str:
        return f"rule.{p[::-1]}"

    run, _ = _run(LabelledWriter(FAITHFUL, GROK_LABELS, rename), verifier=larkspur_v5(rename))
    assert _decisions(run) == EXPECTED_DECISIONS


def test_all_seven_founder_decisions_reach_their_intended_work_under_grok_labels() -> None:
    run, governor = _run(LabelledWriter(MISLABELLED_T07, GROK_LABELS))
    assert _decisions(run) == EXPECTED_DECISIONS
    decided = [w for s in run.steps for w in s.decided_work_ids]
    assert len(decided) == len(set(decided)) == 6, "six work items, each decided once"
    sets = governor.state().semantic.correction_sets
    assert {sets[w].status for w in decided} == {"AGREED", "DECLINED"}
    assert not [r for r in sets.values() if r.status == "PENDING"], "nothing left undecided"


def test_the_repeated_declined_change_lawfully_has_nothing_to_decide() -> None:
    run, governor = _run(LabelledWriter(FAITHFUL, GROK_LABELS))
    t12 = next(s for s in run.steps if s.step_id == "T12-deposit")
    assert t12.decision_status == "NO_WORK: REFUSED (CORRECTION_DECLINED)"
    assert t12.decided_work_ids == ()


def test_a_decision_never_lands_on_another_steps_work() -> None:
    """With no decision at T05, its correction stays PENDING; T12's DECLINE binds only to
    work T12's own evidence produced."""
    steps = tuple(
        s.model_copy(update={"decision": None}) if s.step_id == "T05-deposit" else s
        for s in SCENARIO.steps
    )
    run, governor = _run(LabelledWriter(FAITHFUL, GROK_LABELS),
                         scenario=SCENARIO.model_copy(update={"steps": steps}))  # fmt: skip
    t05 = next(s for s in run.steps if s.step_id == "T05-deposit")
    t12 = next(s for s in run.steps if s.step_id == "T12-deposit")
    sets = governor.state().semantic.correction_sets
    t05_work = [i for i, r in sets.items()
                if {governor.state().semantic.judgments[j].visible_evidence_ids
                    for j in r.member_judgment_ids} == {("EV-T05-deposit",)}]  # fmt: skip
    assert t05.decision_status is None and len(t05_work) == 1
    assert sets[t05_work[0]].status == "PENDING", "T12's decision did not land on T05's work"
    assert t05_work[0] not in t12.decided_work_ids


def test_two_candidate_work_items_are_never_guessed_between() -> None:
    from foundry.experiments.intent_engine_e2e.harness import evidence_id
    from tests.unit.test_runtime_holds import World, _a, _spec
    from tests.unit.test_semantic_admission_v5 import admission5

    w = World()
    start = w.governor.state().last_sequence
    for key, subject in (("A", "Alpha"), ("B", "Beta")):
        w.send(f"{key}-1", subject, _spec(subject, "Rule x holds."),
               (_a("p1", (1,), ("ASSERT", f"x{key}", "x")),), verifier=admission5())  # fmt: skip
        w.send(f"{key}-2", subject, _spec(subject, "Rule x is replaced."),
               (_a("p1", (1,), ("ASSERT", f"y{key}", "y"), ("SUPERSEDE", f"x{key}")),),
               verifier=admission5(), sup=f"{key}-1")  # fmt: skip
    window = tuple(w.store.load(PROJECT_RH, after_sequence=start))
    step = SCENARIO.steps[0].model_copy(update={"step_id": "A-2"})
    assert evidence_id(step) == "EV-A-2"
    with pytest.raises(RoutingAmbiguous):
        route_decision(w.governor, window, step, "AGREE", FOUNDER)
    sets = w.governor.state().semantic.correction_sets
    assert {r.status for r in sets.values()} == {"PENDING"}, "nothing was decided"


def test_correction_judgments_with_no_work_and_no_reason_stop_the_run() -> None:
    with pytest.raises(RoutingUnexplained):
        _run(LabelledWriter(FAITHFUL, GROK_LABELS),
             policy=AdmissionPolicy(canonical_facets=True, correction_sets=False))  # fmt: skip


def test_the_router_reads_no_label_or_wording() -> None:
    tree = ast.parse(Path("src/foundry/experiments/intent_engine_live_v2/harness.py").read_text())
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("subject", "facet", "predicate", "value", "statement", "concern"):
        assert forbidden not in attributes, forbidden


PROJECT_RH = "PROJ-HOLDS"


def test_two_pending_sets_from_one_steps_own_evidence_are_never_guessed_between() -> None:
    """One response correcting two concerns at once: both sets have exactly the step's
    provenance, so neither is "the" correction the founder decided. The harness refuses."""
    from foundry.domain.common import SourceKind
    from foundry.domain.evidence import evidence_item
    from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind
    from foundry.domain.semantic_judgment import (
        AssertClaimProposal,
        ReasonerFingerprint,
        SemanticJudgment,
        SupersedeProposal,
    )
    from tests.unit.test_runtime_holds import World, _a, _spec
    from tests.unit.test_semantic_admission_v5 import admission5

    w = World()
    for key, subject in (("A", "Alpha"), ("B", "Beta")):
        w.send(f"{key}-1", subject, _spec(subject, "Rule x holds."),
               (_a("p1", (1,), ("ASSERT", f"x{key}", "x")),), verifier=admission5())  # fmt: skip
    start = w.governor.state().last_sequence
    w.governor.ingest(evidence_item(
        evidence_id="EV-STEP-X", project_id=PROJECT_RH, source_kind=SourceKind.HUMAN,
        source_ref=FOUNDER, content="Both rules change.",
        observed_at=AT, scope=("library",)))  # fmt: skip
    semantic = w.governor.state().semantic
    fp = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v7")
    judgments = []
    for i, key in enumerate(("A", "B")):
        old = next(c for c in semantic.claims.values() if c.predicate == f"x{key}")
        proposals: tuple[AssertClaimProposal | SupersedeProposal, ...] = (
            AssertClaimProposal(address_id=old.address_id, predicate=f"y{key}",
                                value=ClaimValue(kind=ClaimValueKind.TEXT, text="y"),
                                evidence_ids=("EV-STEP-X",), authority=Authority.INFERRED),
            SupersedeProposal(target_judgment_id=old.created_by_judgment_id, reason="changed"),
        )  # fmt: skip
        for n, proposal in enumerate(proposals):
            judgments.append(SemanticJudgment(
                judgment_id=f"J-X-{i}-{n}", project_id=PROJECT_RH, proposal=proposal,
                visible_evidence_ids=("EV-STEP-X",), rationale="r", reasoner=fp,
                invocation_id="INV-X", proposed_at=AT))  # fmt: skip
    w.governor.submit_proposed(fp, tuple(judgments))
    window = tuple(w.store.load(PROJECT_RH, after_sequence=start))
    pending = [r for r in w.governor.state().semantic.correction_sets.values()
               if r.status == "PENDING"]  # fmt: skip
    assert len(pending) == 2
    step = SCENARIO.steps[0].model_copy(update={"step_id": "STEP-X"})
    with pytest.raises(RoutingAmbiguous):
        route_decision(w.governor, window, step, "AGREE", FOUNDER)
    assert all(r.status == "PENDING" for r in w.governor.state().semantic.correction_sets.values())


def test_work_of_foreign_provenance_is_never_decided_for_a_step() -> None:
    """One pending set in the window, but its members saw another step's evidence: it is not
    this step's work, so the harness refuses rather than decide it."""
    from tests.unit.test_runtime_holds import World, _a, _spec
    from tests.unit.test_semantic_admission_v5 import admission5

    w = World()
    w.send("A-1", "Alpha", _spec("Alpha", "Rule x holds."),
           (_a("p1", (1,), ("ASSERT", "xA", "x")),), verifier=admission5())  # fmt: skip
    start = w.governor.state().last_sequence
    w.send("A-2", "Alpha", _spec("Alpha", "Rule x is replaced."),
           (_a("p1", (1,), ("ASSERT", "yA", "y"), ("SUPERSEDE", "xA")),),
           verifier=admission5(), sup="A-1")  # fmt: skip
    window = tuple(w.store.load(PROJECT_RH, after_sequence=start))
    other_step = SCENARIO.steps[0].model_copy(update={"step_id": "B-9"})
    with pytest.raises(RoutingAmbiguous):
        route_decision(w.governor, window, other_step, "AGREE", FOUNDER)
    (only,) = w.governor.state().semantic.correction_sets.values()
    assert only.status == "PENDING"
