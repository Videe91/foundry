"""IE3 graph certification exam v4: case F made unambiguous, and its scorer tightened.

Exam v3's case F (through commit 2f9f5d6) showed its restated claim as the bare value "thirty
days after purchase" under the default facet "How long may a refund take?", beside a stale
request-window Requirement whose basis link is not visible. A refund-duration reading was lawful
(runtime-v3 NEW rule) yet scored FAIL, as Grok's v3 F-2 was; and the scorer accepted any gap at
all. Exam v4 states the claim as the request-window proposition on a request-window address, so
the stale Requirement and the claim are visibly the same meaning, and it scores graph semantics
only: exactly one same-kind replacement of REQ-stale, grounded on the restated claim, no parallel
node, no gap. Runtime-v3, the prompt, the schemas and the compiler are unchanged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import tests.certification._intent_graph_exam as exam
from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
    IntentGraphDraftPayload,
)
from foundry.domain.gaps import GapKind
from foundry.domain.semantic import SemanticKind
from tests.certification._exam_identity import canonical_digest
from tests.certification._intent_graph_exam import (
    EXPECTED_GRAPH_EXAM_SHA256,
    GRAPH_EXAM_VERSION,
    SUPERSEDED_GRAPH_EXAMS,
    build_graph_case_f,
    build_graph_case_f_v3,
    graph_certificate_standing,
    graph_exam_sha256,
)
from tests.certification._intent_synthesis_exam import state_of
from tests.certification.test_intent_graph_exam_harness import (
    _gap,
    _request,
    attempt,
    fails,
    passes,
)
from tests.unit._ie3_fixtures import b, e, edge, node

K = SemanticKind
S = exam.RelationType.SERVES
D = exam.RelationType.DERIVED_FROM
MANIFESTS = Path(__file__).parent / "exam_manifests"
EVIDENCE = Path(__file__).parent / "evidence"
V3_SHA = "72ca1102d0734900689d3e3260df988f57786494871fde8b73767df79a7331e8"
V4_SHA = "2c676e555286577284e6d50116b99b43f6527ef1c595b7faa4b84b5929442519"

_REQUEST_WINDOW = re.compile(
    r"^refund requests are accepted (within|up to) (\d+|thirty) days (of|after) purchase\.?$",
    re.IGNORECASE,
)
"""Subject "refund requests", operation "are accepted", anchor "purchase"; only the phrasing
of the thirty-day bound varies. Used to check the fixture, never to score an answer."""


def _shown_f(builder: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """The one basis claim and the stale object exactly as a model is shown them."""
    import tests.certification._intent_graph_exam as module

    original = module.GRAPH_BUILDERS["F"]
    module.GRAPH_BUILDERS["F"] = builder
    try:
        request = _request("F")
    finally:
        module.GRAPH_BUILDERS["F"] = original
    ((locus, claim),) = [(lo, c) for lo in request.basis for c in lo.live_claims]
    shown = {
        "subject": locus.subject,
        "facet": locus.facet,
        "predicate": claim.predicate,
        "value": claim.value.text,
    }
    (stale,) = [o for o in request.known_objects if o.object_id == "REQ-stale"]
    return shown, {"text": stale.text, "is_stale": stale.is_stale, "kind": stale.kind}


# --------------------------------------------------------------------------- 9, 10 the fixture


def test_9_the_restated_claim_is_propositionally_complete() -> None:
    shown, stale = _shown_f(build_graph_case_f)
    assert _REQUEST_WINDOW.match(shown["value"]), shown["value"]
    assert _REQUEST_WINDOW.match(stale["text"].replace("30", "thirty")), stale["text"]
    assert stale["is_stale"] is True and stale["kind"] is K.REQUIREMENT


def test_10_the_facet_asks_about_request_eligibility_not_duration() -> None:
    shown, _ = _shown_f(build_graph_case_f)
    assert shown["facet"] == "Within how many days of purchase are refund requests accepted?"
    assert shown["subject"] == "Refund request window"
    assert shown["predicate"] == "refund_request_window"
    assert "how long" not in shown["facet"].lower()


def test_red_the_v3_fixture_admitted_a_duration_reading() -> None:
    """Why Grok's v3 F-2 was defensible: pinned, never re-scored."""
    shown, stale = _shown_f(build_graph_case_f_v3)
    assert shown["value"] == "thirty days after purchase"  # a bare value
    assert shown["facet"] == "How long may a refund take?"  # a duration question
    assert not _REQUEST_WINDOW.match(shown["value"])
    assert _REQUEST_WINDOW.match(stale["text"].replace("30", "thirty"))


def test_the_old_duration_interpretation_is_no_longer_supported_by_anything_visible() -> None:
    """Structural, not model-specific: every visible element now states the request window."""
    shown, stale = _shown_f(build_graph_case_f)
    visible = " ".join([*map(str, shown.values()), stale["text"]]).lower()
    assert "how long" not in visible and "take" not in visible and "complete" not in visible
    assert "refund requests" in shown["value"] and "refund requests" in shown["facet"].lower()


