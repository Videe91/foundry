# IE2 Semantic Completeness Verification (Call 3): Design and Decision Record

**Status:** decided by the founder, implemented offline 2026-09-30. No live call.

**Principle:** before a Call-2 semantic proposal may mutate accepted state, Foundry must verify that the final claim or claims preserve all operative meaning in every proposition the model itself supplied.

**What does not change:**
- the locus model contract `intent-v2-locus-v6` (prompt `13aa8774…`, `AccountedDraftPayload` `921171df…`); no `intent-v2-locus-v7` exists;
- G2, correction cardinality and correction-set authority;
- IE3;
- production `AdmissionPolicy().correction_sets` stays `False`.

## 1. The canonical failure: K-CREDIT-4 (frozen v6 evidence)

**Source** (`K-CREDIT-CLAIM-T1`), two sentences:
- S1: "The service credit for an unavailable vehicle must be claimed in the app within 48 hours after the reservation start."
- S2: "A claim made later is refused."

**The model's proposition:** `p13`, `sentence_ids=[S1,S2]`, statement "…must be claimed within 48 hours…, **and a later claim is refused**".

**The claim draft:** ASSERT_CLAIM `claim_deadline_after_reservation_start = 48 hours`.

**Why every deterministic check passed:**
- source accounting: S1 and S2 are both carried by `p13`;
- proposition accounting: `p13` has exactly one valid disposition, and it cites its evidence;
- correction edges: none apply;
- admission: `LOW_RISK` ASSERT, APPLY.

Nothing compared `p13`'s statement with the claim it produced. Accounting is bookkeeping over ids; meaning was never checked. The test `test_the_recorded_k_credit_proposal_is_reviewed_exactly_as_it_was_written` replays the recorded payload through the real adapter and reconstructs this request exactly.

## 2. Existing infrastructure (audited, and why none of it is reusable as is)

| Candidate | What it actually is | Compares a statement to claims? |
|---|---|---|
| `REQUIRE_SECOND_LENS` / independent lenses (admission rules 5 and 7) | An admission route that waits for an independent reasoner to *propose the same signature*; corroboration by agreement, material kinds only | No: no model call of its own, no statement input, no verdict |
| `AdmissionPolicy` / authority routing / correction sets | Deterministic routing and human authority | No |
| `ModelRuntime` (provider-neutral socket; task-specific certification; `ModelTask`, tiers, registry; used by IE3) | Single typed call, identity verified, usage normalized, no verdict | It is the substrate, not the check |

**Reused:** `ModelRuntime`, as the provider-neutral execution under a new, distinct certified task. **Not reused:** anything named "lens".

## 3. Architecture

**Pipeline `ie2-verified-assimilation-v1`:**

```
Call 1 (concern/binding) -> Call 2 proposal (adapter accounting; a structural refusal raises as before)
  -> Call 3: semantic completeness verification
  -> only on PASS: admission (correction sets, authority work)
```

