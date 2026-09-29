# IE2 Proposition Accounting: nothing supplied to claim writing may silently disappear

**Status:** architecture decision by the founder, 2026-09-29, taken after the audit below.
Amends the IE2 v2 design (new §7.1.3).
**Policy:** `intent-v2-locus-v4` (`XAIPropositionAccountingSemanticReasoner`), prompt SHA-256
`cbf652fb3dc7a5864813c02f64373adc72faceddea0793409c34972a0adb1e2f`, output contract
`AccountedDraftPayload` `921171df25bbf4c64f3a2570ea64dc0b29d6618cf0c8c56f79e01abf1d34a142`.
No live model call has been made under it. `intent-v2-locus-v3` and every earlier identity
are unchanged; locus validation v4 stays `LOCUS_POLICY_NOT_VALIDATED`.

## 1. Audit of the production path (before this change)

| # | question | finding |
|---|---|---|
| 1 | Call 1 receives | the delta evidence items (whole text), descriptors and live-claim profiles of active in-scope addresses, compiled comparison context; CREATE/BIND only |
| 2 | Call 1 produces | CREATE_ADDRESS / BIND_TO_ADDRESS drafts citing evidence ids, with subject and rationale |
| 3 | proposition inventory from Call 1? | none; the unit is the evidence item |
| 4 | Call 2 receives | the same delta (whole text), the claim-neighbourhood addresses and their live claims, comparison context; SUPPORTS/ASSERT/SUPERSEDE/CONFLICTS_WITH |
| 5 | propositions individually? | no; only the evidence text |
| 6 | Call 2 produces | claim drafts citing evidence ids (SUPERSEDE and CONFLICTS_WITH cite none of their own) |
| 7 | where a proposition can disappear | inside the Call-2 response: no object represents it, so omitting it (or a whole document) leaves no trace |
| 8 | does deterministic code know what entered? | it knows evidence ids and which ones Call 1 bound; it never knew proposition count, ids or which received an action |
| 9 | enough ids for accounting? | evidence-level only (a bound item with no Call-2 draft citing it is detectable); not proposition-level |
| 10 | `source_coverage` | validation-only (sealed answer keys); its sentence splitter is a deterministic, reusable primitive |

## 2. The two live failures, traced (validation v4, `477cd2b`)

**C09 (H-5).** H-T9's sentence S3 "… a repeated cancellation is simply acknowledged" was in
both requests. Call 1 bound H-T9 to the cancellation address (correct). Call 2 returned three
SUPPORTS_CLAIM and one ASSERT_CLAIM whose **rationale** reads "a repeated cancellation is
acknowledged and must leave an already cancelled job cancelled…", but whose **value** quotes
numbered rule 3 only. The claim writer saw the meaning and folded it out of the claim; it was
never independently represented before or during Call 2, so there was nothing to check the
drafts against. Admission applied all four drafts correctly.

**C8 (CR-2).** Call 1 bound RETURNS-NOTE-T2 to the customer-refund address with a rationale
naming the new proposition. Call 2 returned `{"drafts": []}`. A deterministic signal existed
and was unused: an item Call 1 bound was cited by no Call-2 draft.

## 3. The decision

**Invariant.** Every sentence of accountable evidence is carried by a proposition or declared
non-operative with a reason; every proposition receives exactly one disposition from the
existing claim laws (SUPPORTS; ASSERT; ASSERT + SUPERSEDE). CONFLICTS_WITH disposes of no
proposition (current policy: each restated side of a conflict is a SUPPORTS; the relation is
between two current claims). There is no "not representable" outcome in IE2 and none is
invented: an undecided proposition is an ASSERT with an UNDECIDED value, as today.

