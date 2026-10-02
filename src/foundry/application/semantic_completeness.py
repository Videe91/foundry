"""IE2 Call 3: semantic completeness verification before any Call-2 mutation.

Pipeline ``ie2-verified-assimilation-v1``::

    Call 1 (concern/binding) -> Call 2 (claim writing, adapter accounting)
        -> Call 3 (this verification) -> only on PASS: admission

``verified_propose_and_submit`` asks the accounting reasoner for its proposal (a structural
accounting refusal still raises exactly as before, and nothing is recorded), builds the bounded
``CompletenessRequest`` deterministically from the model's own propositions and the claims
disposing of each (asserted claims, the supported existing claim, and, as context, the claims a
SUPERSEDE would retire), asks the independent verifier, and records the verification durably
(``SEMANTIC_COMPLETENESS_RECORDED``) whatever its outcome. Only on PASS does the proposal reach
admission, and so correction sets and authority work. On FAIL nothing of Call 2 is recorded or
applied, and ``SemanticCompletenessRefused`` carries each ``INCOMPLETE_PROPOSITION_MEANING``.
A semantic failure is never re-proposed. A proposal with no proposition needs no verification:
it carries no claim content to lose.

**Runtime verifier (policy ``ie2-semantic-completeness-v3``, Intent Engine runtime reset).**
A response is no longer applied or refused whole. ``completeness_units`` partitions it into
minimal safe units (a proposition with every judgment of it, closed over correction sets); a
unit whose every proposition is ``COMPLETE`` goes on to the unchanged admission and authority
law, and every other unit is held: none of its judgments is recorded or applied, so no
correction set and no authority work can exist for it, and one durable blocking gap
(``WORKER_DIVERGENCE``, project-wide) names it, so closure cannot pass it. An invalid answer
(no report, a malformed or partial one, the wrong format) or a verifier that is not
independent holds the whole response the same way. The note is never read; nothing is retried.
v1 and v2 verifications keep the earlier all-or-nothing behaviour unchanged.

**Runtime holds (``ie2-runtime-holds-v1``, round 2).** Every hold is a ``SemanticHoldGap``
scoped to the concerns it touches (``application.semantic_holds``). A proposition the model
says conflicts with a current claim, or with a sibling proposition (joined into one conflict
group), is held as one blocking ``CONTRADICTION`` gap; the current claim stays current and no
winner is picked. A verifier that cannot be selected or reached (``VerifierUnavailable``)
holds the whole response as ``VERIFICATION_UNAVAILABLE``: no semantic verdict exists, nothing
applies. After admission, an open hold whose cause the admitted work removed is closed
deterministically (``domain.hold_resolution``); replay reads that ``GAP_RESOLVED``.
"""

from __future__ import annotations

from typing import Final

from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_holds import (
    close_resolved_holds,
    hold_basis,
    hold_gap,
    judgment_addresses,
)
from foundry.domain.admission import AdmissionDecision
from foundry.domain.completeness_units import CompletenessUnit, completeness_units
from foundry.domain.hold_resolution import conflict_findings
from foundry.domain.semantic_completeness import (
    INCOMPLETE_PROPOSITION_MEANING,
    SEMANTIC_ADMISSION_POLICY_VERSION_V4,
    SEMANTIC_ADMISSION_POLICY_VERSION_V5,
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
    SEMANTIC_CONFLICT,
    SEMANTIC_REPLACEMENT_CONFLICT,
    SEMANTIC_REPLACEMENT_UNCERTAIN,
    SEMANTIC_UNCERTAIN,
    AdmissionReport,
    AdmissionReportV5,
    AdmissionRequest,
    AdmissionRequestV5,
    AdmissionVerdictV5,
    AnyCompletenessReport,
    CompletenessOutcome,
    CompletenessRecord,
    CompletenessRequest,
    ContextClaim,
    IncompletePropositionMeaning,
    PropositionReview,
    ReplacementTarget,
    ReviewedClaim,
    VerdictCompletenessReport,
    completeness_outcome,
    completeness_request_sha256,
    incomplete_meanings,
    not_complete_proposition_ids,
    report_in_policy_format,
)
from foundry.domain.semantic_holds import HoldCause, SemanticHoldGap
from foundry.domain.semantic_identity import ClaimValue, SemanticClaim
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.source_text import numbered_sentences
from foundry.domain.state import IntentState
from foundry.ports.semantic_completeness import (
    CompletenessVerification,
    SemanticCompletenessVerifier,
    VerifierUnavailable,
)
from foundry.ports.semantic_reasoner import (
    AccountedProposal,
    ReasoningRequest,
    SemanticReasoner,
)

