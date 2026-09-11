# Intent Intelligence v2 Core — Implementation Plan

**Task:** 9N. **Branch:** `feat/intent-intelligence-v2`.
**Spec:** `docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md` (9N locks, commit `2539ff81`).
**Method:** strict TDD per task (RED → GREEN → REFACTOR), fresh implementer + reviewer per task, commit per task.
**Runtime rule:** zero live model/API calls. All semantic reasoning under test uses deterministic fakes.

The target is the smallest tested substrate proving:

```text
ANY PROJECT EVIDENCE → AI semantic proposal → governance/admission
→ durable semantic address + claims → conflict preservation → supersession
→ blast-radius propagation → scoped current intent state → explicit Intent→Decision handoff
```

## 0. Architectural ground rules the implementer must obey

1. **AI decides meaning; Foundry governs meaning.** No production function may originate a semantic conclusion from string/descriptor/kind/source/confidence equality. Deterministic code only applies *admitted* judgments.
2. **One event-sourced story.** Every durable transition is an `EventEnvelope` reduced by the existing reducer. No second ledger.
3. **Append-only everywhere.** Addresses, claims, judgments, issue versions and derivation edges are immutable once recorded. Supersession is a new record, never an edit.
4. **Confidence is metadata, never authority.** No admission rule reads `confidence`.
5. **Deterministic IDs for replay.** Every ID the reducer mints derives from `(project_id, event_id[, discriminator])` via sha256 so fresh replay reproduces identical state.
6. **Layer boundaries** (AGENTS.md): `domain/` pure models + deterministic rules (no I/O); `application/` orchestration; `ports/` protocols; `adapters/` persistence/provider only.
7. Do not modify `evals/comparative/**`, `src/foundry/evaluation/**`, `src/foundry/intelligence/**`, or `src/foundry/adapters/intelligence/**`.

## 1. Module map

| Path | Kind | Task |
|---|---|---|
| `src/foundry/domain/common.py` | MODIFY — extend `SourceKind` | T1 |
| `src/foundry/domain/evidence.py` | NEW | T1 |
| `src/foundry/adapters/memory/__init__.py`, `event_store.py` | NEW | T1 |
| `src/foundry/domain/semantic_identity.py` | NEW | T2 |
| `src/foundry/domain/semantic_judgment.py` | NEW | T3 |
| `src/foundry/ports/semantic_reasoner.py` | NEW | T3 |
| `src/foundry/adapters/semantics/__init__.py`, `fake_reasoner.py` | NEW | T3 |
| `src/foundry/domain/events.py` | MODIFY — 4 event types + payloads | T4 |
| `src/foundry/domain/semantic_state.py` | NEW | T4 |
| `src/foundry/domain/state.py` | MODIFY — add `semantic: SemanticState` | T4 |
| `src/foundry/application/semantic_reducer.py` | NEW | T4 |
| `src/foundry/application/reducer.py` | MODIFY — delegate 4 event types | T4 |
| `src/foundry/domain/semantic_view.py` | NEW | T4 |
| `src/foundry/domain/admission.py` | NEW | T5 |
| `src/foundry/domain/derivation.py` | NEW | T6 |
| `src/foundry/application/semantic_governance.py` | NEW | T7 |
| `src/foundry/domain/handoff.py` | NEW | T7 |
| `src/foundry/application/handoff.py` | NEW | T7 |

Tests: `tests/unit/test_evidence.py`, `test_memory_event_store.py`, `test_semantic_identity.py`, `test_semantic_judgment.py`, `test_semantic_events.py`, `test_semantic_reducer.py`, `test_semantic_view.py`, `test_admission.py`, `test_derivation.py`, `test_handoff.py`; `tests/integration/test_semantic_lifecycle.py`.

## 2. Task T1 — Evidence contract and in-memory event store

**Commit:** `feat: add evidence ingestion contract and memory event store`

