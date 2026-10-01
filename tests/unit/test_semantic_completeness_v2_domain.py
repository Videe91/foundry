"""Structured semantic completeness (``ie2-semantic-completeness-v2``): the domain contract.

v1 asked the verifier for free-text ``missing`` / ``unsupported`` / ``contradictory`` regions,
and certification then tried to decide whether that English named the right meaning (exams
v2-v5: four rounds of correct verdicts rejected for their wording). v2 asks the verifier for
STRUCTURED findings: a kind, a direction, and exact evidence quoted from the proposition and,
where the direction needs it, from a named claim. The model decides meaning; deterministic code
only checks that the ids exist, the quotes exist where they say they do, the required fields
are present and the verdict follows from the findings. It never decides whether two English
phrasings mean the same thing.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from foundry.domain.semantic_completeness import (
    FINDING_KINDS,
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
    STRUCTURED_REPORT_FORMAT,
    VERIFIED_ASSIMILATION_PIPELINE,
    CompletenessRecord,
    CompletenessReport,
    CompletenessRequest,
    FindingKind,
    PropositionReview,
    PropositionVerdict,
    ReviewedClaim,
    SemanticFinding,
    StructuredCompletenessReport,
    StructuredPropositionVerdict,
    VerifierIdentity,
    completeness_outcome,
    completeness_request_sha256,
    grounded,
    incomplete_meanings,
    report_findings,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint

WRITER = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v6")
V2 = VerifierIdentity(
    provider="verifier", model="m", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION_V2
)
V1 = VerifierIdentity(
    provider="verifier", model="m", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION
)

K_CREDIT = PropositionReview(
    proposition_id="p13",
    statement="The service credit for an unavailable vehicle must be claimed in the app within 48 "
    "hours after the reservation start, and a later claim is refused.",
    source_sentences=(
        "The service credit for an unavailable vehicle must be claimed in the app within 48 hours "
        "after the reservation start.",
        "A claim made later is refused.",
    ),
    disposition="ASSERT",
    claims=(
        ReviewedClaim(
            ref="JDG-1",
            role="ASSERTED",
            subject="Service credit for an unavailable reserved vehicle",
            predicate="claim_deadline_after_reservation_start",
            value="48 hours",
        ),
    ),
)
LOAN = PropositionReview(
    proposition_id="p2",
    statement="A loan lasts two weeks.",
    source_sentences=("A loan lasts two weeks.",),
    disposition="SUPPORT",
    claims=(
        ReviewedClaim(
            ref="CLM-1", role="SUPPORTED", subject="Library loans", predicate="loan_period",
            value="21 days",
        ),
    ),
)  # fmt: skip
REQUEST = CompletenessRequest(
    project_id="P", subject_invocation_id="INV-1", propositions=(K_CREDIT, LOAN)
)


def _missing(kind: FindingKind, quote: str) -> SemanticFinding:
    return SemanticFinding(kind=kind, direction="MISSING", proposition_evidence=quote)


K_CREDIT_FINDINGS = (
    _missing("CHANNEL", "claimed in the app"),
    _missing("CONSEQUENCE", "A claim made later is refused"),
)
LOAN_CLASH = SemanticFinding(
    kind="TIMING",
    direction="CONTRADICTORY",
    proposition_evidence="two weeks",
    claim_ref="CLM-1",
    claim_evidence="21 days",
)


def _report(*verdicts: StructuredPropositionVerdict) -> StructuredCompletenessReport:
    return StructuredCompletenessReport(report_format=STRUCTURED_REPORT_FORMAT, verdicts=verdicts)


def _v(
    review: PropositionReview, verdict: str, *findings: SemanticFinding
) -> StructuredPropositionVerdict:
    return StructuredPropositionVerdict(
        proposition_id=review.proposition_id,
        verdict=verdict,  # type: ignore[arg-type]
        claim_refs=tuple(c.ref for c in review.claims),
        findings=findings,
    )


GOOD = _report(
    _v(K_CREDIT, "INCOMPLETE", *K_CREDIT_FINDINGS), _v(LOAN, "CONTRADICTORY", LOAN_CLASH)
)


# --- identity -----------------------------------------------------------------------------------


def test_v2_is_a_new_policy_beside_an_unchanged_v1_and_pipeline() -> None:
    assert SEMANTIC_COMPLETENESS_POLICY_VERSION == "ie2-semantic-completeness-v1"
    assert SEMANTIC_COMPLETENESS_POLICY_VERSION_V2 == "ie2-semantic-completeness-v2"
    assert STRUCTURED_REPORT_FORMAT == "ie2-semantic-completeness-report.v2"
    assert VERIFIED_ASSIMILATION_PIPELINE == "ie2-verified-assimilation-v1"


def test_the_finding_taxonomy_is_the_operative_assertions_foundry_already_names() -> None:
    assert set(FINDING_KINDS) == set(get_args(FindingKind)) == {
        "ACTOR", "PERMISSION", "OBLIGATION", "QUANTITY_LIMIT", "TIMING", "TIME_ANCHOR",
        "DEADLINE", "CONDITION", "ELIGIBILITY", "CONSEQUENCE", "EXCEPTION", "DESTINATION",
        "REPETITION", "CHANNEL",
    }  # fmt: skip


# --- the shape of a finding -----------------------------------------------------------------------


def test_each_direction_requires_exactly_its_evidence() -> None:
    _missing("CHANNEL", "in the app")
    SemanticFinding(kind="CONDITION", direction="UNSUPPORTED", claim_ref="J", claim_evidence="x")
    assert LOAN_CLASH.claim_ref == "CLM-1"
    bad = [
        dict(kind="CHANNEL", direction="MISSING"),
        dict(kind="CHANNEL", direction="MISSING", proposition_evidence="x", claim_ref="J"),
        dict(kind="CHANNEL", direction="MISSING", proposition_evidence="x", claim_evidence="y"),
        dict(kind="CONDITION", direction="UNSUPPORTED", claim_ref="J"),
        dict(kind="CONDITION", direction="UNSUPPORTED", claim_evidence="x"),
        dict(kind="CONDITION", direction="UNSUPPORTED", claim_ref="J", claim_evidence="x",
             proposition_evidence="y"),
        dict(kind="TIMING", direction="CONTRADICTORY", claim_ref="J", claim_evidence="x"),
        dict(kind="TIMING", direction="CONTRADICTORY", proposition_evidence="y", claim_ref="J"),
        dict(kind="DURATION", direction="MISSING", proposition_evidence="x"),
        dict(kind="TIMING", direction="WRONG", proposition_evidence="x"),
        dict(kind="TIMING", direction="MISSING", proposition_evidence="   "),
    ]  # fmt: skip
    for fields in bad:
        with pytest.raises(ValidationError):
            SemanticFinding(**fields)  # type: ignore[arg-type]


def test_the_verdict_follows_from_the_findings_by_the_sealed_precedence() -> None:
    clash, gap = LOAN_CLASH, _missing("CHANNEL", "x")
    extra = SemanticFinding(
        kind="CONDITION", direction="UNSUPPORTED", claim_ref="J", claim_evidence="x"
    )
    assert _v(LOAN, "COMPLETE").findings == ()
    good: tuple[tuple[str, tuple[SemanticFinding, ...]], ...] = (
        ("CONTRADICTORY", (clash, gap, extra)),
        ("INCOMPLETE", (gap, extra)),
        ("OVERREACH", (extra,)),
    )
    for verdict, findings in good:
        _v(LOAN, verdict, *findings)
    bad: tuple[tuple[str, tuple[SemanticFinding, ...]], ...] = (
        ("COMPLETE", (gap,)),
        ("INCOMPLETE", ()),
        ("INCOMPLETE", (clash,)),
        ("OVERREACH", (gap, extra)),
        ("CONTRADICTORY", (gap,)),
    )
    for verdict, wrong in bad:
        with pytest.raises(ValidationError):
            _v(LOAN, verdict, *wrong)


# --- deterministic grounding ----------------------------------------------------------------------


def test_grounding_is_whole_word_containment_with_case_space_and_punctuation_folded() -> None:
    text = "A claim made later is refused."
    assert grounded("A claim made later is refused", text)
    assert grounded("a CLAIM  made later", text)
    assert grounded('"claim made later is refused."', text)
    assert not grounded("a claim made late", text), "no partial word"
    assert not grounded("a later claim is refused", text), "no paraphrase: that is the model's job"
    assert not grounded("", text) and not grounded("...", text)


def test_a_well_grounded_report_has_no_finding() -> None:
    assert report_findings(REQUEST, GOOD) == ()


@pytest.mark.parametrize(
    ("finding", "code"),
    [
        (_missing("CHANNEL", "claimed by phone"), "UNGROUNDED_PROPOSITION_EVIDENCE"),
        (
            SemanticFinding(
                kind="CONDITION",
                direction="UNSUPPORTED",
                claim_ref="JDG-9",
                claim_evidence="48 hours",
            ),
            "UNKNOWN_CLAIM_REFERENCE",
        ),  # fmt: skip
        (
            SemanticFinding(
                kind="CONDITION",
                direction="UNSUPPORTED",
                claim_ref="JDG-1",
                claim_evidence="72 hours",
            ),
            "UNGROUNDED_CLAIM_EVIDENCE",
        ),  # fmt: skip
        (
            SemanticFinding(
                kind="DEADLINE",
                direction="CONTRADICTORY",
                proposition_evidence="two weeks",
                claim_ref="CLM-1",
                claim_evidence="21 days",
            ),
            "UNKNOWN_CLAIM_REFERENCE",
        ),  # fmt: skip
    ],
)
def test_evidence_that_does_not_exist_where_it_says_is_refused(
    finding: SemanticFinding, code: str
) -> None:
    verdict = "CONTRADICTORY" if finding.direction == "CONTRADICTORY" else "INCOMPLETE"
    report = _report(_v(K_CREDIT, verdict, K_CREDIT_FINDINGS[0], finding), _v(LOAN, "COMPLETE"))
    assert any(p.startswith(code) for p in report_findings(REQUEST, report)), report_findings(
        REQUEST, report
    )


def test_evidence_is_grounded_in_its_own_proposition_only() -> None:
    other = _missing("TIMING", "two weeks")
    report = _report(_v(K_CREDIT, "INCOMPLETE", other), _v(LOAN, "COMPLETE"))
    assert report_findings(REQUEST, report) == ("UNGROUNDED_PROPOSITION_EVIDENCE: p13",)


def test_duplicate_and_conflicting_findings_are_refused() -> None:
    dup = _report(
        _v(K_CREDIT, "INCOMPLETE", K_CREDIT_FINDINGS[0], K_CREDIT_FINDINGS[0]), _v(LOAN, "COMPLETE")
    )
    assert "DUPLICATE_FINDING: p13" in report_findings(REQUEST, dup)
    flip = SemanticFinding(kind="TIMING", direction="MISSING", proposition_evidence="two weeks")
    conflict = _report(_v(K_CREDIT, "COMPLETE"), _v(LOAN, "CONTRADICTORY", LOAN_CLASH, flip))
    assert "CONFLICTING_FINDINGS: p2" in report_findings(REQUEST, conflict)


def test_v1_structural_laws_still_apply_to_a_structured_report() -> None:
    assert report_findings(REQUEST, _report(_v(LOAN, "COMPLETE"))) == ("MISSING_VERDICT: p13",)
    wrong = StructuredPropositionVerdict(
        proposition_id="p2", verdict="COMPLETE", claim_refs=("CLM-2",), findings=()
    )
    assert "WRONG_CLAIM_REFERENCES: p2" in report_findings(
        REQUEST, _report(_v(K_CREDIT, "COMPLETE"), wrong)
    )


# --- the outcome ------------------------------------------------------------------------------


def test_an_ungrounded_structured_report_is_invalid_output_and_fails() -> None:
    ungrounded = _report(
        _v(K_CREDIT, "INCOMPLETE", _missing("CHANNEL", "claimed by post")), _v(LOAN, "COMPLETE")
    )
    assert completeness_outcome(REQUEST, ungrounded, verifier=V2, writer=WRITER) == (
        "FAIL",
        ("VERIFIER_OUTPUT_INVALID",),
    )


def test_the_report_format_must_match_the_verifier_policy() -> None:
    complete_v2 = _report(_v(K_CREDIT, "COMPLETE"), _v(LOAN, "COMPLETE"))
    complete_v1 = CompletenessReport(
        verdicts=tuple(
            PropositionVerdict(
                proposition_id=p.proposition_id,
                verdict="COMPLETE",
                claim_refs=tuple(c.ref for c in p.claims),
            )
            for p in REQUEST.propositions
        )
    )
    assert completeness_outcome(REQUEST, complete_v2, verifier=V2, writer=WRITER) == ("PASS", ())
    assert completeness_outcome(REQUEST, complete_v1, verifier=V1, writer=WRITER) == ("PASS", ())
    assert completeness_outcome(REQUEST, complete_v1, verifier=V2, writer=WRITER)[0] == "FAIL"
    assert completeness_outcome(REQUEST, complete_v2, verifier=V1, writer=WRITER)[0] == "FAIL"


def test_a_grounded_non_complete_report_fails_with_structured_meanings() -> None:
    assert completeness_outcome(REQUEST, GOOD, verifier=V2, writer=WRITER) == (
        "FAIL",
        ("INCOMPLETE_PROPOSITION_MEANING",),
    )
    k, loan = incomplete_meanings(REQUEST, GOOD, verification_id="VER-1")
    assert k.findings == K_CREDIT_FINDINGS and k.missing == (
        "claimed in the app",
        "A claim made later is refused",
    )
    assert loan.findings == (LOAN_CLASH,) and loan.contradictory == ("two weeks / CLM-1: 21 days",)


# --- the durable record -----------------------------------------------------------------------


def _record(report: object, verifier: VerifierIdentity) -> CompletenessRecord:
    return CompletenessRecord(
        verification_id="VER-1",
        project_id="P",
        subject_invocation_id="INV-1",
        writer=WRITER,
        verifier=verifier,
        verifier_invocation_id="V-1",
        request_sha256=completeness_request_sha256(REQUEST),
        request=REQUEST,
        proposed_judgment_ids=("JDG-1",),
        report=report,  # type: ignore[arg-type]
        outcome="FAIL",
        failure_codes=("INCOMPLETE_PROPOSITION_MEANING",),
    )


def test_a_v2_record_round_trips_its_structured_report() -> None:
    record = _record(GOOD, V2)
    again = CompletenessRecord.model_validate_json(record.model_dump_json())
    assert again == record and isinstance(again.report, StructuredCompletenessReport)


def test_a_v1_record_still_reads_as_v1_and_formats_cannot_be_mixed() -> None:
    v1 = CompletenessReport(
        verdicts=(
            PropositionVerdict(
                proposition_id="p13", verdict="INCOMPLETE", claim_refs=("JDG-1",),
                missing=("a later claim is refused",),
            ),
            PropositionVerdict(proposition_id="p2", verdict="COMPLETE", claim_refs=("CLM-1",)),
        )
    )  # fmt: skip
    record = _record(v1, V1)
    again = CompletenessRecord.model_validate_json(record.model_dump_json())
    assert isinstance(again.report, CompletenessReport) and again == record
    assert "report_format" not in record.model_dump_json()
    with pytest.raises(ValidationError):
        _record(GOOD, V1)
    with pytest.raises(ValidationError):
        _record(v1, V2)
