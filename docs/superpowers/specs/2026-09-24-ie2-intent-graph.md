# IE2 — Intent Graph specification

Base: `0ce8f9831b4f236139f14a77d1db91d30e8e3f01`. Incorporates rulings R1–R22.

## 0. What IE2 is, and is not

IE2 adds **no new universal first-class semantic type** (R1). The audit established that all
21 `SemanticKind`s already exist; six of them (`GOAL`, `ACTOR`, `OUTCOME`, `NON_GOAL`,
`PREFERENCE`, `QUESTION`) are shapes without semantics, appearing in no rule outside
`package.py`'s id buckets.

IE2 is therefore **activation, separation and invariant work**: giving existing types the
rules they were declared to have, and separating two things the delivery contract currently
conflates.

An inert type is worse than an absent one. It appears in the handoff, reads like a
guarantee, and is enforced by nothing — which is exactly the state `NonGoal` is in today.

## 1. Classification of every kind

Three roles, and the role determines which invariants apply.

### Normative — asserts desired state, may bind delivery

| kind | force |
|---|---|
| `INTENT` | root purpose; the thing everything else must serve |
| `GOAL` | desired direction under the Intent |
| `OUTCOME` | desired result; what achieving a Goal looks like |
| `REQUIREMENT` | required obligation |
| `CONSTRAINT` | hard boundary on the solution space |
| `NON_GOAL` | explicit exclusion |
| `PREFERENCE` | tradeable inclination |
| `DECISION` | authoritative recorded choice among alternatives (§6) |

Per R5 there is **no cross-cutting negotiability field**. The type carries the strength.
`Preference` is tradeable because it is a Preference; `Constraint` is not because it is a
Constraint. States such as "non-negotiable Preference" or "tradeable Constraint" are
unrepresentable by construction, which is the point. Authorized change is expressed through
governance, supersession or a `Decision` — never by weakening a type's meaning.

### Epistemic — describes what is known, never what is wanted

`CLAIM`, `EVIDENCE`, `ASSUMPTION`, `UNKNOWN`, `CONFLICT`, `RISK`.

The normative/epistemic boundary is the load-bearing separation from the brief's §5. An
Evidence may support a Claim; a Claim may be the *basis* of a Requirement; neither ever
becomes normative by accumulation. "I think PostgreSQL would be nice" is a Claim or a
Preference and cannot cross into Constraint without an authority act.

### Context and measurement — neither asserts desire nor describes truth

`ACTOR` (semantic context, kept per R8, outside generalized synthesis), `METRIC`,
`VERIFICATION_OBLIGATION`, `AUTHORITY_RECORD`, `AMENDMENT`, `QUESTION` (deprecated, §7),
`CONTRACT` (legacy, §7).

## 2. Basis and relevance are separate axes (R2)

The foundational Intent law of IE2:

```
BASIS      DERIVED_FROM   why is this true / authoritative?
RELEVANCE  SERVES         why is this in this project?
```

A Requirement does **not** need to derive from Intent. It needs a trustworthy basis **and** a
traceable relevance path:

```
regulatory evidence → Claim → DERIVED_FROM → Constraint → SERVES → Intent
```

Collapsing these into one edge forces a fabricated human derivation for obligations the
world imposes. That is the failure this split exists to prevent, and it is stated as an
enforceable prohibition in §4 (`I-SEP-1`).

## 3. Relation legality matrix

`Relation` carries only `relation_type` and `target_id` — **it has no source kind**.
Legality is therefore a property of a *pair resolved against state*, and can only be checked
where both endpoints are known. It is a projection/admission-time check, never a parse-time
one (see §13).

`N` = any normative kind. Direction is written source → target.

