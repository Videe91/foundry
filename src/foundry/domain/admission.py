"""Deterministic admission routing (Intent Intelligence v2, plan §6; spec §20.1, §22).

``route_judgment`` is the governance gate between a proposed ``SemanticJudgment`` and
canonical state. It is a pure function of ``(state, judgment, policy)`` and routes the
judgment to exactly one ``AdmissionRoute``. It never applies anything; the reducer
applies only what an admission event with route ``APPLY`` records (spec §22.1, §22.11).

Rules, tried strictly in this order; the first that decides wins:

1. STRUCTURAL — every referenced address, claim, evidence item and judgment must exist
   in ``state.semantic``; a ``SUPERSEDE`` target must be applied and currently active;
   a judgment already applied can never be admitted twice; a ``CREATE_ADDRESS`` or
   ``BIND_TO_ADDRESS`` whose candidate is already bound by an ACTIVE applied judgment
   is refused until that judgment is superseded — referential identity ends only when
   the binding judgment is superseded, never by a later writer (spec §4.5, §20.1,
   §21 #10); a ``CONFLICTS_WITH`` must name two claims that exist, are LIVE (their
   asserting judgment active) and share one representative locus under
   ``derive_view`` — exactly the check the reducer applies, so an ``APPLY`` route can
   never be refused downstream and leave an orphan judgment; a ``SUPPORTS_CLAIM`` must
   name a claim that exists and is LIVE and evidence that exists — again exactly the
   reducer's precondition (spec §12, D-ADM-5). Any failure is ``REJECT``
   with reasons prefixed ``STRUCTURAL:`` (spec §22.6, §22.7).
2. ACTIVE CONTRADICTION — if any applied, currently-active judgment ``contradicts()``
   the proposal, the route is ``REJECT`` (``CONTRADICTS_ACTIVE_JUDGMENT:<id>``) for
   anyone, including a human with authority. The current interpretation is changed by
   superseding the active judgment (spec §19), never by recording a parallel
   contradictory one.
3. AUTHORITY INVENTION — an ``ASSERT_CLAIM`` with ``CANONICAL`` authority from a
   non-human reasoner is ``REJECT`` (``AUTHORITY_INVENTION``, spec §22.5, §22.13). From
   a human it needs a covering ``AuthorityRecord`` in ``state.objects``; otherwise
   ``REQUIRE_HUMAN`` (``AUTHORITY_UNRESOLVED``). Skipped entirely when
   ``policy.canonical_requires_authority`` is False.
4. HUMAN AUTHORITY — a human reasoner with a covering ``AuthorityRecord`` is applied for
   any kind (``HUMAN_AUTHORITY``): humans are authority, not buttons (spec §20.1). A
   human without one is just another lens for rules 5–7 — evidence, not authority.
5. LENS DISAGREEMENT — if any prior lens (see below) with the same
   ``proposal_signature`` from an ``independent()`` fingerprint ``contradicts()`` this
   one, the route is ``REQUIRE_HUMAN`` (``LENS_DISAGREEMENT``) for ANY kind. Plan §6.1
   lists this inside the material rule, after low-risk; it is hoisted here because
   ``DISTINCT`` is not a material kind by default, and plan §6.2 case J and spec §21
   failure mode 7 ("two judges disagree: no transition applied") require that an
   independent ``DISTINCT`` over a prior ``EQUIVALENT`` never auto-applies.
6. LOW RISK — a kind outside ``policy.material_kinds`` is applied (``LOW_RISK``).
7. MATERIAL — an independent prior lens that ``agrees()`` is ``APPLY``
   (``INDEPENDENT_CORROBORATION``); none is ``REQUIRE_SECOND_LENS``. A prior judgment
   from the same fingerprint never counts — independence is never faked.

A prior recorded judgment is a *lens* when it has no admission yet, when its latest
admission is ``REQUIRE_SECOND_LENS`` or ``REQUIRE_HUMAN``, or when it was applied and
is currently active. A judgment whose latest admission is ``REJECT`` is never a lens —
neither corroboration nor disagreement — because a rejected judgment can never affect
canonical state (spec §22.11). An applied-but-superseded judgment is not a lens either.

Authority record coverage: the record must be lifecycle ``ACTIVE``, its ``authority``
must not be ``REJECTED`` or ``SUPERSEDED``, ``authorized_by`` must equal the human's
actor id (``reasoner.model``), and its ``scope`` must be project-wide (``()``) or
intersect the target scope. The target scope is the referenced address's scope for
``BIND_TO_ADDRESS`` / ``ASSERT_CLAIM`` and the candidate's scope for ``CREATE_ADDRESS``;
relation and supersession kinds have no single target and require a project-wide record.

The judgment's ``confidence`` field is metadata and is never read here (plan §0.4,
spec §20.1). Rules like "confidence >= threshold", "newer wins" and "last writer wins"
are forbidden and absent.

Pure domain: no I/O, no provider imports.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import Field

from foundry.domain.common import Authority, FrozenModel, LifecycleStatus
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    DistinctProposal,
    EquivalentProposal,
    JudgmentKind,
    JudgmentProposal,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
    agrees,
    contradicts,
    independent,
    proposal_signature,
)
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import active_judgment_ids, derive_view
from foundry.domain.state import IntentState

_DEFAULT_MATERIAL_KINDS = frozenset(
    {JudgmentKind.EQUIVALENT, JudgmentKind.CONFLICTS_WITH, JudgmentKind.SUPERSEDE}
)
_DEAD_AUTHORITIES = frozenset({Authority.REJECTED, Authority.SUPERSEDED})


class AdmissionPolicy(FrozenModel):
    material_kinds: frozenset[JudgmentKind] = _DEFAULT_MATERIAL_KINDS
    canonical_requires_authority: bool = True


class AdmissionDecision(FrozenModel):
    judgment_id: str = Field(min_length=1)
    route: AdmissionRoute
    reasons: tuple[str, ...] = Field(min_length=1)
    corroborating_judgment_ids: tuple[str, ...] = ()


# --- rule 1: structural -----------------------------------------------------


def _missing(kind: str, ids: Iterable[str], known: Iterable[str]) -> list[str]:
    present = frozenset(known)
    return [f"STRUCTURAL: {kind} {ref} does not exist" for ref in ids if ref not in present]


def _referenced_addresses(p: JudgmentProposal) -> tuple[str, ...]:
    match p:
        case BindToAddressProposal() | AssertClaimProposal():
            return (p.address_id,)
        case EquivalentProposal() | DistinctProposal():
            return (p.address_a, p.address_b)
        case _:
            return ()


def _referenced_claims(p: JudgmentProposal) -> tuple[str, ...]:
    match p:
        case ConflictsWithProposal():
            return (p.claim_a, p.claim_b)
        case SupportsClaimProposal():
            return (p.claim_id,)
        case _:
            return ()


def _referenced_evidence(judgment: SemanticJudgment) -> tuple[str, ...]:
    p = judgment.proposal
    match p:
        case CreateAddressProposal() | BindToAddressProposal():
            proposal_evidence = p.candidate.evidence_ids
        case AssertClaimProposal() | SupportsClaimProposal():
            proposal_evidence = p.evidence_ids
        case _:
            proposal_evidence = ()
    return judgment.visible_evidence_ids + proposal_evidence


def _supersede_problems(p: JudgmentProposal, semantic: SemanticState) -> list[str]:
    if not isinstance(p, SupersedeProposal):
        return []
    target = p.target_judgment_id
    if target not in semantic.applied_judgment_ids:
        return [f"STRUCTURAL: supersede target {target} is not an applied judgment"]
    if target not in active_judgment_ids(semantic):
        return [f"STRUCTURAL: supersede target {target} is already superseded"]
    return []


def _active_binding_judgment(semantic: SemanticState, candidate_id: str) -> str | None:
    """The active applied CREATE/BIND judgment currently binding ``candidate_id``, if any.

    Mirrors ``semantic_view._active_bindings``: applied order, active judgments only.
    """
    active = active_judgment_ids(semantic)
    bound_by: str | None = None
    for judgment_id in semantic.applied_judgment_ids:
        prior = semantic.judgments.get(judgment_id)
        if prior is None or judgment_id not in active:
            continue
        p = prior.proposal
        if (
            isinstance(p, CreateAddressProposal | BindToAddressProposal)
            and p.candidate.candidate_id == candidate_id
        ):
            bound_by = judgment_id
    return bound_by


def _binding_problems(p: JudgmentProposal, semantic: SemanticState) -> list[str]:
    if not isinstance(p, CreateAddressProposal | BindToAddressProposal):
        return []
    candidate_id = p.candidate.candidate_id
    bound_by = _active_binding_judgment(semantic, candidate_id)
    if bound_by is None:
        return []
    return [f"STRUCTURAL: candidate {candidate_id} already bound by {bound_by}; supersede it first"]


def _conflict_problems(p: JudgmentProposal, semantic: SemanticState) -> list[str]:
    """Both claims must be live and at one locus — the reducer's own precondition."""
    if not isinstance(p, ConflictsWithProposal):
        return []
    if p.claim_a not in semantic.claims or p.claim_b not in semantic.claims:
        return []  # already reported as missing
    locus_of = {
        claim_id: locus.representative_id
        for locus in derive_view(semantic).loci
        for claim_id in locus.claim_ids
    }
    locus_a, locus_b = locus_of.get(p.claim_a), locus_of.get(p.claim_b)
    if locus_a is not None and locus_a == locus_b:
        return []
    return [f"STRUCTURAL: claims {p.claim_a}, {p.claim_b} are not live claims at one locus"]


