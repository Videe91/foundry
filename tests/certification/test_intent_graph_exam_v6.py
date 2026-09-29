"""IE3 certification exam v6: the root-Intent lifecycle (case K), offline.

A root Intent is a staleness boundary (IE3 §17.2): correcting a claim the root cites leaves the
root current, and the stale child beneath it is replaced under the existing law. Exam v5 never
examined a root grounded on a corrected claim, so it cannot certify the lifecycle the production
system now has. Exam v6 keeps every v5 case byte-identical and adds case K. Runtime-v4 is
unchanged: its root rule ("never add an INTENT when one is already shown"; SERVES through shown
existing nodes; "never replace an INTENT") already decides K once the root is shown fresh.

No live call is made here. Every answer is scripted and runs the full production path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import tests.certification._intent_graph_exam as exam
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYSTEM_INSTRUCTION,
    IntentGraphDraftPayload,
)
from foundry.domain.common import RelationType
from foundry.domain.gaps import GapKind
from foundry.domain.semantic import SemanticKind
from foundry.domain.semantic_view import derive_view
from tests.certification._exam_identity import canonical_digest
from tests.certification._intent_graph_exam import (
    SUPERSEDED_GRAPH_EXAMS,
    build_graph_case_k,
    graph_certificate_standing,
    graph_unresolved_work,
)
from tests.certification._intent_synthesis_exam import SCOPE, state_of
from tests.certification.test_intent_graph_exam_harness import (
    CORRECT,
    _gap,
    attempt,
    fails,
    passes,
)
from tests.unit._ie3_fixtures import b, e, edge, local, node

K = SemanticKind
S = RelationType.SERVES
D = RelationType.DERIVED_FROM
MANIFESTS = Path(__file__).parent / "exam_manifests"
EVIDENCE = Path(__file__).parent / "evidence"
EXAM_V5_SHA = "b8fe070ebddb580721fb4b741d43d3da276b59e40e0ee5840fb13b37ce43a90d"
FOURTEEN = "Refund requests are accepted within 14 days of purchase."


def _replacement(s: Any, **extra: Any) -> Any:
    return node(
        K.REQUIREMENT,
        "req",
        statement=FOURTEEN,
        disposition="REPLACES_STALE",
        replaces=e(s.object_ids["old"]),
        **extra,
    )


def _with(**update: Any) -> Any:
    def answer(s: Any) -> object:
        draft = CORRECT["K"](s)
        assert isinstance(draft, IntentGraphDraftPayload)
        values = {k: v(s) if callable(v) else v for k, v in update.items()}
        return draft.model_copy(update=values)

    return answer


# --------------------------------------------------------------------------- the world


def test_k_the_world_grounds_the_root_on_the_claim_that_is_corrected() -> None:
    """K asks its question only if the root cites the corrected claim and the plane marks it."""
    s = build_graph_case_k()
    state = state_of(s.store)
    root, old = s.object_ids["root"], s.object_ids["old"]
    parents = {edge.parent_id for edge in state.semantic.derivations if edge.child_id == root}
    assert parents == {s.claim_ids["old"]}, "the root's provenance is the old claim"
    plane = frozenset(derive_view(state.semantic).stale_ids)
    assert {root, old} <= plane, "under the pre-§17.2 law the root would read stale"
    assert state.objects[root].authority.value == "PROPOSED"
    assert [o.id for o in state.objects.values() if o.kind is K.INTENT] == [root]


def test_k_integrity_the_root_is_shown_fresh_and_the_child_stale() -> None:
    s = build_graph_case_k()
    from foundry.application.intent_graph_synthesis_context import compile_intent_graph_context

    request = compile_intent_graph_context(state_of(s.store), scope=SCOPE).request
    assert request is not None
    shown = {o.object_id: o for o in request.known_objects}
    assert set(shown) == {s.object_ids["root"], s.object_ids["old"]}
    assert shown[s.object_ids["root"]].is_stale is False
    assert shown[s.object_ids["old"]].is_stale is True
    live = {c.claim_id for locus in request.basis for c in locus.live_claims}
    assert live == {s.claim_ids["corrected"]}
    assert request.root_intent_ids == (), "a PROPOSED root is shown, never listed as canonical"


def test_k_declares_no_unresolved_work() -> None:
    s = build_graph_case_k()
    work = graph_unresolved_work("K", s)
    assert work.regions == ()
    assert work.resolved == frozenset({s.claim_ids["corrected"], s.object_ids["old"]})


# --------------------------------------------------------------------------- lawful answers


def test_k_the_replacement_beneath_the_same_root_passes() -> None:
    passes("K", CORRECT["K"])


def test_k_a_replacement_serving_the_root_through_a_new_goal_passes() -> None:
    def through_goal(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(
                _replacement(s),
                node(K.GOAL, "goal", statement="Refund requests are handled predictably."),
            ),
            relations=(
                edge("req", S, local("goal")),
                edge("req", D, b(s.claim_ids["corrected"])),
                edge("goal", S, e(s.object_ids["root"])),
                edge("goal", D, b(s.claim_ids["corrected"])),
            ),
        )

    passes("K", through_goal)


def test_k_a_passing_attempt_leaves_the_root_unchanged_current_and_alone() -> None:
    observation, s = attempt("K", CORRECT["K"])
    from foundry.domain.intent_view import derive_intent_view

    root = s.object_ids["root"]
    after = observation.after
    assert after.objects[root] == observation.before.objects[root]
    assert root not in derive_intent_view(after).stale_ids
    assert [o.id for o in after.objects.values() if o.kind is K.INTENT] == [root]
    parents = {edge.parent_id for edge in after.semantic.derivations if edge.child_id == root}
    assert parents == {s.claim_ids["old"]}, "provenance survives the correction and the graph"


# --------------------------------------------------------------------------- unlawful answers


def test_k_a_root_staleness_gap_beside_the_replacement_fails() -> None:
    fails(
        "K",
        _with(gaps=lambda s: (_gap("root", GapKind.MISSING_INFORMATION, e(s.object_ids["root"])),)),
        "gap",
    )


def test_k_a_root_gap_citing_the_corrected_claim_fails() -> None:
    fails(
        "K",
        _with(
            gaps=lambda s: (
                _gap(
                    "root",
                    GapKind.AMBIGUITY,
                    e(s.object_ids["root"]),
                    b(s.claim_ids["corrected"]),
                ),
            )
        ),
        "gap",
    )


def test_k_a_second_root_is_refused() -> None:
    def second_root(s: Any) -> object:
        draft = CORRECT["K"](s)
        assert isinstance(draft, IntentGraphDraftPayload)
        root2 = node(K.INTENT, "root2", mission="Operate refunds under the corrected window.")
        return draft.model_copy(
            update={
                "nodes": (*draft.nodes, root2),
                "relations": (*draft.relations, edge("root2", D, b(s.claim_ids["corrected"]))),
            }
        )

    fails("K", second_root, "MULTIPLE_ROOTS")


def test_k_a_replacement_root_cannot_even_be_expressed() -> None:
    with pytest.raises(ValueError, match="cannot be replaced"):
        node(
            K.INTENT,
            "root2",
            mission="A new purpose.",
            disposition="REPLACES_STALE",
            replaces=e("INT-anything"),
        )


def test_k_witnessing_the_root_fails() -> None:
    fails("K", _with(unchanged_object_refs=lambda s: (e(s.object_ids["root"]),)), "witness")


def test_k_a_new_node_instead_of_the_replacement_fails() -> None:
    def parallel(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(node(K.REQUIREMENT, "req", statement=FOURTEEN),),
            relations=(
                edge("req", S, e(s.object_ids["root"])),
                edge("req", D, b(s.claim_ids["corrected"])),
            ),
        )

    fails("K", parallel, "exactly one REPLACES_STALE")


def test_k_a_replacement_that_serves_nothing_is_refused() -> None:
    fails(
        "K",
        _with(relations=lambda s: (edge("req", D, b(s.claim_ids["corrected"])),)),
        "NO_RELEVANCE",
    )


def test_k_a_replacement_keeping_the_old_window_fails() -> None:
    def thirty(s: Any) -> object:
        draft = CORRECT["K"](s)
        assert isinstance(draft, IntentGraphDraftPayload)
        (req,) = draft.nodes
        kept = req.model_copy(
            update={"statement": "Refund requests are accepted within 30 days of purchase."}
        )
        return draft.model_copy(update={"nodes": (kept,)})

    fails("K", thirty, "fourteen-day window")


def test_k_integrity_fails_closed_under_the_pre_boundary_law(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the production view stopped treating the root as a boundary, K refuses to score."""
    import foundry.application.intent_graph_synthesis_context as context
    import foundry.domain.intent_view as intent_view

    def plane(state: Any) -> Any:
        return derive_view(state.semantic)

    monkeypatch.setattr(context, "derive_intent_view", plane)
    monkeypatch.setattr(intent_view, "derive_intent_view", plane)
    with pytest.raises(AssertionError, match="EXAM INTEGRITY"):
        passes("K", CORRECT["K"])


