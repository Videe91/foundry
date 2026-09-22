# Intent Synthesis Bridge — Design Specification

**Status:** Architecture approved in chat on 2026-09-22 (Approach 2, with rulings D1/D6/D7 and four design corrections). This document is the binding specification. No implementation, no plan, no code exists yet.

**Base branch:** `feat/intent-intelligence-v2`

**Base commit:** `b8cd8272140693972b00adc8129c1dffad583438`

**Predecessor experiment:** `intent-v2-locus-validation-v1` — seal `cd98fbb`, raw run `17cc9f6`, adjudication `b8cd827`.

**Predecessor outcome:** `LOCUS_POLICY_NOT_VALIDATED`. This outcome is permanent. Nothing in this specification re-adjudicates, reinterprets or replaces it. See §26.4.

---

## 1. Purpose

The v2 semantic substrate (`SemanticAddress` + atomic `SemanticClaim` + judgments + admission + supersession) and the v0/v1 intent contract (`SemanticObject` + `evaluate_closure` + `CanonicalIntentPackage`) both exist, are both tested, and are **not connected**. `build_intent_package` reads only `state.objects`; it never consults `state.semantic`. The only `SemanticObject` any production path writes today is `AuthorityRecord` (`application/semantic_governance.py:172`). The canonicalization event types — `REQUIREMENT_CANONICALIZED`, `CONSTRAINT_DISCOVERED`, `ASSUMPTION_IDENTIFIED`, `SUCCESS_METRIC_DEFINED`, `VERIFICATION_OBLIGATION_DEFINED` — are wired into the reducer (`application/reducer.py:47-52`) and **emitted by nothing**.

This specification defines the missing edge: a governed **Intent Synthesis** layer that turns live atomic claims into typed intent-bearing `SemanticObject`s, so that closure and the canonical contract become reachable from evidence.

It exists because of a structural finding, not a preference. The locus-validation experiment demonstrated that atomic per-proposition claims are correct and that the claim lifecycle works; it also demonstrated that *counting claims* is the wrong way to ask whether intent was captured. A document carrying four independent normative facts yields four claims and one human commitment. Those are two different altitudes, and the system currently has only the lower one.

**One-sentence purpose:** give Foundry a governed, provenance-bearing, replayable way to form human-meaningful intent from evidence-backed propositions, without weakening claim atomicity and without creating a second ledger of intent.

---

## 2. Non-goals

This specification does **not**:

1. change `SemanticClaim` cardinality, atomicity, or any part of the validated claim lifecycle;
2. introduce an `IntentUnit` (or equivalent) durable domain type — the intent-bearing `SemanticObject` kinds already occupy that altitude;
3. modify `evaluate_closure` (ruling D6);
4. modify `build_intent_package` or `CanonicalIntentPackage`;
5. modify `IntentDecisionHandoff` v1 or `HANDOFF_VERSION` (ruling D7);
6. design the Research Worker beyond its interaction boundary (§21);
7. change any frozen prompt, policy version, prompt hash, or output-schema hash;
8. alter, re-adjudicate or reinterpret any sealed experiment;
9. decide materiality thresholds, corroboration policy, or authorization policy beyond what the architecture already establishes (§27).

---

## 3. Altitude and boundary

The Law of Descent makes altitude separation constitutional, not stylistic. Semantic reasoning and intent synthesis are two altitudes and must not share a vocabulary.

| | Semantic reasoning (exists, validated) | Intent synthesis (this spec) |
|---|---|---|
| question answered | *what does this evidence say?* | *what does the human mean / commit to?* |
| unit | one proposition at one locus | one independently meaningful commitment |
| durable output | `SemanticClaim`, `SemanticAddress` | intent-bearing `SemanticObject` |
| vocabulary | `JudgmentKind` (8 members) | `IntentSynthesisProposal` (separate) |
| governance | `route_judgment` | `route_intent_synthesis` (reuses primitives, §10) |
| granularity | atomic, per proposition | human-meaningful, may span many claims |

**Boundary law.** Intent synthesis reads the semantic substrate and never writes to it. It emits no `SemanticJudgment`, creates no address, asserts no claim, supersedes no claim, and records no `CONFLICTS_WITH`. Conversely the semantic reasoner never sees an intent object and never proposes one. `JudgmentKind` is **not** extended; `JudgmentProposal`, `proposal_signature`, `agrees`, `contradicts` and `judgment_address_ids` are left byte-unchanged.

**Why not a new `JudgmentKind`.** It would inherit governance for free, but it would widen the most load-bearing and most-tested module set in the system immediately after the substrate was validated at real cost, and — decisively — it would conflate *what a document says* with *what a human means* inside one vocabulary. That is the quiet altitude violation the constitution names as the characteristic failure: something reasonable happening that nobody upstream decided.

**Why not pure deterministic projection.** `domain/semantic_identity.py` states the governing law: *"Deterministic code cannot originate meaning; it only applies admitted judgments."* Forming a Requirement from claims originates meaning. A deterministic claim→Requirement projector would smuggle semantic authorship into deterministic code — the exact failure the substrate was built to prevent. The only admissible deterministic path is the narrow meaning-preserving exemption of §11.

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
  -> IntentDecisionHandoff v2                  [new; gated on readiness]
  -> Planning / Architecture
