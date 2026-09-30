"""Semantic reasoner port (Intent Intelligence v2, spec §10, §20.1).

The reasoner is compute, not memory (Law 3). It receives a bounded
``ReasoningRequest`` — the exact evidence and the exact known objects it is allowed to
see — and returns proposals. It NEVER receives an ``EventStore`` or ``IntentState``,
and it never mutates state: every return value is a ``SemanticJudgment`` that only
deterministic admission may apply or refuse (spec §4.3).

Provider-neutral. No vendor payload shapes appear here or in any judgment.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from pydantic import Field, model_validator

from foundry.domain.common import FrozenModel
from foundry.domain.evidence import EvidenceItem
from foundry.domain.proposition_accounting import AccountedProposition
from foundry.domain.semantic_identity import SemanticAddress, SemanticClaim
from foundry.domain.semantic_judgment import JudgmentKind, ReasonerFingerprint, SemanticJudgment
from foundry.domain.structural_refusal import ReproposalNotice


class ContextRelation(StrEnum):
    """Structural (not semantic) reason a piece of history is shown (9P2 spec §8, §9).

    Every member names an explicit edge Foundry can follow deterministically:
    evidence lineage, current effective-evidence links, claim-to-address placement,
    and the active claim profile of an address. None of them says what the history
    *means* — no member classifies a transition as support, correction, conflict, or
    new meaning. That judgement belongs to the model and to admission.
    """

    SUPERSEDES = "SUPERSEDES"
    EFFECTIVE_EVIDENCE_OF = "EFFECTIVE_EVIDENCE_OF"
    CLAIM_AT_ADDRESS = "CLAIM_AT_ADDRESS"
    ACTIVE_CLAIM_PROFILE = "ACTIVE_CLAIM_PROFILE"


class ContextInclusionEdge(FrozenModel):
    """One auditable step of the structural path that justified including context.

    ``source_id --relation--> target_id``. Ids here are references into request-only
    context and are NON-CITABLE: appearing in an edge does not make an id admissible
    evidence for a model draft. Only ids in ``ReasoningRequest.evidence`` are citable.
    """

    source_id: str = Field(min_length=1)
    relation: ContextRelation
    target_id: str = Field(min_length=1)


class EvidenceTransitionContext(FrozenModel):
    """Old-to-new evidence transition shown to the model as comparison material.

    Request-only structural history. ``historical_diff`` is a deterministic rendered
    diff of predecessor to current evidence and may be empty. ``touched_claim_ids``
    and ``touched_address_ids`` are the existing objects structurally reached from
    the predecessor; ``inclusion_edges`` is the non-empty audit trail of how they were
    reached. Nothing here is evidence, a judgment, or semantic authority, and the
    predecessor evidence id is not citable unless it is also in ``ReasoningRequest.evidence``.
    """

    current_evidence_id: str = Field(min_length=1)
    predecessor_evidence_id: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    historical_diff: str
    touched_claim_ids: tuple[str, ...] = ()
    touched_address_ids: tuple[str, ...] = ()
    inclusion_edges: tuple[ContextInclusionEdge, ...] = Field(min_length=1)


class ComparisonContext(FrozenModel):
    """Ephemeral, provider-neutral comparison context carried on a ``ReasoningRequest``.

    This is request context only (9P2 spec §8, §15, §16): not canonical state, not a
    semantic object, not an event, not a judgment, never persisted as truth, and never
    a source of semantic authority. It records deterministic structural facts that
    explain why prior material is being shown; the model still decides meaning and
    deterministic admission still decides whether any proposal can affect state.
    Ids inside it are non-citable.
    """

    transitions: tuple[EvidenceTransitionContext, ...] = ()
    active_claim_profile_edges: tuple[ContextInclusionEdge, ...] = ()


class ReasoningRequest(FrozenModel):
    """Bounded, task-specific context. Whole-project state is forbidden by design.

    ``allowed_judgment_kinds`` makes the reasoning task EXPLICIT (task 9O §7): the
    caller states which kinds of judgment the reasoner may return, and an adapter must
    treat any other kind as a structural failure rather than inferring the task from
    which fields happen to be empty. The default permits every kind so that scripted
    fakes and earlier callers keep working unchanged.

    ``comparison_context`` (9P2) is request-only structural history: bounded prior
    material and the structural edges that justified showing it. It is never evidence
    and never semantic authority; its ids are non-citable. It defaults to empty so
    existing callers are unchanged.
    """

    project_id: str = Field(min_length=1)
    evidence: tuple[EvidenceItem, ...]
    focus_object_ids: tuple[str, ...] = ()
    known_addresses: tuple[SemanticAddress, ...] = ()
    known_claims: tuple[SemanticClaim, ...] = ()
    allowed_judgment_kinds: frozenset[JudgmentKind] = Field(
        default_factory=lambda: frozenset(JudgmentKind)
    )
    comparison_context: ComparisonContext = Field(default_factory=ComparisonContext)
    accountable_evidence_ids: tuple[str, ...] = ()
    """Evidence whose every sentence a claim-writing response must account for (IE2 v2
    design §7.1.3): the delta items Call 1 applied a CREATE or BIND for. Structural
    bookkeeping chosen from admissions, never a meaning decision. Empty by default, so
    earlier callers are unchanged; only a policy that accounts for propositions reads it."""

    reproposal: ReproposalNotice | None = None
    """Set only on a production re-proposal (the single bounded second attempt after a
    deterministic structural refusal): the fixed notice and the refusal findings, never what
    to do. Every other field is the refused attempt's request, unchanged. Only a policy that
    accepts re-proposals may receive it."""

    @model_validator(mode="after")
    def accountable_evidence_is_request_evidence(self) -> ReasoningRequest:
        present = {item.evidence_id for item in self.evidence}
        stray = [e for e in self.accountable_evidence_ids if e not in present]
        if stray:
            raise ValueError(f"accountable evidence not in the request: {stray}")
        return self


class ReasonerResponseRefused(Exception):  # noqa: N818 - a refusal, not an internal error
    """A reasoner's whole response was refused by a deterministic structural law of its answer
    contract, before any judgment existed (provider-neutral; adapters subclass it).

    ``findings`` are ``CODE: detail`` strings naming every id at fault. ``invocation_id`` keys
    the adapter's receipt of the refused call; ``proposal_json`` is the refused proposal as the
    contract parsed it. Nothing of the response is ever applied or repaired."""

    def __init__(
        self,
        message: str,
        *,
        findings: tuple[str, ...],
        invocation_id: str | None = None,
        proposal_json: str | None = None,
    ) -> None:
        super().__init__(message)
        self.findings = findings
        self.invocation_id = invocation_id
        self.proposal_json = proposal_json


class SemanticReasoner(Protocol):
    @property
    def fingerprint(self) -> ReasonerFingerprint: ...

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]: ...


class AccountedProposal(FrozenModel):
    """A claim-writing answer with its own proposition accounting (provider-neutral).

    ``judgments`` are exactly what ``propose`` returns. ``propositions`` are the propositions
    the model itself listed (id, source sentence ids, its own statement); ``disposed_by`` maps
    each judgment that disposes of a proposition to that proposition's id. Bookkeeping only:
    nothing here is state, and nothing is applied until admission.
    """

    judgments: tuple[SemanticJudgment, ...]
    propositions: tuple[AccountedProposition, ...] = ()
    disposed_by: Mapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def dispositions_name_known_judgments_and_propositions(self) -> AccountedProposal:
        judgments = {j.judgment_id for j in self.judgments}
        propositions = {p.proposition_id for p in self.propositions}
        for judgment_id, proposition_id in self.disposed_by.items():
            if judgment_id not in judgments or proposition_id not in propositions:
                raise ValueError(f"disposition {judgment_id} -> {proposition_id} is unknown")
        return self


class AccountingSemanticReasoner(SemanticReasoner, Protocol):
    """A reasoner whose claim-writing answer carries its proposition accounting."""

    def propose_accounted(self, request: ReasoningRequest) -> AccountedProposal: ...
