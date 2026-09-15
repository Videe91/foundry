"""Deterministic case evaluation of spec §7.1 over T3 ``LedgerRecord``s (T4).

Records are produced through the REAL governor and ``assimilate_delta`` by scripted
locus fakes whose batches mint the drafts the locus policy prescribes from the actual
``ReasoningRequest``; each failure tag is provoked by mutating the scripted drafts (never
the records), except ``UNGOVERNED_SUPERSEDE``, which no governed path can produce and is
therefore a forged record. No provider, no network, no key; the real adapter classes are
never constructed; sockets are blocked for the module.
"""

from __future__ import annotations

import ast
import os
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import ClassVar

import pytest

from foundry.adapters.semantics.xai_reasoner import (
    LOCUS_POLICY_VERSION,
    LOCUS_SYSTEM_INSTRUCTION,
    XAIProviderError,
)
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.common import Authority
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    ConflictsWithProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    SupportsClaimProposal,
)
from foundry.experiments.locus_validation import evaluation as evaluation_module
from foundry.experiments.locus_validation.corpus import (
    DOCUMENTS,
    LEDGERS,
    PROJECT_IDS,
    SCOPES,
    Ledger,
    evidence_id,
)
from foundry.experiments.locus_validation.evaluation import (
    CaseResult,
    evaluate_ledger,
    evaluate_run,
)
from foundry.experiments.locus_validation.expectations import CASE_IDS, FAILURE_TAGS
from foundry.experiments.locus_validation.protocol import (
    CALLS_PER_LEDGER,
    MAX_FRONTIER_CALLS,
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
)
from foundry.experiments.locus_validation.recording import (
    ExperimentBudget,
    LocusRecordingReasoner,
)
from foundry.experiments.locus_validation.runner import (
    LedgerRecord,
    RunResult,
    RunStatus,
    run_experiment,
    run_ledger,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 15, tzinfo=UTC)
LOCUS_FINGERPRINT = ReasonerFingerprint(
    provider=PROVIDER, model=MODEL, policy_version=LOCUS_POLICY_VERSION
)
LEDGER_OF_PROJECT: dict[str, Ledger] = {project: ledger for ledger, project in PROJECT_IDS.items()}

type Drafts = tuple[SemanticJudgment, ...]
type Batch = Drafts | Callable[[ReasoningRequest], Drafts] | BaseException
type Mutation = Callable[[Drafts], Drafts]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def _no_provider_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    yield
    assert "XAI_API_KEY" not in os.environ


# --- fakes (the T3 idiom) -----------------------------------------------------------


class LocusFake:
    """Mirrors the real locus adapter's observable identity; a scripted ``propose``
    that returns the scripted batch, calls it with the request, or raises it."""

    policy_version: ClassVar[str] = LOCUS_POLICY_VERSION
    system_instruction: ClassVar[str] = LOCUS_SYSTEM_INSTRUCTION
    include_comparison_context: ClassVar[bool] = True
    reasoning_effort: ClassVar[str] = REASONING_EFFORT

    def __init__(self, batches: list[Batch]) -> None:
        self._batches = batches
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return LOCUS_FINGERPRINT

    def propose(self, request: ReasoningRequest) -> Drafts:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        batch = self._batches[index]
        if isinstance(batch, BaseException):
            raise batch
        return batch(request) if callable(batch) else batch


# --- draft builders -----------------------------------------------------------------