```

Research (boundary only, §21):

```
Gap -> Research Job -> EvidenceItem -> normal semantic assimilation -> claims -> Intent Synthesis
```

Research has no direct path to canonical intent.

**Intent-bearing kinds (ruling D1), exactly ten:**
`Intent`, `Goal`, `Outcome`, `Requirement`, `Constraint`, `NonGoal`, `Preference`, `Decision`, `Assumption`, `Contract`.

`Actor` is **canonical intent context, not an intent-bearing commitment**. It remains in `CanonicalIntentPackage.purpose_ids` unchanged and is **not** a synthesis target kind (§26).

Supporting semantic / epistemic / governance objects — `Claim`, `Evidence`, `Unknown`, `Question`, `Conflict`, `Risk`, `Metric`, `VerificationObligation`, `AuthorityRecord`, `Amendment` — are not intent-bearing and are not synthesis targets in this specification.

---

## 5. Existing primitives retained unchanged

Every item below is reused as-is. None is edited by this specification.

| primitive | location | role in the bridge |
|---|---|---|
| `SemanticClaim`, `SemanticAddress` | `domain/semantic_identity.py` | the basis; read-only |
| `CurrentSemanticView`, `SemanticLocus` | `domain/semantic_view.py` | live claims, loci, epistemic state, `effective_evidence`, `stale_ids`, `pending_judgment_ids` |
| `DerivationEdge`, `descendants`, `stale_object_ids` | `domain/derivation.py` | blast radius |
| `Relation`, `RelationType.DERIVED_FROM` | `domain/common.py` | readable provenance |
| `Provenance`, `Authority`, `Materiality`, `SourceKind` | `domain/common.py` | origin and authority vocabulary |
| `AuthorityRecord`, `_covering_authority_record` | `domain/semantic.py`, `domain/admission.py` | how human authority enters |
| `Gap`, `GapKind`, `GapStatus` | `domain/gaps.py` | refusal-with-reason |
| `GapProposal` | `intelligence/proposals.py` | reused verbatim in the result contract |
| `evaluate_closure`, `ClosureResult` | `domain/closure.py` | unchanged (D6) |
| `CanonicalIntentPackage`, `build_intent_package` | `application/package.py` | unchanged; the single contract |
| `SemanticReadiness`, `build_semantic_readiness` | `domain/handoff.py` | the v2 emission gate |
| `IntentDecisionHandoff`, `HANDOFF_VERSION` | `domain/handoff.py` | **frozen** (D7) |
| `SemanticGovernor.derive()` | `application/semantic_governance.py:137` | records `DerivationEdge`s |
| `REQUIREMENT_SUPERSEDED` | `domain/events.py`, `reducer.py:113` | object-level supersession by replacement |

---

## 6. New primitives

| new thing | module | kind |
|---|---|---|
| `IntentSynthesisRequest` | `ports/intent_synthesizer.py` | bounded request |
| `KnownIntentObject` | `ports/intent_synthesizer.py` | request-only snapshot |
| `LocusBasis` | `ports/intent_synthesizer.py` | request-only |
| `IntentSynthesizer` (Protocol) | `ports/intent_synthesizer.py` | port |
| `IntentSynthesisProposal`, `IntentSynthesisResult` | `domain/intent_synthesis.py` | proposal vocabulary |
| `IntentSynthesisPolicy`, `IntentSynthesisDecision`, `route_intent_synthesis` | `domain/intent_synthesis.py` | governance |
| `SynthesisOrigin` | `domain/intent_synthesis.py` | origin enum |
| `INTENT_SYNTHESIS_PROPOSED`, `INTENT_SYNTHESIS_ADMITTED`, `INTENT_OBJECT_PROPOSED` | `domain/events.py` | event vocabulary (§10.5) |
| `IntentDecisionHandoffV2`, `IntentBasisRef` | `domain/handoff_v2.py` | new module; v1 untouched |
| `synthesize_intent(...)` | `application/intent_synthesis.py` | orchestrator |

---

## 7. `IntentSynthesisRequest`

Bounded, task-specific, scope-limited. Mirrors the `ReasoningRequest` law: the synthesizer is compute, not memory. It never receives `IntentState`, `SemanticState`, `EventStore`, or whole-project context.

```
IntentSynthesisRequest
  project_id: str
  scope: str                                   # exactly one scope
  basis: tuple[LocusBasis, ...]                # min_length=1
  known_intent_objects: tuple[KnownIntentObject, ...]   # §8
  allowed_target_kinds: frozenset[SemanticKind]         # subset of the ten
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
  source_kinds: tuple[SourceKind, ...]         # of the effective evidence; enables §10 origin
```

**Keyed on `locus_representative_id`, never `address_id`** (invariant I12). Addresses merged by an active `EQUIVALENT` judgment form one locus; keying on the representative prevents one commitment becoming two objects.

**Construction rules (deterministic, runtime-owned):**
- only claims that are **live** in `derive_view` at request time may appear;
- only loci whose scope is `()` or contains `scope` may appear — the same membership convention `evaluate_closure` and `locus_in_scope` use;
- a locus whose `epistemic_state` is `DISPUTED` or `OPEN`, or that carries a pending material judgment, **is not offered for synthesis**; it produces a `Gap` deterministically (§16) and never reaches the synthesizer;
- `effective_evidence_ids` come from `view.effective_evidence[claim_id]`, so active `SUPPORTS_CLAIM` records are reflected without mutating any claim.

**Forbidden in the request by construction:** `IntentState`, `SemanticState`, retired or non-live claims, out-of-scope loci, judgment bodies, rationales, event ids.

---

## 8. `KnownIntentObject` — bounded snapshot

**Why it exists.** `id + kind + authority` is insufficient: without minimal semantic content the synthesizer cannot detect that a proposal duplicates, overlaps, extends, or conflicts with an intent object that already exists, and the system would accumulate near-duplicate commitments.

**Second-ledger fence — load-bearing.** This snapshot carries statement text. It is therefore governed by exactly the law `ComparisonContext` already establishes for request-only context (`ports/semantic_reasoner.py`): it is **temporary reasoning context, never canonical state, never an event payload, never persisted, never returned in a proposal, and never part of any handoff or package.** It is compiled fresh from current state for one request and discarded when that request ends. The durable truth remains `state.objects`; the snapshot is a read-through projection with no identity of its own.

```
KnownIntentObject                              # request-only; NEVER persisted
  object_id: str
  kind: SemanticKind                            # one of the ten
  authority: Authority
  lifecycle: LifecycleStatus
  scope: tuple[str, ...]
  statement: str                                # the minimum semantic field (see below)
  materiality: Materiality | None               # Requirement only
  basis_claim_ids: tuple[str, ...]              # its DERIVED_FROM relations
  basis_locus_ids: tuple[str, ...]
```

**`statement` field selection per kind** (the single human-readable field already carried by the model; no new content is invented):

| kind | field used as `statement` |
|---|---|
| `Intent` | `mission` |
| `Goal`, `Outcome`, `NonGoal`, `Preference`, `Constraint`, `Assumption`, `Contract` | `statement` |
| `Requirement` | `statement` |
| `Decision` | `statement` (**not** `rationale` — rationale is reasoning, excluded) |

**Bounds:** only objects that are `_is_current` (lifecycle `ACTIVE`, authority not `REJECTED`/`SUPERSEDED`) and in scope are included. Rationales, provenance, relations other than `DERIVED_FROM` basis ids, revisions, timestamps and confidence are excluded. The snapshot is capped; the cap is a slice-time bound recorded in the plan, and an over-cap request is a refusal (§23), never a silent truncation.

---

## 9. `IntentSynthesisProposal` and result

**Design correction 1 is binding: the synthesizer proposes semantic meaning only. It does not propose, choose, or express authority.** The schema cannot express `authority`; runtime assigns it from origin (§10.2). AI and research-derived synthesis can never choose `CANONICAL` and can never choose their own authority.

```
IntentSynthesisProposal                        # what the synthesizer returns
  proposal_id: str
  target_kind: SemanticKind                     # must be in allowed_target_kinds
  statement: str                                # the proposed meaning
  mission: str | None                           # Intent only
  rationale: str                                # concise; never chain-of-thought
  basis_claim_ids: tuple[str, ...]              # min_length=1
  basis_locus_ids: tuple[str, ...]              # min_length=1
  relates_to_object_id: str | None              # an existing object it extends/duplicates
  relation_note: str | None                     # why, when relates_to_object_id is set
  confidence: float | None                      # metadata; no rule reads it
