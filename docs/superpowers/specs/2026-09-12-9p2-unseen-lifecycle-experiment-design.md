# 9P2 Unseen Lifecycle Experiment

**Status:** Experimental structure approved in chat on 2026-09-12; written spec awaiting user review before implementation planning.

**Base branch:** `feat/intent-intelligence-v2`

**Frozen 9P2 core:** `1f89fc86cda463da676bf45603b86a7dcb458452`

**Predecessor design:** `docs/superpowers/specs/2026-09-12-contrastive-semantic-assimilation-design.md`

**Pre-experiment amendment:** `docs/superpowers/specs/2026-09-12-9p2-pre-experiment-amendment.md`

**Experiment version:** `intent-v2-contrastive-unseen-lifecycle-v1`

---

## 1. Purpose

9P established that persistent semantic state can materially reduce repeated context, but failed the longitudinal semantic-continuity gate. 9P2 introduced contrastive semantic context so the frontier reasoner can compare a current claim with the explicit old-to-new evidence transition that structurally touches it.

The next scientific question is:

> On a lifecycle that was not used to design or regress 9P2, does persistent contrastive assimilation correctly evolve existing meaning, and is the improvement attributable to the 9P2 contrastive context rather than model luck or full-history rereading?

This experiment therefore has three simultaneous goals:

1. test whether 9P2 persistent assimilation is semantically correct on an unseen lifecycle;
2. test whether 9P2 improves semantic continuity over the frozen 9P-style request shape;
3. verify that persistent assimilation remains materially cheaper in input context than reconstructing state from raw history.

The experiment is intentionally narrow. It does not test observation coverage for fresh material meaning, cross-model inheritance, general context retrieval, or 9Q.

---

## 2. Why this lifecycle is unseen

Before this spec was written, repository search at frozen core `1f89fc86cda463da676bf45603b86a7dcb458452` returned no matches for either:

- `Kestrel Delivery Worker`
- `no more than three delivery attempts in total`

The Kestrel lifecycle below did not appear in the 9P2 design, the Track A regression, the 9P live evidence, or prior Foundry benchmark fixtures.

Once this spec is committed, that wording is no longer unseen to the repository, so the scientific protection is the frozen chronology: the evidence and answer key are introduced only after the 9P2 core freeze. Production/core code must not be changed after this experiment design in response to Kestrel behavior before the live result is recorded.

---

## 3. Scientific hypotheses

### H1 — persistent semantic continuity

Arm F must correctly distinguish all three unseen lifecycle changes:

- T2: correction of an existing semantic locus;
- T3: restatement of the corrected meaning, not another correction;
- T4: correction of a different existing semantic locus.

Arm F must have **zero material continuity errors** across those three checkpoints.

### H2 — causal contribution of 9P2

Arm F must make fewer material continuity errors than the 9P-style ablation Arm A.

If F is semantically correct but A is equally correct, the experiment is **INCONCLUSIVE** about whether the contrastive compiler caused the improvement.

### H3 — context economy

Over T2-T4, Arm F input tokens must be at least 25% lower than reconstruction Arm R:

```text
F_input_tokens_T2_T4 <= 0.75 * R_input_tokens_T2_T4
```

### H4 — no correctness trade for efficiency

Arm F material continuity errors must be no greater than Arm R material errors:

```text
F_material_errors <= R_material_errors
```

---

## 4. Three arms

All arms use the same provider family and model: `xai / grok-4.6`, reasoning effort `high`, no tools, no web/search, no retry, no judge.

### Arm F — 9P2 persistent contrastive assimilation

Arm F is the system under test.

- one persistent append-only ledger across T1-T4;
- current delta only is citable evidence after T1;
- `XAIContrastiveSemanticReasoner`;
- policy version `intent-v2-9p2-v1`;
- contrastive prompt SHA256 `a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410`;
- model-facing schema SHA256 `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`;
- active claim profiles visible in Call 1;
- structural old-to-new comparison context visible in both calls where compiled;
- exactly two frontier calls per time step;
- normal 9P2 scope closure and context limits apply.

### Arm A — persistent 9P-style ablation

Arm A isolates whether 9P2's additional context actually matters.

It uses a separate persistent ledger across T1-T4, but the experiment harness deliberately projects the model-visible requests back to the old 9P semantics:

#### Call 1

