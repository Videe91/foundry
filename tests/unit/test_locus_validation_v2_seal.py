"""Locus validation v2: corpus, answer key, leakage, identity and the preflight gates.

These are the freeze checks. The corpus and expectations digests are pinned (any edit after
sealing fails here first); the proposition inventory must agree with every expected claim
count, so no case assumes one claim per document; the answer key never reaches the request
path; the orion ledger is 9P3's sealed locus-H bytes; and every preflight gate refuses the
fact it exists to catch.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import XAILocusSemanticReasoner
from foundry.domain.evidence import sha256_of_content
from foundry.experiments.locus_validation.recording import IdentityDrift, require_locus_identity
from foundry.experiments.locus_validation_v2 import protocol
from foundry.experiments.locus_validation_v2.corpus import (
    DOCUMENTS,
    SEED_WORLDS,
    corpus_sha256,
)
from foundry.experiments.locus_validation_v2.expectations import (
    ADDRESSES,
    CASES,
    PROPOSITIONS,
    REVISED_ITEMS,
    SEED_ITEMS,
    SEMANTIC_QUESTIONS,
    expectations_document,
    expectations_sha256,
)
from foundry.experiments.locus_validation_v2.seal import (
    GATE_NAMES,
    NINE_P3_H,
    GitFacts,
    build_manifest,
    leakage_findings,
    preflight_gates,
)

PACKAGE = Path(__file__).resolve().parents[2] / "src/foundry/experiments/locus_validation_v2"
NINE_P3 = Path("docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1")

CORPUS_SHA256 = "acde42feef7f16a80612ee40ebde5b9958e3ac7b7801fc1791a38ad051de505f"
EXPECTATIONS_SHA256 = "2151089506afcf7af3d037a75313308169a7e10452c123dfc8c21d9fb96a2c9b"


# --------------------------------------------------------------------------- freeze


def test_the_corpus_and_expectations_are_pinned() -> None:
    assert corpus_sha256() == CORPUS_SHA256
    assert expectations_sha256() == EXPECTATIONS_SHA256
    assert expectations_document() == expectations_document()


def test_the_orion_ledger_is_9p3_sealed_locus_h_byte_for_byte() -> None:
    manifest = json.loads((NINE_P3 / "manifest.json").read_text())
    sealed = {r["evidence_id"]: r for r in manifest["evidence"]}
    for key, (evidence_id, digest) in NINE_P3_H.items():
        text = DOCUMENTS[key].text
        assert sha256_of_content(text) == digest == sealed[evidence_id]["content_sha256"]
        assert len(text.encode("utf-8")) == sealed[evidence_id]["content_bytes"]


# --------------------------------------------------------------------------- the answer key


def test_every_proposition_lives_at_an_expected_address() -> None:
    keys = {a.key for a in ADDRESSES}
    assert {p.address for p in PROPOSITIONS} <= keys
    known = {p.id for p in PROPOSITIONS} | {
        c.key for w in SEED_WORLDS.values() for a in w for c in a.claims
    }
    assert all(p.of in known for p in PROPOSITIONS if p.of is not None)


def test_claim_counts_follow_the_inventory_never_one_claim_per_document() -> None:
    """Each address's expected claims == the propositions the inventory places there."""
    seeded = Counter(a.key for w in SEED_WORLDS.values() for a in w for _ in a.claims)
    t1 = Counter(p.address for p in PROPOSITIONS if p.relation == "SEED") + seeded
    adds = Counter(
        p.address for p in PROPOSITIONS if p.relation in ("EXTENDS", "NEW_LOCUS", "CORRECTS")
    )
    for a in ADDRESSES:
        if a.live_claims_after_t1 is not None:
            assert a.live_claims_after_t1 == t1[a.key], a.key
        assert a.live_claims_after_t2 == t1[a.key] + adds[a.key], a.key
    multi = [d for d, n in Counter(p.document for p in PROPOSITIONS).items() if n > 1]
    assert len(multi) >= 8, "the corpus must exercise multi-proposition documents"


def test_every_item_expectation_agrees_with_the_inventory() -> None:
    for item in (*SEED_ITEMS, *REVISED_ITEMS):
        placed = Counter(
            p.address
            for p in PROPOSITIONS
            if p.document == item.document
            and p.relation in ("SEED", "EXTENDS", "NEW_LOCUS", "CORRECTS")
        )
        assert dict(placed) == item.new_claims, item.document
        restated = [
            p.of for p in PROPOSITIONS if p.document == item.document and p.relation == "RESTATES"
        ]
        if item.must_support:
            assert tuple(restated) == item.must_support


