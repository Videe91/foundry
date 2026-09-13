"""9P3 T5: the typed leakage gate (spec §15, §15.1; T5 brief; clarifications 2-5).

The gate scans harness-authored, model-visible text -- the two frozen system
instructions plus nine structurally representative request skeletons rendered through
the real assembly functions and the real ``render_request`` over opaque stand-in
evidence -- for every sealed needle, each matched ONLY by its own kind's matcher:
``PROSE`` by the exact 9P2 C1 normalization, ``CANONICAL_LABEL`` and
``CHECKPOINT_LABEL`` as case-sensitive standalone identifier tokens on the raw text.
Evidence content is model-state, never harness text, so a needle placed in the
evidence stand-in content must NOT fail the gate, while the same needle placed in
static harness text MUST. The fifteen numbered regressions of the brief are the
individually named ``test_regression_NN_*`` functions. ZERO live calls; sockets are
blocked.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
)
from foundry.experiments.contrastive_unseen.leakage import normalize_leakage_text
from foundry.experiments.long_horizon_bounded import expectations as expectations_module
from foundry.experiments.long_horizon_bounded import leakage as leakage_module
from foundry.experiments.long_horizon_bounded.expectations import (
    BASELINE_MEANINGS,
    CHECKPOINTS,
    CURRENT_MEANING_BY_T,
    DECISION_NAMES,
    R_GRADING_RULES,
)
from foundry.experiments.long_horizon_bounded.leakage import (
    EXTRA_HARNESS_TEXT_PREFIX,
    REQUEST_PATH_MODULES,
    SKELETON_IDS,
    LeakageNeedle,
    LeakageResult,
    SkeletonRecord,
    SkeletonText,
    build_skeletons,
    matches,
    needle_set_sha256,
    needles,
    placeholder_evidence_content,
    render_skeletons,
    request_path_import_gate,
    run_leakage_gate,
    scan_skeletons,
    typed_needles,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    ARTIFACT_REFS,
    TIMELINE,
    evidence_id,
    reconstruction_corpus,
)

PACKAGE_DIR = Path("src/foundry/experiments/long_horizon_bounded")

REQUIRED_SKELETON_IDS = (
    "F_T1_CALL1",
    "F_CORRECTION_CALL1_TOUCHED",
    "F_CORRECTION_CALL2_TOUCHED",
    "F_RESTATEMENT_CALL1_TOUCHED",
    "F_RESTATEMENT_CALL2_TOUCHED",
    "A_CALL1_NO_CLAIMS",
    "A_CALL2_WITH_CLAIMS_NO_CONTEXT",
    "R_CUMULATIVE_CALL1",
    "R_CUMULATIVE_CALL2",
)

CLASS_LABELS = ("RESTATEMENT", "CORRECTION", "REVERT", "COMPATIBLE_EXTENSION", "SEMANTIC_NO_OP")
CHECKPOINT_LABELS = tuple(f"C{t:02d}" for t in range(2, 17))
INTEGRITY_LABELS = tuple(f"I{n}" for n in range(1, 16))
ERROR_LABELS = ("errors_F", "errors_A", "errors_R")
EXPECTED_CANONICAL = frozenset({*CLASS_LABELS, *DECISION_NAMES, *INTEGRITY_LABELS, *ERROR_LABELS})
EXPECTED_PROSE = frozenset(
    {
        *(c.expected_current_meaning for c in CHECKPOINTS),
        *(line for c in CHECKPOINTS for line in c.requirements),
        *BASELINE_MEANINGS.values(),
        *(m for by_locus in CURRENT_MEANING_BY_T.values() for m in by_locus.values()),
        *R_GRADING_RULES,
    }
)

FIVE_KEYS = (
    "allowed_judgment_kinds",
    "evidence",
    "known_addresses",
    "known_claims",
    "comparison_context",
)
FOUR_KEYS = FIVE_KEYS[:4]

MEANING_C03 = CHECKPOINTS[1].expected_current_meaning
"""One hidden ``expected_current_meaning`` sentence (C03), used by regressions 9-10."""

IMPORT_FORMS = (
    "import foundry.experiments.long_horizon_bounded.expectations",
    "import foundry.experiments.long_horizon_bounded.expectations as e",
    "from foundry.experiments.long_horizon_bounded.expectations import select_architecture",
    "from foundry.experiments.long_horizon_bounded.expectations import GRADING_LABELS as L",
    "from foundry.experiments.long_horizon_bounded import expectations",
    "from foundry.experiments.long_horizon_bounded import select_architecture",
    "from foundry.experiments.long_horizon_bounded import timeline, expectations",
    "from .expectations import GRADING_LABELS",
    "from . import expectations",
    "from . import select_architecture",
    "from ..long_horizon_bounded.expectations import CHECKPOINTS",
    "from ..long_horizon_bounded import expectations",
)
"""The twelve answer-key import forms the request-path gate must reject."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _request_payload(text: str, instruction: str) -> dict[str, Any]:
    prefix = instruction + "\n"
    assert text.startswith(prefix)
    payload = json.loads(text[len(prefix) :])
    assert isinstance(payload, dict)
    return payload