def test_both_claims_of_the_restatement_share_one_address_and_one_meaning() -> None:
    substrate = build_graph_case_f()
    claims = state_of(substrate.store).semantic.claims
    old, restated = claims[substrate.claim_ids["old"]], claims[substrate.claim_ids["restated"]]
    assert old.address_id == restated.address_id
    assert old.predicate == restated.predicate == "refund_request_window"
    for claim in (old, restated):
        assert _REQUEST_WINDOW.match(claim.value.text or ""), claim.value.text


# --------------------------------------------------------------------------- the scorer


def _replacement(
    target: str = "REQ-stale",
    statement: str = "Refund requests are accepted up to thirty days after purchase.",
    kind: SemanticKind = K.REQUIREMENT,
) -> Any:
    def answer(s: Any) -> object:
        extra = {"facet": "PROJECT_BOUNDARY"} if kind is K.CONSTRAINT else {}
        return IntentGraphDraftPayload(
            nodes=(
                node(
                    kind,
                    "window",
                    statement=statement,
                    disposition="REPLACES_STALE",
                    replaces=e(target),
                    **extra,
                ),
            ),
            relations=(
                edge("window", S, e("GOAL-refunds")),
                edge("window", D, b(s.claim_ids["restated"])),
            ),
        )

    return answer


def _new_parallel(rationale: str = "A new requirement records the claimed window.") -> Any:
    def answer(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(
                node(
                    K.REQUIREMENT,
                    "window",
                    statement="Refund requests are accepted up to thirty days after purchase.",
                    proposal_rationale=rationale,
                ),
            ),
            relations=(
                edge("window", S, e("GOAL-refunds")),
                edge("window", D, b(s.claim_ids["restated"])),
            ),
        )

    return answer


