"""T10 — reconciliation-aware delivery readiness and IntentDecisionHandoff v2.

This is the quality gate between the Intent Engine and Architecture/Planning. It does
not change the contract: ``CanonicalIntentPackage`` remains the single thing delivered
downstream. T10 answers only *is the current governed intent safe enough to deliver?*

The central problem it solves is D6-R. ``SemanticReadiness.stale_object_ids`` is
topological: once a basis claim is superseded, every object derived from it stays in the
blast radius **forever**, even after that object has been correctly replaced and retired.
Gating delivery on ``semantic_readiness.ready`` would therefore deadlock a project the
moment it ever corrected itself. V2 partitions that same raw set into *provably
reconciled* and *still blocking*, and gates on the latter.

"Provably" is doing real work. Reconciliation is only accepted when a durable
``RetirementRecord`` chain leads to a head that is current, in scope, fresh, and — if
the original was canonical — canonical itself. A ``SUPERSEDED`` lifecycle on its own is
not proof of anything.
"""

from __future__ import annotations

import pytest

from foundry.application.handoff import build_intent_decision_handoff
from foundry.application.handoff_v2 import (
    HANDOFF_V2_VERSION,
    IntentDecisionHandoffV2,
    IntentDeliveryNotReadyError,
    build_intent_decision_handoff_v2,
)
from foundry.application.intent_synthesis import (
    resume_incomplete_synthesis,
    synthesize_intent,
)
from foundry.application.package import build_intent_package
from foundry.application.replay import replay
from foundry.application.semantic_reducer import claim_id_for
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Relation,
    RelationType,
)
from foundry.domain.events import DerivationPayload, EventType
from foundry.domain.handoff import build_semantic_readiness, locus_in_scope
from foundry.domain.handoff_v2 import (
    IntentBasisRef,
    IntentDeliveryReadiness,
    build_intent_delivery_readiness,
    scoped_incomplete_synthesis_proposal_ids,
    v2_blocking_stale_object_ids,
    validly_reconciled,
)
from foundry.domain.intent_synthesis import (
    IntentDisposition,
    IntentSynthesisPolicy,
    IntentSynthesisResult,
)
from foundry.domain.intent_synthesis_state import IntentSynthesisState, RetirementRecord
from foundry.domain.semantic import Intent, Requirement
from foundry.domain.semantic_judgment import SupersedeProposal
from foundry.domain.semantic_state import SemanticState
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from tests.unit._t8_fixtures import (
    AT,
    HUMAN,
    HUMAN_ACTOR,
    OTHER_SCOPE,
    PROJECT,
    PROVENANCE,
    RUN_ID,
    SCOPE,
    Ledger,
    ScriptedSynthesizer,
    assert_claim,
    authority_record,
    create_address,
    fixed_clock,
    judgment,
    run_id_factory,
)
from tests.unit.test_intent_synthesis_orchestrator import proposal

POLICY = IntentSynthesisPolicy()
ADDR_JDG = "J-addr"
OLD_JDG = "J-old"
NEW_JDG = "J-new"


def canonical_intent(object_id: str = "INTENT-1", scope: tuple[str, ...] = (SCOPE,)) -> Intent:
    return Intent(
        id=object_id,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=AT,
        scope=scope,
        mission="Refunds are fast and predictable.",
    )


def canonical_requirement(
    object_id: str,
    *,
    basis_claim_ids: tuple[str, ...] = (),
    scope: tuple[str, ...] = (SCOPE,),
    authority: Authority = Authority.CANONICAL,
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
    statement: str = "Refunds complete within seven days.",
) -> Requirement:
    return Requirement(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        lifecycle=lifecycle,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=AT,
        scope=scope,
        statement=statement,
        materiality=Materiality.LOW,
        requires_metric=False,
        requires_verification=False,
        relations=tuple(
            Relation(relation_type=RelationType.DERIVED_FROM, target_id=cid)
            for cid in basis_claim_ids
        ),
    )


