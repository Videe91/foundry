"""9P2 T3: structural comparison-context compiler.

Spec §9, §10, §17, §18; plan §5. ``compile_comparison_context`` follows ONLY explicit
structural edges: the delta item's ``supersedes_evidence_id`` lineage, the current
view's effective-evidence links (immutable claim evidence ∪ ACTIVE ``SUPPORTS_CLAIM``),
claim-to-address placement, and the caller-supplied profile addresses — which are both
the active claim profile set and the hard eligibility boundary for transition touches
(2026-09-12 pre-experiment amendment, Ruling A). It
never reads claim or address wording, never ranks, never truncates, and never labels a
transition as support/correction/conflict/new. Every ledger here is driven through the
real ``SemanticGovernor`` over an ``InMemoryEventStore`` so ids, admissions and
supersessions are the reducer's own.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

import foundry.application.contrastive_context as contrastive_context_module
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.context_errors import ContextUnsupported
from foundry.application.contrastive_context import (
    MAX_COMPARISON_CONTEXT_CHARS,
    comparison_context_character_count,
    comparison_context_json,
    compile_comparison_context,
    contrastive_address_ids,
    historical_evidence_ids,
)
from foundry.application.contrastive_diff import render_unified_diff
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from foundry.ports.semantic_reasoner import (
    ComparisonContext,
    ContextInclusionEdge,
    ContextRelation,
    EvidenceTransitionContext,
)

PROJECT = "PROJ-CC"
T0 = datetime(2026, 9, 12, tzinfo=UTC)
MODEL_A = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")
MODEL_B = ReasonerFingerprint(provider="anthropic", model="claude-opus-5", policy_version="p1")
SCOPE = ("A",)

ADDR_A = address_id_for(PROJECT, "J-cA")
ADDR_B = address_id_for(PROJECT, "J-cB")
ADDR_C = address_id_for(PROJECT, "J-cC")
ADDR_T = address_id_for(PROJECT, "J-cT")
CLAIM_A = claim_id_for(PROJECT, "J-clA")  # ADDR_A, cites EV-A, supported by EV-S (active)
CLAIM_A2 = claim_id_for(PROJECT, "J-clA2")  # ADDR_A, cites EV-B
CLAIM_OLD = claim_id_for(PROJECT, "J-clOld")  # ADDR_A, cites EV-OLD, SUPERSEDED
CLAIM_B = claim_id_for(PROJECT, "J-clB")  # ADDR_B, cites EV-B
CLAIM_B2 = claim_id_for(PROJECT, "J-clB2")  # ADDR_B, cites EV-B
CLAIM_C = claim_id_for(PROJECT, "J-clC")  # ADDR_C, cites EV-C, support by EV-S SUPERSEDED
CLAIM_T = claim_id_for(PROJECT, "J-clT")  # ADDR_T, cites EV-TWIN (same wording as CLAIM_A)

SEMANTIC_LABEL_TOKENS = ("CORRECTION", "SUPPORT", "CONFLICT", "NEW", "SIMILAR", "LIKELY")
STRUCTURAL_RELATIONS = frozenset(
    {
        ContextRelation.SUPERSEDES,
        ContextRelation.EFFECTIVE_EVIDENCE_OF,
        ContextRelation.CLAIM_AT_ADDRESS,
        ContextRelation.ACTIVE_CLAIM_PROFILE,
    }
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- builders ---------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _governor(store: InMemoryEventStore) -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


def _evidence(
    evidence_id: str,
    *,
    artifact_ref: str | None = None,
    supersedes: str | None = None,
    content: str | None = None,
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=content if content is not None else f"Evidence body {evidence_id}.\nSecond line.",
        observed_at=T0,
        scope=SCOPE,
        artifact_ref=artifact_ref,
        supersedes_evidence_id=supersedes,
    )


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    *,
    evidence_id: str,
    reasoner: ReasonerFingerprint = MODEL_A,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _create(judgment_id: str, evidence_id: str) -> SemanticJudgment:
    candidate = SemanticCandidate(
        candidate_id=f"CAND-{judgment_id}",
        subject=f"subject {judgment_id}",
        facet="retention",
        scope=SCOPE,
        evidence_ids=(evidence_id,),
    )
    proposal = CreateAddressProposal(candidate=candidate)
    return _judgment(judgment_id, proposal, evidence_id=evidence_id)


def _claim(judgment_id: str, address_id: str, evidence_id: str, quantity: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="retention_period",
            value=ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit="day"),
            evidence_ids=(evidence_id,),
            authority=Authority.OBSERVED,
        ),
        evidence_id=evidence_id,
    )


def _support(judgment_id: str, claim_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupportsClaimProposal(claim_id=claim_id, evidence_ids=(evidence_id,)),
        evidence_id=evidence_id,
    )


def _apply_supersede(governor: SemanticGovernor, tag: str, target: str, evidence_id: str) -> None:
    """Supersede ``target`` and get it APPLIED via independent corroboration."""
    proposal = SupersedeProposal(target_judgment_id=target, reason="The older record is corrected.")
    first = governor.submit(
        _judgment(f"J-sup-{tag}-a", proposal, evidence_id=evidence_id, reasoner=MODEL_A)
    )
    assert first.route is AdmissionRoute.REQUIRE_SECOND_LENS
    second = governor.submit(
        _judgment(f"J-sup-{tag}-b", proposal, evidence_id=evidence_id, reasoner=MODEL_B)
    )
    assert second.route is AdmissionRoute.APPLY


TWIN_CONTENT = "Retention is seven days.\nSecond line."

EVIDENCE = (
    ("EV-A", "docs/a.md", TWIN_CONTENT),
    ("EV-TWIN", "docs/twin.md", TWIN_CONTENT),  # identical wording, NO lineage edge to EV-A
    ("EV-S", "docs/s.md", None),
    ("EV-OLD", "docs/old.md", None),
    ("EV-B", "docs/b.md", None),
    ("EV-C", "docs/c.md", None),
    ("EV-U", "docs/u.md", None),  # cited by nothing
)
CREATES = (("J-cA", "EV-A"), ("J-cB", "EV-B"), ("J-cC", "EV-C"), ("J-cT", "EV-TWIN"))
CLAIMS = (
    ("J-clA", ADDR_A, "EV-A", "7"),
    ("J-clT", ADDR_T, "EV-TWIN", "7"),  # same predicate/value wording as J-clA
    ("J-clOld", ADDR_A, "EV-OLD", "3"),
    ("J-clA2", ADDR_A, "EV-B", "9"),
    ("J-clB", ADDR_B, "EV-B", "30"),
    ("J-clB2", ADDR_B, "EV-B", "31"),
    ("J-clC", ADDR_C, "EV-C", "14"),
)
SUPPORTS = (("J-sA", CLAIM_A, "EV-S"), ("J-sC", CLAIM_C, "EV-S"))


def _story(*, reverse: bool = False) -> IntentState:
    """One ledger; ``reverse`` flips the insertion order inside every phase."""

    def order[T](items: tuple[T, ...]) -> tuple[T, ...]:
        return tuple(reversed(items)) if reverse else items

    governor = _governor(InMemoryEventStore())
    for evidence_id, artifact, content in order(EVIDENCE):
        governor.ingest(_evidence(evidence_id, artifact_ref=artifact, content=content))
    for judgment_id, evidence_id in order(CREATES):
        assert governor.submit(_create(judgment_id, evidence_id)).route is AdmissionRoute.APPLY
    for judgment_id, address_id, evidence_id, quantity in order(CLAIMS):
        decision = governor.submit(_claim(judgment_id, address_id, evidence_id, quantity))
        assert decision.route is AdmissionRoute.APPLY
    for judgment_id, claim_id, evidence_id in order(SUPPORTS):
        assert governor.submit(_support(judgment_id, claim_id, evidence_id)).route is (
            AdmissionRoute.APPLY
        )
    _apply_supersede(governor, "old", "J-clOld", "EV-A")  # CLAIM_OLD is no longer live
    _apply_supersede(governor, "sC", "J-sC", "EV-C")  # EV-S no longer supports CLAIM_C
    return governor.state()


def _delta(evidence_id: str, *, artifact: str, supersedes: str) -> EvidenceItem:
    return _evidence(
        evidence_id,
        artifact_ref=artifact,
        supersedes=supersedes,
        content=f"Revised body {evidence_id}.\nSecond line.",
    )


def _compile(
    state: IntentState, *delta: EvidenceItem, profile: tuple[str, ...] = ()
) -> ComparisonContext:
    return compile_comparison_context(delta=delta, state=state, profile_address_ids=profile)


def _edge(source: str, relation: ContextRelation, target: str) -> ContextInclusionEdge:
    return ContextInclusionEdge(source_id=source, relation=relation, target_id=target)


def _expected_edges(
    current: str, predecessor: str, touched: tuple[tuple[str, str], ...]
) -> tuple[ContextInclusionEdge, ...]:
    edges = [_edge(current, ContextRelation.SUPERSEDES, predecessor)]
    for claim_id, address_id in touched:
        edges.append(_edge(predecessor, ContextRelation.EFFECTIVE_EVIDENCE_OF, claim_id))
        edges.append(_edge(claim_id, ContextRelation.CLAIM_AT_ADDRESS, address_id))
    return tuple(edges)


# --- fixture sanity ---------------------------------------------------------------


def test_story_liveness_is_the_views_own() -> None:
    view = derive_view(_story().semantic)
    assert CLAIM_OLD not in view.effective_evidence
    assert view.effective_evidence[CLAIM_A] == ("EV-A", "EV-S")
    assert view.effective_evidence[CLAIM_C] == ("EV-C",)
    assert view.effective_evidence[CLAIM_T] == ("EV-TWIN",)


def test_constant_is_locked() -> None:
    assert MAX_COMPARISON_CONTEXT_CHARS == 131_072


# --- structural touch rules -------------------------------------------------------


def test_direct_immutable_claim_evidence_dependency_touches_the_claim() -> None:
    state = _story()
    current = _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A")

    context = _compile(state, current, profile=(ADDR_A,))

    assert len(context.transitions) == 1
    transition = context.transitions[0]
    assert isinstance(transition, EvidenceTransitionContext)
    assert transition.current_evidence_id == "EV-A2"
    assert transition.predecessor_evidence_id == "EV-A"
    assert transition.artifact_ref == "docs/a.md"
    assert transition.touched_claim_ids == (CLAIM_A,)
    assert transition.touched_address_ids == (ADDR_A,)
    predecessor = state.semantic.evidence["EV-A"]
    assert transition.historical_diff == render_unified_diff(predecessor, current)
    assert transition.inclusion_edges == _expected_edges("EV-A2", "EV-A", ((CLAIM_A, ADDR_A),))
    assert context.active_claim_profile_edges == tuple(
        _edge(ADDR_A, ContextRelation.ACTIVE_CLAIM_PROFILE, claim_id)
        for claim_id in sorted((CLAIM_A, CLAIM_A2))
    )


def test_active_supports_claim_dependency_touches_the_claim_and_superseded_support_does_not() -> (
    None
):
    state = _story()
    current = _delta("EV-S2", artifact="docs/s.md", supersedes="EV-S")

    (transition,) = _compile(state, current, profile=(ADDR_A, ADDR_C)).transitions

    # CLAIM_A never cites EV-S directly; it is reached only through the ACTIVE support.
    assert "EV-S" not in state.semantic.claims[CLAIM_A].evidence_ids
    assert transition.touched_claim_ids == (CLAIM_A,)
    assert transition.touched_address_ids == (ADDR_A,)
    # CLAIM_C's support by EV-S was superseded: not reached.
    assert CLAIM_C not in transition.touched_claim_ids
    assert transition.inclusion_edges == _expected_edges("EV-S2", "EV-S", ((CLAIM_A, ADDR_A),))


def test_superseded_claim_is_excluded_and_transition_still_exists() -> None:
    state = _story()
    current = _delta("EV-OLD2", artifact="docs/old.md", supersedes="EV-OLD")

    # ADDR_A is eligible; CLAIM_OLD is excluded only because it is no longer live.
    (transition,) = _compile(state, current, profile=(ADDR_A,)).transitions

    assert state.semantic.claims[CLAIM_OLD].address_id == ADDR_A
    assert state.semantic.claims[CLAIM_OLD].evidence_ids == ("EV-OLD",)
    assert transition.touched_claim_ids == ()
    assert transition.touched_address_ids == ()
    assert transition.inclusion_edges == (_edge("EV-OLD2", ContextRelation.SUPERSEDES, "EV-OLD"),)
    assert transition.historical_diff == render_unified_diff(
        state.semantic.evidence["EV-OLD"], current
    )


def test_unrelated_evidence_and_claims_are_excluded() -> None:
    state = _story()
    current = _delta("EV-U2", artifact="docs/u.md", supersedes="EV-U")

    # Every address is eligible; nothing is touched because no live claim depends on EV-U.
    context = _compile(state, current, profile=(ADDR_A, ADDR_B, ADDR_C, ADDR_T))

    (transition,) = context.transitions
    assert transition.touched_claim_ids == ()
    assert transition.touched_address_ids == ()
    assert transition.inclusion_edges == (_edge("EV-U2", ContextRelation.SUPERSEDES, "EV-U"),)
    assert historical_evidence_ids(context) == ("EV-U",)
    assert contrastive_address_ids(context) == ()


def test_same_wording_without_lineage_edge_does_not_touch() -> None:
    state = _story()
    evidence = state.semantic.evidence
    assert evidence["EV-TWIN"].content == evidence["EV-A"].content
    twin, original = state.semantic.claims[CLAIM_T], state.semantic.claims[CLAIM_A]
    assert (twin.predicate, twin.value) == (original.predicate, original.value)
    current = _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A")

    context = _compile(state, current, profile=(ADDR_A, ADDR_T))

    (transition,) = context.transitions
    assert transition.touched_claim_ids == (CLAIM_A,)  # ADDR_T is eligible, yet untouched
    assert CLAIM_T not in transition.touched_claim_ids
    assert ADDR_T not in transition.touched_address_ids
    assert "EV-TWIN" not in historical_evidence_ids(context)
    assert "EV-TWIN" not in comparison_context_json(context)


def test_delta_item_without_lineage_produces_no_transition() -> None:
    state = _story()
    fresh = _evidence("EV-N", artifact_ref="docs/n.md")

    context = _compile(state, fresh)

    assert context == ComparisonContext()
    assert historical_evidence_ids(context) == ()
    assert contrastive_address_ids(context) == ()


def test_multiple_touched_claims_sort_and_addresses_deduplicate() -> None:
    state = _story()
    current = _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B")

    (transition,) = _compile(state, current, profile=(ADDR_B, ADDR_A)).transitions

    expected_claims = tuple(sorted((CLAIM_A2, CLAIM_B, CLAIM_B2)))
    assert transition.touched_claim_ids == expected_claims
    assert transition.touched_address_ids == tuple(sorted((ADDR_A, ADDR_B)))
    assert len(transition.touched_address_ids) == 2
    claims = state.semantic.claims
    address_of = {claim_id: claims[claim_id].address_id for claim_id in expected_claims}
    assert transition.inclusion_edges == _expected_edges(
        "EV-B2", "EV-B", tuple((claim_id, address_of[claim_id]) for claim_id in expected_claims)
    )


def test_transitions_follow_delta_order_and_skip_items_without_lineage() -> None:
    state = _story()
    b2 = _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B")
    fresh = _evidence("EV-N", artifact_ref="docs/n.md")
    a2 = _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A")

    context = _compile(state, b2, fresh, a2, profile=(ADDR_A, ADDR_B))

    assert tuple(t.current_evidence_id for t in context.transitions) == ("EV-B2", "EV-A2")
    assert historical_evidence_ids(context) == ("EV-A", "EV-B")
    assert contrastive_address_ids(context) == tuple(sorted((ADDR_A, ADDR_B)))


# --- active claim profile edges ---------------------------------------------------


def test_profile_edges_include_only_live_claims_at_supplied_addresses() -> None:
    state = _story()
    current = _delta("EV-U2", artifact="docs/u.md", supersedes="EV-U")

    context = _compile(state, current, profile=(ADDR_C, ADDR_A))

    expected = tuple(
        _edge(address_id, ContextRelation.ACTIVE_CLAIM_PROFILE, claim_id)
        for address_id, claim_id in sorted(
            ((ADDR_A, CLAIM_A), (ADDR_A, CLAIM_A2), (ADDR_C, CLAIM_C))
        )
    )
    assert context.active_claim_profile_edges == expected
    targets = {edge.target_id for edge in context.active_claim_profile_edges}
    assert CLAIM_OLD not in targets  # superseded claim at ADDR_A is not live
    assert CLAIM_B not in targets and CLAIM_T not in targets  # addresses not supplied
    # Profile addresses are not "touched" addresses and do not widen the transition.
    assert contrastive_address_ids(context) == ()
    (transition,) = context.transitions
    assert transition.touched_claim_ids == ()


def test_no_profile_addresses_means_no_profile_edges() -> None:
    state = _story()
    context = _compile(state, _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"))
    assert context.active_claim_profile_edges == ()


# --- structural-only edges and helpers --------------------------------------------


def test_edges_are_exactly_structural_and_carry_no_semantic_classification() -> None:
    state = _story()
    context = _compile(
        state,
        _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"),
        _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B"),
        profile=(ADDR_A,),
    )

    relations = {edge.relation for t in context.transitions for edge in t.inclusion_edges}
    relations |= {edge.relation for edge in context.active_claim_profile_edges}
    assert relations <= STRUCTURAL_RELATIONS
    assert relations == STRUCTURAL_RELATIONS
    assert set(EvidenceTransitionContext.model_fields) == {
        "current_evidence_id",
        "predecessor_evidence_id",
        "artifact_ref",
        "historical_diff",
        "touched_claim_ids",
        "touched_address_ids",
        "inclusion_edges",
    }
    rendered = comparison_context_json(context)
    for token in SEMANTIC_LABEL_TOKENS:
        assert token not in rendered


def test_historical_evidence_ids_returns_predecessor_ids_only_sorted_deduped() -> None:
    state = _story()
    context = _compile(
        state,
        _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B"),
        _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"),
        profile=(ADDR_C,),
    )

    assert historical_evidence_ids(context) == ("EV-A", "EV-B")
    # not current ids, not claim-cited evidence, not profile material
    assert not {"EV-A2", "EV-B2", "EV-S", "EV-C"} & set(historical_evidence_ids(context))


def test_contrastive_address_ids_returns_touched_addresses_only() -> None:
    state = _story()
    context = _compile(
        state,
        _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"),
        _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B"),
        profile=(ADDR_A, ADDR_B, ADDR_C, ADDR_T),
    )

    # ADDR_C and ADDR_T are eligible (in the profile) but structurally untouched.
    assert contrastive_address_ids(context) == tuple(sorted((ADDR_A, ADDR_B)))


def test_canonical_json_and_character_count() -> None:
    state = _story()
    context = _compile(state, _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"))

    rendered = comparison_context_json(context)
    assert rendered == json.dumps(
        context.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert comparison_context_character_count(context) == len(rendered)
    again = _compile(state, _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"))
    assert comparison_context_json(again) == rendered


# --- failure behaviour ------------------------------------------------------------


def test_missing_predecessor_raises_value_error_without_search() -> None:
    state = _story()
    orphan = _delta("EV-Z2", artifact="docs/a.md", supersedes="EV-Z")
    assert "EV-Z" not in state.semantic.evidence

    with pytest.raises(ValueError, match="EV-Z"):
        _compile(state, orphan)


def test_artifact_ref_mismatch_raises_value_error() -> None:
    state = _story()
    mismatched = _delta("EV-A2", artifact="docs/elsewhere.md", supersedes="EV-A")

    with pytest.raises(ValueError, match="artifact_ref"):
        _compile(state, mismatched)


def _install_fixed_diff(monkeypatch: pytest.MonkeyPatch, rendered: str) -> None:
    def fake_render(predecessor: EvidenceItem, current: EvidenceItem) -> str:
        return rendered

    monkeypatch.setattr(contrastive_context_module, "render_unified_diff", fake_render)


def _boundary_filler_length(monkeypatch: pytest.MonkeyPatch, state: IntentState) -> int:
    _install_fixed_diff(monkeypatch, "")
    base = comparison_context_character_count(
        _compile(state, _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"))
    )
    return MAX_COMPARISON_CONTEXT_CHARS - base


def test_exactly_max_chars_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _story()
    filler = "x" * _boundary_filler_length(monkeypatch, state)
    _install_fixed_diff(monkeypatch, filler)

    context = _compile(state, _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"))

    assert comparison_context_character_count(context) == 131_072
    assert context.transitions[0].historical_diff == filler


def test_one_char_over_max_is_refused_with_no_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _story()
    filler = "x" * (_boundary_filler_length(monkeypatch, state) + 1)
    _install_fixed_diff(monkeypatch, filler)

    with pytest.raises(ContextUnsupported, match=r"^UNSUPPORTED_COMPARISON_CONTEXT") as info:
        _compile(state, _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"))

    assert "131073" in str(info.value) or "131,073" in str(info.value)
    assert "131072" in str(info.value) or "131,072" in str(info.value)
    assert issubclass(ContextUnsupported, RuntimeError)


def test_bound_counts_unicode_characters_not_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _story()
    filler = "é" * _boundary_filler_length(monkeypatch, state)  # 2 UTF-8 bytes per character
    _install_fixed_diff(monkeypatch, filler)

    context = _compile(state, _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"))

    assert comparison_context_character_count(context) == 131_072
    assert len(comparison_context_json(context).encode("utf-8")) > 131_072


# --- determinism ------------------------------------------------------------------


def test_mapping_insertion_order_does_not_alter_output() -> None:
    forward, backward = _story(), _story(reverse=True)
    assert tuple(forward.semantic.evidence) != tuple(backward.semantic.evidence)
    assert tuple(forward.semantic.claims) != tuple(backward.semantic.claims)
    delta = (
        _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B"),
        _delta("EV-S2", artifact="docs/s.md", supersedes="EV-S"),
    )
    profile = (ADDR_C, ADDR_A)

    first = compile_comparison_context(delta=delta, state=forward, profile_address_ids=profile)
    second = compile_comparison_context(delta=delta, state=backward, profile_address_ids=profile)

    assert first == second
    assert comparison_context_json(first) == comparison_context_json(second)
    assert (
        compile_comparison_context(delta=delta, state=forward, profile_address_ids=(ADDR_A, ADDR_C))
        == first
    )


# --- eligibility boundary (2026-09-12 pre-experiment amendment, Ruling A) ----------


def test_transition_touches_only_claims_at_profile_addresses() -> None:
    """EV-B is effective evidence of live CLAIM_A2 (at ADDR_A) and of live CLAIM_B and
    CLAIM_B2 (at ADDR_B). ``profile_address_ids`` is the hard eligibility boundary for
    transition touches: with ``(ADDR_A,)`` only the ADDR_A claim is touched, and no
    CLAIM_B / CLAIM_B2 / ADDR_B id or edge is emitted anywhere in the context.
    """
    state = _story()
    view = derive_view(state.semantic)
    assert "EV-B" in view.effective_evidence[CLAIM_A2]
    assert "EV-B" in view.effective_evidence[CLAIM_B]
    assert "EV-B" in view.effective_evidence[CLAIM_B2]
    current = _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B")

    context = _compile(state, current, profile=(ADDR_A,))

    (transition,) = context.transitions
    assert transition.touched_claim_ids == (CLAIM_A2,)
    assert transition.touched_address_ids == (ADDR_A,)
    assert transition.inclusion_edges == (
        _edge("EV-B2", ContextRelation.SUPERSEDES, "EV-B"),
        _edge("EV-B", ContextRelation.EFFECTIVE_EVIDENCE_OF, CLAIM_A2),
        _edge(CLAIM_A2, ContextRelation.CLAIM_AT_ADDRESS, ADDR_A),
    )
    assert contrastive_address_ids(context) == (ADDR_A,)
    rendered = comparison_context_json(context)
    for out_of_profile_id in (CLAIM_B, CLAIM_B2, ADDR_B):
        assert out_of_profile_id not in rendered
    # Eligibility narrows the touched set only; the lineage and its diff are unchanged.
    assert transition.historical_diff == render_unified_diff(
        state.semantic.evidence["EV-B"], current
    )


def test_empty_profile_keeps_the_lineage_transition_with_zero_touches() -> None:
    state = _story()
    current = _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B")

    context = _compile(state, current, profile=())

    (transition,) = context.transitions
    assert transition.touched_claim_ids == ()
    assert transition.touched_address_ids == ()
    assert transition.inclusion_edges == (_edge("EV-B2", ContextRelation.SUPERSEDES, "EV-B"),)
    assert transition.historical_diff == render_unified_diff(
        state.semantic.evidence["EV-B"], current
    )
    assert historical_evidence_ids(context) == ("EV-B",)
    assert contrastive_address_ids(context) == ()


def test_contrastive_address_ids_are_always_a_subset_of_the_profile() -> None:
    state = _story()
    delta = (
        _delta("EV-A2", artifact="docs/a.md", supersedes="EV-A"),
        _delta("EV-B2", artifact="docs/b.md", supersedes="EV-B"),
    )
    expected = {
        (ADDR_A,): (ADDR_A,),
        (ADDR_B,): (ADDR_B,),
        (ADDR_A, ADDR_B): tuple(sorted((ADDR_A, ADDR_B))),
        (ADDR_C,): (),
        (): (),
    }
    for profile, touched in expected.items():
        context = compile_comparison_context(delta=delta, state=state, profile_address_ids=profile)
        assert contrastive_address_ids(context) == touched
        assert set(contrastive_address_ids(context)) <= set(profile)
