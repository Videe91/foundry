# Certification record: anthropic/claude-fable-5-1 for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v3, exam v4)

```
status:     NOT CERTIFIED (23/27): 3 semantic failures, 0 protocol failures, 1 INCOMPLETE
standing:   NOT_CERTIFIED
candidate:  anthropic/claude-fable-5-1 (REASONER, effort max; output guard 128000, timeout 600 s)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-28
evidence:   tests/certification/evidence/anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/
identity:   ie3-graph-certification.v3; intent-synthesis.graph-v1 / runtime-v3;
            prompt 504b6080…; canonical 6b64d274…; Anthropic wire e40ae63b…
            (foundry.anthropic-structured-outputs.v2 + foundry.anthropic-graph-wire.v1);
            exam v4 2c676e55…; frozen production base 17c469e
```

No certificate was issued. Unlike an INCOMPLETE, the **three semantic failures are verdicts**:
canonical-valid graphs that the frozen exam-v4 scorer rejected. A completed run could not change
this record.

| Case | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| A NEW | PASS | PASS | PASS |
| B SAME THING | FAIL | FAIL | PASS |
| C REAL CHANGE | PASS | PASS | PASS |
| D GAP | PASS | PASS | PASS |
| E INVISIBLE | PASS | PASS | PASS |
| F STALE | FAIL | PASS | PASS |
| G CONTRADICTION | PASS | PASS | PASS |
| H MIXED | PASS | PASS | PASS |
| I KIND PAIR | PASS | PASS | INCOMPLETE |

**Semantic failures.**

- **B-1, B-2.** Both listed `REQ-existing` in `unchanged_object_refs` (correct) but *also*
  raised a gap: B-1 `MISSING_INFORMATION`, B-2 `AMBIGUITY`. Each gap argued that the basis facet
  "How long may a refund take?" reads as processing duration, while the claim states the request
  window. Scorer: "expected a pure NO_CHANGE witness answer, got 0 node(s), 0 relation(s), 1
  gap(s)".
- **F-1.** The correct REQUIREMENT `REPLACES_STALE` of `REQ-stale`, plus an `AMBIGUITY` gap
  asking whether the thirty days are calendar or business days. Scorer: "raised 1 gap(s) where
  the restatement is unambiguous; a gap does not stand in for replacing 'REQ-stale'".

**INCOMPLETE cause.** I-3 was cut off mid-stream by HTTP 400 `invalid_request_error`: "Your
credit balance is too low to access the Anthropic API". Nothing was retried.

**Answered attempts of note.**

- **F-2, F-3.** One REQUIREMENT `REPLACES_STALE` of `REQ-stale` ("Refund requests are accepted
  up to thirty days after purchase."), DERIVED_FROM the restated claim and SERVES
  `GOAL-refunds`, with no gap.
- **I-1, I-2.** The completion deadline became a REQUIREMENT ("an obligation on behaviour rather
  than a restriction"), and UK hosting became a CONSTRAINT `PROJECT_BOUNDARY` ("removing options
  from how any solution may be realised"), each with two gaps on the restriction's origin and
  scope.

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

**Measurements.** 171,347 input and 84,238 output tokens over 26 answered calls. Anthropic
reports no cost. At list price ($10 / $50 per MTok) that is about $5.93, an estimate. Median
latency 37.1 s; output high water 5,747 of 128,000.

**I-3 diagnostic (not a certification attempt).** After the credit was restored, I-3 alone was
run once through the same frozen contestant, production path and scorer, writing no evidence.
It passed: the deadline was a REQUIREMENT and UK hosting a CONSTRAINT `PROJECT_BOUNDARY`, with
two gaps (6,709 input and 4,339 output tokens, 52.1 s). This record is unchanged. The three
semantic failures stand, and no full second sitting was run.
