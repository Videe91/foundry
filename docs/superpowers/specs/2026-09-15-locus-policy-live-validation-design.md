# Locus Policy Live Validation — Design Specification

**Experiment:** `intent-v2-locus-validation-v1`
**Status:** design approved in principle by the architect (Option 2 + two mandatory amendments); this document is the binding specification. No harness code, seal or live call exists yet.
**Policy under test:** `intent-v2-locus-v1` — `XAILocusSemanticReasoner`, prompt SHA-256 `e0547cfeb8d4ad8266c6610793fbd172b3a93cd00661c806b465cb7ad73deaa1`, output schema SHA-256 `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`.
**Production baseline:** the harness commit will descend from `b34b987454c942965fa09a556725693896ecc426` (locus policy `e0f5e42` + tripwire repair). The exact harness SHA is fixed at seal time (`harness_code_sha`).
**Provider configuration:** provider `xai`, model `grok-4.6`, reasoning effort `high`, `GRPC_DNS_RESOLVER=native` — identical to the sealed 9P3 configuration; there is no scientific reason to vary it.
**Predecessor (never rerun, never modified):** 9P3 `intent-v2-long-horizon-bounded-memory-v1` — seal `c3eceae506034345e5eece8c5f314c0db6cebc21`, raw run `f045612e9ec9917b73649175cf08f91f087f2828`, adjudication `3c30c16193dae6a9a03fe630f2ca33bf2a2e8c13`.

---

## 1. Objective

Falsify, on the live model under the production two-call protocol, that the successor semantic policy `intent-v2-locus-v1` produces the correct **address identity** and **claim lifecycle** for the four semantic classes — restatement, compatible extension, correction, distinct locus — with both locus errors made deterministically visible:

- **over-splitting** — a new compatible proposition about a known locus creates a new address (the 9P3 contrastive-arm failure class);
- **under-splitting** — a proposition answering a different question is merged into a known address because the subject is related.

This is a follow-up validation experiment, not a rerun of 9P3. It asks nothing about token economy, bounded growth, reconstruction or long-horizon drift; 9P3 answered those and its frozen artifacts are the evidence. It asks exactly one question: does the live model, given the locus policy, do the right thing in each class — twice, in unrelated wording.

## 2. Hypotheses (all falsifiable per case; all-or-nothing)

| id | hypothesis | falsified by |
|---|---|---|
| H0 | **Creation granularity.** A seed delta of four documents, each about one locus, yields exactly four addresses, one live claim each, with locus-level facets. | any extra or missing address; a facet that names the first claim's aspect rather than the locus (architect) |
| H1 | **No over-splitting.** A genuinely new proposition compatible with a known locus's current claim is asserted as an additional claim at that same address; the existing claim stays current; no address is created; nothing is superseded. | a `CREATE_ADDRESS` citing the revised item; a missing additional claim; a supersession |
| H2 | **No under-splitting.** A proposition answering a different question is created as a new address even though it shares the subject and the document of a known locus. | the proposition bound or asserted at the known address; no `CREATE_ADDRESS` |
| H3 | **Restatement is not re-asserted.** A rewording of a current claim yields `SUPPORTS_CLAIM` of that claim and no new claim, no new address. | any `ASSERT_CLAIM` citing the restated item; a structural duplicate refusal |
| H4 | **Correction stays governed.** An incompatible value yields exactly one new claim at the same address plus one `SUPERSEDE` of the old claim's `created_by_judgment_id`, which remains pending (no human); no `CONFLICTS_WITH` in its place. | a missing or mis-targeted supersede; a conflict instead of a correction; an applied model supersede |

## 3. Semantic classes and the locus law being tested

From the locus policy (spec-level restatement, not prompt text): a **semantic address** is a stable locus — one subject and the one stable question about that subject; a **semantic claim** is one proposition within that locus, carried by its own predicate; several compatible claims may be current at one address; a new proposition never by itself creates an address; sharing a subject never by itself merges loci. The four classes:

| class | same locus? | current claims | required output |
|---|---|---|---|
| restatement | yes | unchanged | `BIND` + `SUPPORTS_CLAIM` |
| compatible extension | yes | preserved + one added | `BIND` + `ASSERT_CLAIM` (new predicate), no `SUPERSEDE` |
| correction | yes | one replaced (governed) | `BIND` + `ASSERT_CLAIM` + `SUPERSEDE` (pending) |
| distinct locus | no | — | `CREATE_ADDRESS` + `ASSERT_CLAIM` there |

The model is never told which class an item belongs to (§9).

## 4. Replicates

Two **independently authored** ledgers instantiate the same six case slots (seed + five revision cases) in unrelated domains with different documentation styles, sentence structures and concepts. They are not noun/value substitutions of one template: ledger α is written as normative rulebook sections; ledger β is written as an operations runbook in question/answer and behaviour/reason form. The semantic expectations (§6) are structurally identical.

