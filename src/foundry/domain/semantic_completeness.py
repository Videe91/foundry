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

**Policy v2 (``ie2-semantic-completeness-v2``): structured findings.** v1's regions are free
text, and certifying a verifier then meant deciding whether its English named the right meaning
(exams v2-v5: correct verdicts rejected, round after round, for their wording). A v2 report
states each finding as a ``SemanticFinding``: a kind, a direction (MISSING / UNSUPPORTED /
CONTRADICTORY) and exact evidence quoted from the proposition (its statement or a source
sentence) and, where the direction needs it, from a named claim. The model decides meaning;
this module only checks that every id exists, every quote occurs where it says it does
(``grounded``: whole words, case / whitespace / punctuation folded, never a paraphrase), the
required fields are present, nothing is duplicated or contradicts itself, and the verdict
follows from the findings. It never decides whether two phrasings mean the same thing. A record
carries the report in the format of the policy that produced it; v1 records are unchanged.

**Policy v3 (``ie2-semantic-completeness-v3``): the runtime contract (Intent Engine runtime
reset).** One question per proposition -- is it fully preserved in its claims? -- answered
``COMPLETE`` or ``NOT_COMPLETE`` with an optional ``note`` for humans and logs. Deterministic code
checks the shape only (every proposition judged exactly once, known ids, the policy's format,
the verifier's independence) and never reads the note. v1 and v2 stay readable and replayable.

**Policy v4 (``ie2-semantic-admission-v4``): the semantic admission verifier.** The writer may
miss a contradiction, so the independent verifier is the backstop. It receives an
``AdmissionRequest`` (the v3 request plus the current claims at the concerns the response
touches) and answers, per proposition, ``completeness`` and ``consistency`` (``NO_CONFLICT`` /
``CONFLICT`` / ``UNCERTAIN``), a CONFLICT naming the shown claims it conflicts with. Deterministic
code checks only shape, ids and that each named claim was shown; it never decides that anything
conflicts and never reads the note. Codes: ``INCOMPLETE_PROPOSITION_MEANING``,
``SEMANTIC_CONFLICT``, ``SEMANTIC_UNCERTAIN``. A v4 report answers only an ``AdmissionRequest``
and an ``AdmissionRequest`` only a v4 report: anything else is invalid output.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Final, Literal, get_args

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, independent

__all__ = [
    "FINDING_KINDS",
    "INCOMPLETE_PROPOSITION_MEANING",
    "SEMANTIC_COMPLETENESS_POLICY_VERSION",
    "SEMANTIC_COMPLETENESS_POLICY_VERSION_V2",
    "SEMANTIC_COMPLETENESS_POLICY_VERSION_V3",
    "ADMISSION_REPORT_FORMAT",
    "SEMANTIC_ADMISSION_POLICY_VERSION_V4",
    "SEMANTIC_CONFLICT",
    "SEMANTIC_UNCERTAIN",
    "AdmissionReport",
    "AdmissionRequest",
    "AdmissionVerdict",
    "ContextClaim",
    "STRUCTURED_REPORT_FORMAT",
    "VERDICT_REPORT_FORMAT",
    "VERIFIED_ASSIMILATION_PIPELINE",
    "AnyCompletenessReport",
    "CompletenessOutcome",
    "CompletenessRecord",
    "CompletenessReport",
    "CompletenessRequest",
    "CompletenessVerdict",
    "FindingDirection",
    "FindingKind",
    "IncompletePropositionMeaning",
    "PropositionCheck",
    "PropositionReview",
    "PropositionVerdict",
    "ReviewedClaim",
    "SemanticFinding",
    "StructuredCompletenessReport",
    "StructuredPropositionVerdict",
    "VerdictCompletenessReport",
    "VerifierIdentity",
    "completeness_outcome",
    "completeness_request_sha256",
    "grounded",
    "incomplete_meanings",
    "not_complete_proposition_ids",
    "report_findings",
    "report_in_policy_format",
]

SEMANTIC_COMPLETENESS_POLICY_VERSION: Final = "ie2-semantic-completeness-v1"
"""The verifier's own policy identity (its instruction and output contract), separate from the
Call-1/Call-2 locus policy, which is unchanged."""
VERIFIED_ASSIMILATION_PIPELINE: Final = "ie2-verified-assimilation-v1"
"""The runtime pipeline identity: Call 1 (concern/binding), Call 2 (claim writing), Call 3
(semantic completeness verification), then admission."""
INCOMPLETE_PROPOSITION_MEANING: Final = "INCOMPLETE_PROPOSITION_MEANING"
SEMANTIC_COMPLETENESS_POLICY_VERSION_V2: Final = "ie2-semantic-completeness-v2"
"""The structured-findings verifier policy: its own instruction and ``StructuredCompletenessReport``
output contract. v1 is unchanged and its records stay readable."""
STRUCTURED_REPORT_FORMAT: Final = "ie2-semantic-completeness-report.v2"
SEMANTIC_COMPLETENESS_POLICY_VERSION_V3: Final = "ie2-semantic-completeness-v3"
"""The runtime verifier policy: one COMPLETE / NOT_COMPLETE verdict per proposition."""
VERDICT_REPORT_FORMAT: Final = "ie2-semantic-completeness-report.v3"
SEMANTIC_ADMISSION_POLICY_VERSION_V4: Final = "ie2-semantic-admission-v4"
"""The semantic admission verifier: per proposition, completeness AND consistency with the
current claims at the concerns the response touches. v1-v3 are unchanged."""
ADMISSION_REPORT_FORMAT: Final = "ie2-semantic-admission-report.v4"
SEMANTIC_CONFLICT: Final = "SEMANTIC_CONFLICT"
SEMANTIC_UNCERTAIN: Final = "SEMANTIC_UNCERTAIN"

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


class ContextClaim(FrozenModel):
    """A current claim shown to the admission verifier (v4), by its real claim id."""

    claim_id: str = Field(min_length=1)
    subject: str
    predicate: str
    value: str


class AdmissionRequest(CompletenessRequest):
    """Policy v4: the completeness request plus the current claims at the concerns the response
    touches (never one it retires itself, never another concern's). Nothing else of state."""

    current_claims: tuple[ContextClaim, ...]


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


# --- policy v2: structured findings ---------------------------------------------------------------

FindingKind = Literal[
    "ACTOR",
    "PERMISSION",
    "OBLIGATION",
    "QUANTITY_LIMIT",
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
]
"""The operative assertions the verifier instruction already names (an actor, an obligation or
permission, a quantity or limit, a timing, a deadline, a condition or eligibility rule, a
consequence or effect, an exception, a destination, a repetition rule), with the time anchor a
timing or deadline is measured from and the channel through which something is done."""
FINDING_KINDS: Final[tuple[str, ...]] = get_args(FindingKind)
FindingDirection = Literal["MISSING", "UNSUPPORTED", "CONTRADICTORY"]

_HAS_WORD = re.compile(r"\w")


class SemanticFinding(FrozenModel):
    """One structured finding. Its evidence is quoted, never paraphrased:

    * MISSING: ``proposition_evidence`` -- the proposition's words for the assertion no claim
      states; no claim is cited.
    * UNSUPPORTED: ``claim_ref`` and ``claim_evidence`` -- the claim and its words that assert
      what the proposition does not.
    * CONTRADICTORY: all three -- the proposition's words, the claim and the claim's words that
      conflict with them.

    ``explanation`` is free text for audit; nothing ever reads its wording.
    """

    kind: FindingKind
    direction: FindingDirection
    proposition_evidence: str | None = None
    claim_ref: str | None = None
    claim_evidence: str | None = None
    explanation: str = ""

    @model_validator(mode="after")
    def validate_evidence(self) -> SemanticFinding:
        needs = {
            "MISSING": (True, False, False),
            "UNSUPPORTED": (False, True, True),
            "CONTRADICTORY": (True, True, True),
        }[self.direction]
        given = (
            self.proposition_evidence is not None,
            self.claim_ref is not None,
            self.claim_evidence is not None,
        )
        if given != needs:
            raise ValueError(f"a {self.direction} finding cites exactly its required evidence")
        for quote in (self.proposition_evidence, self.claim_evidence, self.claim_ref):
            if quote is not None and not _HAS_WORD.search(quote):
                raise ValueError("evidence and references are never empty")
        return self


_PRECEDENCE: Final = (
    ("CONTRADICTORY", "CONTRADICTORY"),
    ("MISSING", "INCOMPLETE"),
    ("UNSUPPORTED", "OVERREACH"),
)


class StructuredPropositionVerdict(FrozenModel):
    proposition_id: str = Field(min_length=1)
    verdict: CompletenessVerdict
    claim_refs: tuple[str, ...] = Field(min_length=1)
    findings: tuple[SemanticFinding, ...] = ()

    @model_validator(mode="after")
    def validate_verdict(self) -> StructuredPropositionVerdict:
        directions = {f.direction for f in self.findings}
        follows = next((v for d, v in _PRECEDENCE if d in directions), "COMPLETE")
        if self.verdict != follows:
            raise ValueError(
                f"verdict {self.verdict} does not follow from findings {sorted(directions)} "
                "(CONTRADICTORY > INCOMPLETE > OVERREACH; COMPLETE has none)"
            )
        return self


class StructuredCompletenessReport(FrozenModel):
    """A v2 verifier's whole output: one verdict per proposition, with structured findings."""

    report_format: Literal["ie2-semantic-completeness-report.v2"]
    verdicts: tuple[StructuredPropositionVerdict, ...]


class PropositionCheck(FrozenModel):
    """Policy v3: is this proposition fully preserved in its claims? ``note`` is for humans and
    logs only: no runtime decision ever reads it."""

    proposition_id: str = Field(min_length=1)
    verdict: Literal["COMPLETE", "NOT_COMPLETE"]
    note: str | None = None


class VerdictCompletenessReport(FrozenModel):
    """A v3 verifier's whole output: exactly one check per proposition, nothing else."""

    report_format: Literal["ie2-semantic-completeness-report.v3"]
    verdicts: tuple[PropositionCheck, ...]


class AdmissionVerdict(FrozenModel):
    """Policy v4, one proposition: is it preserved (``completeness``) and can it hold together
    with the current claims shown (``consistency``)? A CONFLICT names those claims; nothing else
    names any. ``note`` is for humans and logs only: no runtime decision ever reads it."""

    proposition_id: str = Field(min_length=1)
    completeness: Literal["COMPLETE", "NOT_COMPLETE"]
    consistency: Literal["NO_CONFLICT", "CONFLICT", "UNCERTAIN"]
    conflicting_claim_ids: tuple[str, ...] = ()
    note: str | None = None

    @model_validator(mode="after")
    def validate_conflict_names_claims(self) -> AdmissionVerdict:
        if (self.consistency == "CONFLICT") != bool(self.conflicting_claim_ids):
            raise ValueError("exactly a CONFLICT names the current claims it conflicts with")
        if len(set(self.conflicting_claim_ids)) != len(self.conflicting_claim_ids):
            raise ValueError("a conflicting claim is named once")
        return self


class AdmissionReport(FrozenModel):
    """A v4 verifier's whole output: exactly one verdict per proposition, nothing else."""

    report_format: Literal["ie2-semantic-admission-report.v4"]
    verdicts: tuple[AdmissionVerdict, ...]


def not_complete_proposition_ids(
    report: VerdictCompletenessReport | AdmissionReport,
) -> tuple[str, ...]:
    if isinstance(report, AdmissionReport):
        return tuple(v.proposition_id for v in report.verdicts if v.completeness == "NOT_COMPLETE")
    return tuple(v.proposition_id for v in report.verdicts if v.verdict == "NOT_COMPLETE")


AnyCompletenessReport = (
    CompletenessReport | StructuredCompletenessReport | VerdictCompletenessReport | AdmissionReport
)

_APOSTROPHE = re.compile(r"['\u2018\u2019`]")
_NON_WORD = re.compile(r"[\W_]+")


def _folded(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", _APOSTROPHE.sub("", text.casefold())).split())


def grounded(quote: str, text: str) -> bool:
    """Does ``quote`` occur in ``text`` as whole words? Case, whitespace and punctuation are
    folded; nothing else is. A paraphrase is never grounded: meaning is the model's job."""
    q = _folded(quote)
    return bool(q) and f" {q} " in f" {_folded(text)} "


def _expected_report(policy_version: str) -> type[AnyCompletenessReport] | None:
    formats: dict[str, type[AnyCompletenessReport]] = {
        SEMANTIC_COMPLETENESS_POLICY_VERSION: CompletenessReport,
        SEMANTIC_COMPLETENESS_POLICY_VERSION_V2: StructuredCompletenessReport,
        SEMANTIC_COMPLETENESS_POLICY_VERSION_V3: VerdictCompletenessReport,
        SEMANTIC_ADMISSION_POLICY_VERSION_V4: AdmissionReport,
    }
    return formats.get(policy_version)


class VerifierIdentity(FrozenModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)

    def as_fingerprint(self) -> ReasonerFingerprint:
        return ReasonerFingerprint(
            provider=self.provider, model=self.model, policy_version=self.policy_version
        )


class IncompletePropositionMeaning(FrozenModel):
    """The structured failure: which proposition, which claims, what the verifier found. A v2
    failure carries the verifier's ``findings``; its regions are their quoted evidence."""

    code: Literal["INCOMPLETE_PROPOSITION_MEANING"] = "INCOMPLETE_PROPOSITION_MEANING"
    proposition_id: str
    verdict: CompletenessVerdict
    claim_refs: tuple[str, ...]
    verification_id: str
    missing: tuple[str, ...]
    unsupported: tuple[str, ...]
    contradictory: tuple[str, ...]
    findings: tuple[SemanticFinding, ...] = ()


class CompletenessRecord(FrozenModel):
    """The durable audit of one verification. It changes no claim; replay reads it."""

    verification_id: str = Field(min_length=1)
    project_id: str
    subject_invocation_id: str
    writer: ReasonerFingerprint
    verifier: VerifierIdentity
    verifier_invocation_id: str
    request_sha256: str
    request: CompletenessRequest | AdmissionRequest
    """``AdmissionRequest`` exactly for policy v4 (the base is listed first so an earlier record
    always reconstructs as itself)."""
    proposed_judgment_ids: tuple[str, ...]
    report: (
        CompletenessReport
        | StructuredCompletenessReport
        | VerdictCompletenessReport
        | AdmissionReport
        | None
    )
    """``None`` when the verifier's output could not be parsed as a report; otherwise in the
    format of the verifier policy that produced it."""
    outcome: CompletenessOutcome
    failure_codes: tuple[str, ...]
    failures: tuple[IncompletePropositionMeaning, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    wall_clock_ms: int | None = None
    held_proposition_ids: tuple[str, ...] = ()
    """Policy v3: the propositions held unapplied (with every proposition of their safe unit)."""
    gap_ids: tuple[str, ...] = ()
    """Policy v3: the blocking gaps recorded for the held units."""

    @model_validator(mode="after")
    def validate_outcome(self) -> CompletenessRecord:
        if (self.outcome == "PASS") != (not self.failure_codes):
            raise ValueError("a PASS carries no failure code and a FAIL carries at least one")
        if self.request_sha256 != completeness_request_sha256(self.request):
            raise ValueError("request_sha256 must be the digest of the recorded request")
        expected = _expected_report(self.verifier.policy_version)
        if self.report is not None and not isinstance(self.report, expected or ()):
            raise ValueError("the report is not in the format of the verifier's policy")
        return self


def completeness_request_sha256(request: CompletenessRequest) -> str:
    return hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def report_in_policy_format(
    report: AnyCompletenessReport | None, policy_version: str
) -> AnyCompletenessReport | None:
    """The report if it is in the format of ``policy_version``, else ``None`` (invalid output,
    recorded as no report: a FAIL, never coerced)."""
    expected = _expected_report(policy_version)
    return report if expected is not None and isinstance(report, expected) else None


def report_findings(request: CompletenessRequest, report: AnyCompletenessReport) -> tuple[str, ...]:
    """Structural validity of a report: every proposition judged once, on its own claims; for a
    structured report, every finding grounded in its own proposition and claims."""
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
        if isinstance(v, AdmissionVerdict):
            shown = (
                {c.claim_id for c in request.current_claims}
                if isinstance(request, AdmissionRequest)
                else set()
            )
            out.extend(
                f"UNKNOWN_CONFLICT_CLAIM: {v.proposition_id} -> {cid}"
                for cid in v.conflicting_claim_ids
                if cid not in shown
            )
            continue
        if isinstance(v, PropositionCheck):
            continue
        refs = {c.ref for c in expected[v.proposition_id].claims}
        if set(v.claim_refs) != refs:
            out.append(f"WRONG_CLAIM_REFERENCES: {v.proposition_id}")
        if isinstance(v, StructuredPropositionVerdict):
            out.extend(_grounding(expected[v.proposition_id], v))
    for pid in expected:
        if pid not in seen:
            out.append(f"MISSING_VERDICT: {pid}")
    return tuple(out)


def _grounding(review: PropositionReview, verdict: StructuredPropositionVerdict) -> list[str]:
    pid = review.proposition_id
    texts = (review.statement, *review.source_sentences)
    claims = {c.ref: f"{c.subject} {c.predicate} {c.value}" for c in review.claims}
    out: list[str] = []
    for f in verdict.findings:
        if f.proposition_evidence is not None and not any(
            grounded(f.proposition_evidence, t) for t in texts
        ):
            out.append(f"UNGROUNDED_PROPOSITION_EVIDENCE: {pid}")
        if f.claim_ref is not None and f.claim_ref not in claims:
            out.append(f"UNKNOWN_CLAIM_REFERENCE: {pid} {f.claim_ref}")
        elif (
            f.claim_ref is not None
            and f.claim_evidence is not None
            and not grounded(f.claim_evidence, claims[f.claim_ref])
        ):
            out.append(f"UNGROUNDED_CLAIM_EVIDENCE: {pid}")
    keys = [
        (f.kind, f.direction, _folded(f.proposition_evidence or ""), f.claim_ref,
         _folded(f.claim_evidence or ""))
        for f in verdict.findings
    ]  # fmt: skip
    if len(set(keys)) != len(keys):
        out.append(f"DUPLICATE_FINDING: {pid}")
    spans: dict[tuple[str, str], set[str]] = {}
    for f in verdict.findings:
        if f.proposition_evidence is not None:
            key = (f.kind, _folded(f.proposition_evidence))
            spans.setdefault(key, set()).add(f.direction)
    if any(len(directions) > 1 for directions in spans.values()):
        out.append(f"CONFLICTING_FINDINGS: {pid}")
    return out


def completeness_outcome(
    request: CompletenessRequest,
    report: AnyCompletenessReport | None,
    *,
    verifier: VerifierIdentity,
    writer: ReasonerFingerprint,
) -> tuple[CompletenessOutcome, tuple[str, ...]]:
    """All-or-nothing: PASS only for a valid report, in its policy's format, by an independent
    verifier, in which every proposition is COMPLETE."""
    if not independent(verifier.as_fingerprint(), writer):
        return "FAIL", ("VERIFIER_NOT_INDEPENDENT",)
    expected = _expected_report(verifier.policy_version)
    if report is None or expected is None or not isinstance(report, expected):
        return "FAIL", ("VERIFIER_OUTPUT_INVALID",)
    if isinstance(report, AdmissionReport) != isinstance(request, AdmissionRequest):
        return "FAIL", ("VERIFIER_OUTPUT_INVALID",)
    if report_findings(request, report):
        return "FAIL", ("VERIFIER_OUTPUT_INVALID",)
    if isinstance(report, AdmissionReport):
        codes = tuple(
            code
            for code, hit in (
                (INCOMPLETE_PROPOSITION_MEANING, "NOT_COMPLETE"),
                (SEMANTIC_CONFLICT, "CONFLICT"),
                (SEMANTIC_UNCERTAIN, "UNCERTAIN"),
            )
            if any(hit in (v.completeness, v.consistency) for v in report.verdicts)
        )
        return ("FAIL", codes) if codes else ("PASS", ())
    if any(v.verdict != "COMPLETE" for v in report.verdicts):
        return "FAIL", (INCOMPLETE_PROPOSITION_MEANING,)
    return "PASS", ()


def incomplete_meanings(
    request: CompletenessRequest,
    report: CompletenessReport | StructuredCompletenessReport,
    *,
    verification_id: str,
) -> tuple[IncompletePropositionMeaning, ...]:
    if isinstance(report, StructuredCompletenessReport):
        return tuple(_structured_meaning(v, verification_id) for v in report.verdicts if v.findings)
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


def _structured_meaning(
    v: StructuredPropositionVerdict, verification_id: str
) -> IncompletePropositionMeaning:
    def quoted(direction: str) -> tuple[str, ...]:
        out: list[str] = []
        for f in v.findings:
            if f.direction != direction:
                continue
            if direction == "MISSING":
                out.append(str(f.proposition_evidence))
            elif direction == "UNSUPPORTED":
                out.append(f"{f.claim_ref}: {f.claim_evidence}")
            else:
                out.append(f"{f.proposition_evidence} / {f.claim_ref}: {f.claim_evidence}")
        return tuple(out)

    return IncompletePropositionMeaning(
        proposition_id=v.proposition_id,
        verdict=v.verdict,
        claim_refs=v.claim_refs,
        verification_id=verification_id,
        missing=quoted("MISSING"),
        unsupported=quoted("UNSUPPORTED"),
        contradictory=quoted("CONTRADICTORY"),
        findings=v.findings,
    )
