"""End-to-end Intent Engine validation: the final-outcome scorer (offline, no model).

Only final outcomes are scored: missing, invented, wrong or stale truth; a correction that
retired the wrong truth; contradictory current truths left implicit; authority bypassed; a
declined change applied; a silent gap; IE3 inconsistent with IE2; incorrect closure. Which
claim states which expected truth is the adjudicator's answer, never deterministic text
matching, so wording, decomposition and explanations can never change a score.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from foundry.experiments.intent_engine_e2e.expectations import (
    EXPECTED,
    ExpectedCorrection,
    ExpectedOutcome,
    ExpectedTruth,
)
from foundry.experiments.intent_engine_e2e.outcome import (
    Adjudication,
    ClaimReading,
    ClaimView,
    CompletenessView,
    CorrectionSetView,
    DefectCategory,
    FinalOutcome,
    GapView,
    GraphObjectView,
    InvalidAdjudication,
    adjudication_packet,
    score,
)

D = DefectCategory
EXP = ExpectedOutcome(
    scenario_id="mini",
    truths=(
        ExpectedTruth(truth_id="A", concern="c", statement="a holds", final="CURRENT"),
        ExpectedTruth(truth_id="B", concern="c", statement="b held", final="RETIRED"),
        ExpectedTruth(truth_id="N", concern="c", statement="n declined", final="NEVER"),
        ExpectedTruth(truth_id="K1", concern="k", statement="k is 2", final="CONTESTED"),
        ExpectedTruth(truth_id="K2", concern="k", statement="k is 3", final="CONTESTED"),
    ),
    corrections=(
        ExpectedCorrection(correction_id="C1", step_id="S2", cardinality="1:1", retires=("B",),
                           introduces=("A",), decision="AGREE"),
        ExpectedCorrection(correction_id="C2", step_id="S3", cardinality="1:1", retires=("A",),
                           introduces=("N",), decision="DECLINE"),
    ),
    contested_pairs=(("K1", "K2"),),
    open_blocking_gaps=0,
)  # fmt: skip


def _claim(cid: str, *, current: bool = True, by: str = "", pred: str = "p") -> ClaimView:
    return ClaimView(
        claim_id=cid,
        subject="c",
        predicate=pred,
        value=f"value of {cid}",
        current=current,
        created_by=by or f"J-{cid}",
    )


def _baseline() -> tuple[FinalOutcome, Adjudication]:
    outcome = FinalOutcome(
        scenario_id="mini",
        claims=(
            _claim("c-a"),
            _claim("c-b", current=False),
            _claim("c-k1"),
            _claim("c-k2"),
        ),
        applied_judgment_ids=("J-c-a", "J-c-b", "J-c-k1", "J-c-k2", "J-sup"),
        applied_supersedes=(("J-sup", False),),
        correction_sets=(
            CorrectionSetView(
                correction_set_id="CS1",
                subject="c",
                status="AGREED",
                member_judgment_ids=("J-c-a", "J-sup"),
                target_judgment_ids=("J-c-b",),
            ),
            CorrectionSetView(
                correction_set_id="CS2",
                subject="c",
                status="DECLINED",
                member_judgment_ids=("J-n", "J-sup-2"),
                target_judgment_ids=("J-c-a",),
            ),
        ),
        completeness=(
            CompletenessView(
                verification_id="VER-1",
                policy_version="ie2-semantic-completeness-v3",
                outcome="FAIL",
                held_proposition_ids=("p1",),
                gap_ids=("G1",),
            ),
        ),
        gaps=(GapView(gap_id="G1", status="RESOLVED", blocking=True),),
        explicit_conflicts=(("c-k1", "c-k2"),),
        graph=(
            GraphObjectView(object_id="g1", current=True, derived_from=("c-a", "c-k1", "c-k2")),
            GraphObjectView(object_id="g0", current=False, derived_from=("c-b",)),
        ),
        ie3_evaluated=True,
        closure_gap_blockers=(),
        refused_steps=(),
    )
    adjudication = Adjudication(
        readings=(
            ClaimReading(claim_id="c-a", truth_id="A", faithful=True),
            ClaimReading(claim_id="c-b", truth_id="B", faithful=True),
            ClaimReading(claim_id="c-k1", truth_id="K1", faithful=True),
            ClaimReading(claim_id="c-k2", truth_id="K2", faithful=True),
        ),
        contradictions=(("c-k2", "c-k1"),),
    )
    return outcome, adjudication


def _categories(outcome: FinalOutcome, adjudication: Adjudication) -> set[DefectCategory]:
    return {d.category for d in score(outcome, EXP, adjudication).defects}


def test_a_faithful_final_state_passes_with_no_defect() -> None:
    report = score(*_baseline()[:1], EXP, _baseline()[1])
    assert report.defects == () and report.verdict == "PASS"
    assert set(report.counts) == {c.value for c in DefectCategory}
    assert all(n == 0 for n in report.counts.values())


def test_without_ie3_a_clean_ie2_state_is_incomplete_never_pass() -> None:
    outcome, adjudication = _baseline()
    report = score(outcome.model_copy(update={"ie3_evaluated": False, "graph": ()}), EXP,
                   adjudication)  # fmt: skip
    assert report.defects == () and report.verdict == "INCOMPLETE"


def _drop(outcome: FinalOutcome, adj: Adjudication, cid: str) -> tuple[FinalOutcome, Adjudication]:
    return (
        outcome.model_copy(
            update={
                "claims": tuple(c for c in outcome.claims if c.claim_id != cid),
                "graph": tuple(
                    g.model_copy(
                        update={"derived_from": tuple(x for x in g.derived_from if x != cid)}
                    )
                    for g in outcome.graph
                ),
            }
        ),
        adj.model_copy(
            update={
                "readings": tuple(r for r in adj.readings if r.claim_id != cid),
                "contradictions": tuple(p for p in adj.contradictions if cid not in p),
            }
        ),
    )


def _reading(adj: Adjudication, cid: str, **change: object) -> Adjudication:
    return adj.model_copy(
        update={
            "readings": tuple(
                r.model_copy(update=change) if r.claim_id == cid else r for r in adj.readings
            )
        }
    )


def _claims(outcome: FinalOutcome, cid: str, **change: object) -> FinalOutcome:
    return outcome.model_copy(
        update={
            "claims": tuple(
                c.model_copy(update=change) if c.claim_id == cid else c for c in outcome.claims
            )
        }
    )


def _sets(outcome: FinalOutcome, set_id: str, **change: object) -> FinalOutcome:
    return outcome.model_copy(
        update={
            "correction_sets": tuple(
                s.model_copy(update=change) if s.correction_set_id == set_id else s
                for s in outcome.correction_sets
            )
        }
    )


def _graph(outcome: FinalOutcome, *derived: str) -> FinalOutcome:
    return outcome.model_copy(
        update={
            "graph": (
                GraphObjectView(object_id="g1", current=True, derived_from=derived),
                *outcome.graph[1:],
            )
        }
    )


def _with_claim(
    outcome: FinalOutcome, adj: Adjudication, cid: str, truth: str | None
) -> tuple[FinalOutcome, Adjudication]:
    return (
        _graph(
            outcome.model_copy(update={"claims": (*outcome.claims, _claim(cid))}),
            "c-a", "c-k1", "c-k2", cid,
        ),
        adj.model_copy(
            update={
                "readings": (
                    *adj.readings,
                    ClaimReading(claim_id=cid, truth_id=truth, faithful=True),
                )
            }
        ),
    )  # fmt: skip


Case = Callable[[FinalOutcome, Adjudication], tuple[FinalOutcome, Adjudication]]
CASES: dict[str, tuple[Case, set[DefectCategory]]] = {
    "missing": (lambda o, a: _drop(o, a, "c-a"), {D.MISSING_TRUTH}),
    "invented": (lambda o, a: _with_claim(o, a, "c-x", None), {D.INVENTED_TRUTH}),
    "wrong": (lambda o, a: (o, _reading(a, "c-a", faithful=False)), {D.WRONG_TRUTH}),
    "stale": (
        lambda o, a: (_graph(_claims(o, "c-b", current=True), "c-a", "c-k1", "c-k2", "c-b"), a),
        {D.STALE_TRUTH},
    ),
    "wrong-target": (
        lambda o, a: (_graph(_claims(o, "c-a", current=False), "c-k1", "c-k2"), a),
        {D.WRONG_CORRECTION_TARGET},
    ),
    "contradiction-implicit": (
        lambda o, a: (o.model_copy(update={"explicit_conflicts": ()}), a),
        {D.CONTRADICTORY_CURRENT_TRUTHS},
    ),
    "contested-side-lost": (lambda o, a: _drop(o, a, "c-k2"), {D.MISSING_TRUTH}),
    "pending-set-applied": (
        lambda o, a: (_sets(o, "CS1", status="PENDING"), a),
        {D.AUTHORITY_BYPASSED},
    ),
    "supersede-outside-any-agreed-set": (
        lambda o, a: (o.model_copy(update={"applied_supersedes": (("J-sup-x", False),)}), a),
        {D.AUTHORITY_BYPASSED},
    ),
    "declined-member-applied": (
        lambda o, a: (
            o.model_copy(update={"applied_judgment_ids": (*o.applied_judgment_ids, "J-n")}),
            a,
        ),
        {D.DECLINED_CHANGE_APPLIED},
    ),
    "declined-truth-current": (
        lambda o, a: _with_claim(o, a, "c-n", "N"),
        {D.DECLINED_CHANGE_APPLIED},
    ),
    "gap-not-recorded": (
        lambda o, a: (
            o.model_copy(
                update={"completeness": (o.completeness[0].model_copy(update={"gap_ids": ()}),)}
            ),
            a,
        ),
        {D.SILENT_GAP},
    ),
    "gap-id-unknown": (
        lambda o, a: (o.model_copy(update={"gaps": ()}), a),
        {D.SILENT_GAP},
    ),
    "step-refused-without-trace": (
        lambda o, a: (o.model_copy(update={"refused_steps": ("S9",)}), a),
        {D.SILENT_GAP},
    ),
    "ie3-derived-from-retired": (
        lambda o, a: (_graph(o, "c-a", "c-k1", "c-k2", "c-b"), a),
        {D.IE3_INCONSISTENT_WITH_IE2},
    ),
    "ie3-misses-a-current-claim": (
        lambda o, a: (_graph(o, "c-a", "c-k1"), a),
        {D.IE3_INCONSISTENT_WITH_IE2},
    ),
    "closure-blocked-by-an-unexpected-gap": (
        lambda o, a: (o.model_copy(update={"closure_gap_blockers": ("G1",)}), a),
        {D.INCORRECT_CLOSURE},
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_outcome_defect_is_detected_and_nothing_else(name: str) -> None:
    case, expected = CASES[name]
    outcome, adjudication = case(*_baseline())
    report = score(outcome, EXP, adjudication)
    assert {d.category for d in report.defects} == expected
    assert report.verdict == "FAIL"
    assert sum(report.counts.values()) == len(report.defects)


def test_every_defect_category_is_reachable() -> None:
    assert set().union(*(e for _, e in CASES.values())) == set(DefectCategory)


def test_wording_and_decomposition_never_change_the_score() -> None:
    outcome, adjudication = _baseline()
    reworded = outcome.model_copy(
        update={
            "claims": tuple(
                c.model_copy(update={"predicate": f"x_{i}", "value": "entirely other words",
                                     "subject": "another subject"})
                for i, c in enumerate(outcome.claims)
            )
        }
    )  # fmt: skip
    assert score(reworded, EXP, adjudication) == score(outcome, EXP, adjudication)
    split = _with_claim(outcome, adjudication, "c-a2", "A")  # A stated by two claims
    assert score(*split[:1], EXP, split[1]).defects == ()


@pytest.mark.parametrize(
    "broken",
    [
        lambda a: a.model_copy(update={"readings": a.readings[1:]}),
        lambda a: a.model_copy(update={"readings": (*a.readings, a.readings[0])}),
        lambda a: _reading(a, "c-a", truth_id="Z"),
        lambda a: a.model_copy(update={"readings": (*a.readings, ClaimReading(
            claim_id="c-ghost", truth_id="A", faithful=True))}),
        lambda a: a.model_copy(update={"contradictions": (("c-a", "c-b"),)}),
    ],
)  # fmt: skip
def test_an_adjudication_that_does_not_cover_the_state_is_refused(
    broken: Callable[[Adjudication], Adjudication],
) -> None:
    outcome, adjudication = _baseline()
    with pytest.raises(InvalidAdjudication):
        score(outcome, EXP, broken(adjudication))


def test_the_adjudication_packet_shows_truths_and_claims_never_the_expected_status() -> None:
    outcome, _ = _baseline()
    packet = adjudication_packet(outcome, EXP)
    assert [t.truth_id for t in packet.truths] == ["A", "B", "N", "K1", "K2"]
    assert {c.claim_id for c in packet.claims} == {"c-a", "c-b", "c-k1", "c-k2"}
    dumped = packet.model_dump_json()
    for status in ("CURRENT", "RETIRED", "NEVER", "CONTESTED", "AGREE", "DECLINE"):
        assert status not in dumped, status


def test_the_held_out_expectations_are_well_formed() -> None:
    ids = [t.truth_id for t in EXPECTED.truths]
    assert len(ids) == len(set(ids))
    for c in EXPECTED.corrections:
        assert set(c.retires) | set(c.introduces) <= set(ids)
    assert {c.cardinality for c in EXPECTED.corrections} == {"1:1", "N:1", "1:N", "N:M"}
    assert {c.decision for c in EXPECTED.corrections} == {"AGREE", "DECLINE"}
    final = {t.truth_id: t.final for t in EXPECTED.truths}
    for c in EXPECTED.corrections:
        if c.decision == "DECLINE":
            assert {final[t] for t in c.introduces} == {"NEVER"}
            assert {final[t] for t in c.retires} <= {"CURRENT", "CONTESTED"}
    for a, b in EXPECTED.contested_pairs:
        assert final[a] == final[b] == "CONTESTED"
