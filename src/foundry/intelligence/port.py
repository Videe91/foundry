from typing import Protocol

from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.proposals import IntentIntelligenceResult


class IntentIntelligence(Protocol):
    def analyze(self, request: IntelligenceInput) -> IntentIntelligenceResult: ...