| relation | legal source | legal target | transitive | staleness propagation | conflict effect | readiness effect |
|---|---|---|---|---|---|---|
| `DERIVED_FROM` | N | `CLAIM`, `EVIDENCE`, `CONSTRAINT`, `GOAL`, `OUTCOME`, `REQUIREMENT`, `DECISION` | yes — the basis chain | **yes**: parent superseded ⇒ descendants stale | none | absent basis blocks CANONICAL |
| `SERVES` | N except `INTENT` | `GOAL`, `OUTCOME`, `INTENT` | yes — the relevance path | no | none | absent path blocks CANONICAL |
| `EXCLUDES` | `NON_GOAL` | `GOAL`, `OUTCOME`, `REQUIREMENT`, `CONSTRAINT` | no | no | **yes** — canonical vs canonical is a conflict | blocks |
| `CONSTRAINS` | `CONSTRAINT` | `REQUIREMENT`, `GOAL`, `OUTCOME`, `INTENT` | no | yes — review on supersession | none | none directly |
| `CONFLICTS_WITH` | N | N | no | no | **yes** | blocks when material |
| `SUPERSEDES` | any | same kind | no | **yes** — drives blast radius | none | superseded must not be delivery-active |
| `MEASURED_BY` | `REQUIREMENT`, `OUTCOME` | `METRIC` | no | no | none | `requires_metric` unmet blocks |
| `VERIFIED_BY` | `REQUIREMENT`, `CONTRACT` | `VERIFICATION_OBLIGATION` | no | no | none | `requires_verification` unmet blocks |
| `SUPPORTS` | `EVIDENCE` | `CLAIM` | no | no | none | none |
| `CHALLENGES` | `EVIDENCE` | `CLAIM` | no | no | contributes to `CONFLICT` | none |
| `AFFECTS` | `PREFERENCE`, `ASSUMPTION` | N | no | `ASSUMPTION` only, from IE2.3 | none | none |

`REQUIRES` and `RELATES_TO` remain in the serialized enum for compatibility but are **not
used by IE2** and gain no legality. Per R3, `SATISFIES`, `DEPENDS_ON`, `INVALIDATES` and
`QUALIFIES` are not added: the first two are architecture concerns, and the last two are
already covered by `SUPERSEDES` plus derivation staleness, and by `AFFECTS`.

`SERVES` is transitive by design — a Requirement serving an Outcome that serves a Goal that
serves the Intent satisfies relevance without restating the whole chain on every object.

## 3a. The forward-only admission seam (R17)

A law that only tests invoke is not a law. `validate_relations()` must sit on a production
write path. The repository was searched for one, and the honest finding is:

**There is no general governed write path for intent-bearing semantic objects today.**

| production writer | event | carries relations? |
|---|---|---|
| `application/intent_synthesis.py` | `INTENT_OBJECT_SYNTHESIZED` | yes — **frozen, certified** |
| `SemanticGovernor.record_authority()` | `SEMANTIC_OBJECT_RECORDED` | `AuthorityRecord` only |
| `SemanticGovernor.submit()` → `route_judgment()` | `SEMANTIC_ADMISSION_DECIDED` | **no** — `route_judgment` takes a `SemanticJudgment` (claims, addresses, evidence), never a `SemanticObject` |

So the existing admission gate cannot host this: it never sees a Requirement's or NonGoal's
relations. And the one path that does is the certified Slice-1 vertical, which is frozen.

**Smallest seam: `SemanticGovernor.record_intent_object()`** — a new governed write in
`application/semantic_governance.py` (not frozen):

```
NEW WRITE     record_intent_object(obj, *, author, human_actor_id=None)
              → reject kinds outside INTENT_BEARING_SEMANTIC_KINDS
              → authorship law (§3d)                     human vs non-human, authority
              → reject obj.id already in state.objects   admission is creation (§3e)
              → validate_relations(state, obj)           legality, per §3 / §3f
              → append ONE event: INTENT_OBJECT_ADMITTED
                   { object, author, derivation_parent_ids }   §3c

REPLAY        parse_event / reducer / replay
              → NO legality validation, NO target resolution, ever
```

**The API is narrowed, not general.** Its laws were designed for normative intent objects, so
`Claim`, `Evidence`, `AuthorityRecord` and the rest are refused deterministically. The
accepted set is **imported** from the frozen `domain/intent_synthesis.py`
(`INTENT_BEARING_SEMANTIC_KINDS`, the ten intent-bearing kinds with `ACTOR` deliberately
absent) rather than restated. Importing does not modify the frozen module, and it makes drift
impossible by construction — a duplicated set would silently diverge the first time either
moved. A test pins the seam's accepted set to that constant.

## 3c. One atomic durable transition (R23)

**The defect, confirmed from the store.** `EventStore` exposes exactly
`append(event, expected_sequence)` — no batch, no transaction. The Postgres adapter opens
`self._engine.begin()` *inside* `append`, so **every append is its own committed
transaction**. A seam that wrote the object and then looped `derive()` per relation would
perform N+1 independent durable transitions, and a crash or concurrent failure between them
would leave a committed object carrying `DERIVED_FROM` relations with no `DerivationEdge`
recorded — exactly the split `I-DERIV-1` forbids. A single method call is not a transaction.

**The rule.** For every object admitted through the seam, the object and all traversal edges
its basis implies are **one atomic durable transition**. Either both are reconstructable from
the ledger or neither is.

