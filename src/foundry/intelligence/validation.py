from __future__ import annotations

import re

from foundry.intelligence.errors import IntelligenceValidationError
from foundry.intelligence.input import IntelligenceInput
from foundry.intelligence.kinds import IntelligenceSemanticKind
from foundry.intelligence.proposals import (
    GapProposal,
    IntentIntelligenceResult,
    SemanticProposal,
)

_SUBJECT_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ALLOWED_KIND_VALUES = frozenset(kind.value for kind in IntelligenceSemanticKind)


def validate_intelligence_result(
    request: IntelligenceInput,
    result: IntentIntelligenceResult,
) -> IntentIntelligenceResult:
    semantics = result.payload.semantic_proposals
    gaps = result.payload.gap_proposals
    known_events = set(request.source_event_ids)
    semantic_ids = tuple(proposal.proposal_id for proposal in semantics)

    _reject_duplicate(semantic_ids, "duplicate semantic proposal_id: ")
    _reject_duplicate(tuple(gap.proposal_id for gap in gaps), "duplicate gap proposal_id: ")
    _reject_duplicate_gap_identities(gaps)
    _reject_invalid_subject_keys(gaps)
    _reject_unknown_source_events(semantics, known_events, "semantic")
    _reject_unknown_source_events(gaps, known_events, "gap")
    _reject_unknown_affected_proposals(gaps, set(semantic_ids))
    _reject_invalid_confidence(semantics, "semantic")
    _reject_invalid_confidence(gaps, "gap")
    _reject_disallowed_kinds(semantics)
    return result


def _reject_duplicate(values: tuple[str, ...], prefix: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise IntelligenceValidationError(prefix + value)
        seen.add(value)


def _reject_duplicate_gap_identities(gaps: tuple[GapProposal, ...]) -> None:
    seen: set[tuple[str, str]] = set()
    for gap in gaps:
        identity = (_kind_value(gap.kind), gap.subject_key)
        if identity in seen:
            raise IntelligenceValidationError(
                "duplicate gap identity: " + identity[0] + ":" + identity[1]
            )
        seen.add(identity)


def _reject_invalid_subject_keys(gaps: tuple[GapProposal, ...]) -> None:
    for gap in gaps:
        if _SUBJECT_KEY.fullmatch(gap.subject_key) is None:
            raise IntelligenceValidationError("invalid subject_key: " + gap.subject_key)


def _reject_unknown_source_events(
    proposals: tuple[SemanticProposal, ...] | tuple[GapProposal, ...],
    known_events: set[str],
    label: str,
) -> None:
    for proposal in proposals:
        for event_id in proposal.source_event_ids:
            if event_id not in known_events:
                raise IntelligenceValidationError(
                    "unknown source_event_id on "
                    + label
                    + " proposal "
                    + proposal.proposal_id
                    + ": "
                    + event_id
                )


def _reject_unknown_affected_proposals(
    gaps: tuple[GapProposal, ...],
    semantic_ids: set[str],
) -> None:
    for gap in gaps:
        for proposal_id in gap.affected_proposal_ids:
            if proposal_id not in semantic_ids:
                raise IntelligenceValidationError(
                    "unknown affected_proposal_id on gap proposal "
                    + gap.proposal_id
                    + ": "
                    + proposal_id
                )


def _reject_invalid_confidence(
    proposals: tuple[SemanticProposal, ...] | tuple[GapProposal, ...],
    label: str,
) -> None:
    for proposal in proposals:
        if not 0.0 <= proposal.confidence <= 1.0:
            raise IntelligenceValidationError(
                "invalid confidence on "
                + label
                + " proposal "
                + proposal.proposal_id
                + ": "
                + str(proposal.confidence)
            )


def _reject_disallowed_kinds(proposals: tuple[SemanticProposal, ...]) -> None:
    for proposal in proposals:
        if _kind_value(proposal.kind) not in _ALLOWED_KIND_VALUES:
            raise IntelligenceValidationError(
                "disallowed semantic kind on proposal "
                + proposal.proposal_id
                + ": "
                + _kind_value(proposal.kind)
            )


def _kind_value(kind: object) -> str:
    value = getattr(kind, "value", kind)
    return str(value)
