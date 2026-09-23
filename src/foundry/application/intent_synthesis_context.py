"""Bounded context compilation and result validation for Intent Synthesis (T7).

Two halves, both deterministic and both pure:

* **compile** — decide exactly what a synthesizer may see for one scope, and record
  deterministic blockers for the loci it may not;
* **validate** — check what came back against *that exact request*, refusing the whole
  result if any proposal is not grounded in it.

The second half is the load-bearing one: **the model cannot cite invisible state**. A
claim that exists in ``state.semantic`` but was not shown in this request is illegal,
because a proposal grounded in state the model never saw is not a proposal — it is a
guess that happens to typecheck.

Nothing here writes events, mutates state, calls a provider, routes, or constructs a
``Requirement``. Deriving the current view IS this layer's job (unlike the reducer's),
because this is the read model.
"""

from __future__ import annotations

import json
from typing import Final

from foundry.application.assimilation_context import CANDIDATE_ADDRESS_THRESHOLD
from foundry.application.context_errors import ContextUnsupported
from foundry.application.contrastive_context import MAX_COMPARISON_CONTEXT_CHARS
from foundry.domain.common import Authority, FrozenModel, LifecycleStatus, SourceKind
from foundry.domain.gaps import GapKind
from foundry.domain.handoff import judgment_address_ids, locus_in_scope
from foundry.domain.intent_synthesis import (
    INTENT_BEARING_SEMANTIC_KINDS,
    IntentDisposition,
    IntentSynthesisResult,
    RequirementSynthesisProposal,
)
from foundry.domain.semantic import (
    Intent,
    Requirement,
    SemanticBase,
    SemanticKind,
)
from foundry.domain.semantic_identity import ClaimValueKind, IssueEpistemicState
from foundry.domain.semantic_view import CurrentSemanticView, SemanticLocus, derive_view
from foundry.domain.state import IntentState
from foundry.ports.intent_synthesizer import (
    BasisClaim,
    IntentSynthesisRequest,
    KnownIntentObject,
    LocusBasis,
)

__all__ = [
    "MAX_KNOWN_INTENT_CONTEXT_CHARS",
    "KNOWN_INTENT_OBJECT_THRESHOLD",
    "IntentSynthesisContext",
    "IntentSynthesisResultError",
    "SynthesisContextBlocker",
    "ValidatedSynthesisProposal",
    "compile_intent_synthesis_context",
    "known_intent_context_character_count",
    "known_intent_context_json",
    "validate_intent_synthesis_result",
]

KNOWN_INTENT_OBJECT_THRESHOLD: Final[int] = CANDIDATE_ADDRESS_THRESHOLD
"""Count bound on the known-intent snapshot (D9).

Deliberately the SAME constant the candidate-address set already uses: the snapshot is
the direct analogue — "what already exists in this scope, shown in full" — and there is
no principled ground to bound intent objects differently from addresses.
"""

MAX_KNOWN_INTENT_CONTEXT_CHARS: Final[int] = MAX_COMPARISON_CONTEXT_CHARS
"""Character bound on the compiled snapshot (D9), the sibling compiled context's value."""

_DEAD_AUTHORITIES: Final[frozenset[Authority]] = frozenset(
    {Authority.REJECTED, Authority.SUPERSEDED}
)


class IntentSynthesisResultError(RuntimeError):
    """A synthesizer returned something not grounded in the request it was shown.

    Deliberately NOT ``ContextUnsupported``: that means the exact structurally selected
    context exceeds a locked support bound, which is a property of the project, not of
    the model's output. Conflating the two would make a malformed proposal look like a
    scale problem.
    """


class SynthesisContextBlocker(FrozenModel):
    """Why one in-scope locus may not be offered. Orchestration support, not durable truth.

    T8 decides how these become durable ``Gap`` events; T7 mints no gap ids and writes
    nothing.
    """

    locus_representative_id: str
    gap_kind: GapKind
    affected_claim_ids: tuple[str, ...] = ()


class IntentSynthesisContext(FrozenModel):
    """The compiled result: a request when anything is eligible, plus every blocker."""

    request: IntentSynthesisRequest | None
    blockers: tuple[SynthesisContextBlocker, ...] = ()


class ValidatedSynthesisProposal(FrozenModel):
    """A proposal proven grounded in the request, with the two runtime-owned facts.

    ``basis_locus_ids`` and ``target_scope`` are derived here from the claims the
    proposal ACTUALLY cited (C4/I17, I6) — never accepted from the model and never
    widened to everything sharing those loci.
    """

    proposal: RequirementSynthesisProposal
    basis_locus_ids: tuple[str, ...]
    target_scope: tuple[str, ...]


