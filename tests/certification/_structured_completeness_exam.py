"""Structured certification exam v1 for SEMANTIC_COMPLETENESS_VERIFICATION, test-only.

A new lineage. It certifies the structured verifier ``ie2-semantic-completeness-v2`` and never
the free-text verifier (``ie2-semantic-completeness-v1``, exams v1-v5, all NOT CERTIFIED and
frozen). Those exams ended because deterministic code had to read English; this one never does.

**The scoring law.** An attempt passes only if its report is a valid
``StructuredCompletenessReport`` for the request (``report_findings``: every proposition judged
once on exactly its claims, every quote grounded where it says, every claim_ref real, no
duplicate or self-conflicting finding, the verdict following from the findings) and, for every
proposition:

* the verdict is the sealed verdict;
* every sealed region is matched by some finding: the same direction; a kind among the region's
  admissible kinds; when the region has proposition anchors, a proposition quote that contains
  one of them and no anchor of any other region of that proposition; when the region names a
  claim, that claim_ref and a claim quote containing the claim-side anchor;
* every finding matches some sealed region (an unaccounted finding is a wrong finding).

Containment is whole-word with case, whitespace and punctuation folded (``grounded``), between
two pieces of source text: the sealed anchor and the verifier's verbatim quote. Nothing compares
two phrasings for meaning. ``explanation`` is never read. Where the operative-kind taxonomy
genuinely overlaps (a duration is a timing; "only members" restricts an actor and states an
eligibility), a region seals a small set of admissible kinds; the kind is still the model's
classification, never inferred from words.

**Model-visible material** is exactly one ``CompletenessRequest`` per case, through the
production structured verifier, with neutral ids. Every expectation lives only here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from foundry.adapters.semantics.completeness_verifier import (
    COMPLETENESS_POLICY_ID,
    COMPLETENESS_V2_CONTRACT,
    STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION,
    ModelRuntimeStructuredCompletenessVerifier,
)
from foundry.domain.semantic_completeness import (
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
    STRUCTURED_REPORT_FORMAT,
    CompletenessRequest,
    CompletenessVerdict,
    FindingDirection,
    FindingKind,
    PropositionReview,
    SemanticFinding,
    StructuredCompletenessReport,
    StructuredPropositionVerdict,
    grounded,
    report_findings,
)
from foundry.model_runtime.domain import (
    CertifiedContract,
    ModelCapability,
    ModelContract,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelRequest,
    ModelTask,
    ModelTier,
)
from foundry.model_runtime.errors import ModelProtocolError, ModelProviderError
from foundry.model_runtime.ports import ProviderExecutionResult
from foundry.model_runtime.runtime import ModelRuntime
from tests.certification._certification_run import Contestant, classify_execution_failure
from tests.certification._completeness_exam import (
    BINDING_FIELDS,
    CERTIFIED_CONFIGURATION,
    CompletenessObservation,
    ProviderConfiguration,
    attempt_evidence,
    render_request,
)
from tests.certification._completeness_exam import _claim as claim
from tests.certification._completeness_exam import _prop as prop
from tests.certification._completeness_exam import case_by_id as freetext_case
from tests.certification._exam_identity import canonical_digest, code_closure
from tests.certification._schema_identity import schema_sha256

STRUCTURED_EXAM_ID: Final = "ie2.semantic-completeness-verification.structured-certification-exam"
STRUCTURED_EXAM_VERSION: Final = "ie2-semantic-completeness-structured-exam-v1"
STRUCTURED_EVIDENCE_NAMESPACE: Final = "semantic_completeness_structured_exam_v1"
STRUCTURED_RECORD_FORMAT: Final = "ie2-semantic-completeness-structured-certification.v1"
STRUCTURED_SEAL_PATH: Final = Path(
    "tests/certification/exam_manifests/ie2-semantic-completeness-structured-exam-v1.seal.json"
)
EXPECTED_POLICY_ID: Final = "ie2-semantic-completeness"
EXPECTED_POLICY_VERSION: Final = "ie2-semantic-completeness-v2"
EXPECTED_INSTRUCTION_SHA256: Final = (
    "07296c5ec2b1f2fee616b3e3a80c762b5882e78c3cd223eba899b1fd74739710"
)
RUNS_PER_CASE: Final = 3
"""The established rule: three independent runs per case, every one passing."""
CALL_BUDGET: Final = 84
"""``len(CASES) * RUNS_PER_CASE``, pasted and sealed before any live call."""
ACCEPTANCE_RULE: Final = "every case passes all of its independent runs (MR4/MR6)"
EXPECTED_EXAM_SHA256: Final = "0998671b7c742642a2ddef71b76b1d3a6e8798dc604375d7d1fb999c8332e8d1"
"""``structured_exam_sha256()``, pasted, never computed at import."""
STRUCTURED_BINDING_FIELDS: Final = (*BINDING_FIELDS, "report_format")
"""Every field a structured certificate must match, exactly and present."""


# --- the sealed answer key ----------------------------------------------------------------------


@dataclass(frozen=True)
class SealedRegion:
    """One expected finding as a source region.

    ``anchors``: source phrases (statement or source sentence) any one of which marks the
    proposition-side region. ``claim_ref`` / ``claim_anchor``: the claim-side region."""

    kinds: tuple[FindingKind, ...]
    direction: FindingDirection
    anchors: tuple[str, ...] = ()
    claim_ref: str | None = None
    claim_anchor: str | None = None


@dataclass(frozen=True)
class SealedProposition:
    verdict: CompletenessVerdict
    regions: tuple[SealedRegion, ...] = ()


@dataclass(frozen=True)
class StructuredCase:
    case_id: str
    category: str
    request: CompletenessRequest
    expected: Mapping[str, SealedProposition]


PROJECT: Final = "PROJ-S"


def structured_case(
    number: int, category: str, *items: tuple[PropositionReview, SealedProposition]
) -> StructuredCase:
    """Neutral model-visible ids only: the request carries a sequence number, never a label."""
    return StructuredCase(
        case_id=f"S{number:02d}",
        category=category,
        request=CompletenessRequest(
            project_id=PROJECT,
            subject_invocation_id=f"INV-S{number:04d}",
            propositions=tuple(review for review, _ in items),
        ),
        expected={review.proposition_id: sealed for review, sealed in items},
    )


def missing(kinds: tuple[FindingKind, ...], *anchors: str) -> SealedRegion:
    return SealedRegion(kinds, "MISSING", anchors)


def unsupported(kinds: tuple[FindingKind, ...], ref: str, anchor: str) -> SealedRegion:
    return SealedRegion(kinds, "UNSUPPORTED", (), ref, anchor)


def contradicted(
    kinds: tuple[FindingKind, ...], anchor: str, ref: str, claim_anchor: str
) -> SealedRegion:
    return SealedRegion(kinds, "CONTRADICTORY", (anchor,), ref, claim_anchor)


COMPLETE: Final = SealedProposition("COMPLETE")


def incomplete(*regions: SealedRegion) -> SealedProposition:
    return SealedProposition("INCOMPLETE", regions)


def overreach(*regions: SealedRegion) -> SealedProposition:
    return SealedProposition("OVERREACH", regions)


def contradictory(*regions: SealedRegion) -> SealedProposition:
    return SealedProposition("CONTRADICTORY", regions)


# --- the scorer -----------------------------------------------------------------------------------


def _covers(quote: str | None, anchors: tuple[str, ...]) -> bool:
    return quote is not None and any(grounded(anchor, quote) for anchor in anchors)


def finding_matches(
    finding: SemanticFinding, region: SealedRegion, others: tuple[SealedRegion, ...]
) -> bool:
    """Does this structured finding stand for this sealed region? Kind, direction, ids and
    source-span containment only."""
    if finding.direction != region.direction or finding.kind not in region.kinds:
        return False
    if region.anchors:
        if not _covers(finding.proposition_evidence, region.anchors):
            return False
        if any(_covers(finding.proposition_evidence, o.anchors) for o in others):
            return False
    if region.claim_ref is not None:
        if finding.claim_ref != region.claim_ref:
            return False
        if not _covers(finding.claim_evidence, (str(region.claim_anchor),)):
            return False
    return True


def score_structured_report(case: StructuredCase, report: Any) -> tuple[str, ...]:
    """Every reason this report fails its case; empty means the attempt passes."""
    if not isinstance(report, StructuredCompletenessReport):
        return ("not a StructuredCompletenessReport",)
    problems = report_findings(case.request, report)
    if problems:
        return problems
    got = {v.proposition_id: v for v in report.verdicts}
    failures: list[str] = []
    for pid, sealed in case.expected.items():
        verdict = got[pid]
        if verdict.verdict != sealed.verdict:
            failures.append(f"{pid}: verdict {verdict.verdict}, sealed {sealed.verdict}")
            continue
        for region in sealed.regions:
            others = tuple(r for r in sealed.regions if r is not region)
            if not any(finding_matches(f, region, others) for f in verdict.findings):
                failures.append(f"{pid}: no finding for the sealed {region.direction} region")
        for f in verdict.findings:
            if not any(
                finding_matches(f, r, tuple(o for o in sealed.regions if o is not r))
                for r in sealed.regions
            ):
                failures.append(f"{pid}: a {f.kind} {f.direction} finding matches no sealed region")
    return tuple(failures)


def perfect_findings(case: StructuredCase) -> dict[str, tuple[SemanticFinding, ...]]:
    """The answer key rendered as structured findings: what a perfect verifier would return."""
    out: dict[str, tuple[SemanticFinding, ...]] = {}
    for pid, sealed in case.expected.items():
        found = tuple(
            SemanticFinding(
                kind=r.kinds[0],
                direction=r.direction,
                proposition_evidence=r.anchors[0] if r.anchors else None,
                claim_ref=r.claim_ref,
                claim_evidence=r.claim_anchor,
            )
            for r in sealed.regions
        )
        if found:
            out[pid] = found
    return out


# --- the corpus ---------------------------------------------------------------------------------
# A held-out domain (a community makerspace) for everything but the three named regressions.

GUEST: Final = "Guest passes"
LENDING: Final = "Tool lending"
WORKSHOP: Final = "Workshop bookings"
LASER: Final = "Laser cutter"
REQUIRED_COVERAGE: Final = (
    "COMPLETE_EXACT", "COMPLETE_PARAPHRASE", "COMPLETE_MULTI_CLAIM",
    "COMPLETE_JOINT_CONDITION_CONSEQUENCE", "COMPLETE_SUPPORT", "COMPLETE_ASSERT_SUPERSEDE",
    "MISSING_ACTOR", "MISSING_PERMISSION", "MISSING_CHANNEL", "MISSING_CONDITION",
    "MISSING_ELIGIBILITY", "MISSING_CONSEQUENCE", "MISSING_EXCEPTION", "MISSING_DEADLINE",
    "TWO_INDEPENDENT_MISSING", "SECOND_SENTENCE_LOST", "SECOND_CLAUSE_LOST",
    "UNSUPPORTED_ACTOR", "UNSUPPORTED_CONSEQUENCE", "UNSUPPORTED_ELIGIBILITY",
    "UNSUPPORTED_RESTRICTION", "CONFLICTING_QUANTITY", "CONFLICTING_DURATION",
    "CONFLICTING_DESTINATION", "CONFLICTING_PERMISSION",
    "K_CREDIT_REGRESSION", "C05_REGRESSION", "C17_REGRESSION",
)  # fmt: skip

TIME: Final[tuple[FindingKind, ...]] = ("DEADLINE", "TIMING", "TIME_ANCHOR")
RULE: Final[tuple[FindingKind, ...]] = ("CONDITION", "ELIGIBILITY")

CASES: Final[tuple[StructuredCase, ...]] = (
    structured_case(1, "COMPLETE_EXACT", (
        prop("p1", "A guest pass costs 8 EUR per visit.",
             (claim("JDG-1", GUEST, "guest_pass_price", "8 EUR per visit"),)), COMPLETE)),
    structured_case(2, "COMPLETE_PARAPHRASE", (
        prop("p1", "Members can borrow a cordless drill for up to three days.",
             (claim("JDG-1", LENDING, "cordless_drill_lending_period_for_members",
                    "at most 72 hours"),)), COMPLETE)),
    structured_case(3, "COMPLETE_MULTI_CLAIM", (
        prop("p1", "Laser cutter sessions are booked online and last at most 90 minutes.",
             (claim("JDG-1", LASER, "session_booking_channel", "online"),
              claim("JDG-2", LASER, "maximum_session_length", "90 minutes"))), COMPLETE)),
    structured_case(4, "COMPLETE_JOINT_CONDITION_CONSEQUENCE", (
        prop("p1", "A member who misses a booked workshop without cancelling loses the deposit "
             "and cannot book another workshop for 30 days.",
             (claim("JDG-1", WORKSHOP, "no_show_condition",
                    "the member misses a booked workshop without cancelling"),
              claim("JDG-2", WORKSHOP, "no_show_deposit_outcome", "the deposit is forfeited"),
              claim("JDG-3", WORKSHOP, "no_show_booking_ban",
                    "no new workshop booking for 30 days"))), COMPLETE)),
    structured_case(5, "COMPLETE_SUPPORT", (
        prop("p1", "Lockers are rented by the month.",
             (claim("CLM-1", "Locker rental", "rental_period", "one month", "SUPPORTED"),)),
        COMPLETE)),
    structured_case(6, "COMPLETE_ASSERT_SUPERSEDE", (
        prop("p1", "The 3D printing material fee is now 0.05 EUR per gram.",
             (claim("JDG-1", "3D printing", "material_fee", "0.05 EUR per gram"),),
             retired=(claim("CLM-2", "3D printing", "material_fee", "0.03 EUR per gram",
                            "RETIRED"),)), COMPLETE)),
    structured_case(7, "MISSING_ACTOR", (
        prop("p1", "Only staff may unlock the welding bay.",
             (claim("JDG-1", "Welding bay", "unlock_permission", "may be unlocked"),)),
        incomplete(missing(("ACTOR", "PERMISSION", "ELIGIBILITY"), "only staff")))),
    structured_case(8, "MISSING_PERMISSION", (
        prop("p1", "Members may take offcuts from the scrap bin free of charge.",
             (claim("JDG-1", "Scrap bin", "offcut_price", "free of charge"),)),
        incomplete(missing(("PERMISSION", "ACTOR"), "may take offcuts")))),
    structured_case(9, "MISSING_CHANNEL", (
        prop("p1", "Members cancel a workshop booking through the member portal.",
             (claim("JDG-1", WORKSHOP, "cancellation_by_members",
                    "members can cancel a booking"),)),
        incomplete(missing(("CHANNEL", "DESTINATION"), "through the member portal")))),
    structured_case(10, "MISSING_CONDITION", (
        prop("p1", "The large-format printer may be used if a staff member is present.",
             (claim("JDG-1", "Large-format printer", "use_permission", "may be used"),)),
        incomplete(missing(RULE, "if a staff member is present")))),
    structured_case(11, "MISSING_ELIGIBILITY", (
        prop("p1", "Members aged 18 or over may book the welding course.",
             (claim("JDG-1", "Welding course", "booking_permission", "members may book it"),)),
        incomplete(missing(("ELIGIBILITY", "CONDITION", "ACTOR"), "aged 18 or over")))),
    structured_case(12, "MISSING_CONSEQUENCE", (
        prop("p1", "A tool returned damaged must be reported, and the member pays the repair "
             "cost.",
             (claim("JDG-1", LENDING, "damage_report_obligation",
                    "a damaged tool must be reported"),)),
        incomplete(missing(("CONSEQUENCE", "OBLIGATION"), "pays the repair cost")))),
    structured_case(13, "MISSING_EXCEPTION", (
        prop("p1", "All tools can be borrowed for a week, except the laser cutter, which stays "
             "on site.",
             (claim("JDG-1", LENDING, "lending_period", "one week"),)),
        incomplete(missing(("EXCEPTION",), "except the laser cutter")))),
    structured_case(14, "MISSING_DEADLINE", (
        prop("p1", "A workshop can be cancelled free of charge up to 48 hours before it starts.",
             (claim("JDG-1", WORKSHOP, "free_cancellation",
                    "a workshop can be cancelled free of charge"),)),
        incomplete(missing(TIME, "up to 48 hours before it starts")))),
    structured_case(15, "TWO_INDEPENDENT_MISSING", (
        prop("p1", "Guest passes are sold at the front desk and must be paid in cash.",
             (claim("JDG-1", GUEST, "guest_pass_sale", "guest passes are sold"),)),
        incomplete(missing(("DESTINATION", "CHANNEL"), "at the front desk"),
                   missing(("CHANNEL", "CONDITION", "OBLIGATION"), "paid in cash")))),
    structured_case(16, "SECOND_SENTENCE_LOST", (
        prop("p1", "Members must book a bench in advance, and a bench left untidy incurs a 10 EUR "
             "cleaning fee.",
             (claim("JDG-1", "Benches", "advance_booking", "required"),),
             sentences=("Members must book a bench in advance.",
                        "A bench left untidy incurs a 10 EUR cleaning fee.")),
        incomplete(missing(("CONSEQUENCE",), "10 EUR cleaning fee")))),
    structured_case(17, "SECOND_CLAUSE_LOST", (
        prop("p1", "Laser cutter users must wear safety glasses and must not leave a job running "
             "unattended.",
             (claim("JDG-1", LASER, "safety_glasses_required", "safety glasses must be worn"),)),
        incomplete(missing(("OBLIGATION", "PERMISSION", "CONDITION"),
                           "leave a job running unattended")))),
    structured_case(18, "UNSUPPORTED_ACTOR", (
        prop("p1", "Members may borrow the oscilloscope for two days.",
             (claim("JDG-1", LENDING, "oscilloscope_lending_period_for_members", "two days"),
              claim("JDG-2", LENDING, "oscilloscope_lending_to_guests",
                    "guests may also borrow it"))),
        overreach(unsupported(("ACTOR", "PERMISSION", "ELIGIBILITY"), "JDG-2", "guests")))),
    structured_case(19, "UNSUPPORTED_CONSEQUENCE", (
        prop("p1", "A late tool return is charged 2 EUR per day.",
             (claim("JDG-1", LENDING, "late_return_fee",
                    "2 EUR per day, and the membership is suspended"),)),
        overreach(unsupported(("CONSEQUENCE",), "JDG-1", "membership is suspended")))),
    structured_case(20, "UNSUPPORTED_ELIGIBILITY", (
        prop("p1", "Members can rent a locker.",
             (claim("JDG-1", "Locker rental", "locker_rental_for_members",
                    "members with at least six months of membership can rent a locker"),)),
        overreach(unsupported(RULE, "JDG-1", "at least six months")))),
    structured_case(21, "UNSUPPORTED_RESTRICTION", (
        prop("p1", "The CNC router can be booked by trained members.",
             (claim("JDG-1", "CNC router", "booking",
                    "trained members can book it on weekdays only"),)),
        overreach(unsupported(("TIMING", "CONDITION"), "JDG-1", "on weekdays only")))),
    structured_case(22, "CONFLICTING_QUANTITY", (
        prop("p1", "Each member may store at most two projects in the project rack.",
             (claim("JDG-1", "Project rack", "maximum_projects_per_member", "3"),)),
        contradictory(contradicted(("QUANTITY_LIMIT",), "two projects", "JDG-1", "3")))),
    structured_case(23, "CONFLICTING_DURATION", (
        prop("p1", "A guest pass is valid for one day.",
             (claim("JDG-1", GUEST, "guest_pass_validity", "7 days"),)),
        contradictory(contradicted(("TIMING", "QUANTITY_LIMIT"), "one day", "JDG-1", "7 days")))),
    structured_case(24, "CONFLICTING_DESTINATION", (
        prop("p1", "Finished prints are collected from the pickup shelf.",
             (claim("JDG-1", "3D printing", "print_collection_point", "the front desk"),)),
        contradictory(contradicted(("DESTINATION",), "pickup shelf", "JDG-1", "front desk")))),
    structured_case(25, "CONFLICTING_PERMISSION", (
        prop("p1", "Members may not use the spray booth alone.",
             (claim("JDG-1", "Spray booth", "solo_use", "members may use it alone"),)),
        contradictory(contradicted(("PERMISSION", "CONDITION"),
                                   "may not use the spray booth alone", "JDG-1",
                                   "may use it alone")))),
    structured_case(26, "K_CREDIT_REGRESSION", (
        freetext_case("C21").request.propositions[0],
        incomplete(missing(("CHANNEL",), "in the app"),
                   missing(("CONSEQUENCE",), "a later claim is refused",
                           "a claim made later is refused")))),
    structured_case(27, "C05_REGRESSION", (
        freetext_case("C05").request.propositions[0],
        incomplete(missing(("ACTOR", "PERMISSION"), "a member"),
                   missing(RULE, "nobody else has reserved")))),
    structured_case(28, "C17_REGRESSION", (
        freetext_case("C17").request.propositions[0], COMPLETE), (
        freetext_case("C17").request.propositions[1],
        contradictory(contradicted(("TIMING",), "two weeks", "CLM-1", "21 days")))),
)  # fmt: skip

K_CREDIT: Final = "S26"
C05_REGRESSION: Final = "S27"
C17_REGRESSION: Final = "S28"


def case_by_id(case_id: str) -> StructuredCase:
    (case,) = [c for c in CASES if c.case_id == case_id]
    return case


# --- one attempt through the production structured verifier -------------------------------------


class _RecordingProvider:
    """Delegates to the real adapter, including its wire-schema statement; remembers every
    request, result and raised error."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.requests: list[ModelRequest] = []
        self.results: list[ProviderExecutionResult[Any]] = []
        self.errors: list[BaseException] = []

    def __getattr__(self, name: str) -> Any:
        if name in ("wire_schema", "WIRE_SCHEMA_COMPILER"):
            return getattr(self._inner, name)
        raise AttributeError(name)

    @property
    def provider_id(self) -> str:
        return str(self._inner.provider_id)

    def execute(self, **kwargs: Any) -> ProviderExecutionResult[Any]:
        self.requests.append(kwargs["request"])
        try:
            result: ProviderExecutionResult[Any] = self._inner.execute(**kwargs)
        except BaseException as exc:
            self.errors.append(exc)
            raise
        self.results.append(result)
        return result