__all__ = [
    "SemanticCompletenessRefused",
    "SemanticCompletenessRequired",
    "build_completeness_request",
    "recorded_outcome",
    "verified_propose_and_submit",
]


class SemanticCompletenessRequired(ValueError):
    """A pipeline that must verify was asked to run without a verifier (or without an
    accounting reasoner); nothing was written."""


class SemanticCompletenessRefused(RuntimeError):  # noqa: N818 - a refusal, like its peers
    """The verification FAILed: nothing of the Call-2 proposal was applied. The record (with the
    proposal and the verifier's findings) is durable."""

    def __init__(
        self, record: CompletenessRecord, failures: tuple[IncompletePropositionMeaning, ...]
    ) -> None:
        super().__init__(
            f"{record.subject_invocation_id}: semantic completeness FAIL "
            f"({', '.join(record.failure_codes)})"
        )
        self.record = record
        self.failures = failures


def _render(value: ClaimValue) -> str:
    if value.text is not None:
        return value.text
    if value.quantity is not None:
        return f"{value.quantity} {value.unit}" if value.unit else str(value.quantity)
    return value.kind.value


def _existing(state: IntentState, claim: SemanticClaim, ref: str, role: str) -> ReviewedClaim:
    address = state.semantic.addresses.get(claim.address_id)
    return ReviewedClaim(
        ref=ref,
        role=role,  # type: ignore[arg-type]
        subject=address.subject if address is not None else "",
        predicate=claim.predicate,
        value=_render(claim.value),
    )


def build_completeness_request(
    state: IntentState,
    request: ReasoningRequest,
    proposal: AccountedProposal,
    *,
    consistency: bool = False,
    replacement: bool = False,
) -> CompletenessRequest | None:
    """Deterministic: every proposition of the proposal with the claims disposing of it."""
    if not proposal.propositions:
        return None
    semantic = state.semantic
    text = {
        sid: sentence
        for item in request.evidence
        for sid, sentence in numbered_sentences(item.evidence_id, item.content)
    }
    subjects = {a.address_id: a.subject for a in request.known_addresses}
    by_creator = {c.created_by_judgment_id: (cid, c) for cid, c in semantic.claims.items()}
    reviews: list[PropositionReview] = []
    for prop in proposal.propositions:
        disposing = [
            j
            for j in proposal.judgments
            if proposal.disposed_by.get(j.judgment_id) == prop.proposition_id
        ]
        asserted: list[ReviewedClaim] = []
        supported: list[ReviewedClaim] = []
        retired: list[ReviewedClaim] = []
        for j in disposing:
            p = j.proposal
            if isinstance(p, AssertClaimProposal):
                asserted.append(
                    ReviewedClaim(
                        ref=j.judgment_id,
                        role="ASSERTED",
                        subject=subjects.get(p.address_id, ""),
                        predicate=p.predicate,
                        value=_render(p.value),
                    )
                )
            elif isinstance(p, SupportsClaimProposal):
                supported.append(
                    _existing(state, semantic.claims[p.claim_id], p.claim_id, "SUPPORTED")
                )
            elif isinstance(p, SupersedeProposal) and p.target_judgment_id in by_creator:
                cid, claim = by_creator[p.target_judgment_id]
                retired.append(_existing(state, claim, cid, "RETIRED"))
        if asserted and supported or not (asserted or supported):
            raise SemanticCompletenessRequired(
                f"proposition {prop.proposition_id} has no reviewable disposition"
            )
        reviews.append(
            PropositionReview(
                proposition_id=prop.proposition_id,
                statement=prop.statement,
                source_sentences=tuple(text[sid] for sid in prop.sentence_ids),
                disposition="SUPPORT"
                if supported
                else ("ASSERT_SUPERSEDE" if retired else "ASSERT"),
                claims=tuple(supported or asserted),
                retired=tuple(retired),
            )
        )
    invocation = proposal.judgments[0].invocation_id if proposal.judgments else "NONE"
    if replacement:
        return AdmissionRequestV5(
            project_id=request.project_id,
            subject_invocation_id=invocation,
            propositions=tuple(reviews),
            current_claims=_context_claims(state, proposal),
            replacement_targets=replacement_targets(state, proposal),
        )
    if consistency:
        return AdmissionRequest(
            project_id=request.project_id,
            subject_invocation_id=invocation,
            propositions=tuple(reviews),
            current_claims=_context_claims(state, proposal),
        )
    return CompletenessRequest(
        project_id=request.project_id,
        subject_invocation_id=invocation,
        propositions=tuple(reviews),
    )


