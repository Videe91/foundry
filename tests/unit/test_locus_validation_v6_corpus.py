"""Locus validation v6: frozen identity and the model-visible corpus (design §2, §4).

The policy under test is ``intent-v2-locus-v6`` unchanged; correction sets are enabled only
inside this validation's governors. The corpus reuses v5's regression texts byte for byte
and adds a new held-out dense domain whose density is comparable to the long-horizon T1.
"""

from __future__ import annotations

import hashlib

from foundry.adapters.semantics.xai_reasoner import (
    CORRECTION_SET_POLICY_VERSION,
    CORRECTION_SET_SYSTEM_INSTRUCTION,
    XAICorrectionSetSemanticReasoner,
    accounted_output_schema_sha256,
)
from foundry.domain.evidence import sha256_of_content
from foundry.domain.source_text import source_sentences
from foundry.experiments.locus_validation_v5 import corpus as v5_corpus
from foundry.experiments.locus_validation_v6 import corpus, protocol


def test_identity_is_the_unchanged_v6_policy_with_correction_sets_enabled_here_only() -> None:
    assert protocol.EXPERIMENT_VERSION == "intent-v2-locus-validation-v6"
    assert protocol.POLICY_VERSION_FROZEN == CORRECTION_SET_POLICY_VERSION == "intent-v2-locus-v6"
    assert XAICorrectionSetSemanticReasoner.__name__ == protocol.REASONER_CLASS_FROZEN
    prompt = hashlib.sha256(CORRECTION_SET_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert prompt == protocol.PROMPT_SHA256_FROZEN
    assert protocol.PROMPT_SHA256_FROZEN.startswith("13aa8774")
    assert accounted_output_schema_sha256() == protocol.OUTPUT_SCHEMA_SHA256_FROZEN
    assert XAICorrectionSetSemanticReasoner.correction_law == protocol.CORRECTION_LAW_FROZEN
    assert protocol.CORRECTION_LAW_FROZEN == "TARGET_SET"
    assert protocol.CORRECTION_SETS is True and protocol.CANONICAL_FACETS is True
    assert protocol.AUTHORITY_PROTOCOL == "ie2-authority-routing-v2"
    assert (protocol.PROVIDER, protocol.MODEL, protocol.REASONING_EFFORT) == (
        "xai",
        "grok-4.6",
        "high",
    )


def test_the_call_budget_is_exact_and_has_no_retry() -> None:
    assert protocol.CALLS_PER_DELTA == 2
    # core 4 + orion 4 + jobs 4 + conflict 2 + large 4 + dense (T1, T2, T3 x two branches) 8
    assert protocol.MAX_FRONTIER_CALLS == 26
    assert protocol.BRANCHES == ("AGREE", "DECLINE")


def test_regression_texts_are_v5_bytes_under_new_evidence_ids() -> None:
    for key, v5_key in corpus.V5_REUSED.items():
        doc, old = corpus.DOCUMENTS[key], v5_corpus.DOCUMENTS[v5_key]
        assert sha256_of_content(doc.text) == sha256_of_content(old.text), key
        assert doc.evidence_id == f"EV-LV6-{key}" != old.evidence_id
        assert doc.artifact_ref == old.artifact_ref
    assert {d.ledger for d in corpus.DOCUMENTS.values()} == set(protocol.LEDGERS)
    reused = set(corpus.V5_REUSED.values())
    assert reused == set(v5_corpus.DOCUMENTS), "every v5 regression text is carried over"


def test_the_dense_baseline_has_long_horizon_t1_density() -> None:
    t1 = corpus.SEED_DOCUMENTS["dense"]
    assert len(t1) >= 12
    assert sum(len(d.text) for d in t1) >= 8000
    assert sum(len(source_sentences(d.text)) for d in t1) >= 60
    assert len({d.artifact_ref for d in t1}) == len(t1)


def test_dense_revisions_and_their_lineage() -> None:
    t2 = {d.key for d in corpus.REVISION["dense"]}
    assert t2 == {"K-CLEANING-T2", "K-LATE-T2", "K-CREDIT-T2", "K-UNLOCK-WAIT-T2", "K-TRIP-T2"}
    for d in corpus.REVISION["dense"]:
        assert d.supersedes == corpus.DOCUMENTS[d.key.replace("-T2", "-T1")].evidence_id
    t3 = {d.key: d for d in corpus.T3_DOCUMENTS}
    assert set(t3) == {"K-UNLOCK-WAIT-T3", "K-CLEANING-T3"}
    assert t3["K-UNLOCK-WAIT-T3"].text == corpus.DOCUMENTS["K-UNLOCK-WAIT-T2"].text
    assert t3["K-UNLOCK-WAIT-T3"].supersedes == corpus.DOCUMENTS["K-UNLOCK-WAIT-T2"].evidence_id
    assert t3["K-CLEANING-T3"].text not in (
        corpus.DOCUMENTS["K-CLEANING-T2"].text,
        corpus.DOCUMENTS["K-CLEANING-T1"].text,
    )
    assert t3["K-CLEANING-T3"].supersedes == corpus.DOCUMENTS["K-CLEANING-T2"].evidence_id


def test_evidence_ids_are_unique_and_every_document_belongs_to_a_known_ledger() -> None:
    ids = [d.evidence_id for d in corpus.DOCUMENTS.values()]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("EV-LV6-") for i in ids)
    for ledger in protocol.LEDGERS:
        assert corpus.revision_delta(ledger), ledger
    assert corpus.t3_delta()


def test_the_corpus_digest_is_deterministic() -> None:
    assert corpus.corpus_sha256() == corpus.corpus_sha256()
    record = corpus.corpus_record()
    assert set(record["documents"]) == set(corpus.DOCUMENTS)