| slot | class | ledger α (Keyring scheduler) | ledger β (Relay message pipeline) |
|---|---|---|---|
| S01 | seed: four loci | credential revocation; retry timing; worker lease; execution time limit | consumer acknowledgement; delivery ordering; subscription lease; delivery deadline |
| V01 | compatible extension | revoking an already-revoked credential is idempotent | acknowledgement also releases the message's reserved storage slot |
| V02 | compatible extension, different facet of the same locus | retry jitter capped at 500 ms | ordering is preserved across a redelivery |
| V03 | distinct locus, same subject, same document | audit records of job execution retained 30 days (inside the retry document) | delivery receipts kept 14 days (inside the ordering document) |
| V04 | restatement | lease lasts 90 s → one and a half minutes | renew within 10 minutes → at least once every 600 seconds |
| V05 | correction | time limit 30 s → 45 s | dead-letter deadline 24 h → 48 h |

Each ledger is a fresh project, fresh event store, fresh governor: `PROJ-LV-ALPHA` scope `keyring`; `PROJ-LV-BETA` scope `relay`. Nothing is shared between ledgers except the reasoner instance's budget.

## 5. Corpus (frozen; byte-exact in `manifest.json` as evidence records)

Evidence ids: `EV-LV-<ledger><doc><T>` (e.g. `EV-LV-A1-T1`, `EV-LV-B2-T2`). Every T2 item carries `supersedes_evidence_id` = its T1 item and the same `artifact_ref`. Source kind `DOCUMENT`; source ref `experiment://locus-validation/<ledger>/<T>/<doc>`.

### 5.1 Ledger α — Keyring scheduler (normative rulebook style)

**A1 — `keyring/spec/credential-revocation.md`**

T1 (`EV-LV-A1-T1`):
```
## Credentials — revocation

A client credential can be revoked by its owner or by an operator. Revocation takes
effect immediately and cannot be undone by the client.

Normative rule
1. After a credential has been revoked, no authentication attempt that presents it may
   succeed.

Example
Credential K-17 is revoked at 09:00:00. A login presenting K-17 at 09:00:30 is refused.
```

T2 (`EV-LV-A1-T2`, supersedes `EV-LV-A1-T1`):
```
## Credentials — revocation

A client credential can be revoked by its owner or by an operator. Revocation takes
effect immediately and cannot be undone by the client. Because owner tooling retries
its own requests, the same revocation is frequently submitted more than once.

Normative rule
1. After a credential has been revoked, no authentication attempt that presents it may
   succeed.
2. A revocation received for a credential that is already revoked leaves the credential
   revoked and changes nothing else about it.

Example
Credential K-17 is revoked at 09:00:00. A login presenting K-17 at 09:00:30 is refused.
A second revocation of K-17 arrives at 09:05:00; K-17 remains revoked and nothing else
about K-17 changes.
```

**A2 — `keyring/spec/retry-timing.md`**

T1 (`EV-LV-A2-T1`):
```
## Job execution — retry timing

When an execution of a job fails, the scheduler retries the job later rather than at
once, so that a struggling dependency is not hammered.

Normative rule
1. The delay before each retry is double the delay before the previous retry, starting
   from two seconds for the first retry.

Example
Job J-4 fails three times; the scheduler waits 2 s, then 4 s, then 8 s before each
retry.
```

T2 (`EV-LV-A2-T2`, supersedes `EV-LV-A2-T1`):
```
## Job execution — retry timing

When an execution of a job fails, the scheduler retries the job later rather than at
once, so that a struggling dependency is not hammered. To keep many failing jobs from
retrying in lockstep, a small random jitter is added to every retry delay.

Normative rule
1. The delay before each retry is double the delay before the previous retry, starting
   from two seconds for the first retry.
2. A random jitter is added to each retry delay; the jitter never exceeds 500
   milliseconds.

Example
Job J-4 fails three times; the scheduler waits 2 s, then 4 s, then 8 s before each
retry, each wait lengthened by at most half a second of jitter.

## Job execution — audit trail

Every execution of a job writes an audit record when it ends.

Normative rule
3. Audit records of job execution are retained for 30 days after they are written and
   are then deleted.

Example
An audit record written on 1 March is deleted on 31 March.
```

**A3 — `keyring/spec/worker-lease.md`**

T1 (`EV-LV-A3-T1`):
```
## Worker lease — duration

A worker holds a lease on the job it is executing so that no other worker picks the
same job up.

Normative rule
1. A lease lasts 90 seconds from the moment it is granted.

Example
A lease granted at 10:00:00 expires at 10:01:30.
```

T2 (`EV-LV-A3-T2`, supersedes `EV-LV-A3-T1`):
```
## Worker lease — duration

A worker holds a lease on the job it is executing so that no other worker picks the
same job up.

Normative rule
1. A lease is valid for one and a half minutes, counted from the moment it is granted.

Example
A lease granted at 10:00:00 is no longer valid after 10:01:30.
```

**A4 — `keyring/spec/execution-time-limit.md`**

