"""The verified IE2 pipeline (``ie2-verified-assimilation-v1``), end to end and offline.

Call 1 -> Call 2 proposal -> (adapter accounting) -> Call 3 semantic completeness verification
-> only on PASS, admission. A FAIL applies nothing of Call 2 (no judgment, no correction set, no
authority work), keeps the proposal and the verifier's findings durable, and raises a precise
``INCOMPLETE_PROPOSITION_MEANING`` failure. No live call: the reasoner and verifier are scripted.
"""

from __future__ import annotations

from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.replay import replay
from foundry.application.semantic_completeness import (
    SemanticCompletenessRefused,
    SemanticCompletenessRequired,
    recorded_outcome,
)
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic_completeness import (
    INCOMPLETE_PROPOSITION_MEANING,
    SEMANTIC_COMPLETENESS_POLICY_VERSION,
    VerifierIdentity,
)
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.domain.semantic_view import derive_view
from foundry.domain.structural_refusal import ExecutionMode
from tests.unit._completeness_fixtures import (
    AT,
    ScriptedAccountingReasoner,
    ScriptedVerifier,
    all_complete,
    event_types,
    missing_in,
)

PROJECT = "PROJ-SC"
SCOPE = "carshare"
CREDIT_CLAIM = (
    "## 11. Claiming the service credit\n\nRules\n"
    "1. The service credit for an unavailable vehicle must be claimed in the app within 48 hours "
    "after the reservation start.\n"
    "2. A claim made later is refused.\n"
    "3. The claim must name the reservation and include a photo of the vehicle.\n"
)
K_CREDIT_CALL_2 = (
    (
        "p13",
        (1, 2),
        "The service credit for an unavailable vehicle must be claimed in the app within 48 hours "
        "after the reservation start, and a later claim is refused.",
        (("ASSERT", "claim_deadline_after_reservation_start", "48 hours"),),
    ),
    (
        "p14",
        (3,),
        "The service-credit claim must name the reservation and include a photo of the vehicle.",
        (("ASSERT", "claim_contents", "must name the reservation and include a photo"),),
    ),
)
_IDS = count(1)


def _world(correction_sets: bool = False) -> tuple[InMemoryEventStore, SemanticGovernor]:
    store = InMemoryEventStore()
    return store, SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(canonical_facets=True, correction_sets=correction_sets),
        clock=lambda: AT,
        id_factory=lambda p: f"{p}-{next(_IDS):05d}",
    )


def _doc(key: str, text: str, supersedes: str | None = None):  # type: ignore[no-untyped-def]
    return evidence_item(
        evidence_id=f"EV-{key}",
        project_id=PROJECT,
        source_kind=SourceKind.HUMAN,
        source_ref="human://author",
        content=text,
        observed_at=AT,
        scope=(SCOPE,),
        artifact_ref=f"spec/{key.split('-')[0]}.md",
        supersedes_evidence_id=supersedes,
    )


def _run(governor, reasoner, key, text, verifier, mode=ExecutionMode.EXPERIMENT, sup=None):  # type: ignore[no-untyped-def]
    return assimilate_delta(
        governor=governor,
        reasoner=reasoner,
        delta=(_doc(key, text, sup),),
        scope=SCOPE,
        mode=mode,
        verifier=verifier,
    )


def _call_2_judgments(governor: SemanticGovernor) -> list[str]:
    semantic = governor.state().semantic
    return [
        j
        for j, x in semantic.judgments.items()
        if x.proposal.kind not in (JudgmentKind.CREATE_ADDRESS, JudgmentKind.BIND_TO_ADDRESS)
    ]


# ------------------------------------------------------------------ success


