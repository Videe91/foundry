# Certification record: anthropic/claude-sonnet-5 for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v3, exam v4)

```
status:     NOT CERTIFIED (13/27): 0 semantic failures, 0 protocol failures, 14 INCOMPLETE
standing:   NOT_CERTIFIED (graph_certificate_standing has no INCOMPLETE category)
candidate:  anthropic/claude-sonnet-5 (REASONER, effort max; output guard 128000, timeout 600 s)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-28
evidence:   tests/certification/evidence/anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/
identity:   ie3-graph-certification.v3; intent-synthesis.graph-v1 / runtime-v3;
            prompt 504b6080…; canonical 6b64d274…; Anthropic wire e40ae63b…
            (foundry.anthropic-structured-outputs.v2 + foundry.anthropic-graph-wire.v1);
            exam v4 2c676e55…; frozen production base 17c469e
```

No certificate was issued: the acceptance rule requires 27 passes. **Every attempt Sonnet 5
answered passed (13/13).** The other 14 got no answer because the Anthropic account's credit ran
out. **Cases F, G, H and I were never examined**, so this record says nothing about case F or I.

| Case | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| A NEW | PASS | PASS | PASS |
| B SAME THING | PASS | PASS | PASS |
| C REAL CHANGE | PASS | PASS | PASS |
| D GAP | PASS | PASS | PASS |
| E INVISIBLE | PASS | INCOMPLETE | INCOMPLETE |
| F STALE | INCOMPLETE | INCOMPLETE | INCOMPLETE |
| G CONTRADICTION | INCOMPLETE | INCOMPLETE | INCOMPLETE |
| H MIXED | INCOMPLETE | INCOMPLETE | INCOMPLETE |
| I KIND PAIR | INCOMPLETE | INCOMPLETE | INCOMPLETE |

**INCOMPLETE causes.** E-2 was cut off mid-stream; E-3 through I-3 were refused. All 14 got
HTTP 400 `invalid_request_error`: "Your credit balance is too low to access the Anthropic
API". Nothing was retried.

**Transport.** Anthropic Messages API through `anthropic` 1.8.0: `client.messages.stream(...)`
then `get_final_message()`, with `output_config = {format: {type: json_schema, schema: <compact
graph wire>}, effort: "max"}`. `thinking` is omitted (adaptive), `max_tokens` is 128,000, the
timeout is 600 s, `max_retries=0` and there are no server-side fallbacks. The reply is converted
mechanically to canonical form (`parse_graph_wire`), then validated as `IntentGraphDraftPayload`.
The compiled canonical wire (`ca63b550…`, compiler v1) was refused by Anthropic as too large a
grammar (`evidence/_compatibility/anthropic/schema_probe.json`); the compact wire was accepted
by all three Claude models (`compact_wire_probe.json`).

**Protocol-invalid answers: none.** Every reply that arrived passed both the wire shape and
canonical validation.

**Measurements.** 85,020 input and 103,267 output tokens over 13 answered calls. Anthropic
reports no cost. At list price ($2 / $10 per MTok) that is about $1.20, an estimate. Median
latency 78.5 s; output high water 17,542 of 128,000.
