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
    GraphRef,
    IntentGraphIdentity,
    IntentGraphSynthesisResult,
    LocalNodeRef,
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
from tests.certification._exam_identity import canonical_digest, code_closure
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
from tests.certification._schema_identity import schema_sha256

EXPECTED_GRAPH_POLICY_ID: Final = "intent-synthesis.graph-v1"
EXPECTED_GRAPH_POLICY_VERSION: Final = "intent-graph-synthesis-runtime-v4"
EXPECTED_GRAPH_PROMPT_SHA256: Final = (
    "fd395605ecd12f39430a9bb0140bf1a3ce6dc43643859e94485a23970856a6e4"
)
"""The contestant, frozen before any live call. A prompt edit breaks the exam, not the score."""

EXPECTED_GRAPH_ANSWER_SCHEMA_SHA256: Final = (
    "6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494"
)
"""The canonical graph-answer schema the contestant is constrained by, frozen with the prompt."""

GRAPH_EVIDENCE_NAMESPACE: Final = "intent_graph_synthesis_exam_v5"
"""Where an exam-v5 certification's evidence is written. Never a historical namespace."""
HISTORICAL_V1_NAMESPACE: Final = "intent_graph_synthesis"
"""The first (NOT CERTIFIED, 4/24) run under runtime-v1. Immutable evidence; never written."""
HISTORICAL_V2_NAMESPACE: Final = "intent_graph_synthesis_v2"
"""The runtime-v2 runs recorded before schema binding: Grok NOT CERTIFIED (7/24) and Astra
INCOMPLETE (0/24, schema refused before inference). Immutable evidence; never written."""
HISTORICAL_SCHEMA_BOUND_NAMESPACE: Final = "intent_graph_synthesis_schema_bound"
"""Astra's first semantic run (NOT CERTIFIED, 21/24), under exam v1 whose case C joined two
different propositions. Immutable evidence; never written."""
HISTORICAL_EXAM_V2_NAMESPACE: Final = "intent_graph_synthesis_exam_bound"
"""Exam v2 under runtime-v2: Astra PASS 24/24 (superseded) and Grok's diagnostic NOT CERTIFIED
21/24, whose case A failures fall in the REQUIREMENT/CONSTRAINT dimension exam v2 left
unspecified. Immutable evidence; never written."""
HISTORICAL_EXAM_V3_NAMESPACE: Final = "intent_graph_synthesis_exam_v3"
"""Exam v3 under runtime-v3: Astra PASS 27/27 (superseded) and Grok NOT CERTIFIED 20/27 (F-1 a
genuine failure; F-2 a lawful reading of the ambiguous v3 case F). Immutable; never written."""
HISTORICAL_EXAM_V4_NAMESPACE: Final = "intent_graph_synthesis_exam_v4"
"""Exam v4 under runtime-v3: Astra, Claude Opus 5.5 and Claude Sonnet 5 PASS 27/27 (superseded),
Claude Fable 5.1 NOT CERTIFIED 23/27 (B-1 and B-2 gaps beside a resolved witness under an
ambiguous fixture and gap contract; F-1 a speculative gap beside a correct replacement) and Grok
NOT CERTIFIED 17/27 (10 INCOMPLETE, no semantic failure). Immutable; never written."""
HISTORICAL_GRAPH_NAMESPACES: Final = (
    HISTORICAL_V1_NAMESPACE,
    HISTORICAL_V2_NAMESPACE,
    HISTORICAL_SCHEMA_BOUND_NAMESPACE,
    HISTORICAL_EXAM_V2_NAMESPACE,
    HISTORICAL_EXAM_V3_NAMESPACE,
    HISTORICAL_EXAM_V4_NAMESPACE,
)

GRAPH_CERTIFICATION_RECORD_FORMAT: Final = "ie3-graph-certification.v3"
"""v3 binds the certification exam itself (id, version, deterministic exam hash) as well as
v2's answer-schema contract and v1's provider, model, task, policy and prompt.

It moved because exam v1's case C was defective: a certificate that does not name its exam
could be silently carried across a change in what the exam asks or accepts. Earlier formats are
historical and bind only under their own rules: v1 (no ``record_format``) records no schema or
exam identity, v2 records a schema identity but no exam identity. Nothing is ever fabricated
into them, and neither can bind an exam-bound identity, whatever its verdict."""
SCHEMA_BOUND_RECORD_FORMAT: Final = "ie3-graph-certification.v2"

GRAPH_EXAM_ID: Final = "ie3.intent-graph-synthesis.certification-exam"
GRAPH_EXAM_VERSION: Final = "5"
"""v1 (through 5e88489): case C joined two propositions. v2 (through 5ff8edf): case C corrected,
but the exam scored REQUIREMENT against CONSTRAINT that the runtime-v2 contract never defined,
case A's claim carried only a bare value, and no case required a CONSTRAINT. v3: every case A
claim states its proposition, and case I pairs a delivered-behaviour obligation (REQUIREMENT)
with a solution-space boundary (CONSTRAINT) in the same modality. v4: case F only; its restated
claim and address state the refund-request window, and its scorer requires exactly one
replacement of REQ-stale (no gap, no parallel node). v5 (runtime-v4): the shared B/E/H substrate
states the refund-request window on every visible field (its facet asked about refund duration),
case J adds one resolvable and one genuinely unresolved meaning, and every case's gaps are scored
by one rule (``graph_unresolved_work``, ``_require_gap_semantics``). See SUPERSEDED_GRAPH_EXAMS."""
EXPECTED_GRAPH_EXAM_SHA256: Final = (
    "b8fe070ebddb580721fb4b741d43d3da276b59e40e0ee5840fb13b37ce43a90d"
)
"""``graph_exam_sha256()``, pasted, never computed at import. A change to what the exam asks,
builds, scores or accepts fails the build until the version and this digest are reviewed."""
GRAPH_CASES: Final = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J")
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


