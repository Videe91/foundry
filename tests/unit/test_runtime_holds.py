"""Runtime holds (Intent Engine runtime reset, round 2): contradictions, cause-specific gap
resolution, an unavailable verifier, and the smallest safe gap scope. Offline, no model.

* **Contradiction (Q1).** Call 2 may say a proposition conflicts with a current claim or with a
  sibling proposition of the same response. The current claim stays current; the conflicting
  side (and its minimal safe unit, closed over correction sets and sibling conflicts) is held
  as one blocking ``CONTRADICTION`` gap. Nothing picks a winner; nothing becomes authority work.
* **Resolution (Q2).** A hold gap Foundry itself created closes deterministically when its cause
  is demonstrably gone: a completeness or availability gap when the same source sentences at
  the same concern are later verified COMPLETE and admitted; a conflict gap when, by a later
  lawful change at that concern, none of its conflicting current claims is current any more.
* **Unavailable verifier (Q4).** Nothing is applied and a visible ``VERIFICATION_UNAVAILABLE``
  hold is recorded -- never NOT_COMPLETE, since no semantic judgement was made.
* **Scope (Q5).** A hold names the concerns (and conflicting claims) it is about, not ().
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.authority_routing import decide_correction_set, list_authority_work
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.closure import evaluate_closure
from foundry.domain.common import Authority, SourceKind
from foundry.domain.evidence import evidence_item
from foundry.domain.gaps import GapKind, GapStatus
from foundry.domain.semantic_holds import (
    PropositionConflict,
    SemanticHoldGap,
    hold_resolution_key,
)
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.domain.semantic_view import active_judgment_ids
from foundry.domain.structural_refusal import ExecutionMode
from foundry.ports.semantic_completeness import VerifierUnavailable
from foundry.ports.semantic_reasoner import AccountedProposal, ReasoningRequest
from tests.unit._completeness_fixtures import Prop, ScriptedAccountingReasoner, ScriptedVerifier
from tests.unit._ie21_fixtures import authority_record
from tests.unit.test_semantic_completeness_v3_pipeline import V3, verdicts

AT = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
PROJECT = "PROJ-HOLDS"
SCOPE = "library"
FOUNDER = "human://founder"


def _a(pid: str, n: tuple[int, ...], *drafts: tuple[str, ...]) -> Prop:
    return (pid, n, f"proposition {pid}", drafts)


class Writer(ScriptedAccountingReasoner):
    """A scripted Call-1/Call-2 writer keyed by evidence id. Drafts ``("CONFLICT_CLAIM",
    predicate)`` and ``("CONFLICT_PROP", proposition_id)`` become the response's conflicts."""

    def __init__(self) -> None:
        super().__init__("", [])
        self.script: dict[str, tuple[str, tuple[Prop, ...]]] = {}

    def propose_accounted(self, request: ReasoningRequest) -> AccountedProposal:
        (item,) = request.evidence
        self.subject, props = self.script[item.evidence_id]
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            return super().propose_accounted(request)
        by_predicate = {c.predicate: c for c in request.known_claims}
        conflicts: list[PropositionConflict] = []
        clean: list[Prop] = []
        for pid, numbers, statement, drafts in props:
            for d in drafts:
                if d[0] == "CONFLICT_CLAIM":
                    conflicts.append(
                        PropositionConflict(
                            proposition_id=pid, with_claim_id=by_predicate[d[1]].claim_id
                        )
                    )
                elif d[0] == "CONFLICT_PROP":
                    conflicts.append(
                        PropositionConflict(proposition_id=pid, with_proposition_id=d[1])
                    )
            clean.append(
                (
                    pid,
                    numbers,
                    statement,
                    tuple(d for d in drafts if not d[0].startswith("CONFLICT")),
                )
            )
        self.call_2.append(tuple(clean))
        proposal = super().propose_accounted(request)
        return proposal.model_copy(update={"conflicts": tuple(conflicts)})