def base_story(*, corrected: bool = False) -> tuple[Ledger, str, str]:
    """A canonical, closed scope whose one Requirement derives from a live claim.

    With ``corrected=True`` the basis claim is superseded, which makes REQ-OLD stale
    without touching its lifecycle — exactly the state that deadlocks v1 readiness.

    Both claims are CANONICAL: this story delivers canonical intent, which needs a lawful
    basis (R46, R60). A CANONICAL claim needs covering authority when it is asserted, so
    authority is recorded before either claim (R47).
    """
    ledger = Ledger()
    ledger.ingest("EV-1")
    ledger.ingest("EV-2")
    ledger.apply(create_address(ADDR_JDG, "EV-1"))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.record_object(authority_record("AUTH-1"))
    ledger.apply(
        assert_claim(OLD_JDG, ADDRESS, "EV-1", text="seven days", authority=Authority.CANONICAL)
    )
    old_claim = claim_id_for(PROJECT, OLD_JDG)
    ledger.record_object(canonical_intent())
    ledger.canonicalize(canonical_requirement("REQ-OLD", basis_claim_ids=(old_claim,)))
    ledger.append(
        EventType.DERIVATION_RECORDED, DerivationPayload(child_id="REQ-OLD", parent_id=OLD_JDG)
    )
    new_claim = ""
    if corrected:
        ledger.apply(
            assert_claim(
                NEW_JDG, ADDRESS, "EV-2", text="thirty days", authority=Authority.CANONICAL
            )
        )
        new_claim = claim_id_for(PROJECT, NEW_JDG)
        ledger.apply(
            judgment(
                "J-sup",
                SupersedeProposal(target_judgment_id=OLD_JDG, reason="corrected"),
                ("EV-2",),
            )
        )
    return ledger, old_claim, new_claim


def state_of(ledger: Ledger) -> IntentState:
    return replay(PROJECT, ledger.store.load(PROJECT))


def readiness_of(state: IntentState, scope: str = SCOPE) -> IntentDeliveryReadiness:
    view = derive_view(state.semantic)
    loci = tuple(locus for locus in view.loci if locus_in_scope(locus, scope))
    return build_intent_delivery_readiness(
        state, view, scope, loci, build_semantic_readiness(state, view, scope, loci)
    )


def reconcile_via_synthesis(ledger: Ledger, new_claim: str) -> None:
    """The real Slice-1 human synthesis path — never hand-edited state."""
    synthesize_intent(
        ledger.store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=ScriptedSynthesizer(
            IntentSynthesisResult(
                proposals=(
                    proposal(
                        disposition=IntentDisposition.REPLACES_STALE,
                        relates_to_object_id="REQ-OLD",
                        basis_claim_ids=(new_claim,),
                        statement="Refunds complete within thirty days.",
                    ),
                )
            ),
            fingerprint=HUMAN,
        ),
        policy=POLICY,
        clock=fixed_clock(),
        synthesis_run_id_factory=run_id_factory(RUN_ID),
        human_actor_id=HUMAN_ACTOR,
    )


def hand_built(
    objects: dict[str, object], retirements: tuple[RetirementRecord, ...], stale: tuple[str, ...]
) -> tuple[IntentState, object]:
    """A deliberately hand-built projection, for defence-in-depth checks only.

    These states are not reachable through routing or the reducer. They exist to prove
    the reconciliation law stands on its own rather than leaning on protections above it.
    """
    state = IntentState(
        project_id=PROJECT,
        objects=objects,
        semantic=SemanticState(),
        intent_synthesis=IntentSynthesisState(retirements=retirements),
    )

    class _View:
        stale_ids = stale
        representatives: dict[str, str] = {}

    return state, _View()


# --- C25: dependency direction ----------------------------------------------------------------


def _imported_modules(path: str) -> set[str]:
    """Every module this file actually imports — from the AST, not from its prose."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(path).read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _code_without_docstrings(obj) -> str:  # type: ignore[no-untyped-def]
    """Source with docstrings stripped, so a test checks behaviour and not commentary."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Module):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:]
    return ast.unparse(tree)


def test_the_domain_reconciliation_module_never_imports_the_application_layer() -> None:
    """C25: the earlier file-location sketch must not invert the dependency."""
    imported = _imported_modules("src/foundry/domain/handoff_v2.py")
    assert not {m for m in imported if m.startswith("foundry.application")}
    assert all(m.startswith("foundry.domain") or not m.startswith("foundry") for m in imported)