### 2.1 `SourceKind` extension (`domain/common.py`)
Add members `TICKET`, `PULL_REQUEST`, `AGENT_CONVERSATION`. No consumer matches exhaustively (verified). Existing values unchanged.

### 2.2 `domain/evidence.py`
```python
class EvidenceItem(FrozenModel):
    evidence_id: str            # min_length=1
    project_id: str
    scope: tuple[str, ...] = ()  # () = project-wide, same convention as SemanticBase.scope
    source_kind: SourceKind
    source_ref: str             # stable locator: "human://alice", "repo://svc/x.py#L1-L9", "ticket://PROJ-12"
    content: str                # min_length=1
    content_sha256: str         # pattern ^[0-9a-f]{64}$; validator: must equal sha256(content.encode("utf-8"))
    observed_at: datetime

def evidence_item(*, evidence_id, project_id, source_kind, source_ref, content, observed_at, scope=()) -> EvidenceItem
    # computes content_sha256

class DigRecord(FrozenModel):     # thin, provider-neutral shape future dig emits
    locator: str; kind: SourceKind; content: str; scope: tuple[str, ...] = (); observed_at: datetime

def evidence_from_dig(record: DigRecord, *, project_id: str, evidence_id: str) -> EvidenceItem
```
Human typed text is simply `source_kind=HUMAN, source_ref="human://<actor>"`.

### 2.3 `adapters/memory/event_store.py`
`InMemoryEventStore` implementing `ports.event_store.EventStore` exactly like Postgres semantics: per-project sequence, `ConcurrencyError` on wrong `expected_sequence`, `DuplicateEventError` on repeated `event_id`, `load(project_id, after_sequence)` returns `StoredEvent`s in order, `current_sequence`.

### 2.4 Tests (RED first)
`test_evidence.py`: hash computed and validated (tampered hash rejected); HUMAN, CODE, TEST items build through the same constructor (**Test L**); `evidence_from_dig` preserves locator/kind/scope; three new `SourceKind`s exist.
`test_memory_event_store.py`: append/load round trip; concurrency error; duplicate error; per-project isolation.

## 3. Task T2 — Durable semantic identity models

**Commit:** `feat: add durable semantic identity contracts`

### 3.1 `domain/semantic_identity.py`
```python
class SemanticAddress(FrozenModel):
    address_id: str; project_id: str
    subject: str; facet: str; scope: tuple[str, ...] = ()   # DESCRIPTORS — never equality keys
    descriptor_version: int = 1  (ge=1)
    created_by_judgment_id: str

class ClaimValueKind(StrEnum): QUANTITY, TEXT, ENUMERATION, UNDECIDED
class ClaimValue(FrozenModel):
    kind: ClaimValueKind; text: str | None = None; quantity: Decimal | None = None; unit: str | None = None
    # validator: QUANTITY requires quantity; TEXT/ENUMERATION require text; UNDECIDED requires none; unit only with QUANTITY

class SemanticClaim(FrozenModel):
    claim_id: str; project_id: str; address_id: str
    predicate: str; value: ClaimValue
    evidence_ids: tuple[str, ...]   # min_length=1
    authority: Authority; provenance: Provenance
    created_by_judgment_id: str

class SemanticCandidate(FrozenModel):     # ephemeral: lives only inside a judgment
    candidate_id: str; subject: str; facet: str; scope: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...]   # min_length=1

class IssueEpistemicState(StrEnum): OPEN, CLAIMED, DISPUTED, SETTLED

class SemanticIssueVersion(FrozenModel):   # immutable; minted by the reducer
    version_id: str; project_id: str; address_id: str
    claim_ids: tuple[str, ...]; epistemic_state: IssueEpistemicState
    equivalent_address_ids: tuple[str, ...]   # under the interpretation current at minting
    supersedes_version_id: str | None; created_by_event_id: str
```
Design note recorded in module docstring: descriptors are human-readable and versioned; identity is `address_id` alone (§7.2, §4.5).