def _instruction_for(skeleton_id: str) -> str:
    return SYSTEM_INSTRUCTION if skeleton_id.startswith("A_") else CONTRASTIVE_SYSTEM_INSTRUCTION


def _recipe(entries: list[str]) -> str:
    return _sha256("\x1e".join(sorted(entries)))


def _real_sources() -> dict[str, str]:
    return {name: (PACKAGE_DIR / name).read_text(encoding="utf-8") for name in REQUEST_PATH_MODULES}


def _failed_on(result: LeakageResult, needle: str, kind: str) -> None:
    assert result.passed is False
    assert result.matched_needle == needle
    assert result.matched_needle_kind == kind
    assert result.matched_skeleton_id is not None


# --- needle inventory (clarification 3) --------------------------------------------


def test_typed_needles_assign_exactly_one_kind_per_value_and_cover_the_inventory() -> None:
    typed = typed_needles()
    assert all(isinstance(n, LeakageNeedle) for n in typed)
    by_kind: dict[str, set[str]] = {
        "PROSE": set(),
        "CANONICAL_LABEL": set(),
        "CHECKPOINT_LABEL": set(),
    }
    for needle in typed:
        by_kind[needle.kind].add(needle.value)
    assert by_kind["CHECKPOINT_LABEL"] == set(CHECKPOINT_LABELS)
    assert by_kind["CANONICAL_LABEL"] == EXPECTED_CANONICAL
    assert by_kind["PROSE"] == EXPECTED_PROSE
    # Exactly one kind per value: the three value sets are pairwise disjoint and the
    # values are unique across the tuple.
    values = [n.value for n in typed]
    assert len(values) == len(set(values))
    assert not (by_kind["PROSE"] & by_kind["CANONICAL_LABEL"])
    assert not (by_kind["PROSE"] & by_kind["CHECKPOINT_LABEL"])
    assert not (by_kind["CANONICAL_LABEL"] & by_kind["CHECKPOINT_LABEL"])
    # Deterministic order: sorted by (kind, value).
    assert list(typed) == sorted(typed, key=lambda n: (n.kind, n.value))
    assert typed == typed_needles()
    assert len(by_kind["CHECKPOINT_LABEL"]) == 15
    assert len(by_kind["CANONICAL_LABEL"]) == 5 + len(DECISION_NAMES) + 15 + 3


def test_needles_is_the_value_inventory_of_typed_needles() -> None:
    assert needles() == tuple(n.value for n in typed_needles())
    inventory = set(needles())
    for label in (*CHECKPOINT_LABELS, *CLASS_LABELS, *DECISION_NAMES):
        assert label in inventory
    for checkpoint in CHECKPOINTS:
        assert checkpoint.expected_current_meaning in inventory
        for line in checkpoint.requirements:
            assert line in inventory
    assert len(needles()) == len(EXPECTED_PROSE) + len(EXPECTED_CANONICAL) + len(CHECKPOINT_LABELS)


def test_needles_contain_no_orion_section_text() -> None:
    inventory = needles()
    for lifecycle in TIMELINE:
        for line in lifecycle.item.content.splitlines():
            stripped = line.strip("# ").strip()
            if stripped:
                assert stripped not in inventory
                assert not any(stripped in needle for needle in inventory)


def test_leakage_needle_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValueError):
        LeakageNeedle(value="x", kind="WORD")  # type: ignore[arg-type]


# --- typed matching law (clarification 2) -----------------------------------------


