"""Structured certification exam v1 for ``ie2-semantic-completeness-v2``: corpus and scorer.

The free-text lineage (exams v1-v5) ended because deterministic code could not reliably read
English. This exam never reads English. It scores a ``StructuredCompletenessReport`` only on:
the verdict; for each sealed region, a finding of the right direction and an admissible kind
whose verbatim proposition quote contains the region's anchor (and no other region's anchor)
and, where sealed, whose claim_ref and verbatim claim quote contain the claim-side anchor;
every quote grounded where it says; and no finding left unaccounted for. ``explanation`` is
never read. Anchors are source text; quotes are source text; containment is whole-word with case,
whitespace and punctuation folded -- never paraphrase.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

import tests.certification._completeness_exam as freetext
from foundry.domain.semantic_completeness import (
    STRUCTURED_REPORT_FORMAT,
    CompletenessReport,
    FindingKind,
    PropositionVerdict,
    SemanticFinding,
    StructuredCompletenessReport,
    StructuredPropositionVerdict,
)
from tests.certification._structured_completeness_exam import (
    C05_REGRESSION,
    C17_REGRESSION,
    CASES,
    K_CREDIT,
    REQUIRED_COVERAGE,
    StructuredCase,
    case_by_id,
    perfect_findings,
    score_structured_report,
)


def _report(
    case: StructuredCase, findings: Mapping[str, tuple[SemanticFinding, ...]]
) -> StructuredCompletenessReport:
    verdicts = []
    for p in case.request.propositions:
        found = findings.get(p.proposition_id, ())
        directions = {f.direction for f in found}
        verdict = (
            "CONTRADICTORY" if "CONTRADICTORY" in directions
            else "INCOMPLETE" if "MISSING" in directions
            else "OVERREACH" if "UNSUPPORTED" in directions
            else "COMPLETE"
        )  # fmt: skip
        verdicts.append(
            StructuredPropositionVerdict(
                proposition_id=p.proposition_id,
                verdict=verdict,  # type: ignore[arg-type]
                claim_refs=tuple(c.ref for c in p.claims),
                findings=found,
            )
        )
    return StructuredCompletenessReport(
        report_format=STRUCTURED_REPORT_FORMAT, verdicts=tuple(verdicts)
    )


def _score(case_id: str, findings: Mapping[str, tuple[SemanticFinding, ...]]) -> tuple[str, ...]:
    case = case_by_id(case_id)
    return score_structured_report(case, _report(case, findings))


def _missing(kind: FindingKind, quote: str, explanation: str = "") -> SemanticFinding:
    return SemanticFinding(
        kind=kind,
        direction="MISSING",
        proposition_evidence=quote,
        explanation=explanation,
    )


# --- the corpus -------------------------------------------------------------------------------


def test_the_exam_covers_every_required_shape() -> None:
    covered = {c.category for c in CASES}
    assert covered >= set(REQUIRED_COVERAGE), set(REQUIRED_COVERAGE) - covered
    verdicts = [e.verdict for c in CASES for e in c.expected.values()]
    assert set(verdicts) == {"COMPLETE", "INCOMPLETE", "OVERREACH", "CONTRADICTORY"}
    dispositions = {(p.disposition, c.expected[p.proposition_id].verdict == "COMPLETE")
                    for c in CASES for p in c.request.propositions}  # fmt: skip
    assert {("ASSERT", True), ("SUPPORT", True), ("ASSERT_SUPERSEDE", True)} <= dispositions


def test_most_of_the_exam_is_held_out_from_every_earlier_corpus() -> None:
    earlier = " ".join(p.statement.lower() for c in freetext.CASES for p in c.request.propositions)
    held_out = [c for c in CASES if c.case_id not in (K_CREDIT, C05_REGRESSION, C17_REGRESSION)]
    assert len(held_out) >= len(CASES) - 3 >= 20
    for case in held_out:
        for p in case.request.propositions:
            assert p.statement.lower() not in earlier, case.case_id
            for word in ("library", "loan", "reservation", "service credit"):
                assert word not in p.statement.lower(), (case.case_id, word)


def test_every_sealed_anchor_is_source_text_and_every_claim_anchor_is_its_claims_text() -> None:
    from foundry.domain.semantic_completeness import grounded

    for case in CASES:
        reviews = {p.proposition_id: p for p in case.request.propositions}
        assert set(case.expected) == set(reviews), case.case_id
        for pid, sealed in case.expected.items():
            review = reviews[pid]
            texts = (review.statement, *review.source_sentences)
            claims = {c.ref: f"{c.subject} {c.predicate} {c.value}" for c in review.claims}
            assert (sealed.verdict == "COMPLETE") == (not sealed.regions), (case.case_id, pid)
            for r in sealed.regions:
                for anchor in r.anchors:
                    assert any(grounded(anchor, t) for t in texts), (case.case_id, anchor)
                    for c in claims.values():
                        if r.direction == "MISSING":
                            assert not grounded(anchor, c), (case.case_id, anchor)
                if r.claim_ref is not None:
                    assert r.claim_anchor and grounded(r.claim_anchor, claims[r.claim_ref])
                    assert not any(grounded(r.claim_anchor, t) for t in texts), case.case_id
                assert r.kinds and (r.anchors or r.claim_ref), case.case_id
            anchors = [a for r in sealed.regions for a in r.anchors]
            for a in anchors:
                assert sum(grounded(a, b) or grounded(b, a) for b in anchors) == 1, (
                    case.case_id,
                    a,
                )


def test_the_named_regressions_are_exactly_their_recorded_shapes() -> None:
    (kc,) = case_by_id(K_CREDIT).request.propositions
    assert kc == freetext.case_by_id("C21").request.propositions[0], "the frozen v6 proposition"
    (c05,) = case_by_id(C05_REGRESSION).request.propositions
    assert c05 == freetext.case_by_id("C05").request.propositions[0]
    assert (
        case_by_id(C17_REGRESSION).request.propositions
        == freetext.case_by_id("C17").request.propositions
    )


# --- the perfect answer -------------------------------------------------------------------------


def test_the_perfect_structured_answer_passes_every_case() -> None:
    for case in CASES:
        assert _score(case.case_id, perfect_findings(case)) == (), case.case_id


def test_complete_is_judged_by_the_verdict_alone_and_claim_count_never_matters() -> None:
    for case in CASES:
        if all(e.verdict == "COMPLETE" for e in case.expected.values()):
            assert _score(case.case_id, {}) == (), case.case_id


# --- K-CREDIT -----------------------------------------------------------------------------------


def test_k_credit_needs_both_gaps_and_nothing_else() -> None:
    channel = _missing("CHANNEL", "claimed in the app")
    refusal = _missing("CONSEQUENCE", "A claim made later is refused")
    assert _score(K_CREDIT, {"p1": (channel, refusal)}) == ()
    assert (
        _score(K_CREDIT, {"p1": (channel, _missing("CONSEQUENCE", "a later claim is refused"))})
        == ()
    )
    assert _score(K_CREDIT, {"p1": (_missing("DEADLINE", "within 48 hours"),)}) != ()
    assert _score(K_CREDIT, {"p1": (channel,)}) != ()
    assert _score(K_CREDIT, {"p1": (refusal,)}) != ()
    assert (
        _score(K_CREDIT, {"p1": (channel, refusal, _missing("DEADLINE", "within 48 hours"))}) != ()
    ), "the deadline is represented: claiming it missing is a wrong finding"
    assert _score(K_CREDIT, {}) != ()


# --- C05: explanation never matters -------------------------------------------------------------

LOOP_WORDINGS = (
    "",
    "The renewing member is not stated.",
    "The permission to renew a loan is granted to a member.",  # broke v3
    "A member is the actor permitted to renew the loan.",  # broke v4
    "The renewal permission applies to a member.",  # broke v5
    "Lorem ipsum: purple elephants negotiate the tide.",
)


@pytest.mark.parametrize("explanation", LOOP_WORDINGS)
def test_c05_scores_on_structure_whatever_the_explanation(explanation: str) -> None:
    findings = {
        "p1": (
            _missing("ACTOR", "A member may renew a loan", explanation),
            _missing("CONDITION", "if nobody else has reserved the book", explanation),
        )
    }
    assert _score(C05_REGRESSION, findings) == ()
    wrong = {"p1": (_missing("CONDITION", "if nobody else has reserved the book", explanation),)}
    assert _score(C05_REGRESSION, wrong) != ()


def test_the_score_is_identical_for_every_explanation_on_every_case() -> None:
    for case in CASES:
        base = perfect_findings(case)
        expected = _score(case.case_id, base)
        for explanation in LOOP_WORDINGS:
            varied = {
                pid: tuple(f.model_copy(update={"explanation": explanation}) for f in fs)
                for pid, fs in base.items()
            }
            assert _score(case.case_id, varied) == expected, (case.case_id, explanation)


# --- C17 ----------------------------------------------------------------------------------------


def test_c17_is_timing_contradicted_with_the_claim_side_and_no_echo_rule() -> None:
    def clash(quote: str, ref: str, claim_quote: str) -> SemanticFinding:
        return SemanticFinding(kind="TIMING", direction="CONTRADICTORY", proposition_evidence=quote,
                               claim_ref=ref, claim_evidence=claim_quote)  # fmt: skip

    assert _score(C17_REGRESSION, {"p2": (clash("two weeks", "CLM-1", "21 days"),)}) == ()
    assert (
        _score(C17_REGRESSION, {"p2": (clash("A loan lasts two weeks.", "CLM-1", "21 days"),)})
        == ()
    )
    assert _score(C17_REGRESSION, {"p2": (clash("two weeks", "CLM-1", "loan period"),)}) != ()
    assert _score(C17_REGRESSION, {"p2": (clash("two weeks", "CLM-2", "21 days"),)}) != ()


# --- adversarial --------------------------------------------------------------------------------


def _one_region_case() -> tuple[str, str, SemanticFinding]:
    case = next(c for c in CASES if c.category == "MISSING_CHANNEL")
    ((pid, found),) = perfect_findings(case).items()
    (finding,) = found
    return case.case_id, pid, finding


def test_right_evidence_wrong_kind_or_direction_fails() -> None:
    case_id, pid, f = _one_region_case()
    assert _score(case_id, {pid: (f.model_copy(update={"kind": "EXCEPTION"}),)}) != ()
    value = case_by_id(case_id).request.propositions[0].claims[0].value
    clash = SemanticFinding(
        kind=f.kind,
        direction="CONTRADICTORY",
        proposition_evidence=f.proposition_evidence,
        claim_ref="JDG-1",
        claim_evidence=value,
    )
    assert _score(case_id, {pid: (clash,)}) != ()


def test_invented_quote_wrong_proposition_and_wrong_claim_fail() -> None:
    case_id, pid, f = _one_region_case()
    assert (
        _score(
            case_id, {pid: (f.model_copy(update={"proposition_evidence": "through the fax line"}),)}
        )
        != ()
    )
    other = next(c for c in CASES if c.case_id != case_id and c.category.startswith("MISSING"))
    foreign = other.request.propositions[0].statement
    assert _score(case_id, {pid: (f.model_copy(update={"proposition_evidence": foreign}),)}) != ()
    over = next(c for c in CASES if c.category == "UNSUPPORTED_CONSEQUENCE")
    ((opid, (u,)),) = perfect_findings(over).items()
    assert _score(over.case_id, {opid: (u,)}) == ()
    assert _score(over.case_id, {opid: (u.model_copy(update={"claim_ref": "JDG-9"}),)}) != ()
    assert (
        _score(over.case_id, {opid: (u.model_copy(update={"claim_evidence": "is expelled"}),)})
        != ()
    )


def test_one_finding_never_stands_for_two_regions() -> None:
    case = next(c for c in CASES if c.category == "TWO_INDEPENDENT_MISSING")
    (p,) = case.request.propositions
    shared = set(case.expected[p.proposition_id].regions[0].kinds) & set(
        case.expected[p.proposition_id].regions[1].kinds
    )
    assert "CHANNEL" in shared, "a kind admissible for both regions, so only the anchor law decides"
    whole = _missing("CHANNEL", p.statement)
    assert score_structured_report(case, _report(case, {p.proposition_id: (whole,)})) != ()
    assert score_structured_report(case, _report(case, {p.proposition_id: (whole, whole)})) != ()


def test_an_unsealed_extra_finding_fails() -> None:
    case_id, pid, f = _one_region_case()
    review = case_by_id(case_id).request.propositions[0]
    first_word = review.statement.split()[0]
    assert _score(case_id, {pid: (f, _missing("ACTOR", first_word))}) != ()


def test_reports_that_are_not_valid_structured_reports_fail() -> None:
    case = case_by_id(K_CREDIT)
    assert score_structured_report(case, None) != ()
    v1 = CompletenessReport(
        verdicts=(
            PropositionVerdict(proposition_id="p1", verdict="COMPLETE", claim_refs=("JDG-1",)),
        )
    )
    assert score_structured_report(case, v1) != ()
    assert score_structured_report(case, StructuredCompletenessReport(
        report_format=STRUCTURED_REPORT_FORMAT, verdicts=())) != ()  # fmt: skip


def test_the_region_matcher_checks_kind_direction_claim_ref_and_claim_quote() -> None:
    """At the matcher itself, independent of the grounding that usually fails such answers first."""
    from tests.certification._structured_completeness_exam import SealedRegion, finding_matches

    region = SealedRegion(("ACTOR",), "UNSUPPORTED", (), "JDG-2", "guests")
    right = SemanticFinding(kind="ACTOR", direction="UNSUPPORTED", claim_ref="JDG-2",
                            claim_evidence="guests may also borrow it")  # fmt: skip
    assert finding_matches(right, region, ())
    assert not finding_matches(right.model_copy(update={"claim_ref": "JDG-1"}), region, ())
    assert not finding_matches(right.model_copy(update={"claim_evidence": "borrow it"}), region, ())
    assert not finding_matches(right.model_copy(update={"kind": "CONSEQUENCE"}), region, ())
    clash = SemanticFinding(kind="ACTOR", direction="CONTRADICTORY", proposition_evidence="x",
                            claim_ref="JDG-2", claim_evidence="guests")  # fmt: skip
    assert not finding_matches(clash, region, ())
