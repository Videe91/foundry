"""Canonical facets on the real pipeline: C09, C6, revocation, the 16-concern world, and the
four nearby pairs (IE2 v2 design §7.1.2).

A scripted provider names each governed concern in ``subject`` exactly as the grain fixture
labels it; everything else is production: ``XAICanonicalFacetSemanticReasoner``'s output
contract, parser, facet projection and reference law, ``assimilate_delta``'s two calls, and a
``SemanticGovernor`` under ``AdmissionPolicy(canonical_facets=True)``. Only the transport is
replaced (``_call_model``). What this proves is what is decidable offline: once the concern
is chosen, the facet adds no choice, stays identical as compatible dimensions join the
address, and differs whenever the subject differs. Whether the live model chooses the
concern well is a question for a sealed validation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics.xai_reasoner import (
    ConcernDraftPayload,
    SemanticOutputError,
    XAICanonicalFacetSemanticReasoner,
)
from foundry.application.incremental_assimilation import assimilate_delta
from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic_identity import canonical_facet
from foundry.domain.semantic_judgment import JudgmentKind
from foundry.domain.semantic_view import active_judgment_ids
from foundry.experiments.locus_formation.grain import FIXTURES, GrainFixture, grade_grouping
from foundry.ports.semantic_reasoner import ReasoningRequest

AT = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
PROJECT = "PROJ-CANONICAL-FACET"
SCOPE = "canonical-facet"
V3_RUN = Path("docs/superpowers/experiments/2026-09-29-locus-validation-v3/run.json")

Reply = Callable[[ReasoningRequest], dict[str, Any]]


class ScriptedCanonicalFacetReasoner(XAICanonicalFacetSemanticReasoner):
    """The production canonical-facet adapter with its transport replaced by a script."""

    def __init__(self, reply: Reply) -> None:
        ticks = count(1)
        super().__init__(
            api_key="test-key",
            clock=lambda: AT,
            id_factory=lambda prefix: f"{prefix}-{next(ticks):04d}",
        )
        self._reply = reply

    def _call_model(self, request: ReasoningRequest) -> Any:
        return SimpleNamespace(
            content=json.dumps(self._reply(request)),
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            cost_usd=0.0,
        )


def _evidence(evidence_id: str, text: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=text,
        observed_at=AT,
        scope=(SCOPE,),
    )


def concern_script(concern_of: dict[str, str]) -> Reply:
    """Names each evidence item's concern in ``subject``; binds to a known address with that
    subject, creates one address per new concern, asserts one claim per evidence item."""

    def reply(request: ReasoningRequest) -> dict[str, Any]:
        known = {a.subject: a.address_id for a in request.known_addresses}
        drafts: list[dict[str, Any]] = []
        if JudgmentKind.CREATE_ADDRESS in request.allowed_judgment_kinds:
            new: dict[str, list[str]] = {}
            for item in request.evidence:
                concern = concern_of[item.evidence_id]
                if concern in known:
                    drafts.append(
                        {
                            "kind": "BIND_TO_ADDRESS",
                            "address_id": known[concern],
                            "subject": concern,
                            "evidence_ids": [item.evidence_id],
                            "rationale": "same governed concern",
                        }
                    )
                else:
                    new.setdefault(concern, []).append(item.evidence_id)
            for concern, evidence_ids in new.items():
                drafts.append(
                    {
                        "kind": "CREATE_ADDRESS",
                        "subject": concern,
                        "evidence_ids": evidence_ids,
                        "rationale": "a governed concern",
                    }
                )
        else:
            for item in request.evidence:
                drafts.append(
                    {
                        "kind": "ASSERT_CLAIM",
                        "address_id": known[concern_of[item.evidence_id]],
                        "predicate": f"dimension {item.evidence_id}",
                        "value": {"kind": "TEXT", "text": item.content},
                        "evidence_ids": [item.evidence_id],
                        "rationale": "one proposition",
                    }
                )
        return {"drafts": drafts}

    return reply


class World:
    def __init__(self, concern_of: dict[str, str]) -> None:
        ids = count(1)
        self.governor = SemanticGovernor(
            store=InMemoryEventStore(),
            project_id=PROJECT,
            policy=AdmissionPolicy(canonical_facets=True),
            clock=lambda: AT,
            id_factory=lambda prefix: f"{prefix}-{next(ids):05d}",
        )
        self.reasoner = ScriptedCanonicalFacetReasoner(concern_script(concern_of))
        self.snapshots: list[dict[str, tuple[str, str]]] = []

    def delta(self, items: list[EvidenceItem]) -> None:
        outcome = assimilate_delta(
            governor=self.governor, reasoner=self.reasoner, delta=tuple(items), scope=SCOPE
        )
        routes = [d.route.value for stage in outcome.stage_decisions for d in stage]
        assert set(routes) == {"APPLY"}, routes
        self.snapshots.append(self.addresses())

    def addresses(self) -> dict[str, tuple[str, str]]:
        state = self.governor.state().semantic
        return {a: (x.subject, x.facet) for a, x in sorted(state.addresses.items())}

    def placement(self) -> dict[str, str]:
        """proposition evidence id -> address of the live claim citing it."""
        state = self.governor.state().semantic
        active = active_judgment_ids(state)
        return {
            ev: c.address_id
            for c in state.claims.values()
            if c.created_by_judgment_id in active
            for ev in c.evidence_ids
        }

    def bind_candidate_facets(self) -> set[str]:
        state = self.governor.state().semantic
        return {
            j.proposal.candidate.facet
            for j in state.judgments.values()
            if j.proposal.kind is JudgmentKind.BIND_TO_ADDRESS
        }


def _fixture(fixture_id: str) -> GrainFixture:
    (hit,) = [f for f in FIXTURES if f.id == fixture_id]
    return hit


def _play(fixture: GrainFixture) -> World:
    """ONE_CONCERN: every proposition but the last at T1, the last joins at T2 (the C09 and
    C6 shape). SEPARATE_CONCERNS: all propositions in one delta."""
    items = {p.id: _evidence(f"EV-{p.id}", p.text) for p in fixture.propositions}
    world = World({f"EV-{p.id}": p.concern for p in fixture.propositions})
    ids = [p.id for p in fixture.propositions]
    if fixture.kind == "ONE_CONCERN":
        world.delta([items[i] for i in ids[:-1]])
        world.delta([items[ids[-1]]])
    else:
        world.delta([items[i] for i in ids])
    return world


def _grade(world: World, fixture: GrainFixture) -> tuple[str, ...]:
    placed = world.placement()
    return grade_grouping(
        fixture,
        {p.id: placed[f"EV-{p.id}"] for p in fixture.propositions if f"EV-{p.id}" in placed},
    )


# ------------------------------------------------------------------ one concern, stable facet


@pytest.mark.parametrize(
    ("fixture_id", "concern", "dimensions"),
    [
        ("G1-JOB-CANCELLATION", "job cancellation", 4),
        ("G2-LATE-DELIVERY-COMPENSATION", "late-delivery compensation", 3),
        ("G3-CREDENTIAL-REVOCATION", "credential revocation", 4),
    ],
)
def test_one_concern_keeps_one_address_and_one_canonical_facet(
    fixture_id: str, concern: str, dimensions: int
) -> None:
    fixture = _fixture(fixture_id)
    world = _play(fixture)
    assert _grade(world, fixture) == ()
    (address,) = world.addresses().items()
    assert (
        address[1] == (concern, canonical_facet(concern)) == (concern, f"Rules governing {concern}")
    )
    assert len(world.placement()) == dimensions
    # T1 and T2 show the identical address and facet; the T2 dimension bound with the same
    # canonical facet, so a compatible extension never needs a new or different facet.
    assert world.snapshots[0] == world.snapshots[1]
    assert world.bind_candidate_facets() == {canonical_facet(concern)}


def test_c09_repeated_cancellation_joins_the_one_cancellation_address() -> None:
    fixture = _fixture("G1-JOB-CANCELLATION")
    world = _play(fixture)
    (address_id,) = world.addresses()
    placed = world.placement()
    assert {placed[f"EV-{p.id}"] for p in fixture.propositions} == {address_id}
    assert world.addresses()[address_id][1] == "Rules governing job cancellation"


def test_c6_request_deadline_joins_late_delivery_compensation() -> None:
    fixture = _fixture("G2-LATE-DELIVERY-COMPENSATION")
    world = _play(fixture)
    (address_id,) = world.addresses()
    assert world.placement()["EV-LATE-3"] == address_id
    assert world.addresses()[address_id][1] == "Rules governing late-delivery compensation"


# ------------------------------------------------------------------ nearby concerns stay apart


@pytest.mark.parametrize(
    "fixture_id",
    [
        "G4-CANCELLATION-VS-AUDIT-DELETION",
        "G5-LATE-VS-DAMAGE-COMPENSATION",
        "G6-COMPENSATION-VS-SETTLEMENT",
        "G7-TWO-REFUND-CONCERNS",
    ],
)
def test_separate_concerns_get_separate_addresses_and_different_facets(fixture_id: str) -> None:
    fixture = _fixture(fixture_id)
    world = _play(fixture)
    assert _grade(world, fixture) == ()
    concerns = {p.concern for p in fixture.propositions}
    addresses = world.addresses()
    assert len(addresses) == len(concerns) == 2
    facets = {facet for _, facet in addresses.values()}
    assert facets == {canonical_facet(c) for c in concerns}
    assert len(facets) == 2


# ------------------------------------------------------------------ the 16-concern world


def _v3_large_subjects() -> dict[str, tuple[str, str]]:
    """Each recorded v3 large-world address: document -> (subject, recorded facet)."""
    run = json.loads(V3_RUN.read_text())
    (large,) = [lg for lg in run["ledgers"] if lg["ledger"] == "large"]
    semantic = large["deltas"][0]["state_after"]["semantic"]
    out: dict[str, tuple[str, str]] = {}
    for address in semantic["addresses"].values():
        creator = semantic["judgments"][address["created_by_judgment_id"]]
        (evidence_id,) = creator["proposal"]["candidate"]["evidence_ids"]
        out[evidence_id] = (address["subject"], address["facet"])
    return out


def test_the_v3_large_world_recorded_sixteen_identical_generic_facets() -> None:
    recorded = _v3_large_subjects()
    assert len(recorded) == 16
    assert {facet for _, facet in recorded.values()} == {"How it is governed"}
    assert len({subject for subject, _ in recorded.values()}) == 16


def test_the_sixteen_concern_world_gets_sixteen_concern_specific_canonical_facets() -> None:
    recorded = _v3_large_subjects()
    items = [_evidence(ev, f"source {ev}") for ev in sorted(recorded)]
    world = World({ev: subject for ev, (subject, _) in recorded.items()})
    world.delta(items)
    addresses = world.addresses()
    facets = [facet for _, facet in addresses.values()]
    assert len(addresses) == 16 and len(set(facets)) == 16
    for subject, facet in addresses.values():
        assert facet == canonical_facet(subject) and subject in facet
    assert "How it is governed" not in facets


def test_every_recorded_v3_facet_would_now_be_refused() -> None:
    """The v3 facets that failed or were degenerate are not canonical projections."""
    for subject, facet in _v3_large_subjects().values():
        assert facet != canonical_facet(subject)
    for subject, facet in (
        ("Late delivery compensation", "Sender refund entitlement"),
        ("Damaged parcel compensation", "Sender refund entitlement"),
        ("Cancelling a scheduled job", "Governance"),
        ("Job audit record", "Lifecycle"),
    ):
        assert facet != canonical_facet(subject)


# ------------------------------------------------------------------ the output boundary


def test_a_model_that_writes_a_facet_is_refused_by_the_contract() -> None:
    """The canonical-facet contract has no facet field: a reply carrying one violates the
    sealed schema and the whole batch is refused, so no model facet can reach state."""

    def writes_a_facet(request: ReasoningRequest) -> dict[str, Any]:
        (item,) = request.evidence
        return {
            "drafts": [
                {
                    "kind": "CREATE_ADDRESS",
                    "subject": "job cancellation",
                    "facet": "How it is governed",
                    "evidence_ids": [item.evidence_id],
                    "rationale": "x",
                }
            ]
        }

    world = World({})
    world.reasoner = ScriptedCanonicalFacetReasoner(writes_a_facet)
    with pytest.raises(SemanticOutputError, match="violates the sealed output schema"):
        assimilate_delta(
            governor=world.governor,
            reasoner=world.reasoner,
            delta=(_evidence("EV-X", "Operators may cancel jobs."),),
            scope=SCOPE,
        )
    assert world.governor.state().semantic.addresses == {}


def test_the_contract_schema_offers_no_facet_to_the_model() -> None:
    schema = json.dumps(ConcernDraftPayload.model_json_schema())
    assert '"facet"' not in schema