@pytest.mark.parametrize(
    ("value", "kind", "haystack", "expected"),
    [
        ("CORRECTION", "CANONICAL_LABEL", "CORRECTION", True),
        ("CORRECTION", "CANONICAL_LABEL", "a correction of a known claim", False),
        ("RESTATEMENT", "CANONICAL_LABEL", "RESTATEMENT", True),
        (
            "RESTATEMENT",
            "CANONICAL_LABEL",
            "never emit a duplicate assert_claim for a restatement",
            False,
        ),
        ("RESTATEMENT", "CANONICAL_LABEL", "x RESTATEMENT_ y", False),
        ("RESTATEMENT", "CANONICAL_LABEL", "(RESTATEMENT)", True),
        ("C02", "CHECKPOINT_LABEL", "C02", True),
        ("C02", "CHECKPOINT_LABEL", "checkpoint C02 failed", True),
        ("C02", "CHECKPOINT_LABEL", "EV-O-C02", False),
        ("C02", "CHECKPOINT_LABEL", "prefix-C02", False),
        ("C02", "CHECKPOINT_LABEL", "C02_suffix", False),
        ("C02", "CHECKPOINT_LABEL", "c02", False),
        ("C02", "CHECKPOINT_LABEL", '"C02"', True),
        ("Alpha  beta", "PROSE", "x ALPHA\tBETA y", True),
        ("Alpha beta", "PROSE", "alphabeta", False),
    ],
)
def test_matches_applies_exactly_the_kinds_matcher(
    value: str, kind: str, haystack: str, expected: bool
) -> None:
    needle = LeakageNeedle(value=value, kind=kind)  # type: ignore[arg-type]
    assert matches(needle, haystack) is expected


def test_prose_matching_is_c1_normalization_on_both_sides() -> None:
    needle = LeakageNeedle(value="  Maximum\tFOUR \n\n total attempts ", kind="PROSE")
    assert matches(needle, "x maximum four total attempts y") is True
    assert matches(needle, "x maximum four total attempts y") is False
    assert normalize_leakage_text(needle.value) == "maximum four total attempts"


def test_label_matching_never_casefolds_and_escapes_the_value() -> None:
    assert matches(LeakageNeedle(value="I1", kind="CANONICAL_LABEL"), "gate i1") is False
    assert matches(LeakageNeedle(value="I1", kind="CANONICAL_LABEL"), "gate I1.") is True
    assert matches(LeakageNeedle(value="I1", kind="CANONICAL_LABEL"), "gate I15") is False
    assert matches(LeakageNeedle(value="errors_F", kind="CANONICAL_LABEL"), "errors_F=1") is True
    assert matches(LeakageNeedle(value="errors_F", kind="CANONICAL_LABEL"), "errors_FA") is False
    assert matches(LeakageNeedle(value="a.b", kind="CANONICAL_LABEL"), "axb") is False


# --- skeletons (clarification 5) ---------------------------------------------------


def test_skeleton_ids_are_exactly_the_required_nine_in_order() -> None:
    assert SKELETON_IDS == REQUIRED_SKELETON_IDS
    assert tuple(build_skeletons()) == REQUIRED_SKELETON_IDS
    assert tuple(s.skeleton_id for s in render_skeletons()) == REQUIRED_SKELETON_IDS


def test_fr_skeletons_are_five_key_with_the_contrastive_instruction() -> None:
    skeletons = build_skeletons()
    for skeleton_id in REQUIRED_SKELETON_IDS:
        if skeleton_id.startswith("A_"):
            continue
        payload = _request_payload(skeletons[skeleton_id], CONTRASTIVE_SYSTEM_INSTRUCTION)
        assert tuple(payload) == FIVE_KEYS


def test_a_skeletons_are_four_key_with_the_historical_instruction() -> None:
    skeletons = build_skeletons()
    for skeleton_id in ("A_CALL1_NO_CLAIMS", "A_CALL2_WITH_CLAIMS_NO_CONTEXT"):
        payload = _request_payload(skeletons[skeleton_id], SYSTEM_INSTRUCTION)
        assert tuple(payload) == FOUR_KEYS
        assert "comparison_context" not in payload


