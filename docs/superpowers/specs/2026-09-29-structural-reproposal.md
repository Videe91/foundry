# Structural walls and the production-only bounded re-proposal

**Status:** architecture decision by the founder, 2026-09-29. It answers the ARCHITECTURE QUESTION
of `2026-09-29-ie2-proposition-accounting.md` §4 (option B, production only) and adds the IE3
`PARALLEL_NODE` wall. It amends IE2 v2 design §7.1.4 and IE3 graph design §17.1 and §22.1. No live
model call was made. Validations v1 to v4 and every certificate are unchanged.

## A. IE3 `PARALLEL_NODE`

**Invariant.** Within one graph answer: a `NEW` node and a `REPLACES_STALE` node of the same
`SemanticKind`, both with a direct `DERIVED_FROM` edge to the same basis claim, are refused
`PARALLEL_NODE` (`IntentGraphValidationError`, code `PARALLEL_NODE`, naming both local ids, the
kind and the claim).

**Layer.** `foundry.domain.intent_graph_validation.validate_intent_graph`, as
`_check_parallel_nodes`, after the replacement checks and before cycles. It runs inside
`validate_graph_result` in `_decide`, before anything is appended, so a refused answer mutates
nothing. The code reaches the certification record through the existing `governance_error` path
and, in production, the `STRUCTURAL_REFUSAL_RECORDED` audit event.

**Why exactly this key.** Only deterministic facts: batch, disposition, kind, direct
`DERIVED_FROM` edges. No wording. It is the narrowest key that catches the defect. Different kinds
from one claim stay legal (a claim may ground, for example, a replacement Requirement and a new
Constraint). The same kind from different claims stays legal. Two `NEW` nodes and two replacements
are left to the existing laws (`DOUBLE_REPLACEMENT` covers one target replaced twice). Indirect
derivation (a `NEW` node derived from the replacement node) is a different shape and is not
matched. Under IE2 a claim is one proposition, so one claim yielding a replacement and a parallel
new node of the same kind is a duplicate, not two meanings.

**The recorded Grok exam-v5 case C attempt 1.** It is the motivating answer, but its bytes do not
carry the key. The `NEW` node `req-refund-window` had **no relation at all**, and only the
replacement derived from `CLAIM-4127…`. The exam refused it `NO_RELEVANCE`, the first defect in
the fixed order, and grounding would refuse it too. Firing `PARALLEL_NODE` on those bytes would
mean guessing what an ungrounded node derives from, which is inference, so it stays
`NO_RELEVANCE` as recorded. The **grounded** form of the same answer (the `NEW` node also
deriving from the claim and serving the goal) passes every earlier law and is exactly what the
wall now refuses; that is the offline regression.

**Certification impact.**
- Certificates bind `frozen_production_base` (the commit), the runtime policy version, the prompt
  SHA and the schema SHA. The validator is Foundry governance, not the model contract: runtime-v4's
  prompt, schema and request are byte-identical.
- 1,861 recorded graph answers (every graph result in every JSON file under
  `tests/certification/evidence`) were scanned. None has the refused shape; the only
  same-kind `NEW` plus `REPLACES_STALE` pair anywhere is Grok's case C attempt 1, already a
  recorded FAIL. So every historical certificate remains a truthful record of its base.
- Future certification binds whatever production base it runs on, so it will include the wall.
  No new runtime version is needed for the wall itself.

**Architecture question (not decided here).**

```text
ARCHITECTURE QUESTION: Should IE3 also refuse a NEW node that has no claim grounding of its own
beside a same-kind REPLACES_STALE node (the exact recorded C-1 bytes) as PARALLEL_NODE?

Options:
- A: Keep the edge-only key (today). The recorded bytes stay NO_RELEVANCE, which is already a
  refusal; no inference.
- B: Broaden to "same kind, NEW + REPLACES_STALE, NEW node's direct claims ⊆ the replacement's".
  It catches the ungrounded form under its intended name, but it rejects a lawful ungrounded
  human-authored NEW node beside a replacement, and it names a defect that the grounding law
  already refuses.

Blocked work: none.
```

## B. Production-only bounded re-proposal

**Principle.** It is not repair. Foundry never alters, completes or suggests semantic content. It
records the refused attempt, tells the model only what was structurally wrong (codes and ids),
and asks once for a complete new proposal, which it validates from zero.

**Execution mode** (`foundry.domain.structural_refusal.ExecutionMode`). Only `PRODUCTION` may
re-propose (`REPROPOSE_MODES`). `CERTIFICATION`, `EXPERIMENT` and a caller that names no mode
(fail-closed default) measure the first answer only. `assimilate_delta` and
`synthesize_intent_graph` take `mode=`; no experiment, certification or script source names
`ExecutionMode.PRODUCTION` (a test scans them).

