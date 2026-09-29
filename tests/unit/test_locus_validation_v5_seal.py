"""Locus validation v5: corpus, source coverage, answer key, leakage, identity and gates.

These are the freeze checks. The corpus, expectations, adjudication-question and
source-coverage digests are pinned; every text is v3's sealed text, so the policy is the only
variable; every sentence of every document is accounted for and v3's H-T9 inventory would be
refused; the claim ranges agree with the inventory; the answer key never reaches the request
path; the identity guard admits only the canonical-facet policy with its concern contract;
and every preflight gate refuses the fact it exists to catch.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, ClassVar

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    SemanticDraftPayload,
    XAIPropositionAccountingSemanticReasoner,
    XAIReproposingSemanticReasoner,
)
from foundry.domain.evidence import sha256_of_content
from foundry.domain.semantic_identity import canonical_facet
from foundry.domain.structural_refusal import REPROPOSE_MODES, ExecutionMode
from foundry.experiments.locus_validation_v5 import expectations, protocol, world
from foundry.experiments.locus_validation_v5.corpus import (
    DOCUMENTS,
    REVISION,
    SEED_DOCUMENTS,
    SEED_WORLDS,
    corpus_sha256,
)
from foundry.experiments.locus_validation_v5.expectations import (
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
    SOURCE_COVERAGE,
    adjudication_questions_sha256,
    expectations_document,
    expectations_sha256,
    source_coverage_findings,
    source_coverage_sha256,
)
from foundry.experiments.locus_validation_v5.recording import (
    IdentityDrift,
    require_accounting_policy_identity,
)
from foundry.experiments.locus_validation_v5.seal import (
    GATE_NAMES,
    NINE_P3_H,
    V2_REGRESSION_TEXT,
    GitFacts,
    build_manifest,
    leakage_findings,
    preflight_gates,
)

PACKAGE = Path(__file__).resolve().parents[2] / "src/foundry/experiments/locus_validation_v5"
NINE_P3 = Path("docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1")
V4 = Path("docs/superpowers/experiments/2026-09-29-locus-validation-v4")

CORPUS_SHA256 = "2a614e2a49d434d9b1bb2121737e0c416adfbccfa8e4085fff565f7d48bcd198"
EXPECTATIONS_SHA256 = "16dfa3d1c08fc63af5e293e94ee26393cf7024e73624e96ffdafadb69f0041da"
ADJUDICATION_QUESTIONS_SHA256 = "add624c2a1ac3160fb2d39693dcccdd386f30675c5c25c4b8b2dc3a1736cb1c5"
SOURCE_COVERAGE_SHA256 = "a017d6b5c33b7954c7e52c3f0e6ddddac68852023223d67479ed8fcee8855f87"

_ADDS = ("EXTENDS", "CORRECTS", "NEW_CONCERN")


# --------------------------------------------------------------------------- freeze


def test_the_corpus_expectations_questions_and_coverage_are_pinned() -> None:
    assert corpus_sha256() == CORPUS_SHA256
    assert expectations_sha256() == EXPECTATIONS_SHA256
    assert adjudication_questions_sha256() == ADJUDICATION_QUESTIONS_SHA256
    assert source_coverage_sha256() == SOURCE_COVERAGE_SHA256
    assert expectations_document() == expectations_document()


def test_every_text_is_v4s_sealed_text_byte_for_byte() -> None:
    """The policy is the only variable: v5 feeds v4's exact inputs (new evidence ids)."""
    manifest = json.loads((V4 / "manifest.json").read_text())
    v4 = {d["key"]: d["text"] for d in manifest["corpus"]["documents"]}
    assert set(v4) == set(DOCUMENTS)
    for key, doc in DOCUMENTS.items():
        assert doc.text == v4[key], key
        assert doc.evidence_id == f"EV-LV5-{key}"


def test_the_orion_ledger_is_9p3_sealed_locus_h_byte_for_byte() -> None:
    manifest = json.loads((NINE_P3 / "manifest.json").read_text())
    sealed = {r["evidence_id"]: r for r in manifest["evidence"]}
    for key, (evidence_id, digest) in NINE_P3_H.items():
        text = DOCUMENTS[key].text
        assert sha256_of_content(text) == digest == sealed[evidence_id]["content_sha256"]


