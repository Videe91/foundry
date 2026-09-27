"""Contestant-neutral machinery for running the Intent Synthesis certification exam.

The semantic exam lives in ``_intent_synthesis_exam`` and is identical for every
contestant. This module holds only the parts that differ between providers — which model
sits the exam, which credential reaches it, where its evidence is written — so that adding
a contestant never means copying a scorer.

Two rules shape everything here.

**Evidence is per-contestant.** Each model writes under
``tests/certification/evidence/<provider>/<model>/`` and reads nothing else. A single
shared artifact would mean the second contestant's run silently destroyed the first one's
certification evidence, which is the one thing a certification record must never do.

**The output guard is not the exam.** ``max_output_tokens`` is a transport safety bound,
not part of the semantic contestant, and it means different things per provider: for
OpenAI reasoning models it covers reasoning tokens as well as visible output, while for
xAI it bounds visible output only. A bound that actually bites therefore says nothing about
whether a model understands Intent, so reaching it stops the run as a harness limit rather
than scoring the attempt as incompetence.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Final

import openai

from foundry.adapters.intent_synthesis.model_runtime import ModelRuntimeIntentSynthesizer
from foundry.application.intent_synthesis import synthesize_intent
from foundry.application.intent_synthesis_context import compile_intent_synthesis_context
from foundry.domain.intent_synthesis import IntentSynthesisPolicy
from foundry.model_runtime.domain import (
    ModelCapability,
    ModelDescriptor,
    ModelExecutionConstraints,
    ModelIdentity,
    ModelTask,
    ModelTier,
    ModelTraceContext,
)
from foundry.model_runtime.errors import ModelProtocolError, ModelProviderError
from foundry.model_runtime.ports import ProviderExecutionResult
from foundry.model_runtime.registry import ModelRegistry
from foundry.model_runtime.runtime import ModelRuntime
from tests.certification._intent_synthesis_exam import (
    AT,
    PROJECT,
    SCOPE,
    CallEvidence,
    ExamObservation,
    Substrate,
    state_of,
)

EVIDENCE_ROOT = pathlib.Path("tests/certification/evidence")

MAXIMUM_GUARD_UTILISATION_PERCENT: Final[int] = 80
"""A certification run may use at most this share of its own output guard.

Equivalently: at least 20% headroom. Locked deliberately **before** any contestant's live
telemetry existed, so the threshold can never be chosen — or quietly widened — to make a
particular run pass. Expressed as an integer percent so the boundary is exact arithmetic
rather than float rounding.
"""

# --- failure taxonomy (R5) --------------------------------------------------------------------
#
# Four distinct situations with four different meanings. A generic assertion that collapsed
# them would let a truncated call, a refused call and a wrong answer all read as "the model
# failed", which is exactly the misdiagnosis that makes a certification record worthless.


class CertificationIncomplete(Exception):
    """The run could not be completed. **Not** a verdict about the model.

    Raised where continuing would produce a record that looks like a judgement but is not
    one. The run stops; nothing is retried.
    """


class TransportFailure(CertificationIncomplete):
    """The call never produced an answer. `INCOMPLETE: TRANSPORT FAILURE`."""


class HarnessLimitReached(CertificationIncomplete):
    """The certification's own safety guard bound the call. `INCOMPLETE: HARNESS LIMIT`.

    The guard was predeclared and is required to be non-binding. If it binds, the harness
    is at fault, not the contestant, and the attempt is never scored as incompetence.
    """


class HarnessHeadroomExhausted(CertificationIncomplete):
    """The run finished, but sat too close to our own bound to be scoreable.

    `INCOMPLETE: HARNESS HEADROOM`. Distinct from ``HarnessLimitReached``: nothing was
    truncated, so every answer is intact — but the guard is an artificial certification
    bound, and a contestant pressed against it is one verbose response away from a verdict
    flipping. Neither outcome would mean anything about Intent competence.

    The cure is a fresh run with a wider guard, never a wider guard applied to the run that
    already happened: raising the bound after seeing the numbers would make the threshold a
    function of the result it is supposed to judge.
    """


class ProtocolTaskFailure(AssertionError):
    """A real response that broke the output contract. `NOT CERTIFIED: PROTOCOL/TASK`.

    A refusal or an unsatisfiable schema is a genuine failure of the contestant at this
    task — distinct from a wrong answer, which the semantic scorers catch, and distinct
    from a transport fault, which produced no answer at all.
    """


_STRUCTURED_CAUSE_CATEGORIES: tuple[tuple[type[BaseException], type[Exception]], ...] = (
    # A length cutoff is *our* bound binding, so it can never be a verdict about the model.
    (openai.LengthFinishReasonError, HarnessLimitReached),
    # A content filter is the contestant failing this task, not our guard binding.
    (openai.ContentFilterFinishReasonError, ProtocolTaskFailure),
)
"""Provider exception types that state *why* a response stopped, and what that means here.

