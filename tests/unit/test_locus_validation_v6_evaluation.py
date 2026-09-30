"""The v6 structural evaluator and harness, proven on the real two-call pipeline.

A scripted oracle plays ``intent-v2-locus-v6`` through ``assimilate_delta`` and governors under
``AdmissionPolicy(canonical_facets=True, correction_sets=True)``: lawfully, or with one named
fault. The lawful play must pass every case and every integrity check, including the dense
formation, the four correction cardinalities, atomic AGREE and DECLINE by the scripted human,
the suppressed repeat and the reopened changed basis. Each fault must fail the case it breaks
with the matching finding tag. Nothing here calls a model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count

import pytest

from foundry.experiments.locus_validation_v6.evaluation import evaluate, split_tally
from foundry.experiments.locus_validation_v6.expectations import CASES
from foundry.experiments.locus_validation_v6.runner import RunRecord, run_validation
from tests.unit._locus_v6_oracle import Oracle

_RUNS: dict[tuple[str, ...], RunRecord] = {}


def run_of(*faults: str) -> RunRecord:
    if faults not in _RUNS:
        ids = count(1)
        _RUNS[faults] = run_validation(
            inner=Oracle(*faults),
            guard_identity=False,
            clock=lambda: datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
            id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
        )
    return _RUNS[faults]


def _failing(run: RunRecord) -> dict[str, tuple[str, ...]]:
    return {k: r.findings for k, r in evaluate(run).items() if not r.passed}


def test_the_lawful_play_passes_every_case_and_every_check() -> None:
    run = run_of()
    assert run.status == "COMPLETED"
    assert run.frontier_calls == 26
    results = evaluate(run)
    assert {c.id for c in CASES} <= set(results)
    assert _failing(run) == {}
    assert split_tally(results) == {"OVER_SPLIT": 0, "UNDER_SPLIT": 0}


def test_the_dense_ledger_branches_after_t2_and_runs_t3_in_each_branch() -> None:
    (dense,) = [lg for lg in run_of().ledgers if lg.ledger == "dense"]
    assert [d.t for d in dense.deltas] == [1, 2]
    assert [b.branch for b in dense.branches] == ["AGREE", "DECLINE"]
    for branch in dense.branches:
        assert len(branch.decisions) == 4
        assert {d.outcome for d in branch.decisions} == {branch.branch}
        assert branch.t3 is not None and branch.replay_matches is True
    assert [c.t for c in dense.calls].count(3) == 4


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        # dense formation: section grain, merges and splits
        ("section-grain", {"D0-DENSE-FORMATION": "OVER_SPLIT", "LEDGER-dense": "ADDRESS_COUNT"}),
        ("late-clean-merge", {"S1-LATE-VS-CLEANING": "UNDER_SPLIT"}),
        ("reservation-unlock-merge", {"S4-RESERVATION-VS-UNLOCK": "UNDER_SPLIT"}),
        ("unlock-timeout-split", {"D2-UNLOCK-ATTEMPTS-ONE-CONCERN": "OVER_SPLIT"}),
        ("late-waiver-split", {"D3-LATE-FEE-ONE-CONCERN": "OVER_SPLIT"}),
        # carried regressions
        ("h-over-split", {"C7-C09-REGRESSION": "OVER_SPLIT"}),
        ("late-deadline-split", {"C6-LATE-DELIVERY": "OVER_SPLIT"}),
        ("late-damage-merge", {"U2-LATE-VS-DAMAGE": "UNDER_SPLIT"}),
        # accounting, correction cardinality and facets
        ("drop-proposition", {"PROPOSITION-ACCOUNTING": "ACCOUNTING_RECOMPUTED"}),
        ("one-target-only", {"X4-MANY-TO-MANY": "MISSING_TARGET"}),
        ("non-canonical-candidate", {"CANONICAL-FACETS": "NON_CANONICAL_FACET"}),
    ],
)
def test_each_fault_fails_the_case_it_breaks(fault: str, expected: dict[str, str]) -> None:
    failing = _failing(run_of(fault))
    for case, tag in expected.items():
        assert case in failing, (fault, sorted(failing))
        assert any(f.startswith(f"{tag}:") for f in failing[case]), (fault, failing[case])


def test_the_one_target_only_fault_leaves_an_obsolete_claim_live_after_agree() -> None:
    """Its repeat at T3 is the same one-target set on the same basis, so it is suppressed; what
    the fault breaks is AGREE: the untargeted old wait claim stays current beside the new."""
    failing = _failing(run_of("one-target-only"))
    assert any(f.startswith("CLAIM_COUNT:") for f in failing.get("Z2-AGREE", ()))


def test_a_run_that_never_ran_the_dense_ledger_fails_integrity() -> None:
    run = run_of()
    truncated = run.model_copy(update={"ledgers": run.ledgers[:-1]})
    failing = _failing(truncated)
    assert any(f.startswith("ABORTED:") for f in failing["RUN-INTEGRITY"])


def test_a_new_set_after_decline_is_reopened_work_even_when_every_repeat_was_refused() -> None:
    """Doctor the frozen T3-DECLINE state: one PENDING set at the unlock address that the
    listed drafts did not make. The drafts are all refused as declined repeats, so only the
    new-work law can see it."""
    run = run_of()
    (dense,) = [lg for lg in run.ledgers if lg.ledger == "dense"]
    (decline,) = [b for b in dense.branches if b.branch == "DECLINE"]
    assert decline.t3 is not None
    semantic = decline.t3.state_after.semantic
    unlock = next(
        r
        for r in semantic.correction_sets.values()
        if len(r.assertion_judgment_ids) == 3 and r.status == "DECLINED"
    )
    reopened = unlock.model_copy(
        update={
            "correction_set_id": "CSET-DOCTORED",
            "status": "PENDING",
            "decided_by": None,
            "decision_event_id": None,
            "authority_record_id": None,
            "rationale": None,
        }
    )
    doctored_semantic = semantic.model_copy(
        update={"correction_sets": {**semantic.correction_sets, "CSET-DOCTORED": reopened}}
    )
    state = decline.t3.state_after.model_copy(update={"semantic": doctored_semantic})
    t3 = decline.t3.model_copy(update={"state_after": state})
    branches = tuple(
        b.model_copy(update={"t3": t3}) if b.branch == "DECLINE" else b for b in dense.branches
    )
    doctored = run.model_copy(
        update={
            "ledgers": tuple(
                lg.model_copy(update={"branches": branches}) if lg.ledger == "dense" else lg
                for lg in run.ledgers
            )
        }
    )
    failing = _failing(doctored)
    assert any(f.startswith("REOPENED:") for f in failing["Z4-REPEAT-SUPPRESSED"])
