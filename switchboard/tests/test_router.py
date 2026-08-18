"""Packet: P-002 — Switchboard Routing.

One job: test route_call — the tag gate, role resolution, the provider call,
and the fallback chain. Fully offline via an injected fake completion_fn.

Version: 0.2.0
"""

from __future__ import annotations

from datetime import timezone

import pytest
from pydantic import ValidationError

from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.request import Message, SwitchboardRequest
from switchboard.router import ProviderCallError, route_call
from switchboard.tags import CallTags, MissingTagsError

PRIMARY = "primary/model-a"
FALLBACK = "backup/model-b"
LAST_RESORT = "backup/model-c"

REGISTRY = ModelRegistry(
    roles={
        "builder": RoleRoute(
            model=PRIMARY,
            fallbacks=[FALLBACK, LAST_RESORT],
            max_tokens=4096,
        ),
        "default": RoleRoute(model="default/model-d", fallbacks=[], max_tokens=1024),
    }
)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class FakeCompletion:
    """Mimics the LiteLLM response shape and records every call it receives."""

    def __init__(self, answer: str = "an answer", failing: tuple[str, ...] = ()) -> None:
        self.answer = answer
        self.failing = failing
        self.calls: list[dict[str, object]] = []

    def __call__(
        self, model: str, messages: list[dict[str, str]], max_tokens: int
    ) -> _FakeResponse:
        self.calls.append(
            {"model": model, "messages": messages, "max_tokens": max_tokens}
        )
        if model in self.failing:
            raise RuntimeError(f"provider {model} is unavailable")
        return _FakeResponse(self.answer)


def _request(**tag_values: object) -> SwitchboardRequest:
    tag_values.setdefault("project_id", "foundry")
    tag_values.setdefault("department", "floor")
    tag_values.setdefault("role", "builder")
    return SwitchboardRequest(
        tags=CallTags(**tag_values),
        messages=[Message(role="user", content="ping")],
    )


def test_valid_call_returns_ok_with_model_and_content() -> None:
    fake = FakeCompletion(answer="pong")

    response = route_call(_request(packet_id="P-002"), REGISTRY, fake)

    assert response.status == "ok"
    assert response.model_used == PRIMARY
    assert response.content == "pong"
    assert response.tags.project_id == "foundry"
    assert response.tags.role == "builder"
    assert response.tags.packet_id == "P-002"


def test_response_carries_utc_timestamp() -> None:
    response = route_call(_request(), REGISTRY, FakeCompletion())

    assert response.received_at.tzinfo is not None
    assert response.received_at.utcoffset() == timezone.utc.utcoffset(None)


def test_primary_failure_falls_back_to_next_model() -> None:
    fake = FakeCompletion(answer="from the backup", failing=(PRIMARY,))

    response = route_call(_request(), REGISTRY, fake)

    assert response.model_used == FALLBACK
    assert response.content == "from the backup"
    assert [call["model"] for call in fake.calls] == [PRIMARY, FALLBACK]


def test_all_models_failing_raises_provider_call_error_naming_each() -> None:
    fake = FakeCompletion(failing=(PRIMARY, FALLBACK, LAST_RESORT))

    with pytest.raises(ProviderCallError) as excinfo:
        route_call(_request(), REGISTRY, fake)

    message = str(excinfo.value)
    assert PRIMARY in message
    assert FALLBACK in message
    assert LAST_RESORT in message
    assert len(fake.calls) == 3


def test_tag_gate_runs_before_any_provider_call() -> None:
    fake = FakeCompletion()

    with pytest.raises(MissingTagsError) as excinfo:
        route_call(_request(project_id=""), REGISTRY, fake)

    assert "project_id" in str(excinfo.value)
    assert len(fake.calls) == 0


def test_missing_role_blocks_the_call() -> None:
    fake = FakeCompletion()

    with pytest.raises(MissingTagsError) as excinfo:
        route_call(_request(role=""), REGISTRY, fake)

    assert "role" in str(excinfo.value)
    assert len(fake.calls) == 0


def test_invalid_department_blocks_the_call() -> None:
    fake = FakeCompletion()

    with pytest.raises(MissingTagsError) as excinfo:
        route_call(_request(department="marketing"), REGISTRY, fake)

    assert "marketing" in str(excinfo.value)
    assert len(fake.calls) == 0


def test_empty_messages_list_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SwitchboardRequest(
            tags=CallTags(project_id="foundry", department="floor", role="builder"),
            messages=[],
        )


def test_completion_receives_plain_dicts_and_the_roles_max_tokens() -> None:
    fake = FakeCompletion()
    request = SwitchboardRequest(
        tags=CallTags(project_id="foundry", department="floor", role="builder"),
        messages=[
            Message(role="system", content="be brief"),
            Message(role="user", content="ping"),
        ],
    )

    route_call(request, REGISTRY, fake)

    call = fake.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "ping"},
    ]
    assert all(isinstance(item, dict) for item in call["messages"])
    assert call["max_tokens"] == 4096


def test_unknown_role_routes_through_the_default_entry() -> None:
    fake = FakeCompletion()

    response = route_call(_request(role="archivist"), REGISTRY, fake)

    assert response.model_used == "default/model-d"
    assert fake.calls[0]["max_tokens"] == 1024


def test_optional_tags_may_be_omitted() -> None:
    response = route_call(_request(), REGISTRY, FakeCompletion())

    assert response.tags.packet_id is None
    assert response.tags.ticket_id is None
    assert response.tags.attempt_number is None