```

```
IntentSynthesisResult
  proposals: tuple[IntentSynthesisProposal, ...]
  gap_proposals: tuple[GapProposal, ...]        # existing type, reused verbatim
```

**The synthesizer never emits, and the schema cannot express:** `authority`, object id, `project_id`, `scope`, `provenance`, `relations`, `lifecycle`, `revision`, `created_at`, `materiality`, `requires_metric`, `requires_verification`, judgment ids, or event ids. Runtime owns every one of them. This mirrors the 9O trust boundary verbatim and is the reason an authority-invention class of bug cannot originate in the model.

**Runtime-derived fields:**

| field | derivation |
|---|---|
| `object_id` | runtime id factory |
| `scope` | **union of the basis claims' address scopes** — never chosen by the synthesizer (I6) |
| `authority` | origin (§10.2) |
| `provenance` | origin (§12.3) |
| `relations` | one `DERIVED_FROM` per basis claim (§12.1) |
| `materiality`, `requires_metric`, `requires_verification` | `Requirement` only; slice-1 pinning in §17, general policy is open decision D4 |

---

## 10. Governance and authority law

### 10.1 Origin

```
SynthesisOrigin = HUMAN_STATED | DETERMINISTIC_NORMALIZATION | AI_INFERRED | RESEARCH_DERIVED
```

Origin is determined by **runtime**, never claimed by the synthesizer:

- `HUMAN_STATED` — submitted through the human path with an authenticated actor id, exactly as `SemanticGovernor.submit(..., human_actor_id=...)` requires today.
- `DETERMINISTIC_NORMALIZATION` — produced by runtime code under the §11 exemption. No synthesizer involved.
- `AI_INFERRED` — produced by a non-human `IntentSynthesizer`.
- `RESEARCH_DERIVED` — an `AI_INFERRED` proposal **all** of whose basis claims rest solely on evidence with `SourceKind.RESEARCH`. Computed from `BasisClaim.source_kinds`; never stored as a field, always derivable (§12.4).

### 10.2 Authority assignment (runtime, by origin)

| origin | assigned authority | route |
|---|---|---|
| `HUMAN_STATED` **with** covering `AuthorityRecord` | `CANONICAL` | `APPLY` (`HUMAN_AUTHORITY`) |
| `HUMAN_STATED` **without** covering record | none assigned | `REQUIRE_HUMAN` (`AUTHORITY_UNRESOLVED`); nothing written |
| `DETERMINISTIC_NORMALIZATION` | **inherits** the source object's authority and provenance | `APPLY` only if §11 holds; otherwise `REJECT` |
| `AI_INFERRED` | `PROPOSED` | per policy (§10.4) |
| `RESEARCH_DERIVED` | `PROPOSED` | per policy (§10.4); never privileged over `AI_INFERRED` |

`CANONICAL` is reachable **only** from `HUMAN_STATED` with a covering `AuthorityRecord`, or inherited under §11. There is no other path, at any policy setting.

### 10.3 Anti-invention guard — mandatory, with a stated reason

`admission._authority_invention` is hardcoded to `AssertClaimProposal` (`domain/admission.py:364`). It therefore does **not** protect any new proposal type. Without an equivalent guard, a synthesis proposal carrying `CANONICAL` would fall through to the low-risk rule and be applied with no human anywhere.

`route_intent_synthesis` must therefore implement, as its own rule and before any other admission rule:

> A proposal whose origin is not `HUMAN_STATED` (or a valid §11 inheritance) and whose assigned authority is `CANONICAL` is `REJECT` with reason `AUTHORITY_INVENTION`.

This is **defence in depth**, deliberately redundant with §9: the schema already makes the condition unreachable from a model. The guard exists so that a future refactor which adds an authority field, or a runtime bug in §10.2, fails closed rather than silently canonicalizing AI output. It is an invariant with a test (I2), not an implementation detail.

### 10.4 Materiality and corroboration policy

```
IntentSynthesisPolicy
  material_target_kinds: frozenset[SemanticKind]
  material_materiality_levels: frozenset[Materiality]
  canonical_requires_authority: bool = True
```

A proposal judged **material** under the policy requires either a covering `AuthorityRecord` or independent corroboration, and otherwise routes `REQUIRE_SECOND_LENS` — the same shape `route_judgment` rule 7 already uses. Independence is determined by the existing `ReasonerFingerprint.independent()` helper; a proposal from the same fingerprint never corroborates itself.

**The general policy values are open decision D3 and are not set here.** §17 pins a deliberately conservative slice-1 setting.

**Shared helpers are extracted, never duplicated.** `route_intent_synthesis` reuses the authority-coverage and independence logic that `route_judgment` already implements (`_covering_authority_record`, `independent()`). These are currently private to `domain/admission.py`. They must be **lifted into a shared, tested location and called by both routers**. Two governance paths are acceptable; two divergent copies of the authority-coverage rule are not — a copy that drifts is an authority bug that no test on either side would catch. Duplicated routing logic is a review defect.

`confidence` is metadata and is never read by any routing rule — the same law `route_judgment` already enforces.

### 10.5 Governed path and event vocabulary

```
IntentSynthesisResult
  -> for each proposal:
       INTENT_SYNTHESIS_PROPOSED   (the proposal, recorded verbatim, always)
       route_intent_synthesis(...)
       INTENT_SYNTHESIS_ADMITTED   (the decision, always)
       if route == APPLY:
            REQUIREMENT_CANONICALIZED | CONSTRAINT_DISCOVERED | ASSUMPTION_IDENTIFIED
            | HUMAN_DECISION_RECORDED | SEMANTIC_OBJECT_RECORDED | INTENT_OBJECT_PROPOSED
            DERIVATION_RECORDED  x len(basis_claim_ids)
  -> for each gap_proposal:
       GAP_RECORDED  (or AMBIGUITY_DETECTED for GapKind.AMBIGUITY)
