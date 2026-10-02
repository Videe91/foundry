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
"""

from __future__ import annotations

from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision
from foundry.domain.common import Materiality, RiskLevel
from foundry.domain.completeness_units import CompletenessUnit, completeness_units
from foundry.domain.gaps import Gap, GapKind
from foundry.domain.semantic_completeness import (
    INCOMPLETE_PROPOSITION_MEANING,
    SEMANTIC_COMPLETENESS_POLICY_VERSION_V3,
    AnyCompletenessReport,
    CompletenessOutcome,
    CompletenessRecord,
    CompletenessRequest,
    IncompletePropositionMeaning,
    PropositionReview,
    ReviewedClaim,
    VerdictCompletenessReport,
    completeness_outcome,
    completeness_request_sha256,
    incomplete_meanings,
    not_complete_proposition_ids,
    report_in_policy_format,
)
from foundry.domain.semantic_identity import ClaimValue, SemanticClaim
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    ReasonerFingerprint,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.source_text import numbered_sentences
from foundry.domain.state import IntentState
from foundry.ports.semantic_completeness import (
    CompletenessVerification,
    SemanticCompletenessVerifier,
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
    state: IntentState, request: ReasoningRequest, proposal: AccountedProposal
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
    return CompletenessRequest(
        project_id=request.project_id,
        subject_invocation_id=invocation,
        propositions=tuple(reviews),
    )


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
    check = build_completeness_request(governor.state(), request, proposal)
    if check is None:
        return governor.submit_proposed(writer, proposal.judgments), 0
    answer = verifier.verify(check)
    report = report_in_policy_format(answer.report, answer.verifier.policy_version)
    outcome, codes = completeness_outcome(check, report, verifier=answer.verifier, writer=writer)
    verification_id = f"VER-{check.subject_invocation_id}"
    if answer.verifier.policy_version == SEMANTIC_COMPLETENESS_POLICY_VERSION_V3:
        return _admit_complete_units(
            governor, writer, proposal, check, answer, report, outcome, codes, verification_id
        )
    failures = (
        incomplete_meanings(check, report, verification_id=verification_id)
        if report is not None
        and not isinstance(report, VerdictCompletenessReport)
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
    """Policy v3: hold every unit with a proposition not verified COMPLETE as one blocking gap;
    admit every other unit through the unchanged law. The record precedes the gaps, the gaps
    precede any admission, so the ledger reads in the order the decision was made."""
    units = completeness_units(governor.state().semantic, proposal.judgments, proposal.disposed_by)
    every = tuple(p.proposition_id for p in check.propositions)
    if codes == (INCOMPLETE_PROPOSITION_MEANING,) and isinstance(report, VerdictCompletenessReport):
        failing = set(not_complete_proposition_ids(report))
        held = [u for u in units if failing & set(u.proposition_ids)]
        reason = "NOT_COMPLETE"
    elif outcome == "FAIL":
        held = [
            CompletenessUnit(
                proposition_ids=every, judgment_ids=tuple(j.judgment_id for j in proposal.judgments)
            )
        ]
        reason = codes[0]
    else:
        held, reason = [], ""
    held_judgments = {j for u in held for j in u.judgment_ids}
    gaps = tuple(
        _held_gap(check, unit, reason, verification_id, index)
        for index, unit in enumerate(held, start=1)
    )
    held_propositions = tuple(p for p in every if any(p in u.proposition_ids for u in held))
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
            proposed_judgment_ids=tuple(j.judgment_id for j in proposal.judgments),
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
    admitted = tuple(j for j in proposal.judgments if j.judgment_id not in held_judgments)
    decisions = governor.submit_proposed(writer, admitted) if admitted else ()
    return decisions, 1


def _held_gap(
    check: CompletenessRequest,
    unit: CompletenessUnit,
    reason: str,
    verification_id: str,
    index: int,
) -> Gap:
    """One durable blocking gap for one held unit. Project-wide on purpose: a held proposition
    may bear on any scope, and over-blocking closure is the safe direction."""
    return Gap(
        id=f"GAP-{verification_id}-{index:02d}",
        project_id=check.project_id,
        kind=GapKind.WORKER_DIVERGENCE,
        description=(
            f"Semantic completeness ({reason}) for Call-2 invocation "
            f"{check.subject_invocation_id}, verification {verification_id}: proposition(s) "
            f"{', '.join(unit.proposition_ids) or '(none)'} not applied; judgment(s) "
            f"{', '.join(unit.judgment_ids)} held. Resolve with corrected claims, or by an "
            "authorized decision."
        ),
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=(),
        blocking=True,
    )


def recorded_outcome(state: IntentState, subject_invocation_id: str) -> CompletenessOutcome | None:
    """The RECORDED outcome of the verification of one Call-2 invocation; never recomputed."""
    for record in state.semantic.completeness_records.values():
        if record.subject_invocation_id == subject_invocation_id:
            return record.outcome
    return None
