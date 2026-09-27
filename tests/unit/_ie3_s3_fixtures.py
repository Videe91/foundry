"""Shared builders for IE3 Slice 3: fake synthesizers, a racing store, research-sourced claims.

Everything is offline. A ``FakeGraphSynthesizer`` returns a fixed result (or a result computed
from the request it was shown) and records every request, so tests can prove it was called
exactly once and with exactly what was compiled. ``RacingStore`` wraps the real in-memory store
and lets a test land a concurrent write, or the very same event, just before an append.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import count

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.semantic_reducer import claim_id_for
from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import EventEnvelope, StoredEvent
from foundry.domain.evidence import evidence_item
from foundry.domain.intent_graph import IntentGraphSynthesisResult
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.ports.intent_graph_synthesizer import IntentGraphSynthesisRequest
from tests.unit._ie21_fixtures import ALICE, HUMAN, PROJECT, SCOPE
from tests.unit._ie22b_fixtures import World

GRAPH_POLICY = "intent-graph-synthesis-runtime-v1"
AI = ReasonerFingerprint(provider="fake", model="graph-model", policy_version=GRAPH_POLICY)
RESEARCHER = ReasonerFingerprint(
    provider="fake", model="research-agent", policy_version=GRAPH_POLICY
)
HUMAN_G = ReasonerFingerprint(provider="human", model=ALICE, policy_version=GRAPH_POLICY)
BOB = "human://bob"
HUMAN_BOB = ReasonerFingerprint(provider="human", model=BOB, policy_version=GRAPH_POLICY)
CLOCK_AT = datetime(2026, 9, 27, 15, 0, tzinfo=UTC)
_IDS = count(1)


def clock() -> datetime:
    return CLOCK_AT


def run_ids(*ids: str) -> Callable[[], str]:
    """A run-id factory that hands out exactly ``ids`` and then fails loudly."""
    remaining = list(ids)

    def factory() -> str:
        if not remaining:
            raise AssertionError("a new synthesis_run_id was requested; retries must reuse the run")
        return remaining.pop(0)

    return factory


class FakeGraphSynthesizer:
    """Offline stand-in for a graph synthesizer. Records every request it is shown."""

    def __init__(
        self,
        result: IntentGraphSynthesisResult
        | Callable[[IntentGraphSynthesisRequest], IntentGraphSynthesisResult],
        *,
        fingerprint: ReasonerFingerprint = AI,
    ) -> None:
        self._result = result
        self._fingerprint = fingerprint
        self.requests: list[IntentGraphSynthesisRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult:
        self.requests.append(request)
        if isinstance(self._result, IntentGraphSynthesisResult):
            return self._result
        return self._result(request)


class RacingStore:
    """The real store, plus hooks that fire just before an append, one per append call."""

    def __init__(
        self,
        inner: InMemoryEventStore,
        before_append: Sequence[Callable[[EventEnvelope], None]] = (),
    ) -> None:
        self.inner = inner
        self.hooks = list(before_append)
        self.append_calls = 0

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        self.append_calls += 1
        if self.hooks:
            self.hooks.pop(0)(event)
        return self.inner.append(event, expected_sequence)

    def load(self, project_id: str, after_sequence: int = 0) -> Sequence[StoredEvent]:
        return self.inner.load(project_id, after_sequence)

    def current_sequence(self, project_id: str) -> int:
        return self.inner.current_sequence(project_id)


def unrelated_write(world: World) -> Callable[[EventEnvelope], None]:
    """A concurrent write that changes nothing the graph depends on."""

    def hook(_: EventEnvelope) -> None:
        n = next(_IDS)
        world.governor.ingest(
            evidence_item(
                evidence_id=f"EV-noise-{n}",
                project_id=PROJECT,
                source_kind=SourceKind.DOCUMENT,
                source_ref=f"doc://noise/{n}",
                content="An unrelated memo.",
                observed_at=CLOCK_AT,
                scope=("elsewhere",),
            )
        )

    return hook


def research_claim(world: World, judgment_id: str, *, text: str) -> str:
    """A human-asserted CANONICAL claim whose only evidence is RESEARCH-sourced."""
    evidence_id = f"EV-research-{judgment_id}"
    world.governor.ingest(
        evidence_item(
            evidence_id=evidence_id,
            project_id=PROJECT,
            source_kind=SourceKind.RESEARCH,
            source_ref=f"https://regulator.example/{judgment_id}",
            content="Refunds must settle within thirty days under the consumer code.",
            observed_at=CLOCK_AT,
            scope=(SCOPE,),
        )
    )
    decision = world.governor.submit(
        SemanticJudgment(
            judgment_id=judgment_id,
            project_id=PROJECT,
            proposal=AssertClaimProposal(
                address_id=world.address_id,
                predicate="refund_window",
                value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
                evidence_ids=(evidence_id,),
                authority=Authority.CANONICAL,
            ),
            visible_evidence_ids=(evidence_id,),
            rationale="stated by the regulator",
            reasoner=HUMAN,
            invocation_id=f"INV-{judgment_id}-{next(_IDS)}",
            proposed_at=CLOCK_AT,
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY, decision
    return claim_id_for(PROJECT, judgment_id)