def test_the_application_layer_is_the_one_that_reaches_the_package() -> None:
    imported = _imported_modules("src/foundry/application/handoff_v2.py")
    assert "foundry.application.package" in imported
    assert "foundry.domain.handoff_v2" in imported


def test_the_canonical_package_was_not_relocated_or_duplicated() -> None:
    import pathlib

    from foundry.application.package import CanonicalIntentPackage

    assert CanonicalIntentPackage.__module__ == "foundry.application.package"
    app = pathlib.Path("src/foundry/application/handoff_v2.py").read_text()
    assert "class CanonicalIntentPackage" not in app
    assert "from foundry.application.package import" in app


def test_v1_handoff_modules_are_untouched() -> None:
    """I11: v1 is byte-frozen. Its hashes are checked in the commit gate too."""
    import hashlib
    import pathlib

    assert (
        hashlib.sha256(pathlib.Path("src/foundry/domain/handoff.py").read_bytes()).hexdigest()
        == "759eb5a71dbc2c0a31969dc2cf244e27d48326f7df8638d15894389575ecbc52"
    )
    assert (
        hashlib.sha256(pathlib.Path("src/foundry/application/handoff.py").read_bytes()).hexdigest()
        == "396ddfa7fbf3750c55791c0a5a73a4e2784898337139538d7a954c2eb816c494"
    )


# --- the reconciliation law -------------------------------------------------------------------


def test_a_lifecycle_alone_is_not_proof_of_reconciliation() -> None:
    """§7: retired outside the synthesis path leaves no RetirementRecord, so it blocks."""
    ledger, old_claim, _ = base_story(corrected=True)
    # Retire REQ-OLD the legacy way: just record it SUPERSEDED. No RetirementRecord.
    ledger.canonicalize(
        canonical_requirement(
            "REQ-OLD", basis_claim_ids=(old_claim,), lifecycle=LifecycleStatus.SUPERSEDED
        )
    )
    state = state_of(ledger)
    view = derive_view(state.semantic)

    assert state.objects["REQ-OLD"].lifecycle is LifecycleStatus.SUPERSEDED
    assert state.intent_synthesis.retirements == ()
    assert validly_reconciled(state, view, SCOPE, "REQ-OLD") is False
    assert "REQ-OLD" in readiness_of(state).blocking_stale_object_ids


def test_an_object_that_was_never_retired_is_not_reconciled() -> None:
    """ "Reconciled" means *was replaced*, not *happens to look fine right now*.

    Without the RetirementRecord requirement a perfectly healthy object would report as
    reconciled simply because it is active, canonical and in scope — which would let
    anything that never went through a replacement claim the status.
    """
    healthy = canonical_requirement("A")
    state, view = hand_built({"A": healthy}, (), stale=())
    assert validly_reconciled(state, view, SCOPE, "A") is False


def test_a_retirement_record_contradicting_the_projection_is_not_accepted() -> None:
    """§8: the retired object must actually be SUPERSEDED in the current projection."""
    old = canonical_requirement("A")
    head = canonical_requirement("B", statement="replacement")
    state, view = hand_built(
        {"A": old, "B": head},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="B",
                proposal_instance_id="SYN-x",
                recorded_by_event_id="EVT-x",
            ),
        ),
        stale=("A",),
    )
    # A claims to be retired but is still ACTIVE.
    assert validly_reconciled(state, view, SCOPE, "A") is False


def test_a_chain_is_followed_to_its_head() -> None:
    """§9/§33: A → B → C resolves to C, not merely B."""
    a = canonical_requirement("A", lifecycle=LifecycleStatus.SUPERSEDED)
    b = canonical_requirement("B", lifecycle=LifecycleStatus.SUPERSEDED)
    c = canonical_requirement("C", statement="current head")
    state, view = hand_built(
        {"A": a, "B": b, "C": c},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="B",
                proposal_instance_id="SYN-1",
                recorded_by_event_id="EVT-1",
            ),
            RetirementRecord(
                retired_object_id="B",
                replaced_by_object_id="C",
                proposal_instance_id="SYN-2",
                recorded_by_event_id="EVT-2",
            ),
        ),
        stale=("A", "B"),
    )
    assert validly_reconciled(state, view, SCOPE, "A") is True
    assert validly_reconciled(state, view, SCOPE, "B") is True


