"""The v4 structural evaluator, proven on the real two-call pipeline.

A scripted oracle plays the canonical-facet policy through ``assimilate_delta`` and a
governor under ``AdmissionPolicy(canonical_facets=True)``: perfectly, or with one named
fault. The lawful play must pass every case and
every integrity check; each fault must fail exactly the case(s) it breaks, with the matching
finding tag. Faults cover both directions of the grain: splitting one governed concern
(9P3 C09 arms F and A, validation v2's C7 T1 split and C6 deadline address, a dimension split
in the model-formed large world) and merging separate ones (the four nearby pairs).
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count

import pytest

from foundry.experiments.locus_validation_v4.evaluation import evaluate, split_tally
from foundry.experiments.locus_validation_v4.expectations import CASES
from foundry.experiments.locus_validation_v4.runner import RunRecord, run_validation
from tests.unit._locus_v4_oracle import Oracle

CASE_IDS = tuple(c.id for c in CASES)


def _run(*faults: str) -> RunRecord:
    ids = count(1)
    return run_validation(
        inner=Oracle(*faults),
        guard_identity=False,
        clock=lambda: datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
    )


def _failing(run: RunRecord) -> dict[str, tuple[str, ...]]:
    return {k: r.findings for k, r in evaluate(run).items() if not r.passed}


def test_the_lawful_play_passes_every_case_and_every_integrity_check() -> None:
    run = _run()
    assert run.status == "COMPLETED"
    assert run.frontier_calls == 18
    results = evaluate(run)
    assert set(CASE_IDS) <= set(results)
    assert {k for k, r in results.items() if not r.passed} == set(), {
        k: r.findings for k, r in results.items() if not r.passed
    }


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        # over-splitting one governed concern
        ("over-split", {"C2-EXTENSION": "OVER_SPLIT", "LEDGER-core": "ADDRESS_COUNT"}),
        ("h-over-split", {"C7-C09-REGRESSION": "OVER_SPLIT", "LEDGER-orion": "ADDRESS_COUNT"}),
        ("h-t1-split", {"C7-C09-REGRESSION": "OVER_SPLIT", "LEDGER-orion": "ADDRESS_COUNT"}),
        (
            "late-deadline-split",
            {"C6-LATE-DELIVERY": "OVER_SPLIT", "LEDGER-core": "ADDRESS_COUNT"},
        ),
        ("payout-split", {"C8-LARGE-WORLD": "OVER_SPLIT", "LEDGER-large": "ADDRESS_COUNT"}),
        # under-splitting (merging) separate governed concerns
        (
            "late-damage-merge",
            {
                "C6-LATE-DELIVERY": "UNDER_SPLIT",
                "U2-LATE-VS-DAMAGE": "UNDER_SPLIT",
                "LEDGER-core": "ADDRESS_COUNT",
            },
        ),
        (
            "settlement-merge",
            {
                "C6-LATE-DELIVERY": "UNDER_SPLIT",
                "U3-COMPENSATION-VS-SETTLEMENT": "UNDER_SPLIT",
                "LEDGER-core": "ADDRESS_COUNT",
            },
        ),
        ("audit-merge", {"U1-CANCEL-VS-AUDIT": "UNDER_SPLIT", "LEDGER-jobs": "ADDRESS_COUNT"}),
        (
            "supplier-merge",
            {
                "U4-CUSTOMER-VS-SUPPLIER-REFUND": "UNDER_SPLIT",
                "C8-LARGE-WORLD": "CLAIM_COUNT",
                "LEDGER-large": "ADDRESS_COUNT",
            },
        ),
        # binding to a nearby but different concern
        ("wrong-bind", {"C6-LATE-DELIVERY": "WRONG_BIND", "U2-LATE-VS-DAMAGE": "CLAIM_COUNT"}),
        (
            "settlement-bind",
            {"C6-LATE-DELIVERY": "WRONG_BIND", "U3-COMPENSATION-VS-SETTLEMENT": "CLAIM_COUNT"},
        ),
        ("cancel-note-to-audit", {"U1-CANCEL-VS-AUDIT": "WRONG_BIND"}),
        ("large-wrong-bind", {"C8-LARGE-WORLD": "WRONG_BIND"}),
        ("misbind-only", {"C2-EXTENSION": "MISSING_BIND"}),
        ("misplaced-support", {"C1-RESTATEMENT": "WRONG_BIND"}),
        # claims, supports, supersessions and conflicts
        ("missing-extension", {"C2-EXTENSION": "MISSING_EXTENSION"}),
        ("h-missing-extension", {"C7-C09-REGRESSION": "MISSING_EXTENSION"}),
        ("duplicate-assert", {"C1-RESTATEMENT": "DUPLICATE_ASSERTION"}),
        ("missing-support", {"C1-RESTATEMENT": "MISSING_SUPPORT"}),
        ("h-missing-support", {"C7-C09-REGRESSION": "MISSING_SUPPORT"}),
        ("extra-claim", {"C0-CORE-SEED": "CLAIM_COUNT", "C1-RESTATEMENT": "CLAIM_COUNT"}),
        ("missing-supersede", {"C4-CORRECTION": "MISSING_SUPERSEDE"}),
        ("wrong-supersede-target", {"C4-CORRECTION": "WRONG_SUPERSEDE_TARGET"}),
        ("conflict-instead", {"C4-CORRECTION": "CONFLICT_INSTEAD_OF_CORRECTION"}),
        ("h-supersede", {"C7-C09-REGRESSION": "UNEXPECTED_SUPERSEDE"}),
        ("missing-conflict", {"C5-EXISTING-CONFLICT": "MISSING_CONFLICT"}),
        ("fabricated-supersede", {"C5-EXISTING-CONFLICT": "FABRICATED_SUPERSEDE"}),
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
        clock=lambda: datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
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
    delta = run.ledgers[4].deltas[1]
    rejected = (delta.call_2[0].model_copy(update={"route": "REJECT"}),)
    deltas = (run.ledgers[4].deltas[0], delta.model_copy(update={"call_2": rejected}))
    run = _tampered_ledger(run, 4, deltas=deltas)
    assert any(f.startswith("REJECTED_ADMISSION") for f in _failing(run)["LEDGER-large"])


def test_a_seeded_claim_that_stops_being_live_fails_its_case() -> None:
    """The preregistered end state: both conflicting claims must still be live after T2."""
    run = _run()
    ledger = run.ledgers[3]
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
    run = _tampered_ledger(run, 3, deltas=(ledger.deltas[0], delta))
    assert any(f.startswith("CLAIM_COUNT") for f in _failing(run)["C5-EXISTING-CONFLICT"])


def test_the_split_tally_counts_both_directions() -> None:
    over = split_tally(evaluate(_run("h-over-split")))
    under = split_tally(evaluate(_run("audit-merge")))
    assert over["OVER_SPLIT"] >= 1 and over["UNDER_SPLIT"] == 0
    assert under["UNDER_SPLIT"] >= 1 and under["OVER_SPLIT"] == 0
    assert split_tally(evaluate(_run())) == {"OVER_SPLIT": 0, "UNDER_SPLIT": 0}


@pytest.mark.parametrize(
    ("fault", "case"),
    [
        ("audit-merge", "U1-CANCEL-VS-AUDIT"),
        ("late-damage-merge", "U2-LATE-VS-DAMAGE"),
        ("settlement-merge", "U3-COMPENSATION-VS-SETTLEMENT"),
        ("supplier-merge", "U4-CUSTOMER-VS-SUPPLIER-REFUND"),
    ],
)
def test_a_merged_pair_is_reported_as_one_address(fault: str, case: str) -> None:
    findings = _failing(_run(fault))[case]
    assert any(f.startswith("UNDER_SPLIT") and "not two distinct addresses" in f for f in findings)


# ------------------------------------------------------------------ what the ranges delegate


def test_a_dropped_proposition_inside_its_range_is_left_to_the_adjudicator() -> None:
    """Ranges allow one claim to state two propositions, so dropping one of a document's
    two is not a structural finding; Q-T1-PICKUP (every proposition stated) owns it."""
    assert _failing(_run("missing-claim")) == {}


def test_c09_with_one_claim_stating_both_repeat_propositions_passes_structurally() -> None:
    """v3's live shape: H-4 and H-5 in one claim is lawful; Q-T2-H judges its content."""
    assert _failing(_run("h-merged-ack")) == {}