def test_a_complete_call_2_passes_and_admission_continues() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    verifier = ScriptedVerifier(all_complete)
    outcome = _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier)
    assert outcome.calls_made == 3
    semantic = governor.state().semantic
    assert len(semantic.claims) == 2
    (record,) = semantic.completeness_records.values()
    assert record.outcome == "PASS" and record.verifier == verifier.identity
    types = event_types(store, PROJECT)
    recorded_at = types.index("SEMANTIC_COMPLETENESS_RECORDED")
    call_2_ids = set(_call_2_judgments(governor))
    order = [e.event for e in store.load(PROJECT)]
    for position, event in enumerate(order):
        payload = event.payload
        if (
            getattr(payload, "judgment", None) is not None
            and payload.judgment.judgment_id in call_2_ids
        ):
            assert position > recorded_at, "no Call-2 judgment is recorded before its verification"


# ------------------------------------------------------------------ K-CREDIT


def test_k_credit_loses_the_refusal_and_nothing_of_call_2_applies() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    verifier = ScriptedVerifier(missing_in("p13", "a later claim is refused"))
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier)
    (failure,) = refused.value.failures
    assert failure.code == INCOMPLETE_PROPOSITION_MEANING
    assert failure.proposition_id == "p13" and failure.missing == ("a later claim is refused",)
    semantic = governor.state().semantic
    assert _call_2_judgments(governor) == [] and semantic.claims == {}
    (record,) = semantic.completeness_records.values()
    assert record.outcome == "FAIL" and record.failure_codes == (INCOMPLETE_PROPOSITION_MEANING,)
    assert failure.verification_id == record.verification_id
    assert failure.claim_refs == (record.request.propositions[0].claims[0].ref,)
    (shown,) = verifier.requests
    p13 = next(p for p in shown.propositions if p.proposition_id == "p13")
    assert "a later claim is refused" in p13.statement
    assert [c.predicate for c in p13.claims] == ["claim_deadline_after_reservation_start"]
    assert p13.source_sentences == (
        "The service credit for an unavailable vehicle must be claimed in the app within 48 "
        "hours after the reservation start.",
        "A claim made later is refused.",
    )
    assert event_types(store, PROJECT)[-1] == "SEMANTIC_COMPLETENESS_RECORDED"


# ------------------------------------------------------------------ faithful splits


def test_one_proposition_judged_on_the_union_of_its_claims() -> None:
    _, governor = _world()
    text = (
        "## Reservations\n\nRules\n1. The reservation is made in the Kestrel app and states its "
        "start time and its end time.\n"
    )
    call_2 = (
        (
            "p05",
            (1,),
            "The reservation is made in the Kestrel app and states its start and end time.",
            (
                ("ASSERT", "booking_channel", "Kestrel app"),
                ("ASSERT", "stated_start_and_end_times", "start time and end time"),
            ),
        ),
    )
    reasoner = ScriptedAccountingReasoner("Vehicle reservation", [call_2])
    verifier = ScriptedVerifier(all_complete)
    _run(governor, reasoner, "BOOKING-T1", text, verifier)
    (shown,) = verifier.requests
    (review,) = shown.propositions
    assert [c.predicate for c in review.claims] == ["booking_channel", "stated_start_and_end_times"]
    assert len(governor.state().semantic.claims) == 2


@pytest.mark.parametrize(
    ("text", "props"),
    [
        (  # K-RES-2 as recorded: two model propositions from one sentence
            "## R\n\nRules\n1. The reservation is made in the Kestrel app and states its start "
            "time and its end time.\n",
            (
                (
                    "p05",
                    (1,),
                    "The reservation is made in the Kestrel app.",
                    (("ASSERT", "booking_channel", "Kestrel app"),),
                ),
                (
                    "p06",
                    (1,),
                    "The reservation states its start time and its end time.",
                    (("ASSERT", "stated_start_and_end_times", "start time and end time"),),
                ),
            ),
        ),
        (  # K-UNL-4 as recorded
            "## U\n\nRules\n1. After the fifth failed attempt the app must not send another unlock "
            "command for that reservation, and the member is directed to the support line.\n",
            (
                (
                    "p45",
                    (1,),
                    "After the fifth failed attempt no further unlock command is sent.",
                    (("ASSERT", "further_commands_after_fifth_failure", "no further command"),),
                ),
                (
                    "p46",
                    (1,),
                    "After the fifth failed attempt the member is directed to support.",
                    (("ASSERT", "support_redirection_after_fifth_failure", "support line"),),
                ),
            ),
        ),
    ],
)
def test_the_recorded_faithful_splits_pass(text: str, props: tuple) -> None:  # type: ignore[type-arg]
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Concern", [props])
    verifier = ScriptedVerifier(all_complete)
    _run(governor, reasoner, "SPLIT-T1", text, verifier)
    (shown,) = verifier.requests
    assert [p.proposition_id for p in shown.propositions] == [p[0] for p in props]
    assert all(len(p.claims) == 1 for p in shown.propositions)
    assert len(governor.state().semantic.claims) == 2


