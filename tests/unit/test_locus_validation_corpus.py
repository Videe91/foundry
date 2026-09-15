"""Frozen corpus of the locus-validation experiment (T1): model-visible evidence only.

Locks the sixteen evidence items of spec §5 (two ledgers x four documents x two
versions), their ids, lineage, scope, project, timestamps and byte-exact section
texts — checked against the fenced blocks of the approved spec, parsed read-only as
a test-time oracle — plus the structural records and the single corpus hash.
Nothing here decides meaning; ``corpus.py`` must not import the hidden answer key
(checked by parsing its source with ``ast``). No provider call exists.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foundry.domain.common import SourceKind
from foundry.experiments.locus_validation import corpus as corpus_module
from foundry.experiments.locus_validation.corpus import (
    ARTIFACT_REFS,
    DOCUMENTS,
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    corpus_sha256,
    delta,
    evidence_id,
    evidence_records,
    section_text,
)

SPEC = (
    Path(__file__).resolve().parents[2]
    / "docs/superpowers/specs/2026-09-15-locus-policy-live-validation-design.md"
)

# One fenced block follows every ``T1 (`EV-LV-…`):`` / ``T2 (`EV-LV-…`, supersedes …):`` line.
_BLOCK = re.compile(
    r"^T([12]) \(`EV-LV-([AB][1-4])-T[12]`[^\n]*\):\n```\n(.*?)```",
    re.S | re.M,
)

ALL_DOCUMENTS = ("A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4")
FROZEN_OBSERVED_AT = datetime(2026, 9, 15, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _spec_blocks() -> dict[tuple[str, int], str]:
    # test-time oracle only: the spec is the binding literal for every section text
    found = _BLOCK.findall(SPEC.read_text(encoding="utf-8"))
    return {(document, int(t)): text for t, document, text in found}


def test_constants_are_locked_to_spec_5() -> None:
    assert LEDGERS == ("alpha", "beta")
    assert PROJECT_IDS == {"alpha": "PROJ-LV-ALPHA", "beta": "PROJ-LV-BETA"}
    assert SCOPES == {"alpha": "keyring", "beta": "relay"}
    assert DOCUMENTS == {"alpha": ("A1", "A2", "A3", "A4"), "beta": ("B1", "B2", "B3", "B4")}
    assert ARTIFACT_REFS == {
        "A1": "keyring/spec/credential-revocation.md",
        "A2": "keyring/spec/retry-timing.md",
        "A3": "keyring/spec/worker-lease.md",
        "A4": "keyring/spec/execution-time-limit.md",
        "B1": "relay/runbook/acknowledgement.md",
        "B2": "relay/runbook/delivery-order.md",
        "B3": "relay/runbook/subscription-lease.md",
        "B4": "relay/runbook/delivery-deadline.md",
    }


def test_evidence_ids_follow_the_spec_5_law() -> None:
    assert evidence_id("A1", 1) == "EV-LV-A1-T1"
    assert evidence_id("B2", 2) == "EV-LV-B2-T2"
    ids = [evidence_id(d, t) for d in ALL_DOCUMENTS for t in (1, 2)]
    assert len(ids) == 16 and len(set(ids)) == 16


def test_section_texts_are_byte_exact_to_the_spec_blocks() -> None:
    blocks = _spec_blocks()
    assert len(blocks) == 16
    for document in ALL_DOCUMENTS:
        for t in (1, 2):
            text = section_text(document, t)
            assert text == blocks[(document, t)], (document, t)
            assert text.endswith("\n") and not text.endswith("\n\n"), (document, t)
            assert text == "\n".join(text.split("\n")[:-1]) + "\n"


def test_section_text_refuses_unknown_documents() -> None:
    with pytest.raises(ValueError, match="Z9"):
        section_text("Z9", 1)


def test_no_document_carries_answer_key_or_predecessor_wording() -> None:
    forbidden = (
        "RESTATEMENT",
        "EXTENSION",
        "CORRECTION",
        "DISTINCT",
        "S01",
        "V0",
        "VALIDATED",
        "INCONCLUSIVE",
        "Orion",
        "cancel",
        "EV-O-",
    )
    for document in ALL_DOCUMENTS:
        for t in (1, 2):
            haystack = section_text(document, t).lower()
            for word in forbidden:
                assert word.lower() not in haystack, (document, t, word)


@pytest.mark.parametrize("ledger", LEDGERS)
@pytest.mark.parametrize("t", (1, 2))
def test_delta_yields_the_four_items_of_that_version_in_document_order(ledger: str, t: int) -> None:
    items = delta(ledger, t)
    assert [i.evidence_id for i in items] == [evidence_id(d, t) for d in DOCUMENTS[ledger]]
    for document, item in zip(DOCUMENTS[ledger], items, strict=True):
        assert item.project_id == PROJECT_IDS[ledger]
        assert item.scope == (SCOPES[ledger],)
        assert item.source_kind is SourceKind.DOCUMENT
        assert item.source_ref == f"experiment://locus-validation/{ledger}/T{t}/{document}"
        assert item.artifact_ref == ARTIFACT_REFS[document]
        assert item.observed_at == FROZEN_OBSERVED_AT
        assert item.content == section_text(document, t)
        if t == 1:
            assert item.supersedes_evidence_id is None
        else:
            assert item.supersedes_evidence_id == evidence_id(document, 1)


def test_every_t2_item_supersedes_its_t1_item_with_the_same_artifact_ref() -> None:
    for ledger in LEDGERS:
        first = {i.evidence_id: i for i in delta(ledger, 1)}
        for item in delta(ledger, 2):
            predecessor = first[item.supersedes_evidence_id or ""]
            assert predecessor.artifact_ref == item.artifact_ref
            assert predecessor.content != item.content


def test_evidence_records_are_ordered_alpha_then_beta_t1_then_t2_document_order() -> None:
    records = evidence_records()
    assert len(records) == 16
    expected_ids = [
        evidence_id(d, t) for ledger in LEDGERS for t in (1, 2) for d in DOCUMENTS[ledger]
    ]
    assert [r.evidence_id for r in records] == expected_ids
    for r in records:
        assert r.ledger in LEDGERS and r.document in DOCUMENTS[r.ledger] and r.t in (1, 2)
        assert r.artifact_ref == ARTIFACT_REFS[r.document]
        text = section_text(r.document, r.t)
        assert r.content_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert r.chars == len(text)
        assert r.supersedes_evidence_id == (None if r.t == 1 else evidence_id(r.document, 1))


def test_corpus_sha256_is_deterministic_and_matches_a_recomputation() -> None:
    payload = [
        record.model_dump(mode="json") | {"content": section_text(record.document, record.t)}
        for record in evidence_records()
    ]
    recomputed = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    assert corpus_sha256() == recomputed
    assert corpus_sha256() == corpus_sha256()
    assert re.fullmatch(r"[0-9a-f]{64}", corpus_sha256())


def test_corpus_never_imports_the_hidden_answer_key_or_evaluation_modules() -> None:
    tree = ast.parse(Path(corpus_module.__file__).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    for name in ("expectations", "evaluation", "leakage", "integrity", "protocol"):
        assert not any(name in m for m in mods), name
    allowed_foundry = {
        "foundry.domain.common",
        "foundry.domain.evidence",
        "foundry.experiments.contrastive_unseen.artifacts",
    }
    assert {m for m in mods if m.startswith("foundry")} <= allowed_foundry
