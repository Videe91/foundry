"""T5 — the one shared AuthorityRecord coverage law.

A behaviour-preserving extraction. Semantic Admission and (from T6) Intent Synthesis
must consult ONE implementation of "does this actor hold a live AuthorityRecord
covering this target scope?", so the two governance paths cannot drift apart.

The helper deliberately does NOT decide whether the actor is human — that stays with
the caller, because admission reads it from a ``ReasonerFingerprint`` while synthesis
will read it from its own authorship contract.

Every case below pins TODAY's behaviour. Nothing here is a new governance rule.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foundry.domain.authority import authority_record_is_live, covering_authority_record
from foundry.domain.common import Authority, LifecycleStatus, Materiality, Provenance, SourceKind
from foundry.domain.semantic import AuthorityRecord, Intent, Requirement
from foundry.domain.state import IntentState

PROJECT = "PROJ-A"
ACTOR = "human://alice"
CREATED_AT = datetime(2026, 9, 23, tzinfo=UTC)
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref=ACTOR)

DEAD_CASES = [
    ("lifecycle SUPERSEDED", {"lifecycle": LifecycleStatus.SUPERSEDED}),
    ("lifecycle REJECTED", {"lifecycle": LifecycleStatus.REJECTED}),
    ("lifecycle RESOLVED", {"lifecycle": LifecycleStatus.RESOLVED}),
    ("authority REJECTED", {"authority": Authority.REJECTED}),
    ("authority SUPERSEDED", {"authority": Authority.SUPERSEDED}),
]


def _record(
    *,
    object_id: str = "AUTH-1",
    authorized_by: str = ACTOR,
    scope: tuple[str, ...] = (),
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
    authority: Authority = Authority.CANONICAL,
) -> AuthorityRecord:
    return AuthorityRecord(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=CREATED_AT,
        scope=scope,
        lifecycle=lifecycle,
        subject_id="SUBJ-1",
        authorized_by=authorized_by,
        rationale="because",
    )


def _state(*objects: AuthorityRecord | Intent | Requirement) -> IntentState:
    return IntentState(project_id=PROJECT, objects={o.id: o for o in objects})


def _look_up(
    *objects: AuthorityRecord | Intent | Requirement,
    actor_id: str = ACTOR,
    target_scope: tuple[str, ...] | None = ("keyring",),
) -> AuthorityRecord | None:
    return covering_authority_record(_state(*objects), actor_id=actor_id, target_scope=target_scope)


# --- actor matching --------------------------------------------------------------------


def test_a_matching_actor_with_a_covering_record_is_eligible() -> None:
    record = _record(scope=("keyring",))
    assert _look_up(record) is record


def test_a_different_actor_never_matches() -> None:
    assert _look_up(_record(authorized_by="human://bob", scope=("keyring",))) is None


def test_an_empty_actor_id_fails_closed() -> None:
    """Silently matching nothing would hide a caller bug behind a plausible answer."""
    with pytest.raises(ValueError):
        _look_up(_record(scope=("keyring",)), actor_id="")


# --- liveness --------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "overrides"), DEAD_CASES, ids=[c[0] for c in DEAD_CASES])
def test_a_non_live_record_never_covers(label: str, overrides: dict[str, object]) -> None:
    assert _look_up(_record(scope=("keyring",), **overrides)) is None  # type: ignore[arg-type]


def test_an_active_ordinary_record_remains_eligible() -> None:
    record = _record(scope=("keyring",), authority=Authority.PROPOSED)
    assert _look_up(record) is record


def test_the_liveness_predicate_matches_the_existing_law() -> None:
    assert authority_record_is_live(_record()) is True
    for _label, overrides in DEAD_CASES:
        assert authority_record_is_live(_record(**overrides)) is False  # type: ignore[arg-type]


# --- project-wide authority record ------------------------------------------------------


@pytest.mark.parametrize(
    "target_scope",
    [("keyring",), ("keyring", "relay"), (), None],
    ids=["scoped", "multi-scoped", "project-wide", "no-single-target"],
)
def test_a_project_wide_record_covers_every_target(
    target_scope: tuple[str, ...] | None,
) -> None:
    record = _record(scope=())
    assert _look_up(record, target_scope=target_scope) is record


# --- scoped authority record ------------------------------------------------------------


def test_a_scoped_record_covers_an_intersecting_target() -> None:
    record = _record(scope=("keyring",))
    assert _look_up(record, target_scope=("keyring", "relay")) is record


def test_a_scoped_record_does_not_cover_a_disjoint_target() -> None:
    assert _look_up(_record(scope=("keyring",)), target_scope=("relay",)) is None


def test_a_scoped_record_does_not_cover_a_target_with_no_single_scope() -> None:
    """``None`` means the judgment has no single target; only project-wide authority covers it."""
    assert _look_up(_record(scope=("keyring",)), target_scope=None) is None


def test_a_scoped_record_does_not_cover_a_project_wide_target() -> None:
    assert _look_up(_record(scope=("keyring",)), target_scope=()) is None


def test_coverage_is_intersection_not_containment() -> None:
    """Pinned deliberately: T5 must not silently strengthen this to subset coverage.

    Authority coverage and the C21 replacement-scope law are different concepts.
    """
    record = _record(scope=("billing", "security"))
    assert _look_up(record, target_scope=("security", "identity")) is record


# --- deterministic selection -------------------------------------------------------------


def test_selection_is_deterministic_by_object_id() -> None:
    """Replay and pure routing must never depend on dict construction order."""
    later = _record(object_id="AUTH-Z", scope=("keyring",))
    earlier = _record(object_id="AUTH-A", scope=("keyring",))
    state = IntentState(project_id=PROJECT, objects={later.id: later, earlier.id: earlier})
    chosen = covering_authority_record(state, actor_id=ACTOR, target_scope=("keyring",))
    assert chosen is earlier
    assert chosen is not None
    assert chosen.id == "AUTH-A"


# --- non-authority objects ---------------------------------------------------------------


def test_objects_that_are_not_authority_records_are_ignored() -> None:
    intent = Intent(
        id="AUTH-0",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=CREATED_AT,
        mission="Ship safely.",
    )
    requirement = Requirement(
        id="AUTH-00",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=CREATED_AT,
        statement="s",
        materiality=Materiality.LOW,
        requires_metric=False,
        requires_verification=False,
    )
    record = _record(object_id="AUTH-9", scope=("keyring",))
    # The decoys sort BEFORE the real record, so a missing isinstance check would return one.
    assert _look_up(intent, requirement, record) is record


def test_no_record_at_all_yields_none() -> None:
    assert _look_up() is None


# --- the architectural property: one implementation ---------------------------------------


def test_admission_calls_the_shared_helper_rather_than_reimplementing_it() -> None:
    """T5 exists to stop the two governance paths drifting apart.

    Pinned as an architectural property rather than a source snapshot: admission must
    import the shared primitive, and must not carry its own combination of
    ``authorized_by`` matching, liveness and scope intersection.
    """
    source = Path("src/foundry/domain/admission.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "foundry.domain.authority"
        for alias in node.names
    }
    assert "covering_authority_record" in imported
    # No second body implementing the coverage law.
    assert "authorized_by ==" not in source
    assert "frozenset(record.scope)" not in source


def test_the_shared_module_depends_only_on_leaf_domain_primitives() -> None:
    """No application, adapter, intelligence, ports or event-store dependency."""
    tree = ast.parse(Path("src/foundry/domain/authority.py").read_text(encoding="utf-8"))
    runtime_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        # a TYPE_CHECKING-only import lives under an `if`, so skip guarded blocks
        and not any(
            isinstance(parent, ast.If)
            for parent in ast.walk(tree)
            if isinstance(parent, ast.If) and node in ast.walk(parent)
        )
    }
    for module in runtime_modules:
        for forbidden in (
            "foundry.application",
            "foundry.adapters",
            "foundry.intelligence",
            "foundry.ports",
            "foundry.experiments",
        ):
            assert not module.startswith(forbidden), f"{module} is not a leaf domain dependency"


def test_the_historical_import_path_still_works() -> None:
    """Eight call sites import liveness from admission; none may break."""
    from foundry.domain.admission import authority_record_is_live as from_admission
    from foundry.domain.authority import authority_record_is_live as from_authority

    assert from_admission is from_authority
