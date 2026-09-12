# 9P2 Unseen Lifecycle Experiment

**Status:** Experimental structure approved in chat on 2026-09-12; written spec awaiting user review before implementation planning.

**Base branch:** `feat/intent-intelligence-v2`

**Frozen 9P2 core:** `1f89fc86cda463da676bf45603b86a7dcb458452`

**Predecessor design:** `docs/superpowers/specs/2026-09-12-contrastive-semantic-assimilation-design.md`

**Pre-experiment amendment:** `docs/superpowers/specs/2026-09-12-9p2-pre-experiment-amendment.md`

**Experiment version:** `intent-v2-contrastive-unseen-lifecycle-v1`

---

## 1. Purpose

9P established that persistent semantic state can materially reduce repeated context, but failed the longitudinal semantic-continuity gate. 9P2 introduced active claim profiles and contrastive semantic context so the frontier reasoner can compare current meaning with the explicit old-to-new evidence transition that structurally touches it.

The scientific question is:

> On a lifecycle that was not used to design or regress 9P2, does the full 9P2 model-visible treatment correctly evolve existing meaning, does it outperform the frozen 9P-style treatment, and does persistent assimilation remain materially cheaper than reconstructing state from raw history?

This experiment therefore has three goals:

1. test whether 9P2 persistent assimilation is semantically correct on an unseen lifecycle;
2. test whether the **9P2 treatment bundle** improves continuity over the frozen 9P-style request/prompt shape;
3. verify that persistent assimilation retains material input-context savings versus full-history reconstruction.

The 9P2 treatment bundle consists of:

- active claim profiles visible during Call 1;
- structural old-to-new `comparison_context`;
- the contrastive 9P2 system policy.

With only three arms, the experiment can attribute a difference to that bundle as a whole. It **cannot** isolate which one of those three ingredients caused the difference.

The experiment does not test fresh observation coverage, cross-model inheritance, general semantic retrieval, or 9Q.

---

## 2. Why this lifecycle is legitimately unseen to the frozen core

The scientific protection is chronological, not secrecy from the repository forever.

The 9P2 core was frozen at:

`1f89fc86cda463da676bf45603b86a7dcb458452`

before the Kestrel lifecycle or its hidden answer key was added to the repository. Before this spec commit, GitHub code search also returned no indexed match for `Kestrel Delivery Worker` or the exact phrase `no more than three delivery attempts in total`.

Once this spec is committed, the evidence and answer key are necessarily present in repository history. Therefore:

- production/core 9P2 behavior may not be changed in response to Kestrel outcomes before the live result is frozen;
- the experiment harness may encode the preregistered evidence and grader, but those answer-key objects must never enter the provider/request path;
- any scientific-design change after a live provider call requires a new experiment identity.

---

## 3. Scientific hypotheses

### H1 — persistent semantic continuity

Arm F must correctly distinguish all three unseen lifecycle checkpoints:

- T2: correction of an existing semantic locus;
- T3: restatement of the corrected meaning, not another correction;
- T4: correction of a different existing semantic locus.

Arm F must have **zero material continuity errors** across those three checkpoints.

### H2 — causal contribution of the 9P2 treatment bundle

Arm F must make fewer material continuity errors than the 9P-style ablation Arm A.

If F is semantically correct but A is equally correct, the result is **INCONCLUSIVE** about causal benefit from the 9P2 treatment bundle.

A F-vs-A difference must not be described as proof that `comparison_context` alone caused the improvement.

### H3 — context economy

Over T2-T4, Arm F input tokens must be at least 25% lower than reconstruction Arm R:

```text
F_input_tokens_T2_T4 <= 0.75 * R_input_tokens_T2_T4
```

The integer form in §12 is authoritative.

### H4 — comparative correctness diagnostic

Arm F material continuity errors must be no greater than Arm R material errors:

```text
F_material_errors <= R_material_errors
```

Because H1 already requires `F_material_errors == 0` for PASS/INCONCLUSIVE, H4 is diagnostically redundant on successful F runs. It is retained so a failed run records whether reconstruction was nevertheless more correct.

---

## 4. Three arms

All arms use the same provider family/model: `xai / grok-4.6`, reasoning effort `high`, no tools, no web/search, no retry, no judge.

### Arm F — 9P2 persistent contrastive assimilation

Arm F is the system under test.

