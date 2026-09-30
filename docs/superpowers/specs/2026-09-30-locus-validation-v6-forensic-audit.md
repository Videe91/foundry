# Locus Validation v6: Forensic Audit of the Failures

**Status:** audit only, 2026-09-30. No live call. v6 is not rescored, and its sealed standing stays **`LOCUS_POLICY_NOT_VALIDATED`**.

**Diagnostic code:** `src/foundry/experiments/locus_validation_v6_audit/`, labelled *DIAGNOSTIC / COUNTERFACTUAL ONLY*. It lives outside the frozen experiment directory and writes nothing into it.

## 1. Frozen-v6 integrity

**Unchanged since each was written:**

| Artifact | Since | sha256 |
|---|---|---|
| `manifest.json` | seal `68e9c31` | `9aed79b2…` |
| `expectations.json` | seal `68e9c31` | `dabfcfa6…` |
| `run.json` | raw run `3e03142` | `b541a19d…` |
| `preflight.json` | raw run `3e03142` | — |
| adjudication (93 packets, `adjudication_answers.json` `c3e121b8…`, `verdicts.json` `9babeb11…`) | `0c258c9` | as listed |

`src`, `scripts` and `tests` are unchanged from the seal (the code that ran live) up to the start of this audit. A test (`test_the_frozen_v6_evidence_is_untouched_by_the_audit`) asserts that the directory gains no diagnostic file and that the verdict is unchanged.

## 2. The claim-count failures, reconstructed

Every one comes from a sealed proposition that the model stated as two of its own propositions, each with one lawful disposition.

| Sealed proposition | Source sentence | Model propositions → claims | Added | Lost |
|---|---|---|---|---|
| `K-RES-2` | "The reservation is made in the Kestrel app and states its start time and its end time." | `p05` "made in the Kestrel app" → `booking_channel = Kestrel app`; `p06` "states its start time and its end time" → `stated_start_and_end_times` (both ASSERT_CLAIM) | nothing | nothing |
| `K-UNL-4` | "After the fifth failed attempt the app must not send another unlock command for that reservation, and the member is directed to the support line." | `p45` → `further_commands_after_fifth_failure`; `p46` → `support_redirection_after_fifth_failure` (both ASSERT_CLAIM) | nothing | nothing |
| `K-LATE-7` (T2) | "The fee is a flat 25 EUR for any delay, however short." | `p-late-flat` → `flat_fee_amount = 25 EUR` + SUPERSEDE(rate); `p-late-any-delay` → `charged_for_any_delay_however_short` + SUPERSEDE(grace) | nothing | nothing |

**Why the sealed scorer failed.** Its ranges allowed at most one live claim per sealed proposition (per document). The result:
- one surplus claim at RESERVATION (15 against 14) from T1 onward: D1, D0, and the Z2/Z3 carried counts;
- one surplus at UNLOCK (9 against 8; 10 against 9 after AGREE): D2, D0, Z2, Z3;
- one surplus held assertion at LATE-FEE in the N:1 correction, then one extra live claim after AGREE: X2 `HELD_COUNT`, Z2, and D0 at T3-AGREE.

The adjudicators answered every affected claims and disposition question YES (`Q-T1-DENSE-RESERVATION`, `Q-T1-DENSE-UNLOCK`, `Q-T2-X2-MANY-TO-ONE`, `Q-T2-DISP-K-LATE-T2`, `Q-AGREED-X2`, `Q-AGREED-X4`, `Q-DECLINED-X4`).

## 3. Is one proposition → one claim a production law?

**No, not for the sealed inventory.** Production proposition accounting (`domain/proposition_accounting.py`) binds only the **model's own** propositions:
- every accountable sentence is carried by at least one model proposition, or declared non-operative;
- a sentence may carry several (`carried[sid]` counts, and only zero is refused);
- each model proposition receives exactly one disposition (`_is_valid`: one ASSERT_CLAIM, one SUPPORTS_CLAIM, or ASSERT_CLAIM plus SUPERSEDEs).

Nothing relates model propositions to any external inventory. One source meaning may therefore lawfully become several model propositions and several claims. **The sealed one-claim limit was an oracle assumption: `ORACLE_DEFECT`.**

