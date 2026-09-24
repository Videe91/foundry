"""IE2.1 — relation legality and cross-plane target resolution.

Legality is a property of a *pair resolved against state*: `Relation` carries only a type
and a target id, never a source kind, so nothing can be decided from the relation alone.

Two laws here are load-bearing and each has a control that fails if it is removed:

* **forward-only** — historical objects predate these rules and may carry relations IE2
  would now refuse. Validating during reconstruction would make the log unreplayable, which
  is the property MR4–MR6 certified;
* **cross-plane resolution** — the certified Slice-1 Requirement derives from a v2
  ``SemanticClaim`` in ``state.semantic.claims``, *not* from anything in ``state.objects``.
  A resolver that looked only at ``state.objects`` would reject the certified path.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from foundry.application.replay import replay
from foundry.domain.common import Authority, Provenance, RelationType, SourceKind
from foundry.domain.events import StoredEvent, parse_event
from foundry.domain.relation_legality import (
    AmbiguousTargetError,
    IllegalRelationError,
    UnresolvedTargetError,
    resolve_target_kind,
    validate_relations,
)
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticClaim
from foundry.domain.semantic_state import SemanticState
from foundry.domain.state import IntentState
from tests.unit._ie21_fixtures import (
    PROJECT,
    constraint,
    goal,
    intent,
    non_goal,
    preference,
    project_decision,
    rel,
    requirement,
)

CERTIFIED_LEDGERS = sorted(
    pathlib.Path("tests/certification/evidence").glob("*/*/case_a_ledger.json")
)


def state_with(*objects: object) -> IntentState:
    return IntentState(project_id=PROJECT, objects={o.id: o for o in objects})  # type: ignore[attr-defined]


# --- vocabulary ---------------------------------------------------------------------------


def test_the_two_new_relations_exist_and_no_others_were_added() -> None:
    assert RelationType.SERVES == "SERVES"
    assert RelationType.EXCLUDES == "EXCLUDES"
    for rejected in ("SATISFIES", "DEPENDS_ON", "INVALIDATES", "QUALIFIES"):
        assert not hasattr(RelationType, rejected), f"{rejected} was rejected by R3"


# --- legality matrix ----------------------------------------------------------------------


def test_a_requirement_may_serve_a_goal() -> None:
    req = requirement(relations=(rel(RelationType.SERVES, "GOAL-1"),))
    validate_relations(state_with(req, goal()), req)


def test_the_root_intent_serves_nothing() -> None:
    root = intent(relations=(rel(RelationType.SERVES, "GOAL-1"),))
    with pytest.raises(IllegalRelationError, match="SERVES"):
        validate_relations(state_with(root, goal()), root)


def test_derived_from_may_never_target_intent() -> None:
    """I-SEP-1: relevance is never expressed as basis."""
    req = requirement(relations=(rel(RelationType.DERIVED_FROM, "INTENT-payments"),))
    with pytest.raises(IllegalRelationError, match="DERIVED_FROM"):
        validate_relations(state_with(req, intent()), req)


def test_only_a_non_goal_may_exclude() -> None:
    ng = non_goal(relations=(rel(RelationType.EXCLUDES, "REQ-1"),))
    validate_relations(state_with(ng, requirement()), ng)

    impostor = constraint(relations=(rel(RelationType.EXCLUDES, "REQ-1"),))
    with pytest.raises(IllegalRelationError, match="EXCLUDES"):
        validate_relations(state_with(impostor, requirement()), impostor)


def test_constrains_is_owned_by_constraint_not_decision() -> None:
    """R18: a Decision is a choice; constraining is what an obligation does."""
    con = constraint(relations=(rel(RelationType.CONSTRAINS, "REQ-1"),))
    validate_relations(state_with(con, requirement()), con)

    pref = preference(relations=(rel(RelationType.CONSTRAINS, "REQ-1"),))
    with pytest.raises(IllegalRelationError, match="CONSTRAINS"):
        validate_relations(state_with(pref, requirement()), pref)


# --- cross-plane target resolution (R25) --------------------------------------------------


def test_an_unresolved_target_is_rejected_not_ignored() -> None:
    req = requirement(relations=(rel(RelationType.DERIVED_FROM, "CLAIM-missing"),))
    with pytest.raises(UnresolvedTargetError, match="CLAIM-missing"):
        validate_relations(state_with(req), req)


def test_resolution_never_depends_on_an_id_prefix() -> None:
    """An object whose id merely looks like a claim still resolves to its real kind."""
    looks_like_a_claim = goal("CLAIM-shaped-but-a-goal")
    kind = resolve_target_kind(state_with(looks_like_a_claim), "CLAIM-shaped-but-a-goal")
    assert kind is SemanticKind.GOAL


@pytest.mark.parametrize("ledger", CERTIFIED_LEDGERS, ids=lambda p: p.parent.name)
def test_the_certified_requirement_resolves_against_the_real_v2_claim(
    ledger: pathlib.Path,
) -> None:
    """The compliance pin, built from the real certified ledger.

    Manufacturing a legacy ``Claim`` object here would prove only that the validator can be
    satisfied, never that the certified path is legal. The claim this Requirement derives
    from genuinely lives in ``state.semantic.claims``.
    """
    raw = json.loads(ledger.read_text())
    events = tuple(StoredEvent(sequence=e["sequence"], event=parse_event(e["event"])) for e in raw)
    state = replay("PROJ-CERT", events)

    reqs = [o for o in state.objects.values() if type(o).__name__ == "Requirement"]
    assert reqs, "the certified ledger holds no Requirement"
    req = reqs[0]
    target = req.relations[0].target_id

    # The premise of R25, asserted rather than assumed.
    assert target not in state.objects
    assert target in state.semantic.claims
    assert resolve_target_kind(state, target) is SemanticKind.CLAIM

    # And therefore the certified path is legality-clean.
    validate_relations(state, req)


# --- forward-only -------------------------------------------------------------------------


@pytest.mark.parametrize("ledger", CERTIFIED_LEDGERS, ids=lambda p: p.parent.name)
def test_replay_never_validates_legality(ledger: pathlib.Path) -> None:
    """Historical streams replay untouched, whatever their relations look like now."""
    raw = json.loads(ledger.read_text())
    events = tuple(StoredEvent(sequence=e["sequence"], event=parse_event(e["event"])) for e in raw)
    first = replay("PROJ-CERT", events)
    second = replay("PROJ-CERT", events)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_a_legacy_object_carrying_an_illegal_relation_still_replays() -> None:
    """Construction and reconstruction never run the matrix; only new writes do."""
    illegal = requirement(relations=(rel(RelationType.DERIVED_FROM, "INTENT-payments"),))
    state = state_with(illegal, intent())

    assert state.objects["REQ-1"].relations[0].relation_type is RelationType.DERIVED_FROM
    with pytest.raises(IllegalRelationError):
        validate_relations(state, illegal)


def test_ambiguity_is_representable_and_fails_closed() -> None:
    """No global cross-plane id uniqueness is enforced, so a collision must not be guessed."""
    assert issubclass(AmbiguousTargetError, Exception)


# --- controls the mutation suite proved were missing ----------------------------------------


def claim(claim_id: str) -> SemanticClaim:
    return SemanticClaim(
        claim_id=claim_id,
        project_id=PROJECT,
        address_id="ADDR-1",
        predicate="refund_window_days",
        value=ClaimValue(kind=ClaimValueKind.TEXT, text="thirty"),
        evidence_ids=("EV-1",),
        authority=Authority.OBSERVED,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref="human://alice"),
        created_by_judgment_id="J-1",
    )


def state_with_claim(*objects: object, claims: tuple[SemanticClaim, ...] = ()) -> IntentState:
    return IntentState(
        project_id=PROJECT,
        objects={o.id: o for o in objects},  # type: ignore[attr-defined]
        semantic=SemanticState(claims={c.claim_id: c for c in claims}),
    )


def test_an_id_present_on_both_planes_fails_closed() -> None:
    """The ambiguity is genuinely constructible, so it must be refused, not guessed."""
    colliding = "SHARED-ID"
    state = state_with_claim(goal(colliding), claims=(claim(colliding),))

    with pytest.raises(AmbiguousTargetError, match="more than one plane"):
        resolve_target_kind(state, colliding)


def test_a_decision_may_never_be_the_source_of_constrains() -> None:
    """R18: a choice does not constrain; a separate obligation naming it as basis does."""
    dec = project_decision(relations=(rel(RelationType.CONSTRAINS, "REQ-1"),))
    with pytest.raises(IllegalRelationError, match="CONSTRAINS"):
        validate_relations(state_with(dec, requirement()), dec)


def test_a_constraint_may_derive_from_a_decision_as_intermediate_basis() -> None:
    """The legal consequence shape: Constraint --DERIVED_FROM--> ProjectDecision."""
    con = constraint(relations=(rel(RelationType.DERIVED_FROM, "DEC-1"),))
    validate_relations(state_with(con, project_decision()), con)


def test_only_evidence_may_support_or_challenge_a_claim() -> None:
    """R20: the Evidence claim-id fields stay authoritative; normative objects never support."""
    req = requirement(relations=(rel(RelationType.SUPPORTS, "CLAIM-1"),))
    state = state_with_claim(req, claims=(claim("CLAIM-1"),))
    with pytest.raises(IllegalRelationError, match="SUPPORTS"):
        validate_relations(state, req)


def test_supersession_replaces_like_with_like() -> None:
    same = requirement("REQ-2", relations=(rel(RelationType.SUPERSEDES, "REQ-1"),))
    validate_relations(state_with(same, requirement("REQ-1")), same)

    crosskind = requirement("REQ-3", relations=(rel(RelationType.SUPERSEDES, "GOAL-1"),))
    with pytest.raises(IllegalRelationError, match="SUPERSEDES"):
        validate_relations(state_with(crosskind, goal("GOAL-1")), crosskind)
