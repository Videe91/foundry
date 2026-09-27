# Certification: openai/gpt-6-astra for INTENT_GRAPH_SYNTHESIS (IE3, prompt runtime-v2)

```
status:     NOT CERTIFIED  (0/24; all 24 attempts INCOMPLETE; the model never answered)
candidate:  openai/gpt-6-astra
tier:       REASONER
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-27
evidence:   tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_v2/
```

This is a new certification. It inherits nothing from Astra's Slice-1 INTENT_SYNTHESIS record
or from either Grok 4.7 graph record. Astra's Slice-1 evidence
(`evidence/openai/gpt-6-astra/case_a_ledger.json`, `measurements.json`) is untouched.

## Contestant, frozen

| | |
|---|---|
| identity | `openai/gpt-6-astra`, reused from Astra's Slice-1 runner, not invented |
| provider configuration | `OpenAIModelProvider(reasoning_effort="high", reasoning_mode="standard")`, unchanged from Slice-1 |
| policy id / version | `intent-synthesis.graph-v1` / `intent-graph-synthesis-runtime-v2` |
| prompt SHA256 | `e8e1763db2c7f7df1496406082d0e0014b4de0f0ecea80f6e1e535951a97e605` |
| constraints | `max_output_tokens=16000` (Astra's predeclared reasoning-inclusive guard), `timeout_seconds=180` (the graph exam's), `max_cost_usd=None` |
| frozen production base | `892e00c6c419160ba6969b19bbd965f0a737c2d7` (`src/` verified unmodified) |
| runner | `tests/certification/test_gpt_6_astra_intent_graph_synthesis_live.py`, a contestant only. The exam, scorers and acceptance rule are unchanged. |

## Result

All 24 attempts (8 cases × 3 runs) were refused by the OpenAI API before any model inference
took place:

```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid schema for
response_format 'IntentGraphDraftPayload': In context=(), 'oneOf' is not permitted.",
'type': 'invalid_request_error', 'param': 'text.format.schema', 'code': 'invalid_json_schema'}}
```

| Case | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| A to H | INCOMPLETE (schema refused) | INCOMPLETE (schema refused) | INCOMPLETE (schema refused) |

- The harness's existing taxonomy classifies all 24 attempts as `TransportFailure`, which
  counts as INCOMPLETE. The run log confirms that all 24 have the same cause.
- No answer exists, so no ledger was written and there is nothing to replay. No tokens were
  consumed.
- **Verdict: NOT CERTIFIED**, because the rule requires 24 passing attempts. This record carries
  **no semantic information about GPT-6 Astra**. Astra was never examined on the graph task.

## Cause

The production graph adapter declares `IntentGraphDraftPayload` as its structured output type.
Its reference fields are discriminated unions (local, existing and basis refs). Pydantic renders
these as `oneOf` plus `discriminator`. OpenAI strict structured outputs do not accept `oneOf`.
xAI accepted the same schema, which is why Grok could sit the exam.

An offline check before the run showed that the schema contains `oneOf`. It was not known
whether the API would refuse it, and a refusal is free and classified as INCOMPLETE, so the
run went ahead as the truthful test.

Nothing was changed to work around this. The schema, adapter, prompt, validators and scorers
are untouched, and nothing was retried.

## Binding and containment

- The offline certification suite passed: 220 passed, 86 skipped (live-only), with providers
  bombed.
- `test_the_recorded_certification_binds_exactly_its_contestant[gpt-6-astra/intent_graph_synthesis_v2]`
  passes. The record binds neither its own contract nor the current one, because its verdict
  is not PASS. It never binds another model, prompt digest or policy version.
- The credential scan of the new evidence is clean.

## ARCHITECTURE QUESTION (blocks any Astra graph certification)

Should the IE3 graph output contract be representable in OpenAI strict structured outputs,
and if so, how?

Options:

- **Change the draft schema to emit `anyOf` instead of `oneOf`.** For example, drop the
  pydantic discriminator and keep the namespace literal on each ref. This changes the
  production adapter's wire schema, which needs a policy-version decision and a fresh
  certification of every contestant.
- **Give the OpenAI adapter a provider-side schema transform (`oneOf` → `anyOf`).** This keeps
  domain types unchanged, but the adapter would then send a schema different from the one
  certified for xAI, and neutrality would need to be proved.
- **Declare INTENT_GRAPH_SYNTHESIS xAI-only for now.** No code change, but Foundry becomes
  coupled to one provider for this task, contrary to the provider-isolation rule.

Blocked work: any GPT-6 Astra certification for INTENT_GRAPH_SYNTHESIS.

Per the task's stop rule, the prompt was not modified, no other model was tried, and no attempt
was retried or re-scored.