**The representation: one composite event.**

```
INTENT_OBJECT_ADMITTED
    payload: IntentObjectAdmissionPayload
        object                : SemanticObject
        author                : ReasonerFingerprint
        derivation_parent_ids : tuple[str, ...]
```

`author` is durable because an admission event must preserve **who authored what it
admitted**; reconstructing that from surrounding events would make authorship inferential at
exactly the point it must be certain.

The reducer reconstructs the object **and** its `DerivationEdge`s from this single event.
Partial durability becomes unrepresentable: there is no intermediate state, because there is
no second append.

**Why a new event type rather than extending `SemanticObjectPayload`.** The additive option
was evaluated and rejected on evidence. `SEMANTIC_OBJECT_RECORDED` shares one reducer case
with roughly a dozen event types, and it **appears in both certified ledgers** (one
`AuthorityRecord` each). Extending its payload would add a field to events inside frozen
certification evidence and would change the semantics of an event type whose meaning is
merely "a semantic object was recorded" — derivation is not part of that meaning. A new type
cannot appear in any historical stream, so historical replay is provably untouched, the
shared reducer case is not modified, and the event says what it means.

**Why `derivation_parent_ids` is carried explicitly rather than re-derived from the object's
own `DERIVED_FROM` relations.** Deriving them in the reducer is tempting — it would make
`I-DERIV-1` true by construction rather than by check. It is rejected for a stronger reason:
**replay determinism must not depend on rules that can change.** If the reducer computed edges
from whichever relations currently imply derivation, then any future change to that mapping
would silently alter how existing events replay, and the ledger would stop meaning one fixed
thing. Carrying the ids as immutable data in the event fixes the outcome forever.

The two-sources-of-truth concern is therefore resolved at the **write** boundary, not by
dropping the field: the seam validates that `derivation_parent_ids` equals the object's
`DERIVED_FROM` targets before appending, so one authoring act produces one event in which the
fact appears once as data and once as relation, checked equal at birth and immutable
thereafter.

- `I-DERIV-1` (restated) — in any `INTENT_OBJECT_ADMITTED` event, `derivation_parent_ids` equals the set of the object's `DERIVED_FROM` targets; the reducer reconstructs exactly those edges.
- `I-DERIV-2` — no other write path may record a `DerivationEdge` for an object admitted through the seam.

**Historical compatibility.** Existing events remain valid exactly as they are. Certified
Slice-1 history recorded `INTENT_OBJECT_SYNTHESIZED` with a `DERIVED_FROM` relation and **no**
`DerivationEdge`, and nothing may retroactively require one: there is no replay-time
validation, no backfill, and no change to any existing payload or reducer case. The atomicity
rule applies only to new admission-seam events.

**Coverage.** This seam covers every *new* non-synthesis intent-object write: human-authored
`NonGoal`, `Preference`, `Constraint`, `Goal`, `Outcome`, `ProjectDecision`, and whatever the
future clarification and research paths record. It is also the seam multi-type synthesis will
call when it arrives, so IE2.1 builds the gate that later slices route through rather than
leaving it unattached.

**What it does not cover, stated plainly.** The certified Slice-1 synthesis path is **not**
routed through it in IE2.1, because that file is frozen. That is safe and checkable rather
than merely asserted: Slice 1 emits exactly one relation shape, `Requirement ──DERIVED_FROM──▶
Claim`, which is legal under §3 by construction. IE2.1 pins this with a test asserting every
relation the certified path can emit is legality-clean, so the frozen path cannot drift out of
compliance unnoticed. Routing synthesis through the seam is a reviewed compatibility change
belonging to the multi-type synthesis slice, not to IE2.1.

**Why not the reducer.** Historical objects predate these laws and may carry relations the
matrix now calls illegal. Validating during reconstruction would make the event log
unreplayable and break the property MR4–MR6 certified. Enforcement is forward-only, and a
mutation control plus a legacy-ledger replay proof keep it that way.

## 3b. Source of truth for overlapping representations (R20)

Four places where two records could claim the same fact. The ruling is adopted, and the audit
confirmed one divergence **already exists**.

| pair | authoritative | IE2.1 position |
|---|---|---|
| `Evidence.supported_claim_ids` vs `SUPPORTS` | the **field** | `SUPPORTS` not newly activated; legality listed for completeness only |
| `Evidence.challenged_claim_ids` vs `CHALLENGES` | the **field** | `CHALLENGES` not newly activated |
| durable supersession/retirement vs `SUPERSEDES` relation | the **durable records** | the relation never drives lifecycle; it is traceability only |
| `DerivationEdge` vs `DERIVED_FROM` relation | **both, by role** | see below |

