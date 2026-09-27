# Certification: openai/gpt-6-astra for INTENT_GRAPH_SYNTHESIS (IE3, schema-bound)

```
status:     NOT CERTIFIED  (21/24; acceptance rule requires 24/24)
candidate:  openai/gpt-6-astra
tier:       REASONER (reasoning effort high, mode standard)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-27
evidence:   tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_schema_bound/
format:     ie3-graph-certification.v2
```

This is the first **semantic** examination of GPT-6 Astra on the graph task. The earlier Astra
graph record (`intent_graph_synthesis_v2`, 0/24) was transport evidence only: OpenAI refused the
schema before inference. That record is unchanged and still means no examination occurred.

## Bound identity

| | |
|---|---|
| provider / model | `openai` / `gpt-6-astra` |
| policy id / version | `intent-synthesis.graph-v1` / `intent-graph-synthesis-runtime-v2` |
| prompt SHA256 | `e8e1763db2c7f7df1496406082d0e0014b4de0f0ecea80f6e1e535951a97e605` |
| canonical answer schema | `6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494` |
| OpenAI wire schema | `7b8257300ee6c18fa0d772ffd53cf354bb23a773d25e0dabff91076209249afa` |
| wire compiler | `foundry.openai-structured-outputs.v1` |
| constraints | `max_output_tokens=16000` (high water 1479), `timeout_seconds=180`, `max_cost_usd=None` |
| frozen production base | `5ca6fffc75762e45a9999e5ce06354983b892457` (`src/` verified unmodified) |

The protocol is unchanged: 8 cases × 3 independent fresh-world runs, the MR4/MR6
every-run-passes rule, deterministic scorers, and the existing taxonomy (transport and harness
limits count as INCOMPLETE; semantic and protocol failures count as FAIL).

## Results

| Case | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| A NEW | PASS | PASS | PASS |
| B SAME THING / NO_CHANGE | PASS (pure NO_CHANGE) | PASS | PASS |
| C REAL CHANGE | FAIL | FAIL | FAIL |
| D GAP | PASS | PASS | PASS |
| E INVISIBLE | PASS | PASS | PASS |
| F STALE / NON-CURRENT | PASS | PASS | PASS |
| G CONTRADICTION | PASS | PASS | PASS |
| H MIXED | PASS | PASS | PASS |

- 24 attempts, all answered; 0 INCOMPLETE; 0 transport or protocol faults.
- 21 passed and 3 failed (all case C).
- Tokens: 131,955 input and 12,687 output in total. Median latency 9.6 s. Cost is unknown,
  because the Responses API reports none.

Every failure has the same scored reason: `expected exactly one REPLACES_STALE node replacing
'REQ-old', got 0`. The model-authored answers were:

- **C1 and C3:** no nodes, and one AMBIGUITY gap anchored to the corrected claim and `REQ-old`.
  The gap says the claim is about *how long a refund may take*, while `REQ-old` governs *when
  refund requests are accepted after purchase*, and asks which is meant.
- **C2:** a NEW REQUIREMENT ("A refund must take no more than fourteen calendar days."),
  explicitly distinct from `REQ-old`'s purchase-to-request acceptance window.

## Behaviours the remaining cases show

- **Witnesses.** In B and H, `unchanged_object_refs` named exactly the object that represents
  the claim. No context witness (parent Intent or served Goal) appeared in any answer.
- **Retired objects.** No answer referenced a retiring object unlawfully.
- **Missing information.** In D the model emitted a gap instead of inventing information.
- **Invisible refs.** None were used (E).
- **Mixed answers.** New and already-represented meaning were handled correctly (H, 3/3).

## Caveat: the case C construction defect (unchanged, pre-registered)

Case C's stale object `REQ-old` says "Refund requests are accepted within 30 days of purchase"
(a request window). The superseded claim and its correction ("Refunds must complete within
thirty → fourteen calendar days") describe completion time. The two concepts differ, so
REPLACES_STALE is not the only defensible answer. This was recorded before this run (Grok
runtime-v2 record) and deliberately not changed. Astra identified the mismatch itself in all
three runs.

The verdict follows the acceptance rule and stands: **NOT CERTIFIED**. Whether case C should be
rebuilt, and a fresh certification run, is a decision for the exam's owners. It is not made here.

## Replay and binding (offline, providers disabled)

- **Ledger replay.** All 8 model-authored ledgers replay identically three ways (32 replay
  tests) with every provider disabled.
- **Outcome reproduction.** An ad-hoc replay with the network blocked reproduced each attempt-1
  route (A, C–H APPLY; B NO_CHANGE) and C1's scored failure condition (0 REPLACES_STALE nodes of
  `REQ-old`; one AMBIGUITY gap).
- **Binding.** The v2 record carries all bound fields. Because its verdict is not PASS, it binds
  neither its own identity nor the current one; the tamper matrix (prompt, policy, canonical
  schema, wire schema, compiler, model) never binds.
- **Historical records.** None binds this identity.

No production code changed.