### 3.2 Tests
Model validation (value/kind consistency, evidence non-empty); **Test A (model level):** two `SemanticAddress` objects with identical descriptors and different ids are unequal and nothing in the module offers a descriptor-equality helper (assert via `inspect`: no public callable takes two addresses).

## 4. Task T3 — Semantic judgment, reasoner port, fake

**Commit:** `feat: add semantic judgment and reasoner contracts`

### 4.1 `domain/semantic_judgment.py`
```python
class JudgmentKind(StrEnum):
    CREATE_ADDRESS, BIND_TO_ADDRESS, ASSERT_CLAIM, EQUIVALENT, DISTINCT, CONFLICTS_WITH, SUPERSEDE
    # ASSERT_CLAIM is added beyond the task's minimum list: claims are the governed object and
    # need an admission path. Justification recorded here.

class ReasonerFingerprint(FrozenModel):
    provider: str; model: str; policy_version: str
    @property is_human -> bool   # provider == "human"

def independent(a: ReasonerFingerprint, b: ReasonerFingerprint) -> bool
    # default rule: human is independent of any model; two models are independent iff
    # provider or model differs. Same provider+model+policy is NOT independent regardless
    # of invocation. (Configurable later via AdmissionPolicy.independence.)

# Proposals — discriminated by `kind`
class CreateAddressProposal:   kind=CREATE_ADDRESS; candidate: SemanticCandidate
class BindToAddressProposal:   kind=BIND_TO_ADDRESS; candidate: SemanticCandidate; address_id: str
class AssertClaimProposal:     kind=ASSERT_CLAIM; address_id; predicate; value: ClaimValue; evidence_ids (min 1); authority: Authority
class EquivalentProposal:      kind=EQUIVALENT; address_a: str; address_b: str   # validator a != b
class DistinctProposal:        kind=DISTINCT;   address_a; address_b
class ConflictsWithProposal:   kind=CONFLICTS_WITH; claim_a: str; claim_b: str   # a != b
class SupersedeProposal:       kind=SUPERSEDE; target_judgment_id: str; reason: str
type JudgmentProposal = Annotated[Union[...], Field(discriminator="kind")]

class SemanticJudgment(FrozenModel):
    judgment_id: str; project_id: str
    proposal: JudgmentProposal
    visible_evidence_ids: tuple[str, ...]
    compared_object_ids: tuple[str, ...] = ()
    rationale: str                 # min_length=1, max_length=2000 — concise, never chain-of-thought
    confidence: float | None = None  # metadata only
    reasoner: ReasonerFingerprint; invocation_id: str; proposed_at: datetime
    @property kind -> JudgmentKind

def proposal_signature(p: JudgmentProposal) -> tuple[str, ...]
    # structural identity for agreement/disagreement checks: e.g. ("EQUIVALENT", min(a,b), max(a,b));
    # ("DISTINCT", min, max) pairs with EQUIVALENT on the same pair as a contradiction.
def contradicts(p: JudgmentProposal, q: JudgmentProposal) -> bool  # EQUIVALENT vs DISTINCT same pair only
```

### 4.2 `ports/semantic_reasoner.py`
```python
class ReasoningRequest(FrozenModel):
    project_id: str; evidence: tuple[EvidenceItem, ...]
    focus_object_ids: tuple[str, ...] = ()      # bounded: addresses/claims the reasoner may compare
    known_addresses: tuple[SemanticAddress, ...] = ()
    known_claims: tuple[SemanticClaim, ...] = ()
class SemanticReasoner(Protocol):
    @property fingerprint(self) -> ReasonerFingerprint
    def propose(self, request: ReasoningRequest) -> tuple[SemanticJudgment, ...]
```
The reasoner never receives an `EventStore` or `IntentState` — bounded inputs only (Law 3).

### 4.3 `adapters/semantics/fake_reasoner.py`
`ScriptedSemanticReasoner(fingerprint, judgments)` returns the scripted tuple and records every request it saw (`requests` attribute) so tests can assert bounded inputs. Provider adapter (xAI) is **deferred** to the next integration task; document in module docstring.

