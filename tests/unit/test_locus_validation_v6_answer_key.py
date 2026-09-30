"""Locus validation v6: the sealed answer key (design §6), checked before any live call.

The concern oracle is derived from G2 as clarified on 2026-09-30, never from section count:
several dense sections map to one governed concern, and nearby sections sharing nouns map to
different concerns. Nothing here depends on model output.
"""

from __future__ import annotations

from collections import Counter

from foundry.experiments.locus_validation_v5 import expectations as v5
from foundry.experiments.locus_validation_v6 import corpus
from foundry.experiments.locus_validation_v6 import expectations as key
from foundry.experiments.locus_validation_v6.protocol import LEDGERS

TIMEPOINTS = ("T1", "T2", "AGREED", "DECLINED", "T3-AGREE", "T3-DECLINE")


# ------------------------------------------------------------------ the G2 concern oracle


def test_every_t1_document_belongs_to_exactly_one_concern_and_grain_is_not_section_count() -> None:
    for ledger in LEDGERS:
        t1 = {d.key for d in corpus.SEED_DOCUMENTS[ledger]}
        concerns = [c for c in key.CONCERNS if c.ledger == ledger and c.origin == "MODEL_T1"]
        formed = [d for c in concerns for d in c.documents]
        if ledger == "conflict":
            assert concerns == []
            continue
        assert sorted(formed) == sorted(t1), ledger
        assert len(formed) == len(set(formed)), ledger
    dense = [c for c in key.CONCERNS if c.ledger == "dense"]
    assert len(dense) == 9 < len(corpus.SEED_DOCUMENTS["dense"]) == 15


def test_the_dense_same_concern_groups_span_several_sections() -> None:
    by_key = {c.key: c for c in key.CONCERNS if c.ledger == "dense"}
    assert by_key["RESERVATION"].documents == ("K-BOOKING-T1", "K-HOLD-T1", "K-PROLONG-T1")
    assert by_key["UNLOCK"].documents == (
        "K-UNLOCK-T1",
        "K-UNLOCK-WAIT-T1",
        "K-UNLOCK-TIMEOUT-T1",
    )
    assert by_key["LATE-FEE"].documents == ("K-LATE-T1", "K-LATE-WAIVER-T1")
    assert by_key["SERVICE-CREDIT"].documents == ("K-CREDIT-T1", "K-CREDIT-CLAIM-T1")
    singles = {k for k, c in by_key.items() if len(c.documents) == 1}
    assert singles == {"CLEANING-FEE", "BILLING-RUN", "SUSPENSION", "TRIP-RECORDS", "MEMBERSHIP"}


def test_the_dense_separations_and_the_v5_guards_are_sealed() -> None:
    pairs = {(p.a, p.b) for p in key.EXPECTED_SEPARATE}
    for a, b in (
        ("LATE-FEE", "CLEANING-FEE"),
        ("LATE-FEE", "BILLING-RUN"),
        ("BILLING-RUN", "SUSPENSION"),
        ("RESERVATION", "UNLOCK"),
        ("RESERVATION", "TRIP-RECORDS"),
        ("SERVICE-CREDIT", "LATE-FEE"),
        ("CANCEL", "AUDIT"),
        ("LATE", "DAMAGE"),
        ("LATE", "SETTLEMENT"),
        ("CUSTOMER-REFUND", "SUPPLIER-OVERPAYMENT"),
    ):
        assert (a, b) in pairs


def test_the_dense_baseline_has_thirty_plus_propositions_each_placed_at_its_documents_concern() -> (
    None
):
    t1 = [p for p in key.PROPOSITIONS if p.document.startswith("K-") and p.document.endswith("-T1")]
    assert len(t1) >= 30
    concern_of = {d: c.key for c in key.CONCERNS for d in c.documents}
    for p in key.PROPOSITIONS:
        if p.relation == "SEED" and p.document in concern_of:
            assert p.concern == concern_of[p.document], p.id


def test_c09_and_c6_regressions_are_kept_whole() -> None:
    h = [p for p in key.PROPOSITIONS if p.ledger == "orion" and p.relation != "RESTATES"]
    assert {p.concern for p in h} == {"H"}
    assert {"H-4", "H-5"} <= {p.id for p in h}
    late = [p for p in key.PROPOSITIONS if p.concern == "LATE" and p.ledger == "core"]
    assert {"LATE-1", "LATE-2", "LATE-3"} <= {p.id for p in late}
    assert key.EXPECTED_ADDRESS_COUNTS["orion"] == {"T1": 1, "T2": 1}
    assert key.EXPECTED_ADDRESS_COUNTS["core"] == {"T1": 7, "T2": 8}
    assert key.EXPECTED_ADDRESS_COUNTS["dense"] == dict.fromkeys(TIMEPOINTS, 9)


def test_regression_propositions_are_v5s() -> None:
    ours = {p.id: p.statement for p in key.PROPOSITIONS if p.ledger != "dense"}
    theirs = {p.id: p.statement for p in v5.PROPOSITIONS}
    assert ours == theirs


# ------------------------------------------------------------------ source coverage


def test_source_coverage_is_complete_for_every_document() -> None:
    assert key.source_coverage_findings() == ()
    assert set(key.SOURCE_COVERAGE) == set(corpus.DOCUMENTS)


# ------------------------------------------------------------------ corrections