def run_structured_attempt(
    contestant: Contestant, case: StructuredCase, attempt: int, *, provider: Any
) -> CompletenessObservation:
    """One verification through the production structured verifier and Model Runtime."""
    recording = _RecordingProvider(provider)
    runtime = ModelRuntime(registry=contestant.registry(), providers=(recording,))
    verifier = ModelRuntimeStructuredCompletenessVerifier(
        runtime=runtime, run_id=f"SCS-CERT-{case.request.subject_invocation_id}-{attempt}"
    )
    try:
        verification = verifier.verify(case.request)
    except (ModelProviderError, ModelProtocolError) as exc:
        classify_execution_failure(exc)
        raise  # unreachable; classify_execution_failure always raises
    if recording.errors:
        classify_execution_failure(recording.errors[0])
        raise AssertionError(f"unclassified provider failure: {recording.errors[0]!r}")
    return CompletenessObservation(
        case_id=case.case_id,
        attempt=attempt,
        sent=tuple(recording.requests),
        result=recording.results[0] if recording.results else None,
        report=verification.report,  # type: ignore[arg-type]
        verifier=verification.verifier,
    )


def score_global_gates(
    observation: CompletenessObservation, case: StructuredCase, *, candidate: ModelIdentity
) -> tuple[str, ...]:
    """Applied to every live call, whatever the case expects."""
    if len(observation.sent) != 1 or observation.result is None:
        return (f"one verification must be one answered call, saw {len(observation.sent)}",)
    (sent,) = observation.sent
    ran = observation.result.identity
    failures: list[str] = []
    if (ran.provider, ran.model) != (candidate.provider, candidate.model):
        failures.append(f"executed {ran.provider}/{ran.model}, not the candidate")
    if sent.task is not ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION:
        failures.append(f"task was {sent.task.value}")
    if sent.tier is not ModelTier.REASONER:
        failures.append(f"tier was {sent.tier.value}")
    if (sent.policy_id, sent.policy_version) != (EXPECTED_POLICY_ID, EXPECTED_POLICY_VERSION):
        failures.append(f"policy was {sent.policy_id}/{sent.policy_version}")
    if sent.contract != COMPLETENESS_V2_CONTRACT:
        failures.append("the request is not bound to the structured verifier contract")
    system, user = sent.messages
    if hashlib.sha256(system.content.encode()).hexdigest() != EXPECTED_INSTRUCTION_SHA256:
        failures.append("the instruction is not the frozen structured instruction")
    if user.content != render_request(case.request):
        failures.append("the request sent is not the sealed request")
    if sent.constraints != ModelExecutionConstraints():
        failures.append("the request is not the production request")
    reported = observation.verifier
    if (reported.provider, reported.model, reported.policy_version) != (
        candidate.provider,
        candidate.model,
        EXPECTED_POLICY_VERSION,
    ):
        failures.append(f"verifier identity reported as {reported}")
    return tuple(failures)