def known_intent_context_json(objects: tuple[KnownIntentObject, ...]) -> str:
    """The exact canonical rendering the character bound is measured on."""
    return json.dumps(
        [o.model_dump(mode="json") for o in objects],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def known_intent_context_character_count(objects: tuple[KnownIntentObject, ...]) -> int:
    return len(known_intent_context_json(objects))


def _statement_of(obj: SemanticBase) -> str:
    """The one human-readable field the model already carries. Nothing is invented.

    ``Decision`` exposes its ``statement``, never its ``rationale``: rationale is
    reasoning, and showing it would leak deliberation into a comparison surface.
    """
    if isinstance(obj, Intent):
        return obj.mission
    statement = getattr(obj, "statement", None)
    if not isinstance(statement, str):
        raise ValueError(f"{obj.kind} exposes no statement for the known-intent snapshot")
    return statement


def _is_current(obj: SemanticBase) -> bool:
    return obj.lifecycle is LifecycleStatus.ACTIVE and obj.authority not in _DEAD_AUTHORITIES


def _object_in_scope(obj: SemanticBase, scope: str) -> bool:
    return obj.scope == () or scope in obj.scope


def _eligible_known_objects(state: IntentState, scope: str) -> list[SemanticBase]:
    """Current, in-scope, intent-bearing objects — stale ones deliberately INCLUDED.

    A stale-but-``ACTIVE`` object is exactly the reconciliation context the synthesizer
    needs in order to return ``REPLACES_STALE``. Excluding it would make reconciliation
    impossible, so staleness is surfaced as a flag rather than as a filter.
    """
    return sorted(
        (
            obj
            for obj in state.objects.values()
            if obj.kind in INTENT_BEARING_SEMANTIC_KINDS
            and _is_current(obj)
            and _object_in_scope(obj, scope)
        ),
        key=lambda o: o.id,
    )


def _known_object(
    obj: SemanticBase, state: IntentState, view: CurrentSemanticView
) -> KnownIntentObject:
    stale_ids = frozenset(view.stale_ids)
    # Only a DERIVED_FROM target that is genuinely a v2 SemanticClaim counts. A legacy
    # object may carry the same relation name pointing at something else entirely, and
    # treating that as a claim id would invent a basis that does not exist.
    basis_claim_ids: list[str] = []
    for relation in obj.relations:
        target = relation.target_id
        if (
            relation.relation_type.value == "DERIVED_FROM"
            and target in state.semantic.claims
            and target not in basis_claim_ids
        ):
            basis_claim_ids.append(target)
    basis_locus_ids = sorted(
        {
            view.representatives.get(
                state.semantic.claims[cid].address_id, state.semantic.claims[cid].address_id
            )
            for cid in basis_claim_ids
        }
    )
    return KnownIntentObject(
        object_id=obj.id,
        kind=obj.kind,
        authority=obj.authority,
        lifecycle=obj.lifecycle,
        is_stale=obj.id in stale_ids,
        scope=tuple(obj.scope),
        statement=_statement_of(obj),
        materiality=obj.materiality if isinstance(obj, Requirement) else None,
        basis_claim_ids=tuple(basis_claim_ids),
        basis_locus_ids=tuple(basis_locus_ids),
    )


def _locus_is_stale(state: IntentState, view: CurrentSemanticView, locus: SemanticLocus) -> bool:
    """Staleness of the locus' CURRENT head — never of anything derived from it.

    This distinction is load-bearing. If a locus counted as stale because some
    downstream object derived from it is stale, then a corrected claim could never be
    offered to the synthesizer, and the stale derived object could never be reconciled.
    Reconciliation would deadlock permanently.
    """
    stale_ids = frozenset(view.stale_ids)
    return any(
        (head := state.semantic.issue_heads.get(address_id)) is not None and head in stale_ids
        for address_id in locus.address_ids
    )


def _blockers_for(
    state: IntentState, view: CurrentSemanticView, locus: SemanticLocus
) -> list[SynthesisContextBlocker]:
    """Every independent reason this locus may not be offered, deterministically ordered.

    Several conditions can hold at once and none is silently discarded: one blocker per
    distinct ``GapKind``, so the record of why a scope could not proceed stays complete.
    """
    found: dict[GapKind, tuple[str, ...]] = {}
    if locus.epistemic_state is IssueEpistemicState.DISPUTED:
        found[GapKind.CONTRADICTION] = tuple(
            sorted({cid for pair in locus.disputed_claim_pairs for cid in pair})
        )
    addresses = frozenset(locus.address_ids)
    pending = [
        judgment_id
        for judgment_id in view.pending_judgment_ids
        if judgment_id in state.semantic.judgments
        and judgment_address_ids(state.semantic, state.semantic.judgments[judgment_id]) & addresses
    ]
    if pending:
        found[GapKind.MISSING_AUTHORITY] = ()
    if _locus_is_stale(state, view, locus):
        found[GapKind.STALE_EVIDENCE] = ()
    undecided = tuple(
        sorted(
            claim_id
            for claim_id in locus.claim_ids
            if state.semantic.claims[claim_id].value.kind is ClaimValueKind.UNDECIDED
        )
    )
    if undecided:
        found[GapKind.MISSING_INFORMATION] = undecided
    return [
        SynthesisContextBlocker(
            locus_representative_id=locus.representative_id,
            gap_kind=gap_kind,
            affected_claim_ids=claims,
        )
        for gap_kind, claims in sorted(found.items(), key=lambda item: item[0].value)
    ]


def _basis_claim(state: IntentState, view: CurrentSemanticView, claim_id: str) -> BasisClaim:
    claim = state.semantic.claims[claim_id]
    effective = tuple(sorted(view.effective_evidence.get(claim_id, claim.evidence_ids)))
    kinds: set[SourceKind] = set()
    for evidence_id in effective:
        item = state.semantic.evidence.get(evidence_id)
        if item is None:
            # Silently dropping it would understate the basis and could hide a
            # research-derived origin.
            raise ValueError(
                f"claim {claim_id!r} cites effective evidence {evidence_id!r}, which is "
                "absent from semantic state"
            )
        kinds.add(item.source_kind)
    return BasisClaim(
        claim_id=claim_id,
        predicate=claim.predicate,
        value=claim.value,
        effective_evidence_ids=effective,
        authority=claim.authority,
        source_kinds=tuple(sorted(kinds, key=lambda k: k.value)),
    )


def compile_intent_synthesis_context(
    state: IntentState,
    *,
    scope: str,
    allowed_target_kinds: frozenset[SemanticKind] | None = None,
) -> IntentSynthesisContext:
    """Compile exactly what a synthesizer may see for ``scope``. Pure; state untouched.

    Deterministic structural selection, not retrieval: nothing is ranked, truncated or
    scored. An over-bound context is refused rather than trimmed to fit, because a
    silently shortened context changes what the model can conclude while looking
    identical.
    """
    view = derive_view(state.semantic)
    in_scope = sorted(
        (locus for locus in view.loci if locus_in_scope(locus, scope)),
        key=lambda locus: locus.representative_id,
    )

    blockers: list[SynthesisContextBlocker] = []
    eligible: list[SemanticLocus] = []
    for locus in in_scope:
        if locus.epistemic_state is IssueEpistemicState.OPEN:
            # Nothing to synthesize, and no gap either (spec §16).
            continue
        found = _blockers_for(state, view, locus)
        if found:
            blockers.extend(found)
            continue
        eligible.append(locus)

    if not eligible:
        return IntentSynthesisContext(request=None, blockers=tuple(blockers))

    basis = tuple(
        LocusBasis(
            locus_representative_id=locus.representative_id,
            address_ids=tuple(sorted(locus.address_ids)),
            subject=state.semantic.addresses[locus.representative_id].subject,
            facet=state.semantic.addresses[locus.representative_id].facet,
            live_claims=tuple(
                _basis_claim(state, view, claim_id) for claim_id in sorted(locus.claim_ids)
            ),
            epistemic_state=locus.epistemic_state,
        )
        for locus in eligible
    )

    # D9: the count is checked BEFORE compiling the snapshot, so an oversized project
    # is refused without first building the thing that would not be sent.
    candidates = _eligible_known_objects(state, scope)
    if len(candidates) > KNOWN_INTENT_OBJECT_THRESHOLD:
        raise ContextUnsupported(
            f"UNSUPPORTED_ABOVE_THRESHOLD: {len(candidates)} in-scope intent objects in scope "
            f"{scope!r} exceed the known-intent threshold of {KNOWN_INTENT_OBJECT_THRESHOLD}"
        )
    known = tuple(_known_object(obj, state, view) for obj in candidates)
    size = known_intent_context_character_count(known)
    if size > MAX_KNOWN_INTENT_CONTEXT_CHARS:
        raise ContextUnsupported(
            f"UNSUPPORTED_KNOWN_INTENT_CONTEXT: the known-intent snapshot renders to {size} "
            f"characters; maximum is {MAX_KNOWN_INTENT_CONTEXT_CHARS}"
        )

    return IntentSynthesisContext(
        request=IntentSynthesisRequest(
            project_id=state.project_id,
            scope=scope,
            basis=basis,
            known_intent_objects=known,
            allowed_target_kinds=allowed_target_kinds
            if allowed_target_kinds is not None
            else frozenset({SemanticKind.REQUIREMENT}),
        ),
        blockers=tuple(blockers),
    )


def validate_intent_synthesis_result(
    *,
    state: IntentState,
    request: IntentSynthesisRequest,
    result: IntentSynthesisResult,
) -> tuple[ValidatedSynthesisProposal, ...]:
    """Check every proposal against THIS request. Whole-result refusal, never repair.

    Mirrors the semantic output philosophy: nothing is dropped, rewritten, fuzzy-matched
    or substituted. One bad proposal refuses the batch, because a result that had to be
    edited to be acceptable is not evidence of what the model actually concluded.

    ``gap_proposals`` are preserved verbatim and given no ids here; turning them into
    durable gaps is T8's.
    """
    claim_to_locus: dict[str, str] = {
        basis_claim.claim_id: locus.locus_representative_id
        for locus in request.basis
        for basis_claim in locus.live_claims
    }
    known_by_id = {known.object_id: known for known in request.known_intent_objects}

    validated: list[ValidatedSynthesisProposal] = []
    for proposal in result.proposals:
        if proposal.target_kind not in request.allowed_target_kinds:
            allowed = sorted(k.value for k in request.allowed_target_kinds)
            raise IntentSynthesisResultError(
                f"proposal {proposal.model_proposal_id!r} targets {proposal.target_kind}, "
                f"which is not among the allowed target kinds {allowed}"
            )
        for claim_id in proposal.basis_claim_ids:
            if claim_id not in claim_to_locus:
                raise IntentSynthesisResultError(
                    f"proposal {proposal.model_proposal_id!r} cites claim {claim_id!r}, which was "
                    "not shown in this request; a proposal may not be grounded in invisible state"
                )
        _validate_disposition(proposal, known_by_id)
        validated.append(
            ValidatedSynthesisProposal(
                proposal=proposal,
                # ONLY the loci of the claims actually cited (C4/I17). Widening this to
                # everything sharing those loci would wire unrelated claims into the
                # blast radius and cause false-positive staleness later.
                basis_locus_ids=tuple(
                    sorted({claim_to_locus[cid] for cid in proposal.basis_claim_ids})
                ),
                target_scope=_target_scope_for(state, proposal.basis_claim_ids),
            )
        )
    return tuple(validated)


def _validate_disposition(
    proposal: RequirementSynthesisProposal, known_by_id: dict[str, KnownIntentObject]
) -> None:
    """The state-dependent half of §9.3, against the EXACT snapshot shown (R1).

    Validated against the snapshot rather than a fresh search, so the decision rests on
    what the model could actually see. Exactly the id proposed: never a stale sibling,
    never "the latest equivalent object".
    """
    if proposal.disposition is IntentDisposition.NEW:
        return
    target_id = proposal.relates_to_object_id
    known = known_by_id.get(target_id or "")
    if known is None:
        raise IntentSynthesisResultError(
            f"proposal {proposal.model_proposal_id!r} names {target_id!r}, which was not in the "
            "known-intent snapshot shown to the synthesizer"
        )
    if proposal.disposition is IntentDisposition.REPLACES_STALE and not known.is_stale:
        raise IntentSynthesisResultError(
            f"REPLACES_STALE names {target_id!r}, which is not stale in this snapshot"
        )
    if proposal.disposition is IntentDisposition.EXISTING_UNCHANGED and known.is_stale:
        raise IntentSynthesisResultError(
            f"EXISTING_UNCHANGED names {target_id!r}, which IS stale in this snapshot; a stale "
            "object must be reconciled, not affirmed as current"
        )


def _target_scope_for(state: IntentState, basis_claim_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Union of the cited claims' ADDRESS scopes (I6). ``()`` stays project-wide.

    Never the request scope: a claim at a project-wide address yields a project-wide
    object even when the request was compiled for one scope, because structural truth is
    runtime-owned rather than inherited from how the question was asked.
    """
    scopes: set[str] = set()
    for claim_id in basis_claim_ids:
        claim = state.semantic.claims.get(claim_id)
        if claim is None:
            raise IntentSynthesisResultError(
                f"cited claim {claim_id!r} is absent from current semantic state"
            )
        address = state.semantic.addresses.get(claim.address_id)
        if address is None:
            raise IntentSynthesisResultError(
                f"cited claim {claim_id!r} references address {claim.address_id!r}, which is "
                "absent from current semantic state"
            )
        scopes.update(address.scope)
    return tuple(sorted(scopes))