def test_skeletons_cover_the_required_structural_shapes() -> None:
    skeletons = build_skeletons()
    contrastive = CONTRASTIVE_SYSTEM_INSTRUCTION
    a01, a02, a03 = (evidence_id(t, "A") for t in (1, 2, 3))

    t1 = _request_payload(skeletons["F_T1_CALL1"], contrastive)
    assert [e["evidence_id"] for e in t1["evidence"]] == [
        le.item.evidence_id for le in TIMELINE if le.t == 1
    ]
    assert all(e["supersedes_evidence_id"] is None for e in t1["evidence"])
    assert t1["comparison_context"]["transitions"] == []
    assert t1["allowed_judgment_kinds"] == ["BIND_TO_ADDRESS", "CREATE_ADDRESS"]

    correction_1 = _request_payload(skeletons["F_CORRECTION_CALL1_TOUCHED"], contrastive)
    (transition,) = correction_1["comparison_context"]["transitions"]
    assert transition["predecessor_evidence_id"] == a01
    assert transition["current_evidence_id"] == a02
    assert transition["artifact_ref"] == ARTIFACT_REFS["A"]
    assert len(transition["touched_claim_ids"]) == 1
    assert len(correction_1["known_claims"]) == 1

    correction_2 = _request_payload(skeletons["F_CORRECTION_CALL2_TOUCHED"], contrastive)
    assert correction_2["allowed_judgment_kinds"] == [
        "ASSERT_CLAIM",
        "CONFLICTS_WITH",
        "SUPERSEDE",
        "SUPPORTS_CLAIM",
    ]
    assert len(correction_2["known_addresses"]) == 1
    assert len(correction_2["known_claims"]) == 1

    restatement_1 = _request_payload(skeletons["F_RESTATEMENT_CALL1_TOUCHED"], contrastive)
    (restatement,) = restatement_1["comparison_context"]["transitions"]
    assert restatement["predecessor_evidence_id"] == a02
    assert restatement["current_evidence_id"] == a03
    (claim,) = restatement_1["known_claims"]
    assert a02 not in claim["evidence_ids"]

    restatement_2 = _request_payload(skeletons["F_RESTATEMENT_CALL2_TOUCHED"], contrastive)
    assert len(restatement_2["known_claims"]) == 1

    a_call1 = _request_payload(skeletons["A_CALL1_NO_CLAIMS"], SYSTEM_INSTRUCTION)
    assert len(a_call1["known_addresses"]) == 1
    assert a_call1["known_claims"] == []

    a_call2 = _request_payload(skeletons["A_CALL2_WITH_CLAIMS_NO_CONTEXT"], SYSTEM_INSTRUCTION)
    assert len(a_call2["known_claims"]) == 1

    r1 = _request_payload(skeletons["R_CUMULATIVE_CALL1"], contrastive)
    corpus_ids = [item.evidence_id for item in reconstruction_corpus(4, project_id="x")]
    assert [e["evidence_id"] for e in r1["evidence"]] == corpus_ids
    assert len(r1["comparison_context"]["transitions"]) == 36
    r2 = _request_payload(skeletons["R_CUMULATIVE_CALL2"], contrastive)
    assert len(r2["evidence"]) == len(corpus_ids)


def test_skeletons_are_deterministic() -> None:
    assert build_skeletons() == build_skeletons()
    assert render_skeletons() == render_skeletons()
    assert run_leakage_gate() == run_leakage_gate()


# --- the default gate ---------------------------------------------------------------


def test_default_gate_passes_on_frozen_prompts_and_real_skeletons() -> None:
    result = run_leakage_gate()
    assert isinstance(result, LeakageResult)
    assert result.passed is True
    assert result.needle_set_sha256 == needle_set_sha256()
    assert result.fr_prompt_sha256 == CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256
    assert result.fr_prompt_sha256 == _sha256(CONTRASTIVE_SYSTEM_INSTRUCTION)
    assert result.a_prompt_sha256 == SYSTEM_INSTRUCTION_SHA256
    assert result.a_prompt_sha256 == _sha256(SYSTEM_INSTRUCTION)
    assert tuple(s.skeleton_id for s in result.skeletons) == REQUIRED_SKELETON_IDS
    assert all(isinstance(s, SkeletonRecord) for s in result.skeletons)
    skeletons = build_skeletons()
    for text in skeletons.values():
        assert evidence_id(1, "A") in text
    assert evidence_id(4, "C") in skeletons["R_CUMULATIVE_CALL1"]


