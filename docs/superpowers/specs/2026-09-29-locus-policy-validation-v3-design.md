# Locus Policy Validation v3 — Design Specification

**Experiment:** `intent-v2-locus-validation-v3`
**Status:** binding specification, authorised by the founder (2026-09-29: "prove this policy live"). No live call before the seal.
**Policy under test (unchanged during the validation):** `intent-v2-locus-v2`, `XAIGovernedConcernSemanticReasoner`, prompt `77a20f3b1d39787b351aedaf031176c61c295dc8cab526ffa08373da79a801cd`, output schema `ffc6946a…`, introduced by `a4c114ac2fc43323647b8f3ea6819555f51f0ffc`.
**Provider configuration (held constant from v2):** xAI `grok-4.6`, reasoning effort `high`, `GRPC_DNS_RESOLVER=native`. The model is confirmed by provider metadata before the consuming write; if `grok-4.6` is unavailable the run is refused. No substitute model (Grok 4.7, Astra, Claude or any other) is permitted.
**Predecessors (never rerun, rescored or modified):** `intent-v2-locus-validation-v1` (`b8cd827`) and `intent-v2-locus-validation-v2` (`2ea8ef6`), both `LOCUS_POLICY_NOT_VALIDATED`. v2 tested `intent-v2-locus-v1`.

## 1. Question

> Does the governed-concern policy cause the live model to form and reuse semantic addresses at the correct grain?

v2 isolated the failure: old policy + `grok-4.6` over-split C09 and C6. v3 holds the model, effort, pipeline, admission policy and reference law constant and changes only the policy, so the answer is attributable to the policy.

## 2. Hypotheses (all-or-nothing)

On the live model under the unchanged two-call protocol, the governed-concern policy:
(C1) supports a restatement without re-asserting it; (C2) adds a compatible proposition at the same address; (C3) creates an address for an independently governed concern inside a known document; (C4) corrects with ASSERT plus a pending SUPERSEDE of exactly the corrected claim; (C5) holds two already-present incompatible claims in CONFLICTS_WITH without superseding either; (C6) places the 14-day late-delivery request deadline at the existing compensation address (v2's over-split); (C7) forms 9P3 C09 as one cancellation concern holding all three T1 propositions and adds the repeated-cancellation proposition there (critical gate); (C8) forms 16 nearby payment concerns itself and places a lineage-free extension at the right one; and (U1–U4) keeps four nearby but independently governed pairs apart.

## 3. Ledgers (each a fresh project, store and governor)

| ledger | scope | T1 (two calls unless seeded) | T2 (always two calls) | cases |
|---|---|---|---|---|
| `core` | `dispatch` | model: 7 documents, 2 propositions each | 5 items | C0–C4, C6, U2, U3 |
| `orion` | `orion` | model: 9P3 locus H T1, byte-exact | 9P3 locus H T9, byte-exact | C7 |
| `jobs` | `scheduler` | model: job cancellation + job audit records | one lineage-free operator note | U1 |
| `conflict` | `portal` | seed author: 1 address, 2 incompatible claims | a new version of each source, restating it | C5 |
| `large` | `payments` | model: 16 nearby payment documents | one lineage-free note extending one | C8, U4 |

Calls: 4 + 4 + 4 + 2 + 4 = **18**. Ceiling 18 calls, 5.00 USD. No retry, no judge call, no human authorisation of model judgments, no fallback, no third call per delta.

### 4.1 Core
Every new document is written so that each numbered rule or sentence carries exactly one proposition (no rule couples, say, an entitlement with a cap or a deadline with a required attachment), so the sealed claim counts measure address grain, not claim granularity.

v2's core texts are reused byte for byte (pickup, label, weight, delivery attempts, late-delivery compensation and all five T2 items), so C6 receives the exact bytes that over-split under the previous policy (verified against v2's sealed manifest). v2's insurance document is dropped, because loss-or-damage insurance would overlap the new damaged-parcel document and make U2 ambiguous. Two documents are added: damaged-parcel compensation (U2) and the daily bank settlement run (U3), each an independently governed concern next to late-delivery compensation.

