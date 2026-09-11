"""Evidence ingestion contract for Intent Intelligence v2.

Architectural role: every input to semantic reasoning — a human sentence, a
source file, a test, a ticket, a pull request, an agent transcript — enters the
system as an :class:`EvidenceItem`. Evidence is *not* intent. It carries no
authority and no semantic conclusion; it is the bounded, content-addressed
material a reasoner is allowed to see and a judgment may cite by ``evidence_id``.

Design notes:

* One constructor for any evidence. Human typed text is simply
  ``source_kind=HUMAN, source_ref="human://<actor>"``; nothing here privileges
  one source kind over another.
* ``content_sha256`` is validated against ``content`` so a stored item cannot
  silently drift from the bytes the reasoner actually saw.
* ``scope=()`` means project-wide, the same convention as ``SemanticBase.scope``.
* :class:`DigRecord` is the thin, provider-neutral shape a future dig emits;
  :func:`evidence_from_dig` is the only translation into evidence.

This module is pure domain: no I/O, no provider imports.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel, SourceKind

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


def sha256_of_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class EvidenceItem(FrozenModel):
    evidence_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    scope: tuple[str, ...] = ()
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=_SHA256_HEX_PATTERN)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_content_hash(self) -> EvidenceItem:
        expected = sha256_of_content(self.content)
        if self.content_sha256 != expected:
            raise ValueError(
                f"content_sha256 {self.content_sha256} does not match content hash {expected}"
            )
        return self


def evidence_item(
    *,
    evidence_id: str,
    project_id: str,
    source_kind: SourceKind,
    source_ref: str,
    content: str,
    observed_at: datetime,
    scope: tuple[str, ...] = (),
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        project_id=project_id,
        scope=scope,
        source_kind=source_kind,
        source_ref=source_ref,
        content=content,
        content_sha256=sha256_of_content(content),
        observed_at=observed_at,
    )


class DigRecord(FrozenModel):
    locator: str = Field(min_length=1)
    kind: SourceKind
    content: str = Field(min_length=1)
    scope: tuple[str, ...] = ()
    observed_at: datetime


def evidence_from_dig(record: DigRecord, *, project_id: str, evidence_id: str) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=project_id,
        source_kind=record.kind,
        source_ref=record.locator,
        content=record.content,
        observed_at=record.observed_at,
        scope=record.scope,
    )
