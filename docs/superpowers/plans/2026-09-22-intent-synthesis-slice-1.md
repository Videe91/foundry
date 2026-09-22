# Intent Synthesis — Slice 1 Implementation Plan (Requirement only)

**Status:** Plan awaiting review. **No code written.** No provider calls, no live experiments.

**Design spec:** `docs/superpowers/specs/2026-09-22-intent-synthesis-bridge-design.md` — approved for Slice-1 implementation planning on 2026-09-22 (C1-C14, D6-R approved).

**Base branch:** `feat/intent-intelligence-v2`

**Base commit:** `a177052c961cc0c4b4f823fb2d6d938bba74c9ea`

**Slice:** synthesize `Requirement` **only**. No other intent-bearing kind enters `allowed_target_kinds`.

---

## 1. Scope

Build the end-to-end path of spec §17.2 and nothing more:

```
live CANONICAL human-provenanced claim
  -> HUMAN_STATED synthesis (disposition NEW)
  -> CANONICAL Requirement, LOW materiality, requires_metric=False, requires_verification=False
  -> dual provenance in ONE atomic event
  -> evaluate_closure closes                    [unchanged]
  -> build_intent_package emits the contract    [unchanged]
  -> IntentDecisionHandoff v2 emits, gated
```

Plus the four proofs of §17.3 — authority boundary, blast radius, no-duplicate, crash consistency — and the C11-C14 behaviours: canonical preservation, decision durability, lifecycle totality, both concurrency races.

---

## 2. Plan-time decisions

### D11 — bounded retry (ruled by the architect)

```
MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS: Final[int] = 3   # 3 TOTAL attempts, not 3 retries
```
Attempt 1 plus at most 2 further attempts. Exhaustion behaviour per spec §10.6: at `DECIDED` nothing is durable and a typed error is raised; at `SYNTHESIZED` the proposal stays incomplete and retriable by the next recovery run.

### D9 — `KnownIntentObject` snapshot cap, **derived from the existing envelope**

The codebase already bounds request context in **two** complementary ways, both of which **refuse and never truncate, rank or fall back**:

| existing bound | value | measured on | refusal |
|---|---|---|---|
| `CANDIDATE_ADDRESS_THRESHOLD` (`application/assimilation_context.py:86`) | `200` | count of active in-scope addresses, checked **before** compiling | `ContextUnsupported("UNSUPPORTED_ABOVE_THRESHOLD: …")` |
| `MAX_COMPARISON_CONTEXT_CHARS` (`application/contrastive_context.py:58`) | `131_072` | canonical JSON of the compiled context | `ContextUnsupported("UNSUPPORTED_COMPARISON_CONTEXT: …")` |

Slice 1 adopts **both forms, mirrored exactly**, because `known_intent_objects` occupies the same two slots: it is the "what already exists in this scope, shown in full" set (the direct analogue of the candidate-address set) and it is request-only compiled context (the analogue of `ComparisonContext`).

```
KNOWN_INTENT_OBJECT_THRESHOLD:     Final[int] = 200        # == CANDIDATE_ADDRESS_THRESHOLD
MAX_KNOWN_INTENT_CONTEXT_CHARS:    Final[int] = 131_072    # == MAX_COMPARISON_CONTEXT_CHARS
```

Both values are **taken from existing constants rather than invented**, with a stated reason: there is no principled ground for bounding intent objects in a scope differently from addresses in that scope, nor for bounding this compiled context differently from the sibling compiled context that already ships. Character count is measured by the identical canonical rendering (`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`), and both overflow paths raise the existing `ContextUnsupported`. If slice-1 evidence shows either bound wrong, it is a one-constant change.

### Plan-time decisions arising from the audit (§7)

| id | decision |
|---|---|
| **P1** | `_covering_authority_record` **cannot** be reused as-is: it takes a `SemanticJudgment` and derives scope via `_target_scope(state, judgment.proposal)`, which switches over `JudgmentProposal` types a synthesis proposal does not have. It is extracted and **generalized** to `covering_authority_record(state, *, actor_id: str, target_scope: tuple[str, ...] | None)`, with `admission.py` calling it with its existing derived values. Precedent: `authority_record_is_live` is already public and shared "so the two can never drift". |
| **P2** | The synthesis orchestrator gets its **own** appender rather than reusing `SemanticGovernor._append`, because that method mints random event ids via `self._id_factory(prefix)` and Slice 1 requires deterministic ids (I21) and caller-controlled `expected_sequence` (C12). `semantic_governance.py` is **not** modified. A test asserts both appenders refuse an unreplayable event identically, so the dry-run discipline cannot drift. |
| **P3** | The I19 reconciliation test must use a **human-authored `CANONICAL` replacement**, because §10.7 forbids a non-canonical replacement from retiring a `CANONICAL` target. Written with an AI replacement the test would be unsatisfiable by design. Recorded so it is not discovered late. |
| **P4** | `evaluate_closure` still closes while a derived Requirement is stale (it is `ACTIVE`/`CANONICAL`, and closure has no staleness concept). Only v2's gate blocks. This is spec §20.6 working as designed, not a defect, and the tests assert it explicitly so a later reader does not "fix" it. |
| **P5** | Reducer-level canonical preservation (§10.7 layer 2) compares `objects[replaces_object_id].authority` with `payload.object.authority`. Both are already in state and payload, so no view derivation is needed and the reducer stays cheap and replay-deterministic. |

