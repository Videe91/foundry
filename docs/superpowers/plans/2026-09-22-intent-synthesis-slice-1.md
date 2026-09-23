# Intent Synthesis — Slice 1 Implementation Plan (Requirement only)

**Status:** Plan awaiting review. **No code written.** No provider calls, no live experiments.

**Amended** after review of `de1c5b5d` with corrections C15-C18 and three bookkeeping fixes: the stale `incomplete_proposal_ids` formulation is removed in favour of the single §10.8 definition (C15); lifecycle totality is restated as a three-way snapshot **partition** with terminality moved to the recovery protocol (C16); the anti-invention negative control is rewritten so it exercises runtime-assigned authority **without** adding an `authority` field to the proposal schema (C17); concurrency byte-equivalence is pinned against a **matched** baseline containing the same unrelated event (C18); nine dependency layers, I24a counted and mapped, and the `HUMAN_STATED` definition made explicit against basis laundering.

**Design spec:** `docs/superpowers/specs/2026-09-22-intent-synthesis-bridge-design.md` — approved for Slice-1 implementation planning on 2026-09-22 (C1-C14, D6-R approved).

**Base branch:** `feat/intent-intelligence-v2`

**Base commit:** `a177052c961cc0c4b4f823fb2d6d938bba74c9ea`

**Slice:** synthesize `Requirement` **only**. No other intent-bearing kind enters `allowed_target_kinds`.

---

## 1. Scope

Build the end-to-end path of spec §17.2 and nothing more:

```
live CANONICAL human-provenanced claim              [basis only - confers NO origin]
  -> HUMAN_STATED synthesis (disposition NEW)
     = a human-AUTHORED or human-AFFIRMED synthesis proposal
       (author.is_human AND authenticated human_actor_id == author.model)
       PLUS a covering AuthorityRecord
  -> CANONICAL Requirement, LOW materiality, requires_metric=False, requires_verification=False
  -> dual provenance in ONE atomic event
  -> evaluate_closure closes                    [unchanged]
  -> build_intent_package emits the contract    [unchanged]
  -> IntentDecisionHandoff v2 emits, gated
```

**The basis claim's authority and provenance confer nothing.** A `CANONICAL`, human-provenanced basis claim never implies `HUMAN_STATED`: origin follows the **author of the synthesis proposal**, never its basis (spec §10.1, C9/I22 anti-laundering law). The slice-1 happy path is `HUMAN_STATED` because a human authors the proposal and holds a covering `AuthorityRecord` — not because the claim beneath it is canonical.

Plus the four proofs of §17.3 — authority boundary, blast radius, no-duplicate, crash consistency — and the C11-C14 behaviours: canonical preservation, decision durability, lifecycle partition, both concurrency races.

---

## 2. Plan-time decisions

### D12 — `Requirement.confidence` — **RESOLVED**

`RequirementSynthesisProposal.confidence` stays `float | None`. A synthesized
`Requirement` preserves it **exactly**: `0.72 → 0.72`, `None → None`. `None` means *no
numeric confidence was supplied* — it is **not** zero confidence, and the two are
distinguishable at every layer.

**No fallback is introduced.** `0.0` asserts no confidence, `1.0` asserts certainty,
`0.5` asserts a coin flip; each would fabricate an epistemic statement, attribute it to
the model, and make it durable and unreviewable.

**Why it resolves by widening `Requirement` alone:**

1. `SemanticJudgment.confidence` is already optional metadata;
2. `RequirementSynthesisProposal.confidence` is already optional metadata;
3. `SemanticClaim` carries no numeric confidence that could honestly be inherited;
4. routing explicitly does not read confidence (T6, asserted by an AST test);
5. closure and `CanonicalIntentPackage` never consult it — verified: the only
   `.confidence` reads in `src/foundry` are on `GapProposal`, never on a
   `SemanticObject`;
6. inventing a number would fabricate an epistemic statement;
7. therefore `Requirement` alone declares `confidence: float | None = None`.