class World:
    def __init__(self, prefix: str = "X") -> None:
        ids = count(1)
        self.store = InMemoryEventStore()
        self.governor = SemanticGovernor(
            store=self.store,
            project_id=PROJECT,
            policy=AdmissionPolicy(canonical_facets=True, correction_sets=True),
            clock=lambda: AT,
            id_factory=lambda p: f"{p}-{prefix}{next(ids):05d}",
        )
        self.governor.record_authority(
            authority_record("AUTH-founder", project_id=PROJECT, scope=(), subject_id="library",
                             authorized_by=FOUNDER, authority=Authority.CANONICAL)
        )  # fmt: skip
        self.writer = Writer()

    def send(
        self,
        key: str,
        subject: str,
        text: str,
        props: tuple[Prop, ...],
        verifier: Any = None,
        sup: str | None = None,
    ) -> Any:
        self.writer.script[f"EV-{key}"] = (subject, props)
        return assimilate_delta(
            governor=self.governor,
            reasoner=self.writer,
            delta=(
                evidence_item(
                    evidence_id=f"EV-{key}",
                    project_id=PROJECT,
                    source_kind=SourceKind.HUMAN,
                    source_ref=FOUNDER,
                    content=text,
                    observed_at=AT,
                    scope=(SCOPE,),
                    artifact_ref=f"spec/{subject}.md",
                    supersedes_evidence_id=f"EV-{sup}" if sup else None,
                ),
            ),
            scope=SCOPE,
            mode=ExecutionMode.EXPERIMENT,
            verifier=verifier if verifier is not None else ScriptedVerifier(verdicts(), V3),
        )

    def agree(self, subject: str) -> None:
        state = self.governor.state()
        (pending,) = [
            r for r in state.semantic.correction_sets.values()
            if r.status == "PENDING" and state.semantic.addresses[r.address_id].subject == subject
        ]  # fmt: skip
        decide_correction_set(
            self.governor, work_id=pending.correction_set_id, outcome="AGREE",
            human_actor_id=FOUNDER, expected_sequence=state.last_sequence, rationale="founder",
        )  # fmt: skip

    def current(self) -> dict[str, str]:
        semantic = self.governor.state().semantic
        active = active_judgment_ids(semantic)
        return {
            c.predicate: c.value.text or ""
            for c in semantic.claims.values()
            if c.created_by_judgment_id in active
        }

    def holds(self, status: GapStatus | None = None) -> list[SemanticHoldGap]:
        return [
            g for g in self.governor.state().gaps.values()
            if isinstance(g, SemanticHoldGap) and (status is None or g.status is status)
        ]  # fmt: skip

    def address(self, subject: str) -> str:
        (aid,) = [
            a.address_id for a in self.governor.state().semantic.addresses.values()
            if a.subject == subject
        ]  # fmt: skip
        return aid

    def claim_id(self, predicate: str) -> str:
        (cid,) = [
            c.claim_id for c in self.governor.state().semantic.claims.values()
            if c.predicate == predicate
        ]  # fmt: skip
        return cid

    def closure_gaps(self) -> list[str]:
        closure = evaluate_closure(self.governor.state(), SCOPE)
        return [i for b in closure.blockers if b.code == "OPEN_BLOCKING_GAP" for i in b.object_ids]


def _spec(title: str, *rules: str) -> str:
    return f"## {title}\n\nRules\n" + "".join(f"{n}. {r}\n" for n, r in enumerate(rules, 1))


HOLD_2 = "A reserved tool is held for 2 days after it becomes available."
HOLD_3 = "A reserved tool is held for 3 days after it becomes available."
MAX_RES = "A member may hold at most two reservations."


def _seeded() -> World:
    w = World()
    w.send("RES-1", "Reservations", _spec("Reservations", HOLD_2),
           (_a("p1", (1,), ("ASSERT", "hold_period", "2 days")),))  # fmt: skip
    return w


