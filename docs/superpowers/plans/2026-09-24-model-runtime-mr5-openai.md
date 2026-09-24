# Model Runtime — MR5: OpenAI provider + GPT-6 Astra live transport proof

Base: `28f9a2ece570ed4b1811e352aca9115a7e25b4b8` (MR4 certified and closed).

## What MR5 is

A second real provider behind the already-certified shared Model Runtime:

```
ModelRuntime → OpenAIModelProvider → OpenAI Responses API → gpt-6-astra → typed output
```

That is the entire claim. MR5 proves **transport and protocol**. It does not certify GPT-6
Astra for Intent Synthesis, or for anything else. Certification is task-specific, and
Astra's Intent exam is MR6.

The most useful result of this slice is the part that required no work: `foundry/model_runtime`
was not touched. A second provider with a materially different protocol — Responses rather
than a chat-completions shape, per-request timeouts rather than client-scoped, no cost
field, no finish reason — fit the existing port without a single change to it. That is the
evidence that the MR1 socket was cut at the right joint; had the runtime needed adjusting to
admit OpenAI, the adapter boundary would have been provider-shaped all along.

## Files

```
src/foundry/adapters/model_runtime/openai.py          new — the adapter
src/foundry/adapters/model_runtime/__init__.py        export only
tests/unit/adapters/model_runtime/_fake_openai.py     new — SDK double
tests/unit/adapters/model_runtime/test_openai.py      new — 57 unit proofs
tests/integration/test_openai_model_runtime_live.py   new — one live smoke
pyproject.toml / uv.lock                              openai>=3.17,<4
docs/superpowers/specs/2026-09-24-model-runtime-design.md   additive §12c
```

Zero changes to `foundry/model_runtime/`, to the xAI adapter, to any Intent production
file, and to `tests/certification/`.

## The SDK was inspected, not remembered

Every protocol decision below was checked against the installed `openai` **3.19.2** rather
than against documentation or memory. Three findings changed the implementation:

1. **`max_retries` defaults to `2`.** One Foundry execution would silently have become up
   to three provider attempts. A test pins the SDK default, so if it ever changes the law
   is re-read rather than quietly kept as ceremony.
2. **`output_parsed` is a property that walks past refusals.** Its real implementation
   returns the first `output_text` with a `parsed` value and `None` otherwise — so a
   refusal and a genuinely empty result are indistinguishable at that seam. The adapter
   separates them deliberately; the test double reproduces the property exactly so this is
   tested against real behaviour rather than a convenient fake.
3. **`LengthFinishReasonError` and `ContentFilterFinishReasonError` are `OpenAIError` but
   not `APIError`.** They mean the call reached the model and the output was cut short, so
   they map to `ModelProtocolError`, not to the transport category. A test pins that
   subclassing fact too.

Also confirmed: `Response` has **no** `finish_reason` field, `ResponseUsage` has **no**
cost field, and `gpt-6-astra` / `gpt-6-sol` / `gpt-6-luna` are real entries in the SDK's
model literal.

## Laws, and why each is load-bearing

| law | what it prevents |
|---|---|
| `max_retries=0` | the SDK retrying beneath a runtime that promises one attempt |
| `store=False` | the Responses API's default storage becoming project memory (Law 3) |
| `reasoning.context="current_turn"` | prior-turn reasoning leaking into a bounded call |
| no `previous_response_id` / `conversation` | provider-side conversation state |
| `tools=[]` | tool use inherited from a vendor rather than certified deliberately |
| no `temperature` / `top_p` | unsupported knobs on Astra; effort is the quality knob |
| identity from `response.model` | a substitution agreeing with itself |
| `cost_usd = None` | a list-price guess being treated later as a measurement |
| `finish_reason = None` | inventing `"stop"` to resemble another provider |
| `max_cost_usd` refused pre-network | a caller believing a budget applied that never did |

## Two things deliberately kept distinct

**Transport is not protocol.** `openai.APIError` propagates unconverted, so the runtime
reports `ModelProviderError` with the cause preserved. MR2's first live run misreported a
transient gRPC fault as "output could not be parsed", which sent the diagnosis in exactly
the wrong direction; that lesson is encoded here rather than relearned.

**A refusal is not an empty answer.** They get different errors, and the refusal's own text
is never interpolated into the message — the operator learns the category, not the model's
prose about possibly sensitive input.

## Verification

57 unit proofs, all against a real runtime, real registry and real adapter with only the
SDK boundary doubled. **24 mutation controls**, one per law in the brief's negative-control
list; every one was applied to the adapter, confirmed to break at least one test, and the
tree was restored byte-identical and re-proved green. A suite that cannot fail certifies
nothing, so the mutations are the actual evidence that these tests assert the laws they
claim to.

Live smoke: one real call to `gpt-6-astra`, answering `17 × 4` as a typed `ArithmeticAnswer`.
The only quality claim in MR5 is that deterministic arithmetic fact. The smoke's registry
entry grants `EVALUATION` as test-local transport permission and nothing else.

## MR6 seam

No architecture change is needed to run Astra through the Intent exam: point a descriptor
at `openai/gpt-6-astra` for `INTENT_SYNTHESIS`, hand `ModelRuntimeIntentSynthesizer` the
same runtime with an `OpenAIModelProvider`, and run the identical five-case, fifteen-call
exam Grok sat.

The Intent prompt must not change for OpenAI, and no OpenAI-specific Intent prompt may be
created. Comparing providers is only meaningful against the same Intent Engine; a prompt
tuned per provider would measure the tuning, not the model.