### 4.4 Tests
Proposal validation (a != b); `independent()` truth table incl. same fingerprint/different invocation → False, human vs model → True; `contradicts()`; rationale length bound; fake returns scripted judgments and records requests.

## 5. Task T4 — Events, semantic state, reducer, current view

**Commit:** `feat: add governed semantic state transitions`

### 5.1 `domain/events.py` additions
```python
EventType: EVIDENCE_INGESTED, SEMANTIC_JUDGMENT_RECORDED, SEMANTIC_ADMISSION_DECIDED, DERIVATION_RECORDED
class EvidencePayload(FrozenModel): evidence: EvidenceItem
class SemanticJudgmentPayload(FrozenModel): judgment: SemanticJudgment
class SemanticAdmissionPayload(FrozenModel):
    judgment_id: str; route: AdmissionRoute; reasons: tuple[str, ...]; corroborating_judgment_ids: tuple[str, ...] = ()
class DerivationPayload(FrozenModel): child_id: str; parent_id: str
```
`AdmissionRoute` (StrEnum `APPLY | REQUIRE_SECOND_LENS | REQUIRE_HUMAN | REJECT`) is defined in `domain/semantic_judgment.py` (T3 adds it) so events.py does not import admission.py. Register in `EVENT_PAYLOAD_TYPES`; extend `_reject_project_mismatch` for the new payloads that embed project_id.

### 5.2 `domain/semantic_state.py`
```python
class EquivalenceRecord(FrozenModel): judgment_id; address_a; address_b
class ConflictRecord(FrozenModel):    judgment_id; claim_a; claim_b
class SemanticState(FrozenModel):
    evidence: Mapping[str, EvidenceItem]
    addresses: Mapping[str, SemanticAddress]
    claims: Mapping[str, SemanticClaim]
    judgments: Mapping[str, SemanticJudgment]          # every recorded proposal (evidence)
    admissions: Mapping[str, SemanticAdmissionPayload]  # by judgment_id — latest decision
    applied_judgment_ids: tuple[str, ...]               # in order
    superseded_judgment_ids: Mapping[str, str]          # target -> superseding judgment_id
    bindings: Mapping[str, str]                         # candidate_id -> address_id
    equivalences: tuple[EquivalenceRecord, ...]
    conflicts: tuple[ConflictRecord, ...]
    issue_versions: Mapping[str, SemanticIssueVersion]
    issue_heads: Mapping[str, str]                      # address_id -> version_id
    derivations: tuple[DerivationEdge, ...]             # from domain/derivation (T6 adds model; T4 declares field with tuple of a minimal DerivationEdge defined in T4 — see 5.5)
```
Mappings frozen via the same `MappingProxyType` pattern as `IntentState`.

### 5.3 `domain/state.py`
Add `semantic: SemanticState = Field(default_factory=SemanticState)`. Existing tests must stay green.

### 5.4 `application/semantic_reducer.py`
`reduce_semantic_event(state: SemanticState, stored: StoredEvent) -> SemanticState` handling the four types:
- `EVIDENCE_INGESTED` → add evidence.
- `SEMANTIC_JUDGMENT_RECORDED` → add judgment (duplicate id → ValueError).
- `SEMANTIC_ADMISSION_DECIDED` → record admission; **only when `route is APPLY`** apply the transition:
  - `CREATE_ADDRESS`: mint `address_id = "ADDR-" + sha256(project_id|judgment_id)[:16]`; record binding candidate→address; mint issue version (OPEN).
  - `BIND_TO_ADDRESS`: address must exist → record binding.
  - `ASSERT_CLAIM`: address must exist; every evidence_id must exist in `state.evidence`; mint `claim_id = "CLAIM-" + sha256(project_id|judgment_id)[:16]`; provenance from the judgment's reasoner + evidence; new issue version.
  - `EQUIVALENT`: both addresses exist → append `EquivalenceRecord`; new issue versions for both addresses.
  - `DISTINCT`: record only (no state change beyond admission).
  - `CONFLICTS_WITH`: both claims exist **and share a representative** under the current view (else ValueError — a conflict is between claims at one locus); append `ConflictRecord`; new issue versions.
  - `SUPERSEDE`: target must be an applied judgment; record `superseded_judgment_ids[target] = judgment_id`; mint new issue versions for every address touched by the target.
  - Any other route → record admission only. **A non-APPLY admission never touches addresses/claims/equivalences/conflicts.**
