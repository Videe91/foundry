# Certification record: openai/gpt-6-astra for INTENT_GRAPH_SYNTHESIS (IE3, runtime-v4, exam v6)

```
status:     CERTIFIED (33/33): 0 semantic failures, 0 protocol failures, 0 INCOMPLETE
standing:   CURRENT (graph_certificate_standing)
candidate:  openai/gpt-6-astra (REASONER, reasoning effort high, mode standard; output guard 16000, timeout 180 s)
            provider metadata before the run: id gpt-6-astra, owned_by system (no alias)
task:       INTENT_GRAPH_SYNTHESIS
date:       2026-09-29
evidence:   tests/certification/evidence/openai/gpt-6-astra/intent_graph_synthesis_exam_v6/
identity:   ie3-graph-certification.v3; intent-synthesis.graph-v1 / runtime-v4;
            prompt fd395605…; canonical 6b64d274…; wire 7b825730…
            (foundry.openai-structured-outputs.v1); exam v6 818f6f87…;
            frozen production base 0b8f077 (root Intent staleness boundary, IE3 §17.2)
```

One complete, independent sitting. Every call was single-shot, and the adapter sets `max_retries=0`. There was no re-proposal, repair, retry, prompt change or scorer change.

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
| K ROOT LIFECYCLE | PASS | PASS | PASS |

**Case K (root lifecycle).** In every attempt the request showed the PROPOSED root `INT-619188ae…` fresh (`is_stale = false`, not in `root_intent_ids`) and the Requirement `REQ-f16b72fc…` stale, with only the corrected claim live. Each answer was:
- exactly one `REPLACES_STALE` REQUIREMENT of `REQ-f16b72fc…`, stating the fourteen-day window;
- `DERIVED_FROM` the corrected claim `CLAIM-4127c02f…`;
- `SERVES` the existing root;
- no Intent node, no witness and no gap.

Afterwards, the root was unchanged and the only Intent. It was not stale in the bounded view, while still stale in the raw semantic plane, as designed. It kept its provenance edge to the superseded claim. The old Requirement was retired and replaced. The mission wording was not scored.

**Gaps.** 9 in all, every one required: a CONTRADICTION in each D, G and J attempt. There were none elsewhere, and none about the root in K.

**Measurements.** 208,215 input and 13,816 output tokens. OpenAI does not report cost, and none is estimated. Median latency 10.4 s, maximum 15.0 s; output high water 713 of 16,000.

**Supersedes** Astra's exam-v5 certificate. That record is unchanged and reads `SUPERSEDED`.
