"""The IE3 Intent Graph certification exam: scenarios, deterministic scoring, evidence capture.

Test-only, and deliberately a sibling of ``_intent_synthesis_exam`` rather than a parallel
system. It reuses that exam's substrate builders, ``CallEvidence``, ``ExamFailure`` and
refund-window markers, and ``_certification_run``'s contestant, recording provider, failure
taxonomy, guard check and measurement writer. The acceptance rule is the existing one
(MR4/MR6): **every case must pass every one of its three independent runs**. There is no
threshold, and a model is never certified because most attempts passed.

Every attempt drives the real production path: real semantic substrate, the Slice 3 context
compiler, ``synthesize_intent_graph`` with its forward IE2 laws and durable reducer, the shared
Model Runtime, and the Slice 4 graph adapter. The model proposes semantics; deterministic
Foundry remains authoritative. The model is never asked whether it answered correctly, its
confidence is never a pass criterion, and an answer Foundry refuses is a scored failure. Being
caught is not the same as being competent.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from typing import Any, Final, NoReturn

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_ID,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
    IntentGraphDraftPayload,
    ModelRuntimeIntentGraphSynthesizer,
    render_intent_graph_synthesis_request,
)
from foundry.application.intent_graph_synthesis import synthesize_intent_graph
from foundry.domain.common import Authority, LifecycleStatus, Relation, RelationType
from foundry.domain.events import DerivationPayload, EventEnvelope, EventType
from foundry.domain.gaps import GapKind
from foundry.domain.intent_graph import (
    BasisClaimRef,
    ExistingObjectRef,
    GraphNodeDisposition,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
)
from foundry.domain.intent_graph_state import IntentGraphDecisionRecord
from foundry.domain.intent_synthesis import IntentSynthesisRoute
from foundry.domain.semantic import Goal, NonGoal, SemanticKind
from foundry.domain.state import IntentState
from foundry.model_runtime.domain import ModelIdentity, ModelTask, ModelTier, ModelTraceContext
from foundry.model_runtime.errors import ModelProtocolError, ModelProviderError
from foundry.model_runtime.ports import ProviderExecutionResult
from foundry.model_runtime.runtime import ModelRuntime
from foundry.ports.intent_graph_synthesizer import IntentGraphSynthesisRequest
from tests.certification._certification_run import (
    Contestant,
    RecordingProvider,
    classify_execution_failure,
)
from tests.certification._intent_synthesis_exam import (
    AT,
    PROJECT,
    PROV,
    SCOPE,
    CallEvidence,
    ExamFailure,
    Substrate,
    _assert_claim,
    _create_address,
    _governor,
    _ingest,
    _intent_object,
    _project_authority,
    _record_object,
    _requirement,
    expresses_refund_window,
    state_of,
)

EXPECTED_GRAPH_POLICY_ID: Final = "intent-synthesis.graph-v1"
EXPECTED_GRAPH_POLICY_VERSION: Final = "intent-graph-synthesis-runtime-v1"
EXPECTED_GRAPH_PROMPT_SHA256: Final = (
    "265a7fbd0f9be4533bb256173d87e91f61ccd7f37b5983427d673127cf9ac176"
)
"""The contestant, frozen before any live call. A prompt edit breaks the exam, not the score."""

GRAPH_EVIDENCE_NAMESPACE: Final = "intent_graph_synthesis"
GRAPH_CASES: Final = ("A", "B", "C", "D", "E", "F", "G", "H")
GRAPH_RUNS_PER_CASE: Final = 3
"""The existing MR4/MR6 rule: three consecutive independent runs per case, every one passing."""

GRAPH_OUTPUT_GUARD: Final = 4000
GRAPH_TIMEOUT_SECONDS: Final = 180.0
"""Transport guards, predeclared before any live telemetry. A graph answer is larger than a
Slice-1 answer, so the Slice-1 guard is not reused blindly; the guard must stay non-binding
with at least 20% headroom (``assert_guard_was_not_binding``), or the run is INCOMPLETE."""

GOAL_ID: Final = "GOAL-refunds"
INTENT_ID: Final = "INTENT-payments"
SAME_THING: Final = "Refund requests are accepted within 30 days of purchase."

_DIGITAL = re.compile(r"digital", re.IGNORECASE)
_REFUND = re.compile(r"refund", re.IGNORECASE)
_ORIGINAL = re.compile(r"original", re.IGNORECASE)
_PAYMENT = re.compile(r"payment|card|method", re.IGNORECASE)


# --- observation --------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphObservation:
    """Everything one attempt produced, as data the scorers can be tested against."""

    case_id: str
    attempt: int
    request: IntentGraphSynthesisRequest | None
    raw_draft: IntentGraphDraftPayload | None
    result: IntentGraphSynthesisResult | None
    before: IntentState
    after: IntentState
    provider_calls: int
    evidence: CallEvidence | None
    governance_error: str | None
    record: IntentGraphDecisionRecord | None


def _fail(observation: GraphObservation, message: str) -> NoReturn:
    raise ExamFailure(f"[{observation.case_id} attempt {observation.attempt}] {message}")


class _GraphRecordingProvider(RecordingProvider):
    """``RecordingProvider`` that also keeps the request, so task and tier are observed."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)
        self.requests: list[Any] = []

    def execute(self, **kwargs: Any) -> ProviderExecutionResult[Any]:
        self.requests.append(kwargs["request"])
        return super().execute(**kwargs)


