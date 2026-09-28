# Certification: openai/gpt-6-astra for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v3, exam v4)

> **Superseded by exam v5, 2026-09-28 (notice added; the record below is unchanged).** Exam v5 and runtime-v4 (2026-09-28) state what a gap is, which the runtime-v3 contract never did: a gap is blocking, decision-relevant unresolved work, and a meaning resolved as PARAPHRASE, CORRECTION or NEW takes no gap. They also correct case B's shared address (its facet asked "How long may a refund take?" beside a refund-request-window claim), add a mixed case J, and score every case's gaps by one rule. This certificate remains a true statement that Astra passed exam v4 under runtime-v3. It carries no authority for exam v5, where `graph_certificate_standing` reports it as `SUPERSEDED`.

```
status:     CERTIFIED (PASS, 27/27) for the exact bound identity below only
standing:   CURRENT (graph_certificate_standing)
candidate:  openai/gpt-6-astra
tier:       REASONER (reasoning effort high, mode standard)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-28
evidence:   tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_exam_v4/
format:     ie3-graph-certification.v3
```

Certification grants compute eligibility, not authority. Every model-authored node is still
PROPOSED, and Foundry validates every answer. Live graph synthesis remains **disabled**.

## Bound identity

| | |
|---|---|
| provider / model / task | `openai` / `gpt-6-astra` / `INTENT_GRAPH_SYNTHESIS` |
| policy id / version | `intent-synthesis.graph-v1` / `intent-graph-synthesis-runtime-v3` |
| prompt SHA256 | `504b6080656253630d1c1e752ed499a23b864cf2ff290ca190941b94db140e5b` |
| canonical answer schema | `6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494` |
| OpenAI wire schema | `7b8257300ee6c18fa0d772ffd53cf354bb23a773d25e0dabff91076209249afa` |
| wire compiler | `foundry.openai-structured-outputs.v1` |
| exam (worlds, scorers, gates, runner, verdict, acceptance rule) | `ie3.intent-graph-synthesis.certification-exam`, version `4`, hash `2c676e555286577284e6d50116b99b43f6527ef1c595b7faa4b84b5929442519` |
| recorded, not bound | reasoning effort `high`, `max_output_tokens=16000`, `timeout_seconds=180` |
| frozen production base | `83d416fe33bc49ff1d9222ac0860ab7fe05b701a` (`src/` verified unmodified) |

**Tamper checks (offline).** Any of the following fails to bind:

- a changed model, provider, task or policy id;
- runtime-v2 or its prompt;
- the canonical schema, the xAI wire or the xAI compiler;
- exam v3's hash, exam v2's hash, exam version 3, or another exam id;
- an exam hash edited inside the record itself.

The exam-v3 certificate is SUPERSEDED and cannot bind exam v4.

## Results (27 fresh attempts)

All 27 passed, 0 were INCOMPLETE, and there were no retries.

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

- **Case F, every run.** One REQUIREMENT `REPLACES_STALE` of `REQ-stale` (confidence 1.0),
  derived from the restated claim, with no gap and no parallel node. The statements were
  "Refund requests are accepted up to thirty days after purchase." in F-1 and "Refund requests
  must be accepted up to thirty days after purchase." in F-2 and F-3. Rationale: "replaces the
  stale requirement … rather than creating a parallel requirement".
- **Case I, every run.** The obligation became a REQUIREMENT ("Refund processing must complete
  within thirty calendar days after approval."; "a required delivery/completion deadline"). The
  boundary became a CONSTRAINT with facet `PROJECT_BOUNDARY` ("…only within approved UK-hosted
  infrastructure"; "restricts where refund-processing data may be stored and processed … no
  external mandate or factual limitation is supplied").
- **Measurements.** 158,550 input and 11,149 output tokens; output high water 722 of 16,000.
  Median latency 10.6 s; cost is not reported.
