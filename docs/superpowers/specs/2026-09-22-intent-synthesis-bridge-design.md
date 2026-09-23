# Intent Synthesis Bridge — Design Specification

**Status:** Architecture approved in direction on 2026-09-22 (Approach 2, rulings D1/D6/D7/**D6-R**). **Amended three times:** after review of `30342f13` (C1-C5), of `616bef8b` (C6-C10), and of `9846b76a` (C11-C14), all recorded in §0.

**APPROVED FOR SLICE-1 IMPLEMENTATION PLANNING** on 2026-09-22, after review of `a177052c`. C11-C14 accepted; D6-R remains approved; the reducer-level `CANONICAL` equality safeguard in §10.7 is retained and must **not** be replaced by an `Authority` ordering; the rule that a non-canonical replacement cannot retire or reconcile a `CANONICAL` target is accepted deliberately, with the scope remaining blocked until a `CANONICAL` replacement is authorized.

**General lifecycle principle established by the architect:** *every state capable of blocking delivery must have an explicit legal exit.* This generalizes C6 (stale objects), C7 (replacement without retirement) and C13 (durable decisions that could never be effected), and governs any future state added to this subsystem.

Slice-1 plan: `docs/superpowers/plans/2026-09-22-intent-synthesis-slice-1.md`. **No code exists.** Slice 1 synthesizes `Requirement` only.

**Base branch:** `feat/intent-intelligence-v2`

**Base commit:** `b8cd8272140693972b00adc8129c1dffad583438`

**Predecessor experiment:** `intent-v2-locus-validation-v1` — seal `cd98fbb`, raw run `17cc9f6`, adjudication `b8cd827`.

**Predecessor outcome:** `LOCUS_POLICY_NOT_VALIDATED`. This outcome is permanent. Nothing here re-adjudicates, reinterprets or replaces it. See §27.4.

---

## 0. Amendment record

Corrections applied to `30342f13` after review. Each is load-bearing; none changes the approved direction.

| # | correction | sections |
|---|---|---|
| **C1** | **Crash consistency.** The original §10.5 required 3+N non-atomic appends for one synthesis. `EventStore.append()` is single-event in both adapters, so a crash could leave an `APPLY` with no object, or an object with partial derivation edges — readable provenance without blast-radius provenance, violating I3/I4. Resolved by collapsing object + **all** edges into one event and defining a resumable, exactly-once protocol for the remaining boundaries. | §10.5, **§10.6 (new)**, §12.2, §22, §23, §24, §25 |
| **C2** | **I5 was factually false.** `reducer.py:113-128` *does* mutate the projected object (`lifecycle=SUPERSEDED`, `revision+1`). Immutability belongs to the event log, not the current projection. Corrected; the reducer is **not** changed — analysis (§15.3) finds it architecturally right. | §15.2, **§15.3 (new)**, I5, §25 |
| **C3** | **Intent-object lifecycle and duplicates.** `relates_to_object_id` had no governing semantics, so a repeated equivalent Requirement could silently mint duplicate durable intent. `KnownIntentObject` also exposed `lifecycle` but not semantic staleness, so a stale-but-`ACTIVE` object was indistinguishable from a sound one. Resolved with an explicit `IntentDisposition` vocabulary, a `NO_CHANGE` route, and a runtime-derived `is_stale` signal. | §8, §9, **§9.3 (new)**, §10.4, §16, §24, §25 |
| **C4** | **Basis locus must be runtime-derived, plus basis coverage.** `basis_locus_ids` was untrusted model output; it is now derived by runtime from validated `basis_claim_ids`, under the same trust rule as `scope`. Added a basis semantic-coverage invariant: citing a claim the statement does not represent creates **false-positive staleness**. The §13 example was itself in breach and is fixed. | §9, §13, **§13.2 (new)**, I17, §25 |
| **C5** | **Proposal shape narrowed.** A single generic proposal cannot honestly instantiate ten kinds with required kind-specific fields (`Assumption.risk_level`, `Contract.observable`, `Decision.rationale`, Requirement's materiality/metric/verification). Slice 1 defines exactly one variant, `RequirementSynthesisProposal`, and `allowed_target_kinds == {REQUIREMENT}`. | §9, §17, §26 |

### Second amendment round — corrections to `616bef8b`

| # | correction | sections |
|---|---|---|
| **C6** | **Reconciliation did not clear delivery blocking.** `scoped_stale_object_ids` receives only `(semantic, view, loci)` and has **no access to `state.objects`**, so it cannot filter a stale id whose object was later retired — and `view.stale_ids` is purely derivation-topological, with a superseded judgment staying inactive forever. A reconciled scope was therefore blocked **permanently**: v2 could never become deliverable again. Resolved with a v2-specific blocking-stale calculation backed by durable reconciliation evidence. `domain/handoff.py` is still not touched. | **§15.6 (new)**, §18, I19, §25 |
| **C7** | **`REPLACES_STALE` crash window.** `INTENT_OBJECT_SYNTHESIZED` → `INTENT_OBJECT_RETIRED` as two events meant a crash between them left the proposal marked applied, so `incomplete_proposal_ids` no longer detected the unfinished reconciliation. Resolved by collapsing retirement into the same atomic event via `replaces_object_id`; `INTENT_OBJECT_RETIRED` is **removed** from the design. | §10.5, §10.6, §15.2, I16, I20, §25 |
| **C8** | **Durable ids derived from raw model `proposal_id`.** `event_id` uniqueness is **global** — `uq_intent_events_event_id` carries no `project_id`, and `InMemoryEventStore` uses one process-wide `_event_ids` set. A model-chosen `proposal_id` can repeat across projects, across runs and across retries, and gave an untrusted model influence over durable identity. Resolved with a runtime-owned `synthesis_run_id` and a derived `proposal_instance_id`. | §9.4, §10.6, I21, §25 |
| **C9** | **Authorship was implicit; human authority could be laundered.** Origin was specified but no durable authenticated-author contract existed, leaving open the reading that human-authored basis claims make a model-generated Requirement `HUMAN_STATED`. Resolved by attaching a runtime-owned `ReasonerFingerprint` author to every proposal record and locking the anti-laundering law. | §9.4, §10.1, §10.2, I22, §25 |
| **C10** | **Recovery idempotency wording was wrong.** The spec called `resume_incomplete_synthesis()` idempotent while the test expected a second call to raise `DuplicateEventError`. Recovery is now genuinely idempotent at the operation level; `DuplicateEventError` is demoted to a race backstop. | §10.6, §25 |

### Fourth amendment round — correction to `9a6b38ad`

| # | correction | sections |
|---|---|---|
| **C19** | **A durable decision must be recoverable.** `IntentSynthesisState.decisions` held a bare `IntentSynthesisDecision` — enough to classify lifecycle, but **not** to resume a durable `DECIDED(APPLY)` without re-calling a provider or rescanning raw event history. Recovery must *finish the decision already made*, not reconstruct one from state that has since moved. The plane now holds an `IntentSynthesisDecisionRecord` carrying identity, proposal, author, origin, assigned authority, decision, `decision_event_id` and `decided_at`. **No fifth state plane is added**, and the record deliberately carries **no synthesized object** — `INTENT_OBJECT_SYNTHESIZED` remains the only event that establishes one. | §9.4, **§9.5 (new)**, §10.5, I21, I16, §25 |

### Fifth amendment round — corrections during T4

| # | correction | sections |
|---|---|---|
| **C20** | **The effect must belong to the durable decision.** `INTENT_OBJECT_SYNTHESIZED` was correlated with a decision only by a shared `proposal_instance_id` — a loose label. A durable APPLY decision is the authoritative effect input, so the reducer now requires the object to BE that decision's outcome: deterministic object id, kind, statement, assigned authority, `decided_at` as `created_at`, exact basis equality, runtime-derived scope, provenance pointing back at the decision event, and exactly one `DERIVED_FROM` per basis claim. A decision for statement A can never establish statement B. | §10.5, §15.2, I3, I23 |
| **C21** | **A replacement may not narrow applicability.** Request assembly exposes objects merely "in the current scope", which is not enough for retirement safety: a `("payments",)` replacement retiring a project-wide `()` Requirement would make that intent silently vanish everywhere else. A replacement may retire a target only if its scope **covers** the target's — `()` covers everything, nothing narrower covers `()`, otherwise superset. A structural deletion guard, not routing policy. | §10.7, §15.2, I23 |

**Unchanged and still binding:** Approach 2; `SemanticClaim` atomicity; separate Intent Synthesis altitude; runtime-owned authority; dual provenance; `CanonicalIntentPackage` unchanged; delivery gated on semantic readiness; v1 coexistence; Research → Evidence only; `locus-validation-v1` permanently `LOCUS_POLICY_NOT_VALIDATED`.

### Third amendment round — corrections to `9846b76a`

| # | correction | sections |
|---|---|---|
| **C11** | **Canonical authority was removable by a `PROPOSED` replacement.** A stale `CANONICAL` Requirement could be retired by an `AI_INFERRED` replacement that is `PROPOSED`; the replacement never enters `obligation_ids`, and at `LOW` materiality never blocks closure, so a canonical obligation could **silently disappear** while the scope stayed deliverable. Resolved with a canonical-preservation law enforced at three layers. | **§10.7 (new)**, §9.3, §15.6, I23, §25 |
| **C12** | **Purity did not guarantee the same recovery decision.** §10.6 argued that re-routing after a crash yields the identical decision because `route_intent_synthesis` is pure. False: purity gives identical output only for identical *inputs*, and `AuthorityRecord`s, claim liveness, staleness and related objects can all change between the proposal append and recovery. Resolved by collapsing proposal and admission into **one** `INTENT_SYNTHESIS_DECIDED` event appended at a checked sequence, which removes the decided-with-no-decision state entirely. | §10.5, §10.6, I16, §25 |
| **C13** | **An admitted `APPLY` had no terminal invalidation path.** If a basis claim stopped being live between a durable `APPLY` and its effect, I1 correctly forbids applying — but the proposal then stayed `admitted APPLY, not applied` **forever**, so `incomplete_proposal_ids` never cleared and delivery was permanently blocked. Resolved with `INTENT_SYNTHESIS_INVALIDATED` and a lifecycle invariant — **later refined by C16 into the three-way snapshot partition** I24 now states. (This row describes the pre-C12/C13 design; "admitted" is that design's vocabulary, not the current model's.) | §10.6, **§10.8 (new)**, I24, §25 |
| **C14** | **Only `DuplicateEventError` was handled, not `ConcurrencyError`.** `append()` takes `expected_sequence`, so an unrelated concurrent append raises `ConcurrencyError` with no duplicate id. Recovery must reload, recompute, revalidate and retry under a bounded policy, falling back to C13 invalidation. | §10.6, §23, I25, §25 |

**Ruling refinement recorded (D6-R) — APPROVED by the architect on review of `9846b76a`.** D6's literal wording — *"v2 MUST refuse unless `SemanticReadiness.ready == true`"* — is **provably unsatisfiable after any reconciliation**, for the reason in C6: `SemanticReadiness.ready` embeds the unfiltered stale set, which never clears. Its *substance* is preserved exactly — a stale basis blocks delivery and `evaluate_closure` is unchanged — by gating v2 on a v2-specific readiness that distinguishes **unreconciled** staleness from **historical, validly-reconciled** staleness (§15.6). The architect directed this refinement in review and **explicitly approved it** on review of `9846b76a`; it is recorded here so the change from D6's literal form is visible rather than silent. `domain/handoff.py` stays unchanged and v1's readiness is retained verbatim inside v2 for transparency.

---

## 1. Purpose

The v2 semantic substrate (`SemanticAddress` + atomic `SemanticClaim` + judgments + admission + supersession) and the v0/v1 intent contract (`SemanticObject` + `evaluate_closure` + `CanonicalIntentPackage`) both exist, are both tested, and are **not connected**. `build_intent_package` reads only `state.objects`; it never consults `state.semantic`. The only `SemanticObject` any production path writes today is `AuthorityRecord` (`application/semantic_governance.py:172`). The canonicalization event types — `REQUIREMENT_CANONICALIZED` and its siblings — are wired into the reducer (`application/reducer.py:47-52`) and **emitted by nothing**.

This specification defines the missing edge: a governed **Intent Synthesis** layer turning live atomic claims into typed intent-bearing `SemanticObject`s, so closure and the canonical contract become reachable from evidence.

It exists because of a structural finding. The locus-validation experiment showed that atomic per-proposition claims are correct and the claim lifecycle works, and that *counting claims* is the wrong way to ask whether intent was captured. A document carrying four independent normative facts yields four claims and one human commitment. Those are two altitudes; the system currently has only the lower one.

**Purpose in one sentence:** give Foundry a governed, provenance-bearing, crash-consistent, replayable way to form human-meaningful intent from evidence-backed propositions, without weakening claim atomicity and without creating a second ledger of intent.

---

## 2. Non-goals

This specification does **not**:

1. change `SemanticClaim` cardinality, atomicity, or any part of the validated claim lifecycle;
2. introduce an `IntentUnit` durable type — the intent-bearing `SemanticObject` kinds already occupy that altitude;
3. modify `evaluate_closure` (D6);
4. modify `build_intent_package` or `CanonicalIntentPackage`;
5. modify `IntentDecisionHandoff` v1 or `HANDOFF_VERSION` (D7);
6. modify `EventStore`, `ConcurrencyError`, `DuplicateEventError`, or either adapter (§10.6);
7. modify the `REQUIREMENT_SUPERSEDED` reducer branch (§15.3);
8. design the Research Worker beyond its interaction boundary (§21);
9. change any frozen prompt, policy version, prompt hash, or output-schema hash;
10. alter, re-adjudicate or reinterpret any sealed experiment;
11. decide materiality thresholds or corroboration policy beyond what the architecture already establishes (§28).

---

## 3. Altitude and boundary

The Law of Descent makes altitude separation constitutional, not stylistic.

| | Semantic reasoning (exists, validated) | Intent synthesis (this spec) |
|---|---|---|
| question | *what does this evidence say?* | *what does the human mean / commit to?* |
| unit | one proposition at one locus | one independently meaningful commitment |
| durable output | `SemanticClaim`, `SemanticAddress` | intent-bearing `SemanticObject` |
| vocabulary | `JudgmentKind` (8 members) | `RequirementSynthesisProposal` (separate) |
| governance | `route_judgment` | `route_intent_synthesis` (shared primitives, §10.4) |
| granularity | atomic, per proposition | human-meaningful, may span many claims |

**Boundary law.** Intent synthesis reads the semantic substrate and never writes to it, except `DerivationEdge`s (I14). It emits no `SemanticJudgment`, creates no address, asserts no claim, supersedes no claim, records no `CONFLICTS_WITH`. The semantic reasoner never sees an intent object and never proposes one. `JudgmentKind`, `JudgmentProposal`, `proposal_signature`, `agrees`, `contradicts`, `AdmissionRoute` and `judgment_address_ids` are left byte-unchanged.

**Why not a new `JudgmentKind`.** It would inherit governance free but would widen the most load-bearing module set in the system immediately after the substrate was validated at real cost, and — decisively — would conflate *what a document says* with *what a human means* in one vocabulary. That is the quiet altitude violation the constitution names as the characteristic failure.

**Why not pure deterministic projection.** `domain/semantic_identity.py`: *"Deterministic code cannot originate meaning; it only applies admitted judgments."* Forming a Requirement from claims originates meaning. The only admissible deterministic path is the narrow exemption of §11.

### 3.1 Frozen-artifact compatibility exception (R2, deferred)

`IntentSynthesisResult.gap_proposals` reuses `GapProposal`, whose canonical definition lives in `foundry.intelligence.proposals`. `foundry.domain.intent_synthesis` therefore imports **upward**, from `domain` into `intelligence` — the one place in this codebase where that direction occurs.

**This crosses the layer boundary only because the correct definition site is frozen.** `GapProposal` depends on nothing but `FrozenModel` and `GapKind` and belongs in `domain/gaps.py`. Both endpoints of that relocation are **immutable evidence of the sealed comparative experiment**, listed in `evals/comparative/contestant-freeze.json`:

| file | contestant | frozen sha256 |
|---|---|---|
| `src/foundry/intelligence/proposals.py` | `contestant_a` | `e33a4255…` |
| `src/foundry/domain/gaps.py` | `contestant_b` | `c37e9689…` |

Editing either raises `ExperimentFreezeViolation`. There is no route that both relocates the type and preserves the freeze.

**The standing rules:**

1. The exception exists **only** because both correct relocation endpoints are immutable evidence of a sealed comparative experiment.
2. **Preserving that evidence outranks layering cleanup.** A frozen experiment is the system's record of what was actually measured; a layering inversion is a structural blemish with no effect on behaviour.
3. This is the **only permitted `domain → intelligence` dependency introduced by Intent Synthesis.**
4. It **must not be used as precedent** for another such dependency. Any further cross-layer import is a defect, not an application of this exception.
5. When the comparative freeze no longer constrains those working-tree paths, the intended repair is unchanged: move `GapProposal` to `domain/gaps.py`; re-export it compatibly from `intelligence/proposals.py` so every historical import path keeps working; and make `domain/intent_synthesis.py` depend only on the domain location.
6. R2 is therefore **deferred, not abandoned**, and is **non-blocking for Slice 1**.

`GapProposal` is **not** duplicated, and `gap_proposals` is **not** removed from `IntentSynthesisResult` to dodge the freeze. Runtime behaviour is unchanged by this exception.

---

## 4. Approved flow

```
Evidence
  -> SemanticAddress
  -> atomic SemanticClaims                     [validated; unchanged]
  -> governed Intent Synthesis                 [THIS SPEC]
  -> typed intent-bearing SemanticObjects
  -> governance / authority
  -> closure                                   [evaluate_closure, unchanged]
  -> CanonicalIntentPackage                    [unchanged; the single contract]
  -> IntentDecisionHandoff v2                  [new; readiness-gated]
  -> Planning / Architecture
```

Research (boundary only, §21): `Gap -> Research Job -> EvidenceItem -> normal semantic assimilation -> claims -> Intent Synthesis`. Research has no direct path to canonical intent.

**Intent-bearing kinds (D1), exactly ten:** `Intent`, `Goal`, `Outcome`, `Requirement`, `Constraint`, `NonGoal`, `Preference`, `Decision`, `Assumption`, `Contract`.

`Actor` is **canonical intent context, not an intent-bearing commitment**. It stays in `CanonicalIntentPackage.purpose_ids` unchanged and is **not** a synthesis target (§26).

`Claim`, `Evidence`, `Unknown`, `Question`, `Conflict`, `Risk`, `Metric`, `VerificationObligation`, `AuthorityRecord`, `Amendment` are supporting objects, not synthesis targets here.

---

## 5. Existing primitives retained unchanged

| primitive | location | role |
|---|---|---|
| `SemanticClaim`, `SemanticAddress` | `domain/semantic_identity.py` | the basis; read-only |
| `CurrentSemanticView`, `SemanticLocus` | `domain/semantic_view.py` | live claims, loci, epistemic state, `effective_evidence`, `stale_ids`, `pending_judgment_ids` |
| `DerivationEdge`, `descendants`, `stale_object_ids` | `domain/derivation.py` | blast radius |
| `Relation`, `RelationType.DERIVED_FROM` | `domain/common.py` | readable provenance |
| `Provenance`, `Authority`, `Materiality`, `SourceKind` | `domain/common.py` | origin and authority vocabulary |
| `AuthorityRecord`, `_covering_authority_record` | `domain/semantic.py`, `domain/admission.py` | how human authority enters |
| `Gap`, `GapKind`, `GapStatus` | `domain/gaps.py` | refusal with a reason |
| `GapProposal` | `intelligence/proposals.py` | reused verbatim |
| `evaluate_closure`, `ClosureResult` | `domain/closure.py` | unchanged (D6) |
| `CanonicalIntentPackage`, `build_intent_package` | `application/package.py` | unchanged; the single contract |
| `SemanticReadiness`, `build_semantic_readiness` | `domain/handoff.py` | the v2 emission gate |
| `IntentDecisionHandoff`, `HANDOFF_VERSION` | `domain/handoff.py` | **frozen** (D7) |
| `EventStore`, both adapters | `ports/`, `adapters/` | **unchanged** (§10.6) |
| `REQUIREMENT_SUPERSEDED` reducer branch | `reducer.py:113-128` | **unchanged** (§15.3) |
| `SemanticGovernor.derive()` | `semantic_governance.py:137` | retained for non-synthesis derivations |

---

## 6. New primitives

| new thing | module | kind |
|---|---|---|
| `IntentSynthesisRequest`, `LocusBasis`, `BasisClaim`, `KnownIntentObject` | `ports/intent_synthesizer.py` | request-only |
| `IntentSynthesizer` (Protocol) | `ports/intent_synthesizer.py` | port |
| `IntentSynthesisProposal` (base), `RequirementSynthesisProposal` | `domain/intent_synthesis.py` | proposal vocabulary (C5) |
| `IntentDisposition` | `domain/intent_synthesis.py` | `NEW` / `EXISTING_UNCHANGED` / `REPLACES_STALE` (C3) |
| `IntentSynthesisRoute` | `domain/intent_synthesis.py` | `APPLY` / `NO_CHANGE` / `REQUIRE_SECOND_LENS` / `REQUIRE_HUMAN` / `REJECT` |
| `SynthesisOrigin`, `IntentSynthesisPolicy`, `IntentSynthesisDecision`, `route_intent_synthesis` | `domain/intent_synthesis.py` | governance |
| `IntentSynthesisState`, `incomplete_proposal_ids`, `RetirementRecord` | `domain/intent_synthesis_state.py` | projection, crash detection (C1), reconciliation evidence (C6) |
| `SynthesisIdentity` (`synthesis_run_id`, `proposal_instance_id`) | `domain/intent_synthesis.py` | runtime-owned durable identity (C8) |
| `IntentObjectPayload` | `domain/events.py` | object + `basis_claim_ids` + `replaces_object_id`, one atomic unit (C1, C7) |
| `INTENT_SYNTHESIS_DECIDED`, `INTENT_OBJECT_SYNTHESIZED`, `INTENT_SYNTHESIS_INVALIDATED` | `domain/events.py` | event vocabulary — **three** events: proposal+decision collapsed (C12), retirement folded into the object event (C7), terminal non-applied outcome (C13) |
| `InvalidationReason` | `domain/intent_synthesis.py` | bounded enum: `BASIS_CHANGED` / `TARGET_CHANGED` / `AUTHORITY_CHANGED` (C13) |
| `v2_blocking_stale_object_ids`, `IntentDeliveryReadiness` | `domain/handoff_v2.py` | v2 reconciliation-aware readiness (C6) |
| `IntentDecisionHandoffV2`, `IntentBasisRef` | `domain/handoff_v2.py` | new module; v1 untouched |
| `synthesize_intent`, `resume_incomplete_synthesis` | `application/intent_synthesis.py` | orchestrator + recovery |

`IntentState` gains one additive field, `intent_synthesis: IntentSynthesisState = <empty>`, mirroring exactly how `semantic: SemanticState` was added. Existing event streams replay unchanged because the field defaults to empty.

---

## 7. `IntentSynthesisRequest`

Bounded, scope-limited. The synthesizer is compute, not memory: it never receives `IntentState`, `SemanticState`, `EventStore`, or whole-project context.

```
IntentSynthesisRequest
  project_id: str
  scope: str                                   # exactly one scope
  basis: tuple[LocusBasis, ...]                # min_length=1
  known_intent_objects: tuple[KnownIntentObject, ...]   # §8
  allowed_target_kinds: frozenset[SemanticKind]         # slice 1: {REQUIREMENT}
```

```
LocusBasis                                     # request-only
  locus_representative_id: str
  address_ids: tuple[str, ...]
  subject: str
  facet: str
  live_claims: tuple[BasisClaim, ...]          # min_length=1
  epistemic_state: IssueEpistemicState
```

```
BasisClaim                                     # request-only
  claim_id: str
  predicate: str
  value: ClaimValue
  effective_evidence_ids: tuple[str, ...]      # from view.effective_evidence
  authority: Authority
  source_kinds: tuple[SourceKind, ...]         # of the effective evidence; enables §10.1 origin
```

**Keyed on `locus_representative_id`, never `address_id`** (I12): addresses merged by an active `EQUIVALENT` form one locus, and keying on the representative stops one commitment becoming two objects.

**Construction rules (deterministic, runtime-owned):**
- only claims **live** in `derive_view` at request time may appear;
- only loci whose scope is `()` or contains `scope` — the membership convention `evaluate_closure` and `locus_in_scope` already use;
- a locus that is `DISPUTED` or `OPEN`, carries a pending material judgment, or is stale **is not offered**; it yields a `Gap` deterministically (§16) and never reaches the synthesizer;
- `effective_evidence_ids` come from `view.effective_evidence[claim_id]`, so active `SUPPORTS_CLAIM` records are reflected without mutating any claim.

**Forbidden by construction:** `IntentState`, `SemanticState`, non-live claims, out-of-scope loci, judgment bodies, rationales, event ids.

---

## 8. `KnownIntentObject` — bounded snapshot

**Why it exists.** `id + kind + authority` is insufficient: without minimal semantic content the synthesizer cannot detect that a proposal duplicates, overlaps, extends or conflicts with existing intent, and the system would accumulate near-duplicate commitments (C3).

**Second-ledger fence — load-bearing.** This snapshot carries statement text. It is therefore governed by the law `ComparisonContext` already establishes for request-only context: **temporary reasoning context, never canonical state, never an event payload, never persisted, never returned in a proposal, never part of any handoff or package.** Compiled fresh for one request and discarded. Durable truth remains `state.objects`; the snapshot is a read-through projection with no identity.

```
KnownIntentObject                              # request-only; NEVER persisted
  object_id: str
  kind: SemanticKind
  authority: Authority
  lifecycle: LifecycleStatus
  is_stale: bool                                # C3 — runtime-derived, see below
  scope: tuple[str, ...]
  statement: str
  materiality: Materiality | None               # Requirement only
  basis_claim_ids: tuple[str, ...]
  basis_locus_ids: tuple[str, ...]
```

**`is_stale` is the C3 fix and is runtime-derived, never stored on the object:**

```
is_stale := object_id in derive_view(state.semantic).stale_ids
```

A derived Requirement remains `lifecycle == ACTIVE` while its semantic basis is superseded; `lifecycle` alone therefore cannot distinguish a sound current object from one awaiting reconciliation. Without `is_stale` the synthesizer would treat a stale object as authoritative and return `EXISTING_UNCHANGED`, permanently freezing a commitment whose basis has been corrected. `is_stale` is what makes `REPLACES_STALE` (§9.3) decidable.

**`statement` field per kind** (the one human-readable field already on the model; nothing is invented):

| kind | field |
|---|---|
| `Intent` | `mission` |
| `Requirement`, `Goal`, `Outcome`, `NonGoal`, `Preference`, `Constraint`, `Assumption`, `Contract` | `statement` |
| `Decision` | `statement` (**not** `rationale` — rationale is reasoning, excluded) |

**Bounds:** only `_is_current` objects (lifecycle `ACTIVE`, authority not `REJECTED`/`SUPERSEDED`) in scope. Rationale, provenance, relations other than basis ids, revision, timestamps and confidence are excluded. The snapshot is capped; an over-cap request is a refusal (§23), never a silent truncation. The numeric cap is D9.

---

## 9. Proposal and result

### 9.1 Narrowed shape (C5)

A single generic proposal cannot honestly instantiate ten kinds, because the domain types carry **required** kind-specific fields: `Assumption.risk_level`, `Contract.observable`, `Decision.rationale` (verified: `domain/semantic.py:99-167`), plus Requirement's materiality/metric/verification fields. A generic schema would either be unconstructable or pad itself with speculative optionals that lie about what is supported.

**Slice 1 defines exactly one variant.** Additional kinds require their own variant and their own design before entering `allowed_target_kinds`.

```
IntentSynthesisProposal                        # base — shared fields only
  model_proposal_id: str                          # model-local ONLY; never durable (§9.4)
  target_kind: SemanticKind
  disposition: IntentDisposition                # C3, §9.3
  statement: str
  rationale: str                                # concise; never chain-of-thought
  basis_claim_ids: tuple[str, ...]              # min_length=1
  relates_to_object_id: str | None              # required when disposition != NEW
  confidence: float | None                      # metadata; no rule reads it
```

```
RequirementSynthesisProposal(IntentSynthesisProposal)   # the ONLY slice-1 variant
  target_kind: Literal[SemanticKind.REQUIREMENT]
```

```
IntentSynthesisResult
  proposals: tuple[RequirementSynthesisProposal, ...]
  gap_proposals: tuple[GapProposal, ...]        # existing type, reused verbatim
```

`GapProposal` is imported from `foundry.intelligence.proposals` under the frozen-artifact compatibility exception of **§3.1** — the sole authorized `domain → intelligence` dependency, deferred rather than abandoned.

### 9.2 What the synthesizer cannot express

The schema **cannot** carry: `authority`, `author` (C9), `basis_locus_ids` (C4), `synthesis_run_id` or `proposal_instance_id` (C8), object id, `project_id`, `scope`, `provenance`, `relations`, `lifecycle`, `revision`, `created_at`, `materiality`, `requires_metric`, `requires_verification`, judgment ids, event ids. Runtime owns every one. This mirrors the 9O trust boundary verbatim and is why an authority-invention bug cannot originate in the model.

**Runtime-derived fields:**

| field | derivation |
|---|---|
| `object_id` | **deterministic function of `proposal_instance_id`** — never of the raw `model_proposal_id` (§9.4, C8) |
| `author` | the synthesizer's or authenticated human's `ReasonerFingerprint`, attached by runtime (§9.4, C9) |
| `basis_locus_ids` | **C4** — `{ representative_of(claims[cid].address_id) for cid in basis_claim_ids }`, from the current view |
| `scope` | union of the basis claims' address scopes — never chosen by the synthesizer (I6) |
| `authority` | origin (§10.2) |
| `provenance` | origin (§12.4) |
| `relations` | one `DERIVED_FROM` per basis claim (§12.1) |
| `materiality`, `requires_metric`, `requires_verification` | slice-1 pinning §17.4; general policy is D4 |

**Why `basis_locus_ids` moved to runtime (C4).** It is a structural fact Foundry already knows: given validated `basis_claim_ids`, the locus set is a pure lookup through `claims[cid].address_id` and the view's representatives. Accepting it from an untrusted source would let a model's mistaken locus attribution silently misdirect scope derivation and blast-radius attribution. Same trust rule as `scope`: **structural facts Foundry already knows are runtime-owned.**

### 9.3 `IntentDisposition` (C3)

`relates_to_object_id` previously had no governing semantics, so a repeated equivalent Requirement could silently mint duplicate durable intent. Lifecycle semantics must be explicit, not buried in free text.

| disposition | meaning | `relates_to_object_id` | durable effect |
|---|---|---|---|
| `NEW` | no current object represents this meaning | must be `None` | mint a new object |
| `EXISTING_UNCHANGED` | already represented by a current, **non-stale** object | **required** | **none** — route `NO_CHANGE`; no object minted |
| `REPLACES_STALE` | reconciles a currently **stale** object | **required**, and it must be stale | mint replacement **and** retire the named target |

**Validation, enforced by runtime before routing:**
- `NEW` with a `relates_to_object_id` → structural failure;
- `EXISTING_UNCHANGED` or `REPLACES_STALE` without one → structural failure;
- `relates_to_object_id` not in `known_intent_objects` → structural failure;
- `REPLACES_STALE` naming an object whose `is_stale` is false → structural failure;
- `EXISTING_UNCHANGED` naming an object whose `is_stale` is **true** → structural failure (a stale object may not be affirmed as current; it must be reconciled or refused);
- `REPLACES_STALE` naming a `CANONICAL` object when the replacement's runtime-assigned authority is not `CANONICAL` → the retirement must not apply (§10.7, C11). The proposal survives as a proposal; the canonical target stays live, stale and blocking.

`EXISTING_UNCHANGED` is a **success**, not a rejection: the correct outcome is that no duplicate intent is created. It is recorded as one `INTENT_SYNTHESIS_DECIDED` event carrying the proposal and the `NO_CHANGE` decision (there is no separate proposal/admission lifecycle after C12), so the outcome is auditable; no object is synthesized, and it writes no relation and no derivation edge.

`REPLACES_STALE` retires **exactly** the named object (§15.2) — never a sibling, never "the newest stale one" (I18).

Disposition is the synthesizer's *proposal*; runtime validates it against `is_stale` and the known set. The synthesizer cannot assert staleness — it is told.

### 9.4 Durable identity and authorship (C8, C9)

Both are runtime-owned. Neither is expressible by the synthesizer.

#### Identity — the raw model id is never durable

`event_id` uniqueness is **global**, not per project: `uq_intent_events_event_id` carries no `project_id` (`migrations/versions/0001_event_streams.py:33`) and `InMemoryEventStore` keeps one process-wide `_event_ids` set. A model-chosen `model_proposal_id` can therefore repeat across projects, across synthesis runs within one project, and across retries — and deriving durable ids from it would hand an untrusted model influence over durable identity.

```
synthesis_run_id      runtime-owned, one per synthesize_intent invocation,
                      from an injected factory; PERSISTED in
                      INTENT_SYNTHESIS_DECIDED so recovery can read it back
model_proposal_id     model-local only; meaningful ONLY within one result
proposal_instance_id  = deterministic(project_id, synthesis_run_id, model_proposal_id)
object_id             = f(proposal_instance_id)
event_id              = f(proposal_instance_id, step)
```

**Digest construction (T1.2).** The deterministic function hashes a **canonical JSON array** of its components, never a separator-joined string: `model_proposal_id` is untrusted, and a bare `a|b` join lets a crafted id shift a boundary so that `("P|R","X","Y")`, `("P","R|X","Y")` and `("P","R","X|Y")` all collapse to one digest — a forgeable collision. It returns the **full 64-hex SHA-256**, never a truncation: having removed boundary forgery through the encoding, discarding most of the digest would reintroduce birthday-collision headroom on ids that are globally unique and partly attacker-influenced. `semantic_reducer._minted_id` is a separate path with runtime-owned inputs and is unchanged.

**Mandatory invariants (I21):**
- the raw `model_proposal_id` is **never** a globally durable identity by itself;
- ids cannot collide across projects — `project_id` is in the derivation;
- ids cannot collide across separate synthesis runs in one project — `synthesis_run_id` is in the derivation;
- **the same interrupted run reproduces the same ids**, because `synthesis_run_id` is persisted in `INTENT_SYNTHESIS_DECIDED` and read back by recovery;
- **retry or recovery never requires another provider call** — every input to the derivation is already durable.

`model_proposal_id` must be unique **within one result**; a duplicate is a structural failure for the whole result (§23), following the `_reject_duplicate` precedent in `intelligence/validation.py`.

#### Authorship — human authority is never laundered

```
author: ReasonerFingerprint      # attached by runtime, never by the model
```

`ReasonerFingerprint` is reused rather than re-invented, because it already provides exactly what is needed: `provider="human"` with the actor id in `model` (`human://alice`) is the shape `_covering_authority_record` already keys on (`obj.authorized_by == judgment.reasoner.model`, `admission.py:347`); `is_human` already exists; and `independent()` already implements the independence rule D3 will need, so future corroboration has durable author identity to test.

> **Anti-laundering law.** Origin is determined by the **author of the synthesis proposal**, never by the authority or provenance of its basis claims. Human-authored, `CANONICAL` basis claims do **not** make a model-generated Requirement `HUMAN_STATED`. Any proposal produced by a non-human `IntentSynthesizer` is `AI_INFERRED` — or `RESEARCH_DERIVED` where applicable — regardless of what its basis rests on.

`HUMAN_STATED` means the human explicitly authored or explicitly affirmed the semantics of **that synthesis proposal**. It requires both `author.is_human` and an authenticated `human_actor_id == author.model`, validated exactly as `SemanticGovernor._require_actor` validates today. A non-human author with a supplied `human_actor_id`, or a human author without one, is a structural failure.

Enforcement mirrors `propose_and_submit`: runtime attaches `author = synthesizer.fingerprint` for every proposal in a batch, and the batch is checked before anything is recorded. The model cannot choose, spoof or influence it (I22).

### 9.5 The durable decision record (C19)

```
IntentSynthesisDecisionRecord
  identity: SynthesisIdentity              # the (project, run, model_proposal_id) triple
  proposal: RequirementSynthesisProposal   # the meaning, verbatim
  author: ReasonerFingerprint              # runtime-owned
  origin: SynthesisOrigin                  # runtime-owned; follows the AUTHOR, never the basis
  assigned_authority: Authority | None     # runtime-owned; None when none was assigned
  decision: IntentSynthesisDecision        # route + reasons, exactly as recorded
  decision_event_id: str                   # from the envelope's event_id
  decided_at: datetime                     # from the envelope's occurred_at
```

**Why each field is durable.** Recovery must *complete* a decision, not re-derive it. The proposal body must not require a provider call; origin must not be recomputed from evidence that may have evolved; `assigned_authority` must not be recomputed under later routing or policy state; `decision_event_id` gives exact provenance; and `decided_at` stops recovery minting a different `created_at` merely because it ran later.

**Identity coherence, enforced (T2.2).** The record must cohere on **both** axes; the second is not implied by the first:

```
mapping key  ==  identity.proposal_instance_id  ==  decision.proposal_instance_id
identity.model_proposal_id  ==  proposal.model_proposal_id
```

The durable-id chain alone is insufficient. Without the second agreement a malformed record could pair the identity and decision of proposal A with the **body** of proposal B: every durable id would agree, nothing downstream would notice, and recovery would faithfully execute the wrong meaning under an entirely valid durable identity. `decision_event_id` is additionally non-empty.

`incomplete_proposal_ids` reads `record.decision.route` and preserves projection order unchanged.

**Boundary.** The record carries **no synthesized object** — the object does not exist at decision time. It is the durable *effect input*, never a prematurely applied object.

**T3 payload consequence.** `INTENT_SYNTHESIS_DECIDED` must carry enough for T4 to reconstruct this record with **no external lookup**: proposal, author, identity, origin, assigned authority and decision. The envelope supplies the rest — `event_id` → `decision_event_id`, `occurred_at` → `decided_at` — and those two are taken from the envelope, **never accepted from a synthesizer**. T4 projects the resulting record into `state.intent_synthesis.decisions`, which is what makes recovery state-derived and replay-derived rather than a search through raw event history.

---

## 10. Governance and authority law

### 10.1 Origin

```
SynthesisOrigin = HUMAN_STATED | DETERMINISTIC_NORMALIZATION | AI_INFERRED | RESEARCH_DERIVED
```

Determined by **runtime from the proposal's `author`** (§9.4), never claimed by the synthesizer and **never inferred from the basis** (C9):

- `HUMAN_STATED` — `author.is_human` **and** an authenticated `human_actor_id == author.model`, exactly as `SemanticGovernor.submit(..., human_actor_id=...)` requires. The human explicitly authored or affirmed the semantics of *this* proposal.
- `DETERMINISTIC_NORMALIZATION` — runtime code under §11. No synthesizer involved.
- `AI_INFERRED` — a non-human `IntentSynthesizer` author. **Always**, regardless of basis authority or provenance.
- `RESEARCH_DERIVED` — an `AI_INFERRED` proposal **all** of whose basis claims rest solely on `SourceKind.RESEARCH` evidence. Computed from `BasisClaim.source_kinds`; never stored, always derivable (§12.4).

There is no rule, at any policy setting, by which the authority of a basis claim contributes to the origin of a proposal. Origin is a fact about *who wrote the statement*, not about *what the statement rests on*.

### 10.2 Authority assignment (runtime, by origin)

| origin | authority | route |
|---|---|---|
| `HUMAN_STATED` **with** covering `AuthorityRecord` | `CANONICAL` | `APPLY` (`HUMAN_AUTHORITY`) |
| `HUMAN_STATED` **without** | none assigned | `REQUIRE_HUMAN` (`AUTHORITY_UNRESOLVED`); nothing written |
| `DETERMINISTIC_NORMALIZATION` | **inherits** source authority and provenance | `APPLY` only if §11 holds; else `REJECT` |
| `AI_INFERRED` | `PROPOSED` | per policy (§10.4) |
| `RESEARCH_DERIVED` | `PROPOSED` | per policy; never privileged over `AI_INFERRED` |

`CANONICAL` is reachable **only** from `HUMAN_STATED` with a covering `AuthorityRecord`, or by §11 inheritance. No other path exists at any policy setting. In particular, an `AI_INFERRED` proposal over a `CANONICAL`, human-provenanced basis claim is `PROPOSED` — the basis does not raise it (C9, I22).

### 10.3 Anti-invention guard — mandatory, with its reason

`admission._authority_invention` is hardcoded to `AssertClaimProposal` (`domain/admission.py:364`) and therefore protects no new proposal type. Without an equivalent guard a synthesis proposal carrying `CANONICAL` would fall through to the low-risk rule and be applied with no human anywhere.

`route_intent_synthesis` must implement, before every other rule:

> A proposal whose origin is not `HUMAN_STATED` (or a valid §11 inheritance) and whose assigned authority is `CANONICAL` is `REJECT` with reason `AUTHORITY_INVENTION`.

**Defence in depth, deliberately redundant with §9.2:** the schema already makes the condition unreachable from a model. The guard exists so a runtime bug in §10.2, or a future refactor, fails **closed**.

**How this is tested without weakening the schema (C17).** The negative control must **not** add an `authority` field to `RequirementSynthesisProposal` in order to become constructible — that would destroy the §9.2 property it is meant to protect. Authority is a **runtime-assigned routing input**, not a proposal field, so the illegal case is constructed at that layer: the routing input (or the internally constructed decision) is given `origin != HUMAN_STATED` with `authority = CANONICAL`, simulating a §10.2 bug. Two assertions, together:

1. the model-facing proposal schema **still forbids authority entirely** — `RequirementSynthesisProposal` rejects it (`extra="forbid"`);
2. an internally mis-assigned `CANONICAL` on a non-human origin is `REJECT` / `AUTHORITY_INVENTION` and never reaches a low-risk route.

Invariant I2 covers both halves.

### 10.4 Policy, disposition routing, and shared helpers

```
IntentSynthesisPolicy
  material_target_kinds: frozenset[SemanticKind]
  material_materiality_levels: frozenset[Materiality]
  canonical_requires_authority: bool = True
```

A **material** proposal requires a covering `AuthorityRecord` or independent corroboration, else routes `REQUIRE_SECOND_LENS` — the shape `route_judgment` rule 7 already uses. Independence uses the existing `ReasonerFingerprint.independent()`; a proposal from the same fingerprint never corroborates itself.

A proposal with disposition `EXISTING_UNCHANGED` routes `NO_CHANGE` **before** any materiality consideration: nothing durable is written, so no authority is required (§9.3).

`confidence` is metadata; no routing rule reads it — the law `route_judgment` already enforces.

**General policy values are D3 and are not set here.** §17.4 pins a conservative slice-1 setting.

**Shared helpers are extracted, never duplicated.** `route_intent_synthesis` reuses the authority-coverage and independence logic `route_judgment` already implements (`_covering_authority_record`, `independent()`), currently private to `domain/admission.py`. These must be **lifted into a shared, tested location and called by both routers**. Two governance paths are acceptable; two divergent copies of the authority-coverage rule are not — a drifted copy is an authority bug neither side's tests would catch. Duplicated routing logic is a review defect.

### 10.5 Governed path and event vocabulary (revised for C1)

```
for each proposal:
    (1) N := store.current_sequence(project)
        decision := route_intent_synthesis(state_at_N, proposal, origin, policy)
        INTENT_SYNTHESIS_DECIDED   proposal + author + identity + decision,
                                   appended with expected_sequence = N
        -> ConcurrencyError: reload, recompute, retry (bounded, §10.6).
           NOTHING is durable until this append succeeds.
    (2) if decision.route == APPLY:
            revalidate preconditions against current state
            if still valid:
                INTENT_OBJECT_SYNTHESIZED   ONE event: the object, EVERY derivation
                                            edge, AND (for REPLACES_STALE) the
                                            retirement of the target
            else:
                INTENT_SYNTHESIS_INVALIDATED  terminal non-applied outcome (§10.8)
        if decision.route == NO_CHANGE / REJECT / REQUIRE_*:
            (nothing further — the decision is the whole outcome)
for each gap_proposal:
    GAP_RECORDED   (or AMBIGUITY_DETECTED for GapKind.AMBIGUITY)
```

**Proposal and decision are one event (C12).** Separating them created a durable `PROPOSED`-with-no-decision state whose only completion was to re-route later — and the earlier claim that purity made that re-route safe was **wrong**: `route_intent_synthesis` is pure, but its *inputs* are current state, and `AuthorityRecord`s, claim liveness, staleness and related objects can all change between the two appends. Purity guarantees identical output only for identical inputs. Computing the decision against sequence `N` and appending at `expected_sequence = N` makes the decision and the state it was computed from **the same durable fact**: if anything intervened, `ConcurrencyError` fires and the decision is recomputed *before* it is durable. The recovery state disappears rather than being reasoned about.

The proposal is still **always recorded**, whatever the route — it rides inside the decision event — so a `REJECT` leaves it readable with canonical state untouched, the guarantee `submit` already gives.

**Retirement is not a separate event (C7).** An `INTENT_OBJECT_RETIRED` following `INTENT_OBJECT_SYNTHESIZED` would reopen precisely the window C1 closed: a crash between the two would leave the replacement applied — so `proposal_instance_id` is already in `applied_proposal_ids` and `incomplete_proposal_ids` no longer reports it — while the required retirement is missing. The design therefore has **no persistence boundary at which a replacement is complete but its retirement is not.**

A proposal is **always recorded**, whatever the route. `REJECT` leaves it readable with canonical state untouched — the guarantee `submit` already gives.

**`IntentObjectPayload` — the atomicity primitive (C1):**

```
IntentObjectPayload
  object: SemanticObject                        # one of the ten intent-bearing kinds
  basis_claim_ids: tuple[str, ...]              # min_length=1
  replaces_object_id: str | None                # set iff disposition == REPLACES_STALE (C7)
  proposal_instance_id: str                     # runtime-owned durable id (C8)
```

The reducer, applying `INTENT_OBJECT_SYNTHESIZED`, writes **in one indivisible step**:
1. `objects[object.id] = object` (relations already carry one `DERIVED_FROM` per basis claim);
2. for each `cid` in `basis_claim_ids`, `DerivationEdge(child_id=object.id, parent_id=state.semantic.claims[cid].created_by_judgment_id)` appended to `semantic.derivations`;
3. **if `replaces_object_id` is set (C7):** retire exactly that object — `model_copy(update={"lifecycle": SUPERSEDED, "revision": old.revision + 1})`, mirroring the existing `REQUIREMENT_SUPERSEDED` branch — and append a `RetirementRecord(retired_object_id, replaced_by_object_id=object.id, proposal_instance_id, recorded_by_event_id)` to `intent_synthesis.retirements`;
4. `intent_synthesis.applied_proposal_ids += (proposal_instance_id,)`.

Steps 1-4 are one event, one `append()`, one transaction.

**Effect/decision binding (C20).** `proposal_instance_id` is not a loose correlation label: the reducer requires the synthesized object to be the outcome of the already-durable `IntentSynthesisDecisionRecord`. Object id, kind, statement, authority, `created_at`, basis, scope, provenance and relations must all match what was decided, and the decision must be a live `APPLY` that is neither applied nor invalidated.

**Scope preservation (C21).** A replacement may retire a target only if the replacement's applicability **covers** the target's: `()` (project-wide) covers everything, nothing narrower covers `()`, and otherwise the target's scopes must be a subset of the replacement's. A narrower replacement cannot delete broader intent.

**Reducer validation is structural only.** The semantic precondition — that the target is genuinely stale — is decided at routing time (§9.3), where the decision is recorded. The reducer applies rather than re-decides, so replay stays deterministic and cheap, and it never re-derives a view. It rejects only structural impossibilities: `replaces_object_id` absent from `objects`, not `_is_current`, out of scope, or already retired. Any of these makes the event unreplayable and `SemanticGovernor._append`'s existing dry-run refuses it before it can reach the ledger.

The edge parents are **derived by the reducer** from state, not carried in the payload — deterministic, replay-exact, and impossible to desynchronise from the claims. A missing claim makes the event unreplayable and it is refused by `SemanticGovernor._append`'s existing dry-run before it can reach the ledger.

**Why one neutral event name.** `SEMANTIC_OBJECT_RECORDED` rejects specialized kinds (`GENERIC_SEMANTIC_KINDS`), and the specialized events are named for canonicalization, so recording a `PROPOSED` Requirement through `REQUIREMENT_CANONICALIZED` would make the ledger say something untrue. `INTENT_OBJECT_SYNTHESIZED` is authority-neutral and honest for both `CANONICAL` and `PROPOSED` (I15). The existing specialized events remain for non-synthesized objects (direct human authoring with no claim basis) and are untouched.

### 10.6 Crash-consistency law (C1, new)

**The hazard.** `EventStore.append()` is one event per transaction in both adapters (`adapters/memory/event_store.py`, `adapters/postgres/event_store.py` — the latter wraps exactly one event in `engine.begin()`). There is no batch API. The original design's 3+N appends could therefore be interrupted mid-sequence, leaving an `APPLY` with no object, or an object with some or none of its derivation edges — readable provenance without blast-radius provenance, which is a *correct-looking but unsafe* ledger and a direct I3/I4 violation.

This hazard is **pre-existing, not introduced here**: `SemanticGovernor.submit()` already appends `SEMANTIC_JUDGMENT_RECORDED` and `SEMANTIC_ADMISSION_DECIDED` non-atomically. The architecture already tolerates the resulting partial state deliberately — `admission._is_lens` treats `admission is None` as a valid lens (`domain/admission.py:433-438`). **That tolerance is the precedent this law builds on**, and it is why the answer is a protocol rather than a transaction.

**Option A — widen `EventStore` with an atomic batch append.** Rejected. It changes a port and both adapters for a problem that already exists in `submit()` and would remain unsolved there; it makes every future adapter carry a stronger contract; and it is unnecessary once the N+1 collapse below removes the only genuinely unsafe partial state. The instruction not to casually widen `EventStore` is met.

**Option B — selected: collapse, then resume.** Two mechanisms:

**B1 — Collapse (removes the dangerous state by construction).** Object + *all* derivation edges ride **one** event (§10.5). One event is one `append()` is one transaction. A partial object/edge state is therefore **unrepresentable**, not merely unlikely. This alone discharges the I3/I4 hazard.

**B2 — Resumable, exactly-once protocol (for the one remaining boundary).**

**After C12 there is exactly one interruption window**, and it is benign and detectable:

| interrupted | resulting state | safe? | completion |
|---|---|---|---|
| before `DECIDED` lands | nothing durable at all | yes — no decision exists | recompute from scratch; no recovery needed |
| after `DECIDED(APPLY)`, before `SYNTHESIZED` / `INVALIDATED` | decision to apply with no effect | yes but **incomplete** — a legal non-terminal state; must not be delivered | revalidate, then `SYNTHESIZED` **or** `INVALIDATED` (§10.8) |

The former `PROPOSED`-without-decision window **no longer exists** (C12), so the false purity argument that justified it is gone with it.

**There is no window for `REPLACES_STALE` either (C7).** Because retirement rides inside `SYNTHESIZED`, a replacement is either fully applied — object, edges, retirement, retirement record, completion marker — or not applied at all. The state "replacement exists, target still live" is unrepresentable, so `incomplete_proposal_ids` can never under-report an unfinished reconciliation.

Three requirements make completion exactly-once:

1. **Runtime-owned deterministic ids (C8).** `object_id` and every `event_id` derive from `proposal_instance_id` — itself derived from `(project_id, synthesis_run_id, model_proposal_id)` (§9.4) — never from the raw model id. `synthesis_run_id` is persisted in the `INTENT_SYNTHESIS_DECIDED` event, so an interrupted run reproduces byte-identical ids on recovery **without another provider call**. No random id factory is used on the synthesis path.
2. **Race backstop.** Because ids are deterministic, a *concurrent* completion attempt raises the existing `DuplicateEventError` (enforced in both adapters before the sequence check). This is a backstop against two workers racing, **not** the idempotence mechanism — see below.
3. **The decision is never recomputed after it is durable (C12).** Recovery does **not** re-route. It reads the recorded decision and either effects it or terminally invalidates it (§10.8). Purity is therefore not load-bearing for recovery correctness — and the spec no longer claims it is. Purity remains valuable for replay and testability, not as a safety argument across time.

**Detection.** `incomplete_proposal_ids(state)` is a pure derived function, **defined once in §10.8** and not restated here. It reads `intent_synthesis.decisions` and excludes both applied and invalidated proposals. (An earlier formulation over `intent_synthesis.admissions` that omitted invalidation predated C12/C13 and is removed: §10.8 is the single source.)

**Non-deliverability.** `IntentDecisionHandoff v2` **refuses** while any in-scope proposal is incomplete (§18), alongside the readiness gate. An incomplete synthesis can therefore never reach Planning or Architecture.

**Recovery (C10).** `resume_incomplete_synthesis(...)` is **genuinely idempotent at the operation level**:

1. reload current state from the event store;
2. compute `incomplete_proposal_ids`;
3. complete **only** the missing work;
4. if nothing is incomplete, return a **no-op success** — not an exception;
5. if a concurrent worker completes **the same** item between the read and the write, the resulting `DuplicateEventError` is **caught internally**, state is reloaded, and the item is treated as already-done — success, not an error surfaced to the caller;
6. if an **unrelated** event is appended between the read and the write, `append()` raises `ConcurrencyError` — no duplicate id is involved — and recovery must (C14): **reload → recompute the incomplete set → revalidate apply preconditions → retry if still valid → otherwise take the §10.8 terminal invalidation path.**

**Bounded retry (C14).** Retries are bounded by a named constant, not unbounded spinning. The codebase's only precedent for a bounded attempt policy is `MAX_ATTEMPTS_PER_CASE = 2` (`evaluation/phase2_runner.py:108`); synthesis retries are cheaper — no provider call, pure recomputation — so a small bound above that is appropriate and must be a named constant, never a magic number. On exhaustion:
- at the `DECIDED` step, nothing is durable, so recovery raises a typed error and the caller may retry later — no state is left behind;
- at the `SYNTHESIZED` step, the proposal simply remains **incomplete**: detectable, non-deliverable, and retried by the next recovery run. Contention can delay completion; it can never corrupt state or silently drop work.

A second call after completion is therefore a no-op success. `DuplicateEventError` is a race-safety backstop and is never the mechanism by which idempotence is achieved; the earlier wording, which called recovery idempotent while the test expected the second call to raise, was contradictory and is corrected here.

Recovery makes **no provider call** and takes **no new decision** — it only finishes a decision already recorded.

**Testing obligation (non-negotiable).** Interruption tests at **every** persistence boundary: after (1), after (2), and — as negative controls — mid-`SYNTHESIZED` for a plain `NEW` proposal and mid-`SYNTHESIZED` for a `REPLACES_STALE` proposal, proving that neither a partial object/edge state nor a replacement-without-retirement state is representable. Each test asserts the state is detectable, non-deliverable, and completes to exactly the same final state as an uninterrupted run (I16, I20).

### 10.7 Canonical authority preservation (C11, new)

**The hole being closed.** Before this rule the following was permitted end to end:

```
stale CANONICAL Requirement
  -> AI_INFERRED replacement, authority PROPOSED (§10.2)
  -> LOW materiality, slice-1 policy routes APPLY
  -> REPLACES_STALE retires the CANONICAL target
  -> the PROPOSED replacement is absent from obligation_ids (§20.2)
  -> a LOW non-canonical Requirement does not block closure
  -> the scope becomes deliverable with the canonical obligation GONE
```

That is an **indirect authority-deletion path**: an AI could remove a canonical obligation from the contract without ever being granted authority to assert one. §10.3 blocks *inventing* canonical authority; nothing blocked *deleting* it.

**The protection that exists today is accidental and must not be relied on.** If the retired obligation is the scope's *only* canonical obligation, `MISSING_CANONICAL_OBLIGATION` fires and closure fails (`closure.py:59-69`). But that check is satisfied by **any one** canonical obligation in scope, so the moment a scope holds two, retiring one becomes invisible: `NON_CANONICAL_REQUIREMENT` fires only at `MEDIUM`+ materiality (`MATERIAL_REQUIREMENT_LEVELS`, `closure.py:25-27`), and the retired object drops out of `_is_current` entirely. The hole is real and widens with scope size.

**The law:**

> **A `CANONICAL` intent object may be retired or reconciled only by a `CANONICAL` replacement.**

For the Requirement slice specifically:

| target | replacement | outcome |
|---|---|---|
| `CANONICAL` | `CANONICAL` | eligible for replacement |
| `CANONICAL` | non-`CANONICAL` | **retirement must not apply** |
| non-`CANONICAL` | any | ordinary replacement rules |

An `AI_INFERRED` / `PROPOSED` replacement for a canonical target remains a **live proposal awaiting governed or human authorization**. It is recorded and visible; it simply cannot retire the canonical target. The stale canonical object stays live, stays stale and keeps blocking delivery — which is the correct outcome: an unresolved canonical obligation should block, not vanish.

**No total ordering over `Authority` is introduced.** The minimum law is *preservation of `CANONICAL`*, expressed as a single equality check. Ranking `PROPOSED` against `INFERRED` or `OBSERVED` is not required and is not done.

**Defence in depth — three independent layers, each with its own test:**

1. **Routing.** `route_intent_synthesis` refuses, or requires human authorization, before `APPLY` when the target is `CANONICAL` and the assigned replacement authority is not. The natural route is `REQUIRE_HUMAN` with reason `CANONICAL_REPLACEMENT_REQUIRED`: the proposal survives as a proposal and a human can authorize it.
2. **Reduction.** The reducer structurally refuses an `INTENT_OBJECT_SYNTHESIZED` whose `replaces_object_id` names a `CANONICAL` object while `object.authority` is not `CANONICAL`. This is a pure structural comparison of two authorities already present in state and payload, so it stays within the reducer's remit (§10.5) and needs no view derivation. The existing `_append` dry-run refuses such an event before it can reach the ledger.
3. **Reconciliation.** `validly_reconciled` must not clear a canonical stale chain whose head is non-`CANONICAL` — condition 6 in §15.6.

Layers 1 and 2 prevent the act; layer 3 ensures that even if an ill-formed chain existed, it could not unblock delivery.

### 10.8 Terminal invalidation of a durable `DECIDED(APPLY)` (C13, new)

**The deadlock being closed.** After a durable `DECIDED(APPLY)` and before `INTENT_OBJECT_SYNTHESIZED`, relevant state can change — most obviously a basis claim superseded by another worker. I1 correctly forbids applying against a non-live basis. But without a terminal outcome the proposal stays `APPLY, not applied` **forever**, so `incomplete_proposal_ids` never clears and §18's gate blocks delivery permanently. The C13 deadlock is the mirror of the C6 deadlock: both are states with no exit.

**`INTENT_SYNTHESIS_INVALIDATED`** is the terminal non-applied outcome. It:

- is **durable and replayable**, like every other outcome;
- records a **bounded** reason — `InvalidationReason` ∈ { `BASIS_CHANGED`, `TARGET_CHANGED`, `AUTHORITY_CHANGED` } — never free text, so the ledger stays analysable;
- **removes the proposal from `incomplete_proposal_ids`**, unblocking delivery;
- **never creates or retires an intent object** — it is purely the recording of a non-effect;
- requires a **fresh synthesis run** if the intent still needs resolving. It is not a retry and never silently re-decides.

**Revalidation before effect** — checked against current state immediately before `SYNTHESIZED`, each mapping to exactly one reason:

| check | fails as |
|---|---|
| every basis claim still live, in scope, unchanged | `BASIS_CHANGED` |
| `replaces_object_id` still exists, is current, in scope, still stale, not already retired | `TARGET_CHANGED` |
| target/replacement authority relationship still satisfies §10.7 | `AUTHORITY_CHANGED` |

**Lifecycle partition (I24) — a statement about every snapshot, not about eventual progress:**

> At **any** replayed snapshot, every durable `DECIDED(APPLY)` proposal is in exactly one of three states: **applied** (`INTENT_OBJECT_SYNTHESIZED`), **invalidated** (`INTENT_SYNTHESIS_INVALIDATED`), or **incomplete** (neither). The three are mutually exclusive and their union covers every `DECIDED(APPLY)`.

`applied` and `invalidated` are the two **terminal** outcomes. **`incomplete` is a legal non-terminal state** — delivery-blocking, detectable and retriable — not a defect. The architecture deliberately admits it: it is the window between a durable decision and its effect (§10.6), and bounded-retry exhaustion (C14) may legitimately leave a proposal there.

**What must not be claimed.** This specification does **not** claim that every snapshot is already terminal, nor that progress is unconditional. If recovery is never invoked, or bounded contention keeps exhausting attempts, a proposal stays incomplete — correctly blocking delivery rather than silently proceeding. Terminality is a property of the **recovery protocol**, not of the state projection:

> **Recovery terminality.** A *successful* completion or recovery pass ends each proposal it processes as applied **xor** invalidated. Bounded-retry exhaustion may leave a proposal incomplete; the **next** recovery invocation may resume it. No proposal is ever abandoned, and no incomplete state is a hidden dead-end.

This is the exact sense in which I24a's "explicit legal exit" holds: the exit exists and is always reachable by running recovery. It is not an automatic guarantee that it has already been taken.

Non-`APPLY` routes (`NO_CHANGE`, `REJECT`, `REQUIRE_SECOND_LENS`, `REQUIRE_HUMAN`) are already terminal at the decision: they never enter `incomplete_proposal_ids` and need no invalidation.

```
incomplete_proposal_ids(state) :=
    { p for p in intent_synthesis.decisions
        if route(p) == APPLY
       and p not in intent_synthesis.applied_proposal_ids
       and p not in intent_synthesis.invalidated_proposal_ids }
```

---

## 11. Deterministic-normalization exemption

Narrow by construction. If this fence leaks it becomes an unaudited canonical-authority minting route.

A deterministic normalization may **inherit** its source's authority and provenance only if **all three** hold:

1. **exactly one** basis claim;
2. **no** merging, inference, generalization, quantifier change, unit conversion or aggregation — a pure restatement whose meaning is provably identical;
3. the basis claim's authority is `CANONICAL` **and** its provenance `source_kind` is `HUMAN`.

Any failure means it is synthesis and takes the §10 path. No partial credit, no "mostly deterministic" route.

Because condition 2 is not mechanically checkable in general, the exemption is admissible **only** for transformations whose meaning-preservation is established by construction in code and pinned by a test with exact input and output. An open-ended normalizer is not eligible. **Out of scope for slice 1** (§26).

---

## 12. Dual provenance invariant

Both recordings are mandatory for every basis claim. Neither substitutes for the other.

### 12.1 Readable semantic provenance

```
intent_object.relations includes
    Relation(relation_type=RelationType.DERIVED_FROM, target_id=<basis claim_id>)
```

One per basis claim. Human-readable, queryable, immutable, part of the object. Uses **`claim_id`**.

### 12.2 Blast-radius provenance

```
DerivationEdge(
    child_id  = <intent_object_id>,
    parent_id = <basis_claim.created_by_judgment_id>,
)
```

One per basis claim, written by the reducer as part of the single `INTENT_OBJECT_SYNTHESIZED` application (§10.5), not by separate `DERIVATION_RECORDED` events. Uses the **asserting judgment id**.

`SemanticGovernor.derive()` remains available and unchanged for non-synthesis derivations; the synthesis path does not use it, because per-edge events would reintroduce the C1 hazard.

### 12.3 The asymmetry is deliberate — do not "fix" it

`derivation.stale_object_ids` computes roots as *inactive judgment ids* plus *issue versions minted by them*, then takes `descendants(state.derivations, roots)`. **Claim ids are never roots.** An edge whose `parent_id` is a `claim_id` would record provenance that looks correct and **silently fail to propagate staleness** — a correct-looking ledger with a broken blast radius, worse than an obvious defect.

> **Never use `claim_id` as a `DerivationEdge` parent under the current staleness algorithm.**

Any future change to `stale_object_ids` roots must revisit this section explicitly.

### 12.4 Provenance record

```
Provenance(
    source_kind      = HUMAN (HUMAN_STATED) | SYSTEM (AI_INFERRED, RESEARCH_DERIVED)
                     | inherited (DETERMINISTIC_NORMALIZATION),
    source_ref       = actor id | synthesis invocation id | inherited,
    source_event_ids = the INTENT_SYNTHESIS_DECIDED event,
)
```

**Research-derivedness is derived, never stored.** `research_derived(object)` is true when every basis claim's *effective* evidence carries `SourceKind.RESEARCH`. The property is recoverable through the derivation chain with no new field, and stays correct when a later `SUPPORTS_CLAIM` adds non-research evidence.

### 12.5 Count invariant

```
len([r for r in object.relations if r.relation_type is DERIVED_FROM])
    == len(basis_claim_ids)
    == len(edges where child_id == object_id)
```

A `Relation` without an edge is a silent staleness hole; an edge without a `Relation` is unreadable provenance. Both are defects; both are caught by I3. After C1 the three counts cannot diverge across a crash, because they are established in one event.

---

## 13. Many atomic claims → one intent object

### 13.1 The shape

`basis_claim_ids` has `min_length=1` and no upper bound beyond the request cap. Semantics are **conjunctive**: the object asserts a commitment supported by all cited claims jointly.

Worked example over the frozen locus-validation alpha evidence (illustrative; that experiment is not rerun):

```
ADDR-ae0de307833fe2f5   "Client credential / What are the rules of revocation?"
   CLAIM-6e40a6...  who may revoke                -> owner or operator
   CLAIM-4595a5...  when revocation takes effect  -> immediately
   CLAIM-a7a6fa...  client can undo               -> no
   CLAIM-ded86e...  auth with revoked credential  -> must not succeed
        |
        +--> REQ-1  "Only the credential's owner or an operator may revoke it;
                     revocation takes effect immediately, cannot be undone by the
                     client, and permanently prevents authentication."
               basis_claim_ids  = all four
               relations        = 4 x DERIVED_FROM (claim ids)
               derivation edges = 4, each to the claim's asserting judgment id
               basis_locus_ids  = runtime-derived: {ADDR-ae0de307833fe2f5}
```

**The statement covers all four cited propositions.** The original version of this example cited four claims but omitted "who may revoke" from the statement — itself a breach of §13.2, corrected here (C4).

**This is the structural resolution of the granularity question.** Claims stay atomic and independently supersedable; intent stays human-meaningful. Nothing downstream counts claims, so "how many claims should there be" ceases to be a contested number.

Bases spanning more than one locus are permitted and are normal for a commitment constraining several subjects.

### 13.2 Basis coverage invariant (C4, new)

> **Every basis claim must materially support meaning represented by the synthesized object. A claim is never cited merely because it is available at the same locus.**

**Why this matters concretely.** A cited claim is wired into the blast radius (§12.2). Superseding a claim the statement does not actually represent would mark the object stale, block the handoff and demand reconciliation — for a correction that changed nothing the commitment asserts. That is **false-positive staleness**: it trains operators to dismiss staleness signals, which destroys the value of the mechanism that makes evolving intent safe.

The converse is equally a defect: a proposition the statement *does* assert but does not cite is **false-negative staleness** — the commitment silently outlives the evidence that justified it.

Coverage is semantic and not fully mechanically checkable. It is therefore enforced by three means, stated honestly:
1. the synthesizer's `rationale` must account for the basis as a whole;
2. a test proves an unrelated claim at the same locus is **not** included merely because it is available (I17);
3. review treats an uncovered citation as a defect, exactly as it treats a missing one.

Runtime checks what it can: every `basis_claim_id` must be live, in scope, and present in the request (§23). It cannot check material support, and this specification does not pretend otherwise.

---

## 14. One claim → many intent objects

Permitted, unrestricted, and **no uniqueness constraint may be introduced**. `DerivationEdge` is many-to-many by construction (one `parent_id`, arbitrarily many `child_id`s) and `descendants` is a set-valued transitive closure, so fan-out propagates unchanged.

```
CLAIM-ded86e...  "no authentication attempt that presents it may succeed"
    +--> REQ-1         (the revocation requirement)
    +--> CONSTRAINT-2  ("no authentication path may bypass revocation")
    +--> VO-3          (future: "test: authenticate with a revoked credential")
```

Superseding that one claim marks **all three** stale in one traversal. This is why §12.2 edges must exist even where they feel redundant with §12.1.

---

## 15. Staleness and reconciliation

### 15.1 Correction (basis claim superseded)

Works end to end with **no change to existing code**, once the §12.2 edge exists:

```
SUPERSEDE applied  ->  asserting judgment becomes inactive
  -> stale_object_ids() roots include it
  -> descendants(derivations, roots) includes the intent object
  -> view.stale_ids contains the intent object id
  -> scoped_stale_object_ids attributes it to the scope        [handoff.py:149]
  -> semantic_blockers_clear = False
  -> SemanticReadiness.ready = False
  -> it is UNRECONCILED, so it blocks v2 delivery              [§15.6]
  -> and only a CANONICAL replacement may reconcile it          [§10.7]
  -> IntentDecisionHandoff v2 REFUSES to emit                  [D6 substance]
  -> the object surfaces as is_stale=True in the next request  [§8, C3]
```

The object is never auto-rewritten and never auto-retired. It is stale, and the scope stops being deliverable until reconciled.

### 15.2 Reconciliation (corrected for C2)

Reconciliation is **supersession by replacement**, driven by disposition `REPLACES_STALE` (§9.3):

1. a fresh proposal over the corrected claims, `disposition=REPLACES_STALE`, `relates_to_object_id=<the stale object>`;
2. runtime validates at routing time that the named object exists, is in scope and `is_stale` is true;
3. **one** `INTENT_OBJECT_SYNTHESIZED` event, carrying `replaces_object_id`, atomically mints the replacement (its own new `object_id`, relations and edges), retires **exactly** the named object (I18), and records the `RetirementRecord` that §15.6 needs (C7).

There is no separate retirement event. The replacement and the retirement are the same durable act.

**What is and is not immutable — the C2 correction.** The earlier claim that "the original object's bytes are unchanged" was **false**. `reducer.py:113-128` applies `old.model_copy(update={"lifecycle": SUPERSEDED, "revision": old.revision + 1})`. The accurate law is:

- **the event log is immutable and append-only**; the original creation event is never rewritten, deleted or edited;
- supersession is recorded by a **new event**, never by editing history;
- **replay therefore changes the current projection** of the retired object to `lifecycle=SUPERSEDED` with `revision` incremented — the projection is *supposed* to move;
- the **replacement carries its own object id**; the two are distinct durable objects;
- **historical truth remains reconstructable** by replaying the log to any earlier sequence, which reproduces the retired object exactly as it stood.

Immutability belongs to the log, not to the current projection. Any future statement to the contrary in this specification is an error.

### 15.3 The reducer is not changed (C2 analysis)

The instruction was to change the reducer only if analysis proves it architecturally wrong. It does not.

Mutating the projected object on supersession is correct event-sourced behaviour: `IntentState` is a *projection*, rebuilt deterministically from the log, and a projection that failed to reflect a recorded supersession would be the defect. Bumping `revision` is the standard signal that the projection moved. `_is_current` then excludes the object from closure and the package, which is exactly the intended effect.

Two properties of the existing branch are worth recording, because they bound what reconciliation can rely on:
- it validates that `payload.superseded_by` resolves to a `Requirement` in current state but does **not** persist the link on either object — the replacement relationship lives in the event, recoverable only by reading the log;
- it is `Requirement`-specific, which is sufficient for a `Requirement`-only slice and is the substance of D8.

The replacement link is therefore projected durably as a `RetirementRecord` written inside `INTENT_OBJECT_SYNTHESIZED` (§10.5), so it is queryable without re-reading history — which §15.6 depends on. `REQUIREMENT_SUPERSEDED` remains untouched and available for non-synthesis paths; synthesis never emits it.

### 15.4 Disputed and pending

A locus that is `DISPUTED`, carries a pending material judgment, or is stale is never offered for synthesis (§7) and blocks readiness through the existing `disputed_locus_ids` / `pending_material_judgment_ids` / `stale_object_ids` fields. No new mechanism.

### 15.5 Compatible extension — explicitly unresolved

A new claim added at a basis locus supersedes nothing, so the derived object does **not** become stale. It may nevertheless be *incomplete*: a proposition exists at its locus that its statement does not reflect. Note this is the mirror of §13.2's false-negative case, arising from evolution rather than from authoring.

Blocking would be wrong (nothing was invalidated); ignoring may be wrong (the commitment may be understated). No existing `GapKind` names the condition.

**Deliberately not decided here.** Slice-1 behaviour is **no effect, no gap, no staleness** — the conservative, non-blocking reading, pinned by I13 so a later change is conscious. Open decision D5; must be resolved before synthesis runs on an evolving corpus.

### 15.6 Delivery-blocking staleness in v2 (C6, new)

**The defect being fixed.** `scoped_stale_object_ids` intersects `view.stale_ids` with attributed descendants and applies **no lifecycle filter** — it receives only `(semantic, view, in_scope_loci)` and has **no access to `state.objects`**, so it could not filter one even in principle. `view.stale_ids` is purely derivation-topological, and a superseded judgment stays inactive permanently. Consequently a retired object's id remains in `view.stale_ids` and in `scoped_stale_object_ids` **forever**, `semantic_blockers_clear` stays false, and a scope that has been correctly reconciled becomes **permanently undeliverable**. Reconciliation without this rule is not a story that terminates.

`domain/handoff.py` is **not** modified (D7). v2 computes its own blocking set.

#### Durable evidence of reconciliation

```
RetirementRecord                    # in IntentSynthesisState, append-only
  retired_object_id: str
  replaced_by_object_id: str
  proposal_instance_id: str
  recorded_by_event_id: str
```

Written **only** by the reducer inside `INTENT_OBJECT_SYNTHESIZED` when `replaces_object_id` is set (§10.5). It cannot be forged by a synthesizer, cannot be written independently of a replacement, and cannot exist without the replacement it names, because both are established in the same event.

#### The v2 blocking-stale calculation

```
v2_blocking_stale_object_ids(state, view, scope, in_scope_loci) :=
    tuple(sorted(
        oid
        for oid in scoped_stale_object_ids(state.semantic, view, in_scope_loci)   # v1 helper, unchanged
        if not validly_reconciled(state, view, scope, oid)
    ))
```

`validly_reconciled(oid)` follows the retirement chain from `oid` to its head and requires **every** condition to hold:

1. a `RetirementRecord` exists for `oid` — mere absence from `objects`, or a lifecycle of `SUPERSEDED` reached by any other route, is **not** evidence;
2. the retired object's current projection is `lifecycle == SUPERSEDED`;
3. the chain `oid → replaced_by → …` is followed to its head, cycle-safe with a visited set, so a chain of successive reconciliations resolves correctly;
4. the head object **exists**, is `_is_current` (`ACTIVE`, authority not `REJECTED`/`SUPERSEDED`), and is in scope;
5. **the head object is itself not in `view.stale_ids`;**
6. **if `oid`'s object was `CANONICAL`, the chain head is `CANONICAL` too** (§10.7, C11) — a `PROPOSED` head never reconciles a canonical stale chain.

Condition 5 is the load-bearing one for correctness over time. A replacement whose own basis has since been superseded has resolved nothing; treating its predecessor as reconciled would let a scope deliver on a commitment that is itself out of date. Condition 1 is what makes this *proof of reconciliation* rather than *ignoring superseded ids*: an object retired by any path that did not produce a valid replacement continues to block, which is exactly the required negative control. Condition 6 is the third layer of §10.7's defence: even an ill-formed canonical chain that somehow existed could not unblock delivery.

#### v2 readiness

```
IntentDeliveryReadiness
  semantic_readiness: SemanticReadiness          # the v1 result, embedded verbatim for transparency
  blocking_stale_object_ids: tuple[str, ...]     # the v2 calculation above
  reconciled_stale_object_ids: tuple[str, ...]   # historical, non-blocking — visible, not hidden
  incomplete_synthesis_proposal_ids: tuple[str, ...]
  deliverable: bool
```

```
deliverable := semantic_readiness.closure.closed
           and not semantic_readiness.disputed_locus_ids
           and not semantic_readiness.pending_material_judgment_ids
           and not blocking_stale_object_ids
           and not incomplete_synthesis_proposal_ids
```

v2 substitutes `blocking_stale_object_ids` for the unfiltered stale set and reuses every other v1 condition **unchanged**. `evaluate_closure` is untouched; `build_semantic_readiness` is untouched and its verbatim result is carried so a reviewer can see both views and the difference between them.

`reconciled_stale_object_ids` is reported rather than dropped: a reader can always see which historical staleness was set aside and why it did not block.

**Relationship to D6.** D6's substance — a stale basis blocks delivery, closure unchanged — is preserved exactly. Its literal form is not satisfiable after any reconciliation (§0, D6-R).

---

## 16. Gap behaviour

Synthesis refuses **with a reason**, never silently. Every condition maps to an **existing** `GapKind`; no new kind is introduced.

| condition | `GapKind` | blocking | decided by |
|---|---|---|---|
| locus `DISPUTED` (active `CONFLICTS_WITH`) | `CONTRADICTION` | yes | runtime |
| pending material judgment on a basis locus | `MISSING_AUTHORITY` | yes | runtime |
| any basis claim stale | `STALE_EVIDENCE` | yes | runtime |
| any basis claim value `UNDECIDED` | `MISSING_INFORMATION` | yes | runtime |
| statement cannot be formed as one coherent commitment | `AMBIGUITY` | yes | synthesizer |
| material target, basis inferred/research only | `MISSING_AUTHORITY` | policy (D3) | runtime |
| canonical `Requirement` with `requires_metric` and no metric | `MISSING_SUCCESS_METRIC` | yes | runtime |
| locus `OPEN` (no live claims) | — nothing to synthesize; no gap | — | runtime |

**Exclusivity (I10):** for one basis and one target kind, synthesis emits an object proposal **or** a `Gap` for a given unresolved condition — never both. Runtime-decided conditions are settled before the synthesizer is called, so it is never asked to reason about a locus it should have been refused.

**Disposition interaction (C3):** `EXISTING_UNCHANGED` is **not** a gap. It is a successful no-op with route `NO_CHANGE` (§9.3). Emitting a gap for it would misreport correct de-duplication as an unresolved problem.

`GapKind.AMBIGUITY` is recorded through `AMBIGUITY_DETECTED`, which the envelope validator already constrains to that kind; all other kinds use `GAP_RECORDED`.

---

## 17. Requirement-first vertical slice

### 17.1 Why `Requirement`, not `Constraint`

`Constraint` looks simpler — bare `statement`, no materiality, metric or verification fields. It is the wrong first kind: `evaluate_closure` raises `NON_CANONICAL_OBLIGATION` for **any** non-canonical `Constraint` in scope (`closure.py:115`), so a single `PROPOSED` Constraint blocks closure permanently until canonicalized or rejected.

`Requirement` blocks closure only at `materiality >= MEDIUM` (`MATERIAL_REQUIREMENT_LEVELS`), so a `LOW` proposal is harmless and visible. **`Requirement` is the smallest coherent vertical slice.**

### 17.2 Slice-1 contents

1. one live, human-provenanced, `CANONICAL` basis claim at one in-scope locus;
2. `HUMAN_STATED` synthesis with a covering `AuthorityRecord`, `disposition=NEW`;
3. one `CANONICAL` `Requirement`, `materiality=LOW`, `requires_metric=False`, `requires_verification=False`;
4. dual provenance recorded atomically in one event (§10.5, §12);
5. a `CANONICAL` `Intent` in scope (via `SEMANTIC_OBJECT_RECORDED`; `INTENT` is in `GENERIC_SEMANTIC_KINDS`);
6. `evaluate_closure` closes — **unchanged**;
7. `build_intent_package` emits the contract — **unchanged**;
8. `IntentDecisionHandoff v2` emits, gated on readiness **and** on no incomplete synthesis.

`requires_metric=False` makes the metric blocker unreachable (`closure.py:136` guards on the flag), so no `Metric` or `VerificationObligation` is needed and no metric-design decision is forced.

`allowed_target_kinds == {SemanticKind.REQUIREMENT}` (C5). `RequirementSynthesisProposal` is the only variant that exists.

### 17.3 Four proofs carried in slice 1

Cheap, and they pin what matters most:

- **authority boundary** — one `AI_INFERRED` Requirement at `LOW` materiality is `PROPOSED`, never enters `obligation_ids`, does not block closure;
- **blast radius** — superseding the basis claim makes the Requirement stale, and handoff v2 refuses;
- **no duplicate intent (C3)** — a second equivalent proposal returns `EXISTING_UNCHANGED` / `NO_CHANGE` and mints nothing;
- **crash consistency (C1)** — interruption at each persistence boundary is detectable, non-deliverable and completes exactly once to the identical final state.

### 17.4 Slice-1 policy pinning (conservative, not the general law)

```
IntentSynthesisPolicy(
    material_target_kinds        = frozenset(),      # no kind material in slice 1
    material_materiality_levels  = frozenset(),
    canonical_requires_authority = True,
)
```

Safe because slice 1 admits only `HUMAN_STATED` (which needs a covering `AuthorityRecord` regardless) and `AI_INFERRED` at `LOW` materiality (`PROPOSED`, non-contractual, non-blocking). **A slice-1 restriction, not the general policy** — D3.

---

## 18. `IntentDecisionHandoff` v2

New module `domain/handoff_v2.py`. `domain/handoff.py` is **not edited at all**, including its `HandoffVersion` type — the v2 literal is declared in the new module (D7).

```
IntentDecisionHandoffV2
  handoff_version: Literal["intent-decision-handoff-v2"]
  project_id: str
  scope: str
  intent_version: int                      # package revision
  semantic_state_revision: int

  # --- PRIMARY: canonical intent ---------------------------------
  contract: CanonicalIntentPackage         # already ids-only
  canonical_intent_object_ids: tuple[str, ...]
  proposed_intent_object_ids: tuple[str, ...]    # visible; NOT authoritative

  # --- BRIDGE: intent traced to substrate -------------------------
  intent_basis: tuple[IntentBasisRef, ...]

  # --- TRACEABILITY: retained from v1 -----------------------------
  loci, claim_ids, evidence_ids, authority_record_ids, superseded_judgment_ids

  # --- GOVERNANCE --------------------------------------------------
  blocking_stale_object_ids: tuple[str, ...]              # C6 — unreconciled only
  reconciled_stale_object_ids: tuple[str, ...]            # C6 — historical, non-blocking
  pending_material_judgment_ids: tuple[str, ...]
  incomplete_synthesis_proposal_ids: tuple[str, ...]      # C1
  readiness: IntentDeliveryReadiness                      # embeds SemanticReadiness verbatim
```

```
IntentBasisRef
  object_id: str
  basis_claim_ids: tuple[str, ...]
  basis_locus_ids: tuple[str, ...]         # runtime-derived (C4)
```

**Emission gate — one condition, computed from five (C6):**

> `build_intent_decision_handoff_v2` **refuses** unless `IntentDeliveryReadiness.deliverable is True` (§15.6).

That is: closure met, no disputed locus, no pending material judgment, **no unreconciled stale object**, and no incomplete synthesis. Refusal raises a typed error naming the blocking condition, in the shape `IntentNotClosedError` establishes. Nothing partial is emitted.

The gate is **not** `SemanticReadiness.ready`, because that field embeds the unfiltered stale set and therefore never clears after a reconciliation (§15.6, D6-R). It is carried verbatim inside `IntentDeliveryReadiness` so both views remain visible.

`evaluate_closure`, `build_semantic_readiness` and `CanonicalIntentPackage` stay unchanged; every gate lives in v2, where the semantic conditions already live.

**No second ledger.** Embedding `CanonicalIntentPackage` by value is safe precisely because it is itself ids-only. `intent_basis` is ids only. No statement text, claim value, rationale or evidence content appears anywhere in v2 (I9).

`loci`, `claim_ids` and `evidence_ids` are retained and **explicitly labelled traceability**: they support blast-radius analysis, governance and audit. They are not the contract.

---

## 19. v1 / v2 coexistence

- v1 is **byte-frozen**: `IntentDecisionHandoff`, `HANDOFF_VERSION`, `HandoffVersion`, `SemanticReadiness` and every helper in `domain/handoff.py` unchanged. Every existing `tests/unit/test_handoff.py` test passes untouched (I11).
- v2 is additive, in a separate module. Both may be built from the same state.
- v1 has **no** readiness gate and keeps that behaviour; v2 has two. The difference is intentional and is why they coexist without ambiguity.
- v2 becomes the downstream target **only after independent proof**. Until then no consumer is migrated and no call site changes.
- Deprecating v1 is out of scope (D7 remains a migration question, not a design question).

---

## 20. `CanonicalIntentPackage` as the single downstream contract

1. `build_intent_package` is **not modified**; it still refuses on non-closure with `IntentNotClosedError`.
2. Obligations have one source: `obligation_ids` remains `Requirement | Constraint | Contract` filtered to `CANONICAL`. A `PROPOSED` object can never reach a consumer as an obligation (I8).
3. `Actor` remains in `purpose_ids` (D1), unchanged.
4. In v2, claims and loci are **demoted to traceability** and labelled as such. Planning and Architecture consume `contract`; they read `loci` / `claim_ids` only for blast radius and audit.
5. The package becomes *reachable* for the first time. It is unchanged and already end-to-end tested (`tests/e2e/test_replay_to_package.py`) with hand-fed objects; synthesis supplies those objects from governed state instead of fixtures.
6. **Contract vs. gate, stated to prevent a later contradiction:** `CanonicalIntentPackage` is the single **contract**; `IntentDecisionHandoff v2` is the single **delivery gate**. The package may still be built while the basis is stale or a synthesis is incomplete — unchanged v0 behaviour, deliberately preserved (D6). Delivery is what those conditions block.

---

## 21. Research Worker interaction boundary

**Boundary only. The Research Worker is not designed here.**

```
Gap -> Research Job -> EvidenceItem -> normal semantic assimilation -> claims -> Intent Synthesis
```

The law is already the architecture's and is already enforced by construction:

- `specs/2026-09-09-intent-engine-v0-design.md` principle 1: *"Research is subordinate to intent and produces evidence only."*; line 331: *"Research cannot directly create canonical requirements or decisions."*
- `DigRecord` → `evidence_from_dig()` (`domain/evidence.py:112`) returns an `EvidenceItem` and nothing else. **No function exists** by which research output can mint an address, a claim or an intent object.
- `Job` (`domain/jobs.py:46`) already carries `gap_id`, `JobType.RESEARCH_PLANNING` / `EVIDENCE_COLLECTION` / `EVIDENCE_RECONCILIATION`, `permitted_executors`, `budget_usd`, `verification_requirement`. Research is pre-governed and pre-budgeted.
- `Gap.resolution_event_id` + `GapStatus.RESOLVED` / `WAIVED` close the loop.

**What this specification adds:** research-derived intent is `RESEARCH_DERIVED` origin (§10.1), assigned `PROPOSED` authority (§10.2), never privileged. A requirement inferred from research is a proposal, not canonical intent — enforced by §10.2 and §10.3, not by convention.

Research evidence is admitted, bound, supported and superseded by exactly the same governance as human- or document-sourced evidence.

---

## 22. Replay and determinism

The synthesizer is non-deterministic. The **ledger** must not be.

1. **State is rebuilt from events, never by re-running a synthesizer.** Proposal and decision are recorded as events; the reducer applies only what an `APPLY` decision records — the separation `SEMANTIC_JUDGMENT_RECORDED` / `SEMANTIC_ADMISSION_DECIDED` already establishes.
2. **Replay exactness (I7):** replaying the log reproduces byte-identical `state.objects` (including retired projections), `state.semantic.derivations`, `state.intent_synthesis` (decisions, `applied_proposal_ids`, `invalidated_proposal_ids`, `retirements`), closure result, `IntentDeliveryReadiness`, `CanonicalIntentPackage` and `IntentDecisionHandoffV2`.
3. **Derivation edges are recomputed by the reducer** from `basis_claim_ids` and current claims (§10.5). They are a pure function of prior state, so replay reproduces them exactly and they cannot desynchronise from the claims they describe.
4. `route_intent_synthesis` is **pure** in `(state, proposal, origin, policy)` — no I/O, no clock, no provider import, no randomness, no mutation.
5. **Deterministic ids on the synthesis path (C1):** `object_id` and every `event_id` are pure functions of **`proposal_instance_id`** — itself `deterministic(project_id, synthesis_run_id, model_proposal_id)` — and, for an event, the step. Never of the raw `model_proposal_id`. No random id factory. This is what makes recovery exactly-once (§10.6) *and* replay-stable.
6. Ordering is deterministic: proposals in returned order; gaps after proposals; derivation edges in `basis_claim_ids` order.
7. Runtime clocks and invocation ids enter through injected factories, as `SemanticGovernor` already does.
8. **Zero provider calls in the test suite.** All synthesis tests use a scripted fake synthesizer, mirroring the existing `SpecReasoner` pattern.

---

## 23. Failure and refusal behaviour

**Whole-batch refusal**, mirroring `SemanticOutputError`: nothing is repaired, guessed, fuzzy-matched, dropped or substituted.

| condition | behaviour |
|---|---|
| proposal cites a claim not in the request | structural failure; **whole result refused** |
| proposal cites a claim no longer live at apply time | structural failure; whole result refused |
| `target_kind` not in `allowed_target_kinds` | structural failure; whole result refused |
| proposal is not a `RequirementSynthesisProposal` in slice 1 | structural failure; whole result refused |
| `basis_claim_ids` empty | schema rejection (`min_length=1`) |
| `disposition == NEW` with `relates_to_object_id` | structural failure (§9.3) |
| `disposition != NEW` without `relates_to_object_id` | structural failure (§9.3) |
| `relates_to_object_id` not in `known_intent_objects` | structural failure |
| `REPLACES_STALE` naming a non-stale object | structural failure (§9.3) |
| `EXISTING_UNCHANGED` naming a stale object | structural failure (§9.3) |
| proposal carries `authority` or `basis_locus_ids` | unrepresentable in the schema; if present, structural failure |
| result exceeds the request cap | refusal; never silent truncation |
| origin not `HUMAN_STATED` and authority `CANONICAL` | `REJECT` / `AUTHORITY_INVENTION` (§10.3) |
| `HUMAN_STATED` without covering `AuthorityRecord` | `REQUIRE_HUMAN` / `AUTHORITY_UNRESOLVED`; recorded, not applied |
| material proposal without corroboration | `REQUIRE_SECOND_LENS`; recorded, not applied |
| locus `DISPUTED` / pending / stale / `UNDECIDED` | `Gap` (§16); synthesizer never invoked for that locus |
| `INTENT_OBJECT_SYNTHESIZED` names a claim absent from state | unreplayable; refused by the existing `_append` dry-run before reaching the ledger |
| crash mid-sequence | detectable, non-deliverable, completable exactly once (§10.6) |
| `REPLACES_STALE` on a `CANONICAL` target with a non-`CANONICAL` replacement | `REQUIRE_HUMAN` / `CANONICAL_REPLACEMENT_REQUIRED`; retirement does not apply; target stays live, stale and blocking (§10.7) |
| basis, target or authority relationship changed between `DECIDED(APPLY)` and effect | `INTENT_SYNTHESIS_INVALIDATED` with a bounded reason; terminal, no object created or retired (§10.8) |
| unrelated concurrent append during recovery | `ConcurrencyError` → reload, recompute, revalidate, bounded retry, else terminal invalidation (§10.6, C14) |
| same-item concurrent completion during recovery | `DuplicateEventError` caught internally; treated as already-done; success to the caller |
| handoff v2 with `IntentDeliveryReadiness.deliverable is False` — non-closure, disputed locus, pending judgment, **unreconciled** stale object, or incomplete synthesis | typed refusal naming the condition; nothing emitted |
| closure not met | existing `IntentNotClosedError`; unchanged |

A refusal **always** leaves a readable record. Because proposal and decision are one event (C12), that record is either the `INTENT_SYNTHESIS_DECIDED` event — which carries the proposal verbatim alongside its route and reasons, so a `REJECT`, `REQUIRE_HUMAN` or `REQUIRE_SECOND_LENS` stays fully readable with canonical state untouched — or an `INTENT_SYNTHESIS_INVALIDATED` event, or a `Gap`. There is no separate proposal or admission event on the synthesis path. Silent failure is a defect.

---

## 24. Invariants

| # | invariant |
|---|---|
| **I1** | No synthesis without basis: `basis_claim_ids` non-empty; every id is a claim **live** in `derive_view` at both request and apply time. |
| **I2** | **No AI-chosen authority.** The schema cannot express authority. A non-`HUMAN_STATED` proposal with `CANONICAL` is `REJECT` / `AUTHORITY_INVENTION` and never reaches a low-risk route. |
| **I3** | **Dual provenance.** Per basis claim: a `Relation(DERIVED_FROM, claim_id)` **and** a `DerivationEdge(object_id, claim.created_by_judgment_id)`; counts equal (§12.5). The edge parent is **never** a `claim_id`. |
| **I4** | **Staleness propagates.** Superseding any basis claim's asserting judgment places the object in `view.stale_ids` and `scoped_stale_object_ids(scope)`, making `readiness.ready` false. Fan-out: one claim supporting N objects marks all N. |
| **I5** | **Event-log immutability, projection mobility (C2).** The creation event is never rewritten; supersession is a new event; replay moves the retired object's projection to `lifecycle=SUPERSEDED` with `revision+1`; the replacement holds its own object id; replay to an earlier sequence reproduces the retired object exactly. |
| **I6** | **Scope is derived** as the union of the basis claims' address scopes; never chosen by the synthesizer. |
| **I7** | **Replay exactness** (§22.2). |
| **I8** | **Contract purity.** A `PROPOSED` object never appears in `obligation_ids`. `LOW`-materiality proposals do not block closure; `MEDIUM`+ do. `Actor` remains in `purpose_ids`. |
| **I9** | **No second ledger.** Handoff v2 carries ids only. `KnownIntentObject` is never persisted, never an event payload, never returned in a proposal. |
| **I10** | **Gap-or-object exclusivity** (§16). `EXISTING_UNCHANGED` is a no-op, never a gap. |
| **I11** | **v1 frozen.** `domain/handoff.py` byte-unchanged; every existing handoff test passes untouched. |
| **I12** | **Locus keying.** Two addresses merged by an active `EQUIVALENT` yield one object, not two. |
| **I13** | **Compatible extension is inert in slice 1** — no staleness, no gap (pins D5). |
| **I14** | **Altitude separation.** Synthesis emits no `SemanticJudgment` and writes nothing into `state.semantic` except `DerivationEdge`s; `JudgmentKind`, `JudgmentProposal` and `AdmissionRoute` unchanged. |
| **I15** | **Event honesty.** `INTENT_OBJECT_SYNTHESIZED` is authority-neutral and carries its basis; the existing specialized canonicalization events are not reused for synthesized objects and remain untouched. |
| **I16** | **Crash consistency (C1).** Object and all its derivation edges are established in **one** event, so a partial object/edge state is unrepresentable. After C12 there is exactly **one** durable interruption window — `DECIDED(APPLY)` → `SYNTHESIZED` | `INVALIDATED` — detectable via `incomplete_proposal_ids`, non-deliverable via the handoff gate, and completable **exactly once** by deterministic ids plus the existing `DuplicateEventError`. `EventStore` is unchanged. |
| **I17** | **Basis coverage (C4).** Every basis claim materially supports meaning the object represents; no claim is cited merely for sharing a locus. `basis_locus_ids` is runtime-derived and never accepted from the synthesizer. |
| **I18** | **Disposition integrity (C3).** An equivalent existing commitment yields `EXISTING_UNCHANGED` / `NO_CHANGE` and mints nothing. `REPLACES_STALE` retires **exactly** the named object, which must be stale. A stale object is never affirmed as `EXISTING_UNCHANGED`. |
| **I19** | **Reconciliation clears delivery (C6).** A validly replaced and retired stale object no longer blocks v2, proved by a `RetirementRecord` whose chain head exists, is current, is in scope and is **itself not stale**. A stale object retired without a valid replacement **still blocks**. `domain/handoff.py` is unchanged. |
| **I20** | **No replacement without retirement (C7).** Replacement and retirement are established in one event. There is no persistence boundary at which a replacement is complete while its required retirement is missing, and `incomplete_proposal_ids` can never under-report an unfinished reconciliation. |
| **I21** | **Runtime-owned durable identity (C8).** The raw `model_proposal_id` is never a durable identity. Ids derive from `proposal_instance_id = deterministic(project_id, synthesis_run_id, model_proposal_id)`; they cannot collide across projects or across runs within a project; an interrupted run reproduces them exactly; recovery never needs a provider call. |
| **I22** | **Authorship is runtime-owned and human authority is never laundered (C9).** Origin follows the proposal's `author`, never its basis. A non-human `IntentSynthesizer` yields `AI_INFERRED`/`RESEARCH_DERIVED` regardless of basis authority. `HUMAN_STATED` requires `author.is_human` and an authenticated matching actor id. The model cannot choose or spoof `author`. |
| **I23** | **Canonical authority is preserved (C11).** A `CANONICAL` intent object may be retired or reconciled **only** by a `CANONICAL` replacement, enforced at routing, at reduction, and in `validly_reconciled`. No AI path can remove an obligation from `CanonicalIntentPackage`. No total ordering over `Authority` is introduced. |
| **I24** | **Lifecycle partition (C13, C16).** At **any** snapshot every durable `DECIDED(APPLY)` is exactly one of **applied**, **invalidated**, or **incomplete** (neither) — mutually exclusive, jointly covering. `applied` and `invalidated` are terminal; `incomplete` is a legal, delivery-blocking, detectable, retriable non-terminal state. Terminality belongs to the recovery protocol: a **successful** recovery pass ends each proposal applied xor invalidated; bounded-retry exhaustion may leave it incomplete for the next pass. No claim of unconditional eventual progress is made. |
| **I24a** | **Explicit legal exit (architect principle).** Every state capable of blocking delivery has an explicit legal exit, **reachable by a defined operation** — not necessarily already taken: unreconciled staleness → a valid `CANONICAL` replacement (§15.6); replacement without retirement → unrepresentable (§10.5); an incomplete `DECIDED(APPLY)` → `resume_incomplete_synthesis` ending it applied xor invalidated (§10.6, §10.8). No blocking state is a hidden dead-end. Any future blocking state added to this subsystem must ship with its exit. |
| **I25** | **Concurrency is handled on both axes (C14).** `DuplicateEventError` (same item completed elsewhere) resolves to success; `ConcurrencyError` (unrelated append) triggers reload, recompute, revalidate and bounded retry, falling back to terminal invalidation. Retries are bounded by a named constant; recovery never spins unbounded and never drops work. |

---

## 25. Tests

Every invariant has at least one test. Negative controls are mandatory wherever a rule could silently not fire.

**Structural / request**
- reject empty basis; retired claim id; out-of-scope claim; claim that goes non-live between request and apply.
- `DISPUTED` / `OPEN` / pending / stale loci are never offered (assert the synthesizer was not called).
- `KnownIntentObject` excludes rationale, provenance, revision, timestamps; `Decision` uses `statement`, not `rationale`.
- **`is_stale` is present and correct** for an `ACTIVE` object whose basis was superseded (C3).

**Proposal shape (C5)**
- `allowed_target_kinds == {REQUIREMENT}`; any other target kind is a structural failure.
- a proposal carrying `authority` or `basis_locus_ids` is unrepresentable; a hand-built one is refused.
- **negative control:** assert no generic proposal type can construct an `Assumption`, `Contract` or `Decision` in slice 1.

**Authority (I2)**
- `HUMAN_STATED` + covering `AuthorityRecord` → `CANONICAL`, `APPLY`.
- `HUMAN_STATED` without → `REQUIRE_HUMAN`, nothing written.
- `AI_INFERRED` → `PROPOSED`; `CANONICAL` unreachable.
- **negative control (C17), two halves, without weakening the schema:** (a) `RequirementSynthesisProposal` **still rejects** an `authority` field — the §9.2 property is intact; (b) an **internally mis-assigned** `CANONICAL` on a non-human origin, injected at the runtime routing-input / decision-construction layer, is `REJECT` / `AUTHORITY_INVENTION` and does **not** fall through to a low-risk `APPLY`. No authority field is added to the proposal to make this constructible.
- `RESEARCH_DERIVED` treated exactly as `AI_INFERRED`.

**Provenance (I3)**
- per basis claim, one `DERIVED_FROM` relation and one edge; counts equal.
- **assert the edge parent equals `claim.created_by_judgment_id` and differs from `claim_id`.**
- `research_derived()` computed, not stored; adding non-research evidence via `SUPPORTS_CLAIM` flips it.

**Basis coverage (I17, C4)**
- **an unrelated claim at the same locus is not included merely because it is available** — the required C4 test.
- `basis_locus_ids` is runtime-derived and matches the claims' loci; a synthesizer-supplied value is impossible and a hand-built one is refused.
- a claim cited but not represented by the statement is caught in review; the test pins the runtime-checkable half (live, in scope, present in request).

**Disposition and duplicates (I18, C3)**
- **an equivalent existing Requirement yields `EXISTING_UNCHANGED` / `NO_CHANGE` and creates no duplicate durable intent** — object count unchanged, no new relation, no new edge.
- **a stale Requirement is presented as reconciliation context** (`is_stale=True`) and is eligible for `REPLACES_STALE`.
- **replacement retires the intended stale Requirement and not another object** — with a sibling stale Requirement present in the same scope as a decoy.
- **an unrelated Requirement remains distinct** — not merged, not retired, not cited.
- `NEW` with `relates_to_object_id`, `EXISTING_UNCHANGED` on a stale object, and `REPLACES_STALE` on a non-stale object are each structural failures.

**Crash consistency (I16, I20, C1, C7, C10)** — interruption at **every** persistence boundary of the current lifecycle
- interrupt **before `INTENT_SYNTHESIS_DECIDED` lands**: nothing durable, no decision exists, **no recovery state** — the run is simply recomputed from scratch. (The pre-C12 `PROPOSED`-without-decision boundary no longer exists and is not tested.)
- interrupt **after `DECIDED(APPLY)`, before `SYNTHESIZED` / `INVALIDATED`**: proposal in `incomplete_proposal_ids`; **handoff v2 refuses**; recovery **reads the recorded decision and never re-routes**, then completes it as applied or invalidated.
- **negative control:** no interruption can produce an object with a partial edge set — object and edges arrive in one event.
- **`REPLACES_STALE` specifically (I20):** interrupt mid-`SYNTHESIZED` on a replacement and assert the state "replacement exists, target still live, no `RetirementRecord`" is **unrepresentable**; assert `incomplete_proposal_ids` never reports a replacement as complete while its retirement is missing.
- **idempotent recovery (C10):** a second `resume_incomplete_synthesis()` after completion is a **no-op success**, not an exception, and leaves state byte-identical.
- **race backstop:** a concurrent completion between recovery's read and write surfaces as success to the caller, with `DuplicateEventError` caught internally.
- every interrupted-then-resumed run reaches a final state byte-identical to an uninterrupted run.
- `EventStore`, both adapters and their tests are unchanged.

**Durable identity (I21, C8)**
- the same `model_proposal_id` in two different projects yields **different** `proposal_instance_id`, `object_id` and `event_id`; no cross-project collision.
- the same `model_proposal_id` in two different synthesis runs of one project yields different ids.
- an interrupted run reproduces **byte-identical** ids on recovery, with **zero** provider calls.
- a duplicate `model_proposal_id` within one result is a structural failure for the whole result.
- **negative control:** assert no durable id is a pure function of the raw `model_proposal_id`.

**Authorship and anti-laundering (I22, C9)**
- **the required negative test:** a `CANONICAL`, human-provenanced basis claim plus an **AI-produced** synthesis statement remains `AI_INFERRED` / `PROPOSED`, and **cannot** reach `CANONICAL` through the `HUMAN_STATED` path.
- `author` is attached by runtime from the synthesizer's fingerprint; a model-supplied author is unrepresentable and a hand-built one is refused.
- a non-human author with a supplied `human_actor_id`, and a human author without one, are each structural failures.
- `author` is durable on the proposal record and sufficient for `independent()` to evaluate two authors (the durable input D3 will need).

**Canonical authority preservation (I23, C11)** — required negative controls
- **an AI `PROPOSED` replacement cannot retire a stale `CANONICAL` Requirement** — routing refuses before `APPLY`.
- the canonical target **remains live, stale and blocking** after such an attempt.
- **a `PROPOSED` head does not reconcile a `CANONICAL` stale chain** (§15.6 condition 6).
- a **human-authorized `CANONICAL` replacement** retires it and clears delivery.
- **end-to-end negative control: no AI path can remove an obligation from `CanonicalIntentPackage`** — `obligation_ids` before and after an attempted non-canonical replacement are identical.
- reducer layer independently: a hand-built `INTENT_OBJECT_SYNTHESIZED` retiring a `CANONICAL` object with a non-`CANONICAL` replacement is refused by the dry-run — proving the defence does not rely on routing alone.
- assert **no total ordering over `Authority`** is introduced; the check is a `CANONICAL` equality test.

**Lifecycle totality and terminal invalidation (I24, C13)**
- `DECIDED(APPLY)` → basis claim superseded by another worker → recovery emits `INTENT_SYNTHESIS_INVALIDATED(BASIS_CHANGED)`; **the proposal leaves `incomplete_proposal_ids` and handoff v2 becomes deliverable again** — the anti-deadlock test.
- `TARGET_CHANGED`: the replacement target is retired or ceases to be stale before effect.
- `AUTHORITY_CHANGED`: the target/replacement authority relationship stops satisfying §10.7.
- invalidation **creates and retires nothing** — `objects`, `derivations` and `retirements` are unchanged.
- **partition (C16):** at **every** replayed snapshot, applied / invalidated / incomplete are pairwise disjoint and jointly cover every durable `DECIDED(APPLY)`.
- **recovery terminality (C16):** after a **successful** recovery pass, each processed proposal is applied **xor** invalidated. Separately, assert that bounded-retry exhaustion legitimately **leaves** a proposal incomplete and that a subsequent recovery invocation resumes it — the spec claims a reachable exit, not automatic progress.
- an invalidated proposal is **not** retried automatically; resolving the intent requires a fresh synthesis run.
- the invalidation reason is drawn from the bounded enum — never free text.

**Concurrency (I25, C14)**
- **unrelated concurrent append** during recovery raises `ConcurrencyError` → reload → recompute → revalidate → retry succeeds. **Byte-equivalence is pinned against a matched baseline (C18):** the baseline history contains the *same* synthesis work **and the same unrelated event**, serialized without collision; the race history contains the *same logical events* with the unrelated one landing between read and append. The two reconstructed final states must be byte-identical. **No event may be dropped or ignored to make the equality pass** — comparing against a history that lacks the unrelated event would be comparing different ledgers.
- `ConcurrencyError` where revalidation now **fails** → terminal invalidation, not a spin.
- **bounded retry:** exhaustion at the `SYNTHESIZED` step leaves the proposal incomplete and retriable by the next recovery run — never corrupt, never silently dropped; exhaustion at the `DECIDED` step leaves **nothing durable**.
- **same-item completion race** still treats `DuplicateEventError` as success (the C10 semantics, retained).
- **no provider call is required during any recovery path** — asserted across every concurrency test.
- **decision durability (C12):** a decision is never recomputed once durable; assert recovery reads the recorded decision rather than re-routing, and that an `AuthorityRecord` revoked after `DECIDED` does **not** silently change the recorded decision — it surfaces as `AUTHORITY_CHANGED` invalidation.

**Reconciliation clears delivery (I19, C6)** — the required end-to-end test
- claim correction → old Requirement stale → **v2 handoff refuses** → `REPLACES_STALE` creates a valid replacement and retires the old object → the old historical stale id **no longer blocks** → **v2 handoff emits successfully**.
- **negative control:** a stale Requirement retired **without** a valid replacement still blocks delivery.
- **negative control:** a replacement that is **itself stale** does not reconcile its predecessor (condition 5).
- a chain of successive reconciliations resolves to its head; a cyclic chain terminates and does not hang.
- the old id appears in `reconciled_stale_object_ids`, not silently dropped.
- `scoped_stale_object_ids` and `build_semantic_readiness` return **identical** results before and after the v2 rule exists — `domain/handoff.py` is unchanged and its tests pass untouched.

**Supersession and reconciliation (I5, C2)**
- after the replacing `INTENT_OBJECT_SYNTHESIZED`, the retired object's **projection** is `SUPERSEDED` with `revision+1` — asserting the projection *moves*, the opposite of the earlier false claim.
- the creation event is byte-identical in the log afterwards.
- **replay to the pre-supersession sequence reproduces the retired object exactly** as it stood.
- the replacement has a distinct `object_id`.
- **negative control (I13):** a compatible extension at a basis locus leaves the object non-stale and emits no gap.

**Gaps (I10)**
- `DISPUTED` → `CONTRADICTION` and **zero** proposals; `UNDECIDED` → `MISSING_INFORMATION`; unformable statement → `AMBIGUITY` via `AMBIGUITY_DETECTED`.
- `EXISTING_UNCHANGED` emits **no** gap.

**Contract (I8)**
- `PROPOSED` Requirement absent from `obligation_ids`; `LOW` does not block closure, `MEDIUM` does; canonical Requirement with `requires_metric=False` closes without a `Metric`; `Actor` still in `purpose_ids`.

**Handoff (I9, I11)**
- v2 refuses for each blocking condition separately: stale, disputed, pending, **incomplete synthesis**.
- v2 emits when ready; `intent_basis` matches recorded relations and runtime-derived loci.
- field inspection: no free-text semantic field anywhere in v2.
- `domain/handoff.py` byte-unchanged; all `test_handoff.py` pass.

**Determinism (I7)**
- replay reproduces objects, edges, `intent_synthesis`, closure, package and handoff byte-identically.
- `route_intent_synthesis` purity: same inputs → same decision; state not mutated.
- deterministic `object_id` / `event_id`: the same **`(project_id, synthesis_run_id, model_proposal_id)`** reproduces byte-identical ids — which is what makes recovery exactly-once. Two **different runs**, and two **different projects**, sharing one `model_proposal_id` produce **different** ids (I21).
- zero provider calls across the suite.

**Regression locks (must pass unchanged)**
`tests/unit/test_compatible_extension_lifecycle.py` in full — in particular `test_address_granularity_same_locus_new_proposition_is_one_address_two_claims` and `test_several_compatible_claims_coexist_and_a_byte_identical_reassert_is_refused` — plus `test_closure.py`, `test_package.py`, `test_handoff.py`, `test_semantic_view.py`, `test_reducer.py`, `test_evidence.py`, `tests/e2e/test_replay_to_package.py`. **Claim atomicity, reducer behaviour and v1 behaviour must not move.**

---

## 26. Out of scope

1. `Metric` and `VerificationObligation` synthesis; any metric or verifier design.
2. Every intent-bearing kind except `Requirement` — each needs its own proposal variant and design before entering `allowed_target_kinds` (C5).
3. `Actor` synthesis — canonical intent context, not an intent-bearing commitment (D1).
4. **Any change to `locus-validation-v1`.** Its outcome is permanently `LOCUS_POLICY_NOT_VALIDATED`. It is not re-adjudicated, reinterpreted or replaced. Any future evaluation of its frozen evidence under corrected granularity rules must be a **separately named successor or post-hoc artifact** and must never be presented as changing the original outcome.
5. The Research Worker itself — planning, job routing, budget policy, source selection, retrieval, reconciliation.
6. Deterministic normalization (§11 defines the fence; nothing is built under it).
7. Multi-claim and cross-locus bases in slice 1 (the contracts support them; the slice does not exercise them).
8. Migrating any consumer from handoff v1 to v2.
9. Changes to `EventStore`, either adapter, `domain/handoff.py`, or the `REQUIREMENT_SUPERSEDED` reducer branch.
10. Changes to any prompt, `POLICY_VERSION`, prompt hash or output-schema hash.
11. A successor locus-policy validation experiment.
12. Materiality thresholds and corroboration policy (D3, D4).
13. Compatible-extension completeness semantics (D5).
14. Retrofitting the §10.6 protocol onto `SemanticGovernor.submit()`'s existing two-event sequence — a pre-existing condition (D10), deliberately not widened into here. Note that C12's collapse is the pattern `submit()` would adopt if D10 is ever taken up.
15. Any total ordering over `Authority`; §10.7 introduces only preservation of `CANONICAL` (C11).

---

## 27. Open decisions

**Blocking work beyond slice 1 — not blocking slice-1 planning:**

| # | decision | status |
|---|---|---|
| **D3** | Materiality and corroboration policy for material inferred intent: which target kinds and levels are material; does independent corroboration suffice or is a human always required? | Slice 1 pinned conservatively (§17.4); anything wider is blocked. |
| **D4** | Who assigns `materiality` to a synthesized `Requirement`, on what basis; defaults for `requires_metric` / `requires_verification`. | Slice 1 pins `LOW` / `False` / `False`. |

**Not blocking slice 1; must be resolved before broader use:**

| # | decision |
|---|---|
| **D5** | Compatible-extension semantics (§15.5). Slice-1 behaviour pinned by I13. |
| **D8** | Object-level retirement outside synthesis. Retirement is now folded into `INTENT_OBJECT_SYNTHESIZED` (C7) and is therefore fully covered for every synthesis path and every intent-bearing kind. What remains open is retirement for **non-synthesis** paths, where only the `Requirement`-specific `REQUIREMENT_SUPERSEDED` exists. Not a blocker for synthesis. |
| **D11** | The exact bounded-retry constant for C14 (§10.6). The precedent is `MAX_ATTEMPTS_PER_CASE = 2`; synthesis retries are cheaper, so a small bound above it is appropriate. A plan-time decision, not a design one. |
| **D6-R** | **APPROVED on review of `9846b76a`.** Recorded in §0: v2 gates on `IntentDeliveryReadiness.deliverable` rather than the literal `SemanticReadiness.ready`, because the latter is unsatisfiable after any reconciliation (§15.6). Directed by the architect in review; listed so the confirmation is explicit. |
| **D9** | `KnownIntentObject` snapshot cap (§8) — numeric bound, a plan-time decision. |
| **D10** | Whether `SemanticGovernor.submit()`'s pre-existing two-event non-atomicity should adopt the §10.6 protocol. Out of scope here (§26.14); recorded because §10.6 makes the pattern available. |
| **D7** | Migration timing for v2 downstream. Design-settled (coexist; v2 after independent proof); timing remains open. |

**Settled by ruling, recorded for traceability:** D1 (Actor stays contract-relevant context, not intent-bearing), D2 (superseded — `Decision` is out of slice 1; `INTENT_OBJECT_SYNTHESIZED` resolves non-canonical recording generally), D6 (handoff v2 gates on readiness; `evaluate_closure` unchanged).

---

## 28. Self-review: contradiction audit

Performed before commit across the seven areas named in review.

**Crash consistency.** The dangerous state — object without complete edges — is removed *by construction* (one event), not mitigated by convention. The one surviving interruption window — `DECIDED(APPLY)` → `SYNTHESIZED` | `INVALIDATED` — is argued safe, detectable and completable, and carries a required test. Exactly-once rests on deterministic ids plus the existing `DuplicateEventError`, which both adapters enforce before the sequence check, so no new port method is introduced. §10.6 states plainly that the hazard pre-exists in `submit()` and that this spec does not fix it there — recorded as D10 rather than silently widened. *No contradiction.*

**Duplicate intent.** `EXISTING_UNCHANGED` + `NO_CHANGE` is a success path that writes nothing; §16 explicitly states it is not a gap, preventing the natural misreading that de-duplication is a failure. Every illegal disposition/staleness combination is enumerated in §9.3 and mirrored in §23. *No contradiction.*

**Reconciliation.** `is_stale` is runtime-derived and is what makes `REPLACES_STALE` decidable; §9.3 forbids affirming a stale object as unchanged, closing the loop where a stale commitment could otherwise be frozen forever. Retirement targets exactly the named object, with a decoy test. *No contradiction.*

**Provenance and blast radius.** §12.1 uses `claim_id`; §12.2 uses `created_by_judgment_id`. The asymmetry reads like an inconsistency and would invite a cleanup that silently breaks staleness, so §12.3 states the reason, forbids the change, and the test asserts the parent is *not* the claim id. Edges are now reducer-derived, which strengthens this: they cannot desynchronise from claims even in principle. §13.2 adds the converse discipline — citing more than the statement represents is as much a defect as citing less, and the spec names the harm (false-positive staleness) rather than asserting a rule without a reason. *No contradiction.*

**Trust-boundary ownership.** `authority`, `scope`, `basis_locus_ids`, `object_id`, `provenance`, `relations`, `materiality` are all runtime-owned, and §9.2 states the schema cannot express them. The rule is uniform: *structural facts Foundry already knows are runtime-owned; meaning is proposed.* Disposition is the one judgement the synthesizer supplies about existing objects, and runtime validates it against `is_stale`, so the synthesizer proposes a relationship but can never assert staleness. *No contradiction.*

**Replay exactness.** Non-determinism is confined to the synthesizer; everything downstream is a pure function of recorded events. Reducer-derived edges and deterministic ids both strengthen replay rather than threatening it. §22.5 ties the deterministic-id requirement to both recovery and replay so the two cannot drift apart. *No contradiction.*

**Event honesty.** One authority-neutral event replaces the earlier `INTENT_OBJECT_PROPOSED` + specialized-canonicalization split, so the ledger never labels a `PROPOSED` object "canonicalized". The `RetirementRecord` written inside that same event records `replaced_by_object_id`, so the replacement link is projectable rather than only recoverable from history — which is what makes §15.6 decidable. The existing specialized events keep their meaning and their non-synthesis role. *No contradiction.*

**Altitude.** §3 forbids extending `JudgmentKind`; §12.2 has synthesis writing `DerivationEdge`s into `state.semantic`. I14 names this exception precisely: derivation edges are the generic cross-engine hook `derivation.py` was explicitly built for ("future engines … attach to"), not semantic content. A separate `IntentSynthesisRoute` is introduced rather than extending `AdmissionRoute`, keeping the semantic vocabulary untouched. *No contradiction.*

**Second-round audit (C6-C10).**

*Reconciliation termination.* The previous version described reconciliation without checking that it terminates. It did not: a retired object's id stays in `view.stale_ids` permanently, so a reconciled scope could never deliver. §15.6 fixes this with proof-of-reconciliation rather than by ignoring superseded ids — condition 1 requires a `RetirementRecord` that only the atomic replacement event can write, and condition 5 requires the chain head not to be stale itself. `domain/handoff.py` is untouched and its outputs are asserted unchanged. *No contradiction; a real deadlock removed.*

*Replacement atomicity.* Folding retirement into `INTENT_OBJECT_SYNTHESIZED` removes the last window in which `applied_proposal_ids` could mark a proposal complete while required work was missing. This also makes §15.6 sound: the `RetirementRecord` cannot exist without its replacement, nor the replacement without the record, so reconciliation evidence cannot be half-formed. C7 and C6 are mutually reinforcing rather than independent fixes. *No contradiction.*

*Identity.* Durable ids no longer depend on model-chosen values, closing both a collision hazard (global `event_id` uniqueness across projects and runs) and a trust hazard (model influence over durable identity). Recovery determinism is preserved because `synthesis_run_id` is persisted in `INTENT_SYNTHESIS_DECIDED`, so recomputation needs no provider call. *No contradiction.*

*Authorship.* Origin now follows the author, never the basis. This closes the laundering path in which a `CANONICAL` human basis claim could have been read as making a model-written statement `HUMAN_STATED`. The rule is stated as an absolute with no policy escape, and the negative test pins it. Reusing `ReasonerFingerprint` also gives D3 the durable author identity independence testing requires, rather than deferring that problem. *No contradiction.*

*Recovery idempotency.* The earlier text was self-contradictory — prose claimed idempotence while the test expected an exception. Recovery is now idempotent at the operation level, with `DuplicateEventError` demoted to a race backstop caught internally. *Contradiction found and removed.*

**Third-round audit (C11-C14).**

*Authority preservation.* §10.3 stopped canonical authority being **invented**; nothing stopped it being **deleted**. §10.7 closes the deletion path with a single equality check at three independent layers, and deliberately introduces no ordering over `Authority` — the minimum law that fixes the hole. I also recorded that today's apparent protection (`MISSING_CANONICAL_OBLIGATION`) is accidental and evaporates once a scope holds two canonical obligations, so no one later mistakes it for the safeguard. *No contradiction; a real authority hole closed.*

*Lifecycle partition.* C13 is the mirror of C6: both were states with no exit, one for stale objects and one for admitted decisions. Both are now closed by making the exit explicit and durable rather than implied. After C16, I24 is a **three-way snapshot partition**: every durable `DECIDED(APPLY)` belongs to exactly one of **applied**, **invalidated** or **incomplete**, the three being mutually exclusive and jointly covering. `incomplete` is a legal non-terminal member, not an omission. Any future lifecycle state must **explicitly extend the partition**, and if it can block delivery it must satisfy I24a with a defined legal exit. *No contradiction; a second deadlock removed.*

*Crash recovery and the purity error.* The previous version argued that re-routing after a crash was safe because `route_intent_synthesis` is pure. That was **wrong** — purity constrains outputs for identical inputs, and the inputs are live governance state. Rather than patch the argument by persisting enough context to make re-routing defensible, C12 removes the state that required the argument: decision and proposal are one event appended at a checked sequence, so a decision and the state it was computed from are the same durable fact. The spec now says explicitly that purity is **not** load-bearing for recovery, so the discredited reasoning cannot creep back. *Contradiction found and removed.*

*ConcurrencyError.* `DuplicateEventError` and `ConcurrencyError` are genuinely different races — same item versus unrelated append — and only the first was handled. Both are now specified, with bounded retry and a terminal fallback, so contention can delay completion but can never corrupt state, spin forever, or silently drop work. *No contradiction.*

*Delivery termination, checked as a whole.* Three independent ways existed for a scope to become permanently undeliverable: unforgettable stale ids (C6), a replacement whose retirement never landed (C7), and a durable decision that could never be effected (C13). All three now have explicit exits, and §18's gate reads exactly the five conditions those exits clear. *No contradiction.*

**Residual risks accepted, stated rather than hidden:**
- §15.5 (compatible extension) is unresolved *by intent*. Slice 1 does not exercise an evolving corpus, and I13 pins the behaviour so the decision cannot be made silently later.
- §13.2 coverage is **not** mechanically enforceable. The spec says so explicitly and pins only the runtime-checkable half, rather than implying a guarantee the code cannot provide.
- §15.6 introduces a **second** readiness calculation alongside v1's. That is a real cost — two notions of "ready" now exist in the codebase. It is accepted because the alternative is mutating `domain/handoff.py`, which D7 forbids, and because v1's verbatim result is embedded in v2's so the two can be compared rather than silently diverging. If v1 is ever retired (D7 timing), the two should be reunified.
- §10.7 layer 2 compares two authorities inside the reducer. That is a whisker more semantics than "structural", and I accepted it: both values are already present in state and payload, the comparison needs no view derivation and no policy, and the alternative — trusting routing alone — would leave a hand-built event able to delete canonical intent.
- A non-canonical replacement for a canonical target leaves the scope **blocked** until a human authorizes a canonical replacement. That is deliberate: an unresolved canonical obligation must block rather than vanish. It does mean an AI cannot unblock such a scope alone, which is the intended cost.
- The `RetirementRecord` chain is followed transitively with a visited set. Chain depth is unbounded in principle; it is bounded in practice by the number of reconciliations in a scope, and the cycle-safety test pins termination. No depth limit is imposed, because an arbitrary limit would silently block a legitimately long-lived commitment.