## 4. The correct future claim-coverage law

**Score semantic coverage, not claim cardinality** (`claim_coverage.coverage_findings`). An expectation is met when:
- every expected meaning is stated by at least one claim at its own concern (`MISSING_MEANING`, `WRONG_CONCERN`);
- every claim states at least one expected meaning (`EXTRA_MEANING`);
- no claim is incompatible with the expectation (`INCOMPATIBLE_CLAIM`);
- no claim is counted for two mutually incompatible expectations (`DOUBLE_COUNTED`; such a claim credits neither).

**What is deterministic and what is semantic:**
- **Deterministic:** placement, and the provenance chain claim → judgment → model draft → model proposition → source sentences → sealed propositions of that sentence.
- **Semantic (independent adjudication):** whether a claim states the whole meaning of a sentence that carries more than one meaning. This is exactly the step that let `K-CREDIT-4` through (§7).

**The diagnostic admits a surplus only when all three guards hold:**
- (a) every claim traces to a sentence carrying a sealed proposition of the concern;
- (b) collapsing claims that share a source sentence brings the count within bound;
- (c) every sealed question at the creating timepoint and at the finding's timepoint that lists the carried propositions is YES.

A lower-bound (missing-claim) finding is never removed. Production accounting is not weakened.

## 5. The Z4 false positive, root cause

**The declined correction.**
- Set: `CSET-15fcc3e35b1962434086dcc0` (DECLINED).
- Equivalence key: `CEQ-62194a8ef9603bf715e98211`.
- Targets: `JDG-5a420940` (fixed 10-second wait) and `JDG-baf03fa4` (uniform wait).
- Basis: `a15bc47d…`, the content of `K-UNLOCK-WAIT-T2`.

**The T3-DECLINE repeat.**
- `K-UNLOCK-WAIT-T3` has content sha `a15bc47d…`, byte-identical to T2.
- The model re-proposed 3 assertions and 2 SUPERSEDEs of the same targets. Recomputed with production's `equivalence_key`, the repeat is `CEQ-62194a8e…`: equal to the declined set's.
- Production refused all five members `CORRECTION_DECLINED` naming `CSET-15fcc3e3…`, and formed no set.

**The legitimate change.**
- `K-CLEANING-T3` content sha `29ee1be5…` (35 EUR) differs from the declined T2 set's basis `de1e3c86…` (40 EUR).
- The target is the same (`JDG-5bc1fe05`), but the key is new (`CEQ-a30979ce…`), so there is a new PENDING set `CSET-83159e2a…`. That is correct.

**What fooled the scorer.** Every SUPERSEDE of the T3 call carries `visible_evidence_ids = [K-UNLOCK-WAIT-T3, K-CLEANING-T3]`: the adapter records the whole request's evidence. The sealed scorer selected "drafts citing the unlock-wait document" through that field, so it picked up the cleaning SUPERSEDE (`REQUIRE_HUMAN`, `CORRECTION_SET_MEMBER`) and reported `REOPENED`. **`HARNESS_DEFECT`.** Production is correct.

## 6. The correct future Z4 law

Use production's own identities, never a request-level evidence list (`diagnostic.corrected_repeat_findings`):
- select the delta's drafts by the address they bear on (an ASSERT_CLAIM's `address_id`; a SUPERSEDE's target claim's address);
- every one must be REJECT with `(CORRECTION_DECLINED, <the DECLINED set at that address>)`;
- their recomputed `equivalence_key` must equal that set's;
- no new correction set may exist at the address.

Tests: the recorded run passes; a doctored new PENDING set at the address fails; the changed cleaning-fee set is not mistaken for the repeat.

## 7. `K-CREDIT-4`, exactly

**The source** (`K-CREDIT-CLAIM-T1`), two separate sentences:
- S1: "The service credit for an unavailable vehicle must be claimed in the app within 48 hours after the reservation start."
- S2: "A claim made later is refused."

**The model's accounting.** One proposition, `p13`, with `sentence_ids = [S1, S2]` and statement: "The service credit for an unavailable vehicle must be claimed in the app within 48 hours after the reservation start, **and a later claim is refused**."

