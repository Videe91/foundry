"""Locus validation v3: corpus, answer key, leakage, identity and the preflight gates.

These are the freeze checks. The corpus, expectations and adjudication-question digests are
pinned (any edit after sealing fails here first); the proposition inventory must agree with
every expected claim count, so no case assumes one claim per document; the answer key never
reaches the request path; the orion ledger is 9P3's sealed locus-H bytes and the C6 inputs
are validation v2's sealed bytes; the large world is formed by the model, not hand-written;
and every preflight gate refuses the fact it exists to catch.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    XAIGovernedConcernSemanticReasoner,
    XAILocusSemanticReasoner,
)
from foundry.domain.evidence import sha256_of_content
from foundry.experiments.locus_validation_v3 import protocol
from foundry.experiments.locus_validation_v3.corpus import (
    DOCUMENTS,
    REVISION,
    SEED_DOCUMENTS,
    SEED_WORLDS,
    corpus_sha256,
)
from foundry.experiments.locus_validation_v3.expectations import (
    ADDRESSES,
    CASES,
    CRITICAL_CASE,
    EXPECTED_ADDRESS_COUNTS,
    EXPECTED_SEPARATE,
    LARGE_KEYS,
    PROPOSITIONS,
    REVISED_ITEMS,
    SEED_ITEMS,
    SEMANTIC_QUESTIONS,
    adjudication_questions_sha256,
    expectations_document,
    expectations_sha256,
)
from foundry.experiments.locus_validation_v3.recording import (
    IdentityDrift,
    require_governed_concern_identity,
)
from foundry.experiments.locus_validation_v3.seal import (
    GATE_NAMES,
    NINE_P3_H,
    V2_REGRESSION_TEXT,
    GitFacts,
    build_manifest,
    leakage_findings,
    preflight_gates,
)

PACKAGE = Path(__file__).resolve().parents[2] / "src/foundry/experiments/locus_validation_v3"
NINE_P3 = Path("docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1")
V2 = Path("docs/superpowers/experiments/2026-09-28-locus-validation-v2")

CORPUS_SHA256 = "cc6b87e7f21c66f7d9816247e4dda1878e21a0f829f75a467555400ae16723e6"
EXPECTATIONS_SHA256 = "611823d8f5a0ea2e9953aafaedc02724b6a81ef5e1d5436e14065c5d1bbca7f5"
ADJUDICATION_QUESTIONS_SHA256 = "72daf61642306ba8222c6dc18a8f1fbc505a3515d3903559577243bef3f10988"


# --------------------------------------------------------------------------- freeze


def test_the_corpus_expectations_and_questions_are_pinned() -> None:
    assert corpus_sha256() == CORPUS_SHA256
    assert expectations_sha256() == EXPECTATIONS_SHA256
    assert adjudication_questions_sha256() == ADJUDICATION_QUESTIONS_SHA256
    assert expectations_document() == expectations_document()


def test_the_orion_ledger_is_9p3_sealed_locus_h_byte_for_byte() -> None:
    manifest = json.loads((NINE_P3 / "manifest.json").read_text())
    sealed = {r["evidence_id"]: r for r in manifest["evidence"]}
    for key, (evidence_id, digest) in NINE_P3_H.items():
        text = DOCUMENTS[key].text
        assert sha256_of_content(text) == digest == sealed[evidence_id]["content_sha256"]
        assert len(text.encode("utf-8")) == sealed[evidence_id]["content_bytes"]


def test_the_core_texts_shared_with_v2_are_v2s_sealed_bytes() -> None:
    """C6 is a regression only if its inputs are the exact bytes that over-split in v2."""
    v2 = {d["key"]: d["text"] for d in json.loads((V2 / "manifest.json").read_text())["corpus"]
          ["documents"]}  # fmt: skip
    for key, digest in V2_REGRESSION_TEXT.items():
        assert sha256_of_content(v2[key]) == digest == sha256_of_content(DOCUMENTS[key].text)
    shared = [d for d in DOCUMENTS.values() if d.ledger == "core" and d.key in v2]
    assert len(shared) == 10
    for doc in shared:
        assert doc.text == v2[doc.key], doc.key


def test_the_policy_under_test_is_the_governed_concern_policy() -> None:
    assert XAIGovernedConcernSemanticReasoner.policy_version == protocol.POLICY_VERSION_FROZEN
    assert XAIGovernedConcernSemanticReasoner.__name__ == protocol.REASONER_CLASS_FROZEN
    assert protocol.MODEL == "grok-4.6" and protocol.REASONING_EFFORT == "high"


# --------------------------------------------------------------------------- the answer key


def test_every_proposition_lives_at_an_expected_address() -> None:
    keys = {a.key for a in ADDRESSES}
    assert {p.address for p in PROPOSITIONS} <= keys
    known = {p.id for p in PROPOSITIONS} | {
        c.key for w in SEED_WORLDS.values() for a in w for c in a.claims
    }
    assert all(p.of in known for p in PROPOSITIONS if p.of is not None)
    assert len({p.id for p in PROPOSITIONS}) == len(PROPOSITIONS)


def test_every_document_has_its_propositions_enumerated() -> None:
    enumerated = {p.document for p in PROPOSITIONS}
    seeded = {c.document for w in SEED_WORLDS.values() for a in w for c in a.claims}
    assert set(DOCUMENTS) == enumerated | seeded


def test_claim_counts_follow_the_inventory_never_one_claim_per_document() -> None:
    """Each address's expected claims == the propositions the inventory places there."""
    seeded = Counter(a.key for w in SEED_WORLDS.values() for a in w for _ in a.claims)
    t1 = Counter(p.address for p in PROPOSITIONS if p.relation == "SEED") + seeded
    adds = Counter(
        p.address for p in PROPOSITIONS if p.relation in ("EXTENDS", "NEW_CONCERN", "CORRECTS")
    )
    for a in ADDRESSES:
        if a.live_claims_after_t1 is not None:
            assert a.live_claims_after_t1 == t1[a.key], a.key
        assert a.live_claims_after_t2 == t1[a.key] + adds[a.key], a.key
    multi = [d for d, n in Counter(p.document for p in PROPOSITIONS).items() if n > 1]
    assert len(multi) >= 12, "the corpus must exercise multi-proposition documents"


