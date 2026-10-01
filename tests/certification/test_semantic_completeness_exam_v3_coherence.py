"""Exam v3's semantic inventory, derived verdicts and construction coherence (offline).

Exam v2 hand-authored every expected verdict. Three of them (C02, C24, C10) contradicted the
approved verifier law ``ie2-semantic-completeness-v1`` and a fourth (C22 p2) did too without
being caught: each proposition carried an operative assertion (an actor, a time anchor) that its
claims never stated. Exam v3 therefore never authors a verdict. Every proposition carries a
scorer-side inventory of its operative assertions, each classified (represented by named
claims, missing, unsupported or contradicted) and anchored to the text it classifies; the
verdict is derived from that inventory by the sealed precedence, and a case whose inventory is
incoherent cannot be built at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import get_args

import pytest

import tests.certification._completeness_exam as v2
from foundry.adapters.semantics.completeness_verifier import COMPLETENESS_SYSTEM_INSTRUCTION
from foundry.domain.semantic_completeness import CompletenessVerdict
from tests.certification._completeness_exam import MarkerGroup, normalise
from tests.certification._completeness_exam_v3 import (
    ASSERTION_KINDS,
    CASES,
    CHANGED_FROM_V2,
    AssertionKind,
    PropositionInventory,
    added,
    case_by_id,
    clash,
    derive_verdict,
    held,
    inventory_case,
    inventory_problems,
    lost,
)

GROUP = MarkerGroup("anything", ("anything",))

INTENDED: Mapping[str, Mapping[str, CompletenessVerdict]] = {
    "C01": {"p1": "COMPLETE"},
    "C02": {"p1": "COMPLETE"},
    "C03": {"p1": "COMPLETE"},
    "C04": {"p1": "COMPLETE"},
    "C05": {"p1": "INCOMPLETE"},
    "C06": {"p1": "INCOMPLETE"},
    "C07": {"p1": "INCOMPLETE"},
    "C08": {"p1": "INCOMPLETE"},
    "C09": {"p1": "INCOMPLETE"},
    "C10": {"p1": "OVERREACH"},
    "C11": {"p1": "CONTRADICTORY"},
    "C12": {"p1": "INCOMPLETE"},
    "C13": {"p1": "COMPLETE"},
    "C14": {"p1": "COMPLETE"},
    "C15": {"p1": "INCOMPLETE"},
    "C16": {"p1": "INCOMPLETE"},
    "C17": {"p1": "COMPLETE", "p2": "CONTRADICTORY"},
    "C18": {"p1": "INCOMPLETE"},
    "C19": {"p1": "COMPLETE"},
    "C20": {"p1": "INCOMPLETE"},
    "C21": {"p1": "INCOMPLETE"},
    "C22": {"p1": "COMPLETE", "p2": "OVERREACH"},
    "C23": {"p1": "CONTRADICTORY"},
    "C24": {"p1": "COMPLETE"},
    "C25": {"p1": "COMPLETE"},
}
"""What each case is designed to test, written independently of the inventories. The derived
verdict must agree with it: two sources, and any disagreement fails the build."""

MISSING_OBLIGATIONS: Mapping[str, tuple[AssertionKind, ...]] = {
    "C05": ("ACTOR", "CONDITION"),
    "C09": ("ELIGIBILITY", "QUANTITY"),
    "C15": ("TIME_ANCHOR", "CONSEQUENCE"),
    "C16": ("ACTOR", "CONSEQUENCE"),
    "C21": ("CHANNEL", "CONSEQUENCE"),
}
"""The approved multi-gap cases: every sealed missing assertion must be found, not only the
originally designed gap."""


def _verdicts(case_id: str) -> dict[str, str]:
    return {e.proposition_id: e.verdict for e in case_by_id(case_id).expected}


# --- the inventory vocabulary -------------------------------------------------------------------


def test_the_inventory_can_represent_every_operative_kind_of_the_verifier_contract() -> None:
    required = {
        "ACTOR",
        "OBLIGATION",
        "PERMISSION",
        "QUANTITY",
        "TIMING",
        "TIME_ANCHOR",
        "DEADLINE",
        "CONDITION",
        "ELIGIBILITY",
        "CONSEQUENCE",
        "EXCEPTION",
        "DESTINATION",
        "REPETITION",
        "CHANNEL",
    }
    assert set(ASSERTION_KINDS) == required == set(get_args(AssertionKind))
    # the production contract these mirror is unchanged and names them
    for word in ("an actor", "an obligation or permission", "a quantity or limit", "a timing",
                 "a deadline", "a condition or eligibility rule", "a consequence or effect",
                 "an exception", "a destination", "a repetition rule"):  # fmt: skip
        assert word in " ".join(COMPLETENESS_SYSTEM_INSTRUCTION.split()), word


# --- the derivation law -------------------------------------------------------------------------


def _inv(*assertions: object) -> PropositionInventory:
    return PropositionInventory("p1", tuple(assertions))  # type: ignore[arg-type]


HELD = held("QUANTITY", "ten", "10", "JDG-1")
LOST = lost("ACTOR", "a member", GROUP)
ADDED = added("CONDITION", "photo", "JDG-1", GROUP)
CLASH = clash("QUANTITY", "ten", "15", "JDG-1", GROUP)


@pytest.mark.parametrize(
    ("assertions", "verdict"),
    [
        ((HELD,), "COMPLETE"),
        ((HELD, ADDED), "OVERREACH"),
        ((HELD, LOST), "INCOMPLETE"),
        ((HELD, LOST, ADDED), "INCOMPLETE"),
        ((CLASH, LOST), "CONTRADICTORY"),
        ((CLASH, ADDED), "CONTRADICTORY"),
        ((CLASH, LOST, ADDED), "CONTRADICTORY"),
        ((HELD, CLASH), "CONTRADICTORY"),
    ],
)
def test_the_verdict_is_derived_by_the_sealed_precedence(
    assertions: tuple[object, ...], verdict: str
) -> None:
    """CONTRADICTORY > INCOMPLETE > OVERREACH > COMPLETE, exactly the verifier instruction's."""
    assert derive_verdict(_inv(*assertions)) == verdict
    assert "prefer CONTRADICTORY, then INCOMPLETE, then OVERREACH" in " ".join(
        COMPLETENESS_SYSTEM_INSTRUCTION.split()
    )


