# 9P2 — Contrastive Semantic Assimilation

**Status:** Design direction approved in chat on 2026-09-12; written spec awaiting user file review before implementation planning.

**Base branch:** `feat/intent-intelligence-v2`

**Base commit:** `a94754e1f9c029c7a4ef80d52eada9a35fad6102`

**Predecessor experiment:** 9P — `intent-v2-longitudinal-assimilation-v2`

**Predecessor adjudication:** FAIL with E1, E2, E3, E6, E7, E8, E9, E10 failing; persistence/context economy, replay integrity, and governance boundary supported.

---

## 1. Purpose

9P established that Foundry can retain durable semantic state and process later evidence with substantially less repeated context than full reconstruction. It did **not** establish that the frontier reasoner can reliably recognize when new evidence changes an existing interpretation rather than merely supporting it or describing a nearby new concept.

The next question is therefore narrower than a general Context Compiler:

> When new evidence is structurally connected to evidence that helped establish current semantic state, what minimum prior context must Foundry rehydrate so the frontier reasoner can correctly distinguish support, correction, contest, and genuinely new meaning?

9P2 introduces the minimum architecture needed to answer that question.

The proposed component is the **Contrastive Semantic Context Compiler v0**.

Its purpose is not to decide meaning. Its purpose is to assemble an auditable comparison problem for the semantic reasoner.

---

## 2. Postmortem: what 9P proved and what failed

### 2.1 What worked

9P successfully demonstrated all of the following:

1. Persistent semantic state can be carried across T1–T4 without whole-project reconstruction.
2. Arm F reread zero unchanged raw evidence.
3. Arm F used 124,126 input tokens over T2–T4 versus 266,423 for reconstruction Arm R.
4. The append-only semantic ledger replayed exactly.
5. Material semantic change remained governed: a model proposal did not directly change canonical state.
6. Track B showed the intended path can work: new evidence was associated with the existing validation locus, a corrected claim was proposed, an exact `SUPERSEDE` was proposed, and the current interpretation changed only after human authorization.

These results support the persistence, governance, and context-economy parts of the Foundry thesis.

### 2.2 What failed

The semantic continuity layer was not reliable enough.

#### Track A — correction forked into a new identity

At T1, the designated Track A address was:

`SemanticAddress | identity vs descriptors`

with the claim:

`address_id is the identity; subject, facet, and scope are descriptors never compared for equality`

At T2 the reasoner did two different things with the new evidence:

- it correctly `BIND_TO_ADDRESS` on the old Track A address;
- it also `CREATE_ADDRESS` for a nearby locus, `Referential identity | post-admission determinism`, and placed the materially corrected interpretation there.

It then emitted `SUPPORTS_CLAIM` for the old Track A claim rather than treating the materially new wording as a correction of the old interpretation.

Result: the semantic change forked instead of evolving the existing locus.

This caused or contributed to E2, E3, E6, E7 and E10 failures.

#### Track C — initial observation omission plus lost correction continuity

At T3 the reasoner failed to identify the concrete implementation defect:

`SemanticClaim.evidence_ids` are EvidenceItem IDs, but the reducer incorrectly copied those IDs into `Provenance.source_event_ids`, which is reserved for EventEnvelope IDs.

That is primarily an **observation coverage** failure: no prior durable interpretation existed that could be rehydrated to help.

At T4 the reasoner did identify the corrected provenance law, but it created a new semantic address rather than evolving the designated Track C continuity.

That second failure is a **semantic change continuity** failure.

The two failure classes must remain distinct:

```text
fresh material meaning is missed entirely
        -> observation coverage problem

existing meaning changes but is forked/recreated
        -> contrastive semantic context problem
```

9P2 addresses the second problem first.

---

## 3. Root cause

The 9P assimilation compiler compressed history too aggressively.

### Call 1 in 9P

Call 1 received:

- the new evidence delta;
- active in-scope address descriptors only;
- no current claims.

The reasoner therefore had to decide `BIND_TO_ADDRESS` versus `CREATE_ADDRESS` while seeing an address label but not the current semantic content held at that address.

### Call 2 in 9P

Call 2 received:

- the same new evidence delta;
- the touched addresses;
- their live claims.

But it deliberately did **not** rehydrate the historical evidence from which those claims were formed.

This made the model compare a current claim against new evidence without seeing the specific old-to-new source transition that caused the claim to need reconsideration.