# --- one attempt through the production path ----------------------------------------------


def run_graph_attempt(
    contestant: Contestant, substrate: Substrate, case_id: str, attempt: int, *, provider: Any
) -> GraphObservation:
    """One call through the whole production path, with fresh everything.

    Execution failures are classified by the existing taxonomy (transport and harness limits
    are INCOMPLETE; protocol faults are NOT CERTIFIED). A Foundry refusal of the answer is
    recorded as ``governance_error`` for the scorer, never raised as a harness fault.
    """
    recording = _GraphRecordingProvider(provider)
    runtime = ModelRuntime(registry=contestant.registry(), providers=(recording,))
    traces = count(1)
    synthesizer = ModelRuntimeIntentGraphSynthesizer(
        runtime=runtime,
        model_identity=contestant.identity,
        trace_factory=lambda: ModelTraceContext(
            run_id=f"GRAPH-CERT-{case_id}-{attempt}", call_id=f"CALL-{next(traces)}"
        ),
        execution_constraints=contestant.constraints(),
    )
    run_id = f"GRAPH-RUN-{case_id}-{attempt}"
    holder: dict[str, Any] = {}

    class Capturing:
        """Records the exact request and result, before Foundry acts on them."""

        @property
        def fingerprint(self) -> Any:
            return synthesizer.fingerprint

        def synthesize(self, request: IntentGraphSynthesisRequest) -> IntentGraphSynthesisResult:
            holder["request"] = request
            produced = synthesizer.synthesize(request)
            holder["result"] = produced
            return produced

    before = state_of(substrate.store)
    error: str | None = None
    try:
        synthesize_intent_graph(
            substrate.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=Capturing(),
            clock=lambda: AT,
            synthesis_run_id_factory=lambda: run_id,
        )
    except (ModelProviderError, ModelProtocolError) as exc:
        classify_execution_failure(exc)
        raise  # unreachable; classify_execution_failure always raises
    except Exception as exc:  # noqa: BLE001 - a Foundry refusal is exam evidence
        error = f"{type(exc).__name__}: {exc}"

    after = state_of(substrate.store)
    metadata = recording.results[0] if recording.results else None
    sent = recording.requests[0] if recording.requests else None
    evidence = (
        CallEvidence(
            provider=metadata.identity.provider,
            model=metadata.identity.model,
            task=sent.task.value,
            tier=sent.tier.value,
            input_tokens=metadata.usage.input_tokens,
            output_tokens=metadata.usage.output_tokens,
            cost_usd=metadata.usage.cost_usd,
            wall_clock_ms=metadata.usage.wall_clock_ms,
            finish_reason=metadata.finish_reason,
        )
        if metadata is not None and sent is not None
        else None
    )
    graph_id = IntentGraphIdentity(project_id=PROJECT, synthesis_run_id=run_id).graph_instance_id
    raw = metadata.output if metadata is not None else None
    return GraphObservation(
        case_id=case_id,
        attempt=attempt,
        request=holder.get("request"),
        raw_draft=raw if isinstance(raw, IntentGraphDraftPayload) else None,
        result=holder.get("result"),
        before=before,
        after=after,
        provider_calls=recording.calls,
        evidence=evidence,
        governance_error=error,
        record=after.intent_graph_synthesis.decisions.get(graph_id),
    )