def test_a_retirement_cycle_terminates_and_does_not_reconcile() -> None:
    """§34: A → B → A must return False rather than recurse forever."""
    a = canonical_requirement("A", lifecycle=LifecycleStatus.SUPERSEDED)
    b = canonical_requirement("B", lifecycle=LifecycleStatus.SUPERSEDED)
    state, view = hand_built(
        {"A": a, "B": b},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="B",
                proposal_instance_id="SYN-1",
                recorded_by_event_id="EVT-1",
            ),
            RetirementRecord(
                retired_object_id="B",
                replaced_by_object_id="A",
                proposal_instance_id="SYN-2",
                recorded_by_event_id="EVT-2",
            ),
        ),
        stale=("A", "B"),
    )
    assert validly_reconciled(state, view, SCOPE, "A") is False
    assert validly_reconciled(state, view, SCOPE, "B") is False


@pytest.mark.parametrize(
    ("lifecycle", "authority", "scope", "label"),
    [
        (LifecycleStatus.SUPERSEDED, Authority.CANONICAL, (SCOPE,), "head-not-active"),
        (LifecycleStatus.ACTIVE, Authority.REJECTED, (SCOPE,), "head-rejected"),
        (LifecycleStatus.ACTIVE, Authority.SUPERSEDED, (SCOPE,), "head-superseded-authority"),
        (LifecycleStatus.ACTIVE, Authority.CANONICAL, (OTHER_SCOPE,), "head-out-of-scope"),
    ],
)
def test_a_head_that_is_not_current_and_applicable_does_not_reconcile(
    lifecycle: LifecycleStatus, authority: Authority, scope: tuple[str, ...], label: str
) -> None:
    a = canonical_requirement("A", lifecycle=LifecycleStatus.SUPERSEDED)
    head = canonical_requirement("B", lifecycle=lifecycle, authority=authority, scope=scope)
    state, view = hand_built(
        {"A": a, "B": head},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="B",
                proposal_instance_id="SYN-1",
                recorded_by_event_id="EVT-1",
            ),
        ),
        stale=("A",),
    )
    assert validly_reconciled(state, view, SCOPE, "A") is False


def test_a_missing_head_does_not_reconcile() -> None:
    a = canonical_requirement("A", lifecycle=LifecycleStatus.SUPERSEDED)
    state, view = hand_built(
        {"A": a},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="GONE",
                proposal_instance_id="SYN-1",
                recorded_by_event_id="EVT-1",
            ),
        ),
        stale=("A",),
    )
    assert validly_reconciled(state, view, SCOPE, "A") is False


def test_a_stale_head_does_not_reconcile_its_predecessor() -> None:
    """§11/§31: the replacement's own basis was later superseded, so nothing is settled."""
    a = canonical_requirement("A", lifecycle=LifecycleStatus.SUPERSEDED)
    b = canonical_requirement("B", statement="replacement that itself went stale")
    state, view = hand_built(
        {"A": a, "B": b},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="B",
                proposal_instance_id="SYN-1",
                recorded_by_event_id="EVT-1",
            ),
        ),
        stale=("A", "B"),
    )
    assert validly_reconciled(state, view, SCOPE, "A") is False


def test_a_proposed_head_cannot_reconcile_a_canonical_chain() -> None:
    """§12/§32: C11 defence-in-depth, below routing and the reducer."""
    a = canonical_requirement("A", lifecycle=LifecycleStatus.SUPERSEDED)
    head = canonical_requirement("B", authority=Authority.PROPOSED)
    state, view = hand_built(
        {"A": a, "B": head},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="B",
                proposal_instance_id="SYN-1",
                recorded_by_event_id="EVT-1",
            ),
        ),
        stale=("A",),
    )
    assert validly_reconciled(state, view, SCOPE, "A") is False


def test_a_non_canonical_original_may_be_reconciled_by_a_proposed_head() -> None:
    """Canonical preservation constrains canonical chains only."""
    a = canonical_requirement(
        "A", authority=Authority.PROPOSED, lifecycle=LifecycleStatus.SUPERSEDED
    )
    head = canonical_requirement("B", authority=Authority.PROPOSED)
    state, view = hand_built(
        {"A": a, "B": head},
        (
            RetirementRecord(
                retired_object_id="A",
                replaced_by_object_id="B",
                proposal_instance_id="SYN-1",
                recorded_by_event_id="EVT-1",
            ),
        ),
        stale=("A",),
    )
    assert validly_reconciled(state, view, SCOPE, "A") is True