`SemanticBase.confidence` stays **required** for every other kind — a negative control
pins that `Claim` and `Goal` still reject a missing confidence. Each future synthesized
intent kind must make its own explicit decision rather than inheriting this one.

**C20 binding completed.** The reducer now requires
`payload.object.confidence == record.proposal.confidence` exactly, `None == None`
included. Once `DECIDED` is durable the effect event must not rewrite even metadata.

**T8 construction rule, for when T8 begins:**

```python
Requirement(..., confidence=record.proposal.confidence, ...)
```

No computation, no inference, no lookup, no basis aggregation, no author-based
substitution. T8 carries the already-recorded metadata forward unchanged.

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
| **P1** | **Resolved in T5.** The shared primitive lives in **`domain/authority.py`** — a neutral leaf module, deliberately not in `intent_synthesis.py` and deliberately not reached through `admission.py`: `admission` depends on `IntentState`, which now reaches Intent Synthesis types, so an `intent_synthesis → admission` edge would run the wrong way and risk a cycle. `covering_authority_record(state, *, actor_id, target_scope)` holds the one coverage law; `authority_record_is_live` and `record_covers_scope` live beside it. `admission._target_scope` remains admission-specific and is the adapter from a `JudgmentProposal` to the generic target-scope input, with admission also keeping the human-actor check. T6 routing imports the shared primitive, **never** the admission router. Original finding: `_covering_authority_record` **cannot** be reused as-is: it takes a `SemanticJudgment` and derives scope via `_target_scope(state, judgment.proposal)`, which switches over `JudgmentProposal` types a synthesis proposal does not have. It is extracted and **generalized** to `covering_authority_record(state, *, actor_id: str, target_scope: tuple[str, ...] | None)`, with `admission.py` calling it with its existing derived values. Precedent: `authority_record_is_live` is already public and shared "so the two can never drift". |
| **P2** | The synthesis orchestrator gets its **own** appender rather than reusing `SemanticGovernor._append`, because that method mints random event ids via `self._id_factory(prefix)` and Slice 1 requires deterministic ids (I21) and caller-controlled `expected_sequence` (C12). `semantic_governance.py` is **not** modified. A test asserts both appenders refuse an unreplayable event identically, so the dry-run discipline cannot drift. |
| **P3** | The I19 reconciliation test must use a **human-authored `CANONICAL` replacement**, because §10.7 forbids a non-canonical replacement from retiring a `CANONICAL` target. Written with an AI replacement the test would be unsatisfiable by design. Recorded so it is not discovered late. |
| **P4** | `evaluate_closure` still closes while a derived Requirement is stale (it is `ACTIVE`/`CANONICAL`, and closure has no staleness concept). Only v2's gate blocks. This is spec §20.6 working as designed, not a defect, and the tests assert it explicitly so a later reader does not "fix" it. |
| **P6** | **R2 is deferred under the frozen-artifact compatibility exception (spec §3.1).** `domain/intent_synthesis.py` imports `GapProposal` from `foundry.intelligence.proposals`. `GapProposal` belongs in `domain/gaps.py`, but **both** relocation endpoints — `intelligence/proposals.py` (`contestant_a`, `e33a4255…`) and `domain/gaps.py` (`contestant_b`, `c37e9689…`) — are frozen contestant artifacts of the sealed comparative experiment; editing either raises `ExperimentFreezeViolation`. Preserving that evidence outranks layering cleanup. This is the **only** authorized `domain → intelligence` dependency, is **not** precedent for another, and the repair is deferred, not abandoned. `GapProposal` is not duplicated and `gap_proposals` is not removed from the result. Non-blocking for Slice 1. |
| **P5** | Reducer-level canonical preservation (§10.7 layer 2) compares `objects[replaces_object_id].authority` with `payload.object.authority`. Both are already in state and payload, so no view derivation is needed and the reducer stays cheap and replay-deterministic. |

---

## 3. Dependency order

Strict bottom-up across **nine** layers, L0 through L8; each layer is green before the next begins.