Reading the preserved ``__cause__`` rather than the outer message is not a refinement, it
is the only thing that works. MR5's adapter collapses both SDK truncation errors into one
sentence -- "OpenAI stopped the response before the requested structure was complete" --
which names no reason and is byte-identical for both. Classifying on that text would blame
the contestant for the certification's own 16,000-token guard, and would do it on a billed
run where the mistake is expensive and easy to believe.

Adding a provider later is a row here, not another branch below.
"""

_TRUNCATION_SIGNALS = ("max_output_tokens", "max_messages")
"""Substrings a provider uses to say it stopped because an output bound was reached.

The fallback for paths that carry their reason in text and raise from no SDK error -- the
Responses ``status=incomplete`` path is exactly that shape. It is consulted only after the
structured signals above find nothing, so a real cause always wins over prose.
"""


def _structured_category(exc: BaseException) -> type[Exception] | None:
    """Walk the explicit cause chain for a provider signal that names the reason.

    Only ``__cause__`` is followed, never ``__context__``: an implicit context can carry an
    unrelated exception that happened to be in flight, and misreading one of those as a
    truncation signal would be a worse failure than having no signal at all.
    """
    seen: set[int] = set()
    cause = exc.__cause__
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        for sdk_error, category in _STRUCTURED_CAUSE_CATEGORIES:
            if isinstance(cause, sdk_error):
                return category
        cause = cause.__cause__
    return None


def classify_execution_failure(exc: BaseException) -> None:
    """Re-raise ``exc`` as the category it actually belongs to.

    Order matters twice over. Transport is checked first because it means no answer
    existed, and a bound cannot have been reached by a call that never ran. Within a
    protocol failure, a structured provider cause beats message text, because the text is
    the adapter's summary while the cause is the provider's own account of why it stopped.
    """
    if isinstance(exc, ModelProviderError):
        raise TransportFailure(f"the provider call did not produce an answer: {exc}") from exc
    if isinstance(exc, ModelProtocolError):
        category = _structured_category(exc)
        if category is HarnessLimitReached:
            raise HarnessLimitReached(
                "the provider reported it stopped at a length bound; the certification's "
                "predeclared output guard is required to be non-binding, so this is a "
                f"harness defect, not a model verdict: {exc}"
            ) from exc
        if category is ProtocolTaskFailure:
            raise ProtocolTaskFailure(
                f"the provider stopped the response for its own reasons: {exc}"
            ) from exc
        if any(signal in str(exc) for signal in _TRUNCATION_SIGNALS):
            raise HarnessLimitReached(
                "the certification's predeclared output guard bound this call; the guard is "
                f"required to be non-binding, so this is a harness defect, not a model "
                f"verdict: {exc}"
            ) from exc
        raise ProtocolTaskFailure(
            f"the provider answered but broke the output contract: {exc}"
        ) from exc


# --- the contestant ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Contestant:
    """One model sitting the exam, and everything provider-specific about doing so."""

    identity: ModelIdentity
    credential_env: str
    provider_factory: Callable[[str], Any]
    reasoning_effort: str = "high"
    max_output_tokens: int = 2000
    timeout_seconds: float = 120.0
    task: ModelTask = ModelTask.INTENT_SYNTHESIS
    """The one task this contestant may SIT. Defaulted so every Slice-1 runner is unchanged."""
    evidence_namespace: str | None = None
    """A per-task evidence subdirectory. ``None`` keeps the Slice-1 layout byte-identical; a
    second task under the same model writes beside it and can never overwrite it."""
    wire_schema: Callable[[type[Any]], Mapping[str, Any]] | None = None
    """The provider's own statement of the structured-output schema it transmits (its
    ``wire_schema``). Required by a schema-bound certification; ``None`` for Slice-1 runners."""
    wire_schema_compiler: str | None = None
    """The provider's ``WIRE_SCHEMA_COMPILER``: what produced that wire schema."""

    @property
    def evidence_dir(self) -> pathlib.Path:
        """Per-contestant (and per-task), so no run can overwrite another's record."""
        base = EVIDENCE_ROOT / self.identity.provider / self.identity.model
        return base / self.evidence_namespace if self.evidence_namespace else base

    @property
    def measurements_path(self) -> pathlib.Path:
        return self.evidence_dir / "measurements.json"

    @property
    def ledger_path(self) -> pathlib.Path:
        return self.evidence_dir / "case_a_ledger.json"

    @property
    def label(self) -> str:
        return f"{self.identity.provider}/{self.identity.model}"

    def registry(self) -> ModelRegistry:
        """Test-local descriptor: permits this model to SIT the exam. Not certification."""
        return ModelRegistry(
            descriptors=(
                ModelDescriptor(
                    identity=self.identity,
                    tiers=frozenset({ModelTier.REASONER}),
                    capabilities=frozenset(
                        {ModelCapability.TEXT_GENERATION, ModelCapability.STRUCTURED_OUTPUT}
                    ),
                    certified_tasks=frozenset({self.task}),
                ),
            )
        )

    def constraints(self) -> ModelExecutionConstraints:
        return ModelExecutionConstraints(
            timeout_seconds=self.timeout_seconds,
            max_output_tokens=self.max_output_tokens,
            max_cost_usd=None,
        )


