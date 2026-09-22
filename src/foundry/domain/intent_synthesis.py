"""Intent Synthesis vocabulary and durable identity (Slice-1 task T1).

Design spec: ``docs/superpowers/specs/2026-09-22-intent-synthesis-bridge-design.md``.

This module is the *altitude boundary* made concrete. Intent synthesis asks what the
human means; semantic reasoning asks what the evidence says. They never share a
vocabulary, so ``JudgmentKind``, ``JudgmentProposal`` and ``AdmissionRoute`` are not
extended or reused here — ``IntentSynthesisRoute`` is a separate enum (spec §3, I14).

Trust boundary (spec §9.2, C17)
-------------------------------
A synthesizer proposes MEANING and nothing else. The model-facing schema cannot
express ``authority``, ``author``, ``basis_locus_ids``, ``scope``, ``object_id``,
``project_id``, ``provenance``, ``relations``, ``lifecycle``, ``revision``,
``materiality``, ``requires_metric``, ``requires_verification`` or any identity —
``FrozenModel``'s ``extra="forbid"`` is the enforcement. Runtime owns every one of them.

In particular ``authority`` is absent BY DESIGN and must stay absent: the
anti-invention guard (spec §10.3) is tested by injecting an illegal authority at the
runtime routing layer, never by adding a field here for test convenience (C17).

Durable identity (spec §9.4, I21)
---------------------------------
``event_id`` uniqueness is GLOBAL — ``uq_intent_events_event_id`` carries no
``project_id`` and ``InMemoryEventStore`` keeps one process-wide id set — so a
model-chosen id can repeat across projects, across synthesis runs and across retries.
The raw ``model_proposal_id`` is therefore never a durable identity by itself. Every
durable id derives from ``proposal_instance_id``, which is a deterministic function of
``(project_id, synthesis_run_id, model_proposal_id)``. Because ``synthesis_run_id`` is
persisted in ``INTENT_SYNTHESIS_DECIDED``, an interrupted run recomputes byte-identical
ids on recovery with no provider call.

Pure domain: no I/O, no clock, no randomness, no provider import.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel, Materiality
from foundry.domain.semantic import SemanticKind
from foundry.intelligence.proposals import GapProposal

__all__ = [
    "IntentDisposition",
    "IntentSynthesisDecision",
    "IntentSynthesisPolicy",
    "IntentSynthesisProposal",
    "IntentSynthesisResult",
    "IntentSynthesisRoute",
    "InvalidationReason",
    "RequirementSynthesisProposal",
    "SynthesisIdentity",
    "SynthesisOrigin",
]


class SynthesisOrigin(StrEnum):
    """Who authored the proposal. Determined by runtime from the author, NEVER from
    the basis: human-authored basis claims do not make a model-written statement
    ``HUMAN_STATED`` (spec §10.1, C9/I22 anti-laundering law)."""

    HUMAN_STATED = "HUMAN_STATED"
    DETERMINISTIC_NORMALIZATION = "DETERMINISTIC_NORMALIZATION"
    AI_INFERRED = "AI_INFERRED"
    RESEARCH_DERIVED = "RESEARCH_DERIVED"


class IntentDisposition(StrEnum):
    """What the proposal does to existing intent (spec §9.3, C3).

    ``EXISTING_UNCHANGED`` is a SUCCESS, not a refusal: the correct outcome is that no
    duplicate durable intent is created.
    """

    NEW = "NEW"
    EXISTING_UNCHANGED = "EXISTING_UNCHANGED"
    REPLACES_STALE = "REPLACES_STALE"


class IntentSynthesisRoute(StrEnum):
    """Where governance sends a synthesis proposal.

    Deliberately NOT ``AdmissionRoute``: the semantic vocabulary stays untouched
    (spec §3, I14), and synthesis needs ``NO_CHANGE``, which has no semantic analogue.
    """

    APPLY = "APPLY"
    NO_CHANGE = "NO_CHANGE"
    REQUIRE_SECOND_LENS = "REQUIRE_SECOND_LENS"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"
    REJECT = "REJECT"


class InvalidationReason(StrEnum):
    """Why a durable ``DECIDED(APPLY)`` was terminally not applied (spec §10.8, C13).

    Bounded by design: the ledger stays analysable, so this is never free text.
    """

    BASIS_CHANGED = "BASIS_CHANGED"
    TARGET_CHANGED = "TARGET_CHANGED"
    AUTHORITY_CHANGED = "AUTHORITY_CHANGED"


def _digest(*parts: str) -> str:
    """Deterministic 16-hex digest over an UNAMBIGUOUS encoding of ``parts``.

    Two properties are load-bearing, and both exist because ``model_proposal_id`` is
    UNTRUSTED model output while ``event_id`` uniqueness is GLOBAL (spec §9.4, I21).

    *Unambiguous encoding.* A canonical JSON array is used rather than the
    ``f"{a}|{b}"`` join of ``semantic_reducer._minted_id``: a bare separator join lets
    a crafted id shift a boundary — ``("P|R", "X", "Y")``, ``("P", "R|X", "Y")`` and
    ``("P", "R", "X|Y")`` all collapse to one digest — forging a durable-id collision.
    JSON string escaping removes that class of collision. ``_minted_id``'s inputs are
    both runtime-owned ids, so its simpler join is safe in its own context and is left
    unchanged; it is a separate path outside this slice.

    *Full width.* The FULL 64-hex SHA-256 is returned, never a truncation. An earlier
    draft truncated to 16 hex (64 bits), which was never approved: having removed
    boundary forgery through the encoding, there is no reason to discard most of the
    digest immediately afterwards and reintroduce birthday-collision headroom on ids
    that are globally unique and partly attacker-influenced.
    """
    canonical = json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SynthesisIdentity(FrozenModel):
    """Runtime-owned durable identity for one proposal (spec §9.4, I21).

    Every component is runtime-owned except ``model_proposal_id``, which is
    model-local and never a durable identity on its own.
    """

    project_id: str = Field(min_length=1)
    synthesis_run_id: str = Field(min_length=1)
    model_proposal_id: str = Field(min_length=1)

    @property
    def proposal_instance_id(self) -> str:
        return "SYN-" + _digest(
            "proposal_instance", self.project_id, self.synthesis_run_id, self.model_proposal_id
        )

    def object_id(self, prefix: str) -> str:
        """The durable id of the object this proposal would mint, if applied."""
        return f"{prefix}-" + _digest("object", self.proposal_instance_id, prefix)

    def event_id(self, step: str) -> str:
        """The durable id of one event in this proposal's lifecycle.

        ``step`` is a plain string rather than an enum so T1 does not pre-empt the
        event vocabulary introduced by T3.
        """
        return "EVT-" + _digest("event", self.proposal_instance_id, step)


class IntentSynthesisProposal(FrozenModel):
    """Shared fields of a synthesis proposal. Meaning only — never authority.

    ``model_proposal_id`` is named for what it is: the model's own local handle,
    meaningful ONLY within one result. Durable identity comes from
    ``SynthesisIdentity``.
    """

    model_proposal_id: str = Field(min_length=1)
    target_kind: SemanticKind
    disposition: IntentDisposition
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    basis_claim_ids: tuple[str, ...] = Field(min_length=1)
    relates_to_object_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_disposition_matrix(self) -> IntentSynthesisProposal:
        """The STRUCTURAL half of the §9.3 matrix.

        The remaining rules — the named object must exist in ``known_intent_objects``,
        ``REPLACES_STALE`` may name only a stale object, and ``EXISTING_UNCHANGED`` may
        not name a stale one — all require request or governed state and are enforced
        at request assembly (T7) and routing (T6). They are not knowable here.
        """
        if self.disposition is IntentDisposition.NEW:
            if self.relates_to_object_id is not None:
                raise ValueError("disposition NEW must not name relates_to_object_id")
        elif self.relates_to_object_id is None:
            raise ValueError(f"disposition {self.disposition} requires relates_to_object_id")
        return self


class RequirementSynthesisProposal(IntentSynthesisProposal):
    """The ONLY Slice-1 variant (spec §9.1, C5).

    A single generic proposal cannot honestly instantiate ten kinds, because the domain
    types carry required kind-specific fields — ``Assumption.risk_level``,
    ``Contract.observable``, ``Decision.rationale``. Each further kind needs its own
    variant and its own design before entering ``allowed_target_kinds``.
    """

    target_kind: Literal[SemanticKind.REQUIREMENT] = SemanticKind.REQUIREMENT


class IntentSynthesisResult(FrozenModel):
    """What one synthesizer invocation returns: proposals, or gaps explaining why not."""

    proposals: tuple[RequirementSynthesisProposal, ...] = ()
    gap_proposals: tuple[GapProposal, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_model_proposal_ids(self) -> IntentSynthesisResult:
        """Two proposals sharing a model id would derive ONE durable identity (§9.4)."""
        seen: set[str] = set()
        for proposal in self.proposals:
            if proposal.model_proposal_id in seen:
                raise ValueError(
                    f"duplicate model_proposal_id in one result: {proposal.model_proposal_id}"
                )
            seen.add(proposal.model_proposal_id)
        return self


class IntentSynthesisPolicy(FrozenModel):
    """Governance knobs. Defaults are the Slice-1 pinning of spec §17.4.

    No kind and no materiality level is material in Slice 1, which is safe because the
    slice admits only ``HUMAN_STATED`` (which needs a covering ``AuthorityRecord``
    regardless) and ``AI_INFERRED`` at ``LOW`` materiality (``PROPOSED``,
    non-contractual, non-blocking). The general policy is open decision D3.
    """

    material_target_kinds: frozenset[SemanticKind] = frozenset()
    material_materiality_levels: frozenset[Materiality] = frozenset()
    canonical_requires_authority: bool = True


class IntentSynthesisDecision(FrozenModel):
    """The route taken for one proposal, with its reasons. Mirrors ``AdmissionDecision``."""

    proposal_instance_id: str = Field(min_length=1)
    route: IntentSynthesisRoute
    reasons: tuple[str, ...] = Field(min_length=1)
    corroborating_proposal_instance_ids: tuple[str, ...] = ()