def _context_claims(state: IntentState, proposal: AccountedProposal) -> tuple[ContextClaim, ...]:
    """The bounded consistency context (v4): every current claim at a concern the response's
    claim judgments touch, except a claim the response itself retires. Nothing else of state."""
    semantic = state.semantic
    active = active_judgment_ids(semantic)
    addresses = {a for j in proposal.judgments for a in judgment_addresses(state, j)}
    retired = {
        j.proposal.target_judgment_id
        for j in proposal.judgments
        if isinstance(j.proposal, SupersedeProposal)
    }
    return tuple(
        ContextClaim(
            claim_id=cid,
            subject=semantic.addresses[c.address_id].subject,
            predicate=c.predicate,
            value=_render(c.value),
        )
        for cid, c in sorted(semantic.claims.items())
        if c.address_id in addresses
        and c.created_by_judgment_id in active
        and c.created_by_judgment_id not in retired
    )


def replacement_targets(
    state: IntentState, proposal: AccountedProposal
) -> tuple[ReplacementTarget, ...]:
    """Policy v5: every current claim a proposition of the response proposes to SUPERSEDE, by
    proposition, in response order. Read from judgments and state only, never from wording."""
    semantic = state.semantic
    by_creator = {c.created_by_judgment_id: (cid, c) for cid, c in semantic.claims.items()}
    out: list[ReplacementTarget] = []
    for j in proposal.judgments:
        pid = proposal.disposed_by.get(j.judgment_id)
        p = j.proposal
        if (
            pid is None
            or not isinstance(p, SupersedeProposal)
            or p.target_judgment_id not in by_creator
        ):
            continue
        cid, claim = by_creator[p.target_judgment_id]
        out.append(
            ReplacementTarget(
                proposition_id=pid,
                claim_id=cid,
                subject=semantic.addresses[claim.address_id].subject,
                predicate=claim.predicate,
                value=_render(claim.value),
            )
        )
    return tuple(out)


