"""Semantic reasoner port (Intent Intelligence v2, spec §10, §20.1).

The reasoner is compute, not memory (Law 3). It receives a bounded
``ReasoningRequest`` — the exact evidence and the exact known objects it is allowed to
see — and returns proposals. It NEVER receives an ``EventStore`` or ``IntentState``,
and it never mutates state: every return value is a ``SemanticJudgment`` that only
deterministic admission may apply or refuse (spec §4.3).

Provider-neutral. No vendor payload shapes appear here or in any judgment.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from foundry.domain.common import FrozenModel
from foundry.domain.evidence import EvidenceItem
from foundry.domain.semantic_identity import SemanticAddress, SemanticClaim
from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment


class ReasoningRequest(FrozenModel):
    """Bounded, task-specific context. Whole-project state is forbidden by design."""

    project_id: str = Field(min_length=1)
    evidence: tuple[EvidenceItem, ...]
    focus_object_ids: tuple[str, ...] = ()
    known_addresses: tuple[SemanticAddress, ...] = ()
    known_claims: tuple[SemanticClaim, ...] = ()


class SemanticReasoner(Protocol):
    @property
    def fingerprint(self) -> ReasonerFingerprint: ...

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]: ...