def _judgment(
    ledger: Ledger, judgment_id: str, proposal: JudgmentProposal, cited: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT_IDS[ledger],
        proposal=proposal,
        visible_evidence_ids=(cited,),
        rationale=f"Scripted draft {judgment_id}.",
        reasoner=LOCUS_FINGERPRINT,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _candidate(ledger: Ledger, judgment_id: str, cited: str, label: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=f"CAND-{judgment_id}",
        subject=f"{label} subject",
        facet=f"{label} facet",
        scope=(SCOPES[ledger],),
        evidence_ids=(cited,),
    )


def _create(ledger: Ledger, judgment_id: str, cited: str, label: str) -> SemanticJudgment:
    proposal = CreateAddressProposal(candidate=_candidate(ledger, judgment_id, cited, label))
    return _judgment(ledger, judgment_id, proposal, cited)


def _bind(
    ledger: Ledger, judgment_id: str, address_id: str, cited: str, label: str
) -> SemanticJudgment:
    proposal = BindToAddressProposal(
        candidate=_candidate(ledger, judgment_id, cited, label), address_id=address_id
    )
    return _judgment(ledger, judgment_id, proposal, cited)


def _assert(
    ledger: Ledger, judgment_id: str, address_id: str, cited: str, predicate: str, value: str
) -> SemanticJudgment:
    proposal = AssertClaimProposal(
        address_id=address_id,
        predicate=predicate,
        value=ClaimValue(kind=ClaimValueKind.TEXT, text=value),
        evidence_ids=(cited,),
        authority=Authority.INFERRED,
    )
    return _judgment(ledger, judgment_id, proposal, cited)


def _support(ledger: Ledger, judgment_id: str, claim_id: str, cited: str) -> SemanticJudgment:
    proposal = SupportsClaimProposal(claim_id=claim_id, evidence_ids=(cited,))
    return _judgment(ledger, judgment_id, proposal, cited)


def _supersede(ledger: Ledger, judgment_id: str, target: str, cited: str) -> SemanticJudgment:
    proposal = SupersedeProposal(target_judgment_id=target, reason="Scripted supersession.")
    return _judgment(ledger, judgment_id, proposal, cited)


def _conflict(
    ledger: Ledger, judgment_id: str, claim_a: str, claim_b: str, cited: str
) -> SemanticJudgment:
    proposal = ConflictsWithProposal(claim_a=claim_a, claim_b=claim_b)
    return _judgment(ledger, judgment_id, proposal, cited)


# --- the scripted specification: drafts derived from the real request ---------------


def _seed_create_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T1-create-{document}"


def _seed_claim_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T1-claim-{document}"


def _revision_claim_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T2-claim-{document}"


def _revision_bind_id(ledger: Ledger, document: str) -> str:
    return f"J-{ledger}-T2-bind-{document}"


def _extra_create_id(ledger: Ledger) -> str:
    return f"J-{ledger}-T2-create-{DOCUMENTS[ledger][1]}-new"


def _extra_claim_id(ledger: Ledger) -> str:
    return f"J-{ledger}-T2-claim-{DOCUMENTS[ledger][1]}-new"


def _support_id(ledger: Ledger) -> str:
    return f"J-{ledger}-T2-support-{DOCUMENTS[ledger][2]}"


def _supersede_id(ledger: Ledger) -> str:
    return f"J-{ledger}-T2-supersede-{DOCUMENTS[ledger][3]}"


def _seed_address(ledger: Ledger, document: str) -> str:
    return address_id_for(PROJECT_IDS[ledger], _seed_create_id(ledger, document))


def _extra_address(ledger: Ledger) -> str:
    return address_id_for(PROJECT_IDS[ledger], _extra_create_id(ledger))


def _seed_claim(ledger: Ledger, document: str) -> str:
    return claim_id_for(PROJECT_IDS[ledger], _seed_claim_id(ledger, document))


def _revision_claim(ledger: Ledger, document: str) -> str:
    return claim_id_for(PROJECT_IDS[ledger], _revision_claim_id(ledger, document))


def _extra_claim(ledger: Ledger) -> str:
    return claim_id_for(PROJECT_IDS[ledger], _extra_claim_id(ledger))


def _ledger_and_t(request: ReasoningRequest) -> tuple[Ledger, int]:
    ledger = LEDGER_OF_PROJECT[request.project_id]
    t = 1 if all(item.supersedes_evidence_id is None for item in request.evidence) else 2
    return ledger, t


def _document_of_address(ledger: Ledger, address_id: str) -> str:
    for document in DOCUMENTS[ledger]:
        if _seed_address(ledger, document) == address_id:
            return document
    raise AssertionError(f"unknown seed address {address_id}")


def _prescribed(request: ReasoningRequest) -> Drafts:
    """Per call, the drafts the locus policy prescribes for the sealed corpus, minted
    from what the request actually shows. The revision Call 2 is minted from the
    deterministic ids so that a mutated Call 1 does not change its shape."""
    ledger, t = _ledger_and_t(request)
    first_call = JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds
    documents = DOCUMENTS[ledger]
    if t == 1 and first_call:
        assert request.known_addresses == ()
        return tuple(
            _create(ledger, _seed_create_id(ledger, doc), item.evidence_id, doc)
            for doc, item in zip(documents, request.evidence, strict=True)
        )
    if t == 1:
        return tuple(
            _assert(
                ledger,
                _seed_claim_id(ledger, doc),
                address.address_id,
                evidence_id(doc, 1),
                f"{doc} rule",
                f"{doc} first value",
            )
            for address in request.known_addresses
            for doc in (_document_of_address(ledger, address.address_id),)
        )
    if first_call:
        binds = tuple(
            _bind(
                ledger,
                _revision_bind_id(ledger, doc),
                address.address_id,
                evidence_id(doc, 2),
                doc,
            )
            for address in request.known_addresses
            for doc in (_document_of_address(ledger, address.address_id),)
        )
        extra = _create(
            ledger, _extra_create_id(ledger), evidence_id(documents[1], 2), f"{documents[1]} new"
        )
        return (*binds, extra)
    d1, d2, d3, d4 = documents
    return (
        _assert(
            ledger,
            _revision_claim_id(ledger, d1),
            _seed_address(ledger, d1),
            evidence_id(d1, 2),
            f"{d1} addition",
            f"{d1} added value",
        ),
        _assert(
            ledger,
            _revision_claim_id(ledger, d2),
            _seed_address(ledger, d2),
            evidence_id(d2, 2),
            f"{d2} addition",
            f"{d2} added value",
        ),
        _assert(
            ledger,
            _extra_claim_id(ledger),
            _extra_address(ledger),
            evidence_id(d2, 2),
            f"{d2} new rule",
            f"{d2} new value",
        ),
        _support(ledger, _support_id(ledger), _seed_claim(ledger, d3), evidence_id(d3, 2)),
        _assert(
            ledger,
            _revision_claim_id(ledger, d4),
            _seed_address(ledger, d4),
            evidence_id(d4, 2),
            f"{d4} rule",
            f"{d4} second value",
        ),
        _supersede(ledger, _supersede_id(ledger), _seed_claim_id(ledger, d4), evidence_id(d4, 2)),
    )


def _mutated(mutation: Mutation) -> Callable[[ReasoningRequest], Drafts]:
    """The prescribed batch for the request, passed through ``mutation``."""
    return lambda request: mutation(_prescribed(request))


def _script(*overrides: tuple[int, Batch], calls: int = MAX_FRONTIER_CALLS) -> list[Batch]:
    batches: list[Batch] = [_prescribed] * calls
    for index, batch in overrides:
        batches[index] = batch
    return batches


# --- harness ------------------------------------------------------------------------


def _clock() -> Callable[[], datetime]:
    tick = count()
    return lambda: T0.replace(minute=next(tick) % 60, hour=next(tick) // 60 % 24)


def _ids() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _run(*overrides: tuple[int, Batch]) -> RunResult:
    fake = LocusFake(_script(*overrides))
    return run_experiment(inner=fake, budget=ExperimentBudget(), clock=_clock(), id_factory=_ids())


def _alpha(*overrides: tuple[int, Batch]) -> LedgerRecord:
    """One alpha ledger through ``run_ledger`` with per-call overrides (indices 0..3)."""
    fake = LocusFake(_script(*overrides, calls=CALLS_PER_LEDGER))
    wrapper = LocusRecordingReasoner(fake, ledger="alpha", budget=ExperimentBudget())
    return run_ledger(ledger="alpha", reasoner=wrapper, clock=_clock(), id_factory=_ids())


def _alpha_mutated(
    call_index: int, mutation: Mutation, *more: tuple[int, Mutation]
) -> LedgerRecord:
    overrides: list[tuple[int, Batch]] = [(call_index, _mutated(mutation))]
    overrides += [(index, _mutated(m)) for index, m in more]
    return _alpha(*overrides)


def _by_case(results: tuple[CaseResult, ...]) -> dict[str, CaseResult]:
    assert [r.case_id for r in results] == list(CASE_IDS)
    return {r.case_id: r for r in results}


def _assert_passed(result: CaseResult) -> None:
    assert result.structural_passed is True, (result.case_id, result.tags, result.detail)
    assert result.tags == ()


def _assert_failed(result: CaseResult, *tags: str) -> None:
    assert result.structural_passed is False, (result.case_id, result.detail)
    assert set(tags) <= set(result.tags), (result.case_id, result.tags, result.detail)
    assert set(result.tags) <= set(FAILURE_TAGS)


def _assert_not_run(result: CaseResult) -> None:
    assert result.structural_passed is None
    assert result.tags == ()
    assert result.detail == "delta not run"
    assert result.evidence == {}


A1, A2, A3, A4 = DOCUMENTS["alpha"]


# --- the correct stories ------------------------------------------------------------


def test_correct_alpha_and_beta_stories_pass_every_case_with_no_tags() -> None:
    run = _run()
    assert run.status is RunStatus.COMPLETED

    results = evaluate_run(run)

    assert len(results) == 12
    assert [r.ledger for r in results] == ["alpha"] * 6 + ["beta"] * 6
    assert [r.case_id for r in results] == list(CASE_IDS) * 2
    for result in results:
        _assert_passed(result)
    for ledger, record in zip(LEDGERS, run.ledgers, strict=True):
        assert results[LEDGERS.index(ledger) * 6 :][:6] == evaluate_ledger(record)


def test_evidence_carries_ids_and_counts_only() -> None:
    record = _alpha()
    cases = _by_case(evaluate_ledger(record))

    seed = cases["S01"].evidence
    assert seed["address_count"] == 4
    assert sorted(seed["address_ids"]) == sorted(
        _seed_address("alpha", d) for d in DOCUMENTS["alpha"]
    )
    assert seed["create_count"] == 4 and seed["bind_count"] == 0
    assert seed["rejected_count"] == 0

    v01 = cases["V01"].evidence
    assert v01["address_id"] == _seed_address("alpha", A1)
    assert v01["bound_address_ids"] == [_seed_address("alpha", A1)]
    assert v01["seed_claim_ids"] == [_seed_claim("alpha", A1)]
    assert v01["new_claim_ids"] == [_revision_claim("alpha", A1)]
    assert v01["address_count"] == 5

    v03 = cases["V03"].evidence
    assert v03["created_address_ids"] == [_extra_address("alpha")]
    assert v03["created_claim_ids"] == [_extra_claim("alpha")]
    assert v03["address_count"] == 5

    v04 = cases["V04"].evidence
    assert v04["support_judgment_ids"] == [_support_id("alpha")]
    assert v04["assert_count"] == 0

    v05 = cases["V05"].evidence
    assert v05["supersede_judgment_ids"] == [_supersede_id("alpha")]
    assert v05["supersede_target_judgment_id"] == _seed_claim_id("alpha", A4)
    assert v05["supersede_route"] == AdmissionRoute.REQUIRE_SECOND_LENS.value
    assert v05["supersede_applied"] is False
    assert v05["pending_judgment_ids"] == [_supersede_id("alpha")]
    assert v05["conflict_count"] == 0
    assert v05["human_authorizations"] == 0

    for result in cases.values():
        for value in result.evidence.values():
            assert isinstance(value, int | str | list | bool | type(None))
            if isinstance(value, list):
                assert all(isinstance(item, str) for item in value)


# --- one mutation per tag -----------------------------------------------------------


def _drop(judgment_id: str) -> Mutation:
    return lambda drafts: tuple(d for d in drafts if d.judgment_id != judgment_id)


def _add(*extra: SemanticJudgment) -> Mutation:
    return lambda drafts: (*drafts, *extra)


def _replace(judgment_id: str, replacement: SemanticJudgment) -> Mutation:
    return lambda drafts: tuple(replacement if d.judgment_id == judgment_id else d for d in drafts)


def test_over_split_a_create_citing_d1_revised() -> None:
    stray = _create("alpha", "J-alpha-T2-create-A1-stray", evidence_id(A1, 2), f"{A1} stray")
    record = _alpha_mutated(2, _add(stray))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_passed(cases["S01"])
    _assert_failed(cases["V01"], "OVER_SPLIT")
    _assert_failed(cases["V03"], "OVER_SPLIT")
    assert cases["V03"].evidence["address_count"] == 6
    _assert_passed(cases["V02"])
    _assert_passed(cases["V04"])
    _assert_passed(cases["V05"])


def test_under_split_v03_asserted_at_x2_with_no_creation() -> None:
    merged = _assert(
        "alpha",
        _extra_claim_id("alpha"),
        _seed_address("alpha", A2),
        evidence_id(A2, 2),
        f"{A2} new rule",
        f"{A2} new value",
    )
    record = _alpha_mutated(
        2, _drop(_extra_create_id("alpha")), (3, _replace(_extra_claim_id("alpha"), merged))
    )
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V03"], "UNDER_SPLIT")
    assert cases["V03"].evidence["address_count"] == 4
    assert cases["V03"].evidence["created_address_ids"] == []
    _assert_failed(cases["V02"], "EXTRA_DRAFT")
    _assert_passed(cases["V01"])
    _assert_passed(cases["V04"])
    _assert_passed(cases["V05"])


def test_missing_extension_no_new_claim_at_x1() -> None:
    record = _alpha_mutated(3, _drop(_revision_claim_id("alpha", A1)))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V01"], "MISSING_EXTENSION")
    assert cases["V01"].tags == ("MISSING_EXTENSION",)
    assert cases["V01"].evidence["new_claim_ids"] == []
    for case_id in ("S01", "V02", "V03", "V04", "V05"):
        _assert_passed(cases[case_id])


def test_duplicate_assertion_an_applied_assert_citing_d3_revised() -> None:
    reasserted = _assert(
        "alpha",
        "J-alpha-T2-claim-A3-again",
        _seed_address("alpha", A3),
        evidence_id(A3, 2),
        f"{A3} rule restated",
        f"{A3} restated value",
    )
    record = _alpha_mutated(3, _add(reasserted))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V04"], "DUPLICATE_ASSERTION")
    assert cases["V04"].evidence["assert_count"] == 1
    assert cases["V04"].evidence["duplicate_rejection_count"] == 0
    for case_id in ("S01", "V01", "V02", "V03", "V05"):
        _assert_passed(cases[case_id])


def test_duplicate_assertion_a_structural_duplicate_refusal() -> None:
    identical = _assert(
        "alpha",
        "J-alpha-T2-claim-A3-identical",
        _seed_address("alpha", A3),
        evidence_id(A3, 2),
        f"{A3} rule",
        f"{A3} first value",
    )
    record = _alpha_mutated(3, _add(identical))
    assert record.status == "COMPLETED"
    routes = [d.route for d in record.deltas[1].stage_decisions[1]]
    assert routes[-1] is AdmissionRoute.REJECT

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V04"], "DUPLICATE_ASSERTION")
    assert cases["V04"].evidence["duplicate_rejection_count"] == 1


def test_missing_supersede() -> None:
    record = _alpha_mutated(3, _drop(_supersede_id("alpha")))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V05"], "MISSING_SUPERSEDE")
    assert cases["V05"].tags == ("MISSING_SUPERSEDE",)
    assert cases["V05"].evidence["supersede_judgment_ids"] == []
    assert cases["V05"].evidence["pending_judgment_ids"] == []
    for case_id in ("S01", "V01", "V02", "V03", "V04"):
        _assert_passed(cases[case_id])


def test_wrong_supersede_target_a_supersede_of_a_claim_at_x1() -> None:
    wrong = _supersede(
        "alpha", _supersede_id("alpha"), _seed_claim_id("alpha", A1), evidence_id(A4, 2)
    )
    record = _alpha_mutated(3, _replace(_supersede_id("alpha"), wrong))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V01"], "WRONG_SUPERSEDE_TARGET")
    _assert_failed(cases["V05"], "WRONG_SUPERSEDE_TARGET")
    assert cases["V05"].evidence["supersede_target_judgment_id"] == _seed_claim_id("alpha", A1)
    for case_id in ("S01", "V02", "V03", "V04"):
        _assert_passed(cases[case_id])


def test_conflict_instead_of_correction() -> None:
    conflict = _conflict(
        "alpha",
        "J-alpha-T2-conflict-A4",
        _seed_claim("alpha", A4),
        _revision_claim("alpha", A4),
        evidence_id(A4, 2),
    )
    record = _alpha_mutated(3, _replace(_supersede_id("alpha"), conflict))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V05"], "CONFLICT_INSTEAD_OF_CORRECTION", "MISSING_SUPERSEDE")
    assert cases["V05"].evidence["conflict_count"] == 1
    for case_id in ("S01", "V01", "V02", "V03", "V04"):
        _assert_passed(cases[case_id])


def test_wrong_bind_d3_revised_bound_to_x4() -> None:
    misbound = _bind(
        "alpha", _revision_bind_id("alpha", A3), _seed_address("alpha", A4), evidence_id(A3, 2), A3
    )
    record = _alpha_mutated(2, _replace(_revision_bind_id("alpha", A3), misbound))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V04"], "WRONG_BIND")
    assert cases["V04"].tags == ("WRONG_BIND",)
    assert cases["V04"].evidence["bound_address_ids"] == [_seed_address("alpha", A4)]
    for case_id in ("S01", "V01", "V02", "V03", "V05"):
        _assert_passed(cases[case_id])


def test_extra_draft_a_second_call_one_bind_citing_d1_revised() -> None:
    second = _bind(
        "alpha", "J-alpha-T2-bind-A1-again", _seed_address("alpha", A1), evidence_id(A1, 2), A1
    )
    record = _alpha_mutated(2, _add(second))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V01"], "EXTRA_DRAFT")
    assert cases["V01"].tags == ("EXTRA_DRAFT",)
    assert cases["V01"].evidence["call_one_draft_count"] == 2
    for case_id in ("S01", "V02", "V03", "V04", "V05"):
        _assert_passed(cases[case_id])


def test_extra_draft_a_call_two_kind_outside_the_expected_set_for_d4_revised() -> None:
    stray = _support("alpha", "J-alpha-T2-support-A4", _seed_claim("alpha", A4), evidence_id(A4, 2))
    record = _alpha_mutated(3, _add(stray))
    assert record.status == "COMPLETED"

    cases = _by_case(evaluate_ledger(record))

    _assert_failed(cases["V05"], "EXTRA_DRAFT")
    assert cases["V05"].tags == ("EXTRA_DRAFT",)
    for case_id in ("S01", "V01", "V02", "V03", "V04"):
        _assert_passed(cases[case_id])


def test_ungoverned_supersede_a_forged_record_showing_the_model_supersede_applied() -> None:
    record = _alpha()
    assert record.final_state is not None
    semantic = record.final_state.semantic
    assert _supersede_id("alpha") not in semantic.applied_judgment_ids
    forged_semantic = semantic.model_copy(
        update={"applied_judgment_ids": (*semantic.applied_judgment_ids, _supersede_id("alpha"))}
    )
    forged = record.model_copy(
        update={"final_state": record.final_state.model_copy(update={"semantic": forged_semantic})}
    )

    cases = _by_case(evaluate_ledger(forged))

    _assert_failed(cases["V05"], "UNGOVERNED_SUPERSEDE")
    assert cases["V05"].evidence["supersede_applied"] is True
    assert cases["V05"].evidence["ungoverned_supersede_judgment_ids"] == [_supersede_id("alpha")]
    _assert_passed(cases["S01"])


# --- deltas that did not run --------------------------------------------------------


def test_a_ledger_failed_after_t1_evaluates_s01_and_leaves_the_revision_cases_none() -> None:
    record = _alpha((2, XAIProviderError("PROVIDER_FAILURE")))
    assert record.status == "FAILED"
    assert [d.t for d in record.deltas] == [1, 2]
    assert record.deltas[1].requests == ()

    cases = _by_case(evaluate_ledger(record))

    _assert_passed(cases["S01"])
    for case_id in ("V01", "V02", "V03", "V04", "V05"):
        _assert_not_run(cases[case_id])


def test_a_revision_that_failed_after_call_one_is_evaluated_from_the_ledger_events() -> None:
    record = _alpha((3, XAIProviderError("PROVIDER_FAILURE")))
    assert record.status == "FAILED"
    assert record.deltas[1].stage_decisions == ((), ())
    assert len(record.deltas[1].requests) == 1

    cases = _by_case(evaluate_ledger(record))

    _assert_passed(cases["S01"])
    v01 = cases["V01"]
    assert v01.structural_passed is False
    assert v01.evidence["bound_address_ids"] == [_seed_address("alpha", A1)]
    assert v01.evidence["new_claim_ids"] == []
    _assert_failed(v01, "MISSING_EXTENSION")
    assert cases["V03"].evidence["address_count"] == 5
    _assert_failed(cases["V05"], "MISSING_SUPERSEDE")


def test_a_not_run_ledger_and_a_ledger_that_never_answered_its_seed_are_all_none() -> None:
    run = _run((0, XAIProviderError("PROVIDER_FAILURE")))
    alpha, beta = run.ledgers
    assert alpha.status == "FAILED" and alpha.deltas[0].requests == ()
    assert beta.status == "NOT_RUN"

    results = evaluate_run(run)

    assert len(results) == 12
    assert [r.ledger for r in results] == ["alpha"] * 6 + ["beta"] * 6
    assert [r.case_id for r in results] == list(CASE_IDS) * 2
    for result in results:
        _assert_not_run(result)


def test_evaluate_run_is_the_two_ledger_evaluations_alpha_then_beta() -> None:
    run = _run((5, XAIProviderError("PROVIDER_FAILURE")))
    alpha, beta = run.ledgers
    assert alpha.status == "COMPLETED" and beta.status == "FAILED"

    results = evaluate_run(run)

    assert results == (*evaluate_ledger(alpha), *evaluate_ledger(beta))
    assert all(r.structural_passed is True for r in results[:6])
    assert results[6].case_id == "S01" and results[6].structural_passed is False
    assert results[6].ledger == "beta"
    for result in results[7:]:
        _assert_not_run(result)


# --- shape --------------------------------------------------------------------------


def test_case_result_is_frozen_and_tags_are_from_the_vocabulary() -> None:
    result = evaluate_ledger(_alpha())[0]
    assert isinstance(result, CaseResult)
    with pytest.raises(Exception):  # noqa: B017 - FrozenModel refuses assignment
        result.structural_passed = False
    assert set(evaluation_module.__all__) == {"CaseResult", "evaluate_ledger", "evaluate_run"}


# --- hygiene: no wording logic, no adapter ------------------------------------------


def _evaluation_tree() -> ast.Module:
    return ast.parse(Path(evaluation_module.__file__).read_text(encoding="utf-8"))


def test_evaluation_never_imports_the_adapter_or_a_text_library() -> None:
    tree = _evaluation_tree()
    modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    for module in modules:
        assert not module.startswith("foundry.adapters"), module
        assert module.split(".")[0] not in {"re", "difflib", "unicodedata", "string"}, module
    assert "foundry.experiments.locus_validation.runner" in modules
    assert "foundry.experiments.locus_validation.expectations" in modules


def test_evaluation_contains_no_wording_comparison() -> None:
    tree = _evaluation_tree()
    forbidden_calls = {"lower", "casefold", "upper", "split", "strip", "find", "count"}
    forbidden_attributes = {"predicate", "text", "subject", "facet", "rationale", "reason"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls, ast.dump(node)
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes, ast.dump(node)
        if isinstance(node, ast.Compare):
            for operator, comparator in zip(node.ops, node.comparators, strict=True):
                if isinstance(operator, ast.In | ast.NotIn):
                    left_is_text = isinstance(node.left, ast.Constant) and isinstance(
                        node.left.value, str
                    )
                    right_is_text = isinstance(comparator, ast.Constant) and isinstance(
                        comparator.value, str
                    )
                    assert not (left_is_text or right_is_text), ast.dump(node)
    source = Path(evaluation_module.__file__).read_text(encoding="utf-8")
    assert "section_text" not in source
    assert "model_dump_json" not in source