# ------------------------------------------------------------------ canonical facets


def _tamper_address_facet(run: RunRecord, index: int, t: int, facet: str) -> RunRecord:
    ledger = run.ledgers[index]
    delta = ledger.deltas[t - 1]
    semantic = delta.state_after.semantic
    address_id = sorted(semantic.addresses)[0]
    addresses = dict(semantic.addresses)
    addresses[address_id] = addresses[address_id].model_copy(update={"facet": facet})
    state = delta.state_after.model_copy(
        update={"semantic": semantic.model_copy(update={"addresses": addresses})}
    )
    deltas = list(ledger.deltas)
    deltas[t - 1] = delta.model_copy(update={"state_after": state})
    return _tampered_ledger(run, index, deltas=tuple(deltas))


@pytest.mark.parametrize(
    "facet",
    [
        "Sender refund entitlement",
        "How it is governed",
        "Governance",
        "Lifecycle",
        "Who may cancel a job?",
        "How cancellation affects execution attempts",
    ],
)
def test_a_historical_bad_facet_in_state_fails_the_facet_check(facet: str) -> None:
    failing = _failing(_tamper_address_facet(_run(), 0, 1, facet))
    findings = failing["CANONICAL-FACETS"]
    assert any(f.startswith("NON_CANONICAL_FACET") for f in findings)
    assert any(f.startswith("BANNED_FACET") for f in findings)


