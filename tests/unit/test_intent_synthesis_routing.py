"""T6 — governed Intent Synthesis routing.

Pure domain: no I/O, no clock, no provider, no EventStore, no state mutation, no
semantic-view derivation, and no reuse of ``route_judgment``.

The rule order is load-bearing and is asserted throughout:

  1. structural identity          (project, model id agreement)
  2. authorship / origin          (I22 — origin follows the AUTHOR, never the basis)
  3. Slice-1 fences               (no DETERMINISTIC_NORMALIZATION, LOW only, pinned policy)
  4. EXISTING_UNCHANGED           → NO_CHANGE, before any authority lookup
  5. authority assignment         (HUMAN_STATED → CANONICAL or AUTHORITY_UNRESOLVED;
                                   AI/RESEARCH → PROPOSED)
  6. anti-invention backstop      (C17/I2 — FIRST rule of the internal stage)
  7. C11 canonical replacement
  8. HUMAN_AUTHORITY / LOW_RISK
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foundry.domain.authority import covering_authority_record
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    SourceKind,
)
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisPolicy,
    IntentSynthesisRoute,
    IntentSynthesisRoutingOutcome,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
    _route_with_assigned_authority,  # the C17 backstop, exercised directly
    route_intent_synthesis,
)
from foundry.domain.semantic import AuthorityRecord, Requirement
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.state import IntentState

PROJECT = "PROJ-A"
ACTOR = "human://alice"
CREATED_AT = datetime(2026, 9, 23, tzinfo=UTC)
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref=ACTOR)
SCOPE = ("keyring",)

HUMAN = ReasonerFingerprint(provider="human", model=ACTOR, policy_version="v1")
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v1")

SLICE_1_POLICY = IntentSynthesisPolicy()


def _identity(tag: str = "p1", project_id: str = PROJECT) -> SynthesisIdentity:
    return SynthesisIdentity(project_id=project_id, synthesis_run_id="RUN-1", model_proposal_id=tag)


def _proposal(
    tag: str = "p1",
    *,
    disposition: IntentDisposition = IntentDisposition.NEW,
    relates_to_object_id: str | None = None,
    confidence: float | None = None,
) -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=tag,
        disposition=disposition,
        statement="Revocation is immediate.",
        rationale="r",
        basis_claim_ids=("CLAIM-1",),
        relates_to_object_id=relates_to_object_id,
        confidence=confidence,
    )


def _authority_record(
    *, object_id: str = "AUTH-1", scope: tuple[str, ...] = SCOPE
) -> AuthorityRecord:
    return AuthorityRecord(
        id=object_id,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=CREATED_AT,
        scope=scope,
        subject_id="SUBJ-1",
        authorized_by=ACTOR,
        rationale="because",
    )


def _target(
    *, object_id: str = "REQ-old", authority: Authority = Authority.CANONICAL
) -> Requirement:
    return Requirement(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=CREATED_AT,
        scope=SCOPE,
        lifecycle=LifecycleStatus.ACTIVE,
        statement="The older commitment.",
        materiality=Materiality.LOW,
        requires_metric=False,
        requires_verification=False,
    )


def _state(*objects: AuthorityRecord | Requirement) -> IntentState:
    return IntentState(project_id=PROJECT, objects={o.id: o for o in objects})


def _route(
    *objects: AuthorityRecord | Requirement,
    identity: SynthesisIdentity | None = None,
    proposal: RequirementSynthesisProposal | None = None,
    author: ReasonerFingerprint = HUMAN,
    origin: SynthesisOrigin = SynthesisOrigin.HUMAN_STATED,
    human_actor_id: str | None = ACTOR,
    target_scope: tuple[str, ...] = SCOPE,
    materiality: Materiality = Materiality.LOW,
    policy: IntentSynthesisPolicy = SLICE_1_POLICY,
    state: IntentState | None = None,
) -> IntentSynthesisRoutingOutcome:
    ident = identity or _identity()
    return route_intent_synthesis(
        state if state is not None else _state(*objects),
        identity=ident,
        proposal=proposal or _proposal(ident.model_proposal_id),
        author=author,
        origin=origin,
        human_actor_id=human_actor_id,
        target_scope=target_scope,
        materiality=materiality,
        policy=policy,
    )


def _ai(*objects: AuthorityRecord | Requirement, **kwargs: object) -> IntentSynthesisRoutingOutcome:
    kwargs.setdefault("author", MODEL)
    kwargs.setdefault("origin", SynthesisOrigin.AI_INFERRED)
    kwargs.setdefault("human_actor_id", None)
    return _route(*objects, **kwargs)  # type: ignore[arg-type]


# --- structural identity ----------------------------------------------------------------


def test_the_decision_always_names_the_identity_proposal_instance() -> None:
    ident = _identity()
    outcome = _route(_authority_record(), identity=ident)
    assert outcome.decision.proposal_instance_id == ident.proposal_instance_id


def test_an_identity_from_another_project_fails_structurally() -> None:
    with pytest.raises(ValueError, match="project"):
        _route(_authority_record(), identity=_identity(project_id="PROJ-OTHER"))


def test_a_proposal_body_from_another_proposal_fails_structurally() -> None:
    """A routing call may not pair one body with another identity."""
    with pytest.raises(ValueError, match="model_proposal_id"):
        _route(_authority_record(), identity=_identity("p1"), proposal=_proposal("p2"))


# --- authorship / origin (I22) ------------------------------------------------------------


def test_human_stated_requires_a_human_author_and_a_matching_actor_id() -> None:
    outcome = _route(_authority_record())
    assert outcome.assigned_authority is Authority.CANONICAL


@pytest.mark.parametrize(
    ("author", "origin", "human_actor_id", "label"),
    [
        (MODEL, SynthesisOrigin.HUMAN_STATED, ACTOR, "non-human author + HUMAN_STATED"),
        (HUMAN, SynthesisOrigin.AI_INFERRED, None, "human author + AI_INFERRED"),
        (HUMAN, SynthesisOrigin.RESEARCH_DERIVED, None, "human author + RESEARCH_DERIVED"),
        (HUMAN, SynthesisOrigin.HUMAN_STATED, None, "human author, no actor id"),
        (HUMAN, SynthesisOrigin.HUMAN_STATED, "human://bob", "actor id mismatch"),
        (MODEL, SynthesisOrigin.AI_INFERRED, ACTOR, "non-human author given an actor id"),
    ],
)
def test_every_invalid_authorship_combination_fails_structurally(
    author: ReasonerFingerprint,
    origin: SynthesisOrigin,
    human_actor_id: str | None,
    label: str,
) -> None:
    """Never silently downgraded: a malformed combination is not a governance route."""
    with pytest.raises(ValueError):
        _route(_authority_record(), author=author, origin=origin, human_actor_id=human_actor_id)


def test_research_derived_has_the_same_authorship_shape_as_ai_inferred() -> None:
    outcome = _ai(origin=SynthesisOrigin.RESEARCH_DERIVED)
    assert outcome.assigned_authority is Authority.PROPOSED


# --- Slice-1 fences -----------------------------------------------------------------------


def test_deterministic_normalization_fails_closed_as_unsupported() -> None:
    """§11 defines the fence but builds nothing under it in Slice 1."""
    with pytest.raises(ValueError, match="DETERMINISTIC_NORMALIZATION"):
        _route(
            _authority_record(),
            author=HUMAN,
            origin=SynthesisOrigin.DETERMINISTIC_NORMALIZATION,
            human_actor_id=ACTOR,
        )


@pytest.mark.parametrize(
    "materiality", [Materiality.MEDIUM, Materiality.HIGH, Materiality.CRITICAL]
)
def test_non_low_materiality_fails_closed(materiality: Materiality) -> None:
    """D4 stays a genuine expansion gate rather than silently activating."""
    with pytest.raises(ValueError, match="materiality"):
        _route(_authority_record(), materiality=materiality)


@pytest.mark.parametrize(
    "policy",
    [
        IntentSynthesisPolicy(
            material_target_kinds=frozenset(
                {
                    __import__(
                        "foundry.domain.semantic", fromlist=["SemanticKind"]
                    ).SemanticKind.REQUIREMENT
                }
            )
        ),
        IntentSynthesisPolicy(material_materiality_levels=frozenset({Materiality.LOW})),
        IntentSynthesisPolicy(canonical_requires_authority=False),
    ],
    ids=["material kinds", "material levels", "authority not required"],
)
def test_a_policy_wider_than_slice_one_fails_closed(policy: IntentSynthesisPolicy) -> None:
    """D3 stays a genuine expansion gate; no corroboration algorithm is guessed."""
    with pytest.raises(ValueError, match="policy|Slice"):
        _route(_authority_record(), policy=policy)


# --- EXISTING_UNCHANGED (I18) --------------------------------------------------------------


def test_existing_unchanged_is_a_successful_no_change() -> None:
    outcome = _route(
        proposal=_proposal(
            disposition=IntentDisposition.EXISTING_UNCHANGED, relates_to_object_id="REQ-existing"
        ),
        state=_state(),
    )
    assert outcome.assigned_authority is None
    assert outcome.decision.route is IntentSynthesisRoute.NO_CHANGE
    assert outcome.decision.reasons == ("EXISTING_UNCHANGED",)


def test_no_change_never_consults_authority_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """No object is written, so no AuthorityRecord is needed to decide it."""
    import foundry.domain.intent_synthesis as module

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("authority coverage must not be consulted for NO_CHANGE")

    monkeypatch.setattr(module, "covering_authority_record", _explode)
    outcome = _route(
        proposal=_proposal(
            disposition=IntentDisposition.EXISTING_UNCHANGED, relates_to_object_id="REQ-existing"
        ),
        state=_state(),
    )
    assert outcome.decision.route is IntentSynthesisRoute.NO_CHANGE


# --- authority assignment --------------------------------------------------------------------


def test_human_stated_with_a_covering_record_is_canonical_and_applies() -> None:
    outcome = _route(_authority_record())
    assert outcome.assigned_authority is Authority.CANONICAL
    assert outcome.decision.route is IntentSynthesisRoute.APPLY
    assert outcome.decision.reasons == ("HUMAN_AUTHORITY",)


def test_human_stated_without_a_covering_record_is_authority_unresolved() -> None:
    outcome = _route(state=_state())
    assert outcome.assigned_authority is None
    assert outcome.decision.route is IntentSynthesisRoute.REQUIRE_HUMAN
    assert outcome.decision.reasons == ("AUTHORITY_UNRESOLVED",)


def test_a_record_that_does_not_cover_the_target_scope_does_not_authorize() -> None:
    outcome = _route(_authority_record(scope=("relay",)))
    assert outcome.decision.reasons == ("AUTHORITY_UNRESOLVED",)


def test_ai_inferred_is_proposed_and_low_risk() -> None:
    outcome = _ai()
    assert outcome.assigned_authority is Authority.PROPOSED
    assert outcome.decision.route is IntentSynthesisRoute.APPLY
    assert outcome.decision.reasons == ("LOW_RISK",)


def test_research_derived_is_never_privileged_over_ai_inferred() -> None:
    ai = _ai()
    research = _ai(origin=SynthesisOrigin.RESEARCH_DERIVED)
    assert research.assigned_authority == ai.assigned_authority
    assert research.decision.route is ai.decision.route
    assert research.decision.reasons == ai.decision.reasons


# --- C17 / I2: anti-invention is an independent backstop ---------------------------------------


def test_the_proposal_schema_still_cannot_express_authority() -> None:
    forbidden = {"authority", "assigned_authority", "author", "origin"}
    assert not forbidden & set(RequirementSynthesisProposal.model_fields)


def test_an_internally_mis_assigned_canonical_is_rejected_before_low_risk() -> None:
    """Simulates a runtime-assignment bug: the guard must fail closed, not fall through."""
    ident = _identity()
    decision = _route_with_assigned_authority(
        _state(),
        identity=ident,
        proposal=_proposal(),
        origin=SynthesisOrigin.AI_INFERRED,
        assigned_authority=Authority.CANONICAL,
    )
    assert decision.route is IntentSynthesisRoute.REJECT
    assert decision.reasons == ("AUTHORITY_INVENTION",)
    assert decision.proposal_instance_id == ident.proposal_instance_id


def test_deterministic_normalization_is_not_an_exception_to_anti_invention() -> None:
    decision = _route_with_assigned_authority(
        _state(),
        identity=_identity(),
        proposal=_proposal(),
        origin=SynthesisOrigin.DETERMINISTIC_NORMALIZATION,
        assigned_authority=Authority.CANONICAL,
    )
    assert decision.route is IntentSynthesisRoute.REJECT
    assert decision.reasons == ("AUTHORITY_INVENTION",)


# --- I22 anti-laundering (load-bearing) ---------------------------------------------------------


def test_a_canonical_human_basis_never_elevates_a_model_written_statement() -> None:
    """Origin follows the AUTHOR, never the basis. Routing must not read basis authority."""
    canonical_human_record = _authority_record()
    outcome = _ai(canonical_human_record)
    assert outcome.assigned_authority is Authority.PROPOSED
    assert outcome.assigned_authority is not Authority.CANONICAL
    assert outcome.decision.route is IntentSynthesisRoute.APPLY
    assert outcome.decision.reasons == ("LOW_RISK",)


# --- C11 / I23 replacement safeguard --------------------------------------------------------------


def _replacement(tag: str = "p1", target_id: str = "REQ-old") -> RequirementSynthesisProposal:
    return _proposal(
        tag, disposition=IntentDisposition.REPLACES_STALE, relates_to_object_id=target_id
    )


def test_a_canonical_target_with_a_proposed_replacement_requires_a_human() -> None:
    target = _target(authority=Authority.CANONICAL)
    outcome = _ai(target, proposal=_replacement())
    assert outcome.assigned_authority is Authority.PROPOSED
    assert outcome.decision.route is IntentSynthesisRoute.REQUIRE_HUMAN
    assert outcome.decision.reasons == ("CANONICAL_REPLACEMENT_REQUIRED",)


def test_a_canonical_target_with_an_authorized_canonical_replacement_applies() -> None:
    outcome = _route(
        _authority_record(), _target(authority=Authority.CANONICAL), proposal=_replacement()
    )
    assert outcome.assigned_authority is Authority.CANONICAL
    assert outcome.decision.route is IntentSynthesisRoute.APPLY
    assert outcome.decision.reasons == ("HUMAN_AUTHORITY",)


def test_a_non_canonical_target_with_a_proposed_replacement_applies_ordinarily() -> None:
    outcome = _ai(_target(authority=Authority.PROPOSED), proposal=_replacement())
    assert outcome.assigned_authority is Authority.PROPOSED
    assert outcome.decision.route is IntentSynthesisRoute.APPLY
    assert outcome.decision.reasons == ("LOW_RISK",)


def test_a_missing_replacement_target_fails_structurally() -> None:
    with pytest.raises(ValueError, match="REQ-old"):
        _ai(proposal=_replacement())


def test_authority_unresolved_takes_precedence_over_the_replacement_rule() -> None:
    """Not having established authority for the scope is the more fundamental failure."""
    outcome = _route(_target(authority=Authority.CANONICAL), proposal=_replacement())
    assert outcome.decision.route is IntentSynthesisRoute.REQUIRE_HUMAN
    assert outcome.decision.reasons == ("AUTHORITY_UNRESOLVED",)


# --- reason vocabulary ------------------------------------------------------------------------- --


def test_only_the_pinned_reason_strings_are_emitted() -> None:
    """These persist in INTENT_SYNTHESIS_DECIDED, so spelling is part of the contract."""
    allowed = {
        "EXISTING_UNCHANGED",
        "AUTHORITY_INVENTION",
        "AUTHORITY_UNRESOLVED",
        "CANONICAL_REPLACEMENT_REQUIRED",
        "HUMAN_AUTHORITY",
        "LOW_RISK",
    }
    outcomes = [
        _route(_authority_record()),
        _route(state=_state()),
        _ai(),
        _ai(_target(), proposal=_replacement()),
        _route(
            proposal=_proposal(
                disposition=IntentDisposition.EXISTING_UNCHANGED,
                relates_to_object_id="REQ-x",
            ),
            state=_state(),
        ),
    ]
    for outcome in outcomes:
        assert set(outcome.decision.reasons) <= allowed


# --- confidence blindness ---------------------------------------------------------------------- --


@pytest.mark.parametrize("confidence", [None, 0.0, 1.0])
def test_confidence_never_changes_routing(confidence: float | None) -> None:
    outcome = _ai(proposal=_proposal(confidence=confidence))
    assert outcome.assigned_authority is Authority.PROPOSED
    assert outcome.decision.route is IntentSynthesisRoute.APPLY
    assert outcome.decision.reasons == ("LOW_RISK",)


def test_routing_source_never_reads_confidence() -> None:
    """No routing rule reads it; a threshold would be an unreviewable judgement."""
    tree = ast.parse(Path("src/foundry/domain/intent_synthesis.py").read_text(encoding="utf-8"))
    routing = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and ("route" in node.name or "authority" in node.name)
    ]
    assert routing, "routing functions not found"
    for func in routing:
        for node in ast.walk(func):
            assert not (isinstance(node, ast.Attribute) and node.attr == "confidence")


# --- purity and determinism -------------------------------------------------------------------- --


def test_routing_is_deterministic_and_leaves_state_untouched() -> None:
    state = _state(_authority_record())
    before = state.model_dump(mode="json")
    first = _route(state=state)
    second = _route(state=state)
    assert first == second
    assert state.model_dump(mode="json") == before


def test_the_outcome_is_frozen() -> None:
    from pydantic import ValidationError

    outcome = _route(_authority_record())
    with pytest.raises(ValidationError):
        outcome.assigned_authority = Authority.PROPOSED


# --- dependency boundary ----------------------------------------------------------------------- --


def test_routing_uses_the_shared_authority_law_and_never_admission() -> None:
    source = Path("src/foundry/domain/intent_synthesis.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "foundry.domain.authority" in modules
    assert "foundry.domain.admission" not in modules
    for module in modules:
        for forbidden in ("foundry.application", "foundry.adapters", "foundry.ports"):
            assert not module.startswith(forbidden)
    assert covering_authority_record.__module__ == "foundry.domain.authority"
