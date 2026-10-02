# Live End-to-End Intent Engine Validation v2: Design

**Status:** harness built and sealed offline. No live call has been made. The run starts only after a founder `role_binding.json` and green preflight gates.

**Predecessor:** `intent-engine-live-e2e-v1`, sealed verdict **FAIL** at `52fc54a`. It is frozen and untouched; v2 is a new lineage.

## 1. What v1 taught, and the only two changes

| v1 finding | v2 change |
|---|---|
| Six of seven founder decisions were lost: routing used the writer's concern labels. | The harness routes by **provenance** (`provenance-v1`): the step's ledger window plus its immutable evidence id. It never reads a label or any wording. Ambiguous or unexplained routing stops the run as NOT_VALIDATED. |
| Competing evidence written as a correction escaped the contradiction law: the retired claim is outside the v4 verifier's consistency context. | The verifier is **`ie2-semantic-admission-v5`**. Every proposed supersession target is shown separately and judged SUPPORTED_REPLACEMENT / CONFLICTING_EVIDENCE / UNCERTAIN. Conflicting evidence goes to the existing contradiction hold, and uncertain to the existing unresolved hold. |

## 2. What is unchanged from v1

- **Corpus and oracle:** the same Larkspur corpus (18 steps) and the same oracle meaning (24 truths). The T07 contradiction is expected open, with closure NOT CLOSED.
- **Scorer:** the same twelve-category scorer (`intent_engine_e2e.outcome`, byte-identical). It gains one structural rule in the v2 runner: a FAILED v5 completeness record must name recorded gaps.
- **Contracts:** the same writer contract (`intent-v2-locus-v7`), IE3 certificate (gpt-6-astra exam v6, runtime-v4) and adjudicator contract (`intent-engine-outcome-adjudication-v1`).
- **Run law:** EXPERIMENT mode with no retry, the same hidden-oracle isolation, and the same budgets (writer ≤ 36, verifier ≤ 18, IE3 1, adjudicator 1).

## 3. Offline preflight (all green before the seal)

**The live v1 shapes, under the v2 laws.** These are Grok's labels and the T07 handbook written as ASSERT plus SUPERSEDE, with a scripted v5 verifier judging that replacement CONFLICTING_EVIDENCE:
- all seven founder decisions land, or lawfully have nothing to decide (T12: `REFUSED (CORRECTION_DECLINED)`);
- exactly one open `CONTRADICTION` hold; the 2-day rule is current and the 3-day rule is not;
- result: **PASS** with 0 defects.

**Each failure is caught:**
- a blind v5 verifier;
- a routing stop (NOT_VALIDATED, with no IE3 and no oracle);
- a v5 silent gap.

**Oracle isolation** holds, each gate refuses its own defect, and **v1 is untouched**.
