"""Full fake lifecycle of the 9P longitudinal dogfood (plan "Integration"; spec §26, §27, §29, §34).

One end-to-end story, told twice: directly through ``run_arm_f`` / ``run_arm_r`` /
``structural_metrics`` / ``deterministic_verdicts`` and through the entry point
``scripts/run_longitudinal_dogfood.py`` (``--seal`` then the run) with a scripted stdin.

The four timeline paths are served by a fake Git with real-looking versioned texts
(T1 constitution + spec v1; T2 spec v2 — corrected framing; T3 reducer v1 + identity;
T4 reducer v2 + spec v3). The only reasoner is a scripted fake playing the ideal story
in exactly 16 calls: Arm F CREATE A / B / control at T1, BIND A / B and correct both at
T2 (ASSERT new + SUPERSEDE old), CREATE C with an INFERRED defect claim at T3, BIND C and
correct it at T4; Arm R creates everything afresh at every T. The only human is a
scripted authorizer. ZERO live calls: a socket guard covers the module and the real
adapter class is replaced by one that raises on construction.

Scenario 1 (AGREE ×3) asserts the deterministic parts of E1–E12, the budgets, the ledger
counts, delta-only input for F, cumulative input for R, replay of both arms, the artifact
set and the §34 decision rule (with the architect verdicts supplied as PASS). Scenario 2
(DECLINE at Track C) asserts E12 applies and holds while ``intent-engine`` stays blocked
and ``constitution`` stays clear.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest

import scripts.run_longitudinal_dogfood as script
from foundry.adapters.memory.event_store import InMemoryEventStore
from foundry.adapters.semantics import xai_reasoner
from foundry.adapters.semantics.xai_reasoner import (
    SemanticDraftPayload,
    SemanticReasoningReceipt,
    render_request,
)
from foundry.application.assimilation_context import (
    ASSIMILATION_JUDGMENT_KINDS,
    CLAIM_ASSIMILATION_JUDGMENT_KINDS,
)
from foundry.application.replay import replay
from foundry.application.semantic_reducer import address_id_for, claim_id_for
from foundry.domain.admission import AdmissionPolicy
from foundry.domain.common import Authority
from foundry.domain.events import EventType, StoredEvent, parse_event
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
)
from foundry.domain.semantic_view import CurrentSemanticView, derive_view
from foundry.domain.state import IntentState
from foundry.experiments.longitudinal.arm_f import (
    MAX_F_CALLS,
    PROJECT_ID,
    ArmFResult,
    StepRecord,
    run_arm_f,
)
from foundry.experiments.longitudinal.arm_r import MAX_R_CALLS, ArmRStep, project_id_for, run_arm_r
from foundry.experiments.longitudinal.artifacts import (
    EXPERIMENT_DIR_NAME,
    POST_RUN_FILES,
    PRE_RUN_FILES,
    TIMELINE_PROJECT_ID,
)
from foundry.experiments.longitudinal.authority import (
    ARCHITECT_ACTOR,
    AuthorizationBudget,
    AuthorizationDecision,
)
from foundry.experiments.longitudinal.derivations import CONTROL_CHAIN, TRACK_A_CHAIN
from foundry.experiments.longitudinal.expectations import (
    EXPECTATIONS,
    LOCKED_CEILINGS,
    DecisionInputs,
    ExpectationManifest,
    ExpectationVerdict,
    Verdict,
    decision_rule,
    seal,
)
from foundry.experiments.longitudinal.scoring import (
    ScoringManifest,
    StructuralMetrics,
    deterministic_verdicts,
    replay_matches,
    structural_metrics,
)
from foundry.experiments.longitudinal.timeline import (
    VersionedEvidence,
    load_timeline,
    persistent_delta,
    reconstruction_corpus,
)
from foundry.ports.semantic_reasoner import ReasoningRequest

T0 = datetime(2026, 9, 11, tzinfo=UTC)
FROZEN_SHA = "f" * 40
MODEL = ReasonerFingerprint(provider="xai", model="grok-4.6", policy_version="9p-v1")
SCOPE = "intent-engine"
SCOPES = ("intent-engine", "constitution")
FAKE_KEY = "xai-TESTKEY000000000000000000"

T1 = "097584a39dd76cf86510500acb548778ce00fad9"
T2 = "2539ff81f79f085c1eba42718947050c1b3ac61c"
T3 = "90246a8b986b0dcbcbae6a4f3484204f916afeb5"
T4 = "779a66ac90eceaea7eb7d4af0692ee4f167292fc"

CONSTITUTION = "FOUNDRY_CONSTITUTION.md"
SPEC = "docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md"
REDUCER = "src/foundry/application/semantic_reducer.py"
IDENTITY = "src/foundry/domain/semantic_identity.py"

# Evidence ids the Task 10 loader mints, per T, in timeline order.
EV_CONSTITUTION = "EV-T1-01"
EV_SPEC_V1 = "EV-T1-02"
EV_SPEC_V2 = "EV-T2-01"
EV_REDUCER_V1 = "EV-T3-01"
EV_IDENTITY_V1 = "EV-T3-02"
EV_REDUCER_V2 = "EV-T4-01"
EV_SPEC_V3 = "EV-T4-02"
DELTA_IDS_BY_T: dict[int, tuple[str, ...]] = {
    1: (EV_CONSTITUTION, EV_SPEC_V1),
    2: (EV_SPEC_V2,),
    3: (EV_REDUCER_V1, EV_IDENTITY_V1),
    4: (EV_REDUCER_V2, EV_SPEC_V3),
}
ALL_EVIDENCE_IDS = tuple(ev for t in (1, 2, 3, 4) for ev in DELTA_IDS_BY_T[t])

# --- real-looking versioned texts -------------------------------------------------------

CONSTITUTION_V1 = """# Foundry Constitution

## The Law of Descent

Decisions originate at the highest applicable layer and flow down. Lower layers
execute or invalidate upward. They never decide.

Intent -> Architecture -> Planning -> Build ; Verification is an independent authority.

## Separation of authority

- Builder is never Verifier. Self-approval fails hardest under pressure.
- Intent is never Architecture. Design must not silently redefine the goal.
- Architecture is never Planning. What it should be is not what order to build it.

## Standing rules

- Unmeasurable is a defect. A criterion no one can run is not a criterion.
- filesAffected is a contract. Editing outside it fails the package.
- Assumptions are superseded, never edited.
- Report outcomes faithfully. The evidence ledger is the only thing the system trusts.
"""

SPEC_V1 = """# Intent Intelligence v2 - design

## 6. Admission

An admitted binding is provisional: the address it names is treated as a candidate
identity until a second lens confirms it. Admission therefore records the binding but
does not yet make the address referable from other judgments.

## 9. Validation

Validation is a gate: a judgment either passes the structural checks and is applied,
or fails them and is rejected. There is no held state; validation is binary.

## 11. Provenance

Every semantic object carries a Provenance with source_kind and source_ref.
"""

SPEC_V2 = """# Intent Intelligence v2 - design

## 6. Admission

CORRECTION. An admitted binding is durable and referential: once admission routes a
BIND_TO_ADDRESS to APPLY, the address it names is a stable identity that later
judgments may reference by id. Admission is not a provisional stage; nothing waits for
a second lens unless the kind is material.

## 9. Validation

CORRECTION. Validation is not a binary gate. Admission has four routes - APPLY,
REQUIRE_SECOND_LENS, REQUIRE_HUMAN, REJECT - and a held judgment is preserved in the
ledger with its route so a later authority may satisfy it. Validation is a routing
decision over a recorded proposal, never a filter that discards.

## 11. Provenance

