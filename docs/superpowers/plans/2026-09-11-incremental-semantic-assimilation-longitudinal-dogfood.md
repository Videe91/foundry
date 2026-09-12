# Incremental Semantic Assimilation + Longitudinal Dogfood Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and freeze the smallest Intent Intelligence v2 lifecycle substrate required to test whether a frontier model can assimilate real project changes from evidence deltas plus persistent semantic state instead of reconstructing the full history each cycle.

**Architecture:** Bind-first incremental assimilation. Call 1 binds or creates semantic addresses from delta evidence; Call 2 supports/asserts/supersedes claims only within the admitted neighborhood. Foundry governs every proposal, preserves immutable history, propagates supersession through blast radius, scopes readiness, and compares one persistent arm against a fair fresh-reconstruction arm over real Foundry history.

**Tech Stack:** Python 3.12+, Pydantic v2, existing Foundry event/reducer architecture, uv, pytest, xAI SDK, Git historical evidence.

**Spec:** `docs/superpowers/specs/2026-09-11-incremental-semantic-assimilation-longitudinal-dogfood-design.md` (APPROVED 2026-09-11 at `bacd6093`).

---

## Global Constraints (locked — no task may alter these)

1. **AI decides meaning. Foundry decides whether/how that meaning changes durable state.** No production function may originate a semantic conclusion from string equality, chronology, confidence, or similarity.
2. **Bind-first, two frontier calls per delta.** Call 1 allows `BIND_TO_ADDRESS | CREATE_ADDRESS`; Call 2 allows `SUPPORTS_CLAIM | ASSERT_CLAIM | SUPERSEDE | CONFLICTS_WITH`. No whole-state reconciliation call. `EQUIVALENT` / `DISTINCT` are never requested in 9P.
3. **Reference law.** Every id a model draft references must already exist in the `ReasoningRequest`. A claim asserted in a response has no durable id and may be referenced by nothing in that response. `CONFLICTS_WITH` needs two *pre-existing known* claims.
4. **Correction path** = `ASSERT_CLAIM(new, at known address)` + `SUPERSEDE(old claim's known created_by_judgment_id)` in one Call 2 response. No third call. No model-generated claim ids.
5. **Exactly one new semantic operation:** `SUPPORTS_CLAIM` with durable `ClaimSupportRecord`. `SemanticClaim.evidence_ids` is never mutated; the view derives effective evidence.
6. **Evidence lineage** (`artifact_ref`, `supersedes_evidence_id`) is deterministic data. Never: "newer evidence supersedes a semantic claim".
7. **`SUPERSEDE` stays material.** A human authority actor may only AGREE (identical `proposal_signature`, authenticated human fingerprint) or DECLINE. ≤1 authorization per tracked correction (A, B, C), ≤3 total. The human never edits, retargets, creates, selects, repairs or authors.
8. **Pending material governance qualifies readiness** via `pending_material_judgment_ids`; a declined supersession leaves both claims live and the proposal pending; no conflict is inferred.
9. **`SATISFIED_BY`** is a view-level derivation over `proposal_signature`; no mutable workflow record.
10. **Retrieval:** show all active in-scope address descriptors iff count ≤ 200; otherwise an explicit `UNSUPPORTED_ABOVE_THRESHOLD` failure (deferred branch). No lexical top-K, no embeddings.
11. **Arm F:** one ledger across T1–T4; T>1 receives delta evidence only, never unchanged evidence. **Arm R:** fresh ledger per T, all evidence versions ≤ T, same two-call shape, same model/effort/prompt/drafts.
12. **Model:** xAI `grok-4.6`, `reasoning_effort=high`, no tools, no web, no stored chat, gRPC retries 0, no rerolls.
13. **Ceilings:** 16 frontier calls, 0 judge calls, ≤3 human authorizations, $8.00 hard.
14. **T6 cross-model is 9Q.** No second provider.
15. **Frozen forever:** `evals/comparative/**`, 9K/9L/9M/9N/9O artifacts, the v1 xAI adapter, v0 behaviour. The 9O experiment directory is never modified.
16. **Two phases with a hard boundary:** `9P-IMPLEMENTATION` (Tasks 1–18, zero live calls) ends with a frozen commit; `9P-LIVE` (Task 19) starts only from that commit with a clean tree and ends with committed artifacts. After the first live call, no source/test/script/prompt/policy change until artifacts are committed.
17. **New durable primitives beyond** `SUPPORTS_CLAIM`, `ClaimSupportRecord`, the two lineage fields, `pending_material_judgment_ids` and the `SATISFIED_BY` derivation **require architect review** — stop with `PLAN_BLOCKED_BY_ARCHITECTURE_CONFLICT`.

**Per-task discipline (every task):** write the test file first → run it and capture RED verbatim → minimal production change → GREEN → refactor while green → `uv run pytest tests/unit -q`, `uv run ruff check src tests scripts`, `uv run mypy src` → fresh spec-compliance review + code-quality review → commit with the stated message. Reviewers judge files only.

**Conventions used below:** `T0 = datetime(2026, 9, 11, tzinfo=UTC)`; ids minted in tests via `itertools.count` factories; hand-built `StoredEvent`s drive reducer tests; `InMemoryEventStore` + `SemanticGovernor` drive application tests; `ScriptedSemanticReasoner` is the only reasoner under test; a `socket` guard is installed on every harness test module.

---

## Task map

| # | Task | Layer | Files |
|---|---|---|---|
| 1 | Evidence lineage | domain + reducer + view | `domain/evidence.py`, `application/semantic_reducer.py`, `domain/semantic_view.py` |
| 2 | `SUPPORTS_CLAIM` contract | domain | `domain/semantic_judgment.py`, `domain/semantic_state.py` |
| 3 | `SUPPORTS_CLAIM` reducer + view + admission | application + domain | `application/semantic_reducer.py`, `domain/semantic_view.py`, `domain/admission.py` |
| 4 | Pending governance + `SATISFIED_BY` readiness | domain | `domain/semantic_view.py`, `domain/handoff.py`, `application/handoff.py` |
| 5 | xAI lifecycle drafts | adapter | `adapters/semantics/xai_reasoner.py` |
| 6 | Prompt + request rendering | adapter | `adapters/semantics/xai_reasoner.py` |
| 7 | Incremental context assembly | application | `application/assimilation_context.py` |
| 8 | Incremental assimilation orchestrator | application | `application/incremental_assimilation.py` |
| 9 | Human authorization protocol | experiments | `experiments/longitudinal/authority.py` |
| 10 | Real Foundry timeline loader | experiments | `experiments/longitudinal/timeline.py` |
| 11 | Preregistered derivation fixture | experiments | `experiments/longitudinal/derivations.py` |
| 12 | Arm F runner | experiments | `experiments/longitudinal/arm_f.py` |
| 13 | Arm R runner | experiments | `experiments/longitudinal/arm_r.py` |
| 14 | Sealed expectation manifest | experiments | `experiments/longitudinal/expectations.py` |
| 15 | Integrity gates | experiments | `experiments/longitudinal/integrity.py` |
| 16 | Immutable artifact schema | experiments | `experiments/longitudinal/artifacts.py` |
| 17 | Replay + structural scoring | experiments | `experiments/longitudinal/scoring.py` |
| 18 | Freeze implementation | — | verification only |
| 19 | 9P-LIVE | scripts | `scripts/run_longitudinal_dogfood.py` (built in Task 16, executed in Task 19) |

New package: `src/foundry/experiments/longitudinal/` (with `__init__.py`). Tests under `tests/unit/` (`test_evidence_lineage.py`, `test_supports_claim.py`, `test_supports_claim_reducer.py`, `test_pending_governance.py`, `test_xai_lifecycle_drafts.py`, `test_xai_lifecycle_prompt.py`, `test_assimilation_context.py`, `test_incremental_assimilation.py`, `test_longitudinal_authority.py`, `test_longitudinal_timeline.py`, `test_longitudinal_derivations.py`, `test_longitudinal_arm_f.py`, `test_longitudinal_arm_r.py`, `test_longitudinal_expectations.py`, `test_longitudinal_integrity.py`, `test_longitudinal_artifacts.py`, `test_longitudinal_scoring.py`) and `tests/integration/test_longitudinal_lifecycle.py`.

---

# 9P-IMPLEMENTATION

## Task 1 — Evidence lineage

**Spec:** §15, §16. **Commit:** `feat: add immutable evidence version lineage`

### Production change (minimal)

`src/foundry/domain/evidence.py`:
```python
class EvidenceItem(FrozenModel):
    ...existing fields...
    artifact_ref: str | None = None            # stable identity of the versioned thing, e.g. "repo:docs/x.md"
    supersedes_evidence_id: str | None = None  # previous immutable version of the same artifact

    @model_validator(mode="after")
    def validate_lineage_shape(self) -> EvidenceItem:
        if self.supersedes_evidence_id is not None:
            if self.artifact_ref is None:
                raise ValueError("supersedes_evidence_id requires artifact_ref")
            if self.supersedes_evidence_id == self.evidence_id:
                raise ValueError("evidence cannot supersede itself")
        return self
```
`evidence_item(...)` gains keyword-only `artifact_ref: str | None = None, supersedes_evidence_id: str | None = None`. `DigRecord` gains `artifact_ref: str | None = None`; `evidence_from_dig` forwards it. Both defaults keep every existing constructor call and test green.