**The derivation pair needs a rule, and implementation corrected what that rule rests on.**
An earlier draft of this section stated that the certified synthesis path writes the
`DERIVED_FROM` relation and no edge at all. That is **false**, and IE2.1 found it: the
reducer creates a `DerivationEdge` from `INTENT_OBJECT_SYNTHESIZED`'s `basis_claim_ids` as
part of "one indivisible application". So the composite-event pattern R23 arrived at is not
a new invention — it is the pattern the certified path has used all along, which is the best
available evidence that it is the right one.

Two things genuinely do differ, and the rule must account for them. `SemanticGovernor.derive()`
writes edges too, and in production is called only from experiments. More importantly the two
paths use **different parent id spaces**: Slice-1 edges point at the claim's
`created_by_judgment_id`, while the IE2 seam points at the `DERIVED_FROM` target itself.
Slice-1 can do this because its basis is always a claim asserted by a judgment; the generic
seam cannot, because its basis may be a `Goal`, `Constraint` or `ProjectDecision` that has no
judgment at all. This is noted rather than unified: IE2.3's blast-radius traversal will have
to handle both, and forcing one id space now would mean rewriting certified history.

Roles, fixed here:

- **`DERIVED_FROM` relation** — object-local traceability. Lives on the object, travels with it, answers "what is this object's basis" without a graph walk.
- **`DerivationEdge`** — the traversal structure for synthesis staleness. Answers "what is downstream of this judgment". *Superseded for IE2.3 by R65:* assumption blast radius walks object-local `DERIVED_FROM` instead, because the two parent-id conventions above make edges writer-dependent.

Consistency rule for the new seam: `record_intent_object()` appends **exactly one**
`INTENT_OBJECT_ADMITTED` event, whose `derivation_parent_ids` are computed from the object's
own `DERIVED_FROM` targets at write time. The reducer reconstructs the object and exactly the
`DerivationEdge`s those ids name, from that single event.

**`record_intent_object()` emits no `DERIVATION_RECORDED` event.** Two events could split
under crash or concurrency (§3c); one cannot. `SemanticGovernor.derive()` and every
historical `DERIVATION_RECORDED` event remain untouched and fully supported for their
existing uses — the composite event is the rule for the new seam only, not a replacement for
the derivation event elsewhere.

An invariant pins it:

- `I-DERIV-1` — for every object admitted through the seam, the `derivation_parent_ids` in its `INTENT_OBJECT_ADMITTED` event equal the set of its `DERIVED_FROM` targets, and replay reconstructs exactly those `DerivationEdge`s — no more, no fewer.

`I-DERIV-1` is **forward-only**. IE2.1 does **not** retro-fill edges for historical objects,
including certified Slice-1 Requirements, because backfilling would rewrite history to satisfy
a law those events predate. The gap is documented rather than papered over; if IE2.3 needs
blast radius across Slice-1 Requirements, closing it is an explicit, reviewed migration.

## 3d. Authorship is explicit; provenance is not authorship (R24)

The earlier `I-PROV-1` was unenforceable at this seam, and the reason is worth recording:
it was written over `SynthesisOrigin`, which lives on synthesis proposals and **does not
exist on `SemanticObject`**. The seam could never have checked it.

The fix is not to add `SynthesisOrigin` to `SemanticObject` — that would push a synthesis
concept into the generic model. Nor may authorship be inferred from `Provenance`: basis
provenance records *where a fact came from*, authorship records *who asserted it*, and
collapsing them is precisely the laundering the existing C9/I22 law forbids. Human-authored
basis does not make a model-written statement human-authored.

Foundry already has the durable identity primitive: **`ReasonerFingerprint`**, where a human
is `provider="human"` with `model` carrying the actor id. The seam therefore takes the author
explicitly:

```python
record_intent_object(obj, *, author: ReasonerFingerprint, human_actor_id: str | None = None)
```

Forward-write law, mirroring the existing `_require_actor` rule on `submit()`:

- `I-AUTH-1` — `author.is_human` ⇒ `human_actor_id` is present and equals `author.model`.
- `I-AUTH-2` — a non-human author ⇒ `human_actor_id` is `None`.
- `I-AUTH-3` — a `CANONICAL` object requires a **human** author, a matching authenticated actor, and a covering `AuthorityRecord` for the target scope.
- `I-AUTH-4` — a non-human author proposing `CANONICAL` is **rejected before append**. No event is written.
- `I-AUTH-5` — `Provenance` never substitutes for `author`; an object whose provenance is `HUMAN` but whose author is non-human is still non-human-authored.

