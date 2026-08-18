"""Packet: P-001 — Switchboard Scaffold.

One job: test the CallTags model and the tag gate validation.

Version: 0.1.0
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from switchboard.tags import CallTags, MissingTagsError, validate_tags


def test_valid_tags_pass_validation() -> None:
    tags = CallTags(project_id="foundry", department="floor", role="builder")

    assert validate_tags(tags) is None


def test_missing_project_id_raises_missing_tags_error() -> None:
    tags = CallTags(department="floor", role="builder")

    with pytest.raises(MissingTagsError) as excinfo:
        validate_tags(tags)

    assert "project_id" in str(excinfo.value)


def test_missing_role_raises_missing_tags_error() -> None:
    tags = CallTags(project_id="foundry", department="floor")

    with pytest.raises(MissingTagsError) as excinfo:
        validate_tags(tags)

    assert "role" in str(excinfo.value)


def test_invalid_department_raises_missing_tags_error() -> None:
    tags = CallTags(project_id="foundry", department="marketing", role="builder")

    with pytest.raises(MissingTagsError) as excinfo:
        validate_tags(tags)

    assert "marketing" in str(excinfo.value)


def test_extra_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CallTags(
            project_id="foundry",
            department="floor",
            role="builder",
            urgency="high",
        )


def test_optional_fields_may_be_omitted() -> None:
    tags = CallTags(project_id="foundry", department="floor", role="builder")

    assert tags.packet_id is None
    assert tags.ticket_id is None
    assert tags.attempt_number is None


def test_optional_fields_are_accepted_when_present() -> None:
    tags = CallTags(
        project_id="foundry",
        department="floor",
        role="builder",
        packet_id="P-001",
        ticket_id="T-014",
        attempt_number=2,
    )

    assert validate_tags(tags) is None
    assert tags.packet_id == "P-001"
    assert tags.ticket_id == "T-014"
    assert tags.attempt_number == 2


def test_empty_required_tag_is_treated_as_missing() -> None:
    tags = CallTags(project_id="   ", department="floor", role="builder")

    with pytest.raises(MissingTagsError) as excinfo:
        validate_tags(tags)

    assert "project_id" in str(excinfo.value)