def test_every_item_expectation_agrees_with_the_inventory() -> None:
    for item in (*SEED_ITEMS, *REVISED_ITEMS):
        placed = Counter(
            p.address
            for p in PROPOSITIONS
            if p.document == item.document
            and p.relation in ("SEED", "EXTENDS", "NEW_CONCERN", "CORRECTS")
        )
        assert dict(placed) == item.new_claims, item.document
        restated = [
            p.of for p in PROPOSITIONS if p.document == item.document and p.relation == "RESTATES"
        ]
        if item.must_support:
            assert tuple(restated) == item.must_support
    items = {i.document for i in (*SEED_ITEMS, *REVISED_ITEMS)}
    model_docs = {
        d.key
        for ledger in protocol.LEDGERS
        for d in (*(SEED_DOCUMENTS[ledger] if ledger in protocol.MODEL_SEEDED else ()),
                  *REVISION[ledger])
    }  # fmt: skip
    assert items == model_docs


def test_address_counts_agree_with_the_addresses() -> None:
    for ledger, (t1, t2) in EXPECTED_ADDRESS_COUNTS.items():
        mine = [a for a in ADDRESSES if a.ledger == ledger]
        assert sum(1 for a in mine if a.live_claims_after_t1 is not None) == t1, ledger
        assert len(mine) == t2, ledger


def test_every_case_and_question_is_wired() -> None:
    assert [c.id for c in CASES] == [
        "C0-CORE-SEED",
        "C1-RESTATEMENT",
        "C2-EXTENSION",
        "C3-NEW-CONCERN",
        "C4-CORRECTION",
        "C5-EXISTING-CONFLICT",
        "C6-LATE-DELIVERY",
        "C7-C09-REGRESSION",
        "C8-LARGE-WORLD",
        "U1-CANCEL-VS-AUDIT",
        "U2-LATE-VS-DAMAGE",
        "U3-COMPENSATION-VS-SETTLEMENT",
        "U4-CUSTOMER-VS-SUPPLIER-REFUND",
    ]
    assert CRITICAL_CASE == "C7-C09-REGRESSION"
    question_ids = [q.id for q in SEMANTIC_QUESTIONS]
    assert len(question_ids) == len(set(question_ids))
    assert {q for c in CASES for q in c.semantic} == set(question_ids)
    assert {q.case for q in SEMANTIC_QUESTIONS} <= {c.id for c in CASES}
    for q in SEMANTIC_QUESTIONS:
        (case,) = [c for c in CASES if c.id == q.case]
        assert q.id in case.semantic and q.ledger == case.ledger, q.id


def test_every_model_formed_address_is_judged_after_t1() -> None:
    judged = {q.id.removeprefix("Q-T1-") for q in SEMANTIC_QUESTIONS if q.after == 1}
    assert judged == {a.key for a in ADDRESSES if a.origin == "MODEL_T1"}


def test_the_large_world_is_sixteen_model_formed_addresses() -> None:
    """The user's rule: the 16 facets come from the policy under test, not a hand-written seed."""
    assert "large" in protocol.MODEL_SEEDED and "large" not in SEED_WORLDS
    large = [a for a in ADDRESSES if a.ledger == "large"]
    assert len(large) == len(LARGE_KEYS) == len(SEED_DOCUMENTS["large"]) == 16
    assert all(a.origin == "MODEL_T1" for a in large)
    (note,) = REVISION["large"]
    assert note.supersedes is None, "the extension must be found by meaning, not lineage"