**Its one disposition:** ASSERT_CLAIM `claim_deadline_after_reservation_start = QUANTITY 48 hours`.

**Why accounting passed.** Both sentences are carried by a proposition; `p13` has exactly one valid disposition; the draft cites `K-CREDIT-CLAIM-T1`. Every production accounting law holds.

**Question A: genuinely missing.** Under IE2 semantics:
- a claim is ONE proposition, carried by its own predicate and a structured value;
- G2 lists *deadlines* and *effects* as distinct dimensions (distinct claims) of one concern.

The claim `claim_deadline… = 48 hours` states a deadline: a condition on making the claim. The refusal is the consequence of missing it. It is a separate operative proposition (the effect), and a deadline does not entail refusal: it could entail a penalty or discretion. A `QUANTITY 48 hours` value cannot express refusal. **`K-CREDIT-4` is missing from the claim state.**

Batch D of the adjudicators was right. Batch A's three YES answers crediting the deadline claim (`Q-T1-DENSE-SERVICE-CREDIT`, `Q-AGREED-X3`, `Q-DECLINED-X3`) were adjudicator leniency. They stand in the frozen record; the diagnostic rules them NO.

**Question B: where the gap is.** Not source accounting: S2 was accounted, and the model's own proposition statement **did preserve** the meaning. The loss is at **proposition → claim**:
- the model bundled two operative propositions into one proposition;
- the accounting law permits exactly one ASSERT for it;
- the one claim carried half.

It is an ordinary model semantic miss under an adequate contract. The v6 prompt says: "A claim is ONE PROPOSITION about the concern, carried by its own predicate"; "Classify PER PROPOSITION"; and lists "effects" and "deadlines" as separate dimensions. It also exposes a **known, designed limit**: accounting is bookkeeping over ids (design §7.1.3), and nothing compares a proposition's statement with the claim written for it. Sentence granularity is not the cause: the two meanings were already two sentences.

## 8. Source-accounting completeness: what is verifiable today, and the options

**What is verifiable today:** every sentence is carried or declared non-operative, and every model proposition has one lawful disposition. **Not verifiable:** that a proposition carries one operative meaning, or that its claim states its whole statement.

| Option | Guarantee gained | False-split risk | Call cost | Policy impact | Catches `K-CREDIT-4`? |
|---|---|---|---|---|---|
| A. Keep sentence-level accounting; completeness measured by validation | none new | none | 0 | none | no (validation caught it) |
| B. Deterministic clause splitting | clause-level coverage where syntax is reliable | medium (conjunctions inside one rule) | 0 | new sentence index → new policy identity | **no**: S1 and S2 were already separate sentences |
| C. Atomic source-span inventory (e.g. every operative sentence has a proposition of its own; merging requires each sentence also stand alone) | would refuse `p13` | **high**: lawful multi-sentence propositions (v5 H-T1, restatements) would be refused or duplicated | 0, but more refusals | model contract → new policy | yes, by structural refusal |
| D. Independent completeness lens (a second, independent reasoner compares each proposition statement with the claim written for it) | proposition → claim fidelity at runtime | low | +1 call per claim-writing delta | architecture (a new lens), not the model contract | **yes**: the statement says "refused", the claim does not |
| E. Existing lens routing: treat an ASSERT whose proposition cites ≥2 operative sentences as material (`REQUIRE_SECOND_LENS`) | a second lens before multi-sentence claims apply | none | a lens call when triggered | admission policy flag | yes, if the lens compares meaning |

**Recommendation:** A now. The architecture question below is for the founder and does not block Path 1.

**ARCHITECTURE QUESTION:** Must proposition → claim completeness be a runtime guarantee (option D, or E with a meaning-comparing lens), or does it remain a model-quality property measured by sealed validation (option A)?

## 9. The four subject-naming NOs

