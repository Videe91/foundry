"""The v2 structural evaluator, proven on the real two-call pipeline.

A scripted oracle plays the locus policy through ``assimilate_delta`` and the real
governor: perfectly, or with one named fault. The lawful play must pass every case and
every integrity check; each fault must fail exactly the case(s) it breaks, with the
matching finding tag. Several faults are the historical failures: 9P3 C09's arm F
(``h-over-split``), arm A (``h-missing-extension``), and v1's granularity shape
(``extra-claim``, ``missing-claim``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count

import pytest

from foundry.experiments.locus_validation_v2.evaluation import evaluate
from foundry.experiments.locus_validation_v2.expectations import CASES
from foundry.experiments.locus_validation_v2.runner import RunRecord, run_validation
from tests.unit._locus_v2_oracle import Oracle

CASE_IDS = tuple(c.id for c in CASES)


def _run(*faults: str) -> RunRecord:
    ids = count(1)
    return run_validation(
        inner=Oracle(*faults),
        guard_identity=False,
        clock=lambda: datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
    )


def _failing(run: RunRecord) -> dict[str, tuple[str, ...]]:
    return {k: r.findings for k, r in evaluate(run).items() if not r.passed}


def test_the_lawful_play_passes_every_case_and_every_integrity_check() -> None:
    run = _run()
    assert run.status == "COMPLETED"
    assert run.frontier_calls == 12
    results = evaluate(run)
    assert set(CASE_IDS) <= set(results)
    assert {k for k, r in results.items() if not r.passed} == set(), {
        k: r.findings for k, r in results.items() if not r.passed
    }


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("over-split", {"C2-EXTENSION": "OVER_SPLIT", "LEDGER-core": "ADDRESS_COUNT"}),
        (
            "under-split",
            {
                "C0-CORE-SEED": "UNDER_SPLIT",
                "C6-NEARBY": "UNDER_SPLIT",
                "LEDGER-core": "ADDRESS_COUNT",
            },
        ),
        ("wrong-bind", {"C6-NEARBY": "WRONG_BIND"}),
        ("missing-extension", {"C2-EXTENSION": "MISSING_EXTENSION"}),
        ("h-missing-extension", {"C7-C09-REGRESSION": "MISSING_EXTENSION"}),
        (
            "h-over-split",
            {"C7-C09-REGRESSION": "OVER_SPLIT", "LEDGER-orion": "ADDRESS_COUNT"},
        ),
        ("duplicate-assert", {"C1-RESTATEMENT": "DUPLICATE_ASSERTION"}),
        ("missing-support", {"C1-RESTATEMENT": "MISSING_SUPPORT"}),
        ("missing-claim", {"C0-CORE-SEED": "CLAIM_COUNT", "C1-RESTATEMENT": "CLAIM_COUNT"}),
        ("extra-claim", {"C0-CORE-SEED": "CLAIM_COUNT", "C1-RESTATEMENT": "CLAIM_COUNT"}),
        ("missing-supersede", {"C4-CORRECTION": "MISSING_SUPERSEDE"}),
        ("wrong-supersede-target", {"C4-CORRECTION": "WRONG_SUPERSEDE_TARGET"}),
        ("conflict-instead", {"C4-CORRECTION": "CONFLICT_INSTEAD_OF_CORRECTION"}),
        ("missing-conflict", {"C5-EXISTING-CONFLICT": "MISSING_CONFLICT"}),
        ("fabricated-supersede", {"C5-EXISTING-CONFLICT": "FABRICATED_SUPERSEDE"}),
        ("large-wrong-bind", {"C8-LARGE-WORLD": "WRONG_BIND"}),
        ("misbind-only", {"C2-EXTENSION": "MISSING_BIND"}),
        ("misplaced-support", {"C1-RESTATEMENT": "WRONG_BIND"}),
    ],
)
def test_each_fault_fails_exactly_the_cases_it_breaks(fault: str, expected: dict[str, str]) -> None:
    run = _run(fault)
    assert run.status == "COMPLETED", run.ledgers[-1].error
    failing = _failing(run)
    assert set(failing) == set(expected), failing
    for case, tag in expected.items():
        assert any(f.startswith(tag) for f in failing[case]), (case, failing[case])


def test_a_bind_to_the_wrong_address_is_caught_even_when_the_claim_lands_right() -> None:
    """The bind law on its own: LABEL-T2 bound to PICKUP, its claim still asserted at LABEL."""
    failing = _failing(_run("misbind-only"))
    assert any(f.startswith("WRONG_BIND") for f in failing["C2-EXTENSION"])
    assert not any("new claims" in f for f in failing["C2-EXTENSION"])


def test_an_aborted_run_passes_nothing() -> None:
    class Broken(Oracle):
        def propose(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider went away")

    ids = count(1)
    run = run_validation(
        inner=Broken(),
        guard_identity=False,
        clock=lambda: datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
    )
    assert run.status == "ABORTED"
    results = evaluate(run)
    assert not results["RUN-INTEGRITY"].passed
    assert all(not results[c].passed for c in CASE_IDS)


# ------------------------------------------------------------------ integrity laws on a crafted run


def _tampered_ledger(run: RunRecord, index: int, **update: object) -> RunRecord:
    ledgers = list(run.ledgers)
    ledgers[index] = ledgers[index].model_copy(update=update)
    return run.model_copy(update={"ledgers": tuple(ledgers)})


def test_a_ledger_that_does_not_replay_fails_integrity() -> None:
    run = _tampered_ledger(_run(), 0, replay_matches=False)
    assert "RUN-INTEGRITY" in _failing(run)


def test_a_missing_call_fails_integrity() -> None:
    run = _run()
    run = _tampered_ledger(run, 1, calls=run.ledgers[1].calls[:-1])
    assert any(f.startswith("INTEGRITY") for f in _failing(run)["RUN-INTEGRITY"])


def test_a_reference_outside_its_request_fails_integrity() -> None:
    run = _run()
    calls = list(run.ledgers[0].calls)
    calls[1] = calls[1].model_copy(update={"citable_evidence_ids": ()})
    run = _tampered_ledger(run, 0, calls=tuple(calls))
    assert any("outside its request" in f for f in _failing(run)["RUN-INTEGRITY"])


def test_a_rejected_admission_fails_its_ledger() -> None:
    run = _run()
    delta = run.ledgers[3].deltas[1]
    rejected = (delta.call_2[0].model_copy(update={"route": "REJECT"}),)
    deltas = (run.ledgers[3].deltas[0], delta.model_copy(update={"call_2": rejected}))
    run = _tampered_ledger(run, 3, deltas=deltas)
    assert any(f.startswith("REJECTED_ADMISSION") for f in _failing(run)["LEDGER-large"])


def test_a_seeded_claim_that_stops_being_live_fails_its_case() -> None:
    """The preregistered end state: both conflicting claims must still be live after T2."""
    run = _run()
    ledger = run.ledgers[2]
    lost = ledger.seed_claim_ids["SESSION-30"]
    t2 = ledger.deltas[1].state_after
    judgment = t2.semantic.claims[lost].created_by_judgment_id
    semantic = t2.semantic.model_copy(
        update={
            "applied_judgment_ids": tuple(
                j for j in t2.semantic.applied_judgment_ids if j != judgment
            )
        }
    )
    delta = ledger.deltas[1].model_copy(
        update={"state_after": t2.model_copy(update={"semantic": semantic})}
    )
    run = _tampered_ledger(run, 2, deltas=(ledger.deltas[0], delta))
    assert any(f.startswith("CLAIM_COUNT") for f in _failing(run)["C5-EXISTING-CONFLICT"])
