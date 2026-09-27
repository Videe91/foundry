# Certification: openai/gpt-6-astra for INTENT_GRAPH_SYNTHESIS (IE3, exam v2)

```
status:     CERTIFIED (PASS, 24/24) for the exact bound identity below only
candidate:  openai/gpt-6-astra
tier:       REASONER (reasoning effort high, mode standard)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-27
evidence:   tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_exam_bound/
format:     ie3-graph-certification.v3
```

Certification grants **compute eligibility, not authority**. Every model-authored node is still
PROPOSED, and Foundry validates every answer. Live graph synthesis is **not** enabled in normal
Foundry execution; this record changes no runtime path.

## Bound identity

| | |
|---|---|
| provider / model / task | `openai` / `gpt-6-astra` / `INTENT_GRAPH_SYNTHESIS` |
| policy id / version | `intent-synthesis.graph-v1` / `intent-graph-synthesis-runtime-v2` |
| prompt SHA256 | `e8e1763db2c7f7df1496406082d0e0014b4de0f0ecea80f6e1e535951a97e605` |
| canonical answer schema | `6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494` |
| OpenAI wire schema | `7b8257300ee6c18fa0d772ffd53cf354bb23a773d25e0dabff91076209249afa` |
| wire compiler | `foundry.openai-structured-outputs.v1` |
| exam | `ie3.intent-graph-synthesis.certification-exam`, version `2`, hash `813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c` |
| recorded, not bound | reasoning effort `high`, `max_output_tokens=16000`, `timeout_seconds=180` |
| frozen production base | `9d12687a6cd48434afea3ff1a5afe0e4b438de05` (`src/` verified unmodified) |

Changing any bound value makes the record certify nothing. The tamper checks (provider, model,
task, policy id and version, prompt, canonical schema, wire schema, compiler, exam id, version
and hash, and an edited record) never bind.

## Exam v2: what changed and why

Exam v1's case C (committed through `5e88489`) joined two propositions:

- REQ-old stated a refund-request window ("accepted within 30 days of purchase").
- Its basis claim, its address facet ("How long may a refund take?") and the correction stated a
  refund-completion time ("must complete within … calendar days").

Replacing REQ-old was therefore not compelled. In the exam-v1 run
(`intent_graph_synthesis_schema_bound`, NOT CERTIFIED 21/24, unchanged), Astra named the
mismatch in all three case C attempts.

Exam v2 corrects case C only:

- REQ-old, its basis claim and the correction all state the refund-request window, and only
  the value changes (30 → 14 days of purchase).
- They share one address, whose facet is "Within how many days of purchase are refund requests
  accepted?".
- The old judgment is superseded, so REQ-old is stale.

Scorers, gates and the acceptance rule are unchanged. The historical v1 builder is kept, and a
regression pins its defect.

The exam hash covers:

- each case's world, as its full event ledger with incidental counters normalised;
- the whitespace-, comment- and docstring-insensitive AST closure of the builders, scorers,
  global gates, dispatch, attempt runner and verdict, together with every exam constant they
  read;
- the acceptance rule.

It is deterministic, and the offline tests show that changing any case, seeded datum, scorer,
shared helper, rule or verdict function changes it, while formatting changes do not.

## Results (24 fresh attempts; no credit carried from any earlier run)

| Case | Run 1 | Run 2 | Run 3 | What the model did |
|---|---|---|---|---|
| A NEW | PASS | PASS | PASS | one NEW REQUIREMENT grounded on the claim |
| B SAME THING | PASS | PASS | PASS | pure NO_CHANGE, witness `REQ-existing` only |
| C REAL CHANGE | PASS | PASS | PASS | exactly one REQUIREMENT `REPLACES_STALE` of `REQ-old`; REQ-old durably SUPERSEDED |
| D GAP | PASS | PASS | PASS | a gap on the competing claims; nothing invented |
| E INVISIBLE | PASS | PASS | PASS | NEW requirement; the hidden object is never cited |
| F STALE | PASS | PASS | PASS | `REPLACES_STALE` of `REQ-stale`; the stale object is not witnessed |
| G CONTRADICTION | PASS | PASS | PASS | CONTRADICTION gap on the NonGoal; the excluded node is not proposed |
| H MIXED | PASS | PASS | PASS | NEW payment requirement, and witness `REQ-existing` for the represented window |

- 24 answered, 0 INCOMPLETE, 0 failures.
- No context witnesses and no unlawful references to a retiring object.
- Tokens: 131,985 input and 11,338 output. Output high water 1,132 of 16,000 (the guard was
  non-binding). Median latency 8.6 s. Cost is unknown (not reported by the Responses API).

## Replay and binding (offline, providers disabled)

- **Ledger replay.** All 8 ledgers replay identically; attempt-1 routes reproduce, including
  C's single replacement and REQ-old SUPERSEDED.
- **Test suite.** The certification suite gives 345 passed and 86 skipped (live-only).
- **Historical records.** v1 and v2 records remain byte-identical, keep their verdicts and bind
  nothing under the exam-bound identity.

## Caveats

- The certificate covers exactly the bound identity. Grok 4.7 has no exam-v2 run (xAI credits),
  and no other model is covered.
- Case B's address facet ("How long may a refund take?") is shared by the default world builder
  and does not match its request-window claim. B passed 3/3 under every contestant and was
  outside this correction; it is covered by the exam hash, so any future fix is a new exam
  version.