def test_every_case_and_question_is_wired() -> None:
    assert [c.id for c in CASES] == [
        "C0-CORE-SEED",
        "C1-RESTATEMENT",
        "C2-EXTENSION",
        "C3-NEW-LOCUS",
        "C4-CORRECTION",
        "C5-EXISTING-CONFLICT",
        "C6-NEARBY",
        "C7-C09-REGRESSION",
        "C8-LARGE-WORLD",
    ]
    question_ids = {q.id for q in SEMANTIC_QUESTIONS}
    assert {q for c in CASES for q in c.semantic} == question_ids
    assert {q.case for q in SEMANTIC_QUESTIONS} <= {c.id for c in CASES}


def test_the_large_world_has_exactly_sixteen_nearby_addresses() -> None:
    assert len(SEED_WORLDS["large"]) == 16
    assert sum(1 for a in ADDRESSES if a.ledger == "large") == 16


def test_the_conflict_world_holds_two_incompatible_claims_at_one_address() -> None:
    (address,) = SEED_WORLDS["conflict"]
    assert len(address.claims) == 2
    assert {c.predicate for c in address.claims} == {"idle session expiry"}
    assert len({c.text for c in address.claims}) == 2


# --------------------------------------------------------------------------- leakage


def test_no_model_visible_text_names_the_answer_key() -> None:
    assert leakage_findings(PACKAGE) == ()


def test_the_leakage_gate_catches_a_request_path_import_of_the_answer_key(tmp_path: Path) -> None:
    copy = tmp_path / "pkg"
    shutil.copytree(PACKAGE, copy)
    runner = copy / "runner.py"
    runner.write_text(
        "from foundry.experiments.locus_validation_v2.expectations import CASES\n"
        + runner.read_text()
    )
    assert any("runner" in f for f in leakage_findings(copy))


# --------------------------------------------------------------------------- identity


def test_the_identity_guard_accepts_exactly_the_policy_under_test() -> None:
    require_locus_identity(
        XAILocusSemanticReasoner(api_key="k", model=protocol.MODEL, reasoning_effort="high")
    )
    for model, effort in (("grok-4.7", "high"), (protocol.MODEL, "low")):
        with pytest.raises(IdentityDrift):
            require_locus_identity(
                XAILocusSemanticReasoner(api_key="k", model=model, reasoning_effort=effort)
            )


# --------------------------------------------------------------------------- preflight


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
        "sealed_manifest": build_manifest(harness_sha="harness"),
        "sealed_expectations": expectations_document(),
        "git": git,
        "grpc_dns_resolver": "native",
        "raw_present": (),
        "package_dir": PACKAGE,
    }
    facts.update(overrides)
    return facts


def _failed(**overrides: Any) -> set[str]:
    return {g.name for g in preflight_gates(**_facts(**overrides)) if not g.passed}


def test_every_gate_passes_on_a_correct_seal() -> None:
    gates = preflight_gates(**_facts())
    assert tuple(g.name for g in gates) == GATE_NAMES
    assert _failed() == set()


def test_each_gate_refuses_its_fact() -> None:
    out = protocol.EXPERIMENT_ARTIFACT_DIR
    base = _facts()["git"]
    tampered_manifest = {**build_manifest(harness_sha="harness"), "model": "grok-4.7"}
    tampered_expectations = {**expectations_document(), "cases": []}
    assert _failed(sealed_manifest=tampered_manifest) == {"manifest_matches_code"}
    assert _failed(sealed_expectations=tampered_expectations) == {"expectations_match_code"}
    assert "seal_commit_adds_exactly_the_sealed_files" in _failed(
        git=base.model_copy(update={"head_changed_files": (*base.head_changed_files, "src/x.py")})
    )
    assert _failed(git=base.model_copy(update={"head_parent_sha": "other"})) == {
        "seal_parent_is_the_harness"
    }
    assert _failed(git=base.model_copy(update={"worktree_clean": False})) == {"worktree_clean"}
    assert _failed(grpc_dns_resolver=None) == {"grpc_dns_resolver_native"}
    assert _failed(raw_present=("run.json",)) == {"single_use"}
    assert _failed(sealed_manifest=None) >= {"manifest_matches_code", "seal_parent_is_the_harness"}
    assert f"{out}manifest.json" in base.head_added_files
