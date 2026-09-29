# Intent Intelligence v2 — AI-Native Semantic Identity and Consolidation

## Status

**LOCKED CORE ARCHITECTURE (Task 9N amendments, architect-approved) — implementation of
the core slice authorised.**

The amendments recorded under headings marked **[9N LOCK]** supersede any conflicting
wording elsewhere in this document. Where the 9M text and a 9N lock disagree, the lock
wins. Items outside the core slice remain provisional (see §9, §27).

- Supersedes nothing in v1. Intent Intelligence v1 remains frozen and unmodified.
- Design evidence: `docs/superpowers/postmortems/2026-09-10-intent-intelligence-v1-comparative-postmortem.md` (Task 9L), commit `19bcd6ea2f81a63f22ddd1d9192c52a9a1dee5b6`.
- Governing law: `FOUNDRY_CONSTITUTION.md`, in particular Laws 3, 4, 5, 7, 8, 9, 10, 13.
- This document contains **no implementation and no implementation plan**.

---

## 1. Problem Statement

### 1.1 [9N LOCK] The Intent Engine starts from evidence, not from typed requirements

The pipeline does **not** begin at "messy human intent". It begins at **any project
evidence**: human statements, documents, code, tests, tickets, pull requests, agent
conversations, existing architecture, runtime observations, research, and brownfield
archaeology (dig) output. Human-written requirements are one evidence source among many.

Greenfield and brownfield are different initial conditions converging into the **same
semantic substrate**:

```text
GREENFIELD  human conversation ─┐
                                ├──►  Evidence  ──►  Semantic reasoning  ──►  one semantic state
BROWNFIELD  code/tests/tickets ─┘
```

The Intent Engine must never depend on humans changing behaviour and writing formal
requirements. 9N defines a general evidence-ingestion contract that dig can feed directly;
it does not build dig.

### 1.2 The v1 defect

Intent Intelligence v1 discovers the right unresolved issues and then emits each one
several times, under several labels, with no mechanism able to tell that they are the
same thing.

The defect is not intelligence. It is the absence of a **durable semantic identity** and
of a **governed consolidation stage** between discovery and emission.

v2 must add both **without** replacing semantic reasoning with deterministic rules.
Meaning is open-ended. `"retain audit records for seven years"` and `"audit history must
remain accessible for 84 months"` are the same requirement and share almost no literal
representation. No key comparison, keyword overlap, or similarity threshold can be
allowed to decide that question.

The design therefore has one organising sentence:

```text
AI understands meaning.
Foundry governs meaning.
```

---

## 2. Evidence From v1

All figures are frozen 9K/9L measurements. They are design inputs, not targets.

**Discovery is not the problem.**

| | Foundry | Baseline |
|---|---|---|
| critical semantic recall | 31/32 | 31/32 |
| overall semantic recall | 55/58 | 55/58 |
| Foundry-only matches | **0** | — |
| Baseline-only matches | — | **0** |
| trap concepts matched (conflict/authority/staleness/insufficiency) | 14/14 | 14/14 |

Coverage was not merely tied; it was **identical**, concept for concept.

**Everything measurable that went wrong happened after discovery.**

```text
+31 predictions  =  -1 useful  +6 unsupported  +26 redundant
```

**The identity is blind to its own duplicates.**

| Property of a (duplicate, anchor) pair | Foundry | Baseline |
|---|---|---|
| shares `GapKind` | **0 / 44** | 0 / 25 |
| shares `subject_key` | **3 / 44** | 1 / 25 |
| shares ≥1 semantic-proposal ancestor | **42 / 44 (95.5%)** | n/a |
| base rate: any two gaps in a case share an ancestor | 34.8% | n/a |

Ancestry overlap is **2.75× enriched** on true duplicates. Source-event overlap is not a
usable discriminator (76.7% base rate). Self-reported confidence is not usable either
(redundant 0.850 mean vs matched 0.881, fully overlapping ranges).

**Grounding is structural, not semantic.** Both safety incidents cited `source_event_id`s
that genuinely exist. v1's validation could not have caught either.

**Cost is contract, not evidence.** Rendered visible evidence was byte-identical between
contestants (23,687 chars). **91.8%** of Foundry's input-token overhead was the
transmitted output schema.

**The semantic plane already exists but is unexploited.** 371 semantic proposals; 62.6% of
referenced proposals fan out into more than one gap; 22.1% are referenced by nothing.

**Conclusion drawn for this design:** Foundry already computes the signal that identifies
its own duplicates and never uses it, because it has no identity strong enough to merge on
safely and no stage in which merging would happen.

---

## 3. Architectural Thesis

### 3.1 [9N LOCK] Frontier models are the brain; Foundry is the governance around it

Foundry's purpose is **not** to beat Grok, GPT or Claude at one-shot semantic discovery.
9L showed a frontier model already matches Foundry's discovery exactly. Frontier discovery
is commodity compute.

> **Foundry compounds frontier intelligence across evidence, time, agents, models and the
> software lifecycle by turning temporary semantic judgments into durable, governed and
> reconcilable state.**

```text
AI decides meaning.
Foundry decides whether and how that semantic judgment is allowed to change durable state.
```

> Discovery output is **disposable**. Interpreted, governed semantic state is **durable**.

v1 treated the model's emission as the product. v2 treats it as raw evidence entering a
governed pipeline whose output is persistent semantic state, from which gaps — and later,
architecture decisions — are **projected**.

Three consequences:

1. **Identity is assigned by Foundry, not by prose.** A semantic thing gets a Foundry-owned
   opaque address. Models propose *bindings* to that address; they do not own it. This is
   what makes state survive model replacement (Law 3, Law 13).
2. **Consolidation is a state transition, not a text operation.** It merges *addresses*,
   never *claims* — which makes conflict destruction structurally impossible.
3. **Classification is late.** `GapKind` is removed from identity entirely and assigned
   after consolidation, over a consolidated issue.

---

## 4. AI vs Deterministic Responsibility Boundary

This section is the contract every later section must obey.

### 4.1 AI decides (semantic compute)

AI is the **only** component permitted to answer an open-ended meaning question:

- What underlying subject and facet is this statement about?
- Does this candidate belong at an existing semantic address, or is it a new one?
- Are A and B the same issue, is one narrower, do they merely overlap, do they conflict,
  is one a consequence of the other?
- Does this candidate bundle several independent issues, and where are the seams?
- Does the cited evidence actually support this claim?
- Is this issue genuinely unresolved and material to safe implementation, given the
  decisions and authority already in state?
- Which `GapKind` best classifies this consolidated issue?

Every one of these is emitted as a **`SemanticJudgment`**: a structured, provenance-bearing
proposal. Never a mutation.

### 4.2 Deterministic Foundry decides (semantic governance)

- Schema validity and structural well-formedness of every judgment.
- Existence of every referenced event, address, issue, claim, and judgment.
- Whether a proposed transition is **admissible** under policy, authority and invariants.
- Application of admitted transitions, version creation, append-only ledger writes.
- Preservation of evidence edges, provenance, conflicts and history through every merge and
  split.
- Candidate **retrieval** (cheap, approximate, explicitly non-authoritative).
- Rejection, with a recorded reason, of any judgment that violates an invariant.

### 4.3 The line, stated as a rule

```text
AI may propose a state-changing semantic judgment.
AI may never apply one.

Deterministic Foundry may apply or refuse a state transition.
Deterministic Foundry may never originate an open-ended semantic conclusion.
```