def test_the_under_split_pairs_are_the_four_required_ones() -> None:
    assert {(s.a, s.b) for s in EXPECTED_SEPARATE} == {
        ("CANCEL", "AUDIT"),
        ("LATE", "DAMAGE"),
        ("LATE", "SETTLEMENT"),
        ("CUSTOMER-REFUND", "SUPPLIER-OVERPAYMENT"),
    }
    keys = {(a.ledger, a.key) for a in ADDRESSES}
    for s in EXPECTED_SEPARATE:
        assert (s.ledger, s.a) in keys and (s.ledger, s.b) in keys


def test_the_conflict_world_holds_two_incompatible_claims_at_one_address() -> None:
    (address,) = SEED_WORLDS["conflict"]
    assert len(address.claims) == 2
    assert len({c.predicate for c in address.claims}) == 1
    assert len({c.text for c in address.claims}) == 2
    assert set(protocol.LEDGERS) - protocol.MODEL_SEEDED == {"conflict"}


# --------------------------------------------------------------------------- leakage


def test_no_model_visible_text_names_the_answer_key() -> None:
    assert leakage_findings(PACKAGE) == ()


@pytest.mark.parametrize("module", ["expectations", "evaluation", "adjudication"])
def test_the_leakage_gate_catches_a_request_path_import_of_the_answer_key(
    tmp_path: Path, module: str
) -> None:
    copy = tmp_path / "pkg"
    shutil.copytree(PACKAGE, copy)
    runner = copy / "runner.py"
    runner.write_text(
        f"from foundry.experiments.locus_validation_v3.{module} import X\n" + runner.read_text()
    )
    assert any("runner" in f for f in leakage_findings(copy))


# --------------------------------------------------------------------------- identity


def test_the_identity_guard_accepts_exactly_the_policy_under_test() -> None:
    require_governed_concern_identity(
        XAIGovernedConcernSemanticReasoner(
            api_key="k", model=protocol.MODEL, reasoning_effort="high"
        )
    )
    for model, effort in (("grok-4.7", "high"), (protocol.MODEL, "low")):
        with pytest.raises(IdentityDrift):
            require_governed_concern_identity(
                XAIGovernedConcernSemanticReasoner(
                    api_key="k", model=model, reasoning_effort=effort
                )
            )


def test_the_identity_guard_refuses_the_previous_policy() -> None:
    with pytest.raises(IdentityDrift):
        require_governed_concern_identity(
            XAILocusSemanticReasoner(api_key="k", model=protocol.MODEL, reasoning_effort="high")
        )


def test_the_identity_guard_refuses_a_shadowed_instruction() -> None:
    reasoner = XAIGovernedConcernSemanticReasoner(
        api_key="k", model=protocol.MODEL, reasoning_effort="high"
    )
    reasoner.system_instruction = reasoner.system_instruction + " "  # type: ignore[misc]
    with pytest.raises(IdentityDrift):
        require_governed_concern_identity(reasoner)


# --------------------------------------------------------------------------- preflight


def _manifest() -> dict[str, Any]:
    return build_manifest(harness_sha="harness", package_dir=PACKAGE)


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
        "sealed_manifest": _manifest(),
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


def test_the_manifest_freezes_everything_the_run_depends_on() -> None:
    manifest = _manifest()
    for key in (
        "design_spec_sha256",
        "corpus_sha256",
        "expectations_sha256",
        "adjudication_questions_sha256",
        "scoring_sources_sha256",
        "policy_version",
        "reasoner_class",
        "prompt_sha256",
        "output_schema_sha256",
        "model",
        "reasoning_effort",
    ):
        assert manifest[key] not in (None, "", "MISSING"), key
    assert set(manifest["scoring_sources_sha256"]) == {
        "evaluation.py",
        "adjudication.py",
        "expectations.py",
    }
    assert "MISSING" not in manifest["scoring_sources_sha256"].values()


def test_every_gate_passes_on_a_correct_seal() -> None:
    gates = preflight_gates(**_facts())
    assert tuple(g.name for g in gates) == GATE_NAMES
    assert _failed() == set()


def test_each_gate_refuses_its_fact(tmp_path: Path) -> None:
    out = protocol.EXPERIMENT_ARTIFACT_DIR
    base = _facts()["git"]
    tampered_expectations = {**expectations_document(), "cases": []}
    assert _failed(sealed_manifest={**_manifest(), "model": "grok-4.7"}) == {
        "manifest_matches_code"
    }
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


def test_an_edited_scoring_rule_after_the_seal_is_refused(tmp_path: Path) -> None:
    copy = tmp_path / "pkg"
    shutil.copytree(PACKAGE, copy)
    evaluation = copy / "evaluation.py"
    evaluation.write_text(evaluation.read_text() + "\n# softened\n")
    assert "manifest_matches_code" in _failed(package_dir=copy)
