"""Call 2 with at most one production re-proposal (design 2026-09-29; IE2 v2 design §7.1.4).

``claim_call`` makes Call 2 once. Only with ``mode`` in ``REPROPOSE_MODES`` (production), only
after a whole-response structural refusal (``ReasonerResponseRefused``) whose every finding is on
the IE2 allowlist, and only for a reasoner whose policy declares ``accepts_reproposal``, it
records the refusal (``STRUCTURAL_REFUSAL_RECORDED``, no state change) and asks ONCE more with
the same request plus the fixed notice. A second refusal is recorded and raised. There is no
loop: one ``try``, one second attempt, never a third. Anything else propagates unchanged, exactly
as the two-call orchestrator (``incremental_assimilation``) always did.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from foundry.application.semantic_governance import SemanticGovernor
from foundry.domain.admission import AdmissionDecision
from foundry.domain.structural_refusal import (
    REPROPOSE_MODES,
    ExecutionMode,
    RefusalEngine,
    ReproposalNotice,
    StructuralRefusal,
    refusal_codes,
    reproposable,
)
from foundry.ports.semantic_reasoner import (
    ReasonerResponseRefused,
    ReasoningRequest,
    SemanticReasoner,
)

__all__ = ["claim_call"]


def _request_sha256(request: ReasoningRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _refusal(
    refused: ReasonerResponseRefused,
    *,
    mode: ExecutionMode,
    attempt: Literal[1, 2],
    request: ReasoningRequest,
    reasoner: SemanticReasoner,
    reproposal_of: str | None = None,
) -> StructuralRefusal:
    engine = RefusalEngine.IE2_CLAIM_ASSIMILATION
    return StructuralRefusal(
        engine=engine,
        mode=mode,
        attempt=attempt,
        request_sha256=_request_sha256(request.model_copy(update={"reproposal": None})),
        reasoner=reasoner.fingerprint,
        findings=refused.findings,
        codes=refusal_codes(refused.findings),
        reproposable=reproposable(engine, refused.findings),
        invocation_id=refused.invocation_id,
        proposal_json=refused.proposal_json or "{}",
        reproposal_of=reproposal_of,
        notice=request.reproposal,
    )


def claim_call(
    governor: SemanticGovernor,
    reasoner: SemanticReasoner,
    request: ReasoningRequest,
    mode: ExecutionMode | None,
) -> tuple[tuple[AdmissionDecision, ...], tuple[StructuralRefusal, ...], int]:
    """Call 2, with at most one production re-proposal. Returns decisions, the recorded
    refusal of a replaced attempt, and the number of Call-2 attempts made (1 or 2)."""
    try:
        return governor.propose_and_submit(reasoner, request), (), 1
    except ReasonerResponseRefused as refused:
        if mode not in REPROPOSE_MODES:
            raise
        assert mode is not None
        first = _refusal(refused, mode=mode, attempt=1, request=request, reasoner=reasoner)
        recorded = governor.record_structural_refusal(first)
        if not first.reproposable or not getattr(type(reasoner), "accepts_reproposal", False):
            raise
    retry = request.model_copy(update={"reproposal": ReproposalNotice(findings=first.findings)})
    try:
        return governor.propose_and_submit(reasoner, retry), (first,), 2
    except ReasonerResponseRefused as again:
        governor.record_structural_refusal(
            _refusal(
                again,
                mode=mode,
                attempt=2,
                request=retry,
                reasoner=reasoner,
                reproposal_of=recorded.event.event_id,
            )
        )
        raise