- `DERIVATION_RECORDED` → append edge.
Issue version ids: `f"{event_id}:{address_id}"`. Epistemic state of a minted version is computed by `semantic_view` helpers over the *post-transition* state.

### 5.5 `domain/derivation.py` — model only in T4
`class DerivationEdge(FrozenModel): child_id; parent_id; recorded_by_event_id`. Traversal is T6.

### 5.6 `application/reducer.py`
Add one `case` covering the four new types delegating to `reduce_semantic_event(state.semantic, stored_event)` and threading the result into the returned `IntentState`.

### 5.7 `domain/semantic_view.py` — pure derivation of the current interpretation
```python
class SemanticLocus(FrozenModel):
    representative_id: str; address_ids: tuple[str, ...]   # sorted; representative = min
    claim_ids: tuple[str, ...]; epistemic_state: IssueEpistemicState
    disputed_claim_pairs: tuple[tuple[str, str], ...]
    scope: tuple[str, ...]        # union of member scopes
class CurrentSemanticView(FrozenModel):
    representatives: Mapping[str, str]      # address_id -> representative_id
    loci: tuple[SemanticLocus, ...]         # sorted by representative_id
    active_equivalence_judgment_ids, active_conflict_judgment_ids: tuple[str, ...]
def active_judgment_ids(state) -> frozenset[str]   # applied and not superseded (transitively: a SUPERSEDE that is itself superseded restores its target)
def derive_view(state: SemanticState) -> CurrentSemanticView
```
Union-find over **active** `EQUIVALENT` records. Epistemic rule per locus: no claims → OPEN; any active conflict between two member claims → DISPUTED; else any claim with `authority is CANONICAL` → SETTLED; else CLAIMED. (Conflict wins over canonical: an unresolved dispute is never SETTLED.)

### 5.8 Tests
`test_semantic_events.py`: envelope validation for the 4 types; project mismatch rejection.
`test_semantic_reducer.py` (drive with hand-built `StoredEvent`s, no governor):
- **B** binding creates referential identity: after APPLY of BIND_TO_ADDRESS, `state.semantic.bindings[C] == "ADDR-X"`.
- **A** two CREATE_ADDRESS with identical descriptors → two addresses, view has two loci.
- **C** EQUIVALENT applied: both addresses still in `addresses`, both issue heads present, view has one locus containing both ids.
- **E** two addresses each with one claim, EQUIVALENT → locus claim_ids contains both; no claim removed.
- **F** two claims at one address + CONFLICTS_WITH → both claims present; locus DISPUTED.
- **D** SUPERSEDE of the EQUIVALENT judgment → view shows two loci again; old judgment still in `judgments`; `superseded_judgment_ids` set; old issue versions still readable.
- Non-APPLY admission changes nothing.
- CONFLICTS_WITH across different loci → ValueError.
- **P** replay determinism: replay the same events twice → identical `IntentState` (model equality) and identical `derive_view`.
`test_semantic_view.py`: epistemic rules incl. conflict beats canonical; representative is min id.

## 6. Task T5 — Admission routing

**Commit:** `feat: add semantic admission routing`