```

A proposal is **always recorded**, whatever the route. A `REJECT` leaves the proposal readable and canonical state untouched — the same guarantee `submit` gives today.

**`INTENT_OBJECT_PROPOSED` is required and is a genuine finding.** The existing event vocabulary cannot record a *non-canonical* `Requirement`, `Constraint`, `Assumption` or `Decision`: `SEMANTIC_OBJECT_RECORDED` rejects specialized kinds (`GENERIC_SEMANTIC_KINDS`, `domain/events.py`), and the specialized events are named for canonicalization. Recording a `PROPOSED` Requirement through `REQUIREMENT_CANONICALIZED` would make the ledger say something untrue. `INTENT_OBJECT_PROPOSED` carries `SemanticObjectPayload`, is restricted to the ten intent-bearing kinds, and **must reject `authority == CANONICAL`** — the event type itself is a structural guard.

Correspondingly, the specialized canonicalization events are used **only** for `CANONICAL` objects.

---

## 11. Deterministic-normalization exemption

Narrow by construction. If this fence leaks, it becomes an unaudited canonical-authority minting route, which is precisely the `AUTHORITY_INVENTION` failure the architecture forbids.

A deterministic normalization may **inherit** its source's authority and provenance only if **all three** hold:

1. **exactly one** basis claim;
2. **no** merging, inference, generalization, quantifier change, unit conversion, or aggregation — the transformation is a pure restatement whose meaning is provably identical;
3. the basis claim's authority is `CANONICAL` **and** its provenance `source_kind` is `HUMAN`.

If any test fails, the transformation is synthesis and takes the §10 path. There is no partial credit and no "mostly deterministic" route.

Because condition 2 is not mechanically checkable in general, the exemption is admissible **only** for transformations whose meaning-preservation is established by construction in code and covered by a test that pins the exact input and output. An open-ended normalizer is not eligible. Deterministic normalization is **out of scope for slice 1** (§26).

---

## 12. Dual provenance invariant

**Both recordings are mandatory for every basis claim. Neither substitutes for the other.**

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

One per basis claim, recorded via the existing `SemanticGovernor.derive()`. Uses the **asserting judgment id**.

### 12.3 The asymmetry is deliberate — do not "fix" it

`derivation.stale_object_ids` computes its roots as *inactive judgment ids* plus *issue versions minted by them*, then takes `descendants(state.derivations, roots)`. **Claim ids are never roots.** An edge whose `parent_id` is a `claim_id` would record provenance that looks correct and would **silently fail to propagate staleness** — a correct-looking ledger with a broken blast radius, which is worse than an obvious defect.

> **Never use `claim_id` as a `DerivationEdge` parent under the current staleness algorithm.**

Any future change to `stale_object_ids` roots must revisit this section explicitly.

### 12.4 Provenance record

```
Provenance(
    source_kind     = HUMAN  (HUMAN_STATED) | SYSTEM (AI_INFERRED, RESEARCH_DERIVED)
                    | inherited (DETERMINISTIC_NORMALIZATION),
    source_ref      = actor id | synthesis invocation id | inherited,
    source_event_ids = the INTENT_SYNTHESIS_PROPOSED / _ADMITTED events,
)
```

**Research-derivedness is derived, never stored.** `research_derived(object)` is true when every basis claim's *effective* evidence carries `SourceKind.RESEARCH`. `SourceKind.RESEARCH` already exists, so the property is recoverable through the derivation chain without a new field — consistent with the codebase's "derive the current view, never store it" discipline, and it stays correct when a later `SUPPORTS_CLAIM` adds non-research evidence to a basis claim.

### 12.5 Count invariant

For every synthesized object:

```
len([r for r in object.relations if r.relation_type is DERIVED_FROM])
    == len(basis_claim_ids)
    == len(edges where child_id == object_id)
```

A `Relation` without an edge is a silent staleness hole. An edge without a `Relation` is unreadable provenance. Both are defects, and both are caught by I3.

---

## 13. Many atomic claims → one intent object

`basis_claim_ids` has `min_length=1` and no upper bound beyond the request cap. Semantics are **conjunctive**: the object asserts a commitment supported by all cited claims jointly.

Worked example, using the frozen locus-validation alpha evidence (illustrative only; that experiment is not rerun):

```
ADDR-ae0de307833fe2f5   "Client credential / What are the rules of revocation?"
   CLAIM-6e40a6...  who may revoke                -> owner or operator
   CLAIM-4595a5...  when revocation takes effect  -> immediately
   CLAIM-a7a6fa...  client can undo               -> no
   CLAIM-ded86e...  auth with revoked credential  -> must not succeed
        |
        +--> REQ-1  "Revocation is immediate, irreversible by the client, and
                     permanently prevents authentication."
               basis_claim_ids = all four
               relations       = 4 x DERIVED_FROM
               derivation edges= 4, each to the claim's asserting judgment
```

**This is the structural resolution of the granularity question.** Claims stay atomic and independently supersedable; intent stays human-meaningful. Nothing downstream counts claims, so "how many claims should there be" ceases to be a contested number.

Bases spanning more than one locus are permitted and are the normal case for a commitment that constrains several subjects.

---

## 14. One claim → many intent objects

Permitted, unrestricted, and **no uniqueness constraint may be introduced**. `DerivationEdge` is many-to-many by construction (one `parent_id`, arbitrarily many `child_id`s) and `descendants` is a set-valued transitive closure, so fan-out propagates with no change.

```
CLAIM-ded86e...  "no authentication attempt that presents it may succeed"
    +--> REQ-1         (the revocation requirement)
    +--> CONSTRAINT-2  ("no authentication path may bypass revocation")
    +--> VO-3          (future: "test: authenticate with a revoked credential")
```

Superseding that single claim marks **all three** stale in one traversal. This is why §12.2 edges must exist even where they feel redundant with §12.1.

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
  -> IntentDecisionHandoff v2 REFUSES to emit                  [D6]
```

The object is **never auto-rewritten and never auto-retired**. It is stale — `NEEDS_RECONCILIATION` — and the scope stops being deliverable.

### 15.2 Reconciliation

Supersession by replacement, never edit:

1. a fresh `IntentSynthesisProposal` over the corrected claims;
2. the new object is recorded through §10.5;
3. the old object is retired with the **existing** `REQUIREMENT_SUPERSEDED` event (`reducer.py:113-128`), which marks it `LifecycleStatus.SUPERSEDED` and bumps its revision.

The original object's bytes are never modified (I5). The superseded object remains readable history.

**Note (feeds open decision D8):** `REQUIREMENT_SUPERSEDED` is `Requirement`-specific and requires the replacement to already exist in state. The other nine intent-bearing kinds have no object-level supersession event. Slice 1 is `Requirement`-only, so this is sufficient now; extending synthesis beyond `Requirement` requires a general object-supersession event.

### 15.3 Disputed and pending

A locus that is `DISPUTED`, or that carries a pending material judgment, is never offered for synthesis (§7) and blocks readiness through the existing `disputed_locus_ids` / `pending_material_judgment_ids` fields. No new mechanism.

### 15.4 Compatible extension — explicitly unresolved

A new claim added at a basis locus supersedes nothing, so the derived object does **not** become stale. It may nevertheless now be *incomplete*: a proposition exists at its locus that its statement does not reflect.

Blocking would be wrong (nothing was invalidated); ignoring may be wrong (the commitment may be understated). No existing `GapKind` names this condition precisely.

**This specification deliberately does not decide it.** Slice-1 behaviour is: **no effect, no gap, no staleness** — the conservative, non-blocking reading. This is recorded as open decision **D5** and must be resolved before synthesis is used on an evolving corpus. §24 I13 pins the slice-1 behaviour so a later change is a conscious one.

---

## 16. Gap behaviour

Synthesis refuses **with a reason**, never silently. Every condition maps to an **existing** `GapKind`; no new kind is introduced.

| condition | `GapKind` | blocking | decided by |
|---|---|---|---|
| locus `DISPUTED` (active `CONFLICTS_WITH`) | `CONTRADICTION` | yes | runtime, deterministically |
| pending material judgment on a basis locus | `MISSING_AUTHORITY` | yes | runtime, deterministically |
| any basis claim is stale | `STALE_EVIDENCE` | yes | runtime, deterministically |
| any basis claim value is `UNDECIDED` | `MISSING_INFORMATION` | yes | runtime, deterministically |
| statement cannot be formed as one coherent commitment | `AMBIGUITY` | yes | synthesizer |
| material target, basis is inferred/research only | `MISSING_AUTHORITY` | policy (D3) | runtime |
| canonical `Requirement` with `requires_metric` and no metric | `MISSING_SUCCESS_METRIC` | yes | runtime |
| locus `OPEN` (no live claims) | — nothing to synthesize; no gap | — | runtime |

**Exclusivity (I10):** for one basis and one target kind, synthesis emits an object proposal **or** a `Gap` for a given unresolved condition — never both. A runtime-decided condition is settled before the synthesizer is called, so the synthesizer is never asked to reason about a locus it should have been refused.

`GapKind.AMBIGUITY` is recorded through `AMBIGUITY_DETECTED`, which the envelope validator already constrains to that kind; all other kinds use `GAP_RECORDED`.

---

## 17. Requirement-first vertical slice

### 17.1 Why `Requirement` and not `Constraint`

`Constraint` looks simpler — a bare `statement`, no materiality, no metric or verification fields. It is the wrong first kind: `evaluate_closure` raises `NON_CANONICAL_OBLIGATION` for **any** non-canonical `Constraint` in scope (`closure.py:115`). A single `PROPOSED` Constraint therefore blocks closure permanently until it is canonicalized or rejected.

`Requirement` blocks closure only at `materiality >= MEDIUM` (`NON_CANONICAL_REQUIREMENT`, `MATERIAL_REQUIREMENT_LEVELS`). A `LOW`-materiality proposal is therefore harmless and visible. **`Requirement` is the smallest coherent vertical slice.**

### 17.2 Slice-1 contents

A complete path from evidence to a delivered contract:

1. one live, human-provenanced, `CANONICAL` basis claim at one in-scope locus;
2. `HUMAN_STATED` synthesis with a covering `AuthorityRecord`;
3. one `CANONICAL` `Requirement`, `materiality=LOW`, `requires_metric=False`, `requires_verification=False`;
4. dual provenance recorded (§12);
5. a `CANONICAL` `Intent` present in scope (recorded via `SEMANTIC_OBJECT_RECORDED`; `INTENT` is in `GENERIC_SEMANTIC_KINDS`);
6. `evaluate_closure` closes — **unchanged**;
7. `build_intent_package` emits the contract — **unchanged**;
8. `IntentDecisionHandoff v2` emits, gated on `readiness.ready`.

`requires_metric=False` makes the metric blocker unreachable (`closure.py:135-137` guards on the flag), so no `Metric` or `VerificationObligation` is needed and no metric-design decision is forced.

### 17.3 Two proofs carried in slice 1

Cheap, and they pin the invariants that matter most:

- **authority boundary** — one `AI_INFERRED` Requirement at `materiality=LOW` is assigned `PROPOSED`, recorded via `INTENT_OBJECT_PROPOSED`, never enters `obligation_ids`, and does not block closure;
- **blast radius** — superseding the basis claim puts the Requirement in `view.stale_ids` and `scoped_stale_object_ids`, and handoff v2 refuses.

### 17.4 Slice-1 policy pinning (conservative, not the general law)

```
IntentSynthesisPolicy(
    material_target_kinds       = frozenset(),          # no kind is material in slice 1
    material_materiality_levels = frozenset(),
    canonical_requires_authority= True,
)
```

Safe because slice 1 admits only `HUMAN_STATED` (which needs a covering `AuthorityRecord` regardless) and `AI_INFERRED` at `LOW` materiality (which is `PROPOSED`, non-contractual and non-blocking). **This pinning is a slice-1 restriction, not the general policy** — see D3.

---

## 18. `IntentDecisionHandoff` v2

New module `domain/handoff_v2.py`. `domain/handoff.py` is **not edited at all**, including its `HandoffVersion` type — the v2 literal is declared in the new module (ruling D7).

