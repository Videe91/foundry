"""IE2.1 — the governed admission seam: atomicity, authorship, creation-not-overwrite.

Three laws, each with the failure it exists to prevent:

* **one durable transition** — `EventStore` exposes only `append(event, expected_sequence)`
  and each adapter commits per call, so a seam that appended the object and then recorded
  its edges would be N+1 transitions with a crash window between them;
* **authorship is explicit** — a model may reason and propose, and canonicalize nothing.
  Authority is granted by a human who holds it, recorded where anyone can audit it;
* **admission creates** — the shared reducer case assigns straight into the object mapping,
  which for an admission would be revision by dictionary assignment.
"""

from __future__ import annotations

from itertools import count

import pytest
from pydantic import ValidationError

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, Provenance, RelationType, SourceKind
from foundry.domain.events import (
    SPECIALIZED_SEMANTIC_KIND_BY_EVENT,
    EventEnvelope,
    EventType,
    IntentObjectAdmissionPayload,
    SemanticObjectPayload,
)
from foundry.domain.relation_legality import IllegalRelationError
from foundry.domain.semantic import Claim, ConstraintFacet, SemanticKind, SemanticObject
from tests.unit._ie21_fixtures import (
    ALICE,
    AT,
    HUMAN,
    HUMAN_PROV,
    MODEL,
    PROJECT,
    SYSTEM_PROV,
    authority_record,
    constraint,
    goal,
    intent,
    non_goal,
    rel,
    requirement,
)

_IDS = count(1)


def governor() -> SemanticGovernor:
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: AT,
        id_factory=lambda prefix: f"{prefix}-{next(_IDS)}",
    )


def events_of(gov: SemanticGovernor) -> list[str]:
    return [s.event.event_type.value for s in gov._store.load(PROJECT)]  # noqa: SLF001


def seed(gov: SemanticGovernor, *objects: SemanticObject) -> None:
    """Place objects in state without going through the seam under test.

    Appends the ordinary generic object event directly, so the seam's own laws are never
    exercised while arranging a fixture.
    """
    store = gov._store  # noqa: SLF001
    specialized = {kind: ev for ev, kind in SPECIALIZED_SEMANTIC_KIND_BY_EVENT.items()}
    for obj in objects:
        store.append(
            EventEnvelope(
                event_id=f"EVT-seed-{obj.id}",
                project_id=PROJECT,
                event_type=specialized.get(obj.kind, EventType.SEMANTIC_OBJECT_RECORDED),
                occurred_at=AT,
                payload=SemanticObjectPayload(object=obj),
            ),
            expected_sequence=store.current_sequence(PROJECT),
        )


# --- atomicity (R23) ----------------------------------------------------------------------


def test_an_object_with_two_basis_relations_is_one_durable_append() -> None:
    gov = governor()
    seed(gov, goal("GOAL-1"), goal("GOAL-2"))
    obj = requirement(
        relations=(
            rel(RelationType.DERIVED_FROM, "GOAL-1"),
            rel(RelationType.DERIVED_FROM, "GOAL-2"),
        )
    )
    before = len(gov._store.load(PROJECT))  # noqa: SLF001
    gov.record_intent_object(obj, author=MODEL)

    appended = events_of(gov)[before:]
    assert appended == ["INTENT_OBJECT_ADMITTED"], "exactly one event, never three"
    assert "DERIVATION_RECORDED" not in appended


def test_replay_reconstructs_the_object_and_exactly_its_edges() -> None:
    gov = governor()
    seed(gov, goal("GOAL-1"), goal("GOAL-2"))
    obj = requirement(
        relations=(
            rel(RelationType.DERIVED_FROM, "GOAL-1"),
            rel(RelationType.DERIVED_FROM, "GOAL-2"),
        )
    )
    gov.record_intent_object(obj, author=MODEL)

    state = replay(PROJECT, gov._store.load(PROJECT))  # noqa: SLF001
    assert state.objects["REQ-1"].id == "REQ-1"
    parents = sorted(e.parent_id for e in state.semantic.derivations if e.child_id == "REQ-1")
    assert parents == ["GOAL-1", "GOAL-2"], "no more, no fewer"