def test_the_c6_inputs_are_v2s_bytes() -> None:
    for key, digest in V2_REGRESSION_TEXT.items():
        assert sha256_of_content(DOCUMENTS[key].text) == digest


def test_the_policy_under_test_is_the_accounting_policy_in_experiment_mode() -> None:
    cls = XAIReproposingSemanticReasoner
    assert cls.policy_version == protocol.POLICY_VERSION_FROZEN == "intent-v2-locus-v5"
    assert cls.__name__ == protocol.REASONER_CLASS_FROZEN
    assert cls.draft_payload.__name__ == protocol.OUTPUT_SCHEMA_FROZEN == "AccountedDraftPayload"
    assert protocol.MODEL == "grok-4.6" and protocol.REASONING_EFFORT == "high"
    assert protocol.CANONICAL_FACETS is True
    assert protocol.EXECUTION_MODE is ExecutionMode.EXPERIMENT
    assert protocol.EXECUTION_MODE not in REPROPOSE_MODES


def test_the_mode_gate_refuses_any_reproposing_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(protocol, "EXECUTION_MODE", ExecutionMode.PRODUCTION)
    assert "experiment_mode_single_attempt" in _failed()


def test_every_governor_runs_the_canonical_facet_admission() -> None:
    for ledger in protocol.LEDGERS:
        _, governor = world.fresh_governor(
            ledger, clock=lambda: protocol.OBSERVED_AT, id_factory=lambda p: f"{p}-X"
        )
        assert governor._policy.canonical_facets is True, ledger  # noqa: SLF001


def test_the_seeded_address_carries_its_canonical_facet() -> None:
    for seeded in SEED_WORLDS.values():
        for address in seeded:
            assert address.facet == canonical_facet(address.subject)


# --------------------------------------------------------------------------- source coverage


def test_every_sentence_of_every_document_is_accounted_for() -> None:
    assert source_coverage_findings() == ()
    assert set(SOURCE_COVERAGE) == set(DOCUMENTS)


def test_c09_carries_the_acknowledged_proposition() -> None:
    (h5,) = [p for p in PROPOSITIONS if p.id == "H-5"]
    assert h5.document == "H-T9" and h5.address == "H" and h5.relation == "EXTENDS"
    assert "acknowledged" in h5.statement
    (ack,) = [a for a in SOURCE_COVERAGE["H-T9"] if "simply acknowledged" in a.sentence]
    assert ack.propositions == ("H-5",)


def test_v3s_h_t9_inventory_would_be_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    gapped = dict(SOURCE_COVERAGE)
    gapped["H-T9"] = tuple(a for a in gapped["H-T9"] if "acknowledged" not in a.sentence)
    monkeypatch.setattr(expectations, "SOURCE_COVERAGE", gapped)
    findings = source_coverage_findings()
    assert any("UNACCOUNTED_SENTENCE" in f and "simply acknowledged" in f for f in findings)
    assert "H-T9: UNSOURCED_PROPOSITION: H-5" in findings


def test_an_account_naming_another_documents_proposition_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foundry.experiments.locus_formation.source_coverage import SentenceAccount

    wrong = dict(SOURCE_COVERAGE)
    first, *rest = wrong["LATE-NOTE-T2"]
    wrong["LATE-NOTE-T2"] = (
        SentenceAccount(sentence=first.sentence, propositions=("LATE-3", "DAMAGE-2")),
        *rest,
    )
    monkeypatch.setattr(expectations, "SOURCE_COVERAGE", wrong)
    assert "LATE-NOTE-T2: UNKNOWN_PROPOSITION: DAMAGE-2" in source_coverage_findings()


def test_every_omission_carries_a_reason_and_every_account_a_real_proposition() -> None:
    known = {p.id for p in PROPOSITIONS} | {
        c.key for w in SEED_WORLDS.values() for a in w for c in a.claims
    }
    for key, accounts in SOURCE_COVERAGE.items():
        for account in accounts:
            assert account.propositions or account.non_operative_reason, key
            assert set(account.propositions) <= known, key


# --------------------------------------------------------------------------- the answer key