- one persistent append-only ledger across T1-T4;
- after T1, current delta only is citable evidence;
- `XAIContrastiveSemanticReasoner`;
- policy version `intent-v2-9p2-v1`;
- prompt SHA256 `a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410`;
- model-facing schema SHA256 `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`;
- active claim profiles visible in Call 1;
- structural comparison context visible where compiled;
- exactly two frontier calls per time step;
- existing 200-address, scope-closure, diff, and comparison-context limits remain binding.

### Arm A — persistent 9P-style ablation

Arm A uses a separate persistent ledger across T1-T4, but an **experiment-only runner** projects the model-visible requests back to the old 9P treatment.

#### A Call 1

- citable evidence = current delta only;
- visible addresses = active in-scope address descriptors;
- `known_claims = ()`;
- no rendered `comparison_context`;
- allowed kinds = `BIND_TO_ADDRESS`, `CREATE_ADDRESS`.

#### A Call 2

- citable evidence = current delta only;
- visible addresses = only addresses in the applied Call-1 decision neighbourhood;
- visible claims = live claims at those addresses;
- no rendered `comparison_context`;
- no contrastive-address widening;
- allowed kinds = `SUPPORTS_CLAIM`, `ASSERT_CLAIM`, `SUPERSEDE`, `CONFLICTS_WITH`.

Arm A uses historical `XAISemanticReasoner`:

- policy version `intent-v2-9p-v4`;
- prompt SHA256 `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`;
- same model-facing output schema as F;
- exactly two frontier calls per T.

The ablation exists only in experiment code. It must not mutate historical 9P artifacts or production 9P2 code.

### Arm R — fresh full-history reconstruction

At every T independently:

1. create a fresh governor/ledger;
2. supply all evidence versions available through that T in the frozen chronological order in §5 as one reconstruction batch;
3. run exactly two calls through the current 9P2 assimilation path with `XAIContrastiveSemanticReasoner`;
4. record artifacts;
5. discard the R state before the next T.

R receives no semantic memory from its previous time step. It may receive deterministic lineage diffs derivable from the cumulative raw-evidence batch, making R a deliberately strong reconstruction baseline.

---

## 5. Frozen Kestrel lifecycle

**Project id:** `PROJ-9P2-UNSEEN-KESTREL`

**Semantic scope:** `("kestrel-delivery",)`

All evidence is `SourceKind.DOCUMENT`.

The literal evidence text below is model-visible. The hidden interpretation in §6 is not.

### T1 — initial policies

#### EV-K-A1

```text
source_ref  = experiment://kestrel/T1/A1
artifact_ref = kestrel/delivery-attempt-policy.md
observed_at = 2026-09-01T00:00:00Z
scope       = ("kestrel-delivery",)
```

Content:

```text
# Delivery attempt allowance

For each delivery job, the worker may make no more than three delivery attempts in total. The first delivery attempt is included in that limit.
```

#### EV-K-B1

```text
source_ref  = experiment://kestrel/T1/B1
artifact_ref = kestrel/retry-wait-policy.md
observed_at = 2026-09-01T00:01:00Z
scope       = ("kestrel-delivery",)
```

Content:

```text
# Retry wait

Before starting any retry attempt, the worker waits five seconds after the preceding failed attempt.
```

#### EV-K-N1 — stable control

```text
source_ref  = experiment://kestrel/T1/N1
artifact_ref = kestrel/final-failure-policy.md
observed_at = 2026-09-01T00:02:00Z
scope       = ("kestrel-delivery",)
```

Content:

```text
# Final failure handling

If a delivery job still has not succeeded after its last permitted attempt, leave the job in failed state and require operator review. Do not automatically discard the job.
```

F/A T1 delta is exactly:

```text
(EV-K-A1, EV-K-B1, EV-K-N1)
```

R T1 reconstruction evidence is the same tuple.

### T2 — correction at locus A

#### EV-K-A2

```text
source_ref  = experiment://kestrel/T2/A2
artifact_ref = kestrel/delivery-attempt-policy.md
supersedes_evidence_id = EV-K-A1
observed_at = 2026-09-02T00:00:00Z
scope       = ("kestrel-delivery",)
```

Content:

```text
# Delivery attempt allowance

Each delivery job begins with one original delivery attempt. If that attempt fails, the worker may make up to three additional retry attempts.
```

F/A T2 delta is exactly `(EV-K-A2,)`.

R T2 evidence is exactly:

