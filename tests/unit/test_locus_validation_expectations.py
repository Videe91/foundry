"""Hidden answer key of the locus-validation experiment (T1).

Locks the six case slots per ledger with their semantic classes and carrying
documents, the failure-tag, outcome and semantic-assertion vocabularies, the
verbatim §2 / §6 / §7.1 / §7.2 prose (checked against the approved spec, parsed
read-only as a test-time oracle so no answer-key wording is duplicated here), the
§14 per-case and experiment-outcome rules as a truth table, and the canonical
expectations document. Nothing here is ever sent to a model; ``corpus.py`` must
not import this module (checked with ``ast``). No live call exists.
"""

from __future__ import annotations

import ast
import itertools
import json
import re
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry.experiments.locus_validation import corpus as corpus_module
from foundry.experiments.locus_validation.corpus import DOCUMENTS, LEDGERS
from foundry.experiments.locus_validation.expectations import (
    ASSERTION_TEXT,
    CASE_IDS,
    CASE_OUTCOME_RULES,
    CASES,
    EXPECTED_STATE,
    FAILURE_TAGS,
    FREEZE_STATE_MACHINE,
    HYPOTHESES,
    IDENTITY_STATE_MACHINE,
    OUTCOMES,
    SCORING_RULE,
    SEMANTIC_ASSERTION_IDS,
    SEMANTIC_QUESTIONS,
    Case,
    CaseOutcomeRule,
    expectations_document,
    experiment_outcome,
)

# spec §16: a case id is a case-sensitive standalone identifier token, never a
# substring of a compound token like ``A-S01`` (same boundary rule as the sealed
# leakage matcher's CHECKPOINT_LABEL kind: a hyphen does not count as a boundary).
_CASE_ID_BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_-])"
_CASE_ID_BOUNDARY_AFTER = r"(?![A-Za-z0-9_-])"