# --- Q1: contradictions -----------------------------------------------------------------------


def test_a_new_claim_conflicting_with_a_current_claim_is_held_and_the_current_one_stays() -> None:
    w = _seeded()
    w.send("RES-HB", "Reservations", _spec("Reservations", HOLD_3, MAX_RES), (
        _a("p1", (1,), ("ASSERT", "hold_period_handbook", "3 days"),
           ("CONFLICT_CLAIM", "hold_period")),
        _a("p2", (2,), ("ASSERT", "max_reservations", "two")),
    ))  # fmt: skip
    current = w.current()
    assert current["hold_period"] == "2 days", "A stays current"
    assert "hold_period_handbook" not in current, "B never silently becomes canonical"
    assert current["max_reservations"] == "two", "the unrelated proposition applies (C)"
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.kind is GapKind.CONTRADICTION and gap.blocking and gap.cause == "CONFLICT"
    assert gap.conflicting_claim_ids == (w.claim_id("hold_period"),)
    assert gap.held_proposition_ids == ("p1",)
    assert set(gap.affected_object_ids) == {w.address("Reservations"), w.claim_id("hold_period")}
    assert gap.id in w.closure_gaps()
    assert w.governor.state().semantic.correction_sets == {}
    queue = list_authority_work(w.governor)
    assert queue.items == () and queue.correction_sets == ()


def test_two_conflicting_sibling_propositions_both_stay_out_as_one_conflict_group() -> None:
    w = World()
    w.send("RES-1", "Reservations", _spec("Reservations", HOLD_2, HOLD_3, MAX_RES), (
        _a("p1", (1,), ("ASSERT", "hold_a", "2 days")),
        _a("p2", (2,), ("ASSERT", "hold_b", "3 days"), ("CONFLICT_PROP", "p1")),
        _a("p3", (3,), ("ASSERT", "max_reservations", "two")),
    ))  # fmt: skip
    assert w.current() == {"max_reservations": "two"}
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "CONFLICT" and gap.kind is GapKind.CONTRADICTION
    assert gap.held_proposition_ids == ("p1", "p2") and gap.conflicting_claim_ids == ()
    assert gap.affected_object_ids == (w.address("Reservations"),)


def test_a_conflict_inside_a_correction_set_holds_the_whole_set() -> None:
    w = _seeded()
    w.send("RES-1b", "Reservations", _spec("Reservations", MAX_RES),
           (_a("p1", (1,), ("ASSERT", "max_reservations", "two")),))  # fmt: skip
    w.send("RES-2", "Reservations", _spec("Reservations", HOLD_3, "A member may hold three."), (
        _a("p1", (1,), ("ASSERT", "hold_period_v2", "3 days"), ("SUPERSEDE", "hold_period")),
        _a("p2", (2,), ("ASSERT", "max_three", "three"), ("CONFLICT_CLAIM", "max_reservations")),
    ), sup="RES-1")  # fmt: skip
    current = w.current()
    assert current == {"hold_period": "2 days", "max_reservations": "two"}, "nothing of the set"
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "CONFLICT" and gap.held_proposition_ids == ("p1", "p2")
    assert w.governor.state().semantic.correction_sets == {}, "no correction-approval work"


