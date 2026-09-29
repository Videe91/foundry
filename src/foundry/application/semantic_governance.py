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
from foundry.domain.authority import covering_authority_record
from foundry.domain.basis import assert_lawful_basis
from foundry.domain.common import Authority, SourceKind
from foundry.domain.events import (
    DerivationPayload,
    EventEnvelope,
    EventPayload,
    EventType,
    EvidencePayload,
    IntentObjectAdmissionPayload,
    SemanticAdmissionPayload,
    SemanticJudgmentPayload,
    SemanticObjectPayload,
    StoredEvent,
    StructuralRefusalPayload,
    derivation_parents_of,
)
from foundry.domain.evidence import EvidenceItem
from foundry.domain.graph_cycles import assert_no_cycle_introduced
from foundry.domain.intent_synthesis import INTENT_BEARING_SEMANTIC_KINDS
from foundry.domain.relation_legality import validate_relations
from foundry.domain.relevance import assert_relevant
from foundry.domain.semantic import AuthorityRecord, Constraint, ConstraintFacet, SemanticObject
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState
from foundry.domain.structural_refusal import StructuralRefusal
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

    def record_structural_refusal(self, refusal: StructuralRefusal) -> StoredEvent:
        """Append the audit record of one refused semantic-call attempt. It changes no state:
        nothing of the refused proposal is applied, and the record is never overwritten."""
        if refusal.reasoner.is_human:
            raise ValueError("structural refusals record non-human proposals only")
        return self._append(
            EventType.STRUCTURAL_REFUSAL_RECORDED,
            StructuralRefusalPayload(refusal=refusal),
            "REFUSAL",
        )

    def record_intent_object(
        self,
        obj: SemanticObject,
        *,
        author: ReasonerFingerprint,
        human_actor_id: str | None = None,
    ) -> StoredEvent:
        """Admit one intent-bearing object, as a single atomic durable transition.

        The forward-only seam for IE2 graph semantics. Everything refusable is refused
        here, before anything is appended, because a rejected admission must leave the
        ledger byte-identical rather than half-written.

        Authorship is a parameter, never inferred from ``obj.provenance``: provenance
        records where a fact came from and authorship records who asserted it, and reading
        one as the other is the laundering C9/I22 forbids. Human-versus-non-human is
        sufficient for this boundary; ``SynthesisOrigin`` stays in the synthesis subsystem
        where its four-way distinction has meaning.

        Legality is checked only on this path. Historical objects predate these rules and
        may carry relations IE2 would now refuse; validating during replay would make the
        log unreplayable, which is the property the model certifications rest on.
        """
        self._require_project(obj.project_id, "intent object")
        if obj.kind not in INTENT_BEARING_SEMANTIC_KINDS:
            raise ValueError(
                f"{obj.kind.value} is not an intent-bearing kind; this seam admits normative "
                "intent objects only"
            )
        self._require_author(obj, author, human_actor_id)
        if obj.id in self.state().objects:
            raise ValueError(
                f"{obj.id!r} already exists; admission creates and never revises, so "
                "supersession stays an explicit operation"
            )
        self._require_facet(obj)
        validate_relations(self.state(), obj)
        assert_no_cycle_introduced(self.state(), obj)
        if obj.authority is Authority.CANONICAL:
            # Non-canonical objects stay unconstrained: proposing before the basis is sound
            # is ordinary incremental work. Canonical intent must rest on a lawful basis.
            assert_lawful_basis(self.state(), obj)
            # IE2.2c: relevance is proved by explicit SERVES, per declared scope, and any
            # Decision the basis rests on must itself be applicable and relevant (R59).
            assert_relevant(self.state(), obj)

        # One definition of "this object's basis", shared with the event's own validator so
        # the seam and the contract cannot drift apart.
        parents = derivation_parents_of(obj)
        return self._append(
            EventType.INTENT_OBJECT_ADMITTED,
            IntentObjectAdmissionPayload(object=obj, author=author, derivation_parent_ids=parents),
            "intent object",
        )

    @staticmethod
    def _require_facet(obj: SemanticObject) -> None:
        """A canonical Constraint must say what can legitimately relax it.

        Optional on the model so historical constraints replay unchanged, required here so
        a new hard boundary cannot enter the graph without recording whether anyone inside
        the project may lift it.

        **What IE2.1 proves, exactly.** One structurally decidable rule:
        ``EXTERNAL_MANDATE`` may not carry ``SourceKind.HUMAN`` provenance, because a
        mandate the project wrote for itself is a project boundary wearing a stronger name.
        That check is sound on its own terms and is kept.

        **What IE2.1 does not prove.** It does *not* establish that non-``HUMAN``
        provenance is genuinely external. ``SYSTEM``, ``CODE``, ``TEST`` and ``RUNTIME`` are
        not external authorities, and treating them as such would invent a provenance
        ontology to make a check look stronger than it is. Nor does it verify that
        ``EXTERNAL_MANDATE`` carries a covering ``AuthorityRecord``, or that
        ``EVIDENCE_BOUND`` rests on a ``Claim``/``Evidence`` basis: both require the basis
        chain, which is IE2.2. The facet is *recorded and required* here; it is *proved* there.
        """
        if not isinstance(obj, Constraint) or obj.authority is not Authority.CANONICAL:
            return
        if obj.facet is None:
            raise ValueError(
                f"canonical constraint {obj.id!r} must declare a ConstraintFacet; a hard "
                "boundary with no stated relaxation rule is a junk drawer entry"
            )
        if (
            obj.facet is ConstraintFacet.EXTERNAL_MANDATE
            and obj.provenance.source_kind is SourceKind.HUMAN
        ):
            raise ValueError(
                f"constraint {obj.id!r} claims EXTERNAL_MANDATE but its provenance is a "
                "project human; an external mandate no project actor may waive cannot "
                "originate inside the project"
            )

    def _require_author(
        self,
        obj: SemanticObject,
        author: ReasonerFingerprint,
        human_actor_id: str | None,
    ) -> None:
        """Authorship and authority, checked before any append.

        A non-human may propose anything and canonicalize nothing. That is the whole
        boundary: a model may reason and propose, but authority is granted by a human who
        holds it, recorded where anyone can audit it.
        """
        if author.is_human:
            if human_actor_id is None or human_actor_id != author.model:
                raise ValueError(_HUMAN_ACTOR_REQUIRED)
        elif human_actor_id is not None:
            raise ValueError(
                "a non-human author must not carry an authenticated human actor id; "
                "authorship is not borrowed"
            )

        if obj.authority is not Authority.CANONICAL:
            return

        if not author.is_human:
            raise ValueError(
                f"{author.provider}/{author.model} may not author a CANONICAL object; "
                "certification grants compute, never authority"
            )
        if (
            covering_authority_record(
                self.state(), actor_id=author.model, target_scope=obj.scope or None
            )
            is None
        ):
            raise ValueError(
                f"no live AuthorityRecord covers {author.model} for scope {obj.scope}; "
                "canonical intent requires recorded human authority"
            )

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