def test_the_payload_parents_equal_the_derived_from_targets() -> None:
    """I-DERIV-1, checked at write time and frozen into the event."""
    gov = governor()
    seed(gov, goal("GOAL-1"))
    obj = requirement(
        relations=(
            rel(RelationType.DERIVED_FROM, "GOAL-1"),
            rel(RelationType.SERVES, "GOAL-1"),
        )
    )
    gov.record_intent_object(obj, author=MODEL)

    payload = gov._store.load(PROJECT)[-1].event.payload  # noqa: SLF001
    assert isinstance(payload, IntentObjectAdmissionPayload)
    assert payload.derivation_parent_ids == ("GOAL-1",), "SERVES is relevance, not basis"


def test_a_refused_admission_leaves_the_ledger_byte_identical() -> None:
    gov = governor()
    seed(gov, intent())
    before = [s.event.model_dump(mode="json") for s in gov._store.load(PROJECT)]  # noqa: SLF001

    illegal = requirement(relations=(rel(RelationType.DERIVED_FROM, "INTENT-payments"),))
    with pytest.raises(IllegalRelationError):
        gov.record_intent_object(illegal, author=MODEL)

    after = [s.event.model_dump(mode="json") for s in gov._store.load(PROJECT)]  # noqa: SLF001
    assert after == before, "neither object nor edges may survive a refusal"


def test_no_intermediate_state_holds_the_object_without_its_edges() -> None:
    """Asserted over every prefix of the stream, not just the final projection."""
    gov = governor()
    seed(gov, goal("GOAL-1"))
    gov.record_intent_object(
        requirement(relations=(rel(RelationType.DERIVED_FROM, "GOAL-1"),)), author=MODEL
    )

    stream = gov._store.load(PROJECT)  # noqa: SLF001
    for cut in range(1, len(stream) + 1):
        state = replay(PROJECT, stream[:cut])
        if "REQ-1" in state.objects:
            edges = [e for e in state.semantic.derivations if e.child_id == "REQ-1"]
            assert edges, "the object appeared in a state with no basis edge"


# --- authorship and authority (R24) --------------------------------------------------------