# --- the v2 stale partition -------------------------------------------------------------------


def test_the_partition_keeps_every_raw_stale_id_and_never_drops_one() -> None:
    ledger, _, new_claim = base_story(corrected=True)
    reconcile_via_synthesis(ledger, new_claim)
    state = state_of(ledger)
    view = derive_view(state.semantic)
    loci = tuple(locus for locus in view.loci if locus_in_scope(locus, SCOPE))

    from foundry.domain.handoff import scoped_stale_object_ids

    raw = set(scoped_stale_object_ids(state.semantic, view, loci))
    readiness = readiness_of(state)
    partition = set(readiness.blocking_stale_object_ids) | set(
        readiness.reconciled_stale_object_ids
    )
    assert partition == raw
    assert not set(readiness.blocking_stale_object_ids) & set(readiness.reconciled_stale_object_ids)
    assert v2_blocking_stale_object_ids(state, view, SCOPE, loci) == (
        readiness.blocking_stale_object_ids
    )


def test_a_reconciled_id_stays_visible_as_history() -> None:
    """I19/C6: it moves out of blocking, it does not vanish from the audit trail."""
    ledger, _, new_claim = base_story(corrected=True)
    before = readiness_of(state_of(ledger))
    assert "REQ-OLD" in before.blocking_stale_object_ids

    reconcile_via_synthesis(ledger, new_claim)
    after = readiness_of(state_of(ledger))

    assert "REQ-OLD" not in after.blocking_stale_object_ids
    assert "REQ-OLD" in after.reconciled_stale_object_ids


# --- scoped incomplete synthesis --------------------------------------------------------------


def _incomplete_ledger(address_scope: tuple[str, ...] = (SCOPE,)) -> Ledger:
    """A durable DECIDED(APPLY) whose effect never landed."""
    from tests.unit.test_intent_synthesis_recovery import CrashingStore, Interrupted

    ledger = Ledger(CrashingStore(EventType.INTENT_OBJECT_SYNTHESIZED))
    ledger.ingest("EV-1")
    ledger.apply(create_address(ADDR_JDG, "EV-1", scope=address_scope))
    from tests.unit._t8_fixtures import ADDRESS

    ledger.apply(assert_claim("J-claim", ADDRESS, "EV-1"))
    ledger.record_object(canonical_intent(scope=address_scope or (SCOPE,)))
    ledger.record_object(authority_record("AUTH-1", scope=()))
    ledger.canonicalize(canonical_requirement("REQ-BASE", scope=address_scope or (SCOPE,)))
    with pytest.raises(Interrupted):
        synthesize_intent(
            ledger.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=ScriptedSynthesizer(IntentSynthesisResult(proposals=(proposal(),))),
            policy=POLICY,
            clock=fixed_clock(),
            synthesis_run_id_factory=run_id_factory(RUN_ID),
        )
    return ledger


def test_an_incomplete_proposal_blocks_only_the_scope_its_basis_applies_to() -> None:
    ledger = _incomplete_ledger(address_scope=(SCOPE,))
    state = state_of(ledger)
    assert scoped_incomplete_synthesis_proposal_ids(state, SCOPE) != ()
    assert scoped_incomplete_synthesis_proposal_ids(state, OTHER_SCOPE) == ()


def test_a_project_wide_incomplete_proposal_blocks_every_scope() -> None:
    ledger = _incomplete_ledger(address_scope=())
    state = state_of(ledger)
    assert scoped_incomplete_synthesis_proposal_ids(state, SCOPE) != ()
    assert scoped_incomplete_synthesis_proposal_ids(state, OTHER_SCOPE) != ()


def test_an_invalidated_proposal_is_never_reported_as_incomplete() -> None:
    """§36: T9's terminal non-effect is a legitimate exit, not lingering work."""
    ledger = _incomplete_ledger()
    ledger.store._crash_on = None  # type: ignore[attr-defined]
    ledger.apply(
        judgment(
            "J-sup", SupersedeProposal(target_judgment_id="J-claim", reason="wrong"), ("EV-1",)
        )
    )
    resume_incomplete_synthesis(ledger.store, project_id=PROJECT, clock=fixed_clock())

    state = state_of(ledger)
    assert state.intent_synthesis.invalidated_proposal_ids != ()
    assert scoped_incomplete_synthesis_proposal_ids(state, SCOPE) == ()