T1 (`EV-LV-A4-T1`):
```
## Execution — time limit

A stalled execution must not hold its worker indefinitely.

Normative rule
1. A single execution may run for at most 30 seconds; when the limit is reached the
   execution is stopped and recorded as a failure.

Example
An execution that starts at 11:00:00 and is still running at 11:00:30 is stopped and
recorded as failed.
```

T2 (`EV-LV-A4-T2`, supersedes `EV-LV-A4-T1`):
```
## Execution — time limit

A stalled execution must not hold its worker indefinitely.

Normative rule
1. A single execution may run for at most 45 seconds; when the limit is reached the
   execution is stopped and recorded as a failure.

Example
An execution that starts at 11:00:00 and is still running at 11:00:45 is stopped and
recorded as failed.
```

### 5.2 Ledger β — Relay message pipeline (operations runbook style)

**B1 — `relay/runbook/acknowledgement.md`**

T1 (`EV-LV-B1-T1`):
```
# Consumer acknowledgement

Q: What does acknowledging a message do?
A: The message is removed from that consumer's pending set. Relay will not deliver it
to that consumer again.

Q: Is acknowledgement required?
A: Yes. Until a message is acknowledged it stays pending for the consumer that
received it.
```

T2 (`EV-LV-B1-T2`, supersedes `EV-LV-B1-T1`):
```
# Consumer acknowledgement

Q: What does acknowledging a message do?
A: The message is removed from that consumer's pending set. Relay will not deliver it
to that consumer again. Acknowledging also releases the storage slot that was reserved
for the message while it was pending, so the slot can be reused by later messages.

Q: Is acknowledgement required?
A: Yes. Until a message is acknowledged it stays pending for the consumer that
received it.
```

**B2 — `relay/runbook/delivery-order.md`**

T1 (`EV-LV-B2-T1`):
```
# Delivery ordering

Behaviour: Messages published by one producer are delivered to a consumer in the order
in which they were published.

Reason: Consumers rebuild state by replaying messages, and an out-of-order replay would
corrupt that state.
```

T2 (`EV-LV-B2-T2`, supersedes `EV-LV-B2-T1`):
```
# Delivery ordering

Behaviour: Messages published by one producer are delivered to a consumer in the order
in which they were published.

Behaviour: Ordering survives a redelivery. When a message from a producer is
redelivered, it is delivered before any message that the same producer published after
it.

Reason: Consumers rebuild state by replaying messages, and an out-of-order replay would
corrupt that state.

# Delivery receipts

Behaviour: Relay keeps a receipt for every delivery it makes. Receipts are kept for 14
days and are then discarded.

Reason: Operators investigate delivery disputes within two weeks; older receipts are
never consulted.
```

**B3 — `relay/runbook/subscription-lease.md`**

T1 (`EV-LV-B3-T1`):
```
# Subscription lease

Q: How long does a subscription stay alive without a renewal?
A: A subscription expires unless the consumer renews it within 10 minutes of the
previous renewal.
```

T2 (`EV-LV-B3-T2`, supersedes `EV-LV-B3-T1`):
```
# Subscription lease

Q: How long does a subscription stay alive without a renewal?
A: A consumer must renew its subscription at least once every 600 seconds, measured
from the previous renewal; otherwise the subscription lapses.
```

**B4 — `relay/runbook/delivery-deadline.md`**

T1 (`EV-LV-B4-T1`):
```
# Delivery deadline

Behaviour: A message that has not been delivered within 24 hours of being published is
moved to the dead-letter store and is not delivered afterwards.

Reason: A message older than that is stale for every known consumer.
```

T2 (`EV-LV-B4-T2`, supersedes `EV-LV-B4-T1`):
```
# Delivery deadline

Behaviour: A message that has not been delivered within 48 hours of being published is
moved to the dead-letter store and is not delivered afterwards.

Reason: A message older than that is stale for every known consumer.
```

### 5.3 Corpus discipline

- 16 evidence items (8 per ledger); `corpus_sha256` = canonical SHA-256 of the ordered evidence records, recorded in the manifest and re-verified by preflight.
- Every item is realistic evolving documentation: no item names a semantic class, an expected action, a case id or an evaluator term.
- Words that are part of the hidden answer key never appear in a document (`EXTENSION`, `RESTATEMENT`, `CORRECTION`, `DISTINCT`, case ids, outcome names).
- No 9P3 wording, entity, evidence id, locus label or checkpoint id is reused.

## 6. Expected lifecycle state (per ledger; identical structure for α and β)

Notation: `D1..D4` = the four documents; `X1..X4` = the addresses created from them at T1; `D2'` = the revised second document, which carries V02 (extension) and V03 (distinct locus).

**After T1 (seed, S01):**
- exactly 4 active in-scope addresses `X1..X4`;
- each `Xi` has exactly one live claim citing `Di-T1`;
- Call 1 applied exactly 4 `CREATE_ADDRESS` (one per item) and 0 `BIND_TO_ADDRESS`; Call 2 applied exactly 4 `ASSERT_CLAIM`; 0 `SUPERSEDE`, 0 `CONFLICTS_WITH`, 0 rejections.