### Corrected architectural diagnosis

The 9P invariant:

> persistent assimilation rereads zero unchanged evidence

was too strong.

Replace it with:

> persistent assimilation never reconstructs history wholesale; historical material may be rehydrated only through explicit, recorded structural dependencies, and every rehydrated byte must have an auditable why-this-is-in-context path.

The failure was therefore not lack of durable memory. The information already exists in Foundry's evidence, judgments, claim supports, provenance, and lineage. The missing layer is selective re-compilation of that history into a contrast the frontier reasoner can use.

---

## 4. Governing principle

The existing semantic law remains unchanged:

> **AI understands meaning. Foundry governs meaning.**

9P2 adds a subordinate law:

> **Foundry may deterministically identify structural reasons to compare objects; only the semantic reasoner may decide what the comparison means.**

Foundry may deterministically know:

```text
EV-new supersedes EV-old
CLAIM-X is effectively supported by EV-old
therefore CLAIM-X is structurally touched by EV-new
```

Foundry may **not** deterministically conclude:

```text
EV-new supports CLAIM-X
EV-new corrects CLAIM-X
EV-new contradicts CLAIM-X
EV-new is semantically unrelated to CLAIM-X
```

Those remain frontier semantic judgments.

No lexical threshold, embedding similarity, descriptor equality, deterministic string rule, or source-diff heuristic may become semantic authority.

---

## 5. Selected architecture

Three approaches were considered.

### Option A — prompt-only repair

Strengthen the system prompt and ask the model to distinguish support from correction more carefully.

**Rejected as insufficient.** The missing comparison material is absent from the request. Prompt wording cannot recover evidence that was not shown.

### Option B — contrastive semantic context compiler

Deterministically identify structurally affected prior semantic state and rehydrate a bounded old-to-new comparison context for the existing two-call assimilation loop.

**Selected.** It directly tests the 9P diagnosis while preserving the governance model, the two-call shape, and most of the context-economy result.

### Option C — add a third semantic-change classification call

Introduce a separate frontier call to classify support/new/correction/contest before normal assimilation.

**Deferred.** It may be useful if Option B fails, but it changes call count, latency, cost, and workflow before we have evidence that richer contrastive context is insufficient.

---

## 6. Scope

### In scope

1. Active claim profiles visible during Call 1 locus resolution.
2. Evidence-lineage transition capsules for superseding evidence.
3. Deterministic old-to-new textual diffs for directly versioned artifacts.
4. Structural mapping from predecessor evidence to live claims and addresses that depend on it.
5. Ephemeral comparison context in `ReasoningRequest`.
6. Explicit reasoner guidance for support versus correction versus contest versus new meaning.
7. Exact accounting of all rehydrated historical material and why it was included.
8. Track A as a regression test.
9. At least one separate, unseen lifecycle case for scientific validation.

### Out of scope

1. A general Context Compiler.
2. Embeddings.
3. Lexical semantic retrieval.
4. Whole-project or whole-history reconstruction.
5. A third frontier call.
6. New durable semantic judgment kinds.
7. Deterministic correction classification.
8. A code-AST observation engine.
9. General observation-coverage repair for Track C/T3.
10. Cross-model inheritance / 9Q.
11. A second provider or judge model.
12. Automatic repair of duplicate addresses created by prior runs.

---

## 7. Existing primitives retained unchanged

The following stay architecturally unchanged:

- `EvidenceItem` remains immutable and content-addressed.
- `artifact_ref` and `supersedes_evidence_id` remain deterministic lineage only, never authority.
- `SemanticAddress` identity remains `address_id`; descriptors never become equality keys.
- `SemanticClaim` remains immutable.
- `SemanticJudgment` remains the only form in which a semantic conclusion enters Foundry.
- `BIND_TO_ADDRESS`, `CREATE_ADDRESS`, `ASSERT_CLAIM`, `SUPPORTS_CLAIM`, `SUPERSEDE`, and `CONFLICTS_WITH` retain their existing semantics.
- material admission remains governed.
- the event ledger remains append-only.
- two frontier calls per delta remain the default for this slice.

No new durable truth primitive is required.

---

## 8. New ephemeral primitive: `ComparisonContext`

`ComparisonContext` is request context only. It is not canonical state, not a semantic object, not an event, not a judgment, and not persisted as truth.

Conceptually:

```text
ReasoningRequest
├── project_id
├── evidence
├── focus_object_ids
├── known_addresses
├── known_claims
├── allowed_judgment_kinds
└── comparison_context
```

`comparison_context` contains deterministic structural facts that explain why prior material is being shown.

Minimum shape:

```text
ComparisonContext
└── transitions: tuple[EvidenceTransitionContext, ...]

EvidenceTransitionContext
├── current_evidence_id
├── predecessor_evidence_id | null
├── artifact_ref | null
├── historical_diff
├── touched_claim_ids
├── touched_address_ids
└── inclusion_edges
```

`inclusion_edges` records the auditable structural path, for example:

```text
EV-T2-01
  --supersedes--> EV-T1-02
  --effective_evidence_of--> CLAIM-03937dfe0815d553
  --claim_at--> ADDR-ea676cc2a41f99e1
```

The exact Python field names are implementation details, but these semantics are locked.

### Non-citable rule

Historical comparison material is context, not current evidence.

The model may cite only IDs present in `ReasoningRequest.evidence` when making new evidence-backed proposals.

A predecessor evidence ID shown inside comparison context is not automatically admissible as new support for a new claim unless that evidence is also explicitly in the citable evidence set.

This prevents context rehydration from silently widening the evidence authority surface.

---

## 9. Structural relevance algorithm

For each current delta evidence item `E_new`:

### Step 1 — follow explicit evidence lineage

If `E_new.supersedes_evidence_id = E_old`, retrieve `E_old` from durable state.

No semantic search is needed.

### Step 2 — find claims structurally dependent on the predecessor

A live claim is structurally touched if `E_old` appears in its **effective evidence**:

```text
claim.evidence_ids
UNION
active SUPPORTS_CLAIM evidence
```

This is a deterministic graph lookup.

### Step 3 — find touched addresses

Each touched live claim yields its existing `address_id`.

### Step 4 — compile the comparison capsule

For every touched claim/address pair, include:

- the current address descriptor;
- the live claim;
- the old evidence identity;
- the new evidence identity;
- the deterministic old-to-new artifact diff;
- the structural inclusion path.

### Step 5 — no semantic conclusion

The compiler does not label the capsule `CORRECTION`, `SUPPORT`, `CONFLICT`, or `NEW`.

It merely says, in effect:

> This new evidence version replaces evidence that contributed to this current interpretation. Compare them.

---

## 10. Deterministic old-to-new diff

When both current and predecessor evidence belong to the same `artifact_ref`, Foundry computes a deterministic unified line diff.

The diff is a transport representation, not a semantic judgment.

The 9P2 diff contract is locked to:

- UTF-8 text already validated by `EvidenceItem`;
- line-based unified diff;
- exactly **3 unchanged context lines per hunk**;
- stable predecessor/current labels based on evidence IDs;
- no LLM, lexical ranking, semantic summarization, or heuristic hunk selection.

Example:

```diff
- address equality becomes deterministic and authoritative
+ address equality is a deterministic referential fact
+ under the current admitted interpretation only
+ it is not eternal semantic truth
+ the binding may later be superseded
```

### Exact bounds

For 9P2:

- maximum rendered historical diff per evidence transition: **65,536 Unicode characters**;
- maximum total rendered comparison context per reasoning request: **131,072 Unicode characters**.

If either limit would be exceeded, context compilation fails explicitly **before** the provider call. The compiler does not truncate the diff, choose “important” hunks, summarize the predecessor, or fall back to whole-history reconstruction.

These bounds are support limits, not semantic thresholds. They decide only whether the current implementation can safely present the structurally selected context.

### Diff requirements

1. Deterministic for identical old/new bytes.
2. No LLM used to create the diff.
3. No semantic ranking or summarization by deterministic code.
4. The exact rendered diff is included in request-accounting artifacts/tests.
5. No silent truncation.
6. No full historical corpus fallback.

---

## 11. Call 1 changes: semantic identity resolution sees active claim profiles

### 9P behavior

Call 1 showed address descriptors but no claims.

### 9P2 behavior

Call 1 still decides only:

```text
BIND_TO_ADDRESS | CREATE_ADDRESS
```

but every visible address is accompanied by its active claim profile, and any transition capsule structurally touching that address is included.

This does **not** allow Call 1 to assert or supersede a claim. It only gives the model enough semantic content to decide whether the new observation belongs to an existing locus.

Conceptually:

```text
ADDR-A
subject: SemanticAddress
facet: identity vs descriptors

CURRENT CLAIM
address_id is the identity; descriptors are not equality keys

TRANSITION
EV-new supersedes EV-old
EV-old is effective evidence for this claim
old->new diff: ...

TASK
Does the new observation refer to ADDR-A or require a genuinely new locus?
```

### Exact small-state bound

9P2 retains the existing **200 active in-scope address** support threshold.

- At `<= 200` active in-scope addresses, Call 1 may receive all active address descriptors and all active claim profiles for those addresses.
- Full contrastive transition detail is attached only to structurally touched addresses/claims.
- At `> 200` active in-scope addresses, context compilation fails explicitly with `ContextUnsupported` before a provider call.
- 9P2 introduces no lexical top-K, embeddings, truncation, or fallback retrieval branch.

This threshold is a support boundary only. It is not a semantic rule and does not rank or decide meaning.

---

## 12. Call 2 changes: explicit contrastive claim assimilation

Call 2 keeps the same allowed semantic operations:

```text
SUPPORTS_CLAIM
ASSERT_CLAIM
SUPERSEDE
CONFLICTS_WITH
```

No `CORRECTS` operation is introduced.

The existing correction path remains:

```text
ASSERT_CLAIM(new interpretation at known address)
+
SUPERSEDE(old claim's created_by_judgment_id)
```

The difference is that the model now sees the explicit transition context for claims whose predecessor evidence has been replaced.

### Required task guidance

For each structurally touched live claim, the model must choose among these semantic possibilities:

1. **Restatement / continued support**
   - emit `SUPPORTS_CLAIM`.

2. **Correction / old interpretation no longer current**
   - emit `ASSERT_CLAIM` at the same known address;
   - emit `SUPERSEDE` targeting the old claim's creating judgment.

3. **Additional compatible meaning at the same locus**
   - emit `ASSERT_CLAIM` at the same known address without superseding the old claim.

4. **Contest where neither interpretation should retire yet**
   - preserve both claims;
   - use `CONFLICTS_WITH` only when both claim IDs already exist in the request, under the existing reference law.

5. **Genuinely different semantic locus**
   - that identity decision belongs to Call 1 via `CREATE_ADDRESS`.

6. **Uncertain / no justified semantic change**
   - emit no unsupported change.

The model is never forced to classify every transition.

---

## 13. Track A expected regression behavior

Track A is no longer scientific evidence once the design is derived from its failure. It becomes a regression case.

Expected flow:

```text
T1
ADDR-A
└── C-A1

T2
E-new supersedes E-old
E-old structurally supports C-A1
        ↓
Contrastive Semantic Context Compiler
        ↓
Call 1 sees ADDR-A + C-A1 + old->new transition
        ↓
BIND_TO_ADDRESS -> ADDR-A
        ↓
Call 2 sees C-A1 + old->new transition
        ↓
ASSERT_CLAIM C-A2 at ADDR-A
SUPERSEDE J(C-A1)
        ↓
material governance
        ↓
if authorized:
C-A2 current
C-A1 historical
blast radius fires
```

Regression failure conditions include:

- corrected Track A meaning is created as a separate durable address;
- the old claim receives only `SUPPORTS_CLAIM` despite the known materially corrective transition;
- supersession is silently applied without governance;
- current interpretation changes before authorized supersession;
- unchanged whole historical evidence is resent without a structural inclusion reason.

---

## 14. Track C treatment

Track C is split into two lessons.

### C/T3 — observation coverage

9P2 does not claim to solve the failure to detect a materially important fact in a fresh artifact when no prior semantic state points at it.

That remains a separate possible future slice, provisionally called the **Observation Lens**.

### C/T4 — correction continuity

If a T3 claim about provenance identity exists, the T4 corrected reducer/spec version should structurally touch it through evidence lineage. The contrastive compiler must then give the reasoner enough old-to-new context to evolve that existing locus rather than create a disconnected correction address.

9P2 may test this path with controlled fixtures, but it must not claim to have solved T3 observation coverage merely because the T4 continuity case succeeds.

---

## 15. No new durable memory

9P2 must reuse existing durable facts rather than invent a second memory subsystem.

The required information already exists in:

- `SemanticState.evidence`;
- `EvidenceItem.artifact_ref`;
- `EvidenceItem.supersedes_evidence_id`;
- live `SemanticClaim`s;
- claim support records and derived `effective_evidence`;
- `SemanticJudgment.visible_evidence_ids`;
- semantic judgment rationale/provenance where useful for rendering current state.