### 4.4 Forbidden shortcuts

None of the following may **ever** become an authoritative semantic rule in v2:

```text
same subject string          = same meaning
same GapKind                 = same meaning
high embedding similarity    = same meaning
shared source event          = same meaning
shared semantic ancestor     = same meaning
AI confidence > threshold    = safe merge
```

Each may be used **only** to decide *"these deserve comparison"*. Candidate generation is
not a semantic decision.

### 4.5 [9N LOCK] Referential identity after admission — the corrected law

```text
AI makes the semantic judgment:   candidate X refers to semantic address ADDR-x.
Foundry admits and records that judgment.

After admission:
  ADDR-x == ADDR-x  is a deterministic REFERENTIAL fact
                    under the CURRENT admitted interpretation.

It is NOT a new semantic inference.
It is NOT eternal truth.
It is NOT model-independent proof that the binding judgment was semantically correct.
The binding may later be superseded.
```

Foundry may use `ADDR-x` as X's admitted semantic reference in the current view. Foundry
may **never** use address equality — or descriptor equality, or anything else deterministic
— to *originate* meaning. Determinism begins only **after** an admitted semantic judgment,
and it ends the moment that judgment is superseded (§19). Two candidates whose `subject`,
`facet` and `scope` descriptors are byte-identical are **not** the same thing until a
reasoner says so and Foundry admits it.

The same principle governs quantities: once AI has normalised two claims to structured
values, comparing `7 year` against `10 year` is arithmetic, not interpretation. Foundry may
compute that they differ; only AI may decide that both statements are claims about the same
address in the first place.

---

## 5. Architecture Alternatives

### Option A — Gap-centric AI consolidation

Keep `GapProposal` as the primary object; add an AI pass that judges relations between
emitted gaps and drops duplicates.

- **Pros:** smallest change; reuses everything; fastest to test.
- **Cons:** identity remains `(GapKind, subject_key)`, which is blind to 100% of measured
  duplicates. `GapKind` is still assigned before anything decides two gaps are the same
  issue, so the 6 measured `SAME_ISSUE_DIFFERENT_GAPKIND` duplicates remain structurally
  invisible. Nothing persists, so the lifecycle thesis stays untestable. Produces a
  cleaner list, not a durable asset.
- **Verdict:** rejected. Treats the symptom.

### Option B — Semantic-state-first

Discovery emits only normalized semantic candidates with no gap framing. All gaps are
projected from consolidated state.

- **Pros:** cleanest conceptual model; strongest durability; classification is naturally
  late.
- **Cons:** it changes the discovery contract, which is the **one thing v1 provably does
  well** (31/32 critical, identical to a frontier baseline). Reframing the discovery task
  risks regressing the only requirement that must not regress. It also front-loads the
  full persistent-state machinery before any of it has been shown to pay.
- **Verdict:** rejected for v2's first form — right destination, wrong first step.

### Option C — Hybrid: semantic candidate → governed state → gap projection

Discovery keeps its proven framing and emits a `SemanticIssueCandidate` carrying an
**advisory, non-binding** gap hypothesis. Foundry retrieves candidates, AI adjudicates
address binding and relationships, deterministic policy consolidates into persistent
semantic state, and gaps are projected — with `GapKind` assigned *after* consolidation.

- **Pros:** preserves the discovery behaviour that works; removes `GapKind` from identity;
  gives a durable substrate; each stage is independently measurable; shrinks the discovery
  output schema (the measured 91.8% cost driver) by moving classification, relations,
  grounding and materiality out of it.
- **Cons:** more moving parts than A; more calls than a single pass.
- **Verdict:** **recommended.**

---

## 6. Recommended Architecture

**Option C.**

```text
SOURCE EVIDENCE (immutable events)
        │
        ▼
BOUNDED INPUT COMPILATION                          deterministic
        │
        ▼
AI DISCOVERY  ──────────────────────────────────►  SemanticIssueCandidate[]   (ephemeral)
        │                                          small schema; advisory gap hypothesis
        ▼
CANDIDATE RETRIEVAL                                deterministic, approximate,
  known addresses │ ancestry │ lexical             NON-AUTHORITATIVE
        │
        ▼
AI SEMANTIC ADJUDICATION  ──────────────────────►  SemanticJudgment[]  (immutable evidence)
  address binding │ relations │ split seams        cluster-at-a-time, not pairwise
  grounding │ materiality
        │
        ▼
DETERMINISTIC ADMISSIBILITY + POLICY               may REJECT, APPLY, or ESCALATE
        │
        ▼
STATE TRANSITION                                   append-only; versioned
        │
        ▼
PERSISTENT SEMANTIC STATE
  SemanticAddress · SemanticIssue · SemanticClaim
        │
        ▼
AI CLASSIFICATION (late)  ──────────────────────►  GapKind over the consolidated issue
        │
        ▼
GAP PROJECTION                                     deterministic; a view, not a record
```

**Why this ordering, from evidence:** every measured defect lives between "AI discovered the
issue" and "the issue was emitted". This architecture inserts governance exactly there and
changes nothing before it.

---

## 7. Semantic Primitive

### 7.1 The address / claim split

