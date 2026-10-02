# Live End-to-End Intent Engine Validation v1: Report

## Sealed experimental verdict: **FAIL**

This verdict was produced by the sealed scorer, unchanged. It is reproduced exactly by `integrity.py`, which re-scores the committed final state and adjudication. Nothing below changes it.

| Category | Count |
|---|---|
| MISSING_TRUTH | 4 (L4, F3, X3, X4) |
| INVENTED_TRUTH | 0 |
| WRONG_CURRENT_TRUTH | 0 |
| STALE_TRUTH | 5 (L1, F1, F2, X1, X2) |
| WRONG_CORRECTION_TARGET | 0 |
| CONTRADICTORY_CURRENT_TRUTHS | 0 |
| AUTHORITY_BYPASS | 0 |
| DECLINED_CHANGE_APPLIED | 0 |
| SILENT_GAP | 1 (R1/R2: the expected open contradiction was never a visible contradiction hold) |
| INCORRECT_GAP_RESOLUTION | 0 |
| IE2_IE3_SEMANTIC_MISMATCH | 3 (D1, L2, R1 current in IE2, not stated by IE3) |
| INCORRECT_CLOSURE | 1 (the expected open `CONTRADICTION` hold is absent) |

The adjudication covers the final state completely and with certainty: every reading is certain, there are no adjudication issues, and IE3 was evaluated.

## Run facts

**Run shape.** One canonical sequential run of 18 steps, in the sealed order, with none skipped or duplicated.

**Calls.** Every call stayed within the sealed budget, and no call errored. No step was refused.

| Role | Calls | Model | Contract | Input tokens | Output tokens |
|---|---|---|---|---|---|
| Writer | 36 / 36 | `xai/grok-4.6` (requested; canonical, no aliases, by metadata check) | `intent-v2-locus-v7` | 271,949 | 9,965 |
| Verifier | 18 / 18 | `openai/gpt-6-astra` (executed) | `ie2-semantic-admission-v4` | 20,568 | 2,805 |
| IE3 | 1 / 1 | `openai/gpt-6-astra` (executed) | `intent-graph-synthesis-runtime-v4`, certificate exam v6 | 6,513 | 2,248 |
| Adjudicator | 1 / 1 | `anthropic/claude-opus-5-5` (executed) | `intent-engine-outcome-adjudication-v1` | 4,916 | 1,557 |

Writer cost was 1.24 USD. Total wall clock was 1,824.6 s.

**Integrity** (`integrity.json`):
- Replay reproduces every step digest and the final state exactly.
- The re-score equals the sealed report.
- The seal and oracle are intact.
- No oracle text reached any model input. Three writer-authored proposition statements happen to equal oracle statements word for word, and they reached the verifier as the writer's own text. They are listed in `integrity.json`; none is a leak.

**Holds.** No runtime hold was created, resolved or left open.
- **Writer:** declared no conflicts.
- **Verifier:** returned COMPLETE + NO_CONFLICT for all 41 propositions.
- **T10 membership revision:** Grok preserved the under-25 fee, so no incompleteness occurred.

**Founder decisions** (preregistered, unchanged):

| Step | Decision | Outcome |
|---|---|---|
| T11 | AGREE | Delivered and applied |
| T03, T04, T06, T09 | AGREE | Not delivered: "0 pending correction sets at <concern>" |
| T05, T12 | DECLINE | Not delivered: "0 pending correction sets at <concern>" |

Eight correction sets remain PENDING, and none of their members is applied.

**Final state.**
- **IE2:** 15 current claims. All are faithful to an oracle truth, none is invented, and none contradicts another.
- **IE3:** 5 requirements, covering Membership and Opening hours only.
- **Closure:** NOT CLOSED, but blocked by other closure conditions, not by the expected contradiction hold.

## Diagnostic interpretation (post-run; not part of the sealed verdict)

### 1. Harness defect: founder decisions routed by concern label

Most defects trace to one root cause in the experiment harness, not in the Intent Engine runtime. `harness._decide` finds "the PENDING correction set at this concern" by exact equality between the address subject and the scenario's concern label.

**What Grok named the concerns** (the writer's own labels, which the scorer correctly ignores):
- "Tool loan", which also holds the deposit rules;
- "Late return";
- "Tool damage";
- "Tool reservation";
- "Library opening hours".

**What matched.** Only "Membership" matched, so only T11's AGREE was delivered. The other six preregistered decisions found nothing to decide.

**Downstream consequences.**
- Every other correction stayed PENDING. This accounts for all 4 missing and all 5 stale truths.
- Every concern with pending authority work is withheld from IE3's basis, which is a runtime law. IE3 was therefore shown only Membership and Opening hours, so D1, L2 and R1 never reached it (3 IE2→IE3 mismatches).

The offline preflight did not catch this, because its scripted writer used the scenario's labels exactly.

**Runtime safety held throughout.** No pending correction applied, no authority was bypassed, and no declined change became current. No invented, wrong or contradictory current truth appeared.

### 2. The T07 contradiction became pending authority work, not a contradiction hold

Grok proposed the handbook's 3-day hold as a correction: ASSERT the 3-day claim and SUPERSEDE the current 2-day claim. That made the change pending authority work.

**Why the verifier could not catch it.** A claim the response itself retires is excluded from the verifier's bounded context, by design (ADR §8). So the 2-day claim was never shown to Astra, and the v4 consistency backstop had nothing to compare against.

**Was the outcome safe?** Yes. The 3-day rule is not current and the 2-day rule is current. But the contradiction exists only as a PENDING correction set, never as the visible `CONTRADICTION` hold the oracle requires. Hence 1 SILENT_GAP and 1 INCORRECT_CLOSURE.

**Open question for the founder.** A contradiction between two sources can be misread by the writer as a correction. The correction is then still held for human authority, but it escapes the contradiction law. The question is whether that is an acceptable representation, or a residual risk to address. Grok treated "the board rejected" (T08) in the same way, as a correction of the then-current claim.

### 3. Classification

| Failure | Classification |
|---|---|
| Founder decisions not delivered | **Experiment-harness defect** (decision routing by label). Not provider or infrastructure, and not an IE runtime safety failure. |
| T07 as correction, not contradiction | **Semantic (writer) behaviour** meeting a **bounded-context design limit** (the documented residual risk). Safe, but not the sealed expected representation. |
| Provider or infrastructure failures | None. |

No repair, retry, rerun or substitution was made. Per the experiment law, this run stands as FAIL.
