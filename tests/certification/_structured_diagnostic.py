"""OFFLINE diagnostic: the v2-v5 problem findings, scored as structured evidence (test-only).

Exams v2-v5 certified ``ie2-semantic-completeness-v1`` by trying to understand the verifier's
English. This module shows the same judgements scored without reading any English: a finding is
a kind, a direction and verbatim evidence; the scorer checks the kind, the direction, the ids,
that the evidence is grounded in the request (``report_findings``), and that the proposition
evidence covers the sealed source region of the expected finding and no other expected region.
It never compares two phrasings for meaning: anchors are source text, matched against source
text the verifier quoted.

DIAGNOSTIC ONLY. Nothing here re-scores or re-opens a historical certification: v2 66/75, v3
74/75, v4 72/75 and v5 74/75 stand as recorded. The translations below are human-authored
structured renderings of what each recorded free-text finding said; they are not model output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from foundry.domain.semantic_completeness import (
    STRUCTURED_REPORT_FORMAT,
    CompletenessRequest,
    CompletenessVerdict,
    FindingDirection,
    FindingKind,
    SemanticFinding,
    StructuredCompletenessReport,
    StructuredPropositionVerdict,
    grounded,
    report_findings,
)


@dataclass(frozen=True)
class SealedRegion:
    """One expected finding: its kind, direction and source region.

    ``anchors``: source phrases (from the statement or a source sentence) any one of which marks
    the proposition-side region. ``claim_ref`` / ``claim_anchor``: the claim-side region."""

    kind: FindingKind
    direction: FindingDirection
    anchors: tuple[str, ...] = ()
    claim_ref: str | None = None
    claim_anchor: str | None = None


@dataclass(frozen=True)
class SealedProposition:
    verdict: CompletenessVerdict
    regions: tuple[SealedRegion, ...] = ()


def _covers(evidence: str | None, anchors: tuple[str, ...]) -> bool:
    return evidence is not None and any(grounded(a, evidence) for a in anchors)


def _matches(f: SemanticFinding, region: SealedRegion, others: tuple[SealedRegion, ...]) -> bool:
    if (f.kind, f.direction) != (region.kind, region.direction):
        return False
    if region.anchors:
        if not _covers(f.proposition_evidence, region.anchors):
            return False
        if any(_covers(f.proposition_evidence, o.anchors) for o in others if o.anchors):
            return False  # one quote may not stand for two expected regions
    if region.claim_ref is not None:
        if f.claim_ref != region.claim_ref or f.claim_evidence is None:
            return False
        if region.claim_anchor is not None and not grounded(region.claim_anchor, f.claim_evidence):
            return False
    return True


def score_structured(
    request: CompletenessRequest,
    report: StructuredCompletenessReport,
    sealed: dict[str, SealedProposition],
) -> tuple[str, ...]:
    """Every reason the report fails; empty means it passes. No English is interpreted."""
    problems = list(report_findings(request, report))
    if problems:
        return tuple(problems)
    got = {v.proposition_id: v for v in report.verdicts}
    for pid, expected in sealed.items():
        verdict = got[pid]
        if verdict.verdict != expected.verdict:
            problems.append(f"{pid}: verdict {verdict.verdict}, sealed {expected.verdict}")
            continue
        for region in expected.regions:
            others = tuple(r for r in expected.regions if r is not region)
            if not any(_matches(f, region, others) for f in verdict.findings):
                problems.append(
                    f"{pid}: no finding for the sealed {region.kind} {region.direction}"
                )
    return tuple(problems)


def report(
    request: CompletenessRequest, findings: dict[str, tuple[SemanticFinding, ...]]
) -> StructuredCompletenessReport:
    """A structured report: the verdict follows from each proposition's findings."""
    verdicts = []
    for p in request.propositions:
        found = findings.get(p.proposition_id, ())
        directions = {f.direction for f in found}
        verdict: CompletenessVerdict = (
            "CONTRADICTORY"
            if "CONTRADICTORY" in directions
            else "INCOMPLETE"
            if "MISSING" in directions
            else "OVERREACH"
            if "UNSUPPORTED" in directions
            else "COMPLETE"
        )
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


def missing(kind: FindingKind, quote: str) -> SemanticFinding:
    return SemanticFinding(kind=kind, direction="MISSING", proposition_evidence=quote)


def unsupported(kind: FindingKind, ref: str, quote: str) -> SemanticFinding:
    return SemanticFinding(kind=kind, direction="UNSUPPORTED", claim_ref=ref, claim_evidence=quote)


def contradicted(kind: FindingKind, quote: str, ref: str, claim_quote: str) -> SemanticFinding:
    return SemanticFinding(
        kind=kind,
        direction="CONTRADICTORY",
        proposition_evidence=quote,
        claim_ref=ref,
        claim_evidence=claim_quote,
    )