The postmortem's candidate fields were `subject / property / predicate / value / unit /
scope`. Evaluated: these conflate two different things, and the conflation is the source of
v1's failure.

```text
"audit records must be retained 7 years"
"audit records must be retained 10 years"
```

These are **the same address** with **conflicting claims**. Any primitive that folds the
value into the identity makes them different things and destroys the conflict. Therefore:

| Field | Belongs to | Rationale |
|---|---|---|
| `subject` | **Address** | the governed concern (act, entity or record, entitlement, state, decision or coherent operational concern) |
| `facet` | **Address** | the question about that governed concern as a whole (amended 2026-09-28, §7.1.1); never one of its dimensions. From `intent-v2-locus-v3` it is `canonical_facet(subject)`, a deterministic projection (amended 2026-09-29, §7.1.2) |
| `scope` | **Address** | the bounded context in which it holds |
| `predicate` | Claim | the relation asserted (`at_least`, `equals`, `must_not`, `undecided`, …) |
| `value` | Claim | what is asserted |
| `unit` | Claim | dimension of a quantitative value |

Six fields survive, redistributed across two objects. `property` is renamed `facet` to avoid
collision with the software sense of "property".

### 7.1.1 [AMENDED 2026-09-28] Address grain: one governed concern (G2)

The original row read `facet`: "which property/aspect/question of the subject (v1's
`property`)". That definition is **withdrawn**. It made every dimension of a concern a
separate address, and it reached the model beside the locus policy's contrary guidance
(`intent-v2-locus-v1` appended "one stable question … put the specific aspect in the claim
predicate" beneath a base prompt that still said "one facet (property, aspect, or
question)"). Locus validation v2 (`intent-v2-locus-validation-v2`, adjudicated `2ea8ef6`)
exposed the conflict: in both of its failures (9P3's C09 cancellation locus and late-delivery
compensation) the model wrote a dimension-shaped facet, then treated a later compatible
proposition as a different question and created a new address. That validation remains
`LOCUS_POLICY_NOT_VALIDATED` for `intent-v2-locus-v1`; 9P3, locus validation v1 and v2 and
their results are unchanged historical evidence of this defect.

**Authoritative definition.** A semantic address represents **one governed act, entity or
record, entitlement, state, decision or coherent operational concern**. `subject` names the
concern; `facet` asks about the concern as a whole and never names one of its dimensions or
paraphrases the first proposition known about it.

**Dimensions are claims.** Who may perform it, when it may occur, eligibility and
preconditions, effects, limits and quantities, deadlines, destinations, what repeating it
does, and exceptions are claims (predicates) at the concern's one address. A proposition that
answers a different who / when / how / how long / whether about the same concern never
creates an address.

**Separate-address rule.** A new address is created only for a genuinely independently
governed act, entity or record, entitlement, decision, state transition or operational
concern: one with its own rules and lifecycle, whose rules can change without changing the
first concern's. Topical similarity, a shared word, a shared document or a shared subject area
never merges two concerns; a different grammatical dimension never splits one.

**Process-stage rule.** A stage of a process has its own address only when it is itself
independently governed as an operation or decision. A deadline for doing something, an
eligibility condition, an amount, a payment destination, an actor, an effect or a repetition
rule belongs to the concern it constrains. (Late-delivery compensation is one concern: its
entitlement, the amount refunded, where it is paid and the deadline for requesting it are
claims at one address.)

**Reaching the model.** Exactly one definition reaches the model: policy
`intent-v2-locus-v2` rewrites the base definition rather than appending to it
(`docs/superpowers/specs/2026-09-28-ie2-governed-concern-grain.md`). Historical policy
identities are unchanged.

### 7.1.2 [AMENDED 2026-09-29] The facet is a canonical projection of the subject

Under §7.1.1 `subject` names the governed concern and every dimension is a claim, so the
facet carries no semantic information of its own: its only required content was "the concern
as a whole", which the subject already names. Locus validation v3
(`intent-v2-locus-validation-v3`, adjudicated `4e277a6`) showed that leaving the facet to the
model adds a second, unnecessary semantic choice that the model gets wrong while getting the
grain right: zero over- or under-splits, yet facets naming one dimension ("Sender refund
entitlement", for both late-delivery and damage compensation) or no concern at all ("How it
is governed" on all sixteen payment concerns; "Governance"; "Lifecycle").

**Invariant.** The facet is a stable canonical descriptor of the governed concern and carries
no independent partitioning decision: `facet == canonical_facet(subject)`, where
`canonical_facet(subject) = "Rules governing " + subject`, the subject preserved byte for
byte. The projection is deterministic, inference-free and injective (distinct subjects give
distinct facets), so it can neither split nor merge concerns; the concern decision stays with
the admitted CREATE/BIND judgment, and a subject that fails to distinguish two concerns is a
subject defect the projection faithfully exposes rather than hides.

**Descriptors, not keys.** §7.2 is unchanged: subject, facet and scope are never equality
keys; `address_id` is the identity. No address, claim, event, reducer or identity rule
changes, and no stored address is migrated.

**Contract.** Policy `intent-v2-locus-v3` (`XAICanonicalFacetSemanticReasoner`) asks the model
for the governed concern only: its output contract `ConcernDraftPayload` has CREATE_ADDRESS
and BIND_TO_ADDRESS drafts without a facet field (a reply carrying one violates the sealed
schema and is refused whole), and the adapter sets every candidate facet to
`canonical_facet(subject)`. Admission enforces it: under `AdmissionPolicy(canonical_facets=True)`
a CREATE_ADDRESS or BIND_TO_ADDRESS candidate with any other facet is refused
`STRUCTURAL: NON_CANONICAL_FACET`. The flag defaults to False, so historical policies and
ledgers route exactly as before; every earlier policy identity and the shared output schema
`ffc6946a…` are unchanged (`docs/superpowers/specs/2026-09-29-ie2-canonical-facet.md`).

### 7.2 SemanticAddress

```text
SemanticAddress
  address_id            Foundry-owned opaque stable ID   ← the durable identity
  subject               AI-normalized noun phrase        (descriptor, not a key)
  facet                 AI-normalized question about the governed concern as a whole
                        (descriptor, not a key; §7.1.1); from intent-v2-locus-v3 the
                        deterministic canonical_facet(subject) (§7.1.2)
  scope                 AI-normalized bounding context, or GLOBAL
  created_by_judgment   the admitted binding judgment that created it
  descriptor_version    immutable version of the human-readable descriptor
```

**`subject`, `facet` and `scope` are descriptors, never keys.** Foundry never compares them
for equality to decide identity. `address_id` is the identity, and a candidate reaches it
only through an admitted AI binding judgment.

This is what makes state model-independent (§24): a different model, or a human, proposes a
binding to the same `address_id`; nothing in the durable state carries the vocabulary of the
model that created it.

#### 7.2.1 [9N LOCK] Addresses are immutable identities and are never destructively merged

If `ADDR-17` and `ADDR-42` both exist and a reasoner later judges them equivalent, Foundry
does **not** delete either, does not rewrite any historical reference, and does not copy
claims from one to the other. It records the admitted `EQUIVALENT` judgment and derives a
**current representative view**:

```text
ADDR-17 ─┐
         ├── admitted EQUIVALENT (judgment J)  ──►  current representative / view
ADDR-42 ─┘
```

Every historical object keeps referring to whichever immutable address it originally
referenced. If the equivalence is later shown wrong, J is superseded, the current view is
recomputed, and `ADDR-17` and `ADDR-42` are distinct again. **No historical reference ever
becomes invalid.** The representative is a derived, replayable view — never a rewrite.

### 7.3 SemanticClaim

```text
SemanticClaim
  claim_id              immutable
  address_id            which address this asserts about
  predicate             AI-normalized
  value                 structured: quantity | enumeration | text | UNDECIDED
  unit                  present only for quantity
  evidence_ids          supporting EvidenceItem IDs (>= 1) - THE evidence edge
  grounding             the admitted GroundingJudgment for this claim
  authority             reuse existing domain Authority enum
  provenance            of the asserting reasoner; its source_event_ids are actual
                        ledger EventEnvelope IDs only, when available - never EvidenceItem IDs
  recorded_by_judgment  provenance of the AI judgment that produced it
```

**Identity-type law (9N-R1).** Two identifier families must never be conflated:
`SemanticClaim.evidence_ids` holds *EvidenceItem* IDs and is the evidence relationship;
`Provenance.source_event_ids` holds *EventEnvelope* IDs only. When the ingestion event IDs
behind a claim's evidence are not known at construction time, `source_event_ids` is left
empty (`()`) rather than filled with identifiers of the wrong type. No event ID is ever
invented and no EvidenceItem ID is ever copied into an event-ID field.

**Claims are append-only and are never merged, rewritten, or averaged.**

### 7.4 SemanticIssue

```text
SemanticIssue                       (mutable head)
  issue_id
  address_id                        exactly one
  head_version_id
SemanticIssueVersion                (immutable)
  version_id
  claim_ids                         the set of claims currently held
  epistemic_state                   see §8
  materiality                       admitted MaterialityJudgment
  contributing_candidate_ids        every discovery candidate ever folded in
  relations                         admitted relations to other issues
  supersedes_version_id
  created_by_judgment_ids
