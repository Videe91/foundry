"""The budgeted, identity-guarded, recording wrapper around the reasoner (design §9, §10).

It records structural facts only (what each request showed, what came back, what it
cost) and decides nothing about meaning. Ceilings are enforced before forwarding; nothing
is retried. On the live path it applies v1's identity guard unchanged
(``require_locus_identity``): the policy, prompt, schema, model and effort under test are
the same literals. The request path never imports the answer key.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Final

from foundry.adapters.semantics.xai_reasoner import render_request
from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.experiments.locus_validation.recording import require_locus_identity
from foundry.experiments.locus_validation_v2.protocol import (
    CALLS_PER_DELTA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    LedgerId,
)
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = ["BudgetExceeded", "CallRecord", "RecordingReasoner", "RunBudget"]

_COST_CEILING: Final = Decimal(str(MAX_COST_USD))


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
    ) -> None:
        self._guard = guard_identity
        if guard_identity:
            require_locus_identity(inner)
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
            require_locus_identity(self._inner)
        if self._t is None:
            raise BudgetExceeded("NO_DELTA_BEGUN: propose before begin_delta")
        if self._budget.frontier_calls + 1 > MAX_FRONTIER_CALLS:
            raise BudgetExceeded(f"FRONTIER_CEILING: call {self._budget.frontier_calls + 1}")
        if self._calls_this_delta >= CALLS_PER_DELTA:
            raise BudgetExceeded("THIRD_CALL_REFUSED: no retry, fallback or third call")
        if self._budget.provider_cost_usd > _COST_CEILING:
            raise BudgetExceeded(f"COST_CEILING: {self._budget.provider_cost_usd} USD")
        receipts_before = len(getattr(self._inner, "receipts", ()))
        self._budget.frontier_calls += 1
        self._calls_this_delta += 1
        result = self._inner.propose(request)
        rendered = render_request(request, include_comparison_context=True)
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
            )
        )
        for receipt in tuple(getattr(self._inner, "receipts", ()))[receipts_before:]:
            self.receipts.append(receipt)
            cost = getattr(receipt, "cost_usd", None)
            if cost is not None:
                self._budget.provider_cost_usd += Decimal(str(cost))
        return result