**After T2 (revision):**
- exactly **5** active in-scope addresses: `X1..X4` and one new address `X5` (V03);
- `X1` (V01): 2 live claims — the T1 claim (same id, still live) and exactly one new claim citing `D1'`; no supersede targets `X1`'s claims;
- `X2` (V02): 2 live claims — the T1 claim and exactly one new claim citing `D2'`;
- `X5` (V03): exactly 1 live claim citing `D2'`; created by a `CREATE_ADDRESS` citing `D2'`;
- `X3` (V04): exactly 1 live claim (the T1 claim); at least one `SUPPORTS_CLAIM` of it citing `D3'`; **no** `ASSERT_CLAIM` cites `D3'`;
- `X4` (V05): 2 live claims — the T1 claim (still live: no human authority exists) and exactly one new claim citing `D4'`; exactly one `SUPERSEDE` whose `target_judgment_id` equals the T1 claim's `created_by_judgment_id`, admitted `REQUIRE_SECOND_LENS` and never applied; 0 `CONFLICTS_WITH`;
- Call-1 drafts of T2: exactly one `BIND_TO_ADDRESS` per revised document to its own T1 address (`D1'→X1`, `D2'→X2`, `D3'→X3`, `D4'→X4`) and exactly one `CREATE_ADDRESS`, citing `D2'`;
- `human_authorizations == 0`; `pending_judgment_ids` == the single V05 supersede.

## 7. Assertions

### 7.1 Deterministic structural assertions (computed by code from the frozen raw artifacts; no wording is read)

| case | assertion set |
|---|---|
| S01 | `len(addresses) == 4`; one live claim per address; the 4 creates cite distinct items; 0 binds; 0 supersede/conflict; 0 rejected admissions |
| V01 | exactly one Call-1 draft cites `D1'` and it is a `BIND` to `X1`; `X1` live claims == {T1 claim, one new claim citing `D1'`}; no `SUPERSEDE` targets `X1`'s claims; total address count unchanged by `D1'` |
| V02 | same shape for `D2'` at `X2` (the bind and the new claim) |
| V03 | exactly one `CREATE_ADDRESS` in Call 1 of T2 and it cites `D2'`; total addresses == 5; the created address has exactly one live claim citing `D2'`; no claim citing `D2'` at any address other than `X2` and `X5` |
| V04 | exactly one Call-1 draft cites `D3'` and it is a `BIND` to `X3`; `X3` live claims == {T1 claim}; ≥ 1 `SUPPORTS_CLAIM` of that claim citing `D3'`; 0 `ASSERT_CLAIM` citing `D3'`; 0 structural duplicate rejections in the run |
| V05 | exactly one Call-1 draft cites `D4'` and it is a `BIND` to `X4`; `X4` live claims == {T1 claim, one new claim citing `D4'`}; exactly one `SUPERSEDE` in the run, target == T1 claim's `created_by_judgment_id`, route `REQUIRE_SECOND_LENS`, not applied; 0 `CONFLICTS_WITH`; `human_authorizations == 0` |
| run | 8 request records total, 4 per ledger, call numbers (1, 2) per delta; 0 judge calls; 0 retries; request-only reference law holds for every call; replay of each ledger reproduces its final state and view; receipts, requests and ledger events reconcile; identity guard never tripped; cost ≤ ceiling |

Deterministic failure tags (recorded per case when the assertion set fails; several may apply): `OVER_SPLIT` (a `CREATE` cites a revised item other than the V03 creation), `UNDER_SPLIT` (V03 proposition bound/asserted at `X2` or no creation), `MISSING_EXTENSION` (no new claim at `X1`/`X2`), `DUPLICATE_ASSERTION` (an `ASSERT` cites `D3'`, or any structural duplicate refusal), `MISSING_SUPERSEDE`, `WRONG_SUPERSEDE_TARGET`, `CONFLICT_INSTEAD_OF_CORRECTION`, `UNGOVERNED_SUPERSEDE` (a model supersede applied), `WRONG_BIND` (a revised item bound to an address other than its T1 address), `EXTRA_DRAFT` (any other unexpected draft citing the item).

### 7.2 Architect semantic assertions (offline, after the raw commit; binary per item; only where wording is model-chosen)

| id | question answered by the architect from the frozen drafts/claims |
|---|---|
| A-S01 | Do the four seed facets name the locus-level question (e.g. what revocation does; how retries are timed; how long a lease lasts; how long an execution may run) rather than the first claim's specific value? |
| A-V01 | Does the new claim at `X1` state the V01 proposition (α: repeated revocation is idempotent and leaves the credential revoked; β: acknowledgement releases the reserved storage slot)? |
| A-V02 | Does the new claim at `X2` state the V02 proposition (α: jitter capped at 500 ms; β: ordering preserved across a redelivery)? |
| A-V03 | Do `X5`'s descriptors and claim denote the V03 locus (α: audit-record retention, 30 days; β: delivery-receipt retention, 14 days) and nothing about `X2`'s question? |
| A-V05 | Does the new claim at `X4` state the corrected value (α: 45 seconds; β: 48 hours)? |

