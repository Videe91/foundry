"""A root INTENT is a staleness boundary (IE3 design §17.2, decision 2026-09-29).

``DERIVED_FROM`` on a root Intent records provenance. It does not make an ordinary claim's
freshness a lifecycle dependency of the root: superseding a claim the root cites leaves the root
current, reusable and not stale, while every other object keeps the existing staleness law.
Root replacement stays D8; nothing here retires or re-grounds a root.

Every world is built through the governed path: claims are asserted and superseded by
judgments, and every graph is applied by ``synthesize_intent_graph`` with the real validator,
router, compiler and reducer. Only the synthesizer's answer is scripted.
"""

from __future__ import annotations

from itertools import count
from typing import Any

import pytest

from foundry.application.intent_graph_synthesis import synthesize_intent_graph
from foundry.application.intent_graph_synthesis_context import (
    compile_intent_graph_context,
    graph_visibility_from_request,
)
from foundry.application.replay import replay
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.common import Authority, LifecycleStatus, RelationType
from foundry.domain.intent_graph import IntentGraphSynthesisResult
from foundry.domain.intent_graph_validation import (
    GraphVisibility,
    IntentGraphValidationError,
    validate_intent_graph,
)
from foundry.domain.intent_synthesis import IntentSynthesisRoute
from foundry.domain.intent_view import derive_intent_view, root_intent_ids
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_identity import SemanticCandidate
from foundry.domain.semantic_judgment import AdmissionRoute, CreateAddressProposal
from foundry.domain.semantic_view import derive_view
from foundry.domain.state import IntentState
from tests.unit._ie3_s3_fixtures import AI, HUMAN_G, FakeGraphSynthesizer, clock
from tests.unit._ie21_fixtures import ALICE, PROJECT, SCOPE
from tests.unit._ie22b_fixtures import EVIDENCE_ID, World, _judgment

_RUNS = count(1)
ACTIVE = LifecycleStatus.ACTIVE
MISSION = "Operate the refund service according to its governing rules."


