"""Shared fixtures for the T7 context suite."""

from __future__ import annotations

from datetime import UTC, datetime

from foundry.domain.common import (
    Authority,
    LifecycleStatus,
    Materiality,
    Provenance,
    Relation,
    RelationType,
    RiskLevel,
    SourceKind,
)
from foundry.domain.evidence import evidence_item
from foundry.domain.semantic import (
    Assumption,
    Constraint,
    Contract,
    Decision,
    Goal,
    Intent,
    NonGoal,
    Outcome,
    Preference,
    Requirement,
    SemanticBase,
    SemanticKind,
)
from foundry.domain.semantic_identity import (
    ClaimValue,
    ClaimValueKind,
    IssueEpistemicState,
    SemanticAddress,
    SemanticClaim,
    SemanticIssueVersion,
)
from foundry.domain.semantic_judgment import (
    AssertClaimProposal,
    ConflictsWithProposal,
    EquivalentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
)
from foundry.domain.semantic_state import SemanticState
from foundry.domain.state import IntentState

PROJECT = "PROJ-A"
SCOPE = "keyring"
AT = datetime(2026, 9, 23, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="p1")
PROVENANCE = Provenance(source_kind=SourceKind.HUMAN, source_ref="human://alice")


def evidence(evidence_id: str, source_kind: SourceKind = SourceKind.DOCUMENT):  # type: ignore[no-untyped-def]
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=source_kind,
        source_ref=f"src://{evidence_id}",
        content=f"content of {evidence_id}",
        observed_at=AT,
        scope=(SCOPE,),
    )


def address(
    address_id: str,
    *,
    scope: tuple[str, ...] = (SCOPE,),
    subject: str = "Subject",
    facet: str = "Facet?",
) -> SemanticAddress:
    return SemanticAddress(
        address_id=address_id,
        project_id=PROJECT,
        subject=subject,
        facet=facet,
        scope=scope,
        created_by_judgment_id=f"JDG-create-{address_id}",
    )


def claim(
    claim_id: str,
    address_id: str,
    *,
    judgment_id: str | None = None,
    evidence_ids: tuple[str, ...] = ("EV-1",),
    authority: Authority = Authority.INFERRED,
    kind: ClaimValueKind = ClaimValueKind.TEXT,
    predicate: str = "pred",
) -> SemanticClaim:
    value = (
        ClaimValue(kind=ClaimValueKind.UNDECIDED)
        if kind is ClaimValueKind.UNDECIDED
        else ClaimValue(kind=ClaimValueKind.TEXT, text="immediately")
    )
    return SemanticClaim(
        claim_id=claim_id,
        project_id=PROJECT,
        address_id=address_id,
        predicate=predicate,
        value=value,
        evidence_ids=evidence_ids,
        authority=authority,
        provenance=PROVENANCE,
        created_by_judgment_id=judgment_id or f"JDG-assert-{claim_id}",
    )


def assert_judgment(
    judgment_id: str,
    address_id: str,
    claim_value: ClaimValue | None = None,
    evidence_ids: tuple[str, ...] = ("EV-1",),
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=AssertClaimProposal(
            address_id=address_id,
            predicate="pred",
            value=claim_value or ClaimValue(kind=ClaimValueKind.TEXT, text="immediately"),
            evidence_ids=evidence_ids,
            authority=Authority.INFERRED,
        ),
        visible_evidence_ids=evidence_ids,
        rationale="r",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=AT,
    )


def equivalent_judgment(judgment_id: str, a: str, b: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=EquivalentProposal(address_a=a, address_b=b),
        visible_evidence_ids=("EV-1",),
        rationale="r",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=AT,
    )


def conflict_judgment(judgment_id: str, claim_a: str, claim_b: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=ConflictsWithProposal(claim_a=claim_a, claim_b=claim_b),
        visible_evidence_ids=("EV-1",),
        rationale="r",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=AT,
    )


def supersede_judgment(judgment_id: str, target_judgment_id: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=SupersedeProposal(target_judgment_id=target_judgment_id, reason="corrected"),
        visible_evidence_ids=("EV-1",),
        rationale="r",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=AT,
    )


def version(
    version_id: str,
    address_id: str,
    claim_ids: tuple[str, ...],
    judgment_id: str,
    state: IssueEpistemicState = IssueEpistemicState.CLAIMED,
) -> SemanticIssueVersion:
    return SemanticIssueVersion(
        version_id=version_id,
        project_id=PROJECT,
        address_id=address_id,
        claim_ids=claim_ids,
        epistemic_state=state,
        equivalent_address_ids=(),
        supersedes_version_id=None,
        created_by_event_id=f"EVT-{version_id}",
        created_by_judgment_id=judgment_id,
    )


