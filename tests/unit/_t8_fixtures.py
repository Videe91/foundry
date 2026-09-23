"""Shared fixtures for the T8 orchestrator suite.

Everything here builds real event streams through a real ``EventStore``: T8's whole
job is to turn compiled context into durable events, so a test that hand-built an
``IntentState`` would prove nothing about the path under test.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.replay import replay
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    SourceKind,
)
from foundry.domain.events import (
    EventEnvelope,
    EventPayload,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    SemanticObjectPayload,
    StoredEvent,
)
from foundry.domain.evidence import evidence_item
from foundry.domain.intent_synthesis import IntentSynthesisResult
from foundry.domain.semantic import AuthorityRecord, Requirement, SemanticBase
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    CreateAddressProposal,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
)
from foundry.domain.state import IntentState
from foundry.ports.intent_synthesizer import IntentSynthesisRequest

PROJECT = "PROJ-T8"
SCOPE = "payments"
OTHER_SCOPE = "security"
AT = datetime(2026, 9, 23, tzinfo=UTC)
DECIDED_AT = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)

AI = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")
HUMAN_ACTOR = "human://alice"
HUMAN = ReasonerFingerprint(provider="human", model=HUMAN_ACTOR, policy_version="p1")
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref=HUMAN_ACTOR)

RUN_ID = "RUN-1"


def fixed_clock(moment: datetime = DECIDED_AT):  # type: ignore[no-untyped-def]
    def clock() -> datetime:
        return moment

    return clock


def run_id_factory(*ids: str):  # type: ignore[no-untyped-def]
    """A factory that hands out ``ids`` in order and records how often it was called."""
    remaining = list(ids or [RUN_ID])
    calls: list[str] = []

    def factory() -> str:
        value = remaining.pop(0) if remaining else ""
        calls.append(value)
        return value

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


class RecordingStore:
    """An ``EventStore`` that remembers exactly how it was called.

    ``appends`` is what proves C12: the expected sequence T8 passed must be the
    sequence of the state the decision was computed against, never one the store was
    asked for afterwards. ``current_sequence_calls`` proves the appender never asks.
    """

    def __init__(self, inner: InMemoryEventStore | None = None) -> None:
        self._inner = inner or InMemoryEventStore()
        self.appends: list[tuple[EventEnvelope, int]] = []
        self.current_sequence_calls: list[str] = []

    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent:
        self.appends.append((event, expected_sequence))
        return self._inner.append(event, expected_sequence)

    def load(self, project_id: str, after_sequence: int = 0) -> Sequence[StoredEvent]:
        return self._inner.load(project_id, after_sequence)

    def current_sequence(self, project_id: str) -> int:
        self.current_sequence_calls.append(project_id)
        return self._inner.current_sequence(project_id)

    @property
    def appended_types(self) -> list[EventType]:
        return [event.event_type for event, _ in self.appends]


class ScriptedSynthesizer:
    """Returns pre-scripted results and records every request it was shown.

    No provider, no network, no adapter: T8 introduces no external call, and the
    recorded requests are what prove the synthesizer saw exactly the bounded T7
    request and nothing else.
    """

    def __init__(
        self, *results: IntentSynthesisResult, fingerprint: ReasonerFingerprint = AI
    ) -> None:
        self._results = list(results)
        self._fingerprint = fingerprint
        self.requests: list[IntentSynthesisRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    @property
    def calls(self) -> int:
        return len(self.requests)

    def synthesize(self, request: IntentSynthesisRequest) -> IntentSynthesisResult:
        self.requests.append(request)
        if not self._results:
            raise AssertionError("synthesizer called more times than the test scripted")
        return self._results.pop(0)


class Ledger:
    """Builds a real event stream inside a real store."""

    def __init__(self, store: RecordingStore | None = None) -> None:
        self.store = store or RecordingStore()
        self._n = 0

    def append(self, event_type: EventType, payload: EventPayload) -> StoredEvent:
        self._n += 1
        return self.store.append(
            EventEnvelope(
                event_id=f"EVT-seed-{self._n}",
                project_id=PROJECT,
                event_type=event_type,
                occurred_at=AT,
                payload=payload,
            ),
            expected_sequence=self.store.current_sequence(PROJECT),
        )

    def ingest(self, evidence_id: str, source_kind: SourceKind = SourceKind.DOCUMENT) -> None:
        self.append(
            EventType.EVIDENCE_INGESTED,
            EvidencePayload(
                evidence=evidence_item(
                    evidence_id=evidence_id,
                    project_id=PROJECT,
                    source_kind=source_kind,
                    source_ref=f"src://{evidence_id}",
                    content=f"body of {evidence_id}",
                    observed_at=AT,
                    scope=(SCOPE,),
                )
            ),
        )

    def apply(self, judgment: SemanticJudgment) -> None:
        self.append(
            EventType.SEMANTIC_JUDGMENT_RECORDED, SemanticJudgmentPayload(judgment=judgment)
        )
        self.append(
            EventType.SEMANTIC_ADMISSION_DECIDED,
            SemanticAdmissionPayload(
                judgment_id=judgment.judgment_id, route=AdmissionRoute.APPLY, reasons=("TEST",)
            ),
        )

    def record_judgment_only(self, judgment: SemanticJudgment) -> None:
        """Recorded but NOT admitted — a pending judgment (MISSING_AUTHORITY blocker)."""
        self.append(
            EventType.SEMANTIC_JUDGMENT_RECORDED, SemanticJudgmentPayload(judgment=judgment)
        )

    def record_object(self, obj: SemanticBase) -> None:
        self.append(EventType.SEMANTIC_OBJECT_RECORDED, SemanticObjectPayload(object=obj))

    def canonicalize(self, requirement_object: Requirement) -> None:
        self.append(
            EventType.REQUIREMENT_CANONICALIZED, SemanticObjectPayload(object=requirement_object)
        )

    def state(self) -> IntentState:
        return replay(PROJECT, self.store.load(PROJECT))


def judgment(judgment_id: str, proposal: JudgmentProposal, evidence_ids: tuple[str, ...]):  # type: ignore[no-untyped-def]
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=evidence_ids,
        rationale="because the evidence says so",
        reasoner=AI,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=AT,
    )


def create_address(
    judgment_id: str,
    evidence_id: str,
    *,
    scope: tuple[str, ...] = (SCOPE,),
    subject: str = "Refund window",
    facet: str = "How long?",
) -> SemanticJudgment:
    return judgment(
        judgment_id,
        CreateAddressProposal(
            candidate=SemanticCandidate(
                candidate_id=f"CAND-{judgment_id}",
                subject=subject,
                facet=facet,
                scope=scope,
                evidence_ids=(evidence_id,),
            )
        ),
        (evidence_id,),
    )


def assert_claim(
    judgment_id: str,
    address_id: str,
    evidence_id: str,
    *,
    text: str = "thirty days",
    authority: Authority = Authority.INFERRED,
    undecided: bool = False,
) -> SemanticJudgment:
    value = (
        ClaimValue(kind=ClaimValueKind.UNDECIDED)
        if undecided
        else ClaimValue(kind=ClaimValueKind.TEXT, text=text)
    )
    return judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="refund_window",
            value=value,
            evidence_ids=(evidence_id,),
            authority=authority,
        ),
        (evidence_id,),
    )


def authority_record(
    object_id: str = "AUTH-1",
    *,
    scope: tuple[str, ...] = (SCOPE,),
    actor: str = HUMAN_ACTOR,
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
    authority: Authority = Authority.CANONICAL,
) -> AuthorityRecord:
    return AuthorityRecord(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        lifecycle=lifecycle,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=AT,
        scope=scope,
        subject_id="intent",
        authorized_by=actor,
        rationale="alice owns payments",
    )


def existing_requirement(
    object_id: str,
    *,
    statement: str = "Refunds within thirty days.",
    scope: tuple[str, ...] = (SCOPE,),
    authority: Authority = Authority.PROPOSED,
    basis_claim_ids: tuple[str, ...] = (),
    materiality: Materiality = Materiality.LOW,
) -> Requirement:
    return Requirement(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        confidence=0.5,
        provenance=PROVENANCE,
        created_at=AT,
        scope=scope,
        statement=statement,
        materiality=materiality,
        requires_metric=False,
        requires_verification=False,
        relations=tuple(
            Relation(relation_type=RelationType.DERIVED_FROM, target_id=cid)
            for cid in basis_claim_ids
        ),
    )


# --- canonical scenarios ---------------------------------------------------------------

ADDR_JDG = "J-addr"
CLAIM_JDG = "J-claim"
ADDRESS = address_id_for(PROJECT, ADDR_JDG)
CLAIM = claim_id_for(PROJECT, CLAIM_JDG)


def eligible_ledger(
    *,
    evidence_kind: SourceKind = SourceKind.DOCUMENT,
    claim_authority: Authority = Authority.INFERRED,
    address_scope: tuple[str, ...] = (SCOPE,),
) -> Ledger:
    """One address, one live CLAIMED claim in ``SCOPE``. The ordinary eligible case."""
    ledger = Ledger()
    ledger.ingest("EV-1", evidence_kind)
    ledger.apply(create_address(ADDR_JDG, "EV-1", scope=address_scope))
    ledger.apply(assert_claim(CLAIM_JDG, ADDRESS, "EV-1", authority=claim_authority))
    return ledger
