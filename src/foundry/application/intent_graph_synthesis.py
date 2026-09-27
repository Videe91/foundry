"""Offline Intent Graph synthesis orchestration (IE3 Slice 3; design §16; R103, R109).

    replay N → compile the bounded request → (blocker: a runtime gap, no call)
             → call the synthesizer EXACTLY ONCE → validate against that exact request
             → per-node origin (R109) → authority + whole-graph route
             → APPLY: compile + the unchanged forward IE2 laws over the whole graph
             → ONE INTENT_GRAPH_SYNTHESIS_DECIDED at expected_sequence = N

**One event, no window (R103).** The decision and its application are the same durable fact,
computed against sequence N and appended at N. There is no effect event and nothing to resume.

**The provider is called once per run, never on retry.** A ``ConcurrencyError`` means nothing
from this graph is durable. The retry reloads, recompiles the request from the new state and
re-validates the *same* result against it, then re-derives origins, re-routes and re-runs the
forward laws. It reuses the same run id, identity and deterministic event id. If the same answer
is no longer grounded in what the model would now be shown, the run fails with
``IntentGraphSynthesisSnapshotChanged``: a stale provider answer is never repaired or
reinterpreted, and the honest response is a new run. Three attempts in total.

**Duplicate adoption.** A ``DuplicateEventError`` means another worker landed this run's
deterministic event. If its durable body is this run's body, it is adopted. Otherwise the run
fails closed rather than disguising a collision as a completion.

The run outcome is an execution report, never truth: durable truth is the event store.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final

from foundry.application.intent_graph_synthesis_context import (
    IntentGraphResultError,
    compile_intent_graph_context,
    validate_graph_result,
)
from foundry.application.reducer import reduce_event
from foundry.application.replay import replay
from foundry.domain.common import FrozenModel, SourceKind
from foundry.domain.events import (
    EventEnvelope,
    EventType,
    GapPayload,
    IntentGraphSynthesisDecidedPayload,
    StoredEvent,
)
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import IntentGraphIdentity, IntentGraphSynthesisResult
from foundry.domain.intent_graph_compiler import (
    NodeAssignment,
    assert_compiled_graph_lawful,
    compile_intent_graph,
)
from foundry.domain.intent_graph_routing import derive_graph_origins, route_intent_graph
from foundry.domain.intent_graph_state import IntentGraphDecision, graph_decision_event_id
from foundry.domain.intent_synthesis import (
    IntentSynthesisRoute,
    synthesis_digest,
    validate_synthesis_actor,
)
from foundry.domain.intent_synthesis_gap import IntentSynthesisGap
from foundry.domain.semantic_judgment import ReasonerFingerprint
from foundry.domain.state import IntentState
from foundry.ports.event_store import ConcurrencyError, DuplicateEventError, EventStore
from foundry.ports.intent_graph_synthesizer import (
    IntentGraphSynthesisRequest,
    IntentGraphSynthesizer,
)

__all__ = [
    "CONTEXT_FAILURE_STEP",
    "GRAPH_SYNTHESIS_POLICY_VERSION",
    "MAX_GRAPH_SYNTHESIS_ATTEMPTS",
    "IntentGraphSynthesisConcurrencyExhausted",
    "IntentGraphSynthesisDuplicateConflict",
    "IntentGraphSynthesisRunOutcome",
    "IntentGraphSynthesisSnapshotChanged",
    "synthesize_intent_graph",
]

GRAPH_SYNTHESIS_POLICY_VERSION: Final = "intent-graph-synthesis-runtime-v2"
"""The only synthesizer policy accepted (§22). Slice-1 certification is not graph certification."""

MAX_GRAPH_SYNTHESIS_ATTEMPTS: Final = 3
CONTEXT_FAILURE_STEP: Final = "CONTEXT_FAILURE"


class IntentGraphSynthesisRunOutcome(FrozenModel):
    """What this run did. An execution report; the event store is the truth."""

    synthesis_run_id: str
    graph_instance_id: str | None = None
    decision: IntentGraphDecision | None = None
    deterministic_runtime_gap_ids: tuple[str, ...] = ()
    adopted: bool = False


class IntentGraphSynthesisSnapshotChanged(RuntimeError):
    """After concurrent writes the same answer is no longer grounded; start a new run."""


class IntentGraphSynthesisConcurrencyExhausted(RuntimeError):
    """Contention outlasted every attempt. Nothing from this run is durable."""


class IntentGraphSynthesisDuplicateConflict(RuntimeError):
    """This run's deterministic event id holds a different durable body. Fail closed."""