```
IntentDecisionHandoffV2
  handoff_version: Literal["intent-decision-handoff-v2"]
  project_id: str
  scope: str
  intent_version: int                      # package revision
  semantic_state_revision: int

  # --- PRIMARY: canonical intent -------------------------------------
  contract: CanonicalIntentPackage         # already ids-only
  canonical_intent_object_ids: tuple[str, ...]   # the ten kinds, CANONICAL only
  proposed_intent_object_ids: tuple[str, ...]    # visible; explicitly NOT authoritative

  # --- BRIDGE: intent traced to substrate -----------------------------
  intent_basis: tuple[IntentBasisRef, ...]

  # --- TRACEABILITY: retained from v1 ---------------------------------
  loci: tuple[SemanticLocus, ...]
  claim_ids: tuple[str, ...]
  evidence_ids: tuple[str, ...]
  authority_record_ids: tuple[str, ...]
  superseded_judgment_ids: tuple[str, ...]

  # --- GOVERNANCE ------------------------------------------------------
  stale_object_ids: tuple[str, ...]
  pending_material_judgment_ids: tuple[str, ...]
  readiness: SemanticReadiness
```

```
IntentBasisRef
  object_id: str
  basis_claim_ids: tuple[str, ...]
  basis_locus_ids: tuple[str, ...]
```

**Emission gate (ruling D6) — the load-bearing rule:**

> `build_intent_decision_handoff_v2` **refuses** unless `SemanticReadiness.ready is True`. A stale semantic basis, a disputed locus, or a pending material judgment blocks the handoff.

Refusal raises a typed error naming the blocking condition, in the shape `IntentNotClosedError` already establishes. Nothing partial is emitted.

`evaluate_closure` and `CanonicalIntentPackage` stay unchanged; the gate lives in the handoff, where the semantic conditions already live.

**No second ledger.** Embedding `CanonicalIntentPackage` by value is safe precisely because it is already ids-only. `intent_basis` is ids only. No statement text, no claim value, no rationale, no evidence content appears anywhere in v2 (I9).

`loci`, `claim_ids` and `evidence_ids` are retained and **explicitly labelled traceability**: they support blast-radius analysis, governance and audit. They are not the contract.

---

## 19. v1 / v2 coexistence

- v1 is **byte-frozen**: `IntentDecisionHandoff`, `HANDOFF_VERSION`, `HandoffVersion`, `SemanticReadiness`, and every helper in `domain/handoff.py` are unchanged. Every existing `tests/unit/test_handoff.py` test passes untouched (I11).
- v2 is additive and lives in a separate module. Both may be built from the same state.
- v1 has **no** readiness gate and keeps that behaviour. v2 has one. The difference is intentional and is the reason they can coexist without ambiguity.
- v2 becomes the downstream target **only after it is independently proved**. Until then no consumer is migrated, and this specification changes no call site.
- Deprecating v1 is out of scope and requires its own decision (D7 remains open as a migration question, not as a design question).

---

## 20. `CanonicalIntentPackage` as the single downstream contract

1. `build_intent_package` is **not modified**; it still refuses on non-closure with `IntentNotClosedError`.
2. Obligations have exactly one source: `obligation_ids` remains `Requirement | Constraint | Contract` filtered to `CANONICAL`. A `PROPOSED` object can never reach a consumer as an obligation (I8).
3. `Actor` remains in `purpose_ids` (ruling D1), unchanged.
4. In v2, claims and loci are **demoted to traceability** and labelled as such in the type. Planning and Architecture consume `contract`; they read `loci` / `claim_ids` only for blast radius and audit.
5. The package becomes *reachable* for the first time. It is unchanged and already end-to-end tested (`tests/e2e/test_replay_to_package.py`) with hand-fed objects; synthesis merely supplies those objects from governed state instead of fixtures.
6. **Contract vs. gate, stated explicitly to prevent a later contradiction:** `CanonicalIntentPackage` is the single **contract**; `IntentDecisionHandoff v2` is the single **delivery gate**. The package may still be built while the semantic basis is stale — that is unchanged v0 behaviour and is deliberately preserved (D6). Delivery is what staleness blocks.

---

## 21. Research Worker interaction boundary

**Boundary only. The Research Worker is not designed here.**

```
Gap -> Research Job -> EvidenceItem -> normal semantic assimilation -> claims -> Intent Synthesis
```

The law is already the architecture's law and is already enforced by construction:

- `specs/2026-09-09-intent-engine-v0-design.md` principle 1: *"Research is subordinate to intent and produces evidence only."*; line 331: *"Research cannot directly create canonical requirements or decisions."*
- `DigRecord` -> `evidence_from_dig()` (`domain/evidence.py:112`) returns an `EvidenceItem` and nothing else. **No function exists** by which research output can mint an address, a claim, or an intent object.
- `Job` (`domain/jobs.py:46`) already carries `gap_id`, `JobType.RESEARCH_PLANNING` / `EVIDENCE_COLLECTION` / `EVIDENCE_RECONCILIATION`, `permitted_executors`, `budget_usd` and `verification_requirement`. Research is pre-governed and pre-budgeted.
- `Gap.resolution_event_id` + `GapStatus.RESOLVED` / `WAIVED` close the loop.

**What this specification adds:** research-derived intent is `RESEARCH_DERIVED` origin (§10.1), is assigned `PROPOSED` authority (§10.2), and is never privileged over any other inferred content. A requirement inferred from research is a proposal, not canonical intent — enforced by §10.2 and §10.3, not by convention.

**Research gets no privileged position anywhere:** its evidence is admitted, bound, supported and superseded by exactly the same governance as human- or document-sourced evidence.

---

## 22. Replay and determinism

The synthesizer is non-deterministic. The **ledger** must not be.

1. **State is rebuilt from events, never by re-running a synthesizer.** The proposal and the admission decision are recorded as events; the reducer applies only what an `APPLY` decision records. This is the same separation `SEMANTIC_JUDGMENT_RECORDED` / `SEMANTIC_ADMISSION_DECIDED` already establishes.
2. **Replay exactness (I7):** replaying the event log reproduces byte-identical `state.objects`, `state.semantic.derivations`, `evaluate_closure` result, `CanonicalIntentPackage` and `IntentDecisionHandoffV2`.
3. `route_intent_synthesis` is a **pure function** of `(state, proposal, origin, policy)` — no I/O, no clock, no provider import, no randomness. It never mutates state.
4. Ordering is deterministic: proposals are processed in returned order; gaps after proposals; derivation edges in `basis_claim_ids` order.
5. Runtime-owned ids, timestamps and invocation ids enter through injected factories, exactly as `SemanticGovernor` does today, so tests are deterministic.
6. **Zero provider calls in the test suite.** All synthesis tests use a scripted fake synthesizer, mirroring the existing `SpecReasoner` pattern.

---

## 23. Failure and refusal behaviour

