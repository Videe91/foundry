"""The v6 scripted human authority (design §7.5): deterministic, human, checkpoint-free.

After dense T2 the scripted human reads the production authority-work listing and decides
every PENDING correction set, as of the listing's sequence: AGREE in one branch, DECLINE in the
other. It is the architect's live project-wide authority, never the model's. Nothing here
calls a model.
"""

from __future__ import annotations

import pytest

from foundry.application.authority_routing import StaleAuthorityDecision, decide_correction_set
from foundry.application.replay import replay
from foundry.domain.authority_work import authority_routing_findings, authority_work
from foundry.domain.events import CorrectionSetDecidedPayload, EventType
from foundry.experiments.locus_validation_v6.protocol import ARCHITECT, AUTHORITY_PROTOCOL
from foundry.experiments.locus_validation_v6.world import fresh_governor
from tests.unit.test_locus_validation_v6_evaluation import run_of


def _dense():  # type: ignore[no-untyped-def]
    (dense,) = [lg for lg in run_of().ledgers if lg.ledger == "dense"]
    return dense


def test_the_pending_work_after_t2_is_four_sets_discovered_by_the_production_listing() -> None:
    dense = _dense()
    queue = dense.work_after_t2
    assert queue is not None and queue.items == ()
    assert len(queue.correction_sets) == 4
    assert authority_routing_findings(dense.deltas[1].state_after, queue) == ()
    again = authority_work(replay(dense.deltas[1].state_after.project_id, dense.events))
    assert [s.work_id for s in again.correction_sets] == [s.work_id for s in queue.correction_sets]


@pytest.mark.parametrize("branch", ["AGREE", "DECLINE"])
def test_every_listed_set_is_decided_whole_by_the_architect(branch: str) -> None:
    dense = _dense()
    listed = {s.work_id for s in dense.work_after_t2.correction_sets}
    (b,) = [x for x in dense.branches if x.branch == branch]
    assert {d.work_id for d in b.decisions} == listed
    state = b.state_after_decisions.semantic
    for decision in b.decisions:
        record = state.correction_sets[decision.work_id]
        assert record.status == ("AGREED" if branch == "AGREE" else "DECLINED")
        assert record.decided_by == ARCHITECT
        applied = set(record.member_judgment_ids) & set(state.applied_judgment_ids)
        assert applied == (set(record.member_judgment_ids) if branch == "AGREE" else set())
        assert decision.listed_at_sequence <= decision.decided_at_sequence
    decided = [
        e.event.payload for e in b.events if e.event.event_type is EventType.CORRECTION_SET_DECIDED
    ]
    assert len(decided) == 4
    assert all(
        isinstance(p, CorrectionSetDecidedPayload)
        and p.authority_protocol == AUTHORITY_PROTOCOL
        and p.decided_by == ARCHITECT
        for p in decided
    )


def test_the_dense_governor_runs_correction_sets_and_the_architect_holds_authority() -> None:
    _, governor = fresh_governor("dense", clock=lambda: None, id_factory=lambda p: f"{p}-X")  # type: ignore[arg-type,return-value]
    policy = governor._policy  # noqa: SLF001 - the frozen configuration under test
    assert policy.correction_sets is True and policy.canonical_facets is True
    for ledger in ("core", "orion", "jobs", "conflict", "large"):
        _, g = fresh_governor(ledger, clock=lambda: None, id_factory=lambda p: f"{p}-X")  # type: ignore[arg-type,return-value]
        assert g._policy.correction_sets is True  # noqa: SLF001


def test_a_decision_taken_on_a_stale_listing_is_refused_by_production() -> None:
    dense = _dense()
    (b,) = [x for x in dense.branches if x.branch == "AGREE"]
    first = b.decisions[0]
    from foundry.adapters.memory.event_store import InMemoryEventStore
    from foundry.application.semantic_governance import SemanticGovernor
    from foundry.domain.admission import AdmissionPolicy

    store = InMemoryEventStore()
    for stored in b.events:
        store.append(stored.event, expected_sequence=stored.sequence - 1)
    governor = SemanticGovernor(
        store=store,
        project_id=b.state_after_decisions.project_id,
        policy=AdmissionPolicy(canonical_facets=True, correction_sets=True),
        clock=lambda: None,  # type: ignore[arg-type,return-value]
        id_factory=lambda p: f"{p}-S",
    )
    with pytest.raises(StaleAuthorityDecision):
        decide_correction_set(
            governor,
            work_id=first.work_id,
            outcome="DECLINE",
            human_actor_id=ARCHITECT,
            expected_sequence=first.listed_at_sequence,
            rationale="late",
        )
