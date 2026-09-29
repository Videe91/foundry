"""The budgeted, identity-guarded, recording wrapper around the reasoner (design §10).

It records structural facts only (what each request showed, what came back, what it
cost) and decides nothing about meaning. Ceilings are enforced before forwarding; nothing
is retried. On the live path it applies ``require_accounting_policy_identity`` before every
call: provider, model, effort, the reasoner class, the policy version (class and
fingerprint), the sha256 of the instruction the instance actually sends, the output contract
(its name and schema sha256) and the contrastive-context flag must equal the frozen literals
of ``protocol``. Each call records the governed state just before it (so the state after
Call 1 is kept, not only the state after each delta) and the exact parsed payload the model
returned. The request path never imports the answer key.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Final

from foundry.adapters.semantics.xai_reasoner import accounted_output_schema_sha256, render_request
from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.domain.state import IntentState
from foundry.experiments.locus_validation.recording import IdentityDrift, observed_identity
from foundry.experiments.locus_validation_v5.protocol import (
    CALLS_PER_DELTA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MODEL,
    OUTPUT_SCHEMA_FROZEN,
    OUTPUT_SCHEMA_SHA256_FROZEN,
    POLICY_VERSION_FROZEN,
    PROMPT_SHA256_FROZEN,
    PROVIDER,
    REASONER_CLASS_FROZEN,
    REASONING_EFFORT,
    LedgerId,
)
from foundry.ports.semantic_reasoner import (
    ReasonerResponseRefused,
    ReasoningRequest,
    SemanticReasoner,
)

__all__ = [
    "EXPECTED_IDENTITY",
    "BudgetExceeded",
    "CallRecord",
    "IdentityDrift",
    "RecordingReasoner",
    "RunBudget",
    "require_accounting_policy_identity",
]

_COST_CEILING: Final = Decimal(str(MAX_COST_USD))

EXPECTED_IDENTITY: Final[dict[str, str | bool]] = {
    "reasoner_class": REASONER_CLASS_FROZEN,
    "provider": PROVIDER,
    "model": MODEL,
    "fingerprint_policy_version": POLICY_VERSION_FROZEN,
    "policy_version": POLICY_VERSION_FROZEN,
    "system_prompt_sha256": PROMPT_SHA256_FROZEN,
    "include_comparison_context": True,
    "reasoning_effort": REASONING_EFFORT,
    "output_schema": OUTPUT_SCHEMA_FROZEN,
    "output_schema_sha256": OUTPUT_SCHEMA_SHA256_FROZEN,
}


def _observed_contract(inner: SemanticReasoner) -> dict[str, str | bool]:
    payload = getattr(type(inner), "draft_payload", None)
    if payload is None:
        return {}
    observed: dict[str, str | bool] = {"output_schema": payload.__name__}
    if payload.__name__ == OUTPUT_SCHEMA_FROZEN:
        observed["output_schema_sha256"] = accounted_output_schema_sha256()
    else:
        observed["output_schema_sha256"] = f"<{payload.__name__}>"
    return observed


def require_accounting_policy_identity(inner: SemanticReasoner) -> None:
    """Raise ``IdentityDrift`` unless every frozen field is observed on ``inner`` and
    equals the protocol literal (the contrastive-path flag must be exactly ``True``)."""
    observed: dict[str, str | bool] = {
        "reasoner_class": type(inner).__name__,
        **observed_identity(inner),
        **_observed_contract(inner),
    }
    for key, expected in EXPECTED_IDENTITY.items():
        if key not in observed:
            raise IdentityDrift(
                f"IDENTITY_DRIFT: {type(inner).__name__} exposes no {key}; expected {expected!r}"
            )
        actual = observed[key]
        drifted = (actual is not expected) if isinstance(expected, bool) else (actual != expected)
        if drifted:
            raise IdentityDrift(
                f"IDENTITY_DRIFT: {type(inner).__name__} {key} observed {actual!r} "
                f"!= frozen {expected!r}"
            )


class BudgetExceeded(RuntimeError):
    pass


class CallRecord(FrozenModel):
    """One forwarded call: the exact rendered request and the ids it made citable."""

    ledger: LedgerId
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
    state_before: IntentState | None = None
    """The governed state when the call was made: after Call 1 for a Call 2."""
    model_payload: dict[str, Any] | None = None
    """The exact payload the model returned, as parsed by the sealed output contract."""
    accountable_evidence_ids: tuple[str, ...] = ()
    """The evidence whose every sentence this call had to account for (design §7.1.3)."""
    refusal_findings: tuple[str, ...] = ()
    """When the adapter refused the whole response structurally (single attempt, EXPERIMENT
    mode, never re-proposed): every finding, by id. Empty for an accepted response."""
    refused_invocation_id: str | None = None


class RunBudget:
    """The one run-scoped tally shared by every ledger's wrapper."""

    def __init__(self) -> None:
        self.frontier_calls = 0
        self.provider_cost_usd = Decimal("0")


class RecordingReasoner:
    def __init__(
        self,
        inner: SemanticReasoner,
        *,
        ledger: LedgerId,
        budget: RunBudget,
        guard_identity: bool,
        state: Callable[[], IntentState] | None = None,
    ) -> None:
        self._guard = guard_identity
        self._state = state
        if guard_identity:
            require_accounting_policy_identity(inner)
        self._inner = inner
        self._ledger: LedgerId = ledger
        self._budget = budget
        self._t: int | None = None
        self._calls_this_delta = 0
        self.records: list[CallRecord] = []
        self.receipts: list[Any] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def begin_delta(self, t: int) -> None:
        self._t = t
        self._calls_this_delta = 0

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        if self._guard:
            require_accounting_policy_identity(self._inner)
        if self._t is None:
            raise BudgetExceeded("NO_DELTA_BEGUN: propose before begin_delta")
        if self._budget.frontier_calls + 1 > MAX_FRONTIER_CALLS:
            raise BudgetExceeded(f"FRONTIER_CEILING: call {self._budget.frontier_calls + 1}")
        if self._calls_this_delta >= CALLS_PER_DELTA:
            raise BudgetExceeded("THIRD_CALL_REFUSED: no retry, fallback or third call")
        if self._budget.provider_cost_usd > _COST_CEILING:
            raise BudgetExceeded(f"COST_CEILING: {self._budget.provider_cost_usd} USD")
        receipts_before = len(getattr(self._inner, "receipts", ()))
        payloads_before = len(getattr(self._inner, "draft_payloads", ()))
        state_before = self._state() if self._state is not None else None
        self._budget.frontier_calls += 1
        self._calls_this_delta += 1
        refusal: ReasonerResponseRefused | None = None
        result: tuple[SemanticJudgment, ...] = ()
        try:
            result = self._inner.propose(request)
        except ReasonerResponseRefused as refused:
            refusal = refused
        # The exact bytes the model saw: this policy's own rendering flags.
        inner_type = type(self._inner)
        rendered = render_request(
            request,
            include_comparison_context=True,
            include_sentence_index=getattr(inner_type, "include_sentence_index", False),
            include_reproposal_notice=getattr(inner_type, "accepts_reproposal", False),
        )
        self.records.append(
            CallRecord(
                ledger=self._ledger,
                t=self._t,
                call=self._calls_this_delta,
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
                state_before=state_before,
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
            )
        )
        for receipt in tuple(getattr(self._inner, "receipts", ()))[receipts_before:]:
            self.receipts.append(receipt)
            cost = getattr(receipt, "cost_usd", None)
            if cost is not None:
                self._budget.provider_cost_usd += Decimal(str(cost))
        if refusal is not None:
            raise refusal
        return result