`src/foundry/application/semantic_reducer.py::_ingest_evidence` — state-aware lineage checks (the model cannot see state): if `supersedes_evidence_id` is set, the target must exist in `state.evidence`, must carry the same `artifact_ref`, and must not already be superseded by another item (one linear chain per artifact). Violations raise `ValueError` (the governor's dry-run therefore refuses the event).

`src/foundry/domain/semantic_view.py` — `CurrentSemanticView` gains `current_evidence_ids: tuple[str, ...]` (evidence items not named as `supersedes_evidence_id` by any other item, sorted) and `superseded_evidence_ids: tuple[str, ...]`. Pure derivation; no authority attached.

### RED → GREEN
- [ ] Write `tests/unit/test_evidence_lineage.py`:
  - `test_lineage_fields_default_to_none_keeping_existing_construction_compatible`
  - `test_supersedes_requires_artifact_ref` (ValidationError)
  - `test_evidence_cannot_supersede_itself` (ValidationError)
  - `test_reducer_refuses_lineage_to_unknown_evidence` (`ValueError` match `unknown`)
  - `test_reducer_refuses_lineage_across_artifacts` (different `artifact_ref` → `ValueError`)
  - `test_reducer_refuses_second_successor_of_same_version` (linear chain)
  - `test_view_derives_current_and_superseded_evidence_versions`
  - `test_lineage_never_changes_claims_or_judgments` — a claim citing the superseded version stays live, unchanged, in the view (§16)
  - `test_replay_reproduces_lineage` (JSON round-trip through `parse_event`)
- [ ] `uv run pytest tests/unit/test_evidence_lineage.py -q` → RED: `TypeError: ... unexpected keyword argument 'artifact_ref'` / `AttributeError: ... 'current_evidence_ids'`.
- [ ] Implement the three changes above → GREEN.
- [ ] `uv run pytest tests/unit -q` (all existing evidence/reducer/view/governance tests still green).

**Review gate:** spec §15/§16 mapped; no rule reads lineage to change a claim; layer rules hold.

---

## Task 2 — `SUPPORTS_CLAIM` domain contract

**Spec:** §11, §12. **Commit:** `feat: add SUPPORTS_CLAIM judgment contract`

### Production change
`src/foundry/domain/semantic_judgment.py`:
```python
class JudgmentKind(StrEnum):
    ...existing...
    SUPPORTS_CLAIM = "SUPPORTS_CLAIM"

class SupportsClaimProposal(FrozenModel):
    kind: Literal[JudgmentKind.SUPPORTS_CLAIM] = JudgmentKind.SUPPORTS_CLAIM
    claim_id: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)

type JudgmentProposal = Annotated[... | SupportsClaimProposal, Field(discriminator="kind")]

# proposal_signature: case SupportsClaimProposal(): return ("SUPPORT", p.claim_id, *sorted(p.evidence_ids))
```
`src/foundry/domain/semantic_state.py`:
```python
class ClaimSupportRecord(FrozenModel):
    judgment_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    recorded_by_event_id: str = Field(min_length=1)

class SemanticState(FrozenModel):
    ...
    claim_supports: tuple[ClaimSupportRecord, ...] = ()
```
No new event type: a `SUPPORTS_CLAIM` judgment travels in `SemanticJudgmentPayload` and is applied by `SEMANTIC_ADMISSION_DECIDED` like every other kind. `AdmissionPolicy.material_kinds` is unchanged (SUPPORT is low-risk).

### RED → GREEN
- [ ] Write `tests/unit/test_supports_claim.py`:
  - `test_supports_claim_proposal_requires_at_least_one_evidence_id`
  - `test_supports_claim_round_trips_through_the_discriminated_union` (`SemanticJudgment.model_validate(model_dump(mode="json"))` picks `SupportsClaimProposal`)
  - `test_supports_claim_signature_is_order_insensitive_over_evidence`
  - `test_supports_claim_is_not_a_material_kind_by_default` (`JudgmentKind.SUPPORTS_CLAIM not in AdmissionPolicy().material_kinds`)
  - `test_claim_support_record_shape_and_state_default` (`SemanticState().claim_supports == ()`)
  - `test_event_with_supports_claim_judgment_parses` (`parse_event` of a `SEMANTIC_JUDGMENT_RECORDED` envelope)
- [ ] RED: `ImportError: cannot import name 'SupportsClaimProposal'`.
- [ ] Implement → GREEN. mypy: `proposal_signature` match must be exhaustive.

**Review gate:** exactly one new kind; claim body untouched; no new event type.

---

## Task 3 — `SUPPORTS_CLAIM` reducer, view, admission

**Spec:** §12 (invariants), D-ADM-5. **Commit:** `feat: apply and derive claim support without mutating claims`

### Production change
`src/foundry/application/semantic_reducer.py`:
```python
case SupportsClaimProposal():
    transitioned, touched = _apply_support_claim(state, judgment, proposal, event_id)

def _apply_support_claim(state, judgment, proposal, event_id) -> tuple[SemanticState, tuple[str, ...]]:
    claim = _require_claim(state, proposal.claim_id)
    if claim.created_by_judgment_id not in active_judgment_ids(state):
        raise ValueError(f"claim {claim.claim_id} is not live")
    for evidence_id in proposal.evidence_ids:
        if evidence_id not in state.evidence: raise ValueError(...)
    record = ClaimSupportRecord(judgment_id=judgment.judgment_id, claim_id=claim.claim_id,
                                evidence_ids=proposal.evidence_ids, recorded_by_event_id=event_id)
    return _updated(state, claim_supports=(*state.claim_supports, record)), (claim.address_id,)
```
`_touched_addresses` handles `SupportsClaimProposal` (the claim's address) so `SUPERSEDE` of a support judgment re-mints the head.

`src/foundry/domain/semantic_view.py` — `CurrentSemanticView.effective_evidence: Mapping[str, tuple[str, ...]]` = for each live claim, `sorted(set(claim.evidence_ids) | ⋃ evidence of ACTIVE support records for it)`; `active_support_judgment_ids`.

`src/foundry/domain/admission.py` — `_referenced_claims` returns `(p.claim_id,)`, `_referenced_evidence` includes `p.evidence_ids` for `SupportsClaimProposal`; new structural rule `_support_problems`: claim must exist **and be live** (mirrors the reducer, D-ADM-5) → `REJECT "STRUCTURAL: claim <id> is not live"`.

### RED → GREEN
- [ ] Write `tests/unit/test_supports_claim_reducer.py` (hand-built `StoredEvent`s + governor):
  - `test_support_appends_record_and_leaves_claim_evidence_ids_untouched`
  - `test_effective_evidence_includes_supporting_evidence`
  - `test_support_targeting_superseded_claim_raises_in_reducer_and_rejects_in_admission`
  - `test_support_citing_unknown_evidence_raises`
  - `test_superseded_support_disappears_from_effective_evidence_but_record_remains`
  - `test_support_mints_new_issue_head_with_created_by_judgment_id`
  - `test_support_routes_apply_as_low_risk_from_a_model` (governor + `route_judgment`)
  - `test_replay_is_identical_with_support_records` (JSON round-trip, `IntentState` equality, view equality)
- [ ] RED: `AttributeError: 'CurrentSemanticView' has no attribute 'effective_evidence'` / reducer `ValueError`-free pass where a raise is expected.
- [ ] Implement → GREEN. Full unit suite green.

**Review gate:** no path mutates `claims[...]`; admission mirrors reducer liveness; view is pure.

---

## Task 4 — Pending governance + `SATISFIED_BY` readiness

**Spec:** §17 (derived status), §24, 9P-A §4. **Commit:** `feat: derive satisfied and pending material governance for readiness`

### Production change
`src/foundry/domain/semantic_view.py`:
```python
class CurrentSemanticView(FrozenModel):
    ...
    pending_judgment_ids: tuple[str, ...] = ()            # latest route ∈ {REQUIRE_SECOND_LENS, REQUIRE_HUMAN} and not satisfied
    satisfied_by: Mapping[str, str] = ...                  # pending judgment_id → applied ACTIVE judgment_id with equal proposal_signature and same kind
```
Derivation: for every judgment whose latest admission is `REQUIRE_SECOND_LENS`/`REQUIRE_HUMAN` and which is not applied: if an applied, active judgment `agrees()` with it → `satisfied_by[pending] = that id`; else it is pending. Deterministic, signature-based, no meaning.

`src/foundry/domain/handoff.py` — `SemanticReadiness.pending_material_judgment_ids: tuple[str, ...]` = `view.pending_judgment_ids` whose `judgment_address_ids(...)` intersects the in-scope address set; `ready = closure.closed and not disputed and not stale and not pending_material`. `IntentDecisionHandoff` gains the same field. `application/handoff.py` threads it.

### RED → GREEN
- [ ] Write `tests/unit/test_pending_governance.py`:
  - `test_pending_supersede_blocks_the_affected_scope_only` (scope A pending → not ready; scope B ready; project not globally blocked)
  - `test_human_agreeing_judgment_satisfies_the_pending_ai_proposal` (AI `SUPERSEDE` → `REQUIRE_SECOND_LENS`; human with `AuthorityRecord` submits identical proposal → `APPLY`; `view.satisfied_by[ai_id] == human_id`; readiness no longer lists it)
  - `test_declined_or_unanswered_proposal_remains_pending`
  - `test_no_conflict_is_inferred_from_a_declined_supersession` (`view.active_conflict_judgment_ids == ()`, both claims live, locus `CLAIMED`)
  - `test_rejected_judgment_is_never_pending`
  - `test_satisfied_by_requires_same_kind_and_signature` (an applied `DISTINCT` never satisfies a pending `EQUIVALENT` on the same pair)
  - `test_replay_reproduces_pending_and_satisfied`
- [ ] RED: `AttributeError: ... 'pending_judgment_ids'`.
- [ ] Implement → GREEN. Existing `test_handoff.py` / lifecycle test remain green (ready scopes have no pending items).

**Review gate:** derivation reads only `admissions`, `applied_judgment_ids`, `supersessions`, `proposal_signature`; no new event/state; E12's "no inferred conflict" invariant proven.

---

## Task 5 — xAI lifecycle drafts

**Spec:** §22, §7, 9P-A §1–2. **Commit:** `feat: expose bind, support and supersede drafts in the xAI reasoner`

### Production change
`src/foundry/adapters/semantics/xai_reasoner.py`:
```python
class BindToAddressDraft(FrozenModel):
    kind: Literal["BIND_TO_ADDRESS"] = "BIND_TO_ADDRESS"
    address_id: str; subject: str; facet: str; evidence_ids: tuple[str, ...] (min 1); rationale: str (1..2000)

class SupportsClaimDraft(FrozenModel):
    kind: Literal["SUPPORTS_CLAIM"] = "SUPPORTS_CLAIM"
    claim_id: str; evidence_ids: tuple[str, ...] (min 1); rationale: str

class SupersedeDraft(FrozenModel):
    kind: Literal["SUPERSEDE"] = "SUPERSEDE"
    target_judgment_id: str; reason: str (1..2000)
```
`SemanticDraft` union extended. `_to_proposal`: BIND → `_require_known("address")`, `_require_known("evidence")`, runtime-minted candidate (id, scope from cited evidence) → `BindToAddressProposal`, compared `(address_id,)`; SUPPORT → claim ∈ known claims, evidence ∈ request → `SupportsClaimProposal`, compared `(claim_id,)`; SUPERSEDE → `target_judgment_id ∈ {c.created_by_judgment_id for c in request.known_claims}` else `SemanticOutputError`, `reason` becomes the proposal reason, compared `(target_judgment_id,)`. `POLICY_VERSION = "intent-v2-9p-v1"`. The v1 adapter `adapters/intelligence/xai.py` is not touched.

### RED → GREEN
- [ ] Write `tests/unit/test_xai_lifecycle_drafts.py` (reuse the `FakeHarness` pattern from `test_xai_semantic_reasoner.py`):
  - `test_bind_draft_wraps_to_bind_proposal_with_runtime_candidate_and_derived_scope`
  - `test_bind_to_unknown_address_fails_whole_batch`
  - `test_support_draft_wraps_and_unknown_claim_fails`
  - `test_supersede_target_must_be_a_known_claims_judgment_id` (unknown → `SemanticOutputError` match target id)
  - `test_same_response_reference_to_a_new_claim_is_impossible` — batch `[AssertClaimDraft, ConflictsWithDraft(claim_a=<known>, claim_b="CLAIM-NEW")]` → whole batch `SemanticOutputError`, receipt still recorded, zero judgments returned
  - `test_correction_pattern_assert_plus_supersede_wraps_in_one_response` (two judgments, same `invocation_id`, neither referencing the other)
  - `test_forbidden_kind_for_call_one_fails` (`SupersedeDraft` under `allowed={CREATE_ADDRESS, BIND_TO_ADDRESS}`)
  - `test_drafts_still_carry_no_runtime_metadata_fields` (extend the forbidden-field set check to the three new drafts)
  - `test_policy_version_is_9p`
- [ ] RED: `ImportError: cannot import name 'BindToAddressDraft'`.
- [ ] Implement → GREEN. `tests/unit/test_xai_semantic_reasoner.py` stays green except `POLICY_VERSION` assertion, which is updated to `"intent-v2-9p-v1"` in the same commit (record this as the one intentional 9O-test change).

**Review gate:** no draft carries ids the runtime owns; every reference validated; v1 adapter untouched.

---

## Task 6 — Prompt and request rendering

**Spec:** §19, §22, 9P-A §1. **Commit:** `feat: render lifecycle context and frozen 9P system instruction`

### Production change
`src/foundry/adapters/semantics/xai_reasoner.py`:
- `render_request`: each `known_claims` entry gains `"created_by_judgment_id"`; each `evidence` entry gains `"artifact_ref"` and `"supersedes_evidence_id"`.
- `SYSTEM_INSTRUCTION` gains a **LIFECYCLE GUIDANCE** block (append-only; all 9O guarantee sentences retained verbatim):
  ```text
  When BIND_TO_ADDRESS is allowed: if a known address already denotes the observation's
  subject and facet, BIND to it regardless of wording. CREATE only for a genuinely new
  locus. NO_MATCH is legitimate: never force an observation onto an unrelated address.
  When SUPPORTS_CLAIM is allowed: if new evidence restates a known claim, return
  SUPPORTS_CLAIM for that claim_id. Never emit a duplicate ASSERT_CLAIM for a restatement.
  A correction of a known claim is exactly: ASSERT_CLAIM (the new interpretation at the
  known address) plus SUPERSEDE (the old claim's created_by_judgment_id). Do not reference
  a claim you are asserting in this same response - it has no id yet.
  Evidence lineage (artifact_ref, supersedes_evidence_id) is chronology. A newer version
  is NOT authority and does not by itself retire any claim.
  CONFLICTS_WITH may name only two claim_ids present in known_claims.
  Every id you reference must be present in this request.
  ```

### RED → GREEN
- [ ] Write `tests/unit/test_xai_lifecycle_prompt.py`:
  - `test_known_claims_render_created_by_judgment_id`
  - `test_evidence_renders_lineage_fields`
  - `test_system_instruction_states_each_lifecycle_rule` (asserts presence of: `SUPPORTS_CLAIM` preference, BIND-when-same-locus, CREATE-only-new, chronology-not-authority, correction = ASSERT + SUPERSEDE, all-ids-must-exist, evidence-is-DATA)
  - `test_system_instruction_is_frozen_by_hash` (asserts `sha256(SYSTEM_INSTRUCTION)` equals a constant `SYSTEM_INSTRUCTION_SHA256` exported by the module; the constant is set once in this task and never changed without a policy-version bump)
  - `test_9o_guarantees_still_present` (DATA / authority / tools / schema / runtime metadata / web)
- [ ] RED: `KeyError: 'created_by_judgment_id'`.
- [ ] Implement → GREEN.

**Review gate:** instruction is additive; hash constant present; nothing in the prompt names a tracked locus.

---

## Task 7 — Incremental context assembly

**Spec:** §18, §19, §34 (neighbourhood). **Commit:** `feat: add bounded assimilation context assembly`

### Production change
New `src/foundry/application/assimilation_context.py` (subordinate to a future Context Compiler; docstring says so):
```python
CANDIDATE_ADDRESS_THRESHOLD: Final[int] = 200

class ContextUnsupported(RuntimeError): ...   # raised above threshold; never silently falls back

def active_in_scope_addresses(state: IntentState, scope: str) -> tuple[SemanticAddress, ...]
def assemble_assimilation_request(*, project_id, delta: tuple[EvidenceItem, ...], state: IntentState, scope: str) -> ReasoningRequest
    # known_addresses = descriptors of all active in-scope addresses if len <= threshold else raise ContextUnsupported
    # known_claims = () ; allowed = {BIND_TO_ADDRESS, CREATE_ADDRESS}
def neighborhood_from_decisions(state_after: IntentState, decisions: tuple[AdmissionDecision, ...]) -> tuple[str, ...]
    # addresses touched by APPLIED CREATE/BIND judgments in `decisions` (bound address or minted address)
def assemble_claim_request(*, project_id, delta, state: IntentState, neighborhood: tuple[str, ...]) -> ReasoningRequest
    # known_addresses = neighborhood addresses; known_claims = LIVE claims at those addresses (asserting judgment active);
    # evidence = delta ∪ evidence versions cited by those claims' effective evidence (lineage-visible, content included);
    # allowed = {SUPPORTS_CLAIM, ASSERT_CLAIM, SUPERSEDE, CONFLICTS_WITH}
```
(Call 2 includes the cited historical evidence *versions* for the neighbourhood so the model can compare old and new text; unchanged evidence outside the neighbourhood is never included. This is the spec's "relevant evidence lineage".)

### RED → GREEN
- [ ] Write `tests/unit/test_assimilation_context.py`:
  - `test_call1_sends_descriptors_only_and_no_claims` (request has `known_claims == ()`; each `SemanticAddress` in `known_addresses`; allowed set exact)
  - `test_call1_above_threshold_raises_context_unsupported_never_falls_back` (201 addresses)
  - `test_neighborhood_is_only_addresses_touched_by_applied_bindings_and_creations` (a `REJECT`ed BIND does not add its address)
  - `test_call2_sends_only_neighborhood_claims_and_their_cited_evidence` (a claim at an untouched address is absent; its evidence absent)
  - `test_call2_excludes_unchanged_uncited_historical_evidence`
  - `test_assembly_emits_no_judgment_and_reads_no_confidence` (source scan: no `SemanticJudgment(` construction, no `confidence`)
  - `test_assembly_is_pure` (state unchanged after call)
- [ ] RED: `ModuleNotFoundError: foundry.application.assimilation_context`.
- [ ] Implement → GREEN.

**Review gate:** selection never decides meaning; threshold is a hard stop; layer rules.

---

## Task 8 — Incremental assimilation orchestrator

**Spec:** §6, §26. **Commit:** `feat: add incremental assimilation orchestrator`

### Production change
New `src/foundry/application/incremental_assimilation.py`:
```python
class DeltaOutcome(FrozenModel):
    stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]   # call 1, call 2
    neighborhood: tuple[str, ...]
    pending_supersede_judgment_ids: tuple[str, ...]      # from view.pending_judgment_ids with kind SUPERSEDE
    calls_made: int                                       # always 2 on success

def assimilate_delta(*, governor: SemanticGovernor, reasoner: SemanticReasoner, delta: tuple[EvidenceItem, ...], scope: str) -> DeltaOutcome
    # 1 ingest each delta item (lineage validated by the reducer dry-run)
    # 2 request1 = assemble_assimilation_request(...); d1 = governor.propose_and_submit(reasoner, request1)
    # 3 neighborhood = neighborhood_from_decisions(governor.state(), d1)
    # 4 request2 = assemble_claim_request(...); d2 = governor.propose_and_submit(reasoner, request2)
    # 5 return DeltaOutcome with pending SUPERSEDE ids surfaced (never resolved here)
```
No authority logic inside. No retry. Exceptions propagate to the caller (the arm runner records them).

### RED → GREEN
- [ ] Write `tests/unit/test_incremental_assimilation.py` (governor + `InMemoryEventStore` + a `SequencedReasoner` fake as in `test_intent_v2_dogfood.py`):
  - `test_delta_makes_exactly_two_reasoner_calls_in_order` (allowed kinds per call asserted on the recorded requests)
  - `test_bind_lands_evidence_on_existing_address_without_new_identity`
  - `test_create_is_legitimate_when_model_reports_no_match`
  - `test_support_adds_evidence_without_new_claim`
  - `test_correction_asserts_new_claim_and_leaves_supersede_pending` (`APPLY` for ASSERT, `REQUIRE_SECOND_LENS` for SUPERSEDE, both claims live)
  - `test_orchestrator_never_submits_a_human_judgment` (no `human_actor_id` path; a human fingerprint reasoner raises via governor)
  - `test_failure_in_call_two_propagates_after_call_one_state_is_kept`
- [ ] RED: `ModuleNotFoundError: foundry.application.incremental_assimilation`.
- [ ] Implement → GREEN.

**Review gate:** two calls, no reconciliation, no retry, no authority.

---

## Task 9 — Human authorization protocol

**Spec:** §17, 9P-A §4–5. **Commit:** `feat: add agree-or-decline authority protocol for supersession`

### Production change
New `src/foundry/experiments/longitudinal/__init__.py` and `authority.py`:
```python
ARCHITECT_ACTOR: Final[str] = "human://architect"
HUMAN_FINGERPRINT = ReasonerFingerprint(provider="human", model=ARCHITECT_ACTOR, policy_version="9p-authority-v1")

class AuthorizationDecision(StrEnum): AGREE = "AGREE"; DECLINE = "DECLINE"
class AuthorizationRecord(FrozenModel):
    track: str; pending_judgment_id: str; decision: AuthorizationDecision
    submitted_judgment_id: str | None; proposal_signature: tuple[str, ...]; recorded_at: datetime

Authorizer = Callable[[SemanticJudgment], AuthorizationDecision]   # the only input path: sees the verbatim proposal, returns AGREE/DECLINE

def record_architect_authority(governor: SemanticGovernor, *, clock, id_factory) -> StoredEvent      # project-wide AuthorityRecord at T0
def resolve_pending_supersessions(*, governor, pending_ids, authorizer, track_of: Callable[[str], str | None], budget: AuthorizationBudget, clock, id_factory) -> tuple[AuthorizationRecord, ...]
    # for each pending SUPERSEDE: if track_of(id) is None or budget exhausted for that track → skip (recorded as NOT_OFFERED);
    # AGREE → build a SemanticJudgment with the IDENTICAL proposal object, HUMAN_FINGERPRINT, rationale "AGREE: <pending id>",
    #         governor.submit(judgment, human_actor_id=ARCHITECT_ACTOR); assert route APPLY; budget.consume(track)
    # DECLINE → no judgment; record only
class AuthorizationBudget(FrozenModel): per_track: int = 1; total: int = 3   (mutable counter kept in the runner, not in state)
```
The interactive authorizer (Task 16's script) prints the proposal verbatim and reads exactly `AGREE` or `DECLINE`; any other input is re-prompted, never interpreted.

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_authority.py`:
  - `test_agree_submits_identical_signature_under_human_fingerprint_and_applies`
  - `test_agree_derives_satisfied_by_and_clears_readiness_block`
  - `test_decline_creates_no_judgment_and_leaves_proposal_pending`
  - `test_budget_per_track_and_total_enforced` (second AGREE on the same track is not offered; 4th overall refused)
  - `test_authorizer_receives_the_verbatim_proposal_and_nothing_else` (spy authorizer sees a `SemanticJudgment` equal to the pending one)
  - `test_no_api_exists_to_edit_target_reason_or_author_a_supersession` (`inspect` scan: the module exposes no function accepting a proposal/target/reason from the human)
  - `test_authority_record_is_project_wide_and_recorded_as_event`
- [ ] RED: `ModuleNotFoundError: foundry.experiments.longitudinal.authority`.
- [ ] Implement → GREEN.

**Review gate:** identical `proposal_signature`; human path only through `governor.submit(..., human_actor_id=...)`; no edit surface.

---

## Task 10 — Real Foundry timeline loader

**Spec:** §15, §20, §25. **Commit:** `feat: load the frozen four-commit Foundry timeline`

### Production change
New `src/foundry/experiments/longitudinal/timeline.py` (reuses the `GitReader` protocol from `intent_v2_dogfood.py`):
```python
TIMELINE: Final[tuple[TimelineStep, ...]] = (
  TimelineStep(t=1, commit="097584a39dd76cf86510500acb548778ce00fad9", paths=(("FOUNDRY_CONSTITUTION.md", DOCUMENT), ("docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md", DOCUMENT))),
  TimelineStep(t=2, commit="2539ff81f79f085c1eba42718947050c1b3ac61c", paths=(("docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md", DOCUMENT),)),
  TimelineStep(t=3, commit="90246a8b986b0dcbcbae6a4f3484204f916afeb5", paths=(("src/foundry/application/semantic_reducer.py", CODE), ("src/foundry/domain/semantic_identity.py", CODE))),
  TimelineStep(t=4, commit="779a66ac90eceaea7eb7d4af0692ee4f167292fc", paths=(("src/foundry/application/semantic_reducer.py", CODE), ("docs/superpowers/specs/2026-09-10-intent-intelligence-v2-design.md", DOCUMENT))),
)
SCOPE = ("intent-engine",)

class VersionedEvidence(FrozenModel): t: int; repo_path: str; artifact_ref: str; commit: str; git_blob_sha: str; content_sha256: str; source_kind; scope; item: EvidenceItem
def load_timeline(reader: GitReader, *, project_id: str, observed_at_for: Callable[[int], datetime]) -> tuple[VersionedEvidence, ...]
    # evidence_id = f"EV-T{t}-{index:02d}"; artifact_ref = f"repo:{path}"; source_ref = f"git://{commit}/{path}";
    # supersedes_evidence_id = the previous VersionedEvidence with the same artifact_ref (linear); scope = SCOPE
def persistent_delta(all_items, t) -> tuple[EvidenceItem, ...]      # items at T whose (artifact_ref, content_sha256) was absent before T
def reconstruction_corpus(all_items, t) -> tuple[EvidenceItem, ...]  # every version with step <= T
```

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_timeline.py` with a `FakeGit` keyed by `(commit, path)`:
  - `test_timeline_is_the_four_approved_commits_and_paths`
  - `test_reads_only_from_named_commits_never_working_tree`
  - `test_lineage_links_versions_of_the_same_artifact_linearly` (spec T1→T2→T4 chain; reducer T3→T4 chain)
  - `test_persistent_delta_excludes_unchanged_artifacts` (constitution absent after T1; an identical-content re-appearance is not a delta)
  - `test_reconstruction_corpus_is_cumulative_all_versions`
  - `test_hashes_recorded_per_version`
- [ ] RED: `ModuleNotFoundError: foundry.experiments.longitudinal.timeline`.
- [ ] Implement → GREEN.

**Review gate:** exact commits/paths from spec §25; no working-tree reads.

---

## Task 11 — Preregistered derivation fixture

**Spec:** §23. **Commit:** `feat: preregister the Track A derivation chain`

### Production change
New `src/foundry/experiments/longitudinal/derivations.py`:
```python
TRACK_A_CHAIN: Final = ("artifact:docs/superpowers/plans/2026-09-11-intent-intelligence-v2-core.md#6.1",
                        "artifact:src/foundry/domain/admission.py",
                        "artifact:tests/unit/test_admission.py")
CONTROL_CHAIN: Final = ("control:D-N1", "control:D-N2")

class LocusSelector(Protocol): def __call__(self, state: IntentState) -> str | None   # returns the T1 claim judgment id for the tracked locus
def attach_preregistered_chains(governor, *, track_a_judgment_id: str, control_root_judgment_id: str) -> tuple[StoredEvent, ...]
    # DERIVATION_RECORDED: D-A1 ← J(C-A1), D-A2 ← D-A1, D-A3 ← D-A2 ; control: D-N1 ← control root, D-N2 ← D-N1
```
**When:** the arm-F runner attaches the chains **after T1 completes and before any T2 evidence is ingested**; Task 12 enforces this with a guard that refuses attachment once any T2 `artifact_ref` version is present in state. **How the root is chosen without post-output tuning:** the root is the T1 `ASSERT_CLAIM` judgment of the address the architect designates as Track A *from T1 state alone*, before T2 runs. The designation is a `T1_locus_designation` entry in `expectations.json` (address id, designated-at timestamp, ledger sequence at designation); the sequence must precede the first T2 `EVIDENCE_INGESTED` event, which Task 17 verifies deterministically. This is a human *selection of which existing T1 address is the tracked locus* — the same act as naming the loci in the sealed manifest — made with no model output from T2 onward visible. It is not semantic reasoning about the model's later proposals, and the architect may not create, bind, or edit anything in doing it. The control root is designated the same way from a constitution-only T1 address.

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_derivations.py`:
  - `test_chains_are_the_approved_ids`
  - `test_attach_records_five_derivation_events_in_order`
  - `test_track_a_supersession_stales_the_three_descendants_and_not_the_control` (drive with reducer: supersede the root; `view.stale_ids ⊇ TRACK_A_CHAIN`; control clean)
  - `test_attach_refuses_if_t2_evidence_already_ingested` (guard on an `artifact_ref` from T2 present in state)
- [ ] RED → GREEN.

**Review gate:** attachment ordering guard is enforced, not documented.

---

## Task 12 — Persistent Arm F runner

**Spec:** §26, §28, §31, §32. **Commit:** `feat: add persistent assimilation arm runner`

### Production change
New `src/foundry/experiments/longitudinal/arm_f.py`:
```python
MAX_F_CALLS: Final[int] = 8
class StepRecord(FrozenModel): t; status: Literal["COMPLETED","FAILED","NOT_RUN"]; evidence_shown; addresses_shown; claims_shown; draft_outputs; judgment_ids; admissions; authorizations: tuple[AuthorizationRecord, ...]; state_snapshot_revision; view: CurrentSemanticView; readiness_by_scope: dict[str, SemanticReadiness]; receipts; error: str | None
class ArmFResult(FrozenModel): steps: tuple[StepRecord, ...]; calls_made: int; ledger: tuple[StoredEvent, ...]; final_state_revision: int

def run_arm_f(*, reasoner, timeline, policy, clock, id_factory, authorizer, track_of, designate_track_a: Callable[[IntentState], str], scopes=("intent-engine","constitution")) -> ArmFResult
    # T0: record_architect_authority
    # T1: assimilate_delta(delta=persistent_delta(1)) ; then designate + attach_preregistered_chains
    # T2..T4: assert no unchanged evidence in delta (structural guard) ; assimilate_delta ; resolve_pending_supersessions
    # any exception at a call → StepRecord FAILED, remaining NOT_RUN, stop; never retry
    # calls_made never exceeds MAX_F_CALLS (assert before each call)
```

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_arm_f.py` (SequencedReasoner scripts for 8 calls; scripted authorizer):
  - `test_arm_f_makes_two_calls_per_t_and_eight_total`
  - `test_t_greater_than_one_receives_delta_only` (constitution never re-sent; recorded `evidence_shown` proves it)
  - `test_chains_attached_after_t1_before_t2`
  - `test_pending_supersession_is_offered_only_after_ai_proposal` (authorizer invoked only when a SUPERSEDE is pending)
  - `test_failure_at_t3_call_two_freezes_and_marks_t4_not_run`
  - `test_tracked_locus_names_never_appear_in_any_request` (scan rendered requests for the sealed track labels)
  - `test_arm_f_ledger_replays_identically`
- [ ] RED → GREEN.

**Review gate:** budget assert; delta-only guard; no retry path exists in source.

---

## Task 13 — Reconstruction Arm R runner

**Spec:** §27, §28. **Commit:** `feat: add fresh reconstruction arm runner`

### Production change
New `src/foundry/experiments/longitudinal/arm_r.py`:
```python
MAX_R_CALLS: Final[int] = 8
class ArmRStep(FrozenModel): t; status; evidence_shown; draft_outputs; judgment_ids; admissions; view; receipts; ledger: tuple[StoredEvent, ...]; error
def run_arm_r(*, reasoner, timeline, policy, clock, id_factory, scope) -> tuple[ArmRStep, ...]
    # per T: fresh InMemoryEventStore + fresh SemanticGovernor (project_id f"PROJ-9P-R-T{t}");
    # ingest reconstruction_corpus(t) (all versions ≤ T, with lineage); assimilate_delta over that corpus as the "delta" with empty state
    # (Call 1 can only CREATE; Call 2 sees created addresses and no known claims → ASSERT only); no authority step
```

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_arm_r.py`:
  - `test_each_t_starts_from_an_empty_ledger`
  - `test_each_t_receives_all_versions_up_to_t` (T2 corpus includes both spec versions)
  - `test_two_calls_per_t_eight_total_same_allowed_kinds_as_arm_f`
  - `test_no_authority_record_and_no_human_path_in_arm_r`
  - `test_same_system_instruction_hash_used_by_both_arms` (compare `SYSTEM_INSTRUCTION_SHA256`)
  - `test_failure_isolates_to_that_t`
- [ ] RED → GREEN.

**Review gate:** R gets ≥ evidence; no persistence leak between T's (assert distinct store instances).

---

## Task 14 — Sealed expectation manifest

**Spec:** §29, §34, 9P-A2. **Commit:** `feat: add sealed lifecycle expectation manifest and verdicts`

### Production change
New `src/foundry/experiments/longitudinal/expectations.py`:
```python
class Verdict(StrEnum): PASS="PASS"; FAIL="FAIL"; NOT_APPLICABLE="NOT_APPLICABLE"
class Expectation(FrozenModel): id: str; text: str; t: str; adjudicator: Literal["architect","deterministic"]; conditional: bool = False
EXPECTATIONS: Final[tuple[Expectation, ...]] = (E1..E11 unconditional, E12 conditional=True)   # texts copied from spec §29 verbatim; no ids, no wording
class ExpectationVerdict(FrozenModel): id: str; verdict: Verdict; adjudicator; evidence_refs: tuple[str, ...]; note: str = ""
    # validator: verdict NOT_APPLICABLE only if the expectation is conditional
class ExpectationManifest(FrozenModel): experiment_version; frozen_code_sha; timeline_hashes; config; expectations; tracked_loci: ("A","B","C") with descriptions from spec §29 (never sent to a model)
def seal(manifest) -> str  # sha256 of canonical JSON
def decision_rule(verdicts, f_tokens_t2_t4, r_tokens_t2_t4, f_material_errors, r_material_errors, declined_any: bool) -> Literal["PASS","FAIL"] + failing ids
    # E1–E9 PASS ∧ E10,E11 PASS ∧ (declined_any → E12 PASS) ∧ f_tokens < r_tokens ∧ f_errors <= r_errors
```

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_expectations.py`:
  - `test_manifest_holds_e1_to_e11_unconditional_and_e12_conditional`
  - `test_not_applicable_is_rejected_for_e1_to_e11` (ValidationError) and accepted for E12
  - `test_decision_rule_gates_e12_only_when_a_decline_occurred` (E12=NOT_APPLICABLE with no decline → PASS; E12=FAIL with decline → FAIL)
  - `test_decision_rule_token_and_error_conditions`
  - `test_seal_is_deterministic_and_changes_on_any_edit`
  - `test_manifest_contains_no_future_runtime_ids` (regex for `ADDR-`, `CLAIM-`, `JDG-` absent)
- [ ] RED → GREEN.

**Review gate:** E1–E11 semantics unchanged from spec; only E12 conditional.

---

## Task 15 — Experiment integrity gates

**Spec:** §28, §31, §32 (13–16). **Commit:** `feat: add longitudinal experiment integrity gates`

### Production change
New `src/foundry/experiments/longitudinal/integrity.py`:
```python
class GateResult(FrozenModel): name: str; passed: bool; detail: str
def preflight(*, git: GitCliLike, frozen_sha: str, manifest_sha: str, expected_manifest_sha: str, prompt_sha: str, expected_prompt_sha: str, timeline, config) -> tuple[GateResult, ...]
    # gates: head_equals_frozen_sha; worktree_clean; manifest_hash_frozen; prompt_hash_frozen; evidence_hashes_frozen;
    #        call_ceiling_is_16; cost_ceiling_is_8; human_ceiling_is_3; judge_calls_zero; xai_retries_disabled (adapter constant);
    #        no_tracked_locus_leakage (render every planned request skeleton; grep track descriptions);
    #        persistent_delta_has_no_unchanged_evidence; reconstruction_corpus_is_cumulative
def all_passed(results) -> bool
```
Any failed gate → the script exits before constructing a reasoner (Task 16).

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_integrity.py` — one test per gate proving both pass and fail detection with a fake git/config; `test_leakage_gate_catches_a_tracked_description_in_a_request`.
- [ ] RED → GREEN.

---

## Task 16 — Immutable artifact schema and script

**Spec:** §31 (accounting), 9O artifact discipline. **Commit:** `feat: add longitudinal experiment artifacts and entry point`

### Production change
New `src/foundry/experiments/longitudinal/artifacts.py` and `scripts/run_longitudinal_dogfood.py`.

Directory: `docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/`

| File | Exists BEFORE live run | Written AFTER |
|---|---|---|
| `manifest.json` (experiment config, frozen sha, timeline hashes, prompt sha, ceilings) | yes — sealed in Task 18 | — |
| `expectations.json` (E1–E12 + tracked loci + `T1_locus_designation` slot) | yes — sealed in Task 18; the designation slot is filled after T1 and before T2 during the live run | updated once |
| `persistent/result.json`, `persistent/ledger.json` | — | yes |
| `reconstruction/T{1..4}-result.json`, `reconstruction/T{1..4}-ledger.json` | — | yes |
| `authorizations.json` (every AGREE/DECLINE with the verbatim proposal) | — | yes |
| `verdicts.json` (deterministic verdicts filled; architect verdicts `null` until adjudicated) | — | yes |
| `report.md` | — | yes |

`write_artifacts` is atomic and refuses to overwrite (as in 9O). The script: parse `--frozen-sha --out`, run `preflight`, STOP on any gate, require `XAI_API_KEY` from env only, build one `XAISemanticReasoner`, run Arm F (interactive authorizer on stdin: `AGREE`/`DECLINE` only), then Arm R, then Task 17 scoring, then write artifacts. Exit non-zero on any non-COMPLETED status. Never prints the key.

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_artifacts.py`:
  - `test_pre_run_files_and_post_run_files_are_the_declared_sets`
  - `test_artifacts_contain_no_secret_and_no_tracked_description_in_prompts_section`
  - `test_write_refuses_overwrite`
  - `test_script_stops_before_reasoner_construction_on_failed_gate` (monkeypatch `XAISemanticReasoner` to raise if constructed)
  - `test_script_stops_without_key` (`XAI_API_KEY_NOT_AVAILABLE`, no reasoner constructed)
- [ ] RED → GREEN.

---

## Task 17 — Replay and deterministic structural scoring

**Spec:** §29 (E10, E11, E12 deterministic parts), §30. **Commit:** `feat: add longitudinal replay and structural scoring`

### Production change
New `src/foundry/experiments/longitudinal/scoring.py`:
```python
def replay_matches(ledger, live_state) -> ReplayResult          # reuse 9O's shape; zero model calls
def structural_metrics(f: ArmFResult, r: tuple[ArmRStep, ...], manifest) -> StructuralMetrics
    # historical_claims_preserved (every T1 claim id still in state); supersession_chain_valid; support_records_replay;
    # pending_governance (ids, satisfied ids); stale_descendants_correct (E6 deterministic part); scope_isolation (E7);
    # e10 (no EQUIVALENT/DISTINCT requested; duplicate-address count deferred to architect); e11 (replay);
    # e12 (conditional: declined_any from authorizations → readiness lists the pending id ∧ no CONFLICTS_WITH without a model judgment)
    # call_counts per arm; token/cost sums per T; persistent_unchanged_reread_count (must be 0); r_rediscovery_counts (addresses per T)
def deterministic_verdicts(metrics) -> tuple[ExpectationVerdict, ...]   # fills E6-part, E7, E10-part, E11, E12; architect ones left null
```
No lexical/descriptor comparison anywhere (test enforces by source scan for `subject ==` / `.facet ==`).

### RED → GREEN
- [ ] Write `tests/unit/test_longitudinal_scoring.py` with synthetic `ArmFResult`/`ArmRStep` fixtures: one test per metric, plus `test_e12_not_applicable_when_no_decline`, `test_e12_fail_when_declined_and_readiness_missing_pending_id`, `test_no_lexical_identity_comparison_in_source`.
- [ ] RED → GREEN.

---

## Integration — full fake lifecycle

**Commit:** `test: prove longitudinal assimilation lifecycle with fakes`

- [ ] Write `tests/integration/test_longitudinal_lifecycle.py`: socket guard; fake git with real-looking versioned texts; scripted reasoner for 16 calls implementing the ideal story (T1 CREATE+ASSERT for A/B; T2 BIND A/B + ASSERT new + SUPERSEDE old ×2; T3 CREATE C + ASSERT defect; T4 BIND C + ASSERT fix + SUPERSEDE); scripted authorizer AGREE×3; assert: E1–E12 deterministic parts, budgets, ledger counts, F delta-only, R cumulative, replay both arms, artifacts written. A second scenario with a DECLINE at Track C asserts E12 applies and `intent-engine` is not ready while `constitution` is ready.
- [ ] GREEN, then full suite.

---

## Task 18 — Freeze implementation (hard boundary)

**Commit:** `feat: freeze 9P longitudinal assimilation implementation`

- [ ] `uv run pytest -v` · `uv run ruff check .` · `uv run mypy src` · `git diff --check` · `uv lock --check` — all clean, no regression versus the 9P-B baseline count.
- [ ] `git diff --stat bacd6093 -- evals src/foundry/evaluation src/foundry/intelligence src/foundry/adapters/intelligence docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood` → **empty**.
- [ ] Generate and commit the **pre-run** artifacts: `manifest.json`, `expectations.json` (sealed hashes recorded inside `manifest.json`), with `frozen_code_sha` = the SHA this commit will have (two-step: commit implementation; then a second commit `chore: seal 9P manifests` carrying the implementation SHA and its own recorded hashes).
- [ ] Record `9P_IMPL_COMMIT` and `9P_SEAL_COMMIT`. Push.
- [ ] **HARD BOUNDARY:** no live call before `9P_SEAL_COMMIT` exists, HEAD equals it, tree is clean.

---

# 9P-LIVE

## Task 19 — Live longitudinal run

**Commit:** `experiment: run incremental semantic assimilation dogfood`

- [ ] Verify `git rev-parse HEAD == 9P_SEAL_COMMIT`, `git status --short` empty, `XAI_API_KEY` present (never printed).
- [ ] `uv run python scripts/run_longitudinal_dogfood.py --frozen-sha $9P_SEAL_COMMIT --out docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal` — preflight gates must all pass or the script exits with no reasoner constructed.
- [ ] Live discipline (from the first external call): no source/test/script/prompt/policy edits; ≤16 calls; ≤3 authorizations, each answered only `AGREE` or `DECLINE` on the verbatim proposal; any failure → artifacts written with the failure status, committed, STOP.
- [ ] After the run: replay both arms (zero calls), deterministic verdicts filled, `report.md` rendered.
- [ ] Commit only the experiment directory; push; record `9P_LIVE_RESULT_COMMIT`.
- [ ] Architect adjudicates E1–E9 (and the E10 duplicate count) into `verdicts.json` in a **separate** commit `docs: adjudicate 9P lifecycle expectations`; the decision rule is then evaluated and recorded.

---

## Planned commit sequence

1. `feat: add immutable evidence version lineage`
2. `feat: add SUPPORTS_CLAIM judgment contract`
3. `feat: apply and derive claim support without mutating claims`
4. `feat: derive satisfied and pending material governance for readiness`
5. `feat: expose bind, support and supersede drafts in the xAI reasoner`
6. `feat: render lifecycle context and frozen 9P system instruction`
7. `feat: add bounded assimilation context assembly`
8. `feat: add incremental assimilation orchestrator`
9. `feat: add agree-or-decline authority protocol for supersession`
10. `feat: load the frozen four-commit Foundry timeline`
11. `feat: preregister the Track A derivation chain`
12. `feat: add persistent assimilation arm runner`
13. `feat: add fresh reconstruction arm runner`
14. `feat: add sealed lifecycle expectation manifest and verdicts`
15. `feat: add longitudinal experiment integrity gates`
16. `feat: add longitudinal experiment artifacts and entry point`
17. `feat: add longitudinal replay and structural scoring`
18. `test: prove longitudinal assimilation lifecycle with fakes`
19. `feat: freeze 9P longitudinal assimilation implementation` + `chore: seal 9P manifests`
20. `experiment: run incremental semantic assimilation dogfood`
21. `docs: adjudicate 9P lifecycle expectations`

---

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §6 lifecycle flow | 7, 8 |
| §7 BIND semantics / §8 BIND vs EQUIVALENT (no EQUIVALENT/DISTINCT in loop) | 5, 7, 8, 12, 17 (E10) |
| §9 candidate lifecycle | 5 (runtime-minted candidate) |
| §10 claim assimilation / §13 correction path | 6, 8 |
| §11–12 SUPPORTS_CLAIM + ClaimSupportRecord + effective evidence | 2, 3 |
| §14 tracks A/B/C | 10, 11, 14, integration |
| §15–16 evidence lineage vs semantic supersession | 1, 10 |
| §17 authority, SATISFIED_BY, decline behaviour, ceilings | 4, 9, 12, 14 |
| §18–19 retrieval ≤200, bounded context | 7 |
| §22 drafts + reference validation | 5, 6 |
| §23 blast radius | 11, 17 |
| §24 scoped readiness + pending_material_judgment_ids | 4, 17 |
| §25 timeline | 10 |
| §26 Arm F / §27 Arm R / §28 fairness | 12, 13, 15 |
| §29 E1–E12 + verdict vocabulary | 14, 17 |
| §30 metrics / §31 accounting / §32 failure modes | 15, 17, 12, 13, 16 |
| §33 T6 deferred | none (no second provider anywhere) |
| §34 hypothesis + decision rule | 14 |
| §35 slice | all |

## Placeholder scan (self-review)
No `TODO`, `TBD`, `similar to`, `appropriate validation`, `handle edge cases`, `implement later`. Deferred items are those the approved spec already marks DEFERRED: the >200 retrieval branch raises `ContextUnsupported` (Task 7), no top-K, no embeddings, no diff deltas, no EQUIVALENT sweeps, no 9Q.

## Type-consistency review
`EvidenceItem.artifact_ref/supersedes_evidence_id` (T1) → used by T7, T10. `SupportsClaimProposal`, `ClaimSupportRecord` (T2) → T3, T5. `effective_evidence` (T3) → T7. `pending_judgment_ids`, `satisfied_by` (T4) → T8, T9, T17. `SemanticReadiness.pending_material_judgment_ids` (T4) → T12, T17. Drafts (T5) → T6. `SYSTEM_INSTRUCTION_SHA256` (T6) → T13, T15. `assemble_*`, `neighborhood_from_decisions`, `ContextUnsupported` (T7) → T8. `assimilate_delta`, `DeltaOutcome` (T8) → T12, T13. `AuthorizationRecord`, `resolve_pending_supersessions`, `record_architect_authority` (T9) → T12. `TIMELINE`, `load_timeline`, `persistent_delta`, `reconstruction_corpus` (T10) → T12, T13, T15. `attach_preregistered_chains` (T11) → T12. `ArmFResult` (T12), `ArmRStep` (T13) → T17. `ExpectationManifest`, `Verdict`, `decision_rule` (T14) → T16, T17. `preflight` (T15) → T16. All pre-existing names referenced (`SemanticGovernor`, `route_judgment`, `derive_view`, `judgment_address_ids`, `GitReader`, `SemanticReasoningReceipt`) exist at `bacd6093`.

## Scope check
No Decision Engine, second provider, embeddings, general Context Compiler, router, Artifact World, UI, or 9Q work appears in any task.

## Execution rulings (Task 9P-C, 2026-09-11)

Recorded by the 9P-C coordinator during execution so that no decision lives only at the
code layer. Each ruling is also named in the commit that carries it. Rulings marked
**ratify** touch experiment semantics and must be confirmed by the architect before
Task 19; the others are execution mechanics.

| # | Where | Ruling |
|---|---|---|
| P1 | T3 | `judgment_address_ids` and `_touched_addresses` attribute a `SUPPORTS_CLAIM` to its claim's address. |
| P5 | T10 | Timeline scope is per path: `FOUNDRY_CONSTITUTION.md` → `("constitution",)`, spec/code → `("intent-engine",)`. Candidate scope is still runtime-derived from cited evidence. |
| P6 | T4 | `SemanticReadiness.semantic_blockers_clear` (no disputed, no stale, no pending material) is added; `ready` keeps its v0 meaning and additionally requires it. |
| R-T4-a | T4 | Three pre-existing tests that asserted whole-view equality after a non-APPLY admission compare the interpretation projection and assert the held id is pending. |
| R-COMMIT-1 | all | Files co-edited by adjacent tasks are committed whole at the earliest task; the message names the ride-along hunks; every ride-along hunk is reviewed before the commit carrying it. |
| R11-a/b/c | T11 | Attach refuses any post-T1 timeline version (id pattern `^EV-T(?!1-)\d+-` or `artifact_ref` lineage), refuses if a designated root is no longer active, and is once-only. |
| R11-d ~~ratify~~ **overturned (9P-C-R1)** | T11 | ~~Root tie-break when an address carries several applied T1 `ASSERT_CLAIM`s: earliest in applied (ledger) order.~~ The root judgment is designated explicitly; see the architect rulings below. |
| R9-a | T9 | A live project-wide `AuthorityRecord` for the architect is required before any ledger write on AGREE (pre-check on freshly replayed state); the post-submit APPLY + HUMAN_AUTHORITY check remains. |
| R9-b **ratify** | T9 | "agree/decline, ≤1 per tracked correction" (spec §26): an answered proposal consumes the track slot and the total budget whether AGREEd or DECLINEd; a declined id is never re-presented. |
| R9-c | T9 | A mid-batch failure raises `AuthorizationHalted` carrying the records completed so far. |
| R12-a/d **ratify** | T11, T12 | Track identification is structural: Tracks A, B, CONTROL are designated after T1 (before T2) and Track C after T3 (before T4) through `designate_root` (instrumentation; never success); chains attach for A and CONTROL only; a pending `SUPERSEDE`'s track is the track whose designated address holds the target claim, otherwise it is not offered (UNTRACKED). |
| R12-b | T12 | The assimilation scope is a required parameter of `run_arm_f`; the entry point passes `intent-engine` and records it in the manifest. |
| R12-c | T12, T13 | Allowed judgment kinds are recorded per forwarded call in both arms (`allowed_kinds_per_call`) through a shared `RequestRecorder`; E10's deterministic half reads them. |
| R12-e **partial (9P-C-R1)** | T12 | Designated addresses must be pairwise distinct. ~~Track C's address must be absent from the view at the end of T2.~~ (rejected; see the architect rulings below). |
| R12-f | T12 | A `KeyboardInterrupt` during a step is recorded as that step's failure; the arm result is returned. |
| R15-a/b | T15 | The leakage gate scans harness-authored text only (system instruction and request skeletons with evidence content replaced by a placeholder), case-insensitively, including backtick-stripped wordings. Evidence bytes are immutable history the model must see. |
| R16-a | T16 | The `t1_locus_designation` slot is filled live through `run_arm_f(on_t1_designations=...)` after the chains attach and before T2 ingest; it holds A, B, CONTROL. Track C's designation lives in `persistent/result.json` with its ledger sequence. |
| R16-b | T16 | An interrupt at a human prompt is recorded as a failed step; artifacts are still written. |
| N-T7-1 ~~ratify~~ **overturned (9P-C-R1)** | T7, T17 | ~~Call 2 includes the evidence versions cited by the neighbourhood's live claims; `persistent_unchanged_reread_count` is measured on the delta and cited re-sends are reported separately.~~ Call 2 raw evidence is the delta only; see the architect rulings below. |
| N-T17-1 **ratify** | T17 | Under a DECLINE, E6 and E7 are recorded FAIL with the reason "never superseded" (spec §29 allows only PASS/FAIL for E1–E11); spec §32 row 9 calls a decline a legitimate outcome — the tension is the spec owner's to resolve. |
| N-T3-1 | T3 | A claim at an address whose CREATE judgment was superseded remains live and supportable (existing substrate definition). Architecture note, no change. |
| R1-sel (9P-C-R1) | T16 | Interactive root selector presentation only: step-2 judgments are listed in applied (ledger) order and the claim value rendering is truncated at 200 characters. Selection is by full judgment id; nothing reaches the ledger, prompts or expectations. |

## Architect rulings on the execution rulings (Task 9P-C-R1, 2026-09-12)

Reviewed by the architect before any live call (external model calls at the time of
review: 0). Where an execution ruling conflicted with the approved spec, the spec won;
the conflicting Task 7 plan wording ("evidence versions cited by those claims' effective
evidence" in Call 2) is superseded by spec §19 and is not to be relied on.

| Execution ruling | Architect ruling |
|---|---|
| R12-a/d | **RATIFIED.** Track identity is structural after human designation: SUPERSEDE target judgment → ASSERT_CLAIM → address → designated Track A/B/C address; anything else is UNTRACKED and never offered. |
| R12-e | **PARTIAL.** Pairwise-distinct designated addresses (A, B, C, CONTROL) **retained** — equality of already-designated durable address ids only, never lexical. "Track C must be new at T3" **rejected**: E8 requires only that C exists after T3 with an INFERRED claim describing the observed defective behaviour; binding the T3 observation to an existing related address is a legitimate persistent-memory outcome and must remain testable. |
| R9-b | **RATIFIED.** AGREE and DECLINE both consume the track slot; A ≤ 1, B ≤ 1, C ≤ 1, total ≤ 3; a declined proposal is never re-presented. |
| R11-d | **OVERTURNED.** Ledger order is not semantic meaning. The semantic blast-radius root is designated explicitly by the architect as an address **and** the active applied `ASSERT_CLAIM` judgment at that address (for Track A: the preregistered old interpretation C-A1; likewise for the control root). `designate_root` validates the pair deterministically (address exists; judgment exists, applied, active, ASSERT_CLAIM, at that address) and never chooses. `attach_preregistered_chains` uses exactly `track_a.judgment_id`; no fallback, no heuristic. Designation sees only the state available at designation time (T1 state for A/B/CONTROL; state through T3 for C); it is instrumentation, not semantic success, authority or frontier assistance. |
| N-T7-1 | **OVERTURNED.** Arm F Call 2 at T>1 receives the same delta raw evidence only, plus neighbourhood addresses and live neighbourhood claims; historical evidence bytes are never re-sent merely because a live claim cites them (spec §19: the persistent arm re-reads ZERO unchanged evidence; live claims and descriptors substitute for raw history). `persistent_unchanged_reread_count` measures the actual requests: any evidence id shown at T>1 outside that T's delta is an UNCHANGED_RAW_EVIDENCE_REREAD; the required invariant for the live run is 0. |
| N-T17-1 | **RATIFIED with clarification.** DECLINE is a legitimate *governance* outcome, not necessarily a successful *experiment* outcome. If Track A never receives an authorized supersession, E6/E7 may FAIL because the preregistered blast-radius transition did not occur. E12 separately verifies that a declined material proposal remains pending, blocks the affected scope and manufactures no deterministic conflict. E6/E7 are not weakened; E12 is unchanged. |
| P5 / R12-b | **RATIFIED.** Assimilation scope `intent-engine`; readiness scopes `intent-engine` and `constitution`; per-path evidence scopes as frozen. |
| R15-a | **RATIFIED.** The leakage gate checks harness-authored instructions, request framing and expectation ids/descriptions outside evidence; a tracked phrase occurring naturally inside immutable historical evidence is not leakage and evidence bytes are never removed from the real model input to pass the scan. |
| R16-a | **RETAINED for 9P only.** The post-T1 designation slot stays outside the sealed expectation payload; it cannot affect prompts or expectation wording; the designations are also in `ArmFResult` and their ordering is verified structurally. Not to be generalised beyond this experiment. |

The old implementation freeze `6f2af281c46827b97e5affd7e322b1508920c56f` and seal
`68b7f0f9b97a835fb6c97948f2de181834b18682` remain in history as the rejected pre-live
freeze; the live run starts from `9P_SEAL_R1_COMMIT`.

## Pre-live environment-invalid attempt (2026-09-12, classified ENVIRONMENT_INVALID_TRANSPORT_ATTEMPT)

- Seal used: `7f0f138fa87c93e15911968aa44160bfe454a6d5` (implementation `e3c416f3bc4939fb6353e7bf4a154ad37fa3d031`); all 13 preflight gates PASS.
- Provider receipts: 0 · input tokens: 0 · output tokens: 0 · cost: $0.00 · no semantic output · no designation (`t1_locus_designation` stayed `null`) · no authorization.
- Transport failure: gRPC `StatusCode.UNAVAILABLE`, "address lookup failed for api.x.ai: DNS query cancelled" — DNS resolution failed before provider contact, for F/T1/Call 1 and for each of R/T1–T4.
- Observed: the detached live process could not resolve `api.x.ai`; a foreground process in the same session resolved it (`104.18.19.80`); GitHub networking succeeded; provider receipts = 0. Working hypothesis: the detached/sandboxed execution context had no usable DNS/network access. This hypothesis does not require a Foundry code fix; the next live attempt runs foreground outside that environment.
- Exposed harness defect (fixed in 9P-C-R2): after an Arm F failure the runner still started Arm R, and Arm R continued to the next T after a failed T — each a further external transport attempt after the first failure.
- The attempt is excluded from the 9P semantic result. Its post-run artifacts were archived outside the repository at `/Users/vineetpandey/Desktop/9p-invalid-transport-attempt-2026-09-12/` and removed from the canonical experiment directory (which again holds only the sealed pre-run files). Archive SHA256 manifest:

```text
c295834f7471e50e8f513eefc40c97fa00f8371c4c91869949c38183579618cd  authorizations.json
b56c4c316b089b4ecbdd5ec4cdefc438480b724abd961056c54c4f249c004e1d  persistent/ledger.json
119dce0bee2fbd3a41f017d476a2f1f537e52d2c091f759c9377a347df1b92ec  persistent/result.json
b753ea174a9a9f28bee3b6eba084a819e4ca3a447e382073a71872b0dabb3eda  reconstruction/T1-ledger.json
5fc65f5c192f936948824b5b5e587154c6773157da5be5606cb689fb537a4094  reconstruction/T1-result.json
e1808201db4f9265414352dd3fb0b01448a94cce34739b6a956df0ab151c879b  reconstruction/T2-ledger.json
9fb22c5a6c99b21029e13ba7a132f2d270cc09531a7ecd46ae80c02c75fc9f07  reconstruction/T2-result.json
e19e548bb29a10e84ff3b441243ae396082aa200c1b914296a7d8bb122708175  reconstruction/T3-ledger.json
8380fcb834fafe23ee79205b4b2cbf4ccdcf0ea5a9108d9753ae792584f8d31d  reconstruction/T3-result.json
1d81ef8c70937cd60168ea7827c0d7c17d5fb2ead4b3c6aec79b719ec680cbbb  reconstruction/T4-ledger.json
afd9c73c222824a14380f8c4d373274d7e401dce682232b3de8b86ed014c1005  reconstruction/T4-result.json
e6b8b01e4c4e6c161ef0917fb9e29f5b697fa31a657ddf0ef59bb802ad2185ea  report.md
d294b3d2a87d450c91a99a4a184e9a47b6eb23f2375d5ef9810696a6eb7d5847  verdicts.json
```

### Architect ruling R2 — global failure law (9P-C-R2)

First FAILED frontier step → record the failure, preserve the current ledger/artifacts, and make NO further call to `SemanticReasoner` in either arm: an Arm F failure at T<n> leaves F T>n and all of Arm R `NOT_RUN`; an Arm R failure at T<n> leaves R T>n `NOT_RUN`. No retry, no fresh call after a failure. Call accounting is the number of requests actually forwarded to the reasoner (a T that fails on Call 1 counts 1), never pre-charged; the pre-T budget check may conservatively require room for two calls.

Execution rulings under R2: **R2-b** — R12-f applies to Arm R as well: a `KeyboardInterrupt` during an Arm R step is recorded as that T's failure (`INTERRUPTED: KeyboardInterrupt`), later T's are `NOT_RUN`, and the arm returns normally so completed R ledgers reach the artifacts. **R2-c** — after a failure in either arm the structural metrics and deterministic verdicts are not computed (symmetrical for F and R); the ledgers and step records are preserved for the architect, and the run status is `FAILED`.