```
L0  enums + proposal types + identity          (pure domain, no deps)   [1/9]
L1  synthesis state + events + payloads        (depends on L0)
L2  IntentState field + reducer branches       (depends on L1)
L3  shared authority helper extraction         (independent; regression-locked)
L4  route_intent_synthesis                     (depends on L0, L2, L3)
L5  port types + request assembly + D9 bounds  (depends on L0)
L6  orchestrator + recovery                    (depends on L1-L5)
L7  handoff v2 + reconciliation readiness      (depends on L2, L6)
L8  end-to-end vertical                        (depends on all)        [9/9]
```

---

## 4. Task breakdown — twelve tasks across nine layers, RED first

Every task: **write failing tests first, confirm RED for the stated reason, then implement to GREEN, then `ruff` + `mypy --strict` clean.** No task is complete while any regression lock fails.

### T1 — Vocabulary and identity (L0)
**RED:** `tests/unit/test_intent_synthesis_types.py`
- `RequirementSynthesisProposal` is the only variant; `target_kind` is `Literal[REQUIREMENT]`.
- schema **cannot** express `authority`, `author`, `basis_locus_ids`, `scope`, `object_id`, `provenance`, `materiality` (`extra="forbid"` rejects each).
- `basis_claim_ids` `min_length=1`.
- **disposition legality — the SCHEMA-LOCAL half only (R1).** T1 can see a proposal and nothing else, so it owns exactly two rules: `NEW` must have `relates_to_object_id is None`, and `EXISTING_UNCHANGED` / `REPLACES_STALE` must supply one. Both illegal combinations are tested here.
- **not T1:** the three remaining §9.3 rules depend on the `known_intent_objects` snapshot and are assigned to **T7, before routing** (see T7). T1 must not be widened to enforce facts it cannot know.
- **I21:** identical `model_proposal_id` in two projects, and in two runs of one project, yield different `proposal_instance_id`; same `(project, run, model id)` reproduces byte-identically; duplicate `model_proposal_id` within one result is refused.
- **negative control:** no durable id is a pure function of the raw `model_proposal_id`.
- **T1.2 digest width:** every durable id carries the **full 64-hex SHA-256**, asserted against a recomputed canonical-JSON digest so a future refactor cannot silently narrow it. An earlier draft truncated to 16 hex (64 bits); that was never approved.
- **T1.2 separator injection:** `("P|R","X","Y")`, `("P","R|X","Y")` and `("P","R","X|Y")` yield three distinct ids — a bare `a|b` join collapses all three to one.

**GREEN:** `domain/intent_synthesis.py` — `SynthesisOrigin`, `IntentDisposition`, `IntentSynthesisRoute`, `InvalidationReason`, `IntentSynthesisProposal`, `RequirementSynthesisProposal`, `IntentSynthesisResult`, `SynthesisIdentity`, `IntentSynthesisPolicy`, `IntentSynthesisDecision`.

### T2 — Synthesis state projection (L1)
**RED:** `tests/unit/test_intent_synthesis_state.py`
- `IntentSynthesisState` empty by default; frozen mappings like `SemanticState`.
- **C19:** `decisions` holds a full `IntentSynthesisDecisionRecord` — identity, proposal, author, origin, assigned authority, decision, `decision_event_id`, `decided_at` — so a durable `DECIDED(APPLY)` can be finished later with **no provider call and no raw-event rescan**. Key agreement, decision/identity agreement and non-empty `decision_event_id` are enforced; every durable field round-trips through serialization; the record carries **no synthesized object**.
- **C15 single source:** `incomplete_proposal_ids` reads `intent_synthesis.**decisions**` (never `admissions`), through `record.decision.route` and is `DECIDED(APPLY)` ∧ ¬applied ∧ ¬invalidated. Assert the projection exposes no second formulation.
- **I24 partition (C16) — a snapshot property, not a progress claim:** at **every** replayed snapshot, `applied` / `invalidated` / `incomplete` are pairwise disjoint and jointly cover all durable `DECIDED(APPLY)`. `applied` and `invalidated` are terminal; **`incomplete` is a legal non-terminal state** and its presence is not a failure. Non-`APPLY` routes never appear in any of the three.
- **I24a — the T2 half only.** T2 owns *representability*: incomplete is explicitly representable, detectable through `incomplete_proposal_ids`, **not rejected merely for being incomplete**, and nothing in the state representation makes it irreversible (either terminal marker may still be recorded later). T2 must **not** implement or import `resume_incomplete_synthesis`; the executable legal exit and the end-to-end proof that it is actually reachable belong to **T9**, where that operation exists.
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