# --- the delivery gate ------------------------------------------------------------------------


def test_the_gate_does_not_read_semantic_readiness_ready() -> None:
    """D6-R as a structural fact: `ready` folds in the raw stale set v2 exists to refine."""
    code = _code_without_docstrings(build_intent_delivery_readiness)
    assert "semantic_readiness.ready" not in code
    assert "open_locus_ids" not in code
    assert "closure.closed" in code
    assert "blocking" in code


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param("closure", "CLOSURE_NOT_MET", id="non-closure"),
        pytest.param("stale", "UNRECONCILED_STALE_OBJECT", id="unreconciled-stale"),
        pytest.param("incomplete", "INCOMPLETE_SYNTHESIS", id="incomplete-synthesis"),
    ],
)
def test_each_blocker_refuses_delivery_with_its_own_code(mutate: str, expected: str) -> None:
    if mutate == "closure":
        ledger, _, _ = base_story()
        # Remove the canonical obligation by superseding it.
        ledger.canonicalize(canonical_requirement("REQ-OLD", lifecycle=LifecycleStatus.SUPERSEDED))
    elif mutate == "stale":
        ledger, _, _ = base_story(corrected=True)
    else:
        ledger = _incomplete_ledger()

    state = state_of(ledger)
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    assert expected in excinfo.value.blocker_codes


def test_blocker_codes_are_reported_in_full_and_in_a_fixed_order() -> None:
    """§25: every applicable code, never just the first one."""
    ledger = _incomplete_ledger()
    ledger.canonicalize(canonical_requirement("REQ-BASE", lifecycle=LifecycleStatus.SUPERSEDED))
    state = state_of(ledger)
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    codes = excinfo.value.blocker_codes
    assert "CLOSURE_NOT_MET" in codes
    assert "INCOMPLETE_SYNTHESIS" in codes
    order = [
        "CLOSURE_NOT_MET",
        "DISPUTED_LOCUS",
        "PENDING_MATERIAL_JUDGMENT",
        "UNRECONCILED_STALE_OBJECT",
        "UNGROUNDED_CANONICAL_OBJECT",
        "DEAD_BASIS",
        "UNLAWFUL_BASIS_AUTHORITY",
        "ASSUMPTION_IN_BASIS",
        "BASIS_CYCLE",
        "INCOMPLETE_SYNTHESIS",
    ]
    assert list(codes) == [c for c in order if c in codes]


def test_a_refused_delivery_emits_no_partial_handoff() -> None:
    ledger, _, _ = base_story(corrected=True)
    state = state_of(ledger)
    with pytest.raises(IntentDeliveryNotReadyError):
        build_intent_decision_handoff_v2(state, SCOPE)


# --- I19: the full correction → replacement → delivery story ----------------------------------


def test_i19_a_corrected_basis_blocks_delivery_until_it_is_properly_reconciled() -> None:
    ledger, _, new_claim = base_story(corrected=True)
    state = state_of(ledger)

    # Closure itself is met: the canonical Intent and Requirement are both still active.
    assert evaluate_closure(state, SCOPE).closed is True
    # Two independently true diagnoses before reconciliation (R60): REQ-OLD is stale, and
    # the claim it declares as its basis is no longer live.
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    assert excinfo.value.blocker_codes == ("UNRECONCILED_STALE_OBJECT", "DEAD_BASIS")

    reconcile_via_synthesis(ledger, new_claim)
    state = state_of(ledger)
    handoff = build_intent_decision_handoff_v2(state, SCOPE)

    replacement = next(
        object_id
        for object_id, obj in state.objects.items()
        if object_id.startswith("REQ-") and object_id != "REQ-OLD"
    )
    assert "REQ-OLD" in handoff.reconciled_stale_object_ids
    assert "REQ-OLD" not in handoff.blocking_stale_object_ids
    assert replacement in handoff.canonical_intent_object_ids
    assert state.objects["REQ-OLD"].lifecycle is LifecycleStatus.SUPERSEDED
    assert state.objects[replacement].authority is Authority.CANONICAL
    # Superseded REQ-OLD yields neither blocker; the replacement rests on a live CANONICAL
    # claim, so it is lawfully grounded itself.
    assert handoff.readiness.basis_blockers == ()
    assert [(r.relation_type, r.target_id) for r in state.objects[replacement].relations] == [
        (RelationType.DERIVED_FROM, new_claim)
    ]
    assert state.semantic.claims[new_claim].authority is Authority.CANONICAL