### 4.2 Orion
9P3 locus H T1 and T9, imported from the sealed 9P3 timeline and verified against the 9P3 manifest digests. Nothing else is in this ledger, so a C09 result cannot be attributed to a sibling document.

### 4.3 Jobs (U1)
Job cancellation (who may cancel; no future run after cancellation) and job audit records (automatic deletion 30 days after the job ends; early deletion only by a compliance officer). T2 is an operator note with no lineage: a request to cancel an already-finished job is refused. It must join cancellation, not the audit-record concern that also speaks of a job that has ended.

### 4.4 Conflict (C5)
An incompatible pair that already exists cannot be produced by one model delta: the same-response reference law forbids a CONFLICTS_WITH naming a claim created in the same response. As in v2 (founder ruling, Option B), a human seed author writes the address and both claims through the real governor, admitted by the unchanged policy and covered by replay. The seeded subject and facet are written at the governed-concern grain. This is the only hand-written address in v3.

### 4.5 Large world (C8, U4)
Sixteen nearby payment concerns (returned-order refunds, supplier overpayments, chargebacks, seller payouts, currency conversion, store credit, gift cards, business invoices, failed subscription payment retries, card checks, fraud holds, payment capture, new-seller limits, displayed prices, instalments, promotional codes), 19 propositions, formed **by the model** under the policy under test in one T1 delta, so the facets the T2 call must search are the policy's own. v2's large rows are not reused: they were written at the old one-question grain (request window, completion time, method and approval of one refund), where the governed-concern policy should merge them. T2 is a lineage-free note: the original delivery charge is also repaid to a customer who returns an order. It must bind to returned-order refunds and to none of the 15 others; supplier overpayments (an excess that must be paid back) is the U4 near miss.

## 5. Corpus

Byte-exact in code (`corpus.py`) and in the sealed manifest. No model-visible document or seed address contains a word of the answer key or of the policy's own vocabulary (governed, concern, dimension, facet, grain, locus, …): leakage gate.

## 6. Proposition inventory and expected state

The sealed `expectations.json` enumerates all 60 propositions of the 38 documents, the address each belongs at and its relation (SEED, RESTATES, EXTENDS, CORRECTS, NEW_CONCERN). Expected live claims per address = propositions the inventory places there (a test enforces it; no document is assumed to carry one claim).

- core after T1: 7 addresses × 2 claims. After T2: PICKUP 2 (both supported by PICKUP-T2; no new claim); LABEL 3; WEIGHT 3 (25 kg added; the 30 kg claim stays live under a pending SUPERSEDE); ATTEMPTS 2; POD new with 2; LATE 3 (+ 14-day request deadline); DAMAGE 2; SETTLEMENT 2. 8 addresses. Exactly one SUPERSEDE (WEIGHT-1); no CONFLICTS_WITH.
- orion: H with 3 claims, then 4. No SUPERSEDE, no conflict, no new address.
- jobs: CANCEL 2 then 3; AUDIT 2 then 2. 2 addresses.
- conflict: SESSION keeps both claims; at least one pending CONFLICTS_WITH naming exactly them; no SUPERSEDE; no new claim.
- large: 16 addresses (PAYOUT, GIFT-CARD, RETRY 2 claims; others 1); after T2 CUSTOMER-REFUND 2, the other 15 unchanged.

Supports: required only for the restatement (C1); elsewhere permitted only at an address the item is bound to. Forbidden: any CREATE beyond the inventory (duplicate address), any claim missing from the inventory, any claim beyond it.

## 7. Assertions