The new compiler is a pure assembly layer over durable state.

It does not write canonical state.

---

## 16. Provider-neutral contract

`ReasoningRequest` remains the provider-neutral boundary.

9P2 extends it with a provider-neutral comparison-context model rather than putting xAI-specific context semantics into application code.

The xAI adapter may render that structure, but it must not be the source of its semantics.

The adapter trust boundary remains unchanged:

- the model receives bounded context;
- the model returns untrusted semantic drafts;
- runtime validates every reference against the request;
- admission decides whether a proposal can affect state;
- model output cannot carry canonical authority.

A model-facing schema or prompt change requires a conscious policy-version and seal update before any new live experiment.

---

## 17. Context provenance and accounting

Every historical item shown to the model must be explainable.

For each request, Foundry must be able to report:

```text
historical characters shown
historical evidence ids shown
which current evidence caused each item to be rehydrated
which structural edge justified inclusion
rendering mode = unified_diff_3_context_lines
```

Required inclusion reasons are structural, for example:

```text
SUPERSEDES
EFFECTIVE_EVIDENCE_OF
CLAIM_AT_ADDRESS
ACTIVE_CLAIM_PROFILE
```

No `SIMILAR_TEXT`, `EMBEDDING_NEAR`, `LIKELY_RELEVANT`, or equivalent semantic heuristic is permitted in 9P2.

This accounting is part of the experiment result because context economy is one of the Foundry thesis claims.

---

## 18. Safety / failure behavior

9P2 fails closed rather than silently widening context.

### Unsupported state size

If active in-scope addresses exceed 200, return `ContextUnsupported` before the provider call.

Do not silently send the full project history and do not narrow semantically.

### Oversized contrast

If one transition diff exceeds 65,536 characters or total comparison context exceeds 131,072 characters, return an explicit context-unsupported failure before the provider call.

Do not truncate, summarize, rank, or silently omit the transition.

### Missing predecessor

If `supersedes_evidence_id` names evidence absent from state, ingestion already fails under existing lineage rules; the compiler does not repair it.

### Broken structural chain

If a live claim is structurally touched but the compiler cannot render the required comparison context, fail before the model call rather than omit the transition silently.

### No semantic auto-repair

The compiler never turns a model's `CREATE_ADDRESS` into a `BIND_TO_ADDRESS`, never redirects claims, never inserts a missing `SUPERSEDE`, and never merges duplicate addresses after the fact.

A wrong model judgment remains auditable evidence of model/architecture performance.

---

## 19. Invariants

The following are locked for 9P2:

1. **Meaning remains AI-owned.** Deterministic machinery does not classify support/correction/new/contest.
2. **Selection is structural only.** Historical context is rehydrated because of explicit durable edges, not semantic similarity.
3. **Historical context is non-citable unless separately supplied as current evidence.**
4. **No whole-history fallback.** Unsupported bounded compilation fails explicitly.
5. **Two-call assimilation remains.** No third semantic call in this slice.
6. **No new semantic judgment kinds.** Existing operations are sufficient.
7. **Correction remains governed.** A materially corrective `SUPERSEDE` follows existing authority/admission rules.
8. **Claims remain immutable.** Historical evidence context never rewrites a claim.
9. **Addresses remain immutable identities.** The compiler cannot merge or rename identity deterministically.
10. **Every rehydrated historical character has an auditable inclusion path.**
11. **Regression cases are not scientific validation.** Track A can prove we stopped repeating a known failure, not that the general architecture works.
12. **Track C/T3 remains unsolved unless separately validated.**
13. **Support bounds are not semantic thresholds.** The 200-address and character limits may stop a request but may never decide meaning.

---

## 20. Implementation boundary

The intended first implementation slice should touch only the minimum seams required for the design:

1. provider-neutral request/context models;
2. contrastive context assembly in the assimilation-context layer;
3. deterministic unified-diff rendering helper;
4. Call 1 assembly to expose active claim profiles and transition context;
5. Call 2 assembly to expose transition context;
6. provider rendering of the new context;
7. prompt/policy seal update;
8. unit tests for structural selection, citable boundaries, determinism, and size failures;
9. Track A regression test with scripted semantic outputs;
10. a new preregistered 9P2 experiment harness only after the implementation passes local verification.

No unrelated semantic-domain refactor is authorized.

---