**Whole-batch refusal**, mirroring `SemanticOutputError`: nothing is repaired, guessed, fuzzy-matched, dropped or substituted.

| condition | behaviour |
|---|---|
| proposal cites a claim not in the request | structural failure; **whole result refused**; nothing written |
| proposal cites a claim that is no longer live at apply time | structural failure; whole result refused |
| `target_kind` not in `allowed_target_kinds` | structural failure; whole result refused |
| `target_kind` not one of the ten intent-bearing kinds | structural failure; whole result refused |
| `basis_claim_ids` empty | schema rejection (`min_length=1`) |
| `relates_to_object_id` not in `known_intent_objects` | structural failure; whole result refused |
| result exceeds the request cap | refusal; never silent truncation |
| origin is not `HUMAN_STATED` and authority is `CANONICAL` | `REJECT` / `AUTHORITY_INVENTION` (§10.3) |
| `HUMAN_STATED` without covering `AuthorityRecord` | `REQUIRE_HUMAN` / `AUTHORITY_UNRESOLVED`; proposal recorded, nothing applied |
| material proposal without corroboration | `REQUIRE_SECOND_LENS`; proposal recorded, nothing applied |
| locus `DISPUTED` / pending / stale / `UNDECIDED` | `Gap` (§16); synthesizer never invoked for that locus |
| handoff v2 requested while `readiness.ready is False` | typed refusal naming the blocking condition; nothing emitted |
| closure not met | existing `IntentNotClosedError`; unchanged |

A refusal **always** leaves a readable record: the proposal event, the admission event, or a `Gap`. Silent failure is a defect.

---

## 24. Invariants

| # | invariant |
|---|---|
| **I1** | No synthesis without basis: `basis_claim_ids` non-empty; every id is a claim that is **live** in `derive_view` at both request and apply time. |
| **I2** | **No AI-chosen authority.** The synthesizer schema cannot express authority. A non-`HUMAN_STATED` proposal with `CANONICAL` authority is `REJECT` / `AUTHORITY_INVENTION` and never reaches a low-risk route. |
| **I3** | **Dual provenance.** For every basis claim: a `Relation(DERIVED_FROM, claim_id)` on the object **and** a `DerivationEdge(object_id, claim.created_by_judgment_id)`. Counts are equal (§12.5). The edge parent is **never** a `claim_id`. |
| **I4** | **Staleness propagates.** Superseding any basis claim's asserting judgment places the object in `view.stale_ids` and in `scoped_stale_object_ids(scope)`, making `readiness.ready` false. Fan-out: one claim supporting N objects marks all N. |
| **I5** | **No object mutation.** Correction produces a new object plus `REQUIREMENT_SUPERSEDED`; the original object's bytes are unchanged. |
| **I6** | **Scope is derived**, as the union of the basis claims' address scopes; never chosen by the synthesizer. |
| **I7** | **Replay exactness** (§22.2). |
| **I8** | **Contract purity.** A `PROPOSED` object never appears in `obligation_ids`. `LOW`-materiality proposals do not block closure; `MEDIUM`+ do. `Actor` remains in `purpose_ids`. |
| **I9** | **No second ledger.** Handoff v2 carries ids only — no statement text, claim value, rationale or evidence content. `KnownIntentObject` is never persisted, never an event payload, never returned in a proposal. |
| **I10** | **Gap-or-object exclusivity** (§16). |
| **I11** | **v1 frozen.** `domain/handoff.py` is byte-unchanged; every existing handoff test passes untouched. |
| **I12** | **Locus keying.** Two addresses merged by an active `EQUIVALENT` yield one object, not two. |
| **I13** | **Compatible extension is inert in slice 1** — no staleness, no gap (pins D5 so a later change is conscious). |
| **I14** | **Altitude separation.** Intent synthesis emits no `SemanticJudgment` and writes nothing into `state.semantic` except `DerivationEdge`s; `JudgmentKind` and `JudgmentProposal` are unchanged. |
| **I15** | **Event honesty.** Specialized canonicalization events carry only `CANONICAL` objects; `INTENT_OBJECT_PROPOSED` rejects `CANONICAL`. |

---

## 25. Tests

Every invariant has at least one test. Negative controls are mandatory where a rule could silently not fire.

**Structural / request**
- reject empty basis; reject a retired claim id; reject an out-of-scope claim; reject a claim that went non-live between request and apply.
- `DISPUTED` / `OPEN` / pending loci are never offered to the synthesizer (assert the synthesizer was not called).
- `KnownIntentObject` excludes rationale, provenance, revision, timestamps; `Decision` uses `statement`, not `rationale`.

**Authority (I2)**
- `HUMAN_STATED` with covering `AuthorityRecord` -> `CANONICAL`, `APPLY`.
- `HUMAN_STATED` without -> `REQUIRE_HUMAN`, nothing written.
- `AI_INFERRED` -> `PROPOSED`; assert `CANONICAL` is unreachable.
- **negative control:** a synthetic proposal carrying `CANONICAL` from a non-human origin is `REJECT` / `AUTHORITY_INVENTION` — explicitly assert it does **not** fall through to a low-risk `APPLY`.
- `RESEARCH_DERIVED` is treated exactly as `AI_INFERRED`; never privileged.

**Provenance (I3)**
- per basis claim, one `DERIVED_FROM` relation and one edge; counts equal.
- **assert the edge parent equals `claim.created_by_judgment_id` and differs from `claim_id`.**
- `research_derived()` is computed, not stored; adding non-research evidence via `SUPPORTS_CLAIM` flips it.

**Staleness (I4, I5)**
- supersede a basis claim -> object in `view.stale_ids` and `scoped_stale_object_ids` -> `readiness.ready is False` -> handoff v2 refuses.
- fan-out: one claim, three objects, all three stale in one traversal.
- reconciliation: new object + `REQUIREMENT_SUPERSEDED`; original bytes unchanged.
- **negative control (I13):** a compatible extension at a basis locus leaves the object non-stale and emits no gap.

**Gaps (I10)**
- `DISPUTED` -> `CONTRADICTION` gap and **zero** proposals.
- `UNDECIDED` value -> `MISSING_INFORMATION`.
- unformable statement -> `AMBIGUITY`, recorded via `AMBIGUITY_DETECTED`.

**Contract (I8)**
- `PROPOSED` Requirement absent from `obligation_ids`.
- `LOW` proposal does not block closure; `MEDIUM` does (`NON_CANONICAL_REQUIREMENT`).
- canonical Requirement with `requires_metric=False` closes without a `Metric`.
- `Actor` still in `purpose_ids`.

