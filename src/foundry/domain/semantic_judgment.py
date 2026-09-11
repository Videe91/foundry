"""Semantic judgment contract (Intent Intelligence v2, spec §4, §10, §20.1, §25).

A ``SemanticJudgment`` is the ONLY shape in which a semantic conclusion may enter
Foundry. It is a structured, provenance-bearing PROPOSAL. AI may propose one; AI may
never apply one. Deterministic code (T5 admission, T4 reducer) applies or refuses it.

Judgment kinds
--------------
``CREATE_ADDRESS``, ``BIND_TO_ADDRESS``, ``EQUIVALENT``, ``DISTINCT``, ``CONFLICTS_WITH``
and ``SUPERSEDE`` are the task's minimum list. ``ASSERT_CLAIM`` is added beyond it:
claims are the governed object (spec §7.3, §8) and therefore need an admission path of
their own; without it no ``SemanticClaim`` could ever be minted by the reducer, because
deterministic code may not originate one (plan §0.1). That justification is recorded here.

``SUPPORTS_CLAIM`` (spec §11, §12) is the one operation added for incremental
assimilation: new immutable evidence semantically supports an already-existing immutable
claim. The claim is never mutated — ``SemanticClaim.evidence_ids`` is never rewritten —
the durable effect is an append-only ``ClaimSupportRecord`` in ``SemanticState``, which is
supersedable like any judgment. It travels in ``SemanticJudgmentPayload`` and is applied
by ``SEMANTIC_ADMISSION_DECIDED`` like every other kind: no new event type exists for it.

Binding (``BIND_TO_ADDRESS``) and supersession (``SUPERSEDE``) are judgment OPERATIONS
on the ledger, not ontology relations between semantic objects. ``EQUIVALENT``,
``DISTINCT`` and ``CONFLICTS_WITH`` are the only relation-shaped kinds, and even those
are recorded as admitted judgments rather than edges edited in place (spec §4.5, §9).

Independence and provenance
---------------------------
Every judgment carries a ``ReasonerFingerprint`` (provider, model, policy_version) so the
admission layer can test independence (spec §20.1). Two invocations of the same model
under any policy are NOT independent merely because their ``invocation_id`` differs.
Humans are authority, not buttons: a human is independent of any model. Human
fingerprint convention: ``provider="human"`` and ``model`` carries the actor id
(e.g. ``"human://alice"``), so two distinct humans are independent of each other while
the same actor is not independent of themselves.

Confidence is metadata, never authority (Law 7, spec §26). Nothing in this module reads
it. ``rationale`` is bounded and concise; chain-of-thought is never persisted (spec §25).

Pure domain: no I/O, no provider imports.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from foundry.domain.common import Authority, FrozenModel
from foundry.domain.semantic_identity import ClaimValue, SemanticCandidate

_HUMAN_PROVIDER = "human"


class JudgmentKind(StrEnum):
    CREATE_ADDRESS = "CREATE_ADDRESS"
    BIND_TO_ADDRESS = "BIND_TO_ADDRESS"
    ASSERT_CLAIM = "ASSERT_CLAIM"
    EQUIVALENT = "EQUIVALENT"
    DISTINCT = "DISTINCT"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    SUPERSEDE = "SUPERSEDE"
    SUPPORTS_CLAIM = "SUPPORTS_CLAIM"


class AdmissionRoute(StrEnum):
    """Where deterministic admission sends a judgment (spec §20.1).

    Defined here rather than in ``admission.py`` so ``events.py`` can embed it in
    a payload without importing admission policy.
    """

    APPLY = "APPLY"
    REQUIRE_SECOND_LENS = "REQUIRE_SECOND_LENS"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"
    REJECT = "REJECT"


class ReasonerFingerprint(FrozenModel):
    """Provenance of a judgment's author. Provenance, not authority.

    For humans: ``provider="human"`` and ``model`` carries the actor id
    (e.g. ``"human://alice"``).
    """

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)

    @property
    def is_human(self) -> bool:
        return self.provider == _HUMAN_PROVIDER


def independent(a: ReasonerFingerprint, b: ReasonerFingerprint) -> bool:
    """Default independence rule (spec §20.1); configurable later via AdmissionPolicy.

    * A human is independent of any non-human.
    * Two non-humans are independent iff provider or model differs.
    * Identical provider+model is never independent, regardless of policy version
      or invocation.
    * Two humans are independent iff their actor ids (``model``) differ.
    """
    if a.is_human != b.is_human:
        return True
    return a.provider != b.provider or a.model != b.model


class CreateAddressProposal(FrozenModel):
    kind: Literal[JudgmentKind.CREATE_ADDRESS] = JudgmentKind.CREATE_ADDRESS
    candidate: SemanticCandidate


class BindToAddressProposal(FrozenModel):
    kind: Literal[JudgmentKind.BIND_TO_ADDRESS] = JudgmentKind.BIND_TO_ADDRESS
    candidate: SemanticCandidate
    address_id: str = Field(min_length=1)


class AssertClaimProposal(FrozenModel):
    kind: Literal[JudgmentKind.ASSERT_CLAIM] = JudgmentKind.ASSERT_CLAIM
    address_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: ClaimValue
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    authority: Authority


class EquivalentProposal(FrozenModel):
    kind: Literal[JudgmentKind.EQUIVALENT] = JudgmentKind.EQUIVALENT
    address_a: str = Field(min_length=1)
    address_b: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distinct_pair(self) -> EquivalentProposal:
        if self.address_a == self.address_b:
            raise ValueError("address_a and address_b must differ")
        return self


class DistinctProposal(FrozenModel):
    kind: Literal[JudgmentKind.DISTINCT] = JudgmentKind.DISTINCT
    address_a: str = Field(min_length=1)
    address_b: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distinct_pair(self) -> DistinctProposal:
        if self.address_a == self.address_b:
            raise ValueError("address_a and address_b must differ")
        return self


class ConflictsWithProposal(FrozenModel):
    kind: Literal[JudgmentKind.CONFLICTS_WITH] = JudgmentKind.CONFLICTS_WITH
    claim_a: str = Field(min_length=1)
    claim_b: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distinct_pair(self) -> ConflictsWithProposal:
        if self.claim_a == self.claim_b:
            raise ValueError("claim_a and claim_b must differ")
        return self


class SupersedeProposal(FrozenModel):
    kind: Literal[JudgmentKind.SUPERSEDE] = JudgmentKind.SUPERSEDE
    target_judgment_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SupportsClaimProposal(FrozenModel):
    """Evidence ``evidence_ids`` semantically supports the existing claim ``claim_id``.

    The claim is never mutated; admission appends a ``ClaimSupportRecord``.
    """

    kind: Literal[JudgmentKind.SUPPORTS_CLAIM] = JudgmentKind.SUPPORTS_CLAIM
    claim_id: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


type JudgmentProposal = Annotated[
    CreateAddressProposal
    | BindToAddressProposal
    | AssertClaimProposal
    | EquivalentProposal
    | DistinctProposal
    | ConflictsWithProposal
    | SupersedeProposal
    | SupportsClaimProposal,
    Field(discriminator="kind"),
]


class SemanticJudgment(FrozenModel):
    """A bounded, provenance-bearing semantic proposal. Never a mutation.

    ``confidence`` is metadata only and is never authority; no admission rule reads it.
    ``rationale`` is concise and bounded; it is never chain-of-thought.
    """

    judgment_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    proposal: JudgmentProposal
    visible_evidence_ids: tuple[str, ...]
    compared_object_ids: tuple[str, ...] = ()
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoner: ReasonerFingerprint
    invocation_id: str = Field(min_length=1)
    proposed_at: datetime

    @property
    def kind(self) -> JudgmentKind:
        return self.proposal.kind


def proposal_signature(p: JudgmentProposal) -> tuple[str, ...]:
    """Structural identity of a proposal, for agreement/disagreement checks.

    ``EQUIVALENT`` and ``DISTINCT`` share the ``PAIR`` signature so that the same
    pair judged both ways is detectable as a contradiction.
    """
    match p:
        case CreateAddressProposal():
            return ("CREATE", p.candidate.candidate_id)
        case BindToAddressProposal():
            return ("BIND", p.candidate.candidate_id, p.address_id)
        case AssertClaimProposal():
            return (
                "CLAIM",
                p.address_id,
                p.predicate,
                p.value.model_dump_json(),
                p.authority.value,
            )
        case EquivalentProposal() | DistinctProposal():
            return ("PAIR", min(p.address_a, p.address_b), max(p.address_a, p.address_b))
        case ConflictsWithProposal():
            return ("CONFLICT", min(p.claim_a, p.claim_b), max(p.claim_a, p.claim_b))
        case SupersedeProposal():
            return ("SUPERSEDE", p.target_judgment_id)
        case SupportsClaimProposal():
            return ("SUPPORT", p.claim_id, *sorted(p.evidence_ids))


def agrees(p: JudgmentProposal, q: JudgmentProposal) -> bool:
    """True iff both proposals are of the same kind and structurally identical."""
    return p.kind == q.kind and proposal_signature(p) == proposal_signature(q)


def contradicts(p: JudgmentProposal, q: JudgmentProposal) -> bool:
    """True only when one is ``EQUIVALENT`` and the other ``DISTINCT`` over the same pair."""
    kinds = {p.kind, q.kind}
    if kinds != {JudgmentKind.EQUIVALENT, JudgmentKind.DISTINCT}:
        return False
    return proposal_signature(p) == proposal_signature(q)
