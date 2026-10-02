"""Semantic completeness verifier port (IE2 Call 3; ``ie2-verified-assimilation-v1``).

Provider-neutral. A verifier receives one bounded ``CompletenessRequest`` (every proposition a
claim-writing proposal listed, its source sentences, and the claims disposing of it) and returns
a ``CompletenessReport`` (policy v1), ``StructuredCompletenessReport`` (policy v2) or
``VerdictCompletenessReport`` (policy v3, the runtime contract): one verdict per proposition.
It never receives an event store or state, never proposes, rewrites or disposes of a claim, and
never decides admission: the application records its answer and applies the law of its policy
(all-or-nothing for v1 and v2; per minimal safe unit, with gaps, for v3). Its identity is
reported by the execution itself (``verifier``), so independence from the writer is checked
against what actually ran.
"""

from __future__ import annotations

from typing import Protocol

from foundry.domain.common import FrozenModel
from foundry.domain.semantic_completeness import (
    CompletenessReport,
    CompletenessRequest,
    StructuredCompletenessReport,
    VerdictCompletenessReport,
    VerifierIdentity,
)

__all__ = ["CompletenessVerification", "SemanticCompletenessVerifier"]


class CompletenessVerification(FrozenModel):
    report: CompletenessReport | StructuredCompletenessReport | VerdictCompletenessReport | None
    """``None`` when the verifier's answer could not be parsed as a report (never repaired);
    otherwise in the format of the verifier's policy (v1 regions, v2 structured findings)."""
    verifier: VerifierIdentity
    invocation_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    wall_clock_ms: int | None = None


class SemanticCompletenessVerifier(Protocol):
    def verify(self, request: CompletenessRequest) -> CompletenessVerification: ...