```

An issue is the *consolidated unresolved thing at one address*. One address holds at most
one live issue; that is what makes the minimal set minimal.

### 7.5 What is deliberately NOT in the primitive

No entity types, no ontology classes, no global identifiers, no cross-project subjects, no
inference rules. YAGNI (§30). The primitive exists to answer six questions — identity,
consolidation, conflict, bundling, materiality, grounding — and nothing else.

---

## 8. Semantic Claims and Epistemic State

Reuse what v0 already defines rather than inventing a parallel vocabulary:

- **Authority** — `OBSERVED / INFERRED / PROPOSED / CANONICAL / DISPUTED / REJECTED /
  SUPERSEDED` (existing `foundry.domain.common.Authority`).
- **Lifecycle** — `ACTIVE / RESOLVED / REJECTED / SUPERSEDED` (existing `LifecycleStatus`).
- **Materiality**, **RiskLevel**, **Provenance** — existing.

One new derived value is needed on `SemanticIssueVersion`, because an issue's epistemic
condition is not the same as any single claim's authority:

```text
IssueEpistemicState
  OPEN            no claim settles the address
  CLAIMED         one or more compatible claims, none yet authorised
  DISPUTED        two or more incompatible claims at this address
  SETTLED         an authorised claim resolves the address
```

`DISPUTED` is **computed deterministically** from an admitted claim-level
`CONFLICTS_WITH` relation at the address (§9) — it is never a merge outcome and can never be cleared by
consolidation. Only an authority event can move `DISPUTED → SETTLED`, and the losing claims
remain readable forever.

Law 7 is preserved exactly: confidence lives on judgments, authority lives on claims, and
provenance is mandatory on both.

---

## 9. Semantic Relationships

Cut aggressively from the candidate list. `SUBSUMES` and `SUBSET_OF` are inverses — one
directional relation is kept and the inverse is derived.

| Relation | Shape | Merges? | Why it exists (v1 evidence) |
|---|---|---|---|
| `EQUIVALENT` | symmetric | **yes — addresses only** | 13 paraphrase/kind-shift duplicates |
| `NARROWS` | directional A→B | no | 6 narrow-component duplicates |
| `CONSEQUENCE_OF` | directional A→B | no | 8 consequence restatements |
| `BUNDLES` | directional A→{B…} | no — triggers split | 14 bundled predictions |
| `CONFLICTS_WITH` | symmetric | **never** | conflict preservation (Law 8, Law 9) |
| `OVERLAPS` | symmetric | never | honest answer when neither equivalence nor containment holds |
| `DISTINCT` | symmetric | never | the explicit negative; prevents re-adjudicating a pair |

Seven values — **provisional beyond the core slice.**

**[9N LOCK] Core-slice vocabulary.** The 9N implementation carries only the relations
required by a testable core invariant: `EQUIVALENT`, `DISTINCT`, `CONFLICTS_WITH`.
Address binding and supersession are **judgment operations**, not ontology relations.
`NARROWS`, `CONSEQUENCE_OF`, `BUNDLES` and `OVERLAPS` remain designed but unbuilt; any
later addition must justify itself against a measured defect.

**Which objects relations connect.** `EQUIVALENT`, `NARROWS`, `CONSEQUENCE_OF`, `BUNDLES`,
`OVERLAPS` and `DISTINCT` relate **candidates and issues** — they are about whether two
*issues* are the same issue. `CONFLICTS_WITH` relates **claims** — it is about whether two
*assertions at one address* are incompatible. This split is the mechanism behind §12: issue
relations can cause a merge, claim relations never can.

Rules:

- **`EQUIVALENT` is the only merge-eligible relation, and it merges addresses, not claims.**
- `EQUIVALENT` and `CONFLICTS_WITH` are mutually exclusive at claim level; at *address*
  level they routinely coexist — that is precisely the two-claims-one-address case.
- `NARROWS` and `CONSEQUENCE_OF` are directional and carry a required
  `subordinate_independently_material: bool` answered by AI in the same judgment. This
  keeps a materiality question in AI's hands while letting the projection policy stay
  deterministic.
- `OVERLAPS` and `DISTINCT` produce no state change beyond recording that the pair was
  adjudicated. Their value is economic: an adjudicated pair is never re-sent to a model.
- `BUNDLES` never merges; it triggers §14.

**Rejected for v2:** `SUBSUMES` (inverse of `NARROWS`), `CAUSES`, `DEPENDS_ON`,
`REFINES`, `IMPLEMENTS`, and every general-ontology relation. None is required by a
measured v1 defect.

---

## 10. AI Semantic Judgment Contract

Provider-neutral. Expressed as a port, not a vendor payload.

```text
SemanticReasoner (protocol)
  bind_and_relate(cluster)   -> AddressBindingJudgment + RelationJudgment[] + SplitProposal[]
  ground(claim, evidence)    -> GroundingJudgment
  assess_materiality(issue)  -> MaterialityJudgment
  classify(issue)            -> ClassificationJudgment
```

Every judgment shares one envelope:

```text
SemanticJudgment
  judgment_id
  judgment_kind             BINDING | RELATION | SPLIT | GROUNDING | MATERIALITY | CLASSIFICATION
  inputs                    exact IDs of every object the reasoner was shown
  visible_evidence_ids      exact source events the reasoner was shown
  outcome                   the structured decision
  rationale                 concise, structured; NOT chain-of-thought
  confidence                metadata only — never a gate (§26)
  reasoner_identity         provider, model, version         ← provenance, not authority
  policy_version            reasoning-policy version in force
  proposed_at
```

Design constraints:

- **Bounded inputs.** A judgment must name every object it saw. A reasoner never receives
  whole project state (Law 3, Law 13).
- **Cluster-shaped, not pairwise.** `bind_and_relate` receives a bounded candidate cluster
  and returns a partition plus relations. This is both cheaper than *k²* pairwise calls and
  more accurate, because the reasoner sees all members simultaneously.
- **No provider vocabulary in the outcome.** Outcomes reference Foundry IDs and the fixed
  relation vocabulary only.
- **No hidden reasoning persisted.** Structured judgment, concise rationale, evidence
  references, provenance — nothing else (§25).

---

## 11. Candidate Retrieval

Retrieval decides *what deserves comparison*. It never decides meaning.

Three sources, cheapest first:

1. **Bound addresses (exact, authoritative).** If a candidate has already been bound to
   `ADDR-x` by an admitted judgment, the live issue at `ADDR-x` is a candidate by
   construction. This is the only exact mechanism, and it is authoritative only because an
   AI binding judgment already happened (§4.5).
2. **Semantic ancestry overlap (measured).** Shared `affected_proposal_ids` ancestry is
   **2.75× enriched** on true duplicates (95.5% vs 34.8%). This is v2's primary cheap
   retrieval signal, and it is the single most defensible mechanism in the design because
   it is the one thing the 9L forensics directly measured.
3. **Lexical / embedding hints (approximate, ranked).** Used only to fill remaining slots.

Explicitly **not** used for retrieval: source-event overlap alone (76.7% base rate — near
worthless as a discriminator) and confidence.

**Avoiding O(n²):** candidates per new issue are ranked and capped at *K*, then grouped into
clusters for adjudication. At v1 volumes (~16 issues per case) exhaustive pairwise would be
~120 comparisons per case; capped clustered retrieval reduces this to a handful of bounded
calls. *K* is `DEFERRED` (§27) pending measurement of retrieval recall.

**Retrieval recall is a first-class metric.** A missed candidate is an undetectable
duplicate, so §24 requires measuring it directly rather than assuming it.

---

## 12. Consolidation

**Definition:**

> Consolidation is the deterministic application of admitted AI relationship judgments to
> produce, per semantic address, one live issue carrying the union of all contributing
> evidence, claims, provenance and relations — without deleting anything.

Mechanics for `EQUIVALENT` between candidate *A* and live issue *I*:

1. Bind *A* to *I*'s `address_id`.
2. Append *A*'s claims to the issue. **Claims are never merged or reconciled.**
3. Union *A*'s evidence edges into the issue's edge set.
4. Append *A* to `contributing_candidate_ids`, immutably.
5. Create a new `SemanticIssueVersion`; move the head. The old version stays readable.
6. Recompute `IssueEpistemicState` deterministically from the claim set.

The §12 worked examples resolve automatically:

```text
A: retain 7 years  (product owner)      ┐
B: retain 7 years  (compliance)         ┘  one address, one issue, TWO evidence edges,
                                           TWO claims, both provenances retained