V04 needs no semantic assertion (its correctness is fully structural). A case whose structural set passes but whose semantic assertion is answered "no" is a FAIL. The architect answers only these questions; no other grading exists.

## 8. Integrity invariants

**Preflight gates (offline, deterministic; evaluated by `--preflight-only` and again, from scratch, by `--live`):**

1. `head_equals_final_seal` — HEAD == `--frozen-sha`; its single parent == `manifest.harness_code_sha`; `parent..HEAD` adds exactly `manifest.json` and `expectations.json`.
2. `worktree_clean`.
3. `seal_descends_from_baseline` — `b34b987…` is an ancestor of the seal.
4. `locus_policy_frozen` — in-process `LOCUS_POLICY_VERSION == "intent-v2-locus-v1"`; `XAILocusSemanticReasoner.policy_version` equals it.
5. `locus_prompt_hash_frozen` — sha256 of the in-process `LOCUS_SYSTEM_INSTRUCTION` == manifest == `e0547cfe…deaa1`.
6. `output_schema_hash_frozen` — `ffc6946a…6851`.
7. `historical_prompts_unchanged` — `SYSTEM_INSTRUCTION` sha `24435801…` and `CONTRASTIVE_SYSTEM_INSTRUCTION` sha `a68b969b…` unchanged (the successor policy did not alter its ancestors).
8. `model_configuration_frozen` — provider, model, reasoning effort, contrastive path (`include_comparison_context is True`) equal the manifest.
9. `calls_per_delta_is_2`.
10. `evidence_manifest_frozen` — in-process corpus records == manifest evidence; `corpus_sha256` matches.
11. `ceilings_frozen` — 8 / 0 / 0 / 0 / 0 / 2.00.
12. `expectations_frozen` — on-disk `expectations.json` canonical hash == manifest `expectations_sha256` == in-process expectations document.
13. `answer_key_not_imported_by_request_path` — AST gate over the experiment's request-path modules (corpus, protocol, runner, recording wrapper): none imports the expectations module or any grading helper.
14. `leakage_gate_passes` — §9.
15. `grpc_dns_resolver_is_native`.
16. `historical_artifacts_unchanged` — for each of the seven frozen experiment directories (the six 9P3 listed dirs plus `docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/`): tree at the approved design base == tree at the seal == manifest.
17. `predecessor_commits_unchanged` — `f045612…` and `3c30c16…` are ancestors of the seal; no path under the 9P3 directory changed since `3c30c16…`.
18. `no_raw_artifacts_exist` — none of the raw artifact paths (§13) exists under the experiment directory.
19. `regression_suites_pass` — the locus policy, admission and lifecycle unit suites and this experiment's unit suite pass.

All 19 gates are pure: no provider client, no reasoner construction, no network, no key read, no write.

**Post-run deterministic verdicts (computed once, from the run in memory, frozen into `verdicts.json` at raw freeze):** `L1` two calls per delta; `L2` no retry / judge / third call; `L3` request-only reference law (the 9P3 `request_only_reference_check` over `RequestRecord` + `RequestReferenceSnapshot` pairs); `L4` replay equality per ledger; `L5` receipts/requests/events reconciliation; `L6` no model-originated `SUPERSEDE` applied and `human_authorizations == 0`; `L7` identity guard never tripped; `L8` cost within ceiling; `L9` the deterministic case assertion sets of §7.1. Each verdict records `passed`, `detail`, `applies_to` (`("alpha",)`, `("beta",)` or both) and `failed_ledgers` — the observed attribution law of 9P3 spec §12.1, with ledgers in place of arms.

## 9. Leakage strategy

The typed leakage matcher and hash recipe of 9P3 spec §15.1 are reused by import:

- **PROSE needles** (C1 normalisation, substring): every expected-outcome sentence of `expectations.json` (§6, §7.1 rows rendered as prose), every semantic-assertion question of §7.2, and the hypothesis sentences of §2.
- **CANONICAL_LABEL needles** (exact case-sensitive standalone tokens): `LOCUS_POLICY_VALIDATED`, `LOCUS_POLICY_NOT_VALIDATED`, `EXPERIMENT_INCONCLUSIVE`, every failure tag of §7.1, `RESTATEMENT`, `COMPATIBLE_EXTENSION`, `CORRECTION`, `DISTINCT_LOCUS`, `L1`…`L9`, `A-S01`…`A-V05`.
- **CHECKPOINT_LABEL needles**: `S01`, `V01`…`V05`.
- **Skeletons** (real assembly + real `render_request` with the locus prompt, opaque `<EVIDENCE:EV-LV-…>` content, real ids/lineage): `SEED_CALL1`, `SEED_CALL2`, `REVISION_CALL1`, `REVISION_CALL2` for each ledger shape — eight skeletons; haystack = `LOCUS_SYSTEM_INSTRUCTION + "\n" + rendered request` after evidence-content substitution; no evidence-id substitution.
- The sealed `leakage_needle_set_sha256` is recorded in the manifest. Gate 14 fails closed on the first match.
- The production prompt legitimately contains the lower-case words "restatement", "correction", "compatible extension" and "distinct locus" as its ordinary lifecycle vocabulary; the typed matcher does not treat them as leaks (CANONICAL_LABEL matches only the exact upper-case tokens). No request, document or prompt ever states which class or action a particular item calls for.

## 10. Identity state machine (Amendment 1 — non-consuming preflight)

```
UNSEALED ──prepare──▶ SEALED ──(preflight-only, any number of times; no write)──▶ SEALED
SEALED ──live: all 19 gates pass, key present, reasoner constructed & guarded──▶ CONSUMED
CONSUMED ──run (4 calls per ledger, fail-fast)──▶ RAW_FROZEN (raw commit)
RAW_FROZEN ──offline adjudication──▶ ADJUDICATED (adjudication commit)
```

- **`--preflight-only`** evaluates every gate of §8, prints the preflight document (gates, `all_passed`, `frontier_calls: 0`, `observed_grpc_dns_resolver`), **writes nothing**, constructs no client or reasoner, never reads the provider key, and never consumes identity. It may be run repeatedly; a failure is correctable (fix, re-preflight).
- **`--live`** re-runs the complete preflight from scratch in-process (never trusting an earlier preflight-only run). A failed gate exits 3 with zero provider calls, zero key reads, nothing written and identity **not** consumed. Only after all 19 gates pass does it read `XAI_API_KEY`; a missing/empty key is a refusal (exit 2), nothing written, not consumed. It then constructs the three-layer reasoner (locus adapter → recording/budget wrapper → identity guard) with **no call**; an identity mismatch at construction is a refusal (exit 2), nothing written, not consumed.
- **Consumption** happens at exactly one point: immediately before the first provider-call attempt, the runner atomically writes `consumption.json` (seal sha, harness sha, policy version, prompt hash, model configuration, UTC timestamp — never the key or any secret-shaped value) and `preflight.json` (the passing preflight document). From this instant the experiment identity is permanently consumed: any later `--live` against this directory refuses (exit 2) because raw artifacts exist, regardless of what happened next.
- Everything after consumption — provider error, timeout, `SemanticOutputError`, identity drift on a later call, budget exhaustion, interrupt, partial completion, later integrity failure — is recorded, the aborted raw tree is written in full, exit 4, and the scientific outcome is `EXPERIMENT_INCONCLUSIVE`. No replacement run, no retry, no second `--live`, ever.
- Tests must prove: preflight-only writes nothing and reads no key across every gate outcome; live with a failing gate writes nothing and consumes nothing; live with a missing key or construction-time identity mismatch writes nothing and consumes nothing; live with passing gates writes `consumption.json` + `preflight.json` before the first forwarded call and refuses any later live invocation; every post-consumption failure class writes the full raw tree and exits 4.

## 11. Raw-freeze / adjudication state machine (Amendment 2)

```
SEAL COMMIT (manifest.json, expectations.json)
   ↓ --live (exactly once)
RAW RUN COMMIT (every raw artifact of §13; deterministic verdicts and case assertions filled;
                semantic fields null; experiment outcome null)
   ↓ offline architect adjudication (no provider, no key)
ADJUDICATION COMMIT (only verdicts.json and report.md change)
```

- The **raw run commit** contains only facts generated by the live run and deterministic checks: provider responses (drafts, receipts), decisions, ledgers, state snapshots, request records with reference snapshots, measurements, the L1–L9 verdicts, and the §7.1 case assertion results with their failure tags. In `verdicts.json` the fields `semantic_assertions` (A-S01…A-V05 per ledger), `semantic_notes`, `case_outcomes` (final PASS/FAIL per case) and `experiment_outcome` are `null`; `report.md` states `experiment_outcome = null (architect adjudication pending)`. The live runner never computes `LOCUS_POLICY_VALIDATED` / `LOCUS_POLICY_NOT_VALIDATED`; it may only record `EXPERIMENT_INCONCLUSIVE` when rule 0 (§14) already holds from deterministic facts, and even then `case_outcomes` stay null.
- **Adjudication** runs offline after the raw commit is verified immutable. Its writer refuses unless: HEAD == the exact raw-run commit sha; the worktree is clean; every raw artifact's current bytes equal `git show <raw sha>:<path>`; no provider key is present in its environment (presence-only check) and no provider/model client is constructed. It reads only the frozen evidence, takes the architect's binary answers to §7.2, computes the final case outcomes and the experiment outcome by §14, and rewrites **only** `verdicts.json` (filling the null fields, keeping every raw entry semantically identical) and `report.md`. Every other raw file must be byte-identical afterwards; the writer proves this before returning. It is write-once: a second adjudication is refused.
- Tests must prove: the raw writer leaves the semantic fields null and never references the outcome names; adjudication refuses on HEAD mismatch, dirt, any differing or missing raw byte, or a present provider key; a successful adjudication changes exactly `verdicts.json` and `report.md`.

