"""The proposition-accounting law (IE2 v2 design §7.1.3), on ids alone.

Every accountable sentence is carried by a proposition or declared non-operative (source
accounting); every proposition receives exactly one disposition from the existing IE2 claim
laws (claim accounting). The law reads no meaning and supplies no disposition: it only
reports, by id, what a response left unaccounted for or accounted for inconsistently.
"""

from __future__ import annotations

import pytest

from foundry.domain.proposition_accounting import (
    VALID_DISPOSITIONS,
    AccountedProposition,
    NonOperativeSentence,
    PropositionDisposition,
    accounting_findings,
)
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.domain.source_text import numbered_sentences, sentence_id, source_sentences
from foundry.experiments.long_horizon_bounded.timeline import SECTION_TEXT

K = JudgmentKind
EV = "EV-1"


def _sentences(n: int, evidence_id: str = EV) -> dict[str, str]:
    return {sentence_id(evidence_id, i): evidence_id for i in range(1, n + 1)}


def _p(pid: str, *sentences: int, evidence_id: str = EV) -> AccountedProposition:
    return AccountedProposition(
        proposition_id=pid,
        sentence_ids=tuple(sentence_id(evidence_id, s) for s in sentences),
        statement=f"statement {pid}",
    )


def _d(pid: str, kind: JudgmentKind, *evidence: str) -> PropositionDisposition:
    cites = evidence or ((EV,) if kind is not K.SUPERSEDE else ())
    return PropositionDisposition(proposition_id=pid, kind=kind, evidence_ids=cites)


def _silent(s: int, evidence_id: str = EV) -> NonOperativeSentence:
    return NonOperativeSentence(sentence_id=sentence_id(evidence_id, s), reason="an example")


def _findings(
    sentences: dict[str, str],
    props: list[AccountedProposition],
    dispositions: list[PropositionDisposition],
    silent: list[NonOperativeSentence] | None = None,
) -> tuple[str, ...]:
    return accounting_findings(
        sentence_evidence=sentences,
        propositions=props,
        non_operative=silent or [],
        dispositions=dispositions,
    )


# ------------------------------------------------------------------ completeness


def test_1_one_proposition_one_action_passes() -> None:
    assert _findings(_sentences(1), [_p("P1", 1)], [_d("P1", K.ASSERT_CLAIM)]) == ()


def test_2_three_propositions_three_actions_pass() -> None:
    props = [_p("P1", 1), _p("P2", 2), _p("P3", 3)]
    drafts = [_d("P1", K.SUPPORTS_CLAIM), _d("P2", K.ASSERT_CLAIM), _d("P3", K.ASSERT_CLAIM)]
    assert _findings(_sentences(3), props, drafts) == ()


def test_3_three_propositions_two_accounted_is_refused() -> None:
    props = [_p("P1", 1), _p("P2", 2), _p("P3", 3)]
    drafts = [_d("P1", K.SUPPORTS_CLAIM), _d("P3", K.ASSERT_CLAIM)]
    assert _findings(_sentences(3), props, drafts) == ("UNACCOUNTED_PROPOSITION: P2",)


def test_4_zero_drafts_for_a_listed_new_proposition_is_refused() -> None:
    assert _findings(_sentences(1), [_p("P1", 1)], []) == ("UNACCOUNTED_PROPOSITION: P1",)


C8_TEXT = (
    "## Returns desk note\n\n"
    "The original delivery charge is also repaid to a customer who returns an order."
)
C8_EV = "EV-LV4-RETURNS-NOTE-T2"


def test_5_the_recorded_c8_shape_is_refused_either_way() -> None:
    """v4 C8: the note was bound, and Call 2 returned nothing at all. Under accounting that
    is refused at the sentence (no inventory) and, with an inventory, at the proposition."""
    sentences = {sid: C8_EV for sid, _ in numbered_sentences(C8_EV, C8_TEXT)}
    assert sentences == {f"{C8_EV}#S1": C8_EV}
    assert _findings(sentences, [], []) == (f"UNACCOUNTED_SENTENCE: {C8_EV}#S1",)
    listed = [_p("P1", 1, evidence_id=C8_EV)]
    assert _findings(sentences, listed, []) == ("UNACCOUNTED_PROPOSITION: P1",)


H9_EV = "EV-H-T9"
H9 = SECTION_TEXT[(9, "H")]


def _h9_sentences() -> dict[str, str]:
    return {sid: H9_EV for sid, _ in numbered_sentences(H9_EV, H9)}