# --- global hard gates ---------------------------------------------------------------------


def score_graph_global_gates(observation: GraphObservation, *, candidate: ModelIdentity) -> None:
    """Applied to every live call, whatever the case expects. ``candidate`` has no default."""
    if observation.provider_calls != 1:
        _fail(
            observation,
            f"one synthesis must be one provider call, saw {observation.provider_calls}",
        )
    evidence = observation.evidence
    if evidence is None:
        _fail(observation, "missing provider execution evidence")
    if (evidence.provider, evidence.model) != (candidate.provider, candidate.model):
        _fail(observation, f"executed {evidence.provider}/{evidence.model}, not the candidate")
    if evidence.task != ModelTask.INTENT_GRAPH_SYNTHESIS.value:
        _fail(observation, f"task was {evidence.task}")
    if evidence.tier != ModelTier.REASONER.value:
        _fail(observation, f"tier was {evidence.tier}")
    if observation.governance_error is not None:
        _fail(observation, f"Foundry refused the answer: {observation.governance_error}")
    if observation.result is None or observation.request is None:
        _fail(observation, "no graph result was captured")
    record = observation.record
    if record is None:
        _fail(observation, "no durable graph decision was recorded")
    author = record.author
    if (author.provider, author.model) != (candidate.provider, candidate.model):
        _fail(observation, f"decision author is {author.provider}/{author.model}")
    if author.policy_version != EXPECTED_GRAPH_POLICY_VERSION:
        _fail(observation, f"author policy version is {author.policy_version!r}")
    if record.result != observation.result:
        _fail(observation, "the durable result differs from what the model returned")
    shown = {o.object_id: o for o in observation.request.known_objects}
    for ref in observation.result.unchanged_object_refs:
        if ref.object_id not in shown or shown[ref.object_id].is_stale:
            _fail(observation, f"witness {ref.object_id!r} was not shown fresh")


# --- per-case scoring helpers ---------------------------------------------------------------


def _nodes(observation: GraphObservation) -> tuple[Any, ...]:
    assert observation.result is not None
    return observation.result.nodes


def _text(node: Any) -> str:
    return str(getattr(node, "statement", None) or getattr(node, "mission", ""))


def _derives_from_claim(observation: GraphObservation, local_id: str, claim_id: str) -> bool:
    assert observation.result is not None
    return any(
        r.source.local_id == local_id
        and r.relation_type is RelationType.DERIVED_FROM
        and isinstance(r.target, BasisClaimRef)
        and r.target.claim_id == claim_id
        for r in observation.result.relations
    )


def _witnesses(observation: GraphObservation) -> tuple[str, ...]:
    assert observation.result is not None
    return tuple(r.object_id for r in observation.result.unchanged_object_refs)


def _route(observation: GraphObservation) -> IntentSynthesisRoute:
    assert observation.record is not None
    return observation.record.decision.route


def _require_route(observation: GraphObservation, route: IntentSynthesisRoute) -> None:
    if _route(observation) is not route:
        _fail(observation, f"expected route {route.value}, got {_route(observation).value}")


def _window_nodes(observation: GraphObservation, number: str) -> list[Any]:
    return [n for n in _nodes(observation) if expresses_refund_window(_text(n), number=number)]


def _mentions(observation: GraphObservation, object_id: str) -> bool:
    assert observation.result is not None
    return object_id in observation.result.model_dump_json()


# --- per-case scorers -----------------------------------------------------------------------


def _score_new(observation: GraphObservation, claim_id: str) -> None:
    if _witnesses(observation):
        _fail(observation, f"invented an existing-object witness: {_witnesses(observation)}")
    _require_route(observation, IntentSynthesisRoute.APPLY)
    matching = [
        n
        for n in _window_nodes(observation, "thirty")
        if n.kind is SemanticKind.REQUIREMENT
        and _derives_from_claim(observation, n.local_id.local_id, claim_id)
    ]
    if not matching:
        _fail(observation, "no new Requirement grounded on the claim expresses the refund window")
    assert observation.record is not None and observation.record.compiled is not None
    minted = {o.id for o in observation.record.compiled.objects}
    if not minted <= set(observation.after.objects):
        _fail(observation, "compiled objects did not become durable")


