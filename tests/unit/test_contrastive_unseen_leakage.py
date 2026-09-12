"""9P2 T4: the five-key leakage gate (spec §14; brief T4; clarification C1).

The gate scans harness-authored, model-visible text -- the two frozen system
instructions plus nine structurally representative request skeletons rendered through
the real assembly functions and the real ``render_request`` -- for every sealed
needle. Evidence content is model-state, never harness text, so a needle placed in
the evidence placeholder input must NOT fail the gate, while the same needle placed in
static harness text MUST. Normalization is exactly C1. ZERO live calls.
"""

from __future__ import annotations

import hashlib
import json
import socket
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    CONTRASTIVE_SYSTEM_INSTRUCTION,
    CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256,
    SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION_SHA256,
)
from foundry.experiments.contrastive_unseen.expectations import (
    ANSWER_KEY_SENTENCES,
    GRADING_LABELS,
    NORMALIZED_CONCLUSIONS,
)
from foundry.experiments.contrastive_unseen.leakage import (
    SKELETON_IDS,
    LeakageResult,
    SkeletonText,
    build_skeletons,
    needle_set_sha256,
    needle_strings,
    normalize_leakage_text,
    placeholder_evidence_content,
    run_leakage_gate,
    scan_skeletons,
)
from foundry.experiments.contrastive_unseen.timeline import TIMELINE

REQUIRED_SKELETON_IDS = (
    "F_T1_CALL1_NO_PREDECESSOR",
    "F_CORRECTION_CALL1_TOUCHED",
    "F_CORRECTION_CALL2_TOUCHED",
    "F_RESTATEMENT_CALL1_TOUCHED",
    "F_RESTATEMENT_CALL2_TOUCHED",
    "A_CALL1_NO_CLAIMS",
    "A_CALL2_WITH_CLAIMS_NO_CONTEXT",
    "R_CUMULATIVE_CALL1",
    "R_CUMULATIVE_CALL2",
)

