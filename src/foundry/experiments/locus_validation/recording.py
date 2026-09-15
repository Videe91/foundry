"""The recording, budgeted, identity-guarded wrapper around the locus reasoner.

Spec §8 (identity gates 4, 5, 8 applied to the live instance), §10 (a guarded
reasoner: construction refuses a non-locus identity, and drift is refused before
every forwarded call), §12 (8 / 0 / 0 / 0 / 0 / 2.00, enforced BEFORE forwarding) and
the L3 request-only reference law (one ``RequestRecord`` bound 1:1 to one
``RequestReferenceSnapshot`` per forwarded call, captured from the very request
object the model receives).

Law of this module: it records structural facts only (ids, hashes, counts, kinds) and
decides nothing about meaning. It never changes a request, never touches the returned
judgments, never retries and never fabricates: a call that raises leaves no record and
no snapshot -- the frontier call was ADMITTED (``frontier_calls`` counts it) but not
answered, and that asymmetry is the evidence. It is a request-path module: it must
never import the hidden answer key or any grading module, and it never constructs a
provider client -- the inner reasoner is supplied by the caller. No key, header or
secret is ever read or recorded; a record holds only what the model itself was shown.

The reused ``RequestRecord`` / ``RequestReferenceSnapshot`` types carry ``arm="F"``
fixed (the locus policy is the successor of the contrastive F path; the types carry no
policy pinning) so the frozen 9P3 ``request_only_reference_check`` applies unchanged;
the ledger identity lives on the wrapper and on the experiment's own documents, never
inferred from ``arm``.

The frozen 9P2 ``RecordingReasoner`` and 9P3 ``BudgetedReasoner`` are deliberately not
reused: they pin historical policies. Identity is read as the INSTANCE resolves it --
the adapter sends ``self.system_instruction`` -- so an instance attribute shadowing a
class variable is what is observed.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import Field

from foundry.adapters.semantics.xai_reasoner import render_request
from foundry.application.contrastive_context import (
    comparison_context_character_count,
    historical_evidence_ids,
)
from foundry.domain.common import FrozenModel
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.experiments.contrastive_unseen.records import RequestRecord
from foundry.experiments.locus_validation.protocol import (
    CALLS_PER_DELTA,
    MAX_COST_USD,
    MAX_FRONTIER_CALLS,
    MODEL,
    POLICY_VERSION_FROZEN,
    PROMPT_SHA256_FROZEN,
    PROVIDER,
    REASONING_EFFORT,
    Ledger,
)
from foundry.experiments.long_horizon_bounded.runner import (
    RequestReferenceSnapshot,
    snapshot_request_references,
)
from foundry.ports.semantic_reasoner import ReasoningRequest, SemanticReasoner

__all__ = [
    "BudgetExceeded",
    "BudgetSnapshot",
    "ExperimentBudget",
    "IdentityDrift",
    "LocusRecordingReasoner",
    "observed_identity",
    "require_locus_identity",
]

_ARM: Final[Literal["F"]] = "F"
_COST_CEILING: Final[Decimal] = Decimal(str(MAX_COST_USD))
_INCLUDE_COMPARISON_CONTEXT: Final = True

_EXPECTED_IDENTITY: Final[dict[str, str | bool]] = {
    "provider": PROVIDER,
    "model": MODEL,
    "fingerprint_policy_version": POLICY_VERSION_FROZEN,
    "policy_version": POLICY_VERSION_FROZEN,
    "system_prompt_sha256": PROMPT_SHA256_FROZEN,
    "include_comparison_context": _INCLUDE_COMPARISON_CONTEXT,
    "reasoning_effort": REASONING_EFFORT,
}


# --------------------------------------------------------------------------- errors


class IdentityDrift(RuntimeError):
    """The wrapped reasoner's observable identity is not the frozen locus identity.
    Raised at construction or BEFORE a call is forwarded; never after."""


class BudgetExceeded(RuntimeError):
    """A ceiling would be breached by the next call; raised BEFORE it is forwarded.
    ``reason`` is one of ``FRONTIER_CEILING``, ``THIRD_CALL_REFUSED``,
    ``COST_CEILING`` or ``NO_DELTA_BEGUN``."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


