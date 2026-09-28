"""IE3 runtime-v4 gap semantics and certification exam v5.

A read-only audit of exam v4 (2026-09-28) found two defects, both below any one model:

* **The model-facing gap contract never said what a gap is.** Runtime-v3 required a gap for an
  UNRESOLVED meaning and allowed "any lawful combination", but never distinguished decision-
  relevant unresolved work from a caveat, and never said that a meaning already resolved as
  PARAPHRASE, CORRECTION or NEW takes no gap. Every model gap is blocking (IE3 §19), so a caveat
  emitted as a gap blocks closure for nothing (Constitution, Law 9).
* **Case B's address still carried the default facet "How long may a refund take?"** beside a
  refund-request-window claim and requirement, the defect exam v4 had removed from case F only.
  Cases E and H share that substrate.

And the scorers treated gaps inconsistently: B and F rejected any gap, C tolerated one beside a
replacement, A/E/H/I tolerated anything.

Runtime-v4 states the gap contract. Exam v5 corrects the shared substrate, adds case J (one
meaning resolved, a distinct meaning genuinely unresolved) and scores every case's gaps with one
rule: a gap passes because the case leaves that region unresolved, and fails because it does
not. Each case declares its unresolved regions and the meanings it resolves; nothing reads text.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import tests.certification._intent_graph_exam as exam
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYSTEM_INSTRUCTION,
    IntentGraphDraftPayload,
    IntentGraphGapDraft,
)
from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
from foundry.adapters.model_runtime.anthropic_graph_wire import parse_graph_wire
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.model_runtime.xai import XAIModelProvider
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import BasisClaimRef
from foundry.domain.semantic import SemanticKind
from tests.certification._exam_identity import canonical_digest
from tests.certification._intent_graph_exam import (
    GRAPH_CASES,
    SUPERSEDED_GRAPH_EXAMS,
    build_graph_case_b,
    build_graph_case_b_v4,
    graph_certificate_standing,
    graph_unresolved_work,
)
from tests.certification.test_intent_graph_exam_harness import (
    CORRECT,
    _gap,
    _request,
    attempt,
    fails,
    passes,
)
from tests.unit._ie3_fixtures import b, e, edge, local, node
from tests.unit.adapters.model_runtime._anthropic_graph_forms import to_wire

K = SemanticKind
S = exam.RelationType.SERVES
D = exam.RelationType.DERIVED_FROM
MANIFESTS = Path(__file__).parent / "exam_manifests"
EVIDENCE = Path(__file__).parent / "evidence"
V4_SHA = "2c676e555286577284e6d50116b99b43f6527ef1c595b7faa4b84b5929442519"
RUNTIME_V3_PROMPT = "504b6080656253630d1c1e752ed499a23b864cf2ff290ca190941b94db140e5b"
RUNTIME_V4_PROMPT = "fd395605ecd12f39430a9bb0140bf1a3ce6dc43643859e94485a23970856a6e4"
Answer = Callable[[Any], object]


def _plus_gap(answer: Answer, kind: GapKind, *anchors: Any) -> Answer:
    """``answer`` with one more gap; an anchor may be a function of the substrate."""

    def wrapped(s: Any) -> object:
        draft = answer(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        resolved = tuple(a(s) if callable(a) else a for a in anchors)
        extra = _gap(f"g{len(draft.gaps)}", kind, *resolved)
        return draft.model_copy(update={"gaps": (*draft.gaps, extra)})

    return wrapped


def _claim(key: str) -> Callable[[Any], BasisClaimRef]:
    return lambda s: b(s.claim_ids[key])


_j_correct: Answer = CORRECT["J"]
"""Case J's lawful answer: the payment claim resolved as NEW, the completion time gapped."""


# --------------------------------------------------------------------------- 1-15 gap semantics


def test_1_a_witness_only_answer_passes() -> None:
    passes("B", CORRECT["B"])


