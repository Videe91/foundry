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

from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from foundry.domain.intent_synthesis import IntentSynthesisDecision, IntentSynthesisRoute
from foundry.domain.intent_synthesis_state import (
    IntentSynthesisState,
    RetirementRecord,
    incomplete_proposal_ids,
)

APPLY = IntentSynthesisRoute.APPLY
NON_APPLY = (
    IntentSynthesisRoute.NO_CHANGE,
    IntentSynthesisRoute.REJECT,
    IntentSynthesisRoute.REQUIRE_HUMAN,
    IntentSynthesisRoute.REQUIRE_SECOND_LENS,
)


def _decision(
    proposal_instance_id: str, route: IntentSynthesisRoute = APPLY
) -> IntentSynthesisDecision:
    return IntentSynthesisDecision(
        proposal_instance_id=proposal_instance_id, route=route, reasons=("REASON",)
    )


def _state(
    *decisions: IntentSynthesisDecision,
    applied: tuple[str, ...] = (),
    invalidated: tuple[str, ...] = (),
    retirements: tuple[RetirementRecord, ...] = (),
) -> IntentSynthesisState:
    return IntentSynthesisState(
        decisions={d.proposal_instance_id: d for d in decisions},
        applied_proposal_ids=applied,
        invalidated_proposal_ids=invalidated,
        retirements=retirements,
    )