def test_every_proposition_lives_at_an_expected_address() -> None:
    keys = {a.key for a in ADDRESSES}
    assert {p.address for p in PROPOSITIONS} <= keys
    known = {p.id for p in PROPOSITIONS} | {
        c.key for w in SEED_WORLDS.values() for a in w for c in a.claims
    }
    assert all(p.of in known for p in PROPOSITIONS if p.of is not None)
    assert len({p.id for p in PROPOSITIONS}) == len(PROPOSITIONS)


def test_claim_ranges_follow_the_inventory() -> None:
    """Per address: after T1 at least one and at most one claim per SEED proposition per
    document; after T2 the same plus each adding document's range."""
    for item in (*SEED_ITEMS, *REVISED_ITEMS):
        placed = Counter(
            p.address
            for p in PROPOSITIONS
            if p.document == item.document and p.relation in ("SEED", *_ADDS)
        )
        assert item.new_claims == {a: (1, n) for a, n in placed.items()}, item.document
    for a in ADDRESSES:
        if a.origin == "AUTHOR_SEED":
            continue
        docs1 = {p.document for p in PROPOSITIONS if p.address == a.key and p.relation == "SEED"}
        docs2 = docs1 | {
            p.document for p in PROPOSITIONS if p.address == a.key and p.relation in _ADDS
        }
        for t, docs, want in (
            (1, docs1, a.live_claims_after_t1),
            (2, docs2, a.live_claims_after_t2),
        ):
            if want is None:
                continue
            n = [
                sum(1 for p in PROPOSITIONS if p.document == d and p.address == a.key
                    and p.relation in ("SEED", *_ADDS))
                for d in docs
            ]  # fmt: skip
            assert want == (len(docs), sum(n)), (a.key, t)


def test_the_restated_material_must_be_supported() -> None:
    by_doc = {i.document: i for i in REVISED_ITEMS}
    assert by_doc["PICKUP-T2"].must_support == ("PICKUP-1", "PICKUP-2")
    assert by_doc["H-T9"].must_support == ("H-1", "H-2", "H-3")


def test_every_model_delta_item_has_an_expectation() -> None:
    items = {i.document for i in (*SEED_ITEMS, *REVISED_ITEMS)}
    model_docs = {
        d.key
        for ledger in protocol.LEDGERS
        for d in (
            *(SEED_DOCUMENTS[ledger] if ledger in protocol.MODEL_SEEDED else ()),
            *REVISION[ledger],
        )
    }
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
        "A-CORE-SOURCE-ACCOUNTING",
        "A-ORION-SOURCE-ACCOUNTING",
        "A-JOBS-SOURCE-ACCOUNTING",
        "A-CONFLICT-SOURCE-ACCOUNTING",
        "A-LARGE-SOURCE-ACCOUNTING",
    ]
    assert CRITICAL_CASE == "C7-C09-REGRESSION"
    question_ids = [q.id for q in SEMANTIC_QUESTIONS]
    assert len(question_ids) == len(set(question_ids))
    assert {q for c in CASES for q in c.semantic} == set(question_ids)
    for q in SEMANTIC_QUESTIONS:
        (case,) = [c for c in CASES if c.id == q.case]
        assert q.id in case.semantic and q.ledger == case.ledger, q.id


def test_the_c09_t2_question_requires_the_acknowledgement() -> None:
    (q,) = [q for q in SEMANTIC_QUESTIONS if q.id == "Q-T2-H"]
    assert q.after == 2 and "H-5" in q.question and "acknowledged" in q.question


def test_every_model_formed_address_is_judged_after_t1() -> None:
    judged = {
        q.id.removeprefix("Q-T1-")
        for q in SEMANTIC_QUESTIONS
        if q.after == 1 and not q.id.startswith("Q-T1-NONOP-")
    }
    assert judged == {a.key for a in ADDRESSES if a.origin == "MODEL_T1"}


def test_the_large_world_is_sixteen_model_formed_addresses() -> None:
    assert "large" in protocol.MODEL_SEEDED and "large" not in SEED_WORLDS
    large = [a for a in ADDRESSES if a.ledger == "large"]
    assert len(large) == len(LARGE_KEYS) == len(SEED_DOCUMENTS["large"]) == 16
    (note,) = REVISION["large"]
    assert note.supersedes is None