Every semantic object carries a Provenance with source_kind and source_ref.
"""

REDUCER_V1 = '''"""Semantic reducer: folds SEMANTIC_* events into SemanticState."""

from foundry.domain.common import Provenance


def _provenance_for(event, judgment):
    # Identity of the provenance is taken from the judgment id only; the stored event
    # id is not carried, so two applications of one judgment are indistinguishable.
    return Provenance(
        source_kind=judgment.reasoner.provider,
        source_ref=judgment.judgment_id,
        source_event_ids=(),
    )


def address_id_for(project_id: str, judgment_id: str) -> str:
    return _minted_id("ADDR", project_id, judgment_id)
'''

IDENTITY_V1 = '''"""Semantic identity: addresses, candidates, claims."""

from foundry.domain.common import FrozenModel


class SemanticAddress(FrozenModel):
    address_id: str
    project_id: str
    subject: str
    facet: str
    scope: tuple[str, ...] = ()
    created_by_judgment_id: str


class SemanticClaim(FrozenModel):
    claim_id: str
    address_id: str
    predicate: str
    evidence_ids: tuple[str, ...]
    created_by_judgment_id: str
'''

REDUCER_V2 = '''"""Semantic reducer: folds SEMANTIC_* events into SemanticState."""

from foundry.domain.common import Provenance


def _provenance_for(event, judgment):
    # FIX: the provenance now carries the stored event id that applied the judgment,
    # so Provenance.source_event_ids identifies the exact ledger position and two
    # applications are distinguishable on replay.
    return Provenance(
        source_kind=judgment.reasoner.provider,
        source_ref=judgment.judgment_id,
        source_event_ids=(event.event_id,),
    )


def address_id_for(project_id: str, judgment_id: str) -> str:
    return _minted_id("ADDR", project_id, judgment_id)
'''

SPEC_V3 = """# Intent Intelligence v2 - design

## 6. Admission

An admitted binding is durable and referential: once admission routes a
BIND_TO_ADDRESS to APPLY, the address it names is a stable identity that later
judgments may reference by id.

## 9. Validation

Admission has four routes - APPLY, REQUIRE_SECOND_LENS, REQUIRE_HUMAN, REJECT - and a
held judgment is preserved in the ledger with its route.

## 11. Provenance