def test_result_is_frozen() -> None:
    result = run_leakage_gate()
    with pytest.raises(Exception, match="frozen"):
        result.passed = False  # type: ignore[misc]


def test_extra_harness_text_is_recorded_as_a_scanned_skeleton() -> None:
    result = run_leakage_gate(extra_harness_text=("opaque harness note",))
    assert result.passed is True
    ids = tuple(s.skeleton_id for s in result.skeletons)
    assert ids[: len(REQUIRED_SKELETON_IDS)] == REQUIRED_SKELETON_IDS
    assert ids[-1] == f"{EXTRA_HARNESS_TEXT_PREFIX}0"
    assert result.skeletons[-1].chars == len("opaque harness note")


# --- numbered typed-matching regressions (brief step 1) -----------------------------


def test_regression_01_canonical_correction_in_harness_text_fails() -> None:
    result = run_leakage_gate(extra_harness_text=("CORRECTION",))
    _failed_on(result, "CORRECTION", "CANONICAL_LABEL")


def test_regression_02_frozen_prompt_wording_correction_passes() -> None:
    assert run_leakage_gate(extra_harness_text=("a correction of a known claim is exactly",)).passed


def test_regression_03_canonical_restatement_in_harness_text_fails() -> None:
    result = run_leakage_gate(extra_harness_text=("RESTATEMENT",))
    _failed_on(result, "RESTATEMENT", "CANONICAL_LABEL")


def test_regression_04_frozen_prompt_wording_restatement_passes_and_prompts_carry_words() -> None:
    assert run_leakage_gate(
        extra_harness_text=("never emit a duplicate assert_claim for a restatement.",)
    ).passed
    for instruction in (CONTRASTIVE_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION):
        assert "restatement" in instruction
        assert "correction" in instruction
        assert "RESTATEMENT" not in instruction
        assert "CORRECTION" not in instruction
    assert run_leakage_gate().passed is True


def test_regression_05_checkpoint_label_in_harness_text_fails() -> None:
    result = run_leakage_gate(extra_harness_text=("C02",))
    _failed_on(result, "C02", "CHECKPOINT_LABEL")


def test_regression_06_checkpoint_label_inside_a_sentence_fails() -> None:
    result = run_leakage_gate(extra_harness_text=("checkpoint C02 failed",))
    _failed_on(result, "C02", "CHECKPOINT_LABEL")


def test_regression_07_evidence_id_ev_o_c02_passes_and_real_r_skeletons_carry_it() -> None:
    assert run_leakage_gate(extra_harness_text=("EV-O-C02",)).passed is True
    skeletons = build_skeletons()
    for skeleton_id in ("R_CUMULATIVE_CALL1", "R_CUMULATIVE_CALL2"):
        assert "EV-O-C02" in skeletons[skeleton_id]
        assert "EV-O-C04" in skeletons[skeleton_id]
        assert re.search(r"(?<![A-Za-z0-9_-])C02(?![A-Za-z0-9_-])", skeletons[skeleton_id]) is None
    result = run_leakage_gate()
    assert result.passed is True
    assert result.matched_skeleton_id is None


def test_regression_08_non_standalone_or_wrong_case_checkpoint_forms_pass() -> None:
    assert run_leakage_gate(extra_harness_text=("prefix-C02", "C02_suffix", "c02")).passed is True


def test_regression_09_prose_with_different_casing_and_doubled_whitespace_fails() -> None:
    variant = MEANING_C03.upper().replace(" ", "  ")
    assert variant != MEANING_C03
    result = run_leakage_gate(extra_harness_text=(f"harness note: {variant} end.",))
    _failed_on(result, MEANING_C03, "PROSE")
    assert result.matched_skeleton_id == f"{EXTRA_HARNESS_TEXT_PREFIX}0"


def test_regression_10_prose_inside_evidence_content_passes_but_in_harness_text_fails() -> None:
    def content(item_id: str) -> str:
        return f"{placeholder_evidence_content(item_id)} {MEANING_C03}"

    skeletons = render_skeletons(evidence_content=content)
    assert any(MEANING_C03 in s.model_visible_text for s in skeletons)
    assert not any(
        normalize_leakage_text(MEANING_C03) in normalize_leakage_text(s.harness_text)
        for s in skeletons
    )
    result = scan_skeletons(skeletons)
    assert result.passed is True
    assert result.matched_needle is None
    failed = scan_skeletons(skeletons, extra_harness_text=(f"note {MEANING_C03}",))
    _failed_on(failed, MEANING_C03, "PROSE")
    assert failed.matched_skeleton_id == f"{EXTRA_HARNESS_TEXT_PREFIX}0"
    assert run_leakage_gate(extra_harness_text=(MEANING_C03,)).passed is False


