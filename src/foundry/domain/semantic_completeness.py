"""Semantic completeness of a claim-writing proposal (design 2026-09-30).

Proposition accounting proves bookkeeping: every accountable sentence is carried, every
proposition the model listed got exactly one lawful disposition. It proves nothing about
MEANING. ``K-CREDIT-4`` (validation v6) passed every accounting law: the model's own
proposition stated "must be claimed within 48 hours, and a later claim is refused", and the
one claim written for it said only ``deadline = 48 hours``.

The law this module carries: before a Call-2 proposal may mutate accepted state, an
independent verifier must judge, for every proposition the model itself supplied, whether the
claim(s) disposing of it (the union: asserted claims, or the supported existing claim)
preserve every operative assertion of the proposition without adding a contradictory or
materially different one. Paraphrase is not a failure; a faithful decomposition is judged by
the union; claim count is irrelevant.

Verdicts: ``COMPLETE``; ``INCOMPLETE`` (``missing`` regions); ``OVERREACH`` (``unsupported``
regions: meaning the proposition does not state); ``CONTRADICTORY`` (``contradictory``
regions). The verifier never proposes a claim, rewrites meaning, or chooses a disposition:
its report has no field for any of them.

Deterministic here: the request's shape and digest, the report's validity (every proposition
judged exactly once, against exactly its own claims), the independence of the verifier from the
writer, the all-or-nothing outcome (any non-``COMPLETE`` verdict fails the whole response) and
the structured failure ``INCOMPLETE_PROPOSITION_MEANING``. The judgement itself is the
verifier's, recorded durably (``CompletenessRecord``) and never recomputed on replay.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final, Literal

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, independent

__all__ = [
    "INCOMPLETE_PROPOSITION_MEANING",
    "SEMANTIC_COMPLETENESS_POLICY_VERSION",
    "VERIFIED_ASSIMILATION_PIPELINE",
    "CompletenessOutcome",
    "CompletenessRecord",
    "CompletenessReport",
    "CompletenessRequest",
    "CompletenessVerdict",
    "IncompletePropositionMeaning",
    "PropositionReview",
    "PropositionVerdict",
    "ReviewedClaim",
    "VerifierIdentity",
    "completeness_outcome",
    "completeness_request_sha256",
    "incomplete_meanings",
    "report_findings",
]

SEMANTIC_COMPLETENESS_POLICY_VERSION: Final = "ie2-semantic-completeness-v1"
"""The verifier's own policy identity (its instruction and output contract), separate from the
Call-1/Call-2 locus policy, which is unchanged."""
VERIFIED_ASSIMILATION_PIPELINE: Final = "ie2-verified-assimilation-v1"
"""The runtime pipeline identity: Call 1 (concern/binding), Call 2 (claim writing), Call 3
(semantic completeness verification), then admission."""
INCOMPLETE_PROPOSITION_MEANING: Final = "INCOMPLETE_PROPOSITION_MEANING"

CompletenessVerdict = Literal["COMPLETE", "INCOMPLETE", "OVERREACH", "CONTRADICTORY"]
CompletenessOutcome = Literal["PASS", "FAIL"]
Disposition = Literal["ASSERT", "SUPPORT", "ASSERT_SUPERSEDE"]


class ReviewedClaim(FrozenModel):
    """One claim as the verifier sees it: never an id it could act on, only a reference."""

    ref: str = Field(min_length=1)
    """The asserting judgment's id (ASSERTED) or the existing claim's id (SUPPORTED, RETIRED)."""
    role: Literal["ASSERTED", "SUPPORTED", "RETIRED"]
    subject: str
    predicate: str
    value: str


class PropositionReview(FrozenModel):
    proposition_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    """The model's own statement of the proposition."""
    source_sentences: tuple[str, ...] = Field(min_length=1)
    disposition: Disposition
    claims: tuple[ReviewedClaim, ...] = Field(min_length=1)
    """The claims disposing of it: newly asserted (ASSERT) or the supported existing one."""
    retired: tuple[ReviewedClaim, ...] = ()
    """For ASSERT_SUPERSEDE: the claims it would retire. Context only; never judged complete."""

    @model_validator(mode="after")
    def validate_roles(self) -> PropositionReview:
        want = "SUPPORTED" if self.disposition == "SUPPORT" else "ASSERTED"
        if any(c.role != want for c in self.claims):
            raise ValueError(f"a {self.disposition} proposition is judged by {want} claims")
        if any(c.role != "RETIRED" for c in self.retired):
            raise ValueError("retired context holds RETIRED claims only")
        if bool(self.retired) != (self.disposition == "ASSERT_SUPERSEDE"):
            raise ValueError("only an ASSERT_SUPERSEDE proposition names retired claims")
        return self


class CompletenessRequest(FrozenModel):
    project_id: str
    subject_invocation_id: str
    """The Call-2 invocation whose proposal is being verified."""
    propositions: tuple[PropositionReview, ...] = Field(min_length=1)