Human-versus-non-human is sufficient for the generic admission boundary. `SynthesisOrigin`
stays in the synthesis subsystem, where its four-way distinction has meaning.

**The authenticated `human_actor_id` need not become semantic provenance.** It is an
admission-time credential, and the durable record already holds the identity: for a human,
`author.model` *is* the actor id, so the fingerprint stored in the event preserves who acted
without copying the credential into the object's provenance.

## 3e. Admission is creation, never silent overwrite (R26)

The event is `INTENT_OBJECT_ADMITTED`, so it admits something new.

- `I-ADMIT-1` — the seam rejects `obj.id` already present in `state.objects`, before append.
- `I-ADMIT-2` — the new reducer case **fails closed** if a malformed event admits an id that already exists, rather than replacing the entry.

The reducer's shared case for existing event types assigns `objects[id] = obj`, which for a
new admission would be a silent overwrite — revision by dictionary assignment. Revision and
supersession are explicit lifecycle operations with their own records; they must never happen
by accident. This applies to the new event type only and never retroactively validates
historical events.

## 3f. Target resolution spans both semantic planes (R25)

`validate_relations` must not assume targets live in `state.objects`. The repository has two
planes, and the certified path already crosses them:

| id namespace | holds | resolves to |
|---|---|---|
| `state.objects` | legacy `SemanticObject` | the object's own `SemanticKind` |
| `state.semantic.claims` | v2 `SemanticClaim` | `CLAIM` |
| `state.semantic.evidence` | v2 `EvidenceItem` | `EVIDENCE` |

**Verified against the certified ledger:** replaying Grok's Case A gives a Requirement whose
`DERIVED_FROM` target is `CLAIM-3d861b7bb2cd0eef`, which is in `state.semantic.claims` and
**not** in `state.objects`. A validator resolving only `state.objects` would reject the
certified path outright. One deterministic helper resolves an id to a kind across the
permitted namespaces:

- `I-RES-1` — an id resolving in no permitted namespace is **rejected as unresolved**, never ignored.
- `I-RES-2` — an id resolving in more than one permitted namespace is **rejected as ambiguous**. The repository proves no global cross-plane id uniqueness — the `CLAIM-`/`REQ-` prefixes are conventions, not constraints — so ambiguity is representable and must fail closed rather than pick a namespace.

Resolution is part of forward-only legality checking. **Replay never re-resolves targets**, so
a later change to the namespace set cannot alter how historical events reconstruct.

The certified-path compliance test must use the **real v2 `SemanticClaim` in
`state.semantic.claims`**. Manufacturing a legacy `SemanticObject` Claim to make the validator
pass would prove only that the test can be satisfied, not that the certified path is legal.

## 4. Invariants

Written so each becomes one deterministic test.

**Basis**
- `I-BASIS-1` — every CANONICAL normative object except `INTENT` has ≥1 `DERIVED_FROM` edge to a *current* object of a legal basis kind.
- `I-BASIS-2` — every basis chain terminates in `CLAIM` or `EVIDENCE`, or in a `CONSTRAINT` whose provenance is external and which carries an `AUTHORITY_RECORD`.
- `I-BASIS-3` — an `ASSUMPTION` may never appear as the terminal basis of a CANONICAL object. Assumptions qualify (`AFFECTS`); they do not ground.

**Relevance**
- `I-REL-1` — every CANONICAL normative object except `INTENT` has a `SERVES` path terminating at the project's canonical root `INTENT`.
- `I-REL-2` — a `SERVES` path may not leave the object's scope.

**Separation (the enforceable form of R2)**
- `I-SEP-1` — `DERIVED_FROM` may never target `INTENT`. Relevance is never expressed as basis.
- `I-SEP-2` — no normative object may have an epistemic object as its *only* `SERVES` target.

**Exclusion**
- `I-EXCL-1` — a CANONICAL `NON_GOAL` that `EXCLUDES` a CANONICAL normative object is an unresolved conflict and blocks readiness.
- `I-EXCL-2` — exclusion is scoped; a `NON_GOAL` constrains only within its own scope.

**Enforcement boundary (R22).** IE2.1 enforces **explicit `EXCLUDES` edges only**. It does
not, and must not be described as, inferring semantic contradiction from statement text — no
deterministic rule can read "must support card refunds" and "we will not build billing" and
decide they collide. What IE2.1 guarantees is narrow and real: once an exclusion is recorded
as an edge, a canonical object on the other end blocks readiness and cannot pass silently.