def test_regression_11_hash_equals_the_documented_recipe() -> None:
    entries = [f"{n.kind}\x00{n.value}" for n in typed_needles()]
    assert needle_set_sha256() == _recipe(entries)
    assert (
        needle_set_sha256()
        == hashlib.sha256("\x1e".join(sorted(entries)).encode("utf-8")).hexdigest()
    )
    assert re.fullmatch(r"[0-9a-f]{64}", needle_set_sha256())


def test_regression_12_hash_commits_to_kind_and_to_unnormalized_values() -> None:
    typed = typed_needles()
    baseline = _recipe([f"{n.kind}\x00{n.value}" for n in typed])
    assert baseline == needle_set_sha256()
    rekinded = [f"{'PROSE' if n.value == 'C02' else n.kind}\x00{n.value}" for n in typed]
    assert _recipe(rekinded) != baseline
    normalized = [f"{n.kind}\x00{normalize_leakage_text(n.value)}" for n in typed]
    assert _recipe(normalized) != baseline
    assert any(n.value != normalize_leakage_text(n.value) for n in typed)


def test_regression_13_hash_is_deterministic_and_order_independent() -> None:
    assert needle_set_sha256() == needle_set_sha256()
    typed = typed_needles()
    shuffled = tuple(reversed(typed))
    assert shuffled != typed
    assert _recipe([f"{n.kind}\x00{n.value}" for n in shuffled]) == needle_set_sha256()
    assert _recipe([f"{n.kind}\x00{n.value}" for n in sorted(typed, key=lambda n: n.value)]) == (
        needle_set_sha256()
    )


def test_regression_14_skeleton_law_ids_refs_no_orion_text_and_records_match() -> None:
    skeletons = build_skeletons()
    result = run_leakage_gate()
    records = {r.skeleton_id: r for r in result.skeletons}
    for skeleton_id, text in skeletons.items():
        payload = _request_payload(text, _instruction_for(skeleton_id))
        assert payload["evidence"], skeleton_id
        for entry in payload["evidence"]:
            assert entry["evidence_id"].startswith("EV-O-")
            assert entry["content"] == placeholder_evidence_content(entry["evidence_id"])
            assert entry["content"] == f"<EVIDENCE:{entry['evidence_id']}>"
            assert entry["artifact_ref"] in ARTIFACT_REFS.values()
            assert entry["source_ref"].startswith("experiment://orion/T")
        for lifecycle in TIMELINE:
            for line in lifecycle.item.content.splitlines():
                stripped = line.strip("# ").strip()
                if stripped:
                    assert stripped not in text, (skeleton_id, stripped)
        for fragment in re.findall(r"<EVIDENCE:[^>]*>", text):
            assert re.fullmatch(r"<EVIDENCE:EV-O-[A-L]\d\d>", fragment), (skeleton_id, fragment)
        assert records[skeleton_id].sha256 == _sha256(text)
        assert records[skeleton_id].chars == len(text)
    lineage = build_skeletons()["F_CORRECTION_CALL1_TOUCHED"]
    assert f'"supersedes_evidence_id":"{evidence_id(1, "A")}"' in lineage
    for skeleton in render_skeletons():
        assert skeleton.harness_text == skeleton.model_visible_text


def test_regression_15_gate_fails_closed_on_first_match_and_passes_with_none_matched() -> None:
    default = run_leakage_gate()
    assert default.passed is True
    assert default.matched_needle is None
    assert default.matched_needle_kind is None
    assert default.matched_skeleton_id is None
    result = run_leakage_gate(
        extra_harness_text=("checkpoint C02 failed", "CORRECTION", MEANING_C03)
    )
    assert result.passed is False
    assert result.matched_skeleton_id == f"{EXTRA_HARNESS_TEXT_PREFIX}0"
    assert result.matched_needle == "C02"
    assert result.matched_needle_kind == "CHECKPOINT_LABEL"
    assert len(result.skeletons) == len(REQUIRED_SKELETON_IDS) + 3
    # A single injected haystack carrying several needles reports exactly one: the first
    # in typed order (CANONICAL_LABEL sorts before CHECKPOINT_LABEL before PROSE).
    mixed = run_leakage_gate(extra_harness_text=(f"C02 CORRECTION {MEANING_C03}",))
    assert mixed.matched_needle == "CORRECTION"
    assert mixed.matched_needle_kind == "CANONICAL_LABEL"