def test_a_conflict_is_resolved_only_by_a_lawful_change_that_removes_it() -> None:
    w = _seeded()
    w.send("RES-HB", "Reservations", _spec("Reservations", HOLD_3),
           (_a("p1", (1,), ("ASSERT", "hold_period_handbook", "3 days"),
               ("CONFLICT_CLAIM", "hold_period")),))  # fmt: skip
    (gap,) = w.holds(GapStatus.OPEN)
    # Restating the current side decides nothing.
    w.send("RES-1r", "Reservations", _spec("Reservations", HOLD_2),
           (_a("p1", (1,), ("SUPPORT", "hold_period")),), sup="RES-1")  # fmt: skip
    assert [g.id for g in w.holds(GapStatus.OPEN)] == [gap.id]
    # A new claim at the same concern changes something there, but the conflicting claim is
    # still current: the contradiction is not gone.
    w.send("RES-MAX", "Reservations", _spec("Reservations", MAX_RES),
           (_a("p1", (1,), ("ASSERT", "max_reservations", "two")),))  # fmt: skip
    assert w.current()["max_reservations"] == "two"
    assert [g.id for g in w.holds(GapStatus.OPEN)] == [gap.id]
    # The founder corrects the spec; until the correction is agreed, the conflict stands.
    w.send("RES-2", "Reservations", _spec("Reservations", HOLD_3),
           (_a("p1", (1,), ("ASSERT", "hold_period_v2", "3 days"),
               ("SUPERSEDE", "hold_period")),), sup="RES-1r")  # fmt: skip
    assert [g.id for g in w.holds(GapStatus.OPEN)] == [gap.id]
    w.agree("Reservations")
    assert w.current() == {"hold_period_v2": "3 days", "max_reservations": "two"}
    (resolved,) = w.holds()
    assert resolved.id == gap.id and resolved.status is GapStatus.RESOLVED
    assert w.closure_gaps() == []


def test_replay_reproduces_holds_and_resolutions_without_any_model() -> None:
    w = _seeded()
    w.send("RES-HB", "Reservations", _spec("Reservations", HOLD_3),
           (_a("p1", (1,), ("ASSERT", "hold_period_handbook", "3 days"),
               ("CONFLICT_CLAIM", "hold_period")),))  # fmt: skip
    w.send("RES-2", "Reservations", _spec("Reservations", HOLD_3),
           (_a("p1", (1,), ("ASSERT", "hold_period_v2", "3 days"),
               ("SUPERSEDE", "hold_period")),), sup="RES-1")  # fmt: skip
    w.agree("Reservations")
    events = list(w.store.load(PROJECT))
    assert replay(PROJECT, events) == w.governor.state()
    types = [e.event.event_type.value for e in events]
    assert types.count("GAP_RESOLVED") == 1
    # A resolution exists only as its event: without it, replay leaves the gap open.
    without = [e for e in events if e.event.event_type.value != "GAP_RESOLVED"]
    (gap,) = [g for g in replay(PROJECT, without).gaps.values() if isinstance(g, SemanticHoldGap)]
    assert gap.status is GapStatus.OPEN


# --- Q2: completeness gaps resolve when the missing work arrives ------------------------------

FEE = "The annual membership fee is 25 EUR; members under 25 pay 10 EUR."
AGE = "Members must be 18 or older."
INCOMPLETE = (
    _a("p1", (1,), ("ASSERT", "minimum_age", "18 or older")),
    _a("p2", (2,), ("ASSERT", "annual_fee", "25 EUR")),
)
COMPLETE = (
    _a("p1", (1,), ("SUPPORT", "minimum_age")),
    _a("p2", (2,), ("ASSERT", "annual_fee", "25 EUR"), ("ASSERT", "under_25_fee", "10 EUR")),
)


def _held_fee() -> tuple[World, SemanticHoldGap]:
    w = World()
    w.send("MEM-1", "Membership", _spec("Membership", AGE, FEE), INCOMPLETE,
           verifier=ScriptedVerifier(verdicts({"p2"}), V3))  # fmt: skip
    (gap,) = w.holds(GapStatus.OPEN)
    return w, gap


def test_not_complete_records_a_blocking_completeness_gap_scoped_to_its_concern() -> None:
    w, gap = _held_fee()
    assert gap.kind is GapKind.WORKER_DIVERGENCE and gap.cause == "NOT_COMPLETE" and gap.blocking
    assert gap.held_proposition_ids == ("p2",)
    assert gap.affected_object_ids == (w.address("Membership"),), "not project-wide"
    assert w.current() == {"minimum_age": "18 or older"}
    assert gap.id in w.closure_gaps()


