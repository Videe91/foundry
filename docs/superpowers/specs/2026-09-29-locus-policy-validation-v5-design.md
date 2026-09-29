# Locus Policy Validation v5 — Design Specification

**Experiment:** `intent-v2-locus-validation-v5`
**Status:** binding specification, authorised by the founder (2026-09-29: "proceed to the next live validation of the IE2 locus layer"). No live call before the seal.
**Policy under test (unchanged during the validation):** `intent-v2-locus-v5`, `XAIReproposingSemanticReasoner`, prompt `cc913e3d7aee49e13e2e40745ddc791df0dee0e663893f42be39a475e16a09dc`, output contract `AccountedDraftPayload` `921171df25bbf4c64f3a2570ea64dc0b29d6618cf0c8c56f79e01abf1d34a142` (historical `ffc6946a…` unchanged); canonical facets; proposition accounting; every governor under `AdmissionPolicy(canonical_facets=True)`. Taken at `47b599c`.
**Execution mode:** `ExecutionMode.EXPERIMENT`. One attempt per semantic call. A structurally refused answer is a failed attempt and is **never re-proposed**. Three independent locks enforce this: the mode is outside `REPROPOSE_MODES`; the recording wrapper does not accept re-proposals; and its budget refuses a third call per delta.
**Provider configuration (held constant from v2 to v4):** xAI `grok-4.6`, reasoning effort `high`, `GRPC_DNS_RESOLVER=native`. Confirmed by provider metadata before design and again before the consuming write. No substitute model.
**Predecessors (never rerun, rescored or modified):** v1 `b8cd827`, v2 `2ea8ef6`, v3 `4e277a6` and v4 `ae1ebcc`, all `LOCUS_POLICY_NOT_VALIDATED`.

## 1. Question

> v4 showed the model grouping, binding and projecting facets correctly but silently dropping propositions. Does `intent-v2-locus-v5` make the same model account for every source sentence and every proposition in its first answer, and state them?

## 2. Isolation

Every document is v4's (and v3's) text byte for byte, with new evidence ids; a test compares each against v4's sealed manifest. The ledgers, cases, proposition inventory (61 propositions) and source-coverage map (71 sentences; digest `a017d6b5…`, identical to v4's) are v4's. The sentence splitter is production's (`foundry.domain.source_text`), so validation and policy share one reading of sentence boundaries.

## 3. Cases

- **C0–C8 and U1–U4:** as v4. C7 (9P3 C09) is critical. Its inventory includes H-1 to H-3, H-4 (the job stays cancelled and nothing else changes) and H-5 (a repeated cancellation is acknowledged).
- **New, A-CORE / A-ORION / A-JOBS / A-CONFLICT / A-LARGE (source accounting):** per ledger, no operative sentence was set aside as non-operative.

## 4. What changed from v4

1. **The model's accounting is recorded.** Each claim-writing call records the rendered request exactly as the model saw it (with `sentences_to_account`), its parsed payload (propositions, non-operative sentences, dispositions by proposition id), and, if refused, the refusal findings. A refused call is recorded like any other, with its receipt.
2. **A structural refusal is measured, not aborted.** It is the adapter refusing a response that breaks the accounting contract. That ledger ends `REFUSED`, its cases fail with the exact findings, and the walk continues so every other ledger is measured. Any other failure (transport, budget, identity) still aborts the run.
3. **Structural check `PROPOSITION-ACCOUNTING`.** It fails on any refused call. For every accepted claim-writing call, it recomputes `accounting_findings` (the production law) from the recorded request and payload; any finding fails.
4. **Expected dispositions are sealed:** SEED, EXTENDS and NEW_CONCERN → ASSERT_CLAIM; RESTATES → SUPPORTS_CLAIM; CORRECTS → ASSERT_CLAIM plus SUPERSEDE.
5. **54 adjudication questions**, each naming its ledger and timepoint, answered from that frozen packet. Each packet now includes the model's accounting for that delta.
   - v4's 35 claim and subject questions.
   - 10 disposition questions (`Q-T2-DISP-<doc>`): every sealed proposition of each T2 document is represented by a listed proposition with its sealed disposition.
   - 9 source-accounting questions (`Q-T<n>-NONOP-<ledger>`): no sentence declared non-operative states a sealed proposition.

## 5. Standing

`LOCUS_POLICY_VALIDATED` iff all of the following hold; otherwise `LOCUS_POLICY_NOT_VALIDATED`, with no partial pass:
- every case, ledger and run-integrity check passes, and so do the `CANONICAL-FACETS`, `SOURCE-COVERAGE` and `PROPOSITION-ACCOUNTING` structural checks. That means zero over- and under-splits, zero refused calls, zero unaccounted sentences or propositions, and every facet canonical;
- every semantic question is answered YES, so there are zero missing propositions, every disposition is as sealed and no operative sentence was set aside;
- C7 (C09) and C8 pass.

## 6. Failure classification (reported, not acted on)

Each failure is classified as one of: concern selection; binding; source extraction or accounting; proposition accounting; claim wording or semantic fidelity; SUPPORT/ASSERT/SUPERSEDE decision; conflict handling; canonical facet; validation-design defect; other. Nothing is patched after the run.

## 7. Sealing and single use

As v4 §10, plus:
- the manifest records `execution_mode`;
- the `accounting_policy_identity` gate checks the v5 prompt and the accounting contract;
- the `experiment_mode_single_attempt` gate refuses a mode that can re-propose.

The seal commit adds exactly `manifest.json` and `expectations.json`. The live run is made once, and `run.json` is written once.