def test_2_a_witness_plus_a_speculative_gap_fails() -> None:
    fails(
        "B",
        _plus_gap(
            CORRECT["B"], GapKind.MISSING_INFORMATION, _claim("refund"), e("INTENT-payments")
        ),
        "gap",
    )


def test_3_a_correct_replacement_passes() -> None:
    passes("F", CORRECT["F"])


def test_4_a_correct_replacement_plus_a_speculative_unit_gap_fails() -> None:
    fails("F", _plus_gap(CORRECT["F"], GapKind.AMBIGUITY, _claim("restated")), "gap")


def test_5_a_fully_resolved_new_node_passes() -> None:
    passes("A", CORRECT["A"])


def test_6_a_new_node_plus_an_unrelated_gap_fails() -> None:
    fails("A", _plus_gap(CORRECT["A"], GapKind.MISSING_INFORMATION, e("GOAL-refunds")), "gap")


def test_7_a_genuinely_unresolved_meaning_takes_a_gap() -> None:
    passes("D", CORRECT["D"])


def test_7b_choosing_a_value_instead_of_a_gap_leaves_the_region_uncovered() -> None:
    def chosen(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(node(K.REQUIREMENT, "pick", statement="Refunds complete within thirty days."),),
            relations=(
                edge("pick", S, e("GOAL-refunds")),
                edge("pick", D, b(s.claim_ids["thirty"])),
            ),
        )

    fails("D", chosen, "has no gap")


def test_8_a_genuine_contradiction_gap_passes() -> None:
    passes("G", CORRECT["G"])


def test_9_a_mixed_answer_across_two_distinct_meanings_passes() -> None:
    passes("J", _j_correct)