def test_the_identical_requirement_later_complete_and_admitted_resolves_that_exact_gap() -> None:
    w, gap = _held_fee()
    w.send("MEM-2", "Membership", _spec("Membership", AGE, FEE), COMPLETE, sup="MEM-1")
    (resolved,) = w.holds()
    assert resolved.id == gap.id and resolved.status is GapStatus.RESOLVED
    assert w.current()["under_25_fee"] == "10 EUR"
    assert w.closure_gaps() == [], "a resolved gap no longer blocks closure"


def test_an_unrelated_complete_proposition_does_not_resolve_the_gap() -> None:
    w, gap = _held_fee()
    w.send("MEM-3", "Membership", _spec("Membership", "Proof of address is required."),
           (_a("p1", (1,), ("ASSERT", "proof_of_address", "required")),))  # fmt: skip
    w.send("RES-1", "Reservations", _spec("Reservations", FEE),
           (_a("p1", (1,), ("ASSERT", "fee_text_elsewhere", "25 EUR")),))  # fmt: skip
    assert [g.id for g in w.holds(GapStatus.OPEN)] == [gap.id]


def test_a_changed_requirement_does_not_resolve_the_gap() -> None:
    w, gap = _held_fee()
    changed = "The annual membership fee is 30 EUR; members under 25 pay 10 EUR."
    w.send("MEM-2", "Membership", _spec("Membership", AGE, changed), (
        _a("p1", (1,), ("SUPPORT", "minimum_age")),
        _a("p2", (2,), ("ASSERT", "annual_fee", "30 EUR"), ("ASSERT", "under_25_fee", "10 EUR")),
    ), sup="MEM-1")  # fmt: skip
    assert [g.id for g in w.holds(GapStatus.OPEN)] == [gap.id]


def test_a_redelivery_that_is_held_again_does_not_resolve_the_gap() -> None:
    w, gap = _held_fee()
    again = (_a("p1", (1,), ("SUPPORT", "minimum_age")), INCOMPLETE[1])
    w.send("MEM-2", "Membership", _spec("Membership", AGE, FEE), again,
           verifier=ScriptedVerifier(verdicts({"p2"}), V3), sup="MEM-1")  # fmt: skip
    assert gap.id in [g.id for g in w.holds(GapStatus.OPEN)]
    assert len(w.holds(GapStatus.OPEN)) == 2


def test_the_resolution_key_is_stable_across_invocations_and_distinct_per_concern() -> None:
    w, one = _held_fee()
    again = (_a("p1", (1,), ("SUPPORT", "minimum_age")), INCOMPLETE[1])
    w.send("MEM-2", "Membership", _spec("Membership", AGE, FEE), again,
           verifier=ScriptedVerifier(verdicts({"p2"}), V3), sup="MEM-1")  # fmt: skip
    w.send("DUE-1", "Dues", _spec("Dues", AGE, FEE), INCOMPLETE,
           verifier=ScriptedVerifier(verdicts({"p2"}), V3))  # fmt: skip
    two, other = [g for g in w.holds() if g.id != one.id]
    assert one.subject_invocation_id != two.subject_invocation_id
    assert one.resolution_key == two.resolution_key, "same requirement, same concern"
    assert one.resolution_key == hold_resolution_key(PROJECT, one.kind, one.basis)
    assert other.resolution_key != one.resolution_key, "another concern"
    assert other.basis[0].sentence_sha256 == one.basis[0].sentence_sha256


# --- Q4: an unavailable verifier ----------------------------------------------------------------


class Unavailable:
    calls = 0

    def verify(self, request: Any) -> Any:
        Unavailable.calls += 1
        raise VerifierUnavailable("no model holds the verifier contract")


