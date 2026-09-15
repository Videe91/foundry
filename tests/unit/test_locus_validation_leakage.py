"""T6: the typed leakage gate of the locus-validation experiment (spec §9; T6 brief).

The gate scans harness-authored, model-visible text -- the frozen locus system
instruction plus eight structurally representative request skeletons rendered through
the real governor, the real assembly functions and the real ``render_request`` over
opaque stand-in evidence -- for every sealed needle, each matched ONLY by its own
kind's matcher (the frozen 9P3 typed matcher, reused by import). Evidence content is
model-state, never harness text, so a needle placed in the evidence stand-in content
must NOT fail the gate, while the same needle in static harness text MUST. The
default gate passing over the eight real skeletons is a real proof that the production
prompt and the corpus ids leak nothing. ZERO live calls; sockets are blocked; the
provider key is never present.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    LOCUS_SYSTEM_INSTRUCTION,
    LOCUS_SYSTEM_INSTRUCTION_SHA256,
)
from foundry.experiments.contrastive_unseen.leakage import normalize_leakage_text
from foundry.experiments.locus_validation import leakage as leakage_module
from foundry.experiments.locus_validation.corpus import (
    ARTIFACT_REFS,
    DOCUMENTS,
    LEDGERS,
    SCOPES,
    Ledger,
    Version,
    evidence_id,
    section_text,
)
from foundry.experiments.locus_validation.expectations import (
    ASSERTION_TEXT,
    CASE_IDS,
    EXPECTED_STATE,
    FAILURE_TAGS,
    HYPOTHESES,
    OUTCOMES,
    SEMANTIC_ASSERTION_IDS,
    SEMANTIC_QUESTIONS,
)
from foundry.experiments.locus_validation.leakage import (
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
from foundry.experiments.locus_validation.protocol import PROMPT_SHA256_FROZEN
from foundry.experiments.long_horizon_bounded import leakage as bounded_leakage
from foundry.experiments.long_horizon_bounded.timeline import (
    PROJECT_ID as ORION_PROJECT_ID,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    SCOPE as ORION_SCOPE,
)
from foundry.experiments.long_horizon_bounded.timeline import (
    TIMELINE as ORION_TIMELINE,
)

PACKAGE_DIR = Path("src/foundry/experiments/locus_validation")
VERSIONS: tuple[Version, ...] = (1, 2)

REQUIRED_SKELETON_IDS = (
    "ALPHA_SEED_CALL1",
    "ALPHA_SEED_CALL2",
    "ALPHA_REVISION_CALL1",
    "ALPHA_REVISION_CALL2",
    "BETA_SEED_CALL1",
    "BETA_SEED_CALL2",
    "BETA_REVISION_CALL1",
    "BETA_REVISION_CALL2",
)

CLASS_TOKENS = ("RESTATEMENT", "COMPATIBLE_EXTENSION", "CORRECTION", "DISTINCT_LOCUS")
VERDICT_IDS = tuple(f"L{n}" for n in range(1, 10))
EXPECTED_CANONICAL = frozenset(
    {*OUTCOMES, *FAILURE_TAGS, *CLASS_TOKENS, *VERDICT_IDS, *SEMANTIC_ASSERTION_IDS}
)
EXPECTED_CHECKPOINT = frozenset(CASE_IDS)

FIVE_KEYS = (
    "allowed_judgment_kinds",
    "evidence",
    "known_addresses",
    "known_claims",
    "comparison_context",
)

ANSWER_KEY_MODULES = ("expectations", "evaluation", "leakage", "integrity", "artifacts")
PACKAGE = "foundry.experiments.locus_validation"

FORBIDDEN_IMPORT_FORMS = tuple(
    form
    for module in ANSWER_KEY_MODULES
    for form in (
        f"import {PACKAGE}.{module}",
        f"import {PACKAGE}.{module} as m",
        f"from {PACKAGE} import {module}",
        f"from {PACKAGE} import corpus, {module}",
        f"from {PACKAGE}.{module} import something",
        f"from .{module} import something",
        f"from . import {module}",
        f"from ..locus_validation.{module} import something",
        f"from ..locus_validation import {module}",
        f'importlib.import_module("{PACKAGE}.{module}")',
        f'import_module("{PACKAGE}.{module}")',
        f'importlib.import_module(".{module}", __package__)',
        f'__import__("{PACKAGE}.{module}")',
    )
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_provider_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    yield
    assert "XAI_API_KEY" not in os.environ


# --- helpers ------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _recipe(entries: list[str]) -> str:
    return _sha256("\x1e".join(sorted(entries)))


def _payload(text: str) -> dict[str, Any]:
    prefix = LOCUS_SYSTEM_INSTRUCTION + "\n"
    assert text.startswith(prefix)
    payload = json.loads(text[len(prefix) :])
    assert isinstance(payload, dict)
    return payload


def _derive_prose(text: str) -> list[str]:
    """Independent test-side transcription of the documented PROSE derivation."""
    stripped = re.sub(r"\*\*|\*|`|\|", "", text)
    fragments: list[str] = []
    for fragment in re.split(r"[.;]\s+|\n", stripped):
        fragment = fragment.strip()
        fragment = fragment.removeprefix("- ").strip()
        fragment = fragment.rstrip(".;:?!").strip()
        if len(fragment.split()) >= 6:
            fragments.append(fragment)
    return fragments


def _expected_prose() -> frozenset[str]:
    sources = (
        *HYPOTHESES.values(),
        *EXPECTED_STATE.values(),
        *ASSERTION_TEXT.values(),
        *SEMANTIC_QUESTIONS.values(),
    )
    return frozenset(fragment for source in sources for fragment in _derive_prose(source))


def _real_sources() -> dict[str, str]:
    return {name: (PACKAGE_DIR / name).read_text(encoding="utf-8") for name in REQUEST_PATH_MODULES}


def _failed_on(result: LeakageResult, needle: str, kind: str) -> None:
    assert result.passed is False
    assert result.matched_needle == needle
    assert result.matched_needle_kind == kind
    assert result.matched_skeleton_id is not None


def _ids(ledger: Ledger, t: Version) -> list[str]:
    return [evidence_id(document, t) for document in DOCUMENTS[ledger]]


def _corpus_lines() -> list[str]:
    lines: list[str] = []
    for ledger in LEDGERS:
        for document in DOCUMENTS[ledger]:
            for t in VERSIONS:
                for line in section_text(document, t).splitlines():
                    stripped = line.strip("# ").strip()
                    if len(stripped.split()) >= 3:
                        lines.append(stripped)
    return lines


ONE_EXPECTED_STATE_SENTENCE = _derive_prose(EXPECTED_STATE["T1"])[0]
"""One hidden expected-state sentence (the first T1 bullet; it carries no label token, so
its only matcher is PROSE), used by the PROSE regressions."""


# --- needle inventory (clarification 2) --------------------------------------------


def test_typed_needles_assign_exactly_one_kind_per_value_and_cover_the_inventory() -> None:
    typed = typed_needles()
    assert all(isinstance(needle, LeakageNeedle) for needle in typed)
    by_kind: dict[str, set[str]] = {
        "PROSE": set(),
        "CANONICAL_LABEL": set(),
        "CHECKPOINT_LABEL": set(),
    }
    for needle in typed:
        by_kind[needle.kind].add(needle.value)
    assert by_kind["CHECKPOINT_LABEL"] == EXPECTED_CHECKPOINT
    assert by_kind["CANONICAL_LABEL"] == EXPECTED_CANONICAL
    assert by_kind["PROSE"] == _expected_prose()
    values = [needle.value for needle in typed]
    assert len(values) == len(set(values))
    assert not (by_kind["PROSE"] & by_kind["CANONICAL_LABEL"])
    assert not (by_kind["PROSE"] & by_kind["CHECKPOINT_LABEL"])
    assert not (by_kind["CANONICAL_LABEL"] & by_kind["CHECKPOINT_LABEL"])
    assert list(typed) == sorted(typed, key=lambda needle: (needle.kind, needle.value))
    assert typed == typed_needles()
    assert len(by_kind["CHECKPOINT_LABEL"]) == 6
    assert len(by_kind["CANONICAL_LABEL"]) == 3 + 10 + 4 + 9 + 5
    assert len(by_kind["PROSE"]) >= 20


def test_prose_needles_are_markup_free_sentences_of_at_least_six_words() -> None:
    prose = [needle.value for needle in typed_needles() if needle.kind == "PROSE"]
    assert prose
    for value in prose:
        assert len(value.split()) >= 6, value
        assert "`" not in value and "*" not in value and "|" not in value, value
        assert value == value.strip()
        assert not value.startswith("- ")
        assert value[-1] not in ".;:?!", value
    # Representative sentences from each of the four sources, markup stripped.
    assert (
        "A seed delta of four documents, each about one locus, yields exactly four addresses, "
        "one live claim each, with locus-level facets"
    ) in prose
    assert "exactly 4 active in-scope addresses X1..X4" in prose
    assert "the 4 creates cite distinct items" in prose
    assert (
        "Does the new claim at X4 state the corrected value (α: 45 seconds; β: 48 hours)"
        not in prose
    )
    assert "Does the new claim at X4 state the corrected value (α: 45 seconds" in prose


def test_needles_is_the_value_inventory_of_typed_needles() -> None:
    assert needles() == tuple(needle.value for needle in typed_needles())
    inventory = set(needles())
    for label in (*CASE_IDS, *OUTCOMES, *FAILURE_TAGS, *CLASS_TOKENS, *VERDICT_IDS):
        assert label in inventory
    for assertion_id in SEMANTIC_ASSERTION_IDS:
        assert assertion_id in inventory
    assert len(needles()) == len(_expected_prose()) + len(EXPECTED_CANONICAL) + len(CASE_IDS)


def test_needles_contain_no_corpus_section_text() -> None:
    inventory = needles()
    for line in _corpus_lines():
        assert line not in inventory
        assert not any(line in needle for needle in inventory)


# --- typed matcher reused by import (clarification 1) ------------------------------


def test_matcher_and_needle_type_are_the_frozen_9p3_ones() -> None:
    assert matches is bounded_leakage.matches
    assert LeakageNeedle is bounded_leakage.LeakageNeedle
    assert matches(LeakageNeedle(value="V03", kind="CHECKPOINT_LABEL"), "case V03 failed")
    assert not matches(LeakageNeedle(value="V03", kind="CHECKPOINT_LABEL"), "EV-LV-A3-T1")
    assert not matches(LeakageNeedle(value="V03", kind="CHECKPOINT_LABEL"), "EV-LV-V03")
    assert matches(
        LeakageNeedle(value="COMPATIBLE_EXTENSION", kind="CANONICAL_LABEL"),
        "x COMPATIBLE_EXTENSION y",
    )
    assert not matches(
        LeakageNeedle(value="COMPATIBLE_EXTENSION", kind="CANONICAL_LABEL"),
        "a compatible extension",
    )
    assert matches(LeakageNeedle(value="Alpha  beta", kind="PROSE"), "x ALPHA\tBETA y")


# --- hash recipe (clarification 1) ----------------------------------------------------


def test_hash_equals_the_documented_recipe() -> None:
    entries = [f"{needle.kind}\x00{needle.value}" for needle in typed_needles()]
    assert needle_set_sha256() == _recipe(entries)
    assert (
        needle_set_sha256()
        == hashlib.sha256("\x1e".join(sorted(entries)).encode("utf-8")).hexdigest()
    )
    assert re.fullmatch(r"[0-9a-f]{64}", needle_set_sha256())
    assert needle_set_sha256() != bounded_leakage.needle_set_sha256()


def test_hash_commits_to_kind_and_to_unnormalized_values() -> None:
    typed = typed_needles()
    baseline = _recipe([f"{n.kind}\x00{n.value}" for n in typed])
    assert baseline == needle_set_sha256()
    rekinded = [f"{'PROSE' if n.value == 'V03' else n.kind}\x00{n.value}" for n in typed]
    assert _recipe(rekinded) != baseline
    normalized = [f"{n.kind}\x00{normalize_leakage_text(n.value)}" for n in typed]
    assert _recipe(normalized) != baseline
    assert any(n.value != normalize_leakage_text(n.value) for n in typed)


def test_hash_is_deterministic_and_order_independent() -> None:
    assert needle_set_sha256() == needle_set_sha256()
    typed = typed_needles()
    shuffled = tuple(reversed(typed))
    assert shuffled != typed
    assert _recipe([f"{n.kind}\x00{n.value}" for n in shuffled]) == needle_set_sha256()


# --- skeletons (clarification 3) ---------------------------------------------------


def test_skeleton_ids_are_exactly_the_required_eight_in_order() -> None:
    assert SKELETON_IDS == REQUIRED_SKELETON_IDS
    assert tuple(build_skeletons()) == REQUIRED_SKELETON_IDS
    assert tuple(s.skeleton_id for s in render_skeletons()) == REQUIRED_SKELETON_IDS


def test_skeletons_are_locus_prompt_plus_five_key_render() -> None:
    skeletons = build_skeletons()
    for skeleton_id in REQUIRED_SKELETON_IDS:
        payload = _payload(skeletons[skeleton_id])
        assert tuple(payload) == FIVE_KEYS


@pytest.mark.parametrize("ledger", LEDGERS)
def test_skeletons_cover_the_seed_and_revision_shapes(ledger: Ledger) -> None:
    skeletons = build_skeletons()
    prefix = ledger.upper()
    t1_ids, t2_ids = _ids(ledger, 1), _ids(ledger, 2)

    seed1 = _payload(skeletons[f"{prefix}_SEED_CALL1"])
    assert [e["evidence_id"] for e in seed1["evidence"]] == t1_ids
    assert all(e["supersedes_evidence_id"] is None for e in seed1["evidence"])
    assert all(e["scope"] == [SCOPES[ledger]] for e in seed1["evidence"])
    assert seed1["known_addresses"] == []
    assert seed1["known_claims"] == []
    assert seed1["comparison_context"]["transitions"] == []
    assert seed1["allowed_judgment_kinds"] == ["BIND_TO_ADDRESS", "CREATE_ADDRESS"]

    seed2 = _payload(skeletons[f"{prefix}_SEED_CALL2"])
    assert [e["evidence_id"] for e in seed2["evidence"]] == t1_ids
    assert seed2["allowed_judgment_kinds"] == [
        "ASSERT_CLAIM",
        "CONFLICTS_WITH",
        "SUPERSEDE",
        "SUPPORTS_CLAIM",
    ]
    assert len(seed2["known_addresses"]) == 4
    assert len(seed2["known_claims"]) == 4
    assert {a["scope"][0] for a in seed2["known_addresses"]} == {SCOPES[ledger]}
    assert sorted(c["evidence_ids"][0] for c in seed2["known_claims"]) == sorted(t1_ids)
    assert {c["value"]["kind"] for c in seed2["known_claims"]} == {"TEXT"}
    assert {a["address_id"] for a in seed2["known_addresses"]} == {
        c["address_id"] for c in seed2["known_claims"]
    }

    revision1 = _payload(skeletons[f"{prefix}_REVISION_CALL1"])
    assert [e["evidence_id"] for e in revision1["evidence"]] == t2_ids
    assert [e["supersedes_evidence_id"] for e in revision1["evidence"]] == t1_ids
    assert revision1["allowed_judgment_kinds"] == ["BIND_TO_ADDRESS", "CREATE_ADDRESS"]
    assert len(revision1["known_addresses"]) == 4
    assert len(revision1["known_claims"]) == 4
    transitions = revision1["comparison_context"]["transitions"]
    assert [t["predecessor_evidence_id"] for t in transitions] == t1_ids
    assert [t["current_evidence_id"] for t in transitions] == t2_ids
    assert [t["artifact_ref"] for t in transitions] == [
        ARTIFACT_REFS[document] for document in DOCUMENTS[ledger]
    ]
    assert all(len(t["touched_claim_ids"]) == 1 for t in transitions)

    revision2 = _payload(skeletons[f"{prefix}_REVISION_CALL2"])
    assert [e["evidence_id"] for e in revision2["evidence"]] == t2_ids
    assert len(revision2["known_addresses"]) == 4
    assert len(revision2["known_claims"]) == 4
    assert len(revision2["comparison_context"]["transitions"]) == 4


def test_skeleton_law_real_ids_opaque_content_no_corpus_text_no_orion() -> None:
    skeletons = build_skeletons()
    result = run_leakage_gate()
    records = {record.skeleton_id: record for record in result.skeletons}
    corpus_lines = _corpus_lines()
    for skeleton_id, text in skeletons.items():
        payload = _payload(text)
        assert payload["evidence"], skeleton_id
        for entry in payload["evidence"]:
            assert entry["evidence_id"].startswith("EV-LV-")
            assert entry["content"] == placeholder_evidence_content(entry["evidence_id"])
            assert entry["content"] == f"<EVIDENCE:{entry['evidence_id']}>"
            assert entry["artifact_ref"] in ARTIFACT_REFS.values()
            assert entry["source_ref"].startswith("experiment://locus-validation/")
        for line in corpus_lines:
            assert line not in text, (skeleton_id, line)
        for fragment in re.findall(r"<EVIDENCE:[^>]*>", text):
            assert re.fullmatch(r"<EVIDENCE:EV-LV-[AB][1-4]-T[12]>", fragment), (
                skeleton_id,
                fragment,
            )
        assert "EV-O-" not in text
        assert "orion" not in text.casefold()
        assert ORION_PROJECT_ID not in text
        assert ORION_SCOPE not in text
        for lifecycle in ORION_TIMELINE:
            for line in lifecycle.item.content.splitlines():
                stripped = line.strip("# ").strip()
                if len(stripped.split()) >= 3:
                    assert stripped not in text, (skeleton_id, stripped)
        assert records[skeleton_id].sha256 == _sha256(text)
        assert records[skeleton_id].chars == len(text)
    assert f'"supersedes_evidence_id":"{evidence_id("A1", 1)}"' in skeletons["ALPHA_REVISION_CALL1"]
    assert f'"supersedes_evidence_id":"{evidence_id("B1", 1)}"' in skeletons["BETA_REVISION_CALL1"]


def test_skeleton_harness_text_has_evidence_content_substituted_out() -> None:
    for skeleton in render_skeletons():
        assert isinstance(skeleton, SkeletonText)
        assert skeleton.model_visible_text.startswith(LOCUS_SYSTEM_INSTRUCTION + "\n")
        assert "<EVIDENCE:" in skeleton.model_visible_text
        assert "<EVIDENCE:" not in skeleton.harness_text
        assert "EV-LV-" in skeleton.harness_text
        assert skeleton.harness_text.startswith(LOCUS_SYSTEM_INSTRUCTION + "\n")


def test_skeletons_are_deterministic() -> None:
    assert build_skeletons() == build_skeletons()
    assert render_skeletons() == render_skeletons()
    assert run_leakage_gate() == run_leakage_gate()


# --- the default gate (clarification 6) -------------------------------------------


def test_default_gate_passes_on_the_frozen_prompt_and_the_eight_real_skeletons() -> None:
    result = run_leakage_gate()
    assert isinstance(result, LeakageResult)
    assert result.passed is True
    assert result.matched_needle is None
    assert result.matched_needle_kind is None
    assert result.matched_skeleton_id is None
    assert result.needle_set_sha256 == needle_set_sha256()
    assert result.prompt_sha256 == PROMPT_SHA256_FROZEN
    assert result.prompt_sha256 == LOCUS_SYSTEM_INSTRUCTION_SHA256
    assert result.prompt_sha256 == _sha256(LOCUS_SYSTEM_INSTRUCTION)
    assert tuple(s.skeleton_id for s in result.skeletons) == REQUIRED_SKELETON_IDS
    assert all(isinstance(s, SkeletonRecord) for s in result.skeletons)
    for text in build_skeletons().values():
        assert "EV-LV-" in text


def test_prompt_carries_lower_case_lifecycle_words_but_no_canonical_tokens() -> None:
    for word in ("restatement", "correction", "compatible extension", "distinct locus"):
        assert word in LOCUS_SYSTEM_INSTRUCTION
    for token in CLASS_TOKENS:
        assert token not in LOCUS_SYSTEM_INSTRUCTION


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
    assert EXTRA_HARNESS_TEXT_PREFIX == "EXTRA-"
    assert result.skeletons[-1].chars == len("opaque harness note")
    assert result.skeletons[-1].sha256 == _sha256("opaque harness note")


# --- injection matrix (task text) ---------------------------------------------------


def test_canonical_class_token_in_harness_text_fails() -> None:
    result = run_leakage_gate(extra_harness_text=("COMPATIBLE_EXTENSION",))
    _failed_on(result, "COMPATIBLE_EXTENSION", "CANONICAL_LABEL")
    assert result.matched_skeleton_id == "EXTRA-0"


def test_lower_case_lifecycle_words_in_harness_text_pass() -> None:
    assert run_leakage_gate(extra_harness_text=("compatible extension",)).passed is True
    assert (
        run_leakage_gate(extra_harness_text=("restatement", "correction", "distinct locus")).passed
        is True
    )


@pytest.mark.parametrize(
    "token",
    [
        "RESTATEMENT",
        "CORRECTION",
        "DISTINCT_LOCUS",
        "LOCUS_POLICY_VALIDATED",
        "OVER_SPLIT",
        "L1",
        "L9",
        "A-V01",
    ],
)
def test_every_canonical_kind_fails_as_a_standalone_token(token: str) -> None:
    result = run_leakage_gate(extra_harness_text=(f"note {token} end",))
    _failed_on(result, token, "CANONICAL_LABEL")


def test_canonical_tokens_are_case_sensitive_and_identifier_bounded() -> None:
    assert run_leakage_gate(extra_harness_text=("l1", "a-v01", "over_split", "L10", "L1x")).passed


def test_case_id_in_harness_text_fails_while_evidence_id_passes() -> None:
    result = run_leakage_gate(extra_harness_text=("V03",))
    _failed_on(result, "V03", "CHECKPOINT_LABEL")
    assert run_leakage_gate(extra_harness_text=("EV-LV-A3-T1",)).passed is True
    assert run_leakage_gate(extra_harness_text=("prefix-V03", "V03_suffix", "v03")).passed is True
    result = run_leakage_gate(extra_harness_text=("case V03 failed",))
    _failed_on(result, "V03", "CHECKPOINT_LABEL")


def test_prose_with_different_casing_and_doubled_whitespace_fails() -> None:
    variant = ONE_EXPECTED_STATE_SENTENCE.upper().replace(" ", "  ")
    assert variant != ONE_EXPECTED_STATE_SENTENCE
    result = run_leakage_gate(extra_harness_text=(f"harness note: {variant} end.",))
    _failed_on(result, ONE_EXPECTED_STATE_SENTENCE, "PROSE")
    assert result.matched_skeleton_id == "EXTRA-0"


def test_prose_inside_evidence_content_passes_but_in_harness_text_fails() -> None:
    def content(item_id: str) -> str:
        return f"{placeholder_evidence_content(item_id)} {ONE_EXPECTED_STATE_SENTENCE}"

    skeletons = render_skeletons(evidence_content=content)
    assert all(ONE_EXPECTED_STATE_SENTENCE in s.model_visible_text for s in skeletons)
    assert not any(
        normalize_leakage_text(ONE_EXPECTED_STATE_SENTENCE)
        in normalize_leakage_text(s.harness_text)
        for s in skeletons
    )
    result = scan_skeletons(skeletons)
    assert result.passed is True
    assert result.matched_needle is None
    failed = scan_skeletons(skeletons, extra_harness_text=(f"note {ONE_EXPECTED_STATE_SENTENCE}",))
    _failed_on(failed, ONE_EXPECTED_STATE_SENTENCE, "PROSE")
    assert failed.matched_skeleton_id == "EXTRA-0"
    assert run_leakage_gate(extra_harness_text=(ONE_EXPECTED_STATE_SENTENCE,)).passed is False


def test_multiline_prose_inside_evidence_content_passes() -> None:
    def content(item_id: str) -> str:
        placeholder = placeholder_evidence_content(item_id)
        return f"{placeholder}\n{ONE_EXPECTED_STATE_SENTENCE}\nCOMPATIBLE_EXTENSION\n"

    skeletons = render_skeletons(evidence_content=content)
    result = scan_skeletons(skeletons)
    assert result.passed is True, (result.matched_needle, result.matched_skeleton_id)


def test_gate_fails_closed_on_first_match_in_scan_order() -> None:
    result = run_leakage_gate(
        extra_harness_text=("case V03 failed", "CORRECTION", ONE_EXPECTED_STATE_SENTENCE)
    )
    assert result.passed is False
    assert result.matched_skeleton_id == "EXTRA-0"
    assert result.matched_needle == "V03"
    assert result.matched_needle_kind == "CHECKPOINT_LABEL"
    assert len(result.skeletons) == len(REQUIRED_SKELETON_IDS) + 3
    later = run_leakage_gate(extra_harness_text=("clean", "CORRECTION"))
    assert later.matched_skeleton_id == "EXTRA-1"
    mixed = run_leakage_gate(extra_harness_text=(f"V03 CORRECTION {ONE_EXPECTED_STATE_SENTENCE}",))
    assert mixed.matched_needle == "CORRECTION"
    assert mixed.matched_needle_kind == "CANONICAL_LABEL"


# --- request-path import gate (clarification 5) ------------------------------------


def test_request_path_modules_are_the_four_request_path_files() -> None:
    assert REQUEST_PATH_MODULES == ("corpus.py", "protocol.py", "recording.py", "runner.py")
    for name in REQUEST_PATH_MODULES:
        assert (PACKAGE_DIR / name).is_file()


def test_request_path_import_gate_passes_on_the_four_real_files() -> None:
    passed, detail = request_path_import_gate(_real_sources())
    assert passed is True, detail
    for name in REQUEST_PATH_MODULES:
        assert name in detail


@pytest.mark.parametrize("statement", FORBIDDEN_IMPORT_FORMS)
def test_request_path_import_gate_rejects_every_forbidden_import_form(statement: str) -> None:
    sources = {name: "" for name in REQUEST_PATH_MODULES}
    sources["runner.py"] = f"from __future__ import annotations\nimport importlib\n{statement}\n"
    passed, detail = request_path_import_gate(sources)
    assert passed is False, statement
    assert "runner.py" in detail
    assert any(module in detail for module in ANSWER_KEY_MODULES)


def test_request_path_import_gate_accepts_clean_sources() -> None:
    sources = {name: "" for name in REQUEST_PATH_MODULES}
    sources["runner.py"] = (
        "from __future__ import annotations\n"
        "import hashlib\n"
        "import importlib\n"
        "from foundry.experiments.locus_validation.corpus import LEDGERS\n"
        "from foundry.experiments.locus_validation.protocol import DELTAS\n"
        "from .recording import LocusRecordingReasoner\n"
        "from . import corpus\n"
        "from foundry.experiments.long_horizon_bounded.leakage import matches\n"
        "from foundry.experiments.long_horizon_bounded import integrity\n"
        "from foundry.experiments.contrastive_unseen.artifacts import canonical_sha256\n"
        "from ..longitudinal.artifacts import redact_secrets\n"
        'importlib.import_module("foundry.experiments.contrastive_unseen.integrity")\n'
    )
    passed, detail = request_path_import_gate(sources)
    assert passed is True, detail


@pytest.mark.parametrize("missing", REQUEST_PATH_MODULES)
def test_request_path_import_gate_requires_all_four_keys(missing: str) -> None:
    sources = _real_sources()
    del sources[missing]
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert missing in detail


def test_request_path_import_gate_fails_on_unparsable_source() -> None:
    sources = _real_sources()
    sources["protocol.py"] = "def broken(:\n"
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "protocol.py" in detail


def test_request_path_import_gate_scans_extra_supplied_modules_too() -> None:
    sources = _real_sources()
    sources["extra.py"] = "from foundry.experiments.locus_validation import expectations\n"
    passed, detail = request_path_import_gate(sources)
    assert passed is False
    assert "extra.py" in detail


# --- module law ---------------------------------------------------------------------


def test_leakage_module_reuses_the_9p3_matcher_and_never_touches_the_provider() -> None:
    source = Path(leakage_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        f"{node.module}.{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert "foundry.experiments.long_horizon_bounded.leakage.matches" in imported
    assert "foundry.experiments.long_horizon_bounded.leakage.LeakageNeedle" in imported
    assert "foundry.experiments.long_horizon_bounded.leakage.needle_set_sha256" not in imported
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "matches" not in defined
    assert "normalize_leakage_text" not in defined
    assert "needle_set_sha256" in defined
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
    assert "XAILocusSemanticReasoner" not in source
    assert "XAISemanticReasoner" not in source
    assert "harness_text" in SkeletonText.model_fields
    assert set(LeakageResult.model_fields) == {
        "passed",
        "needle_set_sha256",
        "skeletons",
        "prompt_sha256",
        "matched_needle",
        "matched_needle_kind",
        "matched_skeleton_id",
    }
    assert set(SkeletonRecord.model_fields) == {"skeleton_id", "sha256", "chars"}
