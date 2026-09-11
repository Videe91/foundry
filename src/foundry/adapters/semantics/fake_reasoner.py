"""Deterministic scripted reasoner for tests (Intent Intelligence v2, plan §4.3).

The live provider adapter (xAI/Grok) is deliberately deferred to a later integration
task. This fake is the ONLY ``SemanticReasoner`` used under test in 9N: zero model or
API calls occur anywhere in the 9N test suite.

``ScriptedSemanticReasoner`` returns the judgments it was constructed with and records
every ``ReasoningRequest`` it receives in ``requests`` so tests can assert that the
reasoner was given bounded inputs and nothing more.
"""

from __future__ import annotations

from foundry.domain.semantic_judgment import ReasonerFingerprint, SemanticJudgment
from foundry.ports.semantic_reasoner import ReasoningRequest


class ScriptedSemanticReasoner:
    def __init__(
        self,
        fingerprint: ReasonerFingerprint,
        judgments: tuple[SemanticJudgment, ...],
    ) -> None:
        self._fingerprint = fingerprint
        self._judgments = judgments
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return self._fingerprint

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        return self._judgments