def score_case_a(observation: GraphObservation, substrate: Substrate) -> None:
    _score_new(observation, substrate.claim_ids["refund"])


def score_case_b(observation: GraphObservation, substrate: Substrate) -> None:
    assert observation.result is not None and observation.record is not None
    result = observation.result
    if result.nodes or result.relations or result.gaps:
        _fail(
            observation,
            f"expected a pure NO_CHANGE witness answer, got {len(result.nodes)} node(s), "
            f"{len(result.relations)} relation(s), {len(result.gaps)} gap(s)",
        )
    if _witnesses(observation) != ("REQ-existing",):
        _fail(
            observation,
            "unchanged_object_refs must be exactly ('REQ-existing',), "
            f"got {_witnesses(observation)}",
        )
    _require_route(observation, IntentSynthesisRoute.NO_CHANGE)
    record = observation.record
    if record.decision.reasons != ("EXISTING_UNCHANGED",):
        _fail(observation, f"reasons were {record.decision.reasons}")
    if record.compiled is not None or record.node_assignments:
        _fail(observation, "NO_CHANGE carried a compiled graph or assignments")
    before, after = observation.before, observation.after
    if (
        dict(after.objects) != dict(before.objects)
        or after.semantic.derivations != before.semantic.derivations
        or dict(after.gaps) != dict(before.gaps)
        or after.intent_synthesis.retirements != before.intent_synthesis.retirements
    ):
        _fail(observation, "NO_CHANGE changed durable graph state")


def score_case_c(observation: GraphObservation, substrate: Substrate) -> None:
    if "REQ-old" in _witnesses(observation):
        _fail(observation, "declared the genuinely changed object unchanged")
    _require_route(observation, IntentSynthesisRoute.APPLY)
    replacing = [
        n
        for n in _nodes(observation)
        if n.disposition is GraphNodeDisposition.REPLACES_STALE
        and n.replaces is not None
        and n.replaces.object_id == "REQ-old"
    ]
    if len(replacing) != 1:
        _fail(
            observation,
            f"expected exactly one REPLACES_STALE node replacing 'REQ-old', got {len(replacing)}",
        )
    (node,) = replacing
    if node.kind is not SemanticKind.REQUIREMENT or not expresses_refund_window(
        _text(node), number="fourteen"
    ):
        _fail(
            observation,
            f"the replacement does not express the fourteen-day window: {_text(node)!r}",
        )
    if not _derives_from_claim(
        observation, node.local_id.local_id, substrate.claim_ids["corrected"]
    ):
        _fail(observation, "the replacement is not grounded on the corrected claim")
    if _window_nodes(observation, "thirty"):
        _fail(observation, "kept the superseded thirty-day window alive in a new node")
    retired = [r.retired_object_id for r in observation.after.intent_synthesis.retirements]
    if (
        "REQ-old" not in retired
        or observation.after.objects["REQ-old"].lifecycle is not LifecycleStatus.SUPERSEDED
    ):
        _fail(observation, "the changed object was not durably retired")


def score_case_d(observation: GraphObservation, substrate: Substrate) -> None:
    for number in ("seven", "thirty"):
        invented = _window_nodes(observation, number)
        if invented:
            _fail(observation, f"invented a choice: {_text(invented[0])!r}")
    assert observation.result is not None
    if not observation.result.gaps:
        _fail(observation, "expected at least one gap for the unresolved window")
    if _witnesses(observation):
        _fail(observation, f"declared unresolved intent unchanged: {_witnesses(observation)}")
    _require_route(observation, IntentSynthesisRoute.APPLY)
    durable = [g for g in observation.after.gaps.values() if g.id not in observation.before.gaps]
    if not durable or any(g.blocking is not True for g in durable):
        _fail(observation, "the unresolved window did not become a durable blocking gap")