def _support_problems(p: JudgmentProposal, semantic: SemanticState) -> list[str]:
    """The supported claim must be live — the reducer's own precondition (D-ADM-5)."""
    if not isinstance(p, SupportsClaimProposal):
        return []
    claim = semantic.claims.get(p.claim_id)
    if claim is None:
        return []  # already reported as missing
    if claim.created_by_judgment_id in active_judgment_ids(semantic):
        return []
    return [f"STRUCTURAL: claim {p.claim_id} is not live"]


def _structural(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision | None:
    semantic = state.semantic
    problems: list[str] = []
    if judgment.judgment_id in semantic.applied_judgment_ids:
        problems.append(f"STRUCTURAL: judgment {judgment.judgment_id} is already applied")
    problems += _missing("address", _referenced_addresses(judgment.proposal), semantic.addresses)
    problems += _missing("claim", _referenced_claims(judgment.proposal), semantic.claims)
    problems += _missing("evidence", _referenced_evidence(judgment), semantic.evidence)
    problems += _supersede_problems(judgment.proposal, semantic)
    problems += _binding_problems(judgment.proposal, semantic)
    problems += _conflict_problems(judgment.proposal, semantic)
    problems += _support_problems(judgment.proposal, semantic)
    if not problems:
        return None
    return AdmissionDecision(
        judgment_id=judgment.judgment_id, route=AdmissionRoute.REJECT, reasons=tuple(problems)
    )


# --- rule 2: contradiction with an active applied judgment -------------------------


def _active_contradiction(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision | None:
    semantic = state.semantic
    contradicted = tuple(
        f"CONTRADICTS_ACTIVE_JUDGMENT:{judgment_id}"
        for judgment_id in sorted(active_judgment_ids(semantic))
        if judgment_id != judgment.judgment_id
        and contradicts(semantic.judgments[judgment_id].proposal, judgment.proposal)
    )
    if not contradicted:
        return None
    return AdmissionDecision(
        judgment_id=judgment.judgment_id, route=AdmissionRoute.REJECT, reasons=contradicted
    )


# --- authority record lookup (rules 3 and 4) -----------------------------------


def _target_scope(state: IntentState, p: JudgmentProposal) -> tuple[str, ...] | None:
    """Scope of the single target address, or None when the kind has no single target."""
    match p:
        case CreateAddressProposal():
            return p.candidate.scope
        case BindToAddressProposal() | AssertClaimProposal():
            return state.semantic.addresses[p.address_id].scope
        case _:
            return None


def authority_record_is_live(record: AuthorityRecord) -> bool:
    """The single liveness rule for an AuthorityRecord: ACTIVE and not REJECTED/SUPERSEDED.

    Shared with the handoff builder so the two can never drift.
    """
    return record.lifecycle is LifecycleStatus.ACTIVE and record.authority not in _DEAD_AUTHORITIES


_record_is_live = authority_record_is_live


def _record_covers(record: AuthorityRecord, target_scope: tuple[str, ...] | None) -> bool:
    if record.scope == ():
        return True
    if target_scope is None:
        return False
    return bool(frozenset(record.scope) & frozenset(target_scope))


def _covering_authority_record(
    state: IntentState, judgment: SemanticJudgment
) -> AuthorityRecord | None:
    if not judgment.reasoner.is_human:
        return None
    target_scope = _target_scope(state, judgment.proposal)
    for _, obj in sorted(state.objects.items()):
        if (
            isinstance(obj, AuthorityRecord)
            and obj.authorized_by == judgment.reasoner.model
            and _record_is_live(obj)
            and _record_covers(obj, target_scope)
        ):
            return obj
    return None


# --- rule 3: authority invention ---------------------------------------------


def _authority_invention(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision | None:
    p = judgment.proposal
    if not policy.canonical_requires_authority:
        return None
    if not isinstance(p, AssertClaimProposal) or p.authority is not Authority.CANONICAL:
        return None
    if not judgment.reasoner.is_human:
        return AdmissionDecision(
            judgment_id=judgment.judgment_id,
            route=AdmissionRoute.REJECT,
            reasons=("AUTHORITY_INVENTION",),
        )
    if _covering_authority_record(state, judgment) is None:
        return AdmissionDecision(
            judgment_id=judgment.judgment_id,
            route=AdmissionRoute.REQUIRE_HUMAN,
            reasons=("AUTHORITY_UNRESOLVED",),
        )
    return None


# --- rule 4: human authority path ----------------------------------------------


def _human_authority(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision | None:
    if _covering_authority_record(state, judgment) is None:
        return None
    return AdmissionDecision(
        judgment_id=judgment.judgment_id,
        route=AdmissionRoute.APPLY,
        reasons=("HUMAN_AUTHORITY",),
    )


# --- rule 5: lens disagreement (any kind) ------------------------------------------


def _lens_disagreement(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision | None:
    disagreeing = tuple(
        prior.judgment_id
        for prior in _independent_lenses(state.semantic, judgment)
        if contradicts(prior.proposal, judgment.proposal)
    )
    if not disagreeing:
        return None
    return AdmissionDecision(
        judgment_id=judgment.judgment_id,
        route=AdmissionRoute.REQUIRE_HUMAN,
        reasons=("LENS_DISAGREEMENT",),
        corroborating_judgment_ids=disagreeing,
    )


# --- rule 6: low risk -----------------------------------------------------------


def _low_risk(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision | None:
    if judgment.kind in policy.material_kinds:
        return None
    return AdmissionDecision(
        judgment_id=judgment.judgment_id, route=AdmissionRoute.APPLY, reasons=("LOW_RISK",)
    )


# --- rule 7: material -------------------------------------------------------------


def _is_lens(semantic: SemanticState, judgment_id: str, active: frozenset[str]) -> bool:
    """A recorded judgment counts as a lens unless rejected or applied-but-inactive."""
    if judgment_id in semantic.applied_judgment_ids:
        return judgment_id in active
    admission = semantic.admissions.get(judgment_id)
    return admission is None or admission.route is not AdmissionRoute.REJECT


def _independent_lenses(
    semantic: SemanticState, judgment: SemanticJudgment
) -> tuple[SemanticJudgment, ...]:
    """Prior lenses on the same signature from an independent fingerprint.

    The judgment being routed never counts as its own lens.
    """
    active = active_judgment_ids(semantic)
    signature = proposal_signature(judgment.proposal)
    return tuple(
        prior
        for _, prior in sorted(semantic.judgments.items())
        if prior.judgment_id != judgment.judgment_id
        and _is_lens(semantic, prior.judgment_id, active)
        and proposal_signature(prior.proposal) == signature
        and independent(prior.reasoner, judgment.reasoner)
    )


def _material(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision | None:
    agreeing = tuple(
        prior.judgment_id
        for prior in _independent_lenses(state.semantic, judgment)
        if agrees(prior.proposal, judgment.proposal)
    )
    if agreeing:
        return AdmissionDecision(
            judgment_id=judgment.judgment_id,
            route=AdmissionRoute.APPLY,
            reasons=("INDEPENDENT_CORROBORATION",),
            corroborating_judgment_ids=agreeing,
        )
    return AdmissionDecision(
        judgment_id=judgment.judgment_id,
        route=AdmissionRoute.REQUIRE_SECOND_LENS,
        reasons=("MATERIAL_REQUIRES_SECOND_LENS",),
    )


# --- entry point --------------------------------------------------------------------

_Rule = Callable[[IntentState, SemanticJudgment, AdmissionPolicy], AdmissionDecision | None]

_RULES: tuple[_Rule, ...] = (
    _structural,
    _active_contradiction,
    _authority_invention,
    _human_authority,
    _lens_disagreement,
    _low_risk,
    _material,
)


def route_judgment(
    state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy
) -> AdmissionDecision:
    """Route one proposed judgment. Pure and deterministic; never mutates ``state``."""
    for rule in _RULES:
        decision = rule(state, judgment, policy)
        if decision is not None:
            return decision
    raise AssertionError("admission rules are exhaustive; the material rule always decides")