def test_the_under_split_pairs_are_the_four_required_ones() -> None:
    assert {(s.a, s.b) for s in EXPECTED_SEPARATE} == {
        ("CANCEL", "AUDIT"),
        ("LATE", "DAMAGE"),
        ("LATE", "SETTLEMENT"),
        ("CUSTOMER-REFUND", "SUPPLIER-OVERPAYMENT"),
    }


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
        f"from foundry.experiments.locus_validation_v5.{module} import X\n" + runner.read_text()
    )
    assert any("runner" in f for f in leakage_findings(copy))


# --------------------------------------------------------------------------- identity


def _canonical(**overrides: Any) -> XAIReproposingSemanticReasoner:
    kwargs: dict[str, Any] = {"api_key": "k", "model": protocol.MODEL, "reasoning_effort": "high"}
    kwargs.update(overrides)
    return XAIReproposingSemanticReasoner(**kwargs)


def test_the_identity_guard_accepts_exactly_the_policy_under_test() -> None:
    require_accounting_policy_identity(_canonical())
    for overrides in ({"model": "grok-4.7"}, {"reasoning_effort": "low"}):
        with pytest.raises(IdentityDrift):
            require_accounting_policy_identity(_canonical(**overrides))


def test_the_identity_guard_refuses_the_previous_policy() -> None:
    with pytest.raises(IdentityDrift):
        require_accounting_policy_identity(
            XAIPropositionAccountingSemanticReasoner(
                api_key="k", model=protocol.MODEL, reasoning_effort="high"
            )
        )


def test_the_identity_guard_refuses_a_shadowed_instruction() -> None:
    reasoner = _canonical()
    reasoner.system_instruction = reasoner.system_instruction + " "  # type: ignore[misc]
    with pytest.raises(IdentityDrift):
        require_accounting_policy_identity(reasoner)


def test_the_identity_guard_refuses_the_same_class_on_the_historical_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the output contract differs: the class name, prompt and version still match."""
    monkeypatch.setattr(XAIReproposingSemanticReasoner, "draft_payload", SemanticDraftPayload)
    with pytest.raises(IdentityDrift, match="output_schema"):
        require_accounting_policy_identity(_canonical())


def test_the_identity_guard_refuses_the_historical_contract() -> None:
    class HistoricalContract(XAIReproposingSemanticReasoner):
        draft_payload: ClassVar[Any] = SemanticDraftPayload

    with pytest.raises(IdentityDrift):
        require_accounting_policy_identity(
            HistoricalContract(api_key="k", model=protocol.MODEL, reasoning_effort="high")
        )


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
        "source_coverage_sha256",
        "scoring_sources_sha256",
        "policy_version",
        "reasoner_class",
        "prompt_sha256",
        "output_schema",
        "execution_mode",
        "output_schema_sha256",
        "historical_output_schema_sha256",
        "canonical_facet_prefix",
        "model",
        "reasoning_effort",
    ):
        assert manifest[key] not in (None, "", "MISSING"), key
    assert manifest["canonical_facets"] is True
    assert manifest["source_coverage_findings"] == []
    assert "MISSING" not in manifest["scoring_sources_sha256"].values()


def test_every_gate_passes_on_a_correct_seal() -> None:
    gates = preflight_gates(**_facts())
    assert tuple(g.name for g in gates) == GATE_NAMES
    assert _failed() == set()


def test_each_gate_refuses_its_fact() -> None:
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


def test_the_admission_gate_refuses_a_governor_without_canonical_facets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(world, "CANONICAL_FACETS", False)
    assert "canonical_facet_admission" in _failed()


def test_the_coverage_gate_refuses_a_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    gapped = dict(SOURCE_COVERAGE)
    del gapped["H-T1"]
    monkeypatch.setattr(expectations, "SOURCE_COVERAGE", gapped)
    assert "source_coverage_complete" in _failed()


def test_an_edited_scoring_rule_after_the_seal_is_refused(tmp_path: Path) -> None:
    copy = tmp_path / "pkg"
    shutil.copytree(PACKAGE, copy)
    evaluation = copy / "evaluation.py"
    evaluation.write_text(evaluation.read_text() + "\n# softened\n")
    assert "manifest_matches_code" in _failed(package_dir=copy)