def test_d6r_v1_readiness_stays_false_while_v2_becomes_deliverable() -> None:
    """The whole reason v2 exists: v1's topological staleness never clears."""
    ledger, _, new_claim = base_story(corrected=True)
    reconcile_via_synthesis(ledger, new_claim)
    state = state_of(ledger)

    handoff = build_intent_decision_handoff_v2(state, SCOPE)

    assert "REQ-OLD" in handoff.readiness.semantic_readiness.stale_object_ids
    assert handoff.readiness.semantic_readiness.ready is False
    assert handoff.readiness.deliverable is True


# --- T9 integration ---------------------------------------------------------------------------


def test_an_incomplete_proposal_blocks_delivery_until_recovery_finishes_it() -> None:
    ledger = _incomplete_ledger()
    state = state_of(ledger)
    readiness = readiness_of(state)
    assert readiness.incomplete_synthesis_proposal_ids != ()
    assert readiness.deliverable is False
    with pytest.raises(IntentDeliveryNotReadyError) as excinfo:
        build_intent_decision_handoff_v2(state, SCOPE)
    assert "INCOMPLETE_SYNTHESIS" in excinfo.value.blocker_codes

    ledger.store._crash_on = None  # type: ignore[attr-defined]
    resume_incomplete_synthesis(ledger.store, project_id=PROJECT, clock=fixed_clock())

    state = state_of(ledger)
    assert readiness_of(state).incomplete_synthesis_proposal_ids == ()
    handoff = build_intent_decision_handoff_v2(state, SCOPE)
    assert handoff.readiness.deliverable is True


# --- the emitted envelope ---------------------------------------------------------------------


def deliverable_handoff() -> tuple[IntentState, IntentDecisionHandoffV2]:
    ledger, _, new_claim = base_story(corrected=True)
    reconcile_via_synthesis(ledger, new_claim)
    state = state_of(ledger)
    return state, build_intent_decision_handoff_v2(state, SCOPE)


def test_the_package_remains_the_single_contract() -> None:
    state, handoff = deliverable_handoff()
    assert handoff.contract == build_intent_package(state, SCOPE)
    assert handoff.intent_version == state.revision


def test_proposed_intent_is_visible_but_never_enters_the_contract() -> None:
    ledger, old_claim, _ = base_story()
    ledger.canonicalize(
        canonical_requirement(
            "REQ-PROPOSED",
            authority=Authority.PROPOSED,
            statement="A suggestion, not a commitment.",
        )
    )
    state = state_of(ledger)
    handoff = build_intent_decision_handoff_v2(state, SCOPE)

    assert "REQ-PROPOSED" in handoff.proposed_intent_object_ids
    assert "REQ-PROPOSED" not in handoff.canonical_intent_object_ids
    assert "REQ-PROPOSED" not in handoff.contract.obligation_ids
    assert "REQ-OLD" in handoff.canonical_intent_object_ids
    assert "REQ-OLD" in handoff.contract.obligation_ids


def test_retired_and_rejected_objects_are_in_neither_id_list() -> None:
    state, handoff = deliverable_handoff()
    assert "REQ-OLD" not in handoff.canonical_intent_object_ids
    assert "REQ-OLD" not in handoff.proposed_intent_object_ids


def test_the_intent_basis_bridge_names_only_real_claims_and_their_loci() -> None:
    state, handoff = deliverable_handoff()
    refs = {ref.object_id: ref for ref in handoff.intent_basis}
    assert set(refs) == set(handoff.canonical_intent_object_ids) | set(
        handoff.proposed_intent_object_ids
    )
    assert [ref.object_id for ref in handoff.intent_basis] == sorted(refs)

    view = derive_view(state.semantic)
    for ref in handoff.intent_basis:
        for claim_id in ref.basis_claim_ids:
            assert claim_id in state.semantic.claims
        expected = sorted(
            {
                view.representatives.get(
                    state.semantic.claims[c].address_id, state.semantic.claims[c].address_id
                )
                for c in ref.basis_claim_ids
            }
        )
        assert list(ref.basis_locus_ids) == expected