| Question | Source heading | Subject returned | Claims at the address | Does the subject exclude a claim? |
|---|---|---|---|---|
| `Q-T1-CORE-PICKUP` | "Pickup cut-off" | "Pickup collection cut-off" | same-day before 14:00; next day at/after 14:00 | no |
| `Q-T1-CORE-WEIGHT` | "Parcel weight limit" | "Parcel weight limit" | max 30 kg; overweight refused at pickup (+ held 25 kg correction) | no |
| `Q-T1-LARGE-CUSTOMER-REFUND` | "Refunds for returned orders" | "Refund of returned order items" | refund of item price; at T2, *delivery charge also repaid* | **yes**: the T2 delivery-charge claim is not about "items" |
| `Q-T1-LARGE-SELLER-LIMIT` | "New seller payment limit" | "New seller payment limit" | at most 1,000 GBP in the first 30 days | no |

**Facets.** Each facet is Foundry's canonical `Rules governing <subject>`, and every canonical-facet check passes.

**G2 applied mechanically.** The contract says the subject "names the governed concern itself … never one dimension of the concern", and "name the governed concern so that a later proposition about any dimension of it belongs there".
- A cut-off (a *when*) and a limit are listed G2 dimensions. "Pickup collection cut-off", "Parcel weight limit" and "New seller payment limit" each name the dimension the section states. All three copy the source heading.
- "Refund of returned order items" names the amount dimension and excludes a claim that sits at its own address.

**Under G2 all four are naming misses.** The customer refund is the clear one. For the other three the concern currently holds only that dimension, and the subject covers every present claim.

**Adjudicator consistency.** v5 (`LOCUS_POLICY_VALIDATED`) answered YES for exactly these subjects, from the same model on byte-identical input ("Pickup collection cut-off", "Parcel weight limit"; "Customer refund for returned order items", "New seller account payment limit"). The v6 subject rubric listed more dimension words. The subject judgement is therefore not reproducible across adjudications, which is a defect of the oracle's reliability, not of production.

**Operational consequence.** The subject is used in three ways, and for nothing else (no identity, hash, equivalence or deduplication):
- to derive the canonical facet;
- as model context (IE2 requests, where it guides BIND and CREATE decisions);
- as IE3 synthesis context (`LocusBasis.subject`).

The address id derives from the judgment, and equivalence is judged by the model. In this run no narrow subject caused a mis-bind: the delivery-charge claim bound to the refund address, and the 25 kg correction bound to weight. The risk is future binding: a dimension-shaped subject invites a later compatible proposition to be read as a new concern. That is locus validation v2's over-split mechanism.

**Contract.** The v6 prompt already states the rule explicitly. **No ambiguity is found.** The one repeated pattern is copying a dimension-shaped section heading. If a later decision wants it named, the smallest wording would be: "A section heading is not a subject: when it names one rule or dimension, name the concern that rule constrains." It changes naming only, not G2 grain. It is **not proposed for implementation**; see §12.

## 10. Counterfactual diagnostic (DIAGNOSTIC / COUNTERFACTUAL ONLY, not a rescore)

**Removed as demonstrated harness defects:** 16 claim-cardinality findings (D0, D1, D2, X2, Z2, Z3) and 1 Z4 scorer finding.

**Remaining:**
- structural: **none**;
- semantic: **8 NO**. These are the 5 recorded NOs (4 subjects and `Q-T2-X3`), plus the 3 recorded YES answers the audit rules wrong because they credit `K-CREDIT-4`;
- failing cases: C0, C8, U4 (subjects); X3, D4, Z2, Z3 (`K-CREDIT-4`).

So two things remain: subject naming (four addresses, one clear), and one missing operative proposition (`K-CREDIT-4`). Nothing else remains: no formation, correction, pending-state, authority, AGREE, DECLINE, repeat or facet failure.

## 11. Classification of every failure

