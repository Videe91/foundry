from __future__ import annotations

import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.experiments.longitudinal.expectations import (
    EXPECTATIONS,
    EXPERIMENT_VERSION,
    LOCKED_CEILINGS,
    TRACKED_LOCI,
    DecisionInputs,
    DecisionOutcome,
    Expectation,
    ExpectationManifest,
    ExpectationVerdict,
    TrackedLocus,
    Verdict,
    decision_rule,
    seal,
)

SPEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-09-11-incremental-semantic-assimilation-longitudinal-dogfood-design.md"
)

UNCONDITIONAL_IDS = tuple(f"E{n}" for n in range(1, 12))
ARCHITECT_IDS = ("E1", "E2", "E3", "E4", "E5", "E8", "E9")
DETERMINISTIC_IDS = ("E6", "E7", "E10", "E11", "E12")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any accidental socket use in this module is a test failure, not a slow test."""

    def blocked(*_: Any, **__: Any) -> None:
        raise AssertionError("a longitudinal expectations unit test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield


def test_socket_guard_is_armed() -> None:
    with pytest.raises(AssertionError, match="network connection"):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(AssertionError, match="network connection"):
        socket.socket().connect(("127.0.0.1", 9))


def _timeline_hashes() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "t": f"T{t}",
            "artifact_ref": f"docs/spec.md@{t}",
            "commit": f"{t:040x}",
            "git_blob_sha": f"{t + 100:040x}",
            "content_sha256": f"{t + 200:064x}",
        }
        for t in range(1, 5)
    )


def _config() -> dict[str, Any]:
    return {
        **LOCKED_CEILINGS,
        "model": "grok-4.6",
        "reasoning_effort": "high",
        "policy_version": "9P-policy-v1",
    }


def _manifest(**overrides: Any) -> ExpectationManifest:
    base: dict[str, Any] = {
        "experiment_version": "intent-v2-longitudinal-assimilation-v2",
        "frozen_code_sha": "a" * 40,
        "timeline_hashes": _timeline_hashes(),
        "prompt_sha256": "b" * 64,
        "semantic_output_schema_sha256": "c" * 64,
        "config": _config(),
        "expectations": EXPECTATIONS,
        "tracked_loci": TRACKED_LOCI,
    }
    base.update(overrides)
    return ExpectationManifest(**base)


def _verdict(
    expectation_id: str,
    verdict: Verdict = Verdict.PASS,
) -> ExpectationVerdict:
    expectation = next(e for e in EXPECTATIONS if e.id == expectation_id)
    return ExpectationVerdict(
        id=expectation_id,
        verdict=verdict,
        adjudicator=expectation.adjudicator,
        evidence_refs=("ledger:seq:1",),
    )


def _all_pass(e12: Verdict = Verdict.NOT_APPLICABLE) -> tuple[ExpectationVerdict, ...]:
    return tuple(_verdict(i) for i in UNCONDITIONAL_IDS) + (_verdict("E12", e12),)


def _inputs(
    verdicts: tuple[ExpectationVerdict, ...],
    *,
    f_tokens: int = 1_000,
    r_tokens: int = 2_000,
    f_errors: int = 0,
    r_errors: int = 0,
    declined_any: bool = False,
) -> DecisionInputs:
    return DecisionInputs(
        verdicts=verdicts,
        f_input_tokens_t2_t4=f_tokens,
        r_input_tokens_t2_t4=r_tokens,
        f_material_errors=f_errors,
        r_material_errors=r_errors,
        declined_any=declined_any,
    )


def test_experiment_identity_is_v2_and_the_manifest_carries_the_output_schema_hash() -> None:
    assert EXPERIMENT_VERSION == "intent-v2-longitudinal-assimilation-v2"
    manifest = _manifest()
    assert manifest.experiment_version == "intent-v2-longitudinal-assimilation-v2"
    assert manifest.semantic_output_schema_sha256 == "c" * 64
    # The v1 identity is not accepted: a v2 seal can never be mistaken for a v1 one.
    with pytest.raises(ValidationError):
        _manifest(experiment_version="intent-v2-longitudinal-assimilation-v1")
    # The output-schema hash is part of the pre-run contract, never optional.
    without = {
        "experiment_version": EXPERIMENT_VERSION,
        "frozen_code_sha": "a" * 40,
        "timeline_hashes": _timeline_hashes(),
        "prompt_sha256": "b" * 64,
        "config": _config(),
        "expectations": EXPECTATIONS,
        "tracked_loci": TRACKED_LOCI,
    }
    with pytest.raises(ValidationError, match="semantic_output_schema_sha256"):
        ExpectationManifest(**without)


def test_manifest_holds_e1_to_e11_unconditional_and_e12_conditional() -> None:
    ids = tuple(e.id for e in EXPECTATIONS)
    assert ids == UNCONDITIONAL_IDS + ("E12",)
    assert len(set(ids)) == 12
    for expectation in EXPECTATIONS:
        assert isinstance(expectation, Expectation)
        assert expectation.conditional is (expectation.id == "E12")
        assert expectation.text.strip() == expectation.text
        assert expectation.text
    by_id = {e.id: e for e in EXPECTATIONS}
    for eid in ARCHITECT_IDS:
        assert by_id[eid].adjudicator == "architect"
    for eid in DETERMINISTIC_IDS:
        assert by_id[eid].adjudicator == "deterministic"
    assert set(ARCHITECT_IDS) | set(DETERMINISTIC_IDS) == set(ids)
    assert tuple(by_id[i].t for i in ("E1", "E2", "E8", "E9", "E10", "E11", "E12")) == (
        "T1",
        "T2",
        "T3",
        "T4",
        "all",
        "end",
        "any",
    )
    assert tuple(locus.key for locus in TRACKED_LOCI) == ("A", "B", "C")
    assert all(isinstance(locus, TrackedLocus) for locus in TRACKED_LOCI)
    assert tuple(locus.t_introduced for locus in TRACKED_LOCI) == (1, 1, 3)
    # Spec §29 parentheticals exactly: no before/after readings ("no wording").
    assert tuple(locus.description for locus in TRACKED_LOCI) == (
        "referential status of admitted bindings",
        "validation framing",
        "identity of `Provenance.source_event_ids`",
    )
    manifest = _manifest()
    assert manifest.expectations == EXPECTATIONS
    assert manifest.tracked_loci == TRACKED_LOCI
    assert manifest.t1_locus_designation is None


def test_not_applicable_is_rejected_for_e1_to_e11_and_accepted_for_e12() -> None:
    for eid in UNCONDITIONAL_IDS:
        with pytest.raises(ValidationError):
            _verdict(eid, Verdict.NOT_APPLICABLE)
        assert _verdict(eid, Verdict.PASS).verdict is Verdict.PASS
        assert _verdict(eid, Verdict.FAIL).verdict is Verdict.FAIL
    e12 = _verdict("E12", Verdict.NOT_APPLICABLE)
    assert e12.verdict is Verdict.NOT_APPLICABLE
    assert e12.note == ""


def test_unknown_expectation_id_rejected() -> None:
    for bad in ("E13", "E0", "e1", "X1", ""):
        with pytest.raises(ValidationError):
            ExpectationVerdict(
                id=bad,
                verdict=Verdict.PASS,
                adjudicator="deterministic",
                evidence_refs=(),
            )


def test_decision_rule_gates_e12_only_when_a_decline_occurred() -> None:
    # Case 1: no decline, E12 NOT_APPLICABLE -> PASS.
    outcome = decision_rule(_inputs(_all_pass(Verdict.NOT_APPLICABLE), declined_any=False))
    assert isinstance(outcome, DecisionOutcome)
    assert outcome.result == "PASS"
    assert outcome.failing == ()

    # Case 2: decline occurred, E12 FAIL -> FAIL naming E12.
    outcome = decision_rule(_inputs(_all_pass(Verdict.FAIL), declined_any=True))
    assert outcome.result == "FAIL"
    assert outcome.failing == ("E12",)

    # Case 3: decline occurred, E12 NOT_APPLICABLE -> rejected at construction (precondition
    # arose, so NOT_APPLICABLE is not a truthful record); decision_rule never sees it.
    with pytest.raises(ValidationError, match="E12"):
        _inputs(_all_pass(Verdict.NOT_APPLICABLE), declined_any=True)

    # Decline occurred and E12 PASS -> PASS.
    outcome = decision_rule(_inputs(_all_pass(Verdict.PASS), declined_any=True))
    assert outcome.result == "PASS"


def test_decision_inputs_reject_e12_verdict_inconsistent_with_decline_flag() -> None:
    # No decline: E12 must be NOT_APPLICABLE; PASS or FAIL is an inconsistent record.
    for verdict in (Verdict.PASS, Verdict.FAIL):
        with pytest.raises(ValidationError, match="E12"):
            _inputs(_all_pass(verdict), declined_any=False)
    # Decline occurred: E12 must be PASS or FAIL; NOT_APPLICABLE is inconsistent.
    with pytest.raises(ValidationError, match="E12"):
        _inputs(_all_pass(Verdict.NOT_APPLICABLE), declined_any=True)
    # Consistent combinations construct.
    assert _inputs(_all_pass(Verdict.NOT_APPLICABLE), declined_any=False).declined_any is False
    assert _inputs(_all_pass(Verdict.PASS), declined_any=True).declined_any is True
    assert _inputs(_all_pass(Verdict.FAIL), declined_any=True).declined_any is True


def test_decision_rule_token_and_error_conditions() -> None:
    verdicts = _all_pass()
    assert decision_rule(_inputs(verdicts, f_tokens=999, r_tokens=1000)).result == "PASS"

    equal_tokens = decision_rule(_inputs(verdicts, f_tokens=1000, r_tokens=1000))
    assert equal_tokens.result == "FAIL"
    assert equal_tokens.failing == ("TOKENS:F>=R",)

    more_tokens = decision_rule(_inputs(verdicts, f_tokens=1001, r_tokens=1000))
    assert more_tokens.result == "FAIL"
    assert more_tokens.failing == ("TOKENS:F>=R",)

    equal_errors = decision_rule(_inputs(verdicts, f_errors=2, r_errors=2))
    assert equal_errors.result == "PASS"

    more_errors = decision_rule(_inputs(verdicts, f_errors=3, r_errors=2))
    assert more_errors.result == "FAIL"
    assert more_errors.failing == ("ERRORS:F>R",)

    failing_e5 = tuple(_verdict(v.id, Verdict.FAIL) if v.id == "E5" else v for v in verdicts)
    combined = decision_rule(_inputs(failing_e5, f_tokens=5, r_tokens=5, f_errors=1, r_errors=0))
    assert combined.result == "FAIL"
    assert combined.failing == ("E5", "TOKENS:F>=R", "ERRORS:F>R")


def test_unadjudicated_unconditional_expectation_fails() -> None:
    missing_e7 = tuple(v for v in _all_pass() if v.id != "E7")
    outcome = decision_rule(_inputs(missing_e7))
    assert outcome.result == "FAIL"
    assert outcome.failing == ("UNADJUDICATED:E7",)

    # A missing E12 with no decline is not a failure.
    missing_e12 = tuple(v for v in _all_pass() if v.id != "E12")
    assert decision_rule(_inputs(missing_e12, declined_any=False)).result == "PASS"

    # A missing E12 with a decline is a failure.
    outcome = decision_rule(_inputs(missing_e12, declined_any=True))
    assert outcome.result == "FAIL"
    assert outcome.failing == ("UNADJUDICATED:E12",)

    # Duplicate verdicts for one id are rejected.
    with pytest.raises(ValidationError):
        _inputs(_all_pass() + (_verdict("E1"),))


def test_seal_is_deterministic_and_ignores_designation_but_changes_on_any_other_edit() -> None:
    manifest = _manifest()
    digest = seal(manifest)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert seal(_manifest()) == digest

    designated = manifest.model_copy(
        update={
            "t1_locus_designation": {
                "a_root_address_id": "ADDR-00000001",
                "control_root_address_id": "ADDR-00000002",
                "ledger_sequence": 42,
                "designated_at": "2026-09-11T00:00:00+00:00",
            }
        }
    )
    assert seal(designated) == digest

    assert seal(_manifest(frozen_code_sha="c" * 40)) != digest
    assert seal(_manifest(prompt_sha256="d" * 64)) != digest
    assert seal(_manifest(semantic_output_schema_sha256="f" * 64)) != digest
    assert seal(_manifest(config={**_config(), "model": "other"})) != digest
    hashes = list(_timeline_hashes())
    hashes[0] = {**hashes[0], "content_sha256": "e" * 64}
    assert seal(_manifest(timeline_hashes=tuple(hashes))) != digest
    edited = tuple(
        e.model_copy(update={"text": e.text + " x"}) if e.id == "E4" else e for e in EXPECTATIONS
    )
    assert seal(_manifest(expectations=edited)) != digest
    loci = tuple(
        locus.model_copy(update={"description": locus.description + " x"})
        if locus.key == "B"
        else locus
        for locus in TRACKED_LOCI
    )
    assert seal(_manifest(tracked_loci=loci)) != digest


def test_manifest_rejects_malformed_fields() -> None:
    with pytest.raises(ValidationError):
        _manifest(frozen_code_sha="abc")
    with pytest.raises(ValidationError):
        _manifest(prompt_sha256="abc")
    with pytest.raises(ValidationError):
        _manifest(semantic_output_schema_sha256="abc")
    with pytest.raises(ValidationError):
        _manifest(experiment_version="something-else")
    with pytest.raises(ValidationError):
        _manifest(timeline_hashes=({"t": "T1"},))
    with pytest.raises(ValidationError):
        _manifest(config={**_config(), "max_frontier_calls": 17})
    with pytest.raises(ValidationError):
        _manifest(config={k: v for k, v in _config().items() if k != "model"})
    with pytest.raises(ValidationError):
        TrackedLocus(key="D", description="x", t_introduced=1)


def test_manifest_contains_no_future_runtime_ids() -> None:
    pattern = re.compile(r"ADDR-|CLAIM-|JDG-|INV-")
    for expectation in EXPECTATIONS:
        assert not pattern.search(expectation.text), expectation.id
    for locus in TRACKED_LOCI:
        assert not pattern.search(locus.description), locus.key


def test_expectation_texts_match_spec() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")
    for expectation in EXPECTATIONS:
        assert expectation.text in spec, expectation.id
        row = f"| {expectation.text} | {expectation.t} |"
        assert row in spec, expectation.id
