# Foundry Agent Rules

This file is binding on every AI coding agent working in this repository.

**Code is an implementation artifact. Intent, decisions, constraints, evidence, authority, contracts, invariants, and verification obligations are the durable system asset.**

Do not treat generated code, prompts, model weights, schemas, infrastructure, configuration, or deployment manifests as the canonical intellectual asset of Foundry. Foundry preserves decisions and manufactures artifacts. Implementation may change. The laws, contracts, and approved specifications do not change to make coding easier.

---

## Purpose

You are here to implement approved work exactly, verify it, and stop when the work is done or when an architectural question is unresolvable from the approved sources.

You are not here to invent Foundry's architecture, reinterpret the goal, expand the milestone, or silently “improve” the system into a more convenient shape.

---

## Source documents and precedence

Read these before writing code. They outrank this file where this file is silent, and they outrank agent convenience everywhere.

| Rank | Document | Role |
|------|----------|------|
| 1 | `FOUNDRY_CONSTITUTION.md` | Durable laws. Outranks all implementation convenience. |
| 2 | `docs/superpowers/specs/2026-09-09-intent-engine-v0-design.md` | Approved Intent Engine design. Outranks the implementation plan if they conflict. |
| 3 | `docs/superpowers/plans/2026-09-09-intent-engine-v0-foundation.md` | Bounded v0 implementation plan. Execute it; do not enlarge it. |

If the constitution, spec, and plan disagree:

1. The constitution wins against convenience and against any implementation that would violate a law.
2. The approved design spec wins against the implementation plan.
3. The implementation plan wins against local coding preference.

If an approved source does not decide something architecturally material, **stop**. Do not fill the gap. Report it for architect review.

Do not modify `FOUNDRY_CONSTITUTION.md`, the design spec, or the implementation plan unless a later approved task explicitly requires it.

---

## Architecture is not yours to invent

Architecture decisions are not yours to invent.

- If the approved constitution, spec, or plan does not decide something architecturally material, stop implementation of that decision and report it for architect review.
- Never silently change Foundry's architecture to make implementation easier.
- `FOUNDRY_CONSTITUTION.md` outranks all implementation convenience.
- A reasonable-looking choice that nobody upstream decided is a defect, not a contribution.
- No `TODO` placeholders for architectural decisions. An undecided architecture question is a stop, not a comment.

When a task reveals an architectural ambiguity, report exactly:

```text
ARCHITECTURE QUESTION: <question>
```

Then explain the options and consequences. Do not decide it silently.

---

## Current milestone

The current approved milestone is **Intent Engine v0**: the deterministic substrate that can represent semantic intent, record immutable events, replay current state, represent gaps and jobs, evaluate closure, and score sealed evaluation fixtures.

Intent Engine v0 does not generate downstream production application/system code. This repository milestone does implement the production-quality deterministic Intent Engine substrate itself.

v0 does **not** choose full system architecture, ingest with models, compile advanced worker context, route executors, run research workers, deploy infrastructure, operate production systems, train ML models, or build a graphical IDE.

Do not add functionality that belongs to later milestones. Do not begin a later plan's work because it seems adjacent or obviously next.

Python v0 must remain a **modular monolith**.

Do not introduce microservices, Kubernetes, a graph database, a persistent super-agent, or model-provider coupling unless explicitly approved later.

---

## One bounded task at a time

Implement exactly one bounded task at a time.

- Work from the approved implementation plan's current task.
- Do not start the next task until the current task is finished, verified, and committed as specified.
- Do not expand the task's declared file list to sneak in later work.
- If the task cannot be completed truthfully without an unapproved architectural decision, stop and report an architecture question.

---

## Strict test-driven development

Use strict test-driven development on every implementation task:

1. Write the behavioral test first.
2. Run it and confirm it fails for the intended reason (missing type, missing module, missing behavior — not a broken test).
3. Write the minimum implementation required to pass.
4. Re-run the relevant tests.
5. Run the full available verification suite.

Never weaken, delete, or rewrite a valid test merely to make implementation pass.

If a test is wrong because the approved spec or plan is more precise than the test, fix the test to match the approved source and say so. If the test encodes an approved invariant, the implementation must change.

---

## Verification before “done”

After every task, run:

- the tests for that task, and
- the full available verification suite.

Once the Python toolchain exists, the standard suite is:

```bash
uv run pytest -v
uv run ruff check .
uv run mypy src
```

If a check is not yet available because an earlier bootstrap task has not created it, say that. Do not pretend a missing suite passed.

Do not claim a task is finished without the completion report below.

---

## Durable-state laws you must not violate

These are operational restatements of the constitution and Intent Engine spec. They are not optional style.

### Intended state is above artifacts

No artifact is canonical merely because it exists. Foundry reconciles **Intended State** (what is authorized to be true) with **Actual State** (what currently exists or occurs). Existing code, tests, documentation, runtime behavior, model outputs, research, and human statements may all provide evidence. Evidence can support or challenge intent; existence does not automatically create authority.

The Intent Engine owns **what must become true and why**. Downstream architecture owns **how**. Do not collapse that boundary by encoding implementation choices as intent unless they are explicit user intent or externally imposed constraints.

Creation and operation are the same reconciliation loop. Do not split development and operations into unrelated control systems.

### Models are compute, not project memory

No model is the canonical memory of a project. Persistent state must live outside models. Models receive a job, return structured results, and may disappear.

Context supplied to workers must be bounded and task-specific. Whole-project context is forbidden by default. Context is rent: pay only for the minimum sufficient context required by the current job.

