"""The durable record of one atomic correction set (design 2026-09-30, authority v2).

A correction set is every ASSERT_CLAIM at one address and every SUPERSEDE of a claim at that
address, proposed together in one non-human response. It is decided as ONE unit: PENDING
(nothing of it is current), AGREED (every member applied in one transition) or DECLINED
(nothing of it ever applies). The member judgments stay the only semantic content; this record
holds ids, the deterministic basis and the terminal decision.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel

__all__ = [
    "CORRECTION_SET_MEMBER",
    "CorrectionSetOutcome",
    "CorrectionSetRecord",
    "CorrectionSetStatus",
]

CORRECTION_SET_MEMBER: Final = "CORRECTION_SET_MEMBER"
"""The first admission reason of every held member of a PENDING correction set."""

CorrectionSetStatus = Literal["PENDING", "AGREED", "DECLINED"]
CorrectionSetOutcome = Literal["AGREE", "DECLINE"]


class CorrectionSetRecord(FrozenModel):
    correction_set_id: str = Field(min_length=1)
    """Instance identity: ``CSET-`` + sha256(project, invocation, address)."""
    address_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    proposer: str = Field(min_length=1)
    """``provider:model@policy`` of the proposing (non-human) reasoner."""
    assertion_judgment_ids: tuple[str, ...]
    supersede_judgment_ids: tuple[str, ...] = Field(min_length=1)
    target_judgment_ids: tuple[str, ...] = Field(min_length=1)
    """Sorted, distinct: the judgments whose claims the set retires."""
    basis_content_hashes: tuple[str, ...]
    """Sorted, distinct sha256 of the content of the evidence the assertions cite."""
    equivalence_key: str = Field(min_length=1)
    """Decline/repeat identity: ``CEQ-`` + sha256(project, address, targets, basis hashes)."""
    status: CorrectionSetStatus = "PENDING"
    decided_by: str | None = None
    decision_event_id: str | None = None
    authority_record_id: str | None = None
    rationale: str | None = None

    @property
    def member_judgment_ids(self) -> tuple[str, ...]:
        """Assertions first, then supersessions: the order an AGREE applies them in."""
        return (*self.assertion_judgment_ids, *self.supersede_judgment_ids)

    @model_validator(mode="after")
    def validate_shape(self) -> CorrectionSetRecord:
        members = self.member_judgment_ids
        if len(set(members)) != len(members):
            raise ValueError("a correction set lists each member once")
        if tuple(sorted(set(self.target_judgment_ids))) != self.target_judgment_ids:
            raise ValueError("target_judgment_ids are sorted and distinct")
        if tuple(sorted(set(self.basis_content_hashes))) != self.basis_content_hashes:
            raise ValueError("basis_content_hashes are sorted and distinct")
        decided = (self.decided_by, self.decision_event_id, self.authority_record_id)
        if (self.status == "PENDING") != all(x is None for x in decided):
            raise ValueError("only a decided correction set carries its decision")
        return self