```text
(EV-K-A1, EV-K-B1, EV-K-N1, EV-K-A2)
```

### T3 — restatement at locus A

#### EV-K-A3

```text
source_ref  = experiment://kestrel/T3/A3
artifact_ref = kestrel/delivery-attempt-policy.md
supersedes_evidence_id = EV-K-A2
observed_at = 2026-09-03T00:00:00Z
scope       = ("kestrel-delivery",)
```

Content:

```text
# Delivery attempt allowance

A job gets one initial delivery attempt. After that initial attempt fails, no more than three retry attempts may follow.
```

F/A T3 delta is exactly `(EV-K-A3,)`.

R T3 evidence is exactly:

```text
(EV-K-A1, EV-K-B1, EV-K-N1, EV-K-A2, EV-K-A3)
```

### T4 — correction at locus B

#### EV-K-B2

```text
source_ref  = experiment://kestrel/T4/B2
artifact_ref = kestrel/retry-wait-policy.md
supersedes_evidence_id = EV-K-B1
observed_at = 2026-09-04T00:00:00Z
scope       = ("kestrel-delivery",)
```

Content:

```text
# Retry wait

Retry waits are not fixed. Before the first retry, wait two seconds. Before each later retry, double the previous wait, but never wait more than thirty seconds.
```

F/A T4 delta is exactly `(EV-K-B2,)`.

R T4 evidence is exactly:

```text
(EV-K-A1, EV-K-B1, EV-K-N1, EV-K-A2, EV-K-A3, EV-K-B2)
```

No distractor or fresh semantic locus is introduced. Fresh-observation coverage is deliberately outside this experiment.

---

## 6. Sealed semantic answer key

This section is grading truth and leakage-gate input. It must never be passed into a reasoner request.

### Locus A — delivery attempt allowance

- T1: maximum **three total attempts**, initial attempt included.
- T2: one initial attempt plus up to three retries, therefore up to **four total attempts**. The old three-total interpretation is no longer current.
- T3: materially the same as T2. It is a **restatement**, not another correction.

### Locus B — retry wait

- T1: fixed five-second wait before every retry.
- T4: fixed five seconds is replaced by exponential delay starting at two seconds, doubling before later retries, capped at thirty seconds.

### Locus N — stable control

At every T:

- final unsuccessful job remains failed;
- operator review is required;
- the job is not automatically discarded.

### Representation freedom

Predicate names, descriptor wording, and valid structured value representation are not answer-key requirements. Grading concerns material meaning and lifecycle continuity, not exact strings.

---

## 7. Persistent-arm T1 root designation

F and A designate their own roots mechanically after T1. No architect chooses among model-created objects.

For each seed evidence id `EV-K-A1`, `EV-K-B1`, `EV-K-N1`:

1. derive the current semantic view;
2. collect all live claim ids whose `effective_evidence` contains that seed id;
3. map those claims to their address ids;
4. designation succeeds iff there is at least one seed-supported live claim and all such claims map to exactly one unique address;
5. record that address, **all** seed-supported live claims at it, and all of those claims' creating judgment ids, each claim/judgment collection sorted by id.

The root records are:

```text
A_ROOT = (address_id, claim_ids, creating_judgment_ids)
B_ROOT = (address_id, claim_ids, creating_judgment_ids)
N_ROOT = (address_id, claim_ids, creating_judgment_ids)
```

Multiple faithful claims at one semantic address are allowed. Representation granularity alone must not make root designation fail.

If a seed has zero supported live claims or those claims span multiple addresses:

- that root is `UNDESIGNATED`;
- the T1 root expectation fails;
- no human resolves it;
- later root-dependent conditions fail if they cannot be evaluated;
- the experiment continues unless an operational failure occurs.

---

## 8. Mechanical authority protocol

Only persistent arms F and A can need authority.

Authority checkpoints:

- T2: designated A root;
- T4: designated B root.

After the relevant Call 2:

1. inspect pending model-proposed `SUPERSEDE` judgments;
2. keep only proposals whose `target_judgment_id` is one of the checkpoint root's pre-existing `creating_judgment_ids`;
3. group them by target judgment id;
4. for each target with exactly one pending proposal, submit one human `AGREE` using the **identical proposal object/signature**;
5. if zero proposals target a root judgment, nothing is authorized for it;
6. if multiple pending proposals compete for the same target, none is auto-selected for that target;
7. proposals targeting non-root judgments are never auto-authorized;
8. the harness does not inspect whether the proposed new semantic claim is correct before agreement.