def score_case_e(observation: GraphObservation, substrate: Substrate) -> None:
    assert observation.request is not None
    if "REQ-hidden" in observation.request.model_dump_json():
        raise AssertionError("EXAM INTEGRITY: the hidden object reached the request")
    if _mentions(observation, "REQ-hidden"):
        _fail(observation, "referenced an object that was never shown")
    if _route(observation) is IntentSynthesisRoute.NO_CHANGE:
        _fail(observation, "claimed NO_CHANGE with nothing visible representing the claim")
    _score_new(observation, substrate.claim_ids["refund"])


def score_case_f(observation: GraphObservation, substrate: Substrate) -> None:
    if "REQ-stale" in _witnesses(observation):
        _fail(observation, "declared a stale object unchanged")
    if _mentions(observation, "REQ-dead"):
        _fail(observation, "referenced a non-current object that was never shown")
    _require_route(observation, IntentSynthesisRoute.APPLY)
    replacing = [
        n
        for n in _nodes(observation)
        if n.disposition is GraphNodeDisposition.REPLACES_STALE
        and n.replaces is not None
        and n.replaces.object_id == "REQ-stale"
    ]
    assert observation.result is not None
    if replacing:
        (node,) = replacing
        if not expresses_refund_window(_text(node), number="thirty") or not _derives_from_claim(
            observation, node.local_id.local_id, substrate.claim_ids["restated"]
        ):
            _fail(observation, "the replacement lost the window or its current basis")
    elif not observation.result.gaps:
        _fail(observation, "the stale object 'REQ-stale' was neither replaced nor raised as a gap")


def score_case_g(observation: GraphObservation, substrate: Substrate) -> None:
    excluded = [
        n for n in _nodes(observation) if _DIGITAL.search(_text(n)) and _REFUND.search(_text(n))
    ]
    if excluded:
        _fail(observation, f"proposed a node the shown NonGoal excludes: {_text(excluded[0])!r}")
    if "NG-digital" in _witnesses(observation):
        _fail(observation, "declared the conflicting NonGoal an unchanged witness")
    assert observation.result is not None
    contradictions = [
        g
        for g in observation.result.gaps
        if g.kind is GapKind.CONTRADICTION
        and ExistingObjectRef(object_id="NG-digital") in g.anchors
    ]
    if not contradictions:
        _fail(observation, "expected a CONTRADICTION gap anchored to 'NG-digital'")
    _require_route(observation, IntentSynthesisRoute.APPLY)


def score_case_h(observation: GraphObservation, substrate: Substrate) -> None:
    if _witnesses(observation) != ("REQ-existing",):
        _fail(
            observation,
            "unchanged_object_refs must be exactly ('REQ-existing',), "
            f"got {_witnesses(observation)}",
        )
    duplicates = _window_nodes(observation, "thirty")
    if duplicates:
        _fail(
            observation,
            f"duplicated the already-represented refund window: {_text(duplicates[0])!r}",
        )
    new = [
        n
        for n in _nodes(observation)
        if n.kind is SemanticKind.REQUIREMENT
        and _ORIGINAL.search(_text(n))
        and _PAYMENT.search(_text(n))
        and _derives_from_claim(observation, n.local_id.local_id, substrate.claim_ids["payment"])
    ]
    if not new:
        _fail(observation, "no new Requirement grounded on the payment claim expresses it")
    _require_route(observation, IntentSynthesisRoute.APPLY)
    assert observation.record is not None and observation.record.compiled is not None
    if "REQ-existing" in {o.id for o in observation.record.compiled.objects}:
        _fail(observation, "the compiler minted the witness")
    if observation.after.objects["REQ-existing"] != observation.before.objects["REQ-existing"]:
        _fail(observation, "the witness was changed")


SCORERS: Final[dict[str, Callable[[GraphObservation, Substrate], None]]] = {
    "A": score_case_a,
    "B": score_case_b,
    "C": score_case_c,
    "D": score_case_d,
    "E": score_case_e,
    "F": score_case_f,
    "G": score_case_g,
    "H": score_case_h,
}


def score_graph_attempt(
    observation: GraphObservation, substrate: Substrate, *, candidate: ModelIdentity
) -> None:
    score_graph_global_gates(observation, candidate=candidate)
    SCORERS[observation.case_id](observation, substrate)