# --- request-path import gate (C2) ---------------------------------------------------


def test_request_path_modules_are_the_six_9p3_request_path_files() -> None:
    assert REQUEST_PATH_MODULES == (
        "timeline.py",
        "protocol.py",
        "designation.py",
        "authority.py",
        "measurements.py",
        "runner.py",
    )
    for name in REQUEST_PATH_MODULES:
        assert (PACKAGE_DIR / name).is_file()


def test_request_path_import_gate_passes_on_the_six_real_files() -> None:
    passed, detail = request_path_import_gate(_real_sources())
    assert passed is True
    for name in REQUEST_PATH_MODULES:
        assert name in detail


@pytest.mark.parametrize("statement", IMPORT_FORMS)
def test_request_path_import_gate_rejects_every_answer_key_import_form(statement: str) -> None:
    sources = {name: "" for name in REQUEST_PATH_MODULES}
    sources["runner.py"] = f"from __future__ import annotations\n{statement}\n"
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "runner.py" in detail
    assert "expectations" in detail or "select_architecture" in detail


def test_request_path_import_gate_flags_every_public_grading_helper_name() -> None:
    for helper in expectations_module.__all__:
        sources = {name: "" for name in REQUEST_PATH_MODULES}
        sources["timeline.py"] = f"from foundry.experiments.long_horizon_bounded import {helper}\n"
        passed, _ = request_path_import_gate(sources)
        assert passed is False, helper


def test_request_path_import_gate_accepts_clean_sources() -> None:
    sources = {name: "" for name in REQUEST_PATH_MODULES}
    sources["runner.py"] = (
        "from __future__ import annotations\n"
        "import hashlib\n"
        "from foundry.experiments.long_horizon_bounded.timeline import TIMELINE\n"
        "from foundry.experiments.long_horizon_bounded.protocol import ARM_SCHEDULE\n"
        "from .authority import HUMAN_FINGERPRINT\n"
        "from foundry.experiments.contrastive_unseen.records import RecordingReasoner\n"
    )
    passed, _ = request_path_import_gate(sources)
    assert passed is True


def test_request_path_import_gate_fails_when_runner_is_missing() -> None:
    sources = _real_sources()
    del sources["runner.py"]
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "runner.py" in detail


@pytest.mark.parametrize("missing", REQUEST_PATH_MODULES)
def test_request_path_import_gate_requires_all_six_keys(missing: str) -> None:
    sources = _real_sources()
    del sources[missing]
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert missing in detail


def test_request_path_import_gate_fails_on_unparsable_source() -> None:
    sources = _real_sources()
    sources["authority.py"] = "def broken(:\n"
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "authority.py" in detail


def test_request_path_import_gate_scans_extra_supplied_modules_too() -> None:
    sources = _real_sources()
    sources["artifacts.py"] = "from foundry.experiments.long_horizon_bounded import expectations\n"
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "artifacts.py" in detail


# --- module law ---------------------------------------------------------------------


def test_leakage_module_is_outside_the_request_path_and_reuses_9p2_normalization() -> None:
    source = Path(leakage_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        f"{node.module}.{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert "foundry.experiments.contrastive_unseen.leakage.normalize_leakage_text" in imported
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "normalize_leakage_text" not in defined
    # The only matchers are the three of the typed law: no similarity, ranking or
    # fuzzy logic anywhere in the code (identifiers and imports; docstrings are prose).
    modules = {alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names}
    modules |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(
        m.split(".")[0] in {"difflib", "rapidfuzz", "thefuzz", "Levenshtein"} for m in modules
    )
    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    identifiers |= {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for fragment in ("similar", "fuzz", "levenshtein", "score", "rank", "embed"):
        assert not any(fragment in i.casefold() for i in identifiers), fragment
    assert "XAI_API_KEY" not in source
    assert "harness_text" in SkeletonText.model_fields