def _retirement(
    *,
    retired_object_id: str = "REQ-old",
    replaced_by_object_id: str = "REQ-new",
    proposal_instance_id: str = "SYN-1",
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
    state = _state(_decision("SYN-1"))
    with pytest.raises(ValidationError):
        state.applied_proposal_ids = ("SYN-1",)
    assert isinstance(state.decisions, MappingProxyType)
    with pytest.raises(TypeError):
        state.decisions["SYN-2"] = _decision("SYN-2")  # type: ignore[index]


def test_serialization_is_deterministic_and_round_trips() -> None:
    state = _state(
        _decision("SYN-1"), _decision("SYN-2"), applied=("SYN-1",), retirements=(_retirement(),)
    )
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
    state = _state(_decision("SYN-1"))
    assert incomplete_proposal_ids(state) == ("SYN-1",)


# --- incomplete: the single definition ------------------------------------------------


def test_apply_with_neither_terminal_marker_is_incomplete() -> None:
    assert incomplete_proposal_ids(_state(_decision("SYN-1"))) == ("SYN-1",)


def test_apply_that_was_applied_is_not_incomplete() -> None:
    state = _state(_decision("SYN-1"), applied=("SYN-1",))
    assert incomplete_proposal_ids(state) == ()


def test_apply_that_was_invalidated_is_not_incomplete() -> None:
    state = _state(_decision("SYN-1"), invalidated=("SYN-1",))
    assert incomplete_proposal_ids(state) == ()


@pytest.mark.parametrize("route", NON_APPLY)
def test_a_non_apply_decision_is_never_incomplete(route: IntentSynthesisRoute) -> None:
    """Non-APPLY routes are terminal at the decision and need no invalidation."""
    assert incomplete_proposal_ids(_state(_decision("SYN-1", route))) == ()


def test_incomplete_preserves_deterministic_projection_order() -> None:
    """Projection order, not alphabetical order: the ids below sort the other way."""
    state = _state(_decision("SYN-9"), _decision("SYN-3"), _decision("SYN-5"))
    assert incomplete_proposal_ids(state) == ("SYN-9", "SYN-3", "SYN-5")
    assert incomplete_proposal_ids(state) != tuple(sorted(incomplete_proposal_ids(state)))


def test_incomplete_is_a_tuple_not_an_unordered_set() -> None:
    assert isinstance(incomplete_proposal_ids(_state(_decision("SYN-1"))), tuple)


# --- I24: the three-way snapshot partition --------------------------------------------


def test_the_three_sets_are_pairwise_disjoint_and_jointly_cover_every_apply() -> None:
    state = _state(
        _decision("SYN-1"),
        _decision("SYN-2"),
        _decision("SYN-3"),
        _decision("SYN-4", IntentSynthesisRoute.REJECT),
        applied=("SYN-2",),
        invalidated=("SYN-3",),
    )
    applied = frozenset(state.applied_proposal_ids)
    invalidated = frozenset(state.invalidated_proposal_ids)
    incomplete = frozenset(incomplete_proposal_ids(state))

    assert applied & invalidated == frozenset()
    assert applied & incomplete == frozenset()
    assert invalidated & incomplete == frozenset()

    every_apply = frozenset(
        pid for pid, d in state.decisions.items() if d.route is IntentSynthesisRoute.APPLY
    )
    assert applied | invalidated | incomplete == every_apply


def test_a_non_apply_decision_belongs_to_none_of_the_three_sets() -> None:
    state = _state(_decision("SYN-1", IntentSynthesisRoute.NO_CHANGE))
    assert state.applied_proposal_ids == ()
    assert state.invalidated_proposal_ids == ()
    assert incomplete_proposal_ids(state) == ()


def test_there_is_no_fourth_lifecycle_state() -> None:
    """applied / invalidated / incomplete and nothing else."""
    state = _state(_decision("SYN-1"), _decision("SYN-2"), applied=("SYN-1",))
    covered = (
        frozenset(state.applied_proposal_ids)
        | frozenset(state.invalidated_proposal_ids)
        | frozenset(incomplete_proposal_ids(state))
    )
    assert covered == frozenset(state.decisions)


# --- I24: fail closed on impossible terminal bookkeeping ------------------------------


def test_one_proposal_cannot_be_both_applied_and_invalidated() -> None:
    with pytest.raises(ValidationError):
        _state(_decision("SYN-1"), applied=("SYN-1",), invalidated=("SYN-1",))


@pytest.mark.parametrize("marker", ["applied", "invalidated"])
def test_a_terminal_marker_needs_a_durable_decision(marker: str) -> None:
    kwargs = {marker: ("SYN-missing",)}
    with pytest.raises(ValidationError):
        _state(_decision("SYN-1"), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("marker", ["applied", "invalidated"])
@pytest.mark.parametrize("route", NON_APPLY)
def test_a_terminal_marker_is_refused_for_a_non_apply_decision(
    marker: str, route: IntentSynthesisRoute
) -> None:
    kwargs = {marker: ("SYN-1",)}
    with pytest.raises(ValidationError):
        _state(_decision("SYN-1", route), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("marker", ["applied", "invalidated"])
def test_a_terminal_marker_cannot_be_recorded_twice(marker: str) -> None:
    kwargs = {marker: ("SYN-1", "SYN-1")}
    with pytest.raises(ValidationError):
        _state(_decision("SYN-1"), **kwargs)  # type: ignore[arg-type]


def test_a_decision_must_be_keyed_by_its_own_proposal_instance_id() -> None:
    with pytest.raises(ValidationError):
        IntentSynthesisState(decisions={"SYN-wrong": _decision("SYN-1")})


# --- I24a, the T2 half only -----------------------------------------------------------


def test_incomplete_is_representable_and_accepted_not_an_error() -> None:
    """``incomplete`` is a LEGAL non-terminal state; the projection must not refuse it."""
    state = _state(_decision("SYN-1"), _decision("SYN-2"))
    assert incomplete_proposal_ids(state) == ("SYN-1", "SYN-2")


def test_nothing_in_the_representation_makes_incomplete_irreversible() -> None:
    """Either terminal marker may still be recorded later; neither is foreclosed."""
    state = _state(_decision("SYN-1"))
    assert incomplete_proposal_ids(state) == ("SYN-1",)
    applied_later = _state(_decision("SYN-1"), applied=("SYN-1",))
    invalidated_later = _state(_decision("SYN-1"), invalidated=("SYN-1",))
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
                "proposal_instance_id": "SYN-1",
                "recorded_by_event_id": "EVT-1",
                "reason": "because",
            }
        )


def test_an_object_cannot_replace_itself() -> None:
    with pytest.raises(ValidationError):
        _retirement(retired_object_id="REQ-1", replaced_by_object_id="REQ-1")


def test_retirements_are_an_immutable_ordered_tuple() -> None:
    first = _retirement(retired_object_id="REQ-1", proposal_instance_id="SYN-1")
    second = _retirement(retired_object_id="REQ-2", proposal_instance_id="SYN-2")
    state = _state(retirements=(first, second))
    assert state.retirements == (first, second)
    assert isinstance(state.retirements, tuple)
    with pytest.raises(ValidationError):
        state.retirements = ()