- **C19 payload requirement:** `INTENT_SYNTHESIS_DECIDED` must carry enough for T4 to reconstruct an `IntentSynthesisDecisionRecord` with **no external lookup** — proposal, author, identity, origin, assigned authority, decision. `decision_event_id` and `decided_at` come from the envelope's `event_id` and `occurred_at` and are **never accepted from a synthesizer**; a test asserts the payload schema cannot express them.

**GREEN:** `domain/events.py` — additive only; existing types, `SPECIALIZED_SEMANTIC_KIND_BY_EVENT` and `GENERIC_SEMANTIC_KINDS` untouched.

### T4 — Reducer: atomic application (L2)
**RED:** `tests/unit/test_intent_synthesis_reducer.py`
- **DECIDED projection (plan omission, fixed):** T4 owns reducer semantics for **all three** synthesis events, not two. `INTENT_SYNTHESIS_DECIDED` projects the durable `IntentSynthesisDecisionRecord` into `state.intent_synthesis.decisions` and creates **no** object, edge, retirement or marker — replay cannot work otherwise. Structural feasibility is checked there: an `APPLY` decision must carry an assigned authority, and `EXISTING_UNCHANGED` can never carry `APPLY`.
- **C20 effect/decision binding:** the object must be the outcome of the durable decision — deterministic object id, kind, statement, assigned authority, `created_at == decided_at`, exact basis equality, runtime-derived scope, provenance naming the decision event, and exactly one `DERIVED_FROM` per basis claim. The decision must be a live `APPLY`, neither applied nor invalidated, and the event id must be the deterministic one.
- **C21 scope preservation:** a replacement retires a target only if its scope covers the target's — `()` covers all, nothing narrower covers `()`, else superset. A negative test proves a scoped replacement cannot retire a project-wide canonical Requirement.
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
- `covering_authority_record(state, *, actor_id, target_scope)` in **`domain/authority.py`** matches the current `_covering_authority_record` on every existing case: `authorized_by` match, liveness (lifecycle `SUPERSEDED`/`REJECTED`/`RESOLVED`, authority `REJECTED`/`SUPERSEDED`), project-wide `()` records covering every target including `None`, scoped records covering by **intersection** — never silently strengthened to containment, which is a different law from C21 — and scoped records covering neither `None` nor a project-wide `()` target.
- deterministic selection by lexically earliest object id, so replay never depends on mapping construction order.
- the helper never inspects a `ReasonerFingerprint` or `SemanticJudgment`; the human check stays with the caller.
- an architectural test pins that admission **imports and calls** the shared primitive rather than reproducing the algorithm.
- **regression lock:** the entire existing `tests/unit/test_admission.py` passes **unchanged**.

**GREEN:** extract per **P1** into the leaf module; `admission.py` becomes a thin adapter supplying the human check and `_target_scope`. Behaviour-preserving refactor only — no routing rule changes, no `Authority` ordering, no reason-string changes.