class RecordingProvider:
    """Wraps any real adapter so the exam keeps provider metadata. Test-only.

    Production is untouched: this delegates to the real provider and only remembers what
    came back. It names no vendor, so it serves every contestant.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.results: list[ProviderExecutionResult[Any]] = []

    @property
    def provider_id(self) -> str:
        return str(self._inner.provider_id)

    @property
    def calls(self) -> int:
        return len(self.results)

    def execute(self, **kwargs: Any) -> ProviderExecutionResult[Any]:
        result = self._inner.execute(**kwargs)
        self.results.append(result)
        return result


@dataclass
class AttemptRecord:
    """One attempt's observation plus whatever governance said about it."""

    observation: ExamObservation
    governance_error: Exception | None = None
    measurement: dict[str, Any] = field(default_factory=dict)


# --- one live attempt -------------------------------------------------------------------------


def run_attempt(
    contestant: Contestant,
    substrate: Substrate,
    case_id: str,
    attempt: int,
    *,
    api_key: str,
) -> AttemptRecord:
    """One live call through the whole production path, with fresh everything.

    Fresh store, substrate, synthesis run id and trace ids per attempt, so no case can
    pass on conversational carry-over.
    """
    provider = RecordingProvider(contestant.provider_factory(api_key))
    runtime = ModelRuntime(registry=contestant.registry(), providers=(provider,))
    traces = count(1)
    synthesizer = ModelRuntimeIntentSynthesizer(
        runtime=runtime,
        model_identity=contestant.identity,
        trace_factory=lambda: ModelTraceContext(
            run_id=f"CERT-{case_id}-{attempt}", call_id=f"CALL-{next(traces)}"
        ),
        execution_constraints=contestant.constraints(),
    )

    before = state_of(substrate.store)
    context = compile_intent_synthesis_context(before, scope=SCOPE)
    assert context.request is not None, f"{case_id}: nothing eligible; the exam cannot run"
    visible_claims = tuple(c.claim_id for locus in context.request.basis for c in locus.live_claims)
    visible_objects = tuple(o.object_id for o in context.request.known_intent_objects)

    result_holder: dict[str, Any] = {}

    class CapturingSynthesizer:
        """Records exactly what the model returned, before T7/T8 act on it."""

        @property
        def fingerprint(self) -> Any:
            return synthesizer.fingerprint

        def synthesize(self, request: Any) -> Any:
            produced = synthesizer.synthesize(request)
            result_holder["result"] = produced
            return produced

    error: Exception | None = None
    try:
        synthesize_intent(
            substrate.store,
            project_id=PROJECT,
            scope=SCOPE,
            synthesizer=CapturingSynthesizer(),  # type: ignore[arg-type]
            policy=IntentSynthesisPolicy(),
            clock=lambda: AT,
            synthesis_run_id_factory=lambda: f"RUN-{case_id}-{attempt}",
            human_actor_id=None,
        )
    except (ModelProviderError, ModelProtocolError) as exc:
        # Execution never yielded a scoreable answer. Classify it precisely before any
        # generic assertion below can flatten it into "the model failed".
        classify_execution_failure(exc)
        raise  # unreachable; classify_execution_failure always raises
    except Exception as exc:  # noqa: BLE001 - a governance rejection is exam evidence
        error = exc

    after = state_of(substrate.store)
    metadata = provider.results[0] if provider.results else None
    evidence = (
        CallEvidence(
            provider=metadata.identity.provider,
            model=metadata.identity.model,
            task=ModelTask.INTENT_SYNTHESIS.value,
            tier=ModelTier.REASONER.value,
            input_tokens=metadata.usage.input_tokens,
            output_tokens=metadata.usage.output_tokens,
            # Unknown stays unknown. A provider that reports no cost did not make a free
            # call, and a provider that exposes no finish reason did not stop for "stop".
            cost_usd=metadata.usage.cost_usd,
            wall_clock_ms=metadata.usage.wall_clock_ms,
            finish_reason=metadata.finish_reason,
        )
        if metadata is not None
        else None
    )

    produced = result_holder.get("result")
    assert produced is not None, f"{case_id} attempt {attempt}: no model result was captured"

    observation = ExamObservation(
        case_id=case_id,
        attempt=attempt,
        result=produced,
        state=after,
        provider_calls=provider.calls,
        evidence=evidence,
        visible_claim_ids=visible_claims,
        visible_object_ids=visible_objects,
        decision_authors=tuple(r.author for r in after.intent_synthesis.decisions.values()),
    )

    measurement = {
        "case": case_id,
        "attempt": attempt,
        "provider": evidence.provider if evidence else None,
        "model": evidence.model if evidence else None,
        "input_tokens": evidence.input_tokens if evidence else None,
        "output_tokens": evidence.output_tokens if evidence else None,
        "cost_usd": evidence.cost_usd if evidence else None,
        "wall_clock_ms": evidence.wall_clock_ms if evidence else None,
        "finish_reason": evidence.finish_reason if evidence else None,
        "outcome": (
            "AMBIGUITY"
            if produced.gap_proposals
            else produced.proposals[0].disposition.value
            if produced.proposals
            else "EMPTY"
        ),
        "governance_error": type(error).__name__ if error else None,
    }
    return AttemptRecord(observation=observation, governance_error=error, measurement=measurement)


