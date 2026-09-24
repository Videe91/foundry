"""IE2.2a — cycle refusal for SERVES and DERIVED_FROM.

The hazard is narrower than it looks, and the fixtures here reflect what the seam can
actually produce. IE2.1 requires every relation target to resolve, so the naive shape --
admit `A -> B`, then admit `B -> A` -- is impossible: either `B` exists and the second
admission is refused as a duplicate, or it does not and the first raises
``UnresolvedTargetError``. Writing that as a test would manufacture a failure the seam
cannot create.

What these tests exercise is the real shape: a **legacy or dangling** historical graph
completed by a new write. Historical objects carry relations that were never validated,
including edges to ids that do not exist, and a later admission can close one into a cycle.
"""

from __future__ import annotations

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import RelationType
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    SemanticObjectPayload,
)
from foundry.domain.graph_cycles import (
    CYCLE_CHECKED_RELATIONS,
    RelationCycleError,
    assert_no_cycle_introduced,
)
from foundry.domain.relation_legality import UnresolvedTargetError
from foundry.domain.state import IntentState
from tests.unit._ie21_fixtures import AT, MODEL, PROJECT, goal, rel

TRANSITIVE = [RelationType.SERVES, RelationType.DERIVED_FROM]


def governor() -> SemanticGovernor:
    return SemanticGovernor(
        store=InMemoryEventStore(),
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: AT,
        id_factory=lambda prefix: prefix,
    )


def seed_legacy(gov: SemanticGovernor, *objects: object) -> None:
    """Record objects the way history holds them: without IE2.1 validation.

    This is the only honest way to build the fixture, because the seam would refuse these
    shapes -- which is precisely why they can only arrive from history.
    """
    store = gov._store  # noqa: SLF001
    for obj in objects:
        store.append(
            EventEnvelope(
                event_id=f"EVT-legacy-{obj.id}",  # type: ignore[attr-defined]
                project_id=PROJECT,
                event_type=EventType.SEMANTIC_OBJECT_RECORDED,
                occurred_at=AT,
                payload=SemanticObjectPayload(object=obj),  # type: ignore[arg-type]
            ),
            expected_sequence=store.current_sequence(PROJECT),
        )


def events_of(gov: SemanticGovernor) -> list[str]:
    return [s.event.event_type.value for s in gov._store.load(PROJECT)]  # noqa: SLF001


# --- the premise: the naive shape is impossible, so it is not what we test ------------------


def test_the_naive_fresh_write_cycle_cannot_be_formed_at_all() -> None:
    """Pins why these fixtures use legacy state rather than two ordinary admissions."""
    gov = governor()
    with pytest.raises(UnresolvedTargetError):
        gov.record_intent_object(
            goal("A", relations=(rel(RelationType.SERVES, "B"),)), author=MODEL
        )


# --- closing a dangling historical edge -----------------------------------------------------


@pytest.mark.parametrize("relation", TRANSITIVE, ids=lambda r: r.value)
def test_a_new_write_may_not_close_a_dangling_two_node_cycle(relation: RelationType) -> None:
    gov = governor()
    seed_legacy(gov, goal("A", relations=(rel(relation, "B"),)))  # B does not exist
    before = len(gov._store.load(PROJECT))  # noqa: SLF001

    with pytest.raises(RelationCycleError, match=relation.value):
        gov.record_intent_object(goal("B", relations=(rel(relation, "A"),)), author=MODEL)

    assert len(gov._store.load(PROJECT)) == before, "a refusal appends nothing"  # noqa: SLF001


@pytest.mark.parametrize("relation", TRANSITIVE, ids=lambda r: r.value)
def test_a_new_write_may_not_close_a_three_node_cycle(relation: RelationType) -> None:
    gov = governor()
    seed_legacy(
        gov,
        goal("A", relations=(rel(relation, "B"),)),
        goal("B", relations=(rel(relation, "C"),)),  # C dangles
    )
    with pytest.raises(RelationCycleError):
        gov.record_intent_object(goal("C", relations=(rel(relation, "A"),)), author=MODEL)


def test_a_refused_admission_leaves_the_store_byte_identical() -> None:
    gov = governor()
    seed_legacy(gov, goal("A", relations=(rel(RelationType.SERVES, "B"),)))
    before = [s.event.model_dump(mode="json") for s in gov._store.load(PROJECT)]  # noqa: SLF001

    with pytest.raises(RelationCycleError):
        gov.record_intent_object(
            goal("B", relations=(rel(RelationType.SERVES, "A"),)), author=MODEL
        )

    after = [s.event.model_dump(mode="json") for s in gov._store.load(PROJECT)]  # noqa: SLF001
    assert after == before