def test_two_addresses_with_one_facet_fail_the_facet_check() -> None:
    run = _run()
    ledger = run.ledgers[0]
    delta = ledger.deltas[0]
    semantic = delta.state_after.semantic
    first, second = sorted(semantic.addresses)[:2]
    addresses = dict(semantic.addresses)
    addresses[second] = addresses[second].model_copy(
        update={"subject": addresses[first].subject, "facet": addresses[first].facet}
    )
    state = delta.state_after.model_copy(
        update={"semantic": semantic.model_copy(update={"addresses": addresses})}
    )
    run = _tampered_ledger(
        run,
        0,
        deltas=(delta.model_copy(update={"state_after": state}), *ledger.deltas[1:]),
    )
    assert any(f.startswith("FACET_COLLISION") for f in _failing(run)["CANONICAL-FACETS"])


def test_a_model_payload_carrying_a_facet_fails_the_facet_check() -> None:
    run = _run()
    calls = list(run.ledgers[0].calls)
    calls[0] = calls[0].model_copy(
        update={"model_payload": {"drafts": [{"kind": "CREATE_ADDRESS", "facet": "Governance"}]}}
    )
    run = _tampered_ledger(run, 0, calls=tuple(calls))
    assert any(f.startswith("MODEL_FACET") for f in _failing(run)["CANONICAL-FACETS"])


def test_a_non_canonical_candidate_is_refused_at_admission_and_fails_the_run() -> None:
    """The governor refuses it (the refusal is in the event log) and the address never
    exists; the ledger cannot complete, so nothing passes."""
    run = _run("non-canonical-candidate")
    core = run.ledgers[0]
    assert any("NON_CANONICAL_FACET" in e.model_dump_json() for e in core.events)
    assert not any('"How it is governed"' in e.model_dump_json() for e in core.events
                   if "ADDRESS_CREATED" in e.model_dump_json())  # fmt: skip
    results = evaluate(run)
    assert not results["RUN-INTEGRITY"].passed
    assert all(not results[c].passed for c in CASE_IDS if c != "C5-EXISTING-CONFLICT")


def test_a_non_canonical_bind_candidate_fails_the_facet_check() -> None:
    """A BIND candidate never becomes an address, so only the candidate check can see it."""
    run = _run()
    ledger = run.ledgers[0]
    delta = ledger.deltas[1]
    semantic = delta.state_after.semantic
    (jid, judgment) = next(
        (j, x)
        for j, x in sorted(semantic.judgments.items())
        if x.proposal.kind.value == "BIND_TO_ADDRESS"
    )
    candidate = judgment.proposal.candidate.model_copy(update={"facet": "Lifecycle"})
    proposal = judgment.proposal.model_copy(update={"candidate": candidate})
    judgments = dict(semantic.judgments)
    judgments[jid] = judgment.model_copy(update={"proposal": proposal})
    state = delta.state_after.model_copy(
        update={"semantic": semantic.model_copy(update={"judgments": judgments})}
    )
    run = _tampered_ledger(
        run, 0, deltas=(ledger.deltas[0], delta.model_copy(update={"state_after": state}))
    )
    findings = _failing(run)["CANONICAL-FACETS"]
    assert any(f.startswith("NON_CANONICAL_FACET") and "candidate" in f for f in findings)


# ------------------------------------------------------------------ source coverage


def test_an_incomplete_source_coverage_map_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from foundry.experiments.locus_validation_v4 import expectations

    gapped = dict(expectations.SOURCE_COVERAGE)
    gapped["H-T9"] = tuple(a for a in gapped["H-T9"] if "acknowledged" not in a.sentence)
    monkeypatch.setattr(expectations, "SOURCE_COVERAGE", gapped)
    findings = _failing(_run())["SOURCE-COVERAGE"]
    assert any("simply acknowledged" in f for f in findings)
    assert any("UNSOURCED_PROPOSITION: H-5" in f for f in findings)