# --- the predeclared guard must stay non-binding -----------------------------------------------


def assert_guard_was_not_binding(
    contestant: Contestant, measurements: list[dict[str, Any]]
) -> None:
    """Independent of the error classifier: prove the guard neither bound nor came close.

    Two conditions, because "nothing was truncated" is not the same as "the bound was
    irrelevant". A run that finishes at 15,999 of 16,000 produced intact answers and would
    pass a saturation check, yet the next attempt is six tokens from a different verdict —
    and that verdict would be about our guard, not about Intent competence.

    The threshold is measured on **output** tokens only: the guard bounds output, and input
    is thousands of prompt tokens that have nothing to do with it.
    """
    reported = [m["output_tokens"] for m in measurements if m["output_tokens"] is not None]
    if not reported:
        return
    high_water = max(reported)
    guard = contestant.max_output_tokens

    if high_water >= guard:
        raise HarnessLimitReached(
            f"{contestant.label} reached the predeclared output guard ({high_water} >= {guard})"
        )

    # Integer comparison rather than `high_water > guard * 0.8`: 0.8 is not exactly
    # representable, so a float boundary would decide the 12800 case by rounding luck.
    if high_water * 100 > guard * MAXIMUM_GUARD_UTILISATION_PERCENT:
        ceiling = guard * MAXIMUM_GUARD_UTILISATION_PERCENT // 100
        raise HarnessHeadroomExhausted(
            f"{contestant.label} left too little headroom under the predeclared output "
            f"guard: high water {high_water} exceeds the {MAXIMUM_GUARD_UTILISATION_PERCENT}% "
            f"ceiling of {ceiling} (guard {guard}). The run is not scoreable either way; a "
            "wider guard requires a fresh run, not a re-reading of this one."
        )


