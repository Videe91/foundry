"""Semantic completeness (design 2026-09-30): the domain law and its durable record.

Proposition accounting proves every proposition got a disposition. This proves nothing about
MEANING: that every operative part of a proposition survived into the claim(s) disposing of
it. Semantic completeness is a separate, independent check whose verdict is recorded before any
Call-2 proposal may mutate accepted state. This file covers the deterministic part: the shape
of a verifier's report, the outcome law, the structured failure and the replayable record.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.semantic_completeness import (
    INCOMPLETE_PROPOSITION_MEANING,
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    CompletenessReport,
    CompletenessRequest,
    PropositionReview,
    PropositionVerdict,
    ReviewedClaim,
    VerifierIdentity,
    completeness_outcome,
    completeness_request_sha256,
    incomplete_meanings,
    report_findings,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.model_runtime.domain import REQUIRED_TIER_BY_TASK, ModelTask, ModelTier

AT = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
WRITER = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v6")
VERIFIER = VerifierIdentity(
    provider="openai", model="gpt-6-astra", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION
)


def _claim(ref: str, predicate: str, value: str, role: str = "ASSERTED") -> ReviewedClaim:
    return ReviewedClaim(
        ref=ref, role=role, subject="Service credit", predicate=predicate, value=value
    )  # type: ignore[arg-type]


def _k_credit() -> CompletenessRequest:
    return CompletenessRequest(
        project_id="P",
        subject_invocation_id="INV-CALL-2",
        propositions=(
            PropositionReview(
                proposition_id="p13",
                statement="The service credit for an unavailable vehicle must be claimed in the "
                "app within 48 hours after the reservation start, and a later claim is refused.",
                source_sentences=(
                    "The service credit for an unavailable vehicle must be claimed in the app "
                    "within 48 hours after the reservation start.",
                    "A claim made later is refused.",
                ),
                disposition="ASSERT",
                claims=(_claim("JDG-p13", "claim_deadline_after_reservation_start", "48 hours"),),
            ),
            PropositionReview(
                proposition_id="p14",
                statement="The claim must name the reservation and include a photo of the vehicle.",
                source_sentences=("The claim must name the reservation and include a photo.",),
                disposition="ASSERT",
                claims=(_claim("JDG-p14", "claim_contents", "name the reservation; photo"),),
            ),
        ),
    )


def _verdict(
    pid: str, verdict: str, refs: tuple[str, ...], **regions: tuple[str, ...]
) -> PropositionVerdict:
    return PropositionVerdict(proposition_id=pid, verdict=verdict, claim_refs=refs, **regions)  # type: ignore[arg-type]


# ------------------------------------------------------------------ identity


def test_the_verifier_is_its_own_certified_task_and_policy() -> None:
    assert SEMANTIC_COMPLETENESS_POLICY_VERSION == "ie2-semantic-completeness-v1"
    assert ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION in REQUIRED_TIER_BY_TASK
    assert REQUIRED_TIER_BY_TASK[ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION] is ModelTier.REASONER


def test_the_request_digest_is_deterministic_and_content_bound() -> None:
    a, b = _k_credit(), _k_credit()
    assert completeness_request_sha256(a) == completeness_request_sha256(b)
    changed = a.model_copy(update={"subject_invocation_id": "INV-OTHER"})
    assert completeness_request_sha256(changed) != completeness_request_sha256(a)


# ------------------------------------------------------------------ the verdict shape


def test_a_verdict_carries_regions_exactly_when_it_is_not_complete() -> None:
    _verdict("p", "COMPLETE", ("c",))
    _verdict("p", "INCOMPLETE", ("c",), missing=("a later claim is refused",))
    _verdict("p", "OVERREACH", ("c",), unsupported=("the account is suspended",))
    _verdict("p", "CONTRADICTORY", ("c",), contradictory=("two different amounts",))
    with pytest.raises(ValidationError):
        _verdict("p", "COMPLETE", ("c",), missing=("x",))
    with pytest.raises(ValidationError):
        _verdict("p", "INCOMPLETE", ("c",))
    with pytest.raises(ValidationError):
        _verdict("p", "OVERREACH", ("c",))
    with pytest.raises(ValidationError):
        _verdict("p", "CONTRADICTORY", ("c",))


def test_the_report_carries_no_rewrite_no_disposition_and_no_claim() -> None:
    fields = set(CompletenessReport.model_fields) | set(PropositionVerdict.model_fields)
    assert not fields & {"corrected_claim", "claim", "value", "predicate", "kind", "disposition"}


def test_a_report_must_judge_every_proposition_once_against_exactly_its_claims() -> None:
    request = _k_credit()
    good = CompletenessReport(
        verdicts=(
            _verdict("p13", "COMPLETE", ("JDG-p13",)),
            _verdict("p14", "COMPLETE", ("JDG-p14",)),
        )
    )
    assert report_findings(request, good) == ()
    missing = CompletenessReport(verdicts=(_verdict("p13", "COMPLETE", ("JDG-p13",)),))
    assert report_findings(request, missing) == ("MISSING_VERDICT: p14",)
    doubled = CompletenessReport(
        verdicts=(*good.verdicts, _verdict("p14", "COMPLETE", ("JDG-p14",)))
    )
    assert report_findings(request, doubled) == ("DUPLICATE_VERDICT: p14",)
    unknown = CompletenessReport(verdicts=(*good.verdicts, _verdict("p99", "COMPLETE", ("x",))))
    assert report_findings(request, unknown) == ("UNKNOWN_PROPOSITION: p99",)
    swapped = CompletenessReport(
        verdicts=(
            _verdict("p13", "COMPLETE", ("JDG-p14",)),
            _verdict("p14", "COMPLETE", ("JDG-p14",)),
        )
    )
    assert report_findings(request, swapped) == ("WRONG_CLAIM_REFERENCES: p13",)


def test_a_faithful_decomposition_is_judged_against_the_union_of_its_claims() -> None:
    request = CompletenessRequest(
        project_id="P",
        subject_invocation_id="INV",
        propositions=(
            PropositionReview(
                proposition_id="p05",
                statement="The reservation is made in the app and states its start and end time.",
                source_sentences=("The reservation is made in the app and states its times.",),
                disposition="ASSERT",
                claims=(
                    _claim("c1", "booking_channel", "Kestrel app"),
                    _claim("c2", "stated_start_and_end_times", "start time and end time"),
                ),
            ),
        ),
    )
    report = CompletenessReport(verdicts=(_verdict("p05", "COMPLETE", ("c1", "c2")),))
    assert report_findings(request, report) == ()
    assert completeness_outcome(request, report, verifier=VERIFIER, writer=WRITER) == ("PASS", ())


# ------------------------------------------------------------------ the outcome law


def test_every_non_complete_verdict_fails_the_whole_response() -> None:
    request = _k_credit()
    for verdict, regions in (
        ("INCOMPLETE", {"missing": ("a later claim is refused",)}),
        ("OVERREACH", {"unsupported": ("the account is suspended",)}),
        ("CONTRADICTORY", {"contradictory": ("the deadline is both 24 and 48 hours",)}),
    ):
        report = CompletenessReport(
            verdicts=(
                _verdict("p13", verdict, ("JDG-p13",), **regions),
                _verdict("p14", "COMPLETE", ("JDG-p14",)),
            )
        )
        outcome, codes = completeness_outcome(request, report, verifier=VERIFIER, writer=WRITER)
        assert (outcome, codes) == ("FAIL", (INCOMPLETE_PROPOSITION_MEANING,)), verdict


def test_a_malformed_report_fails_and_says_so() -> None:
    request = _k_credit()
    report = CompletenessReport(verdicts=(_verdict("p13", "COMPLETE", ("JDG-p13",)),))
    assert completeness_outcome(request, report, verifier=VERIFIER, writer=WRITER) == (
        "FAIL",
        ("VERIFIER_OUTPUT_INVALID",),
    )


def test_a_verifier_that_is_not_independent_of_the_writer_fails() -> None:
    request = _k_credit()
    report = CompletenessReport(
        verdicts=(
            _verdict("p13", "COMPLETE", ("JDG-p13",)),
            _verdict("p14", "COMPLETE", ("JDG-p14",)),
        )
    )
    same = VerifierIdentity(
        provider="xai", model="grok-4.6", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION
    )
    assert completeness_outcome(request, report, verifier=same, writer=WRITER) == (
        "FAIL",
        ("VERIFIER_NOT_INDEPENDENT",),
    )


def test_the_k_credit_failure_names_the_proposition_claims_and_missing_region() -> None:
    request = _k_credit()
    report = CompletenessReport(
        verdicts=(
            _verdict("p13", "INCOMPLETE", ("JDG-p13",), missing=("a later claim is refused",)),
            _verdict("p14", "COMPLETE", ("JDG-p14",)),
        )
    )
    (failure,) = incomplete_meanings(request, report, verification_id="VER-1")
    assert failure.code == INCOMPLETE_PROPOSITION_MEANING
    assert failure.proposition_id == "p13"
    assert failure.claim_refs == ("JDG-p13",)
    assert failure.verification_id == "VER-1"
    assert failure.missing == ("a later claim is refused",)
    assert failure.unsupported == () and failure.contradictory == ()
