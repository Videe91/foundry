"""Final-outcome scoring of an end-to-end Intent Engine run. Wording is never read.

Three steps, each separable:

1. ``final_outcome`` -- a deterministic extract of the replayed final state: every claim
   (current or retired), applied judgments and supersessions, correction sets, completeness
   records, gaps, explicit conflicts, the IE3 graph, and closure's gap blockers.
2. An ``OutcomeAdjudicator`` answers, for every claim, which expected truth it states (or none)
   and whether it states it faithfully, and which pairs of current claims contradict. That is
   semantic judgement, so it is never deterministic text matching here; who adjudicates is
   outside this module (``adjudication_packet`` is all it is shown, never a truth's expected
   status). An adjudication that does not cover the state exactly is refused, never repaired.
3. ``score`` applies fixed rules over (1) and (2) and the held-out ``ExpectedOutcome``.

Categories: missing, invented, wrong or stale truth; a correction that retired the wrong
truth; contradictory current truths left implicit; authority bypassed; a declined change
applied; a silent gap; IE3 inconsistent with IE2; incorrect closure. Predicates, values,
subjects and how a truth is split across claims never change a score.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Literal, Protocol

from foundry.domain.closure import evaluate_closure
from foundry.domain.common import FrozenModel, LifecycleStatus, RelationType
from foundry.domain.intent_graph import IE3_GRAPH_NODE_KINDS
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_completeness import SEMANTIC_COMPLETENESS_POLICY_VERSION_V3
from foundry.domain.semantic_judgment import ConflictsWithProposal, SupersedeProposal
from foundry.domain.semantic_view import active_judgment_ids, derive_view
from foundry.domain.state import IntentState
from foundry.experiments.intent_engine_e2e.expectations import ExpectedOutcome

__all__ = [
    "Adjudication",
    "AdjudicationPacket",
    "ClaimReading",
    "ClaimView",
    "CompletenessView",
    "CorrectionSetView",
    "Defect",
    "DefectCategory",
    "FinalOutcome",
    "GapView",
    "GraphObjectView",
    "InvalidAdjudication",
    "OutcomeAdjudicator",
    "OutcomeReport",
    "PacketClaim",
    "PacketTruth",
    "adjudication_packet",
    "final_outcome",
    "score",
]


class DefectCategory(StrEnum):
    MISSING_TRUTH = "MISSING_TRUTH"
    INVENTED_TRUTH = "INVENTED_TRUTH"
    WRONG_TRUTH = "WRONG_TRUTH"
    STALE_TRUTH = "STALE_TRUTH"
    WRONG_CORRECTION_TARGET = "WRONG_CORRECTION_TARGET"
    CONTRADICTORY_CURRENT_TRUTHS = "CONTRADICTORY_CURRENT_TRUTHS"
    AUTHORITY_BYPASSED = "AUTHORITY_BYPASSED"
    DECLINED_CHANGE_APPLIED = "DECLINED_CHANGE_APPLIED"
    SILENT_GAP = "SILENT_GAP"
    IE3_INCONSISTENT_WITH_IE2 = "IE3_INCONSISTENT_WITH_IE2"
    INCORRECT_CLOSURE = "INCORRECT_CLOSURE"


# --- 1. the final state ---------------------------------------------------------------------


class ClaimView(FrozenModel):
    claim_id: str
    subject: str
    predicate: str
    value: str
    current: bool
    """Its asserting judgment is applied and active. A claim that is not current was retired."""
    created_by: str


class CorrectionSetView(FrozenModel):
    correction_set_id: str
    subject: str
    status: Literal["PENDING", "AGREED", "DECLINED"]
    member_judgment_ids: tuple[str, ...]
    target_judgment_ids: tuple[str, ...]


class CompletenessView(FrozenModel):
    verification_id: str
    policy_version: str
    outcome: Literal["PASS", "FAIL"]
    held_proposition_ids: tuple[str, ...]
    gap_ids: tuple[str, ...]


class GapView(FrozenModel):
    gap_id: str
    status: Literal["OPEN", "RESOLVED", "WAIVED"]
    blocking: bool


class GraphObjectView(FrozenModel):
    object_id: str
    current: bool
    derived_from: tuple[str, ...]


class FinalOutcome(FrozenModel):
    scenario_id: str
    claims: tuple[ClaimView, ...]
    applied_judgment_ids: tuple[str, ...]
    applied_supersedes: tuple[tuple[str, bool], ...]
    """(judgment id, proposed by a human) for every applied SUPERSEDE."""
    correction_sets: tuple[CorrectionSetView, ...]
    completeness: tuple[CompletenessView, ...]
    gaps: tuple[GapView, ...]
    explicit_conflicts: tuple[tuple[str, str], ...]
    """Claim pairs a recorded CONFLICTS_WITH names (applied or pending authority)."""
    graph: tuple[GraphObjectView, ...]
    ie3_evaluated: bool
    closure_gap_blockers: tuple[str, ...]
    """Gap ids closure reports as ``OPEN_BLOCKING_GAP``."""
    refused_steps: tuple[str, ...]
    """Steps whose evidence entered but whose IE2 run ended in an exception (no record)."""


def final_outcome(
    state: IntentState,
    *,
    scenario_id: str,
    scope: str,
    ie3_evaluated: bool,
    refused_steps: tuple[str, ...] = (),
) -> FinalOutcome:
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    applied = frozenset(semantic.applied_judgment_ids)

    def subject(address_id: str) -> str:
        address = semantic.addresses.get(address_id)
        return address.subject if address is not None else ""

    claims = tuple(
        ClaimView(
            claim_id=c.claim_id,
            subject=subject(c.address_id),
            predicate=c.predicate,
            value=c.value.text if c.value.text is not None else c.value.model_dump_json(),
            current=c.created_by_judgment_id in active,
            created_by=c.created_by_judgment_id,
        )
        for c in semantic.claims.values()
        if c.created_by_judgment_id in applied
    )
    supersedes = tuple(
        (j.judgment_id, j.reasoner.is_human)
        for j in semantic.judgments.values()
        if j.judgment_id in applied and isinstance(j.proposal, SupersedeProposal)
    )
    pending = frozenset(derive_view(semantic).pending_judgment_ids)
    conflicts = tuple(
        (j.proposal.claim_a, j.proposal.claim_b)
        for j in semantic.judgments.values()
        if isinstance(j.proposal, ConflictsWithProposal)
        and (j.judgment_id in active or j.judgment_id in pending)
    )
    graph = tuple(
        GraphObjectView(
            object_id=o.id,
            current=o.lifecycle is LifecycleStatus.ACTIVE
            and o.authority.value not in ("REJECTED", "SUPERSEDED"),
            derived_from=tuple(
                r.target_id for r in o.relations if r.relation_type is RelationType.DERIVED_FROM
            ),
        )
        for o in state.objects.values()
        if o.kind in IE3_GRAPH_NODE_KINDS and o.kind is not SemanticKind.INTENT
    )
    closure = evaluate_closure(state, scope)
    return FinalOutcome(
        scenario_id=scenario_id,
        claims=claims,
        applied_judgment_ids=tuple(semantic.applied_judgment_ids),
        applied_supersedes=supersedes,
        correction_sets=tuple(
            CorrectionSetView(
                correction_set_id=r.correction_set_id,
                subject=subject(r.address_id),
                status=r.status,
                member_judgment_ids=r.member_judgment_ids,
                target_judgment_ids=r.target_judgment_ids,
            )
            for r in semantic.correction_sets.values()
        ),
        completeness=tuple(
            CompletenessView(
                verification_id=r.verification_id,
                policy_version=r.verifier.policy_version,
                outcome=r.outcome,
                held_proposition_ids=r.held_proposition_ids,
                gap_ids=r.gap_ids,
            )
            for r in semantic.completeness_records.values()
        ),
        gaps=tuple(
            GapView(gap_id=g.id, status=g.status.value, blocking=g.blocking)
            for g in state.gaps.values()
        ),
        explicit_conflicts=conflicts,
        graph=graph,
        ie3_evaluated=ie3_evaluated,
        closure_gap_blockers=tuple(
            gid for b in closure.blockers if b.code == "OPEN_BLOCKING_GAP" for gid in b.object_ids
        ),
        refused_steps=refused_steps,
    )


# --- 2. adjudication --------------------------------------------------------------------------


class PacketTruth(FrozenModel):
    truth_id: str
    concern: str
    statement: str


class PacketClaim(FrozenModel):
    claim_id: str
    subject: str
    predicate: str
    value: str
    current: bool


class AdjudicationPacket(FrozenModel):
    """What the adjudicator is shown: the truths to look for and every claim. Never whether a
    truth is expected current, retired, declined or contested, and never a decision."""

    truths: tuple[PacketTruth, ...]
    claims: tuple[PacketClaim, ...]


class ClaimReading(FrozenModel):
    claim_id: str
    truth_id: str | None
    """The expected truth the claim states, or ``None`` when it states none of them."""
    faithful: bool
    """Whether it states that truth correctly (ignored when ``truth_id`` is ``None``)."""


class Adjudication(FrozenModel):
    readings: tuple[ClaimReading, ...]
    contradictions: tuple[tuple[str, str], ...]
    """Pairs of current claims that cannot both hold."""


class OutcomeAdjudicator(Protocol):
    def adjudicate(self, packet: AdjudicationPacket) -> Adjudication: ...


class InvalidAdjudication(ValueError):
    """The adjudication does not cover the final state exactly. Nothing is scored."""


def adjudication_packet(outcome: FinalOutcome, expected: ExpectedOutcome) -> AdjudicationPacket:
    return AdjudicationPacket(
        truths=tuple(
            PacketTruth(truth_id=t.truth_id, concern=t.concern, statement=t.statement)
            for t in expected.truths
        ),
        claims=tuple(
            PacketClaim(
                claim_id=c.claim_id,
                subject=c.subject,
                predicate=c.predicate,
                value=c.value,
                current=c.current,
            )
            for c in outcome.claims
        ),
    )


def _validate(outcome: FinalOutcome, expected: ExpectedOutcome, adj: Adjudication) -> None:
    claim_ids = [c.claim_id for c in outcome.claims]
    read = [r.claim_id for r in adj.readings]
    if sorted(read) != sorted(claim_ids):
        raise InvalidAdjudication("every claim must be read exactly once")
    truths = {t.truth_id for t in expected.truths}
    unknown = sorted({r.truth_id for r in adj.readings if r.truth_id is not None} - truths)
    if unknown:
        raise InvalidAdjudication(f"unknown truths: {unknown}")
    current = {c.claim_id for c in outcome.claims if c.current}
    for a, b in adj.contradictions:
        if a == b or a not in current or b not in current:
            raise InvalidAdjudication(
                f"a contradiction names two distinct current claims: {a}, {b}"
            )


# --- 3. scoring -------------------------------------------------------------------------------


class Defect(FrozenModel):
    category: DefectCategory
    subject: tuple[str, ...]
    """Truth, claim, judgment, correction-set, gap, graph-object or step ids. Never wording."""


class OutcomeReport(FrozenModel):
    scenario_id: str
    verdict: Literal["PASS", "FAIL", "INCOMPLETE"]
    """FAIL on any defect; INCOMPLETE when clean but IE3 was required and not evaluated."""
    defects: tuple[Defect, ...]
    counts: dict[str, int]
    ie3_evaluated: bool


def score(
    outcome: FinalOutcome, expected: ExpectedOutcome, adjudication: Adjudication
) -> OutcomeReport:
    _validate(outcome, expected, adjudication)
    defects: list[Defect] = []

    def add(category: DefectCategory, *subject: str) -> None:
        defects.append(Defect(category=category, subject=subject))

    final = {t.truth_id: t.final for t in expected.truths}
    claim = {c.claim_id: c for c in outcome.claims}
    reading = {r.claim_id: r for r in adjudication.readings}
    current_truths = {
        r.truth_id for r in adjudication.readings if r.truth_id and claim[r.claim_id].current
    }
    retired_truths = {
        r.truth_id for r in adjudication.readings if r.truth_id and not claim[r.claim_id].current
    }

    # Truths.
    for truth_id, status in final.items():
        if status in ("CURRENT", "CONTESTED") and truth_id not in current_truths:
            if truth_id in retired_truths:
                add(DefectCategory.WRONG_CORRECTION_TARGET, truth_id)
            else:
                add(DefectCategory.MISSING_TRUTH, truth_id)
    for c in outcome.claims:
        if not c.current:
            continue
        r = reading[c.claim_id]
        if r.truth_id is None:
            add(DefectCategory.INVENTED_TRUTH, c.claim_id)
        elif final[r.truth_id] == "RETIRED":
            add(DefectCategory.STALE_TRUTH, r.truth_id, c.claim_id)
        elif final[r.truth_id] == "NEVER":
            add(DefectCategory.DECLINED_CHANGE_APPLIED, r.truth_id, c.claim_id)
        elif not r.faithful:
            add(DefectCategory.WRONG_TRUTH, r.truth_id, c.claim_id)

    # Contradictions stay explicit.
    explicit = {frozenset(p) for p in outcome.explicit_conflicts}
    for a, b in adjudication.contradictions:
        if frozenset((a, b)) not in explicit:
            add(DefectCategory.CONTRADICTORY_CURRENT_TRUTHS, *sorted((a, b)))

    # Authority.
    applied = set(outcome.applied_judgment_ids)
    agreed = {
        m for s in outcome.correction_sets if s.status == "AGREED" for m in s.member_judgment_ids
    }
    for s in outcome.correction_sets:
        landed = sorted(applied & set(s.member_judgment_ids))
        if s.status == "PENDING" and landed:
            add(DefectCategory.AUTHORITY_BYPASSED, s.correction_set_id, *landed)
        if s.status == "DECLINED" and landed:
            add(DefectCategory.DECLINED_CHANGE_APPLIED, s.correction_set_id, *landed)
    for judgment_id, human in outcome.applied_supersedes:
        if not human and judgment_id not in agreed:
            add(DefectCategory.AUTHORITY_BYPASSED, judgment_id)

    # Nothing held without a durable, visible gap.
    gaps = {g.gap_id: g for g in outcome.gaps}
    for record in outcome.completeness:
        if record.policy_version != SEMANTIC_COMPLETENESS_POLICY_VERSION_V3:
            continue
        if record.outcome == "FAIL" and (
            not record.gap_ids or any(g not in gaps for g in record.gap_ids)
        ):
            add(DefectCategory.SILENT_GAP, record.verification_id)
    for step_id in outcome.refused_steps:
        add(DefectCategory.SILENT_GAP, step_id)

    # IE3 says what IE2 says.
    if outcome.ie3_evaluated:
        current_claims = {c.claim_id for c in outcome.claims if c.current}
        covered: set[str] = set()
        for g in outcome.graph:
            if not g.current:
                continue
            claims_cited = {x for x in g.derived_from if x in claim}
            covered |= claims_cited
            stale = sorted(claims_cited - current_claims)
            if stale:
                add(DefectCategory.IE3_INCONSISTENT_WITH_IE2, g.object_id, *stale)
        for missing in sorted(current_claims - covered):
            add(DefectCategory.IE3_INCONSISTENT_WITH_IE2, missing)

    # Closure.
    if len(outcome.closure_gap_blockers) != expected.open_blocking_gaps:
        add(DefectCategory.INCORRECT_CLOSURE, *outcome.closure_gap_blockers)

    counts = Counter(d.category.value for d in defects)
    if defects:
        verdict: Literal["PASS", "FAIL", "INCOMPLETE"] = "FAIL"
    elif expected.ie3_required and not outcome.ie3_evaluated:
        verdict = "INCOMPLETE"
    else:
        verdict = "PASS"
    return OutcomeReport(
        scenario_id=outcome.scenario_id,
        verdict=verdict,
        defects=tuple(defects),
        counts={c.value: counts.get(c.value, 0) for c in DefectCategory},
        ie3_evaluated=outcome.ie3_evaluated,
    )