def test_a_non_human_may_propose() -> None:
    gov = governor()
    seed(gov, goal("GOAL-1"))
    gov.record_intent_object(
        requirement(relations=(rel(RelationType.SERVES, "GOAL-1"),)), author=MODEL
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_a_non_human_may_not_canonicalize() -> None:
    gov = governor()
    seed(gov, goal("GOAL-1"))
    with pytest.raises(ValueError, match="never authority"):
        gov.record_intent_object(requirement(authority=Authority.CANONICAL), author=MODEL)
    assert "INTENT_OBJECT_ADMITTED" not in events_of(gov)


def test_a_human_canonical_write_needs_a_matching_authenticated_actor() -> None:
    gov = governor()
    with pytest.raises(ValueError):
        gov.record_intent_object(
            requirement(authority=Authority.CANONICAL),
            author=HUMAN,
            human_actor_id="human://mallory",
        )


def test_a_human_canonical_write_needs_a_covering_authority_record() -> None:
    gov = governor()
    with pytest.raises(ValueError, match="AuthorityRecord"):
        gov.record_intent_object(
            requirement(authority=Authority.CANONICAL),
            author=HUMAN,
            human_actor_id=ALICE,
        )


def test_a_human_with_actor_and_covering_authority_succeeds() -> None:
    gov = governor()
    seed(gov, authority_record("AUTH-1", subject_id="REQ-1", authorized_by=ALICE))
    gov.record_intent_object(
        requirement(authority=Authority.CANONICAL), author=HUMAN, human_actor_id=ALICE
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_provenance_cannot_impersonate_authorship() -> None:
    """Human-looking provenance on a model-authored object is still model-authored."""
    gov = governor()
    seed(gov, authority_record("AUTH-1", subject_id="REQ-1", authorized_by=ALICE))
    with pytest.raises(ValueError, match="never authority"):
        gov.record_intent_object(
            requirement(authority=Authority.CANONICAL, provenance=HUMAN_PROV),
            author=MODEL,
        )


def test_a_non_human_author_may_not_carry_a_human_actor_id() -> None:
    gov = governor()
    with pytest.raises(ValueError, match="not borrowed"):
        gov.record_intent_object(requirement(), author=MODEL, human_actor_id=ALICE)


def test_the_author_survives_the_event_round_trip() -> None:
    from foundry.domain.events import parse_event

    gov = governor()
    gov.record_intent_object(requirement(provenance=SYSTEM_PROV), author=MODEL)
    stored = gov._store.load(PROJECT)[-1]  # noqa: SLF001
    reparsed = parse_event(stored.event.model_dump(mode="json"))

    assert isinstance(reparsed.payload, IntentObjectAdmissionPayload)
    assert reparsed.payload.author == MODEL


def test_semantic_object_gained_no_synthesis_origin_field() -> None:
    """The rejected alternative, pinned (R24)."""
    from foundry.domain.semantic import Requirement

    assert "synthesis_origin" not in Requirement.model_fields
    assert "origin" not in Requirement.model_fields


# --- narrowed API -------------------------------------------------------------------------


def test_non_intent_bearing_kinds_are_refused() -> None:
    gov = governor()
    claim = Claim(
        id="CLAIM-x",
        project_id=PROJECT,
        authority=Authority.OBSERVED,
        confidence=1.0,
        provenance=HUMAN_PROV,
        created_at=requirement().created_at,
        statement="Refunds take thirty days.",
    )
    with pytest.raises(ValueError, match="intent-bearing"):
        gov.record_intent_object(claim, author=MODEL)


def test_the_accepted_set_is_the_frozen_constant_itself_not_a_copy() -> None:
    """Drift pin: a local restatement would diverge the first time either moved."""
    import foundry.application.semantic_governance as seam
    from foundry.domain.intent_synthesis import INTENT_BEARING_SEMANTIC_KINDS

    assert seam.INTENT_BEARING_SEMANTIC_KINDS is INTENT_BEARING_SEMANTIC_KINDS
    assert SemanticKind.ACTOR not in INTENT_BEARING_SEMANTIC_KINDS


# --- admission is creation (R26) -----------------------------------------------------------


def test_admitting_an_existing_id_is_refused_before_append() -> None:
    gov = governor()
    gov.record_intent_object(requirement(), author=MODEL)
    before = len(gov._store.load(PROJECT))  # noqa: SLF001

    with pytest.raises(ValueError, match="already exists"):
        gov.record_intent_object(requirement(), author=MODEL)

    assert len(gov._store.load(PROJECT)) == before  # noqa: SLF001


def test_the_reducer_fails_closed_on_a_malformed_duplicate_admission() -> None:
    """Independent of the seam: a hand-built event must not overwrite either."""
    from foundry.domain.events import StoredEvent

    gov = governor()
    gov.record_intent_object(requirement(), author=MODEL)
    stream = list(gov._store.load(PROJECT))  # noqa: SLF001

    duplicate = StoredEvent(
        sequence=stream[-1].sequence + 1,
        event=EventEnvelope(
            event_id="EVT-duplicate",
            project_id=PROJECT,
            event_type=EventType.INTENT_OBJECT_ADMITTED,
            occurred_at=requirement().created_at,
            payload=IntentObjectAdmissionPayload(object=requirement(), author=MODEL),
        ),
    )
    with pytest.raises(ValueError, match="may not overwrite"):
        replay(PROJECT, (*stream, duplicate))


def test_non_goal_admission_works_through_the_seam() -> None:
    gov = governor()
    seed(gov, requirement())
    ng = non_goal(relations=(rel(RelationType.EXCLUDES, "REQ-1"),))
    gov.record_intent_object(ng, author=MODEL)
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_only_derived_from_relations_become_edges() -> None:
    """The reducer uses the payload's parent ids, never the object's whole relation set."""
    gov = governor()
    seed(gov, goal("GOAL-1"), goal("GOAL-2"))
    obj = requirement(
        relations=(
            rel(RelationType.DERIVED_FROM, "GOAL-1"),
            rel(RelationType.SERVES, "GOAL-2"),
        )
    )
    gov.record_intent_object(obj, author=MODEL)

    state = replay(PROJECT, gov._store.load(PROJECT))  # noqa: SLF001
    parents = sorted(e.parent_id for e in state.semantic.derivations if e.child_id == "REQ-1")
    assert parents == ["GOAL-1"], "a SERVES target is relevance and must never become basis"


def test_a_human_author_needs_a_matching_actor_even_when_not_canonical() -> None:
    """The actor law is about authorship, so it applies below CANONICAL too."""
    gov = governor()
    with pytest.raises(ValueError):
        gov.record_intent_object(requirement(), author=HUMAN, human_actor_id="human://mallory")
    assert "INTENT_OBJECT_ADMITTED" not in events_of(gov)


def test_the_admission_payload_requires_an_author() -> None:
    """An admission that could omit its author would make authorship optional."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        IntentObjectAdmissionPayload(object=requirement())  # type: ignore[call-arg]


# --- canonical Constraint facet rules (R19) -------------------------------------------------


def test_a_canonical_constraint_must_declare_its_relaxation_rule() -> None:
    gov = governor()
    seed(gov, authority_record("AUTH-1", subject_id="CON-1", authorized_by=ALICE))
    with pytest.raises(ValueError, match="ConstraintFacet"):
        gov.record_intent_object(
            constraint(authority=Authority.CANONICAL),
            author=HUMAN,
            human_actor_id=ALICE,
        )


def test_an_external_mandate_may_not_originate_inside_the_project() -> None:
    """A mandate the project wrote for itself is a project boundary under a stronger name."""
    gov = governor()
    seed(gov, authority_record("AUTH-1", subject_id="CON-1", authorized_by=ALICE))
    with pytest.raises(ValueError, match="EXTERNAL_MANDATE"):
        gov.record_intent_object(
            constraint(
                authority=Authority.CANONICAL,
                facet=ConstraintFacet.EXTERNAL_MANDATE,
                provenance=HUMAN_PROV,
            ),
            author=HUMAN,
            human_actor_id=ALICE,
        )


def test_an_external_mandate_with_external_provenance_is_admitted() -> None:
    gov = governor()
    seed(gov, authority_record("AUTH-1", subject_id="CON-1", authorized_by=ALICE))
    gov.record_intent_object(
        constraint(
            authority=Authority.CANONICAL,
            facet=ConstraintFacet.EXTERNAL_MANDATE,
            provenance=Provenance(source_kind=SourceKind.DOCUMENT, source_ref="doc://gdpr-art-17"),
        ),
        author=HUMAN,
        human_actor_id=ALICE,
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_a_project_boundary_may_be_human_authored() -> None:
    gov = governor()
    seed(gov, authority_record("AUTH-1", subject_id="CON-1", authorized_by=ALICE))
    gov.record_intent_object(
        constraint(authority=Authority.CANONICAL, facet=ConstraintFacet.PROJECT_BOUNDARY),
        author=HUMAN,
        human_actor_id=ALICE,
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_a_non_canonical_constraint_needs_no_facet_yet() -> None:
    """Proposals may still be forming; the rule applies at canonicalization."""
    gov = governor()
    gov.record_intent_object(constraint(), author=MODEL)
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


# --- the event seals its own contract (R28) --------------------------------------------------


def admission_envelope(obj: SemanticObject, **payload_kwargs: object) -> EventEnvelope:
    return EventEnvelope(
        event_id="EVT-direct",
        project_id=PROJECT,
        event_type=EventType.INTENT_OBJECT_ADMITTED,
        occurred_at=AT,
        payload=IntentObjectAdmissionPayload(object=obj, author=MODEL, **payload_kwargs),  # type: ignore[arg-type]
    )


def test_a_foreign_project_object_is_refused_at_the_event_layer() -> None:
    with pytest.raises(ValidationError, match="does not match event project"):
        admission_envelope(requirement(project_id="OTHER-PROJECT"))


def test_a_non_intent_bearing_object_is_refused_at_the_event_layer() -> None:
    """The contract means what its name says, without relying on the seam."""
    claim = Claim(
        id="CLAIM-x",
        project_id=PROJECT,
        authority=Authority.OBSERVED,
        confidence=1.0,
        provenance=HUMAN_PROV,
        created_at=AT,
        statement="Refunds take thirty days.",
    )
    with pytest.raises(ValidationError, match="intent-bearing"):
        admission_envelope(claim)


@pytest.mark.parametrize(
    ("relations", "parents", "why"),
    [
        ((("DERIVED_FROM", "GOAL-1"),), (), "missing parent"),
        ((("DERIVED_FROM", "GOAL-1"),), ("GOAL-1", "GOAL-9"), "extra parent"),
        ((("DERIVED_FROM", "GOAL-1"),), ("GOAL-9",), "wrong parent"),
        (
            (("DERIVED_FROM", "GOAL-2"), ("DERIVED_FROM", "GOAL-1")),
            ("GOAL-2", "GOAL-1"),
            "unsorted",
        ),
        ((("DERIVED_FROM", "GOAL-1"),), ("GOAL-1", "GOAL-1"), "duplicated"),
    ],
)
def test_an_event_may_not_claim_a_basis_its_object_does_not_hold(
    relations: tuple[tuple[str, str], ...], parents: tuple[str, ...], why: str
) -> None:
    """One basis, stated once. A self-contradicting event would replay forever."""
    obj = requirement(relations=tuple(rel(RelationType(r), t) for r, t in relations))
    with pytest.raises(ValidationError, match="DERIVED_FROM targets"):
        admission_envelope(obj, derivation_parent_ids=parents)


def test_the_canonical_parent_tuple_is_sorted_and_deduplicated() -> None:
    from foundry.domain.events import derivation_parents_of

    obj = requirement(
        relations=(
            rel(RelationType.DERIVED_FROM, "GOAL-2"),
            rel(RelationType.DERIVED_FROM, "GOAL-1"),
            rel(RelationType.DERIVED_FROM, "GOAL-2"),
        )
    )
    assert derivation_parents_of(obj) == ("GOAL-1", "GOAL-2")
    admission_envelope(obj, derivation_parent_ids=("GOAL-1", "GOAL-2"))


def test_the_seam_and_the_event_share_one_definition_of_basis() -> None:
    """If they drifted, the seam could write events its own contract would reject."""
    gov = governor()
    seed(gov, goal("GOAL-1"), goal("GOAL-2"))
    obj = requirement(
        relations=(
            rel(RelationType.DERIVED_FROM, "GOAL-2"),
            rel(RelationType.DERIVED_FROM, "GOAL-1"),
        )
    )
    gov.record_intent_object(obj, author=MODEL)

    payload = gov._store.load(PROJECT)[-1].event.payload  # noqa: SLF001
    assert isinstance(payload, IntentObjectAdmissionPayload)
    assert payload.derivation_parent_ids == ("GOAL-1", "GOAL-2")


# --- what IE2.1 does not claim about facets (R30) --------------------------------------------


def test_ie21_does_not_pretend_non_human_provenance_is_external() -> None:
    """The honest boundary: SYSTEM is not an external authority, and IE2.1 says so by
    not claiming otherwise. Proving the real basis chain is IE2.2."""
    gov = governor()
    seed(gov, authority_record("AUTH-1", subject_id="CON-1", authorized_by=ALICE))
    gov.record_intent_object(
        constraint(
            authority=Authority.CANONICAL,
            facet=ConstraintFacet.EXTERNAL_MANDATE,
            provenance=SYSTEM_PROV,
        ),
        author=HUMAN,
        human_actor_id=ALICE,
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED", (
        "IE2.1 admits this; the facet's basis is proved in IE2.2, not here"
    )


def test_the_seam_refuses_a_bad_kind_before_building_an_event() -> None:
    """Defence in depth, with the seam's own layer observable.

    The event contract refuses a non-intent-bearing object too (R28), so a seam that
    dropped its check would still be caught -- by a pydantic ValidationError raised while
    constructing the payload. That is the wrong shape of failure: the seam's job is to
    refuse before anything is built, so this asserts the plain refusal, not the fallback.
    """
    gov = governor()
    claim = Claim(
        id="CLAIM-y",
        project_id=PROJECT,
        authority=Authority.OBSERVED,
        confidence=1.0,
        provenance=HUMAN_PROV,
        created_at=AT,
        statement="Refunds take thirty days.",
    )
    with pytest.raises(ValueError) as error:
        gov.record_intent_object(claim, author=MODEL)

    assert not isinstance(error.value, ValidationError), (
        "the seam must refuse first; falling through to the event validator means its own "
        "narrowing was lost"
    )