A: retain 7 years                       ┐
B: retain 10 years                      ┘  one address, one issue, TWO claims,
                                           epistemic_state = DISPUTED
```

**Because consolidation merges addresses and never claims, "consolidation destroyed a
conflicting value" is structurally impossible rather than policy-prevented.** This is the
strongest guarantee in the design and the direct answer to §12.

Duplicates are therefore *represented*, not deleted: the duplicate becomes a contributing
candidate and an evidence edge on one issue.

**[9N LOCK] Mechanics for `EQUIVALENT` between two existing addresses** `ADDR-A` and
`ADDR-B` (as opposed to a fresh candidate and a live issue) follow §7.2.1: both addresses,
both issues, all claims, all evidence edges and all historical references are retained
unchanged; the admitted judgment is recorded; the *current view* presents one representative
locus whose claim set is the union of both. Nothing is copied, moved, or deleted. Replaying
the same events reproduces the same view.

---

## 13. Conflict Preservation

A conflict is never a consolidation outcome to be avoided; it is a **first-class state** to
be reached.

- AI proposes `CONFLICTS_WITH` between two claims at one address.
- Foundry admits it and deterministically sets the issue to `DISPUTED`.
- No transition may clear `DISPUTED` except an authority event that settles the address.
- Settling marks losing claims `SUPERSEDED`; it never deletes them.
- A merge whose application *would* reduce the number of distinct claim values at an address
  is refused by invariant (§22), not by convention.

Cross-authority and cross-scope merges are the highest-risk transitions in the system, so
policy may require a stronger reasoner or human authority for them (§20). Both v1 safety
incidents were brownfield, where conflicting evidence is dense.

---

## 14. Bundling and Splitting

v1 was simultaneously too fragmented (51 redundant) and too coarse (14 bundled). Both are
failures of one missing capability: nothing decided what *one issue* is.

`BUNDLES` is proposed by AI when one candidate materially names several independent
unresolved issues. The judgment must return, for each seam:

```text
SplitProposal
  parent_candidate_id
  units[]:
    proposed subject / facet / scope     (address descriptors for each unit)
    evidence_event_ids                   which evidence supports THIS unit
    claim(s)                             belonging to THIS unit
  rationale
```

Deterministic guarantees on application:

- Every unit inherits full provenance back to the parent candidate and to the discovery run.
- **The union of unit evidence edges must equal the parent's evidence edge set.** No edge
  may be dropped, and a split that loses an edge is refused.
- The parent candidate remains immutable and readable as the origin of all units.
- Each unit then re-enters retrieval and may bind to an existing address like any candidate.

**Sentence and clause boundaries are never used as semantic seams.** The seam is an AI
judgment; Foundry only checks that the seam preserves information.

---

## 15. Materiality

v1's dominant precision failure was reopening explicitly settled matters — 5 of 9 unsupported
predictions — plus 2 speculative implementation risks and 1 generic best-practice demand.

The root cause is that v1 judged materiality **from isolated prose, with no view of what was
already decided.** v2 fixes the inputs, not the judge.

`assess_materiality(issue)` receives, deterministically compiled and bounded:

- the issue, its claims and its evidence;
- **existing canonical decisions at or near this address**;
- **authority records** relevant to the address;
- supersession history;
- current scope and closure state.

AI then answers, as one judgment:

```text
MaterialityJudgment
  genuinely_unresolved      bool
  materially_affects_intent bool
  already_resolved_by       claim/decision IDs, if any
  is_generic_practice       bool
  is_implementation_concern bool
  rationale
```

Deterministic policy projects a gap only when `genuinely_unresolved AND
materially_affects_intent`. Foundry never decides materiality itself; it decides what the
reasoner is allowed to see, and what the answer is allowed to change.

This is the clearest instance of the thesis: **the v1 failure was an input-compilation
failure being mistaken for a reasoning failure.**

---

## 16. Semantic Grounding

v1 validated that `source_event_id` exists. Both safety incidents passed that check while
asserting things the evidence did not support.

```text
claim + cited evidence  ──►  AI GroundingJudgment  ──►  deterministic admission
```

Verdict vocabulary, evaluated against the two real incidents rather than adopted:

| Verdict | Kept? | Justification |
|---|---|---|
| `SUPPORTED` | yes | the normal case |
| `PARTIALLY_SUPPORTED` | yes | **required by H-008 P-005** — the attribution claim was supported, the "issued but unrecorded" branch was not |
| `NOT_SUPPORTED` | yes | **required by H-010 P-013** — evidence did not establish the asserted dependency |
| `CONTRADICTED` | yes | distinct and safety-critical: evidence asserts the opposite |
| `INSUFFICIENT` | **cut** | not separable from `NOT_SUPPORTED` in practice, and the project-level notion it gestures at is already the `INSUFFICIENT_EVIDENCE` *GapKind*, which lives on a different plane |

Policy:

- `NOT_SUPPORTED` / `CONTRADICTED` → the claim is refused entry to canonical state. It is
  recorded as a rejected judgment with full provenance (Law 8 — evidence is preserved, not
  discarded).
- `PARTIALLY_SUPPORTED` → the judgment must identify the supported and unsupported parts;
  the unsupported part is either dropped or handed to the split machinery (§14).
- The judgment must attribute support **per cited event**, so a claim citing five events of
  which one is load-bearing cannot hide behind the other four.

**Deterministic invariant:** a valid source ID is never accepted as proof of substantive
grounding.

---

## 17. Gap Projection

**Gap becomes a projection, not the durable object.**

```text
persistent semantic state
  → issues where epistemic_state ∈ {OPEN, CLAIMED, DISPUTED}
  → AND admitted MaterialityJudgment says material and unresolved
  → AND not suppressed by an admitted relation
  → classify (AI, late)
  → Gap