# --- substrates -----------------------------------------------------------------------------


def _goal() -> Goal:
    return Goal(
        id=GOAL_ID,
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROV,
        created_at=AT,
        scope=(SCOPE,),
        statement="Refunds are handled fairly and predictably.",
        relations=(Relation(relation_type=RelationType.SERVES, target_id=INTENT_ID),),
    )


def _base(
    evidence: str, claim_text: str, *, subject: str = "Refund window"
) -> tuple[Substrate, str]:
    from foundry.adapters.memory.event_store import InMemoryEventStore

    store = InMemoryEventStore()
    governor = _governor(store)
    _ingest(governor, "EV-1", evidence)
    address = _create_address(governor, "J-addr", "EV-1", subject=subject)
    claim = _assert_claim(governor, "J-claim", address, "EV-1", claim_text)
    _record_object(store, _intent_object(), EventType.SEMANTIC_OBJECT_RECORDED)
    _record_object(store, _goal(), EventType.SEMANTIC_OBJECT_RECORDED)
    return Substrate(store=store, governor=governor), claim


def _stale_edge(substrate: Substrate, child_id: str, judgment_id: str) -> None:
    substrate.store.append(
        EventEnvelope(
            event_id=f"derivation-{child_id}",
            project_id=PROJECT,
            event_type=EventType.DERIVATION_RECORDED,
            occurred_at=AT,
            payload=DerivationPayload(child_id=child_id, parent_id=judgment_id),
        ),
        expected_sequence=substrate.store.current_sequence(PROJECT),
    )


def build_graph_case_a() -> Substrate:
    """NEW: one clear claim, and nothing visible that already expresses it."""
    substrate, claim = _base(
        "Refunds must complete within thirty calendar days after approval.",
        "thirty calendar days after approval",
    )
    substrate.claim_ids["refund"] = claim
    return substrate


def _same_thing_substrate(*, hidden: bool = False) -> Substrate:
    substrate, claim = _base(
        "Customers can ask for a refund up to thirty days after they buy.",
        "refund requests may be made up to thirty days after purchase",
    )
    existing = _requirement("REQ-existing", SAME_THING, basis_claim_ids=(claim,))
    if hidden:
        existing = existing.model_copy(update={"id": "REQ-hidden", "scope": ("elsewhere",)})
    _record_object(substrate.store, existing, EventType.REQUIREMENT_CANONICALIZED)
    substrate.claim_ids["refund"] = claim
    substrate.object_ids["existing"] = existing.id
    return substrate


def build_graph_case_b() -> Substrate:
    """SAME THING: a current, fresh Requirement already says what the claim says."""
    return _same_thing_substrate()


def build_graph_case_c() -> Substrate:
    """REAL CHANGE: the thirty-day basis was corrected to fourteen days."""
    substrate, old = _base(
        "Refunds must complete within thirty calendar days.", "thirty calendar days"
    )
    stale = _requirement("REQ-old", SAME_THING, basis_claim_ids=(old,))
    _record_object(substrate.store, stale, EventType.REQUIREMENT_CANONICALIZED)
    _stale_edge(substrate, "REQ-old", "J-claim")
    substrate.governor.record_authority(_project_authority())
    _ingest(substrate.governor, "EV-2", "Refunds must complete within fourteen calendar days.")
    address = state_of(substrate.store).semantic.claims[old].address_id
    corrected = _assert_claim(
        substrate.governor, "J-new", address, "EV-2", "fourteen calendar days"
    )
    _supersede(substrate, "J-sup", "J-claim", "EV-2")
    substrate.claim_ids.update(old=old, corrected=corrected)
    return substrate


def _supersede(substrate: Substrate, judgment_id: str, target: str, evidence_id: str) -> None:
    from foundry.domain.semantic_judgment import AdmissionRoute, SupersedeProposal
    from tests.certification._intent_synthesis_exam import ALICE, _judgment

    decision = substrate.governor.submit(
        _judgment(
            judgment_id,
            SupersedeProposal(target_judgment_id=target, reason="corrected"),
            (evidence_id,),
        ),
        human_actor_id=ALICE,
    )
    assert decision.route is AdmissionRoute.APPLY


