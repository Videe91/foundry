"""A double for the Anthropic SDK boundary, and nothing above it.

Everything Foundry owns stays real (the runtime, the registry, the adapter); only the network
edge is replaced. The shapes follow the installed ``anthropic`` 1.x types: ``Message`` carries
``model``, ``content`` (typed blocks), ``stop_reason``, ``stop_details`` and ``usage``, and
``messages.stream(...)`` is a context manager whose ``get_final_message()`` returns it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeThinking:
    """Thinking blocks carry no answer and must be stepped over."""

    thinking: str = ""
    signature: str = "sig"
    type: str = "thinking"


@dataclass
class FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class FakeStopDetails:
    category: str | None = None
    explanation: str | None = None
    type: str = "refusal"


@dataclass
class FakeMessage:
    model: str
    content: list[Any] = field(default_factory=list)
    stop_reason: str | None = "end_turn"
    stop_details: FakeStopDetails | None = None
    usage: FakeUsage | None = None


def answer(json_text: str, *, model: str, usage: FakeUsage | None = None) -> FakeMessage:
    """The ordinary success shape: a thinking block, then one text block of JSON."""
    return FakeMessage(model=model, content=[FakeThinking(), FakeText(json_text)], usage=usage)


class _Stream:
    def __init__(self, outcome: Any, kwargs: dict[str, Any]) -> None:
        self._outcome = outcome
        self._kwargs = kwargs

    def __enter__(self) -> _Stream:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> Any:
        if callable(self._outcome):
            return self._outcome(**self._kwargs)
        return self._outcome


class FakeMessages:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _Stream:
        self.calls.append(kwargs)
        if not self._outcomes:
            raise AssertionError("messages.stream called more times than the test allowed")
        return _Stream(self._outcomes.pop(0), kwargs)

    def create(self, **kwargs: Any) -> Any:
        raise AssertionError("the adapter streams; messages.create must not be called")


class FakeClient:
    def __init__(self, outcomes: list[Any], **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.messages = FakeMessages(outcomes)


class RecordingClientFactory:
    """Stands in for the ``Anthropic(...)`` constructor and remembers what it was given."""

    def __init__(self, *outcomes: Any) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.clients: list[FakeClient] = []

    def __call__(self, **kwargs: Any) -> FakeClient:
        self.calls.append(kwargs)
        client = FakeClient(self._outcomes, **kwargs)
        self.clients.append(client)
        return client

    @property
    def stream_calls(self) -> list[dict[str, Any]]:
        return [call for client in self.clients for call in client.messages.calls]

    @property
    def only_call(self) -> dict[str, Any]:
        calls = self.stream_calls
        if len(calls) != 1:
            raise AssertionError(f"expected exactly one stream call, saw {len(calls)}")
        return calls[0]