### T6 — Routing (L4)
**RED:** `tests/unit/test_intent_synthesis_routing.py`
- **I2:** `HUMAN_STATED` + covering record → `CANONICAL`/`APPLY`; without → `REQUIRE_HUMAN`/`AUTHORITY_UNRESOLVED`; `AI_INFERRED` → `PROPOSED`.
- **I2 negative control (C17) — two halves, schema NOT weakened:** (a) `RequirementSynthesisProposal` **still rejects** an `authority` field, proving the model cannot express authority; (b) a `CANONICAL` authority **mis-assigned internally** to a non-human origin — injected at the runtime routing-input / decision-construction layer, simulating a §10.2 bug — is `REJECT`/`AUTHORITY_INVENTION` and does **not** reach a low-risk `APPLY`. **No `authority` field is added to the proposal to make this test constructible.**
- **I22 required negative test:** `CANONICAL` human basis claim + **AI-produced** statement stays `AI_INFERRED`/`PROPOSED` and cannot reach `CANONICAL` via `HUMAN_STATED`.
- **I22:** non-human author with `human_actor_id`, and human author without one, are structural failures; `author` is unspoofable.
- **I23 layer 1:** `REPLACES_STALE` on a `CANONICAL` target with non-`CANONICAL` replacement → `REQUIRE_HUMAN`/`CANONICAL_REPLACEMENT_REQUIRED`; assert **no total ordering over `Authority`** (the check is a `CANONICAL` equality). `AUTHORITY_UNRESOLVED` takes precedence over this rule: not having established authority for the scope is the more fundamental failure.
- **Durable reason vocabulary (T6), pinned exactly:** `EXISTING_UNCHANGED`, `AUTHORITY_INVENTION`, `AUTHORITY_UNRESOLVED`, `CANONICAL_REPLACEMENT_REQUIRED`, `HUMAN_AUTHORITY`, `LOW_RISK`. These persist in `INTENT_SYNTHESIS_DECIDED`, so spelling is part of the durable contract; no free-text variants.
- **Structural failure vs. `REJECT`:** malformed runtime input — identity mismatch, invalid authorship, unsupported origin, non-Slice-1 materiality or policy, a missing `REPLACES_STALE` target — raises structurally. `REJECT` is reserved for a well-formed proposal that governance refuses, such as `AUTHORITY_INVENTION`.
- **I18:** `EXISTING_UNCHANGED` → `NO_CHANGE`, writes nothing. (The staleness legality of the named object is already settled at T7; routing does not re-litigate it.)
- **I10:** purity — same inputs, same decision; state not mutated (asserted by comparing `state.model_dump(mode="json")` before and after).
- **Slice-1 D3/D4 fence (T6).** The router does **not** implement the unresolved general material/corroboration policy. Slice 1 supports **LOW `Requirement`** synthesis under the pinned empty material sets only; a non-`LOW` materiality or a policy wider than the §17.4 pinning **fails closed** rather than silently activating speculative governance. No corroboration algorithm is guessed: there is no approved synthesis-proposal equivalence/signature law and no material route is reachable in this slice, so `independent()` stays ready but unused until D3 is opened. Future D3 work must define which inferred intent is material, the proposal-equivalence signature, and whether independent corroboration suffices.
- **`DETERMINISTIC_NORMALIZATION` fails closed (T6).** §11 defines the fence but builds nothing under it in Slice 1, so routing refuses the origin outright rather than inferring that a one-claim proposal is "probably normalization". Authority inheritance is not implemented.

**GREEN:** `route_intent_synthesis` in `domain/intent_synthesis.py`.

### T7 — Port and bounded request assembly (L5)
**RED:** `tests/unit/test_intent_synthesis_context.py`
- request excludes non-live claims, out-of-scope loci, and `DISPUTED`/`OPEN`/pending/stale/`UNDECIDED` loci. **T7 proves the prerequisite** — blocked or no eligible context → `request is None`. The behavioural assertion *`request is None` → zero synthesizer calls* moves to **T8**, where a synthesizer actually exists; no invocation is added merely to make the older wording testable.
- **blockers:** `OPEN` yields none (nothing to synthesize); `DISPUTED` → `CONTRADICTION`; pending material governance → `MISSING_AUTHORITY`; stale current head → `STALE_EVIDENCE`; `UNDECIDED` value → `MISSING_INFORMATION`. One per distinct `GapKind`, deterministically ordered; T7 mints no `Gap` ids and writes no events.
- **C22:** merged-locus `subject`/`facet` come from the representative address, never from whichever member is encountered first.