def test_a_legacy_object_with_no_v2_basis_is_legal() -> None:
    ledger, _, _ = base_story()
    state = state_of(ledger)
    handoff = build_intent_decision_handoff_v2(state, SCOPE)
    intent_ref = next(r for r in handoff.intent_basis if r.object_id == "INTENT-1")
    assert intent_ref.basis_claim_ids == ()
    assert intent_ref.basis_locus_ids == ()


def test_the_basis_bridge_does_not_expand_to_unrelated_same_locus_claims() -> None:
    """A sibling claim at the same address is NOT part of an object's basis."""
    ledger, old_claim, _ = base_story()
    from tests.unit._t8_fixtures import ADDRESS

    ledger.ingest("EV-sib")
    ledger.apply(assert_claim("J-sibling", ADDRESS, "EV-sib", text="also true"))
    sibling = claim_id_for(PROJECT, "J-sibling")
    state = state_of(ledger)
    handoff = build_intent_decision_handoff_v2(state, SCOPE)

    ref = next(r for r in handoff.intent_basis if r.object_id == "REQ-OLD")
    assert ref.basis_claim_ids == (old_claim,)
    assert sibling not in ref.basis_claim_ids


def test_v2_carries_ids_and_traceability_only() -> None:
    """I9: no statement, rationale, claim body, evidence content or model output."""
    state, handoff = deliverable_handoff()
    rendered = handoff.model_dump_json()
    for leak in (
        "Refunds complete within thirty days",
        "Refunds are fast and predictable",
        "thirty days",
        "seven days",
        "because the evidence says so",
        "body of EV-1",
        "alice owns payments",
    ):
        assert leak not in rendered
    assert set(IntentBasisRef.model_fields) == {
        "object_id",
        "basis_claim_ids",
        "basis_locus_ids",
    }


def test_v2_reuses_v1_traceability_verbatim() -> None:
    state, handoff = deliverable_handoff()
    v1 = build_intent_decision_handoff(state, SCOPE)
    assert handoff.loci == v1.loci
    assert handoff.claim_ids == v1.claim_ids
    assert handoff.evidence_ids == v1.evidence_ids
    assert handoff.authority_record_ids == v1.authority_record_ids
    assert handoff.superseded_judgment_ids == v1.superseded_judgment_ids
    assert handoff.pending_material_judgment_ids == v1.pending_material_judgment_ids
    assert handoff.readiness.semantic_readiness == v1.readiness


def test_v1_and_v2_coexist_without_migration() -> None:
    state, handoff = deliverable_handoff()
    v1 = build_intent_decision_handoff(state, SCOPE)
    assert v1.handoff_version == "intent-decision-handoff-v1"
    assert handoff.handoff_version == HANDOFF_V2_VERSION == "intent-decision-handoff-v2"


def test_construction_is_deterministic() -> None:
    state, first = deliverable_handoff()
    second = build_intent_decision_handoff_v2(state, SCOPE)
    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


# --- no second ledger -------------------------------------------------------------------------


def test_the_v2_views_are_absent_from_every_durable_structure() -> None:
    from foundry.domain.events import EventPayload
    from foundry.domain.intent_synthesis_state import IntentSynthesisState as ISS

    payloads = {t.__name__ for t in EventPayload.__value__.__args__}
    for name in ("IntentDecisionHandoffV2", "IntentDeliveryReadiness", "IntentBasisRef"):
        assert name not in payloads
    for model in (IntentState, ISS):
        rendered = " ".join(str(f.annotation) for f in model.model_fields.values())
        for name in ("IntentDecisionHandoffV2", "IntentDeliveryReadiness", "IntentBasisRef"):
            assert name not in rendered


def test_no_handoff_event_type_exists() -> None:
    names = {e.name for e in EventType}
    assert not {n for n in names if "HANDOFF" in n or "DELIVER" in n}