# --- construction refuses an incoherent inventory -----------------------------------------------

REVIEW = v2._prop(
    "p1",
    "A member may borrow up to ten items at once.",
    (v2._claim("JDG-1", "Library loans", "maximum_loans_per_member", "10 items at once"),),
)


def _problems(*assertions: object) -> tuple[str, ...]:
    return inventory_problems(REVIEW, _inv(*assertions))


def test_a_coherent_inventory_has_no_problem() -> None:
    assert (
        _problems(
            held("ACTOR", "a member", "per member", "JDG-1"),
            held("PERMISSION", "may borrow", "maximum loans", "JDG-1"),
            held("QUANTITY", "up to ten", "10 items", "JDG-1"),
            held("TIMING", "at once", "at once", "JDG-1"),
        )
        == ()
    )


@pytest.mark.parametrize(
    ("assertions", "why"),
    [
        ((), "no operative assertion"),
        ((held("ACTOR", "a borrower", "per member", "JDG-1"),), "not in the proposition"),
        ((held("ACTOR", "a member", "per borrower", "JDG-1"),), "not in its claims"),
        ((held("ACTOR", "a member", "per member", "JDG-9"),), "not a claim"),
        ((held("ACTOR", "a member", "per member"),), "names no claim"),
        ((lost("TIMING", "at once", GROUP),), "is stated by a claim"),
        ((lost("ACTOR", "a member"),), "no finding markers"),
        (
            (
                held("ACTOR", "a member", "per member", "JDG-1"),
                added("CONDITION", "at once", "JDG-1", GROUP),
            ),
            "is in the proposition",
        ),  # fmt: skip
        (
            (
                held("ACTOR", "a member", "per member", "JDG-1"),
                added("CONDITION", "photo", "JDG-1", GROUP),
            ),
            "not in its claims",
        ),  # fmt: skip
        ((clash("QUANTITY", "ten", "15", "JDG-1", GROUP),), "not in its claims"),
    ],
)
def test_construction_refuses_an_incoherent_inventory(
    assertions: tuple[object, ...], why: str
) -> None:
    problems = _problems(*assertions)
    assert any(why in p for p in problems), problems