def _address(world: World, judgment_id: str, subject: str, facet: str) -> str:
    decision = world.governor.submit(
        _judgment(
            judgment_id,
            CreateAddressProposal(
                candidate=SemanticCandidate(
                    candidate_id=f"CAND-{judgment_id}",
                    subject=subject,
                    facet=facet,
                    scope=(SCOPE,),
                    evidence_ids=(EVIDENCE_ID,),
                )
            ),
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY, decision
    return address_id_for(PROJECT, judgment_id)


def _claim(world: World, judgment_id: str, address_id: str, text: str) -> str:
    saved = world.address_id
    world.address_id = address_id
    try:
        return world.claim(judgment_id, authority=Authority.CANONICAL, text=text)
    finally:
        world.address_id = saved


class Orion:
    """Three operational claims at three addresses, as IE2 would leave them."""

    def __init__(self) -> None:
        self.world = World()
        self.window = claim_id_for(PROJECT, "J-window")
        self.world.claim("J-window", authority=Authority.CANONICAL, text="thirty days")
        method = _address(self.world, "J-addr-method", "Refund method", "Where are refunds paid?")
        self.method = _claim(self.world, "J-method", method, "the original payment method")
        hosting = _address(self.world, "J-addr-host", "Refund data", "Where may data be kept?")
        self.hosting = _claim(self.world, "J-host", hosting, "UK-hosted infrastructure only")

    def state(self) -> IntentState:
        return replay(PROJECT, self.world.store.load(PROJECT))

    def supersede(self, judgment_id: str, target: str) -> None:
        self.world.supersede(judgment_id, target)

    def correct_window(self, text: str = "fourteen days") -> str:
        """The operational correction: a new window claim, the old judgment superseded."""
        new = _claim(self.world, "J-window-2", self.world.address_id, text)
        self.supersede("J-sup-window", "J-window")
        return new


def _basis(claim_id: str) -> dict[str, Any]:
    return {"namespace": "basis", "claim_id": claim_id}


def _local(local_id: str) -> dict[str, Any]:
    return {"namespace": "local", "local_id": local_id}


def _existing(object_id: str) -> dict[str, Any]:
    return {"namespace": "existing", "object_id": object_id}


def _edge(source: str, relation: str, target: dict[str, Any]) -> dict[str, Any]:
    return {"source": {"local_id": source}, "relation_type": relation, "target": target}


def _node(local_id: str, kind: str, text: str, **extra: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "local_id": {"local_id": local_id},
        "kind": kind,
        "proposal_rationale": "scripted",
        **extra,
    }
    node["mission" if kind == "INTENT" else "statement"] = text
    return node


def _apply(
    orion: Orion,
    nodes: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    *,
    author: Any = AI,
) -> IntentState:
    result = IntentGraphSynthesisResult.model_validate({"nodes": nodes, "relations": relations})
    run = f"RUN-root-{next(_RUNS)}"
    outcome = synthesize_intent_graph(
        orion.world.store,
        project_id=PROJECT,
        scope=SCOPE,
        synthesizer=FakeGraphSynthesizer(result, fingerprint=author),
        clock=clock,
        synthesis_run_id_factory=lambda: run,
        human_actor_id=ALICE if author is HUMAN_G else None,
    )
    assert outcome.decision is not None and outcome.decision.route is IntentSynthesisRoute.APPLY
    return orion.state()


def _seed(orion: Orion, *, root_basis: tuple[str, ...], author: Any = AI) -> IntentState:
    """T1: one root cited on ``root_basis``, a Requirement on the window and a Constraint on
    hosting, both serving the root; plus a Requirement on the method, which no test corrects."""
    root_edges = [_edge("root", "DERIVED_FROM", _basis(c)) for c in root_basis]
    return _apply(
        orion,
        [
            _node("root", "INTENT", MISSION),
            _node("req-window", "REQUIREMENT", "Refund requests are accepted for thirty days."),
            _node(
                "con-host",
                "CONSTRAINT",
                "Refund data stays on UK-hosted infrastructure.",
                facet="EVIDENCE_BOUND",
            ),
            _node("req-method", "REQUIREMENT", "Refunds go to the original payment method."),
        ],
        [
            *root_edges,
            _edge("req-window", "DERIVED_FROM", _basis(orion.window)),
            _edge("req-window", "SERVES", _local("root")),
            _edge("con-host", "DERIVED_FROM", _basis(orion.hosting)),
            _edge("con-host", "SERVES", _local("root")),
            _edge("req-method", "DERIVED_FROM", _basis(orion.method)),
            _edge("req-method", "SERVES", _local("root")),
        ],
        author=author,
    )


def _one(state: IntentState, kind: SemanticKind, text: str) -> str:
    (object_id,) = [
        o.id
        for o in state.objects.values()
        if o.kind is kind and text in (getattr(o, "mission", None) or getattr(o, "statement", ""))
    ]
    return object_id


def _root(state: IntentState) -> str:
    (object_id,) = [o.id for o in state.objects.values() if o.kind is SemanticKind.INTENT]
    return object_id


def _stale(state: IntentState) -> frozenset[str]:
    return frozenset(derive_intent_view(state).stale_ids)


def _shown_stale(state: IntentState, object_id: str) -> bool:
    request = compile_intent_graph_context(state, scope=SCOPE).request
    assert request is not None
    (shown,) = [o for o in request.known_objects if o.object_id == object_id]
    return shown.is_stale


def _visibility(state: IntentState) -> GraphVisibility:
    request = compile_intent_graph_context(state, scope=SCOPE).request
    assert request is not None
    return graph_visibility_from_request(request)


def _root_edges(state: IntentState, root: str) -> set[str]:
    return {e.parent_id for e in state.semantic.derivations if e.child_id == root}


# --- 1-3: the root boundary -----------------------------------------------------------------


def test_1_a_root_on_a_current_claim_is_current_and_not_stale() -> None:
    orion = Orion()
    state = _seed(orion, root_basis=(orion.window,))
    root = _root(state)
    assert state.objects[root].lifecycle is LifecycleStatus.ACTIVE
    assert root not in _stale(state)
    assert _shown_stale(state, root) is False


def test_2_superseding_the_roots_claim_leaves_the_root_current_and_not_stale() -> None:
    orion = Orion()
    root = _root(_seed(orion, root_basis=(orion.window,)))
    orion.correct_window()
    state = orion.state()
    assert root in derive_view(state.semantic).stale_ids, "premise: the plane marks it"
    assert state.objects[root].lifecycle is LifecycleStatus.ACTIVE
    assert state.objects[root].authority is Authority.PROPOSED
    assert root not in _stale(state)
    assert _shown_stale(state, root) is False


def test_3_the_roots_derived_from_provenance_is_untouched() -> None:
    orion = Orion()
    before = _seed(orion, root_basis=(orion.window,))
    root = _root(before)
    orion.correct_window()
    after = orion.state()
    assert _root_edges(after, root) == _root_edges(before, root) == {orion.window}
    relations = {(r.relation_type, r.target_id) for r in after.objects[root].relations}
    assert (RelationType.DERIVED_FROM, orion.window) in relations
    assert after.semantic.derivations[: len(before.semantic.derivations)] == (
        before.semantic.derivations
    )


# --- 4-5: the root stays the one root -------------------------------------------------------


def test_4_the_root_stays_a_serves_target_after_its_claim_is_corrected() -> None:
    orion = Orion()
    root = _root(_seed(orion, root_basis=(orion.window,)))
    orion.correct_window()
    state = orion.state()
    visibility = _visibility(state)
    (shown,) = [o for o in visibility.objects if o.object_id == root]
    assert shown.is_current and not shown.is_stale
    new_claim = claim_id_for(PROJECT, "J-window-2")
    result = IntentGraphSynthesisResult.model_validate(
        {
            "nodes": [_node("goal", "GOAL", "Refund requests are handled predictably.")],
            "relations": [
                _edge("goal", "DERIVED_FROM", _basis(new_claim)),
                _edge("goal", "SERVES", _existing(root)),
            ],
        }
    )
    validate_intent_graph(result, visibility, author_is_human=False)


def test_5_a_second_root_is_still_refused_after_the_correction() -> None:
    orion = Orion()
    _seed(orion, root_basis=(orion.window,))
    new_claim = orion.correct_window()
    result = IntentGraphSynthesisResult.model_validate(
        {
            "nodes": [_node("root-2", "INTENT", "A second purpose.")],
            "relations": [_edge("root-2", "DERIVED_FROM", _basis(new_claim))],
        }
    )
    with pytest.raises(IntentGraphValidationError) as refused:
        validate_intent_graph(result, _visibility(orion.state()), author_is_human=False)
    assert refused.value.code == "MULTIPLE_ROOTS"


# --- 6-9: ordinary objects keep the existing law --------------------------------------------


def test_6_a_requirement_on_the_superseded_claim_is_stale_as_before() -> None:
    orion = Orion()
    req = _one(_seed(orion, root_basis=(orion.window,)), SemanticKind.REQUIREMENT, "thirty")
    orion.correct_window()
    state = orion.state()
    assert req in _stale(state)
    assert req in derive_view(state.semantic).stale_ids
    assert _shown_stale(state, req) is True


def test_7_a_constraint_on_the_superseded_claim_is_stale_as_before() -> None:
    orion = Orion()
    con = _one(_seed(orion, root_basis=(orion.hosting,)), SemanticKind.CONSTRAINT, "UK")
    orion.supersede("J-sup-host", "J-host")
    state = orion.state()
    assert con in _stale(state)
    assert _shown_stale(state, con) is True
    assert _root(state) not in _stale(state)


def test_8_the_replacement_serves_the_unchanged_root() -> None:
    orion = Orion()
    seeded = _seed(orion, root_basis=(orion.window,))
    root, req = _root(seeded), _one(seeded, SemanticKind.REQUIREMENT, "thirty")
    new_claim = orion.correct_window()
    after = _apply(
        orion,
        [
            _node(
                "req-window-2",
                "REQUIREMENT",
                "Refund requests are accepted for fourteen days.",
                disposition="REPLACES_STALE",
                replaces=_existing(req),
            )
        ],
        [
            _edge("req-window-2", "DERIVED_FROM", _basis(new_claim)),
            _edge("req-window-2", "SERVES", _existing(root)),
        ],
    )
    replacement = _one(after, SemanticKind.REQUIREMENT, "fourteen")
    assert after.objects[req].lifecycle is LifecycleStatus.SUPERSEDED
    serves = {
        r.target_id
        for r in after.objects[replacement].relations
        if r.relation_type is RelationType.SERVES
    }
    assert serves == {root}
    assert [o.id for o in after.objects.values() if o.kind is SemanticKind.INTENT] == [root]
    assert root not in _stale(after) and replacement not in _stale(after)


def test_9_unrelated_children_are_untouched_by_the_correction() -> None:
    orion = Orion()
    seeded = _seed(orion, root_basis=(orion.window,))
    method = _one(seeded, SemanticKind.REQUIREMENT, "original payment")
    host = _one(seeded, SemanticKind.CONSTRAINT, "UK")
    orion.correct_window()
    state = orion.state()
    assert method not in _stale(state) and host not in _stale(state)
    assert state.objects[method] == seeded.objects[method]
    assert state.objects[host] == seeded.objects[host]


# --- 10-11: several grounding claims ---------------------------------------------------------


def test_10_one_of_several_root_claims_superseded_leaves_the_root_current() -> None:
    orion = Orion()
    root = _root(_seed(orion, root_basis=(orion.window, orion.method, orion.hosting)))
    orion.correct_window()
    state = orion.state()
    assert root not in _stale(state)
    assert state.objects[root].lifecycle is LifecycleStatus.ACTIVE


def test_11_every_root_claim_superseded_still_never_stales_or_retires_the_root() -> None:
    """Automatic claim-derived staleness never simulates an Intent amendment; that is D8."""
    orion = Orion()
    seeded = _seed(orion, root_basis=(orion.window, orion.method, orion.hosting))
    root = _root(seeded)
    orion.supersede("J-sup-window", "J-window")
    orion.supersede("J-sup-method", "J-method")
    orion.supersede("J-sup-host", "J-host")
    state = orion.state()
    assert root in derive_view(state.semantic).stale_ids, "premise: the plane marks it"
    assert root not in _stale(state)
    assert state.objects[root] == seeded.objects[root]
    assert all(r.retired_object_id != root for r in state.intent_synthesis.retirements)
    children = {o.id for o in state.objects.values() if o.kind is not SemanticKind.INTENT}
    assert {c for c in children if c.startswith(("REQ", "CON"))} <= _stale(state)


# --- 12-13: authority does not decide the law ------------------------------------------------


@pytest.mark.parametrize(
    ("author", "authority"),
    [(HUMAN_G, Authority.CANONICAL), (AI, Authority.PROPOSED)],
    ids=["human-authorised", "model-proposed"],
)
def test_12_13_the_law_is_the_same_for_every_root_authority(
    author: Any, authority: Authority
) -> None:
    orion = Orion()
    seeded = _seed(orion, root_basis=(orion.window,), author=author)
    root, req = _root(seeded), _one(seeded, SemanticKind.REQUIREMENT, "thirty")
    assert seeded.objects[root].authority is authority
    orion.correct_window()
    state = orion.state()
    assert root not in _stale(state) and req in _stale(state)
    assert _shown_stale(state, root) is False


# --- 14-15: replay and history ---------------------------------------------------------------


def test_14_replay_is_deterministic() -> None:
    orion = Orion()
    _seed(orion, root_basis=(orion.window,))
    orion.correct_window()
    events = orion.world.store.load(PROJECT)
    first, second = replay(PROJECT, events), replay(PROJECT, events)
    assert first == second
    assert derive_intent_view(first) == derive_intent_view(second)


def test_15_no_event_is_migrated_or_added_by_the_law() -> None:
    """The law is a current-view projection: the ledger is byte-identical with or without it."""
    orion = Orion()
    _seed(orion, root_basis=(orion.window,))
    orion.correct_window()
    events = orion.world.store.load(PROJECT)
    state = replay(PROJECT, events)
    assert [e.event.event_type for e in events] == [
        e.event.event_type for e in orion.world.store.load(PROJECT)
    ]
    plane = frozenset(derive_view(state.semantic).stale_ids)
    assert _stale(state) == plane - root_intent_ids(state)


# --- the root predicate -----------------------------------------------------------------------


def test_every_intent_is_a_root_whatever_its_authority_or_lifecycle() -> None:
    orion = Orion()
    state = _seed(orion, root_basis=(orion.window,))
    assert root_intent_ids(state) == frozenset({_root(state)})
    assert all(state.objects[i].kind is SemanticKind.INTENT for i in root_intent_ids(state))


def test_the_boundary_does_not_pass_staleness_through_the_root() -> None:
    """A boundary, not only an exemption: nothing reaches a descendant through a root."""
    from foundry.domain.derivation import DerivationEdge, stale_object_ids
    from foundry.domain.semantic_view import active_judgment_ids

    orion = Orion()
    root = _root(_seed(orion, root_basis=(orion.window,)))
    orion.correct_window()
    state = orion.state()
    through = DerivationEdge(child_id="X-under-root", parent_id=root, recorded_by_event_id="E")
    semantic = state.semantic.model_copy(
        update={"derivations": (*state.semantic.derivations, through)}
    )
    active = active_judgment_ids(semantic)
    assert "X-under-root" in stale_object_ids(semantic, active)
    bounded = stale_object_ids(semantic, active, staleness_boundary_ids=frozenset({root}))
    assert root not in bounded and "X-under-root" not in bounded


# --- Orion-shaped T1 -> T3 --------------------------------------------------------------------


def test_orion_shaped_t1_to_t3() -> None:
    """T1: a model-proposed root grounded on an operational claim. T3: that claim is corrected.

    The affected Requirement is stale and replaced under the normal law; the root stays current
    and not stale; later objects keep serving it; nothing forces a root-staleness gap."""
    orion = Orion()
    t1 = _seed(orion, root_basis=(orion.window,))
    root, req = _root(t1), _one(t1, SemanticKind.REQUIREMENT, "thirty")
    assert t1.objects[root].authority is Authority.PROPOSED

    new_claim = orion.correct_window()
    t3 = orion.state()
    assert req in _stale(t3) and root not in _stale(t3)
    request = compile_intent_graph_context(t3, scope=SCOPE).request
    assert request is not None
    stale_shown = {o.object_id for o in request.known_objects if o.is_stale}
    assert stale_shown == {req}, "the only reconciliation work is the operational object"

    after = _apply(
        orion,
        [
            _node(
                "req-window-2",
                "REQUIREMENT",
                "Refund requests are accepted for fourteen days.",
                disposition="REPLACES_STALE",
                replaces=_existing(req),
            ),
            _node("goal", "GOAL", "Refund requests are handled predictably."),
        ],
        [
            _edge("req-window-2", "DERIVED_FROM", _basis(new_claim)),
            _edge("req-window-2", "SERVES", _existing(root)),
            _edge("goal", "DERIVED_FROM", _basis(new_claim)),
            _edge("goal", "SERVES", _existing(root)),
        ],
    )
    live_stale = {
        i for i in _stale(after) if i in after.objects and after.objects[i].lifecycle is ACTIVE
    }
    assert live_stale == set(), "only the retired Requirement (and its issue version) stay stale"
    assert req in _stale(after) and after.objects[req].lifecycle is LifecycleStatus.SUPERSEDED
    assert [o.id for o in after.objects.values() if o.kind is SemanticKind.INTENT] == [root]
    assert not [g for g in after.gaps.values() if root in g.affected_object_ids]
    assert after.objects[root] == t1.objects[root]


# --- one view for every intended-state reader -------------------------------------------------


def test_no_production_reader_of_intent_state_bypasses_the_boundary() -> None:
    """``derive_view(<state>.semantic)`` would read staleness without the root boundary. Every
    production reader holding ``IntentState`` goes through ``derive_intent_view``; plain
    ``derive_view`` stays only where the semantic plane is all there is (IE2), and in the
    byte-frozen v1 handoff (I11), whose raw topological stale set the v2 gate never consults."""
    import ast
    from pathlib import Path

    offenders: list[str] = []
    for path in sorted(Path("src/foundry").rglob("*.py")):
        if "experiments" in path.parts or path.name == "intent_view.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "derive_view"
                and node.args
                and isinstance(node.args[0], ast.Attribute)
                and node.args[0].attr == "semantic"
            ):
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_the_v2_delivery_gate_partitions_staleness_with_the_boundary() -> None:
    """v1 is byte-frozen and topological; v2 decides delivery from the bounded view."""
    import inspect

    import foundry.application.handoff_v2 as handoff_v2

    source = inspect.getsource(handoff_v2.build_intent_decision_handoff_v2)
    assert "derive_intent_view(state)" in source
    assert "derive_view(" not in source
