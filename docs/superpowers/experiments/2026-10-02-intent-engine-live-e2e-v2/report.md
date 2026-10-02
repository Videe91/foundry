# Live End-to-End Intent Engine Validation v2: Report

## Sealed experimental verdict: **FAIL**

This verdict comes from the sealed v2 scorer: the unchanged twelve-category scorer plus the v2 runner's v5 silent-gap rule. `integrity.py` reproduces it exactly by re-scoring the committed final state and adjudication. Nothing below changes it.

| Category | Count |
|---|---|
| MISSING_TRUTH | 6 (M4, M5, L4, F3, X3, X4) |
| INVENTED_TRUTH | 0 |
| WRONG_CURRENT_TRUTH | 0 |
| STALE_TRUTH | 6 (M2, L1, F1, F2, X1, X2) |
| WRONG_CORRECTION_TARGET | 0 |
| CONTRADICTORY_CURRENT_TRUTHS | 0 |
| AUTHORITY_BYPASS | 0 |
| DECLINED_CHANGE_APPLIED | 0 |
| SILENT_GAP | 0 |
| INCORRECT_GAP_RESOLUTION | 0 |
| IE2_IE3_SEMANTIC_MISMATCH | 6 (IE3 faithfully states the six stale rules) |
| INCORRECT_CLOSURE | 1 (10 open contradiction holds; 1 expected) |

There was no routing stop. The adjudication is complete and certain: 49 claim, 14 graph and 0 gap readings, all certain.

## Run facts

**Run shape.** One canonical sequential run of 18 steps, in the sealed order. Every call stayed within budget and none errored.

| Role | Calls | Model | Contract | Input tokens | Output tokens |
|---|---|---|---|---|---|
| Writer | 36 / 36 | `xai/grok-4.6` (canonical, no aliases) | `intent-v2-locus-v7` | 269,857 | 10,176 |
| Verifier | 18 / 18 | `openai/gpt-6-astra` (executed) | `ie2-semantic-admission-v5` | 25,166 | 4,294 |
| IE3 | 1 / 1 | `openai/gpt-6-astra` (executed) | `intent-graph-synthesis-runtime-v4`, certificate exam v6 | 9,609 | 4,530 |
| Adjudicator | 1 / 1 | `anthropic/claude-opus-5-5` (executed) | `intent-engine-outcome-adjudication-v1` | 5,485 | 2,007 |

Writer cost was 1.27 USD. Total wall clock was 1,884.7 s.

**Integrity** (`integrity.json`):
- Replay reproduces every step digest and the final state.
- Re-scoring equals the sealed report.
- The seal and oracle are intact.
- No oracle text reached any model input. Three writer-authored statements equal oracle statements word for word, as in v1; they are recorded and are not leaks.

**Founder decisions.** All seven were routed by provenance (`provenance-v1`). There was no ambiguity and nothing unexplained.

| Steps | Outcome |
|---|---|
| T03, T04, T05, T06, T09, T11, T12 | `NO_WORK: HELD (CONFLICT)`. Each step's own work was held as a contradiction, so no correction set existed to decide. |

**Holds.**
- 10 runtime holds, all `CONTRADICTION` / CONFLICT, all OPEN. One arose at each correction step, plus T07 (the expected one) and T08.
- No hold was resolved.
- No correction set was ever created.
- The writer declared no conflicts. The verifier judged all 11 proposed replacements **CONFLICTING_EVIDENCE**.

**Final state.**
- **IE2:** 14 current claims, faithful to M1–M3, L1–L2, F1–F2, D1, X1–X2, R1 and O1–O2, with nothing retired. No contradiction is current. The 3-day rule is not current and the 2-day rule is.
- **IE3:** 14 requirements, faithful to that IE2 state, including its six stale rules.
- **Closure:** NOT CLOSED, with 10 blocking holds.

## Diagnostic interpretation (post-run; not part of the sealed verdict)

### 1. What happened

Every correction step was held as a contradiction. Grok wrote each founder revision correctly, as ASSERT plus SUPERSEDE: T03 "lent for 14 days" replacing 7, T04 the late-return rule, T06 the damage rules, T11 the fee, and so on.

The v5 verifier was shown, for each replacement, only:
- the new source sentences;
- the claim to be replaced.

For each one it answered CONFLICTING_EVIDENCE, with a note such as "the source states a competing duration but does not establish that it updates or replaces the 7-day duration".

The runtime then did exactly what the sealed v5 law requires: it held each one as a visible contradiction, kept the old rule current, and opened no correction work.

### 2. Why: a real Intent Engine contract gap, not model failure or infrastructure

`AdmissionRequestV5` omits the strongest structural sign of a correction: **evidence lineage**. Each revision document supersedes the founder's earlier version of the same document, the one that established the old claim (`supersedes_evidence_id` on the evidence item). The verifier never sees that.

Given only the text, "Tools are lent for 14 days" does not itself say it replaces 7 days. Under its instruction ("CONFLICTING_EVIDENCE: … nothing in it establishes that it amends or replaces that claim"), Astra's judgement was faithful. The T07 handbook, which is a different artifact and revises nothing, was judged the same way. That is correct for T07, but nothing in the request let the verifier tell the two cases apart.

The offline preflight did not reveal this. Its scripted verifier judged by content, not by whether the request contains replacement evidence.

### 3. Safety

The failure was safe:
- no invented, wrong or contradictory truth became current;
- no authority was bypassed;
- no declined change was applied;
- no gap was silent or wrongly resolved.

It over-blocked: lawful founder corrections never reached founder authority.

### 4. Classification

| Item | Classification |
|---|---|
| Overall | **Real Intent Engine problem.** The v5 replacement contract withholds evidence lineage, so genuine revisions cannot be told apart from competing sources. The failure was safe. |
| Experiment infrastructure | No failure. Provenance routing worked; every decision was routed and lawfully had nothing to decide. |
| Model variability | Not the cause. Astra's 11 judgements were consistent with its contract. |
| Provider or infrastructure | None. |

No repair, retry, rerun or substitution was made. This run stands as FAIL.
