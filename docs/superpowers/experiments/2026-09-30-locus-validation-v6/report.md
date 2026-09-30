# Locus Validation v6: Report

**Standing: `LOCUS_POLICY_NOT_VALIDATED`**, by the sealed all-or-nothing rule.
- **Structural:** 11 of 41 cases fail.
- **Independent adjudication:** 88/93 YES.
- **First divergence:** dense T1, `D1-RESERVATION-ONE-CONCERN` (`CLAIM_COUNT`). The cause is the proposition grain of the sealed inventory, not concern formation (see §3).

## Lineage

| Commit | Content |
|---|---|
| `853f24f` | Harness |
| `68e9c31` | Seal (exactly `manifest.json` + `expectations.json`) |
| `3e03142` | Raw run (`preflight.json`, `run.json`) |
| This commit | Structural verdicts, 93 adjudication packets, answers, verdicts, this report |

Nothing sealed and no code changed after the first live call. The manifest recomputes exactly from the code.

## Run

**Configuration:**
- xAI `grok-4.6`, reasoning effort `high`;
- policy `intent-v2-locus-v6` (prompt `13aa8774…`, `AccountedDraftPayload` `921171df…`, law `TARGET_SET`);
- `ExecutionMode.EXPERIMENT`, one attempt per call;
- `AdmissionPolicy(canonical_facets=True, correction_sets=True)` in this validation only. Production `AdmissionPolicy().correction_sets` is still `False`.

**Before the first call:** all 17 preflight gates passed; the model was confirmed by provider metadata.

**Totals:**

| Measure | Value |
|---|---|
| Calls | 26 of 26 |
| Cost | 1.35 USD (ceiling 8) |
| Input tokens | 246,072 |
| Output tokens | 34,118 |
| Median call | 47.7 s |
| Maximum call | 295 s |
| Wall time | 30 min |

**No structural refusals.** Every ledger and both dense branches completed, and every one replays exactly.

**Authority.** The scripted architect decided 4 sets in each branch: AGREE in one, DECLINE in the other. The model decided nothing.

## What held

**Formation.** Zero over-splits and zero under-splits across all six ledgers.
- The dense T1 formed exactly the 9 sealed G2 concerns from 15 sections: reservation (3 sections), unlock attempts (3), late-return fee (2), service credit (2), and five single-section concerns.
- Every dense separation held.

**Carried regressions.**
- **C09:** the cancellation concern stays one concern (C7 passes structurally and semantically).
- **C6:** the late-delivery entitlement, destination and deadline stay one concern.
- **U1–U3** pass.

**Accounting and facets.** Source accounting, proposition accounting (recomputed under TARGET_SET, with correction edges) and canonical facets pass everywhere.

**Correction sets.**
- **1:1 (X1):** passes.
- **N:M (X4):** passes. Both old wait claims are targeted and three assertions are held.
- **1:N (X3):** structural pass; the correction set is correct. It fails only on the semantic question (see §3).
- **PENDING atomicity (Z1):** no correcting claim live, no target retired early, the unrelated trip extension applied.
- **Changed basis (Z5):** a new PENDING set in both branches.
- **Authority routing (Z6):** passes. The observed behaviour of AGREE (all members applied atomically, all targets retired) and DECLINE (nothing applied, nothing held) is correct in every set; the Z2/Z3 structural failures are claim-count consequences (§3).

**Exact repeat after DECLINE: the production behaviour is correct.** All five re-proposed members were refused `CORRECTION_DECLINED` naming the declined T2 set, and no new set formed.

## 3. Failures and their classification

**1. Proposition grain of the sealed inventory (validation/answer-key defect).** First divergence.
- **What happened:** the model split compound sentences that the inventory sealed as one proposition each into two faithful claims:
  - `K-RES-2`: "made in the app **and** states its start and end time";
  - `K-UNL-4`: "no further command **and** directed to the support line";
  - at T2, `K-LATE-7`: "a flat 25 EUR **for any delay, however short**", split into flat amount plus no grace. Each half carried one SUPERSEDE: the rate and the grace claim.
- **Why it fails:** the sealed range (at most one claim per proposition) fails:
  - D1/D2 at T1;
  - D0, Z2 and Z3 claim counts at later timepoints (the extra claims persist);
  - X2 `HELD_COUNT` (2 held assertions, 1 sealed).
- **What the adjudicators found:** they answered every affected claim and disposition question YES (for example `Q-T2-DISP-K-LATE-T2`, `Q-T1-DENSE-RESERVATION`, `Q-T1-DENSE-UNLOCK`).
- **Classification:** validation/harness defect (proposition inventory granularity), surfacing as a structural failure. It is not a concern-formation or correction-cardinality failure.

**2. Z4 `REOPENED` (scorer defect: a false positive).**
- **What happened:** the evaluator selects "drafts citing the redelivered document" through a SUPERSEDE's `visible_evidence_ids`. The production adapter fills that field with every evidence id of the request. So the legitimate PENDING cleaning-fee SUPERSEDE of T3-DECLINE "cites" the unlock-wait document and is reported as a reopened repeat.
- **What the record shows:** the unlock-wait repeat was fully suppressed, and the adjudicator answered `Q-T3-DECLINE-Z4-REPEAT-SUPPRESSED` YES.
- **Classification:** validation/harness defect. It was not caught offline because the scripted oracle cites one document per judgment. Not patched.

**3. Four subject-naming NOs (semantic: address subject names one dimension).**
- `Q-T1-CORE-PICKUP` ("Pickup collection cut-off");
- `Q-T1-CORE-WEIGHT` ("Parcel weight limit");
- `Q-T1-LARGE-CUSTOMER-REFUND` ("Refund of returned order items");
- `Q-T1-LARGE-SELLER-LIMIT` ("New seller payment limit").

These fail C0, C8 and U4.
- **Classification:** governed-concern formation, subject naming only. Grouping is correct: each is the right address with the right claims.
- **Adjudicator note:** the adjudicators flagged the seller-limit case (a one-proposition concern) as dependent on how strictly the subject rule is read.

**4. `Q-T2-X3-ONE-TO-MANY` NO (semantic claim extraction).**
- **What happened:** no live claim states `K-CREDIT-4` ("a claim made later is refused"). The model stated the 48-hour deadline only.
- **Adjudicator disagreement:** the batch-A adjudicator accepted the deadline claim as covering `K-CREDIT-4` in three other questions, and batch D did not. The first answers stand as recorded.

## Integrity

- Replay matches for all 6 ledgers and both branches.
- Calls per delta and per branch are exact, the request-only reference law holds, and all 26 calls are within budget.
- The seal hashes recompute: `expectations` `c4a77dd9…`, corpus `4949e99e…`, questions `c5a9d361…`, scoring sources unchanged.
- Post-run: `lv6` mutation slice 16/16 killed; 278 validation and IE2 regression tests pass; ruff and mypy clean.