# --- what must NOT be refused ---------------------------------------------------------------


def test_an_unrelated_pre_existing_cycle_terminates_and_does_not_refuse() -> None:
    """Termination *and* precision: the walk must stop, and must not over-refuse.

    A dropped visited set makes this hang or recurse; treating any reachable cycle as the
    candidate's cycle makes it refuse `X`, which participates in nothing.
    """
    gov = governor()
    seed_legacy(
        gov,
        goal("A", relations=(rel(RelationType.SERVES, "B"),)),
        goal("B", relations=(rel(RelationType.SERVES, "A"),)),  # pre-existing cycle
    )
    gov.record_intent_object(goal("X", relations=(rel(RelationType.SERVES, "A"),)), author=MODEL)
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_a_diamond_is_not_a_cycle() -> None:
    """Reconvergence is ordinary graph shape; over-refusal is as wrong as under-refusal.

    B --> A
    C --> A
    D --> B, C
    """
    gov = governor()
    seed_legacy(
        gov,
        goal("A"),
        goal("B", relations=(rel(RelationType.SERVES, "A"),)),
        goal("C", relations=(rel(RelationType.SERVES, "A"),)),
    )
    gov.record_intent_object(
        goal("D", relations=(rel(RelationType.SERVES, "B"), rel(RelationType.SERVES, "C"))),
        author=MODEL,
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_a_long_acyclic_chain_is_accepted() -> None:
    gov = governor()
    chain = [goal("N0")]
    for i in range(1, 40):
        chain.append(goal(f"N{i}", relations=(rel(RelationType.SERVES, f"N{i - 1}"),)))
    seed_legacy(gov, *chain)

    gov.record_intent_object(
        goal("N40", relations=(rel(RelationType.SERVES, "N39"),)), author=MODEL
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


def test_only_the_same_relation_type_participates_in_a_cycle() -> None:
    """A SERVES path plus a DERIVED_FROM path are different graphs.

    Mixing them would invent a cycle that exists in neither.
    """
    gov = governor()
    seed_legacy(gov, goal("A", relations=(rel(RelationType.SERVES, "B"),)))  # B dangles

    gov.record_intent_object(
        goal("B", relations=(rel(RelationType.DERIVED_FROM, "A"),)), author=MODEL
    )
    assert events_of(gov)[-1] == "INTENT_OBJECT_ADMITTED"


@pytest.mark.parametrize(
    "relation",
    [RelationType.EXCLUDES, RelationType.CONSTRAINS, RelationType.AFFECTS],
    ids=lambda r: r.value,
)
def test_non_transitive_relations_are_not_walked(relation: RelationType) -> None:
    assert relation not in CYCLE_CHECKED_RELATIONS


# --- the helper directly ----------------------------------------------------------------------


def test_a_self_edge_is_refused_by_the_helper() -> None:
    """Defensive domain behaviour. IE2.1's unresolved-target rule already stops this at the
    seam, so this is not IE2.2a's first line of protection -- it is the helper being total."""
    obj = goal("A", relations=(rel(RelationType.SERVES, "A"),))
    with pytest.raises(RelationCycleError):
        assert_no_cycle_introduced(IntentState(project_id=PROJECT, objects={"A": obj}), obj)


def test_the_helper_treats_unresolved_ids_as_leaves() -> None:
    """History holds dangling edges; the helper refuses new cycles, it does not audit them."""
    existing = goal("A", relations=(rel(RelationType.SERVES, "GHOST"),))
    candidate = goal("B", relations=(rel(RelationType.SERVES, "A"),))
    assert_no_cycle_introduced(IntentState(project_id=PROJECT, objects={"A": existing}), candidate)


# --- replay is untouched -------------------------------------------------------------------


def test_a_legacy_cyclic_stream_still_replays() -> None:
    """Forward-only: refusing a new write never retroactively breaks a stream."""
    gov = governor()
    seed_legacy(
        gov,
        goal("A", relations=(rel(RelationType.SERVES, "B"),)),
        goal("B", relations=(rel(RelationType.SERVES, "A"),)),
    )
    state = replay(PROJECT, gov._store.load(PROJECT))  # noqa: SLF001
    assert state.objects["A"].relations[0].target_id == "B"
    assert state.objects["B"].relations[0].target_id == "A"
