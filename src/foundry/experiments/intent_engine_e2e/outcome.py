"""Final-outcome scoring of an end-to-end Intent Engine run. Wording is never read.

Three steps, each separable:

1. ``final_outcome`` -- a deterministic extract of the replayed final state: every claim
   (current or retired), applied judgments and supersessions, correction sets, completeness
   records, gaps (runtime holds with their cause and conflicting claims; IE3 gaps), explicit
   conflicts, the IE3 graph, and closure.
2. An ``OutcomeAdjudicator`` maps the final state onto the hidden final-truth oracle: for every
   claim, which truth it states (or none) and whether faithfully; which pairs of current claims
   contradict; for every current IE3 graph object, which truths it states and whether
   faithfully; for every open IE3 gap, which truths it concerns. That is semantic judgement,
   so it is never deterministic text matching here, and nothing it writes in prose is graded.
   It is shown ``adjudication_packet`` only: truth statements and the final state, never a
   truth's expected status and never a decision. An adjudication that does not cover the state
   exactly is refused, never repaired.
3. ``score`` applies fixed rules over (1), (2) and the held-out ``ExpectedOutcome``.

Categories (the founder's twelve): missing, invented, wrong current or stale truth; a
correction that retired the wrong truth; contradictory current truths; authority bypass; a
declined change applied; a silent gap; an incorrect gap resolution; an IE2 -> IE3 semantic
mismatch; incorrect closure. Predicates, values, subjects, concern labels and how a truth is
split across claims or graph objects never change a score. A visible, open contradiction gap
the oracle expects is correct; two contradictory current truths are a defect.

``evaluate`` is the live experiment's only entry point (design decision Q3): one independent
adjudicator, evaluation only, no production authority. A failed, uncovering or uncertain
adjudication can never yield PASS; post-run human review is diagnostic and cannot change it.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Literal, Protocol

from foundry.domain.closure import evaluate_closure
from foundry.domain.common import FrozenModel, LifecycleStatus, RelationType
from foundry.domain.intent_graph import IE3_GRAPH_NODE_KINDS
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_completeness import (
    SEMANTIC_ADMISSION_POLICY_VERSION_V4,
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
)
from foundry.domain.semantic_holds import SemanticHoldGap
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
    "GapReading",
    "GapView",
    "GraphObjectView",
    "GraphReading",
    "InvalidAdjudication",
    "OutcomeAdjudicator",
    "OutcomeReport",
    "PacketClaim",
    "PacketGap",
    "PacketGraphObject",
    "PacketTruth",
    "adjudication_packet",
    "evaluate",
    "final_outcome",
    "score",
]


class DefectCategory(StrEnum):
    MISSING_TRUTH = "MISSING_TRUTH"
    INVENTED_TRUTH = "INVENTED_TRUTH"
    WRONG_CURRENT_TRUTH = "WRONG_CURRENT_TRUTH"
    STALE_TRUTH = "STALE_TRUTH"
    WRONG_CORRECTION_TARGET = "WRONG_CORRECTION_TARGET"
    CONTRADICTORY_CURRENT_TRUTHS = "CONTRADICTORY_CURRENT_TRUTHS"
    AUTHORITY_BYPASS = "AUTHORITY_BYPASS"
    DECLINED_CHANGE_APPLIED = "DECLINED_CHANGE_APPLIED"
    SILENT_GAP = "SILENT_GAP"
    INCORRECT_GAP_RESOLUTION = "INCORRECT_GAP_RESOLUTION"
    IE2_IE3_SEMANTIC_MISMATCH = "IE2_IE3_SEMANTIC_MISMATCH"
    INCORRECT_CLOSURE = "INCORRECT_CLOSURE"


_RUNTIME_VERIFIER_POLICIES = frozenset(
    {SEMANTIC_COMPLETENESS_POLICY_VERSION_V3, SEMANTIC_ADMISSION_POLICY_VERSION_V4}
)


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
    kind: str
    status: Literal["OPEN", "RESOLVED", "WAIVED"]
    blocking: bool
    hold_cause: str | None = None
    """The cause of a runtime hold (``SemanticHoldGap``); ``None`` for any other gap."""
    conflicting_claim_ids: tuple[str, ...] = ()
    from_ie3: bool = False
    description: str = ""


class GraphObjectView(FrozenModel):
    object_id: str
    current: bool
    derived_from: tuple[str, ...]
    kind: str = "REQUIREMENT"
    text: str = ""


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
    """Current and retired IE3 objects, the INTENT root excluded."""
    ie3_evaluated: bool
    closure_gap_blockers: tuple[str, ...]
    """Gap ids closure reports as ``OPEN_BLOCKING_GAP``."""
    closure_closed: bool = False
    refused_steps: tuple[str, ...]
    """Steps whose evidence entered but whose IE2 run ended in an exception (no record)."""


def _object_text(obj: object) -> str:
    for name in ("statement", "mission", "description"):
        value = getattr(obj, name, None)
        if isinstance(value, str):
            return value
    return ""


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
            kind=o.kind.value,
            text=_object_text(o),
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
            GapView(
                gap_id=g.id,
                kind=g.kind.value,
                status=g.status.value,
                blocking=g.blocking,
                hold_cause=g.cause if isinstance(g, SemanticHoldGap) else None,
                conflicting_claim_ids=(
                    g.conflicting_claim_ids if isinstance(g, SemanticHoldGap) else ()
                ),
                from_ie3=isinstance(g, IntentSynthesisGap),
                description=g.description,
            )
            for g in state.gaps.values()
        ),
        explicit_conflicts=conflicts,
        graph=graph,
        ie3_evaluated=ie3_evaluated,
        closure_gap_blockers=tuple(
            gid for b in closure.blockers if b.code == "OPEN_BLOCKING_GAP" for gid in b.object_ids
        ),
        closure_closed=closure.closed,
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


class PacketGraphObject(FrozenModel):
    object_id: str
    kind: str
    text: str


class PacketGap(FrozenModel):
    gap_id: str
    description: str


class AdjudicationPacket(FrozenModel):
    """What the adjudicator is shown: the truths to look for, every claim, every current IE3
    object and every open IE3 gap. Never whether a truth is expected current, retired,
    declined or held, and never a decision."""

    truths: tuple[PacketTruth, ...]
    claims: tuple[PacketClaim, ...]
    graph_objects: tuple[PacketGraphObject, ...] = ()
    ie3_gaps: tuple[PacketGap, ...] = ()


class ClaimReading(FrozenModel):
    claim_id: str
    truth_id: str | None
    """The expected truth the claim states, or ``None`` when it states none of them."""
    faithful: bool
    """Whether it states that truth correctly (ignored when ``truth_id`` is ``None``)."""
    certain: bool = True
    """``False`` when the adjudicator could not map the claim with confidence. Any uncertain
    reading makes a result that depends on adjudication ``NOT_VALIDATED``, never PASS."""


class GraphReading(FrozenModel):
    object_id: str
    truth_ids: tuple[str, ...]
    """The truths the IE3 object states; empty when it states none of them."""
    faithful: bool
    """Whether it states them correctly and adds nothing material."""
    certain: bool = True


class GapReading(FrozenModel):
    gap_id: str
    truth_ids: tuple[str, ...]
    """The truths an IE3 gap is about; empty when it is about none of them."""
    certain: bool = True


class Adjudication(FrozenModel):
    readings: tuple[ClaimReading, ...]
    contradictions: tuple[tuple[str, str], ...]
    """Pairs of current claims that cannot both hold."""
    graph_readings: tuple[GraphReading, ...] = ()
    gap_readings: tuple[GapReading, ...] = ()


class OutcomeAdjudicator(Protocol):
    def adjudicate(self, packet: AdjudicationPacket) -> Adjudication: ...


class InvalidAdjudication(ValueError):
    """The adjudication does not cover the final state exactly. Nothing is scored."""


def _current_graph(outcome: FinalOutcome) -> tuple[GraphObjectView, ...]:
    return tuple(g for g in outcome.graph if g.current) if outcome.ie3_evaluated else ()


def _open_ie3_gaps(outcome: FinalOutcome) -> tuple[GapView, ...]:
    return tuple(g for g in outcome.gaps if g.from_ie3 and g.status == "OPEN")


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
        graph_objects=tuple(
            PacketGraphObject(object_id=g.object_id, kind=g.kind, text=g.text)
            for g in _current_graph(outcome)
        ),
        ie3_gaps=tuple(
            PacketGap(gap_id=g.gap_id, description=g.description) for g in _open_ie3_gaps(outcome)
        ),
    )


def _validate(outcome: FinalOutcome, expected: ExpectedOutcome, adj: Adjudication) -> None:
    def exactly_once(label: str, read: list[str], want: list[str]) -> None:
        if sorted(read) != sorted(want):
            raise InvalidAdjudication(f"every {label} must be read exactly once")

    exactly_once("claim", [r.claim_id for r in adj.readings], [c.claim_id for c in outcome.claims])
    exactly_once(
        "current IE3 object",
        [r.object_id for r in adj.graph_readings],
        [g.object_id for g in _current_graph(outcome)],
    )
    exactly_once(
        "open IE3 gap",
        [r.gap_id for r in adj.gap_readings],
        [g.gap_id for g in _open_ie3_gaps(outcome)],
    )
    truths = {t.truth_id for t in expected.truths}
    named = {r.truth_id for r in adj.readings if r.truth_id is not None}
    named |= {t for r in adj.graph_readings for t in r.truth_ids}
    named |= {t for r in adj.gap_readings for t in r.truth_ids}
    if named - truths:
        raise InvalidAdjudication(f"unknown truths: {sorted(named - truths)}")
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
    adjudicated: bool
    """Whether finding it depended on the adjudicator's mapping (else it is structural)."""