Every semantic object carries a Provenance with source_kind, source_ref and
source_event_ids; the last names the ledger events that produced the object, so the
reducer's provenance is identifiable per application (see semantic_reducer.py).
"""

# --- scripted judgment ids (Arm F) ----------------------------------------------------------

J_CREATE_A = "J-T1-create-A"
J_CREATE_B = "J-T1-create-B"
J_CREATE_N = "J-T1-create-N"
J_CLAIM_A = "J-T1-claim-A"
J_CLAIM_B = "J-T1-claim-B"
J_CLAIM_N = "J-T1-claim-N"
J_BIND_A = "J-T2-bind-A"
J_BIND_B = "J-T2-bind-B"
J_CLAIM_A_NEW = "J-T2-claim-A-new"
J_SUPERSEDE_A = "J-T2-supersede-A"
J_CLAIM_B_NEW = "J-T2-claim-B-new"
J_SUPERSEDE_B = "J-T2-supersede-B"
J_CREATE_C = "J-T3-create-C"
J_CLAIM_C = "J-T3-claim-C"
J_BIND_C = "J-T4-bind-C"
J_CLAIM_C_NEW = "J-T4-claim-C-new"
J_SUPERSEDE_C = "J-T4-supersede-C"

ADDR_A = address_id_for(PROJECT_ID, J_CREATE_A)
ADDR_B = address_id_for(PROJECT_ID, J_CREATE_B)
ADDR_N = address_id_for(PROJECT_ID, J_CREATE_N)
ADDR_C = address_id_for(PROJECT_ID, J_CREATE_C)
CLAIM_A = claim_id_for(PROJECT_ID, J_CLAIM_A)
CLAIM_B = claim_id_for(PROJECT_ID, J_CLAIM_B)
CLAIM_N = claim_id_for(PROJECT_ID, J_CLAIM_N)
CLAIM_A_NEW = claim_id_for(PROJECT_ID, J_CLAIM_A_NEW)
CLAIM_B_NEW = claim_id_for(PROJECT_ID, J_CLAIM_B_NEW)
CLAIM_C = claim_id_for(PROJECT_ID, J_CLAIM_C)
CLAIM_C_NEW = claim_id_for(PROJECT_ID, J_CLAIM_C_NEW)

F_JUDGMENTS_BY_T: dict[int, tuple[str, ...]] = {
    1: (J_CREATE_A, J_CREATE_B, J_CREATE_N, J_CLAIM_A, J_CLAIM_B, J_CLAIM_N),
    2: (J_BIND_A, J_BIND_B, J_CLAIM_A_NEW, J_SUPERSEDE_A, J_CLAIM_B_NEW, J_SUPERSEDE_B),
    3: (J_CREATE_C, J_CLAIM_C),
    4: (J_BIND_C, J_CLAIM_C_NEW, J_SUPERSEDE_C),
}

# Ledger arithmetic. Every judgment is two events (recorded + admission decided).
# T0: 1 authority. T1: 2 ingests + 6 judgments + 5 derivation edges = 19.
# T2: 1 ingest + 6 AI judgments + 2 human AGREE judgments = 17.
# T3: 2 ingests + 2 judgments = 6. T4: 2 ingests + 3 AI judgments (+ 1 human AGREE) = 10.
F_LEDGER_LENGTH_ALL_AGREED = 1 + 19 + 17 + 6 + 10
F_LEDGER_LENGTH_C_DECLINED = F_LEDGER_LENGTH_ALL_AGREED - 2
# Arm R at T: n corpus items -> n ingests + n creations + n claims = 5n events.
R_CORPUS_SIZE_BY_T = {1: 2, 2: 3, 3: 5, 4: 7}

type Batch = Callable[[ReasoningRequest], list[SemanticJudgment]]


# --- no network, no adapter, ever ------------------------------------------------------------


def _refuse_network(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("network access is forbidden in the longitudinal lifecycle test")


ADAPTER_CONSTRUCTIONS: list[str] = []


class _ForbiddenAdapter:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        ADAPTER_CONSTRUCTIONS.append("constructed")
        raise AssertionError("XAISemanticReasoner must never be constructed in this module")


@pytest.fixture(autouse=True, scope="module")
def _guards() -> Iterator[None]:
    patcher = pytest.MonkeyPatch()
    patcher.setattr(socket.socket, "connect", _refuse_network)
    patcher.setattr(socket, "create_connection", _refuse_network)
    patcher.setattr(xai_reasoner, "XAISemanticReasoner", _ForbiddenAdapter)
    try:
        yield
    finally:
        patcher.undo()


def test_socket_guard_and_adapter_guard_are_live() -> None:
    with pytest.raises(RuntimeError, match="forbidden"), socket.socket() as sock:
        sock.connect(("127.0.0.1", 9))
    with pytest.raises(RuntimeError, match="forbidden"):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(AssertionError, match="never be constructed"):
        xai_reasoner.XAISemanticReasoner(api_key="xai-nope", model="grok-4.6")
    ADAPTER_CONSTRUCTIONS.clear()


# --- fakes -------------------------------------------------------------------------------------


class FakeGit:
    """Serves bytes for exact ``(commit, path)`` pairs; HEAD and status are scripted."""

    def __init__(self, blobs: dict[tuple[str, str], bytes], *, head: str = FROZEN_SHA) -> None:
        self._blobs = blobs
        self._head = head

    def blob(self, sha: str, path: str) -> bytes:
        if (sha, path) not in self._blobs:
            raise RuntimeError(f"no blob for {sha}:{path}")
        return self._blobs[(sha, path)]

    def blob_sha(self, sha: str, path: str) -> str:
        return hashlib.sha1(b"blob " + self.blob(sha, path)).hexdigest()

    def head(self) -> str:
        return self._head

    def dirty(self) -> str:
        return ""

    def branch(self) -> str:
        return "fake"


class ScriptedReasoner:
    """One scripted batch per call; records requests; exposes receipts and drafts.

    Receipts estimate tokens from the rendered request bytes so F-versus-R economics
    reflect what each arm was actually shown.
    """

    def __init__(self, batches: list[Batch]) -> None:
        self._batches = batches
        self.requests: list[ReasoningRequest] = []
        self._receipts: list[SemanticReasoningReceipt] = []
        self._drafts: list[SemanticDraftPayload] = []

    @property
    def fingerprint(self) -> ReasonerFingerprint:
        return MODEL

    @property
    def receipts(self) -> tuple[SemanticReasoningReceipt, ...]:
        return tuple(self._receipts)

    @property
    def draft_payloads(self) -> tuple[SemanticDraftPayload, ...]:
        return tuple(self._drafts)

    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._batches):
            raise AssertionError(f"CALL {index + 1} ATTEMPTED: only {len(self._batches)} scripted")
        input_tokens = len(render_request(request)) // 4
        self._receipts.append(
            SemanticReasoningReceipt(
                invocation_id=f"INV-{index + 1}",
                model="grok-4.6",
                reasoning_effort="high",
                input_tokens=input_tokens,
                output_tokens=64,
                cost_usd=input_tokens * 3e-6,
                wall_clock_ms=1,
                draft_count=0,
            )
        )
        self._drafts.append(SemanticDraftPayload(drafts=()))
        return tuple(self._batches[index](request))


class ScriptedAuthorizer:
    """Answers scripted decisions in order; records every judgment presented to it."""

    def __init__(self, answers: list[AuthorizationDecision]) -> None:
        self._answers = answers
        self.presented: list[SemanticJudgment] = []

    def __call__(self, pending: SemanticJudgment) -> AuthorizationDecision:
        self.presented.append(pending)
        index = len(self.presented) - 1
        if index >= len(self._answers):
            raise AssertionError(f"AUTHORIZATION {index + 1} ATTEMPTED: only {index} scripted")
        return self._answers[index]


# --- builders ----------------------------------------------------------------------------------


def _blobs() -> dict[tuple[str, str], bytes]:
    return {
        (T1, CONSTITUTION): CONSTITUTION_V1.encode(),
        (T1, SPEC): SPEC_V1.encode(),
        (T2, SPEC): SPEC_V2.encode(),
        (T3, REDUCER): REDUCER_V1.encode(),
        (T3, IDENTITY): IDENTITY_V1.encode(),
        (T4, REDUCER): REDUCER_V2.encode(),
        (T4, SPEC): SPEC_V3.encode(),
    }


def _timeline() -> tuple[VersionedEvidence, ...]:
    return load_timeline(
        FakeGit(_blobs()),
        project_id=TIMELINE_PROJECT_ID,
        observed_at_for=lambda t: T0 + timedelta(days=t),
    )


def _clock() -> Callable[[], datetime]:
    ticks: Iterator[int] = count()
    return lambda: T0 + timedelta(minutes=next(ticks))


def _id_factory() -> Callable[[str], str]:
    ticks = count(1)
    return lambda prefix: f"{prefix}-{next(ticks)}"


def _judgment(
    judgment_id: str, request: ReasoningRequest, proposal: JudgmentProposal, evidence_id: str
) -> SemanticJudgment:
    return SemanticJudgment(
        judgment_id=judgment_id,
        project_id=request.project_id,
        proposal=proposal,
        visible_evidence_ids=(evidence_id,),
        rationale=f"Rationale for {judgment_id}.",
        reasoner=MODEL,
        invocation_id=f"INV-{judgment_id}",
        proposed_at=T0,
    )


def _evidence_in(request: ReasoningRequest, evidence_id: str) -> Any:
    return next(item for item in request.evidence if item.evidence_id == evidence_id)


def _candidate(
    candidate_id: str, request: ReasoningRequest, evidence_id: str, subject: str, facet: str
) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        subject=subject,
        facet=facet,
        scope=_evidence_in(request, evidence_id).scope,
        evidence_ids=(evidence_id,),
    )


def _create(
    judgment_id: str, request: ReasoningRequest, evidence_id: str, subject: str, facet: str
) -> SemanticJudgment:
    assert evidence_id in {item.evidence_id for item in request.evidence}
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id, subject, facet)
    return _judgment(judgment_id, request, CreateAddressProposal(candidate=candidate), evidence_id)


def _bind(
    judgment_id: str,
    request: ReasoningRequest,
    address_id: str,
    evidence_id: str,
    subject: str,
    facet: str,
) -> SemanticJudgment:
    known = {a.address_id for a in request.known_addresses}
    assert address_id in known, f"BIND target {address_id} is not a known address"
    candidate = _candidate(f"CAND-{judgment_id}", request, evidence_id, subject, facet)
    proposal = BindToAddressProposal(candidate=candidate, address_id=address_id)
    return _judgment(judgment_id, request, proposal, evidence_id)


def _claim(
    judgment_id: str,
    request: ReasoningRequest,
    address_id: str,
    evidence_id: str,
    predicate: str,
    text: str,
    authority: Authority = Authority.OBSERVED,
) -> SemanticJudgment:
    known = {a.address_id for a in request.known_addresses}
    assert address_id in known, f"ASSERT target {address_id} is not a known address"
    proposal = AssertClaimProposal(
        address_id=address_id,
        predicate=predicate,
        value=ClaimValue(kind=ClaimValueKind.TEXT, text=text),
        evidence_ids=(evidence_id,),
        authority=authority,
    )
    return _judgment(judgment_id, request, proposal, evidence_id)


def _supersede(
    judgment_id: str, request: ReasoningRequest, target: str, evidence_id: str, reason: str
) -> SemanticJudgment:
    known_targets = {claim.created_by_judgment_id for claim in request.known_claims}
    assert target in known_targets, f"SUPERSEDE target {target} is not a known claim's judgment"
    proposal = SupersedeProposal(target_judgment_id=target, reason=reason)
    return _judgment(judgment_id, request, proposal, evidence_id)


# --- Arm F script: the ideal story in eight calls ---------------------------------------------


def _f_t1_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    assert request.known_addresses == (), "T1 Call 1 must see no known addresses"
    return [
        _create(J_CREATE_A, request, EV_SPEC_V1, "admitted binding", "referential status"),
        _create(J_CREATE_B, request, EV_SPEC_V1, "admission validation", "framing"),
        _create(J_CREATE_N, request, EV_CONSTITUTION, "law of descent", "direction of decision"),
    ]


def _f_t1_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    assert request.known_claims == (), "T1 Call 2 must see no known claims"
    return [
        _claim(
            J_CLAIM_A,
            request,
            ADDR_A,
            EV_SPEC_V1,
            "referential_status",
            "provisional until a second lens confirms",
        ),
        _claim(J_CLAIM_B, request, ADDR_B, EV_SPEC_V1, "validation_framing", "binary gate"),
        _claim(
            J_CLAIM_N,
            request,
            ADDR_N,
            EV_CONSTITUTION,
            "decision_flow",
            "downward only; lower layers execute or invalidate",
        ),
    ]


def _f_t2_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _bind(J_BIND_A, request, ADDR_A, EV_SPEC_V2, "admitted binding", "referential status"),
        _bind(J_BIND_B, request, ADDR_B, EV_SPEC_V2, "admission validation", "framing"),
    ]


def _f_t2_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _claim(
            J_CLAIM_A_NEW,
            request,
            ADDR_A,
            EV_SPEC_V2,
            "referential_status",
            "durable and referential once APPLY is routed",
        ),
        _supersede(
            J_SUPERSEDE_A, request, J_CLAIM_A, EV_SPEC_V2, "Spec v2 corrects the admission model."
        ),
        _claim(
            J_CLAIM_B_NEW,
            request,
            ADDR_B,
            EV_SPEC_V2,
            "validation_framing",
            "routing decision over a recorded proposal; four routes",
        ),
        _supersede(
            J_SUPERSEDE_B, request, J_CLAIM_B, EV_SPEC_V2, "Spec v2 corrects the validation model."
        ),
    ]


def _f_t3_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _create(J_CREATE_C, request, EV_REDUCER_V1, "reducer provenance", "source event identity"),
    ]


def _f_t3_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _claim(
            J_CLAIM_C,
            request,
            ADDR_C,
            EV_REDUCER_V1,
            "source_event_ids",
            "empty: two applications of one judgment are indistinguishable",
            authority=Authority.INFERRED,
        ),
    ]


def _f_t4_call_1(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _bind(
            J_BIND_C, request, ADDR_C, EV_REDUCER_V2, "reducer provenance", "source event identity"
        ),
    ]


def _f_t4_call_2(request: ReasoningRequest) -> list[SemanticJudgment]:
    return [
        _claim(
            J_CLAIM_C_NEW,
            request,
            ADDR_C,
            EV_REDUCER_V2,
            "source_event_ids",
            "carries the applying event id; applications are distinguishable",
        ),
        _supersede(
            J_SUPERSEDE_C,
            request,
            J_CLAIM_C,
            EV_REDUCER_V2,
            "Reducer v2 fixes the provenance identity defect.",
        ),
    ]


def _f_script() -> list[Batch]:
    return [
        _f_t1_call_1,
        _f_t1_call_2,
        _f_t2_call_1,
        _f_t2_call_2,
        _f_t3_call_1,
        _f_t3_call_2,
        _f_t4_call_1,
        _f_t4_call_2,
    ]


# --- Arm R script: create everything, assert everything, at every T -------------------------


def _r_create(t: int) -> Batch:
    def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
        assert request.known_addresses == (), f"R T{t} Call 1 must see no known addresses"
        assert request.project_id == project_id_for(t)
        return [
            _create(
                f"J-R-T{t}-create-{item.evidence_id}",
                request,
                item.evidence_id,
                f"locus from {item.evidence_id}",
                "rediscovered",
            )
            for item in request.evidence
        ]

    return batch


def _r_assert(t: int) -> Batch:
    def batch(request: ReasoningRequest) -> list[SemanticJudgment]:
        assert request.known_claims == (), f"R T{t} Call 2 must see no known claims"
        return [
            _claim(
                f"J-R-T{t}-assert-{item.evidence_id}",
                request,
                address_id_for(project_id_for(t), f"J-R-T{t}-create-{item.evidence_id}"),
                item.evidence_id,
                "observed_state",
                f"as read from {item.evidence_id} at T{t}",
            )
            for item in request.evidence
        ]

    return batch


def _r_script() -> list[Batch]:
    batches: list[Batch] = []
    for t in (1, 2, 3, 4):
        batches.extend((_r_create(t), _r_assert(t)))
    return batches


# --- running the arms directly ----------------------------------------------------------------


def _select(address_id: str) -> Callable[[IntentState], str]:
    def select(state: IntentState) -> str:
        assert address_id in state.semantic.addresses, f"{address_id} not in state"
        return address_id

    return select


class DirectRun:
    """Both arms, the metrics and the deterministic verdicts of one scenario."""

    def __init__(self, answers: list[AuthorizationDecision]) -> None:
        self.timeline = _timeline()
        self.f_reasoner = ScriptedReasoner(_f_script())
        self.r_reasoner = ScriptedReasoner(_r_script())
        self.authorizer = ScriptedAuthorizer(answers)
        self.f: ArmFResult = run_arm_f(
            reasoner=self.f_reasoner,
            timeline=self.timeline,
            policy=AdmissionPolicy(),
            clock=_clock(),
            id_factory=_id_factory(),
            authorizer=self.authorizer,
            designate_track_a=_select(ADDR_A),
            designate_track_b=_select(ADDR_B),
            designate_track_c=_select(ADDR_C),
            designate_control=_select(ADDR_N),
            scope=SCOPE,
            scopes=SCOPES,
        )
        self.r: tuple[ArmRStep, ...] = run_arm_r(
            reasoner=self.r_reasoner,
            timeline=self.timeline,
            policy=AdmissionPolicy(),
            clock=_clock(),
            id_factory=_id_factory(),
            scope=SCOPE,
        )
        self.metrics: StructuralMetrics = structural_metrics(self.f, self.r, ScoringManifest())
        self.verdicts: tuple[ExpectationVerdict, ...] = deterministic_verdicts(self.metrics)
        self.verdict_by_id = {v.id: v for v in self.verdicts}

    def step(self, t: int) -> StepRecord:
        return self.f.steps[t - 1]

    def state_before_sequence(self, sequence: int) -> IntentState:
        return replay(PROJECT_ID, self.f.ledger[: sequence - 1])


@pytest.fixture(scope="module")
def agreed() -> DirectRun:
    return DirectRun([AuthorizationDecision.AGREE] * 3)


@pytest.fixture(scope="module")
def declined_c() -> DirectRun:
    return DirectRun(
        [AuthorizationDecision.AGREE, AuthorizationDecision.AGREE, AuthorizationDecision.DECLINE]
    )


# --- ledger readers ------------------------------------------------------------------------------


def _events_of(ledger: tuple[StoredEvent, ...], event_type: EventType) -> list[StoredEvent]:
    return [stored for stored in ledger if stored.event.event_type is event_type]


def _judgments_in(ledger: tuple[StoredEvent, ...]) -> list[SemanticJudgment]:
    return [
        stored.event.payload.judgment  # type: ignore[union-attr]
        for stored in _events_of(ledger, EventType.SEMANTIC_JUDGMENT_RECORDED)
    ]


def _ingested_ids(ledger: tuple[StoredEvent, ...]) -> list[str]:
    return [
        stored.event.payload.evidence.evidence_id  # type: ignore[union-attr]
        for stored in _events_of(ledger, EventType.EVIDENCE_INGESTED)
    ]


def _address_ids(view: CurrentSemanticView) -> frozenset[str]:
    return frozenset(address_id for locus in view.loci for address_id in locus.address_ids)


def _locus_claims(view: CurrentSemanticView, address_id: str) -> tuple[str, ...]:
    return next(locus.claim_ids for locus in view.loci if address_id in locus.address_ids)


def _human_judgment_sequences(ledger: tuple[StoredEvent, ...]) -> list[int]:
    return [
        stored.sequence
        for stored in _events_of(ledger, EventType.SEMANTIC_JUDGMENT_RECORDED)
        if stored.event.payload.judgment.reasoner.is_human  # type: ignore[union-attr]
    ]


def _replay_through_fresh_store(ledger: tuple[StoredEvent, ...], project_id: str) -> IntentState:
    fresh = InMemoryEventStore()
    for stored in ledger:
        document = json.loads(json.dumps(stored.event.model_dump(mode="json")))
        fresh.append(parse_event(document), expected_sequence=fresh.current_sequence(project_id))
    return replay(project_id, fresh.load(project_id))


# =============================================================================================
# Scenario 1 — the ideal story, every supersession agreed
# =============================================================================================


def test_both_arms_complete_within_the_locked_call_budget(agreed: DirectRun) -> None:
    assert ADAPTER_CONSTRUCTIONS == []
    assert [s.status for s in agreed.f.steps] == ["COMPLETED"] * 4
    assert [s.error for s in agreed.f.steps] == [None] * 4
    assert [s.status for s in agreed.r] == ["COMPLETED"] * 4
    assert [s.error for s in agreed.r] == [None] * 4

    counts = agreed.metrics.call_counts
    assert agreed.f.calls_made == len(agreed.f_reasoner.requests) == MAX_F_CALLS == 8
    assert len(agreed.r_reasoner.requests) == MAX_R_CALLS == 8
    assert counts.f_per_t == {1: 2, 2: 2, 3: 2, 4: 2}
    assert counts.r_per_t == {1: 2, 2: 2, 3: 2, 4: 2}
    assert counts.f_total == 8 and counts.r_total == 8
    assert counts.total == 16 <= LOCKED_CEILINGS["max_frontier_calls"]

    # Bind-first, two calls per delta, identical allowed kinds in both arms (spec §28).
    for reasoner in (agreed.f_reasoner, agreed.r_reasoner):
        for index, request in enumerate(reasoner.requests):
            expected = (
                ASSIMILATION_JUDGMENT_KINDS if index % 2 == 0 else CLAIM_ASSIMILATION_JUDGMENT_KINDS
            )
            assert request.allowed_judgment_kinds == expected

    # Three authorizations, one per tracked correction, all AGREE (spec §17).
    presented = [j.judgment_id for j in agreed.authorizer.presented]
    assert sorted(presented) == sorted([J_SUPERSEDE_A, J_SUPERSEDE_B, J_SUPERSEDE_C])
    assert len(presented) == LOCKED_CEILINGS["max_human_authorizations"] == 3
    records = [record for step in agreed.f.steps for record in step.authorizations]
    assert [(r.track, r.decision) for r in records] == [
        ("A", AuthorizationDecision.AGREE),
        ("B", AuthorizationDecision.AGREE),
        ("C", AuthorizationDecision.AGREE),
    ]
    assert all(r.not_offered is None and r.submitted_judgment_id is not None for r in records)
    assert [r.pending_judgment_id for r in agreed.step(2).authorizations] == [
        J_SUPERSEDE_A,
        J_SUPERSEDE_B,
    ]
    assert [r.pending_judgment_id for r in agreed.step(4).authorizations] == [J_SUPERSEDE_C]
    assert agreed.step(3).authorizations == ()
    budget = AuthorizationBudget()
    assert budget.per_track == 1 and budget.total == 3

    economics = agreed.metrics.economics
    assert economics.within_ceiling
    assert economics.total_cost_usd < LOCKED_CEILINGS["max_cost_usd"]
    assert economics.f.input_tokens_after_t1 < economics.r.input_tokens_after_t1


def test_persistent_ledger_counts_and_judgment_order(agreed: DirectRun) -> None:
    ledger = agreed.f.ledger
    assert len(ledger) == agreed.f.final_state_revision == F_LEDGER_LENGTH_ALL_AGREED
    assert [stored.sequence for stored in ledger] == list(range(1, len(ledger) + 1))
    assert {stored.event.project_id for stored in ledger} == {PROJECT_ID}

    # T0: the architect's project-wide authority is the first event; no call was made.
    first: Any = ledger[0].event.payload
    assert ledger[0].event.event_type is EventType.SEMANTIC_OBJECT_RECORDED
    assert first.object.authorized_by == ARCHITECT_ACTOR and first.object.scope == ()

    assert _ingested_ids(ledger) == list(ALL_EVIDENCE_IDS)
    assert len(_events_of(ledger, EventType.DERIVATION_RECORDED)) == 5
    judgments = _judgments_in(ledger)
    assert len(judgments) == len(_events_of(ledger, EventType.SEMANTIC_ADMISSION_DECIDED)) == 20
    ai_ids = [j.judgment_id for j in judgments if not j.reasoner.is_human]
    assert ai_ids == [j for t in (1, 2, 3, 4) for j in F_JUDGMENTS_BY_T[t]]
    human = [j for j in judgments if j.reasoner.is_human]
    assert [j.proposal.target_judgment_id for j in human] == [  # type: ignore[union-attr]
        J_CLAIM_A,
        J_CLAIM_B,
        J_CLAIM_C,
    ]
    assert all(j.reasoner.model == ARCHITECT_ACTOR for j in human)

    # Per-step accounting: the AI judgments plus the human AGREEs of each T.
    assert agreed.step(1).judgment_ids == F_JUDGMENTS_BY_T[1]
    assert agreed.step(2).judgment_ids[:6] == F_JUDGMENTS_BY_T[2]
    assert len(agreed.step(2).judgment_ids) == 8
    assert agreed.step(3).judgment_ids == F_JUDGMENTS_BY_T[3]
    assert agreed.step(4).judgment_ids[:3] == F_JUDGMENTS_BY_T[4]
    assert len(agreed.step(4).judgment_ids) == 4
    revisions = [s.state_snapshot_revision for s in agreed.f.steps]
    assert revisions == [20, 37, 43, 53]

    # Every AI SUPERSEDE was held (material: a single lens is never enough); every human
    # AGREE applied under authority. Nothing material was auto-applied.
    admissions = {d.judgment_id: d for step in agreed.f.steps for d in step.admissions}
    for supersede in (J_SUPERSEDE_A, J_SUPERSEDE_B, J_SUPERSEDE_C):
        assert admissions[supersede].route is AdmissionRoute.REQUIRE_SECOND_LENS
        assert "MATERIAL_REQUIRES_SECOND_LENS" in admissions[supersede].reasons
    for j in human:
        assert admissions[j.judgment_id].route is AdmissionRoute.APPLY
        assert "HUMAN_AUTHORITY" in admissions[j.judgment_id].reasons
    for kind in (JudgmentKind.EQUIVALENT, JudgmentKind.DISTINCT, JudgmentKind.CONFLICTS_WITH):
        assert not any(j.kind is kind for j in judgments)

    # Arm R: a fresh ledger per T, 5 events per corpus item, its own project id.
    for step in agreed.r:
        n = R_CORPUS_SIZE_BY_T[step.t]
        assert len(step.ledger) == 5 * n
        assert {stored.event.project_id for stored in step.ledger} == {project_id_for(step.t)}
        assert len(step.judgment_ids) == 2 * n
        assert all(d.route is AdmissionRoute.APPLY for d in step.admissions)


def test_f_receives_delta_only_and_r_receives_the_cumulative_corpus(agreed: DirectRun) -> None:
    timeline = agreed.timeline
    seen: set[tuple[str | None, str]] = set()
    for t in (1, 2, 3, 4):
        call_1, call_2 = agreed.f_reasoner.requests[2 * (t - 1) : 2 * t]
        delta = persistent_delta(timeline, t)
        assert tuple(i.evidence_id for i in delta) == DELTA_IDS_BY_T[t]
        assert tuple(i.evidence_id for i in call_1.evidence) == DELTA_IDS_BY_T[t]
        assert tuple(i.evidence_id for i in call_2.evidence[: len(delta)]) == DELTA_IDS_BY_T[t]
        for item in call_1.evidence:
            assert (item.artifact_ref, item.content_sha256) not in seen
            seen.add((item.artifact_ref, item.content_sha256))
        assert agreed.step(t).evidence_shown[: len(delta)] == DELTA_IDS_BY_T[t]
        # Lineage travels as data: every non-first version names its predecessor.
        for item in call_1.evidence:
            if item.evidence_id in (EV_SPEC_V2, EV_REDUCER_V2, EV_SPEC_V3):
                assert item.supersedes_evidence_id is not None
    # The constitution is sent at T1 and never again (spec §25).
    for t in (2, 3, 4):
        assert EV_CONSTITUTION not in agreed.step(t).evidence_shown
    assert agreed.metrics.persistent_unchanged_reread_count == 0
    # Call 2 at T2 carries the evidence the live claims at A/B cite (bounded context, §19).
    assert agreed.step(2).evidence_shown == (EV_SPEC_V2, EV_SPEC_V1)
    assert agreed.metrics.neighborhood_evidence_resent_count == 2  # T2 spec v1, T4 reducer v1
    assert set(agreed.step(2).claims_shown) == {CLAIM_A, CLAIM_B}
    assert agreed.step(4).claims_shown == (CLAIM_C,)
    # Call 1 at T>1 shows only the in-scope descriptors: the constitution locus is not shown.
    assert set(agreed.step(2).addresses_shown) == {ADDR_A, ADDR_B}
    assert ADDR_N not in agreed.step(4).addresses_shown

    # Arm R: every version <= T, in timeline order, and the T4 corpus is all seven.
    for step in agreed.r:
        corpus = reconstruction_corpus(timeline, step.t)
        expected = tuple(ev for t in range(1, step.t + 1) for ev in DELTA_IDS_BY_T[t])
        assert tuple(i.evidence_id for i in corpus) == expected
        assert step.evidence_shown == expected
        assert _ingested_ids(step.ledger) == list(expected)
        call_1 = agreed.r_reasoner.requests[2 * (step.t - 1)]
        assert tuple(i.evidence_id for i in call_1.evidence) == expected
    assert agreed.r[-1].evidence_shown == ALL_EVIDENCE_IDS
    assert len(agreed.r[-1].evidence_shown) == 7
    assert agreed.metrics.r_rediscovery_counts == R_CORPUS_SIZE_BY_T


def test_e1_to_e5_deterministic_parts(agreed: DirectRun) -> None:
    # E1: A and B exist after T1; C does not yet exist (nor after T2).
    t1_addresses = _address_ids(agreed.step(1).view)
    assert {ADDR_A, ADDR_B, ADDR_N} <= t1_addresses
    assert ADDR_C not in t1_addresses
    assert ADDR_C not in _address_ids(agreed.step(2).view)
    assert [d.track for d in agreed.f.designations] == ["A", "B", "CONTROL", "C"]
    assert [d.address_id for d in agreed.f.designations] == [ADDR_A, ADDR_B, ADDR_N, ADDR_C]
    assert [d.judgment_id for d in agreed.f.designations] == [
        J_CLAIM_A,
        J_CLAIM_B,
        J_CLAIM_N,
        J_CLAIM_C,
    ]

    # E2: at T2 the observations were BOUND to the T1 addresses; no address was created.
    t2_judgments = [
        j for j in _judgments_in(agreed.f.ledger) if j.judgment_id in F_JUDGMENTS_BY_T[2]
    ]
    binds = [j.proposal for j in t2_judgments if isinstance(j.proposal, BindToAddressProposal)]
    assert sorted(b.address_id for b in binds) == sorted([ADDR_A, ADDR_B])
    assert not any(isinstance(j.proposal, CreateAddressProposal) for j in t2_judgments)
    assert _address_ids(agreed.step(2).view) == t1_addresses
    view_t2 = agreed.step(2).view
    assert view_t2.active_bindings[f"CAND-{J_BIND_A}"] == ADDR_A
    assert view_t2.active_bindings[f"CAND-{J_BIND_B}"] == ADDR_B

    # E3: a new claim at A (and at B) exists after T2, citing the T2 spec.
    final = replay(PROJECT_ID, agreed.f.ledger)
    for claim_id, address_id in ((CLAIM_A_NEW, ADDR_A), (CLAIM_B_NEW, ADDR_B)):
        claim = final.semantic.claims[claim_id]
        assert claim.address_id == address_id
        assert claim.evidence_ids == (EV_SPEC_V2,)

    # E4: the T1 claims at A and B remain present in state after T2 (and at the end).
    for claim_id in (CLAIM_A, CLAIM_B, CLAIM_N):
        assert claim_id in agreed.state_before_sequence(38).semantic.claims
        assert claim_id in final.semantic.claims
    preservation = agreed.metrics.historical_claims_preserved
    assert preservation.holds and preservation.missing_claim_ids == ()
    assert set(preservation.t1_claim_ids) == {CLAIM_A, CLAIM_B, CLAIM_N}

    # E5: the current view at A (and B) changed ONLY after the authorized supersession.
    # Before the first human judgment the AI SUPERSEDE was held, and both claims were live.
    human_sequences = _human_judgment_sequences(agreed.f.ledger)
    assert len(human_sequences) == 3
    before_agree = derive_view(agreed.state_before_sequence(human_sequences[0]).semantic)
    assert set(_locus_claims(before_agree, ADDR_A)) == {CLAIM_A, CLAIM_A_NEW}
    assert set(_locus_claims(before_agree, ADDR_B)) == {CLAIM_B, CLAIM_B_NEW}
    assert J_SUPERSEDE_A in before_agree.pending_judgment_ids
    assert J_SUPERSEDE_B in before_agree.pending_judgment_ids
    assert before_agree.stale_ids == ()
    after_t2 = agreed.step(2).view
    assert _locus_claims(after_t2, ADDR_A) == (CLAIM_A_NEW,)
    assert _locus_claims(after_t2, ADDR_B) == (CLAIM_B_NEW,)
    assert _locus_claims(after_t2, ADDR_N) == (CLAIM_N,)
    assert after_t2.pending_judgment_ids == ()
    assert set(after_t2.satisfied_by) == {J_SUPERSEDE_A, J_SUPERSEDE_B}
    chain = agreed.metrics.supersession_chain_valid
    assert chain.holds and chain.record_count == 3
    assert [target for target, _ in chain.records] == [J_CLAIM_A, J_CLAIM_B, J_CLAIM_C]


def test_e6_and_e7_blast_radius_and_scope_isolation(agreed: DirectRun) -> None:
    stale = agreed.metrics.stale_descendants_correct
    assert stale.a_root_judgment_id == J_CLAIM_A
    assert stale.a_root_superseded and stale.superseded_at_t == 2
    assert set(TRACK_A_CHAIN) <= set(stale.stale_ids)
    assert set(CONTROL_CHAIN).isdisjoint(stale.stale_ids)
    assert stale.holds is True
    assert set(TRACK_A_CHAIN) <= set(agreed.step(2).view.stale_ids)
    assert agreed.step(1).view.stale_ids == ()
    assert agreed.verdict_by_id["E6"].verdict is Verdict.PASS

    isolation = agreed.metrics.scope_isolation
    assert isolation.evaluated_at_t == 2
    assert set(TRACK_A_CHAIN) <= set(isolation.affected_stale_object_ids)
    assert isolation.unaffected_stale_object_ids == ()
    assert isolation.unaffected_pending_material_judgment_ids == ()
    assert isolation.holds is True
    assert agreed.verdict_by_id["E7"].verdict is Verdict.PASS
    for t in (2, 3, 4):
        readiness = agreed.step(t).readiness_by_scope
        assert set(readiness) == set(SCOPES)
        engine, constitution = readiness["intent-engine"], readiness["constitution"]
        assert set(TRACK_A_CHAIN) <= set(engine.stale_object_ids)
        assert not engine.semantic_blockers_clear and not engine.ready
        assert constitution.stale_object_ids == ()
        assert constitution.pending_material_judgment_ids == ()
        assert constitution.semantic_blockers_clear
    assert agreed.step(1).readiness_by_scope["intent-engine"].semantic_blockers_clear


def test_e8_and_e9_deterministic_parts(agreed: DirectRun) -> None:
    # E8: C exists after T3 with an INFERRED claim; it did not exist at the end of T2.
    assert ADDR_C in _address_ids(agreed.step(3).view)
    final = replay(PROJECT_ID, agreed.f.ledger)
    defect = final.semantic.claims[CLAIM_C]
    assert defect.address_id == ADDR_C and defect.authority is Authority.INFERRED
    assert defect.evidence_ids == (EV_REDUCER_V1,)
    assert _locus_claims(agreed.step(3).view, ADDR_C) == (CLAIM_C,)
    assert agreed.f.designations[3].track == "C"
    assert agreed.f.designations[3].ledger_sequence_at_designation == 43

    # E9: at T4 the corrected observation BINDS to C; a new claim and a SUPERSEDE of the
    # T3 judgment were proposed and held, not silently applied.
    t4 = [j for j in _judgments_in(agreed.f.ledger) if j.judgment_id in F_JUDGMENTS_BY_T[4]]
    bind = next(j.proposal for j in t4 if isinstance(j.proposal, BindToAddressProposal))
    assert bind.address_id == ADDR_C
    supersede = next(j.proposal for j in t4 if isinstance(j.proposal, SupersedeProposal))
    assert supersede.target_judgment_id == J_CLAIM_C
    human_sequences = _human_judgment_sequences(agreed.f.ledger)
    before_agree = derive_view(agreed.state_before_sequence(human_sequences[2]).semantic)
    assert set(_locus_claims(before_agree, ADDR_C)) == {CLAIM_C, CLAIM_C_NEW}
    assert before_agree.pending_judgment_ids == (J_SUPERSEDE_C,)
    assert _locus_claims(agreed.step(4).view, ADDR_C) == (CLAIM_C_NEW,)
    assert ADDR_C not in _address_ids(agreed.step(2).view)
    assert _address_ids(agreed.step(4).view) == _address_ids(agreed.step(3).view)


def test_e10_e11_e12_deterministic_verdicts(agreed: DirectRun) -> None:
    kinds = agreed.metrics.e10_no_equivalence_requested
    assert kinds.holds and kinds.forbidden_requests == ()
    assert kinds.f_requests == 8 and kinds.r_requests == 8
    for step in (*agreed.f.steps, *agreed.r):
        for allowed in step.allowed_kinds_per_call:
            assert "EQUIVALENT" not in allowed and "DISTINCT" not in allowed
    assert agreed.verdict_by_id["E10"].verdict is Verdict.PASS

    replay_check = agreed.metrics.e11_replay
    assert replay_check.holds
    assert replay_check.replay.status == "REPLAY_MATCH"
    assert replay_check.mismatched_steps == () and replay_check.final_revision_matches
    assert agreed.verdict_by_id["E11"].verdict is Verdict.PASS
    # Replay both arms independently through a fresh store (the 9O path).
    final = replay(PROJECT_ID, agreed.f.ledger)
    assert replay_matches(agreed.f.ledger, final).status == "REPLAY_MATCH"
    assert _replay_through_fresh_store(agreed.f.ledger, PROJECT_ID) == final
    for step in agreed.r:
        live = replay(project_id_for(step.t), step.ledger)
        assert derive_view(live.semantic) == step.view
        result = replay_matches(step.ledger, live)
        assert result.status == "REPLAY_MATCH" and result.event_count == len(step.ledger)
    support = agreed.metrics.support_records_replay
    assert support.holds and support.record_count == 0

    governance = agreed.metrics.e12
    assert not governance.declined_any and governance.holds is None
    assert governance.declined_judgment_ids == ()
    assert governance.conflicts_without_reasoner_proposal == ()
    e12 = agreed.verdict_by_id["E12"]
    assert e12.verdict is Verdict.NOT_APPLICABLE and e12.adjudicator == "deterministic"

    pending = agreed.metrics.pending_governance
    assert pending.pending_judgment_ids == ()
    assert set(pending.satisfied_judgment_ids) == {J_SUPERSEDE_A, J_SUPERSEDE_B, J_SUPERSEDE_C}
    assert pending.require_second_lens_count == 3
    assert pending.require_human_count == 0 and pending.rejected_count == 0

    assert [v.id for v in agreed.verdicts] == ["E6", "E7", "E10", "E11", "E12"]
    assert all(v.adjudicator == "deterministic" for v in agreed.verdicts)


def test_decision_rule_passes_with_architect_verdicts_supplied(agreed: DirectRun) -> None:
    architect_ids = [e.id for e in EXPECTATIONS if e.adjudicator == "architect"]
    assert architect_ids == ["E1", "E2", "E3", "E4", "E5", "E8", "E9"]
    architect = tuple(
        ExpectationVerdict(
            id=expectation_id,
            verdict=Verdict.PASS,
            adjudicator="architect",
            evidence_refs=("test:supplied",),
            note="supplied by the integration test as PASS",
        )
        for expectation_id in architect_ids
    )
    # E10 is one id with two halves: the deterministic half is the recorded verdict; the
    # architect half (duplicate-address count for tracked loci is 0) is supplied here.
    e10 = agreed.verdict_by_id["E10"].model_copy(
        update={"note": agreed.verdict_by_id["E10"].note + " Architect half supplied: PASS."}
    )
    deterministic = tuple(e10 if v.id == "E10" else v for v in agreed.verdicts)
    economics = agreed.metrics.economics
    inputs = DecisionInputs(
        verdicts=(*architect, *deterministic),
        f_input_tokens_t2_t4=economics.f.input_tokens_after_t1,
        r_input_tokens_t2_t4=economics.r.input_tokens_after_t1,
        f_material_errors=0,
        r_material_errors=0,
        declined_any=agreed.metrics.e12.declined_any,
    )
    outcome = decision_rule(inputs)
    assert outcome.result == "PASS", outcome.failing
    assert outcome.failing == ()


# =============================================================================================
# Scenario 2 — the Track C supersession is declined
# =============================================================================================


def test_declined_track_c_leaves_governance_pending_and_e12_applies(declined_c: DirectRun) -> None:
    run = declined_c
    assert [s.status for s in run.f.steps] == ["COMPLETED"] * 4
    assert [s.status for s in run.r] == ["COMPLETED"] * 4
    assert run.f.calls_made == 8 and run.metrics.call_counts.total == 16
    assert len(run.f.ledger) == F_LEDGER_LENGTH_C_DECLINED
    assert len(_human_judgment_sequences(run.f.ledger)) == 2

    records = [record for step in run.f.steps for record in step.authorizations]
    assert [(r.track, r.decision) for r in records] == [
        ("A", AuthorizationDecision.AGREE),
        ("B", AuthorizationDecision.AGREE),
        ("C", AuthorizationDecision.DECLINE),
    ]
    (c_record,) = run.step(4).authorizations
    assert c_record.pending_judgment_id == J_SUPERSEDE_C
    assert c_record.submitted_judgment_id is None and c_record.not_offered is None
    assert len(run.authorizer.presented) == 3

    # A declined supersession leaves both claims live, the proposal pending, no conflict.
    t4 = run.step(4).view
    assert set(_locus_claims(t4, ADDR_C)) == {CLAIM_C, CLAIM_C_NEW}
    assert t4.pending_judgment_ids == (J_SUPERSEDE_C,)
    assert J_SUPERSEDE_C not in t4.satisfied_by
    assert t4.active_conflict_judgment_ids == ()
    assert not any(j.kind is JudgmentKind.CONFLICTS_WITH for j in _judgments_in(run.f.ledger))
    assert [target for target, _ in run.metrics.supersession_chain_valid.records] == [
        J_CLAIM_A,
        J_CLAIM_B,
    ]

    # The affected scope is not ready and names the pending id; the constitution is clear.
    engine = run.step(4).readiness_by_scope["intent-engine"]
    constitution = run.step(4).readiness_by_scope["constitution"]
    assert J_SUPERSEDE_C in engine.pending_material_judgment_ids
    assert not engine.semantic_blockers_clear and not engine.ready
    assert constitution.pending_material_judgment_ids == ()
    assert constitution.stale_object_ids == ()
    assert constitution.semantic_blockers_clear

    governance = run.metrics.e12
    assert governance.declined_any and governance.holds is True
    assert governance.declined_judgment_ids == (J_SUPERSEDE_C,)
    assert governance.readiness_missing == ()
    assert governance.conflicts_without_reasoner_proposal == ()
    e12 = run.verdict_by_id["E12"]
    assert e12.verdict is Verdict.PASS and J_SUPERSEDE_C in e12.evidence_refs
    # E6/E7 (Track A, agreed at T2) and E10/E11 are unaffected by the decline at C.
    assert run.verdict_by_id["E6"].verdict is Verdict.PASS
    assert run.verdict_by_id["E7"].verdict is Verdict.PASS
    assert run.verdict_by_id["E10"].verdict is Verdict.PASS
    assert run.verdict_by_id["E11"].verdict is Verdict.PASS
    pending = run.metrics.pending_governance
    assert pending.pending_judgment_ids == (J_SUPERSEDE_C,)
    assert set(pending.satisfied_judgment_ids) == {J_SUPERSEDE_A, J_SUPERSEDE_B}
    assert run.metrics.historical_claims_preserved.holds
    assert run.metrics.persistent_unchanged_reread_count == 0

    # A NOT_APPLICABLE E12 is refused once a decline happened; the recorded PASS is accepted.
    with pytest.raises(ValueError, match="declined"):
        DecisionInputs(
            verdicts=(
                ExpectationVerdict(
                    id="E12",
                    verdict=Verdict.NOT_APPLICABLE,
                    adjudicator="deterministic",
                    evidence_refs=("x",),
                ),
            ),
            f_input_tokens_t2_t4=1,
            r_input_tokens_t2_t4=2,
            f_material_errors=0,
            r_material_errors=0,
            declined_any=True,
        )
    architect = tuple(
        ExpectationVerdict(
            id=e.id, verdict=Verdict.PASS, adjudicator="architect", evidence_refs=("test:supplied",)
        )
        for e in EXPECTATIONS
        if e.adjudicator == "architect"
    )
    outcome = decision_rule(
        DecisionInputs(
            verdicts=(*architect, *run.verdicts),
            f_input_tokens_t2_t4=run.metrics.economics.f.input_tokens_after_t1,
            r_input_tokens_t2_t4=run.metrics.economics.r.input_tokens_after_t1,
            f_material_errors=0,
            r_material_errors=0,
            declined_any=True,
        )
    )
    assert outcome.result == "PASS", outcome.failing


# =============================================================================================
# The entry point: seal, then run with scripted stdin
# =============================================================================================


def _main(
    out: Path,
    *,
    stdin: str = "",
    reasoner: ScriptedReasoner | None = None,
    seal_mode: bool = False,
) -> tuple[int, str]:
    stdout = io.StringIO()

    def factory(api_key: str, config: Any) -> ScriptedReasoner:
        assert api_key == FAKE_KEY
        assert config.model == "grok-4.6" and config.reasoning_effort == "high"
        assert reasoner is not None, "the reasoner factory must not be called in seal mode"
        return reasoner

    argv = ["--frozen-sha", FROZEN_SHA, "--out", str(out), "--repo-root", "/nowhere"]
    if seal_mode:
        argv.append("--seal")
    code = script.main(
        argv,
        stdin=io.StringIO(stdin),
        stdout=stdout,
        reasoner_factory=factory,
        git_factory=lambda _root: FakeGit(_blobs()),
    )
    return code, stdout.getvalue()


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sealed_via_script(tmp_path: Path) -> Path:
    out = tmp_path / EXPERIMENT_DIR_NAME
    code, text = _main(out, seal_mode=True)
    assert code == 0, text
    assert _files(out) == set(PRE_RUN_FILES)
    manifest = _load(out / "manifest.json")
    document = _load(out / "expectations.json")
    assert document["t1_locus_designation"] is None
    assert seal(ExpectationManifest.model_validate(document)) == manifest["expectations_sha256"]
    assert manifest["frozen_code_sha"] == FROZEN_SHA
    assert len(manifest["timeline_hashes"]) == 7
    return out


def _stdin(final_answer: str) -> str:
    # T1 selections (A, B, CONTROL); T2 authorizations (A, B); T3 selection (C); T4 (C).
    return "\n".join([ADDR_A, ADDR_B, ADDR_N, "AGREE", "AGREE", ADDR_C, final_answer, ""])


def test_script_runs_the_agreed_lifecycle_and_writes_every_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_via_script(tmp_path)
    reasoner = ScriptedReasoner([*_f_script(), *_r_script()])

    code, text = _main(out, stdin=_stdin("AGREE"), reasoner=reasoner)

    assert code == 0, text
    assert ADAPTER_CONSTRUCTIONS == []
    assert FAKE_KEY not in text and "xai-" not in text
    assert len(reasoner.requests) == 16
    assert "run_status: COMPLETED" in text
    assert all(
        f"gate {name}: PASS" in text
        for name in ("head_equals_frozen_sha", "no_tracked_locus_leakage")
    )
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)
    for name in POST_RUN_FILES:
        assert (out / name).exists(), name
        assert "xai-" not in (out / name).read_text(encoding="utf-8"), name

    persistent = _load(out / "persistent/result.json")
    assert persistent["run_status"] == "COMPLETED"
    assert [s["status"] for s in persistent["result"]["steps"]] == ["COMPLETED"] * 4
    assert persistent["result"]["calls_made"] == 8
    assert [d["track"] for d in persistent["result"]["designations"]] == ["A", "B", "CONTROL", "C"]
    ledger = _load(out / "persistent/ledger.json")
    assert ledger["project_id"] == PROJECT_ID
    assert ledger["event_count"] == len(ledger["events"]) == F_LEDGER_LENGTH_ALL_AGREED
    for t in (1, 2, 3, 4):
        step = _load(out / f"reconstruction/T{t}-result.json")
        assert step["result"]["status"] == "COMPLETED"
        assert len(step["result"]["evidence_shown"]) == R_CORPUS_SIZE_BY_T[t]
        t_ledger = _load(out / f"reconstruction/T{t}-ledger.json")
        assert t_ledger["project_id"] == project_id_for(t)
        assert t_ledger["event_count"] == 5 * R_CORPUS_SIZE_BY_T[t]

    authorizations = _load(out / "authorizations.json")
    assert authorizations["budget"] == {"per_track": 1, "total": 3}
    assert authorizations["answered"] == 3
    assert [
        (r["t"], r["record"]["track"], r["record"]["decision"]) for r in authorizations["records"]
    ] == [
        (2, "A", "AGREE"),
        (2, "B", "AGREE"),
        (4, "C", "AGREE"),
    ]
    assert [r["proposal"]["proposal"]["target_judgment_id"] for r in authorizations["records"]] == [
        J_CLAIM_A,
        J_CLAIM_B,
        J_CLAIM_C,
    ]

    verdicts = _load(out / "verdicts.json")
    assert verdicts["run_status"] == "COMPLETED" and verdicts["declined_any"] is False
    by_id = {v["id"]: v for v in verdicts["verdicts"]}
    assert [v["id"] for v in verdicts["verdicts"]] == [e.id for e in EXPECTATIONS]
    for expectation_id in ("E1", "E2", "E3", "E4", "E5", "E8", "E9"):
        assert by_id[expectation_id]["verdict"] is None
    for expectation_id in ("E6", "E7", "E10", "E11"):
        assert by_id[expectation_id]["verdict"]["verdict"] == "PASS", expectation_id
    assert by_id["E12"]["verdict"]["verdict"] == "NOT_APPLICABLE"
    assert verdicts["decision"] is None

    # The designation slot was filled live (after T1, before T2) and the seal is unchanged.
    document = _load(out / "expectations.json")
    slot = document["t1_locus_designation"]
    assert [d["track"] for d in slot["designations"]] == ["A", "B", "CONTROL"]
    assert [d["address_id"] for d in slot["designations"]] == [ADDR_A, ADDR_B, ADDR_N]
    first_t2_ingest = min(
        e["sequence"]
        for e in ledger["events"]
        if e["event"]["event_type"] == "EVIDENCE_INGESTED"
        and e["event"]["payload"]["evidence"]["evidence_id"] == EV_SPEC_V2
    )
    assert all(d["ledger_sequence_at_designation"] < first_t2_ingest for d in slot["designations"])
    sealed = _load(out / "manifest.json")["expectations_sha256"]
    assert seal(ExpectationManifest.model_validate(document)) == sealed

    report = (out / "report.md").read_text(encoding="utf-8")
    assert "run_status: **COMPLETED**" in report
    assert "calls: F=8 R=8 total=16" in report
    assert "persistent_unchanged_reread_count: 0" in report
    assert "| E12 | deterministic | NOT_APPLICABLE |" in report
    assert "| E6 | deterministic | PASS |" in report

    # The persisted F ledger replays to the persisted final view.
    events = tuple(StoredEvent.model_validate(e) for e in ledger["events"])
    replayed = replay(PROJECT_ID, events)
    assert replayed.revision == persistent["result"]["final_state_revision"]
    assert derive_view(replayed.semantic) == CurrentSemanticView.model_validate(
        persistent["result"]["steps"][-1]["view"]
    )


def test_script_runs_the_declined_lifecycle_and_still_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    out = _sealed_via_script(tmp_path)
    reasoner = ScriptedReasoner([*_f_script(), *_r_script()])

    code, text = _main(out, stdin=_stdin("DECLINE"), reasoner=reasoner)

    assert code == 0, text
    assert ADAPTER_CONSTRUCTIONS == []
    assert len(reasoner.requests) == 16
    assert "run_status: COMPLETED" in text
    assert _files(out) == set(PRE_RUN_FILES) | set(POST_RUN_FILES)

    authorizations = _load(out / "authorizations.json")
    assert authorizations["answered"] == 3
    assert [(r["record"]["track"], r["record"]["decision"]) for r in authorizations["records"]] == [
        ("A", "AGREE"),
        ("B", "AGREE"),
        ("C", "DECLINE"),
    ]
    assert authorizations["records"][2]["record"]["submitted_judgment_id"] is None
    assert authorizations["records"][2]["proposal"]["judgment_id"] == J_SUPERSEDE_C

    verdicts = _load(out / "verdicts.json")
    assert verdicts["run_status"] == "COMPLETED" and verdicts["declined_any"] is True
    by_id = {v["id"]: v for v in verdicts["verdicts"]}
    assert by_id["E12"]["verdict"]["verdict"] == "PASS"
    assert J_SUPERSEDE_C in by_id["E12"]["verdict"]["evidence_refs"]
    for expectation_id in ("E6", "E7", "E10", "E11"):
        assert by_id[expectation_id]["verdict"]["verdict"] == "PASS", expectation_id

    persistent = _load(out / "persistent/result.json")
    t4 = persistent["result"]["steps"][3]
    assert t4["status"] == "COMPLETED"
    assert t4["view"]["pending_judgment_ids"] == [J_SUPERSEDE_C]
    engine = t4["readiness_by_scope"]["intent-engine"]
    constitution = t4["readiness_by_scope"]["constitution"]
    assert J_SUPERSEDE_C in engine["pending_material_judgment_ids"]
    assert engine["semantic_blockers_clear"] is False
    assert constitution["semantic_blockers_clear"] is True
    assert constitution["pending_material_judgment_ids"] == []
    assert _load(out / "persistent/ledger.json")["event_count"] == F_LEDGER_LENGTH_C_DECLINED
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "| T4 | C | `J-T4-supersede-C` | DECLINE | - | - |" in report
    assert "| E12 | deterministic | PASS |" in report
