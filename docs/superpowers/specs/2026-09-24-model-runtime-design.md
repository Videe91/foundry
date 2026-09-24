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

## 12a. MR2 — the xAI provider boundary (accepted)

The first real provider lives at `src/foundry/adapters/model_runtime/xai.py`, in the
adapter layer. `foundry/model_runtime` remains provider-neutral and still imports no SDK;
a vendor module inside it would make every domain that touches the runtime depend
transitively on that vendor.

`XAIModelProvider` is **not** pinned to a model. The registry decides which model is
certified for a task and the adapter executes what it is handed — hardcoding a model here
would move a certification decision into transport code.

**Transport laws, preserved from Foundry's accepted xAI integrations:** one Foundry call
is one provider attempt (`grpc.enable_retries = 0`); every call is stateless
(`store_messages=False`, no conversation id, no previous response id); no tools, no
search, no multi-agent; structured output through the SDK's own `chat.parse(shape)`, never
hand-repaired JSON; real telemetry only. This is **transport** equivalence — MR2 carries
no historical Intent or Semantic prompt, so no claim of domain-behaviour equivalence is
made, and none is testable until a domain actually migrates.

**Provider-reported identity.** `xai-sdk 1.19.0` exposes no `Response.model` property, but
the underlying `GetChatCompletionResponse` proto carries a `model` field, read via
`response.proto.model`. That is what the adapter reports. `Response.request_settings` was
deliberately *not* used: it echoes the request, which would make the runtime's identity
check vacuous because a substitution would agree with itself. A response reporting no
model is refused rather than assumed.

**Constraint enforcement — honoured or refused, never ignored.** `timeout_seconds` is
client-level in this SDK, so a client is constructed per call and the request's timeout
actually applies instead of being silently widened. `max_output_tokens` maps to the
supported `max_tokens`. `max_cost_usd` is **refused before the network**: MR2 has no
trusted pre-call cost engine, and pretending a budget was enforced would be worse than
declining it.

**Telemetry honesty and a wire-format limitation.** `prompt_tokens` and
`completion_tokens` have **no proto presence** — plain proto3 scalars defaulting to `0`,
so "unreported" and "reported zero" are indistinguishable on the wire. A successful
completion never consumes zero prompt tokens, so the adapter reads `0` there as unknown
rather than injecting a false measurement into every budget built on this metadata.
`cost_in_usd_ticks` *does* carry presence, so a genuine zero cost survives intact, and
`cost_usd_from_usage` already returns `None` when the server reported nothing.

**Transport faults keep their own meaning.** A `grpc.RpcError` during structured-output
parsing propagates rather than being converted, so the runtime maps it to
`ModelProviderError`. MR2's first live call surfaced the alternative: a transient
transport fault reported as "output could not be parsed" sends an operator hunting a
schema bug while the network is the real problem.

**Not certified for Intent.** MR2 proves Grok 4.7 can execute correctly through the
universal socket. It does not prove Grok is trustworthy for Intent Synthesis. Task
certification comes from task-specific evaluation in MR3/MR4; the live smoke's registry
certifies only the single task that transport proof needs.

## 12b. MR3 — the Intent Synthesis adapter (accepted)

`src/foundry/adapters/intent_synthesis/model_runtime.py` connects the certified Intent
port to the runtime. Three layers, three concerns: `foundry/model_runtime` is universal
plumbing, `foundry/adapters/model_runtime` is provider transport that knows nothing of
Intent, and `foundry/adapters/intent_synthesis` owns the Intent prompt and model-facing
schema. The Intent Engine itself was not modified.

**Authorship is bound to one configured `ModelIdentity`,** because T8 reads the
fingerprint before the call and writes it as durable authorship. A runtime execution
returning a different identity raises `ModelProtocolError` and yields no result.

**Consequence, stated rather than buried:** dynamic fallback or model-switching *within a
single synthesis invocation* is **not legal** under the current `IntentSynthesizer`
authorship contract. Resolving that belongs to the Reasoning Orchestrator and an
authorship evolution, not to a looser identity check here.

**The model is given a narrower vocabulary than the durable one.** `IntentAmbiguityDraft`
omits `source_event_ids`, `affected_proposal_ids`, `kind` and `blocking`, because the
request exposes no event ids and Slice 1 admits one gap kind. The model cannot express
them; runtime fills them deterministically; T8 re-validates independently.