## 12. Budgets and ceilings (frozen in the manifest)

| ceiling | value |
|---|---|
| `max_frontier_calls` | **8** (2 ledgers × 2 deltas × 2 calls; the 9th call is refused before forwarding) |
| `max_judge_calls` | 0 |
| `max_semantic_retries` | 0 |
| `max_same_cell_reruns` | 0 |
| `max_human_authorizations` | 0 |
| `max_provider_cost_usd` | **2.00** (hard; the budget wrapper refuses the next call once the recorded cost exceeds it) |

Projection from the frozen 9P3 measurements (contrastive-arm calls: mean $0.056, maximum $0.062 in the small-context window, ~86 s wall each): expected ≈ $0.35–0.50 and ≈ 12 minutes for the 8 calls.

## 13. Artifact layout

`docs/superpowers/experiments/2026-09-15-locus-validation-v1/`

Seal (2 files): `manifest.json`, `expectations.json`.

Raw (write-once, all-or-nothing, secret-scanned; 21 paths):
```
consumption.json          identity consumption record (§10)
preflight.json            the passing preflight document evaluated inside --live
measurements.json         one row per call: tokens, cost, wall clock, request chars
verdicts.json             L1–L9 + §7.1 case assertions; semantic fields null
report.md                 deterministic summary; outcome pending line
L-alpha/requests.json     {"record": RequestRecord, "reference_snapshot": RequestReferenceSnapshot} per call
L-alpha/drafts.json       raw draft payloads as returned by the model
L-alpha/receipts.json     provider receipts
L-alpha/decisions.json    admission decisions per call
L-alpha/ledger.json       every durable event
L-alpha/state_T1.json     semantic state + derived view after the seed delta
L-alpha/state_T2.json     semantic state + derived view after the revision delta
L-alpha/result.json       ledger status, error (redacted), call count, cost
L-beta/…                  the same eight files
```
A ledger that never ran (fail-fast after α) still gets its eight files with status `NOT_RUN` and empty content, so the frozen shape is constant. Secret-shaped scientific request material refuses the whole write (never redacted); only diagnostic text is redacted.

Adjudication: modifies only `verdicts.json` and `report.md`.

## 14. Scoring

**Rule 0 — experiment invalidity (deterministic, above semantic judgment):** any preflight gate failed inside `--live` (cannot happen after consumption — a failed gate never consumes), any abort after consumption (provider/runtime/model-contract/identity/budget/interrupt), any of L1–L8 failed, any raw-artifact preservation failure, or a missing/corrupted raw artifact → `EXPERIMENT_INCONCLUSIVE`. Case outcomes are still recorded where computable but never aggregated into a validation verdict.

**Per case (12 instances: S01, V01–V05 × α, β):** PASS iff every deterministic assertion of its §7.1 row holds **and** its §7.2 semantic assertion (where one exists) is answered "yes". A structurally correct but semantically wrong result is a FAIL, never `INCONCLUSIVE`.

**Experiment outcome (adjudication only):**
- all 12 case instances PASS → `LOCUS_POLICY_VALIDATED`;
- any case instance FAILS → `LOCUS_POLICY_NOT_VALIDATED`, with every failing case's deterministic tags and the architect's answers listed; replicate disagreement (α passes, β fails, or vice versa) is `NOT_VALIDATED` and is itself the finding "not reliable across wording".

No averaging, no partial credit, no favoured outcome, no thresholds. The vocabulary is exactly `LOCUS_POLICY_VALIDATED`, `LOCUS_POLICY_NOT_VALIDATED`, `EXPERIMENT_INCONCLUSIVE`.

## 15. Abort semantics

- Before consumption: refusals (exit 2) and preflight failures (exit 3) write nothing and consume nothing.
- After consumption: the first operational failure stops the walk; the failing ledger records its cells to that point (`FAILED`), the unreached ledger is `NOT_RUN`; deterministic verdicts are computed over what exists; the full raw tree is written; exit 4; rule 0 applies. Nothing is retried; the same seal is never run again. A raw-preservation failure after any forwarded call (secret-shaped request, binding failure, stray target) is an operational failure: exit 4, no second write attempt, no sanitised or replacement run, `preflight.json`/`consumption.json` untouched.
- A fresh attempt requires a new experiment version with a new seal; this document's identity is single-use.

## 16. Preregistration contents