```

**When is `GapKind` assigned?** *After* consolidation, by AI, over the consolidated issue —
with all its claims, all its evidence and its epistemic state visible. Not at discovery.

Evidence for lateness, stated honestly:

- **Supported:** `GapKind` in the identity made 6 measured `SAME_ISSUE_DIFFERENT_GAPKIND`
  duplicates structurally invisible, and **0 of 44** duplicate pairs shared a kind. Removing
  kind from identity is directly justified.
- **Not claimed:** that late classification improves *accuracy*. The baseline classifies
  just as early and scored better (46/55 vs 43/55). The postmortem marked this `UNRESOLVED`,
  and this spec does not promise a fix — it is a measured hypothesis (§24).

Discovery may still emit a **`gap_hypothesis`**: advisory, non-binding, never part of
identity, never carried into projection unquestioned. It exists only to preserve the
discovery framing that achieved 31/32.

Projection suppression rules (deterministic, over admitted relations):

- `CONSEQUENCE_OF` with `subordinate_independently_material = false` → subordinate not
  projected.
- `NARROWS` with `subordinate_independently_material = false` → subordinate not projected.
- `EQUIVALENT` → already one issue, so one gap by construction.
- **`DISPUTED` can never be suppressed by a relation.** No admitted relation may remove a
  disputed issue from projection.

A disputed issue still requires a materiality judgment — projection is a view, and a view
of every immaterial dispute is not useful. Two safeguards make this safe rather than a
loophole:

1. **Materiality for a `DISPUTED` issue is routed to a strong reasoner** (§20) and the
   judgment is recorded, so suppressing a conflict is an auditable decision with an
   author, never a silent default.
2. **The conflict itself is unaffected.** Projection changes what is *shown*; the two
   incompatible claims and the `DISPUTED` state remain in durable state regardless
   (§13, invariant 4). Nothing is destroyed by a projection decision.

This is the deliberate resolution of a real tension: Law 9 forbids material unknowns
disappearing silently, and §12 forbids conflicts collapsing. Both are satisfied by keeping
the conflict in *state* unconditionally while letting a recorded, strongly-reasoned
materiality judgment govern the *projection*.

---

### 17.1 [9N LOCK] Closure is scoped, never global

Foundry already evaluates closure per scope (`evaluate_closure(state, scope)`). v2
preserves and strengthens that: closure is **always evaluated for a scope and never assumed
globally**. Scope A being ready may move forward while scope B remains blocked. Scopes may
later correspond to a semantic address, a capability, a module or a work package; 9N does
not freeze closure thresholds.

---

## 18. Persistent State and Versioning

Fits the existing Foundry model without amendment.

| Plane | Rule |
|---|---|
| **Events** (`EventEnvelope`) | immutable, append-only, content-hashed, never rewritten |
| **Judgments** (`SemanticJudgment`) | immutable once recorded; superseded, never edited |
| **Interpretations** (`SemanticIssueVersion`, `SemanticAddress`, `SemanticClaim`) | immutable versions + mutable head pointer |

**Referential stability (§19 of the task, preserved exactly):** events and historical records
reference *immutable version IDs and judgment IDs only*. A head pointer is never persisted in
history.

Minimal new event vocabulary — two types, deliberately:

```text
SEMANTIC_JUDGMENT_RECORDED     an AI judgment exists            (evidence)
SEMANTIC_ISSUE_VERSIONED       a transition was applied         (canonical state)
    transition ∈ {CREATED, BOUND, MERGED, SPLIT, CLAIM_APPENDED,
                  DISPUTED, SETTLED, SUPERSEDED, REJECTED}
```

Keeping these separate is not bookkeeping — it is Law 8 made structural:

```text
Research → Evidence → Reasoning → Authorization → Canonical State
           ^judgment recorded              ^transition applied
```

A recorded judgment that policy refuses leaves the first event and no second. The proposal
is preserved; canonical state is untouched.

**The lifecycle example (§18 of the task):**

```text
T1  "retention undecided"          → ADDR-1 created, issue OPEN, claim(UNDECIDED)
T2  "product wants 7 years"        → bound to ADDR-1, claim(at_least, 7, year), CLAIMED
T3  "compliance requires 10 years" → bound to ADDR-1, claim(at_least, 10, year),
                                     CONFLICTS_WITH admitted → DISPUTED
T4  legal authority confirms 10    → authority event; 10-year claim CANONICAL,
                                     7-year claim SUPERSEDED, issue SETTLED
```

One address, four versions, every claim still readable, no rediscovery. This is the
behaviour a fresh one-shot model cannot produce without re-reading everything (§24).

---

## 19. Correction and Supersession

Semantic interpretation will sometimes be wrong. Correction is always **append + supersede**,
never destructive mutation.

```text
J1:  A EQUIVALENT B                             (admitted, applied)
     later evidence shows they differ by regulatory scope
J2:  supersedes J1; proposes DISTINCT + new scope-bearing addresses
     → J1 remains readable with its provenance and its original inputs
     → a new issue version splits the merged issue back into two
     → contributing candidates are re-attributed; no evidence edge is lost
     → affected projections are recomputed
```

Because every merge retains `contributing_candidate_ids` and the full evidence union,
**every merge is reversible**. That is a design requirement, not an accident: a
consolidation stage that could not be undone would be unsafe to run at all.

### 19.1 [9N LOCK] Supersession MUST propagate downstream — the derivation primitive

Correcting semantic memory is not enough. If downstream work relied on J1, Foundry must be
able to answer *"what depended on J1?"* and expose the transitive blast radius:

```text
superseded semantic judgment
    ↓ issue / version
    ↓ gap / obligation
    ↓ decision
    ↓ contract
    ↓ task
    ↓ artifact / code / test
```

Most of those layers do not exist yet. 9N therefore implements a **generic
derivation/dependency primitive** that future engines attach to:

```text
DERIVED_FROM   child B derives from parent A   (directional, transitive, append-only)
```

When an admitted semantic basis is superseded, the current derived view marks **every
transitive descendant** `STALE / NEEDS_RECONCILIATION`. Historical records of those
descendants are never rewritten; only the *current view* changes. Tests must prove
propagation through at least three levels (J1 → D1 → D2 → D3). The Decision Engine and
artifact reconciliation are not built here — only the hook they will hang on.

---

## 20. Intelligence Routing and Economics

Law 4 — cheapest trustworthy mechanism.

| Stage | Mechanism | Justification |
|---|---|---|
| Retrieval | deterministic | approximate, non-authoritative, free |
| Already-bound address | deterministic | the semantic decision already happened (§4.5) |
| Routine relation in a small cluster | cheap model | bounded inputs, fixed vocabulary |
| Cross-authority / cross-scope merge, conflict, split | strong model | highest-risk transitions; both v1 safety incidents were here |
| Unresolved high-authority semantic conflict | human | Law 5 — generation cannot certify itself |

### 20.1 [9N LOCK] Admission routing is risk-based, not universal

Two models are **not** required for every judgment, and a human is **not** required for
every canonicalization. Deterministic admission evaluates each proposed judgment against
existing authority, risk/material consequence, judgment kind, current conflict state,
independence requirements and structural validity, and routes it:

```text
APPLY                 low-risk, clear evidence, clear existing authority → one adequate
                      reasoner may auto-admit under policy
REQUIRE_SECOND_LENS   material / high-risk, or an equivalence with significant consequence
                      → an INDEPENDENT second semantic lens is required first
REQUIRE_HUMAN         required lenses disagree, or authority itself is unresolved
REJECT                structurally invalid, references missing objects, or the reasoner
                      attempts to create authority it cannot have