## 12c. MR5 — the OpenAI provider boundary (accepted)

The second real provider lives at `src/foundry/adapters/model_runtime/openai.py`, beside
the xAI adapter and under the same rule: `foundry/model_runtime` stays provider-neutral and
imports no SDK. MR5 changed nothing inside it, which is the point — the socket was already
the right shape, so a second provider is an addition rather than a redesign.

`OpenAIModelProvider` is **not** pinned to a model. The registry decides what is certified;
the adapter executes what it is handed.

**API surface.** The Responses API (`client.responses.parse`), not Chat Completions, with
the caller's own type as `text_format` and the typed value taken from `output_parsed`. JSON
is never hand-parsed, repaired or re-requested.

**Transport laws, each load-bearing rather than stylistic:**

- one Foundry call is one provider attempt — the installed SDK defaults `max_retries` to
  **2**, so disabling it is what makes the runtime's promise true rather than aspirational;
- every call is stateless — the Responses API **stores by default**, so `store=False` is
  sent explicitly, with no `previous_response_id`, no `conversation` and no replayed items;
- reasoning is bounded to `context="current_turn"`, so prior-turn reasoning cannot leak
  into a call that claims to be self-contained;
- no tools, no agents, no background execution, no streaming;
- no `temperature` or `top_p` — Astra does not support custom values, and reasoning effort
  is the quality knob;
- `max_cost_usd` is refused before the network, never approximated from list prices;
- `cost_usd` is always `None`: the Responses API reports no authoritative dollar cost, and
  a transport adapter that guessed one would have later budgets treat a guess as a
  measurement. Unknown is not zero, and it is not a plausible number either;
- no invented `finish_reason` — the Responses API exposes `status`, not the Chat
  Completions contract, so the field stays `None` rather than being filled with `"stop"`
  to resemble another provider.

**Two failure distinctions are deliberate.** An `openai.APIError` propagates unconverted so
the runtime reports `ModelProviderError`: a transport fault must never read as "the output
could not be parsed", which is the misdiagnosis MR2 hit live. Separately, `output_parsed`
returns `None` both when the model **refused** and when it simply produced nothing
parseable — the SDK property walks straight past refusal content — so the adapter
distinguishes them, because a refusal and a schema failure have different fixes. The
refusal text itself is not interpolated into the error; the operator gets the category, not
the model's prose about possibly sensitive input.

**Timeout lifecycle differs from xAI, for a reason.** xAI's timeout is client-scoped, so
that adapter builds a client per call to let a per-request timeout take effect. The
Responses API accepts an exact per-request `timeout`, so MR5 reuses one client per provider
and passes the bound per call. A requested timeout is never widened to a configured default.

### OpenAI model catalogue (registration is not certification)

| model | position |
|---|---|
| `gpt-6-astra` | strongest current OpenAI REASONER candidate |
| `gpt-6-sol` | strong cost-balanced candidate |
| `gpt-6-luna` | efficient high-volume candidate |

Listing a model here records that the adapter can execute it. It certifies nothing. Sol and
Luna are certified for no task, and Astra is **not** certified for `INTENT_SYNTHESIS`.

**MR5 proves OpenAI transport and protocol only. MR6 runs GPT-6 Astra through the frozen
MR4 Intent certification exam** — the same five cases and fifteen calls Grok sat, against
the same unmodified Intent prompt. Comparing providers is only meaningful if they face the
identical Intent Engine, so no OpenAI-specific prompt exists or will.

## 13. Future slices

- **MR2** — real provider adapter(s) behind `ModelProvider`; behavioural-equivalence proof against the existing xAI adapters.
- **MR3** — a `ModelRuntime`-backed `IntentSynthesizer`, replacing nothing until proven.
- **MR4** — live Intent exam against a real model.
- **MR5** — OpenAI provider adapter; transport and protocol proof only.
- **MR6** — GPT-6 Astra through the frozen MR4 Intent exam, for provider comparison.
- **Later** — Reasoning Orchestrator, cost/quality routing policy, BYOK, retry and fallback.

Numbering may be adjusted after MR1 review.