def _append(store: EventStore, state: IntentState, event: EventEnvelope) -> StoredEvent:
    """Dry-run through the reducer, then append at exactly the sequence decided against."""
    expected_sequence = state.last_sequence
    reduce_event(state, StoredEvent(sequence=expected_sequence + 1, event=event))
    return store.append(event, expected_sequence=expected_sequence)


def _context_failure_gap(
    identity: IntentGraphIdentity, scope: str, reason: str
) -> IntentSynthesisGap:
    return IntentSynthesisGap(
        id="GAP-" + synthesis_digest("ie3.context_failure", identity.graph_instance_id),
        project_id=identity.project_id,
        kind=GapKind.CONTEXT_FAILURE,
        description=f"graph synthesis context refused, never truncated: {reason}",
        affected_object_ids=(),
        blocking=True,
        scope=(scope,),
    )


def _decide(
    state: IntentState,
    request: IntentGraphSynthesisRequest,
    result: IntentGraphSynthesisResult,
    *,
    identity: IntentGraphIdentity,
    author: ReasonerFingerprint,
    human_actor_id: str | None,
    at: datetime,
) -> EventEnvelope:
    """Everything from validation to the event, computed against ``state`` alone."""
    visibility = validate_graph_result(result, request, author_is_human=author.is_human)
    claim_source_kinds: dict[str, tuple[SourceKind, ...]] = {
        claim.claim_id: claim.source_kinds for locus in request.basis for claim in locus.live_claims
    }
    origins = derive_graph_origins(
        result, claim_source_kinds=claim_source_kinds, author_is_human=author.is_human
    )
    routing = route_intent_graph(
        state,
        result=result,
        origins=origins,
        author=author,
        human_actor_id=human_actor_id,
        run_scope=request.scope,
    )
    compiled = None
    if routing.decision.route is IntentSynthesisRoute.APPLY:
        assignments = {}
        for assignment in routing.node_assignments:
            assert assignment.authority is not None  # APPLY assigns every node
            assignments[assignment.local_id] = NodeAssignment(
                origin=assignment.origin, authority=assignment.authority
            )
        compiled = compile_intent_graph(
            result,
            visibility,
            identity=identity,
            author=author,
            decided_at=at,
            decision_event_id=graph_decision_event_id(identity),
            assignments=assignments,
        )
        assert_compiled_graph_lawful(state, compiled)
    return EventEnvelope(
        event_id=graph_decision_event_id(identity),
        project_id=identity.project_id,
        event_type=EventType.INTENT_GRAPH_SYNTHESIS_DECIDED,
        occurred_at=at,
        correlation_id=identity.synthesis_run_id,
        payload=IntentGraphSynthesisDecidedPayload(
            identity=identity,
            author=author,
            run_scope=request.scope,
            result=result,
            node_assignments=routing.node_assignments,
            decision=routing.decision,
            compiled=compiled,
        ),
    )


def _adopt(
    store: EventStore,
    identity: IntentGraphIdentity,
    event: EventEnvelope,
) -> IntentGraphSynthesisRunOutcome:
    state = replay(identity.project_id, store.load(identity.project_id))
    record = state.intent_graph_synthesis.decisions.get(identity.graph_instance_id)
    payload = event.payload
    assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
    if (
        record is None
        or record.decision_event_id != event.event_id
        or record.result != payload.result
        or record.author != payload.author
        or record.run_scope != payload.run_scope
    ):
        raise IntentGraphSynthesisDuplicateConflict(
            f"event {event.event_id!r} is durable with a different body; not adopted"
        )
    return IntentGraphSynthesisRunOutcome(
        synthesis_run_id=identity.synthesis_run_id,
        graph_instance_id=identity.graph_instance_id,
        decision=record.decision,
        adopted=True,
    )