```

Rules that can **never** decide semantic authority: `confidence >= threshold`; "newer
wins"; "last writer wins". Confidence is metadata (§26). Authority remains separate from
confidence (Law 7).

**Independence.** Two invocations of the same model under the same policy over the same
context are not independent merely because they carry different invocation IDs. Every
judgment carries a reasoner fingerprint (provider, model, policy version) so the admission
layer can test independence. If required independence cannot be established, the route is
`REQUIRE_HUMAN` or the judgment stays unresolved — Foundry never fakes independence. The
exact independence policy is configurable and remains deferred.

**Humans are authority, not mandatory buttons.** Where an explicit authority record already
settles who owns a decision, Foundry may apply that authority deterministically. Where
authority is genuinely unresolved, escalate. AI cannot invent authority.

**The economics case is strong and comes straight from the measurements.**

91.8% of v1's input overhead was the transmitted output schema. v2 moves classification,
relations, grounding and materiality *out* of the discovery contract, so the discovery
schema shrinks substantially. Later stages send **bounded clusters**, not project state.

The honest counterweight: v2 makes more calls than v1's single pass. Whether total cost
falls is an **empirical question this design does not get to assume** — it is a measured
dimension in §24. What the design does commit to is *semantic capability per token* rather
than schema richness for its own sake.

---

## 21. Failure Modes

| # | Failure | Foundry response |
|---|---|---|
| 1 | AI calls two different issues equivalent | Applied, then correctable: merge retains contributing candidates and the full evidence union, so §19 reverses it. High-risk merges (cross-authority, cross-scope) require a stronger reasoner first. |
| 2 | AI fails to notice equivalent issues | Duplicate persists. Detected later when a third candidate binds to both addresses. Measured as retrieval recall + duplicate-object rate (§24). Accepted and instrumented, not silently assumed away. |
| 3 | AI merges conflicting claims | **Structurally impossible.** Consolidation merges addresses; claims are append-only. Conflict becomes `DISPUTED`. |
| 4 | AI splits one atomic issue unnecessarily | Both units re-enter retrieval; binding to the same address makes them `EQUIVALENT` candidates and they reconsolidate. |
| 5 | AI bundles independent issues | `BUNDLES` → split proposal (§14) with evidence-preservation invariant. |
| 6 | AI cites evidence that does not entail its conclusion | Grounding verdict `NOT_SUPPORTED` / `CONTRADICTED` → refused entry to canonical state, recorded as a rejected judgment. |
| 7 | Two AI judges disagree | **No transition applied.** Both judgments recorded. Escalate per policy. (Law 5.) |
| 8 | New evidence invalidates an earlier relation | Supersede the judgment (§19); recompute affected projections. |
| 9 | Authority changes | New authority event; canonical claim re-derived; superseded claims stay readable. |
| 10 | The semantic identity itself was wrong | Rebinding judgment supersedes the original binding; address descriptors are versioned, so history stays coherent. |
| 11 | Model / provider changes | Addresses are Foundry IDs; judgments carry reasoner provenance; **no durable object depends on a model's vocabulary.** |
| 12 | Retrieval misses the true related object | Degrades to failure #2. Retrieval is explicitly approximate and explicitly measured. |

---

## 22. Deterministic Invariants

Foundry must guarantee all of these regardless of what any reasoner returns:

1. **AI cannot mutate canonical state.** Only an admitted transition changes state.
2. No event, judgment, claim, or issue version is ever rewritten or deleted.
3. **No evidence edge disappears during consolidation.** Merge unions edges; split partitions
   them with union equality enforced.
4. **A conflict cannot silently collapse.** No transition may reduce the number of distinct
   claim values at an address.
5. Authority cannot be invented by a reasoner; only an authority event confers it.
6. Every referenced source event, address, issue, claim and judgment must exist.
7. Every relation target must exist and be live.
8. Version transitions must be legal for the current head; stale-head transitions are refused.
9. Every applied merge and split carries the judgment IDs that authorised it.
10. Every superseded interpretation remains readable with its original inputs and provenance.
11. A rejected judgment can never affect canonical state.
12. **A valid source ID is never proof of grounding.**
13. Provider/model identity is provenance, never write authority.
14. **Given the same prior state and the same admitted judgment, transition application is
    byte-deterministic and replayable.**

Invariant 14 carries the central distinction:

```text
semantic nondeterminism      the reasoner may answer differently on different runs
state-transition determinism given a judgment, application is exact and replayable
```

Foundry cannot make meaning deterministic. It can make *governance* deterministic, and it
can make the ledger reproducible. That is the whole architectural bet.

---

## 23. v2 Falsifiable Hypothesis

### 23.1 [9N LOCK] Single-pass cleanliness is a subsystem gate; the primary validation is longitudinal

The single-pass claim below (preserve recall, reduce redundancy, reduce unsupported output,
preserve grounding/safety) is a **subsystem quality gate**. It is *not* Foundry's final
validation claim. Foundry's primary validation must ultimately be **longitudinal**:

```text
T1  initial evidence               → state created
T2  evidence changes               → state reconciled
T3  conflicting authority arrives  → conflict preserved
T4  authoritative resolution       → interpretation changes
T5  downstream work exists         → blast radius identifies what became stale
T6  another model/agent takes over → state survives without reconstruction
```

That benchmark is not built in 9N. It is the eventual primary validation target.

**Subsystem gate (single-pass, testable first):**

> A persistent AI-semantic + deterministic-governance pipeline can preserve frontier-level
> critical intent coverage while producing a materially cleaner, better-grounded, less
> redundant unresolved semantic state than one-shot frontier analysis on the same evidence.

Operationally, against a raw one-shot baseline on a fresh suite:

```text
PRESERVE   critical_semantic_recall     non-inferior (margin preregistered)
IMPROVE    useful_semantic_precision    strictly better
IMPROVE    redundancy_rate              strictly lower
IMPROVE    unsupported_rate             strictly lower
MAINTAIN   serious_safety_violations    <= baseline
```

**Secondary claim (mechanism):** the improvement is attributable to consolidation. Falsified
if precision improves while the duplicate-object rate does not fall.

**Future lifecycle claim — explicitly NOT yet tested, and not to be asserted:**

> Persistent governed semantic state reconciles evolving evidence more correctly and more
> cheaply than repeated one-shot reconstruction.

9K measured nothing about persistence. This spec does not claim it. §25 designs the
experiment that would.

---

## 24. Future Evaluation Design

Carried forward from the v1 exam: critical and overall semantic recall, useful precision,
redundancy, unsupported rate, bundling, `GapKind` accuracy, serious safety, input tokens,
output tokens, cost, latency.

New measurements the persistent layer requires:

| Dimension | What it measures | Why (v1 evidence) |
|---|---|---|
| duplicate semantic object rate | live issues that should have been one | the core defect |
| semantic relation accuracy | admitted relations vs blind human/judge adjudication | AI is now load-bearing |
| **retrieval recall** | true related pairs actually surfaced | a retrieval miss is an undetectable duplicate |
| conflict preservation rate | conflicts that survive consolidation | must be 100% |
| merge correctness / split correctness | precision and recall of applied transitions | reversibility is not enough |
| grounding verdict accuracy | vs blind adjudication | both v1 safety incidents passed structural checks |
| escalation rate | share of transitions needing a strong model or a human | economics honesty |

Preregistration rules: fresh holdouts, fresh hidden judge commitment, same model where
possible, equivalent visible evidence, blind adjudication, **no reuse of the 9K holdouts for
any victory claim**. The suite must be harder than 9K's — 9K saturated discovery for both
contestants, so a repeat at that difficulty would tie again regardless of architecture.

---

## 25. Smallest Implementable v2 Slice

The first implementation must be independently falsifiable and must not attempt the
persistent-intelligence vision at once.

```text
[frozen v1 discovery, unchanged behaviour]
        │  adapter maps existing output → SemanticIssueCandidate
        ▼
deterministic candidate retrieval          ancestry + lexical, capped at K
        ▼
bounded AI cluster adjudication            binding + relations + split seams
        ▼
deterministic consolidation policy         merge addresses, append claims, preserve conflicts
        ▼