- citable evidence = current delta only;
- visible addresses = active in-scope address descriptors;
- `known_claims = ()`;
- `comparison_context = empty` and is not rendered;
- allowed kinds = `BIND_TO_ADDRESS`, `CREATE_ADDRESS`.

#### Call 2

- citable evidence = current delta only;
- visible addresses = only the addresses in the applied Call-1 decision neighbourhood;
- visible claims = live claims at those addresses;
- `comparison_context = empty` and is not rendered;
- no contrastive-address widening;
- allowed kinds = `SUPPORTS_CLAIM`, `ASSERT_CLAIM`, `SUPERSEDE`, `CONFLICTS_WITH`.

Arm A uses the historical `XAISemanticReasoner`:

- policy version `intent-v2-9p-v4`;
- historical prompt SHA256 `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`;
- the same model-facing output schema SHA256 as F;
- exactly two frontier calls per time step.

This ablation must be implemented only in experiment code. It must not mutate the frozen historical 9P artifacts or change production 9P2 behavior.

### Arm R — fresh full-history reconstruction

Arm R represents starting over from raw evidence.

At each T independently:

1. create a fresh governor/ledger;
2. provide all evidence versions available through that T in chronological order as one reconstruction batch;
3. run exactly two calls through the current 9P2 assimilation path using `XAIContrastiveSemanticReasoner`;
4. discard that R ledger after recording its artifacts for that T.

R therefore receives full raw history and may also receive deterministic lineage diffs generated from that cumulative batch. It receives no durable semantic memory from the previous R time step.

R is intentionally a strong reconstruction baseline: F must remain cheaper even though R is allowed to see all raw evidence and 9P2's generic contrastive policy.

---

## 5. Frozen lifecycle: Kestrel Delivery Worker

**Project id:** `PROJ-9P2-UNSEEN-KESTREL`

**Semantic scope:** `kestrel-delivery`

All evidence is `SourceKind.DOCUMENT`.

The model receives the literal evidence text below. The hidden semantic interpretation in §6 is never inserted into a reasoner request by the harness.

### T1 — initial policies

#### EV-K-A1

`artifact_ref = kestrel/delivery-attempt-policy.md`

```text
# Delivery attempt allowance

For each delivery job, the worker may make no more than three delivery attempts in total. The first delivery attempt is included in that limit.
```

#### EV-K-B1

`artifact_ref = kestrel/retry-wait-policy.md`

```text
# Retry wait

Before starting any retry attempt, the worker waits five seconds after the preceding failed attempt.
```

#### EV-K-N1 — stable control

`artifact_ref = kestrel/final-failure-policy.md`

```text
# Final failure handling

If a delivery job still has not succeeded after its last permitted attempt, leave the job in failed state and require operator review. Do not automatically discard the job.
```

T1 delta for F/A contains exactly `(EV-K-A1, EV-K-B1, EV-K-N1)`.

T1 reconstruction evidence for R is the same tuple.

### T2 — correction at locus A

#### EV-K-A2

`artifact_ref = kestrel/delivery-attempt-policy.md`

`supersedes_evidence_id = EV-K-A1`

```text
# Delivery attempt allowance

Each delivery job begins with one original delivery attempt. If that attempt fails, the worker may make up to three additional retry attempts.
```

F/A T2 citable delta contains exactly `(EV-K-A2,)`.

R T2 reconstruction evidence contains exactly `(EV-K-A1, EV-K-B1, EV-K-N1, EV-K-A2)` in chronological order.

### T3 — semantic restatement at locus A

#### EV-K-A3

`artifact_ref = kestrel/delivery-attempt-policy.md`

`supersedes_evidence_id = EV-K-A2`

```text
# Delivery attempt allowance

A job gets one initial delivery attempt. After that initial attempt fails, no more than three retry attempts may follow.
```

F/A T3 citable delta contains exactly `(EV-K-A3,)`.

R T3 reconstruction evidence contains exactly `(EV-K-A1, EV-K-B1, EV-K-N1, EV-K-A2, EV-K-A3)`.

### T4 — correction at locus B

#### EV-K-B2

`artifact_ref = kestrel/retry-wait-policy.md`

`supersedes_evidence_id = EV-K-B1`

```text
# Retry wait

Retry waits are not fixed. Before the first retry, wait two seconds. Before each later retry, double the previous wait, but never wait more than thirty seconds.
```

F/A T4 citable delta contains exactly `(EV-K-B2,)`.