| Item | Primary cause | Evidence |
|---|---|---|
| D0 `CLAIM_COUNT` ×7 | ORACLE_DEFECT | the one-claim bound; faithful splits `K-RES-2`, `K-UNL-4`, `K-LATE-7`; gates YES |
| D1 `CLAIM_COUNT` (RESERVATION T1) | ORACLE_DEFECT | `K-RES-2` split into `p05`/`p06` |
| D2 `CLAIM_COUNT` (UNLOCK T1) | ORACLE_DEFECT | `K-UNL-4` split into `p45`/`p46` |
| X2 `HELD_COUNT` | ORACLE_DEFECT | `K-LATE-7` split; each half retires one old claim; disposition YES |
| Z2 `CLAIM_COUNT` ×3 | ORACLE_DEFECT | carried splits; AGREE applied atomically |
| Z3 `CLAIM_COUNT` ×2 | ORACLE_DEFECT | carried splits; DECLINE applied nothing |
| Z4 `REOPENED` | HARNESS_DEFECT | scorer read SUPERSEDE `visible_evidence_ids`; production suppressed the repeat |
| `Q-T1-CORE-PICKUP` NO | MODEL_SUBJECT_NAMING_MISS | dimension ("cut-off") heading copied; v5 judged it YES |
| `Q-T1-CORE-WEIGHT` NO | MODEL_SUBJECT_NAMING_MISS | limit dimension; v5 judged it YES |
| `Q-T1-LARGE-CUSTOMER-REFUND` NO | MODEL_SUBJECT_NAMING_MISS | the subject excludes the delivery-charge claim at its own address |
| `Q-T1-LARGE-SELLER-LIMIT` NO | MODEL_SUBJECT_NAMING_MISS | limit dimension; single-claim concern; the adjudicator called it strictness-dependent |
| `Q-T2-X3-ONE-TO-MANY` NO | MODEL_SEMANTIC_MISS | `K-CREDIT-4` bundled into `p13`; the claim states the deadline only |
| (C0, C8, U4, X3 cases) | follow the rows above | — |
| Recorded YES on `Q-T1-DENSE-SERVICE-CREDIT`, `Q-AGREED-X3`, `Q-DECLINED-X3` | ORACLE_DEFECT (adjudicator leniency) | they credit the deadline claim with the refusal |

## 12. Is `intent-v2-locus-v7` needed? No: Path 1

**Why no policy change:**
- the claim-count failures are oracle-only and Z4 is harness-only;
- `K-CREDIT-4` is an ordinary semantic miss under an adequate contract; the loss is proposition → claim, not source → proposition;
- the subject rule is explicit, the misses are ordinary, and the adjudication of them is not reproducible.

No model-policy change is indicated. The next validation should run `intent-v2-locus-v6` again, under a corrected, fresh harness. The runtime-completeness question (§8) is an architecture question for the founder; it does not require a new model policy.

## 13. The next fresh validation (design only; not built, not run)

**Identity:** new, e.g. `intent-v2-locus-validation-v7`. Policy `intent-v2-locus-v6`, unchanged; correction sets enabled inside it only.

**The corrected oracle:**
- **Coverage, not cardinality:** no upper bound per sealed proposition. The deterministic guards of §4, plus the semantic claims questions; lower bounds kept.
- **Proposition → claim fidelity questions:** for every model proposition that cites two or more operative sentences, or states two or more sealed propositions, a pre-registered question compares its statement with its claim(s) at its own timepoint. It would catch a `K-CREDIT-4`.
- **Repeat and reopen by production identity:** address-based member selection, recomputed `equivalence_key`, no new set at the address. Never request-level evidence.
- **A sharper subject rubric**, as two separately answered questions: (i) does the subject exclude any claim, or any sealed proposition, of the concern's full inventory? (ii) is the subject only the name of one dimension (a heading echo included)? Each is adjudicated by **two independent adjudicators**; a disagreement is recorded and resolved conservatively (NO).

**Retained:**
- dense G2 formation (a **new** held-out domain; the Kestrel corpus is now seen);
- the v5 regression ledgers (C09, C6, U1–U4);
- 1:1, N:1, 1:N and N:M corrections;
- atomic correction sets with AGREE and DECLINE branches, the exact repeat and the changed basis;
- authority routing without checkpoints;
- source and proposition accounting (production law, TARGET_SET);
- canonical facets;
- the all-or-nothing standing;
- EXPERIMENT mode, one attempt.

**Before sealing:** the scripted oracle must also produce multi-sentence propositions and request-level `visible_evidence_ids` (the adapter's real shapes). v6's two harness defects came from the oracle not doing so.
