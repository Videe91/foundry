# Locus Policy Validation v6: Design

**Identity:** `intent-v2-locus-validation-v6`. It is new and single-use, and it does not mutate validation v5.

**Status:** sealed before any live call. This design and its seal stop before live execution.

**Purpose:** to validate concern formation, proposition completeness and the correction lifecycle under the current IE2 architecture.

**Grain law:** G2 as clarified by the founder on 2026-09-30 (`2026-09-30-ie2-governed-concern-grain-clarification.md`).

## 1. What is under test

| Component | Identity |
|---|---|
| Policy | `intent-v2-locus-v6` (`XAICorrectionSetSemanticReasoner`), unchanged and byte-identical |
| Prompt | `13aa8774…` |
| Output contract | `AccountedDraftPayload` `921171df…` |
| Correction law | `TARGET_SET` |
| Model | xAI `grok-4.6`, reasoning effort `high` |
| Execution | `ExecutionMode.EXPERIMENT`: one attempt per semantic call, never a re-proposal |

**Admission.** `AdmissionPolicy(canonical_facets=True, correction_sets=True)`, in every governor of this validation and nowhere else. Production and historical configurations are unchanged.

**What is exercised:**
- the G2 grain;
- canonical facets (`Rules governing <subject>`; the model authors no facet);
- source and proposition accounting, with every existing refusal law;
- N:M correction cardinality;
- authority routing (`list_authority_work`);
- atomic correction-set authority (`ie2-authority-routing-v2`): AGREE, DECLINE, and repeat suppression after a DECLINE.

**What is not tested and not changed:** IE3; the model contract; any production activation of correction sets.

## 2. Ledgers and budget

**Six fresh ledgers.**

| Ledger | Content | Calls |
|---|---|---|
| `core` | v5 texts, byte for byte: C0–C6, U2, U3 | 4 |
| `orion` | v5 texts: C09, the 9P3 locus H bytes | 4 |
| `jobs` | v5 texts: U1 | 4 |
| `conflict` | v5 texts: C5; T1 is written by the seed author | 2 |
| `large` | v5 texts: C8, U4 | 4 |
| `dense` | the new held-out domain | 8 (T1, T2, and T3 in each of two branches) |

**Budget:** 26 frontier calls, 0 retries, 0 judge calls, 8 USD ceiling. The v5 texts carry new evidence ids (`EV-LV6-`).

**Carried v5 regressions under correction sets.** C4's correction (30 kg to 25 kg) becomes one PENDING correction set: its correcting claim is held, not live, and it is never decided. Every other v5 expectation is unchanged.

## 3. The dense held-out domain

**Source.** A car-sharing service specification ("Kestrel"): 15 T1 sections, 8,084 characters, 92 sentences and 49 propositions. Nearby rules share actors and nouns: member, vehicle, reservation, fee, app, card. The domain is not Orion, and no Orion label is used.

**The G2 answer key: 9 governed concerns**, derived from the grain law, never from section count.

| Concern | Sections | Why one concern (claims at one address) |
|---|---|---|
| RESERVATION | 1 reservations, 2 no-show, 3 prolonging | window, length, limit, hold, expiry, and adding time (renewal timing, precondition, effect) of one reservation: the lease shape |
| UNLOCK | 4 unlocking, 5 wait between attempts, 6 unlock timeout | attempt limit, retry wait and timeout-as-failure of one unlock act: the execution-attempt shape |
| LATE-FEE | 7 late return, 8 fault waiver | charge, grace, rate, cap and exception of one entitlement |
| SERVICE-CREDIT | 10 vehicle not available, 11 claiming the credit | amount, destination and request deadline of one entitlement: the C6 shape across two sections |
| CLEANING-FEE | 9 | a different entitlement from LATE-FEE (the G5 precedent) |
| BILLING-RUN | 12 | the collection operation, not the fees it collects (the G6 precedent) |
| SUSPENSION | 13 | a decision triggered by billing outcomes, not billing itself |
| TRIP-RECORDS | 14 | a record, not the reservation it records (the G4 precedent) |
| MEMBERSHIP | 15 | the approval decision |

**Separations sealed:**
- LATE-FEE / CLEANING-FEE;
- LATE-FEE and CLEANING-FEE / BILLING-RUN;
- BILLING-RUN / SUSPENSION;
- RESERVATION / UNLOCK;
- RESERVATION / TRIP-RECORDS;
- SERVICE-CREDIT / LATE-FEE.

**Every sentence is exactly one of three things:** a rule or definition carrying sealed propositions; an illustrative example; or plainly non-normative context or rationale. Normative-sounding rationale was removed before sealing, because either reading of it would fail a sealed check. The leakage gate refuses answer-key vocabulary in model-visible text. It caught one word ("reopened") before sealing.

## 4. Deltas and corrections (dense)

**T2: four corrections and one unrelated extension.**