def _require_witnesses(observation: GraphObservation, expected: tuple[str, ...]) -> None:
    """The one witness rule, applied by every scorer (R111, runtime-v2 clarification).

    A witness is an existing object that itself already represents a meaning a claim asserts.
    Each case predeclares exactly which objects qualify; a parent Intent, a served Goal, a
    conflicting NonGoal or any other context object never does.
    """
    if _witnesses(observation) != expected:
        _fail(
            observation,
            f"witness set (unchanged_object_refs) must be exactly {expected}, got "
            f"{_witnesses(observation)}; a witness must itself already represent the claim",
        )


def _require_route(observation: GraphObservation, route: IntentSynthesisRoute) -> None:
    if _route(observation) is not route:
        _fail(observation, f"expected route {route.value}, got {_route(observation).value}")


def _window_nodes(observation: GraphObservation, number: str) -> list[Any]:
    return [n for n in _nodes(observation) if expresses_refund_window(_text(n), number=number)]


def _mentions(observation: GraphObservation, object_id: str) -> bool:
    assert observation.result is not None
    return object_id in observation.result.model_dump_json()


# --- gap semantics: one rule for every case (exam v5, runtime-v4) ---------------------------


@dataclass(frozen=True)
class UnresolvedRegion:
    """A region of intent the case's material leaves genuinely open, as the shown ids (claims,
    objects) that make it up. A gap addresses the region when it anchors at least one of them."""

    ids: frozenset[str]
    kind: GapKind | None = None
    via: str | None = None
    """When set, only a gap of ``kind`` anchored to ``via`` covers the region."""


@dataclass(frozen=True)
class UnresolvedWork:
    """What a case resolves and what it leaves open, declared once and read by one rule.

    ``resolved`` holds the shown claims and objects whose meaning the case's material settles: a
    gap anchored to one restates doubt about a resolved meaning. Context objects (the Intent, a
    Goal) are in neither set and are neutral as extra anchors."""

    resolved: frozenset[str]
    regions: tuple[UnresolvedRegion, ...] = ()


def graph_unresolved_work(case_id: str, substrate: Substrate) -> UnresolvedWork:
    """Each case's unresolved semantic work, from its fixture's ids. No text is read."""
    c = substrate.claim_ids
    conflict = UnresolvedRegion(frozenset({c.get("seven", ""), c.get("thirty", "")}))
    declared: dict[str, Callable[[], UnresolvedWork]] = {
        "A": lambda: UnresolvedWork(frozenset({c["refund"]})),
        "B": lambda: UnresolvedWork(frozenset({c["refund"], "REQ-existing"})),
        "C": lambda: UnresolvedWork(frozenset({c["corrected"], "REQ-old"})),
        "D": lambda: UnresolvedWork(frozenset(), (conflict,)),
        "E": lambda: UnresolvedWork(frozenset({c["refund"]})),
        "F": lambda: UnresolvedWork(frozenset({c["restated"], "REQ-stale"})),
        "G": lambda: UnresolvedWork(
            frozenset(),
            (
                UnresolvedRegion(
                    frozenset({"NG-digital", c["digital"]}),
                    kind=GapKind.CONTRADICTION,
                    via="NG-digital",
                ),
            ),
        ),
        "H": lambda: UnresolvedWork(frozenset({c["window"], c["payment"], "REQ-existing"})),
        "I": lambda: UnresolvedWork(frozenset({c["obligation"], c["boundary"]})),
        "J": lambda: UnresolvedWork(frozenset({c["payment"]}), (conflict,)),
    }
    return declared[case_id]()


def _anchor_id(ref: GraphRef) -> str:
    if isinstance(ref, BasisClaimRef):
        return ref.claim_id
    if isinstance(ref, ExistingObjectRef):
        return ref.object_id
    assert isinstance(ref, LocalNodeRef)
    return f"local:{ref.local_id}"


def _resolved_ids(observation: GraphObservation, work: UnresolvedWork) -> set[str]:
    """The declared resolved ids, plus every new node that resolves one of them."""
    assert observation.result is not None
    resolved = set(work.resolved)
    for n in observation.result.nodes:
        grounded = any(
            _derives_from_claim(observation, n.local_id.local_id, claim) for claim in work.resolved
        )
        if grounded or (n.replaces is not None and n.replaces.object_id in work.resolved):
            resolved.add(f"local:{n.local_id.local_id}")
    return resolved