def test_no_claim_may_be_left_unclassified() -> None:
    two = v2._prop(
        "p1",
        "A member may borrow up to ten items at once.",
        (
            v2._claim("JDG-1", "Library loans", "maximum_loans_per_member", "10 items at once"),
            v2._claim("JDG-2", "Library loans", "loan_desk", "the issue desk"),
        ),
    )
    problems = inventory_problems(two, _inv(held("ACTOR", "a member", "per member", "JDG-1")))
    assert any("JDG-2" in p and "unclassified" in p for p in problems), problems


def test_an_unknown_kind_or_status_is_refused() -> None:
    bogus = held("MOOD", "a member", "per member", "JDG-1")  # type: ignore[arg-type]
    assert any("kind" in p for p in _problems(bogus))


def test_a_forbidden_interpretation_needs_a_non_complete_proposition() -> None:
    inventory = PropositionInventory(
        "p1", (held("QUANTITY", "up to ten", "10 items", "JDG-1"),), forbidden=("x",)
    )
    assert any("forbidden" in p for p in inventory_problems(REVIEW, inventory))


def test_the_builder_raises_rather_than_build_an_incoherent_case() -> None:
    with pytest.raises(ValueError, match="not in its claims"):
        inventory_case(99, "X", (REVIEW, _inv(held("ACTOR", "a member", "per x", "JDG-1"))))
    with pytest.raises(ValueError, match="names its own proposition"):
        inventory_case(
            99,
            "X",
            (REVIEW, PropositionInventory("p2", (held("TIMING", "at once", "at once", "JDG-1"),))),
        )


# --- every v3 case is coherent ------------------------------------------------------------------


def test_every_case_derives_exactly_its_intended_verdict() -> None:
    assert [c.case_id for c in CASES] == list(INTENDED)
    for case in CASES:
        assert _verdicts(case.case_id) == INTENDED[case.case_id], case.case_id


def test_every_case_is_coherent_by_construction() -> None:
    for case in CASES:
        for review, inventory in zip(case.request.propositions, case.inventory, strict=True):
            assert inventory_problems(review, inventory) == (), case.case_id


def test_every_complete_proposition_has_nothing_missing_added_or_contradicted() -> None:
    """The check that would have caught C02 and C24 before v2 was sealed."""
    seen = 0
    for case in CASES:
        for inventory, expected in zip(case.inventory, case.expected, strict=True):
            if expected.verdict != "COMPLETE":
                continue
            seen += 1
            statuses = {a.status for a in inventory.assertions}
            assert statuses == {"REPRESENTED"}, (case.case_id, inventory.proposition_id)
            assert expected.findings == () and expected.forbidden == ()
    assert seen == 11


def test_every_non_complete_proposition_is_coherent_with_its_verdict() -> None:
    for case in CASES:
        for inventory, expected in zip(case.inventory, case.expected, strict=True):
            statuses = [a.status for a in inventory.assertions]
            where = (case.case_id, inventory.proposition_id)
            if expected.verdict == "INCOMPLETE":
                assert "MISSING" in statuses and "CONTRADICTED" not in statuses, where
            if expected.verdict == "OVERREACH":
                assert "UNSUPPORTED" in statuses, where
                assert "MISSING" not in statuses and "CONTRADICTED" not in statuses, where
            if expected.verdict == "CONTRADICTORY":
                assert "CONTRADICTED" in statuses, where
            if expected.verdict != "COMPLETE":
                region = {"INCOMPLETE": "MISSING", "OVERREACH": "UNSUPPORTED",
                          "CONTRADICTORY": "CONTRADICTED"}[expected.verdict]  # fmt: skip
                assert len(expected.findings) == sum(1 for s in statuses if s == region) >= 1, where
                assert all(f.groups for f in expected.findings), where