def synthesize_intent_graph(
    store: EventStore,
    *,
    project_id: str,
    scope: str,
    synthesizer: IntentGraphSynthesizer,
    clock: Callable[[], datetime],
    synthesis_run_id_factory: Callable[[], str],
    human_actor_id: str | None = None,
) -> IntentGraphSynthesisRunOutcome:
    """Run one governed graph synthesis pass over ``scope``. See the module docstring."""
    author = synthesizer.fingerprint
    if author.policy_version != GRAPH_SYNTHESIS_POLICY_VERSION:
        raise ValueError(
            f"synthesizer policy {author.policy_version!r} is not "
            f"{GRAPH_SYNTHESIS_POLICY_VERSION!r}; no other certification covers graph synthesis"
        )
    validate_synthesis_actor(author, human_actor_id)
    synthesis_run_id = synthesis_run_id_factory()
    if not synthesis_run_id:
        raise ValueError("synthesis_run_id_factory must return a non-empty id")
    identity = IntentGraphIdentity(project_id=project_id, synthesis_run_id=synthesis_run_id)

    state = replay(project_id, store.load(project_id))
    context = compile_intent_graph_context(state, scope=scope)
    if context.context_failure is not None:
        gap = _context_failure_gap(identity, scope, context.context_failure)
        _append(
            store,
            state,
            EventEnvelope(
                event_id=identity.event_id(CONTEXT_FAILURE_STEP),
                project_id=project_id,
                event_type=EventType.GAP_RECORDED,
                occurred_at=clock(),
                correlation_id=synthesis_run_id,
                payload=GapPayload(gap=gap),
            ),
        )
        return IntentGraphSynthesisRunOutcome(
            synthesis_run_id=synthesis_run_id, deterministic_runtime_gap_ids=(gap.id,)
        )
    request = context.request
    if request is None:
        return IntentGraphSynthesisRunOutcome(synthesis_run_id=synthesis_run_id)

    result = synthesizer.synthesize(request)

    # The first decision's refusals are the answer's own defects and propagate as they are.
    event = _decide(
        state,
        request,
        result,
        identity=identity,
        author=author,
        human_actor_id=human_actor_id,
        at=clock(),
    )
    for attempt in range(1, MAX_GRAPH_SYNTHESIS_ATTEMPTS + 1):
        try:
            _append(store, state, event)
        except DuplicateEventError:
            return _adopt(store, identity, event)
        except ConcurrencyError:
            if attempt == MAX_GRAPH_SYNTHESIS_ATTEMPTS:
                raise IntentGraphSynthesisConcurrencyExhausted(
                    f"graph {identity.graph_instance_id} lost {attempt} append races"
                ) from None
            state = replay(project_id, store.load(project_id))
            fresh = compile_intent_graph_context(state, scope=scope)
            if fresh.request is None:
                raise IntentGraphSynthesisSnapshotChanged(
                    f"after concurrent writes nothing in scope {scope!r} can be shown"
                ) from None
            request = fresh.request
            try:
                event = _decide(
                    state,
                    request,
                    result,
                    identity=identity,
                    author=author,
                    human_actor_id=human_actor_id,
                    at=clock(),
                )
            except (IntentGraphResultError, ValueError) as exc:
                raise IntentGraphSynthesisSnapshotChanged(
                    f"the same answer is no longer grounded after concurrent writes: {exc}"
                ) from exc
            continue
        payload = event.payload
        assert isinstance(payload, IntentGraphSynthesisDecidedPayload)
        return IntentGraphSynthesisRunOutcome(
            synthesis_run_id=synthesis_run_id,
            graph_instance_id=identity.graph_instance_id,
            decision=payload.decision,
        )
    raise AssertionError("unreachable: every attempt returns or raises")