def test_the_four_correction_cardinalities_are_sealed_in_the_held_out_domain() -> None:
    by_card = {g.cardinality: g for g in key.CORRECTIONS if g.ledger == "dense" and g.at == "T2"}
    assert set(by_card) == {"1:1", "N:1", "1:N", "N:M"}
    assert (len(by_card["1:1"].obsolete), len(by_card["1:1"].replacements)) == (1, 1)
    assert len(by_card["N:1"].obsolete) >= 2 and len(by_card["N:1"].replacements) == 1
    assert len(by_card["1:N"].obsolete) == 1 and len(by_card["1:N"].replacements) >= 2
    assert len(by_card["N:M"].obsolete) >= 2 and len(by_card["N:M"].replacements) >= 3
    ids = {p.id: p for p in key.PROPOSITIONS}
    for g in key.CORRECTIONS:
        for pid in (*g.obsolete, *g.replacements):
            assert ids[pid].concern == g.concern
        for pid in g.replacements:
            assert ids[pid].document == g.document


def test_t3_seals_the_repeat_and_the_changed_basis_per_branch() -> None:
    t3 = {(g.at, g.concern): g for g in key.CORRECTIONS if g.at.startswith("T3")}
    assert t3[("T3-DECLINE", "UNLOCK")].outcome == "SUPPRESSED_AS_DECLINED"
    assert t3[("T3-DECLINE", "CLEANING-FEE")].outcome == "PENDING"
    assert t3[("T3-AGREE", "CLEANING-FEE")].outcome == "PENDING"
    assert ("T3-AGREE", "UNLOCK") not in t3, "after AGREE the redelivered text is a restatement"
    t2_unlock = next(g for g in key.CORRECTIONS if g.at == "T2" and g.concern == "UNLOCK")
    assert t3[("T3-DECLINE", "UNLOCK")].obsolete == t2_unlock.obsolete


def test_every_pending_set_location_is_sealed_per_timepoint() -> None:
    assert key.EXPECTED_PENDING_SETS["dense"]["T2"] == (
        "CLEANING-FEE",
        "LATE-FEE",
        "SERVICE-CREDIT",
        "UNLOCK",
    )
    assert key.EXPECTED_PENDING_SETS["dense"]["AGREED"] == ()
    assert key.EXPECTED_PENDING_SETS["dense"]["DECLINED"] == ()
    assert key.EXPECTED_PENDING_SETS["dense"]["T3-AGREE"] == ("CLEANING-FEE",)
    assert key.EXPECTED_PENDING_SETS["dense"]["T3-DECLINE"] == ("CLEANING-FEE",)
    assert key.EXPECTED_PENDING_SETS["core"]["T2"] == ("WEIGHT",)
    for ledger in ("orion", "jobs", "conflict", "large"):
        assert set(key.EXPECTED_PENDING_SETS[ledger].values()) <= {()}


def test_dispositions_follow_the_claim_laws_and_differ_by_branch_only_at_t3() -> None:
    d = key.EXPECTED_DISPOSITIONS
    assert d["K-CLEAN-1C"] == "ASSERT_CLAIM + SUPERSEDE"
    assert d["K-LATE-7"] == "ASSERT_CLAIM + SUPERSEDE"
    assert d["K-TRIP-4"] == "ASSERT_CLAIM"
    assert d["K-TRIP-1R"] == "SUPPORTS_CLAIM"
    assert d["K-UNL-9-T3A"] == "SUPPORTS_CLAIM"
    assert d["K-UNL-9-T3D"] == "ASSERT_CLAIM (+ SUPERSEDE)"
    assert {p.branch for p in key.PROPOSITIONS if p.document.endswith("-T3")} == {
        "AGREE",
        "DECLINE",
    }
    assert all(p.branch is None for p in key.PROPOSITIONS if not p.document.endswith("-T3"))


# ------------------------------------------------------------------ questions and cases


def test_every_question_names_a_ledger_and_an_exact_timepoint() -> None:
    ids = [q.id for q in key.SEMANTIC_QUESTIONS]
    assert len(ids) == len(set(ids))
    for q in key.SEMANTIC_QUESTIONS:
        assert q.after in TIMEPOINTS
        assert q.question.startswith(f"At {q.after}, in ledger {q.ledger}"), q.id
        if q.after in ("AGREED", "DECLINED", "T3-AGREE", "T3-DECLINE"):
            assert q.ledger == "dense"
    counts = Counter(q.after for q in key.SEMANTIC_QUESTIONS if q.ledger == "dense")
    assert set(counts) == set(TIMEPOINTS)


def test_every_case_semantic_reference_exists_and_every_question_serves_a_case() -> None:
    ids = {q.id for q in key.SEMANTIC_QUESTIONS}
    referenced = {s for c in key.CASES for s in c.semantic}
    assert referenced == ids
    required = {
        "D0-DENSE-FORMATION",
        "X1-ONE-TO-ONE",
        "X2-MANY-TO-ONE",
        "X3-ONE-TO-MANY",
        "X4-MANY-TO-MANY",
        "Z1-PENDING-ATOMIC",
        "Z2-AGREE",
        "Z3-DECLINE",
        "Z4-REPEAT-SUPPRESSED",
        "Z5-CHANGED-BASIS-REOPENS",
        "Z6-AUTHORITY-ROUTING",
        "C6-LATE-DELIVERY",
        "C7-C09-REGRESSION",
    }
    assert required <= {c.id for c in key.CASES}


def test_the_expectations_document_is_deterministic_and_static() -> None:
    assert key.expectations_sha256() == key.expectations_sha256()
    doc = key.expectations_document()
    assert doc["experiment_version"] == "intent-v2-locus-validation-v6"
    assert "LOCUS_POLICY_VALIDATED" in str(doc["standing_rule"])
