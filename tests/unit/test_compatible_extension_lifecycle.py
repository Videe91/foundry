"""Compatible-extension lifecycle: same locus, preserved claims, one additional claim.

The generic weakness exposed by the sealed 9P3 run: when new evidence adds a genuinely new,
compatible proposition about a locus that already has current claims, the right durable
state is ONE address, the existing compatible claims still current, and the new claim added
at that same address — no supersession, no second address, no duplicate claim. The locus
policy (``LOCUS_SYSTEM_INSTRUCTION``) prescribes exactly that output per proposition. The
model cannot be called here, so every scenario drives the REAL ``SemanticGovernor`` and
``assimilate_delta`` with a *specification reasoner* — a scripted double that returns the
drafts the locus policy prescribes — and checks the resulting ledger/state against the
architecture's rule. Counterexamples prove the mechanism does not collapse restatement,
correction, revert, distinct loci or address granularity into the extension shape, and
that governance (structural duplicate refusal, human authority for supersession,
append-only history) is unchanged. Scenario wording is deliberately generic and appears in
NO request-path code or prompt. ZERO live calls; sockets are blocked.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.application.incremental_assimilation import DeltaOutcome, assimilate_delta
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
    SupportsClaimProposal,
)
from foundry.domain.semantic_view import active_judgment_ids
from foundry.ports.semantic_reasoner import ReasoningRequest

PROJECT = "PROJ-LOCUS"
SCOPE = "svc"
T0 = datetime(2026, 9, 14, tzinfo=UTC)
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="intent-v2-locus-v1")
HUMAN = ReasonerFingerprint(provider="human", model="human://alice", policy_version="n/a")
AI_AUTHORITY = Authority.INFERRED

type Batch = list[SemanticJudgment] | Callable[[ReasoningRequest], list[SemanticJudgment]]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is forbidden in this test module")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- specification reasoner ------------------------------------------------------------


class SpecReasoner:
    """Returns, per call, the drafts the locus policy prescribes; refuses any extra call."""

    def __init__(self, batches: list[Batch]) -> None:
        self._batches = batches
        self.requests: list[ReasoningRequest] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return MODEL

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"call {index + 1} attempted; only {len(self._batches)} scripted")
        batch = self._batches[index]
        return tuple(batch(request) if callable(batch) else batch)


# --- builders ---------------------------------------------------------------------------


def _clock() -> Iterator[datetime]:
    tick = count()
    while True:
        yield T0.replace(minute=next(tick) % 60, hour=next(tick) // 60 % 24)


def _governor() -> tuple[InMemoryEventStore, SemanticGovernor]:
    clock = _clock()
    ticks = count(1)
    store = InMemoryEventStore()
    governor = SemanticGovernor(
        store=store,
        project_id=PROJECT,
        policy=AdmissionPolicy(),
        clock=lambda: next(clock),
        id_factory=lambda prefix: f"{prefix}-{next(ticks)}",
    )
    return store, governor


def _evidence(
    evidence_id: str, content: str, *, artifact_ref: str, supersedes: str | None = None
) -> EvidenceItem:
    return evidence_item(
        evidence_id=evidence_id,
        project_id=PROJECT,
        source_kind=SourceKind.DOCUMENT,
        source_ref=f"doc://{evidence_id}",
        content=content,
        observed_at=T0,
        scope=(SCOPE,),
        artifact_ref=artifact_ref,
        supersedes_evidence_id=supersedes,
    )


def _judgment(judgment_id: str, proposal: JudgmentProposal, evidence_id: str) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=PROJECT,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Prescribed by the locus policy for {judgment_id}.",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _candidate(judgment_id: str, evidence_id: str, subject: str, facet: str) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=f"CAND-{judgment_id}",
        subject=subject,
        facet=facet,
        scope=(SCOPE,),
        evidence_ids=(evidence_id,),
    )


def _create(judgment_id: str, evidence_id: str, subject: str, facet: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        CreateAddressProposal(candidate=_candidate(judgment_id, evidence_id, subject, facet)),
        evidence_id,
    )


def _bind(
    judgment_id: str, address_id: str, evidence_id: str, subject: str, facet: str
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        BindToAddressProposal(
            candidate=_candidate(judgment_id, evidence_id, subject, facet), address_id=address_id
        ),
        evidence_id,
    )


def _assert(
    judgment_id: str, address_id: str, evidence_id: str, predicate: str, value: ClaimValue
) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        AssertClaimProposal(
            address_id=address_id,
            predicate=predicate,
            value=value,
            evidence_ids=(evidence_id,),
            authority=AI_AUTHORITY,
        ),
        evidence_id,
    )


def _text(text: str) -> ClaimValue:
    return ClaimValue(kind=ClaimValueKind.TEXT, text=text)


def _quantity(quantity: str, unit: str) -> ClaimValue:
    return ClaimValue(kind=ClaimValueKind.QUANTITY, quantity=Decimal(quantity), unit=unit)


def _support(judgment_id: str, claim_id: str, evidence_id: str) -> SemanticJudgment:
    return _judgment(
        judgment_id,
        SupportsClaimProposal(claim_id=claim_id, evidence_ids=(evidence_id,)),
        evidence_id,
    )


def _supersede(
    judgment_id: str,
    target_judgment_id: str,
    evidence_id: str,
    *,
    reasoner: ReasonerFingerprint = MODEL,
) -> SemanticJudgment:
    judgment = _judgment(
        judgment_id,
        SupersedeProposal(
            target_judgment_id=target_judgment_id, reason="Corrected by newer evidence."
        ),
        evidence_id,
    )
    return judgment.model_copy(update={"reasoner": reasoner})


def _authority_record(actor: str) -> AuthorityRecord:
    return AuthorityRecord(
        id=f"AUTH-{actor.split('://')[-1]}",
        project_id=PROJECT,
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(source_kind=SourceKind.HUMAN, source_ref=actor),
        created_at=T0,
        scope=(),
        subject_id="semantic-corrections",
        authorized_by=actor,
        rationale="Owns semantic corrections project-wide.",
    )


def _addr(judgment_id: str) -> str:
    return address_id_for(PROJECT, judgment_id)


def _claim(judgment_id: str) -> str:
    return claim_id_for(PROJECT, judgment_id)


# --- observation helpers -----------------------------------------------------------------


def _live_claims_at(governor: SemanticGovernor, address_id: str) -> dict[str, str]:
    """``claim_id -> predicate`` for LIVE claims at ``address_id``."""
    semantic = governor.state().semantic
    active = active_judgment_ids(semantic)
    return {
        claim_id: claim.predicate
        for claim_id, claim in sorted(semantic.claims.items())
        if claim.address_id == address_id and claim.created_by_judgment_id in active
    }


def _in_scope_address_ids(governor: SemanticGovernor) -> list[str]:
    semantic = governor.state().semantic
    active = active_judgment_ids(semantic)
    return sorted(
        address_id
        for address_id, address in semantic.addresses.items()
        if address.created_by_judgment_id in active and SCOPE in address.scope
    )


def _routes(outcome: DeltaOutcome) -> tuple[list[AdmissionRoute], list[AdmissionRoute]]:
    return (
        [d.route for d in outcome.stage_decisions[0]],
        [d.route for d in outcome.stage_decisions[1]],
    )


def _seed(
    governor: SemanticGovernor,
    evidence: EvidenceItem,
    loci: list[tuple[str, str, str, list[tuple[str, str, ClaimValue]]]],
) -> DeltaOutcome:
    """T1: one evidence item creates the listed loci ``(judgment_id, subject, facet, claims)``;
    every claim is ``(judgment_id, predicate, value)`` at that locus."""
    creates = [
        _create(jid, evidence.evidence_id, subject, facet) for jid, subject, facet, _ in loci
    ]
    asserts = [
        _assert(cjid, _addr(jid), evidence.evidence_id, predicate, value)
        for jid, _, _, claims in loci
        for cjid, predicate, value in claims
    ]
    reasoner = SpecReasoner([creates, asserts])
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(evidence,), scope=SCOPE)
    assert all(route is AdmissionRoute.APPLY for stage in _routes(outcome) for route in stage)
    return outcome


# --- the generic extension shape ----------------------------------------------------------

CREDENTIAL_V1 = "Revoking a credential prevents future authentication attempts with it."
CREDENTIAL_V2 = (
    "Revoking a credential prevents future authentication attempts with it. Revoking an "
    "already-revoked credential is idempotent and leaves it revoked."
)


def _credential_story() -> tuple[SemanticGovernor, SpecReasoner, DeltaOutcome]:
    _, governor = _governor()
    v1 = _evidence("EV-CRED-1", CREDENTIAL_V1, artifact_ref="auth/credentials.md")
    _seed(
        governor,
        v1,
        [
            (
                "J-cred",
                "API credential lifecycle",
                "what revocation does to the credential",
                [("J-cred-revoke", "effect of revocation", _text(CREDENTIAL_V1))],
            )
        ],
    )
    v2 = _evidence(
        "EV-CRED-2", CREDENTIAL_V2, artifact_ref="auth/credentials.md", supersedes="EV-CRED-1"
    )
    reasoner = SpecReasoner(
        [
            # Call 1: the propositions belong to the known locus -> BIND, never CREATE.
            [
                _bind(
                    "J-cred-bind",
                    _addr("J-cred"),
                    "EV-CRED-2",
                    "API credential lifecycle",
                    "what revocation does to the credential",
                )
            ],
            # Call 2, per proposition: restated -> SUPPORTS; new & compatible -> ASSERT at the
            # SAME address with its own predicate; no SUPERSEDE.
            [
                _support("J-cred-support", _claim("J-cred-revoke"), "EV-CRED-2"),
                _assert(
                    "J-cred-idem",
                    _addr("J-cred"),
                    "EV-CRED-2",
                    "repeated revocation",
                    _text(
                        "Revoking an already-revoked credential is idempotent and leaves it "
                        "revoked."
                    ),
                ),
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v2,), scope=SCOPE)
    return governor, reasoner, outcome


def test_compatible_extension_adds_a_claim_at_the_same_address_and_preserves_the_old_one() -> None:
    governor, reasoner, outcome = _credential_story()

    call_1, call_2 = _routes(outcome)
    assert call_1 == [AdmissionRoute.APPLY]
    assert call_2 == [AdmissionRoute.APPLY, AdmissionRoute.APPLY]
    assert len(reasoner.requests) == 2
    # ONE address for the locus; no duplicate identity was minted.
    assert _in_scope_address_ids(governor) == [_addr("J-cred")]
    # The existing compatible claim is still current and the new one sits beside it.
    assert _live_claims_at(governor, _addr("J-cred")) == {
        _claim("J-cred-revoke"): "effect of revocation",
        _claim("J-cred-idem"): "repeated revocation",
    }
    # Nothing was superseded or left pending.
    assert outcome.pending_supersede_judgment_ids == ()
    assert governor.view().pending_judgment_ids == ()
    assert governor.state().semantic.supersessions == ()


def test_extension_call_two_saw_the_bound_locus_with_its_live_claim() -> None:
    _, reasoner, _ = _credential_story()

    call_2 = reasoner.requests[1]
    assert JudgmentKind.CREATE_ADDRESS not in call_2.allowed_judgment_kinds
    assert [a.address_id for a in call_2.known_addresses] == [_addr("J-cred")]
    assert [c.claim_id for c in call_2.known_claims] == [_claim("J-cred-revoke")]
    assert [e.evidence_id for e in call_2.evidence] == ["EV-CRED-2"]


# --- counterexample A: restatement --------------------------------------------------------


def test_restatement_supports_the_current_claim_and_adds_no_claim() -> None:
    _, governor = _governor()
    v1 = _evidence("EV-LEASE-1", "A lease lasts 90 seconds.", artifact_ref="workers/lease.md")
    _seed(
        governor,
        v1,
        [
            (
                "J-lease",
                "worker lease",
                "how long a lease lasts",
                [("J-lease-90", "duration", _quantity("90", "second"))],
            )
        ],
    )
    v2 = _evidence(
        "EV-LEASE-2",
        "A lease lasts one and a half minutes.",
        artifact_ref="workers/lease.md",
        supersedes="EV-LEASE-1",
    )
    reasoner = SpecReasoner(
        [
            [
                _bind(
                    "J-lease-bind",
                    _addr("J-lease"),
                    "EV-LEASE-2",
                    "worker lease",
                    "how long a lease lasts",
                )
            ],
            [_support("J-lease-support", _claim("J-lease-90"), "EV-LEASE-2")],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v2,), scope=SCOPE)

    assert _routes(outcome) == ([AdmissionRoute.APPLY], [AdmissionRoute.APPLY])
    assert _in_scope_address_ids(governor) == [_addr("J-lease")]
    assert _live_claims_at(governor, _addr("J-lease")) == {_claim("J-lease-90"): "duration"}
    assert "J-lease-support" in governor.view().active_support_judgment_ids


# --- counterexample B: correction (and its revert) ----------------------------------------


def _timeout_story() -> tuple[InMemoryEventStore, SemanticGovernor, DeltaOutcome]:
    store, governor = _governor()
    v1 = _evidence(
        "EV-TO-1", "An execution times out after 30 seconds.", artifact_ref="exec/timeout.md"
    )
    _seed(
        governor,
        v1,
        [
            (
                "J-to",
                "execution attempt",
                "how long one execution may run",
                [("J-to-30", "time limit", _quantity("30", "second"))],
            )
        ],
    )
    v2 = _evidence(
        "EV-TO-2",
        "An execution times out after 45 seconds.",
        artifact_ref="exec/timeout.md",
        supersedes="EV-TO-1",
    )
    reasoner = SpecReasoner(
        [
            [
                _bind(
                    "J-to-bind",
                    _addr("J-to"),
                    "EV-TO-2",
                    "execution attempt",
                    "how long one execution may run",
                )
            ],
            [
                _assert(
                    "J-to-45", _addr("J-to"), "EV-TO-2", "time limit", _quantity("45", "second")
                ),
                _supersede("J-to-sup", "J-to-30", "EV-TO-2"),
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v2,), scope=SCOPE)
    return store, governor, outcome


def test_correction_asserts_the_new_meaning_and_leaves_supersession_to_human_authority() -> None:
    store, governor, outcome = _timeout_story()

    call_1, call_2 = _routes(outcome)
    assert call_1 == [AdmissionRoute.APPLY]
    assert call_2 == [AdmissionRoute.APPLY, AdmissionRoute.REQUIRE_SECOND_LENS]
    # Same address; the corrected meaning is current; the old one stays current until a
    # human agrees — the model-originated SUPERSEDE never applies by itself.
    assert _in_scope_address_ids(governor) == [_addr("J-to")]
    assert set(_live_claims_at(governor, _addr("J-to"))) == {_claim("J-to-30"), _claim("J-to-45")}
    assert outcome.pending_supersede_judgment_ids == ("J-to-sup",)
    assert "J-to-sup" not in governor.state().semantic.applied_judgment_ids

    events_before = len(store.load(PROJECT))
    governor.record_authority(_authority_record("human://alice"))
    decision = governor.submit(
        _supersede("J-to-human", "J-to-30", "EV-TO-2", reasoner=HUMAN),
        human_actor_id="human://alice",
    )

    assert decision.route is AdmissionRoute.APPLY
    assert decision.reasons == ("HUMAN_AUTHORITY",)
    assert _live_claims_at(governor, _addr("J-to")) == {_claim("J-to-45"): "time limit"}
    assert dict(governor.view().satisfied_by) == {"J-to-sup": "J-to-human"}
    assert governor.view().pending_judgment_ids == ()
    # Append-only: the superseded claim, its judgment and every earlier event stay readable.
    semantic = governor.state().semantic
    assert _claim("J-to-30") in semantic.claims
    assert "J-to-30" in semantic.applied_judgment_ids
    assert "J-to-sup" not in semantic.applied_judgment_ids
    assert len(store.load(PROJECT)) > events_before


def test_revert_returns_the_historical_meaning_as_a_new_claim_without_resurrection() -> None:
    _, governor, _ = _timeout_story()
    governor.record_authority(_authority_record("human://alice"))
    assert (
        governor.submit(
            _supersede("J-to-human", "J-to-30", "EV-TO-2", reasoner=HUMAN),
            human_actor_id="human://alice",
        ).route
        is AdmissionRoute.APPLY
    )
    v3 = _evidence(
        "EV-TO-3",
        "An execution times out after 30 seconds.",
        artifact_ref="exec/timeout.md",
        supersedes="EV-TO-2",
    )
    reasoner = SpecReasoner(
        [
            [
                _bind(
                    "J-to-bind3",
                    _addr("J-to"),
                    "EV-TO-3",
                    "execution attempt",
                    "how long one execution may run",
                )
            ],
            [
                # The historical proposition returns as a NEW claim (the dead claim is never
                # resurrected and never counts as a live duplicate); the immediately-current
                # incompatible claim is proposed for supersession.
                _assert(
                    "J-to-30-again",
                    _addr("J-to"),
                    "EV-TO-3",
                    "time limit",
                    _quantity("30", "second"),
                ),
                _supersede("J-to-sup2", "J-to-45", "EV-TO-3"),
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v3,), scope=SCOPE)

    assert _routes(outcome) == (
        [AdmissionRoute.APPLY],
        [AdmissionRoute.APPLY, AdmissionRoute.REQUIRE_SECOND_LENS],
    )
    assert (
        governor.submit(
            _supersede("J-to-human2", "J-to-45", "EV-TO-3", reasoner=HUMAN),
            human_actor_id="human://alice",
        ).route
        is AdmissionRoute.APPLY
    )
    assert _live_claims_at(governor, _addr("J-to")) == {_claim("J-to-30-again"): "time limit"}
    semantic = governor.state().semantic
    assert {_claim("J-to-30"), _claim("J-to-45"), _claim("J-to-30-again")} <= set(semantic.claims)
    assert _claim("J-to-30") != _claim("J-to-30-again")


# --- counterexample C: distinct locus inside one evidence item -----------------------------


def test_distinct_locus_in_the_same_change_is_not_bound_to_the_known_locus() -> None:
    _, governor = _governor()
    v1 = _evidence(
        "EV-CANCEL-1",
        "After a job is cancelled no future execution attempt starts; a running attempt is "
        "not interrupted.",
        artifact_ref="jobs/lifecycle.md",
    )
    _seed(
        governor,
        v1,
        [
            (
                "J-cancel",
                "job cancellation",
                "what cancellation does to execution attempts",
                [
                    (
                        "J-cancel-attempts",
                        "effect on attempts",
                        _text("No future attempt starts; a running attempt is not interrupted."),
                    )
                ],
            )
        ],
    )
    v2 = _evidence(
        "EV-CANCEL-2",
        "After a job is cancelled no future execution attempt starts; a running attempt is "
        "not interrupted. "
        "Audit records are retained for 30 days.",
        artifact_ref="jobs/lifecycle.md",
        supersedes="EV-CANCEL-1",
    )
    reasoner = SpecReasoner(
        [
            [
                _bind(
                    "J-cancel-bind",
                    _addr("J-cancel"),
                    "EV-CANCEL-2",
                    "job cancellation",
                    "what cancellation does to execution attempts",
                ),
                _create(
                    "J-audit", "EV-CANCEL-2", "audit records", "how long audit records are retained"
                ),
            ],
            [
                _support("J-cancel-support", _claim("J-cancel-attempts"), "EV-CANCEL-2"),
                _assert(
                    "J-audit-30",
                    _addr("J-audit"),
                    "EV-CANCEL-2",
                    "retention period",
                    _quantity("30", "day"),
                ),
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v2,), scope=SCOPE)

    assert _routes(outcome) == (
        [AdmissionRoute.APPLY, AdmissionRoute.APPLY],
        [AdmissionRoute.APPLY, AdmissionRoute.APPLY],
    )
    assert _in_scope_address_ids(governor) == sorted([_addr("J-cancel"), _addr("J-audit")])
    assert _live_claims_at(governor, _addr("J-cancel")) == {
        _claim("J-cancel-attempts"): "effect on attempts"
    }
    assert _live_claims_at(governor, _addr("J-audit")) == {_claim("J-audit-30"): "retention period"}


# --- counterexample D: the extension shape in the cancellation domain ----------------------


def test_compatible_extension_d_repeated_action_idempotency_joins_the_existing_locus() -> None:
    _, governor = _governor()
    v1 = _evidence("EV-D-1", "Cancellation stops future attempts.", artifact_ref="jobs/cancel.md")
    _seed(
        governor,
        v1,
        [
            (
                "J-d",
                "job cancellation",
                "what cancellation does",
                [
                    (
                        "J-d-stop",
                        "effect on future attempts",
                        _text("Cancellation stops future attempts."),
                    )
                ],
            )
        ],
    )
    v2 = _evidence(
        "EV-D-2",
        "Cancellation stops future attempts. Repeated cancellation is idempotent.",
        artifact_ref="jobs/cancel.md",
        supersedes="EV-D-1",
    )
    reasoner = SpecReasoner(
        [
            [
                _bind(
                    "J-d-bind", _addr("J-d"), "EV-D-2", "job cancellation", "what cancellation does"
                )
            ],
            [
                _support("J-d-support", _claim("J-d-stop"), "EV-D-2"),
                _assert(
                    "J-d-idem",
                    _addr("J-d"),
                    "EV-D-2",
                    "repeated cancellation",
                    _text("Repeated cancellation is idempotent."),
                ),
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v2,), scope=SCOPE)

    assert _routes(outcome) == (
        [AdmissionRoute.APPLY],
        [AdmissionRoute.APPLY, AdmissionRoute.APPLY],
    )
    assert _in_scope_address_ids(governor) == [_addr("J-d")]
    assert _live_claims_at(governor, _addr("J-d")) == {
        _claim("J-d-stop"): "effect on future attempts",
        _claim("J-d-idem"): "repeated cancellation",
    }
    assert governor.state().semantic.supersessions == ()


# --- counterexample E + address granularity ----------------------------------------------


def _retry_story() -> SemanticGovernor:
    """Subject "job execution", two DISTINCT loci: retry timing policy, audit retention."""
    _, governor = _governor()
    v1 = _evidence(
        "EV-RETRY-1",
        "Retries use exponential backoff. Audit records are kept for 30 days.",
        artifact_ref="jobs/execution.md",
    )
    _seed(
        governor,
        v1,
        [
            (
                "J-retry",
                "job execution",
                "retry timing policy",
                [("J-retry-backoff", "backoff shape", _text("Retries use exponential backoff."))],
            ),
            (
                "J-auditp",
                "job execution",
                "audit retention policy",
                [("J-auditp-30", "retention period", _quantity("30", "day"))],
            ),
        ],
    )
    return governor


def test_address_granularity_same_subject_different_locus_stays_two_addresses() -> None:
    governor = _retry_story()

    assert _in_scope_address_ids(governor) == sorted([_addr("J-retry"), _addr("J-auditp")])
    assert _live_claims_at(governor, _addr("J-retry")) == {
        _claim("J-retry-backoff"): "backoff shape"
    }
    assert _live_claims_at(governor, _addr("J-auditp")) == {
        _claim("J-auditp-30"): "retention period"
    }


def test_address_granularity_same_locus_new_proposition_is_one_address_two_claims() -> None:
    governor = _retry_story()
    v2 = _evidence(
        "EV-RETRY-2",
        "Retries use exponential backoff; retry jitter is capped at 500 ms. Audit records are "
        "kept for 30 days.",
        artifact_ref="jobs/execution.md",
        supersedes="EV-RETRY-1",
    )
    reasoner = SpecReasoner(
        [
            # Partial overlap (E): the jitter cap answers the retry-timing question -> the
            # retry locus, NOT the same-subject audit locus, and NOT a new address.
            [
                _bind(
                    "J-retry-bind",
                    _addr("J-retry"),
                    "EV-RETRY-2",
                    "job execution",
                    "retry timing policy",
                ),
                _bind(
                    "J-auditp-bind",
                    _addr("J-auditp"),
                    "EV-RETRY-2",
                    "job execution",
                    "audit retention policy",
                ),
            ],
            [
                _support("J-retry-support", _claim("J-retry-backoff"), "EV-RETRY-2"),
                _assert(
                    "J-retry-jitter",
                    _addr("J-retry"),
                    "EV-RETRY-2",
                    "jitter cap",
                    _quantity("500", "millisecond"),
                ),
                _support("J-auditp-support", _claim("J-auditp-30"), "EV-RETRY-2"),
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v2,), scope=SCOPE)

    assert _routes(outcome) == (
        [AdmissionRoute.APPLY, AdmissionRoute.APPLY],
        [AdmissionRoute.APPLY, AdmissionRoute.APPLY, AdmissionRoute.APPLY],
    )
    # Still exactly two addresses: same subject did not merge them, the new proposition did
    # not split the retry locus.
    assert _in_scope_address_ids(governor) == sorted([_addr("J-retry"), _addr("J-auditp")])
    assert _live_claims_at(governor, _addr("J-retry")) == {
        _claim("J-retry-backoff"): "backoff shape",
        _claim("J-retry-jitter"): "jitter cap",
    }
    assert _live_claims_at(governor, _addr("J-auditp")) == {
        _claim("J-auditp-30"): "retention period"
    }


# --- coexistence and the structural duplicate backstop -------------------------------------


def test_several_compatible_claims_coexist_and_a_byte_identical_reassert_is_refused() -> None:
    governor = _retry_story()
    v2 = _evidence(
        "EV-RETRY-2",
        "Retries use exponential backoff with a maximum delay of 30 seconds; jitter is capped "
        "at 500 ms.",
        artifact_ref="jobs/execution.md",
        supersedes="EV-RETRY-1",
    )
    jitter = _quantity("500", "millisecond")
    reasoner = SpecReasoner(
        [
            [
                _bind(
                    "J-retry-bind",
                    _addr("J-retry"),
                    "EV-RETRY-2",
                    "job execution",
                    "retry timing policy",
                )
            ],
            [
                _support("J-retry-support", _claim("J-retry-backoff"), "EV-RETRY-2"),
                _assert(
                    "J-retry-max",
                    _addr("J-retry"),
                    "EV-RETRY-2",
                    "maximum delay",
                    _quantity("30", "second"),
                ),
                _assert("J-retry-jitter", _addr("J-retry"), "EV-RETRY-2", "jitter cap", jitter),
                # A second draft carrying the exact same proposition: refused structurally,
                # never a fourth live claim, and the response is not discarded.
                _assert("J-retry-jitter-dup", _addr("J-retry"), "EV-RETRY-2", "jitter cap", jitter),
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v2,), scope=SCOPE)

    _, call_2 = _routes(outcome)
    assert call_2 == [
        AdmissionRoute.APPLY,
        AdmissionRoute.APPLY,
        AdmissionRoute.APPLY,
        AdmissionRoute.REJECT,
    ]
    duplicate = outcome.stage_decisions[1][3]
    assert duplicate.reasons == (
        f"STRUCTURAL: claim {_claim('J-retry-jitter')} already asserts this proposition at "
        f"{_addr('J-retry')}; support it instead",
    )
    assert _live_claims_at(governor, _addr("J-retry")) == {
        _claim("J-retry-backoff"): "backoff shape",
        _claim("J-retry-max"): "maximum delay",
        _claim("J-retry-jitter"): "jitter cap",
    }
    assert _claim("J-retry-jitter-dup") not in governor.state().semantic.claims


def test_a_byte_identical_reassert_in_a_later_delta_is_refused_too() -> None:
    governor, _, _ = _credential_story()
    v3 = _evidence(
        "EV-CRED-3", CREDENTIAL_V2, artifact_ref="auth/credentials.md", supersedes="EV-CRED-2"
    )
    reasoner = SpecReasoner(
        [
            [
                _bind(
                    "J-cred-bind3",
                    _addr("J-cred"),
                    "EV-CRED-3",
                    "API credential lifecycle",
                    "what revocation does to the credential",
                )
            ],
            [
                _assert(
                    "J-cred-idem-again",
                    _addr("J-cred"),
                    "EV-CRED-3",
                    "repeated revocation",
                    _text(
                        "Revoking an already-revoked credential is idempotent and leaves it "
                        "revoked."
                    ),
                )
            ],
        ]
    )
    outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=(v3,), scope=SCOPE)

    assert _routes(outcome) == ([AdmissionRoute.APPLY], [AdmissionRoute.REJECT])
    assert len(_live_claims_at(governor, _addr("J-cred"))) == 2


def test_no_model_originated_supersede_ever_applies_without_a_human() -> None:
    _, governor, outcome = _timeout_story()
    # Even re-proposing it from the model changes nothing: material, no independent lens.
    again = governor.submit(_supersede("J-to-sup-again", "J-to-30", "EV-TO-2"))

    assert again.route is AdmissionRoute.REQUIRE_SECOND_LENS
    assert "J-to-sup" not in governor.state().semantic.applied_judgment_ids
    assert "J-to-sup-again" not in governor.state().semantic.applied_judgment_ids
    assert set(governor.view().pending_judgment_ids) == {"J-to-sup", "J-to-sup-again"}
    assert outcome.pending_supersede_judgment_ids == ("J-to-sup",)
