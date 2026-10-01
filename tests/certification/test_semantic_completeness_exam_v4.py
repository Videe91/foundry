"""Exam v4: v3's corpus, inventories and finding law carried unchanged; only the ACTOR law moves.

Proofs that v4 is v3 with exactly one scoring change: every model-visible request is v3's byte
for byte; every inventory assertion keeps its kind, status, anchors and claims; every non-ACTOR
marker group is v3's object; every derived verdict and every required finding is v3's, except
that the two scored ACTOR assertions (C05, C16) are identified by their role structure. The
coherence law, the precedence and the all-gaps coverage rule are unchanged.
"""

from __future__ import annotations

import pytest

import tests.certification._completeness_exam_v3 as v3
from foundry.domain.semantic_completeness import CompletenessReport, PropositionVerdict
from tests.certification._completeness_exam import MarkerGroup, render_request
from tests.certification._completeness_exam_v3 import (
    derive_verdict,
)
from tests.certification._completeness_exam_v4 import (
    ACTOR_ROLES,
    CASES,
    RENEWER_ROLE,
    OperativeAssertion,
    RequiredFinding,
    added,
    case_by_id,
    clash,
    held,
    inventory_problems,
    lost,
    lost_actor,
    score_completeness_report,
)
from tests.certification.test_semantic_completeness_exam_v3 import PASSING_FINDINGS

GROUP = MarkerGroup("anything", ("anything",))
REVIEW = v3.case_by_id("C05").request.propositions[0]
V3_C05_ATTEMPT_1 = (
    "The permission to renew a loan is granted to a member.",
    "Renewal is conditional on nobody else having reserved the book.",
)


def _report(case_id: str, pid: str, verdict: str, missing: tuple[str, ...]) -> CompletenessReport:
    case = case_by_id(case_id)
    out = []
    for p in case.request.propositions:
        sealed = {e.proposition_id: e.verdict for e in case.expected}[p.proposition_id]
        v = verdict if p.proposition_id == pid else sealed
        region = {"INCOMPLETE": "missing", "OVERREACH": "unsupported",
                  "CONTRADICTORY": "contradictory"}  # fmt: skip
        items = (
            missing
            if p.proposition_id == pid
            else PASSING_FINDINGS.get(case_id, {}).get(p.proposition_id, ())
        )
        out.append(
            PropositionVerdict(
                proposition_id=p.proposition_id,
                verdict=v,  # type: ignore[arg-type]
                claim_refs=tuple(c.ref for c in p.claims),
                **({} if v == "COMPLETE" else {region[v]: items}),
            )
        )
    return CompletenessReport(verdicts=tuple(out))


def _passes(case_id: str, *items: str, pid: str = "p1") -> bool:
    sealed = {e.proposition_id: e.verdict for e in case_by_id(case_id).expected}[pid]
    return (
        score_completeness_report(case_by_id(case_id), _report(case_id, pid, sealed, items)) == ()
    )


# --- v3 carried unchanged ----------------------------------------------------------------------


def test_every_model_visible_request_is_v3_byte_for_byte() -> None:
    assert [c.case_id for c in CASES] == [c.case_id for c in v3.CASES]
    for new, old in zip(CASES, v3.CASES, strict=True):
        assert render_request(new.request) == render_request(old.request), new.case_id
        assert new.category == old.category


def test_every_inventory_is_v3s_but_for_the_scored_actors() -> None:
    for new, old in zip(CASES, v3.CASES, strict=True):
        for ni, oi in zip(new.inventory, old.inventory, strict=True):
            assert ni.forbidden == oi.forbidden
            for na, oa in zip(ni.assertions, oi.assertions, strict=True):
                assert isinstance(na, OperativeAssertion)
                assert (na.kind, na.status, na.stated, na.claimed, na.by) == (
                    oa.kind, oa.status, oa.stated, oa.claimed, oa.by,
                )  # fmt: skip
                if na.kind == "ACTOR" and na.status != "REPRESENTED":
                    assert na.groups == () and na.role is ACTOR_ROLES[new.case_id]
                else:
                    assert na.groups == oa.groups and na.role is None, new.case_id
                    assert all(g is h for g, h in zip(na.groups, oa.groups, strict=True))


def test_every_derived_verdict_and_required_finding_is_v3s() -> None:
    for new, old in zip(CASES, v3.CASES, strict=True):
        for ne, oe in zip(new.expected, old.expected, strict=True):
            assert (ne.verdict, ne.forbidden) == (oe.verdict, oe.forbidden), new.case_id
            assert [f.name for f in ne.findings] == [f.name for f in oe.findings]
            for nf, of in zip(ne.findings, oe.findings, strict=True):
                assert isinstance(nf, RequiredFinding)
                if nf.role is None:
                    assert nf.groups == of.groups


def test_every_coverage_obligation_of_v3_stands() -> None:
    def kinds(case_id: str) -> list[str]:
        return [f.name.split()[0] for f in case_by_id(case_id).expected[0].findings]

    assert kinds("C05") == ["ACTOR", "CONDITION"]
    assert kinds("C09") == ["ELIGIBILITY", "QUANTITY"]
    assert kinds("C15") == ["TIME_ANCHOR", "CONSEQUENCE"]
    assert kinds("C16") == ["ACTOR", "CONSEQUENCE"]
    assert kinds("C21") == ["CHANNEL", "CONSEQUENCE"]


