"""Semantic admission v5: the independent verifier judges every proposed REPLACEMENT. Offline.

A writer may label competing evidence a correction (ASSERT plus SUPERSEDE). A claim the response
retires is rightly kept out of ordinary consistency checking (a correction always differs from
what it corrects), so v4 could not see the problem. v5 shows each proposed supersession target
separately, and the verifier answers, per target: SUPPORTED_REPLACEMENT (the evidence presents
itself as changing that rule), CONFLICTING_EVIDENCE (a competing rule, not an amendment) or
UNCERTAIN. Deterministic code checks only that every supplied target is judged once and nothing
else is named. CONFLICTING_EVIDENCE converges on the existing contradiction hold, UNCERTAIN on
the existing unresolved hold; SUPPORTED_REPLACEMENT continues to ordinary correction authority.
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from foundry.adapters.semantics.completeness_verifier import (
    ADMISSION_V4_CONTRACT,
    ADMISSION_V5_CONTRACT,
    ADMISSION_V5_SYSTEM_INSTRUCTION,
    ADMISSION_V5_SYSTEM_INSTRUCTION_SHA256,
    ModelRuntimeAdmissionVerifier,
    ModelRuntimeAdmissionVerifierV5,
)
from foundry.application.authority_routing import list_authority_work
from foundry.application.replay import replay
from foundry.domain.gaps import GapKind, GapStatus
from foundry.domain.semantic_completeness import (
    ADMISSION_REPORT_FORMAT_V5,
    SEMANTIC_ADMISSION_POLICY_VERSION_V5,
    AdmissionReportV5,
    AdmissionRequestV5,
    AdmissionVerdictV5,
    ReplacementVerdict,
    VerifierIdentity,
)
from foundry.model_runtime.domain import CertifiedContract, ModelTask, output_schema_sha256
from foundry.ports.semantic_completeness import VerifierUnavailable
from tests.unit._completeness_fixtures import ScriptedVerifier
from tests.unit.test_runtime_holds import PROJECT, World, _a, _spec
from tests.unit.test_semantic_admission_v4 import admission
from tests.unit.test_semantic_completeness_v3 import _runtime

V5 = VerifierIdentity(
    provider="openai", model="gpt-6-astra", policy_version=SEMANTIC_ADMISSION_POLICY_VERSION_V5
)
SCV = ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION

HOLD_2 = "A reserved tool is held for 2 days after it becomes available."
HOLD_3 = "A reserved tool is held for 3 days after it becomes available."
R30 = "Refund requests are accepted within 30 days of delivery."
R14 = "The refund request window is changed from 30 days to 14 days."


class AdmissionVerifierV5(ScriptedVerifier):
    checks_consistency = True
    checks_replacement = True

    def __init__(self, answer: Any) -> None:
        super().__init__(answer, V5)


def admission5(
    *,
    replacement: Mapping[str, str] | None = None,
    raw: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
    note: str | None = None,
) -> AdmissionVerifierV5:
    """``replacement`` gives a judgement per proposition (default SUPPORTED_REPLACEMENT) for
    every target it was shown; ``raw`` replaces a proposition's judgements verbatim."""

    def answer(request: AdmissionRequestV5) -> AdmissionReportV5:
        out = []
        for p in request.propositions:
            pid = p.proposition_id
            shown = [t.claim_id for t in request.replacement_targets if t.proposition_id == pid]
            judged = (raw or {}).get(pid) or tuple(
                (cid, (replacement or {}).get(pid, "SUPPORTED_REPLACEMENT")) for cid in shown
            )
            out.append(
                AdmissionVerdictV5(
                    proposition_id=pid,
                    completeness="COMPLETE",
                    consistency="NO_CONFLICT",
                    replacements=tuple(
                        ReplacementVerdict(claim_id=c, judgement=j)  # type: ignore[arg-type]
                        for c, j in judged
                    ),
                    note=note,
                )
            )
        return AdmissionReportV5(report_format=ADMISSION_REPORT_FORMAT_V5, verdicts=tuple(out))

    return AdmissionVerifierV5(answer)


def _reservations() -> World:
    w = World()
    w.send("RES-1", "Reservations", _spec("Reservations", HOLD_2),
           (_a("p1", (1,), ("ASSERT", "hold", "2 days")),), verifier=admission5())  # fmt: skip
    return w