Recognising that a *new proposal* falls inside an existing NonGoal is a synthesis-stage
obligation: future multi-type synthesis must be given current NonGoals in its request and must
either refuse the proposal or emit the `EXCLUDES`/`CONFLICTS_WITH` relation. Until that slice
exists, an unrecorded contradiction is undetected, and this spec claims nothing more.

**Strength**
- `I-STR-1` — a `PREFERENCE` never appears in `obligation_ids`.
- `I-STR-2` — a `PREFERENCE` may not be promoted to `CONSTRAINT` or `REQUIREMENT` by revision; that transition requires a new object with its own authority.

**Authorship and authority (R24 — replaces the former `I-PROV-1`)**

See §3d for `I-AUTH-1`…`I-AUTH-5`. The invariant is stated over *authorship and authority*,
not provenance, because the earlier provenance-shaped wording named a field the generic model
does not have and conflated where a fact came from with who asserted it.

**Stated plainly: IE2.1 cannot prove that no model-preferred technology entered the graph.**
It proves that nothing non-human-authored reached canonical authority without a human author,
a matching authenticated actor and a covering `AuthorityRecord`. Refusing unwarranted
technology *proposals* is a synthesis-stage concern — prompt, schema and deterministic
scorers, as in the certified Slice-1 exam — and belongs to the multi-type synthesis slice, not
to a domain invariant. Recognising a technology in arbitrary prose would need a classifier or
keyword matching, and neither belongs in deterministic domain law.

## 5. ConstraintFacet (R6)

`Constraint` stays one type. The facet exists to answer exactly one machine-checkable
question — **who may relax this?** — because that is the only distinction that changes
system behaviour. Facets that would merely describe a constraint's topic are rejected as
decoration.

| facet | what can legitimately change it | basis requirement |
|---|---|---|
| `EXTERNAL_MANDATE` | nothing inside the project; only the external mandating authority | external provenance + `AUTHORITY_RECORD` |
| `PROJECT_BOUNDARY` | an authorized project human, through a governed authority act | human provenance |
| `EVIDENCE_BOUND` | a change in its basis; never a preference or a decision | `CLAIM`/`EVIDENCE` basis |

Each name states the *relaxation behaviour*, not the topic. The earlier draft used
`REGULATORY`/`ORGANIZATIONAL`/`TECHNICAL`; `TECHNICAL` was a topic label covering constraints
with entirely different relaxation rules — a platform limit that dies when re-measured and a
vendor contract that no engineer may waive would both have landed in it. That is how a junk
drawer starts, so the axis is now behaviour throughout.

Justification for each, and for every rejected candidate:

- **EXTERNAL_MANDATE** — a waiver by any project actor is invalid, so the system must refuse one. Covers law, regulation, standards bodies and external contractual obligation: all share one rule, that relaxation authority lies outside the project.
- **PROJECT_BOUNDARY** — the project imposed it and an authorized human may lift it. Budget, resource, timeline and policy limits fold in here: identical relaxation authority, so separate values would encode topics rather than rules.
- **EVIDENCE_BOUND** — cannot be waived by preference, decision or authority, but *does* die when its basis changes. Distinct lifecycle from both of the above, which is what earns it a value.
- **`TECHNICAL` — rejected** (see above): a topic, not a behaviour.
- **`SCOPE_BOUNDARY` — rejected.** A scope boundary is an exclusion, and `NON_GOAL` with `EXCLUDES` already models it. Admitting it here would recreate the junk drawer immediately.
- **`INVARIANT` — rejected.** A system invariant is an architecture property, not intent.

This classification is **Constraint-specific by construction**. It is not a generic
negotiability abstraction (R5 stands): no other kind carries it, and it grades *what can
change a hard boundary*, never *how strongly* anything is wanted.

The facet is **optional with default `None`** for replay compatibility (§13). It is required
only at canonicalization of new constraints.

**What is proved where (R30).** The "basis requirement" column above is the *target* state,
and IE2.1 does not reach it. IE2.1 records the facet, requires one on a newly canonicalized
Constraint, and enforces the single structurally decidable rule available without a basis
chain: `EXTERNAL_MANDATE` may not carry `SourceKind.HUMAN` provenance.