AI classification (late) + gap projection
```

**In slice 1:** in-memory addresses and issues for a single run; the full invariant set;
judgments recorded; conflicts preserved.
**Not in slice 1:** cross-run persistence, event-store integration, supersession machinery,
embedding retrieval, materiality-from-canonical-decisions, human escalation.

Slice 1 can falsify the **primary** claim (recall preserved, redundancy and unsupported rate
down) because those are single-pass metrics. It cannot touch the lifecycle claim.

**The lifecycle experiment (slice 2+, designed here, not built):**

```text
T1 evidence            → build semantic state
T2 evidence changes    → reconcile
T3 conflicting authority arrives → preserve conflict
T4 authoritative resolution     → update interpretation

compare:  Foundry persistent state + bounded AI
against:  a fresh one-shot model reconstructing everything at each T

dimensions: context tokens per step, semantic consistency across T1..T4,
            repeated rediscovery rate, state-update correctness,
            conflict preservation, cumulative cost, latency
```

This is the experiment closest to Foundry's actual thesis, and the one 9K could not run.

---

### 25.1 [9N LOCK] Intent → Decision handoff contract is explicit now

Before the Decision/Architecture Engine exists, the intent side defines exactly what it
will consume. The handoff is **versioned and scoped** and carries, for ONE scope:

```text
project identity · scope identity · semantic-state revision
current admitted semantic addresses (representative view)
current claims · current conflicts/disputes
evidence/provenance references · authority state
supersession information relevant to the scope
stale dependency information (blast radius)
closure/readiness result for the scope
```

It points to durable truth by stable ID rather than duplicating the ledger; context is
bounded. 9N defines and tests this contract and does not implement its consumer.

---

## 26. Non-Goals

Out of scope for v2, per §36 and §30:

```text
Decision/Architecture Engine        general Context Compiler
Intelligence Router                 research fabric
deployment / runtime reconciliation IDE
graph database                      microservices
general ontology / RDF              knowledge-management platform
formal theorem proving              universal entity resolution
multi-agent debate framework
```

Also explicitly out of scope: deterministic semantic normalization, deterministic dedupe,
similarity-threshold merging, and any rule from §4.4.

v2 is bounded to software intent.

---

## 27. Decision Summary

| # | Decision | Resolution |
|---|---|---|
| 1 | Durable semantic primitive | `SemanticAddress` (subject + facet + scope, Foundry-owned opaque ID) with `SemanticClaim` (predicate + value + unit) and `SemanticIssue` versions |
| 2 | What remains ephemeral | `SemanticIssueCandidate` from discovery; retrieval candidate sets; the advisory `gap_hypothesis` |
| 3 | What AI decides | address binding, relations, split seams, grounding, materiality, late classification |
| 4 | What Foundry decides | structure, existence, admissibility, authority, invariants, transition application, versioning, retrieval |
| 5 | When AI is invoked | discovery; cluster adjudication; grounding; materiality; classification — always over bounded inputs |
| 6 | What consolidation is | deterministic application of admitted relations to yield one live issue per address, unioning evidence and appending claims |
| 7 | Duplicate representation | one issue, multiple contributing candidates, multiple evidence edges — represented, never deleted |
| 8 | Conflict representation | multiple claims at one address + admitted `CONFLICTS_WITH` → `DISPUTED`; never merged |
| 9 | Bundle splitting | AI `BUNDLES` + `SplitProposal`; evidence-union equality enforced deterministically |
| 10 | Materiality | AI judgment over an input set that *includes existing decisions, authority and supersession* — the v1 fix is the input, not the judge |
| 11 | Grounding | AI entailment verdict: `SUPPORTED` / `PARTIALLY_SUPPORTED` / `NOT_SUPPORTED` / `CONTRADICTED`, per cited event; `INSUFFICIENT` cut with justification |
| 12 | When `GapKind` is assigned | **after** consolidation, over the consolidated issue; removed from identity entirely |
| 13 | Is Gap durable or projected | **projected**; the durable object is the issue at an address |
| 14 | Provenance through merge/split | `contributing_candidate_ids` + evidence-union/partition invariants + authorising judgment IDs; every merge reversible |
| 15 | Correction model | append + supersede; judgments immutable; affected projections recomputed |
| 16 | Evolution across evidence | new claims bind to existing addresses; issue versions accumulate; conflicts persist until authority settles them |
| 17 | Smallest falsifiable v2 | frozen v1 discovery → retrieval → bounded AI cluster adjudication → deterministic consolidation → late classification → gap projection, in-memory, single run |
| 18 | **[9N LOCK]** Entry point | any project evidence via one ingestion contract; human intent is one source; greenfield and brownfield converge (§1.1) |
| 19 | **[9N LOCK]** Referential identity | deterministic only *after* an admitted binding, only under the current interpretation, never originating meaning (§4.5) |
| 20 | **[9N LOCK]** Address equivalence | non-destructive: both addresses retained, representative view derived, reversible (§7.2.1) |
| 21 | **[9N LOCK]** Admission routing | risk-based `APPLY / REQUIRE_SECOND_LENS / REQUIRE_HUMAN / REJECT`; independence testable via reasoner fingerprint; confidence never authority (§20.1) |
| 22 | **[9N LOCK]** Supersession propagation | generic `DERIVED_FROM` primitive; transitive descendants marked stale in the current view (§19.1) |
| 23 | **[9N LOCK]** Closure | always scoped, never global (§17.1) |
| 24 | **[9N LOCK]** Handoff | explicit, versioned, scoped Intent → Decision contract (§25.1) |
| 25 | **[9N LOCK]** Core-slice relations | `EQUIVALENT`, `DISTINCT`, `CONFLICTS_WITH`; binding and supersession are judgment operations (§9) |
| 26 | **[9N LOCK]** Validation framing | single-pass cleanliness is a subsystem gate; longitudinal T1–T6 is the primary target (§23.1) |

### Deferred decisions

Each names the experiment that resolves it. None is silently pushed into implementation.

| Deferred | Resolved by |
|---|---|
| Candidate cap *K* and the retrieval signal mix | Measure retrieval recall vs cost on the v2 suite; ancestry (2.75× enriched) is the slice-1 default |
| Whether embedding retrieval earns its complexity | Same measurement; slice 1 ships without it |
| Whether late classification improves `GapKind` accuracy | Direct measurement. 9L marked this `UNRESOLVED` and this spec does **not** claim a fix |
| Whether the 11 discovery semantic kinds should shrink | Measure which kinds ever bind to an address; 22.1% of v1 proposals bound to nothing |
| Whether total v2 cost falls below v1 | The v2 experiment. More calls but far smaller schemas — the sign is genuinely unknown |
| Cross-model / cross-provider address stability | The lifecycle experiment (§25), with two different reasoners binding to one address set |

### Open architecture question for the architect

```text
ARCHITECTURE QUESTION: 9L showed a one-shot frontier model matches Foundry's semantic
coverage exactly, including every conflict, authority and staleness trap. This spec
assumes per-cycle discovery remains worth performing and that Foundry's differentiation
lies in governed, persistent interpretation on top of it.

If the architect instead concludes that discovery is commodity, the recommended
architecture does not change - discovery is already treated as a replaceable, disposable
front end - but the v2 experiment's framing does: the primary endpoint would shift from
"cleaner single-pass output" toward the lifecycle experiment in section 25.

Blocked: the choice of which experiment v2 must pass to be considered validated.
```