def score_structured_attempt(
    observation: CompletenessObservation, case: StructuredCase, *, candidate: ModelIdentity
) -> tuple[str, ...]:
    return (
        *score_global_gates(observation, case, candidate=candidate),
        *score_structured_report(case, observation.report),
    )


def structured_verdict(attempts: list[dict[str, Any]]) -> str:
    """PASS only when every case's every required run was recorded exactly once and passed."""
    required = {(c.case_id, n) for c in CASES for n in range(1, RUNS_PER_CASE + 1)}
    recorded = [(a["case"], a["attempt"]) for a in attempts]
    complete = len(recorded) == len(required) == CALL_BUDGET
    if not complete or set(recorded) != required:
        return "NOT CERTIFIED"
    return "PASS" if all(a["verdict"] == "PASS" for a in attempts) else "NOT CERTIFIED"


# --- exam identity --------------------------------------------------------------------------------


def _region_document(r: SealedRegion) -> dict[str, Any]:
    return {
        "kinds": list(r.kinds),
        "direction": r.direction,
        "anchors": list(r.anchors),
        "claim_ref": r.claim_ref,
        "claim_anchor": r.claim_anchor,
    }


def _case_document(case: StructuredCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "request": case.request.model_dump(mode="json"),
        "request_sha256": hashlib.sha256(render_request(case.request).encode()).hexdigest(),
        "expected": {
            pid: {"verdict": s.verdict, "regions": [_region_document(r) for r in s.regions]}
            for pid, s in sorted(case.expected.items())
        },
    }