7.1 **Structural** (`evaluation.py`, deterministic, no wording read): per item, binds (exactly one to each expected address, none elsewhere), creations (more = OVER_SPLIT; fewer, or one creation citing two documents = UNDER_SPLIT), new claims per address, required supports; per address, live claims after T1 and after T2; per separated pair, two distinct addresses; per ledger, active address counts after T1 and T2, supersessions (count, target, pending, unapplied), conflicts (pair, pending), no rejected admission; per run, completion, replay, two calls per model delta, 18 calls, request-only references. Findings are tagged (OVER_SPLIT, UNDER_SPLIT, WRONG_BIND, MISSING_BIND, MISSING_EXTENSION, DUPLICATE_ASSERTION, MISSING_SUPPORT, CLAIM_COUNT, ADDRESS_COUNT, MISSING_SUPERSEDE, WRONG_SUPERSEDE_TARGET, UNGOVERNED_SUPERSEDE, FABRICATED_SUPERSEDE, UNEXPECTED_SUPERSEDE, CONFLICT_INSTEAD_OF_CORRECTION, MISSING_CONFLICT, UNEXPECTED_CONFLICT, REJECTED_ADMISSION, UNEXPECTED_CLAIM, ABORTED, INTEGRITY) and over- and under-split findings are tallied.

7.2 **Semantic** (independent adjudication, binary YES/NO): 35 sealed questions. **Every question names its ledger and the timepoint it judges** ("After T1, in ledger core, …" / "After T2, …") and is answered from a packet built from exactly that ledger's frozen `state_after` of exactly that delta: the addresses active then, all their claims with a live flag, the judgments admitted by then with their routes, and the documents received by then. Nothing later can reach an earlier packet (tested offline; v2's defect was a T1 question answered on the final state). Every model-formed address is judged after T1: its live claims state exactly its inventory, and its facet asks about the governed concern as a whole, so that every proposition of the concern's full sealed inventory answers part of it, rather than only what one proposition answers. After T2: the full expected claim set at each T2-changed address, proof of delivery as a new concern, the correction's SUPERSEDE target, and the preserved conflict.

The adjudicator is a separate agent that is not the harness builder, sees only the question, its packet and nothing of the builder's reasoning, and answers each question independently.

## 8. Standing

`LOCUS_POLICY_VALIDATED` iff every structural case, every ledger check and run integrity pass, every semantic question is answered YES, **and** the critical case C7-C09-REGRESSION passes. Anything else is `LOCUS_POLICY_NOT_VALIDATED`. No partial or qualified pass. A C09 failure is NOT_VALIDATED whatever else passes and is reported by name.

A pass means only that the governed-concern locus policy has passed its own validation. It does not validate the Foundry stack and does not authorise the 16-turn IE2 + IE3 scale experiment, which is a separate task.

## 9. Recording

Per call: the exact rendered request and its digest, allowed kinds, the ids it made citable, and the judgments returned. Per delta: every admission decision and its route and reasons, and the full frozen state after the delta. Per ledger: every event (replayed and compared), provider receipts (input and output tokens, cost, wall-clock latency). Every address, facet, claim action, relation and model rationale is in the frozen state.

## 10. Sealing and single use

`prepare` writes `manifest.json` (identity and configuration; policy version, class, prompt and schema digests; the design spec digest; the harness SHA; the corpus and its digest; the 9P3 H and v2 regression digests; the expectations digest; the adjudication-question digest; the digests of the scoring sources `evaluation.py`, `adjudication.py` and `expectations.py`) and `expectations.json` into an empty directory; the seal commit adds exactly those two files. `live` recomputes both from code, checks the seal shape, a clean tree, the policy identity, the resolver, single use, leakage and the regression bytes, reads the key only after every gate, confirms `grok-4.6` by model metadata, guards the reasoner identity before every call, makes one consuming write (`preflight.json`) and runs once. A second run of this identity is refused. Expectations, questions and scoring rules cannot change after live output exists: any edit fails `manifest_matches_code`.
