"""Semantic governance service (Intent Intelligence v2, plan §8.1; spec §4, §20.1, §22).

``SemanticGovernor`` is the orchestration seam between evidence, semantic reasoners
and the event-sourced ledger. Three laws hold here without exception:

* **The reasoner never sees the store.** A ``SemanticReasoner`` receives a bounded
  ``ReasoningRequest`` and returns proposals; it is never handed an ``EventStore``,
  an ``IntentState`` or a view (Law 3: models are compute, not memory).
* **AI never mutates state.** A judgment becomes canonical only through
  ``submit``: the judgment is recorded as evidence, routed by the pure
  ``route_judgment`` over a freshly replayed state, and the resulting decision is
  recorded. Only the reducer, replaying an admission whose route is ``APPLY``,
  changes semantic state (spec §22.1, §22.11).
* **Every transition is an ``EventEnvelope``.** There is no second ledger and no
  in-memory shortcut: ``state()`` is always a replay of ``store.load(project_id)``.

Human trust boundary
--------------------
A judgment whose fingerprint claims to be human (``provider="human"``) is only
accepted when the caller passes an authenticated ``human_actor_id`` equal to the
fingerprint's actor id. A non-human judgment must not carry an actor. This is the
only place the "humans are authority" rule of admission can be reached, so the
governor — not the reasoner — is what asserts who is speaking.

Ledger hygiene
--------------
Before any event is appended it is reduced once, in isolation, over the current
replayed state. An event the reducer would refuse (duplicate evidence id, duplicate
judgment id, admission for an unknown judgment, ...) never reaches the store, so the
ledger stays replayable — the reducer's rules are the single source of what is
appendable; nothing is re-implemented here.

This is the ONLY module that turns a ``SemanticJudgment`` into an event.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.domain.admission import AdmissionDecision, AdmissionPolicy, route_judgment
from foundry.domain.events import (
    DerivationPayload,
    EventEnvelope,
    EventPayload,
    EventType,
    EvidencePayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    SemanticObjectPayload,
    StoredEvent,
)
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState
from foundry.ports.event_store import EventStore
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

_HUMAN_ACTOR_REQUIRED = "human fingerprint requires an authenticated actor"


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


class SemanticGovernor:
    def __init__(
        self,
        store: EventStore,
        project_id: str,
        policy: AdmissionPolicy,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._store = store
        self._project_id = project_id
        self._policy = policy
        self._clock = clock
        self._id_factory = id_factory or _default_id_factory

    @property
    def project_id(self) -> str:
        return self._project_id

    # --- reads -------------------------------------------------------------------

    def state(self) -> IntentState:
        """Replay of every stored event for this project. Never cached."""
        return replay(self._project_id, self._store.load(self._project_id))

    def view(self) -> CurrentSemanticView:
        return derive_view(self.state().semantic)

    # --- writes ------------------------------------------------------------------

    def ingest(self, evidence: EvidenceItem) -> StoredEvent:
        self._require_project(evidence.project_id, "evidence")
        return self._append(
            EventType.EVIDENCE_INGESTED, EvidencePayload(evidence=evidence), "evidence"
        )

    def submit(
        self, judgment: SemanticJudgment, *, human_actor_id: str | None = None
    ) -> AdmissionDecision:
        """Record a judgment, route it deterministically, record the decision.

        Returns the decision. Only an ``APPLY`` route, replayed through the reducer,
        changes semantic state; every other route leaves the proposal recorded and
        the interpretation untouched.
        """
        self._require_project(judgment.project_id, "judgment")
        self._require_actor(judgment, human_actor_id)
        recorded = self._append(
            EventType.SEMANTIC_JUDGMENT_RECORDED,
            SemanticJudgmentPayload(judgment=judgment),
            "judgment",
        )
        decision = route_judgment(self.state(), judgment, self._policy)
        self._append(
            EventType.SEMANTIC_ADMISSION_DECIDED,
            SemanticAdmissionPayload(
                judgment_id=decision.judgment_id,
                route=decision.route,
                reasons=decision.reasons,
                corroborating_judgment_ids=decision.corroborating_judgment_ids,
            ),
            "admission",
            causation_id=recorded.event.event_id,
        )
        return decision

    def derive(self, child_id: str, parent_id: str) -> StoredEvent:
        return self._append(
            EventType.DERIVATION_RECORDED,
            DerivationPayload(child_id=child_id, parent_id=parent_id),
            "derivation",
        )

    def propose_and_submit(
        self, reasoner: SemanticReasoner, request: ReasoningRequest
    ) -> tuple[AdmissionDecision, ...]:
        """Ask a non-human reasoner for proposals over a bounded request; submit each in order.

        The reasoner receives ``request`` and nothing else. Human authority never
        enters through this path: a human speaks through ``submit`` with an
        authenticated actor id. Every returned judgment must carry the reasoner's own
        fingerprint — identity is provenance and independence must not be spoofable —
        and the whole batch is checked before any of it is recorded.
        """
        if reasoner.fingerprint.is_human:
            raise ValueError("propose_and_submit accepts non-human reasoners only")
        self._require_project(request.project_id, "request")
        judgments = reasoner.propose(request)
        for judgment in judgments:
            if judgment.reasoner != reasoner.fingerprint:
                raise ValueError(
                    f"judgment {judgment.judgment_id} carries fingerprint "
                    f"{_fingerprint_text(judgment.reasoner)}, not the proposing reasoner's "
                    f"{_fingerprint_text(reasoner.fingerprint)}"
                )
        return tuple(self.submit(judgment) for judgment in judgments)

    def record_authority(self, record: AuthorityRecord) -> StoredEvent:
        """Record who owns a decision. This is how human authority enters the ledger."""
        self._require_project(record.project_id, "authority record")
        return self._append(
            EventType.SEMANTIC_OBJECT_RECORDED, SemanticObjectPayload(object=record), "authority"
        )

    # --- internals -----------------------------------------------------------------

    def _require_project(self, project_id: str, what: str) -> None:
        if project_id != self._project_id:
            raise ValueError(
                f"{what} belongs to project {project_id}, governor is for {self._project_id}"
            )

    @staticmethod
    def _require_actor(judgment: SemanticJudgment, human_actor_id: str | None) -> None:
        if judgment.reasoner.is_human:
            if human_actor_id is None or human_actor_id != judgment.reasoner.model:
                raise ValueError(_HUMAN_ACTOR_REQUIRED)
        elif human_actor_id is not None:
            raise ValueError("a non-human judgment must not carry a human actor")

    def _append(
        self,
        event_type: EventType,
        payload: EventPayload,
        prefix: str,
        *,
        causation_id: str | None = None,
    ) -> StoredEvent:
        expected_sequence = self._store.current_sequence(self._project_id)
        event = EventEnvelope(
            event_id=self._id_factory(prefix),
            project_id=self._project_id,
            event_type=event_type,
            occurred_at=self._clock(),
            causation_id=causation_id,
            payload=payload,
        )
        # Dry-run through the reducer so an unreplayable event never enters the ledger.
        reduce_event(self.state(), StoredEvent(sequence=expected_sequence + 1, event=event))
        return self._store.append(event, expected_sequence=expected_sequence)


def _fingerprint_text(fingerprint: ReasonerFingerprint) -> str:
    return f"{fingerprint.provider}:{fingerprint.model}@{fingerprint.policy_version}"