def test_every_sealed_missing_assertion_of_a_multi_gap_case_is_a_required_finding() -> None:
    for case_id, kinds in MISSING_OBLIGATIONS.items():
        (inventory,) = case_by_id(case_id).inventory
        missing = tuple(a.kind for a in inventory.assertions if a.status == "MISSING")
        assert sorted(missing) == sorted(kinds), case_id
        (expected,) = case_by_id(case_id).expected
        assert len(expected.findings) == len(kinds), case_id
    multi = {
        c.case_id
        for c in CASES
        for e in c.expected
        if e.verdict == "INCOMPLETE" and len(e.findings) > 1
    }
    assert multi == set(MISSING_OBLIGATIONS)


def test_every_operative_kind_the_corpus_needs_is_used() -> None:
    used = {a.kind for c in CASES for i in c.inventory for a in i.assertions}
    assert used == set(ASSERTION_KINDS)


# --- the corrections and what was carried forward ----------------------------------------------


def test_only_the_approved_cases_changed_and_every_other_payload_is_v2_byte_for_byte() -> None:
    assert frozenset({"C02", "C04", "C10", "C22", "C24"}) == CHANGED_FROM_V2
    for case in CASES:
        old = v2.case_by_id(case.case_id)
        same = v2.render_request(old.request) == v2.render_request(case.request)
        assert same == (case.case_id not in CHANGED_FROM_V2), case.case_id
    # C22 changes only p2: p1 is carried
    assert case_by_id("C22").request.propositions[0] == v2.case_by_id("C22").request.propositions[0]


def _claims(case_id: str, pid: str = "p1") -> list[tuple[str, str, str, str]]:
    (p,) = [p for p in case_by_id(case_id).request.propositions if p.proposition_id == pid]
    return [(c.ref, c.subject, c.predicate, c.value) for c in p.claims]


def test_c02_states_the_member_actor_explicitly() -> None:
    (p,) = case_by_id("C02").request.propositions
    assert p.statement == v2.case_by_id("C02").request.propositions[0].statement
    assert _claims("C02") == [
        ("JDG-1", "Library reservations", "maximum_active_reservations_per_member", "4")
    ]


def test_c04_states_the_renewing_member_explicitly_not_by_presupposition() -> None:
    assert _claims("C04")[0] == ("JDG-1", "Loan renewals", "maximum_renewals_per_member", "2")
    (inventory,) = case_by_id("C04").inventory
    (actor,) = [a for a in inventory.assertions if a.kind == "ACTOR"]
    assert actor.by == ("JDG-1",) and "JDG-3" not in actor.by


def test_c24_states_the_member_actor_in_both_claims() -> None:
    assert _claims("C24") == [
        ("JDG-1", "Printing", "free_print_quota_per_member", "20 pages per day at no charge"),
        ("JDG-2", "Printing", "additional_page_price_per_member",
         "0.10 EUR per page beyond 20 pages in a day"),
    ]  # fmt: skip


def test_c10_is_complete_but_for_exactly_the_unsupported_suspension() -> None:
    assert _claims("C10") == [
        ("JDG-1", "Damage reports", "late_damage_report",
         "refused if made more than 7 days after return, and the member is suspended"),
    ]  # fmt: skip
    (inventory,) = case_by_id("C10").inventory
    assert [a.status for a in inventory.assertions].count("UNSUPPORTED") == 1
    assert {a.kind for a in inventory.assertions if a.status == "REPRESENTED"} >= {
        "TIME_ANCHOR",
        "DEADLINE",
        "CONSEQUENCE",
    }


def test_c22_p2_states_the_member_actor_and_adds_only_the_photo_id() -> None:
    assert _claims("C22", "p2") == [
        ("JDG-3", "Library loans", "maximum_loans_per_member",
         "10 items at once, only with a valid photo ID"),
    ]  # fmt: skip
    inventory = case_by_id("C22").inventory[1]
    assert [a.kind for a in inventory.assertions if a.status == "UNSUPPORTED"] == ["CONDITION"]


# --- the exact frozen v2 payloads are, under the same law, INCOMPLETE ---------------------------


def _historical(case_id: str, pid: str, *assertions: object) -> CompletenessVerdict:
    """Build the exact v2 proposition with an inventory and derive its verdict. Never a case of
    v3, never a rescore of v2: a proof that the correction matches the unchanged policy."""
    (review,) = [p for p in v2.case_by_id(case_id).request.propositions if p.proposition_id == pid]
    inventory = PropositionInventory(pid, tuple(assertions))  # type: ignore[arg-type]
    assert inventory_problems(review, inventory) == ()
    return derive_verdict(inventory)


