# Live End-to-End Intent Engine Validation v1: Design

**Status:** harness built and sealed offline. No live call has been made. The run starts only after the founder writes `role_binding.json` and every preflight gate passes.

**Question.** After realistic requirements and changes over time, does Foundry end with the correct canonical understanding of what must become true?

This is a whole-system validation. It is not a certification, an exam or a repeatability study.

## 1. System under test

The architecture is frozen at `d229bca`, with no change.

**IE2:**
- G2 governed-concern grain;
- Call 1 binding;
- Call 2 `intent-v2-locus-v7`, with proposition accounting and writer conflict declarations;
- the semantic admission verifier `ie2-semantic-admission-v4` (completeness and independent contradiction backstops);
- runtime holds `ie2-runtime-holds-v1`;
- atomic correction sets;
- authority routing v2;
- gap resolution;
- closure.

**IE3:** the current graph certificate, `openai/gpt-6-astra` exam v6 on `intent-graph-synthesis-runtime-v4`. It runs once, on the settled IE2 state.

**Mode:** `ExecutionMode.EXPERIMENT`. In this mode the runtime never invokes the PRODUCTION-only bounded structural re-proposal, so the run has no retry of any kind.

## 2. Corpus and run shape

The corpus is the held-out Larkspur Tool Library: 18 ordered steps, run once and sequentially. The founder's decisions are preregistered: AGREE ×6 and DECLINE ×2.

The corpus covers:
- **Initial specification:** a dense six-section spec, with related rules spread across sections and similar wording across distinct concerns.
- **Restatement and new information:** a restatement (T02), and ordinary new information on a new concern (T13).
- **Corrections:**
  - 1:1 (T03), approved;
  - N:1 (T04), approved;
  - 1:N (T05), declined;
  - N:M (T06), approved;
  - a changed correction (T09).
- **Contradiction:** the handbook (T07) contradicts the spec and stays unresolved.
- **Rejected and repeated changes:** a board-rejected change (T08). The declined change proposed again (T12) is refused by the runtime as already declined.
- **Incomplete proposal:** a revision prone to losing meaning (T10), re-sent (T11).

Whether the live writer actually loses meaning at T10, or misses the T07 conflict, is the model's behaviour. The final truth is the same either way, and both paths are proven offline.

## 3. Roles

| Role | Requirement | Status at the seal |
|---|---|---|
| Writer | `XAIConflictSemanticReasoner`, policy v7, xAI SDK | candidate `xai/grok-4.6`: eligible, unvalidated (v7 never ran live; Call-2 policies have no certification) |
| Verifier | exactly `ADMISSION_V4_CONTRACT`, independent of the writer | **blocked**: no model is certified for it (an experiment-scoped founder authorization is required) |
| IE3 | the v6 certificate identity | certified |
| Adjudicator | task EVALUATION; a model other than the writer, verifier and IE3 | **blocked**: EVALUATION has no certification (an experiment-scoped founder authorization is required) |

## 4. Oracle and scoring

The hidden oracle is in `oracle.json`, and the manifest holds it only by digest. It states meaning, not wording: 24 truths, each CURRENT / RETIRED / NEVER / HELD.
- **The T07 contradiction must end unresolved.** A visible OPEN `CONTRADICTION` hold must name the current 2-day claim, the 3-day side must never be current, and closure must stay NOT CLOSED.
- **Who sees the oracle.** The writer, verifier and IE3 never see it. The adjudicator receives it, with the final IE2/IE3 state, only after IE3 has run.

Twelve defect categories are scored on final state only:
- missing, invented, wrong current or stale truth;
- wrong correction target;
- contradictory current truths;
- authority bypass;
- declined change applied;
- silent gap;
- incorrect gap resolution;
- IE2→IE3 semantic mismatch;
- incorrect closure.

Wording, decomposition, claim count, concern labels, notes and explanations are never scored.

**PASS** requires zero defects, IE3 evaluated, and a complete, certain adjudication. An uncertain, malformed, uncovering or failed adjudication is **NOT_VALIDATED**. Human review is diagnostic only.

## 5. Offline preflight (all green before the seal)

- **Oracle isolation:** the oracle never reaches the writer, verifier or IE3, and is loaded only after IE3, for the adjudicator alone.
- **Faithful scripted run:** PASS.
- **Harmless variation:** renamed predicates and a re-split decomposition still PASS.
- **Expected open contradiction:** not scored as contradictory-current-truth.
- **Faults:** missing, invented, stale, accepted contradiction, authority bypass, declined change applied, silent gap, incorrect gap resolution, IE3 mismatch and false closure are each detected.
- **Adjudication failures:** uncovered, uncertain or failed adjudication is NOT_VALIDATED.
- **Gates:** each preflight gate refuses its defect.

## 6. Budget

- Writer ≤ 36 calls (2 per step), cost ≤ 25 USD.
- Verifier ≤ 18 calls.
- IE3: 1 call.
- Adjudicator: 1 call.

A call beyond budget is refused before it reaches a provider, and the refusal is recorded.