def verified_propose_and_submit(
    governor: SemanticGovernor,
    reasoner: SemanticReasoner,
    verifier: SemanticCompletenessVerifier,
    request: ReasoningRequest,
) -> tuple[tuple[AdmissionDecision, ...], int]:
    """Call 2 then Call 3, then admission only on PASS. Returns the decisions and the number of
    verifier calls made (0 when the proposal has no proposition, else 1)."""
    propose_accounted = getattr(reasoner, "propose_accounted", None)
    if propose_accounted is None:
        raise SemanticCompletenessRequired(
            f"{type(reasoner).__name__} exposes no proposition accounting to verify"
        )
    proposal: AccountedProposal = propose_accounted(request)
    writer = reasoner.fingerprint
    check = build_completeness_request(
        governor.state(),
        request,
        proposal,
        consistency=bool(getattr(verifier, "checks_consistency", False)),
        replacement=bool(getattr(verifier, "checks_replacement", False)),
    )
    if check is None:
        if proposal.conflicts:
            raise SemanticCompletenessRequired("a conflict names no proposition of the response")
        return governor.submit_proposed(writer, proposal.judgments), 0
    try:
        answer = verifier.verify(check)
    except VerifierUnavailable as unavailable:
        _hold_unverified(governor, proposal, check, str(unavailable))
        return (), 1
    report = report_in_policy_format(answer.report, answer.verifier.policy_version)
    outcome, codes = completeness_outcome(check, report, verifier=answer.verifier, writer=writer)
    verification_id = f"VER-{check.subject_invocation_id}"
    if answer.verifier.policy_version in (
        SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
        SEMANTIC_ADMISSION_POLICY_VERSION_V4,
        SEMANTIC_ADMISSION_POLICY_VERSION_V5,
    ):
        return _admit_complete_units(
            governor, writer, proposal, check, answer, report, outcome, codes, verification_id
        )
    if proposal.conflicts:
        raise SemanticCompletenessRequired(
            f"conflicts are held only under {SEMANTIC_COMPLETENESS_POLICY_VERSION_V3}"
        )
    failures = (
        incomplete_meanings(check, report, verification_id=verification_id)
        if report is not None
        and not isinstance(report, VerdictCompletenessReport | AdmissionReport | AdmissionReportV5)
        and codes == (INCOMPLETE_PROPOSITION_MEANING,)
        else ()
    )
    record = CompletenessRecord(
        verification_id=verification_id,
        project_id=check.project_id,
        subject_invocation_id=check.subject_invocation_id,
        writer=writer,
        verifier=answer.verifier,
        verifier_invocation_id=answer.invocation_id,
        request_sha256=completeness_request_sha256(check),
        request=check,
        proposed_judgment_ids=tuple(j.judgment_id for j in proposal.judgments),
        report=report,
        outcome=outcome,
        failure_codes=codes,
        failures=failures,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
        cost_usd=answer.cost_usd,
        wall_clock_ms=answer.wall_clock_ms,
    )
    governor.record_completeness(record)
    if outcome == "FAIL":
        raise SemanticCompletenessRefused(record, failures)
    return governor.submit_proposed(writer, proposal.judgments), 1