def build_graph_case_d() -> Substrate:
    """GAP: two live claims of equal standing, seven days and thirty days."""
    substrate, seven = _base(
        "Refunds must complete within seven calendar days.", "seven calendar days"
    )
    _ingest(substrate.governor, "EV-2", "Refunds must complete within thirty calendar days.")
    address = state_of(substrate.store).semantic.claims[seven].address_id
    thirty = _assert_claim(substrate.governor, "J-thirty", address, "EV-2", "thirty calendar days")
    substrate.claim_ids.update(seven=seven, thirty=thirty)
    return substrate


def build_graph_case_e() -> Substrate:
    """INVISIBLE: the same meaning exists, but only in another scope the model never sees."""
    return _same_thing_substrate(hidden=True)


def build_graph_case_f() -> Substrate:
    """STALE: a stale object says the same thing as a restated current claim; a dead one too."""
    substrate, old = _base(
        "Customers may request a refund within thirty days of purchase.",
        "thirty days of purchase",
    )
    stale = _requirement("REQ-stale", SAME_THING, basis_claim_ids=(old,))
    _record_object(substrate.store, stale, EventType.REQUIREMENT_CANONICALIZED)
    _stale_edge(substrate, "REQ-stale", "J-claim")
    dead = _requirement("REQ-dead", SAME_THING, basis_claim_ids=()).model_copy(
        update={"authority": Authority.SUPERSEDED}
    )
    _record_object(substrate.store, dead, EventType.REQUIREMENT_CANONICALIZED)
    substrate.governor.record_authority(_project_authority())
    _ingest(
        substrate.governor, "EV-2", "Refund requests are accepted up to thirty days after purchase."
    )
    address = state_of(substrate.store).semantic.claims[old].address_id
    restated = _assert_claim(
        substrate.governor, "J-new", address, "EV-2", "thirty days after purchase"
    )
    _supersede(substrate, "J-sup", "J-claim", "EV-2")
    substrate.claim_ids.update(old=old, restated=restated)
    return substrate


def build_graph_case_g() -> Substrate:
    """CONTRADICTION: a shown NonGoal excludes what the claim would have the project do."""
    substrate, claim = _base(
        "Customers may refund digital download purchases within thirty days.",
        "digital downloads may be refunded within thirty days",
        subject="Digital download refunds",
    )
    non_goal = NonGoal(
        id="NG-digital",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=PROV,
        created_at=AT,
        scope=(SCOPE,),
        statement="We will not offer refunds for digital downloads.",
        relations=(Relation(relation_type=RelationType.SERVES, target_id=INTENT_ID),),
    )
    _record_object(substrate.store, non_goal, EventType.SEMANTIC_OBJECT_RECORDED)
    substrate.claim_ids["digital"] = claim
    return substrate


def build_graph_case_h() -> Substrate:
    """MIXED: the window is already represented; the payment method is genuinely new."""
    substrate = _same_thing_substrate()
    _ingest(
        substrate.governor, "EV-2", "Refunds are always paid back to the original payment method."
    )
    address = _create_address(
        substrate.governor,
        "J-addr2",
        "EV-2",
        subject="Refund payment method",
        facet="Where are refunds paid?",
    )
    payment = _assert_claim(
        substrate.governor,
        "J-pay",
        address,
        "EV-2",
        "refunds are paid to the original payment method",
    )
    substrate.claim_ids.update(window=substrate.claim_ids["refund"], payment=payment)
    return substrate


GRAPH_BUILDERS: Final[dict[str, Callable[[], Substrate]]] = {
    "A": build_graph_case_a,
    "B": build_graph_case_b,
    "C": build_graph_case_c,
    "D": build_graph_case_d,
    "E": build_graph_case_e,
    "F": build_graph_case_f,
    "G": build_graph_case_g,
    "H": build_graph_case_h,
}


# --- evidence ----------------------------------------------------------------------------------


