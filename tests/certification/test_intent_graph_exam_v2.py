"""IE3 graph certification exam v2: the corrected case C, and certificates bound to their exam.

Exam v1's case C (through commit 5e88489) joined two propositions. REQ-old said when a refund
*request* is accepted ("within 30 days of purchase"); its basis claim, its address facet and the
correction said how long a refund takes to *complete* ("within ... calendar days"). Replacing
REQ-old was one defensible reading, not the only one, and GPT-6 Astra named the mismatch in all
three runs. The historical 21/24 record stays exactly as it is. Here the exam is corrected, the
defect is pinned, and a certificate now names the exact exam it was earned on.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

import tests.certification._intent_graph_exam as exam
from foundry.adapters.intent_graph_synthesis.model_runtime import IntentGraphDraftPayload
from foundry.domain.gaps import GapKind
from foundry.domain.semantic import SemanticKind
from foundry.model_runtime.domain import ModelIdentity, ModelTask
from tests.certification._exam_identity import source_fingerprint
from tests.certification._intent_graph_exam import (
    C_CORRECTED_EVIDENCE,
    C_OLD_EVIDENCE,
    EXPECTED_GRAPH_EXAM_SHA256,
    GRAPH_CERTIFICATION_RECORD_FORMAT,
    GRAPH_EXAM_ID,
    GRAPH_EXAM_VERSION,
    build_graph_case_c,
    build_graph_case_c_v1,
    certificate_binds,
    graph_exam_sha256,
    record_format,
    schema_bound_certificate_binds,
)
from tests.certification._intent_synthesis_exam import state_of
from tests.certification.test_intent_graph_exam_harness import (
    CORRECT,
    _gap,
    _new_answer,
    fails,
    passes,
)
from tests.unit._ie3_fixtures import b, e, edge, node

K = SemanticKind

# --------------------------------------------------------------------------- propositions

_REQUEST_WINDOW = re.compile(
    r"^refund requests are accepted within (?P<value>\d+|thirty|fourteen) days of purchase\.?$",
    re.IGNORECASE,
)
"""The one proposition of corrected case C: subject "refund requests", operation "are accepted",
anchor "of purchase"; only the day count varies."""


def _propositions(builder: Any) -> dict[str, str]:
    """Every text in the case that states or frames the disputed requirement."""
    substrate = builder()
    state = state_of(substrate.store)
    old = state.semantic.claims[substrate.claim_ids["old"]]
    corrected = state.semantic.claims[substrate.claim_ids["corrected"]]
    return {
        "REQ-old statement": state.objects["REQ-old"].statement,
        "old claim evidence": state.semantic.evidence[old.evidence_ids[0]].content,
        "corrected claim evidence": state.semantic.evidence[corrected.evidence_ids[0]].content,
        "old claim text": old.value.text or "",
        "corrected claim text": corrected.value.text or "",
        "address facet": state.semantic.addresses[old.address_id].facet,
        "same address": str(old.address_id == corrected.address_id),
    }


def test_red_the_historical_case_c_joined_two_different_propositions() -> None:
    """Why the historical Astra answers were defensible. Not a re-score of that record."""
    texts = _propositions(build_graph_case_c_v1)
    assert _REQUEST_WINDOW.match(texts["REQ-old statement"])  # request accepted, 30 days
    for key in ("old claim evidence", "corrected claim evidence"):
        assert not _REQUEST_WINDOW.match(texts[key]), texts[key]
        assert re.search(r"must complete within", texts[key])  # completion time
    assert texts["address facet"] == "How long may a refund take?"  # completion framing
    assert "purchase" not in texts["old claim evidence"] + texts["corrected claim evidence"]


def test_corrected_case_c_is_one_proposition_with_one_changed_value() -> None:
    texts = _propositions(build_graph_case_c)
    values = {}
    for key in ("REQ-old statement", "old claim evidence", "corrected claim evidence"):
        match = _REQUEST_WINDOW.match(texts[key])
        assert match, f"{key} is not the request-window proposition: {texts[key]!r}"
        values[key] = match.group("value")
    assert values["REQ-old statement"] == values["old claim evidence"] == "30"
    assert values["corrected claim evidence"] == "14"
    for key, number in (("old claim text", "thirty"), ("corrected claim text", "fourteen")):
        assert _REQUEST_WINDOW.match(texts[key] + "."), texts[key]
        assert number in texts[key]
    assert texts["address facet"] == (
        "Within how many days of purchase are refund requests accepted?"
    )
    assert texts["same address"] == "True"
    assert "complete" not in " ".join(texts.values()).lower()
    assert (
        texts["old claim evidence"],
        texts["corrected claim evidence"],
    ) == (C_OLD_EVIDENCE, C_CORRECTED_EVIDENCE)


def test_corrected_case_c_shows_req_old_stale_and_only_the_corrected_claim() -> None:
    from tests.certification.test_intent_graph_exam_harness import _claims, _shown

    assert _shown("C")["REQ-old"].is_stale is True
    substrate = build_graph_case_c()
    assert substrate.claim_ids["corrected"] in _claims("C")
    assert substrate.claim_ids["old"] not in _claims("C")


# --------------------------------------------------------------------------- the scorer


def _replacement(target: str) -> Any:
    def answer(s: Any) -> object:
        return IntentGraphDraftPayload(
            nodes=(
                node(
                    K.REQUIREMENT,
                    "req",
                    statement="Refund requests are accepted within 14 days of purchase.",
                    disposition="REPLACES_STALE",
                    replaces=e(target),
                ),
            ),
            relations=(
                edge("req", exam.RelationType.SERVES, e("GOAL-refunds")),
                edge("req", exam.RelationType.DERIVED_FROM, b(s.claim_ids["corrected"])),
            ),
        )

    return answer


def test_2_the_lawful_answer_replaces_req_old() -> None:
    passes("C", CORRECT["C"])
    passes("C", _replacement("REQ-old"))


def test_3_a_separate_new_requirement_fails() -> None:
    fails(
        "C",
        _new_answer("corrected", "Refund requests are accepted within 14 days of purchase."),
        "REPLACES_STALE",
    )


def test_4_an_ambiguity_gap_fails() -> None:
    fails(
        "C",
        lambda s: IntentGraphDraftPayload(
            gaps=(_gap("window", GapKind.AMBIGUITY, b(s.claim_ids["corrected"]), e("REQ-old")),)
        ),
        "REPLACES_STALE|resolved meaning takes no gap",  # exam v5 reports the gap rule first
    )


def test_5_no_change_fails() -> None:
    fails(
        "C",
        lambda s: IntentGraphDraftPayload(unchanged_object_refs=(e("REQ-old"),)),
        "UNCHANGED_REF_STALE",
    )


@pytest.mark.parametrize(
    ("target", "law"),
    [
        ("GOAL-refunds", "REPLACEMENT_KIND_MISMATCH"),
        ("INTENT-payments", "REPLACEMENT_KIND_MISMATCH"),
        ("REQ-missing", "INVISIBLE_EXISTING_REF"),
    ],
)
def test_6_a_wrong_replacement_target_fails(target: str, law: str) -> None:
    fails("C", _replacement(target), law)


@pytest.mark.parametrize("extra", ["INTENT-payments", "GOAL-refunds"])
def test_7_an_extra_context_witness_fails(extra: str) -> None:
    def answer(s: Any) -> object:
        draft = _replacement("REQ-old")(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        return draft.model_copy(update={"unchanged_object_refs": (e(extra),)})

    fails("C", answer, "witness set")


def test_8_referencing_the_retiring_target_is_refused() -> None:
    """Replacing REQ-old and anchoring a gap on it in the same answer is refused, not repaired."""

    def answer(s: Any) -> object:
        draft = _replacement("REQ-old")(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        return draft.model_copy(update={"gaps": (_gap("old", GapKind.AMBIGUITY, e("REQ-old")),)})

    from tests.certification.test_intent_graph_exam_harness import attempt

    observation, _ = attempt("C", answer)
    assert observation.governance_error is not None
    assert "RETIRING_TARGET_REFERENCED" in observation.governance_error
    fails("C", answer, "RETIRING_TARGET_REFERENCED")


def test_8b_declaring_stale_req_old_unchanged_is_refused() -> None:
    def answer(s: Any) -> object:
        draft = _replacement("REQ-old")(s)
        assert isinstance(draft, IntentGraphDraftPayload)
        return draft.model_copy(update={"unchanged_object_refs": (e("REQ-old"),)})

    fails("C", answer, "UNCHANGED_REF_STALE")


# --------------------------------------------------------------------------- exam identity


def test_9_the_exam_hash_is_deterministic_and_pinned() -> None:
    assert graph_exam_sha256() == graph_exam_sha256() == EXPECTED_GRAPH_EXAM_SHA256
    assert (GRAPH_EXAM_ID, GRAPH_EXAM_VERSION) == (
        "ie3.intent-graph-synthesis.certification-exam",
        "5",
    )  # v2 is frozen in exam_manifests/ and recorded in SUPERSEDED_GRAPH_EXAMS


def test_building_a_world_between_hashes_does_not_move_it() -> None:
    before = graph_exam_sha256()
    for builder in exam.GRAPH_BUILDERS.values():
        builder()
    assert graph_exam_sha256() == before


def test_10_changing_any_case_world_changes_the_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = graph_exam_sha256()
    monkeypatch.setitem(exam.GRAPH_BUILDERS, "C", build_graph_case_c_v1)
    assert graph_exam_sha256() != baseline
    monkeypatch.setitem(exam.GRAPH_BUILDERS, "C", build_graph_case_c)

    def other_same_thing() -> Any:
        substrate = exam._same_thing_substrate()
        exam._ingest(substrate.governor, "EV-extra", "An unrelated remark.")
        return substrate

    monkeypatch.setitem(exam.GRAPH_BUILDERS, "B", other_same_thing)
    assert graph_exam_sha256() != baseline


def test_10b_changing_seeded_world_data_changes_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = graph_exam_sha256()
    monkeypatch.setattr(
        exam, "C_CORRECTED_EVIDENCE", "Refund requests are accepted within 7 days of purchase."
    )
    assert graph_exam_sha256() != baseline


def test_11_changing_a_scorer_changes_the_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = graph_exam_sha256()

    def lenient_c(observation: Any, substrate: Any) -> None:
        return None

    monkeypatch.setitem(exam.SCORERS, "C", lenient_c)
    assert graph_exam_sha256() != baseline


def test_11b_changing_a_shared_scoring_helper_changes_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = graph_exam_sha256()
    monkeypatch.setattr(exam, "SAME_THING", "Refund requests are accepted within 31 days.")
    assert graph_exam_sha256() != baseline


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GRAPH_RUNS_PER_CASE", 2),
        ("GRAPH_CASES", ("A", "B", "C", "D", "E", "F", "G")),
        ("GRAPH_ACCEPTANCE_RULE", "most runs pass"),
    ],
)
def test_12_changing_the_acceptance_rule_changes_the_hash(
    monkeypatch: pytest.MonkeyPatch, name: str, value: Any
) -> None:
    baseline = graph_exam_sha256()
    monkeypatch.setattr(exam, name, value)
    assert graph_exam_sha256() != baseline


def test_12b_changing_the_verdict_function_changes_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = graph_exam_sha256()
    original = exam.graph_verdict

    def majority(attempts: list[dict[str, Any]]) -> str:
        return "PASS" if sum(a["verdict"] == "PASS" for a in attempts) > 12 else "NOT CERTIFIED"

    monkeypatch.setattr(exam, "graph_verdict", majority)
    assert graph_exam_sha256() != baseline
    monkeypatch.setattr(exam, "graph_verdict", original)
    assert graph_exam_sha256() == baseline


def test_13_formatting_comments_and_docstrings_do_not_move_the_fingerprint() -> None:
    plain = "def f(x):\n    return x + 1\n"
    decorated = (
        "def f(x):\n"
        '    """A docstring that says nothing executable."""\n'
        "    # a comment\n"
        "\n"
        "    return (x\n"
        "            + 1)\n"
    )
    changed = "def f(x):\n    return x + 2\n"
    assert source_fingerprint(plain) == source_fingerprint(decorated)
    assert source_fingerprint(plain) != source_fingerprint(changed)


# --------------------------------------------------------------------------- binding

ASTRA = ModelIdentity(provider="openai", model="gpt-6-astra")


def _v3_record(**overrides: Any) -> dict[str, Any]:
    from tests.certification.test_intent_graph_exam_harness import RECORD

    record = {
        **RECORD,
        "record_format": GRAPH_CERTIFICATION_RECORD_FORMAT,
        "exam_id": GRAPH_EXAM_ID,
        "exam_version": GRAPH_EXAM_VERSION,
        "exam_sha256": EXPECTED_GRAPH_EXAM_SHA256,
    }
    record.update(overrides)
    return record


def _identity(**overrides: Any) -> dict[str, Any]:
    from tests.certification.test_intent_graph_exam_harness import (
        CANONICAL_SHA,
        OPENAI_WIRE_SHA,
    )
    from tests.certification.test_intent_graph_exam_harness import (
        OpenAIModelProvider as Provider,
    )

    fields: dict[str, Any] = {
        "identity": ASTRA,
        "task": ModelTask.INTENT_GRAPH_SYNTHESIS,
        "policy_id": exam.EXPECTED_GRAPH_POLICY_ID,
        "policy_version": exam.EXPECTED_GRAPH_POLICY_VERSION,
        "prompt_sha256": exam.EXPECTED_GRAPH_PROMPT_SHA256,
        "canonical_schema_sha256": CANONICAL_SHA,
        "wire_schema_sha256": OPENAI_WIRE_SHA,
        "wire_schema_compiler": Provider.WIRE_SCHEMA_COMPILER,
        "exam_id": GRAPH_EXAM_ID,
        "exam_version": GRAPH_EXAM_VERSION,
        "exam_sha256": EXPECTED_GRAPH_EXAM_SHA256,
    }
    fields.update(overrides)
    return fields


def test_14_a_passing_v3_record_binds_exactly_its_exam() -> None:
    assert certificate_binds(_v3_record(), **_identity())


@pytest.mark.parametrize(
    "override",
    [
        {"exam_sha256": "0" * 64},
        {"exam_sha256": "f7ffd9f3747c4a7541fed6293fd85de354bf771af95e95dd986ec6198c069697"},
        {"exam_version": "1"},
        {"exam_version": "6"},
        {"exam_id": "ie3.some-other-exam"},
    ],
    ids=lambda o: f"{next(iter(o))}={str(next(iter(o.values())))[:10]}",
)
def test_14_an_exam_hash_x_certificate_never_binds_exam_y(override: dict[str, Any]) -> None:
    assert not certificate_binds(_v3_record(), **_identity(**override))
    assert not certificate_binds(_v3_record(**override), **_identity())


@pytest.mark.parametrize("missing", ["exam_id", "exam_version", "exam_sha256", "record_format"])
def test_14_a_record_missing_any_exam_field_binds_nothing(missing: str) -> None:
    record = {k: v for k, v in _v3_record().items() if k != missing}
    assert not certificate_binds(record, **_identity())


def test_a_v2_record_never_binds_an_exam_bound_identity() -> None:
    v2_pass = {
        k: v
        for k, v in _v3_record(record_format="ie3-graph-certification.v2").items()
        if k not in ("exam_id", "exam_version", "exam_sha256")
    }
    assert record_format(v2_pass) == "ie3-graph-certification.v2"
    assert not certificate_binds(v2_pass, **_identity())
    historical = {k: v for k, v in _identity().items() if not k.startswith("exam_")}
    assert schema_bound_certificate_binds(v2_pass, **historical), "v2's own question still answers"
    assert not schema_bound_certificate_binds(_v3_record(), **historical)


def test_the_live_runners_freeze_the_exam() -> None:
    import inspect

    import tests.certification.test_gpt_6_astra_intent_graph_synthesis_live as astra
    import tests.certification.test_grok_4_7_intent_graph_synthesis_live as grok

    for runner in (astra, grok):
        source = inspect.getsource(runner.test_the_contestant_is_frozen)
        assert "graph_exam_sha256()" in source and "EXPECTED_GRAPH_EXAM_SHA256" in source


def test_the_record_writer_binds_the_exam(tmp_path: Any) -> None:
    from dataclasses import replace

    from tests.certification.test_intent_graph_exam_harness import CONTESTANT
    from tests.certification.test_intent_graph_exam_harness import (
        OpenAIModelProvider as Provider,
    )

    bound = replace(
        CONTESTANT,
        wire_schema=Provider.wire_schema,
        wire_schema_compiler=Provider.WIRE_SCHEMA_COMPILER,
        evidence_namespace=str(tmp_path / "record"),
    )
    payload = exam.write_graph_certification(bound, [], frozen_production_base="x")
    written = json.loads((tmp_path / "record" / "certification.json").read_text())
    assert written == payload
    assert payload["record_format"] == "ie3-graph-certification.v3"
    assert (payload["exam_id"], payload["exam_version"], payload["exam_sha256"]) == (
        GRAPH_EXAM_ID,
        GRAPH_EXAM_VERSION,
        EXPECTED_GRAPH_EXAM_SHA256,
    )
    assert payload["verdict"] == "NOT CERTIFIED"