def test_the_prompt_already_states_the_root_rule_k_relies_on() -> None:
    text = " ".join(GRAPH_SYSTEM_INSTRUCTION.split())
    assert "never add an INTENT when one is already shown" in text
    assert "through your new nodes and/or shown existing nodes" in text
    assert "Never replace an INTENT or an ASSUMPTION" in text


# --------------------------------------------------------------------------- identity and history


def test_exam_v5_is_frozen_and_every_v5_case_is_unchanged() -> None:
    v5 = json.loads((MANIFESTS / "ie3-graph-exam-v5.json").read_text())
    assert canonical_digest(v5) == EXAM_V5_SHA
    v6 = exam.graph_exam_manifest()
    assert sorted(v6["cases"]) == sorted([*v5["cases"], "K"])
    assert all(v5["cases"][c] == v6["cases"][c] for c in v5["cases"])


def test_exam_v5_is_superseded_by_the_root_lifecycle() -> None:
    (v5,) = [s for s in SUPERSEDED_GRAPH_EXAMS if s.exam_version == "5"]
    assert (v5.exam_sha256, v5.superseded_by) == (EXAM_V5_SHA, "6")
    assert "staleness boundary" in v5.defect
    assert v5.not_a_precedent_for == "ROOT_INTENT_LIFECYCLE"