# --- durable evidence -------------------------------------------------------------------------


def write_case_a_ledger(contestant: Contestant, substrate: Substrate) -> None:
    """Preserve a genuinely model-authored event stream for the offline replay proof."""
    contestant.evidence_dir.mkdir(parents=True, exist_ok=True)
    contestant.ledger_path.write_text(
        json.dumps(
            [
                {"sequence": s.sequence, "event": s.event.model_dump(mode="json")}
                for s in substrate.store.load(PROJECT)
            ],
            indent=2,
        )
    )


def write_measurements(
    contestant: Contestant,
    measurements: list[dict[str, Any]],
    *,
    policy_version: str,
    prompt_sha256: str,
    runs_per_case: int,
) -> dict[str, Any]:
    """Write this contestant's measured baseline. Unknown telemetry stays unknown.

    Aggregates skip unreported values rather than defaulting them, so a provider that
    reports no dollar cost yields ``known_cost_total: null`` and a truthful
    ``unknown_cost_samples`` count — never a fabricated ``0`` that a later comparison would
    read as "this model was free".
    """
    costs = [m["cost_usd"] for m in measurements if m["cost_usd"] is not None]
    latencies = sorted(m["wall_clock_ms"] for m in measurements if m["wall_clock_ms"] is not None)
    inputs = [m["input_tokens"] for m in measurements if m["input_tokens"] is not None]
    outputs = [m["output_tokens"] for m in measurements if m["output_tokens"] is not None]
    finishes = sorted({m["finish_reason"] for m in measurements if m["finish_reason"] is not None})

    payload: dict[str, Any] = {
        "candidate": contestant.label,
        "policy_version": policy_version,
        "prompt_sha256": prompt_sha256,
        "runs_per_case": runs_per_case,
        "calls": measurements,
        "known_cost_total": sum(costs) if costs else None,
        "known_cost_samples": len(costs),
        "unknown_cost_samples": len(measurements) - len(costs),
        "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
        "input_tokens_total": sum(inputs) if inputs else None,
        "output_tokens_total": sum(outputs) if outputs else None,
        "reported_finish_reasons": finishes,
        "output_token_guard": contestant.max_output_tokens,
        "output_token_high_water": max(outputs) if outputs else None,
    }
    contestant.evidence_dir.mkdir(parents=True, exist_ok=True)
    contestant.measurements_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload
