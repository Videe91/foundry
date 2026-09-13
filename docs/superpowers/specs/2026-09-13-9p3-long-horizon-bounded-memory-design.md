# 9P3 — Long-Horizon Bounded Memory Experiment

**Status:** DESIGN SPEC — awaiting architect review before implementation planning

**Base branch:** `feat/intent-intelligence-v2`

**Predecessor evidence commit:** `201198f60c51e16269451e7d582027361d7e8a24` (frozen completed raw artifacts of `intent-v2-contrastive-unseen-lifecycle-v3`)

**Frozen 9P2 core:** `1f89fc86cda463da676bf45603b86a7dcb458452`

**Predecessor designs:** `docs/superpowers/specs/2026-09-12-contrastive-semantic-assimilation-design.md`, `docs/superpowers/specs/2026-09-12-9p2-pre-experiment-amendment.md`, `docs/superpowers/specs/2026-09-12-9p2-unseen-lifecycle-experiment-design.md`

**Experiment version (to be sealed by the implementation):** `intent-v2-long-horizon-bounded-memory-v1`

This document is a design specification only. It authorizes no implementation, no implementation plan, no production change and no provider call.

---

## 1. Purpose

9P3 is an **architecture-selection experiment**. It does not defend 9P2; it decides which memory architecture Foundry should keep as project history grows.

Three strategies compete on one long synthetic project history:

| Arm | Strategy |
|---|---|
| **F** | persistent contrastive semantic memory — one append-only semantic ledger carried across every version, with active claim profiles and structural old-to-new comparison context (the 9P2 treatment) |
| **A** | persistent non-contrastive semantic memory — the same persistent ledger, but the historical 9P request shape: no claim profiles in Call 1, no comparison context, no contrastive widening |
| **R** | fresh reconstruction — at every version a new ledger is built from the cumulative raw evidence, carrying no semantic state from the previous reconstruction |

Primary questions:

1. Which persistent strategy should Foundry keep, F or A?
2. Can persistent semantic context remain approximately bounded as history becomes long?
3. Does fresh reconstruction grow materially with history?
4. Does contrastive context earn its additional complexity and token cost?

**Selection law:** if A matches F semantically and is meaningfully cheaper (the frozen 5 % margin of §16.1), **SELECT A**; semantic correctness dominates cost in every comparison (§16). The experiment has no favored arm. It succeeds when it yields an honest architecture decision, whichever that is.

### 1.1 What 9P2 established and what it did not

The completed `intent-v2-contrastive-unseen-lifecycle-v3` run (raw artifacts frozen at `201198f`) recorded, operationally: `frontier_calls = 24`, `provider_cost_usd = 0.490336`, `human_authorizations = 4`, `operational_status = COMPLETED`, deterministic integrity verdicts F1 and F3–F8 all `true`.

Architect adjudication of those frozen artifacts (reported to this design; the adjudication commit is separate from `201198f`, whose `verdicts.json` still records the semantic fields as pending) found:

- F material semantic errors = 0 — F handled the 3-total → 4-total correction, the same-locus restatement, the fixed-5-second → exponential retry correction, governed supersession, stable semantic identity and exact replay;
- A material semantic errors = 0 — the non-contrastive persistent arm handled the same lifecycle correctly;
- R material semantic errors = 3 — reconstruction retained obsolete and corrected meanings concurrently current at multiple checkpoints.

The preregistered 9P2 decision is therefore **FAIL**, for two reasons that this experiment inherits as open questions:

1. `CAUSAL` was not established: A was as correct as F, so the 9P2 treatment bundle showed no causal benefit on that lifecycle.
2. `ECONOMY` failed: F input tokens T2–T4 = 29,800 versus R = 30,772; the rule `4·F ≤ 3·R` required at least 25 % savings; the observed saving was ≈ 3.2 %. (A used 24,558 input tokens over T2–T4, ≈ 20 % below R — also short of 25 %. R's per-T input grew 9,639 → 10,252 → 10,881 across T2–T4.)

What is established: persistent Foundry semantics worked (F and A were both correct; governance, replay, scope closure and non-citability held). What is **not** established: whether contrastive context is necessary, and whether persistent state becomes materially cheaper than reconstruction over a genuinely long history. A four-version lifecycle is too short to separate a constant overhead from a growth trend. 9P3 lengthens the history to sixteen versions and twelve loci so that both questions can be answered with preregistered thresholds.

### 1.2 Design philosophy

- Do not add Foundry architecture yet.
- Do not optimize the contrastive compiler yet.
- Do not assume F is the desired winner.
- Measure both persistent arms independently; never report `min(F, A)`.
- Every threshold is fixed here, before any live call, and is never revised after results are seen.

---

## 2. Foundry laws that remain frozen

The following hold for every arm and every call. They are not experimental variables.

1. Exactly two frontier calls per delta (Call 1: `BIND_TO_ADDRESS | CREATE_ADDRESS`; Call 2: `SUPPORTS_CLAIM | ASSERT_CLAIM | SUPERSEDE | CONFLICTS_WITH`).
2. No judge model.
3. No same-cell retry.
4. No provider retry introduced by the experiment.
5. No tools; no web/search.
6. No embeddings; no vector database; no lexical semantic matching.
7. No deterministic semantic correction classification.
8. No third reconciliation call; no hidden semantic repair.
9. No new durable semantic primitive; no reducer redesign; no authority redesign; no semantic-event redesign.
10. Comparison-context historical evidence remains non-citable; only ids in `ReasoningRequest.evidence` are citable.
11. AI proposes meaning; Foundry governs durable state.
12. The existing support bounds stay binding: 200 active in-scope addresses, 65,536 characters per transition diff, 131,072 characters of total comparison context, scope closure (pre-experiment amendment Ruling A).

---

## 3. Synthetic project: Orion Job Execution Service

Orion is one realistic, evolving software specification for an asynchronous job-execution service: jobs are enqueued, delivered to workers under a lease, executed with bounded attempts and timeouts, retried with a delay policy, de-duplicated by job id and idempotency key, cancellable, escalated to operators on repeated failure, ordered within partitions and audited.

The specification contains exactly twelve stable semantic loci. Each locus is one section of the specification and one `artifact_ref` throughout the experiment:

| Locus | Subject | `artifact_ref` |
|---|---|---|
| A | maximum execution attempts | `orion/spec/A-execution-attempts.md` |
| B | retry delay / backoff | `orion/spec/B-retry-delay.md` |
| C | per-attempt timeout | `orion/spec/C-attempt-timeout.md` |
| D | duplicate-delivery handling | `orion/spec/D-duplicate-delivery.md` |
| E | idempotency-key lifetime | `orion/spec/E-idempotency-keys.md` |
| F | worker lease duration | `orion/spec/F-worker-lease.md` |
| G | lease-renewal rule | `orion/spec/G-lease-renewal.md` |
| H | cancellation semantics | `orion/spec/H-cancellation.md` |
| I | final failure / dead-letter behavior | `orion/spec/I-final-failure.md` |
| J | operator escalation threshold | `orion/spec/J-operator-escalation.md` |
| K | ordering guarantee | `orion/spec/K-ordering.md` |
| L | audit-retention period | `orion/spec/L-audit-retention.md` |

The locus letter **F** (worker lease) is a specification section; the arm letter **F** (contrastive arm) is an experiment arm. The document always says "locus F" or "Arm F" where ambiguity is possible.

Each version of the specification is the ordered set of its twelve sections. Every section has the shape:

```text
<heading>

<explanatory prose: one or two paragraphs describing intent and context>

Normative rule
<one or more numbered normative statements using "must"/"must not">

Example
<one short worked example>
```

Prose and examples are non-normative. Only the "Normative rule" block carries meaning that a checkpoint grades. Restatements change the wording of a normative rule without changing what it requires; corrections change what it requires.

---

## 4. T1 baseline

Version T1 establishes the twelve baseline meanings. Document order at T1 is A, B, C, D, E, F, G, H, I, J, K, L. The exact section texts are frozen below; the implementation must reproduce them byte-for-byte (a single trailing newline terminates each section; headings, blank lines and numbering are part of the bytes).

### 4.1 Section A (T1)

```text
## 1. Execution attempts

Every job admitted to Orion is executed by a worker. An execution attempt is one delivery of the job to a worker that either succeeds, fails, or times out. Orion bounds the number of attempts so that a job that cannot succeed does not consume worker capacity forever.

Normative rule
1. A job must be executed at most three times in total.
2. The first execution counts as one of the three.
3. When the third execution has ended without success, no further execution of that job may be started.

Example
A job whose first two executions fail is executed a third time. If that execution also fails, the job has exhausted its attempts.
```

### 4.2 Section B (T1)

```text
## 2. Retry delay

After an execution attempt fails, Orion waits before delivering the job again. The wait gives transient downstream faults time to clear without hammering the dependency that just failed.

Normative rule
1. Before every retry attempt the worker must wait exactly five seconds, measured from the end of the failed attempt.
2. The wait must not be shortened or lengthened based on the attempt number.

Example
An attempt fails at 10:00:00. The next attempt may start no earlier than 10:00:05. If that attempt also fails at 10:00:20, the following attempt may start no earlier than 10:00:25.
```

### 4.3 Section C (T1)

```text
## 3. Attempt timeout

A worker that hangs must not hold a job indefinitely. Each attempt is bounded by a timeout after which the attempt is treated as failed and the retry policy applies.

Normative rule
1. Each execution attempt must time out after thirty seconds of execution.
2. An attempt that reaches the timeout must be recorded as a failed attempt.

Example
An attempt starts at 12:00:00 and has not completed by 12:00:30. Orion records the attempt as failed at 12:00:30.
```

### 4.4 Section D (T1)

```text
## 4. Duplicate delivery

Producers may deliver the same job more than once, for example after a network timeout on the producer side. Orion must not execute a job twice because of such redelivery.

Normative rule
1. While a job with a given job id is active, any further delivery carrying the same job id must be ignored.
2. Ignoring a duplicate delivery must not change the state of the active job.

Example
Job J-17 is delivered at 09:00 and is executing. A second delivery of J-17 arrives at 09:01 and is ignored; J-17 continues unaffected.
```

### 4.5 Section E (T1)

```text
## 5. Idempotency keys

Each delivery may carry an idempotency key chosen by the producer. Orion remembers keys for a bounded period so that repeated deliveries with the same key can be recognised.

Normative rule
1. Orion must retain each idempotency key for twenty-four hours after it is first seen.
2. After the retention period the key may be forgotten and a later delivery with the same key is treated as new.

Example
Key K-9 is first seen on Monday at 08:00. A delivery with K-9 on Monday at 20:00 is recognised as a repeat. A delivery with K-9 on Tuesday at 09:00 is treated as new.
```

### 4.6 Section F (T1)

```text
## 6. Worker lease

A worker that receives a job holds a lease on it. The lease is how Orion knows that the job is being worked on and prevents a second worker from taking it.

Normative rule
1. A worker lease must last sixty seconds from the moment the job is delivered to the worker.
2. When the lease expires without renewal or release, the job must become available to other workers.

Example
A worker receives job J-4 at 14:00:00 and neither renews nor releases it. At 14:01:00 the lease expires and J-4 may be delivered to another worker.
```

### 4.7 Section G (T1)

```text
## 7. Lease renewal

Long-running work must be able to keep its lease. A worker renews the lease to signal that it is still progressing.

Normative rule
1. A worker may renew its lease every thirty seconds while work on the job is progressing.
2. A renewal must extend the lease by the full lease duration from the moment of renewal.

Example
A worker holding a sixty-second lease that started at 14:00:00 renews at 14:00:30; the lease now runs until 14:01:30.
```

### 4.8 Section H (T1)

```text
## 8. Cancellation

A producer or operator may cancel a job. Cancellation stops Orion from investing further effort in the job, but Orion does not forcibly abort work that a worker is already performing.

Normative rule
1. After a job is cancelled, no future execution attempt of that job may be started.
2. Cancellation must not interrupt an execution attempt that is already running; that attempt runs to its own completion, failure or timeout.

Example
Job J-8 is cancelled while its second attempt is running. The second attempt continues; when it ends, no third attempt is started.
```

### 4.9 Section I (T1)

```text
## 9. Final failure handling

When a job has used all of its attempts without success, Orion must decide what happens to it. Orion parks such jobs where they can be inspected without blocking the queue.

Normative rule
1. After the final unsuccessful execution attempt, Orion must automatically move the job to the dead-letter queue.
2. A job in the dead-letter queue must not be executed again unless explicitly resubmitted.

Example
Job J-2 fails its last permitted attempt at 16:05. Orion moves J-2 to the dead-letter queue at 16:05 without operator involvement.
```

### 4.10 Section J (T1)

```text
## 10. Operator escalation

Repeated dead-letter events for one tenant usually indicate a systemic fault rather than isolated bad jobs. Orion escalates to an operator when the rate of such events crosses a threshold.

Normative rule
1. When three dead-letter events occur for the same tenant within one hour, Orion must raise an operator escalation.
2. The one-hour window must be measured from the first of the three events.

Example
Tenant T-1 accumulates dead-letter events at 10:05, 10:40 and 10:55. The third event is within one hour of the first, so an escalation is raised.
```

### 4.11 Section K (T1)

```text
## 11. Queue ordering

Producers sometimes depend on jobs being executed in the order they were enqueued. Orion guarantees ordering only where it can do so without serialising the whole service.

Normative rule
1. First-in-first-out execution order must be guaranteed only among jobs in the same queue partition.
2. No ordering guarantee is made between jobs in different partitions.

Example
Jobs J-10 and J-11 are enqueued in that order into partition P-3; J-10 begins execution before J-11. Job J-12 in partition P-4 may begin before or after either.
```

### 4.12 Section L (T1)

```text
## 12. Audit retention

Every state transition of a job is recorded as an audit event. Audit events support incident investigation and tenant reporting, and are retained for a bounded period.

Normative rule
1. Audit events must be retained for thirty days after they are recorded.
2. After thirty days an audit event may be deleted.

Example
An audit event recorded on 1 March may be deleted on or after 31 March.
```

### 4.13 Baseline meanings (grading reference; not model-visible)

| Locus | T1 meaning |
|---|---|
| A | maximum 3 total execution attempts, initial attempt included |
| B | fixed 5-second wait before every retry |
| C | each execution attempt times out after 30 seconds |
| D | a duplicate delivery with the same job id is ignored while an existing job is active |
| E | idempotency keys retained for 24 hours |
| F | worker lease duration 60 seconds |
| G | worker may renew the lease every 30 seconds while work is progressing |
| H | cancellation prevents future attempts but does not interrupt an attempt already executing |
| I | after the final unsuccessful attempt the job is automatically moved to the dead-letter queue |
| J | operator escalation after 3 dead-letter events for the same tenant within 1 hour |
| K | FIFO ordering guaranteed only within one queue partition |
| L | audit events retained for 30 days |

---

## 5. Versions T2–T16

Each version is derived from the previous one. Unless a version says otherwise, every section is carried forward **byte-identical** from the previous version and still receives a new versioned evidence record (§7). Where a section is replaced, its full replacement text is frozen here.

### T2 — locus C restatement

Section C is replaced by:

```text
## 3. Attempt timeout

A worker that hangs must not hold a job indefinitely. Each attempt is bounded by a timeout after which the attempt is treated as failed and the retry policy applies.

Normative rule
1. An individual execution may run for no longer than half a minute; when that limit is reached the execution must be stopped.
2. An execution stopped at the limit must be recorded as a failed attempt.

Example
An execution starts at 12:00:00 and is still running at 12:00:30. Orion stops it and records a failed attempt at 12:00:30.
```

Meaning: unchanged (30-second per-attempt timeout). Expected persistent lifecycle: same C address; `SUPPORTS_CLAIM`; no duplicate current claim; no supersession.

### T3 — locus A correction

Section A is replaced by:

```text
## 1. Execution attempts

Every job admitted to Orion is executed by a worker. An execution attempt is one delivery of the job to a worker that either succeeds, fails, or times out. Orion bounds the number of attempts so that a job that cannot succeed does not consume worker capacity forever.

Normative rule
1. Each job begins with one initial execution.
2. If the initial execution does not succeed, the worker may perform up to three retry executions of that job.
3. When the third retry has ended without success, no further execution of that job may be started.

Example
A job's initial execution fails, and so do its first and second retries. A third retry is performed. If that retry also fails, the job has exhausted its attempts.
```

Meaning: one initial attempt plus up to three retries, i.e. **maximum 4 total attempts**; the 3-total meaning is no longer current. Expected: same A address; assert the corrected 4-total meaning; the incompatible 3-total meaning is superseded through human authority.

### T4 — semantic no-op (structural rewrite)

Every section is replaced. Sections are regrouped and reordered, headings are renamed, all explanatory prose and examples are rewritten, and **no normative meaning changes**. Document order at T4 becomes A, C, B, F, G, H, D, E, K, I, J, L. The twelve replacement texts:

```text
## Execution — attempt budget

Orion delivers each job to a worker for execution. One delivery that ends in success, failure or timeout is an execution. Because some jobs can never succeed, the number of executions per job is capped.

Normative rule
1. Each job begins with one initial execution.
2. If the initial execution does not succeed, the worker may perform up to three retry executions of that job.
3. When the third retry has ended without success, no further execution of that job may be started.

Example
Job Q-31 fails on its initial execution and on three retries. Q-31 is not executed a fifth time.
```

```text
## Execution — time limit per execution

Workers can stall. To keep a stalled worker from holding a job forever, every execution is subject to a time limit, after which the execution is treated as a failure and the retry rules take over.

Normative rule
1. An individual execution may run for no longer than half a minute; when that limit is reached the execution must be stopped.
2. An execution stopped at the limit must be recorded as a failed attempt.

Example
Job Q-31's retry starts at 08:15:00 and is still running at 08:15:30; Orion stops it and records a failure.
```

```text
## Execution — delay before a retry

Once an execution has failed, Orion pauses before delivering the job again so that a transient fault downstream has a chance to clear.

Normative rule
1. Before every retry attempt the worker must wait exactly five seconds, measured from the end of the failed attempt.
2. The wait must not be shortened or lengthened based on the attempt number.

Example
Q-31's initial execution fails at 08:14:10; the first retry starts no earlier than 08:14:15. Each later retry likewise starts no earlier than five seconds after the preceding failure.
```

```text
## Ownership — lease on a delivered job

Delivering a job to a worker grants that worker a lease. The lease tells Orion the job is in hand and keeps other workers away from it.

Normative rule
1. A worker lease must last sixty seconds from the moment the job is delivered to the worker.
2. When the lease expires without renewal or release, the job must become available to other workers.

Example
Worker W-2 receives Q-40 at 09:30:00 and goes silent. At 09:31:00 the lease lapses and Q-40 can be handed to W-5.
```

```text
## Ownership — keeping the lease alive

A worker that is still making progress renews its lease so that the job is not reassigned underneath it.

Normative rule
1. A worker may renew its lease every thirty seconds while work on the job is progressing.
2. A renewal must extend the lease by the full lease duration from the moment of renewal.

Example
W-2 renews Q-40's sixty-second lease at 09:30:30; the lease now ends at 09:31:30.
```

```text
## Ownership — cancelling a job

Producers and operators can cancel jobs. Cancellation tells Orion to stop investing in the job; it does not reach into a worker and abort work already under way.

Normative rule
1. After a job is cancelled, no future execution attempt of that job may be started.
2. Cancellation must not interrupt an execution attempt that is already running; that attempt runs to its own completion, failure or timeout.

Example
Q-40 is cancelled while its second execution is running. That execution finishes on its own terms and no further execution follows.
```

```text
## Input handling — repeated deliveries

A producer that times out may send the same job again. Orion recognises the repeat by job id and does not run the job twice.

Normative rule
1. While a job with a given job id is active, any further delivery carrying the same job id must be ignored.
2. Ignoring a duplicate delivery must not change the state of the active job.

Example
Q-52 is delivered at 11:00 and again at 11:02 while still active; the second delivery is dropped and Q-52 is unaffected.
```

```text
## Input handling — idempotency-key memory

Deliveries may carry a producer-chosen idempotency key. Orion keeps recent keys so repeats can be recognised.

Normative rule
1. Orion must retain each idempotency key for twenty-four hours after it is first seen.
2. After the retention period the key may be forgotten and a later delivery with the same key is treated as new.

Example
Key IK-77 first appears on Thursday at 13:00; it is recognised at Thursday 23:00 and forgotten by Friday 14:00.
```

```text
## Delivery guarantees — ordering

Some producers rely on enqueue order. Orion promises order only where doing so does not serialise the whole service.

Normative rule
1. First-in-first-out execution order must be guaranteed only among jobs in the same queue partition.
2. No ordering guarantee is made between jobs in different partitions.

Example
Q-60 then Q-61 are enqueued into partition P-1; Q-60 starts first. Q-62 in P-2 has no ordering relation to either.
```

```text
## Failure handling — after the last attempt

A job that has spent its attempt budget without succeeding is parked for inspection rather than left blocking the queue.

Normative rule
1. After the final unsuccessful execution attempt, Orion must automatically move the job to the dead-letter queue.
2. A job in the dead-letter queue must not be executed again unless explicitly resubmitted.

Example
Q-31 exhausts its attempts at 08:20; Orion places it in the dead-letter queue at 08:20 with no operator action.
```

```text
## Failure handling — alerting an operator

Many dead-letter events for one tenant in a short time usually mean something systemic. Orion raises an escalation when that pattern appears.

Normative rule
1. When three dead-letter events occur for the same tenant within one hour, Orion must raise an operator escalation.
2. The one-hour window must be measured from the first of the three events.

Example
Tenant T-7 produces dead-letter events at 08:20, 08:45 and 09:10; the third falls within an hour of the first, so an escalation is raised.
```

```text
## Audit — how long records are kept

Each job state change produces an audit event used for investigations and tenant reports. Audit events are kept for a bounded period.

Normative rule
1. Audit events must be retained for thirty days after they are recorded.
2. After thirty days an audit event may be deleted.

Example
An audit event written on 2 June may be removed on or after 2 July.
```

Expected: no material semantic churn in any locus — every live claim is restated or left untouched; no supersession, no new address, no conflict, no duplicate current meaning. (Arm F receives twelve structural transitions with twelve real diffs at this version; that is the point.)

### T5 — locus B correction

Section B ("Execution — delay before a retry") is replaced by:

```text
## Execution — delay before a retry

Once an execution has failed, Orion pauses before delivering the job again so that a transient fault downstream has a chance to clear. The pause grows with each failure so that a dependency under sustained pressure is not retried at a fixed cadence.

Normative rule
1. Before the first retry of a job the worker must wait two seconds, measured from the end of the failed execution.
2. Before each later retry the worker must wait twice as long as it waited before the previous retry.
3. The wait before any retry must never exceed thirty seconds.

Example
Q-31 fails at 08:14:10. Its first retry starts no earlier than 08:14:12; if that fails at 08:14:20 the second retry starts no earlier than 08:14:24; a subsequent wait would be eight seconds, then sixteen, then thirty (the cap).
```

Meaning: exponential retry delay starting at 2 seconds, doubling, capped at 30 seconds; the fixed-5-second meaning is no longer current. Expected: same B address; new backoff meaning asserted; governed supersession of the fixed-5 meaning.

### T6 — locus A restatement

Section A ("Execution — attempt budget") is replaced by:

```text
## Execution — attempt budget

Orion delivers each job to a worker for execution. One delivery that ends in success, failure or timeout is an execution. Because some jobs can never succeed, the number of executions per job is capped.

Normative rule
1. One original execution of a job may be followed by no more than three retry executions.
2. Once three retry executions have ended without success, the job must not be executed again.

Example
Q-31 is executed once and then retried three times without success. Q-31 is not executed again.
```

Meaning: unchanged (one initial plus up to three retries; 4 total). Expected: same A address; `SUPPORTS_CLAIM` on the current 4-total meaning; no supersession.

### T7 — locus F correction

Section F ("Ownership — lease on a delivered job") is replaced by:

```text
## Ownership — lease on a delivered job

Delivering a job to a worker grants that worker a lease. The lease tells Orion the job is in hand and keeps other workers away from it. Field experience shows that sixty seconds was too short for workers that perform a cold start before their first renewal.

Normative rule
1. A worker lease must last ninety seconds from the moment the job is delivered to the worker.
2. When the lease expires without renewal or release, the job must become available to other workers.

Example
Worker W-2 receives Q-40 at 09:30:00 and goes silent. At 09:31:30 the lease lapses and Q-40 can be handed to W-5.
```

Meaning: worker lease duration 90 seconds; the 60-second meaning is no longer current. Expected: same F address; new 90-second claim; governed supersession of the 60-second claim.

### T8 — locus B historical revert

Section B ("Execution — delay before a retry") is replaced by:

```text
## Execution — delay before a retry

Once an execution has failed, Orion pauses before delivering the job again so that a transient fault downstream has a chance to clear. Operational review found that a growing pause made recovery times unpredictable for tenants; the delay is therefore a single fixed pause again.

Normative rule
1. Before every retry attempt the worker must wait exactly five seconds, measured from the end of the failed attempt.
2. The wait must not be shortened or lengthened based on the attempt number.

Example
Q-31 fails at 08:14:10; its first retry starts no earlier than 08:14:15, and every later retry likewise starts no earlier than five seconds after the preceding failure.
```

Meaning: fixed 5-second wait before every retry — the same meaning that was current at T1–T4 — and the exponential meaning current since T5 is no longer current. This is intentionally difficult: the new meaning matches an older historical meaning but supersedes the **current** meaning. Expected: same B address; assert a current fixed-5 claim; supersede the current exponential meaning; do not resurrect the old durable claim object as if history rewound (the T1 claim remains historical and superseded; a new claim carries the restored meaning); append-only lineage preserved.

### T9 — locus H compatible extension

Section H ("Ownership — cancelling a job") is replaced by:

```text
## Ownership — cancelling a job

Producers and operators can cancel jobs. Cancellation tells Orion to stop investing in the job; it does not reach into a worker and abort work already under way. A job that has not yet started must not start at all once cancelled.

Normative rule
1. After a job is cancelled, no future execution attempt of that job may be started.
2. Cancellation must not interrupt an execution attempt that is already running; that attempt runs to its own completion, failure or timeout.
3. If a cancellation is received before the first execution attempt of a job has started, that job must never begin execution.

Example
Q-40 is cancelled while its second execution is running; that execution finishes on its own terms and no further execution follows. Q-41 is cancelled before any worker has received it; Q-41 is never executed.
```

Meaning: the existing cancellation rule remains current and a compatible rule is added. Expected: same H address; add the compatible meaning (an additional `ASSERT_CLAIM` at H, or a support of the existing claim plus an additional claim); do not retire the existing compatible cancellation meaning.

### T10 — locus D qualifier correction

Section D ("Input handling — repeated deliveries") is replaced by:

```text
## Input handling — repeated deliveries

A producer that times out may send the same job again, but two deliveries that share a job id are not necessarily the same request: a producer may reuse a job id for different payloads. Orion therefore uses the idempotency key to decide whether a repeat is genuinely the same request.

Normative rule
1. While a job with a given job id is active, a further delivery must be ignored only when it carries both the same job id and the same idempotency key as the active job.
2. A further delivery that carries the same job id but a different idempotency key must be rejected as conflicting input and must not change the state of the active job.

Example
Q-52 (key IK-1) is delivered at 11:00 and is active. A delivery of Q-52 with key IK-1 at 11:02 is ignored. A delivery of Q-52 with key IK-2 at 11:03 is rejected as conflicting.
```

Meaning: a duplicate is ignored only when both job id and idempotency key match; otherwise it is rejected as conflicting input. The unqualified "ignore by job id alone" rule is materially incomplete and must not remain current. Expected: same D address; corrected current duplicate rule; governed supersession of the unqualified old rule.

### T11 — locus L restatement

Section L ("Audit — how long records are kept") is replaced by:

```text
## Audit — how long records are kept

Each job state change produces an audit event used for investigations and tenant reports. Audit history is kept for a bounded period so that investigations have a predictable window.

Normative rule
1. Audit history must remain queryable for one month, defined here as thirty calendar days from the moment each event is recorded.
2. Once an event is older than that window it may be deleted.

Example
An audit event written on 2 June must remain queryable through 2 July and may be removed afterwards.
```

Meaning: unchanged (30-day audit retention). Expected: same L address; `SUPPORTS_CLAIM`; no duplicate.

### T12 — locus G correction

Section G ("Ownership — keeping the lease alive") is replaced by:

```text
## Ownership — keeping the lease alive

A worker that is still making progress renews its lease so that the job is not reassigned underneath it. Renewal is driven by remaining lease life rather than a fixed cadence, and is rate-limited so that many workers cannot flood the lease service.

Normative rule
1. A worker must renew its lease when twenty seconds of lease life remain, provided work on the job is progressing.
2. A worker must never renew the same lease more often than once every fifteen seconds.
3. A renewal must extend the lease by the full lease duration from the moment of renewal.

Example
W-2 holds a ninety-second lease on Q-40 from 09:30:00. It renews at 09:31:10 (twenty seconds remaining); the lease now ends at 09:32:40, and W-2 may not renew again before 09:31:25.
```

Meaning: renew when 20 seconds of lease life remain, never more often than once every 15 seconds; the fixed every-30-seconds renewal meaning is no longer current. Expected: same G address; corrected renewal meaning; governed supersession of the old fixed-interval meaning.

### T13 — locus K semantic relocation

Section K is moved from the "Delivery guarantees" group to a new "Consistency" group and its prose is rewritten; the normative rule is unchanged. Document order at T13 becomes A, C, B, F, G, H, D, E, I, J, K, L. Section K is replaced by:

```text
## Consistency — what order jobs run in

Orion offers a narrow consistency promise about execution order. Producers that need strict sequencing place related jobs in one partition; producers that do not need it gain throughput by spreading work across partitions. The promise is deliberately limited so that a slow job in one partition never stalls the others.

Normative rule
1. First-in-first-out execution order must be guaranteed only among jobs in the same queue partition.
2. No ordering guarantee is made between jobs in different partitions.

Example
Q-70 then Q-71 are enqueued into partition P-9; Q-70 starts first. Q-72 in P-10 may start before, between or after them.
```

Meaning: unchanged (FIFO only within one queue partition). Expected: same K address; support of the existing meaning; no duplicate address caused by the relocation.

### T14 — locus J correction

Section J ("Failure handling — alerting an operator") is replaced by:

```text
## Failure handling — alerting an operator

Many dead-letter events for one tenant in a short time usually mean something systemic. The threshold is tuned so that a brief burst does not page an operator while a sustained fault does.

Normative rule
1. When five dead-letter events occur for the same tenant within any rolling thirty-minute window, Orion must raise an operator escalation.
2. The window is rolling: at each new dead-letter event Orion must count the events for that tenant in the preceding thirty minutes, including the new event.

Example
Tenant T-7 produces dead-letter events at 08:20, 08:25, 08:31, 08:40 and 08:49. At 08:49 five events fall within the preceding thirty minutes, so an escalation is raised.
```

Meaning: escalation after 5 dead-letter events for the same tenant within a rolling 30-minute window; the 3-in-1-hour rule is no longer current. Expected: same J address; corrected threshold and window; governed supersession of the old rule.

### T15 — locus F restatement

Section F ("Ownership — lease on a delivered job") is replaced by:

```text
## Ownership — lease on a delivered job

Delivering a job to a worker grants that worker a lease. The lease tells Orion the job is in hand and keeps other workers away from it.

Normative rule
1. A worker owns a delivered job for one and a half minutes unless the lease is renewed or released earlier.
2. When that ownership period ends without renewal or release, the job must become available to other workers.

Example
Worker W-2 receives Q-40 at 09:30:00, never renews and never releases. At 09:31:30 ownership ends and Q-40 can be handed to W-5.
```

Meaning: unchanged (90-second lease). Expected: same F address; support of the 90-second claim; no supersession.

### T16 — locus I correction

Section I ("Failure handling — after the last attempt") is replaced by:

```text
## Failure handling — after the last attempt

A job that has spent its attempt budget without succeeding needs a human decision. Automatic dead-lettering hid genuine faults from tenants; Orion now keeps the job visible in a failed state until an operator has looked at it.

Normative rule
1. After the final unsuccessful execution attempt, Orion must leave the job in the failed state.
2. A job in the failed state must require operator review before any further action is taken on it.
3. Orion must not automatically move a job to the dead-letter queue.

Example
Q-31 exhausts its attempts at 08:20. Q-31 remains in the failed state and appears in the operator review list; nothing moves it to the dead-letter queue automatically.
```

Meaning: the job is left failed and requires operator review; automatic dead-lettering is no longer current. Expected: same I address; corrected current meaning; governed supersession of the automatic dead-letter behaviour.

### 5.1 Document order by version

| Versions | Order |
|---|---|
| T1–T3 | A B C D E F G H I J K L |
| T4–T12 | A C B F G H D E K I J L |
| T13–T16 | A C B F G H D E I J K L |

---

## 6. Transition classes

| Class | Versions | What it tests |
|---|---|---|
| RESTATEMENT | T2, T6, T11, T13, T15 | wording changes without meaning change; the arm must support, not supersede or duplicate |
| CORRECTION | T3, T5, T7, T10, T12, T14, T16 | meaning changes; the arm must assert the new meaning at the same locus and retire the incompatible old meaning only through governance |
| REVERT | T8 | the new meaning equals an older historical meaning and supersedes the current one; history must not "rewind" |
| COMPATIBLE EXTENSION | T9 | a new compatible rule is added; the existing meaning must survive |
| SEMANTIC NO-OP | T4 | every section changes bytes and no meaning changes; nothing material may happen |

T8 and T10 are the discriminating transitions. T8 asks whether an arm can tell "this matches something old" from "this replaces what is current". T10 asks whether an arm recognises that an unqualified rule has become materially incomplete rather than merely reworded. These are exactly the historical/current distinctions that contrastive context was designed to support; if Arm A handles them as well as Arm F, contrast has not earned its cost on this history.

---

## 7. Evidence corpus

The implementation freezes the full corpus **before** any live call.

- 16 versions × 12 loci = **192 `EvidenceItem`s**, all `SourceKind.DOCUMENT`.
- Exactly one evidence item per locus per version, even when the section is byte-identical to the previous version; R must see a realistic cumulative history and the persistent arms must see realistic version churn.
- `artifact_ref` is stable per locus across all versions (table in §3).
- Every T > 1 item carries `supersedes_evidence_id` naming the same locus's item at T−1 (a single linear chain of length 16 per locus; 180 lineage edges in total).
- Ids: `EV-O-<locus><TT>` (e.g. `EV-O-A01`, `EV-O-B08`, `EV-O-L16`). Source refs: `experiment://orion/T<TT>/<locus>`.
- `observed_at`: `2026-10-<TT>T00:<pp>:00Z` where `pp` is the zero-based document position of that locus in that version's order (§5.1). Ordering within a version is therefore document order; ordering across versions is by day.
- Scope: `("orion-jobs",)` for every item. Lifecycle project id for the manifest: `PROJ-9P3-ORION`; arm governors use arm-distinct project ids exactly as 9P2 did.
- Persistent delta at T is the twelve items of version T in document order. R's reconstruction batch at T is all items of versions 1..T in version order then document order.
- Machine-visible evidence carries no grading semantics: no evidence text, id, ref, heading or metadata may contain `correction`, `restatement`, `revert`, `no-op`, `compatible extension`, `expected`, `lifecycle`, checkpoint ids, class names, error counts, decision names, or any statement of which `SemanticAddress` is correct. Change narration inside prose is limited to in-world engineering rationale (as written in §5) and never names an experiment concept.
- Exact bytes, content SHA256 values, timestamps and order are sealed in the manifest before the live run (§16).
- **Corpus size discipline (checked at freeze):** no section may exceed 1,400 characters. Rationale: R's cumulative batch at T16 compiles up to 180 lineage transitions through the frozen comparison-context compiler (§8), and the total-context bound of 131,072 characters is a frozen production limit that must not be approached by design. Identical carried-forward content yields an empty diff, so only changed sections contribute diff text; the size cap and the offline compilation gate I13 (§12) together guarantee the bound is never reached.

The hidden answer key (§4.13, §5 "Meaning"/"Expected" lines, §6, §10) lives outside the provider request path (§15).

---

## 8. Arms

All arms: provider `xai`, model `grok-4.6`, reasoning effort `high`, no tools, no search, no retry, no judge. Exactly two frontier calls per arm per version.

### Arm F — persistent contrastive semantic memory

- One append-only semantic ledger from T1 through T16.
- The frozen production assimilation path (`assimilate_delta`): Call 1 sees all active in-scope addresses with their active claim profiles and the compiled comparison context; Call 2 sees the decision neighbourhood widened by structurally touched addresses, with the call-specific comparison context.
- `XAIContrastiveSemanticReasoner`, policy `intent-v2-9p2-v1`, prompt SHA256 `a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410`, output schema SHA256 `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`.
- Citable evidence after T1: the current delta only.

### Arm A — persistent non-contrastive semantic memory

- One append-only semantic ledger from T1 through T16, separate from F's.
- The existing experiment-only ablation path (9P2's `assimilate_ablation_delta`): Call 1 sees active in-scope address descriptors, `known_claims = ()`, no comparison context; Call 2 sees only the applied Call-1 decision neighbourhood with its live claims, no comparison context, no contrastive widening.
- Historical `XAISemanticReasoner`, policy `intent-v2-9p-v4`, prompt SHA256 `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`, same output schema.
- Citable evidence after T1: the current delta only.

### Arm R — fresh reconstruction

- At every T: a new store and governor, no semantic state from R(T−1).
- Reconstruction batch = cumulative raw evidence T1..T (§7), ingested in order, then exactly two calls through the frozen production path with `XAIContrastiveSemanticReasoner` (the 9P2 R contract: R may receive the deterministic lineage diffs derivable from the cumulative batch, making it a deliberately strong baseline).
- Citable evidence: the whole cumulative batch of that T.
- R never holds an authority record and never receives human authorization.

No production semantics are altered to create any arm.

---

## 9. Arm order

The six-step rotation below is repeated deterministically; nothing is randomized at runtime.

| T | order | T | order | T | order | T | order |
|---|---|---|---|---|---|---|---|
| T1 | F A R | T5 | A F R | T9 | R F A | T13 | F A R |
| T2 | A R F | T6 | R A F | T10 | F R A | T14 | A R F |
| T3 | R F A | T7 | F A R | T11 | A F R | T15 | R F A |
| T4 | F R A | T8 | A R F | T12 | R A F | T16 | F R A |

Each persistent arm still advances T1 → T16 in order. Authority processing for a persistent arm happens immediately after that arm's Call 2 and before the next scheduled arm. No arm receives another arm's state, requests, outputs, receipts or verdicts.

Call ceiling: 16 T × 3 arms × 2 calls = **96 frontier calls**, exactly, for a completed run. No extra semantic calls exist.

---

## 10. Semantic grading

### 10.1 Root designation (persistent arms)

After each persistent arm's T1, the twelve roots are designated mechanically exactly as in 9P2 §7: for each seed evidence id `EV-O-<locus>01`, collect live claims whose effective evidence contains the seed; designation succeeds iff there is at least one such claim and all of them map to exactly one address. The designated address of each locus is fixed for the rest of the run. An `UNDESIGNATED` locus fails I1 and causes every later checkpoint that depends on it to fail; the run continues.

### 10.2 Checkpoints

Hidden checkpoints **C02 … C16**, one per transition T2–T16, are binary PASS/FAIL per arm. Any failure of a checkpoint's required lifecycle behaviour contributes exactly **one** material error for that arm (a checkpoint never contributes more than one). T1 is setup/integrity and is not a material checkpoint.

For persistent arms F and A, the requirements by class:

**Restatement (C02, C06, C11, C13, C15)** — PASS iff:
- the delta is bound to the designated address of the target locus (no `CREATE_ADDRESS` for that locus);
- the current meaning of the target locus is unchanged;
- a `SUPPORTS_CLAIM` (or no change) is the only semantic action on the current claim where support is appropriate;
- no duplicate current meaning is created at the locus;
- no pending or applied `SUPERSEDE` targets a live claim at the locus.

**Correction (C03, C05, C07, C10, C12, C14, C16)** — PASS iff:
- the delta is bound to the designated address (no duplicate same-locus address);
- the corrected meaning is asserted and current at that address;
- the incompatible old meaning remains historically readable;
- the incompatible old meaning does not leave the current view before authority;
- a model `SUPERSEDE` proposal targets the creating judgment of every materially incompatible claim that was live at the designated address immediately before T (an eligible pre-T target, §18.1) and is applied only through the mechanical authority protocol (§18);
- after authority, no incompatible old meaning is current at the locus;
- any still-compatible subclaim at the locus is not required to be superseded.

**Revert (C08)** — PASS iff:
- the delta is bound to the designated B address;
- the immediately preceding current meaning (exponential; the T5-created claim live at the designated B address immediately before T8, i.e. the eligible pre-T target of §18.1) is targeted for governed supersession and, after authority, is not current;
- the restored meaning (fixed 5 seconds) is current, carried by a claim asserted at T8 (a new claim object);
- the historical T1 claim object is not treated as re-activated or as a literal state rollback (it remains superseded);
- history is append-only and the lineage T1 → T5 → T8 is readable.

**Compatible extension (C09)** — PASS iff:
- the delta is bound to the designated H address;
- the existing compatible meaning remains current;
- the new compatible meaning is added (an additional current claim at H, or an additional claim alongside a support of the existing one);
- no `SUPERSEDE` (pending or applied) targets the existing H claim.

**Semantic no-op (C04)** — PASS iff there is no material semantic churn in any locus: no new address for any locus, no pending or applied `SUPERSEDE`, no `CONFLICTS_WITH`, no duplicate current meaning, no change to any current meaning; supports and no-ops are the only permitted actions.

### 10.3 Stable controls

At every T2–T16, every locus other than the transition's target locus is a control. A **control error** is counted for that arm at that T for any unjustified:
- supersession (pending or applied) of a control claim;
- `CONFLICTS_WITH` involving a control claim;
- duplicate current address for a control locus;
- duplicate current meaning at a control locus;
- material mutation of a control's current meaning;
- semantic disappearance of a control's current meaning.

At most one control error is counted per arm per T. Control errors count toward the arm's total semantic error count.

### 10.4 R grading

R has no persistent address identity and no authority. At each T, R is judged only on the fresh current reconstruction:
- the current reconstruction must cleanly represent the meaning that is current at that T for every locus (§4.13 and §5);
- obsolete historical interpretations must not remain concurrently current at the same locus — for example after T3 the 3-total and 4-total meanings cannot both be current; after T5 fixed-5 and exponential cannot both be current; after T8 exponential must not be current when fixed-5 has been restored; after T10 the unqualified duplicate rule must not be current; after T16 automatic dead-lettering must not be current;
- duplicate same-locus current addresses are errors.

R's checkpoint C0k is PASS iff both the target locus and every control locus meet these conditions at T = k; one material error per failed checkpoint; control errors are counted for R under the same definitions as §10.3 restricted to what a fresh reconstruction can exhibit.

### 10.5 Semantic acceptability

An arm is **semantically acceptable** iff `material_errors == 0` AND `control_errors == 0` AND every applicable deterministic integrity gate (§12) passes. Cost never compensates for semantic incorrectness.

### 10.6 Representation freedom and adjudication

Predicate names, descriptor wording and structured value representation are not answer-key requirements; grading concerns material meaning and lifecycle continuity. Semantic verdicts (meaning equivalence, whether two addresses denote one locus, which old subclaims are incompatible, control stability, per-checkpoint PASS/FAIL, error totals) are architect adjudication after the raw freeze, exactly as in 9P2 §18. No model judge is used. The harness computes only structural facts.

---

## 11. Expected authority profile (informational)

Corrections (7) and the revert (1) are the only transitions at which a persistent arm is expected to need authority: 8 per persistent arm, 16 in total. The authorization ceiling (§17) is a safety maximum, not a target.

---

## 12. Integrity gates

Deterministic verdicts computed from raw artifacts after the run (and, where marked ⊙, also evaluated offline in preflight before any call).

| Gate | Requirement | Applies to |
|---|---|---|
| I1 | exactly twelve pairwise-distinct designated T1 root addresses | F, A |
| I2 | exactly two model calls for every completed persistent T (call numbers 1, 2; no duplicate request identity) | F, A (and R per T) |
| I3 | no semantic retry, fallback, judge or third phase anywhere in the run | all |
| I4 | every evidence id cited by every model-originated proposal was present in that exact request's `ReasoningRequest.evidence` | all |
| I5 | a predecessor shown only in comparison context is never cited | F, R |
| I6 | scope closure: every known address is eligible for `("orion-jobs",)`; known claims and touched addresses stay within each request's known addresses | F, R (A: known claims within known addresses) |
| I7 | no model-originated `SUPERSEDE` is itself the applied state-changing judgment | F, A |
| I8 | every applied material supersession is a human AGREE (route `APPLY`, reason `HUMAN_AUTHORITY`) whose proposal signature equals an earlier pending model proposal | F, A |
| I9 | replay of the final ledger reproduces the final state and derived view exactly | F, A (and each R ledger) |
| I10 | same-response reference law: every `SUPERSEDE`/`SUPPORTS_CLAIM`/`CONFLICTS_WITH` target exists in that request or earlier in that response, per the frozen adapter law | all |
| I11 | durable history is append-only and every superseded claim/judgment remains readable in the final ledger | F, A |
| I12 | no hidden reconciliation operation exists: request records, receipts and ledger events reconcile one-to-one with the 96-call schedule | all |
| I13 ⊙ | offline compilation of every R Call-1 request and every persistent T1 request from the frozen corpus succeeds within the frozen bounds, and R's T16 canonical comparison context is ≤ 100,000 characters (≈ 76 % of the 131,072 bound, leaving headroom for Call-2 profile edges) | R (offline) |
| I14 ⊙ | 9P2's leakage gate (five-key skeletons, needle set of §15) passes over the 9P3 needle set | all |
| I15 | mechanical authority chain (§18.3): every applied material supersession is a human AGREE whose target judgment id was in that transition's structurally snapshotted pre-T eligible set `ELIGIBLE_T` (§18.1), whose proposal signature equals an earlier pending model-originated proposal, routed `APPLY` with reason `HUMAN_AUTHORITY`; every AGREE was issued only at a correction/revert checkpoint; every pending proposal outside `ELIGIBLE_T` was recorded as not authorized and never applied; no authority record or AGREE carries any semantic assessment | F, A |

Where a comparison-context property (I5, I6 touched-address clause, I13) does not apply to Arm A, the corresponding A gate is the non-contrastive reduction (I4, I6 known-claims clause). Preflight additionally carries forward every 9P2 gate that remains meaningful (seal identity, worktree cleanliness, frozen core ancestry and unchanged core paths, policy/prompt/schema hashes, `CALLS_PER_DELTA == 2`, ablation two-call/no-retry, fresh R ledger per T, evidence manifest, schedule, ceilings, answer-key import gate, regression suites, historical artifact preservation for every prior experiment directory, `GRPC_DNS_RESOLVER=native`).

---

## 13. Measurements

For every provider call record (derived from the existing request records and receipts; the provider prompt is never changed to instrument measurement):

- `input_tokens`, `output_tokens`, `provider_cost_usd`, `wall_clock_ms` (provider-reported receipt);
- rendered request character count (`len(rendered_user_request)`);
- number of known addresses; number of known claims;
- F/R comparison-context character count (`comparison_context_chars`; 0 for A);
- R cumulative raw-evidence character count (sum of `len(content)` over the batch; recorded per R T).

Per arm per T, sums over the two calls are recorded; per arm, totals over T2–T16 and over the early/late windows (§14.2).

---

## 14. Economy and bounded growth

### 14.1 Total economy (T2–T16)

```text
F_TOTAL = Σ input_tokens of all Arm F calls at T2..T16
A_TOTAL = Σ input_tokens of all Arm A calls at T2..T16
R_TOTAL = Σ input_tokens of all Arm R calls at T2..T16
```

A persistent arm satisfies the economy criterion iff the exact integer inequality holds:

```text
ECONOMY_F : 4 · F_TOTAL <= 3 · R_TOTAL
ECONOMY_A : 4 · A_TOTAL <= 3 · R_TOTAL
```

i.e. at least 25 % fewer input tokens than R. F and A are reported and judged independently; `min(F, A)` is never used.

### 14.2 Bounded-growth test

```text
EARLY window = T2..T5     LATE window = T13..T16
X_EARLY_MEAN = mean over T in EARLY of (Σ input_tokens of arm X's two calls at T)
X_LATE_MEAN  = mean over T in LATE  of (Σ input_tokens of arm X's two calls at T)
```

Persistent bounded-growth criterion (each of F and A independently):

```text
BOUNDED_X : X_LATE_MEAN <= 1.35 · X_EARLY_MEAN
```

R expected-history-growth criterion:

```text
R_GROWS : R_LATE_MEAN >= 1.50 · R_EARLY_MEAN
```

Means are computed in exact rational arithmetic on integer token counts; comparisons are exact.

**This is an empirical finite-history scaling test. It is NOT a mathematical O(1) proof.** It can show that on a sixteen-version history persistent context stayed within 35 % of its early size while reconstruction grew by at least 50 %; it cannot show what happens at version 200.

---

## 15. Leakage protection

The provider request path must not be able to access:
- the C02–C16 answer keys (§4.13 meanings, §5 "Meaning"/"Expected" lines, §10 requirements);
- expected transition classes (§6);
- expected error counts or the expected authority profile;
- the architecture-selection result names (§16) and their conditions;
- economy/growth grading values where they would reveal expected answers.

Mechanism (carried over from 9P2 §14 and its Ruling B): a sealed needle set of grading labels (word-bounded), full answer-key sentences, transition-class names, checkpoint ids and decision names, with the exact C1 normalization; real request skeletons rendered through the real assembly and rendering paths with opaque placeholder evidence and descriptors (T1 no-predecessor, correction-shaped, restatement-shaped, F Call 1/2, A Call 1/2, R cumulative Call 1/2); fail-closed before reasoner construction. The grading/answer-key module must not be imported by any request-path module (AST import gate over the six request-path files plus any new 9P3 request-path module).

---

## 16. Architecture-selection rule

The experiment has **no favored arm**. All thresholds are fixed here and never changed after results are seen.

**Core law: SEMANTIC CORRECTNESS DOMINATES COST.** A semantically incorrect arm never beats a semantically correct arm on cost, and a semantically correct arm is never required to be cheaper than an incorrect competitor before it can be selected.

### 16.1 Inputs

For each arm X ∈ {F, A, R}: `errors_X = material_errors_X + control_errors_X` (architect-adjudicated); for the persistent arms, `acceptable_X = (errors_X == 0) AND every applicable integrity gate of §12 passes`; `ECONOMY_X` and `BOUNDED_X` (§14); `R_GROWS` (§14.2); `F_TOTAL`, `A_TOTAL`, `R_TOTAL`; and the operational status. `errors_R` is recorded and reported but is not a selection input.

The frozen F/A token-difference formulation is symmetric with the cheaper arm as denominator, in exact rational arithmetic on integer token counts:

```text
TOKEN_DIFF_FA = |F_TOTAL − A_TOTAL| / min(F_TOTAL, A_TOTAL)
MEANINGFUL_COST_DIFFERENCE = (TOKEN_DIFF_FA >= 5/100)
```

Both totals are strictly positive for a completed run (every arm makes 30 calls over T2–T16), so the denominator is never zero.

### 16.2 Precedence

Evaluated strictly top to bottom; the first matching rule is the decision. The decision artifact records every input, the truth value of every predicate, the matched rule, and — for the residual — the unmatched predicate vector.

**0. Operational / scientific invalidity — above architecture judgment.** If the experiment cannot be scientifically adjudicated because of a provider/runtime abort, a violated preregistration, missing or corrupted artifacts, invalid call counts, answer-key leakage, or any other experiment-invalidating integrity failure (a failed gate of §12 that is not attributable to one arm's semantic behaviour), then:

```text
EXPERIMENT_INCONCLUSIVE
```

**1. Neither persistent arm is semantically acceptable.**

```text
NOT acceptable_F AND NOT acceptable_A  ->  REDESIGN_PERSISTENT_CONTEXT
```

**2. Exactly one persistent arm is semantically acceptable.** Let X be that arm (the other arm is out of contention regardless of its cost).

```text
2A. BOUNDED_X AND ECONOMY_X          ->  SELECT_X
2B. NOT BOUNDED_X                    ->  REDESIGN_PERSISTENT_CONTEXT
2C. BOUNDED_X AND NOT ECONOMY_X:
        NOT R_GROWS                  ->  SCALE_NOT_YET_PROVEN
        R_GROWS                      ->  EXPERIMENT_INCONCLUSIVE
```

Reason: a semantically wrong competitor never wins because it happens to use fewer tokens.

**3. Both F and A are semantically acceptable.** Boundedness is evaluated first.

```text
3A. NOT BOUNDED_F AND NOT BOUNDED_A  ->  REDESIGN_PERSISTENT_CONTEXT

3B. exactly one bounded; let X be the bounded arm:
        ECONOMY_X                    ->  SELECT_X
        NOT ECONOMY_X AND NOT R_GROWS ->  SCALE_NOT_YET_PROVEN
        NOT ECONOMY_X AND R_GROWS    ->  EXPERIMENT_INCONCLUSIVE

3C. both bounded; evaluate economy versus R:
    a. NOT ECONOMY_F AND NOT ECONOMY_A:
        NOT R_GROWS                  ->  SCALE_NOT_YET_PROVEN
        R_GROWS                      ->  EXPERIMENT_INCONCLUSIVE
    b. exactly one economical; let X be the economical arm:
                                     ->  SELECT_X
    c. ECONOMY_F AND ECONOMY_A:
        TOKEN_DIFF_FA < 5/100        ->  INCONCLUSIVE_TIE
        F_TOTAL < A_TOTAL            ->  SELECT_F
        A_TOTAL < F_TOTAL            ->  SELECT_A
```

(In 3C.c, `F_TOTAL == A_TOTAL` gives `TOKEN_DIFF_FA == 0`, which is the tie.)

**4. Residual.** Any state not matched above:

```text
EXPERIMENT_INCONCLUSIVE, recording the unmatched predicate vector
(acceptable_F, acceptable_A, BOUNDED_F, BOUNDED_A, ECONOMY_F, ECONOMY_A, R_GROWS, TOKEN_DIFF_FA)
```

### 16.3 Exhaustiveness and contradiction review

- Rules 1, 2 and 3 partition the space by the number of acceptable persistent arms (0, 1, 2); within each, every combination of the boolean predicates `BOUNDED_*`, `ECONOMY_*` and `R_GROWS` reaches exactly one outcome, and 3C.c is total over the three-way comparison of `F_TOTAL` and `A_TOTAL`. The residual rule therefore fires only if an input is undefined (which rule 0 already catches); it is retained as the fail-closed floor.
- `SELECT_F` and `SELECT_A` are symmetric: every path that selects an arm selects it because it is the only acceptable arm, the only bounded arm among acceptable arms, the only economical arm among bounded acceptable arms, or the meaningfully cheaper of two otherwise equal arms. Semantic error counts enter only through `acceptable_X` (zero errors); no rule compares `errors_F` with `errors_A` numerically, because an arm with any error is out of contention regardless of how many the other arm has.
- `SCALE_NOT_YET_PROVEN` fires only when at least one acceptable, bounded persistent arm exists, no such arm met the 25 % economy criterion, and R did not exhibit the preregistered ≥ 50 % history growth — i.e. the history was too light to establish the scaling claim fairly. When R did grow and a bounded acceptable arm still failed economy, the result is `EXPERIMENT_INCONCLUSIVE` (the economy claim was tested and not met, but the design does not preregister a "persistence is not cheaper" architecture decision).
- `INCONCLUSIVE_TIE` requires both arms acceptable, bounded and economical with a sub-5 % cost difference; it cannot coincide with any `SELECT_*` path.
- No rule requires a correct arm to be cheaper than an incorrect arm.

### 16.4 Worked examples (binding illustrations of the precedence)

| # | Situation | Path | Result |
|---|---|---|---|
| 1 | F semantically wrong (`errors_F ≥ 1`); A semantically perfect; A slightly more expensive than F | rule 2 with X = A | F cannot win. `SELECT_A` if `BOUNDED_A AND ECONOMY_A`; `REDESIGN_PERSISTENT_CONTEXT` if not bounded; otherwise 2C. A's cost relative to F is irrelevant. |
| 2 | F and A both perfect; both bounded; both economical; `A_TOTAL` is 12 % below `F_TOTAL` | 3C.c, `TOKEN_DIFF_FA ≈ 13.6 % ≥ 5 %`, `A_TOTAL < F_TOTAL` | `SELECT_A` |
| 3 | F and A both perfect; both bounded; both economical; `F_TOTAL` is 2 % below `A_TOTAL` | 3C.c, `TOKEN_DIFF_FA ≈ 2.04 % < 5 %` | `INCONCLUSIVE_TIE` |
| 4 | F perfect; A has one material error; F bounded and economical; A much cheaper | rule 2 with X = F, 2A | `SELECT_F` |
| 5 | F and A both perfect and bounded; neither economical; R does not grow by the preregistered 1.50 factor | 3C.a, `NOT R_GROWS` | `SCALE_NOT_YET_PROVEN` |

(Example 2: with `A_TOTAL = 0.88·F_TOTAL`, `TOKEN_DIFF_FA = 0.12/0.88 ≈ 13.6 %`. Example 3: with `F_TOTAL = 0.98·A_TOTAL`, `TOKEN_DIFF_FA = 0.02/0.98 ≈ 2.04 %`.)

---

## 17. Budgets and provider defaults

```text
max_frontier_calls        = 96
max_judge_calls           = 0
max_semantic_retries      = 0
max_same_cell_reruns      = 0
max_human_authorizations  = 24
max_provider_cost_usd     = 10.0
```

The authorization ceiling of 24 is a hard safety maximum enforced before any durable write; the expected count is 16 (§11). Cost is provider-reported receipt cost accumulated in exact decimal arithmetic; a call whose receipt breaches the ceiling is recorded and no later call is made.

Provider defaults unless amended before sealing: provider `xai`; model `grok-4.6`; reasoning effort `high`; `GRPC_DNS_RESOLVER=native` supplied by the launcher before Python starts (sealed in the manifest and gated exactly as in 9P2 v2/v3); no tools; no search; no retries.

---

## 18. Human authority

Human intervention during live execution is entirely mechanical and identical in shape to 9P2 §8. Authority checkpoints exist only at the correction and revert transitions (T3, T5, T7, T8, T10, T12, T14, T16), for the persistent arms only, immediately after that arm's Call 2 and before the next scheduled arm. No authority checkpoint exists at restatement, extension or no-op transitions, and pending proposals there are never authorized.

### 18.1 Frozen pre-T eligibility rule

Before a persistent arm ingests transition T's evidence, the harness snapshots — structurally, from the derived current view of that arm's own pre-T state — the **eligible target set** for T:

```text
ELIGIBLE_T = { claim.created_by_judgment_id
               for claim live in derive_view(state_before_T)
               if claim.address_id == DESIGNATED_ADDRESS[target_locus(T)] }
```

`DESIGNATED_ADDRESS` is the root address designated mechanically after T1 (§10.1); `target_locus(T)` is the preregistered locus of transition T (§5, §6). The snapshot is taken from pre-T state only and is never recomputed after the transition runs.

After that arm's Call 2 at T, a pending `SUPERSEDE` proposal is mechanically eligible for the harness authority action only when **all** of the following hold:

1. its `target_judgment_id` created a claim that was **live in the derived current view at the designated target address immediately before ingesting T's evidence** (i.e. the target is in `ELIGIBLE_T`);
2. that address is the preregistered designated address for the transition's semantic locus;
3. the pending model proposal targets that exact judgment id;
4. the authority action is exactly the preregistered `AGREE` operation — one human `SemanticJudgment` carrying the identical proposal object/signature, the frozen authority identity, and no visible evidence;
5. the human/harness performs no semantic correctness assessment of the proposal or of the claim it would retire.

For each id in `ELIGIBLE_T` (sorted): exactly one pending model-originated proposal targeting it receives one `AGREE`; zero proposals authorize nothing; competing proposals for one id authorize nothing.

The harness **fails closed** (authorizes nothing for that target, records the reason, and never repairs or substitutes a target) when:

- the proposed target was not live pre-T (including a target that became live only during T);
- the target's claim belongs to another address;
- the address is not the preregistered locus for T;
- multiple target interpretations make the mechanical mapping ambiguous (competing proposals for one id, or a proposal whose target cannot be resolved to exactly one pre-T live claim);
- no exact eligible target exists.

Every non-eligible pending proposal is recorded as not authorized and remains pending. No human inspects whether the semantic proposal is "right" before `AGREE`; the harness never asks the human whether Grok is right.

### 18.2 What the rule is and is not

This is an **experiment-harness authority-eligibility rule**. It does not alter production authority semantics, admission, reducer behaviour, model permissions, semantic correctness, or which claim the model chooses to supersede. The model still decides and proposes the semantic target; the harness only determines whether the proposed target belongs to the mechanically authorized pre-T live set. The pre-T snapshot generalises 9P2's "T1 root creating judgments": at the revert T8 the claim that must be retired is the current exponential-backoff claim created at T5, which is live at the designated B address immediately before T8 and is therefore in `ELIGIBLE_T8`; the historical T1 claim is not live pre-T8 and is not eligible. For an ordinary correction (e.g. T3), `ELIGIBLE_T` is the set of T1-created claims live at the designated address, exactly as in 9P2. The rule reads ids, addresses and liveness only, never wording.

The frozen authority identity is `provider=human`, `model=human://architect`, `policy_version=intent-v2-9p3-long-horizon-v1`, logical actor `architect`.

### 18.3 Integrity statement

Every applied material supersession in a persistent arm must trace, with no semantic human judgment in the loop, through exactly this chain (gate I15, §12):

```text
model proposal
    -> exact pre-T live target at the preregistered designated address
    -> pending governance (held by admission; not applied by the model)
    -> mechanical human AGREE (identical proposal signature, frozen identity)
    -> durable application (route APPLY, reason HUMAN_AUTHORITY)
```

---

## 19. Freeze discipline

1. Freeze the evidence corpus (192 items; bytes, hashes, timestamps, order).
2. Freeze the hidden answer key (§4.13, §5, §6, §10) and the needle set.
3. Freeze the schedule (§9).
4. Freeze policies, prompts, output schema and model (§8, §17).
5. Freeze budgets (§17).
6. Freeze measurements and thresholds (§13, §14, §16).
7. Seal `manifest.json` + `expectations.json` (no self-referential seal SHA; `harness_code_sha` = the clean pre-seal HEAD; seal commit adds exactly those two files under `docs/superpowers/experiments/<date>-long-horizon-bounded-memory-v1/`).
8. Offline preflight (`--preflight-only`, zero calls, no key access, no reasoner construction).
9. Exactly one live attempt per sealed identity.
10. Freeze raw artifacts immediately in a raw-run commit (no source/test/script/spec/plan/prompt/manifest/expectations change).
11. Semantic grading only after the raw-evidence commit.
12. The adjudication result is committed separately and updates only the allowed verdict/report files.

An operational or provider abort consumes the experiment identity; a consumed identity is never rerun. A subsequent attempt requires a new sealed identity (`…-v2`, `…-v3`, …) with the predecessor's evidence directory preserved by a dedicated preservation gate, as 9P2 v2/v3 did.

---

## 20. No production changes authorized

This design authorizes **no** change to:

- `src/foundry/domain/`, `src/foundry/application/`, `src/foundry/ports/`, `src/foundry/adapters/`;
- semantic reducer behaviour; authority semantics; durable event models;
- the xAI output schema; the existing F (contrastive) prompt; the existing A (historical) prompt;
- comparison-context compiler semantics; incremental-assimilation semantics;
- `src/foundry/experiments/longitudinal/` or any prior experiment directory.

The implementation phase may only add the experiment corpus, harness, grading/integrity code and tests (under `src/foundry/experiments/`, `scripts/`, `tests/`, and the new experiment directory) unless the architect later approves a separate design amendment. If implementing this design turns out to require a production change, that is an architecture finding to be raised — not a permission.

---

## 21. Non-goals

- retrieval above 200 active addresses;
- embeddings; vector search; semantic search;
- agent planning; code-generation quality;
- multi-repository context;
- provider comparison; model comparison;
- production latency optimization;
- fresh-observation coverage (Track C/T3 of 9P2); cross-model inheritance (9Q).

---

## 22. Design self-review record

Performed before committing this document.

1. **No TBD/TODO/placeholders** — verified; every value is fixed.
2. **All 16 versions fully specified** — T1 gives all twelve section texts; T4 gives all twelve replacements; every other T gives the full replacement text of its changed section; unchanged sections are byte-identical carry-forwards; document order per version is tabulated (§5.1).
3. **Transition expectations vs lifecycle laws** — every expectation uses only the existing judgment kinds; corrections/revert retire meaning only through the mechanical authority protocol; the revert asserts a new claim rather than re-activating a superseded one (append-only law); the extension adds meaning without supersession; the no-op permits only supports/no-ops. One issue found and fixed during the original review: 9P2's authority rule (eligible targets = T1 root creating judgments) cannot retire the T5 claim at T8. Amendment 1 (architect-approved) freezes the replacement in §18.1: the eligible target set `ELIGIBLE_T` is snapshotted structurally from the arm's pre-T derived view (claims live at the designated address of the transition's locus immediately before ingesting T), the model still proposes the target, the harness only checks membership, and it fails closed on non-live, wrong-address, wrong-locus, ambiguous or absent targets. Verified against every transition: at T8 `ELIGIBLE_T8` contains exactly the T5-created exponential claim's judgment (live pre-T8) and excludes the T1 claim (superseded at T5); at each ordinary correction (T3, T5, T7, T10, T12, T14, T16) it contains the claims live at that locus pre-T (T1-created claims, or the T3-created A claim at later A transitions), which is what the model must retire; at restatement/extension/no-op transitions there is no checkpoint, so nothing is ever authorized. No semantic human judgment exists anywhere in the chain (§18.3, gate I15).
4. **Decision table exhaustive and non-contradictory** — Amendment 2 (architect-approved) replaced the original rule set with the architecture-neutral precedence of §16.2 under the core law that semantic correctness dominates cost. The five residual combinations flagged in the original review are now all classified: (a) both perfect/bounded/economical with F ≥ 5 % cheaper → `SELECT_F` (3C.c); (b) bounded acceptable arm, economy failed, `R_GROWS` → `EXPERIMENT_INCONCLUSIVE` (2C/3B/3C.a, R branch); (c) one acceptable arm, economical but not bounded → `REDESIGN_PERSISTENT_CONTEXT` (2B); (d) A acceptable, F not, A bounded and economical but not cheaper than F → `SELECT_A` (2A; cost relative to an unacceptable arm is irrelevant); (e) F acceptable and `errors_F > errors_R` → `errors_R` is no longer a selection input, so F is selected on its own merits (2A). §16.3 records the exhaustiveness argument; the residual rule 4 is retained only as a fail-closed floor.
5. **No threshold depends on observed results** — 25 %, 1.35, 1.50, 5 %, the windows and the ceilings are fixed here; 9P2's observed numbers are cited only as motivation.
6. **Evidence design does not leak the answer** — no evidence text uses the forbidden labels; change rationale is in-world; the needle set and import gate are specified (§15); the answer key is outside the request path. One issue found and fixed during review: an early draft of T8's prose used the word "revert"; the frozen text now says the delay "is therefore a single fixed pause again".
7. **R reconstruction contract explicit** — §8 (fresh store/governor per T, cumulative batch, two calls, contrastive reasoner, no carried state, no authority) and §10.4 (grading); the compilation-size hazard at T16 is handled by the section-size cap (§7) and the offline gate I13 (§12) without touching the compiler.
8. **Human authority mechanical** — §18.
9. **No production implementation decision** — §20; the only implementation-facing statements are experiment-harness contracts. The eligible-target generalisation in §18 is an experiment-harness rule over existing state, not a change to authority semantics in production code.
10. **9P2 evidence referenced accurately** — §1.1 cites the frozen artifact values (24 calls, $0.490336, 4 authorizations, F1/F3–F8 true) from `201198f`, the token totals recomputed from the frozen receipts (F 29,800; A 24,558; R 30,772; R per-T 9,639/10,252/10,881), and states that the semantic counts are architect adjudication whose commit is separate from the referenced evidence commit.

---

## 23. What this experiment can establish

- `SELECT_F`: contrastive persistent memory is semantically acceptable, stays bounded and is materially cheaper than reconstruction, and either A was not semantically acceptable (or not bounded/economical) or A was equally correct but meaningfully (≥ 5 %) more expensive.
- `SELECT_A`: non-contrastive persistent memory is semantically acceptable, bounded and cheaper than reconstruction, and either F was not semantically acceptable (or not bounded/economical) or F was equally correct but meaningfully (≥ 5 %) more expensive — contrastive context did not earn its cost on this history; Foundry should simplify.
- `REDESIGN_PERSISTENT_CONTEXT`: persistent memory as built is either incorrect or unbounded on this history; the context design must change before scale is pursued.
- `SCALE_NOT_YET_PROVEN`: persistence worked but the history was too light to demonstrate the economy claim; a heavier history is needed.
- `INCONCLUSIVE_TIE`: both persistent designs are correct, bounded and cheaper than reconstruction with no material cost difference; the choice is not decided by this evidence.
- `EXPERIMENT_INCONCLUSIVE`: no decision; the artifact names why.

Not established here: behaviour beyond sixteen versions, retrieval above the 200-address bound, fresh-observation coverage, cross-model inheritance, or anything about other providers or models.

---

## 24. Live-authorization gate

This design does not authorize a live run. Required sequence: written spec approved → implementation plan approved → harness implemented with strict TDD → local verification and independent review → manifest/expectations/leakage gate sealed → final pre-run seal independently verified → explicit architect live authorization → one live run. Until then, zero live provider/model/judge calls are authorized for this experiment.