---

## 3. Dependency order

Strict bottom-up; each layer is green before the next begins.

```
L0  enums + proposal types + identity          (pure domain, no deps)
L1  synthesis state + events + payloads        (depends on L0)
L2  IntentState field + reducer branches       (depends on L1)
L3  shared authority helper extraction         (independent; regression-locked)
L4  route_intent_synthesis                     (depends on L0, L2, L3)
L5  port types + request assembly + D9 bounds  (depends on L0)
L6  orchestrator + recovery                    (depends on L1-L5)
L7  handoff v2 + reconciliation readiness      (depends on L2, L6)
L8  end-to-end vertical                        (depends on all)
```

---

## 4. Task breakdown — RED first, every task

Every task: **write failing tests first, confirm RED for the stated reason, then implement to GREEN, then `ruff` + `mypy --strict` clean.** No task is complete while any regression lock fails.

### T1 — Vocabulary and identity (L0)
**RED:** `tests/unit/test_intent_synthesis_types.py`
- `RequirementSynthesisProposal` is the only variant; `target_kind` is `Literal[REQUIREMENT]`.
- schema **cannot** express `authority`, `author`, `basis_locus_ids`, `scope`, `object_id`, `provenance`, `materiality` (`extra="forbid"` rejects each).
- `basis_claim_ids` `min_length=1`.
- disposition/`relates_to_object_id` legality matrix (§9.3), all five illegal combinations.
- **I21:** identical `model_proposal_id` in two projects, and in two runs of one project, yield different `proposal_instance_id`; same `(project, run, model id)` reproduces byte-identically; duplicate `model_proposal_id` within one result is refused.
- **negative control:** no durable id is a pure function of the raw `model_proposal_id`.

**GREEN:** `domain/intent_synthesis.py` — `SynthesisOrigin`, `IntentDisposition`, `IntentSynthesisRoute`, `InvalidationReason`, `IntentSynthesisProposal`, `RequirementSynthesisProposal`, `IntentSynthesisResult`, `SynthesisIdentity`, `IntentSynthesisPolicy`, `IntentSynthesisDecision`.

### T2 — Synthesis state projection (L1)
**RED:** `tests/unit/test_intent_synthesis_state.py`
- `IntentSynthesisState` empty by default; frozen mappings like `SemanticState`.
- `incomplete_proposal_ids` = `APPLY` ∧ ¬applied ∧ ¬invalidated.
- **I24 totality:** applied and invalidated sets are disjoint; every `APPLY` lands in exactly one; non-`APPLY` routes never appear.
- `RetirementRecord` shape and append-only behaviour.

**GREEN:** `domain/intent_synthesis_state.py`.