def _openai_wire() -> tuple[str, str]:
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider

    return (
        schema_sha256(OpenAIModelProvider.wire_schema(StructuredCompletenessReport)),
        OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
    )


def structured_exam_manifest() -> dict[str, Any]:
    """Everything that decides what the exam asks, how each run executes and what passes."""
    wire, compiler = _openai_wire()
    return {
        "exam_id": STRUCTURED_EXAM_ID,
        "exam_version": STRUCTURED_EXAM_VERSION,
        "cases": [_case_document(case) for case in CASES],
        "code": code_closure(
            [
                structured_case,
                missing,
                unsupported,
                contradicted,
                finding_matches,
                score_structured_report,
                render_request,
                run_structured_attempt,
                score_global_gates,
                score_structured_attempt,
                attempt_evidence,
                structured_verdict,
                structured_certificate_binds,
                write_structured_certification,
                certified_descriptor,
            ]
        ),
        "acceptance": {
            "rule": ACCEPTANCE_RULE,
            "cases": [case.case_id for case in CASES],
            "runs_per_case": RUNS_PER_CASE,
            "call_budget": CALL_BUDGET,
        },
        "identity": {
            "task": ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION.value,
            "tier": ModelTier.REASONER.value,
            "verifier_policy_id": EXPECTED_POLICY_ID,
            "verifier_policy_version": EXPECTED_POLICY_VERSION,
            "instruction_sha256": EXPECTED_INSTRUCTION_SHA256,
            "report_format": STRUCTURED_REPORT_FORMAT,
            "canonical_schema_sha256": schema_sha256(
                StructuredCompletenessReport.model_json_schema()
            ),
            "openai_wire_schema_sha256": wire,
            "openai_wire_schema_compiler": compiler,
            "routing_contract": COMPLETENESS_V2_CONTRACT.model_dump(mode="json"),
            "configuration": {
                "reasoning_effort": CERTIFIED_CONFIGURATION.reasoning_effort,
                "reasoning_mode": CERTIFIED_CONFIGURATION.reasoning_mode,
                "timeout_seconds": CERTIFIED_CONFIGURATION.timeout_seconds,
                "output_guard": CERTIFIED_CONFIGURATION.output_guard,
            },
        },
        "binding_fields": list(STRUCTURED_BINDING_FIELDS),
    }


