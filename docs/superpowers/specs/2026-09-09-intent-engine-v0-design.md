# Foundry Intent Engine v0 — Design Specification

## Status

Approved — 2026-09-09

## Purpose

The Intent Engine is the front door to Foundry's system of truth.

Its job is to convert incomplete, ambiguous, conflicting human goals and external evidence into a canonical, evidence-backed, machine-operable definition of what should become true.

It does not design architecture or write production code. It produces sufficiently closed intent that downstream decision and architecture systems can safely operate.

## Core Boundary

The Intent Engine owns **what must become true and why**.

The downstream Decision / Architecture Engine owns **how the system should make it true**.

Example:

- Intent Engine: `The system must remain available after loss of one region.`
- Architecture Engine: `Use active-active regional cells.`

The Intent Engine must not collapse this boundary by prematurely making implementation choices unless those choices are themselves explicit user intent or externally imposed constraints.

## Architectural Shape

The Intent Engine is not a single long-lived AI agent.

It is an event-driven semantic kernel with persistent external state and stateless capabilities.

Conceptually:

`Event -> Normalize -> Claims -> State Update -> Gap Detection -> Jobs -> Routing -> Evidence/Resolution -> State Update -> Closure Check`

Models are temporary executors. The project state persists independently.

## Architectural Principles

The Intent Engine inherits and must obey `FOUNDRY_CONSTITUTION.md`.

Additional subsystem principles:

1. Research is subordinate to intent and produces evidence only.
2. Every material semantic object has provenance.
3. Authority and confidence are separate fields.
4. Material ambiguity is explicit state, never hidden in prose.
5. Unknowns may remain only if they are known, bounded, and non-blocking.
6. Expensive reasoning is invoked only when deterministic logic or cheaper workers are not trustworthy enough.
7. Worker context is compiled per job and must be bounded.
8. Disagreement among evidence is preserved rather than summarized away.
9. Closure is based on risk and unresolved materiality, not on the absence of all unknowns.
10. Greenfield and brownfield inputs converge into the same canonical intent schema.

## Inputs

The engine may ingest:

- human conversation,
- product briefs,
- requirements documents,
- tickets,
- diagrams,
- screenshots,
- existing codebase evidence,
- tests,
- documentation,
- production telemetry,
- regulations,
- research,
- benchmarks,
- datasets,
- business objectives,
- explicit human decisions.

All input enters as an Event. No input mutates canonical state directly.

## Event Model

Every meaningful incoming change becomes an immutable event.

Initial event types include:

- `USER_STATED_INTENT`
- `DOCUMENT_ADDED`
- `ARTIFACT_CONNECTED`
- `RESEARCH_RESULT_RECEIVED`
- `CLAIM_INFERRED`
- `EVIDENCE_ATTACHED`
- `CONFLICT_DETECTED`
- `AMBIGUITY_DETECTED`
- `UNKNOWN_IDENTIFIED`
- `HUMAN_DECISION_RECORDED`
- `REQUIREMENT_CANONICALIZED`
- `REQUIREMENT_SUPERSEDED`
- `CONSTRAINT_DISCOVERED`
- `ASSUMPTION_IDENTIFIED`
- `RISK_IDENTIFIED`
- `SUCCESS_METRIC_DEFINED`
- `VERIFICATION_OBLIGATION_DEFINED`
- `SEMANTIC_OBJECT_RECORDED`
- `INTENT_CLOSURE_REACHED`
- `INTENT_REOPENED`

Events are append-only.

The current intent state must be reproducible by replaying the ledger through deterministic reducers.

### Semantic reachability invariant

Every semantic object type that may exist in current Intent State must have an approved typed event path.

`SEMANTIC_OBJECT_RECORDED` is the bounded generic path for semantic kinds that do not have a stronger dedicated transition event.

Semantic kinds with dedicated events may not use the generic event. This prevents generic recording from bypassing transition semantics such as requirement canonicalization, claim inference, or metric definition.

## Semantic State

The initial semantic vocabulary is intentionally small.

### Core object types

- `Intent`
- `Goal`
- `Actor`
- `Outcome`
- `Requirement`
- `Constraint`
- `NonGoal`
- `Decision`
- `Preference`
- `Assumption`
- `Claim`
- `Evidence`
- `Unknown`
- `Question`
- `Conflict`
- `Risk`
- `Metric`
- `Contract`
- `VerificationObligation`
- `AuthorityRecord`
- `Amendment`