SEALED: Final[dict[str, dict[str, SealedProposition]]] = {
    "C05": {"p1": SealedProposition("INCOMPLETE", (
        SealedRegion("ACTOR", "MISSING", ("a member",)),
        SealedRegion("CONDITION", "MISSING", ("if nobody else has reserved the book",)),
    ))},
    "C10": {"p1": SealedProposition("OVERREACH", (
        SealedRegion("CONSEQUENCE", "UNSUPPORTED", claim_ref="JDG-1", claim_anchor="suspended"),
    ))},
    "C11": {"p1": SealedProposition("CONTRADICTORY", (
        SealedRegion("QUANTITY_LIMIT", "CONTRADICTORY", ("10 EUR",), "JDG-2", "15 EUR"),
    ))},
    "C16": {"p1": SealedProposition("INCOMPLETE", (
        SealedRegion("ACTOR", "MISSING", ("only members",)),
        SealedRegion("CONSEQUENCE", "MISSING", ("is cancelled",)),
    ))},
    "C17": {
        "p1": SealedProposition("COMPLETE"),
        "p2": SealedProposition("CONTRADICTORY", (
            SealedRegion("TIMING", "CONTRADICTORY", ("two weeks",), "CLM-1", "21 days"),
        )),
    },
    "C21": {"p1": SealedProposition("INCOMPLETE", (
        SealedRegion("CHANNEL", "MISSING", ("in the app",)),
        SealedRegion("CONSEQUENCE", "MISSING",
                     ("a later claim is refused", "a claim made later is refused")),
    ))},
    "C23": {"p1": SealedProposition("CONTRADICTORY", (
        SealedRegion("DESTINATION", "CONTRADICTORY", ("any branch",), "JDG-1",
                     "the branch that issued the loan"),
    ))},
}  # fmt: skip
"""The expected structured findings of the diagnostic cases, as source regions."""


@dataclass(frozen=True)
class Translation:
    exam: str
    case: str
    attempt: int
    recorded_text: tuple[str, ...]
    """The recorded free-text findings, exactly as the live evidence holds them."""
    structured: dict[str, tuple[SemanticFinding, ...]]


C05_STRUCTURED: dict[str, tuple[SemanticFinding, ...]] = {
    "p1": (
        missing("ACTOR", "A member may renew a loan"),
        missing("CONDITION", "if nobody else has reserved the book"),
    )
}
C05_CONDITION = "Renewal is conditional on nobody else having reserved the book."

TRANSLATIONS: Final[tuple[Translation, ...]] = (
    Translation("v3", "C05", 1,
                ("The permission to renew a loan is granted to a member.", C05_CONDITION),
                C05_STRUCTURED),
    Translation("v4", "C05", 2,
                ("A member is the actor permitted to renew the loan.", C05_CONDITION),
                C05_STRUCTURED),
    Translation("v4", "C05", 3,
                ("The member is the actor permitted to renew the loan.", C05_CONDITION),
                C05_STRUCTURED),
    Translation("v5", "C05", 2,
                ("The renewal permission applies to a member.", C05_CONDITION),
                C05_STRUCTURED),
    Translation("v4", "C17", 1,
                ("The proposition states a loan lasts two weeks (14 days), but CLM-1 states 21 "
                 "days.",),
                {"p2": (contradicted("TIMING", "two weeks", "CLM-1", "21 days"),)}),
    Translation("v5", "C21", 1,
                ("The service credit must be claimed in the app.",
                 "A claim made more than 48 hours after the reservation start is refused."),
                {"p1": (missing("CHANNEL", "claimed in the app"),
                        missing("CONSEQUENCE", "A claim made later is refused"))}),
    Translation("v5", "C16", 1,
                ("Only members may reserve a book.",
                 "A reservation by a member with outstanding fines is cancelled."),
                {"p1": (missing("ACTOR", "Only members with no outstanding fines may reserve a "
                                "book"),
                        missing("CONSEQUENCE", "a reservation by a member with fines is "
                                "cancelled"))}),
    Translation("v5", "C10", 1,
                ("The member is suspended if a damage report is made more than 7 days after "
                 "return.",),
                {"p1": (unsupported("CONSEQUENCE", "JDG-1", "the member is suspended"),)}),
    Translation("v5", "C11", 1,
                ("JDG-2 sets the late-fine cap at 15 EUR per item, contradicting the proposition's "
                 "10 EUR per-item cap and JDG-1.",),
                {"p1": (contradicted("QUANTITY_LIMIT", "10 EUR per item", "JDG-2", "15 EUR"),)}),
    Translation("v5", "C23", 1,
                ("The proposition permits returning a book to any library branch, but JDG-1 "
                 "restricts returns to the branch that issued the loan.",),
                {"p1": (contradicted("DESTINATION", "any branch", "JDG-1",
                                     "only the branch that issued the loan"),)}),
)  # fmt: skip
"""Recorded free-text findings and their structured renderings. Different wordings of one
judgement (C05 under v3, v4 and v5) render to one structured answer."""