R T4 reconstruction evidence contains exactly `(EV-K-A1, EV-K-B1, EV-K-N1, EV-K-A2, EV-K-A3, EV-K-B2)`.

No additional distractor or new semantic locus is introduced. Fresh-observation coverage is deliberately outside this experiment.

---

## 6. Sealed semantic answer key

This section is post-run grading truth and leakage-gate input. It must never be inserted into a model-visible request by experiment code.

### Locus A — delivery attempt allowance

- T1 material meaning: maximum **three total attempts**, with the initial attempt included.
- T2 material meaning: one initial attempt plus up to three retries, therefore up to **four total attempts**. The T1 interpretation is no longer current.
- T3 material meaning: semantically equivalent to the T2 interpretation. It is a **restatement**, not another correction.

### Locus B — retry wait

- T1 material meaning: fixed five-second wait before every retry.
- T4 material meaning: fixed five seconds is replaced by an exponential schedule starting at two seconds, doubling for later retries, capped at thirty seconds.

### Locus N — stable control

At every T, final failure remains:

- job remains failed;
- operator review is required;
- job is not automatically discarded.

### What is not an answer-key requirement

The reasoner is free to choose predicate names, TEXT versus QUANTITY representation where the schema permits, descriptor wording, or other semantically faithful representation details. Grading is about material meaning and lifecycle continuity, not string matching.

---

## 7. Persistent-arm T1 root designation

F and A each designate their own roots after T1. No architect manually chooses a model-created address or claim.

For seed evidence `EV-K-A1`, `EV-K-B1`, and `EV-K-N1` independently:

1. derive the current semantic view;
2. collect live claim ids whose `effective_evidence` contains the seed evidence id;
3. collect the unique address ids of those claims;
4. designation succeeds only if there is exactly one unique address **and exactly one live seed-supported claim at that address**;
5. record that address id, claim id, and the claim's `created_by_judgment_id` as the root tuple.

The resulting root tuples are named:

```text
A_ROOT = (address_id, claim_id, created_by_judgment_id)
B_ROOT = (address_id, claim_id, created_by_judgment_id)
N_ROOT = (address_id, claim_id, created_by_judgment_id)
```

If any designation is zero-or-many ambiguous:

- the relevant T1 expectation fails;
- that root is recorded as `UNDESIGNATED`;
- the experiment does not ask a human to resolve the ambiguity;
- later expectations depending on that root automatically fail if they cannot be evaluated mechanically;
- the live experiment continues unless an infrastructure/runtime failure occurs.

This removes the manual root-picking weakness of 9P.

---

## 8. Mechanical authority protocol

Only persistent arms F and A can require material supersession authority.

There are two expected authority checkpoints per persistent arm:

- T2: the previously designated A root judgment;
- T4: the previously designated B root judgment.

After Call 2 for the relevant arm/time:

1. inspect pending model-proposed `SUPERSEDE` judgments;
2. filter to proposals whose `target_judgment_id` equals the exact designated root judgment for that checkpoint;
3. if and only if there is exactly one such pending proposal, the harness submits an `AGREE` under the frozen human/architect fingerprint using the **identical proposal object/signature**;
4. the harness does not inspect whether the proposed new claim is semantically correct before agreement;
5. if there are zero or multiple exact-target proposals, no agreement is submitted for that checkpoint;
6. proposals targeting any other judgment are never auto-authorized and remain evidence of model behavior.

The semantic correctness of the new claim is graded only after the run.

Maximum human authorizations: **4 total** = 2 checkpoints x 2 persistent arms.

No authority action creates a frontier/model call.

---

## 9. Frozen call order

To reduce simple provider-time ordering bias, arm order rotates by T while each persistent arm still advances T1 -> T4 in order:

```text
T1: F -> A -> R
T2: A -> R -> F
T3: R -> F -> A
T4: F -> A -> R
```

An R entry means a fresh reconstruction run for that T only.

Authority processing, if applicable, happens immediately after that arm's Call 2 and before the next scheduled arm at the same T.

No arm receives another arm's state, requests, outputs, receipts, or verdicts.

---

## 10. Material-continuity error rubric

Error counting is frozen before the run and is intentionally checkpoint-based so one semantic mistake is not multiplied into many downstream penalties.

Each arm receives at most **one material continuity error per checkpoint**.

The three checkpoints are T2-A, T3-A, and T4-B.

### F/A checkpoint C1 — T2 A correction