These are semantic objects, not free-form documents.

### Shared metadata

Material semantic objects should support, where applicable:

- stable ID,
- project ID,
- version / revision,
- status,
- authority,
- confidence,
- provenance,
- source event IDs,
- created timestamp,
- supersession / amendment history,
- relevant scope,
- relations to other semantic objects.

## Authority Model

Authority is independent from confidence.

Initial authority states:

- `OBSERVED`
- `INFERRED`
- `PROPOSED`
- `CANONICAL`
- `DISPUTED`
- `REJECTED`
- `SUPERSEDED`

A brownfield inference can be highly confident and remain `INFERRED`.

A human-authorized requirement may become `CANONICAL` even when the supporting evidence is sparse, because authority answers a different question from confidence.

## Claims and Canonicalization

Events initially produce claims or observations, not immediate truth.

Example:

`User says: Users should be able to log in with Google.`

Possible normalized claim:

`CLAIM-17: Google authentication is required.`

The engine must then determine whether this is:

- a hard requirement,
- a preference,
- a candidate decision,
- a question requiring clarification,
- or a conflict with existing canonical state.

Only the appropriate authorized transition can create canonical intent.

## Gap Detection

After every material state update, the engine evaluates what prevents safe downstream work.

Initial gap classes:

- missing information,
- ambiguity,
- contradiction,
- unsupported assumption,
- missing authority,
- missing success metric,
- missing verification obligation,
- unresolved risk,
- stale evidence,
- insufficient evidence,
- underspecified scope,
- unresolved dependency on another decision.

A gap is a first-class object with materiality, risk, affected scope, and blocking state.

## Job System

The Intent Engine itself should not solve every gap.

A gap can produce one or more bounded jobs.

Initial job classes:

- deterministic extraction,
- semantic classification,
- ambiguity analysis,
- contradiction analysis,
- research planning,
- evidence collection,
- evidence reconciliation,
- requirement refinement,
- metric design,
- verification-obligation design,
- trade-off analysis,
- strong-reasoning resolution,
- human clarification,
- human authorization.

Every job has:

- stable job ID,
- job type,
- target semantic object(s),
- required output schema,
- risk level,
- maximum permitted context,
- permitted executor classes,
- cost / budget envelope,
- verification requirements,
- completion status.

## Context Compiler

No worker chooses its own global context.

Given a job and current semantic state, the Context Compiler produces the minimum sufficient context packet required for trustworthy execution.

A context packet may include:

- the target gap,
- directly relevant canonical intent,
- relevant claims,
- relevant evidence,
- constraints,
- authority rules,
- explicit required output schema,
- bounded artifact excerpts when necessary.

Whole-project context is forbidden by default.

## Intelligence Router

The router chooses the cheapest trustworthy executor class.

Initial executor classes:

1. `DETERMINISTIC`
2. `CHEAP_MODEL`
3. `STANDARD_MODEL`
4. `STRONG_MODEL`
5. `FRONTIER_MODEL`
6. `HUMAN`

Routing inputs include:

- job type,
- semantic risk,
- ambiguity class,
- historical reliability for similar jobs,
- expected cost,
- required confidence,
- availability of executable verification,
- consequence of error.

The router must support explicit escalation after failed or divergent results.

## Research Fabric

Research is triggered only by a recognized knowledge gap.

Flow:

`Knowledge Gap -> Research Plan -> Parallel Research Jobs -> Evidence Objects -> Evidence Reconciliation -> Intent Reasoning`

Research workers return structured evidence rather than essays where possible.

Evidence should preserve:

- claim supported or challenged,
- source,
- source type,
- retrieval time,
- scope,
- confidence,
- freshness,
- excerpts or artifact references,
- contradictions,
- limitations.

Research cannot directly create canonical requirements or decisions.

## Evidence Reconciliation

Conflicting evidence is preserved.

The system must be able to represent:

- multiple claims about the same subject,
- evidence supporting each claim,
- explicit contradiction relations,
- unresolved conflict state,
- final resolution and its authority.

A summarizer must never erase meaningful disagreement merely to create a clean answer.

## Ambiguity Handling

Ambiguity is a first-class semantic defect.

The engine should distinguish at least:

- lexical ambiguity,
- scope ambiguity,
- threshold ambiguity,
- temporal ambiguity,
- priority ambiguity,
- exception ambiguity,
- actor ambiguity,
- authority ambiguity,
- behavioral ambiguity,
- success-criterion ambiguity.

When needed, the engine increases specification precision through progressively more executable forms:

`natural language -> structured requirement -> examples/counterexamples -> decision table -> schema/predicate/state machine -> executable contract`

Precision should increase only as far as necessary.

## Success and Verification Design

Intent is not sufficiently closed if important outcomes cannot be observed or judged.

For each material requirement, the engine should determine whether a metric, contract, or verification obligation is required.

Example:

`Requirement: The system must remain available after loss of one region.`

Possible verification obligation:

`Simulate loss of one region and verify service interruption stays below the authorized threshold.`

The exact verifier belongs downstream, but the obligation to prove the intent belongs here.

## Closure Model

The Intent Engine does not require zero unknowns.

It requires **Sufficient Intent Closure**.

Closure passes when:

- no unresolved blocking ambiguity remains,
- no unresolved material conflict remains,
- no uncontrolled high-risk assumption remains,
- all material requirements have sufficient authority,
- material success criteria are measurable or explicitly exempted,
- required verification obligations exist,
- remaining unknowns are explicitly classified, bounded, assigned authority, and non-blocking.

Closure may be partial by scope. A project can have closed intent for one bounded work package while other areas remain open.

Sufficient Intent Closure is non-vacuous: a scope requires at least one active canonical Intent and at least one active canonical hard obligation (Requirement, Constraint, or Contract).

For closure authority gating, Requirement materiality MEDIUM/HIGH/CRITICAL is material; LOW may remain non-blocking.

Unknown closure behavior uses the explicit Unknown.blocking field; v0 does not infer an unrepresented Unknown risk level.

Closure is recalculated from current semantic state and does not trust a previous closed-scope marker.

## Canonical Intent Package

The output is a versioned semantic package, not a prose PRD.

Conceptual shape:

```text
CanonicalIntentPackage
├── identity
│   ├── project_id
│   ├── intent_version
│   └── lineage
├── purpose
│   ├── mission
│   ├── goals
│   ├── actors
│   └── desired_outcomes
├── boundaries
│   ├── scope
│   └── non_goals
├── obligations
│   ├── requirements
│   ├── constraints
│   ├── invariants
│   └── contracts
├── decisions
│   ├── canonical
│   ├── proposed
│   └── superseded
├── epistemics
│   ├── assumptions
│   ├── claims
│   ├── evidence
│   ├── conflicts
│   └── unknowns
├── quality
│   ├── success_metrics
│   ├── failure_conditions
│   └── verification_obligations
├── governance
│   ├── authority
│   ├── risk
│   └── approval_requirements
└── history
    └── amendments
```

The v0 package is a deterministic projection of object IDs, not a duplicate of semantic content.

- `purpose_ids`: current non-rejected Intent, Goal, Actor, Outcome.
- `boundary_ids`: current non-rejected NonGoal and Preference.
- `obligation_ids`: only ACTIVE + CANONICAL Requirement, Constraint, and Contract.
- `canonical_decision_ids`: current canonical Decisions.
- `proposed_decision_ids`: current Decisions whose authority is OBSERVED, INFERRED, PROPOSED, or DISPUTED.
- `superseded_decision_ids`: Decisions whose lifecycle or authority is SUPERSEDED.
- `epistemic_ids`: current non-rejected Assumption, Claim, Evidence, Unknown, Question, and Conflict.
- `quality_ids`: ACTIVE + CANONICAL Metric and VerificationObligation.
- `governance_ids`: current non-rejected Risk, AuthorityRecord, and Amendment.
- `history_event_ids`: `state.source_events` in event-history order, unsorted.

Package construction always re-evaluates current closure. It must not trust `state.closed_scopes` or a caller-supplied ClosureResult.

## Greenfield Behavior

Greenfield starts mainly from human intent and external evidence.

Flow:

`Human Idea -> Claims -> Gaps -> Research/Clarification -> Canonical Intent -> Architecture`

No implementation artifact is required for intent formation.

## Brownfield Behavior

Brownfield starts from a mix of human objective and existing artifacts.

