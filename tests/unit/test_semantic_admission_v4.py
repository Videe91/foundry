"""Semantic admission verifier v4: completeness AND consistency with current truth. Offline.

The writer may miss a contradiction. The independent verifier is the backstop: for every
proposition it answers ``completeness`` (COMPLETE / NOT_COMPLETE) and ``consistency``
(NO_CONFLICT / CONFLICT / UNCERTAIN), naming for a CONFLICT the current claims it conflicts
with -- only claims it was shown, which are the current claims at the concerns the response
touches. Deterministic code checks ids, cardinality and currency; it never reads meaning or the
note. Only COMPLETE + NO_CONFLICT proceeds; NOT_COMPLETE, CONFLICT and UNCERTAIN are held by the
existing runtime-hold machinery; an invalid answer holds the whole response.
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.adapters.semantics.completeness_verifier import (
    ADMISSION_SYSTEM_INSTRUCTION,
    ADMISSION_SYSTEM_INSTRUCTION_SHA256,
    ADMISSION_V4_CONTRACT,
    COMPLETENESS_V3_CONTRACT,
    ModelRuntimeAdmissionVerifier,
)
from foundry.application.authority_routing import list_authority_work
from foundry.application.replay import replay
from foundry.domain.gaps import GapKind, GapStatus
from foundry.domain.semantic_completeness import (
    ADMISSION_REPORT_FORMAT,
    SEMANTIC_ADMISSION_POLICY_VERSION_V4,
    AdmissionReport,
    AdmissionRequest,
    AdmissionVerdict,
    CompletenessRequest,
    VerifierIdentity,
)
from foundry.domain.semantic_holds import SemanticHoldGap
from foundry.model_runtime.domain import CertifiedContract, ModelTask, output_schema_sha256
from foundry.ports.semantic_completeness import VerifierUnavailable
from tests.unit._completeness_fixtures import ScriptedVerifier
from tests.unit.test_runtime_holds import PROJECT, World, _a, _spec
from tests.unit.test_semantic_completeness_v3 import _runtime
from tests.unit.test_semantic_completeness_v3_pipeline import V3, verdicts

V4 = VerifierIdentity(
    provider="openai", model="gpt-6-astra", policy_version=SEMANTIC_ADMISSION_POLICY_VERSION_V4
)
SCV = ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION

R14 = "Refund requests are accepted within 14 days of delivery."
R30 = "Refund requests are accepted within 30 days of delivery."
RECEIPT = "A refund requires the original receipt."


class AdmissionVerifier(ScriptedVerifier):
    """A scripted v4 verifier. It asks for the consistency context like the runtime adapter."""

    checks_consistency = True

    def __init__(self, answer: Callable[[Any], Any], identity: VerifierIdentity = V4) -> None:
        super().__init__(answer, identity)


def admission(
    *,
    not_complete: frozenset[str] = frozenset(),
    conflicts: Mapping[str, tuple[str, ...]] | None = None,
    uncertain: frozenset[str] = frozenset(),
    raw_ids: Mapping[str, tuple[str, ...]] | None = None,
    note: str | None = None,
) -> AdmissionVerifier:
    """``conflicts`` names current claims by predicate (the script's way of pointing at what it
    was shown); ``raw_ids`` names claim ids verbatim (to test invalid references)."""

    def answer(request: AdmissionRequest) -> AdmissionReport:
        shown = {c.predicate: c.claim_id for c in request.current_claims}
        out = []
        for p in request.propositions:
            pid = p.proposition_id
            ids = tuple(shown[x] for x in (conflicts or {}).get(pid, ())) + (raw_ids or {}).get(
                pid, ()
            )
            out.append(
                AdmissionVerdict(
                    proposition_id=pid,
                    completeness="NOT_COMPLETE" if pid in not_complete else "COMPLETE",
                    consistency="CONFLICT"
                    if ids
                    else ("UNCERTAIN" if pid in uncertain else "NO_CONFLICT"),
                    conflicting_claim_ids=ids,
                    note=note,
                )
            )
        return AdmissionReport(report_format=ADMISSION_REPORT_FORMAT, verdicts=tuple(out))

    return AdmissionVerifier(answer)


def _refunds() -> World:
    w = World()
    w.send("REF-1", "Refunds", _spec("Refunds", R14),
           (_a("p1", (1,), ("ASSERT", "refund_window", "14 days")),),
           verifier=admission())  # fmt: skip
    return w


def _missed(w: World, verifier: Any) -> Any:
    """The new source: 30 days, plus an unrelated receipt rule. The writer declares nothing."""
    return w.send("REF-2", "Refunds", _spec("Refunds", R30, RECEIPT), (
        _a("p1", (1,), ("ASSERT", "refund_window_new", "30 days")),
        _a("p2", (2,), ("ASSERT", "receipt_required", "original receipt")),
    ), verifier=verifier)  # fmt: skip


# --- the contract ------------------------------------------------------------------------------


def test_v4_is_a_new_admission_contract_and_v3_is_unchanged() -> None:
    assert SEMANTIC_ADMISSION_POLICY_VERSION_V4 == "ie2-semantic-admission-v4"
    assert ADMISSION_REPORT_FORMAT == "ie2-semantic-admission-report.v4"
    assert ADMISSION_V4_CONTRACT.policy_version == SEMANTIC_ADMISSION_POLICY_VERSION_V4
    assert ADMISSION_V4_CONTRACT != COMPLETENESS_V3_CONTRACT
    digest = hashlib.sha256(ADMISSION_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert digest == ADMISSION_SYSTEM_INSTRUCTION_SHA256 == ADMISSION_V4_CONTRACT.instruction_sha256
    assert ADMISSION_V4_CONTRACT.output_schema_sha256 == output_schema_sha256(AdmissionReport)
    assert COMPLETENESS_V3_CONTRACT.instruction_sha256 == (
        "b92e41fba225def0138c9230ce8d90372f5a4291ff77405d305114fdb4b52c19"
    )
    text = " ".join(ADMISSION_SYSTEM_INSTRUCTION.split())
    for phrase in ("current_claims", "NO_CONFLICT", "CONFLICT", "UNCERTAIN",
                   "conflicting_claim_ids", "never read", "When you are unsure"):  # fmt: skip
        assert phrase in text, phrase


def test_the_verdict_shape_ties_conflict_to_named_claims() -> None:
    AdmissionVerdict(proposition_id="p", completeness="COMPLETE", consistency="NO_CONFLICT")
    AdmissionVerdict(proposition_id="p", completeness="COMPLETE", consistency="UNCERTAIN")
    AdmissionVerdict(proposition_id="p", completeness="NOT_COMPLETE", consistency="CONFLICT",
                     conflicting_claim_ids=("C-1",))  # fmt: skip
    for bad in (
        {"consistency": "CONFLICT", "conflicting_claim_ids": ()},
        {"consistency": "NO_CONFLICT", "conflicting_claim_ids": ("C-1",)},
        {"consistency": "UNCERTAIN", "conflicting_claim_ids": ("C-1",)},
        {"consistency": "MAYBE"},
        {"consistency": "CONFLICT", "conflicting_claim_ids": ("C-1", "C-1")},
    ):
        with pytest.raises(ValidationError):
            AdmissionVerdict(proposition_id="p", completeness="COMPLETE", **bad)


def test_the_adapter_binds_v4_and_a_v3_only_model_is_never_asked() -> None:
    runtime, provider = _runtime(
        {}, (CertifiedContract(task=SCV, contract=COMPLETENESS_V3_CONTRACT),)
    )
    request = AdmissionRequest(
        project_id="P", subject_invocation_id="I",
        propositions=_refunds_request().propositions, current_claims=(),
    )  # fmt: skip
    with pytest.raises(VerifierUnavailable):
        ModelRuntimeAdmissionVerifier(runtime=runtime, run_id="R").verify(request)
    assert provider.calls == 0
    assert ModelRuntimeAdmissionVerifier.checks_consistency is True
    report = AdmissionReport(report_format=ADMISSION_REPORT_FORMAT, verdicts=())
    runtime, provider = _runtime(
        report.model_dump(mode="json"),
        (CertifiedContract(task=SCV, contract=ADMISSION_V4_CONTRACT),),
    )
    result = ModelRuntimeAdmissionVerifier(runtime=runtime, run_id="R").verify(request)
    (call,) = provider.requests
    assert call.request.contract == ADMISSION_V4_CONTRACT and call.output_type is AdmissionReport
    assert json.loads(call.request.messages[1].content) == request.model_dump(mode="json")
    assert result.verifier.policy_version == SEMANTIC_ADMISSION_POLICY_VERSION_V4


def _refunds_request() -> CompletenessRequest:
    w = _refunds()
    probe = admission()
    _missed(w, probe)
    (request,) = probe.requests
    return request


# --- the bounded context ----------------------------------------------------------------------


def test_the_verifier_sees_only_current_claims_at_the_concerns_the_response_touches() -> None:
    w = _refunds()
    w.send("DEP-1", "Deposits", _spec("Deposits", "Power tools require a deposit of 50 EUR."),
           (_a("p1", (1,), ("ASSERT", "deposit", "50 EUR")),), verifier=admission())  # fmt: skip
    probe = admission()
    _missed(w, probe)
    (request,) = probe.requests
    assert isinstance(request, AdmissionRequest)
    assert [c.predicate for c in request.current_claims] == ["refund_window"], "not Deposits"
    assert request.current_claims[0].claim_id == w.claim_id("refund_window")


def test_a_claim_the_response_itself_retires_is_not_shown_as_current() -> None:
    w = _refunds()
    probe = admission()
    w.send("REF-2", "Refunds", _spec("Refunds", R30),
           (_a("p1", (1,), ("ASSERT", "refund_window_new", "30 days"),
               ("SUPERSEDE", "refund_window")),), verifier=probe, sup="REF-1")  # fmt: skip
    (request,) = probe.requests
    assert isinstance(request, AdmissionRequest) and request.current_claims == ()


# --- the backstop -----------------------------------------------------------------------------


def test_a_missed_writer_conflict_is_caught_and_held_and_the_rest_applies() -> None:
    w = _refunds()
    _missed(w, admission(conflicts={"p1": ("refund_window",)}))
    current = w.current()
    assert current["refund_window"] == "14 days", "the current truth stays current"
    assert "refund_window_new" not in current, "the 30-day proposal does not become current"
    assert current["receipt_required"] == "original receipt", "unrelated safe work continues"
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "CONFLICT" and gap.kind is GapKind.CONTRADICTION and gap.blocking
    assert gap.conflicting_claim_ids == (w.claim_id("refund_window"),)
    assert gap.held_proposition_ids == ("p1",)
    queue = list_authority_work(w.governor)
    assert queue.items == () and queue.correction_sets == ()


def test_writer_and_verifier_both_detecting_make_one_gap() -> None:
    w = _refunds()
    w.send("REF-2", "Refunds", _spec("Refunds", R30), (
        _a("p1", (1,), ("ASSERT", "refund_window_new", "30 days"),
           ("CONFLICT_CLAIM", "refund_window")),
    ), verifier=admission(conflicts={"p1": ("refund_window",)}))  # fmt: skip
    (gap,) = w.holds()
    assert gap.cause == "CONFLICT" and gap.conflicting_claim_ids == (w.claim_id("refund_window"),)


def test_no_conflict_continues_normally() -> None:
    w = _refunds()
    _missed(w, admission())
    assert w.current()["refund_window_new"] == "30 days"
    assert w.holds() == []


@pytest.mark.parametrize("note", [None, "", "looks contradictory", "definitely compatible"])
def test_uncertain_is_held_and_never_applied_whatever_the_note(note: str | None) -> None:
    w = _refunds()
    _missed(w, admission(uncertain=frozenset({"p1"}), note=note))
    assert "refund_window_new" not in w.current()
    assert w.current()["receipt_required"] == "original receipt"
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "UNCERTAIN" and gap.kind is GapKind.AMBIGUITY and gap.blocking
    assert gap.affected_object_ids == (w.address("Refunds"),)


def test_not_complete_still_routes_to_a_completeness_hold() -> None:
    w = _refunds()
    _missed(w, admission(not_complete=frozenset({"p2"})))
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "NOT_COMPLETE" and gap.held_proposition_ids == ("p2",)


@pytest.mark.parametrize("case", ["unknown", "not-current", "other-concern"])
def test_an_invalid_conflict_reference_holds_the_whole_response(case: str) -> None:
    w = _refunds()
    w.send("DEP-1", "Deposits", _spec("Deposits", "Power tools require a deposit of 50 EUR."),
           (_a("p1", (1,), ("ASSERT", "deposit", "50 EUR")),), verifier=admission())  # fmt: skip
    w.send("REF-0", "Refunds", _spec("Refunds", "Old rule."), (
        _a("p1", (1,), ("ASSERT", "old_rule", "old"),),), verifier=admission())  # fmt: skip
    w.send("REF-0b", "Refunds", _spec("Refunds", "New rule."), (
        _a("p1", (1,), ("ASSERT", "new_rule", "new"), ("SUPERSEDE", "old_rule")),),
        verifier=admission(), sup="REF-0")  # fmt: skip
    w.agree("Refunds")
    named = {
        "unknown": "CLAIM-ghost",
        "not-current": w.claim_id("old_rule"),
        "other-concern": w.claim_id("deposit"),
    }[case]
    before = dict(w.current())
    _missed(w, admission(raw_ids={"p1": (named,)}))
    assert w.current() == before, "nothing of the response applies"
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFIER_OUTPUT_INVALID" and gap.held_proposition_ids == ("p1", "p2")


def test_a_conflicting_member_holds_the_whole_correction_set() -> None:
    w = _refunds()
    w.send("REF-R", "Refunds", _spec("Refunds", RECEIPT),
           (_a("p1", (1,), ("ASSERT", "receipt_required", "original receipt")),),
           verifier=admission())  # fmt: skip
    w.send("REF-2", "Refunds", _spec("Refunds", R30, "A refund requires no receipt."), (
        _a("p1", (1,), ("ASSERT", "refund_window_new", "30 days"), ("SUPERSEDE", "refund_window")),
        _a("p2", (2,), ("ASSERT", "no_receipt", "no receipt")),
    ), verifier=admission(conflicts={"p2": ("receipt_required",)}), sup="REF-1")  # fmt: skip
    assert w.current() == {"refund_window": "14 days", "receipt_required": "original receipt"}
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "CONFLICT" and gap.held_proposition_ids == ("p1", "p2")
    assert w.governor.state().semantic.correction_sets == {}


def test_a_verifier_detected_conflict_resolves_by_the_same_lawful_change() -> None:
    w = _refunds()
    _missed(w, admission(conflicts={"p1": ("refund_window",)}))
    (gap,) = w.holds(GapStatus.OPEN)
    w.send("REF-3", "Refunds", _spec("Refunds", R30), (
        _a("p1", (1,), ("ASSERT", "refund_window_v2", "30 days"), ("SUPERSEDE", "refund_window")),
    ), verifier=admission(), sup="REF-1")  # fmt: skip
    assert [g.id for g in w.holds(GapStatus.OPEN)] == [gap.id], "pending until agreed"
    w.agree("Refunds")
    assert w.current()["refund_window_v2"] == "30 days"
    (resolved,) = [g for g in w.holds() if g.id == gap.id]
    assert resolved.status is GapStatus.RESOLVED


def test_an_uncertain_hold_resolves_when_the_same_work_is_later_verified_clean() -> None:
    w = _refunds()
    _missed(w, admission(uncertain=frozenset({"p1"})))
    (gap,) = w.holds(GapStatus.OPEN)
    w.send("REF-2b", "Refunds", _spec("Refunds", R30, RECEIPT), (
        _a("p1", (1,), ("ASSERT", "refund_window_new", "30 days")),
        _a("p2", (2,), ("SUPPORT", "receipt_required")),
    ), verifier=admission(), sup="REF-2")  # fmt: skip
    (resolved,) = [g for g in w.holds() if g.id == gap.id]
    assert resolved.status is GapStatus.RESOLVED
    assert w.current()["refund_window_new"] == "30 days"


def test_replay_never_calls_the_verifier_and_reconstructs_the_same_state() -> None:
    w = _refunds()
    verifier = admission(conflicts={"p1": ("refund_window",)})
    _missed(w, verifier)
    calls = len(verifier.requests)
    events = list(w.store.load(PROJECT))
    assert replay(PROJECT, events) == w.governor.state()
    assert len(verifier.requests) == calls == 1
    (record,) = [
        r for r in w.governor.state().semantic.completeness_records.values()
        if r.verifier.policy_version == SEMANTIC_ADMISSION_POLICY_VERSION_V4 and r.outcome == "FAIL"
    ]  # fmt: skip
    assert isinstance(record.request, AdmissionRequest) and isinstance(
        record.report, AdmissionReport
    )
    assert record.failure_codes == ("SEMANTIC_CONFLICT",)


def test_an_unavailable_verifier_is_never_uncertain() -> None:
    class Unavailable(AdmissionVerifier):
        def verify(self, request: Any) -> Any:
            raise VerifierUnavailable("no model holds the v4 contract")

    w = _refunds()
    _missed(w, Unavailable(lambda r: None))
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFICATION_UNAVAILABLE" and gap.kind is GapKind.CONTEXT_FAILURE
    assert "refund_window_new" not in w.current() and "receipt_required" not in w.current()


def test_a_v3_answer_to_a_consistency_request_is_invalid() -> None:
    w = _refunds()
    _missed(w, AdmissionVerifier(verdicts(), V3))
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFIER_OUTPUT_INVALID"
    assert "refund_window_new" not in w.current()


def test_a_v4_report_on_a_plain_request_is_invalid() -> None:
    w = _refunds()
    report = AdmissionReport(
        report_format=ADMISSION_REPORT_FORMAT,
        verdicts=(
            AdmissionVerdict(
                proposition_id="p1", completeness="COMPLETE", consistency="NO_CONFLICT"
            ),
            AdmissionVerdict(
                proposition_id="p2", completeness="COMPLETE", consistency="NO_CONFLICT"
            ),
        ),
    )
    _missed(w, ScriptedVerifier(lambda r: report, V4))  # type: ignore[arg-type,return-value]
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFIER_OUTPUT_INVALID"
    assert "refund_window_new" not in w.current()


def test_every_hold_is_a_runtime_hold_gap() -> None:
    w = _refunds()
    _missed(w, admission(conflicts={"p1": ("refund_window",)}, uncertain=frozenset({"p2"})))
    holds = w.holds(GapStatus.OPEN)
    assert {g.cause for g in holds} == {"CONFLICT", "UNCERTAIN"}
    assert all(isinstance(g, SemanticHoldGap) for g in holds)
    assert w.current() == {"refund_window": "14 days"}
