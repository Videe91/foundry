# OpenAI Structured Outputs compatibility: IE3 graph-answer wire schema

```
kind:       SCHEMA TRANSPORT COMPATIBILITY PROBE (not a model certification)
result:     ACCEPTED
provider:   openai (model endpoint gpt-6-astra, reasoning high / standard)
date:       2026-09-27
code:       a0fccc7
evidence:   tests/certification/evidence/_compatibility/openai/schema_probe.json
probe:      tests/integration/test_openai_graph_schema_probe_live.py
            (opt-in: OPENAI_API_KEY + RUN_LIVE_OPENAI_SCHEMA_PROBE=1; 2 calls)
```

| | |
|---|---|
| canonical graph-answer schema | `6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494` |
| OpenAI wire schema | `7b8257300ee6c18fa0d772ffd53cf354bb23a773d25e0dabff91076209249afa` |
| wire compiler | `foundry.openai-structured-outputs.v1` |

## What was established

1. **OpenAI accepts the compiled schema.** The earlier refusal (`400 invalid_json_schema`,
   "'oneOf' is not permitted") does not recur. The wire contains no `oneOf`.
2. **Nested `anyOf` is accepted** in all nine union positions: `GraphRef`, `GraphNodeProposal`
   and the seven two-state replaceable node families.
3. **`discriminator` metadata is accepted.** It was retained unchanged, not removed on a guess.
4. **One structured answer passed end to end** through `OpenAIModelProvider` and was validated
   by `IntentGraphDraftPayload` (outcome `ACCEPTED_AND_VALIDATED`).

## Regex boundary: no counterexample, not a proof

Pydantic and JSON Schema's ECMA semantics both refuse a `local_id` ending in a newline. Python's
`re` would accept one; the offline tests therefore validate `pattern` with ECMA semantics and
show that the difference exists only in that local engine. Whether OpenAI's `pattern`
implementation also refuses the value cannot be proven offline.

The model was asked for exactly such a value (`"a\n"`). It returned `"a"`, which satisfies the
pattern, so no wire-soundness counterexample was observed. That is evidence, not proof: the
decoder may forbid the newline, or the model may simply not have produced one.

**Open item before certification:** decide whether this residual uncertainty is acceptable, or
whether it needs a narrower wire form or further evidence. In every case, Pydantic still refuses
such a value in the adapter, so no invalid value can enter Foundry. The only risk is that an
attempt fails as a protocol error.

## What this is not

No model was examined. No certification record was written, no exam case ran, no scorer was
consulted, and nothing is wired into normal Foundry execution. The 24-attempt GPT-6 Astra graph
certification has not been started.
