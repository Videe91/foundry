"""Packet: P-001 — Switchboard Scaffold.

One job: test route_call — the tag gate and the stub response.

Version: 0.1.0
"""

from __future__ import annotations

from datetime import timezone

import pytest

from switchboard.request import SwitchboardRequest
from switchboard.router import route_call
from switchboard.tags import CallTags, MissingTagsError


def _request(**tag_values: object) -> SwitchboardRequest:
    return SwitchboardRequest(tags=CallTags(**tag_values), prompt="ping")


def test_valid_tags_return_stub_and_echo_tags() -> None:
    request = _request(
        project_id="foundry",
        department="floor",
        role="builder",
        packet_id="P-001",
    )

    response = route_call(request)

    assert response.status == "stub"
    assert response.tags.project_id == "foundry"
    assert response.tags.department == "floor"
    assert response.tags.role == "builder"
    assert response.tags.packet_id == "P-001"


def test_response_carries_utc_timestamp() -> None:
    response = route_call(
        _request(project_id="foundry", department="floor", role="builder")
    )

    assert response.received_at.tzinfo is not None
    assert response.received_at.utcoffset() == timezone.utc.utcoffset(None)


def test_missing_project_id_blocks_the_call() -> None:
    with pytest.raises(MissingTagsError) as excinfo:
        route_call(_request(department="floor", role="builder"))

    assert "project_id" in str(excinfo.value)


def test_missing_role_blocks_the_call() -> None:
    with pytest.raises(MissingTagsError) as excinfo:
        route_call(_request(project_id="foundry", department="floor"))

    assert "role" in str(excinfo.value)


def test_invalid_department_blocks_the_call() -> None:
    with pytest.raises(MissingTagsError) as excinfo:
        route_call(
            _request(project_id="foundry", department="marketing", role="builder")
        )

    assert "marketing" in str(excinfo.value)


def test_optional_tags_may_be_omitted() -> None:
    response = route_call(
        _request(project_id="foundry", department="floor", role="builder")
    )

    assert response.status == "stub"
    assert response.tags.packet_id is None
    assert response.tags.ticket_id is None
    assert response.tags.attempt_number is None
