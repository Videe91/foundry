# Certification record: anthropic/claude-opus-5-5 for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v3, exam v4)

```
status:     CERTIFIED (27/27): 0 semantic failures, 0 protocol failures, 0 INCOMPLETE
standing:   CURRENT
candidate:  anthropic/claude-opus-5-5 (REASONER, effort max; output guard 128000, timeout 600 s)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-28
evidence:   tests/certification/evidence/anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/
identity:   ie3-graph-certification.v3; intent-synthesis.graph-v1 / runtime-v3;
            prompt 504b6080…; canonical 6b64d274…; Anthropic wire e40ae63b…
            (foundry.anthropic-structured-outputs.v2 + foundry.anthropic-graph-wire.v1);
            exam v4 2c676e55…; frozen production base 122a3c2
```

Every attempt of every case passed on one complete, independent sitting.

| Case | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| A NEW | PASS | PASS | PASS |
| B SAME THING | PASS | PASS | PASS |
| C REAL CHANGE | PASS | PASS | PASS |
| D GAP | PASS | PASS | PASS |
| E INVISIBLE | PASS | PASS | PASS |
| F STALE | PASS | PASS | PASS |
| G CONTRADICTION | PASS | PASS | PASS |
| H MIXED | PASS | PASS | PASS |
| I KIND PAIR | PASS | PASS | PASS |

**Earlier sitting.** A first sitting (commit `122a3c2`, frozen base `17c469e`) recorded 25/27
with 0 semantic failures. Its I-2 and I-3 got no answer because the Anthropic account's credit
ran out (HTTP 400 "credit balance is too low"). It was an incomplete examination, not a verdict.
This complete sitting replaces that record on disk; the first remains in git history. Nothing
was stitched between sittings.

**Answered attempts of note.**

- **F-1, F-2, F-3.** Each was one REQUIREMENT `REPLACES_STALE` of `REQ-stale` ("Refund
  requests are accepted up to thirty days after purchase."), with no gap.
- **I-1, I-2, I-3.** Each gave the completion deadline as a REQUIREMENT and UK hosting as a
  CONSTRAINT `PROJECT_BOUNDARY`, plus two or three gaps on the hosting restriction's origin and
  scope.

**Transport.** Anthropic Messages API through `anthropic` 1.8.0: `client.messages.stream(...)`
then `get_final_message()`, with `output_config = {format: {type: json_schema, schema: <compact
graph wire>}, effort: "max"}`. `thinking` is omitted (adaptive), `max_tokens` is 128,000, the
timeout is 600 s, `max_retries=0` and there are no server-side fallbacks. The reply is converted
mechanically to canonical form (`parse_graph_wire`), then validated as `IntentGraphDraftPayload`.
The compiled canonical wire (`ca63b550…`, compiler v1) was refused by Anthropic as too large a
grammar (`evidence/_compatibility/anthropic/schema_probe.json`); the compact wire was accepted
(`compact_wire_probe.json`).

**Binding.** The certificate binds only this model: it does not bind any other Claude model,
`openai/gpt-6-astra` or `xai/grok-4.7`. Changing the provider, model, wire hash, wire compiler,
canonical hash, prompt, policy version, exam version or exam hash breaks it.

**Measurements.** 178,056 input and 144,659 output tokens over 27 calls. Anthropic reports no
cost. At list price ($4 / $20 per MTok) that is about $3.61, an estimate. Median latency
30.7 s; output high water 16,692 of 128,000.