def _admit_complete_units(
    governor: SemanticGovernor,
    writer: ReasonerFingerprint,
    proposal: AccountedProposal,
    check: CompletenessRequest,
    answer: CompletenessVerification,
    report: AnyCompletenessReport | None,
    outcome: CompletenessOutcome,
    codes: tuple[str, ...],
    verification_id: str,
) -> tuple[tuple[AdmissionDecision, ...], int]:
    """Policy v3: hold every unit with a proposition not verified COMPLETE, or named in a
    conflict, as one blocking gap per cause; admit every other unit through the unchanged law;
    then close any earlier hold the admitted work resolves. The record precedes the gaps, the
    gaps precede any admission, so the ledger reads in the order the decision was made."""
    state = governor.state()
    judgments = proposal.judgments
    every = tuple(p.proposition_id for p in check.propositions)
    invalid_conflicts = conflict_findings(state, every, proposal.conflicts)
    siblings = tuple(
        (c.proposition_id, c.with_proposition_id)
        for c in proposal.conflicts
        if c.with_proposition_id is not None
    )
    units = completeness_units(
        state.semantic, judgments, proposal.disposed_by, () if invalid_conflicts else siblings
    )
    whole = CompletenessUnit(
        proposition_ids=every, judgment_ids=tuple(j.judgment_id for j in judgments)
    )
    held: list[tuple[CompletenessUnit, HoldCause, tuple[str, ...]]] = []
    if isinstance(check, AdmissionRequestV5) and check.replacement_targets != replacement_targets(
        state, proposal
    ):  # the verifier must have been shown exactly the proposed supersessions: fail safe
        outcome, codes = "FAIL", ("VERIFIER_OUTPUT_INVALID",)
    verifier_conflicts: dict[str, tuple[str, ...]] = {}
    uncertain: set[str] = set()
    if (
        isinstance(report, AdmissionReport | AdmissionReportV5)
        and outcome == "FAIL"
        and set(codes) <= _SEMANTIC_CODES
    ):
        # Consistency conflicts and replacement conflicts are one fact per proposition: the
        # union of the claims named, routed onto the one contradiction hold of the unit.
        for v in report.verdicts:
            named = set(v.conflicting_claim_ids) if v.consistency == "CONFLICT" else set()
            replacements = v.replacements if isinstance(v, AdmissionVerdictV5) else ()
            named |= {r.claim_id for r in replacements if r.judgement == "CONFLICTING_EVIDENCE"}
            if named:
                verifier_conflicts[v.proposition_id] = tuple(sorted(named))
            if v.consistency == "UNCERTAIN" or any(
                r.judgement == "UNCERTAIN" for r in replacements
            ):
                uncertain.add(v.proposition_id)
        named = {c for ids in verifier_conflicts.values() for c in ids}
        if named - _current_claim_ids(state):  # shown, but no longer current: fail safe
            codes, verifier_conflicts, uncertain = ("VERIFIER_OUTPUT_INVALID",), {}, set()
    if (
        isinstance(report, VerdictCompletenessReport | AdmissionReport | AdmissionReportV5)
        and outcome == "FAIL"
        and set(codes) <= _SEMANTIC_CODES
    ):
        failing = set(not_complete_proposition_ids(report))
        held += [(u, "NOT_COMPLETE", ()) for u in units if failing & set(u.proposition_ids)]
        held += [(u, "UNCERTAIN", ()) for u in units if uncertain & set(u.proposition_ids)]
    elif outcome == "FAIL":
        cause: HoldCause = (
            "VERIFIER_NOT_INDEPENDENT"
            if codes[0] == "VERIFIER_NOT_INDEPENDENT"
            else "VERIFIER_OUTPUT_INVALID"
        )
        held.append((whole, cause, ()))
    if invalid_conflicts and not any(u is whole for u, _, _ in held):
        held.append((whole, "INVALID_CONFLICT_REFERENCE", ()))
    elif not any(u is whole for u, _, _ in held):
        # Writer-declared and verifier-detected conflicts are one fact per unit: one gap.
        conflicted = {c.proposition_id for c in proposal.conflicts} | set(verifier_conflicts)
        for u in units:
            if conflicted & set(u.proposition_ids):
                claims = tuple(
                    sorted(
                        {
                            c.with_claim_id
                            for c in proposal.conflicts
                            if c.proposition_id in u.proposition_ids and c.with_claim_id
                        }
                        | {
                            cid
                            for pid, ids in verifier_conflicts.items()
                            if pid in u.proposition_ids
                            for cid in ids
                        }
                    )
                )
                held.append((u, "CONFLICT", claims))
    held_judgments = {j for u, _, _ in held for j in u.judgment_ids}
    gaps = tuple(
        hold_gap(
            project_id=check.project_id,
            gap_id=f"GAP-{verification_id}-{index:02d}",
            cause=cause,
            invocation_id=check.subject_invocation_id,
            basis=hold_basis(state, check, judgments, proposal.disposed_by, u.proposition_ids),
            proposition_ids=u.proposition_ids,
            judgment_ids=u.judgment_ids,
            conflicting_claim_ids=claims,
            detail=f", verification {verification_id}",
        )
        for index, (u, cause, claims) in enumerate(held, start=1)
    )
    held_propositions = tuple(p for p in every if any(p in u.proposition_ids for u, _, _ in held))
    governor.record_completeness(
        CompletenessRecord(
            verification_id=verification_id,
            project_id=check.project_id,
            subject_invocation_id=check.subject_invocation_id,
            writer=writer,
            verifier=answer.verifier,
            verifier_invocation_id=answer.invocation_id,
            request_sha256=completeness_request_sha256(check),
            request=check,
            proposed_judgment_ids=tuple(j.judgment_id for j in judgments),
            report=report,
            outcome=outcome,
            failure_codes=codes,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
            cost_usd=answer.cost_usd,
            wall_clock_ms=answer.wall_clock_ms,
            held_proposition_ids=held_propositions,
            gap_ids=tuple(g.id for g in gaps),
        )
    )
    for gap in gaps:
        governor.record_gap(gap)
    admitted = tuple(j for j in judgments if j.judgment_id not in held_judgments)
    decisions = governor.submit_proposed(writer, admitted) if admitted else ()
    _close_resolved(governor, state, proposal, check, admitted, decisions, gaps)
    return decisions, 1