It deliberately does **not** claim that non-`HUMAN` provenance is external — `SYSTEM`,
`CODE`, `TEST` and `RUNTIME` are not external authorities, and treating them as such would
invent a provenance ontology to make a weak check read as a strong one. Verifying the
covering `AuthorityRecord` for `EXTERNAL_MANDATE` and the `Claim`/`Evidence` basis for
`EVIDENCE_BOUND` both need the basis chain, and are **carried forward to IE2.2** alongside
`I-BASIS-1`…`I-BASIS-3`.

## 6. ProjectDecision semantics (R9)

`SemanticKind.DECISION` is retained in serialized vocabulary. Its meaning is narrowed to:

> **An authoritative recorded choice among identified alternatives, with rationale.**

It is not `SemanticJudgment`, not `IntentSynthesisDecision`, not a governance routing
decision. Those three already exist and are governance machinery; this one is project or
product content.

The load-bearing rule: **a ProjectDecision does not automatically become an obligation.**
"We chose PostgreSQL" does not by itself constrain anything.

`CONSTRAINS` stays owned by `CONSTRAINT`. A Decision never constrains, because a Decision is
a choice and constraining is what an obligation does — letting a Decision emit `CONSTRAINS`
would hand it Constraint semantics through the back door, which is exactly the confusion the
narrowed definition exists to prevent. Consequence is expressed by a **separate consequence
object naming the Decision as basis**:

```
Constraint / Requirement / Preference  ──DERIVED_FROM──▶  ProjectDecision
```

`DECISION` is therefore a legal `DERIVED_FROM` target — an *intermediate* basis, never a
terminal one. `I-BASIS-2` still requires the chain to continue past it to a `CLAIM`/`EVIDENCE`
root or an authority-backed external Constraint, and the Decision itself must satisfy
`I-BASIS-1` and `I-REL-1` like any other normative object. A decision may also `SUPERSEDES` a
prior decision.

- `I-DEC-1` — a CANONICAL `DECISION` with no outgoing consequence relation is *inert*; it is reported, and in IE2.5 it may block when a downstream fork depends on it.
- `I-DEC-2` — a `DECISION` may not appear in `obligation_ids`. It is already delivered separately as `canonical_decision_ids`.

**Naming without breaking history.** The `kind` literal is what serializes, so the Python
class may be renamed freely. Recommendation: rename the class to `ProjectDecision`, keep
`Decision = ProjectDecision` as a deprecated module-level alias so existing imports and the
`SemanticObject` union continue to work, and keep `kind: Literal[SemanticKind.DECISION]`
untouched. Zero serialization impact.

## 7. Compatibility — Question and Contract

**Question (R7).** Long-term, `Unknown` is the durable epistemic state and a question is a
*clarification action* generated to resolve one. IE2 does **not** build rich Question
semantics and does **not** remove the kind. It stays parseable, replayable and untouched in
history; it is marked deprecated in documentation, gains no new rules, and is produced by no
new code path. When the Clarification subsystem arrives it owns questions as actions, and the
durable kind can then be retired by a separate migration.

**Contract (R10).** Kept exactly as-is for compatibility: it remains in `obligation_ids` and
keeps its `NON_CANONICAL_OBLIGATION` closure behaviour and `VERIFIED_BY` relation. IE2
neither expands synthesis around it nor removes it. The target direction is that
`Requirement` + `Metric` + `VerificationObligation` compose into a derived acceptance
contract downstream, and that an external legal obligation is represented as a
`Requirement`/`Constraint` with the appropriate basis and provenance. No removal in IE2.1.

## 8. boundary_ids compatibility (R4)

**Additive compatibility is feasible, with no contradictory contracts.** The decisive fact:
`CanonicalIntentPackage` is *derived* from state on every call and is **never persisted in
the event log**, so changing it carries **zero replay risk**.

Target:

```
exclusion_ids   → NonGoal        (hard exclusions; must never be reintroduced)
preference_ids  → Preference     (tradeable)
obligation_ids  → Requirement | Constraint | Contract, CANONICAL only   (unchanged)
boundary_ids    → DEPRECATED, retained as exactly sorted(exclusion_ids + preference_ids)
```

Because the deprecated field remains the exact union, no consumer can observe a
contradiction between old and new fields, and both existing assertions
(`test_package.py:107` expecting `("NG-A", "PREF-A")`, and `test_intent_synthesis_replay.py:922`
expecting `()`) continue to pass unchanged. A new test pins `boundary_ids ==
sorted(exclusion_ids + preference_ids)` so the compatibility field cannot silently drift from
the authoritative ones.

`handoff_v2` embeds the package as `contract`, so it inherits the new fields without a
`HANDOFF_V2_VERSION` bump — the version string identifies the envelope, which is unchanged in
shape. **This is the one delivery-contract change in IE2.1 and requires explicit approval.**