**Components:**
- **Domain** (`domain/semantic_completeness.py`): request, report, verdict law, all-or-nothing outcome, the `INCOMPLETE_PROPOSITION_MEANING` failure and the durable `CompletenessRecord`.
- **Port** (`ports/semantic_completeness.py`): `SemanticCompletenessVerifier.verify(CompletenessRequest) -> CompletenessVerification`. Provider-neutral; the verification reports the identity that actually ran.
- **Reasoner port** (`AccountedProposal`, `propose_accounted`): exposes the proposition accounting the accounting adapter already parses (the model's propositions, and which judgment disposes of which). `propose`, the prompt and the output contract are unchanged.
- **Adapter** (`adapters/semantics/completeness_verifier.py`): `ModelRuntimeCompletenessVerifier`, which runs `ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION` (REASONER). It names no provider or model; selection is the registry's.
- **Application** (`application/semantic_completeness.py`): `build_completeness_request` (deterministic), `verified_propose_and_submit`, and `recorded_outcome`. It is wired through `claim_call(verifier=…)` and `assimilate_delta(verifier=…)`.
- **Governor:** `propose_and_submit` is split into `submit_proposed`, which the verified path calls only after a PASS, and `record_completeness`.

**Ordering compatibility.** Before this change, Call 2 mutated nothing before `propose_and_submit` recorded its judgments, so the check sits between the adapter's answer and submission. Nothing had to move. Call 1's bindings apply before Call 2 exactly as before.

## 4. The completeness law

For each proposition P, and the union of the claims disposing of it:

> Do the claims, taken together, preserve every operative assertion of P, without adding a contradictory or materially different assertion?

**Definitions:**
- An *operative assertion* is an actor, obligation or permission, quantity or limit, timing, deadline, condition or eligibility, consequence or effect, exception, destination or repetition rule.
- A condition and its consequence are two assertions: a deadline does not state what happens when it is missed.
- Wording, paraphrase, predicate names, word order and claim count never matter.

**Verdicts:**

| Verdict | Meaning |
|---|---|
| `COMPLETE` | every operative assertion stated, nothing materially beyond |
| `INCOMPLETE` | a `missing` region: an operative assertion no claim states |
| `OVERREACH` | an `unsupported` region: an operative assertion P does not make (an extra rule, a stronger or weaker quantity, a new actor, condition or consequence) |
| `CONTRADICTORY` | a `contradictory` region: claims contradict P or each other |

A verdict carries regions exactly when it is not COMPLETE (schema-enforced).

**The overreach boundary.** A claim that adds an operative assertion P does not make fails, even when it also contains P's meaning. "Refused after 30 days, *and the member is suspended*" is OVERREACH. A paraphrase or a more specific restatement of the same assertion is not OVERREACH.

**The outcome (deterministic, all-or-nothing).** PASS requires all of the following:
- a valid report, with every proposition judged exactly once on exactly its own claim refs (`MISSING_VERDICT`, `DUPLICATE_VERDICT`, `UNKNOWN_PROPOSITION` and `WRONG_CLAIM_REFERENCES` are refusals);
- a verifier independent of the writer;
- every verdict COMPLETE.

Anything else FAILs the **whole** response (`INCOMPLETE_PROPOSITION_MEANING`, `VERIFIER_OUTPUT_INVALID` or `VERIFIER_NOT_INDEPENDENT`).

**Report output (the smallest possible).** Per proposition: `proposition_id`, `verdict`, `claim_refs`, and `missing` / `unsupported` / `contradictory` regions. There is no field for a corrected claim, a value, a predicate or a disposition. The verifier cannot propose, rewrite or choose ASSERT, SUPPORT or SUPERSEDE.

## 5. Dispositions

| Disposition | Reviewed claims | Question |
|---|---|---|
| SUPPORT | the one supported existing claim (`SUPPORTED`) | does that claim fully carry P? |
| ASSERT | the asserted claims (`ASSERTED`) | do they carry P? |
| ASSERT + SUPERSEDE | the asserted claims; the retired claims shown as context (`RETIRED`) | do the new claims carry P *before* the old ones are treated as obsolete? |

## 6. One proposition → one or several claims

**What production allows today.** The accounting law allows exactly one ASSERT_CLAIM per model proposition. The v6 "one meaning → two claims" cases (`K-RES-2`, `K-UNL-4`, `K-LATE-7`) were the model creating two propositions of its own, each with one claim. The verifier judges the model's propositions, never a sealed inventory, so the one-claim-per-expected-proposition mistake cannot recur.

**The contract still judges the union.** A request carries every claim disposing of a proposition. `test_one_proposition_judged_on_the_union_of_its_claims` and the domain test `test_a_faithful_decomposition_is_judged_against_the_union_of_its_claims` prove that a two-claim disposition PASSes. The production accounting law is **not** changed.

**The recorded splits.** `K-RES-2` (`p05`/`p06`), `K-UNL-4` (`p45`/`p46`) and `K-LATE-7` (`p-flat`/`p-any`, each retiring one old claim) each reach admission after a PASS.

## 7. Every Call 2, or a deterministic subset?

**Every accepted Call 2 that lists at least one proposition is verified.** No sound deterministic trigger exists:
- a single-sentence, single-claim proposition can still lose a clause (exam `E08`);
- a SUPPORT can carry a different meaning (`E14/b`).

**The one deterministic skip:** a Call 2 with no proposition. It has no claim content to lose. For example, only CONFLICTS_WITH relations, which are not proposition dispositions.

## 8. Independence and model selection

**Rules:**
- The verifier must be independent of the writer by the existing `independent()` rule (different provider or model). A same-model verifier is refused at record time (`VERIFIER_NOT_INDEPENDENT`), and nothing applies.
- Selection is policy-bound: the registry routes to a model certified for `SEMANTIC_COMPLETENESS_VERIFICATION`. Production code names no provider or model.

**What a deployment must do:** certify a verifier model independent of the IE2 writer. The runtime check fails closed if it is not.

## 9. Call budget

**Normal verified assimilation:**
- Call 1: concern/binding;
- Call 2: claim writing;
- Call 3: semantic completeness verification (`VERIFICATION_CALLS_PER_DELTA = 1`).

**Production maximum:** `MAX_PRODUCTION_CALLS_PER_DELTA` = 1 + 2 + 1 = 4 (Call 1, Call 2, its one structural re-proposal, Call 3). Call 3 is a verifier: it generates no proposal and modifies no content. `DeltaOutcome.calls_made` counts it.

**`ExecutionMode.PRODUCTION` requires a verifier** (`SemanticCompletenessRequired`), and also a reasoner that exposes proposition accounting. Both are refused before anything is written.

**EXPERIMENT and CERTIFICATION** without a verifier keep the historical two-call path byte-for-byte, so v5, v6 and every frozen run replay and re-run unchanged.

## 10. Re-proposal

**A completeness FAIL is never re-proposed.** `SemanticCompletenessRefused` is not a `ReasonerResponseRefused`, and the production re-propose allowlist is unchanged; the result is STOP and refuse. A structural accounting refusal is still re-proposed once, and the accepted attempt is then verified.

**Future option (not built):** a bounded semantic re-proposal workflow would need its own notice, identity and budget.

## 11. Correction sets and authority

Verification happens **before** correction-set formation and authority. On FAIL:
- no judgment is recorded;
- no correcting ASSERT and no SUPERSEDE effect;
- no `CORRECTION_SET_PROPOSED`;
- no authority work.

A human is never asked to approve an incomplete correction. The response fails whole, even when the correction itself was complete (`test_an_incomplete_response_creates_no_correction_set_and_no_authority_work`).

## 12. Failure representation, audit and replay

**The failure.** `SemanticCompletenessRefused(record, failures)` carries each `IncompletePropositionMeaning`: `code=INCOMPLETE_PROPOSITION_MEANING`, `proposition_id`, `verdict`, `claim_refs`, `verification_id`, and `missing` / `unsupported` / `contradictory` regions. It is never disguised as an accounting code, a schema error, an admission REJECT or a confidence.

**The durable record.** `SEMANTIC_COMPLETENESS_RECORDED` (`CompletenessRecord`) is appended for every verification, PASS or FAIL, **before** any Call-2 judgment. The reducer refuses a record whose proposal's judgments already exist. The record holds:
- the checked request (every proposition, statement, source sentences and claims);
- the proposed judgment ids;
- writer and verifier identities, and the verifier invocation;
- `request_sha256` (validated);
- the report, the outcome, the failure codes and the structured failures;
- usage (tokens, cost, latency).

**What it touches.** It changes no claim; the verifier's prose never enters canonical claim state. Replay reads the record (`recorded_outcome`) and never calls a verifier. The verifier's parse failure is recorded as no report, under the routed identity: a FAIL.

## 13. Identities

| Identity | Value |
|---|---|
| Locus policy (model-facing Call 1 / Call 2) | `intent-v2-locus-v6`, unchanged |
| Runtime pipeline | `ie2-verified-assimilation-v1` |
| Verifier policy | `ie2-semantic-completeness-v1`: instruction sha256 `56b753a9156883264f9bdd070f9b5b63facb653c68bdb5fbcd0c0322814a0d7c`, output contract `CompletenessReport` |
| Certified runtime task | `ModelTask.SEMANTIC_COMPLETENESS_VERIFICATION` (REASONER) |
| Certification exam | `ie2-semantic-completeness-exam-v1` (sha256 `8eb4ea4e…`) |

## 14. Verifier certification exam (prepared, not run)

`src/foundry/experiments/completeness_verifier_exam/exam.py` holds 18 cases in a held-out library domain, plus the named K-CREDIT regression.

**Categories:**
- complete paraphrase (×2);
- faithful decomposition;
- three claims jointly complete;
- missing condition, consequence, exception, second sentence and clause;
- unsupported addition;
- contradiction;
- misleading lexical overlap (both directions);
- deadline vs refusal (library and K-CREDIT);
- eligibility vs consequence;
- SUPPORT disposition (complete and contradictory);
- correction disposition (complete and incomplete).

**Verdict balance:** 7 COMPLETE and 13 non-COMPLETE propositions, so every verdict and both failure directions are examined.

**Scoring** is all-or-nothing: `SEMANTIC_COMPLETENESS_VERIFIER_CERTIFIED` iff every report is valid and every verdict matches. Tests prove that an oracle is certified, and that always-COMPLETE, always-INCOMPLETE and unparseable verifiers are not.

**Leakage:** no request contains a verdict word.

**Sealing and running** the exam live is a separate, later task.

## 15. What is not decided or not built here

- Which certified model serves as verifier (a registry and certification decision).
- Live certification of any verifier.
- A semantic re-proposal workflow.
- Relaxing the one-ASSERT-per-proposition accounting law.
- Subject naming, which is out of scope and stays a model-quality property under the explicit v6 contract.
