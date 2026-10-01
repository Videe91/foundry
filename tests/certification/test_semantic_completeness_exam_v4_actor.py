"""Exam v4's ACTOR scoring law: the semantic role triple ACTOR -> ROLE -> GOVERNED ACTION.

Exam v3 scored a missing actor with an enumerated list of role phrases. Live, Astra answered
C05 attempt 1 with "The permission to renew a loan is granted to a member." -- a correct
finding the list did not admit (v3: NOT CERTIFIED 74/75, frozen). Co-occurrence of an actor, an
action and a relation word is no better: "renewal is only allowed if no other member has
reserved the book" contains all three, yet the member there is the actor of the condition.

Exam v4 identifies a missing ACTOR only when one finding item binds them: the relation governs
the action (relation <-> action) AND the actor fills the actor slot of that same construction
(actor <-> relation / action), with the polarity of the sealed assertion. The bindings are
generic constructions over each assertion's sealed groups; nothing here is specific to renew,
reserve, C05 or C16. Matching stays v2's normalised whole-word / phrase matching.
"""

from __future__ import annotations

import json

import pytest

from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._completeness_exam import MarkerGroup
from tests.certification._completeness_exam_v4 import (
    ACTOR_ROLES,
    CASES,
    RENEWER_ROLE,
    RESERVER_ROLE,
    ActorRole,
    OperativeAssertion,
    case_by_id,
    identifies_actor,
    score_completeness_report,
)
from tests.certification.test_semantic_completeness_exam_v4 import _report

C05 = case_by_id("C05").request.propositions[0].statement
C16 = case_by_id("C16").request.propositions[0].statement
V3_C05_ATTEMPT_1 = "The permission to renew a loan is granted to a member."
CONDITION_ONLY_PROBES = (
    "renewal is only allowed if no other member has reserved the book",
    "Renewal is permitted only when the book is not reserved by another member.",
    "Renewal can happen only if no other member holds a reservation.",
)
CONSEQUENCE_ONLY_PROBES = (
    "Reservations by a member with fines can be cancelled.",
    "A reservation by a member with outstanding fines is cancelled.",
    "A member cancelled a reservation.",
)


def _renewer(*items: str) -> bool:
    return identifies_actor(items, RENEWER_ROLE, C05)


def _reserver(*items: str) -> bool:
    return identifies_actor(items, RESERVER_ROLE, C16)


# --- C05: a member may renew --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("form", "finding"),
    [
        ("nominal, actor after, granted to (frozen v3 C05/1)", V3_C05_ATTEMPT_1),
        ("active, actor before", "A member may renew."),
        ("active with object", "A member may renew the loan."),
        ("active, plural", "Members can renew their loans."),
        ("passive permission", "A member is permitted to renew a loan."),
        ("passive permission, plural", "Members are allowed to renew."),
        ("nominal, granted to", "Permission to renew is granted to a member."),
        ("action-noun permission, granted to", "Renewal permission is granted to a member."),
        ("nominal right, belongs to", "The right to renew belongs to a member."),
        ("limited to actor", "Renewal is limited to members."),
        ("restriction prefix", "Only a member may renew a loan."),
        ("actor with modifier", "A member who holds the loan may renew it."),
        (
            "actor with the condition in the same item",
            "A member may renew only if no other member has reserved it.",
        ),  # fmt: skip
    ],
)
def test_renewer_role_bindings_pass(form: str, finding: str) -> None:
    assert _renewer(finding), form


@pytest.mark.parametrize(
    ("form", "finding"),
    [
        *(("bystander actor in condition", f) for f in CONDITION_ONLY_PROBES),
        ("denied", "A member was denied renewal."),
        ("negated modal", "A member may not renew."),
        ("negated permission", "Members are not allowed to renew."),
        ("negated grant", "Renewal permission is not granted to members."),
        ("withdrawn", "Renewal permission was withdrawn from the member."),
        ("prohibited", "Members are prohibited from renewal."),
        ("unrelated co-occurrence", "The member cancelled the renewal."),
        ("unrelated co-occurrence", "Renewal affects a member."),
        ("unrelated co-occurrence", "A member complained about renewal."),
        ("actor + relation, no action", "A member may borrow books."),
        ("action + relation, no actor", "Renewal may be granted."),
        ("actor + action, no relation", "The renewing member."),
        ("other actor in the grant", "Renewal is granted to another member."),
        ("relation governs another verb", "A member can be told about renewal."),
        (
            "clause break before the grant",
            "Renewal is checked when the loan is granted to a member.",
        ),
    ],
)
def test_co_occurrence_bystanders_and_inverse_polarity_fail(form: str, finding: str) -> None:
    assert not _renewer(finding), form


def test_the_triple_must_be_bound_in_one_item() -> None:
    assert not _renewer("A member.", "Renewal is permitted.")
    assert not _renewer("the member", "may renew")
    assert not _renewer("Permission to renew.", "It is granted to a member.")
    assert _renewer("unrelated", "A member may renew.")


def test_keyword_stuffing_and_echo_identify_nothing() -> None:
    assert not _renewer("member members renew renewal renewals may can permitted allowed")
    assert not _renewer(C05)


# --- C16: only members may reserve ------------------------------------------------------------