def _with_gap(answer: Any, *anchors: Any) -> Any:
    def wrapped(s: Any) -> object:
        draft = answer(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        resolved = tuple(a(s) if callable(a) else a for a in anchors)
        return draft.model_copy(update={"gaps": (_gap("g", GapKind.AMBIGUITY, *resolved),)})

    return wrapped


def _unrelated_gap(s: Any) -> object:
    return IntentGraphDraftPayload(
        gaps=(_gap("g", GapKind.MISSING_INFORMATION, e("GOAL-refunds")),)
    )


def test_1_the_correct_replacement_passes() -> None:
    passes("F", _replacement())
    passes("F", _replacement(statement="Refund requests are accepted within 30 days of purchase."))


def test_2_a_plain_new_parallel_requirement_fails() -> None:
    fails("F", _new_parallel(), "exactly one REPLACES_STALE")


def test_3_new_plus_an_unrelated_gap_fails() -> None:
    fails("F", _with_gap(_new_parallel(), e("GOAL-refunds")), "gap")


def test_4_an_unrelated_gap_alone_fails() -> None:
    fails("F", _unrelated_gap, "gap")


def test_5_even_a_properly_anchored_ambiguity_gap_fails_because_none_remains() -> None:
    """Every visible element states one proposition; a gap would stand in for the replacement."""

    def anchored(s: Any) -> object:
        return IntentGraphDraftPayload(
            gaps=(_gap("g", GapKind.AMBIGUITY, b(s.claim_ids["restated"]), e("REQ-stale")),)
        )

    fails("F", anchored, "gap")


def test_5b_a_correct_replacement_plus_a_gap_fails() -> None:
    fails("F", _with_gap(_replacement(), e("GOAL-refunds")), "gap")


def test_6_naming_the_stale_object_in_a_rationale_is_not_a_replacement() -> None:
    fails(
        "F",
        _new_parallel("This supersedes the stale requirement REQ-stale on the same subject."),
        "exactly one REPLACES_STALE",
    )


@pytest.mark.parametrize(
    ("target", "law"),
    [
        ("GOAL-refunds", "REPLACEMENT_KIND_MISMATCH"),
        ("REQ-dead", "INVISIBLE_EXISTING_REF"),
        ("REQ-missing", "INVISIBLE_EXISTING_REF"),
    ],
)
def test_7_a_replacement_of_the_wrong_object_fails(target: str, law: str) -> None:
    fails("F", _replacement(target=target), law)


def test_8_the_right_relation_with_the_wrong_meaning_fails() -> None:
    fails(
        "F",
        _replacement(statement="Refund requests are accepted within fourteen days of purchase."),
        "lost the window",
    )
    fails("F", _replacement(kind=K.CONSTRAINT), "REPLACEMENT_KIND_MISMATCH")


def test_the_grok_v3_f2_answer_shape_fails_in_v4_on_graph_structure() -> None:
    """NEW beside the stale object: now contrary to what the fixture visibly states."""

    def duration(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(
                node(K.REQUIREMENT, "w", statement="A refund may take thirty days after purchase."),
            ),
            relations=(edge("w", S, e("GOAL-refunds")), edge("w", D, b(s.claim_ids["restated"]))),
        )

    fails("F", duration, "exactly one REPLACES_STALE")


def test_the_replacement_retires_req_stale_durably() -> None:
    observation, _ = attempt("F", _replacement())
    retired = [r.retired_object_id for r in observation.after.intent_synthesis.retirements]
    assert "REQ-stale" in retired


# --------------------------------------------------------------------------- identity


def test_exam_v4_identity_is_frozen_and_superseded_by_v5() -> None:
    """Exam v4 is history now (runtime-v4 and exam v5 are current); its manifest is its identity."""
    v4 = json.loads((MANIFESTS / "ie3-graph-exam-v4.json").read_text())
    assert canonical_digest(v4) == V4_SHA != V3_SHA
    assert v4["exam_version"] == "4"
    assert GRAPH_EXAM_VERSION == "5"
    assert graph_exam_sha256() == EXPECTED_GRAPH_EXAM_SHA256 != V4_SHA
    assert GRAPH_SYNTHESIS_POLICY_VERSION == "intent-graph-synthesis-runtime-v4"
    assert GRAPH_SYSTEM_INSTRUCTION_SHA256 != (
        "504b6080656253630d1c1e752ed499a23b864cf2ff290ca190941b94db140e5b"
    )


@pytest.mark.parametrize(
    ("version", "sha"),
    [
        ("2", "813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c"),
        ("3", V3_SHA),
        ("4", V4_SHA),
    ],
)
def test_earlier_exams_are_frozen_and_reproducible(version: str, sha: str) -> None:
    manifest = json.loads((MANIFESTS / f"ie3-graph-exam-v{version}.json").read_text())
    assert canonical_digest(manifest) == sha
    assert manifest["exam_version"] == version


def test_only_case_f_moved_between_v3_and_v4() -> None:
    v3 = json.loads((MANIFESTS / "ie3-graph-exam-v3.json").read_text())
    v4 = json.loads((MANIFESTS / "ie3-graph-exam-v4.json").read_text())
    assert sorted(v3["cases"]) == sorted(v4["cases"])
    changed_worlds = [c for c in v3["cases"] if v3["cases"][c] != v4["cases"][c]]
    assert changed_worlds == ["F"]
    changed_code = {
        k for k in set(v3["code"]) | set(v4["code"]) if v3["code"].get(k) != v4["code"].get(k)
    }
    assert changed_code <= {
        "tests.certification._intent_graph_exam.build_graph_case_f",
        "tests.certification._intent_graph_exam.score_case_f",
        "tests.certification._intent_graph_exam:F_REQUEST_WINDOW_FACET",
        "tests.certification._intent_graph_exam:F_REQUEST_WINDOW_SUBJECT",
        "tests.certification._intent_graph_exam:F_OLD_CLAIM",
        "tests.certification._intent_graph_exam:F_RESTATED_CLAIM",
        "tests.certification._intent_graph_exam:F_OLD_EVIDENCE",
        "tests.certification._intent_graph_exam:F_RESTATED_EVIDENCE",
    }, changed_code
    assert v3["acceptance"]["rule"] == v4["acceptance"]["rule"]


# --------------------------------------------------------------------------- history


def _record(relative: str) -> dict[str, Any]:
    return json.loads((EVIDENCE / relative).read_text())


def test_exam_v3_is_recorded_as_superseded_with_its_case_f_defect() -> None:
    (v3,) = [s for s in SUPERSEDED_GRAPH_EXAMS if s.exam_version == "3"]
    assert (v3.exam_sha256, v3.superseded_by) == (V3_SHA, "4")
    assert "case F" in v3.defect
    assert v3.not_a_precedent_for == "STALE_OBJECT_UNDER_AN_AMBIGUOUS_CLAIM"


def test_astra_v3_certificate_is_historical_pass_now_superseded() -> None:
    record = _record("openai/gpt-6-astra/intent_graph_synthesis_exam_v3/certification.json")
    assert (record["verdict"], record["passed_attempts"], record["exam_version"]) == (
        "PASS",
        27,
        "3",
    )
    assert graph_certificate_standing(record) == "SUPERSEDED"


def test_grok_v3_record_stays_not_certified_diagnostic() -> None:
    record = _record("xai/grok-4.7/intent_graph_synthesis_exam_v3/certification.json")
    assert (record["verdict"], record["passed_attempts"]) == ("NOT CERTIFIED", 20)
    assert graph_certificate_standing(record) == "NOT_CERTIFIED"
    failed = [(a["case"], a["attempt"]) for a in record["attempts"] if a["verdict"] == "FAIL"]
    assert failed == [("F", 1), ("F", 2)]


@pytest.mark.parametrize(
    "relative",
    [
        "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/certification.json",
        "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/certification.json",
        "xai/grok-4.7/intent_graph_synthesis_exam_v3/certification.json",
    ],
)
def test_no_earlier_record_binds_exam_v4(relative: str) -> None:
    record = _record(relative)
    identity = exam.ModelIdentity(provider=record["provider"], model=record["model"])
    assert not exam.certificate_binds(record, **exam._current_graph_identity(identity))