_SEMANTIC_CODES: Final = frozenset(
    {
        INCOMPLETE_PROPOSITION_MEANING,
        SEMANTIC_CONFLICT,
        SEMANTIC_UNCERTAIN,
        SEMANTIC_REPLACEMENT_CONFLICT,
        SEMANTIC_REPLACEMENT_UNCERTAIN,
    }
)
"""Verdict codes held per unit; any other FAIL code holds the whole response."""


def _current_claim_ids(state: IntentState) -> set[str]:
    active = active_judgment_ids(state.semantic)
    return {cid for cid, c in state.semantic.claims.items() if c.created_by_judgment_id in active}


def _close_resolved(
    governor: SemanticGovernor,
    before: IntentState,
    proposal: AccountedProposal,
    check: CompletenessRequest,
    admitted: tuple[SemanticJudgment, ...],
    decisions: tuple[AdmissionDecision, ...],
    gaps: tuple[SemanticHoldGap, ...],
) -> None:
    """What this response delivered (propositions verified COMPLETE whose every judgment was
    admitted, not refused) and changed (claims it applied) may close earlier holds."""
    refused = {d.judgment_id for d in decisions if d.route is AdmissionRoute.REJECT}
    admitted_ids = {j.judgment_id for j in admitted}
    delivered_propositions = {
        p
        for p in {proposal.disposed_by.get(j.judgment_id) for j in admitted} - {None}
        if all(
            j.judgment_id in admitted_ids and j.judgment_id not in refused
            for j in proposal.judgments
            if proposal.disposed_by.get(j.judgment_id) == p
        )
    }
    applied = set(governor.state().semantic.applied_judgment_ids)
    close_resolved_holds(
        governor,
        delivered=hold_basis(
            before,
            check,
            admitted,
            proposal.disposed_by,
            delivered_propositions,  # type: ignore[arg-type]
        ),
        applied_addresses={
            j.proposal.address_id
            for j in admitted
            if isinstance(j.proposal, AssertClaimProposal) and j.judgment_id in applied
        },
        exclude={g.id for g in gaps},
    )


def _hold_unverified(
    governor: SemanticGovernor,
    proposal: AccountedProposal,
    check: CompletenessRequest,
    reason: str,
) -> None:
    """No verifier could be selected or reached: nothing of the response applies, and one
    visible hold says so. No completeness record exists, because no verdict exists."""
    every = tuple(p.proposition_id for p in check.propositions)
    governor.record_gap(
        hold_gap(
            project_id=check.project_id,
            gap_id=f"GAP-UNVERIFIED-{check.subject_invocation_id}",
            cause="VERIFICATION_UNAVAILABLE",
            invocation_id=check.subject_invocation_id,
            basis=hold_basis(
                governor.state(), check, proposal.judgments, proposal.disposed_by, every
            ),
            proposition_ids=every,
            judgment_ids=tuple(j.judgment_id for j in proposal.judgments),
            detail=f" ({reason})",
        )
    )


def recorded_outcome(state: IntentState, subject_invocation_id: str) -> CompletenessOutcome | None:
    """The RECORDED outcome of the verification of one Call-2 invocation; never recomputed."""
    for record in state.semantic.completeness_records.values():
        if record.subject_invocation_id == subject_invocation_id:
            return record.outcome
    return None