def test_old_c02_payload_is_incomplete_under_the_unchanged_policy() -> None:
    assert v2.case_by_id("C02").expected[0].verdict == "COMPLETE", "v2 history is not rewritten"
    assert _historical(
        "C02", "p1",
        lost("ACTOR", "a member", GROUP),
        held("PERMISSION", "may hold", "active reservations", "JDG-1"),
        held("QUANTITY", ("at most", "four"), ("maximum", "4"), "JDG-1"),
        held("TIMING", "at once", "active", "JDG-1"),
    ) == "INCOMPLETE"  # fmt: skip


def test_old_c24_payload_is_incomplete_under_the_unchanged_policy() -> None:
    assert v2.case_by_id("C24").expected[0].verdict == "COMPLETE"
    assert _historical(
        "C24", "p1",
        lost("ACTOR", "members", GROUP),
        held("PERMISSION", "may print", "print quota", "JDG-1"),
        held("QUANTITY", "up to 20 pages a day", "20 pages per day", "JDG-1"),
        held("CONSEQUENCE", "free of charge", "no charge", "JDG-1"),
        held("CONDITION", "further pages", "beyond 20 pages", "JDG-2"),
        held("CONSEQUENCE", "0.10 EUR each", "0.10 EUR per page", "JDG-2"),
    ) == "INCOMPLETE"  # fmt: skip


def test_old_c10_payload_is_incomplete_not_overreach_under_the_unchanged_precedence() -> None:
    """Missing time anchor + unsupported suspension: INCOMPLETE beats OVERREACH."""
    assert v2.case_by_id("C10").expected[0].verdict == "OVERREACH"
    assert _historical(
        "C10", "p1",
        held("DEADLINE", "more than 7 days", "after 7 days", "JDG-1"),
        lost("TIME_ANCHOR", "after return", GROUP),
        held("CONSEQUENCE", "is refused", "refused", "JDG-1"),
        added("CONSEQUENCE", "suspended", "JDG-1", GROUP),
    ) == "INCOMPLETE"  # fmt: skip


def test_old_c22_p2_and_old_c04_payloads_are_incomplete_under_the_unchanged_policy() -> None:
    assert v2.case_by_id("C22").expected[1].verdict == "OVERREACH"
    assert _historical(
        "C22", "p2",
        lost("ACTOR", "a member", GROUP),
        held("PERMISSION", "may borrow", "maximum loans", "JDG-3"),
        held("QUANTITY", "up to ten", "10 items", "JDG-3"),
        added("CONDITION", "photo", "JDG-3", GROUP),
    ) == "INCOMPLETE"  # fmt: skip
    assert v2.case_by_id("C04").expected[0].verdict == "COMPLETE"
    assert _historical(
        "C04", "p1",
        lost("ACTOR", "a member", GROUP),
        held("PERMISSION", "may renew", "renewals", "JDG-1"),
        held("REPETITION", "twice", "2", "JDG-1"),
        held("CHANNEL", "online", "online", "JDG-2"),
        held("CONDITION", "nobody else has reserved", "no other member has reserved", "JDG-3"),
    ) == "INCOMPLETE"  # fmt: skip


def test_corrected_c10_is_overreach() -> None:
    assert _verdicts("C10") == {"p1": "OVERREACH"}


# --- K-CREDIT ----------------------------------------------------------------------------------


def test_the_k_credit_payload_and_its_v2_marker_groups_are_unchanged() -> None:
    old, new = v2.case_by_id("C21"), case_by_id("C21")
    assert v2.render_request(old.request) == v2.render_request(new.request)
    (expected,) = new.expected
    assert expected.verdict == "INCOMPLETE"
    assert expected.forbidden == v2.DEADLINE_MISREAD
    refusal = [f for f in expected.findings if f.groups == (v2.LATENESS_48, v2.REFUSAL)]
    assert len(refusal) == 1, "the v2 lateness + refusal law is carried unchanged"
    (channel,) = [f for f in expected.findings if f is not refusal[0]]
    assert any(normalise("app") in g.markers for g in channel.groups)
