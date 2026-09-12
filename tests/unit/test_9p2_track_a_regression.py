"""Track A contrastive-correction lifecycle through the real governor (9P2 Task T6).

Regression of the known 9P Track A failure (spec §2, §13): at T2 the model saw only the
new evidence, bound correctly, then emitted ``SUPPORTS_CLAIM`` for the old claim (or
forked a new identity) because it was never shown the old interpretation it was
correcting. 9P2 shows the old-to-new transition as request-only comparison context.

This is a REGRESSION of that one known failure with scripted model outputs. It is not
scientific validation: the scripted reasoner asserts what it was shown and returns the
approved correction path; nothing here proves that a real model would do the same.

The whole stack is real: ``SemanticGovernor`` over ``InMemoryEventStore``, the real
reducer, view and ``AdmissionPolicy()``, and ``assimilate_delta``. The only fake is an
in-process scripted ``SemanticReasoner`` whose ``propose`` receives the real
``ReasoningRequest`` and runs a per-call callback of assertions. Sockets are blocked;
ZERO provider calls.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.incremental_assimilation import DeltaOutcome, assimilate_delta
from foundry.application.replay import replay
from foundry.application.semantic_governance import SemanticGovernor
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.evidence import EvidenceItem, evidence_item
from foundry.domain.semantic import AuthorityRecord
from foundry.domain.semantic_identity import ClaimValue, ClaimValueKind, SemanticCandidate
from foundry.domain.semantic_judgment import (
    AdmissionRoute,
    AssertClaimProposal,
    BindToAddressProposal,
    CreateAddressProposal,
    JudgmentKind,
    JudgmentProposal,
    ReasonerFingerprint,
    SemanticJudgment,
    SupersedeProposal,
    proposal_signature,
)
from foundry.domain.semantic_view import CurrentSemanticView, SemanticLocus, derive_view
from foundry.ports.semantic_reasoner import ContextRelation, ReasoningRequest

PROJECT = "PROJ-9P2-TRACK-A"
SCOPE_ENGINE = "intent-engine"
SCOPE_CONSTITUTION = "constitution"
T0 = datetime(2026, 9, 12, tzinfo=UTC)

MODEL = ReasonerFingerprint(
    provider="scripted", model="scripted-track-a", policy_version="9p2-regression-fixture"
)
ARCHITECT = "human://architect"
HUMAN = ReasonerFingerprint(provider="human", model=ARCHITECT, policy_version="9p2-authority-v1")

ARTIFACT_A = "docs/semantic-address.md"
ARTIFACT_N = "docs/constitution.md"

# Judgment ids fixed by the plan (§8) and the ids the real reducer mints from them.
J_CREATE_A = "J-cA"
J_CREATE_N = "J-cN"
J_A1 = "J-A1"
J_N1 = "J-N1"
J_BIND_A2 = "J-bA2"
J_A2 = "J-A2"
J_SUPERSEDE_A1 = "J-supA1"
ADDR_A = address_id_for(PROJECT, J_CREATE_A)
ADDR_N = address_id_for(PROJECT, J_CREATE_N)
CLAIM_A1 = claim_id_for(PROJECT, J_A1)
CLAIM_A2 = claim_id_for(PROJECT, J_A2)
CLAIM_N1 = claim_id_for(PROJECT, J_N1)

TRACK_A_CHAIN = ("D-A1", "D-A2", "D-A3")
CONTROL_CHAIN = ("D-N1", "D-N2")

CALL1_KINDS = frozenset({JudgmentKind.BIND_TO_ADDRESS, JudgmentKind.CREATE_ADDRESS})
CALL2_KINDS = frozenset(
    {
        JudgmentKind.SUPPORTS_CLAIM,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.SUPERSEDE,
        JudgmentKind.CONFLICTS_WITH,
    }
)

# --- the two interpretations ------------------------------------------------------------

OLD_LINE = "After admission, address equality is deterministic and authoritative."
NEW_LINE_1 = (
    "After admission, address identity is a deterministic referential fact under the "
    "current admitted interpretation."
)
NEW_LINE_2 = (
    "It is not eternal semantic truth: the binding may later be superseded by a governed judgment."
)
SHARED_HEAD = (
    "# Semantic address",
    "",
    "A semantic address is a durable identity minted by admission.",
)
SHARED_TAIL = (
    "Two references name the same address iff their address ids are equal.",
    "Descriptors describe an address; they never identify it.",
)
OLD_TEXT = "\n".join((*SHARED_HEAD, OLD_LINE, *SHARED_TAIL))
NEW_TEXT = "\n".join((*SHARED_HEAD, NEW_LINE_1, NEW_LINE_2, *SHARED_TAIL))

OLD_CLAIM_TEXT = "After admission, address equality is deterministic and authoritative."
NEW_CLAIM_TEXT = (
    "Address identity is a deterministic referential fact under the current admitted "
    "interpretation, not eternal semantic truth; the binding may later be superseded."
)
CONTROL_TEXT = "The constitution outranks every plan and every task."
CORRECTION_REASON = (
    "EV-A2 corrects EV-A1: address identity is referential under the current admitted "
    "interpretation, not eternal semantic truth."
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- scripted reasoner ----------------------------------------------------------------

CallScript = Callable[[ReasoningRequest], list[SemanticJudgment]]


class ScriptedReasoner:
    """Runs one scripted callback per call against the REAL request; refuses extra calls."""

    def __init__(self, scripts: list[CallScript]) -> None:
        self._scripts = scripts
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return MODEL

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._scripts):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._scripts)} scripted")
        return tuple(self._scripts[index](request))


# --- builders ---------------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick))


def _counter_id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _governor(store: InMemoryEventStore) -> SemanticGovernor:
    clock = _clock()
    return SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=_counter_id_factory(),
    )


def _evidence(
    evidence_id: str,
    *,
    content: str,
    artifact_ref: str,
    scope: tuple[str, ...],
    supersedes: str | None = None,
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"git://b798507/{artifact_ref}#{evidence_id}",
        content=content,
        observed_at=T0,
        scope=scope,
        artifact_ref=artifact_ref,
        supersedes_evidence_id=supersedes,
    )


EV_A1 = _evidence("EV-A1", content=OLD_TEXT, artifact_ref=ARTIFACT_A, scope=(SCOPE_ENGINE,))
EV_A2 = _evidence(
    "EV-A2",
    content=NEW_TEXT,
    artifact_ref=ARTIFACT_A,
    scope=(SCOPE_ENGINE,),
    supersedes="EV-A1",
)
EV_N1 = _evidence(
    "EV-N1", content=CONTROL_TEXT, artifact_ref=ARTIFACT_N, scope=(SCOPE_CONSTITUTION,)
)


def _judgment(
    judgment_id: str,
    proposal: JudgmentProposal,
    *,
    visible_evidence_ids: tuple[str, ...],
    reasoner: ReasonerFingerprint = MODEL,
    rationale: str | None = None,
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=visible_evidence_ids,
        rationale=rationale or f"Rationale for {judgment_id}.",
        reasoner=reasoner,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _candidate(
    candidate_id: str, subject: str, facet: str, scope: str, ev: str
) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id, subject=subject, facet=facet, scope=(scope,), evidence_ids=(ev,)
    )


def _text_claim(
    judgment_id: str, address_id: str, evidence_id: str, text: str, authority: Authority
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate="interpretation",
            value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
            evidence_ids=(evidence_id,),
            authority=authority,
        ),
        visible_evidence_ids=(evidence_id,),
    )


def _architect_authority() -> AuthorityRecord:
    """Project-wide (``scope == ()``) record: a supersession has no single target scope."""
    return AuthorityRecord(
        id="AUTH-architect",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=ARCHITECT),
        created_at=T0,
        scope=(),
        subject_id="material-semantic-change",
        authorized_by=ARCHITECT,
        rationale="Architect authority for AGREE/DECLINE of material supersession proposals.",
    )


# --- request inspection helpers ----------------------------------------------------------


def _evidence_ids(request: ReasoningRequest) -> list[str]:
    return [item.evidence_id for item in request.evidence]


def _address_ids(request: ReasoningRequest) -> list[str]:
    return [address.address_id for address in request.known_addresses]


def _claim_ids(request: ReasoningRequest) -> list[str]:
    return [claim.claim_id for claim in request.known_claims]


def _locus(view: CurrentSemanticView, representative_id: str) -> SemanticLocus:
    return next(locus for locus in view.loci if locus.representative_id == representative_id)


def _assert_track_a_transition_is_visible(request: ReasoningRequest) -> None:
    """The structural path EV-A2 -> EV-A1 -> C-A1 -> A, the diff, and delta-only evidence."""
    # A and its live claim C-A1 are visible; the control address N is out of scope.
    assert ADDR_A in _address_ids(request)
    assert ADDR_N not in _address_ids(request)
    assert _claim_ids(request) == [CLAIM_A1]
    known_claim = request.known_claims[0]
    assert known_claim.address_id == ADDR_A
    assert known_claim.evidence_ids == ("EV-A1",)
    assert known_claim.value.text == OLD_CLAIM_TEXT
    # Citable evidence is the delta only. EV-A1 is never a second citable item.
    assert request.evidence == (EV_A2,)
    assert _evidence_ids(request) == ["EV-A2"]
    assert request.evidence[0].supersedes_evidence_id == "EV-A1"
    # Exactly one transition, reached by explicit structural edges only.
    context = request.comparison_context
    assert len(context.transitions) == 1
    transition = context.transitions[0]
    assert transition.current_evidence_id == "EV-A2"
    assert transition.predecessor_evidence_id == "EV-A1"
    assert transition.artifact_ref == ARTIFACT_A
    assert transition.touched_claim_ids == (CLAIM_A1,)
    assert transition.touched_address_ids == (ADDR_A,)
    assert [(e.source_id, e.relation, e.target_id) for e in transition.inclusion_edges] == [
        ("EV-A2", ContextRelation.SUPERSEDES, "EV-A1"),
        ("EV-A1", ContextRelation.EFFECTIVE_EVIDENCE_OF, CLAIM_A1),
        (CLAIM_A1, ContextRelation.CLAIM_AT_ADDRESS, ADDR_A),
    ]
    assert [(e.source_id, e.relation, e.target_id) for e in context.active_claim_profile_edges] == [
        (ADDR_A, ContextRelation.ACTIVE_CLAIM_PROFILE, CLAIM_A1)
    ]
    # Deterministic old->new diff carries both interpretations, labelled by evidence id.
    diff = transition.historical_diff
    assert diff.startswith("--- evidence:EV-A1\n+++ evidence:EV-A2\n")
    diff_lines = diff.splitlines()
    assert f"-{OLD_LINE}" in diff_lines
    assert f"+{NEW_LINE_1}" in diff_lines
    assert f"+{NEW_LINE_2}" in diff_lines
    assert f" {SHARED_HEAD[2]}" in diff_lines  # unchanged context is shown, not stripped
    assert not any(
        line.startswith("-") and line[1:] in NEW_TEXT.splitlines() for line in diff_lines
    )
    assert not any(
        line.startswith("+") and line[1:] in OLD_TEXT.splitlines() for line in diff_lines
    )


# --- T1 -----------------------------------------------------------------------------------


def _t1(governor: SemanticGovernor) -> None:
    """T1: A with old claim C-A1 (J-A1), control N with C-N1 (J-N1), five derivation edges."""
    governor.ingest(EV_A1)
    create_a = _judgment(
        J_CREATE_A,
        CreateAddressProposal(
            candidate=_candidate(
                "CAND-A", "SemanticAddress", "identity vs descriptors", SCOPE_ENGINE, "EV-A1"
            )
        ),
        visible_evidence_ids=("EV-A1",),
    )
    assert governor.submit(create_a).route is AdmissionRoute.APPLY
    old_claim = _text_claim(J_A1, ADDR_A, "EV-A1", OLD_CLAIM_TEXT, Authority.OBSERVED)
    assert governor.submit(old_claim).route is AdmissionRoute.APPLY

    governor.ingest(EV_N1)
    create_n = _judgment(
        J_CREATE_N,
        CreateAddressProposal(
            candidate=_candidate(
                "CAND-N", "Constitution", "precedence over plans", SCOPE_CONSTITUTION, "EV-N1"
            )
        ),
        visible_evidence_ids=("EV-N1",),
    )
    assert governor.submit(create_n).route is AdmissionRoute.APPLY
    control_claim = _text_claim(J_N1, ADDR_N, "EV-N1", CONTROL_TEXT, Authority.OBSERVED)
    assert governor.submit(control_claim).route is AdmissionRoute.APPLY

    governor.derive("D-A1", J_A1)
    governor.derive("D-A2", "D-A1")
    governor.derive("D-A3", "D-A2")
    governor.derive("D-N1", J_N1)
    governor.derive("D-N2", "D-N1")

    state = governor.state()
    view = derive_view(state.semantic)
    assert set(state.semantic.addresses) == {ADDR_A, ADDR_N}
    assert set(state.semantic.claims) == {CLAIM_A1, CLAIM_N1}
    assert state.semantic.claims[CLAIM_A1].created_by_judgment_id == J_A1
    assert [(e.child_id, e.parent_id) for e in state.semantic.derivations] == [
        ("D-A1", J_A1),
        ("D-A2", "D-A1"),
        ("D-A3", "D-A2"),
        ("D-N1", J_N1),
        ("D-N2", "D-N1"),
    ]
    assert view.stale_ids == ()
    assert view.pending_judgment_ids == ()
    assert view.effective_evidence[CLAIM_A1] == ("EV-A1",)
    assert _locus(view, ADDR_A).claim_ids == (CLAIM_A1,)
    assert _locus(view, ADDR_N).claim_ids == (CLAIM_N1,)


# --- T2 scripts --------------------------------------------------------------------------


def _call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    """Assimilation: sees A, C-A1 and the old->new transition; binds to A, creates nothing."""
    assert request.project_id == PROJECT
    assert request.allowed_judgment_kinds == CALL1_KINDS
    assert _address_ids(request) == [ADDR_A]
    _assert_track_a_transition_is_visible(request)
    return [
        _judgment(
            J_BIND_A2,
            BindToAddressProposal(
                candidate=_candidate(
                    "CAND-A2", "SemanticAddress", "identity vs descriptors", SCOPE_ENGINE, "EV-A2"
                ),
                address_id=ADDR_A,
            ),
            visible_evidence_ids=("EV-A2",),
            rationale="EV-A2 revises the same artifact and the same identity question as A.",
        )
    ]


def _call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    """Claim assimilation: same visibility; asserts corrected C-A2 at A, supersedes J-A1."""
    assert request.project_id == PROJECT
    assert request.allowed_judgment_kinds == CALL2_KINDS
    assert _address_ids(request) == [ADDR_A]
    _assert_track_a_transition_is_visible(request)
    return [
        _text_claim(J_A2, ADDR_A, "EV-A2", NEW_CLAIM_TEXT, Authority.INFERRED),
        _judgment(
            J_SUPERSEDE_A1,
            SupersedeProposal(target_judgment_id=J_A1, reason=CORRECTION_REASON),
            visible_evidence_ids=("EV-A2",),
            rationale="The old interpretation at A is materially corrected by EV-A2.",
        ),
    ]


def _human_agreement(pending: SemanticJudgment) -> SemanticJudgment:
    """The architect's AGREE: the identical proposal object under the human fingerprint."""
    assert isinstance(pending.proposal, SupersedeProposal)
    return SemanticJudgment(
        judgment_id="J-human-supA1",
        project_id=PROJECT,
        proposal=SupersedeProposal(
            target_judgment_id=pending.proposal.target_judgment_id, reason=pending.proposal.reason
        ),
        visible_evidence_ids=(),
        rationale=f"AGREE: {pending.judgment_id}",
        reasoner=HUMAN,
        invocation_id="AUTHZ-supA1",
        proposed_at=T0,
    )