### T7.1 — Honest, scoped synthesis gaps (L5)

Additive domain capability so T8 can persist a gap truthfully. No orchestration, no synthesizer call.

- **C23:** every durable synthesis gap uses `GAP_RECORDED` carrying an `IntentSynthesisGap`, `AMBIGUITY` included. The new path never emits `AMBIGUITY_DETECTED`, whose detection-only reducer arm projects nothing into `state.gaps`; its legacy meaning is unchanged so old replay is unchanged.
- `IntentSynthesisGap(Gap)` widens `materiality` and `risk` to `... | None` (`None` is *unclassified*, never `LOW`) and adds explicit `scope`, `confidence`, `locus_representative_id`, `affected_claim_ids`, `subject_key`, `model_gap_proposal_id`. `source_event_ids` is deliberately absent — model-supplied event ids are never trusted into durable state.
- `GapPayload.gap: Gap | IntentSynthesisGap`, base first, so a historical `Gap` still parses as `Gap`.
- `_gap_applies` enforces a synthesis gap's explicit scope before the affected-object logic, so a scope-local blocker cannot become project-wide through the unknown-id branch.
- One gap plane only: `IntentState.gaps`.
- **T8 rule, documented not implemented:** a synthesis gap is persisted with the exact run scope `(scope,)` unless a future governed rule establishes wider applicability.
- **Stale-locus meaning:** the locus' **current head** is stale — never "something derived from this locus is stale", which would deadlock reconciliation. A negative control proves a corrected locus stays eligible while the Requirement derived from its superseded claim shows as `is_stale=True` in the snapshot.
- **I12:** two addresses merged by an active `EQUIVALENT` produce **one** `LocusBasis` keyed on `representative_id`.
- **C3 `is_stale`:** correct for an `ACTIVE` object whose basis was superseded.
- `KnownIntentObject` excludes rationale, provenance, revision, timestamps; `Decision` would use `statement`, not `rationale`.
- **D9:** above `KNOWN_INTENT_OBJECT_THRESHOLD` → `ContextUnsupported`; above `MAX_KNOWN_INTENT_CONTEXT_CHARS` → `ContextUnsupported`; **never truncated**.
- **I6:** derived scope = union of basis address scopes.
- **I17/C4:** `basis_locus_ids` is runtime-derived and matches the claims' loci; **an unrelated claim at the same locus is not included merely because available.**
- **disposition legality — the STATE-DEPENDENT half (R1), validated here BEFORE routing**, against the exact `known_intent_objects` snapshot handed to the synthesizer. All three are **structural failures**, never routing-policy outcomes:
  - the named `relates_to_object_id` must be present in `known_intent_objects`;
  - `REPLACES_STALE` may name only an object with `is_stale=True`;
  - `EXISTING_UNCHANGED` may name only an object with `is_stale=False`.
  Each has a negative-control test, and a test asserts these are rejected at assembly rather than reaching `route_intent_synthesis`.

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
- **I24 recovery terminality (C16):** after a **successful** recovery pass, each processed proposal is applied **xor** invalidated. Separately assert that **bounded-retry exhaustion legitimately leaves a proposal incomplete**, that this is not a failure, and that the **next** recovery invocation resumes it. Do **not** assert unconditional eventual progress: with recovery never run, or contention exhausting attempts every time, incomplete correctly persists and correctly blocks delivery.
- **I25/C14 byte-equivalence, matched baseline (C18):** the comparison is only meaningful between histories containing the **same event set**, differing only in interleaving.
  - *baseline:* same synthesis work **plus the same unrelated event**, serialized with no collision;
  - *race run:* the **same logical events**, with the unrelated event landing between recovery's read and append, raising `ConcurrencyError`;
  - after reload/retry, the two reconstructed final states are **byte-identical**.
  - **No event may be dropped or ignored to make the equality pass**; a baseline lacking the unrelated event is a different ledger and an invalid comparison.