Existing code, tests, docs, telemetry, and behavior are evidence, not automatic intent.

Flow:

`Existing Artifacts + Human Objective -> Observations -> Inferred Claims -> Conflicts/Unknowns -> Human/Reasoned Canonicalization -> Canonical Intent`

Once canonicalized, brownfield and greenfield produce the same Intent State and Canonical Intent Package.

## Storage Boundaries

v0 should use simple storage while preserving logical boundaries.

Recommended initial design:

- append-only event ledger,
- relational semantic state,
- object/file storage for large artifacts,
- derived relation/graph projection as an index,
- no graph database requirement,
- no model-specific persistent memory.

Storage technology is replaceable; semantic contracts are not.

## API Boundary

The Intent Engine should expose operations conceptually equivalent to:

- ingest event,
- read current intent state,
- list blocking gaps,
- create/inspect jobs,
- attach evidence,
- record human clarification,
- record human authorization,
- evaluate closure,
- emit canonical intent package,
- compute intent delta between versions,
- replay state from event history.

Exact transport and framework choices are intentionally deferred.

## Failure Handling

The engine must explicitly represent failure rather than silently compensate.

Examples:

- worker returns invalid schema -> job failure,
- workers disagree materially -> divergence gap,
- research sources conflict -> conflict object,
- stale evidence detected -> evidence freshness gap,
- context packet insufficient -> context failure and bounded recompile,
- repeated cheap-worker failure -> router escalation,
- no executor can resolve safely -> human escalation,
- closure check fails -> affected scope remains open.

## Evaluation Strategy

The first Foundry milestone is not code generation.

It is to prove that the Intent Engine can systematically identify material intent gaps and produce a more trustworthy machine-operable intent representation than a one-shot frontier-model PRD.

Initial evaluation dimensions:

- critical gaps detected,
- critical gaps missed,
- false gaps invented,
- ambiguities detected,
- conflicts detected,
- unsupported assumptions exposed,
- evidence quality,
- provenance completeness,
- success metrics defined,
- verification obligations defined,
- unnecessary human questions,
- expensive-model invocations,
- total token cost,
- wall-clock time,
- reproducibility from event replay.

- Evaluation inputs use the same typed EventEnvelope contract as production ingestion.
- Gap correctness requires exact (GapKind, fingerprint) identity.
- Duplicate gap fingerprints are invalid evaluation data rather than silently deduplicated.
- Cost and usage counters are non-negative.
- input.json and judge.json are separate by architecture and loader API.
- v0 sealing is not an OS-level security boundary; stronger executor/process isolation is deferred until execution workers exist.

This v0 seal is an architectural/API boundary, not an OS security boundary. A malicious process with arbitrary repository filesystem access could still open `judge.json`. Process/filesystem isolation belongs to the later executor harness.

## Initial Fixture Families

Two fixture families must exist from the beginning.

### Greenfield fixtures

Messy human idea -> expected semantic intent obligations and hidden gaps.

### Brownfield fixtures

Human objective + existing artifacts -> expected inferred claims, conflicts, unknowns, and canonicalization requirements.

Both must converge into the same semantic schema.

## v0 Non-Goals

Intent Engine v0 will not:

- generate production code,
- choose full system architecture,
- deploy infrastructure,
- operate production systems,
- train ML models,
- build a graphical IDE,
- require a graph database,
- implement microservices,
- maintain one persistent super-agent,
- attempt to formalize every requirement.

These are downstream concerns or premature complexity.

## First Falsifiable Bet

**Claim:** A persistent, evidence-backed Intent Engine with bounded workers can discover and control materially important ambiguity, missing decisions, constraints, assumptions, and verification obligations more reliably than a one-shot frontier model, while using frontier intelligence only for the subset of problems that require it.

The bet should be evaluated on sealed fixtures with predefined hidden expectations and exact cost metering.

Failure is informative. If the structured engine does not materially outperform the simpler baseline, Foundry should not add downstream factory complexity until the reason is understood.

## Next Design Layer

After this specification is approved, implementation planning should begin with only the minimum v0 foundation:

1. semantic types,
2. event ledger,
3. deterministic reducer,
4. current Intent State,
5. gap representation,
6. job representation,
7. sealed evaluation harness.

AI ingestion, research, routing, and advanced context compilation should be added only after the deterministic substrate is tested.
