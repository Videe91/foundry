"""A durable gap that intent synthesis can record without inventing a classification.

The frozen ``Gap`` requires both ``materiality`` and ``risk``. Neither producer of a
synthesis gap supplies them honestly: a deterministic T7 blocker is a structural fact
about the substrate, not a graded judgement, and a frozen ``GapProposal`` carries no
materiality or risk at all. Choosing ``LOW`` to satisfy the schema would fabricate a
classification nobody made, and it would be durable and unreviewable once written.

``domain/gaps.py`` is a sealed comparative-experiment artifact, so ``Gap`` cannot be
relaxed in place. This subtype widens exactly those two fields for the synthesis path
and leaves every other legacy gap untouched.
"""

from __future__ import annotations

from pydantic import Field

from foundry.domain.common import Materiality, RiskLevel
from foundry.domain.gaps import Gap

__all__ = ["IntentSynthesisGap"]


class IntentSynthesisGap(Gap):
    """A first-class, resolvable gap produced by intent synthesis.

    It travels the ordinary ledger — ``GAP_RECORDED`` → ``IntentState.gaps`` — so it can
    be resolved, waived, read by closure and picked up by jobs exactly like any other
    gap. There is no second gap plane.
    """

    # Widening an inherited required field is a Liskov violation, and mypy is right to
    # flag it: a reader typed against ``Gap.materiality`` could receive ``None``. It is
    # accepted for the same reason as D12 — the frozen base demands a value, synthesis
    # genuinely does not have one, closure reads ``blocking`` rather than either field,
    # and editing the sealed base is prohibited.
    materiality: Materiality | None = Field(default=None)  # type: ignore[assignment]
    """``None`` means synthesis has not classified materiality. It does not mean ``LOW``."""

    risk: RiskLevel | None = Field(default=None)  # type: ignore[assignment]
    """``None`` means synthesis has not classified risk. It does not mean ``LOW``."""

    scope: tuple[str, ...] = ()
    """Scopes this gap applies to, by the usual convention: ``()`` is project-wide.

    Explicit scope exists because the legacy alternative is unsafe. ``_gap_applies``
    treats an unknown ``affected_object_ids`` entry as applying, so routing claim or
    locus ids through that field would silently promote a scope-local blocker into a
    project-wide one.
    """

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """Optional model metadata. ``None`` is absence of a number, not zero confidence.

    Nothing in closure or governance reads it, and neither ``risk`` nor ``materiality``
    is ever derived from it.
    """

    locus_representative_id: str | None = Field(default=None, min_length=1)
    """Traceability for a deterministic runtime blocker."""

    affected_claim_ids: tuple[str, ...] = ()
    """Traceability for a deterministic runtime blocker; never used for scope matching."""

    subject_key: str | None = Field(default=None, min_length=1)
    """Traceability for a model-returned ambiguity."""

    model_gap_proposal_id: str | None = Field(default=None, min_length=1)
    """The raw model gap id, metadata only. It is never the durable ``id``."""

    # Deliberately absent: ``source_event_ids``. The frozen ``GapProposal`` carries them,
    # but the synthesis request exposes no event ids at all, so any the model returned
    # would be invented. The ``EventEnvelope`` is the ledger provenance.