# --------------------------------------------------------------------------- identity


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def observed_identity(inner: SemanticReasoner) -> dict[str, str | bool]:
    """What ``inner`` observably IS, keyed by the frozen field each value must equal:
    provider, model and policy version from its fingerprint; the class-level
    ``policy_version``, sha256 of ``system_instruction`` and
    ``include_comparison_context`` when the class carries them, each read as the
    instance resolves it; the reasoning effort from ``reasoning_effort`` or the
    adapter's ``_reasoning_effort``. A field the reasoner does not expose is absent."""
    fingerprint = inner.fingerprint
    cls = type(inner)
    observed: dict[str, str | bool] = {
        "provider": fingerprint.provider,
        "model": fingerprint.model,
        "fingerprint_policy_version": fingerprint.policy_version,
    }
    if hasattr(cls, "policy_version"):
        observed["policy_version"] = str(getattr(inner, "policy_version"))  # noqa: B009
    if hasattr(cls, "system_instruction"):
        instruction = getattr(inner, "system_instruction")  # noqa: B009
        observed["system_prompt_sha256"] = (
            _sha256(instruction)
            if isinstance(instruction, str)
            else f"<{type(instruction).__name__}>"
        )
    if hasattr(cls, "include_comparison_context"):
        flag = getattr(inner, "include_comparison_context")  # noqa: B009
        observed["include_comparison_context"] = flag if isinstance(flag, bool) else repr(flag)
    for attribute in ("reasoning_effort", "_reasoning_effort"):
        if hasattr(inner, attribute):
            observed["reasoning_effort"] = str(getattr(inner, attribute))
            break
    return observed


def require_locus_identity(inner: SemanticReasoner) -> None:
    """Raise ``IdentityDrift`` unless every frozen field is observed on ``inner`` and
    equals the protocol literal (the contrastive-path flag must be exactly ``True``)."""
    observed = observed_identity(inner)
    for key, expected in _EXPECTED_IDENTITY.items():
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


# --------------------------------------------------------------------------- budget


class BudgetSnapshot(FrozenModel):
    """The shared budget as it stood when a document was assembled."""

    frontier_calls: int = Field(ge=0)
    provider_cost_usd: str
    judge_calls: int = Field(ge=0)
    human_authorizations: int = Field(ge=0)


class ExperimentBudget:
    """The one mutable, run-scoped tally shared by both ledgers' wrappers.

    ``judge_calls`` and ``human_authorizations`` are 0 for the life of the run: no
    judge and no human authority exist in this harness, and nothing here changes them.
    """

    def __init__(self) -> None:
        self.frontier_calls: int = 0
        self.provider_cost_usd: Decimal = Decimal("0")
        self.judge_calls: int = 0
        self.human_authorizations: int = 0

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            frontier_calls=self.frontier_calls,
            provider_cost_usd=str(self.provider_cost_usd),
            judge_calls=self.judge_calls,
            human_authorizations=self.human_authorizations,
        )


# --------------------------------------------------------------------------- wrapper


