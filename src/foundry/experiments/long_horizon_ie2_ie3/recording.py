"""Budgeted, identity-guarded recorders for both layers (design §4, §12).

**IE2.** ``IE2Recorder`` wraps the xAI reasoner. Before every call it applies validation
v5's ``require_accounting_policy_identity`` (the same frozen policy: class, provider, model,
effort, policy version, sent-prompt sha256, output contract and schema sha256, contrastive
path). It refuses a third call in a turn, a 33rd call overall and any call once the known
cost exceeds the ceiling, before forwarding. It records the exact rendered request, the
parsed payload and any structural refusal. A refusal is recorded and re-raised, never
re-proposed.

**IE3.** ``RecordingGraphProvider`` wraps the OpenAI provider under the Model Runtime and
records each execution (identity the provider reports, usage, finish reason, output).
``IE3Budget`` refuses a 17th graph call before forwarding. ``require_ie3_identity`` checks the
runtime-v4 policy, prompt, canonical schema, OpenAI wire schema and compiler against the
certificate literals before every call.

Structural facts only; nothing here reads the answer key or decides meaning.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final

from pydantic import BaseModel

from foundry.adapters.intent_graph_synthesis.model_runtime import (
    GRAPH_SYNTHESIS_POLICY_ID,
    GRAPH_SYNTHESIS_POLICY_VERSION,
    GRAPH_SYSTEM_INSTRUCTION,
    GRAPH_SYSTEM_INSTRUCTION_SHA256,
    IntentGraphDraftPayload,
)
from foundry.adapters.model_runtime.openai import OpenAIModelProvider
from foundry.adapters.model_runtime.openai_wire_schema import OPENAI_WIRE_SCHEMA_COMPILER
from foundry.adapters.semantics.xai_reasoner import render_request
from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.experiments.locus_validation_v5.recording import (
    EXPECTED_IDENTITY as V5_EXPECTED_IDENTITY,
)
from foundry.experiments.locus_validation_v5.recording import (
    IdentityDrift,
    require_accounting_policy_identity,
)
from foundry.experiments.long_horizon_ie2_ie3 import protocol
from foundry.model_runtime.domain import ModelIdentity, ModelRequest
from foundry.model_runtime.ports import ProviderExecutionResult
from foundry.ports.semantic_reasoner import (
    ReasonerResponseRefused,
    ReasoningRequest,
    SemanticReasoner,
)

__all__ = [
    "EXPECTED_IE2_IDENTITY",
    "BudgetExceeded",
    "GraphCallRecord",
    "IE2CallRecord",
    "IE2Recorder",
    "IE3Budget",
    "IdentityDrift",
    "RecordingGraphProvider",
    "RunBudget",
    "canonical_schema_sha256",
    "require_ie3_identity",
    "wire_schema_sha256",
]

EXPECTED_IE2_IDENTITY: Final[dict[str, str | bool]] = {
    "reasoner_class": protocol.IE2_REASONER_CLASS,
    "provider": protocol.IE2_PROVIDER,
    "model": protocol.IE2_MODEL,
    "fingerprint_policy_version": protocol.IE2_POLICY_VERSION,
    "policy_version": protocol.IE2_POLICY_VERSION,
    "system_prompt_sha256": protocol.IE2_PROMPT_SHA256,
    "include_comparison_context": True,
    "reasoning_effort": protocol.IE2_REASONING_EFFORT,
    "output_schema": protocol.IE2_OUTPUT_SCHEMA,
    "output_schema_sha256": protocol.IE2_OUTPUT_SCHEMA_SHA256,
}
"""Must equal validation v5's frozen identity field for field (a gate checks it), so the
v5 guard function applied below guards exactly this experiment's policy."""

_IE2_COST_CEILING: Final = Decimal(str(protocol.MAX_IE2_COST_USD))


class BudgetExceeded(RuntimeError):
    pass


class RunBudget:
    """The run-scoped tally of both layers."""

    def __init__(self) -> None:
        self.ie2_calls = 0
        self.ie2_cost_usd = Decimal("0")
        self.ie3_calls = 0


# --------------------------------------------------------------------------- IE2