# ------------------------------------------------------------------ corrections

LATE_T1 = (
    "## 7. Late return\n\nRules\n"
    "1. No fee is charged if the vehicle is returned within 10 minutes after the reservation end.\n"
    "2. Beyond those 10 minutes the fee is 0.50 EUR for every started minute.\n"
    "3. The late-return fee for one reservation must not exceed 60 EUR.\n"
)
LATE_T2 = (
    "## 7. Late return\n\nRules\n"
    "1. The fee is a flat 25 EUR for any delay, however short.\n"
    "2. The late-return fee for one reservation must not exceed 60 EUR.\n"
)
_LATE_SEED = (
    ("s1", (1,), "No fee within 10 minutes.", (("ASSERT", "grace", "10 minutes"),)),
    ("s2", (2,), "0.50 EUR per started minute beyond.", (("ASSERT", "rate", "0.50 EUR"),)),
    ("s3", (3,), "The fee does not exceed 60 EUR.", (("ASSERT", "cap", "60 EUR"),)),
)
_LATE_NM = (  # K-LATE-7 as recorded: the flat amount and the any-delay rule, each retiring one
    (
        "p-flat",
        (1,),
        "The late-return fee is a flat 25 EUR.",
        (("ASSERT", "flat_fee_amount", "25 EUR"), ("SUPERSEDE", "rate")),
    ),
    (
        "p-any",
        (1,),
        "The late-return fee is charged for any delay, however short.",
        (("ASSERT", "charged_for_any_delay", "any delay"), ("SUPERSEDE", "grace")),
    ),
    ("p-cap", (2,), "The fee does not exceed 60 EUR.", (("SUPPORT", "cap"),)),
)


def _seeded(correction_sets: bool = True):  # type: ignore[no-untyped-def]
    store, governor = _world(correction_sets)
    reasoner = ScriptedAccountingReasoner("Late-return fee", [_LATE_SEED])
    _run(governor, reasoner, "LATE-T1", LATE_T1, ScriptedVerifier(all_complete))
    return store, governor, reasoner


def test_a_complete_nm_correction_becomes_one_atomic_correction_set() -> None:
    store, governor, reasoner = _seeded()
    reasoner.call_2.append(_LATE_NM)
    verifier = ScriptedVerifier(all_complete)
    _run(governor, reasoner, "LATE-T2", LATE_T2, verifier, sup="EV-LATE-T1")
    (shown,) = verifier.requests
    flat = next(p for p in shown.propositions if p.proposition_id == "p-flat")
    assert flat.disposition == "ASSERT_SUPERSEDE"
    assert [c.predicate for c in flat.retired] == ["rate"]
    cap = next(p for p in shown.propositions if p.proposition_id == "p-cap")
    assert cap.disposition == "SUPPORT" and cap.claims[0].role == "SUPPORTED"
    assert cap.claims[0].predicate == "cap"
    (pending,) = [
        r for r in governor.state().semantic.correction_sets.values() if r.status == "PENDING"
    ]
    assert len(pending.assertion_judgment_ids) == 2 and len(pending.supersede_judgment_ids) == 2