def _require_gap_semantics(observation: GraphObservation, work: UnresolvedWork) -> None:
    """A gap is accepted because unresolved work exists, and rejected because it does not.

    Every gap must anchor at least one id of a declared unresolved region and none of a meaning
    the case resolves; every declared region must be covered by a gap. A case with no unresolved
    region therefore admits no gap, and a mixed case admits exactly the gaps its open region
    needs. Graph references only; descriptions are never read."""
    assert observation.result is not None
    gaps = observation.result.gaps
    resolved = _resolved_ids(observation, work)
    open_ids = {i for region in work.regions for i in region.ids}
    for g in gaps:
        anchors = {_anchor_id(a) for a in g.anchors}
        duplicated = sorted(anchors & resolved)
        if duplicated:
            _fail(
                observation,
                f"gap {g.local_gap_id!r} anchors {duplicated}, whose meaning this case resolves; "
                "a resolved meaning takes no gap",
            )
        if not anchors & open_ids:
            _fail(
                observation,
                f"gap {g.local_gap_id!r} anchors no unresolved region of this case "
                f"(anchors {sorted(anchors)}); a gap must stand for unresolved work",
            )
    for region in work.regions:
        covering = [
            g
            for g in gaps
            if {_anchor_id(a) for a in g.anchors} & region.ids
            and (region.kind is None or g.kind is region.kind)
            and (region.via is None or region.via in {_anchor_id(a) for a in g.anchors})
        ]
        if not covering:
            expected = (
                f"; expected a {region.kind.value} gap anchored to {region.via!r}"
                if region.kind is not None
                else ""
            )
            _fail(
                observation,
                f"the unresolved region {sorted(region.ids)} has no gap{expected}",
            )


# --- per-case scorers -----------------------------------------------------------------------


def _score_new(observation: GraphObservation, claim_id: str) -> None:
    _require_witnesses(observation, ())
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
    if result.nodes or result.relations:
        _fail(
            observation,
            f"expected a pure NO_CHANGE witness answer, got {len(result.nodes)} node(s) and "
            f"{len(result.relations)} relation(s)",
        )
    _require_witnesses(observation, ("REQ-existing",))
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
    _require_witnesses(observation, ())
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
    _require_witnesses(observation, ())
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
    """Exactly one same-kind replacement of REQ-stale, grounded on the restatement.

    The fixture states one proposition everywhere, so nothing is left unresolved and the shared
    gap rule admits no gap (exam v5; exam v4 hard-coded it here). A NEW parallel node fails,
    whatever its rationale says. Graph semantics only.
    """
    _require_witnesses(observation, ())
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
    if len(replacing) != 1:
        _fail(
            observation,
            f"expected exactly one REPLACES_STALE node replacing 'REQ-stale', got {len(replacing)}",
        )
    (node,) = replacing
    if node.kind is not SemanticKind.REQUIREMENT:
        _fail(observation, f"REQ-stale is a REQUIREMENT; the replacement is {node.kind.value}")
    if not expresses_refund_window(_text(node), number="thirty") or not _derives_from_claim(
        observation, node.local_id.local_id, substrate.claim_ids["restated"]
    ):
        _fail(observation, "the replacement lost the window or its current basis")
    parallel = [n for n in _nodes(observation) if n is not node]
    if parallel:
        _fail(observation, f"{len(parallel)} parallel node(s) beside the replacement")
    retired = [r.retired_object_id for r in observation.after.intent_synthesis.retirements]
    if "REQ-stale" not in retired:
        _fail(observation, "the stale object was not durably retired")


def score_case_g(observation: GraphObservation, substrate: Substrate) -> None:
    excluded = [
        n for n in _nodes(observation) if _DIGITAL.search(_text(n)) and _REFUND.search(_text(n))
    ]
    if excluded:
        _fail(observation, f"proposed a node the shown NonGoal excludes: {_text(excluded[0])!r}")
    _require_witnesses(observation, ())
    _require_route(observation, IntentSynthesisRoute.APPLY)


def score_case_h(observation: GraphObservation, substrate: Substrate) -> None:
    _require_witnesses(observation, ("REQ-existing",))
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


_UK_HOSTED = re.compile(r"\bUK\b|United Kingdom", re.IGNORECASE)
_THIRTY_DAYS = re.compile(r"\b(30|thirty)\b.*\bday", re.IGNORECASE)


def score_case_i(observation: GraphObservation, substrate: Substrate) -> None:
    """Exactly one REQUIREMENT for the obligation and one CONSTRAINT for the boundary."""
    _require_witnesses(observation, ())
    _require_route(observation, IntentSynthesisRoute.APPLY)
    obligation, boundary = substrate.claim_ids["obligation"], substrate.claim_ids["boundary"]

    def grounded_on(claim_id: str) -> list[Any]:
        return [
            n
            for n in _nodes(observation)
            if _derives_from_claim(observation, n.local_id.local_id, claim_id)
        ]

    on_obligation, on_boundary = grounded_on(obligation), grounded_on(boundary)
    if [n.kind for n in on_obligation] != [SemanticKind.REQUIREMENT]:
        _fail(
            observation,
            "the delivered-behaviour obligation must be exactly one REQUIREMENT, got "
            f"{[n.kind.value for n in on_obligation]}",
        )
    if [n.kind for n in on_boundary] != [SemanticKind.CONSTRAINT]:
        _fail(
            observation,
            "the solution-space boundary must be exactly one CONSTRAINT, got "
            f"{[n.kind.value for n in on_boundary]}",
        )
    (requirement,), (constraint,) = on_obligation, on_boundary
    if requirement is constraint:
        _fail(observation, "one node cannot stand for both claims")
    if not _THIRTY_DAYS.search(_text(requirement)):
        _fail(observation, f"the REQUIREMENT lost the thirty-day limit: {_text(requirement)!r}")
    if not _UK_HOSTED.search(_text(constraint)):
        _fail(observation, f"the CONSTRAINT lost the UK-hosting boundary: {_text(constraint)!r}")
    assert observation.record is not None and observation.record.compiled is not None
    minted = {o.id for o in observation.record.compiled.objects}
    if not minted <= set(observation.after.objects):
        _fail(observation, "compiled objects did not become durable")