**Allowlists** (only codes Foundry can state deterministically as a breach of the answer contract;
the refusal is re-proposable iff there is a finding and every finding's code is listed):
- IE2: `UNACCOUNTED_SENTENCE`, `UNKNOWN_SENTENCE`, `DOUBLE_ACCOUNTED_SENTENCE`,
  `UNACCOUNTED_PROPOSITION`, `UNKNOWN_PROPOSITION`, `DUPLICATE_PROPOSITION`,
  `CONFLICTING_DISPOSITION`, `PROPOSITION_EVIDENCE_MISMATCH`.
- IE3: `PARALLEL_NODE`.
- **Not re-proposable:**
  - `NON_CANONICAL_FACET`: an admission REJECT of one judgment after submission, not a
    whole-response refusal, and the canonical-facet adapter cannot produce it.
  - Schema violations, forbidden kinds and reference-law breaches: raised as `SemanticOutputError`
    and not yet reviewed for the allowlist.
  - Every other graph code.
  - Admission REJECTs, semantic scorer or reviewer disagreement, low confidence, undesirable
    meaning.
  - Provider and transport failures: a separate concern, not retried here.

**Budget.** `MAX_REPROPOSALS = 1`. IE2: Call 1, Call 2 attempt 1, Call 2 attempt 2, at most
`MAX_PRODUCTION_CALLS_PER_DELTA = 3`. IE3: attempt 1, attempt 2. The count is Foundry's control
flow (one `try`, one retry, no loop), never model-controlled; a second refusal is recorded and
raised.

**Re-propose request.**
- IE2: the refused attempt's `ReasoningRequest` unchanged, plus `reproposal: ReproposalNotice`
  (refused_attempt = 1, findings). It is rendered only by a policy that accepts re-proposals as
  `previous_proposal_refused: {refused_attempt, findings, notice}`. Every other adapter refuses a
  request carrying a notice before calling.
- IE3: the runtime-v4 system instruction and request message byte for byte, plus one further user
  message with the same `previous_proposal_refused` object.
- The notice text is fixed:

  > Your previous proposal for this same request was refused because it broke the structural
  > answer contract. Refusal: {findings}. Nothing from that proposal was kept. Answer the whole
  > request again with a complete new proposal.

**Identities.**
- IE2: `intent-v2-locus-v5` (`XAIReproposingSemanticReasoner`), prompt `cc913e3d…`. It is the
  accounting prompt plus one section, the same `AccountedDraftPayload` contract, and
  `accepts_reproposal = True`. `intent-v2-locus-v4` and every earlier identity are byte-identical.
- IE3: `intent-graph-synthesis-reproposal-v1`, the re-proposal answer's authorship (the model saw
  more than the certified request). Runtime-v4 is unchanged.
- Both: `REPROPOSAL_CONTRACT_SHA256` `613ac286…` pins the notice text, both allowlists, the maximum
  and the modes. IE2 and IE3 keep separate policy objects.

**IE3 production enablement: blocked on certification.** Production graph synthesis runs only
the certified runtime-v4 ("no other certification covers graph synthesis"). A re-proposal answer
is produced from a request no certification covers, so `CERTIFIED_GRAPH_REPROPOSAL_POLICY_VERSIONS`
is empty. Today production records the IE3 refusal and stops. The mechanism is complete and
proven offline with the set standing in for a future certification. Enabling it is a
certification task.

**Audit** (`STRUCTURAL_REFUSAL_RECORDED`, payload `StructuralRefusal`; reduced like
`DOCUMENT_ADDED`, changing no state). Each record carries:
- `engine`, `mode` and `attempt`;
- the `request_sha256` of the semantic request both attempts answer (the notice excluded);
- the author `reasoner` fingerprint;
- `findings`, `codes` and `reproposable`;
- `invocation_id` (IE2: keys the adapter's receipt of tokens, cost and latency);
- `proposal_json`, the refused proposal as the contract parsed it;
- for attempt 2, `reproposal_of` (attempt 1's event id) and `notice` (exactly what the model was
  shown).

IE3 records use the run's deterministic steps `STRUCTURAL-REFUSAL-1` and `-2`. Records are
appended, never overwritten. A successful attempt 2 leaves attempt 1's record in the ledger, and
the IE2 outcome lists it in `refused_attempts`.

**State law.**
- **Attempt 1 refused:** nothing from it is applied. IE2's Call-1 admissions remain, exactly as
  for any Call-2 failure today; there is no whole-delta transaction.
- **Attempt 2 accepted:** only attempt 2's proposal is admitted (IE3: decided under the
  re-proposal author).
- **Attempt 2 refused:** stop; nothing from either attempt is applied; the final refusal is raised.

**Isolation.**
- Re-proposal needs `mode=PRODUCTION` **and**, for IE2, a reasoner whose class declares
  `accepts_reproposal`, or, for IE3, a `ReproposingIntentGraphSynthesizer` with a certified
  re-proposal identity.
- Sealed-experiment recording wrappers do not declare it (tested), their budgets refuse a third
  call per delta, and their identity guards admit only their frozen policies.
- Certification harnesses call without a mode.