# --- the inventory law, with the structural actor ----------------------------------------------


@pytest.mark.parametrize(
    ("assertion", "why"),
    [
        (lost("ACTOR", "a member", GROUP), "scored by its role alone"),
        (
            OperativeAssertion(
                "ACTOR", "MISSING", ("a member",), groups=(GROUP,), role=RENEWER_ROLE
            ),
            "scored by its role alone",
        ),  # fmt: skip
        (
            OperativeAssertion(
                "CONDITION",
                "MISSING",
                ("nobody else has reserved",),
                groups=(GROUP,),
                role=RENEWER_ROLE,
            ),
            "only a scored actor carries a role",
        ),  # fmt: skip
        (
            OperativeAssertion(
                "ACTOR", "REPRESENTED", ("a member",), ("renewals",), ("JDG-1",), role=RENEWER_ROLE
            ),
            "seals no finding",
        ),  # fmt: skip
    ],
)
def test_construction_refuses_an_actor_scored_any_other_way(
    assertion: OperativeAssertion, why: str
) -> None:
    inventory = v3.PropositionInventory(
        "p1",
        (
            assertion,
            held("PERMISSION", "may renew", "renewals", "JDG-1"),
            held("CHANNEL", "online", "online", "JDG-2"),
        ),
    )
    assert any(why in p for p in inventory_problems(REVIEW, inventory))


def test_a_role_scored_actor_is_coherent() -> None:
    inventory = v3.PropositionInventory(
        "p1",
        (
            lost_actor("a member", RENEWER_ROLE),
            held("PERMISSION", "may renew", "renewals", "JDG-1"),
            held("CHANNEL", "online", "online", "JDG-2"),
        ),
    )
    assert inventory_problems(REVIEW, inventory) == ()


@pytest.mark.parametrize(
    ("assertions", "verdict"),
    [
        ((held("CHANNEL", "online", "online", "JDG-2"),), "COMPLETE"),
        (
            (held("CHANNEL", "online", "online", "JDG-2"), added("CONDITION", "x", "JDG-1", GROUP)),
            "OVERREACH",
        ),  # fmt: skip
        (
            (lost_actor("a member", RENEWER_ROLE), added("CONDITION", "x", "JDG-1", GROUP)),
            "INCOMPLETE",
        ),  # fmt: skip
        (
            (lost_actor("a member", RENEWER_ROLE), clash("TIMING", "twice", "3", "JDG-1", GROUP)),
            "CONTRADICTORY",
        ),  # fmt: skip
    ],
)
def test_the_precedence_is_unchanged(assertions: tuple[object, ...], verdict: str) -> None:
    assert derive_verdict(v3.PropositionInventory("p1", assertions)) == verdict  # type: ignore[arg-type]


# --- the scorer -------------------------------------------------------------------------------


def test_v3s_perfect_findings_still_pass_every_case() -> None:
    for case in CASES:
        for e in case.expected:
            items = PASSING_FINDINGS.get(case.case_id, {}).get(e.proposition_id, ())
            if e.verdict != "COMPLETE":
                assert _passes(case.case_id, *items, pid=e.proposition_id), case.case_id


def test_the_exact_frozen_v3_c05_attempt_1_answer_passes_c05() -> None:
    assert _passes("C05", *V3_C05_ATTEMPT_1)


def test_c05_still_needs_both_the_actor_and_the_condition() -> None:
    actor, condition = V3_C05_ATTEMPT_1
    assert not _passes("C05", actor)
    assert not _passes("C05", condition)
    assert not _passes("C05", "A member was denied renewal.", condition)
    assert not _passes("C05", "A member.", "Renewal is permitted.", condition)


def test_c16_accepts_the_structural_actor_and_still_needs_the_cancellation() -> None:
    cancelled = "A reservation by a member with outstanding fines is cancelled."
    assert _passes("C16", "Reservation permission is limited to members.", cancelled)
    assert _passes("C16", "Non-members cannot reserve a book.", cancelled)
    assert not _passes("C16", "Members cannot reserve a book.", cancelled)
    assert not _passes("C16", "Reservation permission is limited to members.")


def test_c21_still_needs_the_app_channel_and_the_late_refusal() -> None:
    app, refusal = PASSING_FINDINGS["C21"]["p1"]
    assert _passes("C21", app, refusal)
    assert not _passes("C21", refusal)
    assert not _passes("C21", app)
    assert not _passes("C21", app, "the 48-hour deadline is missing", refusal)


def test_no_other_finding_type_was_loosened() -> None:
    assert not _passes("C10", "the claim goes beyond the proposition")
    assert not _passes("C11", "the claims conflict")
    assert not _passes("C15", "a report made after that deadline is refused")
    assert not _passes("C09", "the limit of at most five items")
    assert not _passes("C22", "the limit of ten items", pid="p2")
