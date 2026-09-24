# Model Runtime — MR1 implementation plan and result

Spec: `docs/superpowers/specs/2026-09-24-model-runtime-design.md`.

## Scope

MR1 creates the stable socket every later Foundry domain will plug into. It adds no
provider adapter, no orchestration and no domain migration.

## Package

```
src/foundry/model_runtime/
    __init__.py   public surface
    domain.py     ModelTier, ModelCapability, ModelTask, REQUIRED_TIER_BY_TASK,
                  ModelIdentity, ModelDescriptor, MessageRole, ModelMessage,
                  ModelExecutionConstraints, ModelTraceContext, ModelRequest,
                  ModelUsage, ModelResultMetadata, ModelExecutionResult[T]
    ports.py      ModelProvider protocol, ProviderExecutionResult[T]
    registry.py   ModelRegistry (immutable, deterministic, duplicate-refusing)
    routing.py    select_model — pure, no clock, no randomness, no provider call
    runtime.py    ModelRuntime.execute(request, output_type=...)
    errors.py     five distinguishable failures
    fake.py       strict deterministic provider double
```

No `openai.py`, `anthropic.py`, `google.py` or `xai.py` — MR2+.

## Public API

```python
runtime = ModelRuntime(registry=ModelRegistry(descriptors=(...)), providers=(...,))
result: ModelExecutionResult[Answer] = runtime.execute(request, output_type=Answer)
```

The caller owns `Answer`. The runtime never defines domain output schemas and never
unions them.

## Execution flow

```
ModelRequest (task↔tier validated at construction)
  → select_model(registry, request)        certified tier + task + capabilities
  → provider adapter lookup by provider_id
  → provider.execute(...)                  exactly once; no retry, no fallback
  → verify returned provider/model identity
  → validate output against the caller's type
  → ModelExecutionResult[T]
```

## MEASURED (MR1 complete)

**RED:** `ModuleNotFoundError: No module named 'foundry.model_runtime'` across all five
test modules. **130 tests**, five focused modules under `tests/unit/model_runtime/`.

- **WORKER/REASONER matrix:** `CODING+WORKER`, `ARCHITECTURE+REASONER`,
  `INTENT_SYNTHESIS+REASONER` valid; `CODING+REASONER`, `ARCHITECTURE+WORKER`,
  `INTENT_SYNTHESIS+WORKER`, `TESTING+REASONER`, `GAP_ANALYSIS+WORKER`,
  `REPOSITORY_INSPECTION+REASONER` all structurally refused. Never auto-corrected.
- **Certification:** wrong tier, wrong task and missing capability each yield ineligible;
  all three satisfied yields eligible; extra capabilities never disqualify.
- **Dual role:** one descriptor with `tiers={WORKER, REASONER}` and
  `certified_tasks={CODING, ARCHITECTURE}` executes both requests, and is still bound by
  its certified task list.
- **Plug-and-play:** changing only the registry changes which provider executes, with the
  caller's `ModelRequest`, output type and runtime API unchanged.
- **Failures:** no certified model → `ModelUnavailableError` with zero provider calls;
  adapter absent → `ModelProviderUnavailableError` and no fall-through to an installed
  adapter; adapter raises → `ModelProviderError` with `__cause__` preserved; wrong model
  or provider returned → `ModelProtocolError`; wrong or invalid output → `ModelProtocolError`,
  never repaired.
- **No retry:** one `execute` makes at most one provider call.
- **Boundaries:** no module imports a provider SDK, the ledger, Foundry authority, or any
  Intent-specific module; no domain prompt text; no public contract carries a credential
  field; the runtime's `__dict__` is byte-for-byte unchanged across calls.

**Mutations: 13 applied, 13 killed, none survived** — tier validation removed, tier mapping
inverted, task certification ignored, capability ignored, tier certification ignored,
identity check removed, adapter fall-through, duplicate registry entries accepted, routing
order reversed, credential field added to `ModelRequest`, provider SDK imported into the
port, `verified` field added to the result, and the output-type boundary downgraded.

**Intent Synthesis Slice 1 is untouched and green.**

## Deliberately not in MR1

Real provider adapters, any vendor SDK, xAI migration, Intent real-model adapter,
Research Worker or Planner, Architecture or Planning engines, Reasoning Orchestrator,
model-to-model delegation, parallel execution, fallback, retry, cost optimisation, BYOK,
credential vault, persistent registry, eval-based routing, traffic splitting, streaming,
tool execution, agent loops.
