"""Recording wrappers: every model call of the run, as it happened, under a hard budget.

Each wrapper is transparent to the runtime (every attribute it does not define is the wrapped
port's own, so policy identity, ``checks_consistency`` and the sentence-index flag pass through
unchanged) and records the bounded request and the answer -- or the error -- before returning or
re-raising it. Nothing is repaired, retried or reordered. A call beyond the budget is refused
before it reaches the provider, and that refusal is recorded too.
"""

from __future__ import annotations

from typing import Any

from foundry.experiments.intent_engine_e2e.scenario import SCENARIO
from foundry.experiments.intent_engine_live_v1 import protocol

__all__ = ["BudgetExceeded", "CallLog", "RecordingIE3", "RecordingVerifier", "RecordingWriter"]


class BudgetExceeded(RuntimeError):
    """The sealed call budget would be exceeded; the call is not made."""


def _dump(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else value


class CallLog:
    def __init__(self, role: str, limit: int) -> None:
        self.role = role
        self.limit = limit
        self.records: list[dict[str, Any]] = []

    def admit(self) -> int:
        if len(self.records) >= self.limit:
            raise BudgetExceeded(f"{self.role}: the sealed budget of {self.limit} calls is spent")
        return len(self.records) + 1

    def record(self, number: int, request: Any, answer: Any, error: BaseException | None) -> None:
        self.records.append(
            {
                "role": self.role,
                "call": number,
                "request": _dump(request),
                "answer": _dump(answer),
                "error": None if error is None else f"{type(error).__name__}: {error}",
            }
        )


class _Recording:
    _inner: Any
    log: CallLog

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _call(self, method: str, request: Any) -> Any:
        number = self.log.admit()
        try:
            answer = getattr(self._inner, method)(request)
        except BaseException as error:
            self.log.record(number, request, None, error)
            raise
        self.log.record(number, request, answer, None)
        return answer


class RecordingWriter(_Recording):
    """Call 1 and Call 2, two calls per step at most."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.log = CallLog("WRITER", protocol.MAX_WRITER_CALLS_PER_STEP * len(SCENARIO.steps))

    def propose(self, request: Any) -> Any:
        return self._call("propose", request)

    def propose_accounted(self, request: Any) -> Any:
        return self._call("propose_accounted", request)


class RecordingVerifier(_Recording):
    """The semantic admission verifier, one call per step at most."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.log = CallLog("VERIFIER", protocol.MAX_VERIFIER_CALLS_PER_STEP * len(SCENARIO.steps))

    def verify(self, request: Any) -> Any:
        return self._call("verify", request)


class RecordingIE3(_Recording):
    """The graph synthesizer, once."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.log = CallLog("IE3", protocol.MAX_IE3_CALLS)

    def synthesize(self, request: Any) -> Any:
        return self._call("synthesize", request)
