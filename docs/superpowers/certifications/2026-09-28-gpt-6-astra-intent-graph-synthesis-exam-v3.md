# Certification: openai/gpt-6-astra for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v3, exam v3)

```
status:     CERTIFIED (PASS, 27/27) for the exact bound identity below only
standing:   CURRENT (graph_certificate_standing)
candidate:  openai/gpt-6-astra
tier:       REASONER (reasoning effort high, mode standard)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-28
evidence:   tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_exam_v3/
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
| exam | `ie3.intent-graph-synthesis.certification-exam`, version `3`, hash `72ca1102d0734900689d3e3260df988f57786494871fde8b73767df79a7331e8` |
| recorded, not bound | reasoning effort `high`, `max_output_tokens=16000`, `timeout_seconds=180` |
| frozen production base | `ecb3f700c3b7bc05d7f43904b415121d8362440f` (`src/` verified unmodified) |

The exam hash covers the case worlds, the scorers, the gates, the attempt runner, the verdict
function and the acceptance rule. Offline, altering any bound value (model, provider, task,
policy id, policy runtime-v2, prompt v2, canonical schema, the xAI wire, the compiler, exam v2's
hash or version, or the exam id) prevents binding.

## Results (27 fresh attempts)

| Case | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| A NEW | PASS | PASS | PASS |
| B SAME THING | PASS | PASS | PASS |
| C REAL CHANGE | PASS | PASS | PASS |
| D GAP | PASS | PASS | PASS |
| E INVISIBLE | PASS | PASS | PASS |
| F STALE | PASS | PASS (AMBIGUITY gap) | PASS |
| G CONTRADICTION | PASS | PASS | PASS |
| H MIXED | PASS | PASS | PASS |
| I KIND PAIR | PASS | PASS | PASS |

27 answered, 0 INCOMPLETE and 0 retries. Tokens: 158,517 input and 13,395 output; output high
water 1,387 of 16,000. Median latency 11.2 s; cost is not reported.

**Case I (REQUIREMENT versus CONSTRAINT).** In every run:

- The obligation became a **REQUIREMENT** with the statement "Refund processing must complete
  within thirty calendar days after approval." The rationale was a required delivery deadline,
  "rather than a solution-space constraint".
- The boundary became a **CONSTRAINT** with facet `PROJECT_BOUNDARY`, stating that
  refund-processing data must remain within approved UK-hosted infrastructure. The rationale was
  that it "restricts where refund-processing data may reside …; no external mandate or factual
  limitation is supplied".

Both claims read "must … within", so the kinds follow what each claim governs, not its wording.

## Caveat

Case F's world (unchanged since exam v2) shows its claim as the bare value "thirty days after
purchase" under the facet "How long may a refund take?", beside a stale request-window
requirement. That is the representation weakness corrected in case A. Astra resolved it lawfully
(two replacements and one honest AMBIGUITY gap, which the scorer accepts). The verdict follows
the frozen rule and is unaffected.
