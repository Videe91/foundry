"""Offline proofs of the IE2 + IE3 long-horizon harness (no live call).

Fast tests pin the corpus identity, the sealed answer key, the identities, budgets, gates and
standing. Pipeline tests drive the real IE2 -> authority -> IE3 path with oracle reasoners
(``tests/unit/_lh23_oracle.py``) over T1..T3: the correct oracle passes every mechanical
check, and oracles that break a law are caught by the matching check. The full 16-turn oracle
takes about twenty minutes (every judgment replays the ledger in production governance) and
runs only with ``LH23_FULL_ORACLE=1``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from foundry.experiments.long_horizon_ie2_ie3 import corpus, expectations, protocol, recording, seal
from foundry.experiments.long_horizon_ie2_ie3.adjudication import adjudication_bundle, standing
from foundry.experiments.long_horizon_ie2_ie3.evaluation import CheckResult, Evaluation, evaluate
from foundry.experiments.long_horizon_ie2_ie3.expectations import ADJUDICATION_QUESTIONS, TURNS
from foundry.experiments.long_horizon_ie2_ie3.runner import RunRecord
from tests.unit._lh23_oracle import AT, OracleIE2, OracleIE3

PACKAGE = Path("src/foundry/experiments/long_horizon_ie2_ie3")
HISTORICAL = Path(protocol.HISTORICAL_ARTIFACT_DIR) / "manifest.json"


# --------------------------------------------------------------------------- corpus and key


def test_the_corpus_is_the_sealed_9p3_corpus_byte_for_byte() -> None:
    historical = json.loads(HISTORICAL.read_text())
    assert corpus.historical_corpus_findings(historical) == ()
    assert [len(corpus.delta(t)) for t in range(1, 17)] == [12] * 16
    assert all(
        item.project_id == protocol.PROJECT_ID for t in range(1, 17) for item in corpus.delta(t)
    )


def test_a_changed_historical_item_is_found() -> None:
    historical = json.loads(HISTORICAL.read_text())
    historical["evidence"][40] = {**historical["evidence"][40], "content_sha256": "0" * 64}
    assert any("content_sha256" in f for f in corpus.historical_corpus_findings(historical))


def test_every_sentence_of_every_section_is_accounted_for() -> None:
    assert expectations.source_coverage_findings() == ()
    assert len(expectations.SOURCE_COVERAGE) == 38


def test_the_turns_follow_the_sealed_9p3_key() -> None:
    classes = {t.t: (t.transition, t.target_locus) for t in TURNS}
    assert classes[1] == ("BASELINE", None)
    assert classes[9] == ("COMPATIBLE_EXTENSION", "H")
    assert classes[15] == ("RESTATEMENT", "F"), "T15 restates the 90-second lease"
    assert expectations.CORRECTION_TURNS == (3, 5, 7, 8, 10, 12, 14, 16)
    assert [t.t for t in TURNS if t.ie3_behaviour == "REPLACE_STALE"] == [
        3,
        5,
        7,
        8,
        10,
        12,
        14,
        16,
    ]
    for turn in TURNS[1:]:
        for locus, rng in turn.new_claims.items():
            if locus != turn.target_locus:
                assert rng == (0, 0)
    assert TURNS[8].new_claims["H"] == (1, 2)
    assert TURNS[8].required_current["H"] == ("H-1", "H-2", "H-3", "H-4", "H-5")


def test_the_questions_are_sealed_and_separate_by_layer() -> None:
    ids = [q.id for q in ADJUDICATION_QUESTIONS]
    assert len(ids) == len(set(ids)) == 70
    assert sum(q.layer == "IE2" for q in ADJUDICATION_QUESTIONS) == 44
    assert sum(q.layer == "IE3" for q in ADJUDICATION_QUESTIONS) == 26
    assert {"Q-IE2-T09-H-EXISTING", "Q-IE2-T09-H-4", "Q-IE2-T09-H-5", "Q-IE3-T09-TARGET"} <= set(
        ids
    )


def test_the_key_never_reads_mission_wording() -> None:
    assert all("mission" not in q.question.lower() for q in ADJUDICATION_QUESTIONS)


# --------------------------------------------------------------------------- identities


def test_the_ie2_identity_is_validation_v5s() -> None:
    from foundry.experiments.locus_validation_v5.recording import EXPECTED_IDENTITY

    assert recording.EXPECTED_IE2_IDENTITY == EXPECTED_IDENTITY


def test_the_ie3_identity_is_the_certificates() -> None:
    recording.require_ie3_identity()
    data = Path(protocol.IE3_CERTIFICATE_PATH).read_bytes()
    assert hashlib.sha256(data).hexdigest() == protocol.IE3_CERTIFICATE_SHA256
    record = json.loads(data)
    from tests.certification._intent_graph_exam import graph_certificate_standing

    assert graph_certificate_standing(record) == "CURRENT"
    assert (record["exam_sha256"], record["prompt_sha256"], record["wire_schema_sha256"]) == (
        protocol.IE3_EXAM_SHA256,
        protocol.IE3_PROMPT_SHA256,
        protocol.IE3_WIRE_SCHEMA_SHA256,
    )


def test_the_request_path_never_imports_the_answer_key() -> None:
    assert seal.leakage_findings(PACKAGE) == ()
    for module in seal.REQUEST_PATH_MODULES:
        tree = ast.parse((PACKAGE / f"{module}.py").read_text())
        names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any(
            "expectations" in n or "adjudication" in n or "evaluation" in n for n in names
        )


# --------------------------------------------------------------------------- budgets


class _Refusing:
    fingerprint = OracleIE2.fingerprint

    def propose(self, request: Any) -> tuple[()]:
        return ()


def test_the_ie2_recorder_refuses_a_third_call_and_the_ceilings() -> None:
    from foundry.ports.semantic_reasoner import ReasoningRequest

    budget = recording.RunBudget()
    recorder = recording.IE2Recorder(_Refusing(), budget=budget, guard_identity=False)
    request = ReasoningRequest(project_id=protocol.PROJECT_ID, evidence=())
    recorder.begin_turn(1)
    recorder.propose(request)
    recorder.propose(request)
    with pytest.raises(recording.BudgetExceeded, match="THIRD_CALL"):
        recorder.propose(request)
    budget.ie2_calls = protocol.MAX_IE2_CALLS
    recorder.begin_turn(2)
    with pytest.raises(recording.BudgetExceeded, match="IE2_CEILING"):
        recorder.propose(request)
    budget.ie2_calls = 0
    budget.ie2_cost_usd = Decimal("20.01")
    with pytest.raises(recording.BudgetExceeded, match="COST"):
        recorder.propose(request)


def test_the_ie3_budget_refuses_a_seventeenth_call() -> None:
    budget = recording.RunBudget()
    gate = recording.IE3Budget(budget)
    for _ in range(protocol.MAX_IE3_CALLS):
        gate.admit()
    with pytest.raises(recording.BudgetExceeded, match="IE3_CEILING"):
        gate.admit()


def test_the_live_ie3_wiring_is_the_certification_contestants() -> None:
    from foundry.experiments.long_horizon_ie2_ie3.ie3_runtime import (
        astra_constraints,
        registry_from_certificate,
    )

    constraints = astra_constraints()
    assert (constraints.max_output_tokens, constraints.timeout_seconds) == (16000, 180.0)
    record = json.loads(Path(protocol.IE3_CERTIFICATE_PATH).read_text())
    (descriptor,) = registry_from_certificate(record).descriptors
    assert (descriptor.identity.provider, descriptor.identity.model) == ("openai", "gpt-6-astra")
    assert [t.value for t in descriptor.certified_tasks] == [record["task"]]
    for field, value in (("model", "gpt-6"), ("verdict", "NOT CERTIFIED"), ("task", "X")):
        with pytest.raises(ValueError, match="not this experiment"):
            registry_from_certificate({**record, field: value})


# --------------------------------------------------------------------------- gates and standing


def _git(**overrides: Any) -> seal.GitFacts:
    base = {
        "head_sha": "s",
        "head_parent_sha": "h",
        "head_added_files": tuple(
            f"{protocol.EXPERIMENT_ARTIFACT_DIR}{n}" for n in protocol.SEALED_FILE_NAMES
        ),
        "head_changed_files": tuple(
            f"{protocol.EXPERIMENT_ARTIFACT_DIR}{n}" for n in protocol.SEALED_FILE_NAMES
        ),
        "worktree_clean": True,
        "boundary_commit_is_ancestor": True,
    }
    return seal.GitFacts(**{**base, **overrides})


def _gates(**overrides: Any) -> dict[str, seal.Gate]:
    manifest = seal.build_manifest(harness_sha="h", package_dir=PACKAGE)
    kwargs: dict[str, Any] = {
        "sealed_manifest": manifest,
        "sealed_expectations": expectations.expectations_document(),
        "git": _git(),
        "historical_manifest": json.loads(HISTORICAL.read_text()),
        "certificate_sha256": protocol.IE3_CERTIFICATE_SHA256,
        "certificate_standing": "CURRENT",
        "grpc_dns_resolver": "native",
        "raw_present": (),
        "package_dir": PACKAGE,
        **overrides,
    }
    return {g.name: g for g in seal.preflight_gates(**kwargs)}


def test_every_gate_passes_on_a_sealed_unconsumed_harness() -> None:
    gates = _gates()
    assert tuple(gates) == seal.GATE_NAMES
    assert all(g.passed for g in gates.values()), [g for g in gates.values() if not g.passed]


@pytest.mark.parametrize(
    ("override", "gate"),
    [
        ({"certificate_standing": "SUPERSEDED"}, "ie3_certificate_current"),
        ({"certificate_sha256": "0" * 64}, "ie3_certificate_current"),
        ({"raw_present": ("run.json",)}, "single_use"),
        ({"grpc_dns_resolver": None}, "grpc_dns_resolver_native"),
        ({"git": _git(boundary_commit_is_ancestor=False)}, "root_staleness_boundary_present"),
        ({"git": _git(worktree_clean=False)}, "worktree_clean"),
        ({"git": _git(head_added_files=("x",))}, "seal_commit_adds_exactly_the_sealed_files"),
        ({"sealed_expectations": {"tampered": True}}, "expectations_match_code"),
        ({"sealed_manifest": {"harness_sha": "h"}}, "manifest_matches_code"),
    ],
)
def test_each_gate_refuses_its_defect(override: dict[str, Any], gate: str) -> None:
    assert _gates(**override)[gate].passed is False


def _checks(passed: bool = True) -> dict[str, CheckResult]:
    return {
        "T01-IE2": CheckResult(name="T01-IE2", passed=passed, findings=() if passed else ("X: y",))
    }


def test_the_standing_is_all_or_nothing() -> None:
    yes = {q.id: "YES" for q in ADJUDICATION_QUESTIONS}
    assert standing(_checks(), yes).standing == "LONG_HORIZON_IE2_IE3_VALIDATED"
    assert standing(_checks(False), yes).standing == "LONG_HORIZON_IE2_IE3_NOT_VALIDATED"
    one_no = {**yes, "Q-IE3-T09-TARGET": "NO"}
    result = standing(_checks(), one_no)
    assert result.standing == "LONG_HORIZON_IE2_IE3_NOT_VALIDATED"
    assert result.failed_ie3_questions == ("Q-IE3-T09-TARGET",) and result.ie2_semantic_passed
    missing = dict(yes)
    missing.pop("Q-IE2-T01-A")
    assert standing(_checks(), missing).unanswered == ("Q-IE2-T01-A",)


# --------------------------------------------------------------------------- the pipeline, T1..T3


def _run(turns: tuple[int, ...] = (1, 2, 3), **kwargs: Any) -> RunRecord:
    from foundry.experiments.long_horizon_ie2_ie3.runner import run_experiment

    ie3_keys = ("second_root_at", "root_gap_at", "no_replace_at", "dup_at", "no_root")
    ie3 = OracleIE3(**{k: v for k, v in kwargs.items() if k in ie3_keys})
    ids = count(1)
    return run_experiment(
        ie2=OracleIE2(**{k: v for k, v in kwargs.items() if k not in ie3_keys}),
        ie3_synthesizer=ie3,
        ie3_calls=ie3.records,
        budget=recording.RunBudget(),
        guard_identity=False,
        clock=lambda: AT,
        id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
        turns=turns,
    )


@pytest.fixture(scope="module")
def correct() -> tuple[RunRecord, Evaluation]:
    run = _run()
    return run, evaluate(run)


def _findings(ev: Evaluation, name: str) -> tuple[str, ...]:
    return ev.checks[name].findings


def test_a_correct_system_passes_every_check_of_t1_to_t3(
    correct: tuple[RunRecord, Evaluation],
) -> None:
    run, ev = correct
    assert run.replay_matches is True
    for t in (1, 2, 3):
        for layer in ("IE2", "IE3"):
            assert ev.checks[f"T{t:02d}-{layer}"].passed, _findings(ev, f"T{t:02d}-{layer}")
    assert ev.checks["SOURCE-COVERAGE"].passed
    assert run.human_authorizations == 3, "the three T1 attempt claims, each AGREEd at T3"


def test_the_correct_run_has_one_stable_fresh_root(correct: tuple[RunRecord, Evaluation]) -> None:
    run, ev = correct
    assert ev.root_id is not None
    by_t = {m["t"]: m for m in ev.metrics}
    assert [by_t[t]["ie3"]["root_count"] for t in (1, 2, 3)] == [1, 1, 1]
    assert by_t[3]["ie3"]["root_stale_bounded"] is False
    assert by_t[3]["ie3"]["root_stale_raw_plane"] is True, "the root cites a corrected claim"
    assert by_t[3]["ie3"]["replacements"] == 1
    assert by_t[2]["ie3"]["route"] == "NO_CHANGE"


def test_the_evaluator_reads_only_the_unfinished_turns_as_not_run(
    correct: tuple[RunRecord, Evaluation],
) -> None:
    _, ev = correct
    assert ev.checks["RUN-INTEGRITY"].passed is False, "a three-turn run is incomplete"
    assert any("INCOMPLETE" in f for f in _findings(ev, "RUN-INTEGRITY"))
    for t in range(4, 17):
        for layer in ("IE2", "IE3"):
            assert _findings(ev, f"T{t:02d}-{layer}") == ("NOT_RUN: no record of this turn",)


def test_every_question_has_a_packet(correct: tuple[RunRecord, Evaluation]) -> None:
    run, _ = correct
    bundle = adjudication_bundle(run)
    by_id = {i["id"]: i for i in bundle["items"]}
    assert len(by_id) == 70
    assert by_id["Q-IE2-T03-TARGET"]["packet"]["claims"]
    assert by_id["Q-IE3-T03-TARGET"]["packet"]["graph_objects"]
    assert by_id["Q-IE2-T02-ACCOUNT"]["packet"]["sentences_to_account"]
    assert by_id["Q-IE2-T09-H-4"]["packet"] == {"unavailable": "T9 NOT_RUN"}


def test_a_missed_supersession_is_caught_at_both_layers() -> None:
    ev = evaluate(_run(skip_supersede_at=3))
    assert any(f.startswith("MISSING_SUPERSEDE") for f in _findings(ev, "T03-IE2"))
    assert ev.first_divergence is not None
    assert (ev.first_divergence["t"], ev.first_divergence["layer"]) == (3, "IE2")
    # IE3 is judged on the claim state it was given: the contradiction is IE2's, upstream.


def test_a_second_root_is_refused_and_caught() -> None:
    ev = evaluate(_run(turns=(1, 2), second_root_at=2))
    assert any(
        f.startswith("IE3_REFUSED") and "MULTIPLE_ROOTS" in f for f in _findings(ev, "T02-IE3")
    )


def test_a_graph_without_a_root_is_caught() -> None:
    ev = evaluate(_run(turns=(1,), no_root=True))
    assert any(f.startswith("ROOT_COUNT") for f in _findings(ev, "T01-IE3")), _findings(
        ev, "T01-IE3"
    )


def test_a_root_staleness_gap_is_caught() -> None:
    ev = evaluate(_run(root_gap_at=3))
    assert any(f.startswith("INCORRECT_GAP") for f in _findings(ev, "T03-IE3"))


@pytest.mark.parametrize(
    ("kwargs", "check", "tags"),
    [
        ({"extra_claim_at": 2}, "T02-IE2", ("CLAIM_COUNT",)),
        ({"create_at": 2}, "T02-IE2", ("OVER_SPLIT", "WRONG_BIND")),
        ({"bad_accounting_at": 2}, "T02-IE2", ("ACCOUNTING_RECOMPUTED",)),
        ({"no_replace_at": 3}, "T03-IE3", ("STALE_RETAINED", "UNCOVERED_CLAIM")),
        ({"dup_at": 2}, "T02-IE3", ("DUPLICATE_OBJECT", "FALSE_NEW")),
    ],
    ids=["duplicate-claim", "over-split", "silent-accounting-loss", "stale-kept", "duplicate-node"],
)
def test_each_broken_law_is_caught_by_its_own_check(
    kwargs: dict[str, Any], check: str, tags: tuple[str, ...]
) -> None:
    turns = (1, 2) if check.startswith("T02") else (1, 2, 3)
    ev = evaluate(_run(turns=turns, **kwargs))
    found = {f.split(":", 1)[0] for f in _findings(ev, check)}
    assert set(tags) <= found, _findings(ev, check)


# --------------------------------------------------------------------------- the full oracle


@pytest.mark.skipif(os.environ.get("LH23_FULL_ORACLE") != "1", reason="about twenty minutes")
def test_a_correct_system_passes_all_sixteen_turns() -> None:
    run = _run(turns=protocol.TURNS)
    ev = evaluate(run)
    failed = {n: c.findings for n, c in ev.checks.items() if not c.passed}
    assert failed == {}
    assert ev.first_divergence is None
