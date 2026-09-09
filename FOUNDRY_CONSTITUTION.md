# Foundry Constitution

Foundry is an autonomous computational-systems factory.

Its purpose is to convert intent into verified running systems and continuously keep actual systems aligned with their intended state.

This constitution defines the laws that every Foundry subsystem must obey. Implementation may change. These laws are the durable architectural constraints.

## Founding Thesis

**Implementation artifacts are replaceable. Decisions are durable.**

Code is not the canonical intellectual asset of a computational system. Neither are model weights, prompts, schemas, infrastructure definitions, configuration, datasets, or deployment manifests.

The durable asset is the evidence-backed system of intent, decisions, constraints, contracts, invariants, rationale, authority, and verification obligations that determines what the system must become and remain.

Foundry therefore preserves decisions and manufactures artifacts.

## Law 1 — Intended State Is Above Artifacts

No artifact is canonical merely because it exists.

Existing code, tests, documentation, runtime behavior, model outputs, research, and human statements may all provide evidence. Evidence can support or challenge intent, but existence does not automatically create authority.

A production behavior can be real and still be wrong.

## Law 2 — Foundry Reconciles Intended and Actual State

Foundry continuously reasons about the difference between:

- **Intended State** — what is authorized to be true.
- **Actual State** — what currently exists or occurs.

Conceptually:

`Delta = Actual State - Intended State`

Every Foundry operation must help explain, reduce, verify, or explicitly authorize this delta.

This law applies to greenfield creation, brownfield modernization, feature development, migrations, incidents, security remediation, infrastructure operations, ML training, model drift, AI-agent optimization, and autonomous maintenance.

## Law 3 — Intelligence Is Compute, Not Memory

No model is the canonical memory of a project.

Persistent state lives outside models. Models receive bounded, compiled context for a specific job, perform a transformation, return structured results, and may then disappear.

The system must not depend on one long-lived coordinator repeatedly rereading project history.

**Context is rent. Pay only for the minimum sufficient context required by the current job.**

## Law 4 — Use the Cheapest Trustworthy Executor

Foundry routes work to the cheapest mechanism that can reliably satisfy the required confidence, risk, and verification level.

Preferred order:

1. deterministic computation,
2. cheap model worker,
3. stronger model worker,
4. frontier reasoning,
5. human authority.

Expensive intelligence is reserved for high-value ambiguity, difficult reasoning, novel architecture, conflicting constraints, and exceptional diagnosis.

Project size alone must not force use of a stronger brain.

## Law 5 — Generation Cannot Certify Itself

The process that creates a proposal or artifact cannot be its sole authority for correctness.

Generation and verification are separate concerns.

Verification may use tests, contracts, invariants, exact assertions, formal checks, simulations, benchmarks, evaluation suites, security controls, runtime observation, or human approval.

A generated artifact is accepted because its obligations are satisfied, not because the generator claims success.

## Law 6 — Ambiguity Is a First-Class Defect

The existence of a written rule does not imply that the rule is sufficiently precise for reliable execution.

Foundry must detect materially ambiguous intent and progressively increase specification precision only as far as required.

Possible representations include:

- natural language,
- structured requirements,
- examples and counterexamples,
- decision tables,
- schemas,
- predicates,
- state machines,
- executable contracts.

Foundry must distinguish a missing decision from an ambiguous decision and from a decision that exceeds a worker's reasoning capability.

## Law 7 — Authority and Confidence Are Independent

Every material belief must distinguish:

- **confidence** — how strongly the evidence supports it,
- **authority** — whether it is allowed to define intended state,
- **provenance** — where it came from.

A highly confident inference from code is still an inference unless it has been authorized as canonical intent.

## Law 8 — Research Produces Evidence, Not Truth

Research cannot directly mutate canonical intent.

The required flow is:

`Research -> Evidence -> Reasoning -> Authorization -> Canonical State`

Foundry must preserve provenance, disagreement, scope, freshness, and uncertainty rather than collapsing conflicting sources into a convenient summary.

## Law 9 — Material Unknowns Cannot Disappear Silently

Foundry does not need perfect knowledge before work can proceed.

It does require that every material unknown be resolved or explicitly controlled.

A known, bounded, non-blocking uncertainty may travel with the system. An uncontrolled material unknown must block the affected downstream work.

## Law 10 — Every Meaningful Change Is Traceable

Foundry maintains an append-only history of material events, claims, evidence, decisions, amendments, verification outcomes, and promotions.

The current state must be reconstructable from history.

The system must be able to answer not only what is true now, but how and why it became true.

## Law 11 — Reality Must Remain Explainable

For every meaningful artifact or behavior, Foundry should be able to answer:

- Why does this exist?
- What intent or decision requires it?
- What evidence supports that decision?
- What verifies it?
- What depends on it?
- What would be affected if it changed?
- Who or what authorized it?
- How has it changed over time?
- Does actual behavior currently diverge from intended behavior?

An unexplained meaningful artifact is technical debt in Foundry's worldview.

## Law 12 — One Kernel, Many Domains

Foundry uses one universal lifecycle and semantic core across software, infrastructure, data systems, machine learning, AI agents, models, prompts, and future computational artifacts.

Domain-specific adapters may understand specialized mechanics, but they must not create separate sources of truth.

Greenfield and brownfield systems are different initial conditions of the same architecture, not different products.

## Law 13 — No Single Brain Must Understand the Whole System

Foundry scales by decomposition, persistent state, and compiled context rather than by requiring one model to hold an ever-growing project in context.

Global understanding belongs to the system representation, not to a single model invocation.

## Law 14 — Foundry Must Be Able to Build and Operate the Same System

Creation and operation are the same reconciliation loop at different points in a system's lifecycle.

Before deployment, Foundry closes the gap between intent and missing artifacts.

After deployment, Foundry closes the gap between intended behavior and observed reality.

The architecture must not split development and operations into unrelated control systems.

## Law 15 — The Constitution Outranks Implementation Convenience

If a proposed implementation violates these laws for convenience, the implementation must change.

If experiments falsify one of these laws, the law must be amended explicitly, with evidence and rationale preserved in history.

Nothing is sacred except what survives evidence.