Do not introduce a long-lived coordinator that rereads project history as its memory. Do not store project truth in prompts, chat logs, or provider-specific memory features.

### Events are the only mutation path

All material input enters canonical state through typed events.

No external input may mutate canonical intent directly. Human conversation, documents, code, tests, telemetry, research, and model output are evidence or claims until an authorized event transition makes them canonical.

The event history is append-only. There is no update or delete API for event rows.

Current Intent State must be reproducible from event replay through deterministic reducers. If state cannot be reconstructed from the ledger, the implementation is wrong.

### Authority, confidence, and provenance

Authority and confidence must remain separate.

- **confidence** is how strongly evidence supports a belief.
- **authority** is whether that belief is allowed to define intended state.
- **provenance** is where it came from.

A highly confident inference is still an inference until authorized. Provenance is mandatory for material semantic knowledge. Do not create material semantic objects without it.

### Research and evidence

Research creates evidence, never canonical truth directly.

Required flow:

```text
Research -> Evidence -> Reasoning -> Authorization -> Canonical State
```

Preserve disagreement, scope, freshness, uncertainty, and contradiction. Do not collapse conflicting sources into a convenient summary.

### Explicit defects, not smoothed prose

Ambiguity, contradiction, unknowns, conflicts, and risk must remain explicit rather than being summarized away.

- Ambiguity is a first-class defect.
- Material unknowns cannot disappear silently.
- A known, bounded, non-blocking uncertainty may travel with the system.
- An uncontrolled material unknown must block affected downstream work.
- Closure is based on risk and unresolved materiality, not on the absence of all unknowns.

### Generation cannot certify itself

Generation cannot be its own sole verifier.

The process that creates a proposal or artifact cannot be the sole authority for its correctness. Verification is a separate concern. A generated artifact is accepted because its obligations are satisfied, not because the generator claims success.

### One semantic kernel

Greenfield and brownfield must converge into the same semantic kernel.

Existing code, tests, documentation, and runtime behavior are evidence, not automatic intent. Domain adapters may understand specialized mechanics, but they must not create a second source of truth.

Meaningful artifacts must remain explainable: why they exist, what intent requires them, what evidence supports them, what verifies them, who authorized them, and whether actual behavior currently diverges from intended behavior.

---

## Approved v0 shape

Until a later approved design says otherwise, implement inside this shape:

- Python 3.12 modular monolith.
- Domain models are immutable, strongly typed objects.
- All state changes enter through typed append-only events.
- A pure reducer materializes `IntentState`.
- PostgreSQL persists event streams.
- Closure and package generation are deterministic projections.
- The evaluation harness is isolated from execution inputs so future workers cannot see hidden expectations.

Approved layer boundaries from the v0 plan:

| Layer | May do | Must not do |
|-------|--------|-------------|
| `domain/` | Pure immutable models and deterministic rules | Database, network, model-provider, or CLI imports |
| `application/` | Orchestration over domain objects | Provider-specific code |
| `ports/` | Protocols that adapters implement | Persistence or provider details |
| `adapters/postgres/` | Persistence only | Domain policy or model calls |
| `evaluation/` | Sealed-fixture loading and scoring | Mutating Intent State; exposing judge data to executors |

Storage technology is replaceable. Semantic contracts are not. Do not add a graph database, extra service topology, or any store the current task does not specify. The v0 plan persists append-only event streams in PostgreSQL.

---

## Model and provider isolation

Keep all model/provider integrations behind abstractions.

Foundry must not depend on Grok, OpenAI, Anthropic, Google, or any single provider.

v0 has no model-provider integration. Do not add one. When a later approved task adds executors, they must sit behind ports. Provider SDKs, API keys, and vendor payload shapes must not leak into `domain/` or `application/`.

---

## Engineering constraints

- Prefer simple deterministic code over clever abstractions.
- Do not over-engineer for hypothetical scale.
- All new public domain structures must be strongly typed.
- No hidden mutable global state.
- No free-form dictionaries standing in for approved domain types once those types exist.
- Do not accept arbitrary dictionaries as validated event payloads.
- Do not invent public types, event kinds, gap kinds, job types, or executor classes beyond the approved sources.
- Use the cheapest trustworthy mechanism: deterministic code first, models only when a later approved task requires them.

---

## v0 non-goals — do not build these

Do not implement, scaffold, or “leave room for”:

- production code generation
- full system architecture selection
- infrastructure deployment / Kubernetes
- production operations control planes
- ML training
- a graphical IDE
- a graph database
- microservices
- a persistent super-agent
- model-driven ingestion, research fabric, intelligence routing, or advanced context compilation
- formalizing every requirement
- coupling the kernel to a single model provider

These are downstream concerns or premature complexity.

---

## Completion report

Before saying a task is finished, report:

1. files changed
2. tests added
3. commands run
4. exact test results
5. any assumptions
6. any architecture questions
7. commit SHA

If you did not run a check, say you did not run it. If a test failed, paste the failure. A false success corrupts every decision downstream.

---

## Architecture questions

Stop and report rather than guess when any of the following is true:

- the constitution, spec, and plan do not decide an architecturally material point
- implementing the task requires a new public domain concept, event type, storage model, or service boundary not in the approved sources
- the spec and plan appear to conflict and the conflict is architecturally material
- a test, type, or API would need to encode a policy nobody upstream decided

Format:

```text
ARCHITECTURE QUESTION: <question>

Options:
- <option A> — <consequence>
- <option B> — <consequence>

Blocked work:
- <what cannot proceed until this is decided>
```

Do not pick an option to keep momentum. Invalidating upward is success. Quietly deciding is failure.
