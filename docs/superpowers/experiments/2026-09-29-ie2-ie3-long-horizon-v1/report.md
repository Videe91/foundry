# IE2 + IE3 Long-Horizon Experiment v1 — Report

**Standing: `LONG_HORIZON_IE2_IE3_NOT_VALIDATED`.**
- **Mechanical:** 2/34 check-sets pass (RUN-INTEGRITY and SOURCE-COVERAGE).
- **Independent adjudication:** IE2 15/44 YES, IE3 19/26 YES.
- **First divergence:** T1, IE2 (concern formation).

**Limitation.** The Orion corpus lacks an authoritative mission statement. This experiment therefore tests long-horizon evolution of evidence-grounded graph state beneath a single model-proposed stable Intent root. It does not test the semantic correctness of the root's natural-language mission wording.

## Lineage

| Commit | Content |
|---|---|
| `71cdac9` | Harness |
| `9559940` | Seal (exactly `manifest.json` + `expectations.json`) |
| `a3ff1ee` | Raw run (`preflight.json`, `run.json`) |
| This commit | Evaluation, 70 packets, answers, verdicts, this report |

**Corpus:** the 9P3 corpus byte for byte (192 items; structural digest `50b83eea…`).

## Run

- **Scope:** 16/16 turns completed in one walk, with no reset.
- **IE2:** 32 calls, grok-4.6 `intent-v2-locus-v5`, EXPERIMENT mode. Known cost 4.15 USD; 661,998 input and 123,045 output tokens; median call 130 s, maximum 285 s.
- **IE3:** 16 calls, gpt-6-astra runtime-v4, exam-v6 certificate CURRENT, EXPERIMENT mode. 236,050 input and 39,309 output tokens; cost not reported by OpenAI; median 33 s, maximum 133 s (T1).
- **Authority:** 10 human AGREEs.
- **Wall time:** 5,501 s.
- **Integrity:** the final ledger replays exactly.

## What failed, in causal order

1. **T1 — IE2 concern formation (model/policy).** grok-4.6 formed 9 addresses for 12 governed concerns:
   - "Job execution attempts" held A (attempts), B (retry delay) and C (timeout);
   - "Worker lease on a job" held F (lease) and G (renewal).

   The v5 grain rule (one address per governed concern) did not hold at this scale: 12 sections and 74 sentences in one delta. Validation v5 never presented that. Every later check at A/B/C and F/G is contaminated by this merge.

2. **T8 to T12 — IE2 structural refusal, repeated five times (architecture: accounting contract).**
   - At the T8 revert, the model had to retire the three exponential-backoff claims asserted at T5 and restore a two-rule fixed wait.
   - `VALID_DISPOSITIONS` allows at most one SUPERSEDE per proposition ((ASSERT, SUPERSEDE)). The model's answer (ASSERT, SUPERSEDE, SUPERSEDE on one proposition) was refused.
   - EXPERIMENT mode gives one attempt, so the revert never happened. The B section stayed the same at T9 to T12, the model made the same attempt each time, and it was refused each time.

   Consequences:
   - **C09 (T9)** never reached claim assimilation, so H-4 and H-5 were never stated.
   - **The T10 D and T12 G corrections** were lost, because each whole Call 2 was refused.

   A legitimate transition (N old claims replaced by M < N new propositions) is not expressible under the current contract.

3. **T13 — pending governance outside a checkpoint (experiment protocol, inherited from 9P3).**
   - The model finally proposed the B, D and F/G supersessions at T13, which is not an authority checkpoint.
   - The 9P3 protocol relays an AGREE only at checkpoints and only for pre-T eligible targets. These stayed pending to the end: NOT_ELIGIBLE at T14 and T16.
   - The IE3 context compiler excludes loci with pending judgments, so the affected claims were never shown to IE3 (UNCOVERED from T13).

4. **IE3's own findings:**
   - One duplicate at T1: two REQUIREMENTs derive from one claim at the merged F/G address.
   - Fidelity misses found by adjudication: T1 B dropped "exactly" and the measurement point; T1 D left D-3 unexpressed; T5 B dropped the measurement point.
   - Every other IE3 failure, at T6 and T8 to T16, is downstream of the IE2 state it was given.

5. **Scorer defect (reported, not patched after the run).** On a turn whose Call 2 is refused, `assimilate_delta` raises, so the harness records no Call 1 decisions. The evaluator therefore reports `MISSING_BIND` for items Call 1 did bind: at T8, Call 1 applied 9 bind judgments covering all 12 items. It does not change the standing, because those turns already fail on the recorded refusal.

## What held

- **Root lifecycle, all 16 turns:**
  - one PROPOSED model-authored Intent (`INT-7a46e400…`);
  - never a second root, a replacement or a root gap;
  - provenance edges unchanged;
  - never stale in the bounded view.

  At T16 the root's grounding claim (locus I, automatic dead-lettering) was corrected. The root became stale on the raw plane and stayed current in the bounded view, as IE3 §17.2 requires.
- **Correct governed corrections:**
  - T3 A, T5 B and T7 F: IE2 superseded the eligible claims, the architect AGREEd, and IE3 replaced the stale objects under the same root.
  - T14 J and T16 I: fully correct at both layers.
- **Restatements** at T2 C, T4 (no-op), T6 A, T11 L and T15 F were handled with supports and witnesses. The only exceptions were the extra claims counted at the merged addresses and one extra J claim at T6.

## Historical comparison (9P3, frozen, never rescored)

- **F:** 14/15, failed C09. It stated the compatible extension at a new address instead of the designated H address.
- **A:** 14/15, failed C09. It bound T9 to H and supported the existing claim, but never asserted the new repeated-cancellation meaning.
- **R:** 1/15. It diverged from C03 because obsolete meanings stayed concurrently current.
- **This run:**
  - it failed at C09 too, but for a different reason: an accounting-contract refusal inherited from T8, not a concern or claim error at T9;
  - it failed earlier, at T1 concern formation, which 9P3's persistent arms passed (12 designated roots).

This is not a model benchmark: the architecture, contracts and components have all changed.

The current architecture does **not** solve the historical long-horizon failure. It moves the failure: to T1 concern formation at scale, to an accounting contract that cannot express a many-to-fewer correction, and to governance that stays pending outside the checkpoint schedule.