class OutcomeReport(FrozenModel):
    scenario_id: str
    verdict: Literal["PASS", "FAIL", "INCOMPLETE", "NOT_VALIDATED"]
    """FAIL on any structural defect, or on any defect when every reading is certain.
    NOT_VALIDATED when the adjudication failed, did not cover the state, or was uncertain and
    no structural defect exists. INCOMPLETE when clean but IE3 was required and not run.
    PASS only when clean, certain and complete. Nothing after the run changes a verdict."""
    defects: tuple[Defect, ...]
    counts: dict[str, int]
    ie3_evaluated: bool
    adjudication_issues: tuple[str, ...] = ()


def score(
    outcome: FinalOutcome, expected: ExpectedOutcome, adjudication: Adjudication
) -> OutcomeReport:
    _validate(outcome, expected, adjudication)
    defects: list[Defect] = []

    def add(category: DefectCategory, *subject: str, adjudicated: bool = False) -> None:
        defects.append(Defect(category=category, subject=subject, adjudicated=adjudicated))

    def truth(category: DefectCategory, *subject: str) -> None:
        add(category, *subject, adjudicated=True)

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
        if status == "CURRENT" and truth_id not in current_truths:
            if truth_id in retired_truths:
                truth(DefectCategory.WRONG_CORRECTION_TARGET, truth_id)
            else:
                truth(DefectCategory.MISSING_TRUTH, truth_id)
    for c in outcome.claims:
        if not c.current:
            continue
        r = reading[c.claim_id]
        if r.truth_id is None:
            truth(DefectCategory.INVENTED_TRUTH, c.claim_id)
        elif final[r.truth_id] == "RETIRED":
            truth(DefectCategory.STALE_TRUTH, r.truth_id, c.claim_id)
        elif final[r.truth_id] == "NEVER":
            truth(DefectCategory.DECLINED_CHANGE_APPLIED, r.truth_id, c.claim_id)
        elif final[r.truth_id] == "HELD":
            truth(DefectCategory.CONTRADICTORY_CURRENT_TRUTHS, r.truth_id, c.claim_id)
        elif not r.faithful:
            truth(DefectCategory.WRONG_CURRENT_TRUTH, r.truth_id, c.claim_id)

    # A known contradiction is never two current truths.
    for a, b in expected.contested_pairs:
        if a in current_truths and b in current_truths:
            truth(DefectCategory.CONTRADICTORY_CURRENT_TRUTHS, a, b)
    explicit = {frozenset(p) for p in outcome.explicit_conflicts}
    for a, b in adjudication.contradictions:
        if frozenset((a, b)) not in explicit:
            truth(DefectCategory.CONTRADICTORY_CURRENT_TRUTHS, *sorted((a, b)))

    # Authority.
    applied = set(outcome.applied_judgment_ids)
    agreed = {
        m for s in outcome.correction_sets if s.status == "AGREED" for m in s.member_judgment_ids
    }
    for s in outcome.correction_sets:
        landed = sorted(applied & set(s.member_judgment_ids))
        if s.status == "PENDING" and landed:
            add(DefectCategory.AUTHORITY_BYPASS, s.correction_set_id, *landed)
        if s.status == "DECLINED" and landed:
            add(DefectCategory.DECLINED_CHANGE_APPLIED, s.correction_set_id, *landed)
    for judgment_id, human in outcome.applied_supersedes:
        if not human and judgment_id not in agreed:
            add(DefectCategory.AUTHORITY_BYPASS, judgment_id)

    # Nothing held without a durable, visible gap.
    gaps = {g.gap_id: g for g in outcome.gaps}
    for record in outcome.completeness:
        if record.policy_version not in _RUNTIME_VERIFIER_POLICIES:
            continue
        if record.outcome == "FAIL" and (
            not record.gap_ids or any(g not in gaps for g in record.gap_ids)
        ):
            add(DefectCategory.SILENT_GAP, record.verification_id)
    for step_id in outcome.refused_steps:
        add(DefectCategory.SILENT_GAP, step_id)

    # Gap resolution: a contradiction hold closes only once its conflicting claims are gone,
    # and an expected open contradiction must still be open and visible.
    for g in outcome.gaps:
        if g.hold_cause == "CONFLICT" and g.status != "OPEN":
            still = sorted(c for c in g.conflicting_claim_ids if c in claim and claim[c].current)
            if still:
                add(DefectCategory.INCORRECT_GAP_RESOLUTION, g.gap_id, *still)
    truth_of = {r.claim_id: r.truth_id for r in adjudication.readings}
    for current_side, held_side in expected.open_contradictions:
        holds = [
            g
            for g in outcome.gaps
            if g.hold_cause == "CONFLICT"
            and any(truth_of.get(c) == current_side for c in g.conflicting_claim_ids)
        ]
        if any(g.status == "OPEN" for g in holds):
            continue
        if holds:
            truth(DefectCategory.INCORRECT_GAP_RESOLUTION, current_side, held_side)
        elif held_side not in current_truths:
            truth(DefectCategory.SILENT_GAP, current_side, held_side)

    # IE3 says what IE2 settled.
    if outcome.ie3_evaluated:
        current_claims = {c.claim_id for c in outcome.claims if c.current}
        for obj in _current_graph(outcome):
            cited = {x for x in obj.derived_from if x in claim}
            stale = sorted(cited - current_claims)
            if stale:
                add(DefectCategory.IE2_IE3_SEMANTIC_MISMATCH, obj.object_id, *stale)
        stated: set[str] = set()
        for gr in adjudication.graph_readings:
            stated |= set(gr.truth_ids)
            wrong = sorted(t for t in gr.truth_ids if final[t] != "CURRENT")
            if not gr.truth_ids or wrong or not gr.faithful:
                truth(DefectCategory.IE2_IE3_SEMANTIC_MISMATCH, gr.object_id, *wrong)
        for truth_id in sorted(t for t, s in final.items() if s == "CURRENT"):
            if truth_id in current_truths and truth_id not in stated:
                truth(DefectCategory.IE2_IE3_SEMANTIC_MISMATCH, truth_id)
        open_issue = {t for pair in expected.open_contradictions for t in pair}
        for gp in adjudication.gap_readings:
            if not set(gp.truth_ids) & open_issue:
                truth(DefectCategory.IE2_IE3_SEMANTIC_MISMATCH, gp.gap_id)

    # Closure: exactly the expected runtime holds stay open, and they block it.
    open_holds = [g for g in outcome.gaps if g.hold_cause is not None and g.status == "OPEN"]
    blocking = set(outcome.closure_gap_blockers)
    unblocked = [g.gap_id for g in open_holds if g.gap_id not in blocking]
    if (
        sorted(g.kind for g in open_holds) != sorted(expected.open_blocking_gap_kinds)
        or unblocked
        or outcome.closure_closed != expected.closure_closed
    ):
        add(DefectCategory.INCORRECT_CLOSURE, *unblocked)

    uncertain = tuple(
        f"UNCERTAIN_READING: {i}"
        for i in (
            *(r.claim_id for r in adjudication.readings if not r.certain),
            *(r.object_id for r in adjudication.graph_readings if not r.certain),
            *(r.gap_id for r in adjudication.gap_readings if not r.certain),
        )
    )
    counts = Counter(d.category.value for d in defects)
    verdict: Literal["PASS", "FAIL", "INCOMPLETE", "NOT_VALIDATED"]
    if any(not d.adjudicated for d in defects) or (defects and not uncertain):
        verdict = "FAIL"
    elif uncertain:
        verdict = "NOT_VALIDATED"
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
        adjudication_issues=uncertain,
    )


def evaluate(
    outcome: FinalOutcome, expected: ExpectedOutcome, adjudicator: OutcomeAdjudicator
) -> OutcomeReport:
    """The experiment's only scoring entry point. One adjudicator, shown the final state and
    the judge-only truths; an adjudicator that fails, or answers without covering the state
    exactly, makes the result ``NOT_VALIDATED`` with no defect counted -- never PASS."""
    try:
        adjudication = adjudicator.adjudicate(adjudication_packet(outcome, expected))
        return score(outcome, expected, adjudication)
    except Exception as error:  # a failed mapping is recorded, never repaired or retried
        return OutcomeReport(
            scenario_id=outcome.scenario_id,
            verdict="NOT_VALIDATED",
            defects=(),
            counts={c.value: 0 for c in DefectCategory},
            ie3_evaluated=outcome.ie3_evaluated,
            adjudication_issues=(f"ADJUDICATION_FAILED: {type(error).__name__}",),
        )