`manifest.json`: `experiment_version`, `artifact_format_version = 1`, `harness_code_sha`, `baseline_sha = b34b987…`, `final_seal_rule`, `spec_path` (this file), `spec_sha256`, `provider`, `model`, `reasoning_effort`, `grpc_dns_resolver`, `policy_version`, `prompt_sha256`, `historical_prompt_sha256s` (9p-v4, 9p2-v1), `output_schema_sha256`, `calls_per_delta`, `ledgers` (ids, project ids, scopes, document order), `evidence` (16 records, byte-exact), `corpus_sha256`, `leakage_needle_set_sha256`, `expectations_sha256`, `ceilings`, `historical_preservation_base_sha`, `historical_artifact_dirs` (seven), `historical_artifact_tree_hashes`, `predecessor_raw_run_sha = f045612…`, `predecessor_adjudication_sha = 3c30c16…`, `raw_artifact_paths` (21).

`expectations.json`: the hypotheses, the case table (§4), the expected lifecycle state (§6), the deterministic assertion sets and failure tags (§7.1), the semantic assertion questions (§7.2), the scoring rule and outcome vocabulary (§14), the identity and freeze state machines (§10–§11) as literal text. It is the hidden answer key: never imported by a request-path module, never rendered into a request, and the source of the PROSE needles.

## 17. Historical-preservation requirements

- The six 9P3-frozen directories and the 9P3 v1 directory itself are protected by gate 16 (tree equality at design base, seal and manifest) and gate 17 (the 9P3 raw and adjudication commits are ancestors and their tree is unchanged since `3c30c16…`).
- The 9P3 harness package, the 9P2 package, the longitudinal package and the production core are not modified by this experiment; the new code lives only under `src/foundry/experiments/locus_validation/`, two new scripts and new tests. Reuse is by import only (`RequestRecord`, `RequestReferenceSnapshot`, `request_only_reference_check`, the typed leakage matcher, canonical hashing, redaction, replay, `GateResult`/`all_passed`, `GitCliLike`). The 9P2 `RecordingReasoner` and 9P3 `BudgetedReasoner` are **not** reused: they pin the historical policies and would refuse the locus policy; the experiment carries its own small recording/budget wrapper.
- The historical prompts and policy versions are untouched (gate 7).

## 18. Exact call budget

| step | ledger | calls |
|---|---|---|
| seed delta (Call 1 + Call 2) | α | 2 |
| revision delta (Call 1 + Call 2) | α | 2 |
| seed delta | β | 2 |
| revision delta | β | 2 |
| **total = maximum** | | **8** |

No judge, no retry, no rerun, no third call, no human authorization. Cost ceiling **$2.00**.

## 19. Why this suffices

9P3 established that both persistent architectures are correct on restatement, correction, revert and no-op over sixteen versions and that the only persistent semantic failure was the compatible-extension class — in both arms, through the same missing locus/claim distinction. This experiment isolates that distinction under the successor policy: the four classes arrive together in production-realistic mixed deltas, twice in unrelated wording and documentation styles, with both locus errors deterministically visible and the lifecycle shape scored from frozen state. A pass in both replicates shows the C09 class is eliminable on the live model under the production protocol; a fail names the violated locus rule. 9P3 is never rerun and its evidence is never touched.

## 20. Design self-review record

1. No placeholder: every value, id, ceiling, path, hash and rule is fixed; the only value bound at seal time is `harness_code_sha` (and the derived `spec_sha256`, `corpus_sha256`, `expectations_sha256`, `leakage_needle_set_sha256`), which prepare records from the tree, never from a template.
2. No contradiction between §6, §7.1 and §14: every expected state has exactly one assertion row and one scoring consequence; V04 has no semantic assertion by design.
3. Ambiguity closed: consumption is one atomic write at one point (§10); the adjudication writer's allowed file set is exactly two files (§11); "the 9th call is refused before forwarding" fixes the ceiling semantics.
4. No 9P3 coupling: no 9P3 policy, class, schedule, locus, checkpoint, evidence id, arm, authority checkpoint or manifest key is reused; 9P3 identities appear only as frozen predecessors to be preserved (gates 16–17).
5. No experiment-specific leakage: the corpus contains no class name, action name, case id or evaluator term; the needle set covers every hidden sentence and token; the live prompt is the sealed production prompt, unchanged.
6. Preflight cannot consume identity: `--preflight-only` has no write path at all; in `--live` the only write before the first call is the consumption record, and it happens after every gate, the key check and construction have succeeded.
7. Adjudication cannot mutate raw evidence: it runs on a committed raw tree, proves byte-identity of every raw file before and after, and writes only `verdicts.json` and `report.md`.
8. Replicates are independently authored: α is a normative rulebook with rule lists and examples; β is a runbook in Q/A and behaviour/reason form; the V01 concepts differ (idempotent repeated revocation vs. storage-slot release), as do V02 (jitter cap vs. ordering across redelivery), V03 (audit records vs. delivery receipts), V04 (90 s ↔ 1.5 min vs. 10 min ↔ 600 s) and V05 (30→45 s vs. 24→48 h).