**Two boundaries, two reasons.** *Source accounting* (sentence → proposition:
`UNACCOUNTED_SENTENCE`, `UNKNOWN_SENTENCE`, `DOUBLE_ACCOUNTED_SENTENCE`) is distinct from *claim
accounting* (proposition → disposition: `UNACCOUNTED_PROPOSITION`, `UNKNOWN_PROPOSITION`,
`DUPLICATE_PROPOSITION`, `CONFLICTING_DISPOSITION`, `PROPOSITION_EVIDENCE_MISMATCH`). The same
sentence splitter serves sealed validations (answer-key source coverage) and production (the
model's inventory).

**Architecture: Option B, at the existing claim-writing boundary.** Option A (reuse Call 1's
propositions) does not exist: Call 1 produces none. Option C (a separate extraction call) is
not needed and would break the two-call law. The inventory is part of the Call-2 response:

* `ReasoningRequest.accountable_evidence_ids` (defaulted empty) names the delta items Call 1's
  applied CREATE/BIND judgments cite (`accountable_evidence_from_decisions`). A NO_MATCH item
  has no address to hold a claim and is not accountable.
* The rendered request of this policy only adds `sentences_to_account`: every sentence of the
  accountable evidence with Foundry's id `<evidence_id>#S<n>`.
* `AccountedDraftPayload`: `propositions` (id, sentence ids, statement), `non_operative`
  (sentence id, reason) and drafts whose ASSERT/SUPPORTS/SUPERSEDE each carry `proposition_id`.
* The adapter validates with `accounting_findings` right after parsing, before wrapping: a
  finding raises `PropositionAccountingError` (a `SemanticOutputError`), so the whole response
  is refused before any judgment exists. State is unchanged by it (Call 1's admissions stay, as
  for every Call-2 failure); the receipt and the refused payload remain recorded.

**No silent repair.** Foundry never writes, infers or suggests a missing disposition. The
refusal names ids only.

**Policy identity.** The model-facing contract changes (prompt section, rendered sentence
index, output schema), so this is a new policy, `intent-v2-locus-v4`. It could not be a pure
admission invariant: without proposition ids in the response nothing deterministic can know
what the writer was given. The prompt is the canonical-facet prompt with one section
appended; nothing is rewritten because the section defines a new part of the response, not a
second meaning of an existing term.

**What accounting cannot guarantee (stated, not hidden).** Accounting makes omission
impossible to do silently: C8's empty response and C09's unlisted acknowledgement sentence are
refused by id. It does not judge fidelity: a proposition listed and asserted with a value that
states it only partly (the exact C09 value shape, if the model lists "repeat acknowledged and
unchanged" as one proposition and quotes rule 3) passes accounting and stays a matter for the
reasoner, admission and semantic adjudication. The model's proposition statements are recorded
in the adapter's payload records, not in the event ledger; persisting the inventory as durable
provenance would be a new event or judgment type and is not decided here.

## 4. Production re-propose loop: not implemented (ARCHITECTURE QUESTION)

The proposed loop (keep the refused proposal and reason; re-ask the same model once with only
the deterministic refusal, e.g. `UNACCOUNTED_PROPOSITION: H-5`; validate the new answer from
zero; accept or stop) is sound in shape and can be isolated from certification (experiment
wrappers already refuse a third call per delta). It is not implemented because it conflicts
with an approved law: the IE2 design and `incremental_assimilation` fix **exactly two frontier
calls per delta, no re-attempt, no fallback** (spec §6). A re-ask is a third call.

```text
ARCHITECTURE QUESTION: May production assimilation make one bounded re-ask of Call 2 after a
deterministic accounting refusal, given the approved two-calls-per-delta law?

Options:
- A: Keep the two-call law; a refusal ends the delta (today). Simple; the ledger stays exact;
  an omitted proposition costs a whole new delta run by the caller.
- B: Amend the law for production only: at most one re-ask of Call 2 per delta, carrying only
  refusal ids, in a production orchestrator distinct from assimilate_delta; certification and
  sealed experiments keep exactly two calls. Needs: where the refused proposal and reason are
  recorded (adapter record vs a new ledger event), how the re-ask is rendered (a new request
  field, which is model-facing and so policy-versioned), and a budget rule.

Blocked work:
- the production re-propose loop.
```

## 5. PARALLEL_NODE (IE3) — outstanding

Nothing named `PARALLEL_NODE` exists in the repository. The IE3 graph-synthesis prompt tells the
model "Do not create a parallel new node beside the stale object"
(`adapters/intent_graph_synthesis/model_runtime.py`), and `intent_graph_validation` rejects
`DUPLICATE_RELATION`, but no structural check refuses a REPLACES_STALE node plus a parallel NEW
node of the same kind derived from the same claim. It is still outstanding, belongs to the IE3
validation layer (not the IE2 accounting law) and is not touched here.