| Case | Cardinality | Correction |
|---|---|---|
| X1 | 1:1 | cleaning fee 30 → 40 EUR |
| X2 | N:1 | grace period + per-minute rate → one flat 25 EUR fee; the cap is restated |
| X3 | 1:N | one 10 EUR credit → 10 EUR up to four hours + 20 EUR over four hours |
| X4 | N:M (T8 shape) | a fixed 10-second wait and "the same for every attempt" → 5 seconds first, doubling, and a 40-second cap |
| — | extension | trip records gain a download right (EXTENDS). It applies while the four sets are pending |

**Branches after T2.** The store is cloned once per branch. In each clone, the scripted architect (`human://validation-architect`, holding a live project-wide `AuthorityRecord` recorded before T1):
- reads `list_authority_work`;
- decides every PENDING set it lists, one at a time, as of the sequence just read, through `decide_correction_set`: **AGREE** in branch AGREE, **DECLINE** in branch DECLINE.

The model never decides authority. There is no checkpoint schedule.

**T3: the same delta in both branches.**
- **Case A (Z4):** the X4 section is redelivered byte for byte.
  - After DECLINE, the same correction on the same basis must not become work again: its members are refused `CORRECTION_DECLINED`.
  - After AGREE it is a restatement of the agreed claims.
- **Case B (Z5):** the cleaning fee changes to 35 EUR, a new basis. In both branches, one new PENDING set.

## 5. Timepoints

| Timepoint | State |
|---|---|
| `T1`, `T2` | every ledger |
| `AGREED`, `DECLINED` | the dense ledger right after the scripted decisions, per branch |
| `T3-AGREE`, `T3-DECLINE` | after T3 in each branch |

Every question names its timepoint. Every packet is built from exactly that frozen state: nothing later appears in it, and no branch's packet shows the other branch.

## 6. Structural checks (deterministic)

**Formation.** Per sealed concern, exactly one CREATE citing exactly its sections, and none citing two concerns' sections (`OVER_SPLIT`, `UNDER_SPLIT`). Address counts per timepoint. Live-claim ranges per concern per timepoint: at least one and at most one claim per current proposition, per document.

**Items.** Binds, creates, new live claims, held set members, required supports.

**Corrections, while PENDING:**
- exactly one set per sealed correction;
- targets only among the claims of the sealed sections, between one and the number of obsolete propositions;
- exactly all of those claims where the section is wholly obsolete;
- no member applied (`LEAK`) and no target retired (`EARLY_RETIREMENT`).

**Corrections, after the decision:**
- AGREE: every member applied and every target retired (`PARTIAL_APPLY`, `TARGET_NOT_RETIRED`);
- DECLINE: nothing applied, nothing retired, nothing still held (`DECLINE_APPLIED`, `STILL_BLOCKING`).

**The repeat after DECLINE** makes no new set, and every re-proposed member is refused `CORRECTION_DECLINED` naming the declined set (`REOPENED`).

**Pending sets.** At every timepoint the PENDING sets are exactly the sealed ones.

**Authority routing, at every timepoint:**
- the production invariant holds;
- no per-edge work for a correction;
- every listed set is decided, by the architect, with protocol `ie2-authority-routing-v2`;
- no set member is applied by admission;
- work ids are stable under replay.

**Other checks:**
- canonical facets everywhere, and no model-authored facet;
- source coverage;
- proposition accounting, recomputed with the TARGET_SET law including correction edges;
- run integrity: calls per delta and branch, replay of every ledger and branch, the request-only reference law, 26 calls.

## 7. Semantic adjudication (independent, pre-registered)

**93 questions.** They cover:
- concern boundaries and subjects (T1);
- claim fidelity;
- correction semantics and N:M replacement (T2);
- the post-AGREE and post-DECLINE states;
- the repeat and the changed basis at T3;
- the dispositions of every revised document;
- the non-operative sentences of every claim-writing call.

**Where the answers come from.** Each question is answered YES or NO from its own packet only.

**The standing is all-or-nothing:** `LOCUS_POLICY_VALIDATED` iff every structural check passes and every question is answered YES; otherwise `LOCUS_POLICY_NOT_VALIDATED`. Critical cases are named: C7 (C09), C6 and D0 (dense formation).

## 8. Seal and gates

**The manifest freezes:**
- this design and the grain decision (sha256);
- the corpus and the dense density;
- the source coverage and the answer key;
- the questions;
- the scoring sources (evaluation, adjudication, expectations, authority);
- the model identity;
- the policy, prompt, output contract and correction law;
- the admission configuration;
- the authority protocol with its actor, record and branches;
- the budgets;
- the regression bytes.

**Preflight gates** refuse:
- any difference between code and seal;
- a seal commit that adds anything but the two sealed files;
- a dirty tree;
- any identity drift (including a ONE_TARGET law);
- a governor without canonical facets or correction sets;
- an authority-protocol mismatch;
- a coverage gap;
- insufficient density;
- a non-native resolver;
- a consumed identity;
- leakage;
- changed regression bytes.
