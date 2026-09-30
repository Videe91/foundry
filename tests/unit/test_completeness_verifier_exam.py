"""The semantic completeness verifier's certification exam (prepared offline, never run here).

A verifier is not trusted because a prompt was written for it. It must pass a sealed exam:
every case is one ``CompletenessRequest`` with a hidden expected verdict per proposition, and
the exam is all-or-nothing. This file checks the exam's coverage, its leakage discipline and
its scorer, using scripted verifiers only. No live call.
"""

from __future__ import annotations

import json

from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    PropositionVerdict,
)
from foundry.experiments.completeness_verifier_exam.exam import (
    CASES,
    CATEGORIES,
    CERTIFIED,
    EXAM_VERSION,
    NOT_CERTIFIED,
    exam_sha256,
    score,
)

REQUIRED = {
    "COMPLETE_PARAPHRASE",
    "FAITHFUL_DECOMPOSITION",
    "JOINTLY_COMPLETE_THREE_CLAIMS",
    "MISSING_CONDITION",
    "MISSING_CONSEQUENCE",
    "MISSING_EXCEPTION",
    "MISSING_SECOND_SENTENCE",
    "MISSING_CLAUSE",
    "UNSUPPORTED_ADDITION",
    "CONTRADICTION",
    "LEXICAL_OVERLAP",
    "DEADLINE_VS_REFUSAL",
    "ELIGIBILITY_VS_CONSEQUENCE",
    "SUPPORT_DISPOSITION",
    "CORRECTION_DISPOSITION",
}


def _answer(expected: dict[str, str]):  # type: ignore[no-untyped-def]
    def verify(request: CompletenessRequest) -> CompletenessReport:
        return CompletenessReport(
            verdicts=tuple(
                PropositionVerdict(
                    proposition_id=p.proposition_id,
                    verdict=expected[p.proposition_id],  # type: ignore[arg-type]
                    claim_refs=tuple(c.ref for c in p.claims),
                    missing=("x",) if expected[p.proposition_id] == "INCOMPLETE" else (),
                    unsupported=("x",) if expected[p.proposition_id] == "OVERREACH" else (),
                    contradictory=("x",) if expected[p.proposition_id] == "CONTRADICTORY" else (),
                )
                for p in request.propositions
            )
        )

    return verify


def _oracle(request: CompletenessRequest) -> CompletenessReport:
    case = next(c for c in CASES if c.request == request)
    return _answer(dict(case.expected))(request)


def test_the_exam_covers_every_required_category_in_both_directions() -> None:
    assert EXAM_VERSION == "ie2-semantic-completeness-exam-v1"
    assert set(CATEGORIES) >= REQUIRED
    for category in REQUIRED:
        assert any(c.category == category for c in CASES), category
    verdicts = {v for c in CASES for _, v in c.expected}
    assert verdicts == {"COMPLETE", "INCOMPLETE", "OVERREACH", "CONTRADICTORY"}
    completes = sum(1 for c in CASES for _, v in c.expected if v == "COMPLETE")
    others = sum(1 for c in CASES for _, v in c.expected if v != "COMPLETE")
    assert completes >= 6 and others >= 8, "both failure directions are examined"


def test_every_case_is_a_valid_request_with_one_expected_verdict_per_proposition() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        assert {p for p, _ in case.expected} == {
            p.proposition_id for p in case.request.propositions
        }, case.id


def test_no_request_leaks_its_expected_verdict() -> None:
    for case in CASES:
        text = json.dumps(case.request.model_dump(mode="json")).upper()
        for word in ("INCOMPLETE", "OVERREACH", "CONTRADICTORY", "EXPECTED", "VERDICT"):
            assert word not in text, (case.id, word)


def test_the_exam_is_held_out_from_the_validation_corpus() -> None:
    from foundry.experiments.locus_validation_v6.corpus import DOCUMENTS

    corpus = " ".join(d.text for d in DOCUMENTS.values()).lower()
    for case in CASES:
        if case.category == "DEADLINE_VS_REFUSAL" and case.id.endswith("K-CREDIT"):
            continue  # the one named regression, taken from the recorded v6 failure
        for p in case.request.propositions:
            assert p.statement.lower() not in corpus, case.id


def test_a_verifier_answering_every_case_right_is_certified() -> None:
    result = score(_oracle)
    assert result.standing == CERTIFIED and result.failures == ()


def test_a_verifier_that_always_says_complete_is_not_certified() -> None:
    result = score(lambda r: _answer({p.proposition_id: "COMPLETE" for p in r.propositions})(r))
    assert result.standing == NOT_CERTIFIED
    failed = {f.split(":", 1)[0] for f in result.failures}
    assert {"MISSING_CONSEQUENCE", "UNSUPPORTED_ADDITION", "CONTRADICTION"} <= failed


def test_a_verifier_that_rejects_decomposition_is_not_certified() -> None:
    result = score(lambda r: _answer({p.proposition_id: "INCOMPLETE" for p in r.propositions})(r))
    failed = {f.split(":", 1)[0] for f in result.failures}
    assert result.standing == NOT_CERTIFIED
    assert {"FAITHFUL_DECOMPOSITION", "JOINTLY_COMPLETE_THREE_CLAIMS"} <= failed


def test_an_unparseable_answer_fails_its_case() -> None:
    result = score(lambda r: None)
    assert result.standing == NOT_CERTIFIED and len(result.failures) == len(CASES)


def test_the_exam_digest_is_deterministic() -> None:
    assert exam_sha256() == exam_sha256()