def structured_exam_sha256() -> str:
    return canonical_digest(structured_exam_manifest())


# --- the certificate, and the routing it grants -------------------------------------------------


def write_structured_certification(
    contestant: Contestant,
    attempts: list[dict[str, Any]],
    *,
    frozen_production_base: str,
    configuration: ProviderConfiguration,
) -> dict[str, Any]:
    """The verdict record, bound to the exact structured verifier contract and this exam."""
    if contestant.wire_schema is None or contestant.wire_schema_compiler is None:
        raise ValueError("a structured certification must bind the provider's wire schema")
    if contestant.task is not ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION:
        raise ValueError("the contestant must sit SEMANTIC_COMPLETENESS_VERIFICATION")
    if (contestant.reasoning_effort, contestant.timeout_seconds) != (
        configuration.reasoning_effort,
        configuration.timeout_seconds,
    ):
        raise ValueError("the recorded configuration is not the contestant's")
    passed = sum(1 for a in attempts if a["verdict"] == "PASS")
    payload: dict[str, Any] = {
        "record_format": STRUCTURED_RECORD_FORMAT,
        "exam_id": STRUCTURED_EXAM_ID,
        "exam_version": STRUCTURED_EXAM_VERSION,
        "exam_sha256": structured_exam_sha256(),
        "candidate": contestant.label,
        "provider": contestant.identity.provider,
        "model": contestant.identity.model,
        "task": contestant.task.value,
        "tier": ModelTier.REASONER.value,
        "verifier_policy_id": COMPLETENESS_POLICY_ID,
        "verifier_policy_version": SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
        "instruction_sha256": hashlib.sha256(
            STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION.encode()
        ).hexdigest(),
        "report_format": STRUCTURED_REPORT_FORMAT,
        "canonical_schema_sha256": schema_sha256(StructuredCompletenessReport.model_json_schema()),
        "wire_schema_sha256": schema_sha256(contestant.wire_schema(StructuredCompletenessReport)),
        "wire_schema_compiler": contestant.wire_schema_compiler,
        "reasoning_effort": configuration.reasoning_effort,
        "reasoning_mode": configuration.reasoning_mode,
        "timeout_seconds": configuration.timeout_seconds,
        "output_guard": configuration.output_guard,
        "request_constraints": ModelExecutionConstraints().model_dump(mode="json"),
        "frozen_production_base": frozen_production_base,
        "acceptance_rule": ACCEPTANCE_RULE,
        "cases": [case.case_id for case in CASES],
        "runs_per_case": RUNS_PER_CASE,
        "call_budget": CALL_BUDGET,
        "required_attempts": CALL_BUDGET,
        "recorded_attempts": len(attempts),
        "passed_attempts": passed,
        "verdict": structured_verdict(attempts),
        "attempts": attempts,
    }
    contestant.evidence_dir.mkdir(parents=True, exist_ok=True)
    (contestant.evidence_dir / "certification.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
    return payload


def current_structured_identity(identity: ModelIdentity) -> dict[str, Any] | None:
    """What a structured certificate must bind today, or ``None`` for a provider with no
    adapter."""
    from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider
    from foundry.adapters.model_runtime.xai import XAIModelProvider

    providers: dict[str, Any] = {
        "xai": XAIModelProvider,
        "openai": OpenAIModelProvider,
        "anthropic": AnthropicModelProvider,
    }
    provider = providers.get(identity.provider)
    if provider is None:
        return None
    return {
        "record_format": STRUCTURED_RECORD_FORMAT,
        "verdict": "PASS",
        "provider": identity.provider,
        "model": identity.model,
        "task": ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION.value,
        "verifier_policy_id": COMPLETENESS_POLICY_ID,
        "verifier_policy_version": SEMANTIC_COMPLETENESS_POLICY_VERSION_V2,
        "instruction_sha256": hashlib.sha256(
            STRUCTURED_COMPLETENESS_SYSTEM_INSTRUCTION.encode()
        ).hexdigest(),
        "canonical_schema_sha256": schema_sha256(StructuredCompletenessReport.model_json_schema()),
        "wire_schema_sha256": schema_sha256(provider.wire_schema(StructuredCompletenessReport)),
        "wire_schema_compiler": provider.WIRE_SCHEMA_COMPILER,
        "exam_id": STRUCTURED_EXAM_ID,
        "exam_version": STRUCTURED_EXAM_VERSION,
        "exam_sha256": structured_exam_sha256(),
        "reasoning_effort": CERTIFIED_CONFIGURATION.reasoning_effort,
        "reasoning_mode": CERTIFIED_CONFIGURATION.reasoning_mode,
        "timeout_seconds": CERTIFIED_CONFIGURATION.timeout_seconds,
        "output_guard": CERTIFIED_CONFIGURATION.output_guard,
        "runs_per_case": RUNS_PER_CASE,
        "call_budget": CALL_BUDGET,
        "report_format": STRUCTURED_REPORT_FORMAT,
    }


def structured_certificate_binds(record: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    """Fail-closed: every binding field present and equal."""
    return all(
        key in record and key in expected and record[key] == expected[key]
        for key in STRUCTURED_BINDING_FIELDS
    )


def structured_certificate_standing(record: Mapping[str, Any]) -> str:
    """``NOT_CERTIFIED`` (never PASS), ``CURRENT`` (binds every field of this exam and the
    exact structured verifier contract) or ``NOT_BINDING`` (any other PASS: another exam,
    another task, the free-text verifier, another format)."""
    if record.get("verdict") != "PASS":
        return "NOT_CERTIFIED"
    if record.get("record_format") != STRUCTURED_RECORD_FORMAT:
        return "NOT_BINDING"
    current = current_structured_identity(
        ModelIdentity(provider=str(record.get("provider")), model=str(record.get("model")))
    )
    if current is not None and structured_certificate_binds(record, current):
        return "CURRENT"
    return "NOT_BINDING"


def certified_descriptor(record: Mapping[str, Any]) -> ModelDescriptor | None:
    """The routing a certificate grants: for a CURRENT structured certificate, a descriptor
    certified for exactly the structured verifier contract through exactly the certified wire
    schema; for anything else, nothing."""
    if structured_certificate_standing(record) != "CURRENT":
        return None
    contract = ModelContract(
        policy_id=str(record["verifier_policy_id"]),
        policy_version=str(record["verifier_policy_version"]),
        instruction_sha256=str(record["instruction_sha256"]),
        output_schema_sha256=str(record["canonical_schema_sha256"]),
    )
    return ModelDescriptor(
        identity=ModelIdentity(provider=str(record["provider"]), model=str(record["model"])),
        tiers=frozenset({ModelTier.REASONER}),
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
        ),
        certified_tasks=frozenset({ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION}),
        certified_contracts=frozenset(
            {
                CertifiedContract(
                    task=ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION,
                    contract=contract,
                    wire_schema_sha256=str(record["wire_schema_sha256"]),
                    wire_schema_compiler=str(record["wire_schema_compiler"]),
                )
            }
        ),
    )


# --- evidence integrity ---------------------------------------------------------------------------


def structured_evidence_problems(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Re-derive a record from its own attempts. Any disagreement is a problem, never fixed."""
    if record.get("record_format") != STRUCTURED_RECORD_FORMAT:
        return ("not a structured completeness certification record",)
    if record.get("exam_sha256") != structured_exam_sha256():
        return ("earned on a different exam; it cannot be re-scored against this one",)
    attempts: list[dict[str, Any]] = list(record.get("attempts") or [])
    problems: list[str] = []
    passed = sum(1 for a in attempts if a.get("verdict") == "PASS")
    if record.get("recorded_attempts") != len(attempts):
        problems.append("recorded_attempts disagrees with the attempts")
    if record.get("passed_attempts") != passed:
        problems.append("passed_attempts disagrees with the attempts")
    if record.get("required_attempts") != CALL_BUDGET:
        problems.append("required_attempts is not the sealed budget")
    if record.get("verdict") != structured_verdict(attempts):
        problems.append("the verdict does not follow from the attempts")
    cases = {case.case_id: case for case in CASES}
    for a in attempts:
        where = f"{a.get('case')}/{a.get('attempt')}"
        case = cases.get(str(a.get("case")))
        if case is None:
            problems.append(f"{where}: not an exam case")
            continue
        answered = a.get("request_json") is not None or a.get("verdict") == "PASS"
        if answered and a.get("request_json") != render_request(case.request):
            problems.append(f"{where}: the recorded request is not the sealed request")
        if a.get("verdict") != "PASS":
            continue
        if (a.get("provider"), a.get("model")) != (record.get("provider"), record.get("model")):
            problems.append(f"{where}: answered by another model")
        if a.get("instruction_sha256") != EXPECTED_INSTRUCTION_SHA256:
            problems.append(f"{where}: not the frozen structured instruction")
        if a.get("parsed_report") is None:
            problems.append(f"{where}: a PASS without a report")
            continue
        report = StructuredCompletenessReport.model_validate(a["parsed_report"])
        if StructuredCompletenessReport.model_validate(a.get("raw_output")) != report:
            problems.append(f"{where}: the parsed report is not the raw response")
        if score_structured_report(case, report):
            problems.append(f"{where}: the recorded report does not pass its case")
    return tuple(problems)


# --- the seal ---------------------------------------------------------------------------------


def write_structured_seal(path: Path, *, harness_sha: str) -> None:
    manifest = structured_exam_manifest()
    document = {
        "exam_id": STRUCTURED_EXAM_ID,
        "exam_version": STRUCTURED_EXAM_VERSION,
        "exam_sha256": canonical_digest(manifest),
        "harness_sha": harness_sha,
        "manifest": manifest,
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def structured_seal_problems(path: Path = STRUCTURED_SEAL_PATH) -> tuple[str, ...]:
    """Nothing may be called until the committed seal is exactly the current exam."""
    if not path.exists():
        return (f"the structured exam is not sealed: {path} is absent",)
    document = json.loads(path.read_text())
    problems: list[str] = []
    if document.get("manifest") != structured_exam_manifest():
        problems.append("the sealed manifest is not the current exam")
    if document.get("exam_sha256") != canonical_digest(document.get("manifest")):
        problems.append("the sealed hash is not the digest of the sealed manifest")
    if document.get("exam_sha256") != structured_exam_sha256():
        problems.append("the sealed hash is not the current exam hash")
    if not re.fullmatch(r"[0-9a-f]{40}", str(document.get("harness_sha"))):
        problems.append("the seal names no harness commit")
    return tuple(problems)


def scripted_report(
    case: StructuredCase, findings: Mapping[str, tuple[SemanticFinding, ...]]
) -> StructuredCompletenessReport:
    """A structured report for ``case``: the verdict follows from each proposition's findings."""
    verdicts = []
    for p in case.request.propositions:
        found = findings.get(p.proposition_id, ())
        directions = {f.direction for f in found}
        verdict: CompletenessVerdict = (
            "CONTRADICTORY" if "CONTRADICTORY" in directions
            else "INCOMPLETE" if "MISSING" in directions
            else "OVERREACH" if "UNSUPPORTED" in directions
            else "COMPLETE"
        )  # fmt: skip
        verdicts.append(
            StructuredPropositionVerdict(
                proposition_id=p.proposition_id,
                verdict=verdict,
                claim_refs=tuple(c.ref for c in p.claims),
                findings=found,
            )
        )
    return StructuredCompletenessReport(
        report_format=STRUCTURED_REPORT_FORMAT, verdicts=tuple(verdicts)
    )