def score_case_j(observation: GraphObservation, substrate: Substrate) -> None:
    """MIXED WITH A GAP: the payment-method claim is resolved as NEW, the completion time is
    genuinely open (two conflicting claims). The shared rule covers both halves of the gap
    contract: a gap for the open region, none for the resolved one."""
    for number in ("seven", "thirty"):
        invented = _window_nodes(observation, number)
        if invented:
            _fail(observation, f"invented a choice: {_text(invented[0])!r}")
    _require_witnesses(observation, ())
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
    durable = [g for g in observation.after.gaps.values() if g.id not in observation.before.gaps]
    if not durable or any(g.blocking is not True for g in durable):
        _fail(observation, "the unresolved completion time did not become a durable blocking gap")
    assert observation.record is not None and observation.record.compiled is not None
    minted = {o.id for o in observation.record.compiled.objects}
    if not minted <= set(observation.after.objects):
        _fail(observation, "compiled objects did not become durable")


SCORERS: Final[dict[str, Callable[[GraphObservation, Substrate], None]]] = {
    "A": score_case_a,
    "B": score_case_b,
    "C": score_case_c,
    "D": score_case_d,
    "E": score_case_e,
    "F": score_case_f,
    "G": score_case_g,
    "H": score_case_h,
    "I": score_case_i,
    "J": score_case_j,
}


def score_graph_attempt(
    observation: GraphObservation, substrate: Substrate, *, candidate: ModelIdentity
) -> None:
    score_graph_global_gates(observation, candidate=candidate)
    _require_gap_semantics(observation, graph_unresolved_work(observation.case_id, substrate))
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
    evidence: str,
    claim_text: str,
    *,
    subject: str = "Refund window",
    facet: str = "How long may a refund take?",
    predicate: str = "refund_window",
) -> tuple[Substrate, str]:
    from foundry.adapters.memory.event_store import InMemoryEventStore

    store = InMemoryEventStore()
    governor = _governor(store)
    _ingest(governor, "EV-1", evidence)
    address = _create_address(governor, "J-addr", "EV-1", subject=subject, facet=facet)
    claim = _assert_claim(governor, "J-claim", address, "EV-1", claim_text, predicate=predicate)
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
    """NEW: one clear claim, and nothing visible that already expresses it.

    Exam v3: the claim states its whole proposition (a delivered-behaviour obligation). In v2
    it carried only "thirty calendar days after approval", and the evidence sentence never
    reaches a graph synthesizer (the port forbids evidence content).
    """
    substrate, claim = _base(
        "Refunds must complete within thirty calendar days after approval.",
        "refunds must complete within thirty calendar days after approval",
        subject="Refund completion time",
        predicate="refund_completion_time",
    )
    substrate.claim_ids["refund"] = claim
    return substrate


B_REQUEST_WINDOW_SUBJECT: Final = "Refund request window"
B_REQUEST_WINDOW_FACET: Final = "Within how many days of purchase may refund requests be made?"
B_EVIDENCE: Final = "Customers can ask for a refund up to thirty days after they buy."
B_CLAIM: Final = "refund requests may be made up to thirty days after purchase"