def requirement(
    object_id: str,
    *,
    statement: str = "A commitment.",
    scope: tuple[str, ...] = (SCOPE,),
    authority: Authority = Authority.CANONICAL,
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
    materiality: Materiality = Materiality.LOW,
    basis_claim_ids: tuple[str, ...] = (),
) -> Requirement:
    return Requirement(
        id=object_id,
        project_id=PROJECT,
        authority=authority,
        confidence=1.0,
        provenance=PROVENANCE,
        created_at=AT,
        scope=scope,
        lifecycle=lifecycle,
        relations=tuple(
            Relation(relation_type=RelationType.DERIVED_FROM, target_id=cid)
            for cid in basis_claim_ids
        ),
        statement=statement,
        materiality=materiality,
        requires_metric=False,
        requires_verification=False,
    )


def object_of_kind(
    kind: SemanticKind, object_id: str = "OBJ-1", scope: tuple[str, ...] = (SCOPE,)
) -> SemanticBase:
    base = {
        "id": object_id,
        "project_id": PROJECT,
        "authority": Authority.CANONICAL,
        "confidence": 1.0,
        "provenance": PROVENANCE,
        "created_at": AT,
        "scope": scope,
    }
    table: dict[SemanticKind, SemanticBase] = {
        SemanticKind.INTENT: Intent(**base, mission="THE MISSION"),  # type: ignore[arg-type]
        SemanticKind.GOAL: Goal(**base, statement="GOAL-S"),  # type: ignore[arg-type]
        SemanticKind.OUTCOME: Outcome(**base, statement="OUTCOME-S"),  # type: ignore[arg-type]
        SemanticKind.NON_GOAL: NonGoal(**base, statement="NONGOAL-S"),  # type: ignore[arg-type]
        SemanticKind.PREFERENCE: Preference(**base, statement="PREF-S"),  # type: ignore[arg-type]
        SemanticKind.CONSTRAINT: Constraint(**base, statement="CONSTR-S"),  # type: ignore[arg-type]
        SemanticKind.REQUIREMENT: Requirement(  # type: ignore[arg-type]
            **base,
            statement="REQ-S",
            materiality=Materiality.HIGH,
            requires_metric=False,
            requires_verification=False,
        ),
        SemanticKind.DECISION: Decision(**base, statement="DEC-S", rationale="DEC-RATIONALE"),  # type: ignore[arg-type]
        SemanticKind.ASSUMPTION: Assumption(**base, statement="ASSUM-S", risk_level=RiskLevel.LOW),  # type: ignore[arg-type]
        SemanticKind.CONTRACT: Contract(**base, statement="CONTR-S", observable=True),  # type: ignore[arg-type]
    }
    return table[kind]


def semantic_state(**kwargs) -> SemanticState:  # type: ignore[no-untyped-def]
    return SemanticState(**kwargs)


def intent_state(
    semantic: SemanticState, objects: dict[str, SemanticBase] | None = None
) -> IntentState:
    return IntentState(project_id=PROJECT, objects=objects or {}, semantic=semantic)


def simple_locus_state(
    *,
    address_scope: tuple[str, ...] = (SCOPE,),
    claim_kind: ClaimValueKind = ClaimValueKind.TEXT,
    objects: dict[str, SemanticBase] | None = None,
    extra_claims: dict[str, str] | None = None,
) -> IntentState:
    """One address, one live claim, CLAIMED locus, one evidence item."""
    addr = address("ADDR-1", scope=address_scope)
    j1 = assert_judgment("JDG-1", "ADDR-1")
    c1 = claim("CLAIM-1", "ADDR-1", judgment_id="JDG-1", kind=claim_kind)
    claims = {"CLAIM-1": c1}
    judgments = {"JDG-1": j1}
    applied = ["JDG-1"]
    for cid, jid in (extra_claims or {}).items():
        claims[cid] = claim(cid, "ADDR-1", judgment_id=jid)
        judgments[jid] = assert_judgment(jid, "ADDR-1")
        applied.append(jid)
    sem = SemanticState(
        evidence={"EV-1": evidence("EV-1")},
        addresses={"ADDR-1": addr},
        claims=claims,
        judgments=judgments,
        applied_judgment_ids=tuple(applied),
        issue_versions={"VER-1": version("VER-1", "ADDR-1", tuple(claims), "JDG-1")},
        issue_heads={"ADDR-1": "VER-1"},
    )
    return intent_state(sem, objects)