REPRESENTATIVE_PHRASES = (
    GRADING_LABELS[0],
    GRADING_LABELS[-1],
    ANSWER_KEY_SENTENCES[0],
    *NORMALIZED_CONCLUSIONS,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _by_id(skeletons: tuple[SkeletonText, ...]) -> dict[str, SkeletonText]:
    return {s.skeleton_id: s for s in skeletons}


def _request_payload(skeleton: SkeletonText, instruction: str) -> dict[str, Any]:
    prefix = instruction + "\n"
    assert skeleton.model_visible_text.startswith(prefix)
    payload = json.loads(skeleton.model_visible_text[len(prefix) :])
    assert isinstance(payload, dict)
    return payload


# --- C1 normalization --------------------------------------------------------------


def test_normalize_casefolds_and_collapses_only_ascii_whitespace() -> None:
    assert normalize_leakage_text("  Maximum\tFOUR \n\n total\r\v\fattempts ") == (
        "maximum four total attempts"
    )


def test_normalize_leaves_non_ascii_whitespace_and_punctuation_alone() -> None:
    assert normalize_leakage_text("a b") == "a b"
    assert normalize_leakage_text("a  b") == "a  b"
    assert normalize_leakage_text("Five-second, wait.") == "five-second, wait."


# --- needles -----------------------------------------------------------------------


def test_needles_are_exactly_labels_sentences_and_conclusions() -> None:
    expected = tuple(sorted({*GRADING_LABELS, *ANSWER_KEY_SENTENCES, *NORMALIZED_CONCLUSIONS}))
    assert needle_strings() == expected
    assert len(needle_strings()) == len(GRADING_LABELS) + len(ANSWER_KEY_SENTENCES) + len(
        NORMALIZED_CONCLUSIONS
    )


def test_needles_contain_no_evidence_text() -> None:
    needles = needle_strings()
    for lifecycle in TIMELINE:
        for line in lifecycle.item.content.splitlines():
            stripped = line.strip("# ").strip()
            if stripped:
                assert stripped not in needles
                assert not any(stripped in needle for needle in needles)


def test_needle_set_sha256_is_canonical_json_of_sorted_unnormalized_needles() -> None:
    canonical = json.dumps(
        list(needle_strings()), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert needle_set_sha256() == _sha256(canonical)
    # Unnormalized: the sealed strings keep their original case.
    assert any(needle != needle.casefold() for needle in needle_strings())


# --- skeletons ---------------------------------------------------------------------


def test_skeleton_ids_are_exactly_the_required_nine_in_order() -> None:
    assert SKELETON_IDS == REQUIRED_SKELETON_IDS
    assert tuple(s.skeleton_id for s in build_skeletons()) == REQUIRED_SKELETON_IDS


def test_fr_skeletons_use_the_contrastive_instruction_and_five_key_rendering() -> None:
    skeletons = _by_id(build_skeletons())
    for skeleton_id in REQUIRED_SKELETON_IDS:
        if skeleton_id.startswith("A_"):
            continue
        payload = _request_payload(skeletons[skeleton_id], CONTRASTIVE_SYSTEM_INSTRUCTION)
        assert tuple(payload) == (
            "allowed_judgment_kinds",
            "evidence",
            "known_addresses",
            "known_claims",
            "comparison_context",
        )


def test_a_skeletons_use_the_historical_instruction_and_four_key_rendering() -> None:
    skeletons = _by_id(build_skeletons())
    for skeleton_id in ("A_CALL1_NO_CLAIMS", "A_CALL2_WITH_CLAIMS_NO_CONTEXT"):
        payload = _request_payload(skeletons[skeleton_id], SYSTEM_INSTRUCTION)
        assert tuple(payload) == (
            "allowed_judgment_kinds",
            "evidence",
            "known_addresses",
            "known_claims",
        )


def test_skeletons_cover_the_required_structural_shapes() -> None:
    skeletons = _by_id(build_skeletons())
    contrastive = CONTRASTIVE_SYSTEM_INSTRUCTION

    t1 = _request_payload(skeletons["F_T1_CALL1_NO_PREDECESSOR"], contrastive)
    assert [e["evidence_id"] for e in t1["evidence"]] == ["EV-K-A1", "EV-K-B1", "EV-K-N1"]
    assert all(e["supersedes_evidence_id"] is None for e in t1["evidence"])
    assert t1["comparison_context"]["transitions"] == []
    assert t1["allowed_judgment_kinds"] == ["BIND_TO_ADDRESS", "CREATE_ADDRESS"]

    correction_1 = _request_payload(skeletons["F_CORRECTION_CALL1_TOUCHED"], contrastive)
    (transition,) = correction_1["comparison_context"]["transitions"]
    assert transition["predecessor_evidence_id"] == "EV-K-A1"
    assert transition["current_evidence_id"] == "EV-K-A2"
    assert len(transition["touched_claim_ids"]) == 1
    assert len(correction_1["known_claims"]) == 1  # active claim profile shown in Call 1
    assert correction_1["comparison_context"]["active_claim_profile_edges"] != []
    assert transition["historical_diff"].startswith("--- evidence:EV-K-A1")

    correction_2 = _request_payload(skeletons["F_CORRECTION_CALL2_TOUCHED"], contrastive)
    assert correction_2["allowed_judgment_kinds"] == [
        "ASSERT_CLAIM",
        "CONFLICTS_WITH",
        "SUPERSEDE",
        "SUPPORTS_CLAIM",
    ]
    assert len(correction_2["known_addresses"]) == 1
    assert len(correction_2["known_claims"]) == 1
    (transition_2,) = correction_2["comparison_context"]["transitions"]
    assert transition_2["touched_address_ids"] == [correction_2["known_addresses"][0]["address_id"]]

    restatement_1 = _request_payload(skeletons["F_RESTATEMENT_CALL1_TOUCHED"], contrastive)
    (restatement,) = restatement_1["comparison_context"]["transitions"]
    assert restatement["predecessor_evidence_id"] == "EV-K-A2"
    assert restatement["current_evidence_id"] == "EV-K-A3"
    assert len(restatement["touched_claim_ids"]) == 1
    # Restatement-shaped: the claim is reached through an ACTIVE SUPPORTS_CLAIM link,
    # never through its immutable asserting evidence.
    (claim,) = restatement_1["known_claims"]
    assert "EV-K-A2" not in claim["evidence_ids"]

    restatement_2 = _request_payload(skeletons["F_RESTATEMENT_CALL2_TOUCHED"], contrastive)
    assert len(restatement_2["known_claims"]) == 1
    assert len(restatement_2["comparison_context"]["transitions"]) == 1

    a1 = _request_payload(skeletons["A_CALL1_NO_CLAIMS"], SYSTEM_INSTRUCTION)
    assert len(a1["known_addresses"]) == 1
    assert a1["known_claims"] == []

    a2 = _request_payload(skeletons["A_CALL2_WITH_CLAIMS_NO_CONTEXT"], SYSTEM_INSTRUCTION)
    assert len(a2["known_claims"]) == 1
    assert "comparison_context" not in a2

    r1 = _request_payload(skeletons["R_CUMULATIVE_CALL1"], contrastive)
    assert [e["evidence_id"] for e in r1["evidence"]] == [
        "EV-K-A1",
        "EV-K-B1",
        "EV-K-N1",
        "EV-K-A2",
        "EV-K-A3",
        "EV-K-B2",
    ]
    assert len(r1["comparison_context"]["transitions"]) == 3

    r2 = _request_payload(skeletons["R_CUMULATIVE_CALL2"], contrastive)
    assert len(r2["evidence"]) == 6
    assert r2["allowed_judgment_kinds"] == [
        "ASSERT_CLAIM",
        "CONFLICTS_WITH",
        "SUPERSEDE",
        "SUPPORTS_CLAIM",
    ]


def test_skeletons_carry_placeholder_evidence_and_no_kestrel_text() -> None:
    skeletons = build_skeletons()
    for skeleton in skeletons:
        for lifecycle in TIMELINE:
            for line in lifecycle.item.content.splitlines():
                stripped = line.strip("# ").strip()
                if stripped:
                    assert stripped not in skeleton.model_visible_text
        instruction = SYSTEM_INSTRUCTION if skeleton.arm == "A" else CONTRASTIVE_SYSTEM_INSTRUCTION
        payload = _request_payload(skeleton, instruction)
        for entry in payload["evidence"]:
            assert entry["content"] == placeholder_evidence_content(entry["evidence_id"])
            assert entry["content"] == f"<EVIDENCE:{entry['evidence_id']}>"
    for skeleton in skeletons:
        assert "SUBJECT_ALPHA" in skeleton.model_visible_text or skeleton.skeleton_id in (
            "F_T1_CALL1_NO_PREDECESSOR",
            "R_CUMULATIVE_CALL1",
            "R_CUMULATIVE_CALL2",
        )


def test_skeletons_are_deterministic() -> None:
    assert build_skeletons() == build_skeletons()
    assert run_leakage_gate() == run_leakage_gate()


# --- the gate on frozen text -------------------------------------------------------


def test_gate_passes_on_frozen_harness_text_and_records_identity() -> None:
    result = run_leakage_gate()
    assert isinstance(result, LeakageResult)
    assert result.passed is True
    assert result.matched_needle is None
    assert result.matched_skeleton_id is None
    assert result.needle_set_sha256 == needle_set_sha256()
    assert result.fr_prompt_sha256 == CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256
    assert result.fr_prompt_sha256 == _sha256(CONTRASTIVE_SYSTEM_INSTRUCTION)
    assert result.a_prompt_sha256 == SYSTEM_INSTRUCTION_SHA256
    assert result.a_prompt_sha256 == _sha256(SYSTEM_INSTRUCTION)
    assert tuple(s.skeleton_id for s in result.skeletons) == REQUIRED_SKELETON_IDS
    built = _by_id(build_skeletons())
    for record in result.skeletons:
        assert record.sha256 == _sha256(built[record.skeleton_id].model_visible_text)
        assert record.chars == len(built[record.skeleton_id].model_visible_text)


def test_result_is_frozen() -> None:
    result = run_leakage_gate()
    with pytest.raises(Exception, match="frozen"):
        result.passed = False  # type: ignore[misc]


# --- mutation proofs ---------------------------------------------------------------


@pytest.mark.parametrize("phrase", REPRESENTATIVE_PHRASES)
def test_hidden_phrase_in_static_harness_text_fails_the_gate(phrase: str) -> None:
    result = run_leakage_gate(extra_harness_text=(f"harness guidance: {phrase} end.",))
    assert result.passed is False
    assert result.matched_needle == phrase
    assert result.matched_skeleton_id is not None
    assert result.matched_skeleton_id.startswith("EXTRA_HARNESS_TEXT_")


@pytest.mark.parametrize("phrase", REPRESENTATIVE_PHRASES)
def test_case_and_ascii_whitespace_variants_of_a_phrase_still_fail(phrase: str) -> None:
    variant = phrase.upper().replace(" ", "\t \n")
    result = run_leakage_gate(extra_harness_text=(f"x {variant} y",))
    assert result.passed is False
    assert result.matched_needle == phrase


def test_grading_label_needle_is_word_bounded() -> None:
    assert run_leakage_gate(extra_harness_text=("token ABC1DEF here",)).passed is True
    assert run_leakage_gate(extra_harness_text=("token c1_suffix here",)).passed is True
    failed = run_leakage_gate(extra_harness_text=("token (c1) here",))
    assert failed.passed is False
    assert failed.matched_needle == "C1"


def test_extra_harness_text_is_recorded_as_a_scanned_skeleton() -> None:
    result = run_leakage_gate(extra_harness_text=("opaque harness note",))
    assert result.passed is True
    ids = tuple(s.skeleton_id for s in result.skeletons)
    assert ids[: len(REQUIRED_SKELETON_IDS)] == REQUIRED_SKELETON_IDS
    assert ids[-1] == "EXTRA_HARNESS_TEXT_0"


@pytest.mark.parametrize("phrase", REPRESENTATIVE_PHRASES)
def test_hidden_phrase_in_evidence_placeholder_content_is_not_harness_leakage(
    phrase: str,
) -> None:
    def content(evidence_id: str) -> str:
        return f"{placeholder_evidence_content(evidence_id)} {phrase}"

    skeletons = build_skeletons(evidence_content=content)
    # The phrase reaches the model-visible text (evidence bytes and the diffs built
    # from them) ...
    assert any(phrase in s.model_visible_text for s in skeletons)
    # ... but evidence content is substituted out before scanning. (Two-character
    # labels are checked only through the word-bounded scan below: "c1" may occur
    # inside a minted hex id, which is exactly why labels are word-bounded.)
    if phrase not in GRADING_LABELS:
        assert not any(normalize_leakage_text(phrase) in s.harness_text for s in skeletons)
    result = scan_skeletons(skeletons)
    assert result.passed is True
    assert result.matched_needle is None


def test_same_phrase_in_harness_text_still_fails_when_evidence_also_carries_it() -> None:
    phrase = NORMALIZED_CONCLUSIONS[1]

    def content(evidence_id: str) -> str:
        return f"{placeholder_evidence_content(evidence_id)} {phrase}"

    result = scan_skeletons(
        build_skeletons(evidence_content=content), extra_harness_text=(f"note {phrase}",)
    )
    assert result.passed is False
    assert result.matched_needle == phrase
    assert result.matched_skeleton_id == "EXTRA_HARNESS_TEXT_0"


def test_default_skeleton_harness_text_equals_normalized_model_visible_text() -> None:
    """With placeholder content the substitution is the identity, so the scanned text
    is exactly the normalized model-visible text -- nothing else is hidden."""
    for skeleton in build_skeletons():
        assert skeleton.harness_text == normalize_leakage_text(skeleton.model_visible_text)
