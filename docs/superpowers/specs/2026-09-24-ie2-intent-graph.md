# IE2 — Intent Graph specification

Base: `0ce8f9831b4f236139f14a77d1db91d30e8e3f01`. Incorporates rulings R1–R15.

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
| `DERIVED_FROM` | N | `CLAIM`, `EVIDENCE`, `CONSTRAINT`, `GOAL`, `OUTCOME`, `REQUIREMENT` | yes — the basis chain | **yes**: parent superseded ⇒ descendants stale | none | absent basis blocks CANONICAL |
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

**Strength**
- `I-STR-1` — a `PREFERENCE` never appears in `obligation_ids`.
- `I-STR-2` — a `PREFERENCE` may not be promoted to `CONSTRAINT` or `REQUIREMENT` by revision; that transition requires a new object with its own authority.

**Provenance**
- `I-PROV-1` — a normative object naming an implementation technology requires human or external provenance; model-proposed technology choices are refused (R6).

## 5. ConstraintFacet (R6)

`Constraint` stays one type. The facet exists to answer exactly one machine-checkable
question — **who may relax this?** — because that is the only distinction that changes
system behaviour. Facets that would merely describe a constraint's topic are rejected as
decoration.

| facet | who may relax | basis requirement |
|---|---|---|
| `REGULATORY` | nobody inside the project | external provenance + `AUTHORITY_RECORD` |
| `ORGANIZATIONAL` | the project's human authority | human provenance |
| `TECHNICAL` | nobody by decision; only new evidence may invalidate it | `CLAIM`/`EVIDENCE` basis |

Justification for each, and for every rejected candidate:

- **REGULATORY** — a waiver by a project actor is invalid, so the system must refuse one. Distinct behaviour, earns a value.
- **ORGANIZATIONAL** — waivable by the sponsor. Budget and resource limits fold in here: identical relaxation authority, so a separate `RESOURCE` value would encode a topic, not a rule.
- **TECHNICAL** — cannot be waived by preference or authority, but *can* die when evidence changes. Different lifecycle from both of the above, so it earns a value.
- **`SCOPE_BOUNDARY` — rejected.** A scope boundary is an exclusion, and `NON_GOAL` already models it with `EXCLUDES`. Admitting it as a Constraint facet would recreate the junk drawer immediately.
- **`INVARIANT` — rejected.** A system invariant is an architecture property, not intent. It belongs downstream (§9).
- **`BUSINESS` vs `CONTRACTUAL` — rejected.** Both reduce to organizational or regulatory by relaxation authority; splitting them adds topics without adding rules.

The facet is **optional with default `None`** for replay compatibility (§13). It is required
only at canonicalization of new constraints.

## 6. ProjectDecision semantics (R9)

`SemanticKind.DECISION` is retained in serialized vocabulary. Its meaning is narrowed to:

> **An authoritative recorded choice among identified alternatives, with rationale.**

It is not `SemanticJudgment`, not `IntentSynthesisDecision`, not a governance routing
decision. Those three already exist and are governance machinery; this one is project or
product content.

The load-bearing rule: **a ProjectDecision does not automatically become an obligation.**
"We chose PostgreSQL" does not by itself constrain anything. Its consequence must be
explicit — the Decision `CONSTRAINS` an object, or `SUPERSEDES` a prior Decision, or a
resulting `Constraint`/`Requirement`/`Preference` records it as basis via `DERIVED_FROM`.

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
explicit `Constraint`, `Decision` or `Preference`, which `I-PROV-1` enforces by refusing
model-proposed technology.

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