### 6.1 `domain/admission.py`
```python
class AdmissionPolicy(FrozenModel):
    material_kinds: frozenset[JudgmentKind] = {EQUIVALENT, CONFLICTS_WITH, SUPERSEDE}
    canonical_requires_authority: bool = True
class AdmissionDecision(FrozenModel):
    judgment_id: str; route: AdmissionRoute; reasons: tuple[str, ...]; corroborating_judgment_ids: tuple[str, ...]
def route_judgment(state: IntentState, judgment: SemanticJudgment, policy: AdmissionPolicy) -> AdmissionDecision
```
Deterministic rules, in order:
1. **Structural** — every referenced address/claim/evidence/judgment exists in `state.semantic`; SUPERSEDE target must be applied and not already superseded; else `REJECT` (reason `STRUCTURAL:*`).
2. **Authority invention** — `ASSERT_CLAIM` with `authority is CANONICAL` from a non-human reasoner → `REJECT` (`AUTHORITY_INVENTION`). From a human reasoner: requires an active `AuthorityRecord` in `state.objects` whose `authorized_by == reasoner.model` (convention: when `provider == "human"`, `model` carries the human actor id, e.g. `"human://alice"`) and whose `scope` is `()` or intersects the target address's scope; if absent → `REQUIRE_HUMAN` (`AUTHORITY_UNRESOLVED`).
3. **Human authority path** — a human reasoner whose authority record covers the scope → `APPLY` for any kind.
4. **Low-risk** — kind not in `material_kinds` → `APPLY`.
5. **Material** — find prior *recorded* judgments in `state.semantic.judgments` with the same `proposal_signature`, not superseded, from an `independent()` fingerprint:
   - any prior independent judgment whose proposal `contradicts()` this one → `REQUIRE_HUMAN` (`LENS_DISAGREEMENT`), corroborating ids listed;
   - an independent agreeing judgment exists → `APPLY` with `corroborating_judgment_ids`;
   - none → `REQUIRE_SECOND_LENS`.
6. `confidence` is never read (test enforces via a judgment with `confidence=1.0` and one with `None` routing identically).

### 6.2 Tests (`test_admission.py`)
**G** high-confidence EQUIVALENT alone → REQUIRE_SECOND_LENS. **H** CREATE_ADDRESS/ASSERT_CLAIM(PROPOSED) from a model → APPLY. **I** one material judgment → not APPLY. **J** EQUIVALENT then independent DISTINCT on same pair → REQUIRE_HUMAN, no transition. Same-fingerprint second EQUIVALENT (different invocation) → still REQUIRE_SECOND_LENS (independence not faked). Independent agreeing second lens → APPLY with corroboration. **K** human canonical claim without AuthorityRecord → REQUIRE_HUMAN; with record → APPLY. AI canonical claim → REJECT. Missing address → REJECT. Confidence-blind test.

## 7. Task T6 — Derivation and blast radius

**Commit:** `feat: add semantic supersession blast radius`

### 7.1 `domain/derivation.py` additions
```python
def descendants(edges: Iterable[DerivationEdge], roots: Iterable[str]) -> frozenset[str]   # transitive, cycle-safe
def stale_object_ids(state: SemanticState) -> frozenset[str]
    # roots = superseded judgment ids ∪ issue versions created by superseded judgments' events
    # (versions whose created_by_event_id is the admission event of a superseded judgment)
    # returns descendants(roots) — historical records untouched; this is a current-view computation
```
Add `stale_ids: tuple[str, ...]` to `CurrentSemanticView` (T4 leaves it empty; T6 fills it).

### 7.2 Tests (`test_derivation.py`)
**M** J1 → D1 → D2 → D3; supersede J1 → `{D1, D2, D3} ⊆ stale`; nothing stale before supersession; cycle does not loop; unrelated derivation chain untouched; historical edges unchanged after supersession.

## 8. Task T7 — Governance service, scoped handoff, lifecycle

**Commit:** `feat: add evidence ingestion and scoped intent handoff` then `test: prove Intent Intelligence v2 core lifecycle invariants`