**Handoff (I9, I11)**
- v2 refuses when `readiness.ready is False`, for each of the three blocking conditions separately.
- v2 emits when ready; `intent_basis` matches recorded relations.
- field inspection: no free-text semantic field anywhere in v2.
- `domain/handoff.py` byte-unchanged; all `test_handoff.py` pass.

**Determinism (I7)**
- replay reproduces objects, edges, closure, package and handoff byte-identically.
- `route_intent_synthesis` purity: same inputs -> same decision; state not mutated.
- zero provider calls across the suite.

**Regression locks (must pass unchanged)**
`tests/unit/test_compatible_extension_lifecycle.py` in full — in particular `test_address_granularity_same_locus_new_proposition_is_one_address_two_claims` and `test_several_compatible_claims_coexist_and_a_byte_identical_reassert_is_refused` — plus `test_closure.py`, `test_package.py`, `test_handoff.py`, `test_semantic_view.py`, `tests/e2e/test_replay_to_package.py`. **Claim atomicity and v1 behaviour must not move.**

---

## 26. Out of scope

Explicitly **not** in this specification, and not in slice 1:

1. `Metric` and `VerificationObligation` synthesis; any metric or verifier design.
2. `Constraint`, `Contract`, `Decision`, `Goal`, `Outcome`, `NonGoal`, `Preference`, `Assumption`, `Intent` synthesis (slice 1 is `Requirement`-only).
3. `Actor` synthesis — `Actor` is canonical intent context, not an intent-bearing commitment (D1).
4. **Any change to `locus-validation-v1`.** Its outcome is permanently `LOCUS_POLICY_NOT_VALIDATED`. It is not re-adjudicated, reinterpreted or replaced. Any future evaluation of its frozen evidence under corrected granularity rules must be a **separately named successor or post-hoc artifact** and must never be presented as changing the original outcome.
5. The Research Worker itself — planning, job routing, budget policy, source selection, retrieval, reconciliation.
6. Deterministic normalization (§11 defines the fence; nothing is built under it in slice 1).
7. Multi-claim and cross-locus bases in slice 1 (the contracts support them; the slice does not exercise them).
8. Migrating any consumer from handoff v1 to v2.
9. Changes to any prompt, `POLICY_VERSION`, prompt hash, or output-schema hash.
10. A successor locus-policy validation experiment.
11. Materiality thresholds, corroboration policy, authorization policy (D3, D4).
12. Compatible-extension completeness semantics (D5).

---

## 27. Open decisions

**Blocking implementation planning:**

| # | decision | why it blocks |
|---|---|---|
| **D3** | Materiality and corroboration policy for material inferred intent: which target kinds and materiality levels are material; does independent corroboration suffice or is a human always required? | `IntentSynthesisPolicy` values. Slice 1 is pinned conservatively (§17.4) and is **not** blocked; anything beyond slice 1 is. |
| **D4** | Who assigns `materiality` for a synthesized `Requirement`, on what basis; defaults for `requires_metric` / `requires_verification`. | Slice 1 pins `LOW` / `False` / `False`. Beyond slice 1, unresolved. |

**Not blocking slice 1, must be resolved before broader use:**

| # | decision |
|---|---|
| **D5** | Compatible-extension semantics (§15.4). Slice-1 behaviour pinned by I13. |
| **D8** | Object-level supersession for the other nine intent-bearing kinds: `REQUIREMENT_SUPERSEDED` is `Requirement`-only (§15.2). A general event is needed before synthesis extends beyond `Requirement`. |
| **D9** | `KnownIntentObject` snapshot cap (§8) — the numeric bound is a slice-time decision recorded in the plan. |
| **D7** | Migration timing: when v2 replaces v1 downstream. Design-settled (coexist; v2 after independent proof); the timing remains a decision. |

**Settled by ruling, recorded for traceability:** D1 (Actor stays in `purpose_ids`, not intent-bearing), D2 (superseded — `Decision` is out of slice 1; `INTENT_OBJECT_PROPOSED` in §10.5 resolves the general non-canonical recording problem), D6 (handoff v2 gates on readiness; `evaluate_closure` unchanged).

---

## 28. Self-review: contradiction audit

Performed before commit, per instruction, across the four named risk areas.

**Authority.** The synthesizer cannot express authority (§9), runtime assigns it from origin (§10.2), and admission rejects a non-human `CANONICAL` (§10.3). §10.3 is redundant with §9 **by design** and is labelled as defence in depth, not as a second mechanism that could disagree. The §11 inheritance path is the only other route to `CANONICAL` and is fenced by three conjunctive conditions plus a construction-level restriction. *No contradiction.* One residual sharp edge is recorded honestly: §10.3 protects against a future refactor, and its test must therefore construct the illegal proposal directly rather than through the port.

**Staleness.** §15.1 asserts the blast radius blocks delivery; §20.6 asserts the package may still be built while stale. These are consistent only because the contract and the delivery gate are different objects — stated explicitly in §20.6 so a later reader cannot read one as contradicting the other. `evaluate_closure` is unchanged everywhere (§2.3, §5, §17.2, §20.1). *No contradiction.*

**Provenance.** §12.1 uses `claim_id`; §12.2 uses `created_by_judgment_id`. This asymmetry reads like an inconsistency and would invite a "cleanup" that silently breaks the blast radius, so §12.3 states the reason and forbids the change explicitly, with I3 asserting both halves and the test asserting the parent is *not* the claim id. *No contradiction; the trap is documented.*

**Second ledger.** Three surfaces carry semantic content: `KnownIntentObject` (statement text), `IntentSynthesisProposal` (statement), and handoff v2. The first is fenced as request-only and never persisted (§8), matching the existing `ComparisonContext` law. The second is the *origin* of the object's statement, not a copy of durable truth. The third carries ids only (§18, I9). `CanonicalIntentPackage` is embedded by value only because it is itself ids-only. *No contradiction.*

**Altitude.** §3 forbids extending `JudgmentKind`; §12.2 has synthesis writing `DerivationEdge`s into `state.semantic`. I14 states this exception precisely — derivation edges are the generic cross-engine hook `derivation.py` was explicitly built for ("future engines … attach to"), not semantic content. *No contradiction; the exception is named.*

**Residual risk accepted:** §15.4 is unresolved by intent, not by omission. Slice 1 is safe because it does not exercise an evolving corpus, and I13 pins the behaviour so the decision cannot be made silently later.
