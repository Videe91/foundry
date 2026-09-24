"""A double for the xAI SDK transport, not for the Model Runtime.

The runtime and the adapter under test are real; only the network boundary is replaced.
Response and usage are built from the SDK's **own proto types**, so the fields the adapter
reads are the fields the real SDK exposes — a hand-rolled stub could drift from the
protocol it claims to stand in for and the tests would never notice.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from xai_sdk.proto import chat_pb2, usage_pb2


def sampling_usage(
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_in_usd_ticks: int | None = None,
) -> usage_pb2.SamplingUsage:
    """Real SDK usage proto. Omitted fields stay genuinely unreported."""
    usage = usage_pb2.SamplingUsage()
    if prompt_tokens is not None:
        usage.prompt_tokens = prompt_tokens
    if completion_tokens is not None:
        usage.completion_tokens = completion_tokens
    if cost_in_usd_ticks is not None:
        usage.cost_in_usd_ticks = cost_in_usd_ticks
    return usage


class FakeResponse:
    """Mirrors exactly the ``xai_sdk.chat.Response`` surface the adapter touches."""

    def __init__(
        self,
        *,
        model: str,
        usage: usage_pb2.SamplingUsage | None = None,
        finish_reason: str | None = "FINISH_REASON_STOP",
        finish_reason_raises: Exception | None = None,
    ) -> None:
        self._proto = chat_pb2.GetChatCompletionResponse(model=model)
        self._usage = usage if usage is not None else usage_pb2.SamplingUsage()
        self._finish_reason = finish_reason
        self._finish_reason_raises = finish_reason_raises

    @property
    def proto(self) -> chat_pb2.GetChatCompletionResponse:
        return self._proto

    @property
    def usage(self) -> usage_pb2.SamplingUsage:
        return self._usage

    @property
    def finish_reason(self) -> str:
        if self._finish_reason_raises is not None:
            raise self._finish_reason_raises
        if self._finish_reason is None:
            raise AttributeError("this response reports no finish reason")
        return self._finish_reason


class FakeChat:
    """One prepared chat. Records the shape it was asked to parse."""

    def __init__(
        self,
        *,
        response: FakeResponse,
        parsed: object,
        parse_raises: Exception | None = None,
    ) -> None:
        self._response = response
        self._parsed = parsed
        self._parse_raises = parse_raises
        self.parse_shapes: list[type] = []

    def parse(self, shape: type[BaseModel]) -> tuple[FakeResponse, object]:
        self.parse_shapes.append(shape)
        if self._parse_raises is not None:
            raise self._parse_raises
        return self._response, self._parsed


class FakeChatNamespace:
    def __init__(self, chats: list[FakeChat], create_calls: list[dict[str, Any]]) -> None:
        self._chats = chats
        self.create_calls = create_calls

    def create(self, **kwargs: Any) -> FakeChat:
        self.create_calls.append(kwargs)
        if not self._chats:
            raise AssertionError("chat.create called more times than the test scripted")
        return self._chats.pop(0)


class FakeXAIClient:
    """Stands in for ``xai_sdk.Client``; records how it was constructed."""

    def __init__(self, **client_kwargs: Any) -> None:
        self.client_kwargs = client_kwargs
        self.chats: list[FakeChat] = []
        self.create_calls: list[dict[str, Any]] = []
        self.chat = FakeChatNamespace(self.chats, self.create_calls)

    def script(self, chat: FakeChat) -> None:
        self.chats.append(chat)


class RecordingClientFactory:
    """Captures every client construction so timeout wiring is provable."""

    def __init__(self, *chats: FakeChat, raises: Exception | None = None) -> None:
        self._chats = list(chats)
        self._raises = raises
        self.constructions: list[dict[str, Any]] = []
        self.clients: list[FakeXAIClient] = []

    def __call__(self, **kwargs: Any) -> FakeXAIClient:
        self.constructions.append(kwargs)
        client = FakeXAIClient(**kwargs)
        for chat in self._chats:
            client.script(chat)
        self._chats = []
        self.clients.append(client)
        return client

    @property
    def create_calls(self) -> list[dict[str, Any]]:
        return [call for client in self.clients for call in client.create_calls]