Frozen authority identity:

```text
provider       = human
model          = human://architect
policy_version = intent-v2-9p2-unseen-v1
actor_id       = architect
```

Architect grading later determines whether the reasoner superseded the materially obsolete root claim(s) and preserved any still-compatible subclaims correctly.

Human-authorization ceiling: **16** total. This is a support ceiling, not a semantic target. A normal successful lifecycle is expected to use far fewer.

No authority action is a frontier/model call.

---

## 9. Frozen arm order

Arm order rotates by T:

```text
T1: F -> A -> R
T2: A -> R -> F
T3: R -> F -> A
T4: F -> A -> R
```

Each persistent arm still advances T1 -> T4 in order. Each R entry is a new fresh reconstruction for that T.

Authority processing happens immediately after that persistent arm's Call 2 and before the next scheduled arm.

No arm receives another arm's state, outputs, requests, receipts, or verdicts.

---

## 10. Material-continuity error rubric

Each arm receives at most one material error per checkpoint, preventing one underlying semantic mistake from being multiplied into many downstream penalties.

Checkpoints:

```text
C1 = T2 / locus A correction
C2 = T3 / locus A restatement
C3 = T4 / locus B correction
```

### F/A C1 — T2 A correction

Correct iff all materially applicable conditions hold:

1. T2 remains at the designated A address rather than creating a duplicate same-locus address;
2. current A meaning expresses one initial attempt plus up to three retries / up to four total attempts;
3. pre-T2 A claims remain readable historical state;
4. every pre-T2 A root claim whose material meaning is incompatible with T2 is targeted for governed supersession;
5. no still-compatible A subclaim is required to be superseded merely because it shares the root evidence;
6. incompatible old A meaning does not leave the current view before authority;
7. after authority, no incompatible three-total-attempt interpretation remains current;
8. no duplicate current A identity represents the corrected meaning.

Any failure contributes exactly 1 C1 error.

### F/A C2 — T3 A restatement

Correct iff:

1. T3 remains at the designated A address;
2. current A meaning still expresses the T2 one-plus-three-retries interpretation;
3. T3 produces `SUPPORTS_CLAIM` for the current A meaning;
4. the current corrected A claim is not superseded merely because of T3;
5. no materially duplicate A claim/address is created for the restatement.

Any failure contributes exactly 1 C2 error.

### F/A C3 — T4 B correction

Correct iff all materially applicable conditions hold:

1. T4 remains at the designated B address rather than creating a duplicate same-locus address;
2. current B meaning expresses exponential retry delay beginning at two seconds, doubling before later retries, capped at thirty seconds;
3. pre-T4 B claims remain readable historical state;
4. every pre-T4 B root claim whose material meaning is incompatible with T4 is targeted for governed supersession;
5. no still-compatible B subclaim is required to be superseded merely because it shares the root evidence;
6. incompatible fixed-five-second meaning does not leave the current view before authority;
7. after authority, incompatible fixed-five-second meaning is no longer current;
8. no duplicate current B identity represents the corrected meaning.

Any failure contributes exactly 1 C3 error.

### R grading

R has no persistent address identity requirement.

- **R C1 / T2:** current reconstruction cleanly represents one initial plus up to three retries; obsolete three-total-attempt meaning may not remain concurrently current as a competing interpretation of the same locus.
- **R C2 / T3:** current reconstruction cleanly represents the same one-plus-three-retries meaning; obsolete or incompatible duplicate meaning may not remain current.
- **R C3 / T4:** current reconstruction cleanly represents exponential retry delay `2 -> double -> cap 30`; fixed-five-second meaning may not remain concurrently current as a competing interpretation of the same locus.

Thus:

```text
F_material_errors in [0,3]
A_material_errors in [0,3]
R_material_errors in [0,3]
```

Semantic checkpoint adjudication occurs only after raw artifacts are frozen. There is no model judge.

---

## 11. Mandatory Arm F integrity expectations

PASS or INCONCLUSIVE also requires every item below.

### F1 — unique T1 root addresses

A, B, and N each designate exactly one root address by §7.

### F2 — stable control

N remains materially unchanged through T4 and is not spuriously superseded, conflicted, or duplicated because of A/B changes.

### F3 — allowed operation boundary

