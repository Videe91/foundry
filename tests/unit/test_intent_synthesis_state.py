"""T2 — the Intent Synthesis state projection.

Covers the Slice-1 T2 contract: ``IntentSynthesisState``, ``RetirementRecord`` and
``incomplete_proposal_ids``.

Three laws are load-bearing here and each has its own section below:

* **C15** — there is exactly ONE definition of incomplete, it reads ``decisions``, and
  no field named ``admissions`` exists anywhere on this projection.
* **I24** — applied / invalidated / incomplete is a three-way partition of every
  durable ``DECIDED(APPLY)`` **at any snapshot**. It is not a claim that progress has
  happened; ``incomplete`` is a legal, detectable, non-terminal state.
* **I24a (the T2 half only)** — incomplete is representable, detectable, accepted, and
  never made irreversible by the representation. Proving the exit *operation* is
  reachable belongs to T9, where ``resume_incomplete_synthesis`` exists.

Nothing here touches events, reducers, orchestration or recovery; those are T3+.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisDecision,
    IntentSynthesisDecisionRecord,
    IntentSynthesisRoute,
    RequirementSynthesisProposal,
    SynthesisIdentity,
    SynthesisOrigin,
)
from foundry.domain.intent_synthesis_state import (
    IntentSynthesisState,
    RetirementRecord,
    incomplete_proposal_ids,
)
from foundry.domain.semantic_judgment import ReasonerFingerprint

APPLY = IntentSynthesisRoute.APPLY
NON_APPLY = (
    IntentSynthesisRoute.NO_CHANGE,
    IntentSynthesisRoute.REJECT,
    IntentSynthesisRoute.REQUIRE_HUMAN,
    IntentSynthesisRoute.REQUIRE_SECOND_LENS,
)


DECIDED_AT = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
AUTHOR = ReasonerFingerprint(provider="human", model="human://alice", policy_version="v1")


def _identity(tag: str) -> SynthesisIdentity:
    """A real identity; its derivation is exercised exhaustively by the T1 suite."""
    return SynthesisIdentity(project_id="PROJ-A", synthesis_run_id="RUN-1", model_proposal_id=tag)


def _pid(tag: str) -> str:
    """The durable ``proposal_instance_id`` runtime derives for ``tag``."""
    return _identity(tag).proposal_instance_id


def _proposal(tag: str = "a") -> RequirementSynthesisProposal:
    return RequirementSynthesisProposal(
        model_proposal_id=tag,
        disposition=IntentDisposition.NEW,
        statement="Revocation is immediate.",
        rationale="Stated by the owner.",
        basis_claim_ids=("CLAIM-1",),
    )


def _record(
    tag: str,
    route: IntentSynthesisRoute = APPLY,
    *,
    decision: IntentSynthesisDecision | None = None,
    origin: SynthesisOrigin = SynthesisOrigin.HUMAN_STATED,
    assigned_authority: Authority | None = Authority.CANONICAL,
    decision_event_id: str = "EVT-1",
) -> IntentSynthesisDecisionRecord:
    identity = _identity(tag)
    return IntentSynthesisDecisionRecord(
        identity=identity,
        proposal=_proposal(tag),
        author=AUTHOR,
        origin=origin,
        assigned_authority=assigned_authority,
        decision=decision
        or IntentSynthesisDecision(
            proposal_instance_id=identity.proposal_instance_id, route=route, reasons=("REASON",)
        ),
        decision_event_id=decision_event_id,
        decided_at=DECIDED_AT,
    )


def _state(
    *records: IntentSynthesisDecisionRecord,
    applied: tuple[str, ...] = (),
    invalidated: tuple[str, ...] = (),
    retirements: tuple[RetirementRecord, ...] = (),
) -> IntentSynthesisState:
    return IntentSynthesisState(
        decisions={r.identity.proposal_instance_id: r for r in records},
        applied_proposal_ids=applied,
        invalidated_proposal_ids=invalidated,
        retirements=retirements,
    )


def _retirement(
    *,
    retired_object_id: str = "REQ-old",
    replaced_by_object_id: str = "REQ-new",
    proposal_instance_id: str = _pid("1"),
    recorded_by_event_id: str = "EVT-1",
) -> RetirementRecord:
    return RetirementRecord(
        retired_object_id=retired_object_id,
        replaced_by_object_id=replaced_by_object_id,
        proposal_instance_id=proposal_instance_id,
        recorded_by_event_id=recorded_by_event_id,
    )


# --- empty, immutable, deterministic --------------------------------------------------


def test_the_projection_starts_empty() -> None:
    state = IntentSynthesisState()
    assert state.decisions == {}
    assert state.applied_proposal_ids == ()
    assert state.invalidated_proposal_ids == ()
    assert state.retirements == ()


def test_the_projection_is_frozen_and_its_mappings_are_frozen_proxies() -> None:
    state = _state(_record("1"))
    with pytest.raises(ValidationError):
        state.applied_proposal_ids = (_pid("1"),)
    assert isinstance(state.decisions, MappingProxyType)
    with pytest.raises(TypeError):
        state.decisions[_pid("2")] = _record("2")  # type: ignore[index]


def test_serialization_is_deterministic_and_round_trips() -> None:
    state = _state(_record("1"), _record("2"), applied=(_pid("1"),), retirements=(_retirement(),))
    dumped = state.model_dump(mode="json")
    assert isinstance(dumped["decisions"], dict)
    restored = IntentSynthesisState.model_validate(dumped)
    assert restored == state
    assert restored.model_dump(mode="json") == dumped


# --- C15: decisions, never admissions -------------------------------------------------


def test_the_projection_has_no_admissions_field() -> None:
    """C15: a second formulation over ``admissions`` predated C12/C13 and is gone."""
    assert "admissions" not in IntentSynthesisState.model_fields
    assert set(IntentSynthesisState.model_fields) == {
        "decisions",
        "applied_proposal_ids",
        "invalidated_proposal_ids",
        "retirements",
    }


def test_incomplete_reads_the_decisions_plane() -> None:
    state = _state(_record("1"))
    assert incomplete_proposal_ids(state) == (_pid("1"),)


# --- incomplete: the single definition ------------------------------------------------


def test_apply_with_neither_terminal_marker_is_incomplete() -> None:
    assert incomplete_proposal_ids(_state(_record("1"))) == (_pid("1"),)


def test_apply_that_was_applied_is_not_incomplete() -> None:
    state = _state(_record("1"), applied=(_pid("1"),))
    assert incomplete_proposal_ids(state) == ()


def test_apply_that_was_invalidated_is_not_incomplete() -> None:
    state = _state(_record("1"), invalidated=(_pid("1"),))
    assert incomplete_proposal_ids(state) == ()


@pytest.mark.parametrize("route", NON_APPLY)
def test_a_non_apply_decision_is_never_incomplete(route: IntentSynthesisRoute) -> None:
    """Non-APPLY routes are terminal at the decision and need no invalidation."""
    assert incomplete_proposal_ids(_state(_record("1", route))) == ()


def test_incomplete_preserves_deterministic_projection_order() -> None:
    """Projection order, never sorted order.

    The insertion order is chosen as the REVERSE of the derived ids' sort order, so the
    distinction is guaranteed rather than left to whatever the hashes happen to be — a
    test that only accidentally distinguished the two could rot into a vacuous one.
    """
    tags = ("9", "3", "5")
    descending = sorted(tags, key=_pid, reverse=True)
    state = _state(*(_record(tag) for tag in descending))
    expected = tuple(_pid(tag) for tag in descending)
    assert incomplete_proposal_ids(state) == expected
    assert expected != tuple(sorted(expected))
    assert incomplete_proposal_ids(state) != tuple(sorted(expected))


def test_incomplete_is_a_tuple_not_an_unordered_set() -> None:
    assert isinstance(incomplete_proposal_ids(_state(_record("1"))), tuple)


# --- I24: the three-way snapshot partition --------------------------------------------


def test_the_three_sets_are_pairwise_disjoint_and_jointly_cover_every_apply() -> None:
    state = _state(
        _record("1"),
        _record("2"),
        _record("3"),
        _record("4", IntentSynthesisRoute.REJECT),
        applied=(_pid("2"),),
        invalidated=(_pid("3"),),
    )
    applied = frozenset(state.applied_proposal_ids)
    invalidated = frozenset(state.invalidated_proposal_ids)
    incomplete = frozenset(incomplete_proposal_ids(state))

    assert applied & invalidated == frozenset()
    assert applied & incomplete == frozenset()
    assert invalidated & incomplete == frozenset()

    every_apply = frozenset(
        pid
        for pid, record in state.decisions.items()
        if record.decision.route is IntentSynthesisRoute.APPLY
    )
    assert applied | invalidated | incomplete == every_apply


def test_a_non_apply_decision_belongs_to_none_of_the_three_sets() -> None:
    state = _state(_record("1", IntentSynthesisRoute.NO_CHANGE))
    assert state.applied_proposal_ids == ()
    assert state.invalidated_proposal_ids == ()
    assert incomplete_proposal_ids(state) == ()


def test_there_is_no_fourth_lifecycle_state() -> None:
    """applied / invalidated / incomplete and nothing else."""
    state = _state(_record("1"), _record("2"), applied=(_pid("1"),))
    covered = (
        frozenset(state.applied_proposal_ids)
        | frozenset(state.invalidated_proposal_ids)
        | frozenset(incomplete_proposal_ids(state))
    )
    assert covered == frozenset(state.decisions)


# --- I24: fail closed on impossible terminal bookkeeping ------------------------------


def test_one_proposal_cannot_be_both_applied_and_invalidated() -> None:
    with pytest.raises(ValidationError):
        _state(_record("1"), applied=(_pid("1"),), invalidated=(_pid("1"),))


@pytest.mark.parametrize("marker", ["applied", "invalidated"])
def test_a_terminal_marker_needs_a_durable_decision(marker: str) -> None:
    kwargs = {marker: ("SYN-missing",)}
    with pytest.raises(ValidationError):
        _state(_record("1"), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("marker", ["applied", "invalidated"])
@pytest.mark.parametrize("route", NON_APPLY)
def test_a_terminal_marker_is_refused_for_a_non_apply_decision(
    marker: str, route: IntentSynthesisRoute
) -> None:
    kwargs = {marker: (_pid("1"),)}
    with pytest.raises(ValidationError):
        _state(_record("1", route), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("marker", ["applied", "invalidated"])
def test_a_terminal_marker_cannot_be_recorded_twice(marker: str) -> None:
    kwargs = {marker: (_pid("1"), _pid("1"))}
    with pytest.raises(ValidationError):
        _state(_record("1"), **kwargs)  # type: ignore[arg-type]


def test_a_decision_must_be_keyed_by_its_own_proposal_instance_id() -> None:
    with pytest.raises(ValidationError):
        IntentSynthesisState(decisions={"SYN-wrong": _record("1")})


# --- C19: the durable decision record -------------------------------------------------


def test_the_decisions_plane_holds_full_durable_records() -> None:
    """C19: enough to FINISH the decision already made, with no provider call."""
    record = _state(_record("1")).decisions[_pid("1")]
    assert record.proposal.statement == "Revocation is immediate."
    assert record.proposal.basis_claim_ids == ("CLAIM-1",)
    assert record.proposal.disposition is IntentDisposition.NEW
    assert record.origin is SynthesisOrigin.HUMAN_STATED
    assert record.author == AUTHOR
    assert record.assigned_authority is Authority.CANONICAL
    assert record.decision_event_id == "EVT-1"
    assert record.decided_at == DECIDED_AT
    assert record.identity.proposal_instance_id == _pid("1")


def test_the_record_carries_exactly_the_approved_fields() -> None:
    assert set(IntentSynthesisDecisionRecord.model_fields) == {
        "identity",
        "proposal",
        "author",
        "origin",
        "assigned_authority",
        "decision",
        "decision_event_id",
        "decided_at",
    }


def test_the_record_does_not_carry_a_synthesized_object() -> None:
    """The object does not exist yet; INTENT_OBJECT_SYNTHESIZED establishes it."""
    fields = set(IntentSynthesisDecisionRecord.model_fields)
    assert not fields & {"object", "requirement", "synthesized_object", "intent_object"}


def test_the_record_and_its_decision_must_name_the_same_proposal() -> None:
    mismatched = IntentSynthesisDecision(
        proposal_instance_id=_pid("2"), route=APPLY, reasons=("REASON",)
    )
    with pytest.raises(ValidationError):
        _record("1", decision=mismatched)


def test_a_decision_event_id_is_required() -> None:
    with pytest.raises(ValidationError):
        _record("1", decision_event_id="")


def test_assigned_authority_may_be_absent_when_no_authority_was_assigned() -> None:
    """REQUIRE_HUMAN assigns none; the record must represent that, not invent a default."""
    record = _record("1", IntentSynthesisRoute.REQUIRE_HUMAN, assigned_authority=None)
    assert record.assigned_authority is None


def test_every_durable_field_survives_a_serialization_round_trip() -> None:
    """Recovery reads a replayed projection, so each durable field must round-trip."""
    state = _state(_record("1"), _record("2", IntentSynthesisRoute.NO_CHANGE))
    restored = IntentSynthesisState.model_validate(state.model_dump(mode="json"))
    assert restored == state
    original = state.decisions[_pid("1")]
    revived = restored.decisions[_pid("1")]
    assert revived.identity == original.identity
    assert revived.proposal == original.proposal
    assert revived.author == original.author
    assert revived.origin is original.origin
    assert revived.assigned_authority is original.assigned_authority
    assert revived.decision == original.decision
    assert revived.decision_event_id == original.decision_event_id
    assert revived.decided_at == original.decided_at


def test_the_record_is_frozen_and_forbids_extra_fields() -> None:
    record = _record("1")
    with pytest.raises(ValidationError):
        record.decision_event_id = "EVT-2"
    with pytest.raises(ValidationError):
        IntentSynthesisDecisionRecord.model_validate(
            {**record.model_dump(mode="json"), "applied_object": "REQ-1"}
        )


def test_incomplete_reads_the_route_through_the_durable_record() -> None:
    state = _state(_record("1"), _record("2", IntentSynthesisRoute.REJECT))
    assert incomplete_proposal_ids(state) == (_pid("1"),)
    assert state.decisions[_pid("1")].decision.route is APPLY


# --- I24a, the T2 half only -----------------------------------------------------------


def test_incomplete_is_representable_and_accepted_not_an_error() -> None:
    """``incomplete`` is a LEGAL non-terminal state; the projection must not refuse it."""
    state = _state(_record("1"), _record("2"))
    assert incomplete_proposal_ids(state) == (_pid("1"), _pid("2"))


def test_nothing_in_the_representation_makes_incomplete_irreversible() -> None:
    """Either terminal marker may still be recorded later; neither is foreclosed."""
    state = _state(_record("1"))
    assert incomplete_proposal_ids(state) == (_pid("1"),)
    applied_later = _state(_record("1"), applied=(_pid("1"),))
    invalidated_later = _state(_record("1"), invalidated=(_pid("1"),))
    assert incomplete_proposal_ids(applied_later) == ()
    assert incomplete_proposal_ids(invalidated_later) == ()


def test_t2_neither_defines_nor_imports_the_recovery_operation() -> None:
    """The executable legal exit belongs to T9, not to this projection.

    Checked structurally, not by text search: the module docstring deliberately NAMES
    ``resume_incomplete_synthesis`` to record where the exit lives, and saying so is
    the point rather than a violation.
    """
    import ast

    import foundry.domain.intent_synthesis_state as module

    assert not hasattr(module, "resume_incomplete_synthesis")
    source = module.__file__
    assert source is not None
    tree = ast.parse(Path(source).read_text(encoding="utf-8"), filename=source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom | ast.Import)
        for alias in node.names
    }
    assert "resume_incomplete_synthesis" not in defined | imported


def test_t2_imports_no_layer_above_the_domain() -> None:
    """No orchestration, no application layer, and no new cross-layer dependency."""
    import ast

    import foundry.domain.intent_synthesis_state as module

    source = module.__file__
    assert source is not None
    tree = ast.parse(Path(source).read_text(encoding="utf-8"), filename=source)
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    for name in modules:
        assert not name.startswith("foundry.application")
        assert not name.startswith("foundry.adapters")
        assert not name.startswith("foundry.intelligence")
        assert not name.startswith("foundry.ports")


# --- RetirementRecord -----------------------------------------------------------------


def test_a_retirement_record_carries_exactly_the_approved_shape() -> None:
    assert set(RetirementRecord.model_fields) == {
        "retired_object_id",
        "replaced_by_object_id",
        "proposal_instance_id",
        "recorded_by_event_id",
    }


@pytest.mark.parametrize(
    "field",
    [
        "retired_object_id",
        "replaced_by_object_id",
        "proposal_instance_id",
        "recorded_by_event_id",
    ],
)
def test_every_retirement_identifier_must_be_non_empty(field: str) -> None:
    with pytest.raises(ValidationError):
        _retirement(**{field: ""})  # type: ignore[arg-type]


def test_a_retirement_record_is_frozen_and_forbids_extras() -> None:
    record = _retirement()
    with pytest.raises(ValidationError):
        record.retired_object_id = "REQ-other"
    with pytest.raises(ValidationError):
        RetirementRecord.model_validate(
            {
                "retired_object_id": "REQ-old",
                "replaced_by_object_id": "REQ-new",
                "proposal_instance_id": _pid("1"),
                "recorded_by_event_id": "EVT-1",
                "reason": "because",
            }
        )


def test_an_object_cannot_replace_itself() -> None:
    with pytest.raises(ValidationError):
        _retirement(retired_object_id="REQ-1", replaced_by_object_id="REQ-1")


def test_retirements_are_an_immutable_ordered_tuple() -> None:
    first = _retirement(retired_object_id="REQ-1", proposal_instance_id=_pid("1"))
    second = _retirement(retired_object_id="REQ-2", proposal_instance_id=_pid("2"))
    state = _state(retirements=(first, second))
    assert state.retirements == (first, second)
    assert isinstance(state.retirements, tuple)
    with pytest.raises(ValidationError):
        state.retirements = ()
