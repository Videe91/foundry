"""Offline adversarial proof of the governed-concern grain (IE2 v2 design §7.1.1).

What is provable offline, and proved here:

* every fixture's deciding rule is in the new contract and absent from the old one;
* the grader catches both failure directions: a concern split by dimension (OVER_SPLIT)
  and independent concerns merged by topic (UNDER_SPLIT), and passes the governed grain;
* on the RECORDED historical decisions: locus validation v2's C09 and C6 placements are
  over-splits, v1's revocation locus and v2's insurance/late-delivery separation are the
  governed grain;
* the facet screen flags every historical dimension-shaped facet and passes concern-level
  ones.

Whether the live model follows the contract is not provable offline; it belongs to a sealed
validation, which this phase does not run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    GOVERNED_CONCERN_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION,
)
from foundry.experiments.locus_formation.grain import (
    FIXTURES,
    GrainFixture,
    dimension_shaped,
    grade_grouping,
)

EXPERIMENTS = Path("docs/superpowers/experiments")
NEW = " ".join(GOVERNED_CONCERN_SYSTEM_INSTRUCTION.split())
OLD = " ".join(LOCUS_SYSTEM_INSTRUCTION.split())
ONE = [f for f in FIXTURES if f.kind == "ONE_CONCERN"]
SEPARATE = [f for f in FIXTURES if f.kind == "SEPARATE_CONCERNS"]


def _governed(fixture: GrainFixture) -> dict[str, str]:
    return {p.id: f"ADDR-{p.concern}" for p in fixture.propositions}


# --------------------------------------------------------------------------- the fixtures


def test_the_fixture_set_covers_both_failure_directions() -> None:
    assert [f.id for f in FIXTURES] == [
        "G1-JOB-CANCELLATION",
        "G2-LATE-DELIVERY-COMPENSATION",
        "G3-CREDENTIAL-REVOCATION",
        "G4-CANCELLATION-VS-AUDIT-DELETION",
        "G5-LATE-VS-DAMAGE-COMPENSATION",
        "G6-COMPENSATION-VS-SETTLEMENT",
        "G7-TWO-REFUND-CONCERNS",
    ]
    for f in ONE:
        assert len({p.concern for p in f.propositions}) == 1 and len(f.propositions) >= 3
    for f in SEPARATE:
        concerns = {p.concern for p in f.propositions}
        assert len(concerns) == 2
        assert all(sum(p.concern == c for p in f.propositions) >= 2 for c in concerns)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.id)
def test_each_fixture_is_decided_by_a_rule_the_new_contract_states(fixture: GrainFixture) -> None:
    assert fixture.rule in NEW


def test_the_old_contract_stated_neither_the_grain_nor_the_stage_rule() -> None:
    """Why v2 failed: the old prompt carried two definitions and none of the G2 rules."""
    assert "one subject and one facet (property, aspect, or question)" in OLD
    assert "one subject and the one stable question" in OLD
    for rule in {f.rule for f in FIXTURES}:
        assert rule not in OLD, rule


# --------------------------------------------------------------------------- the grader


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.id)
def test_the_governed_grain_passes(fixture: GrainFixture) -> None:
    assert grade_grouping(fixture, _governed(fixture)) == ()


@pytest.mark.parametrize("fixture", ONE, ids=lambda f: f.id)
def test_splitting_one_concern_by_dimension_is_an_over_split(fixture: GrainFixture) -> None:
    per_dimension = {p.id: f"ADDR-{p.id}" for p in fixture.propositions}
    assert any(f.startswith("OVER_SPLIT") for f in grade_grouping(fixture, per_dimension))
    last = fixture.propositions[-1].id
    only_the_new_one = {**_governed(fixture), last: "ADDR-NEW"}
    assert any(f.startswith("OVER_SPLIT") for f in grade_grouping(fixture, only_the_new_one))


@pytest.mark.parametrize("fixture", SEPARATE, ids=lambda f: f.id)
def test_merging_independent_concerns_by_topic_is_an_under_split(fixture: GrainFixture) -> None:
    one_drawer = {p.id: "ADDR-TOPIC" for p in fixture.propositions}
    findings = grade_grouping(fixture, one_drawer)
    assert any(f.startswith("UNDER_SPLIT") for f in findings)
    assert not any(f.startswith("OVER_SPLIT") for f in findings)


def test_an_unplaced_proposition_is_reported() -> None:
    fixture = FIXTURES[0]
    placement = _governed(fixture)
    del placement["H-4"]
    assert grade_grouping(fixture, placement) == ("UNPLACED: H-4",)


# --------------------------------------------------------------------------- recorded history


def _v2_ledger(ledger: str) -> dict[str, object]:
    run = json.loads((EXPERIMENTS / "2026-09-28-locus-validation-v2/run.json").read_text())
    (record,) = [r for r in run["ledgers"] if r["ledger"] == ledger]
    return record["deltas"][-1]["state_after"]["semantic"]


def _by_predicate(semantic: dict[str, object], mapping: dict[str, str]) -> dict[str, str]:
    claims = semantic["claims"]
    assert isinstance(claims, dict)
    found = {c["predicate"]: c["address_id"] for c in claims.values()}
    return {pid: found[predicate] for pid, predicate in mapping.items()}


def _facet(semantic: dict[str, object], address_id: str) -> str:
    addresses = semantic["addresses"]
    assert isinstance(addresses, dict)
    return str(addresses[address_id]["facet"])


def test_c09_as_recorded_in_locus_validation_v2_is_an_over_split() -> None:
    semantic = _v2_ledger("orion")
    placement = _by_predicate(
        semantic,
        {
            "H-1": "permitted cancellers",
            "H-2": "future execution attempts after cancellation",
            "H-3": "already-running execution attempt",
            "H-4": "repeated cancellation of an already-cancelled job",
        },
    )
    assert grade_grouping(FIXTURES[0], placement) == (
        "OVER_SPLIT: 'job cancellation' spread over 3 addresses",
    )
    assert all(dimension_shaped(_facet(semantic, a)) for a in set(placement.values()))


def test_c6_as_recorded_in_locus_validation_v2_is_an_over_split() -> None:
    semantic = _v2_ledger("core")
    placement = _by_predicate(
        semantic,
        {
            "LATE-1": "compensation for delivery later than the promised date",
            "LATE-2": "refund payment destination",
            "LATE-3": "late-delivery refund request window",
        },
    )
    assert grade_grouping(FIXTURES[1], placement) == (
        "OVER_SPLIT: 'late-delivery compensation' spread over 2 addresses",
    )
    assert all(dimension_shaped(_facet(semantic, a)) for a in set(placement.values()))


def test_v1_revocation_as_recorded_is_the_governed_grain() -> None:
    state = json.loads(
        (EXPERIMENTS / "2026-09-15-locus-validation-v1/L-alpha/state_T2.json").read_text()
    )
    semantic = state["state"]["semantic"]
    placement = _by_predicate(
        semantic,
        {
            "REV-1": "who may revoke a credential",
            "REV-2": "when revocation takes effect",
            "REV-3": "whether the client can undo revocation",
            "REV-4": "effect of a revocation received for an already-revoked credential",
        },
    )
    assert grade_grouping(FIXTURES[2], placement) == ()
    (address,) = set(placement.values())
    assert not dimension_shaped(_facet(semantic, address))


def test_v2_kept_late_delivery_and_damage_cover_apart_as_recorded() -> None:
    semantic = _v2_ledger("core")
    placement = _by_predicate(
        semantic,
        {
            "LT-1": "compensation for delivery later than the promised date",
            "DM-1": "standard cover limit against loss or damage",
        },
    )
    fixture = FIXTURES[4]
    partial = fixture.model_copy(
        update={"propositions": tuple(p for p in fixture.propositions if p.id in placement)}
    )
    assert grade_grouping(partial, placement) == ()


# --------------------------------------------------------------------------- the facet screen


@pytest.mark.parametrize(
    "facet",
    [
        "Who may cancel a job",
        "How cancellation affects execution attempts",
        "How a repeated cancellation is handled",
        "How is the sender compensated?",
        "When must a late-delivery refund be requested?",
        "How long may a refund take?",
        "Whether a revoked credential can be restored",
    ],
)
def test_dimension_shaped_facets_are_flagged(facet: str) -> None:
    assert dimension_shaped(facet)


@pytest.mark.parametrize(
    "facet",
    [
        "What governs job cancellation?",
        "What governs late-delivery compensation?",
        "What are the rules of revocation?",
        "What rules govern supplier overpayment refunds?",
        "What cover is provided?",
    ],
)
def test_concern_level_facets_pass_the_screen(facet: str) -> None:
    assert not dimension_shaped(facet)