- **I25/C14:** where revalidation now fails → terminal invalidation, not a spin; **`MAX_SYNTHESIS_CONCURRENCY_ATTEMPTS = 3` total attempts** — exhaustion at `DECIDED` leaves nothing durable, at `SYNTHESIZED` leaves it incomplete and retriable.
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

**I1-I25 plus the architect principle I24a** — twenty-six entries in total. All apply to Slice 1.

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
| I24 lifecycle partition (snapshot) | T2, T9 |
| I24a explicit legal exit — representability at T2, operational reachability at T9 | T2 (representable, detectable, reversible), T9 (exit actually runs), T10 (delivery unblocks) |
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
- **C15 naming (audit):** `SemanticState` already has an `admissions` field; `IntentSynthesisState` deliberately uses **`decisions`**. Distinct names on distinct planes — no collision, and the rename removes the very ambiguity that let the stale formulation survive.
- **C18 constructibility (audit):** `current_sequence()` and `append()` are separate calls on both adapters, so the read→append window is **directly exercisable in a test** by appending an unrelated event between them. Both the matched baseline and the race run are constructible without mocking adapter internals, and `InMemoryEventStore.append` is deterministic, so byte-equality is a meaningful assertion.
- **C16 constructibility (audit):** bounded-retry exhaustion is reproducible by forcing three consecutive `ConcurrencyError`s the same way, so "exhaustion legitimately leaves it incomplete" is testable rather than merely asserted in prose.
- **Canonical preservation vs. reconciliation:** the I19 test needs a `CANONICAL` replacement, which §10.2 makes reachable only via `HUMAN_STATED` + covering record. Satisfiable — recorded as **P3** so the test is not written unsatisfiably.
- **Closure vs. staleness:** closure still closes while a derived object is stale; only v2 blocks. Spec §20.6 as designed — **P4** pins it with an explicit assertion.
- **Additive state:** `intent_synthesis` defaults empty, so historical streams replay unchanged (T12).
- **`admission.py` edit:** permitted — it is not in the protected list and spec §10.4 explicitly requires the shared extraction; `authority_record_is_live` is the existing precedent for exactly this sharing. Regression-locked by `test_admission.py`.
- **Reducer remit:** §10.7 layer 2 compares two authorities already present in state and payload — no view derivation, replay stays deterministic (**P5**).

---

## 8. Definition of done

1. Every task GREEN, in dependency order.
2. **I1-I25 and I24a** all have passing tests, including every named negative control.
3. Every regression lock in T12 passes unchanged.
4. **`ruff` clean, and the repo-configured `uv run mypy` clean (R4).** The configured gate is `[tool.mypy] strict = true, packages = ["foundry"]` — i.e. the **production package**. Slice-1 production code must introduce **zero** mypy errors. Pre-existing typing debt in `tests/`, which lies outside the configured package, is **not** a hidden requirement of this slice and must not be silently widened into it: Slice 1 neither inherits it nor adds to it.
5. Zero provider calls in the suite; no network.
6. `git diff` touches no file in the "Not touched" list.
7. `allowed_target_kinds == {REQUIREMENT}` throughout.

---

## 9. Out of scope

Every item in spec §26, plus: the other nine intent-bearing kinds; `Metric`/`VerificationObligation`; deterministic normalization; multi-claim and cross-locus bases; migrating any consumer to v2; D3/D4 policy (blockers only for expansion beyond Slice 1); D5, D7, D8, D10.

Also explicitly out of scope:

- any edit to a frozen comparative-experiment artifact — `src/foundry/intelligence/proposals.py`, `src/foundry/domain/gaps.py`, `evals/comparative/contestant-freeze.json`, or any sealed hash — and therefore the **R2 layering repair itself**, which is deferred under spec §3.1 / P6;
- any **additional** `domain → intelligence` dependency: §3.1 authorizes exactly one and is expressly not precedent;
- changes to `semantic_reducer._minted_id`, a separate identity path with runtime-owned inputs, untouched by the T1.2 widening.
