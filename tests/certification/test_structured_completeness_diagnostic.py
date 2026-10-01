"""OFFLINE diagnostic: the v2-v5 problem findings scored as structured evidence.

Every recorded free-text finding in the table is checked against the frozen live evidence; its
structured rendering is then scored with no natural-language interpretation at all. Different
wordings of the same judgement (C05 across v3, v4 and v5) become the same structured answer and
pass the same way. Wrong kinds, wrong directions, deadline-only answers, invented quotes and a
whole-proposition quote standing in for two regions all fail. Historical standings are untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._completeness_exam import render_request
from tests.certification._completeness_exam_v5 import case_by_id
from tests.certification._structured_diagnostic import (
    C05_CONDITION,
    SEALED,
    TRANSLATIONS,
    contradicted,
    missing,
    report,
    score_structured,
    unsupported,
)

NAMESPACE = {
    "v3": "semantic_completeness_verification_exam_v3",
    "v4": "semantic_completeness_verification_exam_v4",
    "v5": "semantic_completeness_verification_exam_v5",
}


def _recorded(exam: str, case: str, attempt: int) -> dict:  # type: ignore[type-arg]
    path = EVIDENCE_ROOT / f"openai/gpt-6-astra/{NAMESPACE[exam]}/certification.json"
    (a,) = [
        a
        for a in json.loads(path.read_text())["attempts"]
        if (a["case"], a["attempt"]) == (case, attempt)
    ]
    return a  # type: ignore[no-any-return]


def _score(case: str, findings: dict) -> tuple[str, ...]:  # type: ignore[type-arg]
    request = case_by_id(case).request
    return score_structured(request, report(request, findings), SEALED[case])


# --- the table is the real history ------------------------------------------------------------


@pytest.mark.parametrize("t", TRANSLATIONS, ids=lambda t: f"{t.exam}-{t.case}-{t.attempt}")
def test_each_recorded_finding_is_exactly_what_the_live_evidence_holds(t) -> None:  # type: ignore[no-untyped-def]
    a = _recorded(t.exam, t.case, t.attempt)
    assert a["request_json"] == render_request(case_by_id(t.case).request)
    (pid,) = t.structured
    (v,) = [v for v in a["parsed_report"]["verdicts"] if v["proposition_id"] == pid]
    assert tuple(v["missing"] + v["unsupported"] + v["contradictory"]) == t.recorded_text


# --- every historical judgement scores without reading English --------------------------------


@pytest.mark.parametrize("t", TRANSLATIONS, ids=lambda t: f"{t.exam}-{t.case}-{t.attempt}")
def test_each_structured_rendering_passes_on_kind_direction_ids_and_grounding(t) -> None:  # type: ignore[no-untyped-def]
    assert _score(t.case, t.structured) == ()


def test_three_exams_worth_of_c05_wordings_are_one_structured_answer() -> None:
    c05 = [t for t in TRANSLATIONS if t.case == "C05"]
    assert {(t.exam, t.attempt) for t in c05} == {("v3", 1), ("v4", 2), ("v4", 3), ("v5", 2)}
    assert len({t.recorded_text[0] for t in c05}) == 4, "four different English wordings"
    assert all(t.structured == c05[0].structured for t in c05), "one structured judgement"


# --- K-CREDIT ----------------------------------------------------------------------------------


def test_k_credit_needs_the_channel_and_the_refusal_and_a_deadline_only_answer_fails() -> None:
    channel = missing("CHANNEL", "claimed in the app")
    refusal = missing("CONSEQUENCE", "a later claim is refused")
    assert _score("C21", {"p1": (channel, refusal)}) == ()
    deadline = missing("DEADLINE", "within 48 hours after the reservation start")
    assert _score("C21", {"p1": (deadline,)}) != ()
    assert _score("C21", {"p1": (channel,)}) != ()
    assert _score("C21", {"p1": (refusal,)}) != ()
    assert _score("C21", {}) != (), "COMPLETE is the K-CREDIT failure itself"


# --- C05 and the all-gaps law ------------------------------------------------------------------


def test_c05_actor_gap_is_a_kind_and_a_quote_not_a_phrase() -> None:
    condition = missing("CONDITION", "if nobody else has reserved the book")
    for actor_quote in ("A member may renew a loan", "A member", "A member may renew"):
        assert _score("C05", {"p1": (missing("ACTOR", actor_quote), condition)}) == ()
    assert _score("C05", {"p1": (condition,)}) != (), "the condition never stands for the actor"
    whole = case_by_id("C05").request.propositions[0].statement
    assert _score("C05", {"p1": (missing("ACTOR", whole), condition)}) != (), (
        "one quote covering two expected regions identifies neither"
    )
    assert _score("C05", {"p1": (missing("PERMISSION", "A member may renew"), condition)}) != ()
    assert C05_CONDITION  # the recorded condition wording is irrelevant to scoring


# --- contradiction, overreach, grounding --------------------------------------------------------


def test_c17_contradiction_needs_the_claim_side_and_no_echo_rule() -> None:
    assert _score("C17", {"p2": (contradicted("TIMING", "two weeks", "CLM-1", "21 days"),)}) == ()
    assert _score("C17", {"p2": (contradicted("TIMING", "A loan lasts two weeks", "CLM-1",
                                              "21 days"),)}) == ()  # fmt: skip
    assert _score("C17", {"p2": (contradicted("TIMING", "two weeks", "CLM-1", "14 days"),)}) != ()
    assert _score("C17", {"p2": (contradicted("TIMING", "two weeks", "JDG-1", "21 days"),)}) != ()
    assert _score("C17", {"p2": (missing("TIMING", "two weeks"),)}) != (), "wrong direction"


def test_overreach_is_a_claim_ref_and_its_quote() -> None:
    assert (
        _score("C10", {"p1": (unsupported("CONSEQUENCE", "JDG-1", "the member is suspended"),)})
        == ()
    )
    assert (
        _score("C10", {"p1": (unsupported("CONSEQUENCE", "JDG-1", "the member is banned"),)}) != ()
    )
    assert (
        _score("C10", {"p1": (unsupported("CONSEQUENCE", "JDG-9", "the member is suspended"),)})
        != ()
    )
    assert (
        _score("C10", {"p1": (unsupported("ELIGIBILITY", "JDG-1", "the member is suspended"),)})
        != ()
    )


def test_an_invented_quote_never_scores() -> None:
    invented = missing("CHANNEL", "claimed by phone")
    assert _score("C21", {"p1": (invented, missing("CONSEQUENCE", "a later claim is refused"))})


def test_the_structured_scorer_reads_no_english_and_uses_no_marker_vocabulary() -> None:
    source = Path("tests/certification/_structured_diagnostic.py").read_text()
    code = source.split("SEALED: Final", 1)[0]
    for forbidden in ("MarkerGroup", "_completeness_exam", "synonyms", "echo", "identifies"):
        assert forbidden not in code, forbidden


def test_a_region_is_matched_only_by_its_own_kind_and_direction() -> None:
    """At the matcher itself: the schema and the verdict law make most direction mistakes fail
    earlier, but the region match never relies on that."""
    from tests.certification._structured_diagnostic import SealedRegion, _matches

    region = SealedRegion("CONSEQUENCE", "UNSUPPORTED", claim_ref="JDG-1", claim_anchor="suspended")
    right = unsupported("CONSEQUENCE", "JDG-1", "the member is suspended")
    wrong_direction = contradicted("CONSEQUENCE", "is refused", "JDG-1", "the member is suspended")
    wrong_kind = unsupported("ELIGIBILITY", "JDG-1", "the member is suspended")
    assert _matches(right, region, ())
    assert not _matches(wrong_direction, region, ())
    assert not _matches(wrong_kind, region, ())
