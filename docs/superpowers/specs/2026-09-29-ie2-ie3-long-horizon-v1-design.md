# IE2 + IE3 Long-Horizon Experiment v1: Design Specification

**Experiment:** `intent-ie2-ie3-long-horizon-v1` (single-use, sealed).
**Status:** binding specification, authorised by the founder on 2026-09-29 ("Proceed with the fresh sealed 16-turn combined IE2 + IE3 long-horizon experiment"). No live call is made before the seal.
**Historical predecessor (never rerun, rescored or modified):** `intent-v2-long-horizon-bounded-memory-v1` (9P3). F 14/15 and A 14/15 both failed C09; R 1/15 failed from C03 onward.

## 1. Question

> Does the current Foundry architecture solve the historical long-horizon failure? Across all 16 turns of the historical Orion world, can the validated IE2 policy and the certified IE3 synthesizer accumulate, preserve and evolve meaning over the whole growing state?

This is not a pure model benchmark. The architecture, contracts and components have all changed since 9P3.

## 2. Corpus (identical to 9P3)

- **Input per turn T.** `long_horizon_bounded.timeline.persistent_delta(T)`: the twelve historical sections of version T, in the historical document order. The frozen items are unchanged except `project_id` (`PROJ-LH23-ORION`).
- **Coverage.** All 12 loci (A–L), all 16 versions, 192 items and 38 distinct section texts.
- **Identity proof.** `corpus.historical_corpus_findings` must be empty before sealing. It checks the structural corpus digest (`50b83eea…`, equal to the 9P3 manifest's `corpus_sha256`) and, item by item, content sha256, byte length, version, lineage, timestamp, scope, kind and reference.
- **Representation difference.** The project id only.
- **No new inputs.** No semantic input is added, and the corpus has no explicit mission statement.

## 3. IE2 (validated)

- **Policy.** `intent-v2-locus-v5` on xAI `grok-4.6`, reasoning effort high, `GRPC_DNS_RESOLVER=native`.
  - Reasoner `XAIReproposingSemanticReasoner`.
  - Prompt `cc913e3d…`.
  - Output contract `AccountedDraftPayload` `921171df…`.
  - Canonical facets, proposition accounting and source accounting.
  - The governor runs `AdmissionPolicy(canonical_facets=True)`.
- **Validation.** `intent-v2-locus-validation-v5`, `LOCUS_POLICY_VALIDATED`, at `20b4005`.
- **Mode.** `ExecutionMode.EXPERIMENT`: exactly two calls per turn and one attempt each. There is no re-proposal and no third call; the first answer counts.
- **Identity guard.** Validation v5's `require_accounting_policy_identity` runs before every call. Its frozen identity must equal this experiment's field for field.

## 4. IE3 (certified)

- **Model and configuration.** `openai/gpt-6-astra`: reasoning effort high, mode standard, output guard 16,000, timeout 180 s.
- **Task and policy.** Task `INTENT_GRAPH_SYNTHESIS` at tier REASONER, policy `intent-synthesis.graph-v1` / `intent-graph-synthesis-runtime-v4`.
- **Bound identities.** Prompt `fd395605…`, canonical schema `6b64d274…`, OpenAI wire `7b825730…` (`foundry.openai-structured-outputs.v1`).
- **Certificate.** Exam v6 `818f6f87…`: 33/33, certificate `851c8a6b…`. Its root-staleness base is `0b8f077`, which must be an ancestor of HEAD.
- **Before sealing.** The certificate must read `CURRENT` under `graph_certificate_standing`.
- **Mode.** `ExecutionMode.EXPERIMENT`, and no graph re-proposal policy is certified. One call per turn, with no re-proposal, retry or repair; the OpenAI adapter's `max_retries=0` means one synthesis is one provider execution.

## 5. Root Intent rule

The Orion corpus lacks an authoritative mission statement. Therefore this experiment validates long-horizon evolution of evidence-grounded graph state beneath a single model-proposed stable Intent root; it does not validate the semantic correctness of the root's natural-language mission wording.

- **At T1.** IE3 may propose exactly one PROPOSED root Intent, lawfully grounded (`DERIVED_FROM`) on shown claims. No human mission is injected, and the mission wording is never scored.
- **From T2 to T16:**
  - the T1 root stays the one current Intent, unchanged and never retired;
  - it is not stale in the bounded view (IE3 §17.2); its raw-plane staleness is recorded separately and not scored;
  - its provenance edges stay recorded;
  - there is no second root, no replacement root and no root-staleness gap.
- **D8.** D8 is out of scope, because no turn changes the overall mission.

## 6. Pipeline per turn (real, no reset)

One project, one store and one governor for all 16 turns; T16 sees every consequence of T1 to T15.

1. **Pre-T snapshot.** At a checkpoint (9P3 `AUTHORITY_CHECKPOINTS`: T3 A, T5 B, T7 F, T8 B, T10 D, T12 G, T14 J, T16 I), the eligible target judgments at the target locus's designated address are snapshotted before T's evidence is ingested.
2. **IE2.** `assimilate_delta` (Call 1 CREATE/BIND, Call 2 claims with accounting).
3. **Designation.** After T1, the 9P3 module designates one address per locus, structurally.
4. **Authority.** At checkpoints, the 9P3 protocol relays an already-pending model SUPERSEDE that targets an eligible judgment to the architect's AGREE. Anything else is recorded and left pending. This is the same human-authorisation sequence as 9P3.
5. **IE3.** `synthesize_intent_graph` runs over scope `orion-jobs` with the production context compiler, validator, router, compiler and reducer.

Nothing is hand-authored, and no state is synthetic.

A structural refusal is recorded and the walk continues. That covers an IE2 Call 2 refused by accounting (the turn keeps Call 1's admissions) and an IE3 answer Foundry refuses (nothing durable). A provider, transport, budget, identity or harness failure stops the walk, and every remaining turn is `NOT_RUN`. Nothing is ever repaired.

## 7. Answer key (sealed, derived from the 9P3 key only)

The key comes from the historical baseline meanings, each transition's §5 meaning and the checkpoint classes. It never uses a historical model output.

- **Propositions.** Per locus:
  - REQUIRED propositions: the normative rules the historical meanings name;
  - OPTIONAL propositions: descriptive or rationale statements a model may state as claims or set aside, neither being an error.
- **Source coverage.** Every sentence of every one of the 38 texts is accounted for, by proposition ids or as an example; preparation refuses a gap.
- **Correction turns, per the sealed key.**
  - Corrections: T3 A, T5 B, T7 F, T10 D, T12 G, T14 J and T16 I.
  - Revert: T8 B.
  - T15 F is a restatement (the 90-second lease restated), not a correction.

### 7.1 IE2 laws (mechanical)

- **Formation and binding.**
  - T1 forms exactly 12 addresses, each designated, and they are pairwise distinct.
  - After T1 no address is created, so any creation is an over-split.
  - Every item of every turn is bound to its own locus's designated address; a missing bind or wrong bind is a finding.
  - No address holds two loci; that would be an under-split.
- **Claim ranges per turn.** Claims newly asserted at each locus must fall in these ranges:

  | Turn and locus | New claims |
  |---|---|
  | T1 | 1 … the number of propositions in the text |
  | A control locus | 0 |
  | A correction or revert target | 1 … the number of propositions in the new text |
  | The T9 target | 1 … 2 |
  | A restatement target | 0 … the number of genuinely new optional propositions |

- **Removals.** No live claim leaves a control locus.
- **Supersession.**
  - A correction or revert turn needs at least one AGREEd supersession, with no ambiguous or not-eligible proposal.
  - No other turn may propose a SUPERSEDE.
  - No pending judgment is left after authority.
- **Other laws.**
  - No CONFLICTS_WITH.
  - No rejected admission.
  - Every new address's facet equals `canonical_facet(subject)`.
- **Accounting.** Every accepted Call 2's accounting is recomputed under the production law.
- **Revert (T8).** No T1 B claim is live again.
- **C09 (T9).** Every H claim live before T9 is still live after it.

### 7.2 IE3 laws (mechanical, per turn)

- **Call.** Exactly one execution of `openai/gpt-6-astra INTENT_GRAPH_SYNTHESIS REASONER`, and an applied decision (APPLY or NO_CHANGE).
- **Root lifecycle.** As in §5.
- **Coverage.** Every live claim is the `DERIVED_FROM` basis of at least one current non-root object.
- **Staleness.** No current object is stale in the bounded view (no stale retention).
- **Duplicates.** For each live claim and kind, at most one current object derives from that claim.
- **Preservation.** Every object that was current and not stale before the turn is unchanged after it.
- **No false NEW.** From T2, a created object either replaces a stale one or derives from a claim created this turn.
- **Replacement locus.** A replacement's basis loci are a subset of the retired object's basis loci.
- **Gaps.** No gap is created. The material leaves nothing open if IE2 is right.
- **Kinds.** Every current non-root object is a REQUIREMENT, CONSTRAINT, GOAL, OUTCOME or NON_GOAL. The certified ontology does not decide REQUIREMENT against CONSTRAINT for these operational rules, or NON_GOAL for "no ordering guarantee across partitions". A DECISION, PREFERENCE, ASSUMPTION or second INTENT is unlawful.
- **Serving path.** Every current non-root object reaches the root through SERVES over current objects.

Behaviour class per turn:

| Class | Turns |
|---|---|
| GRAPH_FORMATION | T1 |
| NO_GRAPH_CHANGE | T2, T4, T6, T11, T13, T15 |
| REPLACE_STALE | T3, T5, T7, T8, T10, T12, T14, T16 |
| EXTEND | T9 |

Prose is never scored; graph evolution is.

### 7.3 C09 (T9), the primary before-and-now checkpoint

- **IE2** must:
  - reuse the designated H address (no new address);
  - keep H-1..H-3 live, with no SUPERSEDE;
  - state H-4 (a repeated cancellation leaves the job cancelled and otherwise unchanged) and H-5 (it is acknowledged) as new compatible claims;
  - account for every sentence.
- **IE3** must:
  - add object(s) grounded on the new H claim(s);
  - leave the existing H objects untouched;
  - replace nothing;
  - serve the same root.

## 8. Independent adjudication (sealed questions)

There are 70 questions. Each names its layer, turn, timepoint and locus, and is answered from a frozen packet of exactly that state.

- **IE2 (44).**
  - Twelve T1 locus questions.
  - One target question per turn from T2, except T4 (a no-op, judged mechanically) and T9, which has three: existing H, H-4 and H-5.
  - Sixteen accounting questions ("no required proposition silently lost; every listed proposition faithful").
- **IE3 (26).**
  - Twelve T1 locus questions.
  - Fourteen target questions from T2 (T4 excluded): "current objects faithfully express the current meaning; none still expresses the superseded meaning".

The adjudicator is independent (`foundry-verifier`) and answers YES or NO with a reason. It never sees expectations beyond the question and never rewrites one. IE2 and IE3 results are kept apart.

## 9. Standing

**`LONG_HORIZON_IE2_IE3_VALIDATED`** requires all of the following; anything else is **`LONG_HORIZON_IE2_IE3_NOT_VALIDATED`**:
- all 16 turns completed;
- every `T<nn>-IE2` and `T<nn>-IE3` check-set, `RUN-INTEGRITY` (replay, budgets) and `SOURCE-COVERAGE` passing;
- every one of the 70 adjudication answers YES.

That implies:
- zero over-splits and under-splits, zero missing propositions, zero silent accounting losses;
- every IE3 validation passing, with one stable root, no false root staleness, no duplicates, no wrong replacements and no stale retention;
- C09 passing, the correction turns passing, and T10–T16 passing.

Per-layer standings are reported. They never weaken the verdict.

## 10. Failure attribution

The first divergence is the earliest turn with a failing check-set, with IE2 considered before IE3 in a turn. Findings are classified by layer:
- **IE2:** concern formation, binding, source accounting, proposition accounting, claim extraction, SUPPORT/ASSERT/SUPERSEDE, conflict, authority or canonical facet.
- **IE3:** context, root lifecycle, model choice, kind, grounding, serving, witness, replacement, gap, contradiction, duplicate or validator.
- **Experiment:** corpus, expectation, scorer, adjudication or harness.

An IE3 finding at a locus whose IE2 state was already wrong is a downstream consequence, not an independent failure.

**Named architecture category (declared before the run).** A replacement is strictly one for one, and retiring an object without a successor is D8, which is unbuilt. So a stale object whose meaning has no successor claim cannot lawfully leave the graph. This can happen when IE2 splits a corrected locus into fewer claims than IE3 made nodes for, most plausibly at the T8 revert. If it happens it is classified `ARCHITECTURE: no retirement without successor (D8)`, not as a model error. It still fails the verdict.

## 11. Budgets and live rules

- **Budgets.** IE2 at most 32 calls (2 per turn) and at most 20 USD of known cost. IE3 at most 16 calls (1 per turn; OpenAI reports no cost).
- **Ceilings.** They are enforced before forwarding.
- **No second attempts.** No retry, re-proposal, repair, judge, expectation edit, prompt edit or model substitution.
- **Provider metadata.** It confirms `grok-4.6` and `gpt-6-astra` before the consuming write.
- **Single use.** `run.json` is written once.

## 12. Sealing

- **Commits.** The harness commit comes first. The seal commit adds exactly `manifest.json` and `expectations.json`, and its parent is the harness. Then the raw run commit, then the adjudication commit.
- **Preflight.** It recomputes both sealed files and checks:
  - the git shape and a clean tree;
  - the root-staleness base (`0b8f077`);
  - the IE2 and IE3 identities, and that the IE3 certificate reads CURRENT;
  - single-attempt modes and canonical facets;
  - source coverage and historical corpus identity;
  - the resolver, single use and leakage (no request-path module imports the answer key).