### 8.1 `application/semantic_governance.py`
```python
class SemanticGovernor:
    def __init__(self, store: EventStore, project_id: str, policy: AdmissionPolicy, clock: Callable[[], datetime], id_factory: Callable[[str], str] | None = None)
    def state(self) -> IntentState                      # replay(project_id, store.load(project_id))
    def view(self) -> CurrentSemanticView
    def ingest(self, evidence: EvidenceItem) -> StoredEvent
    def submit(self, judgment: SemanticJudgment) -> AdmissionDecision
        # 1 append SEMANTIC_JUDGMENT_RECORDED  2 route_judgment over fresh replayed state
        # 3 append SEMANTIC_ADMISSION_DECIDED with the route  4 return decision
    def derive(self, child_id: str, parent_id: str) -> StoredEvent
    def propose_and_submit(self, reasoner: SemanticReasoner, request: ReasoningRequest) -> tuple[AdmissionDecision, ...]
```
The governor is the only place a judgment becomes an event; the reasoner never sees the store. Event ids: `id_factory(prefix)` default `uuid4`-based; tests inject a counter for determinism.

### 8.2 `domain/handoff.py` + `application/handoff.py`
```python
HANDOFF_VERSION = "intent-decision-handoff-v1"
class SemanticReadiness(FrozenModel):
    closure: ClosureResult                      # existing scoped closure, unchanged
    disputed_locus_ids: tuple[str, ...]; stale_object_ids: tuple[str, ...]; open_locus_ids: tuple[str, ...]
    ready: bool                                 # closure.closed and no disputed and no stale in scope
class IntentDecisionHandoff(FrozenModel):
    handoff_version: Literal[HANDOFF_VERSION]; project_id: str; scope: str; semantic_state_revision: int
    loci: tuple[SemanticLocus, ...]              # only loci whose scope is () or contains `scope`
    claim_ids, evidence_ids, authority_record_ids: tuple[str, ...]
    superseded_judgment_ids: tuple[str, ...]     # superseded judgments touching in-scope addresses
    stale_object_ids: tuple[str, ...]
    readiness: SemanticReadiness
def build_intent_decision_handoff(state: IntentState, scope: str) -> IntentDecisionHandoff   # application/handoff.py
```
Points to truth by ID; copies no rationale, no evidence content.

### 8.3 Tests
`test_handoff.py`: **N** scope A (canonical Intent+Requirement objects, one CLAIMED locus) ready; scope B has a DISPUTED locus → B not ready, A still builds and is ready. **O** A's handoff contains only A's loci/claims/evidence, correct revision, no B ids.
`tests/integration/test_semantic_lifecycle.py` (governor + InMemoryEventStore + ScriptedSemanticReasoner): full T1→T5 story — ingest human/code/test evidence (**L**); create two addresses via model (**H**); assert claims; EQUIVALENT from model → SECOND_LENS (**G/I**); independent second model agrees → APPLY (**C/E**); conflict claims → CONFLICTS_WITH via second lens → DISPUTED (**F**); derive D1→D2→D3 from the equivalence judgment; human supersedes with authority → equivalence reversed (**D**), blast radius (**M**); replay from `store.load` reproduces state and view (**P**); handoff for a ready scope (**N/O**). Assert zero network via a socket guard fixture.

## 9. Task T8 — Verification and review

Full `uv run pytest -v`, `ruff check .`, `mypy src`, `git diff --check`; confirm `git diff <9N_ARCHITECTURE_COMMIT> -- evals` is empty; code-quality review pass over all new modules; fix findings; final commit if needed.

## 10. Deferred (explicitly)
Provider (xAI) `SemanticReasoner` adapter; JSONL file event store; configurable independence policy beyond the default rule; materiality/grounding engines; relations beyond EQUIVALENT/DISTINCT/CONFLICTS_WITH; gap projection from loci; Postgres migration for new event types (Postgres stores `event_document` JSON — no schema change needed, but the e2e suite is not extended here).
