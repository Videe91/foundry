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

## 6. Architecture questions from round 1

Q1, Q2, Q4 and Q5 were decided by the founder and implemented in round 2 (§7).

Q3 is decided for the future live run, but nothing was run:

- one independent `OutcomeAdjudicator`;
- evaluation only, with no production authority;
- it sees the final state plus the judge-only truths;
- a failed, uncovering or uncertain mapping is `NOT_VALIDATED`, never PASS;
- post-run human review is diagnostic only.

`outcome.evaluate` and `score` implement this law. No adjudicator model was selected or called.

## 7. Round 2 decisions (2026-10-02)

These close Q1, Q2, Q4 and Q5 of §6. Holds are recorded as `SemanticHoldGap`, under the deterministic protocol `ie2-runtime-holds-v1`. A `SemanticHoldGap` is an ordinary blocking gap that also carries:

- `cause`;
- `basis`, the (address, source-sentence sha256) pairs held;
- `resolution_key`;
- the held proposition and judgment ids;
- `conflicting_claim_ids`.

No new `GapKind` was added: `GapKind` belongs to sealed model-facing IE3 and baseline schemas.

1. **Explicit contradictions (Q1).**
   - **New Call-2 identity `intent-v2-locus-v7`.** It is v6 plus one instruction section and one output field: `conflicts`, each naming a proposition and *either* a known current claim *or* a sibling proposition. v6 and every earlier identity stay byte-identical.
   - **The held side.** A conflicting proposition is held with its minimal safe unit. Sibling conflicts join one group, and correction sets stay atomic. This is recorded as one blocking `CONTRADICTION` gap. The current claim stays current, and nothing picks a winner.
   - **No approval work.** The held judgments are never recorded, so no correction-approval work exists for them.
   - **Resolution.** The gap closes only when a later lawful change applies a claim at that concern and no named conflicting claim is current any more. In practice that means an AGREED correction. Restating the current side decides nothing; a human waiver keeps it.
2. **Cause-specific resolution (Q2, Q4 recovery).**
   - **Which gaps.** This applies only to Foundry-made holds. No other gap is touched.
   - **When it closes.** A completeness or availability hold closes, with `GAP_RESOLVED`, when a later response delivers its whole basis: the same source sentences at the same concerns, verified COMPLETE, with every judgment admitted (pending authority counts; refused does not count).
   - **The key.** `resolution_key = HOLD-sha256(project, gap kind, sorted basis)`. It contains no invocation or event id.
   - **What does not close it.** Unrelated, changed or other-concern evidence never closes it.
   - **Replay.** Replay reads the event and never recomputes it.
3. **Verifier unavailable (Q4).**
   - **Translation.** The v3 adapter maps "no certified model", "provider not installed" and "provider failure" to the port's `VerifierUnavailable`.
   - **What is recorded.** The whole response is held as `VERIFICATION_UNAVAILABLE` (kind `CONTEXT_FAILURE`). Nothing applies. No completeness record is written, because no verdict exists.
   - **Unchanged.** A contract-breaking answer is still invalid output, as before.
4. **Smallest safe scope (Q5).**
   - **What a gap names.** `affected_object_ids` lists the concern addresses the held judgments touch, plus the conflicting claims. A whole-response hold names every touched concern. It is `()` only when nothing can be localised.
   - **Closure.** Project closure stays false while any blocking hold is open. IE2 work on other concerns keeps applying.

**Larkspur, offline, round 2.**
- **Final state.** With a faithful scripted writer and verifier, the final state has 0 defects (`CONTRADICTORY_CURRENT_TRUTHS` 0, `INCORRECT_CLOSURE` 0). The verdict is `INCOMPLETE` only because IE3 is not run offline.
- **Expectation change.** The T07 handbook truth (R2) is now `HELD` (never current) instead of `CONTESTED`. The project must end with exactly one open blocking `CONTRADICTION` gap, so closure stays false. The round-1 expectation (both sides current, contradiction "explicit") encoded the outcome Q1 now forbids.
- **The T10 completeness gap** closes when T11 delivers the same sentence complete.

## 8. Independent contradiction backstop (round 3)

**The hole.** Contradiction safety depended on the writer declaring the conflict.

RED at `a119d0f`:
- The current claim is "refunds within 14 days". A new source says 30 days.
- The writer declares nothing, and the v3 verifier judges completeness only.
- Result: `{'refund_window': '14 days', 'refund_window_new': '30 days'}` were both current.

**The contract.** New verifier contract `ie2-semantic-admission-v4`, bound as `ADMISSION_V4_CONTRACT`. v1–v3 are unchanged, and exact contract routing still applies.

**The request (`AdmissionRequest`).** It is the v3 request plus `current_claims`, each given as claim_id, subject, predicate and value. The context is bounded:
- only claims currently true at the concerns the response's judgments touch;
- never a claim the response itself retires;
- never another concern's claim.

**The answer.** Per proposition, the verifier returns:
- `completeness`: COMPLETE / NOT_COMPLETE;
- `consistency`: NO_CONFLICT / CONFLICT / UNCERTAIN;
- `conflicting_claim_ids`: present exactly when CONFLICT, distinct;
- `note`: never read by any rule.

**Deterministic checks (ids only).** Every proposition is judged once. Every named claim must have been shown and still be current. A v4 report answers only an `AdmissionRequest`, and vice versa. Anything else is invalid output, and the whole response is held.

**The law.** Only COMPLETE + NO_CONFLICT proceeds.
- NOT_COMPLETE follows the completeness-hold law.
- CONFLICT becomes the existing `CONTRADICTION` hold. A unit flagged by both the writer (locus-v7) and the verifier gets one gap, carrying the union of the named claims.
- UNCERTAIN becomes an `AMBIGUITY` hold (cause `UNCERTAIN`). It is never applied and resolves by later clean delivery.

Correction sets stay atomic. Unavailable stays `VERIFICATION_UNAVAILABLE` and is never treated as UNCERTAIN. Resolution and replay reuse the round-2 laws unchanged.

**Larkspur.** With the writer missing the T07 conflict and the verifier catching it: 0 defects, and exactly one contradiction gap.