## 21. Test strategy

### Unit tests

Must prove:

- predecessor evidence is selected only through `supersedes_evidence_id`;
- a claim is structurally touched only through derived effective evidence;
- untouched claims are not placed into transition capsules;
- touched address IDs come from touched claims, not descriptor matching;
- unified diff output is stable with exactly three unchanged context lines per hunk;
- a transition diff over 65,536 characters is refused before provider invocation;
- total comparison context over 131,072 characters is refused before provider invocation;
- prior evidence in comparison context cannot be cited by new drafts unless present in `request.evidence`;
- Call 1 can see active claim profiles without gaining claim-changing judgment kinds;
- Call 1 refuses more than 200 active in-scope addresses;
- Call 2 still uses exactly the existing claim-assimilation kinds;
- context accounting names every historical inclusion edge;
- no truncation or whole-history fallback exists.

### Regression test

Track A must reproduce the desired correction path with controlled scripted model outputs and prove the resulting governance/blast-radius mechanics.

This regression test verifies plumbing and protects against reintroducing the known 9P failure shape.

### Scientific validation

A separate unseen lifecycle sequence must be preregistered before the next live model run.

It must contain at least:

- one unchanged/restated interpretation that should produce support rather than correction;
- one materially corrected interpretation that should reuse the existing locus and propose governed supersession;
- one genuinely new semantic locus that should still create a new address;
- one control locus unaffected by the changes.

The exact expected semantic outcomes must be sealed before live calls.

Track A may be included as a regression, but cannot be the sole or primary proof.

---

## 22. Primary hypothesis for the next live experiment

H-9P2:

> For versioned evidence changes whose predecessor evidence structurally contributes to existing live semantic state, persistent assimilation with contrastive structural rehydration will correctly distinguish continued support, correction of existing meaning, and genuinely new meaning without reconstructing full project history.

A live experiment may claim PASS only if correctness conditions hold first and context use remains materially below reconstruction.

Efficiency remains a necessary condition, never a substitute for semantic correctness.

---

## 23. Metrics

The next experiment records at minimum:

### Correctness

- existing-locus reuse rate on preregistered changed loci;
- erroneous duplicate-address count;
- correct support-vs-correction decisions;
- required supersession proposed at the correct old judgment;
- unauthorized semantic mutation count;
- control-locus stability;
- material semantic errors by arm.

### Context economy

- current-delta input characters/tokens;
- historical comparison characters/tokens rehydrated;
- number of predecessor evidence items shown;
- number of structurally touched claims shown;
- number of untouched historical evidence items shown, expected zero;
- cumulative input tokens versus reconstruction;
- cost and wall time.

### Governance / replay

- pending material proposals;
- authorizations;
- stale blast radius after authorized supersession;
- scoped readiness;
- replay state match;
- replay view match.

---

## 24. Success criteria before 9Q

9Q cross-model inheritance remains blocked until all of the following are true:

1. Track A regression passes.
2. The unseen 9P2 lifecycle correctness gate passes.
3. Persistent context remains materially smaller than reconstruction.
4. No deterministic semantic authority has been introduced.
5. Governance and replay invariants continue to hold.
6. The observation-coverage problem is either separately solved or explicitly shown not to block the lifecycle being handed to another model.

Only then is it meaningful to ask whether another frontier model can inherit the durable state.

A different model inheriting semantically malformed state would test portability of error, not compounding intelligence.

---

## 25. Architectural conclusion

9P did not show that persistent semantic memory is a dead end. It showed that **durable state without contrastive recompilation is insufficient**.

The correct next step is not more memory and not more deterministic semantics.

It is a small compiler that reconstructs the **minimum relevant contrast** from already-durable structural history and hands that contrast back to the frontier reasoner.

The intended pipeline becomes:

```text
NEW EVIDENCE DELTA
        +
EXPLICIT VERSION LINEAGE
        +
STRUCTURALLY TOUCHED LIVE SEMANTIC STATE
        +
BOUNDED OLD->NEW CONTRAST
        ↓
CONTRASTIVE SEMANTIC CONTEXT COMPILER
        ↓
FRONTIER SEMANTIC REASONER
        ↓
BIND / CREATE
SUPPORT / ASSERT / SUPERSEDE / CONTEST
        ↓
DETERMINISTIC GOVERNANCE
        ↓
DURABLE STATE
```

This is the minimum architecture warranted by the 9P evidence.