def test_9b_the_mixed_case_rejects_resolving_the_unresolved_meaning() -> None:
    def invented(s: Any) -> object:
        draft = _j_correct(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        choice = node(
            K.REQUIREMENT,
            "fast",
            statement="Refunds must complete within seven calendar days after approval.",
        )
        return draft.model_copy(
            update={
                "nodes": (*draft.nodes, choice),
                "relations": (
                    *draft.relations,
                    edge("fast", S, e("GOAL-refunds")),
                    edge("fast", D, b(s.claim_ids["seven"])),
                ),
            }
        )

    fails("J", invented, "invented a choice")


def test_9c_the_mixed_case_rejects_dropping_the_unresolved_meaning() -> None:
    def resolved_only(s: Any) -> object:
        draft = _j_correct(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        return draft.model_copy(update={"gaps": ()})

    fails("J", resolved_only, "has no gap")


def test_10_a_mixed_answer_whose_gap_duplicates_the_resolved_meaning_fails() -> None:
    fails("J", _plus_gap(_j_correct, GapKind.AMBIGUITY, _claim("payment")), "gap")

    def duplicate_instead(s: Any) -> object:
        draft = _j_correct(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        return draft.model_copy(
            update={"gaps": (_gap("pay-doubt", GapKind.AMBIGUITY, b(s.claim_ids["payment"])),)}
        )

    fails("J", duplicate_instead, "gap")


def test_10b_a_gap_anchored_to_the_resolved_node_is_a_duplicate_too() -> None:
    fails("J", _plus_gap(_j_correct, GapKind.AMBIGUITY, local("pay")), "gap")


def test_10c_a_gap_on_the_resolving_node_fails_even_beside_the_open_region() -> None:
    """Anchoring the open conflict too does not launder a caveat about the resolved meaning."""
    fails(
        "J",
        _plus_gap(_j_correct, GapKind.AMBIGUITY, local("pay"), _claim("seven")),
        "resolves",
    )


def test_10d_a_node_that_replaces_a_resolved_object_is_itself_resolved() -> None:
    """Directly on the rule: a replacement of a resolved object resolves it, whatever it cites."""
    observation, substrate = attempt(
        "F",
        _plus_gap(CORRECT["F"], GapKind.AMBIGUITY, local("req"), _claim("restated")),
    )
    work = exam.UnresolvedWork(
        frozenset({"REQ-stale"}),
        (exam.UnresolvedRegion(frozenset({substrate.claim_ids["restated"]})),),
    )
    with pytest.raises(exam.ExamFailure, match="resolves"):
        exam._require_gap_semantics(observation, work)


def test_11_a_gap_anchored_only_to_an_unrelated_object_fails() -> None:
    fails("D", _plus_gap(CORRECT["D"], GapKind.MISSING_INFORMATION, e("GOAL-refunds")), "gap")


def test_12_a_gap_with_valid_ids_but_no_unresolved_decision_fails() -> None:
    fails("B", _plus_gap(CORRECT["B"], GapKind.AMBIGUITY, e("REQ-existing")), "gap")


def test_13_a_hypothetical_doubt_unsupported_by_the_material_does_not_qualify() -> None:
    fails("A", _plus_gap(CORRECT["A"], GapKind.AMBIGUITY, _claim("refund")), "gap")


def test_14_missing_information_that_cannot_change_the_graph_does_not_qualify() -> None:
    fails("H", _plus_gap(CORRECT["H"], GapKind.MISSING_INFORMATION, e("INTENT-payments")), "gap")


def test_15_missing_information_that_prevents_a_decision_qualifies() -> None:
    def partial(s: Any) -> object:
        draft = _j_correct(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        only = _gap("which", GapKind.MISSING_INFORMATION, b(s.claim_ids["thirty"]))
        return draft.model_copy(update={"gaps": (only,)})

    passes("J", partial)


# --------------------------------------------------------------------------- one rule, every case


NO_UNRESOLVED_WORK = ("A", "B", "C", "E", "F", "H", "I")


def test_every_case_declares_its_unresolved_work() -> None:
    assert GRAPH_CASES == ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J")
    for case_id in GRAPH_CASES:
        work = graph_unresolved_work(case_id, exam.GRAPH_BUILDERS[case_id]())
        assert bool(work.regions) is (case_id not in NO_UNRESOLVED_WORK), case_id
        for region in work.regions:
            assert not region.ids & work.resolved, case_id


@pytest.mark.parametrize("case_id", GRAPH_CASES)
def test_every_scorer_rejects_a_gap_that_anchors_no_unresolved_region(case_id: str) -> None:
    answer = CORRECT[case_id]
    fails(case_id, _plus_gap(answer, GapKind.AMBIGUITY, e("GOAL-refunds")), "gap")


@pytest.mark.parametrize("case_id", NO_UNRESOLVED_WORK)
def test_every_resolved_case_rejects_a_gap_on_its_resolved_meaning(case_id: str) -> None:
    def on_resolved(s: Any) -> object:
        draft = CORRECT[case_id](s)
        assert isinstance(draft, IntentGraphDraftPayload)
        claim = sorted(graph_unresolved_work(case_id, s).resolved)[0]
        anchor = b(claim) if claim.startswith("CLAIM-") else e(claim)
        return draft.model_copy(update={"gaps": (_gap("doubt", GapKind.AMBIGUITY, anchor),)})

    fails(case_id, on_resolved, "gap")


def test_c_no_longer_tolerates_a_speculative_gap_beside_its_replacement() -> None:
    """Exam v4 passed this in C and failed it in F. Now both fail, for one reason."""
    fails("C", _plus_gap(CORRECT["C"], GapKind.AMBIGUITY, _claim("corrected")), "gap")


# --------------------------------------------------------------------------- 16-17 case B fixture


def _shown_b(builder: Callable[[], Any]) -> tuple[dict[str, Any], str]:
    original = exam.GRAPH_BUILDERS["B"]
    exam.GRAPH_BUILDERS["B"] = builder
    try:
        request = _request("B")
    finally:
        exam.GRAPH_BUILDERS["B"] = original
    ((locus, claim),) = [(lo, c) for lo in request.basis for c in lo.live_claims]
    (existing,) = [o for o in request.known_objects if o.object_id == "REQ-existing"]
    shown = {
        "subject": locus.subject,
        "facet": locus.facet,
        "predicate": claim.predicate,
        "value": claim.value.text,
    }
    return shown, existing.text


def test_16_case_b_shows_one_proposition_everywhere() -> None:
    shown, existing = _shown_b(build_graph_case_b)
    assert shown == {
        "subject": "Refund request window",
        "facet": "Within how many days of purchase may refund requests be made?",
        "predicate": "refund_request_window",
        "value": "refund requests may be made up to thirty days after purchase",
    }
    assert existing == "Refund requests are accepted within 30 days of purchase."
    visible = " ".join([*shown.values(), existing]).lower()
    assert "how long" not in visible and "take" not in visible and "complete" not in visible


def test_16b_the_shared_substrate_is_corrected_for_e_and_h_too() -> None:
    for case_id in ("E", "H"):
        facets = {locus.facet for locus in _request(case_id).basis}
        assert "How long may a refund take?" not in facets, case_id


def test_17_the_v4_case_b_fixture_is_pinned_as_historically_ambiguous() -> None:
    shown, existing = _shown_b(build_graph_case_b_v4)
    assert shown["facet"] == "How long may a refund take?"  # a duration question
    assert shown["subject"] == "Refund window" and shown["predicate"] == "refund_window"
    assert "refund requests" in shown["value"] and "refund requests" in existing.lower()


# --------------------------------------------------------------------------- 18-20 Fable's shapes


def _recorded(case_id: str, attempt_no: int) -> dict[str, Any]:
    path = EVIDENCE / "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/certification.json"
    record = json.loads(path.read_text())
    (hit,) = [a for a in record["attempts"] if (a["case"], a["attempt"]) == (case_id, attempt_no)]
    return dict(hit["raw_draft"])


def _transplant(draft: dict[str, Any], claim_key: str) -> Answer:
    """The recorded answer, with its one basis claim re-addressed to this exam's claim id.

    Case B's claim id moved with its corrected address; every other field is kept as recorded.
    """

    def answer(s: Any) -> object:
        text = json.dumps(draft)
        for old in {
            a["claim_id"] for g in draft["gaps"] for a in g["anchors"] if a.get("claim_id")
        }:
            text = text.replace(old, s.claim_ids[claim_key])
        return IntentGraphDraftPayload.model_validate_json(text)

    return answer


@pytest.mark.parametrize("attempt_no", [1, 2])
def test_18_19_fables_recorded_b_shapes_are_indefensible_under_the_new_contract(
    attempt_no: int,
) -> None:
    fails("B", _transplant(_recorded("B", attempt_no), "refund"), "resolves")
    without_gap = {**_recorded("B", attempt_no), "gaps": []}
    passes("B", _transplant(without_gap, "refund"))


def test_20_fables_recorded_f1_gap_violates_the_new_rule() -> None:
    recorded = _recorded("F", 1)
    fails("F", _transplant(recorded, "restated"), "resolves")
    passes("F", _transplant({**recorded, "gaps": []}, "restated"))


def test_18_20_the_prompt_states_the_rule_those_shapes_break() -> None:
    assert "Never pair a resolved meaning with a gap about that same meaning" in (
        " ".join(GRAPH_SYSTEM_INSTRUCTION.split())
    )


# --------------------------------------------------------------------------- 21 legitimate gaps


def test_21_the_legitimate_d_and_g_gaps_remain_valid() -> None:
    passes("D", CORRECT["D"])
    passes("G", CORRECT["G"])
    passes("D", _plus_gap(CORRECT["D"], GapKind.CONTRADICTION, _claim("seven"), e("GOAL-refunds")))


def test_21b_g_still_requires_the_contradiction_on_the_non_goal() -> None:
    fails(
        "G",
        lambda s: IntentGraphDraftPayload(
            gaps=(_gap("g", GapKind.AMBIGUITY, b(s.claim_ids["digital"])),)
        ),
        "CONTRADICTION",
    )


def test_21d_g_needs_the_contradiction_kind_on_the_right_anchor() -> None:
    """Right anchor, wrong kind; right kind, wrong anchor: each alone leaves G uncovered."""
    fails(
        "G",
        lambda s: IntentGraphDraftPayload(
            gaps=(_gap("g", GapKind.AMBIGUITY, e("NG-digital"), b(s.claim_ids["digital"])),)
        ),
        "CONTRADICTION",
    )
    fails(
        "G",
        lambda s: IntentGraphDraftPayload(
            gaps=(_gap("g", GapKind.CONTRADICTION, b(s.claim_ids["digital"])),)
        ),
        "NG-digital",
    )


def test_21c_every_recorded_d_and_g_gap_of_exam_v4_is_still_a_lawful_gap() -> None:
    """Across every v4 contestant: the unresolved regions (D's two claims, G's NonGoal) did not
    move, so every recorded D and G gap still anchors one and none anchors a resolved meaning."""
    for record_path in sorted(
        EVIDENCE.glob("*/*/intent_graph_synthesis_exam_v4/certification.json")
    ):
        record = json.loads(record_path.read_text())
        for recorded in record["attempts"]:
            if recorded["case"] in ("D", "G") and recorded.get("raw_draft"):
                answer = IntentGraphDraftPayload.model_validate(recorded["raw_draft"])
                passes(recorded["case"], lambda s, answer=answer: answer)


# --------------------------------------------------------------------------- 22-23 provider parity


def _canonical_gap_description() -> str:
    return str(IntentGraphGapDraft.model_json_schema()["description"])


def test_22_every_provider_wire_carries_the_same_gap_meaning() -> None:
    canonical = _canonical_gap_description()
    assert "blocking" in canonical
    openai = OpenAIModelProvider.wire_schema(IntentGraphDraftPayload)
    xai = XAIModelProvider.wire_schema(IntentGraphDraftPayload)
    anthropic = AnthropicModelProvider.wire_schema(IntentGraphDraftPayload)
    assert openai["$defs"]["IntentGraphGapDraft"]["description"] == canonical
    assert xai["$defs"]["IntentGraphGapDraft"]["description"] == canonical
    assert anthropic["properties"]["gaps"]["items"]["description"] == canonical


def test_22b_no_wire_states_a_gap_rule_of_its_own() -> None:
    """Gap semantics live in the provider-neutral prompt; wires carry schema descriptions only."""
    for wire in (
        OpenAIModelProvider.wire_schema(IntentGraphDraftPayload),
        XAIModelProvider.wire_schema(IntentGraphDraftPayload),
        AnthropicModelProvider.wire_schema(IntentGraphDraftPayload),
    ):
        text = json.dumps(wire).lower()
        for rule in ("caveat", "speculative", "never pair", "decision cannot be made"):
            assert rule not in text


@pytest.mark.parametrize("case_id", GRAPH_CASES)
def test_23_every_correct_answer_survives_the_anthropic_wire_unchanged(case_id: str) -> None:
    answer = CORRECT[case_id]
    value = answer(exam.GRAPH_BUILDERS[case_id]())
    assert isinstance(value, IntentGraphDraftPayload)
    converted = parse_graph_wire(json.dumps(to_wire(value)))
    assert IntentGraphDraftPayload.model_validate_json(json.dumps(converted)) == value


# --------------------------------------------------------------------------- 24 prompt hygiene


def test_24_the_prompt_names_no_model_provider_or_exam_answer() -> None:
    text = GRAPH_SYSTEM_INSTRUCTION.lower()
    for word in (
        "astra", "grok", "claude", "fable", "opus", "sonnet", "gpt", "openai", "anthropic",
        "xai", "refund", "thirty", "calendar", "business day", "digital", "uk-hosted",
        "req-", "claim-", "exam", "certification", "score",
    ):  # fmt: skip
        assert word not in text, word


def test_the_prompt_defines_a_gap_by_the_decision_it_blocks() -> None:
    text = " ".join(GRAPH_SYSTEM_INSTRUCTION.split())
    assert "WHAT A GAP IS" in text
    assert "Foundry records every gap as blocking" in text
    assert "would the graph you return change" in text
    assert "MIXED ANSWERS" in text and "GAP ANCHORS" in text


# --------------------------------------------------------------------------- identity and history


def test_exam_v4_is_frozen_and_reproducible() -> None:
    manifest = json.loads((MANIFESTS / "ie3-graph-exam-v4.json").read_text())
    assert canonical_digest(manifest) == V4_SHA
    assert manifest["exam_version"] == "4"


def test_exactly_the_shared_substrate_cases_moved_and_j_was_added() -> None:
    v4 = json.loads((MANIFESTS / "ie3-graph-exam-v4.json").read_text())
    v5 = exam.graph_exam_manifest()
    assert sorted(v5["cases"]) == sorted([*v4["cases"], "J"])
    moved = sorted(c for c in v4["cases"] if v4["cases"][c] != v5["cases"][c])
    assert moved == ["B", "E", "H"]


def test_exam_v4_is_superseded_and_its_gap_verdicts_are_no_precedent() -> None:
    (v4,) = [s for s in SUPERSEDED_GRAPH_EXAMS if s.exam_version == "4"]
    assert (v4.exam_sha256, v4.superseded_by) == (V4_SHA, "5")
    assert "case B" in v4.defect and "gap" in v4.defect
    assert v4.not_a_precedent_for == "GAP_BESIDE_A_RESOLVED_MEANING"


@pytest.mark.parametrize(
    ("relative", "verdict", "passed", "standing"),
    [
        ("openai/gpt-6-astra", "PASS", 27, "SUPERSEDED"),
        ("anthropic/claude-opus-5-5", "PASS", 27, "SUPERSEDED"),
        ("anthropic/claude-sonnet-5", "PASS", 27, "SUPERSEDED"),
        ("anthropic/claude-fable-5-1", "NOT CERTIFIED", 23, "NOT_CERTIFIED"),
        ("xai/grok-4.7", "NOT CERTIFIED", 17, "NOT_CERTIFIED"),
    ],
)
def test_every_exam_v4_record_is_historical_truth_and_binds_nothing_current(
    relative: str, verdict: str, passed: int, standing: str
) -> None:
    record = json.loads(
        (EVIDENCE / relative / "intent_graph_synthesis_exam_v4/certification.json").read_text()
    )
    assert (record["verdict"], record["passed_attempts"], record["exam_version"]) == (
        verdict,
        passed,
        "4",
    )
    assert record["policy_version"] == "intent-graph-synthesis-runtime-v3"
    assert graph_certificate_standing(record) == standing
    identity = exam.ModelIdentity(provider=record["provider"], model=record["model"])
    assert not exam.certificate_binds(record, **exam._current_graph_identity(identity))


def test_fables_v4_failures_stay_on_record() -> None:
    record = json.loads(
        (
            EVIDENCE
            / "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/certification.json"
        ).read_text()
    )
    failed = [(a["case"], a["attempt"]) for a in record["attempts"] if a["verdict"] == "FAIL"]
    assert failed == [("B", 1), ("B", 2), ("F", 1)]


def test_a_passing_j_attempt_leaves_one_blocking_gap_and_one_object() -> None:
    observation, _ = attempt("J", _j_correct)
    assert observation.record is not None and observation.record.compiled is not None
    assert len(observation.record.compiled.objects) == 1
    new_gaps = [g for g in observation.after.gaps.values() if g.id not in observation.before.gaps]
    assert len(new_gaps) == 1 and new_gaps[0].blocking is True
