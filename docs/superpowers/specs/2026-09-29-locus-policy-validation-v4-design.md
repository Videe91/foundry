# Locus Policy Validation v4 — Design Specification

**Experiment:** `intent-v2-locus-validation-v4`
**Status:** binding specification, authorised by the founder (2026-09-29: "validate the current governed-concern locus policy live"). No live call before the seal.
**Policy under test (unchanged during the validation):** `intent-v2-locus-v3`, `XAICanonicalFacetSemanticReasoner`, prompt `83a717a9e11d26841b0538bcb781eb766b07bdfc94873213da0965be5ac2d803`, output contract `ConcernDraftPayload` `08d881db080f87b45abebc3fb79ce53229ccf490b1ba331f75744efb55051b79` (the historical `SemanticDraftPayload` `ffc6946a…` is unchanged), canonical facet `canonical_facet(subject) = "Rules governing " + subject`, every governor under `AdmissionPolicy(canonical_facets=True)`. Introduced by `ce5195f`.
**Provider configuration (held constant from v2 and v3):** xAI `grok-4.6`, reasoning effort `high`, `GRPC_DNS_RESOLVER=native`, the production `XAISemanticReasoner` transport. Confirmed by provider metadata before design and again before the consuming write; if unavailable the run is refused. No substitute model.
**Predecessors (never rerun, rescored or modified):** v1 (`b8cd827`), v2 (`2ea8ef6`, `intent-v2-locus-v1`), v3 (`4e277a6`, `intent-v2-locus-v2`), all `LOCUS_POLICY_NOT_VALIDATED`.

## 1. Question

> The old policies failed with Grok 4.6. Does `intent-v2-locus-v3` make the same model form and reuse addresses at the governed-concern grain, with every facet Foundry's projection of the concern subject?

## 2. Hypotheses (all-or-nothing)

As v3 (C1 restatement, C2 extension, C3 new concern, C4 correction, C5 existing conflict, C6 late-delivery deadline, C7 C09 critical, C8 sixteen model-formed concerns, U1–U4 separate concerns), plus: every address and every CREATE/BIND candidate carries `canonical_facet(subject)`; no model payload carries a facet; facets are pairwise distinct per ledger; and every source-supported proposition, including C09's "a repeated cancellation is simply acknowledged", is stated.

## 3. Isolation: the policy is the only variable

Every document is validation v3's text byte for byte (a test compares each to v3's sealed manifest); only evidence ids are new. The model, effort, transport, two-call pipeline, reference law and ledgers are v3's. v2 and v3 failed on these inputs under `intent-v2-locus-v1` and `-v2`.

## 4. Ledgers

As v3 §3–§4.5: `core` (7 T1 documents, 5 T2 items), `orion` (9P3 locus H T1 and T9, byte-exact), `jobs` (cancellation and audit records; a lineage-free operator note), `conflict` (seeded incompatible pair, C5), `large` (16 model-formed payment concerns; a lineage-free extension). 18 calls, ceiling 18 calls and 5.00 USD, no retries.

**4.4 Conflict seed.** The one hand-written address (the incompatible pair cannot be produced by one model delta under the same-response reference law; founder ruling Option B, v2) is written with `facet = canonical_facet(subject)`, because the governor refuses any other facet.

## 5. Source coverage (the v3 lesson)

Every sentence of every document (`source_sentences`: headings and bare labels carry none; an abbreviation such as "2 p.m. local time" never splits a sentence) is sealed in `SOURCE_COVERAGE` with the proposition ids it carries or an explicit reason it carries none (an illustrative example that restates listed rules; the question an FAQ answer responds to). 71 sentences over 38 documents. `source_coverage_findings` also refuses an account naming an unknown proposition and a proposition that no sentence of its document carries. `prepare` refuses to seal, and the `source_coverage_complete` gate refuses to run, on any finding; `SOURCE-COVERAGE` is a structural check of the standing. C09's H-T9 prose sentence "… a repeated cancellation is simply acknowledged" carries a new proposition H-5 (EXTENDS at H), beside H-4 (remains cancelled, nothing else changes). H-T1's prose restatement is mapped to H-2 and H-3.