def _handbook(w: World, verifier: Any, *extra: Any) -> None:
    """The live T07 shape: an independent source, written as a correction, no conflict."""
    w.send("RES-HB", "Reservations", _spec("Reservations", HOLD_3), (
        _a("p1", (1,), ("ASSERT", "hold_hb", "3 days"), ("SUPERSEDE", "hold"), *extra),
    ), verifier=verifier)  # fmt: skip


def _refunds() -> World:
    w = World()
    w.send("REF-1", "Refunds", _spec("Refunds", R30),
           (_a("p1", (1,), ("ASSERT", "refund_window", "30 days")),),
           verifier=admission5())  # fmt: skip
    return w


# --- the contract ------------------------------------------------------------------------------


def test_v5_is_a_new_contract_and_v4_is_unchanged() -> None:
    assert SEMANTIC_ADMISSION_POLICY_VERSION_V5 == "ie2-semantic-admission-v5"
    assert ADMISSION_REPORT_FORMAT_V5 == "ie2-semantic-admission-report.v5"
    assert ADMISSION_V5_CONTRACT.policy_version == SEMANTIC_ADMISSION_POLICY_VERSION_V5
    assert ADMISSION_V5_CONTRACT != ADMISSION_V4_CONTRACT
    assert ADMISSION_V4_CONTRACT.instruction_sha256 == (
        "42a58b9a5fc25f0a0642526de612dab59c4fdd75203de54eb4e46c9a34fd43cd"
    )
    digest = hashlib.sha256(ADMISSION_V5_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert (
        digest == ADMISSION_V5_SYSTEM_INSTRUCTION_SHA256 == ADMISSION_V5_CONTRACT.instruction_sha256
    )
    assert ADMISSION_V5_CONTRACT.output_schema_sha256 == output_schema_sha256(AdmissionReportV5)
    assert ModelRuntimeAdmissionVerifierV5.checks_replacement is True
    assert getattr(ModelRuntimeAdmissionVerifier, "checks_replacement", False) is False
    text = " ".join(ADMISSION_V5_SYSTEM_INSTRUCTION.split())
    for phrase in ("replacement_targets", "SUPPORTED_REPLACEMENT", "CONFLICTING_EVIDENCE",
                   "UNCERTAIN", "never read"):  # fmt: skip
        assert phrase in text, phrase


def test_the_replacement_verdict_shape() -> None:
    ReplacementVerdict(claim_id="C", judgement="CONFLICTING_EVIDENCE")
    with pytest.raises(ValidationError):
        ReplacementVerdict(claim_id="C", judgement="CORRECTION")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        AdmissionVerdictV5(
            proposition_id="p", completeness="COMPLETE", consistency="NO_CONFLICT",
            replacements=(ReplacementVerdict(claim_id="C", judgement="UNCERTAIN"),
                          ReplacementVerdict(claim_id="C", judgement="UNCERTAIN")),
        )  # fmt: skip


def test_the_v5_adapter_binds_v5_and_a_v4_only_model_is_never_asked() -> None:
    w = _refunds()
    probe = admission5()
    w.send("REF-2", "Refunds", _spec("Refunds", R14), (
        _a("p1", (1,), ("ASSERT", "refund_window_v2", "14 days"), ("SUPERSEDE", "refund_window")),
    ), verifier=probe, sup="REF-1")  # fmt: skip
    (request,) = probe.requests[-1:]
    runtime, provider = _runtime({}, (CertifiedContract(task=SCV, contract=ADMISSION_V4_CONTRACT),))
    with pytest.raises(VerifierUnavailable):
        ModelRuntimeAdmissionVerifierV5(runtime=runtime, run_id="R").verify(request)
    assert provider.calls == 0


# --- the context -------------------------------------------------------------------------------


def test_replacement_targets_are_shown_separately_from_ordinary_consistency() -> None:
    w = _reservations()
    probe = admission5(replacement={"p1": "CONFLICTING_EVIDENCE"})
    _handbook(w, probe)
    (request,) = probe.requests[-1:]
    assert isinstance(request, AdmissionRequestV5)
    assert [(t.proposition_id, t.claim_id) for t in request.replacement_targets] == [
        ("p1", w.claim_id("hold"))
    ]
    assert request.current_claims == (), "the retired claim is not an ordinary conflict target"


# --- the hole, closed --------------------------------------------------------------------------


def test_competing_evidence_mislabelled_as_a_correction_is_held_as_a_contradiction() -> None:
    w = _reservations()
    _handbook(w, admission5(replacement={"p1": "CONFLICTING_EVIDENCE"}))
    assert w.current() == {"hold": "2 days"}, "the settled claim stays current, 3 days held"
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "CONFLICT" and gap.kind is GapKind.CONTRADICTION
    assert gap.conflicting_claim_ids == (w.claim_id("hold"),)
    assert w.governor.state().semantic.correction_sets == {}
    queue = list_authority_work(w.governor)
    assert queue.items == () and queue.correction_sets == (), "no ordinary correction work"


def test_a_genuine_correction_continues_to_founder_authority() -> None:
    w = _refunds()
    w.send("REF-2", "Refunds", _spec("Refunds", R14), (
        _a("p1", (1,), ("ASSERT", "refund_window_v2", "14 days"), ("SUPERSEDE", "refund_window")),
    ), verifier=admission5(), sup="REF-1")  # fmt: skip
    (pending,) = w.governor.state().semantic.correction_sets.values()
    assert pending.status == "PENDING" and w.holds() == []
    assert w.current() == {"refund_window": "30 days"}, "nothing applies before authority"
    w.agree("Refunds")
    assert w.current() == {"refund_window_v2": "14 days"}


@pytest.mark.parametrize(
    ("seed", "drafts", "after"),
    [
        (("a",), (("ASSERT", "n1", "x"), ("SUPERSEDE", "a")), {"n1"}),
        (("a", "b"), (("ASSERT", "n1", "x"), ("SUPERSEDE", "a"), ("SUPERSEDE", "b")), {"n1"}),
        (("a",), (("ASSERT", "n1", "x"), ("ASSERT", "n2", "y"), ("SUPERSEDE", "a")),
         {"n1", "n2"}),
    ],
    ids=["1:1", "N:1", "1:N"],
)  # fmt: skip
def test_supported_corrections_of_every_cardinality(
    seed: tuple[str, ...], drafts: tuple[tuple[str, ...], ...], after: set[str]
) -> None:
    w = World()
    text = _spec("Rules", *(f"Rule {s} holds." for s in seed))
    w.send("R-1", "Rules", text,
           tuple(_a(f"s{i}", (i,), ("ASSERT", s, s)) for i, s in enumerate(seed, 1)),
           verifier=admission5())  # fmt: skip
    w.send("R-2", "Rules", _spec("Rules", "The rules are replaced."), (_a("p1", (1,), *drafts),),
           verifier=admission5(), sup="R-1")  # fmt: skip
    w.agree("Rules")
    assert set(w.current()) == after and w.holds() == []


def test_supported_n_to_m_correction() -> None:
    w = World()
    w.send("R-1", "Rules", _spec("Rules", "Rule a holds.", "Rule b holds."),
           (_a("s1", (1,), ("ASSERT", "a", "a")), _a("s2", (2,), ("ASSERT", "b", "b"))),
           verifier=admission5())  # fmt: skip
    w.send("R-2", "Rules", _spec("Rules", "Rule c replaces a.", "Rule d replaces b."), (
        _a("p1", (1,), ("ASSERT", "c", "c"), ("SUPERSEDE", "a")),
        _a("p2", (2,), ("ASSERT", "d", "d"), ("SUPERSEDE", "b")),
    ), verifier=admission5(), sup="R-1")  # fmt: skip
    w.agree("Rules")
    assert set(w.current()) == {"c", "d"} and w.holds() == []


def test_an_uncertain_replacement_is_held_unresolved_and_never_applied() -> None:
    w = _reservations()
    _handbook(w, admission5(replacement={"p1": "UNCERTAIN"}))
    assert w.current() == {"hold": "2 days"}
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "UNCERTAIN" and gap.kind is GapKind.AMBIGUITY
    assert w.governor.state().semantic.correction_sets == {}


def test_one_conflicting_replacement_holds_the_whole_atomic_set() -> None:
    w = World()
    w.send("R-1", "Rules", _spec("Rules", "Rule a holds.", "Rule b holds."),
           (_a("s1", (1,), ("ASSERT", "a", "a")), _a("s2", (2,), ("ASSERT", "b", "b"))),
           verifier=admission5())  # fmt: skip
    w.send("R-2", "Rules", _spec("Rules", "Rule c replaces a.", "Rule d is stated elsewhere."), (
        _a("p1", (1,), ("ASSERT", "c", "c"), ("SUPERSEDE", "a")),
        _a("p2", (2,), ("ASSERT", "d", "d"), ("SUPERSEDE", "b")),
    ), verifier=admission5(replacement={"p2": "CONFLICTING_EVIDENCE"}), sup="R-1")  # fmt: skip
    assert set(w.current()) == {"a", "b"}, "no partial application"
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "CONFLICT" and gap.held_proposition_ids == ("p1", "p2")
    assert gap.conflicting_claim_ids == (w.claim_id("b"),)
    assert w.governor.state().semantic.correction_sets == {}


@pytest.mark.parametrize(
    "raw",
    [
        {"p1": (("CLAIM-ghost", "SUPPORTED_REPLACEMENT"),)},
        {"p1": (("TARGET", "SUPPORTED_REPLACEMENT"), ("CLAIM-extra", "SUPPORTED_REPLACEMENT"))},
    ],
    ids=["invalid-target-id", "unshown-extra-target"],
)
def test_an_invalid_replacement_target_holds_the_whole_response(
    raw: dict[str, tuple[tuple[str, str], ...]],
) -> None:
    w = _reservations()
    target = w.claim_id("hold")
    raw = {p: tuple((target if c == "TARGET" else c, j) for c, j in v) for p, v in raw.items()}
    _handbook(w, admission5(raw=raw))
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFIER_OUTPUT_INVALID" and w.current() == {"hold": "2 days"}


def test_a_target_left_unjudged_holds_the_whole_response() -> None:
    w = _reservations()

    def omit(request: AdmissionRequestV5) -> AdmissionReportV5:
        report: AdmissionReportV5 = admission5()._answer(request)  # type: ignore[assignment]
        return report.model_copy(
            update={"verdicts": tuple(v.model_copy(update={"replacements": ()})
                                      for v in report.verdicts)}
        )  # fmt: skip

    _handbook(w, AdmissionVerifierV5(omit))
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFIER_OUTPUT_INVALID" and w.current() == {"hold": "2 days"}


def test_a_v4_report_on_a_v5_request_and_a_v5_report_on_a_v4_request_are_invalid() -> None:
    w = _reservations()

    class V4AnswersV5Request(AdmissionVerifierV5):
        def __init__(self) -> None:
            inner = admission()
            super().__init__(inner._answer)
            self.identity = inner.identity

    _handbook(w, V4AnswersV5Request())
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFIER_OUTPUT_INVALID"


def test_writer_conflict_and_replacement_conflict_on_one_unit_make_one_gap() -> None:
    w = _reservations()
    _handbook(w, admission5(replacement={"p1": "CONFLICTING_EVIDENCE"}),
              ("CONFLICT_CLAIM", "hold"))  # fmt: skip
    (gap,) = w.holds()
    assert gap.cause == "CONFLICT" and gap.conflicting_claim_ids == (w.claim_id("hold"),)


def test_the_replacement_conflict_resolves_by_the_existing_lawful_change() -> None:
    w = _reservations()
    _handbook(w, admission5(replacement={"p1": "CONFLICTING_EVIDENCE"}))
    (gap,) = w.holds(GapStatus.OPEN)
    w.send("RES-2", "Reservations", _spec("Reservations", "The hold is changed to 3 days."), (
        _a("p1", (1,), ("ASSERT", "hold_v2", "3 days"), ("SUPERSEDE", "hold")),
    ), verifier=admission5(), sup="RES-1")  # fmt: skip
    w.agree("Reservations")
    assert w.current() == {"hold_v2": "3 days"}
    (resolved,) = [g for g in w.holds() if g.id == gap.id]
    assert resolved.status is GapStatus.RESOLVED


def test_replay_never_calls_the_verifier() -> None:
    w = _reservations()
    verifier = admission5(replacement={"p1": "CONFLICTING_EVIDENCE"})
    _handbook(w, verifier)
    events = list(w.store.load(PROJECT))
    assert replay(PROJECT, events) == w.governor.state()
    assert len(verifier.requests) == 1
    (record,) = [
        r for r in w.governor.state().semantic.completeness_records.values()
        if r.verifier.policy_version == SEMANTIC_ADMISSION_POLICY_VERSION_V5 and r.outcome == "FAIL"
    ]  # fmt: skip
    assert isinstance(record.request, AdmissionRequestV5)
    assert isinstance(record.report, AdmissionReportV5)
    assert record.failure_codes == ("SEMANTIC_REPLACEMENT_CONFLICT",)


@pytest.mark.parametrize("note", [None, "", "this is clearly a correction", "contradiction!"])
def test_the_note_never_changes_the_outcome(note: str | None) -> None:
    w = _reservations()
    _handbook(w, admission5(replacement={"p1": "CONFLICTING_EVIDENCE"}, note=note))
    assert w.current() == {"hold": "2 days"}
    assert [g.cause for g in w.holds(GapStatus.OPEN)] == ["CONFLICT"]