@pytest.mark.parametrize(
    ("relative", "verdict", "passed", "standing"),
    [
        ("openai/gpt-6-astra", "PASS", 30, "SUPERSEDED"),
        ("anthropic/claude-opus-5-5", "PASS", 30, "SUPERSEDED"),
        ("anthropic/claude-sonnet-5", "PASS", 30, "SUPERSEDED"),
        ("anthropic/claude-fable-5-1", "PASS", 30, "SUPERSEDED"),
        ("xai/grok-4.7", "NOT CERTIFIED", 29, "NOT_CERTIFIED"),
    ],
)
def test_every_exam_v5_record_is_historical_and_certifies_nothing_current(
    relative: str, verdict: str, passed: int, standing: str
) -> None:
    record = json.loads(
        (EVIDENCE / relative / "intent_graph_synthesis_exam_v5/certification.json").read_text()
    )
    assert (record["verdict"], record["passed_attempts"], record["exam_version"]) == (
        verdict,
        passed,
        "5",
    )
    assert record["policy_version"] == "intent-graph-synthesis-runtime-v4"
    assert graph_certificate_standing(record) == standing
    identity = exam.ModelIdentity(provider=record["provider"], model=record["model"])
    assert not exam.certificate_binds(record, **exam._current_graph_identity(identity))


def test_astras_v5_certificate_matches_everything_but_the_exam() -> None:
    """Prompt, policy, schemas and wire are byte-identical; only the exam moved, and with it the
    certificate's authority. Nothing in the record was rewritten."""
    record = json.loads(
        (
            EVIDENCE / "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/certification.json"
        ).read_text()
    )
    current = exam._current_graph_identity(
        exam.ModelIdentity(provider=record["provider"], model=record["model"])
    )
    same = ("policy_id", "policy_version", "prompt_sha256", "canonical_schema_sha256")
    assert all(record[k] == current[k] for k in same)
    assert record["wire_schema_sha256"] == current["wire_schema_sha256"]
    assert record["exam_sha256"] == EXAM_V5_SHA != current["exam_sha256"]


# --------------------------------------------------------------------------- the scorer on its own
#
# Production validation already refuses a second root and an irrelevant node, so those answers
# never reach the scorer through the full path. The scorer still states each law itself, proved
# here on observations that bypass validation.


def _scored_with(**changes: Any) -> None:
    from dataclasses import replace

    from tests.certification._intent_graph_exam import score_case_k

    observation, s = attempt("K", CORRECT["K"])
    score_case_k(observation, s)  # the untouched observation passes
    score_case_k(replace(observation, **{k: v(observation, s) for k, v in changes.items()}), s)


def test_k_scorer_refuses_a_new_intent_node_on_its_own() -> None:
    def with_root(o: Any, s: Any) -> Any:
        extra = node(K.INTENT, "root2", mission="A second purpose.")
        return o.result.model_copy(update={"nodes": (*o.result.nodes, extra)})

    with pytest.raises(exam.ExamFailure, match="new Intent node"):
        _scored_with(result=with_root)


def test_k_scorer_refuses_a_replacement_that_does_not_serve_the_root_on_its_own() -> None:
    def unserved(o: Any, s: Any) -> Any:
        kept = tuple(r for r in o.result.relations if r.relation_type is not S)
        return o.result.model_copy(update={"relations": kept})

    with pytest.raises(exam.ExamFailure, match="does not serve the existing root"):
        _scored_with(result=unserved)


def test_k_scorer_refuses_a_changed_root_on_its_own() -> None:
    def changed(o: Any, s: Any) -> Any:
        root = s.object_ids["root"]
        objects = dict(o.after.objects)
        objects[root] = objects[root].model_copy(update={"mission": "A different purpose."})
        return o.after.model_copy(update={"objects": objects})

    with pytest.raises(exam.ExamFailure, match="did not survive unchanged"):
        _scored_with(after=changed)