def test_an_incomplete_response_creates_no_correction_set_and_no_authority_work() -> None:
    """The correction itself is complete; another proposition of the same response is not.
    The response fails whole: no judgment, no correction set, no authority work."""
    store, governor, reasoner = _seeded()
    before = governor.state().semantic
    reasoner.call_2.append(_LATE_NM)
    verifier = ScriptedVerifier(missing_in("p-cap", "the cap applies per reservation"))
    with pytest.raises(SemanticCompletenessRefused):
        _run(governor, reasoner, "LATE-T2", LATE_T2, verifier, sup="EV-LATE-T1")
    after = governor.state().semantic
    assert after.correction_sets == {} == before.correction_sets
    assert after.claims == before.claims
    assert "CORRECTION_SET_PROPOSED" not in event_types(store, PROJECT)
    from foundry.application.authority_routing import list_authority_work

    queue = list_authority_work(governor)
    assert queue.correction_sets == () and queue.items == ()


# ------------------------------------------------------------------ fail-closed laws


def test_a_verifier_that_is_not_independent_applies_nothing() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    same = VerifierIdentity(
        provider="xai", model="grok-4.6", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION
    )
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, ScriptedVerifier(all_complete, same))
    assert refused.value.record.failure_codes == ("VERIFIER_NOT_INDEPENDENT",)
    assert governor.state().semantic.claims == {}


def test_an_unparseable_verifier_answer_applies_nothing() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, ScriptedVerifier(lambda r: None))
    assert refused.value.record.failure_codes == ("VERIFIER_OUTPUT_INVALID",)
    assert governor.state().semantic.claims == {}


def test_production_requires_a_verifier_and_writes_nothing_without_one() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    with pytest.raises(SemanticCompletenessRequired):
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, None, mode=ExecutionMode.PRODUCTION)
    assert store.load(PROJECT) == ()


def test_a_semantic_failure_is_never_reproposed() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2, K_CREDIT_CALL_2])
    verifier = ScriptedVerifier(missing_in("p13", "a later claim is refused"))
    with pytest.raises(SemanticCompletenessRefused):
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier, mode=ExecutionMode.PRODUCTION)
    assert reasoner.calls == 2 and len(verifier.requests) == 1
    assert "STRUCTURAL_REFUSAL_RECORDED" not in event_types(store, PROJECT)


def test_without_a_verifier_the_historical_two_call_path_is_unchanged() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    outcome = _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, None)
    assert outcome.calls_made == 2
    assert governor.state().semantic.completeness_records == {}
    assert len(governor.state().semantic.claims) == 2


def test_a_call_2_with_no_proposition_needs_no_verification() -> None:
    _, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [()])
    verifier = ScriptedVerifier(all_complete)
    outcome = _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, verifier)
    assert verifier.requests == [] and outcome.calls_made == 2


# ------------------------------------------------------------------ replay


def test_replay_reads_the_recorded_verdict_and_never_calls_the_verifier() -> None:
    store, governor = _world()
    reasoner = ScriptedAccountingReasoner("Service credit", [K_CREDIT_CALL_2])
    same = VerifierIdentity(
        provider="xai", model="grok-4.6", policy_version=SEMANTIC_COMPLETENESS_POLICY_VERSION
    )
    with pytest.raises(SemanticCompletenessRefused) as refused:
        _run(governor, reasoner, "CREDIT-T1", CREDIT_CLAIM, ScriptedVerifier(all_complete, same))
    replayed = replay(PROJECT, store.load(PROJECT))
    assert replayed == governor.state()
    invocation = refused.value.record.subject_invocation_id
    # every verdict in the report is COMPLETE, yet the recorded outcome is FAIL (not independent):
    assert {v.verdict for v in refused.value.record.report.verdicts} == {"COMPLETE"}  # type: ignore[union-attr]
    assert recorded_outcome(replayed, invocation) == "FAIL"
    assert derive_view(replayed.semantic).pending_judgment_ids == ()