def _same_thing_substrate(*, hidden: bool = False) -> Substrate:
    """Exam v5: one proposition, the refund-request window, on every field a model sees.

    Subject, facet, predicate and claim value all state the request window, and REQ-existing
    says the same thing. Shared by B (SAME THING), E (INVISIBLE) and H (MIXED)."""
    substrate, claim = _base(
        B_EVIDENCE,
        B_CLAIM,
        subject=B_REQUEST_WINDOW_SUBJECT,
        facet=B_REQUEST_WINDOW_FACET,
        predicate="refund_request_window",
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


def build_graph_case_b_v4() -> Substrate:
    """HISTORICAL, exam v4 (never examined again): the ambiguous shared substrate of B, E and H.

    The address kept ``_base``'s default subject "Refund window", facet "How long may a refund
    take?" and predicate ``refund_window`` beside a refund-request-window claim and Requirement:
    a visible duration question no claim answers. Kept only so the defect stays demonstrable."""
    substrate, claim = _base(B_EVIDENCE, B_CLAIM)
    existing = _requirement("REQ-existing", SAME_THING, basis_claim_ids=(claim,))
    _record_object(substrate.store, existing, EventType.REQUIREMENT_CANONICALIZED)
    substrate.claim_ids["refund"] = claim
    substrate.object_ids["existing"] = existing.id
    return substrate


I_OBLIGATION: Final = "refund processing must complete within thirty calendar days after approval"
I_BOUNDARY: Final = "refund-processing data must remain within approved UK-hosted infrastructure"


def build_graph_case_i() -> Substrate:
    """KIND (exam v3): one obligation on delivered behaviour, one boundary on the solution space.

    Both claims are stated by the same project human, in the same modality ("must ...
    within"), about the same refund process, and both are new. The first governs what the
    process must deliver and by when: a REQUIREMENT. The second removes options from how any
    process may be built (where its data may live): a CONSTRAINT. Neither wording nor
    "always REQUIREMENT" separates them; only the kind ontology does.
    """
    substrate, obligation = _base(
        "Refund processing must complete within thirty calendar days after approval.",
        I_OBLIGATION,
        subject="Refund completion time",
        facet="How long may refund processing take once a refund is approved?",
        predicate="refund_completion_time",
    )
    _ingest(
        substrate.governor,
        "EV-2",
        "Refund-processing data must remain within approved UK-hosted infrastructure.",
    )
    address = _create_address(
        substrate.governor,
        "J-addr-2",
        "EV-2",
        subject="Refund data hosting",
        facet="Where may refund-processing data be stored and processed?",
    )
    boundary = _assert_claim(
        substrate.governor,
        "J-claim-2",
        address,
        "EV-2",
        I_BOUNDARY,
        predicate="refund_data_location",
    )
    substrate.claim_ids.update(obligation=obligation, boundary=boundary)
    return substrate


C_REQUEST_WINDOW_SUBJECT: Final = "Refund request window"
C_REQUEST_WINDOW_FACET: Final = "Within how many days of purchase are refund requests accepted?"
C_OLD_EVIDENCE: Final = "Refund requests are accepted within 30 days of purchase."
C_CORRECTED_EVIDENCE: Final = "Refund requests are accepted within 14 days of purchase."


def build_graph_case_c() -> Substrate:
    """REAL CHANGE (exam v2): the request window REQ-old states was corrected, 30 to 14 days.

    One proposition throughout: REQ-old, its basis claim, the address it lives at and the
    correcting claim all speak of the days after purchase within which a refund request is
    accepted. Only the value changes, the old claim's judgment is superseded, and REQ-old is
    therefore stale. Nothing here describes how long a refund takes, so a replacement is the
    one lawful reading.
    """
    substrate, old = _base(
        C_OLD_EVIDENCE,
        "refund requests are accepted within thirty days of purchase",
        subject=C_REQUEST_WINDOW_SUBJECT,
        facet=C_REQUEST_WINDOW_FACET,
    )
    stale = _requirement("REQ-old", SAME_THING, basis_claim_ids=(old,))
    _record_object(substrate.store, stale, EventType.REQUIREMENT_CANONICALIZED)
    _stale_edge(substrate, "REQ-old", "J-claim")
    substrate.governor.record_authority(_project_authority())
    _ingest(substrate.governor, "EV-2", C_CORRECTED_EVIDENCE)
    address = state_of(substrate.store).semantic.claims[old].address_id
    corrected = _assert_claim(
        substrate.governor,
        "J-new",
        address,
        "EV-2",
        "refund requests are accepted within fourteen days of purchase",
    )
    _supersede(substrate, "J-sup", "J-claim", "EV-2")
    substrate.claim_ids.update(old=old, corrected=corrected)
    return substrate


def build_graph_case_c_v1() -> Substrate:
    """HISTORICAL, exam v1 (never examined again): the defective case C.

    REQ-old states a refund-request window ("accepted within 30 days of purchase") while its
    basis claim, the address facet ("How long may a refund take?") and the correction all state
    a refund-completion time ("must complete within ... calendar days"). Two propositions, so a
    replacement was not compelled. Kept only so the defect stays demonstrable.
    """
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


F_REQUEST_WINDOW_SUBJECT: Final = "Refund request window"
F_REQUEST_WINDOW_FACET: Final = "Within how many days of purchase are refund requests accepted?"
F_OLD_EVIDENCE: Final = "Customers may request a refund within thirty days of purchase."
F_OLD_CLAIM: Final = "refund requests are accepted within thirty days of purchase"
F_RESTATED_EVIDENCE: Final = "Refund requests are accepted up to thirty days after purchase."
F_RESTATED_CLAIM: Final = "refund requests are accepted up to thirty days after purchase"


def build_graph_case_f() -> Substrate:
    """STALE (exam v4): a stale Requirement says what a restated current claim says.

    One proposition throughout, the refund-request window: REQ-stale's text, the address
    subject and facet, the predicate and both claim values. The old claim's judgment was
    superseded by the restatement, so REQ-stale is stale although its meaning is unchanged; a
    stale object is never a witness, so it is replaced. A dead (non-current) object exists
    too and is never shown.
    """
    substrate, old = _base(
        F_OLD_EVIDENCE,
        F_OLD_CLAIM,
        subject=F_REQUEST_WINDOW_SUBJECT,
        facet=F_REQUEST_WINDOW_FACET,
        predicate="refund_request_window",
    )
    stale = _requirement("REQ-stale", SAME_THING, basis_claim_ids=(old,))
    _record_object(substrate.store, stale, EventType.REQUIREMENT_CANONICALIZED)
    _stale_edge(substrate, "REQ-stale", "J-claim")
    dead = _requirement("REQ-dead", SAME_THING, basis_claim_ids=()).model_copy(
        update={"authority": Authority.SUPERSEDED}
    )
    _record_object(substrate.store, dead, EventType.REQUIREMENT_CANONICALIZED)
    substrate.governor.record_authority(_project_authority())
    _ingest(substrate.governor, "EV-2", F_RESTATED_EVIDENCE)
    address = state_of(substrate.store).semantic.claims[old].address_id
    restated = _assert_claim(
        substrate.governor,
        "J-new",
        address,
        "EV-2",
        F_RESTATED_CLAIM,
        predicate="refund_request_window",
    )
    _supersede(substrate, "J-sup", "J-claim", "EV-2")
    substrate.claim_ids.update(old=old, restated=restated)
    return substrate


def build_graph_case_f_v3() -> Substrate:
    """HISTORICAL, exam v3 (never examined again): the ambiguous case F.

    The restated claim was the bare value "thirty days after purchase" under the default
    facet "How long may a refund take?", beside a request-window REQ-stale whose basis link is
    not shown, so a refund-duration reading was lawful. Kept only so the defect stays
    demonstrable.
    """
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


J_PAYMENT_CLAIM: Final = "refunds are paid to the original payment method"
J_SEVEN_CLAIM: Final = "refunds must complete within seven calendar days after approval"
J_THIRTY_CLAIM: Final = "refunds must complete within thirty calendar days after approval"


def build_graph_case_j() -> Substrate:
    """MIXED WITH A GAP (exam v5): one meaning resolvable, a distinct meaning genuinely open.

    The payment-method claim is new and unambiguous (NEW, a REQUIREMENT). The completion time is
    stated twice on one address, seven and thirty calendar days, by claims of equal standing: no
    graph decision can be made for it. The lawful answer resolves the first and gaps the second,
    and must not pair the resolved meaning with a gap."""
    substrate, payment = _base(
        "Refunds are always paid back to the original payment method.",
        J_PAYMENT_CLAIM,
        subject="Refund payment method",
        facet="Where are refunds paid?",
        predicate="refund_payment_method",
    )
    _ingest(
        substrate.governor,
        "EV-2",
        "Refunds must complete within seven calendar days after approval.",
    )
    address = _create_address(
        substrate.governor,
        "J-addr-2",
        "EV-2",
        subject="Refund completion time",
        facet="How long may refund processing take once a refund is approved?",
    )
    seven = _assert_claim(
        substrate.governor,
        "J-seven",
        address,
        "EV-2",
        J_SEVEN_CLAIM,
        predicate="refund_completion_time",
    )
    _ingest(
        substrate.governor,
        "EV-3",
        "Refunds must complete within thirty calendar days after approval.",
    )
    thirty = _assert_claim(
        substrate.governor,
        "J-thirty",
        address,
        "EV-3",
        J_THIRTY_CLAIM,
        predicate="refund_completion_time",
    )
    substrate.claim_ids.update(payment=payment, seven=seven, thirty=thirty)
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
    "I": build_graph_case_i,
    "J": build_graph_case_j,
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


GRAPH_ACCEPTANCE_RULE: Final = "every case passes all of its independent runs (MR4/MR6)"


def graph_verdict(attempts: list[dict[str, Any]]) -> str:
    """The acceptance rule: PASS only when every required attempt ran and passed."""
    required = len(GRAPH_CASES) * GRAPH_RUNS_PER_CASE
    passed = sum(1 for a in attempts if a["verdict"] == "PASS")
    return "PASS" if len(attempts) == required and passed == required else "NOT CERTIFIED"


# --- exam identity --------------------------------------------------------------------------


def graph_exam_world(case_id: str) -> Any:
    """The world a case builds, as its full event ledger, with incidental numbering removed.

    Event ids and judgment invocation ids come from process-wide counters, so they differ
    between two builds of the same world. Each event id is replaced by its position in the
    ledger (and every reference to it likewise); an invocation id loses its counter suffix.
    Everything else (evidence text, claims, addresses, facets, objects, authority, staleness
    edges, supersessions, scope, time) is kept exactly.
    """
    substrate = GRAPH_BUILDERS[case_id]()
    events = [stored.event.model_dump(mode="json") for stored in substrate.store.load(PROJECT)]
    positions = {event["event_id"]: f"EVENT-{i}" for i, event in enumerate(events)}

    def normalise(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {k: normalise(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [normalise(v) for v in value]
        if isinstance(value, str):
            if value in positions:
                return positions[value]
            if key == "invocation_id":
                return re.sub(r"-\d+$", "", value)
        return value

    return {
        "events": normalise(events),
        "claim_ids": dict(sorted(substrate.claim_ids.items())),
        "object_ids": dict(sorted(substrate.object_ids.items())),
    }


def graph_exam_manifest() -> dict[str, Any]:
    """Everything that decides what the exam asks, how each run executes and what passes."""
    return {
        "exam_id": GRAPH_EXAM_ID,
        "exam_version": GRAPH_EXAM_VERSION,
        "cases": {case: graph_exam_world(case) for case in GRAPH_CASES},
        "code": code_closure(
            [
                *(GRAPH_BUILDERS[case] for case in GRAPH_CASES),
                *(SCORERS[case] for case in GRAPH_CASES),
                score_graph_attempt,
                score_graph_global_gates,
                run_graph_attempt,
                graph_verdict,
            ]
        ),
        "acceptance": {
            "rule": GRAPH_ACCEPTANCE_RULE,
            "cases": list(GRAPH_CASES),
            "runs_per_case": GRAPH_RUNS_PER_CASE,
        },
    }


def graph_exam_sha256() -> str:
    return canonical_digest(graph_exam_manifest())


def write_graph_certification(
    contestant: Contestant, attempts: list[dict[str, Any]], *, frozen_production_base: str
) -> dict[str, Any]:
    """The verdict record, bound to the exam it was earned on."""
    required = len(GRAPH_CASES) * GRAPH_RUNS_PER_CASE
    passed = sum(1 for a in attempts if a["verdict"] == "PASS")
    if contestant.wire_schema is None or contestant.wire_schema_compiler is None:
        raise ValueError("a graph certification must bind the provider's wire schema")
    payload: dict[str, Any] = {
        "record_format": GRAPH_CERTIFICATION_RECORD_FORMAT,
        "exam_id": GRAPH_EXAM_ID,
        "exam_version": GRAPH_EXAM_VERSION,
        "exam_sha256": graph_exam_sha256(),
        "canonical_schema_sha256": schema_sha256(IntentGraphDraftPayload.model_json_schema()),
        "wire_schema_sha256": schema_sha256(contestant.wire_schema(IntentGraphDraftPayload)),
        "wire_schema_compiler": contestant.wire_schema_compiler,
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
        "acceptance_rule": GRAPH_ACCEPTANCE_RULE,
        "cases": list(GRAPH_CASES),
        "runs_per_case": GRAPH_RUNS_PER_CASE,
        "required_attempts": required,
        "recorded_attempts": len(attempts),
        "passed_attempts": passed,
        "verdict": graph_verdict(attempts),
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
    canonical_schema_sha256: str,
    wire_schema_sha256: str,
    wire_schema_compiler: str,
    exam_id: str,
    exam_version: str,
    exam_sha256: str,
) -> bool:
    """Does ``record`` certify exactly this contestant, answer contract and exam?

    A record certifies one provider, model, task, policy, prompt digest, canonical answer
    schema, provider wire schema, wire compiler and exam (id, version, hash) together. Change
    any of them and the record certifies nothing, rather than silently covering a system or an
    exam it never examined. Fail-closed on any missing field, so no v1 or v2 record ever binds.
    """
    expected = {
        "record_format": GRAPH_CERTIFICATION_RECORD_FORMAT,
        "exam_id": exam_id,
        "exam_version": exam_version,
        "exam_sha256": exam_sha256,
        "verdict": "PASS",
        "provider": identity.provider,
        "model": identity.model,
        "task": task.value,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "prompt_sha256": prompt_sha256,
        "canonical_schema_sha256": canonical_schema_sha256,
        "wire_schema_sha256": wire_schema_sha256,
        "wire_schema_compiler": wire_schema_compiler,
    }
    return all(record.get(key) == value for key, value in expected.items())


@dataclass(frozen=True)
class GraphExamSupersession:
    """An exam version that is no longer authoritative, and exactly why.

    Supersession never rewrites a record: a certificate earned on a superseded exam stays a
    truthful statement about that exam. It stops counting for the current contract, because
    ``certificate_binds`` requires the current exam hash, and this entry says in the repository
    why the old exam could not certify the dimension it failed to specify.
    """

    exam_version: str
    exam_sha256: str | None
    superseded_by: str
    defect: str
    not_a_precedent_for: str | None


SUPERSEDED_GRAPH_EXAMS: Final[tuple[GraphExamSupersession, ...]] = (
    GraphExamSupersession(
        exam_version="1",
        exam_sha256=None,
        superseded_by="2",
        defect="case C joined two propositions: REQ-old stated a refund-request window while "
        "its basis claim, address facet and correction stated a refund-completion time",
        not_a_precedent_for="REPLACES_STALE",
    ),
    GraphExamSupersession(
        exam_version="2",
        exam_sha256="813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c",
        superseded_by="3",
        defect="the exam scored REQUIREMENT against CONSTRAINT while the runtime-v2 contract "
        "defined neither kind, case A's claim carried only a bare value, and no case ever "
        "required a CONSTRAINT",
        not_a_precedent_for="REQUIREMENT_VERSUS_CONSTRAINT",
    ),
    GraphExamSupersession(
        exam_version="3",
        exam_sha256="72ca1102d0734900689d3e3260df988f57786494871fde8b73767df79a7331e8",
        superseded_by="4",
        defect="case F showed the restated claim as the bare value 'thirty days after purchase' "
        "under the facet 'How long may a refund take?' beside a request-window REQ-stale whose "
        "basis link is not visible, so a refund-duration reading (NEW, stale left alone) was "
        "lawful yet scored FAIL; and its scorer accepted any gap. A NEW node whose own rationale "
        "states that it supersedes REQ-stale remains a genuine failure under either exam",
        not_a_precedent_for="STALE_OBJECT_UNDER_AN_AMBIGUOUS_CLAIM",
    ),
    GraphExamSupersession(
        exam_version="4",
        exam_sha256="2c676e555286577284e6d50116b99b43f6527ef1c595b7faa4b84b5929442519",
        superseded_by="5",
        defect="the runtime-v3 gap contract never said what a gap is: it did not separate "
        "unresolved work that blocks a graph decision from a caveat, and never said that a "
        "meaning resolved as PARAPHRASE, CORRECTION or NEW takes no gap; case B's address "
        "(shared by E and H) asked 'How long may a refund take?' beside a refund-request-window "
        "claim and Requirement; and the scorers treated gaps inconsistently (B and F rejected "
        "any gap, C tolerated one beside a replacement, A/E/H/I tolerated any). Under exam v5 "
        "and runtime-v4 a gap beside a resolved meaning is contrary to the stated contract",
        not_a_precedent_for="GAP_BESIDE_A_RESOLVED_MEANING",
    ),
)
"""Exam v1 predates exam hashing (its records carry no exam identity), so it has no hash here.
The full manifests of exams v2, v3 and v4 are frozen in ``exam_manifests/``."""


def _current_graph_identity(identity: ModelIdentity) -> dict[str, Any]:
    from foundry.adapters.model_runtime.anthropic import AnthropicModelProvider
    from foundry.adapters.model_runtime.openai import OpenAIModelProvider
    from foundry.adapters.model_runtime.xai import XAIModelProvider

    provider = {
        "xai": XAIModelProvider,
        "openai": OpenAIModelProvider,
        "anthropic": AnthropicModelProvider,
    }[identity.provider]
    return {
        "identity": identity,
        "task": ModelTask.INTENT_GRAPH_SYNTHESIS,
        "policy_id": GRAPH_SYNTHESIS_POLICY_ID,
        "policy_version": GRAPH_SYNTHESIS_POLICY_VERSION,
        "prompt_sha256": GRAPH_SYSTEM_INSTRUCTION_SHA256,
        "canonical_schema_sha256": schema_sha256(IntentGraphDraftPayload.model_json_schema()),
        "wire_schema_sha256": schema_sha256(provider.wire_schema(IntentGraphDraftPayload)),
        "wire_schema_compiler": provider.WIRE_SCHEMA_COMPILER,
        "exam_id": GRAPH_EXAM_ID,
        "exam_version": GRAPH_EXAM_VERSION,
        "exam_sha256": graph_exam_sha256(),
    }


def graph_certificate_standing(record: dict[str, Any]) -> str:
    """What a graph certification record means for the *current* contract and exam.

    ``NOT_CERTIFIED``: its verdict was never PASS. ``HISTORICAL_FORMAT``: written before exam
    binding (v1/v2), so it can speak only to its own era. ``CURRENT``: it binds the current
    provider wire, prompt, policy, schema and exam exactly. ``SUPERSEDED``: a PASS earned on an
    exam or contract that has since been replaced; true history, no current authority.
    ``NOT_BINDING``: a PASS that matches neither the current identity nor any recorded
    supersession, which should not exist and is reported rather than guessed at.
    """
    if record.get("verdict") != "PASS":
        return "NOT_CERTIFIED"
    if record_format(record) != GRAPH_CERTIFICATION_RECORD_FORMAT:
        return "HISTORICAL_FORMAT"
    identity = ModelIdentity(provider=record["provider"], model=record["model"])
    if certificate_binds(record, **_current_graph_identity(identity)):
        return "CURRENT"
    superseded = {(s.exam_version, s.exam_sha256) for s in SUPERSEDED_GRAPH_EXAMS}
    if (record.get("exam_version"), record.get("exam_sha256")) in superseded:
        return "SUPERSEDED"
    return "NOT_BINDING"


def schema_bound_certificate_binds(
    record: dict[str, Any],
    *,
    identity: ModelIdentity,
    task: ModelTask,
    policy_id: str,
    policy_version: str,
    prompt_sha256: str,
    canonical_schema_sha256: str,
    wire_schema_sha256: str,
    wire_schema_compiler: str,
) -> bool:
    """The v2 question, for reasoning about historical v2 records only: did this v2 record
    certify this pre-exam identity? It answers nothing about any exam-bound identity, and no
    current certification path consults it."""
    if record_format(record) != SCHEMA_BOUND_RECORD_FORMAT:
        return False
    expected = {
        "verdict": "PASS",
        "provider": identity.provider,
        "model": identity.model,
        "task": task.value,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "prompt_sha256": prompt_sha256,
        "canonical_schema_sha256": canonical_schema_sha256,
        "wire_schema_sha256": wire_schema_sha256,
        "wire_schema_compiler": wire_schema_compiler,
    }
    return all(record.get(key) == value for key, value in expected.items())


def record_format(record: dict[str, Any]) -> str:
    """The format a record was written in; a record without the field is historical v1."""
    return str(record.get("record_format", "ie3-graph-certification.v1"))


def historical_certificate_binds(
    record: dict[str, Any],
    *,
    identity: ModelIdentity,
    task: ModelTask,
    policy_id: str,
    policy_version: str,
    prompt_sha256: str,
) -> bool:
    """The v1 question, for reasoning about historical records only: did this v1 record
    certify this pre-schema identity? It answers nothing about any schema-bound identity, and
    no current certification path consults it."""
    if record_format(record) != "ie3-graph-certification.v1":
        return False
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