Every F request uses only the locked two-call judgment sets. No relationship-repair phase, `EQUIVALENT`/`DISTINCT` call, third reconciliation call, or hidden semantic repair is introduced.

### F4 — non-citable historical context

For every F proposal, each cited evidence id must be present in that exact request's `ReasoningRequest.evidence`. A predecessor present only in `comparison_context` is non-citable.

### F5 — scoped visibility

Every address/claim exposed in F is eligible for `("kestrel-delivery",)` under the locked scope rule. Contrastive context may not widen across scope.

### F6 — exactly two calls, no retry

Each completed F T makes exactly two calls, in order, with no retry/fallback/judge.

### F7 — exact replay

Replay of F's final append-only ledger reproduces final F state and derived view exactly.

### F8 — governance boundary

No model directly applies material supersession. Incompatible old meaning leaves the current view only through existing admission plus the mechanical authority protocol.

---

## 12. Token, cost, and call accounting

Primary token totals:

```text
F_input_tokens_T2_T4 = sum(input_tokens of all F calls at T2,T3,T4)
R_input_tokens_T2_T4 = sum(input_tokens of all R calls at T2,T3,T4)
```

Economy passes iff the exact integer inequality holds:

```text
4 * F_input_tokens_T2_T4 <= 3 * R_input_tokens_T2_T4
```

A tokens are recorded but not decision-bearing.

Locked ceilings:

```text
max_frontier_calls       = 24
max_judge_calls          = 0
max_human_authorizations = 16
max_cost_usd             = 8.0
```

A completed run uses exactly:

```text
3 arms * 4 times * 2 calls = 24 frontier calls
```

Record per arm/T/call:

- input tokens;
- output tokens;
- cost USD;
- wall-clock time;
- draft count.

If cumulative provider-reported cost exceeds `$8.00`, record that call and stop before any later call.

---

## 13. Scientific decision rule

A scientific decision exists only if all three arms complete through T4 with required artifacts.

Operationally incomplete runs receive an abort/not-run status and **no** scientific PASS/INCONCLUSIVE/FAIL.

For a completed run define:

```text
F_SEMANTIC = (F_material_errors == 0)
CAUSAL     = (F_material_errors < A_material_errors)
ECONOMY    = (4 * F_input_tokens_T2_T4 <= 3 * R_input_tokens_T2_T4)
NO_WORSE_R = (F_material_errors <= R_material_errors)
INTEGRITY  = all F1..F8 pass
```

### PASS

```text
F_SEMANTIC
AND CAUSAL
AND ECONOMY
AND NO_WORSE_R
AND INTEGRITY
```

### INCONCLUSIVE

```text
F_SEMANTIC
AND NOT CAUSAL
AND ECONOMY
AND NO_WORSE_R
AND INTEGRITY
```

Given `F_SEMANTIC`, `NOT CAUSAL` means A also has zero material continuity errors. The experiment then shows that 9P2 handled the unseen lifecycle, but not that the treatment bundle caused the success.

### FAIL

Every other completed-run outcome.

The decision artifact names each failed component among:

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

Thresholds may not change post-run.

---

## 14. 9P2-specific leakage gate

This implements Ruling B of the pre-experiment amendment.

### 14.1 Timing

The gate runs before reasoner construction and before any live provider call.

Failure means:

```text
run_status = ABORTED_PREFLIGHT
frontier_calls = 0
```

### 14.2 Exact policies scanned

F and R:

- `CONTRASTIVE_SYSTEM_INSTRUCTION`;
- real five-key request rendering with `comparison_context` included.

A:

- historical `SYSTEM_INSTRUCTION`;
- historical four-key rendering with no comparison context.

### 14.3 Structural skeleton coverage

Using real request assembly/rendering and a deterministic synthetic fixture, scan at least:

- T1 with no predecessor transition;
- correction-shaped lineage touching an existing claim;
- restatement-shaped lineage touching an existing claim;
- F contrastive Call 1 with active claim profile;
- F contrastive Call 2 with touched claim/address;
- A Call 1 with no claims;
- A Call 2 with current claims and no comparison context;
- R cumulative-history Call 1 and Call 2.

### 14.4 Evidence/model-state versus harness text

Legitimate evidence content and model-generated semantic wording are not harness leakage.

Synthetic evidence content must therefore be opaque placeholders such as:

```text
<EVIDENCE:EV-K-A1>
<EVIDENCE:EV-K-A2>
```

Real diff code generates diffs from those placeholders.

Synthetic address descriptors and claim semantic fields also use opaque values.

The scan still includes real:

- system instruction;
- JSON/request keys;
- evidence ids;
- artifact refs;
- lineage ids;
- allowed kinds;
- comparison-context keys;
- inclusion edges;
- diff headers;
- static harness-authored request text.

### 14.5 Sealed leakage needles

Needles include at minimum:

1. every grading-only expectation/decision label;
2. every full hidden answer-key sentence in §6;
3. normalized conclusions:
   - `maximum four total attempts`;
   - `T3 is a restatement, not another correction`;
   - `fixed five-second wait is replaced`;
   - `exponential retry delay begins at two seconds and caps at thirty seconds`;
4. any additional architect-only tracked-locus wording introduced by the implementation plan.

Normalization is limited to case folding and collapsing consecutive ASCII whitespace. No semantic/fuzzy matching.

### 14.6 Fail closed and record

If any needle appears in harness-authored model-visible text after evidence/model-state placeholders are substituted, preflight fails.

Record:

- needle-set SHA256;
- each skeleton SHA256;
- policy prompt hashes;
- PASS/FAIL;
- matched needle and skeleton id if failed.

Historical 9P leakage artifacts remain unchanged.

---

## 15. Preflight gates

Before the first live call, write all results to `preflight.json` and require PASS for every gate:

1. repository HEAD equals the final experiment seal commit;
2. working tree clean;
3. seal descends from frozen core `1f89fc86cda463da676bf45603b86a7dcb458452`;
4. relative to frozen core, the experiment work changes **nothing** under `src/foundry/domain/`, `src/foundry/application/`, `src/foundry/ports/`, or `src/foundry/adapters/`; experiment logic may live under `src/foundry/experiments/`, scripts, tests, and experiment docs/artifacts only;
5. F/R policy = `intent-v2-9p2-v1`;
6. F/R prompt hash = `a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410`;
7. A policy = `intent-v2-9p-v4`;
8. A prompt hash = `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`;
9. all arms use output-schema hash `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`;
10. F uses `CALLS_PER_DELTA == 2`;
11. A experiment runner proves exactly two calls/no retry;
12. every R T starts from a fresh ledger;
13. evidence ids, metadata, exact content, supersession links, ordering, and content SHA256 values equal the sealed manifest;
14. arm schedule equals §9;
15. ceilings equal §12;
16. provider/request-path modules do not import the answer-key/expectation module;
17. §14 leakage gate passes;
18. Track A regression passes locally;
19. scope-closure regression passes locally;
20. previous 9P experiment artifacts are unchanged.

No provider/network call is allowed merely for reachability testing.

---

## 16. Failure discipline

### Before first live provider call

Any failed preflight gate produces `ABORTED_PREFLIGHT`, zero calls, no scientific decision.

### After live execution begins

The entire experiment stops immediately after recording any:

- provider/network failure;
- structured-output/schema failure;
- malformed reference-validation failure;
- unhandled runtime failure;
- `ContextUnsupported` refusal;
- authority-ceiling breach;
- budget ceiling breach;
- prompt/schema/manifest/seal identity drift.

Then:

1. preserve all artifacts already produced;
2. make no later arm/T calls;
3. do not retry;
4. do not coerce/repair model output;
5. do not rerun under the same experiment identity;
6. record an operational abort reason, not scientific FAIL.

Semantically wrong but structurally valid model behavior does not stop the run; it is graded afterward.

Operational statuses include:

```text
NOT_RUN
ABORTED_PREFLIGHT
ABORTED_PROVIDER
ABORTED_MODEL_CONTRACT
ABORTED_RUNTIME
ABORTED_AUTHORITY_CEILING
ABORTED_BUDGET
COMPLETED
```

---

## 17. Artifact contract

Experiment directory:

`docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/`

### 17.1 Sealed preregistration artifacts before live authorization

Before live authorization, the directory contains at minimum:

```text
manifest.json
expectations.json
```

Both are sealed and immutable once the final pre-run seal is created.

`manifest.json` seals:

- experiment version;
- frozen core SHA;
- final experiment seal SHA handling rule;
- spec SHA256;
- model/provider/effort;
- all policy versions/prompt hashes;
- output-schema hash;
- exact arm schedule;
- exact ceilings;
- evidence metadata/content SHA256 values;
- leakage needle-set SHA256;
- exact decision thresholds;
- artifact version.