def attempt_evidence(
    observation: GraphObservation, *, verdict: str, failure: str | None
) -> dict[str, Any]:
    """Every input and output of one attempt, as data. Unknown telemetry stays null."""
    record = observation.record
    evidence = observation.evidence
    return {
        "case": observation.case_id,
        "attempt": observation.attempt,
        "request_json": (
            render_intent_graph_synthesis_request(observation.request)
            if observation.request
            else None
        ),
        "raw_draft": observation.raw_draft.model_dump(mode="json")
        if observation.raw_draft
        else None,
        "result": observation.result.model_dump(mode="json") if observation.result else None,
        "governance_error": observation.governance_error,
        "route": record.decision.route.value if record else None,
        "reasons": list(record.decision.reasons) if record else None,
        "compiled_object_ids": (
            [o.id for o in record.compiled.objects] if record and record.compiled else []
        ),
        "provider": evidence.provider if evidence else None,
        "model": evidence.model if evidence else None,
        "task": evidence.task if evidence else None,
        "tier": evidence.tier if evidence else None,
        "input_tokens": evidence.input_tokens if evidence else None,
        "output_tokens": evidence.output_tokens if evidence else None,
        "cost_usd": evidence.cost_usd if evidence else None,
        "wall_clock_ms": evidence.wall_clock_ms if evidence else None,
        "finish_reason": evidence.finish_reason if evidence else None,
        "outcome": record.decision.route.value if record else "REFUSED",
        "verdict": verdict,
        "failure": failure,
    }


def write_graph_ledger(contestant: Contestant, case_id: str, substrate: Substrate) -> None:
    """Preserve a genuinely model-authored event stream for the offline replay proof."""
    contestant.evidence_dir.mkdir(parents=True, exist_ok=True)
    (contestant.evidence_dir / f"case_{case_id.lower()}_ledger.json").write_text(
        json.dumps(
            [
                {"sequence": s.sequence, "event": s.event.model_dump(mode="json")}
                for s in substrate.store.load(PROJECT)
            ],
            indent=2,
        )
    )


def production_base() -> str:
    """The commit whose ``src/`` the exam ran against; refuses to name a dirty source tree."""
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "src"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if dirty:
        raise AssertionError(f"EXAM INTEGRITY: src/ is modified; nothing can be pinned:\n{dirty}")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def write_graph_certification(
    contestant: Contestant, attempts: list[dict[str, Any]], *, frozen_production_base: str
) -> dict[str, Any]:
    """The verdict record. PASS only when every required attempt ran and passed."""
    required = len(GRAPH_CASES) * GRAPH_RUNS_PER_CASE
    passed = sum(1 for a in attempts if a["verdict"] == "PASS")
    payload: dict[str, Any] = {
        "candidate": contestant.label,
        "provider": contestant.identity.provider,
        "model": contestant.identity.model,
        "task": contestant.task.value,
        "tier": ModelTier.REASONER.value,
        "policy_id": GRAPH_SYNTHESIS_POLICY_ID,
        "policy_version": GRAPH_SYNTHESIS_POLICY_VERSION,
        "prompt_sha256": GRAPH_SYSTEM_INSTRUCTION_SHA256,
        "reasoning_effort": contestant.reasoning_effort,
        "constraints": contestant.constraints().model_dump(mode="json"),
        "frozen_production_base": frozen_production_base,
        "acceptance_rule": "every case passes all of its independent runs (MR4/MR6)",
        "cases": list(GRAPH_CASES),
        "runs_per_case": GRAPH_RUNS_PER_CASE,
        "required_attempts": required,
        "recorded_attempts": len(attempts),
        "passed_attempts": passed,
        "verdict": "PASS" if len(attempts) == required and passed == required else "NOT CERTIFIED",
        "attempts": attempts,
    }
    contestant.evidence_dir.mkdir(parents=True, exist_ok=True)
    (contestant.evidence_dir / "certification.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
    return payload


def certificate_binds(
    record: dict[str, Any],
    *,
    identity: ModelIdentity,
    task: ModelTask,
    policy_id: str,
    policy_version: str,
    prompt_sha256: str,
) -> bool:
    """Does ``record`` certify exactly this contestant? Fail-closed on any missing field.

    A record certifies one provider, model, task, policy and prompt digest together. Change
    any of them and the old record certifies nothing, rather than silently covering a system
    it never examined.
    """
    expected = {
        "verdict": "PASS",
        "provider": identity.provider,
        "model": identity.model,
        "task": task.value,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "prompt_sha256": prompt_sha256,
    }
    return all(record.get(key) == value for key, value in expected.items())
