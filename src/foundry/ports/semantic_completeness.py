"""Semantic completeness verifier port (IE2 Call 3; ``ie2-verified-assimilation-v1``).

Provider-neutral. A verifier receives one bounded ``CompletenessRequest`` (every proposition a
claim-writing proposal listed, its source sentences, and the claims disposing of it) and returns
a ``CompletenessReport``: one verdict per proposition. It never receives an event store or state,
never proposes, rewrites or disposes of a claim, and never decides admission: the application
records its answer and applies the all-or-nothing law. Its identity is reported by the execution
itself (``verifier``), so independence from the writer is checked against what actually ran.
"""

from __future__ import annotations

from typing import Protocol

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    VerifierIdentity,
)

__all__ = ["CompletenessVerification", "SemanticCompletenessVerifier"]


class CompletenessVerification(FrozenModel):
    report: CompletenessReport | None
    """``None`` when the verifier's answer could not be parsed as a report (never repaired)."""
    verifier: VerifierIdentity
    invocation_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    wall_clock_ms: int | None = None


class SemanticCompletenessVerifier(Protocol):
    def verify(self, request: CompletenessRequest) -> CompletenessVerification: ...