`expectations.json` contains the hidden answer key, checkpoint rubric, F1-F8, and the PASS/INCONCLUSIVE/FAIL rule. It is not model-visible.

The manifest seal must not depend on a field that can only be known after T1 model output. T1 root designations belong in raw result artifacts, not in the sealed manifest.

### 17.2 Raw live artifacts

The live invocation creates:

```text
preflight.json
verdicts.json
report.md

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

`verdicts.json` may contain deterministic verdicts and null/unadjudicated architect-semantic fields at the raw-freeze stage.

### 17.3 Per-call request record

Record for every provider call:

- arm;
- T;
- call number;
- policy version;
- system prompt SHA256;
- exact rendered user request text;
- request SHA256;
- citable evidence ids;
- historical comparison evidence ids;
- known address ids;
- known claim ids;
- allowed judgment kinds;
- comparison-context character count.

No API key, auth header, or secret may be persisted.

### 17.4 Raw-run freeze

After a live run completes or aborts, commit raw empirical artifacts **before** architect semantic adjudication.

The raw-run commit may not change:

- source;
- tests;
- scripts;
- spec;
- plan;
- prompts/policies;
- `manifest.json`;
- `expectations.json`;
- previous experiment artifacts.

### 17.5 Adjudication commit

Architect semantic adjudication is a separate commit that may update only the specifically allowed verdict/report files. Raw requests, receipts, drafts, decisions, ledgers, results, preflight, manifest, and expectations remain byte-identical.

---

## 18. Deterministic versus architect adjudication

Deterministic machinery may adjudicate:

- call count/order;
- root-address designation cardinality;
- proposal kind/target ids;
- authority timing/routes;
- evidence-reference subset law;
- scope visibility;
- prompt/schema/request hashes;
- token/cost arithmetic;
- replay equality;
- allowed judgment-kind boundaries.

Architect adjudication is required for:

- whether two differently-id'd addresses denote one A/B locus;
- whether a claim materially matches the hidden answer key;
- which pre-change subclaims are materially incompatible versus still compatible;
- whether T3 is a genuine restatement in the model's current semantic state;
- whether R concurrently preserves obsolete and current meanings at one locus;
- C1/C2/C3 material-error counts for F/A/R;
- stable-control semantic correctness.

No model judge is used.

---

## 19. No contamination after preregistration

After the final experiment seal:

- no 9P2 production change;
- no evidence edit;
- no answer-key/rubric edit;
- no threshold edit;
- no arm-order edit;
- no prompt/policy/schema edit;
- no partial-result repair then continuation.

Before the first live call, a non-scientific harness defect may be repaired and resealed under the same experiment version only if the evidence, hypotheses, answer key, rubrics, thresholds, policies, and arm semantics are unchanged.

Any scientific-design change requires a new experiment version.

After the first live call, any correction requires a new experiment identity and explicit architect authorization.

---

## 20. What the result can establish

### PASS supports

- 9P2 persistent assimilation correctly handled this unseen lifecycle;
- the **9P2 treatment bundle** improved continuity relative to the frozen 9P-style ablation on this lifecycle;
- F retained at least 25% input-token savings versus reconstruction;
- replay/governance/non-citable-history/scope boundaries held.

PASS does **not** isolate which 9P2 ingredient caused the benefit.

### INCONCLUSIVE supports

- F handled the unseen lifecycle correctly and economically;
- A was equally semantically correct, so causal benefit from the 9P2 treatment bundle was not established.

### FAIL means

At least one preregistered semantic, causal, economy, comparative, or integrity condition failed. Report the exact failed conditions without threshold changes.

### Not established here

- fresh-observation coverage;
- generic software correctness;
- cross-model inheritance;
- large-state retrieval beyond the existing support bound;
- 9Q.

---

## 21. Live-authorization gate

This design does **not** authorize a live run.

Required sequence:

```text
written spec approved
  -> implementation plan approved
  -> experiment harness implemented with strict TDD
  -> local verification and independent review
  -> manifest / expectations / leakage gate sealed
  -> final pre-run seal independently verified
  -> explicit architect live authorization
  -> one live run
```

Until final pre-run seal verification, **zero live provider/model/judge calls are authorized for this experiment**.

9Q remains unauthorized.
