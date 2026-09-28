# Locus Policy Validation v2 — Design Specification

**Experiment:** `intent-v2-locus-validation-v2`
**Status:** binding specification, authorised by the founder (Option B, 2026-09-28). No live call before the seal.
**Policy under test (unchanged):** `intent-v2-locus-v1`, `XAILocusSemanticReasoner`, prompt `e0547cfe…`, output schema `ffc6946a…`.
**Provider configuration (v1's, unchanged):** xAI `grok-4.6`, reasoning effort `high`, `GRPC_DNS_RESOLVER=native`. Availability was confirmed by model metadata before design. No substitute model is permitted; if `grok-4.6` is unavailable at run time the run is refused.
**Predecessor (never rerun, rescored or modified):** `intent-v2-locus-validation-v1`, adjudicated `b8cd827`, `LOCUS_POLICY_NOT_VALIDATED`.

## 1. Why a second validation

v1's three structural failures (α S01, α V03, β S01) were an expectation defect, not a
locus failure. The policy says "classify PER PROPOSITION … several compatible claims may be
current at one address", the corpus documents stated 4, 2 and 2 propositions, and v1's
expectations required exactly one claim per document. Every semantic assertion passed. v1
cannot be rescored without rewriting expectations after results, so v2 validates the same
policy afresh with a sealed proposition inventory.

## 2. Hypotheses (all-or-nothing)

The locus policy, on the live model under the unchanged two-call protocol, (1) supports a
restatement without re-asserting it, (2) adds a compatible proposition at the same address,
(3) creates an address only for a genuinely different question, (4) corrects with ASSERT plus
a pending SUPERSEDE, (5) holds two already-present incompatible claims in CONFLICTS_WITH
without superseding either, (6) keeps a nearby but different concept apart, (7) handles
9P3's C09 shape correctly, and (8) finds the right address among 16 nearby ones.

## 3. The contradiction ruling (Option B)

The current policy classes an incoming incompatible proposition as a **correction**
(same address, ASSERT + SUPERSEDE). CONFLICTS_WITH is defined only between two claims that
already exist in the request (the same-response reference law forbids naming a claim created
in the same response). v2 tests exactly that: case 5 seeds two incompatible live claims and
expects them preserved and held in conflict. No concurrent-source policy is invented; the
reference law and the IE2/IE3 boundary are unchanged.

## 4. Ledgers (each a fresh project, store and governor)

| ledger | T1 | T2 (always two calls) | cases |
|---|---|---|---|
| `core` (scope `dispatch`) | model: 6 documents, 2 propositions each | 5 items | 0, 1, 2, 3, 4, 6 |
| `orion` (scope `orion`) | model: 9P3 locus H T1, byte-exact | 9P3 locus H T9, byte-exact | 7 |
| `conflict` (scope `portal`) | seed author: 1 address, 2 incompatible claims | a new version of each source, restating it | 5 |
| `large` (scope `payments`) | seed author: 16 nearby refund/payout addresses | one new note (no lineage) extending one of them | 8 |

4.3 / 4.4: the `conflict` and `large` worlds are written deterministically by a human seed
author through the real governor (CREATE_ADDRESS and ASSERT_CLAIM, admitted by the unchanged
policy), so they are exactly what the case needs and replay like everything else. The large
world's extension carries no evidence lineage to its target, so the address must be found by
meaning, not by structure. The orion texts are imported from the sealed 9P3 timeline and
verified against the 9P3 manifest's recorded digests (exempt from v1's non-reuse rule).

Calls: core 4 + orion 4 + conflict 2 + large 2 = **12**. Ceiling 12 calls, 3.00 USD. No
retry, no judge, no human authorisation of model judgments.

## 5. Corpus

Byte-exact in code (`corpus.py`) and in the sealed manifest. Documents are realistic
multi-proposition rules; no document names a class, case, action or evaluator term (leakage
gate).

## 6. Proposition inventory and expected state

The sealed `expectations.json` enumerates every proposition of every document, the address it
belongs at and its relation (SEED, RESTATES, EXTENDS, CORRECTS, NEW_LOCUS). Expected live
claims per address = propositions placed there (a test enforces the equality). Summary:

- core T1: 6 addresses × 2 claims. T2: PICKUP 2 (restated, each supported); LABEL 3 (+barcode);
  WEIGHT 3 (+25 kg; the 30 kg claim stays live under a pending SUPERSEDE); ATTEMPTS 2; POD new
  with 2 (signature recorded; kept 90 days); INSURANCE 2; LATE 3 (+14-day request deadline).
  7 addresses; exactly one SUPERSEDE (WEIGHT); no conflict.
- orion: H with 3 claims (who may cancel; no future attempt; running attempt not
  interrupted), then 4 (+ repeated cancellation is idempotent). No SUPERSEDE, no new address.
- conflict: SESSION keeps both claims; at least one pending CONFLICTS_WITH naming exactly
  them; no SUPERSEDE; no new claim.
- large: 16 addresses; PARTIAL 2 (+ several partial refunds per order); every other 1.

## 7. Assertions

7.1 **Structural** (`evaluation.py`, deterministic, no wording read): per item, binds (exactly
one to each expected address, none elsewhere), creations, new claims per address, required
supports; per address, live claims after T1 and T2; per ledger, active addresses, supersessions
(count, target address, pending and unapplied), conflicts (pair, pending), no rejected
admission; per run, completion, replay, two calls per model delta, 12 calls, request-only
references. Tags: OVER_SPLIT, UNDER_SPLIT, WRONG_BIND, MISSING_BIND, MISSING_EXTENSION,
DUPLICATE_ASSERTION, MISSING_SUPPORT, CLAIM_COUNT, ADDRESS_COUNT, MISSING_SUPERSEDE,
WRONG_SUPERSEDE_TARGET, UNGOVERNED_SUPERSEDE, FABRICATED_SUPERSEDE, CONFLICT_INSTEAD_OF_CORRECTION,
MISSING_CONFLICT, UNEXPECTED_CONFLICT, REJECTED_ADMISSION.

7.2 **Semantic** (independent adjudication, binary): 13 sealed questions (`SEMANTIC_QUESTIONS`)
answered from the frozen claims by an adjudicator who is not the harness builder and does not
see the builder's reasoning: each seed address states exactly its inventory, with a locus-level
facet; each new claim states its inventory proposition; the correction supersedes the 30 kg
claim, not the refusal claim.

## 8. Standing

`LOCUS_POLICY_VALIDATED` iff every structural case, every ledger check and run integrity pass
**and** every semantic question is answered YES. Anything else is `LOCUS_POLICY_NOT_VALIDATED`.
No partial or qualified pass.

## 9. Sealing and single use

`prepare` writes `manifest.json` (identity, configuration, corpus and its digest, the 9P3 H
digests, the expectations digest, this spec's digest, the harness SHA) and `expectations.json`
into an empty directory; the seal commit adds exactly those two files. `live` recomputes both
from code, checks the seal shape, a clean tree, the policy identity, the resolver, single use,
leakage and the 9P3 bytes, reads the key only after every gate, confirms `grok-4.6`, guards the
reasoner identity, makes one consuming write (`preflight.json`) and runs once. A second run of
this identity is refused.
