# Model Runtime — MR3: ModelRuntime-backed IntentSynthesizer

Spec: `docs/superpowers/specs/2026-09-24-model-runtime-design.md`.
MR1 and MR2 remain completed measured slices; neither is rewritten.

## Scope

Connect the certified `IntentSynthesizer` port to the certified `ModelRuntime`. The
adapter converts model output and nothing else — T7 and T8 remain the authority.

**Zero production changes to the certified Intent Engine.** `ports/intent_synthesizer.py`,
`application/intent_synthesis.py`, `application/intent_synthesis_context.py` and
`domain/intent_synthesis.py` are all untouched; the architecture fit without them.

## Files

```
src/foundry/adapters/intent_synthesis/__init__.py
src/foundry/adapters/intent_synthesis/model_runtime.py
tests/unit/adapters/intent_synthesis/test_model_runtime.py          31 tests
tests/integration/test_intent_synthesis_model_runtime.py             7 tests
```

## Public shape

```python
ModelRuntimeIntentSynthesizer(
    *,
    runtime: ModelRuntime,
    model_identity: ModelIdentity,
    trace_factory: Callable[[], ModelTraceContext],
    execution_constraints: ModelExecutionConstraints | None = None,
)
```

`INTENT_SYNTHESIS_POLICY_ID = "intent-synthesis.slice1"`
`INTENT_SYNTHESIS_POLICY_VERSION = "intent-synthesis-runtime-v1"`
`SYSTEM_INSTRUCTION_SHA256 = "af49dbd3ac8049642cfb7a2af70acf719da4e2c2af5faf7128ec47d6413e8f5d"`

`trace_factory` exists because the Intent port deliberately does not expose
`synthesis_run_id`: Model Runtime trace ids are operational telemetry, not durable Intent
identity, and the port was not widened to carry them.

## The authorship law, and its known limitation

T8 reads `synthesizer.fingerprint` **before** the call and writes it as durable authorship
on the decision record. So one instance is bound to one expected `ModelIdentity`, and the
fingerprint is configured provider/model plus the pinned policy version — never anything
the model said.

After execution the adapter compares `result.metadata.identity` to the configured identity
and raises `ModelProtocolError` on any difference, returning no result. The runtime may
consider the routed model perfectly valid; that is not the question. Returning a result
would write a decision record naming a model that never ran, and nothing model-derived is
durable at that point, so failing closed is safe.

**Stated plainly rather than buried:** because the fingerprint is read before execution and
becomes durable, **dynamic fallback or model-switching within one synthesis invocation is
not legal** under the current `IntentSynthesizer` authorship contract. That is a real
constraint on multi-model routing. It belongs to a future Reasoning Orchestrator and an
authorship evolution — not to MR3, and it must not be worked around by loosening the
identity check.

## Why the legacy GapProposal is not exposed to the model

`GapProposal` carries `source_event_ids`, `affected_proposal_ids`, a free `GapKind` and
`blocking`. The Intent request exposes **no event ids at all**, and Slice 1 admits only
`AMBIGUITY`. A model filling those fields would be inventing provenance and classification.

`IntentAmbiguityDraft` therefore has exactly four fields — `proposal_id`, `subject_key`,
`description`, `confidence` — so the model *cannot express* the rest rather than being
trusted not to. Runtime maps deterministically to `GapProposal` with `kind=AMBIGUITY`,
`blocking=True`, `source_event_ids=()`, `affected_proposal_ids=()`, and T8's own
`_validate_model_gaps` still re-checks the mapped result independently.

Requirement proposals reuse the existing `RequirementSynthesisProposal` — no second
competing vocabulary — since it already cannot express authority, scope, durable ids,
provenance or materiality.

## MEASURED (MR3 complete)

**RED:** `ModuleNotFoundError: No module named 'foundry.adapters.intent_synthesis'`.

- **Request mapping:** `INTENT_SYNTHESIS` / `REASONER` / `{TEXT_GENERATION, STRUCTURED_OUTPUT}`, pinned policy labels, injected trace, exactly two messages (SYSTEM instruction, USER rendered request).
- **Rendering:** canonical JSON of the exact approved request, asserted by `json.loads(rendered) == request.model_dump(mode="json")` — enrichment is structurally detectable, not a matter of vigilance.
- **Prompt freeze:** live hash equals the pasted literal; a prompt edit fails the build until hash and policy version are updated deliberately.
- **Round trip:** proposals survive with no field loss; confidence `None`/`0.0`/`0.61`/`1.0` each preserved exactly.
- **Both branches preserved:** mixed and empty results pass through unrepaired for T8's C24 to reject.
- **Provider neutrality:** the same adapter class, same request, same output schema, two different providers — proven with two fakes behind the real runtime.
- **Production vertical:** model proposal → durable Requirement through the real T8 path, with author = configured identity, authority assigned by routing (`PROPOSED`), `created_at` from `decided_at`, provenance and `DERIVED_FROM` relations runtime-owned.
- **Ambiguity vertical:** draft → durable `IntentSynthesisGap` with `AMBIGUITY`, `blocking=True`, runtime-owned scope, `materiality=None`, `risk=None`, no Requirement written.
- **Non-durability:** invisible claim, target absent from snapshot, mixed result and empty result each rejected with **zero** `INTENT_SYNTHESIS_DECIDED`, `INTENT_OBJECT_SYNTHESIZED` or `GAP_RECORDED` appended.
- **No-call fence:** a scope with nothing eligible reaches **zero** provider calls.
- **No memory:** a second synthesis carries nothing from the first.

**Mutations: 20 applied, 20 killed, none survived.**

**No real model is task-certified.** Test-local descriptors certify `INTENT_SYNTHESIS`
solely to exercise the runtime path. Formal Grok certification requires MR4's live exam.

## MR4 seam

Swapping in a real provider is configuration only:

```python
runtime = ModelRuntime(registry=..., providers=(XAIModelProvider(api_key=...),))
synthesizer = ModelRuntimeIntentSynthesizer(
    runtime=runtime, model_identity=ModelIdentity(provider="xai", model="grok-4.7"), ...
)
synthesize_intent(store, ..., synthesizer=synthesizer, ...)
```

No architectural change required.
