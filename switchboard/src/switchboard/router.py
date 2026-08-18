"""Packet: P-001 — Switchboard Scaffold.

One job: the single entry point that validates a call's tags and returns a
stub response. No provider integration, no network — the gate only.

Version: 0.1.0
"""

from __future__ import annotations

from datetime import datetime, timezone

from switchboard.request import SwitchboardRequest, SwitchboardResponse
from switchboard.tags import validate_tags

STUB_STATUS = "stub"


def route_call(request: SwitchboardRequest) -> SwitchboardResponse:
    """Validate the request's tags, then return a stub response.

    Raises MissingTagsError when a required tag is missing or empty, or when
    the department is not an allowed Foundry department.
    """
    validate_tags(request.tags)

    return SwitchboardResponse(
        status=STUB_STATUS,
        tags=request.tags,
        received_at=datetime.now(timezone.utc),
    )
