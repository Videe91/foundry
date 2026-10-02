# Intent Engine Runtime Reset: Decision Record

**Status:** implemented 2026-10-02 (policy `ie2-semantic-completeness-v3`). No live model call was made. No model was certified. Nothing was activated in production. The 16-turn experiment was not rerun.

**Decided by:** the founder ("FOUNDER ARCHITECTURE DECISION / Intent Engine Runtime Reset"), after the architecture-reset audit.

**Amends:** `2026-09-30-ie2-semantic-completeness-design.md`. A v3 FAIL no longer refuses the whole Call-2 response. v1 and v2 keep their all-or-nothing law and stay replayable.

## 1. Why

The certification loop is frozen. Free-text exams v2–v5 and structured exam v1 were all NOT CERTIFIED, and their evidence is untouched. Two kinds of variation kept failing them:

- **Normal model variability.** The wording of findings, how propositions are decomposed, and how explanations are phrased.
- **Rigid response handling.** One incomplete proposition discarded every correct one.

Neither of these is a defect in the final understanding. The runtime should tolerate the first and stop amplifying the second, while staying fail-safe.

## 2. Decision

1. **Verifier contract v3.** For each proposition the verifier returns `{proposition_id, verdict: COMPLETE | NOT_COMPLETE, note?}`.
   - Its instruction is pinned by `VERDICT_COMPLETENESS_SYSTEM_INSTRUCTION_SHA256`.
   - It is bound as `COMPLETENESS_V3_CONTRACT` through exact contract routing. A model registered only for v1 or v2 is never asked.
   - **No rule ever reads the note.**
2. **Deterministic code checks shape only.**
   - The report validates against the schema.
   - Every proposition is judged exactly once, and every id is known.
   - The format matches the policy.
   - The verifier is independent of the writer.

   The code interprets no meaning.
3. **NOT_COMPLETE is a gap, not a refusal.** Each NOT_COMPLETE proposition holds its *minimal safe unit* (§3). That unit becomes:
   - one durable `GAP_RECORDED` of kind `WORKER_DIVERGENCE`;
   - HIGH materiality and risk, blocking, project-wide;
   - a description naming the reason, the invocation, the verification, the propositions and the held judgments. It never includes the note.

   Held judgments are never recorded. So a held correction creates no correction set and no authority work. Everything else in the response is admitted unchanged.
4. **Invalid verifier output fails safe.** This covers:
   - a missing or unparseable report, a wrong format or a cardinality error (`VERIFIER_OUTPUT_INVALID`);
   - a dependent verifier (`VERIFIER_NOT_INDEPENDENT`).

   In each case the whole response is held as one gap.
5. **One verifier, no semantic retry.** Exactly one Call 3 is made per Call 2.
6. **Replay uses the record.** `CompletenessRecord` gains `held_proposition_ids` and `gap_ids`. Replay never recomputes an outcome and never calls a verifier.

## 3. The minimal safe unit

`domain/completeness_units.py` defines the minimal safe unit. It is the union-find closure, over the response's judgments, of two links:

- **Same proposition.** A proposition expressed by several claims is kept or lost together.
- **Same correction set** (`form_correction_sets`). A correcting assertion is never applied without the retirement it depends on, and the reverse also holds.

No other link can arise within one response, because admission refuses references to unknown state. A unit applies only if every proposition in it is COMPLETE. Correction sets therefore stay atomic.

## 4. Evidence

All of this was offline, with no model calls.

| Item | Result |
|---|---|
| RED before implementation | contract: `ImportError`. Pipeline: 13 failed, 2 passed (the two COMPLETE cases). |
| `tests/unit/test_semantic_completeness_v3.py` | 9 passed |
| `tests/unit/test_semantic_completeness_v3_pipeline.py` | 16 passed |

The 16 pipeline tests cover K-CREDIT, COMPLETE, note variability, partial response, correction set, invalid output (six shapes), no retry, and replay.

The runtime-safety mutation slice `rts` killed 9 of 9 mutants:

- NOT_COMPLETE applies;
- gap not created;
- closure ignores an open gap;
- correction set partially applies;
- authority work for an incomplete correction;
- malformed answer treated as complete;
- replay recomputes;
- note affects the result;
- wrong contract accepted.

## 5. End-to-end validation (built, not run live)

The end-to-end validation lives in `src/foundry/experiments/intent_engine_e2e/`. It uses a new held-out domain, the Larkspur Tool Library: 16 steps that cover:

- a dense six-section spec;
- a restatement;
- corrections 1:1, N:1, 1:N (declined) and N:M;
- a cross-source contradiction;
- a correction the board rejected;
- a correction changed again;
- an incomplete proposal that the verifier holds and that is later re-sent complete and approved.

**How it is scored.** `expectations.py` is judge-only. `outcome.py` scores **final outcomes only**:

- missing, invented, wrong or stale truth;
- wrong correction target;
- implicit contradictory current truths;
- authority bypassed;
- declined change applied;
- silent gap;
- IE3 inconsistent with IE2;
- incorrect closure.

Which claim states which truth is an adjudicator's answer (the `OutcomeAdjudicator` port). It is never text matching. An adjudication that does not cover the state exactly is refused. When IE3 is not evaluated, the verdict is at best `INCOMPLETE`, never `PASS`.

**Offline result.** The writer, verifier and adjudicator were scripted and faithful. Every truth, correction, decline and authority outcome comes out right. Two defects remain, and both are runtime gaps rather than harness errors (§6 Q1, Q2):

- `CONTRADICTORY_CURRENT_TRUTHS` (R1/R2);
- `INCORRECT_CLOSURE` (the held T10 gap stays open).

The e2e tests: 28 for the scorer plus 24 for the harness. The `e2e` mutation slice killed 10 of 10 mutants.

## 6. Open architecture questions (not decided here)

- **Q1. Cross-source contradiction.** Proposition accounting has no disposition for "contradicts an existing claim". A `CONFLICTS_WITH` judgment cannot name a claim asserted in the same response. As a result, a faithful writer leaves two contradictory current claims, and nothing makes the contradiction explicit.
- **Q2. Closing a completeness gap.** `WORKER_DIVERGENCE` gaps route only to `RECONCILE`. No application path records `GAP_RESOLVED`, and `GAP_RESOLVED` has no authority gate. When the held proposal later arrives complete, the gap still blocks closure for ever.
- **Q3. Adjudication method.** Who adjudicates the final state in a live run: a human, an independent model behind the port, or both? This is unresolved.
- **Q4. Unreachable verifier.** A verifier that cannot be reached (for example, a wrong contract) makes `ModelUnavailableError` propagate before any record exists. Nothing is applied, but no gap is recorded either. The e2e harness scores this as `SILENT_GAP`.
- **Q5. Gap granularity.** v3 gaps are project-wide (`affected_object_ids=()`). This blocks all closure in the project, not only the affected concern.
