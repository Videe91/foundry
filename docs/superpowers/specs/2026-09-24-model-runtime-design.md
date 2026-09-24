# Foundry Model Runtime — design

**Status:** MR1 implemented. Root shared primitive at `src/foundry/model_runtime/`.

## 1. Purpose

The Model Runtime is **Foundry's universal socket to models**. It is a root primitive, a
peer of `domain`, `application`, `ports` and `adapters`, because every Foundry domain
will eventually use it: Intent, Research, Architecture, Planning, Evaluation, Coding and
Testing workers, Operations.

It exists so that changing which model does a job is a registry decision rather than a
code change in the domain that needed the job done.

## 2. The split

| The **domain** decides | The **runtime** decides |
|---|---|
| what reasoning or work is required | which certified model may execute it |
| what bounded context is supplied | which provider adapter to call |
| what output schema is legal | how to invoke it |
| what policy and prompt apply | how to normalize runtime metadata |
| what authority the result may have | how to enforce the request's execution constraints |

**The runtime never decides domain meaning.** Intent owns Intent policy; Research owns
Research policy; Architecture owns Architecture policy. No domain prompt lives here, and
a structural test asserts the package cannot import Intent's modules or contain its
instruction text.

## 3. WORKER and REASONER — a Foundry law

Exactly two operational tiers.

**WORKER** — the builders and executors: coding, editing files, writing tests, repository
inspection, bounded research execution, extraction, transformation, classification,
mechanical analysis. A worker receives a bounded task contract. It does **not** own
architecture, planning, final evaluation, gap resolution or high-level intent decisions.
On discovering a design conflict it reports the blockage upward; it does not silently
redesign the system.

**REASONER** — the brains: intent synthesis, research planning, architecture, planning,
evaluation, adversarial critique, trade-off analysis, gap analysis and gap-closing
proposals, complex diagnosis.

Every task pins exactly one legal tier in `REQUIRED_TIER_BY_TASK`. A request whose
declared tier disagrees with its task is a **structural refusal** — never promoted,
never demoted. Auto-correcting would hide a caller bug behind a plausible execution, and
the two tiers carry different authority over the work they perform.

**Tier is a role certification, not a brand assumption.** Nothing hardcodes "Claude is a
reasoner" or "small model is a worker". A model may legitimately hold both tiers when
Foundry has certified it for both, and the same descriptor may then execute an
`ARCHITECTURE` request and a `CODING` request.

## 4. Certification is task-specific

Being registered is not permission to perform every task. Eligibility is a conjunction:

```
requested tier ∈ descriptor.tiers
AND task ∈ descriptor.certified_tasks
AND required_capabilities ⊆ descriptor.capabilities
```

A model that supports the tier but was never certified for the task is ineligible, and so
is one certified for the task that lacks a declared capability. Being able to generate
text says nothing about being authorised to do architecture.

## 5. Routing — a deterministic seam, honestly labelled

Zero eligible candidates raises `ModelUnavailableError`; otherwise the first candidate in
registry order is selected. Registry order is lexical by `(provider, model)`.

That ordering is **reproducibility, not a quality ranking**. MR1 has no certified pricing
or benchmark data, and a "cheapest" rule invented without it would be a guess wearing the
costume of Law 4. The correct statement of MR1's determinism is:

- selection and routing are deterministic under MR1 policy;
- provider compute is not deterministic in general;
- domain durability remains entirely outside the runtime.

### Cheapest-trustworthy boundary

The constitution's `deterministic → cheap worker → stronger worker → frontier reasoning →
human` ordering is **not** implemented in MR1. What MR1 establishes is its prerequisite:
tier, capabilities, task certification, a registry, a routing seam, and usage/cost
metadata. Later policy can optimise for cost, latency, quality or risk by replacing
`select_model` — without any domain caller changing.

## 6. Provider isolation

`ports.py` defines `ModelProvider` and imports no SDK, no transport and no vendor type. An
adapter turns the neutral contract into whatever its provider speaks and turns the
response back into the caller's own output type. Nothing provider-shaped travels upward:
the public result carries a normalized `ModelUsage` and a `ModelResultMetadata`, and no
vendor object escapes.

The runtime verifies the identity that came back. A provider that reports a different
provider or model than the one selected raises `ModelProtocolError` — it may not silently
substitute a model, and MR1 resolves no aliases.

## 7. Error taxonomy

Five distinguishable failures, deliberately not collapsed, because each has a different
fix:

| error | meaning | fix |
|---|---|---|
| `ModelRequestError` | caller request or runtime configuration is invalid | caller / config |
| `ModelUnavailableError` | nothing certified for this task, tier and capabilities | a certification decision |
| `ModelProviderUnavailableError` | certified model selected, its adapter is not installed | a deployment change |
| `ModelProviderError` | the adapter failed executing; cause preserved | retry or incident |
| `ModelProtocolError` | wrong identity returned, or output failed the caller's type | provider or schema bug |

## 8. Generation cannot certify itself (Law 5)

Runtime success means exactly: **the provider call completed, and the transport, identity
and output contracts held.** It does not mean the domain answer is correct. Nothing in the
result is named `verified`, `correct`, `accepted` or `certified`, and a structural test
enforces that. Evaluation and verification remain separate concerns.

## 9. Model compute is not durable truth (Law 3)

The runtime touches no ledger and retains nothing between calls — no conversation state,
no project history, no prior output as memory, no provider thread ids. It holds immutable
registry configuration and adapter instances, and adapters may hold transport clients.
Every call receives its full bounded request. A runtime that remembered would quietly
become the project's memory, which is exactly what Law 3 forbids.

The result is compute. The calling domain decides what, if anything, becomes durable.

## 10. Reasoning Orchestrator boundary

MR1 owns **single-call execution and provider-neutral routing foundations** only.

```
Domain Reasoner → Reasoning Orchestrator → Model Runtime → Provider adapters
```

The future Reasoning Orchestrator will own subagents, delegation, primary-plus-critic,
parallel models, independent lenses, escalation, maximum delegation depth and reasoning
budgets. None of that is in MR1, and the runtime must not grow into an agent framework.

`ModelTraceContext.parent_call_id` exists **only** as trace structure so that future
delegation is traceable. MR1 never reads it to decide anything and never spawns a child
call from it. A model must not be able to cause provider-to-provider calls by describing
one: delegation is authorised by Foundry, executed by the runtime, and never controlled
by the model itself.

## 11. BYOK boundary

MR1 implements no credential management. `ModelRequest`, `ModelDescriptor` and the result
types carry no API keys, and a structural test asserts no public contract has a
credential-shaped field and no module mentions one. Provider adapters will receive
credentials out of band in MR2+, which keeps Foundry-managed keys, tenant BYOK and
per-tenant provider credentials all possible later without changing these contracts.

## 12. Existing provider integrations are untouched

`adapters/intelligence/xai.py`, `adapters/intelligence/xai_baseline.py` and
`adapters/semantics/xai_reasoner.py` are historical working code with frozen prompts,
pasted hashes, policy versions and sealed experiment artifacts. MR1 does not migrate,
move or edit them. MR2 introduces an xAI `ModelProvider` adapter and must prove
behavioural equivalence before anything migrates.

## 13. Future slices

- **MR2** — real provider adapter(s) behind `ModelProvider`; behavioural-equivalence proof against the existing xAI adapters.
- **MR3** — a `ModelRuntime`-backed `IntentSynthesizer`, replacing nothing until proven.
- **MR4** — live Intent exam against a real model.
- **Later** — Reasoning Orchestrator, cost/quality routing policy, BYOK, retry and fallback.

Numbering may be adjusted after MR1 review.