class PropositionVerdict(FrozenModel):
    proposition_id: str = Field(min_length=1)
    verdict: CompletenessVerdict
    claim_refs: tuple[str, ...] = Field(min_length=1)
    """The claims the verdict was reached on: exactly the proposition's claims."""
    missing: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    contradictory: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_regions(self) -> PropositionVerdict:
        regions = {
            "INCOMPLETE": self.missing,
            "OVERREACH": self.unsupported,
            "CONTRADICTORY": self.contradictory,
        }
        if self.verdict == "COMPLETE":
            if self.missing or self.unsupported or self.contradictory:
                raise ValueError("a COMPLETE verdict names no region")
        elif not regions[self.verdict]:
            raise ValueError(f"an {self.verdict} verdict names the region it is about")
        return self


class CompletenessReport(FrozenModel):
    """The verifier's whole output: a verdict per proposition, nothing else."""

    verdicts: tuple[PropositionVerdict, ...]


class VerifierIdentity(FrozenModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)

    def as_fingerprint(self) -> ReasonerFingerprint:
        return ReasonerFingerprint(
            provider=self.provider, model=self.model, policy_version=self.policy_version
        )


class IncompletePropositionMeaning(FrozenModel):
    """The structured failure: which proposition, which claims, what the verifier found."""

    code: Literal["INCOMPLETE_PROPOSITION_MEANING"] = "INCOMPLETE_PROPOSITION_MEANING"
    proposition_id: str
    verdict: CompletenessVerdict
    claim_refs: tuple[str, ...]
    verification_id: str
    missing: tuple[str, ...]
    unsupported: tuple[str, ...]
    contradictory: tuple[str, ...]


class CompletenessRecord(FrozenModel):
    """The durable audit of one verification. It changes no claim; replay reads it."""

    verification_id: str = Field(min_length=1)
    project_id: str
    subject_invocation_id: str
    writer: ReasonerFingerprint
    verifier: VerifierIdentity
    verifier_invocation_id: str
    request_sha256: str
    request: CompletenessRequest
    proposed_judgment_ids: tuple[str, ...]
    report: CompletenessReport | None
    """``None`` when the verifier's output could not be parsed as a report."""
    outcome: CompletenessOutcome
    failure_codes: tuple[str, ...]
    failures: tuple[IncompletePropositionMeaning, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    wall_clock_ms: int | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> CompletenessRecord:
        if (self.outcome == "PASS") != (not self.failure_codes):
            raise ValueError("a PASS carries no failure code and a FAIL carries at least one")
        if self.request_sha256 != completeness_request_sha256(self.request):
            raise ValueError("request_sha256 must be the digest of the recorded request")
        return self


def completeness_request_sha256(request: CompletenessRequest) -> str:
    return hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def report_findings(request: CompletenessRequest, report: CompletenessReport) -> tuple[str, ...]:
    """Structural validity of a report: every proposition judged once, on its own claims."""
    expected = {p.proposition_id: p for p in request.propositions}
    seen: dict[str, int] = {}
    out: list[str] = []
    for v in report.verdicts:
        if v.proposition_id not in expected:
            out.append(f"UNKNOWN_PROPOSITION: {v.proposition_id}")
            continue
        seen[v.proposition_id] = seen.get(v.proposition_id, 0) + 1
        if seen[v.proposition_id] > 1:
            out.append(f"DUPLICATE_VERDICT: {v.proposition_id}")
            continue
        refs = {c.ref for c in expected[v.proposition_id].claims}
        if set(v.claim_refs) != refs:
            out.append(f"WRONG_CLAIM_REFERENCES: {v.proposition_id}")
    for pid in expected:
        if pid not in seen:
            out.append(f"MISSING_VERDICT: {pid}")
    return tuple(out)


def completeness_outcome(
    request: CompletenessRequest,
    report: CompletenessReport | None,
    *,
    verifier: VerifierIdentity,
    writer: ReasonerFingerprint,
) -> tuple[CompletenessOutcome, tuple[str, ...]]:
    """All-or-nothing: PASS only for a valid report by an independent verifier in which every
    proposition is COMPLETE."""
    if not independent(verifier.as_fingerprint(), writer):
        return "FAIL", ("VERIFIER_NOT_INDEPENDENT",)
    if report is None or report_findings(request, report):
        return "FAIL", ("VERIFIER_OUTPUT_INVALID",)
    if any(v.verdict != "COMPLETE" for v in report.verdicts):
        return "FAIL", (INCOMPLETE_PROPOSITION_MEANING,)
    return "PASS", ()


def incomplete_meanings(
    request: CompletenessRequest, report: CompletenessReport, *, verification_id: str
) -> tuple[IncompletePropositionMeaning, ...]:
    return tuple(
        IncompletePropositionMeaning(
            proposition_id=v.proposition_id,
            verdict=v.verdict,
            claim_refs=v.claim_refs,
            verification_id=verification_id,
            missing=v.missing,
            unsupported=v.unsupported,
            contradictory=v.contradictory,
        )
        for v in report.verdicts
        if v.verdict != "COMPLETE"
    )