### T3 — Event vocabulary (L1)
**RED:** `tests/unit/test_intent_synthesis_events.py`
- three new `EventType`s; `EVENT_PAYLOAD_TYPES` entries; envelope validation rejects mismatched payloads.
- `INTENT_OBJECT_SYNTHESIZED` restricted to the ten intent-bearing kinds; **I15** rejects a non-intent kind.
- `IntentObjectPayload.basis_claim_ids` `min_length=1`; `replaces_object_id` optional.
- `InvalidationReason` is a bounded enum — free text rejected.
- project-mismatch rejection (existing `_reject_project_mismatch` law).
- JSON round-trip through `parse_event` (the in-memory store's law).

**GREEN:** `domain/events.py` — additive only; existing types, `SPECIALIZED_SEMANTIC_KIND_BY_EVENT` and `GENERIC_SEMANTIC_KINDS` untouched.

### T4 — Reducer: atomic application (L2)
**RED:** `tests/unit/test_intent_synthesis_reducer.py`
- **I3/I12.5:** applying `INTENT_OBJECT_SYNTHESIZED` writes the object **and** one `DerivationEdge` per basis claim in **one** event; the three counts are equal.
- **I3 critical:** edge `parent_id == claims[cid].created_by_judgment_id` and **`!= claim_id`**.
- **I20/C7:** with `replaces_object_id`, the same single event writes object + edges + retirement (`SUPERSEDED`, `revision+1`) + `RetirementRecord` + applied marker.
- **I5/C2:** the retired object's **projection moves**; replay to the pre-supersession sequence reproduces it exactly; the replacement has a distinct id.
- **I23 layer 2:** a hand-built event retiring a `CANONICAL` object with a non-`CANONICAL` replacement is **refused**.
- structural refusals: unknown basis claim, unknown/non-current/out-of-scope/already-retired target.
- `INTENT_SYNTHESIS_INVALIDATED` creates and retires nothing.
- **regression:** the `REQUIREMENT_SUPERSEDED` branch is byte-unchanged and `test_reducer.py` passes untouched.

**GREEN:** `domain/state.py` (additive `intent_synthesis` field), `application/reducer.py` (new branches only).

### T5 — Shared authority helper (L3)
**RED:** `tests/unit/test_authority_coverage.py`
- `covering_authority_record(state, actor_id=…, target_scope=…)` matches the current `_covering_authority_record` on every existing case: liveness, `authorized_by` match, project-wide `()` scope, scope intersection, dead authorities.
- **regression lock:** the entire existing `tests/unit/test_admission.py` passes unchanged.

**GREEN:** extract and generalize per **P1**; `admission.py` calls the shared function with its existing derived values. Behaviour-preserving refactor only — no routing rule changes.

### T6 — Routing (L4)
**RED:** `tests/unit/test_intent_synthesis_routing.py`
- **I2:** `HUMAN_STATED` + covering record → `CANONICAL`/`APPLY`; without → `REQUIRE_HUMAN`/`AUTHORITY_UNRESOLVED`; `AI_INFERRED` → `PROPOSED`.
- **I2 negative control:** a directly constructed non-human `CANONICAL` proposal → `REJECT`/`AUTHORITY_INVENTION`; assert it does **not** reach a low-risk `APPLY`.
- **I22 required negative test:** `CANONICAL` human basis claim + **AI-produced** statement stays `AI_INFERRED`/`PROPOSED` and cannot reach `CANONICAL` via `HUMAN_STATED`.
- **I22:** non-human author with `human_actor_id`, and human author without one, are structural failures; `author` is unspoofable.
- **I23 layer 1:** `REPLACES_STALE` on a `CANONICAL` target with non-`CANONICAL` replacement → `REQUIRE_HUMAN`/`CANONICAL_REPLACEMENT_REQUIRED`; assert **no total ordering over `Authority`** (the check is a `CANONICAL` equality).
- **I18:** `EXISTING_UNCHANGED` → `NO_CHANGE`, writes nothing.
- **I10:** purity — same inputs, same decision; state not mutated.

**GREEN:** `route_intent_synthesis` in `domain/intent_synthesis.py`.

### T7 — Port and bounded request assembly (L5)
**RED:** `tests/unit/test_intent_synthesis_context.py`
- request excludes non-live claims, out-of-scope loci, and `DISPUTED`/`OPEN`/pending/stale loci (assert the synthesizer is **not** called).
- **I12:** two addresses merged by an active `EQUIVALENT` produce **one** `LocusBasis` keyed on `representative_id`.
- **C3 `is_stale`:** correct for an `ACTIVE` object whose basis was superseded.
- `KnownIntentObject` excludes rationale, provenance, revision, timestamps; `Decision` would use `statement`, not `rationale`.
- **D9:** above `KNOWN_INTENT_OBJECT_THRESHOLD` → `ContextUnsupported`; above `MAX_KNOWN_INTENT_CONTEXT_CHARS` → `ContextUnsupported`; **never truncated**.
- **I6:** derived scope = union of basis address scopes.
- **I17/C4:** `basis_locus_ids` is runtime-derived and matches the claims' loci; **an unrelated claim at the same locus is not included merely because available.**

**GREEN:** `ports/intent_synthesizer.py`, `application/intent_synthesis_context.py`.

### T8 — Orchestrator: decide + apply (L6)
**RED:** `tests/unit/test_intent_synthesis_orchestrator.py`
- **C12:** decision computed against state at `N` and appended at `expected_sequence=N`; **one** `INTENT_SYNTHESIS_DECIDED` carries proposal + author + identity + decision.
- **C12:** a decision is **never recomputed once durable** — recovery reads the recorded decision rather than re-routing; an `AuthorityRecord` revoked after `DECIDED` surfaces as `AUTHORITY_CHANGED` invalidation, never a silently changed decision.
- **I1:** basis revalidated at apply time; a claim that went non-live is not applied.
- **I13 negative control:** a compatible extension at a basis locus leaves the object non-stale and emits no gap.
- **I10/§16:** `DISPUTED` → `CONTRADICTION` gap and **zero** proposals; `UNDECIDED` → `MISSING_INFORMATION`; `EXISTING_UNCHANGED` emits **no** gap.
- **zero provider calls** (scripted fake synthesizer, `SpecReasoner` pattern).

**GREEN:** `application/intent_synthesis.py` — `synthesize_intent`, own appender per **P2**.

### T9 — Crash recovery, invalidation, concurrency (L6)
**RED:** `tests/unit/test_intent_synthesis_recovery.py` — the heart of C1/C13/C14/C10
- **I16:** interrupt before `DECIDED` lands → nothing durable; interrupt after `DECIDED(APPLY)` before `SYNTHESIZED` → in `incomplete_proposal_ids`, **v2 refuses**, recovery completes.
- **I16/I20 negative controls:** no interruption yields a partial edge set; no interruption yields replacement-without-retirement.
- **I24/C13:** basis superseded by another worker between `DECIDED(APPLY)` and effect → `INTENT_SYNTHESIS_INVALIDATED(BASIS_CHANGED)`; **proposal leaves `incomplete_proposal_ids` and v2 becomes deliverable** — the anti-deadlock test. Also `TARGET_CHANGED` and `AUTHORITY_CHANGED`.
- **I24 totality:** over a randomized interleaving, every `DECIDED(APPLY)` ends applied **xor** invalidated; sets disjoint and jointly exhaustive.
- **I25/C14:** unrelated concurrent append → `ConcurrencyError` → reload → recompute → revalidate → retry succeeds, final state byte-identical to uninterrupted; where revalidation now fails → terminal invalidation, not a spin; **`MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS = 3` total attempts** — exhaustion at `DECIDED` leaves nothing durable, at `SYNTHESIZED` leaves it incomplete and retriable.
- **I25/C10:** same-item race → `DuplicateEventError` caught internally → success; **a second `resume_incomplete_synthesis()` is a no-op success, not an exception.**
- **no provider call on any recovery path.**
- **I21:** an interrupted run reproduces byte-identical ids.

**GREEN:** `resume_incomplete_synthesis` in `application/intent_synthesis.py`.

### T10 — Handoff v2 and reconciliation readiness (L7)
**RED:** `tests/unit/test_handoff_v2.py`
- **I19 required end-to-end:** claim correction → Requirement stale → **v2 refuses** → human-authored `CANONICAL` `REPLACES_STALE` (per **P3**) → old id no longer blocks → **v2 emits**.
- **I19 negative controls:** retired **without** a valid replacement still blocks; a replacement that is **itself stale** does not reconcile its predecessor; **I23:** a `PROPOSED` head does not reconcile a `CANONICAL` chain.
- chain of successive reconciliations resolves to its head; a cyclic chain terminates.
- old id appears in `reconciled_stale_object_ids`, not silently dropped.
- v2 refuses on each condition separately: non-closure, disputed, pending, unreconciled stale, incomplete synthesis.
- **I9:** field inspection — ids only; no statement text, claim value, rationale or evidence content.
- **I11 regression:** `domain/handoff.py` byte-unchanged; `scoped_stale_object_ids` and `build_semantic_readiness` identical before and after; all `test_handoff.py` pass.

**GREEN:** `domain/handoff_v2.py`.

### T11 — End-to-end vertical (L8)
**RED:** `tests/integration/test_intent_synthesis_slice1.py`
- the full §17.2 chain to a delivered handoff.
- **I8:** `PROPOSED` Requirement absent from `obligation_ids`; `LOW` does not block closure, `MEDIUM` does; canonical Requirement with `requires_metric=False` closes without a `Metric`; **`Actor` still in `purpose_ids`**.
- **I23 end-to-end:** no AI path removes an obligation from `CanonicalIntentPackage` — `obligation_ids` identical before and after an attempted non-canonical replacement.
- **P4:** closure still closes while the derived Requirement is stale; only v2's gate blocks — asserted explicitly.
- **I4:** fan-out — one claim supporting N objects marks all N stale.
- **I14:** synthesis emits no `SemanticJudgment` and writes nothing into `state.semantic` except `DerivationEdge`s.

### T12 — Replay, determinism, full regression (L8)
**RED:** `tests/unit/test_intent_synthesis_replay.py`
- **I7:** replay reproduces byte-identical `objects` (including retired projections), `semantic.derivations`, `intent_synthesis` (decisions, applied, invalidated, retirements), closure, `IntentDeliveryReadiness`, package and handoff v2.
- old event streams (no synthesis events) replay unchanged — the additive-field guarantee.
- **zero provider calls across the entire suite.**
- **regression locks green:** `test_compatible_extension_lifecycle.py` in full (especially `test_address_granularity_same_locus_new_proposition_is_one_address_two_claims` and `test_several_compatible_claims_coexist_and_a_byte_identical_reassert_is_refused`), `test_closure.py`, `test_package.py`, `test_handoff.py`, `test_semantic_view.py`, `test_reducer.py`, `test_admission.py`, `test_evidence.py`, `tests/e2e/test_replay_to_package.py`.

---

## 5. Invariant → task map

All 25 apply to Slice 1.

| invariant | task |
|---|---|
| I1 basis live | T8 |
| I2 no AI authority | T6 |
| I3 dual provenance (+ parent ≠ claim_id) | T4 |
| I4 staleness propagates, fan-out | T10, T11 |
| I5 log immutable / projection moves | T4 |
| I6 scope derived | T7 |
| I7 replay exactness | T12 |
| I8 contract purity | T11 |
| I9 no second ledger | T7, T10 |
| I10 gap-or-object exclusivity | T8 |
| I11 v1 frozen | T10, T12 |
| I12 locus keying | T7 |
| I13 extension inert | T8 |
| I14 altitude separation | T11 |
| I15 event honesty | T3 |
| I16 crash consistency | T9 |
| I17 basis coverage | T7 |
| I18 disposition integrity | T6, T10 |
| I19 reconciliation clears delivery | T10 |
| I20 no replacement without retirement | T4, T9 |
| I21 runtime-owned identity | T1, T9 |
| I22 anti-laundering | T6 |
| I23 canonical preservation | T4, T6, T10, T11 |
| I24 lifecycle totality | T2, T9 |
| I25 concurrency both races | T9 |

---

## 6. Files

**Created:** `domain/intent_synthesis.py`, `domain/intent_synthesis_state.py`, `domain/handoff_v2.py`, `ports/intent_synthesizer.py`, `application/intent_synthesis.py`, `application/intent_synthesis_context.py`, plus the test modules named in §4.

**Modified (additively):** `domain/events.py` (new types/payloads only), `domain/state.py` (one defaulted field), `application/reducer.py` (new branches only), `domain/admission.py` (**P1** behaviour-preserving extraction only).

**Not touched:** `ports/event_store.py`, both event-store adapters, `domain/handoff.py`, the `REQUIREMENT_SUPERSEDED` reducer branch, `domain/semantic*.py`, `domain/closure.py`, `application/package.py`, `application/semantic_governance.py`, `adapters/semantics/*`, every prompt/policy version/hash, every frozen experiment artifact.

---

## 7. Pre-commit audit

Run against the current codebase and the amended spec.

**No design contradiction found.** Five unspecified implementation shapes surfaced and are recorded as P1-P5 rather than papered over.

Checked and clear:
- **Canonical preservation vs. reconciliation:** the I19 test needs a `CANONICAL` replacement, which §10.2 makes reachable only via `HUMAN_STATED` + covering record. Satisfiable — recorded as **P3** so the test is not written unsatisfiably.
- **Closure vs. staleness:** closure still closes while a derived object is stale; only v2 blocks. Spec §20.6 as designed — **P4** pins it with an explicit assertion.
- **Additive state:** `intent_synthesis` defaults empty, so historical streams replay unchanged (T12).
- **`admission.py` edit:** permitted — it is not in the protected list and spec §10.4 explicitly requires the shared extraction; `authority_record_is_live` is the existing precedent for exactly this sharing. Regression-locked by `test_admission.py`.
- **Reducer remit:** §10.7 layer 2 compares two authorities already present in state and payload — no view derivation, replay stays deterministic (**P5**).

---

## 8. Definition of done

1. Every task GREEN, in dependency order.
2. All 25 invariants have passing tests, including every named negative control.
3. Every regression lock in T12 passes unchanged.
4. `ruff` and `mypy --strict` clean (`line-length = 100`, `strict = true`).
5. Zero provider calls in the suite; no network.
6. `git diff` touches no file in the "Not touched" list.
7. `allowed_target_kinds == {REQUIREMENT}` throughout.

---

## 9. Out of scope

Every item in spec §26, plus: the other nine intent-bearing kinds; `Metric`/`VerificationObligation`; deterministic normalization; multi-claim and cross-locus bases; migrating any consumer to v2; D3/D4 policy (blockers only for expansion beyond Slice 1); D5, D7, D8, D10.
