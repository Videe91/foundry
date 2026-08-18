"""Packet: P-001 — Switchboard Scaffold.

One job: define the Foundry tag block, the allowed department values, and the
validation that makes "no tags, no call" executable.

Version: 0.1.0
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

ALLOWED_DEPARTMENTS: tuple[str, ...] = (
    "intent",
    "cortex",
    "design_studio",
    "floor",
    "adversarial",
    "deploy",
    "post_deploy",
)

REQUIRED_TAGS: tuple[str, ...] = ("project_id", "department", "role")


class MissingTagsError(Exception):
    """Raised when a call's tags are absent, empty, or not an allowed value."""

    def __init__(self, message: str, missing: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.missing = missing


class CallTags(BaseModel):
    """The Foundry tag block carried by every switchboard call."""

    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str = ""
    department: str = ""
    role: str = ""
    packet_id: str | None = None
    ticket_id: str | None = None
    attempt_number: int | None = None


def validate_tags(tags: CallTags) -> None:
    """Enforce the tag gate. Returns None when the tags are valid."""
    missing = tuple(
        name for name in REQUIRED_TAGS if not str(getattr(tags, name)).strip()
    )
    if missing:
        raise MissingTagsError(
            f"missing or empty required tags: {', '.join(missing)}",
            missing,
        )

    if tags.department not in ALLOWED_DEPARTMENTS:
        raise MissingTagsError(
            f"department '{tags.department}' is not an allowed Foundry "
            f"department; allowed: {', '.join(ALLOWED_DEPARTMENTS)}"
        )