## 6. Proposition inventory and expected state

61 propositions. Claim counts are **ranges**, not points: per address, a document adds at least one live claim and at most one per proposition it places there. v3 showed that one sentence may be read as one claim or two (its H-4 claim stated H-4 and H-5 together); a range keeps that legitimate variation from failing a structural check, while every proposition must still be stated, which the adjudicator decides. Address counts per ledger stay exact (7→8, 1, 2, 1, 16), so over- and under-splitting stay structural.

Required supports: C1 (PICKUP-T2 supports every earlier PICKUP claim) and C7 (H-T9 supports every T1 claim at H). Elsewhere a support is permitted only at a bound address. Exactly one SUPERSEDE (WEIGHT, pending); at least one pending CONFLICTS_WITH naming exactly the two seeded session claims; nothing else.

## 7. Assertions

**7.1 Structural** (`evaluation.py`, deterministic, no wording read): v3's per-item, per-address, per-pair, per-ledger and run-integrity checks with ranges (§6), tagged and tallied for over- and under-splits.

**7.2 Semantic** (independent adjudication, YES/NO): 35 questions. Each names its ledger and timepoint and is answered from the packet of exactly that frozen state (tested offline). For every model-formed address after T1: every listed proposition is stated by at least one live claim and no live claim states anything else; and the **subject** names the governed concern itself, such that every proposition of the concern's full sealed inventory is about it, not one dimension or a generic word. After T2: the same claim rule on the full inventory of each T2-changed address; proof of delivery as a new concern; the correction's SUPERSEDE target; the preserved conflict. The facet is not asked about: it is Foundry's projection and is checked in 7.3.

**7.3 Canonical facets** (structural, `CANONICAL-FACETS`): after T1 and after T2, every address has `facet == canonical_facet(subject)` (`NON_CANONICAL_FACET`), none is one of the facets v2/v3 recorded ("Sender refund entitlement", "How it is governed", "Governance", "Lifecycle", "Who may cancel a job?", "How cancellation affects execution attempts": `BANNED_FACET`), no two active addresses of a ledger share a facet (`FACET_COLLISION`); every CREATE/BIND candidate is canonical; and no recorded model payload contains a `facet` field (`MODEL_FACET`). A reply that carries a facet violates the sealed contract and is refused whole by the adapter (the run then aborts: nothing is repaired); a non-canonical candidate is refused by the governor (`STRUCTURAL: NON_CANONICAL_FACET`) and fails the ledger.

## 8. Standing

`LOCUS_POLICY_VALIDATED` iff every case, ledger, `CANONICAL-FACETS`, `SOURCE-COVERAGE` and run-integrity structural check passes (hence zero over- and under-splits), every semantic question is answered YES (hence zero missing propositions), and the critical case C7-C09-REGRESSION passes. Otherwise `LOCUS_POLICY_NOT_VALIDATED`. No partial pass. A pass validates this locus policy only; it does not authorise the IE2 + IE3 sixteen-turn scale experiment.

## 9. Recording

Per call: the rendered request and its digest, allowed kinds, citable ids, returned judgments, the governed state just before the call (so the state after Call 1 is kept, not only after each delta) and the exact payload the model returned as parsed by the sealed contract (subjects chosen, drafts). Per delta: every admission decision with route and reasons, the frozen state after it (addresses with subject and projected facet, claims, relations). Per ledger: events (replayed and compared) and receipts (tokens, cost, latency).

## 10. Sealing and single use

`prepare` refuses an incomplete source-coverage map, then writes `manifest.json` (identity, configuration, policy version, class, prompt, concern-contract and historical-contract digests, the canonical-facet flag and prefix, the design spec digest, the harness SHA, the corpus and its digest, the source-coverage digest and findings, the 9P3 H and v2 regression digests, the expectations and adjudication-question digests, the digests of the scoring sources) and `expectations.json`; the seal commit adds exactly those two files. Preflight also checks the canonical-facet policy identity, that a ledger governor actually runs `canonical_facets=True`, and source coverage. `live` confirms `grok-4.6`, guards the reasoner identity (including its output contract) before every call, makes one consuming write and runs once.