class IE2CallRecord(FrozenModel):
    t: int
    call: int
    request_sha256: str
    rendered_request: str
    allowed_kinds: tuple[str, ...]
    citable_evidence_ids: tuple[str, ...]
    known_address_ids: tuple[str, ...]
    known_claim_ids: tuple[str, ...]
    known_claim_judgment_ids: tuple[str, ...]
    returned_judgment_ids: tuple[str, ...]
    model_payload: dict[str, Any] | None = None
    accountable_evidence_ids: tuple[str, ...] = ()
    refusal_findings: tuple[str, ...] = ()
    refused_invocation_id: str | None = None
    wall_clock_ms: int | None = None


class IE2Recorder:
    def __init__(self, inner: SemanticReasoner, *, budget: RunBudget, guard_identity: bool) -> None:
        if V5_EXPECTED_IDENTITY != EXPECTED_IE2_IDENTITY:
            raise IdentityDrift("IDENTITY_DRIFT: validation v5's frozen identity moved")
        self._guard = guard_identity
        if guard_identity:
            require_accounting_policy_identity(inner)
        self._inner = inner
        self._budget = budget
        self._t: int | None = None
        self._calls_this_turn = 0
        self.records: list[IE2CallRecord] = []
        self.receipts: list[Any] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def begin_turn(self, t: int) -> None:
        self._t = t
        self._calls_this_turn = 0

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if self._guard:
            require_accounting_policy_identity(self._inner)
        if self._t is None:
            raise BudgetExceeded("NO_TURN_BEGUN: propose before begin_turn")
        if self._budget.ie2_calls + 1 > protocol.MAX_IE2_CALLS:
            raise BudgetExceeded(f"IE2_CEILING: call {self._budget.ie2_calls + 1}")
        if self._calls_this_turn >= protocol.IE2_CALLS_PER_TURN:
            raise BudgetExceeded("THIRD_CALL_REFUSED: no retry, fallback or re-proposal")
        if self._budget.ie2_cost_usd > _IE2_COST_CEILING:
            raise BudgetExceeded(f"IE2_COST_CEILING: {self._budget.ie2_cost_usd} USD")
        receipts_before = len(getattr(self._inner, "receipts", ()))
        payloads_before = len(getattr(self._inner, "draft_payloads", ()))
        self._budget.ie2_calls += 1
        self._calls_this_turn += 1
        refusal: ReasonerResponseRefused | None = None
        result: tuple[SemanticJudgment, ...] = ()
        started = time.perf_counter()
        try:
            result = self._inner.propose(request)
        except ReasonerResponseRefused as refused:
            refusal = refused
        elapsed = int((time.perf_counter() - started) * 1000)
        inner_type = type(self._inner)
        rendered = render_request(
            request,
            include_comparison_context=True,
            include_sentence_index=getattr(inner_type, "include_sentence_index", False),
            include_reproposal_notice=getattr(inner_type, "accepts_reproposal", False),
        )
        self.records.append(
            IE2CallRecord(
                t=self._t,
                call=self._calls_this_turn,
                request_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                rendered_request=rendered,
                allowed_kinds=tuple(sorted(k.value for k in request.allowed_judgment_kinds)),
                citable_evidence_ids=tuple(sorted(e.evidence_id for e in request.evidence)),
                known_address_ids=tuple(sorted(a.address_id for a in request.known_addresses)),
                known_claim_ids=tuple(sorted(c.claim_id for c in request.known_claims)),
                known_claim_judgment_ids=tuple(
                    sorted(c.created_by_judgment_id for c in request.known_claims)
                ),
                returned_judgment_ids=tuple(j.judgment_id for j in result),
                model_payload=next(
                    (
                        p.model_dump(mode="json")
                        for p in tuple(getattr(self._inner, "draft_payloads", ()))[payloads_before:]
                    ),
                    None,
                ),
                accountable_evidence_ids=request.accountable_evidence_ids,
                refusal_findings=refusal.findings if refusal is not None else (),
                refused_invocation_id=refusal.invocation_id if refusal is not None else None,
                wall_clock_ms=elapsed,
            )
        )
        for receipt in tuple(getattr(self._inner, "receipts", ()))[receipts_before:]:
            self.receipts.append(receipt)
            cost = getattr(receipt, "cost_usd", None)
            if cost is not None:
                self._budget.ie2_cost_usd += Decimal(str(cost))
        if refusal is not None:
            raise refusal
        return result


