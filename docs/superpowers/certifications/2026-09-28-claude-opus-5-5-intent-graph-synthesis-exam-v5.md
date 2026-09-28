# Certification record: anthropic/claude-opus-5-5 for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v4, exam v5)

```
status:     CERTIFIED (30/30): 0 semantic failures, 0 protocol failures, 0 INCOMPLETE
standing:   CURRENT
candidate:  anthropic/claude-opus-5-5 (REASONER, effort max; output guard 128000, timeout 600 s)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-28
evidence:   tests/certification/evidence/anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/
identity:   ie3-graph-certification.v3; intent-synthesis.graph-v1 / runtime-v4;
            prompt fd395605…; canonical 6b64d274…; wire 885a90ec…
            (foundry.anthropic-structured-outputs.v3); exam v5 b8fe070e…;
            frozen production base 39d4579
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
| J MIXED WITH A GAP | PASS | PASS | PASS |

**Gaps.** 9 in all, every one required: a CONTRADICTION anchored to the two conflicting claims in
each D and J attempt, and a CONTRADICTION anchored to `NG-digital` and the claim in each G
attempt. No gap in any other case: none beside the witness in B, none beside the replacement in F.

**Case J (mixed).** Each attempt resolved the payment-method claim as one NEW REQUIREMENT and left
the conflicting completion-time claims as one CONTRADICTION gap, anchored to those claims only.

**Measurements.** 220,590 input and 67,093 output tokens. Anthropic reports no cost. At list price ($4 / $20 per MTok) about $2.22, an estimate. Median
latency 14.8 s; output high water 6,272 of 128,000.