@pytest.mark.parametrize(
    ("form", "finding"),
    [
        ("restriction, active", "Only members may reserve a book."),
        ("action-noun permission, limited to", "Reservation permission is limited to members."),
        ("passive permission, light verb", "Members are permitted to make reservations."),
        ("gerund, restricted to", "Reserving a book is restricted to members."),
        ("actor-only restriction", "Members only can make reservations."),
        ("actor with modifier", "Only members with no outstanding fines may reserve a book."),
        ("contrapositive", "Non-members cannot reserve a book."),
        ("contrapositive, light verb", "A non-member may not place a reservation."),
        ("contrapositive, passive", "Non-members are not permitted to reserve."),
    ],
)
def test_reserver_role_bindings_pass(form: str, finding: str) -> None:
    assert _reserver(finding), form


@pytest.mark.parametrize(
    ("form", "finding"),
    [
        *(("actor inside the consequence", f) for f in CONSEQUENCE_ONLY_PROBES),
        ("inverse", "Members cannot reserve a book."),
        ("inverse", "Members may not reserve."),
        ("complement affirmed: the wrong rule", "Non-members may reserve a book."),
        ("barred", "Members are barred from reserving."),
        ("no action", "Only members."),
        ("no actor", "Reservations are limited."),
        ("action, no binding", "A member reserved a book."),
    ],
)
def test_reserver_consequence_actor_inverse_and_complement_fail(form: str, finding: str) -> None:
    assert not _reserver(finding), form


# --- the all-gaps guarantee -----------------------------------------------------------------


def test_a_condition_finding_never_satisfies_the_actor_gap_but_still_names_the_condition() -> None:
    case = case_by_id("C05")
    for probe in CONDITION_ONLY_PROBES[:2]:
        reasons = score_completeness_report(case, _report("C05", "p1", "INCOMPLETE", (probe,)))
        assert len(reasons) == 1 and "ACTOR" in reasons[0], (probe, reasons)


def test_a_consequence_finding_never_satisfies_the_actor_gap() -> None:
    case = case_by_id("C16")
    for probe in CONSEQUENCE_ONLY_PROBES[:2]:
        reasons = score_completeness_report(case, _report("C16", "p1", "INCOMPLETE", (probe,)))
        assert len(reasons) == 1 and "ACTOR" in reasons[0], (probe, reasons)


# --- the primitive is generic -----------------------------------------------------------------


def test_the_role_engine_knows_nothing_of_renewing_or_reserving() -> None:
    signer = ActorRole(
        actor=MarkerGroup("guardian", ("guardian", "guardians")),
        action=MarkerGroup("sign", ("sign", "countersign")),
        action_noun=MarkerGroup("signature", ("signature", "signing")),
        modal=RENEWER_ROLE.modal,
        licensed=RENEWER_ROLE.licensed,
        grant=RENEWER_ROLE.grant,
    )
    statement = "A guardian may sign the form."
    assert identifies_actor(("Only a guardian may sign.",), signer, statement)
    assert identifies_actor(("The right to sign is granted to a guardian.",), signer, statement)
    assert identifies_actor(("Signing is restricted to guardians.",), signer, statement)
    assert not identifies_actor(("A guardian may not sign.",), signer, statement)
    assert not identifies_actor(("The form needs a signature if the guardian is absent.",),
                                signer, statement)  # fmt: skip


# --- the audit: every ACTOR assertion -------------------------------------------------------


def test_every_actor_assertion_is_audited() -> None:
    actors = [
        (c.case_id, i.proposition_id, a.status)
        for c in CASES
        for i in c.inventory
        for a in i.assertions
        if a.kind == "ACTOR"
    ]
    assert actors == [
        ("C02", "p1", "REPRESENTED"),
        ("C04", "p1", "REPRESENTED"),
        ("C05", "p1", "MISSING"),
        ("C09", "p1", "REPRESENTED"),
        ("C14", "p1", "REPRESENTED"),
        ("C16", "p1", "MISSING"),
        ("C22", "p2", "REPRESENTED"),
        ("C24", "p1", "REPRESENTED"),
    ]


def test_every_scored_actor_uses_the_role_law_and_nothing_else_does() -> None:
    assert set(ACTOR_ROLES) == {"C05", "C16"}
    for c in CASES:
        for i in c.inventory:
            for a in i.assertions:
                assert isinstance(a, OperativeAssertion)
                scored = a.kind == "ACTOR" and a.status != "REPRESENTED"
                assert (a.role is not None) == scored, (c.case_id, a.kind)
                if scored:
                    assert a.role is ACTOR_ROLES[c.case_id] and a.groups == ()
    assert RENEWER_ROLE.complement is None, "a permission has no contrapositive"
    assert RESERVER_ROLE.complement is not None, "a restriction does"


# --- the frozen v3 evidence ------------------------------------------------------------------


def test_all_six_frozen_v3_c05_and_c16_findings_identify_their_actor_under_v4() -> None:
    """A scorer regression proof, not a re-score: v3's standing is untouched."""
    path = EVIDENCE_ROOT / (
        "openai/gpt-6-astra/semantic_completeness_verification_exam_v3/certification.json"
    )
    record = json.loads(path.read_text())
    findings = {
        (a["case"], a["attempt"]): tuple(a["parsed_report"]["verdicts"][0]["missing"])
        for a in record["attempts"]
        if a["case"] in ("C05", "C16")
    }
    assert len(findings) == 6 and V3_C05_ATTEMPT_1 in findings[("C05", 1)]
    for (case_id, attempt), items in findings.items():
        role, statement = (RENEWER_ROLE, C05) if case_id == "C05" else (RESERVER_ROLE, C16)
        assert identifies_actor(items, role, statement), (case_id, attempt)
        case = case_by_id(case_id)
        assert score_completeness_report(case, _report(case_id, "p1", "INCOMPLETE", items)) == ()