# --- the regression -----------------------------------------------------------------------


def test_track_a_correction_lifecycle_through_the_real_governor() -> None:
    store = InMemoryEventStore()
    governor = _governor(store)
    _t1(governor)
    reasoner = ScriptedReasoner([_call_1, _call_2])

    # --- T2: one delta, two scripted calls, real admission ---------------------------------
    outcome = assimilate_delta(
        governor=governor, reasoner=reasoner, delta=(EV_A2,), scope=SCOPE_ENGINE
    )

    assert isinstance(outcome, DeltaOutcome)
    assert outcome.calls_made == 2
    assert len(reasoner.requests) == 2
    assert reasoner.requests[0].allowed_judgment_kinds == CALL1_KINDS
    assert reasoner.requests[1].allowed_judgment_kinds == CALL2_KINDS
    assert outcome.neighborhood == (ADDR_A,)
    assert outcome.claim_neighborhood == (ADDR_A,)
    # On the BIND path the structural widening is a no-op (the decision neighbourhood
    # already holds A); the widening itself is proven by T4's deliberate-CREATE test.
    assert outcome.neighborhood == outcome.claim_neighborhood
    decisions_1, decisions_2 = outcome.stage_decisions
    assert [(d.judgment_id, d.route) for d in decisions_1] == [(J_BIND_A2, AdmissionRoute.APPLY)]
    assert [(d.judgment_id, d.route) for d in decisions_2] == [
        (J_A2, AdmissionRoute.APPLY),
        (J_SUPERSEDE_A1, AdmissionRoute.REQUIRE_SECOND_LENS),
    ]
    assert outcome.pending_supersede_judgment_ids == (J_SUPERSEDE_A1,)

    # Before authority: no new identity, both claims live at A, nothing stale, held SUPERSEDE.
    state = governor.state()
    view = derive_view(state.semantic)
    assert set(state.semantic.addresses) == {ADDR_A, ADDR_N}
    assert view.active_bindings["CAND-A2"] == ADDR_A
    assert set(_locus(view, ADDR_A).claim_ids) == {CLAIM_A1, CLAIM_A2}
    assert view.pending_judgment_ids == (J_SUPERSEDE_A1,)
    assert J_SUPERSEDE_A1 not in state.semantic.applied_judgment_ids
    assert J_A1 in state.semantic.applied_judgment_ids
    assert view.stale_ids == ()
    assert view.effective_evidence[CLAIM_A1] == ("EV-A1",)
    assert view.effective_evidence[CLAIM_A2] == ("EV-A2",)
    assert view.current_evidence_ids == ("EV-A2", "EV-N1")
    assert view.superseded_evidence_ids == ("EV-A1",)

    # --- human authority: AGREE with the identical proposal -----------------------------------
    governor.record_authority(_architect_authority())
    pending = state.semantic.judgments[J_SUPERSEDE_A1]
    agreement = _human_agreement(pending)
    assert agreement.proposal == pending.proposal
    assert proposal_signature(agreement.proposal) == proposal_signature(pending.proposal)
    assert proposal_signature(agreement.proposal) == ("SUPERSEDE", J_A1)

    decision = governor.submit(agreement, human_actor_id=ARCHITECT)

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)

    # --- final state ---------------------------------------------------------------------------
    state = governor.state()
    semantic = state.semantic
    view = derive_view(semantic)

    # Exactly two model calls; no third call, no reconciliation.
    assert len(reasoner.requests) == 2
    # No duplicate Track-A identity: durable addresses are A and the control N only.
    assert set(semantic.addresses) == {ADDR_A, ADDR_N}
    assert semantic.addresses[ADDR_A].subject == "SemanticAddress"
    assert semantic.addresses[ADDR_A].facet == "identity vs descriptors"
    # A's current locus holds the corrected claim and not the old one.
    locus_a = _locus(view, ADDR_A)
    assert locus_a.address_ids == (ADDR_A,)
    assert locus_a.claim_ids == (CLAIM_A2,)
    assert CLAIM_A1 not in locus_a.claim_ids
    assert _locus(view, ADDR_N).claim_ids == (CLAIM_N1,)
    # The old claim and its judgment remain readable history; nothing was rewritten.
    assert semantic.claims[CLAIM_A1].value.text == OLD_CLAIM_TEXT
    assert semantic.claims[CLAIM_A1].evidence_ids == ("EV-A1",)
    assert semantic.judgments[J_A1].kind is JudgmentKind.ASSERT_CLAIM
    assert J_A1 in semantic.applied_judgment_ids
    assert semantic.admissions[J_A1].route is AdmissionRoute.APPLY
    assert semantic.admissions[J_SUPERSEDE_A1].route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert J_SUPERSEDE_A1 not in semantic.applied_judgment_ids
    assert "J-human-supA1" in semantic.applied_judgment_ids
    # Blast radius: Track A descendants are stale; the control chain is untouched.
    stale = set(view.stale_ids)
    assert stale >= set(TRACK_A_CHAIN)
    assert stale.isdisjoint(CONTROL_CHAIN)
    assert J_N1 not in stale
    assert len(semantic.derivations) == 5
    # The model's pending supersession is satisfied by the human's; nothing is pending.
    assert dict(view.satisfied_by) == {J_SUPERSEDE_A1: "J-human-supA1"}
    assert J_SUPERSEDE_A1 not in view.pending_judgment_ids
    assert view.pending_judgment_ids == ()
    # No EQUIVALENT/DISTINCT judgment and no kind outside the existing enum in the ledger.
    kinds = {judgment.kind for judgment in semantic.judgments.values()}
    assert kinds == {
        JudgmentKind.CREATE_ADDRESS,
        JudgmentKind.ASSERT_CLAIM,
        JudgmentKind.BIND_TO_ADDRESS,
        JudgmentKind.SUPERSEDE,
    }
    assert kinds.isdisjoint({JudgmentKind.EQUIVALENT, JudgmentKind.DISTINCT})
    assert all(isinstance(kind, JudgmentKind) for kind in kinds)
    assert set(semantic.judgments) == {
        J_CREATE_A,
        J_A1,
        J_CREATE_N,
        J_N1,
        J_BIND_A2,
        J_A2,
        J_SUPERSEDE_A1,
        "J-human-supA1",
    }
    # The corrected claim cites EV-A2 only, never the predecessor EV-A1.
    new_claim = semantic.claims[CLAIM_A2]
    assert new_claim.address_id == ADDR_A
    assert new_claim.evidence_ids == ("EV-A2",)
    assert new_claim.authority is Authority.INFERRED
    assert new_claim.value.text == NEW_CLAIM_TEXT
    assert new_claim.created_by_judgment_id == J_A2
    assert view.effective_evidence[CLAIM_A2] == ("EV-A2",)
    assert CLAIM_A1 not in view.effective_evidence
    assert view.active_support_judgment_ids == ()
    # Replay of the ledger reproduces the final state and view exactly.
    replayed = replay(PROJECT, store.load(PROJECT))
    assert replayed == state
    assert derive_view(replayed.semantic) == view