The checkpoint is correct only if all of the following hold for that arm:

1. the T2 observation is associated with the designated A address rather than a newly created same-locus address;
2. a new current interpretation at A materially expresses one initial attempt plus up to three retries / up to four total attempts;
3. the T1 A interpretation is not silently destroyed;
4. the exact T1 A creating judgment is proposed for supersession;
5. the T1 A interpretation does not leave the current view until the mechanical authority event applies;
6. no duplicate address representing the same A semantic locus is left current.

If any element fails, C1 contributes exactly 1 material error.

### F/A checkpoint C2 — T3 A restatement

The checkpoint is correct only if all of the following hold:

1. the T3 observation remains associated with the designated A address;
2. the current A claim continues to express the T2 meaning;
3. the T3 evidence is treated as continued support/restatement of that current meaning, including a `SUPPORTS_CLAIM` on the current A claim;
4. the current A claim is not superseded because of T3;
5. no materially duplicate new A claim/address is created for the restatement.

If any element fails, C2 contributes exactly 1 material error.

### F/A checkpoint C3 — T4 B correction

The checkpoint is correct only if all of the following hold:

1. the T4 observation is associated with the designated B address rather than a newly created same-locus address;
2. a new current interpretation at B materially expresses exponential retry delay beginning at two seconds, doubling for later retries, capped at thirty seconds;
3. the old fixed-five-second interpretation remains historical but is no longer current after authority;
4. the exact T1 B creating judgment is proposed for supersession;
5. the old B interpretation does not leave the current view until the mechanical authority event applies;
6. no duplicate address representing the same B semantic locus is left current.

If any element fails, C3 contributes exactly 1 material error.

### R checkpoint grading

R has no persistent address identity to preserve, so R is graded on reconstructed current meaning only.

- **R C1 / T2:** current reconstruction must cleanly represent one initial plus up to three retries; obsolete three-total-attempt meaning may not remain concurrently current as a competing interpretation of the same locus.
- **R C2 / T3:** current reconstruction must cleanly represent the same one-plus-three-retries meaning; obsolete or duplicate incompatible meanings may not remain current.
- **R C3 / T4:** current reconstruction must cleanly represent exponential retry delay 2 -> double -> cap 30; the fixed-five-second interpretation may not remain concurrently current as a competing interpretation of the same locus.

Each R checkpoint is binary 0/1 by the same material-error principle.

Therefore:

```text
F_material_errors in [0, 3]
A_material_errors in [0, 3]
R_material_errors in [0, 3]
```

Semantic checkpoint adjudication is performed after raw artifacts are frozen. No model judge is used.

---

## 11. Mandatory Arm F integrity expectations

In addition to `F_material_errors == 0`, all of the following are required for scientific PASS or INCONCLUSIVE:

### F1 — unique T1 roots

A, B, and N each have exactly one structurally designated root address and one seed-supported root claim after T1.

### F2 — stable control

The N control meaning remains materially unchanged through T4 and is not superseded, conflicted, or duplicated because of A/B changes.

### F3 — no semantic-repair relations

Arm F requests no `EQUIVALENT` or `DISTINCT` judgment at any T. 9P2 is being tested on correct assimilation, not post-hoc identity repair.

### F4 — non-citable historical context remains non-citable

For every F model proposal, each cited evidence id must be present in that exact request's `ReasoningRequest.evidence`. A predecessor id present only in `comparison_context` may not be cited.

### F5 — scoped visibility

Every address/claim in each F comparison context and known-object set is eligible for scope `kestrel-delivery` under the locked scope rule. No out-of-scope widening is permitted.

### F6 — two calls, no retry

Every completed F time step makes exactly two frontier calls, in order, with no third reconciliation call, hidden retry, fallback, or judge.

### F7 — replay

Replay of the complete F append-only ledger reproduces the final F state and derived view exactly.

### F8 — governance boundary

No model proposal directly applies material supersession outside existing admission rules. Current interpretation may change through supersession only after the mechanical authority protocol applies the exact pending proposal.

---

## 12. Token, cost, and call accounting

Token accounting uses provider receipts from completed calls only.

Primary economy metric:

```text
F_input_tokens_T2_T4 = sum(input_tokens for all F calls at T2,T3,T4)
R_input_tokens_T2_T4 = sum(input_tokens for all R calls at T2,T3,T4)
```

Economy passes iff:

```text
4 * F_input_tokens_T2_T4 <= 3 * R_input_tokens_T2_T4
```

The integer inequality above is authoritative and avoids floating-point ambiguity.

A-arm tokens are recorded but are not part of the PASS rule.

Locked experiment ceilings:

```text
max_frontier_calls       = 24
max_judge_calls          = 0
max_human_authorizations = 4
max_cost_usd             = 8.0
```

Completed call allocation is exactly:

```text
3 arms x 4 times x 2 calls = 24 frontier calls
```

The harness must record per-arm, per-T input tokens, output tokens, cost, and wall-clock time.

If cumulative provider-reported cost exceeds `$8.00`, the run stops immediately after recording the call that crossed the ceiling. No later call is made.

---

## 13. Scientific decision rule

A scientific decision is produced only if the run reaches `COMPLETED` with all three arms through T4 and all required artifacts present.

Otherwise the run has an operational status such as `NOT_RUN`, `ABORTED_PREFLIGHT`, `ABORTED_PROVIDER`, `ABORTED_MODEL_CONTRACT`, `ABORTED_RUNTIME`, or `ABORTED_BUDGET`; no PASS/INCONCLUSIVE/FAIL claim about H1-H4 is allowed.

For a completed run define:

```text
F_SEMANTIC = (F_material_errors == 0)
CAUSAL     = (F_material_errors < A_material_errors)
ECONOMY    = (4 * F_input_tokens_T2_T4 <= 3 * R_input_tokens_T2_T4)
NO_WORSE_R = (F_material_errors <= R_material_errors)
INTEGRITY  = all mandatory F expectations F1-F8 pass
```

### PASS

```text
PASS iff
F_SEMANTIC
AND CAUSAL
AND ECONOMY
AND NO_WORSE_R
AND INTEGRITY
```

### INCONCLUSIVE

```text
INCONCLUSIVE iff
F_SEMANTIC
AND NOT CAUSAL
AND ECONOMY
AND NO_WORSE_R
AND INTEGRITY
```

Given `F_SEMANTIC`, `NOT CAUSAL` means the ablation also had zero material continuity errors. In that case 9P2 worked, but this experiment cannot attribute the success to contrastive context.

### FAIL

Every other completed-run result is FAIL.

The decision artifact must list every failed component among:

```text
F_SEMANTIC
CAUSAL
ECONOMY
NO_WORSE_R
F1
F2
F3
F4
F5
F6
F7
F8
```

No post-run threshold changes are permitted.

---

## 14. 9P2-specific leakage gate

This section implements the pre-experiment amendment's Ruling B.

The historical 9P leakage gate is not sufficient because it deliberately omits `comparison_context`.

### 14.1 Gate timing

The 9P2 leakage gate runs during preflight **before reasoner construction and before the first live provider call**.

Any failure means:

```text
run_status = ABORTED_PREFLIGHT
frontier_calls = 0
```

### 14.2 Exact model-visible policies scanned

For F and R, scan:

- `CONTRASTIVE_SYSTEM_INSTRUCTION`;
- the real five-key request rendering with `comparison_context` included.

For A, scan:

- historical `SYSTEM_INSTRUCTION`;
- the real historical four-key request rendering with no comparison context.

### 14.3 Request skeletons

The gate must exercise every planned Call-1 and Call-2 structural shape through the real assembly/rendering path using a deterministic synthetic fixture that covers:

- T1 with no predecessor transition;
- T2/T4 correction-shaped lineage with a touched existing claim;
- T3 restatement-shaped lineage with a touched existing claim;
- F contrastive Call 1 with active claim profile;
- F contrastive Call 2 with touched claim/address;
- A Call 1 with no claims;
- A Call 2 with current claims but no comparison context;
- R cumulative-history Call 1 and Call 2.

### 14.4 Evidence-versus-harness distinction

Leakage scanning must not call legitimate immutable evidence content a harness leak.

Therefore the gate builds the skeletons with opaque evidence content placeholders, such as:

```text
<EVIDENCE:EV-K-A1>
<EVIDENCE:EV-K-A2>
```

and lets the real diff compiler generate comparison diffs from those placeholders.

Synthetic known-address descriptors and known-claim semantic fields must also use opaque placeholder values, not hidden answer-key wording.

The resulting scan still includes the real:

- system instruction;
- JSON keys;
- evidence ids;
- artifact refs;
- lineage ids;
- comparison-context keys;
- inclusion edges;
- diff headers;
- allowed judgment kinds;
- request shape and static harness-authored task text.

### 14.5 Leakage needles

The sealed needle set must include, at minimum:

1. every final expectation id/name used only for grading;
2. every full hidden answer-key statement from §6;
3. these normalized hidden conclusions:
   - `maximum four total attempts`;
   - `T3 is a restatement, not another correction`;
   - `fixed five-second wait is replaced`;
   - `exponential retry delay begins at two seconds and caps at thirty seconds`;
4. every decision-rule label from §13;
5. any additional architect-only tracked-locus wording introduced by the implementation plan.

Needles are normalized only for case and consecutive ASCII whitespace. No semantic/fuzzy matching is required.

### 14.6 Fail-closed rule

If any leakage needle appears in harness-authored model-visible text after evidence/model-output placeholders are substituted, preflight fails.

The leakage gate output records:

- needle-set SHA256;
- each rendered skeleton SHA256;
- system prompt SHA256 for each policy;
- PASS/FAIL;
- exact matched needle and skeleton id on failure.

The old historical 9P leakage gate and artifacts remain unchanged.

---

## 15. Preflight gates

Before the first live call, all gates below must PASS and be written to `preflight.json`:

1. repository HEAD equals the final experiment seal commit;
2. working tree is clean;
3. final experiment seal is a descendant of frozen 9P2 core `1f89fc86cda463da676bf45603b86a7dcb458452`;
4. frozen core semantic/domain files were not changed by the experiment harness except explicitly approved experiment-only integration points;
5. F/R policy version is exactly `intent-v2-9p2-v1`;
6. F/R contrastive prompt hash is exactly `a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410`;
7. A policy version is exactly `intent-v2-9p-v4`;
8. A prompt hash is exactly `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`;
9. semantic output schema hash is exactly `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851` for all arms;
10. `CALLS_PER_DELTA == 2` for F;
11. A experiment-only ablation runner statically/runtime-proves exactly two calls and no retry;
12. R runner uses a fresh ledger at every T;
13. evidence ids, artifact refs, supersession edges, exact contents, and content SHA256 values match the sealed manifest;
14. arm schedule matches §9;
15. call/cost/human/judge ceilings match §12;
16. hidden answer key and expectation module are not imported by provider adapters or request assembly/rendering modules;
17. the new 9P2 leakage gate in §14 passes;
18. Track A regression still passes locally;
19. scope-closure regression still passes locally;
20. no previous 9P experiment artifact is modified by the experiment harness.

No network/provider call is permitted merely to test preflight reachability.

---

## 16. Failure discipline

### Before any provider call

Any preflight failure produces `ABORTED_PREFLIGHT`, zero provider calls, and no scientific decision.

### After live execution begins

After the first provider call, any of the following stops the entire experiment immediately:

- provider/network failure;
- structured-output/schema failure;
- reference-validation failure caused by malformed model output;
- unhandled runtime exception;
- context-support refusal (`ContextUnsupported`);
- cost ceiling breach;
- manifest/seal/prompt/schema identity drift detected during execution.

On stop:

1. preserve every receipt, request, draft, decision, ledger event, and preflight artifact recorded so far;
2. make no further arm or time-step calls;
3. do not retry the failed call;
4. do not repair/model-coerce the output;
5. do not rerun under the same experiment identity;
6. record an operational abort reason, not a scientific FAIL.

A new live attempt after such an abort requires a new experiment identity and explicit architect authorization.

Semantic mistakes that are structurally valid do **not** stop the run. They are the subject of the experiment and are graded afterward.

---

## 17. Artifact contract

The experiment directory is:

`docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/`

Before live authorization it must contain sealed preregistration artifacts only. After the live run it receives raw empirical artifacts. Post-run semantic adjudication is a separate commit.

Minimum files:

```text
manifest.json
expectations.json
preflight.json
report.md
verdicts.json

F/
  requests.json
  drafts.json
  receipts.json
  decisions.json
  authorizations.json
  ledger.json
  result.json

A/
  requests.json
  drafts.json
  receipts.json
  decisions.json
  authorizations.json
  ledger.json
  result.json

R/
  T1/
    requests.json
    drafts.json
    receipts.json
    decisions.json
    ledger.json
    result.json
  T2/
    ...
  T3/
    ...
  T4/
    ...
```

### `manifest.json`