SPEC = (
    Path(__file__).resolve().parents[2]
    / "docs/superpowers/specs/2026-09-15-locus-policy-live-validation-design.md"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _spec() -> str:
    return SPEC.read_text(encoding="utf-8")


def _table_cells(prefix: str) -> dict[str, str]:
    # test-time oracle: rows ``| <id> | <text> | ...`` -> second cell, verbatim
    cells: dict[str, str] = {}
    for line in _spec().splitlines():
        if line.startswith(f"| {prefix}"):
            parts = [c.strip() for c in line.strip().strip("|").split("|")]
            cells[parts[0]] = parts[1]
    return cells


def _bullets_after(heading: str) -> str:
    text = _spec()
    start = text.index(heading) + len(heading)
    lines: list[str] = []
    for line in text[start:].splitlines()[1:]:
        if not line.startswith("- "):
            break
        lines.append(line)
    return "\n".join(lines)


def _section_body(start_prefix: str, end_prefix: str) -> str:
    # test-time oracle: the text strictly between two "## N." headings, stripped
    lines = _spec().splitlines()
    start_idx = next(i for i, line in enumerate(lines) if line.startswith(start_prefix))
    end_idx = next(i for i, line in enumerate(lines) if line.startswith(end_prefix))
    return "\n".join(lines[start_idx + 1 : end_idx]).strip()


def _contains_case_id_token(text: str) -> bool:
    return any(
        re.search(_CASE_ID_BOUNDARY_BEFORE + re.escape(case_id) + _CASE_ID_BOUNDARY_AFTER, text)
        for case_id in CASE_IDS
    )


def _all_keys() -> list[tuple[str, str]]:
    return [(ledger, case_id) for ledger in LEDGERS for case_id in CASE_IDS]


def test_vocabularies_are_locked_verbatim() -> None:
    assert CASE_IDS == ("S01", "V01", "V02", "V03", "V04", "V05")
    assert FAILURE_TAGS == (
        "OVER_SPLIT",
        "UNDER_SPLIT",
        "MISSING_EXTENSION",
        "DUPLICATE_ASSERTION",
        "MISSING_SUPERSEDE",
        "WRONG_SUPERSEDE_TARGET",
        "CONFLICT_INSTEAD_OF_CORRECTION",
        "UNGOVERNED_SUPERSEDE",
        "WRONG_BIND",
        "EXTRA_DRAFT",
    )
    assert OUTCOMES == (
        "LOCUS_POLICY_VALIDATED",
        "LOCUS_POLICY_NOT_VALIDATED",
        "EXPERIMENT_INCONCLUSIVE",
    )
    assert SEMANTIC_ASSERTION_IDS == ("A-S01", "A-V01", "A-V02", "A-V03", "A-V05")
    assert "A-V04" not in SEMANTIC_ASSERTION_IDS
    assert tuple(SEMANTIC_QUESTIONS) == SEMANTIC_ASSERTION_IDS
    assert tuple(HYPOTHESES) == ("H0", "H1", "H2", "H3", "H4")


def test_cases_per_ledger_carry_class_and_revised_document() -> None:
    expected_classes = {
        "S01": "SEED",
        "V01": "COMPATIBLE_EXTENSION",
        "V02": "COMPATIBLE_EXTENSION",
        "V03": "DISTINCT_LOCUS",
        "V04": "RESTATEMENT",
        "V05": "CORRECTION",
    }
    expected_slot = {"S01": 0, "V01": 0, "V02": 1, "V03": 1, "V04": 2, "V05": 3}
    for ledger in LEDGERS:
        cases = CASES[ledger]
        assert [c.id for c in cases] == list(CASE_IDS)
        for case in cases:
            assert isinstance(case, Case)
            assert case.semantic_class == expected_classes[case.id]
            assert case.document == DOCUMENTS[ledger][expected_slot[case.id]]
    assert [c.document for c in CASES["alpha"]] == ["A1", "A1", "A2", "A2", "A3", "A4"]
    assert [c.document for c in CASES["beta"]] == ["B1", "B1", "B2", "B2", "B3", "B4"]


def test_case_rejects_an_unknown_semantic_class() -> None:
    with pytest.raises(ValidationError):
        Case(id="V01", semantic_class="MERGE", document="A1")  # type: ignore[arg-type]


def test_hypotheses_are_the_spec_2_cells_verbatim() -> None:
    assert _table_cells("H") == HYPOTHESES
    assert HYPOTHESES["H0"].startswith("**Creation granularity.**")
    assert "`SUPERSEDE`" in HYPOTHESES["H4"]


def test_expected_state_is_the_spec_6_bullet_text_verbatim() -> None:
    assert tuple(EXPECTED_STATE) == ("T1", "T2")
    assert EXPECTED_STATE["T1"] == _bullets_after("**After T1 (seed, S01):**")
    assert EXPECTED_STATE["T2"] == _bullets_after("**After T2 (revision):**")
    assert EXPECTED_STATE["T1"].count("\n") == 2
    assert EXPECTED_STATE["T2"].count("\n") == 7
    assert "`human_authorizations == 0`" in EXPECTED_STATE["T2"]


def test_assertion_text_is_the_spec_7_1_row_per_case_verbatim() -> None:
    rows = _table_cells("S01") | _table_cells("V0")
    assert tuple(ASSERTION_TEXT) == CASE_IDS
    for case_id in CASE_IDS:
        assert ASSERTION_TEXT[case_id] == rows[case_id], case_id
    assert ASSERTION_TEXT["S01"].startswith("`len(addresses) == 4`")
    assert "`REQUIRE_SECOND_LENS`" in ASSERTION_TEXT["V05"]


def test_semantic_questions_are_the_spec_7_2_rows_verbatim() -> None:
    rows = _table_cells("A-")
    assert set(rows) == set(SEMANTIC_ASSERTION_IDS)
    for assertion_id in SEMANTIC_ASSERTION_IDS:
        assert SEMANTIC_QUESTIONS[assertion_id] == rows[assertion_id], assertion_id
    assert "α:" in SEMANTIC_QUESTIONS["A-V01"] and "β:" in SEMANTIC_QUESTIONS["A-V01"]


def test_case_outcome_rules_bind_each_case_to_its_semantic_assertion() -> None:
    assert tuple(CASE_OUTCOME_RULES) == CASE_IDS
    for case_id, rule in CASE_OUTCOME_RULES.items():
        assert isinstance(rule, CaseOutcomeRule) and rule.case_id == case_id
    assert CASE_OUTCOME_RULES["V04"].semantic_assertion_id is None
    assert CASE_OUTCOME_RULES["S01"].semantic_assertion_id == "A-S01"
    assert CASE_OUTCOME_RULES["V05"].semantic_assertion_id == "A-V05"
    assert "PASS iff" in SCORING_RULE


def test_case_passes_requires_structural_and_semantic_yes_where_one_exists() -> None:
    with_semantic = CASE_OUTCOME_RULES["V01"]
    assert with_semantic.case_passes(structural=True, semantic=True) is True
    assert with_semantic.case_passes(structural=True, semantic=False) is False
    assert with_semantic.case_passes(structural=False, semantic=True) is False
    assert with_semantic.case_passes(structural=False, semantic=False) is False
    with pytest.raises(ValueError, match="A-V01"):
        with_semantic.case_passes(structural=True, semantic=None)
    without = CASE_OUTCOME_RULES["V04"]
    assert without.case_passes(structural=True, semantic=None) is True
    assert without.case_passes(structural=False, semantic=None) is False
    with pytest.raises(ValueError, match="V04"):
        without.case_passes(structural=True, semantic=True)


def test_experiment_outcome_truth_table() -> None:
    keys = _all_keys()
    assert len(keys) == 12
    all_true = dict.fromkeys(keys, True)
    assert experiment_outcome(rule_zero=False, case_passes=all_true) == "LOCUS_POLICY_VALIDATED"
    assert experiment_outcome(rule_zero=True, case_passes=all_true) == "EXPERIMENT_INCONCLUSIVE"
    for key in keys:
        one_false = all_true | {key: False}
        assert experiment_outcome(rule_zero=False, case_passes=one_false) == (
            "LOCUS_POLICY_NOT_VALIDATED"
        ), key
        assert experiment_outcome(rule_zero=True, case_passes=one_false) == (
            "EXPERIMENT_INCONCLUSIVE"
        ), key
    all_false = dict.fromkeys(keys, False)
    assert experiment_outcome(rule_zero=False, case_passes=all_false) == (
        "LOCUS_POLICY_NOT_VALIDATED"
    )
    # replicate disagreement is NOT_VALIDATED, never a third value
    alpha_only = {k: k[0] == "alpha" for k in keys}
    assert experiment_outcome(rule_zero=False, case_passes=alpha_only) == (
        "LOCUS_POLICY_NOT_VALIDATED"
    )
    # exhaustive: 2^12 vectors; VALIDATED iff every instance passes, never a third value
    for bits in itertools.product((True, False), repeat=12):
        passes = dict(zip(keys, bits, strict=True))
        outcome = experiment_outcome(rule_zero=False, case_passes=passes)
        assert outcome in OUTCOMES and outcome != "EXPERIMENT_INCONCLUSIVE"
        assert (outcome == "LOCUS_POLICY_VALIDATED") is all(bits)


def test_experiment_outcome_requires_exactly_the_twelve_case_instances() -> None:
    keys = _all_keys()
    complete = dict.fromkeys(keys, True)
    with pytest.raises(ValueError):
        experiment_outcome(rule_zero=False, case_passes={k: True for k in keys[:-1]})
    with pytest.raises(ValueError):
        experiment_outcome(rule_zero=False, case_passes=complete | {("alpha", "V06"): True})
    with pytest.raises(ValueError):
        experiment_outcome(rule_zero=False, case_passes=complete | {("gamma", "S01"): True})
    with pytest.raises(ValueError):
        experiment_outcome(rule_zero=True, case_passes={})


def test_state_machines_are_the_spec_10_11_sections_verbatim() -> None:
    assert _section_body("## 10.", "## 11.") == IDENTITY_STATE_MACHINE
    assert _section_body("## 11.", "## 12.") == FREEZE_STATE_MACHINE
    assert IDENTITY_STATE_MACHINE.startswith("```\nUNSEALED")
    assert FREEZE_STATE_MACHINE.startswith("```\nSEAL COMMIT")
    assert "ADJUDICATED" in IDENTITY_STATE_MACHINE
    assert "ADJUDICATION COMMIT" in FREEZE_STATE_MACHINE
    # spec §16: no case id token (checked with the same standalone-token boundary
    # rule the sealed leakage matcher uses for CHECKPOINT_LABEL, so a compound
    # identifier like `A-S01` is correctly not a case id occurrence)
    assert not _contains_case_id_token(IDENTITY_STATE_MACHINE)
    assert not _contains_case_id_token(FREEZE_STATE_MACHINE)


def test_expectations_document_is_canonical_deterministic_and_complete() -> None:
    first = expectations_document()
    second = expectations_document()
    assert first == second
    dumped = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert json.dumps(first, separators=(",", ":"), ensure_ascii=False) == dumped
    assert first["case_ids"] == list(CASE_IDS)
    assert first["failure_tags"] == list(FAILURE_TAGS)
    assert first["outcomes"] == list(OUTCOMES)
    assert first["semantic_assertion_ids"] == list(SEMANTIC_ASSERTION_IDS)
    assert first["hypotheses"] == HYPOTHESES
    assert first["expected_state"] == EXPECTED_STATE
    assert first["assertion_text"] == ASSERTION_TEXT
    assert first["semantic_questions"] == SEMANTIC_QUESTIONS
    assert first["scoring_rule"] == SCORING_RULE
    assert first["identity_state_machine"] == IDENTITY_STATE_MACHINE
    assert first["freeze_state_machine"] == FREEZE_STATE_MACHINE
    assert [c["id"] for c in first["cases"]["alpha"]] == list(CASE_IDS)
    assert [c["id"] for c in first["cases"]["beta"]] == list(CASE_IDS)
    assert first["case_outcome_rules"]["V04"]["semantic_assertion_id"] is None
    # no runtime id and no evidence text
    assert not re.search(r"ADDR-|CLAIM-|JDG-", dumped)
    assert "Normative rule" not in dumped and "Q: " not in dumped


def test_corpus_does_not_import_expectations() -> None:
    tree = ast.parse(Path(corpus_module.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not any("expectations" in m for m in mods)