## 9. Boundary against downstream domains

The Intent Graph holds *what, why, boundaries, success conditions*. It does not hold service
decomposition, schemas, framework choices, infrastructure topology, class design or
implementation plans — **unless** a human or external authority makes one of those an
explicit `Constraint`, `Decision` or `Preference`. IE2.1 enforces only the authority half
of that (`I-AUTH-3`: nothing non-human-authored reaches CANONICAL unauthorised); refusing
an unwarranted technology *proposal* is a synthesis-stage rule, not a domain invariant
(§4).

Per R13, IE2 adds no brownfield-specific types and asserts nothing permanent about how Actual
Software Reality must be modelled; descriptive `CODE`/`TEST`/`RUNTIME` claims are sufficient
evidence into Intent for now, and a richer reality graph may live outside this kernel later.

Per R14, `Hypothesis`, `ExperimentalVariable`, `Baseline` and `Dataset` are **not** added. A
discovery objective is expressible today as `Intent` + `Goal` + desired `Outcome` + `Metric`
as success condition + `Unknown` for what is undetermined + `Assumption` for what the
experiment presumes. Experiment Lab adds its own semantics downstream.

## 10. Future hooks

**Clarification/research (IE2.4).** `GapKind` answers *what is wrong*; a separate resolution
route will answer *how it should be closed* — conceptually `DERIVE`, `RESEARCH`, `ASK_HUMAN`,
`RECONCILE`, `PRESERVE/WAIT`. It is an orthogonal axis, not more `GapKind` values. Research
workers return evidence and claims with provenance; they never create canonical intent, which
`I-BASIS-1` and the existing governance path already enforce.

**Readiness (IE2.5).** The hooks IE2.1 must leave in place: exclusion conflicts as a blocker
source, preference identifiable as never-blocking, assumption blast radius queryable, and
inert decisions reportable. Full closure design is deferred.

## 11. Frozen

The certified Intent Synthesis vertical does not change: `adapters/intent_synthesis/model_runtime.py`,
`adapters/model_runtime/{xai,openai}.py`, `ports/intent_synthesizer.py`,
`application/intent_synthesis.py`, `application/intent_synthesis_context.py`,
`domain/intent_synthesis.py`, all of `model_runtime/`, `tests/certification/`, and both
certification records. Slice 1 produces only `REQUIREMENT`; IE2 works additively around that
path, never through it.


## 12. IE2.3 — assumption blast radius (as built, R63–R69)

`domain/assumption_impact.py`, a pure projection:

```
blast radius(A) = { X : A ─AFFECTS→ X }                      direct
                ∪ { Y : Y ─DERIVED_FROM→⁺ X, X direct }       transitive, reverse, object-local
```

- `direct_assumption_impacts`, `assumption_blast_radius` (historical: walks through dead
  intermediates) and `actionable_assumption_blast_radius` (filtered by `object_is_current`);
  ids only, sorted, deduplicated, project-local. Unknown id → `UnknownAssumptionError`;
  non-Assumption → `NotAnAssumptionError`; dangling targets ignored; iterative with a visited
  set, so historical cycles terminate.
- Only `AFFECTS` seeds; only `DERIVED_FROM` propagates. Object-local relations cover certified
  Slice-1 Requirements (they carry `DERIVED_FROM → Claim`) with no edge migration.
- **Not propagated, by decision:** `SERVES` (R64 — relevance, several lawful paths may exist;
  *future reconciliation note:* a scoped relevance consequence may ask whether impacted nodes
  remove an object's final lawful `SERVES` path), `EXCLUDES` (R69 — a closure rule, not
  dependency), and every other relation. The §3 matrix column for `SUPERSEDES`/`CONSTRAINS`
  concerns supersession staleness, not assumption impact.
- **No invalidation state (R68).** Nothing durable says "this assumption is now false";
  `UNSUPPORTED_ASSUMPTION` gaps, gap status, `risk_level` and lifecycle are not that. A later
  trigger (IE2.4/reconciliation) decides when an Assumption needs action and consumes this
  radius. IE2.3 mutates nothing and creates no gap; `UNCONTROLLED_HIGH_RISK_ASSUMPTION` is
  unchanged.
- **Recorded limitation, unrelated to IE2.3:** a new root Intent `DERIVED_FROM` a Decision
  cannot bootstrap that Decision's relevance through the single-object seam; that needs a
  future multi-object/atomic graph-construction operation.
