from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.proposals import (
    IntelligenceUsage,
    IntentIntelligencePayload,
    IntentIntelligenceResult,
)


class FakeIntentIntelligence:
    def __init__(
        self,
        payload: IntentIntelligencePayload,
        usage: IntelligenceUsage | None = None,
    ) -> None:
        self._payload = payload
        self._usage = IntelligenceUsage() if usage is None else usage

    def analyze(self, request: IntelligenceInput) -> IntentIntelligenceResult:
        return IntentIntelligenceResult(payload=self._payload, usage=self._usage)