class LocusRecordingReasoner:
    """A ``SemanticReasoner`` that guards, budgets and records every call it forwards.

    ``propose`` order (load-bearing, spec §10 / §12): identity re-check; ceilings
    (frontier, per-delta, cost, delta begun); raw reference capture from the exact
    request; admit (count) the call; forward; on return bind one record to one
    snapshot and account the new receipts. On exception nothing is appended and the
    exception is re-raised unchanged.
    """

    def __init__(
        self, inner: SemanticReasoner, *, ledger: Ledger, budget: ExperimentBudget
    ) -> None:
        require_locus_identity(inner)
        self._inner = inner
        self._ledger: Ledger = ledger
        self._budget = budget
        self._t: int | None = None
        self._calls_this_delta = 0
        self._records: list[RequestRecord] = []
        self._snapshots: list[RequestReferenceSnapshot] = []

    # --- configuration ------------------------------------------------------------

    @property
    def inner(self) -> SemanticReasoner:
        return self._inner

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    @property
    def budget(self) -> ExperimentBudget:
        return self._budget

    # --- SemanticReasoner protocol ------------------------------------------------

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._inner.fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        # (a) identity: the reasoner must still be the locus policy, before anything.
        require_locus_identity(self._inner)
        # (b) ceilings, all before forwarding.
        budget = self._budget
        if budget.frontier_calls + 1 > MAX_FRONTIER_CALLS:
            raise BudgetExceeded(
                "FRONTIER_CEILING",
                f"call {budget.frontier_calls + 1} would exceed {MAX_FRONTIER_CALLS}; "
                "refused before forwarding",
            )
        if self._calls_this_delta >= CALLS_PER_DELTA:
            raise BudgetExceeded(
                "THIRD_CALL_REFUSED",
                f"ledger {self._ledger} T{self._t} already made {CALLS_PER_DELTA} calls; "
                "no retry, fallback or third call is permitted",
            )
        if budget.provider_cost_usd > _COST_CEILING:
            raise BudgetExceeded(
                "COST_CEILING",
                f"recorded provider cost {budget.provider_cost_usd} USD exceeds "
                f"{_COST_CEILING} USD; refusing call {budget.frontier_calls + 1}",
            )
        if self._t is None:
            raise BudgetExceeded(
                "NO_DELTA_BEGUN", "propose called before begin_delta(t); nothing forwarded"
            )
        t = self._t
        # (c) raw reference capture from the exact request object.
        refs = snapshot_request_references(request)
        receipts_before = len(self.receipts)
        # (d) admit the call: counted whether or not it is answered.
        budget.frontier_calls += 1
        self._calls_this_delta += 1
        call_number: Literal[1, 2] = 1 if self._calls_this_delta == 1 else 2
        # (e) forward; an exception leaves no record and no snapshot.
        result = self._inner.propose(request)
        # (f) bind one record to one snapshot; account the new receipts.
        rendered = render_request(request, include_comparison_context=_INCLUDE_COMPARISON_CONTEXT)
        request_sha256 = _sha256(rendered)
        self._records.append(
            RequestRecord(
                arm=_ARM,
                t=t,
                call_number=call_number,
                policy_version=POLICY_VERSION_FROZEN,
                system_prompt_sha256=PROMPT_SHA256_FROZEN,
                rendered_user_request=rendered,
                request_sha256=request_sha256,
                citable_evidence_ids=refs[0],
                historical_comparison_evidence_ids=historical_evidence_ids(
                    request.comparison_context
                ),
                known_address_ids=refs[1],
                known_claim_ids=refs[2],
                allowed_judgment_kinds=tuple(
                    sorted(kind.value for kind in request.allowed_judgment_kinds)
                ),
                comparison_context_chars=comparison_context_character_count(
                    request.comparison_context
                ),
            )
        )
        self._snapshots.append(
            RequestReferenceSnapshot(
                arm=_ARM,
                t=t,
                call_number=call_number,
                request_sha256=request_sha256,
                citable_evidence_ids=refs[0],
                known_address_ids=refs[1],
                known_claim_ids=refs[2],
                known_claim_creating_judgment_ids=refs[3],
            )
        )
        for receipt in self.receipts[receipts_before:]:
            cost = getattr(receipt, "cost_usd", None)
            if cost is None:
                raise RuntimeError("RECEIPT_INTEGRITY: receipt carries no cost_usd")
            budget.provider_cost_usd += Decimal(str(cost))
        return result

    # --- delta accounting ---------------------------------------------------------

    def begin_delta(self, t: int) -> None:
        """Start delta ``t``: resets the per-delta call counter (at most 2 calls)."""
        self._t = t
        self._calls_this_delta = 0

    # --- captured evidence --------------------------------------------------------

    @property
    def records(self) -> tuple[RequestRecord, ...]:
        return tuple(self._records)

    @property
    def snapshots(self) -> tuple[RequestReferenceSnapshot, ...]:
        return tuple(self._snapshots)

    @property
    def receipts(self) -> tuple[Any, ...]:
        """``inner.receipts`` when the inner reasoner exposes them, else ``()``."""
        return tuple(getattr(self._inner, "receipts", ()))

    @property
    def draft_payloads(self) -> tuple[Any, ...]:
        """``inner.draft_payloads`` when the inner reasoner exposes them, else ``()``."""
        return tuple(getattr(self._inner, "draft_payloads", ()))
