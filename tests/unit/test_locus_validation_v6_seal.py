"""Locus validation v6: leakage, identity guard, manifest and preflight gates (design §10).

The seal freezes everything the run depends on; every preflight gate refuses the fact it
exists to catch; the answer key never reaches the request path; the identity guard admits
only ``intent-v2-locus-v6`` with its TARGET_SET law; every governor runs correction sets; and
the historical v5 identity and the frozen long-horizon run are untouched.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics import xai_reasoner
from foundry.adapters.semantics.xai_reasoner import (
    REPROPOSAL_SYSTEM_INSTRUCTION,
    XAICorrectionSetSemanticReasoner,
    XAIReproposingSemanticReasoner,
)
from foundry.domain.evidence import sha256_of_content
from foundry.experiments.locus_validation_v5 import protocol as v5_protocol
from foundry.experiments.locus_validation_v6 import expectations, protocol, world
from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS
from foundry.experiments.locus_validation_v6.recording import (
    IdentityDrift,
    require_accounting_policy_identity,
)
from foundry.experiments.locus_validation_v6.seal import (
    GATE_NAMES,
    GitFacts,
    build_manifest,
    leakage_findings,
    preflight_gates,
)

PACKAGE = Path(__file__).resolve().parents[2] / "src/foundry/experiments/locus_validation_v6"
LONG_HORIZON = Path("docs/superpowers/experiments/2026-09-29-ie2-ie3-long-horizon-v1")


def _reasoner(cls: type = XAICorrectionSetSemanticReasoner) -> Any:
    return cls(api_key="k")


# ------------------------------------------------------------------ leakage


def test_no_model_visible_text_names_the_answer_key_and_no_request_module_imports_it() -> None:
    assert leakage_findings(PACKAGE) == ()


def test_the_leakage_gate_catches_answer_key_words_and_imports(tmp_path: Path) -> None:
    copy = tmp_path / "pkg"
    shutil.copytree(PACKAGE, copy)
    runner = copy / "runner.py"
    runner.write_text(
        runner.read_text() + "\nfrom foundry.experiments.locus_validation_v6 import expectations\n"
    )
    assert any("imports the answer key" in f for f in leakage_findings(copy))


def test_no_dense_document_carries_a_policy_term() -> None:
    from foundry.experiments.locus_validation_v6.seal import ANSWER_KEY_VOCABULARY

    for doc in DOCUMENTS.values():
        if doc.ledger == "dense":
            assert not [w for w in ANSWER_KEY_VOCABULARY if w.lower() in doc.text.lower()], doc.key


# ------------------------------------------------------------------ identity


def test_the_identity_guard_accepts_exactly_the_policy_under_test() -> None:
    require_accounting_policy_identity(_reasoner())


def test_the_identity_guard_refuses_the_v5_policy() -> None:
    with pytest.raises(IdentityDrift):
        require_accounting_policy_identity(_reasoner(XAIReproposingSemanticReasoner))


def test_the_identity_guard_refuses_a_one_target_law(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(XAICorrectionSetSemanticReasoner, "correction_law", "ONE_TARGET")
    with pytest.raises(IdentityDrift, match="correction_law"):
        require_accounting_policy_identity(_reasoner())


def test_the_v6_prompt_is_byte_identical_and_v5_history_is_untouched() -> None:
    v6 = hashlib.sha256(XAICorrectionSetSemanticReasoner.system_instruction.encode()).hexdigest()
    assert v6 == protocol.PROMPT_SHA256_FROZEN
    v5 = hashlib.sha256(REPROPOSAL_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert v5 == v5_protocol.PROMPT_SHA256_FROZEN
    assert v5_protocol.EXPERIMENT_VERSION == "intent-v2-locus-validation-v5"
    # A successor identity exists since the runtime reset (Q1, ``intent-v2-locus-v7``); it is
    # a separate class and contract, v6 is byte-identical, and this guard still refuses it.
    assert XAICorrectionSetSemanticReasoner.policy_version == "intent-v2-locus-v6"
    assert XAICorrectionSetSemanticReasoner.draft_payload.__name__ == "AccountedDraftPayload"
    with pytest.raises(IdentityDrift):
        require_accounting_policy_identity(_reasoner(xai_reasoner.XAIConflictSemanticReasoner))


def test_the_long_horizon_run_is_untouched() -> None:
    files = sorted(p.name for p in LONG_HORIZON.iterdir() if p.is_file())
    assert "report.md" in files and "run.json" in files
    report = (LONG_HORIZON / "report.md").read_text()
    assert "LONG_HORIZON_IE2_IE3_NOT_VALIDATED" in report
    assert not any("interpretation" in name for name in files)


# ------------------------------------------------------------------ manifest and gates


def _facts(**overrides: Any) -> dict[str, Any]:
    out = protocol.EXPERIMENT_ARTIFACT_DIR
    git = GitFacts(
        head_sha="seal",
        head_parent_sha="harness",
        head_added_files=(f"{out}manifest.json", f"{out}expectations.json"),
        head_changed_files=(f"{out}manifest.json", f"{out}expectations.json"),
        worktree_clean=True,
    )
    facts: dict[str, Any] = {
        "sealed_manifest": build_manifest(harness_sha="harness", package_dir=PACKAGE),
        "sealed_expectations": expectations.expectations_document(),
        "git": git,
        "grpc_dns_resolver": "native",
        "raw_present": (),
        "package_dir": PACKAGE,
    }
    facts.update(overrides)
    return facts


def _failed(**overrides: Any) -> set[str]:
    return {g.name for g in preflight_gates(**_facts(**overrides)) if not g.passed}


def test_the_manifest_freezes_everything_the_run_depends_on() -> None:
    m = build_manifest(harness_sha="harness", package_dir=PACKAGE)
    assert m == build_manifest(harness_sha="harness", package_dir=PACKAGE)
    assert m["experiment_version"] == "intent-v2-locus-validation-v6"
    assert m["policy_version"] == "intent-v2-locus-v6"
    assert m["prompt_sha256"] == protocol.PROMPT_SHA256_FROZEN
    assert m["output_schema_sha256"] == protocol.OUTPUT_SCHEMA_SHA256_FROZEN
    assert m["correction_law"] == "TARGET_SET"
    assert m["admission"] == {"canonical_facets": True, "correction_sets": True}
    assert m["authority"]["protocol"] == "ie2-authority-routing-v2"
    assert m["authority"]["actor"] == protocol.ARCHITECT
    assert m["authority"]["branches"] == ["AGREE", "DECLINE"]
    assert (m["provider"], m["model"], m["reasoning_effort"]) == ("xai", "grok-4.6", "high")
    assert m["budgets"] == {
        "calls_per_delta": 2,
        "max_frontier_calls": 26,
        "max_cost_usd": 8.0,
        "retries": 0,
        "judge_calls": 0,
    }
    dense = m["dense_density"]
    assert dense["documents"] >= 12 and dense["characters"] >= 8000
    assert dense["propositions"] >= 30 and dense["concerns"] == 9
    assert m["expectations_sha256"] == expectations.expectations_sha256()
    assert m["adjudication_questions_sha256"] == expectations.adjudication_questions_sha256()
    assert set(m["scoring_sources_sha256"]) == {
        "evaluation.py",
        "adjudication.py",
        "expectations.py",
        "authority.py",
    }
    assert set(m["decision_records_sha256"]) == {
        protocol.GRAIN_DECISION_PATH,
        protocol.DESIGN_SPEC_PATH,
    }
    for key, digest in m["v5_regression_text_sha256"].items():
        assert sha256_of_content(DOCUMENTS[key].text) == digest


def test_every_gate_passes_on_a_correct_seal() -> None:
    gates = preflight_gates(**_facts())
    assert tuple(g.name for g in gates) == GATE_NAMES
    assert [g.name for g in gates if not g.passed] == []


def test_each_gate_refuses_its_fact() -> None:
    base = _facts()["git"]
    assert _failed(sealed_manifest={"harness_sha": "harness"}) >= {"manifest_matches_code"}
    assert _failed(sealed_expectations={}) == {"expectations_match_code"}
    assert "seal_commit_adds_exactly_the_sealed_files" in _failed(
        git=base.model_copy(update={"head_added_files": ("x",)})
    )
    assert "seal_parent_is_the_harness" in _failed(
        git=base.model_copy(update={"head_parent_sha": "other"})
    )
    assert _failed(git=base.model_copy(update={"worktree_clean": False})) == {"worktree_clean"}
    assert _failed(grpc_dns_resolver="ares") == {"grpc_dns_resolver_native"}
    assert _failed(raw_present=("run.json",)) == {"single_use"}


def test_the_admission_gate_refuses_a_governor_without_correction_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(world, "CORRECTION_SETS", False)
    assert "correction_set_admission" in _failed()


def test_the_identity_gate_refuses_a_one_target_law(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(XAICorrectionSetSemanticReasoner, "correction_law", "ONE_TARGET")
    assert "policy_identity" in _failed()


def test_the_coverage_gate_refuses_a_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(expectations, "source_coverage_findings", lambda: ("UNMAPPED: x",))
    assert "source_coverage_complete" in _failed()


def test_an_edited_scoring_rule_after_the_seal_is_refused(tmp_path: Path) -> None:
    copy = tmp_path / "pkg"
    shutil.copytree(PACKAGE, copy)
    sealed = build_manifest(harness_sha="harness", package_dir=copy)
    (copy / "evaluation.py").write_text((copy / "evaluation.py").read_text() + "\n# edited\n")
    assert "manifest_matches_code" in _failed(sealed_manifest=sealed, package_dir=copy)
