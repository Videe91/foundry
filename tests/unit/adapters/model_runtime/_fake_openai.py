"""A double for the OpenAI SDK boundary, and nothing above it.

Everything Foundry owns stays real in these tests — the runtime, the registry, the
adapter. Only the network edge is replaced, because a test that fakes the adapter proves
nothing about the adapter.

The shapes here are copied from the installed ``openai`` 3.19.2 types rather than
invented, and ``output_parsed`` reproduces the real property's logic exactly:

    for output in self.output:
        if output.type == "message":
            for content in output.content:
                if content.type == "output_text" and content.parsed:
                    return content.parsed
    return None

That detail is load-bearing. The real property walks past a refusal and returns ``None``,
which makes "the model refused" and "the model returned nothing parseable" look identical
at this seam. The adapter has to tell them apart deliberately, so the double must not
smooth the difference away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeRefusal:
    """``ResponseOutputRefusal``: an explicit refusal, never a typed success."""

    refusal: str = "I can't help with that."
    type: str = "refusal"


@dataclass
class FakeOutputText:
    """``ParsedResponseOutputText``: carries the parsed structured value."""

    parsed: Any = None
    text: str = ""
    type: str = "output_text"


@dataclass
class FakeMessage:
    """``ParsedResponseOutputMessage``."""

    content: list[Any] = field(default_factory=list)
    type: str = "message"
    role: str = "assistant"
    status: str = "completed"
    phase: str | None = "final_answer"


@dataclass
class FakeReasoningItem:
    """A reasoning item, which carries no parsed output and must be stepped over."""

    type: str = "reasoning"
    summary: list[Any] = field(default_factory=list)


@dataclass
class FakeIncompleteDetails:
    """``IncompleteDetails``. Real reasons: max_output_tokens, max_messages,
    content_filter, steered."""

    reason: str | None = None


@dataclass
class FakeUsage:
    """``ResponseUsage``. Note both token counts are plain ``int`` on the real type."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class FakeResponse:
    """``ParsedResponse`` — including its real ``output_parsed`` semantics."""

    def __init__(
        self,
        *,
        model: str,
        status: str | None = "completed",
        output: list[Any] | None = None,
        usage: FakeUsage | None = None,
        incomplete_details: FakeIncompleteDetails | None = None,
    ) -> None:
        self.model = model
        self.status = status
        self.output = output if output is not None else []
        self.usage = usage
        self.incomplete_details = incomplete_details

    @property
    def output_parsed(self) -> Any:
        for item in self.output:
            if getattr(item, "type", None) == "message":
                for content in item.content:
                    if getattr(content, "type", None) == "output_text" and content.parsed:
                        return content.parsed
        return None


def parsed_response(
    parsed: Any,
    *,
    model: str,
    usage: FakeUsage | None = None,
    status: str = "completed",
) -> FakeResponse:
    """The ordinary success shape: a reasoning item, then a final-answer message.

    The answer travels as JSON text, as it does on the wire. Without ``text_format`` the real
    SDK leaves ``parsed`` as ``None``; the adapter validates the text itself.
    """
    return FakeResponse(
        model=model,
        status=status,
        usage=usage,
        output=[
            FakeReasoningItem(),
            FakeMessage(content=[FakeOutputText(parsed=None, text=parsed.model_dump_json())]),
        ],
    )


def refusal_response(*, model: str, refusal: str = "I can't help with that.") -> FakeResponse:
    """A completed response whose content is a refusal rather than the schema."""
    return FakeResponse(
        model=model,
        status="completed",
        output=[FakeMessage(content=[FakeRefusal(refusal=refusal)])],
    )


class FakeResponses:
    """``client.responses``. Records every call; performs exactly what it is told."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._outcomes:
            raise AssertionError("responses.parse called more times than the test allowed")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(**kwargs)
        return outcome


class FakeClient:
    """``OpenAI``. Retains construction kwargs so client-level laws are checkable."""

    def __init__(self, outcomes: list[Any], **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.responses = FakeResponses(outcomes)


class RecordingClientFactory:
    """Stands in for the ``OpenAI(...)`` constructor and remembers what it was given."""

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
    def parse_calls(self) -> list[dict[str, Any]]:
        """Every ``responses.parse`` call across every client this factory built."""
        return [call for client in self.clients for call in client.responses.calls]

    @property
    def only_parse_call(self) -> dict[str, Any]:
        calls = self.parse_calls
        if len(calls) != 1:
            raise AssertionError(f"expected exactly one parse call, saw {len(calls)}")
        return calls[0]