Must seal:

- experiment version;
- frozen 9P2 core SHA;
- final experiment seal SHA;
- design/spec SHA256;
- model/provider/effort;
- all policy versions and prompt hashes;
- output-schema hash;
- exact arm schedule;
- exact ceilings;
- exact evidence metadata and content SHA256 values;
- leakage needle-set SHA256;
- exact decision thresholds;
- exact artifact version.

### `expectations.json`

Contains the hidden answer key, checkpoint rubric, mandatory F expectations, and PASS/INCONCLUSIVE/FAIL rule. It is never sent to a model.

### Request artifacts

For every provider call record:

- arm;
- T;
- call number 1 or 2;
- policy version;
- system prompt SHA256;
- exact rendered user request text sent to the adapter/provider;
- citable evidence ids;
- historical comparison evidence ids;
- known address ids;
- known claim ids;
- allowed judgment kinds;
- comparison-context character count;
- request SHA256.

Do not persist API keys, authorization headers, or secrets.

### Raw-run freeze

After the live run completes or aborts, all raw artifacts are committed before architect semantic adjudication.

The raw-run commit must not alter source, tests, spec, plan, prompts, policies, or sealed preregistration files.

### Adjudication commit

Architect semantic adjudication then updates only the allowed verdict/report files in a separate commit. Raw evidence remains byte-identical.

---

## 18. Deterministic versus architect adjudication

The harness may deterministically adjudicate only structural facts such as:

- call count/order;
- exact root-designation cardinality;
- whether a specific proposal kind/target id appears;
- authority timing and route;
- cited-evidence subset checks;
- scope visibility;
- request/prompt/schema hashes;
- token/cost arithmetic;
- replay equality;
- whether `EQUIVALENT`/`DISTINCT` was requested;
- whether duplicate address ids exist as ids (not whether two differently-id'd addresses mean the same thing).

Architect adjudication is required for semantic facts such as:

- whether two addresses represent the same A or B locus;
- whether a claim materially expresses the hidden answer key;
- whether T3 is represented as semantic restatement rather than a materially different claim;
- whether R simultaneously keeps obsolete and current meanings at one semantic locus;
- the three per-arm material continuity error counts.

No model judge is used.

---

## 19. No contamination after preregistration

Once the experiment harness/manifest is sealed for live execution:

- do not edit 9P2 production behavior;
- do not edit Kestrel evidence;
- do not edit the answer key;
- do not edit the checkpoint rubric;
- do not edit thresholds;
- do not change arm order;
- do not change prompts/policies/schema;
- do not inspect a partial semantic result and then continue after repair.

Any required correction before the first live call produces a new preregistration seal but may retain the same experiment version only if **zero provider calls** have occurred and the correction does not change the scientific hypothesis/evidence/thresholds. A scientific-design change requires a new experiment version.

After any live provider call, the identity is immutable.

---

## 20. What this experiment can establish

### A PASS supports

- 9P2 persistent contrastive context can correctly evolve existing semantic meaning on this unseen lifecycle;
- the contrastive context materially improved continuity relative to the frozen 9P-style ablation on this lifecycle;
- the persistent approach retained at least 25% input-token savings versus full reconstruction;
- the improvement did not trade semantic correctness for efficiency;
- replay/governance/non-citable-history/scope boundaries held.

### INCONCLUSIVE supports only

- 9P2 itself handled the unseen lifecycle correctly and economically;
- but the ablation was equally correct, so this experiment does not establish that 9P2 caused the success.

### FAIL means

At least one preregistered semantic, causal, economy, comparative-correctness, or integrity condition failed. The exact failed conditions must be reported without post-hoc threshold changes.

### This experiment does not establish

- fresh observation coverage;
- generic software correctness;
- cross-model inheritance;
- multi-domain semantic retrieval;
- large-state retrieval beyond the 200-address support bound;
- 9Q.

---

## 21. Live-authorization gate

This design does **not** authorize a live run.

The required sequence is:

```text
written experiment spec approved
        ->
implementation plan approved
        ->
experiment harness implemented with strict TDD
        ->
local verification + independent review
        ->
manifest / evidence / expectations / leakage gate sealed
        ->
final pre-run seal commit independently verified
        ->
explicit architect live authorization
        ->
run once
```

Until the final pre-run seal is independently verified, **zero live provider/model/judge calls are authorized for this experiment**.

9Q remains unauthorized.