def _h9_inventory() -> list[AccountedProposition]:
    """H-T9: S1 who may cancel; S2 no future attempt + no abort; S3 a repeat is simply
    acknowledged; S4 no future attempt; S5 running attempt continues; S6 repeat leaves the
    job cancelled and unchanged; S7-S8 the example."""
    return [
        _p("P1", 1, evidence_id=H9_EV),
        _p("P2", 2, 4, evidence_id=H9_EV),
        _p("P3", 2, 5, evidence_id=H9_EV),
        _p("P4", 6, evidence_id=H9_EV),
        _p("P5", 3, evidence_id=H9_EV),
    ]


def _h9_complete() -> list[PropositionDisposition]:
    return [
        _d("P1", K.SUPPORTS_CLAIM, H9_EV),
        _d("P2", K.SUPPORTS_CLAIM, H9_EV),
        _d("P3", K.SUPPORTS_CLAIM, H9_EV),
        _d("P4", K.ASSERT_CLAIM, H9_EV),
        _d("P5", K.ASSERT_CLAIM, H9_EV),
    ]


def _h9_examples() -> list[NonOperativeSentence]:
    return [_silent(7, H9_EV), _silent(8, H9_EV)]


def test_the_c09_source_has_eight_sentences_and_s3_is_the_acknowledgement() -> None:
    sentences = source_sentences(H9)
    assert len(sentences) == 8
    assert "simply acknowledged" in sentences[2]


def test_6_c09_with_h5_omitted_is_refused_by_id() -> None:
    drafts = [d for d in _h9_complete() if d.proposition_id != "P5"]
    assert _findings(_h9_sentences(), _h9_inventory(), drafts, _h9_examples()) == (
        "UNACCOUNTED_PROPOSITION: P5",
    )


def test_7_c09_fully_accounted_passes() -> None:
    assert _findings(_h9_sentences(), _h9_inventory(), _h9_complete(), _h9_examples()) == ()


def test_8_a_supported_proposition_counts_exactly_once() -> None:
    assert _findings(_sentences(1), [_p("P1", 1)], [_d("P1", K.SUPPORTS_CLAIM)]) == ()
    twice = [_d("P1", K.SUPPORTS_CLAIM), _d("P1", K.SUPPORTS_CLAIM)]
    assert _findings(_sentences(1), [_p("P1", 1)], twice) == (
        "CONFLICTING_DISPOSITION: P1 (SUPPORTS_CLAIM, SUPPORTS_CLAIM)",
    )


def test_9_an_asserted_proposition_counts_exactly_once() -> None:
    twice = [_d("P1", K.ASSERT_CLAIM), _d("P1", K.ASSERT_CLAIM)]
    assert _findings(_sentences(1), [_p("P1", 1)], twice) == (
        "CONFLICTING_DISPOSITION: P1 (ASSERT_CLAIM, ASSERT_CLAIM)",
    )


def test_10_a_correction_is_one_disposition_of_two_drafts() -> None:
    correction = [_d("P1", K.SUPERSEDE), _d("P1", K.ASSERT_CLAIM)]
    assert _findings(_sentences(1), [_p("P1", 1)], correction) == ()
    alone = [_d("P1", K.SUPERSEDE)]
    assert _findings(_sentences(1), [_p("P1", 1)], alone) == (
        "CONFLICTING_DISPOSITION: P1 (SUPERSEDE)",
    )


def test_11_an_existing_conflict_is_two_supports_and_the_relation_disposes_of_nothing() -> None:
    """Current policy (C5): each restatement of a conflicting side is a SUPPORTS_CLAIM; the
    CONFLICTS_WITH between the two current claims names no proposition, so it is not a
    disposition and cannot stand in for one."""
    props = [_p("P1", 1), _p("P2", 2)]
    supports = [_d("P1", K.SUPPORTS_CLAIM), _d("P2", K.SUPPORTS_CLAIM)]
    assert _findings(_sentences(2), props, supports) == ()
    assert K.CONFLICTS_WITH not in {k for d in VALID_DISPOSITIONS for k in d}
    assert _findings(_sentences(2), props, supports[:1]) == ("UNACCOUNTED_PROPOSITION: P2",)


def test_12_an_unknown_proposition_id_is_refused() -> None:
    drafts = [_d("P1", K.ASSERT_CLAIM), _d("P9", K.ASSERT_CLAIM)]
    assert _findings(_sentences(1), [_p("P1", 1)], drafts) == ("UNKNOWN_PROPOSITION: P9",)


def test_13_mutually_exclusive_dispositions_are_refused() -> None:
    drafts = [_d("P1", K.SUPPORTS_CLAIM), _d("P1", K.ASSERT_CLAIM)]
    assert _findings(_sentences(1), [_p("P1", 1)], drafts) == (
        "CONFLICTING_DISPOSITION: P1 (ASSERT_CLAIM, SUPPORTS_CLAIM)",
    )