# --------------------------------------------------------------------------- IE3


def _schema_sha256(schema: Mapping[str, Any]) -> str:
    """The certification harness's schema identity rule (``_schema_identity.schema_sha256``)."""
    import json

    text = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_schema_sha256() -> str:
    return _schema_sha256(IntentGraphDraftPayload.model_json_schema())


def wire_schema_sha256() -> str:
    return _schema_sha256(OpenAIModelProvider.wire_schema(IntentGraphDraftPayload))


def require_ie3_identity() -> None:
    """Raise ``IdentityDrift`` unless runtime-v4 and its schemas equal the certificate."""
    observed = {
        "policy_id": GRAPH_SYNTHESIS_POLICY_ID,
        "policy_version": GRAPH_SYNTHESIS_POLICY_VERSION,
        "prompt_sha256": hashlib.sha256(GRAPH_SYSTEM_INSTRUCTION.encode()).hexdigest(),
        "prompt_constant": GRAPH_SYSTEM_INSTRUCTION_SHA256,
        "canonical_schema_sha256": canonical_schema_sha256(),
        "wire_schema_sha256": wire_schema_sha256(),
        "wire_schema_compiler": OpenAIModelProvider.WIRE_SCHEMA_COMPILER,
        "compiler_constant": OPENAI_WIRE_SCHEMA_COMPILER,
    }
    expected = {
        "policy_id": protocol.IE3_POLICY_ID,
        "policy_version": protocol.IE3_POLICY_VERSION,
        "prompt_sha256": protocol.IE3_PROMPT_SHA256,
        "prompt_constant": protocol.IE3_PROMPT_SHA256,
        "canonical_schema_sha256": protocol.IE3_CANONICAL_SCHEMA_SHA256,
        "wire_schema_sha256": protocol.IE3_WIRE_SCHEMA_SHA256,
        "wire_schema_compiler": protocol.IE3_WIRE_SCHEMA_COMPILER,
        "compiler_constant": protocol.IE3_WIRE_SCHEMA_COMPILER,
    }
    for key, value in expected.items():
        if observed[key] != value:
            raise IdentityDrift(
                f"IDENTITY_DRIFT: IE3 {key} observed {observed[key]!r} != {value!r}"
            )


class IE3Budget:
    def __init__(self, budget: RunBudget) -> None:
        self._budget = budget

    def admit(self) -> None:
        if self._budget.ie3_calls + 1 > protocol.MAX_IE3_CALLS:
            raise BudgetExceeded(f"IE3_CEILING: call {self._budget.ie3_calls + 1}")
        self._budget.ie3_calls += 1


class GraphCallRecord(FrozenModel):
    """One provider execution of one graph synthesis: what the provider said it ran."""

    provider: str
    model: str
    task: str
    tier: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    wall_clock_ms: int | None
    finish_reason: str | None
    output: dict[str, Any] | None


class RecordingGraphProvider:
    """The provider under the Model Runtime, recording each execution. Forwards unchanged."""

    def __init__(self, inner: Any, budget: IE3Budget) -> None:
        self._inner = inner
        self._budget = budget
        self.records: list[GraphCallRecord] = []

    @property
    def provider_id(self) -> str:
        return str(self._inner.provider_id)

    def execute[T: BaseModel](
        self, *, model: ModelIdentity, request: ModelRequest, output_type: type[T]
    ) -> ProviderExecutionResult[T]:
        require_ie3_identity()
        self._budget.admit()
        result: ProviderExecutionResult[T] = self._inner.execute(
            model=model, request=request, output_type=output_type
        )
        usage = result.usage
        self.records.append(
            GraphCallRecord(
                provider=result.identity.provider,
                model=result.identity.model,
                task=request.task.value,
                tier=request.tier.value,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=usage.cost_usd,
                wall_clock_ms=usage.wall_clock_ms,
                finish_reason=result.finish_reason,
                output=result.output.model_dump(mode="json"),
            )
        )
        return result
