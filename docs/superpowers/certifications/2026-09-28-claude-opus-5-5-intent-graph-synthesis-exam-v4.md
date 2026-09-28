# Certification record: anthropic/claude-opus-5-5 for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v3, exam v4)

```
status:     NOT CERTIFIED (25/27): 0 semantic failures, 0 protocol failures, 2 INCOMPLETE
standing:   NOT_CERTIFIED (graph_certificate_standing has no INCOMPLETE category)
candidate:  anthropic/claude-opus-5-5 (REASONER, effort max; output guard 128000, timeout 600 s)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-28
evidence:   tests/certification/evidence/anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/
identity:   ie3-graph-certification.v3; intent-synthesis.graph-v1 / runtime-v3;
            prompt 504b6080…; canonical 6b64d274…; Anthropic wire e40ae63b…
            (foundry.anthropic-structured-outputs.v2 + foundry.anthropic-graph-wire.v1);
            exam v4 2c676e55…; frozen production base 17c469e
```

No certificate was issued: the acceptance rule requires 27 passes. **Every attempt Opus 5.5
answered passed (25/25).** The other two got no answer because the Anthropic account's credit
ran out, so this record is an incomplete examination, not evidence of a semantic failure.

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
| I KIND PAIR | PASS | INCOMPLETE | INCOMPLETE |

**INCOMPLETE causes.** I-2 was cut off mid-stream and I-3 was refused, both with HTTP 400
`invalid_request_error`: "Your credit balance is too low to access the Anthropic API". The
frozen protocol has no retry rule, so nothing was retried. **Case I was examined once.**

**Answered attempts of note.**

- **F-1, F-2, F-3.** Each was one REQUIREMENT `REPLACES_STALE` of `REQ-stale` ("Refund
  requests are accepted up to thirty days after purchase."; F-3 "must be accepted"), with
  DERIVED_FROM the restated claim and SERVES `GOAL-refunds`, and no gap.
- **I-1.** The completion deadline became a REQUIREMENT ("governs the result delivered, not how
  a solution is built"), and UK hosting became a CONSTRAINT `PROJECT_BOUNDARY` ("removes hosting
  and data-location options"), plus two gaps on the hosting restriction's origin and scope.

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

**Measurements.** 164,638 input and 106,131 output tokens over 25 answered calls. Anthropic
reports no cost. At list price ($4 / $20 per MTok) that is about $2.78, an estimate that
excludes any charge for the call cut off mid-stream. Median latency 31.0 s; output high water
13,195 of 128,000.