def test_14_output_about_sentences_or_propositions_outside_the_request_is_refused() -> None:
    stray_sentence = [_p("P1", 1), _p("P2", 7)]
    drafts = [_d("P1", K.ASSERT_CLAIM), _d("P2", K.ASSERT_CLAIM)]
    assert _findings(_sentences(1), stray_sentence, drafts) == (f"UNKNOWN_SENTENCE: {EV}#S7",)
    other = [_p("P1", 1), _p("P2", 1, evidence_id="EV-OTHER")]
    assert "UNKNOWN_SENTENCE: EV-OTHER#S1" in _findings(_sentences(1), other, drafts)


def test_15_nothing_accountable_and_nothing_returned_is_valid() -> None:
    assert _findings({}, [], []) == ()


def test_16_accountable_sentences_and_an_empty_response_are_refused() -> None:
    assert _findings(_sentences(2), [], []) == (
        f"UNACCOUNTED_SENTENCE: {EV}#S1",
        f"UNACCOUNTED_SENTENCE: {EV}#S2",
    )


def test_duplicate_proposition_ids_are_refused() -> None:
    props = [_p("P1", 1), _p("P1", 2)]
    assert "DUPLICATE_PROPOSITION: P1" in _findings(
        _sentences(2), props, [_d("P1", K.ASSERT_CLAIM)]
    )


def test_a_sentence_both_carried_and_declared_or_declared_twice_is_refused() -> None:
    both = _findings(_sentences(1), [_p("P1", 1)], [_d("P1", K.ASSERT_CLAIM)], [_silent(1)])
    assert both == (f"DOUBLE_ACCOUNTED_SENTENCE: {EV}#S1",)
    twice = _findings(_sentences(1), [], [], [_silent(1), _silent(1)])
    assert twice == (f"DOUBLE_ACCOUNTED_SENTENCE: {EV}#S1",)


def test_a_disposition_must_cite_the_evidence_its_proposition_comes_from() -> None:
    sentences = {**_sentences(1), **_sentences(1, "EV-2")}
    props = [_p("P1", 1), _p("P2", 1, evidence_id="EV-2")]
    drafts = [_d("P1", K.ASSERT_CLAIM, EV), _d("P2", K.ASSERT_CLAIM, EV)]
    (finding,) = _findings(sentences, props, drafts)
    assert finding.startswith("PROPOSITION_EVIDENCE_MISMATCH: P2")


def test_every_missing_id_is_named_and_none_is_invented() -> None:
    props = [_p("P1", 1), _p("P2", 2), _p("P3", 3)]
    findings = _findings(_sentences(4), props, [])
    assert findings == (
        f"UNACCOUNTED_SENTENCE: {EV}#S4",
        "UNACCOUNTED_PROPOSITION: P1",
        "UNACCOUNTED_PROPOSITION: P2",
        "UNACCOUNTED_PROPOSITION: P3",
    )


# ------------------------------------------------------------------ source → proposition → claim


def test_17_every_sentence_and_every_proposition_accounted_passes() -> None:
    assert _findings(_h9_sentences(), _h9_inventory(), _h9_complete(), _h9_examples()) == ()


def test_18_an_unaccounted_sentence_fails_at_source_accounting() -> None:
    """v3's answer-key shape, now in a model response: the acknowledgement sentence is
    neither carried nor declared."""
    inventory = [p for p in _h9_inventory() if p.proposition_id != "P5"]
    drafts = [d for d in _h9_complete() if d.proposition_id != "P5"]
    assert _findings(_h9_sentences(), inventory, drafts, _h9_examples()) == (
        f"UNACCOUNTED_SENTENCE: {H9_EV}#S3",
    )


def test_19_a_covered_source_with_an_omitted_proposition_fails_at_claim_accounting() -> None:
    drafts = [d for d in _h9_complete() if d.proposition_id != "P5"]
    findings = _findings(_h9_sentences(), _h9_inventory(), drafts, _h9_examples())
    assert findings == ("UNACCOUNTED_PROPOSITION: P5",)


def test_20_the_two_boundaries_fail_with_distinct_reasons() -> None:
    source = _unaccounted_sentence_reason()
    claim = "UNACCOUNTED_PROPOSITION"
    assert source == "UNACCOUNTED_SENTENCE" and source != claim


def _unaccounted_sentence_reason() -> str:
    inventory = [p for p in _h9_inventory() if p.proposition_id != "P5"]
    drafts = [d for d in _h9_complete() if d.proposition_id != "P5"]
    (finding,) = _findings(_h9_sentences(), inventory, drafts, _h9_examples())
    return finding.split(":", 1)[0]


@pytest.mark.parametrize("n", [1, 5, 12])
def test_sentence_ids_are_stable_and_one_based(n: int) -> None:
    text = " ".join(f"Rule {i} applies." for i in range(n))
    ids = [sid for sid, _ in numbered_sentences("EV-X", text)]
    assert ids == [f"EV-X#S{i}" for i in range(1, n + 1)]