def test_an_unavailable_verifier_applies_nothing_and_leaves_a_visible_gap() -> None:
    w = World()
    w.send("MEM-1", "Membership", _spec("Membership", AGE, FEE), (
        _a("p1", (1,), ("ASSERT", "minimum_age", "18 or older")),
        _a("p2", (2,), ("ASSERT", "annual_fee", "25 EUR"), ("ASSERT", "under_25_fee", "10 EUR")),
    ), verifier=Unavailable())  # fmt: skip
    assert w.current() == {}
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFICATION_UNAVAILABLE", "never reported as NOT_COMPLETE"
    assert gap.kind is GapKind.CONTEXT_FAILURE
    assert gap.blocking and gap.held_proposition_ids == ("p1", "p2")
    assert gap.affected_object_ids == (w.address("Membership"),)
    assert w.governor.state().semantic.completeness_records == {}, "no semantic verdict exists"
    assert gap.id in w.closure_gaps()


def test_later_successful_verification_of_the_held_work_resolves_the_availability_gap() -> None:
    w = World()
    props = (
        _a("p1", (1,), ("ASSERT", "minimum_age", "18 or older")),
        _a("p2", (2,), ("ASSERT", "annual_fee", "25 EUR"), ("ASSERT", "under_25_fee", "10 EUR")),
    )
    w.send("MEM-1", "Membership", _spec("Membership", AGE, FEE), props, verifier=Unavailable())
    (gap,) = w.holds()
    w.send("MEM-2", "Membership", _spec("Membership", AGE, FEE), props, sup="MEM-1")
    (resolved,) = w.holds()
    assert resolved.id == gap.id and resolved.status is GapStatus.RESOLVED
    assert w.current()["under_25_fee"] == "10 EUR"


# --- Q5 + closure -------------------------------------------------------------------------------


def test_a_local_gap_blocks_project_closure_but_not_unrelated_work() -> None:
    w, gap = _held_fee()
    w.send("DEP-1", "Deposits", _spec("Deposits", "Power tools require a 50 EUR deposit."),
           (_a("p1", (1,), ("ASSERT", "deposit", "50 EUR")),))  # fmt: skip
    assert w.current()["deposit"] == "50 EUR", "unrelated safe work becomes canonical"
    assert w.closure_gaps() == [gap.id], "project closure stays blocked by the local gap"
    w.send("MEM-2", "Membership", _spec("Membership", AGE, FEE), COMPLETE, sup="MEM-1")
    assert w.closure_gaps() == []


def test_an_invalid_verifier_answer_holds_every_touched_concern() -> None:
    w = _seeded()
    w.send("MIX-1", "Reservations", _spec("Reservations", MAX_RES, HOLD_2), (
        _a("p1", (1,), ("ASSERT", "max_reservations", "two")),
        _a("p2", (2,), ("SUPPORT", "hold_period")),
    ), verifier=ScriptedVerifier(lambda r: None, V3))  # fmt: skip
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == "VERIFIER_OUTPUT_INVALID"
    assert gap.affected_object_ids == (w.address("Reservations"),)


@pytest.mark.parametrize("cause", ["NOT_COMPLETE", "VERIFICATION_UNAVAILABLE", "CONFLICT"])
def test_every_hold_gap_is_blocking_and_names_a_cause(cause: str) -> None:
    w = _seeded()
    verifier: Any = {
        "NOT_COMPLETE": ScriptedVerifier(verdicts({"p1"}), V3),
        "VERIFICATION_UNAVAILABLE": Unavailable(),
        "CONFLICT": None,
    }[cause]
    w.send("RES-HB", "Reservations", _spec("Reservations", HOLD_3),
           (_a("p1", (1,), ("ASSERT", "hold_period_handbook", "3 days"),
               *((("CONFLICT_CLAIM", "hold_period"),) if cause == "CONFLICT" else ())),),
           verifier=verifier)  # fmt: skip
    (gap,) = w.holds(GapStatus.OPEN)
    assert gap.cause == cause and gap.blocking and gap.affected_object_ids
